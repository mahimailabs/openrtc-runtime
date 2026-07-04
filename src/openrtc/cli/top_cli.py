"""``openrtc top`` rendering: pure filter/sort + a rich table build (MAH-92).

The interactive command (in ``main_cli``) polls the worker's IPC socket each
refresh and hands the row dicts here. Keeping filter/sort and the table build
pure makes them testable without a TTY; the live loop stays a thin shell.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from rich.table import Table

__all__ = [
    "SORT_KEYS",
    "STATUS_FILTERS",
    "build_top_table",
    "filter_and_sort",
    "next_sort_key",
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


def next_sort_key(current: str) -> str:
    """Return the next sort key in the cycle (wraps; unknown -> first)."""
    try:
        index = SORT_KEYS.index(current)
    except ValueError:
        return SORT_KEYS[0]
    return SORT_KEYS[(index + 1) % len(SORT_KEYS)]


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
