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
from collections.abc import Callable, Iterator
from typing import Any

import livekit.agents.ipc.proc_pool as _proc_pool_mod
from livekit.agents import AgentServer

from openrtc.core.registry import ServerParams
from openrtc.core.validation import require_positive_int
from openrtc.execution.coroutine import CoroutinePool

logger = logging.getLogger("openrtc.execution.coroutine_server")


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

    @property
    def coroutine_pool(self) -> CoroutinePool | None:
        """Return the constructed :class:`CoroutinePool` once :meth:`run` has built it."""
        return self._coroutine_pool

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

    def _build_pool_factory(self) -> Callable[..., CoroutinePool]:
        """Return the ``ProcPool`` replacement factory that builds a ``CoroutinePool``."""

        def _factory(**pool_kwargs: Any) -> CoroutinePool:
            pool = CoroutinePool(
                **pool_kwargs,
                max_concurrent_sessions=self._max_concurrent_sessions,
                consecutive_failure_limit=self._consecutive_failure_limit,
                on_consecutive_failure_limit=self._on_consecutive_failure_limit,
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
        """Swap ipc.proc_pool.ProcPool for our pool factory for one run()."""
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
        """Patch ``ipc.proc_pool.ProcPool`` and delegate to ``AgentServer.run``."""
        with self._patched_proc_pool():
            await super().run(devmode=devmode, unregistered=unregistered)


def build_server(params: ServerParams) -> _CoroutineAgentServer:
    """Build the coroutine-mode server from shared worker params."""
    return _CoroutineAgentServer(
        max_concurrent_sessions=params.max_concurrent_sessions,
        consecutive_failure_limit=params.consecutive_failure_limit,
        drain_timeout=params.drain_timeout,
    )
