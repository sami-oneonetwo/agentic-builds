#!/usr/bin/env bash
# agents/probe.sh - the headless probe loop (docs/IDLEWORLD.md section 4.6 item 2).
#
#   loop { pause flag; df >= 20 GB; probe.py observe --json; claude -p "$(cat agents/prompts/probe.md)"
#          --output-format json (Read + the read-only commands allowed, nothing else); probe.py ingest < result;
#          sleep 1200 (300 while chat_stats.msgs_per_min_5m > 50) }
#
# Launch (RESUME.md):
#   RUN_DIR=$L env -u STREAM_KEY -u SRT_PASSPHRASE -u KICK_CLIENT_SECRET -u KICK_TOKEN -u NGROK_AUTHTOKEN \
#       nohup bash agents/probe.sh >> $L/logs/probe.out 2>&1 &
#   The script also scrubs those five itself (re-exec through env -u) so `ps -E` never shows a stream secret.
#   The API variables the claude session needs (ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN, HANDOFF.md) are NOT in
#   ~/.config/kick-live/env; the launcher passes them explicitly. They are left untouched here.
# Flags:  --once     one tick, then exit          --dry   everything but the claude call (probe.py dry-result instead)
#         --run-dir D  (else $RUN_DIR)             --no-sweep  skip the 48 h /tmp/lg-* sweep on OBSERVE
# Files:  pid $RUN_DIR/pids/probe.pid, log $RUN_DIR/logs/probe.out (the launcher redirects), think $RUN_DIR/probe/think.json.
# The probe never writes state.json (no heartbeat), never touches world.json / chat.jsonl, never draws anything.
set -u

SECRETS=(STREAM_KEY SRT_PASSPHRASE KICK_CLIENT_SECRET KICK_TOKEN NGROK_AUTHTOKEN)
if [ -z "${PROBE_SCRUBBED:-}" ]; then
  SCRUB=(env -u STREAM_KEY -u SRT_PASSPHRASE -u KICK_CLIENT_SECRET -u KICK_TOKEN -u NGROK_AUTHTOKEN PROBE_SCRUBBED=1)
  exec "${SCRUB[@]}" bash "$0" "$@"
fi
for v in "${SECRETS[@]}"; do
  if [ -n "${!v:-}" ]; then echo "probe.sh: refusing to run with $v in the environment" >&2; exit 3; fi
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PY:-/Users/sandy/.local/share/kick-live/venv/bin/python}"
CLAUDE="${CLAUDE_BIN:-claude}"
PROMPT="$ROOT/agents/prompts/probe.md"
SLEEP_S=1200
FAST_S=300
FAST_MPM=50
DF_MIN_GB=20
ONCE=0; DRY=0; SWEEP=1
while [ $# -gt 0 ]; do
  case "$1" in
    --once) ONCE=1 ;;
    --dry) DRY=1 ;;
    --no-sweep) SWEEP=0 ;;
    --run-dir) shift; RUN_DIR="$1" ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "probe.sh: unknown flag $1" >&2; exit 2 ;;
  esac
  shift
done
: "${RUN_DIR:?RUN_DIR (or --run-dir) is required}"
export RUN_DIR
LIVE="$HOME/.local/share/kick-live/run-live"
if [ "$(cd "$RUN_DIR" 2>/dev/null && pwd -P)" = "$(cd "$LIVE" 2>/dev/null && pwd -P)" ] && [ "${MODE:-test}" != "live" ]; then
  echo "probe.sh: refusing the live run dir in MODE=${MODE:-test}" >&2; exit 3
fi
mkdir -p "$RUN_DIR/probe" "$RUN_DIR/pids" "$RUN_DIR/logs"
PIDFILE="$RUN_DIR/pids/probe.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null && [ "$(cat "$PIDFILE")" != "$$" ]; then
  echo "probe.sh: another probe loop is alive (pid $(cat "$PIDFILE")); not starting a second one" >&2; exit 4
fi
echo $$ > "$PIDFILE"
SLEEP_PID=""
cleanup() { [ -n "$SLEEP_PID" ] && kill "$SLEEP_PID" 2>/dev/null; rm -f "$PIDFILE"; }
trap 'cleanup; exit 0' INT TERM
trap 'cleanup' EXIT
# The nap runs as a child and the loop `wait`s on it, so SIGTERM (stop.sh) ends the loop at once instead of after
# 20 min. It is the venv python, not /bin/sleep: macOS hides the environment of Apple-signed binaries from `ps -E`,
# and the secret check (`ps -E -p <child>`, swap-build.sh step 5) needs a child whose environment ps can show.
nap() { "$PY" -c 'import sys, time; time.sleep(float(sys.argv[1]))' "$1" & SLEEP_PID=$!; wait "$SLEEP_PID"; SLEEP_PID=""; }

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
free_gb() { df -g "$RUN_DIR" 2>/dev/null | awk 'NR==2 {print $4}'; }
mpm() { "$PY" - "$RUN_DIR/chat_stats.json" <<'EOF' 2>/dev/null || echo 0
import json, sys
try:
    print(int(float(json.load(open(sys.argv[1])).get("msgs_per_min_5m") or 0)))
except Exception:
    print(0)
EOF
}

