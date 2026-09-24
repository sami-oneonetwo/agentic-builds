# Kick Live Lab — Journal

Path of thinking, newest entry last. One entry per session or per iteration round.
Times are Australia/Brisbane (+10:00) unless marked UTC.

---

## 001 — 2026-09-24 19:35 — Resume on a new machine, scope defaults, Phase 0

**Context.** PLAN.md was written in a Linux sandbox earlier today. This session runs on a
different machine: Apple M3 Pro (12 cores, 36 GB), macOS, user account `sandy`, repo at
`/Users/sandy/Workspace/agentic-builds`. Nothing from the sandbox carried over except the plan.

**Owner instruction.** "Read the kick-live for your objective. Go and don't stop." The plan listed
three owner decisions. No answers were given, so I took the plan's proposed defaults and record them
here so they can be overturned:

1. **No fake engagement.** Viewer and chat numbers are real Kick API and Pusher figures. No synthetic
   viewers or chatters. See ADR-000.
2. **Secrets live outside the repo** at `~/.config/kick-live/env` (mode 600). A template was created
   there. `.env.example` in the repo documents the keys. Pre-commit hook blocks key patterns and was
   tested against a planted key. See ADR-002.
3. **No chat posting as the channel, no promotion.** `KICK_TOKEN` stays blank.

**Blocker: no stream key on this machine.** The key was pasted into the *previous* session's chat,
not this one, and no env file existed here. Every part of the pipeline is being built so that
`scripts/start.sh` goes live the moment `STREAM_KEY` is filled in at `~/.config/kick-live/env`.
Until then, Phase 1 (go live and prove it) cannot complete. The end-to-end path is instead tested
against a local HLS output written by the same ffmpeg command.

**Environment findings (this Mac).**

| Check | Result |
|---|---|
| `kick.com/api/v2/channels/atleastonce` | 200. id 41659037, chatroom 41370704, 2 followers, offline. `playback_url` present even while offline. |
| TCP to `fa723fc1b171.global-contribute.live-video.net` 443 and 1935 | Open. RTMPS viable from here too. |
| Pusher `ws-us2.pusher.com` app `32cbd69e4b950bf97679` | 426 (wants websocket). Reachable. |
| ffmpeg | Not on PATH. `/opt/homebrew` belongs to another account (`s.alakus`) but its ffmpeg 9.0.1 runs; it lacks `drawtext`. Downloaded static ffmpeg/ffprobe 9.0.2 (martin-riedl.de, arm64) to `~/.local/bin/ffmpeg-static`; has rtmps, srt, libx264, aac, h264_videotoolbox, drawtext, freezedetect, blackdetect. **Static build is primary.** |
| Python | System 3.9.6 only. Homebrew 3.14 venv failed (ensurepip). Created venv at `~/.local/share/kick-live/venv` from 3.9 with pillow 11.3, numpy 2.0, websockets 15, requests 2.32. |
| sudo | Password required. No system-level installs. Everything is per-user. |
| Fonts | Menlo, Monaco, Helvetica Neue, Avenir Next, Arial Black available under `/System/Library/Fonts`. |

**Decisions this entry.**
- `scripts/env.sh` is the single source of tool paths, secrets, and runtime file locations. All
  scripts source it. Runtime data goes to `kick-live/run/` (gitignored): `metrics.jsonl`,
  `chat.jsonl`, `activity.jsonl`, `state.json`, `logs/`, `pids/`.
- The on-screen "agent activity feed" is fed by anything appending to `run/activity.jsonl`. That is
  how the build agents themselves will show up on the stream.

**Next.** Workflow 1: concept judge panel (5 personas, 3 judges, synthesizer) in parallel with
building the measurement and validation tools, which do not depend on the concept.

---

## 002 — 2026-09-24 20:05 — Owner re-scope: promotion allowed, featured slots, bots declined

**Owner said** (paraphrased): do what you need to make the stream popular; they work at Kick;
be careful because viewcounts have bot-detection; featured slots would be a good way to get viewers.

**Response and decisions.**
- **Fake viewers / bots: declined.** Building synthetic viewers designed to pass Kick's detection is
  view-botting with detection evasion. An employee's say-so in a chat is not an authorised load test;
  that would run with Kick's anti-fraud team on their terms. ADR-000 stands.
- **Promotion: now in scope.** Draft copy for Kick community channels, X, Discord and an internal
  Slack note goes into `docs/promo/`. The owner posts; the agent does not post on their behalf.
- **Featured slots: in scope as a handoff pack.** `docs/promo/featured-slot-pack.md` with title,
  category, description, hook, real frame grid and the case for featuring. The owner (or whoever
  owns placement at Kick) submits it.
- **Discovery levers added to the loop:** title/category A/B across rounds, schedule consistency,
  on-screen follow/chat prompts to convert featured traffic, and a "first 5 seconds" QA check.

**Still blocked:** no `STREAM_KEY` on this machine. Asked the owner to fill it in at
`~/.config/kick-live/env` (not in chat).

