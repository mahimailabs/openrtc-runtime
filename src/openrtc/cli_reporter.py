"""Background runtime metrics reporter (Rich dashboard, JSON file, JSONL stream)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from rich.live import Live
from rich.panel import Panel

from openrtc.cli_dashboard import build_runtime_dashboard, console
from openrtc.core.pool import AgentPool
from openrtc.metrics_stream import JsonlMetricsSink


class RuntimeReporter:
    """Background reporter: Rich dashboard, static JSON file, and/or JSONL stream."""

    def __init__(
        self,
        pool: AgentPool,
        *,
        dashboard: bool,
        refresh_seconds: float,
        json_output_path: Path | None,
        metrics_jsonl_path: Path | None = None,
        metrics_jsonl_interval: float | None = None,
    ) -> None:
        self._pool = pool
        self._dashboard = dashboard
        self._refresh_seconds = max(refresh_seconds, 0.25)
        self._json_output_path = json_output_path
        self._jsonl_interval = (
            max(metrics_jsonl_interval, 0.25)
            if metrics_jsonl_interval is not None
            else self._refresh_seconds
        )
        self._jsonl_sink: JsonlMetricsSink | None = None
        if metrics_jsonl_path is not None:
            self._jsonl_sink = JsonlMetricsSink(metrics_jsonl_path)
            self._jsonl_sink.open()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._needs_periodic_file_or_ui = dashboard or json_output_path is not None

    def start(self) -> None:
        """Start the background reporter when at least one output is enabled."""
        if (
            not self._dashboard
            and self._json_output_path is None
            and self._jsonl_sink is None
        ):
            return
        self._thread = threading.Thread(
            target=self._run,
            name="openrtc-runtime-reporter",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the background reporter and flush one final snapshot."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(self._refresh_seconds * 2, 1.0))
        self._write_json_snapshot()
        self._emit_jsonl()
        if self._jsonl_sink is not None:
            self._jsonl_sink.close()

    def _run(self) -> None:
        now = time.monotonic()
        next_periodic = (
            now + self._refresh_seconds
            if self._needs_periodic_file_or_ui
            else float("inf")
        )
        next_jsonl = now + self._jsonl_interval if self._jsonl_sink else float("inf")

        def schedule_cycle(live: Live | None) -> bool:
            """Wait until the next tick; run JSON/JSONL/dashboard work. Return False to exit."""
            nonlocal next_periodic, next_jsonl
            n = time.monotonic()
            wait_periodic = max(0.0, next_periodic - n)
            wait_jsonl = (
                max(0.0, next_jsonl - n)
                if self._jsonl_sink is not None
                else float("inf")
            )
            timeout = min(wait_periodic, wait_jsonl, 3600.0)
            if self._stop_event.wait(timeout):
                return False
            n = time.monotonic()
            if self._needs_periodic_file_or_ui and n >= next_periodic:
                if live is not None:
                    live.update(self._build_dashboard_renderable())
                self._write_json_snapshot()
                next_periodic += self._refresh_seconds
            if self._jsonl_sink is not None and n >= next_jsonl:
                self._emit_jsonl()
                next_jsonl += self._jsonl_interval
            return True

        if self._dashboard:
            with Live(
                self._build_dashboard_renderable(),
                console=console,
                refresh_per_second=max(int(round(1 / self._refresh_seconds)), 1),
                transient=True,
            ) as live:
                while schedule_cycle(live):
                    pass
                live.update(self._build_dashboard_renderable())
            return

        while schedule_cycle(None):
            pass

    def _build_dashboard_renderable(self) -> Panel:
        snapshot = self._pool.runtime_snapshot()
        return build_runtime_dashboard(snapshot)

    def _write_json_snapshot(self) -> None:
        if self._json_output_path is None:
            return
        payload = self._pool.runtime_snapshot().to_dict()
        self._json_output_path.parent.mkdir(parents=True, exist_ok=True)
        self._json_output_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _emit_jsonl(self) -> None:
        """Write one snapshot line then any queued session events (same tick)."""
        if self._jsonl_sink is None:
            return
        self._jsonl_sink.write_snapshot(self._pool.runtime_snapshot())
        for ev in self._pool.drain_metrics_stream_events():
            self._jsonl_sink.write_event(ev)
