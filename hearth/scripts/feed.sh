#!/usr/bin/env bash
# Append a chat line to hearth's own chat.jsonl. For a running preview/loop, not Kick.
# Usage: scripts/feed.sh [name] [words...]
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/env.sh"
NAME="${1:-you}"
shift || true
TEXT="${*:-hey}"
mkdir -p "$(dirname "$CHAT_FILE")"
TS="$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
ID="feed-$RANDOM-$RANDOM"
# tiny python so the JSON is valid even if TEXT has quotes
"$PYTHON" - "$CHAT_FILE" "$NAME" "$TEXT" "$TS" "$ID" <<'PY'
import json, sys, hashlib
path, name, text, ts, mid = sys.argv[1:]
color = "#%06x" % (int(hashlib.sha256(name.encode()).hexdigest()[:6], 16) & 0xFFFFFF)
rec = {"ts": ts, "id": mid, "username": name, "slug": name.lower(),
       "content": text, "color": "#"+format(int(hashlib.sha256(name.encode()).hexdigest()[:6],16),"06x"),
       "type": "message", "badges": []}
with open(path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
print("fed", name, repr(text), "->", path)
PY
