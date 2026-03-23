# Changelog

All notable changes to this project are documented here.
Entries are added automatically when a new GitHub release is published.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

Changes that have landed on `main` but have not yet been tagged for release.

---

<!-- releases -->

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
