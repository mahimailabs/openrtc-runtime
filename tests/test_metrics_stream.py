"""Tests for JSONL metrics stream, sink, and RuntimeReporter export."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pytest

from openrtc.cli_app import RuntimeReporter
from openrtc.observability.metrics import MetricsStreamEvent
from openrtc.observability.snapshot import PoolRuntimeSnapshot
from openrtc.observability.stream import (
    KIND_EVENT,
    KIND_SNAPSHOT,
    METRICS_STREAM_SCHEMA_VERSION,
    JsonlMetricsSink,
    parse_metrics_jsonl_line,
    snapshot_envelope,
)


def _read_jsonl_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").split("\n") if ln.strip()]


def _wait_for_jsonl_lines(
    path: Path,
    *,
    min_lines: int,
    timeout: float = 5.0,
    poll_interval: float = 0.02,
) -> list[str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        lines = _read_jsonl_lines(path)
        if len(lines) >= min_lines:
            return lines
        time.sleep(poll_interval)
    raise AssertionError(
        f"timed out after {timeout}s waiting for {min_lines} JSONL line(s) in {path!s}",
    )


class _StubPool:
    def __init__(self, snapshot: PoolRuntimeSnapshot) -> None:
        self._snap = snapshot

    def drain_metrics_stream_events(self) -> list[MetricsStreamEvent]:
        return []

    def runtime_snapshot(self) -> PoolRuntimeSnapshot:
        return self._snap


def test_parse_metrics_jsonl_line() -> None:
    good = json.dumps(
        {
            "schema_version": METRICS_STREAM_SCHEMA_VERSION,
            "kind": KIND_SNAPSHOT,
            "seq": 9,
            "wall_time_unix": 12.0,
            "payload": {"registered_agents": 0},
        }
    )
    parsed = parse_metrics_jsonl_line(good)
    assert parsed is not None
    assert parsed["seq"] == 9
    assert parse_metrics_jsonl_line("") is None
    assert parse_metrics_jsonl_line("not-json") is None
    assert parse_metrics_jsonl_line('{"schema_version": 999}') is None


def test_parse_metrics_jsonl_line_rejects_bool_wall_time() -> None:
    bad = json.dumps(
        {
            "schema_version": METRICS_STREAM_SCHEMA_VERSION,
            "kind": KIND_SNAPSHOT,
            "seq": 1,
            "wall_time_unix": True,
            "payload": {},
        }
    )
    assert parse_metrics_jsonl_line(bad) is None


def test_jsonl_sink_seq_property(
    tmp_path: Path,
    minimal_pool_runtime_snapshot: PoolRuntimeSnapshot,
) -> None:
    """Cover :attr:`JsonlMetricsSink.seq` (lock + counter)."""
    snap = minimal_pool_runtime_snapshot
    path = tmp_path / "seq.jsonl"
    sink = JsonlMetricsSink(path)
    sink.open()
    assert sink.seq == 0
    sink.write_snapshot(snap)
    assert sink.seq == 1
    sink.write_event({"event": "x"})
    assert sink.seq == 2
    sink.close()


def test_parse_metrics_jsonl_line_rejects_malformed_envelope() -> None:
    base = {
        "schema_version": METRICS_STREAM_SCHEMA_VERSION,
        "kind": KIND_SNAPSHOT,
        "seq": 1,
        "wall_time_unix": 1.0,
        "payload": {"x": 1},
    }
    bad_seq = {**base, "seq": True}
    assert parse_metrics_jsonl_line(json.dumps(bad_seq)) is None
    bad_wall = {**base, "wall_time_unix": None}
    assert parse_metrics_jsonl_line(json.dumps(bad_wall)) is None
    bad_payload = {**base, "payload": None}
    assert parse_metrics_jsonl_line(json.dumps(bad_payload)) is None
    bad_payload2 = {**base, "payload": [1, 2]}
    assert parse_metrics_jsonl_line(json.dumps(bad_payload2)) is None


def test_parse_metrics_jsonl_line_rejects_unknown_kind() -> None:
    bad = json.dumps(
        {
            "schema_version": METRICS_STREAM_SCHEMA_VERSION,
            "kind": "future-kind",
            "seq": 1,
            "wall_time_unix": 0.0,
            "payload": {},
        }
    )
    assert parse_metrics_jsonl_line(bad) is None


def test_jsonl_metrics_sink_requires_open_before_write(
    tmp_path: Path,
    minimal_pool_runtime_snapshot: PoolRuntimeSnapshot,
) -> None:
    sink = JsonlMetricsSink(tmp_path / "unopened.jsonl")
    with pytest.raises(RuntimeError, match="open"):
        sink.write_snapshot(minimal_pool_runtime_snapshot)
    with pytest.raises(RuntimeError, match="open"):
        sink.write_event({"event": "x"})


def test_parse_metrics_jsonl_line_accepts_event() -> None:
    line = json.dumps(
        {
            "schema_version": METRICS_STREAM_SCHEMA_VERSION,
            "kind": "event",
            "seq": 2,
            "wall_time_unix": 3.0,
            "payload": {"event": "session_started", "agent": "x"},
        },
        sort_keys=True,
    )
    rec = parse_metrics_jsonl_line(line)
    assert rec is not None
    assert rec["kind"] == "event"
    assert rec["payload"]["agent"] == "x"


def test_jsonl_sink_writes_snapshot_then_event(
    tmp_path: Path,
    minimal_pool_runtime_snapshot: PoolRuntimeSnapshot,
) -> None:
    path = tmp_path / "e.jsonl"
    sink = JsonlMetricsSink(path)
    sink.open()
    sink.write_snapshot(minimal_pool_runtime_snapshot)
    sink.write_event({"event": "session_finished", "agent": "a"})
    sink.close()
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["kind"] == KIND_SNAPSHOT
    assert json.loads(lines[1])["kind"] == "event"
    assert json.loads(lines[1])["seq"] == 2


def test_runtime_metrics_store_drains_stream_events() -> None:
    from openrtc.observability.metrics import RuntimeMetricsStore

    store = RuntimeMetricsStore()
    store.record_session_started("dental")
    drained = store.drain_stream_events()
    assert drained == [{"event": "session_started", "agent": "dental"}]
    assert store.drain_stream_events() == []


def test_runtime_metrics_store_overflow_emits_synthetic_on_drain(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from openrtc.observability import metrics as resources_mod
    from openrtc.observability.metrics import RuntimeMetricsStore

    monkeypatch.setattr(resources_mod, "_STREAM_EVENTS_MAXLEN", 3)
    store = RuntimeMetricsStore()
    with caplog.at_level(logging.WARNING, logger="openrtc"):
        for _ in range(6):
            store.record_session_started("x")
    drained = store.drain_stream_events()
    assert len([e for e in drained if e.get("event") == "session_started"]) == 3
    overflow_rows = [e for e in drained if e.get("event") == "metrics_stream_overflow"]
    assert len(overflow_rows) == 1
    assert overflow_rows[0].get("overflow_dropped") == 3
    assert "metrics stream buffer full" in caplog.text
    assert store.drain_stream_events() == []


def test_snapshot_envelope_shape(
    minimal_pool_runtime_snapshot: PoolRuntimeSnapshot,
) -> None:
    snap = minimal_pool_runtime_snapshot
    env = snapshot_envelope(seq=7, snapshot=snap)
    assert env["schema_version"] == METRICS_STREAM_SCHEMA_VERSION
    assert env["kind"] == KIND_SNAPSHOT
    assert env["seq"] == 7
    assert isinstance(env["wall_time_unix"], float)
    assert env["payload"] == snap.to_dict()


def test_jsonl_sink_truncates_on_open_and_increments_seq(
    tmp_path: Path,
    minimal_pool_runtime_snapshot: PoolRuntimeSnapshot,
) -> None:
    path = tmp_path / "stream.jsonl"
    sink = JsonlMetricsSink(path)
    sink.open()
    snap = minimal_pool_runtime_snapshot
    sink.write_snapshot(snap)
    sink.write_snapshot(snap)
    sink.close()

    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    a, b = (json.loads(line) for line in lines)
    assert a["seq"] == 1
    assert b["seq"] == 2


def test_jsonl_sink_new_open_truncates_previous_file(
    tmp_path: Path,
    minimal_pool_runtime_snapshot: PoolRuntimeSnapshot,
) -> None:
    path = tmp_path / "stream.jsonl"
    sink1 = JsonlMetricsSink(path)
    sink1.open()
    sink1.write_snapshot(minimal_pool_runtime_snapshot)
    sink1.close()

    sink2 = JsonlMetricsSink(path)
    sink2.open()
    sink2.write_snapshot(minimal_pool_runtime_snapshot)
    sink2.close()

    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    assert json.loads(lines[0])["seq"] == 1


def test_runtime_reporter_emits_snapshot_then_drained_events_in_order(
    tmp_path: Path,
    minimal_pool_runtime_snapshot: PoolRuntimeSnapshot,
) -> None:
    """Each tick writes one snapshot line, then any events from the pool (order)."""

    class _PoolWithOneEvent:
        def __init__(self, snap: PoolRuntimeSnapshot) -> None:
            self._snap = snap
            self._sent = False

        def runtime_snapshot(self) -> PoolRuntimeSnapshot:
            return self._snap

        def drain_metrics_stream_events(self) -> list[MetricsStreamEvent]:
            if self._sent:
                return []
            self._sent = True
            return [{"event": "session_started", "agent": "demo"}]

    path = tmp_path / "ordered.jsonl"
    pool = _PoolWithOneEvent(minimal_pool_runtime_snapshot)
    reporter = RuntimeReporter(
        pool,
        dashboard=False,
        refresh_seconds=0.25,
        json_output_path=None,
        metrics_jsonl_path=path,
        metrics_jsonl_interval=0.25,
    )
    reporter.start()
    try:
        lines = _wait_for_jsonl_lines(path, min_lines=2, timeout=5.0)
    finally:
        reporter.stop()

    first = json.loads(lines[0])
    assert first["kind"] == KIND_SNAPSHOT
    assert first["seq"] >= 1
    second = json.loads(lines[1])
    assert second["kind"] == KIND_EVENT
    assert second["payload"]["event"] == "session_started"


def test_runtime_reporter_emits_jsonl_periodically(
    tmp_path: Path,
    minimal_pool_runtime_snapshot: PoolRuntimeSnapshot,
) -> None:
    path = tmp_path / "live.jsonl"
    pool = _StubPool(minimal_pool_runtime_snapshot)
    reporter = RuntimeReporter(
        pool,
        dashboard=False,
        refresh_seconds=0.25,
        json_output_path=None,
        metrics_jsonl_path=path,
        metrics_jsonl_interval=0.25,
    )
    reporter.start()
    try:
        lines = _wait_for_jsonl_lines(path, min_lines=2, timeout=5.0)
    finally:
        reporter.stop()

    first = json.loads(lines[0])
    last = json.loads(lines[-1])
    assert first["schema_version"] == METRICS_STREAM_SCHEMA_VERSION
    assert last["seq"] > first["seq"]
