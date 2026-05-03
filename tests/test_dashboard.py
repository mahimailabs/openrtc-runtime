"""Unit tests for ``openrtc.cli.dashboard`` rendering helpers.

The CLI integration tests cover the happy paths via ``CliRunner``; this
module pins the small pure helpers (`_format_percent`, `_memory_style`,
`_truncate_cell`) and the ``plain`` print-output branches that the
integration tests don't exercise individually.
"""

from __future__ import annotations

from typing import Any

import pytest
from livekit.agents import Agent

from openrtc import AgentPool
from openrtc.cli.dashboard import (
    _format_percent,
    _memory_style,
    _truncate_cell,
    print_list_plain,
    print_list_rich_table,
    print_resource_summary_plain,
    print_resource_summary_rich,
)
from openrtc.observability.snapshot import ProcessResidentSetInfo


class TinyAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="x")


def test_format_percent_returns_dash_when_inputs_missing() -> None:
    assert _format_percent(None, 100) == "—"
    assert _format_percent(50, None) == "—"
    assert _format_percent(50, 0) == "—"


def test_format_percent_rounds_ratio_to_zero_decimals() -> None:
    assert _format_percent(33, 100) == "33%"
    assert _format_percent(666, 1000) == "67%"


def test_memory_style_returns_white_when_value_unknown() -> None:
    assert _memory_style(None) == "white"


def test_memory_style_thresholds() -> None:
    assert _memory_style(100 * 1024 * 1024) == "green"
    assert _memory_style(800 * 1024 * 1024) == "yellow"
    assert _memory_style(2 * 1024 * 1024 * 1024) == "red"


def test_truncate_cell_appends_ellipsis_when_exceeding_max_length() -> None:
    assert _truncate_cell("x" * 40, max_len=10) == "x" * 9 + "…"


def test_truncate_cell_passes_short_strings_through_unchanged() -> None:
    assert _truncate_cell("short", max_len=10) == "short"


def test_print_list_rich_table_renders_dash_for_missing_source_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A registered agent without ``source_path`` shows ``—`` in the source column."""
    pool = AgentPool()
    pool.add("a", TinyAgent)

    print_list_rich_table([pool.get("a")], resources=True)

    out = capsys.readouterr().out
    assert "—" in out


def test_print_list_plain_includes_source_size_for_known_paths(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Any,
) -> None:
    """``print_list_plain`` appends ``source_size=...`` for agents with a path."""
    module = tmp_path / "mod.py"
    module.write_text("# test\n", encoding="utf-8")
    pool = AgentPool()
    pool.add("a", TinyAgent, source_path=module)

    print_list_plain([pool.get("a")], resources=True)

    out = capsys.readouterr().out
    assert "source_size=" in out
    assert "Resource summary" in out


def test_print_resource_summary_plain_emits_known_path_caveat(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When some agents lack a path, the summary prints the per-path-known caveat."""
    pool = AgentPool()
    pool.add("known-path", TinyAgent)

    print_resource_summary_plain([pool.get("known-path")])

    out = capsys.readouterr().out
    assert "per-agent source size" in out
    assert "OpenRTC runs every agent" in out


def test_print_resource_summary_plain_handles_unavailable_rss(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When RSS is unavailable, the unavailable-metric branch fires."""
    from openrtc.cli import dashboard as dashboard_module

    monkeypatch.setattr(
        dashboard_module,
        "get_process_resident_set_info",
        lambda: ProcessResidentSetInfo(
            bytes_value=None, metric="unavailable", description="no metric"
        ),
    )

    pool = AgentPool()
    pool.add("a", TinyAgent)
    print_resource_summary_plain([pool.get("a")])

    out = capsys.readouterr().out
    assert "Resident memory metric unavailable" in out


def test_build_list_json_payload_omits_resource_keys_when_resources_disabled() -> None:
    """Branch: ``include_resources=False`` skips both per-agent and summary resource keys."""
    from openrtc.cli.dashboard import build_list_json_payload

    pool = AgentPool()
    pool.add("a", TinyAgent)

    payload = build_list_json_payload([pool.get("a")], include_resources=False)

    assert payload["agents"][0].keys() == {
        "name",
        "class",
        "stt",
        "llm",
        "tts",
        "greeting",
    }
    assert "resource_summary" not in payload


def test_print_resource_summary_rich_handles_unavailable_rss(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The Rich summary uses the alternate "unavailable" string when RSS is None."""
    from openrtc.cli import dashboard as dashboard_module

    monkeypatch.setattr(
        dashboard_module,
        "get_process_resident_set_info",
        lambda: ProcessResidentSetInfo(
            bytes_value=None, metric="unavailable", description="no metric"
        ),
    )

    pool = AgentPool()
    pool.add("a", TinyAgent)
    print_resource_summary_rich([pool.get("a")])

    out = capsys.readouterr().out
    assert "Resident memory metric unavailable" in out
