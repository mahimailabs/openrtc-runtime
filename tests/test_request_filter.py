"""Job-request filter: a worker accepts only rooms it should handle.

These tests pin the ownership rule (which rooms map to a registered agent) and
the accept/reject wiring against a fake ``JobRequest``. They are the guard for
the shared-LiveKit scenario: two openrtc workers on one project, each of which
must join only its own rooms instead of default-falling-back onto every room.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from openrtc.routing.request_filter import (
    _build_registered_rooms_filter,
    _owns_room,
)


@dataclass
class _FakeRoom:
    name: str = ""
    metadata: Any = None


@dataclass
class _FakeJob:
    metadata: Any = None
    room: _FakeRoom = field(default_factory=_FakeRoom)


class _FakeRequest:
    """Minimal ``JobRequest`` stand-in that records accept/reject."""

    def __init__(
        self,
        *,
        room_name: str = "",
        job_metadata: Any = None,
        room_metadata: Any = None,
    ) -> None:
        room = _FakeRoom(name=room_name, metadata=room_metadata)
        self.job = _FakeJob(metadata=job_metadata, room=room)
        self.room = room
        self.accepted = False
        self.rejected = False

    async def accept(self, **_kwargs: Any) -> None:
        self.accepted = True

    async def reject(self, **_kwargs: Any) -> None:
        self.rejected = True


_AGENTS = {"alpha": object(), "beta": object()}


# --- ownership rule ---------------------------------------------------------


def test_owns_room_true_for_registered_prefix() -> None:
    assert _owns_room(
        _AGENTS, room_name="alpha-call-1", job_metadata=None, room_metadata=None
    )


def test_owns_room_true_for_job_metadata_naming_registered_agent() -> None:
    assert _owns_room(
        _AGENTS,
        room_name="t_9f2c",
        job_metadata={"agent": "beta"},
        room_metadata=None,
    )


def test_owns_room_true_for_room_metadata_naming_registered_agent() -> None:
    assert _owns_room(
        _AGENTS,
        room_name="t_9f2c",
        job_metadata=None,
        room_metadata='{"agent": "alpha"}',
    )


def test_owns_room_false_for_foreign_prefix() -> None:
    assert not _owns_room(
        _AGENTS, room_name="t_9f2c", job_metadata=None, room_metadata=None
    )


def test_owns_room_false_for_metadata_naming_unregistered_agent() -> None:
    # Metadata that names another worker's agent must be treated as "not mine",
    # never raised (the routing resolver raises; the filter must not).
    assert not _owns_room(
        _AGENTS,
        room_name="t_9f2c",
        job_metadata={"agent": "gamma"},
        room_metadata=None,
    )


def test_owns_room_false_for_missing_room_name() -> None:
    assert not _owns_room(
        _AGENTS, room_name=None, job_metadata=None, room_metadata=None
    )


def test_owns_room_false_for_empty_agents() -> None:
    assert not _owns_room(
        {}, room_name="alpha-call-1", job_metadata=None, room_metadata=None
    )


# --- accept/reject wiring ---------------------------------------------------


def test_filter_accepts_owned_room() -> None:
    request_fnc = _build_registered_rooms_filter(_AGENTS)
    req = _FakeRequest(room_name="alpha-call-1")

    asyncio.run(request_fnc(req))

    assert req.accepted is True
    assert req.rejected is False


def test_filter_rejects_foreign_room() -> None:
    request_fnc = _build_registered_rooms_filter(_AGENTS)
    req = _FakeRequest(room_name="t_9f2c")

    asyncio.run(request_fnc(req))

    assert req.rejected is True
    assert req.accepted is False


def test_filter_accepts_room_routed_by_metadata() -> None:
    request_fnc = _build_registered_rooms_filter(_AGENTS)
    req = _FakeRequest(room_name="t_9f2c", room_metadata='{"agent": "beta"}')

    asyncio.run(request_fnc(req))

    assert req.accepted is True


def test_filter_reads_agents_dict_live() -> None:
    # The filter closes over the pool's live dict, so agents registered after
    # the filter is built are still recognized (registration happens after the
    # pool is constructed).
    agents: dict[str, object] = {}
    request_fnc = _build_registered_rooms_filter(agents)
    req_before = _FakeRequest(room_name="late-call-1")
    asyncio.run(request_fnc(req_before))
    assert req_before.rejected is True

    agents["late"] = object()
    req_after = _FakeRequest(room_name="late-call-1")
    asyncio.run(request_fnc(req_after))
    assert req_after.accepted is True
