#!/usr/bin/env bash
# scripts/deploy.sh — restart ONLY the compositor child under stream/relay.py. ffmpeg is never touched.
#
# Usage: [RUN_DIR=...] scripts/deploy.sh [--wait N] [--reason TEXT] [--via-relay] [--help]
#   --wait N       seconds to wait for the new compositor to reconnect (default 30)
#   --reason TEXT  one line for the on-screen activity feed / journal (default "deploy")
#   --via-relay    ask the relay to restart its child (SIGUSR1 to relay.pid) instead of SIGTERM to compositor.pid
#
# What it does: verifies a relay is running for $RUN_DIR (refuses otherwise: without the relay a compositor restart
# drops ingest, journal 011), records the ffmpeg pid, SIGTERMs the compositor child, waits for the relay to respawn
# it and for the new child to reconnect, then prints the ingest-gap measurement the relay recorded (how many
# frames it held: last-frame repeats + card frames) and proves the ffmpeg pid did not change.
# Exit 0 = redeployed, ffmpeg pid unchanged; 1 = refused / gap not closed in time / ffmpeg pid changed; 2 = usage.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

WAIT=30; REASON="deploy"; VIA=child
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --wait) WAIT="${2:-}"; case "$WAIT" in ''|*[!0-9]*) echo "deploy.sh: --wait needs an integer" >&2; exit 2 ;; esac; shift ;;
    --reason) REASON="${2:-deploy}"; shift ;;
    --via-relay) VIA=relay ;;
    *) echo "deploy.sh: unknown option '$1' (try --help)" >&2; exit 2 ;;
  esac
  shift
done

pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }
pidfile() { cat "$PID_DIR/$1.pid" 2>/dev/null || true; }
STATUS="$RUN_DIR/relay_status.json"
jget() { # jget <key> [default]  (top-level scalar from relay_status.json)
  "$PYTHON" -c 'import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: print(sys.argv[3] if len(sys.argv)>3 else ""); sys.exit(0)
v=d.get(sys.argv[2]); print("" if v is None else (len(v) if isinstance(v,list) else v))' "$STATUS" "$@"
}

RELAY_PID="$(pidfile relay)"; COMP_PID="$(pidfile compositor)"; FF_PID="$(pidfile ffmpeg)"
echo "deploy.sh: run_dir=$RUN_DIR reason=\"$REASON\""
if ! pid_alive "$RELAY_PID"; then
  echo "deploy.sh: REFUSING: no relay running for $RUN_DIR (relay.pid='${RELAY_PID:-none}')." >&2
  echo "           Without stream/relay.py a compositor restart closes ffmpeg's stdin and drops ingest (journal 011)." >&2
  echo "           Start the pipeline with SOURCE=compositor RELAY=1 stream/run.sh (the default) and retry." >&2
  exit 1
