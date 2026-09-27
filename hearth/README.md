# hearth

A night hill. One fire. Chat is wood. Silence is cold.

This is a separate stream from `kick-live`. It does not share run dirs, snapshots, or the live encoder. Do not point it at `~/.local/share/kick-live/run-live`.

## What it is

Every real chat line drops a person into the ring, forever. Later lines throw a log. The size of the light is the whole meter. No HUD, no vote, no village.

Moods, from the flame:

- **ash** — it went out. A coal. A match might catch.
- **embers** — almost no one. Close. Crackling.
- **campfire** — a handful of voices. The ring is a room.
- **bonfire** — volume. The light climbs.
- **wildfire** — a pile-on. Spectacular, and it costs the edge of the ring.

Mean talk still burns. It just burns ugly. Kindness is not scored. Quiet forever-people sit in the ring. They do not feed the flame.

## Look at it

Needs the kick-live venv (Pillow, numpy) and `~/.local/bin/ffmpeg-static`. Nothing is installed globally.

```bash
cd hearth
scripts/selftest.sh          # sim checks + 180 PNG frames, writes /tmp/hearth-selftest
scripts/preview.sh 12        # local mp4, writes ~/.local/share/hearth/run/preview.mp4
scripts/feed.sh jo hey       # append a line to hearth's own chat.jsonl
```

`preview.sh` never touches Kick. Open the mp4.

A packed night in the self-test walks embers -> campfire -> wildfire. People sit in a horseshoe in front of the flame. Their words are the only copy on the picture.

## Put it on Kick later

Stop the other stream first. Hearth will refuse to start live while kick-live's ffmpeg is alive.

```bash
MODE=live scripts/start.sh --dry-run
# owner only, after kick-live is down:
#   scripts/listen.sh &          # tails Kick chat into hearth's chat.jsonl
#   MODE=live scripts/start.sh
```

Secrets stay in `~/.config/kick-live/env` (same `STREAM_KEY`). Runtime state is `~/.local/share/hearth/run`. Title idea: `say anything. the fire lives on it`.

## Rules this app keeps

- Every face is a real chatter. Nobody is invented.
- Chat is data. It feeds the fire. It does not run the box.
- No AI copy on the picture.
- Forever-people sit in the ring after they go quiet. They do not vanish. They also do not haul wood.
