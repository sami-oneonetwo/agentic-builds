#!/usr/bin/env bash
# Common environment for every kick-live script. Source it; do not execute it.
#   source "$(dirname "$0")/env.sh"
# Resolves tool paths, loads secrets from OUTSIDE the repo, and defines runtime paths.

KICK_LIVE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export KICK_LIVE_ROOT

# --- secrets (outside the repo) -------------------------------------------
KICK_LIVE_ENV="${KICK_LIVE_ENV:-$HOME/.config/kick-live/env}"
if [ -f "$KICK_LIVE_ENV" ]; then
  set -a; . "$KICK_LIVE_ENV"; set +a
fi
export KICK_CHANNEL="${KICK_CHANNEL:-atleastonce}"
export KICK_CHATROOM_ID="${KICK_CHATROOM_ID:-41370704}"
export KICK_CHANNEL_ID="${KICK_CHANNEL_ID:-41659037}"

# --- tools -----------------------------------------------------------------
_pick() { for c in "$@"; do if [ -n "$c" ] && [ -x "$c" ]; then echo "$c"; return; fi; done; }
export FFMPEG="${FFMPEG:-$(_pick "$HOME/.local/bin/ffmpeg-static" /opt/homebrew/bin/ffmpeg "$(command -v ffmpeg)")}"
export FFPROBE="${FFPROBE:-$(_pick "$HOME/.local/bin/ffprobe-static" /opt/homebrew/bin/ffprobe "$(command -v ffprobe)")}"
export PYTHON="${PYTHON:-$(_pick "$HOME/.local/share/kick-live/venv/bin/python" "$(command -v python3)")}"
export PYTHONWARNINGS="${PYTHONWARNINGS:-ignore}"
export NGROK="${NGROK:-$(_pick "$HOME/.local/bin/ngrok" /opt/homebrew/bin/ngrok "$(command -v ngrok)")}"

# --- kick developer app + tunnel (kickapp/, scripts/kick-app.sh, scripts/tunnel.sh) ----
export KICK_APP_PORT="${KICK_APP_PORT:-8787}"                                        # local receiver port
export KICK_TOKENS_FILE="${KICK_TOKENS_FILE:-$HOME/.config/kick-live/tokens.json}"   # OAuth tokens, mode 600, outside repo

# --- runtime paths (gitignored) -------------------------------------------
export RUN_DIR="${RUN_DIR:-$KICK_LIVE_ROOT/run}"
mkdir -p "$RUN_DIR"
export METRICS_FILE="$RUN_DIR/metrics.jsonl"      # monitor/kick_api.py appends one JSON line per poll
export CHAT_FILE="$RUN_DIR/chat.jsonl"            # monitor/chat_listener.py appends one JSON line per message
export ACTIVITY_FILE="$RUN_DIR/activity.jsonl"    # anything may append {ts, actor, text} for the on-screen feed
export STATE_FILE="$RUN_DIR/state.json"           # compositor scene state (title, task, agenda, votes, answers)
export LOG_DIR="$RUN_DIR/logs"; mkdir -p "$LOG_DIR"
export PID_DIR="$RUN_DIR/pids"; mkdir -p "$PID_DIR"

# --- encode defaults --------------------------------------------------------
export STREAM_WIDTH="${STREAM_WIDTH:-1280}"
export STREAM_HEIGHT="${STREAM_HEIGHT:-720}"
export STREAM_FPS="${STREAM_FPS:-30}"
export VIDEO_BITRATE="${VIDEO_BITRATE:-3000k}"
export AUDIO_BITRATE="${AUDIO_BITRATE:-128k}"

kl_log() { printf '%s [%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${1:-kick-live}" "${*:2}"; }
kl_activity() { # kl_activity <actor> <text>
  printf '{"ts":"%s","actor":"%s","text":%s}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$(printf '%s' "${*:2}" | "$PYTHON" -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" >> "$ACTIVITY_FILE"
}
