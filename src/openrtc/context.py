"""Public per-session context accessors for agent code (MAH-101).

Agent code running inside a session can read the current session's identity
without reaching into OpenRTC internals:

    from openrtc.context import current_tenant_id

    class MyAgent(Agent):
        async def on_enter(self) -> None:
            tenant = current_tenant_id()  # e.g. "acme", or "default"

These read contextvars bound for the session's whole task tree, so they work in
``on_enter``, tool calls, and any task spawned within the session. Outside a
session (no bound context) they return ``None``.
"""

from __future__ import annotations

from openrtc.observability.session_context import (
    current_agent_name,
    current_session_id,
    current_tenant_id,
)

__all__ = [
    "current_agent_name",
    "current_session_id",
    "current_tenant_id",
]
