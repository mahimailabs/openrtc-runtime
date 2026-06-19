"""Public per-session observability seam.

A ``SessionObserver`` is notified when a session goes live and when it ends, so
external telemetry (VoiceGateway, OpenTelemetry, custom) can attach to each live
``AgentSession`` without reaching into OpenRTC internals. OpenRTC hands the live
session and a typed ``SessionInfo`` to the observer and defines no per-turn event
schema of its own.

Observer calls are isolated: a raising or slow observer is logged and skipped and
never crashes the session, its siblings, or the worker.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from livekit.agents import AgentSession


class SessionStatus(Enum):
    """Terminal status of an observed session."""

    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """Stable identity of one observed session for its whole lifetime."""

    agent_name: str
    room_name: str
    job_id: str
    metadata: Mapping[str, str]
    started_at: float


@dataclass(frozen=True, slots=True)
class SessionOutcome:
    """How an observed session ended.

    ``error`` holds the terminating exception for ``FAILED`` and ``CANCELLED``
    outcomes, and is ``None`` for ``SUCCESS``. ``status`` is the source of truth.
    """

    status: SessionStatus
    error: BaseException | None
    ended_at: float
    duration_seconds: float


@runtime_checkable
class SessionObserver(Protocol):
    """Receive per-session lifecycle notifications from an ``AgentPool``.

    ``on_session_start`` receives the live ``AgentSession`` once it has started,
    which is the point at which an observer can subscribe to session metrics.
    ``on_session_end`` receives the terminal outcome. Both run inside the
    session's own task and should not raise (a raising observer is logged and
    skipped).
    """

    async def on_session_start(
        self, info: SessionInfo, session: AgentSession[Any]
    ) -> None:
        """Handle a session going live after it has started and connected."""
        ...

    async def on_session_end(self, info: SessionInfo, outcome: SessionOutcome) -> None:
        """Handle a session ending, for any terminal outcome."""
        ...
