# Getting Started

## Requirements

OpenRTC requires Python **`>=3.11,<3.14`** and depends on
`livekit-agents[openai,silero,turn-detector]~=1.4`. **3.10 is not supported**
(LiveKit’s Silero / turn-detector stack pulls `onnxruntime`, which does not ship
wheels for CPython 3.10 in current releases). See the repository’s
`CONTRIBUTING.md` for `uv` workflows.

## Install

```bash
pip install openrtc
```

The base package includes the LiveKit Silero and turn-detector plugins used by
OpenRTC's shared prewarm path. The wheel includes **PEP 561** `py.typed` for type
checkers.

With **uv**:

```bash
uv add openrtc
uv add "openrtc[cli,tui]"
```

Install the **Typer/Rich CLI** (`openrtc list`, `openrtc start`, `openrtc dev`,
`openrtc console`, …) with:

```bash
pip install 'openrtc[cli]'
```

Install the optional **Textual sidecar** for `openrtc tui --watch` with:

```bash
pip install 'openrtc[cli,tui]'
```

See [CLI](./cli) for subcommands, output modes (`--plain`, `--json`, `--resources`),
the JSONL metrics stream (`--metrics-jsonl`), and optional-dependency behavior.

If you are contributing locally, install the package in editable mode:

```bash
python -m pip install -e .
```

Contributor environments typically use `uv sync --group dev`, which includes
Typer, Rich, and Textual so `openrtc` and `openrtc tui` run without extra flags.

## CLI quick path

With `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` set, the minimal
worker invocation is:

```bash
openrtc dev --agents-dir ./agents
```

Use `openrtc start` for production-style runs. See [CLI](./cli) for `console`,
`connect`, `download-files`, metrics files, and the sidecar TUI.

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
