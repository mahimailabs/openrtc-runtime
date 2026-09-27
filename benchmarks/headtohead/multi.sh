#!/usr/bin/env bash
# Start K OpenRTC workers under one parent, worker i pinned to core i (PIN=0: all share the
# cores run.sh gives), so run.sh samples PSS and CPU for all of them as one tree.
# usage: K=2 ./multi.sh <worker command...>   (run.sh appends "start")
set -u
K=${K:-2}
# Background jobs of a script ignore SIGINT, so forward SIGTERM (livekit drains on it too).
trap 'kill -TERM $(jobs -p) 2>/dev/null; wait' INT TERM
for i in $(seq 0 $((K - 1))); do
  if [ "${PIN:-1}" = 1 ]; then pin=(taskset -c "$i"); else pin=(); fi
  BENCH_PORT=$((8090 + i)) "${pin[@]}" "$@" &
done
wait
