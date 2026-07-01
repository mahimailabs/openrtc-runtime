"""MAH-84: render and log reload events."""

from __future__ import annotations

import logging

from openrtc.reload.base_reload import ReloadEvent
from openrtc.reload.reporter import format_reload_line, log_reload_event


def _event(
    status: str = "swapped",
    *,
    swapped: int = 3,
    ms: float = 23.4,
    error: str | None = None,
) -> ReloadEvent:
    return ReloadEvent(
        agent_name="foo",
        status=status,  # type: ignore[arg-type]
        sessions_swapped=swapped,
        duration_ms=ms,
        source_path="/agents/foo.py",
        error=error,
    )


def test_format_swapped_line() -> None:
    line = format_reload_line(_event())
    assert "foo.py" in line
    assert "swapped 3 sessions" in line
    assert "23ms" in line


def test_format_failed_line_includes_error() -> None:
    line = format_reload_line(_event("failed", swapped=0, error="foo.py:2: bad token"))
    assert "foo.py" in line
    assert "failed" in line
    assert "foo.py:2: bad token" in line


def test_log_swapped_at_info(caplog) -> None:  # type: ignore[no-untyped-def]
    with caplog.at_level(logging.INFO, logger="openrtc"):
        log_reload_event(_event())
    levels = [r.levelno for r in caplog.records]
    assert logging.INFO in levels
    assert logging.ERROR not in levels


def test_log_failed_at_error(caplog) -> None:  # type: ignore[no-untyped-def]
    with caplog.at_level(logging.INFO, logger="openrtc"):
        log_reload_event(_event("failed", swapped=0, error="boom"))
    assert logging.ERROR in [r.levelno for r in caplog.records]
