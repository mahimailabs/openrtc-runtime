from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from livekit.agents import Agent

from openrtc import AgentPool
from openrtc.core.pool import _run_universal_session
from openrtc.core.routing import _resolve_agent_config


class RestaurantAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="Restaurant")


class DentalAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="Dental")


@dataclass
class FakeProcess:
    userdata: dict[str, Any] = field(
        default_factory=lambda: {
            "vad": object(),
            "turn_detection_factory": lambda: object(),
        }
    )
    inference_executor: object | None = None


@dataclass
class FakeJob:
    metadata: Any = None


@dataclass
class FakeRoom:
    metadata: Any = None
    name: str = "general-room"


EVENT_LOG: list[str] = []


class FakeJobContext:
    def __init__(
        self,
        *,
        job_metadata: Any = None,
        room_metadata: Any = None,
        room_name: str = "general-room",
    ) -> None:
        self.job = FakeJob(metadata=job_metadata)
        self.room = FakeRoom(metadata=room_metadata, name=room_name)
        self.proc = FakeProcess()
        self.events: list[str] = []

    async def connect(self) -> None:
        self.events.append("connect")
        EVENT_LOG.append("connect")


class FakeSession:
    instances: list[FakeSession] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.events: list[str] = []
        self.generated_instructions: list[str] = []
        self.started_agent: Agent | None = None
        self.started_room: FakeRoom | None = None
        FakeSession.instances.append(self)

    async def start(self, *, agent: Agent, room: FakeRoom) -> None:
        self.started_agent = agent
        self.started_room = room
        self.events.append("start")
        EVENT_LOG.append("start")

    async def generate_reply(self, *, instructions: str) -> None:
        self.generated_instructions.append(instructions)
        self.events.append("generate_reply")
        EVENT_LOG.append("generate_reply")


@pytest.fixture(autouse=True)
def reset_fake_session() -> None:
    FakeSession.instances.clear()
    EVENT_LOG.clear()


@pytest.fixture
def pool() -> AgentPool:
    pool = AgentPool()
    pool.add("restaurant", RestaurantAgent, greeting="Welcome to reservations.")
    pool.add(
        "dental",
        DentalAgent,
        session_kwargs={"max_tool_steps": 5},
    )
    return pool


def test_resolve_agent_prefers_job_metadata_over_room_metadata(
    pool: AgentPool,
) -> None:
    ctx = FakeJobContext(
        job_metadata={"agent": "dental"},
        room_metadata={"agent": "restaurant"},
    )

    resolved = _resolve_agent_config(pool._agents, ctx)

    assert resolved.name == "dental"


def test_resolve_agent_supports_demo_metadata_key(pool: AgentPool) -> None:
    ctx = FakeJobContext(job_metadata={"demo": "restaurant"})

    resolved = _resolve_agent_config(pool._agents, ctx)

    assert resolved.name == "restaurant"


def test_resolve_agent_prefers_agent_key_over_demo_key(pool: AgentPool) -> None:
    ctx = FakeJobContext(job_metadata={"agent": "dental", "demo": "restaurant"})

    resolved = _resolve_agent_config(pool._agents, ctx)

    assert resolved.name == "dental"


def test_resolve_agent_matches_room_name_prefix(pool: AgentPool) -> None:
    ctx = FakeJobContext(room_name="dental-follow-up")

    resolved = _resolve_agent_config(pool._agents, ctx)

    assert resolved.name == "dental"


def test_resolve_agent_falls_back_to_first_registered_agent(pool: AgentPool) -> None:
    ctx = FakeJobContext(room_name="general-room")

    resolved = _resolve_agent_config(pool._agents, ctx)

    assert resolved.name == "restaurant"


def test_resolve_agent_raises_for_unknown_metadata_agent(pool: AgentPool) -> None:
    ctx = FakeJobContext(job_metadata={"agent": "missing"})

    with pytest.raises(
        ValueError,
        match="Unknown agent 'missing' requested via job metadata",
    ):
        _resolve_agent_config(pool._agents, ctx)


