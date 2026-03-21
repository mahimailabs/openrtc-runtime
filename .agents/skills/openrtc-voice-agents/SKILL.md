---
name: openrtc-voice-agents
description: >-
  Write and wire up LiveKit voice agents using OpenRTC so that multiple agents
  run inside a single shared worker process. Use when the user asks to create a
  voice agent, add a new agent to an existing pool, configure STT/LLM/TTS
  providers, set up agent routing, or run multiple LiveKit agents together with
  OpenRTC.
license: MIT
compatibility: Requires Python 3.10+ and uv (or pip). Requires the openrtc package.
metadata:
  author: mahimailabs
  version: "1.0"
---

# Writing LiveKit voice agents with OpenRTC

OpenRTC lets you run multiple LiveKit voice agents in **one worker process**
with shared prewarmed models (Silero VAD, turn detection). Each agent is a
standard `livekit.agents.Agent` subclass — nothing OpenRTC-specific leaks into
the agent class itself.

## When to use this skill

- The user asks to create, add, or modify a voice agent
- The user wants to run several agents in a single worker
- The user mentions OpenRTC, AgentPool, or agent discovery
- The user needs help with STT / LLM / TTS provider configuration

## Directory structure convention

All agents live in a flat `agents/` directory at the project root, one Python
file per agent. The entrypoint `main.py` sits next to it.

```
project/
├── agents/
│   ├── restaurant.py      # one agent per file
│   ├── dental.py
│   └── support.py
├── main.py                # AgentPool entrypoint
├── pyproject.toml
└── .env                   # LIVEKIT_URL, API keys
```

Rules:
- **One `Agent` subclass per file.** `discover()` picks up the first local
  `Agent` subclass it finds.
- **No `__init__.py` needed** in `agents/`. Files starting with `_` are
  skipped.
- The filename stem becomes the agent name unless `@agent_config(name=...)`
  overrides it.

## Step 1 — Install OpenRTC

```bash
pip install openrtc
```

This also installs `livekit-agents[silero,turn-detector]`.

## Step 2 — Write an agent file

Each agent file defines a class that subclasses `livekit.agents.Agent`.
Optionally use the `@agent_config(...)` decorator to set the agent name,
provider overrides, and greeting.

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

### `@agent_config(...)` fields

| Field | Default | Purpose |
|---|---|---|
| `name` | filename stem | Unique name for routing |
| `stt` | pool default | STT provider override |
| `llm` | pool default | LLM provider override |
| `tts` | pool default | TTS provider override |
| `greeting` | pool default | Spoken after `ctx.connect()` |

If the decorator is omitted entirely, the agent uses the filename as its name
and inherits all pool defaults.

## Step 3 — Write the entrypoint

The entrypoint creates an `AgentPool`, discovers agents from the directory,
and calls `pool.run()`.

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

### Using provider objects instead of strings

For advanced provider configuration, pass provider instances:

```python
from livekit.plugins import openai

pool = AgentPool(
    default_stt=openai.STT(model="gpt-4o-mini-transcribe"),
    default_llm=openai.responses.LLM(model="gpt-4.1-mini"),
    default_tts=openai.TTS(model="gpt-4o-mini-tts"),
)
```

### Using `add()` instead of `discover()`

When you need explicit control (e.g. agents in subdirectories, conditional
registration), use `pool.add()`:

```python
from agents.restaurant import RestaurantAgent
from agents.dental import DentalAgent

pool = AgentPool()
pool.add("restaurant", RestaurantAgent,
         stt="deepgram/nova-3:multi",
         llm="openai/gpt-4.1-mini",
         tts="cartesia/sonic-3",
         greeting="Welcome to reservations.")
pool.add("dental", DentalAgent,
         stt="deepgram/nova-3:multi",
         llm="openai/gpt-4.1-mini",
         tts="cartesia/sonic-3")
pool.run()
```

## Step 4 — Set environment variables

```bash
# Required — LiveKit server connection
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret

# Provider keys — only the ones your agents actually use
DEEPGRAM_API_KEY=...
OPENAI_API_KEY=...
CARTESIA_API_KEY=...
```

## Step 5 — Run

```bash
# Development mode (auto-reload)
openrtc dev --agents-dir ./agents

# Production mode
openrtc start --agents-dir ./agents

# List discovered agents (no server needed)
openrtc list --agents-dir ./agents \
  --default-stt deepgram/nova-3:multi \
  --default-llm openai/gpt-4.1-mini \
  --default-tts cartesia/sonic-3
```

Or run the entrypoint directly:

```bash
python main.py dev
```

## Routing behavior

When a call arrives, `AgentPool` resolves the agent in this order:

1. `ctx.job.metadata["agent"]`
2. `ctx.job.metadata["demo"]`
3. `ctx.room.metadata["agent"]`
4. `ctx.room.metadata["demo"]`
5. Room name prefix match (`restaurant-call-123` → `restaurant`)
6. First registered agent (fallback)

If metadata references an unknown name, a `ValueError` is raised — it does
**not** silently fall back.

## Provider string reference

See [references/providers.md](references/providers.md) for the full list of
supported provider/model strings.

## Gotchas

- **Agent classes must be defined at module scope.** Local classes (inside
  functions) cannot be pickled for spawned workers.
- **`discover()` only scans `*.py` in the given directory** — it does not
  recurse into subdirectories. Use `add()` for nested layouts.
- **The `@agent_config` decorator does not make the class OpenRTC-specific.**
  It only attaches metadata. The class is still a standard `livekit.agents.Agent`.
- **`pool.run()` calls `livekit.agents.cli.run_app()`** — pass `dev` or
  `start` as the first CLI argument (e.g. `python main.py dev`).
- **Provider objects must be pickleable** for multi-process workers. Use
  provider strings or supported LiveKit plugin types.
- **Session kwargs like `allow_interruptions`, `min_endpointing_delay`** are
  passed via `session_kwargs={}` or as direct keyword arguments to `add()`.
  Direct kwargs take precedence over `session_kwargs`.
- **`greeting` fires after `ctx.connect()`** — if omitted or `None`, no
  greeting is generated.

## Adding a new agent — checklist

- [ ] Create `agents/<agent_name>.py` with one `Agent` subclass
- [ ] Add `@agent_config(name="...", greeting="...")` if overriding defaults
- [ ] Add `@function_tool` methods for any tools the agent needs
- [ ] Run `openrtc list --agents-dir ./agents` to verify discovery
- [ ] Test with `openrtc dev --agents-dir ./agents`
