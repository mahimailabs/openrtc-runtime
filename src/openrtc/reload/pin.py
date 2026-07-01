"""MAH-83: opt a live session out of mid-flow class swaps.

Some flows cannot tolerate a behavior change mid-session (payment confirmation,
multi-step auth, anything whose state machine assumes one consistent class). A
pinned session keeps the agent instance it had at pin time; the re-bind protocol
skips it until it is unpinned or ends.

The public entry point is the :func:`pin_reload` context manager. Pins live in a
process-global ``WeakSet`` so a dropped session releases its pin automatically;
the coordinator also unpins proactively when a session ends. Because it is
OpenRTC-owned rather than a method monkeypatched onto livekit's ``AgentSession``,
it works uniformly whether or not hot reload is currently running (an unread pin
is simply harmless).
"""

from __future__ import annotations

import weakref
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

    from livekit.agents import AgentSession

__all__ = ["is_pinned", "pin", "pin_reload", "unpin"]

_pinned: weakref.WeakSet[AgentSession[Any]] = weakref.WeakSet()


def pin(session: AgentSession[Any]) -> None:
    """Exclude *session* from class swaps until it is unpinned or ends."""
    _pinned.add(session)


def unpin(session: AgentSession[Any]) -> None:
    """Release a pin; a no-op if *session* was not pinned."""
    _pinned.discard(session)


def is_pinned(session: AgentSession[Any]) -> bool:
    """Return whether *session* is currently opted out of swaps."""
    return session in _pinned


@contextmanager
def pin_reload(session: AgentSession[Any]) -> Iterator[None]:
    """Pin *session* for the duration of a critical flow, releasing on exit.

    Example::

        async def confirm_payment(self, ctx: RunContext) -> str:
            with pin_reload(ctx.session):
                ...  # this session will not swap class mid-confirmation
    """
    pin(session)
    try:
        yield
    finally:
        unpin(session)
