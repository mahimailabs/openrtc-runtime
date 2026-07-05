"""Deployment version tag on the pool + runtime snapshot (MAH-110)."""

from __future__ import annotations

import pytest
from livekit.agents import Agent

from openrtc import AgentPool


class _Agent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="a")


def _pool(**kw: object) -> AgentPool:
    return AgentPool(agent=_Agent, enable_introspection=False, **kw)  # type: ignore[arg-type]


def test_deployment_version_defaults_to_none() -> None:
    assert _pool().deployment_version is None


def test_deployment_version_is_stored() -> None:
    assert _pool(deployment_version="v1.2.3").deployment_version == "v1.2.3"


def test_deployment_version_is_stripped() -> None:
    assert _pool(deployment_version="  v2.0.0  ").deployment_version == "v2.0.0"


def test_deployment_version_on_runtime_snapshot() -> None:
    snap = _pool(deployment_version="v1.2.3").runtime_snapshot()
    assert snap.deployment_version == "v1.2.3"
    assert snap.to_dict()["deployment_version"] == "v1.2.3"


def test_deployment_version_none_on_snapshot() -> None:
    snap = _pool().runtime_snapshot()
    assert snap.deployment_version is None
    assert snap.to_dict()["deployment_version"] is None


def test_deployment_version_rejects_blank() -> None:
    with pytest.raises(ValueError, match="deployment_version"):
        _pool(deployment_version="   ")
