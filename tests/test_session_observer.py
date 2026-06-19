from __future__ import annotations

import pickle

from openrtc.observability.observer import (
    SessionInfo,
    SessionObserver,
    SessionOutcome,
    SessionStatus,
)


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
