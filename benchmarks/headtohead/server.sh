#!/usr/bin/env bash
# Start a local dev livekit-server (keys devkey / secret) on cores 2-3, away from the worker.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p out
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  taskset -c 2,3 bin/livekit-server --dev --bind 127.0.0.1 > out/livekit-server.log 2>&1 &
echo "livekit-server pid $!"
