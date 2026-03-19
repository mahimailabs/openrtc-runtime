# OpenRTC

OpenRTC is a Python package for running multiple LiveKit voice agents in a
single worker process with shared prewarmed runtime dependencies.

## Why OpenRTC?

- **Multi-agent routing** from a single worker process.
- **Shared prewarm** for VAD and turn detection models.
- **Explicit registration** through a small programmatic API.
- **LiveKit-native runtime** built on `livekit-agents`.

## What you can do today

The current package is intentionally small and focused:

- register one or more LiveKit `Agent` subclasses with `AgentPool`
- select an agent using room or job metadata
- share runtime dependencies across sessions in one worker process
- start a LiveKit worker using the registered pool

## Read the docs

- [Getting Started](./getting-started)
- [Architecture](./concepts/architecture)
- [AgentPool API](./api/pool)
- [Examples](./examples)
- [CLI](./cli)
- [GitHub Pages deployment](./deployment/github-pages)
