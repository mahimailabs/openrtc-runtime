"""Typer arg aliases, option helpers, and parameter bundles for the OpenRTC CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import click
import typer

from openrtc.observability.jsonl_sink import DEFAULT_METRICS_JSONL_FILENAME
from openrtc.utils.types import ProviderValue

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
        envvar="OPENRTC_ISOLATION",
        help=(
            "Worker isolation mode (default 'coroutine'). 'coroutine' runs "
            "every session as an asyncio.Task in one worker for high density; "
            "'process' is the v0.0.x default of one OS process per session. "
            "Precedence: CLI flag > OPENRTC_ISOLATION > library default."
        ),
        rich_help_panel=PANEL_OPENRTC,
    ),
]

MaxConcurrentSessionsArg = Annotated[
    int,
    typer.Option(
        "--max-concurrent-sessions",
        min=1,
        envvar="OPENRTC_MAX_CONCURRENT_SESSIONS",
        help=(
            "Coroutine-mode backpressure threshold (default 50). The worker "
            "reports load >= 1.0 to LiveKit dispatch once this many sessions "
            "are in flight; ignored under --isolation process. "
            "Precedence: CLI flag > OPENRTC_MAX_CONCURRENT_SESSIONS > library default."
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
            "Append JSON Lines for external tailing or tooling (off by default; "
            "truncates when the worker starts). Point it at "
            f"``./{DEFAULT_METRICS_JSONL_FILENAME}`` to tail or script the stream. "
            "On ``start``/``dev``/``console`` you may pass that path as the "
            "**second** positional after the agents directory (optional: omit it if "
            "you only need to point at the agents folder)."
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


# ---------------------------------------------------------------------------
# Parameter bundles
# ---------------------------------------------------------------------------


def agent_provider_kwargs(
    default_stt: ProviderValue | None,
    default_llm: ProviderValue | None,
    default_tts: ProviderValue | None,
    default_greeting: str | None,
) -> dict[str, Any]:
    """Keyword arguments for :class:`openrtc.core.pool.AgentPool` provider defaults."""
    return {
        "default_stt": default_stt,
        "default_llm": default_llm,
        "default_tts": default_tts,
        "default_greeting": default_greeting,
    }


def agent_pool_runtime_kwargs(
    *,
    isolation: str = "coroutine",
    max_concurrent_sessions: int = 50,
) -> dict[str, Any]:
    """Keyword arguments for the runtime knobs on :class:`AgentPool`."""
    return {
        "isolation": isolation,
        "max_concurrent_sessions": max_concurrent_sessions,
    }


@dataclass(frozen=True)
class SharedLiveKitWorkerOptions:
    """Options shared by ``start`` / ``dev`` / ``console`` / ``connect`` handoff paths.

    Typer still lists each flag on every command so ``--help`` stays accurate; this
    dataclass deduplicates the handoff to :mod:`openrtc.cli.livekit_cli`.
    """

    agents_dir: Path
    default_stt: ProviderValue | None
    default_llm: ProviderValue | None
    default_tts: ProviderValue | None
    default_greeting: str | None
    url: str | None
    api_key: str | None
    api_secret: str | None
    log_level: str | None
    dashboard: bool
    dashboard_refresh: float
    metrics_json_file: Path | None
    metrics_jsonl: Path | None
    metrics_jsonl_interval: float | None
    isolation: str = "coroutine"
    max_concurrent_sessions: int = 50

    def agent_pool_kwargs(self) -> dict[str, Any]:
        return {
            **agent_provider_kwargs(
                self.default_stt,
                self.default_llm,
                self.default_tts,
                self.default_greeting,
            ),
            **agent_pool_runtime_kwargs(
                isolation=self.isolation,
                max_concurrent_sessions=self.max_concurrent_sessions,
            ),
        }

    @classmethod
    def from_cli(
        cls,
        agents_dir: Path,
        *,
        default_stt: ProviderValue | None = None,
        default_llm: ProviderValue | None = None,
        default_tts: ProviderValue | None = None,
        default_greeting: str | None = None,
        url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        log_level: str | None = None,
        dashboard: bool = False,
        dashboard_refresh: float = 1.0,
        metrics_json_file: Path | None = None,
        metrics_jsonl: Path | None = None,
        metrics_jsonl_interval: float | None = None,
        isolation: str = "coroutine",
        max_concurrent_sessions: int = 50,
    ) -> SharedLiveKitWorkerOptions:
        return cls(
            agents_dir=agents_dir,
            default_stt=default_stt,
            default_llm=default_llm,
            default_tts=default_tts,
            default_greeting=default_greeting,
            url=url,
            api_key=api_key,
            api_secret=api_secret,
            log_level=log_level,
            dashboard=dashboard,
            dashboard_refresh=dashboard_refresh,
            metrics_json_file=metrics_json_file,
            metrics_jsonl=metrics_jsonl,
            metrics_jsonl_interval=metrics_jsonl_interval,
            isolation=isolation,
            max_concurrent_sessions=max_concurrent_sessions,
        )

    @classmethod
    def for_download_files(
        cls,
        agents_dir: Path,
        *,
        url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        log_level: str | None = None,
    ) -> SharedLiveKitWorkerOptions:
        return cls(
            agents_dir=agents_dir,
            default_stt=None,
            default_llm=None,
            default_tts=None,
            default_greeting=None,
            url=url,
            api_key=api_key,
            api_secret=api_secret,
            log_level=log_level,
            dashboard=False,
            dashboard_refresh=1.0,
            metrics_json_file=None,
            metrics_jsonl=None,
            metrics_jsonl_interval=None,
        )
