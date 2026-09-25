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

---

## 006 — 2026-09-24 20:47 — Webhook path proven; compositor build started

The test stream ended (went offline 10:46:12Z, ~16 min after 10:29:39Z start). Kick delivered a
signature-verified `livestream.status.updated` webhook to the receiver, stored at
`$RUN_DIR/webhooks.jsonl`. So the push-based liveness path works end to end; the supervisor will tail
that file and treat `is_live:false` as a fast restart trigger (faster than the 15 s API poll).

**Compositor build launched** (workflow, MODE=test / local HLS only, never live): a spine agent
builds a complete-but-simple working show plus the Panel / StateStore / AudioEngine / RoundEngine /
ChatBridge interfaces (`stream/COMPOSITOR_API.md`); then 8 parallel specialists replace each part
with the rich version from CONCEPT.md (header/stage/chat/ballot panels, numpy audio, the 180 s round
engine, the moderation+command chat bridge, the generative canvas); then an integration agent runs
the whole thing to local HLS and captures a frame grid; then viewer-QA + legibility + retention-critic
agents inspect the real frames; then a fix pass. Panels are separate files so agents don't collide;
a panel that raises is caught and shows a placeholder so the loop never dies.

---

## 007 — 2026-09-24 21:20 — Owner housekeeping; key unchanged by choice

Owner rotated the browser session (the pasted cookie is dead) and confirmed the **stream key was not
rotated**, deliberately, for now. OAuth user token, webhook receiver and tunnel all survived the
logout (OAuth is independent of the browser session). Post-project key rotation stays on the list.

Compositor workflow restarted on Fable 5.1 (all agent calls pinned with `model: 'fable'`; the first
run had inherited Opus 4.8 from the session). Spine phase in progress; 90 self-test frames rendered
and inspected: layout, hook header, ballot, honest empty states all present; a few truncation issues
noted for the module/integration passes.

---

## 008 — 2026-09-24 21:22 — SHIP IT LIVE is on air (spine build), verified from Kick playback

Owner asked to speed up (under ten minutes). Decision: go live with the **spine compositor** now
rather than wait for the module/QA phases; it already renders the full legible layout at 3-10 ms per
frame and survived its fault tests. The enrichment workflow keeps running in the background against
the working tree; the live show runs from a **frozen snapshot** at `~/.local/share/kick-live/live-snapshot`
so agent edits cannot disturb it. All runtime state is in the shared `$RUN_DIR`.

Launch: `MODE=live SOURCE=compositor AUDIO_SOURCE=pipe:$RUN_DIR/a.pcm scripts/start.sh` from the
snapshot → supervisor → run.sh → compositor | ffmpeg (RTMPS, CA file, verify on); plus
`monitor/kick_api.py --json-state` and `monitor/chat_listener.py`. Webhook receiver + tunnel (peer
session) already up. Title/category re-applied via OAuth just before launch.

| Check | Result |
|---|---|
| Processes | supervisor, run, compositor, ffmpeg, kick_api, chat_listener, kickapp, ngrok all alive |
| Encoder | 3.1 Mbps, 0 drops; compositor render avg 3.2 ms, p95 9.6 ms, in-process numpy audio via FIFO |
| Kick API | `is_live true`, title and category correct |
| HLS probe (real playback) | **PASS** 1280x720@30, aac 48k stereo, latency 3.9 s, no black/frozen/silent |
| Decoded frame | full layout: hook header, LIVE dot, countdown 02:30, ballot, activity feed with real events, honest empty chat |

Known cosmetic issues carried into the enrichment pass: stage title and pinned strip truncate; ticker
and activity lines can clip. Micro rounds run compositor-owned; the first ship will land in under 3
minutes with an agent-pick if nobody votes.

Gotcha: `source scripts/env.sh` via a *relative* path from the snapshot resolved `KICK_LIVE_ROOT` one
level too high; absolute paths resolve correctly. Always launch with absolute paths.

---

## 009 — 2026-09-24 21:28 — Live hotfix: stage panel thrash ("stage_body over budget")

**Symptom (owner saw it on screen):** the frame-time guard disabled `stage_body` every ~16 s
(30 renders > 20 ms → placeholder for 300 frames → re-enable → trip again), and `activity_feed`
too at up to 70 ms. Encoder was unaffected (30 fps, 0 drops) but the stage flickered to a placeholder
for most of each cycle, and each disable wrote to the activity feed, forcing that panel to re-render.

