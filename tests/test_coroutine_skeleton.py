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


def test_coroutine_job_executor_launch_job_requires_entrypoint() -> None:
    ex = CoroutineJobExecutor(context_factory=lambda info: object())  # type: ignore[arg-type, return-value]
    with pytest.raises(RuntimeError, match="entrypoint_fnc"):
        asyncio.run(ex.launch_job(info=None))  # type: ignore[arg-type]


def test_coroutine_job_executor_launch_job_requires_context_factory() -> None:
    async def _entry(_ctx: Any) -> None:
        return None

    ex = CoroutineJobExecutor(entrypoint_fnc=_entry)
    with pytest.raises(RuntimeError, match="context_factory"):
        asyncio.run(ex.launch_job(info=None))  # type: ignore[arg-type]


def _stub_info(job_id: str = "job-1") -> Any:
    """Minimal RunningJobInfo stand-in (only `.job.id` is touched downstream)."""
    from types import SimpleNamespace

    return SimpleNamespace(job=SimpleNamespace(id=job_id))


def test_coroutine_job_executor_launch_job_marks_success_on_clean_completion() -> None:
    seen: list[Any] = []

    async def _entry(ctx: Any) -> None:
        seen.append(ctx)

    ex = CoroutineJobExecutor(
        entrypoint_fnc=_entry,
        context_factory=lambda info: f"ctx-for-{info.job.id}",  # type: ignore[return-value]
    )

    async def _scenario() -> None:
        await ex.launch_job(_stub_info())
        assert ex._task is not None
        await ex._task

    asyncio.run(_scenario())

    assert seen == ["ctx-for-job-1"]
    assert ex.status is JobStatus.SUCCESS
    assert ex.running_job is not None
    assert ex.running_job.job.id == "job-1"


def test_coroutine_job_executor_launch_job_marks_failed_without_propagating() -> None:
    async def _entry(_ctx: Any) -> None:
        raise RuntimeError("boom inside entrypoint")

    ex = CoroutineJobExecutor(
        entrypoint_fnc=_entry,
        context_factory=lambda info: "ctx",  # type: ignore[return-value]
    )

    async def _scenario() -> None:
        await ex.launch_job(_stub_info())
        assert ex._task is not None
        # The task must not propagate the exception out of the wrapper.
        await ex._task

    asyncio.run(_scenario())

    assert ex.status is JobStatus.FAILED


def test_coroutine_job_executor_launch_job_calls_session_end_fnc_on_success() -> None:
    end_calls: list[Any] = []

    async def _entry(_ctx: Any) -> None:
        return None

    async def _end(ctx: Any) -> None:
        end_calls.append(ctx)

    ex = CoroutineJobExecutor(
        entrypoint_fnc=_entry,
        session_end_fnc=_end,
        context_factory=lambda info: "ctx-success",  # type: ignore[return-value]
    )

    async def _scenario() -> None:
        await ex.launch_job(_stub_info())
        assert ex._task is not None
        await ex._task

    asyncio.run(_scenario())

    assert end_calls == ["ctx-success"]
    assert ex.status is JobStatus.SUCCESS


def test_coroutine_job_executor_launch_job_calls_session_end_fnc_on_failure() -> None:
    end_calls: list[Any] = []

    async def _entry(_ctx: Any) -> None:
        raise RuntimeError("boom")

    async def _end(ctx: Any) -> None:
        end_calls.append(ctx)

    ex = CoroutineJobExecutor(
        entrypoint_fnc=_entry,
        session_end_fnc=_end,
        context_factory=lambda info: "ctx-failure",  # type: ignore[return-value]
    )

    async def _scenario() -> None:
        await ex.launch_job(_stub_info())
        assert ex._task is not None
        await ex._task

    asyncio.run(_scenario())

    assert end_calls == ["ctx-failure"]
    assert ex.status is JobStatus.FAILED


