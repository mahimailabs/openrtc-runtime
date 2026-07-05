"""Blue-green drain trigger + draining visibility (MAH-109)."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import Agent, JobExecutorType

from openrtc import AgentPool
from openrtc.runtime.coroutine_runtime import CoroutinePool


class _Agent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="a")


async def _noop(_ctx: Any) -> None:
    pass


def _coroutine_pool() -> CoroutinePool:
    return CoroutinePool(
        initialize_process_fnc=lambda _proc: None,
        job_entrypoint_fnc=_noop,
        session_end_fnc=None,
        num_idle_processes=0,
        initialize_timeout=10.0,
        close_timeout=5.0,
        inference_executor=None,
        job_executor_type=JobExecutorType.PROCESS,
        mp_ctx=mp.get_context(),
        memory_warn_mb=0.0,
        memory_limit_mb=0.0,
        http_proxy=None,
        loop=asyncio.get_event_loop(),
        max_concurrent_sessions=5,
    )


# --- CoroutinePool.begin_drain ----------------------------------------------


@pytest.mark.asyncio
async def test_begin_drain_flags_without_awaiting() -> None:
    pool = _coroutine_pool()
    assert pool.draining is False
    pool.begin_drain()
    assert pool.draining is True


@pytest.mark.asyncio
async def test_begin_drain_rejects_new_jobs() -> None:
    pool = _coroutine_pool()
    await pool.start()
    try:
        pool.begin_drain()
        info = SimpleNamespace(
            job=SimpleNamespace(id="j1"), fake_job=True, worker_id="w"
        )
        with pytest.raises(RuntimeError, match="draining"):
            await pool.launch_job(info)  # type: ignore[arg-type]
    finally:
        await pool.aclose()


@pytest.mark.asyncio
async def test_drain_still_awaits_after_begin_drain() -> None:
    # begin_drain sets the flag; a later drain() must still complete (no early exit).
    pool = _coroutine_pool()
    pool.begin_drain()
    await pool.drain()  # no in-flight -> returns cleanly
    assert pool.draining is True


# --- AgentPool.begin_drain + draining visibility ----------------------------


class _StubPool:
    def __init__(self) -> None:
        self.draining = False

    def begin_drain(self) -> None:
        self.draining = True


def test_agent_pool_not_draining_by_default() -> None:
    pool = AgentPool(agent=_Agent, enable_introspection=False)
    assert pool.draining is False
    assert pool.runtime_snapshot().draining is False


def test_agent_pool_begin_drain_delegates_and_surfaces() -> None:
    pool = AgentPool(agent=_Agent, enable_introspection=False)
    stub = _StubPool()
    pool._server._coroutine_pool = stub  # type: ignore[attr-defined]

    pool.begin_drain()

    assert stub.draining is True
    assert pool.draining is True
    snap = pool.runtime_snapshot()
    assert snap.draining is True
    assert snap.to_dict()["draining"] is True


def test_agent_pool_begin_drain_noop_without_running_pool() -> None:
    # No running coroutine pool: begin_drain is a safe no-op.
    pool = AgentPool(agent=_Agent, enable_introspection=False)
    pool._server._coroutine_pool = None  # type: ignore[attr-defined]
    pool.begin_drain()
    assert pool.draining is False
