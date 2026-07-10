"""The livekit backend: adapts livekit's ``AgentServer`` to OpenRTC's ``Backend``.

Wraps the server an ``AgentPool`` builds for its isolation mode and owns the
wiring of shared prewarm plus the universal session entrypoint (via
``core.wiring.wire_pool``). Server construction, run, introspection, reload, and
drain still live on the pool against ``raw_server`` and migrate here in later
steps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openrtc.core.wiring import wire_pool

if TYPE_CHECKING:
    from openrtc.core.wiring import _PoolRuntimeState
    from openrtc.runtime.base_runtime import SessionRuntime
    from openrtc.utils.types import RequestFilter

__all__ = ["LiveKitBackend"]


class LiveKitBackend:
    """Run OpenRTC sessions on livekit's ``AgentServer`` substrate."""

    __slots__ = ("_server",)

    def __init__(self, server: SessionRuntime) -> None:
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
