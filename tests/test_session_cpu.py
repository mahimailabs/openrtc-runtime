"""Per-session CPU attribution via sampling (MAH-89).

The pure accumulator turns a stream of sampled running-session ids into
per-session shares; the acceptance is that three sessions doing different
workloads are distinguished. The sampler drives it from a background thread.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from openrtc.observability.session_cpu import (
    SessionCpuAccumulator,
    SessionCpuSampler,
    default_running_session_provider,
)


def test_accumulator_distinguishes_workloads() -> None:
    # Acceptance: 3 sessions, different workloads, attribution distinguishes them.
    acc = SessionCpuAccumulator()
    for _ in range(60):
        acc.record("A")
    for _ in range(30):
        acc.record("B")
    for _ in range(10):
        acc.record("C")

    snap = acc.snapshot({"A": "sales", "B": "support", "C": "sched"}, 0.01)

    assert snap["A"].cpu_pct == 60.0
    assert snap["B"].cpu_pct == 30.0
    assert snap["C"].cpu_pct == 10.0
    assert snap["A"].samples == 60
    assert snap["A"].cpu_seconds == 0.6
    assert snap["A"].agent_name == "sales"


def test_idle_samples_reduce_shares() -> None:
    acc = SessionCpuAccumulator()
    for _ in range(50):
        acc.record("A")
    for _ in range(50):
        acc.record(None)  # loop idle / framework code, not a session
    snap = acc.snapshot({"A": "a"}, 0.01)
    assert snap["A"].cpu_pct == 50.0


def test_empty_accumulator_is_zero() -> None:
    snap = SessionCpuAccumulator().snapshot({"A": "a"}, 0.01)
    assert snap["A"].cpu_pct == 0.0
    assert snap["A"].samples == 0


def test_ended_session_pruned() -> None:
    acc = SessionCpuAccumulator()
    for _ in range(10):
        acc.record("A")
    for _ in range(10):
        acc.record("B")
    snap = acc.snapshot({"A": "a"}, 0.01)  # B ended
    assert set(snap) == {"A"}
    # A now owns all remaining tracked samples of the active set.
    assert snap["A"].samples == 10


def test_sampler_sample_once_feeds_accumulator() -> None:
    sampler = SessionCpuSampler(
        sessions_provider=lambda: {"A": "a"},
        running_session_provider=lambda: "A",
    )
    for _ in range(5):
        sampler.sample_once()
    snap = sampler.report()
    assert snap["A"].samples == 5
    assert snap["A"].cpu_pct == 100.0
    assert sampler.snapshot()["A"].samples == 5


def test_sampler_thread_runs_then_stops() -> None:
    sampler = SessionCpuSampler(
        sessions_provider=lambda: {"A": "a"},
        running_session_provider=lambda: "A",
        sample_interval=0.005,
    )
    sampler.start()
    sampler.start()  # idempotent: still one thread
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if sampler.report().get("A") and sampler.snapshot()["A"].samples > 0:
                break
            time.sleep(0.01)
    finally:
        sampler.stop()
    assert sampler.snapshot()["A"].samples > 0
    assert sampler._thread is None
    sampler.stop()  # idempotent when already stopped


@pytest.mark.asyncio
async def test_default_provider_reads_running_task_tag() -> None:
    loop = asyncio.get_running_loop()
    current = asyncio.current_task()
    assert current is not None
    current._openrtc_session_id = "run-x"  # type: ignore[attr-defined]
    assert default_running_session_provider(loop) == "run-x"


def test_default_provider_none_when_no_running_task() -> None:
    loop = asyncio.new_event_loop()
    try:
        assert default_running_session_provider(loop) is None
    finally:
        loop.close()
