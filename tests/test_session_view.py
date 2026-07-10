"""Neutral SessionView seam (framework-agnostic backend, step 1).

The routing, observability, and reload layers only need a small, backend-neutral
view of a live job: the room name, job id, raw job/room dispatch metadata, the
live session handle, and connect(). SessionView is that view. This is the
additive first step: the seam and a livekit adapter, with no existing runtime
code retargeted onto it yet.

(The spec named this SessionContext; renamed to SessionView because
openrtc.observability.session_context already owns that name for the per-session
contextvars.)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from openrtc.core.session_view import SessionView, for_livekit, for_pipecat


def _livekit_ctx(
    *,
    room_name="sales-1",
    job_id="j1",
    job_meta=None,
    room_meta=None,
    job_room_name=None,
    job_room_meta=None,
):
    connected = {"value": False}

    async def _connect() -> None:
        connected["value"] = True

    job = SimpleNamespace(id=job_id, metadata=job_meta)
    # Real livekit jobs carry the pre-connect room on ctx.job.room; add it only
    # when a test asks for one so the "job room absent" fallback stays exercised.
    if job_room_name is not None or job_room_meta is not None:
        job.room = SimpleNamespace(name=job_room_name or "", metadata=job_room_meta)

    ctx = SimpleNamespace(
        room=SimpleNamespace(name=room_name, metadata=room_meta),
        job=job,
        connect=_connect,
        _primary_agent_session="LIVE_SESSION",
    )
    return ctx, connected


def test_for_livekit_exposes_the_neutral_surface() -> None:
    ctx, _ = _livekit_ctx(
        room_name="sales-1", job_id="j1", job_meta='{"agent": "sales"}', room_meta=None
    )
    sv = for_livekit(ctx)
    assert isinstance(sv, SessionView)  # satisfies the runtime-checkable Protocol
    assert sv.room_name == "sales-1"
    assert sv.job_id == "j1"
    assert sv.job_metadata == '{"agent": "sales"}'  # raw; consumers parse it
    assert sv.room_metadata is None
    assert sv.session == "LIVE_SESSION"


def test_for_livekit_defaults_absent_fields_defensively() -> None:
    # A ctx missing room/job attributes must never raise (a missing name or id
    # can never turn a healthy session into a failed one).
    sv = for_livekit(SimpleNamespace())
    assert sv.room_name == ""
    assert sv.job_id == ""
    assert sv.job_metadata is None
    assert sv.room_metadata is None
    assert sv.session is None


@pytest.mark.asyncio
async def test_for_livekit_connect_delegates() -> None:
    ctx, connected = _livekit_ctx()
    sv = for_livekit(ctx)
    await sv.connect()
    assert connected["value"] is True


# ---------------------------------------------------------------------------
# Pre-connect room semantics. Routing runs before ctx.connect(), so the rtc
# Room name/metadata are still empty; the authoritative pre-connect values live
# on ctx.job.room (the dispatch assignment). The adapter must prefer those,
# mirroring the routing strategies exactly, so routing can read only the view.
# ---------------------------------------------------------------------------


def test_room_name_prefers_job_room_over_rtc_room() -> None:
    # rtc room name is empty pre-connect; the job room name is authoritative.
    ctx, _ = _livekit_ctx(room_name="", job_room_name="dental-follow-up")
    assert for_livekit(ctx).room_name == "dental-follow-up"


def test_room_name_falls_back_to_rtc_room_when_job_room_absent() -> None:
    ctx, _ = _livekit_ctx(room_name="sales-1")  # no job room
    assert for_livekit(ctx).room_name == "sales-1"


def test_room_name_is_empty_string_when_neither_is_a_string() -> None:
    # A missing rtc room name (None) and no job room coerce to "" (never raises,
    # and "" matches no agent prefix, so routing simply defers).
    ctx, _ = _livekit_ctx(room_name=None)
    assert for_livekit(ctx).room_name == ""


def test_room_metadata_prefers_job_room_when_present() -> None:
    ctx, _ = _livekit_ctx(room_meta=None, job_room_meta='{"agent": "dental"}')
    assert for_livekit(ctx).room_metadata == '{"agent": "dental"}'


def test_room_metadata_falls_back_to_rtc_room_when_job_room_absent() -> None:
    ctx, _ = _livekit_ctx(room_meta='{"agent": "sales"}')  # no job room
    assert for_livekit(ctx).room_metadata == '{"agent": "sales"}'


# ---------------------------------------------------------------------------
# Pipecat adapter. Pipecat's runner hands one RunnerArguments per connection;
# for_pipecat maps it onto the same neutral view: body carries the routing
# signal, session_id is the job id, and the room name comes from whichever
# transport-specific field is present. The adapter imports no pipecat type (it
# only reads attributes), so importing the module stays framework-free.
# ---------------------------------------------------------------------------


def _pipecat_args(**kwargs):
    # RunnerArguments is a per-connection attribute bag; a SimpleNamespace stands
    # in without importing pipecat, since the adapter only uses getattr.
    return SimpleNamespace(**kwargs)


def test_for_pipecat_exposes_the_neutral_surface() -> None:
    args = _pipecat_args(
        session_id="s1", body={"agent": "sales"}, room_url="https://x.daily.co/r"
    )
    sv = for_pipecat(args)
    assert isinstance(sv, SessionView)  # satisfies the runtime-checkable Protocol
    assert sv.room_name == "https://x.daily.co/r"
    assert sv.job_id == "s1"
    assert sv.job_metadata == {"agent": "sales"}  # raw body; consumers parse it
    assert sv.room_metadata is None
    assert sv.session is None


def test_for_pipecat_room_name_prefers_room_url_then_room_name_then_session() -> None:
    both = _pipecat_args(room_url="ru", room_name="rn", session_id="s")
    assert for_pipecat(both).room_name == "ru"  # room_url wins (Daily)
    no_url = _pipecat_args(room_name="rn", session_id="s")
    assert for_pipecat(no_url).room_name == "rn"  # room_name next (LiveKit)
    only_session = _pipecat_args(session_id="s")
    assert for_pipecat(only_session).room_name == "s"  # session_id last resort


def test_for_pipecat_defaults_absent_fields_defensively() -> None:
    # A RunnerArguments missing every mapped field must never raise.
    sv = for_pipecat(_pipecat_args())
    assert sv.room_name == ""
    assert sv.job_id == ""
    assert sv.job_metadata is None
    assert sv.room_metadata is None
    assert sv.session is None


def test_for_pipecat_surfaces_an_attached_session() -> None:
    # The serving glue may attach the live PipelineTask; the view surfaces it.
    sv = for_pipecat(_pipecat_args(session="TASK"))
    assert sv.session == "TASK"


@pytest.mark.asyncio
async def test_for_pipecat_connect_is_a_noop() -> None:
    # Pipecat connects inside its transport/runner, so the view's connect() does
    # nothing (and never raises).
    await for_pipecat(_pipecat_args()).connect()
