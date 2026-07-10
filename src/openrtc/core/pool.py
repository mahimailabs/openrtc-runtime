from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from livekit.agents import Agent, AgentServer

from openrtc.backends.registry import resolve_backend_builder
from openrtc.core.audit import DEPLOYMENT_DRAIN_STARTED, AuditLog, AuditSink
from openrtc.core.circuit_breaker import TenantCircuitBreaker
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
from openrtc.core.tenant_config import TenantConfigResolver, TenantConfigSource
from openrtc.core.wiring import _PoolRuntimeState
from openrtc.observability.base_observer import SessionObserver
from openrtc.observability.metrics import (
    MetricsStreamEvent,
)
from openrtc.observability.snapshot import PoolRuntimeSnapshot
from openrtc.routing.request_filter import (
    _build_per_agent_backpressure_filter,
    _build_per_tenant_backpressure_filter,
    _build_registered_rooms_filter,
    _build_tenant_circuit_filter,
)
from openrtc.runtime.registry import ServerParams
from openrtc.utils.types import AgentRouter, ProviderValue, RequestFilter
from openrtc.utils.validation import (
    require_agent_name,
    require_non_negative_number,
    require_positive_int,
    require_tenant_id,
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

if TYPE_CHECKING:
    from openrtc.core.backend import Backend
    from openrtc.observability.introspection_runtime import IntrospectionRuntime

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
        agent: type[Agent] | None = None,
        agents: Mapping[str, type[Agent]] | None = None,
        default_stt: ProviderValue | None = None,
        default_llm: ProviderValue | None = None,
        default_tts: ProviderValue | None = None,
        default_greeting: str | None = None,
        observers: Sequence[SessionObserver] | None = None,
        backend: str = "livekit",
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
        router: AgentRouter | None = None,
        agent_name: str | None = None,
        tenant_config: TenantConfigSource | None = None,
        max_sessions_per_agent: Mapping[str, int] | None = None,
        max_sessions_per_tenant: Mapping[str, int] | None = None,
        enable_tenant_circuit_breaker: bool = False,
        tenant_circuit_cooldown_s: float = 30.0,
        enable_introspection: bool = True,
        slow_session_threshold_ms: float = 50.0,
        introspection_socket_path: Path | None = None,
        deployment_version: str | None = None,
        audit_sink: AuditSink | None = None,
    ) -> None:
        """Create a pool with shared provider defaults, prewarm, and a universal entrypoint.

        ``agents`` registers a ``{name: AgentClass}`` mapping at construction; the
        single-agent shorthand ``agent=MyAgent`` registers it under ``"default"``.
        The two are mutually exclusive, and either composes with later ``add()`` /
        ``discover()`` calls. Names are validated (1-64 ASCII letters/digits/dashes)
        and duplicates rejected.

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

        ``tenant_config`` supplies per-tenant provider overrides (MAH-102): a
        ``{tenant: {"stt"/"llm"/"tts": ProviderValue}}`` mapping, or a callable
        ``tenant -> config`` (e.g. a DB load). At session start the tenant's providers
        replace the agent's (omitted keys fall back to the agent's), so each tenant
        runs on its own keys/models. Configs are cached per tenant; a missing tenant
        falls back to the agent/pool defaults with a one-time warning. Per-tenant
        prompts are out of scope: route a tenant to its own agent via ``router`` for a
        distinct prompt. Same spawn-safety caveat as ``router`` under process isolation.

        ``router`` is a custom dispatch router: ``router(job_metadata) -> agent_name``
        (``job_metadata`` is the parsed dispatch metadata mapping or ``None``). It
        takes precedence over the default job/room-metadata + room-prefix chain;
        returning ``None`` defers to that chain, an unknown name or a raised router
        rejects the session. In ``process`` isolation it must be picklable (a
        module-level function, not a lambda); coroutine mode accepts any callable.

        ``max_sessions_per_agent`` sets per-agent session caps (e.g.
        ``{"sales": 30, "support": 20}``): a job whose target agent is at its cap is
        rejected (backpressure) while sibling agents keep accepting. Caps may sum
        past ``max_concurrent_sessions``; the global cap still applies on top. The
        cap is soft/best-effort (it reads live active counts, incremented at session
        start), so a burst of simultaneous accepts can briefly overshoot. It layers
        over ``request_fnc`` / ``accept_only_registered_rooms`` when combined.

        ``max_sessions_per_tenant`` sets per-tenant caps (e.g. ``{"acme": 50}``),
        keyed by the dispatch metadata ``tenant``: a job for a tenant at its cap is
        rejected while sibling tenants keep accepting. It composes with
        ``max_sessions_per_agent`` (a job needs headroom under both) and the global
        cap; it is soft/best-effort in the same way.

        ``enable_tenant_circuit_breaker`` (default off) opens a per-tenant breaker
        when a tenant's recent session failure ratio trips, rejecting that tenant's
        new sessions for ``tenant_circuit_cooldown_s`` (default 30s) before auto-
        recovering. This confines one tenant's bad code path so it cannot keep
        consuming slots or trip the worker supervisor for the healthy tenants.

        ``agent_name`` sets the worker's LiveKit dispatch name. The default
        (``None``) registers an *unnamed* worker for **automatic dispatch**:
        LiveKit offers it every room and the pool's own router picks the agent.
        Set a name to register for **explicit dispatch** instead, so a caller that
        requests this worker by name (``agent_dispatch.create_dispatch(agent_name=
        ...)`` or a room created with ``roomConfig.agents[].agentName``) reaches
        it, with its per-dispatch metadata intact. LiveKit only routes an explicit
        dispatch to a worker registered under that name, so an unnamed pool never
        receives one. This is orthogonal to routing (``router`` / the metadata
        chain), which picks *which registered agent* handles a job the worker has
        already accepted.

        ``deployment_version`` tags this worker's version (e.g. ``"v1.2.3"``) for
        blue-green drain deploys: it is surfaced on ``runtime_snapshot()`` so an
        operator can watch which version each worker runs while an old pool drains.
        OpenRTC runs one worker; the gradual traffic shift and rollout orchestration
        are the deployment platform's job (a rolling update / LiveKit worker
        rotation). See the deployment guide.

        ``memory_warn_mb`` / ``memory_limit_mb`` set worker memory watermarks in
        MB (``0`` disables a band; defaults mirror livekit: warn 1000, limit 0).
        In ``process`` isolation livekit enforces them per subprocess natively.
        In ``coroutine`` isolation every session shares one process, so caps are
        worker-level: the worker warns when its RSS crosses ``memory_warn_mb``
        and drains + restarts when it crosses ``memory_limit_mb``.

        ``enable_introspection`` (default on) brings up the ``openrtc top`` stack:
        per-session memory/CPU attribution, a slow-session (event-loop-block)
        detector at ``slow_session_threshold_ms``, and a private local Unix socket
        (at ``introspection_socket_path`` or the per-user default) the inspector
        connects to. It is coroutine-mode only (process mode isolates every
        session in its own subprocess, where a shared-process inspector sees
        nothing), so it is silently skipped under ``process`` isolation.
        """
        if request_fnc is not None and accept_only_registered_rooms:
            raise ValueError(
                "Pass either request_fnc or accept_only_registered_rooms, not both."
            )
        if agent is not None and agents is not None:
            raise ValueError("Pass either agent or agents, not both.")
        validate_isolation(isolation)
        # The voice framework this pool runs on. Defaults to livekit; a pipecat
        # backend plugs in behind openrtc[pipecat]. resolve_backend_builder rejects
        # an unknown name and lazily imports only the selected framework.
        self._backend_name = backend
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
        # Blue-green deployment tag (MAH-110): labels which version this worker
        # runs, surfaced on runtime_snapshot() so an operator can watch a drain.
        self._deployment_version: str | None = None
        if deployment_version is not None:
            stripped = deployment_version.strip()
            if not stripped:
                raise ValueError(
                    "deployment_version must be a non-empty string when set."
                )
            self._deployment_version = stripped
            logger.info("Pool deployment_version=%s", stripped)
        # Worker LiveKit dispatch name. None (default) registers an unnamed worker
        # for automatic dispatch: LiveKit offers it every room and the pool's own
        # router picks the agent. A non-empty name registers the worker for
        # explicit dispatch (agent_dispatch / roomConfig.agents[].agentName), so a
        # frontend or SIP rule that names this worker reaches it.
        self._agent_name: str | None = None
        if agent_name is not None:
            stripped_name = agent_name.strip()
            if not stripped_name:
                raise ValueError("agent_name must be a non-empty string when set.")
            self._agent_name = stripped_name
            logger.info("Pool agent_name=%s (explicit dispatch)", stripped_name)
        # Deployment audit log (MAH-112): structured, monotonic-sequence events,
        # logged by default or handed to a custom sink (S3 / SIEM).
        self._audit = AuditLog(sink=audit_sink)
        # The worker substrate the pool drives, behind the neutral Backend seam.
        # The livekit backend builds and wraps the AgentServer for the isolation
        # mode; run and drain run through the seam, while introspection and reload
        # still read the raw server (exposed as .server) until they migrate too.
        self._backend: Backend = resolve_backend_builder(self._backend_name)(
            self._build_server_params(), self._isolation
        )
        self._server: AgentServer = self._backend.raw_server
        self._agents: dict[str, AgentConfig] = {}
        self._runtime_state = _PoolRuntimeState(
            agents=self._agents,
            observer_timeout=float(self._drain_timeout),
            router=router,
            tenant_resolver=(
                TenantConfigResolver(tenant_config)
                if tenant_config is not None
                else None
            ),
            deployment_version=self._deployment_version,
        )
        if observers is not None:
            for observer in observers:
                self.add_observer(observer)
        self._default_stt = default_stt
        self._default_llm = default_llm
        self._default_tts = default_tts
        self._default_greeting = default_greeting
        # Register any agents passed to the constructor (defaults must be set
        # first: add() resolves provider/greeting defaults). The single-agent
        # shorthand registers under the name "default"; add() validates each
        # name and rejects duplicates, giving every agent its own pool slot.
        if agent is not None:
            self.add("default", agent)
        for agent_name, agent_cls in (agents or {}).items():
            self.add(agent_name, agent_cls)
        # Build the ownership filter over the live agents dict so agents
        # registered after construction (via add()/discover()) are still
        # recognized at job-acceptance time.
        self._request_fnc: RequestFilter | None = (
            _build_registered_rooms_filter(self._agents)
            if accept_only_registered_rooms
            else request_fnc
        )
        # Per-agent budgets (MAH-96): layer a backpressure filter over the base
        # decision so a job for an agent at its cap is rejected while siblings
        # keep accepting. The global max_concurrent_sessions cap still applies.
        self._max_sessions_per_agent: dict[str, int] = {}
        if max_sessions_per_agent is not None:
            self._max_sessions_per_agent = {
                require_agent_name(name): require_positive_int(
                    f"max_sessions_per_agent[{name!r}]", cap
                )
                for name, cap in max_sessions_per_agent.items()
            }
            self._request_fnc = _build_per_agent_backpressure_filter(
                agents=self._agents,
                caps=self._max_sessions_per_agent,
                active_counts=self._runtime_state.metrics.active_by_agent,
                base_filter=self._request_fnc,
            )
        # Per-tenant budgets (MAH-103): layer over the per-agent filter, so tenant
        # and agent caps compose (a job needs headroom under both). Same global cap
        # still applies on top.
        self._max_sessions_per_tenant: dict[str, int] = {}
        if max_sessions_per_tenant is not None:
            self._max_sessions_per_tenant = {
                require_tenant_id(name): require_positive_int(
                    f"max_sessions_per_tenant[{name!r}]", cap
                )
                for name, cap in max_sessions_per_tenant.items()
            }
            self._request_fnc = _build_per_tenant_backpressure_filter(
                caps=self._max_sessions_per_tenant,
                active_counts=self._runtime_state.metrics.active_by_tenant,
                base_filter=self._request_fnc,
            )
        # Per-tenant circuit breaker (MAH-104): the outermost safety layer. A tenant
        # whose recent sessions fail past the breaker's threshold has its new
        # sessions rejected for a cooldown, so its bad code cannot keep consuming
        # slots or trip the worker supervisor for the healthy tenants.
        self._circuit_breaker: TenantCircuitBreaker | None = None
        if enable_tenant_circuit_breaker:
            self._circuit_breaker = TenantCircuitBreaker(
                cooldown_seconds=tenant_circuit_cooldown_s
            )
            self._runtime_state.circuit_breaker = self._circuit_breaker
            self._request_fnc = _build_tenant_circuit_filter(
                should_reject=self._circuit_breaker.should_reject,
                base_filter=self._request_fnc,
            )
        self._backend.wire(
            self._runtime_state,
            self._request_fnc,
            agent_name=self._agent_name,
        )
        self._introspection: IntrospectionRuntime | None = None
        if enable_introspection and isolation == "coroutine":
            self._setup_introspection(
                slow_session_threshold_ms, introspection_socket_path
            )
        self._enable_hot_reload = enable_hot_reload
        if enable_hot_reload:
            self._setup_hot_reload(watch_paths)

    def _build_server_params(self) -> ServerParams:
        """Collect the shared worker options the backend builds its server from."""
        return ServerParams(
            max_concurrent_sessions=self._max_concurrent_sessions,
            consecutive_failure_limit=self._consecutive_failure_limit,
            drain_timeout=self._drain_timeout,
            memory_warn_mb=self._memory_warn_mb,
            memory_limit_mb=self._memory_limit_mb,
        )

    def _setup_introspection(
        self, slow_session_threshold_ms: float, socket_path: Path | None
    ) -> None:
        """Build the introspection stack and bind it to the coroutine server.

        The registry is registered as a session observer so it tracks live
        sessions; the stack itself (samplers, detector, IPC socket) is handed to
        the server, which shares it with the ``CoroutinePool`` it builds so the
        socket follows the pool's start/close lifecycle.
        """
        from openrtc.observability.introspection_runtime import IntrospectionRuntime
        from openrtc.runtime.coroutine_server import _CoroutineAgentServer

        runtime = IntrospectionRuntime(
            socket_path=socket_path,
            slow_session_threshold_ms=slow_session_threshold_ms,
        )
        self.add_observer(runtime.registry)
        assert isinstance(self._server, _CoroutineAgentServer)
        self._server.attach_introspection(runtime)
        self._introspection = runtime

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
    def introspection(self) -> IntrospectionRuntime | None:
        """The ``openrtc top`` introspection stack, or ``None`` if disabled/process mode."""
        return self._introspection

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

    @property
    def max_sessions_per_agent(self) -> dict[str, int]:
        """Return the per-agent session caps (empty when no per-agent budgets)."""
        return dict(self._max_sessions_per_agent)

    @property
    def max_sessions_per_tenant(self) -> dict[str, int]:
        """Return the per-tenant session caps (empty when no per-tenant budgets)."""
        return dict(self._max_sessions_per_tenant)

    @property
    def tenant_circuit_breaker(self) -> TenantCircuitBreaker | None:
        """Return the per-tenant circuit breaker, or ``None`` when disabled."""
        return self._circuit_breaker

    @property
    def router(self) -> AgentRouter | None:
        """Return the custom dispatch router, or ``None`` for the default chain."""
        return self._runtime_state.router

    @property
    def deployment_version(self) -> str | None:
        """Return the blue-green deployment version tag, or ``None`` if untagged."""
        return self._deployment_version

    @property
    def agent_name(self) -> str | None:
        """Return the worker's LiveKit dispatch name, or ``None`` for automatic dispatch."""
        return self._agent_name

    @property
    def draining(self) -> bool:
        """``True`` once the worker has begun draining (rejecting new jobs, MAH-109)."""
        return self._backend.draining

    def begin_drain(self) -> None:
        """Start a blue-green drain: reject new jobs; in-flight calls run to hangup.

        Non-blocking. Production deploys trigger drain via SIGTERM (the deployment
        platform handles the switchover); this is the programmatic trigger for a
        coordinator. A no-op if the worker's coroutine pool is not running yet or in
        process isolation (where the platform drains each subprocess directly).
        """
        if self._backend.begin_drain():
            logger.info(
                "Pool draining: rejecting new jobs; in-flight calls run to hangup."
            )
            self._audit.emit(
                DEPLOYMENT_DRAIN_STARTED,
                target="worker",
                version=self._deployment_version,
            )

    @property
    def audit_log(self) -> AuditLog:
        """Return the pool's deployment audit log (MAH-112)."""
        return self._audit

    def runtime_snapshot(self) -> PoolRuntimeSnapshot:
        """Return a live snapshot of worker metrics for dashboards and automation."""
        return self._runtime_state.metrics.snapshot(
            registered_agents=len(self._agents),
            deployment_version=self._deployment_version,
            draining=self.draining,
        )

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
        normalized_name = require_agent_name(name)
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
        self._backend.run()

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
