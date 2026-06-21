"""Both isolation-mode servers conform to the SessionRuntime surface."""

from __future__ import annotations

from livekit.agents import AgentServer

from openrtc.runtime.base_runtime import SessionRuntime
from openrtc.runtime.coroutine_server import _CoroutineAgentServer


def test_agent_server_conforms() -> None:
    assert isinstance(AgentServer(drain_timeout=30), SessionRuntime)


def test_coroutine_agent_server_conforms() -> None:
    server = _CoroutineAgentServer(
        max_concurrent_sessions=5,
        consecutive_failure_limit=5,
        drain_timeout=30,
    )
    assert isinstance(server, SessionRuntime)
