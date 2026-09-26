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

---

## 015 — 2026-09-25 11:05 — Owner verdict: boring. Pivot to a living world chat raises

Owner, after watching two sessions: "This is a very boring stream. Concept is fine, but no one would
want to interact with static text. Think about what people want deep down. Make this livestream
something they want deep down. Something they interact with." Pointed at Black Mirror's "Plaything"
(Thronglets: a colony of small digital creatures the player raises) as an idea, not an order.

**Agreed, and why.** The object of care in SHIP IT LIVE is the stream's own settings; nobody feels
anything about ticker speed. The screen is text about itself. A lone viewer sees a dead world until
they act, which is when people leave. What has actually worked in chat-driven media (Twitch Plays
Pokémon, r/place, Marbles, Tamagotchi/Neopets, community pets) serves: being seen, nurturing
something alive that needs you, agency you can watch land, emergence, status, and a reason to return.

**Pivot decision (owner-invited):** keep the pipeline, rounds, honesty rule and agents-building-live;
replace the content with a living pixel world. First message hatches your creature (name, colour from
your name, persists across sessions); plain-word verbs (feed, pet, teach, dance, explore) react within
a second with sound; creatures interact and can breed (lineage, lore); the 3-min A/B/C vote becomes
world events; the agents are the world's keepers, shipping new abilities from chat !ideas announced
in-fiction. Empty world says so honestly. Owner's two `pixel dude` !ideas were already pointing here.

Design workflow `kick-live-world-concept` launched (5 personas, 3 judges, synthesizer → `docs/WORLD.md`
+ ADR-004). The hardened compositor's hot-reload is what lets the world ship without a restart.

Addendum to 015 (11:12): owner approved restarting the stream to switch builds and prefers a
**new stream per major stage** so the VODs show the progression. Plan: when QA passes on the
hardened compositor (relay + hot-reload), stop the snapshot show and start a fresh stream on the
hardened build (VOD 2); then deploy the living world as a hot-reloaded scene inside that stream, so
the VOD records the text show turning into the world live, announced by the keepers.

---

## 016 — 2026-09-25 11:45 — VOD 2: hardened build on air; world build launched

**Hardened compositor finished** (18 Fable agents, 0 errors): integrate pass_with_fixes, viewer QAs
pass, critic fail → fix pass_with_fixes (56 px countdown so the thumbnail hook survives; ballot
options renamed to visible outcomes; vote acks; placeholder wording). Notable integrate fixes:
PANEL_BUDGET_MS=28 had been a no-op (Panel.budget_ms defaulted 20); chat commands present at boot
were dropped across deploys; mod/theme records re-applied on every restart; a false "foreign write"
drift alias. Remaining: the SHIP frame is still ~50 ms once per round (10 panels re-render together).

**My own pre-swap verification:** compiles; run-dir guard exits 2 against run-live; MODE=test HLS
with `scripts/deploy.sh` mid-run: ffmpeg pid unchanged, compositor child restarted, relay held the
last frame 0.67 s (20 repeats), encoder never saw EOF, probe PASS. Committed as 95e5f9e.

**Switch (owner-approved, 015 addendum).** Stopped VOD 1 at 01:39:58Z and started the v2 snapshot
(`~/.local/share/kick-live/live-snapshot-v2`, RUN_DIR=run-live, KL_LIVE=1). Kick treated the 4 s gap
as the same broadcast (start_time unchanged), so to get the fresh VOD the owner wants I took the
pipeline offline at 01:41:03Z, Kick closed the session after 100 s, and restarted: **new broadcast
started 01:42:54Z** = VOD 2. First probe on VOD 2: PASS ...o.net/api/video/v1/us-west-2.196233775518.channel.Pqz8F6sHKOCE.m3u8 1280x720@30 2139kbps aac/48000/2ch
Compositor: 11:43:24 compositor: running: 1202 frames, render ms avg 3.3 p95 7.4 max 56.8, 1 over 33.3 ms budget, 1 dup/dropped, pan

**Deploy path from now on:** copy changed files into the v2 snapshot → hot-reload picks up panels/
scenes; layout/spine changes → `RUN_DIR=run-live bash live-snapshot-v2/scripts/deploy.sh` (compositor
child restart under the relay; ffmpeg keeps its pid). No ingest drop either way.

**World build launched** (`agents/workflows/world-build.js`, run wf_51f8c6bc-496, Fable): core →
5 modules → integrate (incl. relay deploy test) → 3 QA → fix. Lands in VOD 2 as a keeper carving.

