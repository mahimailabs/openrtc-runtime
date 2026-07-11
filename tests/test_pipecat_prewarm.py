"""SharedPrewarm and PipecatCallView: the pipecat shared-prewarm primitives."""

from __future__ import annotations

import builtins
from typing import Any

import pytest

from openrtc.backends.pipecat.call_view import PipecatCallView
from openrtc.backends.pipecat.prewarm import (
    SharedPrewarm,
    _default_turn_factory,
    _default_vad_factory,
)
from openrtc.core.session_view import SessionView

# --- SharedPrewarm: load once, share across accesses ------------------------


def test_shared_prewarm_builds_the_vad_once_and_caches_it() -> None:
    calls = 0

    def vad_factory() -> object:
        nonlocal calls
        calls += 1
        return object()

    prewarm = SharedPrewarm(vad_factory=vad_factory, turn_factory=object)
    first = prewarm.vad
    second = prewarm.vad
    assert first is second  # same instance shared across accesses
    assert calls == 1  # factory ran exactly once


def test_shared_prewarm_builds_the_turn_once_and_caches_it() -> None:
    calls = 0

    def turn_factory() -> object:
        nonlocal calls
        calls += 1
        return object()

    prewarm = SharedPrewarm(vad_factory=object, turn_factory=turn_factory)
    first = prewarm.turn
    second = prewarm.turn
    assert first is second
    assert calls == 1


def test_shared_prewarm_caches_a_none_result_without_reloading() -> None:
    # None is a legitimate factory result, distinct from the not-loaded marker.
    calls = 0

    def vad_factory() -> None:
        nonlocal calls
        calls += 1
        # falls through: returns None, a legitimate cached value

    prewarm = SharedPrewarm(vad_factory=vad_factory, turn_factory=object)
    assert prewarm.vad is None
    assert prewarm.vad is None
    assert calls == 1  # cached, not re-loaded (distinct from the _UNSET sentinel)


# --- default factories: real pipecat load, and a clear error when it is absent


def test_default_vad_factory_builds_a_real_silero_analyzer() -> None:
    from pipecat.audio.vad.silero import SileroVADAnalyzer

    assert isinstance(_default_vad_factory(), SileroVADAnalyzer)


def test_default_turn_factory_builds_a_real_smart_turn_analyzer() -> None:
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import (
        LocalSmartTurnAnalyzerV3,
    )

    assert isinstance(_default_turn_factory(), LocalSmartTurnAnalyzerV3)


def test_default_vad_factory_raises_a_clear_error_when_pipecat_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def _import_without_vad(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pipecat.audio.vad.silero":
            raise ModuleNotFoundError("No module named 'pipecat'", name="pipecat")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import_without_vad)
    with pytest.raises(RuntimeError, match=r"openrtc\[pipecat\]"):
        _default_vad_factory()


def test_default_turn_factory_raises_a_clear_error_when_pipecat_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def _import_without_turn(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("pipecat.audio.turn"):
            raise ModuleNotFoundError("No module named 'pipecat'", name="pipecat")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import_without_turn)
    with pytest.raises(RuntimeError, match=r"openrtc\[pipecat\]"):
        _default_turn_factory()


# --- PipecatCallView: forwards the neutral view, adds prewarm ---------------


class _FakeView:
    """A minimal SessionView stand-in that records connect()."""

    def __init__(self) -> None:
        self.connected = False

    @property
    def room_name(self) -> str:
        return "room-7"

    @property
    def job_id(self) -> str:
        return "job-7"

    @property
    def job_metadata(self) -> Any:
        return '{"agent": "sales"}'

    @property
    def room_metadata(self) -> Any:
        return {"tenant": "acme"}

    @property
    def session(self) -> Any:
        return "SESSION"

    async def connect(self) -> None:
        self.connected = True


def test_pipecat_call_view_forwards_the_neutral_fields_and_adds_prewarm() -> None:
    base = _FakeView()
    prewarm = SharedPrewarm(vad_factory=lambda: "VAD", turn_factory=lambda: "TURN")
    view = PipecatCallView(base, prewarm)

    assert view.room_name == "room-7"
    assert view.job_id == "job-7"
    assert view.job_metadata == '{"agent": "sales"}'
    assert view.room_metadata == {"tenant": "acme"}
    assert view.session == "SESSION"
    assert view.prewarmed is prewarm
    assert view.prewarmed.vad == "VAD"  # the builder reaches shared prewarm here


def test_pipecat_call_view_satisfies_the_session_view_protocol() -> None:
    prewarm = SharedPrewarm(vad_factory=object, turn_factory=object)
    view = PipecatCallView(_FakeView(), prewarm)
    # routing / observability isinstance-check the neutral protocol.
    assert isinstance(view, SessionView)


def test_pipecat_call_view_carries_an_optional_connection() -> None:
    prewarm = SharedPrewarm(vad_factory=object, turn_factory=object)
    default = PipecatCallView(_FakeView(), prewarm)
    assert default.connection is None  # off the serving path, no connection
    served = PipecatCallView(_FakeView(), prewarm, connection="RUNNER_ARGS")
    # serving attaches the RunnerArguments so the builder builds its transport.
    assert served.connection == "RUNNER_ARGS"


@pytest.mark.asyncio
async def test_pipecat_call_view_delegates_connect() -> None:
    base = _FakeView()
    prewarm = SharedPrewarm(vad_factory=object, turn_factory=object)
    view = PipecatCallView(base, prewarm)
    await view.connect()
    assert base.connected is True
