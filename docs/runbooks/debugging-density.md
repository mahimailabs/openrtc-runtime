---
title: Debugging Density
description: My pool feels slow, or one session is hot. A troubleshooting flow using openrtc top and the slow-session detector.
icon: stethoscope
---

# Debugging Density

Running many sessions in one worker is efficient until one session misbehaves and
you cannot tell which. This runbook is the flow for "my pool feels slow" or "one
session is hot", using [`openrtc top`](/cli/top) and the slow-session detector.
It assumes coroutine mode with introspection on (the default).

## 1. Look at the pool

Open the live inspector next to your worker:

```bash
openrtc top
```

Scan the table:

- **One `slow` row.** A session is blocking the shared event loop. Jump to
  [section 3](#3-a-session-is-blocking-the-loop).
- **One row with a high, sustained `cpu%`.** A session is CPU-heavy (a tight loop,
  a large sync transform). See [section 4](#4-a-session-is-cpu-hot).
- **`peak` climbing across the board, `mem(MB)` trending up.** Worker-level memory
  pressure. See [section 5](#5-the-worker-is-trending-toward-its-memory-limit).
- **Nothing stands out but latency is bad.** The bottleneck is likely in the voice
  pipeline (STT/LLM/TTS), which OpenRTC does not measure. See
  [section 6](#6-nothing-in-openrtc-explains-it).

Sort and filter to focus:

```bash
openrtc top --sort cpu_pct      # busiest sessions first
openrtc top --status slow       # only sessions blocking the loop
```

## 2. Confirm it is density, not a single wedged call

Press `s` to sort by `duration_s`. A single very long-lived session that should
have ended can look like load. If a call is stuck, that is a session bug (an
`await` that never resolves), not a density problem. Fix it in the agent.

## 3. A session is blocking the loop

A `slow` status means the detector measured the event loop stalling while that
session's task was on-CPU. Check the worker logs for the attribution line:

```
[slow-session] session_id=job-c1d550 blocked event loop for 320ms
```

The usual cause is a **synchronous blocking call** inside an otherwise async
agent: a sync HTTP client, `time.sleep`, a blocking file or DB call, or a heavy
CPU section run inline. The fix is always the same shape (get it off the loop):

- Use the async client (`aiohttp`/`httpx.AsyncClient`) instead of a sync one.
- Wrap unavoidable blocking work in `await asyncio.to_thread(...)`.
- Break large CPU loops into chunks that `await asyncio.sleep(0)` between them.

Lower `slow_session_threshold_ms` (default 50 ms) to catch smaller stalls while
hunting, e.g. `AgentPool(slow_session_threshold_ms=20)`.

<Note>
The detector reports the session and duration, not the exact source line (stack
sampling is deferred). Use the session id to find the call in that agent's code;
a block over ~50 ms in an async agent is almost always one sync call.
</Note>

## 4. A session is CPU-hot

A high, sustained `cpu%` without a `slow` status is a session doing real work
that is not (yet) blocking the loop, but it still competes for the one core.
Remember `cpu%` is a **sampled share**, not exact seconds: use it to rank
sessions, not to bill them. If one agent is consistently hot, move its heavy work
to `asyncio.to_thread`, or run that agent under `isolation="process"` so it gets
its own core and cannot starve the others.

## 5. The worker is trending toward its memory limit

`mem(MB)` is an **equal share** of process RSS, so per-session numbers sum back to
the real RSS (watch the trend, not any single row). If the total is climbing
toward your [`memory_limit_mb`](/cli), the worker will drain and restart when it
crosses the limit (coroutine caps are worker-level, not per-session). To find a
leak, restart with `isolation="process"` temporarily so the OS accounts memory
per session, or reduce `max_concurrent_sessions` to lower peak pressure.

## 6. Nothing in OpenRTC explains it

If sessions look healthy in `openrtc top` but calls are still slow, the
bottleneck is in the **voice pipeline** (STT, LLM, or TTS latency), which
OpenRTC does not see (it sees coroutines, not providers). That is
**voicegateway's** lane: cost, provider latency, and quality metrics live there,
keyed by the `agent_name` and `metadata["tenant"]` OpenRTC emits. Look there for
per-provider latency, not here.

## Quick reference

| Symptom | First move | Likely fix |
| --- | --- | --- |
| One `slow` row | Read the `[slow-session]` log line | Move the sync call off the loop |
| High `cpu%`, not slow | `openrtc top --sort cpu_pct` | `to_thread` or `isolation="process"` |
| `mem(MB)` climbing | Watch the RSS trend | Lower concurrency / find the leak in process mode |
| Healthy table, slow calls | (not an OpenRTC issue) | Pipeline latency: voicegateway |
