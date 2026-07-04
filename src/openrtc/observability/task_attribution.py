"""asyncio task -> session attribution (foundation for MAH-89 / MAH-90).

A custom task factory tags every ``asyncio.Task`` created within a session's
context with that session's id, read from :mod:`session_context` at task-creation
time (``asyncio`` copies the context into the task, so the tag is stable for the
task's life). This is the task graph that CPU attribution (MAH-89) and the
slow-session detector (MAH-90) both walk to answer "which session owns this
task". The factory chains onto any existing factory so it never clobbers one.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

from openrtc.observability.session_context import current_session_id

__all__ = [
    "install_session_task_factory",
    "live_task_session_ids",
    "task_session_id",
]

_SESSION_ATTR = "_openrtc_session_id"


def task_session_id(task: asyncio.Task[Any]) -> str | None:
    """Return the ``session_id`` tagged on ``task`` at creation, or ``None``."""
    return getattr(task, _SESSION_ATTR, None)


def install_session_task_factory(
    loop: asyncio.AbstractEventLoop,
) -> Callable[[], None]:
    """Tag every task the loop creates with the current session_id; return a restore fn.

    Chains onto any pre-existing task factory rather than replacing it.
    """
    previous = loop.get_task_factory()

    def _factory(
        loop_: asyncio.AbstractEventLoop, coro: Any, **kwargs: Any
    ) -> asyncio.Future[Any]:
        if previous is not None:
            task = previous(loop_, coro, **kwargs)
        else:
            task = asyncio.Task(coro, loop=loop_, **kwargs)
        with contextlib.suppress(Exception):
            task._openrtc_session_id = current_session_id()  # type: ignore[attr-defined]
        return task

    loop.set_task_factory(_factory)

    def _restore() -> None:
        loop.set_task_factory(previous)

    return _restore


def live_task_session_ids() -> list[str]:
    """Return the session_ids of every live (not-done) task that carries a tag."""
    ids: list[str] = []
    for task in asyncio.all_tasks():
        if task.done():
            continue
        session_id = task_session_id(task)
        if session_id is not None:
            ids.append(session_id)
    return ids
