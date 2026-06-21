"""Agent resolver: builds the strategy chain and selects the agent for a session."""

from __future__ import annotations

from collections.abc import Mapping

from livekit.agents import JobContext

from openrtc.core.config import AgentConfig
from openrtc.routing.base_routing import RoutingStrategy
from openrtc.routing.default_routing import _DefaultFallbackStrategy
from openrtc.routing.metadata_routing import _MetadataStrategy
from openrtc.routing.room_prefix_routing import _RoomNamePrefixStrategy

_ROUTING_STRATEGIES: tuple[RoutingStrategy, ...] = (
    _MetadataStrategy(source_attr="job", source_label="job metadata"),
    _MetadataStrategy(source_attr="room", source_label="room metadata"),
    _RoomNamePrefixStrategy(),
    _DefaultFallbackStrategy(),
)


def _resolve_agent_config(
    agents: Mapping[str, AgentConfig],
    ctx: JobContext,
) -> AgentConfig:
    """Resolve the agent for a session from metadata or fallback order."""
    if not agents:
        raise RuntimeError("No agents are registered in the pool.")
    for strategy in _ROUTING_STRATEGIES:
        resolved = strategy.resolve(agents, ctx)
        if resolved is not None:
            return resolved
    raise RuntimeError("No routing strategy resolved an agent.")  # pragma: no cover
