"""Pipecat CLI helpers: serve agents discovered from a directory.

The pipecat counterpart of ``livekit_cli``. Kept separate so the pipecat serving
path (discovery + ``run``) does not entangle the livekit worker commands.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import typer

from openrtc.core.pool import AgentPool

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("openrtc")

__all__ = ["serve_pipecat_agents"]


def serve_pipecat_agents(agents_dir: Path) -> None:
    """Discover ``@agent_config``-marked builders from a directory and serve them.

    Builds a pipecat pool, discovers the directory into it, and hands off to
    ``run`` (blocking). Exits with a clear message when the directory is missing,
    is not a directory, or holds no marked builders.
    """
    pool = AgentPool(backend="pipecat")
    try:
        discovered = pool.discover(agents_dir)
    except FileNotFoundError:
        logger.error(
            "Agents directory does not exist: %s. Pass a valid path.", agents_dir
        )
        raise typer.Exit(code=1) from None
    except NotADirectoryError:
        logger.error(
            "Agents path is not a directory: %s. Pass a directory of agent modules.",
            agents_dir,
        )
        raise typer.Exit(code=1) from None
    if not discovered:
        logger.error("No pipecat agents were discovered in %s.", agents_dir)
        raise typer.Exit(code=1)
    logger.info("Serving %d pipecat agent(s) from %s.", len(discovered), agents_dir)
    pool.run()
