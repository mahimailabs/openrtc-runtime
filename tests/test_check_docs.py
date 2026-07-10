"""Tests for the docs structure + house-style validator (docs/_check_docs.py).

The validator is a standalone script (run as its own CI job, not under the
openrtc coverage gate). It is written so ``check_docs(docs_dir)`` is importable
and testable against crafted temp docs trees, one perturbation per rule.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

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


_GOOD_PAGE = """\
---
title: Index
description: The landing page.
---

# Index

A clean page with no violations.
"""


def _write(tmp: Path, rel: str, content: str) -> Path:
    path = tmp / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _docs_json(tabs: list[dict[str, Any]]) -> dict[str, Any]:
    return {"navigation": {"tabs": tabs}}


def _one_tab(pages: list[str]) -> list[dict[str, Any]]:
    return [{"tab": "T", "groups": [{"group": "G", "pages": pages}]}]


def _clean_tree(tmp: Path, *, extra_pages: dict[str, str] | None = None) -> None:
    """Write a minimal clean docs tree: docs.json + one page per nav entry."""
    pages = ["index"]
    extra = extra_pages or {}
    pages.extend(extra)
    _write(tmp, "docs.json", json.dumps(_docs_json(_one_tab(pages))))
    _write(tmp, "index.md", _GOOD_PAGE)
    for name, content in extra.items():
        _write(tmp, f"{name}.md", content)


def test_clean_tree_has_no_violations(tmp_path: Path) -> None:
    _clean_tree(tmp_path)
    assert check_docs(tmp_path) == []


def test_rule1_empty_tabs_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "docs.json", json.dumps(_docs_json([])))
    _write(tmp_path, "index.md", _GOOD_PAGE)
    errors = check_docs(tmp_path)
    assert any("tab" in e.lower() for e in errors)


def test_rule1_group_with_no_pages_is_flagged(tmp_path: Path) -> None:
    tabs = [{"tab": "T", "groups": [{"group": "Empty", "pages": []}]}]
    _write(tmp_path, "docs.json", json.dumps(_docs_json(tabs)))
    errors = check_docs(tmp_path)
    assert any("page" in e.lower() for e in errors)


def test_rule2_nav_page_without_file_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "docs.json", json.dumps(_docs_json(_one_tab(["index", "ghost"]))))
    _write(tmp_path, "index.md", _GOOD_PAGE)
    errors = check_docs(tmp_path)
    assert any("ghost" in e for e in errors)


def test_rule3_orphan_file_is_flagged(tmp_path: Path) -> None:
    _clean_tree(tmp_path)
    _write(tmp_path, "stray.md", _GOOD_PAGE)  # on disk, not in nav
    errors = check_docs(tmp_path)
    assert any("orphan" in e.lower() and "stray" in e for e in errors)


def test_rule3_excluded_dirs_are_not_orphans(tmp_path: Path) -> None:
    _clean_tree(tmp_path)
    _write(tmp_path, "design/notes.md", "raw design note with no frontmatter")
    assert check_docs(tmp_path) == []


def test_rule3_duplicate_nav_page_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "docs.json", json.dumps(_docs_json(_one_tab(["index", "index"]))))
    _write(tmp_path, "index.md", _GOOD_PAGE)
    errors = check_docs(tmp_path)
    assert any("duplicate" in e.lower() for e in errors)


def test_rule4_broken_internal_link_is_flagged(tmp_path: Path) -> None:
    page = _GOOD_PAGE + "\nSee [routing](/concepts/routing) for more.\n"
    _clean_tree(tmp_path, extra_pages={"index2": page})
    # /concepts/routing is not a nav page -> broken internal link.
    errors = check_docs(tmp_path)
    assert any("/concepts/routing" in e for e in errors)


def test_rule4_resolving_internal_link_is_ok(tmp_path: Path) -> None:
    linker = _GOOD_PAGE + "\nSee [start](/getting-started).\n"
    _clean_tree(tmp_path, extra_pages={"getting-started": _GOOD_PAGE, "linker": linker})
    assert check_docs(tmp_path) == []


def test_rule5_em_dash_in_prose_is_flagged(tmp_path: Path) -> None:
    page = "---\ntitle: T\ndescription: D\n---\n\nText with an em dash — here.\n"
    _clean_tree(tmp_path, extra_pages={"emdash": page})
    errors = check_docs(tmp_path)
    assert any("em dash" in e.lower() and "emdash" in e for e in errors)


def test_rule5_em_dash_in_code_is_allowed(tmp_path: Path) -> None:
    page = (
        "---\ntitle: T\ndescription: D\n---\n\n"
        "Inline `a — b` is fine.\n\n```\nblock — dash\n```\n"
    )
    _clean_tree(tmp_path, extra_pages={"codeblock": page})
    assert check_docs(tmp_path) == []


def test_rule6_vitepress_key_is_flagged(tmp_path: Path) -> None:
    page = "---\ntitle: T\ndescription: D\nlayout: home\n---\n\n# T\n"
    _clean_tree(tmp_path, extra_pages={"vp": page})
    errors = check_docs(tmp_path)
    assert any("layout" in e for e in errors)


def test_rule7_missing_description_is_flagged(tmp_path: Path) -> None:
    page = "---\ntitle: Only Title\n---\n\n# T\n"
    _clean_tree(tmp_path, extra_pages={"nodesc": page})
    errors = check_docs(tmp_path)
    assert any("description" in e.lower() and "nodesc" in e for e in errors)


def test_rule7_empty_title_is_flagged(tmp_path: Path) -> None:
    page = "---\ntitle: ''\ndescription: D\n---\n\n# T\n"
    _clean_tree(tmp_path, extra_pages={"emptytitle": page})
    errors = check_docs(tmp_path)
    assert any("title" in e.lower() and "emptytitle" in e for e in errors)


def test_rule8_custom_anchor_is_flagged(tmp_path: Path) -> None:
    page = "---\ntitle: T\ndescription: D\n---\n\n## Section {#custom-id}\n"
    _clean_tree(tmp_path, extra_pages={"anchor": page})
    errors = check_docs(tmp_path)
    assert any("anchor" in e.lower() and "anchor" in e for e in errors)


def test_rule9_unquoted_colon_value_is_flagged(tmp_path: Path) -> None:
    # An unquoted description containing ": " breaks YAML parsing downstream.
    page = "---\ntitle: T\ndescription: Do this: then that\n---\n\n# T\n"
    _clean_tree(tmp_path, extra_pages={"colon": page})
    errors = check_docs(tmp_path)
    assert any("quote" in e.lower() and "colon" in e for e in errors)


def test_missing_docs_json_is_flagged(tmp_path: Path) -> None:
    errors = check_docs(tmp_path)
    assert any("docs.json" in e for e in errors)


def test_main_returns_zero_on_clean_tree(tmp_path: Path) -> None:
    _clean_tree(tmp_path)
    assert validator.main(tmp_path) == 0


def test_main_returns_one_on_dirty_tree(tmp_path: Path) -> None:
    _clean_tree(tmp_path)
    _write(tmp_path, "stray.md", _GOOD_PAGE)
    assert validator.main(tmp_path) == 1


def test_real_docs_pass_the_validator() -> None:
    # The shipped docs/ tree must validate clean (this is the CI gate in miniature).
    real_docs = Path(__file__).resolve().parents[1] / "docs"
    if not (real_docs / "docs.json").exists():  # pragma: no cover
        pytest.skip("docs.json not present")
    assert check_docs(real_docs) == []
