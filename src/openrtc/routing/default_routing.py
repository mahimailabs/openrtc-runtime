"""Default fallback routing strategy: resolve to the first registered agent."""

from __future__ import annotations

from collections.abc import Collection

from openrtc.core.session_view import SessionView
from openrtc.routing.base_routing import logger


class _DefaultFallbackStrategy:
    """Resolve to the first registered agent name."""

    def resolve(self, agent_names: Collection[str], view: SessionView) -> str | None:
        name = next(iter(agent_names))
        logger.info("Resolved agent '%s' via default fallback.", name)
        return name
