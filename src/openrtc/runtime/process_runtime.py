"""Process-mode runtime: one OS process per session via livekit's default server."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from livekit.agents import AgentServer

if TYPE_CHECKING:
    from openrtc.observability.process_top import ProcessIntrospectionRuntime
    from openrtc.runtime.registry import ServerParams

__all__ = ["build_server"]


class _ProcessAgentServer(AgentServer):
    """livekit's stock server, plus the ``openrtc top`` socket around ``run()``."""

    _openrtc_top: ProcessIntrospectionRuntime | None = None

    def attach_introspection(self, runtime: ProcessIntrospectionRuntime) -> None:
        """Serve ``openrtc top`` while the worker runs."""
        self._openrtc_top = runtime

    async def run(self, *, devmode: bool = False, unregistered: bool = False) -> None:
        # Register the turn detector's inference runner before livekit decides
        # whether to start its inference process: livekit checks the registered
        # runners before prewarm runs, so without this import every turn fails
        # with "no inference executor" (same fix as the coroutine server).
        with contextlib.suppress(Exception):
            from livekit.plugins.turn_detector.multilingual import (  # noqa: F401
                MultilingualModel as _M,
            )
        top = self._openrtc_top
        if top is None:
            await super().run(devmode=devmode, unregistered=unregistered)
            return
        await top.start()
        try:
            await super().run(devmode=devmode, unregistered=unregistered)
        finally:
            await top.aclose()


def build_server(params: ServerParams) -> AgentServer:
    """Build the process-mode server: livekit's own, one subprocess per call.

    livekit enforces ``job_memory_*_mb`` per subprocess natively in this mode.
    """
    return _ProcessAgentServer(
        drain_timeout=params.drain_timeout,
        job_memory_warn_mb=params.memory_warn_mb,
        job_memory_limit_mb=params.memory_limit_mb,
        **params.port_kwargs(),
    )
