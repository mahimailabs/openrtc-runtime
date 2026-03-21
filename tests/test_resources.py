from __future__ import annotations

from pathlib import Path

from livekit.agents import Agent

from openrtc.pool import AgentPool
from openrtc.resources import (
    agent_disk_footprints,
    file_size_bytes,
    format_byte_size,
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
