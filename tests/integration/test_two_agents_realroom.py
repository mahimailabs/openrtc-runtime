"""Integration test: two agents in one coroutine worker, real-room lifecycle.

This is the end-to-end guard that openrtc keeps working with real livekit
``Agent`` classes. It drives two real-room jobs (``simulate_job(fake_job=False)``)
so each agent genuinely connects to the dev server, then checks the surface
that broke when openrtc started the session before connecting: each agent's
``on_enter`` reaches ``room.local_participant`` (raises "cannot access local
participant before connecting" if the room is not connected yet) and records
the outcome instead of crashing.

Asserts that openrtc routed each room to the right agent class, both
``on_enter`` ran post-connect, both sessions were live concurrently (density),
and both finished without failure once the rooms are deleted.

Hermetic: uses fake STT/LLM/TTS (no API keys), so it runs on every PR. Requires
only the LiveKit dev server (``docker compose -f docker-compose.test.yml up -d``);
the ``livekit_dev_server`` fixture skips cleanly otherwise.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

import pytest
from livekit import api
from livekit.agents import Agent
from livekit.agents.job import get_job_context
from livekit.protocol import models

from openrtc import AgentPool
from openrtc.runtime.coroutine_server import _CoroutineAgentServer

from ._fakes import FakeLLM, FakeSTT, FakeTTS
from .conftest import LiveKitDevServer

# room name -> outcome recorded by the agent's on_enter (module-global because
# the pool instantiates the agent classes itself).
_OUTCOMES: dict[str, dict[str, Any]] = {}


async def _rpc_handler(_data: Any) -> str:
    return "ok"


class _RealRoomAgent(Agent):
    """Records, on enter, whether its room's local participant is reachable."""

    _label = "base"

    def __init__(self) -> None:
        super().__init__(instructions="Integration test agent.")

    async def on_enter(self) -> None:
        ctx = get_job_context()
        room = ctx.room
        try:
            # The exact failure surface from the incident: reach the local
            # participant and register an RPC, as a real agent does on enter.
            # Raises "cannot access local participant before connecting" if the
            # session was started before the room finished connecting.
            room.local_participant.register_rpc_method("ping", _rpc_handler)
            _OUTCOMES[room.name] = {"agent": self._label, "local_participant": True}
        except Exception as exc:  # noqa: BLE001 - record, do not crash the session
            _OUTCOMES[room.name] = {
                "agent": self._label,
                "local_participant": False,
                "error": str(exc),
            }


class AlphaAgent(_RealRoomAgent):
    _label = "alpha"


class BetaAgent(_RealRoomAgent):
    _label = "beta"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_two_agents_realroom_on_enter_runs_post_connect(
    livekit_dev_server: LiveKitDevServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two routed agents connect, run on_enter post-connect, and finish clean."""
    os.environ["LIVEKIT_URL"] = livekit_dev_server.url
    os.environ["LIVEKIT_API_KEY"] = livekit_dev_server.api_key
    os.environ["LIVEKIT_API_SECRET"] = livekit_dev_server.api_secret

    _OUTCOMES.clear()

    pool = AgentPool(
        isolation="coroutine",
        max_concurrent_sessions=10,
        default_stt=FakeSTT(),
        default_llm=FakeLLM(),
        default_tts=FakeTTS(),
    )
    pool.add("alpha", AlphaAgent)
    pool.add("beta", BetaAgent)

    server = pool.server
    assert isinstance(server, _CoroutineAgentServer)

    # Prevent InferenceProcExecutor from starting in CI: the eager
    # MultilingualModel import in _CoroutineAgentServer.run() registers the EOU
    # runner, and worker.py then spawns an InferenceProcExecutor subprocess that
    # must load the ONNX model. In CI the model may be absent or slow, causing
    # the 30s pool-start timeout to expire. Setting this env var before the
    # import makes multilingual.py skip runner registration (it only registers
    # when LIVEKIT_REMOTE_EOT_URL is unset). _supports_multilingual_turn_detection
    # still returns True via the env-var branch, so session wiring is unchanged.
    # Only set when absent (preserves a real URL a developer configured), and via
    # monkeypatch so it reverts on teardown instead of leaking into later unit
    # tests that assert the VAD fallback path.
    if "LIVEKIT_REMOTE_EOT_URL" not in os.environ:
        monkeypatch.setenv("LIVEKIT_REMOTE_EOT_URL", "http://eot-disabled.invalid/eot")

    rooms = ["alpha-room-1", "beta-room-1"]
    runner = asyncio.create_task(server.run(devmode=True, unregistered=True))
    try:
        deadline = asyncio.get_event_loop().time() + 30.0
        while server.coroutine_pool is None or not server.coroutine_pool.started:
            if asyncio.get_event_loop().time() > deadline:
                pytest.fail("CoroutinePool did not start within 30s")
            await asyncio.sleep(0.1)
        pool_obj = server.coroutine_pool
        assert pool_obj is not None

        # Drive two concurrent real-room jobs (fake_job=False connects to the
        # dev server). Room names are prefixed so openrtc's room-prefix routing
        # sends each to a different agent class.
        await server.simulate_job(
            room="alpha-room-1",
            fake_job=False,
            agent_identity="agent-alpha",
            room_info=models.Room(name="alpha-room-1"),
        )
        await server.simulate_job(
            room="beta-room-1",
            fake_job=False,
            agent_identity="agent-beta",
            room_info=models.Room(name="beta-room-1"),
        )

        deadline = asyncio.get_event_loop().time() + 30.0
        while len(_OUTCOMES) < 2:
            if asyncio.get_event_loop().time() > deadline:
                pytest.fail(f"on_enter did not run for both agents; got {_OUTCOMES}")
            await asyncio.sleep(0.1)

        # Outcomes are keyed by the connected room name. If on_enter ran before
        # connect (the bug), room.name is "" and the keys would be wrong, so this
        # fails descriptively rather than with a later KeyError.
        assert set(_OUTCOMES) == set(rooms), (
            "on_enter recorded unexpected room names (a sign it ran before the "
            f"room connected, when room.name is empty): {sorted(_OUTCOMES)}"
        )

        # Both sessions live at once: openrtc hosts two agents in one worker.
        assert len(pool_obj.processes) == 2, (
            f"expected 2 concurrent sessions, got {len(pool_obj.processes)}"
        )

        # Routing sent each room to the right agent class.
        assert _OUTCOMES["alpha-room-1"]["agent"] == "alpha", _OUTCOMES
        assert _OUTCOMES["beta-room-1"]["agent"] == "beta", _OUTCOMES

        # The bug-catch: on_enter ran after the room connected, so the local
        # participant was reachable for both.
        for room_name, outcome in _OUTCOMES.items():
            assert outcome["local_participant"] is True, (
                f"on_enter ran before the room connected for {room_name}: "
                f"{outcome.get('error')!r}"
            )

        # Graceful teardown: delete the rooms so each agent sees a clean
        # disconnect and the session finishes SUCCESS (not a cancellation).
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

        deadline = asyncio.get_event_loop().time() + 30.0
        while pool_obj.processes:
            if asyncio.get_event_loop().time() > deadline:
                pytest.fail(f"sessions did not drain; alive: {len(pool_obj.processes)}")
            await asyncio.sleep(0.1)

        snapshot = pool.runtime_snapshot()
        assert snapshot.total_sessions_started == 2
        assert snapshot.total_session_failures == 0
    finally:
        await server.aclose()
        with contextlib.suppress(TimeoutError, asyncio.CancelledError, Exception):
            await asyncio.wait_for(runner, timeout=10.0)
