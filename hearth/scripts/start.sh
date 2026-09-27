#!/usr/bin/env bash
# Start hearth locally (MODE=test) or, if you really mean it, to Kick (MODE=live).
#
# Hearth is a DIFFERENT stream from kick-live. Going live here will fight the
# other encoder for the same ingest key. Stop kick-live first.
#
#   MODE=test scripts/start.sh          # local HLS at $RUN_DIR/hls/index.m3u8
#   MODE=live scripts/start.sh --dry-run
#   MODE=live scripts/start.sh          # owner only
#
# Picture from the compositor. Crackle from ffmpeg. Chat is data in $CHAT_FILE.
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/env.sh"

DRY=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "start.sh: unknown option $a" >&2; exit 2 ;;
  esac
done
MODE="${MODE:-test}"
RTMPS_URL="${RTMPS_URL:-rtmps://fa723fc1b171.global-contribute.live-video.net:443/app/}"
STREAM_KEY="${STREAM_KEY:-}"
mkdir -p "$RUN_DIR/hls" "$LOG_DIR" "$PID_DIR"

if [ "$MODE" = live ] && [ -z "$STREAM_KEY" ]; then
  echo "start.sh: MODE=live but STREAM_KEY is empty" >&2
  exit 3
fi
if [ "$MODE" = live ]; then
  OTHER="$HOME/.local/share/kick-live/run-live/pids/ffmpeg.pid"
  if [ -f "$OTHER" ] && kill -0 "$(cat "$OTHER")" 2>/dev/null; then
    echo "start.sh: REFUSING MODE=live while kick-live ffmpeg pid $(cat "$OTHER") is alive." >&2
    echo "          stop that stream first. hearth will not share the encoder." >&2
    exit 4
  fi
fi

ENC=(
  -f rawvideo -pix_fmt rgb24 -s "${STREAM_WIDTH}x${STREAM_HEIGHT}" -r "$STREAM_FPS" -i pipe:0
  -f lavfi -i "anoisesrc=color=brown:sample_rate=48000:amplitude=0.03,volume=-22dB,aformat=channel_layouts=stereo"
  -map 0:v:0 -map 1:a:0
  -c:v libx264 -preset veryfast -tune zerolatency -profile:v high -pix_fmt yuv420p
  -b:v "$VIDEO_BITRATE" -maxrate "$VIDEO_BITRATE" -g $((STREAM_FPS * 2))
  -c:a aac -b:a "$AUDIO_BITRATE" -ar 48000 -ac 2
)
OUT=(); DESC=""
case "$MODE" in
  test)
    OUT=(-f hls -hls_time 2 -hls_list_size 6 -hls_flags delete_segments
         -hls_segment_filename "$RUN_DIR/hls/seg_%05d.ts" "$RUN_DIR/hls/index.m3u8")
    DESC="$RUN_DIR/hls/index.m3u8" ;;
  live)
    TLS_CA="${TLS_CA_FILE:-/etc/ssl/cert.pem}"
    [ -r "$TLS_CA" ] && OUT+=(-ca_file "$TLS_CA" -tls_verify 1)
    OUT+=(-f flv "${RTMPS_URL}${STREAM_KEY}")
    DESC="${RTMPS_URL}***" ;;
  *) echo "start.sh: MODE must be test|live" >&2; exit 2 ;;
esac

echo "start.sh: MODE=$MODE out=$DESC run_dir=$RUN_DIR chat=$CHAT_FILE"
if [ "$DRY" = 1 ]; then
  echo "$PYTHON -m hearth.compositor --run-dir $RUN_DIR --no-audio |"
  echo "$FFMPEG ... $DESC"
  exit 0
fi

cd "$HEARTH_ROOT"
export PYTHONPATH="$HEARTH_ROOT${PYTHONPATH:+:$PYTHONPATH}"
touch "$CHAT_FILE"
env -u STREAM_KEY -u SRT_PASSPHRASE -u KICK_CLIENT_SECRET -u KICK_TOKEN \
  "$PYTHON" -m hearth.compositor --run-dir "$RUN_DIR" --no-audio \
  2>>"$LOG_DIR/compositor.log" | \
"$FFMPEG" -hide_banner -nostdin -loglevel info "${ENC[@]}" "${OUT[@]}" \
  2>>"$LOG_DIR/ffmpeg.log"
