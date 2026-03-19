from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .pool import AgentConfig, AgentDiscoveryConfig, AgentPool, agent_config

try:
    __version__ = version("openrtc")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "AgentConfig",
    "AgentDiscoveryConfig",
    "AgentPool",
    "__version__",
    "agent_config",
]
