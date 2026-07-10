"""RoutingStrategy Protocol and shared helper functions for the routing family."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from openrtc.core.config import AgentConfig
from openrtc.core.session_view import SessionView

logger = logging.getLogger("openrtc")

_METADATA_AGENT_KEYS = ("agent", "demo")


@runtime_checkable
class RoutingStrategy(Protocol):
    """Resolve the agent for a session, or return None to defer to the next strategy."""

    def resolve(
        self, agents: Mapping[str, AgentConfig], view: SessionView
    ) -> AgentConfig | None: ...


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
