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
