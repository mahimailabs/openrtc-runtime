"""Slow-session detector: attribute event-loop blocks to a session (MAH-90).

When many sessions share one event loop, a single synchronous blocking call (a
sync ``requests.get()``, a heavy CPU loop) starves all the others. This watcher
schedules itself on a short interval and measures how late its wakeup actually
fires: the delay past the interval is how long the loop was blocked. On a block
over the configurable threshold it attributes the block to the session that was
running during it (from the CPU sampler's last-seen running session, which shares
the task->session foundation) and logs + reports it.

Best-effort: the offending source line is not captured (that needs stack
sampling and is deferred); the ``session_id`` + duration are, which is enough to
find the culprit.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger("openrtc")

__all__ = ["LoopBlockEvent", "SlowSessionDetector"]

_DEFAULT_THRESHOLD_MS = 50.0

BlockedSessionProvider = Callable[[], str | None]
OnBlock = Callable[["LoopBlockEvent"], None]


@dataclass(frozen=True, slots=True)
class LoopBlockEvent:
    """One detected event-loop block, attributed to the running session."""

    session_id: str | None
    blocked_ms: float


class SlowSessionDetector:
    """Watch event-loop scheduling latency; attribute blocks over threshold."""

    def __init__(
        self,
        *,
        blocked_session_provider: BlockedSessionProvider,
        threshold_ms: float = _DEFAULT_THRESHOLD_MS,
        on_block: OnBlock | None = None,
        sample_interval_ms: float | None = None,
    ) -> None:
        self._blocked_session_provider = blocked_session_provider
        self._threshold_ms = threshold_ms
        self._on_block = on_block
        interval_ms = (
            sample_interval_ms
            if sample_interval_ms is not None
            else max(1.0, threshold_ms / 2.0)
        )
        self._sample_interval = interval_ms / 1000.0

    def evaluate_lag(self, lag_ms: float) -> LoopBlockEvent | None:
        """Report a block event when ``lag_ms`` exceeds the threshold, else ``None``."""
        if lag_ms <= self._threshold_ms:
            return None
        session_id = self._blocked_session_provider()
        event = LoopBlockEvent(session_id=session_id, blocked_ms=round(lag_ms, 1))
        logger.warning(
            "[slow-session] session_id=%s blocked event loop for %.0fms",
            session_id,
            event.blocked_ms,
        )
        if self._on_block is not None:
            self._on_block(event)
        return event

    async def run(self, stop: asyncio.Event) -> None:
        """Sample loop lag every interval until ``stop`` is set."""
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            expected = loop.time() + self._sample_interval
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._sample_interval)
            lag_ms = max(0.0, loop.time() - expected) * 1000.0
            self.evaluate_lag(lag_ms)
