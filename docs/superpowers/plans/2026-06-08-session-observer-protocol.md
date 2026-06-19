# Session Observer Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a public `SessionObserver` protocol so external telemetry (VoiceGateway, OpenTelemetry, custom) can attach to each live session through `AgentPool`, without touching OpenRTC internals.

**Architecture:** A new `openrtc/observability/observer.py` defines the protocol, the `SessionInfo`/`SessionOutcome`/`SessionStatus` types, and internal build/notify helpers. `core/pool.py` carries an observer list on `_PoolRuntimeState`, exposes an `observers=` kwarg and `add_observer()` on `AgentPool`, and notifies observers inside the existing `_run_universal_session` try/finally. The metrics store and `execution/coroutine.py` are untouched.

**Tech Stack:** Python 3.11+, livekit-agents ~1.5, uv, pytest + pytest-asyncio, ruff, mypy --strict.

## Global Constraints

- All commands run through `uv` (`uv run pytest`, `uv run mypy src/`, `uv run ruff check .`, `uv run ruff format .`). Commit through `uv run git commit ...` so the `pre-commit` hook resolves.
- Coverage gate: line + branch coverage must stay `>= 99%` (`uv run pytest --cov=openrtc --cov-fail-under=99`). Every new line needs a test or a justified `# pragma: no cover`.
- `mypy src/` runs in `--strict` mode and must pass clean. Type everything; avoid `Any` except where the upstream surface forces it.
- Additive and backward compatible: default pool behavior (no observers) is byte-for-byte unchanged. Do not modify `RuntimeMetricsStore` or `execution/coroutine.py`.
- No em dashes in prose, code comments, or docs. Use colons, periods, or parentheses.
- Commit messages: conventional commits, authored as the maintainer (no AI attribution, no Co-Authored-By, no emoji).
- Observer fault rule: a raising or slow observer must never crash the session, its siblings, or the worker.

---

### Task 1: Observer types and protocol

**Files:**
- Create: `src/openrtc/observability/observer.py`
- Test: `tests/test_session_observer.py`

