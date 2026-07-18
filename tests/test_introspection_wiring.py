"""Pool wiring for openrtc top: CoroutinePool + AgentPool serve the socket (MAH-92)."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest
from livekit.agents import JobExecutorType

from openrtc.core.pool import AgentPool
from openrtc.observability.introspection_ipc import fetch_snapshot
from openrtc.observability.introspection_runtime import IntrospectionRuntime
from openrtc.runtime.coroutine_runtime import CoroutinePool


async def _noop(_ctx: Any) -> None:
    pass


def _short_socket() -> Path:
    return Path(tempfile.gettempdir()) / f"ortc-wire-{uuid.uuid4().hex[:8]}.sock"


def test_agent_pool_worker_context_maps_the_runtime_snapshot() -> None:
    pool = AgentPool(max_concurrent_sessions=200)
    ctx = pool._worker_context()
    assert ctx.max_sessions == 200  # from the pool's concurrency cap
    assert ctx.uptime_s >= 0.0
    assert ctx.started == 0  # fresh pool, nothing started yet
    assert ctx.failed == 0
    assert ctx.draining is False
    assert isinstance(ctx.name, str) and ctx.name  # hostname, non-empty
    assert ctx.saved_bytes is None or isinstance(ctx.saved_bytes, int)


def _make_pool(introspection: IntrospectionRuntime | None) -> CoroutinePool:
    return CoroutinePool(
        initialize_process_fnc=lambda _proc: None,
        job_entrypoint_fnc=_noop,
        session_end_fnc=None,
        num_idle_processes=0,
        initialize_timeout=10.0,
        close_timeout=5.0,
        inference_executor=None,
        job_executor_type=JobExecutorType.PROCESS,
        mp_ctx=mp.get_context(),
        memory_warn_mb=0.0,
        memory_limit_mb=0.0,
        http_proxy=None,
        loop=asyncio.get_running_loop(),
        max_concurrent_sessions=5,
        introspection=introspection,
    )


@pytest.mark.asyncio
async def test_coroutine_pool_serves_and_tears_down_introspection() -> None:
    socket_path = _short_socket()
    runtime = IntrospectionRuntime(
        socket_path=socket_path,
        rss_reader=lambda: 100 * 1024 * 1024,
    )
    pool = _make_pool(runtime)
    await pool.start()
    try:
        # The pool brought the socket up; a client can read a (empty) snapshot.
        assert socket_path.exists()
        assert (await fetch_snapshot(socket_path))["sessions"] == []
    finally:
        await pool.aclose()
    assert not socket_path.exists()  # torn down with the pool


@pytest.mark.asyncio
async def test_coroutine_pool_without_introspection_is_unaffected() -> None:
    pool = _make_pool(None)
    await pool.start()
    try:
        assert pool._introspection is None
    finally:
        await pool.aclose()


def test_agent_pool_enables_introspection_by_default() -> None:
    socket_path = _short_socket()
    pool = AgentPool(introspection_socket_path=socket_path)
    runtime = pool.introspection
    assert runtime is not None
    assert runtime.socket_path == socket_path
    # The registry is registered as a session observer so it tracks live sessions.
    assert runtime.registry in pool._runtime_state.observers
    # And the server carries the same stack it will hand to the CoroutinePool.
    from openrtc.runtime.coroutine_server import _CoroutineAgentServer

    assert isinstance(pool.server, _CoroutineAgentServer)
    assert pool.server._introspection is runtime


def test_agent_pool_can_disable_introspection() -> None:
    pool = AgentPool(enable_introspection=False)
    assert pool.introspection is None


def test_agent_pool_skips_introspection_in_process_mode() -> None:
    # process mode isolates each session in a subprocess; a shared-process
    # inspector sees nothing, so introspection is silently skipped.
    pool = AgentPool(isolation="process")
    assert pool.introspection is None
