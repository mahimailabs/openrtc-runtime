"""Tenant tagging on metrics, snapshot, and openrtc top (MAH-105)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from openrtc.cli.top_cli import build_top_table, filter_and_sort
from openrtc.core.session_view import for_livekit
from openrtc.observability.base_observer import _build_session_info
from openrtc.observability.metrics import RuntimeMetricsStore


def _ctx(job_metadata: Any = None) -> Any:
    return for_livekit(
        SimpleNamespace(
            job=SimpleNamespace(metadata=job_metadata, id="j1", room=None),
            room=SimpleNamespace(metadata=None, name="r"),
        )
    )


# --- observer payload (voicegateway reads metadata["tenant"]) ---------------


def test_metadata_always_carries_resolved_tenant() -> None:
    # Present tenant is carried through.
    info = _build_session_info("sales", _ctx('{"tenant": "acme"}'))
    assert info.metadata["tenant"] == "acme"
    # Absent tenant is injected as "default", so voicegateway always sees it.
    info = _build_session_info("sales", _ctx('{"agent": "sales"}'))
    assert info.metadata["tenant"] == "default"
    assert info.tenant == "default"


# --- per-tenant metric counts ----------------------------------------------


def test_sessions_by_tenant_tracks_starts_and_finishes() -> None:
    store = RuntimeMetricsStore()
    store.record_session_started("sales", "acme")
    store.record_session_started("support", "acme")
    store.record_session_started("sales", "globex")

    assert store.active_by_tenant() == {"acme": 2, "globex": 1}

    store.record_session_finished("sales", "acme")
    assert store.active_by_tenant() == {"acme": 1, "globex": 1}
    store.record_session_finished("support", "acme")
    assert store.active_by_tenant() == {"globex": 1}  # key removed at zero


def test_active_by_tenant_returns_a_copy() -> None:
    store = RuntimeMetricsStore()
    store.record_session_started("sales", "acme")
    counts = store.active_by_tenant()
    counts["acme"] = 99
    assert store.active_by_tenant()["acme"] == 1


def test_snapshot_exposes_sessions_by_tenant() -> None:
    store = RuntimeMetricsStore()
    store.record_session_started("sales", "acme")
    store.record_session_started("sales", "acme")
    snap = store.snapshot(registered_agents=1)
    assert snap.sessions_by_tenant == {"acme": 2}
    assert snap.to_dict()["sessions_by_tenant"] == {"acme": 2}


def test_stream_events_carry_tenant() -> None:
    store = RuntimeMetricsStore()
    store.record_session_started("sales", "acme")
    store.record_session_finished("sales", "acme")
    events = store.drain_stream_events()
    assert [e.get("tenant") for e in events] == ["acme", "acme"]


def test_failure_event_carries_tenant() -> None:
    store = RuntimeMetricsStore()
    store.record_session_failure("sales", RuntimeError("boom"), "acme")
    event = store.drain_stream_events()[0]
    assert event["tenant"] == "acme"
    assert event["event"] == "session_failed"


# --- openrtc top tenant filter ----------------------------------------------


def _rows() -> list[dict[str, Any]]:
    return [
        {
            "session_id": "s1",
            "agent_name": "sales",
            "tenant": "acme",
            "status": "active",
        },
        {
            "session_id": "s2",
            "agent_name": "support",
            "tenant": "globex",
            "status": "active",
        },
        {
            "session_id": "s3",
            "agent_name": "sales",
            "tenant": "acme",
            "status": "active",
        },
    ]


def test_top_filter_by_tenant() -> None:
    acme = filter_and_sort(
        _rows(), sort_key="session_id", status_filter="all", tenant_filter="acme"
    )
    assert {r["session_id"] for r in acme} == {"s1", "s3"}


def test_top_table_respects_tenant_filter() -> None:
    table = build_top_table(_rows(), sort_key="session_id", tenant_filter="globex")
    assert table.row_count == 1
