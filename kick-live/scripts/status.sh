#!/usr/bin/env bash
# scripts/status.sh — one-screen status. Runs monitor/report.py when it exists, else a built-in summary.
#
# Usage: scripts/status.sh [--raw] [--lines N] [--help]   (other args are passed to monitor/report.py)
#   --raw       force the built-in summary even if monitor/report.py exists
#   --lines N   log tail length for the built-in summary (default 5)
# Appends a category line ($RUN_DIR/category_latest.json) and a chatter-funnel line ($RUN_DIR/chatters.json) when present.
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
# category context (monitor/category_sampler.py) + chatter funnel (monitor/chatter_log.py), one line each, only
# when their files exist. Skipped for --json / --compare / --iteration-summary so machine output stays clean.
extra_lines() {
  case " ${PASS[*]-} " in *" --json "*|*" --compare "*|*" --iteration-summary "*) return 0 ;; esac
  if [ -s "$RUN_DIR/category_latest.json" ]; then
    "$PYTHON" - "$RUN_DIR/category_latest.json" <<'PY' 2>/dev/null || echo "category  (category_latest.json unreadable)"
import json, sys
from datetime import datetime, timezone
d = json.load(open(sys.argv[1]))
ts = d.get("ts") or ""
try:
    age = (datetime.now(timezone.utc) - datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)).total_seconds()
    age_s = "%dm ago" % (age // 60) + ("  [STALE >20m]" if age > 1200 else "")
except ValueError:
    age_s = "ts unknown"
cats = d.get("categories") or {}
ours = next((c for c in cats.values() if c.get("our_rank") is not None), None)
if ours:
    head = "%s: our rank #%s of %s live (%s cat viewers, we have %s)" % (
        ours.get("category"), ours["our_rank"], ours.get("live_channels"), ours.get("total_viewers"), ours.get("our_viewer_count"))
else:
    o = d.get("ours") or {}
    head = "not listed in any sampled category (live=%s)" % o.get("is_live")
others = []
for cid, c in sorted(cats.items(), key=lambda kv: int(kv[0])):
    if c is ours or c.get("error"):
        continue
    cut = c.get("rank24_cutoff")
    others.append("%s %s live/%s v/cut %s/would-be #%s" % (
        c.get("category"), c.get("live_channels"), c.get("total_viewers"), "-" if cut is None else cut, c.get("our_would_be_rank") or "-"))
print("category  %s  (%s)" % (head, age_s))
if others:
    print("          " + " | ".join(others))
PY
  fi
  if [ -s "$RUN_DIR/chatters.json" ] && [ -f "$KICK_LIVE_ROOT/monitor/chatter_log.py" ]; then
    "$PYTHON" "$KICK_LIVE_ROOT/monitor/chatter_log.py" --out "$RUN_DIR/chatters.json" --summary 2>/dev/null || echo "chatters  (chatters.json unreadable)"
  fi
}

if [ "$RAW" = 0 ] && [ -f "$KICK_LIVE_ROOT/monitor/report.py" ]; then
  "$PYTHON" "$KICK_LIVE_ROOT/monitor/report.py" ${PASS[@]+"${PASS[@]}"}; rc=$?
  extra_lines
  exit $rc
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
echo "--- category / chatters"
extra_lines
for l in supervisor ffmpeg kick_api chat_listener compositor; do
  if [ -s "$LOG_DIR/$l.log" ]; then echo "--- $l.log (tail $LINES)"; tail -"$LINES" "$LOG_DIR/$l.log" | cut -c1-200 | sed 's/^/  /'; fi
done
