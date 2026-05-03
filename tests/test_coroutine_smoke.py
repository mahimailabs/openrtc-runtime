"""End-to-end smoke test for the coroutine path.

Wires the stack the way ``AgentServer.run() + simulate_job(fake_job=True)``
would: AgentPool -> _CoroutineAgentServer (built by AgentPool.__init__) ->
CoroutinePool (constructed with the same setup_fnc + entrypoint_fnc the
real ``run()`` would pass) -> the universal entrypoint that resolves the
agent and spawns an AgentSession.

We don't engage ``AgentServer.run()`` itself because that requires a real
LiveKit URL + API credentials and a live WS dispatcher. Instead we drive
the same callbacks the real ``run()`` would, while stubbing the heavy
dependencies (silero/turn-detector models, AgentSession, rtc.Room).

This is the v0.1 §7 Phase 1 "one sanity-check integration test" — proof
that the wiring agrees end-to-end, without standing up a server.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import Agent, JobExecutorType

from openrtc import AgentPool
from openrtc.execution.coroutine import CoroutinePool
from openrtc.execution.coroutine_server import _CoroutineAgentServer


class _SmokeAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="smoke test agent")


def _stub_running_job_info(job_id: str = "smoke-job-1") -> Any:
    """Minimal fake_job RunningJobInfo stand-in."""
    return SimpleNamespace(
        job=SimpleNamespace(id=job_id),
        fake_job=True,
        worker_id="smoke-worker",
    )


def test_coroutine_pool_runs_one_simulated_job_through_universal_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # --- Stub the heavy dependencies that the real run() would touch ----

    started_sessions: list[dict[str, Any]] = []
    generate_calls: list[str] = []

    class _FakeSession:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def start(self, *, agent: Any, room: Any) -> None:
            started_sessions.append(
                {
                    "agent_class": type(agent).__name__,
                    "session_kwargs": dict(self.kwargs),
                }
            )

        async def generate_reply(self, *, instructions: str) -> None:
            generate_calls.append(instructions)

    monkeypatch.setattr("openrtc.core.pool.AgentSession", _FakeSession)

    # Skip the real Silero/turn-detector load. _prewarm_worker is sync.
    def _stub_prewarm(_runtime_state: Any, proc: Any) -> None:
        proc.userdata["vad"] = "vad-stub"
        proc.userdata["turn_detection_factory"] = lambda: "td-stub"

    monkeypatch.setattr("openrtc.core.pool._prewarm_worker", _stub_prewarm)

    # --- Build the AgentPool exactly as a user would ----------------------

    pool = AgentPool(isolation="coroutine", max_concurrent_sessions=4)
    pool.add("smoke", _SmokeAgent, greeting="hello smoke")

    server = pool.server
    assert isinstance(server, _CoroutineAgentServer)
    assert server.setup_fnc is not None
    assert server._entrypoint_fnc is not None

    # --- Construct a CoroutinePool the way _CoroutineAgentServer.run() would.
    # We do this inline (rather than calling server.run()) because run()
    # would try to open an HTTP server and connect to LiveKit.

    coro_pool = CoroutinePool(
        initialize_process_fnc=server.setup_fnc,
        job_entrypoint_fnc=server._entrypoint_fnc,
        session_end_fnc=server._session_end_fnc,
        num_idle_processes=0,
        initialize_timeout=5.0,
        close_timeout=5.0,
        inference_executor=None,
        job_executor_type=JobExecutorType.PROCESS,
        mp_ctx=mp.get_context(),
        memory_warn_mb=0.0,
        memory_limit_mb=0.0,
        http_proxy=None,
        loop=asyncio.new_event_loop(),
        max_concurrent_sessions=server._max_concurrent_sessions,
    )

    # Replace the JobContext builder so we don't construct a real rtc.Room.
    # The universal entrypoint (`_run_universal_session`) only reads
    # ctx.proc, ctx.job, ctx.room, ctx.connect; we provide those.

    def _fake_ctx(info: Any) -> Any:
        async def _connect() -> None:
            return None

        return SimpleNamespace(
            proc=coro_pool.shared_process,
            job=info.job,
            room=SimpleNamespace(name="smoke-room", metadata={"agent": "smoke"}),
            connect=_connect,
        )

    coro_pool._build_job_context = _fake_ctx  # type: ignore[assignment]

    # --- Drive: start, launch one job, drain to completion ---------------

    async def _scenario() -> None:
        await coro_pool.start()
        assert coro_pool.shared_process is not None
        assert coro_pool.shared_process.userdata["vad"] == "vad-stub"

        await coro_pool.launch_job(_stub_running_job_info())

        # Drain the entrypoint task so the FakeSession.start finishes.
        for ex in list(coro_pool.processes):
            task = ex._task  # type: ignore[attr-defined]
            if task is not None:
                await task

        await coro_pool.aclose()

    asyncio.run(_scenario())

    # --- Verify the universal entrypoint did its job --------------------

    assert len(started_sessions) == 1
    assert started_sessions[0]["agent_class"] == "_SmokeAgent"
    # The universal entrypoint pulls vad from prewarm; confirm wiring.
    assert started_sessions[0]["session_kwargs"]["vad"] == "vad-stub"
    # The greeting was passed through after connect.
    assert generate_calls == ["hello smoke"]
    # After drain, the executor is gone and the pool is shut.
    assert coro_pool.processes == []
    assert coro_pool.started is False
