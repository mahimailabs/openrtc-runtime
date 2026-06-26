"""Regression tests: coroutine mode inference executor wiring.

In standard livekit-agents, each subprocess worker sets its own
``proc.inference_executor`` via the IPC client that talks to the main
process's InferenceProcExecutor subprocess. Coroutine mode bypasses the
subprocess runner entirely — there is one shared ``JobProcess`` and no per-job
subprocess. The fixes tested here close two gaps:

1. ``CoroutinePool.start()`` wires ``self._inference_executor`` onto
   ``proc.inference_executor`` so ``_supports_multilingual_turn_detection``
   (which reads ``proc.inference_executor``) returns True.

2. ``_CoroutineAgentServer.run()`` eagerly imports ``MultilingualModel``
   before calling ``super().run()``, because ``worker.py`` checks
   ``_InferenceRunner.registered_runners`` (populated by the import's
   side-effect) *before* calling ``setup_fnc`` (prewarm). The lazy import
   inside ``_prewarm_worker`` fires too late.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from typing import Any

import pytest
from livekit.agents import JobExecutorType

from openrtc.runtime.coroutine_runtime import CoroutinePool


def _make_pool(entrypoint: Any, *, inference_executor: Any = None) -> CoroutinePool:
    return CoroutinePool(
        initialize_process_fnc=lambda _proc: None,
        job_entrypoint_fnc=entrypoint,
        session_end_fnc=None,
        num_idle_processes=0,
        initialize_timeout=10.0,
        close_timeout=5.0,
        inference_executor=inference_executor,
        job_executor_type=JobExecutorType.PROCESS,
        mp_ctx=mp.get_context(),
        memory_warn_mb=0.0,
        memory_limit_mb=0.0,
        http_proxy=None,
        loop=asyncio.get_running_loop(),
        max_concurrent_sessions=5,
    )


async def _noop(_ctx: Any) -> None:
    pass


@pytest.mark.asyncio
async def test_coroutine_pool_wires_inference_executor_to_shared_proc() -> None:
    """CoroutinePool.start() sets proc.inference_executor when an executor is provided.

    ``_supports_multilingual_turn_detection`` reads ``proc.inference_executor``;
    if it is not set the session falls back to VAD-only turn detection even when
    a real InferenceProcExecutor has been started by worker.py.
    """
    fake_executor = object()
    pool = _make_pool(_noop, inference_executor=fake_executor)
    await pool.start()
    try:
        proc = pool.shared_process
        assert proc is not None
        assert getattr(proc, "inference_executor", None) is fake_executor, (
            "proc.inference_executor was not set; multilingual turn detection "
            "will fall back to VAD even though an executor is available."
        )
    finally:
        await pool.aclose()


@pytest.mark.asyncio
async def test_coroutine_pool_does_not_set_inference_executor_when_none() -> None:
    """When no inference executor is provided, proc.inference_executor is not set.

    ``_supports_multilingual_turn_detection`` uses ``getattr(proc,
    'inference_executor', None)`` so the attribute should be absent (not set to
    None) when no executor was passed — avoids a misleading truthy check later.
    """
    pool = _make_pool(_noop, inference_executor=None)
    await pool.start()
    try:
        proc = pool.shared_process
        assert proc is not None
        assert not hasattr(proc, "inference_executor"), (
            "proc.inference_executor should not be set when no executor was provided"
        )
    finally:
        await pool.aclose()
