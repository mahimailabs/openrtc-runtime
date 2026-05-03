# JobExecutor Protocol Surface (livekit-agents 1.5.0)

This document captures the exact surface our v0.1 `CoroutineJobExecutor` must
implement. It is derived from a direct read of the installed
`livekit-agents==1.5.0` source under
`.venv/lib/python3.13/site-packages/livekit/agents/ipc/job_executor.py` (and
the `proc_pool.py` neighbor that drives executors). Re-derive when the pin
moves.

## Source

```
.venv/lib/python3.13/site-packages/livekit/agents/ipc/job_executor.py  (45 LOC)
.venv/lib/python3.13/site-packages/livekit/agents/ipc/proc_pool.py     (256 LOC)
```

## Protocol definition (verbatim)

```python
class JobExecutor(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def started(self) -> bool: ...

    @property
    def user_arguments(self) -> Any | None: ...

    @user_arguments.setter
    def user_arguments(self, value: Any | None) -> None: ...

    @property
    def running_job(self) -> RunningJobInfo | None: ...

    @property
    def status(self) -> JobStatus: ...

    async def start(self) -> None: ...

    async def join(self) -> None: ...

    async def initialize(self) -> None: ...

    async def aclose(self) -> None: ...

    async def launch_job(self, info: RunningJobInfo) -> None: ...

    def logging_extra(self) -> dict[str, Any]: ...
```

```python
class JobStatus(Enum):
    RUNNING = "running"
    FAILED = "failed"
    SUCCESS = "success"
```

## Method-by-method contract

| Member | Async | What our implementation owes |
|---|---|---|
| `id: str` | property | Stable per-executor identifier (uuid4 hex is fine). Used by the pool's `get_by_job_id` lookup and in log fields. |
| `started: bool` | property | True after `start()` returns and before `aclose()` completes. The pool consults this to decide whether the executor is ready for `launch_job`. |
| `user_arguments: Any \| None` | property + setter | Opaque blob the worker passes through to the user entrypoint via `JobContext.proc.user_arguments`. We only need to store and return it. |
| `running_job: RunningJobInfo \| None` | property | The info passed to the most recent `launch_job` (or `None` before any). Pool reads it for `get_by_job_id` and for telemetry. |
| `status: JobStatus` | property | One of `RUNNING`/`FAILED`/`SUCCESS`. The pool's `_monitor_process_task` reads this when the executor finishes to count consecutive failures. |
| `start()` | async | Bring the executor to a state where it can accept `launch_job`. For coroutine mode this is essentially a no-op (the asyncio loop is already there); we just flip `started=True`. |
| `join()` | async | Block until the executor has fully stopped. The pool awaits this when shutting down. |
| `initialize()` | async | Run after `start`, before any `launch_job`. For process mode, this is where the child completes its handshake. For coroutine mode there is nothing to handshake; this remains a no-op. |
| `aclose()` | async | Idempotent shutdown. Cancel any in-flight task spawned by `launch_job`, await it, then settle. |
| `launch_job(info)` | async | The hot path. Construct a `JobContext` referencing the shared `JobProcess`, schedule the user's entrypoint as `asyncio.create_task(...)`, wrap so an unhandled exception flips `status` to `FAILED` instead of escaping. |
| `logging_extra()` | sync | Returns a dict merged into log records (job id, room name, etc.). Mirror what `ProcJobExecutor.logging_extra` produces so log piping stays consistent. |

## `RunningJobInfo` shape (the `launch_job` payload)

From `livekit/agents/job.py:89-96`:

```python
@dataclass
class RunningJobInfo:
    accept_arguments: JobAcceptArguments
    job: agent.Job          # protobuf job message from the worker WS
    url: str                # LiveKit URL
    token: str              # participant JWT
    worker_id: str
    fake_job: bool          # True when invoked via simulate_job
```

## `ProcPool` surface our `CoroutinePool` must mirror

`AgentServer` instantiates a `ProcPool` and treats it as a black box through
this surface (`livekit/agents/ipc/proc_pool.py`):

| Member | Async | Purpose |
|---|---|---|
| `__init__(initialize_timeout, close_timeout, job_executor_type, mp_ctx, loop, num_idle_processes, http_proxy, memory_warn_mb, memory_limit_mb, memory_check_interval, ws_url, ws_token, worker_id)` | sync | Constructor signature — we will not honor every kwarg but must accept the keyword-call shape from `AgentServer`. |
| `processes -> list[JobExecutor]` | property | Snapshot of every executor currently tracked. |
| `get_by_job_id(job_id) -> JobExecutor \| None` | sync | Lookup by `RunningJobInfo.job.id` (NOT executor id). |
| `start()` | async | Bring the pool up; spawn idle executors. For us: invoke the user `setup_fnc` once into a singleton `JobProcess`, then we are ready. |
| `aclose()` | async | Drain. Cancel everything; await `join()` on each. |
| `launch_job(info)` | async | Allocate (or create) an executor and tell it to run `info`. |
| `set_target_idle_processes(num)` | sync | Adjust the warm-pool size. We can no-op or treat it as `max_concurrent_sessions`. |
| `target_idle_processes -> int` | property | Read of the target. |

`ProcPool` extends `utils.EventEmitter[EventTypes]`. The events
`AgentServer` cares about are `process_created`, `process_started`,
`process_ready`, `process_closed`, `process_job_launched`. Our
`CoroutinePool` must emit the same names with the same payload shape so
`AgentServer`'s metric/load reporting code works unchanged.

## Notes for the v0.1 implementation

- We do not need to implement `JobExecutorType.THREAD` semantics. Process and
  coroutine are the only two modes.
- `JobStatus` only has three values — a `CANCELLED` status would be useful but
  is not in the upstream enum. Map our cancellations to `FAILED` with a
  `CancelledError`-typed `last_error`.
- `running_job` returns the **most recent** info, not a list. A coroutine
  executor that has finished one job and is between launches still reports
  the previous `running_job`; the pool clears it via `aclose`.
- The Protocol uses the `Protocol` decorator (PEP 544), not an ABC. We do not
  need to inherit; structural typing applies. We will still `@dataclass` our
  implementation for the slot-friendly storage.
