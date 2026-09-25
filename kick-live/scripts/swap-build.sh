#!/usr/bin/env bash
# scripts/swap-build.sh — freeze the working tree into a new live snapshot and restart the live
# pipeline on it, inside Kick's reconnect window (same VOD), applying the secrets scrub.
#
# Usage: scripts/swap-build.sh <snapshot-name> [--title "new stream title"] [--category-id N]
# Owner-approved restart only (journal 015 addendum). Steps:
#   1. rsync working tree -> ~/.local/share/kick-live/<snapshot-name>   (frozen copy)
#   2. py_compile everything in the snapshot; run the honesty self-test if present
#   3. optional: PATCH channel title/category via OAuth (kickapp)
#   4. stop.sh (current snapshot) -> start.sh (new snapshot), RUN_DIR=run-live, KL_LIVE=1
#   5. wait for frames, verify Kick is_live and HLS probe PASS, print the pid table
set -euo pipefail
NAME="${1:?snapshot name required, e.g. live-snapshot-v3}"; shift || true
TITLE=""; CAT=""
while [ $# -gt 0 ]; do case "$1" in --title) TITLE="$2"; shift 2;; --category-id) CAT="$2"; shift 2;; *) echo "unknown arg $1" >&2; exit 2;; esac; done
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="$HOME/.local/share/kick-live"; NEW="$BASE/$NAME"; L="$BASE/run-live"
CUR="$(readlink "$BASE/live-current" 2>/dev/null || true)"
[ -z "$CUR" ] && CUR="$(ps -o command= -p "$(cat "$L/pids/compositor.pid" 2>/dev/null || echo 0)" 2>/dev/null | grep -o "$BASE/live-snapshot[^/ ]*" | head -1 || true)"
echo "current live snapshot: ${CUR:-unknown}"; echo "new snapshot: $NEW"

echo "== 1. freeze"; rm -rf "$NEW"; mkdir -p "$NEW"
rsync -a --exclude 'run/' --exclude 'stream/experiments/' --exclude '__pycache__' --exclude '*.pyc' --exclude 'docs/promo/*.png' "$ROOT/" "$NEW/"
echo "   $(find "$NEW" -type f | wc -l | tr -d ' ') files"

echo "== 2. compile + honesty self-test"; source "$NEW/scripts/env.sh" >/dev/null 2>&1
"$PYTHON" -m py_compile "$NEW"/stream/*.py "$NEW"/stream/panels/*.py "$NEW"/stream/scenes/*.py "$NEW"/stream/world/*.py "$NEW"/agents/duty.py && echo "   compiles"
if [ -f "$NEW/stream/world/honesty.py" ]; then RUN_DIR=/tmp/swap-honesty "$PYTHON" "$NEW/stream/world/honesty.py" --self-test 2>&1 | tail -2 | sed 's/^/   /' || { echo "   HONESTY SELF-TEST FAILED, aborting"; exit 3; }; fi

if [ -n "$TITLE$CAT" ]; then echo "== 3. channel metadata"; "$PYTHON" - "$TITLE" "$CAT" <<'PY'
import sys; sys.path.insert(0, "/Users/sandy/Workspace/agentic-builds/.claude/worktrees/kick-ngrok-tunnel/kick-live/kickapp"); import kick_oauth as ko
title, cat = sys.argv[1], sys.argv[2]; body = {}
if title: body["stream_title"] = title
if cat: body["category_id"] = int(cat)
ko._req("PATCH", "/channels", ko.user_token(), json=body); print("   applied", body)
PY
fi

echo "== 4. restart pipeline (inside Kick's ~100 s window)"; T0=$(date +%s)
if [ -n "$CUR" ] && [ -x "$CUR/scripts/stop.sh" ]; then RUN_DIR="$L" bash "$CUR/scripts/stop.sh" 2>&1 | tail -1 | sed 's/^/   /'; else RUN_DIR="$L" bash "$NEW/scripts/stop.sh" 2>&1 | tail -1 | sed 's/^/   /'; fi
[ -p "$L/a.pcm" ] || mkfifo "$L/a.pcm"
cd "$NEW" && RUN_DIR="$L" KL_LIVE=1 MODE=live SOURCE=compositor AUDIO_SOURCE="pipe:$L/a.pcm" nohup bash "$NEW/scripts/start.sh" > "$L/logs/start-$NAME.out" 2>&1
sed -E 's|sk_[A-Za-z0-9_-]+|sk_***|g' "$L/logs/start-$NAME.out" | grep -E 'started|REFUS|error' | sed 's/^/   /'
ln -sfn "$NEW" "$BASE/live-current"
until [ "$(awk -F= '$1=="frame"{f=$2} END{print f+0}' "$L/ffmpeg_progress.txt" 2>/dev/null)" -gt 150 ]; do sleep 3; [ $(( $(date +%s) - T0 )) -gt 180 ] && { echo "   encoder not up after 180 s"; tail -3 "$L/supervisor_events.jsonl"; exit 4; }; done
echo "   encoder up after $(( $(date +%s) - T0 )) s"

echo "== 5. verify"; for p in "$L"/pids/*.pid; do n=$(basename "$p" .pid); pid=$(cat "$p"); kill -0 "$pid" 2>/dev/null && printf '%s ✓  ' "$n" || printf '%s ✗  ' "$n"; done; echo
for n in relay compositor ffmpeg; do pid=$(cat "$L/pids/$n.pid" 2>/dev/null || echo 0); v=$(ps -E -o command= -p "$pid" 2>/dev/null | tr ' ' '\n' | grep -cE '^(STREAM_KEY|SRT_PASSPHRASE|KICK_CLIENT_SECRET|KICK_TOKEN|NGROK_AUTHTOKEN)=' || true); echo "   $n secrets in env: ${v:-0}"; done
RUN_DIR="$L" "$PYTHON" "$NEW/monitor/kick_api.py" --once 2>/dev/null | "$PYTHON" -c "import sys,json;d=json.load(sys.stdin);print('   kick is_live=%s viewers=%s title=%r' % (d.get('is_live'),d.get('viewer_count'),d.get('title')))"
RUN_DIR="$L" "$PYTHON" "$NEW/validate/hls_probe.py" --channel atleastonce --seconds 8 --out "$L/probe/swap-$NAME" 2>&1 | tail -1 | cut -c1-120 | sed 's/^/   /'
echo "done: $L/probe/swap-$NAME/last_frame.png"
