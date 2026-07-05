"""Thread-safe runtime counters for a running shared worker."""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import Lock
from typing import TypedDict, cast

from openrtc.observability.resident_set import get_process_resident_set_info
from openrtc.observability.savings import estimate_shared_worker_savings
from openrtc.observability.snapshot import PoolRuntimeSnapshot
from openrtc.utils.validation import DEFAULT_TENANT

__all__ = ["MetricsStreamEvent", "RuntimeMetricsStore"]

logger = logging.getLogger("openrtc")

_STREAM_EVENTS_MAXLEN = 256


class MetricsStreamEvent(TypedDict, total=False):
    """One drained session lifecycle row for JSONL export.

    Rows always include ``event``, ``agent``, and ``tenant`` from the store;
    ``session_failed`` rows may include ``error``. A synthetic
    ``metrics_stream_overflow`` row may include ``overflow_dropped``.
    """

    event: str
    agent: str
    tenant: str
    error: str
    overflow_dropped: int


@dataclass(slots=True)
class RuntimeMetricsStore:
    """Thread-safe counters for a running shared worker."""

    started_at: float = field(default_factory=time.monotonic)
    total_sessions_started: int = 0
    total_session_failures: int = 0
    last_routed_agent: str | None = None
    last_error: str | None = None
    sessions_by_agent: dict[str, int] = field(default_factory=dict)
    sessions_by_tenant: dict[str, int] = field(default_factory=dict)
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
            "sessions_by_tenant": dict(self.sessions_by_tenant),
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
        raw_sbt = state.get("sessions_by_tenant", {})
        if not isinstance(raw_sbt, Mapping):
            raise TypeError("pickle state 'sessions_by_tenant' must be a mapping")
        self.sessions_by_tenant = {
            str(key): int(value) for key, value in dict(raw_sbt).items()
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

    def record_session_started(
        self, agent_name: str, tenant: str = DEFAULT_TENANT
    ) -> None:
        """Increment active counters for one routed session (per agent + per tenant)."""
        with self._lock:
            self.total_sessions_started += 1
            self.last_routed_agent = agent_name
            self.sessions_by_agent[agent_name] = (
                self.sessions_by_agent.get(agent_name, 0) + 1
            )
            self.sessions_by_tenant[tenant] = self.sessions_by_tenant.get(tenant, 0) + 1
            self._append_stream_event_locked(
                {"event": "session_started", "agent": agent_name, "tenant": tenant},
            )

    def record_session_finished(
        self, agent_name: str, tenant: str = DEFAULT_TENANT
    ) -> None:
        """Decrement active counters once a session exits (per agent + per tenant)."""
        with self._lock:
            self._decrement_locked(self.sessions_by_agent, agent_name)
            self._decrement_locked(self.sessions_by_tenant, tenant)
            self._append_stream_event_locked(
                {"event": "session_finished", "agent": agent_name, "tenant": tenant},
            )

    @staticmethod
    def _decrement_locked(counts: dict[str, int], key: str) -> None:
        """Drop one from ``counts[key]``, removing the key at zero. Caller holds the lock."""
        next_value = counts.get(key, 0) - 1
        if next_value > 0:
            counts[key] = next_value
        else:
            counts.pop(key, None)

    def record_session_failure(
        self, agent_name: str, exc: BaseException, tenant: str = DEFAULT_TENANT
    ) -> None:
        """Track a failed session attempt with the most recent error."""
        with self._lock:
            self.last_routed_agent = agent_name
            self.total_session_failures += 1
            self.last_error = f"{exc.__class__.__name__}: {exc}"
            self._append_stream_event_locked(
                {
                    "event": "session_failed",
                    "agent": agent_name,
                    "tenant": tenant,
                    "error": f"{exc.__class__.__name__}: {exc}"[:500],
                },
            )

    def active_by_agent(self) -> dict[str, int]:
        """Return a thread-safe copy of the live active-session count per agent.

        This is the per-agent load gauge the backpressure filter (MAH-96) reads to
        decide whether an agent is at its cap.
        """
        with self._lock:
            return dict(self.sessions_by_agent)

    def active_by_tenant(self) -> dict[str, int]:
        """Return a thread-safe copy of the live active-session count per tenant.

        The per-tenant load gauge the tenant backpressure filter (MAH-103) reads.
        """
        with self._lock:
            return dict(self.sessions_by_tenant)

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
            sessions_by_tenant = dict(self.sessions_by_tenant)
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
            sessions_by_tenant=sessions_by_tenant,
            resident_set=rss_info,
            savings_estimate=estimate_shared_worker_savings(
                agent_count=registered_agents,
                shared_worker_bytes=rss_info.bytes_value,
            ),
        )
