---
name: openrtc-python
description: >-
  Write and wire up LiveKit voice agents using OpenRTC so that multiple agents
  run inside a single shared worker process. Use when the user asks to create a
  voice agent, add a new agent to an existing pool, configure STT/LLM/TTS
  providers, set up agent routing, or run multiple LiveKit agents together with
  OpenRTC.
license: MIT
compatibility: Requires Python 3.11+ and uv (or pip). Requires the openrtc package.
metadata:
  author: mahimailabs
  version: "1.0"
---

## Directory layout

```
project/
├── agents/
│   ├── restaurant.py      # one Agent subclass per file
│   ├── dental.py
│   └── support.py
├── main.py                # AgentPool entrypoint
├── pyproject.toml
└── .env                   # LIVEKIT_URL, provider API keys
```

- One `Agent` subclass per file. `discover()` picks the first local subclass.
- No `__init__.py` needed. Files starting with `_` are skipped.
- Filename stem becomes the agent name unless `@agent_config(name=...)` overrides it.

## Step 1 — Create an agent file

```python
# agents/restaurant.py
from livekit.agents import Agent, RunContext, function_tool
from openrtc import agent_config


@agent_config(name="restaurant", greeting="Welcome to reservations.")
class RestaurantAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="You help callers book restaurant reservations."
        )

    @function_tool
    async def check_availability(
        self, context: RunContext, party_size: int, time: str
    ) -> str:
        """Check whether a table is available."""
        return f"A table for {party_size} at {time} looks good."
```

`@agent_config(...)` is optional. All fields fall back to pool defaults when
omitted. The decorator accepts: `name`, `stt`, `llm`, `tts`, `greeting`.

## Step 2 — Create the entrypoint

```python
# main.py
from pathlib import Path
from dotenv import load_dotenv
from openrtc import AgentPool

load_dotenv()

pool = AgentPool(
    default_stt="deepgram/nova-3:multi",
    default_llm="openai/gpt-4.1-mini",
    default_tts="cartesia/sonic-3",
)
pool.discover(Path("./agents"))
pool.run()
```

Use `discover()` for the standard flat-directory layout. For explicit control
(subdirectories, conditional registration), use `pool.add()` instead — read
[references/api.md](references/api.md) for the `add()` signature.

For advanced provider config (custom parameters, non-default endpoints), pass
provider objects instead of strings — read
[references/providers.md](references/providers.md) when configuring non-default
provider settings.

## Step 3 — Set environment variables

```bash
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
```

Add only the provider keys your agents use. Read
[references/providers.md](references/providers.md) for the full mapping of
provider names to environment variable names.

## Step 4 — Validate and run

```bash
# Validate discovery works (no server needed)
openrtc list --agents-dir ./agents \
  --default-stt deepgram/nova-3:multi \
  --default-llm openai/gpt-4.1-mini \
  --default-tts cartesia/sonic-3
```

If an agent is missing from the output: check the file is in `agents/`, has
exactly one `Agent` subclass at module scope, and the filename doesn't start
with `_`. Fix and re-run `openrtc list` until all agents appear.

```bash
# Development mode (auto-reload) — set LIVEKIT_* env vars first
openrtc dev --agents-dir ./agents

# Production mode
openrtc start --agents-dir ./agents

# Same LiveKit subcommands as python agent.py: console, connect, download-files
# openrtc console --agents-dir ./agents
# openrtc connect --agents-dir ./agents --room my-room

# Optional: JSON Lines metrics + sidecar TUI (pip install 'openrtc[cli,tui]')
# openrtc dev --agents-dir ./agents --metrics-jsonl ./openrtc-metrics.jsonl
# openrtc tui

# Or run the entrypoint directly
python main.py dev
```

## Routing

When a call arrives, `AgentPool` resolves the agent in this priority:

1. `ctx.job.metadata["agent"]`
2. `ctx.job.metadata["demo"]`
3. `ctx.room.metadata["agent"]`
4. `ctx.room.metadata["demo"]`
5. Room name prefix match (`restaurant-call-123` → `restaurant`)
6. First registered agent (fallback)

Unknown metadata names raise `ValueError` — no silent fallback.

## Gotchas

- **Agent classes must be defined at module scope.** Classes inside functions
  cannot be pickled for spawned workers — you'll get a serialization error at
  startup.
- **`discover()` does not recurse into subdirectories.** It only scans `*.py`
  in the given directory. For nested agent layouts, use `pool.add()`.
- **`pool.run()` delegates to `livekit.agents.cli.run_app()`.** The first CLI
  argument must be `dev` or `start` (e.g. `python main.py dev`). Without it,
  the process exits immediately with a usage error.
- **`openrtc dev|start|…` sets up discovery then calls the same LiveKit CLI.**
  OpenRTC-only flags (`--agents-dir`, `--dashboard`, `--metrics-jsonl`, …) are
  stripped from `sys.argv` before LiveKit parses arguments—do not expect LiveKit
  to understand them.
- **Provider objects must be pickleable.** OpenRTC has built-in serialization
  for `livekit.plugins.openai` STT, TTS, and LLM. Other providers: use string
  identifiers or ensure the object is natively pickleable.
- **`session_kwargs` direct kwargs win.** When the same key appears in both
  `session_kwargs={}` and as a direct keyword to `add()`, the direct keyword
  takes precedence.
- **`greeting` fires after `ctx.connect()`** via `session.generate_reply()`.
  If `None`, no greeting is generated and the agent waits silently for the
  caller to speak.

## Adding a new agent — checklist

- [ ] Create `agents/<name>.py` with one `Agent` subclass at module scope
- [ ] Optionally add `@agent_config(name="...", greeting="...")` for overrides
- [ ] Add `@function_tool` methods for any callable tools
- [ ] Run `openrtc list --agents-dir ./agents` — verify the agent appears
- [ ] If missing, check filename, class scope, and `_` prefix — fix and re-run
- [ ] Test with `openrtc dev --agents-dir ./agents`
