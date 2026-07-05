"""Job-request filter family: decide which incoming rooms a worker accepts.

Routing (see :mod:`openrtc.routing.resolver`) picks *which* agent handles a job
once the worker has accepted it, and always resolves *something* thanks to the
default fallback. That is the wrong layer for scoping a worker: with automatic
dispatch LiveKit offers every room to every worker, so a pool that shares a
LiveKit project with another worker would accept foreign rooms and default-route
them onto its first agent.

This module works one layer earlier, at job acceptance. It mirrors the routing
precedence (job metadata, room metadata, room-name prefix) but *excludes* the
default fallback, turning "which agent" into a yes/no "is this room mine".
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from openrtc.observability.base_observer import _coerce_metadata
from openrtc.routing.base_routing import _agent_name_from_metadata, logger
from openrtc.utils.validation import DEFAULT_TENANT

if TYPE_CHECKING:
    from livekit.agents import JobRequest

    from openrtc.utils.types import RequestFilter


def _owns_room(
    agents: Mapping[str, Any],
    *,
    room_name: object,
    job_metadata: object,
    room_metadata: object,
) -> bool:
    """Return True when an explicit routing signal maps this room to a registered agent.

    Follows the pool's routing precedence (job metadata, then room metadata,
    then room-name prefix) but stops short of the default fallback: a room that
    no registered agent claims is *not* ours. Metadata naming an unregistered
    agent is likewise treated as not ours (it belongs to another worker) rather
    than raised, so an unexpected metadata value can never crash job acceptance.
    """
    for metadata in (job_metadata, room_metadata):
        name = _agent_name_from_metadata(metadata)
        if name is not None and name in agents:
            return True
    if isinstance(room_name, str):
        for agent_name in agents:
            if room_name.startswith(f"{agent_name}-"):
                return True
    return False


def _build_registered_rooms_filter(agents: Mapping[str, Any]) -> RequestFilter:
    """Build a request filter accepting only rooms that map to a registered agent.

    Closes over the pool's live ``agents`` mapping, so agents registered after
    the filter is built (registration happens after the pool is constructed) are
    still recognized.
    """

    async def request_fnc(req: JobRequest) -> None:
        room = req.room
        room_name = getattr(room, "name", None)
        if _owns_room(
            agents,
            room_name=room_name,
            job_metadata=getattr(req.job, "metadata", None),
            room_metadata=getattr(room, "metadata", None),
        ):
            await req.accept()
        else:
            logger.info(
                "Rejecting job for room '%s': no registered agent owns it.",
                room_name,
            )
            await req.reject()

    return request_fnc


def _resolve_request_agent_name(
    agents: Mapping[str, Any],
    *,
    room_name: object,
    job_metadata: object,
    room_metadata: object,
) -> str | None:
    """Resolve which registered agent will handle a job, mirroring routing precedence.

    Follows job metadata, room metadata, room-name prefix, then the first-registered
    fallback (the same order as :func:`openrtc.routing.resolver._resolve_agent_config`).
    Returns ``None`` only when no agents are registered. This attributes an incoming
    job to an agent for per-agent backpressure; it does not validate (a metadata name
    for an unregistered agent falls through to the prefix / fallback rather than
    raising, which routing and the ownership filter handle at their own layers).
    """
    if not agents:
        return None
    for metadata in (job_metadata, room_metadata):
        name = _agent_name_from_metadata(metadata)
        if name is not None and name in agents:
            return name
    if isinstance(room_name, str):
        for agent_name in agents:
            if room_name.startswith(f"{agent_name}-"):
                return agent_name
    return next(iter(agents))  # first-registered fallback


def _build_per_agent_backpressure_filter(
    *,
    agents: Mapping[str, Any],
    caps: Mapping[str, int],
    active_counts: Callable[[], Mapping[str, int]],
    base_filter: RequestFilter | None,
) -> RequestFilter:
    """Reject a job when its target agent is at its per-agent session cap.

    Layers *before* the base ownership decision: a job whose target agent is at cap
    is rejected (a backpressure signal LiveKit understands) regardless of the base;
    otherwise the base filter decides, or the job is accepted when there is no base.
    Sibling agents under their own caps are unaffected. The global
    ``max_concurrent_sessions`` cap still applies on top via the load function; a
    per-agent cap only adds a reject condition, it never widens the global limit.

    The cap is a **soft, best-effort** limit: it reads the live per-agent active
    count, which is incremented at session start (after acceptance), so a burst of
    simultaneous accepts can briefly overshoot before the counts catch up.
    """

    async def request_fnc(req: JobRequest) -> None:
        room = req.room
        name = _resolve_request_agent_name(
            agents,
            room_name=getattr(room, "name", None),
            job_metadata=getattr(req.job, "metadata", None),
            room_metadata=getattr(room, "metadata", None),
        )
        if name is not None:
            cap = caps.get(name)
            if cap is not None and active_counts().get(name, 0) >= cap:
                logger.info(
                    "Rejecting job for agent '%s': at per-agent cap (%d).", name, cap
                )
                await req.reject()
                return
        if base_filter is not None:
            await base_filter(req)
        else:
            await req.accept()

    return request_fnc


def _resolve_request_tenant(*, job_metadata: object, room_metadata: object) -> str:
    """Resolve the tenant for an incoming job from its dispatch metadata.

    Mirrors the session's own resolution: merge room then job metadata (job wins),
    read key ``tenant``, default to ``"default"``. Unvalidated here (a malformed
    tenant simply matches no configured cap and is rejected later at session
    start), so backpressure never crashes job acceptance.
    """
    merged = _coerce_metadata(room_metadata)
    merged.update(_coerce_metadata(job_metadata))
    return merged.get("tenant") or DEFAULT_TENANT


def _build_per_tenant_backpressure_filter(
    *,
    caps: Mapping[str, int],
    active_counts: Callable[[], Mapping[str, int]],
    base_filter: RequestFilter | None,
) -> RequestFilter:
    """Reject a job when its tenant is at its per-tenant session cap (MAH-103).

    Layers exactly like the per-agent filter (MAH-96): a job whose tenant is at cap
    is rejected regardless of the base; otherwise the base decides (which may be the
    per-agent filter, so tenant and agent caps compose — both must have headroom).
    The global ``max_concurrent_sessions`` cap still applies on top. Soft/best-effort:
    reads the live per-tenant active count, incremented at session start.
    """

    async def request_fnc(req: JobRequest) -> None:
        tenant = _resolve_request_tenant(
            job_metadata=getattr(req.job, "metadata", None),
            room_metadata=getattr(req.room, "metadata", None),
        )
        cap = caps.get(tenant)
        if cap is not None and active_counts().get(tenant, 0) >= cap:
            logger.info(
                "Rejecting job for tenant '%s': at per-tenant cap (%d).", tenant, cap
            )
            await req.reject()
            return
        if base_filter is not None:
            await base_filter(req)
        else:
            await req.accept()

    return request_fnc
