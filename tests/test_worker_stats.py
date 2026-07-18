"""WorkerStatsSampler: psutil-backed worker/system stats for the openrtc top header."""

from __future__ import annotations

import builtins
from typing import Any

import pytest

from openrtc.observability.worker_stats import SystemStats, WorkerStatsSampler


class _Mem:
    def __init__(self, used: int, total: int) -> None:
        self.used = used
        self.total = total


class _Net:
    def __init__(self, sent: int, recv: int) -> None:
        self.bytes_sent = sent
        self.bytes_recv = recv


class _FakePsutil:
    """Minimal psutil stand-in so the sampler is tested without real hardware."""

    def __init__(
        self, *, cpu: float = 17.6, net: tuple[int, int] = (1000, 2000)
    ) -> None:
        self._cpu = cpu
        self._net = net
        self.load_raises = False

    def cpu_percent(self, interval: Any = None) -> float:
        return self._cpu

    def cpu_count(self) -> int:
        return 16

    def virtual_memory(self) -> _Mem:
        return _Mem(31_200_000_000, 68_700_000_000)

    def swap_memory(self) -> _Mem:
        return _Mem(0, 8_000_000_000)

    def net_io_counters(self) -> _Net:
        return _Net(*self._net)

    def getloadavg(self) -> tuple[float, float, float]:
        if self.load_raises:
            raise OSError("load average not available")
        return (0.74, 0.68, 0.59)


def test_sample_populates_system_stats_from_psutil() -> None:
    sampler = WorkerStatsSampler(psutil_module=_FakePsutil())
    stats = sampler.sample()
    assert isinstance(stats, SystemStats)
    assert stats.available is True
    assert stats.cpu_pct == 17.6
    assert stats.vcpus == 16
    assert stats.mem_used_bytes == 31_200_000_000
    assert stats.mem_total_bytes == 68_700_000_000
    assert stats.swap_total_bytes == 8_000_000_000
    assert (stats.load1, stats.load5, stats.load15) == (0.74, 0.68, 0.59)


def test_cpu_history_accumulates_and_is_bounded() -> None:
    sampler = WorkerStatsSampler(psutil_module=_FakePsutil(cpu=42.0), history_len=3)
    for _ in range(5):
        sampler.sample()
    assert sampler.cpu_history == (42.0, 42.0, 42.0)  # bounded to history_len


def test_net_rate_is_none_first_then_delta_over_time() -> None:
    clock = {"t": 100.0}
    fake = _FakePsutil(net=(0, 0))
    sampler = WorkerStatsSampler(psutil_module=fake, time_source=lambda: clock["t"])
    first = sampler.sample()
    assert first.net_rate_bps is None  # no prior sample to diff against
    fake._net = (500, 1500)  # +2000 bytes total
    clock["t"] = 102.0  # 2 seconds later
    second = sampler.sample()
    assert second.net_rate_bps == 1000.0  # 2000 bytes / 2s


def test_missing_load_average_degrades_to_none() -> None:
    fake = _FakePsutil()
    fake.load_raises = True
    stats = WorkerStatsSampler(psutil_module=fake).sample()
    assert (stats.load1, stats.load5, stats.load15) == (None, None, None)
    assert stats.cpu_pct == 17.6  # the rest still populates


def test_without_psutil_stats_are_unavailable() -> None:
    sampler = WorkerStatsSampler(psutil_module=None)
    stats = sampler.sample()
    assert stats.available is False
    assert stats.cpu_pct is None
    assert sampler.cpu_history == ()  # nothing sampled


def test_net_rate_none_when_no_time_elapsed() -> None:
    fake = _FakePsutil(net=(0, 0))
    sampler = WorkerStatsSampler(psutil_module=fake, time_source=lambda: 100.0)
    sampler.sample()
    fake._net = (500, 1500)
    second = sampler.sample()
    assert second.net_rate_bps is None  # elapsed == 0, so no rate is computed


def test_default_psutil_returns_the_installed_module() -> None:
    import psutil

    from openrtc.observability.worker_stats import _default_psutil

    assert _default_psutil() is psutil


def test_default_psutil_returns_none_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openrtc.observability import worker_stats

    real_import = builtins.__import__

    def _without_psutil(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "psutil":
            raise ModuleNotFoundError("No module named 'psutil'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _without_psutil)
    assert worker_stats._default_psutil() is None
