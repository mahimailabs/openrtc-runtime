# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: engineers who self-host LiveKit Agents workers (usually the one person who owns the voice stack at a small team), running several agent classes and debugging them on real calls. They arrive from GitHub or PyPI with a working livekit-agents agent and want to know, in minutes, whether OpenRTC changes how they write agents (it does not) and what it gives them to operate the worker.

Stage: very early, close to zero users. The docs are small on purpose.

## Product Purpose

OpenRTC is the operations layer for self-hosted LiveKit Agents. One `AgentPool` hosts every agent class in one worker, and adds what livekit-agents leaves to you: routing a call to the right agent, hot reload that keeps the live conversation, a live session inspector (`openrtc top`), per-tenant limits and a circuit breaker, and graceful drain for deploys. Success is an engineer running their existing agents through one pool, then using `openrtc dev` and `openrtc top` daily.

## Positioning

Your `Agent` subclasses stay standard livekit-agents code: no base class, no wrapper around `@function_tool` or the node hooks. OpenRTC changes how you run agents, not how you write them.

It is not a density product. A measured head-to-head against livekit-agents 1.8.3 showed coroutine mode uses about 3x less memory per call (~22 MB vs ~64 MB PSS) at about the same CPU on uvloop (the default), but one worker is one Python process, so it does not raise the calls one machine can serve.

## Operating Context

- Install: `pip install "openrtc[livekit]"` (Python 3.11 to 3.13, livekit-agents `>=1.5,<1.9`).
- Daily loop: `openrtc dev ./agents` with hot reload, `openrtc top` beside it.
- Production: `openrtc start ./agents`, one worker per core, SIGTERM or `pool.begin_drain()` on deploy.
- Web: `web/docs/` (Astro, static) renders `docs/*.mdx` to `docs.openrtc.tech`; `web/landing/` is the marketing page at `openrtc.tech`; `web/shared/` holds the theme both use. Both deploy to Cloudflare Workers. Five pages: Why OpenRTC, How it works, CLI, Benchmark, Changelog.

## Capabilities and Constraints

- Isolation: `coroutine` (default, every session an `asyncio.Task` in one process) or `process` (livekit's process per job).
- Coroutine mode hooks private livekit-agents internals, hence the tight version pin.
- Per-agent and per-tenant caps and the tenant circuit breaker need coroutine mode.
- `openrtc top` needs a coroutine-mode worker on the same host.
- Pipecat support was removed. LiveKit only.

## Brand Commitments

- Name: OpenRTC. Built by Mahimai (mahimai.ca), alongside Voice Prices and VoiceGateway.
- Voice: short, declarative, technically specific. No marketing tone, no em dashes, no "on steroids".
- Every performance number is measured, with its method and machine stated. Never reintroduce "50+ sessions per worker" or "~3 GB per process".
- Say what is not covered and why.

## Evidence on Hand

- Head-to-head benchmark, livekit-agents 1.8.3, full voice pipeline, 2 pinned cores, PSS (README "Throughput and density").
- Loop-lag load signal run: 24 calls, one every 3 s, 2 cores.
- Throughput harness `tests/benchmarks/throughput.py`, density gate `tests/benchmarks/density.py`.
- `openrtc top` rendered with sample sessions (demo tenants acme, globex, initech): `web/docs/public/openrtc-top.svg`.
- Absent, do not fabricate: users, testimonials, production deployments, company logos.

## Product Principles

1. Your agent code does not change.
2. Measured, not claimed: every number has a method.
3. Say the limits next to the feature.
4. Few pages, each complete.
