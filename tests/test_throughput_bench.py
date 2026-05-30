"""Smoke test for the throughput benchmark harness (MAH-163).

Loads ``tests/benchmarks/throughput.py`` and runs the deterministic ``cpu``
workload at small N with tiny windows, so the sweep -> startup/steady-state
split -> result path is exercised without a model, network, or meaningful
wall-clock cost. The realistic ``vad`` workload is run manually.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# The benchmark lives under tests/benchmarks/ and is normally run as a script;
# put that directory on the path so the smoke test can import it directly.
sys.path.insert(0, str(Path(__file__).parent / "benchmarks"))

import throughput  # noqa: E402  (path adjusted just above)


@pytest.mark.asyncio
async def test_throughput_cpu_sweep_smoke() -> None:
    results = await throughput.run_sweep(
        [1, 2], workload="cpu", warmup_s=0.05, measure_s=0.1
    )
    assert [r.sessions for r in results] == [1, 2]
    for r in results:
        assert r.samples > 0
        assert r.steady_p99_ms >= 0.0
        assert r.startup_p99_ms >= 0.0
    # Every count is well under a huge SLO, so the largest is sustainable.
    assert throughput.sustainable_sessions(results, slo_ms=10_000.0) == 2
    # No count clears an impossibly tight SLO.
    assert throughput.sustainable_sessions(results, slo_ms=0.0) == 0


@pytest.mark.asyncio
async def test_throughput_unknown_workload_raises() -> None:
    with pytest.raises(ValueError, match="unknown workload"):
        await throughput.run_sweep([1], workload="nonsense")
