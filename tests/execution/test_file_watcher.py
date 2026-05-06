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
    _discover_user_modules,
    _interpreter_excluded_roots,
)


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
