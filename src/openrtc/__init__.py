from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .core.pool import AgentConfig, AgentDiscoveryConfig, AgentPool, agent_config
from .types import ProviderValue

try:
    __version__ = version("openrtc")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "AgentConfig",
    "AgentDiscoveryConfig",
    "AgentPool",
    "ProviderValue",
    "__version__",
    "agent_config",
]
