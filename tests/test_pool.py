from __future__ import annotations

import pytest
from livekit.agents import Agent

from openrtc import AgentPool


class TestAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="Test agent")


def test_add_registers_agent() -> None:
    pool = AgentPool()

    config = pool.add(
        "test",
        TestAgent,
        stt="deepgram/nova-3",
        llm="openai/gpt-4.1-mini",
        tts="cartesia/sonic-3",
    )

    assert config.name == "test"
    assert pool.list_agents() == ["test"]


def test_add_duplicate_name_raises() -> None:
    pool = AgentPool()
    pool.add("test", TestAgent)

    with pytest.raises(ValueError):
        pool.add("test", TestAgent)


@pytest.mark.parametrize("agent_cls", [str, object])
def test_add_non_agent_raises(agent_cls: type[object]) -> None:
    pool = AgentPool()

    with pytest.raises(TypeError):
        pool.add("test", agent_cls)  # type: ignore[arg-type]


def test_list_agents_returns_registration_order() -> None:
    pool = AgentPool()
    pool.add("restaurant", TestAgent)
    pool.add("dental", TestAgent)

    assert pool.list_agents() == ["restaurant", "dental"]


def test_run_without_agents_raises() -> None:
    pool = AgentPool()

    with pytest.raises(RuntimeError):
        pool.run()
