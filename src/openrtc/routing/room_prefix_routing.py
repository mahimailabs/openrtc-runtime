"""Room-name-prefix routing strategy: resolve when room name starts with agent name."""

from __future__ import annotations

from collections.abc import Mapping

from openrtc.core.config import AgentConfig
from openrtc.core.session_view import SessionView
from openrtc.routing.base_routing import logger


class _RoomNamePrefixStrategy:
    """Resolve when the room name starts with ``<agent>-``."""

    def resolve(
        self, agents: Mapping[str, AgentConfig], view: SessionView
    ) -> AgentConfig | None:
        # The view resolves the pre-connect room name (job room preferred over the
        # rtc room, which is empty until connect) and always yields a str, so a
        # non-matching or absent name simply matches no prefix and defers.
        room_name = view.room_name
        for agent_name, config in agents.items():
            if room_name.startswith(f"{agent_name}-"):
                logger.info(
                    "Resolved agent '%s' via room name prefix from room '%s'.",
                    agent_name,
                    room_name,
                )
                return config
        return None
