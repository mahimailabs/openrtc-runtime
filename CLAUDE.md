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
| Docs site (preview) | `npm ci --prefix web/docs && npm run dev --prefix web/docs` |
| Docs check (CI parity) | `python3 docs/_check_docs.py` and `npm run build --prefix web/docs` |

`mypy src/` (in `strict = true` mode), `ruff check` and `ruff format --check` run in CI (`.github/workflows/lint.yml`). The combined line + branch coverage gate is enforced at 99% (project sits around 99.4%).

Python 3.11+ is required; 3.10 will fail because the LiveKit Silero / turn-detector plugins pull `onnxruntime`, which has no 3.10 wheels.

## High-level architecture

OpenRTC is a thin layer on top of `livekit-agents` that lets one worker process host many agent classes, with shared prewarm (Silero VAD, turn detector) loaded once instead of once per worker. User agents stay as standard `livekit.agents.Agent` subclasses; OpenRTC never introduces a custom base class. `import openrtc` does not import livekit: it is the opt-in `openrtc[livekit]` extra. Pipecat support was removed; OpenRTC targets livekit-agents only.

### Package layout (`src/openrtc/`)

- `core/pool.py`: `AgentPool`, the public facade (`add`, `discover`, `remove`, `run`, drain, observers, tenant/backpressure options). It builds a backend, wires routing + request filters, and owns the runtime state.
- `core/wiring.py`: the universal session entrypoint (`run_session`, `build_session`). Per job: resolve the agent, instantiate it, build an `AgentSession` from pool defaults + per-agent + per-tenant overrides, attach the prewarmed VAD from `proc.userdata`, start.
- `core/backend.py`: the `Backend` protocol the pool drives. `backends/registry.py` resolves `AgentPool(backend="livekit")` lazily (the only backend); the implementation lives in `backends/livekit/`.
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

`runtime/coroutine_runtime.py` imports private livekit-agents surfaces (`ipc.job_executor`, `job._JobContextVar`, `ipc.proc_pool`). The pin (`>=1.5,<1.9`) is deliberately tight; an unsupported version fails import with a message pointing to `isolation="process"`. `.github/workflows/canary.yml` runs the suite against the latest livekit-agents release. When bumping the pin: relock with `uv lock --upgrade-package livekit-agents`, run the full suite against the real SDK, and update the range in `pyproject.toml`, `README.md`, `docs/index.mdx`, `docs/how-it-works.mdx`, `AGENTS.md` and the error message in `coroutine_runtime.py`.

### Provider passthrough contract

`ProviderValue = str | object` (see `utils/types.py`). Anything passed to `stt=`, `llm=`, `tts=` on `pool.add()` or as pool defaults is forwarded to `AgentSession` unchanged: instantiated plugin objects (`openai.STT(...)`) work, and so do shorthand strings (`"openai/gpt-4o-mini-transcribe"`) — the LiveKit runtime resolves the strings at session construction time. OpenRTC does not interpret or validate them.

### Spawn-safe configuration

