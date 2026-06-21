"""The server registry resolves isolation modes to builders, lazily."""

from __future__ import annotations

import pytest
from livekit.agents import AgentServer

from openrtc.runtime.coroutine_server import _CoroutineAgentServer
from openrtc.runtime.registry import ServerParams, resolve_server_builder

_PARAMS = ServerParams(
    max_concurrent_sessions=5, consecutive_failure_limit=5, drain_timeout=30
)


def test_process_builder_returns_plain_agent_server() -> None:
    server = resolve_server_builder("process")(_PARAMS)
    assert type(server) is AgentServer


def test_coroutine_builder_returns_coroutine_server() -> None:
    server = resolve_server_builder("coroutine")(_PARAMS)
    assert isinstance(server, _CoroutineAgentServer)
    assert server._max_concurrent_sessions == 5


def test_unknown_mode_raises() -> None:
    with pytest.raises(ValueError, match="Unknown isolation mode"):
        resolve_server_builder("threads")
