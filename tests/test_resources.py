from __future__ import annotations

import sys
from pathlib import Path

import pytest
from livekit.agents import Agent

import openrtc.observability.metrics as resources_module
from openrtc.core.pool import AgentPool
from openrtc.observability.metrics import (
    agent_disk_footprints,
    file_size_bytes,
    format_byte_size,
    get_process_resident_set_info,
    process_resident_set_bytes,
)
from openrtc.observability.snapshot import ProcessResidentSetInfo


class TinyAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="hi")


def test_format_byte_size() -> None:
    assert format_byte_size(0) == "0 B"
    assert format_byte_size(512) == "512 B"
    assert format_byte_size(1024) == "1.0 KiB"
    assert format_byte_size(1024 * 1024) == "1.0 MiB"


def test_file_size_bytes_counts_bytes(tmp_path: Path) -> None:
    path = tmp_path / "x.txt"
    path.write_bytes(b"abc")
    assert file_size_bytes(path) == 3


def test_agent_disk_footprints_skips_unknown_paths() -> None:
    pool = AgentPool()
    pool.add("a", TinyAgent)
    cfg = pool.get("a")
    assert agent_disk_footprints([cfg]) == []


def test_process_resident_set_info_smoke() -> None:
    info = get_process_resident_set_info()
    assert info.metric in (
        "linux_vm_rss",
        "darwin_ru_max_rss",
        "unavailable",
    )
    assert len(info.description) > 5
    b = process_resident_set_bytes()
    assert b is None or isinstance(b, int)
    # Equality of info.bytes_value vs b is not asserted: each call re-reads
    # /proc or rusage, so values can differ between consecutive samples.


def test_process_resident_set_bytes_delegates_to_get_process_resident_set_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = ProcessResidentSetInfo(
        bytes_value=12345,
        metric="linux_vm_rss",
        description="stub",
    )
    monkeypatch.setattr(
        resources_module,
        "get_process_resident_set_info",
        lambda: fake,
    )
    assert process_resident_set_bytes() == 12345


def test_resident_set_descriptions_align_with_platform() -> None:
    """Guardrail: Linux vs macOS wording must stay distinct (see resources docs)."""
    info = get_process_resident_set_info()
    desc = info.description.lower()
    if sys.platform.startswith("linux"):
        assert info.metric == "linux_vm_rss"
        assert "vmrss" in desc or "/proc" in desc
    elif sys.platform == "darwin":
        assert info.metric == "darwin_ru_max_rss"
        assert "ru_maxrss" in desc or "getrusage" in desc
        assert "peak" in desc or "max" in desc or "not instantaneous" in desc
    else:
        assert info.metric == "unavailable"


def test_agent_disk_footprints_includes_registered_paths(tmp_path: Path) -> None:
    module = tmp_path / "mod.py"
    module.write_text("# test\n", encoding="utf-8")
    pool = AgentPool()
    pool.add("x", TinyAgent, source_path=module)
    fps = agent_disk_footprints([pool.get("x")])
    assert len(fps) == 1
    assert fps[0].name == "x"
    assert fps[0].path == module.resolve()
    assert fps[0].size_bytes == module.stat().st_size


def test_format_byte_size_clamps_negative_input_to_zero() -> None:
    """Negative byte counts are surfaced as ``0 B`` rather than raising."""
    assert format_byte_size(-100) == "0 B"


def test_file_size_bytes_returns_zero_when_path_missing(tmp_path: Path) -> None:
    """A missing file produces 0 instead of raising OSError."""
    assert file_size_bytes(tmp_path / "missing.txt") == 0


def test_estimate_savings_short_circuits_when_agent_count_zero() -> None:
    from openrtc.observability.metrics import estimate_shared_worker_savings

    estimate = estimate_shared_worker_savings(agent_count=0, shared_worker_bytes=100)

    assert estimate.estimated_separate_workers_bytes is None
    assert estimate.estimated_saved_bytes is None


def test_estimate_savings_short_circuits_when_shared_worker_bytes_none() -> None:
    from openrtc.observability.metrics import estimate_shared_worker_savings

    estimate = estimate_shared_worker_savings(agent_count=3, shared_worker_bytes=None)

    assert estimate.estimated_separate_workers_bytes is None
    assert estimate.estimated_saved_bytes is None


def test_get_process_resident_set_info_for_linux_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Linux branch reads VmRSS via the ``_linux_rss_bytes`` helper."""
    from openrtc.observability import metrics as metrics_module

    monkeypatch.setattr(metrics_module.sys, "platform", "linux")
    monkeypatch.setattr(metrics_module, "_linux_rss_bytes", lambda: 4096)

    info = metrics_module.get_process_resident_set_info()

    assert info.metric == "linux_vm_rss"
    assert info.bytes_value == 4096


def test_get_process_resident_set_info_for_unknown_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-Linux non-Darwin platforms get the unavailable sentinel."""
    from openrtc.observability import metrics as metrics_module

    monkeypatch.setattr(metrics_module.sys, "platform", "win32")

    info = metrics_module.get_process_resident_set_info()

    assert info.metric == "unavailable"
    assert info.bytes_value is None


