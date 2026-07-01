"""Shared result and event types for the hot reload subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from livekit.agents import Agent

ReloadStatus = Literal["swapped", "failed"]

__all__ = ["ReloadEvent", "ReloadResult", "ReloadStatus"]


@dataclass(frozen=True)
class ReloadResult:
    """Outcome of re-importing a single agent module.

    ``swapped`` carries the freshly imported ``agent_cls``. ``failed`` carries a
    human-readable ``error`` (with ``file:line`` where available) and leaves the
    previously loaded module untouched.
    """

    status: ReloadStatus
    agent_cls: type[Agent] | None = None
    error: str | None = None


@dataclass(frozen=True)
class ReloadEvent:
    """A reload attempt, surfaced to logs, stdout, and the metrics stream."""

    agent_name: str
    status: ReloadStatus
    sessions_swapped: int
    duration_ms: float
    source_path: str
    error: str | None = None
