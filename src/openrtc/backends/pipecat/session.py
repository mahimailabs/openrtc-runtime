"""The pipecat universal entrypoint: turn a registered builder into a session.

A pipecat agent registers as a *builder callable* (the model chosen for OpenRTC's
pipecat backend): given the backend-neutral :class:`~openrtc.core.session_view.SessionView`
for a call, it returns the pipecat processors for that call. ``build_pipecat_session``
is the seam that invokes the builder and attaches OpenRTC's observability, so every
pipecat session is observed the same way regardless of how the user assembled its
pipeline. The returned processors and observer are run by the dispatch (and, in
tests, by :func:`openrtc.backends.pipecat.testing.simulate_call`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from openrtc.backends.pipecat.observer import PipecatLifecycleObserver

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pipecat.processors.frame_processor import FrameProcessor

    from openrtc.backends.pipecat.call_view import PipecatCallView
    from openrtc.observability.base_observer import SessionInfo, SessionObserver

    PipelineBuilder = Callable[[PipecatCallView], Sequence[FrameProcessor]]

__all__ = ["build_pipecat_session"]


def build_pipecat_session(
    builder: PipelineBuilder,
    view: PipecatCallView,
    *,
    info: SessionInfo,
    observers: Sequence[SessionObserver],
    timeout: float,
) -> tuple[list[FrameProcessor], PipecatLifecycleObserver]:
    """Invoke a registered builder for a call and attach OpenRTC observability.

    ``view`` is the enriched :class:`~openrtc.backends.pipecat.call_view.PipecatCallView`
    (the neutral view plus shared prewarm), so the builder can reach the worker's
    shared VAD/turn (``view.prewarmed``). Returns the call's pipecat processors and
    a :class:`PipecatLifecycleObserver` bound to this session's ``info`` and live
    handle (``view.session``). The caller runs them (``PipelineWorker(Pipeline(
    processors), observers=[observer])``); the observer then drives
    ``on_session_start`` / ``on_session_end`` from the pipeline's frame boundaries.
    """
    processors = list(builder(view))
    observer = PipecatLifecycleObserver(
        info=info, session=view.session, observers=observers, timeout=timeout
    )
    return processors, observer
