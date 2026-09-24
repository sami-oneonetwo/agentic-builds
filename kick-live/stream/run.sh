#!/usr/bin/env bash
# stream/run.sh — runs exactly ONE ffmpeg encoder. Video + generated/piped audio -> RTMPS | HLS | FLV file.
#
# Usage: stream/run.sh [--dry-run] [--help]
#   --dry-run   print the (key-masked) ffmpeg command line and exit 0 without encoding
#
# Environment (all optional except STREAM_KEY in live mode; defaults come from scripts/env.sh):
#   MODE=live|test|file        live -> -f flv "$RTMPS_URL$STREAM_KEY"   (exit 3 if STREAM_KEY is empty)
#                              test -> HLS at $RUN_DIR/hls/index.m3u8, prints progress every 5 s
#                              file -> $RUN_DIR/out.flv                  (default: live)
#   SOURCE=compositor|testsrc  compositor -> $PYTHON stream/compositor.py | rawvideo rgb24 on stdin
#                              testsrc    -> lavfi colour bars + channel name + UTC clock (default: compositor)
#   AUDIO_SOURCE=generated|pipe:<fifo>|silence
#                              generated -> low-level ambient tone bed, about -18 dBFS peak (default)
#                              pipe:PATH -> s16le 48 kHz stereo read from a FIFO
#   DURATION=<seconds>         adds -t (stop after N seconds)
#   STREAM_WIDTH/HEIGHT/FPS, VIDEO_BITRATE, AUDIO_BITRATE, RTMPS_URL, STREAM_KEY, KICK_CHANNEL
#
# Files: $LOG_DIR/ffmpeg.log (stderr, stream key masked), $LOG_DIR/compositor.log,
#        $RUN_DIR/ffmpeg_progress.txt (-progress, machine readable), $PID_DIR/ffmpeg.pid, $PID_DIR/compositor.pid
# Exit codes: 0 ok / ffmpeg exit code, 2 usage, 3 refused (live without STREAM_KEY), 4 missing input program/file
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../scripts/env.sh"
source "$KICK_LIVE_ROOT/stream/testsrc.sh"

DRY_RUN=0
for a in "$@"; do
  case "$a" in
    -h|--help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --dry-run) DRY_RUN=1 ;;
    *) echo "run.sh: unknown option '$a' (try --help)" >&2; exit 2 ;;
  esac
done

MODE="${MODE:-live}"
SOURCE="${SOURCE:-compositor}"
AUDIO_SOURCE="${AUDIO_SOURCE:-generated}"
DURATION="${DURATION:-}"
RTMPS_URL="${RTMPS_URL:-rtmps://fa723fc1b171.global-contribute.live-video.net:443/app/}"
STREAM_KEY="${STREAM_KEY:-}"
FFLOG="$LOG_DIR/ffmpeg.log"
PROGRESS="$RUN_DIR/ffmpeg_progress.txt"
TAG="run.sh"

log() { kl_log "$TAG" "$@"; }

# --- refuse early ----------------------------------------------------------
case "$MODE" in live|test|file) ;; *) echo "run.sh: MODE must be live|test|file (got '$MODE')" >&2; exit 2 ;; esac
case "$SOURCE" in compositor|testsrc) ;; *) echo "run.sh: SOURCE must be compositor|testsrc (got '$SOURCE')" >&2; exit 2 ;; esac
if [ "$MODE" = live ] && [ -z "$STREAM_KEY" ]; then
  echo "run.sh: REFUSING to start: MODE=live but STREAM_KEY is empty." >&2
  echo "        Fill STREAM_KEY in ${KICK_LIVE_ENV:-$HOME/.config/kick-live/env} (mode 600), or use MODE=test / MODE=file." >&2
  exit 3
fi
COMPOSITOR="$KICK_LIVE_ROOT/stream/compositor.py"
if [ "$SOURCE" = compositor ] && [ ! -f "$COMPOSITOR" ]; then
  echo "run.sh: SOURCE=compositor but $COMPOSITOR does not exist (use SOURCE=testsrc until it is built)" >&2
  exit 4
