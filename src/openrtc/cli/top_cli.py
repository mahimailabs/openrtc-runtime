"""``openrtc top`` rendering: pure filter/sort + a rich table build (MAH-92).

The interactive command (in ``main_cli``) polls the worker's IPC socket each
refresh and hands the row dicts here. Keeping filter/sort and the table build
pure makes them testable without a TTY; the live loop stays a thin shell.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from openrtc.observability.introspection_ipc import fetch_snapshot

__all__ = [
    "REFRESH_HZ_MAX",
    "REFRESH_HZ_MIN",
    "SORT_KEYS",
    "STATUS_FILTERS",
    "apply_key",
    "bar_gauge",
    "build_header_panel",
    "build_top_table",
    "cpu_area",
    "fetch_top",
    "filter_and_sort",
    "fmt_gb",
    "fmt_uptime",
    "next_sort_key",
    "next_status_filter",
    "paginate",
    "run_live",
    "run_once",
    "validate_refresh_hz",
]

# Eighths for partial cells, index 0..8 (empty -> full block).
_EIGHTHS = " ▁▂▃▄▅▆▇█"


def bar_gauge(value: float, *, width: int = 20, max_value: float = 100.0) -> str:
    """A horizontal bar: the filled proportion of ``width`` as blocks, rest as track."""
    fraction = 0.0 if max_value <= 0 else max(0.0, min(1.0, value / max_value))
    filled = round(fraction * width)
    return "█" * filled + "░" * (width - filled)


def cpu_area(
    history: Sequence[float],
    *,
    width: int = 40,
    height: int = 4,
    max_value: float = 100.0,
) -> list[str]:
    """Render a filled area chart of ``history`` as ``height`` rows of ``width`` chars.

    The most recent ``width`` samples fill from the bottom up; a short history is
    left-padded with empty columns. The top cell of each column uses a partial
    block so the surface reads as a smooth curve, htop-style.
    """
    recent = list(history)[-width:]
    values = [0.0] * (width - len(recent)) + recent
    denom = max_value if max_value > 0 else 1.0
    rows: list[str] = []
    for row_index in range(height):
        row_from_bottom = height - 1 - row_index
        cells = []
        for value in values:
            filled_rows = max(0.0, min(1.0, value / denom)) * height
            cell = filled_rows - row_from_bottom  # portion of THIS row filled (0..1)
            level = max(0, min(8, round(cell * 8)))
            cells.append(_EIGHTHS[level])
        rows.append("".join(cells))
    return rows


def fmt_gb(num_bytes: int | None) -> str:
    """Format a byte count as ``N.NG``; ``n/a`` when unavailable (no psutil)."""
    if num_bytes is None:
        return "n/a"
    return f"{num_bytes / 1e9:.1f}G"


def fmt_uptime(seconds: float) -> str:
    """Format an uptime as ``<days>d <hours>h`` or, under a day, ``Hh MMm``."""
    total = int(max(0.0, seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    return f"{days}d {hours}h" if days > 0 else f"{hours}h {minutes:02d}m"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def build_header_panel(worker: dict[str, Any] | None) -> RenderableType:
    """Build the ``openrtc top`` worker header: vitals stat block + CPU% area chart.

    ``worker`` is the ``{...}`` block from the socket snapshot. A missing worker
    (stale / empty snapshot) renders as nothing; host vitals show ``n/a`` when the
    worker was built without psutil.
    """
    if worker is None:
        return Text("")
    system: dict[str, Any] = worker.get("system") or {}
    cpu = system.get("cpu_pct")
    mem_used, mem_total = system.get("mem_used_bytes"), system.get("mem_total_bytes")
    vcpus, net, load1 = (
        system.get("vcpus"),
        system.get("net_rate_bps"),
        system.get("load1"),
    )

    cpu_cell = _pct(cpu)
    if cpu is not None:
        cpu_cell += "  " + bar_gauge(cpu, width=14)
    mem_pct = (mem_used / mem_total * 100.0) if mem_used and mem_total else 0.0
    mem_cell = f"{fmt_gb(mem_used)} / {fmt_gb(mem_total)}"
    if mem_used is not None:
        mem_cell = f"{bar_gauge(mem_pct, width=10)}  " + mem_cell
    net_cell = "n/a" if net is None else f"{net * 8 / 1e9:.1f}Gb/s"
    load_cell = "n/a" if load1 is None else f"{load1:.2f}"

    grid = Table.grid(padding=(0, 3))
    for _ in range(4):
        grid.add_column()
    grid.add_row(
        "[dim]CPU[/dim]",
        cpu_cell,
        "[dim]vCPUs[/dim]",
        "n/a" if vcpus is None else str(vcpus),
    )
    grid.add_row(
        "[dim]MEM[/dim]",
        mem_cell,
        "[dim]SWAP[/dim]",
        f"{fmt_gb(system.get('swap_used_bytes'))} / {fmt_gb(system.get('swap_total_bytes'))}",
    )
    grid.add_row(
        "[dim]NET[/dim]",
        net_cell,
        "[dim]SESSIONS[/dim]",
        f"[bold]{worker.get('active_sessions', 0)}[/bold] / {worker.get('max_sessions', 0)}",
    )
    grid.add_row(
        "[dim]LOAD[/dim]",
        load_cell,
        "[dim]SAVED[/dim]",
        fmt_gb(worker.get("saved_bytes")),
    )

    chart_lines = cpu_area(worker.get("cpu_history") or [], width=44, height=3)
    chart = Text("\n".join(chart_lines), style="cyan")
    body = Group(grid, Text(""), Text("CPU% (60s)", style="dim"), chart)
    title = (
        f"[bold]openrtc top[/bold]  ·  {worker.get('name', 'worker')}"
        f"  ·  up {fmt_uptime(worker.get('uptime_s', 0.0))}"
    )
    return Panel(body, title=title, title_align="left", border_style="blue")


# Cycle order for the 's' key. Numeric columns sort descending (biggest first,
# htop-style); text columns ascending.
SORT_KEYS: tuple[str, ...] = (
    "mem_mb",
    "cpu_pct",
    "duration_s",
    "agent_name",
    "session_id",
)
STATUS_FILTERS: tuple[str, ...] = ("all", "active", "slow", "draining", "errored")
_NUMERIC = frozenset({"mem_mb", "peak_mb", "cpu_pct", "duration_s"})

# The inspector clamps its refresh rate to this band (AC: 0.5-10 Hz).
REFRESH_HZ_MIN = 0.5
REFRESH_HZ_MAX = 10.0


def _next_in_cycle(current: str, cycle: tuple[str, ...]) -> str:
    """Return the next value in ``cycle`` after ``current`` (wraps; unknown -> first)."""
    try:
        index = cycle.index(current)
    except ValueError:
        return cycle[0]
    return cycle[(index + 1) % len(cycle)]


def next_sort_key(current: str) -> str:
    """Return the next sort key in the cycle (wraps; unknown -> first)."""
    return _next_in_cycle(current, SORT_KEYS)


def next_status_filter(current: str) -> str:
    """Return the next status filter in the cycle (wraps; unknown -> first)."""
    return _next_in_cycle(current, STATUS_FILTERS)


def validate_refresh_hz(hz: float) -> float:
    """Return ``hz`` if within the allowed band, else raise ``ValueError``."""
    if not REFRESH_HZ_MIN <= hz <= REFRESH_HZ_MAX:
        raise ValueError(
            f"refresh rate must be between {REFRESH_HZ_MIN} and {REFRESH_HZ_MAX} Hz; "
            f"got {hz}"
        )
    return hz


def apply_key(key: str, *, sort_key: str, status_filter: str) -> tuple[str, str, bool]:
    """Fold one keypress into ``(sort_key, status_filter, should_quit)``.

    ``q`` quits, ``s`` cycles the sort column, ``f`` cycles the status filter,
    and ``r`` (or any other key) just triggers a redraw with unchanged state.
    """
    pressed = key.lower()
    if pressed == "q":
        return sort_key, status_filter, True
    if pressed == "s":
        return next_sort_key(sort_key), status_filter, False
    if pressed == "f":
        return sort_key, next_status_filter(status_filter), False
    return sort_key, status_filter, False


def filter_and_sort(
    rows: Iterable[dict[str, Any]],
    *,
    sort_key: str,
    status_filter: str,
    agent_filter: str | None = None,
    tenant_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Filter rows by status, agent, and tenant (``all`` / ``None`` = no filter), then sort."""
    filtered = [
        row
        for row in rows
        if (status_filter in ("all", "") or row.get("status") == status_filter)
        and (agent_filter is None or row.get("agent_name") == agent_filter)
        and (tenant_filter is None or row.get("tenant") == tenant_filter)
    ]
    descending = sort_key in _NUMERIC
    default: Any = 0 if descending else ""
    return sorted(
        filtered,
        key=lambda row: row.get(sort_key, default),
        reverse=descending,
    )


