"""Backpressure tests for the coroutine path.

Covers design §8 acceptance criterion 6: with
``max_concurrent_sessions=10``, the 11th job is not accepted by LiveKit
dispatch because ``load >= 1.0`` is reported. Backpressure in v0.1 is
**load-driven**, not hard-rejected at the pool: the dispatcher reads
``load_fnc`` (which our ``_CoroutineAgentServer`` wires to
``CoroutinePool.current_load``), sees ``>= 1.0``, and routes the next
job elsewhere. If the dispatcher races and sends one anyway the pool
still accepts it (and reports ``> 1.0``); the design (§5.4 / §6.3)
documents this as cooperative.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import time
from types import SimpleNamespace
from typing import Any

from livekit.agents import JobExecutorType

from openrtc.runtime.coroutine_runtime import CoroutinePool


def _stub_running_job_info(job_id: str) -> Any:
    return SimpleNamespace(
        job=SimpleNamespace(id=job_id),
        fake_job=True,
        worker_id="backpressure-test",
    )


def _build_pool(
    *,
    max_concurrent_sessions: int,
    entrypoint: Any,
    track_loop_lag: bool = False,
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
        max_concurrent_sessions=max_concurrent_sessions,
    )
    pool._build_job_context = lambda info: SimpleNamespace(  # type: ignore[assignment]
        proc=pool.shared_process,
        job=info.job,
        room=SimpleNamespace(name=f"room-{info.job.id}"),
        session_id=info.job.id,
    )
    if not track_loop_lag:
        # Session-pressure tests assert exact loads; keep scheduler jitter out.
        pool.record_loop_lag = lambda _lag_ms: None  # type: ignore[method-assign]
    return pool


def test_current_load_reaches_one_at_capacity_with_real_executors() -> None:
    """§8.6 happy path: 10 in-flight sessions out of 10 -> load == 1.0."""

    started = 0
    release = asyncio.Event()

    async def _entrypoint(_ctx: Any) -> None:
        nonlocal started
        started += 1
        await release.wait()

    pool = _build_pool(max_concurrent_sessions=10, entrypoint=_entrypoint)

    async def _scenario() -> tuple[float, float]:
        await pool.start()
        for i in range(10):
            await pool.launch_job(_stub_running_job_info(f"j-{i}"))
        # Let the entrypoints reach the await point.
        while started < 10:
            await asyncio.sleep(0.005)

        load_at_capacity = pool.current_load()

        release.set()
        # Drain.
        for ex in list(pool.processes):
            task = getattr(ex, "_task", None)
            if task is not None:
                await task
        # Yield once so done callbacks fire.
        while pool.processes:
            await asyncio.sleep(0.005)
        load_after_drain = pool.current_load()

        await pool.aclose()
        return load_at_capacity, load_after_drain

    load_at_capacity, load_after_drain = asyncio.run(_scenario())

    assert load_at_capacity == 1.0
    assert load_after_drain == 0.0


def test_current_load_reports_over_one_when_dispatcher_overshoots() -> None:
    """The pool tolerates an 11th job arriving before dispatch sees the new load.

    Design §5.4 says backpressure is cooperative — the dispatcher reads
    load_fnc and decides to route elsewhere. If a race lets one through
    we still accept it (better that than dropping a real call) and the
    next load read tells the dispatcher to back off harder.
    """

    started = 0
    release = asyncio.Event()

    async def _entrypoint(_ctx: Any) -> None:
        nonlocal started
        started += 1
        await release.wait()

    pool = _build_pool(max_concurrent_sessions=10, entrypoint=_entrypoint)

    async def _scenario() -> float:
        await pool.start()
        for i in range(11):  # one over capacity
            await pool.launch_job(_stub_running_job_info(f"j-{i}"))
        while started < 11:
            await asyncio.sleep(0.005)

        load_over_capacity = pool.current_load()

        release.set()
        for ex in list(pool.processes):
            task = getattr(ex, "_task", None)
            if task is not None:
                await task
        while pool.processes:
            await asyncio.sleep(0.005)
        await pool.aclose()
        return load_over_capacity

    load_over_capacity = asyncio.run(_scenario())

    assert load_over_capacity == 11 / 10  # 1.1


def test_current_load_climbs_smoothly_below_capacity() -> None:
    """Sanity: the ratio is exactly len(active) / max_concurrent_sessions."""

    started = 0
    release = asyncio.Event()

    async def _entrypoint(_ctx: Any) -> None:
        nonlocal started
        started += 1
        await release.wait()

    pool = _build_pool(max_concurrent_sessions=10, entrypoint=_entrypoint)

    async def _scenario() -> list[float]:
        await pool.start()
        loads: list[float] = []
        for i in range(10):
            await pool.launch_job(_stub_running_job_info(f"j-{i}"))
            # Wait until the entrypoint has actually reached its await point.
            while started < i + 1:
                await asyncio.sleep(0.005)
            loads.append(pool.current_load())

        release.set()
        for ex in list(pool.processes):
            task = getattr(ex, "_task", None)
            if task is not None:
                await task
        while pool.processes:
            await asyncio.sleep(0.005)
        await pool.aclose()
        return loads

    loads = asyncio.run(_scenario())

    assert loads == [
        0.1,
        0.2,
        0.3,
        0.4,
        0.5,
        0.6,
        0.7,
        0.8,
        0.9,
        1.0,
    ]


def test_load_fnc_closure_pattern_reports_pool_load() -> None:
    """The closure `_CoroutineAgentServer.run()` registers reflects pool.current_load.

    This re-exercises the closure pattern (already covered by
    tests/test_coroutine_server.py at the unit level) end-to-end against
    a real pool with active executors.
    """

    started = 0
    release = asyncio.Event()

    async def _entrypoint(_ctx: Any) -> None:
        nonlocal started
        started += 1
        await release.wait()

    pool = _build_pool(max_concurrent_sessions=10, entrypoint=_entrypoint)
    captured: dict[str, CoroutinePool | None] = {"pool": None}

    def _load_fnc() -> float:
        p = captured["pool"]
        if p is None:
            return 0.0
        return p.current_load()

    async def _scenario() -> tuple[float, float, float]:
        await pool.start()
        captured["pool"] = pool

        load_idle = _load_fnc()

        for i in range(7):
            await pool.launch_job(_stub_running_job_info(f"j-{i}"))
        while started < 7:
            await asyncio.sleep(0.005)
        load_partial = _load_fnc()

        for i in range(7, 10):
            await pool.launch_job(_stub_running_job_info(f"j-{i}"))
        while started < 10:
            await asyncio.sleep(0.005)
        load_full = _load_fnc()

        release.set()
        for ex in list(pool.processes):
            task = getattr(ex, "_task", None)
            if task is not None:
                await task
        while pool.processes:
            await asyncio.sleep(0.005)
        await pool.aclose()
        return load_idle, load_partial, load_full

    load_idle, load_partial, load_full = asyncio.run(_scenario())

    assert load_idle == 0.0
    assert load_partial == 0.7
    assert load_full == 1.0


def test_loop_lag_raises_load_above_session_pressure() -> None:
    """A saturated loop reports load even with few sessions, capped at 1.0."""

    async def _noop(_ctx: Any) -> None:
        return None

    pool = _build_pool(
        max_concurrent_sessions=10, entrypoint=_noop, track_loop_lag=True
    )
    assert pool.current_load() == 0.0

    pool.record_loop_lag(250.0)  # one sample; EWMA 0.2 -> 50 ms -> load 0.5
    assert pool.loop_lag_ms == 50.0
    assert pool.current_load() == 0.5

    for _ in range(50):
        pool.record_loop_lag(1000.0)
    assert pool.current_load() == 1.0


def test_lag_monitor_detects_a_blocked_loop_and_stops_on_close() -> None:
    """The real sampler sees a synchronous block and is cancelled by aclose()."""

    async def _noop(_ctx: Any) -> None:
        return None

    async def _scenario() -> tuple[float, bool]:
        pool = _build_pool(
            max_concurrent_sessions=10, entrypoint=_noop, track_loop_lag=True
        )
        await pool.start()
        await asyncio.sleep(0.05)
        time.sleep(0.3)  # block the loop past the 100 ms sample interval
        await asyncio.sleep(0.15)
        lag = pool.loop_lag_ms
        await pool.aclose()
        return lag, pool._lag_monitor_task is None

    lag, stopped = asyncio.run(_scenario())

    assert lag > 20.0
    assert stopped
