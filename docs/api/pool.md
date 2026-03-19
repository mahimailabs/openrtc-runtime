# AgentPool API

## Imports

```python
from openrtc import AgentConfig, AgentPool
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
```

`AgentConfig` is returned from `AgentPool.add()` and represents a registered
LiveKit agent configuration.

## `AgentPool()`

Create a pool that manages multiple LiveKit agents in one worker process.

```python
pool = AgentPool()
```

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
)
```

Registers a named LiveKit `Agent` subclass.

### Validation rules

- `name` must be a non-empty string after trimming whitespace
- names must be unique
- `agent_cls` must be a subclass of `livekit.agents.Agent`

### Returns

An `AgentConfig` instance for the registration.

### Raises

- `ValueError` for an empty or duplicate name
- `TypeError` if `agent_cls` is not a LiveKit `Agent` subclass

## `list_agents()`

```python
pool.list_agents()
```

Returns registered agent names in registration order.

## `run()`

```python
pool.run()
```

Starts the LiveKit worker application.

### Raises

`RuntimeError` if called before any agents are registered.

## Example

```python
from examples.agents.restaurant import RestaurantAgent
from openrtc import AgentPool

pool = AgentPool()
pool.add(
    "restaurant",
    RestaurantAgent,
    stt="deepgram/nova-3:multi",
    llm="openai/gpt-5-mini",
    tts="cartesia/sonic-3",
)

pool.run()
```
