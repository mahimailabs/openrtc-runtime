"""Textual sidecar UI for tailing :mod:`openrtc.metrics_stream` JSONL output."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TextIO

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static

from openrtc.metrics_stream import KIND_EVENT, KIND_SNAPSHOT, parse_metrics_jsonl_line


def validate_metrics_watch_path(path: Path) -> None:
    """Ensure *path* can be used as the metrics JSONL file (not a directory)."""
    resolved = path.resolve()
    if resolved.exists() and resolved.is_dir():
        raise ValueError(
            "'--watch' must be a JSONL file path (the same path you pass to "
            "'--metrics-jsonl' on the OpenRTC worker). This value is a directory "
            "— for example, use a file such as ./metrics.jsonl, not your agents "
            f"folder. Got: {resolved}"
        )


class MetricsTuiApp(App[None]):
    """Tail ``--metrics-jsonl`` and show live pool metrics."""

    TITLE = "OpenRTC metrics"
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, watch_path: Path, *, from_start: bool = False) -> None:
        super().__init__()
        self._path = watch_path.resolve()
        validate_metrics_watch_path(self._path)
        self._from_start = from_start
        self._fh: TextIO | None = None
        self._buf = ""
        self._latest: dict[str, Any] | None = None
        self._last_event: dict[str, Any] | None = None
        self._path_st_ino: int | None = None
        self._path_st_dev: int | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(
            "Waiting for JSONL metrics (run the worker with --metrics-jsonl)…",
            id="status",
        )
        yield Static("", id="event")
        yield Static("", id="agents")
        yield Static("", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()
        self._open_metrics_file()
        self.set_interval(0.25, self._poll_file)

    def on_unmount(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def _capture_path_identity(self, st: os.stat_result) -> None:
        self._path_st_ino = st.st_ino
        self._path_st_dev = st.st_dev

    def _open_metrics_file(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        self._buf = ""
        self._fh = self._path.open("r", encoding="utf-8")
        if self._from_start:
            self._fh.seek(0)
        else:
            self._fh.seek(0, 2)
        st = os.stat(self._path)
        self._capture_path_identity(st)

    def _sync_metrics_file_handle(self) -> None:
        """Reopen the reader after truncation or path replacement so new bytes are visible."""
        try:
            st = os.stat(self._path)
        except OSError:
            return
        if self._fh is None:
            self._open_metrics_file()
            return
        pos = self._fh.tell()
        identity_ok = (
            self._path_st_ino is not None
            and self._path_st_dev is not None
            and st.st_ino == self._path_st_ino
            and st.st_dev == self._path_st_dev
        )
        if not identity_ok or st.st_size < pos:
            self._open_metrics_file()

    def _poll_file(self) -> None:
        self._sync_metrics_file_handle()
        if self._fh is None:
            return
        chunk = self._fh.read()
        if not chunk:
            return
        self._buf += chunk
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            rec = parse_metrics_jsonl_line(line)
            if rec is None:
                continue
            if rec.get("kind") == KIND_SNAPSHOT:
                self._latest = rec
                self._refresh_view()
            elif rec.get("kind") == KIND_EVENT:
                pl = rec.get("payload")
                if isinstance(pl, dict):
                    self._last_event = pl
                    self._refresh_event_line()

    def _refresh_event_line(self) -> None:
        if self._last_event is None:
            return
        ev = self.query_one("#event", Static)
        ev.update(
            "[bold]Last event[/bold] "
            + " ".join(f"{k}={v!r}" for k, v in sorted(self._last_event.items()))
        )

    def _refresh_view(self) -> None:
        if self._latest is None:
            return
        payload = self._latest.get("payload")
        if not isinstance(payload, dict):
            return
        seq = self._latest.get("seq")
        wall = self._latest.get("wall_time_unix")
        wall_s = "n/a"
        if wall is not None:
            try:
                wall_s = f"{float(wall):.3f}"
            except (TypeError, ValueError):
                wall_s = "n/a"
        status = self.query_one("#status", Static)
        status.update(
            f"seq={seq}  wall={wall_s}  registered={payload.get('registered_agents')} "
            f"active={payload.get('active_sessions')}  "
            f"uptime={float(payload.get('uptime_seconds', 0)):.1f}s"
        )
        sba = payload.get("sessions_by_agent") or {}
        if isinstance(sba, dict):
            lines = [f"  {name}: {c}" for name, c in sorted(sba.items())]
            body = "\n".join(lines) if lines else "  (no per-agent sessions yet)"
        else:
            body = "  (invalid payload)"
        agents = self.query_one("#agents", Static)
        agents.update("[bold]Sessions by agent[/bold]\n" + body)
        route = payload.get("last_routed_agent")
        err = payload.get("last_error")
        detail = self.query_one("#detail", Static)
        detail.update(
            f"[bold]Last route[/bold] {route or '—'}\n"
            f"[bold]Last error[/bold] {err or '—'}\n"
            f"[bold]Totals[/bold] started={payload.get('total_sessions_started')} "
            f"failures={payload.get('total_session_failures')}"
        )

    async def action_quit(self) -> None:
        self.exit()


def run_metrics_tui(watch_path: Path, *, from_start: bool = False) -> None:
    """Run the Textual app until the user quits."""
    MetricsTuiApp(watch_path, from_start=from_start).run()
