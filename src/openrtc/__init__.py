from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .core.config import AgentConfig, AgentDiscoveryConfig, agent_config
from .core.pool import AgentPool
from .observability.base_observer import (
    SessionInfo,
    SessionObserver,
    SessionOutcome,
    SessionStatus,
)
from .reload.pin import is_pinned, pin_reload
from .runtime.file_watcher import FileChange, FileWatcher
from .utils.types import ProviderValue, RequestFilter

try:
    __version__ = version("openrtc")
except PackageNotFoundError:
    # Fallback when openrtc is imported without being installed (e.g. running
    # from a source checkout without `pip install -e .`). Kept in sync with
    # `[tool.hatch.version.raw-options].fallback_version` in pyproject.toml.
    __version__ = "0.1.0.dev0"

__all__ = [
    "AgentConfig",
    "AgentDiscoveryConfig",
    "AgentPool",
    "FileChange",
    "FileWatcher",
    "ProviderValue",
    "RequestFilter",
    "SessionInfo",
    "SessionObserver",
    "SessionOutcome",
    "SessionStatus",
    "__version__",
    "agent_config",
    "is_pinned",
    "pin_reload",
]
