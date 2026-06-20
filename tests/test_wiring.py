"""Composition root: build_session constructs from config; state stays picklable."""

from __future__ import annotations

import pickle
from types import SimpleNamespace

from openrtc.core.wiring import _PoolRuntimeState, build_session


def test_runtime_state_is_picklable() -> None:
    state = _PoolRuntimeState(agents={})
    assert isinstance(pickle.dumps(state), bytes)


def test_build_session_uses_resolved_config_and_prewarm_vad(monkeypatch) -> None:
    from openrtc.core import wiring

    config = SimpleNamespace(
        name="a", stt="s", llm="l", tts="t", session_kwargs={}, greeting=None
    )
    monkeypatch.setattr(wiring, "_resolve_agent_config", lambda agents, ctx: config)
    monkeypatch.setattr(wiring, "_build_session_kwargs", lambda kw, proc: {})
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
