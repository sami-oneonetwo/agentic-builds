#!/usr/bin/env bash
# ngrok tunnel to the local Kick app receiver.
#   scripts/tunnel.sh start|stop|restart|status|urls|logs
# Needs NGROK_AUTHTOKEN in ~/.config/kick-live/env. NGROK_DOMAIN (a reserved ngrok domain) is strongly
# recommended: without it the public URL changes on every restart and the redirect/webhook URLs
# registered on the Kick app stop matching.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

[ -n "${NGROK:-}" ] && [ -x "$NGROK" ] || NGROK="$(command -v ngrok || true)"
NGROK_API="${NGROK_API:-http://127.0.0.1:4040}"
PID_FILE="$PID_DIR/ngrok.pid"
URL_FILE="$RUN_DIR/public_url"
LOG_FILE="$LOG_DIR/ngrok.log"

_running() { [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; }

_public_url() {
  curl -fsS --max-time 2 "$NGROK_API/api/tunnels" 2>/dev/null \
    | "$PYTHON" -c 'import json,sys
for t in json.load(sys.stdin).get("tunnels",[]):
    u=t.get("public_url","")
    if u.startswith("https://"): print(u); break' 2>/dev/null || true
}

_print_urls() {
  local u="$1"
  echo "Public URL:    $u"
  echo "Redirect URL:  $u/oauth/callback     <- Kick app 'Redirect URL'"
  echo "Webhook URL:   $u/webhooks/kick      <- Kick app 'Webhook URL'"
}

cmd_start() {
  # Adopt an ngrok agent that is already running (e.g. started by hand) instead of launching a second one.
  local existing; existing="$(_public_url)"
  if [ -n "$existing" ] && ! _running; then
    echo "$existing" > "$URL_FILE"
    echo "adopting already-running ngrok (not managed by this script): $existing"
    _print_urls "$existing"; return 0
  fi
  [ -n "$NGROK" ] && [ -x "$NGROK" ] || { echo "ngrok not found. Expected $HOME/.local/bin/ngrok" >&2; exit 1; }
  if [ -z "${NGROK_AUTHTOKEN:-}" ]; then
    echo "NGROK_AUTHTOKEN is empty. Get it from https://dashboard.ngrok.com/get-started/your-authtoken" >&2
    echo "and add NGROK_AUTHTOKEN=... to $KICK_LIVE_ENV" >&2
    exit 1
  fi
  if _running; then
    echo "ngrok already running (pid $(cat "$PID_FILE"))"
  else
    local args=(http "127.0.0.1:${KICK_APP_PORT}" --log "$LOG_FILE" --log-format json --log-level info)
    [ -n "${NGROK_DOMAIN:-}" ] && args+=(--url "https://${NGROK_DOMAIN#https://}")
    # ngrok reads the authtoken from the NGROK_AUTHTOKEN env var; nothing is written into the repo.
    NGROK_AUTHTOKEN="$NGROK_AUTHTOKEN" nohup "$NGROK" "${args[@]}" >/dev/null 2>&1 &
    echo $! > "$PID_FILE"
    kl_log tunnel "started ngrok pid $! -> 127.0.0.1:${KICK_APP_PORT} ${NGROK_DOMAIN:+domain $NGROK_DOMAIN}"
  fi
  local u="" i
  for i in $(seq 1 30); do
    u="$(_public_url)"; [ -n "$u" ] && break
    if ! _running; then
      echo "ngrok exited. Last log lines:" >&2; tail -n 5 "$LOG_FILE" >&2 || true; rm -f "$PID_FILE"; exit 1
    fi
    sleep 0.5
  done
  [ -n "$u" ] || { echo "ngrok did not report a public URL within 15 s; see $LOG_FILE" >&2; exit 1; }
  echo "$u" > "$URL_FILE"
  if [ -z "${NGROK_DOMAIN:-}" ]; then
    echo "WARNING: NGROK_DOMAIN not set; this URL changes on every restart." >&2
    echo "         Reserve a free static domain at https://dashboard.ngrok.com/domains and put it in $KICK_LIVE_ENV" >&2
  fi
  _print_urls "$u"
}

cmd_stop() {
  if _running; then kill "$(cat "$PID_FILE")" && kl_log tunnel "stopped ngrok pid $(cat "$PID_FILE")"; fi
  rm -f "$PID_FILE"
}

cmd_status() {
  if _running; then
    local u; u="$(_public_url)"
    echo "ngrok: running (pid $(cat "$PID_FILE")), inspector $NGROK_API"
    if [ -n "$u" ]; then _print_urls "$u"; else echo "ngrok: no https tunnel reported yet"; fi
  else
    echo "ngrok: not running"; return 1
  fi
}

cmd_urls() {
  local u; u="$(_public_url)"; [ -n "$u" ] || u="$(cat "$URL_FILE" 2>/dev/null || true)"
  [ -n "$u" ] || { echo "no public URL known; run: scripts/tunnel.sh start" >&2; exit 1; }
  _print_urls "$u"
}

case "${1:-status}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_stop; cmd_start ;;
  status) cmd_status ;;
  urls) cmd_urls ;;
  logs) tail -n "${2:-50}" "$LOG_FILE" ;;
  *) echo "usage: $0 start|stop|restart|status|urls|logs" >&2; exit 2 ;;
esac
