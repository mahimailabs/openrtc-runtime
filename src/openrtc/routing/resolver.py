"""Agent resolver: builds the strategy chain and selects the agent for a session."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from livekit.agents import JobContext

from openrtc.core.config import AgentConfig
from openrtc.routing.base_routing import RoutingStrategy
from openrtc.routing.default_routing import _DefaultFallbackStrategy
from openrtc.routing.metadata_routing import _MetadataStrategy
from openrtc.routing.room_prefix_routing import _RoomNamePrefixStrategy
from openrtc.utils.types import AgentRouter

logger = logging.getLogger("openrtc")

_ROUTING_STRATEGIES: tuple[RoutingStrategy, ...] = (
    _MetadataStrategy(source_attr="job", source_label="job metadata"),
    _MetadataStrategy(source_attr="room", source_label="room metadata"),
    _RoomNamePrefixStrategy(),
    _DefaultFallbackStrategy(),
)


def _metadata_to_mapping(metadata: Any) -> Mapping[str, Any] | None:
    """Parse dispatch metadata into a mapping for the custom router, else ``None``.

    Accepts a mapping as-is or a JSON-object string; anything else (empty, non-JSON,
    or a non-object payload) becomes ``None`` so the router sees a consistent shape.
    """
    if isinstance(metadata, Mapping):
        return metadata
    if isinstance(metadata, str):
        stripped = metadata.strip()
        if stripped:
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError:
                return None
            if isinstance(decoded, Mapping):
                return decoded
    return None


def _resolve_via_router(
    agents: Mapping[str, AgentConfig],
    ctx: JobContext,
    router: AgentRouter,
) -> AgentConfig | None:
    """Resolve the agent via the custom router, or ``None`` to defer to the chain.

    An unknown agent name or a raised router rejects the session (raises
    ``ValueError``, which aborts the entrypoint). Returning ``None`` lets the
    default metadata / prefix / fallback chain decide.
    """
    job = getattr(ctx, "job", None)
    job_id = getattr(job, "id", None) or "unknown"
    metadata = _metadata_to_mapping(getattr(job, "metadata", None))
    try:
        name = router(metadata)
    except Exception as exc:
        logger.error("Custom router raised for job '%s'; rejecting session.", job_id)
        raise ValueError(
            f"Custom router raised while resolving the agent for job '{job_id}'."
        ) from exc
    if name is None:
        return None
    config = agents.get(name)
    if config is None:
        raise ValueError(
            f"Custom router returned unknown agent '{name}' for job '{job_id}'."
        )
    logger.info("Router resolved agent '%s' for job '%s'.", name, job_id)
    return config


def _resolve_agent_config(
    agents: Mapping[str, AgentConfig],
    ctx: JobContext,
    *,
    router: AgentRouter | None = None,
) -> AgentConfig:
    """Resolve the agent for a session: custom router first, then the default chain."""
    if not agents:
        raise RuntimeError("No agents are registered in the pool.")
    if router is not None:
        resolved = _resolve_via_router(agents, ctx, router)
        if resolved is not None:
            return resolved
    for strategy in _ROUTING_STRATEGIES:
        resolved = strategy.resolve(agents, ctx)
        if resolved is not None:
            return resolved
    raise RuntimeError("No routing strategy resolved an agent.")  # pragma: no cover
