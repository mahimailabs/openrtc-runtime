# AgentPool API

## Imports

```python
from openrtc import AgentConfig, AgentDiscoveryConfig, AgentPool, agent_config
```

## `AgentConfig`

```python
@dataclass(slots=True)
class AgentConfig:
    name: str
    agent_cls: type[Agent]
    stt: Any = None
    llm: Any = None
    tts: Any = None
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
    stt: Any = None
    llm: Any = None
    tts: Any = None
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
from livekit.plugins import openai

pool = AgentPool(
    default_stt=openai.STT(model="gpt-4o-mini-transcribe"),
    default_llm=openai.responses.LLM(model="gpt-4.1-mini"),
    default_tts=openai.TTS(model="gpt-4o-mini-tts"),
    default_greeting="Hello from OpenRTC.",
)
```

Constructor defaults are used when an agent registration or discovered agent
module omits those values.

## `server`

```python
server = pool.server
```

Returns the underlying LiveKit `AgentServer` instance.

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

Starts the LiveKit worker application.

### Raises

- `RuntimeError` if called before any agents are registered

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
