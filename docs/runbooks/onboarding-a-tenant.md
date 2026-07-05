---
title: Onboarding a Tenant
description: The step-by-step flow to add a new client (tenant) to an OpenRTC pool safely.
icon: user-plus
---

# Onboarding a Tenant

Adding a client to a running agency pool. Follow this in order; each step is
independently verifiable before the next.

## 1. Pick the tenant id

Choose a stable id (1-128 chars of letters, digits, dashes, underscores), e.g.
`acme-corp`. This id keys the tenant's config, caps, metrics, and logs, so it must
match everywhere. Your dispatch layer sets it as the metadata key `tenant`.

## 2. Provision the tenant's provider keys

Create the client's own STT/LLM/TTS keys with your providers. Never reuse another
tenant's key: OpenRTC keeps each tenant's provider objects separate, but only if
you give it separate objects.

## 3. Add the tenant config

Build the plugin objects with the tenant's keys and register them:

```python
pool = AgentPool(
    agent=SupportAgent,
    tenant_config={
        "acme-corp": {
            "stt": deepgram.STT(api_key="acme-dg"),
            "llm": openai.LLM(model="gpt-4o", api_key="acme-oa"),
            "tts": cartesia.TTS(api_key="acme-ct"),
        },
        # ... existing tenants ...
    },
    max_sessions_per_tenant={"acme-corp": 50},
    enable_tenant_circuit_breaker=True,
)
```

For a large or dynamic roster, use a callable so tenants load from your database
without a redeploy:

```python
def load_tenant(tenant: str):
    row = db.tenants.get(tenant)   # return None to fall back to defaults
    return None if row is None else {"llm": openai.LLM(model=row.model, api_key=row.key)}

pool = AgentPool(agent=SupportAgent, tenant_config=load_tenant)
```

Omitted providers fall back to the agent's defaults, so a tenant can override just
the `llm` and keep the shared `stt` / `tts`.

## 4. Set the tenant's budget

Give the tenant a session cap sized to its plan: `max_sessions_per_tenant={"acme-corp": 50}`.
Caps may sum past `max_concurrent_sessions` (they overlap); the global worker cap
still applies on top.

## 5. Route the tenant's calls

Your dispatch layer must put `tenant` in the job (or room) metadata for every
call. If a client needs a different **prompt**, route it to its own agent with a
custom `router` (a distinct prompt lives in a distinct `Agent` subclass), not in
`tenant_config` (which governs providers only).

## 6. Verify before going live

- Place a test call for the tenant. Confirm it appears under the right tenant:
  ```bash
  openrtc top --tenant acme-corp
  ```
- Check the scoped logs carry `"tenant": "acme-corp"`.
- Confirm `runtime_snapshot().sessions_by_tenant` counts the tenant.
- Confirm cost shows up under the tenant in voicegateway (it reads
  `metadata["tenant"]` with no extra config on your side).

## 7. Watch the first day

Keep `openrtc top --tenant acme-corp` open during the first real traffic. If the
tenant's sessions start failing, its circuit breaker will confine the damage (see
[tenant incident](/runbooks/tenant-incident)).
