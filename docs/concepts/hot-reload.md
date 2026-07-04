---
title: Hot Reload
description: Edit an agent file and OpenRTC swaps live sessions to the new class on their next turn, with no dropped calls.
icon: bolt
---

# Hot Reload

Edit an agent file while calls are in flight, and OpenRTC re-imports it and swaps
every live session to the new class on its next turn. This is something
`livekit-agents` cannot do, because each of its sessions runs in its own OS
process. OpenRTC can, because in coroutine mode the agent class is an object in
shared memory.

<Note>
Hot reload is coroutine-mode only (`isolation="coroutine"`, the default). Process
mode runs one subprocess per session and cannot swap a class in place. `openrtc
start` never hot reloads; `openrtc dev` enables it by default.
</Note>

## Enable it

```bash
openrtc dev ./agents                     # coroutine mode watches your files by default
openrtc dev ./agents --no-watch          # opt out
openrtc dev ./agents --watch-path ./lib  # watch extra paths (repeatable)
```

Programmatically:

```python
from openrtc import AgentPool

pool = AgentPool(enable_hot_reload=True)   # coroutine mode only
```

## How a reload happens

<Steps>
  <Step title="Detect">
    A debounced file watcher notices the edited module and hands the change to the reload coordinator.
  </Step>
  <Step title="Validate">
    The coordinator re-imports the file into a fresh module object and compiles it. Nothing is swapped until the import succeeds and a local `Agent` subclass is found.
  </Step>
  <Step title="Swap new sessions">
    The registered `AgentConfig.agent_cls` is replaced, so every session that starts from now builds the new class.
  </Step>
  <Step title="Re-bind live sessions">
    Each live session still on the old class is re-bound via livekit's `AgentSession.update_agent`, which blocks new turns and drains the in-flight one. The current turn finishes on the old class; the next turn runs the new. No WebSocket drop, no audio gap.
  </Step>
</Steps>

Each reload logs a line you can watch on the dev console:

```text
[reload] restaurant.py changed -> swapped 5 sessions in 23ms
```

## Rollback safety

The whole point of hot reload is iteration speed, so a bad save must never poison
the running pool.

| Condition | Behavior |
|---|---|
| `SyntaxError` on save | Keep the running class; log `restaurant.py:12: ...`. No swap. |
| `ImportError` or any import-time exception | Roll `sys.modules` back to the prior module; log the traceback. No swap. |
| Module no longer defines an `Agent` subclass | Keep the running class; report a failed reload. |
| Agent file deleted | Keep the loaded class live; log a warning. |

A failed reload logs at `ERROR` and leaves every live session exactly where it was.

## Pinning critical flows

Some flows cannot tolerate a behavior change mid-session (payment confirmation,
multi-step authentication). Wrap them so a reload skips that session until the
block exits:

```python
from openrtc import pin_reload


class CheckoutAgent(Agent):
    @function_tool
    async def confirm_payment(self, ctx: RunContext) -> str:
        with pin_reload(ctx.session):
            # This session will not swap class until confirmation completes,
            # even if the file is edited mid-flow.
            return await self._charge(ctx)
```

A pinned session that missed a reload catches up to the newest class the next
time it re-binds after being unpinned. `is_pinned(session)` reports the current
state.

## Scope

- One agent is reloaded at a time.
- Only agents with a known `source_path` (from `discover()` or `add(..., source_path=...)`) are watchable; agents registered with a bare class are not.
- Pinning is per session and manual (no pin-by-predicate).

For the API surface, see [AgentPool](/api/pool).
