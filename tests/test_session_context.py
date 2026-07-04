"""Per-session identity contextvar for the shared worker (MAH-91).

The coroutine worker multiplexes many sessions in one process, so a session_id
must ride the async context (contextvars), not a thread local. These tests pin
propagation into child tasks and clean set/reset semantics.
"""

from __future__ import annotations

import asyncio

from openrtc.observability.session_context import (
    current_session_id,
    reset_session_id,
    session_scope,
    set_session_id,
)


def test_no_session_id_outside_scope() -> None:
    assert current_session_id() is None


def test_session_scope_sets_and_resets() -> None:
    assert current_session_id() is None
    with session_scope("abc123"):
        assert current_session_id() == "abc123"
    assert current_session_id() is None


def test_set_reset_tokens() -> None:
    token = set_session_id("s1")
    assert current_session_id() == "s1"
    reset_session_id(token)
    assert current_session_id() is None


def test_nested_scopes_restore() -> None:
    with session_scope("outer"):
        assert current_session_id() == "outer"
        with session_scope("inner"):
            assert current_session_id() == "inner"
        assert current_session_id() == "outer"
    assert current_session_id() is None


def test_scope_resets_on_exception() -> None:
    try:
        with session_scope("boom"):
            raise ValueError("x")
    except ValueError:
        pass
    assert current_session_id() is None


def test_propagates_to_child_tasks() -> None:
    """A task spawned inside the scope inherits the session_id (contextvars copy)."""
    seen: list[str | None] = []

    async def _child() -> None:
        seen.append(current_session_id())

    async def _run() -> None:
        with session_scope("task-sess"):
            await asyncio.create_task(_child())

    asyncio.run(_run())
    assert seen == ["task-sess"]
