# OpenRTC-Python v0.1 — Task List

Pick the **first** unchecked task. Tasks are roughly ordered by
dependency. Do not skip ahead unless a task is blocked.

Status legend: `[ ]` todo, `[x]` done, `[~]` skipped (note why),
`[?]` blocked (note why).

---

## Phase 0 — Repository structure refactor

Current layout is flat (15 files at top level). Reorganize into
domain-grouped packages before adding new code. This makes the
coroutine work clean and gives the project headroom.

Target layout (also documented in design §6.1):

    src/openrtc/
    ├── __init__.py
    ├── py.typed
    ├── types.py                  # was provider_types.py
    ├── core/
    │   ├── __init__.py
    │   ├── pool.py               # AgentPool (slim)
    │   ├── config.py             # AgentConfig, AgentDiscoveryConfig, @agent_config
    │   ├── routing.py            # extracted from pool.py
    │   ├── discovery.py          # extracted from pool.py
    │   ├── serialization.py      # _ProviderRef logic
    │   └── turn_handling.py      # deprecated kwargs translation
    ├── execution/
    │   ├── __init__.py
    │   ├── coroutine.py          # NEW: CoroutinePool, CoroutineJobExecutor
    │   ├── coroutine_server.py   # NEW: _CoroutineAgentServer
    │   └── prewarm.py            # shared prewarm helpers
    ├── observability/
    │   ├── __init__.py
    │   ├── metrics.py            # was resources.py
    │   ├── stream.py             # was metrics_stream.py
    │   └── snapshot.py           # PoolRuntimeSnapshot etc
    ├── cli/
    │   ├── __init__.py
    │   ├── entry.py              # was cli.py (lazy entrypoint)
    │   ├── app.py                # was cli_app.py
    │   ├── dashboard.py          # was cli_dashboard.py
    │   ├── livekit.py            # was cli_livekit.py
    │   ├── params.py             # was cli_params.py
    │   ├── reporter.py           # was cli_reporter.py
    │   └── types.py              # was cli_types.py
    └── tui/
        ├── __init__.py
        └── app.py                # was tui_app.py

Refactor rules:
- Use `git mv` to preserve blame.
- Update all imports in one pass per moved file.
- Re-export public symbols from `src/openrtc/__init__.py` so the
  user-facing `from openrtc import AgentPool` still works.
- After each move: run tests; commit before moving the next file.
- Do NOT change behavior — pure file moves and import rewrites only.

Tasks:
- [x] Delete dead code: `_version.py`, `AgentPool._resolve_agent`,
  `AgentPool._handle_session`, underscore-prefixed exports in
  `cli_app.__all__`. Verify no external references.
- [x] Rename `provider_types.py` → `types.py`.
- [x] Create `core/` package. Move `pool.py` into it (no split yet).
- [x] Extract `core/config.py` from `pool.py`: `AgentConfig`,
  `AgentDiscoveryConfig`, `agent_config` decorator.
- [x] Extract `core/routing.py` from `pool.py`: `_resolve_agent_config`
  and routing helpers (currently `pool.py:781-853`).
- [x] Extract `core/discovery.py` from `pool.py`: `discover()`
  module loading helpers (currently `pool.py:378-431`).
- [x] Extract `core/serialization.py` from `pool.py`: `_ProviderRef`,
  `_PROVIDER_REF_KEYS`, `_try_build_provider_ref`,
  `__getstate__/__setstate__` helpers (currently `pool.py:573-646`).
- [x] Extract `core/turn_handling.py` from `pool.py`: deprecated
  kwargs translation logic (currently `pool.py:42-53, 649-778`).
- [x] Create `observability/` package skeleton (empty
  `__init__.py`) and rename `resources.py` →
  `observability/metrics.py`. Update all import sites.
- [x] Rename `metrics_stream.py` → `observability/stream.py`.
  Update all import sites.
- [x] Extract `PoolRuntimeSnapshot` (and the
  `ProcessResidentSetInfo` / `SavingsEstimate` payload dataclasses
  it embeds) from `observability/metrics.py` to
  `observability/snapshot.py`. `metrics.py` imports the snapshot
  types back in.
- [x] Create `cli/` package. Move all `cli_*.py` files in, dropping
  the `cli_` prefix. Update entrypoint references. (Note: `cli_app.py`
  → `cli/commands.py`, not `cli/app.py`, because Python collides
  the submodule name with the re-exported `app` Typer instance at
  the package level. Documented in `cli/__init__.py`.)
- [x] Create `tui/` package. Move `tui_app.py` to `tui/app.py`.
- [x] Verify `from openrtc import AgentPool, AgentConfig,
  AgentDiscoveryConfig, agent_config, ProviderValue` still works.
- [x] Verify `openrtc dev`, `openrtc list`, `openrtc tui` still work.
- [x] Verify all 124 tests still pass. (Suite has grown to 130
  since the original count; full CI coverage gate also satisfied
  at 90.31%, well above the 80% floor.)

---

## Phase 1 — Coroutine pool prototype (Week 1)

Goal: prove the density win. Stop and reassess if we can't hit 50
sessions in 4 GB.

Tasks:
- [x] Pin `livekit-agents~=1.5` exactly in `pyproject.toml`.
- [x] Read `livekit/agents/ipc/job_executor.py` at the pinned
  version. Document the `JobExecutor` Protocol surface in
  `docs/design/job-executor-protocol.md`.
