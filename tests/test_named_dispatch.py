"""Named-worker (explicit LiveKit dispatch) support on AgentPool.

By default an ``AgentPool`` registers an *unnamed* worker (automatic dispatch):
LiveKit offers it every room and the pool's own router picks the agent. That
breaks a frontend or SIP rule that requests an *explicit* dispatch
(``agent_name="realty"``), because LiveKit routes an explicit dispatch only to
workers registered under that name. Setting ``AgentPool(agent_name=...)``
registers a named worker so explicit dispatch (and its per-dispatch metadata)
keeps working.
"""

from __future__ import annotations

from typing import Any

import pytest
from livekit.agents import Agent

from openrtc import AgentPool


class _Agent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="realty")


def test_agent_name_defaults_to_none_automatic_dispatch() -> None:
    pool = AgentPool(agent=_Agent, enable_introspection=False)
    assert pool.agent_name is None  # unnamed worker == automatic dispatch


def test_agent_name_is_exposed_when_set() -> None:
    pool = AgentPool(agent=_Agent, agent_name="realty", enable_introspection=False)
    assert pool.agent_name == "realty"


def test_agent_name_is_stripped() -> None:
    pool = AgentPool(agent=_Agent, agent_name="  realty  ", enable_introspection=False)
    assert pool.agent_name == "realty"


def test_blank_agent_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="agent_name must be a non-empty string"):
        AgentPool(agent=_Agent, agent_name="   ", enable_introspection=False)


def test_pool_threads_agent_name_to_wire_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """The regression guard: the pool must actually hand the name to wire_pool,
    which is what reaches ``server.rtc_session(agent_name=...)``. The original
    bug was that the name never left the constructor."""
    import openrtc.core.pool as pool_mod

    captured: dict[str, Any] = {}
    real = pool_mod.wire_pool

    def _spy(server: Any, state: Any, request_fnc: Any = None, **kwargs: Any) -> Any:
        captured["agent_name"] = kwargs.get("agent_name")
        return real(server, state, request_fnc, **kwargs)

    monkeypatch.setattr(pool_mod, "wire_pool", _spy)
    AgentPool(agent=_Agent, agent_name="realty", enable_introspection=False)

    assert captured["agent_name"] == "realty"
