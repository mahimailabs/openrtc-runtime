"""use_uvloop: install uvloop's policy, honour OPENRTC_UVLOOP=0, survive its absence."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator

import pytest

from openrtc.runtime.event_loop import use_uvloop


@pytest.fixture(autouse=True)
def _restore_policy() -> Iterator[None]:
    yield
    asyncio.set_event_loop_policy(None)


def test_installs_uvloop_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    uvloop = pytest.importorskip("uvloop")
    monkeypatch.delenv("OPENRTC_UVLOOP", raising=False)
    assert use_uvloop() is True
    assert isinstance(asyncio.get_event_loop_policy(), uvloop.EventLoopPolicy)


def test_env_opt_out_keeps_asyncio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENRTC_UVLOOP", "0")
    before = asyncio.get_event_loop_policy()
    assert use_uvloop() is False
    assert asyncio.get_event_loop_policy() is before


def test_missing_uvloop_keeps_asyncio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENRTC_UVLOOP", raising=False)
    monkeypatch.setitem(sys.modules, "uvloop", None)  # makes `import uvloop` raise
    before = asyncio.get_event_loop_policy()
    assert use_uvloop() is False
    assert asyncio.get_event_loop_policy() is before
