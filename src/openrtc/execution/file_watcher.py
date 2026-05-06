"""File watcher infrastructure for user agent code (MAH-80, v0.2.1).

The watcher monitors user-edited Python modules and emits debounced
change events. Reload, re-import, and session re-binding are out of
scope here — see MAH-81 onward. This module provides the foundation:
discovery, event shape, and a callback API.

Contract summary
----------------

- The watcher discovers user-editable modules from ``sys.modules`` at
  construction (when ``paths=None``) and ignores anything under
  ``site-packages`` / ``sys.prefix``.
- Filesystem events are consumed via ``watchfiles.awatch`` and mapped
  to :class:`FileChange` instances.
- Rapid events are coalesced through a trailing-edge debounce
  (``debounce_ms``, default 200) before the user callback fires, so
  multi-write editor saves produce a single dispatch.
- The user callback is awaited inside a try/except: exceptions are
  logged at ERROR and swallowed, leaving the watcher running.
- ``stop()`` cancels the in-flight watch and flush tasks, drops the
  pending buffer, and is safe to call repeatedly.

Public API (locked at design.md §3.5):

- :class:`FileChange` — frozen dataclass describing a single change
- :class:`FileWatcher` — async watcher with
  ``start()`` / ``stop()`` / ``refresh_paths()``

Both names are re-exported from the package root, so callers can write
``from openrtc import FileWatcher, FileChange``.
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
    Paths emitted by :class:`FileWatcher` are absolutized (via
    ``Path.resolve(strict=False)``) at the watcher boundary; instances
    constructed by callers directly carry whatever path they pass in.
    ``change_type`` is one of ``"created"``, ``"modified"``, or
    ``"deleted"`` (mapped from watchfiles' ``Change`` enum).
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
        """Construct a watcher; does not start watching until :meth:`start`.

        Args:
            on_change: Async callable invoked with the coalesced
                ``list[FileChange]`` after each debounce window.
                Exceptions raised by this callable are logged and
                swallowed.
            debounce_ms: Trailing-edge debounce window. Must be > 0.
            paths: Explicit list of files or directories to watch. When
                ``None`` (default), the watcher snapshots
                ``sys.modules`` and excludes anything under the
                interpreter / site-packages roots — :meth:`refresh_paths`
                only re-runs discovery in this auto-discover mode.

        Raises:
            ValueError: ``debounce_ms`` is not strictly positive.
        """
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
        # debounce flushes; _flush_task fires the trailing-edge flush.
        # _restart_event signals the watch loop to recreate awatch with
        # the latest self._paths after refresh_paths() mutates them.
        self._pending: list[FileChange] = []
        self._stop_event: asyncio.Event | None = None
        self._restart_event: asyncio.Event | None = None
        self._watch_task: asyncio.Task[None] | None = None
        self._flush_task: asyncio.Task[None] | None = None

    @property
    def paths(self) -> list[Path]:
        """Return the current snapshot of watched paths."""
        return list(self._paths)

    @property
    def state(self) -> WatcherState:
        """Return the current lifecycle state."""
        return self._state

    def refresh_paths(self) -> None:
        """Re-snapshot ``sys.modules`` for the auto-discover watcher.

        Side effects:
            - Replaces ``self._paths`` with a fresh discovery snapshot
              when the watcher was constructed with ``paths=None``.
              No-op when explicit paths were supplied (the caller owns
              the list).
            - When the watcher is running, sets ``_restart_event`` so
              the watch loop tears down the current ``awatch`` iterator
              and recreates it with the new path set on the next
              iteration boundary.

        Notes:
            Synchronous because rebuilding the path set is a fast
            in-process snapshot. The live recreate happens
            asynchronously in the watch loop, typically within a few
            milliseconds.
        """
        if not self._auto_discover:
            return
        self._paths = _discover_user_modules()
        if self._restart_event is not None:
            self._restart_event.set()

    async def start(self) -> None:
        """Begin watching. Idempotent.

        Side effects:
            Creates an ``asyncio.Event`` (``_stop_event``) and an
            ``asyncio.Task`` running :meth:`_run_watch_loop`, then
            transitions the state to ``running``.

        Raises:
            RuntimeError: Called after :meth:`stop`. A stopped watcher
                cannot be restarted; construct a new instance.

        Notes:
            A second call while ``running`` is a no-op (does not spawn
            a duplicate watch task).
        """
        if self._state == "running":
            return
        if self._state == "stopped":
            raise RuntimeError(
                "FileWatcher cannot be restarted after stop(); construct a new watcher.",
            )
        self._state = "running"
        self._stop_event = asyncio.Event()
        self._restart_event = asyncio.Event()
        self._watch_task = asyncio.create_task(
            self._run_watch_loop(),
            name=f"openrtc.file_watcher[{id(self):#x}]",
        )

    async def stop(self) -> None:
        """Stop watching. Idempotent and graceful.

        Side effects:
            - Transitions state to ``stopped`` (terminal — :meth:`start`
              will raise).
            - Sets ``_stop_event`` so ``watchfiles.awatch`` exits its
              async iterator.
            - Cancels and awaits the in-flight watch task and any
              pending flush task; ``CancelledError`` is suppressed.
            - Drops ``self._pending`` (any unflushed events are lost).

        Notes:
            Calling ``stop()`` on a fresh (never-started) watcher still
            moves it to ``stopped`` so the no-restart invariant holds.
            A pending debounce flush is cancelled without invoking the
            user callback.
        """
        if self._state == "stopped":
            return
        self._state = "stopped"
        if self._stop_event is not None:
            self._stop_event.set()
        if self._restart_event is not None:
            # Wake any awaiter blocked on the restart side of the mirror
            # task so the watch loop can observe stop.
            self._restart_event.set()
        if self._flush_task is not None:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task
            self._flush_task = None
        if self._watch_task is not None:
            self._watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watch_task
            self._watch_task = None
        self._stop_event = None
        self._restart_event = None
        self._pending.clear()

    async def _run_watch_loop(self) -> None:
        """Background task: consume ``watchfiles.awatch`` and feed the debounce.

        Wraps ``watchfiles.awatch`` in an outer loop so :meth:`refresh_paths`
        can swap the watched path set without restarting the whole
        watcher: when ``_restart_event`` fires, the inner ``awatch``
        iterator's ``stop_event`` is tripped, the loop tears it down,
        and the next iteration creates a fresh ``awatch`` over the
        latest ``self._paths``.

        Each batch from watchfiles is converted to ``FileChange``
        instances (with absolutized paths) and handed to
        :meth:`_handle_change_batch`, which extends ``self._pending``
        and (re)schedules the trailing flush.
        """
        assert self._stop_event is not None
        assert self._restart_event is not None
        while not self._stop_event.is_set():
            # Snapshot paths at iteration start. refresh_paths() mutates
            # self._paths and sets _restart_event; the next iteration
            # picks up the new list.
            current_paths = list(self._paths)
            iter_done = asyncio.Event()
            mirror = asyncio.create_task(
                self._mirror_signals(iter_done),
                name=f"openrtc.file_watcher.mirror[{id(self):#x}]",
            )
            try:
                if current_paths:
                    try:
                        async for changes in watchfiles.awatch(
                            *current_paths,
                            stop_event=iter_done,
                        ):
                            batch: list[FileChange] = []
                            for change_kind, raw_path in changes:
                                change_type = _WATCHFILES_CHANGE_MAP.get(change_kind)
                                if change_type is None:
                                    # watchfiles may add new variants;
                                    # ignore unknowns.
                                    continue
                                batch.append(
                                    FileChange(
                                        path=Path(raw_path).resolve(strict=False),
                                        change_type=change_type,
                                    )
                                )
                            if batch:
                                self._handle_change_batch(batch)
                    except asyncio.CancelledError:
                        raise
                    except Exception:  # noqa: BLE001 — logged and swallowed
                        _log.exception(
                            "FileWatcher loop crashed; events will stop firing",
                        )
                        return
                else:
                    # No paths to watch — wait for stop or restart.
                    await iter_done.wait()
            finally:
                mirror.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await mirror
            # Drain whichever signal triggered iter_done. If stop fired,
            # the while-condition exits us. Otherwise clear the restart
            # flag and loop back to recreate awatch over the new paths.
            if self._restart_event.is_set() and not self._stop_event.is_set():
                self._restart_event.clear()

    async def _mirror_signals(self, target: asyncio.Event) -> None:
        """Set *target* when either ``_stop_event`` or ``_restart_event`` fires.

        Used to translate the watcher's two lifecycle signals into the
        single ``stop_event`` that ``watchfiles.awatch`` accepts.
        """
        assert self._stop_event is not None
        assert self._restart_event is not None
        stop_wait = asyncio.create_task(self._stop_event.wait())
        restart_wait = asyncio.create_task(self._restart_event.wait())
        try:
            await asyncio.wait(
                {stop_wait, restart_wait},
                return_when=asyncio.FIRST_COMPLETED,
            )
            target.set()
        finally:
            for task in (stop_wait, restart_wait):
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

    def _handle_change_batch(self, batch: list[FileChange]) -> None:
        """Buffer one batch and (re)schedule the trailing debounce flush.

        Called from the watchfiles loop for each emitted batch and from
        unit tests directly. The semantics: extend ``_pending``, cancel
        any in-flight flush task, schedule a fresh flush
        ``debounce_ms / 1000`` seconds from now. If five rapid batches
        arrive, only the last reschedule survives — the prior four
        flush tasks are cancelled before they fire.
        """
        self._pending.extend(batch)
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
        self._flush_task = asyncio.create_task(
            self._flush_after(self._debounce_ms / 1000.0),
            name=f"openrtc.file_watcher.flush[{id(self):#x}]",
        )

    async def _flush_after(self, delay_s: float) -> None:
        """Wait *delay_s* seconds then flush ``_pending`` through ``on_change``.

        Cancellation before the timer fires drops the in-flight flush
        without firing the callback (used both by the debounce reschedule
        and by ``stop()`` for clean shutdown). Exceptions raised by the
        user callback are logged and swallowed so the watch loop keeps
        running for subsequent events.
        """
        try:
            await asyncio.sleep(delay_s)
        except asyncio.CancelledError:
            raise
        # Snapshot + clear under the same logical step. If new events
        # arrive while on_change is awaiting, _handle_change_batch will
        # schedule the next flush around them.
        collapsed = _collapse_changes(self._pending)
        self._pending.clear()
        if not collapsed:
            return
        try:
            await self._on_change(collapsed)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — user callback isolation
            _log.exception(
                "FileWatcher.on_change raised; continuing to watch",
            )


def _collapse_changes(changes: list[FileChange]) -> list[FileChange]:
    """Coalesce multiple events for the same path into one ``FileChange``.

    Per design.md §3.4, the salient state wins:

    - any ``deleted`` in the path's window → emit ``deleted`` (the file
      is gone now, regardless of intermediate states)
    - else any ``created`` in the window → emit ``created`` (the file is
      new; downstream consumers must register it for the first time)
    - otherwise → emit ``modified``

    Output preserves the first-seen order of paths in *changes*.
    """
    by_path: dict[Path, list[ChangeType]] = {}
    for change in changes:
        by_path.setdefault(change.path, []).append(change.change_type)
    collapsed: list[FileChange] = []
    for path, types in by_path.items():
        chosen: ChangeType
        if "deleted" in types:
            chosen = "deleted"
        elif "created" in types:
            chosen = "created"
        else:
            chosen = "modified"
        collapsed.append(FileChange(path=path, change_type=chosen))
    return collapsed
