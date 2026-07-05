"""Tenant context propagation: contextvar + public accessor + resolution (MAH-101)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from openrtc.context import current_tenant_id
from openrtc.observability.base_observer import _build_session_info
from openrtc.observability.session_context import (
    reset_tenant_id,
    set_tenant_id,
)
from openrtc.utils.validation import require_tenant_id

# --- validation -------------------------------------------------------------


def test_require_tenant_id_accepts_alnum_dashes_underscores() -> None:
    assert require_tenant_id("acme") == "acme"
    assert require_tenant_id("acme_corp-eu-1") == "acme_corp-eu-1"
    assert require_tenant_id("  trimmed  ") == "trimmed"
    assert require_tenant_id("a" * 128) == "a" * 128


def test_require_tenant_id_rejects_empty() -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        require_tenant_id("   ")


def test_require_tenant_id_rejects_bad_chars_and_length() -> None:
    with pytest.raises(ValueError, match="ASCII letters"):
        require_tenant_id("has space")
    with pytest.raises(ValueError, match="ASCII letters"):
        require_tenant_id("a" * 129)


# --- contextvar + public accessor ------------------------------------------


def test_public_import_reads_the_contextvar() -> None:
    assert current_tenant_id() is None
    token = set_tenant_id("acme")
    try:
        assert current_tenant_id() == "acme"
    finally:
        reset_tenant_id(token)
    assert current_tenant_id() is None


def test_tenant_propagates_to_nested_tasks() -> None:
    seen: list[str | None] = []

    async def _child() -> None:
        seen.append(current_tenant_id())

    async def _run() -> None:
        token = set_tenant_id("globex")
        try:
            await asyncio.create_task(_child())
        finally:
            reset_tenant_id(token)

    asyncio.run(_run())
    assert seen == ["globex"]


# --- SessionInfo tenant resolution -----------------------------------------


def _ctx(job_metadata: Any = None) -> Any:
    return SimpleNamespace(
        job=SimpleNamespace(metadata=job_metadata, id="j1", room=None),
        room=SimpleNamespace(metadata=None, name="r"),
    )


def test_session_info_resolves_tenant_from_metadata() -> None:
    info = _build_session_info("sales", _ctx(job_metadata='{"tenant": "acme"}'))
    assert info.tenant == "acme"


def test_session_info_defaults_tenant_when_absent() -> None:
    info = _build_session_info("sales", _ctx(job_metadata='{"agent": "sales"}'))
    assert info.tenant == "default"


def test_session_info_rejects_malformed_tenant() -> None:
    with pytest.raises(ValueError, match="ASCII letters"):
        _build_session_info("sales", _ctx(job_metadata='{"tenant": "bad tenant"}'))


# --- run_session wiring -----------------------------------------------------


@pytest.mark.asyncio
async def test_run_session_binds_tenant_and_sets_session_attr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tenant is live in the contextvar during the session, on session.tenant_id,
    and reset afterward (MAH-101)."""
    from openrtc.core import wiring

    config = SimpleNamespace(
        name="a",
        stt="s",
        llm="l",
        tts="t",
        session_kwargs={},
        greeting=None,
        agent_cls=lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        wiring, "_resolve_agent_config", lambda agents, ctx, *, router=None: config
    )
    monkeypatch.setattr(wiring, "_build_session_kwargs", lambda kw, proc, ie=None: {})

    seen_ctxvar: list[str | None] = []
    seen_attr: list[str | None] = []

    class _FakeSession:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def start(self, **kwargs: object) -> None:
            seen_ctxvar.append(current_tenant_id())
            seen_attr.append(getattr(self, "tenant_id", None))

    monkeypatch.setattr(wiring, "AgentSession", _FakeSession)

    async def _connect() -> None:
        pass

    ctx = SimpleNamespace(
        proc=SimpleNamespace(
            userdata={"vad": "VAD", "turn_detection_factory": object()}
        ),
        room=SimpleNamespace(name="a-1", metadata=None),
        job=SimpleNamespace(id="j", metadata='{"tenant": "acme"}'),
        connect=_connect,
        inference_executor=None,
    )
    state = wiring._PoolRuntimeState(agents={"a": config})

    assert current_tenant_id() is None
    await wiring.run_session(state, ctx)

    assert seen_ctxvar == ["acme"]  # live during the session
    assert seen_attr == ["acme"]  # set on session.tenant_id before start
    assert current_tenant_id() is None  # reset in finally
