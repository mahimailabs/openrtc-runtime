"""The pipecat backend: OpenRTC's operational layer over pipecat.

Pipecat has neither registration nor routing nor a shared session lifecycle;
OpenRTC supplies them. Agents register as pipeline builders; each call is routed
to one via the shared name resolver and built into an observed pipecat session
(:func:`~openrtc.backends.pipecat.dispatch.dispatch_pipecat_call`). That per-call
path is verified against real pipecat. Serving (accepting calls over a transport
and running a session per connection) is the remaining transport-integration
piece; ``run`` documents that boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from openrtc.backends.pipecat.dispatch import dispatch_pipecat_call
from openrtc.backends.pipecat.prewarm import SharedPrewarm

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pipecat.processors.frame_processor import FrameProcessor

    from openrtc.backends.pipecat.observer import PipecatLifecycleObserver
    from openrtc.backends.pipecat.session import PipelineBuilder
    from openrtc.core.session_view import SessionView
    from openrtc.core.wiring import _PoolRuntimeState
    from openrtc.observability.base_observer import SessionObserver
    from openrtc.runtime.registry import ServerParams
    from openrtc.utils.types import AgentRouter, RequestFilter

__all__ = ["PipecatAgentConfig", "PipecatBackend", "build_backend"]

_DEFAULT_OBSERVER_TIMEOUT = 30.0


@dataclass(frozen=True, slots=True)
class PipecatAgentConfig:
    """A registered pipecat agent: a name and its pipeline builder.

    The pipecat counterpart of ``AgentConfig`` (which holds a livekit ``Agent``
    class). Returned by ``AgentPool.add`` on the pipecat backend.
    """

    name: str
    builder: PipelineBuilder


class PipecatBackend:
    """Register pipeline builders, route each call to one, and run it on pipecat."""

    __slots__ = (
        "_builders",
        "_deployment_version",
        "_draining",
        "_observer_timeout",
        "_observers",
        "_prewarm",
        "_router",
    )

    def __init__(
        self, params: ServerParams, *, prewarm: SharedPrewarm | None = None
    ) -> None:
        self._builders: dict[str, PipelineBuilder] = {}
        self._observers: Sequence[SessionObserver] = ()
        self._observer_timeout: float = _DEFAULT_OBSERVER_TIMEOUT
        self._router: AgentRouter | None = None
        self._deployment_version: str | None = None
        self._draining = False
        # One shared VAD/turn holder, handed to every call so N sessions share
        # one analyzer instead of pipecat's per-bot construction.
        self._prewarm = prewarm if prewarm is not None else SharedPrewarm()

    @property
    def raw_server(self) -> Any:
        """Pipecat has no server object; OpenRTC dispatches per call."""
        return None

    def wire(
        self,
        runtime_state: _PoolRuntimeState,
        request_fnc: RequestFilter | None,
        *,
        agent_name: str | None,
    ) -> None:
        """Capture the neutral runtime state the per-call dispatch needs.

        ``request_fnc`` and ``agent_name`` are livekit dispatch concepts (a
        JobRequest accept/reject hook, a worker dispatch name); pipecat routes and
        accepts per call, so they do not apply here.
        """
        self._observers = list(runtime_state.observers)
        self._observer_timeout = runtime_state.observer_timeout
        self._router = runtime_state.router
        self._deployment_version = runtime_state.deployment_version

    def register(self, name: str, builder: PipelineBuilder) -> None:
        """Register a pipeline builder under an agent name (``pool.add`` on pipecat)."""
        if name in self._builders:
            raise ValueError(f"Agent '{name}' is already registered.")
        self._builders[name] = builder

    def registered_names(self) -> list[str]:
        """Return the registered agent names in registration order."""
        return list(self._builders)

    def get(self, name: str) -> PipecatAgentConfig:
        """Return a registered agent configuration by name (``pool.get``)."""
        try:
            builder = self._builders[name]
        except KeyError as exc:
            raise KeyError(f"Unknown agent '{name}'.") from exc
        return PipecatAgentConfig(name=name, builder=builder)

    def remove(self, name: str) -> PipecatAgentConfig:
        """Remove and return a registered agent configuration (``pool.remove``)."""
        try:
            builder = self._builders.pop(name)
        except KeyError as exc:
            raise KeyError(f"Unknown agent '{name}'.") from exc
        return PipecatAgentConfig(name=name, builder=builder)

    def dispatch(
        self, view: SessionView, *, connection: Any = None
    ) -> tuple[list[FrameProcessor], PipecatLifecycleObserver]:
        """Route one call to its builder and build its observed session.

        ``connection`` is the served call's transport connection (a pipecat
        ``RunnerArguments``), passed through to the builder via the call view; it
        is ``None`` for the dispatch-only path.
        """
        return dispatch_pipecat_call(
            view,
            self._builders,
            observers=self._observers,
            timeout=self._observer_timeout,
            deployment_version=self._deployment_version,
            router=self._router,
            prewarm=self._prewarm,
            connection=connection,
        )

    def build_call(
        self, runner_args: Any
    ) -> tuple[list[FrameProcessor], PipecatLifecycleObserver]:
        """Build the observed session for one served connection (the ``bot`` seam).

        Adapts a pipecat ``RunnerArguments`` to the neutral view (routing reads
        ``body["agent"]``), routes to the builder, and passes the ``RunnerArguments``
        through as the call's ``connection`` so the builder builds its transport.
        Returns the processors and lifecycle observer; the serving front assembles
        them into a ``PipelineTask`` and runs one per connection.
        """
        from openrtc.core.session_view import for_pipecat

        return self.dispatch(for_pipecat(runner_args), connection=runner_args)

    def run(self) -> None:
        raise NotImplementedError(
            "The pipecat serving front (accepting calls over a transport and "
            "running PipecatBackend.dispatch per connection) is not yet wired. The "
            "per-call session logic is complete and verified; wiring a transport "
            "server is the remaining step."
        )

    def begin_drain(self) -> bool:
        """Begin draining; return whether this call started it (idempotent)."""
        if self._draining:
            return False
        self._draining = True
        return True

    @property
    def draining(self) -> bool:
        return self._draining


def build_backend(params: ServerParams, isolation: str) -> PipecatBackend:
    """Build a pipecat backend. Pipecat runs in-process (coroutine-style density)."""
    return PipecatBackend(params)