**Interfaces:**
- Produces: `SessionStatus` (Enum: `SUCCESS`/`FAILED`/`CANCELLED`); `SessionInfo(agent_name: str, room_name: str, job_id: str, metadata: Mapping[str, str], started_at: float)` (frozen, slots); `SessionOutcome(status: SessionStatus, error: BaseException | None, ended_at: float, duration_seconds: float)` (frozen, slots); `SessionObserver` (runtime_checkable Protocol with async `on_session_start(info, session)` and `on_session_end(info, outcome)`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_observer.py
from __future__ import annotations

import pickle

from openrtc.observability.observer import (
    SessionInfo,
    SessionObserver,
    SessionOutcome,
    SessionStatus,
)


def test_session_info_is_frozen_and_picklable() -> None:
    info = SessionInfo(
        agent_name="restaurant",
        room_name="restaurant-call-1",
        job_id="job-1",
        metadata={"tenant": "acme"},
        started_at=1.0,
    )
    assert info.agent_name == "restaurant"
    assert info.metadata["tenant"] == "acme"
    round_tripped = pickle.loads(pickle.dumps(info))
    assert round_tripped == info


def test_session_outcome_carries_status_and_error() -> None:
    err = ValueError("boom")
    outcome = SessionOutcome(
        status=SessionStatus.FAILED,
        error=err,
        ended_at=2.0,
        duration_seconds=1.0,
    )
    assert outcome.status is SessionStatus.FAILED
    assert outcome.error is err
    assert pickle.loads(pickle.dumps(SessionStatus.SUCCESS)) is SessionStatus.SUCCESS


def test_session_observer_is_runtime_checkable() -> None:
    class Good:
        async def on_session_start(self, info: object, session: object) -> None: ...
        async def on_session_end(self, info: object, outcome: object) -> None: ...

    class Bad:
        async def on_session_start(self, info: object, session: object) -> None: ...

    assert isinstance(Good(), SessionObserver)
    assert not isinstance(Bad(), SessionObserver)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_session_observer.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'openrtc.observability.observer'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/openrtc/observability/observer.py
"""Public per-session observability seam.

A ``SessionObserver`` is notified when a session goes live and when it ends, so
external telemetry (VoiceGateway, OpenTelemetry, custom) can attach to each live
``AgentSession`` without reaching into OpenRTC internals. OpenRTC hands the live
session and a typed ``SessionInfo`` to the observer and defines no per-turn event
schema of its own.

Observer calls are isolated: a raising or slow observer is logged and skipped and
never crashes the session, its siblings, or the worker.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from livekit.agents import AgentSession


class SessionStatus(Enum):
    """Terminal status of an observed session."""

    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """Stable identity of one observed session for its whole lifetime."""

    agent_name: str
    room_name: str
    job_id: str
    metadata: Mapping[str, str]
    started_at: float


@dataclass(frozen=True, slots=True)
class SessionOutcome:
    """How an observed session ended.

    ``error`` holds the terminating exception for ``FAILED`` and ``CANCELLED``
    outcomes, and is ``None`` for ``SUCCESS``. ``status`` is the source of truth.
    """

    status: SessionStatus
    error: BaseException | None
    ended_at: float
    duration_seconds: float


@runtime_checkable
class SessionObserver(Protocol):
    """Receive per-session lifecycle notifications from an ``AgentPool``.

    ``on_session_start`` receives the live ``AgentSession`` once it has started,
    which is the point at which an observer can subscribe to session metrics.
    ``on_session_end`` receives the terminal outcome. Both run inside the
    session's own task and should not raise (a raising observer is logged and
    skipped).
    """

    async def on_session_start(self, info: SessionInfo, session: AgentSession) -> None:
        """Handle a session going live after it has started and connected."""
        ...

    async def on_session_end(self, info: SessionInfo, outcome: SessionOutcome) -> None:
        """Handle a session ending, for any terminal outcome."""
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_session_observer.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Type-check and commit**

```bash
uv run mypy src/
uv run git add src/openrtc/observability/observer.py tests/test_session_observer.py
uv run git commit -m "feat(observability): add SessionObserver protocol and types"
```

---

### Task 2: Metadata, info, outcome, and notify helpers

**Files:**
- Modify: `src/openrtc/observability/observer.py`
- Test: `tests/test_session_observer.py`

**Interfaces:**
- Consumes: `SessionInfo`, `SessionOutcome`, `SessionStatus`, `SessionObserver` from Task 1.
- Produces: `_build_session_info(agent_name: str, ctx: JobContext) -> SessionInfo`; `_build_session_outcome(info: SessionInfo, error: BaseException | None) -> SessionOutcome`; `async _notify_session_start(observers, info, session, *, timeout: float) -> None`; `async _notify_session_end(observers, info, outcome, *, timeout: float) -> None`. `observers` is `Iterable[SessionObserver]`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_session_observer.py
import asyncio
import logging
import types

from openrtc.observability.observer import (
    _build_session_info,
    _build_session_outcome,
    _notify_session_end,
    _notify_session_start,
)


def _fake_ctx(*, job_metadata=None, room_metadata=None, room_name="general-room", job_id=None):
    job = types.SimpleNamespace(metadata=job_metadata)
    if job_id is not None:
        job.id = job_id
    room = types.SimpleNamespace(metadata=room_metadata, name=room_name)
    return types.SimpleNamespace(job=job, room=room)


def test_build_session_info_parses_and_merges_metadata() -> None:
    ctx = _fake_ctx(
        job_metadata='{"tenant": "acme", "agent": "restaurant"}',
        room_metadata={"tenant": "ignored", "region": "eu"},
        room_name="restaurant-1",
        job_id="job-9",
    )
    info = _build_session_info("restaurant", ctx)
    assert info.agent_name == "restaurant"
    assert info.room_name == "restaurant-1"
    assert info.job_id == "job-9"
    assert info.metadata == {"tenant": "acme", "agent": "restaurant", "region": "eu"}
    assert info.started_at > 0


def test_build_session_info_defends_missing_attrs() -> None:
    # FakeJob in the repo has no ``id``; a missing room name or job id must not raise.
    ctx = _fake_ctx(job_metadata="not-json", room_name="")
    info = _build_session_info("agent", ctx)
    assert info.room_name == ""
    assert info.job_id == ""
    assert info.metadata == {}


def test_build_session_outcome_classifies_status() -> None:
    info = SessionInfo("a", "r", "j", {}, started_at=0.0)
    assert _build_session_outcome(info, None).status is SessionStatus.SUCCESS
    failed = _build_session_outcome(info, ValueError("x"))
    assert failed.status is SessionStatus.FAILED
    assert isinstance(failed.error, ValueError)
    cancelled = _build_session_outcome(info, asyncio.CancelledError())
    assert cancelled.status is SessionStatus.CANCELLED
    assert cancelled.duration_seconds >= 0.0


class _RecordingObserver:
    def __init__(self) -> None:
        self.starts: list[tuple[object, object]] = []
        self.ends: list[object] = []

    async def on_session_start(self, info, session) -> None:
        self.starts.append((info, session))

    async def on_session_end(self, info, outcome) -> None:
        self.ends.append(outcome)


def test_notify_start_and_end_call_observers() -> None:
    obs = _RecordingObserver()
    info = SessionInfo("a", "r", "j", {}, started_at=0.0)
    session = object()
    asyncio.run(_notify_session_start([obs], info, session, timeout=5.0))
    outcome = _build_session_outcome(info, None)
    asyncio.run(_notify_session_end([obs], info, outcome, timeout=5.0))
    assert obs.starts == [(info, session)]
    assert obs.ends == [outcome]


def test_notify_is_noop_for_empty_observers() -> None:
    info = SessionInfo("a", "r", "j", {}, started_at=0.0)
    asyncio.run(_notify_session_start([], info, object(), timeout=5.0))
    asyncio.run(_notify_session_end([], info, _build_session_outcome(info, None), timeout=5.0))


def test_notify_swallows_observer_exception(caplog) -> None:
    class _Raises:
        async def on_session_start(self, info, session) -> None:
            raise RuntimeError("observer boom")

        async def on_session_end(self, info, outcome) -> None:
            raise RuntimeError("observer boom")

    info = SessionInfo("a", "r", "j", {}, started_at=0.0)
    with caplog.at_level(logging.WARNING, logger="openrtc"):
        asyncio.run(_notify_session_start([_Raises()], info, object(), timeout=5.0))
    assert "failed on_session_start" in caplog.text


def test_notify_enforces_timeout(caplog) -> None:
    class _Slow:
        async def on_session_start(self, info, session) -> None:
            await asyncio.sleep(10.0)

        async def on_session_end(self, info, outcome) -> None:
            await asyncio.sleep(10.0)

    info = SessionInfo("a", "r", "j", {}, started_at=0.0)
    with caplog.at_level(logging.WARNING, logger="openrtc"):
        asyncio.run(_notify_session_start([_Slow()], info, object(), timeout=0.01))
    assert "failed on_session_start" in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_session_observer.py -q`
Expected: FAIL with `ImportError: cannot import name '_build_session_info'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/openrtc/observability/observer.py` (new imports at top, helpers at bottom):

```python
# add to the import block
import asyncio
import json
import logging
import time
from collections.abc import Iterable
from typing import Any

# add to the TYPE_CHECKING block
if TYPE_CHECKING:
    from livekit.agents import AgentSession, JobContext

logger = logging.getLogger("openrtc")
```

```python
# append at the bottom of observer.py
def _coerce_metadata(raw: Any) -> dict[str, str]:
    """Parse one metadata value (JSON string, mapping, or absent) into a str map."""
    decoded: Any = raw
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return {}
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            return {}
    if isinstance(decoded, Mapping):
        return {str(key): str(value) for key, value in decoded.items()}
    return {}


def _merge_metadata(ctx: JobContext) -> dict[str, str]:
    """Merge room metadata then job metadata (job wins) into one str map."""
    room = getattr(ctx, "room", None)
    job = getattr(ctx, "job", None)
    merged = _coerce_metadata(getattr(room, "metadata", None))
    merged.update(_coerce_metadata(getattr(job, "metadata", None)))
    return merged


def _build_session_info(agent_name: str, ctx: JobContext) -> SessionInfo:
    """Build a ``SessionInfo`` from the resolved agent and the job context.

    Uses defensive attribute access so a missing room name or job id can never
    turn a healthy session into a failed one.
    """
    room = getattr(ctx, "room", None)
    job = getattr(ctx, "job", None)
    return SessionInfo(
        agent_name=agent_name,
        room_name=getattr(room, "name", "") or "",
        job_id=getattr(job, "id", "") or "",
        metadata=_merge_metadata(ctx),
        started_at=time.time(),
    )


def _build_session_outcome(
    info: SessionInfo, error: BaseException | None
) -> SessionOutcome:
    """Classify the terminal outcome from the in-flight exception, if any."""
    if error is None:
        status = SessionStatus.SUCCESS
    elif isinstance(error, asyncio.CancelledError):
        status = SessionStatus.CANCELLED
    else:
        status = SessionStatus.FAILED
    ended_at = time.time()
    return SessionOutcome(
        status=status,
        error=error,
        ended_at=ended_at,
        duration_seconds=max(ended_at - info.started_at, 0.0),
    )


async def _notify_session_start(
    observers: Iterable[SessionObserver],
    info: SessionInfo,
    session: AgentSession,
    *,
    timeout: float,
) -> None:
    """Notify every observer that the session is live; isolate failures."""
    for observer in observers:
        try:
            await asyncio.wait_for(observer.on_session_start(info, session), timeout)
        except Exception:
            logger.warning(
                "session observer %r failed on_session_start for agent '%s'",
                observer,
                info.agent_name,
                exc_info=True,
            )


async def _notify_session_end(
    observers: Iterable[SessionObserver],
    info: SessionInfo,
    outcome: SessionOutcome,
    *,
    timeout: float,
) -> None:
    """Notify every observer that the session ended; isolate failures."""
    for observer in observers:
        try:
            await asyncio.wait_for(observer.on_session_end(info, outcome), timeout)
        except Exception:
            logger.warning(
                "session observer %r failed on_session_end for agent '%s'",
                observer,
                info.agent_name,
                exc_info=True,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_session_observer.py -q`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Type-check, lint, commit**

```bash
uv run mypy src/
uv run ruff check src/openrtc/observability/observer.py
uv run git add src/openrtc/observability/observer.py tests/test_session_observer.py
uv run git commit -m "feat(observability): add session info/outcome builders and notify helpers"
```

---

### Task 3: Register observers on AgentPool

**Files:**
- Modify: `src/openrtc/core/pool.py` (`_PoolRuntimeState`, `AgentPool.__init__`, new `add_observer`)
- Test: `tests/test_session_observer.py`

**Interfaces:**
- Consumes: `SessionObserver` from Task 1.
- Produces: `AgentPool(observers: Sequence[SessionObserver] | None = None, ...)`; `AgentPool.add_observer(observer: SessionObserver) -> None`; `_PoolRuntimeState.observers: list[SessionObserver]`; `_PoolRuntimeState.observer_timeout: float`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_session_observer.py
import pytest
from livekit.agents import Agent

from openrtc import AgentPool


class _Agent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="x")


def test_pool_registers_observers_via_kwarg_and_method() -> None:
    a = _RecordingObserver()
    b = _RecordingObserver()
    pool = AgentPool(observers=[a])
    pool.add_observer(b)
    assert pool._runtime_state.observers == [a, b]
    assert pool._runtime_state.observer_timeout == float(pool.drain_timeout)


def test_pool_rejects_non_observer() -> None:
    pool = AgentPool()
    with pytest.raises(TypeError, match="SessionObserver"):
        pool.add_observer(object())  # type: ignore[arg-type]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_session_observer.py -q -k pool`
Expected: FAIL (`AgentPool() got an unexpected keyword argument 'observers'` or `add_observer` missing).

- [ ] **Step 3: Write minimal implementation**

In `src/openrtc/core/pool.py`:

Add imports near the existing observability import:

```python
from collections.abc import Mapping, Sequence
from openrtc.observability.observer import SessionObserver
```

Extend `_PoolRuntimeState`:

```python
@dataclass(slots=True)
class _PoolRuntimeState:
    """Serializable runtime state shared with worker callbacks."""

    agents: dict[str, AgentConfig]
    metrics: RuntimeMetricsStore = field(default_factory=RuntimeMetricsStore)
    observers: list[SessionObserver] = field(default_factory=list)
    observer_timeout: float = 30.0
```

Add an `observers` parameter to `AgentPool.__init__` (after `default_greeting`):

```python
        observers: Sequence[SessionObserver] | None = None,
```

Document it in the docstring Args:

```
            observers: Optional session observers notified for every session in
                the pool (see ``add_observer``).
```

Where `self._runtime_state` is constructed, pass the timeout and register observers (replace the existing assignment around the current line 184):

```python
        self._runtime_state = _PoolRuntimeState(
            agents=self._agents,
            observer_timeout=float(self._drain_timeout),
        )
        if observers is not None:
            for observer in observers:
                self.add_observer(observer)
```

Add the method (next to `remove`):

```python
    def add_observer(self, observer: SessionObserver) -> None:
        """Register a session observer notified for every session in the pool.

        Call before ``run()``. The observer is notified on the session's own task
        when the session goes live and when it ends. A raising or slow observer is
        logged and skipped, never crashing the session.

        Args:
            observer: An object implementing the ``SessionObserver`` protocol.

        Raises:
            TypeError: If ``observer`` does not implement the protocol.
        """
        if not isinstance(observer, SessionObserver):
            raise TypeError(
                "observer must implement on_session_start and on_session_end "
                f"(SessionObserver protocol); got {type(observer).__name__}."
            )
        self._runtime_state.observers.append(observer)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_session_observer.py -q -k pool`
Expected: PASS.

- [ ] **Step 5: Type-check and commit**

```bash
uv run mypy src/
uv run git add src/openrtc/core/pool.py tests/test_session_observer.py
uv run git commit -m "feat(pool): register session observers on AgentPool"
```

---

### Task 4: Notify observers from the universal session

**Files:**
- Modify: `src/openrtc/core/pool.py` (`_run_universal_session`)
- Test: `tests/test_session_observer.py`

**Interfaces:**
- Consumes: `_build_session_info`, `_build_session_outcome`, `_notify_session_start`, `_notify_session_end` (Task 2); `_PoolRuntimeState.observers`, `.observer_timeout` (Task 3).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_session_observer.py
from openrtc.core.pool import _run_universal_session


class _FakeSession:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    async def start(self, *, agent, room) -> None:
        return None

    async def generate_reply(self, *, instructions) -> None:
        return None


class _FailingSession(_FakeSession):
    async def generate_reply(self, *, instructions) -> None:
        raise ValueError("greeting failed")


class _CancelledSession(_FakeSession):
    async def generate_reply(self, *, instructions) -> None:
        raise asyncio.CancelledError()


def _ctx_with_proc(**kw):
    ctx = _fake_ctx(**kw)
    ctx.proc = types.SimpleNamespace(userdata={"vad": object()})

    async def connect() -> None:
        return None

    ctx.connect = connect
    return ctx


def test_observer_notified_on_success(monkeypatch) -> None:
    monkeypatch.setattr("openrtc.core.pool.AgentSession", _FakeSession)
    obs = _RecordingObserver()
    pool = AgentPool(observers=[obs])
    pool.add("restaurant", _Agent, greeting="hi")
    ctx = _ctx_with_proc(room_name="restaurant-1", job_id="job-1")
    asyncio.run(_run_universal_session(pool._runtime_state, ctx))
    assert len(obs.starts) == 1
    start_info, _session = obs.starts[0]
    assert start_info.agent_name == "restaurant"
    assert start_info.room_name == "restaurant-1"
    assert len(obs.ends) == 1
    assert obs.ends[0].status is SessionStatus.SUCCESS
    # metrics still recorded
    assert pool._runtime_state.metrics.total_sessions_started == 1


def test_observer_notified_on_failure(monkeypatch) -> None:
    monkeypatch.setattr("openrtc.core.pool.AgentSession", _FailingSession)
    obs = _RecordingObserver()
    pool = AgentPool(observers=[obs])
    pool.add("restaurant", _Agent, greeting="hi")
    ctx = _ctx_with_proc()
    with pytest.raises(ValueError, match="greeting failed"):
        asyncio.run(_run_universal_session(pool._runtime_state, ctx))
    assert obs.ends[0].status is SessionStatus.FAILED
    assert isinstance(obs.ends[0].error, ValueError)
    assert pool._runtime_state.metrics.total_session_failures == 1


def test_observer_notified_on_cancellation(monkeypatch) -> None:
    monkeypatch.setattr("openrtc.core.pool.AgentSession", _CancelledSession)
    obs = _RecordingObserver()
    pool = AgentPool(observers=[obs])
    pool.add("restaurant", _Agent, greeting="hi")
    ctx = _ctx_with_proc()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run_universal_session(pool._runtime_state, ctx))
    assert obs.ends[0].status is SessionStatus.CANCELLED


def test_raising_observer_does_not_break_session(monkeypatch) -> None:
    monkeypatch.setattr("openrtc.core.pool.AgentSession", _FakeSession)

    class _Raises:
        async def on_session_start(self, info, session) -> None:
            raise RuntimeError("boom")

        async def on_session_end(self, info, outcome) -> None:
            raise RuntimeError("boom")

    good = _RecordingObserver()
    pool = AgentPool(observers=[_Raises(), good])
    pool.add("restaurant", _Agent, greeting="hi")
    ctx = _ctx_with_proc()
    asyncio.run(_run_universal_session(pool._runtime_state, ctx))  # no raise
    assert len(good.ends) == 1  # the well-behaved observer still ran


def test_no_observers_is_unchanged(monkeypatch) -> None:
    monkeypatch.setattr("openrtc.core.pool.AgentSession", _FakeSession)
    pool = AgentPool()
    pool.add("restaurant", _Agent, greeting="hi")
    ctx = _ctx_with_proc()
    asyncio.run(_run_universal_session(pool._runtime_state, ctx))  # no error
    assert pool._runtime_state.metrics.total_sessions_started == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_session_observer.py -q -k observer_notified`
Expected: FAIL (observer `starts`/`ends` empty; not yet wired).

- [ ] **Step 3: Write minimal implementation**

In `src/openrtc/core/pool.py`, add `import sys` at the top, and the observer imports:

```python
from openrtc.observability.observer import (
    SessionObserver,
    _build_session_info,
    _build_session_outcome,
    _notify_session_end,
    _notify_session_start,
)
```

Rewrite `_run_universal_session`:

```python
async def _run_universal_session(
    runtime_state: _PoolRuntimeState,
    ctx: JobContext,
) -> None:
    """Dispatch a session through the owning ``AgentPool``."""
    if not runtime_state.agents:
        raise RuntimeError("No agents are registered in the pool.")
    config = _resolve_agent_config(runtime_state.agents, ctx)
    session_kwargs = _build_session_kwargs(config.session_kwargs, ctx.proc)
    session: AgentSession[None] = AgentSession(
        stt=config.stt,
        llm=config.llm,
        tts=config.tts,
        vad=ctx.proc.userdata["vad"],
        **session_kwargs,
    )
    info = _build_session_info(config.name, ctx)
    try:
        runtime_state.metrics.record_session_started(config.name)
        await session.start(
            agent=config.agent_cls(),  # type: ignore[call-arg]
            room=ctx.room,
        )
        await ctx.connect()
        await _notify_session_start(
            runtime_state.observers,
            info,
            session,
            timeout=runtime_state.observer_timeout,
        )

        if config.greeting is not None:
            logger.debug("Generating greeting for agent '%s'.", config.name)
            await session.generate_reply(instructions=config.greeting)
    except Exception as exc:
        runtime_state.metrics.record_session_failure(config.name, exc)
        raise
    finally:
        runtime_state.metrics.record_session_finished(config.name)
        outcome = _build_session_outcome(info, sys.exc_info()[1])
        await _notify_session_end(
            runtime_state.observers,
            info,
            outcome,
            timeout=runtime_state.observer_timeout,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_session_observer.py -q`
Expected: PASS (all observer tests).

- [ ] **Step 5: Full suite, type-check, lint, commit**

```bash
uv run pytest --cov=openrtc --cov-fail-under=99 -q
uv run mypy src/
uv run ruff check . && uv run ruff format --check .
uv run git add src/openrtc/core/pool.py tests/test_session_observer.py
uv run git commit -m "feat(pool): notify session observers across the session lifecycle"
```

---

### Task 5: Public exports

**Files:**
- Modify: `src/openrtc/observability/__init__.py`
- Modify: `src/openrtc/__init__.py`
- Test: `tests/test_session_observer.py`

**Interfaces:**
- Produces: `openrtc.SessionObserver`, `openrtc.SessionInfo`, `openrtc.SessionOutcome`, `openrtc.SessionStatus`; same four re-exported from `openrtc.observability`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_session_observer.py
def test_public_exports() -> None:
    import openrtc
    from openrtc import SessionInfo, SessionObserver, SessionOutcome, SessionStatus
    from openrtc.observability import SessionInfo as SI

    assert SI is SessionInfo
    for name in ("SessionObserver", "SessionInfo", "SessionOutcome", "SessionStatus"):
        assert name in openrtc.__all__
    assert {SessionObserver, SessionOutcome, SessionStatus}  # referenced
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_session_observer.py -q -k public_exports`
Expected: FAIL (`ImportError: cannot import name 'SessionObserver' from 'openrtc'`).

- [ ] **Step 3: Write minimal implementation**

`src/openrtc/observability/__init__.py`:

```python
from openrtc.observability.observer import (
    SessionInfo,
    SessionObserver,
    SessionOutcome,
    SessionStatus,
)

__all__ = [
    "SessionInfo",
    "SessionObserver",
    "SessionOutcome",
    "SessionStatus",
]
```

`src/openrtc/__init__.py`: add the import and the four names to `__all__`:

```python
from .observability.observer import (
    SessionInfo,
    SessionObserver,
    SessionOutcome,
    SessionStatus,
)
```

```python
__all__ = [
    "AgentConfig",
    "AgentDiscoveryConfig",
    "AgentPool",
    "FileChange",
    "FileWatcher",
    "ProviderValue",
    "SessionInfo",
    "SessionObserver",
    "SessionOutcome",
    "SessionStatus",
    "__version__",
    "agent_config",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_session_observer.py -q`
Expected: PASS.

- [ ] **Step 5: Type-check, lint, commit**

```bash
uv run mypy src/
uv run ruff check .
uv run git add src/openrtc/__init__.py src/openrtc/observability/__init__.py tests/test_session_observer.py
uv run git commit -m "feat(observability): export session observer public API"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md` (add a "Session observers" section)
- Modify: `docs/changelog.md` (note the additive feature)

- [ ] **Step 1: Add a README section**

Add after the routing or provider-configuration section a concise "Session observers" block:

````markdown
## Session observers

Attach external telemetry to every session without subclassing or touching
OpenRTC internals. Implement `SessionObserver` and pass it to the pool:

```python
from openrtc import AgentPool, SessionInfo, SessionObserver, SessionOutcome

class LoggingObserver:
    async def on_session_start(self, info: SessionInfo, session) -> None:
        print(f"live: {info.agent_name} in {info.room_name}")

    async def on_session_end(self, info: SessionInfo, outcome: SessionOutcome) -> None:
        print(f"done: {info.agent_name} -> {outcome.status.value}")

pool = AgentPool(observers=[LoggingObserver()])  # or pool.add_observer(...)
```

`on_session_start` receives the live `AgentSession` (subscribe to its metrics
there). Observer calls are isolated: a raising or slow observer is logged and
skipped, never crashing the session. In `process` isolation mode observers must
be picklable (build live resources lazily on first `on_session_start`).
````

- [ ] **Step 2: Add a changelog entry**

Add an unreleased entry to `docs/changelog.md` noting: "Added a public `SessionObserver` protocol (`SessionObserver`, `SessionInfo`, `SessionOutcome`, `SessionStatus`) and `AgentPool(observers=...)` / `add_observer()` so external telemetry can attach per session. Additive and backward compatible."

- [ ] **Step 3: Lint and commit**

```bash
uv run ruff format --check .
uv run git add README.md docs/changelog.md
uv run git commit -m "docs: document the session observer protocol"
```

---

### Task 7: Final verification

- [ ] **Step 1: Full CI-parity gate**

```bash
uv run pytest --cov=openrtc --cov-report=term-missing --cov-fail-under=99 -q
uv run mypy src/
uv run ruff check .
uv run ruff format --check .
```
Expected: all green, coverage `>= 99%`. If a new line is uncovered, add a focused test (do not lower the gate).

- [ ] **Step 2: Push and open the PR**

```bash
uv run git push -u origin feat/session-observer-protocol
gh pr create --title "feat: public SessionObserver protocol for per-session telemetry" --body-file <(printf '...')
```
PR body: summarize the additive seam, the isolation guarantees, the deliberate decision to leave the metrics store untouched, and link the spec.
