"""Real-audio throughput benchmark for coroutine-mode density (MAH-163).

Measures event-loop scheduler p99 latency under N concurrent voice sessions
doing real per-frame work, separating the startup burst from steady state. The
headline is the largest N whose *steady-state* p99 stays under an SLO: that is
the defensible "sessions per worker" number, unlike the sleep-stub density gate
(``density.py``) which only proves memory, not throughput.

Why this measures the right thing: the continuous on-loop CPU cost in a voice
session is per-frame VAD inference (~50 times a second per session), all sharing
one GIL. Network calls to STT/LLM/TTS are async I/O and do not block the loop,
so they are intentionally not modelled here.

Workloads:

- ``vad`` (default): each session runs the real Silero VAD over synthetic
  16 kHz PCM at 50 fps. Requires the Silero ONNX weights (downloaded on first
  use), so it needs network on a cold cache.
- ``cpu``: a deterministic synthetic per-frame cost (no model, no network), used
  by the smoke test and for offline runs.

Run:

    uv run python tests/benchmarks/throughput.py                     # vad, default sweep
    uv run python tests/benchmarks/throughput.py --sessions 1,5,10,25,50
    uv run python tests/benchmarks/throughput.py --workload cpu --json
    uv run python tests/benchmarks/throughput.py --slo-ms 100 --csv out.csv --plot chart.png

Report-only: this is not a pass/fail CI gate. p99 latency on shared CI runners
is noisy; gate on it only on dedicated hardware with median-of-N runs.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import statistics
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from openrtc.observability.metrics import process_resident_set_bytes

_FRAME_S = 0.02  # 20 ms per frame -> 50 fps, the live audio cadence
_SAMPLE_INTERVAL_S = 0.005
_DEFAULT_SESSIONS = (1, 5, 10, 25, 50, 75, 100)
_DEFAULT_WARMUP_S = 2.0
_DEFAULT_MEASURE_S = 3.0
_DEFAULT_SLO_MS = 100.0

SessionFactory = Callable[[asyncio.Event], Awaitable[None]]


@dataclass
class NResult:
    """Steady-state result for one session count."""

    sessions: int
    startup_p99_ms: float
    steady_p99_ms: float
    steady_median_ms: float
    peak_rss_mb: float | None
    samples: int


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (no numpy dependency on the hot path)."""
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


async def _pace(frame_start: float, stop: asyncio.Event) -> None:
    """Sleep until the next 20 ms frame boundary, interruptible by ``stop``."""
    delay = _FRAME_S - (time.monotonic() - frame_start)
    if delay <= 0:
        await asyncio.sleep(0)  # yield without extra delay if we overran
        return
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=delay)


# --- workloads -------------------------------------------------------------

_BURN_MAT = np.random.RandomState(0).rand(96, 96).astype(np.float32)


def _burn_once() -> None:
    """One frame of synthetic on-loop CPU cost (~VAD-inference-sized)."""
    np.dot(_BURN_MAT, _BURN_MAT)


async def _cpu_session(stop: asyncio.Event) -> None:
    """Synthetic session: a fixed CPU cost every frame. No model, no network."""
    while not stop.is_set():
        start = time.monotonic()
        _burn_once()
        await _pace(start, stop)


def _make_vad_session(vad: Any) -> SessionFactory:
    """Build a session runner that streams synthetic PCM through the real VAD."""
    from livekit import rtc

    samples = int(16000 * _FRAME_S)  # 320 samples per 20 ms frame at 16 kHz
    pcm = np.zeros(samples, dtype=np.int16).tobytes()

    async def _runner(stop: asyncio.Event) -> None:
        stream = vad.stream()

        async def _consume() -> None:
            with contextlib.suppress(Exception):
                async for _ev in stream:
                    pass

        consume = asyncio.create_task(_consume())
        try:
            while not stop.is_set():
                start = time.monotonic()
                stream.push_frame(
                    rtc.AudioFrame(
                        data=pcm,
                        sample_rate=16000,
                        num_channels=1,
                        samples_per_channel=samples,
                    )
                )
                await _pace(start, stop)
        finally:
            with contextlib.suppress(Exception):
                stream.end_input()
            with contextlib.suppress(Exception, TimeoutError):
                await asyncio.wait_for(consume, timeout=2.0)
            with contextlib.suppress(Exception):
                await stream.aclose()

    return _runner


