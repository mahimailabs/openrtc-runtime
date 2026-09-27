# Head-to-head: OpenRTC against livekit-agents

The harness behind [docs.openrtc.tech/benchmark](https://docs.openrtc.tech/benchmark/). It runs the
same agent five ways on two pinned cores, plays real speech into real rooms, and measures CPU and
memory. `results/` holds the raw numbers the Benchmark page quotes; `python3 summarize.py` prints
them as the page's tables.

## What it runs

| Worker | Command |
| --- | --- |
| livekit-agents, a process per call | `BENCH_EXECUTOR=process python vanilla_agent.py start` |
| livekit-agents, one process (thread mode) | `BENCH_EXECUTOR=thread python vanilla_agent.py start` |
| OpenRTC, asyncio loop | `OPENRTC_UVLOOP=0 python openrtc_agent.py start` |
| OpenRTC, asyncio loop, introspection off | `OPENRTC_UVLOOP=0 BENCH_INTROSPECTION=0 python openrtc_agent.py start` |
| OpenRTC, uvloop (the default) | `python openrtc_agent.py start` |

Every call runs the full livekit pipeline: WebRTC audio both ways through a local livekit-server,
the real Silero VAD and turn detector, and stand-in STT, LLM and TTS (`fakes.py`) that sleep for
realistic latency and emit real audio, so provider variance does not enter the numbers. Every
worker admits every call (load is `active / 200`), so only the execution model differs.

## Needs

- Linux with at least 4 cores and `taskset`: the worker gets cores 0-1; the load generator and
  livekit-server get cores 2-3.
- The dev environment (`uv sync --group dev` at the repo root). `threads.sh` also needs py-spy:
  `uv pip install py-spy`.

## Run

```bash
./fetch.sh      # livekit-server 1.13.7 and the speech clip, into bin/ and .
./server.sh     # local dev livekit-server (keys devkey / secret) on cores 2-3
./sweep.sh      # 5 workers x 2 runs, 8 calls held 60 s: about 25 minutes -> results/sweep.jsonl
./threads.sh    # CPU per thread, 40 s mid-call, for three workers -> results/*.threads.json
python3 summarize.py
```

One run on its own: `./run.sh <label> <calls> <hold seconds> <worker command...>` prints one JSON
line. `N=16 ./sweep.sh` changes the call count.

## How each number is measured

| Number | How |
| --- | --- |
| CPU | busy ticks of cores 0-1 from `/proc/stat`, over the load window (`cores01_busy_pct_of_2`) |
| Memory | PSS of the worker's process tree, sampled every second (`sampler.py`). RSS double counts the pages forked processes share. Per call is peak minus idle, over the calls. |
| Answered | the caller heard non-silent audio from the agent (`loadgen.py`) |
| Per-thread CPU | `utime + stime` of every thread in `/proc/<pid>/task`, named with `py-spy dump` (`threadcpu.py`) |

## Results in `results/`

- `sweep.jsonl`: the 2026-09-27 sweep (livekit-agents 1.8.3, Python 3.11, a Linux cloud
  container). Its uvloop runs installed uvloop through a wrapper before `AgentPool(enable_uvloop=...)`
  existed; the policy and the event loop are the same.
- `thr-*.threads.json`: the per-thread runs quoted on the page.

A single run is noisy (the two uvloop runs spread 10 points), so compare pairs, and rerun on your
own hardware before quoting a number.
