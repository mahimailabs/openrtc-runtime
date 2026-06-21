"""File watcher: discover user-edited Python modules and emit debounced change events."""

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
    """A single filesystem change event; frozen so instances are hashable."""

    path: Path
    change_type: ChangeType


def _interpreter_excluded_roots() -> list[Path]:
    """Return directory roots that contain interpreter, stdlib, and third-party code."""
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
    """Snapshot ``sys.modules`` and return absolute paths to user-editable Python files."""
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

    Lifecycle: ``new`` to ``running`` to ``stopped``. A stopped watcher cannot be
    restarted; construct a new one.
    """

    def __init__(
        self,
        on_change: Callable[[list[FileChange]], Awaitable[None]],
        *,
        debounce_ms: int = 200,
        paths: list[Path] | None = None,
    ) -> None:
        """Construct a watcher; does not start watching until :meth:`start`."""
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
        """Re-snapshot ``sys.modules`` and signal the watch loop to recreate ``awatch``."""
        if not self._auto_discover:
            return
        self._paths = _discover_user_modules()
        if self._restart_event is not None:
            self._restart_event.set()

    async def start(self) -> None:
        """Begin watching; idempotent. Raises ``RuntimeError`` if called after ``stop()``."""
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
        """Stop watching, cancel in-flight tasks, and drop unflushed events; idempotent."""
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
        """Background task: consume ``watchfiles.awatch`` and feed the debounce buffer.

        Wraps ``awatch`` in an outer loop so ``refresh_paths()`` can swap the path
        set mid-run: ``_restart_event`` trips the inner iterator, tears it down, and
        the next iteration creates a fresh ``awatch`` over the updated paths.
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
                    except Exception:  # noqa: BLE001 - logged and swallowed
                        _log.exception(
                            "FileWatcher loop crashed; events will stop firing",
                        )
                        return
                else:
                    # No paths to watch: wait for stop or restart.
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
        """Set *target* when either ``_stop_event`` or ``_restart_event`` fires."""
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
        """Buffer a batch and (re)schedule the trailing debounce flush."""
        self._pending.extend(batch)
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
        self._flush_task = asyncio.create_task(
            self._flush_after(self._debounce_ms / 1000.0),
            name=f"openrtc.file_watcher.flush[{id(self):#x}]",
        )

    async def _flush_after(self, delay_s: float) -> None:
        """Wait *delay_s* seconds then flush ``_pending`` through ``on_change``."""
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
        except Exception:  # noqa: BLE001 - user callback isolation
            _log.exception(
                "FileWatcher.on_change raised; continuing to watch",
            )


def _collapse_changes(changes: list[FileChange]) -> list[FileChange]:
    """Coalesce multiple events per path: deleted wins, then created, then modified."""
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
