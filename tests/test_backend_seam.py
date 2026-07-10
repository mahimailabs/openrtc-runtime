"""The neutral Backend seam and its livekit adapter (framework-agnostic step).

AgentPool drives its worker substrate through the backend-neutral ``Backend``
seam instead of a livekit type. ``LiveKitBackend`` is the first (and today only)
implementation: it wraps livekit's ``AgentServer`` and owns the wiring of shared
prewarm plus the universal session entrypoint. This is the additive first step;
server construction, run, introspection, reload, and drain still reach the raw
server and are migrated onto the seam in later steps.
"""

from __future__ import annotations

import pytest

from openrtc import AgentPool
from openrtc.backends.livekit.backend import LiveKitBackend
from openrtc.core.backend import Backend
from openrtc.core.wiring import _PoolRuntimeState
from openrtc.runtime.registry import ServerParams, resolve_server_builder

_PARAMS = ServerParams(
    max_concurrent_sessions=10,
    consecutive_failure_limit=3,
    drain_timeout=30,
)


def _server() -> object:
    return resolve_server_builder("coroutine")(_PARAMS)


def test_livekit_backend_conforms_to_backend_protocol() -> None:
    assert isinstance(LiveKitBackend(_server()), Backend)


def test_raw_server_returns_the_wrapped_server() -> None:
    server = _server()
    assert LiveKitBackend(server).raw_server is server


def test_wire_binds_prewarm_and_entrypoint() -> None:
    server = _server()
    backend = LiveKitBackend(server)
    backend.wire(_PoolRuntimeState(agents={}), None, agent_name=None)
    # wire() sets the shared-prewarm setup_fnc and registers the entrypoint.
    assert server.setup_fnc is not None  # type: ignore[attr-defined]


def test_agent_pool_drives_a_livekit_backend() -> None:
    pool = AgentPool()
    assert isinstance(pool._backend, LiveKitBackend)
    assert isinstance(pool._backend, Backend)
    # The raw server stays the same object the pool exposes as .server, so the
    # introspection / reload code that still reads it is unaffected.
    assert pool._server is pool._backend.raw_server
    assert pool.server is pool._backend.raw_server


# --- run / drain migrated onto the Backend ---------------------------------


class _StubCoroutinePool:
    def __init__(self) -> None:
        self.draining = False

    def begin_drain(self) -> None:
        self.draining = True


def test_build_backend_constructs_the_isolation_server() -> None:
    from openrtc.backends.livekit import build_backend
    from openrtc.runtime.coroutine_server import _CoroutineAgentServer

    coroutine = build_backend(_PARAMS, "coroutine")
    assert isinstance(coroutine, LiveKitBackend)
    assert isinstance(coroutine.raw_server, _CoroutineAgentServer)
    assert coroutine.raw_server._max_concurrent_sessions == 10

    process = build_backend(_PARAMS, "process")
    assert isinstance(process, LiveKitBackend)
    assert not isinstance(process.raw_server, _CoroutineAgentServer)


def test_run_delegates_to_cli_run_app(monkeypatch: pytest.MonkeyPatch) -> None:
    import openrtc.backends.livekit.backend as backend_mod

    server = _server()
    captured: list[object] = []
    monkeypatch.setattr(backend_mod.cli, "run_app", lambda s: captured.append(s))
    LiveKitBackend(server).run()
    assert captured == [server]


def test_begin_drain_returns_false_without_a_running_pool() -> None:
    backend = LiveKitBackend(_server())
    assert backend.begin_drain() is False
    assert backend.draining is False


def test_begin_drain_delegates_to_the_coroutine_pool() -> None:
    server = _server()
    server._coroutine_pool = _StubCoroutinePool()  # type: ignore[attr-defined]
    backend = LiveKitBackend(server)
    assert backend.begin_drain() is True
    assert backend.draining is True
    assert server.coroutine_pool.draining is True  # type: ignore[attr-defined]
