# CLI

OpenRTC ships a console script named `openrtc` (Typer + Rich) for discovery-based
workflows. The implementation lives in `openrtc.cli` / `openrtc.cli_app`; the
programmatic entry is `typer.main.get_command(app).main(...)` (Click’s
`Command.main`), not the test-only `CliRunner`.

## Installation

The **library** ( `AgentPool`, discovery, routing ) installs with:

```bash
pip install openrtc
```

The **CLI stack** (Typer, Rich) is declared as the optional extra `cli`:

```bash
pip install 'openrtc[cli]'
```

If Typer/Rich are not importable, `openrtc.cli:main` exits with `1` and prints
an install hint. In practice, `livekit-agents` may pull Typer transitively, so
the hint path is mainly covered by tests and edge environments—see
`tests/test_cli_optional_extra_integration.py` in the repo.

## Commands

### `openrtc list`

Discovers agent modules and prints each agent’s resolved settings.

- **Default:** Rich **table** (human-friendly).
- **`--plain`** — Stable, line-oriented text (no ANSI/table borders); good for
  grep and CI.
- **`--json`** — Stable JSON. Top-level fields include `schema_version` (bump
  when the shape changes) and `command: "list"`. Combine with `--resources` for
  `resource_summary`.
- **`--plain` and `--json` together** are rejected (non-zero exit).

```bash
openrtc list --agents-dir ./agents
openrtc list --agents-dir ./agents --plain
openrtc list --agents-dir ./agents --json
```

### `openrtc start`

Discovers agent modules and starts the LiveKit worker in production mode.

```bash
openrtc start --agents-dir ./agents
```

### `openrtc dev`

Discovers agent modules and starts the LiveKit worker in development mode.

```bash
openrtc dev --agents-dir ./agents
```

## Shared default options

Each command accepts these optional defaults, which are applied when a
discovered agent does not override them via `@agent_config(...)`:

- `--default-stt`
- `--default-llm`
- `--default-tts`
- `--default-greeting`

Example:

```bash
openrtc list \
  --agents-dir ./examples/agents \
  --default-stt openai/gpt-4o-mini-transcribe \
  --default-llm openai/gpt-4.1-mini \
  --default-tts openai/gpt-4o-mini-tts \
  --default-greeting "Hello from OpenRTC."
```

These defaults are passed through to `livekit-agents` as raw strings. If you
need provider-native plugin objects, configure them in Python with `AgentPool`
instead of through the CLI flags.

## `list --resources` (footprint)

With **`--resources`**, `list` adds:

- **Per-agent** on-disk size of the discovered `.py` module when the path is
  known (see `AgentConfig.source_path` in the API docs).
- **Summary** — total source bytes and a **best-effort** process memory metric
  from `openrtc.resources` (Linux: current VmRSS; macOS: peak `ru_maxrss`, not
  live RSS—see `resident_set.description` in `--json` output).

Use this for **rough** local comparisons (single worker vs many images). For
production, rely on host or container metrics.

```bash
openrtc list --agents-dir ./examples/agents --resources
openrtc list --agents-dir ./examples/agents --resources --json
```

## Notes

- `--agents-dir` is required for every command.
- `list` returns a non-zero exit code when no discoverable agents are found.
- `start` and `dev` both discover agents before handing off to the underlying
  LiveKit worker runtime.
