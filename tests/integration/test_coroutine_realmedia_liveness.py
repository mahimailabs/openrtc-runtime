"""Real-media held-open liveness for coroutine mode (MAH-164).

The shipped real-room test (``test_coroutine_realroom.py``) drives
``simulate_job(fake_job=True)``: a fake job has no live room to disconnect, so
it completes on entrypoint return and cannot prove held-open liveness end to
end (MAH-160: a session must stay live for the call, not be marked SUCCESS the
moment the greeting finishes).

This test closes that gap. It drives N real jobs (``fake_job=False``) into real
rooms, has a separate participant publish a real audio track via ``livekit.rtc``
into each, and asserts the worker holds N sessions live through a hold window,
then drains to zero once the callers disconnect and the rooms are deleted.

Hermetic: fake STT/LLM/TTS (no API keys), so it runs on every PR. The callers
publish silence, so Silero VAD never fires and the non-speaking fakes are never
invoked. Requires only the LiveKit dev server
(``docker compose -f docker-compose.test.yml up -d``); the ``livekit_dev_server``
fixture skips cleanly otherwise.
"""

from __future__ import annotations

import asyncio
import contextlib
import os

import pytest
from livekit import api, rtc
from livekit.agents import Agent
from livekit.protocol import models

from openrtc import AgentPool
from openrtc.runtime.coroutine_server import _CoroutineAgentServer

from ._fakes import FakeLLM, FakeSTT, FakeTTS
from .conftest import LiveKitDevServer

_SESSIONS = 3
_SAMPLE_RATE = 16000
_FRAME_SAMPLES = _SAMPLE_RATE // 100  # 10 ms of audio
_HOLD_SECONDS = 2.0


class _LiveAgent(Agent):
    """A minimal non-speaking agent; it exists to be held live in a real room."""

    def __init__(self) -> None:
        super().__init__(instructions="Integration liveness agent.")


def _caller_token(server: LiveKitDevServer, room_name: str, identity: str) -> str:
    return (
        api.AccessToken(server.api_key, server.api_secret)
        .with_identity(identity)
        .with_grants(api.VideoGrants(room_join=True, room=room_name))
        .to_jwt()
    )


