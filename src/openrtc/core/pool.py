from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, Literal

from livekit.agents import Agent, AgentServer, AgentSession, JobContext, JobProcess, cli

from openrtc.core.config import (
    AgentConfig,
    AgentDiscoveryConfig,
    _resolve_discovery_metadata,
    agent_config,
)
from openrtc.core.discovery import (
    _find_local_agent_subclass,
    _load_agent_module,
)
from openrtc.core.routing import _resolve_agent_config
from openrtc.core.turn_handling import _build_session_kwargs
from openrtc.observability.metrics import (
    MetricsStreamEvent,
    RuntimeMetricsStore,
)
from openrtc.observability.snapshot import PoolRuntimeSnapshot
from openrtc.types import ProviderValue

__all__ = [
    "AgentConfig",
    "AgentDiscoveryConfig",
    "AgentPool",
    "IsolationMode",
    "agent_config",
]

logger = logging.getLogger("openrtc")

IsolationMode = Literal["coroutine", "process"]


@dataclass(slots=True)
class _PoolRuntimeState:
    """Serializable runtime state shared with worker callbacks."""

    agents: dict[str, AgentConfig]
    metrics: RuntimeMetricsStore = field(default_factory=RuntimeMetricsStore)


def _prewarm_worker(
    runtime_state: _PoolRuntimeState,
    proc: JobProcess,
) -> None:
    """Load shared runtime assets into ``proc.userdata`` once per worker."""
    if not runtime_state.agents:
        raise RuntimeError("Register at least one agent before calling run().")
    silero_module, turn_detector_model = _load_shared_runtime_dependencies()
    proc.userdata["vad"] = silero_module.VAD.load()
    proc.userdata["turn_detection_factory"] = turn_detector_model


async def _run_universal_session(
    runtime_state: _PoolRuntimeState,
    ctx: JobContext,
) -> None:
    """Dispatch a session through the owning ``AgentPool``."""
    if not runtime_state.agents:
        raise RuntimeError("No agents are registered in the pool.")
    config = _resolve_agent_config(runtime_state.agents, ctx)
    session_kwargs = _build_session_kwargs(config.session_kwargs, ctx.proc)
    session: AgentSession = AgentSession(
        stt=config.stt,
        llm=config.llm,
        tts=config.tts,
        vad=ctx.proc.userdata["vad"],
        **session_kwargs,
    )
    try:
        runtime_state.metrics.record_session_started(config.name)
        await session.start(
            agent=config.agent_cls(),  # type: ignore[call-arg]
            room=ctx.room,
        )
        await ctx.connect()

        if config.greeting is not None:
            logger.debug("Generating greeting for agent '%s'.", config.name)
            await session.generate_reply(instructions=config.greeting)
    except Exception as exc:
        runtime_state.metrics.record_session_failure(config.name, exc)
        raise
    finally:
        runtime_state.metrics.record_session_finished(config.name)


