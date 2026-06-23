"""Regression tests: coroutine mode HTTP session lifecycle.

The HTTP session must be a worker-lifetime resource, not per-job. Plugin
instances (STT, TTS) are shared across all coroutine jobs in one worker. They
cache the aiohttp ClientSession on first use (``self._session =
http_context.http_session()``). Closing the session at per-job teardown
invalidates that cache — every subsequent job hits ``Session is closed`` on
ws_connect. The fix: open once in ``CoroutinePool.start()``, close once in
``CoroutinePool.aclose()``.
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
async def test_coroutine_http_session_stays_open_after_job_closes_at_pool_aclose() -> (
    None
):
    """The http session outlives individual jobs and closes only when the pool closes.

    Plugin instances cache ``http_session()`` on first use. If openrtc closed
    the session at job teardown, every subsequent job would find the cached
    session closed. This asserts the session is open after a job finishes and
    closed only after ``pool.aclose()``.
    """
    captured: dict[str, Any] = {}

    async def _entrypoint(_ctx: Any) -> None:
        captured["session"] = http_context.http_session()

    pool = _make_pool(_entrypoint)
    await pool.start()
    try:
        await pool.launch_job(_stub_running_job_info("job-lifetime-1"))
        for ex in list(pool.processes):
            task = getattr(ex, "_task", None)
            if task is not None:
                await task

        session = captured.get("session")
        assert session is not None, (
            "http_session() was not captured inside the entrypoint"
        )
        assert not session.closed, (
            "http session was closed after one job finished; "
            "this breaks any shared plugin (STT/TTS) that cached it on first use."
        )
    finally:
        await pool.aclose()

    assert session is not None
    assert session.closed, "http session was not closed after pool.aclose()"


@pytest.mark.asyncio
async def test_coroutine_shared_plugin_reuses_session_across_jobs() -> None:
    """Shared plugin instances reuse the same open session across sequential jobs.

    This is the direct regression test for the bug: Deepgram STT / Cartesia TTS
    instances are shared across all coroutine jobs. They cache the aiohttp
    ClientSession on first use. Job 1 populates the cache; job 2 must find the
    same session still open. Closing the session per-job (the previous behavior)
    broke this: job 2 would hit 'Session is closed' on ws_connect and die.
    """

    class _SharedPlugin:
        """Simulates a livekit STT/TTS plugin that caches http_session() once."""

        def __init__(self) -> None:
            self._session: Any = None

        def use(self) -> None:
            if self._session is None:
                self._session = http_context.http_session()
            if self._session.closed:
                raise RuntimeError("Session is closed")

    plugin = _SharedPlugin()
    errors: list[str] = []

    async def _entrypoint(_ctx: Any) -> None:
        try:
            plugin.use()
        except RuntimeError as exc:
            errors.append(str(exc))

    pool = _make_pool(_entrypoint)
    await pool.start()
    try:
        for job_id in ("job-shared-1", "job-shared-2"):
            await pool.launch_job(_stub_running_job_info(job_id))
            for ex in list(pool.processes):
                task = getattr(ex, "_task", None)
                if task is not None:
                    await task
    finally:
        await pool.aclose()

    assert errors == [], (
        "Shared plugin found a closed session on job reuse — "
        "the per-job http teardown is still active: " + str(errors)
    )
    assert plugin._session is not None
    assert plugin._session.closed, (
        "Expected the worker-lifetime http session to be closed after pool.aclose()"
    )
