"""Local Unix-socket IPC for openrtc top (MAH-92); payload is {worker, sessions}."""

from __future__ import annotations

import os
import stat
import tempfile
import uuid
from pathlib import Path

import pytest

from openrtc.observability.introspection import SessionRow, TopSnapshot
from openrtc.observability.introspection_ipc import (
    IntrospectionServer,
    _private_runtime_dir,
    default_socket_path,
    fetch_snapshot,
    snapshot_from_json,
    snapshot_to_json,
)
from openrtc.observability.worker_stats import SystemStats, WorkerStats


def _rows() -> list[SessionRow]:
    return [
        SessionRow("s1", "sales", "acme", 5.0, 120.0, 150.0, 42.0, "active", True),
        SessionRow("s2", "support", None, 3.0, 80.0, 90.0, 10.0, "slow", False),
    ]


def _worker() -> WorkerStats:
    return WorkerStats(
        name="wrk-01",
        uptime_s=100.0,
        active_sessions=2,
        max_sessions=200,
        started=10,
        failed=0,
        saved_bytes=248_000_000_000,
        draining=False,
        system=SystemStats(available=True, cpu_pct=17.6, vcpus=16),
        cpu_history=(1.0, 2.0, 3.0),
    )


def _snapshot() -> TopSnapshot:
    return TopSnapshot(worker=_worker(), sessions=_rows())


def _empty_snapshot() -> TopSnapshot:
    return TopSnapshot(
        worker=WorkerStats(
            name="wrk-01",
            uptime_s=0.0,
            active_sessions=0,
            max_sessions=0,
            started=0,
            failed=0,
            saved_bytes=None,
            draining=False,
            system=SystemStats(),
            cpu_history=(),
        ),
        sessions=[],
    )


def _short_socket() -> Path:
    # Keep the path short (Unix sockets cap at ~104 chars).
    return Path(tempfile.gettempdir()) / f"ortc-{uuid.uuid4().hex[:8]}.sock"


def test_snapshot_json_round_trip() -> None:
    parsed = snapshot_from_json(snapshot_to_json(_snapshot()))
    assert parsed["worker"]["name"] == "wrk-01"
    assert parsed["worker"]["system"]["cpu_pct"] == 17.6  # nested SystemStats
    assert parsed["worker"]["cpu_history"] == [1.0, 2.0, 3.0]
    assert parsed["sessions"][0]["session_id"] == "s1"
    assert parsed["sessions"][0]["pinned"] is True
    assert parsed["sessions"][1]["tenant"] is None


def test_snapshot_from_json_tolerates_garbage() -> None:
    assert snapshot_from_json("not json") == {"worker": None, "sessions": []}
    # A bare list (legacy shape) is not a dict -> empty snapshot, no crash.
    assert snapshot_from_json("[1, 2, 3]") == {"worker": None, "sessions": []}
    # A non-dict worker and non-dict session entries are dropped.
    parsed = snapshot_from_json('{"worker": 5, "sessions": [{"session_id": "s1"}, 2]}')
    assert parsed == {"worker": None, "sessions": [{"session_id": "s1"}]}
    # A non-list sessions field degrades to [].
    assert snapshot_from_json('{"worker": {"name": "x"}, "sessions": 7}') == {
        "worker": {"name": "x"},
        "sessions": [],
    }


def test_default_socket_path_is_private() -> None:
    path = default_socket_path()
    assert path.name == "top.sock"
    parent = path.parent
    assert parent.name == f"openrtc-{os.getuid()}"
    # The per-user socket directory is private (0700).
    assert stat.S_IMODE(parent.stat().st_mode) == 0o700


def test_private_runtime_dir_rejects_symlink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    # A hostile symlink pre-planted where the per-uid dir would be.
    (tmp_path / f"openrtc-{os.getuid()}").symlink_to(tmp_path)
    with pytest.raises(RuntimeError, match="symlinked"):
        _private_runtime_dir()


@pytest.mark.asyncio
async def test_server_client_round_trip() -> None:
    socket_path = _short_socket()
    server = IntrospectionServer(snapshot_provider=_snapshot, socket_path=socket_path)
    await server.start()
    try:
        # The socket is restricted to the owning uid (0600).
        assert stat.S_IMODE(socket_path.stat().st_mode) == 0o600
        snap = await fetch_snapshot(socket_path)
        assert snap["worker"]["name"] == "wrk-01"
        assert [r["session_id"] for r in snap["sessions"]] == ["s1", "s2"]
        assert snap["sessions"][1]["status"] == "slow"
    finally:
        await server.aclose()
    assert not socket_path.exists()


@pytest.mark.asyncio
async def test_server_start_replaces_stale_socket() -> None:
    socket_path = _short_socket()
    socket_path.write_text("stale")  # a stale file at the path
    server = IntrospectionServer(
        snapshot_provider=_empty_snapshot, socket_path=socket_path
    )
    await server.start()
    try:
        assert (await fetch_snapshot(socket_path))["sessions"] == []
    finally:
        await server.aclose()


@pytest.mark.asyncio
async def test_aclose_is_idempotent() -> None:
    socket_path = _short_socket()
    server = IntrospectionServer(snapshot_provider=_snapshot, socket_path=socket_path)
    await server.start()
    await server.aclose()
    await server.aclose()  # no error the second time
