"""MAH-82: atomically swap agent_cls and re-bind live sessions."""

from __future__ import annotations

import asyncio
from typing import Any

from livekit.agents import Agent

from openrtc.core.config import AgentConfig
from openrtc.observability.base_observer import SessionInfo
from openrtc.reload.rebind import rebind_agent
from openrtc.reload.session_registry import LiveSessionRegistry


class OldAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="old")


class NewAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="new")


class _FakeSession:
    """Minimal stand-in exposing the two members rebind touches."""

    def __init__(self, agent: Agent, *, fail: bool = False) -> None:
        self._agent = agent
        self._fail = fail
        self.update_calls: list[Agent] = []

    @property
    def current_agent(self) -> Agent:
        return self._agent

    def update_agent(self, agent: Agent) -> None:
        if self._fail:
            raise RuntimeError("update boom")
        self.update_calls.append(agent)
        self._agent = agent


def _register(reg: LiveSessionRegistry, name: str, session: object, job: str) -> None:
    info = SessionInfo(
        agent_name=name, room_name="r", job_id=job, metadata={}, started_at=0.0
    )
    asyncio.run(reg.on_session_start(info, session))  # type: ignore[arg-type]


def _config() -> AgentConfig:
    return AgentConfig(name="foo", agent_cls=OldAgent)


def test_rebinds_all_live_sessions() -> None:
    reg = LiveSessionRegistry()
    sessions = [_FakeSession(OldAgent()) for _ in range(5)]
    for i, s in enumerate(sessions):
        _register(reg, "foo", s, f"j{i}")
    config = _config()

    swapped = rebind_agent(config, NewAgent, reg)

    assert swapped == 5
    assert config.agent_cls is NewAgent
    for s in sessions:
        assert len(s.update_calls) == 1
        assert isinstance(s.update_calls[0], NewAgent)
        assert isinstance(s.current_agent, NewAgent)


def test_new_sessions_use_new_class() -> None:
    reg = LiveSessionRegistry()
    config = _config()

    rebind_agent(config, NewAgent, reg)

    # build_session instantiates config.agent_cls() per call.
    assert isinstance(config.agent_cls(), NewAgent)


def test_pinned_session_is_skipped() -> None:
    reg = LiveSessionRegistry()
    pinned = _FakeSession(OldAgent())
    others = [_FakeSession(OldAgent()) for _ in range(2)]
    for i, s in enumerate([pinned, *others]):
        _register(reg, "foo", s, f"j{i}")
    config = _config()

    swapped = rebind_agent(config, NewAgent, reg, is_pinned=lambda s: s is pinned)

    assert swapped == 2
    assert pinned.update_calls == []
    assert isinstance(pinned.current_agent, OldAgent)
    for s in others:
        assert isinstance(s.current_agent, NewAgent)


def test_session_already_on_new_class_is_skipped() -> None:
    reg = LiveSessionRegistry()
    already_new = _FakeSession(NewAgent())
    stale = _FakeSession(OldAgent())
    _register(reg, "foo", already_new, "j0")
    _register(reg, "foo", stale, "j1")
    config = _config()

    swapped = rebind_agent(config, NewAgent, reg)

    assert swapped == 1
    assert already_new.update_calls == []
    assert len(stale.update_calls) == 1


def test_update_failure_on_one_session_is_isolated() -> None:
    reg = LiveSessionRegistry()
    good = _FakeSession(OldAgent())
    bad = _FakeSession(OldAgent(), fail=True)
    _register(reg, "foo", good, "j0")
    _register(reg, "foo", bad, "j1")
    config = _config()

    swapped = rebind_agent(config, NewAgent, reg)

    assert swapped == 1
    assert config.agent_cls is NewAgent
    assert len(good.update_calls) == 1


def test_no_live_sessions_still_swaps_config() -> None:
    reg = LiveSessionRegistry()
    config = _config()

    swapped = rebind_agent(config, NewAgent, reg)

    assert swapped == 0
    assert config.agent_cls is NewAgent


def test_rebind_to_same_class_is_a_noop() -> None:
    reg = LiveSessionRegistry()
    session = _FakeSession(OldAgent())
    _register(reg, "foo", session, "j0")
    config = _config()

    swapped = rebind_agent(config, OldAgent, reg)

    assert swapped == 0
    assert session.update_calls == []


def test_only_sessions_of_this_agent_are_touched() -> None:
    reg = LiveSessionRegistry()
    mine = _FakeSession(OldAgent())
    other: Any = _FakeSession(OldAgent())
    _register(reg, "foo", mine, "j0")
    _register(reg, "bar", other, "j1")
    config = _config()

    rebind_agent(config, NewAgent, reg)

    assert isinstance(mine.current_agent, NewAgent)
    assert other.update_calls == []
