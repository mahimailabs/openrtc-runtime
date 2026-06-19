# OpenRTC Session Observer Protocol: Design

**Status:** Approved (brainstorm), pending implementation
**Date:** 2026-06-08
**Scope:** openrtc-python only. A first-class, public per-session observability
seam so external observers (VoiceGateway, OpenTelemetry, custom telemetry) can
attach to each live session without reaching into OpenRTC internals.

## 1. Problem

OpenRTC owns the `AgentSession` for every job (constructed inside
`_run_universal_session`, `core/pool.py`). The only built-in telemetry is
`RuntimeMetricsStore`, baked directly into that function. There is **no public
seam** for a second observer. Today the only way a tool like VoiceGateway could
observe a session is to edit `_run_universal_session` or wrap internals, which
couples the two projects.

This matters because OpenRTC's own roadmap (v0.1 design doc, section 10) plans an
"OpenRTC platform repo assembling OpenRTC-Python + VoiceGateway", while section 3
keeps multi-tenancy/billing/dashboard out of this package. The clean way to honor
both is a lean, public per-session hook here, with the actual VoiceGateway wiring
living in an adapter outside this package.

## 2. Goals and non-goals

**Goals**
- A public `SessionObserver` protocol notified at well-defined per-session
  lifecycle points: the session goes live, and the session ends.
- A public, typed identity object (`SessionInfo`) carrying the resolved agent
  name, room, job id, parsed metadata, and start time, so observers attribute
  correctly without re-deriving routing internals.
- Observer failures and slowness are fully contained: a raising or hanging
  observer must never crash the session, its siblings, or the worker.
- Additive and backward compatible. Zero behavior change when no observers are
  registered.

**Non-goals**
- No OpenRTC-owned per-turn/per-metric event taxonomy. OpenRTC hands the live
  `AgentSession` to the observer; the observer subscribes to whatever it needs
  (VoiceGateway's `attach()` subscribes to the session's own metrics).