def test_coroutine_job_executor_session_end_fnc_exception_is_suppressed() -> None:
    async def _entry(_ctx: Any) -> None:
        return None

    async def _end(_ctx: Any) -> None:
        raise RuntimeError("session_end boom")

    ex = CoroutineJobExecutor(
        entrypoint_fnc=_entry,
        session_end_fnc=_end,
        context_factory=lambda info: "ctx",  # type: ignore[return-value]
    )

    async def _scenario() -> None:
        await ex.launch_job(_stub_info())
        assert ex._task is not None
        await ex._task

    asyncio.run(_scenario())

    # Entrypoint succeeded; session_end_fnc exception must not flip status.
    assert ex.status is JobStatus.SUCCESS


def test_coroutine_job_executor_launch_job_rejects_concurrent_launch() -> None:
    async def _entry(_ctx: Any) -> None:
        await asyncio.sleep(60)

    ex = CoroutineJobExecutor(
        entrypoint_fnc=_entry,
        context_factory=lambda info: "ctx",  # type: ignore[return-value]
    )

    async def _scenario() -> None:
        await ex.launch_job(_stub_info("first"))
        try:
            with pytest.raises(RuntimeError, match="in-flight job"):
                await ex.launch_job(_stub_info("second"))
        finally:
            await ex.aclose()

    asyncio.run(_scenario())

    assert ex.running_job is not None
    assert ex.running_job.job.id == "first"


def test_coroutine_job_executor_kill_on_idle_executor_is_safe() -> None:
    ex = CoroutineJobExecutor()

    ex.kill()

    # No task ran, so status stays at the construction default and no
    # exception is raised.
    assert ex.status is JobStatus.RUNNING
    assert ex.started is False


def test_coroutine_job_executor_kill_is_idempotent() -> None:
    ex = CoroutineJobExecutor()

    ex.kill()
    ex.kill()

    assert ex.status is JobStatus.RUNNING
    assert ex.started is False


def test_coroutine_job_executor_kill_returns_immediately_and_marks_failed() -> None:
    async def _entry(_ctx: Any) -> None:
        await asyncio.sleep(60)

    ex = CoroutineJobExecutor(
        entrypoint_fnc=_entry,
        context_factory=lambda info: "ctx",  # type: ignore[return-value]
    )

    async def _scenario() -> tuple[bool, asyncio.Task[None] | None]:
        await ex.launch_job(_stub_info())
        await asyncio.sleep(0)  # let the task actually start
        ex.kill()
        # kill() is synchronous; it must not have awaited the task.
        task = ex._task
        was_done_at_kill_return = bool(task is not None and task.done())
        # Drain the event loop so the cancellation takes effect.
        await asyncio.sleep(0)
        return was_done_at_kill_return, task

    was_done_at_kill_return, task = asyncio.run(_scenario())

    # Status flipped immediately even though the task may still be settling.
    assert ex.status is JobStatus.FAILED
    assert ex.started is False
    # The task object exists and (after the loop yielded) is done.
    assert task is not None and task.done()
    # The kill() call itself returned before awaiting cancellation.
    assert was_done_at_kill_return is False


def test_coroutine_job_executor_kill_preserves_success_when_task_already_done() -> None:
    async def _entry(_ctx: Any) -> None:
        return None

    ex = CoroutineJobExecutor(
        entrypoint_fnc=_entry,
        context_factory=lambda info: "ctx",  # type: ignore[return-value]
    )

    async def _scenario() -> None:
        await ex.launch_job(_stub_info())
        assert ex._task is not None
        await ex._task

    asyncio.run(_scenario())
    assert ex.status is JobStatus.SUCCESS

    ex.kill()

    # kill() must not overwrite a SUCCESS status.
    assert ex.status is JobStatus.SUCCESS
    assert ex.started is False


