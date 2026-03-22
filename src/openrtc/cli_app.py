from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from openrtc.pool import AgentConfig, AgentPool
from openrtc.resources import (
    PoolRuntimeSnapshot,
    agent_disk_footprints,
    estimate_shared_worker_savings,
    file_size_bytes,
    format_byte_size,
    get_process_resident_set_info,
)

logger = logging.getLogger("openrtc")

PANEL_OPENRTC = "OpenRTC"
PANEL_LIVEKIT = "Connection"

app = typer.Typer(
    name="openrtc",
    help=(
        "Run multiple LiveKit voice agents from one shared worker. Subcommands mirror "
        "the LiveKit Agents CLI ([code]dev[/code], [code]start[/code], [code]console[/code], "
        "[code]connect[/code], [code]download-files[/code]) as in "
        "[code]python agent.py <command>[/code]. "
        "Add [code]--agents-dir[/code] so OpenRTC discovers and registers agents; use "
        "[code]--url[/code] / [code]--api-key[/code] / [code]--api-secret[/code] or "
        "the usual [code]LIVEKIT_*[/code] environment variables for the server."
    ),
    pretty_exceptions_show_locals=False,
    rich_markup_mode="rich",
    no_args_is_help=True,
)

console = Console()


class RuntimeReporter:
    """Background reporter that renders a Rich dashboard and/or JSON snapshots."""

    def __init__(
        self,
        pool: AgentPool,
        *,
        dashboard: bool,
        refresh_seconds: float,
        json_output_path: Path | None,
    ) -> None:
        self._pool = pool
        self._dashboard = dashboard
        self._refresh_seconds = max(refresh_seconds, 0.25)
        self._json_output_path = json_output_path
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background reporter when at least one output is enabled."""
        if not self._dashboard and self._json_output_path is None:
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

    def _run(self) -> None:
        if self._dashboard:
            with Live(
                self._build_dashboard_renderable(),
                console=console,
                refresh_per_second=max(int(round(1 / self._refresh_seconds)), 1),
                transient=True,
            ) as live:
                while not self._stop_event.wait(self._refresh_seconds):
                    live.update(self._build_dashboard_renderable())
                    self._write_json_snapshot()
                live.update(self._build_dashboard_renderable())
            return

        while not self._stop_event.wait(self._refresh_seconds):
            self._write_json_snapshot()

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


def _format_percent(saved_bytes: int | None, baseline_bytes: int | None) -> str:
    if saved_bytes is None or baseline_bytes in (None, 0):
        return "—"
    return f"{(saved_bytes / baseline_bytes) * 100:.0f}%"


def _memory_style(num_bytes: int | None) -> str:
    if num_bytes is None:
        return "white"
    mib = num_bytes / (1024 * 1024)
    if mib < 512:
        return "green"
    if mib < 1024:
        return "yellow"
    return "red"


def _build_sessions_table(snapshot: PoolRuntimeSnapshot) -> Table:
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Agent", style="cyan")
    table.add_column("Active sessions", justify="right")

    if snapshot.sessions_by_agent:
        for agent_name, count in sorted(
            snapshot.sessions_by_agent.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            table.add_row(agent_name, str(count))
    else:
        table.add_row("—", "0")
    return table


def build_runtime_dashboard(snapshot: PoolRuntimeSnapshot) -> Panel:
    """Build a Rich dashboard from a runtime snapshot."""
    metrics = Table.grid(expand=True)
    metrics.add_column(ratio=2)
    metrics.add_column(ratio=1)

    rss_bytes = snapshot.resident_set.bytes_value
    savings = snapshot.savings_estimate
    progress_total = max(snapshot.registered_agents, 1)
    left = Table.grid(padding=(0, 1))
    left.add_column(style="bold cyan")
    left.add_column()
    left.add_row(
        "Worker RSS",
        Text(
            format_byte_size(rss_bytes or 0)
            if rss_bytes is not None
            else "Unavailable",
            style=_memory_style(rss_bytes),
        ),
    )
    left.add_row("Metric", snapshot.resident_set.metric)
    left.add_row("Uptime", f"{snapshot.uptime_seconds:.1f}s")
    left.add_row("Registered", str(snapshot.registered_agents))
    left.add_row("Active", str(snapshot.active_sessions))
    left.add_row("Total handled", str(snapshot.total_sessions_started))
    left.add_row("Failures", str(snapshot.total_session_failures))
    left.add_row("Last route", snapshot.last_routed_agent or "—")

    right = Table.grid(padding=(0, 1))
    right.add_column(style="bold magenta")
    right.add_column()
    right.add_row(
        "Shared worker",
        format_byte_size(savings.shared_worker_bytes or 0)
        if savings.shared_worker_bytes is not None
        else "Unavailable",
    )
    right.add_row(
        "10x style estimate"
        if snapshot.registered_agents == 10
        else "Separate workers",
        format_byte_size(savings.estimated_separate_workers_bytes or 0)
        if savings.estimated_separate_workers_bytes is not None
        else "Unavailable",
    )
    right.add_row(
        "Estimated saved",
        format_byte_size(savings.estimated_saved_bytes or 0)
        if savings.estimated_saved_bytes is not None
        else "Unavailable",
    )
    right.add_row(
        "Saved vs separate",
        _format_percent(
            savings.estimated_saved_bytes,
            savings.estimated_separate_workers_bytes,
        ),
    )

    metrics.add_row(left, right)

    progress = Table.grid(expand=True)
    progress.add_column(ratio=3)
    progress.add_column(ratio=2)
    progress.add_row(
        ProgressBar(
            total=progress_total,
            completed=min(snapshot.active_sessions, progress_total),
            complete_style="green",
            finished_style="green",
            pulse_style="cyan",
        ),
        _build_sessions_table(snapshot),
    )

    footer = Text(
        f"Memory metric: {snapshot.resident_set.description}",
        style="dim",
    )
    if snapshot.last_error:
        footer.append(f"\nLast error: {snapshot.last_error}", style="bold red")

    body = Table.grid(expand=True)
    body.add_row(metrics)
    body.add_row("")
    body.add_row(progress)
    body.add_row("")
    body.add_row(footer)

    return Panel(
        body,
        title="[bold blue]OpenRTC runtime dashboard[/bold blue]",
        subtitle="shared worker visibility",
        border_style="bright_blue",
    )


def _pool_kwargs(
    default_stt: str | None,
    default_llm: str | None,
    default_tts: str | None,
    default_greeting: str | None,
) -> dict[str, Any]:
    return {
        "default_stt": default_stt,
        "default_llm": default_llm,
        "default_tts": default_tts,
        "default_greeting": default_greeting,
    }


_OPENRTC_ONLY_FLAGS_WITH_VALUE: frozenset[str] = frozenset(
    {
        "--agents-dir",
        "--default-stt",
        "--default-llm",
        "--default-tts",
        "--default-greeting",
        "--dashboard-refresh",
        "--metrics-json-file",
    }
)
_OPENRTC_ONLY_BOOL_FLAGS: frozenset[str] = frozenset({"--dashboard"})


def _strip_openrtc_only_flags_for_livekit(argv_tail: list[str]) -> list[str]:
    """Drop OpenRTC-only CLI flags; LiveKit's ``run_app`` parses ``sys.argv`` itself.

    ``openrtc start`` / ``openrtc dev`` are implemented with Typer, then delegate to
    :func:`livekit.agents.cli.run_app`, which builds a separate Typer application
    that does not recognize OpenRTC options such as ``--agents-dir``. Those must
    be removed before the handoff while preserving any forwarded LiveKit flags
    (e.g. ``--reload``, ``--url``) when we add pass-through options later.
    """
    out: list[str] = []
    i = 0
    while i < len(argv_tail):
        arg = argv_tail[i]
        if arg == "--":
            out.extend(argv_tail[i:])
            break
        if "=" in arg:
            name = arg.split("=", 1)[0]
            if (
                name in _OPENRTC_ONLY_FLAGS_WITH_VALUE
                or name in _OPENRTC_ONLY_BOOL_FLAGS
            ):
                i += 1
                continue
            out.append(arg)
            i += 1
            continue
        if arg in _OPENRTC_ONLY_BOOL_FLAGS:
            i += 1
            continue
        if arg in _OPENRTC_ONLY_FLAGS_WITH_VALUE:
            i += 1
            if i < len(argv_tail) and not argv_tail[i].startswith("--"):
                i += 1
            continue
        out.append(arg)
        i += 1
    return out


def _livekit_sys_argv(subcommand: str) -> None:
    """Set ``sys.argv`` for ``livekit.agents.cli.run_app``.

    OpenRTC-specific options are stripped because the LiveKit CLI re-parses
    ``sys.argv`` and only accepts its own flags per subcommand.

    When the process was not started as ``openrtc <subcommand> ...`` (e.g. tests
    that patch ``sys.argv``), only ``[argv0, subcommand]`` is used.
    """
    prog = sys.argv[0]
    if len(sys.argv) >= 2 and sys.argv[1] == subcommand:
        rest = _strip_openrtc_only_flags_for_livekit(list(sys.argv[2:]))
        sys.argv = [prog, subcommand, *rest]
    else:
        sys.argv = [prog, subcommand]


def _apply_optional_livekit_connection_env(
    *,
    url: str | None,
    api_key: str | None,
    api_secret: str | None,
) -> None:
    """Mirror LiveKit CLI env vars when the user passes connection flags on OpenRTC."""
    if url is not None:
        os.environ["LIVEKIT_URL"] = url
    if api_key is not None:
        os.environ["LIVEKIT_API_KEY"] = api_key
    if api_secret is not None:
        os.environ["LIVEKIT_API_SECRET"] = api_secret


def _apply_optional_livekit_log_level(log_level: str | None) -> None:
    if log_level is not None:
        os.environ["LIVEKIT_LOG_LEVEL"] = log_level


def _delegate_discovered_pool_to_livekit(
    *,
    agents_dir: Path,
    subcommand: str,
    default_stt: str | None,
    default_llm: str | None,
    default_tts: str | None,
    default_greeting: str | None,
    dashboard: bool,
    dashboard_refresh: float,
    metrics_json_file: Path | None,
    url: str | None,
    api_key: str | None,
    api_secret: str | None,
    log_level: str | None,
) -> None:
    """Discover agents, optionally set connection env, then run a LiveKit CLI subcommand."""
    pool = AgentPool(
        **_pool_kwargs(default_stt, default_llm, default_tts, default_greeting)
    )
    _discover_or_exit(agents_dir, pool)
    _apply_optional_livekit_connection_env(
        url=url, api_key=api_key, api_secret=api_secret
    )
    _apply_optional_livekit_log_level(log_level)
    _livekit_sys_argv(subcommand)
    _run_pool_with_reporting(
        pool,
        dashboard=dashboard,
        dashboard_refresh=dashboard_refresh,
        metrics_json_file=metrics_json_file,
    )


def _run_connect_handoff(
    *,
    agents_dir: Path,
    default_stt: str | None,
    default_llm: str | None,
    default_tts: str | None,
    default_greeting: str | None,
    room: str,
    participant_identity: str | None,
    log_level: str | None,
    url: str | None,
    api_key: str | None,
    api_secret: str | None,
    dashboard: bool,
    dashboard_refresh: float,
    metrics_json_file: Path | None,
) -> None:
    """Hand off to LiveKit ``connect`` with explicit argv (Typer consumes flags first)."""
    pool = AgentPool(
        **_pool_kwargs(default_stt, default_llm, default_tts, default_greeting)
    )
    _discover_or_exit(agents_dir, pool)
    _apply_optional_livekit_connection_env(
        url=url, api_key=api_key, api_secret=api_secret
    )
    prog = sys.argv[0]
    tail: list[str] = ["connect", "--room", room]
    if participant_identity is not None:
        tail.extend(["--participant-identity", participant_identity])
    if log_level is not None:
        tail.extend(["--log-level", log_level])
    sys.argv = [prog, *tail]
    _run_pool_with_reporting(
        pool,
        dashboard=dashboard,
        dashboard_refresh=dashboard_refresh,
        metrics_json_file=metrics_json_file,
    )


def _discover_or_exit(agents_dir: Path, pool: AgentPool) -> list[AgentConfig]:
    try:
        discovered = pool.discover(agents_dir)
    except FileNotFoundError:
        logger.error(
            "Agents directory does not exist: %s. Pass a valid --agents-dir path.",
            agents_dir,
        )
        raise typer.Exit(code=1) from None
    except NotADirectoryError:
        logger.error(
            "--agents-dir is not a directory: %s. Pass a directory of agent modules.",
            agents_dir,
        )
        raise typer.Exit(code=1) from None
    except PermissionError as exc:
        logger.error(
            "Permission denied reading agents directory %s: %s",
            agents_dir,
            exc,
        )
        raise typer.Exit(code=1) from exc
    if not discovered:
        logger.error("No agent modules were discovered in %s.", agents_dir)
        raise typer.Exit(code=1)
    return discovered


def _truncate_cell(text: str, max_len: int = 36) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


AgentsDirArg = Annotated[
    Path,
    typer.Option(
        "--agents-dir",
        help="Directory containing discoverable agent modules.",
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
        rich_help_panel=PANEL_OPENRTC,
    ),
]

DashboardArg = Annotated[
    bool,
    typer.Option(
        "--dashboard",
        help="Show a live Rich dashboard with worker memory and active sessions.",
        rich_help_panel=PANEL_OPENRTC,
    ),
]

DashboardRefreshArg = Annotated[
    float,
    typer.Option(
        "--dashboard-refresh",
        min=0.25,
        help="Refresh interval in seconds for the runtime dashboard and metrics file.",
        rich_help_panel=PANEL_OPENRTC,
    ),
]

MetricsJsonFileArg = Annotated[
    Path | None,
    typer.Option(
        "--metrics-json-file",
        help="Write live runtime metrics snapshots to this JSON file for automation.",
        resolve_path=True,
        path_type=Path,
        rich_help_panel=PANEL_OPENRTC,
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
        rich_help_panel=PANEL_LIVEKIT,
    ),
]

LiveKitLogLevelArg = Annotated[
    str | None,
    typer.Option(
        "--log-level",
        help="Log level (e.g. DEBUG, INFO, WARN, ERROR).",
        envvar="LIVEKIT_LOG_LEVEL",
        case_sensitive=False,
        rich_help_panel=PANEL_LIVEKIT,
    ),
]


@app.command("list")
def list_command(
    agents_dir: AgentsDirArg,
    resources: Annotated[
        bool,
        typer.Option(
            "--resources",
            help=(
                "Include footprint fields (with --json and --plain) or extra "
                "columns/summary (default Rich table). "
                "Memory line is OS-specific (Linux: current VmRSS; macOS: peak "
                "ru_maxrss, not live RSS—see JSON description)."
            ),
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit machine-readable JSON to stdout (stable for scripts).",
        ),
    ] = False,
    plain: Annotated[
        bool,
        typer.Option(
            "--plain",
            help=(
                "Line-oriented plain text without ANSI or table borders "
                "(stable for scripts and CI)."
            ),
        ),
    ] = False,
    default_stt: DefaultSttArg = None,
    default_llm: DefaultLlmArg = None,
    default_tts: DefaultTtsArg = None,
    default_greeting: DefaultGreetingArg = None,
) -> None:
    """List discovered agents and optional resource estimates."""
    if plain and json_output:
        raise typer.BadParameter("Use only one of --plain and --json.")

    pool = AgentPool(
        **_pool_kwargs(default_stt, default_llm, default_tts, default_greeting)
    )
    discovered = _discover_or_exit(agents_dir, pool)

    if json_output:
        payload = _build_list_json_payload(discovered, include_resources=resources)
        print(json.dumps(payload, indent=2, default=str))
        return

    if plain:
        _print_list_plain(discovered, resources=resources)
        return

    _print_list_rich_table(discovered, resources=resources)
    if resources:
        _print_resource_summary_rich(discovered)


def _print_list_rich_table(
    discovered: list[AgentConfig],
    *,
    resources: bool,
) -> None:
    table = Table(
        title="Discovered agents",
        show_header=True,
        header_style="bold",
        show_lines=False,
    )
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Class", style="green")
    table.add_column("STT")
    table.add_column("LLM")
    table.add_column("TTS")
    table.add_column("Greeting")
    if resources:
        table.add_column("Source size", style="dim")

    for config in discovered:
        greeting = "" if config.greeting is None else config.greeting
        row = [
            config.name,
            config.agent_cls.__name__,
            _truncate_cell(repr(config.stt)),
            _truncate_cell(repr(config.llm)),
            _truncate_cell(repr(config.tts)),
            _truncate_cell(greeting),
        ]
        if resources:
            if config.source_path is not None:
                sz = file_size_bytes(config.source_path)
                row.append(format_byte_size(sz))
            else:
                row.append("—")
        table.add_row(*row)

    console.print(table)


def _print_list_plain(
    discovered: list[AgentConfig],
    *,
    resources: bool,
) -> None:
    for config in discovered:
        line = (
            f"{config.name}: class={config.agent_cls.__name__}, "
            f"stt={config.stt!r}, llm={config.llm!r}, tts={config.tts!r}, "
            f"greeting={config.greeting!r}"
        )
        if resources and config.source_path is not None:
            sz = file_size_bytes(config.source_path)
            line += f", source_size={format_byte_size(sz)}"
        print(line)

    if resources:
        print()
        _print_resource_summary_plain(discovered)


def _build_list_json_payload(
    discovered: list[AgentConfig],
    *,
    include_resources: bool,
) -> dict[str, Any]:
    agents: list[dict[str, Any]] = []
    for config in discovered:
        entry: dict[str, Any] = {
            "name": config.name,
            "class": config.agent_cls.__name__,
            "stt": config.stt,
            "llm": config.llm,
            "tts": config.tts,
            "greeting": config.greeting,
        }
        if include_resources:
            entry["source_path"] = (
                str(config.source_path) if config.source_path is not None else None
            )
            entry["source_file_bytes"] = (
                file_size_bytes(config.source_path)
                if config.source_path is not None
                else None
            )
        agents.append(entry)

    # Bump when the JSON shape changes so automation can branch safely.
    payload: dict[str, Any] = {
        "schema_version": 1,
        "command": "list",
        "agents": agents,
    }
    if include_resources:
        footprints = agent_disk_footprints(discovered)
        total_source = sum(f.size_bytes for f in footprints)
        rss_info = get_process_resident_set_info()
        savings = estimate_shared_worker_savings(
            agent_count=len(discovered),
            shared_worker_bytes=rss_info.bytes_value,
        )
        payload["resource_summary"] = {
            "agent_count": len(discovered),
            "total_source_bytes": total_source,
            "agents_with_known_path": len(footprints),
            "resident_set": {
                "bytes": rss_info.bytes_value,
                "metric": rss_info.metric,
                "description": rss_info.description,
            },
            "savings_estimate": {
                "agent_count": savings.agent_count,
                "shared_worker_bytes": savings.shared_worker_bytes,
                "estimated_separate_workers_bytes": (
                    savings.estimated_separate_workers_bytes
                ),
                "estimated_saved_bytes": savings.estimated_saved_bytes,
                "assumptions": list(savings.assumptions),
            },
        }
    return payload


@app.command("start")
def start_command(
    agents_dir: AgentsDirArg,
    default_stt: DefaultSttArg = None,
    default_llm: DefaultLlmArg = None,
    default_tts: DefaultTtsArg = None,
    default_greeting: DefaultGreetingArg = None,
    url: LiveKitUrlArg = None,
    api_key: LiveKitApiKeyArg = None,
    api_secret: LiveKitApiSecretArg = None,
    log_level: LiveKitLogLevelArg = None,
    dashboard: DashboardArg = False,
    dashboard_refresh: DashboardRefreshArg = 1.0,
    metrics_json_file: MetricsJsonFileArg = None,
) -> None:
    """Run the worker (same role as [code]python agent.py start[/code] with LiveKit)."""
    _delegate_discovered_pool_to_livekit(
        agents_dir=agents_dir,
        subcommand="start",
        default_stt=default_stt,
        default_llm=default_llm,
        default_tts=default_tts,
        default_greeting=default_greeting,
        dashboard=dashboard,
        dashboard_refresh=dashboard_refresh,
        metrics_json_file=metrics_json_file,
        url=url,
        api_key=api_key,
        api_secret=api_secret,
        log_level=log_level,
    )


@app.command("dev")
def dev_command(
    agents_dir: AgentsDirArg,
    default_stt: DefaultSttArg = None,
    default_llm: DefaultLlmArg = None,
    default_tts: DefaultTtsArg = None,
    default_greeting: DefaultGreetingArg = None,
    url: LiveKitUrlArg = None,
    api_key: LiveKitApiKeyArg = None,
    api_secret: LiveKitApiSecretArg = None,
    log_level: LiveKitLogLevelArg = None,
    dashboard: DashboardArg = False,
    dashboard_refresh: DashboardRefreshArg = 1.0,
    metrics_json_file: MetricsJsonFileArg = None,
) -> None:
    """Development worker with reload (same role as [code]python agent.py dev[/code])."""
    _delegate_discovered_pool_to_livekit(
        agents_dir=agents_dir,
        subcommand="dev",
        default_stt=default_stt,
        default_llm=default_llm,
        default_tts=default_tts,
        default_greeting=default_greeting,
        dashboard=dashboard,
        dashboard_refresh=dashboard_refresh,
        metrics_json_file=metrics_json_file,
        url=url,
        api_key=api_key,
        api_secret=api_secret,
        log_level=log_level,
    )


@app.command("console")
def console_command(
    agents_dir: AgentsDirArg,
    default_stt: DefaultSttArg = None,
    default_llm: DefaultLlmArg = None,
    default_tts: DefaultTtsArg = None,
    default_greeting: DefaultGreetingArg = None,
    url: LiveKitUrlArg = None,
    api_key: LiveKitApiKeyArg = None,
    api_secret: LiveKitApiSecretArg = None,
    log_level: LiveKitLogLevelArg = None,
    dashboard: DashboardArg = False,
    dashboard_refresh: DashboardRefreshArg = 1.0,
    metrics_json_file: MetricsJsonFileArg = None,
) -> None:
    """Local console session (same role as [code]python agent.py console[/code])."""
    _delegate_discovered_pool_to_livekit(
        agents_dir=agents_dir,
        subcommand="console",
        default_stt=default_stt,
        default_llm=default_llm,
        default_tts=default_tts,
        default_greeting=default_greeting,
        dashboard=dashboard,
        dashboard_refresh=dashboard_refresh,
        metrics_json_file=metrics_json_file,
        url=url,
        api_key=api_key,
        api_secret=api_secret,
        log_level=log_level,
    )


@app.command("connect")
def connect_command(
    agents_dir: AgentsDirArg,
    room: ConnectRoomArg,
    default_stt: DefaultSttArg = None,
    default_llm: DefaultLlmArg = None,
    default_tts: DefaultTtsArg = None,
    default_greeting: DefaultGreetingArg = None,
    participant_identity: ConnectParticipantArg = None,
    log_level: LiveKitLogLevelArg = None,
    url: LiveKitUrlArg = None,
    api_key: LiveKitApiKeyArg = None,
    api_secret: LiveKitApiSecretArg = None,
    dashboard: DashboardArg = False,
    dashboard_refresh: DashboardRefreshArg = 1.0,
    metrics_json_file: MetricsJsonFileArg = None,
) -> None:
    """Connect the worker to an existing room (LiveKit [code]connect[/code])."""
    _run_connect_handoff(
        agents_dir=agents_dir,
        default_stt=default_stt,
        default_llm=default_llm,
        default_tts=default_tts,
        default_greeting=default_greeting,
        room=room,
        participant_identity=participant_identity,
        log_level=log_level,
        url=url,
        api_key=api_key,
        api_secret=api_secret,
        dashboard=dashboard,
        dashboard_refresh=dashboard_refresh,
        metrics_json_file=metrics_json_file,
    )


@app.command("download-files")
def download_files_command(
    agents_dir: AgentsDirArg,
    default_stt: DefaultSttArg = None,
    default_llm: DefaultLlmArg = None,
    default_tts: DefaultTtsArg = None,
    default_greeting: DefaultGreetingArg = None,
    url: LiveKitUrlArg = None,
    api_key: LiveKitApiKeyArg = None,
    api_secret: LiveKitApiSecretArg = None,
    log_level: LiveKitLogLevelArg = None,
) -> None:
    """Download plugin assets (LiveKit [code]download-files[/code])."""
    _delegate_discovered_pool_to_livekit(
        agents_dir=agents_dir,
        subcommand="download-files",
        default_stt=default_stt,
        default_llm=default_llm,
        default_tts=default_tts,
        default_greeting=default_greeting,
        dashboard=False,
        dashboard_refresh=1.0,
        metrics_json_file=None,
        url=url,
        api_key=api_key,
        api_secret=api_secret,
        log_level=log_level,
    )


def _run_pool_with_reporting(
    pool: AgentPool,
    *,
    dashboard: bool,
    dashboard_refresh: float,
    metrics_json_file: Path | None,
) -> None:
    reporter = RuntimeReporter(
        pool,
        dashboard=dashboard,
        refresh_seconds=dashboard_refresh,
        json_output_path=metrics_json_file,
    )
    reporter.start()
    try:
        pool.run()
    finally:
        reporter.stop()


def _print_resource_summary_rich(discovered: list[AgentConfig]) -> None:
    footprints = agent_disk_footprints(discovered)
    total_source = sum(f.size_bytes for f in footprints)
    rss_info = get_process_resident_set_info()
    savings = estimate_shared_worker_savings(
        agent_count=len(discovered),
        shared_worker_bytes=rss_info.bytes_value,
    )

    lines: list[str] = [
        (
            f"Agents: {len(discovered)}; on-disk agent source total: "
            f"{format_byte_size(total_source)}"
        ),
    ]
    if len(footprints) < len(discovered):
        lines.append(
            "Per-agent source size is shown only when the module path is known "
            "(e.g. via discovery)."
        )

    if rss_info.bytes_value is not None:
        lines.append(
            f"{format_byte_size(rss_info.bytes_value)} — {rss_info.description}"
        )
    else:
        lines.append(
            f"Resident memory metric unavailable on this platform ({rss_info.metric})."
        )

    if savings.estimated_saved_bytes is not None:
        lines.append(
            "Estimated shared-worker savings versus one worker per agent: "
            f"{format_byte_size(savings.estimated_saved_bytes)}"
        )

    lines.append("")
    lines.append(
        "OpenRTC runs every agent in one shared LiveKit worker process, so you ship "
        "one container image and one runtime instead of duplicating a large base "
        "image per agent. Actual memory at runtime depends on models, concurrent "
        "sessions, and providers; use host metrics in production."
    )

    console.print()
    console.print(
        Panel(
            "\n".join(lines),
            title="[bold]Resource summary[/bold]",
            subtitle="Local estimates for this [code]openrtc list[/code] process",
            border_style="blue",
        )
    )


def _print_resource_summary_plain(discovered: list[AgentConfig]) -> None:
    footprints = agent_disk_footprints(discovered)
    total_source = sum(f.size_bytes for f in footprints)
    rss_info = get_process_resident_set_info()
    savings = estimate_shared_worker_savings(
        agent_count=len(discovered),
        shared_worker_bytes=rss_info.bytes_value,
    )

    print("Resource summary (local estimates for this `openrtc list` process):")
    print(
        f"  Agents: {len(discovered)}; on-disk agent source total: "
        f"{format_byte_size(total_source)}"
    )
    if len(footprints) < len(discovered):
        print(
            "  Note: per-agent source size is shown only for agents "
            "registered with a known file path (e.g. via discovery)."
        )
    if rss_info.bytes_value is not None:
        print(
            f"  Resident set metric ({rss_info.metric}): "
            f"{format_byte_size(rss_info.bytes_value)} — {rss_info.description}"
        )
    else:
        print(
            f"  Resident memory metric unavailable ({rss_info.metric}): "
            f"{rss_info.description}"
        )
    if savings.estimated_saved_bytes is not None:
        print(
            "  Estimated shared-worker savings versus one worker per agent: "
            f"{format_byte_size(savings.estimated_saved_bytes)}"
        )
    print()
    print(
        "OpenRTC runs every agent in one shared LiveKit worker process, so you ship "
        "one container image and one runtime instead of duplicating a large base "
        "image per agent. Actual memory at runtime depends on models, concurrent "
        "sessions, and providers; use host metrics in production."
    )


def main(argv: list[str] | None = None) -> int:
    """Run the CLI via Typer's underlying Click command (programmatic API).

    Uses :func:`typer.main.get_command` and :meth:`click.core.Command.main` so
    production code does not rely on :class:`typer.testing.CliRunner` (tests may
    still use CliRunner). Pass ``args`` without the program name when invoking
    programmatically; ``prog_name`` matches the ``openrtc`` console script.

    Worker subcommands (``start``, ``dev``, ``console``, ``connect``,
    ``download-files``) mutate :data:`sys.argv` before ``pool.run()``; we restore
    the previous argv list after the command finishes so programmatic callers
    are not polluted.
    """
    from typer.main import get_command

    cli = get_command(app)
    previous_argv = sys.argv
    try:
        if argv is not None:
            cli.main(args=list(argv), prog_name="openrtc", standalone_mode=True)
        else:
            cli.main(args=None, prog_name="openrtc", standalone_mode=True)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1
    finally:
        sys.argv = previous_argv
    return 0
