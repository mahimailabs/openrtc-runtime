from __future__ import annotations

import logging
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, Literal

from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli

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
from openrtc.core.registry import ServerParams, resolve_server_builder
from openrtc.core.routing import _resolve_agent_config
from openrtc.core.turn_handling import _build_session_kwargs
from openrtc.core.validation import require_positive_int, validate_isolation
from openrtc.execution.prewarm import _prewarm_worker
from openrtc.execution.resources import PrewarmResources
from openrtc.observability.metrics import (
    MetricsStreamEvent,
    RuntimeMetricsStore,
)
from openrtc.observability.observer import (
    SessionObserver,
    _build_session_info,
    _build_session_outcome,
    _notify_session_end,
    _notify_session_start,
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

# The on_session_start notification runs in the interactive hot path (before the
# greeting), so it is bounded by this short timeout rather than the larger drain
# budget that bounds the on_session_end notification at teardown.
_OBSERVER_START_TIMEOUT_SECONDS = 5.0


@dataclass(slots=True)
class _PoolRuntimeState:
    """Serializable runtime state shared with worker callbacks."""

    agents: dict[str, AgentConfig]
    metrics: RuntimeMetricsStore = field(default_factory=RuntimeMetricsStore)
    observers: list[SessionObserver] = field(default_factory=list)
    observer_timeout: float = 30.0


async def _run_universal_session(
    runtime_state: _PoolRuntimeState,
    ctx: JobContext,
) -> None:
    """Dispatch a session through the owning ``AgentPool``."""
    if not runtime_state.agents:
        raise RuntimeError("No agents are registered in the pool.")
    config = _resolve_agent_config(runtime_state.agents, ctx)
    session_kwargs = _build_session_kwargs(config.session_kwargs, ctx.proc)
    session: AgentSession[None] = AgentSession(
        stt=config.stt,
        llm=config.llm,
        tts=config.tts,
        vad=PrewarmResources.vad_from(ctx.proc),
        **session_kwargs,
    )
    info = _build_session_info(config.name, ctx)
    try:
        runtime_state.metrics.record_session_started(config.name)
        await session.start(
            agent=config.agent_cls(),  # type: ignore[call-arg]
            room=ctx.room,
        )
        await ctx.connect()
        await _notify_session_start(
            runtime_state.observers,
            info,
            session,
            timeout=min(
                runtime_state.observer_timeout, _OBSERVER_START_TIMEOUT_SECONDS
            ),
        )

        if config.greeting is not None:
            logger.debug("Generating greeting for agent '%s'.", config.name)
            await session.generate_reply(instructions=config.greeting)
    except Exception as exc:
        runtime_state.metrics.record_session_failure(config.name, exc)
        raise
    finally:
        runtime_state.metrics.record_session_finished(config.name)
        outcome = _build_session_outcome(info, sys.exc_info()[1])
        await _notify_session_end(
            runtime_state.observers,
            info,
            outcome,
            timeout=runtime_state.observer_timeout,
        )


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
        observers: Sequence[SessionObserver] | None = None,
        isolation: IsolationMode = "coroutine",
        max_concurrent_sessions: int = 50,
        consecutive_failure_limit: int = 5,
        drain_timeout: int = 30,
    ) -> None:
        """Create a pool with shared provider defaults, prewarm, and a universal entrypoint.

        ``isolation`` controls whether sessions run as ``asyncio.Task``s in one
        process (``"coroutine"``, high density) or as separate OS processes
        (``"process"``, livekit-agents default).
        ``drain_timeout`` sets the maximum seconds the worker waits for in-flight
        sessions to finish after SIGTERM before cancelling them.
        """
        validate_isolation(isolation)
        self._isolation: IsolationMode = isolation
        self._max_concurrent_sessions = require_positive_int(
            "max_concurrent_sessions", max_concurrent_sessions
        )
        self._consecutive_failure_limit = require_positive_int(
            "consecutive_failure_limit", consecutive_failure_limit
        )
        self._drain_timeout = require_positive_int("drain_timeout", drain_timeout)
        self._server = self._build_server()
        self._agents: dict[str, AgentConfig] = {}
        self._runtime_state = _PoolRuntimeState(
            agents=self._agents,
            observer_timeout=float(self._drain_timeout),
        )
        if observers is not None:
            for observer in observers:
                self.add_observer(observer)
        self._default_stt = default_stt
        self._default_llm = default_llm
        self._default_tts = default_tts
        self._default_greeting = default_greeting
        self._server.setup_fnc = partial(_prewarm_worker, self._runtime_state)
        self._server.rtc_session()(partial(_run_universal_session, self._runtime_state))

    def _build_server(self) -> AgentServer:
        """Construct the underlying LiveKit server matching ``isolation``."""
        params = ServerParams(
            max_concurrent_sessions=self._max_concurrent_sessions,
            consecutive_failure_limit=self._consecutive_failure_limit,
            drain_timeout=self._drain_timeout,
        )
        return resolve_server_builder(self._isolation)(params)

    @property
    def isolation(self) -> IsolationMode:
        """Return the configured worker isolation mode (``"coroutine"`` or ``"process"``)."""
        return self._isolation

    @property
    def max_concurrent_sessions(self) -> int:
        """Return the coroutine-mode backpressure threshold."""
        return self._max_concurrent_sessions

    @property
    def consecutive_failure_limit(self) -> int:
        """Return the coroutine-mode supervisor failure threshold."""
        return self._consecutive_failure_limit

    @property
    def drain_timeout(self) -> int:
        """Return the seconds the worker waits for in-flight sessions on SIGTERM."""
        return self._drain_timeout

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
        """Register an agent in the pool and return its configuration."""
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
        """Discover and register agent modules from a directory; return registered configs."""
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
        """Return a registered agent configuration by name."""
        try:
            return self._agents[name]
        except KeyError as exc:
            raise KeyError(f"Unknown agent '{name}'.") from exc

    def remove(self, name: str) -> AgentConfig:
        """Remove and return a registered agent configuration."""
        try:
            removed = self._agents.pop(name)
        except KeyError as exc:
            raise KeyError(f"Unknown agent '{name}'.") from exc
        logger.debug("Removed agent '%s'.", name)
        return removed

    def add_observer(self, observer: SessionObserver) -> None:
        """Register a session observer notified for every session in the pool.

        Call before run(). In process isolation mode the observer must be
        picklable (it rides the serializable worker state), so build any live
        resources lazily on the first on_session_start, not in the constructor.
        """
        if not isinstance(observer, SessionObserver):
            raise TypeError(
                "observer must implement on_session_start and on_session_end "
                f"(SessionObserver protocol); got {type(observer).__name__}."
            )
        self._runtime_state.observers.append(observer)

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
