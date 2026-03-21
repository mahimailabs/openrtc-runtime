# CLI

OpenRTC exposes a console script named `openrtc` for discovery-based workflows.

## Commands

### `openrtc list`

Discovers agent modules and prints the resolved registration settings for each
agent.

```bash
openrtc list --agents-dir ./agents
```

### `openrtc start`

Discovers agent modules and starts the LiveKit worker in production mode.

```bash
openrtc start --agents-dir ./agents
```

### `openrtc dev`

Discovers agent modules and starts the LiveKit worker in development mode.

```bash
openrtc dev --agents-dir ./agents
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

## Notes

- `--agents-dir` is required for every command.
- `list` returns a non-zero exit code when no discoverable agents are found.
- `start` and `dev` both discover agents before handing off to the underlying
  LiveKit worker runtime.
