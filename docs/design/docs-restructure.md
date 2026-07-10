# OpenRTC docs restructure: tabs + groups + validator

Status: **design / research (Loop 1)**. Not implemented.

## Goal

Move OpenRTC's docs from a flat, single-sidebar layout to voicegateway's proven shape: **horizontal tabs** (top-level sections) over **vertical groups** (sidebar, easy to advanced), with framework parity via `<Tabs>` and a Python **validator** that gates every page. When the pipecat backend lands, the docs must present "works with livekit and pipecat" cleanly.

## Current state

- OpenRTC uses the **old** Mintlify schema: `docs/mint.json` with `navigation: [{group, pages}]`. Four flat groups today: Get started, Concepts, Operations, Reference (21 pages).
- voicegateway uses the **new** schema: `docs/docs.json` with `navigation: {tabs: [{tab, groups: [{group, pages}]}]}`. Five tabs, ~70 pages, plus a 9-rule `docs/_check_docs.py`.

So this is a `mint.json -> docs.json` migration plus a re-grouping into tabs.

## Proposed tab structure

Four horizontal tabs (OpenRTC has no cloud/self-host split, so fewer than voicegateway's five):

```
Overview (TAB)
  Overview (GROUP): index, coming-from-livekit-agents, [frameworks - added with pipecat backend]

Guide (TAB)   <- the main developer journey, easy -> advanced
  Get started (GROUP): getting-started, examples
  Concepts (GROUP):    concepts/architecture, concepts/routing, concepts/hot-reload,
                       concepts/session-introspection, concepts/multi-tenancy, concepts/migration
  Operations (GROUP):  operations/deployments, operations/monitoring-deploys, operations/rollback,
                       compliance/audit-events, runbooks/debugging-density,
                       runbooks/onboarding-a-tenant, runbooks/tenant-incident

CLI (TAB)
  CLI (GROUP): cli, cli/top

Reference (TAB)
  Reference (GROUP): api/pool, benchmarks/density-v0.1, changelog
```

Rationale (mirrors voicegateway's arc):
- **Overview** = conceptual entry + the adoption front door ("Coming from livekit-agents"). When pipecat lands, add a **Frameworks** page here (the parity story).
- **Guide** = the sequential journey a developer walks: quickstart -> mental model (Concepts) -> running it in production (Operations). This is voicegateway's "Self-Host" tab pattern applied to OpenRTC.
- **CLI** and **Reference** = lookup tabs.

Files do not move; only `mint.json` -> `docs.json` grouping changes, so every cross-link keeps resolving (same discipline used in the last docs pass).

## Framework-agnostic docs treatment (ties to the backend work)

Once the pipecat backend exists, adopt voicegateway's exact pattern:

1. **A "Frameworks" page** (`concepts/frameworks` or top of Overview) stating the neutral-core model: `import openrtc` pulls no framework; `AgentPool(backend=...)` lazily imports the one you use; install `openrtc[livekit]` or `openrtc[pipecat]`. Include the support matrix (which features work on which backend, honestly: e.g. hot reload livekit-first).
2. **`<Tabs>` for divergent code** on every page that shows a pool being built: a "LiveKit" tab and a "Pipecat" tab, where the `AgentPool` / routing / tenancy calls are identical and only the agent/provider ceremony differs. This is voicegateway's highest-value convention: the reader picks their framework once and sees only relevant code.
3. Keep concept pages (routing, tenancy, deploys, introspection) **framework-neutral**; push framework specifics into the tabs.

## The validator (port + adapt `_check_docs.py`)

voicegateway's `docs/_check_docs.py` is a 9-rule gate. Port it, adapting rules to OpenRTC:

| Rule | voicegateway | OpenRTC adaptation |
| --- | --- | --- |
| 1 | `docs.json` shape: tabs -> groups -> pages non-empty | Same (after migrating to `docs.json`) |
| 2 | Every nav page has a `.md`/`.mdx` file | Same |
| 3 | Every file referenced exactly once (no orphans/dupes) | Same (exclude `design/`, `superpowers/`, `diagrams/`, `public/`, `deployment/`) |
| 4 | Internal `/...` links resolve to a nav page | Same |
| 5 | No deprecated API outside the migration page | OpenRTC has no deprecated-API sunset yet; **replace with a no-em-dash rule** (the project bans em dashes everywhere; flag the U+2014 character and fail, excluding fenced code and inline code spans) |
| 6 | No VitePress-only frontmatter keys | Same |
| 7 | Non-empty `title` + `description` frontmatter | Same |
| 8 | No `{#custom-anchor}` heading ids | Same |
| 9 | Quote frontmatter with `: ` or YAML indicators | Same |

The em-dash rule (rule 5 replacement) is a genuinely useful OpenRTC-specific check: it enforces the house style automatically and would have caught the LLM-authored em dash in the agent's own greeting had it been in docs. Wire the validator into CI (a `Validate docs` job alongside the existing `Validate mint.json`).

## Decision

**Proceed after the backend refactor is underway (or in parallel).** The tab structure is a clear readability win and low-risk (nav-only, files stay put). Do the `mint.json -> docs.json` migration + validator first (mechanical), then add the Frameworks page + Tabs when the pipecat backend gives them something to document. Do not add the Frameworks page before the pipecat backend exists (it would document vapor).

## Open questions

- **Schema migration timing.** Mintlify supports both `mint.json` and `docs.json`; confirm the deployed site (openrtc.mintlify.app) picks up `docs.json` cleanly and retire `mint.json` in the same PR.
- **Tab count.** Four tabs vs folding CLI into Reference (three tabs). Leaning four: CLI is a distinct, frequently-hit surface. Revisit if CLI stays only two pages.
- **Runbooks placement.** Under Operations (current plan) vs their own group. Leaning Operations; promote to a group only if the runbook count grows.
- **Validator strictness in CI.** Global structure rules (1-3) always; content rules (4-9) on changed pages per PR, all pages on a nightly/`main` gate (voicegateway's phased pattern).

## Task list for implementation (Loop 2)

1. Migrate `docs/mint.json` -> `docs/docs.json` with the four-tab structure above; delete `mint.json`; verify all 21 pages resolve.
2. Port `docs/_check_docs.py` with the adapted rules (including the no-em-dash rule); run it clean over the current docs.
3. Add a `Validate docs` CI job running the validator (replace/extend the current `Validate mint.json` job).
4. (With the pipecat backend) add the Frameworks page + convert code-bearing pages to `<Tabs>` (LiveKit / Pipecat); keep concept pages neutral.
5. Cross-link discipline: each Guide page ends with a "Next steps" `<CardGroup>` (voicegateway convention).
