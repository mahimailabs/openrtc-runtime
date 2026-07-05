"""Introspection runtime façade: assembles registry + samplers + IPC (MAH-92)."""

from __future__ import annotations

import asyncio
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from openrtc.observability.introspection_ipc import fetch_snapshot
from openrtc.observability.introspection_runtime import IntrospectionRuntime
from openrtc.observability.slow_session import LoopBlockEvent


def _info(
    job_id: str, agent: str, tenant: str | None = None, started_at: float = 0.0
) -> Any:
    resolved = tenant if tenant is not None else "default"
    return SimpleNamespace(
        job_id=job_id,
        agent_name=agent,
        metadata={"tenant": resolved},
        started_at=started_at,
        tenant=resolved,
    )


def _short_socket() -> Path:
    # Keep the path short (Unix sockets cap at ~104 chars).
    return Path(tempfile.gettempdir()) / f"ortc-rt-{uuid.uuid4().hex[:8]}.sock"


class _Clock:
    """A settable time source so duration and the slow window are deterministic."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


async def _register(runtime: IntrospectionRuntime, info: Any) -> None:
    await runtime.registry.on_session_start(info, object())


def test_snapshot_joins_registry_and_memory_before_start() -> None:
    clock = _Clock(10.0)
    runtime = IntrospectionRuntime(
        socket_path=_short_socket(),
        rss_reader=lambda: 200 * 1024 * 1024,
        time_source=clock,
    )
    asyncio.run(_register(runtime, _info("s1", "sales", tenant="acme", started_at=4.0)))
    # Drive one memory sample so the equal-share attribution is populated.
    runtime._memory.sample_once()

    rows = runtime.snapshot()
    assert len(rows) == 1
    row = rows[0]
    assert row.session_id == "s1"
    assert row.agent_name == "sales"
    assert row.tenant == "acme"
    assert row.duration_s == 6.0  # now(10) - started_at(4)
    assert row.mem_mb == 200.0  # 200 MB / 1 active session
    assert row.cpu_pct == 0.0  # no CPU sampler before start
    assert row.status == "active"
    assert row.pinned is False


def test_recent_block_marks_session_slow_then_expires() -> None:
    clock = _Clock(100.0)
    runtime = IntrospectionRuntime(
        socket_path=_short_socket(),
        rss_reader=lambda: 100 * 1024 * 1024,
        time_source=clock,
        slow_window_s=5.0,
    )
    asyncio.run(_register(runtime, _info("s1", "a", started_at=0.0)))

    runtime._on_block(LoopBlockEvent(session_id="s1", blocked_ms=80.0))
    assert runtime.snapshot()[0].status == "slow"

    clock.t = 106.0  # advance past the 5s window
    assert runtime.snapshot()[0].status == "active"
    assert runtime._recent_blocks == {}  # pruned on snapshot


def test_on_block_ignores_unattributed_event() -> None:
    runtime = IntrospectionRuntime(socket_path=_short_socket(), time_source=_Clock(1.0))
    runtime._on_block(LoopBlockEvent(session_id=None, blocked_ms=90.0))
    assert runtime._recent_blocks == {}


def test_custom_is_pinned_is_honored() -> None:
    clock = _Clock(1.0)
    runtime = IntrospectionRuntime(
        socket_path=_short_socket(),
        time_source=clock,
        is_pinned=lambda _session: True,
    )
    asyncio.run(_register(runtime, _info("s1", "a", started_at=0.0)))
    assert runtime.snapshot()[0].pinned is True


def test_default_socket_path_used_when_none() -> None:
    runtime = IntrospectionRuntime()
    assert runtime.socket_path.name == "top.sock"


@pytest.mark.asyncio
async def test_start_serves_socket_and_aclose_restores_and_cleans_up() -> None:
    socket_path = _short_socket()
    clock = _Clock(50.0)
    runtime = IntrospectionRuntime(
        socket_path=socket_path,
        rss_reader=lambda: 300 * 1024 * 1024,
        time_source=clock,
    )
    await _register(runtime, _info("s1", "sales", started_at=10.0))

    loop = asyncio.get_running_loop()
    factory_before = loop.get_task_factory()
    await runtime.start(loop)
    await runtime.start(loop)  # idempotent: second start is a no-op
    try:
        assert loop.get_task_factory() is not factory_before  # task factory installed
        rows = await fetch_snapshot(socket_path)
        assert [r["session_id"] for r in rows] == ["s1"]
        assert rows[0]["duration_s"] == 40.0  # now(50) - started_at(10)
    finally:
        await runtime.aclose()

    assert loop.get_task_factory() is factory_before  # restored
    assert not socket_path.exists()
    await runtime.aclose()  # idempotent


@pytest.mark.asyncio
async def test_aclose_before_start_is_a_noop() -> None:
    runtime = IntrospectionRuntime(socket_path=_short_socket())
    await runtime.aclose()  # never started: must not raise
