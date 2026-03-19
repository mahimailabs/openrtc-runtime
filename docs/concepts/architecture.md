# Architecture

OpenRTC keeps the public API intentionally narrow.

## Core building blocks

### `AgentConfig`

`AgentConfig` stores the registration-time settings for a LiveKit agent:

- unique `name`
- `agent_cls` subclass
- optional `stt`, `llm`, and `tts` providers
- optional `greeting` placeholder for future use

### `AgentPool`

`AgentPool` owns a single LiveKit `AgentServer`, a registry of named agents, and
one universal session handler.

At startup it configures shared prewarm behavior so worker-level runtime assets
are loaded once and reused across sessions.

## Session lifecycle

When a room is assigned to the worker:

1. OpenRTC resolves the target agent from job metadata, room metadata, or the
   first registered agent.
2. Create an `AgentSession` using the selected agent configuration.
3. Prewarmed VAD and turn detection models are injected from `proc.userdata`.
4. The resolved agent instance is then started and connected to the LiveKit job
   context.

## Shared runtime dependencies

During prewarm, OpenRTC loads:

- `livekit.plugins.silero`
- `livekit.plugins.turn_detector.multilingual.MultilingualModel`

If those plugins are unavailable, OpenRTC raises a `RuntimeError` explaining
that the package should be installed with the required extras.

## Why this shape?

This design keeps the package easy to reason about:

- routing logic is explicit
- worker-scoped dependencies are loaded once
- agent registration stays stable and readable
- the public API remains small enough for contributors to extend safely
