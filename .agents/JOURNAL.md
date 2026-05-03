# OpenRTC-Python v0.1 — Implementation Journal

Append-only log. One entry per Ralph Loop iteration. Newest entries
at the bottom.

---

## 2026-05-03 06:35 UTC — refactor: delete v0.1 Phase 0 dead code
Files: src/openrtc/_version.py (deleted, was 3 LOC, untracked .gitignore entry),
       src/openrtc/pool.py (-19 LOC: removed `_resolve_agent` and `_handle_session`),
       src/openrtc/cli_app.py (-4 LOC: dropped underscore re-exports from imports + `__all__`),
       tests/test_routing.py (+1 import; 14 call-site rewrites to module-level helpers),
       tests/test_pool.py (5 call-site rewrites to `pool_module._run_universal_session`),
       tests/test_cli.py (1 import path rewrite cli_app -> cli_livekit).
Tests: 130/130 pass. ruff: clean. mypy: clean.
Notes: Test rewrites are the explicit behavior change required by this
task (PROMPT.md exception). Tests now call module-level
`_resolve_agent_config(pool._agents, ctx)` and
`_run_universal_session(pool._runtime_state, ctx)` directly — same
coverage, no wrapper layer. Branch override: staying on
feat/light-websocket per user instruction (overrides PROMPT.md
v0.1/<slug> convention).

## 2026-05-03 06:48 UTC — refactor: rename provider_types.py to types.py
Files: git mv src/openrtc/provider_types.py -> src/openrtc/types.py,
       src/openrtc/__init__.py (1 import path),
       src/openrtc/pool.py (1 import path; ruff-fixed import order),
       src/openrtc/cli_params.py (1 import path),
       tests/test_cli.py (1 import path; ruff-fixed import order),
       README.md, CLAUDE.md (doc references).
Tests: 130/130 pass. ruff: clean. mypy: clean.
Notes: Pure rename per Phase 0 refactor rules (no behavior change).
Used `git mv` so blame is preserved. ruff auto-fix reordered the now-
alphabetically-misplaced imports in pool.py and tests/test_cli.py.
docs/audit-2026-05-02.md left unchanged (historical snapshot).

## 2026-05-03 07:00 UTC — refactor: move pool.py into core/ package
Files: src/openrtc/core/__init__.py (new, empty),
       git mv src/openrtc/pool.py -> src/openrtc/core/pool.py,
       6 src import sites (__init__.py, cli_app.py, cli_dashboard.py,
       cli_livekit.py, cli_reporter.py, cli_params.py docstring,
       resources.py TYPE_CHECKING block),
       4 test sites (test_pool.py: 5 patterns; test_routing.py: 2;
       test_resources.py: 1; conftest.py docstring),
       README.md (project tree), CLAUDE.md, CONTRIBUTING.md.
Tests: 130/130 pass. ruff: clean (auto-fixed 2 import-order issues
in cli_app.py and cli_reporter.py). mypy: clean.
Notes: No behavior change. `from openrtc import AgentPool` still
works because __init__.py re-exports from .core.pool. All
monkeypatch path strings updated from "openrtc.pool.X" to
"openrtc.core.pool.X". docs/audit-2026-05-02.md historical paths
left as-is.

## 2026-05-03 07:15 UTC — refactor: extract core/config.py from pool.py
Files: src/openrtc/core/config.py (new, 158 LOC),
       src/openrtc/core/pool.py (-126 LOC: removed AgentConfig,
       AgentDiscoveryConfig, agent_config, _normalize_optional_name,
       _AgentType TypeVar, _AGENT_METADATA_ATTR; added imports +
       __all__ for stable internal surface),
       src/openrtc/__init__.py (split AgentPool import from the
       config types), src/openrtc/cli_dashboard.py,
       src/openrtc/cli_livekit.py, src/openrtc/resources.py
       (TYPE_CHECKING block) — all updated to import from
       core.config.
Tests: 130/130 pass. ruff: clean. mypy: clean.
Notes: AgentConfig.__post_init__/__getstate__/__setstate__ use
late imports of _serialize_provider_value, _deserialize_provider_value,
_build_agent_class_ref, _resolve_agent_class to avoid a circular
import with core.pool. These late imports are temporary — they
collapse to module-level imports when core/serialization.py is
extracted in the next refactor task. Comment in the file explains.
Public API unchanged.