class AgentPool:
    """Manage multiple LiveKit agents inside a single worker process.

    ``AgentPool`` keeps user-defined agents as standard LiveKit ``Agent``
    subclasses while centralizing the shared worker concerns OpenRTC adds:
    prewarm, routing, and per-agent session construction.
    """

    def __init__(
        self,
        *,
        default_stt: ProviderValue | None = None,
        default_llm: ProviderValue | None = None,
        default_tts: ProviderValue | None = None,
        default_greeting: str | None = None,
        isolation: IsolationMode = "coroutine",
        max_concurrent_sessions: int = 50,
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
            isolation: Worker isolation mode. ``"coroutine"`` (the v0.1 default)
                runs every session as an ``asyncio.Task`` inside one worker
                process for high density. ``"process"`` preserves the v0.0.x
                behavior of one OS process per session via livekit-agents'
                default ``ProcPool``. The setting is plumbed but not yet acted
                on; the actual coroutine runtime arrives in a follow-up
                iteration.
            max_concurrent_sessions: Backpressure threshold for coroutine mode.
                Once this many concurrent sessions are running, the worker
                reports ``load >= 1.0`` to LiveKit dispatch and additional
                jobs are routed elsewhere. Default ``50`` matches the design
                target. Ignored in ``"process"`` mode (livekit-agents' own
                load math applies). Plumbed but not yet enforced.
        """
        if isolation not in ("coroutine", "process"):
            raise ValueError(
                f"isolation must be 'coroutine' or 'process', got {isolation!r}."
            )
        if not isinstance(max_concurrent_sessions, int) or isinstance(
            max_concurrent_sessions, bool
        ):
            raise TypeError(
                "max_concurrent_sessions must be an int, "
                f"got {type(max_concurrent_sessions).__name__}."
            )
        if max_concurrent_sessions < 1:
            raise ValueError(
                f"max_concurrent_sessions must be >= 1, got {max_concurrent_sessions}."
            )
        self._isolation: IsolationMode = isolation
        self._max_concurrent_sessions: int = max_concurrent_sessions
        self._server = self._build_server()
        self._agents: dict[str, AgentConfig] = {}
        self._runtime_state = _PoolRuntimeState(agents=self._agents)
        self._default_stt = default_stt
        self._default_llm = default_llm
        self._default_tts = default_tts
        self._default_greeting = default_greeting
        self._server.setup_fnc = partial(_prewarm_worker, self._runtime_state)
        self._server.rtc_session()(partial(_run_universal_session, self._runtime_state))

    def _build_server(self) -> AgentServer:
        """Construct the underlying LiveKit server matching ``isolation``.

        Coroutine mode returns an :class:`_CoroutineAgentServer` that
        monkey-patches ``ipc.proc_pool.ProcPool`` with our
        :class:`CoroutinePool` for the duration of ``run()``. Process mode
        returns a vanilla :class:`AgentServer` (the v0.0.x default).

        The coroutine import is deferred so process-only callers do not
        load ``execution/coroutine_server.py`` at module import time.
        """
        if self._isolation == "coroutine":
            from openrtc.execution.coroutine_server import _CoroutineAgentServer

            return _CoroutineAgentServer(
                max_concurrent_sessions=self._max_concurrent_sessions,
            )
        return AgentServer()

    @property
    def isolation(self) -> IsolationMode:
        """Return the configured worker isolation mode (``"coroutine"`` or ``"process"``)."""
        return self._isolation

    @property
    def max_concurrent_sessions(self) -> int:
        """Return the coroutine-mode backpressure threshold."""
        return self._max_concurrent_sessions

    @property
    def server(self) -> AgentServer:
        """Return the underlying LiveKit ``AgentServer`` instance."""
        return self._server

    def runtime_snapshot(self) -> PoolRuntimeSnapshot:
        """Return a live snapshot of worker metrics for dashboards and automation."""
        return self._runtime_state.metrics.snapshot(registered_agents=len(self._agents))

    def drain_metrics_stream_events(self) -> list[MetricsStreamEvent]:
        """Drain pending session lifecycle events for JSONL sidecar export."""
        return self._runtime_state.metrics.drain_stream_events()

    def add(
        self,
        name: str,
        agent_cls: type[Agent],
        *,
        stt: ProviderValue | None = None,
        llm: ProviderValue | None = None,
        tts: ProviderValue | None = None,
        greeting: str | None = None,
        session_kwargs: Mapping[str, Any] | None = None,
        source_path: Path | str | None = None,
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
            source_path: Optional path to the agent's Python module on disk
                (used for discovery metadata and footprint reporting).

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

        resolved_source: Path | None
        if source_path is None:
            resolved_source = None
        else:
            resolved_source = Path(source_path).expanduser().resolve()

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
            source_path=resolved_source,
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

            module = _load_agent_module(module_path)
            agent_cls = _find_local_agent_subclass(module)
            metadata = _resolve_discovery_metadata(agent_cls)
            agent_name = metadata.name or module_path.stem
            config = self.add(
                agent_name,
                agent_cls,
                stt=metadata.stt,
                llm=metadata.llm,
                tts=metadata.tts,
                greeting=metadata.greeting,
                source_path=module_path,
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

    def _resolve_provider(
        self,
        value: ProviderValue | None,
        default_value: ProviderValue | None,
    ) -> ProviderValue | None:
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
