# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common commands

All workflows go through `uv` (preferred over pip). The Makefile wraps the most-used ones.

| Task | Command |
| --- | --- |
| Install dev env | `uv sync --group dev` |
| Run all tests | `uv run pytest` |
| Tests with coverage gate (CI parity) | `uv run pytest --cov=openrtc --cov-report=xml --cov-fail-under=80` |
| Run a single test | `uv run pytest tests/test_pool.py::test_name -xvs` |
| Run integration tests only | `uv run pytest -m integration` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` |
| Type check | `uv run mypy src/` |
| Smoke-check discovery without LiveKit | `make dev` (or `uv run openrtc list ./examples/agents --default-stt … --default-llm … --default-tts …`) |
| Build wheel | `uv build` |

`mypy src/` and `ruff check` both run in CI (`.github/workflows/lint.yml`). The coverage gate is enforced at 80%.

Python 3.11+ is required; 3.10 will fail because the LiveKit Silero / turn-detector plugins pull `onnxruntime`, which has no 3.10 wheels.

## High-level architecture

OpenRTC is a thin layer on top of `livekit-agents` that lets one worker process host many agent classes, with shared prewarm (Silero VAD, turn detector) loaded once instead of once per worker. User agents stay as standard `livekit.agents.Agent` subclasses; OpenRTC never introduces a custom base class.

### The single load-bearing module: `src/openrtc/pool.py`

Almost everything that matters happens here:

- `AgentPool` — the public facade. Wraps `livekit.agents.AgentServer` and registers a single universal entrypoint with it.
- `AgentConfig` / `AgentDiscoveryConfig` / `agent_config` decorator — registration data + per-file discovery metadata.
- `_prewarm_worker` — the function passed to `AgentServer` as `prewarm_fnc`. Loads shared resources (VAD, turn detector) once into `proc.userdata`. Adding new shared resources means adding them here.
- `_run_universal_session` — the `entrypoint_fnc`. For every incoming job, it runs the routing chain, instantiates the chosen `Agent` subclass, builds an `AgentSession` from cached defaults plus per-agent overrides, pulls the prewarmed VAD from `proc.userdata`, and starts the session.
- Routing chain (priority order, implemented around `pool.py:781-853`):
  1. `ctx.job.metadata["agent"]`
  2. `ctx.job.metadata["demo"]`
  3. `ctx.room.metadata["agent"]`
  4. `ctx.room.metadata["demo"]`
  5. Room name prefix match (e.g. `restaurant-call-123` → `restaurant`)
  6. First registered agent (fallback)

  A metadata value naming an unregistered agent raises `ValueError`. Do not silently fall back.

- `AgentPool.run()` — calls `cli.run_app(self._server)`, handing control to LiveKit's CLI parser.

### Provider passthrough contract

`ProviderValue = str | object` (see `provider_types.py`). Anything passed to `stt=`, `llm=`, `tts=` on `pool.add()` or as pool defaults is forwarded to `AgentSession` unchanged: instantiated plugin objects (`openai.STT(...)`) work, and so do shorthand strings (`"openai/gpt-4o-mini-transcribe"`) — the LiveKit runtime resolves the strings at session construction time. OpenRTC does not interpret or validate them.

### Spawn-safe configuration

Worker processes can be spawned (LiveKit's default on macOS), so anything captured by `entrypoint_fnc` must survive serialization across the process boundary. Provider configs live in the registration data, not in closures, and are reconstructed from a serialization-safe representation in the worker. When adding new fields to `AgentConfig` or related dataclasses, keep them serialization-safe (no live sockets, no open files, no `lambda`/local closures). Live plugin instances are also supported but rely on the underlying objects being well-behaved across spawn.

### Test conftest shim

`tests/conftest.py` contains a hand-maintained stub of `livekit.agents` that activates **only when `livekit.agents` cannot be imported**. With `uv sync --group dev`, the real wheel is installed and the shim is bypassed. Two consequences:

- When you upgrade the `livekit-agents` pin (`~=1.4` today) or use a new symbol from `livekit.agents` in `src/`, run the suite locally against the real SDK and extend the shim if a CI environment without LiveKit would break.
- If imports behave oddly in tests, check whether the shim path is active — the symbol you expect from upstream may not be implemented in the stub.

### CLI architecture

`cli.py` is the lazy entrypoint that prints a friendly message if the `cli` extra isn't installed, then defers to `cli_app.py`. Subcommands (`list`, `start`, `dev`, `console`, `connect`, `download-files`, `tui`) mirror the LiveKit Agents CLI shape; OpenRTC-only flags (`--agents-dir`, `--metrics-jsonl`, etc.) are stripped before handoff. The handoff itself happens in `cli_livekit.py`, which rewrites `sys.argv` and applies env overrides before calling `pool.run()`.

The Textual sidecar (`tui_app.py`) is gated behind the `tui` extra and tails the JSONL metrics stream produced by `cli_reporter.py`.

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

`docs/audit-2026-05-02.md` is a deep audit of OpenRTC's current architecture against the goal of running 50+ sessions per worker (vs livekit-agents' ~1 session per process at ~3 GB each). The key finding: `pool.py:284` (`self._server = AgentServer()`) currently inherits livekit-agents' process-per-job model unchanged. The recommended next step (Option B in the doc) is a custom `JobExecutor` that runs jobs as `asyncio.Task`s in the main loop instead of spawning a subprocess per job. Read the audit before proposing architectural changes in this direction.
