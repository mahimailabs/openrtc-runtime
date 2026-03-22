# Architecture

OpenRTC keeps the public API intentionally narrow.

## Core building blocks

### `AgentConfig`

`AgentConfig` stores the registration-time settings for a LiveKit agent:

- unique `name`
- `agent_cls` subclass
- optional `stt`, `llm`, and `tts` values (`ProviderValue | None`: provider ID
  strings or plugin instances)
- optional `greeting` generated after `ctx.connect()`
- optional `session_kwargs` forwarded to `AgentSession`
- optional `source_path` when the module file is known (e.g. after discovery), for
  tooling and footprint estimates—not used for routing

### `AgentDiscoveryConfig`

`AgentDiscoveryConfig` stores optional discovery metadata attached by
`@agent_config(...)`:

- optional explicit `name`
- optional `stt`, `llm`, and `tts` overrides
- optional `greeting` override

### `AgentPool`

`AgentPool` owns a single LiveKit `AgentServer`, a registry of named agents, and
one universal session handler.

At startup it configures shared prewarm behavior so worker-level runtime assets
are loaded once and reused across sessions.

## Session lifecycle

When a room is assigned to the worker:

1. OpenRTC resolves the target agent from job metadata, room metadata, room-name
   prefix matching, or the first registered agent.
2. It creates an `AgentSession` using the selected agent configuration.
3. Prewarmed VAD and turn detection models are injected from `proc.userdata`.
4. The resolved agent instance is started for the room.
5. OpenRTC connects the room context.
6. If a greeting is configured, it generates the greeting after connect.

## Shared runtime dependencies

During prewarm, OpenRTC loads:

- `livekit.plugins.silero`
- `livekit.plugins.turn_detector.multilingual.MultilingualModel`

These plugins are expected to be available from the package installation.
If they are missing at runtime, OpenRTC raises a `RuntimeError` with install
instructions.

## Why this shape?

This design keeps the package easy to reason about:

- routing logic is explicit
- worker-scoped dependencies are loaded once
- discovery metadata is opt-in and typed
- agent registration stays stable and readable
- the public API remains small enough for contributors to extend safely
