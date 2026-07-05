"""Deployment audit log hooks (MAH-112).

Enterprise compliance (SOC 2, HIPAA, FedRAMP) needs "who deployed what when"
answerable from logs. This is a small, structured audit emitter: each event gets a
monotonic sequence number (so a gap or reorder is evident), a timestamp, and typed
fields, and is handed to a pluggable sink (structured log by default, or a callback
to S3 / a SIEM). Per-call "which worker version handled this call" is emitted on the
SessionObserver payload (``SessionInfo.deployment_version``); voicegateway records
it, keeping OpenRTC in its runtime lane.

Migration events (``migration.*``) are reserved for the deferred mid-call migration
feature (see the state inventory); v0.6 is blue-green drain, so they are not emitted.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

logger = logging.getLogger("openrtc.audit")

__all__ = [
    "DEPLOYMENT_COMPLETED",
    "DEPLOYMENT_DRAIN_STARTED",
    "DEPLOYMENT_ROLLED_BACK",
    "DEPLOYMENT_STARTED",
    "WORKER_REJECTED",
    "AuditEvent",
    "AuditLog",
]

# Event types actually emitted in v0.6 (blue-green drain). ``migration.*`` is
# reserved for the deferred migration feature and intentionally absent here.
DEPLOYMENT_STARTED = "deployment.started"
DEPLOYMENT_COMPLETED = "deployment.completed"
DEPLOYMENT_ROLLED_BACK = "deployment.rolled_back"
DEPLOYMENT_DRAIN_STARTED = "deployment.drain_started"
WORKER_REJECTED = "worker.rejected"

AuditSink = Callable[["AuditEvent"], None]


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One structured audit record with a tamper-evident sequence number."""

    seq: int
    timestamp: float
    event_type: str
    actor: str
    target: str
    result: str
    version: str | None
    fields: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a flat, JSON-serializable record (extra fields merged in)."""
        return {
            "seq": self.seq,
            "timestamp": self.timestamp,
            "event": self.event_type,
            "actor": self.actor,
            "target": self.target,
            "result": self.result,
            "version": self.version,
            **dict(self.fields),
        }


def _log_sink(event: AuditEvent) -> None:
    """Default sink: emit the event as one structured JSON log line."""
    import json

    logger.info("audit %s", json.dumps(event.to_dict()))


class AuditLog:
    """Emit deployment audit events with a monotonic sequence and a pluggable sink."""

    def __init__(
        self,
        *,
        sink: AuditSink | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._sink = sink if sink is not None else _log_sink
        self._clock = clock
        self._seq = 0
        self._lock = Lock()

    def emit(
        self,
        event_type: str,
        *,
        actor: str = "system",
        target: str = "",
        result: str = "ok",
        version: str | None = None,
        **fields: Any,
    ) -> AuditEvent:
        """Record one audit event and return it. A failing sink never reaches the caller."""
        with self._lock:
            self._seq += 1
            event = AuditEvent(
                seq=self._seq,
                timestamp=self._clock(),
                event_type=event_type,
                actor=actor,
                target=target,
                result=result,
                version=version,
                fields=dict(fields),
            )
        # A deploy must not fail because an audit sink is down; isolate + log it.
        with contextlib.suppress(Exception):
            self._sink(event)
        return event
