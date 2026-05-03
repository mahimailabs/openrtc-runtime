"""Shared fixtures for ``pytest -m integration`` tests.

The integration suite expects a LiveKit dev server reachable at
``LIVEKIT_URL`` (default ``ws://localhost:7880``). Bring it up with::

    docker compose -f docker-compose.test.yml up -d

Tests under ``tests/integration/`` should be marked
``@pytest.mark.integration`` and may rely on the ``livekit_dev_server``
fixture, which skips the test cleanly when no server is reachable rather
than failing CI in environments that do not run the harness.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator
from dataclasses import dataclass

import pytest


@dataclass(frozen=True)
class LiveKitDevServer:
    """Resolved connection info for the integration LiveKit dev server."""

    url: str
    api_key: str
    api_secret: str
    host: str
    port: int


def _probe(host: str, port: int, timeout: float = 0.5) -> bool:
    """True if a TCP connection to ``host:port`` succeeds within ``timeout``."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def livekit_dev_server() -> Iterator[LiveKitDevServer]:
    """Yield a :class:`LiveKitDevServer` if reachable, else skip the test.

    Reads ``LIVEKIT_URL``/``LIVEKIT_API_KEY``/``LIVEKIT_API_SECRET`` from
    the environment. Defaults match the credentials baked into
    ``docker-compose.test.yml`` (``--dev``: ``devkey`` / ``secret``).
    """
    url = os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
    api_key = os.environ.get("LIVEKIT_API_KEY", "devkey")
    api_secret = os.environ.get("LIVEKIT_API_SECRET", "secret")

    # Resolve the host:port for a TCP probe so we can skip cleanly when
    # the dev server is not running (the URL is ws:// so urllib doesn't
    # help here).
    if "://" not in url:
        pytest.fail(f"LIVEKIT_URL must be a ws:// or wss:// URL; got {url!r}")
    scheme, _, rest = url.partition("://")
    host_port, _, _ = rest.partition("/")
    host, _, port_str = host_port.partition(":")
    if not port_str:
        port_str = "443" if scheme == "wss" else "80"
    try:
        port = int(port_str)
    except ValueError:
        pytest.fail(f"LIVEKIT_URL has a non-numeric port: {url!r}")

    if not _probe(host, port):
        pytest.skip(
            "LiveKit dev server is not reachable at "
            f"{host}:{port}; bring it up with "
            "`docker compose -f docker-compose.test.yml up -d`"
        )

    yield LiveKitDevServer(
        url=url,
        api_key=api_key,
        api_secret=api_secret,
        host=host,
        port=port,
    )
