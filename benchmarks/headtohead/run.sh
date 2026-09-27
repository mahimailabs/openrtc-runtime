#!/usr/bin/env bash
# One run: start a worker on cores 0-1, play N calls from cores 2-3 for HOLD seconds, print
# one JSON line of results. usage: run.sh <label> <calls> <hold s> <worker command...>
set -u
cd "$(dirname "$0")"
LABEL=$1 N=$2 HOLD=$3; shift 3
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export LIVEKIT_URL=ws://127.0.0.1:7880 LIVEKIT_API_KEY=devkey LIVEKIT_API_SECRET=secret PYTHONPATH=$PWD
PY=${PY:-../../.venv/bin/python}
mkdir -p out
taskset -c 0,1 "$@" start > "out/$LABEL.worker.log" 2>&1 &
WPID=$!
for _ in $(seq 120); do grep -q "registered worker" "out/$LABEL.worker.log" && break; sleep 1; done
sleep 15  # let prewarm settle: the first rows of the sampler are the idle baseline
$PY sampler.py $WPID "out/$LABEL.csv" &
SPID=$!
sleep 5
grep -E "^cpu[01] " /proc/stat > "out/$LABEL.stat0"
TIMEFORMAT="%R %U %S"
{ time taskset -c 2,3 timeout $((HOLD + 150)) $PY loadgen.py "$N" "$HOLD" "$LABEL" \
    > "out/$LABEL.load.json" 2> "out/$LABEL.load.err"; } 2> "out/$LABEL.loadtime"
grep -E "^cpu[01] " /proc/stat > "out/$LABEL.stat1"
[ -s "out/$LABEL.load.json" ] || echo '{"calls": '"$N"', "loadgen_timed_out": true}' > "out/$LABEL.load.json"
sleep 30
STUCK=$($PY cleanup.py "$LABEL" 2>/dev/null)
kill -INT $WPID; sleep 5; kill -9 $WPID 2>/dev/null; pkill -9 -P $WPID 2>/dev/null
kill $SPID 2>/dev/null
STUCK=$STUCK $PY collect.py "$LABEL"
