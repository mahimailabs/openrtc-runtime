---
title: Tenant Incident
description: Identify, isolate, and escalate a misbehaving tenant without disrupting the others.
icon: triangle-exclamation
---

# Tenant Incident

One client is misbehaving (failing calls, eating capacity, blocking the loop). The
goal: confine it, keep the other tenants healthy, and escalate. OpenRTC does most
of the confinement automatically; this runbook is how you confirm and act.

## 1. Identify which tenant

Open the inspector and look tenant by tenant:

```bash
openrtc top --tenant <suspect>     # only that tenant's sessions
openrtc top --sort cpu_pct         # busiest sessions across the pool
```

Filter the scoped logs to the tenant to see its errors:

```bash
openrtc logs worker.jsonl --session <session_id>   # each record carries "tenant"
```

`runtime_snapshot().sessions_by_tenant` shows who is consuming slots.

## 2. Recognize the failure mode

- **Failing calls.** The tenant's sessions raise or drop. If
  `enable_tenant_circuit_breaker` is on, its breaker opens automatically once its
  failure ratio trips: you will see `[circuit-breaker] tenant 'X' opened ...` in
  the logs, and its new sessions are rejected for the cooldown (default 30s), then
  it auto-recovers. **The other tenants are untouched.**
- **Eating capacity.** The tenant is at or near its cap. Its overflow is already
  rejected (`max_sessions_per_tenant`), so siblings keep accepting. If it has no
  cap, add one (see step 4).
- **Blocking the loop.** A `slow` status in `openrtc top` attributed to the
  tenant's sessions means synchronous blocking code. This degrades scheduling for
  everyone until fixed (shared event loop). Follow the
  [density debugging runbook](/runbooks/debugging-density).

## 3. Confirm the blast radius is confined

Check that the healthy tenants are still accepting and completing:

```bash
openrtc top --tenant <healthy-tenant>
```

`runtime_snapshot().total_session_failures` rising with only the suspect tenant's
sessions failing (and siblings still counted active) is the confinement working.

## 4. Act

- **Tighten the tenant's budget** immediately if it is starving others: lower its
  `max_sessions_per_tenant` (a redeploy, or a config reload if you load caps
  dynamically).
- **Force isolation** for a repeat offender or untrusted code: move that tenant to
  its own worker (or `isolation="process"`). Coroutine mode is a shared process,
  not a sandbox.
- **Tune the breaker** if it is too eager or too slow: adjust the cooldown
  (`tenant_circuit_cooldown_s`).

## 5. Escalate

If the failure is in the tenant's own agent code, hand the session id + the scoped
log lines (they carry `tenant` + `agent_name`) to that client. If it is a provider
outage for that tenant's keys, the breaker will keep rejecting until the provider
recovers; watch for the auto-recovery log line.

For per-tenant **cost / latency** anomalies (not runtime failures), look in
voicegateway, which owns that lane keyed off `metadata["tenant"]`.

## Limits to know

- Caps and the breaker are **soft/best-effort**: a burst of simultaneous accepts
  can briefly overshoot a cap before the live counts catch up.
- The breaker acts on **failure rate**, not on a single bad call, and needs a
  minimum sample count before it opens.
- Shared-process isolation is not an OS sandbox. For a hard wall, isolate the
  tenant per the "Force isolation" step above.
