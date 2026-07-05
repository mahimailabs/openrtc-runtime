"""Per-agent hot reload: a file change reloads only its own agent (MAH-97).

The reload architecture is per-agent by construction: the coordinator maps each
changed file to the agent whose ``source_path`` matches, and the rebinder only
touches ``registry.sessions_for(config.name)``. These tests pin that isolation
end-to-end through the coordinator with the *real* rebinder + registry (not a
mock), so editing one agent never disturbs a sibling's live sessions.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from livekit.agents import Agent

from openrtc.core.config import AgentConfig
from openrtc.observability.base_observer import SessionInfo
from openrtc.reload.base_reload import ReloadEvent, ReloadResult
from openrtc.reload.coordinator import ReloadCoordinator
from openrtc.reload.session_registry import LiveSessionRegistry
from openrtc.runtime.file_watcher import FileChange


class SalesV1(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="sales v1")


class SalesV2(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="sales v2")


class SupportV1(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="support v1")


class SupportV2(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="support v2")


class _FakeSession:
    """Stand-in exposing the two members the rebinder touches."""

    def __init__(self, agent: Agent) -> None:
        self._agent = agent
        self.update_calls: list[Agent] = []

    @property
    def current_agent(self) -> Agent:
        return self._agent

    def update_agent(self, agent: Agent) -> None:
        self.update_calls.append(agent)
        self._agent = agent


def _register(reg: LiveSessionRegistry, name: str, session: Any, job: str) -> None:
    info = SessionInfo(
        agent_name=name, room_name="r", job_id=job, metadata={}, started_at=0.0
    )
    asyncio.run(reg.on_session_start(info, session))


def test_editing_one_agent_swaps_only_its_sessions(tmp_path: Path) -> None:
    sales_path = tmp_path / "sales.py"
    support_path = tmp_path / "support.py"
    sales_cfg = AgentConfig(name="sales", agent_cls=SalesV1, source_path=sales_path)
    support_cfg = AgentConfig(
        name="support", agent_cls=SupportV1, source_path=support_path
    )

    reg = LiveSessionRegistry()
    sales_session = _FakeSession(SalesV1())
    support_session = _FakeSession(SupportV1())
    _register(reg, "sales", sales_session, "j-sales")
    _register(reg, "support", support_session, "j-support")

    events: list[ReloadEvent] = []
    coord = ReloadCoordinator(
        {"sales": sales_cfg, "support": support_cfg},
        reg,
        report=events.append,
        reloader=lambda _p, _cur: ReloadResult(status="swapped", agent_cls=SalesV2),
        # Real rebinder (default): genuine per-agent scoping via sessions_for().
    )

    asyncio.run(coord.on_change([FileChange(path=sales_path, change_type="modified")]))

    # Exactly one reload event, for sales, tagged with its agent_name.
    assert len(events) == 1
    assert events[0].agent_name == "sales"
    assert events[0].sessions_swapped == 1
    # Sales swapped to v2 (config + live session); support untouched.
    assert sales_cfg.agent_cls is SalesV2
    assert isinstance(sales_session.current_agent, SalesV2)
    assert support_cfg.agent_cls is SupportV1
    assert support_session.update_calls == []
    assert isinstance(support_session.current_agent, SupportV1)


def test_batch_change_reloads_each_agent_independently(tmp_path: Path) -> None:
    sales_path = tmp_path / "sales.py"
    support_path = tmp_path / "support.py"
    sales_cfg = AgentConfig(name="sales", agent_cls=SalesV1, source_path=sales_path)
    support_cfg = AgentConfig(
        name="support", agent_cls=SupportV1, source_path=support_path
    )
    new_by_path: dict[Path, type[Agent]] = {
        sales_path: SalesV2,
        support_path: SupportV2,
    }

    reg = LiveSessionRegistry()
    sales_session = _FakeSession(SalesV1())
    support_session = _FakeSession(SupportV1())
    _register(reg, "sales", sales_session, "j-sales")
    _register(reg, "support", support_session, "j-support")

    events: list[ReloadEvent] = []
    coord = ReloadCoordinator(
        {"sales": sales_cfg, "support": support_cfg},
        reg,
        report=events.append,
        reloader=lambda p, _cur: ReloadResult(
            status="swapped", agent_cls=new_by_path[p]
        ),
    )

    asyncio.run(
        coord.on_change(
            [
                FileChange(path=sales_path, change_type="modified"),
                FileChange(path=support_path, change_type="modified"),
            ]
        )
    )

    assert {e.agent_name for e in events} == {"sales", "support"}
    assert isinstance(sales_session.current_agent, SalesV2)
    assert isinstance(support_session.current_agent, SupportV2)
