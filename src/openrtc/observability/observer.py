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

import asyncio
import json
import logging
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from livekit.agents import AgentSession, JobContext

logger = logging.getLogger("openrtc")


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


def _coerce_metadata(raw: Any) -> dict[str, str]:
    """Parse one metadata value (JSON string, mapping, or absent) into a str map."""
    decoded: Any = raw
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return {}
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            return {}
    if isinstance(decoded, Mapping):
        return {str(key): str(value) for key, value in decoded.items()}
    return {}


def _merge_metadata(ctx: JobContext) -> dict[str, str]:
    """Merge room metadata then job metadata (job wins) into one str map."""
    room = getattr(ctx, "room", None)
    job = getattr(ctx, "job", None)
    merged = _coerce_metadata(getattr(room, "metadata", None))
    merged.update(_coerce_metadata(getattr(job, "metadata", None)))
    return merged


def _build_session_info(agent_name: str, ctx: JobContext) -> SessionInfo:
    """Build a ``SessionInfo`` from the resolved agent and the job context.

    Uses defensive attribute access so a missing room name or job id can never
    turn a healthy session into a failed one.
    """
    room = getattr(ctx, "room", None)
    job = getattr(ctx, "job", None)
    return SessionInfo(
        agent_name=agent_name,
        room_name=getattr(room, "name", "") or "",
        job_id=getattr(job, "id", "") or "",
        metadata=_merge_metadata(ctx),
        started_at=time.time(),
    )


def _build_session_outcome(
    info: SessionInfo, error: BaseException | None
) -> SessionOutcome:
    """Classify the terminal outcome from the in-flight exception, if any."""
    if error is None:
        status = SessionStatus.SUCCESS
    elif isinstance(error, asyncio.CancelledError):
        status = SessionStatus.CANCELLED
    else:
        status = SessionStatus.FAILED
    ended_at = time.time()
    return SessionOutcome(
        status=status,
        error=error,
        ended_at=ended_at,
        duration_seconds=max(ended_at - info.started_at, 0.0),
    )


async def _notify_session_start(
    observers: Iterable[SessionObserver],
    info: SessionInfo,
    session: AgentSession[Any],
    *,
    timeout: float,
) -> None:
    """Notify every observer that the session is live; isolate failures."""
    for observer in observers:
        try:
            await asyncio.wait_for(observer.on_session_start(info, session), timeout)
        except Exception:  # noqa: BLE001 - observer faults must not reach the session
            logger.warning(
                "session observer %r failed on_session_start for agent '%s'",
                observer,
                info.agent_name,
                exc_info=True,
            )


async def _notify_session_end(
    observers: Iterable[SessionObserver],
    info: SessionInfo,
    outcome: SessionOutcome,
    *,
    timeout: float,
) -> None:
    """Notify every observer that the session ended; isolate failures."""
    for observer in observers:
        try:
            await asyncio.wait_for(observer.on_session_end(info, outcome), timeout)
        except Exception:  # noqa: BLE001 - observer faults must not reach the session
            logger.warning(
                "session observer %r failed on_session_end for agent '%s'",
                observer,
                info.agent_name,
                exc_info=True,
            )
