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
    *, room_name: str = "sales-1", job_id: str = "j1", job_meta=None, room_meta=None
):
    connected = {"value": False}

    async def _connect() -> None:
        connected["value"] = True

    ctx = SimpleNamespace(
        room=SimpleNamespace(name=room_name, metadata=room_meta),
        job=SimpleNamespace(id=job_id, metadata=job_meta),
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
