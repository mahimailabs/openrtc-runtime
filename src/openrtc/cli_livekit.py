"""LiveKit CLI handoff: argv stripping, env overrides, pool lifecycle."""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import typer

from openrtc.cli_params import SharedLiveKitWorkerOptions
from openrtc.cli_reporter import RuntimeReporter
from openrtc.core.pool import AgentConfig, AgentPool

logger = logging.getLogger("openrtc")


_OPENRTC_ONLY_FLAGS_WITH_VALUE: frozenset[str] = frozenset(
    {
        "--agents-dir",
        "--default-stt",
        "--default-llm",
        "--default-tts",
        "--default-greeting",
        "--dashboard-refresh",
        "--metrics-json-file",
        "--metrics-jsonl",
        "--metrics-jsonl-interval",
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

    For flags in ``_OPENRTC_ONLY_FLAGS_WITH_VALUE``, the **next** token is always
    consumed as the value when present, even if it starts with ``--`` (e.g. a
    path or provider string must not be mistaken for a following flag).
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
            if i < len(argv_tail):
                i += 1
            continue
        out.append(arg)
        i += 1
    return out


def _inject_agents_dir_positional(argv: list[str]) -> list[str]:
    """``<cmd> ./agents ...`` → ``<cmd> --agents-dir ./agents ...`` when flag absent."""
    rest = argv[1:]
    if not rest or rest[0].startswith("-"):
        return argv
    if any(t == "--agents-dir" or t.startswith("--agents-dir=") for t in rest):
        return argv
    return [argv[0], "--agents-dir", rest[0], *rest[1:]]


def _inject_worker_start_dev_console(argv: list[str]) -> list[str]:
    """``dev|start|console ./agents [./metrics.jsonl]`` into ``--agents-dir`` / ``--metrics-jsonl``."""
    rest = argv[1:]
    if not rest or rest[0].startswith("-"):
        return argv
    if any(t == "--agents-dir" or t.startswith("--agents-dir=") for t in rest):
        return argv
    has_metrics_flag = any(
        t == "--metrics-jsonl" or t.startswith("--metrics-jsonl=") for t in rest
    )
    agents_token = rest[0]
    out = [argv[0], "--agents-dir", agents_token]
    pos = 1
    if not has_metrics_flag and pos < len(rest) and not rest[pos].startswith("-"):
        out.extend(["--metrics-jsonl", rest[pos]])
        pos += 1
    out.extend(rest[pos:])
    return out


def _inject_tui_watch_positional(argv: list[str]) -> list[str]:
    """``tui ./metrics.jsonl`` → ``tui --watch ./metrics.jsonl`` when ``--watch`` absent."""
    rest = argv[1:]
    if not rest or rest[0].startswith("-"):
        return argv
    if any(t == "--watch" or t.startswith("--watch=") for t in rest):
        return argv
    return [argv[0], "--watch", rest[0], *rest[1:]]


def inject_cli_positional_paths(argv: list[str]) -> list[str]:
    """Rewrite common positional shortcuts into explicit flags before Typer parses.

    Pass-through tokens (e.g. ``--reload`` for LiveKit) must never be treated as
    paths; only a leading non-flag token after the subcommand is rewritten.
    """
    if not argv:
        return argv
    sub = argv[0]
    if sub in {"start", "dev", "console"}:
        return _inject_worker_start_dev_console(argv)
    if sub in {"list", "connect", "download-files"}:
        return _inject_agents_dir_positional(argv)
    if sub == "tui":
        return _inject_tui_watch_positional(argv)
    return argv


def inject_worker_positional_paths(argv: list[str]) -> list[str]:
    """Backward-compatible alias for :func:`inject_cli_positional_paths`."""
    return inject_cli_positional_paths(argv)


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


_LIVEKIT_ENV_OVERRIDE_KEYS: tuple[str, ...] = (
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "LIVEKIT_LOG_LEVEL",
)


def _snapshot_livekit_env() -> dict[str, str | None]:
    return {key: os.environ.get(key) for key in _LIVEKIT_ENV_OVERRIDE_KEYS}


def _restore_livekit_env(snapshot: dict[str, str | None]) -> None:
    for key, previous in snapshot.items():
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


@contextlib.contextmanager
def _livekit_env_overrides(
    *,
    url: str | None,
    api_key: str | None,
    api_secret: str | None,
    log_level: str | None,
) -> Iterator[None]:
    """Temporarily set LiveKit env vars; restore previous values on exit."""
    snapshot = _snapshot_livekit_env()
    try:
        if url is not None:
            os.environ["LIVEKIT_URL"] = url
        if api_key is not None:
            os.environ["LIVEKIT_API_KEY"] = api_key
        if api_secret is not None:
            os.environ["LIVEKIT_API_SECRET"] = api_secret
        if log_level is not None:
            os.environ["LIVEKIT_LOG_LEVEL"] = log_level
        yield
    finally:
        _restore_livekit_env(snapshot)


def _delegate_discovered_pool_to_livekit(
    subcommand: str,
    opts: SharedLiveKitWorkerOptions,
) -> None:
    """Discover agents, optionally set connection env, then run a LiveKit CLI subcommand."""
    pool = AgentPool(**opts.agent_pool_kwargs())
    _discover_or_exit(opts.agents_dir, pool)
    with _livekit_env_overrides(
        url=opts.url,
        api_key=opts.api_key,
        api_secret=opts.api_secret,
        log_level=opts.log_level,
    ):
        _livekit_sys_argv(subcommand)
        _run_pool_with_reporting(
            pool,
            dashboard=opts.dashboard,
            dashboard_refresh=opts.dashboard_refresh,
            metrics_json_file=opts.metrics_json_file,
            metrics_jsonl=opts.metrics_jsonl,
            metrics_jsonl_interval=opts.metrics_jsonl_interval,
        )


def _run_connect_handoff(
    opts: SharedLiveKitWorkerOptions,
    *,
    room: str,
    participant_identity: str | None,
) -> None:
    """Hand off to LiveKit ``connect`` with explicit argv (Typer consumes flags first)."""
    pool = AgentPool(**opts.agent_pool_kwargs())
    _discover_or_exit(opts.agents_dir, pool)
    with _livekit_env_overrides(
        url=opts.url,
        api_key=opts.api_key,
        api_secret=opts.api_secret,
        log_level=None,
    ):
        prog = sys.argv[0]
        tail: list[str] = ["connect", "--room", room]
        if participant_identity is not None:
            tail.extend(["--participant-identity", participant_identity])
        if opts.log_level is not None:
            tail.extend(["--log-level", opts.log_level])
        sys.argv = [prog, *tail]
        _run_pool_with_reporting(
            pool,
            dashboard=opts.dashboard,
            dashboard_refresh=opts.dashboard_refresh,
            metrics_json_file=opts.metrics_json_file,
            metrics_jsonl=opts.metrics_jsonl,
            metrics_jsonl_interval=opts.metrics_jsonl_interval,
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


def _run_pool_with_reporting(
    pool: AgentPool,
    *,
    dashboard: bool,
    dashboard_refresh: float,
    metrics_json_file: Path | None,
    metrics_jsonl: Path | None = None,
    metrics_jsonl_interval: float | None = None,
) -> None:
    reporter = RuntimeReporter(
        pool,
        dashboard=dashboard,
        refresh_seconds=dashboard_refresh,
        json_output_path=metrics_json_file,
        metrics_jsonl_path=metrics_jsonl,
        metrics_jsonl_interval=metrics_jsonl_interval,
    )
    reporter.start()
    try:
        pool.run()
    finally:
        reporter.stop()
