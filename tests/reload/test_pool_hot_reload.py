"""MAH-85: AgentPool wiring for hot reload."""

from __future__ import annotations

from pathlib import Path

import pytest
from livekit.agents import Agent

from openrtc import AgentPool
from openrtc.reload.session_registry import LiveSessionRegistry


class _Agent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="x")


def _has_registry(pool: AgentPool) -> bool:
    return any(
        isinstance(o, LiveSessionRegistry) for o in pool._runtime_state.observers
    )


def test_hot_reload_disabled_by_default() -> None:
    pool = AgentPool()
    assert pool.enable_hot_reload is False
    assert not _has_registry(pool)
    assert pool._server._reload_on_change is None  # type: ignore[attr-defined]


def test_hot_reload_enabled_wires_registry_and_server() -> None:
    pool = AgentPool(enable_hot_reload=True)
    assert pool.enable_hot_reload is True
    assert _has_registry(pool)
    assert pool._server._reload_on_change is not None  # type: ignore[attr-defined]


def test_hot_reload_requires_coroutine_mode() -> None:
    with pytest.raises(ValueError, match="coroutine"):
        AgentPool(enable_hot_reload=True, isolation="process")


def test_watch_paths_are_forwarded_to_the_server() -> None:
    paths = [Path("/agents")]
    pool = AgentPool(enable_hot_reload=True, watch_paths=paths)
    assert pool._server._reload_watch_paths == paths  # type: ignore[attr-defined]


def test_registry_observer_tracks_a_started_session() -> None:
    import asyncio

    from openrtc.observability.base_observer import SessionInfo

    pool = AgentPool(enable_hot_reload=True)
    registry = next(
        o for o in pool._runtime_state.observers if isinstance(o, LiveSessionRegistry)
    )
    info = SessionInfo(
        agent_name="foo", room_name="r", job_id="j1", metadata={}, started_at=0.0
    )
    asyncio.run(registry.on_session_start(info, object()))  # type: ignore[arg-type]
    assert registry.active_count() == 1