async def _connect_caller(
    ws_url: str, token: str, stop: asyncio.Event
) -> tuple[rtc.Room, asyncio.Task[None]]:
    """Join a room and publish a silent mic track; return the room and pump task."""
    room = rtc.Room()
    await room.connect(ws_url, token)
    source = rtc.AudioSource(_SAMPLE_RATE, 1)
    track = rtc.LocalAudioTrack.create_audio_track("caller-mic", source)
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )
    silence = rtc.AudioFrame(
        data=bytes(_FRAME_SAMPLES * 2),  # 16-bit PCM silence
        sample_rate=_SAMPLE_RATE,
        num_channels=1,
        samples_per_channel=_FRAME_SAMPLES,
    )

    async def _pump() -> None:
        # capture_frame paces to real time via the source's internal queue.
        while not stop.is_set():
            with contextlib.suppress(Exception):
                await source.capture_frame(silence)

    return room, asyncio.create_task(_pump())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_realmedia_sessions_stay_live_through_the_call_then_drain(
    livekit_dev_server: LiveKitDevServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N real-media sessions stay held live during the call, then drain to zero."""
    os.environ["LIVEKIT_URL"] = livekit_dev_server.url
    os.environ["LIVEKIT_API_KEY"] = livekit_dev_server.api_key
    os.environ["LIVEKIT_API_SECRET"] = livekit_dev_server.api_secret
    # Disable the InferenceProcExecutor (no ONNX load in CI); only set when
    # absent and via monkeypatch so it reverts on teardown.
    if "LIVEKIT_REMOTE_EOT_URL" not in os.environ:
        monkeypatch.setenv("LIVEKIT_REMOTE_EOT_URL", "http://eot-disabled.invalid/eot")

    pool = AgentPool(
        isolation="coroutine",
        max_concurrent_sessions=10,
        default_stt=FakeSTT(),
        default_llm=FakeLLM(),
        default_tts=FakeTTS(),
    )
    pool.add("live", _LiveAgent)

    server = pool.server
    assert isinstance(server, _CoroutineAgentServer)

    rooms = [f"media-room-{i}" for i in range(_SESSIONS)]
    stop = asyncio.Event()
    callers: list[tuple[rtc.Room, asyncio.Task[None]]] = []
    runner = asyncio.create_task(server.run(devmode=True, unregistered=True))
    try:
        deadline = asyncio.get_event_loop().time() + 30.0
        while server.coroutine_pool is None or not server.coroutine_pool.started:
            if asyncio.get_event_loop().time() > deadline:
                pytest.fail("CoroutinePool did not start within 30s")
            await asyncio.sleep(0.1)
        pool_obj = server.coroutine_pool
        assert pool_obj is not None

        # Bring up N real-room agent sessions (held open) and a caller per room.
        for room_name in rooms:
            await server.simulate_job(
                room=room_name,
                fake_job=False,
                agent_identity=f"agent-{room_name}",
                room_info=models.Room(name=room_name),
            )
        for i, room_name in enumerate(rooms):
            token = _caller_token(livekit_dev_server, room_name, f"caller-{i}")
            callers.append(await _connect_caller(livekit_dev_server.url, token, stop))

        # Hold window: sessions stay live for the duration of the "call".
        deadline = asyncio.get_event_loop().time() + 30.0
        while len(pool_obj.processes) < _SESSIONS:
            if asyncio.get_event_loop().time() > deadline:
                pytest.fail(
                    f"only {len(pool_obj.processes)}/{_SESSIONS} sessions came live"
                )
            await asyncio.sleep(0.1)

        await asyncio.sleep(_HOLD_SECONDS)
        snapshot = pool.runtime_snapshot()
        print(
            f"\n[realmedia] hold: processes={len(pool_obj.processes)} "
            f"active_sessions={snapshot.active_sessions} "
            f"started={snapshot.total_sessions_started} "
            f"failures={snapshot.total_session_failures}"
        )

        # Held-open liveness: every session is live mid-call in BOTH the executor
        # pool and the metrics snapshot. MAH-166 reports session end at the real
        # disconnect (not the greeting boundary), so active_sessions stays == N
        # for the whole call rather than dropping to 0 early.
        assert len(pool_obj.processes) == _SESSIONS, (
            "a session dropped before the call ended (marked done early): "
            f"{len(pool_obj.processes)}/{_SESSIONS} still live"
        )
        assert snapshot.active_sessions == _SESSIONS
        assert snapshot.total_session_failures == 0

        # Disconnect callers and delete rooms: the agents see a clean disconnect.
        stop.set()
        for room, task in callers:
            with contextlib.suppress(Exception):
                await room.disconnect()
            task.cancel()
        callers.clear()

        http_url = livekit_dev_server.url.replace("ws://", "http://").replace(
            "wss://", "https://"
        )
        async with api.LiveKitAPI(
            url=http_url,
            api_key=livekit_dev_server.api_key,
            api_secret=livekit_dev_server.api_secret,
        ) as lkapi:
            for room_name in rooms:
                with contextlib.suppress(Exception):
                    await lkapi.room.delete_room(api.DeleteRoomRequest(room=room_name))

        # Drain: every held-open session finishes once its room is gone.
        deadline = asyncio.get_event_loop().time() + 30.0
        while pool_obj.processes:
            if asyncio.get_event_loop().time() > deadline:
                pytest.fail(f"sessions did not drain; alive: {len(pool_obj.processes)}")
            await asyncio.sleep(0.1)

        final = pool.runtime_snapshot()
        assert final.total_sessions_started == _SESSIONS
        assert final.total_session_failures == 0
        assert final.active_sessions == 0
    finally:
        stop.set()
        for room, task in callers:
            with contextlib.suppress(Exception):
                await room.disconnect()
            task.cancel()
        await server.aclose()
        with contextlib.suppress(TimeoutError, asyncio.CancelledError, Exception):
            await asyncio.wait_for(runner, timeout=10.0)
