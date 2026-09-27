#!/usr/bin/env bash
# Tail Kick chat into hearth's own chat.jsonl. Read-only on the socket. Does not send.
# Uses the kick-live listener script as a program, not as a library.
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/env.sh"
LISTENER=""
for c in \
  "$HEARTH_ROOT/../kick-live/monitor/chat_listener.py" \
  "$HOME/Workspace/agentic-builds/kick-live/monitor/chat_listener.py"
 do
  [ -f "$c" ] && LISTENER="$c" && break
done
if [ -z "$LISTENER" ]; then
  echo "listen.sh: chat_listener.py not found next to hearth" >&2
  exit 4
fi
mkdir -p "$(dirname "$CHAT_FILE")" "$LOG_DIR"
echo "listen.sh: $LISTENER -> $CHAT_FILE chatroom=$KICK_CHATROOM_ID"
export CHAT_FILE RUN_DIR
exec "$PYTHON" "$LISTENER"
