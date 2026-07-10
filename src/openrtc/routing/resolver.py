"""Agent resolver: builds the strategy chain and selects the agent for a session."""

from __future__ import annotations

import json
import logging
from collections.abc import Collection, Mapping
from typing import Any

from openrtc.core.config import AgentConfig
from openrtc.core.session_view import SessionView, for_livekit
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
    agent_names: Collection[str],
    view: SessionView,
    router: AgentRouter,
) -> str | None:
    """Resolve the agent name via the custom router, or ``None`` to defer.

    An unknown agent name or a raised router rejects the session (raises
    ``ValueError``, which aborts the entrypoint). Returning ``None`` lets the
    default metadata / prefix / fallback chain decide.
    """
    job_id = view.job_id or "unknown"
    metadata = _metadata_to_mapping(view.job_metadata)
    try:
        name = router(metadata)
    except Exception as exc:
        logger.error("Custom router raised for job '%s'; rejecting session.", job_id)
        raise ValueError(
            f"Custom router raised while resolving the agent for job '{job_id}'."
        ) from exc
    if name is None:
        return None
    if name not in agent_names:
        raise ValueError(
            f"Custom router returned unknown agent '{name}' for job '{job_id}'."
        )
    logger.info("Router resolved agent '%s' for job '%s'.", name, job_id)
    return name


def _resolve_agent_name(
    agent_names: Collection[str],
    view: SessionView,
    *,
    router: AgentRouter | None = None,
) -> str:
    """Resolve which registered agent name handles a call: router, then the chain.

    Backend-neutral: every backend routes with the same precedence (custom router,
    then job / room metadata, then room-name prefix, then first registered), then
    looks the name up in its own registry.
    """
    if router is not None:
        name = _resolve_via_router(agent_names, view, router)
        if name is not None:
            return name
    for strategy in _ROUTING_STRATEGIES:
        name = strategy.resolve(agent_names, view)
        if name is not None:
            return name
    raise RuntimeError("No routing strategy resolved an agent.")  # pragma: no cover


def _resolve_agent_config(
    agents: Mapping[str, AgentConfig],
    ctx: Any,
    *,
    router: AgentRouter | None = None,
) -> AgentConfig:
    """Resolve the agent config for a session: name resolution, then lookup.

    ``ctx`` is a livekit ``JobContext`` (or any object shaped like one). It is
    adapted to the backend-neutral :class:`SessionView` once here, so the router
    and every routing strategy read only that seam, never a framework type.
    """
    if not agents:
        raise RuntimeError("No agents are registered in the pool.")
    view = for_livekit(ctx)
    name = _resolve_agent_name(agents.keys(), view, router=router)
    return agents[name]