## 2026-05-03 07:30 UTC — refactor: extract core/routing.py from pool.py
Files: src/openrtc/core/routing.py (new, 91 LOC: _resolve_agent_config,
       _agent_name_from_metadata, _agent_name_from_mapping,
       _get_registered_agent, _METADATA_AGENT_KEYS),
       src/openrtc/core/pool.py (-77 LOC: removed those functions and
       the constant; now imports _resolve_agent_config from .routing.
       ruff auto-removed the unused json import.),
       tests/test_routing.py (split the import — _resolve_agent_config
       now from openrtc.core.routing, _run_universal_session still
       from openrtc.core.pool).
Tests: 130/130 pass. ruff: clean. mypy: clean.
Notes: routing.py imports AgentConfig from core.config (no cycle)
and JobContext from livekit.agents. _run_universal_session in
pool.py keeps using _resolve_agent_config via the new import.
Public API unchanged.

## 2026-05-03 07:50 UTC — refactor: extract core/discovery.py from pool.py
Files: src/openrtc/core/discovery.py (new, 89 LOC: _load_module_from_path,
       _discovered_module_name, _try_get_module_path,
       _load_agent_module, _find_local_agent_subclass,
       _resolve_discovery_metadata),
       src/openrtc/core/pool.py (-86 LOC: removed three module-level
       loaders and three former AgentPool methods; added imports from
       .discovery; AgentPool.discover() now calls free functions.
       ruff auto-removed inspect, sys, hashlib.sha1, typing.cast,
       _AGENT_METADATA_ATTR, _discovered_module_name unused imports),
       tests/test_pool.py (added `import openrtc.core.discovery as
       discovery_module`; rewrote 5 references from pool_module.X to
       discovery_module.X for the moved symbols).
Tests: 130/130 pass. ruff: clean. mypy: clean.
Notes: The three former AgentPool instance methods
(_resolve_discovery_metadata, _load_agent_module,
_find_local_agent_subclass) are now free functions — none of them
used `self`, so the conversion is mechanical and behavior-preserving.
_resolve_discovery_metadata dropped the unused `module` parameter
along the way (only agent_cls is read). Public API unchanged.

## 2026-05-03 08:10 UTC — refactor: extract core/serialization.py from pool.py
Files: src/openrtc/core/serialization.py (new, 188 LOC: _AgentClassRef,
       _ProviderRef, _PROVIDER_REF_KEYS, _OPENAI_NOT_GIVEN_TYPE,
       _serialize_provider_value, _deserialize_provider_value,
       _try_build_provider_ref, _extract_provider_kwargs,
       _filter_provider_kwargs, _is_not_given, _build_agent_class_ref,
       _resolve_agent_class, _resolve_qualname),
       src/openrtc/core/pool.py (~150 LOC removed: all the serialization
       block plus the openai NotGiven import; ruff auto-removed the
       now-unused ModuleType import after fixup),
       src/openrtc/core/config.py (TYPE_CHECKING block dropped; late
       imports inside __post_init__/__getstate__/__setstate__ collapsed
       to module-level imports from core.serialization. Also picked up
       _resolve_discovery_metadata from discovery.py — see below.),
       src/openrtc/core/discovery.py (dropped _resolve_discovery_metadata
       and the now-unused `cast`, `_AGENT_METADATA_ATTR`,
       `AgentDiscoveryConfig` imports — required to break a new cycle
       config -> serialization -> discovery -> config),
       tests/test_pool.py (added `import openrtc.core.serialization as
       serialization_module`; rewrote 3 references plus the
       `from openrtc.core.pool import _is_not_given` to point at the
       new module).
Tests: 130/130 pass. ruff: clean. mypy: clean.
Notes: serialization.py uses `importlib.import_module("pickle")` for
the spawn-safety probe so the behavior matches what pool.py already
did. The `_resolve_discovery_metadata` function moved out of
discovery.py and into config.py because it only reads
`_AGENT_METADATA_ATTR` and returns `AgentDiscoveryConfig` — both
already in config.py. This kept the import graph acyclic
(config -> serialization -> discovery; pool depends on all three).
Public API unchanged. Note: the previous iteration's commit
(b1d9307) shipped the code already; this entry catches the journal
up after a hook blocked the inline edit.

