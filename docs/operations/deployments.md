---
title: Zero-downtime Deployments
description: Upgrade an OpenRTC worker fleet without dropping calls, using blue-green drain.
icon: rocket
---

# Zero-downtime Deployments

The enterprise ask is simple: deploy a new version without dropping calls. OpenRTC
answers it with **blue-green drain**. The new version takes new calls; the old
version stops accepting and lets its in-flight calls finish naturally, then exits.
No live call is ever moved, so none is ever dropped.

<Note>
OpenRTC does **not** migrate a live call between workers. A live session holds an
open WebRTC transport and in-flight STT/LLM/TTS streams that are not portable (see
the [worker state inventory](/concepts/migration)). Drain sidesteps the infeasible
handoff and still delivers zero dropped calls.
</Note>

## The model

OpenRTC runs one worker. The fleet-level orchestration (start the new version,
shift traffic, retire the old) is your **deployment platform's** job (a Kubernetes
rolling update, a LiveKit worker rotation). OpenRTC supplies the primitives the
platform drives:

| Primitive | What it does |
| --- | --- |
| `AgentPool(deployment_version="v2.0.0")` | Tags the worker so you can see which version each one runs. |
| `runtime_snapshot().deployment_version` / `.draining` | Observe the version and drain state of a worker. |
| `pool.begin_drain()` (or SIGTERM) | Stop accepting new calls; in-flight run to hangup, then exit. |
| Signed membership (`sign_membership` / `MembershipVerifier`) | Keep a leftover old-version worker from grabbing new traffic. |
| Audit hooks (`audit_sink`) | Record every deploy / drain / rejection for compliance. |

## The walkthrough

1. **Tag both versions.** Old workers run `AgentPool(deployment_version="v1.0.0")`;
   the new build runs `deployment_version="v2.0.0"`.

2. **Roll out the new version.** Your platform starts v2 workers alongside v1.
   LiveKit dispatches new jobs across the available workers. If you want v2 to take
   all new traffic first, gate v1 with signed membership against a v2 manifest so
   the coordinator stops routing new jobs to v1 (see
   [signed membership](/compliance/audit-events#signed-membership)).

3. **Drain the old version.** Signal each v1 worker to drain. In production this is
   the **SIGTERM** your platform sends when retiring a pod; OpenRTC's Phase 2 drain
   handles it (stop accepting, await in-flight, exit within `drain_timeout`). To
   trigger it programmatically from a coordinator:

   ```python
   pool.begin_drain()   # reject new jobs; in-flight calls run to hangup
   ```

4. **Watch the switchover.** A draining worker reports `draining=True` and rejects
   new jobs; its `active_sessions` fall as calls hang up. See
   [monitoring deploys](/operations/monitoring-deploys).

5. **Old workers exit clean.** Once a v1 worker's last call ends, it exits. The
   fleet is now all v2. Zero calls were dropped, because every in-flight call
   finished on the worker it started on.

## What "zero-downtime" means here (and does not)

- Every **in-flight** call finishes uninterrupted on its original worker.
- Every **new** call lands on the new version.
- A call is never paused, moved, or resumed elsewhere (no mid-call migration).

If you need the new code to affect a call that is already live, that call must end
first (or you edit the agent in place with [hot reload](/concepts/hot-reload),
which is a different mechanism for in-process changes).

Next: [rollback](/operations/rollback) and [monitoring a deploy](/operations/monitoring-deploys).
