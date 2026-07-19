"""Map a pipecat pipeline's frame boundaries to OpenRTC's neutral session signals.

Pipecat has no session-lifecycle concept OpenRTC can observe; it emits frames. A
``StartFrame`` opens the pipeline, an ``EndFrame`` closes it gracefully, and a
``CancelFrame`` tears it down. This observer watches those boundaries and drives
OpenRTC's framework-neutral ``SessionObserver`` hooks (the same ones the livekit
backend fires), so external telemetry (VoiceGateway, OpenTelemetry) attaches to a
pipecat session exactly as it does to a livekit one.

The observer is attached to a ``PipelineTask`` (``observers=[...]``) and reuses the
neutral notify helpers from :mod:`openrtc.observability.base_observer`.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from pipecat.frames.frames import CancelFrame, EndFrame, StartFrame
from pipecat.observers.base_observer import BaseObserver

from openrtc.observability.base_observer import (
    _build_session_outcome,
    _notify_session_end,
    _notify_session_start,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pipecat.observers.base_observer import FramePushed

    from openrtc.observability.base_observer import SessionInfo, SessionObserver

__all__ = ["PipecatLifecycleObserver"]


class PipecatLifecycleObserver(BaseObserver):
    """Emit OpenRTC ``on_session_start`` / ``on_session_end`` from pipecat frames.

    ``StartFrame`` fires the start (once); the first ``EndFrame`` (success) or
    ``CancelFrame`` (cancelled) fires the end (once). The end is skipped if the
    session never started, matching the livekit backend, which never reports an
    end without a paired start once live.
    """

    def __init__(
        self,
        *,
        info: SessionInfo,
        session: Any,
        observers: Sequence[SessionObserver],
        timeout: float,
    ) -> None:
        super().__init__()
        self._info = info
        self._session = session
        self._observers = observers
        self._timeout = timeout
        self._started = False
        self._ended = False

    @property
    def session_info(self) -> SessionInfo:
        """The neutral session identity this observer reports (for context scoping)."""
        return self._info

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        if isinstance(frame, StartFrame):
            await self._start()
        elif isinstance(frame, (EndFrame, CancelFrame)):
            await self._end(cancelled=isinstance(frame, CancelFrame))

    async def _start(self) -> None:
        if self._started:
            return
        self._started = True
        await _notify_session_start(
            self._observers, self._info, self._session, timeout=self._timeout
        )

    async def _end(self, *, cancelled: bool) -> None:
        if self._ended or not self._started:
            return
        self._ended = True
        error: BaseException | None = asyncio.CancelledError() if cancelled else None
        outcome = _build_session_outcome(self._info, error)
        await _notify_session_end(
            self._observers, self._info, outcome, timeout=self._timeout
        )
