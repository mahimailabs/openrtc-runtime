# OpenRTC API reference

## Public exports

```python
from openrtc import AgentPool, AgentConfig, AgentDiscoveryConfig, agent_config
```

## `AgentPool`

### Constructor

```python
AgentPool(
    *,
    default_stt: str | Any = None,
    default_llm: str | Any = None,
    default_tts: str | Any = None,
    default_greeting: str | None = None,
)
```

All defaults are inherited by agents that don't override them.

### `pool.add()`

```python
pool.add(
    name: str,                                  # unique routing name
    agent_cls: type[Agent],                     # Agent subclass
    *,
    stt: str | Any = None,                      # STT provider override
    llm: str | Any = None,                      # LLM provider override
    tts: str | Any = None,                      # TTS provider override
    greeting: str | None = None,                # greeting after connect
    session_kwargs: Mapping[str, Any] = None,   # extra AgentSession kwargs
    **session_options: Any,                      # direct AgentSession kwargs
) -> AgentConfig
```

- Raises `ValueError` if `name` is duplicate or empty.
- Raises `TypeError` if `agent_cls` is not an `Agent` subclass.
- Direct `**session_options` override matching keys in `session_kwargs`.

### `pool.discover()`

```python
pool.discover(agents_dir: str | Path) -> list[AgentConfig]
```

- Scans `agents_dir` for `*.py` files (skips `__init__.py` and `_`-prefixed).
- Each file must define exactly one local `Agent` subclass.
- Reads `@agent_config(...)` metadata from the class if present.
- Calls `pool.add()` for each discovered agent.

### `pool.list_agents()`

```python
pool.list_agents() -> list[str]
```

Returns registered agent names in registration order.

### `pool.get()` / `pool.remove()`

```python
pool.get(name: str) -> AgentConfig        # raises KeyError
pool.remove(name: str) -> AgentConfig      # raises KeyError
```

### `pool.run()`

```python
pool.run() -> None
```

Starts the LiveKit worker. Raises `RuntimeError` if no agents are registered.
Under the hood this calls `livekit.agents.cli.run_app()`, so pass `dev` or
`start` as a CLI argument.

### `pool.server`

```python
pool.server -> AgentServer
```

The underlying LiveKit `AgentServer` instance.

## `@agent_config(...)`

```python
@agent_config(
    *,
    name: str | None = None,
    stt: str | Any = None,
    llm: str | Any = None,
    tts: str | Any = None,
    greeting: str | None = None,
)
```

Decorator that attaches discovery metadata to an `Agent` class. All fields are
optional — omitted fields fall back to pool defaults.

## `AgentConfig`

Dataclass holding the resolved configuration for a registered agent:

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Unique routing name |
| `agent_cls` | `type[Agent]` | The Agent subclass |
| `stt` | `Any` | Resolved STT provider |
| `llm` | `Any` | Resolved LLM provider |
| `tts` | `Any` | Resolved TTS provider |
| `greeting` | `str \| None` | Greeting text |
| `session_kwargs` | `dict[str, Any]` | Extra AgentSession kwargs |

## Session kwargs

Common kwargs forwarded to `AgentSession(...)`:

| Key | Type | Purpose |
|---|---|---|
| `max_tool_steps` | `int` | Max tool-call rounds per turn |
| `preemptive_generation` | `bool` | Start LLM before user finishes |
| `turn_handling` | `dict \| object` | Turn detection / interruption config |