def _build_factory(workload: str) -> SessionFactory:
    if workload == "cpu":
        return _cpu_session
    if workload == "vad":
        from livekit.plugins import silero

        vad = silero.VAD.load()  # downloads ONNX weights on a cold cache
        return _make_vad_session(vad)
    raise ValueError(f"unknown workload {workload!r}; expected 'vad' or 'cpu'")


# --- harness ---------------------------------------------------------------


async def _sample_loop_latency(stop: asyncio.Event, out: list[float]) -> None:
    """Record event-loop wakeup latency (ms) until ``stop`` is set."""
    while not stop.is_set():
        target = time.monotonic() + _SAMPLE_INTERVAL_S
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=_SAMPLE_INTERVAL_S)
        out.append(max(0.0, (time.monotonic() - target) * 1000.0))


async def _sample_peak_rss(stop: asyncio.Event, peak: list[int]) -> None:
    while not stop.is_set():
        rss = process_resident_set_bytes()
        if rss is not None and rss > peak[0]:
            peak[0] = rss
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=_SAMPLE_INTERVAL_S)


async def _sample_window(
    seconds: float, latency: list[float], peak_rss: list[int] | None = None
) -> None:
    stop = asyncio.Event()
    tasks = [asyncio.create_task(_sample_loop_latency(stop, latency))]
    if peak_rss is not None:
        tasks.append(asyncio.create_task(_sample_peak_rss(stop, peak_rss)))
    await asyncio.sleep(seconds)
    stop.set()
    await asyncio.gather(*tasks)


async def run_one(
    sessions: int,
    session_factory: SessionFactory,
    *,
    warmup_s: float,
    measure_s: float,
) -> NResult:
    """Run ``sessions`` concurrent session runners; sample startup vs steady."""
    stop = asyncio.Event()
    runners = [asyncio.create_task(session_factory(stop)) for _ in range(sessions)]

    startup: list[float] = []
    steady: list[float] = []
    peak_rss = [0]
    try:
        await _sample_window(warmup_s, startup)
        await _sample_window(measure_s, steady, peak_rss)
    finally:
        stop.set()
        await asyncio.gather(*runners, return_exceptions=True)

    return NResult(
        sessions=sessions,
        startup_p99_ms=round(_percentile(startup, 99.0), 3),
        steady_p99_ms=round(_percentile(steady, 99.0), 3),
        steady_median_ms=round(statistics.median(steady) if steady else 0.0, 3),
        peak_rss_mb=round(peak_rss[0] / (1024 * 1024), 1) if peak_rss[0] else None,
        samples=len(steady),
    )


async def run_sweep(
    session_counts: list[int],
    *,
    workload: str = "vad",
    warmup_s: float = _DEFAULT_WARMUP_S,
    measure_s: float = _DEFAULT_MEASURE_S,
) -> list[NResult]:
    """Run the throughput sweep across the given session counts (sequentially)."""
    factory = _build_factory(workload)
    return [
        await run_one(count, factory, warmup_s=warmup_s, measure_s=measure_s)
        for count in session_counts
    ]


def sustainable_sessions(results: list[NResult], slo_ms: float) -> int:
    """Largest session count whose steady-state p99 stays under the SLO."""
    ok = [r.sessions for r in results if r.steady_p99_ms <= slo_ms]
    return max(ok) if ok else 0


# --- reporting -------------------------------------------------------------


def _format_chart(results: list[NResult], slo_ms: float) -> str:
    if not results:
        return "(no results)"
    worst = max(r.steady_p99_ms for r in results) or 1.0
    width = 40
    lines = ["", "steady-state event-loop p99 (ms) by session count:"]
    for r in results:
        bars = int((r.steady_p99_ms / worst) * width)
        flag = "" if r.steady_p99_ms <= slo_ms else "  <- over SLO"
        lines.append(
            f"  N={r.sessions:>4}  {'#' * bars:<{width}} {r.steady_p99_ms:7.2f}{flag}"
        )
    return "\n".join(lines)


