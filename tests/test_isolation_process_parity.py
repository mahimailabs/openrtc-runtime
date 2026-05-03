"""Parity tests for ``isolation="process"`` (v0.0.17 behavior).

Design §8 acceptance criterion 7: ``isolation="process"`` mode is
verified to behave identically to v0.0.17. Most existing pool tests
exercise the layer above the server (registration, routing, session
construction, runtime snapshot) and are isolation-agnostic, so we don't
re-parameterise the whole suite. This file pins the v0.0.17 invariants
that DO depend on isolation:

- ``pool.server`` is the vanilla :class:`AgentServer` (not a
  ``_CoroutineAgentServer``).
- The OpenRTC-only kwargs (``max_concurrent_sessions``,
  ``consecutive_failure_limit``) live on the pool only — they are
  never pushed onto the vanilla AgentServer surface.
- The same pool operations (add, list, routing resolution, session
  construction) produce identical observable outputs in both isolation
  modes.
- Constructing ``AgentPool(isolation="process")`` does not import the
  coroutine subsystem (the import is deferred so process-only callers
  pay no cost).
"""

from __future__ import annotations

import asyncio
import sys

import pytest
from livekit.agents import Agent, AgentServer

from openrtc import AgentPool
from openrtc.core.pool import _run_universal_session
from openrtc.core.routing import _resolve_agent_config


class _DemoAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="parity")


@pytest.mark.parametrize("isolation", ["coroutine", "process"])
def test_pool_add_and_list_behave_identically(isolation: str) -> None:
    pool = AgentPool(isolation=isolation)  # type: ignore[arg-type]
    config = pool.add(
        "demo",
        _DemoAgent,
        stt="openai/gpt-4o-mini-transcribe",
        llm="openai/gpt-4.1-mini",
        tts="openai/gpt-4o-mini-tts",
        greeting="hi",
    )

    assert config.name == "demo"
    assert pool.list_agents() == ["demo"]
    assert pool.get("demo") is config


@pytest.mark.parametrize("isolation", ["coroutine", "process"])
def test_pool_runtime_snapshot_starts_clean(isolation: str) -> None:
    pool = AgentPool(isolation=isolation)  # type: ignore[arg-type]
    pool.add("demo", _DemoAgent)

    snapshot = pool.runtime_snapshot()

    assert snapshot.registered_agents == 1
    assert snapshot.active_sessions == 0
    assert snapshot.total_sessions_started == 0
    assert snapshot.total_session_failures == 0


@pytest.mark.parametrize("isolation", ["coroutine", "process"])
def test_routing_resolves_via_module_level_helper_under_both_modes(
    isolation: str,
) -> None:
    """``_resolve_agent_config`` operates on ``pool._agents``; both modes share it."""
    pool = AgentPool(isolation=isolation)  # type: ignore[arg-type]
    pool.add("a", _DemoAgent)
    pool.add("b", _DemoAgent)

    from types import SimpleNamespace

    ctx_a = SimpleNamespace(
        job=SimpleNamespace(metadata={"agent": "a"}),
        room=SimpleNamespace(metadata=None, name="x"),
    )
    ctx_b = SimpleNamespace(
        job=SimpleNamespace(metadata=None),
        room=SimpleNamespace(metadata={"agent": "b"}, name="x"),
    )

    assert _resolve_agent_config(pool._agents, ctx_a).name == "a"
    assert _resolve_agent_config(pool._agents, ctx_b).name == "b"


@pytest.mark.parametrize("isolation", ["coroutine", "process"])
def test_universal_entrypoint_runs_under_both_modes(
    isolation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The universal entrypoint is the same module-level coroutine in both modes."""
    started: list[str] = []

    class _FakeSession:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        async def start(self, *, agent: Agent, room: object) -> None:
            started.append(type(agent).__name__)

        async def generate_reply(self, *, instructions: str) -> None:
            return None

    monkeypatch.setattr("openrtc.core.pool.AgentSession", _FakeSession)

    pool = AgentPool(isolation=isolation)  # type: ignore[arg-type]
    pool.add("demo", _DemoAgent, greeting="hi")

    from types import SimpleNamespace

    ctx = SimpleNamespace(
        job=SimpleNamespace(metadata={"agent": "demo"}),
        room=SimpleNamespace(metadata=None, name="demo-room"),
        proc=SimpleNamespace(
            userdata={"vad": "vad-stub", "turn_detection_factory": lambda: "td"},
            inference_executor=None,
        ),
        connect=lambda: _no_op_async(),
    )

    asyncio.run(_run_universal_session(pool._runtime_state, ctx))

    assert started == ["_DemoAgent"]


async def _no_op_async() -> None:
    return None


def test_process_mode_server_is_vanilla_agent_server() -> None:
    """v0.0.17 invariant: process mode hands callers an unwrapped AgentServer."""
    from openrtc.execution.coroutine_server import _CoroutineAgentServer

    pool = AgentPool(isolation="process")

    assert isinstance(pool.server, AgentServer)
    assert not isinstance(pool.server, _CoroutineAgentServer)


def test_process_mode_server_has_no_openrtc_only_attributes() -> None:
    """v0.0.17 vanilla AgentServer must not learn coroutine-only fields."""
    pool = AgentPool(
        isolation="process",
        max_concurrent_sessions=7,
        consecutive_failure_limit=3,
    )

    assert pool.max_concurrent_sessions == 7
    assert pool.consecutive_failure_limit == 3
    assert not hasattr(pool.server, "_max_concurrent_sessions")
    assert not hasattr(pool.server, "_consecutive_failure_limit")
    assert not hasattr(pool.server, "coroutine_pool")


def test_process_mode_does_not_import_coroutine_subsystem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Process-only callers should not pay for ``execution/coroutine*`` imports.

    The lazy import in ``AgentPool._build_server`` only fires for
    ``isolation="coroutine"``; this test confirms that purging the
    coroutine modules from ``sys.modules`` and constructing a process
    pool does not re-import them.
    """
    for name in ("openrtc.execution.coroutine_server",):
        monkeypatch.delitem(sys.modules, name, raising=False)

    pool = AgentPool(isolation="process")
    assert isinstance(pool.server, AgentServer)
    # The coroutine_server module should not have been re-imported.
    assert "openrtc.execution.coroutine_server" not in sys.modules


@pytest.mark.parametrize("isolation", ["coroutine", "process"])
def test_pool_remove_and_get_keyerror_on_unknown(isolation: str) -> None:
    pool = AgentPool(isolation=isolation)  # type: ignore[arg-type]
    pool.add("demo", _DemoAgent)

    pool.remove("demo")
    assert pool.list_agents() == []

    with pytest.raises(KeyError, match="Unknown agent"):
        pool.get("demo")
    with pytest.raises(KeyError, match="Unknown agent"):
        pool.remove("demo")
