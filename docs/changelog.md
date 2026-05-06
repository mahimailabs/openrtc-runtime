# Changelog

All notable changes to this project are documented here.
Entries are added automatically when a new GitHub release is published.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

Changes that have landed on `main` but have not yet been tagged for release.

### v0.1.0 — coroutine-mode worker (default behavior change)

> **Heads up:** the default isolation flips from process-per-session to
> a coroutine-mode worker that hosts every session as an `asyncio.Task`
> inside one process. The user-facing API does not break, but workers
> behave differently at runtime. Read the migration notes below before
> upgrading production deployments.

**Added**

- `AgentPool(isolation="coroutine" | "process")` selects the worker
  isolation mode. `"coroutine"` is the new default; `"process"`
  preserves v0.0.17 behavior (one OS subprocess per session via
  `livekit-agents`'s `ProcPool`).
- `AgentPool(max_concurrent_sessions=50)` sets the coroutine-mode
  backpressure threshold. The worker reports `load >= 1.0` to the
  LiveKit dispatcher once this many sessions are in flight; ignored
  in process mode.
- `AgentPool(consecutive_failure_limit=5)` sets the worker supervisor
  threshold. After this many non-`SUCCESS` session terminations the
  worker calls `aclose()` so the deployment platform can restart it
  (bounded blast radius for systemic bugs). Ignored in process mode.
- `AgentPool(drain_timeout=30)` bounds the graceful-drain window.
  When SIGTERM (or SIGINT) is delivered, upstream `AgentServer`'s
  signal handler calls `aclose()`; `drain_timeout` is the per-pool
  budget for in-flight sessions to finish. Sessions that exceed it
  are cancelled with a `WARNING` log and the per-executor `kill()`
  escalation runs. Honored in both isolation modes (forwarded to
  upstream `AgentServer` via the constructor kwarg).
- New CLI flags `--isolation` and `--max-concurrent-sessions` on
  `start` / `dev` / `console`. Both also read environment variables
  (`OPENRTC_ISOLATION`, `OPENRTC_MAX_CONCURRENT_SESSIONS`); precedence
  is CLI flag > env var > library default.
- New `openrtc.execution.coroutine.CoroutinePool` and
  `CoroutineJobExecutor` (internal). Both implement the
  `livekit.agents.ipc.proc_pool.ProcPool` / `JobExecutor` shapes;
  `_CoroutineAgentServer` (also internal) monkey-patches `ProcPool`
  during `run()` so `AgentServer`'s state machine and dispatcher
  protocol are reused unchanged.
- New `tests/benchmarks/density.py` script and corresponding CI gate
  (`.github/workflows/bench.yml`) enforcing ≥ 50 concurrent sessions
  per worker at ≤ 4 GB peak RSS on every PR.
- New nightly canary CI job (`.github/workflows/canary.yml`) that
  runs the integration suite against the latest released
  `livekit-agents` and is allowed to fail.
- New `docker-compose.test.yml` + `tests/integration/conftest.py`
  fixture harness for local and CI integration runs.

**Changed**

- `livekit-agents` pin tightened from `~=1.4` to `~=1.5` because the
  internal-ish surfaces we hook (`ProcPool`, `JobExecutor` Protocol)
  are version-sensitive; the canary job watches the next minor.
- Source layout reorganised under `core/`, `cli/`, `observability/`,
  `tui/`, and `execution/` packages. Public imports
  (`from openrtc import AgentPool`, etc.) are unchanged; internal
  consumers should update to the canonical paths
  (`openrtc.core.config.AgentConfig`, etc.).

**Migration**

- Existing code that does `pool = AgentPool()` keeps working but now
  runs every session in coroutine mode. To stay on the v0.0.17
  process-per-session model, pass `isolation="process"`:

  ```python
  pool = AgentPool(isolation="process")
  ```

  Pick `"process"` when:
  - regulatory or compliance requirements demand hard process
    isolation between sessions;
  - per-session memory caps (`livekit-agents`' `job_memory_limit_mb`)
    are required;
  - the workload mixes very heavy agents with very light agents and
    you want subprocess-level resource accounting.

  Pick the new default `"coroutine"` when:
  - you run many concurrent sessions on a single host and the
    prewarm/idle baseline (VAD, turn detector) was the dominant cost;
  - you want backpressure routed back to LiveKit dispatch via load
    reporting instead of OS-level rejection.

- `consecutive_failure_limit` defaults to 5 in coroutine mode. If your
  agents legitimately fail more often (e.g. exploratory dev runs),
  raise the threshold or run under `isolation="process"` (which the
  setting does not affect).

- The `current_load()` reported in coroutine mode is
  `len(active) / max_concurrent_sessions`. If your dispatch policy
  was tuned around `livekit-agents`' default CPU-based load math, the
  new shape may route differently — verify against your dispatch
  thresholds (`load_threshold` defaults to `0.7`).

- Per-session memory caps (`job_memory_limit_mb` on `AgentServer`)
  cannot be enforced in coroutine mode (one process, no subprocess
  boundary). Process mode preserves the cap. Documented in design
  §9.4.

See `docs/concepts/architecture.md` for the coroutine-mode lifecycle
and `docs/benchmarks/density-v0.1.md` for the §7 success-gate
benchmark numbers.

**Developer experience**

User-facing behavior is unchanged by these — they land here so the
contributor onboarding matches what's in the repo.

- Test coverage: combined line + branch coverage now sits at 100%
  with the CI gate at 99% (was 80% line-only). `pytest` runs with
  `branch = true` by default.
- Type checking: `mypy` runs in `strict = true` mode on `src/`. CI
  blocks PRs with untyped defs, implicit `Optional`, redundant
  casts, or `Any` returns.
- Linting: ruff selects expanded to include `SIM`, `PT`, `RET`,
  `PERF`, `PIE`, `ICN`, `TID`, `BLE`, `A` on top of the previous
  `E`/`W`/`F`/`I`/`B`/`C4`/`UP` set.
- Pre-commit hook chain extended with `mypy --strict src/` so the
  same typecheck CI applies fires locally on every commit (only
  for source / `pyproject.toml` changes).
- New `make ci` aggregate target runs `lint format-check typecheck
  test` in the same order as CI, short-circuiting on the first
  failure.
- `.github/dependabot.yml` keeps Python and GitHub Actions
  dependencies fresh weekly; `livekit-agents` is intentionally
  excluded (the `~=1.5` pin is design-locked).
- `.github/PULL_REQUEST_TEMPLATE.md` adds a short checklist for
  contributors. `.editorconfig` keeps file-level conventions
  consistent across editors. `SECURITY.md` documents the
  vulnerability-disclosure intake path.

---

<!-- releases -->

## [0.2.1] - 2026-05-06

## What's Changed
* [v0.2.1] File watcher infrastructure for agent code (MAH-80) by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/39


**Full Changelog**: https://github.com/mahimailabs/openrtc-runtime/compare/v0.1.0...v0.2.1

---

## [0.1.0] - 2026-05-06

## What's Changed
* Feat: light websocket by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/30
* docs: bring docs/ in sync with v0.1 surface by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/35
* Feat: struc refac by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/36
* Feat/coroutine pool by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/37
* Feat/coroutine pool prod by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/38


**Full Changelog**: https://github.com/mahimailabs/openrtc-runtime/compare/v0.0.17...v0.1.0

---

## [0.0.17] - 2026-04-03

## What's Changed
* feat: enable generic serialization for all LiveKit plugins  by @mahimairaja in https://github.com/mahimairaja/openrtc-python/pull/28


**Full Changelog**: https://github.com/mahimairaja/openrtc-python/compare/v0.0.16...v0.0.17

---

## [0.0.16] - 2026-03-23

## What's Changed
* DX improvements: uv CI, DeprecationWarning for legacy session_kwargs, CHANGELOG, issue templates, Makefile, .env.example by @Copilot in https://github.com/mahimairaja/openrtc-python/pull/26


**Full Changelog**: https://github.com/mahimairaja/openrtc-python/compare/v0.0.15...v0.0.16

---

## [0.0.15] - 2026-03-22

### Fixed
- CLI: generic error message in `validate_metrics_watch_path`; restored
  `sys.argv` correctly when `main(argv=…)` is called programmatically.

### Added
- CLI: positional shortcuts for `list`, `connect`, `download-files`, and `tui`
  commands so the agents directory and metrics path can be passed as positional
  arguments.
- CLI: positional agents dir and metrics JSONL path on `start`/`dev`/`console`.
- CLI: `openrtc tui` defaults `--watch` to `./openrtc-metrics.jsonl`.
- `DeprecationWarning` emitted when deprecated `session_kwargs` top-level keys
  (e.g. `allow_interruptions`, `min_endpointing_delay`) are used instead of the
  `turn_handling` dict.
- GitHub issue templates for bug reports and feature requests.
- `Makefile` with shortcuts for common developer commands (`make test`,
  `make lint`, `make format`, `make typecheck`).
- `.env.example` documenting all supported environment variables.

### Changed
- CI test and lint workflows migrated from bare `pip` to `uv` with lockfile
  caching, matching the `uv sync --group dev` workflow in `CONTRIBUTING.md`.

---

## [0.0.14] - 2026-03-22

### Changed
- Require **Python 3.11+** (dropped 3.10; transitive `onnxruntime` does not
  ship supported wheels for 3.10).
- CLI refactored into focused submodules (`cli_app`, `cli_livekit`,
  `cli_params`, `cli_reporter`, `cli_types`, `cli_dashboard`).
- Added `ProviderValue` type alias (`str | object`) for STT/LLM/TTS slots;
  exported from the public package surface.
- `SharedLiveKitWorkerOptions` dataclass bundles worker hand-off options.
- Provider serialisation registry (`_PROVIDER_REF_KEYS`) for spawn-safe
  round-trip of OpenAI plugin objects; OpenAI `NotGiven` sentinel detected
  without coupling to `repr()`.

---

## [0.0.13] - 2026-03-22

### Added
- Runtime CLI observability dashboard (`openrtc dev --dashboard`).
- Metrics JSONL stream: session lifecycle events written to a configurable
  `.jsonl` file for the TUI sidecar (`--metrics-jsonl`).
- Textual sidecar TUI (`openrtc tui`); optional install with
  `pip install 'openrtc[tui]'`.

### Fixed
- Leaked runtime session counters after session errors.

---

## [0.0.12] - 2026-03-21

### Added
- `AgentConfig.source_path` records the resolved path of the discovered module.
- Resource monitoring: `get_process_resident_set_info()` and
  `SavingsEstimate`; `pool.runtime_snapshot()` includes live memory data.
- Coverage gate enforced at 80% (`--cov-fail-under=80`).

---

## [0.0.11] - 2026-03-21

### Fixed
- `resource` module lazy-imported on Windows where `RUSAGE_SELF` is absent.

---

## [0.0.9] - 2026-03-21

### Added
- Agent resource monitoring via `PoolRuntimeSnapshot` and
  `RuntimeMetricsStore`.
- `pool.runtime_snapshot()` public method.
- `pool.drain_metrics_stream_events()` public method.

---

## [0.0.8] - 2026-03-21

### Fixed
- `PicklingError` for agent classes discovered from non-package modules in
  `dev` / spawn mode; `_AgentClassRef` now stores and resolves by file path.

---

## [0.0.5] - 2026-03-21

### Added
- `AgentPool.discover()` for automatic one-file-per-agent discovery.
- `@agent_config(name, stt, llm, tts, greeting)` decorator for per-agent
  metadata in discovered modules.
- Room-name prefix routing fallback.

### Fixed
- Worker callbacks made spawn-safe; `AgentPool` state serialised through
  `_PoolRuntimeState` for cross-process delivery.

---

## [0.0.2] - 2026-03-20

### Added
- Initial public release.
- `AgentPool` with `add()`, `remove()`, `get()`, `list_agents()`, and `run()`.
- Job and room metadata routing (`agent` / `demo` keys).
- Shared prewarm for Silero VAD and multilingual turn detector.
- `AgentSession` wired per call with per-agent STT/LLM/TTS providers.
- Greeting support via `session.generate_reply()`.
- `openrtc[cli]` optional extra for `rich`/`typer` CLI.
- PEP 561 `py.typed` marker shipped in the wheel.
