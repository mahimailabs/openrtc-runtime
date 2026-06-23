"""Composition root: the worker object graph and the session entrypoint."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING

from livekit.agents import AgentSession

from openrtc.core.config import AgentConfig
from openrtc.core.turn_handling import _build_session_kwargs
from openrtc.observability.base_observer import (
    SessionInfo,
    SessionObserver,
    _build_session_info,
    _build_session_outcome,
    _notify_session_end,
    _notify_session_start,
)
from openrtc.observability.metrics import RuntimeMetricsStore
from openrtc.routing.resolver import _resolve_agent_config
from openrtc.runtime.prewarm import _prewarm_worker
from openrtc.runtime.resources import PrewarmResources

if TYPE_CHECKING:
    from livekit.agents import JobContext

    from openrtc.runtime.base_runtime import SessionRuntime

logger = logging.getLogger("openrtc")

# The on_session_start notification runs in the interactive hot path (before the
# greeting), so it is bounded by this short timeout rather than the larger drain
# budget that bounds the on_session_end notification at teardown.
_OBSERVER_START_TIMEOUT_SECONDS = 5.0

__all__ = ["build_session", "run_session", "wire_pool"]


@dataclass(slots=True)
class _PoolRuntimeState:
    """Serializable runtime state shared with worker callbacks."""

    agents: dict[str, AgentConfig]
    metrics: RuntimeMetricsStore = field(default_factory=RuntimeMetricsStore)
    observers: list[SessionObserver] = field(default_factory=list)
    observer_timeout: float = 30.0


def build_session(
    runtime_state: _PoolRuntimeState,
    ctx: JobContext,
) -> tuple[AgentSession[None], AgentConfig, SessionInfo]:
    """Resolve the agent and construct its AgentSession (no side effects)."""
    if not runtime_state.agents:
        raise RuntimeError("No agents are registered in the pool.")
    config = _resolve_agent_config(runtime_state.agents, ctx)
    session_kwargs = _build_session_kwargs(config.session_kwargs, ctx.proc)
    session: AgentSession[None] = AgentSession(
        stt=config.stt,  # type: ignore[arg-type]
        llm=config.llm,  # type: ignore[arg-type]
        tts=config.tts,  # type: ignore[arg-type]
        vad=PrewarmResources.vad_from(ctx.proc),
        **session_kwargs,
    )
    info = _build_session_info(config.name, ctx)
    return session, config, info


async def run_session(
    runtime_state: _PoolRuntimeState,
    ctx: JobContext,
) -> None:
    """Run one session through its lifecycle: metrics, observers, greeting."""
    session, config, info = build_session(runtime_state, ctx)
    try:
        runtime_state.metrics.record_session_started(config.name)
        # Connect before starting the session. start() fires the agent's
        # on_enter as a detached task (livekit schedules it with
        # wait_on_enter=False); if the room is not connected yet, any on_enter
        # that touches room.local_participant raises "cannot access local
        # participant before connecting". connect() is idempotent, so start()'s
        # own internal connect is a no-op.
        await ctx.connect()
        await session.start(
            agent=config.agent_cls(),  # type: ignore[call-arg]
            room=ctx.room,
        )
        await _notify_session_start(
            runtime_state.observers,
            info,
            session,
            timeout=min(
                runtime_state.observer_timeout, _OBSERVER_START_TIMEOUT_SECONDS
            ),
        )
        if config.greeting is not None:
            logger.debug("Generating greeting for agent '%s'.", config.name)
            await session.generate_reply(instructions=config.greeting)
    except Exception as exc:
        runtime_state.metrics.record_session_failure(config.name, exc)
        raise
    finally:
        runtime_state.metrics.record_session_finished(config.name)
        outcome = _build_session_outcome(info, sys.exc_info()[1])
        await _notify_session_end(
            runtime_state.observers,
            info,
            outcome,
            timeout=runtime_state.observer_timeout,
        )


def wire_pool(server: SessionRuntime, runtime_state: _PoolRuntimeState) -> None:
    """Bind prewarm and the session entrypoint onto the server."""
    server.setup_fnc = partial(_prewarm_worker, runtime_state)
    server.rtc_session()(partial(run_session, runtime_state))
