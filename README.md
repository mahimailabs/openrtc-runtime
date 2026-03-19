# OpenRTC

OpenRTC is a Python framework for running multiple LiveKit voice agents in a
single worker process with shared prewarmed models.

## Shared provider defaults

When multiple agents use the same STT, LLM, or TTS providers, configure those
once on `AgentPool` and let discovered agent modules override only the values
that differ.

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

The CLI also accepts shared defaults for discovered agents:

```bash
openrtc list \
  --agents-dir ./examples/agents \
  --default-stt deepgram/nova-3:multi \
  --default-llm openai/gpt-4.1-mini \
  --default-tts cartesia/sonic-3
```
