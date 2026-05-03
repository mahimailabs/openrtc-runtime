"""Console script entrypoint for OpenRTC.

The Typer command definitions live in :mod:`openrtc.cli.commands` (named that
way to avoid a collision between the submodule name and the re-exported
``app`` Typer instance). The lazy install-hint shim lives in
:mod:`openrtc.cli.entry`. This package re-exports both ``main`` and ``app`` so
``openrtc.cli:main`` (the console script in ``pyproject.toml``) and
``from openrtc.cli import app`` still resolve.
"""

from __future__ import annotations

from typing import Any

from openrtc.cli.entry import (
    CLI_EXTRA_INSTALL_HINT,
    _optional_typer_rich_missing,
    main,
)

__all__ = [
    "CLI_EXTRA_INSTALL_HINT",
    "app",
    "main",
]


# Eagerly bind ``app`` so ``from openrtc.cli import app`` returns the Typer
# instance. With typer/rich missing we fall through to ``__getattr__`` below,
# which surfaces the install hint instead of failing the bare ``import
# openrtc.cli``.
if not _optional_typer_rich_missing():
    from openrtc.cli.commands import app  # noqa: F401 (re-exported for callers)


def __getattr__(name: str) -> Any:
    if name == "app":
        if _optional_typer_rich_missing():
            raise ImportError(CLI_EXTRA_INSTALL_HINT)
        from openrtc.cli.commands import app as typer_app

        return typer_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
