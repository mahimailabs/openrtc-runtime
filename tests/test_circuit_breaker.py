"""Per-tenant circuit breaker for blast-radius isolation (MAH-104)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import Agent

from openrtc import AgentPool
from openrtc.core.circuit_breaker import TenantCircuitBreaker
from openrtc.routing.request_filter import _build_tenant_circuit_filter


class _Agent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="a")


class _Req:
    def __init__(self, *, job_metadata: Any = None) -> None:
        self.job = SimpleNamespace(metadata=job_metadata)
        self.room = SimpleNamespace(name="", metadata=None)
        self.accepted = False
        self.rejected = False

    async def accept(self, **_kwargs: object) -> None:
        self.accepted = True

    async def reject(self, **_kwargs: object) -> None:
        self.rejected = True


class _Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _breaker(clock: _Clock, **kw: float) -> TenantCircuitBreaker:
    params: dict[str, float] = {
        "failure_ratio": 0.5,
        "min_samples": 4,
        "window_seconds": 60.0,
        "cooldown_seconds": 30.0,
    }
    params.update(kw)
    return TenantCircuitBreaker(time_source=clock, **params)  # type: ignore[arg-type]


def test_closed_by_default() -> None:
    breaker = _breaker(_Clock())
    assert breaker.should_reject("acme") is False


def test_does_not_open_below_min_samples() -> None:
    clock = _Clock()
    breaker = _breaker(clock, min_samples=4)
    # 3 failures, but below the 4-sample minimum: stays closed.
    for _ in range(3):
        breaker.record_outcome("acme", success=False)
    assert breaker.should_reject("acme") is False


def test_opens_when_failure_ratio_exceeded() -> None:
    clock = _Clock()
    breaker = _breaker(clock, min_samples=4, failure_ratio=0.5)
    for _ in range(3):
        breaker.record_outcome("acme", success=False)
    breaker.record_outcome("acme", success=True)  # 3/4 = 75% > 50%
    assert breaker.should_reject("acme") is True


def test_healthy_tenant_stays_closed() -> None:
    clock = _Clock()
    breaker = _breaker(clock, min_samples=4)
    for _ in range(3):
        breaker.record_outcome("acme", success=False)
    breaker.record_outcome("acme", success=False)  # acme now open
    # globex has only successes: it never opens (isolation).
    for _ in range(5):
        breaker.record_outcome("globex", success=True)
    assert breaker.should_reject("globex") is False
    assert breaker.should_reject("acme") is True


def test_cooldown_auto_recovers() -> None:
    clock = _Clock(100.0)
    breaker = _breaker(clock, min_samples=4, cooldown_seconds=30.0)
    for _ in range(4):
        breaker.record_outcome("acme", success=False)
    assert breaker.should_reject("acme") is True
    clock.t = 129.0  # still within cooldown
    assert breaker.should_reject("acme") is True
    clock.t = 131.0  # cooldown elapsed
    assert breaker.should_reject("acme") is False  # auto-recovered


def test_window_prunes_old_outcomes() -> None:
    clock = _Clock(0.0)
    breaker = _breaker(clock, min_samples=4, window_seconds=10.0)
    breaker.record_outcome("acme", success=False)
    breaker.record_outcome("acme", success=False)
    clock.t = 20.0  # the two failures age out of the 10s window
    breaker.record_outcome("acme", success=False)
    breaker.record_outcome("acme", success=False)
    # Only 2 in-window outcomes (< min_samples 4): stays closed.
    assert breaker.should_reject("acme") is False


def test_state_change_callback_fires_on_open_and_close() -> None:
    clock = _Clock(0.0)
    events: list[tuple[str, str]] = []
    breaker = _breaker(clock, min_samples=4)
    breaker._on_state_change = lambda tenant, state: events.append((tenant, state))
    for _ in range(4):
        breaker.record_outcome("acme", success=False)
    assert ("acme", "open") in events
    clock.t = 100.0
    breaker.should_reject("acme")  # triggers recovery
    assert ("acme", "closed") in events


# --- request filter integration ---------------------------------------------


def test_record_outcome_ignored_while_open() -> None:
    clock = _Clock(0.0)
    breaker = _breaker(clock, min_samples=4)
    for _ in range(4):
        breaker.record_outcome("acme", success=False)  # opens
    assert breaker.should_reject("acme") is True
    # A further outcome while open is a no-op (recovery is time-based, not outcome).
    breaker.record_outcome("acme", success=True)
    assert breaker.should_reject("acme") is True


@pytest.mark.asyncio
async def test_circuit_filter_rejects_open_tenant() -> None:
    open_tenants = {"acme"}
    fnc = _build_tenant_circuit_filter(
        should_reject=lambda t: t in open_tenants, base_filter=None
    )
    acme = _Req(job_metadata='{"tenant": "acme"}')
    await fnc(acme)
    assert acme.rejected

    globex = _Req(job_metadata='{"tenant": "globex"}')
    await fnc(globex)
    assert globex.accepted  # healthy tenant passes through


@pytest.mark.asyncio
async def test_circuit_filter_defers_healthy_tenant_to_base() -> None:
    seen: list[Any] = []

    async def _base(req: Any) -> None:
        seen.append(req)
        await req.accept()

    fnc = _build_tenant_circuit_filter(
        should_reject=lambda _t: False, base_filter=_base
    )
    req = _Req(job_metadata='{"tenant": "globex"}')
    await fnc(req)
    assert seen == [req]  # deferred to the base filter
    assert req.accepted


# --- pool wiring + end-to-end blast radius -----------------------------------


def test_pool_wires_circuit_breaker() -> None:
    pool = AgentPool(
        agents={"a": _Agent},
        enable_tenant_circuit_breaker=True,
        tenant_circuit_cooldown_s=15.0,
        enable_introspection=False,
    )
    assert pool.tenant_circuit_breaker is not None
    assert pool.request_fnc is not None


def test_pool_without_circuit_breaker() -> None:
    pool = AgentPool(agents={"a": _Agent}, enable_introspection=False)
    assert pool.tenant_circuit_breaker is None


@pytest.mark.asyncio
async def test_finish_session_records_outcome_and_isolates_tenants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tenant's failures open its breaker via _finish_session; siblings unaffected."""
    from openrtc.core import wiring
    from openrtc.observability.base_observer import SessionInfo

    clock = _Clock(0.0)
    breaker = _breaker(clock, min_samples=4)
    state = wiring._PoolRuntimeState(agents={}, circuit_breaker=breaker)

    def _info(tenant: str) -> SessionInfo:
        return SessionInfo(
            agent_name="a",
            room_name="r",
            job_id="j",
            metadata={"tenant": tenant},
            started_at=0.0,
            tenant=tenant,
        )

    # Four acme failures open acme's breaker; globex only succeeds.
    for _ in range(4):
        await wiring._finish_session(state, _info("acme"), "a", RuntimeError("boom"))
    for _ in range(4):
        await wiring._finish_session(state, _info("globex"), "a", None)

    assert breaker.should_reject("acme") is True
    assert breaker.should_reject("globex") is False  # blast radius confined