**Root cause (spine build):**
1. `StageBody.inputs()` restarted the typewriter whenever the STATUS lines changed, and those lines
   contain an `hh:mm:ss` clock, so the panel re-typed forever at 40 full re-renders per second
   (each 20-40 ms over an 840x236 text panel).
2. `layout.truncate()` shaves one character per loop with a font measurement each time; O(n) text
   measurements per call, several calls per feed render.

**Hotfix applied to the live snapshot only** (working tree `stage.py` is being rewritten by the
enrichment workflow; carry these into reconciliation):
- `stage.py`: typewriter restarts only when the clock-stripped content changes; reveal quantised to
  8-char steps (~5 renders/s instead of 40).
- `layout.py`: `truncate` memoised with `lru_cache(8192)`.
- `compositor.py`: `PANEL_BUDGET_MS` 20 → 28 (frame budget is 33 ms; total avg is ~4 ms).
Restart: TERM to the compositor → supervisor relaunched in 2 s (exit rc=0, attempt 2). Kick stayed live.

**Result:** 0 disables; stage_body max 17.5 ms and ~2.6 renders/s (was 40.9 ms, ~30/s);
activity_feed max 15.9 ms (was 70); frame p95 14 ms (was 37); 2 real viewers watching.

---

## 010 — 2026-09-24 21:41 — Agent on duty; first human-requested macro-ship (chaos mode)

Owner asked whether chat reaches the agent. It did not: chat reached only the compositor (votes,
!idea, !theme parsed in-process); no model was in the loop and the screen said "no agent on duty".

**Went on duty.** `agents/duty.py` (new): heartbeat loop (agent.on_duty + heartbeat_ts every 30 s),
`classify` for !idea, `macro-start/step/done` for the on-screen macro clock and stage steps, `say`.
It writes only the fields the concept reserves for an external agent and uses the same re-read +
atomic-replace protocol as rounds.py. A chat Monitor now notifies this session of every non-vote
message. The NEXT UP panel flipped from "no agent on duty" to the queue.

**Macro-ship v0.4.0 (commit 6781fce), requested by @atleastonce via `!idea change everything. Make it
all random`.** Built live in ~12 min: a `chaos: randomise one parameter` ballot option in the round
menu; when it ships it rolls one other parameter to a new random value and rewrites the ship title to
what actually changed (`chaos → palette: gold`), so patch notes stay honest. Unit-tested 4 rolls;
deployed by restarting the compositor (2 s, supervisor attempt 3); patch saved at
`stream/patches/0001-chaos-option.patch` for reconciliation into the working tree.

**Bugs found live and fixed in the snapshot:** idea ids collided (`len(ideas)+1` → two `i-0002`);
generator now uses max(existing)+1. `duty.py classify` also updated every id match; now exactly one,
with `--match TEXT` to disambiguate. State repaired by hand (i-0002 chaos, i-0003 pixel-art).

Second idea queued: `!idea build a pixel art bot that responds` (i-0003, macro). Note: the version
counter read v0.4.0 after the macro bump (engine had macro=3); monotonic and tied to real ship events,
but the scheme differs from CONCEPT §8; align during reconciliation.

---

## 011 — 2026-09-24 21:43 — Owner rule: never restart the live pipeline

Owner: "You shouldn't kill the stream, that's not a good look." Correct. Both deploys today (the
stage-thrash hotfix and the chaos macro-ship) restarted the compositor, which closes ffmpeg's stdin;
ingest dropped 2-4 s each time. Kick kept `is_live` true but every viewer saw a stall.

**Rule from now on:** no compositor/ffmpeg restarts on a live show without the owner's go-ahead.
Deploys must be invisible: state.json-driven changes only (read live), or hot-reloaded modules, or a
frame-relay that owns the ffmpeg pipes and repeats the last good frame while the renderer restarts.
The one remaining restart that is genuinely needed, swapping to the enriched compositor, will carry
the relay + hot reload so it is the last visible one, and it happens only when the owner says so.
Until then the pixel-art idea (i-0003) stays queued: it needs new panel code, which the spine cannot
hot-load.

---

## 012 — 2026-09-24 21:47 — Session end: show stopped on owner request, resume notes

