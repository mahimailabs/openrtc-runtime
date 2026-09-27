---
name: operating-openrtc
description: 'Runs an OpenRTC worker in production and debugs it: start vs dev, one worker per core with --port, drain deploys with deployment_version, per-tenant providers, session caps and the circuit breaker, reading openrtc top, the JSONL metrics stream, load shedding, and when to switch to process isolation. Use when the user says "deploy my openrtc worker", "run openrtc in production", "openrtc top shows slow", "the worker keeps rejecting calls", "one tenant is eating the worker", "cap calls per client", "run several workers on one machine", "address already in use 8081", "No such option", "which agent took this call", or is changing a live OpenRTC deployment. Not for moving a project onto OpenRTC (adopting-openrtc) or for LiveKit Cloud agent hosting itself (operating-livekit-agents).'
license: MIT
metadata:
  author: mahimailabs
---

# Operating OpenRTC

An OpenRTC worker is a livekit-agents worker: it registers with LiveKit, takes jobs, and drains on
SIGTERM like any other. OpenRTC adds routing, hot reload, `openrtc top`, tenants, and drain
tooling on top. This skill covers `openrtc` 0.20 and later.

Facts come from `https://docs.openrtc.tech/llms-full.txt`, not memory. For the LiveKit side
(dispatch, rooms, Cloud hosting), load `operating-livekit-agents` and `reading-livekit-docs`.

## Commands

| Command | Use |
| --- | --- |
| `openrtc start ./agents` | production: no hot reload |
| `openrtc dev ./agents` | development: hot reload on live calls (coroutine mode) |
| `openrtc console ./agents` | talk to an agent from the terminal, no room |
| `openrtc download-files ./agents` | fetch model files at image build time, not at first call |
| `openrtc top` | live table of every call in a worker on the same host |
| `openrtc list ./agents` | what would register, without connecting |

A flag beats its environment variable, which beats the default: `--isolation` /
`OPENRTC_ISOLATION`, `--max-concurrent-sessions` / `OPENRTC_MAX_CONCURRENT_SESSIONS`, `--port` /
`OPENRTC_PORT`. Credentials come from `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`.

```bash
openrtc start ./agents --isolation coroutine --max-concurrent-sessions 40 --metrics-jsonl ./metrics.jsonl
```

## Capacity: CPU is the limit

One coroutine worker is one Python process, so it tops out at about one core. It runs on uvloop by
default (`OPENRTC_UVLOOP=0` turns it off). Its load, as LiveKit sees it, is the higher of
`active / max_concurrent_sessions` and its event-loop lag (60 ms counts as full), so a saturated
worker stops taking calls instead of degrading every call. Something must provide more workers:
more replicas or an autoscaler.

To use more cores on one machine, run one worker per core, each with its own port and its own
`openrtc top` socket:

```python
from openrtc import AgentPool

pool = AgentPool(port=8082, introspection_socket_path="/run/openrtc/worker-2.sock")
```

```bash
OPENRTC_PORT=8082 openrtc start ./agents
openrtc top --socket /run/openrtc/worker-2.sock
```

Measured on two cores: two pinned workers used about a quarter less CPU than one, but each extra
worker adds about 1.1 GB of idle memory. Containers need neither setting: each has its own ports
and filesystem. Switch to `isolation="process"` when the agents do heavy CPU work in Python.

## Reading `openrtc top`

| Column | Coroutine mode | Process mode |
| --- | --- | --- |
| `MEM~` | an equal share of the worker's memory; adds up, but doesn't single out a heavy call | that call's own process (PSS on Linux) |
| `CPU%` | the call's share of sampled CPU | its process's CPU |
| `status` | `slow` when the call blocked the shared loop for over 50 ms | always `active` |

A `slow` call is almost always synchronous work on the event loop (a blocking HTTP client, a large
parse, a CPU-heavy tool) starving every other call in the worker. Fix it in the agent: use an
async client, or `await asyncio.to_thread(...)` for the blocking part. Filter with
`openrtc top --status slow`, `--agent NAME`, `--tenant NAME`; one snapshot with `--once`.

## Tenants

A tenant is `{"tenant": "acme"}` in the dispatch metadata; none means `default`.

```python
from livekit.plugins import openai

from openrtc import AgentPool

pool = AgentPool(
    tenant_config={"acme": {"llm": openai.responses.LLM(api_key="acme-key")}},
    max_sessions_per_tenant={"acme": 50},
    max_sessions_per_agent={"booking": 20},
    enable_tenant_circuit_breaker=True,
)
```

- `tenant_config` gives each tenant its own providers and keys.
- The caps reject a tenant's or agent's new calls at its cap while the others keep accepting. They
  work in both isolation modes, and are soft: a burst of simultaneous calls can overshoot briefly.
- The breaker rejects a tenant's new calls for `tenant_circuit_cooldown_s` (30 s) after at least
  half of its last 60 s of calls failed (5 minimum). Coroutine mode only; `AgentPool` raises
  otherwise.
- Tenants share a process: this confines load and failures, not memory. For a hard wall between
  clients, run a worker per tenant.

## Deploys

A live call cannot move between processes, so deploys drain: the new version takes new calls and
the old one finishes its calls, then exits. On SIGTERM a worker stops accepting and waits up to
`drain_timeout` (30 s by default).

```python
from openrtc import AgentPool

pool = AgentPool(deployment_version="v2.3.0", drain_timeout=120)
```

Set `drain_timeout` longer than a typical call, and match your platform's grace period to it (for
Kubernetes, `terminationGracePeriodSeconds`). `deployment_version` shows in `runtime_snapshot()`
and on audit events, so you can see which version served a call. `pool.begin_drain()` starts a
drain from your own code in coroutine mode.

## Observability

- `--metrics-jsonl PATH`: one JSON object per line, pool snapshots plus `session_started`,
  `session_finished` and `session_failed` events, for `tail -f` or `jq`.
- `AgentPool(observers=[...])`: async `on_session_start` / `on_session_end` hooks for your own
  telemetry. A slow or failing observer never breaks the call.
- `pool.runtime_snapshot()`: active sessions by agent and tenant, totals, memory, the deployment
  version and whether it is draining.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `address already in use` on 8081 | a second worker on the host; give each its own `--port` |
| `No such option: --isolation` | openrtc before 0.20.1 passed runtime flags to livekit's parser; upgrade, or use the `OPENRTC_*` variables |
| `ValueError` naming an unknown agent | dispatch or room metadata names an agent the pool lacks; fix the metadata or register the agent |
| every call goes to the first agent | no routing signal matched; set `{"agent": ...}` metadata or name rooms `<agent>-...` |
| the worker stops accepting calls under load | its event loop is saturated; add workers, fix `slow` calls, or use `isolation="process"` |
| `openrtc top` says no worker | wrong host or socket; pass `--socket`, or the worker was built with `enable_introspection=False` |
| a tenant's calls all rejected for 30 s | its circuit breaker opened after repeated failures; fix the cause in its logs |