def test_coroutine_job_executor_aclose_cancels_in_flight_launch_job() -> None:
    async def _entry(_ctx: Any) -> None:
        await asyncio.sleep(60)

    ex = CoroutineJobExecutor(
        entrypoint_fnc=_entry,
        context_factory=lambda info: "ctx",  # type: ignore[return-value]
    )

    async def _scenario() -> None:
        await ex.launch_job(_stub_info())
        # Yield once so the entrypoint task starts.
        await asyncio.sleep(0)
        await ex.aclose()

    asyncio.run(_scenario())

    assert ex.status is JobStatus.FAILED
    assert ex.started is False
    assert ex._task is not None and ex._task.done()


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


@pytest.mark.parametrize("method_name", ["aclose"])
def test_coroutine_pool_lifecycle_methods_are_unimplemented(method_name: str) -> None:
    pool = _build_pool()
    method = getattr(pool, method_name)
    assert inspect.iscoroutinefunction(method)
    with pytest.raises(NotImplementedError, match="skeleton"):
        asyncio.run(method())


def _build_pool_with_setup(
    setup_fnc: Any, *, initialize_timeout: float = 5.0
) -> CoroutinePool:
    async def _entry(_ctx: Any) -> None:
        return None

    return CoroutinePool(
        initialize_process_fnc=setup_fnc,
        job_entrypoint_fnc=_entry,
        session_end_fnc=None,
        num_idle_processes=0,
        initialize_timeout=initialize_timeout,
        close_timeout=10.0,
        inference_executor=None,
        job_executor_type=JobExecutorType.PROCESS,
        mp_ctx=mp.get_context(),
        memory_warn_mb=0.0,
        memory_limit_mb=0.0,
        http_proxy="http://proxy.example",
        loop=asyncio.new_event_loop(),
    )


def test_coroutine_pool_start_invokes_setup_fnc_once_with_singleton_proc() -> None:
    seen_procs: list[Any] = []

    def _setup(proc: Any) -> None:
        seen_procs.append(proc)
        proc.userdata["loaded"] = True

    pool = _build_pool_with_setup(_setup)

    assert pool.started is False
    assert pool.shared_process is None

    asyncio.run(pool.start())

    assert pool.started is True
    assert pool.shared_process is not None
    assert pool.shared_process.userdata["loaded"] is True
    assert seen_procs == [pool.shared_process]


def test_coroutine_pool_start_is_idempotent() -> None:
    call_count = 0

    def _setup(_proc: Any) -> None:
        nonlocal call_count
        call_count += 1

    pool = _build_pool_with_setup(_setup)

    async def _scenario() -> None:
        await pool.start()
        await pool.start()
        await pool.start()

    asyncio.run(_scenario())

    assert call_count == 1
    assert pool.started is True


def test_coroutine_pool_start_awaits_async_setup_fnc() -> None:
    invoked: list[Any] = []

    async def _setup(proc: Any) -> None:
        await asyncio.sleep(0)
        invoked.append(proc)
        proc.userdata["async_loaded"] = True

    pool = _build_pool_with_setup(_setup)

    asyncio.run(pool.start())

    assert pool.started is True
    assert pool.shared_process is not None
    assert pool.shared_process.userdata["async_loaded"] is True
    assert invoked == [pool.shared_process]


def test_coroutine_pool_start_respects_initialize_timeout() -> None:
    async def _slow_setup(_proc: Any) -> None:
        await asyncio.sleep(60)

    pool = _build_pool_with_setup(_slow_setup, initialize_timeout=0.1)

    with pytest.raises(TimeoutError):
        asyncio.run(pool.start())

    assert pool.started is False
    assert pool.shared_process is None


def test_coroutine_pool_shared_process_propagates_http_proxy() -> None:
    def _setup(_proc: Any) -> None:
        return None

    pool = _build_pool_with_setup(_setup)

    asyncio.run(pool.start())

    assert pool.shared_process is not None
    assert pool.shared_process.http_proxy == "http://proxy.example"


