"""Route a pipecat call to its registered builder and build the observed session.

This composes the backend-neutral primitives: the shared name resolver picks
which registered agent handles the call (the same precedence the livekit backend
uses), ``_build_session_info`` builds the call's identity from the view, and
``build_pipecat_session`` invokes the chosen builder and attaches observability.
The result (processors plus lifecycle observer) is run by the dispatch server
(and, in tests, by ``simulate_call``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from openrtc.backends.pipecat.call_view import PipecatCallView
from openrtc.backends.pipecat.prewarm import SharedPrewarm
from openrtc.backends.pipecat.session import build_pipecat_session
from openrtc.observability.base_observer import _build_session_info
from openrtc.routing.resolver import _resolve_agent_name

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pipecat.processors.frame_processor import FrameProcessor

    from openrtc.backends.pipecat.observer import PipecatLifecycleObserver
    from openrtc.backends.pipecat.session import PipelineBuilder
    from openrtc.core.session_view import SessionView
    from openrtc.observability.base_observer import SessionObserver
    from openrtc.utils.types import AgentRouter

__all__ = ["dispatch_pipecat_call"]


def dispatch_pipecat_call(
    view: SessionView,
    builders: Mapping[str, PipelineBuilder],
    *,
    observers: Sequence[SessionObserver],
    timeout: float,
    deployment_version: str | None = None,
    router: AgentRouter | None = None,
    prewarm: SharedPrewarm | None = None,
) -> tuple[list[FrameProcessor], PipecatLifecycleObserver]:
    """Resolve which builder handles a call and build its observed session.

    Routing uses the shared precedence (custom router, then job / room metadata,
    then room-name prefix, then first registered). Raises ``RuntimeError`` when no
    agent is registered, and ``ValueError`` when a routing signal names an
    unregistered agent, matching the livekit backend.

    ``prewarm`` is the worker's shared VAD/turn holder; the neutral view is wrapped
    as a :class:`~openrtc.backends.pipecat.call_view.PipecatCallView` carrying it,
    so the builder reaches the same analyzers on every call. When omitted (direct
    callers that do not use prewarm) a fresh, unloaded holder is used.
    """
    if not builders:
        raise RuntimeError("No agents are registered in the pool.")
    call_view = PipecatCallView(
        view, prewarm if prewarm is not None else SharedPrewarm()
    )
    name = _resolve_agent_name(builders.keys(), call_view, router=router)
    info = _build_session_info(name, call_view, deployment_version)
    return build_pipecat_session(
        builders[name], call_view, info=info, observers=observers, timeout=timeout
    )
