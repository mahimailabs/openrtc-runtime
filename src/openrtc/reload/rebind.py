"""MAH-82: the atomic agent re-bind protocol.

When a new agent class is loaded, ``rebind_agent`` swaps the registry's
``AgentConfig.agent_cls`` (so every *new* session builds the new class) and then
re-binds each *live* session that is still on the old class via livekit's
``AgentSession.update_agent``. livekit blocks new user turns during the transition
and drains the in-flight turn, so the current turn finishes on the old class and
the next turn runs the new one, with no WebSocket drop.

The config swap and the fan-out happen in one synchronous pass with no ``await``
between them, so all sessions observe the swap atomically. Pinned sessions
(MAH-83) are skipped, and a failure to re-bind one session is isolated so it can
never abort the others.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from livekit.agents import Agent, AgentSession

    from openrtc.core.config import AgentConfig
    from openrtc.reload.session_registry import LiveSessionRegistry

logger = logging.getLogger("openrtc")

__all__ = ["rebind_agent"]


def _never_pinned(_session: AgentSession[Any]) -> bool:
    return False


def rebind_agent(
    config: AgentConfig,
    new_cls: type[Agent],
    registry: LiveSessionRegistry,
    *,
    is_pinned: Callable[[AgentSession[Any]], bool] = _never_pinned,
) -> int:
    """Swap ``config.agent_cls`` and re-bind live sessions; return the count swapped.

    Args:
        config: The registered agent whose class is being replaced (mutated in place).
        new_cls: The freshly reloaded agent class.
        registry: The live-session registry to scan for sessions of this agent.
        is_pinned: Predicate marking sessions that opted out of mid-flow swaps.

    Returns:
        The number of live sessions re-bound to ``new_cls``.
    """
    old_cls = config.agent_cls
    config.agent_cls = new_cls
    if new_cls is old_cls:
        return 0

    swapped = 0
    for session in registry.sessions_for(config.name):
        if is_pinned(session):
            continue
        if type(session.current_agent) is not old_cls:
            # Already on the new class, or handed off elsewhere; leave it be.
            continue
        try:
            # User Agent subclasses override __init__ with no required args, the
            # same call shape core/wiring.py uses to build a session's agent.
            session.update_agent(new_cls())  # type: ignore[call-arg]
        except Exception:  # noqa: BLE001 - one bad session must not abort the swap
            logger.warning(
                "[reload] failed to re-bind a live session of agent '%s'",
                config.name,
                exc_info=True,
            )
            continue
        swapped += 1
    return swapped
