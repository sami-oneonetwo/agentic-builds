#!/usr/bin/env bash
# stream/testsrc.sh — lavfi test pattern (colour bars + channel name + UTC clock) for SOURCE=testsrc.
#
# Two ways to use it:
#   1. Sourced by stream/run.sh: defines kl_testsrc_input (lavfi input spec) and
#      kl_testsrc_filter (drawtext graph) as functions.
#   2. Run directly:
#        stream/testsrc.sh --print            print the lavfi input and the video filter graph
#        stream/testsrc.sh --png [PATH]       render ONE frame to PATH (default $RUN_DIR/testsrc_frame.png)
#        stream/testsrc.sh --help
# Reads STREAM_WIDTH/HEIGHT/FPS, KICK_CHANNEL, FFMPEG from scripts/env.sh.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../scripts/env.sh"

KL_FONT="${KL_FONT:-/System/Library/Fonts/Menlo.ttc}"

# lavfi source description (goes after `-f lavfi -i`).
kl_testsrc_input() {
  printf 'testsrc2=size=%sx%s:rate=%s' "$STREAM_WIDTH" "$STREAM_HEIGHT" "$STREAM_FPS"
}

# Video filter graph: channel name + UTC clock (default %{gmtime} format = "YYYY-MM-DD HH:MM:SS",
# which sidesteps the colon-escaping mess), plus a small frame counter.
kl_testsrc_filter() {
  local font="$KL_FONT"
  [ -r "$font" ] || font=""
  local ff=""
  [ -n "$font" ] && ff="fontfile=${font}:"
  printf '%s' \
    "drawtext=${ff}text='${KICK_CHANNEL}   %{gmtime} UTC':fontsize=40:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=14:x=(w-text_w)/2:y=h-text_h-48," \
    "drawtext=${ff}text='TEST SOURCE  frame %{n}':fontsize=22:fontcolor=white@0.85:box=1:boxcolor=black@0.45:boxborderw=8:x=24:y=24," \
    "format=yuv420p"
}

# Only act when executed, not when sourced.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  case "${1:-}" in
    -h|--help)
      sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --print|"")
      echo "input : $(kl_testsrc_input)"
      echo "filter: $(kl_testsrc_filter)"
      exit 0 ;;
    --png)
      out="${2:-$RUN_DIR/testsrc_frame.png}"
      "$FFMPEG" -hide_banner -loglevel error -f lavfi -i "$(kl_testsrc_input)" \
        -vf "$(kl_testsrc_filter)" -frames:v 1 -y "$out"
      echo "wrote $out ($(stat -f %z "$out") bytes)"
      exit 0 ;;
    *)
      echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
fi
