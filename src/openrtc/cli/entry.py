"""Console script entrypoint internals.

The Typer/Rich implementation lives in :mod:`openrtc.cli.commands` and is
installed with the optional extra ``openrtc[cli]``. The package-level
:mod:`openrtc.cli` re-exports :func:`main` and the ``app`` Typer instance, so
the console script in ``pyproject.toml`` (``openrtc.cli:main``) still resolves.
"""

from __future__ import annotations

import importlib
import sys

CLI_EXTRA_INSTALL_HINT = (
    "The OpenRTC CLI requires optional dependencies. "
    "Install with: pip install 'openrtc[cli]'"
)


def _optional_typer_rich_missing() -> bool:
    """Return True only when ``typer`` or ``rich`` cannot be imported.

    Any other :exc:`ModuleNotFoundError` (e.g. a sub-dependency of Typer, or a
    missing core package) is re-raised so callers see the real failure rather
    than the optional-extra install hint.
    """
    try:
        importlib.import_module("typer")
        importlib.import_module("rich")
    except ModuleNotFoundError as exc:
        if exc.name in ("typer", "rich"):
            return True
        raise
    return False


def main(argv: list[str] | None = None) -> int:
    """Run the OpenRTC CLI when optional ``cli`` dependencies are installed."""
    if _optional_typer_rich_missing():
        print(CLI_EXTRA_INSTALL_HINT, file=sys.stderr)
        return 1

    # Do not catch ImportError here: failures (e.g. missing livekit, broken
    # openrtc install) must surface with their original tracebacks.
    from openrtc.cli.commands import main as run_cli

    return run_cli(argv)
