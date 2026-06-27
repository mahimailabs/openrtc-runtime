"""Metadata-based routing strategy: resolve from job or room metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from livekit.agents import JobContext

from openrtc.core.config import AgentConfig
from openrtc.routing.base_routing import (
    _agent_name_from_metadata,
    _get_registered_agent,
)


def _room_metadata(ctx: JobContext) -> Any:
    """Return room metadata available before connect.

    Routing runs before ctx.connect(). ctx.room.metadata is empty until the
    rtc.Room connects; the authoritative pre-connect room metadata is on
    ctx.job.room.metadata (set by the LiveKit dispatch system). Prefer the job
    room's metadata and fall back to ctx.room.metadata for already-connected or
    stubbed contexts.
    """
    job = getattr(ctx, "job", None)
    job_room = getattr(job, "room", None)
    job_room_metadata = getattr(job_room, "metadata", None)
    if job_room_metadata is not None:
        return job_room_metadata
    return getattr(ctx.room, "metadata", None)


class _MetadataStrategy:
    """Resolve from a metadata source (job or room); raise on an unknown name."""

    def __init__(self, *, source_attr: str, source_label: str) -> None:
        self._source_attr = source_attr
        self._source_label = source_label

    def resolve(
        self, agents: Mapping[str, AgentConfig], ctx: JobContext
    ) -> AgentConfig | None:
        if self._source_attr == "room":
            metadata = _room_metadata(ctx)
        else:
            source = getattr(ctx, self._source_attr, None)
            metadata = getattr(source, "metadata", None)
        name = _agent_name_from_metadata(metadata)
        if name is None:
            return None
        return _get_registered_agent(agents, name, source=self._source_label)
