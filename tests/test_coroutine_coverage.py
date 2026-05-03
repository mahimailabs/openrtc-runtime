"""Coverage-completion tests for ``openrtc.execution.coroutine``.

Targets specific uncovered branches the higher-level test files don't
naturally hit (defensive raises, idempotent early-returns, the no-op
inference executor, direct CoroutinePool validation, the real
``_build_job_context`` fake-job path).
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import JobExecutorType

from openrtc.execution.coroutine import (
    _NOOP_INFERENCE_EXECUTOR,
    CoroutinePool,
    _NoOpInferenceExecutor,
)


def test_noop_inference_executor_raises_on_do_inference() -> None:
    """The fallback stub fails loudly so a misconfigured plugin is visible."""
    stub = _NoOpInferenceExecutor()

    async def _scenario() -> None:
        with pytest.raises(RuntimeError, match="without an inference_executor"):
            await stub.do_inference("end_of_turn", b"")

    asyncio.run(_scenario())


def test_module_level_noop_executor_is_a_singleton() -> None:
    """The shared singleton is what the pool's _build_job_context uses."""
    assert isinstance(_NOOP_INFERENCE_EXECUTOR, _NoOpInferenceExecutor)


def _kwargs() -> dict[str, Any]:
    return {
        "initialize_process_fnc": lambda _proc: None,
        "job_entrypoint_fnc": lambda _ctx: None,
        "session_end_fnc": None,
        "num_idle_processes": 0,
        "initialize_timeout": 5.0,
        "close_timeout": 10.0,
        "inference_executor": None,
        "job_executor_type": JobExecutorType.PROCESS,
        "mp_ctx": mp.get_context(),
        "memory_warn_mb": 0.0,
        "memory_limit_mb": 0.0,
        "http_proxy": None,
        "loop": asyncio.new_event_loop(),
    }


def test_coroutine_pool_consecutive_failure_limit_default_is_5() -> None:
    pool = CoroutinePool(**_kwargs())
    assert pool.consecutive_failure_limit == 5


def test_coroutine_pool_consecutive_failure_limit_rejects_non_int() -> None:
    with pytest.raises(TypeError, match="must be an int"):
        CoroutinePool(**_kwargs(), consecutive_failure_limit=2.5)  # type: ignore[arg-type]


def test_coroutine_pool_consecutive_failure_limit_rejects_bool() -> None:
    with pytest.raises(TypeError, match="must be an int"):
        CoroutinePool(**_kwargs(), consecutive_failure_limit=True)  # type: ignore[arg-type]


def test_coroutine_pool_consecutive_failure_limit_rejects_zero_or_negative() -> None:
    with pytest.raises(ValueError, match="must be >= 1"):
        CoroutinePool(**_kwargs(), consecutive_failure_limit=0)
    with pytest.raises(ValueError, match="must be >= 1"):
        CoroutinePool(**_kwargs(), consecutive_failure_limit=-3)


def test_on_executor_done_is_idempotent_for_untracked_executor() -> None:
    """Calling _on_executor_done on an executor that was never tracked is a no-op."""
    pool = CoroutinePool(**_kwargs())

    sentinel = SimpleNamespace(running_job=None, status=None)
    closed: list[Any] = []
    pool.on("process_closed", lambda proc: closed.append(proc))

    pool._on_executor_done(sentinel)  # type: ignore[arg-type]

    assert closed == []
    assert pool._executors == []


def test_build_job_context_real_path_uses_mock_room_for_fake_job() -> None:
    """`_build_job_context(info)` with `fake_job=True` builds a real JobContext."""

    pool = CoroutinePool(**_kwargs())

    async def _scenario() -> tuple[Any, Any]:
        await pool.start()
        info_obj = SimpleNamespace(
            job=SimpleNamespace(id="ctx-build-test", room=SimpleNamespace(name="r")),
            fake_job=True,
            worker_id="bench",
            accept_arguments=SimpleNamespace(identity="i", name="", metadata=""),
            url="ws://x",
            token="t",
        )
        ctx = pool._build_job_context(info_obj)
        return ctx, info_obj

    ctx, info_obj = asyncio.run(_scenario())

    # JobContext stored the proc and info references.
    assert ctx._proc is pool.shared_process
    assert ctx._info is info_obj
    # _on_connect / _on_shutdown are inert callables.
    ctx._on_connect()
    ctx._on_shutdown("test")


def test_build_job_context_before_start_raises() -> None:
    """The fake-room branch still requires the singleton JobProcess."""
    pool = CoroutinePool(**_kwargs())
    info = SimpleNamespace(job=SimpleNamespace(id="x"), fake_job=True)
    with pytest.raises(RuntimeError, match="start.. must complete"):
        pool._build_job_context(info)  # type: ignore[arg-type]


