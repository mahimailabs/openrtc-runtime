"""The backend-neutral substrate seam an ``AgentPool`` drives.

An ``AgentPool`` owns the worker, prewarm, and the session lifecycle. The pool
drives its substrate through this small ``Backend`` seam instead of a framework
type; the livekit backend wraps ``livekit.agents.AgentServer``.

This module imports no framework, so ``import openrtc.core.backend`` does not
pull livekit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from openrtc.core.wiring import _PoolRuntimeState
    from openrtc.observability.introspection_runtime import IntrospectionRuntime
    from openrtc.utils.types import RequestFilter

__all__ = ["Backend"]


@runtime_checkable
class Backend(Protocol):
    """The worker substrate an ``AgentPool`` builds and runs sessions on.

    The pool still reads ``raw_server`` for hot reload, which needs the
    coroutine ``AgentServer`` directly.
    """

    @property
    def raw_server(self) -> Any:
        """The underlying framework server object (a livekit ``AgentServer`` today)."""
        ...

    def wire(
        self,
        runtime_state: _PoolRuntimeState,
        request_fnc: RequestFilter | None,
        *,
        agent_name: str | None,
    ) -> None:
        """Bind shared prewarm and the universal session entrypoint onto the server."""
        ...

    def attach_introspection(self, runtime: IntrospectionRuntime) -> None:
        """Bind the ``openrtc top`` introspection stack to the substrate.

        Called only in coroutine isolation (the pool gates on it). The livekit
        backend hands the stack to its coroutine ``AgentServer`` (shared with the
        ``CoroutinePool`` it builds).
        """
        ...

    def run(self) -> None:
        """Hand the worker to the framework's runtime (blocking until it exits)."""
        ...

    def begin_drain(self) -> bool:
        """Begin draining if the substrate is running; return whether it did.

        Returns ``False`` when there is nothing to drain (no running pool, or a
        backend without a drain concept), so the caller can skip drain-side
        effects such as the audit event.
        """
        ...

    @property
    def draining(self) -> bool:
        """Whether the worker has begun draining (rejecting new jobs)."""
        ...
