#!/usr/bin/env bash
# stream/supervisor.sh — keeps stream/run.sh (one ffmpeg) running. Restart with backoff, watchdog, clean stop.
#
# Usage: stream/supervisor.sh [--once] [--help]
#   --once      run run.sh a single time (no restart loop); exit with its code. Watchdog still active.
# Environment passthrough to run.sh: MODE (default live), SOURCE, AUDIO_SOURCE, DURATION, bitrates.
#
# Behaviour
#   - restart on exit with backoff 2,4,8,16,30 s; backoff resets to 2 s after 5 min of healthy running
#   - run.sh exit 2/3/4 (usage / refused: no STREAM_KEY / missing input) is fatal: supervisor stops
#   - watchdog (MODE=live only): if $RUN_DIR/channel.json (from monitor/kick_api.py) reports is_live=false
#     for >90 s while ffmpeg has run >120 s, the run.sh process group is killed -> restart (watchdog_restart).
#     A channel.json older than 180 s counts as unknown (a dead poller never triggers restarts).
#     Tuning/testing env: WATCHDOG=auto|on|off (auto = live only), WATCHDOG_OFFLINE_S=90,
#     WATCHDOG_MIN_UPTIME_S=120, CHANNEL_JSON_MAX_AGE_S=180
#   - SIGTERM/SIGINT: kills the run.sh process group (run.sh + ffmpeg + compositor), waits, exits 0
# Files
#   $PID_DIR/supervisor.pid, $PID_DIR/run.pid, $PID_DIR/ffmpeg.pid (written by run.sh, verified here)
#   $RUN_DIR/supervisor_events.jsonl   {ts,event,detail}  events: start, exit, restart, watchdog_restart, stop
#   $LOG_DIR/supervisor.log            human log (run.sh stdout/stderr also lands here)
#   $ACTIVITY_FILE                     on-screen feed lines, actor "supervisor"
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../scripts/env.sh"

ONCE=0
for a in "$@"; do
  case "$a" in
    -h|--help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --once) ONCE=1 ;;
    *) echo "supervisor.sh: unknown option '$a' (try --help)" >&2; exit 2 ;;
  esac
done

export MODE="${MODE:-live}"
export SOURCE="${SOURCE:-compositor}"
SUP_LOG="$LOG_DIR/supervisor.log"
EVENTS="$RUN_DIR/supervisor_events.jsonl"
CHANNEL_JSON="$RUN_DIR/channel.json"
RUN_SH="$KICK_LIVE_ROOT/stream/run.sh"
WATCHDOG="${WATCHDOG:-auto}"                              # auto: only when MODE=live; on/off: force
WATCHDOG_OFFLINE_S="${WATCHDOG_OFFLINE_S:-90}"
WATCHDOG_MIN_UPTIME_S="${WATCHDOG_MIN_UPTIME_S:-120}"
CHANNEL_JSON_MAX_AGE_S="${CHANNEL_JSON_MAX_AGE_S:-180}"
case "$WATCHDOG" in auto|on|off) ;; *) echo "supervisor.sh: WATCHDOG must be auto|on|off (got '$WATCHDOG')" >&2; exit 2 ;; esac
HEALTHY_RESET_S=300
BACKOFF_MAX=30
TICK=5

log()   { kl_log supervisor "$@" | tee -a "$SUP_LOG"; }
event() { # event <name> <detail...>
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  "$PYTHON" -c 'import json,sys; print(json.dumps({"ts":sys.argv[1],"event":sys.argv[2],"detail":sys.argv[3]}))' \
    "$ts" "$1" "${*:2}" >> "$EVENTS" 2>/dev/null \
    || printf '{"ts":"%s","event":"%s","detail":"%s"}\n' "$ts" "$1" "$(printf '%s' "${*:2}" | tr -d '"\\')" >> "$EVENTS"
  log "event=$1 $*"
  kl_activity supervisor "$1: ${*:2}" 2>/dev/null || true
}
pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }

# Read channel.json -> true|false|unknown. Tolerates {is_live:bool} or raw API {livestream:null|{is_live}}.
# Anything older than 180 s is "unknown" so a dead poller never triggers restarts.
channel_state() {
  [ -f "$CHANNEL_JSON" ] || { echo unknown; return; }
  "$PYTHON" - "$CHANNEL_JSON" "$CHANNEL_JSON_MAX_AGE_S" <<'PY' 2>/dev/null || echo unknown
import json, os, sys, time
p = sys.argv[1]
try:
    d = json.load(open(p))
except Exception:
    print("unknown"); sys.exit(0)
if time.time() - os.path.getmtime(p) > float(sys.argv[2]):
    print("unknown"); sys.exit(0)
v = None
if isinstance(d.get("is_live"), bool):
    v = d["is_live"]
elif "livestream" in d:
    ls = d["livestream"]
    v = False if ls is None else bool(ls.get("is_live", True))
print("unknown" if v is None else ("true" if v else "false"))
PY
}

# --- guards -------------------------------------------------------------------
if [ "$MODE" = live ] && [ -z "${STREAM_KEY:-}" ]; then
  echo "supervisor.sh: REFUSING: MODE=live but STREAM_KEY is empty (fill ${KICK_LIVE_ENV:-$HOME/.config/kick-live/env})" >&2
  exit 3
fi
if [ -f "$PID_DIR/supervisor.pid" ] && pid_alive "$(cat "$PID_DIR/supervisor.pid")"; then
  echo "supervisor.sh: already running (pid $(cat "$PID_DIR/supervisor.pid"))" >&2
  exit 1