def test_consume_cancelled_task_exception_swallows_invalid_state_error() -> None:
    """`task.exception()` on a not-done task raises InvalidStateError; swallow it."""
    from openrtc.execution.coroutine import _consume_cancelled_task_exception

    async def _scenario() -> None:
        async def _runs_forever() -> None:
            await asyncio.sleep(60)

        loop = asyncio.get_running_loop()
        task = loop.create_task(_runs_forever())
        try:
            assert not task.done()
            _consume_cancelled_task_exception(task)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    asyncio.run(_scenario())


def test_executor_join_swallows_unexpected_exception_from_task() -> None:
    """`join()` defends against tasks that bypass _run_entrypoint and raise directly."""
    from openrtc.execution.coroutine import CoroutineJobExecutor, JobStatus

    executor = CoroutineJobExecutor()

    async def _scenario() -> None:
        loop = asyncio.get_running_loop()

        async def _raises() -> None:
            raise RuntimeError("bypass-wrapper")

        executor._task = loop.create_task(_raises())
        executor._status = JobStatus.RUNNING
        await executor.join()

    asyncio.run(_scenario())


def test_executor_aclose_swallows_non_cancelled_exception_after_cancel() -> None:
    """`aclose()` swallows whatever the task raises post-cancel (not just CancelledError)."""
    from openrtc.execution.coroutine import CoroutineJobExecutor, JobStatus

    executor = CoroutineJobExecutor()

    async def _scenario() -> None:
        loop = asyncio.get_running_loop()

        async def _swap_cancel_for_runtime_error() -> None:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise RuntimeError("post-cancel runtime") from None

        executor._task = loop.create_task(_swap_cancel_for_runtime_error())
        executor._status = JobStatus.RUNNING
        executor._started = True
        await asyncio.sleep(0)
        await executor.aclose()
        assert executor.status is JobStatus.FAILED
        assert executor.started is False

    asyncio.run(_scenario())


def test_executor_join_swallows_cancelled_error_from_in_flight_task() -> None:
    """`join()` swallows a CancelledError raised by the in-flight task."""
    from openrtc.execution.coroutine import CoroutineJobExecutor, JobStatus

    executor = CoroutineJobExecutor()

    async def _scenario() -> None:
        loop = asyncio.get_running_loop()

        async def _runs_until_cancelled() -> None:
            await asyncio.sleep(60)

        task = loop.create_task(_runs_until_cancelled())
        executor._task = task
        executor._status = JobStatus.RUNNING

        async def _race_cancel() -> None:
            await asyncio.sleep(0)
            task.cancel()

        cancel_task = loop.create_task(_race_cancel())
        await executor.join()
        await cancel_task

    asyncio.run(_scenario())


def test_build_job_context_real_room_branch_runs_when_fake_job_is_false() -> None:
    """`info.fake_job=False` triggers the real `rtc.Room()` construction branch."""
    from livekit import rtc

    pool = CoroutinePool(**_kwargs())

    async def _scenario() -> object:
        await pool.start()
        info = SimpleNamespace(
            job=SimpleNamespace(id="real-room-test", room=SimpleNamespace(name="r")),
            fake_job=False,
            worker_id="w",
            accept_arguments=SimpleNamespace(identity="i", name="", metadata=""),
            url="ws://x",
            token="t",
        )
        return pool._build_job_context(info)

    ctx = asyncio.run(_scenario())

    assert isinstance(ctx._room, rtc.Room)


def test_kill_does_not_flip_status_when_executor_is_not_running() -> None:
    """Branch 231->233: kill() preserves a non-RUNNING terminal status."""
    from openrtc.execution.coroutine import CoroutineJobExecutor, JobStatus

    executor = CoroutineJobExecutor()

    async def _scenario() -> None:
        loop = asyncio.get_running_loop()

        async def _runs_forever() -> None:
            await asyncio.sleep(60)

        executor._task = loop.create_task(_runs_forever())
        executor._status = JobStatus.FAILED  # set externally before kill
        executor.kill()
        await asyncio.sleep(0)

    asyncio.run(_scenario())

    assert executor.status is JobStatus.FAILED


def test_run_entrypoint_success_does_not_flip_status_when_already_set() -> None:
    """Branch 279->293: SUCCESS path skips the status flip when status was changed externally."""
    from openrtc.execution.coroutine import CoroutineJobExecutor, JobStatus

    completed: list[bool] = []

    async def _entrypoint(_ctx: Any) -> None:
        completed.append(True)

    executor = CoroutineJobExecutor(entrypoint_fnc=_entrypoint)

    async def _scenario() -> None:
        executor._status = JobStatus.SUCCESS  # external set before completion
        await executor._run_entrypoint(SimpleNamespace())  # type: ignore[arg-type]

    asyncio.run(_scenario())

    assert completed == [True]
    assert executor.status is JobStatus.SUCCESS  # unchanged


