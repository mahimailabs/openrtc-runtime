"""Density benchmark: N concurrent simulated sessions in one CoroutinePool.

Phase 1 success gate from ``docs/design/v0.1.md`` §7: ``>= 50 concurrent
sessions per worker process at <= 4 GB peak RSS, no errors``.

Run as a script:

    uv run python tests/benchmarks/density.py
    uv run python tests/benchmarks/density.py --sessions 50 --rss-budget-mb 4096
    uv run python tests/benchmarks/density.py --sessions 100 --json

Or import :func:`run_density_benchmark` from a pytest harness.

The benchmark launches the same coroutine stack the smoke test exercises,
but with N concurrent ``CoroutineJobExecutor`` instances. Each entrypoint
allocates a small buffer (representing per-session audio + conversation
state), holds it during the simulated session, and exits. We sample RSS
at a short interval throughout the run and record the peak.

Exit code 0 on success; ``2`` on RSS budget breach; ``3`` on any session
error. Stdout is human-readable by default; ``--json`` switches to a
single JSON object the next pipeline step can consume.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import multiprocessing as mp
import os
import platform
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace
from typing import Any

import psutil
from livekit.agents import JobExecutorType

from openrtc.execution.coroutine import CoroutinePool
from openrtc.observability.metrics import process_resident_set_bytes

# Per-session allocation in bytes, chosen to be non-trivial but well below
# the 60 MB target so this benchmark stresses task-scheduling overhead, not
# allocator pressure. The §8.4 real-LiveKit integration test will validate
# the realistic per-session memory budget.
_SESSION_ALLOCATION_BYTES = 5 * 1024 * 1024  # 5 MB

_RSS_SAMPLE_INTERVAL_SECONDS = 0.05
_SESSION_HOLD_SECONDS = 1.0
_LATENCY_SAMPLE_INTERVAL_SECONDS = 0.01


@dataclass
class DensityResult:
    sessions: int
    successes: int
    failures: int
    rss_budget_mb: int
    peak_rss_mb: float | None
    baseline_rss_mb: float | None
    delta_rss_mb: float | None
    elapsed_seconds: float
    rss_within_budget: bool
    scheduler_latency_ms: dict[str, float] = field(default_factory=dict)
    hardware: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _hardware_fingerprint() -> dict[str, Any]:
    """Capture the host signature so benchmark results stay reproducible."""
    uname = platform.uname()
    total_ram_bytes = psutil.virtual_memory().total
    return {
        "cpu_model": platform.processor() or uname.machine,
        "cpu_count": os.cpu_count(),
        "total_ram_gb": round(total_ram_bytes / (1024**3), 2),
        "kernel": f"{uname.system} {uname.release}",
        "python_version": platform.python_version(),
    }


def _stub_running_job_info(job_id: str) -> Any:
    """Minimal fake_job RunningJobInfo stand-in (only ``job.id`` + ``fake_job`` are read)."""
    return SimpleNamespace(
        job=SimpleNamespace(id=job_id),
        fake_job=True,
        worker_id="density-bench",
    )


def _build_pool(*, max_concurrent_sessions: int) -> CoroutinePool:
    """Build a CoroutinePool with a session entrypoint that holds a buffer."""

    successes: list[str] = []
    failures: list[str] = []

    async def _session_entrypoint(ctx: Any) -> None:
        # Hold a per-session buffer to exercise the per-session memory
        # footprint, then yield + exit.
        _buffer = bytearray(_SESSION_ALLOCATION_BYTES)
        try:
            await asyncio.sleep(_SESSION_HOLD_SECONDS)
        finally:
            del _buffer
        successes.append(getattr(ctx, "session_id", ""))

    pool = CoroutinePool(
        initialize_process_fnc=lambda _proc: None,
        job_entrypoint_fnc=_session_entrypoint,
        session_end_fnc=None,
        num_idle_processes=0,
        initialize_timeout=10.0,
        close_timeout=15.0,
        inference_executor=None,
        job_executor_type=JobExecutorType.PROCESS,
        mp_ctx=mp.get_context(),
        memory_warn_mb=0.0,
        memory_limit_mb=0.0,
        http_proxy=None,
        loop=asyncio.new_event_loop(),
        max_concurrent_sessions=max_concurrent_sessions,
    )

    def _build_ctx(info: Any) -> Any:
        return SimpleNamespace(
            proc=pool.shared_process,
            job=info.job,
            room=SimpleNamespace(name=f"density-{info.job.id}", metadata=None),
            session_id=info.job.id,
        )

    pool._build_job_context = _build_ctx  # type: ignore[assignment]
    pool._density_results = {"successes": successes, "failures": failures}  # type: ignore[attr-defined]
    return pool


async def _sample_rss(stop: asyncio.Event, samples: list[int]) -> None:
    """Background task: sample resident set bytes until ``stop`` is set."""
    while not stop.is_set():
        rss = process_resident_set_bytes()
        if rss is not None:
            samples.append(rss)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=_RSS_SAMPLE_INTERVAL_SECONDS)


async def _sample_loop_latency(stop: asyncio.Event, samples: list[float]) -> None:
    """Background task: measure scheduler wakeup latency in milliseconds.

    A small ``asyncio.sleep`` is requested every interval; the delta between
    the requested wakeup time and the actual return time is the loop's
    scheduling latency. Under heavy task pressure this rises and signals
    starvation of the event loop.
    """
    while not stop.is_set():
        target = time.monotonic() + _LATENCY_SAMPLE_INTERVAL_SECONDS
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(_LATENCY_SAMPLE_INTERVAL_SECONDS)
        actual = time.monotonic()
        samples.append(max(0.0, (actual - target) * 1000.0))


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (no numpy dependency)."""
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


