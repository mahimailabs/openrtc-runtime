from __future__ import annotations

import json
import time
from pathlib import Path

from openrtc.cli_app import RuntimeReporter
from openrtc.metrics_stream import (
    KIND_SNAPSHOT,
    METRICS_STREAM_SCHEMA_VERSION,
    JsonlMetricsSink,
    parse_metrics_jsonl_line,
    snapshot_envelope,
)
from openrtc.resources import (
    PoolRuntimeSnapshot,
    ProcessResidentSetInfo,
    SavingsEstimate,
)


def _minimal_snapshot() -> PoolRuntimeSnapshot:
    return PoolRuntimeSnapshot(
        timestamp=1.0,
        uptime_seconds=0.5,
        registered_agents=1,
        active_sessions=0,
        total_sessions_started=0,
        total_session_failures=0,
        last_routed_agent=None,
        last_error=None,
        sessions_by_agent={},
        resident_set=ProcessResidentSetInfo(
            bytes_value=1024,
            metric="test",
            description="test",
        ),
        savings_estimate=SavingsEstimate(
            agent_count=1,
            shared_worker_bytes=1024,
            estimated_separate_workers_bytes=1024,
            estimated_saved_bytes=0,
            assumptions=(),
        ),
    )


class _StubPool:
    def __init__(self) -> None:
        self._snap = _minimal_snapshot()

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


def test_snapshot_envelope_shape() -> None:
    snap = _minimal_snapshot()
    env = snapshot_envelope(seq=7, snapshot=snap)
    assert env["schema_version"] == METRICS_STREAM_SCHEMA_VERSION
    assert env["kind"] == KIND_SNAPSHOT
    assert env["seq"] == 7
    assert isinstance(env["wall_time_unix"], float)
    assert env["payload"] == snap.to_dict()


def test_jsonl_sink_truncates_on_open_and_increments_seq(tmp_path: Path) -> None:
    path = tmp_path / "stream.jsonl"
    sink = JsonlMetricsSink(path)
    sink.open()
    snap = _minimal_snapshot()
    sink.write_snapshot(snap)
    sink.write_snapshot(snap)
    sink.close()

    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    a, b = (json.loads(line) for line in lines)
    assert a["seq"] == 1
    assert b["seq"] == 2


def test_jsonl_sink_new_open_truncates_previous_file(tmp_path: Path) -> None:
    path = tmp_path / "stream.jsonl"
    sink1 = JsonlMetricsSink(path)
    sink1.open()
    sink1.write_snapshot(_minimal_snapshot())
    sink1.close()

    sink2 = JsonlMetricsSink(path)
    sink2.open()
    sink2.write_snapshot(_minimal_snapshot())
    sink2.close()

    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    assert json.loads(lines[0])["seq"] == 1


def test_runtime_reporter_emits_jsonl_periodically(tmp_path: Path) -> None:
    path = tmp_path / "live.jsonl"
    pool = _StubPool()
    reporter = RuntimeReporter(
        pool,
        dashboard=False,
        refresh_seconds=0.25,
        json_output_path=None,
        metrics_jsonl_path=path,
        metrics_jsonl_interval=0.25,
    )
    reporter.start()
    time.sleep(0.85)
    reporter.stop()

    lines = [ln for ln in path.read_text(encoding="utf-8").split("\n") if ln.strip()]
    assert len(lines) >= 2
    first = json.loads(lines[0])
    last = json.loads(lines[-1])
    assert first["schema_version"] == METRICS_STREAM_SCHEMA_VERSION
    assert last["seq"] > first["seq"]