Owner had to leave. `stop.sh` from the live snapshot stopped supervisor → run.sh → compositor + ffmpeg,
plus kick_api and chat_listener; duty agent taken off duty. Peer's webhook receiver (pid 25684) and
ngrok (25728) were left running; they are harmless and Kick only drops the subscriptions after ~1 day
of failed deliveries.

**Session totals (real):** on air ~28 min in two segments; peak 3 concurrent viewers; 8 ships
(6 micro incl. agent picks, 1 human-triggered macro "chaos mode", 1 micro after); founders: atleastonce;
24 chat lines (all the owner); 2 `!idea`s (one shipped, pixel-art bot queued as i-0003).

**Open findings to fix before the next live run**
1. **Live-state contamination.** At ~21:42 the LAST SHIP card showed "v0.3.16 · canvas rule: worms",
   which the live engine cannot produce; a module agent's round-engine test wrote to the shared
   `$RUN_DIR/state.json` (the rounds engine re-reads on-disk state before every write, so the foreign
   version counters were adopted; that is also why the macro bumped to v0.4.0 not v0.2.0). Fixes:
   give the compositor/rounds a `--run-dir` REQUIRED in test mode, make test hooks refuse the canonical
   dir, and have the live engine write only its own fields (not adopt version.* from disk).
2. **No-restart deploys.** Owner rule (011). The enriched build must ship with a frame relay (owns the
   ffmpeg pipes, repeats last frame) and/or module hot-reload before it replaces the snapshot.
3. **Snapshot ≠ working tree.** Hotfixes live only in `~/.local/share/kick-live/live-snapshot`
   (stage typewriter key, `truncate` memo, PANEL_BUDGET_MS 28, chaos option, idea-id generator).
   `stream/patches/0001-chaos-option.patch` captures one; diff the snapshot against `stream/` and
   port the rest when the enrichment workflow finishes.
