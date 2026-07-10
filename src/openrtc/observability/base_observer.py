"""Public per-session observability seam.

A ``SessionObserver`` is notified when a session goes live and when it ends, so
external telemetry (VoiceGateway, OpenTelemetry, custom) can attach to each live
``AgentSession`` without reaching into OpenRTC internals. OpenRTC hands the live
session and a typed ``SessionInfo`` to the observer and defines no per-turn event
schema of its own.

Observer calls are isolated: a raising or slow observer is logged and skipped and
never crashes the session, its siblings, or the worker. Genuine cancellation of
the session's own task still propagates.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from openrtc.utils.validation import DEFAULT_TENANT, require_tenant_id

if TYPE_CHECKING:
    from livekit.agents import AgentSession

    from openrtc.core.session_view import SessionView

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
    # The tenant this session belongs to (MAH-101), resolved from dispatch
    # metadata key "tenant" (matches voicegateway's VoiceGatewayObserver), or
    # "default" when unset. Defaulted so existing construction sites are unaffected.
    tenant: str = DEFAULT_TENANT
    # The worker's deployment version that handled this call (MAH-112), for the
    # per-call audit trail. voicegateway records it; ``None`` when the worker is
    # untagged.
    deployment_version: str | None = None


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
        """Handle a session ending, for any terminal outcome.

        May be called without a preceding ``on_session_start`` when the session
        fails before going live (``session.start()`` or ``connect()`` raised), so
        a stateful observer must tolerate an end with no paired start.
        """
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


def _merge_metadata(view: SessionView) -> dict[str, str]:
    """Merge room metadata then job metadata (job wins) into one str map.

    The view resolves the pre-connect room metadata (job room preferred over the
    rtc room, which is empty until connect), so the merge sees the same dispatch
    metadata the routing chain does.
    """
    merged = _coerce_metadata(view.room_metadata)
    merged.update(_coerce_metadata(view.job_metadata))
    return merged


def _resolve_tenant(metadata: Mapping[str, str]) -> str:
    """Resolve the tenant from dispatch metadata key ``tenant``.

    Absent / empty -> ``"default"`` (single-tenant deployments unchanged). A
    present-but-malformed value is validated and rejected (raises), since a bad
    tenant would otherwise misroute the session's config, caps, and tags.
    """
    raw = metadata.get("tenant")
    if not raw:
        return DEFAULT_TENANT
    return require_tenant_id(raw)


def _build_session_info(
    agent_name: str, view: SessionView, deployment_version: str | None = None
) -> SessionInfo:
    """Build a ``SessionInfo`` from the resolved agent and the session view.

    ``view`` is the backend-neutral :class:`SessionView`, so any backend (livekit
    via ``for_livekit``, pipecat via its own adapter) reaches this the same way.
    The view uses defensive attribute access, so a missing room name or job id can
    never turn a healthy session into a failed one, and it resolves the pre-connect
    room name/metadata (job room preferred over the rtc room, which is empty until
    connect) exactly as routing does. The tenant is the one validated field (a
    malformed ``tenant`` in dispatch metadata rejects the session).
    ``deployment_version`` tags which worker version handled the call (MAH-112).
    """
    metadata = _merge_metadata(view)
    tenant = _resolve_tenant(metadata)
    # Ensure metadata["tenant"] always carries the resolved tenant (including the
    # "default" fallback), so voicegateway's VoiceGatewayObserver attributes
    # per-tenant cost from info.metadata["tenant"] with no change on its side (MAH-105).
    metadata["tenant"] = tenant
    return SessionInfo(
        agent_name=agent_name,
        room_name=view.room_name,
        job_id=view.job_id,
        metadata=metadata,
        started_at=time.time(),
        tenant=tenant,
        deployment_version=deployment_version,
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


async def _invoke_observer(
    awaitable: Awaitable[None],
    *,
    observer: SessionObserver,
    hook: str,
    agent_name: str,
    timeout: float,
) -> None:
    """Run one observer hook with isolation, bounded by ``timeout``.

    A fault in the observer (any ``Exception``, including a timeout) is logged
    and skipped so it never reaches the session. An observer that raises
    ``CancelledError`` on its own is isolated too; only a genuine cancellation of
    the session's own task (``task.cancelling() > 0``) is allowed to propagate.
    """
    try:
        await asyncio.wait_for(awaitable, timeout)
    except asyncio.CancelledError:
        task = asyncio.current_task()
        if task is None:  # pragma: no cover - always inside a running task
            raise
        if task.cancelling() > 0:
            raise  # the worker is cancelling this session; propagate
        logger.warning(
            "session observer %r cancelled %s for agent '%s'",
            observer,
            hook,
            agent_name,
        )
    except Exception:  # noqa: BLE001 - observer faults must not reach the session
        logger.warning(
            "session observer %r failed %s for agent '%s'",
            observer,
            hook,
            agent_name,
            exc_info=True,
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
        await _invoke_observer(
            observer.on_session_start(info, session),
            observer=observer,
            hook="on_session_start",
            agent_name=info.agent_name,
            timeout=timeout,
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
        await _invoke_observer(
            observer.on_session_end(info, outcome),
            observer=observer,
            hook="on_session_end",
            agent_name=info.agent_name,
            timeout=timeout,
        )
