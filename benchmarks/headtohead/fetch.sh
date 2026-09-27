#!/usr/bin/env bash
# Download what the harness needs but the repo does not vendor: livekit-server and the
# speech clip the callers play (livekit/agents' own test fixture, Apache-2.0).
set -euo pipefail
cd "$(dirname "$0")"
V=1.13.7
ARCH=$(uname -m | sed 's/x86_64/amd64/; s/aarch64/arm64/')
if [ ! -x bin/livekit-server ]; then
  mkdir -p bin
  curl -fsSL "https://github.com/livekit/livekit/releases/download/v$V/livekit_${V}_linux_${ARCH}.tar.gz" | tar -xz -C bin livekit-server
fi
[ -s change-sophie.wav ] || curl -fsSL -o change-sophie.wav \
  https://media.githubusercontent.com/media/livekit/agents/main/tests/change-sophie.wav
echo "ready: bin/livekit-server $(bin/livekit-server --version | awk '{print $NF}'), change-sophie.wav"
