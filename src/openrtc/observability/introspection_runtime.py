"""Introspection runtime: the one object that assembles ``openrtc top`` (MAH-92).

The worker owns a single :class:`IntrospectionRuntime`. It bundles the pieces
built across MAH-88/89/90/91/92 into one lifecycle:

- :class:`SessionIntrospectionRegistry` (the ``SessionObserver`` the pool wires),
- the per-session **memory** sampler (equal-share RSS, MAH-88),
- the per-session **CPU** sampler + task->session factory (MAH-89),
- the **slow-session** detector (event-loop-block attribution, MAH-90),
- the local Unix-socket **IPC server** that ``openrtc top`` connects to (MAH-92).

``snapshot()`` joins those signals into the ``SessionRow`` list the inspector
renders. It stays inside openrtc's runtime lane: it reports only worker-internal
introspection (identity, attributed memory/CPU, loop-block status). Cost, quality,
and pipeline latency remain voicegateway's concern; the only cross-lane fields it
emits are ``agent_name`` and ``metadata['tenant']``, straight off the observer
payload.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from openrtc.observability.introspection import (
    SessionIntrospectionRegistry,
    SessionRow,
    build_session_rows,
)
from openrtc.observability.introspection_ipc import (
    IntrospectionServer,
    default_socket_path,
)
from openrtc.observability.resident_set import process_resident_set_bytes
from openrtc.observability.session_cpu import (
    SessionCpuSampler,
    default_running_session_provider,
)
from openrtc.observability.session_memory import SessionMemorySampler
from openrtc.observability.slow_session import (
    LoopBlockEvent,
    SlowSessionDetector,
)
from openrtc.observability.task_attribution import install_session_task_factory

if TYPE_CHECKING:
    from pathlib import Path

    from livekit.agents import AgentSession

__all__ = ["IntrospectionRuntime"]

_DEFAULT_SLOW_THRESHOLD_MS = 50.0
_DEFAULT_SLOW_WINDOW_S = 5.0

IsPinned = Callable[["AgentSession[Any]"], bool]
TimeSource = Callable[[], float]
RssReader = Callable[[], "int | None"]


def _never_pinned(_session: AgentSession[Any]) -> bool:
    """Default pin predicate: v0.3 does not pin sessions server-side.

    Interactive pin-to-top is a client-side ``openrtc top`` affordance deferred
    past v0.3; the worker reports every session as unpinned.
    """
    return False


@dataclass(slots=True)
class _RunningState:
    """Loop-bound resources, set atomically by ``start`` and torn down by ``aclose``."""

    stop: asyncio.Event
    cpu: SessionCpuSampler
    restore_task_factory: Callable[[], None]
    tasks: list[asyncio.Task[None]]


class IntrospectionRuntime:
    """Assemble and run the introspection stack behind ``openrtc top``."""

    def __init__(
        self,
        *,
        socket_path: Path | None = None,
        slow_session_threshold_ms: float = _DEFAULT_SLOW_THRESHOLD_MS,
        slow_window_s: float = _DEFAULT_SLOW_WINDOW_S,
        is_pinned: IsPinned = _never_pinned,
        time_source: TimeSource = time.time,
        rss_reader: RssReader = process_resident_set_bytes,
    ) -> None:
        self.registry = SessionIntrospectionRegistry()
        self._socket_path = socket_path or default_socket_path()
        self._threshold_ms = slow_session_threshold_ms
        self._slow_window_s = slow_window_s
        self._is_pinned = is_pinned
        self._time_source = time_source
        # session_id -> last block time (in _time_source units); a session is
        # "slow" while it stays within slow_window_s of its last block.
        self._recent_blocks: dict[str, float] = {}
        self._memory = SessionMemorySampler(
            sessions_provider=self.registry.active_agents,
            rss_reader=rss_reader,
        )
        self._server = IntrospectionServer(
            snapshot_provider=self.snapshot,
            socket_path=self._socket_path,
        )
        # Populated on start() because they need the worker's running loop.
        self._cpu: SessionCpuSampler | None = None
        self._running: _RunningState | None = None

    @property
    def socket_path(self) -> Path:
        """The Unix socket ``openrtc top`` connects to."""
        return self._socket_path

    def _on_block(self, event: LoopBlockEvent) -> None:
        """Record an attributed loop block so the session shows as slow in top."""
        if event.session_id is not None:
            self._recent_blocks[event.session_id] = self._time_source()

    def _current_slow_ids(self, now: float) -> set[str]:
        """Return session_ids that blocked the loop within the slow window."""
        return {
            sid
            for sid, when in self._recent_blocks.items()
            if now - when <= self._slow_window_s
        }

    def snapshot(self) -> list[SessionRow]:
        """Join every signal into the current ``openrtc top`` rows."""
        now = self._time_source()
        # Prune stale block marks so the set does not grow unbounded.
        self._recent_blocks = {
            sid: when
            for sid, when in self._recent_blocks.items()
            if now - when <= self._slow_window_s
        }
        cpu = self._cpu.report() if self._cpu is not None else {}
        return build_session_rows(
            registry=self.registry,
            memory=self._memory.snapshot(),
            cpu=cpu,
            slow_session_ids=self._current_slow_ids(now),
            is_pinned=self._is_pinned,
            now=now,
        )

    async def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Install the task factory, start the samplers, and serve the socket."""
        if self._running is not None:
            return
        stop = asyncio.Event()
        restore = install_session_task_factory(loop)
        cpu = SessionCpuSampler(
            sessions_provider=self.registry.active_agents,
            running_session_provider=lambda: default_running_session_provider(loop),
        )
        cpu.start()
        detector = SlowSessionDetector(
            blocked_session_provider=cpu.last_running_session,
            threshold_ms=self._threshold_ms,
            on_block=self._on_block,
        )
        tasks = [
            loop.create_task(self._memory.run(stop)),
            loop.create_task(detector.run(stop)),
        ]
        await self._server.start()
        self._cpu = cpu  # read by snapshot()
        self._running = _RunningState(
            stop=stop, cpu=cpu, restore_task_factory=restore, tasks=tasks
        )

    async def aclose(self) -> None:
        """Stop the samplers, restore the task factory, and remove the socket; idempotent."""
        running = self._running
        if running is None:
            return
        self._running = None
        self._cpu = None
        running.stop.set()
        for task in running.tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        running.cpu.stop()
        running.restore_task_factory()
        await self._server.aclose()