def test_resolve_agent_raises_when_no_agents_registered() -> None:
    ctx = FakeJobContext()

    with pytest.raises(RuntimeError, match="No agents are registered"):
        _resolve_agent_config({}, ctx)


def test_resolve_agent_uses_room_metadata_when_job_metadata_absent(
    pool: AgentPool,
) -> None:
    ctx = FakeJobContext(room_metadata={"agent": "dental"})

    resolved = _resolve_agent_config(pool._agents, ctx)

    assert resolved.name == "dental"


def test_resolve_agent_parses_json_string_metadata(pool: AgentPool) -> None:
    ctx = FakeJobContext(job_metadata='{"agent": "dental"}')

    resolved = _resolve_agent_config(pool._agents, ctx)

    assert resolved.name == "dental"


def test_resolve_agent_ignores_non_json_string_metadata(pool: AgentPool) -> None:
    ctx = FakeJobContext(job_metadata="not-json", room_name="dental-room")

    resolved = _resolve_agent_config(pool._agents, ctx)

    assert resolved.name == "dental"


def test_resolve_agent_ignores_blank_string_metadata(pool: AgentPool) -> None:
    ctx = FakeJobContext(job_metadata="   ")

    resolved = _resolve_agent_config(pool._agents, ctx)

    assert resolved.name == "restaurant"


def test_resolve_agent_ignores_json_scalar_metadata(pool: AgentPool) -> None:
    ctx = FakeJobContext(job_metadata="42")

    resolved = _resolve_agent_config(pool._agents, ctx)

    assert resolved.name == "restaurant"


def test_resolve_agent_ignores_empty_metadata_value(pool: AgentPool) -> None:
    ctx = FakeJobContext(job_metadata={"agent": "   "})

    resolved = _resolve_agent_config(pool._agents, ctx)

    assert resolved.name == "restaurant"


def test_agent_name_from_metadata_returns_none_for_non_string_non_mapping() -> None:
    """Branch: an int (or list) metadata value bypasses both string and mapping paths."""
    from openrtc.core.routing import _agent_name_from_metadata

    assert _agent_name_from_metadata(42) is None
    assert _agent_name_from_metadata([1, 2, 3]) is None


def test_resolve_agent_falls_back_when_room_name_is_not_a_string(
    pool: AgentPool,
) -> None:
    """Branch: ``room.name`` of None skips the prefix-match loop entirely."""
    ctx = FakeJobContext()
    ctx.room.name = None  # type: ignore[assignment]

    resolved = _resolve_agent_config(pool._agents, ctx)

    assert resolved.name == "restaurant"


def test_remove_changes_default_fallback_order(pool: AgentPool) -> None:
    pool.remove("restaurant")
    ctx = FakeJobContext(room_name="general-room")

    resolved = _resolve_agent_config(pool._agents, ctx)

    assert resolved.name == "dental"


def test_handle_session_passes_session_kwargs_and_provider_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("openrtc.core.pool.AgentSession", FakeSession)
    stt_provider = object()
    llm_provider = object()
    tts_provider = object()
    pool = AgentPool()
    pool.add(
        "dental",
        DentalAgent,
        stt=stt_provider,
        llm=llm_provider,
        tts=tts_provider,
        session_kwargs={"preemptive_generation": True, "max_tool_steps": 4},
    )
    ctx = FakeJobContext(job_metadata={"agent": "dental"})

    asyncio.run(_run_universal_session(pool._runtime_state, ctx))

    session = FakeSession.instances[0]
    assert session.kwargs["stt"] is stt_provider
    assert session.kwargs["llm"] is llm_provider
    assert session.kwargs["tts"] is tts_provider
    assert session.kwargs["preemptive_generation"] is True
    assert session.kwargs["max_tool_steps"] == 4
    assert session.kwargs["vad"] is ctx.proc.userdata["vad"]
    assert session.kwargs["turn_handling"]["interruption"]["mode"] == "vad"
    assert session.kwargs["turn_handling"]["turn_detection"] == "vad"


