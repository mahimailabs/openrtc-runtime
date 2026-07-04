"""Composition root: build_session constructs from config; state stays picklable."""

from __future__ import annotations

import pickle
from types import SimpleNamespace

import pytest

from openrtc.core.wiring import _PoolRuntimeState, build_session


def test_runtime_state_is_picklable() -> None:
    state = _PoolRuntimeState(agents={})
    assert isinstance(pickle.dumps(state), bytes)


class _RecordingServer:
    """SessionRuntime stub that records what wire_pool passes to rtc_session."""

    def __init__(self) -> None:
        self.setup_fnc = None
        self.rtc_session_kwargs: dict[str, object] = {}
        self.handler = None

    def rtc_session(self, **kwargs: object):
        self.rtc_session_kwargs = kwargs

        def decorator(function):
            self.handler = function
            return function

        return decorator


def test_wire_pool_threads_request_fnc_to_rtc_session() -> None:
    from openrtc.core.wiring import wire_pool

    async def _filter(_req: object) -> None:
        return None

    server = _RecordingServer()
    state = _PoolRuntimeState(agents={})
    wire_pool(server, state, request_fnc=_filter)

    assert server.rtc_session_kwargs["on_request"] is _filter
    assert server.handler is not None
    assert server.setup_fnc is not None


def test_wire_pool_defaults_request_fnc_to_none() -> None:
    from openrtc.core.wiring import wire_pool

    server = _RecordingServer()
    state = _PoolRuntimeState(agents={})
    wire_pool(server, state)

    assert server.rtc_session_kwargs["on_request"] is None


@pytest.mark.asyncio
async def test_run_session_connects_before_starting(monkeypatch) -> None:
    """ctx.connect() must be awaited before session.start().

    on_enter fires as a detached task during session.start() (livekit schedules
    it with wait_on_enter=False). If the room is not connected yet, any on_enter
    that touches room.local_participant raises "cannot access local participant
    before connecting". Connecting first guarantees a connected room before
    on_enter runs. This records the call order and fails if start precedes
    connect.
    """
    from openrtc.core import wiring

    order: list[str] = []

    config = SimpleNamespace(
        name="a",
        stt="s",
        llm="l",
        tts="t",
        session_kwargs={},
        greeting=None,
        agent_cls=lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(wiring, "_resolve_agent_config", lambda agents, ctx: config)
    monkeypatch.setattr(wiring, "_build_session_kwargs", lambda kw, proc, ie=None: {})

    class _FakeSession:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def start(self, **kwargs: object) -> None:
            order.append("start")

        async def generate_reply(self, **kwargs: object) -> None:
            order.append("greet")

    monkeypatch.setattr(wiring, "AgentSession", _FakeSession)

    async def _connect() -> None:
        order.append("connect")

    proc = SimpleNamespace(userdata={"vad": "VAD", "turn_detection_factory": object()})
    ctx = SimpleNamespace(
        proc=proc,
        room=SimpleNamespace(name="a-1", metadata=None),
        job=SimpleNamespace(id="j", metadata=None),
        connect=_connect,
    )

    state = _PoolRuntimeState(agents={"a": config})
    await wiring.run_session(state, ctx)

    assert order == ["connect", "start"], order


def test_build_session_uses_resolved_config_and_prewarm_vad(monkeypatch) -> None:
    from openrtc.core import wiring

    config = SimpleNamespace(
        name="a", stt="s", llm="l", tts="t", session_kwargs={}, greeting=None
    )
    monkeypatch.setattr(wiring, "_resolve_agent_config", lambda agents, ctx: config)
    monkeypatch.setattr(wiring, "_build_session_kwargs", lambda kw, proc, ie=None: {})
    captured = {}

    class _FakeSession:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(wiring, "AgentSession", _FakeSession)
    proc = SimpleNamespace(userdata={"vad": "VAD", "turn_detection_factory": object()})
    ctx = SimpleNamespace(
        proc=proc,
        room=SimpleNamespace(name="a-1", metadata=None),
        job=SimpleNamespace(id="j", metadata=None),
    )

    state = _PoolRuntimeState(agents={"a": config})
    session, resolved, info = build_session(state, ctx)

    assert resolved is config
    assert captured["vad"] == "VAD"
    assert info.agent_name == "a"