fi
echo $$ > "$PID_DIR/supervisor.pid"

# --- process-group control -------------------------------------------------------
RUN_PID=""; STOPPING=0; SLEEP_PID=""
kill_run_group() { # TERM the run.sh process group, wait up to 10 s, then KILL
  [ -n "$RUN_PID" ] || return 0
  kill -TERM -- "-$RUN_PID" 2>/dev/null || kill -TERM "$RUN_PID" 2>/dev/null || true
  local i
  for i in $(seq 1 20); do pid_alive "$RUN_PID" || break; sleep 0.5; done
  if pid_alive "$RUN_PID"; then
    kill -KILL -- "-$RUN_PID" 2>/dev/null || kill -KILL "$RUN_PID" 2>/dev/null || true
    sleep 0.5
  fi
}
on_term() {
  trap - TERM INT
  STOPPING=1
  [ -n "$SLEEP_PID" ] && kill "$SLEEP_PID" 2>/dev/null || true
  log "signal received, stopping run.sh group pgid=${RUN_PID:-none}"
  kill_run_group
  event stop "signal; run.sh group ${RUN_PID:-none} stopped"
  rm -f "${PID_DIR:?}/supervisor.pid" "${PID_DIR:?}/run.pid" "${PID_DIR:?}/ffmpeg.pid" "${PID_DIR:?}/compositor.pid"
  exit 0
}
trap on_term TERM INT
trap 'rm -f "${PID_DIR:?}/supervisor.pid" "${PID_DIR:?}/run.pid"' EXIT
isleep() { sleep "$1" & SLEEP_PID=$!; wait "$SLEEP_PID" 2>/dev/null || true; SLEEP_PID=""; }

# --- main loop -------------------------------------------------------------------
BACKOFF=2; ATTEMPT=0
log "supervisor pid=$$ mode=$MODE source=$SOURCE once=$ONCE root=$KICK_LIVE_ROOT"
while :; do
  ATTEMPT=$((ATTEMPT + 1))
  set -m                       # job control: child gets its own process group so we can kill the whole tree
  "$RUN_SH" >> "$SUP_LOG" 2>&1 &
  RUN_PID=$!
  set +m
  START="$(date +%s)"
  echo "$RUN_PID" > "$PID_DIR/run.pid"
  event start "run.sh pid=$RUN_PID attempt=$ATTEMPT mode=$MODE source=$SOURCE"

  OFFLINE_SINCE=0; WATCHDOG_FIRED=0; FF_SEEN=""
  while pid_alive "$RUN_PID"; do
    isleep "$TICK"
    [ "$STOPPING" = 1 ] && break
    pid_alive "$RUN_PID" || break
    # mirror ffmpeg.pid once run.sh has written it
    if [ -z "$FF_SEEN" ] && [ -s "$PID_DIR/ffmpeg.pid" ]; then
      FF_SEEN="$(cat "$PID_DIR/ffmpeg.pid")"
      if pid_alive "$FF_SEEN"; then log "ffmpeg pid=$FF_SEEN confirmed alive"; else log "WARN ffmpeg pid=$FF_SEEN from pid file is not alive"; fi
    fi
    # watchdog (auto: live only)
    if [ "$WATCHDOG" = on ] || { [ "$WATCHDOG" = auto ] && [ "$MODE" = live ]; }; then
      NOW="$(date +%s)"; STATE="$(channel_state)"
      case "$STATE" in
        true) OFFLINE_SINCE=0 ;;
        false)
          [ "$OFFLINE_SINCE" = 0 ] && OFFLINE_SINCE="$NOW"
          if [ $((NOW - OFFLINE_SINCE)) -gt "$WATCHDOG_OFFLINE_S" ] && [ $((NOW - START)) -gt "$WATCHDOG_MIN_UPTIME_S" ]; then
            event watchdog_restart "channel.json is_live=false for $((NOW - OFFLINE_SINCE))s, ffmpeg uptime $((NOW - START))s; killing pgid $RUN_PID"
            WATCHDOG_FIRED=1
            kill_run_group
            break
          fi ;;
      esac
    fi
  done

  set +e; wait "$RUN_PID" 2>/dev/null; RC=$?; set -e
  UPTIME=$(( $(date +%s) - START ))
  rm -f "${PID_DIR:?}/run.pid" "$PID_DIR/ffmpeg.pid" "$PID_DIR/compositor.pid"
  [ "$STOPPING" = 1 ] && exit 0
  event exit "run.sh rc=$RC uptime=${UPTIME}s attempt=$ATTEMPT$([ "$WATCHDOG_FIRED" = 1 ] && echo " cause=watchdog")"

  case "$RC" in
    2|3|4) event stop "fatal run.sh rc=$RC (usage/refused/missing input); not restarting"; exit "$RC" ;;
  esac
  if [ "$ONCE" = 1 ]; then event stop "once mode; run.sh rc=$RC"; exit "$RC"; fi
  if [ "$RC" = 0 ] && [ -n "${DURATION:-}" ]; then event stop "DURATION=${DURATION}s completed rc=0"; exit 0; fi

  if [ "$UPTIME" -ge "$HEALTHY_RESET_S" ]; then BACKOFF=2; fi
  event restart "sleeping ${BACKOFF}s before attempt $((ATTEMPT + 1))"
  isleep "$BACKOFF"
  [ "$STOPPING" = 1 ] && exit 0
  BACKOFF=$(( BACKOFF * 2 )); [ "$BACKOFF" -gt "$BACKOFF_MAX" ] && BACKOFF=$BACKOFF_MAX
done
