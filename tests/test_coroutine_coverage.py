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