- No worker-level (`on_worker_start`/`on_worker_stop`) hooks in this iteration.
  `_prewarm_worker` is synchronous, and mixing a sync worker hook with the async
  session hooks would violate the single-style API rule (AGENTS.md). The one real
  need (build a shared resource once per worker, e.g. VoiceGateway's shared sink)
  is met by the observer lazily initializing on its first `on_session_start`.
- No change to `RuntimeMetricsStore` (see section 7).
- No VoiceGateway code. The VG `attach()` hardening and the observer adapter are
  a separate effort.

## 3. The protocol and types (`openrtc/observability/observer.py`, public)

```python
class SessionStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass(frozen=True, slots=True)
class SessionInfo:
    agent_name: str                 # resolved AgentConfig.name (the logical agent)
    room_name: str
    job_id: str
    metadata: Mapping[str, str]     # parsed + merged job/room metadata (room base, job overrides)
    started_at: float               # wall-clock unix seconds

@dataclass(frozen=True, slots=True)
class SessionOutcome:
    status: SessionStatus
    error: BaseException | None
    ended_at: float
    duration_seconds: float

@runtime_checkable
class SessionObserver(Protocol):
    async def on_session_start(self, info: SessionInfo, session: AgentSession) -> None: ...
    async def on_session_end(self, info: SessionInfo, outcome: SessionOutcome) -> None: ...
```

Both hooks are async (uniform style; `on_session_end` must be awaitable so an
observer can flush within the drain budget). `on_session_start` receives the
**live** `AgentSession` (after `session.start()`), which is the point at which an
observer can subscribe to the session's metrics. `AgentSession` is imported under
`TYPE_CHECKING` in the protocol signature so importing `openrtc.observability` does
not hard-require a constructed session type at runtime.

`metadata` is produced by parsing `ctx.job.metadata` and `ctx.room.metadata`
(each may be a JSON string, a mapping, or absent, exactly as `core/routing.py`
already tolerates) into a single `dict[str, str]`, room first then job override.
This is where an observer reads a tenant id.

## 4. Where it hooks (`core/pool.py`, the only touched runtime file)

All notification happens inside the existing `_run_universal_session`
try/finally, so observers get the **same delivery guarantee as the built-in
metrics store** and `execution/coroutine.py` is not touched at all:

```
info = _build_session_info(config, ctx)        # defensive; never raises into the session
try:
    metrics.record_session_started(config.name)         # unchanged
    await session.start(agent=config.agent_cls(), room=ctx.room)
    await ctx.connect()
    await _notify_session_start(observers, info, session, timeout)   # NEW (live session)
    if config.greeting is not None:
        await session.generate_reply(instructions=config.greeting)
except Exception as exc:
    metrics.record_session_failure(config.name, exc)    # unchanged
    raise
finally:
    metrics.record_session_finished(config.name)        # unchanged
    outcome = _build_session_outcome(info, sys.exc_info()[1])        # NEW
    await _notify_session_end(observers, info, outcome, timeout)     # NEW
```

- `on_session_start` fires after `ctx.connect()`, in the per-session
  `asyncio.Task` (`loop.create_task` in coroutine mode), so each notification
  lands in its own context copy. This is the boundary that keeps identity from
  cross-talking at density.
- Outcome is derived from `sys.exc_info()[1]` in the `finally`: no in-flight
  exception is `SUCCESS`; `CancelledError` is `CANCELLED`; anything else is
  `FAILED` with `error` set. This reads the existing exception flow without
  changing the `except` structure or the metrics calls.
- `_build_session_info` uses defensive attribute access (`getattr` with safe
  fallbacks for `room.name` / `job.id`) so a missing attribute can never turn a
  good session into a failed one.

When `observers` is empty, both `_notify_*` helpers return immediately, so there
is zero overhead and zero behavior change for the default pool.

## 5. Observer isolation (non-negotiable)

Every observer call is wrapped:

```python
for observer in observers:
    try:
        await asyncio.wait_for(observer.on_session_start(info, session), timeout)
    except Exception:
        logger.warning("session observer %r failed on_session_start", observer, exc_info=True)
```

- A raising observer is logged and skipped; the session proceeds.
- A slow observer is bounded by `asyncio.wait_for(timeout)` so it cannot stall
  the shared event loop (the loop-starvation risk inherent to coroutine mode).
- `CancelledError` is **not** caught (it is `BaseException`, not `Exception`), so
  worker cancellation still propagates correctly.
- `on_session_end` runs in the `finally` and is best-effort under hard
  cancellation, exactly like the existing `record_session_finished` line beside
  it. On normal completion and within-budget drain it always runs. (A shielded
  drain-flush is a possible future refinement, not in this iteration.)

`timeout` defaults to the pool's `drain_timeout` (so an end notification can
never exceed the drain budget) and is carried on `_PoolRuntimeState`.

## 6. Registration API (`AgentPool`)

```python
pool = AgentPool(observers=[VoiceGatewayObserver(...)])   # new optional kwarg
pool.add_observer(observer)                               # also addable before run()
```

- Validated early: each observer must satisfy `isinstance(observer, SessionObserver)`
  (the `runtime_checkable` protocol), else `TypeError` with an actionable message.
- Stored on `_PoolRuntimeState.observers` (a list, mirroring how `agents` is a
  shared dict the universal entrypoint reads). `add_observer` appends, matching
  the existing `add()` mutation pattern, and must be called before `run()`.
- Pool-scoped: every agent notifies every observer. Per-agent observers are
  YAGNI for now.

## 7. Deliberate decision: the metrics store is not refactored here

The brainstorm floated folding `RuntimeMetricsStore` into the protocol as
"observer #1". Reading the code changed that call:
`record_session_started` fires **before** `session.start()` (it counts dispatch
attempts, including sessions that fail during startup), whereas an external
observer needs the **live** session **after** `start()`. These are two different
lifecycle moments; collapsing them would conflate "attempted" with "observed
live" and would change the meaning of the existing `total_sessions_started`
counter (touching the snapshot, savings-readout, and stream tests). Per AGENTS.md
(smallest clean change, additive, backward compatible, preserve public behavior),
the metrics store stays exactly as-is. The observer seam is purely additive. A
future change could add a pre-start observer event if a real need appears.

