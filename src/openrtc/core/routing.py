"""Resolve which registered agent should handle an incoming session."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from livekit.agents import JobContext

from openrtc.core.config import AgentConfig

logger = logging.getLogger("openrtc")

_METADATA_AGENT_KEYS = ("agent", "demo")


@runtime_checkable
class RoutingStrategy(Protocol):
    """Resolve the agent for a session, or return None to defer to the next strategy."""

    def resolve(
        self, agents: Mapping[str, AgentConfig], ctx: JobContext
    ) -> AgentConfig | None: ...


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


class _DefaultFallbackStrategy:
    """Resolve to the first registered agent."""

    def resolve(
        self, agents: Mapping[str, AgentConfig], ctx: JobContext
    ) -> AgentConfig | None:
        default_agent = next(iter(agents.values()))
        logger.info("Resolved agent '%s' via default fallback.", default_agent.name)
        return default_agent


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


def _agent_name_from_metadata(metadata: Any) -> str | None:
    if metadata is None:
        return None
    if isinstance(metadata, Mapping):
        return _agent_name_from_mapping(metadata)
    if isinstance(metadata, str):
        stripped = metadata.strip()
        if not stripped:
            return None
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            logger.debug("Ignoring non-JSON metadata: %s", stripped)
            return None
        if isinstance(decoded, Mapping):
            return _agent_name_from_mapping(decoded)
    return None


def _agent_name_from_mapping(metadata: Mapping[str, Any]) -> str | None:
    for key in _METADATA_AGENT_KEYS:
        value = metadata.get(key)
        if isinstance(value, str):
            normalized_value = value.strip()
            if normalized_value:
                return normalized_value
    return None


def _get_registered_agent(
    agents: Mapping[str, AgentConfig],
    name: str,
    *,
    source: str,
) -> AgentConfig:
    try:
        config = agents[name]
    except KeyError as exc:
        raise ValueError(f"Unknown agent '{name}' requested via {source}.") from exc
    logger.info("Resolved agent '%s' via %s.", name, source)
    return config
