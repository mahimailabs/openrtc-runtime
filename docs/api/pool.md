# AgentPool API

## Imports

```python
from dataclasses import field
from typing import Any

from livekit.agents import Agent

from openrtc import (
    AgentConfig,
    AgentDiscoveryConfig,
    AgentPool,
    ProviderValue,
    agent_config,
)
```

`ProviderValue` is `str | Any`: provider ID strings (for example
`openai/gpt-4.1-mini`) or concrete LiveKit plugin instances (for example
`openai.STT(...)`).

## `AgentConfig`

```python
@dataclass(slots=True)
class AgentConfig:
    name: str
    agent_cls: type[Agent]
    stt: ProviderValue | None = None
    llm: ProviderValue | None = None
    tts: ProviderValue | None = None
    greeting: str | None = None
    session_kwargs: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None
```

`AgentConfig` is returned from `AgentPool.add()` and represents a registered
LiveKit agent configuration.

`source_path` is set when an agent is registered via **`discover()`** (path to
the module file) or when **`add(..., source_path=...)`** is used. It enables
tooling such as the `openrtc list --resources` footprint output and is included
in pickle state for worker processes.

## `AgentDiscoveryConfig`

```python
@dataclass(slots=True)
class AgentDiscoveryConfig:
    name: str | None = None
    stt: ProviderValue | None = None
    llm: ProviderValue | None = None
    tts: ProviderValue | None = None
    greeting: str | None = None
```

`AgentDiscoveryConfig` stores optional metadata attached to an agent class with
`@agent_config(...)`.

## `agent_config(...)`

```python
from livekit.plugins import openai

@agent_config(
    name="restaurant",
    stt=openai.STT(model="gpt-4o-mini-transcribe"),
    llm=openai.responses.LLM(model="gpt-4.1-mini"),
    tts=openai.TTS(model="gpt-4o-mini-tts"),
    greeting="Welcome to reservations.",
)
class RestaurantAgent(Agent):
    ...
```

Use `agent_config(...)` to attach discovery metadata to a standard LiveKit
`Agent` subclass.

## `AgentPool(...)`

Create a pool that manages multiple LiveKit agents in one worker process.

```python
from typing import Literal

from livekit.plugins import openai

pool = AgentPool(
    default_stt=openai.STT(model="gpt-4o-mini-transcribe"),
    default_llm=openai.responses.LLM(model="gpt-4.1-mini"),
    default_tts=openai.TTS(model="gpt-4o-mini-tts"),
    default_greeting="Hello from OpenRTC.",
    isolation="coroutine",
    max_concurrent_sessions=50,
    consecutive_failure_limit=5,
)
```

Constructor defaults are used when an agent registration or discovered agent
module omits those values.

### Constructor kwargs

