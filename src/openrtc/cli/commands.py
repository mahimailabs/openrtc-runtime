"""Typer CLI: command registration and programmatic :func:`main` entry."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Annotated

import typer
from typer import Context

from openrtc.cli.dashboard import (
    build_list_json_payload,
    build_runtime_dashboard,
    print_list_plain,
    print_list_rich_table,
    print_resource_summary_rich,
)
from openrtc.cli.livekit import (
    _delegate_discovered_pool_to_livekit,
    _discover_or_exit,
    _run_connect_handoff,
    inject_cli_positional_paths,
)
from openrtc.cli.params import SharedLiveKitWorkerOptions, agent_provider_kwargs
from openrtc.cli.reporter import RuntimeReporter
from openrtc.cli.types import (
    _LIVEKIT_CLI_CONTEXT_SETTINGS,
    PANEL_ADVANCED,
    AgentsDirArg,
    ConnectParticipantArg,
    ConnectRoomArg,
    DashboardArg,
    DashboardRefreshArg,
    DefaultGreetingArg,
    DefaultLlmArg,
    DefaultSttArg,
    DefaultTtsArg,
    IsolationArg,
    LiveKitApiKeyArg,
    LiveKitApiSecretArg,
    LiveKitLogLevelArg,
    LiveKitUrlArg,
    MaxConcurrentSessionsArg,
    MetricsJsonFileArg,
    MetricsJsonlArg,
    MetricsJsonlIntervalArg,
    TuiFromStartArg,
    TuiWatchPathArg,
)
from openrtc.core.pool import AgentPool
from openrtc.observability.stream import DEFAULT_METRICS_JSONL_FILENAME

logger = logging.getLogger("openrtc")

_QUICKSTART_EPILOG = (
    "[bold]Typical usage[/bold]: set [code]LIVEKIT_URL[/code], [code]LIVEKIT_API_KEY[/code], "
    "and [code]LIVEKIT_API_SECRET[/code], then run "
    "[code]openrtc dev ./agents[/code] (agents dir only) or add a second path for "
    "[code]--metrics-jsonl[/code]; or use [code]--agents-dir[/code]. "
    "[code]start[/code] for production. "
    "Defaults are conservative (e.g. no dashboard, 1s refresh); tuning flags are under "
    "the [bold]Advanced[/bold] group in each command's [code]--help[/code]."
)

app = typer.Typer(
    name="openrtc",
    help=(
        "Run multiple LiveKit voice agents from one shared worker. Commands match "
        "LiveKit Agents ([code]dev[/code], [code]start[/code], [code]console[/code], "
        "[code]connect[/code], [code]download-files[/code]) plus [code]list[/code] and "
        "[code]tui[/code]. Most commands accept the agents directory as the first "
        "positional argument instead of [code]--agents-dir[/code]; "
        "[code]start[/code]/[code]dev[/code]/[code]console[/code] also accept a "
        "second path for [code]--metrics-jsonl[/code], and [code]tui[/code] can "
        "take a metrics file path as the first positional instead of [code]--watch[/code]; "
        "credentials use [code]LIVEKIT_*[/code] env vars by default (CLI flags optional)."
    ),
    epilog=_QUICKSTART_EPILOG,
    pretty_exceptions_show_locals=False,
    rich_markup_mode="rich",
    no_args_is_help=True,
)


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
            rich_help_panel=PANEL_ADVANCED,
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
        **agent_provider_kwargs(default_stt, default_llm, default_tts, default_greeting)
    )
    discovered = _discover_or_exit(agents_dir, pool)

    if json_output:
        payload = build_list_json_payload(discovered, include_resources=resources)
        print(json.dumps(payload, indent=2, default=str))
        return

    if plain:
        print_list_plain(discovered, resources=resources)
        return

    print_list_rich_table(discovered, resources=resources)
    if resources:
        print_resource_summary_rich(discovered)


_WORKER_POSITIONAL_HELP = (
    " Use [code]openrtc {name} ./agents[/code] or [code]--agents-dir ./agents[/code]; "
    "add a second path only when you want JSONL metrics "
    f"([code]--metrics-jsonl[/code], e.g. [code]./{DEFAULT_METRICS_JSONL_FILENAME}[/code] for "
    "[code]openrtc tui[/code])."
)

_STANDARD_LIVEKIT_WORKER_SPECS: tuple[tuple[str, str], ...] = (
    (
        "start",
        "Run the worker (same role as [code]python agent.py start[/code] with LiveKit)."
        + _WORKER_POSITIONAL_HELP.format(name="start"),
    ),
    (
        "dev",
        "Development worker with reload (same role as [code]python agent.py dev[/code])."
        + _WORKER_POSITIONAL_HELP.format(name="dev"),
    ),
    (
        "console",
        "Local console session (same role as [code]python agent.py console[/code])."
        + _WORKER_POSITIONAL_HELP.format(name="console"),
    ),
)


def _make_standard_livekit_worker_handler(subcommand: str):
    """Build a Typer command that shares one option signature for start/dev/console."""

    def handler(
        _ctx: Context,
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
        metrics_jsonl: MetricsJsonlArg = None,
        metrics_jsonl_interval: MetricsJsonlIntervalArg = None,
        isolation: IsolationArg = "coroutine",
        max_concurrent_sessions: MaxConcurrentSessionsArg = 50,
    ) -> None:
        _delegate_discovered_pool_to_livekit(
            subcommand,
            SharedLiveKitWorkerOptions.from_cli(
                agents_dir,
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
            ),
        )

    handler.__name__ = f"{subcommand}_command"
    return handler


for _subcommand, _doc in _STANDARD_LIVEKIT_WORKER_SPECS:
    _handler = _make_standard_livekit_worker_handler(_subcommand)
    _handler.__doc__ = _doc
    app.command(_subcommand, context_settings=_LIVEKIT_CLI_CONTEXT_SETTINGS)(_handler)


@app.command("connect", context_settings=_LIVEKIT_CLI_CONTEXT_SETTINGS)
def connect_command(
    _ctx: Context,
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
    metrics_jsonl: MetricsJsonlArg = None,
    metrics_jsonl_interval: MetricsJsonlIntervalArg = None,
) -> None:
    """Connect the worker to an existing room (LiveKit [code]connect[/code])."""
    _run_connect_handoff(
        SharedLiveKitWorkerOptions.from_cli(
            agents_dir,
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
        ),
        room=room,
        participant_identity=participant_identity,
    )


@app.command("download-files")
def download_files_command(
    agents_dir: AgentsDirArg,
    url: LiveKitUrlArg = None,
    api_key: LiveKitApiKeyArg = None,
    api_secret: LiveKitApiSecretArg = None,
    log_level: LiveKitLogLevelArg = None,
) -> None:
    """Download plugin assets (LiveKit [code]download-files[/code]).

    Uses the same discovery path as other commands so the worker entrypoint is
    valid; provider defaults are not needed for this subcommand.
    """
    _delegate_discovered_pool_to_livekit(
        "download-files",
        SharedLiveKitWorkerOptions.for_download_files(
            agents_dir,
            url=url,
            api_key=api_key,
            api_secret=api_secret,
            log_level=log_level,
        ),
    )


@app.command("tui")
def tui_command(
    watch: TuiWatchPathArg = Path(DEFAULT_METRICS_JSONL_FILENAME),
    from_start: TuiFromStartArg = False,
) -> None:
    """Sidecar Textual UI tailing JSONL metrics (requires the ``tui`` extra).

    With no ``--watch``, tails ``./openrtc-metrics.jsonl`` in the current directory;
    start the worker with ``--metrics-jsonl`` set to that same path.
    """
    try:
        from openrtc.tui.app import run_metrics_tui
    except ImportError as exc:
        logger.error(
            "The TUI requires Textual. Install with: pip install 'openrtc[tui]' "
            "(the cli extra is required for the openrtc command)."
        )
        raise typer.Exit(code=1) from exc
    try:
        run_metrics_tui(watch, from_start=from_start)
    except ValueError as exc:
        logger.error("%s", exc)
        raise typer.Exit(code=1) from None


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
            injected_args = inject_cli_positional_paths(list(argv))
            # Mirror a real CLI invocation so LiveKit handoff logic that
            # inspects sys.argv sees the injected arguments (e.g. --reload).
            sys.argv = [previous_argv[0], *injected_args]
            cli.main(
                args=injected_args,
                prog_name="openrtc",
                standalone_mode=True,
            )
        else:
            if len(sys.argv) >= 2:
                tail = inject_cli_positional_paths(list(sys.argv[1:]))
                sys.argv = [sys.argv[0], *tail]
            cli.main(args=None, prog_name="openrtc", standalone_mode=True)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1
    finally:
        sys.argv = previous_argv
    return 0


__all__ = [
    "RuntimeReporter",
    "app",
    "build_runtime_dashboard",
    "main",
]
