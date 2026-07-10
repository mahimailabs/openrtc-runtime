"""The backend-neutral substrate seam an ``AgentPool`` drives.

An ``AgentPool`` owns the worker, prewarm, and the session lifecycle. To let one
pool run over more than one voice framework (livekit today, pipecat next), the
pool drives its substrate through this small neutral ``Backend`` seam instead of
a framework type. Each backend adapts its framework's server to it: the livekit
backend wraps ``livekit.agents.AgentServer``; a pipecat backend will wrap a
``PipelineRunner``.

This module imports no framework, so ``import openrtc.core.backend`` pulls
neither livekit nor pipecat. (See docs/design/framework-agnostic-backend.md.)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from openrtc.core.wiring import _PoolRuntimeState
    from openrtc.utils.types import RequestFilter

__all__ = ["Backend"]


@runtime_checkable
class Backend(Protocol):
    """The worker substrate an ``AgentPool`` builds and runs sessions on.

    One implementation per framework. Today the pool still reads ``raw_server``
    for the substrate operations not yet migrated onto the seam (run,
    introspection, reload, drain); those move here in later steps.
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
