#!/usr/bin/env bash
# scripts/start.sh — one command to bring the whole pipeline up (background, nohup, pids in $PID_DIR).
#
# Usage: [MODE=live|test|file] [SOURCE=compositor|testsrc] scripts/start.sh [--no-monitor] [--dry-run] [--help]
#   --no-monitor   start only the stream supervisor (skip kick_api.py and chat_listener.py)
#   --dry-run      show what would start, start nothing
# Starts: stream/supervisor.sh (-> stream/run.sh -> ffmpeg), monitor/kick_api.py --json-state,
#         monitor/chat_listener.py. Monitors that are not built yet are skipped with a note.
# Idempotent: refuses (exit 1) if any of those pids is alive. MODE=live with empty STREAM_KEY: exit 3.
# Stop with scripts/stop.sh, inspect with scripts/status.sh.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

NO_MONITOR=0; DRY=0
for a in "$@"; do
  case "$a" in
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --no-monitor) NO_MONITOR=1 ;;
    --dry-run) DRY=1 ;;
    *) echo "start.sh: unknown option '$a' (try --help)" >&2; exit 2 ;;
  esac
done
export MODE="${MODE:-live}"
export SOURCE="${SOURCE:-compositor}"
export AUDIO_SOURCE="${AUDIO_SOURCE:-generated}"

pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }
pidfile_alive() { [ -f "$PID_DIR/$1.pid" ] && pid_alive "$(cat "$PID_DIR/$1.pid")"; }

# --- guards ------------------------------------------------------------------
if [ "$MODE" = live ] && [ -z "${STREAM_KEY:-}" ]; then
  echo "start.sh: REFUSING: MODE=live but STREAM_KEY is empty in ${KICK_LIVE_ENV:-$HOME/.config/kick-live/env}." >&2
  echo "          Nothing started. Use MODE=test scripts/start.sh for a local HLS run." >&2
  exit 3
fi
if [ "$SOURCE" = compositor ] && [ ! -f "$KICK_LIVE_ROOT/stream/compositor.py" ]; then
  echo "start.sh: SOURCE=compositor but stream/compositor.py is not built yet; use SOURCE=testsrc." >&2
  exit 4
fi
BUSY=0
for n in supervisor kick_api chat_listener run ffmpeg; do   # run/ffmpeg: a direct run.sh (e.g. test_local.sh) in progress
  if pidfile_alive "$n"; then echo "start.sh: $n already running (pid $(cat "$PID_DIR/$n.pid"))" >&2; BUSY=1; fi
done
if [ "$BUSY" = 1 ]; then echo "start.sh: refusing to start twice. Run scripts/stop.sh first, or scripts/status.sh." >&2; exit 1; fi
for n in supervisor kick_api chat_listener run ffmpeg compositor; do rm -f "${PID_DIR:?}/${n:?}.pid"; done  # stale

# --- plan ---------------------------------------------------------------------
NAMES=(); CMDS=()
NAMES+=(supervisor); CMDS+=("$KICK_LIVE_ROOT/stream/supervisor.sh")
if [ "$NO_MONITOR" = 0 ]; then
  if [ -f "$KICK_LIVE_ROOT/monitor/kick_api.py" ]; then
    NAMES+=(kick_api); CMDS+=("$PYTHON $KICK_LIVE_ROOT/monitor/kick_api.py --json-state")
  else echo "start.sh: monitor/kick_api.py not present yet, skipped"; fi
  if [ -f "$KICK_LIVE_ROOT/monitor/chat_listener.py" ]; then
    NAMES+=(chat_listener); CMDS+=("$PYTHON $KICK_LIVE_ROOT/monitor/chat_listener.py")
  else echo "start.sh: monitor/chat_listener.py not present yet, skipped"; fi
fi

echo "start.sh: MODE=$MODE SOURCE=$SOURCE AUDIO_SOURCE=$AUDIO_SOURCE ${STREAM_WIDTH}x${STREAM_HEIGHT}@${STREAM_FPS} v=$VIDEO_BITRATE a=$AUDIO_BITRATE"
case "$MODE" in
  live) echo "start.sh: output -> ${RTMPS_URL:-rtmps://fa723fc1b171.global-contribute.live-video.net:443/app/}***" ;;
  test) echo "start.sh: output -> $RUN_DIR/hls/index.m3u8 (local HLS, nothing goes to Kick)" ;;
  file) echo "start.sh: output -> $RUN_DIR/out.flv" ;;
esac

# --- launch ---------------------------------------------------------------------
i=0
while [ "$i" -lt "${#NAMES[@]}" ]; do
  n="${NAMES[$i]}"; c="${CMDS[$i]}"
  if [ "$DRY" = 1 ]; then echo "  would start $n: $c"; i=$((i+1)); continue; fi
  # shellcheck disable=SC2086
  nohup $c >> "$LOG_DIR/$n.out" 2>&1 < /dev/null &
  pid=$!
  # supervisor writes its own pid file; for the others we do it
  [ "$n" = supervisor ] || echo "$pid" > "$PID_DIR/$n.pid"
  sleep 1
  if pid_alive "$pid"; then echo "  started $n pid=$pid log=$LOG_DIR/$n.out"
  else echo "  FAILED  $n exited immediately; tail of $LOG_DIR/$n.out:"; tail -5 "$LOG_DIR/$n.out" | sed 's/^/    /'; rm -f "${PID_DIR:?}/${n:?}.pid"; fi
  i=$((i+1))
done
[ "$DRY" = 1 ] && exit 0
kl_activity start.sh "pipeline started mode=$MODE source=$SOURCE" 2>/dev/null || true
echo "start.sh: done. scripts/status.sh to inspect, scripts/stop.sh to stop."
