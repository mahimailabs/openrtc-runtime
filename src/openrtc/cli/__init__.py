"""Console script entrypoint for OpenRTC."""

from __future__ import annotations

from typing import Any

from openrtc.cli.entry_cli import (
    CLI_EXTRA_INSTALL_HINT,
    _optional_typer_rich_missing,
    main,
)

__all__ = [
    "CLI_EXTRA_INSTALL_HINT",
    "app",
    "main",
]


if not _optional_typer_rich_missing():
    from openrtc.cli.main_cli import app  # noqa: F401 (re-exported for callers)


def __getattr__(name: str) -> Any:
    if name == "app":
        if _optional_typer_rich_missing():
            raise ImportError(CLI_EXTRA_INSTALL_HINT)
        from openrtc.cli.main_cli import app as typer_app

        return typer_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
