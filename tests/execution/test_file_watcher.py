"""Unit tests for the file watcher (MAH-80)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from openrtc.execution.file_watcher import FileChange


class TestFileChange:
    """The :class:`FileChange` dataclass is the event-payload contract."""

    def test_construction(self) -> None:
        change = FileChange(path=Path("/tmp/agent.py"), change_type="modified")
        assert change.path == Path("/tmp/agent.py")
        assert change.change_type == "modified"

    def test_equality_same_values(self) -> None:
        a = FileChange(path=Path("/tmp/agent.py"), change_type="modified")
        b = FileChange(path=Path("/tmp/agent.py"), change_type="modified")
        assert a == b

    def test_equality_different_paths(self) -> None:
        a = FileChange(path=Path("/tmp/a.py"), change_type="modified")
        b = FileChange(path=Path("/tmp/b.py"), change_type="modified")
        assert a != b

    def test_equality_different_change_types(self) -> None:
        a = FileChange(path=Path("/tmp/agent.py"), change_type="created")
        b = FileChange(path=Path("/tmp/agent.py"), change_type="modified")
        assert a != b

    def test_hashable_for_set_deduplication(self) -> None:
        a = FileChange(path=Path("/tmp/agent.py"), change_type="modified")
        b = FileChange(path=Path("/tmp/agent.py"), change_type="modified")
        c = FileChange(path=Path("/tmp/agent.py"), change_type="created")
        # Equal instances collapse in a set; unequal ones do not.
        assert {a, b, c} == {a, c}

    def test_frozen_rejects_mutation(self) -> None:
        change = FileChange(path=Path("/tmp/agent.py"), change_type="modified")
        with pytest.raises(dataclasses.FrozenInstanceError):
            change.path = Path("/tmp/other.py")  # type: ignore[misc]
