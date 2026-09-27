#!/usr/bin/env bash
# The Benchmark page's head-to-head: five workers x 2 runs, interleaved, 8 calls held 60 s.
# Appends to results/sweep.jsonl.
set -u
cd "$(dirname "$0")"
PY=${PY:-../../.venv/bin/python}
N=${N:-8} HOLD=${HOLD:-60}
for rep in 1 2; do
  ./run.sh vproc-$rep           $N $HOLD env BENCH_EXECUTOR=process $PY vanilla_agent.py
  ./run.sh vthread-$rep         $N $HOLD env BENCH_EXECUTOR=thread $PY vanilla_agent.py
  ./run.sh openrtc-$rep         $N $HOLD env OPENRTC_UVLOOP=0 $PY openrtc_agent.py
  ./run.sh openrtc-nointro-$rep $N $HOLD env OPENRTC_UVLOOP=0 BENCH_INTROSPECTION=0 $PY openrtc_agent.py
  ./run.sh openrtc-uvloop-$rep  $N $HOLD $PY openrtc_agent.py
done | tee -a results/sweep.jsonl
