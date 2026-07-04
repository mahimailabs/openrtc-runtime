"""Worker-level RSS watermark for coroutine mode (MAH-161).

``memory_warn_mb`` / ``memory_limit_mb`` used to be stored and never read: a
user who set a cap got a silent no-op. Coroutine mode runs every session in one
process, so per-session caps are impossible; these tests pin the worker-level
enforcement instead: warn once when RSS crosses ``memory_warn_mb``, and trip the
supervisor (restart the worker) when it crosses ``memory_limit_mb``. A band set
to ``0`` is disabled.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from typing import Any

import pytest
from livekit.agents import JobExecutorType

import openrtc.runtime.coroutine_runtime as coroutine_runtime
from openrtc.runtime.coroutine_runtime import CoroutinePool, _memory_watermark_action


async def _noop(_ctx: Any) -> None:
    pass


def _make_pool(
    *,
    memory_warn_mb: float = 0.0,
    memory_limit_mb: float = 0.0,
    on_memory_limit_exceeded: Any = None,
    memory_check_interval: float = 0.01,
) -> CoroutinePool:
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
        memory_warn_mb=memory_warn_mb,
        memory_limit_mb=memory_limit_mb,
        http_proxy=None,
        loop=asyncio.get_running_loop(),
        max_concurrent_sessions=5,
        on_memory_limit_exceeded=on_memory_limit_exceeded,
        memory_check_interval=memory_check_interval,
    )


# --- pure classification ----------------------------------------------------


def test_watermark_action_ok_below_all_bands() -> None:
    assert _memory_watermark_action(300.0, warn_mb=1000.0, limit_mb=2000.0) == "ok"


def test_watermark_action_warn_between_bands() -> None:
    assert _memory_watermark_action(1500.0, warn_mb=1000.0, limit_mb=2000.0) == "warn"


def test_watermark_action_limit_takes_precedence() -> None:
    assert _memory_watermark_action(2500.0, warn_mb=1000.0, limit_mb=2000.0) == "limit"


def test_watermark_action_zero_band_is_disabled() -> None:
    # limit disabled (0): a huge reading is only a warn.
    assert _memory_watermark_action(9999.0, warn_mb=1000.0, limit_mb=0.0) == "warn"
    # both disabled: always ok.
    assert _memory_watermark_action(9999.0, warn_mb=0.0, limit_mb=0.0) == "ok"


# --- single-sample behavior -------------------------------------------------


def _patch_rss(monkeypatch: pytest.MonkeyPatch, mb: float | None) -> None:
    monkeypatch.setattr(
        coroutine_runtime,
        "process_resident_set_bytes",
        lambda: None if mb is None else int(mb * coroutine_runtime._BYTES_PER_MB),
    )


@pytest.mark.asyncio
async def test_check_once_fires_callback_on_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[float] = []
    pool = _make_pool(
        memory_warn_mb=1000.0,
        memory_limit_mb=2000.0,
        on_memory_limit_exceeded=seen.append,
    )
    _patch_rss(monkeypatch, 2500.0)

    assert pool._check_memory_once() is True
    assert len(seen) == 1
    assert seen[0] == pytest.approx(2500.0)


@pytest.mark.asyncio
async def test_check_once_warns_once_until_recovered(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    pool = _make_pool(memory_warn_mb=1000.0, memory_limit_mb=0.0)

    _patch_rss(monkeypatch, 1500.0)
    with caplog.at_level("WARNING", logger="openrtc"):
        assert pool._check_memory_once() is False
        assert pool._check_memory_once() is False  # still high: no second warning
    assert sum("crossed memory_warn_mb" in r.message for r in caplog.records) == 1

    # Drops back below warn, then crosses again -> a fresh warning.
    _patch_rss(monkeypatch, 500.0)
    assert pool._check_memory_once() is False
    _patch_rss(monkeypatch, 1500.0)
    with caplog.at_level("WARNING", logger="openrtc"):
        assert pool._check_memory_once() is False
    assert sum("crossed memory_warn_mb" in r.message for r in caplog.records) == 2


@pytest.mark.asyncio
async def test_check_once_noop_when_rss_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[float] = []
    pool = _make_pool(memory_limit_mb=1.0, on_memory_limit_exceeded=seen.append)
    _patch_rss(monkeypatch, None)

    assert pool._check_memory_once() is False
    assert seen == []


# --- lifecycle --------------------------------------------------------------


@pytest.mark.asyncio
async def test_monitor_not_started_when_bands_disabled() -> None:
    pool = _make_pool(memory_warn_mb=0.0, memory_limit_mb=0.0)
    await pool.start()
    try:
        assert pool._memory_monitor_task is None
    finally:
        await pool.aclose()


@pytest.mark.asyncio
async def test_monitor_started_when_warn_armed_and_cancelled_on_close() -> None:
    pool = _make_pool(memory_warn_mb=1000.0, memory_limit_mb=0.0)
    await pool.start()
    task = pool._memory_monitor_task
    assert task is not None
    assert not task.done()

    await pool.aclose()
    assert pool._memory_monitor_task is None
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_monitor_loop_fires_limit_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[float] = []
    pool = _make_pool(
        memory_limit_mb=1.0,
        on_memory_limit_exceeded=seen.append,
        memory_check_interval=0.01,
    )
    _patch_rss(monkeypatch, 5000.0)
    await pool.start()
    try:
        for _ in range(200):
            if seen:
                break
            await asyncio.sleep(0.01)
        assert seen, "limit callback did not fire within the poll window"
    finally:
        await pool.aclose()
