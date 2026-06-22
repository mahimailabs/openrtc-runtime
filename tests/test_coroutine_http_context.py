"""Regression test: coroutine mode must open the LiveKit http session context.

RED today (http-context bug): ``CoroutineJobExecutor`` runs the entrypoint
without ever calling ``http_context._new_session_ctx()``, so any plugin that
lazily calls ``livekit.agents.utils.http_context.http_session()`` (Cartesia
TTS, the server API, etc.) raises ``RuntimeError: Attempted to use an http
session outside of a job context``. Upstream binds the http session factory
only in the process/thread runner (``ipc/job_proc_lazy_main.py``), which
coroutine mode bypasses entirely.

These drive one coroutine-pool session and assert (1) ``http_session()``
resolves inside the entrypoint, and (2) that session is closed on teardown.
Both fail on today's code and pass once the executor opens and closes the
http context around the entrypoint.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import JobExecutorType
from livekit.agents.utils import http_context

from openrtc.runtime.coroutine_runtime import CoroutinePool


def _stub_running_job_info(job_id: str) -> Any:
    """Minimal RunningJobInfo stand-in (only ``job.id`` + ``fake_job`` are read)."""
    return SimpleNamespace(
        job=SimpleNamespace(id=job_id),
        fake_job=True,
        worker_id="http-ctx-test",
    )


def _make_pool(entrypoint: Any) -> CoroutinePool:
    """Build a coroutine pool whose jobs run ``entrypoint`` against a stub context.

    The stub context carries ``proc.http_proxy`` because livekit's
    ``_new_session`` factory reads ``get_job_context().proc.http_proxy`` the
    first time ``http_session()`` creates a session.
    """
    pool = CoroutinePool(
        initialize_process_fnc=lambda _proc: None,
        job_entrypoint_fnc=entrypoint,
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

    def _build_ctx(info: Any) -> Any:
        return SimpleNamespace(
            job=info.job,
            room=SimpleNamespace(name=f"room-{info.job.id}"),
            proc=SimpleNamespace(http_proxy=None),
        )

    pool._build_job_context = _build_ctx  # type: ignore[assignment]
    return pool


async def _drive_one(pool: CoroutinePool, job_id: str) -> None:
    """Start the pool, run one job to completion, then close the pool."""
    await pool.start()
    try:
        await pool.launch_job(_stub_running_job_info(job_id))
        for executor in list(pool.processes):
            task = getattr(executor, "_task", None)
            if task is not None:
                await task
    finally:
        await pool.aclose()


@pytest.mark.asyncio
async def test_coroutine_entrypoint_can_use_http_session() -> None:
    """A coroutine-mode entrypoint can call http_session() without raising."""
    captured: dict[str, Any] = {}

    async def _entrypoint(_ctx: Any) -> None:
        try:
            session = http_context.http_session()
            captured["ok"] = session is not None
        except RuntimeError as exc:  # today: "outside of a job context"
            captured["error"] = str(exc)

    await _drive_one(_make_pool(_entrypoint), "job-http-0")

    assert "error" not in captured, (
        "http_session() raised inside the coroutine entrypoint: "
        f"{captured.get('error')!r}. The executor never opened the http context."
    )
    assert captured.get("ok") is True, captured


@pytest.mark.asyncio
async def test_coroutine_closes_http_session_on_teardown() -> None:
    """The per-job http session is closed when the job finishes."""
    captured: dict[str, Any] = {}

    async def _entrypoint(_ctx: Any) -> None:
        captured["session"] = http_context.http_session()

    await _drive_one(_make_pool(_entrypoint), "job-http-1")

    session = captured.get("session")
    assert session is not None, captured
    assert session.closed is True, (
        "http session was not closed on teardown; "
        "_close_http_ctx() did not run in the finally."
    )
