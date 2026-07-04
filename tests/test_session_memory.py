"""Per-session memory attribution sampler (MAH-88).

Per-session RSS in one CPython process is not exactly measurable, so the sampler
reports an equal share of live process RSS across active sessions with a
per-session peak. These tests pin that contract: the shares sum back to process
RSS (the acceptance criterion), peaks are sticky, and ended sessions are pruned.
"""

from __future__ import annotations

import asyncio

import pytest

from openrtc.observability.session_memory import (
    SessionMemory,
    SessionMemorySampler,
)

_MB = 1024 * 1024


def _sampler(sessions: dict[str, str], rss_mb: float | None) -> SessionMemorySampler:
    return SessionMemorySampler(
        sessions_provider=lambda: sessions,
        rss_reader=lambda: None if rss_mb is None else int(rss_mb * _MB),
        interval=0.01,
    )


def test_equal_share_sums_to_process_rss() -> None:
    # Acceptance: 5 sessions running, attribution sums within 10% of process RSS.
    sessions = {f"s{i}": "agent" for i in range(5)}
    result = _sampler(sessions, 500.0).sample_once()

    assert len(result) == 5
    assert all(m.current_mb == 100.0 for m in result.values())
    total = sum(m.current_mb for m in result.values())
    assert abs(total - 500.0) <= 0.1 * 500.0


def test_carries_agent_name() -> None:
    result = _sampler({"s1": "sales"}, 200.0).sample_once()
    assert result["s1"] == SessionMemory("s1", "sales", 200.0, 200.0)


def test_peak_is_sticky_across_samples() -> None:
    sampler = _sampler({"s1": "a"}, 300.0)
    sampler.sample_once()  # current 300, peak 300
    sampler._rss_reader = lambda: 100 * _MB  # type: ignore[assignment]
    result = sampler.sample_once()  # current 100, peak stays 300
    assert result["s1"].current_mb == 100.0
    assert result["s1"].peak_mb == 300.0


def test_no_active_sessions_is_empty() -> None:
    assert _sampler({}, 500.0).sample_once() == {}


def test_rss_unavailable_is_empty() -> None:
    assert _sampler({"s1": "a"}, None).sample_once() == {}


def test_ended_session_pruned_from_peaks() -> None:
    sampler = SessionMemorySampler(
        sessions_provider=lambda: sampler_sessions,
        rss_reader=lambda: 200 * _MB,
        interval=0.01,
    )
    sampler_sessions = {"s1": "a", "s2": "a"}
    sampler.sample_once()
    assert set(sampler._peaks) == {"s1", "s2"}
    sampler_sessions = {"s1": "a"}  # s2 ended
    result = sampler.sample_once()
    assert set(sampler._peaks) == {"s1"}
    assert set(result) == {"s1"}


def test_snapshot_returns_latest() -> None:
    sampler = _sampler({"s1": "a"}, 150.0)
    assert sampler.snapshot() == {}
    sampler.sample_once()
    assert sampler.snapshot()["s1"].current_mb == 150.0


@pytest.mark.asyncio
async def test_run_loop_samples_then_stops() -> None:
    sampler = _sampler({"s1": "a"}, 250.0)
    stop = asyncio.Event()
    task = asyncio.create_task(sampler.run(stop))
    for _ in range(100):
        if sampler.snapshot():
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)
    assert sampler.snapshot()["s1"].current_mb == 250.0
