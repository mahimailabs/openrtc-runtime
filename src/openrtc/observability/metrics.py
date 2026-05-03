from __future__ import annotations

import logging
import sys
import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from openrtc.core.config import AgentConfig

logger = logging.getLogger("openrtc")

_STREAM_EVENTS_MAXLEN = 256


class MetricsStreamEvent(TypedDict, total=False):
    """One drained session lifecycle row for JSONL export.

    Rows always include ``event`` and ``agent`` from the store; ``session_failed``
    rows may include ``error``. A synthetic ``metrics_stream_overflow`` row may
    include ``overflow_dropped``.
    """

    event: str
    agent: str
    error: str
    overflow_dropped: int


@dataclass(frozen=True, slots=True)
class AgentDiskFootprint:
    """On-disk size for a single agent module file."""

    name: str
    path: Path
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ProcessResidentSetInfo:
    """One platform-specific memory figure for this process.

    Always interpret :attr:`bytes_value` together with :attr:`metric` and
    :attr:`description`. Values are **not** comparable across operating systems.
    """

    bytes_value: int | None
    """Numeric value when available, else ``None``."""

    metric: str
    """Stable identifier: ``linux_vm_rss``, ``darwin_ru_max_rss``, or ``unavailable``."""

    description: str
    """What :attr:`bytes_value` represents on this OS (read this before comparing runs)."""


