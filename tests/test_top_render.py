"""openrtc top rendering: filter, sort, and table build (MAH-92)."""

from __future__ import annotations

import io
from typing import Any

from rich.console import Console

from openrtc.cli.top_cli import (
    SORT_KEYS,
    bar_gauge,
    build_header_panel,
    build_top_table,
    cpu_area,
    filter_and_sort,
    fmt_gb,
    fmt_uptime,
    next_sort_key,
    paginate,
)


def _worker(*, available: bool = True) -> dict[str, Any]:
    return {
        "name": "wrk-01",
        "uptime_s": 7 * 86400 + 14 * 3600 + 32 * 60,
        "active_sessions": 162,
        "max_sessions": 1000,
        "started": 4218,
        "failed": 0,
        "saved_bytes": 248_000_000_000,
        "draining": False,
        "system": {
            "available": available,
            "cpu_pct": 17.6 if available else None,
            "vcpus": 16 if available else None,
            "mem_used_bytes": 31_200_000_000 if available else None,
            "mem_total_bytes": 68_700_000_000 if available else None,
            "swap_used_bytes": 0 if available else None,
            "swap_total_bytes": 8_000_000_000 if available else None,
            "load1": 0.74 if available else None,
            "load5": 0.68 if available else None,
            "load15": 0.59 if available else None,
            "net_rate_bps": 150_000_000.0 if available else None,
        },
        "cpu_history": [10.0, 20.0, 40.0, 30.0, 60.0, 80.0, 50.0],
    }


def _render(renderable: Any) -> str:
    console = Console(file=io.StringIO(), width=120)
    console.print(renderable)
    return console.file.getvalue()  # type: ignore[attr-defined]


def test_fmt_uptime_formats_days_hours() -> None:
    assert fmt_uptime(7 * 86400 + 14 * 3600 + 32 * 60) == "7d 14h"
    assert fmt_uptime(4 * 3600 + 12 * 60) == "4h 12m"
    assert fmt_uptime(45) == "0h 00m"


def test_build_header_panel_shows_worker_and_vitals() -> None:
    text = _render(build_header_panel(_worker()))
    assert "wrk-01" in text
    assert "17.6" in text  # CPU%
    assert "162" in text  # SESSIONS active
    assert "1000" in text  # SESSIONS max
    assert "16" in text  # vCPUs
    assert "7d 14h" in text  # uptime


def test_build_header_panel_degrades_without_psutil() -> None:
    text = _render(build_header_panel(_worker(available=False)))
    assert "n/a" in text  # system vitals unavailable
    assert "162" in text  # pool-derived sessions still shown


def test_build_header_panel_handles_missing_worker() -> None:
    # A stale/empty snapshot (no worker block) renders as nothing, no crash.
    assert _render(build_header_panel(None)).strip() == ""


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


def _paged_rows(n: int) -> list[dict[str, Any]]:
    return [{"session_id": f"s{i}", "mem_mb": float(n - i)} for i in range(n)]


def test_paginate_slices_and_reports_total_pages() -> None:
    rows = _paged_rows(6)
    first, page, total = paginate(rows, page=1, page_size=2)
    assert [r["session_id"] for r in first] == ["s0", "s1"]
    assert (page, total) == (1, 3)
    third, page, total = paginate(rows, page=3, page_size=2)
    assert [r["session_id"] for r in third] == ["s4", "s5"]
    assert (page, total) == (3, 3)


def test_paginate_clamps_out_of_range_and_handles_no_size() -> None:
    rows = _paged_rows(3)
    last, page, total = paginate(rows, page=99, page_size=2)  # clamps to last page
    assert [r["session_id"] for r in last] == ["s2"]
    assert (page, total) == (2, 2)
    # No page size disables paging: one page holding every row.
    everything, page, total = paginate(rows, page=1, page_size=None)
    assert len(everything) == 3
    assert (page, total) == (1, 1)


def test_build_table_shows_slot_index_column() -> None:
    text = _render(build_top_table(_rows(), sort_key="mem_mb", status_filter="all"))
    assert "#" in text  # the leading slot column header
    # Sorted by mem desc (s2, s1, s3), slots are 1..3 in view order.
    assert "1" in text
    assert "2" in text
    assert "3" in text


def test_build_table_cpu_and_mem_have_inline_bars() -> None:
    text = _render(build_top_table(_rows()))
    assert "CPU%" in text
    assert "MEM~" in text  # tilde flags the equal-share approximation
    assert "█" in text or "░" in text  # inline gauge glyphs


def test_build_table_status_labels_uppercased_and_styled() -> None:
    rows = [
        {"session_id": "a", "status": "active"},
        {"session_id": "b", "status": "slow"},
        {"session_id": "c", "status": "idle"},
        {"session_id": "d", "status": "ghost"},  # unknown -> plain, no style
    ]
    text = _render(build_top_table(rows, status_filter="all"))
    assert "ACTIVE" in text
    assert "SLOW" in text
    assert "IDLE" in text
    assert "GHOST" in text


def test_build_table_footer_has_keybinds_and_page() -> None:
    text = _render(build_top_table(_rows()))
    assert "quit" in text  # footer keybind hints
    assert "PAGE 1/1" in text


def test_build_table_paginates_when_page_size_given() -> None:
    table = build_top_table(_rows(), sort_key="mem_mb", page_size=2)
    assert table.row_count == 2  # only the first page renders
    text = _render(table)
    assert "PAGE 1/2" in text
    assert "3 session(s)" in text  # title still reports the full match count
