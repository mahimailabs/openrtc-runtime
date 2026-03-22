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

Optional runtime visibility:

- **`--dashboard`** — Show a live Rich dashboard with worker RSS, active
  sessions, failures, and an estimated “separate workers vs shared worker”
  savings comparison.
- **`--dashboard-refresh 1.0`** — Control how often the dashboard refreshes.
- **`--metrics-json-file ./openrtc-runtime.json`** — Write a live JSON snapshot
  for automation and host-side tooling.

### `openrtc dev`

Discovers agent modules and starts the LiveKit worker in development mode.

```bash
openrtc dev --agents-dir ./agents
openrtc dev --agents-dir ./examples/agents --dashboard
openrtc dev --agents-dir ./examples/agents --dashboard --metrics-json-file ./runtime.json
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
- **Savings estimate** — a transparent estimate of the memory saved by one
  shared worker versus one worker per registered agent. The estimate is based on
  the current shared-worker baseline and is meant as an explanatory comparison,
  not an orchestrator-level billing metric.

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
- The live dashboard and `--metrics-json-file` use runtime snapshots from the
  running shared worker, unlike `list --resources`, which reports only on the
  short-lived CLI discovery process.

## Prove the shared-worker value locally

One practical workflow is:

1. Discover your agents:

   ```bash
   openrtc list --agents-dir ./examples/agents --resources
   ```

2. Start one shared worker with the dashboard enabled:

   ```bash
   openrtc dev \
     --agents-dir ./examples/agents \
     --dashboard \
     --metrics-json-file ./runtime.json
   ```

3. Watch the dashboard for:
   - **Worker RSS** — current shared-worker memory
   - **Active sessions** — how much load the single worker is handling
   - **Estimated saved** — the gap between one shared worker and the “one worker
     per agent” baseline
   - **Per-agent sessions** — which agents are actively consuming capacity

4. Use `runtime.json` for automation, shell scripts, or container-side scraping.

For production capacity planning, compare these OpenRTC runtime snapshots with
host or container telemetry from your deployment platform.
