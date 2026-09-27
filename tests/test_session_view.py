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

from openrtc.core.session_view import SessionView, for_livekit


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
