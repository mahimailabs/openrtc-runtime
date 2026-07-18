"""openrtc top rendering: filter, sort, and table build (MAH-92)."""

from __future__ import annotations

import io
from typing import Any

from rich.console import Console

from openrtc.cli.top_cli import (
    SORT_KEYS,
    bar_gauge,
    build_top_table,
    cpu_area,
    filter_and_sort,
    fmt_gb,
    next_sort_key,
)


def test_bar_gauge_fills_proportion_of_width() -> None:
    assert bar_gauge(50.0, width=10, max_value=100.0) == "█████░░░░░"
    assert bar_gauge(0.0, width=4) == "░░░░"
    assert bar_gauge(200.0, width=4, max_value=100.0) == "████"  # clamped to full
    assert bar_gauge(5.0, width=4, max_value=0.0) == "░░░░"  # max 0 -> empty, no crash


def test_cpu_area_renders_filled_rows() -> None:
    assert cpu_area([100.0, 100.0], width=2, height=2) == ["██", "██"]  # full
    assert cpu_area([0.0, 0.0], width=2, height=2) == ["  ", "  "]  # empty
    # 50% of a 2-row chart fills the bottom row only.
    assert cpu_area([50.0], width=1, height=2, max_value=100.0) == [" ", "█"]


def test_cpu_area_left_pads_short_history() -> None:
    # Fewer samples than width: pad the left with empty columns.
    assert cpu_area([100.0], width=3, height=1) == ["  █"]


def test_fmt_gb_formats_bytes_and_handles_none() -> None:
    assert fmt_gb(31_200_000_000) == "31.2G"
    assert fmt_gb(0) == "0.0G"
    assert fmt_gb(None) == "n/a"


def _rows() -> list[dict[str, Any]]:
    return [
        {
            "session_id": "s1",
            "agent_name": "sales",
            "tenant": "acme",
            "duration_s": 5.0,
            "mem_mb": 120.0,
            "peak_mb": 150.0,
            "cpu_pct": 10.0,
            "status": "active",
            "pinned": True,
        },
        {
            "session_id": "s2",
            "agent_name": "support",
            "tenant": None,
            "duration_s": 9.0,
            "mem_mb": 300.0,
            "peak_mb": 320.0,
            "cpu_pct": 80.0,
            "status": "slow",
            "pinned": False,
        },
        {
            "session_id": "s3",
            "agent_name": "billing",
            "tenant": None,
            "duration_s": 1.0,
            "mem_mb": 50.0,
            "peak_mb": 60.0,
            "cpu_pct": 5.0,
            "status": "active",
            "pinned": False,
        },
    ]


def test_next_sort_key_cycles_and_wraps() -> None:
    assert next_sort_key("mem_mb") == "cpu_pct"
    assert next_sort_key(SORT_KEYS[-1]) == SORT_KEYS[0]
    assert next_sort_key("bogus") == SORT_KEYS[0]


def test_sort_numeric_descending() -> None:
    order = [
        r["session_id"]
        for r in filter_and_sort(_rows(), sort_key="mem_mb", status_filter="all")
    ]
    assert order == ["s2", "s1", "s3"]  # 300, 120, 50
    order = [
        r["session_id"]
        for r in filter_and_sort(_rows(), sort_key="cpu_pct", status_filter="all")
    ]
    assert order == ["s2", "s1", "s3"]  # 80, 10, 5


def test_sort_text_ascending() -> None:
    order = [
        r["session_id"]
        for r in filter_and_sort(_rows(), sort_key="agent_name", status_filter="all")
    ]
    assert order == ["s3", "s1", "s2"]  # billing, sales, support


def test_filter_by_status() -> None:
    active = filter_and_sort(_rows(), sort_key="mem_mb", status_filter="active")
    assert {r["session_id"] for r in active} == {"s1", "s3"}
    slow = filter_and_sort(_rows(), sort_key="mem_mb", status_filter="slow")
    assert {r["session_id"] for r in slow} == {"s2"}


def test_build_table_row_count_and_content() -> None:
    table = build_top_table(_rows(), sort_key="mem_mb", status_filter="all")
    assert table.row_count == 3

    console = Console(file=io.StringIO(), width=200)
    console.print(table)
    text = console.file.getvalue()  # type: ignore[attr-defined]
    assert "sales" in text
    assert "support" in text
    assert "sort:mem_mb" in text
    assert "3 session(s)" in text


def test_build_table_respects_filter() -> None:
    table = build_top_table(_rows(), status_filter="slow")
    assert table.row_count == 1


def test_filter_by_agent() -> None:
    support = filter_and_sort(
        _rows(), sort_key="mem_mb", status_filter="all", agent_filter="support"
    )
    assert {r["session_id"] for r in support} == {"s2"}


def test_build_table_respects_agent_filter() -> None:
    table = build_top_table(_rows(), agent_filter="billing")
    assert table.row_count == 1
    console = Console(file=io.StringIO(), width=200)
    console.print(table)
    assert "agent:billing" in console.file.getvalue()  # type: ignore[attr-defined]