fi
if [ "$SOURCE" = compositor ] && [ ! -x "$PYTHON" ]; then
  echo "run.sh: SOURCE=compositor but python not found (PYTHON='$PYTHON')" >&2
  exit 4
fi
if [ -x "$FFMPEG" ]; then :; else echo "run.sh: ffmpeg not found (FFMPEG='$FFMPEG')" >&2; exit 4; fi

# --- inputs ------------------------------------------------------------------
GOP=$((STREAM_FPS * 2))
V_IN=(); V_FILTER=""
case "$SOURCE" in
  compositor)
    V_IN=(-thread_queue_size 64 -f rawvideo -pix_fmt rgb24 -s "${STREAM_WIDTH}x${STREAM_HEIGHT}" -r "$STREAM_FPS" -i pipe:0)
    V_FILTER="format=yuv420p" ;;
  testsrc)
    V_IN=(-re -f lavfi -i "$(kl_testsrc_input)")
    V_FILTER="$(kl_testsrc_filter)" ;;
esac

A_IN=()
case "$AUDIO_SOURCE" in
  generated)
    # Four detuned partials (A2, E3, A3, E4) with slow independent LFOs, low-passed, -18 dB.
    # Measured: mean -25 dBFS, peak -16.4 dBFS.
    L='0.55*sin(2*PI*110*t)*(0.6+0.4*sin(2*PI*0.05*t))+0.35*sin(2*PI*164.81*t)*(0.6+0.4*sin(2*PI*0.031*t+1.3))+0.25*sin(2*PI*220*t)*(0.5+0.5*sin(2*PI*0.017*t))+0.15*sin(2*PI*329.63*t)*(0.5+0.5*sin(2*PI*0.023*t+2.1))'
    R='0.55*sin(2*PI*110.3*t)*(0.6+0.4*sin(2*PI*0.05*t+0.7))+0.35*sin(2*PI*165.1*t)*(0.6+0.4*sin(2*PI*0.031*t))+0.25*sin(2*PI*220.4*t)*(0.5+0.5*sin(2*PI*0.017*t+0.9))+0.15*sin(2*PI*330*t)*(0.5+0.5*sin(2*PI*0.023*t))'
    A_IN=(-re -f lavfi -i "aevalsrc=exprs='${L}|${R}':s=48000:c=stereo,lowpass=f=1800,volume=-18dB") ;;
  silence)
    A_IN=(-re -f lavfi -i "anullsrc=r=48000:cl=stereo") ;;
  pipe:*)
    FIFO="${AUDIO_SOURCE#pipe:}"
    if [ ! -p "$FIFO" ]; then echo "run.sh: AUDIO_SOURCE=$AUDIO_SOURCE but '$FIFO' is not a FIFO" >&2; exit 4; fi
    A_IN=(-thread_queue_size 1024 -f s16le -ar 48000 -ac 2 -i "$FIFO") ;;
  *) echo "run.sh: AUDIO_SOURCE must be generated|silence|pipe:<fifo> (got '$AUDIO_SOURCE')" >&2; exit 2 ;;
esac

# --- encode -------------------------------------------------------------------
kbps_x2() { # "3000k" -> "6000k", "3M" -> "6000k", "3000000" -> "6000000"
  local v="$1"
  case "$v" in
    *[kK]) echo "$(( ${v%[kK]} * 2 ))k" ;;
    *[mM]) echo "$(( ${v%[mM]} * 2000 ))k" ;;
    *) echo "$(( v * 2 ))" ;;
  esac
}
ENC=(
  -map 0:v:0 -map 1:a:0
  -vf "$V_FILTER"
  -c:v libx264 -preset veryfast -tune zerolatency -profile:v high -pix_fmt yuv420p
  -b:v "$VIDEO_BITRATE" -maxrate "$VIDEO_BITRATE" -bufsize "$(kbps_x2 "$VIDEO_BITRATE")"
  -g "$GOP" -keyint_min "$GOP" -sc_threshold 0 -x264-params "nal-hrd=cbr"
  -fps_mode cfr -r "$STREAM_FPS"
  -c:a aac -b:a "$AUDIO_BITRATE" -ar 48000 -ac 2
  -shortest    # if the compositor (or an audio FIFO writer) dies, its input hits EOF and ffmpeg must END so the
               # supervisor restarts it; without this ffmpeg keeps muxing the infinite lavfi audio with a frozen picture
)
[ -n "$DURATION" ] && ENC+=(-t "$DURATION")

