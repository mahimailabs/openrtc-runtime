"""Name-to-builder registry for spawn-safe runtime selection (isolation modes)."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from livekit.agents import AgentServer

__all__ = ["ServerParams", "resolve_server_builder"]


@dataclass(frozen=True, slots=True)
class ServerParams:
    """Shared worker options every server builder receives."""

    max_concurrent_sessions: int
    consecutive_failure_limit: int
    drain_timeout: int


# isolation mode -> (module path, builder attribute). Lazy import keeps the
# coroutine path out of process-only callers' import graph.
_SERVER_BUILDERS: dict[str, tuple[str, str]] = {
    "coroutine": ("openrtc.execution.coroutine_server", "build_server"),
    "process": ("openrtc.core.registry", "_build_process_server"),
}


def _build_process_server(params: ServerParams) -> AgentServer:
    """Build the v0.0.x process-mode server (plain AgentServer)."""
    from livekit.agents import AgentServer

    return AgentServer(drain_timeout=params.drain_timeout)


def resolve_server_builder(
    isolation: str,
) -> Callable[[ServerParams], AgentServer]:
    """Return the server builder for an isolation mode (lazy import)."""
    try:
        module_path, attr = _SERVER_BUILDERS[isolation]
    except KeyError as exc:
        raise ValueError(f"Unknown isolation mode {isolation!r}.") from exc
    module = importlib.import_module(module_path)
    builder: Callable[[ServerParams], AgentServer] = getattr(module, attr)
    return builder
