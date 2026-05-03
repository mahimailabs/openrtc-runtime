"""Drain tests for the coroutine path.

Covers design §8 acceptance criterion 8 (drain test): with N in-flight
sessions, a drain signal must wait for completion before exiting.
``CoroutinePool.drain()`` is the pool-layer primitive a SIGTERM handler
shim would call (the AgentServer layer is exercised by §8.7's parity
test against process mode).
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import JobExecutorType
from livekit.agents.ipc.job_executor import JobStatus

from openrtc.execution.coroutine import CoroutineJobExecutor, CoroutinePool


def _stub_running_job_info(job_id: str) -> Any:
    return SimpleNamespace(
        job=SimpleNamespace(id=job_id),
        fake_job=True,
        worker_id="drain-test",
    )


def _build_pool(*, entrypoint: Any) -> CoroutinePool:
    pool = CoroutinePool(
        initialize_process_fnc=lambda _proc: None,
        job_entrypoint_fnc=entrypoint,
        session_end_fnc=None,
        num_idle_processes=0,
        initialize_timeout=10.0,
        close_timeout=10.0,
        inference_executor=None,
        job_executor_type=JobExecutorType.PROCESS,
        mp_ctx=mp.get_context(),
        memory_warn_mb=0.0,
        memory_limit_mb=0.0,
        http_proxy=None,
        loop=asyncio.new_event_loop(),
        max_concurrent_sessions=10,
    )
    pool._build_job_context = lambda info: SimpleNamespace(  # type: ignore[assignment]
        proc=pool.shared_process,
        job=info.job,
        room=SimpleNamespace(name=f"room-{info.job.id}"),
        session_id=info.job.id,
    )
    return pool


# ---- CoroutineJobExecutor.join semantics ------------------------------


def test_executor_join_on_idle_returns_immediately() -> None:
    ex = CoroutineJobExecutor()
    asyncio.run(ex.join())  # must not raise
    assert ex.status is JobStatus.RUNNING  # untouched default


def test_executor_join_waits_for_in_flight_task() -> None:
    finished = asyncio.Event()

    async def _entrypoint(_ctx: Any) -> None:
        await asyncio.sleep(0.05)
        finished.set()

    ex = CoroutineJobExecutor(
        entrypoint_fnc=_entrypoint,
        context_factory=lambda info: "ctx",  # type: ignore[return-value]
    )

    async def _scenario() -> None:
        await ex.launch_job(_stub_running_job_info("j-1"))
        await ex.join()

    asyncio.run(_scenario())

    assert finished.is_set()
    assert ex.status is JobStatus.SUCCESS


def test_executor_join_is_idempotent_after_completion() -> None:
    async def _entrypoint(_ctx: Any) -> None:
        return None

    ex = CoroutineJobExecutor(
        entrypoint_fnc=_entrypoint,
        context_factory=lambda info: "ctx",  # type: ignore[return-value]
    )

    async def _scenario() -> None:
        await ex.launch_job(_stub_running_job_info("j-1"))
        await ex.join()
        await ex.join()
        await ex.join()

    asyncio.run(_scenario())

    assert ex.status is JobStatus.SUCCESS


def test_executor_join_suppresses_entrypoint_failure() -> None:
    async def _entrypoint(_ctx: Any) -> None:
        raise RuntimeError("boom")

    ex = CoroutineJobExecutor(
        entrypoint_fnc=_entrypoint,
        context_factory=lambda info: "ctx",  # type: ignore[return-value]
    )

    async def _scenario() -> None:
        await ex.launch_job(_stub_running_job_info("j-1"))
        # join must not re-raise the entrypoint's RuntimeError.
        await ex.join()

    asyncio.run(_scenario())

    assert ex.status is JobStatus.FAILED


def test_executor_join_after_cancellation_does_not_raise() -> None:
    async def _entrypoint(_ctx: Any) -> None:
        await asyncio.sleep(60)

    ex = CoroutineJobExecutor(
        entrypoint_fnc=_entrypoint,
        context_factory=lambda info: "ctx",  # type: ignore[return-value]
    )

    async def _scenario() -> None:
        await ex.launch_job(_stub_running_job_info("j-1"))
        await asyncio.sleep(0)  # let the task start
        await ex.aclose()  # cancels + awaits
        await ex.join()  # must absorb the post-cancel state

    asyncio.run(_scenario())

    assert ex.status is JobStatus.FAILED


# ---- CoroutinePool.drain semantics ------------------------------------


def test_pool_drain_on_idle_pool_is_safe() -> None:
    async def _entrypoint(_ctx: Any) -> None:
        return None

    pool = _build_pool(entrypoint=_entrypoint)

    async def _scenario() -> None:
        await pool.start()
        await pool.drain()
        await pool.aclose()

    asyncio.run(_scenario())

    assert pool.draining is True


def test_pool_drain_is_idempotent() -> None:
    async def _entrypoint(_ctx: Any) -> None:
        return None

    pool = _build_pool(entrypoint=_entrypoint)

    async def _scenario() -> None:
        await pool.start()
        await pool.drain()
        await pool.drain()
        await pool.drain()
        await pool.aclose()

    asyncio.run(_scenario())

    assert pool.draining is True


def test_pool_drain_waits_for_three_in_flight_sessions() -> None:
    """§8.8: with 3 in-flight sessions, drain awaits before returning."""

    started_count = 0
    completed: list[str] = []
    release = asyncio.Event()

    async def _entrypoint(ctx: Any) -> None:
        nonlocal started_count
        started_count += 1
        await release.wait()
        completed.append(ctx.session_id)

    pool = _build_pool(entrypoint=_entrypoint)

    async def _scenario() -> None:
        await pool.start()
        for sid in ("a", "b", "c"):
            await pool.launch_job(_stub_running_job_info(sid))
        # Let the entrypoints actually start before we drain.
        while started_count < 3:
            await asyncio.sleep(0.01)
        assert started_count == 3
        assert len(pool.processes) == 3

        async def _release_after_delay() -> None:
            await asyncio.sleep(0.05)
            release.set()

        releaser = asyncio.create_task(_release_after_delay())
        # drain must block until all three sessions complete.
        await pool.drain()
        await releaser
        await pool.aclose()

    asyncio.run(_scenario())

    # All three sessions completed (and only after their release was set).
    assert sorted(completed) == ["a", "b", "c"]
    assert pool.processes == []


def test_pool_drain_rejects_new_launch_jobs() -> None:
    async def _entrypoint(_ctx: Any) -> None:
        await asyncio.sleep(0.01)

    pool = _build_pool(entrypoint=_entrypoint)

    async def _scenario() -> None:
        await pool.start()
        # Drain immediately (no in-flight work) so the flag is set
        # before the next launch.
        await pool.drain()
        with pytest.raises(RuntimeError, match="draining"):
            await pool.launch_job(_stub_running_job_info("late"))
        await pool.aclose()

    asyncio.run(_scenario())


def test_pool_drain_then_aclose_does_not_double_cancel() -> None:
    """drain finishes in-flight cleanly; the subsequent aclose is a no-op."""

    completed: list[str] = []
    release = asyncio.Event()

    async def _entrypoint(ctx: Any) -> None:
        await release.wait()
        completed.append(ctx.session_id)

    pool = _build_pool(entrypoint=_entrypoint)

    async def _scenario() -> None:
        await pool.start()
        await pool.launch_job(_stub_running_job_info("only"))

        async def _release() -> None:
            await asyncio.sleep(0.02)
            release.set()

        releaser = asyncio.create_task(_release())
        await pool.drain()
        await releaser
        await pool.aclose()

    asyncio.run(_scenario())

    # The session ran to completion; drain didn't cancel it.
    assert completed == ["only"]
