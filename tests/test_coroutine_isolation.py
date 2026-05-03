"""Per-job error isolation tests for the coroutine path.

Covers design §8 acceptance criterion 5: a session that raises an
unhandled ``RuntimeError`` must not affect sibling sessions running in
the same coroutine worker. The wrapper inside
``CoroutineJobExecutor._run_entrypoint`` already suppresses exceptions
and flips status to ``FAILED``; this file proves the property holds at
the pool level under realistic concurrency.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from types import SimpleNamespace
from typing import Any

from livekit.agents import JobExecutorType
from livekit.agents.ipc.job_executor import JobStatus

from openrtc.execution.coroutine import CoroutinePool


def _stub_running_job_info(job_id: str) -> Any:
    return SimpleNamespace(
        job=SimpleNamespace(id=job_id),
        fake_job=True,
        worker_id="isolation-test",
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


def test_one_session_raising_does_not_affect_four_siblings() -> None:
    """Five concurrent sessions; the third raises; the other four complete."""

    completed: list[str] = []

    async def _entrypoint(ctx: Any) -> None:
        # Stagger a tiny amount so the failing session is well into the
        # event loop's run queue alongside its siblings.
        await asyncio.sleep(0)
        if ctx.session_id == "session-fail":
            raise RuntimeError("intentional failure for isolation test")
        completed.append(ctx.session_id)

    pool = _build_pool(entrypoint=_entrypoint)

    async def _scenario() -> tuple[list[JobStatus], list[str]]:
        await pool.start()
        for sid in (
            "session-ok-1",
            "session-ok-2",
            "session-fail",
            "session-ok-3",
            "session-ok-4",
        ):
            await pool.launch_job(_stub_running_job_info(sid))

        # Snapshot executors before draining so we can read their final
        # status after their tasks settle (the pool's done callback
        # removes them from `processes` immediately).
        executors_by_session = {
            ex.running_job.job.id: ex  # type: ignore[union-attr]
            for ex in pool.processes
        }
        for ex in pool.processes:
            task = getattr(ex, "_task", None)
            if task is not None:
                await task

        statuses = [
            executors_by_session[sid].status
            for sid in (
                "session-ok-1",
                "session-ok-2",
                "session-fail",
                "session-ok-3",
                "session-ok-4",
            )
        ]
        ordered_completed = sorted(completed)
        await pool.aclose()
        return statuses, ordered_completed

    statuses, ordered_completed = asyncio.run(_scenario())

    # The four siblings ran their entrypoint to completion.
    assert ordered_completed == [
        "session-ok-1",
        "session-ok-2",
        "session-ok-3",
        "session-ok-4",
    ]
    # The four siblings report SUCCESS; the failing one reports FAILED.
    assert statuses == [
        JobStatus.SUCCESS,
        JobStatus.SUCCESS,
        JobStatus.FAILED,
        JobStatus.SUCCESS,
        JobStatus.SUCCESS,
    ]


def test_failing_session_does_not_block_subsequent_launches() -> None:
    """A session failing while another is in flight does not stop new launches."""

    started_marker = asyncio.Event()
    release_marker = asyncio.Event()
    completed: list[str] = []

    async def _entrypoint(ctx: Any) -> None:
        if ctx.session_id == "long-runner":
            started_marker.set()
            await release_marker.wait()
            completed.append(ctx.session_id)
            return
        if ctx.session_id == "boom":
            raise RuntimeError("boom mid-flight")
        completed.append(ctx.session_id)

    pool = _build_pool(entrypoint=_entrypoint)

    async def _scenario() -> list[str]:
        await pool.start()

        await pool.launch_job(_stub_running_job_info("long-runner"))
        await started_marker.wait()

        # Now launch a failing session while long-runner is still in
        # flight, then a fresh successful one.
        await pool.launch_job(_stub_running_job_info("boom"))
        await pool.launch_job(_stub_running_job_info("after-boom"))

        # Drain the failing + after-boom tasks (they finish quickly).
        for ex in list(pool.processes):
            sid = ex.running_job.job.id  # type: ignore[union-attr]
            if sid in ("boom", "after-boom"):
                task = getattr(ex, "_task", None)
                if task is not None:
                    await task

        # The long-runner is still alive and unaffected.
        assert any(
            ex.running_job is not None  # type: ignore[union-attr]
            and ex.running_job.job.id == "long-runner"
            and ex.status is JobStatus.RUNNING
            for ex in pool.processes
        )

        release_marker.set()
        # Drain the rest.
        for ex in list(pool.processes):
            task = getattr(ex, "_task", None)
            if task is not None:
                await task
        await pool.aclose()
        return sorted(completed)

    ordered_completed = asyncio.run(_scenario())

    # boom did not complete; the other two did.
    assert ordered_completed == ["after-boom", "long-runner"]