def _format_human(results: list[NResult], slo_ms: float) -> str:
    lines = [
        f"{'sessions':>8}  {'startup_p99':>11}  {'steady_p99':>10}  "
        f"{'steady_med':>10}  {'peak_rss_mb':>11}",
    ]
    for r in results:
        rss = "n/a" if r.peak_rss_mb is None else f"{r.peak_rss_mb:.0f}"
        lines.append(
            f"{r.sessions:>8}  {r.startup_p99_ms:>11.2f}  {r.steady_p99_ms:>10.2f}  "
            f"{r.steady_median_ms:>10.2f}  {rss:>11}"
        )
    lines.append(_format_chart(results, slo_ms))
    n = sustainable_sessions(results, slo_ms)
    lines.append("")
    lines.append(
        f"sustainable sessions at steady-state p99 <= {slo_ms:.0f} ms: {n}"
        if n
        else f"no tested session count held steady-state p99 <= {slo_ms:.0f} ms"
    )
    return "\n".join(lines)


def _write_csv(results: list[NResult], path: str) -> None:
    header = (
        "sessions,startup_p99_ms,steady_p99_ms,steady_median_ms,peak_rss_mb,samples"
    )

    def _row(r: NResult) -> str:
        rss = "" if r.peak_rss_mb is None else f"{r.peak_rss_mb}"
        return (
            f"{r.sessions},{r.startup_p99_ms},{r.steady_p99_ms},"
            f"{r.steady_median_ms},{rss},{r.samples}"
        )

    rows = [header, *[_row(r) for r in results]]
    with open(path, "w") as handle:
        handle.write("\n".join(rows) + "\n")


def _write_plot(results: list[NResult], slo_ms: float, path: str) -> None:
    try:
        import matplotlib as mpl

        mpl.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed; skipping --plot", file=sys.stderr)
        return
    xs = [r.sessions for r in results]
    ys = [r.steady_p99_ms for r in results]
    plt.figure()
    plt.plot(xs, ys, marker="o", label="steady-state p99")
    plt.axhline(slo_ms, linestyle="--", label=f"SLO {slo_ms:.0f} ms")
    plt.xlabel("concurrent sessions per worker")
    plt.ylabel("event-loop p99 latency (ms)")
    plt.title("OpenRTC coroutine throughput")
    plt.legend()
    plt.savefig(path)
    print(f"wrote plot to {path}")


def _parse_sessions(raw: str) -> list[int]:
    return [int(piece) for piece in raw.split(",") if piece.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--sessions",
        type=_parse_sessions,
        default=list(_DEFAULT_SESSIONS),
        help="comma-separated session counts to sweep (default 1,5,10,25,50,75,100)",
    )
    parser.add_argument(
        "--workload", choices=("vad", "cpu"), default="vad", help="per-frame workload"
    )
    parser.add_argument("--warmup", type=float, default=_DEFAULT_WARMUP_S)
    parser.add_argument("--measure", type=float, default=_DEFAULT_MEASURE_S)
    parser.add_argument("--slo-ms", type=float, default=_DEFAULT_SLO_MS)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument("--csv", type=str, default=None, help="also write a CSV file")
    parser.add_argument("--plot", type=str, default=None, help="also write a PNG plot")
    args = parser.parse_args(argv)

    results = asyncio.run(
        run_sweep(
            args.sessions,
            workload=args.workload,
            warmup_s=args.warmup,
            measure_s=args.measure,
        )
    )

    if args.csv:
        _write_csv(results, args.csv)
    if args.plot:
        _write_plot(results, args.slo_ms, args.plot)

    if args.json:
        print(
            json.dumps(
                {
                    "workload": args.workload,
                    "slo_ms": args.slo_ms,
                    "sustainable_sessions": sustainable_sessions(results, args.slo_ms),
                    "results": [asdict(r) for r in results],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(_format_human(results, args.slo_ms))
    return 0


if __name__ == "__main__":
    sys.exit(main())
