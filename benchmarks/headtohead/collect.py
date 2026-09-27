"""Turn one run's files in out/ into a JSON line: calls answered, core CPU, memory, warnings."""

import csv
import json
import os
import sys
from pathlib import Path

label = sys.argv[1]
rows = list(csv.DictReader(Path(f"out/{label}.csv").read_text().splitlines()))
idle, busy = rows[:4], rows[10:-3] or rows
load = json.loads(Path(f"out/{label}.load.json").read_text())
log = Path(f"out/{label}.worker.log").read_text()


def peak(rs: list[dict[str, str]], key: str) -> float:
    return max(float(r[key]) for r in rs)


def core_busy(path: str) -> tuple[int, int]:
    ticks = [
        list(map(int, line.split()[1:])) for line in Path(path).read_text().splitlines()
    ]
    return sum(sum(t) - t[3] - t[4] for t in ticks), sum(sum(t) for t in ticks)


(b0, t0), (b1, t1) = core_busy(f"out/{label}.stat0"), core_busy(f"out/{label}.stat1")
real, user, sys_ = map(float, Path(f"out/{label}.loadtime").read_text().split())
print(
    json.dumps(
        {
            "label": label,
            **load,
            "cores01_busy_pct_of_2": round(100 * (b1 - b0) / (t1 - t0) * 2),
            "rooms_still_occupied_30s_after": int(os.environ.get("STUCK") or 0),
            "loop_blocked_warnings": log.count("event loop blocked"),
            "vad_slower_than_realtime": log.count(
                "VAD inference is slower than realtime"
            ),
            "jobs_received": log.count("received job request"),
            "loadgen_cpu_pct": round(100 * (user + sys_) / real),
            "idle_pss_mb": peak(idle, "pss_mb"),
            "peak_pss_mb": peak(rows, "pss_mb"),
            "peak_rss_mb": peak(rows, "rss_mb"),
            "peak_procs": int(peak(rows, "nprocs")),
            "avg_cpu_pct_busy": round(
                sum(float(r["cpu_pct"]) for r in busy) / len(busy)
            ),
        }
    )
)
