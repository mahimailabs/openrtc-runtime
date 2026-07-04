"""Real-media proof of the hot-reload live re-bind (MAH-82 / MAH-83 / MAH-166).

The hermetic ``test_hot_reload_live.py`` proves the *config* reloads (new sessions
build the new class). It cannot prove the headline v0.2 feature: swapping a *live
in-call* session to the new class mid-conversation. That needs a real call whose
session stays registered for the whole call, which only works once the session's
end is reported at real disconnect rather than at the greeting boundary (MAH-166).

This test drives two real-media ``alpha`` sessions (real rooms + ``livekit.rtc``
audio publishers), confirms both stay live and counted (``active_sessions == 2``),
pins one, edits the agent file mid-call, and asserts:

- the config reloaded to ``v2`` (MAH-82 config swap);
- the *unpinned live session* re-bound to the v2 class mid-call (MAH-82 live);
- the *pinned live session* stayed on v1 (MAH-83);
- no session dropped or failed across the swap (audio uninterrupted proxy).

Hermetic: fake STT/LLM/TTS, silent audio (Silero VAD never fires). Requires the
docker LiveKit dev server; skips cleanly otherwise.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path

import pytest
from livekit import api, rtc
from livekit.protocol import models

from openrtc import AgentPool
from openrtc.reload.pin import pin
from openrtc.reload.session_registry import LiveSessionRegistry
from openrtc.runtime.coroutine_server import _CoroutineAgentServer

from ._fakes import FakeLLM, FakeSTT, FakeTTS
from .conftest import LiveKitDevServer

_ALPHA = """\
from livekit.agents import Agent

from openrtc import agent_config


@agent_config(name="alpha")
class AlphaAgent(Agent):
    VERSION = "{v}"

    def __init__(self) -> None:
        super().__init__(instructions="alpha {v}")
