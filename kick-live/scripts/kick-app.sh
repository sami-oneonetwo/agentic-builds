#!/usr/bin/env bash
# One command for the Kick developer-app plumbing: local receiver + ngrok tunnel.
#   scripts/kick-app.sh up        start receiver on $KICK_APP_PORT and the tunnel, print the URLs to register
#   scripts/kick-app.sh down      stop both
#   scripts/kick-app.sh status    processes, URLs, token state
#   scripts/kick-app.sh urls      redirect + webhook URLs only
#   scripts/kick-app.sh login [scope ...]   open the browser to authorize the channel account (PKCE)
#   scripts/kick-app.sh logs      tail receiver log
#   scripts/kick-app.sh kick ...  passthrough to kickapp/kick_oauth.py (status|whoami|subscribe|...)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/env.sh"
PID_FILE="$PID_DIR/kickapp.pid"
LOG_FILE="$LOG_DIR/kickapp.log"
SERVER="$KICK_LIVE_ROOT/kickapp/server.py"
KO="$KICK_LIVE_ROOT/kickapp/kick_oauth.py"

_running() { [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; }

server_start() {
  if _running; then echo "receiver: already running (pid $(cat "$PID_FILE"))"; return; fi
  nohup "$PYTHON" "$SERVER" >>"$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  local i; for i in $(seq 1 20); do
    curl -fsS --max-time 1 "http://127.0.0.1:${KICK_APP_PORT}/health" >/dev/null 2>&1 && break
    kill -0 "$(cat "$PID_FILE")" 2>/dev/null || { echo "receiver died; see $LOG_FILE" >&2; tail -n 20 "$LOG_FILE" >&2; exit 1; }
    sleep 0.25
  done
  kl_log kick-app "receiver started pid $(cat "$PID_FILE") on 127.0.0.1:${KICK_APP_PORT}"
  echo "receiver: http://127.0.0.1:${KICK_APP_PORT} (pid $(cat "$PID_FILE"))"
}

server_stop() {
  if _running; then kill "$(cat "$PID_FILE")" && kl_log kick-app "receiver stopped"; fi
  rm -f "$PID_FILE"
}

case "${1:-status}" in
  up) server_start; "$HERE/tunnel.sh" start ;;
  down) "$HERE/tunnel.sh" stop; server_stop ;;
  status)
    if _running; then echo "receiver: running (pid $(cat "$PID_FILE")) on 127.0.0.1:${KICK_APP_PORT}"; else echo "receiver: not running"; fi
    "$HERE/tunnel.sh" status || true
    "$PYTHON" "$KO" status ;;
  urls) "$HERE/tunnel.sh" urls ;;
  login)
    shift; url="$("$PYTHON" "$KO" login-url "$@")"
    echo "Open this in a browser logged into the Kick account that owns the channel:"; echo "  $url"
    if command -v open >/dev/null; then open "$url"; fi ;;
  logs) tail -n "${2:-50}" "$LOG_FILE" ;;
  kick) shift; exec "$PYTHON" "$KO" "$@" ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
