# AgentServer Integration Points (livekit-agents 1.5.0)

This document captures every place `AgentServer` instantiates or uses
`_proc_pool`, the lifecycle ordering around those calls, and the swap
strategies we have for substituting our `CoroutinePool`. Derived from a
direct read of `worker.py` at the pinned 1.5.0 release. Re-derive when the
pin moves.

## Source

```
.venv/lib/python3.13/site-packages/livekit/agents/worker.py  (1435 LOC)
```

## Construction site

The pool is constructed once, inside `AgentServer.run()`, under
`async with self._lock:` (a worker is single-instance per AgentServer).
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

Important consequences:

- `_proc_pool` is **not** an attribute set in `__init__`. It only exists
  after `run()` enters its lock. Subclassing `__init__` to swap is
  insufficient.
- The class symbol used is `ipc.proc_pool.ProcPool`, looked up through the
  module-level `ipc` alias (`from . import ipc` at the top of `worker.py`).
  Replacing the class on that module substitutes our pool everywhere.
- Construction is followed by event-listener setup and `start()` (lines
  718-721). There is no extension hook between the two.

## Every `_proc_pool.X` call site

From a grep over `worker.py`:

| Site (line) | Use |
|---|---|
| `worker.py:587` | Construction (above). |
| `worker.py:718-720` | `_proc_pool.on("process_started" / "process_closed" / "process_job_launched", _update_job_status)` |
| `worker.py:721` | `await self._proc_pool.start()` |
| `worker.py:759` | `self._proc_pool.set_target_idle_processes(available_job)` (load auto-tune branch) |
| `worker.py:761` | `self._proc_pool.set_target_idle_processes(default_num_idle_processes)` (steady-state branch) |
| `worker.py:835` | `[proc.running_job for proc in self._proc_pool.processes if proc.running_job]` (the `active_jobs` property) |
| `worker.py:860` | `procs = [p for p in self._proc_pool.processes if p.running_job]` (drain loop) |
| `worker.py:923` | `await self._proc_pool.launch_job(running_info)` (`simulate_job`) |
| `worker.py:951` | `await self._proc_pool.aclose()` (`aclose`) |
| `worker.py:1163` | `await self._proc_pool.launch_job(running_info)` (`_answer_availability`, the live dispatch path) |
| `worker.py:1300` | `await self._proc_pool.launch_job(running_info)` (console-mode entrypoint) |
| `worker.py:1366` | `proc = self._proc_pool.get_by_job_id(msg.job_id)` then `proc.aclose()` (`_handle_termination`) |

That is the complete dependency surface. Anything else (HTTP server, WS
loop, dispatch protocol, drain logic, status reporting) does not touch the
pool — those concerns are owned by `AgentServer` and we get them for free.

## Lifecycle ordering

`run()` runs:

1. Validate config (`entrypoint_fnc`, `setup_fnc`, `load_fnc`, env vars).
2. Create `inference_executor` if any inference runners are registered.
3. **Create `_proc_pool`** (line 587).
4. Create HTTP and Prometheus servers, allocate channels, start the loop
   load task.
5. Start the inference executor.
6. Wire `_update_job_status` listener to `process_started`,
   `process_closed`, `process_job_launched`.
7. **`await _proc_pool.start()`** (line 721).
8. Open HTTP session, build the LiveKit API client.
9. Run the WS connection task to register with the dispatcher.

`drain(timeout)` (line 841):

- Marks the worker as `WS_FULL` so dispatch stops.
- Awaits all in-flight `_job_lifecycle_tasks` (assignments still in
  flight).
- Polls `_proc_pool.processes` for `running_job is not None` and `await
  proc.join()` on each, until empty.
- Optional `asyncio.wait_for` wrap.

`aclose()` (line 925):

- Cancels `_conn_task` and `_load_task`.
- Awaits in-flight `_job_lifecycle_tasks`.
- **`await _proc_pool.aclose()`** (line 951).
- Awaits inference executor close, HTTP session/server close, API close,
  channel close.
- Resolves `_close_future`.

## How `process_started`/`process_closed`/`process_job_launched` flow into worker status

`_update_job_status(proc)` (line 1405) is the single subscriber:

```python
status: agent.JobStatus = agent.JobStatus.JS_RUNNING
if proc.status == ipc.job_executor.JobStatus.FAILED:
    status = agent.JobStatus.JS_FAILED
elif proc.status == ipc.job_executor.JobStatus.SUCCESS:
    status = agent.JobStatus.JS_SUCCESS
elif proc.status == ipc.job_executor.JobStatus.RUNNING:
    status = agent.JobStatus.JS_RUNNING

update = agent.UpdateJobStatus(job_id=job_info.job.id, status=status, error="")
msg = agent.WorkerMessage(update_job=update)
await self._queue_msg(msg)
```

So our `CoroutineJobExecutor.status` value is the source of truth that
flows back to the LiveKit dispatcher. Every emit of
`process_job_launched` / `process_closed` / `process_started` triggers
this read.

## Swap strategies (ranked)

### A. Module-level class substitution (recommended)

Before instantiating `AgentServer`, do:

```python
import livekit.agents.ipc.proc_pool as _proc_pool_mod
from openrtc.execution.coroutine import CoroutinePool
_proc_pool_mod.ProcPool = CoroutinePool
```

Then `worker.py:587` constructs our pool with the same kwargs. Ours
inherits from `utils.EventEmitter[EventTypes]` and matches the public
surface. **Pros:** smallest code footprint; no `AgentServer` subclass;
zero code duplication. **Cons:** module-level mutation has lifetime
implications (every `AgentServer` after the swap uses ours). For OpenRTC
this is fine — we own the worker process.

### B. `_CoroutineAgentServer` subclass with `run` override

Define a thin `_CoroutineAgentServer(AgentServer)` that overrides `run()`
to first construct the pool with our class, then proceeds with the
remainder of the parent body. **Pros:** isolated from global state.
**Cons:** requires duplicating 200+ lines of `run()`; brittle across
LiveKit version bumps; misses any new logic upstream adds inside
`run()`.

### C. Both strategies combined

Subclass `AgentServer` for our public surface (carry the
`isolation` and `max_concurrent_sessions` parameters explicitly); then
inside `__init__` install the strategy-A module monkey-patch as a
side effect. We get a clean public API without owning the construction
sequence.

### Decision

Pick **strategy A** for the first prototype. It matches the design doc's
"the change is contained to one file" goal (§6.4) and gives the smallest
diff to validate against the density benchmark. If we later want a
public `_CoroutineAgentServer` symbol for type clarity, layer it on as
strategy C without touching the swap mechanism.

## What we still own at the AgentServer layer

Even with the pool swapped, AgentServer continues to:

- Run the WS register / heartbeat / availability protocol.
- Run the load calculator and drive `set_target_idle_processes`.
- Run the HTTP health server and Prometheus exporter.
- Handle `JobTermination` via `get_by_job_id` + `proc.aclose()`.
- Drive `simulate_job` (which our density benchmark will use).
- Re-report `active_jobs` after WS reconnect (`_report_active_jobs`).

None of these need awareness of coroutine-vs-process mode. Our pool just
has to be drop-in compatible with the surface above.
