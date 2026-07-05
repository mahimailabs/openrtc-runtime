"""openrtc top command helpers: refresh/key handling + fetch/render (MAH-92)."""

from __future__ import annotations

import io
import tempfile
import uuid
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from openrtc.cli import app
from openrtc.cli.top_cli import (
    STATUS_FILTERS,
    apply_key,
    fetch_rows,
    next_status_filter,
    run_once,
    validate_refresh_hz,
)
from openrtc.observability.introspection import SessionRow
from openrtc.observability.introspection_ipc import IntrospectionServer


def _rows() -> list[SessionRow]:
    return [
        SessionRow("s1", "sales", "acme", 5.0, 120.0, 150.0, 42.0, "active", False),
        SessionRow("s2", "support", None, 3.0, 80.0, 90.0, 10.0, "slow", False),
    ]


def _short_socket() -> Path:
    return Path(tempfile.gettempdir()) / f"ortc-top-{uuid.uuid4().hex[:8]}.sock"


def test_validate_refresh_hz_accepts_in_range() -> None:
    assert validate_refresh_hz(1.0) == 1.0
    assert validate_refresh_hz(0.5) == 0.5
    assert validate_refresh_hz(10.0) == 10.0


def test_validate_refresh_hz_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="between"):
        validate_refresh_hz(0.4)
    with pytest.raises(ValueError, match="between"):
        validate_refresh_hz(11.0)


def test_next_status_filter_cycles_and_wraps() -> None:
    assert next_status_filter("all") == STATUS_FILTERS[1]
    assert next_status_filter(STATUS_FILTERS[-1]) == STATUS_FILTERS[0]
    assert next_status_filter("bogus") == STATUS_FILTERS[0]


def test_apply_key_quit_sort_filter_and_refresh() -> None:
    # q quits.
    assert apply_key("q", sort_key="mem_mb", status_filter="all")[2] is True
    # s cycles the sort key.
    assert apply_key("s", sort_key="mem_mb", status_filter="all") == (
        "cpu_pct",
        "all",
        False,
    )
    # f cycles the status filter.
    assert apply_key("f", sort_key="mem_mb", status_filter="all") == (
        "mem_mb",
        STATUS_FILTERS[1],
        False,
    )
    # r (refresh) and unknown keys leave state unchanged.
    assert apply_key("r", sort_key="mem_mb", status_filter="all") == (
        "mem_mb",
        "all",
        False,
    )
    assert apply_key("z", sort_key="mem_mb", status_filter="all") == (
        "mem_mb",
        "all",
        False,
    )


@pytest.mark.asyncio
async def test_fetch_rows_returns_none_when_no_pool() -> None:
    assert await fetch_rows(_short_socket(), timeout=0.5) is None


@pytest.mark.asyncio
async def test_run_once_renders_live_server_rows() -> None:
    socket_path = _short_socket()
    server = IntrospectionServer(snapshot_provider=_rows, socket_path=socket_path)
    await server.start()
    console = Console(file=io.StringIO(), width=200)
    try:
        code = await run_once(
            socket_path, sort_key="mem_mb", status_filter="all", console=console
        )
    finally:
        await server.aclose()
    assert code == 0
    text = console.file.getvalue()  # type: ignore[attr-defined]
    assert "sales" in text
    assert "support" in text


@pytest.mark.asyncio
async def test_run_once_agent_filter_narrows_rows() -> None:
    socket_path = _short_socket()
    server = IntrospectionServer(snapshot_provider=_rows, socket_path=socket_path)
    await server.start()
    console = Console(file=io.StringIO(), width=200)
    try:
        code = await run_once(
            socket_path,
            sort_key="mem_mb",
            status_filter="all",
            agent_filter="sales",
            console=console,
        )
    finally:
        await server.aclose()
    assert code == 0
    text = console.file.getvalue()  # type: ignore[attr-defined]
    assert "sales" in text
    assert "support" not in text


@pytest.mark.asyncio
async def test_run_once_reports_missing_pool() -> None:
    console = Console(file=io.StringIO(), width=200)
    code = await run_once(
        _short_socket(),
        sort_key="mem_mb",
        status_filter="all",
        console=console,
        timeout=0.5,
    )
    assert code == 1
    assert "No running openrtc pool" in console.file.getvalue()  # type: ignore[attr-defined]


def test_top_command_once_missing_pool_exits_nonzero() -> None:
    result = CliRunner().invoke(
        app, ["top", "--once", "--socket", str(_short_socket())]
    )
    assert result.exit_code == 1, result.output
    assert "No running openrtc pool" in result.output


def test_top_command_once_with_agent_flag() -> None:
    # Exercises the --agent plumbing through top_command (no pool -> exit 1).
    result = CliRunner().invoke(
        app, ["top", "--once", "--agent", "sales", "--socket", str(_short_socket())]
    )
    assert result.exit_code == 1, result.output


def test_top_command_rejects_bad_sort() -> None:
    result = CliRunner().invoke(app, ["top", "--once", "--sort", "bogus"])
    assert result.exit_code != 0
    assert "sort" in result.output.lower()


def test_top_command_rejects_bad_status() -> None:
    result = CliRunner().invoke(app, ["top", "--once", "--status", "bogus"])
    assert result.exit_code != 0
    assert "status" in result.output.lower()


def test_top_command_rejects_bad_refresh_rate() -> None:
    result = CliRunner().invoke(app, ["top", "--refresh-rate", "99"])
    assert result.exit_code != 0
    assert "between" in result.output.lower()
