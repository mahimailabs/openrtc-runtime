---
title: Architecture
description: How OpenRTC's coroutine-mode worker, session lifecycle, and shared prewarm work.
icon: sitemap
---

# Architecture

OpenRTC keeps the public API intentionally narrow.

## Core building blocks

### `AgentConfig`

`AgentConfig` stores the registration-time settings for a LiveKit agent:

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Unique agent identifier |
| `agent_cls` | `type[Agent]` | The `livekit.agents.Agent` subclass |
| `stt`, `llm`, `tts` | `ProviderValue \| None` | Provider ID strings or plugin instances |
| `greeting` | `str \| None` | Generated after `ctx.connect()`, if set |
| `session_kwargs` | `dict \| None` | Forwarded verbatim to `AgentSession` |
| `source_path` | `Path \| None` | Module file, for tooling and footprint estimates only |

### `AgentDiscoveryConfig`

`AgentDiscoveryConfig` stores optional discovery metadata attached by `@agent_config(...)`:

| Field | Description |
|---|---|
| `name` | Explicit agent name (overrides the module file default) |
| `stt`, `llm`, `tts` | Provider overrides for this agent |
| `greeting` | Greeting override for this agent |

### `AgentPool`

`AgentPool` owns a single LiveKit `AgentServer`, a registry of named agents, and one universal session handler. At startup it configures shared prewarm so worker-level runtime assets are loaded once and reused across sessions.

The pool picks the underlying server class from the `isolation` constructor argument:

- `isolation="coroutine"` (the v0.1 default): swaps `livekit.agents.ipc.proc_pool.ProcPool` for `CoroutinePool`, running sessions as `asyncio.Task`s in the main worker loop.
- `isolation="process"`: uses the vanilla `AgentServer` from `livekit-agents`, one OS subprocess per session (the v0.0.x behavior).

The same agent classes, providers, and routing rules apply in both modes.

## Session lifecycle

<Steps>
  <Step title="Route">
    OpenRTC resolves the target agent from job metadata, room metadata, room-name prefix matching, or the first registered agent.
  </Step>
  <Step title="Build session">
    It creates an `AgentSession` using the selected agent configuration and injects prewarmed VAD and turn detection models from `proc.userdata`.
  </Step>
  <Step title="Start">
    The resolved agent instance is started for the room.
  </Step>
  <Step title="Connect">
    OpenRTC connects the room context.
  </Step>
  <Step title="Greet">
    If a greeting is configured, it generates the greeting after connect.
  </Step>
</Steps>

## Coroutine-mode lifecycle

When `isolation="coroutine"` (the v0.1 default), per-job work runs inside the worker process as `asyncio.Task`s instead of in a forked subprocess.

```mermaid
flowchart TD
    A[AgentServer.run] --> B[Build CoroutinePool]
    B --> C[CoroutinePool.start]
    C --> D[Run setup_fnc ONCE into singleton JobProcess\nLoads VAD, turn detector, ...]
    D --> E[Worker registered (accepts dispatch)]
    E --> F[per session: CoroutinePool.launch_job]
    F --> G[Build CoroutineJobExecutor\nwired with entrypoint_fnc + context_factory]
    G --> H[executor.launch_job schedules _run_entrypoint as asyncio.Task]
    H --> I[User entrypoint runs (AgentSession etc.)]
    I --> J{Session outcome}
    J -- success --> K[Status SUCCESS (executor removed from pool)]
    J -- error --> L[Status FAILED (session_end_fnc called)\nsupervisor counts consecutive failures]
    E --> M[On shutdown: pool.drain awaits all executors\npool.aclose cancels anything still pending]
```

<AccordionGroup>
  <Accordion title="Setup runs once per worker">
    The user's prewarm callback (Silero, turn detector, etc.) is invoked exactly once into the singleton `JobProcess`. Every executor's `JobContext` then references that same process and `userdata` dict. This is the density story: prewarm cost is amortized across N concurrent sessions instead of paid once per session as in process mode.
  </Accordion>
  <Accordion title="One executor, one session">
    Every `launch_job` allocates a fresh `CoroutineJobExecutor`. Concurrent sessions never share an executor, so errors stay isolated to their own task wrapper.
  </Accordion>
  <Accordion title="No subprocess">
    Per-session work runs as `asyncio.Task`s on the worker loop. There is no IPC, no process boundary, and no per-session process startup cost.
  </Accordion>
  <Accordion title="Cooperative backpressure">
    `CoroutinePool.current_load()` returns `len(active) / max_concurrent_sessions`. The `_CoroutineAgentServer` registers a `load_fnc` closure that reads this value, so LiveKit dispatch sees `>= 1.0` at saturation and routes new jobs elsewhere.
  </Accordion>
  <Accordion title="Cooperative shutdown">
    `drain()` flips a flag (rejecting new launches) and awaits every executor's `join()`. `aclose()` then cancels anything still pending and clears state. After both, the worker's asyncio loop has no residual tasks belonging to the pool.

    The wait window is bounded by `AgentPool(drain_timeout=N)` (default 30 seconds). Sessions that exceed the budget are cancelled with a `WARNING` log and the per-executor `kill()` escalation runs so the worker can finish shutting down.
  </Accordion>
  <Accordion title="Supervisor">
    After `consecutive_failure_limit` (default 5) consecutive non-SUCCESS terminations, the pool fires its registered callback. The default callback in `_CoroutineAgentServer` schedules `aclose()` so the worker exits and the deployment platform restarts it, bounding the blast radius of a systemic bug.
  </Accordion>
</AccordionGroup>

<Note>
In process mode, the per-session lifecycle is unchanged from v0.0.x: each session is its own subprocess via `livekit-agents`'s default `ProcPool`, with its own `JobProcess`, its own `setup_fnc` invocation, and its own `rtc.Room`.
</Note>

## Configuration precedence

Worker-runtime settings (`isolation`, `max_concurrent_sessions`) can be supplied at three layers:

| Priority | Source | Example |
|---|---|---|
| 1 (highest) | CLI flag | `--isolation coroutine`, `--max-concurrent-sessions 50` |
| 2 | Environment variable | `OPENRTC_ISOLATION`, `OPENRTC_MAX_CONCURRENT_SESSIONS` |
| 3 (default) | Library default | `isolation="coroutine"`, `max_concurrent_sessions=50` |

The same precedence applies to LiveKit connection settings (`--url` / `LIVEKIT_URL`, `--api-key` / `LIVEKIT_API_KEY`, `--api-secret` / `LIVEKIT_API_SECRET`, `--log-level` / `LIVEKIT_LOG_LEVEL`), which follow the upstream `livekit-agents` naming convention.

## Shared runtime dependencies

During prewarm, OpenRTC loads:

<Info>
Both plugins are bundled with `openrtc` as package dependencies. If they are missing at runtime, OpenRTC raises a `RuntimeError` with install instructions.
</Info>

- `livekit.plugins.silero`: voice activity detection (VAD)
- `livekit.plugins.turn_detector.multilingual.MultilingualModel`: end-of-turn detection
