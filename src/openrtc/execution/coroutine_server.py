"""``_CoroutineAgentServer`` swap shim.

Subclass of ``livekit.agents.AgentServer`` that swaps the worker's
internal ``ProcPool`` for our :class:`CoroutinePool`. Strategy A from
``docs/design/agent-server-integration.md``: monkey-patch the
``ipc.proc_pool.ProcPool`` symbol for the duration of :meth:`run` so the
existing AgentServer construction logic at ``worker.py:587-601`` ends up
calling our class with the same kwargs. The patch is scoped to one
``run()`` lifetime; constructor-time and aclose-time state on
``AgentServer`` are unaffected.

Also installs a ``load_fnc`` that reads from
``CoroutinePool.current_load`` so LiveKit dispatch sees the coroutine
pool's actual session saturation instead of the inherited CPU-based
default.
"""

from __future__ import annotations

import asyncio
from typing import Any

import livekit.agents.ipc.proc_pool as _proc_pool_mod
from livekit.agents import AgentServer

from openrtc.execution.coroutine import CoroutinePool


class _CoroutineAgentServer(AgentServer):
    """``AgentServer`` that constructs a ``CoroutinePool`` instead of ``ProcPool``.

    Args:
        *args: Forwarded to :class:`AgentServer`.
        max_concurrent_sessions: Backpressure threshold passed to the
            constructed :class:`CoroutinePool`. The same value is then
            referenced by the registered ``load_fnc``.
        **kwargs: Forwarded to :class:`AgentServer`.
    """

    def __init__(
        self,
        *args: Any,
        max_concurrent_sessions: int = 50,
        consecutive_failure_limit: int = 5,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        if not isinstance(max_concurrent_sessions, int) or isinstance(
            max_concurrent_sessions, bool
        ):
            raise TypeError(
                "max_concurrent_sessions must be an int, "
                f"got {type(max_concurrent_sessions).__name__}."
            )
        if max_concurrent_sessions < 1:
            raise ValueError(
                f"max_concurrent_sessions must be >= 1, got {max_concurrent_sessions}."
            )
        if not isinstance(consecutive_failure_limit, int) or isinstance(
            consecutive_failure_limit, bool
        ):
            raise TypeError(
                "consecutive_failure_limit must be an int, "
                f"got {type(consecutive_failure_limit).__name__}."
            )
        if consecutive_failure_limit < 1:
            raise ValueError(
                "consecutive_failure_limit must be >= 1, "
                f"got {consecutive_failure_limit}."
            )
        self._max_concurrent_sessions = max_concurrent_sessions
        self._consecutive_failure_limit = consecutive_failure_limit
        self._coroutine_pool: CoroutinePool | None = None

    @property
    def coroutine_pool(self) -> CoroutinePool | None:
        """Return the constructed :class:`CoroutinePool` once :meth:`run` has built it."""
        return self._coroutine_pool

    async def run(
        self,
        *,
        devmode: bool = False,
        unregistered: bool = False,
    ) -> None:
        """Patch ``ipc.proc_pool.ProcPool`` and delegate to ``AgentServer.run``.

        The patch is scoped to one ``run()`` invocation. The factory
        captures the constructed pool on ``self._coroutine_pool`` so
        callers (and the registered ``load_fnc``) can read live state.
        """
        original_proc_pool_cls = _proc_pool_mod.ProcPool
        max_sess = self._max_concurrent_sessions
        failure_limit = self._consecutive_failure_limit
        captured: dict[str, CoroutinePool | None] = {"pool": None}

        # Supervisor: when the pool reports that it has tripped the
        # consecutive-failure limit, schedule self.aclose() so the worker
        # exits and the deployment platform restarts it.
        def _on_consecutive_failure_limit(failures: int) -> None:
            import logging

            logging.getLogger("openrtc.execution.coroutine_server").error(
                "supervisor: %d consecutive session failures observed; "
                "invoking AgentServer.aclose() so the worker can exit",
                failures,
            )
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            loop.create_task(self.aclose())

        def _coroutine_pool_factory(**pool_kwargs: Any) -> CoroutinePool:
            pool = CoroutinePool(
                **pool_kwargs,
                max_concurrent_sessions=max_sess,
                consecutive_failure_limit=failure_limit,
                on_consecutive_failure_limit=_on_consecutive_failure_limit,
            )
            captured["pool"] = pool
            return pool

        _proc_pool_mod.ProcPool = _coroutine_pool_factory  # type: ignore[assignment, misc]

        def _coroutine_load_fnc() -> float:
            pool = captured["pool"]
            if pool is None:
                return 0.0
            return pool.current_load()

        previous_load_fnc = self._load_fnc
        self._load_fnc = _coroutine_load_fnc

        try:
            await super().run(devmode=devmode, unregistered=unregistered)
        finally:
            _proc_pool_mod.ProcPool = original_proc_pool_cls  # type: ignore[misc]
            self._load_fnc = previous_load_fnc
            self._coroutine_pool = captured["pool"]
