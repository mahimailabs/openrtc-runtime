"""MAH-82: an in-memory index of the live AgentSessions in a coroutine worker.

The registry is a :class:`~openrtc.observability.base_observer.SessionObserver`, so
the coroutine runtime tracks live sessions by registering it as an internal
observer. ``core/wiring.py`` needs no changes: it already hands every observer the
live ``AgentSession`` on start and the ``SessionInfo`` on end. Sessions are keyed by
``job_id`` (unique per dispatched job in coroutine mode), which is the only identity
available at ``on_session_end`` time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from livekit.agents import AgentSession

    from openrtc.observability.base_observer import SessionInfo, SessionOutcome

__all__ = ["LiveSessionRegistry"]


@dataclass(slots=True)
class _Entry:
    agent_name: str
    session: AgentSession[Any]


class LiveSessionRegistry:
    """Track live sessions per agent name for the re-bind protocol."""

    def __init__(self) -> None:
        self._by_job: dict[str, _Entry] = {}

    async def on_session_start(
        self, info: SessionInfo, session: AgentSession[Any]
    ) -> None:
        """Record a session that has just gone live."""
        self._by_job[info.job_id] = _Entry(agent_name=info.agent_name, session=session)

    async def on_session_end(self, info: SessionInfo, outcome: SessionOutcome) -> None:
        """Drop a session that has ended; tolerant of an unpaired end."""
        self._by_job.pop(info.job_id, None)

    def sessions_for(self, agent_name: str) -> list[AgentSession[Any]]:
        """Return the live sessions currently bound to *agent_name*."""
        return [
            entry.session
            for entry in self._by_job.values()
            if entry.agent_name == agent_name
        ]

    def active_count(self) -> int:
        """Return the number of live sessions currently tracked."""
        return len(self._by_job)
