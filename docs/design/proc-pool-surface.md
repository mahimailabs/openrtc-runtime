# ProcPool Surface (livekit-agents 1.5.0)

This document captures the exact `AgentServer`-facing surface that our v0.1
`CoroutinePool` must reproduce. Derived from a direct read of the installed
`livekit-agents==1.5.0` source. Re-derive when the pin moves.

## Source

```
.venv/lib/python3.13/site-packages/livekit/agents/ipc/proc_pool.py     (256 LOC)
.venv/lib/python3.13/site-packages/livekit/agents/worker.py:582-601    (constructor call)
```

## How `AgentServer` constructs the pool

Verbatim from `worker.py:587-601`:

```python
self._proc_pool = ipc.proc_pool.ProcPool(
    initialize_process_fnc=self._setup_fnc,
    job_entrypoint_fnc=self._entrypoint_fnc,
    session_end_fnc=self._session_end_fnc,
    num_idle_processes=ServerEnvOption.getvalue(self._num_idle_processes, devmode),
    loop=self._loop,
    job_executor_type=self._job_executor_type,
    inference_executor=self._inference_executor,
    mp_ctx=self._mp_ctx,
    initialize_timeout=self._initialize_process_timeout,
    close_timeout=self._shutdown_process_timeout,
    memory_warn_mb=self._job_memory_warn_mb,
    memory_limit_mb=self._job_memory_limit_mb,
    http_proxy=self._http_proxy or None,
)
```

Our `CoroutinePool.__init__` must accept this exact keyword shape (or a
superset). For coroutine mode several arguments become no-ops:

| Argument | Coroutine-mode treatment |
|---|---|
| `initialize_process_fnc` | Call **once** during `start()` against the singleton `JobProcess`. This is what runs the user's `setup_fnc` (prewarm). |
| `job_entrypoint_fnc` | Stored. Each `launch_job(info)` constructs a `JobContext` and schedules `job_entrypoint_fnc(ctx)` as an `asyncio.Task` on `loop`. |
| `session_end_fnc` | Stored. Awaited by the executor wrapper after the entrypoint task finishes (success or failure). |
| `num_idle_processes` | We do not pre-warm executors (they are cheap asyncio tasks). Honor as a hint by emitting the same `process_ready` events; do not allocate idle workers. |
| `loop` | Use directly. All executor tasks live on this loop. |
| `job_executor_type` | Ignored. We are the implementation behind whichever value `AgentServer` was built with. |
| `inference_executor` | Pass through to each `JobContext.proc.inference_executor`. |
| `mp_ctx` | Ignored (no subprocess to spawn). |
| `initialize_timeout` | Wrap `setup_fnc` in `asyncio.wait_for` to respect this. |
| `close_timeout` | Wrap `aclose()` of in-flight tasks in `asyncio.wait_for`. |
| `memory_warn_mb`, `memory_limit_mb` | Cannot enforce per-job in coroutine mode. Document the gap (design doc §9.4) and accept the args silently. |
| `http_proxy` | Pass through if needed by user code; otherwise no-op. |

## Public methods and properties `AgentServer` actually uses

From `worker.py` (every `_proc_pool.X` access):

| Member | Where AgentServer touches it |
|---|---|
| `start()` | Worker boot (`worker.py:721`). Awaited once before serving. |
| `aclose()` | Drain (`worker.py:951`). |
| `launch_job(info)` | Hot path (`worker.py:923, 1163, 1300`) for live jobs, console mode, and `simulate_job`. |
| `set_target_idle_processes(n)` | Worker auto-tunes idle warm-pool size based on `available_job` headroom (`worker.py:759, 761`). |
| `processes -> list[JobExecutor]` | Read for `running_jobs` enumeration (`worker.py:835, 860`). Returns every currently-tracked executor. |
| `get_by_job_id(job_id)` | Cancel-job path (`worker.py:1366`). Looks up by `RunningJobInfo.job.id`, NOT by executor `id`. |
| `processes[*].running_job` | Iterated on the same lines for the running-jobs snapshot. |

## Events `AgentServer` subscribes to

From `worker.py:718-720`:

```python
self._proc_pool.on("process_started", _update_job_status)
self._proc_pool.on("process_closed", _update_job_status)
self._proc_pool.on("process_job_launched", _update_job_status)
```

The full set declared by `proc_pool.py`:

```python
EventTypes = Literal[
    "process_created",
    "process_started",
    "process_ready",
    "process_closed",
    "process_job_launched",
]
```

Our `CoroutinePool` must extend `utils.EventEmitter[EventTypes]` and emit at
least the three subscribed events (`process_started`, `process_closed`,
`process_job_launched`) with the executor instance as the only payload arg —
this is what `_update_job_status` (a `worker.py` private function) consumes.
The other two (`process_created`, `process_ready`) have no live subscribers
in 1.5.0 but are publicly declared, so we will emit them for forward
compatibility.

## Lifecycle invariants the pool guarantees today

Reading `proc_pool.py:84-156`:

1. `start()` is idempotent — sets `self._started = True` and creates the main
   driver task. If `num_idle_processes > 0`, blocks on a warmup signal with a
   timeout (`initialize_timeout + 2`).
2. `aclose()` is idempotent — guarded on `_started`. Cancels the main task;
   the cancel cascade closes every executor, awaits every monitor task, and
   awaits every pending close.
3. `launch_job(info)` retries up to **3 attempts** (`MAX_ATTEMPTS = 3`). On
   the third failure it logs and re-raises; intermediate failures call
   `proc.aclose()` on the bad executor and try the next one. Our coroutine
   implementation does not need the same retry shape (creating an asyncio
   task is essentially free), but it must still raise on persistent failure
   so the worker treats the dispatch as failed.
4. The main task targets
   `max(min(target_idle_processes, default_num_idle_processes), jobs_waiting_for_process)`
   warm executors at all times. For coroutine mode we treat
   `default_num_idle_processes = 0` (we never pre-warm) and rely on
   `launch_job` creating its own executor on demand.

## Consequences for our `CoroutinePool`

- One singleton `JobProcess` shared across all jobs. `setup_fnc` runs once
  during `CoroutinePool.start()`. Every `CoroutineJobExecutor` constructs a
  `JobContext` referencing this singleton.
- `processes` returns the live executors only (drop them from the list when
  their task finishes — mirror `_monitor_process_task` semantics).
- `get_by_job_id` iterates `_executors` for `running_job.job.id == job_id`;
  the lookup must keep working even after the user entrypoint task
  completes, until we explicitly remove the executor from the list.
- Event emission ordering on `launch_job`: `process_created` →
  `process_started` → `process_ready` → (task scheduled) →
  `process_job_launched`. Cleanup emits `process_closed` from the executor's
  monitor task once the entrypoint coroutine exits.
- `EventEmitter` lives in `livekit.agents.utils`; we will subclass it
  exactly as `ProcPool` does, parameterized by the same `EventTypes` literal.
