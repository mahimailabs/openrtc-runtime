"""MAH-85: the coroutine server runs a FileWatcher for the run() lifetime."""

from __future__ import annotations

import asyncio
from pathlib import Path

from openrtc.runtime.coroutine_server import _CoroutineAgentServer
from openrtc.runtime.file_watcher import FileChange


async def _noop(_changes: list[FileChange]) -> None:
    return None


def test_attach_reload_stores_callback_and_paths() -> None:
    server = _CoroutineAgentServer()
    paths = [Path("/agents")]
    server.attach_reload(_noop, paths)
    assert server._reload_on_change is _noop
    assert server._reload_watch_paths == paths


def test_reload_watching_starts_and_stops_the_watcher(tmp_path: Path) -> None:
    watched = tmp_path / "agent.py"
    watched.write_text("X = 1\n")
    server = _CoroutineAgentServer()
    server.attach_reload(_noop, [watched])

    async def _drive() -> tuple[str, object]:
        async with server._reload_watching():
            assert server.reload_watcher is not None
            state = server.reload_watcher.state
        return state, server.reload_watcher

    running_state, after = asyncio.run(_drive())
    assert running_state == "running"
    assert after is None


def test_reload_watching_is_a_noop_when_not_attached() -> None:
    server = _CoroutineAgentServer()

    async def _drive() -> object:
        async with server._reload_watching():
            return server.reload_watcher

    assert asyncio.run(_drive()) is None
