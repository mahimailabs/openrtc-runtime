# Getting Started

## Requirements

OpenRTC currently supports Python `>=3.10,<3.14` and depends on
`livekit-agents[openai,silero,turn-detector]~=1.4`.

## Install

```bash
pip install openrtc
```

The base package includes the LiveKit Silero and turn-detector plugins used by
OpenRTC's shared prewarm path.

If you are contributing locally, install the package in editable mode:

```bash
python -m pip install -e .
```

## Quick start

```python
from livekit.agents import Agent
from livekit.plugins import openai
from openrtc import AgentPool


class SupportAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="Help callers with support questions.")


pool = AgentPool()
pool.add(
    "support",
    SupportAgent,
    stt=openai.STT(model="gpt-4o-mini-transcribe"),
    llm=openai.responses.LLM(model="gpt-5-mini"),
    tts=openai.TTS(model="gpt-4o-mini-tts"),
)

pool.run()
```

## Routing between agents

`AgentPool` resolves an agent in this order:

1. `ctx.job.metadata["agent"]`
2. `ctx.job.metadata["demo"]`
3. `ctx.room.metadata["agent"]`
4. `ctx.room.metadata["demo"]`
5. room name prefix matching, such as `support-call-123`
6. the first registered agent

Use JSON metadata with an `agent` field, for example:

```json
{"agent": "support"}
```

If metadata references an unknown agent name, OpenRTC raises a `ValueError`
with a clear message instead of silently falling back.

## Discovery-based setup

If you prefer one agent module per file, use discovery with optional
`@agent_config(...)` metadata:

```python
from pathlib import Path

from livekit.plugins import openai
from openrtc import AgentPool

pool = AgentPool(
    default_stt=openai.STT(model="gpt-4o-mini-transcribe"),
    default_llm=openai.responses.LLM(model="gpt-4.1-mini"),
    default_tts=openai.TTS(model="gpt-4o-mini-tts"),
)
pool.discover(Path("./agents"))
pool.run()
```
