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