fi
if ! pid_alive "$FF_PID"; then echo "deploy.sh: REFUSING: ffmpeg.pid='${FF_PID:-none}' is not alive; nothing to protect, nothing to deploy into." >&2; exit 1; fi
if ! pid_alive "$COMP_PID"; then echo "deploy.sh: note: compositor.pid='${COMP_PID:-none}' not alive; the relay is already respawning it"; fi
GAPS0="$(jget gaps 0)"; RESTARTS0="$(jget child_restarts 0)"; OUT0="$(jget out 0)"
# relay_status.json keeps only the LAST 20 gaps, so len(gaps) stops growing once the list is full (journal 024: two
# successful deploys printed FAIL). Success is judged on the newest gap's start_ts changing, not on the count.
jlastgap() { "$PYTHON" -c 'import json,sys
try: d=json.load(open(sys.argv[1])); g=(d.get("gaps") or [{}])[-1]; print(g.get("start_ts") or "")
except Exception: print("")' "$STATUS"; }
LASTGAP0="$(jlastgap)"
FF_START="$(ps -o lstart= -p "$FF_PID" 2>/dev/null | sed 's/^ *//')"
echo "  before: ffmpeg pid=$FF_PID (started $FF_START)  relay pid=$RELAY_PID  compositor pid=${COMP_PID:-none}  relay frames out=$OUT0 gaps=$GAPS0 restarts=$RESTARTS0"

kl_activity deploy "$REASON: restarting compositor pid=${COMP_PID:-?} under relay pid=$RELAY_PID (encoder pid=$FF_PID untouched)" 2>/dev/null || true
T0=$(date +%s.%N 2>/dev/null || date +%s)
if [ "$VIA" = relay ]; then
  echo "  SIGUSR1 -> relay pid=$RELAY_PID (relay terminates and respawns its child)"
  kill -USR1 "$RELAY_PID"
else
  echo "  SIGTERM -> compositor pid=$COMP_PID (relay respawns it)"
  kill -TERM "$COMP_PID"
fi

# wait: new child pid alive, gap count grew (the relay closes a gap only when fresh frames flow again)
NEW=""; DEADLINE=$(( $(date +%s) + WAIT )); OK=0
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  NEW="$(pidfile compositor)"
  G="$(jget gaps 0)"; R="$(jget child_restarts 0)"; C="$(jget connected)"
  LG="$(jlastgap)"
  if [ -n "$NEW" ] && [ "$NEW" != "$COMP_PID" ] && pid_alive "$NEW" && [ "$R" -gt "$RESTARTS0" ] && { [ "$G" -gt "$GAPS0" ] || { [ -n "$LG" ] && [ "$LG" != "$LASTGAP0" ]; }; } && [ "$C" = True ]; then OK=1; break; fi
  sleep 0.25
done
T1=$(date +%s.%N 2>/dev/null || date +%s)
ELAPSED="$("$PYTHON" -c 'import sys;print("%.1f"%(float(sys.argv[1])-float(sys.argv[2])))' "$T1" "$T0" 2>/dev/null || echo "?")"

echo "--- result"
FF_NOW="$(pidfile ffmpeg)"
if [ "$FF_NOW" = "$FF_PID" ] && pid_alive "$FF_PID"; then echo "  ffmpeg pid=$FF_PID UNCHANGED and alive (started $FF_START)"; else echo "  FAIL: ffmpeg pid changed or died: before=$FF_PID now=${FF_NOW:-none}"; OK=0; fi
if [ "$OK" = 1 ]; then
  echo "  compositor: old pid=${COMP_PID:-none} -> new pid=$NEW, reconnected after ${ELAPSED}s wall"
  "$PYTHON" - "$STATUS" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
g = (d.get("gaps") or [{}])[-1]
fps = float(d.get("fps") or 30)
print("  ingest gap (relay measurement): compositor absent %.2f s = %d frames held: %d last-frame repeats (%.2f s) + %d 'deploying' card frames (%.2f s); encoder saw no EOF, 0 frames missing" % (
    g.get("duration_s", 0), g.get("repeated_frames", 0), g.get("repeated", 0), g.get("repeated", 0) / fps, g.get("card", 0), g.get("card", 0) / fps))
print("  relay totals: out=%s fresh=%s repeated=%s card=%s in_dropped=%s restarts=%s gaps=%s tick_ms_avg=%s" % (
    d.get("out"), d.get("fresh"), d.get("repeated"), d.get("card"), d.get("in_dropped"), d.get("child_restarts"), len(d.get("gaps") or []), d.get("tick_ms_avg")))
EOF
  grep "gap #" "$LOG_DIR/relay.log" 2>/dev/null | tail -1 | sed 's/^/  relay.log: /'
  kl_activity deploy "$REASON: done, compositor pid=$NEW live again; encoder pid=$FF_PID unchanged" 2>/dev/null || true
  exit 0
else
  echo "  FAIL: new compositor did not reconnect within ${WAIT}s (compositor.pid=${NEW:-none}, relay gaps=$(jget gaps 0) restarts=$(jget child_restarts 0) connected=$(jget connected))"
  echo "  relay.log tail:"; tail -5 "$LOG_DIR/relay.log" 2>/dev/null | sed 's/^/    /'
  echo "  compositor.log tail:"; tail -5 "$LOG_DIR/compositor.log" 2>/dev/null | sed 's/^/    /'
  exit 1
fi
