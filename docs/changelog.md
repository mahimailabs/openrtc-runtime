---
title: Changelog
description: All notable changes to OpenRTC, including migration notes and version history.
icon: clock-rotate-left
---

# Changelog

All notable changes to this project are documented here.
Entries are added automatically when a new GitHub release is published.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

Changes that have landed on `main` but have not yet been tagged for release.

### v0.9.0: routing: resolve room metadata from the job's room assignment so it works before connect

### v0.1.0: coroutine-mode worker (default behavior change)

> **Heads up:** the default isolation flips from process-per-session to
> a coroutine-mode worker that hosts every session as an `asyncio.Task`
> inside one process. The user-facing API does not break, but workers
> behave differently at runtime. Read the migration notes below before
> upgrading production deployments.

**Added**

- `AgentPool(isolation="coroutine" | "process")` selects the worker
  isolation mode. `"coroutine"` is the new default; `"process"`
  preserves v0.0.17 behavior (one OS subprocess per session via
  `livekit-agents`'s `ProcPool`).
- `AgentPool(max_concurrent_sessions=50)` sets the coroutine-mode
  backpressure threshold. The worker reports `load >= 1.0` to the
  LiveKit dispatcher once this many sessions are in flight; ignored
  in process mode.
- `AgentPool(consecutive_failure_limit=5)` sets the worker supervisor
  threshold. After this many non-`SUCCESS` session terminations the
  worker calls `aclose()` so the deployment platform can restart it
  (bounded blast radius for systemic bugs). Ignored in process mode.
- `AgentPool(drain_timeout=30)` bounds the graceful-drain window.
  When SIGTERM (or SIGINT) is delivered, upstream `AgentServer`'s
  signal handler calls `aclose()`; `drain_timeout` is the per-pool
  budget for in-flight sessions to finish. Sessions that exceed it
  are cancelled with a `WARNING` log and the per-executor `kill()`
  escalation runs. Honored in both isolation modes (forwarded to
  upstream `AgentServer` via the constructor kwarg).
- New CLI flags `--isolation` and `--max-concurrent-sessions` on
  `start` / `dev` / `console`. Both also read environment variables
  (`OPENRTC_ISOLATION`, `OPENRTC_MAX_CONCURRENT_SESSIONS`); precedence
  is CLI flag > env var > library default.
- New `openrtc.execution.coroutine.CoroutinePool` and
  `CoroutineJobExecutor` (internal). Both implement the
  `livekit.agents.ipc.proc_pool.ProcPool` / `JobExecutor` shapes;
  `_CoroutineAgentServer` (also internal) monkey-patches `ProcPool`
  during `run()` so `AgentServer`'s state machine and dispatcher
  protocol are reused unchanged.
- New `tests/benchmarks/density.py` script and corresponding CI gate
  (`.github/workflows/bench.yml`) enforcing ≥ 50 concurrent sessions
  per worker at ≤ 4 GB peak RSS on every PR.
- New nightly canary CI job (`.github/workflows/canary.yml`) that
  runs the integration suite against the latest released
  `livekit-agents` and is allowed to fail.
- New `docker-compose.test.yml` + `tests/integration/conftest.py`
  fixture harness for local and CI integration runs.
- Public `SessionObserver` protocol (`openrtc.SessionObserver`,
  `SessionInfo`, `SessionOutcome`, `SessionStatus`) plus
  `AgentPool(observers=[...])` and `AgentPool.add_observer(...)`. External
  telemetry attaches to each live session through the pool:
  `on_session_start` hands the live `AgentSession`, `on_session_end` the
  terminal outcome. Observer faults are isolated (logged and skipped,
  bounded by a timeout) and never crash the session. Additive and backward
  compatible; the built-in metrics store is unchanged.

**Changed**

- `livekit-agents` pin tightened from `~=1.4` to `~=1.5` because the
  internal-ish surfaces we hook (`ProcPool`, `JobExecutor` Protocol)
  are version-sensitive; the canary job watches the next minor.
- Source layout reorganised under `core/`, `cli/`, `observability/`,
  `tui/`, and `execution/` packages. Public imports
  (`from openrtc import AgentPool`, etc.) are unchanged; internal
  consumers should update to the canonical paths
  (`openrtc.core.config.AgentConfig`, etc.).

**Migration**

- Existing code that does `pool = AgentPool()` keeps working but now
  runs every session in coroutine mode. To stay on the v0.0.17
  process-per-session model, pass `isolation="process"`:

  ```python
  pool = AgentPool(isolation="process")
  ```

  Pick `"process"` when:
  - regulatory or compliance requirements demand hard process
    isolation between sessions;
  - per-session memory caps (`livekit-agents`' `job_memory_limit_mb`)
    are required;
  - the workload mixes very heavy agents with very light agents and
    you want subprocess-level resource accounting.

  Pick the new default `"coroutine"` when:
  - you run many concurrent sessions on a single host and the
    prewarm/idle baseline (VAD, turn detector) was the dominant cost;
  - you want backpressure routed back to LiveKit dispatch via load
    reporting instead of OS-level rejection.

- `consecutive_failure_limit` defaults to 5 in coroutine mode. If your
  agents legitimately fail more often (e.g. exploratory dev runs),
  raise the threshold or run under `isolation="process"` (which the
  setting does not affect).

- The `current_load()` reported in coroutine mode is
  `len(active) / max_concurrent_sessions`. If your dispatch policy
  was tuned around `livekit-agents`' default CPU-based load math, the
  new shape may route differently. Verify against your dispatch
  thresholds (`load_threshold` defaults to `0.7`).

- Per-session memory caps (`job_memory_limit_mb` on `AgentServer`)
  cannot be enforced in coroutine mode (one process, no subprocess
  boundary). Process mode preserves the cap. Documented in design
  §9.4.

See `docs/concepts/architecture.md` for the coroutine-mode lifecycle
and `docs/benchmarks/density-v0.1.md` for the §7 success-gate
benchmark numbers.

**Developer experience**

User-facing behavior is unchanged by these: they land here so the
contributor onboarding matches what's in the repo.

- Test coverage: combined line + branch coverage now sits at 100%
  with the CI gate at 99% (was 80% line-only). `pytest` runs with
  `branch = true` by default.
- Type checking: `mypy` runs in `strict = true` mode on `src/`. CI
  blocks PRs with untyped defs, implicit `Optional`, redundant
  casts, or `Any` returns.
- Linting: ruff selects expanded to include `SIM`, `PT`, `RET`,
  `PERF`, `PIE`, `ICN`, `TID`, `BLE`, `A` on top of the previous
  `E`/`W`/`F`/`I`/`B`/`C4`/`UP` set.
- Pre-commit hook chain extended with `mypy --strict src/` so the
  same typecheck CI applies fires locally on every commit (only
  for source / `pyproject.toml` changes).
- New `make ci` aggregate target runs `lint format-check typecheck
  test` in the same order as CI, short-circuiting on the first
  failure.
- `.github/dependabot.yml` keeps Python and GitHub Actions
  dependencies fresh weekly; `livekit-agents` is intentionally
  excluded (the `~=1.5` pin is design-locked).
- `.github/PULL_REQUEST_TEMPLATE.md` adds a short checklist for
  contributors. `.editorconfig` keeps file-level conventions
  consistent across editors. `SECURITY.md` documents the
  vulnerability-disclosure intake path.

---

<!-- releases -->

## [0.19.0] - 2026-07-18

## What's Changed
* feat(backend): neutral SessionView seam (framework-agnostic, step 1) by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/73
* feat(backend): route on the neutral SessionView seam by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/74
* feat(backend): build SessionInfo from the neutral SessionView seam by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/75
* docs: tabbed docs.json + house-style validator + Validate docs CI by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/76
* feat(backend): drive AgentPool through a neutral Backend seam by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/77
* feat(backend): move run and drain onto the Backend seam by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/78
* feat(backend): move AgentServer construction into the livekit backend by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/79
* feat(backend): select the backend via AgentPool(backend=...) by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/80
* refactor(backend): make import openrtc pull no voice framework by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/81
* feat(backend)!: move livekit-agents to the [livekit] extra (BREAKING) by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/82
* test(pipecat): add the [pipecat] extra and a frame-driven test harness by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/83
* feat(pipecat): lifecycle observer mapping frames to OpenRTC session signals by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/84
* test(pipecat): a call-simulation harness for end-to-end backend verification by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/85
* feat(pipecat): session builder from a registered builder callable by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/86
* refactor(routing): strategies resolve an agent name, resolver looks up by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/87
* feat(pipecat): dispatch a call to its registered builder by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/88
* feat(pipecat): PipecatBackend implementing the Backend seam by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/89
* feat(pipecat): AgentPool(backend="pipecat") constructs and registers builders by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/90
* feat(pipecat): pool.get/remove parity for registered builders by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/91
* feat(pipecat): SharedPrewarm and PipecatCallView primitives by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/92
* feat(pipecat): thread shared prewarm through dispatch to the builder by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/93
* docs: add a Frameworks page for the livekit and pipecat backends by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/94
* feat(pipecat): for_pipecat neutral view adapter by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/95
* feat(pipecat): thread a served call's connection to the builder by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/96
* feat(pipecat): build_call, the runner-args to observed-session seam by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/97
* build(pipecat): add openrtc[pipecat-serve] extra for the serving front by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/98
* feat(pipecat): wire run() to serve calls via pipecat's runner by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/99
* docs: the pipecat backend now serves calls via run() by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/100
* fix(pipecat): hand pipecat's runner a clean argv when serving by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/101
* feat(pipecat): decline new calls while the backend is draining by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/102
* docs: add a Serving snippet for the pipecat backend by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/103
* feat(pipecat): file-based builder discovery via @agent_config by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/104
* feat(pipecat): openrtc serve command by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/105
* docs: document the openrtc serve command by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/106
* test(pipecat): end-to-end serving test; migrate off deprecated PipelineTask/PipelineRunner by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/107
* docs: local smoke-test note for the pipecat serving front by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/108
* examples: runnable pipecat agents + a live-tryout guide for both backends by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/109
* docs(brand): animated density banner in the README by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/110
* feat(brand): refined logo mark + rebranded banner/wordmark by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/111
* docs(brand): new logo, blue palette, fix GitHub links by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/112


**Full Changelog**: https://github.com/mahimailabs/openrtc-runtime/compare/v0.18.0...v0.19.0

---

## [0.18.0] - 2026-07-06

## What's Changed
* test(v0.4): three-agent pool success gate (MAH-100) by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/67
* docs: adoption-first restructure for livekit-agents users by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/68
* docs: lead with the livekit-agents adoption path by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/69
* chore(actions)(deps): bump codecov/codecov-action from 5 to 7 by @dependabot[bot] in https://github.com/mahimailabs/openrtc-runtime/pull/46
* chore(actions)(deps): bump astral-sh/setup-uv from 6 to 7 by @dependabot[bot] in https://github.com/mahimailabs/openrtc-runtime/pull/47
* chore(actions)(deps): bump actions/upload-artifact from 4 to 7 by @dependabot[bot] in https://github.com/mahimailabs/openrtc-runtime/pull/57
* feat(dispatch): named-worker support via AgentPool(agent_name=...) by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/71

## New Contributors
* @dependabot[bot] made their first contribution in https://github.com/mahimailabs/openrtc-runtime/pull/46

**Full Changelog**: https://github.com/mahimailabs/openrtc-runtime/compare/v0.17.0...v0.18.0

---

## [0.17.0] - 2026-07-05

## v0.6: Zero-downtime worker upgrades

Upgrade a worker fleet without dropping calls, using blue-green drain. The new version takes new calls; the old version stops accepting and lets its in-flight calls finish naturally, then exits. No live call is ever moved, so none is dropped.

### Highlights

- **Blue-green drain**: `pool.begin_drain()` (or a SIGTERM from your platform) stops the worker accepting new jobs while its in-flight calls run to hangup, then it exits. Reuses the graceful-drain path, now idempotent so `begin_drain()` then `drain()` compose.
- **Deployment version tag**: `AgentPool(deployment_version="v2.0.0")` labels which version a worker runs, surfaced on `runtime_snapshot().deployment_version` / `.draining` and on the `SessionObserver` payload, so an operator can watch a drain and voicegateway can bucket deploy metrics by version.
- **Signed-version membership**: `sign_membership` / `MembershipVerifier` (HMAC-SHA256, constant-time compare, replay window, secret rotation) keep a leftover old-version worker from grabbing new traffic during a rollout.
- **Deployment audit log**: a monotonic-sequence, pluggable-sink `AuditLog` records deploy / drain / rollback / worker-rejection events for compliance (SOC 2, HIPAA, FedRAMP); `begin_drain()` emits `deployment.drain_started`. Ship events to a SIEM with `audit_sink=...`.
- **Operator docs**: a full deployment guide: the blue-green walkthrough, monitoring signals, a rollback decision tree, the migration-vs-drain rationale, and an audit-event + signed-membership compliance reference.

### The load-bearing decision: drain, not migrate

A live `AgentSession` holds an open WebRTC transport and in-flight STT/LLM/TTS streams. That state is bound to this process and this moment: you cannot serialize a half-generated LLM token or an audio buffer mid-synthesis and resume it elsewhere without a gap the caller hears. So OpenRTC upgrades by draining, not by migrating live sessions. Mid-call migration is deferred by design; the `migration.*` audit events are reserved and not emitted. Full rationale and the state inventory are in the docs.

### Lane boundary

OpenRTC stays in its runtime lane. It emits `info.agent_name`, `info.metadata["tenant"]`, and now `info.deployment_version` on every session; voicegateway buckets deploy cost/quality/latency by version. Watch OpenRTC's `runtime_snapshot()` to confirm a deploy completed; watch voicegateway to judge whether the new version is better.

### Notes

- OpenRTC runs one worker and supplies the primitives (version tag, drain, signed membership, audit). The gradual traffic shift and rollout orchestration are the deployment platform's job (a Kubernetes rolling update, a LiveKit worker rotation).
- Zero-downtime means every in-flight call finishes uninterrupted on its original worker and every new call lands on the new version. A call is never paused, moved, or resumed elsewhere. To have new code affect a call already live, either wait for it to end or use hot reload (a different, in-worker mechanism).
- A rollback is just a blue-green deploy pointed the other way: the primitives are symmetric, so it also drops zero calls.

Milestone: v0.6, Zero-downtime worker upgrades (MAH-108, MAH-109, MAH-110, MAH-111, MAH-112, MAH-113, MAH-114).

---

## [0.16.0] - 2026-07-05

## v0.5: Per-tenant pool isolation

Run every client (tenant) in one pool, isolated. The agency rung: per-tenant provider keys, resource fairness, and blast-radius isolation.

### Highlights

- **Per-tenant provider keys**: `tenant_config={tenant: {stt/llm/tts: ...}}` (or a callable) runs each client on its own STT/LLM/TTS keys and models, resolved at session start and cached per tenant. Keys are never shared across tenants, so an agency can attribute API cost per client.
- **Per-tenant budgets**: `max_sessions_per_tenant={"acme": 50}`: a tenant at its cap is rejected while sibling tenants keep accepting. Composes with per-agent caps and the global cap.
- **Blast-radius isolation**: `enable_tenant_circuit_breaker=True`: a tenant whose calls start failing has its new sessions rejected for a cooldown (default 30s) before auto-recovering. Failures are counted per tenant, so one noisy client never tears down the worker for the others.
- **Tenant tagging**: the tenant is on every worker-internal signal (`openrtc top --tenant`, scoped logs, `runtime_snapshot().sessions_by_tenant`) and on the `SessionObserver` payload, so voicegateway attributes per-tenant cost with no extra config.
- **Tenant context**: resolved from the dispatch metadata key `tenant` (default `"default"`), readable in agent code via `from openrtc.context import current_tenant_id` or `session.tenant_id`.

### Lane boundary

Per-tenant cost and quality attribution stay with voicegateway, keyed off the `metadata["tenant"]` OpenRTC emits. This release owns the runtime side only: config, caps, blast radius, and tenant-tagged introspection.

### Notes

- Single-tenant deployments are unchanged: no `tenant` means the `"default"` tenant, and nothing about your setup changes.
- Per-tenant config keeps OpenRTC's provider passthrough contract: you supply a shorthand string or a pre-built plugin object (with its key); OpenRTC does not parse a `{provider, model, api_key}` spec.
- Per-tenant prompts are done via per-tenant agents (route with `router`), not `tenant_config` (which governs providers only).
- Coroutine mode is shared-process isolation, not an OS sandbox. For a hard wall, run `isolation="process"` or a worker per tenant. See the multi-tenancy guide.

Milestone: v0.5, Per-tenant pool isolation (MAH-101, MAH-102, MAH-103, MAH-104, MAH-105, MAH-106, MAH-107).

---

## [0.15.0] - 2026-07-05

## v0.4: Multi-agent ergonomics

Run several agent types in one pool, with per-agent registration, budgets, routing, reload isolation, and introspection. The bridge from solo dev to small team.

### Highlights

- **Multi-agent registration**: `AgentPool(agents={"sales": SalesAgent, "support": SupportAgent})`, plus the single-agent shorthand `AgentPool(agent=MyAgent)`. Names are validated and duplicates rejected; both compose with `add()` / `discover()`.
- **Per-agent budgets**: `max_sessions_per_agent={"sales": 30, "support": 20}`: a job for an agent at its cap is rejected (backpressure) while sibling agents keep accepting. The global `max_concurrent_sessions` cap still applies on top.
- **Custom router**: `AgentPool(router=fn)` maps dispatch metadata to an agent name, taking precedence over the default metadata/prefix chain. Return `None` to defer to it; an unknown name or a raised router rejects the session.
- **Per-agent hot reload**: editing one agent's file re-binds only that agent's live sessions; sibling agents' calls are untouched (proven with a two-agent real-media integration test).
- **Per-agent metrics namespace**: `agent_name` on scoped log records, and `openrtc top --agent` to filter to one agent (group with `--sort agent_name`).

### Lane boundary

Per-agent cost and latency stay with voicegateway, attributed from the `info.agent_name` OpenRTC emits on the SessionObserver payload. This release only wires the worker's own introspection views by agent.

### Notes

- Agent names accept letters, digits, dashes, and underscores (1-64 chars); underscores are allowed so filename-derived discovery names keep working.
- Per-agent caps are soft/best-effort (they read live active counts, incremented at session start), matching LiveKit's load-based backpressure.
- A custom `router` must be picklable under `process` isolation (a module-level function); the default `coroutine` mode accepts any callable.

Milestone: v0.4, Multi-agent ergonomics (MAH-95, MAH-96, MAH-97, MAH-98, MAH-99).

---

## [0.14.0] - 2026-07-04

## v0.3: Pool observability

See inside a shared coroutine worker for the first time. This release adds per-session introspection: how each multiplexed session uses memory and CPU, and which one is blocking the loop.

### Highlights

- **`openrtc top`**: an htop-style live inspector for your session pool. Columns for memory, CPU, duration, tenant, and status; sort (`s`), filter (`f`), refresh, and `--once` for scripts/CI. Connects to a running coroutine worker over a private local Unix socket (mode 0600, per-user).
- **Per-session memory**: equal-share RSS attribution with a per-session peak (sums back to process RSS). An honest approximation of a shared process; use `isolation="process"` for hard accounting.
- **Per-session CPU**: statistical sampling of which session is on-CPU, via asyncio task->session tagging.
- **Slow-session detector**: attributes an event-loop block over `slow_session_threshold_ms` (default 50ms) to the running session and logs it. The tool for "one session is starving the others".
- **Per-session log scoping**: `session_id` on every log record inside a session, plus `openrtc logs --session` to filter a JSONL log.

### Lane boundary

OpenRTC introspection sees coroutines, not the voice pipeline. Cost, provider latency (STT/LLM/TTS), and quality metrics stay with voicegateway, which consumes the `agent_name` and `metadata["tenant"]` OpenRTC emits.

### Notes

- Introspection is on by default in coroutine mode and skipped in process mode; disable with `AgentPool(enable_introspection=False)`.
- New docs: session introspection concept, `openrtc top` reference (with screenshot), and a density-debugging runbook.

Milestone: v0.3, Pool observability (MAH-88, MAH-89, MAH-90, MAH-91, MAH-92, MAH-94).

---

## [0.13.0] - 2026-07-04

## What's Changed
* fix(coroutine): report session end at real disconnect; prove live hot-reload re-bind (MAH-166/82/83) by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/62


**Full Changelog**: https://github.com/mahimailabs/openrtc-runtime/compare/v0.12.0...v0.13.0

---

## [0.12.0] - 2026-07-04

## What's Changed
* fix(coroutine): clear coroutine debt: turn detector, memory watermark, liveness test, bench framing (MAH-159/161/164/165) by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/61


**Full Changelog**: https://github.com/mahimailabs/openrtc-runtime/compare/v0.11.0...v0.12.0

---

## [0.11.0] - 2026-07-04

## What's Changed
* feat(routing): job-request filter to scope which rooms a worker accepts by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/60


**Full Changelog**: https://github.com/mahimailabs/openrtc-runtime/compare/v0.10.0...v0.11.0

---

## [0.10.0] - 2026-07-04

## What's Changed
* docs: migrate from VitePress to Mintlify by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/53
* docs: restructure navigation with Pipecat-style tabs and grouped sidebar by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/54
* docs: visual polish on architecture, examples, and getting-started by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/55
* fix: flatten mint.json navigation to group/pages format by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/56
* docs: rebrand and meticulously refresh the README by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/58
* feat: hot reload: edit an agent, swap live sessions on the next turn (v0.2, MAH-81..87) by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/59


**Full Changelog**: https://github.com/mahimailabs/openrtc-runtime/compare/v0.9.0...v0.10.0

---

## [0.9.0] - 2026-06-27

## What's Changed
* fix(routing): resolve room metadata from ctx.job.room.metadata before… by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/52


**Full Changelog**: https://github.com/mahimailabs/openrtc-runtime/compare/v0.8.0...v0.9.0

---

## [0.8.0] - 2026-06-26

## What's Changed
* feat(coroutine): wire inference executor so multilingual turn detection by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/51


**Full Changelog**: https://github.com/mahimailabs/openrtc-runtime/compare/v0.7.0...v0.8.0

---

## [0.7.0] - 2026-06-23

## What's Changed
* fix(coroutine): use worker-lifetime http session instead of per-job by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/50


**Full Changelog**: https://github.com/mahimailabs/openrtc-runtime/compare/v0.6.0...v0.7.0

---

## [0.6.0] - 2026-06-23

## What's Changed
* Fix real-room session lifecycle (connect before start) and routing, with a two-agent integration guard by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/49


**Full Changelog**: https://github.com/mahimailabs/openrtc-runtime/compare/v0.5.0...v0.6.0

---

## [0.5.0] - 2026-06-22

## What's Changed
* Open a per-job HTTP context in coroutine (density) mode by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/48


**Full Changelog**: https://github.com/mahimailabs/openrtc-runtime/compare/v0.4.0...v0.5.0

---

## [0.4.0] - 2026-06-21

## What's Changed
* Support livekit-agents 1.6.x in coroutine mode (version-tolerant ProcPool surface) by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/44


**Full Changelog**: https://github.com/mahimailabs/openrtc-runtime/compare/v0.3.1...v0.4.0

---

## [0.3.0] - 2026-06-19

## What's Changed
* feat: public SessionObserver protocol for per-session telemetry by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/42


**Full Changelog**: https://github.com/mahimailabs/openrtc-runtime/compare/v0.2.3...v0.3.0

---

## [0.2.3] - 2026-05-30

### Added
- Day-one savings readout: each worker logs the fleet-collapse idle-baseline memory saved (N agents in one shared-prewarm worker vs N separate livekit-agents workers) once at startup, for both `pool.run()` and `openrtc dev/start`, with no `--dashboard` flag. The line claims only idle baseline saved (not per-session density), stays neutral for a single agent, degrades gracefully when RSS is unavailable, and names its equal-baseline assumption.
- README: a one-screen "Migrating from livekit-agents" recipe (N per-agent workers to one AgentPool).

---

## [0.2.2] - 2026-05-30

### Fixed
- Coroutine mode now establishes the LiveKit job context for the session duration, so `get_job_context()` works inside agents and sessions and shutdown callbacks run (MAH-158).
- Coroutine sessions are held open until the call ends (room disconnect or `ctx.shutdown()`) instead of being marked SUCCESS when the entrypoint returns, so `max_concurrent_sessions` backpressure and runtime session counts are accurate (MAH-160).

### Added
- Real-audio throughput benchmark (`tests/benchmarks/throughput.py`) reporting steady-state event-loop p99 vs session count, separating startup from steady state (MAH-163).
- `examples/density_demo.py`: a no-server demo comparing process-per-session vs coroutine-pool resident memory.

### Changed
- The coroutine real-room integration test is now a correctness gate (job context plus no-failure); throughput moved to the dedicated benchmark.

---

## [0.2.1] - 2026-05-06

## What's Changed
* [v0.2.1] File watcher infrastructure for agent code (MAH-80) by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/39


**Full Changelog**: https://github.com/mahimailabs/openrtc-runtime/compare/v0.1.0...v0.2.1

---

## [0.1.0] - 2026-05-06

## What's Changed
* Feat: light websocket by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/30
* docs: bring docs/ in sync with v0.1 surface by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/35
* Feat: structural refactor by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/36
* Feat/coroutine pool by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/37
* Feat/coroutine pool prod by @mahimairaja in https://github.com/mahimailabs/openrtc-runtime/pull/38


**Full Changelog**: https://github.com/mahimailabs/openrtc-runtime/compare/v0.0.17...v0.1.0

---

## [0.0.17] - 2026-04-03

## What's Changed
* feat: enable generic serialization for all LiveKit plugins  by @mahimairaja in https://github.com/mahimairaja/openrtc-python/pull/28


**Full Changelog**: https://github.com/mahimairaja/openrtc-python/compare/v0.0.16...v0.0.17

---

## [0.0.16] - 2026-03-23

## What's Changed
* DX improvements: uv CI, DeprecationWarning for legacy session_kwargs, CHANGELOG, issue templates, Makefile, .env.example by @Copilot in https://github.com/mahimairaja/openrtc-python/pull/26


**Full Changelog**: https://github.com/mahimairaja/openrtc-python/compare/v0.0.15...v0.0.16

---

## [0.0.15] - 2026-03-22

### Fixed
- CLI: generic error message in `validate_metrics_watch_path`; restored
  `sys.argv` correctly when `main(argv=…)` is called programmatically.

### Added
- CLI: positional shortcuts for `list`, `connect`, `download-files`, and `tui`
  commands so the agents directory and metrics path can be passed as positional
  arguments.
- CLI: positional agents dir and metrics JSONL path on `start`/`dev`/`console`.
- CLI: `openrtc tui` defaults `--watch` to `./openrtc-metrics.jsonl`.
- `DeprecationWarning` emitted when deprecated `session_kwargs` top-level keys
  (e.g. `allow_interruptions`, `min_endpointing_delay`) are used instead of the
  `turn_handling` dict.
- GitHub issue templates for bug reports and feature requests.
- `Makefile` with shortcuts for common developer commands (`make test`,
  `make lint`, `make format`, `make typecheck`).
- `.env.example` documenting all supported environment variables.

### Changed
- CI test and lint workflows migrated from bare `pip` to `uv` with lockfile
  caching, matching the `uv sync --group dev` workflow in `CONTRIBUTING.md`.

---

## [0.0.14] - 2026-03-22

### Changed
- Require **Python 3.11+** (dropped 3.10; transitive `onnxruntime` does not
  ship supported wheels for 3.10).
- CLI refactored into focused submodules (`cli_app`, `cli_livekit`,
  `cli_params`, `cli_reporter`, `cli_types`, `cli_dashboard`).
- Added `ProviderValue` type alias (`str | object`) for STT/LLM/TTS slots;
  exported from the public package surface.
- `SharedLiveKitWorkerOptions` dataclass bundles worker hand-off options.
- Provider serialisation registry (`_PROVIDER_REF_KEYS`) for spawn-safe
  round-trip of OpenAI plugin objects; OpenAI `NotGiven` sentinel detected
  without coupling to `repr()`.

---

## [0.0.13] - 2026-03-22

### Added
- Runtime CLI observability dashboard (`openrtc dev --dashboard`).
- Metrics JSONL stream: session lifecycle events written to a configurable
  `.jsonl` file for the TUI sidecar (`--metrics-jsonl`).
- Textual sidecar TUI (`openrtc tui`); optional install with
  `pip install 'openrtc[tui]'`.

### Fixed
- Leaked runtime session counters after session errors.

---

## [0.0.12] - 2026-03-21

### Added
- `AgentConfig.source_path` records the resolved path of the discovered module.
- Resource monitoring: `get_process_resident_set_info()` and
  `SavingsEstimate`; `pool.runtime_snapshot()` includes live memory data.
- Coverage gate enforced at 80% (`--cov-fail-under=80`).

---

## [0.0.11] - 2026-03-21

### Fixed
- `resource` module lazy-imported on Windows where `RUSAGE_SELF` is absent.

---

## [0.0.9] - 2026-03-21

### Added
- Agent resource monitoring via `PoolRuntimeSnapshot` and
  `RuntimeMetricsStore`.
- `pool.runtime_snapshot()` public method.
- `pool.drain_metrics_stream_events()` public method.

---

## [0.0.8] - 2026-03-21

### Fixed
- `PicklingError` for agent classes discovered from non-package modules in
  `dev` / spawn mode; `_AgentClassRef` now stores and resolves by file path.

---

## [0.0.5] - 2026-03-21

### Added
- `AgentPool.discover()` for automatic one-file-per-agent discovery.
- `@agent_config(name, stt, llm, tts, greeting)` decorator for per-agent
  metadata in discovered modules.
- Room-name prefix routing fallback.

### Fixed
- Worker callbacks made spawn-safe; `AgentPool` state serialised through
  `_PoolRuntimeState` for cross-process delivery.

---

## [0.0.2] - 2026-03-20

### Added
- Initial public release.
- `AgentPool` with `add()`, `remove()`, `get()`, `list_agents()`, and `run()`.
- Job and room metadata routing (`agent` / `demo` keys).
- Shared prewarm for Silero VAD and multilingual turn detector.
- `AgentSession` wired per call with per-agent STT/LLM/TTS providers.
- Greeting support via `session.generate_reply()`.
- `openrtc[cli]` optional extra for `rich`/`typer` CLI.
- PEP 561 `py.typed` marker shipped in the wheel.
