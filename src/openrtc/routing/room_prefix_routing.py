"""Room-name-prefix routing strategy: resolve when room name starts with agent name."""

from __future__ import annotations

from collections.abc import Mapping

from livekit.agents import JobContext

from openrtc.core.config import AgentConfig
from openrtc.routing.base_routing import logger


class _RoomNamePrefixStrategy:
    """Resolve when the room name starts with ``<agent>-``."""

    def resolve(
        self, agents: Mapping[str, AgentConfig], ctx: JobContext
    ) -> AgentConfig | None:
        room_name = getattr(ctx.room, "name", None)
        if not isinstance(room_name, str):
            return None
        for agent_name, config in agents.items():
            if room_name.startswith(f"{agent_name}-"):
                logger.info(
                    "Resolved agent '%s' via room name prefix from room '%s'.",
                    agent_name,
                    room_name,
                )
                return config
        return None
