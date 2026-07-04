"""MAH-86: end-to-end hot reload through the real stack (no LiveKit server).

Drives the real module_reloader + rebind + coordinator over actual agent files on
disk, faking only the AgentSession (which needs a live LiveKit runtime). This is
the "edit the file, live sessions swap" loop, verifiable in plain CI.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from livekit.agents import Agent

from openrtc.core.config import AgentConfig
from openrtc.core.discovery import _find_local_agent_subclass, _load_agent_module
from openrtc.observability.base_observer import SessionInfo
from openrtc.reload.base_reload import ReloadEvent
from openrtc.reload.coordinator import ReloadCoordinator
from openrtc.reload.pin import pin, unpin
from openrtc.reload.session_registry import LiveSessionRegistry
from openrtc.runtime.file_watcher import FileChange

_AGENT_SOURCE = """\
from livekit.agents import Agent


class E2EAgent(Agent):
    version = "{marker}"

    def __init__(self) -> None:
        super().__init__(instructions="marker {marker}")
"""


class _FakeSession:
    """Weak-referenceable session exposing what rebind touches."""

    def __init__(self, agent: Agent) -> None:
        self._agent = agent
        self.update_calls: list[Agent] = []

    @property
    def current_agent(self) -> Agent:
        return self._agent

    def update_agent(self, agent: Agent) -> None:
        self.update_calls.append(agent)
        self._agent = agent


def _write(path: Path, marker: str) -> None:
    path.write_text(_AGENT_SOURCE.format(marker=marker))


def _load(path: Path) -> type[Agent]:
    return _find_local_agent_subclass(_load_agent_module(path))


def _fixture(
    tmp_path: Path, n: int
) -> tuple[
    Path, AgentConfig, LiveSessionRegistry, list[_FakeSession], list[ReloadEvent]
]:
    path = tmp_path / "e2e_agent.py"
    _write(path, "v1")
    v1 = _load(path)
    config = AgentConfig(name="e2e", agent_cls=v1, source_path=path)
    registry = LiveSessionRegistry()
    sessions = [_FakeSession(v1()) for _ in range(n)]  # type: ignore[call-arg]
    for i, session in enumerate(sessions):
        info = SessionInfo(
            agent_name="e2e", room_name="r", job_id=f"j{i}", metadata={}, started_at=0.0
        )
        asyncio.run(registry.on_session_start(info, session))  # type: ignore[arg-type]
    events: list[ReloadEvent] = []
    return path, config, registry, sessions, events


def _fire(config, registry, events, path) -> None:  # type: ignore[no-untyped-def]
    coord = ReloadCoordinator({"e2e": config}, registry, report=events.append)
    asyncio.run(coord.on_change([FileChange(path=path, change_type="modified")]))


def test_edit_swaps_all_live_sessions(tmp_path: Path) -> None:
    path, config, registry, sessions, events = _fixture(tmp_path, 5)

    _write(path, "v2")
    _fire(config, registry, events, path)

    assert config.agent_cls.version == "v2"  # new sessions get v2
    for session in sessions:
        assert session.current_agent.version == "v2"  # live sessions swapped
    assert events[-1].status == "swapped"
    assert events[-1].sessions_swapped == 5


def test_syntax_error_keeps_every_session_on_the_old_class(tmp_path: Path) -> None:
    path, config, registry, sessions, events = _fixture(tmp_path, 3)

    path.write_text("class E2EAgent(Agent)\n    broken\n")  # SyntaxError
    _fire(config, registry, events, path)

    assert config.agent_cls.version == "v1"  # rolled back
    for session in sessions:
        assert session.current_agent.version == "v1"
        assert session.update_calls == []
    assert events[-1].status == "failed"


def test_pinned_session_is_left_on_the_old_class(tmp_path: Path) -> None:
    path, config, registry, sessions, events = _fixture(tmp_path, 3)
    pinned = sessions[0]
    pin(pinned)  # type: ignore[arg-type]
    try:
        _write(path, "v2")
        _fire(config, registry, events, path)

        assert pinned.current_agent.version == "v1"
        for session in sessions[1:]:
            assert session.current_agent.version == "v2"
        assert events[-1].sessions_swapped == 2
    finally:
        unpin(pinned)  # type: ignore[arg-type]
