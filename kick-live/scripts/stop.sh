#!/usr/bin/env bash
# scripts/stop.sh — stop everything scripts/start.sh started, via pid files, wait, clean up.
#
# Usage: scripts/stop.sh [--force] [--sweep] [--help]
#   --force   skip the graceful wait: TERM then KILL after 2 s
#   --sweep   also kill stray processes whose command line is under this repo's stream/ or monitor/
#             (default: only report them, so concurrent dev runs are not killed)
# Order: supervisor (which kills its run.sh/ffmpeg/compositor group) -> leftover run/ffmpeg/compositor
#        -> kick_api -> chat_listener -> stray report/sweep.
# Exit 0 if nothing tracked by a pid file is left running, 1 otherwise.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

FORCE=0; SWEEP=0
for a in "$@"; do
  case "$a" in
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --force) FORCE=1 ;;
    --sweep) SWEEP=1 ;;
    *) echo "stop.sh: unknown option '$a' (try --help)" >&2; exit 2 ;;
  esac
done
pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }
GRACE=15; [ "$FORCE" = 1 ] && GRACE=2

stop_one() { # stop_one <name> [group]
  local n="${1:?}" f="${PID_DIR:?}/${1:?}.pid" pid
  [ -f "$f" ] || return 0
  pid="$(cat "$f" 2>/dev/null || true)"
  if ! pid_alive "$pid"; then echo "  $n: not running (stale pid file removed)"; rm -f "$f"; return 0; fi
  printf '  %s: pid %s TERM' "$n" "$pid"
  kill -TERM "$pid" 2>/dev/null || true
  if [ "${2:-}" = group ]; then kill -TERM -- "-$pid" 2>/dev/null || true; fi
  local i; for i in $(seq 1 $((GRACE * 2))); do pid_alive "$pid" || break; sleep 0.5; printf '.'; done
  if pid_alive "$pid"; then
    kill -KILL "$pid" 2>/dev/null || true
    if [ "${2:-}" = group ]; then kill -KILL -- "-$pid" 2>/dev/null || true; fi
    sleep 0.5; printf ' KILL'
  fi
  if pid_alive "$pid"; then echo " STILL ALIVE"; else echo " stopped"; fi
  rm -f "$f"
}

echo "stop.sh: stopping kick-live processes (pids in $PID_DIR)"
stop_one supervisor
stop_one run group
stop_one ffmpeg
stop_one compositor
stop_one kick_api
stop_one chat_listener
stop_one category_sampler
stop_one ops_switch

# Strays: anything else running from this repo's stream/ or monitor/ dirs (never ourselves).
STRAY="$(pgrep -f "$KICK_LIVE_ROOT/(stream|monitor)/" 2>/dev/null | grep -vx -e "$$" -e "$PPID" || true)"
if [ -n "$STRAY" ]; then
  echo "  untracked processes from $KICK_LIVE_ROOT (not started via pid files):"
  for p in $STRAY; do echo "    $(ps -o pid=,command= -p "$p" | cut -c1-140)"; done
  if [ "$SWEEP" = 1 ]; then
    for p in $STRAY; do kill -TERM "$p" 2>/dev/null || true; done
    sleep 2
    for p in $STRAY; do if pid_alive "$p"; then kill -KILL "$p" 2>/dev/null || true; fi; done
    echo "  swept."
  else
    echo "  left alone (pass --sweep to kill them)."
  fi
fi
LEFT=""
for n in supervisor run ffmpeg compositor kick_api chat_listener category_sampler ops_switch; do
  if [ -f "$PID_DIR/$n.pid" ] && pid_alive "$(cat "$PID_DIR/$n.pid")"; then LEFT="$LEFT $n"; fi
done
kl_activity stop.sh "pipeline stopped" 2>/dev/null || true
if [ -n "$LEFT" ]; then echo "stop.sh: WARNING still alive:$LEFT"; exit 1; fi
echo "stop.sh: all stopped, pid files cleaned."
