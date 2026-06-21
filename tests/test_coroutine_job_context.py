"""Regression test: coroutine mode must establish the LiveKit job context.

RED today (job-context bug): ``CoroutineJobExecutor`` runs the entrypoint
without ever calling ``_JobContextVar.set(ctx)``, so
``livekit.agents.get_job_context()`` raises ``RuntimeError`` inside any
session. Upstream sets the contextvar only in the process/thread runner
(``ipc/job_proc_lazy_main.py``), which coroutine mode bypasses entirely.

This drives one coroutine-pool session whose entrypoint calls
``get_job_context()`` and asserts it resolves to the session's own
``JobContext``. It fails on today's code and should pass once the executor
establishes (and resets) the job context around the entrypoint.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import JobExecutorType
from livekit.agents.job import get_job_context

from openrtc.runtime.coroutine_runtime import CoroutinePool


def _stub_running_job_info(job_id: str) -> Any:
    """Minimal RunningJobInfo stand-in (only ``job.id`` + ``fake_job`` are read)."""
    return SimpleNamespace(
        job=SimpleNamespace(id=job_id),
        fake_job=True,
        worker_id="ctx-test",
    )


@pytest.mark.asyncio
async def test_coroutine_entrypoint_can_resolve_job_context() -> None:
    """A coroutine-mode entrypoint can call get_job_context() and get its ctx."""
    captured: dict[str, Any] = {}

    async def _entrypoint(ctx: Any) -> None:
        try:
            captured["matches"] = get_job_context() is ctx
        except RuntimeError as exc:  # today: "no job context found ..."
            captured["error"] = str(exc)

    pool = CoroutinePool(
        initialize_process_fnc=lambda _proc: None,
        job_entrypoint_fnc=_entrypoint,
        session_end_fnc=None,
        num_idle_processes=0,
        initialize_timeout=10.0,
        close_timeout=15.0,
        inference_executor=None,
        job_executor_type=JobExecutorType.PROCESS,
        mp_ctx=mp.get_context(),
        memory_warn_mb=0.0,
        memory_limit_mb=0.0,
        http_proxy=None,
        loop=asyncio.get_running_loop(),
        max_concurrent_sessions=5,
    )

    # Hand the entrypoint a lightweight stub context instead of constructing a
    # real rtc.Room. get_job_context() resolves a process-global contextvar,
    # so object identity is all this assertion needs.
    def _build_ctx(info: Any) -> Any:
        return SimpleNamespace(
            job=info.job, room=SimpleNamespace(name=f"room-{info.job.id}")
        )

    pool._build_job_context = _build_ctx  # type: ignore[assignment]

    await pool.start()
    try:
        await pool.launch_job(_stub_running_job_info("job-0"))
        for executor in list(pool.processes):
            task = getattr(executor, "_task", None)
            if task is not None:
                await task
    finally:
        await pool.aclose()

    assert "error" not in captured, (
        "get_job_context() raised inside the coroutine entrypoint: "
        f"{captured.get('error')!r}. The executor never set _JobContextVar."
    )
    assert captured.get("matches") is True, captured
