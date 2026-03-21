from __future__ import annotations

import logging
import resource
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from openrtc.pool import AgentConfig

logger = logging.getLogger("openrtc")


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
    return f"{int(num_bytes)} B"


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


def process_resident_set_bytes() -> int | None:
    """Best-effort current resident set size (RSS) for this process.

    Returns:
        RSS in bytes on supported platforms, or ``None`` if unavailable
        (e.g. some Windows builds).
    """
    if sys.platform.startswith("linux"):
        return _linux_rss_bytes()
    if sys.platform == "darwin":
        return _macos_rss_bytes()
    return None


def _linux_rss_bytes() -> int | None:
    try:
        text = Path("/proc/self/status").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) >= 2:
                # Value is in kB on Linux.
                return int(parts[1]) * 1024
    return None


def _macos_rss_bytes() -> int | None:
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
    except OSError:
        return None
    # On macOS, ru_maxrss is bytes (per CPython docs).
    value = int(usage.ru_maxrss)
    return value if value > 0 else None
