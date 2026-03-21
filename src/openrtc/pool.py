from __future__ import annotations

import importlib.util
import json
import logging
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from types import ModuleType
from typing import Any, TypeVar

from livekit.agents import Agent, AgentServer, AgentSession, JobContext, JobProcess, cli

logger = logging.getLogger("openrtc")

_AgentType = TypeVar("_AgentType", bound=type[Agent])
_AGENT_METADATA_ATTR = "__openrtc_agent_config__"
_METADATA_AGENT_KEYS = ("agent", "demo")


@dataclass(slots=True)
class _PoolRuntimeState:
    """Serializable runtime state shared with worker callbacks."""

    agents: dict[str, AgentConfig]


def _prewarm_worker(
    runtime_state: _PoolRuntimeState,
    proc: JobProcess,
) -> None:
    """Load shared runtime assets into ``proc.userdata`` once per worker."""
    if not runtime_state.agents:
        raise RuntimeError("Register at least one agent before calling run().")
    silero_module, turn_detector_model = _load_shared_runtime_dependencies()
    proc.userdata["vad"] = silero_module.VAD.load()
    proc.userdata["turn_detection"] = turn_detector_model()


async def _run_universal_session(
    runtime_state: _PoolRuntimeState,
    ctx: JobContext,
) -> None:
    """Dispatch a session through the owning ``AgentPool``."""
    if not runtime_state.agents:
        raise RuntimeError("No agents are registered in the pool.")
    config = _resolve_agent_config(runtime_state.agents, ctx)
    session = AgentSession(
        stt=config.stt,
        llm=config.llm,
        tts=config.tts,
        vad=ctx.proc.userdata["vad"],
        turn_detection=ctx.proc.userdata["turn_detection"],
        **config.session_kwargs,
    )

    await session.start(agent=config.agent_cls(), room=ctx.room)
    await ctx.connect()

    if config.greeting is not None:
        logger.debug("Generating greeting for agent '%s'.", config.name)
        await session.generate_reply(instructions=config.greeting)


@dataclass(slots=True)
class AgentConfig:
    """Configuration for a registered LiveKit agent.

    Args:
        name: Unique name used to identify and route to the agent.
        agent_cls: A ``livekit.agents.Agent`` subclass.
        stt: Speech-to-text provider string or provider instance.
        llm: Large language model provider string or provider instance.
        tts: Text-to-speech provider string or provider instance.
        greeting: Optional initial greeting played after the session connects.
        session_kwargs: Additional keyword arguments forwarded to ``AgentSession``.
    """

    name: str
    agent_cls: type[Agent]
    stt: Any = None
    llm: Any = None
    tts: Any = None
    greeting: str | None = None
    session_kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentDiscoveryConfig:
    """Optional metadata attached to an ``Agent`` class for discovery.

    Args:
        name: Optional explicit agent name. Falls back to the module filename when
            omitted.
        stt: Optional STT provider override.
        llm: Optional LLM provider override.
        tts: Optional TTS provider override.
        greeting: Optional greeting override.
    """

    name: str | None = None
    stt: Any = None
    llm: Any = None
    tts: Any = None
    greeting: str | None = None


def agent_config(
    *,
    name: str | None = None,
    stt: Any = None,
    llm: Any = None,
    tts: Any = None,
    greeting: str | None = None,
) -> Callable[[_AgentType], _AgentType]:
    """Attach OpenRTC discovery metadata to a standard LiveKit ``Agent`` class.

    Args:
        name: Optional explicit agent name used during discovery.
        stt: Optional STT provider override.
        llm: Optional LLM provider override.
        tts: Optional TTS provider override.
        greeting: Optional greeting override.

    Returns:
        A decorator that stores OpenRTC discovery metadata on the class.
    """

    metadata = AgentDiscoveryConfig(
        name=_normalize_optional_name(name, field_name="name"),
        stt=stt,
        llm=llm,
        tts=tts,
        greeting=_normalize_optional_name(greeting, field_name="greeting"),
    )

    def decorator(agent_cls: _AgentType) -> _AgentType:
        setattr(agent_cls, _AGENT_METADATA_ATTR, metadata)
        return agent_cls

    return decorator


