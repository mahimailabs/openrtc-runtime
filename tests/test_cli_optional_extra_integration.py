"""Integration coverage for the optional ``openrtc[cli]`` install hint.

``livekit-agents`` (a core dependency) transitively installs Typer, so a normal
``pip install openrtc`` environment usually already has ``typer`` and ``rich``.
Uninstalling them breaks ``import openrtc`` before ``cli.main`` runs, so we
cannot assert the real "missing wheels" case end-to-end without a stripped
install.

This module instead runs a **subprocess** that patches only
:func:`importlib.import_module` (which :mod:`openrtc.cli` uses for the optional
check) while leaving ``import typer`` (used by LiveKit) unchanged. That matches
how the unit test in :mod:`tests.test_cli` exercises the hint path, but in a
fresh interpreter with no shared pytest state.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.integration
def test_cli_extra_missing_hint_in_fresh_subprocess() -> None:
    """``main()`` returns 1 and prints the ``openrtc[cli]`` hint when Typer import_module fails."""
    code = r"""
import importlib
import sys

_real = importlib.import_module

def _fake(name, package=None):
    if name == "typer":
        raise ModuleNotFoundError("No module named 'typer'", name="typer")
    return _real(name, package)

importlib.import_module = _fake

from openrtc.cli import main

sys.exit(main(["list", "--agents-dir", "."]))
"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"subprocess timed out: {exc!r}")
    assert proc.returncode == 1, proc.stderr + proc.stdout
    assert "openrtc[cli]" in (proc.stderr + proc.stdout)
