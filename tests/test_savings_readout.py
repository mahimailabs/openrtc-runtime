"""Day-one savings readout: the format_prewarm_savings line and its prewarm emit.

The readout makes the fleet-collapse idle-baseline win visible on first run. It
claims only idle-baseline memory saved (never per-session density or a speed
multiple) and stays graceful when RSS is unavailable.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from openrtc.execution import prewarm as prewarm_module
from openrtc.execution.prewarm import _prewarm_worker
from openrtc.observability.savings import format_prewarm_savings

_MB = 1024 * 1024


def test_savings_line_for_multiple_agents() -> None:
    line = format_prewarm_savings(agent_count=3, shared_worker_bytes=400 * _MB)
    assert "3 agents" in line
    assert "400 MB" in line  # shared baseline
    assert "1200 MB" in line  # 3 separate workers
    assert "800 MB" in line  # idle baseline saved: (3 - 1) * 400
    assert "assumes" in line.lower()
    assert "saves" in line.lower()


def test_neutral_line_for_single_agent() -> None:
    line = format_prewarm_savings(agent_count=1, shared_worker_bytes=400 * _MB)
    assert "1 agent" in line
    assert "saves" not in line.lower()  # no boast for a single agent
    assert "amortize" in line.lower()


def test_graceful_when_rss_unavailable() -> None:
    line = format_prewarm_savings(agent_count=3, shared_worker_bytes=None)
    assert "3 agents" in line
    assert "unavailable" in line.lower()
    assert "MB" not in line  # no fabricated number


def test_prewarm_emits_one_savings_line(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _FakeVAD:
        @staticmethod
        def load() -> str:
            return "vad"

    class _FakeSilero:
        VAD = _FakeVAD

    class _FakeTurnDetector:
        pass

    monkeypatch.setattr(
        prewarm_module,
        "_load_shared_runtime_dependencies",
        lambda: (_FakeSilero, _FakeTurnDetector),
    )
    runtime_state = SimpleNamespace(agents={"a": object(), "b": object()})
    proc = SimpleNamespace(userdata={}, inference_executor=None)

    with caplog.at_level(logging.INFO, logger="openrtc.execution.prewarm"):
        _prewarm_worker(runtime_state, proc)  # type: ignore[arg-type]

    records = [r for r in caplog.records if r.name == "openrtc.execution.prewarm"]
    assert len(records) == 1
    message = records[0].getMessage()
    assert message.startswith("OpenRTC:")
    assert "2 agents" in message
    assert "saves" in message.lower()  # RSS is available in-process, so a number
