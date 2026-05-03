"""Resolve which registered agent should handle an incoming session."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from livekit.agents import JobContext

from openrtc.core.config import AgentConfig

logger = logging.getLogger("openrtc")

_METADATA_AGENT_KEYS = ("agent", "demo")


def _resolve_agent_config(
    agents: Mapping[str, AgentConfig],
    ctx: JobContext,
) -> AgentConfig:
    """Resolve the agent for a session from metadata or fallback order."""
    if not agents:
        raise RuntimeError("No agents are registered in the pool.")

    selected_name = _agent_name_from_metadata(getattr(ctx.job, "metadata", None))
    if selected_name is not None:
        return _get_registered_agent(agents, selected_name, source="job metadata")

    selected_name = _agent_name_from_metadata(getattr(ctx.room, "metadata", None))
    if selected_name is not None:
        return _get_registered_agent(agents, selected_name, source="room metadata")

    room_name = getattr(ctx.room, "name", None)
    if isinstance(room_name, str):
        for agent_name, config in agents.items():
            if room_name.startswith(f"{agent_name}-"):
                logger.info(
                    "Resolved agent '%s' via room name prefix from room '%s'.",
                    agent_name,
                    room_name,
                )
                return config

    default_agent = next(iter(agents.values()))
    logger.info("Resolved agent '%s' via default fallback.", default_agent.name)
    return default_agent


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
