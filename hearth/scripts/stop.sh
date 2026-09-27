#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/env.sh"
for n in compositor ffmpeg listen; do
  f="$PID_DIR/$n.pid"
  if [ -f "$f" ]; then
    pid=$(cat "$f")
    if kill -0 "$pid" 2>/dev/null; then
      echo "stop.sh: killing $n pid=$pid"
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "$f"
  fi
done
rm -f "$RUN_DIR/a.pcm"
echo "stop.sh: done"