class AgentPool:
    """Manage multiple LiveKit agents inside a single worker process.

    ``AgentPool`` keeps user-defined agents as standard LiveKit ``Agent``
    subclasses while centralizing the shared worker concerns OpenRTC adds:
    prewarm, routing, and per-agent session construction.
    """

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
            default_stt: Default STT provider used when an agent does not override
                it during ``add()`` or ``discover()``.
            default_llm: Default LLM provider used when an agent does not override
                it during ``add()`` or ``discover()``.
            default_tts: Default TTS provider used when an agent does not override
                it during ``add()`` or ``discover()``.
            default_greeting: Default greeting used when an agent does not override
                it during ``add()`` or ``discover()``.
        """
        self._server = AgentServer()
        self._agents: dict[str, AgentConfig] = {}
        self._runtime_state = _PoolRuntimeState(agents=self._agents)
        self._default_stt = default_stt
        self._default_llm = default_llm
        self._default_tts = default_tts
        self._default_greeting = default_greeting
        self._server.setup_fnc = partial(_prewarm_worker, self._runtime_state)
        self._server.rtc_session()(partial(_run_universal_session, self._runtime_state))

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
        session_kwargs: Mapping[str, Any] | None = None,
        **session_options: Any,
    ) -> AgentConfig:
        """Register an agent in the pool.

        Args:
            name: Unique name used for dispatch.
            agent_cls: Agent subclass to instantiate per session.
            stt: STT provider string or instance.
            llm: LLM provider string or instance.
            tts: TTS provider string or instance.
            greeting: Optional greeting played after the room connection completes.
            session_kwargs: Extra keyword arguments forwarded to ``AgentSession``.
                Common examples include ``preemptive_generation``,
                ``allow_interruptions``, ``min_endpointing_delay``,
                ``max_endpointing_delay``, and ``max_tool_steps``.
            **session_options: Additional ``AgentSession`` options passed
                directly to ``add()``. When the same option appears in both
                ``session_kwargs`` and direct keyword arguments, the direct
                keyword argument takes precedence.

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
            session_kwargs=self._merge_session_kwargs(
                session_kwargs=session_kwargs,
                direct_session_kwargs=session_options,
            ),
        )
        self._agents[normalized_name] = config
        logger.debug("Registered agent '%s'.", normalized_name)
        return config

    def discover(self, agents_dir: str | Path) -> list[AgentConfig]:
        """Discover agent modules from a directory and register them.

        Args:
            agents_dir: Directory containing Python files that define agent modules.
                Each discovered module must define a local LiveKit ``Agent``
                subclass. Optional OpenRTC overrides are read from the
                ``@agent_config(...)`` decorator attached to that class. When a
                field is omitted, ``AgentPool`` falls back to the module filename
                for the agent name and to pool defaults for providers and greeting.

        Returns:
            The list of agent configurations registered from the directory.

        Raises:
            FileNotFoundError: If ``agents_dir`` does not exist.
            NotADirectoryError: If ``agents_dir`` is not a directory.
            RuntimeError: If a module cannot be loaded or contains no local
                ``Agent`` subclass.
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
            metadata = self._resolve_discovery_metadata(module, agent_cls)
            agent_name = metadata.name or module_path.stem
            config = self.add(
                agent_name,
                agent_cls,
                stt=metadata.stt,
                llm=metadata.llm,
                tts=metadata.tts,
                greeting=metadata.greeting,
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

    def get(self, name: str) -> AgentConfig:
        """Return a registered agent configuration by name.

        Args:
            name: The registered agent name.

        Returns:
            The registered configuration.

        Raises:
            KeyError: If the agent name is unknown.
        """
        try:
            return self._agents[name]
        except KeyError as exc:
            raise KeyError(f"Unknown agent '{name}'.") from exc

    def remove(self, name: str) -> AgentConfig:
        """Remove and return a registered agent configuration.

        Args:
            name: The registered agent name.

        Returns:
            The removed configuration.

        Raises:
            KeyError: If the agent name is unknown.
        """
        try:
            removed = self._agents.pop(name)
        except KeyError as exc:
            raise KeyError(f"Unknown agent '{name}'.") from exc
        logger.debug("Removed agent '%s'.", name)
        return removed

    def run(self) -> None:
        """Run the LiveKit worker for the registered agents.

        Raises:
            RuntimeError: If no agents were registered before startup.
        """
        if not self._agents:
            raise RuntimeError("Register at least one agent before calling run().")
        cli.run_app(self._server)

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
        return _resolve_agent_config(self._agents, ctx)

    async def _handle_session(self, ctx: JobContext) -> None:
        """Create and start a LiveKit ``AgentSession`` for the resolved agent."""
        await _run_universal_session(self._runtime_state, ctx)

    def _resolve_provider(self, value: Any, default_value: Any) -> Any:
        return default_value if value is None else value

    def _resolve_greeting(self, greeting: str | None) -> str | None:
        return self._default_greeting if greeting is None else greeting

    def _merge_session_kwargs(
        self,
        session_kwargs: Mapping[str, Any] | None,
        direct_session_kwargs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        merged_kwargs: dict[str, Any] = {}
        if session_kwargs is not None:
            merged_kwargs.update(session_kwargs)
        if direct_session_kwargs is not None:
            merged_kwargs.update(direct_session_kwargs)
        return merged_kwargs

    def _resolve_discovery_metadata(
        self,
        module: ModuleType,
        agent_cls: type[Agent],
    ) -> AgentDiscoveryConfig:
        metadata = getattr(agent_cls, _AGENT_METADATA_ATTR, None)
        if metadata is not None:
            return metadata

        return AgentDiscoveryConfig()

    def _load_agent_module(self, module_path: Path) -> ModuleType:
        module_name = f"openrtc_discovered_{module_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not create import spec for {module_path}.")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            sys.modules.pop(module_name, None)
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


def _normalize_optional_name(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(
            f"OpenRTC metadata field {field_name!r} must be a string, got "
            f"{type(value).__name__}."
        )
    normalized_value = value.strip()
    if not normalized_value:
        raise RuntimeError(f"OpenRTC metadata field {field_name!r} cannot be empty.")
    return normalized_value


def _resolve_agent_config(
    agents: Mapping[str, AgentConfig],
    ctx: JobContext,
) -> AgentConfig:
    """Resolve the agent for a session from metadata or fallback order."""
    if not agents:
        raise RuntimeError("No agents are registered in the pool.")

    selected_name = _agent_name_from_metadata(getattr(ctx.job, "metadata", None))
    if selected_name is not None:
        return _get_registered_agent(agents, selected_name, source="job metadata")

    selected_name = _agent_name_from_metadata(getattr(ctx.room, "metadata", None))
    if selected_name is not None:
        return _get_registered_agent(agents, selected_name, source="room metadata")

    room_name = getattr(ctx.room, "name", None)
    if isinstance(room_name, str):
        for agent_name, config in agents.items():
            if room_name.startswith(f"{agent_name}-"):
                logger.info(
                    "Resolved agent '%s' via room name prefix from room '%s'.",
                    agent_name,
                    room_name,
                )
                return config

    default_agent = next(iter(agents.values()))
    logger.info("Resolved agent '%s' via default fallback.", default_agent.name)
    return default_agent


def _agent_name_from_metadata(metadata: Any) -> str | None:
    if metadata is None:
        return None
    if isinstance(metadata, Mapping):
        return _agent_name_from_mapping(metadata)
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
            return _agent_name_from_mapping(decoded)
    return None


def _agent_name_from_mapping(metadata: Mapping[str, Any]) -> str | None:
    for key in _METADATA_AGENT_KEYS:
        value = metadata.get(key)
        if isinstance(value, str):
            normalized_value = value.strip()
            if normalized_value:
                return normalized_value
    return None


def _get_registered_agent(
    agents: Mapping[str, AgentConfig],
    name: str,
    *,
    source: str,
) -> AgentConfig:
    try:
        config = agents[name]
    except KeyError as exc:
        raise ValueError(f"Unknown agent '{name}' requested via {source}.") from exc
    logger.info("Resolved agent '%s' via %s.", name, source)
    return config


def _load_shared_runtime_dependencies() -> tuple[Any, type[Any]]:
    """Load the optional LiveKit runtime dependencies used during prewarm."""
    try:
        from livekit.plugins import silero
        from livekit.plugins.turn_detector.multilingual import MultilingualModel
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "OpenRTC requires the LiveKit Silero and turn-detector plugins. "
            "Reinstall openrtc, or install livekit-agents[silero,turn-detector]."
        ) from exc

    return silero, MultilingualModel
