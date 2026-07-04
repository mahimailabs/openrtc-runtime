"""Per-agent resource budgets and backpressure (MAH-96)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import Agent

from openrtc import AgentPool
from openrtc.observability.metrics import RuntimeMetricsStore
from openrtc.routing.request_filter import (
    _build_per_agent_backpressure_filter,
    _resolve_request_agent_name,
)


class _Sales(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="sales")


class _Support(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="support")


class _Req:
    """Minimal JobRequest stand-in that records accept/reject."""

    def __init__(
        self,
        *,
        room_name: str = "",
        job_metadata: Any = None,
        room_metadata: Any = None,
    ) -> None:
        self.job = SimpleNamespace(metadata=job_metadata)
        self.room = SimpleNamespace(name=room_name, metadata=room_metadata)
        self.accepted = False
        self.rejected = False

    async def accept(self, **_kwargs: object) -> None:
        self.accepted = True

    async def reject(self, **_kwargs: object) -> None:
        self.rejected = True


_AGENTS = {"sales": object(), "support": object()}


# --- agent resolution -------------------------------------------------------


def test_resolve_via_job_metadata() -> None:
    name = _resolve_request_agent_name(
        _AGENTS, room_name="", job_metadata={"agent": "support"}, room_metadata=None
    )
    assert name == "support"


def test_resolve_via_room_name_prefix() -> None:
    name = _resolve_request_agent_name(
        _AGENTS, room_name="sales-call-1", job_metadata=None, room_metadata=None
    )
    assert name == "sales"


def test_resolve_falls_back_to_first_registered() -> None:
    name = _resolve_request_agent_name(
        _AGENTS, room_name="mystery", job_metadata=None, room_metadata=None
    )
    assert name == "sales"  # first key in insertion order


def test_resolve_falls_back_when_room_name_not_str() -> None:
    name = _resolve_request_agent_name(
        _AGENTS, room_name=None, job_metadata=None, room_metadata=None
    )
    assert name == "sales"  # non-str room name skips prefix, hits fallback


def test_resolve_returns_none_when_no_agents() -> None:
    assert (
        _resolve_request_agent_name(
            {}, room_name="x", job_metadata=None, room_metadata=None
        )
        is None
    )


def test_active_by_agent_returns_live_copy() -> None:
    store = RuntimeMetricsStore()
    store.record_session_started("sales")
    store.record_session_started("sales")
    store.record_session_started("support")
    counts = store.active_by_agent()
    assert counts == {"sales": 2, "support": 1}
    counts["sales"] = 99  # mutating the copy must not touch the live store
    assert store.active_by_agent()["sales"] == 2


# --- backpressure filter ----------------------------------------------------


def _filter(caps: dict[str, int], active: dict[str, int], base: Any = None) -> Any:
    return _build_per_agent_backpressure_filter(
        agents=_AGENTS,
        caps=caps,
        active_counts=lambda: active,
        base_filter=base,
    )


@pytest.mark.asyncio
async def test_rejects_when_target_agent_at_cap() -> None:
    fnc = _filter({"sales": 2}, {"sales": 2})
    req = _Req(job_metadata={"agent": "sales"})
    await fnc(req)
    assert req.rejected
    assert not req.accepted


@pytest.mark.asyncio
async def test_sibling_agent_accepts_when_other_at_cap() -> None:
    fnc = _filter({"sales": 2}, {"sales": 2})
    req = _Req(job_metadata={"agent": "support"})
    await fnc(req)
    assert req.accepted
    assert not req.rejected


@pytest.mark.asyncio
async def test_accepts_under_cap() -> None:
    fnc = _filter({"sales": 30}, {"sales": 5})
    req = _Req(job_metadata={"agent": "sales"})
    await fnc(req)
    assert req.accepted


@pytest.mark.asyncio
async def test_fallback_agent_cap_applies() -> None:
    # No routing signal -> first-registered (sales); its cap governs.
    fnc = _filter({"sales": 1}, {"sales": 1})
    req = _Req(room_name="mystery")
    await fnc(req)
    assert req.rejected


@pytest.mark.asyncio
async def test_defers_to_base_filter_when_under_cap() -> None:
    async def _reject_all(req: Any) -> None:
        await req.reject()

    fnc = _filter({"sales": 30}, {"sales": 0}, base=_reject_all)
    req = _Req(job_metadata={"agent": "sales"})
    await fnc(req)
    assert req.rejected  # base rejected even though under cap


@pytest.mark.asyncio
async def test_empty_agents_defers_to_accept() -> None:
    fnc = _build_per_agent_backpressure_filter(
        agents={}, caps={"sales": 1}, active_counts=dict, base_filter=None
    )
    req = _Req(job_metadata={"agent": "sales"})
    await fnc(req)
    assert req.accepted


# --- pool wiring ------------------------------------------------------------


def test_pool_wires_per_agent_caps() -> None:
    pool = AgentPool(
        agents={"sales": _Sales, "support": _Support},
        max_sessions_per_agent={"sales": 30, "support": 20},
        enable_introspection=False,
    )
    assert pool.max_sessions_per_agent == {"sales": 30, "support": 20}
    assert pool.request_fnc is not None  # backpressure filter installed


def test_pool_global_cap_preserved_when_agent_caps_exceed_it() -> None:
    pool = AgentPool(
        agents={"sales": _Sales, "support": _Support},
        max_concurrent_sessions=40,
        max_sessions_per_agent={"sales": 30, "support": 20},  # sum 50 > 40
        enable_introspection=False,
    )
    assert pool.max_concurrent_sessions == 40  # global cap untouched


def test_pool_rejects_non_positive_cap() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        AgentPool(
            agents={"sales": _Sales},
            max_sessions_per_agent={"sales": 0},
            enable_introspection=False,
        )