OUT=(); OUT_DESC=""
case "$MODE" in
  live)
    # Static ffmpeg builds have no CA path on macOS; point OpenSSL at the system bundle and verify.
    TLS_CA="${TLS_CA_FILE:-/etc/ssl/cert.pem}"
    OUT=(); [ -r "$TLS_CA" ] && OUT+=(-ca_file "$TLS_CA" -tls_verify 1)
    OUT+=(-f flv "${RTMPS_URL}${STREAM_KEY}"); OUT_DESC="${RTMPS_URL}***" ;;
  test)
    mkdir -p "${RUN_DIR:?}/hls"; rm -f "${RUN_DIR:?}/hls/"*.ts "${RUN_DIR:?}/hls/"*.m3u8 2>/dev/null || true
    OUT=(-f hls -hls_time 2 -hls_list_size 6 -hls_flags delete_segments+program_date_time
         -hls_segment_filename "$RUN_DIR/hls/seg_%05d.ts" "$RUN_DIR/hls/index.m3u8")
    OUT_DESC="$RUN_DIR/hls/index.m3u8" ;;
  file) OUT=(-y -f flv "$RUN_DIR/out.flv"); OUT_DESC="$RUN_DIR/out.flv" ;;
esac

CMD=("$FFMPEG" -hide_banner -nostdin -loglevel info -nostats -stats_period 5 -progress "$PROGRESS"
     "${V_IN[@]}" "${A_IN[@]}" "${ENC[@]}" "${OUT[@]}")

# Key masking. Pure bash on purpose: an external `sed "s|$KEY|***|"` would put the key into that
# process's argv, visible to every user in `ps`. The quoted pattern makes the match literal (no globbing).
mask_str() { local s="$1"; if [ -n "$STREAM_KEY" ]; then s="${s//"$STREAM_KEY"/***}"; fi; printf '%s' "$s"; }
masked_cmd() { # printable ffmpeg command line, key replaced BEFORE %q so an odd key cannot dodge the mask
  local a out=""
  for a in "${CMD[@]}"; do out+="$(printf '%q' "$(mask_str "$a")") "; done
  printf '%s\n' "$out"
}
mask_stream() { # stdin -> stdout with the key replaced, line by line, unbuffered
  local line
  while IFS= read -r line || [ -n "$line" ]; do printf '%s\n' "$(mask_str "$line")"; done
}

log "mode=$MODE source=$SOURCE audio=$AUDIO_SOURCE size=${STREAM_WIDTH}x${STREAM_HEIGHT}@${STREAM_FPS} v=$VIDEO_BITRATE a=$AUDIO_BITRATE gop=$GOP out=$OUT_DESC${DURATION:+ duration=${DURATION}s}"
if [ "$DRY_RUN" = 1 ]; then
  [ "$SOURCE" = compositor ] && echo "$PYTHON $COMPOSITOR |"
  masked_cmd; exit 0
fi

# --- run ------------------------------------------------------------------------
: > "$PROGRESS"
{ echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) run.sh start mode=$MODE source=$SOURCE out=$OUT_DESC"; masked_cmd; } >> "$FFLOG"