| Argument | Type | Default | Notes |
| --- | --- | --- | --- |
| `default_stt` / `default_llm` / `default_tts` | `ProviderValue \| None` | `None` | Provider used when `add()` / `discover()` omits one. |
| `default_greeting` | `str \| None` | `None` | Greeting used when none is configured per agent. |
| `isolation` | `Literal["coroutine", "process"]` | `"coroutine"` | Worker isolation mode. **`"coroutine"`** is the v0.1 default and runs every session as an `asyncio.Task` in one worker process; **`"process"`** preserves v0.0.17 behavior (one OS subprocess per session via `livekit-agents`'s `ProcPool`). See [Architecture → Coroutine-mode lifecycle](../concepts/architecture#coroutine-mode-lifecycle). |
| `max_concurrent_sessions` | `int` | `50` | Coroutine-mode backpressure threshold. The worker reports `current_load >= 1.0` to LiveKit dispatch once this many sessions are in flight, so new jobs route elsewhere. Must be `>= 1`. Ignored in process mode (livekit-agents' own load math applies there). |
| `consecutive_failure_limit` | `int` | `5` | After this many non-`SUCCESS` session terminations in a row, the coroutine pool's supervisor schedules `aclose()` so the deployment platform restarts the worker (bounded blast radius for systemic bugs). Must be `>= 1`. Ignored in process mode. |

### Read-only properties

| Property | Returns | Notes |
| --- | --- | --- |
| `pool.isolation` | `Literal["coroutine", "process"]` | The configured isolation mode (set in the constructor). |
| `pool.max_concurrent_sessions` | `int` | The configured backpressure threshold. |
| `pool.consecutive_failure_limit` | `int` | The configured supervisor threshold. |

### Migration note

Existing code that does `pool = AgentPool()` keeps working but now runs every
session in coroutine mode by default. Pass `isolation="process"` to stay on the
v0.0.17 process-per-session model. The full migration block lives in the v0.1.0
section of [the changelog](../changelog).

## `server`

```python
server = pool.server
```

Returns the underlying LiveKit `AgentServer` instance. Under
`isolation="coroutine"`, this is an internal `_CoroutineAgentServer` subclass
that swaps `livekit.agents.ipc.proc_pool.ProcPool` for an `openrtc.execution.coroutine.CoroutinePool`
during `run()`. Under `isolation="process"`, this is the vanilla
`livekit.agents.AgentServer`.

## `add()`

```python
pool.add(
    name,
    agent_cls,
    *,
    stt=None,
    llm=None,
    tts=None,
    greeting=None,
    session_kwargs=None,
    source_path=None,
    **session_options,
)
```

Registers a named LiveKit `Agent` subclass.

Optional **`source_path`** records the filesystem path to the agent’s module
(used for discovery metadata and footprint reporting).

### Validation rules

- `name` must be a non-empty string after trimming whitespace
- names must be unique
- `agent_cls` must be a subclass of `livekit.agents.Agent`
- `agent_cls` must be defined at module scope for spawn-based worker runtimes

### Session options

- `session_kwargs` forwards a mapping of keyword arguments to `AgentSession`
- direct `**session_options` are also forwarded to `AgentSession`
- when the same key appears in both places, the direct keyword argument wins
- by default, OpenRTC supplies `turn_handling` with multilingual turn detection
  and VAD-based interruption unless you override it explicitly

### Returns

An `AgentConfig` instance for the registration.

### Raises

- `ValueError` for an empty or duplicate name
- `TypeError` if `agent_cls` is not a LiveKit `Agent` subclass

## `discover()`

```python
pool.discover("./agents")
```

Discovers Python modules in a directory, imports them, finds a local `Agent`
subclass, and registers it.

Discovery behavior:

- skips `__init__.py`
- skips files whose stem starts with `_`
- uses `@agent_config(...)` metadata when present
- otherwise uses the filename stem as the agent name
- falls back to pool defaults for omitted provider and greeting fields
- preserves file-backed agent loading so discovered agents work with `livekit dev`

### Raises

- `FileNotFoundError` if the directory does not exist
- `NotADirectoryError` if the path is not a directory
- `RuntimeError` if a module cannot be imported or defines no local `Agent`
  subclass

## `list_agents()`

```python
pool.list_agents()
```

Returns registered agent names in registration order.

## `get()`

```python
pool.get("restaurant")
```

Returns a registered `AgentConfig`.

### Raises

- `KeyError` if the agent name is unknown

## `remove()`

```python
pool.remove("restaurant")
```

Removes and returns a registered `AgentConfig`.

### Raises

- `KeyError` if the agent name is unknown

## `run()`

```python
pool.run()
```

Starts the LiveKit worker application by handing the configured
[`server`](#server) to `livekit.agents.cli.run_app`. Under
`isolation="coroutine"` (the v0.1 default), the worker hosts every session as
an `asyncio.Task` inside one process; under `isolation="process"` it spawns
one OS subprocess per session, matching v0.0.17 behavior.

### Raises

- `RuntimeError` if called before any agents are registered. The same guard
  fires inside `_prewarm_worker` if a worker process spawns with an empty
  registry.

## `runtime_snapshot()`

```python
snapshot = pool.runtime_snapshot()
```

Returns a typed runtime snapshot for the current shared worker. The snapshot is
used by the CLI dashboard, `--metrics-json-file`, and `kind: "snapshot"` lines
in `--metrics-jsonl` output. It includes:

- resident memory metadata
- registered and active session counts
- per-agent active session counts
- total sessions started
- session failure count
- last routed agent
- a best-effort shared-worker savings estimate

## `drain_metrics_stream_events()`

```python
events = pool.drain_metrics_stream_events()
```

Removes and returns queued **session lifecycle** records for JSONL export
(`session_started`, `session_finished`, `session_failed`). The OpenRTC CLI calls
this when writing `--metrics-jsonl`; most applications can ignore it.

## Routing behavior

`AgentPool` resolves the active agent in this order:

1. `ctx.job.metadata["agent"]`
2. `ctx.job.metadata["demo"]`
3. `ctx.room.metadata["agent"]`
4. `ctx.room.metadata["demo"]`
5. room-name prefix matching such as `restaurant-call-123`
6. the first registered agent

If metadata references an unknown agent, OpenRTC raises `ValueError`.

## Example

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

## See also

- [Architecture → Coroutine-mode lifecycle](../concepts/architecture#coroutine-mode-lifecycle)
  for the per-session task lifecycle, supervisor, drain, and
  `current_load` semantics.
- [Density benchmark (v0.1)](../benchmarks/density-v0.1) for the
  ≥50-sessions-per-worker numbers backing the default `max_concurrent_sessions`.
- [Changelog](../changelog) for the v0.1.0 migration block.
