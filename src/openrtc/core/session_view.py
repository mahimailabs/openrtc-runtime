"""The backend-neutral view of a live job that routing/observability/reload need.

OpenRTC's runtime is coupled to livekit's ``JobContext`` across the routing,
observability, and reload layers. To let those layers run over more than one
framework (livekit today, pipecat next), they read a small neutral view instead
of a framework type: the room name, job id, raw job/room dispatch metadata, the
live session handle, and ``connect()``. Each backend adapts its framework's
context to this ``SessionView``.

This module imports no framework: ``for_livekit`` wraps a livekit ``JobContext``
using only attribute access, so ``import openrtc.core.session_view`` pulls neither
livekit nor pipecat. (See docs/design/framework-agnostic-backend.md. The spec
called this ``SessionContext``; renamed to ``SessionView`` because
``openrtc.observability.session_context`` already owns that name.)
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ["SessionView", "for_livekit", "for_pipecat"]


@runtime_checkable
class SessionView(Protocol):
    """What routing / observability / reload need from a live job, backend-neutral.

    ``job_metadata`` / ``room_metadata`` are the raw dispatch values (a JSON string,
    a mapping, or ``None``); consumers parse them, so a backend never has to. The
    ``session`` handle is the live ``AgentSession`` (livekit) or ``PipelineTask``
    (pipecat), or ``None`` before it is built.
    """

    @property
    def room_name(self) -> str: ...
    @property
    def job_id(self) -> str: ...
    @property
    def job_metadata(self) -> Any: ...
    @property
    def room_metadata(self) -> Any: ...
    @property
    def session(self) -> Any: ...
    async def connect(self) -> None: ...


class _LiveKitSessionView:
    """Adapts a livekit ``JobContext`` to :class:`SessionView` (attribute access only).

    Uses the same defensive ``getattr`` reads the current observability/routing
    code uses, so a missing room name or job id can never turn a healthy session
    into a failed one, matching today's behavior exactly.

    Routing runs before ``ctx.connect()``, so the rtc ``Room`` name/metadata are
    still empty; the authoritative pre-connect values are on ``ctx.job.room`` (the
    dispatch assignment). ``room_name`` and ``room_metadata`` therefore prefer the
    job room, falling back to the rtc room for already-connected or stubbed
    contexts, exactly as the routing strategies did before they read this view.
    """

    __slots__ = ("_ctx",)

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx

    @property
    def room_name(self) -> str:
        job_room = getattr(getattr(self._ctx, "job", None), "room", None)
        name = getattr(job_room, "name", None) or getattr(
            getattr(self._ctx, "room", None), "name", None
        )
        return name if isinstance(name, str) else ""

    @property
    def job_id(self) -> str:
        return getattr(getattr(self._ctx, "job", None), "id", "") or ""

    @property
    def job_metadata(self) -> Any:
        return getattr(getattr(self._ctx, "job", None), "metadata", None)

    @property
    def room_metadata(self) -> Any:
        job_room = getattr(getattr(self._ctx, "job", None), "room", None)
        job_room_metadata = getattr(job_room, "metadata", None)
        if job_room_metadata is not None:
            return job_room_metadata
        return getattr(getattr(self._ctx, "room", None), "metadata", None)

    @property
    def session(self) -> Any:
        # livekit stashes the primary AgentSession here once start() runs (MAH-166).
        return getattr(self._ctx, "_primary_agent_session", None)

    async def connect(self) -> None:
        await self._ctx.connect()


def for_livekit(ctx: Any) -> SessionView:
    """Wrap a livekit ``JobContext`` as a neutral :class:`SessionView`."""
    return _LiveKitSessionView(ctx)


class _PipecatSessionView:
    """Adapts a pipecat ``RunnerArguments`` to :class:`SessionView` (getattr only).

    Pipecat's runner hands one ``RunnerArguments`` per connection. Its ``body``
    dict carries the dispatch payload (where ``{"agent": ...}`` lives, the pipecat
    equivalent of livekit's job metadata), ``session_id`` identifies the call, and
    the room name comes from whichever transport-specific field is present
    (``room_url`` for Daily, ``room_name`` for LiveKit, else the session id). All
    reads are defensive ``getattr`` so a subclass missing a field never raises, and
    no pipecat type is imported, so importing this module stays framework-free.
    """

    __slots__ = ("_args",)

    def __init__(self, runner_args: Any) -> None:
        self._args = runner_args

    @property
    def room_name(self) -> str:
        name = (
            getattr(self._args, "room_url", None)
            or getattr(self._args, "room_name", None)
            or getattr(self._args, "session_id", None)
        )
        return name if isinstance(name, str) else ""

    @property
    def job_id(self) -> str:
        session_id = getattr(self._args, "session_id", None)
        return session_id if isinstance(session_id, str) else ""

    @property
    def job_metadata(self) -> Any:
        return getattr(self._args, "body", None)

    @property
    def room_metadata(self) -> Any:
        # Pipecat has no separate pre-connect room metadata; the dispatch payload
        # rides on body (exposed as job_metadata).
        return None

    @property
    def session(self) -> Any:
        # The serving glue may attach the live PipelineTask here; None until then.
        return getattr(self._args, "session", None)

    async def connect(self) -> None:
        # Pipecat connects inside its transport / runner, so this is a no-op.
        return None


def for_pipecat(runner_args: Any) -> SessionView:
    """Wrap a pipecat ``RunnerArguments`` as a neutral :class:`SessionView`."""
    return _PipecatSessionView(runner_args)
