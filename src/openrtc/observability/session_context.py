"""Per-session identity in the shared worker: a ``session_id`` contextvar (MAH-91).

The coroutine worker hosts many sessions in one process, so a session's identity
must ride the async context rather than a thread local. Everything in the v0.3
introspection surface (log scoping, memory/CPU attribution, ``openrtc top``) keys
off the ``session_id`` bound here. A task spawned inside a scope inherits the id
because ``asyncio`` copies the context at task-creation time.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

__all__ = [
    "current_agent_name",
    "current_session_id",
    "reset_agent_name",
    "reset_session_id",
    "session_scope",
    "set_agent_name",
    "set_session_id",
]

_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "openrtc_session_id", default=None
)
# Bound alongside the session_id (the routed agent for the session), so scoped
# log records carry which agent produced them (MAH-98), keyed the same way as
# the SessionObserver payload's info.agent_name.
_agent_name: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "openrtc_agent_name", default=None
)


def current_session_id() -> str | None:
    """Return the ``session_id`` bound to the current async context, or ``None``."""
    return _session_id.get()


def set_session_id(session_id: str) -> contextvars.Token[str | None]:
    """Bind ``session_id`` to the current context; return a token for ``reset``."""
    return _session_id.set(session_id)


def reset_session_id(token: contextvars.Token[str | None]) -> None:
    """Restore the ``session_id`` bound before ``set_session_id`` returned ``token``."""
    _session_id.reset(token)


def current_agent_name() -> str | None:
    """Return the ``agent_name`` bound to the current async context, or ``None``."""
    return _agent_name.get()


def set_agent_name(agent_name: str) -> contextvars.Token[str | None]:
    """Bind ``agent_name`` to the current context; return a token for ``reset``."""
    return _agent_name.set(agent_name)


def reset_agent_name(token: contextvars.Token[str | None]) -> None:
    """Restore the ``agent_name`` bound before ``set_agent_name`` returned ``token``."""
    _agent_name.reset(token)


@contextmanager
def session_scope(session_id: str) -> Iterator[None]:
    """Bind ``session_id`` for the duration of the ``with`` block, then restore."""
    token = _session_id.set(session_id)
    try:
        yield
    finally:
        _session_id.reset(token)
