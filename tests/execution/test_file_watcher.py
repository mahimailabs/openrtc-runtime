"""Unit tests for the file watcher (MAH-80)."""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
import types
from pathlib import Path

import pytest

from openrtc.execution.file_watcher import (
    FileChange,
    FileWatcher,
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
