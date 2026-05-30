"""Prove the OpenRTC density win, on one laptop, with real numbers.

The claim: livekit-agents runs roughly one OS process per session (about
3 GB each in production). OpenRTC's coroutine pool runs N sessions as
asyncio tasks inside a single process, so the heavy per-process cost
(Python interpreter, the livekit-agents import graph, and shared models
like Silero VAD and the turn detector) is paid ONCE instead of N times.

This script measures both models for real:

  * "process-per-session" (what vanilla livekit-agents does):
    spawn N subprocesses, each imports the agent stack and holds a
    per-session buffer. We sum the resident memory across all of them.

  * "OpenRTC coroutine pool" (the default isolation mode):
    import the stack ONCE, run N asyncio sessions in this single process,
    each holding the same per-session buffer. We read this process's
    resident memory.

Then it prints total memory each way, memory per session, and the ratio.
No LiveKit server, no network, no model download required.

Run it:

    uv run python examples/density_demo.py                 # N = 16
    uv run python examples/density_demo.py --sessions 32
    uv run python examples/density_demo.py --sessions 50 --load-vad

Use --load-vad to also load the real Silero VAD in every worker (the model
livekit-agents would load per process and OpenRTC shares). It downloads
ONNX weights on first run, then makes the gap even wider.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import multiprocessing as mp
import os
import time

import psutil

# Stand-in for one session's live audio plus conversation state. The real
# per-session cost is dominated by the shared-vs-per-process fixed cost, so
# the exact buffer size is not load-bearing; it just keeps each session honest.
_SESSION_BUFFER_MB = 5


def _import_stack(load_vad: bool) -> None:
    """Pay the per-process import cost that livekit-agents incurs per session."""
    import livekit.agents  # noqa: F401  (the real wheel, ~150 MB resident)

    import openrtc  # noqa: F401

    if load_vad:
        # The shared model OpenRTC loads once in prewarm and livekit-agents
        # loads in every worker process. Widens the gap; needs a one-time
        # weights download.
        from livekit.plugins import silero

        silero.VAD.load()


def _process_worker(ready: object, stop: object, load_vad: bool) -> None:
    """One subprocess == one session, the livekit-agents process-per-job model."""
    _import_stack(load_vad)
    _buffer = bytearray(_SESSION_BUFFER_MB * 1024 * 1024)  # noqa: F841
    ready.set()  # type: ignore[attr-defined]
    stop.wait()  # type: ignore[attr-defined]  hold the buffer until measured


def measure_process_model(sessions: int, load_vad: bool) -> float:
    """Sum resident memory of N independent worker processes (MB)."""
    # "spawn" matches LiveKit's default executor on macOS, so each child pays
    # the full fresh-interpreter import cost, exactly as in production.
    ctx = mp.get_context("spawn")
    ready_events = [ctx.Event() for _ in range(sessions)]
    stop_event = ctx.Event()
    procs = [
        ctx.Process(
            target=_process_worker, args=(ready_events[i], stop_event, load_vad)
        )
        for i in range(sessions)
    ]
    for p in procs:
        p.start()
    for ev in ready_events:
        ev.wait(timeout=120)  # every worker finished importing + allocated

    time.sleep(0.5)  # let resident memory settle
    total_bytes = 0
    for p in procs:
        with contextlib.suppress(
            psutil.NoSuchProcess
        ):  # a worker may have exited early
            total_bytes += psutil.Process(p.pid).memory_info().rss

    stop_event.set()
    for p in procs:
        p.join()
    return total_bytes / (1024 * 1024)


async def measure_coroutine_model(sessions: int, load_vad: bool) -> float:
    """Resident memory of ONE process hosting N asyncio sessions (MB)."""
    _import_stack(load_vad)  # paid once, in this process

    async def _session() -> None:
        _buffer = bytearray(_SESSION_BUFFER_MB * 1024 * 1024)
        try:
            await asyncio.sleep(3600)  # stay alive until measured
        finally:
            del _buffer

    tasks = [asyncio.create_task(_session()) for _ in range(sessions)]
    await asyncio.sleep(0.5)  # let all sessions allocate + settle
    rss_mb = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)

    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    return rss_mb


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--sessions", type=int, default=16, help="concurrent sessions (default 16)"
    )
    parser.add_argument(
        "--load-vad",
        action="store_true",
        help="also load real Silero VAD in every worker",
    )
    args = parser.parse_args()
    n = args.sessions

    print(f"\nHosting {n} concurrent voice sessions. Measuring resident memory.\n")

    # Process model first so this parent process stays light; the coroutine
    # measurement then imports the stack into this same process on purpose.
    process_mb = measure_process_model(n, args.load_vad)
    coroutine_mb = asyncio.run(measure_coroutine_model(n, args.load_vad))

    ratio = process_mb / coroutine_mb if coroutine_mb else float("inf")
    print(
        f"  livekit-agents (process per session): {process_mb:8.0f} MB total   "
        f"({process_mb / n:6.1f} MB/session)"
    )
    print(
        f"  OpenRTC coroutine pool (one process): {coroutine_mb:8.0f} MB total   "
        f"({coroutine_mb / n:6.1f} MB/session)"
    )
    print(f"\n  OpenRTC uses {ratio:.1f}x less memory for the same {n} sessions.\n")
    print("  Same agent code, both ways. In OpenRTC you flip one argument:")
    print('    AgentPool(isolation="process")    # the left column above')
    print('    AgentPool(isolation="coroutine")  # the right column (default)\n')


if __name__ == "__main__":
    main()
