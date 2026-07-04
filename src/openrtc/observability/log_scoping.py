"""Per-session log scoping (MAH-91): tag and structure the shared worker's logs.

``SessionIdFilter`` stamps every log record with the current ``session_id`` (from
:mod:`openrtc.observability.session_context`), so logs from many interleaved
sessions in one worker are attributable. ``JsonLogFormatter`` renders records as
one JSON object per line for ``jq`` / a log shipper / the ``openrtc logs`` filter.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openrtc.observability.session_context import current_session_id

__all__ = ["JsonLogFormatter", "SessionIdFilter"]


class SessionIdFilter(logging.Filter):
    """Attach ``session_id`` (or ``None``) from the current context to each record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.session_id = current_session_id()
        return True


class JsonLogFormatter(logging.Formatter):
    """Render a record as one JSON line: timestamp, level, session_id, message."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "session_id": getattr(record, "session_id", None),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)
