---
title: Session Introspection
description: How OpenRTC attributes memory, CPU, and event-loop blocks to individual sessions inside one shared worker, what it measures, and what it cannot see.
icon: gauge
---

# Session Introspection

In coroutine mode OpenRTC runs many sessions as `asyncio.Task`s in a single
process. That density is the whole point (one worker instead of one subprocess
per call), but it raises a fair question: if everything shares one process, how
do you tell which session is eating memory or blocking the loop? Session
introspection is the answer. It attributes per-session memory, CPU, and
event-loop stalls from inside the shared worker, and surfaces them live through
[`openrtc top`](/cli/top).

<Note>
Introspection is coroutine-mode only and on by default. Process mode isolates
every session in its own subprocess where the OS already accounts per session, so
a shared-process inspector would see nothing and OpenRTC skips it. Disable it with
`AgentPool(enable_introspection=False)`.
</Note>

## What it can and cannot see

OpenRTC sees **coroutines, not the voice pipeline**. It knows which task belongs
to which session and how those tasks use the process. It does not look inside the
STT / LLM / TTS calls a session makes.

| OpenRTC introspection (this doc) | voicegateway (separate product) |
| --- | --- |
| Per-session memory share | Cost per call / per provider |
| Per-session CPU share | STT / LLM / TTS latency |
| Event-loop block attribution | Transcript quality / eval metrics |
| Live session table (`openrtc top`) | Telemetry export, dashboards, alerting |

<Warning>
This is a **runtime density** tool, not an observability suite. For cost,
pipeline latency (STT/LLM/TTS), quality metrics, and telemetry export, use
**voicegateway**: it consumes the `agent_name` and `metadata["tenant"]` OpenRTC
emits and owns that lane. OpenRTC does not duplicate it.
</Warning>

## Per-session memory

CPython does not tag heap allocations by async context, and `tracemalloc` groups
by code location (identical across sessions running the same agent class). So the
true RSS of one session is not directly measurable in a shared process. Instead
of guessing, OpenRTC reports an honest approximation: an **equal share** of live
process RSS across the active sessions, sampled on an interval, with a per-session
**peak** held over the session's lifetime.

- `mem_mb`: current equal share (`process_RSS / active_sessions`).
- `peak_mb`: the highest share this session has seen while alive.

Because it divides the real RSS, the per-session numbers **sum back to process
RSS**. That makes it useful for "how much memory pressure, and is it growing" at
the pool level, and for spotting a worker trending toward its
[`memory_limit_mb`](/cli). It deliberately does **not** claim to tell you that
session X specifically allocated 200 MB. For hard per-session memory accounting,
run `isolation="process"`.

## Per-session CPU

Every task created inside a session's context is tagged with that session's id (a
chained `asyncio` task factory reads the id from a context variable at task
creation). A background thread then samples, at high frequency, **which session's
task is currently running** on the loop and accumulates counts.

- `cpu_pct`: this session's share of sampled running time.
- CPU seconds ≈ `samples × sample_interval`.

This is **statistical, not exact**: a session that is on-CPU more often ranks
higher, which is exactly what you need to tell a busy session from an idle one.
It is not a precise per-session `cpu_seconds` accounting, and it cannot see time
spent inside a provider's own process or the network.

## Slow-session detection

The most disruptive thing in a shared loop is one session making a **synchronous
blocking call** (a sync `requests.get()`, a heavy CPU loop). It starves every
other session on the worker. The slow-session detector catches this: a watcher
reschedules itself on a short interval and measures how late its wakeup actually
fires. The delay past the interval is how long the loop was blocked. On a block
over the threshold (`slow_session_threshold_ms`, default 50 ms) it attributes the
stall to the session that was running during it and logs:

```
[slow-session] session_id=job-c1d550 blocked event loop for 320ms
```

That session then shows as `slow` in `openrtc top` for a few seconds. The
offending source line is not captured (that needs stack sampling and is deferred);
the session id and duration are, which is enough to find the culprit. See the
[density debugging runbook](/runbooks/debugging-density) for the full flow.

## Overhead

Introspection is designed to stay well under a **1–2% CPU / 50 MB** budget: one
RSS read per memory interval, one `current_task` read per CPU sample, and a short
loop-lag probe. The snapshot is served on demand over a **private local Unix
socket** (mode `0600`, in a per-user `0700` directory), so nothing is exposed off
the host and only the owning user can read it.

## Trying it

```bash
openrtc dev ./agents          # coroutine mode, introspection on by default
openrtc top                   # live inspector in another terminal
openrtc top --once            # one snapshot (scripts / CI)
```

See the [`openrtc top` reference](/cli/top) for columns, key bindings, and filters.
