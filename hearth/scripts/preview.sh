#!/usr/bin/env bash
# Local mp4 of a scripted night. Does not touch Kick or kick-live.
# Picture from the compositor, crackle from ffmpeg. One pipe, no FIFO.
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/env.sh"
SECONDS_N="${1:-12}"
export RUN_DIR="${RUN_DIR:-$HOME/.local/share/hearth/run}"
mkdir -p "$RUN_DIR" "$LOG_DIR"
OUT="$RUN_DIR/preview.mp4"
FRAMES=$(( SECONDS_N * STREAM_FPS ))
export PYTHONPATH="$HEARTH_ROOT${PYTHONPATH:+:$PYTHONPATH}"
FIFO="$RUN_DIR/a.pcm"
rm -f "$FIFO"
mkfifo "$FIFO"
echo "preview: ${SECONDS_N}s -> $OUT"
"$PYTHON" -m hearth.compositor --run-dir "$RUN_DIR" --demo --frames "$FRAMES" --audio-fifo "$FIFO" \
  2>"$LOG_DIR/preview-compositor.log" | \
"$FFMPEG" -hide_banner -y -loglevel warning \
  -f rawvideo -pix_fmt rgb24 -s "${STREAM_WIDTH}x${STREAM_HEIGHT}" -r "$STREAM_FPS" -i pipe:0 \
  -f s16le -ar 48000 -ac 2 -i "$FIFO" \
  -c:v libx264 -pix_fmt yuv420p -preset veryfast -crf 18 \
  -c:a aac -b:a "$AUDIO_BITRATE" -shortest -t "$SECONDS_N" \
  "$OUT"
rm -f "$FIFO"
echo "preview: wrote $OUT"
ls -lh "$OUT"
