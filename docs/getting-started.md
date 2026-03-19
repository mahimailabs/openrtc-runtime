# Getting Started

## Requirements

OpenRTC currently supports Python `>=3.10,<3.14` and depends on
`livekit-agents[silero,turn-detector]~=1.4`.

## Install

```bash
pip install openrtc
```

If you are contributing locally, install the package in editable mode:

```bash
python -m pip install -e .
```

## Quick start

```python
from livekit.agents import Agent
from openrtc import AgentPool


class SupportAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="Help callers with support questions.")


pool = AgentPool()
pool.add(
    "support",
    SupportAgent,
    stt="deepgram/nova-3:multi",
    llm="openai/gpt-5-mini",
    tts="cartesia/sonic-3",
)

pool.run()
```

## Routing between agents

`AgentPool` resolves an agent in this order:

1. `ctx.job.metadata`
2. `ctx.room.metadata`
3. the first registered agent

Use JSON metadata with an `agent` field, for example:

```json
{"agent": "support"}
```

If metadata references an unknown agent name, OpenRTC raises a `ValueError`
with a clear message instead of silently falling back.
