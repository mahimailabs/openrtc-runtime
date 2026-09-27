<div align="center">

<a href="https://docs.openrtc.tech">
  <picture>
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/mahimailabs/openrtc-runtime/main/assets/cover-light.png" />
    <img src="https://raw.githubusercontent.com/mahimailabs/openrtc-runtime/main/assets/cover-dark.png" alt="OpenRTC: the ops layer for self-hosted LiveKit agents. An openrtc top table lists live calls with their agent, tenant, CPU and memory." width="100%" />
  </picture>
</a>

<p>
  <a href="https://pypi.org/project/openrtc/"><img src="https://raw.githubusercontent.com/mahimailabs/openrtc-runtime/main/assets/badges/pypi.svg" height="28" alt="PyPI"/></a>
  <img src="https://raw.githubusercontent.com/mahimailabs/openrtc-runtime/main/assets/badges/python.svg" height="28" alt="Python 3.11 to 3.13"/>
  <a href="https://docs.livekit.io/agents"><img src="https://raw.githubusercontent.com/mahimailabs/openrtc-runtime/main/assets/badges/livekit.svg" height="28" alt="LiveKit Agents 1.x"/></a>
  <a href="LICENSE"><img src="https://raw.githubusercontent.com/mahimailabs/openrtc-runtime/main/assets/badges/license.svg" height="28" alt="MIT License"/></a>
</p>

[**Docs**](https://docs.openrtc.tech) · [**Quick start**](#quick-start) · [**Benchmark**](https://docs.openrtc.tech/benchmark/) · [**Contributing**](#contributing)

</div>

```python
from openrtc import AgentPool
from my_agents import BookingAgent, SupportAgent, SalesAgent

pool = AgentPool()                 # one livekit-agents worker
pool.add("booking", BookingAgent)  # plain livekit.agents.Agent subclasses
pool.add("support", SupportAgent)
pool.add("sales", SalesAgent)
pool.run()                         # each call is routed to one of them
```

OpenRTC is the ops layer for self-hosted [LiveKit Agents](https://docs.livekit.io/agents): routing, hot reload, a live `openrtc top`, tenant caps and drain deploys, around the livekit-agents worker you already run.

## Why

- **The problem.** A livekit-agents worker has one entrypoint. With more than one agent you either write the dispatch yourself or run a worker per agent, and the tooling to operate it (which call is slow, which client is using the box, how to ship without cutting calls) is yours to build too.
- **What you get.** One pool that routes each call to the right agent, swaps live calls to your edited code, shows every call in `openrtc top`, caps each tenant, and drains on deploy.
- **What doesn't change.** Your agents stay standard `Agent` subclasses. No base class, and `@function_tool`, `RunContext`, `on_enter` and the `*_node` hooks are untouched. You delete the per-worker `entrypoint` and `AgentSession` wiring.

## Quick start

```bash
pip install "openrtc[livekit,cli]"
```

Python 3.11 to 3.13, livekit-agents `>=1.5,<1.9`. Set `LIVEKIT_URL`, `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` as for any LiveKit worker. Put one agent per file in a directory:

```python
# agents/booking.py
from livekit.agents import Agent
from openrtc import agent_config


@agent_config(name="booking", greeting="Welcome to reservations.")
class BookingAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="You help callers book a table.")
```

```bash
openrtc dev ./agents \
  --default-stt openai/gpt-4o-mini-transcribe \
  --default-llm openai/gpt-4.1-mini \
  --default-tts openai/gpt-4o-mini-tts

openrtc top          # in a second terminal: every live call
```

A room named `booking-call-1` now reaches `BookingAgent`. Edit the file during a call and the next turn runs your change. Prefer Python to a directory? `pool.add(...)` as above, then `python main.py dev`. [Full quick start](https://docs.openrtc.tech/).

Using a coding agent (Claude Code, Cursor, Codex)? `npx skills add mahimailabs/openrtc-runtime` gives it two skills: moving a livekit-agents project onto OpenRTC, and running it in production.

## What you get, and where it stops

| | What it does | Limits |
| --- | --- | --- |
| **Routing** | Each call goes to one agent by job metadata, room metadata, or room-name prefix. | An unknown agent name raises; routing never falls back silently. |
| **Hot reload** | `openrtc dev` moves live calls to your edited agent on their next turn. A bad save keeps the old code. | Coroutine mode only. |
| **`openrtc top`** | A live table of every call: agent, tenant, duration, CPU and memory; `slow` when a call blocks the others. | Same host. `slow` needs coroutine mode. |
| **Tenants** | Per-tenant providers and keys, per-tenant and per-agent caps, a circuit breaker for a failing tenant. | Not a sandbox. The breaker needs coroutine mode. |
| **Deploys** | `deployment_version`, `pool.begin_drain()` and audit events around livekit's drain. | Calls finish on the old version; none is moved. |
| **Two isolation modes** | `coroutine` (default): every call in one process. `process`: livekit's process per call. | Coroutine mode leans on livekit internals, hence the tight version pin. |

## Measured, not claimed

Against livekit-agents 1.8.3 on the same two cores, 8 calls: OpenRTC's default mode used about **22 MB per call against about 65 MB**, at **about the same CPU** (uvloop). CPU, not memory, is what limits calls per machine, so OpenRTC does not make one box serve more calls. [Benchmark](https://docs.openrtc.tech/benchmark/), with the harness to rerun it in [`benchmarks/headtohead`](benchmarks/headtohead).

**When not to use it:** you have one agent and don't need the ops tooling (plain livekit-agents is simpler), or you need hard per-call isolation and hot reload together (`isolation="process"` isolates each call but cannot hot reload).

## Docs

[Why OpenRTC](https://docs.openrtc.tech/) · [How it works](https://docs.openrtc.tech/how-it-works/) · [CLI](https://docs.openrtc.tech/cli/) · [Benchmark](https://docs.openrtc.tech/benchmark/) · [Changelog](https://docs.openrtc.tech/changelog/) · for AI coding tools: [`llms.txt`](https://docs.openrtc.tech/llms.txt)

## Contributing

OpenRTC is early, and a small change moves it. Three commands to a green run (`make ci` itself takes about a minute):

```bash
git clone https://github.com/mahimailabs/openrtc-runtime && cd openrtc-runtime
uv sync --group dev
make ci          # ruff, format, mypy --strict, pytest with the 99% coverage gate
```

**Where to start:** issues labelled [`good first issue`](https://github.com/mahimailabs/openrtc-runtime/labels/good%20first%20issue) are scoped, with the files to read and what done looks like. [`help wanted`](https://github.com/mahimailabs/openrtc-runtime/labels/help%20wanted) are bigger. Found a bug or have an idea? [Open an issue](https://github.com/mahimailabs/openrtc-runtime/issues/new/choose).

**How we work:** read [CONTRIBUTING.md](CONTRIBUTING.md). Performance claims need a measurement. AI-assisted PRs are welcome: the repo ships a [`CLAUDE.md`](CLAUDE.md) and agent skills ([`skills/`](skills) for adopters), and a PR is judged on the same `make ci` and review either way.

<a href="https://github.com/mahimailabs/openrtc-runtime/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=mahimailabs/openrtc-runtime&max=40&columns=10&anon=0" alt="Contributors" />
</a>

## License

[MIT](LICENSE). Built by [Mahimai Raja](https://mahimai.dev) at [Mahimai AI](https://mahimai.ca), in public, on [LiveKit Agents](https://github.com/livekit/agents).
