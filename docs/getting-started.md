---
title: Getting Started
description: Install OpenRTC and run your first multi-agent LiveKit worker.
icon: rocket
---

# Getting Started

<Note>
Already using livekit-agents? Start with
[Coming from livekit-agents](/coming-from-livekit-agents) for the before/after:
what you delete, what you keep, and what you gain. This page is the from-scratch
install.
</Note>

## Requirements

OpenRTC requires Python **`>=3.11,<3.14`** and depends on
`livekit-agents[openai,silero,turn-detector]~=1.5`. **3.10 is not supported**
(LiveKit's Silero / turn-detector stack pulls `onnxruntime`, which does not ship
wheels for CPython 3.10 in current releases). See the repository's
`CONTRIBUTING.md` for `uv` workflows.

## Install

The voice framework is an opt-in extra: `import openrtc` pulls neither livekit
nor pipecat. The livekit backend is the default, so install `openrtc[livekit]`
to run it (add `cli` for the CLI):

<Tabs>
  <Tab title="uv (recommended)">
    ```bash
    uv add "openrtc[livekit]"
    ```

    Include the CLI extras (`openrtc list`, `openrtc start`, `openrtc dev`, `openrtc console`, ...):

    ```bash
    uv add "openrtc[livekit,cli]"
    ```
  </Tab>
  <Tab title="pip">
    ```bash
    pip install "openrtc[livekit]"
    ```

    With CLI extras:

    ```bash
    pip install 'openrtc[livekit,cli]'
    ```
  </Tab>
  <Tab title="Editable (contributors)">
    ```bash
    python -m pip install -e .
    ```

    Contributor environments typically use `uv sync --group dev`, which includes Typer and Rich so `openrtc` runs without extra flags.
  </Tab>
</Tabs>

The base package includes the LiveKit Silero and turn-detector plugins used by OpenRTC's shared prewarm path. The wheel includes **PEP 561** `py.typed` for type checkers.

See [CLI](./cli) for subcommands, output modes (`--plain`, `--json`, `--resources`), the JSONL metrics stream (`--metrics-jsonl`), and optional-dependency behavior.

## CLI quick path

With `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` set, the minimal
worker invocation is:

```bash
openrtc dev ./agents
```

Use `openrtc start` for production-style runs. See [CLI](./cli) for `console`,
`connect`, `download-files`, and the JSONL metrics stream (`--metrics-jsonl`,
which you can tail with `tail -f openrtc-metrics.jsonl` or pipe through `jq`).

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
    llm=openai.responses.LLM(model="gpt-4.1-mini"),
    tts=openai.TTS(model="gpt-4o-mini-tts"),
)

pool.run()
```

## Routing between agents

`AgentPool` resolves an agent in this order:

| Priority | Source | Example |
|---|---|---|
| 1 | `ctx.job.metadata["agent"]` | `{"agent": "support"}` in job metadata |
| 2 | `ctx.job.metadata["demo"]` | Legacy fallback key, same format |
| 3 | `ctx.job.room.metadata["agent"]` | Room metadata from dispatch (read pre-connect) |
| 4 | `ctx.job.room.metadata["demo"]` | Legacy fallback key, same format |
| 5 | Room name prefix | `support-call-123` routes to `support` |
| 6 | First registered agent | Default fallback |

Pass metadata as a JSON object with an `"agent"` key:

```json
{"agent": "support"}
```

<Note>
If metadata references an agent name that is not registered, OpenRTC raises a `ValueError` with a clear message instead of silently falling back.
</Note>

See [Routing](/concepts/routing) for the full priority chain and error behavior.

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
