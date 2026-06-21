"""Per-agent on-disk footprint helpers for the list/dashboard views."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openrtc.core.config import AgentConfig

logger = logging.getLogger("openrtc")

__all__ = [
    "AgentDiskFootprint",
    "agent_disk_footprints",
    "file_size_bytes",
    "format_byte_size",
]


@dataclass(frozen=True, slots=True)
class AgentDiskFootprint:
    """On-disk size for a single agent module file."""

    name: str
    path: Path
    size_bytes: int


def format_byte_size(num_bytes: int) -> str:
    """Return a short human-readable size string using binary units."""
    if num_bytes < 0:
        num_bytes = 0
    value = float(num_bytes)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for i, unit in enumerate(units):
        if value < 1024.0 or i == len(units) - 1:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    raise AssertionError("unreachable: last unit always matches")  # pragma: no cover


def file_size_bytes(path: Path) -> int:
    """Return the size of a file in bytes, or ``0`` if it cannot be read."""
    try:
        return path.stat().st_size
    except OSError as exc:
        logger.debug("Could not stat %s: %s", path, exc)
        return 0


def agent_disk_footprints(configs: Sequence[AgentConfig]) -> list[AgentDiskFootprint]:
    """Collect per-agent source file sizes when a path was recorded at registration."""
    footprints: list[AgentDiskFootprint] = []
    for config in configs:
        if config.source_path is None:
            continue
        path = config.source_path
        footprints.append(
            AgentDiskFootprint(
                name=config.name,
                path=path,
                size_bytes=file_size_bytes(path),
            )
        )
    return footprints
