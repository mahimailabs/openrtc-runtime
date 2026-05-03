"""Filesystem-driven agent discovery and dynamic module loading."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import sys
from hashlib import sha1
from pathlib import Path
from types import ModuleType
from typing import cast

from livekit.agents import Agent

from openrtc.core.config import _AGENT_METADATA_ATTR, AgentDiscoveryConfig

logger = logging.getLogger("openrtc")


def _load_module_from_path(module_name: str, module_path: Path) -> ModuleType:
    resolved_path = module_path.resolve()
    existing_module = sys.modules.get(module_name)
    if existing_module is not None:
        existing_file = getattr(existing_module, "__file__", None)
        if existing_file is not None and Path(existing_file).resolve() == resolved_path:
            return existing_module

    spec = importlib.util.spec_from_file_location(module_name, resolved_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not create import spec for {resolved_path}.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _discovered_module_name(module_path: Path) -> str:
    resolved_path = module_path.resolve()
    digest = sha1(str(resolved_path).encode("utf-8")).hexdigest()[:12]
    return f"openrtc_discovered_{resolved_path.stem}_{digest}"


def _try_get_module_path(agent_cls: type[Agent]) -> Path | None:
    try:
        source_path = inspect.getsourcefile(agent_cls)
    except (OSError, TypeError):
        source_path = None
    if source_path is None:
        return None
    return Path(source_path).resolve()


def _load_agent_module(module_path: Path) -> ModuleType:
    module_name = _discovered_module_name(module_path)
    try:
        return _load_module_from_path(module_name, module_path)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to import agent module '{module_path.name}': {exc}"
        ) from exc


def _find_local_agent_subclass(module: ModuleType) -> type[Agent]:
    for value in vars(module).values():
        if (
            isinstance(value, type)
            and issubclass(value, Agent)
            and value is not Agent
            and value.__module__ == module.__name__
        ):
            return value

    raise RuntimeError(
        f"Module '{module.__name__}' does not define a local Agent subclass."
    )


def _resolve_discovery_metadata(agent_cls: type[Agent]) -> AgentDiscoveryConfig:
    metadata = getattr(agent_cls, _AGENT_METADATA_ATTR, None)
    if metadata is not None:
        return cast(AgentDiscoveryConfig, metadata)

    return AgentDiscoveryConfig()
