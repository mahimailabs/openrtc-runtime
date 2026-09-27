# OpenRTC examples: try it live

`agents/` holds standard `livekit.agents.Agent` subclasses, so you can confirm
OpenRTC works end to end. The quickest live check uses OpenAI, so you only need an
`OPENAI_API_KEY`.

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
[routing rules](https://docs.openrtc.tech/how-it-works/#routing) (metadata, then room name prefix, then the first agent).

## What this proves

Registration, routing, prewarm, and the session lifecycle over a real (or
console) call.

Everything up to accepting the transport connection is also covered by the
automated suite (`make ci`); these examples are the live confirmation.
