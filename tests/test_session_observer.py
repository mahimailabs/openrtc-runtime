from __future__ import annotations

import asyncio
import logging
import pickle
import types

import pytest
from livekit.agents import Agent

from openrtc.observability.observer import (
    SessionInfo,
    SessionObserver,
    SessionOutcome,
    SessionStatus,
    _build_session_info,
    _build_session_outcome,
    _notify_session_end,
    _notify_session_start,
)


class _Agent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="x")


class _RecordingObserver:
    def __init__(self) -> None:
        self.starts: list[tuple[object, object]] = []
        self.ends: list[SessionOutcome] = []

    async def on_session_start(self, info: object, session: object) -> None:
        self.starts.append((info, session))

    async def on_session_end(self, info: object, outcome: SessionOutcome) -> None:
        self.ends.append(outcome)


def _fake_ctx(
    *,
    job_metadata: object = None,
    room_metadata: object = None,
    room_name: str = "general-room",
    job_id: str | None = None,
) -> types.SimpleNamespace:
    job = types.SimpleNamespace(metadata=job_metadata)
    if job_id is not None:
        job.id = job_id
    room = types.SimpleNamespace(metadata=room_metadata, name=room_name)
    return types.SimpleNamespace(job=job, room=room)


def test_session_info_is_frozen_and_picklable() -> None:
    info = SessionInfo(
        agent_name="restaurant",
        room_name="restaurant-call-1",
        job_id="job-1",
        metadata={"tenant": "acme"},
        started_at=1.0,
    )
    assert info.agent_name == "restaurant"
    assert info.metadata["tenant"] == "acme"
    round_tripped = pickle.loads(pickle.dumps(info))
    assert round_tripped == info


def test_session_outcome_carries_status_and_error() -> None:
    err = ValueError("boom")
    outcome = SessionOutcome(
        status=SessionStatus.FAILED,
        error=err,
        ended_at=2.0,
        duration_seconds=1.0,
    )
    assert outcome.status is SessionStatus.FAILED
    assert outcome.error is err
    assert pickle.loads(pickle.dumps(SessionStatus.SUCCESS)) is SessionStatus.SUCCESS


def test_session_observer_is_runtime_checkable() -> None:
    class Good:
        async def on_session_start(self, info: object, session: object) -> None: ...
        async def on_session_end(self, info: object, outcome: object) -> None: ...

    class Bad:
        async def on_session_start(self, info: object, session: object) -> None: ...

    assert isinstance(Good(), SessionObserver)
    assert not isinstance(Bad(), SessionObserver)


def test_build_session_info_parses_and_merges_metadata() -> None:
    ctx = _fake_ctx(
        job_metadata='{"tenant": "acme", "agent": "restaurant"}',
        room_metadata={"tenant": "ignored", "region": "eu"},
        room_name="restaurant-1",
        job_id="job-9",
    )
    info = _build_session_info("restaurant", ctx)
    assert info.agent_name == "restaurant"
    assert info.room_name == "restaurant-1"
    assert info.job_id == "job-9"
    assert info.metadata == {"tenant": "acme", "agent": "restaurant", "region": "eu"}
    assert info.started_at > 0


def test_build_session_info_defends_missing_attrs() -> None:
    # FakeJob in the repo has no ``id``; a missing room name or job id must not raise.
    ctx = _fake_ctx(job_metadata="not-json", room_name="")
    info = _build_session_info("agent", ctx)
    assert info.room_name == ""
    assert info.job_id == ""
    assert info.metadata == {}


def test_build_session_outcome_classifies_status() -> None:
    info = SessionInfo("a", "r", "j", {}, started_at=0.0)
    assert _build_session_outcome(info, None).status is SessionStatus.SUCCESS
    failed = _build_session_outcome(info, ValueError("x"))
    assert failed.status is SessionStatus.FAILED
    assert isinstance(failed.error, ValueError)
    cancelled = _build_session_outcome(info, asyncio.CancelledError())
    assert cancelled.status is SessionStatus.CANCELLED
    assert cancelled.duration_seconds >= 0.0


def test_notify_start_and_end_call_observers() -> None:
    obs = _RecordingObserver()
    info = SessionInfo("a", "r", "j", {}, started_at=0.0)
    session = object()
    asyncio.run(_notify_session_start([obs], info, session, timeout=5.0))
    outcome = _build_session_outcome(info, None)
    asyncio.run(_notify_session_end([obs], info, outcome, timeout=5.0))
    assert obs.starts == [(info, session)]
    assert obs.ends == [outcome]


def test_notify_is_noop_for_empty_observers() -> None:
    info = SessionInfo("a", "r", "j", {}, started_at=0.0)
    asyncio.run(_notify_session_start([], info, object(), timeout=5.0))
    asyncio.run(
        _notify_session_end([], info, _build_session_outcome(info, None), timeout=5.0)
    )


def test_notify_swallows_observer_exception(caplog: pytest.LogCaptureFixture) -> None:
    class _Raises:
        async def on_session_start(self, info: object, session: object) -> None:
            raise RuntimeError("observer boom")

        async def on_session_end(self, info: object, outcome: object) -> None:
            raise RuntimeError("observer boom")

    info = SessionInfo("a", "r", "j", {}, started_at=0.0)
    with caplog.at_level(logging.WARNING, logger="openrtc"):
        asyncio.run(_notify_session_start([_Raises()], info, object(), timeout=5.0))
    assert "failed on_session_start" in caplog.text


def test_notify_enforces_timeout(caplog: pytest.LogCaptureFixture) -> None:
    class _Slow:
        async def on_session_start(self, info: object, session: object) -> None:
            await asyncio.sleep(10.0)

        async def on_session_end(self, info: object, outcome: object) -> None:
            await asyncio.sleep(10.0)

    info = SessionInfo("a", "r", "j", {}, started_at=0.0)
    with caplog.at_level(logging.WARNING, logger="openrtc"):
        asyncio.run(_notify_session_start([_Slow()], info, object(), timeout=0.01))
    assert "failed on_session_start" in caplog.text
