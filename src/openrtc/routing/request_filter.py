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

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from openrtc.routing.base_routing import _agent_name_from_metadata, logger

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
