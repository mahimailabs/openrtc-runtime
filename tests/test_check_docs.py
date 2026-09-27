"""Tests for the docs structure + house-style validator (docs/_check_docs.py).

The validator is a standalone script (run as its own CI job). ``check_docs`` is
importable and tested against crafted temp docs trees, one perturbation per rule.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_MODULE_PATH = Path(__file__).resolve().parents[1] / "docs" / "_check_docs.py"


def _load_validator() -> Any:
    spec = importlib.util.spec_from_file_location("_check_docs", _MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load_validator()
check_docs = validator.check_docs

PAGES = [("/", "index.mdx"), ("/cli/", "cli.mdx")]

_GOOD_PAGE = """\
---
title: "Index"
description: "The landing page."
---

A clean page. See the [CLI](/cli/) and [its flags](/cli#flags).
"""


def _write(tmp: Path, rel: str, content: str) -> Path:
    path = tmp / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _clean_tree(tmp: Path, index: str = _GOOD_PAGE) -> None:
    _write(tmp, "index.mdx", index)
    _write(tmp, "cli.mdx", _GOOD_PAGE.replace("Index", "CLI"))


def test_clean_tree_has_no_violations(tmp_path: Path) -> None:
    _clean_tree(tmp_path)
    assert check_docs(tmp_path, PAGES) == []


def test_no_pages_is_flagged(tmp_path: Path) -> None:
    assert check_docs(tmp_path, []) == ["site.ts: no pages found"]


def test_rule1_listed_page_without_file_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "index.mdx", _GOOD_PAGE)
    errors = check_docs(tmp_path, PAGES)
    assert any("missing docs/cli.mdx" in e for e in errors)


def test_rule2_orphan_file_is_flagged(tmp_path: Path) -> None:
    _clean_tree(tmp_path)
    _write(tmp_path, "stray.md", _GOOD_PAGE)
    errors = check_docs(tmp_path, PAGES)
    assert any("orphan" in e and "stray" in e for e in errors)


def test_rule2_internal_notes_are_not_orphans(tmp_path: Path) -> None:
    _clean_tree(tmp_path)
    _write(tmp_path, "design/notes.md", "raw design note with no frontmatter")
    _write(tmp_path, "audit-2026-05-02.md", "archived audit")
    assert check_docs(tmp_path, PAGES) == []


def test_rule3_broken_internal_link_is_flagged(tmp_path: Path) -> None:
    _clean_tree(tmp_path, _GOOD_PAGE + "\nSee [routing](/concepts/routing).\n")
    errors = check_docs(tmp_path, PAGES)
    assert any("/concepts/routing" in e for e in errors)


def test_rule3_asset_link_is_ignored(tmp_path: Path) -> None:
    _clean_tree(tmp_path, _GOOD_PAGE + "\n![top](/openrtc-top.svg)\n")
    assert check_docs(tmp_path, PAGES) == []


def test_rule4_em_dash_in_prose_is_flagged(tmp_path: Path) -> None:
    _clean_tree(tmp_path, _GOOD_PAGE + "\nOne pool — many agents.\n")
    errors = check_docs(tmp_path, PAGES)
    assert any("em dash" in e for e in errors)


def test_rule4_em_dash_in_code_is_allowed(tmp_path: Path) -> None:
    page = _GOOD_PAGE + "\nUse `a — b`.\n\n```text\nx — y\n```\n"
    _clean_tree(tmp_path, page)
    assert check_docs(tmp_path, PAGES) == []


def test_rule5_missing_frontmatter_is_flagged(tmp_path: Path) -> None:
    _clean_tree(tmp_path, "No frontmatter here.\n")
    errors = check_docs(tmp_path, PAGES)
    assert any("no frontmatter" in e for e in errors)


def test_rule5_missing_description_is_flagged(tmp_path: Path) -> None:
    _clean_tree(tmp_path, '---\ntitle: "Index"\n---\n\nBody.\n')
    errors = check_docs(tmp_path, PAGES)
    assert any("'description'" in e for e in errors)


def test_rule5_unquoted_colon_value_is_flagged(tmp_path: Path) -> None:
    page = '---\ntitle: "Index"\ndescription: Pool: one worker\n---\n\nBody.\n'
    _clean_tree(tmp_path, page)
    errors = check_docs(tmp_path, PAGES)
    assert any("must be quoted" in e for e in errors)


def test_rule6_custom_anchor_is_flagged(tmp_path: Path) -> None:
    _clean_tree(tmp_path, _GOOD_PAGE + "\n## Routing {#routing}\n")
    errors = check_docs(tmp_path, PAGES)
    assert any("custom anchor" in e for e in errors)


def test_read_site_pages_parses_site_ts(tmp_path: Path) -> None:
    site_ts = _write(
        tmp_path,
        "site.ts",
        "export const PAGES = [\n"
        "  { href: '/', label: 'Why', file: 'index.mdx' },\n"
        "  { href: '/cli/', label: 'CLI', file: 'cli.mdx' },\n"
        "];\n",
    )
    assert validator.read_site_pages(site_ts) == PAGES


def test_main_reports_violations(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(validator, "DOCS_DIR", tmp_path)
    monkeypatch.setattr(validator, "read_site_pages", lambda: PAGES)
    _write(tmp_path, "index.mdx", _GOOD_PAGE)
    assert validator.main() == 1
    _write(tmp_path, "cli.mdx", _GOOD_PAGE)
    assert validator.main() == 0


def test_real_docs_pass_the_validator() -> None:
    errors = check_docs(validator.DOCS_DIR, validator.read_site_pages())
    assert errors == []
