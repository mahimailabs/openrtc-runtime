"""Shape tests for the coroutine executor / pool skeletons.

The real runtime arrives in later iterations. These tests verify only that
:class:`CoroutineJobExecutor` and :class:`CoroutinePool` expose the
structural surface ``AgentServer``/``ProcPool`` need (per
``docs/design/job-executor-protocol.md`` and
``docs/design/proc-pool-surface.md``), and that the unimplemented methods
raise :class:`NotImplementedError` with a helpful hint.
"""

from __future__ import annotations

import asyncio
import inspect
import multiprocessing as mp
from typing import Any

import pytest
from livekit.agents import JobExecutorType
from livekit.agents.ipc.job_executor import JobStatus

from openrtc.execution.coroutine import CoroutineJobExecutor, CoroutinePool


def _build_pool() -> CoroutinePool:
    async def _entry(_ctx: Any) -> None:
        return None

    def _setup(_proc: Any) -> Any:
        return None

    return CoroutinePool(
        initialize_process_fnc=_setup,
        job_entrypoint_fnc=_entry,
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
    )


# ---- CoroutineJobExecutor shape ----


def test_coroutine_job_executor_exposes_protocol_properties() -> None:
    ex = CoroutineJobExecutor()

    assert isinstance(ex.id, str) and len(ex.id) > 0
    assert ex.started is False
    assert ex.user_arguments is None
    assert ex.running_job is None
    assert ex.status is JobStatus.RUNNING


def test_coroutine_job_executor_user_arguments_is_settable() -> None:
    ex = CoroutineJobExecutor()
    ex.user_arguments = {"hello": "world"}
    assert ex.user_arguments == {"hello": "world"}
    ex.user_arguments = None
    assert ex.user_arguments is None


def test_coroutine_job_executor_logging_extra_is_dict() -> None:
    ex = CoroutineJobExecutor()
    extra = ex.logging_extra()
    assert isinstance(extra, dict)
    assert extra["executor_id"] == ex.id


@pytest.mark.parametrize("method_name", ["start", "join"])
def test_coroutine_job_executor_lifecycle_methods_are_unimplemented(
    method_name: str,
) -> None:
    ex = CoroutineJobExecutor()
    method = getattr(ex, method_name)
    assert inspect.iscoroutinefunction(method)
    with pytest.raises(NotImplementedError, match="skeleton"):
        asyncio.run(method())


def test_coroutine_job_executor_launch_job_is_unimplemented() -> None:
    ex = CoroutineJobExecutor()
    with pytest.raises(NotImplementedError, match="skeleton"):
        asyncio.run(ex.launch_job(info=None))  # type: ignore[arg-type]


def test_coroutine_job_executor_initialize_is_noop_and_idempotent() -> None:
    ex = CoroutineJobExecutor()

    async def _twice() -> None:
        await ex.initialize()
        await ex.initialize()

    asyncio.run(_twice())
    # initialize() must not change observable state.
    assert ex.started is False
    assert ex.status is JobStatus.RUNNING
    assert ex.running_job is None


def test_coroutine_job_executor_aclose_with_no_task_is_safe_and_idempotent() -> None:
    ex = CoroutineJobExecutor()

    async def _twice() -> None:
        await ex.aclose()
        await ex.aclose()

    asyncio.run(_twice())
    assert ex.started is False
    # No task ever ran, so status stays at the construction default.
    assert ex.status is JobStatus.RUNNING


def test_coroutine_job_executor_aclose_clears_started_after_synthetic_start() -> None:
    ex = CoroutineJobExecutor()
    ex._started = True  # simulate post-start state until start() lands

    asyncio.run(ex.aclose())

    assert ex.started is False


def test_coroutine_job_executor_aclose_cancels_pending_task_and_marks_failed() -> None:
    ex = CoroutineJobExecutor()

    async def _scenario() -> None:
        async def _long_running() -> None:
            await asyncio.sleep(60)

        ex._task = asyncio.create_task(_long_running())  # white-box stand-in
        # Yield once so the task actually starts.
        await asyncio.sleep(0)
        await ex.aclose()

    asyncio.run(_scenario())

    assert ex.status is JobStatus.FAILED
    assert ex.started is False
    assert ex._task is not None and ex._task.done()


def test_coroutine_job_executor_aclose_preserves_success_when_task_finished() -> None:
    ex = CoroutineJobExecutor()

    async def _scenario() -> None:
        async def _quick() -> None:
            return None

        ex._task = asyncio.create_task(_quick())
        await ex._task  # let it finish cleanly first
        # launch_job's wrapper would normally set SUCCESS; do it here by hand.
        ex._status = JobStatus.SUCCESS
        await ex.aclose()

    asyncio.run(_scenario())

    assert ex.status is JobStatus.SUCCESS
    assert ex.started is False


# ---- CoroutinePool shape ----


def test_coroutine_pool_constructor_accepts_proc_pool_kwargs() -> None:
    pool = _build_pool()
    assert pool.processes == []
    assert pool.target_idle_processes == 0


def test_coroutine_pool_set_target_idle_processes_updates_value() -> None:
    pool = _build_pool()
    pool.set_target_idle_processes(7)
    assert pool.target_idle_processes == 7


def test_coroutine_pool_get_by_job_id_returns_none_for_empty_pool() -> None:
    pool = _build_pool()
    assert pool.get_by_job_id("nonexistent") is None


@pytest.mark.parametrize("method_name", ["start", "aclose"])
def test_coroutine_pool_lifecycle_methods_are_unimplemented(method_name: str) -> None:
    pool = _build_pool()
    method = getattr(pool, method_name)
    assert inspect.iscoroutinefunction(method)
    with pytest.raises(NotImplementedError, match="skeleton"):
        asyncio.run(method())


def test_coroutine_pool_launch_job_is_unimplemented() -> None:
    pool = _build_pool()
    with pytest.raises(NotImplementedError, match="skeleton"):
        asyncio.run(pool.launch_job(info=None))  # type: ignore[arg-type]


def test_coroutine_pool_emits_event_emitter_protocol() -> None:
    """CoroutinePool must subclass utils.EventEmitter so AgentServer can subscribe."""
    pool = _build_pool()
    received: list[Any] = []
    pool.on("process_created", lambda proc: received.append(proc))
    pool.emit("process_created", "sentinel")
    assert received == ["sentinel"]