def test_run_entrypoint_exception_does_not_flip_status_when_already_set() -> None:
    """Branch 286->288: exception path skips the status flip when status was changed externally."""
    from openrtc.execution.coroutine import CoroutineJobExecutor, JobStatus

    async def _entrypoint(_ctx: Any) -> None:
        raise RuntimeError("expected")

    executor = CoroutineJobExecutor(entrypoint_fnc=_entrypoint)

    async def _scenario() -> None:
        executor._status = JobStatus.SUCCESS  # external set before raise
        await executor._run_entrypoint(SimpleNamespace())  # type: ignore[arg-type]

    asyncio.run(_scenario())

    assert executor.status is JobStatus.SUCCESS  # unchanged (defensive override)


def test_pool_aclose_timeout_skips_executors_without_kill_method() -> None:
    """Branch 528->526: aclose escalation tolerates executors that lack `kill`."""
    pool = CoroutinePool(**_kwargs())
    pool._close_timeout = 0.05  # force timeout fast

    class _NoKillExecutor:
        async def aclose(self) -> None:
            await asyncio.sleep(60)  # never returns within close_timeout

    no_kill = _NoKillExecutor()
    pool._executors.append(no_kill)  # type: ignore[arg-type]

    async def _scenario() -> None:
        await pool.start()
        await pool.aclose()

    asyncio.run(_scenario())
    # Branch covered: the `if callable(kill_method):` guard skipped no_kill.


def test_pool_launch_job_skips_done_callback_when_executor_has_no_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Branch 571->578: launch_job emits process_job_launched even when the executor sets no _task."""
    pool = CoroutinePool(**_kwargs())
    pool._build_job_context = lambda info: SimpleNamespace(  # type: ignore[assignment]
        proc=pool.shared_process, job=info.job, room=None
    )

    launched: list[Any] = []
    pool.on("process_job_launched", lambda ex: launched.append(ex))

    async def _scenario() -> None:
        await pool.start()

        original_build = pool._build_executor

        def _build_no_task() -> Any:
            ex = original_build()

            async def _no_task(_info: Any) -> None:
                ex._task = None  # explicitly leave task None

            ex.launch_job = _no_task  # type: ignore[method-assign]
            return ex

        pool._build_executor = _build_no_task  # type: ignore[assignment]

        info = SimpleNamespace(job=SimpleNamespace(id="no-task"), fake_job=True)
        await pool.launch_job(info)
        await pool.aclose()

    asyncio.run(_scenario())
    assert len(launched) == 1


def test_pool_consecutive_failure_limit_with_no_callback_does_not_raise() -> None:
    """Branch 679->exit: the failure-limit branch tolerates a None callback."""
    from openrtc.execution.coroutine import JobStatus

    kwargs = _kwargs()
    pool = CoroutinePool(
        **kwargs,
        consecutive_failure_limit=2,
        on_consecutive_failure_limit=None,
    )

    failed_executor_a = SimpleNamespace(running_job=None, status=JobStatus.FAILED)
    failed_executor_b = SimpleNamespace(running_job=None, status=JobStatus.FAILED)
    pool._executors.append(failed_executor_a)  # type: ignore[arg-type]
    pool._executors.append(failed_executor_b)  # type: ignore[arg-type]

    pool._on_executor_done(failed_executor_a)  # type: ignore[arg-type]
    pool._on_executor_done(failed_executor_b)  # type: ignore[arg-type]

    assert pool.consecutive_failures == 2
    assert pool._failure_limit_fired is True


def test_launch_job_re_raises_when_executor_launch_job_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the per-executor launch_job raises, the pool emits process_closed and re-raises."""
    pool = CoroutinePool(**_kwargs())
    pool._build_job_context = lambda info: SimpleNamespace(  # type: ignore[assignment]
        proc=pool.shared_process, job=info.job, room=None
    )

    closed: list[Any] = []
    pool.on("process_closed", lambda proc: closed.append(proc))

    async def _scenario() -> None:
        await pool.start()

        original_build = pool._build_executor

        def _bad_build() -> Any:
            ex = original_build()

            async def _raise(_info: Any) -> None:
                raise RuntimeError("simulated executor refusal")

            ex.launch_job = _raise  # type: ignore[method-assign]
            return ex

        pool._build_executor = _bad_build  # type: ignore[assignment]

        info = SimpleNamespace(job=SimpleNamespace(id="boom"), fake_job=True)
        with pytest.raises(RuntimeError, match="simulated executor refusal"):
            await pool.launch_job(info)
        await pool.aclose()

    asyncio.run(_scenario())

    assert len(closed) == 1
    assert pool.processes == []
