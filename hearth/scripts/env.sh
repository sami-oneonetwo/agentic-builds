#!/usr/bin/env bash
# Common environment for hearth. Source it; do not execute it.
# Separate from kick-live. Never points RUN_DIR at ~/.local/share/kick-live/*.

if [ -n "${BASH_SOURCE[0]:-}" ]; then __src="${BASH_SOURCE[0]}"
elif [ -n "${ZSH_VERSION:-}" ]; then eval '__src="${(%):-%x}"'
else __src="$0"; fi
HEARTH_ROOT="${HEARTH_ROOT:-$(cd "$(dirname "$__src")/.." && pwd)}"
unset __src
if [ ! -f "$HEARTH_ROOT/scripts/env.sh" ]; then
  echo "env.sh: HEARTH_ROOT=$HEARTH_ROOT does not contain scripts/env.sh" >&2
  return 1 2>/dev/null || exit 1
fi
export HEARTH_ROOT

# STREAM_KEY and Kick ids live in the existing secrets file. We take those
# defaults, then restore any pre-set vars so a CLI RUN_DIR always wins.
KICK_LIVE_ENV="${KICK_LIVE_ENV:-$HOME/.config/kick-live/env}"
if [ -f "$KICK_LIVE_ENV" ]; then
  __pre="$(export -p)"
  set -a; . "$KICK_LIVE_ENV"; set +a
  eval "$__pre"
  unset __pre
fi
export KICK_CHANNEL="${KICK_CHANNEL:-atleastonce}"
export KICK_CHATROOM_ID="${KICK_CHATROOM_ID:-41370704}"
export KICK_CHANNEL_ID="${KICK_CHANNEL_ID:-41659037}"

# kick-live's secrets file also exports RUN_DIR / CHAT_FILE. those are the other stream.
# drop them unless the caller set them on the command line (already restored above).
for __v in RUN_DIR CHAT_FILE STATE_FILE ACTIVITY_FILE METRICS_FILE PID_DIR LOG_DIR; do
  eval "__val=\${$__v:-}"
  case "$__val" in
    *kick-live*) unset "$__v" ;;
  esac
done
unset __v __val

_pick() { for c in "$@"; do if [ -n "$c" ] && [ -x "$c" ]; then echo "$c"; return; fi; done; }
export FFMPEG="${FFMPEG:-$(_pick "$HOME/.local/bin/ffmpeg-static" /opt/homebrew/bin/ffmpeg "$(command -v ffmpeg)")}"
export PYTHON="${PYTHON:-$(_pick "$HOME/.local/share/kick-live/venv/bin/python" "$(command -v python3)")}"
export PYTHONWARNINGS="${PYTHONWARNINGS:-ignore}"
export SSL_CERT_FILE="${SSL_CERT_FILE:-/etc/ssl/cert.pem}"

# hearth's own runtime. never the kick-live live dir.
export RUN_DIR="${RUN_DIR:-$HOME/.local/share/hearth/run}"
case "$(cd "$RUN_DIR" 2>/dev/null && pwd -P || echo "$RUN_DIR")" in
  *kick-live*) echo "env.sh: REFUSING RUN_DIR=$RUN_DIR (kick-live). unset RUN_DIR." >&2; return 1 2>/dev/null || exit 1 ;;
esac
mkdir -p "$RUN_DIR"
export CHAT_FILE="${CHAT_FILE:-$RUN_DIR/chat.jsonl}"
export LOG_DIR="$RUN_DIR/logs"; mkdir -p "$LOG_DIR"
export PID_DIR="$RUN_DIR/pids"; mkdir -p "$PID_DIR"

export STREAM_WIDTH="${STREAM_WIDTH:-1280}"
export STREAM_HEIGHT="${STREAM_HEIGHT:-720}"
export STREAM_FPS="${STREAM_FPS:-30}"
export VIDEO_BITRATE="${VIDEO_BITRATE:-3000k}"
export AUDIO_BITRATE="${AUDIO_BITRATE:-128k}"
export RTMPS_URL="${RTMPS_URL:-rtmps://fa723fc1b171.global-contribute.live-video.net:443/app/}"

export PYTHONPATH="$HEARTH_ROOT${PYTHONPATH:+:$PYTHONPATH}"