- [x] Read `livekit/agents/ipc/proc_pool.py`. Document the
  `ProcPool` surface that `AgentServer` calls.
- [x] Read `livekit/agents/worker.py`. Document where
  `AgentServer` instantiates and uses `_proc_pool`.
- [x] Add `isolation: Literal["coroutine", "process"]` parameter to
  `AgentPool.__init__`, default `"coroutine"`. Thread through but
  don't act on it yet — just plumbing.
- [x] Add `max_concurrent_sessions: int = 50` parameter to
  `AgentPool.__init__`. Plumbing only.
- [x] Create `execution/coroutine.py`: skeleton classes
  `CoroutineJobExecutor` and `CoroutinePool` satisfying the
  `JobExecutor` Protocol but raising `NotImplementedError` in all
  methods. Add basic unit tests verifying the Protocol shape.
- [x] Implement `CoroutineJobExecutor.initialize()` and `aclose()`.
- [x] Implement `CoroutineJobExecutor.launch_job(info)`: construct
  `JobContext` referencing the shared `JobProcess` singleton;
  schedule the entrypoint as `asyncio.Task`; wrap exceptions to
  prevent escape. (Note: actual `JobContext` construction is
  delegated to a `context_factory` callable injected at executor
  construction time. The CoroutinePool will own the real factory
  once it's wired up; tests inject stubs.)
- [x] Implement `CoroutineJobExecutor.kill()` and status reporting.
  (Note: `kill()` is NOT part of the upstream JobExecutor Protocol
  at 1.5.0 — it is an OpenRTC-internal forceful escalation hook
  beyond `aclose()`. Status reporting was already correct via the
  property; the iteration verifies idle / in-flight / completed
  semantics under kill.)
- [x] Implement `CoroutinePool.start()`: invoke `setup_fnc` once,
  populate the singleton `JobProcess.userdata` with shared models.
- [x] Implement `CoroutinePool.launch_job()`: instantiate a
  `CoroutineJobExecutor`, track it, return.
- [x] Implement `CoroutinePool.current_load()`:
  `len(active) / max_concurrent_sessions`. (Note: not part of the
  upstream ProcPool surface; AgentPool will register the pool's
  current_load as a custom load_fnc when the wiring lands.)
- [x] Implement `CoroutinePool.aclose()`: drain — cancel all
  executors, await them.
- [x] Create `execution/coroutine_server.py`: `_CoroutineAgentServer`
  subclass that swaps `_proc_pool` for our `CoroutinePool`.
- [x] Wire `AgentPool` to choose between `AgentServer()` and
  `_CoroutineAgentServer(...)` based on `isolation` parameter.
- [x] First end-to-end smoke test: `AgentPool(isolation="coroutine")`
  registers, accepts one simulated job, runs it to completion.
- [x] Density benchmark script `tests/benchmarks/density.py`: spawn
  50 simulated jobs concurrently in one worker; record peak RSS.
- [x] Run density benchmark. Record results in
  `docs/benchmarks/density-v0.1.md`.

**Phase 1 success gate:** density benchmark shows ≥ 50 concurrent
sessions at ≤ 4 GB RSS, no errors. If not met, add a
"Phase 1 reassessment" section to TODO.md and stop.

---

## Phase 2 — Productionize (Week 2)

Tasks:
- [ ] Per-job error isolation test: a session raising
  `RuntimeError` does not affect 4 sibling sessions.
- [ ] Implement worker supervisor: track consecutive session
  failures; after N (default 5), call `aclose()` and exit non-zero.
- [ ] Implement graceful drain on SIGTERM: stop accepting jobs;
  await in-flight to complete.
- [ ] Add CLI flag `--isolation` to `cli/app.py` (default
  `coroutine`). Add `--max-concurrent-sessions` (default 50).
  Wire through `cli/params.py`.
- [ ] Set up containerized LiveKit dev server for integration tests
  in CI (`docker-compose.test.yml`).
- [ ] Write integration test: 5 concurrent real calls in one
  coroutine worker, all complete with real STT/LLM/TTS.
  Mark with `pytest.mark.integration`.
- [ ] Verify `isolation="process"` mode behaves identically to
  v0.0.17 (regression test against existing test suite).
- [ ] Backpressure test: with `max_concurrent_sessions=10`, the
  11th job is rejected; LiveKit dispatch sees `load >= 1.0`.
- [ ] Drain test: SIGTERM with 3 in-flight sessions waits for
  completion before worker exits.
- [ ] Add CI canary job that runs `pytest -m integration` against
  the latest `livekit-agents` release (allowed to fail;
  informational).
- [ ] Add CI density benchmark job; fail if peak RSS > 4 GB.
- [ ] Update `README.md`: add isolation modes section, density
  benchmark table, when-to-use-which guidance.
- [ ] Update `docs/concepts/architecture.md` with coroutine-mode
  lifecycle.
- [ ] Add migration note to `docs/changelog.md` for v0.1.0 entry,
  flagging the default behavior change (process → coroutine).
- [ ] Bump version to `0.1.0` in `pyproject.toml`.
- [ ] Tag `v0.1.0` and verify PyPI publish workflow succeeds.

**Phase 2 success gate:** all 12 acceptance criteria in
`docs/design/v0.1.md` §8 pass.

---

## Discovered work

(Add new tasks here as they come up. Keep this section ordered by
priority.)dead-code-cleanup

- [ ] _none yet_
