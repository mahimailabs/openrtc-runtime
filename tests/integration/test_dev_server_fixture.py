"""Smoke test for the integration LiveKit dev server fixture.

Verifies that the fixture either yields a populated
:class:`LiveKitDevServer` (when the harness is running) or skips the
test (when it is not). Either outcome is acceptable for CI; this exists
so the fixture itself is exercised on every run instead of only when
real integration tests are added.
"""

from __future__ import annotations

import pytest

from .conftest import LiveKitDevServer


@pytest.mark.integration
def test_livekit_dev_server_fixture_yields_or_skips(
    livekit_dev_server: LiveKitDevServer,
) -> None:
    # If we got here, the fixture did not skip — sanity-check the shape.
    assert livekit_dev_server.url.startswith(("ws://", "wss://"))
    assert livekit_dev_server.api_key
    assert livekit_dev_server.api_secret
    assert livekit_dev_server.host
    assert livekit_dev_server.port > 0
