"""Per-job error isolation tests for the coroutine path.

Covers design §8 acceptance criterion 5 (sibling isolation) plus the
worker supervisor from design §6.8 (consecutive-failure limit triggers
``aclose()`` so the deployment platform can restart). The wrapper inside
``CoroutineJobExecutor._run_entrypoint`` already suppresses exceptions
and flips status to ``FAILED``; this file proves the properties hold at
the pool level under realistic concurrency.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import JobExecutorType
from livekit.agents.ipc.job_executor import JobStatus

from openrtc.execution.coroutine import CoroutinePool


def _stub_running_job_info(job_id: str) -> Any:
    return SimpleNamespace(
        job=SimpleNamespace(id=job_id),
        fake_job=True,
        worker_id="isolation-test",
    )


def _build_pool(
    *,
    entrypoint: Any,
    consecutive_failure_limit: int = 5,
    on_consecutive_failure_limit: Any = None,
) -> CoroutinePool:
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
        consecutive_failure_limit=consecutive_failure_limit,
        on_consecutive_failure_limit=on_consecutive_failure_limit,
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


async def _drain_until_idle(pool: CoroutinePool) -> None:
    """Wait until every executor's done-callback has fired.

    The done callbacks (which call ``_observe_executor_status``) are
    scheduled via ``loop.call_soon``, not run synchronously when an
    awaited task completes. Polling on ``pool.processes`` is the
    cleanest signal that every callback has actually fired, because
    each callback removes its executor from the live list.
    """
    while pool.processes:
        await asyncio.sleep(0.01)


def test_supervisor_fires_after_n_consecutive_failures() -> None:
    """consecutive_failure_limit=3 + 3 failing sessions -> callback fires once."""

    fired_with: list[int] = []

    def _on_limit(failures: int) -> None:
        fired_with.append(failures)

    async def _entrypoint(_ctx: Any) -> None:
        raise RuntimeError("always boom")

    pool = _build_pool(
        entrypoint=_entrypoint,
        consecutive_failure_limit=3,
        on_consecutive_failure_limit=_on_limit,
    )

    async def _scenario() -> int:
        await pool.start()
        for i in range(3):
            await pool.launch_job(_stub_running_job_info(f"f-{i}"))
        await _drain_until_idle(pool)
        observed = pool.consecutive_failures
        await pool.aclose()
        return observed

    observed = asyncio.run(_scenario())

    assert observed == 3
    # Callback fired exactly once with the failure count at trip time.
    assert fired_with == [3]


def test_supervisor_does_not_fire_below_threshold() -> None:
    fired_with: list[int] = []

    def _on_limit(failures: int) -> None:
        fired_with.append(failures)

    async def _entrypoint(_ctx: Any) -> None:
        raise RuntimeError("boom")

    pool = _build_pool(
        entrypoint=_entrypoint,
        consecutive_failure_limit=5,
        on_consecutive_failure_limit=_on_limit,
    )

    async def _scenario() -> None:
        await pool.start()
        for i in range(4):  # one short of the limit
            await pool.launch_job(_stub_running_job_info(f"f-{i}"))
        await _drain_until_idle(pool)
        await pool.aclose()

    asyncio.run(_scenario())

    assert pool.consecutive_failures == 4
    assert fired_with == []


def test_supervisor_resets_on_success() -> None:
    """Mixed FAIL FAIL SUCCESS FAIL FAIL FAIL must NOT trip a limit of 3."""

    sequence = iter([True, True, False, True, True, True])
    fired_with: list[int] = []

    async def _entrypoint(ctx: Any) -> None:
        # ctx.session_id encodes the planned outcome via the iterator.
        should_fail = next(sequence)
        if should_fail:
            raise RuntimeError("plan FAIL")

    def _on_limit(failures: int) -> None:
        fired_with.append(failures)

    pool = _build_pool(
        entrypoint=_entrypoint,
        consecutive_failure_limit=3,
        on_consecutive_failure_limit=_on_limit,
    )

    async def _scenario() -> None:
        await pool.start()
        # We must launch sequentially and let each one fully observe
        # before launching the next, to enforce the FAIL/SUCCESS
        # interleaving the iterator above defines.
        for i in range(6):
            await pool.launch_job(_stub_running_job_info(f"j-{i}"))
            await _drain_until_idle(pool)
        await pool.aclose()

    asyncio.run(_scenario())

    # After the SUCCESS at index 2, the counter reset to 0; the
    # subsequent three FAILs bring it to 3 and trip the limit once.
    assert pool.consecutive_failures == 3
    assert fired_with == [3]


def test_supervisor_callback_exception_does_not_propagate() -> None:
    """A buggy supervisor callback must not escape and crash the pool."""

    def _bad_callback(_failures: int) -> None:
        raise RuntimeError("bug in supervisor handler")

    async def _entrypoint(_ctx: Any) -> None:
        raise RuntimeError("boom")

    pool = _build_pool(
        entrypoint=_entrypoint,
        consecutive_failure_limit=2,
        on_consecutive_failure_limit=_bad_callback,
    )

    async def _scenario() -> None:
        await pool.start()
        for i in range(2):
            await pool.launch_job(_stub_running_job_info(f"f-{i}"))
        await _drain_until_idle(pool)
        await pool.aclose()

    # Must not raise.
    asyncio.run(_scenario())


def test_agent_pool_threads_consecutive_failure_limit_to_server() -> None:
    """AgentPool.consecutive_failure_limit propagates to _CoroutineAgentServer."""
    from openrtc import AgentPool
    from openrtc.execution.coroutine_server import _CoroutineAgentServer

    pool = AgentPool(consecutive_failure_limit=12)

    assert pool.consecutive_failure_limit == 12
    assert isinstance(pool.server, _CoroutineAgentServer)
    assert pool.server._consecutive_failure_limit == 12


def test_agent_pool_consecutive_failure_limit_validation() -> None:
    from openrtc import AgentPool

    with pytest.raises(TypeError, match="must be an int"):
        AgentPool(consecutive_failure_limit=1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="must be an int"):
        AgentPool(consecutive_failure_limit=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be >= 1"):
        AgentPool(consecutive_failure_limit=0)
