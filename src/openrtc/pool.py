from __future__ import annotations

import importlib.util
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from livekit.agents import Agent, AgentServer, AgentSession, JobContext, JobProcess, cli

logger = logging.getLogger("openrtc")


@dataclass(slots=True)
class AgentConfig:
    """Configuration for a registered LiveKit agent.

    Args:
        name: Unique name used to identify and route to the agent.
        agent_cls: A ``livekit.agents.Agent`` subclass.
        stt: Speech-to-text provider string or provider instance.
        llm: Large language model provider string or provider instance.
        tts: Text-to-speech provider string or provider instance.
        greeting: Optional initial greeting reserved for future use.
    """

    name: str
    agent_cls: type[Agent]
    stt: Any = None
    llm: Any = None
    tts: Any = None
    greeting: str | None = None


class AgentPool:
    """Manage multiple LiveKit agents inside a single worker process."""

    def __init__(
        self,
        *,
        default_stt: Any = None,
        default_llm: Any = None,
        default_tts: Any = None,
        default_greeting: str | None = None,
    ) -> None:
        """Create a pool with shared defaults, prewarm, and a universal entrypoint.

        Args:
            default_stt: Default STT provider used when an agent does not override it.
            default_llm: Default LLM provider used when an agent does not override it.
            default_tts: Default TTS provider used when an agent does not override it.
            default_greeting: Default greeting used when an agent does not override it.
        """
        self._server = AgentServer()
        self._agents: dict[str, AgentConfig] = {}
        self._default_stt = default_stt
        self._default_llm = default_llm
        self._default_tts = default_tts
        self._default_greeting = default_greeting
        self._server.setup_fnc = self._prewarm

        @self._server.rtc_session()
        async def universal_session(ctx: JobContext) -> None:
            await self._handle_session(ctx)

    @property
    def server(self) -> AgentServer:
        """Return the underlying LiveKit ``AgentServer`` instance."""
        return self._server

    def add(
        self,
        name: str,
        agent_cls: type[Agent],
        *,
        stt: Any = None,
        llm: Any = None,
        tts: Any = None,
        greeting: str | None = None,
    ) -> AgentConfig:
        """Register an agent in the pool.

        Args:
            name: Unique name used for dispatch.
            agent_cls: Agent subclass to instantiate per session.
            stt: STT provider string or instance.
            llm: LLM provider string or instance.
            tts: TTS provider string or instance.
            greeting: Optional greeting reserved for later milestones.

        Returns:
            The created agent configuration.

        Raises:
            TypeError: If ``agent_cls`` is not a LiveKit ``Agent`` subclass.
            ValueError: If ``name`` is empty or already registered.
        """
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Agent name must be a non-empty string.")
        if normalized_name in self._agents:
            raise ValueError(f"Agent '{normalized_name}' is already registered.")
        if not isinstance(agent_cls, type) or not issubclass(agent_cls, Agent):
            raise TypeError("agent_cls must be a subclass of livekit.agents.Agent.")

        config = AgentConfig(
            name=normalized_name,
            agent_cls=agent_cls,
            stt=self._resolve_provider(stt, self._default_stt),
            llm=self._resolve_provider(llm, self._default_llm),
            tts=self._resolve_provider(tts, self._default_tts),
            greeting=self._resolve_greeting(greeting),
        )
        self._agents[normalized_name] = config
        logger.debug("Registered agent '%s'.", normalized_name)
        return config

    def discover(self, agents_dir: str | Path) -> list[AgentConfig]:
        """Discover agent modules from a directory and register them.

        Args:
            agents_dir: Directory containing Python files that define agent modules.

        Returns:
            The list of agent configurations registered from the directory.

        Raises:
            FileNotFoundError: If ``agents_dir`` does not exist.
            NotADirectoryError: If ``agents_dir`` is not a directory.
            RuntimeError: If a module cannot be loaded or contains no local ``Agent``
                subclass.
        """
        directory = Path(agents_dir).expanduser().resolve()
        if not directory.exists():
            raise FileNotFoundError(f"Agents directory does not exist: {directory}")
        if not directory.is_dir():
            raise NotADirectoryError(f"Agents path is not a directory: {directory}")

        discovered_configs: list[AgentConfig] = []
        for module_path in sorted(directory.glob("*.py")):
            if module_path.name == "__init__.py" or module_path.stem.startswith("_"):
                logger.debug("Skipping agent module '%s'.", module_path.name)
                continue

            module = self._load_agent_module(module_path)
            agent_cls = self._find_local_agent_subclass(module)
            agent_name = self._read_module_str(module, "AGENT_NAME") or module_path.stem
            config = self.add(
                agent_name,
                agent_cls,
                stt=getattr(module, "AGENT_STT", None),
                llm=getattr(module, "AGENT_LLM", None),
                tts=getattr(module, "AGENT_TTS", None),
                greeting=self._read_module_str(module, "AGENT_GREETING"),
            )
            logger.info(
                "Discovered agent '%s' from %s using class %s.",
                config.name,
                module_path,
                agent_cls.__name__,
            )
            discovered_configs.append(config)

        return discovered_configs

    def list_agents(self) -> list[str]:
        """Return registered agent names in registration order."""
        return list(self._agents)

    def run(self) -> None:
        """Run the LiveKit worker for the registered agents.

        Raises:
            RuntimeError: If no agents were registered before startup.
        """
        if not self._agents:
            raise RuntimeError("Register at least one agent before calling run().")
        cli.run_app(self._server)

    def _prewarm(self, proc: JobProcess) -> None:
        """Load shared runtime assets into ``proc.userdata`` once per worker."""
        silero_module, turn_detector_model = self._load_shared_runtime_dependencies()
        proc.userdata["vad"] = silero_module.VAD.load()
        proc.userdata["turn_detection"] = turn_detector_model()

    def _resolve_agent(self, ctx: JobContext) -> AgentConfig:
        """Resolve the agent for a session from metadata or fallback order.

        Args:
            ctx: LiveKit job context for the incoming room session.

        Returns:
            The selected agent configuration.

        Raises:
            RuntimeError: If no agents are registered.
            ValueError: If metadata references an unknown agent.
        """
        if not self._agents:
            raise RuntimeError("No agents are registered in the pool.")

        selected_name = self._agent_name_from_metadata(
            getattr(ctx.job, "metadata", None)
        )
        if selected_name is not None:
            return self._get_registered_agent(selected_name, source="job metadata")

        selected_name = self._agent_name_from_metadata(
            getattr(ctx.room, "metadata", None)
        )
        if selected_name is not None:
            return self._get_registered_agent(selected_name, source="room metadata")

        default_agent = next(iter(self._agents.values()))
        logger.debug(
            "No routing metadata found; defaulting to agent '%s'.", default_agent.name
        )
        return default_agent

    async def _handle_session(self, ctx: JobContext) -> None:
        """Create and start a LiveKit ``AgentSession`` for the resolved agent."""
        config = self._resolve_agent(ctx)
        session = AgentSession(
            stt=config.stt,
            llm=config.llm,
            tts=config.tts,
            vad=ctx.proc.userdata["vad"],
            turn_detection=ctx.proc.userdata["turn_detection"],
        )

        await session.start(agent=config.agent_cls(), room=ctx.room)
        await ctx.connect()

    def _agent_name_from_metadata(self, metadata: Any) -> str | None:
        if metadata is None:
            return None
        if isinstance(metadata, Mapping):
            value = metadata.get("agent")
            return value.strip() if isinstance(value, str) and value.strip() else None
        if isinstance(metadata, str):
            stripped = metadata.strip()
            if not stripped:
                return None
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError:
                logger.debug("Ignoring non-JSON metadata: %s", stripped)
                return None
            if isinstance(decoded, Mapping):
                value = decoded.get("agent")
                return (
                    value.strip() if isinstance(value, str) and value.strip() else None
                )
        return None

    def _get_registered_agent(self, name: str, *, source: str) -> AgentConfig:
        try:
            config = self._agents[name]
        except KeyError as exc:
            raise ValueError(f"Unknown agent '{name}' requested via {source}.") from exc
        logger.debug("Resolved agent '%s' via %s.", name, source)
        return config

    def _resolve_provider(self, value: Any, default_value: Any) -> Any:
        return default_value if value is None else value

    def _resolve_greeting(self, greeting: str | None) -> str | None:
        return self._default_greeting if greeting is None else greeting

    def _load_agent_module(self, module_path: Path) -> ModuleType:
        module_name = f"openrtc_discovered_{module_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not create import spec for {module_path}.")

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to import agent module '{module_path.name}': {exc}"
            ) from exc
        return module

    def _find_local_agent_subclass(self, module: ModuleType) -> type[Agent]:
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, Agent)
                and value is not Agent
                and value.__module__ == module.__name__
            ):
                return value

        raise RuntimeError(
            f"Module '{module.__name__}' does not define a local Agent subclass."
        )

    def _read_module_str(self, module: ModuleType, attribute_name: str) -> str | None:
        value = getattr(module, attribute_name, None)
        if value is None:
            return None
        if not isinstance(value, str):
            raise RuntimeError(
                f"Module '{module.__name__}' has non-string {attribute_name!r}: "
                f"{type(value).__name__}."
            )
        normalized_value = value.strip()
        if not normalized_value:
            raise RuntimeError(
                f"Module '{module.__name__}' defines empty {attribute_name!r}."
            )
        return normalized_value

    def _load_shared_runtime_dependencies(self) -> tuple[Any, type[Any]]:
        """Load the optional LiveKit runtime dependencies used during prewarm.

        Returns:
            A tuple of the imported Silero module and the multilingual turn detector
            model class.

        Raises:
            RuntimeError: If the required LiveKit plugins are not installed.
        """
        try:
            from livekit.plugins import silero
            from livekit.plugins.turn_detector.multilingual import MultilingualModel
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "OpenRTC requires the LiveKit Silero and turn-detector plugins. "
                "Install the package with livekit-agents[silero,turn-detector]."
            ) from exc

        return silero, MultilingualModel
