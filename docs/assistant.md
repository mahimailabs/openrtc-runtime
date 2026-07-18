---
title: OpenRTC AI Assistant
description: Context for the Mintlify AI assistant.
---

OpenRTC is a Python library that lets a single worker process host multiple LiveKit voice agents with shared prewarm.

**Key facts:**

- Install: `pip install openrtc` or `uv add openrtc`. CLI extras: `pip install 'openrtc[cli]'`.
- Requires Python 3.11 or newer (3.10 is not supported).
- The main class is `AgentPool`. Register agents with `pool.add(name, AgentClass)` and start with `pool.run()`.
- Agents are standard `livekit.agents.Agent` subclasses. No OpenRTC base class is required.
- Routing priority: job metadata `agent` key, then room metadata `agent` key, then room name prefix, then first registered agent.
- `isolation="coroutine"` (default) runs all sessions as asyncio tasks in one process. `isolation="process"` spawns one subprocess per session (legacy behavior).
- Shared prewarm loads Silero VAD and the multilingual turn detector once per worker.
- CLI commands: `openrtc dev`, `openrtc start`, `openrtc list`, `openrtc console`, `openrtc connect`.
- Docs live in the `docs/` directory. Source is at https://github.com/mahimailabs/openrtc-runtime.