async def run_density_benchmark(
    *,
    sessions: int,
    rss_budget_mb: int,
) -> DensityResult:
    """Drive N concurrent simulated sessions through a CoroutinePool."""
    notes: list[str] = []

    baseline_rss = process_resident_set_bytes()
    if baseline_rss is None:
        notes.append("RSS unavailable on this platform; budget check skipped.")

    pool = _build_pool(max_concurrent_sessions=sessions)
    stop_event = asyncio.Event()
    samples: list[int] = []
    latency_samples: list[float] = []
    sampler = asyncio.create_task(_sample_rss(stop_event, samples))
    latency_sampler = asyncio.create_task(
        _sample_loop_latency(stop_event, latency_samples)
    )

    start = time.monotonic()
    try:
        await pool.start()
        for index in range(sessions):
            await pool.launch_job(_stub_running_job_info(f"job-{index:04d}"))

        # Drain every entrypoint task.
        for ex in list(pool.processes):
            task = getattr(ex, "_task", None)
            if task is not None:
                await task
        await pool.aclose()
    finally:
        elapsed = time.monotonic() - start
        stop_event.set()
        await sampler
        await latency_sampler

    bookkeeping = pool._density_results  # type: ignore[attr-defined]
    successes = len(bookkeeping["successes"])
    failures = len(bookkeeping["failures"])

    peak_rss = max(samples) if samples else None
    peak_rss_mb = peak_rss / (1024 * 1024) if peak_rss is not None else None
    baseline_rss_mb = baseline_rss / (1024 * 1024) if baseline_rss is not None else None
    delta_rss_mb = (
        peak_rss_mb - baseline_rss_mb
        if peak_rss_mb is not None and baseline_rss_mb is not None
        else None
    )

    rss_within_budget = peak_rss_mb is None or peak_rss_mb <= rss_budget_mb

    if latency_samples:
        scheduler_latency_ms = {
            "samples": float(len(latency_samples)),
            "median": round(statistics.median(latency_samples), 3),
            "p99": round(_percentile(latency_samples, 99.0), 3),
            "max": round(max(latency_samples), 3),
        }
    else:
        scheduler_latency_ms = {}
        notes.append("scheduler latency unavailable: no samples collected.")

    return DensityResult(
        sessions=sessions,
        successes=successes,
        failures=failures,
        rss_budget_mb=rss_budget_mb,
        peak_rss_mb=peak_rss_mb,
        baseline_rss_mb=baseline_rss_mb,
        delta_rss_mb=delta_rss_mb,
        elapsed_seconds=elapsed,
        rss_within_budget=rss_within_budget,
        scheduler_latency_ms=scheduler_latency_ms,
        hardware=_hardware_fingerprint(),
        notes=notes,
    )


def _format_human(result: DensityResult) -> str:
    def _mb(value: float | None) -> str:
        return f"{value:.1f} MB" if value is not None else "n/a"

    lines = [
        f"sessions:          {result.sessions}",
        f"successes:         {result.successes}",
        f"failures:          {result.failures}",
        f"baseline RSS:      {_mb(result.baseline_rss_mb)}",
        f"peak RSS:          {_mb(result.peak_rss_mb)}",
        f"delta RSS:         {_mb(result.delta_rss_mb)}",
        f"RSS budget:        {result.rss_budget_mb} MB",
        f"within budget:     {result.rss_within_budget}",
        f"elapsed:           {result.elapsed_seconds:.2f} s",
    ]
    if result.scheduler_latency_ms:
        lines.extend(
            [
                "scheduler latency (ms):",
                f"  samples:         {int(result.scheduler_latency_ms['samples'])}",
                f"  median:          {result.scheduler_latency_ms['median']:.3f}",
                f"  p99:             {result.scheduler_latency_ms['p99']:.3f}",
                f"  max:             {result.scheduler_latency_ms['max']:.3f}",
            ]
        )
    if result.hardware:
        lines.append("hardware:")
        for key, value in result.hardware.items():
            lines.append(f"  {key}: {value}")
    if result.notes:
        lines.append("notes:")
        lines.extend(f"  - {note}" for note in result.notes)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--sessions",
        type=int,
        default=50,
        help="Number of concurrent simulated sessions (default: 50).",
    )
    parser.add_argument(
        "--rss-budget-mb",
        type=int,
        default=4096,
        help="Peak RSS budget in MB; non-zero exit if exceeded (default: 4096).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a single JSON object instead of human-readable text.",
    )
    args = parser.parse_args(argv)

    result = asyncio.run(
        run_density_benchmark(
            sessions=args.sessions,
            rss_budget_mb=args.rss_budget_mb,
        )
    )

    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    else:
        print(_format_human(result))

    if result.failures > 0:
        return 3
    if not result.rss_within_budget:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
