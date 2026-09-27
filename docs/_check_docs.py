#!/usr/bin/env python3
"""Docs structure + house-style validator for OpenRTC.

The docs site (``web/docs/``) renders the pages listed in ``web/docs/src/lib/site.ts``
from the files in this directory. Six rules, stdlib-only so the CI job needs no
dependency install:

1. Every page listed in ``site.ts`` has its file here.
2. Every ``.md``/``.mdx`` file here is a listed page (no orphans), except the
   internal notes in ``design/`` and the archived files in ``EXCLUDED_FILES``.
3. Every internal ``/...`` link points at a listed page.
4. No em dash (U+2014) outside fenced code and inline code spans (house style).
5. Non-empty ``title`` and ``description`` frontmatter, quoted when the value
   contains ``": "`` or starts with a YAML indicator.
6. No ``{#custom-anchor}`` heading ids.

``check_docs(docs_dir, pages)`` returns the list of human-readable violations
(empty = clean) and is importable for tests; ``main()`` prints them and returns
a process exit code.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent
SITE_PAGES = DOCS_DIR.parent / "web" / "docs" / "src" / "lib" / "site.ts"

EM_DASH = "—"
PAGE_SUFFIXES = (".md", ".mdx")

# Internal notes that live beside the docs but are never published.
EXCLUDED_DIRS = frozenset({"design"})
EXCLUDED_FILES = frozenset({"audit-2026-05-02.md", "README.md"})
# Leading characters that force a YAML value to be quoted (rule 5).
_YAML_INDICATORS = "{[&*!|>%@`\"'#"

_PAGE_RE = re.compile(r"href:\s*'([^']+)'.*?file:\s*'([^']+)'")
_LINK_RE = re.compile(r"\]\(\s*(/[^)\s]*)")
_HEADING_ANCHOR_RE = re.compile(r"^#{1,6}\s.*\{#[\w-]+\}")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")

Page = tuple[str, str]  # (href, file)


def read_site_pages(path: Path = SITE_PAGES) -> list[Page]:
    """Return the ``(href, file)`` pairs listed in ``site.ts``."""
    return _PAGE_RE.findall(path.read_text(encoding="utf-8"))


def _normalize(href: str) -> str:
    path = href.split("#", 1)[0].split("?", 1)[0]
    return "/" + path.strip("/") + ("/" if path.strip("/") else "")


def _is_excluded(rel: Path) -> bool:
    if rel.parts and rel.parts[0] in EXCLUDED_DIRS:
        return True
    return rel.name in EXCLUDED_FILES


def _check_files(docs_dir: Path, pages: list[Page], errors: list[str]) -> list[Path]:
    """Rules 1 and 2: listed pages exist, and nothing else is published."""
    files: list[Path] = []
    for href, name in pages:
        file = docs_dir / name
        if file.is_file():
            files.append(file)
        else:
            errors.append(f"site.ts: page '{href}' points at missing docs/{name}")
    listed = set(files)
    for file in sorted(docs_dir.rglob("*")):
        if file.suffix not in PAGE_SUFFIXES or not file.is_file():
            continue
        rel = file.relative_to(docs_dir)
        if not _is_excluded(rel) and file not in listed:
            errors.append(f"{rel.as_posix()}: not a page in site.ts (orphan)")
    return files


def _check_links(rel: str, text: str, hrefs: set[str], errors: list[str]) -> None:
    """Rule 3: internal ``/...`` links point at a listed page."""
    for match in _LINK_RE.finditer(text):
        target = match.group(1)
        if "." in target.rsplit("/", 1)[-1].split("#", 1)[0]:
            continue  # a static asset, not a page
        if _normalize(target) not in hrefs:
            errors.append(f"{rel}: internal link '{target}' is not a docs page")


def _split_frontmatter(text: str) -> list[str] | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return lines[1:index]
    return None


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _check_frontmatter(rel: str, text: str, errors: list[str]) -> None:
    """Rule 5: required fields, and quoting."""
    fm_lines = _split_frontmatter(text)
    if fm_lines is None:
        errors.append(f"{rel}: page has no frontmatter block")
        return
    data: dict[str, str] = {}
    for line in fm_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        value = raw_value.strip()
        data[key.strip()] = value
        if (
            value
            and value[0] not in "\"'"
            and (": " in value or value[0] in _YAML_INDICATORS)
        ):
            errors.append(
                f"{rel}: frontmatter value for '{key.strip()}' must be quoted"
            )
    errors.extend(
        f"{rel}: frontmatter is missing a non-empty '{field}'"
        for field in ("title", "description")
        if not _unquote(data.get(field, "")).strip()
    )


def _check_line_rules(rel: str, text: str, errors: list[str]) -> None:
    """Rules 4 and 6: em dashes outside code, and custom heading anchors."""
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if EM_DASH in _INLINE_CODE_RE.sub("", line):
            errors.append(f"{rel}:{lineno}: em dash (U+2014) is banned outside code")
        if _HEADING_ANCHOR_RE.match(line):
            errors.append(f"{rel}:{lineno}: heading has a custom anchor id")


def check_docs(docs_dir: Path, pages: list[Page]) -> list[str]:
    """Validate the docs in *docs_dir* against *pages*; return violations."""
    errors: list[str] = []
    if not pages:
        return ["site.ts: no pages found"]
    hrefs = {_normalize(href) for href, _ in pages}
    for file in _check_files(docs_dir, pages, errors):
        rel = file.relative_to(docs_dir).as_posix()
        text = file.read_text(encoding="utf-8")
        _check_links(rel, text, hrefs, errors)
        _check_frontmatter(rel, text, errors)
        _check_line_rules(rel, text, errors)
    return errors


def main() -> int:
    errors = check_docs(DOCS_DIR, read_site_pages())
    if errors:
        print(f"docs validation failed ({len(errors)} issue(s)):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("docs validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
