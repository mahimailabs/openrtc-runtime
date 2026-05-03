from __future__ import annotations

import sys
from pathlib import Path

import pytest
from livekit.agents import Agent

import openrtc.resources as resources_module
from openrtc.core.pool import AgentPool
from openrtc.resources import (
    ProcessResidentSetInfo,
    agent_disk_footprints,
    file_size_bytes,
    format_byte_size,
    get_process_resident_set_info,
    process_resident_set_bytes,
)


class TinyAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="hi")


def test_format_byte_size() -> None:
    assert format_byte_size(0) == "0 B"
    assert format_byte_size(512) == "512 B"
    assert format_byte_size(1024) == "1.0 KiB"
    assert format_byte_size(1024 * 1024) == "1.0 MiB"


def test_file_size_bytes_counts_bytes(tmp_path: Path) -> None:
    path = tmp_path / "x.txt"
    path.write_bytes(b"abc")
    assert file_size_bytes(path) == 3


def test_agent_disk_footprints_skips_unknown_paths() -> None:
    pool = AgentPool()
    pool.add("a", TinyAgent)
    cfg = pool.get("a")
    assert agent_disk_footprints([cfg]) == []


def test_process_resident_set_info_smoke() -> None:
    info = get_process_resident_set_info()
    assert info.metric in (
        "linux_vm_rss",
        "darwin_ru_max_rss",
        "unavailable",
    )
    assert len(info.description) > 5
    b = process_resident_set_bytes()
    assert b is None or isinstance(b, int)
    # Equality of info.bytes_value vs b is not asserted: each call re-reads
    # /proc or rusage, so values can differ between consecutive samples.


def test_process_resident_set_bytes_delegates_to_get_process_resident_set_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = ProcessResidentSetInfo(
        bytes_value=12345,
        metric="linux_vm_rss",
        description="stub",
    )
    monkeypatch.setattr(
        resources_module,
        "get_process_resident_set_info",
        lambda: fake,
    )
    assert process_resident_set_bytes() == 12345


def test_resident_set_descriptions_align_with_platform() -> None:
    """Guardrail: Linux vs macOS wording must stay distinct (see resources docs)."""
    info = get_process_resident_set_info()
    desc = info.description.lower()
    if sys.platform.startswith("linux"):
        assert info.metric == "linux_vm_rss"
        assert "vmrss" in desc or "/proc" in desc
    elif sys.platform == "darwin":
        assert info.metric == "darwin_ru_max_rss"
        assert "ru_maxrss" in desc or "getrusage" in desc
        assert "peak" in desc or "max" in desc or "not instantaneous" in desc
    else:
        assert info.metric == "unavailable"


def test_agent_disk_footprints_includes_registered_paths(tmp_path: Path) -> None:
    module = tmp_path / "mod.py"
    module.write_text("# test\n", encoding="utf-8")
    pool = AgentPool()
    pool.add("x", TinyAgent, source_path=module)
    fps = agent_disk_footprints([pool.get("x")])
    assert len(fps) == 1
    assert fps[0].name == "x"
    assert fps[0].path == module.resolve()
    assert fps[0].size_bytes == module.stat().st_size
