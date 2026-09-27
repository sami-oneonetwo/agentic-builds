#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/env.sh"
for n in caffeinate listen compositor ffmpeg run; do
  f="$PID_DIR/$n.pid"
  if [ -f "$f" ]; then
    pid=$(cat "$f")
    if kill -0 "$pid" 2>/dev/null; then
      echo "stop.sh: killing $n pid=$pid"
      kill "$pid" 2>/dev/null || true
      # pipeline leader: also the group
      if [ "$n" = run ]; then
        kill -TERM -"$pid" 2>/dev/null || true
      fi
    fi
    rm -f "$f"
  fi
done
# leftovers
pkill -f "hearth.compositor" 2>/dev/null || true
sleep 0.4
rm -f "$RUN_DIR/a.pcm"
echo "stop.sh: done"
