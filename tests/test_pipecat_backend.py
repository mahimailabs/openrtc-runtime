"""The pipecat backend, verified against real pipecat via the run_test harness."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pipecat.frames.frames import CancelFrame, EndFrame, StartFrame, TextFrame
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.frame_processor import Frame, FrameDirection, FrameProcessor
from pipecat.tests.utils import run_test

from openrtc.backends.pipecat.backend import PipecatBackend, build_backend
from openrtc.backends.pipecat.dispatch import dispatch_pipecat_call
from openrtc.backends.pipecat.observer import PipecatLifecycleObserver
from openrtc.backends.pipecat.session import build_pipecat_session
from openrtc.backends.pipecat.testing import simulate_call
from openrtc.core.backend import Backend
from openrtc.core.session_view import SessionView, for_livekit
from openrtc.core.wiring import _PoolRuntimeState
from openrtc.observability.base_observer import (
    SessionInfo,
    SessionOutcome,
    SessionStatus,
)
from openrtc.runtime.registry import ServerParams


class _RecordingObserver:
    """A SessionObserver that records the signals it receives."""

    def __init__(self) -> None:
        self.starts: list[Any] = []
        self.start_infos: list[SessionInfo] = []
        self.ends: list[SessionOutcome] = []

    async def on_session_start(self, info: SessionInfo, session: Any) -> None:
        self.starts.append(session)
        self.start_infos.append(info)

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
async def test_simulate_call_drives_the_full_lifecycle_with_the_observer() -> None:
    # The call-simulation harness runs a genuine PipelineWorker/WorkerRunner:
    # StartFrame (connect), the user frame, then EndFrame (disconnect).
    recorder = _RecordingObserver()
    captured = await simulate_call(
        [_Passthrough()],
        user_frames=[TextFrame("hello")],
        observers=[_observer(recorder)],
    )
    assert any(
        isinstance(frame, TextFrame) and frame.text == "hello" for frame in captured
    )
    assert recorder.starts == ["SESSION"]
    assert len(recorder.ends) == 1
    assert recorder.ends[0].status is SessionStatus.SUCCESS


def _view(session: Any = "SESSION") -> SessionView:
    return for_livekit(
        SimpleNamespace(
            room=SimpleNamespace(name="room-1", metadata=None),
            job=SimpleNamespace(id="j1", metadata=None),
            _primary_agent_session=session,
        )
    )


@pytest.mark.asyncio
async def test_session_builder_invokes_the_builder_and_attaches_observability() -> None:
    view = _view(session="SESSION")
    seen: list[SessionView] = []

    def builder(call_view: SessionView) -> list[FrameProcessor]:
        seen.append(call_view)
        return [_Passthrough()]

    recorder = _RecordingObserver()
    processors, observer = build_pipecat_session(
        builder, view, info=_info(), observers=[recorder], timeout=5.0
    )
    assert seen == [view]  # the builder receives the call's neutral view

    # The returned session runs a genuine call lifecycle end-to-end.
    captured = await simulate_call(
        processors, user_frames=[TextFrame("hi")], observers=[observer]
    )
    assert any(isinstance(f, TextFrame) and f.text == "hi" for f in captured)
    assert recorder.starts == ["SESSION"]  # observer bound to view.session
    assert recorder.ends[0].status is SessionStatus.SUCCESS


# --- dispatch: route a call to its builder ---------------------------------


def _view_routing_to(agent: str) -> SessionView:
    return for_livekit(
        SimpleNamespace(
            room=SimpleNamespace(name="room-1", metadata=None),
            job=SimpleNamespace(id="j1", metadata=f'{{"agent": "{agent}"}}'),
            _primary_agent_session="SESSION",
        )
    )


def _builder_recording(label: str, seen: list[str]) -> Any:
    def builder(view: SessionView) -> list[FrameProcessor]:
        seen.append(label)
        return [_Passthrough()]

    return builder


@pytest.mark.asyncio
async def test_dispatch_routes_to_the_builder_and_builds_the_session() -> None:
    seen: list[str] = []
    builders = {
        "sales": _builder_recording("sales", seen),
        "support": _builder_recording("support", seen),
    }
    recorder = _RecordingObserver()
    processors, observer = dispatch_pipecat_call(
        _view_routing_to("support"), builders, observers=[recorder], timeout=5.0
    )
    assert seen == ["support"]  # only the routed builder is invoked

    captured = await simulate_call(
        processors, user_frames=[TextFrame("hi")], observers=[observer]
    )
    assert any(isinstance(f, TextFrame) for f in captured)
    assert recorder.start_infos[0].agent_name == "support"


def test_dispatch_rejects_when_no_agents_registered() -> None:
    with pytest.raises(RuntimeError, match="No agents are registered"):
        dispatch_pipecat_call(_view(), {}, observers=[], timeout=5.0)


def test_dispatch_rejects_an_unregistered_agent() -> None:
    builders = {"sales": _builder_recording("sales", [])}
    with pytest.raises(ValueError, match="Unknown agent 'ghost'"):
        dispatch_pipecat_call(
            _view_routing_to("ghost"), builders, observers=[], timeout=5.0
        )


# --- PipecatBackend + registry ---------------------------------------------

_PARAMS = ServerParams(
    max_concurrent_sessions=10, consecutive_failure_limit=3, drain_timeout=30
)


def test_pipecat_registered_in_the_backend_registry() -> None:
    from openrtc.backends.registry import resolve_backend_builder

    assert resolve_backend_builder("pipecat") is build_backend


def test_build_backend_returns_a_pipecat_backend() -> None:
    backend = build_backend(_PARAMS, "coroutine")
    assert isinstance(backend, PipecatBackend)
    assert isinstance(backend, Backend)  # satisfies the neutral Backend seam
    assert backend.raw_server is None


@pytest.mark.asyncio
async def test_pipecat_backend_wires_registers_and_dispatches() -> None:
    backend = PipecatBackend(_PARAMS)
    recorder = _RecordingObserver()
    # wire threads the neutral runtime state (observers, router, timeout) in.
    backend.wire(
        _PoolRuntimeState(agents={}, observers=[recorder], observer_timeout=5.0),
        None,
        agent_name=None,
    )
    seen: list[str] = []
    backend.register("support", _builder_recording("support", seen))
    processors, observer = backend.dispatch(_view_routing_to("support"))
    assert seen == ["support"]

    captured = await simulate_call(
        processors, user_frames=[TextFrame("hi")], observers=[observer]
    )
    assert any(isinstance(f, TextFrame) for f in captured)
    assert recorder.start_infos[0].agent_name == "support"  # observers came from wire


def test_pipecat_backend_run_documents_the_transport_boundary() -> None:
    with pytest.raises(NotImplementedError, match="serving front"):
        PipecatBackend(_PARAMS).run()


def test_pipecat_backend_drain_is_idempotent() -> None:
    backend = PipecatBackend(_PARAMS)
    assert backend.draining is False
    assert backend.begin_drain() is True
    assert backend.draining is True
    assert backend.begin_drain() is False  # already draining


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
