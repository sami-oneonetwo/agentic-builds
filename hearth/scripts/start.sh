#!/usr/bin/env bash
# Start hearth locally (MODE=test) or to Kick (MODE=live).
#
# Hearth is a DIFFERENT stream from kick-live. Going live here will fight the
# other encoder for the same ingest key. Stop kick-live first.
#
#   MODE=test scripts/start.sh          # local HLS at $RUN_DIR/hls/index.m3u8
#   MODE=live scripts/start.sh --dry-run
#   MODE=live scripts/start.sh          # owner only
#
# Picture from the compositor. Crackle from ffmpeg. Chat is data in $CHAT_FILE.
# Daemonizes. pids in $PID_DIR. Stop with scripts/stop.sh.
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

pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }
pidfile_alive() { [ -f "$PID_DIR/$1.pid" ] && pid_alive "$(cat "$PID_DIR/$1.pid")"; }

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
BUSY=0
for n in run ffmpeg compositor; do
  if pidfile_alive "$n"; then echo "start.sh: $n already running (pid $(cat "$PID_DIR/$n.pid"))" >&2; BUSY=1; fi
done
if [ "$BUSY" = 1 ]; then echo "start.sh: refusing to start twice. Run scripts/stop.sh first." >&2; exit 1; fi

FIFO="$RUN_DIR/a.pcm"

ENC=(
  -f rawvideo -pix_fmt rgb24 -s "${STREAM_WIDTH}x${STREAM_HEIGHT}" -r "$STREAM_FPS" -i pipe:0
  -f s16le -ar 48000 -ac 2 -i "$FIFO"
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
  echo "$PYTHON -m hearth.compositor --run-dir $RUN_DIR --audio-fifo $FIFO |"
  echo "$FFMPEG ... $DESC"
  exit 0
fi

cd "$HEARTH_ROOT"
export PYTHONPATH="$HEARTH_ROOT${PYTHONPATH:+:$PYTHONPATH}"
touch "$CHAT_FILE"
: > "$LOG_DIR/compositor.log"
: > "$LOG_DIR/ffmpeg.log"
rm -f "$FIFO"
mkfifo "$FIFO"

# pipeline in its own process group so stop.sh can kill the tree
set +e
nohup env -u STREAM_KEY -u SRT_PASSPHRASE -u KICK_CLIENT_SECRET -u KICK_TOKEN \
  "$PYTHON" -m hearth.compositor --run-dir "$RUN_DIR" --audio-fifo "$FIFO" \
  2>>"$LOG_DIR/compositor.log" | \
"$FFMPEG" -hide_banner -nostdin -loglevel info "${ENC[@]}" "${OUT[@]}" \
  2>>"$LOG_DIR/ffmpeg.log" &
PIPE_PID=$!
set -e
echo "$PIPE_PID" > "$PID_DIR/run.pid"
sleep 1.5
# children of the pipeline
FF_PID=""; COMP_PID=""
for p in $(pgrep -P "$PIPE_PID" 2>/dev/null || true); do
  cmd=$(ps -p "$p" -o comm= 2>/dev/null || true)
  case "$cmd" in
    *ffmpeg*) FF_PID=$p ;;
    *python*) COMP_PID=$p ;;
  esac
done
# fallback: scan by command line
if [ -z "$FF_PID" ]; then
  FF_PID=$(pgrep -f "ffmpeg-static.*${STREAM_WIDTH}x${STREAM_HEIGHT}" | tail -1 || true)
fi
if [ -z "$COMP_PID" ]; then
  COMP_PID=$(pgrep -f "hearth.compositor" | tail -1 || true)
fi
[ -n "$FF_PID" ] && echo "$FF_PID" > "$PID_DIR/ffmpeg.pid"
[ -n "$COMP_PID" ] && echo "$COMP_PID" > "$PID_DIR/compositor.pid"

if ! pid_alive "$PIPE_PID"; then
  echo "start.sh: pipeline exited immediately" >&2
  tail -20 "$LOG_DIR/compositor.log" | sed 's/^/  compositor: /' >&2
  tail -20 "$LOG_DIR/ffmpeg.log" | sed 's/^/  ffmpeg: /' >&2
  rm -f "$PID_DIR/run.pid" "$PID_DIR/ffmpeg.pid" "$PID_DIR/compositor.pid"
  exit 1
fi

if command -v caffeinate >/dev/null && [ -n "$FF_PID" ]; then
  caffeinate -dimsu -w "$FF_PID" >/dev/null 2>&1 &
  echo $! > "$PID_DIR/caffeinate.pid"
fi

echo "start.sh: run pid=$PIPE_PID compositor=${COMP_PID:-?} ffmpeg=${FF_PID:-?} log=$LOG_DIR"
echo "start.sh: stop with scripts/stop.sh"
