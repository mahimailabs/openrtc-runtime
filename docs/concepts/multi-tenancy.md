---
title: Multi-tenancy
description: Run many clients (tenants) in one OpenRTC pool with per-tenant provider keys, resource fairness, and blast-radius isolation, plus what is shared and what is not.
icon: building
---

# Multi-tenancy

An agency runs many clients on one deployment. OpenRTC makes that safe: each
**tenant** gets its own provider keys, its own resource budget, and a blast
radius that stops one client's bad code from hurting the others. This is the
agency rung.

A tenant is named by the dispatch metadata key **`tenant`** (matching what
voicegateway reads). A session with no `tenant` runs under `"default"`, so
single-tenant deployments work unchanged.

<Note>
The tenant flows through the whole session via a contextvar. Agent code can read
it with `from openrtc.context import current_tenant_id` (or `session.tenant_id`).
It is validated (1-128 chars of letters, digits, dashes, underscores); a malformed
tenant rejects the session rather than silently mislabeling it.
</Note>

## The four guarantees

| Guarantee | Mechanism | Ticket |
| --- | --- | --- |
| **Config isolation** | Per-tenant STT/LLM/TTS providers and keys, resolved at session start. One tenant's key is never used for another's session. | `tenant_config` |
| **Resource fairness** | Per-tenant session caps: a tenant at its cap is rejected while siblings keep accepting. | `max_sessions_per_tenant` |
| **Blast-radius isolation** | A per-tenant circuit breaker opens when a tenant's failure rate trips, rejecting its new sessions for a cooldown, then auto-recovers. | `enable_tenant_circuit_breaker` |
| **Tagging** | Tenant on every worker-internal signal (`openrtc top --tenant`, scoped logs, `runtime_snapshot().sessions_by_tenant`) and on the observer payload. | always on |

```python
from openrtc import AgentPool
from livekit.plugins import openai, deepgram, cartesia, anthropic

pool = AgentPool(
    agent=SupportAgent,
    tenant_config={
        # Each tenant runs on its own keys/models; omitted providers fall back
        # to the agent's. Build the plugin object (with its key) yourself.
        "acme": {"stt": deepgram.STT(api_key="acme-dg"),
                 "llm": openai.LLM(model="gpt-4o", api_key="acme-oa"),
                 "tts": cartesia.TTS(api_key="acme-ct")},
        "globex": {"llm": anthropic.LLM(model="claude-sonnet-4-6", api_key="glx-an")},
        # initech: no entry -> falls back to the agent/pool defaults (logged once).
    },
    max_sessions_per_tenant={"acme": 50, "globex": 100},
    enable_tenant_circuit_breaker=True,   # 30s cooldown by default
)
```

`tenant_config` can also be a callable (`tenant -> config`, e.g. a DB load); its
result is cached per tenant, so a tenant's later sessions reuse the same client
objects.

## What is shared, and what is not

OpenRTC's density comes from **one process** hosting every tenant's sessions.
That sets the isolation boundary honestly:

**Shared** (by design, this is the density win):
- The worker process and its Python heap.
- The prewarmed VAD and turn detector (loaded once).
- The event loop. A tenant that blocks the loop synchronously affects scheduling
  for everyone until the slow-session detector flags it. That is why per-tenant
  code should stay async (see the [density runbook](/runbooks/debugging-density)).

**Not shared** (isolated per tenant):
- Provider clients and API keys (`tenant_config`).
- Session state and conversation history.
- Resource budget (`max_sessions_per_tenant`) and the circuit breaker.
- Every attribution tag (metrics, logs, `openrtc top`).

<Warning>
Coroutine mode is **shared-process** isolation, not OS-level. For a hard memory /
CPU wall between tenants (a compliance boundary, an untrusted-code tenant), run
`isolation="process"` or a **separate worker per tenant**. The guarantees above
are the right default for a trusted multi-client agency; they are not a sandbox.
</Warning>

## The voicegateway boundary

Per-tenant **cost and quality** attribution lives in **voicegateway**, not here.
OpenRTC carries the tenant on `SessionInfo.metadata["tenant"]`, and voicegateway's
`VoiceGatewayObserver` reads it to attribute cost per client with no extra work.
OpenRTC owns the **runtime** side (config, caps, blast radius, tenant-tagged
introspection); it does not build a parallel cost/telemetry layer.

## Next steps

- [Onboarding a tenant](/runbooks/onboarding-a-tenant): the add-a-client flow.
- [Tenant incident](/runbooks/tenant-incident): identify, isolate, and escalate a
  misbehaving tenant.