def test_coroutine_pool_launch_job_requires_start_first() -> None:
    pool = _build_pool()
    with pytest.raises(RuntimeError, match="start.. must complete"):
        asyncio.run(pool.launch_job(info=None))  # type: ignore[arg-type]


def _build_started_pool(
    *,
    entrypoint: Any,
    session_end: Any = None,
) -> CoroutinePool:
    pool = CoroutinePool(
        initialize_process_fnc=lambda _proc: None,
        job_entrypoint_fnc=entrypoint,
        session_end_fnc=session_end,
        num_idle_processes=0,
        initialize_timeout=5.0,
        close_timeout=10.0,
        inference_executor=None,
        job_executor_type=JobExecutorType.PROCESS,
        mp_ctx=mp.get_context(),
        memory_warn_mb=0.0,
        memory_limit_mb=0.0,
        http_proxy=None,
        loop=asyncio.new_event_loop(),
    )
    asyncio.run(pool.start())
    return pool


def _stub_running_job_info(job_id: str = "job-1") -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(job=SimpleNamespace(id=job_id), fake_job=True)


def test_coroutine_pool_launch_job_creates_executor_and_emits_events() -> None:
    seen_ctxs: list[Any] = []

    async def _entry(ctx: Any) -> None:
        seen_ctxs.append(ctx)

    pool = _build_started_pool(entrypoint=_entry)
    pool._build_job_context = lambda info: f"ctx-{info.job.id}"  # type: ignore[assignment, return-value]

    events: list[tuple[str, Any]] = []
    for name in (
        "process_created",
        "process_started",
        "process_ready",
        "process_job_launched",
        "process_closed",
    ):
        pool.on(name, lambda proc, _name=name: events.append((_name, proc)))  # type: ignore[misc]

    async def _scenario() -> None:
        await pool.launch_job(_stub_running_job_info())
        # Drain the entrypoint task so process_closed fires.
        assert pool.processes, "executor should be tracked while running"
        executor = pool.processes[0]
        await executor._task  # type: ignore[attr-defined]

    asyncio.run(_scenario())

    event_names = [name for name, _ in events]
    assert event_names[:4] == [
        "process_created",
        "process_started",
        "process_ready",
        "process_job_launched",
    ]
    assert event_names[-1] == "process_closed"
    assert seen_ctxs == ["ctx-job-1"]
    # After completion, executor is removed from processes.
    assert pool.processes == []


def test_coroutine_pool_launch_job_supports_concurrent_executors() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def _entry(_ctx: Any) -> None:
        started.set()
        await release.wait()

    pool = _build_started_pool(entrypoint=_entry)
    pool._build_job_context = lambda info: f"ctx-{info.job.id}"  # type: ignore[assignment, return-value]

    async def _scenario() -> int:
        await pool.launch_job(_stub_running_job_info("a"))
        await pool.launch_job(_stub_running_job_info("b"))
        await pool.launch_job(_stub_running_job_info("c"))
        active_count = len(pool.processes)
        # Let all entrypoints exit so we drain cleanly.
        release.set()
        await asyncio.gather(
            *(ex._task for ex in pool.processes if ex._task is not None)  # type: ignore[attr-defined]
        )
        return active_count

    active_count = asyncio.run(_scenario())

    assert active_count == 3
    assert pool.processes == []


def test_coroutine_pool_get_by_job_id_finds_running_executor() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def _entry(_ctx: Any) -> None:
        started.set()
        await release.wait()

    pool = _build_started_pool(entrypoint=_entry)
    pool._build_job_context = lambda info: f"ctx-{info.job.id}"  # type: ignore[assignment, return-value]

    async def _scenario() -> Any:
        info = _stub_running_job_info("job-x")
        await pool.launch_job(info)
        # Yield once so the entrypoint task is scheduled.
        await asyncio.sleep(0)
        found = pool.get_by_job_id("job-x")
        release.set()
        for ex in pool.processes:
            if ex._task is not None:  # type: ignore[attr-defined]
                await ex._task  # type: ignore[attr-defined]
        return found

    found = asyncio.run(_scenario())

    assert found is not None
    assert found.running_job is not None
    assert found.running_job.job.id == "job-x"


