"""asyncio task -> session tagging foundation (MAH-89 / MAH-90).

The task factory tags each task with the session_id active where it was created,
so CPU attribution and slow-session detection can map a task back to its session.
"""

from __future__ import annotations

import asyncio

import pytest

from openrtc.observability.session_context import session_scope
from openrtc.observability.task_attribution import (
    install_session_task_factory,
    live_task_session_ids,
    task_session_id,
)


@pytest.mark.asyncio
async def test_factory_tags_task_with_creating_session() -> None:
    loop = asyncio.get_running_loop()
    restore = install_session_task_factory(loop)
    try:

        async def _noop() -> None:
            await asyncio.sleep(0)

        with session_scope("s1"):
            task = asyncio.ensure_future(_noop())
        assert task_session_id(task) == "s1"
        await task
    finally:
        restore()


@pytest.mark.asyncio
async def test_task_outside_scope_has_no_tag() -> None:
    loop = asyncio.get_running_loop()
    restore = install_session_task_factory(loop)
    try:

        async def _noop() -> None:
            await asyncio.sleep(0)

        task = asyncio.ensure_future(_noop())
        assert task_session_id(task) is None
        await task
    finally:
        restore()


@pytest.mark.asyncio
async def test_live_task_session_ids_lists_tagged_live_tasks() -> None:
    loop = asyncio.get_running_loop()
    restore = install_session_task_factory(loop)
    try:
        gate = asyncio.Event()

        async def _hold() -> None:
            await gate.wait()

        with session_scope("live-a"):
            t1 = asyncio.ensure_future(_hold())
        with session_scope("live-b"):
            t2 = asyncio.ensure_future(_hold())
        await asyncio.sleep(0)  # let them start and register

        ids = live_task_session_ids()
        assert "live-a" in ids
        assert "live-b" in ids

        gate.set()
        await asyncio.gather(t1, t2)
    finally:
        restore()


@pytest.mark.asyncio
async def test_restore_reinstalls_previous_factory() -> None:
    loop = asyncio.get_running_loop()
    original = loop.get_task_factory()
    restore = install_session_task_factory(loop)
    assert loop.get_task_factory() is not original
    restore()
    assert loop.get_task_factory() is original


@pytest.mark.asyncio
async def test_factory_chains_onto_existing_factory() -> None:
    loop = asyncio.get_running_loop()
    created: list[str] = []

    def _prev_factory(loop_, coro, **kwargs):  # type: ignore[no-untyped-def]
        created.append("prev")
        return asyncio.Task(coro, loop=loop_, **kwargs)

    loop.set_task_factory(_prev_factory)  # type: ignore[arg-type]
    restore = install_session_task_factory(loop)
    try:

        async def _noop() -> None:
            await asyncio.sleep(0)

        with session_scope("chained"):
            task = asyncio.ensure_future(_noop())
        # The previous factory ran (chained), and our tag was still applied.
        assert created == ["prev"]
        assert task_session_id(task) == "chained"
        await task
    finally:
        restore()
        loop.set_task_factory(None)
