"""Multi-agent registration in AgentPool: dict constructor + shorthand (MAH-95)."""

from __future__ import annotations

from typing import Any

import pytest
from livekit.agents import Agent

from openrtc import AgentPool
from openrtc.utils.validation import require_agent_name


class _Sales(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="sales")


class _Support(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="support")


class _Billing(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="billing")


def _pool(**kwargs: Any) -> AgentPool:
    # Introspection is orthogonal here; disable it so construction stays a pure
    # registration exercise (no socket directory side effects).
    return AgentPool(enable_introspection=False, **kwargs)


def test_agents_dict_registers_all_three() -> None:
    pool = _pool(agents={"sales": _Sales, "support": _Support, "billing": _Billing})
    assert sorted(pool.list_agents()) == ["billing", "sales", "support"]
    assert pool.get("sales").agent_cls is _Sales
    assert pool.get("support").agent_cls is _Support


def test_single_agent_shorthand_registers_as_default() -> None:
    pool = _pool(agent=_Sales)
    assert pool.list_agents() == ["default"]
    assert pool.get("default").agent_cls is _Sales


def test_agent_and_agents_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="either agent or agents"):
        _pool(agent=_Sales, agents={"support": _Support})


def test_constructor_agents_compose_with_add() -> None:
    pool = _pool(agents={"sales": _Sales})
    pool.add("support", _Support)
    assert sorted(pool.list_agents()) == ["sales", "support"]


def test_invalid_agent_name_in_dict_rejected() -> None:
    with pytest.raises(ValueError, match="ASCII letters, digits"):
        _pool(agents={"bad name": _Sales})


# --- name validation helper -------------------------------------------------


def test_require_agent_name_accepts_alnum_dashes_and_underscores() -> None:
    assert require_agent_name("sales-eu-1") == "sales-eu-1"
    assert require_agent_name("fallback_agent") == "fallback_agent"
    assert require_agent_name("  trimmed  ") == "trimmed"


def test_require_agent_name_rejects_empty() -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        require_agent_name("   ")


def test_require_agent_name_rejects_bad_chars() -> None:
    with pytest.raises(ValueError, match="ASCII letters, digits"):
        require_agent_name("has space")
    with pytest.raises(ValueError, match="ASCII letters, digits"):
        require_agent_name("has.dot")


def test_require_agent_name_rejects_too_long() -> None:
    with pytest.raises(ValueError, match="ASCII letters, digits"):
        require_agent_name("a" * 65)
