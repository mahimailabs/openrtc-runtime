"""MAH-84: the coordinator wires file changes to reload + rebind + report."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from livekit.agents import Agent

from openrtc.core.config import AgentConfig
from openrtc.reload.base_reload import ReloadEvent, ReloadResult
from openrtc.reload.coordinator import ReloadCoordinator
from openrtc.reload.session_registry import LiveSessionRegistry
from openrtc.runtime.file_watcher import FileChange


class OldAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="old")


class NewAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="new")


def _run(coord: ReloadCoordinator, changes: list[FileChange]) -> None:
    asyncio.run(coord.on_change(changes))


def test_modified_file_reloads_and_rebinds(tmp_path: Path) -> None:
    path = tmp_path / "foo.py"
    config = AgentConfig(name="foo", agent_cls=OldAgent, source_path=path)
    events: list[ReloadEvent] = []
    rebind_calls: list[tuple[str, type[Agent]]] = []

    coord = ReloadCoordinator(
        {"foo": config},
        LiveSessionRegistry(),
        report=events.append,
        reloader=lambda p, cur: ReloadResult(status="swapped", agent_cls=NewAgent),
        rebinder=lambda cfg, new_cls, reg, **kw: (
            rebind_calls.append((cfg.name, new_cls)) or 4  # type: ignore[func-returns-value]
        ),
        clock=iter([1.0, 1.02]).__next__,
    )

    _run(coord, [FileChange(path=path, change_type="modified")])

    assert rebind_calls == [("foo", NewAgent)]
    assert len(events) == 1
    event = events[0]
    assert event.agent_name == "foo"
    assert event.status == "swapped"
    assert event.sessions_swapped == 4
    assert event.duration_ms == pytest.approx(20.0)  # (1.02 - 1.0) * 1000


def test_failed_reload_reports_and_skips_rebind(tmp_path: Path) -> None:
    path = tmp_path / "foo.py"
    config = AgentConfig(name="foo", agent_cls=OldAgent, source_path=path)
    events: list[ReloadEvent] = []
    rebind_called = False

    def _rebind(cfg, new_cls, reg, **kw):  # type: ignore[no-untyped-def]
        nonlocal rebind_called
        rebind_called = True
        return 0

    coord = ReloadCoordinator(
        {"foo": config},
        LiveSessionRegistry(),
        report=events.append,
        reloader=lambda p, cur: ReloadResult(status="failed", error="foo.py:3: bad"),
        rebinder=_rebind,
    )

    _run(coord, [FileChange(path=path, change_type="modified")])

    assert rebind_called is False
    assert len(events) == 1
    assert events[0].status == "failed"
    assert events[0].error == "foo.py:3: bad"
    assert events[0].sessions_swapped == 0


def test_deleted_file_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "foo.py"
    config = AgentConfig(name="foo", agent_cls=OldAgent, source_path=path)
    events: list[ReloadEvent] = []
    reload_called = False

    def _reloader(p, cur):  # type: ignore[no-untyped-def]
        nonlocal reload_called
        reload_called = True
        return ReloadResult(status="swapped", agent_cls=NewAgent)

    coord = ReloadCoordinator(
        {"foo": config},
        LiveSessionRegistry(),
        report=events.append,
        reloader=_reloader,
        rebinder=lambda *a, **k: 0,
    )

    _run(coord, [FileChange(path=path, change_type="deleted")])

    assert reload_called is False
    assert events == []


def test_unmatched_path_does_nothing(tmp_path: Path) -> None:
    config = AgentConfig(
        name="foo", agent_cls=OldAgent, source_path=tmp_path / "foo.py"
    )
    events: list[ReloadEvent] = []

    coord = ReloadCoordinator(
        {"foo": config},
        LiveSessionRegistry(),
        report=events.append,
        reloader=lambda p, cur: ReloadResult(status="swapped", agent_cls=NewAgent),
        rebinder=lambda *a, **k: 0,
    )

    _run(coord, [FileChange(path=tmp_path / "other.py", change_type="modified")])

    assert events == []


def test_agent_without_source_path_is_not_watchable(tmp_path: Path) -> None:
    # Registered via pool.add() without a module path: not reloadable.
    config = AgentConfig(name="foo", agent_cls=OldAgent, source_path=None)
    events: list[ReloadEvent] = []

    coord = ReloadCoordinator(
        {"foo": config},
        LiveSessionRegistry(),
        report=events.append,
        reloader=lambda p, cur: ReloadResult(status="swapped", agent_cls=NewAgent),
        rebinder=lambda *a, **k: 0,
    )

    _run(coord, [FileChange(path=tmp_path / "foo.py", change_type="modified")])

    assert events == []


def test_default_report_does_not_raise(tmp_path: Path) -> None:
    # Constructed without an explicit report callback: uses the logging default.
    path = tmp_path / "foo.py"
    config = AgentConfig(name="foo", agent_cls=OldAgent, source_path=path)

    coord = ReloadCoordinator(
        {"foo": config},
        LiveSessionRegistry(),
        reloader=lambda p, cur: ReloadResult(status="swapped", agent_cls=NewAgent),
        rebinder=lambda *a, **k: 1,
    )

    _run(coord, [FileChange(path=path, change_type="modified")])
