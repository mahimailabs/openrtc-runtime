"""Session introspection registry + row assembler for openrtc top (MAH-92)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from openrtc.observability.introspection import (
    SessionIntrospectionRegistry,
    build_session_rows,
)
from openrtc.observability.session_cpu import SessionCpu
from openrtc.observability.session_memory import SessionMemory


def _info(
    job_id: str, agent: str, tenant: str | None = None, started_at: float = 0.0
) -> Any:
    metadata = {"tenant": tenant} if tenant is not None else {}
    return SimpleNamespace(
        job_id=job_id, agent_name=agent, metadata=metadata, started_at=started_at
    )


def _register(reg: SessionIntrospectionRegistry, info: Any, session: Any) -> None:
    asyncio.run(reg.on_session_start(info, session))


def test_registry_tracks_active_agents_and_tenant() -> None:
    reg = SessionIntrospectionRegistry()
    _register(reg, _info("s1", "sales", tenant="acme"), object())
    _register(reg, _info("s2", "support"), object())

    assert reg.active_agents() == {"s1": "sales", "s2": "support"}
    assert reg.active_count() == 2
    live = {ls.session_id: ls for ls in reg.live_sessions()}
    assert live["s1"].tenant == "acme"
    assert live["s2"].tenant is None


def test_registry_drops_ended_session() -> None:
    reg = SessionIntrospectionRegistry()
    _register(reg, _info("s1", "a"), object())
    asyncio.run(reg.on_session_end(_info("s1", "a"), SimpleNamespace()))
    assert reg.active_count() == 0
    # Tolerant of an unpaired end.
    asyncio.run(reg.on_session_end(_info("nope", "a"), SimpleNamespace()))


def test_session_for_returns_the_live_session() -> None:
    reg = SessionIntrospectionRegistry()
    sess = object()
    _register(reg, _info("s1", "a"), sess)
    assert reg.session_for("s1") is sess
    assert reg.session_for("missing") is None


def test_build_rows_joins_all_signals() -> None:
    reg = SessionIntrospectionRegistry()
    pinned_session = object()
    _register(
        reg, _info("s1", "sales", tenant="acme", started_at=100.0), pinned_session
    )
    _register(reg, _info("s2", "support", started_at=100.0), object())

    memory = {
        "s1": SessionMemory("s1", "sales", 120.0, 150.0),
        "s2": SessionMemory("s2", "support", 80.0, 90.0),
    }
    cpu = {"s1": SessionCpu("s1", "sales", 42.0, 0.4, 42)}

    rows = build_session_rows(
        registry=reg,
        memory=memory,
        cpu=cpu,
        slow_session_ids={"s2"},
        is_pinned=lambda s: s is pinned_session,
        now=105.0,
    )
    by_id = {r.session_id: r for r in rows}

    assert by_id["s1"].agent_name == "sales"
    assert by_id["s1"].tenant == "acme"
    assert by_id["s1"].duration_s == 5.0
    assert by_id["s1"].mem_mb == 120.0
    assert by_id["s1"].peak_mb == 150.0
    assert by_id["s1"].cpu_pct == 42.0
    assert by_id["s1"].status == "active"
    assert by_id["s1"].pinned is True

    # s2: no CPU sample yet, marked slow, unpinned.
    assert by_id["s2"].cpu_pct == 0.0
    assert by_id["s2"].status == "slow"
    assert by_id["s2"].pinned is False


def test_build_rows_defaults_when_no_samples() -> None:
    reg = SessionIntrospectionRegistry()
    _register(reg, _info("s1", "a", started_at=0.0), object())
    rows = build_session_rows(
        registry=reg,
        memory={},
        cpu={},
        slow_session_ids=set(),
        is_pinned=lambda _s: False,
        now=1.0,
    )
    assert rows[0].mem_mb == 0.0
    assert rows[0].peak_mb == 0.0
    assert rows[0].cpu_pct == 0.0
    assert rows[0].status == "active"
