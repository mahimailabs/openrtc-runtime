"""Metadata-based routing strategy: resolve from job or room metadata."""

from __future__ import annotations

from collections.abc import Mapping

from livekit.agents import JobContext

from openrtc.core.config import AgentConfig
from openrtc.routing.base_routing import (
    _agent_name_from_metadata,
    _get_registered_agent,
)


class _MetadataStrategy:
    """Resolve from a metadata source (job or room); raise on an unknown name."""

    def __init__(self, *, source_attr: str, source_label: str) -> None:
        self._source_attr = source_attr
        self._source_label = source_label

    def resolve(
        self, agents: Mapping[str, AgentConfig], ctx: JobContext
    ) -> AgentConfig | None:
        source = getattr(ctx, self._source_attr, None)
        name = _agent_name_from_metadata(getattr(source, "metadata", None))
        if name is None:
            return None
        return _get_registered_agent(agents, name, source=self._source_label)
