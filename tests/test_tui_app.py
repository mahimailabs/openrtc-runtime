"""Tests for the Textual sidecar ``openrtc tui --watch`` (requires Textual)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from openrtc.observability.metrics import PoolRuntimeSnapshot
from openrtc.observability.stream import snapshot_envelope

pytest.importorskip("textual")


def test_validate_metrics_watch_path_rejects_existing_directory(tmp_path: Path) -> None:
    from openrtc.tui_app import validate_metrics_watch_path

    d = tmp_path / "agents"
    d.mkdir()
    with pytest.raises(ValueError, match="directory"):
        validate_metrics_watch_path(d)


@pytest.mark.asyncio
async def test_metrics_tui_displays_event_line(tmp_path) -> None:
    from openrtc.observability.stream import event_envelope
    from openrtc.tui_app import MetricsTuiApp

    path = tmp_path / "ev.jsonl"
    ev = json.dumps(
        event_envelope(seq=2, payload={"event": "session_started", "agent": "a"}),
        sort_keys=True,
    )
    path.write_text(ev + "\n", encoding="utf-8")

    app = MetricsTuiApp(path, from_start=True)
    async with app.run_test() as pilot:
        app._poll_file()
        await pilot.pause()
        event_w = app.query_one("#event")
        text = str(event_w.renderable)
        assert "session_started" in text
        assert "agent" in text
        assert "a" in text


@pytest.mark.asyncio
async def test_metrics_tui_skips_malformed_line_then_parses_valid(
    tmp_path,
    minimal_pool_runtime_snapshot: PoolRuntimeSnapshot,
) -> None:
    from openrtc.tui_app import MetricsTuiApp

    path = tmp_path / "mix.jsonl"
    snap = minimal_pool_runtime_snapshot
    good = json.dumps(snapshot_envelope(seq=1, snapshot=snap), sort_keys=True)
    path.write_text("not-valid-json\n" + good + "\n", encoding="utf-8")

    app = MetricsTuiApp(path, from_start=True)
    async with app.run_test() as pilot:
        app._poll_file()
        await pilot.pause()
        status = app.query_one("#status")
        assert "seq=1" in str(status.renderable)


@pytest.mark.asyncio
async def test_metrics_tui_displays_snapshot_line(
    tmp_path,
    minimal_pool_runtime_snapshot: PoolRuntimeSnapshot,
) -> None:
    from openrtc.tui_app import MetricsTuiApp

    path = tmp_path / "stream.jsonl"
    snap = minimal_pool_runtime_snapshot
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


@pytest.mark.asyncio
async def test_metrics_tui_reopens_after_writer_truncates_file(
    tmp_path,
    minimal_pool_runtime_snapshot: PoolRuntimeSnapshot,
) -> None:
    from openrtc.tui_app import MetricsTuiApp

    path = tmp_path / "rot.jsonl"
    snap = minimal_pool_runtime_snapshot
    first = json.dumps(snapshot_envelope(seq=1, snapshot=snap), sort_keys=True)
    path.write_text(first + "\n", encoding="utf-8")

    app = MetricsTuiApp(path, from_start=True)
    async with app.run_test() as pilot:
        app._poll_file()
        await pilot.pause()
        assert "seq=1" in str(app.query_one("#status").renderable)

        path.unlink()
        second = json.dumps(snapshot_envelope(seq=2, snapshot=snap), sort_keys=True)
        path.write_text(second + "\n", encoding="utf-8")
        app._poll_file()
        await pilot.pause()
        assert "seq=2" in str(app.query_one("#status").renderable)


@pytest.mark.asyncio
async def test_metrics_tui_creates_watch_file_when_missing(tmp_path: Path) -> None:
    from openrtc.tui_app import MetricsTuiApp

    watch = tmp_path / "nested" / "metrics.jsonl"
    app = MetricsTuiApp(watch, from_start=True)
    async with app.run_test():
        assert watch.is_file()


@pytest.mark.asyncio
async def test_metrics_tui_tail_mode_seeks_to_end_then_reads_appends(
    tmp_path: Path,
    minimal_pool_runtime_snapshot: PoolRuntimeSnapshot,
) -> None:
    from openrtc.tui_app import MetricsTuiApp

    path = tmp_path / "tail.jsonl"
    snap = minimal_pool_runtime_snapshot
    path.write_text(
        json.dumps(snapshot_envelope(seq=1, snapshot=snap), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    app = MetricsTuiApp(path, from_start=False)
    async with app.run_test() as pilot:
        assert app._fh is not None
        assert app._fh.tell() == path.stat().st_size
        more = (
            json.dumps(snapshot_envelope(seq=2, snapshot=snap), sort_keys=True) + "\n"
        )
        path.write_text(path.read_text(encoding="utf-8") + more, encoding="utf-8")
        app._poll_file()
        await pilot.pause()
        assert "seq=2" in str(app.query_one("#status").renderable)


@pytest.mark.asyncio
async def test_metrics_tui_poll_returns_early_when_no_new_bytes(
    tmp_path: Path,
    minimal_pool_runtime_snapshot: PoolRuntimeSnapshot,
) -> None:
    from openrtc.tui_app import MetricsTuiApp

    path = tmp_path / "empty_poll.jsonl"
    snap = minimal_pool_runtime_snapshot
    path.write_text(
        json.dumps(snapshot_envelope(seq=1, snapshot=snap), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    app = MetricsTuiApp(path, from_start=True)
    async with app.run_test() as pilot:
        app._poll_file()
        await pilot.pause()
        app._poll_file()
        await pilot.pause()
        assert "seq=1" in str(app.query_one("#status").renderable)


@pytest.mark.asyncio
async def test_metrics_tui_sync_opens_when_handle_cleared(
    tmp_path: Path,
    minimal_pool_runtime_snapshot: PoolRuntimeSnapshot,
) -> None:
    from openrtc.tui_app import MetricsTuiApp

    path = tmp_path / "reopen.jsonl"
    snap = minimal_pool_runtime_snapshot
    path.write_text(
        json.dumps(snapshot_envelope(seq=1, snapshot=snap), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    app = MetricsTuiApp(path, from_start=True)
    async with app.run_test() as pilot:
        app._fh.close()
        app._fh = None
        app._poll_file()
        await pilot.pause()
        assert app._fh is not None
        assert "seq=1" in str(app.query_one("#status").renderable)


@pytest.mark.asyncio
async def test_metrics_tui_refresh_event_line_noop_without_event(
    tmp_path: Path,
) -> None:
    from openrtc.tui_app import MetricsTuiApp

    path = tmp_path / "no_ev.jsonl"
    path.touch()
    app = MetricsTuiApp(path, from_start=True)
    async with app.run_test() as pilot:
        app._last_event = None
        app._refresh_event_line()
        await pilot.pause()


@pytest.mark.asyncio
async def test_metrics_tui_refresh_view_noop_when_latest_missing(
    tmp_path: Path,
) -> None:
    from openrtc.tui_app import MetricsTuiApp

    path = tmp_path / "no_latest.jsonl"
    path.touch()
    app = MetricsTuiApp(path, from_start=True)
    async with app.run_test() as pilot:
        app._latest = None
        app._refresh_view()
        await pilot.pause()


@pytest.mark.asyncio
async def test_metrics_tui_sync_ignores_stat_oserror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import openrtc.tui_app as tu
    from openrtc.tui_app import MetricsTuiApp

    path = tmp_path / "stat_err.jsonl"
    path.touch()
    real_stat = os.stat
    armed = {"on": False}

    target = os.fspath(path)

    def stat_fn(
        p: str | os.PathLike[str],
        *args: object,
        **kwargs: object,
    ) -> os.stat_result:
        if armed["on"] and os.fspath(p) == target:
            raise OSError("stat failed")
        return real_stat(p, *args, **kwargs)

    monkeypatch.setattr(tu.os, "stat", stat_fn)
    app = MetricsTuiApp(path, from_start=True)
    async with app.run_test() as pilot:
        armed["on"] = True
        app._poll_file()
        await pilot.pause()


@pytest.mark.asyncio
async def test_metrics_tui_refresh_view_skips_bad_payload_shapes(
    tmp_path: Path,
    minimal_pool_runtime_snapshot: PoolRuntimeSnapshot,
) -> None:
    from openrtc.tui_app import MetricsTuiApp

    path = tmp_path / "bad_payload.jsonl"
    path.touch()
    app = MetricsTuiApp(path, from_start=True)
    async with app.run_test() as pilot:
        app._latest = {"payload": "not-a-dict"}
        app._refresh_view()
        app._latest = {
            "seq": 9,
            "wall_time_unix": 1.0,
            "payload": {
                "registered_agents": 1,
                "active_sessions": 0,
                "uptime_seconds": 1.0,
                "sessions_by_agent": [1, 2],
                "last_routed_agent": None,
                "last_error": None,
                "total_sessions_started": 0,
                "total_session_failures": 0,
            },
        }
        app._refresh_view()
        await pilot.pause()
        text = str(app.query_one("#agents").renderable)
        assert "invalid payload" in text


@pytest.mark.asyncio
async def test_metrics_tui_wall_time_invalid_falls_back_to_na(
    tmp_path: Path,
    minimal_pool_runtime_snapshot: PoolRuntimeSnapshot,
) -> None:
    from openrtc.tui_app import MetricsTuiApp

    path = tmp_path / "wall.jsonl"
    path.touch()
    app = MetricsTuiApp(path, from_start=True)
    snap = minimal_pool_runtime_snapshot
    async with app.run_test() as pilot:
        app._latest = {
            "seq": 3,
            "wall_time_unix": "not-numeric",
            "payload": snap.to_dict(),
        }
        app._refresh_view()
        await pilot.pause()
        assert "wall=n/a" in str(app.query_one("#status").renderable)


@pytest.mark.asyncio
async def test_metrics_tui_action_quit_exits(tmp_path: Path) -> None:
    from openrtc.tui_app import MetricsTuiApp

    path = tmp_path / "quit.jsonl"
    path.touch()
    app = MetricsTuiApp(path, from_start=True)
    async with app.run_test() as pilot:
        await app.action_quit()
        await pilot.pause()


def test_run_metrics_tui_calls_app_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import openrtc.tui_app as tu

    ran: list[object] = []

    def fake_run(self: object) -> None:
        ran.append(self)

    monkeypatch.setattr(tu.MetricsTuiApp, "run", fake_run)
    p = tmp_path / "x.jsonl"
    p.touch()
    tu.run_metrics_tui(p, from_start=True)
    assert len(ran) == 1
    assert getattr(ran[0], "_path", None) == p.resolve()


@pytest.mark.asyncio
async def test_metrics_tui_poll_returns_when_open_does_not_restore_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openrtc.tui_app import MetricsTuiApp

    path = tmp_path / "noop_open.jsonl"
    path.touch()
    app = MetricsTuiApp(path, from_start=True)
    async with app.run_test():

        def noop_open() -> None:
            app._fh = None
            app._buf = ""

        monkeypatch.setattr(app, "_open_metrics_file", noop_open)
        app._fh = None
        app._poll_file()


@pytest.mark.asyncio
async def test_metrics_tui_on_unmount_closes_file_handle(tmp_path: Path) -> None:
    from openrtc.tui_app import MetricsTuiApp

    path = tmp_path / "um.jsonl"
    path.touch()
    app = MetricsTuiApp(path, from_start=True)
    async with app.run_test():
        assert app._fh is not None
    assert app._fh is None
