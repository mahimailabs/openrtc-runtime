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

import asyncio
import contextlib
import logging
import site
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import watchfiles

ChangeType = Literal["created", "modified", "deleted"]
WatcherState = Literal["new", "running", "stopped"]

_log = logging.getLogger(__name__)

_WATCHFILES_CHANGE_MAP: dict[watchfiles.Change, ChangeType] = {
    watchfiles.Change.added: "created",
    watchfiles.Change.modified: "modified",
    watchfiles.Change.deleted: "deleted",
}


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


class FileWatcher:
    """Watch user-edited Python modules and emit debounced change events.

    Public API is locked at design.md §3.5. The watcher is async-native:
    ``start()`` schedules a background watch task, ``stop()`` cancels
    it gracefully, and ``refresh_paths()`` rebuilds the auto-discovered
    path set without restarting.

    Lifecycle: a watcher transitions ``new → running → stopped``. A
    stopped watcher cannot be restarted — construct a new one.
    """

    def __init__(
        self,
        on_change: Callable[[list[FileChange]], Awaitable[None]],
        *,
        debounce_ms: int = 200,
        paths: list[Path] | None = None,
    ) -> None:
        if debounce_ms <= 0:
            raise ValueError(
                f"debounce_ms must be > 0, got {debounce_ms}.",
            )
        self._on_change = on_change
        self._debounce_ms = debounce_ms
        # ``paths is None`` → auto-discover, and refresh_paths() will
        # re-run discovery. Explicit paths short-circuit discovery.
        self._auto_discover = paths is None
        self._paths: list[Path] = (
            list(paths) if paths is not None else _discover_user_modules()
        )
        self._state: WatcherState = "new"
        # Filled in on start(). _pending collects changes between
        # debounce flushes; the trailing-edge debounce lands in Step 7.
        self._pending: list[FileChange] = []
        self._stop_event: asyncio.Event | None = None
        self._watch_task: asyncio.Task[None] | None = None

    @property
    def paths(self) -> list[Path]:
        """Return the current snapshot of watched paths."""
        return list(self._paths)

    @property
    def state(self) -> WatcherState:
        """Return the current lifecycle state."""
        return self._state

    def refresh_paths(self) -> None:
        """Re-discover user modules when constructed with ``paths=None``.

        No-op when explicit paths were supplied at construction (the
        caller manages that list). Synchronous because rebuilding the
        path set is a fast in-process snapshot; the live watcher loop
        picks up the change on its next event boundary.
        """
        if not self._auto_discover:
            return
        self._paths = _discover_user_modules()

    async def start(self) -> None:
        """Begin watching. Idempotent: a second call while running is a no-op.

        Raises ``RuntimeError`` if called after :meth:`stop` — construct
        a new watcher instead.
        """
        if self._state == "running":
            return
        if self._state == "stopped":
            raise RuntimeError(
                "FileWatcher cannot be restarted after stop(); construct a new watcher.",
            )
        self._state = "running"
        self._stop_event = asyncio.Event()
        self._watch_task = asyncio.create_task(
            self._run_watch_loop(),
            name=f"openrtc.file_watcher[{id(self):#x}]",
        )

    async def stop(self) -> None:
        """Stop watching. Idempotent: safe to call multiple times.

        Calling ``stop()`` on a fresh (never-started) watcher transitions
        it directly to ``stopped`` so the no-restart invariant still
        holds.
        """
        if self._state == "stopped":
            return
        self._state = "stopped"
        if self._stop_event is not None:
            self._stop_event.set()
        if self._watch_task is not None:
            self._watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watch_task
            self._watch_task = None
        self._stop_event = None

    async def _run_watch_loop(self) -> None:
        """Background task: consume ``watchfiles.awatch`` and buffer events.

        Step 6 lands the buffer; Step 7 swaps appends for the trailing
        debounce flush. Until then, every change just lands in
        ``self._pending`` so tests can verify the wiring.
        """
        if not self._paths:
            # No paths to watch — block until stop().
            assert self._stop_event is not None
            await self._stop_event.wait()
            return
        assert self._stop_event is not None
        try:
            async for changes in watchfiles.awatch(
                *self._paths,
                stop_event=self._stop_event,
            ):
                for change_kind, raw_path in changes:
                    change_type = _WATCHFILES_CHANGE_MAP.get(change_kind)
                    if change_type is None:
                        # watchfiles may add new variants; ignore unknowns.
                        continue
                    self._pending.append(
                        FileChange(
                            path=Path(raw_path),
                            change_type=change_type,
                        )
                    )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — logged and swallowed
            _log.exception("FileWatcher loop crashed; events will stop firing")
