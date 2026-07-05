"""Real-media proof of per-agent hot reload isolation (MAH-97).

The hermetic + single-agent tests prove the reload machinery; this proves the
multi-agent headline: with two different agents each running a live real-media
call, editing one agent's file re-binds only *its* live session and leaves the
sibling agent's live session untouched.

Two agents (``alpha`` + ``beta``) are enough to prove the isolation the ticket
asks for: the code path that could leak a swap across agents is
``registry.sessions_for(name)``, and one sibling exercises it. (The ticket's "3
agents" is illustrative; a third adds no new path over the deterministic unit
proof in tests/reload/test_per_agent_reload.py.)

Hermetic providers, silent audio, requires the docker LiveKit dev server; skips
cleanly otherwise.
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
from openrtc.reload.session_registry import LiveSessionRegistry
from openrtc.runtime.coroutine_server import _CoroutineAgentServer

from ._fakes import FakeLLM, FakeSTT, FakeTTS
from .conftest import LiveKitDevServer

_AGENT_SRC = """\
from livekit.agents import Agent

from openrtc import agent_config


@agent_config(name="{name}")
class {cls}(Agent):
    VERSION = "{v}"

    def __init__(self) -> None:
        super().__init__(instructions="{name} {v}")
"""

_SR = 16000
_FRAME = _SR // 100


def _registry(pool: AgentPool) -> LiveSessionRegistry:
    for obs in pool._runtime_state.observers:
        if isinstance(obs, LiveSessionRegistry):
            return obs
    raise AssertionError("hot reload did not install a LiveSessionRegistry observer")


class _Caller:
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
async def test_editing_one_agent_leaves_sibling_sessions_untouched(
    livekit_dev_server: LiveKitDevServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Editing alpha re-binds only alpha's live session; beta's stays on v1."""
    os.environ["LIVEKIT_URL"] = livekit_dev_server.url
    os.environ["LIVEKIT_API_KEY"] = livekit_dev_server.api_key
    os.environ["LIVEKIT_API_SECRET"] = livekit_dev_server.api_secret
    if "LIVEKIT_REMOTE_EOT_URL" not in os.environ:
        monkeypatch.setenv("LIVEKIT_REMOTE_EOT_URL", "http://eot-disabled.invalid/eot")

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    alpha_file = agents_dir / "alpha.py"
    beta_file = agents_dir / "beta.py"
    alpha_file.write_text(_AGENT_SRC.format(name="alpha", cls="AlphaAgent", v="v1"))
    beta_file.write_text(_AGENT_SRC.format(name="beta", cls="BetaAgent", v="v1"))

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

    rooms = ["alpha-room-0", "beta-room-0"]
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

        # Both agents' sessions go live and stay counted (MAH-166).
        await _await_until(
            lambda: registry.active_count() >= 2,
            timeout=30.0,
            message=f"only {registry.active_count()}/2 sessions registered",
        )
        alpha_live = registry.sessions_for("alpha")
        beta_live = registry.sessions_for("beta")
        assert len(alpha_live) == 1
        assert len(beta_live) == 1
        assert alpha_live[0].current_agent.VERSION == "v1"
        assert beta_live[0].current_agent.VERSION == "v1"

        # Edit ONLY alpha mid-call.
        alpha_file.write_text(_AGENT_SRC.format(name="alpha", cls="AlphaAgent", v="v2"))
        await _await_until(
            lambda: pool.get("alpha").agent_cls.VERSION == "v2",
            timeout=20.0,
            message="alpha config did not reload to v2",
        )
        await _await_until(
            lambda: alpha_live[0].current_agent.VERSION == "v2",
            timeout=20.0,
            message="alpha's live session did not re-bind to v2",
        )

        # Sibling isolation: beta's config and live session stayed on v1.
        assert pool.get("beta").agent_cls.VERSION == "v1"
        assert beta_live[0].current_agent.VERSION == "v1"
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

        await _await_until(
            lambda: not pool_obj.processes,
            timeout=30.0,
            message="sessions did not drain after disconnect",
        )
    finally:
        stop.set()
        for caller in callers:
            await caller.aclose()
        await server.aclose()
        with contextlib.suppress(TimeoutError, asyncio.CancelledError, Exception):
            await asyncio.wait_for(runner, timeout=10.0)
