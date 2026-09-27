"""Measure the memory OpenRTC saves per session, on one machine, with real numbers.

OpenRTC's coroutine pool runs N sessions as asyncio tasks inside a single
process. Stock livekit-agents runs one OS process per session: on Linux it
forks each from a forkserver that preloaded the import graph (children share
those pages copy-on-write); on macOS and Windows it spawns a fresh interpreter.

This script measures both models the way they really run:

  * "process-per-session" (stock livekit-agents): N child processes started
    with the same start method livekit-agents uses on this OS, each holding a
    per-session buffer. We sum their memory, plus the forkserver's.

  * "OpenRTC coroutine pool" (the default isolation mode): import the stack
    ONCE, run N asyncio sessions in this single process, each holding the same
    per-session buffer.

Memory is PSS where the OS reports it (Linux): shared pages are split fairly
between the processes that share them, so the sum is the real total. RSS would
count every shared page once per process and overstate the process model.

This measures memory only. CPU, not memory, usually limits how many calls a
machine can serve; see the README's head-to-head benchmark.
No LiveKit server, no network, no model download required.

Run it:

    uv run python examples/density_demo.py                 # N = 16
    uv run python examples/density_demo.py --sessions 32
    uv run python examples/density_demo.py --sessions 50 --load-vad

Use --load-vad to also load the real Silero VAD in every session process (the
model livekit-agents loads per process in prewarm and OpenRTC shares). It
downloads ONNX weights on first run.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import multiprocessing as mp
import os
import sys
import time

import psutil

# Stand-in for one session's live audio plus conversation state. The real
# per-session cost is dominated by the shared-vs-per-process fixed cost, so
# the exact buffer size is not load-bearing; it just keeps each session honest.
_SESSION_BUFFER_MB = 5


def _memory_bytes(proc: psutil.Process) -> int:
    """PSS where available (Linux), else RSS."""
    info = proc.memory_full_info()
    return int(getattr(info, "pss", info.rss))


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
    """Sum the memory of N session processes plus their forkserver (MB)."""
    # Same start method livekit-agents uses: forkserver with the stack preloaded
    # on Linux (children share it copy-on-write), fresh spawn elsewhere.
    if sys.platform.startswith("linux"):
        ctx = mp.get_context("forkserver")
        ctx.set_forkserver_preload(["livekit.agents", "openrtc"])
    else:
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
    # Every descendant: the session processes and, on Linux, the forkserver
    # that holds the preloaded pages they share.
    for child in psutil.Process().children(recursive=True):
        with contextlib.suppress(psutil.Error):  # a child may have exited early
            total_bytes += _memory_bytes(child)

    stop_event.set()
    for p in procs:
        p.join()
    return total_bytes / (1024 * 1024)


async def measure_coroutine_model(sessions: int, load_vad: bool) -> float:
    """Memory of ONE process hosting N asyncio sessions (MB)."""
    _import_stack(load_vad)  # paid once, in this process

    async def _session() -> None:
        _buffer = bytearray(_SESSION_BUFFER_MB * 1024 * 1024)
        try:
            await asyncio.sleep(3600)  # stay alive until measured
        finally:
            del _buffer

    tasks = [asyncio.create_task(_session()) for _ in range(sessions)]
    await asyncio.sleep(0.5)  # let all sessions allocate + settle
    total_mb = _memory_bytes(psutil.Process(os.getpid())) / (1024 * 1024)

    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    return total_mb


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

    metric = "PSS" if sys.platform.startswith("linux") else "RSS"
    print(f"\nHosting {n} concurrent voice sessions. Measuring memory ({metric}).\n")

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