@dataclass(frozen=True, slots=True)
class SavingsEstimate:
    """Best-effort estimate of memory savings from one shared worker."""

    agent_count: int
    shared_worker_bytes: int | None
    estimated_separate_workers_bytes: int | None
    estimated_saved_bytes: int | None
    assumptions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PoolRuntimeSnapshot:
    """Typed runtime view of the current shared worker state."""

    timestamp: float
    uptime_seconds: float
    registered_agents: int
    active_sessions: int
    total_sessions_started: int
    total_session_failures: int
    last_routed_agent: str | None
    last_error: str | None
    sessions_by_agent: dict[str, int]
    resident_set: ProcessResidentSetInfo
    savings_estimate: SavingsEstimate

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable snapshot payload."""
        return {
            "timestamp": self.timestamp,
            "uptime_seconds": self.uptime_seconds,
            "registered_agents": self.registered_agents,
            "active_sessions": self.active_sessions,
            "total_sessions_started": self.total_sessions_started,
            "total_session_failures": self.total_session_failures,
            "last_routed_agent": self.last_routed_agent,
            "last_error": self.last_error,
            "sessions_by_agent": dict(self.sessions_by_agent),
            "resident_set": {
                "bytes": self.resident_set.bytes_value,
                "metric": self.resident_set.metric,
                "description": self.resident_set.description,
            },
            "savings_estimate": {
                "agent_count": self.savings_estimate.agent_count,
                "shared_worker_bytes": self.savings_estimate.shared_worker_bytes,
                "estimated_separate_workers_bytes": (
                    self.savings_estimate.estimated_separate_workers_bytes
                ),
                "estimated_saved_bytes": self.savings_estimate.estimated_saved_bytes,
                "assumptions": list(self.savings_estimate.assumptions),
            },
        }


@dataclass(slots=True)
class RuntimeMetricsStore:
    """Thread-safe counters for a running shared worker."""

    started_at: float = field(default_factory=time.monotonic)
    total_sessions_started: int = 0
    total_session_failures: int = 0
    last_routed_agent: str | None = None
    last_error: str | None = None
    sessions_by_agent: dict[str, int] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False, compare=False)
    _stream_events: deque[MetricsStreamEvent] = field(
        default_factory=deque,
        init=False,
        repr=False,
        compare=False,
    )
    _metrics_stream_overflow_since_drain: int = field(
        default=0,
        init=False,
        repr=False,
        compare=False,
    )

    def __getstate__(self) -> dict[str, object]:
        with self._lock:
            stream_events = list(self._stream_events)
        return {
            "started_at": self.started_at,
            "total_sessions_started": self.total_sessions_started,
            "total_session_failures": self.total_session_failures,
            "last_routed_agent": self.last_routed_agent,
            "last_error": self.last_error,
            "sessions_by_agent": dict(self.sessions_by_agent),
            "_stream_events": stream_events,
            "_metrics_stream_overflow_since_drain": self._metrics_stream_overflow_since_drain,
        }

    def __setstate__(self, state: Mapping[str, object]) -> None:
        started = state["started_at"]
        if not isinstance(started, (int, float)):
            raise TypeError("pickle state 'started_at' must be int or float")
        self.started_at = float(started)
        tss = state["total_sessions_started"]
        if not isinstance(tss, int):
            raise TypeError("pickle state 'total_sessions_started' must be int")
        self.total_sessions_started = tss
        tsf = state["total_session_failures"]
        if not isinstance(tsf, int):
            raise TypeError("pickle state 'total_session_failures' must be int")
        self.total_session_failures = tsf
        self.last_routed_agent = cast(str | None, state["last_routed_agent"])
        self.last_error = cast(str | None, state["last_error"])
        raw_sba = state["sessions_by_agent"]
        if not isinstance(raw_sba, Mapping):
            raise TypeError("pickle state 'sessions_by_agent' must be a mapping")
        self.sessions_by_agent = {
            str(key): int(value) for key, value in dict(raw_sba).items()
        }
        raw_events = state.get("_stream_events", [])
        if not isinstance(raw_events, list):
            raise TypeError("pickle state '_stream_events' must be a list")
        self._stream_events = deque(cast(list[MetricsStreamEvent], raw_events))
        overflow = state.get("_metrics_stream_overflow_since_drain", 0)
        if not isinstance(overflow, int):
            raise TypeError(
                "pickle state '_metrics_stream_overflow_since_drain' must be int"
            )
        self._metrics_stream_overflow_since_drain = overflow
        self._lock = Lock()

    def _append_stream_event_locked(self, event: MetricsStreamEvent) -> None:
        if len(self._stream_events) >= _STREAM_EVENTS_MAXLEN:
            self._metrics_stream_overflow_since_drain += 1
            logger.warning(
                "metrics stream buffer full (%s events); dropping event %r",
                _STREAM_EVENTS_MAXLEN,
                event.get("event"),
            )
            return
        self._stream_events.append(event)

    def record_session_started(self, agent_name: str) -> None:
        """Increment active counters for one routed session."""
        with self._lock:
            self.total_sessions_started += 1
            self.last_routed_agent = agent_name
            self.sessions_by_agent[agent_name] = (
                self.sessions_by_agent.get(agent_name, 0) + 1
            )
            self._append_stream_event_locked(
                {"event": "session_started", "agent": agent_name},
            )

    def record_session_finished(self, agent_name: str) -> None:
        """Decrement active counters once a session exits."""
        with self._lock:
            current = self.sessions_by_agent.get(agent_name, 0)
            next_value = current - 1
            if next_value > 0:
                self.sessions_by_agent[agent_name] = next_value
            else:
                self.sessions_by_agent.pop(agent_name, None)
            self._append_stream_event_locked(
                {"event": "session_finished", "agent": agent_name},
            )

    def record_session_failure(self, agent_name: str, exc: BaseException) -> None:
        """Track a failed session attempt with the most recent error."""
        with self._lock:
            self.last_routed_agent = agent_name
            self.total_session_failures += 1
            self.last_error = f"{exc.__class__.__name__}: {exc}"
            self._append_stream_event_locked(
                {
                    "event": "session_failed",
                    "agent": agent_name,
                    "error": f"{exc.__class__.__name__}: {exc}"[:500],
                },
            )

    def drain_stream_events(self) -> list[MetricsStreamEvent]:
        """Remove and return pending stream events for JSONL export (order preserved)."""
        with self._lock:
            out = list(self._stream_events)
            self._stream_events.clear()
            dropped = self._metrics_stream_overflow_since_drain
            self._metrics_stream_overflow_since_drain = 0
        if dropped > 0:
            out.append(
                {
                    "event": "metrics_stream_overflow",
                    "agent": "__openrtc__",
                    "overflow_dropped": dropped,
                },
            )
        return out

    def snapshot(self, *, registered_agents: int) -> PoolRuntimeSnapshot:
        """Return a typed snapshot for dashboards and automation."""
        with self._lock:
            sessions_by_agent = dict(self.sessions_by_agent)
            total_sessions_started = self.total_sessions_started
            total_session_failures = self.total_session_failures
            last_routed_agent = self.last_routed_agent
            last_error = self.last_error

        rss_info = get_process_resident_set_info()
        return PoolRuntimeSnapshot(
            timestamp=time.time(),
            uptime_seconds=max(time.monotonic() - self.started_at, 0.0),
            registered_agents=registered_agents,
            active_sessions=sum(sessions_by_agent.values()),
            total_sessions_started=total_sessions_started,
            total_session_failures=total_session_failures,
            last_routed_agent=last_routed_agent,
            last_error=last_error,
            sessions_by_agent=sessions_by_agent,
            resident_set=rss_info,
            savings_estimate=estimate_shared_worker_savings(
                agent_count=registered_agents,
                shared_worker_bytes=rss_info.bytes_value,
            ),
        )


def format_byte_size(num_bytes: int) -> str:
    """Return a short human-readable size string using binary units."""
    if num_bytes < 0:
        num_bytes = 0
    value = float(num_bytes)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for i, unit in enumerate(units):
        if value < 1024.0 or i == len(units) - 1:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{int(num_bytes)} B"


def file_size_bytes(path: Path) -> int:
    """Return the size of a file in bytes, or ``0`` if it cannot be read."""
    try:
        return path.stat().st_size
    except OSError as exc:
        logger.debug("Could not stat %s: %s", path, exc)
        return 0


def agent_disk_footprints(configs: Sequence[AgentConfig]) -> list[AgentDiskFootprint]:
    """Collect per-agent source file sizes when a path was recorded at registration."""
    footprints: list[AgentDiskFootprint] = []
    for config in configs:
        if config.source_path is None:
            continue
        path = config.source_path
        footprints.append(
            AgentDiskFootprint(
                name=config.name,
                path=path,
                size_bytes=file_size_bytes(path),
            )
        )
    return footprints


def get_process_resident_set_info() -> ProcessResidentSetInfo:
    """Return a single best-effort memory figure for this process.

    Semantics differ by platform; do not assume "RSS" means the same thing everywhere.

    **Linux** — Reads **VmRSS** from ``/proc/self/status`` (kernel-reported
    current resident set size; value in kiB in the file, returned here in bytes).
    This is a reasonable snapshot of *current* footprint at the time of the read.

    **macOS** — Uses :func:`resource.getrusage` with :data:`resource.RUSAGE_SELF`.
    CPython documents ``ru_maxrss`` **in bytes** on macOS. That field is the
    **maximum** resident set size the system has attributed to this process (a
    high-water / peak style figure), **not** the instantaneous current RSS.
    For live usage, use host or container metrics (e.g. Activity Monitor).

    **Other** (e.g. Windows): not implemented here; :attr:`ProcessResidentSetInfo.bytes_value`
    is ``None``.

    Linux intentionally uses ``/proc`` rather than ``getrusage`` so the Linux path
    reports a current VmRSS analogue; POSIX ``ru_maxrss`` on Linux is in different
    units than on macOS (see :mod:`resource` documentation).
    """
    if sys.platform.startswith("linux"):
        value = _linux_rss_bytes()
        return ProcessResidentSetInfo(
            bytes_value=value,
            metric="linux_vm_rss",
            description=(
                "Current resident set from VmRSS (/proc/self/status), converted to bytes; "
                "snapshot at query time."
            ),
        )
    if sys.platform == "darwin":
        value = _macos_rss_bytes()
        return ProcessResidentSetInfo(
            bytes_value=value,
            metric="darwin_ru_max_rss",
            description=(
                "Peak-style max resident set: resource.getrusage(RUSAGE_SELF).ru_maxrss "
                "in bytes on macOS (per CPython). Not instantaneous current RSS."
            ),
        )
    return ProcessResidentSetInfo(
        bytes_value=None,
        metric="unavailable",
        description=(
            "No resident-memory figure in OpenRTC on this platform (e.g. Windows)."
        ),
    )


def process_resident_set_bytes() -> int | None:
    """Return the numeric memory metric from :func:`get_process_resident_set_info`, or ``None``.

    The number alone is ambiguous across OSes (Linux current VmRSS vs macOS peak
    ``ru_maxrss``). Prefer :func:`get_process_resident_set_info` for :attr:`~ProcessResidentSetInfo.metric`
    and :attr:`~ProcessResidentSetInfo.description`.
    """
    return get_process_resident_set_info().bytes_value


def estimate_shared_worker_savings(
    *,
    agent_count: int,
    shared_worker_bytes: int | None,
) -> SavingsEstimate:
    """Estimate the value of one shared worker versus one worker per agent.

    The estimate intentionally uses only the current shared worker memory as a
    baseline. It assumes separate workers would each pay approximately the same
    base worker cost before per-call overhead.
    """
    assumptions = (
        "Estimated separate-worker memory multiplies the current shared-worker "
        "baseline by the number of registered agents.",
        "This is a best-effort comparison, not a container-orchestrator metric.",
        "Actual memory depends on active sessions, providers, and model loading.",
    )
    if agent_count <= 0 or shared_worker_bytes is None:
        return SavingsEstimate(
            agent_count=agent_count,
            shared_worker_bytes=shared_worker_bytes,
            estimated_separate_workers_bytes=None,
            estimated_saved_bytes=None,
            assumptions=assumptions,
        )

    separate_workers = shared_worker_bytes * agent_count
    saved_bytes = max(separate_workers - shared_worker_bytes, 0)
    return SavingsEstimate(
        agent_count=agent_count,
        shared_worker_bytes=shared_worker_bytes,
        estimated_separate_workers_bytes=separate_workers,
        estimated_saved_bytes=saved_bytes,
        assumptions=assumptions,
    )


def _linux_rss_bytes() -> int | None:
    """Read VmRSS (kiB in procfs) and convert to bytes."""
    try:
        text = Path("/proc/self/status").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) >= 2:
                # Value is in kB on Linux.
                return int(parts[1]) * 1024
    return None


def _macos_rss_bytes() -> int | None:
    """Return ``ru_maxrss`` on Darwin (bytes per CPython; max resident set, not current RSS)."""
    try:
        import resource
    except ImportError:  # pragma: no cover - ``resource`` is Unix-only (not on Windows)
        return None
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
    except OSError:
        return None
    # CPython documents ru_maxrss in *bytes* on macOS (unlike Linux ru_maxrss in KiB).
    value = int(usage.ru_maxrss)
    return value if value > 0 else None
