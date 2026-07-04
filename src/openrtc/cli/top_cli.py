"""``openrtc top`` rendering: pure filter/sort + a rich table build (MAH-92).

The interactive command (in ``main_cli``) polls the worker's IPC socket each
refresh and hands the row dicts here. Keeping filter/sort and the table build
pure makes them testable without a TTY; the live loop stays a thin shell.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from openrtc.observability.introspection_ipc import fetch_snapshot

__all__ = [
    "REFRESH_HZ_MAX",
    "REFRESH_HZ_MIN",
    "SORT_KEYS",
    "STATUS_FILTERS",
    "apply_key",
    "build_top_table",
    "fetch_rows",
    "filter_and_sort",
    "next_sort_key",
    "next_status_filter",
    "run_live",
    "run_once",
    "validate_refresh_hz",
]

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
    rows: Iterable[dict[str, Any]], *, sort_key: str, status_filter: str
) -> list[dict[str, Any]]:
    """Filter rows by status (``all`` = no filter) and sort by ``sort_key``."""
    filtered = [
        row
        for row in rows
        if status_filter in ("all", "") or row.get("status") == status_filter
    ]
    descending = sort_key in _NUMERIC
    default: Any = 0 if descending else ""
    return sorted(
        filtered,
        key=lambda row: row.get(sort_key, default),
        reverse=descending,
    )


def build_top_table(
    rows: Iterable[dict[str, Any]],
    *,
    sort_key: str = "mem_mb",
    status_filter: str = "all",
) -> Table:
    """Build the ``openrtc top`` table (filtered + sorted)."""
    ordered = filter_and_sort(rows, sort_key=sort_key, status_filter=status_filter)
    table = Table(
        title=(
            f"openrtc top — {len(ordered)} session(s) "
            f"— sort:{sort_key} filter:{status_filter}"
        ),
        title_style="bold cyan",
    )
    table.add_column("session", style="dim", no_wrap=True)
    table.add_column("agent", no_wrap=True)
    table.add_column("tenant", no_wrap=True)
    table.add_column("dur(s)", justify="right")
    table.add_column("mem(MB)", justify="right")
    table.add_column("peak", justify="right")
    table.add_column("cpu%", justify="right")
    table.add_column("status", no_wrap=True)
    table.add_column("pin", justify="center")
    for row in ordered:
        table.add_row(
            str(row.get("session_id", ""))[:12],
            str(row.get("agent_name", "")),
            str(row.get("tenant") or "-"),
            f"{float(row.get('duration_s', 0.0)):.0f}",
            f"{float(row.get('mem_mb', 0.0)):.0f}",
            f"{float(row.get('peak_mb', 0.0)):.0f}",
            f"{float(row.get('cpu_pct', 0.0)):.0f}",
            str(row.get("status", "")),
            "*" if row.get("pinned") else "",
        )
    return table


async def fetch_rows(
    socket_path: Path, *, timeout: float = 2.0
) -> list[dict[str, Any]] | None:
    """Fetch one snapshot; return ``None`` when no worker is serving the socket.

    A missing / refused socket or a read timeout means "no running pool" rather
    than an error, so the caller can print a friendly hint instead of a traceback.
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
    console: Console,
    timeout: float = 2.0,
) -> int:
    """Print one snapshot table; return an exit code (0 ok, 1 no pool)."""
    rows = await fetch_rows(socket_path, timeout=timeout)
    if rows is None:
        console.print(
            f"[red]No running openrtc pool found at[/red] {socket_path}\n"
            "Start a worker in coroutine mode, then run [bold]openrtc top[/bold]."
        )
        return 1
    console.print(build_top_table(rows, sort_key=sort_key, status_filter=status_filter))
    return 0


async def run_live(  # pragma: no cover - interactive TTY loop
    socket_path: Path,
    *,
    sort_key: str,
    status_filter: str,
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
                rows = await fetch_rows(socket_path) or []
                live.update(
                    build_top_table(
                        rows,
                        sort_key=state["sort"],
                        status_filter=state["status"],
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
