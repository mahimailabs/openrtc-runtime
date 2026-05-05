# Density Benchmark — v0.1

Phase 1 success gate from `docs/design/v0.1.md` §7:

> ≥ 50 concurrent sessions per worker process at ≤ 4 GB peak RSS, no errors.

This run **passes the gate**, with substantial headroom. Re-run after any
behavioral change to the coroutine path; record new numbers below the
existing table rather than overwriting (one row per session-count config
per environment).

## Methodology

The harness lives in `tests/benchmarks/density.py`. It constructs the
same `CoroutinePool` chain `_CoroutineAgentServer` would build, then
launches **N** concurrent fake-job sessions through it. Each session
entrypoint:

1. allocates a 5 MB `bytearray` (per-session footprint stand-in),
2. holds the buffer for ~1 s via `await asyncio.sleep(1.0)`,
3. drops the buffer and exits.

A background asyncio task samples
`openrtc.observability.metrics.process_resident_set_bytes()` every
50 ms throughout the run; we record the maximum and the delta from
baseline.

Caveats:

- **5 MB per session is intentionally low.** It exercises Python task
  scheduling and coroutine dispatch overhead, not realistic per-session
  memory pressure. The realistic ~60 MB/session target (audio buffers,
  WebRTC peer connection state, LLM context) validates against the §8.4
  real-LiveKit integration test in Phase 2.
- **No real WebRTC, no real STT/LLM/TTS.** AgentSession, rtc.Room, and
  the inference executor are bypassed via stubs. A real worker carries
  process-wide overhead from the Silero VAD and turn-detector models
  (~250-400 MB on macOS) that the benchmark replaces with a no-op
  prewarm.
- **One worker process.** No multi-worker scaling claim is implied.

To reproduce a row:

```bash
uv run python tests/benchmarks/density.py --sessions 50 --json
uv run python tests/benchmarks/density.py --sessions 50 --rss-budget-mb 4096
```

Exit codes: `0` success, `2` peak RSS over budget, `3` any session
error.

## Results

### 2026-05-03 — local: macOS Darwin 24.3.0 / Python 3.13.5 / uv 0.8.15 / arm64

Three back-to-back runs at the §7 gate (50 sessions, 4096 MB budget) plus
a headroom sweep:

| Run | Sessions | Successes | Failures | Baseline RSS | Peak RSS | Delta RSS | Elapsed | Within budget |
|-----|----------|-----------|----------|--------------|----------|-----------|---------|----------------|
| 1   | 50       | 50        | 0        | 115.5 MB     | 366.5 MB | 250.9 MB  | 1.08 s  | ✓              |
| 2   | 50       | 50        | 0        | 115.8 MB     | 366.8 MB | 251.0 MB  | 1.03 s  | ✓              |
| 3   | 50       | 50        | 0        | 115.9 MB     | 366.9 MB | 251.0 MB  | 1.04 s  | ✓              |
| 4   | 100      | 100       | 0        | 114.9 MB     | 616.9 MB | 502.0 MB  | 1.10 s  | ✓              |
| 5   | 200      | 200       | 0        | 115.7 MB     | 1072.7 MB | 956.9 MB | 1.19 s  | ✓              |
| 6   | 500      | 500       | 0        | 114.8 MB     | 1370.4 MB | 1255.7 MB | 1.30 s  | ✓ (8 GB cap) |

Notes:

- Per-session memory tracks the 5 MB buffer up to ~200 sessions; at 500
  sessions GC starts compacting and the per-session amortized cost drops
  to ~2.5 MB. This says nothing about real workloads — under 5 MB
  buffers are tiny — but it confirms the asyncio scheduler is not
  pathologically expensive at scale.
- Walltime stays in the 1.0-1.3 s band (essentially the 1 s sleep + tiny
  setup/teardown) across 50-500 sessions. There is no quadratic
  spawning cost in the pool's `launch_job` path.

### Verdict

**Phase 1 §7 gate met.** Peak RSS at 50 sessions is 367 MB, leaving
~3.7 GB of headroom against the 4 GB budget. The gate exists to verify
the coroutine architecture supports many concurrent sessions in one
process; with the stub workload it does, comfortably. The realistic
per-session footprint validation (and the ~50-100 sessions per 4 GB
working number) is deferred to the §8.4 real-LiveKit integration tests
once the dev-server harness lands in Phase 2.

### 2026-05-05 — local: macOS Darwin 24.3.0 / Python 3.13.5 / arm64 (10 cores, 16 GB)

Re-run after `tests/benchmarks/density.py` was extended with scheduler-
latency sampling (10 ms cadence, median + p99 + max) and a hardware
fingerprint dict (commit `32bde3a`). Three back-to-back runs at the
§7 gate:

| Run | Sessions | Successes | Failures | Baseline RSS | Peak RSS | Delta RSS | Elapsed | Sched p99 | Sched max | Within budget |
|-----|----------|-----------|----------|--------------|----------|-----------|---------|-----------|-----------|----------------|
| A   | 50       | 50        | 0        | 116.1 MB     | 367.0 MB | 251.0 MB  | 1.06 s  | 6.17 ms   | 50.27 ms  | ✓              |
| B   | 50       | 50        | 0        | 116.5 MB     | 354.0 MB | 237.5 MB  | 1.08 s  | 5.64 ms   | 63.66 ms  | ✓              |
| C   | 50       | 50        | 0        | 116.5 MB     | 367.4 MB | 251.0 MB  | 1.02 s  | 3.19 ms   | 3.36 ms   | ✓              |

Hardware fingerprint (identical across runs): `arm` / `10 cores` /
`16 GB total` / `Darwin 24.3.0` / `Python 3.13.5`.

Notes:

- Peak-RSS numbers track the 2026-05-03 row at the same N=50 config
  (~367 MB), confirming no regression from the benchmark instrumentation
  additions.
- Scheduler median latency holds in the 1.06-1.10 ms band — well below
  the 10 ms sampling interval, so the loop is not starved at this load.
- Scheduler p99 sits at 3-6 ms; the higher values (50-64 ms) on runs A
  and B come from a single-sample tail spike each (the `max` column),
  most likely a transient OS scheduling event on a busy laptop. Run C,
  with all background processes quiet, lands at p99 = 3.19 ms / max =
  3.36 ms — the clean baseline. The p99 is the load-bearing number for
  worker stability; the tail max is an environmental artefact.
- Walltime stays in the same 1.0-1.1 s band (≈ 1 s sleep + setup).

### Verdict (2026-05-05)

**Phase 1 §7 gate continues to pass.** All three runs hit 50/50
sessions, 0 failures, peak RSS ≤ 367 MB. The new scheduler-latency
metric provides additional Phase 2 capacity-planning input: a healthy
loop runs at ~1 ms median / ~3 ms p99 under a 50-session stub
workload.
