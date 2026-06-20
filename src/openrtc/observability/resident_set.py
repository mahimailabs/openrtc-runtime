"""Best-effort per-process resident-set memory, with per-OS semantics."""

from __future__ import annotations

import sys
from pathlib import Path

from openrtc.observability.snapshot import ProcessResidentSetInfo

__all__ = ["get_process_resident_set_info", "process_resident_set_bytes"]


def get_process_resident_set_info() -> ProcessResidentSetInfo:
    """Return a single best-effort memory figure for this process.

    Semantics differ by platform; do not assume "RSS" means the same thing everywhere.

    **Linux** -- Reads **VmRSS** from ``/proc/self/status`` (kernel-reported
    current resident set size; value in kiB in the file, returned here in bytes).
    This is a reasonable snapshot of *current* footprint at the time of the read.

    **macOS** -- Uses :func:`resource.getrusage` with :data:`resource.RUSAGE_SELF`.
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
    try:
        import resource
    except ImportError:  # pragma: no cover - ``resource`` is Unix-only (not on Windows)
        return None
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
    except OSError:
        return None
    # CPython documents ru_maxrss in *bytes* on macOS (unlike Linux ru_maxrss in KiB).
    value = int(usage.ru_maxrss)
    return value if value > 0 else None