# Read + the read-only commands, nothing else (the allow patterns are prefix globs; probe.md lists the same commands).
ALLOWED=(
  "Read"
  "Bash($PY $ROOT/agents/probe.py --run-dir $RUN_DIR observe*)"
  "Bash($PY $ROOT/agents/probe.py --run-dir $RUN_DIR next*)"
  "Bash(cat $RUN_DIR/probe/latest.json)"
  "Bash(cat $RUN_DIR/probe/observe.json)"
  "Bash(RUN_DIR=$RUN_DIR $PY $ROOT/monitor/report.py --window * --json)"
  "Bash(RUN_DIR=$RUN_DIR $PY $ROOT/monitor/chatter_log.py --out - --no-report --json)"
  "Bash($PY $ROOT/agents/duty.py --run-dir $RUN_DIR list)"
)
DISALLOWED=("Edit" "Write" "MultiEdit" "NotebookEdit" "WebFetch" "WebSearch" "Agent" "Task" "Bash(rm *)" "Bash(git *)" "Bash(*ingest*)" "Bash(*take*)" "Bash(*built*)" "Bash(*reject*)" "Bash(*--write*)")

tick() {
  local free think rc
  if [ -e "$RUN_DIR/pause_bot.json" ]; then
    echo "$(ts) probe: paused (pause_bot.json): observe only"
    "$PY" "$ROOT/agents/probe.py" --run-dir "$RUN_DIR" observe >/dev/null 2>&1
    return 0
  fi
  free="$(free_gb)"; free="${free:-0}"
  if [ "$free" -lt "$DF_MIN_GB" ]; then
    echo "$(ts) probe: disk ${free} GB free < ${DF_MIN_GB}: observe only, no THINK (fix-only proposals need an orchestrator)"
    "$PY" "$ROOT/agents/probe.py" --run-dir "$RUN_DIR" observe >/dev/null 2>&1
    return 0
  fi
  if [ "$SWEEP" = 1 ]; then
    "$PY" "$ROOT/agents/probe.py" --run-dir "$RUN_DIR" observe --sweep >/dev/null || { echo "$(ts) probe: observe failed"; return 1; }
  else
    "$PY" "$ROOT/agents/probe.py" --run-dir "$RUN_DIR" observe >/dev/null || { echo "$(ts) probe: observe failed"; return 1; }
  fi
  "$PY" "$ROOT/agents/probe.py" --run-dir "$RUN_DIR" classify --write >/dev/null 2>&1 || true
  "$PY" "$ROOT/agents/probe.py" --run-dir "$RUN_DIR" dossiers >/dev/null 2>&1 || true
  think="$RUN_DIR/probe/think.json"
  if [ "$DRY" = 1 ]; then
    "$PY" "$ROOT/agents/probe.py" --run-dir "$RUN_DIR" dry-result > "$think" || { echo "$(ts) probe: dry-result failed"; return 1; }
    echo "$(ts) probe: dry tick (no claude call)"
  else
    # The prompt is the fixed file plus one data line naming RUN_DIR. No chat text enters the prompt: the model reads
    # observe.json through the Read tool as data.
    ( cd "$ROOT" && "$CLAUDE" -p "RUN_DIR=$RUN_DIR
$(cat "$PROMPT")" --output-format json --permission-mode dontAsk --permission-prompts none --no-session-persistence \
        --tools "Read,Bash" --allowedTools "${ALLOWED[@]}" --disallowedTools "${DISALLOWED[@]}" \
        --add-dir "$RUN_DIR" ) > "$think" 2>> "$RUN_DIR/logs/probe.claude.err"
    rc=$?
    if [ $rc -ne 0 ]; then echo "$(ts) probe: claude -p exited $rc (see logs/probe.claude.err)"; return 1; fi
  fi
  "$PY" "$ROOT/agents/probe.py" --run-dir "$RUN_DIR" ingest < "$think"
  rc=$?
  echo "$(ts) probe: ingest exit $rc"
  return 0
}

echo "$(ts) probe.sh start pid $$ run_dir=$RUN_DIR root=$ROOT once=$ONCE dry=$DRY"
echo "$(ts) probe.sh secrets in env (must be []): $("$PY" -c 'import os; print(sorted(k for k in os.environ if k in ("STREAM_KEY", "SRT_PASSPHRASE", "KICK_CLIENT_SECRET", "KICK_TOKEN", "NGROK_AUTHTOKEN")))')"
while :; do
  tick
  [ "$ONCE" = 1 ] && break
  if [ "$(mpm)" -gt "$FAST_MPM" ]; then nap "$FAST_S"; else nap "$SLEEP_S"; fi
done