def test_handle_session_passes_provider_strings_through_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("openrtc.core.pool.AgentSession", FakeSession)
    pool = AgentPool()
    pool.add(
        "dental",
        DentalAgent,
        stt="openai/gpt-4o-mini-transcribe",
        llm="openai/gpt-4.1-mini",
        tts="openai/gpt-4o-mini-tts",
    )
    ctx = FakeJobContext(job_metadata={"agent": "dental"})

    asyncio.run(_run_universal_session(pool._runtime_state, ctx))

    session = FakeSession.instances[0]
    assert session.kwargs["stt"] == "openai/gpt-4o-mini-transcribe"
    assert session.kwargs["llm"] == "openai/gpt-4.1-mini"
    assert session.kwargs["tts"] == "openai/gpt-4o-mini-tts"


def test_handle_session_supports_direct_session_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("openrtc.core.pool.AgentSession", FakeSession)
    pool = AgentPool()
    pool.add(
        "dental",
        DentalAgent,
        session_kwargs={"preemptive_generation": False},
        preemptive_generation=True,
        max_tool_steps=6,
    )
    ctx = FakeJobContext(job_metadata={"agent": "dental"})

    asyncio.run(_run_universal_session(pool._runtime_state, ctx))

    session = FakeSession.instances[0]
    assert session.kwargs["max_tool_steps"] == 6
    assert session.kwargs["preemptive_generation"] is True
    assert session.kwargs["turn_handling"]["interruption"]["mode"] == "vad"


def test_handle_session_preserves_explicit_turn_handling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("openrtc.core.pool.AgentSession", FakeSession)
    custom_turn_detection = object()
    pool = AgentPool()
    pool.add(
        "dental",
        DentalAgent,
        session_kwargs={
            "turn_handling": {
                "turn_detection": custom_turn_detection,
                "interruption": {"mode": "adaptive", "enabled": False},
            }
        },
    )
    ctx = FakeJobContext(job_metadata={"agent": "dental"})

    asyncio.run(_run_universal_session(pool._runtime_state, ctx))

    session = FakeSession.instances[0]
    assert session.kwargs["turn_handling"]["turn_detection"] is custom_turn_detection
    assert session.kwargs["turn_handling"]["interruption"]["mode"] == "adaptive"
    assert session.kwargs["turn_handling"]["interruption"]["enabled"] is False


def test_handle_session_uses_multilingual_turn_detection_when_inference_executor_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("openrtc.core.pool.AgentSession", FakeSession)
    pool = AgentPool()
    pool.add("dental", DentalAgent)
    ctx = FakeJobContext(job_metadata={"agent": "dental"})
    ctx.proc.inference_executor = object()

    asyncio.run(_run_universal_session(pool._runtime_state, ctx))

    session = FakeSession.instances[0]
    assert session.kwargs["turn_handling"]["turn_detection"] is not None
    assert session.kwargs["turn_handling"]["turn_detection"] != "vad"


def test_handle_session_generates_greeting_after_connect(
    monkeypatch: pytest.MonkeyPatch,
    pool: AgentPool,
) -> None:
    monkeypatch.setattr("openrtc.core.pool.AgentSession", FakeSession)
    ctx = FakeJobContext(job_metadata={"agent": "restaurant"})

    asyncio.run(_run_universal_session(pool._runtime_state, ctx))

    session = FakeSession.instances[0]
    assert session.events == ["start", "generate_reply"]
    assert ctx.events == ["connect"]
    assert session.generated_instructions == ["Welcome to reservations."]
    assert EVENT_LOG == ["start", "connect", "generate_reply"]


def test_handle_session_skips_greeting_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
    pool: AgentPool,
) -> None:
    monkeypatch.setattr("openrtc.core.pool.AgentSession", FakeSession)
    ctx = FakeJobContext(job_metadata={"agent": "dental"})

    asyncio.run(_run_universal_session(pool._runtime_state, ctx))

    session = FakeSession.instances[0]
    assert session.events == ["start"]
    assert ctx.events == ["connect"]
    assert session.generated_instructions == []
    assert EVENT_LOG == ["start", "connect"]