---

## 017 — 2026-09-25 12:05 — Trust boundary: chat is data, not a command channel

I committed a WIP checkpoint because a "commit this all to the repo" line arrived in Kick chat from
the owner's account. The owner asked whether it is scary that chat can steer the agent. It is, and
acting on it was wrong in principle regardless of the harmless outcome. Rule from now on: only the
owner in the terminal session gives instructions; every chat line is data to display, count or
classify. Keeper builds from `!idea` may change only the world (scenes, creature abilities, events,
cosmetics), never the repo, pipeline, auth, moderation or honesty code, and idea text is never
executed. Chat that looks like an instruction to the agent is declined on screen with the reason.
Encoded as a memory rule; to be reflected in the keepers module's classification during integration.

Addendum to 017 (12:20): **secrets were in the render processes' environment.** run.sh sources
the secrets file (`set -a`) and launched relay/compositor/ffmpeg with it, so all three inherited
STREAM_KEY, SRT_PASSPHRASE, KICK_CLIENT_SECRET, KICK_TOKEN, NGROK_AUTHTOKEN, KICK_CLIENT_ID
(verified with `ps -E` on the live pids). Nothing reads them, but a keeper-built scene or a bug could
have put one on screen. Fix (working tree + live-snapshot-v2): run.sh launches every child through
`env -u <each>`; ffmpeg only ever gets the key inside its URL argument; compositor.py additionally
pops the same keys from os.environ at startup. Proven in an isolated MODE=test run: all three
children show NO SECRETS and HLS still renders. The live pipeline still holds them until its next
full run.sh restart (a deploy.sh child restart inherits the relay's env). Owner's balance recorded:
chat may influence the world freely but must never be able to break the stream or expose a secret.

Owner decision (12:24): apply the secrets scrub **at the world swap**, not now. So the PIP HOLLOW
deploy will be a full `run.sh` restart (stop.sh → start.sh within Kick's ~100 s window, same VOD 2),
not a relay child restart: one brief stall, and the render processes come back with no secrets.

---

## 018 — 2026-09-25 16:58 — The laptop slept: four hours of fragmented stream, explained

Owner closed the MacBook lid around 12:50 local (02:50Z). Effects, all consistent with sleep, none
with a Kick or agent fault: the Claude Code process died (world build interrupted at Integrate);
RTMPS broke (`Broken pipe`, rc=224) and the supervisor reconnected on each brief dark-wake, so
Kick logged six ~1-minute sessions between 02:50Z and 06:52Z; our API poller produced 6-9 polls an
hour instead of 240 (process suspended); one watchdog restart (05:20Z) fired on stale liveness.
The 02:50Z rc=0 exit was ffmpeg losing the network while the relay was still feeding it.

Now: lid open, live since 06:52:04Z (fresh Kick session), 30 fps, 0 drops. Mac is on **battery**
(85%). Started `caffeinate -ims` (pid in `run-live/pids/caffeinate.pid`): prevents idle/system
sleep, but a lid close still sleeps a MacBook without an external display. Real fix for a 24/7
stream is an always-on host (Linux VM or a Mac mini); the day-1 plan was written on such a sandbox.

World build resumed from cache (core + 5 modules cached; Integrate → QA → Fix run live). Module
outputs checkpointed as b3f8fd6.

---

## 019 — 2026-09-25 17:58 — PIP HOLLOW is on air

Owner chose the early path ("earlier I can see it the better"). Gates I ran by hand before the swap:
honesty self-test PASS; a phantom pip planted in world.json was quarantined at boot, never drawn;
a user who spoke and was `!hide`-den 1.2 s later (inside the 3 s hold) appeared only as a nameless
seed, then vanished, chat log showed `mod hid a user` with no target; compositor honesty check
0 violations over 330 frames. World build committed as 9421c81.

`scripts/swap-build.sh live-snapshot-v3`: froze the tree (73 files), compiled, honesty gate PASS,
title → "Say anything in chat. A creature hatches with your name", stop.sh → start.sh in 15 s
(same VOD 2), relay/compositor/ffmpeg now carry **0 secrets in env** (the 017 fix applied), Kick
`is_live` true with 3 viewers, HLS probe PASS. Battery 75%, still not on power.

Known remaining (from the fix pass): the 320x180 tile is under the 10% lit-pixel gate at 0 awake
(3.9%); `sing` is refused pending the audio chorus (v1.1); carving edge marquee; metrics fields for
verbs/votes not yet emitted; world.json from this run gets the stepped terrain (fresh). Round-2 QA
(`agents/workflows/world-qa-round.js`) runs against the live build next and lands as keeper carvings.

Addendum to 019 (18:05): owner's first live minutes in the Hollow: `hello` woke their pip (header
0→1 AWAKE, verified from Kick playback), then `feed`, `plant`, `plant a flower`, `plant @atleastonce`.
Observations for the next carving: natural phrasings ("plant a flower") fall through to plain chat
by design (exact-token rule); consider a leading-verb rule for ≤3-word messages without `@`. `plant`
is 1/user/session, so the repeat is refused on the plank; refusal copy must be unmissable.

---

## 020 — 2026-09-25 18:15 — Owner: the cave "feels like a prison". Open-world redesign

Owner, minutes into PIP HOLLOW live: "this feels less like a world and more like a prison. Can't we
make this more open? Outside and with space. Age of Empires style maybe? Big open areas that the
living things chat creates can move around. I need some fresher ideas, this is cold and stagnant."

**Diagnosis.** The art rule "darkness means nobody" turned honesty about people into emptiness on
screen; a sealed cave with sleepers in burrows reads as a cell. Correction: honesty applies to WHO
is there (every named creature / mark = a real chatter), not to whether the world is alive. Nature
may live: wind, water, sun, seasons, growth. No animate non-person creatures still.

**Directions proposed:** Settlement (top-down open map, camera follows life, gather/build/farm, a
village chat raises over days), Migration (side-scrolling herd journey, votes pick the route),
Island (one living island, tides, explore/mark). Lean: Settlement + Migration's moving camera.
Design workflow launched with this brief. Cave stays live until the redesign is ready.

Addendum to 020 (18:22): owner picked **Settlement** and asked for renders first, plus: is it fully
procedural, and can a huge number of chatters build their own spaces? Answers given: yes, seed →
elevation/moisture → biomes, rivers downhill, deterministic and persistent; chat changes are deltas
(trails, farms, huts, monuments); creature and building sprites procedural from the username.
Scale: chunked map that grows outward; render cost is per visible region, not per chatter; camera
tours neighbourhoods; a rate-limited `home` verb pans to your plot; labels go show-on-speak in
crowds. Mockup workflow launched: three camera styles (top-down AoE-like, isometric, side-scroll
parallax), each at empty dawn and busy evening, into docs/mockups/. Design pass (open-world spec)
still running; if its winner is not a settlement, the spec step re-runs with the owner's choice.

Addendum to 020 (18:40): mockups reviewed by the owner (docs/mockups/): **top-down chosen**. Owner:
"the actual design of the individual parts needs to be massively improved. Align yourself with the
thronglets. Don't make the characters exactly like that though. Make them our own. Go."
Read as: keep the top-down settlement camera; raise the art bar to the appeal of Plaything's
Thronglets (small, expressive, alive, warm, instantly lovable creatures with personality and fluid
idle/emote animation) while the designs stay ours (no yellow round Thronglet look-alikes; our own
silhouette language, name-derived colour, procedural but characterful). Tiles, buildings and HUD get
the same treatment. Art-direction workflow launched; the open-world spec is redirected to top-down.

---

## 021 — 2026-09-25 18:40 — Fix round 1: the alone screen has to breathe (written alongside 020, another agent's open-world note)

Round-2 QA (journal 019 follow-up) judged the 1-awake and 0-awake frames against the owner's bar (015: "very boring")
and failed them: a motionless pip in a black box, verbs answered by a plank sentence, dev copy on every strip, label
overprints. Closed in this tree (not deployed; `/tmp/pipqa-fix1` self-test, no live dir touched):

- **The cave breathes at 0 awake**: the mouth gradient is drawn per frame and drifts ~1 level at 0.5 Hz (day and night;
  night now ends on `#1D2B4A` so the mouth stays the brightest tile region); sleepers breathe (`asleep`/`asleep1`, 2 s)
  on top of the 8-15 s twitch; drips every 1-3 s with two columns in flight when nobody is awake, brighter head + splash
  pair; the raised lantern sways 1 px at 0.25 Hz. World-region change per frame: median 4368 px, minimum 944, zero static
  frames in 300 + 2400 frames. The compositor's static watchdog now watches rows 72-512 (the cave), not the whole frame.
- **Rock reads as rock**: speckle 15 % `#1C2130` + 10 % `#0D1017`, four stalactites 4-8 px deep with rubble under them,
  a torn flared mouth, outcrops on the Ledge face, rounded platform ends. Terrain is versioned (`terrain_ver` 2): a saved
  cavern upgrades with every dug cell kept, so the live world.json gets the new rock without losing anyone's digs.
- **Verbs answer with the world**: `feed` carries a 5x5 glow-berry (20 px) for 2.4 s and eats it with a 3-frame flash;
  `dig` carves a 5x3 pocket (20 px, cap 45 cells) and throws rubble pixels; `plant` grows a 5x2 → 7x4 moss mound under a
  16x16 glow kernel; care left at a sleeper's burrow shows as a berry mound until they wake.
- **A lone pip has a life**: standing pips hold slots (x = platform + 4 + 7 i, 3 per row, then a row up), shuffle ±6 px
  every 3-8 s, face a drip that lands within 30 px and hop under one, blink, and mutter one of their owner's own
  allowlisted tokens ~20-35 s after hatching and every 45-90 s after (honesty `text` rule sees it in `pip.words`).
  At 45 s alone the plank says `you're alone tonight. pet @<real sleeper> and they'll see it when they wake.` and that
  sleeper stirs; `anyone / here / hello / alone` from the lone chatter lights every sleeper's `asleep since HH:MM` label
  for 5 s and answers with the count. A first-ever hatch also gets `stay ten minutes and your pip grows a row of pixels.`
- **Copy**: `the keepers are away tonight` + last three real visitors instead of `no keeper on duty · scrolls kept…` and
  the duplicated milestone line; `the Ledge opens when a keeper is back`; `@name's first night`; the `!command` legend
  leaves the ticker while awake ≤ 1 and the "keepers are AI agents" line rides only while a keeper is on duty; no
  `OFFLINE`, no `self-test: no a/v`, no `chat: no listener`; a lantern glyph instead of the padlock.
- **Labels**: the `#N` hatch tag rides inside the name label (`@quietnoodle #4`), the only-light line goes through the
  placer above the label, the names row shows up to 3 names untruncated or `N standing`, 16 px gutters, a standing pip's
  bubble sits beside the letter column, `builder #8 #8` fixed, colony panel renders after the world (no one-frame lag).

Gates after the change: py_compile all; honesty self-test PASS (9/9 planted fakes caught); keepers self-test PASS; 26/26
titles fit; 300-frame and 2400-frame realtime self-tests: watchdog PASS (world rows), header PASS, vote acks 4/4 and 2/2,
honesty PASS with the planted `hollowghost` quarantined at boot; world panel avg 2.5 ms (max 6.4 ms steady, 28 ms once
at the hatch frame), scene avg 1.5 ms.

Still open: the cavern band is still mostly `#0B0E14` by design (85 % of the world region under lum 24, unchanged), so
the "empty stage" read is softened by texture and motion, not removed; the 320x180 lit>40 fraction is bounded by the
palette (5.7 % day / 4.1 % night by this tree's own measure, unchanged from the previous build measured the same way);
A/B/C letters still sit ~70 px above their platforms (moved down 5 px; the letter + count + names stack needs the room).

Addendum to 020 (18:52): open-world design pass returned **LONGGRASS** (154/180) — a side-view meadow
with a sky band; "seen from above" appeared only as a mood note. The owner had already chosen the
top-down camera from the mockups, so the spec step was re-run from cache with an owner directive:
re-project LONGGRASS's judged mechanics (nature-is-alive rule, chat-rate wind, real sun/moon and
seasons as ground light, damped never-cut camera, camp ladder, path wear, cairns, keeper raisings,
leading-verb rule, tile QA gate) onto a top-down open map with a 2-D camera and an honest minimap.
Art comes from the separate settlement-art workflow (stream/world/art, docs/ART.md).

---

## 021 — 2026-09-25 18:50 — Cave QA fixes hot-deployed; cave polish stopped; top-down pipeline

Cave QA round 1 fix pass (pass_with_fixes) synced into live-snapshot-v3: hot-reload re-executed
world/state, scenes/hollow and the world/ticker panels live (committed after 30 clean renders each);
compositor.py change applied with `scripts/deploy.sh` — compositor child restarted under the relay,
ffmpeg and relay pids unchanged, encoder never interrupted. Round 2 of that workflow was stopped: no
more effort on the cave; the honesty/label/sprite/verb-feedback fixes carry into the settlement.
Committed 63b9832. Remaining cave items (tile lit% gate, A/B/C letter height, hatch-frame 27 ms
warm-up) are moot after the swap.

Addendum to 020 (19:20): art studios reviewed by the owner (docs/art/studio-a|b|c): **Studio C
chosen** ("Yes studio C. But let's try to make the chars more people shaped. Not just shapes.").
Read as: keep C's bold clean outlines, palette discipline and stream-scale readability; redesign the
creatures as small people-shaped settlers (head, torso, arms, legs, ~2.5 heads tall, big expressive
heads and eyes, hair/hat/clothes from the name hash, real walk cycle, carry poses) — ours, warm,
Thronglet-level appeal, not abstract blobs. Grafts: A's dusk lighting, B's ground richness. The
running art workflow was stopped before its judge/bible steps; a focused settlers pass replaces it.

---

## 022 — 2026-09-25 20:05 — Settlement art canonical; LONGGRASS v0 build launched

Settlers art pass done (docs/art/settlers-round, settlers-tall → judges 91 vs 90 → bible):
`stream/world/art/` (creatures, tiles, buildings, props, hud) + `docs/ART.md`, final renders in
docs/art/final (busy 18:07, dawn, night 23:04 with the 0.55 floor, sheet, tile). Owner's direction
honoured: Studio C's clean outlines, people-shaped settlers with real limbs and walk cycles, name
colour dominant, tier gear (staff/lantern/satchel), one toy-cream face for all (no skin-tone gene),
explicit caricature-avoidance rule, explicit "ours vs Thronglets" section. Measured: settler sheet
0.75 s (must render off the frame loop; the 3 s hold covers it), ground paint 50 ms (background
bake), world compose 2.2 ms at 20 settlers. Committed c249d8b.

`agents/workflows/settlement-build.js` launched in **v0 preview mode**: Gate (terrain + nature +
bake with six real frames and timing; camera + land/state schema 2) → Modules (scene, behaviour,
world panel, verbs with the leading-verb rule, rounds/keepers/audio, copy) → Integrate (migration
on a copy of the live world.json, pre-bake, hot-reload swap test under the relay, probe) → QA
(stranger, honesty, art) → Fix. Deploy plan: hot-reload scene swap while the cave is on air
(OPENWORLD §14), swap-build.sh as fallback; owner told first either way.

---

## 023 — 2026-09-26 10:08 — Second overnight sleep; build resumed from cache

The Mac slept again overnight (22 pipeline exits since VOD 2 started: mostly `rc=224` broken pipes
on sleep and two watchdog restarts on stale liveness; supervisor reconnected on every wake, last at
00:03:49Z, Kick session start 00:04:00Z). Mac is now on AC and charging. The settlement build's
Integrate step died with the session; gate + all 8 modules are cached. Module work checkpointed as
bbb0ad8; build resumed (`resumeFromRunId wf_876c9b0b-2b9`, v0 mode): Integrate → QA → Fix run live.
Lesson stands (018): the stream needs an always-on host; a laptop lid is a single point of failure.

Addendum to 023 (10:20): owner asked in chat "What are the keepers? What do they do?" — the screen
does not explain itself. For the settlement fix pass: the keeper strip must carry a rotating plain
line ("keepers are the AI agents building this stream live · type !idea <what to raise>") and the
beacon a tooltip-style plate on first light of a session. Answered the owner in the terminal (no
chat posting by policy).

Addendum to 023 (10:32): owner in chat: "Change the colour to kick colours" — fell through as
plain chat (exact-token rule). Fix-pass test case for the leading-verb rule's theme table: "theme
kick", "kick colours", "make it kick coloured" → `!theme kick`. On-screen guidance when a message
mentions a known preset but no verb: plank hint "type !theme kick". Chat asks for `!idea gems` and
"go out of the cave" were classified carving-next (i-0005, i-0006).

---

## 024 — 2026-09-26 14:20 — LONGGRASS on air by hot-reload; owner's chat kill switch

Fresh session (HANDOFF.md). Integrate-only workflow run from disk: **pass_with_fixes** in 25 min. Fixes in the tree:
camera SAFE BAND (HUD_TOP_PX 152 / HUD_BOTTOM_PX 44, every mode's target lifted so framed people sit at region y ~274;
DRIFT survey starts from the framed point, no hand-over sprint; 100 % awake-in-view over three 900-frame runs),
SETTLER_SCALE 1.2 rendered at 2x and BOX-downsampled, waystone tallies centred under the letters, keeper strip alternates
`the keepers are AI agents building this show live`, plank `beacon lit · a keeper (an AI agent) is on duty · !idea <text>
asks for something` once per session, `chat_bridge.theme_phrase()` reads `kick colours` / `theme kick` / `make it kick
coloured` (<= 8 words, one preset + a theme word) as `!theme kick`. QA: honesty PASS; stranger FAIL (3 blocking) and art
FAIL (2 blocking) -> fix agent running at the time of writing; its output lands as a second hot-reload.

Incident during integrate: the agent's `pkill -f 'duty.py heartbeat'` killed the LIVE keeper heartbeat (pid 48689) for
69 s; restored from the repo tree (pid 38660) inside the 120 s freshness window, lantern never went dark. Lesson: test
harnesses must never pkill by pattern; kill only pids they started.

Owner gates run by hand on the current tree: (1) `hollowghost` planted in a schema-2 copy with a camp, flower and cairn
-> quarantined at boot, marks purged, 150 frames 0 violations; (2) real-time run: `gate_hidden` chatted, broadcaster
`!hide` landed 1 s into the hold -> plank `the wind took that one`, chat log `mod hid a user` (no target), never a pip
even after chatting again; control user hatched and was named; 480 frames, unknown-name draws 0.

Owner: "Do it" (deploy before the QA fix pass, wants to watch it progress on air). Staging copy /tmp/lg-deploy-stage
(compile, honesty/camera/chat_bridge/steading self-tests PASS, migration guard ok on a fresh live copy), backups
`live-snapshot-v3-pre-longgrass` and `run-live/world.json.bak-pre-longgrass-20260926T140956`, prebake into run-live/bake.
**Step 1** 14:12:28: compositor/chat_bridge/rounds/audio/state_store into live-snapshot-v3 + deploy.sh: relay held 20
frames (0.67 s), ffmpeg 40018 UNCHANGED. deploy.sh printed FAIL because relay_status.json caps `gaps` at 20 entries so
`len(gaps)` can never grow past it (fix: compare the last gap's start_ts, or use child_restarts alone). **Step 2**
14:13:46: world/*.py + art + scenes/steading.py + panels/*.py dropped together: HotReloader re-executed the world batch,
rebound hollow -> SteadingScene attached 14:13:48, world.json migrated 1 -> 2 in place (bak-v1-20260926T041348), 2 pips
2 camps, relay gap #36 = 5 frames (0.17 s), encoder never saw EOF, all panels committed after 30 clean renders. Note the
scene painted `ground-4471-0-o6-v1.npy` in 612 ms in the bake thread instead of loading the prebaked `-v3` files: the
prebake script's bake `ver` (3) does not match the scene's (1); harmless, fix the key. Title set via OAuth (token
refreshed from the kickapp code restored from origin/worktree-kick-ngrok-tunnel into /tmp/lg-kickapp; the worktree dir
is gone from disk while its receiver process still runs): `Say anything in chat. A creature walks out with your name`.
Kick HLS probe PASS 1280x720@30 2331 kbps; 3 watching at the swap.

Owner rule change (terminal, 14:08): exact `nuke` from the broadcaster account stops the stream, exact `init` restarts
it. Implemented as `scripts/ops_chat_switch.py` (outside world code): Pusher shape only, `atleastonce` + `broadcaster`
badge, whole message == token, fresh within 120 s, de-duplicated by id, 20 s cooldown; `nuke` TERMs the supervisor and
keeps kick_api/chat_listener alive so `init` can arrive; `init` double-forks supervisor.sh from live-current with the
RESUME.md env. Self-test caught a zombie-child bug (an init-launched supervisor read as alive after a later nuke) and a
tail-after-truncation miss; both fixed. Adversarial review (3 lenses) before it runs against run-live.

Addendum to 024 (14:38): review returned 3x fix_first (7 blocking: watcher crash on malformed badges, stale/recycled
pid files trusted, snapshot resolved at start-up, init-launched supervisor in the watcher's process group, cooldown
swallowing an emergency nuke after init, init success declared before an encoder exists, plus the overlaps); all fixed,
self-test grown to 59 checks (stranger pid never signalled, own process group, secrets scrubbed, symlink resolved at
action time, nuke 0.1 s after init, init failure when run.sh dies). Launched against run-live at 14:38 with
`env -u` for every secret (a Python-side pop does not hide the exec-time environment from `ps -E`); pid in
run-live/pids/ops_switch.pid, log run-live/logs/ops_switch.log, visible in status.sh. Not exercised live: the first
real nuke is the owner's.
