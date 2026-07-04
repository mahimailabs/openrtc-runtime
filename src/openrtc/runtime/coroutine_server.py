"""``_CoroutineAgentServer`` swap shim.

Strategy A: monkey-patch ``ipc.proc_pool.ProcPool`` for the duration of
:meth:`run` so AgentServer's construction logic calls our
:class:`CoroutinePool` with the same kwargs. The patch is scoped to one
``run()`` lifetime; constructor-time and aclose-time state are unaffected.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import TYPE_CHECKING, Any

import livekit.agents.ipc.proc_pool as _proc_pool_mod
from livekit.agents import AgentServer

from openrtc.runtime.coroutine_runtime import CoroutinePool
from openrtc.runtime.file_watcher import FileChange, FileWatcher
from openrtc.runtime.registry import ServerParams
from openrtc.utils.validation import require_positive_int

if TYPE_CHECKING:
    from pathlib import Path

    from openrtc.observability.introspection_runtime import IntrospectionRuntime

    ReloadCallback = Callable[[list[FileChange]], Awaitable[None]]

logger = logging.getLogger("openrtc.runtime.coroutine_server")


class _CoroutineAgentServer(AgentServer):
    """``AgentServer`` that constructs a ``CoroutinePool`` instead of ``ProcPool``."""

    def __init__(
        self,
        *args: Any,
        max_concurrent_sessions: int = 50,
        consecutive_failure_limit: int = 5,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._max_concurrent_sessions = require_positive_int(
            "max_concurrent_sessions", max_concurrent_sessions
        )
        self._consecutive_failure_limit = require_positive_int(
            "consecutive_failure_limit", consecutive_failure_limit
        )
        self._coroutine_pool: CoroutinePool | None = None
        self._reload_on_change: ReloadCallback | None = None
        self._reload_watch_paths: list[Path] | None = None
        self._reload_watcher: FileWatcher | None = None
        self._introspection: IntrospectionRuntime | None = None

    @property
    def coroutine_pool(self) -> CoroutinePool | None:
        """Return the constructed :class:`CoroutinePool` once :meth:`run` has built it."""
        return self._coroutine_pool

    def attach_introspection(self, introspection: IntrospectionRuntime) -> None:
        """Enable ``openrtc top``: run this introspection stack inside the pool.

        The stack is handed to every :class:`CoroutinePool` this server builds so
        its samplers and IPC socket share the pool's start/close lifecycle.
        """
        self._introspection = introspection

    def attach_reload(
        self,
        on_change: ReloadCallback,
        watch_paths: list[Path] | None = None,
    ) -> None:
        """Enable hot reload: run a FileWatcher feeding *on_change* during run().

        Passing the callback rather than the coordinator keeps ``runtime`` free of
        any dependency on the ``reload`` package. ``watch_paths=None`` auto-discovers
        the worker's user-edited modules.
        """
        self._reload_on_change = on_change
        self._reload_watch_paths = watch_paths

    @property
    def reload_watcher(self) -> FileWatcher | None:
        """The live FileWatcher while run() is active, else ``None``."""
        return self._reload_watcher

    @contextlib.asynccontextmanager
    async def _reload_watching(self) -> AsyncIterator[None]:
        """Start the FileWatcher for the run() lifetime; a no-op if reload is off."""
        if self._reload_on_change is None:
            yield
            return
        watcher = FileWatcher(self._reload_on_change, paths=self._reload_watch_paths)
        self._reload_watcher = watcher
        await watcher.start()
        try:
            yield
        finally:
            await watcher.stop()
            self._reload_watcher = None

    def _on_consecutive_failure_limit(self, failures: int) -> None:
        """Log the failure cluster and schedule ``aclose()`` to restart the worker."""
        logger.error(
            "supervisor: %d consecutive session failures observed; "
            "invoking AgentServer.aclose() so the worker can exit",
            failures,
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.aclose())

    def _on_memory_limit_exceeded(self, rss_mb: float) -> None:
        """Schedule ``aclose()`` so the worker exits and is restarted after an RSS breach."""
        logger.error(
            "supervisor: worker RSS %.0f MB exceeded memory_limit_mb; "
            "invoking AgentServer.aclose() so the worker can exit and restart",
            rss_mb,
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.aclose())

    def _build_pool_factory(self) -> Callable[..., CoroutinePool]:
        """Return the ``ProcPool`` replacement factory that builds a ``CoroutinePool``."""

        def _factory(**pool_kwargs: Any) -> CoroutinePool:
            pool = CoroutinePool(
                **pool_kwargs,
                max_concurrent_sessions=self._max_concurrent_sessions,
                consecutive_failure_limit=self._consecutive_failure_limit,
                on_consecutive_failure_limit=self._on_consecutive_failure_limit,
                on_memory_limit_exceeded=self._on_memory_limit_exceeded,
                introspection=self._introspection,
            )
            self._coroutine_pool = pool
            return pool

        return _factory

    def _coroutine_load_fnc(self) -> float:
        """Return pool load for LiveKit dispatch; ``0.0`` before pool construction."""
        pool = self._coroutine_pool
        if pool is None:
            return 0.0
        return pool.current_load()

    @contextlib.contextmanager
    def _patched_proc_pool(self) -> Iterator[None]:
        """Swap ipc.proc_pool.ProcPool and self._load_fnc for the duration of one run()."""
        original_proc_pool_cls = _proc_pool_mod.ProcPool
        previous_load_fnc = self._load_fnc
        _proc_pool_mod.ProcPool = self._build_pool_factory()  # type: ignore[assignment, misc]
        self._load_fnc = self._coroutine_load_fnc
        try:
            yield
        finally:
            _proc_pool_mod.ProcPool = original_proc_pool_cls  # type: ignore[misc]
            self._load_fnc = previous_load_fnc

    async def run(
        self,
        *,
        devmode: bool = False,
        unregistered: bool = False,
    ) -> None:
        """Patch ipc.proc_pool.ProcPool for one run() invocation, then delegate to AgentServer.run."""
        # Register the EOU inference runner before worker.py decides whether to
        # start InferenceProcExecutor. worker.py checks
        # _InferenceRunner.registered_runners *before* calling setup_fnc
        # (prewarm), so the lazy import inside _prewarm_worker is too late.
        # Importing MultilingualModel here registers the runner as a side effect,
        # mirroring how standard livekit-agents users import at the top level.
        with contextlib.suppress(Exception):
            from livekit.plugins.turn_detector.multilingual import (  # noqa: F401
                MultilingualModel as _M,
            )
        async with self._reload_watching(), self._patched_proc_pool_async():
            await super().run(devmode=devmode, unregistered=unregistered)

    @contextlib.asynccontextmanager
    async def _patched_proc_pool_async(self) -> AsyncIterator[None]:
        """Async wrapper over the sync proc-pool patch so run() nests one ``async with``."""
        with self._patched_proc_pool():
            yield


def build_server(params: ServerParams) -> _CoroutineAgentServer:
    """Build the coroutine-mode server from shared worker params."""
    return _CoroutineAgentServer(
        max_concurrent_sessions=params.max_concurrent_sessions,
        consecutive_failure_limit=params.consecutive_failure_limit,
        drain_timeout=params.drain_timeout,
        job_memory_warn_mb=params.memory_warn_mb,
        job_memory_limit_mb=params.memory_limit_mb,
    )
