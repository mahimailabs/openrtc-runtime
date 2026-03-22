# CLI

OpenRTC ships a console script named `openrtc` (Typer + Rich) for discovery-based
workflows. The Typer application and `main()` live in `openrtc.cli_app` (with
helpers in `cli_livekit`, `cli_dashboard`, `cli_reporter`, `cli_types`, and
`cli_params`). The lazy entrypoint and missing-extra hints are in `openrtc.cli`.
The programmatic entry is `typer.main.get_command(app).main(...)` (Click’s
`Command.main`), not the test-only `CliRunner`.

## Installation

The **library** (`AgentPool`, discovery, routing) installs with:

```bash
pip install openrtc
```

The **CLI stack** (Typer, Rich) is the optional extra `cli`:

```bash
pip install 'openrtc[cli]'
```

The **sidecar TUI** (Textual) is a separate optional extra:

```bash
pip install 'openrtc[cli,tui]'
```

If Typer/Rich are not importable, `openrtc.cli:main` exits with `1` and prints
an install hint. If Textual is missing, `openrtc tui` logs an error and exits
with `1`.

## Typical usage

1. Set the same variables as a standard LiveKit worker:

   ```bash
   export LIVEKIT_URL=ws://localhost:7880
   export LIVEKIT_API_KEY=devkey
   export LIVEKIT_API_SECRET=secret
   ```

2. Run a worker subcommand with an agents directory (plus any provider defaults
   your agents need). You can pass **`--agents-dir`** or use the **first
   positional argument** on ``start`` / ``dev`` / ``console``; a **second**
   positional sets ``--metrics-jsonl`` (unless you already passed that flag):

   ```bash
   openrtc dev ./agents
   openrtc dev ./agents ./openrtc-metrics.jsonl
   # equivalent to:
   openrtc dev --agents-dir ./agents --metrics-jsonl ./openrtc-metrics.jsonl
   openrtc start --agents-dir ./agents
   ```

Defaults are conservative: **no** Rich dashboard unless you pass `--dashboard`,
and **no** metrics files unless you pass `--metrics-json-file` or
`--metrics-jsonl`. Refresh intervals default to **1 second** where applicable.

Subcommands mirror the LiveKit Agents CLI (`python agent.py dev`, `start`,
`console`, `connect`, `download-files`). OpenRTC adds **`--agents-dir`** for
discovery, then delegates to `livekit.agents.cli.run_app`. OpenRTC-only flags are
stripped from `sys.argv` before that handoff so LiveKit does not see options
like `--agents-dir`.

## Connection overrides

You can override `LIVEKIT_*` per invocation:

- `--url`
- `--api-key`
- `--api-secret`
- `--log-level` (also `LIVEKIT_LOG_LEVEL`)

These appear under **Connection** or **Advanced** in `--help` depending on the
flag.

## Commands

Across **list**, **connect**, **download-files**, **start** / **dev** / **console**,
and **tui**, you can often pass paths **positionally** instead of `--agents-dir`,
`--metrics-jsonl`, or `--watch` (see each command below). The first non-flag
token after the subcommand is rewritten before parsing; use `--agents-dir` /
`--watch` when you need a different argument order.

### `openrtc list`

Discovers agent modules and prints each agent’s resolved settings.

- **Default:** Rich **table** (human-friendly).
- **`--plain`** — Stable, line-oriented text (no ANSI/table borders); good for
  grep and CI.
- **`--json`** — Stable JSON. Top-level fields include `schema_version` (bump
  when the shape changes) and `command: "list"`. Combine with `--resources` for
  `resource_summary`.
- **`--plain` and `--json` together** are rejected (non-zero exit).
- **`--resources`** — Footprint and memory hints (grouped under **Advanced** in
  `--help`).

```bash
openrtc list ./agents
openrtc list --agents-dir ./agents --plain
openrtc list ./agents --json
```

### `openrtc start`

Production-style worker (same role as `python agent.py start`).

```bash
openrtc start ./agents
```

### `openrtc dev`

Development worker with reload (same role as `python agent.py dev`).

```bash
openrtc dev ./agents
```

### `openrtc console`

Local console session (same role as `python agent.py console`).

```bash
openrtc console ./agents
```

### `openrtc connect`

Connect the worker to an existing room (LiveKit `connect`). Requires
`--room`.

```bash
openrtc connect ./agents --room my-room
```

### `openrtc download-files`

Download plugin assets (LiveKit `download-files`). Only needs the agents
directory (for a valid worker entrypoint) plus connection settings—**no**
`--default-stt` / `--default-llm` / `--default-tts` / `--default-greeting`.

