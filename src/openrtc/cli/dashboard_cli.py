"""Rich dashboard, list output, and resource summary rendering for the CLI."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from openrtc.core.config import AgentConfig
from openrtc.observability.footprint import (
    agent_disk_footprints,
    file_size_bytes,
    format_byte_size,
)
from openrtc.observability.resident_set import get_process_resident_set_info
from openrtc.observability.snapshot import PoolRuntimeSnapshot

console = Console()


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
        table.add_row("-", "0")
    return table


def build_runtime_dashboard(snapshot: PoolRuntimeSnapshot) -> Panel:
    """Build a Rich dashboard from a runtime snapshot."""
    metrics = Table.grid(expand=True)
    metrics.add_column()

    rss_bytes = snapshot.resident_set.bytes_value
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
    left.add_row("Last route", snapshot.last_routed_agent or "-")

    metrics.add_row(left)

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


def _truncate_cell(text: str, max_len: int = 36) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def print_list_rich_table(
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
                row.append("-")
        table.add_row(*row)

    console.print(table)


def print_list_plain(
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
        print_resource_summary_plain(discovered)


def build_list_json_payload(
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
        "schema_version": 2,
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


def print_resource_summary_rich(discovered: list[AgentConfig]) -> None:
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
            f"{format_byte_size(rss_info.bytes_value)} ({rss_info.description})"
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


def print_resource_summary_plain(discovered: list[AgentConfig]) -> None:
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
            f"{format_byte_size(rss_info.bytes_value)} ({rss_info.description})"
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
