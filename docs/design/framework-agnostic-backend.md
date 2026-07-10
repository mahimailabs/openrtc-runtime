# Framework-agnostic OpenRTC: the Backend seam

Status: **design / research (Loop 1)**. Not implemented. Produced by the research loop; consumed by the implementation loop (Loop 2) after review.

## Goal

Let one `AgentPool` run its whole feature set (density, routing, hot reload, introspection, per-tenant isolation, zero-downtime drain) over **more than one voice framework**: livekit-agents today, Pipecat next, and (later) potentially a Rust runtime such as FlowCat. The public API stays the same; the substrate that runs and multiplexes sessions becomes pluggable.

This mirrors what voicegateway already did: a framework-neutral core plus thin per-framework adapters, selected at call time, imported lazily, shipped as extras.

## The voicegateway blueprint (what we copy)

voicegateway went from livekit-only to framework-agnostic with a clean layering (`src/voicegateway/inference/`):

- **Neutral core**, imports no framework: `RequestRecord` (models/), `CostTracker` (middleware/), `Sink` (services/sinks.py), pricing, and ContextVars for session/tenant correlation (inference/session/context.py).
- **Per-framework adapters** in `inference/{livekit,pipecat}/`: livekit `MetricCapture` subscribes to each component's `metrics_collected`; pipecat `VoiceGatewayObserver` is a `BaseObserver` on the `PipelineTask`. Both map framework events into the same `RequestRecord` via `CostTracker.create_record(...)`.
- **A dispatcher** (`_frameworks.detect_framework(obj)` inspects `type(obj).__module__` for a `livekit` / `pipecat` root, walking the MRO) plus **lazy imports** inside `attach()` / `guard()` so `import voicegateway` pulls neither framework.
- **Extras**: `voicegateway[livekit]`, `voicegateway[pipecat]`; provider wheels imply the framework extra. The core `dependencies` list has no framework at all.

The invariant worth stealing verbatim: **framework-specific code never touches storage/logic directly; it only translates framework events into the neutral model.**

## The one structural difference (this is the crux)

voicegateway *attaches* to a session the caller already built. That makes it easy to be agnostic: the adapter is just a metering hook over a neutral core.

**OpenRTC is a runtime.** It *owns* the worker, the multiplexing loop, prewarm, and the session lifecycle. So "agnostic" here means abstracting the **substrate** behind a seam, not just adding an observer. The seam is bigger, but the shape is the same: neutral core above, per-framework substrate below.

| Concern | livekit backend (today) | pipecat backend (new) |
| --- | --- | --- |
| Substrate that runs + multiplexes sessions | `AgentServer` + `CoroutinePool` + `rtc_session` | `PipelineRunner` / `WorkerRunner` + a `/start`-style dispatch that `asyncio.create_task`s a bot |
| "Universal entrypoint" (build a session, start it) | `wiring.run_session` builds an `AgentSession` | build a `Pipeline` + `PipelineTask`, run it |
| Prewarm | shared VAD/turn in `proc.userdata` | Pipecat loads VAD/turn **per session**; OpenRTC provides sharing |
| Routing / dispatch | metadata + room-prefix chain | Pipecat has none; OpenRTC provides it |
| Drain | `CoroutinePool.begin_drain()` | `task.stop_when_done()` / `end()` |
| Session start/end signal | `SessionInfo` + `run_session_end` | pipecat frame-observer boundary (`EndFrame`) |

## The coupling reality (honest scope)

`livekit-agents` is a **hard dependency** (`pyproject.toml` `[dependencies]`), and **29 of 66 `src/openrtc` modules import livekit**. This is not a shim. It is a real, phased refactor. The imports fall into three tiers:

**Tier 1 (substrate, must become per-backend):** `runtime/{coroutine_runtime, coroutine_server, process_runtime, prewarm, registry, resources}`, `core/{wiring, turn_handling, serialization}`. These build/run `AgentSession`, own the `ProcPool`/`CoroutinePool`, and load prewarm. They move into `openrtc/backends/livekit/`.

**Tier 2 (neutral logic that currently references livekit types, needs a neutral context):** `routing/*` (reads `ctx.job.metadata`, `ctx.room.name`), `reload/*` (swaps an `Agent` class on a live session), `observability/{base_observer, introspection}` (builds `SessionInfo` from a `JobContext`). These are *logically neutral* but typed against `JobContext` / `Agent` / `AgentSession`. They get retargeted onto a neutral `SessionContext` (below) that each backend populates.

**Tier 3 (already neutral, no change):** `core/{tenant_config, circuit_breaker, audit, membership}`, `observability/{metrics, snapshot}`, `utils/validation`, `context.py`. These never touch a framework.

