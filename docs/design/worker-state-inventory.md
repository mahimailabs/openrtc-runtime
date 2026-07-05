# Worker state inventory and the drain-only decision (MAH-108)

Status: decided (2026-07). This is the contract every other v0.6 issue rests on.

## Question

To upgrade a worker without dropping calls, can we **migrate a live session** from
an old worker to a new one (serialize its state, resume it elsewhere), or must we
**drain** (let in-flight calls finish on the old worker while new calls go to the
new one)?

The answer depends on whether a live `AgentSession`'s state is serializable. This
document inventories that state and records the decision.

## State inventory

Every piece of state a live session carries, classified as **serializable**
(portable bytes), **derivable** (can be rebuilt from config on the new worker), or
**live** (bound to this process / socket / in-flight operation and not portable).

| State | Class | Notes |
| --- | --- | --- |
| Conversation history (chat context: turns, roles, text) | **serializable** | Plain data. Portable in principle. |
| Agent identity (`agent_name`, `tenant`, `job_id`, dispatch metadata) | **serializable** | Already portable (it is how the session is dispatched). |
| Agent class + instructions | **derivable** | Rebuilt by instantiating the registered `Agent` on the new worker. |
| Provider config (STT/LLM/TTS selection, keys, models) | **derivable** | Rebuilt from the pool's registration / tenant config. |
| Prewarmed VAD + turn detector | **derivable** | Loaded once per worker in prewarm; not session-owned. |
| **LiveKit room / WebRTC transport** (the `rtc.Room`, peer connection, media tracks) | **live** | An open WebRTC session with the caller. Bound to this process's sockets and ICE state. Not serializable, and the caller cannot be silently re-pointed to a new server mid-call without a renegotiation the SDK does not expose. |
| **In-flight STT stream** (audio frames being transcribed) | **live** | An open streaming request to the STT provider. Cannot be paused and resumed elsewhere. |
| **In-flight LLM stream** (a response being generated token by token) | **live** | An open streaming completion. Serializing mid-stream would drop the partial turn. |
| **In-flight TTS stream** (audio being synthesized and played) | **live** | Open synthesis + playback. The caller is hearing it right now. |
| Turn state (VAD endpointing, interrupt handling, the current turn's timers) | **live** | Tied to the in-flight audio and the loop's timers. |
| Open aiohttp sessions / provider clients | **live** | Process-bound sockets, shared across the worker's sessions. |

## The finding

The **serializable + derivable** state (conversation history, identity, config) is
enough to *reconstruct a fresh session* on the new worker. It is **not** enough to
*resume a live one*: the WebRTC transport, the in-flight STT/LLM/TTS streams, and
the turn state are all **live**. There is no supported way to hand an open
`AgentSession`'s media transport and in-flight provider streams to another process
without dropping the current turn's audio, and the caller's SDK is not built to be
re-pointed to a new server mid-call.

In short: **you cannot migrate a live call without a gap the caller hears.**

## Decision: blue-green drain, not migration

v0.6 does **zero-downtime upgrades by draining**, not by migrating live sessions:

- The new worker version takes **new** calls.
- The old worker **stops accepting** new calls and lets its in-flight calls finish
  naturally (drain), then exits.
- Zero calls are dropped, because no live call is ever moved.

This is [MAH-109](https://linear.app/mahimairaja/issue/MAH-109). It reuses the
graceful drain already built in Phase 2 (`CoroutinePool.drain()` on SIGTERM) rather
than inventing a migration protocol on top of non-migratable state.

## Deferred: the migration APIs

The original MAH-108 acceptance criteria included `session.serialize() -> bytes` /
`AgentSession.deserialize(...)` and a cross-worker round-trip. Those are the
building blocks of live migration, which this inventory shows is not viable for a
live call. They are **deferred beyond v0.6** along with migration itself. If
migration is ever revisited (e.g. for a "pause a call, resume later" feature rather
than a live handoff), the format recommendation on record is **msgpack**: compact,
Python-native types, no schema-compiler step, and a `version: 1` header so future
schemas can coexist. Only the serializable + derivable rows above would go in it;
the live rows never can.

## Implication for the rest of v0.6

Because there is no migration, the v0.6 tickets are the **drain-and-deploy**
primitives, not a migration coordinator:

- **MAH-109** graceful drain on deploy (drain-only).
- **MAH-110** `deployment_version` tagging + the blue-green drain pattern (the
  gradual traffic shift and rollout orchestration are the deployment platform's job
  via LiveKit worker rotation / a rolling update; OpenRTC supplies the version tag,
  the drain, and the visibility, since it runs one worker, not a fleet scheduler).
- **MAH-111** signed-version membership (keep an old-version worker from grabbing
  new-version traffic).
- **MAH-112** audit hooks (record each deploy / drain / rollback and which worker
  version handled a call).
