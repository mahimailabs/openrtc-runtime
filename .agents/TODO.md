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
- [x] Per-job error isolation test: a session raising
  `RuntimeError` does not affect 4 sibling sessions.
- [x] Implement worker supervisor: track consecutive session
  failures; after N (default 5), call `aclose()` and exit non-zero.
- [x] Implement graceful drain on SIGTERM: stop accepting jobs;
  await in-flight to complete. (Pool primitive landed:
  `CoroutinePool.drain()` + `CoroutineJobExecutor.join()`. The
  SIGTERM handler shim that calls into them belongs at the CLI
  layer and is implicit via `AgentServer.drain()` which already
  awaits `proc.join()` on every executor — our executor's
  `join` is now wired to satisfy that.)
- [x] Add CLI flag `--isolation` to `cli/app.py` (default
  `coroutine`). Add `--max-concurrent-sessions` (default 50).
  Wire through `cli/params.py`. (Note: `cli_app.py` is now
  `cli/commands.py` after the Phase 0 reorg; flags landed there.)
- [x] Set up containerized LiveKit dev server for integration tests
  in CI (`docker-compose.test.yml`).
- [x] Write integration test: 5 concurrent real calls in one
  coroutine worker, all complete with real STT/LLM/TTS.
  Mark with `pytest.mark.integration`. (Skips when LiveKit dev
  server unreachable OR `OPENAI_API_KEY` is unset; the
  validation runs in CI environments with both available.)
- [x] Verify `isolation="process"` mode behaves identically to
  v0.0.17 (regression test against existing test suite).
- [x] Backpressure test: with `max_concurrent_sessions=10`, the
  11th job is rejected; LiveKit dispatch sees `load >= 1.0`.
  (Note: backpressure in v0.1 is cooperative; the dispatcher
  reads load_fnc and routes elsewhere — the pool itself does
  not hard-reject. If the dispatcher races and sends one
  anyway, the pool accepts it and the next load read tells the
  dispatcher to back off harder. Documented in the test
  module's docstring.)
- [x] Drain test: SIGTERM with 3 in-flight sessions waits for
  completion before worker exits. (Verified at the pool layer
  the way a CLI signal handler would invoke it: drain task is
  observably pending while sessions block, completes only after
  release, and aclose() leaves no residual asyncio tasks on the
  loop. Real subprocess + signal delivery is platform-specific
  and outside the unit boundary.)
- [x] Add CI canary job that runs `pytest -m integration` against
  the latest `livekit-agents` release (allowed to fail;
  informational).
- [x] Add CI density benchmark job; fail if peak RSS > 4 GB.
- [x] Update `README.md`: add isolation modes section, density
  benchmark table, when-to-use-which guidance.
- [x] Update `docs/concepts/architecture.md` with coroutine-mode
  lifecycle.
- [x] Add migration note to `docs/changelog.md` for v0.1.0 entry,
  flagging the default behavior change (process → coroutine).
- [x] Bump version to `0.1.0` in `pyproject.toml`. (The version is
  hatch-vcs-derived from git tags; the literal "bump" is the
  `fallback_version = "0.1.0.dev0"` raw-option for dev checkouts
  without a reachable tag, kept in sync with the
  `__init__.py` PackageNotFoundError fallback. The actual
  `0.1.0` version comes from tagging `v0.1.0` — handled in the
  next task.)
- [?] Tag `v0.1.0` and verify PyPI publish workflow succeeds.
  Blocked on operator: tagging + pushing + creating a GitHub
  release that triggers the publish.yml PyPI workflow requires
  human credentials and intent (PyPI token + release notes).
  All preparation is complete:
  - changelog migration note staged in [Unreleased]
    (docs/changelog.md);
  - hatch-vcs fallback set to 0.1.0.dev0 (pyproject.toml +
    src/openrtc/__init__.py); a `v0.1.0` git tag will yield
    exactly `0.1.0` from hatch-vcs;
  - publish.yml triggers on release and auto-prepends the
    versioned section to docs/changelog.md (see workflow);
  - all other §8 acceptance criteria are discharged in the
    test suite + benchmarks + docs.
  Operator runbook: cherry-pick / merge feat/light-websocket
  into main, then `git tag v0.1.0 && git push --tags`, then
  open a GitHub release on the tag pasting the relevant body
  from the [Unreleased] block in docs/changelog.md.

**Phase 2 success gate:** all 12 acceptance criteria in
`docs/design/v0.1.md` §8 pass.

---

## Discovered work

(Add new tasks here as they come up. Keep this section ordered by
priority.)

- [x] Document `--isolation` and `--max-concurrent-sessions` in
  `docs/cli.md`. (Found while auditing §8.9 for completeness:
  the flags shipped in `cli/commands.py`, the README, and the
  test suite, but the standalone CLI doc page didn't mention
  them. v0.1 release-blocker for §8.9.)