Rough split: ~9 modules are true substrate (Tier 1), ~12 are Tier 2 (retarget onto the neutral context), ~8 are Tier 3 (untouched). Most of the "29" are Tier 2 type-only imports, which is encouraging: the logic is neutral, the *types* are the coupling.

## The proposed seam

Two new neutral abstractions in `openrtc/core/` (framework-free), plus a per-backend package.

### 1. `SessionContext` (neutral): replaces raw `JobContext` in Tier 2 code

```python
# openrtc/core/session_context.py  (imports no framework)
class SessionContext(Protocol):
    """What routing / reload / observability need from a live job, backend-neutral."""
    room_name: str | None
    job_metadata: Mapping[str, Any] | None     # job.metadata, parsed
    room_metadata: Mapping[str, Any] | None     # room.metadata, parsed
    job_id: str
    async def connect(self) -> None: ...
    @property
    def session(self) -> Any: ...                # the live AgentSession / PipelineTask
```

Each backend adapts its framework's context to this. Routing reads `ctx.job_metadata["agent"]` instead of `ctx.job.metadata`; observability builds `SessionInfo` from `SessionContext`; reload holds `ctx.session`. The livekit `JobContext` and pipecat `PipelineTask` both satisfy this via a thin wrapper.

### 2. `Backend` (neutral): generalizes `base_runtime.py::SessionRuntime`

Today `SessionRuntime` is livekit-shaped (`rtc_session(agent_name, on_request, on_session_end)`, `setup_fnc`, `run(devmode, unregistered)`). Generalize it to a framework-neutral contract the pool drives:

```python
# openrtc/core/backend.py  (imports no framework)
class Backend(Protocol):
    """The substrate AgentPool runs sessions on. One per framework."""
    def register(self, *, agent_name: str | None, request_filter, session_end) -> None: ...
    def set_prewarm(self, prewarm_fnc) -> None: ...
    async def run(self, *, devmode: bool = False) -> None: ...
    async def begin_drain(self) -> None: ...
    @property
    def active_sessions(self) -> int: ...
    async def aclose(self) -> None: ...

class BackendSession(Protocol):
    """One running session's handle, for reload/introspection/drain."""
    agent_name: str
    tenant: str
    context: SessionContext
```

