"""Default fallback routing strategy: resolve to the first registered agent."""

from __future__ import annotations

from collections.abc import Mapping

from livekit.agents import JobContext

from openrtc.core.config import AgentConfig
from openrtc.routing.base_routing import logger


class _DefaultFallbackStrategy:
    """Resolve to the first registered agent."""

    def resolve(
        self, agents: Mapping[str, AgentConfig], ctx: JobContext
    ) -> AgentConfig | None:
        default_agent = next(iter(agents.values()))
        logger.info("Resolved agent '%s' via default fallback.", default_agent.name)
        return default_agent
