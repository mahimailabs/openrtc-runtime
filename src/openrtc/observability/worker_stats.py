"""Worker/system stats for the ``openrtc top`` header (CPU / MEM / SWAP / LOAD / NET).

The worker samples its host once per refresh via psutil and serves the result in
the introspection snapshot, so ``openrtc top`` can render the machine vitals above
the session table. psutil is an optional dependency (``openrtc[top]``); without it
the sampler reports :class:`SystemStats` with every field ``None`` and the header
shows ``n/a`` rather than failing.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["SystemStats", "WorkerStatsSampler"]

_UNSET: Any = object()


@dataclass(frozen=True, slots=True)
class SystemStats:
    """A single sample of host vitals; every field is ``None`` without psutil."""

    available: bool = False
    cpu_pct: float | None = None
    vcpus: int | None = None
    mem_used_bytes: int | None = None
    mem_total_bytes: int | None = None
    swap_used_bytes: int | None = None
    swap_total_bytes: int | None = None
    load1: float | None = None
    load5: float | None = None
    load15: float | None = None
    net_rate_bps: float | None = None


def _default_psutil() -> Any:
    try:
        import psutil
    except ModuleNotFoundError:
        return None
    return psutil


class WorkerStatsSampler:
    """Sample host vitals per refresh and keep a bounded CPU% history for the graph.

    ``psutil_module`` defaults to the real psutil (or ``None`` when it is not
    installed); tests inject a stand-in. Network throughput is a rate, so it needs
    two samples: the first returns ``None``.
    """

    __slots__ = ("_history", "_prev_net", "_prev_t", "_psutil", "_time")

    def __init__(
        self,
        *,
        psutil_module: Any = _UNSET,
        history_len: int = 60,
        time_source: Callable[[], float] = monotonic,
    ) -> None:
        self._psutil = _default_psutil() if psutil_module is _UNSET else psutil_module
        self._history: deque[float] = deque(maxlen=history_len)
        self._prev_net: int | None = None
        self._prev_t: float | None = None
        self._time = time_source

    @property
    def cpu_history(self) -> tuple[float, ...]:
        """The bounded rolling CPU% history feeding the header sparkline."""
        return tuple(self._history)

    def sample(self) -> SystemStats:
        """Read one sample of host vitals (``SystemStats`` all-``None`` without psutil)."""
        ps = self._psutil
        if ps is None:
            return SystemStats()

        cpu = float(ps.cpu_percent(interval=None))
        self._history.append(cpu)
        vm = ps.virtual_memory()
        sm = ps.swap_memory()
        try:
            load1, load5, load15 = ps.getloadavg()
        except (AttributeError, OSError):
            load1 = load5 = load15 = None

        net = ps.net_io_counters()
        total = int(net.bytes_sent) + int(net.bytes_recv)
        now = self._time()
        rate: float | None = None
        if self._prev_net is not None and self._prev_t is not None:
            elapsed = now - self._prev_t
            if elapsed > 0:
                rate = (total - self._prev_net) / elapsed
        self._prev_net = total
        self._prev_t = now

        return SystemStats(
            available=True,
            cpu_pct=cpu,
            vcpus=int(ps.cpu_count()),
            mem_used_bytes=int(vm.used),
            mem_total_bytes=int(vm.total),
            swap_used_bytes=int(sm.used),
            swap_total_bytes=int(sm.total),
            load1=load1,
            load5=load5,
            load15=load15,
            net_rate_bps=rate,
        )