def test_linux_rss_bytes_parses_proc_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openrtc.observability import metrics as metrics_module

    fake_status = (
        "Name:\tagent\nVmPeak:\t  131072 kB\nVmRSS:\t  2048 kB\nVmHWM:\t  4096 kB\n"
    )

    def _fake_read_text(self: Path, *_args: object, **_kwargs: object) -> str:
        if str(self) == "/proc/self/status":
            return fake_status
        raise AssertionError(f"unexpected read_text on {self!s}")

    monkeypatch.setattr(metrics_module.Path, "read_text", _fake_read_text)

    assert metrics_module._linux_rss_bytes() == 2048 * 1024


def test_linux_rss_bytes_returns_none_when_proc_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openrtc.observability import metrics as metrics_module

    def _raise(_self: Path, *_args: object, **_kwargs: object) -> str:
        raise OSError("no procfs")

    monkeypatch.setattr(metrics_module.Path, "read_text", _raise)

    assert metrics_module._linux_rss_bytes() is None


def test_linux_rss_bytes_returns_none_when_vmrss_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openrtc.observability import metrics as metrics_module

    def _no_vmrss(_self: Path, *_args: object, **_kwargs: object) -> str:
        return "Name:\tagent\nVmPeak:\t  131072 kB\n"

    monkeypatch.setattr(metrics_module.Path, "read_text", _no_vmrss)

    assert metrics_module._linux_rss_bytes() is None


def test_linux_rss_bytes_continues_loop_when_vmrss_line_has_no_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Branch: a ``VmRSS:`` line without a value falls through to the next line."""
    from openrtc.observability import metrics as metrics_module

    def _malformed_then_good(_self: Path, *_args: object, **_kwargs: object) -> str:
        return "VmRSS:\nName:\tagent\n"

    monkeypatch.setattr(metrics_module.Path, "read_text", _malformed_then_good)

    assert metrics_module._linux_rss_bytes() is None


def test_macos_rss_bytes_returns_none_when_getrusage_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``OSError`` from ``getrusage`` surfaces as ``None``."""
    import resource

    from openrtc.observability import metrics as metrics_module

    def _raise(_who: int) -> object:
        raise OSError("no rusage")

    monkeypatch.setattr(resource, "getrusage", _raise)

    assert metrics_module._macos_rss_bytes() is None


def test_macos_rss_bytes_returns_none_when_value_non_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zero ``ru_maxrss`` (e.g. very early in process lifetime) maps to ``None``."""
    import resource
    from types import SimpleNamespace

    from openrtc.observability import metrics as metrics_module

    monkeypatch.setattr(
        resource, "getrusage", lambda _who: SimpleNamespace(ru_maxrss=0)
    )

    assert metrics_module._macos_rss_bytes() is None


def test_runtime_metrics_store_record_session_finished_keeps_positive_count() -> None:
    """If two sessions are running and one finishes, the agent's count goes 2 -> 1."""
    from openrtc.observability.metrics import RuntimeMetricsStore

    store = RuntimeMetricsStore()
    store.record_session_started("a")
    store.record_session_started("a")

    store.record_session_finished("a")

    assert store.sessions_by_agent == {"a": 1}


@pytest.mark.parametrize(
    ("field_name", "bad_value", "match"),
    [
        ("started_at", "not-a-number", "started_at"),
        ("total_sessions_started", "not-an-int", "total_sessions_started"),
        ("total_session_failures", 1.5, "total_session_failures"),
        ("sessions_by_agent", ["not", "a", "mapping"], "sessions_by_agent"),
        ("_stream_events", "not-a-list", "_stream_events"),
        ("_metrics_stream_overflow_since_drain", "nope", "overflow"),
    ],
)
def test_runtime_metrics_store_setstate_rejects_malformed_state(
    field_name: str, bad_value: object, match: str
) -> None:
    """Each typed restore field rejects the wrong type with a clear TypeError."""
    from openrtc.observability.metrics import RuntimeMetricsStore

    state: dict[str, object] = {
        "started_at": 1.0,
        "total_sessions_started": 0,
        "total_session_failures": 0,
        "last_routed_agent": None,
        "last_error": None,
        "sessions_by_agent": {},
        "_stream_events": [],
        "_metrics_stream_overflow_since_drain": 0,
    }
    state[field_name] = bad_value
    store = RuntimeMetricsStore()

    with pytest.raises(TypeError, match=match):
        store.__setstate__(state)
