"""Local IPC for ``openrtc top``: a Unix-socket server + client (MAH-92).

The worker serves its current introspection snapshot (``{worker, sessions}``: the
host vitals plus the ``SessionRow`` list) as one JSON line over a local Unix domain
socket; ``openrtc top`` connects and reads it each refresh. A Unix socket keeps this **local-only** with no network exposure
(the safe default); ``openrtc top`` is POSIX-only in v0.3 (a Windows named-pipe
transport is deferred). Local pool only — remote/cluster inspection is out of
scope for v0.3, so a single default socket path is assumed unless overridden.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from openrtc.observability.introspection import TopSnapshot

__all__ = [
    "IntrospectionServer",
    "default_socket_path",
    "fetch_snapshot",
    "snapshot_from_json",
    "snapshot_to_json",
]

SnapshotProvider = Callable[[], TopSnapshot]


def _private_runtime_dir() -> Path:
    """Return a per-user 0700 directory for openrtc sockets, creating it if needed.

    Prefers ``$XDG_RUNTIME_DIR`` (a per-user 0700 directory owned by the user);
    otherwise a per-uid subdirectory of the temp dir. Refuses a symlinked
    directory so a hostile local user cannot pre-plant a symlink at the path (a
    /tmp symlink race). Together with the 0600 socket chmod this keeps the
    introspection snapshot readable only by the owning uid.
    """
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(xdg) if xdg else Path(tempfile.gettempdir())
    runtime_dir = base / f"openrtc-{os.getuid()}"
    if runtime_dir.is_symlink():
        raise RuntimeError(f"refusing a symlinked socket directory: {runtime_dir}")
    runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    runtime_dir.chmod(0o700)  # tighten if it pre-existed with looser permissions
    return runtime_dir


def default_socket_path() -> Path:
    """Return the per-user, private default socket path (its directory is 0700).

    The socket itself is chmod'ed to 0600 on bind, so only the owning uid (the
    trusted ``openrtc top`` client) can connect.
    """
    return _private_runtime_dir() / "top.sock"


def snapshot_to_json(snapshot: TopSnapshot) -> str:
    """Serialize a ``TopSnapshot`` to one JSON line: ``{worker, sessions}``."""
    return json.dumps(
        {
            "worker": asdict(snapshot.worker),
            "sessions": [asdict(row) for row in snapshot.sessions],
        }
    )


def snapshot_from_json(payload: str) -> dict[str, Any]:
    """Parse a snapshot line into ``{"worker": dict|None, "sessions": [dict]}``.

    Tolerates a malformed or legacy (bare-list) payload, returning an empty
    snapshot rather than raising, so a stale client never crashes on garbage.
    """
    with contextlib.suppress(json.JSONDecodeError):
        data = json.loads(payload)
        if isinstance(data, dict):
            worker = data.get("worker")
            sessions = data.get("sessions")
            return {
                "worker": worker if isinstance(worker, dict) else None,
                "sessions": [row for row in sessions if isinstance(row, dict)]
                if isinstance(sessions, list)
                else [],
            }
    return {"worker": None, "sessions": []}


class IntrospectionServer:
    """Serve the introspection snapshot over a local Unix socket, one line per connect."""

    def __init__(
        self, *, snapshot_provider: SnapshotProvider, socket_path: Path
    ) -> None:
        self._snapshot_provider = snapshot_provider
        self._socket_path = socket_path
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        """Bind the Unix socket (removing any stale one) and begin serving.

        The socket is chmod'ed to 0600 immediately after bind so only the owning
        uid can connect (connecting to a Unix socket requires write permission on
        the socket file on Linux), preventing local information disclosure to
        other users on the host.
        """
        with contextlib.suppress(FileNotFoundError):
            self._socket_path.unlink()
        self._server = await asyncio.start_unix_server(
            self._handle, path=str(self._socket_path)
        )
        with contextlib.suppress(OSError):
            os.chmod(self._socket_path, 0o600)

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            payload = snapshot_to_json(self._snapshot_provider())
            writer.write(payload.encode() + b"\n")
            await writer.drain()
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def aclose(self) -> None:
        """Stop serving and remove the socket file; idempotent."""
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
            self._server = None
        with contextlib.suppress(FileNotFoundError):
            self._socket_path.unlink()


async def fetch_snapshot(socket_path: Path, *, timeout: float = 2.0) -> dict[str, Any]:
    """Connect to a worker's socket and return one ``{worker, sessions}`` snapshot."""
    reader, writer = await asyncio.wait_for(
        asyncio.open_unix_connection(path=str(socket_path)), timeout
    )
    try:
        line = await asyncio.wait_for(reader.readline(), timeout)
        return snapshot_from_json(line.decode())
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
