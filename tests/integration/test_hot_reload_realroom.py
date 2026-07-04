"""MAH-86: hot reload runs inside a live coroutine worker (integration).

Boots a real ``_CoroutineAgentServer`` with ``enable_hot_reload=True`` and asserts
the FileWatcher is actually running for the run() lifetime and watches the agent
file, then stops cleanly on shutdown. This exercises the wiring inside a real
``server.run()`` (prewarm, load_fnc patch, watcher lifecycle) rather than in
isolation.

The full "edit mid-call, audio uninterrupted, next turn shifts behavior" path is
covered logically end-to-end (real reloader + rebind + coordinator over real
files) by ``tests/reload/test_end_to_end.py``, which runs without a server.

Requires a LiveKit dev server (``docker compose -f docker-compose.test.yml up -d``);
skips cleanly otherwise.
"""

from __future__ import annotations

import asyncio
import contextlib
import os

import pytest

from openrtc import AgentPool
from openrtc.runtime.coroutine_server import _CoroutineAgentServer

from .conftest import LiveKitDevServer

_AGENT_SOURCE = """\
from livekit.agents import Agent

from openrtc import agent_config


@agent_config(name="hot")
class HotAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="version one")
"""


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reload_watcher_runs_inside_a_live_worker(
    livekit_dev_server: LiveKitDevServer,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    os.environ["LIVEKIT_URL"] = livekit_dev_server.url
    os.environ["LIVEKIT_API_KEY"] = livekit_dev_server.api_key
    os.environ["LIVEKIT_API_SECRET"] = livekit_dev_server.api_secret

    agent_file = tmp_path / "hot_agent.py"
    agent_file.write_text(_AGENT_SOURCE)

    pool = AgentPool(
        isolation="coroutine",
        enable_hot_reload=True,
        watch_paths=[agent_file],
        default_stt="openai/gpt-4o-mini-transcribe",
        default_llm="openai/gpt-4.1-mini",
        default_tts="openai/gpt-4o-mini-tts",
    )
    pool.discover(tmp_path)
    server = pool.server
    assert isinstance(server, _CoroutineAgentServer)

    runner = asyncio.create_task(server.run(devmode=True, unregistered=True))
    try:
        deadline = asyncio.get_event_loop().time() + 30.0
        while server.reload_watcher is None or server.reload_watcher.state != "running":
            if asyncio.get_event_loop().time() > deadline:
                pytest.fail("reload watcher did not start within 30s")
            await asyncio.sleep(0.05)

        assert server.reload_watcher.state == "running"
        assert agent_file in server.reload_watcher.paths
    finally:
        await server.aclose()
        with contextlib.suppress(TimeoutError, asyncio.CancelledError, Exception):
            await asyncio.wait_for(runner, timeout=10.0)

    # Once run() unwinds, the watcher is torn down.
    assert server.reload_watcher is None
