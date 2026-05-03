"""Pytest configuration and shared fixtures.

LiveKit SDK shim (below): if ``livekit.agents`` cannot be imported, we register a
minimal ``livekit`` / ``livekit.agents`` package so tests can import
``openrtc.core.pool`` without the real wheel. The shapes here mirror only what
OpenRTC uses today; they are **not** a full SDK copy.

**Target:** align with ``livekit-agents`` as pinned in ``pyproject.toml`` (see
``dependencies`` / ``livekit-agents[...]``). When bumping that version or when
OpenRTC starts calling new ``livekit.agents`` APIs, re-check this block: either
extend the stubs or rely on ``uv sync`` + real SDK (normal contributor setup) so
pytest exercises the actual package.

**Drift risk:** new attributes on real ``Agent``, ``AgentServer``, etc. will exist
on the installed SDK but not on these stubs; code paths that only run under the
shim could diverge. Prefer running ``uv run pytest`` after ``uv sync`` before
release; use the shim mainly for documented minimal environments.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


try:
    importlib.import_module("livekit.agents")
except ImportError:
    livekit_module = types.ModuleType("livekit")
    agents_module = types.ModuleType("livekit.agents")

    class Agent:
        def __init__(self, *, instructions: str) -> None:
            self.instructions = instructions

    class AgentServer:
        def __init__(self) -> None:
            self.setup_fnc = None
            self._session_handler = None

        def rtc_session(self, *args: Any, **kwargs: Any):
            def decorator(function):
                self._session_handler = function
                return function

            return decorator

    class AgentSession:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

        async def start(self, *args: Any, **kwargs: Any) -> None:
            return None

    class JobContext:
        def __init__(self) -> None:
            self.job = types.SimpleNamespace(metadata=None)
            self.room = types.SimpleNamespace(metadata=None)
            self.proc = types.SimpleNamespace(userdata={})

        async def connect(self) -> None:
            return None

    class JobProcess:
        def __init__(self) -> None:
            self.userdata: dict[str, Any] = {}

    class RunContext:
        pass

    def function_tool(function):
        return function

    class _CliModule:
        def run_app(self, server: AgentServer) -> None:
            return None

    agents_module.Agent = Agent
    agents_module.AgentServer = AgentServer
    agents_module.AgentSession = AgentSession
    agents_module.JobContext = JobContext
    agents_module.JobProcess = JobProcess
    agents_module.RunContext = RunContext
    agents_module.function_tool = function_tool
    agents_module.cli = _CliModule()

    livekit_module.agents = agents_module

    sys.modules["livekit"] = livekit_module
    sys.modules["livekit.agents"] = agents_module


import pytest

from openrtc.resources import (
    PoolRuntimeSnapshot,
    ProcessResidentSetInfo,
    SavingsEstimate,
)


@pytest.fixture
def minimal_pool_runtime_snapshot() -> PoolRuntimeSnapshot:
    """Small :class:`PoolRuntimeSnapshot` for metrics stream / TUI tests."""
    return PoolRuntimeSnapshot(
        timestamp=1.0,
        uptime_seconds=0.5,
        registered_agents=1,
        active_sessions=0,
        total_sessions_started=0,
        total_session_failures=0,
        last_routed_agent=None,
        last_error=None,
        sessions_by_agent={},
        resident_set=ProcessResidentSetInfo(
            bytes_value=1024,
            metric="test",
            description="test",
        ),
        savings_estimate=SavingsEstimate(
            agent_count=1,
            shared_worker_bytes=1024,
            estimated_separate_workers_bytes=1024,
            estimated_saved_bytes=0,
            assumptions=(),
        ),
    )
