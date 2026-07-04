"""Per-agent dispatch routing: custom router callable (MAH-99)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import Agent

from openrtc import AgentPool
from openrtc.routing.resolver import _metadata_to_mapping, _resolve_agent_config


class _Sales(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="sales")


class _Support(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="support")


def _agents() -> dict[str, Any]:
    pool = AgentPool(
        agents={"sales": _Sales, "support": _Support}, enable_introspection=False
    )
    return pool._agents


def _ctx(job_metadata: Any = None, job_id: str = "job-1") -> Any:
    return SimpleNamespace(
        job=SimpleNamespace(metadata=job_metadata, id=job_id, room=None),
        room=SimpleNamespace(metadata=None, name=""),
    )


def test_default_style_router_routes_by_metadata() -> None:
    def router(meta: Any) -> str:
        return (meta or {}).get("agent", "sales")

    config = _resolve_agent_config(
        _agents(), _ctx(job_metadata='{"agent": "support"}'), router=router
    )
    assert config.name == "support"


def test_router_receives_parsed_metadata_mapping() -> None:
    seen: list[Any] = []

    def router(meta: Any) -> str:
        seen.append(meta)
        return "sales"

    _resolve_agent_config(
        _agents(),
        _ctx(job_metadata='{"agent": "support", "tier": "gold"}'),
        router=router,
    )
    assert seen == [{"agent": "support", "tier": "gold"}]


def test_router_returning_none_defers_to_default_chain() -> None:
    def router(_meta: Any) -> str | None:
        return None

    # Router defers; the default metadata strategy then routes by "agent".
    config = _resolve_agent_config(
        _agents(), _ctx(job_metadata='{"agent": "support"}'), router=router
    )
    assert config.name == "support"


def test_router_unknown_agent_is_rejected() -> None:
    def router(_meta: Any) -> str:
        return "ghost"

    with pytest.raises(ValueError, match="unknown agent 'ghost'"):
        _resolve_agent_config(_agents(), _ctx(), router=router)


def test_router_exception_is_caught_and_rejected() -> None:
    def router(_meta: Any) -> str:
        raise RuntimeError("boom")

    with pytest.raises(ValueError, match="raised while resolving"):
        _resolve_agent_config(_agents(), _ctx(), router=router)


def test_router_receives_none_for_absent_metadata() -> None:
    seen: list[Any] = []

    def router(meta: Any) -> str:
        seen.append(meta)
        return "sales"

    _resolve_agent_config(_agents(), _ctx(job_metadata=None), router=router)
    _resolve_agent_config(_agents(), _ctx(job_metadata="not json"), router=router)
    assert seen == [None, None]


def test_router_receives_dict_metadata_directly() -> None:
    seen: list[Any] = []

    def router(meta: Any) -> str:
        seen.append(meta)
        return "sales"

    # ctx.job.metadata already a mapping (not a JSON string).
    _resolve_agent_config(
        _agents(), _ctx(job_metadata={"agent": "support"}), router=router
    )
    assert seen == [{"agent": "support"}]


def test_metadata_to_mapping_variants() -> None:
    assert _metadata_to_mapping({"a": 1}) == {"a": 1}
    assert _metadata_to_mapping('{"a": 1}') == {"a": 1}
    assert _metadata_to_mapping("   ") is None  # empty after strip
    assert _metadata_to_mapping("not json") is None  # JSONDecodeError
    assert _metadata_to_mapping("[1, 2]") is None  # valid JSON, not an object
    assert _metadata_to_mapping(None) is None
    assert _metadata_to_mapping(123) is None


def test_pool_router_param_is_wired() -> None:
    def router(meta: Any) -> str:
        return (meta or {}).get("agent", "sales")

    pool = AgentPool(
        agents={"sales": _Sales}, router=router, enable_introspection=False
    )
    assert pool.router is router
    assert pool._runtime_state.router is router