## 8. Spawn safety

`_PoolRuntimeState` is documented as serializable runtime state and is pickled to
the subprocess in `process` isolation mode (`RuntimeMetricsStore` already
implements `__getstate__`/`__setstate__` for this). Observers added to that state
must therefore be picklable for `process` mode. The contract: an observer is a
spawn-safe configuration object and builds any live resources (HTTP clients,
sinks) lazily inside the worker on its first `on_session_start`. In `coroutine`
mode (the default) there is no pickling and any observer works. This is the same
spawn-safe-configuration discipline the repo already documents for `AgentConfig`.

## 9. Testing (must keep the 99% coverage gate green)

New tests in `tests/test_session_observer.py` (plus targeted additions where
`_run_universal_session` is exercised):

- Lifecycle: `on_session_start` and `on_session_end` each fire exactly once per
  session, with a correct `SessionInfo` (agent name, room, job id, parsed
  metadata) and `SessionOutcome`.
- Outcome mapping: success path yields `SUCCESS`; an entrypoint exception yields
  `FAILED` with `error` set and re-raises; a `CancelledError` yields `CANCELLED`.
- Density / no cross-talk: N concurrent sessions each notify with their own
  `SessionInfo` (the per-task isolation guarantee, currently untested in the
  repo).
- Fault isolation: an observer raising in `on_session_start` / `on_session_end`
  does not fail the session or its siblings (the session still completes; the
  built-in metrics still record).
- Timeout: a deliberately slow observer is bounded by `wait_for` and does not
  hang the session; a `WARNING` is logged.
- Registration: `observers=` kwarg and `add_observer` both register; a
  non-conforming object raises `TypeError`; empty observers is a no-op (default
  pool behavior is byte-for-byte unchanged).
- Spawn safety: a `SessionInfo`/`SessionOutcome`/example observer round-trips
  through `pickle` (process-mode contract).

Run locally to match CI: `uv run pytest --cov=openrtc --cov-fail-under=99`,
`uv run mypy src/`, `uv run ruff check .`, `uv run ruff format --check .`. The
`tests/conftest.py` livekit shim may need a small extension if a new attribute
(`job.id`, `room.name`) is read in a no-livekit CI path; extend it if so.

## 10. Acceptance criteria

1. `openrtc.SessionObserver`, `SessionInfo`, `SessionOutcome`, `SessionStatus`
   are public (exported from `openrtc` and `openrtc.observability`).
2. `AgentPool(observers=[...])` and `AgentPool.add_observer(...)` register and
   validate observers.
3. Observers are notified at session-live and session-end with correct identity
   and outcome, in the per-session task.
4. A raising or slow observer never crashes the session, siblings, or worker.
5. Default pool behavior (no observers) is unchanged; the existing suite passes
   untouched.
6. Coverage stays at >= 99%; `mypy src/` and `ruff` are clean.
7. README gains a short "Session observers" section; `docs/changelog.md` notes
   the additive feature.

## 11. File change summary

**New**
- `src/openrtc/observability/observer.py` (protocol, `SessionInfo`,
  `SessionOutcome`, `SessionStatus`, internal `_notify_*` helpers,
  `_build_session_info` / `_build_session_outcome`).
- `tests/test_session_observer.py`.

**Modified**
- `src/openrtc/core/pool.py` (add `observers` to `_PoolRuntimeState`; `observers`
  kwarg + `add_observer` on `AgentPool`; notify calls in `_run_universal_session`).
- `src/openrtc/observability/__init__.py` (re-export the public observer symbols).
- `src/openrtc/__init__.py` (add the four public symbols to `__all__`).
- `README.md`, `docs/changelog.md` (docs).
