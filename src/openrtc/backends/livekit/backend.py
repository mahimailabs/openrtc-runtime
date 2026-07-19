"""The livekit backend: adapts livekit's ``AgentServer`` to OpenRTC's ``Backend``.

Wraps the server an ``AgentPool`` builds for its isolation mode and owns the
wiring of shared prewarm plus the universal session entrypoint (via
``core.wiring.wire_pool``). Server construction, run, introspection, reload, and
drain still live on the pool against ``raw_server`` and migrate here in later
steps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from livekit.agents import AgentServer, cli

from openrtc.core.wiring import wire_pool
from openrtc.runtime.registry import ServerParams, resolve_server_builder

if TYPE_CHECKING:
    from openrtc.core.wiring import _PoolRuntimeState
    from openrtc.observability.introspection_runtime import IntrospectionRuntime
    from openrtc.runtime.coroutine_server import _CoroutineAgentServer
    from openrtc.utils.types import RequestFilter

__all__ = ["LiveKitBackend", "build_backend"]


class LiveKitBackend:
    """Run OpenRTC sessions on livekit's ``AgentServer`` substrate."""

    __slots__ = ("_server",)

    def __init__(self, server: AgentServer) -> None:
        self._server = server

    @property
    def raw_server(self) -> Any:
        """The wrapped livekit ``AgentServer`` (the pool's ``.server``)."""
        return self._server

    def wire(
        self,
        runtime_state: _PoolRuntimeState,
        request_fnc: RequestFilter | None,
        *,
        agent_name: str | None,
    ) -> None:
        """Bind shared prewarm and the universal session entrypoint onto the server."""
        wire_pool(self._server, runtime_state, request_fnc, agent_name=agent_name)

    def attach_introspection(self, runtime: IntrospectionRuntime) -> None:
        """Hand the stack to the coroutine ``AgentServer`` (shared with its pool).

        The pool gates on coroutine isolation before calling this, so the wrapped
        server is always the ``_CoroutineAgentServer`` that exposes the hook.
        """
        cast("_CoroutineAgentServer", self._server).attach_introspection(runtime)

    def run(self) -> None:
        """Hand the worker to livekit's CLI runtime (blocking until it exits)."""
        cli.run_app(self._server)

    def begin_drain(self) -> bool:
        """Begin draining the coroutine pool if one is running; return whether it did.

        A no-op returning ``False`` in process isolation or before the pool starts
        (the platform drains each subprocess directly there).
        """
        pool = getattr(self._server, "coroutine_pool", None)
        begin = getattr(pool, "begin_drain", None)
        if callable(begin):
            begin()
            return True
        return False

    @property
    def draining(self) -> bool:
        """Whether the coroutine pool has begun draining (rejecting new jobs)."""
        pool = getattr(self._server, "coroutine_pool", None)
        return bool(getattr(pool, "draining", False))


def build_backend(params: ServerParams, isolation: str) -> LiveKitBackend:
    """Build a livekit backend running the ``AgentServer`` for an isolation mode.

    The isolation mode (``"coroutine"`` / ``"process"``) selects the server the
    backend wraps, keeping construction of the livekit substrate behind the seam.
    """
    return LiveKitBackend(resolve_server_builder(isolation)(params))
