"""Metadata-based routing strategy: resolve from job or room metadata."""

from __future__ import annotations

from collections.abc import Collection

from openrtc.core.session_view import SessionView
from openrtc.routing.base_routing import (
    _agent_name_from_metadata,
    _require_registered_name,
)


class _MetadataStrategy:
    """Resolve a name from a metadata source (job or room); raise on an unknown one.

    The view already resolves the pre-connect room metadata (job room preferred
    over the rtc room), so this strategy just reads the neutral seam.
    """

    def __init__(self, *, source_attr: str, source_label: str) -> None:
        self._source_attr = source_attr
        self._source_label = source_label

    def resolve(self, agent_names: Collection[str], view: SessionView) -> str | None:
        if self._source_attr == "room":
            metadata = view.room_metadata
        else:
            metadata = view.job_metadata
        name = _agent_name_from_metadata(metadata)
        if name is None:
            return None
        return _require_registered_name(agent_names, name, source=self._source_label)
