from __future__ import annotations

import asyncio
import pickle
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from livekit.agents import Agent

import openrtc.pool as pool_module
from openrtc import AgentPool


class DemoAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="Test agent")


def test_add_registers_agent() -> None:
    pool = AgentPool()

    config = pool.add(
        "test",
        DemoAgent,
        stt="deepgram/nova-3",
        llm="openai/gpt-5-mini",
        tts="cartesia/sonic-3",
    )

    assert config.name == "test"
    assert pool.list_agents() == ["test"]


def test_add_uses_pool_defaults_when_agent_values_are_omitted() -> None:
    pool = AgentPool(
        default_stt="deepgram/nova-3:multi",
        default_llm="openai/gpt-4.1-mini",
        default_tts="cartesia/sonic-3",
        default_greeting="Hello from OpenRTC.",
    )

    config = pool.add("test", DemoAgent)

    assert config.stt == "deepgram/nova-3:multi"
    assert config.llm == "openai/gpt-4.1-mini"
    assert config.tts == "cartesia/sonic-3"
    assert config.greeting == "Hello from OpenRTC."


def test_add_stores_session_kwargs_copy() -> None:
    pool = AgentPool()
    session_kwargs = {
        "preemptive_generation": True,
        "min_endpointing_delay": 0.5,
    }

    config = pool.add("test", DemoAgent, session_kwargs=session_kwargs)
    session_kwargs["preemptive_generation"] = False

    assert config.session_kwargs == {
        "preemptive_generation": True,
        "min_endpointing_delay": 0.5,
    }


def test_add_merges_direct_session_kwargs_with_mapping() -> None:
    pool = AgentPool()
    session_kwargs = {
        "preemptive_generation": False,
        "allow_interruptions": False,
    }

    config = pool.add(
        "test",
        DemoAgent,
        session_kwargs=session_kwargs,
        preemptive_generation=True,
        max_tool_steps=3,
    )
    session_kwargs["allow_interruptions"] = True

    assert config.session_kwargs == {
        "preemptive_generation": True,
        "allow_interruptions": False,
        "max_tool_steps": 3,
    }


def test_add_duplicate_name_raises() -> None:
    pool = AgentPool()
    pool.add("test", DemoAgent)

    with pytest.raises(ValueError):
        pool.add("test", DemoAgent)


@pytest.mark.parametrize("agent_cls", [str, object])
def test_add_non_agent_raises(agent_cls: type[object]) -> None:
    pool = AgentPool()

    with pytest.raises(TypeError):
        pool.add("test", agent_cls)  # type: ignore[arg-type]


def test_add_rejects_local_agent_classes() -> None:
    class LocalAgent(Agent):
        def __init__(self) -> None:
            super().__init__(instructions="Local agent")

    pool = AgentPool()

    with pytest.raises(ValueError, match="module scope"):
        pool.add("local", LocalAgent)


def test_add_rejects_main_module_agent_without_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(DemoAgent, "__module__", "__main__")
    monkeypatch.setattr(pool_module.inspect, "getsourcefile", lambda _value: None)

    pool = AgentPool()

    with pytest.raises(ValueError, match="defined in __main__"):
        pool.add("main-agent", DemoAgent)


