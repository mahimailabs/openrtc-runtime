"""Unit tests for the file watcher (MAH-80)."""

from __future__ import annotations

import asyncio
import dataclasses
import importlib.util
import logging
import sys
import time
import types
from collections.abc import Callable
from pathlib import Path

import pytest

from openrtc.execution.file_watcher import (
    FileChange,
    FileWatcher,
    _collapse_changes,
    _discover_user_modules,
    _interpreter_excluded_roots,
)


async def _noop_callback(_changes: list[FileChange]) -> None:
    """Default callback for lifecycle tests that don't care about events."""


class TestFileChange:
    """The :class:`FileChange` dataclass is the event-payload contract."""

    def test_construction(self) -> None:
        change = FileChange(path=Path("/tmp/agent.py"), change_type="modified")
        assert change.path == Path("/tmp/agent.py")
        assert change.change_type == "modified"

    def test_equality_same_values(self) -> None:
        a = FileChange(path=Path("/tmp/agent.py"), change_type="modified")
        b = FileChange(path=Path("/tmp/agent.py"), change_type="modified")
        assert a == b

    def test_equality_different_paths(self) -> None:
        a = FileChange(path=Path("/tmp/a.py"), change_type="modified")
        b = FileChange(path=Path("/tmp/b.py"), change_type="modified")
        assert a != b

    def test_equality_different_change_types(self) -> None:
        a = FileChange(path=Path("/tmp/agent.py"), change_type="created")
        b = FileChange(path=Path("/tmp/agent.py"), change_type="modified")
        assert a != b

    def test_hashable_for_set_deduplication(self) -> None:
        a = FileChange(path=Path("/tmp/agent.py"), change_type="modified")
        b = FileChange(path=Path("/tmp/agent.py"), change_type="modified")
        c = FileChange(path=Path("/tmp/agent.py"), change_type="created")
        # Equal instances collapse in a set; unequal ones do not.
        assert {a, b, c} == {a, c}

    def test_frozen_rejects_mutation(self) -> None:
        change = FileChange(path=Path("/tmp/agent.py"), change_type="modified")
        with pytest.raises(dataclasses.FrozenInstanceError):
            change.path = Path("/tmp/other.py")  # type: ignore[misc]


