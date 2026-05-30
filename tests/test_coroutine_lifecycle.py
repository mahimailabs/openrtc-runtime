"""Lifecycle tests for the coroutine executor (MAH-158 / MAH-160).

Covers the held-open behavior (a live AgentSession keeps the job RUNNING until
shutdown is requested), the teardown sequence (aclose, session-end, shutdown
callbacks, pending-task cancellation, cleanup), the room-disconnect trigger,
cancellation while held open, and a guard that the upstream JobContext private
hooks we depend on still exist.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import JobContext
from livekit.agents.ipc.job_executor import JobStatus

from openrtc.execution.coroutine import CoroutineJobExecutor


def _info(job_id: str = "x") -> Any:
    return SimpleNamespace(
        job=SimpleNamespace(id=job_id), fake_job=True, worker_id="lifecycle"
    )


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeCtx:
    """A JobContext-shaped stub exposing the private hooks the executor uses."""

    def __init__(
        self,
        *,
        with_session: bool = True,
        room_supports_on: bool = False,
        fake_job: bool = False,
    ) -> None:
        self.job = SimpleNamespace(id="x")
        self._fake_job = fake_job
        self._primary_agent_session = _FakeSession() if with_session else None
        self._on_shutdown: Any = None  # overwritten by the executor's wiring
        self._shutdown_callbacks: list[Any] = []
        self._pending_tasks: list[asyncio.Task[Any]] = []
        self.session_end_seen = False
        self.cleanup_seen = False
        self.disconnect_handler: Any = None
        if room_supports_on:
            self.room: Any = SimpleNamespace(on=self._room_on)
        else:
            self.room = SimpleNamespace(name="r")

    def _room_on(self, event: str, handler: Any) -> None:
        if event == "disconnected":
            self.disconnect_handler = handler

    def is_fake_job(self) -> bool:
        return self._fake_job

    def shutdown(self, reason: str = "") -> None:
        self._on_shutdown(reason)  # mirror JobContext.shutdown -> on_shutdown

    def _on_setup(self) -> None:
        pass

    async def _on_session_end(self) -> None:
        self.session_end_seen = True

    def _on_cleanup(self) -> None:
        self.cleanup_seen = True


async def _noop_entry(_ctx: Any) -> None:
    return None


@pytest.mark.asyncio
async def test_executor_holds_open_until_shutdown_then_teardown() -> None:
    """A live session keeps the job RUNNING until shutdown, then tears down."""
    ctx = _FakeCtx()
    executor = CoroutineJobExecutor(
        entrypoint_fnc=_noop_entry, context_factory=lambda info: ctx
    )
    await executor.launch_job(_info())
    await asyncio.sleep(0)  # entrypoint returns; executor now holds open
    assert executor.status is JobStatus.RUNNING

    ctx.shutdown("caller hung up")
    await executor.join()

    assert executor.status is JobStatus.SUCCESS
    assert ctx._primary_agent_session.closed is True
    assert ctx.session_end_seen is True
    assert ctx.cleanup_seen is True


@pytest.mark.asyncio
async def test_fake_job_with_session_completes_on_return() -> None:
    """A fake job (simulate_job) is not held open even with a primary session."""
    ctx = _FakeCtx(fake_job=True)
    executor = CoroutineJobExecutor(
        entrypoint_fnc=_noop_entry, context_factory=lambda info: ctx
    )
    await executor.launch_job(_info())
    await executor.join()
    assert executor.status is JobStatus.SUCCESS
    # Not held open, so the executor did not run teardown / aclose the session.
    assert ctx._primary_agent_session.closed is False


@pytest.mark.asyncio
async def test_executor_completes_immediately_without_session() -> None:
    """A setup-only entrypoint (no primary session) completes on return."""
    ctx = _FakeCtx(with_session=False)
    executor = CoroutineJobExecutor(
        entrypoint_fnc=_noop_entry, context_factory=lambda info: ctx
    )
    await executor.launch_job(_info())
    await executor.join()
    assert executor.status is JobStatus.SUCCESS


@pytest.mark.asyncio
async def test_room_disconnect_triggers_shutdown() -> None:
    """The room 'disconnected' event resolves the held-open session."""
    ctx = _FakeCtx(room_supports_on=True)
    executor = CoroutineJobExecutor(
        entrypoint_fnc=_noop_entry, context_factory=lambda info: ctx
    )
    await executor.launch_job(_info())
    await asyncio.sleep(0)
    assert executor.status is JobStatus.RUNNING
    assert ctx.disconnect_handler is not None

    ctx.disconnect_handler()  # simulate room "disconnected"
    ctx.disconnect_handler()  # idempotent: shutdown already requested
    await executor.join()
    assert executor.status is JobStatus.SUCCESS


@pytest.mark.asyncio
async def test_held_open_teardown_tolerates_missing_hooks() -> None:
    """Teardown tolerates a primary session without aclose and absent hooks."""
    ctx = SimpleNamespace(
        job=SimpleNamespace(id="x"),
        room=SimpleNamespace(name="r"),
        _primary_agent_session=object(),  # no aclose()
        _on_shutdown=None,  # replaced by the executor's resolver on launch
    )
    executor = CoroutineJobExecutor(
        entrypoint_fnc=_noop_entry, context_factory=lambda info: ctx
    )
    await executor.launch_job(_info())
    await asyncio.sleep(0)
    assert executor.status is JobStatus.RUNNING

    ctx._on_shutdown("done")  # the wiring replaced this with the resolver
    await executor.join()
    assert executor.status is JobStatus.SUCCESS


@pytest.mark.asyncio
async def test_shutdown_callbacks_and_pending_tasks_run_on_teardown() -> None:
    """Shutdown callbacks run with the reason; pending tasks are cancelled."""
    ctx = _FakeCtx()
    ran: list[str] = []

    async def _good_cb(reason: str) -> None:
        ran.append(reason)

    async def _bad_cb(_reason: str) -> None:
        raise RuntimeError("callback boom")  # must not fail the job

    ctx._shutdown_callbacks = [_good_cb, _bad_cb]

    executor = CoroutineJobExecutor(
        entrypoint_fnc=_noop_entry, context_factory=lambda info: ctx
    )
    await executor.launch_job(_info())
    await asyncio.sleep(0)

    async def _never() -> None:
        await asyncio.sleep(60)

    pending = asyncio.ensure_future(_never())
    ctx._pending_tasks.append(pending)

    ctx.shutdown("done")
    await executor.join()

    assert ran == ["done"]
    assert pending.cancelled()
    assert executor.status is JobStatus.SUCCESS


@pytest.mark.asyncio
async def test_aclose_while_held_open_marks_failed() -> None:
    """Cancelling a held-open session (drain/aclose) flips status to FAILED."""
    ctx = _FakeCtx()
    executor = CoroutineJobExecutor(
        entrypoint_fnc=_noop_entry, context_factory=lambda info: ctx
    )
    await executor.launch_job(_info())
    await asyncio.sleep(0)
    assert executor.status is JobStatus.RUNNING

    await executor.aclose()
    assert executor.status is JobStatus.FAILED


def test_upstream_jobcontext_hooks_present() -> None:
    """Guard: fail loudly if a livekit-agents upgrade renames the hooks we use."""
    names = set(dir(JobContext)) | set(JobContext.__init__.__code__.co_names)
    for attr in (
        "_on_setup",
        "_on_session_end",
        "_on_cleanup",
        "_shutdown_callbacks",
        "_pending_tasks",
        "_primary_agent_session",
        "_on_shutdown",
    ):
        assert attr in names, f"livekit-agents JobContext no longer exposes {attr!r}"