@pytest.mark.parametrize("error_type", [OSError, TypeError])
def test_try_get_module_path_returns_none_when_inspect_fails(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    def raise_error(_value: object) -> str:
        raise error_type("boom")

    monkeypatch.setattr(pool_module.inspect, "getsourcefile", raise_error)

    assert pool_module._try_get_module_path(DemoAgent) is None


def test_resolve_agent_class_reuses_loaded_discovered_module(tmp_path: Path) -> None:
    module_path = tmp_path / "agent_module.py"
    module_path.write_text(
        "from livekit.agents import Agent\n\n"
        "class SampleAgent(Agent):\n"
        "    def __init__(self) -> None:\n"
        "        super().__init__(instructions='demo')\n",
        encoding="utf-8",
    )

    module_name = pool_module._discovered_module_name(module_path)
    module = pool_module._load_module_from_path(module_name, module_path)
    agent_ref = pool_module._build_agent_class_ref(module.SampleAgent)

    resolved = pool_module._resolve_agent_class(agent_ref)

    assert resolved is module.SampleAgent


def test_resolve_agent_class_falls_back_to_module_path(tmp_path: Path) -> None:
    module_path = tmp_path / "fallback_agent.py"
    module_path.write_text(
        "from livekit.agents import Agent\n\n"
        "class FallbackAgent(Agent):\n"
        "    def __init__(self) -> None:\n"
        "        super().__init__(instructions='fallback')\n",
        encoding="utf-8",
    )

    agent_ref = pool_module._AgentClassRef(
        module_name="missing_runtime_module",
        qualname="FallbackAgent",
        module_path=str(module_path),
    )

    resolved = pool_module._resolve_agent_class(agent_ref)

    assert resolved.__name__ == "FallbackAgent"
    assert issubclass(resolved, Agent)


def test_resolve_agent_class_raises_when_module_cannot_be_imported() -> None:
    agent_ref = pool_module._AgentClassRef(
        module_name="missing_runtime_module_without_path",
        qualname="MissingAgent",
        module_path=None,
    )

    with pytest.raises(ModuleNotFoundError):
        pool_module._resolve_agent_class(agent_ref)


def test_resolve_agent_class_rejects_non_agent_symbol(tmp_path: Path) -> None:
    module_path = tmp_path / "non_agent_module.py"
    module_path.write_text(
        "class NotAnAgent:\n    pass\n",
        encoding="utf-8",
    )

    agent_ref = pool_module._AgentClassRef(
        module_name="missing_non_agent_module",
        qualname="NotAnAgent",
        module_path=str(module_path),
    )

    with pytest.raises(TypeError, match="is not a livekit.agents.Agent subclass"):
        pool_module._resolve_agent_class(agent_ref)


def test_load_module_from_path_reuses_existing_module(tmp_path: Path) -> None:
    module_path = tmp_path / "reused_module.py"
    module_path.write_text("VALUE = 1\n", encoding="utf-8")

    module_name = "openrtc_test_reused_module"
    first_module = pool_module._load_module_from_path(module_name, module_path)
    second_module = pool_module._load_module_from_path(module_name, module_path)

    assert second_module is first_module


def test_load_module_from_path_cleans_up_sys_modules_on_failure(tmp_path: Path) -> None:
    module_path = tmp_path / "broken_module.py"
    module_path.write_text("raise RuntimeError('boom')\n", encoding="utf-8")

    module_name = "openrtc_test_broken_module"
    with pytest.raises(RuntimeError, match="boom"):
        pool_module._load_module_from_path(module_name, module_path)

    assert module_name not in sys.modules


def test_list_agents_returns_registration_order() -> None:
    pool = AgentPool()
    pool.add("restaurant", DemoAgent)
    pool.add("dental", DemoAgent)

    assert pool.list_agents() == ["restaurant", "dental"]


def test_get_returns_registered_agent() -> None:
    pool = AgentPool()
    config = pool.add("restaurant", DemoAgent)

    assert pool.get("restaurant") is config


def test_get_unknown_agent_raises_key_error() -> None:
    pool = AgentPool()

    with pytest.raises(KeyError, match="Unknown agent 'missing'"):
        pool.get("missing")


def test_remove_returns_removed_agent() -> None:
    pool = AgentPool()
    config = pool.add("restaurant", DemoAgent)

    removed = pool.remove("restaurant")

    assert removed is config
    assert pool.list_agents() == []


def test_remove_unknown_agent_raises_key_error() -> None:
    pool = AgentPool()

    with pytest.raises(KeyError, match="Unknown agent 'missing'"):
        pool.remove("missing")


def test_run_without_agents_raises() -> None:
    pool = AgentPool()

    with pytest.raises(RuntimeError):
        pool.run()


def test_worker_callbacks_are_pickleable_and_keep_registered_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered_session_callback = None
    original_rtc_session = pool_module.AgentServer.rtc_session

    def capture_rtc_session(self: object, *args: object, **kwargs: object):
        decorator = original_rtc_session(self, *args, **kwargs)

        def capture(function: object) -> object:
            nonlocal registered_session_callback
            registered_session_callback = function
            return decorator(function)

        return capture

    monkeypatch.setattr(pool_module.AgentServer, "rtc_session", capture_rtc_session)

    pool = AgentPool()
    pool.add("test", DemoAgent)

    setup_callback = pickle.loads(pickle.dumps(pool.server.setup_fnc))
    assert registered_session_callback is not None
    session_callback = pickle.loads(pickle.dumps(registered_session_callback))

    process = SimpleNamespace(userdata={})

    class FakeVAD:
        @staticmethod
        def load() -> str:
            return "vad"

    class FakeSilero:
        VAD = FakeVAD

    monkeypatch.setattr(
        "openrtc.pool._load_shared_runtime_dependencies",
        lambda: (FakeSilero, lambda: "turn"),
    )
    setup_callback(process)

    assert process.userdata == {"vad": "vad", "turn_detection": "turn"}

    class FakeJobContext:
        def __init__(self) -> None:
            self.job = SimpleNamespace(metadata={"agent": "test"})
            self.room = SimpleNamespace(metadata=None, name="test-room")
            self.proc = process
            self.connected = False

        async def connect(self) -> None:
            self.connected = True

    class FakeSession:
        instances: list[FakeSession] = []

        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            self.started = False
            FakeSession.instances.append(self)

        async def start(self, *, agent: Agent, room: object) -> None:
            self.started = isinstance(agent, DemoAgent) and room is not None

        async def generate_reply(self, *, instructions: str) -> None:
            raise AssertionError("Greeting should not be generated in this test.")

    ctx = FakeJobContext()
    monkeypatch.setattr("openrtc.pool.AgentSession", FakeSession)
    asyncio.run(session_callback(ctx))

    assert ctx.connected is True
    assert FakeSession.instances[0].started is True
