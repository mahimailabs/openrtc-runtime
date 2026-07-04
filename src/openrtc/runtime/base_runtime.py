"""The worker-server surface AgentPool drives, independent of isolation mode."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from livekit.agents import JobContext, JobRequest

__all__ = ["SessionRuntime"]


@runtime_checkable
class SessionRuntime(Protocol):
    """What AgentPool needs from its server, whatever the isolation mode."""

    setup_fnc: Callable[..., Any] | None

    def rtc_session(
        self,
        *,
        on_request: Callable[[JobRequest], Any] | None = None,
        on_session_end: Callable[[JobContext], Any] | None = None,
    ) -> Callable[[Callable[..., Any]], Any]: ...

    async def run(self, *, devmode: bool = ..., unregistered: bool = ...) -> None: ...

    async def aclose(self) -> None: ...
