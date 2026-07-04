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
    # Worker memory watermarks (MB). Defaults mirror livekit's WorkerOptions:
    # warn at 1000, limit 0 (disabled). In process mode livekit enforces these
    # per-subprocess natively; in coroutine mode they drive the worker-level
    # RSS watermark (one process, so caps cannot be per-session).
    memory_warn_mb: float = 1000.0
    memory_limit_mb: float = 0.0


# isolation mode -> (module path, builder attribute). Lazy import keeps the
# coroutine path out of process-only callers' import graph.
_SERVER_BUILDERS: dict[str, tuple[str, str]] = {
    "coroutine": ("openrtc.runtime.coroutine_server", "build_server"),
    "process": ("openrtc.runtime.process_runtime", "build_server"),
}


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
