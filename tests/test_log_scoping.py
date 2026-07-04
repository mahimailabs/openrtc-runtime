"""Per-session log scoping: filter + structured JSON formatter (MAH-91).

Debugging at density means grepping 50 interleaved sessions in one worker. The
filter stamps every record with its session_id (from the contextvar); the
formatter emits one JSON object per line so the haystack is searchable.
"""

from __future__ import annotations

import json
import logging
import sys

from openrtc.observability.log_scoping import JsonLogFormatter, SessionIdFilter
from openrtc.observability.session_context import session_scope


def _record(msg: str = "hi") -> logging.LogRecord:
    return logging.LogRecord("openrtc", logging.INFO, __file__, 1, msg, None, None)


def test_filter_adds_session_id_in_scope() -> None:
    log_filter = SessionIdFilter()
    with session_scope("s1"):
        rec = _record()
        assert log_filter.filter(rec) is True
        assert rec.session_id == "s1"


def test_filter_session_id_is_none_outside_scope() -> None:
    log_filter = SessionIdFilter()
    rec = _record()
    log_filter.filter(rec)
    # None, not "" or a missing attribute.
    assert rec.session_id is None


def test_json_formatter_shape() -> None:
    fmt = JsonLogFormatter()
    rec = _record("hello")
    rec.session_id = "abc"  # type: ignore[attr-defined]
    out = json.loads(fmt.format(rec))
    assert out["level"] == "INFO"
    assert out["session_id"] == "abc"
    assert out["message"] == "hello"
    assert out["logger"] == "openrtc"
    assert "timestamp" in out


def test_json_formatter_session_id_null_when_absent() -> None:
    fmt = JsonLogFormatter()
    out = json.loads(fmt.format(_record()))
    assert out["session_id"] is None


def test_json_formatter_includes_exc_info() -> None:
    fmt = JsonLogFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        rec = logging.LogRecord(
            "openrtc", logging.ERROR, __file__, 1, "err", None, sys.exc_info()
        )
    out = json.loads(fmt.format(rec))
    assert "ValueError" in out["exc_info"]


def test_filter_and_formatter_compose() -> None:
    """Filter stamps the id; formatter renders it (the real logging path)."""
    fmt = JsonLogFormatter()
    log_filter = SessionIdFilter()
    with session_scope("compose-1"):
        rec = _record("in-session")
        log_filter.filter(rec)
        out = json.loads(fmt.format(rec))
    assert out["session_id"] == "compose-1"
