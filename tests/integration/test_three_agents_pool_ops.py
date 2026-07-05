"""v0.4 success gate: three agents in one live pool, routed and tagged (MAH-100).

The v0.4 headline is "watch three agents run in one pool". The unit and
real-media tests each prove one facet of that:

- reload isolation (edit one agent, only its live sessions swap) is proven with
  real media in ``tests/integration/test_per_agent_reload_realroom.py``,
- the per-agent backpressure filter logic (at cap -> reject, sibling accepts) is
  proven exhaustively in ``tests/test_request_backpressure.py``,
- 5 concurrent sessions in one coroutine worker in
  ``tests/integration/test_concurrent_real_calls.py``.

What none of them proves on its own is the unified surface: three *distinct*
registered agents in one live coroutine pool, each addressed by its own routing
signal, each session tagged to the agent that actually handled it. That is this
test. It drives fake jobs (no media: routing + tagging do not need audio) routed
by room-name prefix and asserts, via a recording observer, that every session
landed on the agent its room named. The companion budget-rejection assertion
(the 6th sales rejected while siblings accept, driven through the pool's own
installed ``request_fnc``) lives in ``tests/test_request_backpressure.py`` so it
runs in the fast suite on every PR.

The ticket's 5/5/5 = 15 sessions is illustrative; distinct per-agent counts
(3/2/1) prove the tagging is per-agent rather than a shared tally, and keep the
fake-job run quick and deterministic. Requires the docker LiveKit dev server;
skips cleanly otherwise.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections import Counter
from typing import Any

import pytest
from livekit.agents import Agent

from openrtc import AgentPool
from openrtc.observability.base_observer import SessionInfo
from openrtc.runtime.coroutine_server import _CoroutineAgentServer

from ._fakes import FakeLLM, FakeSTT, FakeTTS
from .conftest import LiveKitDevServer


class _SalesAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="sales")


class _SupportAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="support")


class _SchedulingAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="scheduling")


class _RecordingObserver:
    """Collect the agent name each session was routed and tagged to."""

    def __init__(self) -> None:
        self.started: list[str] = []

    async def on_session_start(self, info: SessionInfo, session: Any) -> None:
        self.started.append(info.agent_name)

    async def on_session_end(self, info: SessionInfo, outcome: Any) -> None:
        return None


# Distinct per-agent counts so the assertion proves per-agent tagging, not a
# shared tally. (The ticket's 5/5/5 is illustrative; see module docstring.)
_PLAN = {"sales": 3, "support": 2, "scheduling": 1}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_three_agents_route_and_tag_in_one_live_pool(
    livekit_dev_server: LiveKitDevServer,
) -> None:
    """Three agents in one pool: each job routes to, and is tagged with, its agent."""
    os.environ["LIVEKIT_URL"] = livekit_dev_server.url
    os.environ["LIVEKIT_API_KEY"] = livekit_dev_server.api_key
    os.environ["LIVEKIT_API_SECRET"] = livekit_dev_server.api_secret

    recorder = _RecordingObserver()
    pool = AgentPool(
        isolation="coroutine",
        max_concurrent_sessions=20,
        default_stt=FakeSTT(),
        default_llm=FakeLLM(),
        default_tts=FakeTTS(),
        observers=[recorder],
    )
    # Three distinct agents, addressed by room-name prefix (sales-room-* -> sales).
    pool.add("sales", _SalesAgent)
    pool.add("support", _SupportAgent)
    pool.add("scheduling", _SchedulingAgent)

    server = pool.server
    assert isinstance(server, _CoroutineAgentServer)

    runner = asyncio.create_task(server.run(devmode=True, unregistered=True))
    try:
        deadline = asyncio.get_event_loop().time() + 30.0
        while server.coroutine_pool is None or not server.coroutine_pool.started:
            if asyncio.get_event_loop().time() > deadline:
                pytest.fail("CoroutinePool did not start within 30s")
            await asyncio.sleep(0.1)

        # Drive one fake job per planned session, room-named for its agent so the
        # room-prefix router dispatches it. Fake jobs need no media.
        async def _drive(agent: str, idx: int) -> None:
            await server.simulate_job(room=f"{agent}-room-{idx}", fake_job=True)

        await asyncio.gather(
            *(_drive(agent, i) for agent, count in _PLAN.items() for i in range(count))
        )

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

        # Routing dispatched each room to the agent its prefix named, and every
        # session was tagged to the agent that handled it (per-agent, not pooled).
        assert Counter(recorder.started) == _PLAN

        snapshot = pool.runtime_snapshot()
        assert snapshot.total_sessions_started == sum(_PLAN.values())
        assert snapshot.total_session_failures == 0
    finally:
        await server.aclose()
        with contextlib.suppress(TimeoutError, asyncio.CancelledError, Exception):
            await asyncio.wait_for(runner, timeout=10.0)