FF_PID=""; COMP_PID=""; PRINTER_PID=""
cleanup() {
  trap - TERM INT EXIT
  [ -n "$PRINTER_PID" ] && kill "$PRINTER_PID" 2>/dev/null || true
  for p in $FF_PID $COMP_PID; do kill -TERM "$p" 2>/dev/null || true; done
  # give ffmpeg a moment to flush the muxer, then be firm
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    alive=0; for p in $FF_PID $COMP_PID; do kill -0 "$p" 2>/dev/null && alive=1; done
    [ "$alive" = 0 ] && break; sleep 0.5
  done
  for p in $FF_PID $COMP_PID; do kill -KILL "$p" 2>/dev/null || true; done
  rm -f "${PID_DIR:?}/ffmpeg.pid" "${PID_DIR:?}/compositor.pid"
}
on_term() { log "signal received, stopping ffmpeg${COMP_PID:+ and compositor}"; cleanup; exit 143; }
trap on_term TERM INT
trap cleanup EXIT

if [ "$SOURCE" = compositor ]; then
  "$PYTHON" "$COMPOSITOR" 2>> "$LOG_DIR/compositor.log" | "${CMD[@]}" 2> >(trap "" TERM INT; mask_stream >> "$FFLOG") &
  FF_PID=$!
  # `wait $FF_PID` reports the PIPELINE status and bash applies pipefail when the job is reaped: the compositor
  # always dies of SIGPIPE/BrokenPipe when ffmpeg stops first, which would turn ffmpeg's rc=0 into 1. We want
  # ffmpeg's own exit code, so pipefail is off from here on (nothing below relies on it).
  set +o pipefail
  # bash: `jobs -p` yields the process-group leader of the job = first pipeline member = compositor
  sleep 0.2; COMP_PID="$(jobs -p | head -1 || true)"
  [ -n "$COMP_PID" ] && echo "$COMP_PID" > "$PID_DIR/compositor.pid"
else
  "${CMD[@]}" 2> >(trap "" TERM INT; mask_stream >> "$FFLOG") &
  FF_PID=$!
fi
echo "$FF_PID" > "$PID_DIR/ffmpeg.pid"
log "ffmpeg pid=$FF_PID${COMP_PID:+ compositor pid=$COMP_PID} log=$FFLOG progress=$PROGRESS"

# MODE=test: print a one-line progress summary every 5 s from the -progress file.
if [ "$MODE" = test ]; then
  (
    while kill -0 "$FF_PID" 2>/dev/null; do
      sleep 5
      if [ -s "$PROGRESS" ]; then
        # last block: take the final value of each key
        awk -F= '{v[$1]=$2} END{printf "progress frame=%s fps=%s bitrate=%s out_time=%s drop=%s dup=%s speed=%s\n", v["frame"], v["fps"], v["bitrate"], v["out_time"], v["drop_frames"], v["dup_frames"], v["speed"]}' "$PROGRESS"
      fi
    done
  ) &
  PRINTER_PID=$!
  disown "$PRINTER_PID" 2>/dev/null || true   # no "Terminated" job notice when we kill it
fi

# Wait for ffmpeg. In compositor mode also watch the compositor: if it dies while ffmpeg is still up
# (belt and braces next to -shortest), stop ffmpeg so the exit propagates to the supervisor.
if [ -n "$COMP_PID" ]; then
  while kill -0 "$FF_PID" 2>/dev/null; do
    if ! kill -0 "$COMP_PID" 2>/dev/null; then
      log "compositor pid=$COMP_PID died while ffmpeg pid=$FF_PID is running; stopping ffmpeg"
      echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) run.sh compositor died, stopping ffmpeg" >> "$FFLOG"
      sleep 3                                  # let -shortest flush the last frames first
      kill -TERM "$FF_PID" 2>/dev/null || true
      break
    fi
    sleep 1
  done
fi
set +e
wait "$FF_PID"; RC=$?
set -e
[ -n "$PRINTER_PID" ] && { kill "$PRINTER_PID" 2>/dev/null || true; PRINTER_PID=""; }
if [ -n "$COMP_PID" ]; then kill -TERM "$COMP_PID" 2>/dev/null || true; fi
echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) run.sh ffmpeg exited rc=$RC" >> "$FFLOG"
log "ffmpeg exited rc=$RC"
exit "$RC"