"""

_SESSIONS = 2
_SR = 16000
_FRAME = _SR // 100


def _registry(pool: AgentPool) -> LiveSessionRegistry:
    for obs in pool._runtime_state.observers:
        if isinstance(obs, LiveSessionRegistry):
            return obs
    raise AssertionError("hot reload did not install a LiveSessionRegistry observer")


class _Caller:
    """A connected participant publishing silence; closes its rtc resources cleanly."""

    def __init__(
        self, room: rtc.Room, source: rtc.AudioSource, task: asyncio.Task[None]
    ) -> None:
        self.room = room
        self.source = source
        self.task = task

    async def aclose(self) -> None:
        self.task.cancel()
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await self.task
        with contextlib.suppress(Exception):
            await self.source.aclose()
        with contextlib.suppress(Exception):
            await self.room.disconnect()


async def _connect_caller(ws_url: str, token: str, stop: asyncio.Event) -> _Caller:
    room = rtc.Room()
    await room.connect(ws_url, token)
    source = rtc.AudioSource(_SR, 1)
    track = rtc.LocalAudioTrack.create_audio_track("caller-mic", source)
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )
    silence = rtc.AudioFrame(
        data=bytes(_FRAME * 2),
        sample_rate=_SR,
        num_channels=1,
        samples_per_channel=_FRAME,
    )

    async def _pump() -> None:
        while not stop.is_set():
            with contextlib.suppress(Exception):
                await source.capture_frame(silence)

    return _Caller(room, source, asyncio.create_task(_pump()))


async def _await_until(predicate, *, timeout: float, message: str) -> None:  # type: ignore[no-untyped-def]
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() > deadline:
            pytest.fail(message)
        await asyncio.sleep(0.2)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_session_rebinds_mid_call_and_respects_pin(
    livekit_dev_server: LiveKitDevServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live in-call session re-binds to the reloaded class; a pinned one does not."""
    os.environ["LIVEKIT_URL"] = livekit_dev_server.url
    os.environ["LIVEKIT_API_KEY"] = livekit_dev_server.api_key
    os.environ["LIVEKIT_API_SECRET"] = livekit_dev_server.api_secret
    if "LIVEKIT_REMOTE_EOT_URL" not in os.environ:
        monkeypatch.setenv("LIVEKIT_REMOTE_EOT_URL", "http://eot-disabled.invalid/eot")

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    alpha_file = agents_dir / "alpha.py"
    alpha_file.write_text(_ALPHA.format(v="v1"))

    pool = AgentPool(
        isolation="coroutine",
        max_concurrent_sessions=10,
        enable_hot_reload=True,
        watch_paths=[agents_dir],
        default_stt=FakeSTT(),
        default_llm=FakeLLM(),
        default_tts=FakeTTS(),
    )
    pool.discover(agents_dir)
    registry = _registry(pool)

    server = pool.server
    assert isinstance(server, _CoroutineAgentServer)

    rooms = [f"alpha-room-{i}" for i in range(_SESSIONS)]
    stop = asyncio.Event()
    callers: list[_Caller] = []
    runner = asyncio.create_task(server.run(devmode=True, unregistered=True))
    try:
        await _await_until(
            lambda: server.coroutine_pool is not None and server.coroutine_pool.started,
            timeout=30.0,
            message="coroutine pool did not start",
        )
        pool_obj = server.coroutine_pool
        assert pool_obj is not None

        for room_name in rooms:
            await server.simulate_job(
                room=room_name,
                fake_job=False,
                agent_identity=f"agent-{room_name}",
                room_info=models.Room(name=room_name),
            )
        for i, room_name in enumerate(rooms):
            token = (
                api.AccessToken(
                    livekit_dev_server.api_key, livekit_dev_server.api_secret
                )
                .with_identity(f"caller-{i}")
                .with_grants(api.VideoGrants(room_join=True, room=room_name))
                .to_jwt()
            )
            callers.append(await _connect_caller(livekit_dev_server.url, token, stop))

        # MAH-166: both sessions stay live AND counted for the whole call, so the
        # registry (and active_sessions) reflect the real call, not the greeting.
        await _await_until(
            lambda: registry.active_count() >= _SESSIONS,
            timeout=30.0,
            message=f"only {registry.active_count()}/{_SESSIONS} sessions registered",
        )
        live = registry.sessions_for("alpha")
        assert len(live) == _SESSIONS
        assert pool.runtime_snapshot().active_sessions == _SESSIONS
        assert all(s.current_agent.VERSION == "v1" for s in live)

        pinned, unpinned = live[0], live[1]
        pin(pinned)

        # Edit the agent mid-call; the real watcher reloads and re-binds live.
        alpha_file.write_text(_ALPHA.format(v="v2"))
        await _await_until(
            lambda: pool.get("alpha").agent_cls.VERSION == "v2",
            timeout=20.0,
            message="alpha config did not reload to v2",
        )
        await _await_until(
            lambda: unpinned.current_agent.VERSION == "v2",
            timeout=20.0,
            message="the unpinned live session did not re-bind to v2 mid-call",
        )

        # MAH-83: the pinned session kept its v1 class across the swap.
        assert pinned.current_agent.VERSION == "v1"
        # No call dropped or failed across the swap (audio uninterrupted proxy).
        assert len(pool_obj.processes) == _SESSIONS
        assert pool.runtime_snapshot().total_session_failures == 0

        http_url = livekit_dev_server.url.replace("ws://", "http://")
        async with api.LiveKitAPI(
            url=http_url,
            api_key=livekit_dev_server.api_key,
            api_secret=livekit_dev_server.api_secret,
        ) as lkapi:
            for room_name in rooms:
                with contextlib.suppress(Exception):
                    await lkapi.room.delete_room(api.DeleteRoomRequest(room=room_name))

        # Drain to zero once the rooms are gone (end reported at real disconnect).
        await _await_until(
            lambda: not pool_obj.processes,
            timeout=30.0,
            message="sessions did not drain after disconnect",
        )
        assert pool.runtime_snapshot().active_sessions == 0
    finally:
        stop.set()
        for caller in callers:
            await caller.aclose()
        await server.aclose()
        with contextlib.suppress(TimeoutError, asyncio.CancelledError, Exception):
            await asyncio.wait_for(runner, timeout=10.0)
