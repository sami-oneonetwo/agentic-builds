#!/usr/bin/env bash
# scripts/status.sh — one-screen status. Runs monitor/report.py when it exists, else a built-in summary.
#
# Usage: scripts/status.sh [--raw] [--lines N] [--help]   (other args are passed to monitor/report.py)
#   --raw       force the built-in summary even if monitor/report.py exists
#   --lines N   log tail length for the built-in summary (default 5)
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

RAW=0; LINES=5; PASS=()
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --raw) RAW=1 ;;
    --lines) LINES="${2:-5}"; shift ;;
    *) PASS+=("$1") ;;
  esac
  shift
done
if [ "$RAW" = 0 ] && [ -f "$KICK_LIVE_ROOT/monitor/report.py" ]; then
  exec "$PYTHON" "$KICK_LIVE_ROOT/monitor/report.py" ${PASS[@]+"${PASS[@]}"}
fi

pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }
echo "kick-live status  $(date -u +%Y-%m-%dT%H:%M:%SZ)  channel=$KICK_CHANNEL  root=$KICK_LIVE_ROOT"
echo "--- processes"
for n in supervisor run ffmpeg compositor kick_api chat_listener; do
  f="$PID_DIR/$n.pid"
  if [ -f "$f" ]; then p="$(cat "$f")"; if pid_alive "$p"; then s="RUNNING pid=$p"; else s="DEAD (stale pid $p)"; fi
  else s="not running"; fi
  printf '  %-14s %s\n' "$n" "$s"
done
echo "--- encoder (last -progress block: $RUN_DIR/ffmpeg_progress.txt)"
if [ -s "$RUN_DIR/ffmpeg_progress.txt" ]; then
  awk -F= '{v[$1]=$2} END{printf "  frame=%s fps=%s bitrate=%s out_time=%s drop=%s dup=%s speed=%s\n", v["frame"], v["fps"], v["bitrate"], v["out_time"], v["drop_frames"], v["dup_frames"], v["speed"]}' "$RUN_DIR/ffmpeg_progress.txt"
else echo "  (no progress file)"; fi
echo "--- supervisor events (last 5)"
if [ -f "$RUN_DIR/supervisor_events.jsonl" ]; then tail -5 "$RUN_DIR/supervisor_events.jsonl" | sed 's/^/  /'; else echo "  (none)"; fi
echo "--- channel (last metrics line)"
if [ -s "$METRICS_FILE" ]; then tail -1 "$METRICS_FILE" | sed 's/^/  /'; else echo "  (no $METRICS_FILE yet)"; fi
echo "--- chat"
if [ -s "$RUN_DIR/chat_stats.json" ]; then sed 's/^/  /' "$RUN_DIR/chat_stats.json"; echo; else echo "  (no chat_stats.json yet)"; fi
if [ -s "$CHAT_FILE" ]; then echo "  last: $(tail -1 "$CHAT_FILE" | cut -c1-160)"; fi
echo "--- activity (last 3)"
if [ -s "$ACTIVITY_FILE" ]; then tail -3 "$ACTIVITY_FILE" | sed 's/^/  /'; else echo "  (none)"; fi
for l in supervisor ffmpeg kick_api chat_listener compositor; do
  if [ -s "$LOG_DIR/$l.log" ]; then echo "--- $l.log (tail $LINES)"; tail -"$LINES" "$LOG_DIR/$l.log" | cut -c1-200 | sed 's/^/  /'; fi
done
