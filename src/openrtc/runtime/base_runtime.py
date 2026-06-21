"""The worker-server surface AgentPool drives, independent of isolation mode."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

__all__ = ["SessionRuntime"]


@runtime_checkable
class SessionRuntime(Protocol):
    """What AgentPool needs from its server, whatever the isolation mode."""

    setup_fnc: Callable[..., Any] | None

    def rtc_session(self) -> Callable[[Callable[..., Any]], Any]: ...

    async def run(self, *, devmode: bool = ..., unregistered: bool = ...) -> None: ...

    async def aclose(self) -> None: ...
