"""Smoke test: 10 live sessions render end-to-end through openrtc top (MAH-92).

Exercises the whole display path without a LiveKit cluster: register 10 sessions
in the introspection registry, serve the snapshot over the real Unix socket, fetch
it as the ``openrtc top`` client would, and render the table. The full live-worker
smoke (10 concurrent calls against a livekit-server container) is covered by the
docker integration suite; this is the CI-runnable guard on the render path.
"""

from __future__ import annotations

import asyncio
import io
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from rich.console import Console

from openrtc.cli.top_cli import build_top_table, run_once
from openrtc.observability.introspection_ipc import fetch_snapshot
from openrtc.observability.introspection_runtime import IntrospectionRuntime


def _info(job_id: str, agent: str, tenant: str | None, started_at: float) -> Any:
    resolved = tenant if tenant is not None else "default"
    return SimpleNamespace(
        job_id=job_id,
        agent_name=agent,
        metadata={"tenant": resolved},
        started_at=started_at,
        tenant=resolved,
    )


def _short_socket() -> Path:
    return Path(tempfile.gettempdir()) / f"ortc-smoke-{uuid.uuid4().hex[:8]}.sock"


@pytest.mark.asyncio
async def test_ten_sessions_render_through_top() -> None:
    socket_path = _short_socket()
    clock = {"t": 1000.0}
    runtime = IntrospectionRuntime(
        socket_path=socket_path,
        rss_reader=lambda: 2048 * 1024 * 1024,  # 2 GB shared across the pool
        time_source=lambda: clock["t"],
    )
    agents = ["sales", "support", "billing"]
    for i in range(10):
        await runtime.registry.on_session_start(
            _info(
                f"job-{i:02d}",
                agents[i % len(agents)],
                tenant=f"tenant-{i % 2}",
                started_at=1000.0 - i,
            ),
            object(),
        )
    runtime._memory.sample_once()  # populate equal-share memory attribution

    loop = asyncio.get_running_loop()
    await runtime.start(loop)
    try:
        rows = (await fetch_snapshot(socket_path))["sessions"]
        assert len(rows) == 10
        # Every session carries identity + attributed memory (2048 MB / 10).
        assert {r["agent_name"] for r in rows} == set(agents)
        assert all(r["mem_mb"] == pytest.approx(204.8) for r in rows)
        assert all(r["tenant"] in {"tenant-0", "tenant-1"} for r in rows)

        # The rendered table shows all 10 rows.
        table = build_top_table(rows, sort_key="mem_mb", status_filter="all")
        assert table.row_count == 10

        # And run_once prints them without error.
        console = Console(file=io.StringIO(), width=200)
        code = await run_once(
            socket_path, sort_key="cpu_pct", status_filter="all", console=console
        )
        assert code == 0
        assert "10 session(s)" in console.file.getvalue()  # type: ignore[attr-defined]
    finally:
        await runtime.aclose()
    assert not socket_path.exists()
