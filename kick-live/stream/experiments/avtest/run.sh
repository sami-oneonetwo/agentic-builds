#!/usr/bin/env bash
set -u
T=/tmp/kl-avtest
PY="$HOME/.local/share/kick-live/venv/bin/python"; FF="$HOME/.local/bin/ffmpeg-static"; FP="$HOME/.local/bin/ffprobe-static"
[ -x "$FF" ] || FF=$(command -v ffmpeg); [ -x "$FP" ] || FP=$(command -v ffprobe)
mkfifo "$T/v.raw" "$T/a.pcm"
"$PY" "$T/gen.py" "$T/v.raw" "$T/a.pcm" 2>"$T/gen.log" &
GEN=$!
"$FF" -hide_banner -loglevel info -nostats -y \
  -thread_queue_size 1024 -probesize 32 -analyzeduration 0 -f rawvideo -pix_fmt rgb24 -s 1280x720 -r 30 -i "$T/v.raw" \
  -thread_queue_size 1024 -f s16le -ar 48000 -ac 2 -i "$T/a.pcm" \
  -map 0:v -map 1:a -c:v h264_videotoolbox -b:v 3000k -maxrate 3000k -bufsize 6000k -g 60 -pix_fmt yuv420p \
  -c:a aac -b:a 128k -ar 48000 -f flv "$T/test.flv" 2>"$T/ff.log"
echo "ffmpeg exit $?"
wait $GEN; echo "gen exit $?"
echo "--- gen.log"; cat "$T/gen.log"
echo "--- ff.log (tail)"; tail -15 "$T/ff.log"
echo "--- probe"; "$FP" -v error -show_entries stream=codec_type,codec_name:format=duration,size,bit_rate -of compact "$T/test.flv"
"$FP" -v error -count_frames -select_streams v -show_entries stream=nb_read_frames -of compact "$T/test.flv"
