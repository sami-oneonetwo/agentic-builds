#!/usr/bin/env bash
# scripts/test_local.sh — offline end-to-end check: run.sh in MODE=test SOURCE=testsrc for DURATION s,
# then probe the HLS output and assert h264 1280x720 + aac, count segments, run validate/hls_probe.py --local.
#
# Usage: scripts/test_local.sh [--duration N] [--help]      (default 25 s; nothing touches Kick ingest)
# Exit 0 = all checks passed, 1 = a check failed, other = run.sh failure code.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

DUR=25
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --duration)
      DUR="${2:-}"
      case "$DUR" in ''|*[!0-9]*|0) echo "test_local.sh: --duration needs a positive integer number of seconds (got '${DUR}')" >&2; exit 2 ;; esac
      shift ;;
    *) echo "test_local.sh: unknown option '$1' (try --help)" >&2; exit 2 ;;
  esac
  shift
done
export MODE=test SOURCE=testsrc DURATION="$DUR"
HLS="${RUN_DIR:?}/hls"; PL="$HLS/index.m3u8"
FAIL=0
ok()   { echo "  PASS  $*"; }
bad()  { echo "  FAIL  $*"; FAIL=1; }

echo "test_local.sh: MODE=$MODE SOURCE=$SOURCE DURATION=${DUR}s -> $PL"
if [ -f "$PID_DIR/ffmpeg.pid" ] && kill -0 "$(cat "$PID_DIR/ffmpeg.pid")" 2>/dev/null; then
  echo "test_local.sh: an ffmpeg from this repo is already running (pid $(cat "$PID_DIR/ffmpeg.pid")); stop it first." >&2; exit 1
fi
rm -rf "${RUN_DIR:?}/hls"; mkdir -p "$HLS"

echo "--- running stream/run.sh (waits ~${DUR}s, progress every 5 s)"
T0=$(date +%s)
set +e; "$KICK_LIVE_ROOT/stream/run.sh"; RC=$?; set -e
T1=$(date +%s)
echo "--- run.sh exited rc=$RC after $((T1 - T0))s"
if [ "$RC" != 0 ]; then echo "test_local.sh: run.sh failed (rc=$RC); tail of ffmpeg.log:"; tail -15 "$LOG_DIR/ffmpeg.log"; exit "$RC"; fi

echo "--- ffprobe $PL"
if [ ! -s "$PL" ]; then bad "playlist missing: $PL"; echo "test_local.sh: FAILED"; exit 1; fi
PROBE_RC=0
PROBE="$("$FFPROBE" -v error -show_entries stream=codec_type,codec_name,width,height,pix_fmt,profile,sample_rate,channels,r_frame_rate -of default=nw=1 "$PL" 2>&1)" || PROBE_RC=$?
echo "$PROBE" | sed 's/^/  /'
if [ "$PROBE_RC" != 0 ]; then bad "ffprobe exited $PROBE_RC on $PL"; fi
chk() { if echo "$PROBE" | grep -q "^$1\$"; then ok "$2"; else bad "$3"; fi; }
chk 'codec_name=h264'   "video codec h264"  "video codec is not h264"
chk 'width=1280'        "video width 1280"  "video width is not 1280"
chk 'height=720'        "video height 720"  "video height is not 720"
chk 'codec_name=aac'    "audio codec aac"   "audio codec is not aac"
chk 'sample_rate=48000' "audio 48000 Hz"    "audio is not 48 kHz"
chk 'channels=2'        "audio stereo"      "audio is not stereo"
chk 'pix_fmt=yuv420p'   "pix_fmt yuv420p"   "pix_fmt is not yuv420p"

echo "--- segments"
NSEG=$(find "$HLS" -maxdepth 1 -name '*.ts' 2>/dev/null | wc -l | tr -d ' ')   # not `ls *.ts`: with zero files that fails under set -e/pipefail
NPL=$(grep -c '^#EXTINF' "$PL" || true)
echo "  segment files on disk: $NSEG   entries in playlist: $NPL   (hls_list_size 6 + delete_segments -> ~6-8 files expected)"
if [ "$NSEG" -ge 3 ]; then ok "at least 3 segments present ($NSEG)"; else bad "too few segments ($NSEG)"; fi
if grep -q '^#EXT-X-PROGRAM-DATE-TIME' "$PL"; then ok "program_date_time tags present"; else bad "no EXT-X-PROGRAM-DATE-TIME"; fi
if grep -q '^#EXT-X-ENDLIST' "$PL"; then ok "playlist finalised (ENDLIST)"; else bad "playlist not finalised"; fi
FRAMES=$(awk -F= '$1=="frame"{v=$2} END{print v+0}' "$RUN_DIR/ffmpeg_progress.txt" 2>/dev/null || echo 0)
DROPS=$(awk -F= '$1=="drop_frames"{v=$2} END{print v+0}' "$RUN_DIR/ffmpeg_progress.txt" 2>/dev/null || echo 0)
EXPECT=$(( DUR * STREAM_FPS ))
echo "  encoded frames: $FRAMES (expected ~$EXPECT)  drop_frames: $DROPS"
if [ "$FRAMES" -ge $(( EXPECT * 9 / 10 )) ]; then ok "frame count >= 90% of expected"; else bad "frame count too low"; fi
if [ "$DROPS" -le $(( EXPECT / 20 )) ]; then ok "drops <= 5%"; else bad "too many dropped frames ($DROPS)"; fi

PROBE_PY="$KICK_LIVE_ROOT/validate/hls_probe.py"
if [ -f "$PROBE_PY" ]; then
  echo "--- validate/hls_probe.py --local"
  if "$PYTHON" "$PROBE_PY" --local; then ok "hls_probe.py --local"; else bad "hls_probe.py --local exited non-zero"; fi
else
  echo "--- validate/hls_probe.py not present yet, skipped"
fi

echo
if [ "$FAIL" = 0 ]; then echo "test_local.sh: ALL CHECKS PASSED"; exit 0; else echo "test_local.sh: FAILED"; exit 1; fi