```bash
openrtc download-files ./agents
```

### `openrtc tui`

Sidecar Textual UI that tails a **JSON Lines** metrics file written by the
worker (`--metrics-jsonl`). Requires `openrtc[tui]`.

With no flags, the TUI tails **`./openrtc-metrics.jsonl`** in the current working
directory. Pass **`--watch PATH`** or a **positional path** to use another file
(it must match `--metrics-jsonl` on the worker).

```bash
# Terminal 1
openrtc dev ./agents ./openrtc-metrics.jsonl

# Terminal 2 (same default file as above)
openrtc tui

# Or pass the file positionally:
# openrtc tui ./openrtc-metrics.jsonl

# Equivalent explicit form:
# openrtc tui --watch ./openrtc-metrics.jsonl
```

Use **`--from-start`** (under **Advanced**) to read the file from the beginning
instead of tailing from EOF.

## Runtime visibility and automation

- **`--dashboard`** — Live Rich summary (RSS, sessions, routing, savings
  estimate). Off by default.
- **`--metrics-json-file PATH`** — Overwrites a JSON file each tick with the
  latest `PoolRuntimeSnapshot` (good for scripts). Grouped under **Advanced**.
- **`--metrics-jsonl PATH`** — Appends **versioned JSON Lines** (truncates when
  the worker starts). Each line is one record: `schema_version`, `kind`
  (`snapshot` or `event`), `seq`, `wall_time_unix`, `payload`. Snapshots match
  `PoolRuntimeSnapshot.to_dict()`; events carry session lifecycle hints
  (`session_started`, `session_finished`, `session_failed`). Intended for
  `openrtc tui` and other tail consumers.
- **`--dashboard-refresh`** — Interval in seconds for dashboard, metrics file,
  and JSONL when `--metrics-jsonl-interval` is not set (**Advanced**).
- **`--metrics-jsonl-interval`** — Override JSONL cadence only (**Advanced**).

## Shared default options (discovery)

Worker commands that load agents accept optional defaults applied when a
discovered agent does not override them via `@agent_config(...)`:

- `--default-stt`
- `--default-llm`
- `--default-tts`
- `--default-greeting` (**Advanced**)

Example:

```bash
openrtc list \
  --agents-dir ./examples/agents \
  --default-stt openai/gpt-4o-mini-transcribe \
  --default-llm openai/gpt-4.1-mini \
  --default-tts openai/gpt-4o-mini-tts
```

These defaults are passed through to `livekit-agents` as raw strings. For
provider-native plugin objects, configure them in Python with `AgentPool`
instead of through the CLI flags.

## `list --resources` (footprint)

With **`--resources`**, `list` adds:

- **Per-agent** on-disk size of the discovered `.py` module when the path is
  known (see `AgentConfig.source_path` in the API docs).
- **Summary** — total source bytes and a **best-effort** process memory metric
  from `openrtc.resources` (Linux: current VmRSS; macOS: peak `ru_maxrss`, not
  live RSS—see `resident_set.description` in `--json` output).
- **Savings estimate** — a transparent estimate of the memory saved by one
  shared worker versus one worker per registered agent.

```bash
openrtc list --agents-dir ./examples/agents --resources
openrtc list --agents-dir ./examples/agents --resources --json
```

## Notes

- `--agents-dir` is required for every command.
- `list` returns a non-zero exit code when no discoverable agents are found.
- Worker commands discover agents before handing off to the LiveKit CLI.
- The live dashboard, `--metrics-json-file`, and `--metrics-jsonl` reflect the
  **running** shared worker, unlike `list --resources`, which reflects the
  short-lived CLI discovery process.

## Prove the shared-worker value locally

1. Discover your agents:

   ```bash
   openrtc list --agents-dir ./examples/agents --resources
   ```

2. Start one shared worker with the dashboard and/or metrics output:

   ```bash
   openrtc dev \
     --agents-dir ./examples/agents \
     --dashboard \
     --metrics-json-file ./runtime.json
   ```

   Or enable JSONL for a sidecar TUI:

   ```bash
   openrtc dev \
     --agents-dir ./examples/agents \
     --metrics-jsonl ./openrtc-metrics.jsonl
   ```

3. Watch the dashboard (or run `openrtc tui` in another terminal for the same
   default JSONL file) for
   worker RSS, active sessions, routing, and errors.

4. Use `runtime.json` or the JSONL stream for automation or scraping.

For production capacity planning, compare these snapshots with host or container
telemetry from your deployment platform.
