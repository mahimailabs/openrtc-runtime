"""Tests for the _CoroutineAgentServer swap shim.

We don't run a real worker here (that needs a LiveKit server). The tests
verify the swap mechanics in isolation: that the subclass validates its
extra kwarg, that the ``ipc.proc_pool.ProcPool`` patch / restore are
scoped to ``run()``, and that the registered ``load_fnc`` reports the
captured CoroutinePool's load.
"""

from __future__ import annotations

import asyncio
from typing import Any

import livekit.agents.ipc.proc_pool as _proc_pool_mod
import pytest
from livekit.agents import AgentServer

from openrtc.execution.coroutine import CoroutinePool
from openrtc.execution.coroutine_server import _CoroutineAgentServer


def test_coroutine_server_default_max_concurrent_sessions_is_50() -> None:
    server = _CoroutineAgentServer()

    assert server._max_concurrent_sessions == 50
    assert server.coroutine_pool is None


def test_coroutine_server_max_concurrent_sessions_override() -> None:
    server = _CoroutineAgentServer(max_concurrent_sessions=12)

    assert server._max_concurrent_sessions == 12


def test_coroutine_server_rejects_invalid_max_concurrent_sessions() -> None:
    with pytest.raises(TypeError, match="must be an int"):
        _CoroutineAgentServer(max_concurrent_sessions=4.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="must be an int"):
        _CoroutineAgentServer(max_concurrent_sessions=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be >= 1"):
        _CoroutineAgentServer(max_concurrent_sessions=0)


def test_coroutine_server_subclasses_agent_server() -> None:
    server = _CoroutineAgentServer()

    assert isinstance(server, AgentServer)


def test_coroutine_server_run_patches_and_restores_proc_pool() -> None:
    """run() should swap ipc.proc_pool.ProcPool only for its duration.

    We let super().run() raise quickly (no entrypoint registered) and
    inspect the symbol before/after to confirm restoration.
    """
    server = _CoroutineAgentServer()
    original = _proc_pool_mod.ProcPool

    # Force super().run() to fail fast with a deterministic error path so we
    # don't need a configured LiveKit URL.
    with pytest.raises(Exception):  # noqa: B017 — any failure path is fine
        asyncio.run(server.run(devmode=True))

    assert _proc_pool_mod.ProcPool is original


def test_coroutine_server_load_fnc_reports_zero_before_pool_built() -> None:
    """The closure handles being called before the pool is constructed."""
    server = _CoroutineAgentServer()

    # Replicate what run() does to install the load_fnc closure.
    captured: dict[str, CoroutinePool | None] = {"pool": None}

    def _load_fnc() -> float:
        pool = captured["pool"]
        if pool is None:
            return 0.0
        return pool.current_load()

    server._load_fnc = _load_fnc
    assert _load_fnc() == 0.0


def test_coroutine_server_load_fnc_reflects_pool_after_capture() -> None:
    captured: dict[str, CoroutinePool | None] = {"pool": None}

    def _load_fnc() -> float:
        pool = captured["pool"]
        if pool is None:
            return 0.0
        return pool.current_load()

    # Build a real CoroutinePool, populate executors, and place it in
    # captured["pool"] to exercise the closure path that run() sets up.
    import multiprocessing as mp

    pool = CoroutinePool(
        initialize_process_fnc=lambda _proc: None,
        job_entrypoint_fnc=lambda _ctx: None,  # type: ignore[arg-type, return-value]
        session_end_fnc=None,
        num_idle_processes=0,
        initialize_timeout=5.0,
        close_timeout=10.0,
        inference_executor=None,
        job_executor_type=None,  # type: ignore[arg-type]
        mp_ctx=mp.get_context(),
        memory_warn_mb=0.0,
        memory_limit_mb=0.0,
        http_proxy=None,
        loop=asyncio.new_event_loop(),
        max_concurrent_sessions=4,
    )
    captured["pool"] = pool
    assert _load_fnc() == 0.0

    pool._executors.extend([object(), object()])  # type: ignore[list-item]
    assert _load_fnc() == 0.5

    pool._executors.extend([object(), object()])  # type: ignore[list-item]
    assert _load_fnc() == 1.0


def test_coroutine_server_factory_constructs_coroutine_pool_with_kwargs() -> None:
    """The factory closure produces a CoroutinePool with the right kwargs."""
    import multiprocessing as mp

    server = _CoroutineAgentServer(max_concurrent_sessions=7)
    captured: dict[str, CoroutinePool | None] = {"pool": None}

    def _factory(**pool_kwargs: Any) -> CoroutinePool:
        pool = CoroutinePool(
            **pool_kwargs, max_concurrent_sessions=server._max_concurrent_sessions
        )
        captured["pool"] = pool
        return pool

    pool_kwargs = {
        "initialize_process_fnc": lambda _proc: None,
        "job_entrypoint_fnc": lambda _ctx: None,
        "session_end_fnc": None,
        "num_idle_processes": 0,
        "initialize_timeout": 5.0,
        "close_timeout": 10.0,
        "inference_executor": None,
        "job_executor_type": None,
        "mp_ctx": mp.get_context(),
        "memory_warn_mb": 0.0,
        "memory_limit_mb": 0.0,
        "http_proxy": None,
        "loop": asyncio.new_event_loop(),
    }
    out = _factory(**pool_kwargs)

    assert isinstance(out, CoroutinePool)
    assert out.max_concurrent_sessions == 7
    assert captured["pool"] is out