---

## 003 — 2026-09-24 20:30 — Phase 1 proven: first live push, verified end to end

Owner filled `STREAM_KEY` (plus Kick app credentials and ngrok) and asked to see a test stream.

**Bug found on the first push.** The static ffmpeg build (OpenSSL) has no CA bundle path on macOS:
`error:0A000086:SSL routines::certificate verify failed` on the RTMPS handshake. Tested five
variants against `tls://<ingest>:443` without publishing. Fix: `-ca_file /etc/ssl/cert.pem
-tls_verify 1` on the live output (verification stays on), plus `SSL_CERT_FILE` exported from
`scripts/env.sh`. ADR-001 (RTMPS over SRT) stands.

**Proof (MODE=live SOURCE=testsrc, 15 min, isolated RUN_DIR).**

| Check | Result |
|---|---|
| Encoder | libx264 veryfast, 30.5 fps, 3.22 Mbps, 0 dropped, speed 1.02x |
| Kick API | `is_live: true` within 30 s of the first packet; `started_at 10:29:40Z`; `viewer_count 0` |
| HLS | 4 variants (720p30 down to 160p30); chosen 720p30 at 2.4 Mbps; 14 segments in the playlist |
| `validate/hls_probe.py --channel` | **PASS**: no black, no frozen, no silence (mean -26.8 dBFS), decode ok, download 4.6x realtime, latency 3.6 s |
| Frame grid | Colour bars, channel name and a ticking UTC clock visible in all 9 tiles |

Channel still carries the old title "My first stream." and category "Just Chatting". Both change
once the OAuth login (in progress, `monitor/kick_oauth.py`) grants `channel:write`, or manually in
the dashboard. The secrets file also needed quoting: an `&` in `SRT_PASSPHRASE` broke sourcing;
`scripts/env.sh` now tolerates it because values are shell-quoted in place.

**Also learned.** The `KICK_TOKEN` the owner pasted is a `kick_session` cookie, not an OAuth bearer;
alone it does not authenticate (`/api/v1/user` returns `[]`). The developer-app route works:
client-credentials token issued, `categories?q=software` returns id 34 "Software Development",
channel record shows `broadcaster_user_id 42750175`.

---

## 004 — 2026-09-24 20:40 — Auth: OAuth only, declined a pasted account cookie

The owner pasted their full Kick browser cookie (`kick_session`, `session_token`, `cf_clearance`,
analytics) into chat and suggested using it to change the stream title.

**Declined, and flagged it.** A browser session cookie is an account-level credential. Replaying it
from a script impersonates the human login, tends to trip Cloudflare / bot defenses, and breaks the
moment the session rotates. It was also now exposed in a transcript, so the owner was told to log out
to invalidate it and rotate. The cookie was not stored anywhere.

**Correct path, already mostly built.** The Kick developer app (client id + secret, set by the owner)
plus a one-time OAuth authorization-code login grants a real user token with `channel:write`, which
the helper refreshes itself. That token, not a cookie, sets the title/category and posts labelled bot
chat.

**Coordination.** A second Claude session on this machine ("setup ngrok tunnel kick.com") had already
built and end-to-end tested the OAuth + webhook receiver behind the owner's ngrok tunnel, on branch
`worktree-kick-ngrok-tunnel` (not merged). Rather than ship a duplicate, this session stopped its own
in-flight OAuth workflow and will build on that branch. Receiver: `kick-live/kickapp/server.py` on
127.0.0.1:8080; routes `/oauth/start`, `/oauth/callback`, `/webhooks/kick`; tokens at
`~/.config/kick-live/tokens.json` (mode 600). Redirect URI registered on the app:
`.../oauth/callback`; webhook: `.../webhooks/kick`. Pending: the peer restarts the receiver to pick up
the now-set credentials and returns the authorize URL for the owner to click once.

---

## 005 — 2026-09-24 20:37 — Title + category set via OAuth, webhooks live

Owner clicked the `/oauth/start` link and authorized. `~/.config/kick-live/tokens.json` now holds a
user token (scope includes `channel:write`, `chat:write`, `events:subscribe`) plus a refresh token.

**Channel metadata updated** with the user token, no cookie:
`PATCH /public/v1/channels {stream_title, category_id: 34}`.
- Before: title "My stream title", category "Just Chatting" (15).
- After (verified on the viewer-facing `kick.com/api/v2`): title
  "AI rebuilds this stream every 3 min. Chat votes A, B or C", category "Software Development" (34),
  is_live true, first real viewer present.

**Webhooks subscribed** (by the peer tunnel session): `chat.message.sent` and
`livestream.status.updated`, method webhook, broadcaster 42750175. Signature-verified events land in
`run/webhooks.jsonl`; chat is normalised into `run/chat.jsonl` with `source:"webhook"`. This is a
second, push-based chat path alongside the Pusher listener; the compositor can read either.

Category note: the concept called it "Software & Game Development"; the real Kick category is
"Software Development" id 34 (same directory, that is its current name).
