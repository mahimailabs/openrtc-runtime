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

The dev group includes Typer and Rich so `uv run openrtc …` works without
`--extra cli`. End users install the CLI with `pip install 'openrtc[cli]'`.

If you prefer, you can also install the package and dev dependencies with pip,
but `uv` is the preferred workflow for contributors.

## Common development commands

### Run tests

```bash
uv run pytest
```

### Run Ruff lint checks

```bash
uv run ruff check
```

### Format code

```bash
uv run ruff format
```

## Project architecture

Keep these responsibilities in mind when contributing:

- `src/openrtc/pool.py` contains the core pooling, discovery, routing, and
  session-construction logic.
- `src/openrtc/cli.py` is the console entrypoint; `src/openrtc/cli_app.py`
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

If you are unsure where a change belongs, start by reading `src/openrtc/pool.py`
and open a small, incremental PR.
