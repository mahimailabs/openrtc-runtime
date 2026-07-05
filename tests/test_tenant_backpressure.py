"""Per-tenant resource caps and backpressure (MAH-103)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import Agent

from openrtc import AgentPool
from openrtc.routing.request_filter import (
    _build_per_agent_backpressure_filter,
    _build_per_tenant_backpressure_filter,
    _resolve_request_tenant,
)


class _Sales(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="sales")


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


# --- tenant resolution ------------------------------------------------------


def test_resolve_request_tenant_from_job_metadata() -> None:
    assert (
        _resolve_request_tenant(job_metadata='{"tenant": "acme"}', room_metadata=None)
        == "acme"
    )


def test_resolve_request_tenant_defaults_when_absent() -> None:
    assert _resolve_request_tenant(job_metadata=None, room_metadata=None) == "default"


def test_resolve_request_tenant_job_wins_over_room() -> None:
    assert (
        _resolve_request_tenant(
            job_metadata='{"tenant": "acme"}', room_metadata='{"tenant": "globex"}'
        )
        == "acme"
    )


# --- tenant backpressure filter ---------------------------------------------


def _tenant_filter(
    caps: dict[str, int], active: dict[str, int], base: Any = None
) -> Any:
    return _build_per_tenant_backpressure_filter(
        caps=caps, active_counts=lambda: active, base_filter=base
    )


@pytest.mark.asyncio
async def test_rejects_when_tenant_at_cap() -> None:
    fnc = _tenant_filter({"acme": 2}, {"acme": 2})
    req = _Req(job_metadata='{"tenant": "acme"}')
    await fnc(req)
    assert req.rejected
    assert not req.accepted


@pytest.mark.asyncio
async def test_sibling_tenant_accepts_when_other_at_cap() -> None:
    fnc = _tenant_filter({"acme": 2}, {"acme": 2})
    req = _Req(job_metadata='{"tenant": "globex"}')
    await fnc(req)
    assert req.accepted


@pytest.mark.asyncio
async def test_default_tenant_cap_applies_when_absent() -> None:
    fnc = _tenant_filter({"default": 1}, {"default": 1})
    req = _Req()  # no metadata -> "default"
    await fnc(req)
    assert req.rejected


@pytest.mark.asyncio
async def test_under_cap_defers_to_base_filter() -> None:
    async def _reject_all(req: Any) -> None:
        await req.reject()

    fnc = _tenant_filter({"acme": 10}, {"acme": 0}, base=_reject_all)
    req = _Req(job_metadata='{"tenant": "acme"}')
    await fnc(req)
    assert req.rejected  # base rejected even though tenant under cap


@pytest.mark.asyncio
async def test_tenant_and_agent_caps_compose() -> None:
    # tenant under cap, but the agent is at its cap: the layered filter rejects.
    agent_fnc = _build_per_agent_backpressure_filter(
        agents={"sales": object()},
        caps={"sales": 5},
        active_counts=lambda: {"sales": 5},
        base_filter=None,
    )
    tenant_fnc = _build_per_tenant_backpressure_filter(
        caps={"acme": 100},
        active_counts=lambda: {"acme": 0},
        base_filter=agent_fnc,
    )
    req = _Req(job_metadata='{"tenant": "acme", "agent": "sales"}')
    await tenant_fnc(req)
    assert req.rejected  # agent cap tripped despite tenant headroom


# --- pool wiring ------------------------------------------------------------


def test_pool_wires_per_tenant_caps() -> None:
    pool = AgentPool(
        agents={"sales": _Sales},
        max_sessions_per_tenant={"acme": 50, "globex": 100},
        enable_introspection=False,
    )
    assert pool.max_sessions_per_tenant == {"acme": 50, "globex": 100}
    assert pool.request_fnc is not None


def test_pool_rejects_non_positive_tenant_cap() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        AgentPool(
            agents={"sales": _Sales},
            max_sessions_per_tenant={"acme": 0},
            enable_introspection=False,
        )
