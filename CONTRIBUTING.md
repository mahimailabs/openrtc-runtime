# Contributing to OpenRTC

Thanks for contributing to OpenRTC.

OpenRTC is a small Python framework for running multiple standard LiveKit voice
agents inside a single worker process with shared runtime assets. The project
prioritizes clarity, correctness, backward compatibility, and contributor
readability.

## Local setup

This repository uses `uv` for local development.

```bash
uv sync --group dev
```

The dev group includes Typer, Rich, and Textual so `uv run openrtc …` and
`uv run openrtc tui …` work without extra install flags. End users install the
CLI with `pip install 'openrtc[cli]'` and the sidecar TUI with
`pip install 'openrtc[tui]'` (or `openrtc[cli,tui]` together).

If you prefer, you can also install the package and dev dependencies with pip,
but `uv` is the preferred workflow for contributors.

**Python version:** OpenRTC requires **3.11+** (transitive `onnxruntime` from
LiveKit plugins does not support 3.10).

## Common development commands

### Run tests

```bash
uv run pytest
```

With `uv sync --group dev`, the real `livekit-agents` package is installed, so
pytest uses the upstream SDK—not the fallback shim in `tests/conftest.py`. That
shim only loads when `livekit.agents` is missing (minimal or broken installs). It
is hand-maintained to match APIs OpenRTC uses; when you upgrade the
`livekit-agents` pin in `pyproject.toml` or add new LiveKit imports in `src/`,
re-run the full suite locally and update `conftest.py` if anything still relies
on the stub.

### Run Ruff lint checks

```bash
uv run ruff check
```

### Format code

```bash
uv run ruff format
```

### Type check (mypy)

CI runs `mypy src/` on pull requests (see `.github/workflows/lint.yml`). Locally:

```bash
uv run mypy src/
```

The wheel and sdist ship `src/openrtc/py.typed` (empty PEP 561 marker) so tools
like mypy and pyright treat `openrtc` as a typed dependency.

## Project architecture

Keep these responsibilities in mind when contributing:

- `src/openrtc/core/pool.py` contains the core pooling, discovery, routing, and
  session-construction logic.
- `src/openrtc/cli/` is the console entrypoint package; `src/openrtc/cli/commands.py`
  implements the Typer/Rich CLI (optional extra ``openrtc[cli]``; dev deps
  include it for local runs).
- `src/openrtc/__init__.py` defines the public package surface.
- `tests/` contains unit tests for pool behavior, discovery, routing, and CLI
  behavior.

## Contribution rules

When making changes, please preserve the core product constraints:

1. User agents should remain standard `livekit.agents.Agent` subclasses.
2. Do not introduce a custom OpenRTC agent base class.
3. Shared runtime assets such as VAD and turn detection must load in prewarm,
   not per call.
4. Keep the public API explicit and easy to understand.
5. Prefer additive, backward-compatible changes unless a breaking change is
   clearly intentional and documented.

## Testing expectations

- Add or update tests for any non-trivial change.
- Prefer unit tests for routing, validation, discovery, and configuration
  behavior.
- Mock LiveKit runtime boundaries where practical.
- Keep tests deterministic and readable.

## Documentation expectations

If your change affects public behavior, update the relevant docs:

- `README.md` for user-facing usage changes
- `docs/` (VitePress site: CLI, getting started, API, architecture)—keep these in
  sync when you change the public CLI, install extras, or `AgentPool` / discovery
  behavior
- docstrings in `src/openrtc/`
- examples, when new behavior should be demonstrated

## Pull requests

Good pull requests for OpenRTC are:

- focused
- well-typed
- covered by tests
- easy to review
- aligned with the existing architecture

If you are unsure where a change belongs, start by reading `src/openrtc/core/pool.py`
and open a small, incremental PR.
