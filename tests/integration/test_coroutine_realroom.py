"""Real-room integration test + throughput probe for coroutine mode.

This is the test the existing ``test_concurrent_real_calls.py`` should have
been. That one uses a trivial no-tool agent, so it never exercises the paths
that broke:

- ``get_job_context()`` (raises in coroutine mode: the executor never sets
  ``_JobContextVar``),
- event-loop saturation under concurrency (the stub density bench measures a
  ``sleep`` + bytearray, not real audio/inference),

Here, the agent calls ``get_job_context()`` in ``on_enter`` (the single most
common reason user code needs the job ctx), and we sample the event-loop
scheduler latency and RSS while the sessions run, so the result is a
throughput signal rather than a memory stunt.

Requires (skips cleanly otherwise):
- a LiveKit dev server (``docker compose -f docker-compose.test.yml up -d``),
- ``OPENAI_API_KEY``.

This is a correctness gate: every session must resolve ``get_job_context()``
and finish without failure. The event-loop p99 latency is printed as a
diagnostic only; the throughput-vs-session-count gate lives in
``tests/benchmarks/throughput.py``.

Liveness (a held-open session staying active for the call duration) needs a
real room: extend ``_drive_session`` to publish an audio track via
``livekit.rtc`` instead of ``simulate_job(fake_job=True)``. A fake job has no
live room to disconnect, so it completes on entrypoint return rather than being
held open. Tracked in MAH-162.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time

import pytest
from livekit.agents import Agent
from livekit.agents.job import get_job_context

from openrtc import AgentPool
from openrtc.observability.resident_set import process_resident_set_bytes
from openrtc.runtime.coroutine_server import _CoroutineAgentServer

from .conftest import LiveKitDevServer

_REQUIRED_PROVIDER_ENV = ("OPENAI_API_KEY",)
_SESSIONS = 5
_LATENCY_SAMPLE_INTERVAL_SECONDS = 0.01

# Shared across the agent instances spawned by the pool: each session records
# whether it could resolve its own job context.
_CONTEXT_PROBE: dict[str, bool] = {}


def _provider_credentials_available() -> bool:
    return all(os.environ.get(name) for name in _REQUIRED_PROVIDER_ENV)


class _ContextProbeAgent(Agent):
    """A minimal agent that records whether get_job_context() works on enter."""

    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are a tiny smoke-test agent. Greet the caller in one short "
                "sentence and then stop talking."
            )
        )

    async def on_enter(self) -> None:
        # The common user pattern: reach the job context for room/metadata or
        # to register a shutdown callback. Record success rather than raising,
        # so the assertion below reports the real cause cleanly.
        try:
            ctx = get_job_context()
            _CONTEXT_PROBE[ctx.room.name] = True
        except RuntimeError:
            # No job context: the coroutine executor never set _JobContextVar.
            with contextlib.suppress(Exception):
                _CONTEXT_PROBE.setdefault("<unresolved>", False)


async def _sample_loop_latency(stop: asyncio.Event, samples: list[float]) -> None:
    """Background task: event-loop scheduler wakeup latency in milliseconds."""
    while not stop.is_set():
        target = time.monotonic() + _LATENCY_SAMPLE_INTERVAL_SECONDS
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                stop.wait(), timeout=_LATENCY_SAMPLE_INTERVAL_SECONDS
            )
        samples.append(max(0.0, (time.monotonic() - target) * 1000.0))


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


@pytest.mark.integration
@pytest.mark.asyncio
async def test_realroom_sessions_resolve_job_context_and_report_latency(
    livekit_dev_server: LiveKitDevServer,
) -> None:
    """N concurrent real-provider sessions resolve their job context, no failures."""
    if not _provider_credentials_available():
        missing = ", ".join(
            name for name in _REQUIRED_PROVIDER_ENV if not os.environ.get(name)
        )
        pytest.skip(f"required provider credentials not set in environment: {missing}")

    os.environ["LIVEKIT_URL"] = livekit_dev_server.url
    os.environ["LIVEKIT_API_KEY"] = livekit_dev_server.api_key
    os.environ["LIVEKIT_API_SECRET"] = livekit_dev_server.api_secret

    _CONTEXT_PROBE.clear()

    pool = AgentPool(
        isolation="coroutine",
        max_concurrent_sessions=10,
        default_stt="openai/gpt-4o-mini-transcribe",
        default_llm="openai/gpt-4.1-mini",
        default_tts="openai/gpt-4o-mini-tts",
    )
    pool.add("probe", _ContextProbeAgent, greeting="Hello from the probe agent.")

    server = pool.server
    assert isinstance(server, _CoroutineAgentServer)

    stop = asyncio.Event()
    latency_samples: list[float] = []
    sampler = asyncio.create_task(_sample_loop_latency(stop, latency_samples))
    baseline_rss = process_resident_set_bytes()

    runner = asyncio.create_task(server.run(devmode=True, unregistered=True))
    try:
        deadline = asyncio.get_event_loop().time() + 30.0
        while server.coroutine_pool is None or not server.coroutine_pool.started:
            if asyncio.get_event_loop().time() > deadline:
                pytest.fail("CoroutinePool did not start within 30s")
            await asyncio.sleep(0.1)

        async def _drive_session(idx: int) -> None:
            await server.simulate_job(room=f"probe-room-{idx}", fake_job=True)

        await asyncio.gather(*(_drive_session(i) for i in range(_SESSIONS)))

        pool_obj = server.coroutine_pool
        assert pool_obj is not None
        deadline = asyncio.get_event_loop().time() + 60.0
        while pool_obj.processes:
            if asyncio.get_event_loop().time() > deadline:
                pytest.fail(f"sessions did not drain; alive: {len(pool_obj.processes)}")
            await asyncio.sleep(0.1)

        snapshot = pool.runtime_snapshot()
        peak_rss = process_resident_set_bytes()
        p99 = _percentile(latency_samples, 99.0)
        print(
            f"\n[realroom] sessions={_SESSIONS} "
            f"started={snapshot.total_sessions_started} "
            f"failures={snapshot.total_session_failures} "
            f"loop_p99_ms={p99:.2f} "
            f"baseline_rss_mb={(baseline_rss or 0) / 1024 / 1024:.0f} "
            f"peak_rss_mb={(peak_rss or 0) / 1024 / 1024:.0f}"
        )

        # (a) Correctness: every session ran and none failed.
        assert snapshot.total_sessions_started == _SESSIONS
        assert snapshot.total_session_failures == 0

        # (b) The job-context bug: every session must have resolved its ctx,
        #     and none recorded the "<unresolved>" sentinel.
        assert "<unresolved>" not in _CONTEXT_PROBE, (
            "at least one session could not resolve get_job_context() "
            "(coroutine executor did not set the job context)"
        )
        assert len(_CONTEXT_PROBE) == _SESSIONS, (
            f"expected {_SESSIONS} resolved contexts, got {sorted(_CONTEXT_PROBE)}"
        )

        # p99 is a printed diagnostic only (see [realroom] line above); the
        # throughput-vs-session-count gate lives in tests/benchmarks/throughput.py.
    finally:
        stop.set()
        await sampler
        await server.aclose()
        with contextlib.suppress(TimeoutError, asyncio.CancelledError, Exception):
            await asyncio.wait_for(runner, timeout=10.0)