def paginate(
    rows: list[dict[str, Any]], *, page: int, page_size: int | None
) -> tuple[list[dict[str, Any]], int, int]:
    """Slice ``rows`` to one page; return ``(page_rows, page, total_pages)``.

    A ``page_size`` of ``None`` (or non-positive) disables paging: one page holds
    every row. The page is clamped into ``[1, total_pages]`` so an out-of-range
    request lands on the nearest real page instead of an empty view.
    """
    if page_size is None or page_size <= 0:
        return rows, 1, 1
    total_pages = max(1, (len(rows) + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    return rows[start : start + page_size], page, total_pages


# Status label -> Rich style. Unknown statuses render plain (no style).
_STATUS_STYLE: dict[str, str] = {
    "active": "green",
    "idle": "dim",
    "slow": "yellow",
    "draining": "cyan",
    "errored": "red",
}


def _status_cell(status: str) -> str:
    """Uppercase the status label and color it by state (plain when unknown)."""
    label = status.upper()
    style = _STATUS_STYLE.get(status)
    return f"[{style}]{label}[/{style}]" if style else label


def build_top_table(
    rows: Iterable[dict[str, Any]],
    *,
    sort_key: str = "mem_mb",
    status_filter: str = "all",
    agent_filter: str | None = None,
    tenant_filter: str | None = None,
    page: int = 1,
    page_size: int | None = None,
) -> Table:
    """Build the ``openrtc top`` session table (filtered, sorted, paginated).

    Each row carries inline CPU% and MEM~ bars and a colored status. The leading
    ``#`` is a view-local slot index, not a PID: ``openrtc top`` serves coroutine
    mode only, where every session shares one worker process, so there is no
    per-session PID to show. MEM~ is an equal-share approximation (hence the
    tilde); its bar reads current draw against the session's own peak.
    """
    ordered = filter_and_sort(
        rows,
        sort_key=sort_key,
        status_filter=status_filter,
        agent_filter=agent_filter,
        tenant_filter=tenant_filter,
    )
    total = len(ordered)
    page_rows, page, total_pages = paginate(ordered, page=page, page_size=page_size)
    agent_label = agent_filter if agent_filter is not None else "all"
    tenant_label = tenant_filter if tenant_filter is not None else "all"
    table = Table(
        title=(
            f"openrtc top: {total} session(s) "
            f"(sort:{sort_key} status:{status_filter} "
            f"agent:{agent_label} tenant:{tenant_label})"
        ),
        title_style="bold cyan",
        caption=(
            "[dim]q[/dim] quit  [dim]s[/dim] sort  [dim]f[/dim] filter  "
            f"[dim]r[/dim] refresh   ·   PAGE {page}/{total_pages}"
        ),
    )
    table.add_column("#", justify="right", style="dim", no_wrap=True)
    table.add_column("session", style="dim", no_wrap=True)
    table.add_column("agent", no_wrap=True)
    table.add_column("tenant", no_wrap=True)
    table.add_column("dur(s)", justify="right")
    table.add_column("CPU%", no_wrap=True)
    table.add_column("MEM~", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("pin", justify="center")
    start_slot = (page - 1) * (page_size or 0)
    for offset, row in enumerate(page_rows, start=1):
        cpu = float(row.get("cpu_pct", 0.0))
        mem = float(row.get("mem_mb", 0.0))
        peak = float(row.get("peak_mb", 0.0))
        cpu_cell = f"{bar_gauge(cpu, width=8, max_value=100.0)} {cpu:>3.0f}%"
        mem_cell = f"{bar_gauge(mem, width=8, max_value=peak)} {mem:>4.0f}"
        table.add_row(
            str(start_slot + offset),
            str(row.get("session_id", ""))[:12],
            str(row.get("agent_name", "")),
            str(row.get("tenant") or "-"),
            f"{float(row.get('duration_s', 0.0)):.0f}",
            cpu_cell,
            mem_cell,
            _status_cell(str(row.get("status", ""))),
            "*" if row.get("pinned") else "",
        )
    return table


async def fetch_top(
    socket_path: Path, *, timeout: float = 2.0
) -> dict[str, Any] | None:
    """Fetch the full ``{worker, sessions}`` snapshot; ``None`` when no worker serves.

    A missing / refused socket or a read timeout means "no running pool" rather
    than an error, so the caller can print a friendly hint instead of a traceback.
    The worker header block is served alongside the rows (``{worker, sessions}``)
    and consumed by the header renderer.
    """
    try:
        return await fetch_snapshot(socket_path, timeout=timeout)
    except (OSError, TimeoutError):
        return None


async def run_once(
    socket_path: Path,
    *,
    sort_key: str,
    status_filter: str,
    agent_filter: str | None = None,
    tenant_filter: str | None = None,
    console: Console,
    timeout: float = 2.0,
) -> int:
    """Print one snapshot (worker header + session table); exit code (0 ok, 1 no pool)."""
    snapshot = await fetch_top(socket_path, timeout=timeout)
    if snapshot is None:
        console.print(
            f"[red]No running openrtc pool found at[/red] {socket_path}\n"
            "Start a worker in coroutine mode, then run [bold]openrtc top[/bold]."
        )
        return 1
    console.print(
        Group(
            build_header_panel(snapshot["worker"]),
            build_top_table(
                snapshot["sessions"],
                sort_key=sort_key,
                status_filter=status_filter,
                agent_filter=agent_filter,
                tenant_filter=tenant_filter,
            ),
        )
    )
    return 0


async def run_live(  # pragma: no cover - interactive TTY loop
    socket_path: Path,
    *,
    sort_key: str,
    status_filter: str,
    agent_filter: str | None = None,
    tenant_filter: str | None = None,
    refresh_hz: float,
    console: Console,
) -> None:
    """Render a live-updating table until ``q`` is pressed (POSIX TTY only).

    The pure pieces (:func:`build_top_table`, :func:`filter_and_sort`,
    :func:`apply_key`, :func:`validate_refresh_hz`) are unit-tested; this shell
    wires them to ``rich.Live`` plus a raw-mode keyboard reader and so is only
    exercised interactively.
    """
    import sys
    import termios
    import tty

    from rich.live import Live

    interval = 1.0 / refresh_hz
    state = {"sort": sort_key, "status": status_filter}
    loop = asyncio.get_running_loop()
    key_queue: asyncio.Queue[str] = asyncio.Queue()

    def _on_stdin() -> None:
        char = sys.stdin.read(1)
        if char:
            loop.call_soon_threadsafe(key_queue.put_nowait, char)

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    loop.add_reader(fd, _on_stdin)
    try:
        with Live(console=console, auto_refresh=False, screen=True) as live:
            while True:
                snapshot = await fetch_top(socket_path) or {
                    "worker": None,
                    "sessions": [],
                }
                live.update(
                    Group(
                        build_header_panel(snapshot["worker"]),
                        build_top_table(
                            snapshot["sessions"],
                            sort_key=state["sort"],
                            status_filter=state["status"],
                            agent_filter=agent_filter,
                            tenant_filter=tenant_filter,
                        ),
                    )
                )
                live.refresh()
                with contextlib.suppress(TimeoutError):
                    key = await asyncio.wait_for(key_queue.get(), timeout=interval)
                    new_sort, new_status, should_quit = apply_key(
                        key, sort_key=state["sort"], status_filter=state["status"]
                    )
                    if should_quit:
                        return
                    state["sort"], state["status"] = new_sort, new_status
    finally:
        loop.remove_reader(fd)
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
