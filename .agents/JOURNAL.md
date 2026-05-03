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
