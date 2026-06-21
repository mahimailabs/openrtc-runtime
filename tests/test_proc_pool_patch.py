"""The ProcPool patch installs inside the context and reverts on exit."""

from __future__ import annotations

import livekit.agents.ipc.proc_pool as proc_pool_mod

from openrtc.execution.coroutine_server import _CoroutineAgentServer


def test_patch_installs_and_reverts() -> None:
    server = _CoroutineAgentServer(
        max_concurrent_sessions=5, consecutive_failure_limit=5, drain_timeout=30
    )
    original = proc_pool_mod.ProcPool
    original_load_fnc = server._load_fnc
    with server._patched_proc_pool():
        assert proc_pool_mod.ProcPool is not original
        assert server._load_fnc == server._coroutine_load_fnc
    assert proc_pool_mod.ProcPool is original
    assert server._load_fnc == original_load_fnc
