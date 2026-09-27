"""CPU seconds per OS thread of a process tree over a window, named via py-spy dump.

usage: threadcpu.py <root pid> <window s> <py-spy path> <out.json>
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

root = int(sys.argv[1])
window = float(sys.argv[2])
spy = sys.argv[3]
HZ = os.sysconf("SC_CLK_TCK")


def tree(pid):
    out = [pid]
    for tid in os.listdir(f"/proc/{pid}/task"):
        try:
            kids = Path(f"/proc/{pid}/task/{tid}/children").read_text().split()
        except OSError:
            continue
        for c in kids:
            out += tree(int(c))
    return out


def snap():
    d = {}
    for pid in tree(root):
        for tid in os.listdir(f"/proc/{pid}/task"):
            try:
                s = Path(f"/proc/{pid}/task/{tid}/stat").read_text()
                comm = s[s.index("(") + 1 : s.rindex(")")]
                f = s[s.rindex(")") + 2 :].split()
                d[(pid, int(tid))] = (comm, (int(f[11]) + int(f[12])) / HZ)
            except OSError:
                pass
    return d


names = {}
for pid in tree(root):
    out = subprocess.run(
        [spy, "dump", "--pid", str(pid)], capture_output=True, text=True
    ).stdout
    for m in re.finditer(r'Thread (\d+) \(\w+\)(?:: "([^"]+)")?', out):
        names[int(m.group(1))] = m.group(2) or "?"
a = snap()
time.sleep(window)
b = snap()
rows = []
for k, (comm, t1) in b.items():
    t0 = a.get(k, (comm, 0.0))[1]
    pid, tid = k
    name = names.get(tid) or ("MainThread" if tid == pid else comm)
    rows.append(
        {
            "pid": pid,
            "tid": tid,
            "name": re.sub(r"_\d+$", "", name),
            "comm": comm,
            "cpu_s": round(t1 - t0, 2),
        }
    )
Path(sys.argv[4]).write_text(json.dumps(rows))