def test_coroutine_pool_default_max_concurrent_sessions_is_50() -> None:
    pool = _build_pool()
    assert pool.max_concurrent_sessions == 50


def test_coroutine_pool_max_concurrent_sessions_constructor_override() -> None:
    pool = CoroutinePool(
        initialize_process_fnc=lambda _proc: None,
        job_entrypoint_fnc=_build_pool().__class__.__init__.__defaults__  # noqa: E501 — placeholder, overwritten
        and (lambda _ctx: None),  # type: ignore[assignment]
        session_end_fnc=None,
        num_idle_processes=0,
        initialize_timeout=5.0,
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
    assert pool.max_concurrent_sessions == 10


def test_coroutine_pool_max_concurrent_sessions_rejects_invalid() -> None:
    base_kwargs: dict[str, Any] = {
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
    with pytest.raises(TypeError, match="must be an int"):
        CoroutinePool(**base_kwargs, max_concurrent_sessions=10.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="must be an int"):
        CoroutinePool(**base_kwargs, max_concurrent_sessions=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be >= 1"):
        CoroutinePool(**base_kwargs, max_concurrent_sessions=0)


def test_coroutine_pool_current_load_is_zero_for_empty_pool() -> None:
    pool = _build_pool()
    assert pool.current_load() == 0.0


def test_coroutine_pool_current_load_reflects_active_executor_count() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def _entry(_ctx: Any) -> None:
        started.set()
        await release.wait()

    pool = _build_started_pool(entrypoint=_entry)
    pool._build_job_context = lambda info: f"ctx-{info.job.id}"  # type: ignore[assignment, return-value]

    async def _scenario() -> tuple[float, float, float]:
        load_idle = pool.current_load()
        await pool.launch_job(_stub_running_job_info("a"))
        await pool.launch_job(_stub_running_job_info("b"))
        load_two = pool.current_load()
        release.set()
        await asyncio.gather(
            *(ex._task for ex in pool.processes if ex._task is not None)  # type: ignore[attr-defined]
        )
        load_drained = pool.current_load()
        return load_idle, load_two, load_drained

    load_idle, load_two, load_drained = asyncio.run(_scenario())

    assert load_idle == 0.0
    # Default max_concurrent_sessions is 50; 2 active = 0.04
    assert load_two == pytest.approx(2 / 50)
    assert load_drained == 0.0


def test_coroutine_pool_current_load_reaches_one_at_capacity() -> None:
    pool = _build_pool()
    pool._max_concurrent_sessions = 4
    pool._executors.extend([object(), object(), object(), object()])  # type: ignore[list-item]

    assert pool.current_load() == 1.0


def test_coroutine_pool_emits_process_closed_on_executor_failure() -> None:
    async def _entry(_ctx: Any) -> None:
        raise RuntimeError("boom")

    pool = _build_started_pool(entrypoint=_entry)
    pool._build_job_context = lambda info: f"ctx-{info.job.id}"  # type: ignore[assignment, return-value]

    closed: list[Any] = []
    pool.on("process_closed", lambda proc: closed.append(proc))

    async def _scenario() -> None:
        await pool.launch_job(_stub_running_job_info())
        for ex in list(pool.processes):
            if ex._task is not None:  # type: ignore[attr-defined]
                await ex._task  # type: ignore[attr-defined]

    asyncio.run(_scenario())

    assert len(closed) == 1
    assert pool.processes == []


def test_coroutine_pool_emits_event_emitter_protocol() -> None:
    """CoroutinePool must subclass utils.EventEmitter so AgentServer can subscribe."""
    pool = _build_pool()
    received: list[Any] = []
    pool.on("process_created", lambda proc: received.append(proc))
    pool.emit("process_created", "sentinel")
    assert received == ["sentinel"]
