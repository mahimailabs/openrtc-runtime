"""Metadata-based routing strategy: resolve from job or room metadata."""

from __future__ import annotations

from collections.abc import Mapping

from openrtc.core.config import AgentConfig
from openrtc.core.session_view import SessionView
from openrtc.routing.base_routing import (
    _agent_name_from_metadata,
    _get_registered_agent,
)


class _MetadataStrategy:
    """Resolve from a metadata source (job or room); raise on an unknown name.

    The view already resolves the pre-connect room metadata (job room preferred
    over the rtc room), so this strategy just reads the neutral seam.
    """

    def __init__(self, *, source_attr: str, source_label: str) -> None:
        self._source_attr = source_attr
        self._source_label = source_label

    def resolve(
        self, agents: Mapping[str, AgentConfig], view: SessionView
    ) -> AgentConfig | None:
        if self._source_attr == "room":
            metadata = view.room_metadata
        else:
            metadata = view.job_metadata
        name = _agent_name_from_metadata(metadata)
        if name is None:
            return None
        return _get_registered_agent(agents, name, source=self._source_label)
