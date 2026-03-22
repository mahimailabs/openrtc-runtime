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
  - title: Multi-agent routing
    details: Dispatch the right Agent implementation from a single worker using room or job metadata.
  - title: Shared prewarm
    details: Load VAD, turn detection, and other heavy dependencies once for every session in the pool.
  - title: LiveKit-native runtime
    details: Built on livekit-agents with familiar dev, start, console, and connect-style workflows.
  - title: CLI and observability
    details: Optional openrtc CLI with JSON output, resource hints, JSONL metrics, and a Textual sidecar TUI.
---

## Read the docs

- [Getting Started](./getting-started)
- [Architecture](./concepts/architecture)
- [AgentPool API](./api/pool)
- [Examples](./examples)
- [CLI](./cli)
- [GitHub Pages deployment](./deployment/github-pages)
