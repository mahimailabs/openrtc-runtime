"""Per-session memory attribution in the shared worker (MAH-88).

Per-session RSS is not exactly measurable in one CPython process: the allocator
does not tag allocations by async context, and ``tracemalloc`` groups by code
location (identical across sessions running the same agent), so neither can
attribute a shared process's RSS to a session. This sampler therefore reports an
honest approximation: an **equal share** of live process RSS across the active
sessions, sampled on an interval, with a per-session peak held over the session's
lifetime. It answers "how much memory pressure, and is it growing" at the pool
level and, because it shares the real RSS, the per-session numbers sum back to
process RSS (the acceptance criterion).

To find *which* session is hot, use CPU attribution (MAH-89) and the slow-session
detector (MAH-90), which can differentiate by scheduling time; or run
``isolation="process"`` for hard per-session memory accounting. Sampling cost is
one ``psutil`` RSS read per interval — well under the <1% CPU / <50 MB budget.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from openrtc.observability.resident_set import process_resident_set_bytes

__all__ = ["SessionMemory", "SessionMemorySampler"]

_BYTES_PER_MB = 1024 * 1024
_DEFAULT_INTERVAL_S = 1.0

# session_id -> agent_name for the sessions currently live in the worker.
SessionsProvider = Callable[[], Mapping[str, str]]
RssReader = Callable[[], int | None]


@dataclass(frozen=True, slots=True)
class SessionMemory:
    """A per-session memory sample: current equal-share MB and lifetime peak MB."""

    session_id: str
    agent_name: str
    current_mb: float
    peak_mb: float


class SessionMemorySampler:
    """Sample live process RSS and attribute an equal share to each live session."""

    def __init__(
        self,
        *,
        sessions_provider: SessionsProvider,
        interval: float = _DEFAULT_INTERVAL_S,
        rss_reader: RssReader = process_resident_set_bytes,
    ) -> None:
        self._sessions_provider = sessions_provider
        self._interval = interval
        self._rss_reader = rss_reader
        self._peaks: dict[str, float] = {}
        self._latest: dict[str, SessionMemory] = {}

    def sample_once(self) -> dict[str, SessionMemory]:
        """Take one sample: read RSS, equal-share it, update peaks; return the map."""
        active = dict(self._sessions_provider())
        # Drop peaks for sessions that have ended.
        self._peaks = {sid: mb for sid, mb in self._peaks.items() if sid in active}
        rss = self._rss_reader()
        result: dict[str, SessionMemory] = {}
        if rss is not None and active:
            share_mb = (rss / _BYTES_PER_MB) / len(active)
            for session_id, agent_name in active.items():
                peak = max(self._peaks.get(session_id, 0.0), share_mb)
                self._peaks[session_id] = peak
                result[session_id] = SessionMemory(
                    session_id=session_id,
                    agent_name=agent_name,
                    current_mb=round(share_mb, 1),
                    peak_mb=round(peak, 1),
                )
        self._latest = result
        return result

    def snapshot(self) -> dict[str, SessionMemory]:
        """Return the most recent per-session memory map (copy)."""
        return dict(self._latest)

    async def run(self, stop: asyncio.Event) -> None:
        """Sample every ``interval`` seconds until ``stop`` is set."""
        while not stop.is_set():
            with contextlib.suppress(Exception):
                self.sample_once()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._interval)