## 2026-05-03 12:08 UTC — feat(pool): plumb max_concurrent_sessions (no behavior yet)
Files: src/openrtc/core/pool.py (new keyword-only
       max_concurrent_sessions: int = 50 on AgentPool.__init__;
       eager type/value validation; new max_concurrent_sessions
       property),
       tests/test_pool.py (5 new tests: default 50, override,
       rejects float, rejects bool, rejects 0/negative).
Tests: 138/138 pass (5 new). ruff: clean. mypy: clean.
Notes: Pure plumbing per the TODO. Stored in
self._max_concurrent_sessions and exposed read-only via the
property. Matches design §5.1's documented public knob; also
notes in the docstring that it is a coroutine-mode concept and
ignored in process mode (livekit-agents owns that load math).
The bool guard rejects True/False because bool is a subclass of
int and would otherwise sneak past isinstance(..., int).

## 2026-05-03 11:55 UTC — feat(pool): plumb `isolation` parameter (no behavior yet)
Files: src/openrtc/core/pool.py (+ Literal import; new module-level
       IsolationMode = Literal["coroutine", "process"]; new isolation
       kwarg on AgentPool.__init__ defaulting to "coroutine";
       validation that rejects unknown values; new `isolation`
       property; __all__ extended with IsolationMode),
       tests/test_pool.py (3 new tests: default is coroutine,
       process accepted, unknown raises ValueError).
Tests: 133/133 pass (3 new). ruff: clean. mypy: clean.
Notes: Pure plumbing per the TODO. The setting is stored and
exposed via `pool.isolation` but nothing in the runtime branches
on it yet — that arrives when CoroutinePool lands. Default flips
the v0.0.x behavior (process) to v0.1's coroutine, matching design
§5.4. Public surface intentionally NOT extended in __init__.py
since users only pass strings; the IsolationMode type alias is
available via `from openrtc.core.pool import IsolationMode` for
type-aware callers but not promoted to the package level.

## 2026-05-03 11:42 UTC — docs: capture AgentServer integration points
Files: docs/design/agent-server-integration.md (new, ~150 LOC).
Tests: not run (docs-only).
Notes: Read worker.py (1435 LOC) and grepped every _proc_pool.X
access. Captured:
  - the construction site (line 587, inside run() under self._lock);
    importantly _proc_pool is NOT set in __init__, so a subclass
    cannot swap it before run() executes,
  - the 12 unique call sites (3 event listeners, start, 2
    set_target_idle_processes calls, processes property, drain
    loop, 3 launch_job sites including simulate_job and the live
    dispatch path, aclose, get_by_job_id),
  - the lifecycle ordering inside run(), drain(timeout), and
    aclose(),
  - how _update_job_status maps our JobStatus enum to the WS
    UpdateJobStatus message,
  - three swap strategies (module-level class substitution,
    AgentServer subclass with run() override, hybrid). Picked
    strategy A for the first prototype: monkey-patch
    livekit.agents.ipc.proc_pool.ProcPool to our CoroutinePool
    before AgentServer.run() executes. Smallest diff, matches the
    "contained to one file" goal in design §6.4.
Closes the 3-doc reading group; implementation work starts next.

## 2026-05-03 11:25 UTC — docs: capture ProcPool surface AgentServer uses
Files: docs/design/proc-pool-surface.md (new, ~120 LOC).
Tests: not run (docs-only).
Notes: Read the full proc_pool.py (256 LOC) and grepped
worker.py for every _proc_pool.X access. Documented:
  - the verbatim ProcPool(__init__ ...) keyword shape AgentServer
    uses at worker.py:587-601 (so CoroutinePool can swap in),
  - per-arg coroutine-mode treatment (which kwargs become no-ops),
  - the 6 methods AgentServer actually calls (start, aclose,
    launch_job, set_target_idle_processes, processes,
    get_by_job_id) plus the .running_job iteration pattern,
  - the 5 EventTypes; only 3 have live worker.py subscribers today
    (process_started, process_closed, process_job_launched) but
    we'll emit all 5 for forward compatibility,
  - lifecycle invariants (idempotent start/aclose, MAX_ATTEMPTS=3
    retry in launch_job, target_idle_processes math), and
  - the consequences for our CoroutinePool (singleton JobProcess,
    one setup_fnc invocation, event ordering).
