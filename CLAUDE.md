# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common commands

All workflows go through `uv` (preferred over pip). The Makefile wraps the most-used ones.

| Task | Command |
| --- | --- |
| Install dev env | `uv sync --group dev` |
| Run all tests | `uv run pytest` |
| Tests with coverage gate (CI parity) | `uv run pytest --cov=openrtc --cov-report=xml --cov-fail-under=99` |
| Run a single test | `uv run pytest tests/test_pool.py::test_name -xvs` |
| Run integration tests only | `uv run pytest -m integration` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` |
| Type check | `uv run mypy src/` |
| Smoke-check discovery without LiveKit | `make dev` (or `uv run openrtc list ./examples/agents --default-stt … --default-llm … --default-tts …`) |
| Build wheel | `uv build` |

`mypy src/` (in `strict = true` mode), `ruff check` and `ruff format --check` run in CI (`.github/workflows/lint.yml`). The combined line + branch coverage gate is enforced at 99% (project sits around 99.4%).

Python 3.11+ is required; 3.10 will fail because the LiveKit Silero / turn-detector plugins pull `onnxruntime`, which has no 3.10 wheels.

## High-level architecture

OpenRTC is a thin layer on top of `livekit-agents` (and, optionally, `pipecat-ai`) that lets one worker process host many agent classes, with shared prewarm (Silero VAD, turn detector) loaded once instead of once per worker. User agents stay as standard `livekit.agents.Agent` subclasses; OpenRTC never introduces a custom base class. `import openrtc` pulls no voice framework: livekit and pipecat are opt-in extras (`openrtc[livekit]`, `openrtc[pipecat]`).

### Package layout (`src/openrtc/`)

- `core/pool.py`: `AgentPool`, the public facade (`add`, `discover`, `remove`, `run`, drain, observers, tenant/backpressure options). It builds a backend, wires routing + request filters, and owns the runtime state.
- `core/wiring.py`: the universal session entrypoint (`run_session`, `build_session`). Per job: resolve the agent, instantiate it, build an `AgentSession` from pool defaults + per-agent + per-tenant overrides, attach the prewarmed VAD from `proc.userdata`, start.
- `core/backend.py`: the framework-neutral `Backend` protocol. `backends/registry.py` resolves `AgentPool(backend="livekit"|"pipecat")` lazily; implementations live in `backends/livekit/` and `backends/pipecat/`.
- `core/config.py`, `core/discovery.py`, `core/serialization.py`: registration data, `@agent_config` discovery, and spawn-safe provider serialization.
- `core/tenant_config.py`, `core/circuit_breaker.py`, `core/audit.py`: multi-tenancy (per-tenant providers, caps, blast-radius breaker) and the audit log.
- `runtime/`: isolation modes. `coroutine_runtime.py` + `coroutine_server.py` (default, `isolation="coroutine"`) run every session as an `asyncio.Task` in one process by swapping livekit's `ProcPool` for a `CoroutinePool`; `process_runtime.py` (`isolation="process"`) is livekit's stock process-per-job server. `prewarm.py` holds `_prewarm_worker` — add new shared resources there.
- `routing/`: strategy chain (`resolver.py`, `metadata_routing.py`, `room_prefix_routing.py`, `default_routing.py`) and per-job accept/reject filters (`request_filter.py`).
- `observability/`: session observers, JSONL metrics stream, per-session memory/CPU/slow-callback attribution, and the introspection IPC behind `openrtc top`.
- `reload/`: hot reload for `openrtc dev` (module reload, rebind live sessions on next turn, rollback on bad save).
- `cli/`: Typer app (see below).

### Routing chain

Priority order (`routing/`):

1. `ctx.job.metadata["agent"]` / `["demo"]`
2. `ctx.room.metadata["agent"]` / `["demo"]`
3. Room name prefix match (e.g. `restaurant-call-123` → `restaurant`)
4. First registered agent (fallback)

A custom `router=` on `AgentPool` can override this. A metadata value naming an unregistered agent raises `ValueError`. Do not silently fall back.

### Coroutine mode depends on livekit-agents internals

`runtime/coroutine_runtime.py` imports private livekit-agents surfaces (`ipc.job_executor`, `job._JobContextVar`, `ipc.proc_pool`). The pin (`>=1.5,<1.9`) is deliberately tight; an unsupported version fails import with a message pointing to `isolation="process"`. `.github/workflows/canary.yml` runs the suite against the latest livekit-agents release. When bumping the pin: relock with `uv lock --upgrade-package livekit-agents`, run the full suite against the real SDK, and update the range in `pyproject.toml`, `README.md`, `docs/getting-started.md`, `AGENTS.md` and the error message in `coroutine_runtime.py`.

### Provider passthrough contract

`ProviderValue = str | object` (see `utils/types.py`). Anything passed to `stt=`, `llm=`, `tts=` on `pool.add()` or as pool defaults is forwarded to `AgentSession` unchanged: instantiated plugin objects (`openai.STT(...)`) work, and so do shorthand strings (`"openai/gpt-4o-mini-transcribe"`) — the LiveKit runtime resolves the strings at session construction time. OpenRTC does not interpret or validate them.

### Spawn-safe configuration

Worker processes can be spawned (LiveKit's default on macOS, and always in `isolation="process"`), so anything captured by the entrypoint must survive serialization across the process boundary. `core/serialization.py` captures `livekit.plugins.*` provider instances as `_ProviderRef(module, qualname, kwargs-from-_opts)` and rebuilds them in the worker. This relies on a plugin's `_opts` mirroring its constructor kwargs; when upstream drifts (e.g. openai STT 1.8 stores `language=` as `_opts.languages`), patch `_extract_provider_kwargs`. When adding new fields to `AgentConfig` or related dataclasses, keep them serialization-safe (no live sockets, no open files, no `lambda`/local closures).

### Test conftest shim

`tests/conftest.py` contains a hand-maintained stub of `livekit.agents` that activates **only when `livekit.agents` cannot be imported**. With `uv sync --group dev`, the real wheel is installed and the shim is bypassed. Two consequences:

- When you upgrade the `livekit-agents` pin or use a new symbol from `livekit.agents` in `src/`, run the suite locally against the real SDK and extend the shim if a CI environment without LiveKit would break. Tests that fake `RunningJobInfo` with `SimpleNamespace` must carry any field upstream now reads (e.g. `job.enable_redaction` since 1.8).
- If imports behave oddly in tests, check whether the shim path is active — the symbol you expect from upstream may not be implemented in the stub.

### CLI architecture

`cli/__init__.py` re-exports `main` and `app`. `cli/entry_cli.py` is the lazy entrypoint that prints a friendly message if the `cli` extra isn't installed, then defers to `cli/main_cli.py` (the Typer app). Worker subcommands (`start`, `dev`, `console`, `connect`, `download-files`) mirror the LiveKit Agents CLI shape; OpenRTC-only commands are `list`, `serve` (pipecat), `logs`, and `top` (live session inspector, `openrtc[top]` adds psutil host vitals). OpenRTC-only flags (`--agents-dir`, `--metrics-jsonl`, etc.) are stripped before handoff in `cli/livekit_cli.py`, which rewrites `sys.argv` and applies env overrides before calling `pool.run()`. `cli/pipecat_cli.py`, `cli/top_cli.py`, `cli/dashboard_cli.py`, `cli/reporter_cli.py` hold the rest; shared helpers live in `cli/base_cli.py`.

### Versioning and release

- Version is derived from git tags via `hatch-vcs`. Dev checkouts produce versions like `0.0.17.dev0+g<hash>`. Do not hand-edit `_version.py`.
- `.github/workflows/publish.yml` triggers on GitHub releases tagged `v*`, builds with `uv build`, publishes to PyPI, then commits a `docs/changelog.md` entry derived from the release body. The changelog commit message uses `[skip ci]`.

## Important constraints (from CONTRIBUTING.md)

These are non-negotiable product invariants — preserve them in any change:

1. User agents remain standard `livekit.agents.Agent` subclasses. No OpenRTC base class.
2. Shared runtime assets (VAD, turn detector) load in prewarm, not per call.
3. Public API stays explicit. Routing precedence and registration semantics are documented in the README — keep them in sync.
4. Prefer additive, backward-compatible changes. Breaking changes need clear justification, doc updates, and a changelog note.

The full coding-style guide lives in `AGENTS.md` (typing rules, async patterns, error-handling expectations, LiveKit-specific guidance). Read it before non-trivial changes.

## Strategic context

OpenRTC's purpose is to make self-hosted LiveKit agents cheap to run: 50+ concurrent sessions per worker instead of livekit-agents' ~1 session per process. `docs/audit-2026-05-02.md` is the original audit that motivated this; its recommended Option B (a custom `JobExecutor` running jobs as `asyncio.Task`s) is now implemented as coroutine isolation (`runtime/coroutine_runtime.py`), the default. Design notes for the livekit internals it hooks live in `docs/design/` (pinned to 1.5.0 source; re-derive when the pin moves).
