"""MAH-84: orchestrate a reload from a file change to a re-bound pool.

The coordinator is the brain that the :class:`~openrtc.runtime.file_watcher.FileWatcher`
drives. For each changed file it finds the registered agent(s) whose ``source_path``
matches, re-imports the module (rollback-safe), re-binds the live sessions, and emits
a :class:`~openrtc.reload.base_reload.ReloadEvent`. One agent is reloaded at a time.

Its collaborators (reloader, rebinder, pin predicate, clock, report sink) are injected
so the orchestration is testable without touching the filesystem or a real session.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from openrtc.reload.base_reload import ReloadEvent
from openrtc.reload.module_reloader import reload_agent_module
from openrtc.reload.pin import is_pinned as _is_pinned
from openrtc.reload.rebind import rebind_agent
from openrtc.reload.reporter import log_reload_event

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from livekit.agents import Agent, AgentSession

    from openrtc.core.config import AgentConfig
    from openrtc.reload.base_reload import ReloadResult
    from openrtc.reload.session_registry import LiveSessionRegistry
    from openrtc.runtime.file_watcher import FileChange

    Reloader = Callable[[Path, type[Agent]], ReloadResult]
    Rebinder = Callable[..., int]
    Report = Callable[[ReloadEvent], None]
    PinPredicate = Callable[[AgentSession[Any]], bool]
    Clock = Callable[[], float]

logger = logging.getLogger("openrtc")

__all__ = ["ReloadCoordinator"]


class ReloadCoordinator:
    """Turn debounced file changes into reloaded, re-bound agents."""

    def __init__(
        self,
        agents: dict[str, AgentConfig],
        registry: LiveSessionRegistry,
        *,
        report: Report | None = None,
        reloader: Reloader = reload_agent_module,
        rebinder: Rebinder = rebind_agent,
        is_pinned: PinPredicate = _is_pinned,
        clock: Clock = time.monotonic,
    ) -> None:
        self._agents = agents
        self._registry = registry
        self._report: Report = report if report is not None else log_reload_event
        self._reloader = reloader
        self._rebinder = rebinder
        self._is_pinned = is_pinned
        self._clock = clock

    async def on_change(self, changes: list[FileChange]) -> None:
        """Handle one debounced batch of file changes from the watcher."""
        by_path = self._configs_by_source_path()
        for change in changes:
            for config in by_path.get(change.path.resolve(), []):
                if change.change_type == "deleted":
                    logger.warning(
                        "[reload] %s deleted; keeping the loaded '%s' class",
                        change.path,
                        config.name,
                    )
                    continue
                self._reload_one(config, change.path)

    def _configs_by_source_path(self) -> dict[Path, list[AgentConfig]]:
        by_path: dict[Path, list[AgentConfig]] = {}
        for config in self._agents.values():
            if config.source_path is None:
                continue
            by_path.setdefault(config.source_path.resolve(), []).append(config)
        return by_path

    def _reload_one(self, config: AgentConfig, path: Path) -> None:
        start = self._clock()
        result = self._reloader(path, config.agent_cls)
        if result.status == "failed" or result.agent_cls is None:
            self._report(
                ReloadEvent(
                    agent_name=config.name,
                    status="failed",
                    sessions_swapped=0,
                    duration_ms=(self._clock() - start) * 1000.0,
                    source_path=str(path),
                    error=result.error,
                )
            )
            return
        swapped = self._rebinder(
            config, result.agent_cls, self._registry, is_pinned=self._is_pinned
        )
        self._report(
            ReloadEvent(
                agent_name=config.name,
                status="swapped",
                sessions_swapped=swapped,
                duration_ms=(self._clock() - start) * 1000.0,
                source_path=str(path),
            )
        )