Complements docs/design/job-executor-protocol.md from the previous
iteration; the two together form the contract for the upcoming
implementation work.

## 2026-05-03 11:08 UTC — docs: capture JobExecutor Protocol surface
Files: docs/design/job-executor-protocol.md (new, ~120 LOC).
Tests: not run (docs-only).
Notes: Read
.venv/lib/python3.13/site-packages/livekit/agents/ipc/job_executor.py
(45 LOC) at the pinned 1.5.0 release, plus its proc_pool.py
neighbor (256 LOC), and wrote a contract reference for our
upcoming CoroutineJobExecutor + CoroutinePool. Captures: the
verbatim Protocol body, a method-by-method contract table, the
RunningJobInfo dataclass shape that launch_job receives, and the
ProcPool surface AgentServer expects (so CoroutinePool can be a
drop-in replacement). Includes implementation notes (event names
to emit, JobStatus mapping for cancellation, running_job
semantics).

## 2026-05-03 10:55 UTC — chore: pin livekit-agents~=1.5 (Phase 1 task 1)
Files: pyproject.toml (~=1.4 -> ~=1.5 on the
       livekit-agents[openai,silero,turn-detector] dependency),
       uv.lock (refreshed via `uv lock`; livekit-agents stays
       resolved at 1.5.0, the version we already had installed).
Tests: 130/130 pass. ruff: clean. mypy: clean.
Notes: Per docs/design/v0.1.md §9.1 we are about to subclass and
patch internal-ish parts of livekit-agents (_proc_pool field and
the JobExecutor Protocol), so the floor needs to match the version
we are actually building against. ~=1.5 still allows the 1.5.x
patch line and any future 1.6+ minors up to <2.0; the design also
calls for a CI canary job (separate task) that runs against the
latest livekit-agents release.

## 2026-05-03 10:42 UTC — verify: full test suite + coverage gate (Phase 0 complete)
Files: none changed (verification-only iteration).
Tests: `uv run pytest --cov=openrtc --cov-report=term-missing
--cov-fail-under=80` -> 130/130 pass, total coverage 90.31% (CI
gate 80%).
Notes: Closes Phase 0. Per-module coverage highlights:
  - core/: pool 92%, config 97%, discovery 98%, serialization 98%,
    routing 75%, turn_handling 88%
  - cli/: entry 100%, params 100%, types 100%, commands 93%,
    livekit 86%, reporter 86%, dashboard 82%, __init__ 54% (the
    dunder __getattr__ + missing-extra branch is intentionally
    untested; needs an environment without typer/rich)
  - observability/: snapshot 100%, stream 100%, metrics 84%
  - tui/app 100%
  - openrtc/__init__ 80% (the PackageNotFoundError fallback runs
    only outside an installed environment)
Phase 0 reorganization is finished: 11 file moves/extractions,
3 verification gates all green. Phase 1 (coroutine pool prototype)
starts next.

## 2026-05-03 10:30 UTC — verify: openrtc dev / list / tui CLI still work
Files: none changed (verification-only iteration).
Tests: not re-run (covered last iteration). Smoke commands:
  - `uv run openrtc --help`: top-level help renders; lists list,
    start, dev, console, connect, download-files, tui.
  - `uv run openrtc dev --help`: command resolves; OpenRTC option
    panel renders (--agents-dir, --default-stt, etc.).
  - `uv run openrtc tui --help`: command resolves; --watch option
    documented with default openrtc-metrics.jsonl.
  - `uv run openrtc list ./examples/agents
       --default-stt openai/gpt-4o-mini-transcribe
       --default-llm openai/gpt-4.1-mini
       --default-tts openai/gpt-4o-mini-tts`: end-to-end success;
    Rich table prints both example agents (dental, restaurant) with
    their string providers.
Notes: This is the same smoke check `make dev` runs. The `openrtc`
console-script entrypoint resolves through the new `openrtc.cli`
package and the renamed `openrtc.cli.commands` module (was
`cli_app.py`); discovery still loads agents from
`examples/agents/`.

