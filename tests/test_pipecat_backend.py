"""The pipecat backend, verified against real pipecat via the run_test harness."""

from __future__ import annotations

from typing import Any

import pytest
from pipecat.frames.frames import CancelFrame, EndFrame, StartFrame, TextFrame
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.frame_processor import Frame, FrameDirection, FrameProcessor
from pipecat.tests.utils import run_test

from openrtc.backends.pipecat.observer import PipecatLifecycleObserver
from openrtc.observability.base_observer import (
    SessionInfo,
    SessionOutcome,
    SessionStatus,
)


class _RecordingObserver:
    """A SessionObserver that records the signals it receives."""

    def __init__(self) -> None:
        self.starts: list[Any] = []
        self.ends: list[SessionOutcome] = []

    async def on_session_start(self, info: SessionInfo, session: Any) -> None:
        self.starts.append(session)

    async def on_session_end(self, info: SessionInfo, outcome: SessionOutcome) -> None:
        self.ends.append(outcome)


def _info() -> SessionInfo:
    return SessionInfo(
        agent_name="bot",
        room_name="room-1",
        job_id="j1",
        metadata={"tenant": "default"},
        started_at=1.0,
    )


def _observer(recorder: _RecordingObserver, *, session: Any = "SESSION") -> Any:
    return PipecatLifecycleObserver(
        info=_info(), session=session, observers=[recorder], timeout=5.0
    )


def _pushed(frame: Frame) -> FramePushed:
    return FramePushed(
        source=None,  # type: ignore[arg-type]
        destination=None,  # type: ignore[arg-type]
        frame=frame,
        direction=FrameDirection.DOWNSTREAM,
        timestamp=0,
    )


class _Passthrough(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


@pytest.mark.asyncio
async def test_observer_emits_start_and_end_over_a_real_pipeline() -> None:
    # run_test sends a real StartFrame then EndFrame through a real PipelineRunner,
    # so this exercises genuine pipecat frame flow, not a mock.
    recorder = _RecordingObserver()
    await run_test(
        _Passthrough(),
        frames_to_send=[TextFrame("hello")],
        expected_down_frames=[TextFrame],
        observers=[_observer(recorder)],
    )
    assert recorder.starts == ["SESSION"]  # one start, carrying the live session
    assert len(recorder.ends) == 1
    assert recorder.ends[0].status is SessionStatus.SUCCESS


@pytest.mark.asyncio
async def test_cancel_frame_marks_the_session_cancelled() -> None:
    recorder = _RecordingObserver()
    observer = _observer(recorder, session=None)
    await observer.on_push_frame(_pushed(StartFrame()))
    await observer.on_push_frame(_pushed(CancelFrame()))
    assert len(recorder.ends) == 1
    assert recorder.ends[0].status is SessionStatus.CANCELLED


@pytest.mark.asyncio
async def test_end_without_start_is_skipped() -> None:
    recorder = _RecordingObserver()
    observer = _observer(recorder, session=None)
    # A pipeline torn down before it started must not report an end.
    await observer.on_push_frame(_pushed(EndFrame()))
    assert recorder.ends == []


@pytest.mark.asyncio
async def test_start_and_end_are_each_reported_once() -> None:
    recorder = _RecordingObserver()
    observer = _observer(recorder, session=None)
    # StartFrame / EndFrame cross several processor boundaries; report once each.
    await observer.on_push_frame(_pushed(StartFrame()))
    await observer.on_push_frame(_pushed(StartFrame()))
    await observer.on_push_frame(_pushed(EndFrame()))
    await observer.on_push_frame(_pushed(EndFrame()))
    assert len(recorder.starts) == 1
    assert len(recorder.ends) == 1
