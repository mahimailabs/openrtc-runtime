#!/usr/bin/env python3
"""Docs structure + house-style validator for OpenRTC.

Gates the docs tree the way voicegateway's ``_check_docs.py`` does, adapted to
OpenRTC. Nine rules, run as a standalone CI job (not under the openrtc coverage
gate), stdlib-only so the job needs no dependency install:

1. ``docs.json`` parses and its ``navigation.tabs -> groups -> pages`` are non-empty.
2. Every nav page has a matching ``.md``/``.mdx`` file.
3. Every doc file is referenced exactly once (no orphans, no duplicates),
   excluding internal/archival directories and files.
4. Every internal ``/...`` link resolves to a nav page.
5. No em dash (U+2014) outside fenced code and inline code spans (house style).
6. No VitePress-only frontmatter keys (migration hygiene).
7. Non-empty ``title`` and ``description`` frontmatter on every page.
8. No ``{#custom-anchor}`` heading ids.
9. Frontmatter values containing ``": "`` (or a leading YAML indicator) are quoted.

``check_docs(docs_dir)`` returns the list of human-readable violations (empty =
clean) and is importable for tests; ``main(docs_dir)`` prints them and returns a
process exit code.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

DOCS_DIR = Path(__file__).resolve().parent

EM_DASH = "—"
PAGE_SUFFIXES = (".md", ".mdx")

# Directories whose files are documentation but never published nav pages, so
# they are exempt from the orphan check (rule 3) and content rules (5-9).
EXCLUDED_DIRS = frozenset(
    {
        "design",
        "superpowers",
        "diagrams",
        "public",
        "deployment",
        "announcements",
    }
)
# Individual internal/archival files at the docs root, exempt like the dirs above.
EXCLUDED_FILES = frozenset(
    {
        "assistant.md",
        "audit-2026-05-02.md",
        "release-v0.1.md",
        "README.md",
    }
)
# Frontmatter keys that only mean something to VitePress; a leftover here is a
# migration bug, since Mintlify ignores them silently.
VITEPRESS_KEYS = frozenset(
    {"layout", "outline", "aside", "titleTemplate", "editLink", "lastUpdated", "head"}
)
# Leading characters that force a YAML value to be quoted (rule 9).
_YAML_INDICATORS = "{[&*!|>%@`\"'#"

_LINK_RE = re.compile(r"\]\(\s*(/[^)\s]*)")
_HEADING_ANCHOR_RE = re.compile(r"^#{1,6}\s.*\{#[\w-]+\}")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")


def _load_docs_json(docs_dir: Path, errors: list[str]) -> dict[str, Any] | None:
    path = docs_dir / "docs.json"
    if not path.exists():
        errors.append("docs.json: file is missing")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"docs.json: invalid JSON ({exc})")
        return None
    if not isinstance(data, dict):
        errors.append("docs.json: top level must be an object")
        return None
    return data


def _nav_pages(data: dict[str, Any], errors: list[str]) -> list[str]:
    """Validate the tabs/groups/pages shape (rule 1) and return the page list."""
    navigation = data.get("navigation")
    tabs = navigation.get("tabs") if isinstance(navigation, dict) else None
    if not isinstance(tabs, list) or not tabs:
        errors.append("docs.json: navigation.tabs is missing or empty")
        return []
    pages: list[str] = []
    for tab in tabs:
        tab_name = tab.get("tab", "?") if isinstance(tab, dict) else "?"
        groups = tab.get("groups") if isinstance(tab, dict) else None
        if not isinstance(groups, list) or not groups:
            errors.append(f"docs.json: tab '{tab_name}' has no groups")
            continue
        for group in groups:
            group_name = group.get("group", "?") if isinstance(group, dict) else "?"
            group_pages = group.get("pages") if isinstance(group, dict) else None
            if not isinstance(group_pages, list) or not group_pages:
                errors.append(f"docs.json: group '{group_name}' has no pages")
                continue
            for page in group_pages:
                if isinstance(page, str):
                    pages.append(page)
                else:
                    errors.append(
                        f"docs.json: group '{group_name}' has a non-string page entry"
                    )
    return pages


def _resolve_page_file(docs_dir: Path, page: str) -> Path | None:
    for suffix in PAGE_SUFFIXES:
        candidate = docs_dir / f"{page}{suffix}"
        if candidate.exists():
            return candidate
    return None


def _is_excluded(rel: Path) -> bool:
    if rel.parts and rel.parts[0] in EXCLUDED_DIRS:
        return True
    return rel.name in EXCLUDED_FILES


def _check_pages(
    docs_dir: Path, pages: list[str], errors: list[str]
) -> dict[str, Path]:
    """Rules 2 and 3 (duplicates): resolve each nav page to a file."""
    resolved: dict[str, Path] = {}
    seen: set[str] = set()
    for page in pages:
        if page in seen:
            errors.append(
                f"docs.json: page '{page}' is referenced more than once (duplicate)"
            )
            continue
        seen.add(page)
        file = _resolve_page_file(docs_dir, page)
        if file is None:
            errors.append(f"{page}: nav page has no .md or .mdx file")
        else:
            resolved[page] = file
    return resolved


def _check_orphans(
    docs_dir: Path, resolved: dict[str, Path], errors: list[str]
) -> None:
    """Rule 3: every doc file is referenced by nav, unless explicitly excluded."""
    referenced = set(resolved.values())
    for file in sorted(docs_dir.rglob("*")):
        if file.suffix not in PAGE_SUFFIXES or not file.is_file():
            continue
        rel = file.relative_to(docs_dir)
        if _is_excluded(rel) or file in referenced:
            continue
        errors.append(
            f"{rel.as_posix()}: file is not referenced by any nav page (orphan)"
        )


def _check_internal_links(
    docs_dir: Path, resolved: dict[str, Path], errors: list[str]
) -> None:
    """Rule 4: internal ``/...`` links must resolve to a nav page."""
    nav_pages = set(resolved)
    for file in resolved.values():
        text = file.read_text(encoding="utf-8")
        for match in _LINK_RE.finditer(text):
            target = match.group(1).split("#", 1)[0].split("?", 1)[0].rstrip("/")
            normalized = target.lstrip("/")
            if not normalized:
                normalized = "index"
            first = normalized.split("/", 1)[0]
            last = normalized.rsplit("/", 1)[-1]
            if first in EXCLUDED_DIRS or "." in last:
                continue  # asset or excluded path, not a nav page
            if normalized not in nav_pages:
                errors.append(
                    f"{file.relative_to(docs_dir).as_posix()}: internal link "
                    f"'{match.group(1)}' does not resolve to a nav page"
                )


def _split_frontmatter(text: str) -> tuple[list[str] | None, int]:
    """Return the frontmatter lines (or None) and the 1-based body start line."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, 1
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return lines[1:index], index + 2
    return None, 1


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _parse_frontmatter(fm_lines: list[str]) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in fm_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        data[key.strip()] = value.strip()
    return data


