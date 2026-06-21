"""Process-mode runtime: one OS process per session via livekit's default server."""

from __future__ import annotations

from typing import TYPE_CHECKING

from livekit.agents import AgentServer

if TYPE_CHECKING:
    from openrtc.runtime.registry import ServerParams

__all__ = ["build_server"]


def build_server(params: ServerParams) -> AgentServer:
    """Build the v0.0.x process-mode server (plain AgentServer)."""
    return AgentServer(drain_timeout=params.drain_timeout)
