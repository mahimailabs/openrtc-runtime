"""``AgentPool(turn_detector=False)`` keeps the turn detector out of the worker.

Importing ``livekit.plugins.turn_detector.multilingual`` registers livekit's
inference runner, which makes livekit start an inference process (~250 MB).
With the flag off, neither server imports it, prewarm stores no factory, and
sessions fall back to VAD turn detection.
"""

from __future__ import annotations

import builtins
from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import Agent, AgentServer

from openrtc import AgentPool
from openrtc.core.turn_handling import _default_turn_detection
from openrtc.runtime import coroutine_server, process_runtime
from openrtc.runtime import prewarm as prewarm_module
from openrtc.runtime.registry import ServerParams


class DemoAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="demo")


def _record_turn_detector_imports(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    real_import = builtins.__import__

    def _import(
        name: str,
        globals: object = None,  # noqa: A002 — must match __import__ signature
        locals: object = None,  # noqa: A002 — must match __import__ signature
        fromlist: object = (),
        level: int = 0,
    ) -> object:
        if name.startswith("livekit.plugins.turn_detector"):
            seen.append(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _import)
    return seen


async def _no_run(self: Any, **_kwargs: Any) -> None:
    return None


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("module", [coroutine_server, process_runtime])
async def test_server_run_imports_turn_detector_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch, module: Any, enabled: bool
) -> None:
    monkeypatch.setattr(AgentServer, "run", _no_run)
    params = ServerParams(
        max_concurrent_sessions=5,
        consecutive_failure_limit=5,
        drain_timeout=5,
        turn_detector=enabled,
    )
    server = module.build_server(params)
    assert server.turn_detector is enabled
    seen = _record_turn_detector_imports(monkeypatch)

    await server.run()

    assert bool(seen) is enabled


def test_prewarm_skips_turn_detector_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("livekit.plugins.silero")
    pool = AgentPool(turn_detector=False)
    pool.add("a", DemoAgent)
    proc = SimpleNamespace(userdata={})

    def _fail() -> object:
        raise AssertionError("turn detector dependencies must not load")

    monkeypatch.setattr(prewarm_module, "_load_shared_runtime_dependencies", _fail)
    monkeypatch.setattr("livekit.plugins.silero.VAD.load", lambda: "VAD")

    prewarm_module._prewarm_worker(pool._runtime_state, proc)

    assert proc.userdata["vad"] == "VAD"
    assert proc.userdata["turn_detection_factory"] is None


def test_default_turn_detection_uses_vad_without_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LIVEKIT_REMOTE_EOT_URL", raising=False)
    proc = SimpleNamespace(userdata={"vad": object(), "turn_detection_factory": None})

    assert _default_turn_detection(proc, inference_executor="real-exec") == "vad"


def test_pool_threads_turn_detector_flag() -> None:
    pool = AgentPool(turn_detector=False)

    assert pool._runtime_state.turn_detector is False
    assert pool._build_server_params().turn_detector is False
    assert AgentPool()._runtime_state.turn_detector is True
