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
