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
from openrtc.observability.session_context import reset_session_id, set_session_id
from openrtc.routing.resolver import _resolve_agent_config
from openrtc.runtime.prewarm import _prewarm_worker
from openrtc.runtime.resources import PrewarmResources

if TYPE_CHECKING:
    from livekit.agents import JobContext

    from openrtc.runtime.base_runtime import SessionRuntime
    from openrtc.utils.types import AgentRouter, RequestFilter

logger = logging.getLogger("openrtc")

# The on_session_start notification runs in the interactive hot path (before the
# greeting), so it is bounded by this short timeout rather than the larger drain
# budget that bounds the on_session_end notification at teardown.
_OBSERVER_START_TIMEOUT_SECONDS = 5.0

__all__ = ["build_session", "run_session", "run_session_end", "wire_pool"]


@dataclass(slots=True)
class _PoolRuntimeState:
    """Serializable runtime state shared with worker callbacks."""

    agents: dict[str, AgentConfig]
    metrics: RuntimeMetricsStore = field(default_factory=RuntimeMetricsStore)
    observers: list[SessionObserver] = field(default_factory=list)
    observer_timeout: float = 30.0
    # Optional custom dispatch router (MAH-99). In process isolation it rides on
    # the spawned worker's pickled state, so it must be picklable there (a
    # module-level function, not a lambda); coroutine mode accepts any callable.
    router: AgentRouter | None = None


def build_session(
    runtime_state: _PoolRuntimeState,
    ctx: JobContext,
) -> tuple[AgentSession[None], AgentConfig, SessionInfo]:
    """Resolve the agent and construct its AgentSession (no side effects)."""
    if not runtime_state.agents:
        raise RuntimeError("No agents are registered in the pool.")
    config = _resolve_agent_config(
        runtime_state.agents, ctx, router=runtime_state.router
    )
    # The inference executor rides on the JobContext, not the JobProcess; pass it
    # so the turn-detection gate selects the prewarmed multilingual detector
    # instead of always falling back to VAD (MAH-159).
    session_kwargs = _build_session_kwargs(
        config.session_kwargs,
        ctx.proc,
        getattr(ctx, "inference_executor", None),
    )
    session: AgentSession[None] = AgentSession(
        stt=config.stt,  # type: ignore[arg-type]
        llm=config.llm,  # type: ignore[arg-type]
        tts=config.tts,  # type: ignore[arg-type]
        vad=PrewarmResources.vad_from(ctx.proc),
        **session_kwargs,
    )
    info = _build_session_info(config.name, ctx)
    return session, config, info


async def _finish_session(
    runtime_state: _PoolRuntimeState,
    info: SessionInfo,
    agent_name: str,
    error: BaseException | None,
) -> None:
    """Record the session finished and notify observers of its end."""
    runtime_state.metrics.record_session_finished(agent_name)
    outcome = _build_session_outcome(info, error)
    await _notify_session_end(
        runtime_state.observers,
        info,
        outcome,
        timeout=runtime_state.observer_timeout,
    )


def _is_held_open_session(ctx: JobContext) -> bool:
    """Whether the coroutine executor holds this session open past entrypoint return.

    A real (non-fake) job with a primary ``AgentSession`` is held open until the
    room disconnects, so its end must be reported then, not when the entrypoint
    returns. Fake jobs (``simulate_job``) and setup-only entrypoints complete on
    return and so report their end inline.
    """
    if getattr(ctx, "_primary_agent_session", None) is None:
        return False
    is_fake = getattr(ctx, "is_fake_job", None)
    return not (bool(is_fake()) if callable(is_fake) else False)


async def run_session(
    runtime_state: _PoolRuntimeState,
    ctx: JobContext,
) -> None:
    """Run one session through its lifecycle: metrics, observers, greeting."""
    session, config, info = build_session(runtime_state, ctx)
    # Bind the session_id for this task tree so every log record and the
    # per-session attribution (v0.3) can be scoped to this session (MAH-91).
    sid_token = set_session_id(info.job_id)
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
        error = sys.exc_info()[1]
        # For a real coroutine session held open past entrypoint return, defer the
        # finished / on_session_end signal to the executor's real session end (room
        # disconnect) via run_session_end, so metrics (active_sessions) and the
        # live-session registry reflect the true call lifetime, not the greeting
        # boundary (MAH-166). Fake jobs, setup-only entrypoints, process mode, and
        # direct unit-test calls report their end here, unchanged.
        if getattr(ctx, "_openrtc_defer_session_end", False) and _is_held_open_session(
            ctx
        ):
            ctx._openrtc_session_finish = partial(  # type: ignore[attr-defined]
                _finish_session, runtime_state, info, config.name, error
            )
        else:
            await _finish_session(runtime_state, info, config.name, error)
        reset_session_id(sid_token)


async def run_session_end(ctx: JobContext) -> None:
    """Fire a held-open session's deferred end notification at its real end.

    Wired as the coroutine executor's ``on_session_end`` hook: it runs after the
    executor has held the session open until the room disconnected. A no-op when
    the session already reported its end inline (fake jobs, process mode, direct
    unit-test calls), so it never double-fires.
    """
    finish = getattr(ctx, "_openrtc_session_finish", None)
    if finish is None:
        return
    ctx._openrtc_session_finish = None  # type: ignore[attr-defined]
    await finish()


def wire_pool(
    server: SessionRuntime,
    runtime_state: _PoolRuntimeState,
    request_fnc: RequestFilter | None = None,
) -> None:
    """Bind prewarm and the session entrypoint onto the server.

    ``request_fnc`` is LiveKit's per-job accept/reject hook. When ``None`` the
    hook is left at LiveKit's default (accept every job), preserving existing
    behavior; a filter lets the worker scope which rooms it handles.
    ``run_session_end`` is registered as the per-job end hook so a held-open
    coroutine session reports its end at real disconnect (MAH-166).
    """
    server.setup_fnc = partial(_prewarm_worker, runtime_state)
    server.rtc_session(
        on_request=request_fnc,
        on_session_end=run_session_end,
    )(partial(run_session, runtime_state))
