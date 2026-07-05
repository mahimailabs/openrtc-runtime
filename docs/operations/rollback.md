---
title: Rolling back a deploy
description: Undo a bad OpenRTC version the same way you rolled it out, by draining, plus a decision tree for when to roll back versus fix forward.
icon: rotate-left
---

# Rolling back a deploy

A rollback is just a [blue-green deploy](/operations/deployments) pointed the
other way. The version you are rolling back to becomes the "new" version: it
takes new calls while the bad version drains and exits. Because no live call is
ever moved, a rollback drops zero calls, exactly like a forward deploy.

<Note>
There is no separate rollback mechanism to learn. If you can deploy, you can roll
back: the primitives (`deployment_version`, drain, signed membership, audit) are
symmetric. Keep the previous version's image tagged and ready so the platform can
start it without a rebuild.
</Note>

## When to roll back (decision tree)

Rollback is the right move when the new version is actively harming calls and a
fix is not one commit away. Fix forward when the fault is small, understood, and
faster to patch than to reverse.

| Signal after a deploy | Action |
| --- | --- |
| New-version sessions error or drop at an elevated rate | **Roll back now.** Drain the new version, bring the old one back. |
| A provider/config regression affecting every new call | **Roll back now.** The blast radius is the whole fleet. |
| A narrow bug (one agent, one tenant) with an obvious one-line fix | **Fix forward.** Ship a new version; rolling back loses the good parts too. |
| Degraded quality or cost (not correctness) | **Escalate to voicegateway's signals first.** Cost/quality/latency live there, not in OpenRTC. Roll back only if it is a hard regression. |
| Unsure | **Roll back.** Reversing to a known-good version is the conservative default; investigate off the critical path. |

## The rollback walkthrough

1. **Identify the last good version.** From the fleet's
   [`deployment_version` distribution](/operations/monitoring-deploys) or your
   deploy history, pick the version that was healthy before this deploy.

2. **Start the good version alongside the bad one.** Your platform starts
   workers tagged `deployment_version="<last-good>"`. New jobs begin landing on
   them. If a leftover bad-version worker must be kept from grabbing new traffic,
   gate it with [signed membership](/compliance/audit-events#signed-membership)
   against the rolled-back manifest.

3. **Drain the bad version.** Signal each bad-version worker to drain. In
   production this is the SIGTERM your platform sends when retiring the pods; to
   trigger it from a coordinator:

   ```python
   pool.begin_drain()   # bad version stops taking calls; in-flight run to hangup
   ```

4. **Record the rollback.** Emit a `deployment.rolled_back` audit event naming
   the version you left and the version you returned to, so the compliance trail
   shows the reversal and its reason:

   ```python
   pool.audit_log.emit(
       "deployment.rolled_back",
       actor="on-call",
       target="fleet",
       version="<last-good>",
       from_version="<bad>",
       reason="elevated session errors",
   )
   ```

5. **Confirm the fleet is clean.** Every worker reports the good version and the
   bad-version workers have exited (`active_sessions` drained to zero). See
   [monitoring a deploy](/operations/monitoring-deploys).

## What a rollback does not do

- It does not rewind calls that already finished on the bad version. Those calls
  are over; a rollback only governs which version handles calls from now on.
- It does not interrupt calls still in flight on the bad version. They finish on
  the bad version (drain), then that worker exits. If the bug makes in-flight
  calls unsafe to continue, ending them is an application decision, not a
  deployment one.

Next: [monitoring a deploy](/operations/monitoring-deploys) and the
[audit-event reference](/compliance/audit-events).
