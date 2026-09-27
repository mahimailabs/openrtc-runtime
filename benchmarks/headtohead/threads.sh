#!/usr/bin/env bash
# CPU seconds per thread over 40 s mid-call, for three workers. Writes results/<label>.threads.json.
# Needs py-spy (uv pip install py-spy) to name the threads.
set -u
cd "$(dirname "$0")"
PY=${PY:-../../.venv/bin/python}
SPY=${SPY:-../../.venv/bin/py-spy}
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export LIVEKIT_URL=ws://127.0.0.1:7880 LIVEKIT_API_KEY=devkey LIVEKIT_API_SECRET=secret PYTHONPATH=$PWD
mkdir -p out
one() {
  local label=$1; shift
  taskset -c 0,1 "$@" start > "out/$label.worker.log" 2>&1 &
  local wpid=$!
  for _ in $(seq 120); do grep -q "registered worker" "out/$label.worker.log" && break; sleep 1; done
  sleep 15
  taskset -c 2,3 $PY loadgen.py 8 70 "$label" > "out/$label.load.json" 2>/dev/null &
  local lpid=$!
  sleep 15
  taskset -c 2,3 $PY threadcpu.py $wpid 40 "$SPY" "results/$label.threads.json"
  wait $lpid
  kill -INT $wpid; sleep 5; kill -9 $wpid 2>/dev/null
}
one thr-vproc   env BENCH_EXECUTOR=process $PY vanilla_agent.py
one thr-openrtc env OPENRTC_UVLOOP=0 $PY openrtc_agent.py
one thr-uvloop  $PY openrtc_agent.py
$PY summarize.py
