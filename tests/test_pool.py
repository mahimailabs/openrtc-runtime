from __future__ import annotations

import asyncio
import pickle
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest
from livekit.agents import Agent

import openrtc.core.discovery as discovery_module
import openrtc.core.pool as pool_module
import openrtc.core.serialization as serialization_module
from openrtc import AgentPool


class DemoAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="Test agent")


def test_add_registers_agent() -> None:
    pool = AgentPool()

    config = pool.add(
        "test",
        DemoAgent,
        stt="openai/gpt-4o-mini-transcribe",
        llm="openai/gpt-5-mini",
        tts="openai/gpt-4o-mini-tts",
    )

    assert config.name == "test"
    assert pool.list_agents() == ["test"]


def test_isolation_defaults_to_coroutine() -> None:
    """v0.1 default is coroutine mode; the setting is plumbed but not yet acted on."""
    pool = AgentPool()

    assert pool.isolation == "coroutine"


def test_isolation_accepts_process_mode() -> None:
    pool = AgentPool(isolation="process")

    assert pool.isolation == "process"


def test_isolation_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="isolation must be 'coroutine' or 'process'"):
        AgentPool(isolation="threaded")  # type: ignore[arg-type]


def test_add_uses_pool_defaults_when_agent_values_are_omitted() -> None:
    pool = AgentPool(
        default_stt="openai/gpt-4o-mini-transcribe",
        default_llm="openai/gpt-4.1-mini",
        default_tts="openai/gpt-4o-mini-tts",
        default_greeting="Hello from OpenRTC.",
    )

    config = pool.add("test", DemoAgent)

    assert config.stt == "openai/gpt-4o-mini-transcribe"
    assert config.llm == "openai/gpt-4.1-mini"
    assert config.tts == "openai/gpt-4o-mini-tts"
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


def test_add_rejects_non_pickleable_unsupported_provider_object() -> None:
    class UnsupportedProvider:
        def __init__(self) -> None:
            import threading

            self.lock = threading.RLock()

    pool = AgentPool()

    with pytest.raises(ValueError, match="not spawn-safe"):
        pool.add("test", DemoAgent, stt=UnsupportedProvider())


def test_add_rejects_main_module_agent_without_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(DemoAgent, "__module__", "__main__")
    monkeypatch.setattr(discovery_module.inspect, "getsourcefile", lambda _value: None)

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

    monkeypatch.setattr(discovery_module.inspect, "getsourcefile", raise_error)

    assert discovery_module._try_get_module_path(DemoAgent) is None


def test_resolve_agent_class_reuses_loaded_discovered_module(tmp_path: Path) -> None:
    module_path = tmp_path / "agent_module.py"
    module_path.write_text(
        "from livekit.agents import Agent\n\n"
        "class SampleAgent(Agent):\n"
        "    def __init__(self) -> None:\n"
        "        super().__init__(instructions='demo')\n",
        encoding="utf-8",
    )

    module_name = discovery_module._discovered_module_name(module_path)
    module = discovery_module._load_module_from_path(module_name, module_path)
    agent_ref = serialization_module._build_agent_class_ref(module.SampleAgent)

    resolved = serialization_module._resolve_agent_class(agent_ref)

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

    agent_ref = serialization_module._AgentClassRef(
        module_name="missing_runtime_module",
        qualname="FallbackAgent",
        module_path=str(module_path),
    )

    resolved = serialization_module._resolve_agent_class(agent_ref)

    assert resolved.__name__ == "FallbackAgent"
    assert issubclass(resolved, Agent)


def test_resolve_agent_class_raises_when_module_cannot_be_imported() -> None:
    agent_ref = serialization_module._AgentClassRef(
        module_name="missing_runtime_module_without_path",
        qualname="MissingAgent",
        module_path=None,
    )

    with pytest.raises(ModuleNotFoundError):
        serialization_module._resolve_agent_class(agent_ref)


def test_resolve_agent_class_rejects_non_agent_symbol(tmp_path: Path) -> None:
    module_path = tmp_path / "non_agent_module.py"
    module_path.write_text(
        "class NotAnAgent:\n    pass\n",
        encoding="utf-8",
    )

    agent_ref = serialization_module._AgentClassRef(
        module_name="missing_non_agent_module",
        qualname="NotAnAgent",
        module_path=str(module_path),
    )

    with pytest.raises(TypeError, match="is not a livekit.agents.Agent subclass"):
        serialization_module._resolve_agent_class(agent_ref)


