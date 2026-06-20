"""RoutingStrategy protocol conformance and precedence preservation."""

from __future__ import annotations

from types import SimpleNamespace

from openrtc.core.routing import (
    _ROUTING_STRATEGIES,
    RoutingStrategy,
    _DefaultFallbackStrategy,
)


def test_concrete_strategies_conform_to_protocol() -> None:
    for strategy in _ROUTING_STRATEGIES:
        assert isinstance(strategy, RoutingStrategy)


def test_strategy_order_is_job_then_room_then_prefix_then_default() -> None:
    kinds = [type(s).__name__ for s in _ROUTING_STRATEGIES]
    assert kinds == [
        "_MetadataStrategy",
        "_MetadataStrategy",
        "_RoomNamePrefixStrategy",
        "_DefaultFallbackStrategy",
    ]


def test_default_fallback_returns_first_registered() -> None:
    agents = {"a": SimpleNamespace(name="a"), "b": SimpleNamespace(name="b")}
    ctx = SimpleNamespace(
        job=SimpleNamespace(metadata=None),
        room=SimpleNamespace(metadata=None, name=None),
    )
    assert _DefaultFallbackStrategy().resolve(agents, ctx).name == "a"  # type: ignore[union-attr]
