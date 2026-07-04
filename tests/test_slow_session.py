"""Slow-session detector: attribute event-loop blocks to a session (MAH-90)."""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

from openrtc.observability.slow_session import LoopBlockEvent, SlowSessionDetector


def _detector(**kwargs: object) -> SlowSessionDetector:
    kwargs.setdefault("blocked_session_provider", lambda: "culprit")
    kwargs.setdefault("threshold_ms", 20.0)
    return SlowSessionDetector(**kwargs)  # type: ignore[arg-type]


def test_lag_below_threshold_is_ignored() -> None:
    events: list[LoopBlockEvent] = []
    detector = _detector(on_block=events.append)
    assert detector.evaluate_lag(5.0) is None
    assert events == []


def test_lag_over_threshold_reports_and_attributes() -> None:
    events: list[LoopBlockEvent] = []
    detector = _detector(on_block=events.append)
    event = detector.evaluate_lag(87.0)
    assert event is not None
    assert event.session_id == "culprit"
    assert event.blocked_ms == 87.0
    assert events == [event]


def test_block_logs_session_and_duration(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="openrtc"):
        _detector().evaluate_lag(87.4)
    assert (
        "[slow-session] session_id=culprit blocked event loop for 87ms" in caplog.text
    )


def test_no_running_session_reports_none() -> None:
    detector = _detector(blocked_session_provider=lambda: None)
    event = detector.evaluate_lag(60.0)
    assert event is not None
    assert event.session_id is None


def test_default_sample_interval_is_half_threshold() -> None:
    assert SlowSessionDetector(
        blocked_session_provider=lambda: None, threshold_ms=50.0
    )._sample_interval == pytest.approx(0.025)


@pytest.mark.asyncio
async def test_run_detects_synthetic_block() -> None:
    # Acceptance: a synthetic blocking call is detected and attributed to the
    # session that was running.
    events: list[LoopBlockEvent] = []
    detector = _detector(
        blocked_session_provider=lambda: "blocker",
        threshold_ms=20.0,
        on_block=events.append,
        sample_interval_ms=5.0,
    )
    stop = asyncio.Event()
    task = asyncio.create_task(detector.run(stop))
    await asyncio.sleep(0.02)  # let the watcher start sampling
    time.sleep(0.1)  # synchronous 100 ms block of the event loop
    await asyncio.sleep(0.05)  # let the watcher observe the lag
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert any(e.session_id == "blocker" and e.blocked_ms >= 20 for e in events), events
