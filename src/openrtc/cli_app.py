from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from openrtc.pool import AgentConfig, AgentPool
from openrtc.resources import (
    agent_disk_footprints,
    file_size_bytes,
    format_byte_size,
    get_process_resident_set_info,
)

logger = logging.getLogger("openrtc")

app = typer.Typer(
    name="openrtc",
    help="Discover and run multiple LiveKit agents in one worker.",
    pretty_exceptions_show_locals=False,
    rich_markup_mode="rich",
    no_args_is_help=True,
)

console = Console()


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


def _discover_or_exit(agents_dir: Path, pool: AgentPool) -> list[AgentConfig]:
    discovered = pool.discover(agents_dir)
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
                "On-disk sizes and RSS are best-effort estimates for this process."
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
        table.add_column("Source file", style="dim")

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
            line += f", source_file={format_byte_size(sz)}"
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
        payload["resource_summary"] = {
            "agent_count": len(discovered),
            "total_source_bytes": total_source,
            "agents_with_known_path": len(footprints),
            "resident_set": {
                "bytes": rss_info.bytes_value,
                "metric": rss_info.metric,
                "description": rss_info.description,
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
) -> None:
    """Run the LiveKit worker (production-style entrypoint)."""
    pool = AgentPool(
        **_pool_kwargs(default_stt, default_llm, default_tts, default_greeting)
    )
    _discover_or_exit(agents_dir, pool)
    sys.argv = [sys.argv[0], "start"]
    pool.run()


@app.command("dev")
def dev_command(
    agents_dir: AgentsDirArg,
    default_stt: DefaultSttArg = None,
    default_llm: DefaultLlmArg = None,
    default_tts: DefaultTtsArg = None,
    default_greeting: DefaultGreetingArg = None,
) -> None:
    """Run the LiveKit worker in development mode."""
    pool = AgentPool(
        **_pool_kwargs(default_stt, default_llm, default_tts, default_greeting)
    )
    _discover_or_exit(agents_dir, pool)
    sys.argv = [sys.argv[0], "dev"]
    pool.run()


def _print_resource_summary_rich(discovered: list[AgentConfig]) -> None:
    footprints = agent_disk_footprints(discovered)
    total_source = sum(f.size_bytes for f in footprints)
    rss_info = get_process_resident_set_info()

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
    print()
    print(
        "OpenRTC runs every agent in one shared LiveKit worker process, so you ship "
        "one container image and one runtime instead of duplicating a large base "
        "image per agent. Actual memory at runtime depends on models, concurrent "
        "sessions, and providers; use host metrics in production."
    )


def main(argv: list[str] | None = None) -> int:
    """Invoke the Typer application (same path as the ``openrtc`` console script)."""
    previous_argv = sys.argv
    if argv is not None:
        sys.argv = [previous_argv[0]] + list(argv)
    try:
        app()
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1
    finally:
        if argv is not None:
            sys.argv = previous_argv
    return 0