## 2026-05-03 10:18 UTC — verify: public surface still resolves after Phase 0
Files: none changed (verification-only iteration).
Tests: ran an explicit round-trip script (not committed) plus the
       full suite (130/130 pass; ruff and mypy clean).
Notes: Confirmed end-to-end after the Phase 0 reorganization:
  - `from openrtc import AgentPool, AgentConfig,
    AgentDiscoveryConfig, agent_config, ProviderValue,
    __version__` resolves.
  - The bound classes carry their canonical paths
    (`openrtc.core.pool.AgentPool`,
    `openrtc.core.config.AgentConfig`,
    `openrtc.core.config.AgentDiscoveryConfig`).
  - `AgentPool().add(...)` constructs an AgentConfig and
    list_agents()/get() round-trip.
  - The `@agent_config(name=..., greeting=...)` decorator attaches
    AgentDiscoveryConfig metadata under `__openrtc_agent_config__`.
  - `ProviderValue` resolves to `str | object` (TypeAlias).
The smoke script intentionally lives in /tmp because spawn-safety
guard rejects __main__-scoped agent classes without source files;
running via `python <file>` exercises the real path.

## 2026-05-03 10:05 UTC — refactor: move tui_app.py into tui/ package
Files: git mv src/openrtc/tui_app.py -> src/openrtc/tui/app.py
       (via temporary tui_pkg_new/ to dodge the file-vs-directory
       naming collision that bit the cli move),
       new src/openrtc/tui/__init__.py (empty package marker),
       src/openrtc/cli/commands.py (1 import: openrtc.tui_app
       -> openrtc.tui.app),
       tests/test_cli.py (3 import sites: 1 monkeypatch string,
       1 inline `import openrtc.tui_app as tu`, 1 inline
       `from openrtc.tui_app import MetricsTuiApp`),
       tests/test_tui_app.py (replace_all rewrote 14 inline
       `from openrtc.tui_app import ...` and 1
       `import openrtc.tui_app as tu`),
       README.md (project tree section), CLAUDE.md (sidecar mention).
Tests: 130/130 pass. ruff: clean. mypy: clean.
Notes: Pure rename per Phase 0 refactor rules. No behavior change.
Used `git mv` so blame is preserved on the moved module.

