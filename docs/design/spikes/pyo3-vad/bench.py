"""Measure parallel speedup under Python threads for three CPU-bound variants.

The decision-relevant metric is the parallel speedup with N threads:
- GIL-held work (pure Python, or Rust that holds the GIL) -> ~1x (serialized).
- Rust that releases the GIL (py.allow_threads) -> approaches N (up to cores).

This is the mechanism a Rust inference/frame kernel relies on to let N voice
sessions run truly concurrently instead of serializing on one core.
"""

import math
import threading
import time

import pyo3_vad_spike as m

THREADS = 8
RUST_ITERS = 60_000_000  # tuned so single-thread ~200ms in release Rust
PY_ITERS = RUST_ITERS // 30  # Python is ~30x slower per iter; keep single-thread comparable


def _time(fn, iters, n_threads):
    fn(iters // 20)  # warmup
    t0 = time.perf_counter()
    fn(iters)
    single = time.perf_counter() - t0
    threads = [threading.Thread(target=fn, args=(iters,)) for _ in range(n_threads)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    multi = time.perf_counter() - t0
    return single, multi, (single * n_threads) / multi


def py_busy(iters):
    acc = 0.0
    for i in range(iters):
        acc += math.sin(math.sqrt(i))
    return acc


def report(label, fn, iters):
    single, multi, speedup = _time(fn, iters, THREADS)
    print(
        f"{label:22s} single={single * 1000:6.0f}ms  {THREADS}x-threads={multi * 1000:6.0f}ms  "
        f"parallel-speedup={speedup:.2f}x  (ideal {THREADS}x)"
    )


if __name__ == "__main__":
    import os

    print(f"cores={os.cpu_count()}  threads={THREADS}\n")
    report("python (GIL-held)", py_busy, PY_ITERS)
    report("rust (holds GIL)", m.cpu_work_hold_gil, RUST_ITERS)
    report("rust (releases GIL)", m.cpu_work_release_gil, RUST_ITERS)
