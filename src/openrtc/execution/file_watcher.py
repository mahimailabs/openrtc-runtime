"""File watcher infrastructure for user agent code.

The watcher monitors user-edited Python modules and emits debounced
change events. Reload, re-import, and session re-binding are out of
scope here — see MAH-81 onward. This module provides the foundation:
discovery, event shape, and a callback API.

Public API (locked at design.md §3.5):

- :class:`FileChange` — frozen dataclass describing a single change
- :class:`FileWatcher` — async watcher with ``start()``/``stop()``/``refresh_paths()``
"""

from __future__ import annotations

import site
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ChangeType = Literal["created", "modified", "deleted"]


@dataclass(frozen=True)
class FileChange:
    """A single filesystem change event.

    Frozen so instances are hashable and can be deduplicated in sets.
    Paths are absolute. ``change_type`` is one of ``"created"``,
    ``"modified"``, or ``"deleted"`` (mapped from watchfiles' ``Change``
    enum at the watcher boundary).
    """

    path: Path
    change_type: ChangeType


def _interpreter_excluded_roots() -> list[Path]:
    """Return absolute directory roots whose contents are NOT user code.

    Modules whose ``__file__`` lives under any of these roots are
    interpreter, standard library, or third-party package code — not
    something a user would edit during a hot-reload session.
    """
    roots: list[Path] = [Path(path).resolve() for path in site.getsitepackages()]
    user_site = site.getusersitepackages()
    if user_site:
        roots.append(Path(user_site).resolve())
    roots.append(Path(sys.prefix).resolve())
    roots.append(Path(sys.base_prefix).resolve())
    # Deduplicate while preserving order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for root in roots:
        if root not in seen:
            seen.add(root)
            unique.append(root)
    return unique


def _is_under(path: Path, roots: list[Path]) -> bool:
    """Return True if *path* is at or below any of *roots*."""
    return any(path.is_relative_to(root) for root in roots)


def _discover_user_modules() -> list[Path]:
    """Snapshot ``sys.modules`` and return user-editable Python file paths.

    A module is "user-editable" when:

    1. It exposes a real ``__file__`` attribute (excludes built-ins,
       namespace packages, and some C extensions).
    2. The file is NOT under any interpreter or site-packages root
       returned by :func:`_interpreter_excluded_roots`.

    Returns absolute, deduplicated paths in module-iteration order.
    Modules without a ``__file__`` are skipped silently — that is the
    documented "graceful" behavior for built-ins.
    """
    excluded = _interpreter_excluded_roots()
    seen: set[Path] = set()
    discovered: list[Path] = []
    # Snapshot to a list to tolerate sys.modules mutation during iteration.
    for module in list(sys.modules.values()):
        file_attr = getattr(module, "__file__", None)
        if not file_attr:
            continue
        try:
            resolved = Path(file_attr).resolve()
        except (OSError, RuntimeError):
            # Resolving can fail on broken symlinks or weird platforms;
            # skip those rather than break discovery.
            continue
        if _is_under(resolved, excluded):
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        discovered.append(resolved)
    return discovered
