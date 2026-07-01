"""MAH-82: track live AgentSessions via the SessionObserver seam."""

from __future__ import annotations

import asyncio

from openrtc.observability.base_observer import (
    SessionInfo,
    SessionObserver,
    SessionOutcome,
    SessionStatus,
)
from openrtc.reload.session_registry import LiveSessionRegistry


def _info(job_id: str, agent_name: str) -> SessionInfo:
    return SessionInfo(
        agent_name=agent_name,
        room_name="room",
        job_id=job_id,
        metadata={},
        started_at=0.0,
    )


def _outcome() -> SessionOutcome:
    return SessionOutcome(
        status=SessionStatus.SUCCESS,
        error=None,
        ended_at=1.0,
        duration_seconds=1.0,
    )


def test_start_registers_session() -> None:
    reg = LiveSessionRegistry()
    session = object()
    asyncio.run(reg.on_session_start(_info("j1", "foo"), session))  # type: ignore[arg-type]

    assert reg.active_count() == 1
    assert reg.sessions_for("foo") == [session]
    assert reg.sessions_for("bar") == []


def test_end_removes_session() -> None:
    reg = LiveSessionRegistry()
    session = object()
    asyncio.run(reg.on_session_start(_info("j1", "foo"), session))  # type: ignore[arg-type]
    asyncio.run(reg.on_session_end(_info("j1", "foo"), _outcome()))

    assert reg.active_count() == 0
    assert reg.sessions_for("foo") == []


def test_sessions_for_filters_by_agent_name() -> None:
    reg = LiveSessionRegistry()
    a, b, c = object(), object(), object()
    asyncio.run(reg.on_session_start(_info("j1", "foo"), a))  # type: ignore[arg-type]
    asyncio.run(reg.on_session_start(_info("j2", "foo"), b))  # type: ignore[arg-type]
    asyncio.run(reg.on_session_start(_info("j3", "bar"), c))  # type: ignore[arg-type]

    assert {id(s) for s in reg.sessions_for("foo")} == {id(a), id(b)}
    assert reg.sessions_for("bar") == [c]
    assert reg.active_count() == 3


def test_end_without_start_is_a_noop() -> None:
    reg = LiveSessionRegistry()
    # A session that fails before going live ends with no paired start.
    asyncio.run(reg.on_session_end(_info("j9", "foo"), _outcome()))
    assert reg.active_count() == 0


def test_satisfies_session_observer_protocol() -> None:
    assert isinstance(LiveSessionRegistry(), SessionObserver)
