"""Room-name-prefix routing strategy: resolve when room name starts with agent name."""

from __future__ import annotations

from collections.abc import Collection

from openrtc.core.session_view import SessionView
from openrtc.routing.base_routing import logger


class _RoomNamePrefixStrategy:
    """Resolve the name whose ``<name>-`` prefix the room name starts with."""

    def resolve(self, agent_names: Collection[str], view: SessionView) -> str | None:
        # The view resolves the pre-connect room name (job room preferred over the
        # rtc room, which is empty until connect) and always yields a str, so a
        # non-matching or absent name simply matches no prefix and defers.
        room_name = view.room_name
        for name in agent_names:
            if room_name.startswith(f"{name}-"):
                logger.info(
                    "Resolved agent '%s' via room name prefix from room '%s'.",
                    name,
                    room_name,
                )
                return name
        return None
