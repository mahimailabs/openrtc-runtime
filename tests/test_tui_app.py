from __future__ import annotations

import json

import pytest

from openrtc.metrics_stream import snapshot_envelope
from openrtc.resources import (
    PoolRuntimeSnapshot,
    ProcessResidentSetInfo,
    SavingsEstimate,
)

pytest.importorskip("textual")


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


@pytest.mark.asyncio
async def test_metrics_tui_displays_snapshot_line(tmp_path) -> None:
    from openrtc.tui_app import MetricsTuiApp

    path = tmp_path / "stream.jsonl"
    snap = _minimal_snapshot()
    line = json.dumps(snapshot_envelope(seq=1, snapshot=snap), sort_keys=True)
    path.write_text(line + "\n", encoding="utf-8")

    app = MetricsTuiApp(path, from_start=True)
    async with app.run_test() as pilot:
        app._poll_file()
        await pilot.pause()
        status = app.query_one("#status")
        text = str(status.renderable)
        assert "seq=1" in text
        assert "registered=1" in text
