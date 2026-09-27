"""BENCH_FFI_STATS=1: count livekit FFI events and how many queue deliveries each one causes.

livekit.rtc's FfiQueue.put runs on a Rust tokio thread under the GIL and offers every event to
every subscriber in the process. This wraps it to log, every 10 s, events/s, subscribers, filter
calls/s and call_soon_threadsafe deliveries/s, so one process with N calls can be compared with
N processes with one call each.
"""

import logging
import threading
import time
from collections import Counter

from livekit.rtc._ffi_client import FfiQueue

log = logging.getLogger("bench.ffi")
_n = {"events": 0, "offers": 0, "delivered": 0, "subs": 0}
_by_type: Counter[str] = Counter()
_orig_put = FfiQueue.put


def _put(self: FfiQueue, item: object) -> None:  # type: ignore[type-arg]
    subs = self._subscribers
    _n["events"] += 1
    _n["offers"] += len(subs)
    _n["subs"] = max(_n["subs"], len(subs))
    got = sum(1 for _, _, f in subs if f is None or f(item))
    _n["delivered"] += got
    which = item.WhichOneof("message")
    if which == "room_event":
        which += "." + str(item.room_event.WhichOneof("message"))
    _by_type[which] += got
    _orig_put(self, item)


def _report() -> None:
    while True:
        time.sleep(10)
        snap = dict(_n)
        for k in ("events", "offers", "delivered"):
            _n[k] = 0
        _n["subs"] = 0
        top = ", ".join(f"{k}={v / 10:.0f}" for k, v in _by_type.most_common(6))
        _by_type.clear()
        log.warning(
            "ffi-stats events/s=%.0f offers/s=%.0f delivered/s=%.0f max_subscribers=%d"
            " delivered/s by type: %s",
            snap["events"] / 10,
            snap["offers"] / 10,
            snap["delivered"] / 10,
            snap["subs"],
            top,
        )


def install() -> None:
    FfiQueue.put = _put  # type: ignore[method-assign]
    threading.Thread(target=_report, daemon=True).start()
