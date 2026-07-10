---
title: Routing
description: How OpenRTC resolves which Agent handles each incoming session, with priority rules, metadata formats, and error behavior.
icon: route
---

# Routing

OpenRTC resolves the active agent for each incoming session through a priority chain. The chain runs before `ctx.connect()`, so it must work entirely from pre-connect metadata.

## Priority chain

Strategies run in order. The first one that returns a match wins.

| Priority | Source | How it works |
|---|---|---|
| 1 | `ctx.job.metadata["agent"]` | Agent name from the job assignment metadata (set by your dispatch caller). |
| 2 | `ctx.job.metadata["demo"]` | Legacy fallback key, same format. |
| 3 | `ctx.job.room.metadata["agent"]` | Room metadata from the job's room assignment (read before connect; authoritative). |
| 4 | `ctx.job.room.metadata["demo"]` | Legacy fallback key, same format. |
| 5 | Room name prefix | Room name begins with `<agent-name>-`, e.g. `support-call-123` routes to `support`. |
| 6 | First registered agent | Default fallback: the agent registered first with `pool.add()`. |

<Note>
Strategies 3 and 4 read `ctx.job.room.metadata`, not `ctx.room.metadata`. The rtc.Room (`ctx.room`) is empty until `ctx.connect()` is called. The job assignment carries the authoritative room metadata from LiveKit's dispatch system before the room connects.
</Note>

## Metadata format

Pass metadata as a JSON object with an `"agent"` key:

```json
{"agent": "support"}
```

OpenRTC accepts:
- A JSON string: `'{"agent": "support"}'` (common from LiveKit CreateRoom)
- A Python dict: `{"agent": "support"}` (common from test fixtures)

The `"demo"` key is an alias for `"agent"` with lower priority. You can use it for showcase scenarios where the primary `"agent"` key is absent.

Non-JSON strings, blank strings, and JSON scalars (e.g. `"42"`) are ignored: the strategy defers to the next one. An absent metadata field is also a no-op (no error).

## Routing a session via job metadata

When dispatching a job with the LiveKit SDK, set `job.metadata`:

```python
from livekit import api

await lk_api.agent_dispatch.create_dispatch(
    api.CreateAgentDispatchRequest(
        agent_name="my-worker",
        room="my-room",
        metadata='{"agent": "dental"}',
    )
)
```

OpenRTC reads `ctx.job.metadata` first (priority 1), which resolves before the room connects.

## Routing a session via room metadata

Set the room's metadata when creating it:

```python
await lk_api.room.create_room(
    api.CreateRoomRequest(
        name="dental-room-42",
        metadata='{"agent": "dental"}',
    )
)
```

OpenRTC reads `ctx.job.room.metadata` (priority 3): the LiveKit dispatch system copies the room metadata onto the job assignment, so routing works pre-connect.

## Routing via room name prefix

If neither job nor room metadata contains an `"agent"` key, OpenRTC checks whether the room name starts with a registered agent name followed by `-`:

```text
dental-call-1234    →  dental
restaurant-room-42  →  restaurant
general-chat        →  (no match, falls through to default)
```

This is convenient for low-config deployments where the room naming convention is enough to route.

## Default fallback

If no strategy matches, OpenRTC routes to the **first registered agent** (the first call to `pool.add()`). This means a single-agent pool always resolves, and a multi-agent pool has a sensible default for sessions that carry no routing signal.

## Scoping which rooms a worker accepts

The priority chain runs **after** a worker has accepted a job, and thanks to the default fallback it always resolves *some* agent. That is the right behavior for a worker that owns its LiveKit project, but the wrong behavior when workers share one.

Under automatic dispatch, LiveKit offers every room to every registered worker. If two OpenRTC workers (or an OpenRTC worker beside a non-OpenRTC agent) share a project, each worker would accept rooms meant for the other and default-route them onto its first agent.

Filter jobs one layer earlier, at acceptance time, with LiveKit's per-job `on_request` hook:

<Note>
A request filter decides **whether** to take a job; the priority chain decides **which** agent handles the jobs you took. They are independent: a job that passes the filter still runs through the full chain.
</Note>

### Convenience: accept only your own rooms

```python
pool = AgentPool(accept_only_registered_rooms=True)
pool.add("support", SupportAgent)
pool.add("billing", BillingAgent)
```

The worker accepts a job only when an **explicit** routing signal maps it to one of this pool's agents:

- job or room metadata names a registered agent (`{"agent": "support"}`), or
- the room name is prefixed with a registered agent name (`support-call-123`).

Everything else is rejected via `req.reject()`. This mirrors the priority chain **minus the default fallback**, so foreign rooms (which no registered agent claims) are declined instead of grabbed. Metadata naming an unregistered agent is treated as "not mine" and rejected, never raised.

### Full control: a custom filter

Pass any async `on_request` handler as `request_fnc`:

```python
from openrtc import AgentPool, RequestFilter
from livekit.agents import JobRequest


async def only_support_rooms(req: JobRequest) -> None:
    if req.room.name.startswith("support-"):
        await req.accept()
    else:
        await req.reject()


support_filter: RequestFilter = only_support_rooms
pool = AgentPool(request_fnc=support_filter)
```

`request_fnc` defaults to `None` (accept every job, LiveKit's default). It is mutually exclusive with `accept_only_registered_rooms`. `RequestFilter` is exported for typing your own filters.

## Error behavior

| Condition | Behavior |
|---|---|
| Metadata specifies an agent name that is not registered | Raises `ValueError("Unknown agent '...' requested via ...")`: no silent fallback |
| Pool has no registered agents | Raises `RuntimeError("No agents are registered in the pool.")` |
| Valid agent resolved | Logs `Resolved agent '<name>' via <source>.` at INFO level |

The deliberate error-on-unknown keeps routing failures loud. A typo in a metadata value surfaces immediately rather than silently falling through to the wrong agent.

## Checking routing in the CLI

```bash
openrtc list --agents-dir ./agents
```

This prints each registered agent and its configured providers. Registration order determines default fallback order.
