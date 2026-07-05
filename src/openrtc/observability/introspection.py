"""Session introspection registry + snapshot model for ``openrtc top`` (MAH-92).

``SessionIntrospectionRegistry`` is a ``SessionObserver`` that tracks the live
sessions in the worker (keyed by session_id = job_id), so it is the active-session
source the memory (MAH-88) and CPU (MAH-89) samplers read. ``build_session_rows``
joins that registry with the memory / CPU / slow-session signals and pin status
into the rows ``openrtc top`` renders. It emits only worker-internal introspection
(``agent_name`` + ``tenant`` come straight off the observer payload) — cost and
pipeline latency stay with voicegateway.
"""

from __future__ import annotations

from collections.abc import Callable, Container, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from livekit.agents import AgentSession

    from openrtc.observability.base_observer import SessionInfo, SessionOutcome
    from openrtc.observability.session_cpu import SessionCpu
    from openrtc.observability.session_memory import SessionMemory

__all__ = [
    "LiveSession",
    "SessionIntrospectionRegistry",
    "SessionRow",
    "build_session_rows",
]


@dataclass(frozen=True, slots=True)
class LiveSession:
    """Identity of one live session tracked for introspection."""

    session_id: str
    agent_name: str
    tenant: str | None
    started_at: float


@dataclass(frozen=True, slots=True)
class SessionRow:
    """One ``openrtc top`` row: identity, attributed resources, and status."""

    session_id: str
    agent_name: str
    tenant: str | None
    duration_s: float
    mem_mb: float
    peak_mb: float
    cpu_pct: float
    status: str
    pinned: bool


class SessionIntrospectionRegistry:
    """Track live sessions per worker; the active-session source for the samplers."""

    def __init__(self) -> None:
        self._by_id: dict[str, tuple[LiveSession, AgentSession[Any]]] = {}

    async def on_session_start(
        self, info: SessionInfo, session: AgentSession[Any]
    ) -> None:
        """Record a session that has gone live."""
        self._by_id[info.job_id] = (
            LiveSession(
                session_id=info.job_id,
                agent_name=info.agent_name,
                tenant=info.tenant,
                started_at=info.started_at,
            ),
            session,
        )

    async def on_session_end(self, info: SessionInfo, outcome: SessionOutcome) -> None:
        """Drop a session that has ended; tolerant of an unpaired end."""
        self._by_id.pop(info.job_id, None)

    def active_agents(self) -> dict[str, str]:
        """Return ``{session_id: agent_name}`` for the samplers' sessions_provider."""
        return {sid: entry[0].agent_name for sid, entry in self._by_id.items()}

    def live_sessions(self) -> list[LiveSession]:
        """Return the live session identities."""
        return [entry[0] for entry in self._by_id.values()]

    def session_for(self, session_id: str) -> AgentSession[Any] | None:
        """Return the live ``AgentSession`` for a session_id (for pin lookups)."""
        entry = self._by_id.get(session_id)
        return entry[1] if entry is not None else None

    def active_count(self) -> int:
        """Return the number of live sessions currently tracked."""
        return len(self._by_id)


def build_session_rows(
    *,
    registry: SessionIntrospectionRegistry,
    memory: Mapping[str, SessionMemory],
    cpu: Mapping[str, SessionCpu],
    slow_session_ids: Container[str],
    is_pinned: Callable[[AgentSession[Any]], bool],
    now: float,
) -> list[SessionRow]:
    """Join the registry with the resource signals into ``openrtc top`` rows."""
    rows: list[SessionRow] = []
    for live in registry.live_sessions():
        mem = memory.get(live.session_id)
        session_cpu = cpu.get(live.session_id)
        session = registry.session_for(live.session_id)
        rows.append(
            SessionRow(
                session_id=live.session_id,
                agent_name=live.agent_name,
                tenant=live.tenant,
                duration_s=round(max(0.0, now - live.started_at), 1),
                mem_mb=mem.current_mb if mem is not None else 0.0,
                peak_mb=mem.peak_mb if mem is not None else 0.0,
                cpu_pct=session_cpu.cpu_pct if session_cpu is not None else 0.0,
                status="slow" if live.session_id in slow_session_ids else "active",
                pinned=is_pinned(session) if session is not None else False,
            )
        )
    return rows