## 2026-05-03 09:50 UTC — refactor: move CLI modules into a cli/ package
Files: 7 git mv operations (via temporary cli_pkg_new/ to avoid the
       cli.py / cli/ file-vs-directory naming collision):
       cli.py -> cli/entry.py,
       cli_app.py -> cli/commands.py (renamed from app.py — see notes),
       cli_dashboard.py -> cli/dashboard.py,
       cli_livekit.py -> cli/livekit.py,
       cli_params.py -> cli/params.py,
       cli_reporter.py -> cli/reporter.py,
       cli_types.py -> cli/types.py.
       New: cli/__init__.py with main re-export and an eager `app`
       binding (with __getattr__ fallback when the [cli] extra is
       absent).
       Updated 4 internal cross-references inside cli/* files.
       Updated 4 test files (test_cli.py: many monkeypatch + import
       sites, test_cli_params.py: 1 import + docstring,
       test_metrics_stream.py: 1 import). Updated 4 docs/config
       references (docs/cli.md, README.md, CLAUDE.md,
       CONTRIBUTING.md).
Tests: 130/130 pass. ruff: clean. mypy: clean.
Notes: Deviation from the .agents/TODO.md target tree: cli_app.py
became cli/commands.py rather than cli/app.py. The TODO target
tree gives both `cli/__init__.py` and `cli/app.py`, but Python
treats `openrtc.cli.app` as both the submodule and the Typer
attribute the package re-exports — `from openrtc.cli import app`
returns the wrong thing depending on import order. Renaming the
submodule file removes the collision and lets the Typer instance
keep the natural `app` name. Behavior, public API, console-script
entrypoint (`openrtc.cli:main` in pyproject.toml) all preserved.

## 2026-05-03 09:20 UTC — refactor: extract observability/snapshot.py from metrics.py
Files: src/openrtc/observability/snapshot.py (new, 80 LOC:
       ProcessResidentSetInfo, SavingsEstimate, PoolRuntimeSnapshot
       and its to_dict),
       src/openrtc/observability/metrics.py (~75 LOC removed; added
       a re-import of the snapshot trio to keep
       openrtc.observability.metrics.PoolRuntimeSnapshot resolvable
       for any external user that already imports it from there),
       4 src import sites updated to the canonical
       openrtc.observability.snapshot path (cli_dashboard.py,
       core/pool.py, observability/stream.py — the latter previously
       imported from metrics, now from snapshot directly),
       5 tests rewired (conftest.py, test_cli.py,
       test_metrics_stream.py, test_resources.py, test_tui_app.py).
Tests: 130/130 pass. ruff: clean. mypy: clean.
Notes: Subtask 3 of 3 from the observability split. The split was
not strictly required by tests (metrics.py still re-exports the
snapshot types) but updating internal users to the canonical path
matches the Phase 0 refactor rule "Update all imports in one pass
per moved file." Public API unchanged.

## 2026-05-03 09:05 UTC — refactor: rename metrics_stream.py to observability/stream.py
Files: git mv src/openrtc/metrics_stream.py ->
       src/openrtc/observability/stream.py,
       5 src import sites (cli_types.py, cli_app.py, cli_reporter.py,
       tui_app.py: import + module docstring),
       2 test files (test_metrics_stream.py: 1 site,
       test_tui_app.py: 2 sites).
Tests: 130/130 pass. ruff: clean (auto-fixed 3 import-order issues
in tui_app.py and the two test files). mypy: clean.
Notes: Pure rename (subtask 2 of 3 from the observability split).
Used `git mv` so blame is preserved. Public API unchanged.

## 2026-05-03 08:55 UTC — refactor: rename resources.py to observability/metrics.py
Files: src/openrtc/observability/__init__.py (new, empty),
       git mv src/openrtc/resources.py ->
       src/openrtc/observability/metrics.py,
       2 src import sites (cli_dashboard.py, core/pool.py,
       metrics_stream.py — three actually),
       6 test sites (test_cli.py, test_metrics_stream.py: 2 places,
       test_resources.py: 2 lines, test_tui_app.py, conftest.py).
Tests: 130/130 pass. ruff: clean. mypy: clean.
Notes: Pure rename (subtask 1 of 3 from the observability split).
The dynamic import pattern in tests/test_metrics_stream.py:200
needed an additional rewrite (`from openrtc import resources as
resources_mod` -> `from openrtc.observability import metrics as
resources_mod`) since simple substring replace missed the
`from openrtc import resources` style. test_resources.py kept its
`resources_module` local alias (just rebound to the new module).
Public API unchanged.

## 2026-05-03 08:40 UTC — chore: split observability extraction into three subtasks
Files: .agents/TODO.md (one item replaced by three).
Tests: not run (TODO-only edit).
Notes: The TODO line "Create observability/ package. Rename
resources.py → observability/metrics.py, metrics_stream.py →
observability/stream.py. Extract PoolRuntimeSnapshot to
observability/snapshot.py." bundled three operations (one rename,
one rename, one extract+split) totaling ~600 LOC of file movement
and ~12 import sites — too large for one iteration per PROMPT.md.
Split into three sequential subtasks. Next iteration picks up the
first one.

## 2026-05-03 08:25 UTC — refactor: extract core/turn_handling.py from pool.py
Files: src/openrtc/core/turn_handling.py (new, 161 LOC:
       _DEPRECATED_TURN_HANDLING_KEYS, _build_session_kwargs,
       _default_turn_handling, _default_turn_detection,
       _supports_multilingual_turn_detection,
       _extract_deprecated_turn_options,
       _deprecated_turn_options_to_turn_handling,
       _merge_turn_handling),
       src/openrtc/core/pool.py (~140 LOC removed; added import
       from .turn_handling; dropped now-unused `os` and `warnings`
       imports).
Tests: 130/130 pass. ruff: clean. mypy: clean.
Notes: No tests needed updating. The existing patch site
`monkeypatch.setattr("openrtc.core.pool._build_session_kwargs", ...)`
in tests/test_pool.py:569 still works because pool.py imports the
symbol at module level — the patch replaces pool.py's local binding,
which is what `_run_universal_session` looks up at call time.
Public API unchanged.
