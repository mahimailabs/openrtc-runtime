"""Textual sidecar UI for tailing :mod:`openrtc.metrics_stream` JSONL output."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static

from openrtc.metrics_stream import parse_metrics_jsonl_line


class MetricsTuiApp(App[None]):
    """Tail ``--metrics-jsonl`` and show live pool metrics."""

    TITLE = "OpenRTC metrics"
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, watch_path: Path, *, from_start: bool = False) -> None:
        super().__init__()
        self._path = watch_path.resolve()
        self._from_start = from_start
        self._fh: Any = None
        self._buf = ""
        self._latest: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(
            "Waiting for JSONL metrics (run the worker with --metrics-jsonl)…",
            id="status",
        )
        yield Static("", id="agents")
        yield Static("", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()
        self._fh = self._path.open("r", encoding="utf-8")
        if not self._from_start:
            self._fh.seek(0, 2)
        self.set_interval(0.25, self._poll_file)

    def on_unmount(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def _poll_file(self) -> None:
        if self._fh is None:
            return
        chunk = self._fh.read()
        if not chunk:
            return
        self._buf += chunk
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            rec = parse_metrics_jsonl_line(line)
            if rec is not None:
                self._latest = rec
                self._refresh_view()

    def _refresh_view(self) -> None:
        if self._latest is None:
            return
        payload = self._latest.get("payload")
        if not isinstance(payload, dict):
            return
        seq = self._latest.get("seq")
        wall = self._latest.get("wall_time_unix")
        status = self.query_one("#status", Static)
        status.update(
            f"seq={seq}  wall={float(wall):.3f}  registered={payload.get('registered_agents')} "
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

    def action_quit(self) -> None:
        self.exit()


def run_metrics_tui(watch_path: Path, *, from_start: bool = False) -> None:
    """Run the Textual app until the user quits."""
    MetricsTuiApp(watch_path, from_start=from_start).run()
