"""Per-tenant provider config resolution + override at session start (MAH-102)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import Agent

from openrtc import AgentPool
from openrtc.core.tenant_config import (
    TenantConfigResolver,
    resolve_tenant_providers,
)


class _Agent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="a")


def _config() -> Any:
    return SimpleNamespace(stt="agent-stt", llm="agent-llm", tts="agent-tts")


# --- provider override merge ------------------------------------------------


def test_tenant_override_replaces_only_given_keys() -> None:
    acme_llm = object()
    stt, llm, tts = resolve_tenant_providers(_config(), {"llm": acme_llm})
    assert llm is acme_llm  # overridden
    assert stt == "agent-stt"  # fell back to the agent's
    assert tts == "agent-tts"


def test_no_tenant_config_uses_agent_providers() -> None:
    stt, llm, tts = resolve_tenant_providers(_config(), None)
    assert (stt, llm, tts) == ("agent-stt", "agent-llm", "agent-tts")


# --- resolver: caching, callable, fallback ----------------------------------


def test_resolver_dict_source_returns_config() -> None:
    resolver = TenantConfigResolver({"acme": {"llm": "acme-llm"}})
    assert resolver.resolve("acme") == {"llm": "acme-llm"}


def test_resolver_missing_tenant_warns_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    resolver = TenantConfigResolver({"acme": {"llm": "x"}})
    with caplog.at_level("WARNING", logger="openrtc"):
        assert resolver.resolve("ghost") is None
        assert resolver.resolve("ghost") is None  # cached: no second lookup/warning
    assert sum("No tenant config for 'ghost'" in r.message for r in caplog.records) == 1


def test_resolver_callable_source_invoked_once_per_tenant() -> None:
    calls: list[str] = []

    def _load(tenant: str) -> Any:
        calls.append(tenant)
        return {"llm": f"{tenant}-llm"}

    resolver = TenantConfigResolver(_load)
    assert resolver.resolve("acme") == {"llm": "acme-llm"}
    assert resolver.resolve("acme") == {"llm": "acme-llm"}  # cached
    assert resolver.resolve("globex") == {"llm": "globex-llm"}
    assert calls == ["acme", "globex"]  # once per tenant


def test_resolver_callable_returning_none_falls_back() -> None:
    resolver = TenantConfigResolver(lambda _t: None)
    assert resolver.resolve("acme") is None


# --- build_session applies the override + key isolation ----------------------


def _build_env(monkeypatch: pytest.MonkeyPatch, resolver: TenantConfigResolver) -> Any:
    from openrtc.core import wiring

    config = SimpleNamespace(
        name="a",
        stt="agent-stt",
        llm="agent-llm",
        tts="agent-tts",
        session_kwargs={},
    )
    monkeypatch.setattr(
        wiring, "_resolve_agent_config", lambda agents, ctx, *, router=None: config
    )
    monkeypatch.setattr(wiring, "_build_session_kwargs", lambda kw, proc, ie=None: {})
    monkeypatch.setattr(
        wiring.PrewarmResources, "vad_from", staticmethod(lambda _proc: "VAD")
    )

    captured: dict[str, Any] = {}

    class _FakeSession:
        def __init__(
            self, *, stt: Any, llm: Any, tts: Any, vad: Any, **_kw: Any
        ) -> None:
            captured["stt"] = stt
            captured["llm"] = llm
            captured["tts"] = tts

    monkeypatch.setattr("livekit.agents.AgentSession", _FakeSession)

    state = wiring._PoolRuntimeState(agents={"a": config}, tenant_resolver=resolver)
    return wiring, state, captured


def _ctx(tenant: str) -> Any:
    return SimpleNamespace(
        proc=SimpleNamespace(userdata={"vad": "VAD"}),
        room=SimpleNamespace(name="r", metadata=None),
        job=SimpleNamespace(id="j", metadata=f'{{"tenant": "{tenant}"}}'),
        inference_executor=None,
    )


def test_build_session_applies_tenant_llm_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acme_llm = object()
    resolver = TenantConfigResolver({"acme": {"llm": acme_llm}})
    wiring, state, captured = _build_env(monkeypatch, resolver)

    _session, _config, info = wiring.build_session(state, _ctx("acme"))

    assert info.tenant == "acme"
    assert captured["llm"] is acme_llm  # tenant override
    assert captured["stt"] == "agent-stt"  # fell back to the agent's
    assert captured["tts"] == "agent-tts"


def test_provider_instances_are_not_shared_across_tenants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acme_llm, globex_llm = object(), object()
    resolver = TenantConfigResolver(
        {"acme": {"llm": acme_llm}, "globex": {"llm": globex_llm}}
    )
    wiring, state, captured = _build_env(monkeypatch, resolver)

    wiring.build_session(state, _ctx("acme"))
    assert captured["llm"] is acme_llm
    wiring.build_session(state, _ctx("globex"))
    assert captured["llm"] is globex_llm  # each tenant kept its own client


# --- pool wiring ------------------------------------------------------------


def test_pool_wires_tenant_config() -> None:
    pool = AgentPool(
        agents={"a": _Agent},
        tenant_config={"acme": {"llm": "acme-llm"}},
        enable_introspection=False,
    )
    assert pool._runtime_state.tenant_resolver is not None
    assert pool._runtime_state.tenant_resolver.resolve("acme") == {"llm": "acme-llm"}


def test_pool_without_tenant_config_has_no_resolver() -> None:
    pool = AgentPool(agents={"a": _Agent}, enable_introspection=False)
    assert pool._runtime_state.tenant_resolver is None
