"""Local IPC for ``openrtc top``: a Unix-socket server + client (MAH-92).

The worker serves its current introspection snapshot (a ``SessionRow`` list) as
one JSON line over a local Unix domain socket; ``openrtc top`` connects and reads
it each refresh. A Unix socket keeps this **local-only** with no network exposure
(the safe default); ``openrtc top`` is POSIX-only in v0.3 (a Windows named-pipe
transport is deferred). Local pool only — remote/cluster inspection is out of
scope for v0.3, so a single default socket path is assumed unless overridden.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import tempfile
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from openrtc.observability.introspection import SessionRow

__all__ = [
    "IntrospectionServer",
    "default_socket_path",
    "fetch_snapshot",
    "rows_from_json",
    "rows_to_json",
]

SnapshotProvider = Callable[[], list[SessionRow]]


def default_socket_path() -> Path:
    """Return the default local socket path for a single pool on this host."""
    return Path(tempfile.gettempdir()) / "openrtc-top.sock"


def rows_to_json(rows: list[SessionRow]) -> str:
    """Serialize ``SessionRow`` list to one JSON line."""
    return json.dumps([asdict(row) for row in rows])


def rows_from_json(payload: str) -> list[dict[str, Any]]:
    """Parse a JSON snapshot line into row dicts; tolerate a non-list payload."""
    with contextlib.suppress(json.JSONDecodeError):
        data = json.loads(payload)
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
    return []


class IntrospectionServer:
    """Serve the introspection snapshot over a local Unix socket, one line per connect."""

    def __init__(
        self, *, snapshot_provider: SnapshotProvider, socket_path: Path
    ) -> None:
        self._snapshot_provider = snapshot_provider
        self._socket_path = socket_path
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        """Bind the Unix socket (removing any stale one) and begin serving."""
        with contextlib.suppress(FileNotFoundError):
            self._socket_path.unlink()
        self._server = await asyncio.start_unix_server(
            self._handle, path=str(self._socket_path)
        )

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            payload = rows_to_json(self._snapshot_provider())
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


async def fetch_snapshot(
    socket_path: Path, *, timeout: float = 2.0
) -> list[dict[str, Any]]:
    """Connect to a worker's socket and return one snapshot of row dicts."""
    reader, writer = await asyncio.wait_for(
        asyncio.open_unix_connection(path=str(socket_path)), timeout
    )
    try:
        line = await asyncio.wait_for(reader.readline(), timeout)
        return rows_from_json(line.decode())
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
