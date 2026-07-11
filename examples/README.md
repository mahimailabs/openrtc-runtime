# OpenRTC examples: try both backends live

Two runnable backends, so you can confirm OpenRTC works end to end.

- `agents/` are **livekit** agents (standard `livekit.agents.Agent` subclasses).
- `pipecat_agents/` are **pipecat** agents (pipeline builders marked with
  `@agent_config`).

The quickest live check for each is below. Both use OpenAI, so you only need an
`OPENAI_API_KEY` (the pipecat `echo` bot needs no key at all).

Install the project first (from the repo root):

```bash
uv sync --group dev
```

## livekit: talk to an agent in your terminal

`openrtc console` runs a local mic/speaker loop, so you do **not** need a LiveKit
server, just provider keys. This serves the example agents (`dental`,
`restaurant`) with OpenAI for STT / LLM / TTS:

```bash
export OPENAI_API_KEY=...
uv run openrtc console ./examples/agents \
  --default-stt "openai/gpt-4o-mini-transcribe" \
  --default-llm "openai/gpt-4.1-mini" \
  --default-tts "openai/gpt-4o-mini-tts"
```

Speak, and the agent responds in your terminal. To run against a real LiveKit
room instead, set `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` and use
`openrtc dev ./examples/agents` (same `--default-*` flags). Routing between the
discovered agents follows the precedence in the
[Routing](../docs/concepts/routing.md) doc (room name prefix, metadata, ...).

## pipecat: serve over WebRTC and talk in the browser

The pipecat backend serves over a transport via pipecat's runner. Install the
serving extra plus the WebRTC transport:

```bash
uv pip install "openrtc[pipecat-serve]" "pipecat-ai[webrtc]"
```

### 1. Zero-key smoke test (`echo`)

Confirms the whole path works (discover, route, serve, connect) without any API
keys: you hear yourself echoed back.

```bash
uv run openrtc serve ./examples/pipecat_agents
```

Open the runner's test client (it prints the URL, default
`http://localhost:7860`), start a call, and talk. Hearing your own voice means
OpenRTC discovered the builder, accepted the WebRTC connection, and ran the
pipeline.

### 2. Full voice assistant (`assistant`)

A real spoken assistant. Add the OpenAI + Silero extras and a key:

```bash
uv pip install "pipecat-ai[webrtc,openai,silero]"
export OPENAI_API_KEY=...
uv run openrtc serve ./examples/pipecat_agents
```

Both `echo` and `assistant` are discovered; the test client's `agent` field (sent
as `body["agent"]`) selects one. The assistant uses OpenRTC's **shared VAD**
(`view.prewarmed.vad`, loaded once per worker), so a start / end session signal is
emitted per call through OpenRTC's observability, exactly like the livekit backend.

## What this proves

- **livekit**: registration, routing, prewarm, and the session lifecycle over a
  real (or console) call.
- **pipecat**: the same operator layer (registration via `@agent_config`
  discovery, routing by `body["agent"]`, shared prewarm, observability) over a
  real WebRTC call, with the builder owning the transport and services.

Everything up to accepting the transport connection is also covered by the
automated suite (`make ci`); these examples are the live confirmation.
