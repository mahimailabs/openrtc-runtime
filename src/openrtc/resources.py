from __future__ import annotations

import logging
import sys

try:
    import resource
except ImportError:  # pragma: no cover - stdlib ``resource`` is Unix-only
    resource = None
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


@dataclass(frozen=True, slots=True)
class ProcessResidentSetInfo:
    """One platform-specific memory figure for this process.

    Always interpret :attr:`bytes_value` together with :attr:`metric` and
    :attr:`description`. Values are **not** comparable across operating systems.
    """

    bytes_value: int | None
    """Numeric value when available, else ``None``."""

    metric: str
    """Stable identifier: ``linux_vm_rss``, ``darwin_ru_max_rss``, or ``unavailable``."""

    description: str
    """What :attr:`bytes_value` represents on this OS (read this before comparing runs)."""


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


def get_process_resident_set_info() -> ProcessResidentSetInfo:
    """Return a single best-effort memory figure for this process.

    Semantics differ by platform; do not assume "RSS" means the same thing everywhere.

    **Linux** — Reads **VmRSS** from ``/proc/self/status`` (kernel-reported
    current resident set size; value in kiB in the file, returned here in bytes).
    This is a reasonable snapshot of *current* footprint at the time of the read.

    **macOS** — Uses :func:`resource.getrusage` with :data:`resource.RUSAGE_SELF`.
    CPython documents ``ru_maxrss`` **in bytes** on macOS. That field is the
    **maximum** resident set size the system has attributed to this process (a
    high-water / peak style figure), **not** the instantaneous current RSS.
    For live usage, use host or container metrics (e.g. Activity Monitor).

    **Other** (e.g. Windows): not implemented here; :attr:`ProcessResidentSetInfo.bytes_value`
    is ``None``.

    Linux intentionally uses ``/proc`` rather than ``getrusage`` so the Linux path
    reports a current VmRSS analogue; POSIX ``ru_maxrss`` on Linux is in different
    units than on macOS (see :mod:`resource` documentation).
    """
    if sys.platform.startswith("linux"):
        value = _linux_rss_bytes()
        return ProcessResidentSetInfo(
            bytes_value=value,
            metric="linux_vm_rss",
            description=(
                "Current resident set from VmRSS (/proc/self/status), converted to bytes; "
                "snapshot at query time."
            ),
        )
    if sys.platform == "darwin":
        value = _macos_rss_bytes()
        return ProcessResidentSetInfo(
            bytes_value=value,
            metric="darwin_ru_max_rss",
            description=(
                "Peak-style max resident set: resource.getrusage(RUSAGE_SELF).ru_maxrss "
                "in bytes on macOS (per CPython). Not instantaneous current RSS."
            ),
        )
    return ProcessResidentSetInfo(
        bytes_value=None,
        metric="unavailable",
        description=(
            "No resident-memory figure in OpenRTC on this platform (e.g. Windows)."
        ),
    )


def process_resident_set_bytes() -> int | None:
    """Return the numeric memory metric from :func:`get_process_resident_set_info`, or ``None``.

    The number alone is ambiguous across OSes (Linux current VmRSS vs macOS peak
    ``ru_maxrss``). Prefer :func:`get_process_resident_set_info` for :attr:`~ProcessResidentSetInfo.metric`
    and :attr:`~ProcessResidentSetInfo.description`.
    """
    return get_process_resident_set_info().bytes_value


def _linux_rss_bytes() -> int | None:
    """Read VmRSS (kiB in procfs) and convert to bytes."""
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
    """Return ``ru_maxrss`` on Darwin (bytes per CPython; max resident set, not current RSS)."""
    if resource is None:
        return None
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
    except OSError:
        return None
    # CPython documents ru_maxrss in *bytes* on macOS (unlike Linux ru_maxrss in KiB).
    value = int(usage.ru_maxrss)
    return value if value > 0 else None
