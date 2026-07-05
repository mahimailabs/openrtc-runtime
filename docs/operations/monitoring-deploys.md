---
title: Monitoring a deploy
description: The OpenRTC runtime signals to watch while a blue-green deploy is in flight, and where the cost and quality signals live instead.
icon: gauge-high
---

# Monitoring a deploy

A blue-green deploy is done when three things are true: every worker reports the
new version, the old-version workers have drained to zero active calls, and no
call was dropped. OpenRTC exposes the runtime signals that let you confirm each
one. This page lists them and where to read them.

<Note>
OpenRTC reports **runtime** state: which version a worker runs, whether it is
draining, how many calls it holds. It does **not** compute deploy cost, quality,
or latency deltas. Those are voicegateway's job, read from the
`info.metadata['tenant']` and `info.deployment_version` OpenRTC emits on every
session. Watch OpenRTC to confirm the deploy *completed*; watch voicegateway to
judge whether the new version is *better*.
</Note>

## The three signals to watch

Every signal below comes from `pool.runtime_snapshot()`, which is what
`openrtc top` renders and what a health endpoint can serialize.

| Signal | Where | Healthy deploy looks like |
| --- | --- | --- |
| `deployment_version` | `runtime_snapshot().deployment_version` (per worker) | Distribution shifts from all-old to all-new as the fleet rolls. |
| `draining` | `runtime_snapshot().draining` (per worker) | `True` on old-version workers once you signal drain, `False` on new ones. |
| `active_sessions` | `runtime_snapshot().active_sessions` | Falls to zero on each draining worker, then that worker exits. Steady or rising on new workers. |

```python
snap = pool.runtime_snapshot()
print(snap.deployment_version, snap.draining, snap.active_sessions)
# "v2.0.0" True 3   -> a draining old worker with 3 calls still finishing
```

## The switchover, signal by signal

1. **Before drain:** old workers report the old version, `draining=False`, and
   carry the live calls. New workers report the new version and start taking new
   jobs.

2. **At drain:** you signal the old workers. Each flips to `draining=True` and
   begins rejecting new jobs (a rejected job raises rather than starting, and is
   recorded as a `worker.rejected` audit event, see the
   [audit reference](/compliance/audit-events)). `active_sessions` on the old
   workers stops rising.

3. **During drain:** `active_sessions` on the old workers falls as calls hang up
   naturally. This is the number to watch: it is the count of calls still
   finishing on the version you are retiring.

4. **Drain complete:** an old worker reaches `active_sessions == 0` and exits.
   When the last old worker exits, every remaining worker reports the new
   version. The deploy is done.

## What "healthy" means (and the one number that matters)

The single number that proves zero-downtime held is **dropped calls, which
should be zero**. A call is dropped only if a worker dies with `active_sessions`
above zero before those calls hang up. So the guardrail is simple: never
hard-kill a draining worker before it reaches zero (give drain a timeout longer
than your longest expected call, or let calls end naturally). A worker that exits
at `active_sessions == 0` dropped nothing.

If a draining worker is stuck above zero past your drain timeout, that is the
signal to investigate (a stalled call, a provider hang), not to hard-kill on
schedule.

## Where cost, quality, and latency go

Deploy dashboards usually also want "did p95 latency regress?" and "did cost per
call change?" across the two versions. OpenRTC deliberately does not answer
those. It tags every session with its `deployment_version` and `tenant` and hands
them to the observer; voicegateway's `VoiceGatewayObserver` buckets the metrics
by version and renders the comparison. Keep the deploy-quality dashboard in
voicegateway and the deploy-completion dashboard (this page's signals) in
OpenRTC.

Next: [rollback](/operations/rollback) if the new version regresses.
