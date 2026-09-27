#!/usr/bin/env python3
"""Docs structure + house-style validator for OpenRTC.

The docs site (``web/docs/``, Fumadocs) renders the pages listed in ``meta.json``
here, in that order, from the files in this directory; ``web/docs/lib/source.ts``
names the same files for the build. Six rules, stdlib-only so the CI job needs no
dependency install:

1. Every page listed in ``meta.json`` has its file here, and ``source.ts`` names
   exactly those files.
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

import json
import re
import sys
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent
META = DOCS_DIR / "meta.json"
SOURCE_TS = DOCS_DIR.parent / "web" / "docs" / "lib" / "source.ts"

EM_DASH = "—"
PAGE_SUFFIXES = (".md", ".mdx")

# Internal notes that live beside the docs but are never published.
EXCLUDED_DIRS = frozenset({"design"})
EXCLUDED_FILES = frozenset({"audit-2026-05-02.md", "README.md"})
# Leading characters that force a YAML value to be quoted (rule 5).
_YAML_INDICATORS = "{[&*!|>%@`\"'#"

_SOURCE_FILES_RE = re.compile(r"files:\s*\[([^\]]*\.mdx?'[^\]]*)\]")
_QUOTED_RE = re.compile(r"'([^']+)'")
_LINK_RE = re.compile(r"\]\(\s*(/[^)\s]*)")
_HEADING_ANCHOR_RE = re.compile(r"^#{1,6}\s.*\{#[\w-]+\}")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")

Page = tuple[str, str]  # (href, file)


def read_meta_pages(path: Path = META) -> list[Page]:
    """Return ``(href, file)`` for each page in ``meta.json``, in its order.

    A page slug maps to ``<slug>.mdx`` or ``<slug>.md`` (whichever exists, ``.mdx``
    when neither does, so rule 1 names the missing file); ``index`` is served at ``/``.
    """
    pages: list[Page] = []
    for slug in json.loads(path.read_text(encoding="utf-8")).get("pages", []):
        name = f"{slug}.mdx"
        if (
            not (path.parent / name).is_file()
            and (path.parent / f"{slug}.md").is_file()
        ):
            name = f"{slug}.md"
        pages.append(("/" if slug == "index" else f"/{slug}/", name))
    return pages


def read_source_files(path: Path = SOURCE_TS) -> list[str]:
    """Return the page files ``source.ts`` hands the Fumadocs build."""
    match = _SOURCE_FILES_RE.search(path.read_text(encoding="utf-8"))
    return _QUOTED_RE.findall(match.group(1)) if match else []


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
            errors.append(f"meta.json: page '{href}' points at missing docs/{name}")
    listed = set(files)
    for file in sorted(docs_dir.rglob("*")):
        if file.suffix not in PAGE_SUFFIXES or not file.is_file():
            continue
        rel = file.relative_to(docs_dir)
        if not _is_excluded(rel) and file not in listed:
            errors.append(f"{rel.as_posix()}: not a page in meta.json (orphan)")
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


def check_docs(
    docs_dir: Path, pages: list[Page], source_files: list[str] | None = None
) -> list[str]:
    """Validate the docs in *docs_dir* against *pages*; return violations.

    *source_files*, when given, is the file list the site build reads; it must
    name exactly the listed pages.
    """
    errors: list[str] = []
    if not pages:
        return ["meta.json: no pages found"]
    if source_files is not None and sorted(source_files) != sorted(
        name for _, name in pages
    ):
        errors.append(
            "web/docs/lib/source.ts: its files list does not match docs/meta.json"
        )
    hrefs = {_normalize(href) for href, _ in pages}
    for file in _check_files(docs_dir, pages, errors):
        rel = file.relative_to(docs_dir).as_posix()
        text = file.read_text(encoding="utf-8")
        _check_links(rel, text, hrefs, errors)
        _check_frontmatter(rel, text, errors)
        _check_line_rules(rel, text, errors)
    return errors


def main() -> int:
    errors = check_docs(DOCS_DIR, read_meta_pages(), read_source_files())
    if errors:
        print(f"docs validation failed ({len(errors)} issue(s)):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("docs validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
