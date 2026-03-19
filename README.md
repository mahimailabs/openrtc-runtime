# OpenRTC

OpenRTC is a Python framework for running multiple LiveKit voice agents in a
single worker process with shared prewarmed models.

It is designed for the common case where you want to run several different
voice agents on a small VPS without paying the memory cost of one full
LiveKit worker per agent.

## Why OpenRTC exists

A standard `livekit-agents` worker process loads shared runtime assets such as
Python, Silero VAD, and turn-detection models. If you run ten agents as ten
separate workers, you pay that base memory cost ten times.

OpenRTC keeps your agent classes completely standard and only centralizes the
worker boilerplate:

- shared prewarm for VAD and turn detection
- metadata-based dispatch to the correct agent
- per-agent `AgentSession` construction inside one worker

Your agent code still subclasses `livekit.agents.Agent` directly. If you stop
using OpenRTC later, your agent classes still work as normal LiveKit agents.

## What OpenRTC wraps

OpenRTC intentionally wraps only the worker orchestration layer:

1. `AgentServer()` setup and prewarm
2. a universal `@server.rtc_session()` entrypoint
3. per-call `AgentSession()` creation with the right providers

OpenRTC does **not** replace:

- `livekit.agents.Agent`
- `@function_tool`
- `RunContext`
- `on_enter`, `on_exit`, `llm_node`, `stt_node`, `tts_node`
- standard LiveKit deployment patterns

## Memory comparison

| Deployment model | Shared runtime loads | Approximate memory shape |
| --- | --- | --- |
| 10 separate LiveKit workers | 10x | ~500 MB × 10 |
| 1 OpenRTC pool with 10 agents | 1x shared + per-call session cost | ~500 MB shared + active-call overhead |

The exact numbers depend on your providers, concurrency, and environment, but
OpenRTC is built to reduce duplicate worker overhead.

## Installation

Install OpenRTC with the common runtime dependencies required for shared
prewarm:

```bash
pip install openrtc[common]
```

If you are developing locally, the repository uses `uv` for environment and
command management.

### Required environment variables

OpenRTC uses the same environment variables as a standard LiveKit worker:

```bash
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
```

Add only the provider keys needed for the models you actually use:

```bash
DEEPGRAM_API_KEY=...
OPENAI_API_KEY=...
CARTESIA_API_KEY=...
GROQ_API_KEY=...
ELEVENLABS_API_KEY=...
```

## Quick start: register agents directly with `add()`

Use `AgentPool.add(...)` when you want the most explicit setup.

```python
from livekit.agents import Agent
from openrtc import AgentPool


class RestaurantAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="You help callers make restaurant bookings.")


class DentalAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="You help callers manage dental appointments.")


pool = AgentPool()
pool.add(
    "restaurant",
    RestaurantAgent,
    stt="deepgram/nova-3:multi",
    llm="openai/gpt-4.1-mini",
    tts="cartesia/sonic-3",
    greeting="Welcome to reservations.",
)
pool.add(
    "dental",
    DentalAgent,
    stt="deepgram/nova-3:multi",
    llm="openai/gpt-4.1-mini",
    tts="cartesia/sonic-3",
)
pool.run()
```

## Quick start: discover agent files with `@agent_config(...)`

Use discovery when you want one agent module per file. OpenRTC will import each
module, find a local `Agent` subclass, and optionally read overrides from the
`@agent_config(...)` decorator.

```python
from pathlib import Path

from openrtc import AgentPool

pool = AgentPool(
    default_stt="deepgram/nova-3:multi",
    default_llm="openai/gpt-4.1-mini",
    default_tts="cartesia/sonic-3",
)
pool.discover(Path("./agents"))
pool.run()
```

Example agent file:

```python
from livekit.agents import Agent
from openrtc import agent_config


@agent_config(name="restaurant", greeting="Welcome to reservations.")
class RestaurantAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="You help callers make restaurant bookings.")
```

### Discovery defaults

A discovered module does not need to provide any OpenRTC metadata. If the agent
class has no `@agent_config(...)` decorator:

- the agent name defaults to the Python filename stem
- STT/LLM/TTS/greeting fall back to `AgentPool(...)` defaults

That keeps discovery straightforward while still allowing per-agent overrides
when needed.

## Routing behavior

For each incoming room, `AgentPool` resolves the agent in this order:

1. `ctx.job.metadata["agent"]`
2. `ctx.job.metadata["demo"]`
3. `ctx.room.metadata["agent"]`
4. `ctx.room.metadata["demo"]`
5. room name prefix match, such as `restaurant-call-123`
6. the first registered agent

This lets one worker process host several agents while staying compatible with
standard LiveKit job and room metadata.

## Greetings and session options

OpenRTC can play a greeting after `ctx.connect()` and pass extra options into
`AgentSession(...)`.

```python
pool.add(
    "restaurant",
    RestaurantAgent,
    greeting="Welcome to reservations.",
    session_kwargs={"allow_interruptions": False},
    max_tool_steps=4,
    preemptive_generation=True,
)
```

Direct keyword arguments take precedence over the same keys inside
`session_kwargs`.

## Provider model strings

OpenRTC passes provider strings through to `livekit-agents`, so the common case
stays simple.

### STT examples

- `deepgram/nova-3`
- `deepgram/nova-3:multi`
- `assemblyai/...`
- `google/...`

### LLM examples

- `openai/gpt-4.1-mini`
- `openai/gpt-4.1`
- `groq/llama-4-scout`
- `anthropic/claude-sonnet-4-20250514`

### TTS examples

- `cartesia/sonic-3`
- `elevenlabs/...`
- `openai/tts-1`

If you need advanced provider configuration, you can still pass provider objects
instead of strings.

## CLI usage

OpenRTC includes a small CLI for agent discovery.

### List discovered agents

```bash
openrtc list \
  --agents-dir ./agents \
  --default-stt deepgram/nova-3:multi \
  --default-llm openai/gpt-4.1-mini \
  --default-tts cartesia/sonic-3
```

### Run in production mode

```bash
openrtc start --agents-dir ./agents
```

### Run in development mode

```bash
openrtc dev --agents-dir ./agents
```

## Project structure

```text
src/openrtc/
├── __init__.py
├── cli.py
└── pool.py
```

- `pool.py` contains the core `AgentPool` implementation
- `cli.py` provides agent discovery and worker startup commands
- `__init__.py` exposes the public package API

## Migration from legacy `AGENT_*` module globals

Older prototypes used module-level constants such as `AGENT_NAME` and
`AGENT_STT`. OpenRTC now standardizes on `@agent_config(...)` plus
`AgentPool(...)` defaults.

Before:

```python
AGENT_NAME = "restaurant"
AGENT_STT = "deepgram/nova-3:multi"
AGENT_LLM = "openai/gpt-4.1-mini"
AGENT_TTS = "cartesia/sonic-3"
AGENT_GREETING = "Welcome to reservations."
```

After:

```python
from openrtc import agent_config


@agent_config(
    name="restaurant",
    greeting="Welcome to reservations.",
)
class RestaurantAgent(Agent):
    ...
```

Move shared provider settings into the pool:

```python
pool = AgentPool(
    default_stt="deepgram/nova-3:multi",
    default_llm="openai/gpt-4.1-mini",
    default_tts="cartesia/sonic-3",
)
```

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md)
before opening a pull request.

## License

MIT. See [LICENSE](LICENSE).
