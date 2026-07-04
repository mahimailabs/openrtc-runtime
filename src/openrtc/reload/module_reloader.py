"""MAH-81: rollback-safe re-import of an edited agent module.

A bad save (``SyntaxError``, ``ImportError``, any exception at import time) must
never poison the running pool. The module is validated and executed into a fresh
module object; ``sys.modules`` is only left mutated when the import succeeds and a
local ``Agent`` subclass is found. On any failure the previously loaded module is
restored and the caller keeps the class it already had.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from typing import TYPE_CHECKING

from livekit.agents import Agent

from openrtc.core.discovery import _discovered_module_name, _find_local_agent_subclass
from openrtc.reload.base_reload import ReloadResult

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("openrtc")

__all__ = ["reload_agent_module"]


def reload_agent_module(source_path: Path, current_cls: type[Agent]) -> ReloadResult:
    """Re-import ``source_path`` and return the new agent class, or a failure.

    Args:
        source_path: The ``.py`` file backing the agent.
        current_cls: The class currently registered, used to pick the matching
            subclass by name when the module defines more than one.

    Returns:
        A :class:`ReloadResult`; ``swapped`` carries the new class, ``failed``
        carries an error string and leaves the running module unchanged.
    """
    try:
        source_text = source_path.read_text()
    except OSError as exc:
        return ReloadResult(status="failed", error=f"{source_path}: {exc}")

    # Compile the freshly read source ourselves. This surfaces a SyntaxError with
    # a clean file:line before sys.modules is touched, and it bypasses the loader's
    # __pycache__ (which is keyed on mtime+size and can serve stale bytecode when an
    # edit keeps the file the same size within one filesystem mtime tick).
    try:
        code = compile(source_text, str(source_path), "exec")
    except SyntaxError as exc:
        return ReloadResult(
            status="failed",
            error=f"{source_path}:{exc.lineno}: {exc.msg}",
        )

    module_name = _discovered_module_name(source_path)
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None:
        return ReloadResult(
            status="failed",
            error=f"{source_path}: could not create an import spec",
        )

    new_module = importlib.util.module_from_spec(spec)
    old_module = sys.modules.get(module_name)
    sys.modules[module_name] = new_module
    try:
        exec(code, new_module.__dict__)  # noqa: S102 - executing user agent code by design
        new_cls = _select_agent_class(new_module, current_cls)
    except Exception as exc:  # noqa: BLE001 - any import-time failure rolls back
        if old_module is not None:
            sys.modules[module_name] = old_module
        else:
            sys.modules.pop(module_name, None)
        logger.error("[reload] %s: %s: %s", source_path, type(exc).__name__, exc)
        return ReloadResult(
            status="failed",
            error=f"{source_path}: {type(exc).__name__}: {exc}",
        )

    return ReloadResult(status="swapped", agent_cls=new_cls)


def _select_agent_class(module: object, current_cls: type[Agent]) -> type[Agent]:
    """Return the reloaded counterpart of *current_cls* from *module*."""
    candidate = getattr(module, current_cls.__name__, None)
    if (
        isinstance(candidate, type)
        and issubclass(candidate, Agent)
        and candidate is not Agent
    ):
        return candidate
    # Fall back to structural discovery (raises RuntimeError if none found,
    # which the caller treats as a failed reload).
    return _find_local_agent_subclass(module)  # type: ignore[arg-type]
