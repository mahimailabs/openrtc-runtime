"""v0.5 composition gate: 3 tenants, config isolated, caps + blast radius enforced.

Exercises the full per-tenant surface end-to-end through the *real* AgentPool
wiring (the layered request filter, the tenant config resolver, the per-tenant
metrics, and the circuit breaker), not mocks. Each individual piece is unit-tested
in its own module (MAH-102/103/104/105); this proves they compose.

The 3 tenants: acme + globex carry distinct provider configs; initech has none and
falls back. A full 15-session real-media cluster run is deferred as redundant here
(every assertion below is deterministic at the pool layer, and the live-session
machinery is covered by the real-media integration tests); this composition test
runs in CI on every PR.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from livekit.agents import Agent

from openrtc import AgentPool

# Distinct sentinel provider objects per tenant: if any leaked across tenants the
# identity assertions below would fail (no shared keys).
ACME_LLM, ACME_STT, ACME_TTS = object(), object(), object()
GLOBEX_LLM, GLOBEX_STT, GLOBEX_TTS = object(), object(), object()


class _Agent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="a")


class _Req:
    def __init__(self, tenant: str) -> None:
        self.job = SimpleNamespace(metadata=f'{{"tenant": "{tenant}"}}')
        self.room = SimpleNamespace(name="", metadata=None)
        self.accepted = False
        self.rejected = False

    async def accept(self, **_kwargs: object) -> None:
        self.accepted = True

    async def reject(self, **_kwargs: object) -> None:
        self.rejected = True


def _pool() -> AgentPool:
    return AgentPool(
        agent=_Agent,
        tenant_config={
            "acme": {"stt": ACME_STT, "llm": ACME_LLM, "tts": ACME_TTS},
            "globex": {"stt": GLOBEX_STT, "llm": GLOBEX_LLM, "tts": GLOBEX_TTS},
        },
        max_sessions_per_tenant={"globex": 10},
        enable_tenant_circuit_breaker=True,
        enable_introspection=False,
    )


async def _decide(pool: AgentPool, tenant: str) -> _Req:
    req = _Req(tenant)
    assert pool.request_fnc is not None
    await pool.request_fnc(req)  # type: ignore[arg-type]
    return req


# --- per-tenant provider config, no key leakage -----------------------------


def test_each_tenant_keeps_its_own_providers() -> None:
    resolver = _pool()._runtime_state.tenant_resolver
    assert resolver is not None
    acme = resolver.resolve("acme")
    globex = resolver.resolve("globex")
    assert acme == {"stt": ACME_STT, "llm": ACME_LLM, "tts": ACME_TTS}
    assert globex == {"stt": GLOBEX_STT, "llm": GLOBEX_LLM, "tts": GLOBEX_TTS}
    assert acme is not None
    assert globex is not None
    assert acme["llm"] is not globex["llm"]  # no client/key sharing
    assert resolver.resolve("initech") is None  # falls back to agent defaults


# --- per-tenant caps confine one tenant -------------------------------------


@pytest.mark.asyncio
async def test_globex_cap_rejects_11th_while_siblings_accept() -> None:
    pool = _pool()
    metrics = pool._runtime_state.metrics
    for _ in range(10):  # globex at its cap of 10
        metrics.record_session_started("default", "globex")

    assert metrics.active_by_tenant()["globex"] == 10  # tagged per tenant
    assert (await _decide(pool, "globex")).rejected  # 11th globex rejected
    assert (await _decide(pool, "acme")).accepted  # siblings unaffected
    assert (await _decide(pool, "initech")).accepted


# --- blast radius: one tenant's failures confined ---------------------------


@pytest.mark.asyncio
async def test_acme_circuit_breaks_without_touching_siblings() -> None:
    pool = _pool()
    breaker = pool.tenant_circuit_breaker
    assert breaker is not None
    for _ in range(5):  # acme fails past the breaker's default threshold
        breaker.record_outcome("acme", success=False)

    assert (await _decide(pool, "acme")).rejected  # acme rejected during cooldown
    assert (await _decide(pool, "globex")).accepted  # globex healthy, accepted
    assert (await _decide(pool, "initech")).accepted  # initech healthy, accepted


# --- metrics tagging across all three tenants -------------------------------


def test_metrics_tagged_per_tenant() -> None:
    pool = _pool()
    metrics = pool._runtime_state.metrics
    metrics.record_session_started("default", "acme")
    metrics.record_session_started("default", "acme")
    metrics.record_session_started("default", "globex")
    metrics.record_session_started("default", "initech")

    snap = pool.runtime_snapshot()
    assert snap.sessions_by_tenant == {"acme": 2, "globex": 1, "initech": 1}
