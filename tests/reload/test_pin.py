"""MAH-83: per-session opt-out from mid-flow class swaps."""

from __future__ import annotations

import asyncio

from livekit.agents import Agent

from openrtc.core.config import AgentConfig
from openrtc.observability.base_observer import SessionInfo
from openrtc.reload.pin import is_pinned, pin, pin_reload, unpin
from openrtc.reload.rebind import rebind_agent
from openrtc.reload.session_registry import LiveSessionRegistry


class OldAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="old")


class NewAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="new")


class _FakeSession:
    """Weak-referenceable session exposing what pin + rebind touch."""

    def __init__(self, agent: Agent) -> None:
        self._agent = agent
        self.update_calls: list[Agent] = []

    @property
    def current_agent(self) -> Agent:
        return self._agent

    def update_agent(self, agent: Agent) -> None:
        self.update_calls.append(agent)
        self._agent = agent


def _register(reg: LiveSessionRegistry, session: object, job: str) -> None:
    info = SessionInfo(
        agent_name="foo", room_name="r", job_id=job, metadata={}, started_at=0.0
    )
    asyncio.run(reg.on_session_start(info, session))  # type: ignore[arg-type]


def test_pin_and_unpin_toggle_state() -> None:
    session = _FakeSession(OldAgent())
    assert not is_pinned(session)
    pin(session)
    assert is_pinned(session)
    unpin(session)
    assert not is_pinned(session)


def test_unpin_is_idempotent() -> None:
    session = _FakeSession(OldAgent())
    unpin(session)  # never pinned; must not raise
    assert not is_pinned(session)


def test_pin_reload_context_manager_pins_then_releases() -> None:
    session = _FakeSession(OldAgent())
    with pin_reload(session):
        assert is_pinned(session)
    assert not is_pinned(session)


def test_pin_reload_releases_on_exception() -> None:
    session = _FakeSession(OldAgent())
    try:
        with pin_reload(session):
            assert is_pinned(session)
            raise ValueError("boom")
    except ValueError:
        pass
    assert not is_pinned(session)


def test_pinned_session_survives_rebind_via_real_predicate() -> None:
    reg = LiveSessionRegistry()
    pinned = _FakeSession(OldAgent())
    free = _FakeSession(OldAgent())
    _register(reg, pinned, "j0")
    _register(reg, free, "j1")
    config = AgentConfig(name="foo", agent_cls=OldAgent)

    with pin_reload(pinned):
        swapped = rebind_agent(config, NewAgent, reg, is_pinned=is_pinned)

    assert swapped == 1
    assert isinstance(pinned.current_agent, OldAgent)
    assert isinstance(free.current_agent, NewAgent)


def test_unpin_during_session_allows_next_swap() -> None:
    reg = LiveSessionRegistry()
    session = _FakeSession(OldAgent())
    _register(reg, session, "j0")
    config = AgentConfig(name="foo", agent_cls=OldAgent)

    pin(session)
    rebind_agent(config, NewAgent, reg, is_pinned=is_pinned)
    assert isinstance(session.current_agent, OldAgent)  # skipped while pinned

    unpin(session)

    # A later reload produces another class; the now-unpinned session swaps.
    class NewerAgent(Agent):
        def __init__(self) -> None:
            super().__init__(instructions="newer")

    rebind_agent(config, NewerAgent, reg, is_pinned=is_pinned)
    assert isinstance(session.current_agent, NewerAgent)


def test_pin_reload_is_public() -> None:
    import openrtc

    assert openrtc.pin_reload is pin_reload
    assert "pin_reload" in openrtc.__all__
