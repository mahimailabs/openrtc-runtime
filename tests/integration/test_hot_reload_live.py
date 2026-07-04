"""MAH-86: editing an agent reloads it inside a live coroutine worker.

Two agents connect to the real LiveKit dev server through one OpenRTC worker with
`enable_hot_reload=True`; editing one agent's file drives the real FileWatcher ->
coordinator -> module reload, and the registered class swaps for that agent while
the other is untouched. The live-session re-bind itself (swapping in-flight
sessions) is covered hermetically by ``tests/reload/test_end_to_end.py``.

Requires the docker LiveKit dev server; skips cleanly otherwise.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path

import pytest
from livekit import api
from livekit.protocol import models

from openrtc import AgentPool
from openrtc.runtime.coroutine_server import _CoroutineAgentServer

from ._fakes import FakeLLM, FakeSTT, FakeTTS
from .conftest import LiveKitDevServer

_ALPHA = """\
from livekit.agents import Agent
from livekit.agents.job import get_job_context

from openrtc import agent_config


@agent_config(name="alpha")
class AlphaAgent(Agent):
    VERSION = "{v}"

    def __init__(self) -> None:
        super().__init__(instructions="alpha {v}")

    async def on_enter(self) -> None:
        get_job_context()
"""

_BETA = """\
from livekit.agents import Agent
from livekit.agents.job import get_job_context

from openrtc import agent_config


@agent_config(name="beta")
class BetaAgent(Agent):
    VERSION = "b1"

    def __init__(self) -> None:
        super().__init__(instructions="beta")

    async def on_enter(self) -> None:
        get_job_context()
"""


async def _await_until(predicate, *, timeout: float, message: str) -> None:  # type: ignore[no-untyped-def]
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() > deadline:
            pytest.fail(message)
        await asyncio.sleep(0.2)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_editing_an_agent_reloads_it_in_a_live_worker(
    livekit_dev_server: LiveKitDevServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    os.environ["LIVEKIT_URL"] = livekit_dev_server.url
    os.environ["LIVEKIT_API_KEY"] = livekit_dev_server.api_key
    os.environ["LIVEKIT_API_SECRET"] = livekit_dev_server.api_secret
    # Only set when absent (preserves a real URL) and via monkeypatch so it
    # reverts on teardown instead of leaking into later unit tests.
    if "LIVEKIT_REMOTE_EOT_URL" not in os.environ:
        monkeypatch.setenv("LIVEKIT_REMOTE_EOT_URL", "http://eot-disabled.invalid/eot")

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    alpha_file = agents_dir / "alpha.py"
    alpha_file.write_text(_ALPHA.format(v="v1"))
    (agents_dir / "beta.py").write_text(_BETA)

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
    assert set(pool.list_agents()) == {"alpha", "beta"}

    server = pool.server
    assert isinstance(server, _CoroutineAgentServer)

    runner = asyncio.create_task(server.run(devmode=True, unregistered=True))
    try:
        await _await_until(
            lambda: server.coroutine_pool is not None and server.coroutine_pool.started,
            timeout=30.0,
            message="coroutine pool did not start",
        )
        assert server.reload_watcher is not None

        # Two agents genuinely connected: two live sessions in one worker.
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
        pool_obj = server.coroutine_pool
        assert pool_obj is not None
        await _await_until(
            lambda: len(pool_obj.processes) >= 2,
            timeout=30.0,
            message="expected two concurrent live sessions",
        )
        assert pool.get("alpha").agent_cls.VERSION == "v1"

        # Edit one agent file while calls are live; the real watcher reloads it.
        alpha_file.write_text(_ALPHA.format(v="v2"))
        await _await_until(
            lambda: pool.get("alpha").agent_cls.VERSION == "v2",
            timeout=20.0,
            message="alpha class did not reload to v2 in the live worker",
        )
        assert pool.get("alpha").agent_cls.VERSION == "v2"
        assert pool.get("beta").agent_cls.VERSION == "b1"  # untouched by an alpha edit

        http_url = livekit_dev_server.url.replace("ws://", "http://")
        async with api.LiveKitAPI(
            url=http_url,
            api_key=livekit_dev_server.api_key,
            api_secret=livekit_dev_server.api_secret,
        ) as lkapi:
            for room in ("alpha-room-1", "beta-room-1"):
                with contextlib.suppress(Exception):
                    await lkapi.room.delete_room(api.DeleteRoomRequest(room=room))
    finally:
        await server.aclose()
        with contextlib.suppress(TimeoutError, asyncio.CancelledError, Exception):
            await asyncio.wait_for(runner, timeout=10.0)
