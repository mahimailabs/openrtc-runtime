"""livekit-agents version compatibility for coroutine mode."""

from __future__ import annotations

import asyncio
import multiprocessing
from typing import Any

from livekit.agents import JobContext, JobExecutorType

from openrtc.runtime.coroutine_runtime import CoroutineJobExecutor, CoroutinePool


def _proc_pool_base_kwargs(loop: asyncio.AbstractEventLoop) -> dict[str, Any]:
    """The required ProcPool-surface kwargs, with harmless dummy values."""

    async def _noop(_ctx: JobContext) -> None:
        return None

    return {
        "initialize_process_fnc": lambda _proc: None,
        "job_entrypoint_fnc": _noop,
        "session_end_fnc": _noop,
        "num_idle_processes": 0,
        "initialize_timeout": 10.0,
        "close_timeout": 10.0,
        "inference_executor": None,
        "job_executor_type": next(iter(JobExecutorType)),
        "mp_ctx": multiprocessing.get_context("spawn"),
        "memory_warn_mb": 0.0,
        "memory_limit_mb": 0.0,
        "http_proxy": None,
        "loop": loop,
    }


def test_pool_accepts_new_and_future_kwargs() -> None:
    loop = asyncio.new_event_loop()

    async def _sim_end(_ctx: JobContext) -> None:
        return None

    try:
        pool = CoroutinePool(
            **_proc_pool_base_kwargs(loop),
            session_end_timeout=5.0,
            simulation_end_fnc=_sim_end,
            a_future_proc_pool_kwarg="absorbed",
        )
        assert pool._session_end_timeout == 5.0
        assert pool._simulation_end_fnc is _sim_end
    finally:
        loop.close()


def test_executor_bounds_session_end_fnc_by_session_end_timeout() -> None:
    timed_out = asyncio.Event()

    async def _entrypoint(_ctx: JobContext) -> None:
        return None

    async def _slow_session_end(_ctx: JobContext) -> None:
        try:
            await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            timed_out.set()
            raise

    class _Ctx:
        is_fake_job = staticmethod(lambda: True)

    async def _run() -> None:
        ex = CoroutineJobExecutor(
            entrypoint_fnc=_entrypoint,
            session_end_fnc=_slow_session_end,
            context_factory=lambda _info: _Ctx(),  # type: ignore[arg-type,return-value]
            session_end_timeout=0.05,
        )
        await ex._run_entrypoint(_Ctx())  # type: ignore[arg-type]

    asyncio.run(asyncio.wait_for(_run(), timeout=5.0))
    assert timed_out.is_set()


def test_every_proc_pool_kwarg_is_explicitly_handled() -> None:
    """Hard gate: every ProcPool ctor kwarg must be an explicit CoroutinePool param.

    A new upstream kwarg is absorbed by **_extra (no crash), but trips this test so a
    maintainer reviews whether it needs honoring, like session_end_timeout did.
    """
    import inspect

    from livekit.agents.ipc.proc_pool import ProcPool

    proc = {
        n
        for n, p in inspect.signature(ProcPool.__init__).parameters.items()
        if n != "self" and p.kind is not inspect.Parameter.VAR_KEYWORD
    }
    explicit = {
        n
        for n, p in inspect.signature(CoroutinePool.__init__).parameters.items()
        if n != "self" and p.kind is not inspect.Parameter.VAR_KEYWORD
    }
    unhandled = proc - explicit
    assert not unhandled, (
        f"ProcPool grew kwargs not explicitly handled by CoroutinePool: {sorted(unhandled)}. "
        "They are absorbed by **_extra so nothing crashes; review whether any needs honoring "
        "and add it to CoroutinePool.__init__."
    )


def test_coroutine_pool_init_accepts_var_keyword() -> None:
    import inspect

    kinds = [
        p.kind for p in inspect.signature(CoroutinePool.__init__).parameters.values()
    ]
    assert inspect.Parameter.VAR_KEYWORD in kinds
