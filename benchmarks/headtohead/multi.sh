#!/usr/bin/env bash
# Start K OpenRTC workers under one parent, worker i pinned to core i (PIN=0: all share the
# cores run.sh gives), so run.sh samples PSS and CPU for all of them as one tree.
# usage: K=2 ./multi.sh <worker command...>   (run.sh appends "start" and signals the
# whole process group, so this wrapper forwards nothing)
set -u
K=${K:-2}
for i in $(seq 0 $((K - 1))); do
  if [ "${PIN:-1}" = 1 ]; then pin=(taskset -c "$i"); else pin=(); fi
  BENCH_PORT=$((8090 + i)) "${pin[@]}" "$@" &
done
wait
