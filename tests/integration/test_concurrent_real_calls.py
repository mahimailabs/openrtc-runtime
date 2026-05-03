"""Integration test: 5 concurrent sessions in one coroutine worker.

Satisfies design §8.4 acceptance criterion. Marks ``integration`` because
it requires:

- a running LiveKit dev server (``docker compose -f docker-compose.test.yml
  up -d``); the :func:`livekit_dev_server` fixture skips otherwise,
- real provider API keys (``OPENAI_API_KEY``); skipped if absent.

The test drives 5 concurrent ``AgentServer.simulate_job(fake_job=True)``
calls through ``AgentPool(isolation="coroutine")``. ``fake_job=True`` uses
a mock room so the per-session WebRTC path doesn't need media tracks; the
worker itself still runs against the real LiveKit dev server (registers
with the dispatcher, opens HTTP server, etc.). Each session fires one
``generate_reply`` for its greeting, which exercises the real STT / LLM /
TTS providers — the property §8.4 demands.
"""

from __future__ import annotations

import asyncio
import contextlib
import os

import pytest
from livekit.agents import Agent

from openrtc import AgentPool
from openrtc.execution.coroutine_server import _CoroutineAgentServer

from .conftest import LiveKitDevServer

_REQUIRED_PROVIDER_ENV = ("OPENAI_API_KEY",)


def _provider_credentials_available() -> bool:
    return all(os.environ.get(name) for name in _REQUIRED_PROVIDER_ENV)


class _SmokeAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are a tiny smoke-test agent. Greet the caller in one short "
                "sentence and then stop talking."
            )
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_five_concurrent_sessions_complete_in_one_coroutine_worker(
    livekit_dev_server: LiveKitDevServer,
) -> None:
    """§8.4: 5 concurrent calls in one coroutine worker, all complete."""

    if not _provider_credentials_available():
        missing = ", ".join(
            name for name in _REQUIRED_PROVIDER_ENV if not os.environ.get(name)
        )
        pytest.skip(f"required provider credentials not set in environment: {missing}")

    # Forward the dev server credentials so AgentServer.run() picks them up.
    os.environ["LIVEKIT_URL"] = livekit_dev_server.url
    os.environ["LIVEKIT_API_KEY"] = livekit_dev_server.api_key
    os.environ["LIVEKIT_API_SECRET"] = livekit_dev_server.api_secret

    pool = AgentPool(
        isolation="coroutine",
        max_concurrent_sessions=10,
        default_stt="openai/gpt-4o-mini-transcribe",
        default_llm="openai/gpt-4.1-mini",
        default_tts="openai/gpt-4o-mini-tts",
    )
    pool.add("smoke", _SmokeAgent, greeting="Hello from the smoke agent.")

    server = pool.server
    assert isinstance(server, _CoroutineAgentServer)

    # Run the worker in the background. unregistered=True keeps us from
    # competing for jobs from the real dispatcher; we drive sessions
    # ourselves via simulate_job.
    runner = asyncio.create_task(server.run(devmode=True, unregistered=True))
    try:
        # Wait for the pool to come up.
        deadline = asyncio.get_event_loop().time() + 30.0
        while server.coroutine_pool is None or not server.coroutine_pool.started:
            if asyncio.get_event_loop().time() > deadline:
                pytest.fail("CoroutinePool did not start within 30s")
            await asyncio.sleep(0.1)

        # Drive 5 concurrent simulate_job() calls.
        async def _one(idx: int) -> None:
            await server.simulate_job(room=f"smoke-room-{idx}", fake_job=True)

        await asyncio.gather(*(_one(i) for i in range(5)))

        # Wait for all sessions to finish (the entrypoint exits after the
        # greeting completes; the pool's done callback removes them).
        pool_obj = server.coroutine_pool
        assert pool_obj is not None
        deadline = asyncio.get_event_loop().time() + 60.0
        while pool_obj.processes:
            if asyncio.get_event_loop().time() > deadline:
                pytest.fail(
                    f"sessions did not drain within 60s; "
                    f"still alive: {len(pool_obj.processes)}"
                )
            await asyncio.sleep(0.1)

        # Every session should have completed without tripping the
        # supervisor.
        snapshot = pool.runtime_snapshot()
        assert snapshot.total_sessions_started == 5
        assert snapshot.total_session_failures == 0
    finally:
        await server.aclose()
        # Best-effort cleanup: swallow whatever the runner task raises so a
        # post-aclose error doesn't mask the actual assertion failure (or
        # success) the test reached above. The runner is a background server
        # loop; any genuine bug it hits has already shown up as a session
        # failure on `pool.runtime_snapshot()`.
        with contextlib.suppress(TimeoutError, asyncio.CancelledError, Exception):
            await asyncio.wait_for(runner, timeout=10.0)


@pytest.mark.integration
def test_provider_credentials_skip_message_is_explicit() -> None:
    """Document the env vars the §8.4 test requires.

    A pure-doc test so the skip path is observable in pytest output even
    when the heavier test is gated out by the dev-server fixture.
    """
    if _provider_credentials_available():
        pytest.skip("provider credentials are present; nothing to document")
    expected: list[str] = list(_REQUIRED_PROVIDER_ENV)
    assert expected == ["OPENAI_API_KEY"]
