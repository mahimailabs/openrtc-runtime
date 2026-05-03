---
layout: home
outline: false

hero:
  name: OpenRTC
  text: Shared worker voice agents
  tagline: Register multiple LiveKit agents in one process, route by metadata, and prewarm models once.
  image:
    src: /banner.png
    alt: OpenRTC banner
  actions:
    - theme: brand
      text: Get started
      link: /getting-started
    - theme: alt
      text: CLI reference
      link: /cli

features:
  - title: Coroutine-mode worker (v0.1)
    details: Host 50+ concurrent sessions per process as asyncio tasks instead of paying one subprocess per session. Cooperative backpressure routed back to LiveKit dispatch via current_load.
  - title: Multi-agent routing
    details: Dispatch the right Agent implementation from a single worker using room or job metadata.
  - title: Shared prewarm
    details: Load VAD, turn detection, and other heavy dependencies once for every session in the pool.
  - title: LiveKit-native runtime
    details: Built on livekit-agents with familiar dev, start, console, and connect-style workflows. Drop into `isolation="process"` for v0.0.17 parity when you need hard process isolation.
  - title: CLI and observability
    details: Optional openrtc CLI with JSON output, resource hints, JSONL metrics, and a Textual sidecar TUI.
---

## Read the docs

- [Getting Started](./getting-started)
- [Architecture](./concepts/architecture)
- [AgentPool API](./api/pool)
- [Examples](./examples)
- [CLI](./cli)
- [Density benchmark (v0.1)](./benchmarks/density-v0.1)
- [Changelog](./changelog)
- [GitHub Pages deployment](./deployment/github-pages)
