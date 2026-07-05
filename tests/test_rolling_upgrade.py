"""v0.6 rolling-upgrade gate: blue-green drain, old finishes, new accepts (MAH-113).

Drives the real drain machinery for two pools side by side (v1 draining, v2 taking
new calls). Zero-downtime is binary, so this pins the binary outcome: v1's in-flight
calls run to their natural end on v1 (not dropped, not migrated), v1 rejects new
calls once draining, and v2 accepts throughout.

Scope (drain-only rescope): mid-call migration is out of scope (MAH-108), so there
is nothing to migrate and no ``migration.*`` events; the traffic shift + rollback
are the deployment platform's job (a rolling update / LiveKit worker rotation). A
full 20-session real-media cluster run is deferred as heavy + redundant here: the
drain mechanics are deterministic at the pool layer, and live sessions are already
covered by the real-media integration tests. This composition runs in CI on every PR.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import JobExecutorType

from openrtc.runtime.coroutine_runtime import CoroutinePool


def _pool(entrypoint: Any) -> CoroutinePool:
    return CoroutinePool(
        initialize_process_fnc=lambda _p: None,
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
        loop=asyncio.get_event_loop(),
        max_concurrent_sessions=50,
    )


def _info(sid: str) -> Any:
    return SimpleNamespace(job=SimpleNamespace(id=sid), fake_job=True, worker_id="w")


_IN_FLIGHT = 5  # stand-in for the ticket's 20; the drain path is per-executor.


@pytest.mark.asyncio
async def test_blue_green_drain_old_finishes_new_accepts() -> None:
    started = 0
    completed = 0
    release = asyncio.Event()

    async def _v1_entrypoint(_ctx: Any) -> None:
        nonlocal started, completed
        started += 1
        await release.wait()  # a held, in-flight call
        completed += 1

    async def _v2_entrypoint(_ctx: Any) -> None:
        return None

    v1 = _pool(_v1_entrypoint)
    v2 = _pool(_v2_entrypoint)
    await v1.start()
    await v2.start()
    try:
        for i in range(_IN_FLIGHT):
            await v1.launch_job(_info(f"v1-{i}"))
        while started < _IN_FLIGHT:
            await asyncio.sleep(0.01)
        assert len(v1.processes) == _IN_FLIGHT

        # Deploy v2: begin draining v1 (blue-green switchover).
        v1.begin_drain()
        assert v1.draining is True

        # v1 rejects new calls; v2 accepts them.
        with pytest.raises(RuntimeError, match="draining"):
            await v1.launch_job(_info("v1-new"))
        await v2.launch_job(_info("v2-1"))  # accepted, no raise

        # v1's in-flight calls are untouched (not dropped, not migrated).
        assert len(v1.processes) == _IN_FLIGHT
        assert completed == 0

        # Let the in-flight calls finish; v1 drains to zero and can exit.
        release.set()
        await v1.drain()  # awaits every in-flight call to its natural end
        assert completed == _IN_FLIGHT  # zero drops
        assert not v1.processes  # v1 empty -> ready to exit cleanly
    finally:
        release.set()
        await v1.aclose()
        await v2.aclose()
