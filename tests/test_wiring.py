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


def test_wire_pool_registers_session_end_hook() -> None:
    from openrtc.core.wiring import run_session_end, wire_pool

    server = _RecordingServer()
    wire_pool(server, _PoolRuntimeState(agents={}))

    assert server.rtc_session_kwargs["on_session_end"] is run_session_end


def test_is_held_open_session_predicate() -> None:
    from openrtc.core.wiring import _is_held_open_session

    # Real (non-fake) job with a primary session: held open.
    assert (
        _is_held_open_session(SimpleNamespace(_primary_agent_session=object())) is True
    )
    # No primary session (setup-only entrypoint): not held.
    assert _is_held_open_session(SimpleNamespace(_primary_agent_session=None)) is False
    # Fake job (simulate_job): completes on return, not held.
    assert (
        _is_held_open_session(
            SimpleNamespace(_primary_agent_session=object(), is_fake_job=lambda: True)
        )
        is False
    )


class _RecordObserver:
    """SessionObserver that records the order of start/end notifications."""

    def __init__(self) -> None:
        self.events: list[str] = []

    async def on_session_start(self, info: object, session: object) -> None:
        self.events.append("start")

    async def on_session_end(self, info: object, outcome: object) -> None:
        self.events.append("end")


@pytest.mark.asyncio
async def test_run_session_defers_end_for_held_open_session(monkeypatch) -> None:
    """A held-open coroutine session reports its end via run_session_end (MAH-166).

    While the call is live the session stays counted (active_sessions == 1) and
    on_session_end has not fired; the executor's end hook fires it at real
    disconnect.
    """
    from openrtc.core import wiring

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
            pass

    monkeypatch.setattr(wiring, "AgentSession", _FakeSession)

    async def _connect() -> None:
        pass

    obs = _RecordObserver()
    ctx = SimpleNamespace(
        proc=SimpleNamespace(
            userdata={"vad": "VAD", "turn_detection_factory": object()}
        ),
        room=SimpleNamespace(name="a-1", metadata=None),
        job=SimpleNamespace(id="j", metadata=None),
        connect=_connect,
        inference_executor=None,
        _openrtc_defer_session_end=True,
        _primary_agent_session=object(),  # livekit set it during start()
    )
    state = _PoolRuntimeState(agents={"a": config}, observers=[obs])

    await wiring.run_session(state, ctx)

    # End deferred: start fired, end did NOT, and the session is still counted.
    assert obs.events == ["start"]
    assert callable(ctx._openrtc_session_finish)
    assert state.metrics.snapshot(registered_agents=1).active_sessions == 1

    # The executor's end hook fires the deferred end at the real disconnect.
    await wiring.run_session_end(ctx)

    assert obs.events == ["start", "end"]
    assert ctx._openrtc_session_finish is None
    assert state.metrics.snapshot(registered_agents=1).active_sessions == 0


@pytest.mark.asyncio
async def test_run_session_end_is_noop_without_deferred_finish() -> None:
    from openrtc.core.wiring import run_session_end

    # No _openrtc_session_finish stashed (fake job, process mode, direct call):
    # the hook is a no-op and never double-fires.
    await run_session_end(SimpleNamespace())


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
