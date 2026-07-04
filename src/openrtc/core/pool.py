from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from livekit.agents import Agent, AgentServer, cli

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
from openrtc.core.wiring import _PoolRuntimeState, wire_pool
from openrtc.observability.base_observer import SessionObserver
from openrtc.observability.metrics import (
    MetricsStreamEvent,
)
from openrtc.observability.snapshot import PoolRuntimeSnapshot
from openrtc.routing.request_filter import _build_registered_rooms_filter
from openrtc.runtime.registry import ServerParams, resolve_server_builder
from openrtc.utils.types import ProviderValue, RequestFilter
from openrtc.utils.validation import (
    require_non_negative_number,
    require_positive_int,
    validate_isolation,
)

__all__ = [
    "AgentConfig",
    "AgentDiscoveryConfig",
    "AgentPool",
    "IsolationMode",
    "agent_config",
]

logger = logging.getLogger("openrtc")

IsolationMode = Literal["coroutine", "process"]


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
        memory_warn_mb: float = 1000.0,
        memory_limit_mb: float = 0.0,
        enable_hot_reload: bool = False,
        watch_paths: list[Path] | None = None,
        request_fnc: RequestFilter | None = None,
        accept_only_registered_rooms: bool = False,
    ) -> None:
        """Create a pool with shared provider defaults, prewarm, and a universal entrypoint.

        ``isolation`` controls whether sessions run as ``asyncio.Task``s in one
        process (``"coroutine"``, high density) or as separate OS processes
        (``"process"``, livekit-agents default).
        ``drain_timeout`` sets the maximum seconds the worker waits for in-flight
        sessions to finish after SIGTERM before cancelling them.

        ``request_fnc`` is LiveKit's per-job accept/reject hook, invoked with a
        ``JobRequest`` that it must resolve via ``await req.accept()`` or
        ``await req.reject()``. It scopes which rooms this worker handles, which
        matters when several workers share one LiveKit project (automatic
        dispatch offers every room to every worker). ``None`` keeps LiveKit's
        accept-all default.
        ``accept_only_registered_rooms`` is a convenience for the common case:
        install a filter that accepts a job only when an explicit routing signal
        (job/room metadata naming a registered agent, or a ``<agent>-`` room-name
        prefix) maps it to one of this pool's agents, and rejects everything
        else. It is mutually exclusive with ``request_fnc``.

        ``memory_warn_mb`` / ``memory_limit_mb`` set worker memory watermarks in
        MB (``0`` disables a band; defaults mirror livekit: warn 1000, limit 0).
        In ``process`` isolation livekit enforces them per subprocess natively.
        In ``coroutine`` isolation every session shares one process, so caps are
        worker-level: the worker warns when its RSS crosses ``memory_warn_mb``
        and drains + restarts when it crosses ``memory_limit_mb``.
        """
        if request_fnc is not None and accept_only_registered_rooms:
            raise ValueError(
                "Pass either request_fnc or accept_only_registered_rooms, not both."
            )
        validate_isolation(isolation)
        self._isolation: IsolationMode = isolation
        self._max_concurrent_sessions = require_positive_int(
            "max_concurrent_sessions", max_concurrent_sessions
        )
        self._consecutive_failure_limit = require_positive_int(
            "consecutive_failure_limit", consecutive_failure_limit
        )
        self._drain_timeout = require_positive_int("drain_timeout", drain_timeout)
        self._memory_warn_mb = require_non_negative_number(
            "memory_warn_mb", memory_warn_mb
        )
        self._memory_limit_mb = require_non_negative_number(
            "memory_limit_mb", memory_limit_mb
        )
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
        # Build the ownership filter over the live agents dict so agents
        # registered after construction (via add()/discover()) are still
        # recognized at job-acceptance time.
        self._request_fnc: RequestFilter | None = (
            _build_registered_rooms_filter(self._agents)
            if accept_only_registered_rooms
            else request_fnc
        )
        wire_pool(self._server, self._runtime_state, self._request_fnc)
        self._enable_hot_reload = enable_hot_reload
        if enable_hot_reload:
            self._setup_hot_reload(watch_paths)

    def _build_server(self) -> AgentServer:
        """Construct the underlying LiveKit server matching ``isolation``."""
        params = ServerParams(
            max_concurrent_sessions=self._max_concurrent_sessions,
            consecutive_failure_limit=self._consecutive_failure_limit,
            drain_timeout=self._drain_timeout,
            memory_warn_mb=self._memory_warn_mb,
            memory_limit_mb=self._memory_limit_mb,
        )
        return resolve_server_builder(self._isolation)(params)

    def _setup_hot_reload(self, watch_paths: list[Path] | None) -> None:
        """Wire live-session tracking and the reload coordinator onto the worker.

        Hot reload is coroutine-mode only: process mode runs one subprocess per
        session and cannot swap an agent class in place.
        """
        if self._isolation != "coroutine":
            raise ValueError(
                "enable_hot_reload requires isolation='coroutine'; process mode "
                "runs one subprocess per session and cannot hot reload."
            )
        from openrtc.reload.coordinator import ReloadCoordinator
        from openrtc.reload.session_registry import LiveSessionRegistry
        from openrtc.runtime.coroutine_server import _CoroutineAgentServer

        registry = LiveSessionRegistry()
        self.add_observer(registry)
        coordinator = ReloadCoordinator(self._agents, registry)
        assert isinstance(self._server, _CoroutineAgentServer)
        self._server.attach_reload(coordinator.on_change, watch_paths)

    @property
    def enable_hot_reload(self) -> bool:
        """Whether hot reload is active for this pool (coroutine mode only)."""
        return self._enable_hot_reload

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
    def memory_warn_mb(self) -> float:
        """Return the worker RSS warn watermark in MB (``0`` disables it)."""
        return self._memory_warn_mb

    @property
    def memory_limit_mb(self) -> float:
        """Return the worker RSS limit watermark in MB (``0`` disables it)."""
        return self._memory_limit_mb

    @property
    def server(self) -> AgentServer:
        """Return the underlying LiveKit ``AgentServer`` instance."""
        return self._server

    @property
    def request_fnc(self) -> RequestFilter | None:
        """Return the per-job accept/reject filter, or ``None`` for accept-all."""
        return self._request_fnc

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