4. Branch reconciliation with `worktree-kick-ngrok-tunnel` (peer's kickapp/) still owed; ping the peer first.
5. Cosmetic: stage title / pinned strip truncation; ticker clipping; version scheme vs CONCEPT §8.

**Background at time of stop:** enrichment workflow `wf_520393aa-e83` (Fable) still finishing
`mod:panels-stage`, then Integrate → QA → Fix; promo-pack workflow `wf_7c8c4d33-864` writing
`docs/promo/`. Both write only to the working tree and /tmp. Their results land uncommitted.

**Resume (cold):**
```bash
cd ~/Workspace/agentic-builds && git pull
tail -120 kick-live/docs/journal.md                 # this entry and 011
ls kick-live/docs/promo/ kick-live/stream/           # what the workflows produced
git status --short                                   # uncommitted agent output to review
grep -c . ~/.config/kick-live/env                    # secrets still there (STREAM_KEY unrotated)
curl -s http://127.0.0.1:8080/health                 # peer receiver up?
# Go live again (spine snapshot, known-good):
MODE=live SOURCE=compositor AUDIO_SOURCE=pipe:$HOME/.local/share/kick-live/run/a.pcm \
  bash ~/.local/share/kick-live/live-snapshot/scripts/start.sh
~/.local/share/kick-live/venv/bin/python kick-live/agents/duty.py heartbeat &   # agent on duty
```
Before any new live run: recreate the FIFO if missing (`mkfifo ~/.local/share/kick-live/run/a.pcm`),
re-apply title/category via OAuth (tokens refresh themselves), and do NOT restart the pipeline while live.

Addendum to 012 (from the tunnel session): receiver and ngrok stay up so the three webhook
subscriptions keep receiving. If the Mac sleeps they die; bring them back with
`scripts/kick-app.sh up` from `.claude/worktrees/kick-ngrok-tunnel/kick-live` (or from main after the
merge), then `scripts/kick-app.sh kick subscriptions` to confirm chat.message.sent,
livestream.status.updated and livestream.metadata.updated are still listed.

---

## 013 — 2026-09-25 10:36 — Day 2 resume: back on air, hardening phase added

The previous Claude Code process died overnight with two workflows mid-flight. Survived: the spine
and all 8 enrichment modules (uncommitted in `stream/`), the featured-slot page + real frames in
`docs/promo/`. Lost: the integration step, the promo posts/README. The peer tunnel session is gone,
so this session now owns the receiver/tunnel too (ngrok had died with the Mac; restarted with the
peer's `scripts/tunnel.sh start`; all three webhook subscriptions still listed). A stray duty
heartbeat from last night was still running; killed.

**Back on air from the known-good snapshot**, but in an **isolated run dir**
`~/.local/share/kick-live/run-live` (history copied over: chat, ships, builders, state) so that no
test agent writing to the default shared dir can contaminate live state again (finding 012.1). Cost:
webhook-sourced chat lands in the shared dir, not the live one; the Pusher listener covers chat.
Title/category re-applied via OAuth. Probe PASS, is_live true within a minute.

**Enrichment workflow resumed** (cached spine + modules) with a new **Harden** phase before
Integrate, 4 parallel Fable agents: `stream/relay.py` (owns ffmpeg's inputs, repeats the last frame
while the compositor child restarts → deploys without dropping ingest) + `scripts/deploy.sh`;
run-dir guard + module hot-reload + state write-ownership; rounds port (chaos option, idea ids,
CONCEPT §8 version scheme, no adoption of foreign version fields); stage/layout hotfix port + the
truncation/clipping cosmetics. Integrate then has to prove a deploy mid-HLS-run with an unchanged
ffmpeg pid and a passing probe.

**One restart still owed:** the snapshot pipeline has no relay, so swapping to the enriched build
means one visible ingest gap. It happens only with the owner's go-ahead, at a quiet moment, and it
is the last one. Promo workflow resumed to finish `posts.md` and `README.md` and fact-check.

Addendum to 013 (10:47): **ingest drop at 00:39:09Z, ~26 s off air.** ffmpeg's output got
`tls: Broken pipe` (Kick/IVS closed the RTMPS connection server-side); ffmpeg exited rc=224 after
flushing. Reconnect attempts 2-3 were refused with `tls: End of file` (ingest still holding the old
publisher session); attempt 4 at +26 s connected and has been stable since. Supervisor backoff
2/4/8 s worked as designed. Not caused by anything on our side; a relay would not have helped (this
was the encoder's output, not its input). A tighter first retry (1 s) is worth considering.

**Word filter installed live.** The spine shipped with a comment-only blocklist (0 terms) — the
show had no slur filter for its first ~50 min. The enrichment module's 79-term list (whole-token,
leet-normalised; verified it does not flag ordinary chat like "strange ass stream") was copied into
the snapshot. The bridge reloads it inside `ingest()`, i.e. when the next message is processed, so
it becomes active on the next chat line; the startup log's "0 terms" predates the reload.

---

## 014 — 2026-09-25 10:58 — Promo pack fact-checked; bugs it surfaced

`docs/promo/` is complete: `featured-slot-pack.md` (one page for whoever owns featured placement,
every number sourced), `posts.md` (Discord/community, X single + 3-tweet thread, internal Slack note
with disclosure, pinned chat message; all counted), `README.md`, real frames from Kick playback +
320x180 thumbnail check. Fact-check verdict: pass_with_fixes (18 corrections, all applied). Two
statements went stale during the check and were updated by hand: the blocklist is now 79 terms
(00:52 UTC), and the 00:39 ingest drop is diagnosed as Kick-side (addendum to 013).

**Bugs the fact-checker found (carry into Harden/Integrate, or fix before a featured window):**
1. Voter names under the ballot cards bypass the 3 s hold AND the username blocklist filter
   (`chat_bridge.tallies()` returns raw names; only `visible()` filters). An offensive username
   could appear under a card within a second.
2. `builders.json` double-counts votes/sessions on every compositor start (history re-ingest):
   26 votes recorded vs 4 real vote messages. Not cited anywhere on screen yet except `#N`.
3. Shared `run/state.json` was written AGAIN at 00:37 UTC by a Harden-phase test
   (`run_dir=/tmp/cp-stage-port-baseline` in its own log, yet the shared file changed). The live
   show is isolated in `run-live/` so nothing was shown on air, but the guard in the Harden phase is
   clearly necessary. Also something deleted `run/probe/promo-1` and `run/probe/live-show-1`
   between 00:44 and 00:52 UTC; the promo copies are the record (sha256 in README).
4. The on-screen ship counter includes the contaminated `v0.3.16` ship from yesterday (8 vs 7 real).
