"""Per-session CPU attribution via statistical sampling (MAH-89).

Exact per-session CPU is not available in a shared asyncio loop, so this samples,
at high frequency from a background thread, which session's task is currently
running on the loop (via the task->session tags from :mod:`task_attribution`),
and accumulates counts. ``cpu_pct`` is a session's share of sampled running time;
``cpu_seconds`` is ``samples x sample_interval``. It is sampling-based, not exact
(a session on-CPU more often ranks higher, which distinguishes workloads); the
precise "who is blocking the loop right now" signal is the slow-session detector
(MAH-90), which shares this same task->session foundation. One ``current_task``
read per sample keeps it well under the <2% CPU budget.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from openrtc.observability.task_attribution import task_session_id

__all__ = [
    "SessionCpu",
    "SessionCpuAccumulator",
    "SessionCpuSampler",
    "default_running_session_provider",
]

_DEFAULT_SAMPLE_INTERVAL_S = 0.01

RunningSessionProvider = Callable[[], str | None]
SessionsProvider = Callable[[], Mapping[str, str]]


@dataclass(frozen=True, slots=True)
class SessionCpu:
    """A per-session CPU sample: share of running time and approximate CPU seconds."""

    session_id: str
    agent_name: str
    cpu_pct: float
    cpu_seconds: float
    samples: int


class SessionCpuAccumulator:
    """Accumulate sampled running-session ids into per-session CPU shares."""

    def __init__(self) -> None:
        self._samples: dict[str, int] = {}
        self._total = 0

    def record(self, session_id: str | None) -> None:
        """Record one sample of the currently-running session (``None`` = idle/framework)."""
        self._total += 1
        if session_id is not None:
            self._samples[session_id] = self._samples.get(session_id, 0) + 1

    def snapshot(
        self, sessions: Mapping[str, str], sample_interval: float
    ) -> dict[str, SessionCpu]:
        """Compute per-session CPU shares for the currently-active sessions."""
        self._samples = {s: c for s, c in self._samples.items() if s in sessions}
        result: dict[str, SessionCpu] = {}
        for session_id, agent_name in sessions.items():
            count = self._samples.get(session_id, 0)
            pct = (count / self._total * 100.0) if self._total else 0.0
            result[session_id] = SessionCpu(
                session_id=session_id,
                agent_name=agent_name,
                cpu_pct=round(pct, 1),
                cpu_seconds=round(count * sample_interval, 2),
                samples=count,
            )
        return result


def default_running_session_provider(loop: asyncio.AbstractEventLoop) -> str | None:
    """Return the session_id of the task currently running on ``loop`` (best-effort)."""
    task = asyncio.current_task(loop)
    if task is None:
        return None
    return task_session_id(task)


class SessionCpuSampler:
    """Sample the running session on a background thread; report per-session shares."""

    def __init__(
        self,
        *,
        sessions_provider: SessionsProvider,
        running_session_provider: RunningSessionProvider,
        sample_interval: float = _DEFAULT_SAMPLE_INTERVAL_S,
    ) -> None:
        self._sessions_provider = sessions_provider
        self._running_session_provider = running_session_provider
        self._sample_interval = sample_interval
        self._acc = SessionCpuAccumulator()
        self._latest: dict[str, SessionCpu] = {}
        self._last_running: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def sample_once(self) -> None:
        """Record one sample of the currently-running session."""
        session_id = self._running_session_provider()
        if session_id is not None:
            self._last_running = session_id
        self._acc.record(session_id)

    def last_running_session(self) -> str | None:
        """Return the last non-idle session sampled on-CPU (the block-attribution source)."""
        return self._last_running

    def report(self) -> dict[str, SessionCpu]:
        """Recompute and return per-session CPU shares from accumulated samples."""
        self._latest = self._acc.snapshot(
            dict(self._sessions_provider()), self._sample_interval
        )
        return self._latest

    def snapshot(self) -> dict[str, SessionCpu]:
        """Return the most recently reported per-session CPU map (copy)."""
        return dict(self._latest)

    def start(self) -> None:
        """Start the background sampling thread; idempotent."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="openrtc-cpu-sampler", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._sample_interval):
            with contextlib.suppress(Exception):
                self.sample_once()

    def stop(self) -> None:
        """Stop the sampling thread and join it; idempotent."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
