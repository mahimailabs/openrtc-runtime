# Architecture

OpenRTC keeps the public API intentionally narrow.

## Core building blocks

### `AgentConfig`

`AgentConfig` stores the registration-time settings for a LiveKit agent:

- unique `name`
- `agent_cls` subclass
- optional `stt`, `llm`, and `tts` values (`ProviderValue | None`: provider ID
  strings or plugin instances)
- optional `greeting` generated after `ctx.connect()`
- optional `session_kwargs` forwarded to `AgentSession`
- optional `source_path` when the module file is known (e.g. after discovery), for
  tooling and footprint estimates—not used for routing

### `AgentDiscoveryConfig`

`AgentDiscoveryConfig` stores optional discovery metadata attached by
`@agent_config(...)`:

- optional explicit `name`
- optional `stt`, `llm`, and `tts` overrides
- optional `greeting` override

### `AgentPool`

`AgentPool` owns a single LiveKit `AgentServer`, a registry of named agents, and
one universal session handler.

At startup it configures shared prewarm behavior so worker-level runtime assets
are loaded once and reused across sessions.

The pool picks the underlying server class from the `isolation` constructor
argument:

- `isolation="coroutine"` (the v0.1 default) constructs an internal
  `_CoroutineAgentServer` subclass that swaps `livekit.agents.ipc.proc_pool.ProcPool`
  for our `CoroutinePool` for the duration of `run()`.
- `isolation="process"` constructs the vanilla `AgentServer` from
  `livekit-agents` (one OS subprocess per session, the v0.0.x behavior).

The same agent classes, providers, and routing rules apply in both modes.

## Session lifecycle

When a room is assigned to the worker:

1. OpenRTC resolves the target agent from job metadata, room metadata, room-name
   prefix matching, or the first registered agent.
2. It creates an `AgentSession` using the selected agent configuration.
3. Prewarmed VAD and turn detection models are injected from `proc.userdata`.
4. The resolved agent instance is started for the room.
5. OpenRTC connects the room context.
6. If a greeting is configured, it generates the greeting after connect.

## Coroutine-mode lifecycle

When `isolation="coroutine"` (the v0.1 default), the per-job lifecycle runs
inside the worker process instead of in a forked subprocess. The high-level
flow is:

```text
                         AgentServer.run()
                                │
              first time, builds CoroutinePool (one per worker)
                                │
                  CoroutinePool.start()
                                │
              ┌─── runs the user's setup_fnc ONCE ───┐
              │   into a singleton JobProcess        │
              │   (loads VAD, turn detector, …)      │
              └──────────────────────────────────────┘
                                │
                       worker is registered
                       and accepts dispatch
                                │
                                ▼
                  per session (N concurrent):
                                │
                    CoroutinePool.launch_job(info)
                                │
              builds a CoroutineJobExecutor wired with
              the same setup_fnc + entrypoint_fnc the pool was
              constructed with, plus a context_factory closing
              over the singleton JobProcess
                                │
                  executor.launch_job(info)
                                │
                schedules `_run_entrypoint(ctx)` as
                an asyncio.Task on the running loop
                                │
                                ▼
                  user entrypoint runs (AgentSession etc.)
                                │
              wrapper catches any exception, sets status
              to FAILED, calls session_end_fnc, removes the
              executor from pool.processes; supervisor counts
              consecutive failures
                                │
                                ▼
                  on shutdown: pool.drain() awaits every
                  in-flight executor's join(); pool.aclose()
                  cancels anything still pending
```

Key invariants in coroutine mode:

- **Setup runs once per worker.** The user's prewarm callback (Silero,
  turn detector, etc.) is invoked exactly once into the singleton
  `JobProcess`, then every executor's `JobContext` references that same
  process and `userdata` dict. This is the density story: prewarm cost
  is amortized across N concurrent sessions instead of paid once per
  session as in process mode.
- **One executor, one session.** Every `launch_job` allocates a fresh
  `CoroutineJobExecutor`; concurrent sessions never share an executor.
  Errors stay isolated to their executor's task wrapper.
- **No subprocess.** Per-session work runs as `asyncio.Task`s on the
  worker loop. There is no IPC, no process boundary, no per-session
  process startup cost.
- **Cooperative backpressure.** `CoroutinePool.current_load()` returns
  `len(active) / max_concurrent_sessions`. The `_CoroutineAgentServer`
  registers a `load_fnc` closure that reads this value, so LiveKit
  dispatch sees `>= 1.0` at saturation and routes new jobs elsewhere.
- **Cooperative shutdown.** `drain()` flips a flag (rejecting new
  launches) and awaits every executor's `join()`; `aclose()` then
  cancels anything still pending and clears state. After both, the
  worker's asyncio loop has no residual tasks belonging to the pool.
- **Supervisor.** After
  `consecutive_failure_limit` (default 5) consecutive non-SUCCESS
  terminations, the pool fires its registered callback. The default
  callback in `_CoroutineAgentServer` schedules `aclose()` so the
  worker exits and the deployment platform restarts it — the blast
  radius of a systemic bug stays bounded.

In process mode, the per-session lifecycle is unchanged from v0.0.x:
each session is its own subprocess via `livekit-agents`'s default
`ProcPool`, with its own `JobProcess`, its own setup_fnc invocation,
and its own `rtc.Room`.

## Shared runtime dependencies

During prewarm, OpenRTC loads:

- `livekit.plugins.silero`
- `livekit.plugins.turn_detector.multilingual.MultilingualModel`

These plugins are expected to be available from the package installation.
If they are missing at runtime, OpenRTC raises a `RuntimeError` with install
instructions.

## Why this shape?

This design keeps the package easy to reason about:

- routing logic is explicit
- worker-scoped dependencies are loaded once
- discovery metadata is opt-in and typed
- agent registration stays stable and readable
- the public API remains small enough for contributors to extend safely