Worker processes can be spawned (LiveKit's default on macOS, and always in `isolation="process"`), so anything captured by the entrypoint must survive serialization across the process boundary. `core/serialization.py` captures `livekit.plugins.*` provider instances as `_ProviderRef(module, qualname, kwargs-from-_opts)` and rebuilds them in the worker. This relies on a plugin's `_opts` mirroring its constructor kwargs; when upstream drifts (e.g. openai STT 1.8 stores `language=` as `_opts.languages`), patch `_extract_provider_kwargs`. When adding new fields to `AgentConfig` or related dataclasses, keep them serialization-safe (no live sockets, no open files, no `lambda`/local closures).

### Test conftest shim

`tests/conftest.py` contains a hand-maintained stub of `livekit.agents` that activates **only when `livekit.agents` cannot be imported**. With `uv sync --group dev`, the real wheel is installed and the shim is bypassed. Two consequences:

- When you upgrade the `livekit-agents` pin or use a new symbol from `livekit.agents` in `src/`, run the suite locally against the real SDK and extend the shim if a CI environment without LiveKit would break. Tests that fake `RunningJobInfo` with `SimpleNamespace` must carry any field upstream now reads (e.g. `job.enable_redaction` since 1.8).
- If imports behave oddly in tests, check whether the shim path is active — the symbol you expect from upstream may not be implemented in the stub.

### CLI architecture

`cli/__init__.py` re-exports `main` and `app`. `cli/entry_cli.py` is the lazy entrypoint that prints a friendly message if the `cli` extra isn't installed, then defers to `cli/main_cli.py` (the Typer app). Worker subcommands (`start`, `dev`, `console`, `connect`, `download-files`) mirror the LiveKit Agents CLI shape; OpenRTC-only commands are `list`, `logs`, and `top` (live session inspector, `openrtc[top]` adds psutil host vitals). OpenRTC-only flags (`--agents-dir`, `--metrics-jsonl`, etc.) are stripped before handoff in `cli/livekit_cli.py`, which rewrites `sys.argv` and applies env overrides before calling `pool.run()`. `cli/top_cli.py`, `cli/dashboard_cli.py`, `cli/reporter_cli.py` hold the rest; shared helpers live in `cli/base_cli.py`.

### Docs site

The web lives in `web/`: `web/docs/` is docs.openrtc.tech, an Astro static site on Cloudflare Workers (`web/docs/wrangler.jsonc`), the same pattern as voice-prices' prices.mahimai.ca; `web/shared/` holds the theme (tokens, base styles, the mark) shared with the landing page. It renders five files from `docs/` and nothing else: `index.mdx`, `how-it-works.mdx`, `cli.mdx`, `benchmark.mdx`, `changelog.md`. The page list lives in `web/docs/src/lib/site.ts`; `docs/_check_docs.py` fails CI on a missing page, an orphan file, a broken internal link, or an em dash. Keep it to few pages, each complete. `docs/design/` and `docs/audit-2026-05-02.md` are internal notes, not published. Product truth for design work is `PRODUCT.md`; the visual system is `DESIGN.md`.

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

## Working conventions (AI-assisted development)

- **Branches:** `feat/<topic>` or `fix/<topic>`. Never a `claude/` prefix.
- **Before every push:** `make ci` (ruff check, ruff format --check, mypy --strict, pytest with the 99% coverage gate) must pass locally.
- **LiveKit facts come from the docs, not memory.** The project ships the LiveKit Docs MCP server (`.mcp.json`) and LiveKit's agent skills (`.claude/skills/`, start with `reading-livekit-docs`). Check the changelog before touching code that hooks livekit-agents internals.
- **Docs and UI:** use the `impeccable` skill for any docs-site or frontend work. The house style is the sibling projects: mahimai.ca (`PRODUCT.md`/`DESIGN.md`: charcoal, one lavender accent, Space Grotesk + JetBrains Mono, no em dashes) and voice-prices' docs (lead with the problem, measured numbers, tables over prose, say what is not covered and why, generated sections fenced by markers).
- **Keep it minimal.** The `ponytail` skill is installed: reuse what exists, stdlib before dependencies, shortest diff that fixes the root cause.
- **Performance claims need a measurement.** Compare memory with PSS, not RSS (forked job processes share pages; RSS double counts them), against vanilla livekit-agents on the same machine.
- **Secrets:** never read or commit `.env` files (denied in `.claude/settings.json`); pass LiveKit credentials as environment variables.
- **Project AI config lives in the repo:** `.claude/settings.json` (permissions, hooks: `uv sync` on cloud session start, `ruff format` after each Python edit), `.claude/skills/` + `skills-lock.json` (update with `npx skills update`), `.mcp.json`. Personal overrides go in the gitignored `.claude/settings.local.json`.

## Strategic context

OpenRTC's original goal was density: many sessions per worker instead of livekit-agents' one process per job. `docs/audit-2026-05-02.md` motivated coroutine isolation (`runtime/coroutine_runtime.py`, the default). A head-to-head benchmark on livekit-agents 1.8.3 (full voice pipeline, 2 pinned cores, PSS) changed the picture:

- Vanilla 1.8 forks jobs from a preloaded forkserver, so a job costs ~63 MB PSS, not ~3 GB. OpenRTC coroutine mode costs ~22 MB per session, with the same ~1.2 GB idle baseline.
- CPU, not memory, is the binding constraint on typical hardware. One OpenRTC worker is one Python process (~1 core of Python), used ~25% more CPU per call, and held fewer calls than vanilla process mode on the same cores.
- OpenRTC's load signal is sessions/max and ignores CPU, so under CPU overload it keeps accepting calls and degrades (unbounded memory growth, stalled sessions) where vanilla sheds load.

Do not reintroduce "50+ sessions per worker" or "~3 GB per process" claims without new measurements. Design notes for the livekit internals coroutine mode hooks live in `docs/design/` (pinned to 1.5.0 source; re-derive when the pin moves).
