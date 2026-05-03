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
- [ ] Rename `metrics_stream.py` → `observability/stream.py`.
  Update all import sites.
- [ ] Extract `PoolRuntimeSnapshot` (and the
  `ProcessResidentSetInfo` / `SavingsEstimate` payload dataclasses
  it embeds) from `observability/metrics.py` to
  `observability/snapshot.py`. `metrics.py` imports the snapshot
  types back in.
- [ ] Create `cli/` package. Move all `cli_*.py` files in, dropping
  the `cli_` prefix. Update entrypoint references.
- [ ] Create `tui/` package. Move `tui_app.py` to `tui/app.py`.
- [ ] Verify `from openrtc import AgentPool, AgentConfig,
  AgentDiscoveryConfig, agent_config, ProviderValue` still works.
- [ ] Verify `openrtc dev`, `openrtc list`, `openrtc tui` still work.
- [ ] Verify all 124 tests still pass.

---

## Phase 1 — Coroutine pool prototype (Week 1)

Goal: prove the density win. Stop and reassess if we can't hit 50
sessions in 4 GB.

Tasks:
- [ ] Pin `livekit-agents~=1.5` exactly in `pyproject.toml`.
- [ ] Read `livekit/agents/ipc/job_executor.py` at the pinned
  version. Document the `JobExecutor` Protocol surface in
  `docs/design/job-executor-protocol.md`.
- [ ] Read `livekit/agents/ipc/proc_pool.py`. Document the
  `ProcPool` surface that `AgentServer` calls.
- [ ] Read `livekit/agents/worker.py`. Document where
  `AgentServer` instantiates and uses `_proc_pool`.
- [ ] Add `isolation: Literal["coroutine", "process"]` parameter to
  `AgentPool.__init__`, default `"coroutine"`. Thread through but
  don't act on it yet — just plumbing.
- [ ] Add `max_concurrent_sessions: int = 50` parameter to
  `AgentPool.__init__`. Plumbing only.
- [ ] Create `execution/coroutine.py`: skeleton classes
  `CoroutineJobExecutor` and `CoroutinePool` satisfying the
  `JobExecutor` Protocol but raising `NotImplementedError` in all
  methods. Add basic unit tests verifying the Protocol shape.
- [ ] Implement `CoroutineJobExecutor.initialize()` and `aclose()`.
- [ ] Implement `CoroutineJobExecutor.launch_job(info)`: construct
  `JobContext` referencing the shared `JobProcess` singleton;
  schedule the entrypoint as `asyncio.Task`; wrap exceptions to
  prevent escape.
- [ ] Implement `CoroutineJobExecutor.kill()` and status reporting.
- [ ] Implement `CoroutinePool.start()`: invoke `setup_fnc` once,
  populate the singleton `JobProcess.userdata` with shared models.
- [ ] Implement `CoroutinePool.launch_job()`: instantiate a
  `CoroutineJobExecutor`, track it, return.
- [ ] Implement `CoroutinePool.current_load()`:
  `len(active) / max_concurrent_sessions`.
- [ ] Implement `CoroutinePool.aclose()`: drain — cancel all
  executors, await them.
- [ ] Create `execution/coroutine_server.py`: `_CoroutineAgentServer`
  subclass that swaps `_proc_pool` for our `CoroutinePool`.
- [ ] Wire `AgentPool` to choose between `AgentServer()` and
  `_CoroutineAgentServer(...)` based on `isolation` parameter.
- [ ] First end-to-end smoke test: `AgentPool(isolation="coroutine")`
  registers, accepts one simulated job, runs it to completion.
- [ ] Density benchmark script `tests/benchmarks/density.py`: spawn
  50 simulated jobs concurrently in one worker; record peak RSS.
- [ ] Run density benchmark. Record results in
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