def test_load_module_from_path_reuses_existing_module(tmp_path: Path) -> None:
    module_path = tmp_path / "reused_module.py"
    module_path.write_text("VALUE = 1\n", encoding="utf-8")

    module_name = "openrtc_test_reused_module"
    first_module = discovery_module._load_module_from_path(module_name, module_path)
    second_module = discovery_module._load_module_from_path(module_name, module_path)

    assert second_module is first_module


def test_load_module_from_path_cleans_up_sys_modules_on_failure(tmp_path: Path) -> None:
    module_path = tmp_path / "broken_module.py"
    module_path.write_text("raise RuntimeError('boom')\n", encoding="utf-8")

    module_name = "openrtc_test_broken_module"
    with pytest.raises(RuntimeError, match="boom"):
        discovery_module._load_module_from_path(module_name, module_path)

    assert module_name not in sys.modules


def test_agent_config_is_pickleable_with_openai_provider_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    openai = pytest.importorskip("livekit.plugins.openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pool = AgentPool()

    config = pool.add(
        "test",
        DemoAgent,
        stt=openai.STT(model="gpt-4o-mini-transcribe"),
        llm=openai.responses.LLM(model="gpt-4.1-mini"),
        tts=openai.TTS(model="gpt-4o-mini-tts"),
    )

    restored = pickle.loads(pickle.dumps(config))

    assert restored.name == "test"
    assert restored.agent_cls is DemoAgent
    assert restored.stt.__class__.__module__ == "livekit.plugins.openai.stt"
    assert restored.llm.__class__.__module__ == "livekit.plugins.openai.responses.llm"
    assert restored.tts.__class__.__module__ == "livekit.plugins.openai.tts"


def test_generic_livekit_plugin_with_opts_is_accepted() -> None:
    """Non-OpenAI livekit plugins with ``_opts`` should serialize via the generic path."""

    class FakeOpts:
        model = "nova-3"

    # Create a class whose module looks like a livekit plugin
    FakeSTT = type("STT", (), {"__module__": "livekit.plugins.deepgram.stt"})
    instance = FakeSTT()
    instance._opts = FakeOpts()  # type: ignore[attr-defined]

    pool = AgentPool()
    # Should not raise — the generic _opts path handles it
    config = pool.add("test", DemoAgent, stt=instance)
    assert config.stt is not None


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
    openai = pytest.importorskip("livekit.plugins.openai")
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

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pool = AgentPool(
        default_stt=openai.STT(model="gpt-4o-mini-transcribe"),
        default_llm=openai.responses.LLM(model="gpt-4.1-mini"),
        default_tts=openai.TTS(model="gpt-4o-mini-tts"),
    )
    pool.add("test", DemoAgent)

    setup_callback = pickle.loads(pickle.dumps(pool.server.setup_fnc))
    assert registered_session_callback is not None
    session_callback = pickle.loads(pickle.dumps(registered_session_callback))

    process = SimpleNamespace(userdata={}, inference_executor=None)

    class FakeVAD:
        @staticmethod
        def load() -> str:
            return "vad"

    turn_factory_calls = 0

    class FakeTurnDetector:
        def __init__(self) -> None:
            nonlocal turn_factory_calls
            turn_factory_calls += 1

    class FakeSilero:
        VAD = FakeVAD

    monkeypatch.setattr(
        "openrtc.core.pool._load_shared_runtime_dependencies",
        lambda: (FakeSilero, FakeTurnDetector),
    )
    setup_callback(process)

    assert process.userdata == {
        "vad": "vad",
        "turn_detection_factory": FakeTurnDetector,
    }
    assert turn_factory_calls == 0

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
    monkeypatch.setattr("openrtc.core.pool.AgentSession", FakeSession)
    asyncio.run(session_callback(ctx))

    assert ctx.connected is True
    assert FakeSession.instances[0].started is True
    assert (
        FakeSession.instances[0].kwargs["stt"].__class__.__module__
        == "livekit.plugins.openai.stt"
    )
    assert (
        FakeSession.instances[0].kwargs["llm"].__class__.__module__
        == "livekit.plugins.openai.responses.llm"
    )
    assert (
        FakeSession.instances[0].kwargs["tts"].__class__.__module__
        == "livekit.plugins.openai.tts"
    )
    assert (
        FakeSession.instances[0].kwargs["turn_handling"]["interruption"]["mode"]
        == "vad"
    )
    assert FakeSession.instances[0].kwargs["turn_handling"]["turn_detection"] == "vad"
    assert turn_factory_calls == 0


def test_runtime_snapshot_reports_active_sessions_and_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = AgentPool()
    pool.add("test", DemoAgent)

    class FakeJobContext:
        def __init__(self) -> None:
            self.job = SimpleNamespace(metadata={"agent": "test"})
            self.room = SimpleNamespace(metadata=None, name="test-room")
            self.proc = SimpleNamespace(
                userdata={"vad": "vad", "turn_detection_factory": lambda: "vad"},
                inference_executor=None,
            )

        async def connect(self) -> None:
            return None

    release_session = asyncio.Event()

    class FakeSession:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        async def start(self, *, agent: Agent, room: object) -> None:
            await release_session.wait()

        async def generate_reply(self, *, instructions: str) -> None:
            return None

    monkeypatch.setattr("openrtc.core.pool.AgentSession", FakeSession)
    ctx = FakeJobContext()

    async def run_session() -> None:
        await pool_module._run_universal_session(pool._runtime_state, ctx)

    async def exercise() -> None:
        task = asyncio.create_task(run_session())
        await asyncio.sleep(0)
        snapshot = pool.runtime_snapshot()
        assert snapshot.active_sessions == 1
        assert snapshot.total_sessions_started == 1
        assert snapshot.sessions_by_agent == {"test": 1}

        release_session.set()
        await task

    asyncio.run(exercise())

    final_snapshot = pool.runtime_snapshot()
    assert final_snapshot.active_sessions == 0
    assert final_snapshot.total_sessions_started == 1
    assert final_snapshot.total_session_failures == 0


def test_runtime_snapshot_records_session_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = AgentPool()
    pool.add("test", DemoAgent)

    class FakeJobContext:
        def __init__(self) -> None:
            self.job = SimpleNamespace(metadata={"agent": "test"})
            self.room = SimpleNamespace(metadata=None, name="test-room")
            self.proc = SimpleNamespace(
                userdata={"vad": "vad", "turn_detection_factory": lambda: "vad"},
                inference_executor=None,
            )

        async def connect(self) -> None:
            return None

    class FakeSession:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        async def start(self, *, agent: Agent, room: object) -> None:
            raise RuntimeError("boom")

        async def generate_reply(self, *, instructions: str) -> None:
            return None

    monkeypatch.setattr("openrtc.core.pool.AgentSession", FakeSession)

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(
            pool_module._run_universal_session(pool._runtime_state, FakeJobContext())
        )

    snapshot = pool.runtime_snapshot()
    assert snapshot.active_sessions == 0
    assert snapshot.total_sessions_started == 1
    assert snapshot.total_session_failures == 1
    assert snapshot.last_routed_agent == "test"
    assert snapshot.last_error == "RuntimeError: boom"


def test_runtime_snapshot_does_not_leak_active_sessions_when_session_build_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = AgentPool()
    pool.add("test", DemoAgent)

    class FakeJobContext:
        def __init__(self) -> None:
            self.job = SimpleNamespace(metadata={"agent": "test"})
            self.room = SimpleNamespace(metadata=None, name="test-room")
            self.proc = SimpleNamespace(
                userdata={"vad": "vad", "turn_detection_factory": lambda: "vad"},
                inference_executor=None,
            )

        async def connect(self) -> None:
            return None

    def raise_build_error(
        configured_kwargs: dict[str, object],
        proc: object,
    ) -> dict[str, object]:
        raise RuntimeError("session kwargs boom")

    monkeypatch.setattr("openrtc.core.pool._build_session_kwargs", raise_build_error)

    with pytest.raises(RuntimeError, match="session kwargs boom"):
        asyncio.run(
            pool_module._run_universal_session(pool._runtime_state, FakeJobContext())
        )

    snapshot = pool.runtime_snapshot()
    assert snapshot.active_sessions == 0
    assert snapshot.total_sessions_started == 0
    assert snapshot.total_session_failures == 0
    assert snapshot.sessions_by_agent == {}


def test_runtime_snapshot_does_not_leak_active_sessions_when_session_constructor_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = AgentPool()
    pool.add("test", DemoAgent)

    class FakeJobContext:
        def __init__(self) -> None:
            self.job = SimpleNamespace(metadata={"agent": "test"})
            self.room = SimpleNamespace(metadata=None, name="test-room")
            self.proc = SimpleNamespace(
                userdata={"vad": "vad", "turn_detection_factory": lambda: "vad"},
                inference_executor=None,
            )

        async def connect(self) -> None:
            return None

    class BrokenSession:
        def __init__(self, **kwargs: object) -> None:
            raise RuntimeError("session constructor boom")

    monkeypatch.setattr("openrtc.core.pool.AgentSession", BrokenSession)

    with pytest.raises(RuntimeError, match="session constructor boom"):
        asyncio.run(
            pool_module._run_universal_session(pool._runtime_state, FakeJobContext())
        )

    snapshot = pool.runtime_snapshot()
    assert snapshot.active_sessions == 0
    assert snapshot.total_sessions_started == 0
    assert snapshot.total_session_failures == 0
    assert snapshot.sessions_by_agent == {}


def test_drain_metrics_stream_events_delegates_to_runtime_store() -> None:
    pool = AgentPool()
    pool.add("test", DemoAgent, stt="a", llm="b", tts="c")
    assert pool.drain_metrics_stream_events() == []


def test_is_not_given_detects_openai_sentinels_without_repr() -> None:
    pytest.importorskip("openai")
    from openai import NOT_GIVEN, not_given

    from openrtc.core.serialization import _is_not_given

    assert _is_not_given(NOT_GIVEN) is True
    assert _is_not_given(not_given) is True
    assert _is_not_given("NOT_GIVEN") is False
    assert _is_not_given(None) is False


def test_is_not_given_ignores_unrelated_class_named_notgiven() -> None:
    from openrtc.core.serialization import _is_not_given

    class NotGiven:
        pass

    assert _is_not_given(NotGiven()) is False


def test_deprecated_session_kwargs_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = AgentPool()

    class FakeSession:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        async def start(self, *, agent: object, room: object) -> None:
            return None

    monkeypatch.setattr("openrtc.core.pool.AgentSession", FakeSession)
    pool.add(
        "test",
        DemoAgent,
        session_kwargs={
            "min_endpointing_delay": 0.3,
            "allow_interruptions": False,
        },
    )
    ctx = SimpleNamespace(
        job=SimpleNamespace(metadata={"agent": "test"}),
        room=SimpleNamespace(metadata=None, name="test-room"),
        proc=SimpleNamespace(
            userdata={"vad": "vad", "turn_detection_factory": lambda: "td"},
            inference_executor=None,
        ),
    )

    async def do_connect(self: object) -> None:
        return None

    ctx.connect = do_connect.__get__(ctx, type(ctx))  # type: ignore[attr-defined]

    with pytest.warns(DeprecationWarning, match="turn_handling"):
        asyncio.run(pool_module._run_universal_session(pool._runtime_state, ctx))


def test_no_warning_for_modern_session_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = AgentPool()

    class FakeSession:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        async def start(self, *, agent: object, room: object) -> None:
            return None

    monkeypatch.setattr("openrtc.core.pool.AgentSession", FakeSession)
    pool.add(
        "test",
        DemoAgent,
        session_kwargs={"preemptive_generation": True, "max_tool_steps": 3},
    )
    ctx = SimpleNamespace(
        job=SimpleNamespace(metadata={"agent": "test"}),
        room=SimpleNamespace(metadata=None, name="test-room"),
        proc=SimpleNamespace(
            userdata={"vad": "vad", "turn_detection_factory": lambda: "td"},
            inference_executor=None,
        ),
    )

    async def do_connect(self: object) -> None:
        return None

    ctx.connect = do_connect.__get__(ctx, type(ctx))  # type: ignore[attr-defined]

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        asyncio.run(pool_module._run_universal_session(pool._runtime_state, ctx))