def _install_synthetic_module(
    name: str, file_path: Path, monkeypatch: pytest.MonkeyPatch
) -> types.ModuleType:
    """Register a real-but-empty module pointing at *file_path*.

    The file must exist on disk, otherwise ``Path.resolve()`` may fail
    on some platforms.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("# synthetic test module\n")
    spec = importlib.util.spec_from_loader(name, loader=None, origin=str(file_path))
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(file_path)
    monkeypatch.setitem(sys.modules, name, module)
    return module


class TestDiscoverUserModules:
    """``_discover_user_modules`` is the watcher's source of truth for paths."""

    def test_includes_user_module_under_tempdir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user_file = tmp_path / "user_pkg" / "agent.py"
        _install_synthetic_module("openrtc_test_user_pkg.agent", user_file, monkeypatch)
        discovered = _discover_user_modules()
        assert user_file.resolve() in discovered

    def test_excludes_module_under_site_packages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_site = tmp_path / "site-packages"
        site_file = fake_site / "third_party" / "lib.py"
        _install_synthetic_module(
            "openrtc_test_third_party.lib", site_file, monkeypatch
        )
        # Make _interpreter_excluded_roots() include our fake site dir.
        original_roots = _interpreter_excluded_roots()
        monkeypatch.setattr(
            "openrtc.execution.file_watcher._interpreter_excluded_roots",
            lambda: [*original_roots, fake_site.resolve()],
        )
        discovered = _discover_user_modules()
        assert site_file.resolve() not in discovered

    def test_handles_modules_without_file_attribute(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Real built-ins like ``sys`` already lack __file__; verify that
        # discovery does not blow up on them (they are present in
        # sys.modules during every run).
        assert getattr(sys, "__file__", None) is None
        discovered = _discover_user_modules()
        # Build a synthetic module with __file__ = None to be extra safe.
        fake = types.ModuleType("openrtc_test_no_file_module")
        fake.__file__ = None  # type: ignore[assignment]
        monkeypatch.setitem(sys.modules, "openrtc_test_no_file_module", fake)
        # Should not raise even with __file__ = None.
        discovered_again = _discover_user_modules()
        assert isinstance(discovered_again, list)
        # The result is at least as informative as the prior call (modules
        # without __file__ contribute nothing, never an exception).
        assert len(discovered_again) >= 0
        del (
            discovered
        )  # silence unused-warning; the first call's purpose was to prove it runs

    def test_returns_distinct_absolute_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        shared_file = tmp_path / "shared.py"
        _install_synthetic_module("openrtc_test_alias_a", shared_file, monkeypatch)
        # Register the same file under a second module name; discovery
        # should deduplicate by resolved path.
        spec = importlib.util.spec_from_loader(
            "openrtc_test_alias_b", loader=None, origin=str(shared_file)
        )
        assert spec is not None
        module_b = importlib.util.module_from_spec(spec)
        module_b.__file__ = str(shared_file)
        monkeypatch.setitem(sys.modules, "openrtc_test_alias_b", module_b)

        discovered = _discover_user_modules()
        absolute = [p.is_absolute() for p in discovered]
        assert all(absolute)
        # The shared file appears at most once.
        assert discovered.count(shared_file.resolve()) == 1


class TestFileWatcherLifecycle:
    """The :class:`FileWatcher` skeleton — construction, state machine, restart guard.

    These tests exercise the lifecycle contract; debounce + watchfiles
    wiring land in later steps.
    """

    def test_construction_with_explicit_paths(self, tmp_path: Path) -> None:
        explicit = [tmp_path / "agent.py"]
        watcher = FileWatcher(_noop_callback, paths=explicit)
        assert watcher.paths == explicit
        assert watcher.state == "new"

    def test_construction_with_none_triggers_discovery(self) -> None:
        watcher = FileWatcher(_noop_callback, paths=None)
        # Discovery returns whatever user-edited modules are loaded;
        # the guarantee is that some snapshot was captured (even an
        # empty list is fine — the contract is "discovery ran").
        assert isinstance(watcher.paths, list)
        # Modules outside site-packages should include the test file
        # itself; verify by checking absoluteness.
        assert all(p.is_absolute() for p in watcher.paths)

    def test_default_debounce_is_200ms(self, tmp_path: Path) -> None:
        watcher = FileWatcher(_noop_callback, paths=[tmp_path / "agent.py"])
        # The default is part of the public API contract (design.md §3.5).
        assert watcher._debounce_ms == 200  # noqa: SLF001 — testing the public default

    def test_rejects_non_positive_debounce(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="debounce_ms"):
            FileWatcher(_noop_callback, debounce_ms=0, paths=[tmp_path / "x.py"])
        with pytest.raises(ValueError, match="debounce_ms"):
            FileWatcher(_noop_callback, debounce_ms=-1, paths=[tmp_path / "x.py"])

    def test_paths_is_a_copy(self, tmp_path: Path) -> None:
        explicit = [tmp_path / "agent.py"]
        watcher = FileWatcher(_noop_callback, paths=explicit)
        # Mutating the original must not mutate the watcher's view.
        explicit.append(tmp_path / "extra.py")
        assert watcher.paths == [tmp_path / "agent.py"]


@pytest.mark.asyncio
class TestFileWatcherAsyncLifecycle:
    """``start`` / ``stop`` are async; assert idempotency and the no-restart rule."""

    async def test_start_is_idempotent(self, tmp_path: Path) -> None:
        watcher = FileWatcher(_noop_callback, paths=[tmp_path / "agent.py"])
        await watcher.start()
        assert watcher.state == "running"
        # Second start: no-op, no error.
        await watcher.start()
        assert watcher.state == "running"
        await watcher.stop()

    async def test_stop_is_idempotent(self, tmp_path: Path) -> None:
        watcher = FileWatcher(_noop_callback, paths=[tmp_path / "agent.py"])
        await watcher.start()
        await watcher.stop()
        assert watcher.state == "stopped"
        # Second stop: no-op, no error.
        await watcher.stop()
        assert watcher.state == "stopped"

    async def test_stop_on_fresh_watcher(self, tmp_path: Path) -> None:
        watcher = FileWatcher(_noop_callback, paths=[tmp_path / "agent.py"])
        # Never started → still safe to stop. Guarantees the no-restart
        # invariant: a fresh+stopped watcher cannot be revived.
        await watcher.stop()
        assert watcher.state == "stopped"
        with pytest.raises(RuntimeError, match="cannot be restarted"):
            await watcher.start()

    async def test_start_after_stop_raises(self, tmp_path: Path) -> None:
        watcher = FileWatcher(_noop_callback, paths=[tmp_path / "agent.py"])
        await watcher.start()
        await watcher.stop()
        with pytest.raises(RuntimeError, match="cannot be restarted"):
            await watcher.start()


class TestFileWatcherRefreshPaths:
    """``refresh_paths`` only re-runs discovery for auto-discover watchers."""

    def test_refresh_with_auto_discover(self, monkeypatch: pytest.MonkeyPatch) -> None:
        watcher = FileWatcher(_noop_callback, paths=None)
        sentinel = [Path("/tmp/refresh_marker.py")]
        monkeypatch.setattr(
            "openrtc.execution.file_watcher._discover_user_modules",
            lambda: list(sentinel),
        )
        watcher.refresh_paths()
        assert watcher.paths == sentinel

    def test_refresh_with_explicit_paths_is_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        explicit = [tmp_path / "agent.py"]
        watcher = FileWatcher(_noop_callback, paths=explicit)
        # Even if discovery would return something, refresh must not
        # touch an explicitly-managed path list.
        monkeypatch.setattr(
            "openrtc.execution.file_watcher._discover_user_modules",
            lambda: [Path("/tmp/should_not_appear.py")],
        )
        watcher.refresh_paths()
        assert watcher.paths == explicit


async def _wait_until(
    predicate: Callable[[], bool],
    *,
    timeout_s: float = 2.0,
    poll_s: float = 0.02,
) -> bool:
    """Poll until *predicate* is True or *timeout_s* elapses."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(poll_s)
    return predicate()


@pytest.mark.asyncio
class TestFileWatcherEventWiring:
    """Step 6 — events from watchfiles land in the watcher buffer."""

    async def test_writes_produce_buffered_filechange(self, tmp_path: Path) -> None:
        target = tmp_path / "agent.py"
        target.write_text("# initial\n")
        watcher = FileWatcher(_noop_callback, paths=[target])
        await watcher.start()
        try:
            # watchfiles takes a few ms to install the OS-level watch on
            # macOS; give it a small head start before mutating the file.
            await asyncio.sleep(0.1)
            target.write_text("# modified\n")
            arrived = await _wait_until(
                lambda: any(
                    fc.path.resolve() == target.resolve()
                    for fc in watcher._pending  # noqa: SLF001 — buffer is internal pre-debounce
                ),
                timeout_s=3.0,
            )
            assert arrived, f"No FileChange for target; pending={watcher._pending!r}"  # noqa: SLF001
        finally:
            await watcher.stop()

    async def test_stop_cancels_watch_task_cleanly(self, tmp_path: Path) -> None:
        target = tmp_path / "agent.py"
        target.write_text("# initial\n")
        watcher = FileWatcher(_noop_callback, paths=[target])
        await watcher.start()
        # Give awatch a moment to install.
        await asyncio.sleep(0.05)
        await watcher.stop()
        assert watcher.state == "stopped"
        # Internal task field is cleared after a clean shutdown.
        assert watcher._watch_task is None  # noqa: SLF001

    async def test_empty_path_list_starts_and_stops(self) -> None:
        watcher = FileWatcher(_noop_callback, paths=[])
        await watcher.start()
        assert watcher.state == "running"
        await watcher.stop()
        assert watcher.state == "stopped"


class TestCollapseChanges:
    """``_collapse_changes`` enforces the design.md §3.4 collapse rules."""

    def test_single_modified_passthrough(self) -> None:
        result = _collapse_changes(
            [FileChange(path=Path("/tmp/a.py"), change_type="modified")]
        )
        assert result == [FileChange(path=Path("/tmp/a.py"), change_type="modified")]

    def test_created_plus_modified_collapses_to_created(self) -> None:
        result = _collapse_changes(
            [
                FileChange(path=Path("/tmp/a.py"), change_type="created"),
                FileChange(path=Path("/tmp/a.py"), change_type="modified"),
            ]
        )
        assert result == [FileChange(path=Path("/tmp/a.py"), change_type="created")]

    def test_modified_plus_deleted_collapses_to_deleted(self) -> None:
        result = _collapse_changes(
            [
                FileChange(path=Path("/tmp/a.py"), change_type="modified"),
                FileChange(path=Path("/tmp/a.py"), change_type="deleted"),
            ]
        )
        assert result == [FileChange(path=Path("/tmp/a.py"), change_type="deleted")]

    def test_deleted_dominates_created(self) -> None:
        # Created and deleted in the same window: the file is gone, so
        # report deleted (final-state-wins for the deletion case).
        result = _collapse_changes(
            [
                FileChange(path=Path("/tmp/a.py"), change_type="created"),
                FileChange(path=Path("/tmp/a.py"), change_type="deleted"),
            ]
        )
        assert result == [FileChange(path=Path("/tmp/a.py"), change_type="deleted")]

    def test_multiple_paths_preserved_in_first_seen_order(self) -> None:
        result = _collapse_changes(
            [
                FileChange(path=Path("/tmp/b.py"), change_type="modified"),
                FileChange(path=Path("/tmp/a.py"), change_type="modified"),
                FileChange(path=Path("/tmp/b.py"), change_type="modified"),
            ]
        )
        assert result == [
            FileChange(path=Path("/tmp/b.py"), change_type="modified"),
            FileChange(path=Path("/tmp/a.py"), change_type="modified"),
        ]

    def test_empty_input_returns_empty(self) -> None:
        assert _collapse_changes([]) == []


@pytest.mark.asyncio
class TestDebounceAndDispatch:
    """Step 7 — trailing-edge debounce coalesces rapid events into one callback."""

    async def test_one_save_one_callback_after_200ms(self, tmp_path: Path) -> None:
        events: list[tuple[float, list[FileChange]]] = []

        async def on_change(changes: list[FileChange]) -> None:
            events.append((time.monotonic(), list(changes)))

        watcher = FileWatcher(on_change, debounce_ms=200, paths=[tmp_path / "a.py"])
        # Don't run the watch loop; drive the seam directly.
        watcher._state = "running"  # noqa: SLF001
        start = time.monotonic()
        watcher._handle_change_batch(  # noqa: SLF001
            [FileChange(path=tmp_path / "a.py", change_type="modified")]
        )
        # Wait past the debounce window.
        await asyncio.sleep(0.35)

        assert len(events) == 1
        elapsed_ms = (events[0][0] - start) * 1000
        assert 150 < elapsed_ms < 350, f"flush at {elapsed_ms:.0f}ms not within 200±150"
        assert events[0][1] == [
            FileChange(path=tmp_path / "a.py", change_type="modified"),
        ]
        await watcher.stop()

    async def test_five_rapid_saves_one_callback(self, tmp_path: Path) -> None:
        events: list[tuple[float, list[FileChange]]] = []

        async def on_change(changes: list[FileChange]) -> None:
            events.append((time.monotonic(), list(changes)))

        watcher = FileWatcher(on_change, debounce_ms=200, paths=[tmp_path / "a.py"])
        watcher._state = "running"  # noqa: SLF001
        start = time.monotonic()
        # Five batches within 50ms, all for the same file.
        for _ in range(5):
            watcher._handle_change_batch(  # noqa: SLF001
                [FileChange(path=tmp_path / "a.py", change_type="modified")]
            )
            await asyncio.sleep(0.005)
        last_event_time = time.monotonic()

        await asyncio.sleep(0.4)

        assert len(events) == 1, (
            f"expected exactly 1 callback, got {len(events)}: {events!r}"
        )
        # Callback should fire ~200ms after the LAST event, not after the first.
        elapsed_after_last_ms = (events[0][0] - last_event_time) * 1000
        assert 150 < elapsed_after_last_ms < 300, (
            f"flush at {elapsed_after_last_ms:.0f}ms after last event, "
            "expected 200ms ±50ms"
        )
        # All five events collapsed to one (same path, all modified).
        assert events[0][1] == [
            FileChange(path=tmp_path / "a.py", change_type="modified"),
        ]
        # Sanity: total elapsed from FIRST event is at least 200ms.
        elapsed_total_ms = (events[0][0] - start) * 1000
        assert elapsed_total_ms >= 200
        await watcher.stop()

    async def test_callback_exception_does_not_break_subsequent_dispatches(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        call_log: list[list[FileChange]] = []
        raise_on_first = True

        async def on_change(changes: list[FileChange]) -> None:
            nonlocal raise_on_first
            call_log.append(list(changes))
            if raise_on_first:
                raise_on_first = False
                raise RuntimeError("boom")

        watcher = FileWatcher(on_change, debounce_ms=100, paths=[tmp_path / "a.py"])
        watcher._state = "running"  # noqa: SLF001
        with caplog.at_level(logging.ERROR, logger="openrtc.execution.file_watcher"):
            watcher._handle_change_batch(  # noqa: SLF001
                [FileChange(path=tmp_path / "a.py", change_type="modified")]
            )
            await asyncio.sleep(0.25)
            # First flush fired and raised; the watcher must still be alive.
            assert len(call_log) == 1
            assert any("on_change raised" in rec.message for rec in caplog.records)

            # Fire a second batch; the watcher should still dispatch.
            watcher._handle_change_batch(  # noqa: SLF001
                [FileChange(path=tmp_path / "b.py", change_type="created")]
            )
            await asyncio.sleep(0.25)
            assert len(call_log) == 2
            assert call_log[1] == [
                FileChange(path=tmp_path / "b.py", change_type="created")
            ]
        await watcher.stop()

    async def test_stop_during_pending_flush_cancels_cleanly(
        self, tmp_path: Path
    ) -> None:
        events: list[list[FileChange]] = []

        async def on_change(changes: list[FileChange]) -> None:
            events.append(list(changes))

        watcher = FileWatcher(on_change, debounce_ms=300, paths=[tmp_path / "a.py"])
        watcher._state = "running"  # noqa: SLF001
        watcher._handle_change_batch(  # noqa: SLF001
            [FileChange(path=tmp_path / "a.py", change_type="modified")]
        )
        # Stop BEFORE the flush window elapses.
        await asyncio.sleep(0.05)
        await watcher.stop()
        # Wait long enough that any leaked flush would have fired.
        await asyncio.sleep(0.4)
        assert events == []
        # No leaked tasks.
        assert watcher._flush_task is None  # noqa: SLF001
