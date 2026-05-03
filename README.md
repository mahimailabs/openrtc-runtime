<div align="center">
  <a href="https://github.com/mahimailabs/openrtc">
    <img src="assets/banner.png" alt="OpenRTC Banner" width="100%" />
  </a>
</div>

<br />

# openrtc-python

Run N LiveKit voice agents in one worker. Pay the model-load cost once.

*PyPI package name: [`openrtc`](https://pypi.org/project/openrtc/).*

<br />

<div align="center">
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python Version"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff"></a>
  <a href="https://pypi.org/project/openrtc/"><img src="https://img.shields.io/pypi/v/openrtc.svg" alt="PyPI version"></a>
  <a href="https://codecov.io/gh/mahimairaja/openrtc-python"><img src="https://codecov.io/gh/mahimairaja/openrtc-python/graph/badge.svg?token=W7VQ5FGSA9" alt="codecov"></a>
  <a href="https://github.com/mahimairaja/openrtc-python/actions/workflows/test.yml"><img src="https://github.com/mahimairaja/openrtc-python/actions/workflows/test.yml/badge.svg" alt="CI"></a>
</div>

<br />

<details>
  <summary><b>Table of Contents</b></summary>
  <ol>
    <li><a href="#the-problem">The problem</a></li>
    <li><a href="#what-openrtc-does">What openrtc does</a></li>
    <li><a href="#installation">Installation</a></li>
    <li><a href="#quick-start-explicit-registration-with-add">Quick start: explicit registration with add()</a></li>
    <li><a href="#quick-start-one-python-file-per-agent-with-discover">Quick start: one Python file per agent with discover()</a></li>
    <li><a href="#memory-before-and-after">Memory: before and after</a></li>
    <li><a href="#routing">Routing</a></li>
    <li><a href="#greetings-and-session-options">Greetings and session options</a></li>
    <li><a href="#provider-configuration">Provider configuration</a></li>
    <li><a href="#cli-and-tui">CLI and TUI</a></li>
    <li><a href="#public-api-at-a-glance">Public API at a glance</a></li>
    <li><a href="#project-structure">Project structure</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
  </ol>
</details>

<br />

## The problem

You already ship three voice agents with `livekit-agents`. Each agent is its own worker on the same VPS. Every worker process loads the same shared stack: Python runtime, Silero VAD, and the turn-detection model. You are not loading three different models. You are loading the same stack three times because the process boundary forces it. On a 1–2 GB instance, that shows up as duplicate resident set for every idle worker. You pay RAM for copies you do not need.

## What openrtc does

`openrtc` gives you one `AgentPool` in one worker: prewarm runs once, each incoming call still gets its own `AgentSession`, and you register multiple `Agent` subclasses on the pool so dispatch can pick one per session from metadata or fallbacks. This package does not replace your agent code. It does not sit between you and `livekit.agents.Agent`, `@function_tool`, `RunContext`, `on_enter`, `on_exit`, `llm_node`, `stt_node`, or `tts_node`. You keep your subclasses and tools as they are. You change how many workers you run, not how you write an agent.

## Installation

OpenRTC **requires Python 3.11 or newer**. The LiveKit Silero / turn-detector
plugins depend on `onnxruntime`, which does not ship supported wheels for
Python 3.10 in current releases—use 3.11+ to avoid install failures.

```bash
pip install openrtc
```

The base install pulls in `livekit-agents[openai,silero,turn-detector]` so shared prewarm has the plugins it expects. The package ships a **PEP 561** `py.typed` marker for downstream type checkers.

With **uv** (recommended in [CONTRIBUTING.md](CONTRIBUTING.md)):

```bash
uv add openrtc
uv add "openrtc[cli,tui]"
```

```bash
pip install 'openrtc[cli]'
```

Optional Textual sidecar for live metrics:

```bash
pip install 'openrtc[cli,tui]'
```

Set the same variables you use for any LiveKit worker:

```bash
export LIVEKIT_URL=ws://localhost:7880
export LIVEKIT_API_KEY=devkey
export LIVEKIT_API_SECRET=secret
```

For OpenAI-backed plugins, set `OPENAI_API_KEY` as you already do.

## Quick start: explicit registration with `add()`

Use this when you want every agent registered in one place with explicit names and providers.

```python
from livekit.agents import Agent
from livekit.plugins import openai
from openrtc import AgentPool


class RestaurantAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="You help callers make restaurant bookings.")


class DentalAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="You help callers manage dental appointments.")


pool = AgentPool()
pool.add(
    "restaurant",
    RestaurantAgent,
    stt=openai.STT(model="gpt-4o-mini-transcribe"),
    llm=openai.responses.LLM(model="gpt-4.1-mini"),
    tts=openai.TTS(model="gpt-4o-mini-tts"),
    greeting="Welcome to reservations.",
)
pool.add(
    "dental",
    DentalAgent,
    stt=openai.STT(model="gpt-4o-mini-transcribe"),
    llm=openai.responses.LLM(model="gpt-4.1-mini"),
    tts=openai.TTS(model="gpt-4o-mini-tts"),
)
pool.run()
```

## Quick start: one Python file per agent with `discover()`

Use this when you prefer one module per agent and optional `@agent_config(...)` on each class.

Create a directory (for example `agents/`) and add one `.py` file per agent. Then:

```python
from pathlib import Path

from livekit.plugins import openai
from openrtc import AgentPool

pool = AgentPool(
    default_stt=openai.STT(model="gpt-4o-mini-transcribe"),
    default_llm=openai.responses.LLM(model="gpt-4.1-mini"),
    default_tts=openai.TTS(model="gpt-4o-mini-tts"),
)
pool.discover(Path("./agents"))
pool.run()
```

Example file `agents/restaurant.py`:

```python
from livekit.agents import Agent
from openrtc import agent_config


@agent_config(name="restaurant", greeting="Welcome to reservations.")
class RestaurantAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="You help callers make restaurant bookings.")
```

If a module has no `@agent_config`, the agent name defaults to the filename stem. STT, LLM, TTS, and greeting fall back to the pool defaults.

Discovered agents work with `livekit dev` and spawn-based workers on macOS. For `add()`, define agent classes at module scope so worker reload can import them.

## Memory: before and after

Assume an illustrative **~400 MB** idle baseline per worker for the shared stack (VAD, turn detector, and similar). Your measured RSS will differ by provider, model, and OS.

| | Before openrtc | After openrtc |
| --- | --- | --- |
| Three workers, same stack | about **3 × 400 MB ≈ 1.2 GB** idle baseline (three loads) | — |
| One worker, three registered agents | — | about **one × 400 MB** idle baseline (one load) plus per-session overhead |

Exact numbers depend on your providers, concurrency, and call patterns. The win is not loading that stack once per agent worker.

## Isolation modes

`AgentPool` accepts an `isolation` argument that picks how each session
runs inside the worker. The v0.1 default is `"coroutine"`; pass
`isolation="process"` to opt back into the v0.0.x behavior:

```python
pool = AgentPool(
    isolation="coroutine",          # default in v0.1
    max_concurrent_sessions=50,     # backpressure threshold (coroutine only)
)
```

| Aspect | `coroutine` (default) | `process` |
| --- | --- | --- |
| Sessions per worker | Many (one `asyncio.Task` per session, shared `JobProcess`) | One (each session is its own subprocess via `livekit-agents` `ProcPool`) |
| Prewarm cost (VAD, turn detector) | Paid once per worker | Paid once per session subprocess |
| Crash isolation | Cooperative: an unhandled exception in one session is logged and marked FAILED; siblings continue. After `consecutive_failure_limit` (default 5) the worker calls `aclose()` so the platform restarts it. | Hard: each subprocess crashes independently; siblings unaffected. |
| Per-session memory cap | Not enforced (asyncio shares one process) | Enforced via `livekit-agents` `job_memory_limit_mb` |
| Backpressure | `current_load() = active / max_concurrent_sessions` reported as worker load; LiveKit dispatch routes elsewhere at `>= load_threshold` | `livekit-agents` default load math (CPU-based) |
| When to pick | High density on a single host; cost-sensitive deployments. | Regulatory/compliance requires hard process isolation; per-session memory caps required. |

### Density (50 concurrent sessions, one worker)

From the v0.1 stub-workload benchmark (`tests/benchmarks/density.py`,
results recorded at `docs/benchmarks/density-v0.1.md`):

| Sessions | Successes | Peak RSS  | Elapsed | Within 4 GB budget |
| --- | --- | --- | --- | --- |
|  50 | 50  | 367 MB  | 1.04 s | ✓ |
| 100 | 100 | 617 MB  | 1.10 s | ✓ |
| 200 | 200 | 1073 MB | 1.19 s | ✓ |
| 500 | 500 | 1370 MB | 1.30 s | ✓ |

**Caveat:** the benchmark allocates ~5 MB per session to stress task
scheduling, not a realistic ~60 MB/session WebRTC + LLM footprint.
Validate against the §8.4 real-LiveKit integration test (which needs
`docker compose -f docker-compose.test.yml up -d` and `OPENAI_API_KEY`)
before quoting a per-session memory number to your operators.

## Routing

One process hosts several agent classes, so each session must resolve to a single registered name. `AgentPool` resolves the agent in this order:

1. `ctx.job.metadata["agent"]`
2. `ctx.job.metadata["demo"]`
3. `ctx.room.metadata["agent"]`
4. `ctx.room.metadata["demo"]`
5. room name prefix match, such as `restaurant-call-123`
6. the first registered agent

If metadata names an agent that is not registered, you get a `ValueError` instead of a silent fallback.

## Greetings and session options

You can pass a greeting and extra `AgentSession` options per registration.

```python
pool.add(
    "restaurant",
    RestaurantAgent,
    greeting="Welcome to reservations.",
    session_kwargs={"turn_handling": {"interruption": {"enabled": False}}},
    max_tool_steps=4,
    preemptive_generation=True,
)
```

Direct keyword arguments win over the same keys inside `session_kwargs`.

By default, OpenRTC sets explicit `turn_handling` with the multilingual turn detector and VAD-based interruption. To opt into adaptive interruption, pass `session_kwargs={"turn_handling": {"interruption": {"mode": "adaptive"}}}`.

## Provider configuration

Pass instantiated provider objects through to `livekit-agents` unchanged, for example:

- `openai.STT(model="gpt-4o-mini-transcribe")`
- `openai.responses.LLM(model="gpt-4.1-mini")`
- `openai.TTS(model="gpt-4o-mini-tts")`

If you pass strings such as `openai/gpt-4.1-mini`, OpenRTC leaves them as-is and the LiveKit runtime interprets them for your deployment.

## CLI and TUI

Install `openrtc[cli]` to get `openrtc` on your PATH. Subcommands follow the LiveKit Agents CLI shape (`dev`, `start`, `console`, `connect`, `download-files`), plus `list` and `tui`. For most commands you can pass the agents directory (or, for `tui`, the metrics JSONL file) as the first path argument instead of `--agents-dir` / `--watch`.

**List what discovery would register** (defaults are string passthroughs for `livekit-agents`, not constructed provider objects):

```bash
openrtc list \
  ./agents \
  --default-stt openai/gpt-4o-mini-transcribe \
  --default-llm openai/gpt-4.1-mini \
  --default-tts openai/gpt-4o-mini-tts
```

**Run a production worker** (after exporting `LIVEKIT_*`):

```bash
openrtc start ./agents
```

**Run a development worker**:

```bash
openrtc dev ./agents
```

Same as ``openrtc dev --agents-dir ./agents``. The metrics JSONL file is **optional**: add a second path only when you want JSONL output (same as ``--metrics-jsonl``), e.g. ``openrtc dev ./agents ./openrtc-metrics.jsonl`` for ``openrtc tui``.

Optional visibility: `--dashboard` prints a Rich summary in the terminal. `--metrics-json-file ./runtime.json` overwrites a JSON snapshot on each tick. Use that for scripts, dashboards, or CI. For JSON Lines plus a separate terminal UI, use `--metrics-jsonl ./openrtc-metrics.jsonl` on the worker and `openrtc tui` in another terminal (it tails `./openrtc-metrics.jsonl` by default; override with `--watch`) after `pip install 'openrtc[cli,tui]'`.

Stable machine output: `openrtc list --json` and `--plain`. Combine `--resources` when you want footprint hints. OpenRTC-only flags are stripped before the handoff to LiveKit’s CLI parser.

Full flag lists live in [docs/cli.md](docs/cli.md).

## Public API at a glance

Everything openrtc exposes publicly is listed here. Anything else is internal and not treated as stable.

- `AgentPool`
- `AgentConfig`
- `AgentDiscoveryConfig`
- `agent_config(...)`
- `ProviderValue` — type alias for STT/LLM/TTS slot values (provider ID strings or LiveKit plugin instances)

`AgentPool(...)` constructor (all keyword-only, all optional):

- `default_stt`, `default_llm`, `default_tts`, `default_greeting` — pool-wide defaults applied when `add()` / `discover()` doesn't override them.
- `isolation: "coroutine" | "process"` (v0.1) — worker isolation mode. Default `"coroutine"` runs every session as an `asyncio.Task` in one worker; `"process"` keeps the v0.0.x one-subprocess-per-session behavior.
- `max_concurrent_sessions: int` (v0.1) — coroutine-mode backpressure threshold. Default `50`. The worker reports `load >= 1.0` to LiveKit dispatch once this many sessions are in flight; ignored under `isolation="process"`.
- `consecutive_failure_limit: int` (v0.1) — coroutine-mode supervisor threshold. Default `5`. After this many non-`SUCCESS` session terminations the worker calls `aclose()` so the deployment platform can restart it; ignored under `isolation="process"`.

On `AgentPool`:

- `add(...)`
- `discover(...)`
- `list_agents()`
- `get(name)`
- `remove(name)`
- `run()`
- `runtime_snapshot()`
- `drain_metrics_stream_events()` — for JSONL export paths (mainly CLI; rare in app code)
- `server`
- `isolation` (read-only property, v0.1)
- `max_concurrent_sessions` (read-only property, v0.1)
- `consecutive_failure_limit` (read-only property, v0.1)

## Project structure

```text
src/openrtc/
├── __init__.py
├── py.typed
├── types.py               # ProviderValue and related typing
├── tui/
│   ├── __init__.py
│   └── app.py             # optional Textual sidecar
├── cli/
│   ├── __init__.py        # re-exports `main` and `app`
│   ├── entry.py           # lazy console entry / missing-extra hint
│   ├── commands.py        # Typer commands and programmatic main()
│   ├── types.py           # shared CLI option aliases
│   ├── dashboard.py       # Rich dashboard and list output
│   ├── reporter.py        # background metrics reporter thread
│   ├── livekit.py         # LiveKit argv/env handoff, pool run
│   └── params.py          # shared worker handoff option bundles
├── core/
│   └── pool.py            # AgentPool, discovery, routing
└── observability/
    ├── metrics.py         # RuntimeMetricsStore, footprint helpers
    ├── snapshot.py        # PoolRuntimeSnapshot dataclass
    └── stream.py          # JSONL metrics schema
```

- `core/pool.py`: `AgentPool`, discovery, routing
- `cli/`: Typer/Rich CLI (`openrtc[cli]`)
- `observability/stream.py`: JSONL metrics schema
- `tui/app.py`: optional Textual sidecar (`openrtc[tui]`)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). CI runs **Ruff** and **mypy** on pull
requests alongside the test suite.

## License

MIT. See [LICENSE](LICENSE).
