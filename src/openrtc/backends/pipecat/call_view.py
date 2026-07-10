"""The pipecat call view: a neutral SessionView plus the worker's shared prewarm.

A pipecat pipeline builder receives this instead of a bare ``SessionView`` so it
can reach the shared VAD/turn analyzers (``view.prewarmed.vad``) while the
neutral routing and observability layers keep reading it as a plain
``SessionView``. It forwards every ``SessionView`` member to the wrapped view and
adds ``prewarmed``; keeping prewarm here (not on the neutral seam) leaves routing
/ observability / reload unaware of a backend concern they do not need.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openrtc.backends.pipecat.prewarm import SharedPrewarm
    from openrtc.core.session_view import SessionView


class PipecatCallView:
    """A ``SessionView`` augmented with the worker's shared prewarm."""

    __slots__ = ("_view", "prewarmed")

    def __init__(self, view: SessionView, prewarmed: SharedPrewarm) -> None:
        self._view: SessionView = view
        self.prewarmed = prewarmed

    @property
    def room_name(self) -> str:
        return self._view.room_name

    @property
    def job_id(self) -> str:
        return self._view.job_id

    @property
    def job_metadata(self) -> Any:
        return self._view.job_metadata

    @property
    def room_metadata(self) -> Any:
        return self._view.room_metadata

    @property
    def session(self) -> Any:
        return self._view.session

    async def connect(self) -> None:
        await self._view.connect()
