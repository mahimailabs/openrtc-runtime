"""Deployment audit log hooks (MAH-112)."""

from __future__ import annotations

import json
from typing import Any

from livekit.agents import Agent

from openrtc.core.audit import (
    DEPLOYMENT_DRAIN_STARTED,
    DEPLOYMENT_STARTED,
    WORKER_REJECTED,
    AuditEvent,
    AuditLog,
)


class _Agent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="a")


class _Clock:
    def __init__(self, t: float = 100.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_emit_assigns_monotonic_sequence() -> None:
    log = AuditLog(sink=lambda _e: None, clock=_Clock())
    a = log.emit(DEPLOYMENT_STARTED, version="v2.0.0")
    b = log.emit(DEPLOYMENT_DRAIN_STARTED, version="v1.0.0")
    c = log.emit(WORKER_REJECTED, result="rejected", version="v0.9.0")
    assert [a.seq, b.seq, c.seq] == [1, 2, 3]  # monotonic, tamper-evident


def test_event_carries_all_fields() -> None:
    clock = _Clock(1234.0)
    log = AuditLog(sink=lambda _e: None, clock=clock)
    event = log.emit(
        DEPLOYMENT_STARTED,
        actor="deployer",
        target="deployment",
        result="ok",
        version="v2.0.0",
        worker_id="w-1",
    )
    assert event.event_type == "deployment.started"
    assert event.actor == "deployer"
    assert event.target == "deployment"
    assert event.result == "ok"
    assert event.version == "v2.0.0"
    assert event.timestamp == 1234.0
    assert event.fields == {"worker_id": "w-1"}


def test_defaults_actor_system_result_ok() -> None:
    log = AuditLog(sink=lambda _e: None, clock=_Clock())
    event = log.emit(DEPLOYMENT_STARTED)
    assert event.actor == "system"
    assert event.result == "ok"
    assert event.version is None


def test_sink_receives_events_in_order() -> None:
    seen: list[AuditEvent] = []
    log = AuditLog(sink=seen.append, clock=_Clock())
    log.emit(DEPLOYMENT_STARTED, version="v2")
    log.emit(DEPLOYMENT_DRAIN_STARTED, version="v1")
    assert [e.event_type for e in seen] == [
        "deployment.started",
        "deployment.drain_started",
    ]
    assert [e.seq for e in seen] == [1, 2]


def test_to_dict_is_json_serializable() -> None:
    log = AuditLog(sink=lambda _e: None, clock=_Clock(9.0))
    event = log.emit(DEPLOYMENT_STARTED, version="v2", worker_id="w-1")
    payload = event.to_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["event"] == "deployment.started"
    assert payload["seq"] == 1
    assert payload["worker_id"] == "w-1"  # extra fields flattened in


def test_default_sink_does_not_raise() -> None:
    # Constructed without an explicit sink: uses the structured-log default.
    log = AuditLog(clock=_Clock())
    event = log.emit(DEPLOYMENT_STARTED, version="v2")
    assert event.seq == 1


def test_sink_fault_is_isolated() -> None:
    def _bad(_e: Any) -> None:
        raise RuntimeError("sink down")

    log = AuditLog(sink=_bad, clock=_Clock())
    # A failing sink must not break the caller (a deploy must not fail on audit).
    event = log.emit(DEPLOYMENT_STARTED, version="v2")
    assert event.seq == 1


# --- pool integration -------------------------------------------------------


def test_pool_has_audit_log() -> None:
    from openrtc import AgentPool

    pool = AgentPool(agent=_Agent, enable_introspection=False)
    assert isinstance(pool.audit_log, AuditLog)


def test_begin_drain_emits_audit_event() -> None:
    from openrtc import AgentPool

    class _StubPool:
        draining = False

        def begin_drain(self) -> None:
            self.draining = True

    seen: list[AuditEvent] = []
    pool = AgentPool(
        agent=_Agent,
        deployment_version="v2.0.0",
        audit_sink=seen.append,
        enable_introspection=False,
    )
    pool._server._coroutine_pool = _StubPool()  # type: ignore[attr-defined]

    pool.begin_drain()

    assert len(seen) == 1
    assert seen[0].event_type == "deployment.drain_started"
    assert seen[0].version == "v2.0.0"
    assert seen[0].target == "worker"


def test_session_info_carries_deployment_version() -> None:
    from types import SimpleNamespace

    from openrtc.core.session_view import for_livekit
    from openrtc.observability.base_observer import _build_session_info

    view = for_livekit(
        SimpleNamespace(
            job=SimpleNamespace(metadata=None, id="j"),
            room=SimpleNamespace(metadata=None, name="r"),
        )
    )
    info = _build_session_info("a", view, "v2.0.0")
    assert info.deployment_version == "v2.0.0"
    # Default (untagged worker): None.
    assert _build_session_info("a", view).deployment_version is None