`AgentPool.__init__` selects the backend from an explicit arg (`AgentPool(backend="pipecat")`) or infers it (voicegateway's `detect_framework` style, when the caller hands framework objects). The pool builds `_PoolRuntimeState` (already neutral) and hands the backend the neutral prewarm + the universal session builder. The universal session builder is the ONE place that differs per framework:

- **livekit backend**: `run_session` builds an `AgentSession` from cached defaults + per-agent overrides (today's `wiring.run_session`, moved under `backends/livekit/`).
- **pipecat backend**: builds a `Pipeline([transport.input(), stt, ctx_agg.user(), llm, tts, transport.output(), ...])`, wraps it in a `PipelineTask` with `enable_metrics=True`, runs it. Providers come from the same registration data (`AgentConfig.stt/llm/tts`), mapped to pipecat services instead of livekit plugins.

Everything above the seam (routing chain, tenant config/caps/circuit breaker, reload coordinator, introspection registry, deployment_version/drain, `SessionInfo` + observer emission, audit) is constructed once, neutrally, and operates on `SessionContext` / `BackendSession`.

## What the pipecat backend must add (that Pipecat lacks)

Pipecat is async-first and already multiplexes bots via `asyncio.create_task` in the runner, so **OpenRTC's density-vs-subprocess win does not apply** (Pipecat has no forced process-per-job). The pipecat backend's value is the operational layer Pipecat has no concept of:

1. **Shared prewarm.** Pipecat instantiates `SileroVADAnalyzer()` and the SmartTurn ONNX model **per bot** (`hello_world.py` builds them inside `run_bot`). The backend loads one VAD/turn model and shares it across sessions (ONNX `Run()` is thread-safe). Direct memory/CPU win, exactly as for livekit. This is also where the Rust inference offload (see `rust-inference-offload.md`) plugs in.
2. **Registration + routing.** Pipecat has one `bot()` per deployment and no dispatch. The backend gives `pool.add(name, builder)` and runs the neutral routing chain (`runner_args.body` / room metadata / room-name prefix) to pick the builder.
3. **A dispatch/server front.** Wrap the FastAPI `/start` (or WorkerRunner) so one worker accepts many calls and starts a `PipelineTask` per call, under OpenRTC's supervision.
4. **Lifecycle signals.** Attach a `BaseObserver` (like voicegateway's) that emits OpenRTC's start/end signals from frame boundaries, feeding the introspection registry and the reload registry.
5. **voicegateway symmetry.** On the pipecat backend, OpenRTC should attach voicegateway's *pipecat* observer to the `PipelineTask` (as it emits the *livekit* SessionObserver payload today), so the cost/quality lane stays wired across both frameworks.

## Package / extras restructure (mirror voicegateway)

```
[project]
dependencies = [ "watchfiles>=0.21,<2" ]   # <- livekit REMOVED from the core

[project.optional-dependencies]
livekit = [ "livekit-agents[openai,silero,turn-detector]>=1.5,<1.7" ]
pipecat = [ "pipecat-ai>=1.5.0,<2.0" ]
cli     = [ "rich>=13", "typer>=0.12" ]
```

- `import openrtc` must import **neither** framework. Enforce with a test (mirror voicegateway) that imports the package in an env with neither installed and asserts success.
- `AgentPool(backend=...)` lazily imports `openrtc.backends.<name>`; a missing extra raises a clear error ("pip install openrtc[pipecat]"), exactly like voicegateway's `require_extra`.
- Directory: `openrtc/backends/{livekit,pipecat}/` for substrate; `openrtc/core/{backend.py, session_context.py}` for the seams; everything neutral stays where it is (retargeted onto `SessionContext`).

## Decision

**Proceed, phased, livekit-first-refactor then pipecat-second.** The seam is worth it: it turns OpenRTC from "a livekit density layer" into "the operator control plane for any voice runtime," which is the stronger and more defensible position (and matches how voicegateway already generalized). The refactor is real (29-module coupling) but mostly Tier-2 type retargeting, not logic rewrites.

Sequence:
1. **Neutralize the core (no behavior change).** Introduce `SessionContext` + `Backend`, move livekit substrate into `openrtc/backends/livekit/`, retarget Tier-2 modules onto `SessionContext`. The livekit backend must be behavior-identical (the 99% suite + integration tests are the gate). Move livekit to the `[livekit]` extra; add the neutral-import test.
2. **Add the pipecat backend** behind `openrtc[pipecat]`: registration, routing, shared prewarm, dispatch front, lifecycle observer, provider mapping. New integration tests against a Pipecat pipeline.
3. **Docs**: a "Frameworks" page + `<Tabs>` for livekit-vs-pipecat (see `docs-restructure.md`).

## Open questions

- **Provider mapping.** livekit plugin objects vs pipecat service objects are different types. Does `AgentConfig.stt/llm/tts` stay framework-specific per backend, or do we add a neutral provider spec (`"deepgram/nova-3"`) that each backend resolves? (Leaning: keep passthrough per-backend, since both frameworks accept their own objects; document the shorthand-string path as the portable one.)
- **`Agent` base class.** livekit users subclass `livekit.agents.Agent`; pipecat has no agent class (it's a pipeline). How does `pool.add(name, X)` stay uniform? Likely `X` is a *builder callable* `(SessionContext) -> session` on the pipecat side, and the livekit `Agent` subclass path is a livekit-backend convenience that wraps into a builder.
- **Hot reload on pipecat.** Reload swaps an `Agent` class mid-call. Pipecat has no class to swap; the unit of reload is the pipeline builder. Does `pin_reload` / rebind translate, or is reload a livekit-only feature initially? (Leaning: reload is livekit-first; pipecat reload is a later, separate design.)
- **Introspection.** `openrtc top` attributes per-session mem/cpu. On pipecat the per-session task tree differs; confirm the sampler works against pipecat's task structure or needs a backend hook.
- **`isolation="process"`.** Does the backend concept subsume isolation mode (coroutine/process are livekit-backend variants), or stay orthogonal? (Leaning: isolation is a livekit-backend option; pipecat is coroutine-only.)

## Task list for implementation (Loop 2)

1. Add `openrtc/core/session_context.py` (`SessionContext` protocol) + a livekit adapter wrapping `JobContext`. Retarget `routing/*` onto it (tests unchanged, green).
2. Add `openrtc/core/backend.py` (`Backend`/`BackendSession`); make `SessionRuntime` a livekit-backend detail. Move `runtime/*` substrate under `openrtc/backends/livekit/`.
3. Retarget `observability/base_observer` + `introspection` + `reload/*` onto `SessionContext` / `BackendSession`. Keep behavior identical; full suite + integration gate.
4. Move `livekit-agents` to `[livekit]` extra; add the "import with neither framework" test; add `require_extra` + backend lazy-selection in `AgentPool`.
5. Add `openrtc/backends/pipecat/` behind `[pipecat]`: builder registration, routing hookup, shared prewarm, dispatch front, lifecycle observer, provider mapping, integration tests.
6. Docs: Frameworks page + tabs.

Each step is additive and backward-compatible; the livekit path must not change behavior (that is the hard invariant and the review gate).
