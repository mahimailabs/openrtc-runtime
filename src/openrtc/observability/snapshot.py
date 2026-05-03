"""Typed snapshot payload returned by ``RuntimeMetricsStore.snapshot``."""

from __future__ import annotations

from dataclasses import dataclass


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
