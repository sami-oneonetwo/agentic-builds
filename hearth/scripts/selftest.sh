#!/usr/bin/env bash
# Render a packed night to PNGs and run the sim tests. Nothing goes to Kick.
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/env.sh"
OUT="${1:-/tmp/hearth-selftest}"
rm -rf "$OUT"
mkdir -p "$OUT"
export RUN_DIR="$OUT"
export CHAT_FILE="$OUT/chat.jsonl"
unset STATE_FILE ACTIVITY_FILE METRICS_FILE
echo "selftest: sim"
"$PYTHON" "$HEARTH_ROOT/hearth/tests/test_sim.py"
echo "selftest: frames -> $OUT/selftest"
"$PYTHON" -m hearth.compositor --self-test 180 --run-dir "$OUT" --no-audio
echo "selftest: refuse kick-live run dir"
if "$PYTHON" -m hearth.compositor --self-test 2 --run-dir "$HOME/.local/share/kick-live/run-live" --no-audio; then
  echo "selftest: FAIL: compositor did not refuse kick-live run-live" >&2
  exit 1
fi
echo "selftest: ok  pngs in $OUT/selftest  meta:"
cat "$OUT/selftest/meta.json"
