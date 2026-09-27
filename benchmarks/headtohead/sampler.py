"""Sample a process tree every second: summed PSS/USS/RSS (MB), CPU% and process count.
PSS splits shared (copy-on-write) pages fairly between processes, so it is the honest
total for a fork-based worker; RSS double counts them."""

import sys
import time

import psutil

root = psutil.Process(int(sys.argv[1]))
with open(sys.argv[2], "w") as out:
    out.write("t,nprocs,pss_mb,uss_mb,rss_mb,cpu_pct\n")
    cache: dict[int, psutil.Process] = {}
    t0 = time.time()
    while root.is_running():
        try:
            procs = [root, *root.children(recursive=True)]
        except psutil.NoSuchProcess:
            break
        pss = uss = rss = cpu = 0.0
        for p in procs:
            p = cache.setdefault(p.pid, p)
            try:
                m = p.memory_full_info()
                pss, uss, rss = pss + m.pss, uss + m.uss, rss + m.rss
                cpu += p.cpu_percent()
            except psutil.Error:
                pass
        out.write(
            f"{time.time() - t0:.1f},{len(procs)},{pss / 2**20:.0f},{uss / 2**20:.0f},{rss / 2**20:.0f},{cpu:.0f}\n"
        )
        out.flush()
        time.sleep(1)
