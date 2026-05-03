"""Typer :class:`typing.Annotated` aliases shared by OpenRTC CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import click
import typer

from openrtc.observability.stream import DEFAULT_METRICS_JSONL_FILENAME

PANEL_OPENRTC = "OpenRTC"
PANEL_LIVEKIT = "Connection"
PANEL_ADVANCED = "Advanced"

AgentsDirArg = Annotated[
    Path,
    typer.Option(
        "--agents-dir",
        help=(
            "Directory of agent modules to load. Pass the same path as the first "
            "positional argument instead of this flag where supported (e.g. "
            "openrtc list ./agents or openrtc dev ./agents). On start/dev/console "
            "only, an optional second positional sets --metrics-jsonl."
        ),
        exists=False,
        resolve_path=True,
        path_type=Path,
        rich_help_panel=PANEL_OPENRTC,
    ),
]

DefaultSttArg = Annotated[
    str | None,
    typer.Option(
        "--default-stt",
        help=(
            "Default STT provider used when a discovered agent does not "
            "override STT via @agent_config(...)."
        ),
        rich_help_panel=PANEL_OPENRTC,
    ),
]

DefaultLlmArg = Annotated[
    str | None,
    typer.Option(
        "--default-llm",
        help=(
            "Default LLM provider used when a discovered agent does not "
            "override LLM via @agent_config(...)."
        ),
        rich_help_panel=PANEL_OPENRTC,
    ),
]

DefaultTtsArg = Annotated[
    str | None,
    typer.Option(
        "--default-tts",
        help=(
            "Default TTS provider used when a discovered agent does not "
            "override TTS via @agent_config(...)."
        ),
        rich_help_panel=PANEL_OPENRTC,
    ),
]

DefaultGreetingArg = Annotated[
    str | None,
    typer.Option(
        "--default-greeting",
        help=(
            "Default greeting used when a discovered agent does not "
            "override greeting via @agent_config(...)."
        ),
        rich_help_panel=PANEL_ADVANCED,
    ),
]

IsolationArg = Annotated[
    str,
    typer.Option(
        "--isolation",
        case_sensitive=False,
        click_type=click.Choice(["coroutine", "process"], case_sensitive=False),
        help=(
            "Worker isolation mode (default 'coroutine'). 'coroutine' runs "
            "every session as an asyncio.Task in one worker for high density; "
            "'process' is the v0.0.x default of one OS process per session."
        ),
        rich_help_panel=PANEL_OPENRTC,
    ),
]

MaxConcurrentSessionsArg = Annotated[
    int,
    typer.Option(
        "--max-concurrent-sessions",
        min=1,
        help=(
            "Coroutine-mode backpressure threshold (default 50). The worker "
            "reports load >= 1.0 to LiveKit dispatch once this many sessions "
            "are in flight; ignored under --isolation process."
        ),
        rich_help_panel=PANEL_OPENRTC,
    ),
]

DashboardArg = Annotated[
    bool,
    typer.Option(
        "--dashboard",
        help="Show a live Rich dashboard (off by default; use for local debugging).",
        rich_help_panel=PANEL_OPENRTC,
    ),
]

DashboardRefreshArg = Annotated[
    float,
    typer.Option(
        "--dashboard-refresh",
        min=0.25,
        help="Refresh interval in seconds for dashboard / metrics file / JSONL (default 1s).",
        rich_help_panel=PANEL_ADVANCED,
    ),
]

MetricsJsonFileArg = Annotated[
    Path | None,
    typer.Option(
        "--metrics-json-file",
        help="Overwrite a JSON file each tick with the latest snapshot (automation / CI).",
        resolve_path=True,
        path_type=Path,
        rich_help_panel=PANEL_ADVANCED,
    ),
]

MetricsJsonlArg = Annotated[
    Path | None,
    typer.Option(
        "--metrics-jsonl",
        help=(
            "Append JSON Lines for the sidecar TUI (off by default; truncates when "
            "the worker starts). For the default ``openrtc tui`` file, use "
            f"``./{DEFAULT_METRICS_JSONL_FILENAME}`` here. On ``start``/``dev``/``console`` "
            "you may pass that path as the **second** positional after the agents directory "
            "(optional—omit it if you only need to point at the agents folder)."
        ),
        resolve_path=True,
        path_type=Path,
        rich_help_panel=PANEL_OPENRTC,
    ),
]

MetricsJsonlIntervalArg = Annotated[
    float | None,
    typer.Option(
        "--metrics-jsonl-interval",
        min=0.25,
        help=("Seconds between JSONL records (default: same as --dashboard-refresh)."),
        rich_help_panel=PANEL_ADVANCED,
    ),
]

TuiWatchPathArg = Annotated[
    Path,
    typer.Option(
        "--watch",
        show_default=True,
        help=(
            "JSONL file the worker writes with --metrics-jsonl (not your "
            f"--agents-dir). Defaults to ./{DEFAULT_METRICS_JSONL_FILENAME}; pass "
            "the same path to --metrics-jsonl on the worker, or pass PATH as the "
            "first positional argument instead of --watch."
        ),
        resolve_path=True,
        path_type=Path,
        rich_help_panel=PANEL_OPENRTC,
    ),
]

TuiFromStartArg = Annotated[
    bool,
    typer.Option(
        "--from-start",
        help="Read the file from the beginning instead of tailing from EOF.",
        rich_help_panel=PANEL_ADVANCED,
    ),
]

LiveKitUrlArg = Annotated[
    str | None,
    typer.Option(
        "--url",
        help="WebSocket URL of the LiveKit server or Cloud project.",
        envvar="LIVEKIT_URL",
        rich_help_panel=PANEL_LIVEKIT,
    ),
]

LiveKitApiKeyArg = Annotated[
    str | None,
    typer.Option(
        "--api-key",
        help="API key for the LiveKit server or Cloud project.",
        envvar="LIVEKIT_API_KEY",
        rich_help_panel=PANEL_LIVEKIT,
    ),
]

LiveKitApiSecretArg = Annotated[
    str | None,
    typer.Option(
        "--api-secret",
        help="API secret for the LiveKit server or Cloud project.",
        envvar="LIVEKIT_API_SECRET",
        rich_help_panel=PANEL_LIVEKIT,
    ),
]

ConnectRoomArg = Annotated[
    str,
    typer.Option(
        "--room",
        help="Room name to connect to (same as LiveKit Agents [code]connect[/code]).",
        rich_help_panel=PANEL_LIVEKIT,
    ),
]

ConnectParticipantArg = Annotated[
    str | None,
    typer.Option(
        "--participant-identity",
        help="Agent participant identity when connecting to the room.",
        rich_help_panel=PANEL_ADVANCED,
    ),
]

LiveKitLogLevelArg = Annotated[
    str | None,
    typer.Option(
        "--log-level",
        help="Log level (e.g. DEBUG, INFO, WARN, ERROR).",
        envvar="LIVEKIT_LOG_LEVEL",
        case_sensitive=False,
        rich_help_panel=PANEL_ADVANCED,
    ),
]

_LIVEKIT_CLI_CONTEXT_SETTINGS = {
    "allow_extra_args": True,
    "ignore_unknown_options": True,
}
