---
title: Audit events
description: The OpenRTC deployment audit-event reference, with the schema, event types, sample SIEM queries, and how to provision the signed-membership secret.
icon: clipboard-check
---

# Audit events

Enterprise compliance (SOC 2, HIPAA, FedRAMP) needs "who deployed what, when"
answerable from logs. OpenRTC emits a small, structured stream of deployment
audit events for exactly this. Each event has a monotonic sequence number, so a
gap or a reorder in the stream is evident (tamper-evident, not tamper-proof), a
timestamp, typed fields, and is handed to a pluggable sink.

<Note>
Audit events cover **deployment lifecycle** (deploy, drain, rollback, worker
rejection). They are not per-call telemetry. "Which worker version handled this
call" rides on the session observer payload (`SessionInfo.deployment_version`),
which voicegateway records, keeping OpenRTC in its runtime lane.
</Note>

## Wiring a sink

By default the audit log writes one structured JSON line per event to the
`openrtc.audit` logger. To ship events to S3, a SIEM, or a compliance store, pass
a sink callable:

```python
from openrtc import AgentPool

def to_siem(event):
    siem_client.put(event.to_dict())   # a flat, JSON-serializable record

pool = AgentPool(
    agent=MyAgent,
    deployment_version="v2.0.0",
    audit_sink=to_siem,
)
```

A sink that raises never reaches the caller: a deploy must not fail because an
audit backend is down. The failure is swallowed and logged, and the sequence
number is still consumed, so a missing `seq` in your store flags the dropped
event.

## Event schema

Every event serializes (via `event.to_dict()`) to a flat record:

| Field | Type | Meaning |
| --- | --- | --- |
| `seq` | int | Monotonic per-process sequence. A gap means a lost or reordered event. |
| `timestamp` | float | Unix time the event was recorded. |
| `event` | string | The event type (see below). |
| `actor` | string | Who triggered it (`"system"`, a user, a coordinator id). Defaults to `"system"`. |
| `target` | string | What it acted on (`"worker"`, `"fleet"`, a worker id). |
| `result` | string | Outcome (`"ok"`, `"rejected"`, ...). Defaults to `"ok"`. |
| `version` | string or null | The deployment version in play. |
| ...extra | any | Any keyword fields passed at emit time are merged in flat (`worker_id`, `reason`, `from_version`, ...). |

## Event types

| Event type | Emitted when | Typical fields |
| --- | --- | --- |
| `deployment.started` | A new version begins rolling out. | `version`, `actor` |
| `deployment.completed` | The fleet is fully on the new version. | `version` |
| `deployment.drain_started` | A worker begins draining (`pool.begin_drain()` or SIGTERM). | `version`, `target="worker"` |
| `deployment.rolled_back` | A deploy is reversed to a prior version. | `version` (good), `from_version` (bad), `reason` |
| `worker.rejected` | A draining or wrong-version worker refuses a new job. | `version`, `result="rejected"` |

<Note>
`migration.*` event types are **reserved** for the deferred mid-call migration
feature (see [migration and drain](/concepts/migration)). v0.6 is blue-green
drain, so they are never emitted. Do not build alerts expecting them.
</Note>

## Sample SIEM queries

The records are flat JSON, so the queries are ordinary field matches. Examples in
a SQL-like SIEM dialect:

```sql
-- Every deploy and rollback in the last 30 days, newest first.
SELECT timestamp, event, version, actor
FROM audit
WHERE event IN ('deployment.started', 'deployment.completed', 'deployment.rolled_back')
  AND timestamp > now() - interval '30 days'
ORDER BY timestamp DESC;

-- Rollbacks and their stated reason (incident review).
SELECT timestamp, version AS rolled_back_to, from_version AS rolled_back_from, reason, actor
FROM audit
WHERE event = 'deployment.rolled_back';

-- Sequence-gap check: a missing seq means a dropped or reordered event.
SELECT seq
FROM audit
WHERE seq NOT IN (SELECT seq - 1 FROM audit)   -- adapt to your window function
ORDER BY seq;

-- Workers that rejected jobs while draining (expected during a deploy; a spike
-- outside a deploy window is worth an alert).
SELECT timestamp, target AS worker, version
FROM audit
WHERE event = 'worker.rejected';
```

## Signed membership

During a rollout, a leftover worker from the previous version must not keep
grabbing new traffic: bugs you just fixed would silently reappear. OpenRTC
provides HMAC-signed membership so a coordinator can verify a worker belongs to
the active deployment before letting it take jobs.

Each worker signs its `(version, worker_id, timestamp)` tuple with a shared
secret; the coordinator verifies the signature and that the version matches the
active manifest:

```python
from openrtc.core.membership import sign_membership, MembershipVerifier

# On the worker, at registration:
token = sign_membership(
    version="v2.0.0", worker_id="w-1", timestamp=now, secret=SECRET,
)

# On the coordinator, before granting traffic:
verifier = MembershipVerifier(secrets=[SECRET], expected_version="v2.0.0")
verifier.verify(token=token, version="v2.0.0", worker_id="w-1", timestamp=now)
# raises MembershipError if the version is wrong, the timestamp is stale or from
# the future (replay protection), or the signature is invalid (constant-time compare).
```

### Provisioning the secret

The signing secret is a deployment credential. Conservative defaults:

- **Source it from your secret manager** (Kubernetes Secret, Vault, cloud KMS),
  injected as an environment variable or mounted file. Never commit it, never
  bake it into an image.
- **Scope it to the deployment control plane.** Only the workers and the
  coordinator need it.
- **Rotate without downtime.** `MembershipVerifier` accepts a list of secrets, so
  during a rotation window pass both the old and new secret; workers signing with
  either verify. Drop the old one once every worker has re-registered with the
  new secret.
- **Freshness window.** The verifier rejects timestamps older or newer than
  `max_age_seconds` (default 300s), which bounds replay. Keep worker and
  coordinator clocks in sync (NTP) so legitimate tokens are not rejected as
  stale.

Attaching the token to LiveKit registration and exiting a rejected worker with a
non-zero code is the coordinator/platform integration on top of these primitives.

Related: [zero-downtime deployments](/operations/deployments),
[rollback](/operations/rollback), [monitoring a deploy](/operations/monitoring-deploys).
