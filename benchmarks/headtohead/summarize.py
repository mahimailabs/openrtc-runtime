"""Print the Benchmark page's tables from results/: the sweep and the per-thread CPU."""

import collections
import json
import os
import re
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")


def sweep() -> None:
    path = os.path.join(RESULTS, "sweep.jsonl")
    if not os.path.exists(path):
        return
    groups: dict[str, list[dict[str, float]]] = collections.defaultdict(list)
    for line in Path(path).read_text().splitlines():
        if line.startswith("{"):
            row = json.loads(line)
            groups[re.sub(r"-\d+$", "", row["label"])].append(row)
    print(f"{'worker':18} {'cpu % of 2 cores':>18} {'MB per call':>12} {'answered':>9}")
    for name, rows in groups.items():
        cpu = " / ".join(str(r["cores01_busy_pct_of_2"]) for r in rows)
        per_call = round(
            sum((r["peak_pss_mb"] - r["idle_pss_mb"]) / r["calls"] for r in rows)
            / len(rows)
        )
        spoke = " / ".join(f"{r.get('agent_spoke')}/{r['calls']}" for r in rows)
        print(f"{name:18} {cpu:>18} {per_call:>12} {spoke:>9}")


def threads() -> None:
    for label in ("thr-vproc", "thr-openrtc", "thr-uvloop"):
        path = os.path.join(RESULTS, f"{label}.threads.json")
        if not os.path.exists(path):
            continue
        rows = json.loads(Path(path).read_text())
        by_name: collections.Counter[str] = collections.Counter()
        for r in rows:
            by_name[r["name"] if r["name"] != "?" else r["comm"]] += r["cpu_s"]
        total = sum(by_name.values())
        print(f"\n{label}: {total:.1f} CPU-s over 40 s")
        for name, secs in by_name.most_common(8):
            print(f"  {secs:6.2f} s  {name}")


sweep()
threads()
