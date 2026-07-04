"""MAH-84: render reload events for humans and route them to logs.

``format_reload_line`` produces the one-line feedback shown on the dev CLI's
stdout and in structured logs. ``log_reload_event`` is the coordinator's default
sink: successes at INFO, failures at ERROR.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openrtc.reload.base_reload import ReloadEvent

logger = logging.getLogger("openrtc")

__all__ = ["format_reload_line", "log_reload_event"]


def format_reload_line(event: ReloadEvent) -> str:
    """Render a reload event as a single ``[reload] ...`` line."""
    name = Path(event.source_path).name
    if event.status == "failed":
        return f"[reload] {name} failed: {event.error}"
    return (
        f"[reload] {name} changed -> swapped {event.sessions_swapped} "
        f"sessions in {event.duration_ms:.0f}ms"
    )


def log_reload_event(event: ReloadEvent) -> None:
    """Log a reload event: INFO for a swap, ERROR for a failure."""
    line = format_reload_line(event)
    if event.status == "failed":
        logger.error(line)
    else:
        logger.info(line)