def _check_frontmatter(rel: str, text: str, errors: list[str]) -> None:
    """Rules 6, 7, 9: VitePress keys, required fields, and quoting."""
    fm_lines, _ = _split_frontmatter(text)
    if fm_lines is None:
        errors.append(f"{rel}: page has no frontmatter block")
        return
    data = _parse_frontmatter(fm_lines)
    errors.extend(
        f"{rel}: VitePress-only frontmatter key '{key}'"
        for key in VITEPRESS_KEYS
        if key in data
    )
    errors.extend(
        f"{rel}: frontmatter is missing a non-empty '{field}'"
        for field in ("title", "description")
        if not _unquote(data.get(field, "")).strip()
    )
    for line in fm_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        value = raw_value.strip()
        if not value or value[0] in "\"'":
            continue
        if ": " in value or value[0] in _YAML_INDICATORS:
            errors.append(
                f"{rel}: frontmatter value for '{key.strip()}' must be quoted"
            )


def _check_line_rules(rel: str, text: str, errors: list[str]) -> None:
    """Rules 5 and 8: em dashes outside code, and custom heading anchors."""
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if EM_DASH in _INLINE_CODE_RE.sub("", line):
            errors.append(f"{rel}:{lineno}: em dash (U+2014) is banned outside code")
        if _HEADING_ANCHOR_RE.match(line):
            errors.append(f"{rel}:{lineno}: heading has a custom anchor id")


def check_docs(docs_dir: Path) -> list[str]:
    """Validate the docs tree at *docs_dir*; return violations (empty = clean)."""
    errors: list[str] = []
    data = _load_docs_json(docs_dir, errors)
    if data is None:
        return errors
    pages = _nav_pages(data, errors)
    resolved = _check_pages(docs_dir, pages, errors)
    _check_orphans(docs_dir, resolved, errors)
    _check_internal_links(docs_dir, resolved, errors)
    for file in resolved.values():
        rel = file.relative_to(docs_dir).as_posix()
        text = file.read_text(encoding="utf-8")
        _check_frontmatter(rel, text, errors)
        _check_line_rules(rel, text, errors)
    return errors


def main(docs_dir: Path | None = None) -> int:
    target = docs_dir if docs_dir is not None else DOCS_DIR
    errors = check_docs(target)
    if errors:
        print(f"docs validation failed ({len(errors)} issue(s)):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("docs validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
