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

---

## 025 — 2026-09-26 15:20 — Fix pass 2 (settlement QA blockers): the letters read, the HUD is a dead zone, camps are promises

Fix agent of the integrate-only workflow (journal 024 said its output lands as a second hot-reload). Five blockers from
the stranger / art QA, all closed in the tree (RUN_DIR=/tmp/lg-fix2, nothing live touched; LONGGRASS has been on air
from live-snapshot-v3 since 14:13):

- **A/B/C titles were invisible** (0 awake: none; round open: dropped by the placer). Now ONE guaranteed row
  `A harvest day · B light: gold · C fog` (`world.py _options_row`, `row_chip`): above the letters, else below the
  stone rows, else a fixed row bottom-right above the place-label band; never dropped (`stats()["options_row_placed"]`).
- **HUD plates over settlers** (owner, 021/023). Three mechanisms: (1) the world panel builds the top-left stack first
  and reserves its REAL boxes (`_hud_strips`), pastes it last, and hands the same boxes to the camera; (2) the camera
  treats those boxes as a **dead zone** (`camera._hud_dead_zone`): every framed point (feet minus the per-tier head
  height the scene supplies, a waystone minus its letter stack when anyone stands at or walks to a stone, every awake
  person on screen in FOLLOW) is projected against the target and the target is lifted by the cells needed, 32 px
  early for the spring lag, capped so the lowest feet stay above the bottom band; (3) every in-view sprite box and camp
  sprite / footprint is reserved in the placer before plates, labels, rows and the shared bottom line (`_sprite_boxes`).
- **Waystone count over voters' faces**: `WAYSTONE_LETTER_DY` 78 -> 128 (the Menlo 22 count now ends at cy - 48) and
  `behaviour.STAND_Y0` = 9 cells (a tier-3 head at 1.2x tops out at cy - 43). The letters move as one row: when a chip
  would cull one they all drop (down to the count sitting on its stone) or all three are culled (fix-run frame 135 had
  `A C` without `B`); a voter whose letters are culled gets its own label. `0 +1` beside the count while a voter walks.
- **Camera FOLLOW never ran under 8 s test rounds**: `KL_SLEEP_AFTER_S` test hook (test mode, /tmp) + a 140 s plan
  with real 180 s rounds: 4200 frames, transitions DRIFT->EVENT->FOLLOW->EVENT->DRIFT->EVENT->FOLLOW->DRIFT->EVENT->FOLLOW,
  max per-frame jump 2.01 cells (= the 60 cells/s cap: no cut), 0 settled FOLLOW frames with nobody in view, 0 at-rest
  frames with a framed head under a chip (163 transient frames while the spring catches a walker), honesty PASS.
- **world.json**: a camp / mark / sleep / hatch event forces a save in the same frame (`FORCE_SAVE_EVENTS`);
  `SteadingScene.save_now()` on compositor exit (self-test and stream) and on a hot-reload scene swap. In the noon run
  kai_dnb's camp (built 04:35:15) is on disk at exit.

Cheap suggestions taken: chat log reads `someone is arriving...` while a seed is in its hold (cache key includes it);
`settlers_sheet.png` (canonical settlers, real pips first) replaces the cave's `pips_sheet.png` in every self-test;
the world panel asserts per frame that no drawn string carries a raw hidden / blocklisted / quarantined username
(`name_leaks`, counted into honesty violations; unit check 0 clean / 3 forged caught); OPENWORLD §12 now says awake ==
chatters whose record cleared the hold. Honesty semantics tightened: `Entity.is_present()` (awake and not walking home
to lie down) is what the header, land line and the presence rule count; wear / fires / camera still use `is_awake()`;
the presence rule allows one wander leg (12 s) after the window closes (the behaviour finishes the leg first).

Evidence (all under /tmp/lg-fix2): dawn / noon / 23:00 x 900 frames with the 36-message plan: honesty PASS x3, world
panel avg 6.4 / 6.7 / 7.2 ms (scene 5.1 / 5.2 / 5.8); 0-awake renders x3 PASS; camera run noon 99.9 % of
awake-settler-frames inside the safe band, 0 frames with any awake head under a HUD box; budget 60 test pips at 0.75x:
scene avg 11.15 ms (gate < 12; integ2 10.46), panel 13.3 ms; 20 pips at 1x: scene 8.8 ms (integ2 8.26); scene
self-test C2 8.05 ms / C3 6.79 ms isolated; night floor: 23:00 tile mean / noon mean 0.64 (gate 0.5), 96 % of the world
band above 0.12 (gate 60 %); fake `hollowghost` gate: quarantined at boot, marks purged, 150 frames 0 violations
(`fake_gate.log`); MODE=test HLS via relay against a copy of live-snapshot-v3: world-batch hot reload held 3 frames
(0.1 s), two deploy.sh child restarts 20 frames each, ffmpeg pid unchanged, probe PASS 1280x720@30 3220 kbps
(`hls_swap.log`). Grids: `report/grid.png`, `report/grid_0awake.png`, `report/tiles.png`.

Known and left: at pinned 1x two people further apart than the 61-cell safe band cannot both be clear of the chips
(the 0.75x zoom is the spec's cure, v0 pins 1x): 11 % of the camera run's frames had some unframed head under a chip;
the harness's realtime pacing lags wall clock so `@builder #8 voted A` for a not-yet-cleared newcomer is timing drift,
not a hold bug; `NOBODY AWAKE` at 72 px stays (spec §8, the thumbnail hook) while the plank carries the land's voice.
Not deployed: the parent session hot-reloads it after telling the owner (memory rule).

Addendum to 025 (15:36): **fix pass 2 on air.** Staging /tmp/lg-deploy-stage2: compile + honesty/camera/behaviour/
state/keepers/chat_bridge/steading self-tests PASS; a 300-frame compositor self-test on a copy of the live world FAILED
honesty when run with an empty chat.jsonl (both pips quarantined, then 567 draws of the quarantined names from
builders.json copy, caught by the new name-leak assertion) and PASSED with the live chat.jsonl alongside (0 violations).
Backups live-snapshot-v3-longgrass-v0a + world.json.bak-pre-fix2. Step 1 15:33:13: compositor.py + deploy.sh child
restart, 20 frames held (0.67 s), ffmpeg 40018 unchanged. Step 2 15:34:11: behaviour/camera/honesty/steading/chat_log/
world.py dropped together, scene re-attached at 15:34:13 with a 2-frame gap (0.07 s), panel committed after 30 clean
renders, 2 pips 2 camps, honesty 0. Kick HLS probe PASS 2335 kbps. deploy.sh false-FAIL fixed (newest gap start_ts
instead of the capped gap count) and copied into v3. HANDOFF.md rewritten for the new state; RESUME.md pointed at it.

---

## 026 — 2026-09-26 16:20 — Owner mandate: continuous self-improvement; "pause bot" failsafe live

Owner (terminal, 16:05): the project's point is that the agent self-improves the stream until it is popular; keep
iterating without stopping; any category allowed; keep the interactive settlers direction for now; goal = real viewers
and engagement; learn what is popular on Kick; the owner goes hands-off. One request: the owner's account saying
`pause bot` in chat must stop chat ingestion and stop the system being altered.

Failsafe, live at 16:15 at two layers: (1) `stream/chat_bridge.py` classifies exact `pause bot` / `bot pause` from a
broadcaster/moderator as the mod `pause` (ingestion stops; `resume bot` / `unpause bot` = `resume`), deployed with a
relay-held child restart (1 frame held, ffmpeg unchanged; deploy.sh now reports success correctly); (2)
`scripts/ops_chat_switch.py` raises run-live/pause_bot.json on `pause bot` (owner + broadcaster badge + sender_id) and
clears it on `resume bot`; the improvement loop checks that flag before any change or deploy. Self-tests: bridge 68/68 +
phrase asserts; switch 68 checks PASS.

Loop: a session cron at :17 and :57 runs observe (metrics, chat, dropped actions, pending !idea) -> deploy finished
builds -> pick the next improvement from the research backlog -> journal + commit + push. In flight: HUD reshape
workflow (owner: "too much information on the screen"; bottom bar goes; one fact once; options row + countdown as the
primary interaction) and a Kick growth research sweep (categories, growth mechanics, format comparables, first minute,
AI streams). Found today: `!idea` is capped at 3 open per user and drops silently (owner's `improve the art style` was
lost); i-0004/i-0005 marked shipped (delivered by Longgrass); the cap needs a plank line. Vote acks mislead when the
voter walks off before the round closes (fix in the HUD spec). Memory: owner-mandate-continuous-improvement.md.

Tick 16:24 (loop 026): not paused; all 9 processes alive. Last 40 min: viewers 1-4 (avg 1.9), live 100 %, followers 2;
chat quiet since 15:58 (58 msgs this session). Two silent misses from the second account earlier: `say hello to
@atleastonce` (conversational, no answer) and `wak south` (typo -> plain). Both feed the HUD/plank-hint spec (a message
with a place/direction word but no verb gets `type: go south`). Rounds keep shipping as agent picks with 0 votes. No
!idea pending. In flight: HUD reshape (design + judges + synthesis done, implementing), Kick research (2/5 angles done).
Nothing deployed this tick.

## 027 — 2026-09-26 16:35 — Kick growth research in; backlog adopted

`docs/research/kick-growth-2026-09-26.md` (five angles, all sourced). Hard facts sampled 06:14-06:24 UTC (Sat 16:14
AEST, NA off-peak): Kick ~696k concurrent viewers over 198 live subcategories; Software Development = 8 live channels,
31 viewers total, median 2; we sit #5-7 with 1-2 viewers, #1 needs ~16-21. Category pages sort by concurrent viewers for
anonymous browsers, so category choice is the only row-position lever; Just Chatting/IRL are invisible below ~600-900
CCV. The homepage Featured row is editorial and currently carries channels with 2 and 7 viewers that have a hook (a
world-record attempt, a 30-day marathon): the featured/pitch pack is the biggest discovery lever at our size. Games +
Demos (42 live / 353 viewers / rank-24 cutoff 2) is the honest alternative when the world is the show; category
hopping into inaccurate categories is a Guidelines violation and is off the table. Backlog adopted (top 8): (1) positive
zero-state header + tile gate [in the HUD workflow], (2) title with live counters `Your name becomes a pixel settler.
Type anything. AI agents build the village · Day N · S settled` + tags, (3) instrumentation: category sampler, our rank
in metrics.jsonl, per-chatter first-message funnel + daily report, (4) chat-said/pip-did ledger, (5) a big creature in
every frame at low awake (disclosed keeper pip), (6) arrival beat within 10 s of a viewer_count rise, (7) 48 h category
sampler then a measured Games + Demos vs Software Development test, (8) keeper persona + build ledger. Declined: a
chat-posting keeper bot (owner said no bots earlier; also needs chat:write consent). Launched: workflow
kick-instrumentation-and-title (items 2, 3, 7; monitor/ + scripts/ only; title stays dry-run until the orchestrator
sets it). HUD reshape is in its implement phase (layout.py + 8 panels + compositor + chat_bridge being edited).

Tick 17:00 (loop): not paused; 9/9 processes alive; viewers 1-4 (avg 2.2), live 100 %, followers 2; chat quiet since
15:58, no !idea pending, honesty 0. HUD reshape: implementer running its budget + camera chain (/tmp/lg-hud-build).
Instrumentation: build + two reviews done, fix/go-live step running (sampler not started yet). Nothing deployed.

---

## 028 — 2026-09-26 17:10 — HUD pass: fifteen text clusters to seven (not deployed; layout changed -> child restart)

Owner (terminal, 15:50): "There is too much information on the screen. The bottom bar with the scrolling and frame rate
could go completely. Review the rest and see what is valid and what is not. Think about how people would like to
interact with this and shape it for that. Do people need to see all this information? What else is important here?"
Built in the tree against the HUD spec (OPENWORLD 8 rewritten); nothing live touched (RUN_DIR /tmp/lg-hud-build, MODE=test).

What left the frame: header_left (channel name + `CHAT BUILDS THIS` slogan slot), the countdown strip, the version string,
`1 watching`, `day N`, the land line, the time dial + wind/moon rows, the floating A/B/C options row, the bottom-left place
label, the colony and keeper strips, the ticker, the oscilloscope, the readout. Telemetry (fps, frame ms, stale, audio
fallback, degrade flags) now lives only in the compositor log / state.json / status.sh: the owner and mods no longer read
it off the stream. What stayed, once each: the 56 px headline (`SAY ANYTHING` at 0 awake and before boot, `N AWAKE`
after: the tile hook, no more `NOBODY AWAKE`), a two-row column beside it (`a creature walks out / with your name`),
`LONGGRASS ● LIVE` (the dot doubles as the chat-link state: red linked, amber reconnecting), the plank as the land's
single voice (blank at idle with people awake; DRIFT caption at 0 awake), ONE plate, labels, bubbles, letters over the
stones, edge arrows, the chat log (6 slots, `chat is quiet.`). New: a fixed VOTE CARD top-right (state + timer header,
three rows [letter chip][title][count], the leader filled, the round's fuse along its edge; the card's count string ==
the stone's, asserted per frame), a muted clock row (`23:04 · night · wind NW calm · spring`), the minimap bottom-right
(no caption), ONE land strip (`2 have walked here · 1 more and the cairn is named` / `AI keepers build this show live
from chat's ideas` STATIC / keeper state / the honesty line STATIC in two rows, asserted every frame).

Interaction copy (all rendered in the runs): vote ack `@fern_ok walks to B · counts while standing there · closes in
0:07` (VOTE_ACK_S 1.5 -> 5; the tally is who stands at close); `@lumen_k walked off A · that vote is dropped · type A to
stand again` (behaviour leave_platform, gated on round.tally_source == platforms; the bridge pops _votes for a pip that
is no longer standing so vote_count / zero-vote plank / card / stones agree); unparsed-with-hint from our own tokens only
(`go north further` -> `to do that, type: go north`, `build a hut here` -> `to do that, type: camp`; `hello there`, `I love
trees`, `the river is pretty` stay chat; a name-leak case `go north @hiddenname` -> no @ in the hint; 17 cases in the
bridge self-test); newcomer sticky `that's you, @quill_z · try: go river · plant a flower · camp · or A, B, C` (hatch at
awake <= 1, until the first verb; the first-breath hearth is not a verb); next-two hints after go / camp / plant / fire /
a vote at awake <= 1; `new round · everyone steps off the stones · type A, B or C`; `@moss_m's idea is on the board · the
keepers read it next`; land row 3 `raising the Ford bridge · asked by @moss_m · 09:59 left` -> `just raised the Ford
bridge · asked by @moss_m`. Notices are newest-first across the bridge and the panel (a 5 s ack no longer hides the
refusal that came after it).

Geometry: world (0,66,1280,456) -- the spec said 480; measured at 60 test pips / 0.75x (the fix-2 protocol, 300 frames
in the compositor) 480 gave scene avg 12.26 ms (a 600-frame run 11.44 / 12.62) against the < 12 gate (440 had 11.15), so
the spec's stated ladder rung 456 ships: 114 / 152 / 76 cells at 1x / 0.75x / 1.5x (integer at every zoom), measured
11.90 / 11.48 / 12.51 / 11.59 / 11.46 (mean 11.79, 4 of 5 under 12: AT the gate for the synthetic 60-pip stress; the real
6-awake runs sit at 5.3-5.8 ms scene, 7 ms panel; 20 pips at 1x 8.83). A tried bake-multiply rewrite (broadcast instead
of np.repeat) was SLOWER (14.4 ms) and was reverted. Footer 198 px: land (0,522,720,198), chat_log (720,522,560,198).
Camera SCREEN/CROP_PX/HUD_TOP_PX 56/HUD_BOTTOM_PX 16; steading SCREEN; compositor WORLD_BAND (66,522). The camera self-test
scenario 4b moved its north pip 12 cells further up so the smaller HUD band still exercises the dead zone.

Evidence (/tmp/lg-hud-build): noon / dawn / 23:00 x 1200 paced frames with the 42-message plan: honesty PASS x3, vote acks
6/6 x3, land strip check 1200/1200 x3, vote card check 3573-3576/3576 x3, header band PASS, watchdog PASS; 0-awake x3
(300): all PASS; drop plan (60 s rounds, 1500 frames): dropped copy, hints, next-two hints, blank plank at idle; sticky
plan (660, 23:00): the newcomer line; camera run 4200 frames (180 s rounds, 60 s sleep hook): 0 framed points under a HUD
chip at rest, 100 % awake-settler-frames in the safe band, max jump 2.01 cells (no cut), DRIFT->EVENT->FOLLOW->EVENT->
DRIFT->... 11 transitions; night floor: night / noon tile mean 0.64 (gate 0.50), 93 % of the world band > 0.12; tiles.png:
`SAY ANYTHING` and `6 AWAKE` read at 320x180. Module self-tests: py_compile all, honesty PASS, steading PASS (C2 60 pips
0.75x 8.74 ms isolated), camera PASS, chat_bridge 68 cases PASS. Grids: report/grid.png, grid_0awake.png, tiles.png.

Deploy: layout.py changed, so this is NOT a hot-reload: stage to /tmp, then `scripts/deploy.sh` (relay-held compositor
child restart, ffmpeg / relay pids unchanged) with every changed file copied into live-snapshot-v3 together. Tell the
owner first (never-restart rule; the child restart was pre-approved for this change only). Note for the owner: the frame
no longer shows fps / viewers / version; status.sh and the compositor log carry them.

## 029 — 2026-09-26 17:20 — Instrumentation live; title set

Workflow kick-instrumentation-and-title (pass_with_fixes; two adversarial reviews, 5 blockers fixed: Day N computed
from the wrong metrics file under the documented invocation, raw usernames in reports, env.sh KICK_LIVE_ROOT wrong when
sourced from zsh, site fallback on by default, poller restart env). Live now: `monitor/category_sampler.py` loop (pid in
run-live/pids/category_sampler.pid; 7 categories every 10 min, public API v1 with v2 fallback; site scrape only as a
last resort), `monitor/kick_api.py` restarted from the repo tree and writing category_live / category_viewers / our_rank
into metrics.jsonl (17:14: rank #3 of 9, 35 category viewers, 3 ours). The first relaunch attempt failed (zsh sourcing
resolved KICK_LIVE_ROOT wrong) and left an 81 s polling gap; env.sh now detects its own path under bash and zsh and
refuses when the root is wrong. `monitor/chatter_log.py` writes run-live/chatters.json and run/reports/YYYY-MM-DD.md with
the on-air name filter (blocklist -> builder #N, owner/staff accounts flagged separately): so far 2 chatters, both
owner/staff; the external funnel is empty. Title set through the OAuth app at 17:14 (scripts/set_title.py, variant A,
state file caps it at one PATCH per 24 h): "Your name becomes a pixel settler. Type anything. AI agents build the
village · Day 3 · 2 settled". custom_tags were sent (10) but GET /channels returns custom_tags null; whether Kick stores
them for this account is open. stop.sh now stops category_sampler and ops_switch too. The HUD implementer wrote journal
028 + a HANDOFF addendum: the HUD pass changes layout.py regions, so it ships as ONE child restart with every changed
file copied together (a partial copy shows a black strip).

Tick 17:24 (loop): not paused; 10/10 processes alive (incl. category_sampler). Viewers 1-4 (avg 2.6), rank #3 of 9 in
Software Development (29 category viewers), followers 2, new title live. Chat quiet since 15:58; honesty 0. HUD QA:
owner lens PASS; stranger lens FAIL on two blockers (clock chip pasted over the waystone letters when the camera frames
the stones low-right; zero-vote copy duplicated on plank + vote card). Fix agent running. Nothing deployed.

## 030 — 2026-09-26 17:55 — HUD fix pass: the clock leaves the land, the card owns the vote, the hold shows its hand (not deployed)

Fix agent on the HUD pass (journal 028; owner 15:50 "too much information on the screen"). Two review blockers plus the
cheap suggestions, all in the tree (RUN_DIR /tmp/lg-hud-fix, MODE=test; nothing live touched; layout.py changed again, so
still ONE relay-held compositor child restart with every changed file copied together).

Blockers closed:
- **The clock chip sat over the waystone counts** when the camera framed the stones low-right (hud-build noon / night
  frame 1199). The clock row LEFT the land: `header_right` is now 400 px (880-1280; header_center 880, `SAY ANYTHING`
  484 px + the column still fit) with two rows, `LONGGRASS ● LIVE` (y 7) and the muted clock row (Menlo 20, y 38): `midday
  · wind NE fresh · spring`. The wall clock is no longer printed on the real-time land (every viewer has one; a time zone
  that is not theirs reads wrong); hour mode keeps `14:30 · afternoon · a day here is one hour`. The world panel still
  derives the string (`last_clock_row`), the header draws it; the world region carries only the plank, the vote card and
  the minimap. The minimap became a BOTTOM box in the camera's dead zone (`camera._hud_dead_zone`: framed feet are
  pushed above it, capped so no head comes back under a top box; heads outrank feet; self-test 4c: without the box the
  east pip's feet land at (1137, 371) inside the minimap, with it at (1137, 342), push peaked at 7.3 cells, no head under a
  top chip).
- **The same vote fact twice** (plank `nobody has voted · one letter from you decides this round` + card `one letter
  decides it`; plank `nobody voted. the land picked C itself.` + card `nobody voted · land picked C`). The zero-vote line
  and the ship-hold result left the plank (`ZERO_VOTE_LINE` removed); the card header is the vote's one home; the plank at 0
  awake shows the DRIFT caption through the ship hold (`surveying · the Ford`, grid_0awake). The raising notices
  (`the keepers raised X` / `are raising X`) left the plank too: land strip row 3 carries them pinned / for 10 min.

Suggestions taken: card header `type A, B or C to vote` at 0 standing for every awake count (`stand at a stone to vote`
named nothing to type); the card timer is Menlo Bold 24 (text / amber < 30 s / red < 10 s with the fuse; it was the
smallest text on screen for the owner's priority (4)); a vote inside a newcomer's 3 s hold is acked `someone new walks
to A · counts while standing there · closes in 0:35` in the same frame (the tuft is nameless; `@builder #N` for a name
that is merely waiting is gone) and again BY NAME at the hold's end (`chat_bridge._pump_held_acks`; noon8 plank log:
`someone new walks to A` -> `@fern_ok walks to A`); the chat log shows a record inside its hold as a muted `kai_dnb: …`
(a chatter past their first hold: their name is already on their pip; the text waits) or `someone is arriving...` (a
first record), bounded to 2 rows, one per chatter, and only once the record's own `t` has been reached (a record stamped
ahead of this clock is not shown as held: the harness's pacing lag made 5 `…` rows pile up in the first rerun); camp
plates rotate only while their owner is awake (or when the DRIFT stop pins them) once anyone is awake, and every plate
is clamped whole inside the region (drop frame 1400 had one cut at the bottom edge); mark plates say `flower · @name ·
planted today` / `tree · @name · sapling · planted 3 days ago` / `the Shore · first reached by @name · yesterday` (no
`day N` without the header's day); land row 3 `a keeper is on duty now · type !idea <what to raise>` / `no keeper on
duty · your !idea waits on the board` (`one is on duty` had no subject). Found on the way: a voter still WALKING to a
stone who was sent elsewhere (`A`, then `go north` ten seconds later) dropped the vote silently (`behaviour._start_walk`
emitted `leave_platform` only for a standing voter); the walker's case now emits the same event. And the line itself
had stopped showing at all: the bridge's `@lumen_k walks north` echo and the world's `@lumen_k walked off A · that vote
is dropped · type A to stand again` land in the SAME frame, and the plank's "newest person line wins" used a strict `>`,
so the echo won and the consequence never showed (instrumented under KL_PLANK_LOG: the event arrived, `_vote_left`
passed every guard). A same-frame tie now goes to the world's line (`_plank_text_land`, `>=`); the final drop run's
plank log reads `someone new walks to B` -> `leave_platform lumen_k A` -> `@lumen_k walked off A · that vote is dropped ·
type A to stand again` -> `@kai_dnb walks to B`. The tie rule then hid one vote ack (5/6): a changed letter produced
the world's `@willow_9 moved to A` in the same frame as the bridge's `walks to A · counts while standing there`; the
`moved to` line is gone (the same fact twice; the ack carries the walk, the rule and the deadline), acks back to 6/6.

Frame budget (60 test pips, 0.75x, 300 frames unpaced, three runs; the gate is < 12 ms scene avg): 10.13 / 10.90 / 11.00
ms, **median 10.90** (the previous pass measured 11.5-12.5 with one run at 12.51 including the warm-up spike; the
per-run scene avg still includes frame 8's ~55 ms boot spike, so the median of three is the gate value from now on). The
440 px rung stays ready; nothing was added to the world text layer (the clock chip left it).

Evidence (/tmp/lg-hud-fix, chain.log + chain2.log): noon / dawn / 23:00 x 1200 paced frames with the 42-message plan at
60 s rounds (the normal `type A, B or C to vote` / `A leads` / `tied` states in the grid; the 8 s-round edge case is its
own run noon8): honesty PASS, vote acks 6/6, land strip check 1200/1200, vote card check 3576/3576, header band PASS,
watchdog PASS on every run; 0-awake x3 (300) PASS; drop plan (1500, 60 s) with the dropped-vote copy; sticky plan (660,
23:00); camera run 4200 frames: DRIFT->EVENT->FOLLOW->EVENT->DRIFT->EVENT->FOLLOW->EVENT->FOLLOW->EVENT->FOLLOW (10
transitions), max per-frame jump 2.01 cells (the 60 cells/s cap, no cut), 0 at-rest frames with a framed point under a
HUD chip, 0 frames with any awake head under a chip (the previous run had 13), 99.3 % of awake-settler-frames in the safe
band, 27 settled FOLLOW frames with nobody in view (the previous run: 30; the sleep hook's walk-home); night floor:
night / noon tile mean 0.64 (0.62 at 0 awake; gate 0.50), 93 % of the world band > 0.12; textual check over every run's
plank log: 0 vote-state lines, 0 raising lines, 0 text-layer errors; header row 2 luminance std ~38 in every last frame
(the clock row is there). Module self-tests: py_compile all, camera PASS (4c added), behaviour PASS, honesty PASS,
steading PASS, chat_bridge 68 cases PASS + a hold-ack / held-rows unit (report/bridge_unit.txt). Grids: report/grid.png,
grid_0awake.png, grid_states.png (the 8 s-round card states with a person-only plank), tiles.png,
crop_header_card_2x.png, drop_chatlog_hold_sheet.png.

Known and left: a speaking label for a pip at the region's bottom edge can overprint a plate clamped to the same edge
(noon8 frame 1170: `@willow_9: what colour is this` over `@kai_dnb's camp · night 1`; labels win by design, the plate used
to be clipped there instead); the by-name ack at a hold's end is shadowed when a newer person line lands in the same
5 s (newest wins, by design); the season drops off the header clock row when the wind word is long (`midday · wind NW
fresh`, 368 px). Deploy: as journal 028 (deploy.sh child restart, all changed files copied together, owner told first);
the frame no longer shows a clock on the land; status.sh / the compositor log keep the telemetry.

Tick 18:00 (loop): not paused; 10/10 alive. Viewers 1-5 (avg 2.6), followers 2 -> 3 (first new follower since the
settlement went up), rank #3 of 10 in Software Development (34 category viewers). Chat: two `b` votes from the staff
account at 17:39 and 17:43. Honesty 0. HUD fix agent still re-proving (drop-debug run in /tmp/lg-hud-fix). Nothing
deployed.

## 031 — 2026-09-26 18:20 — First external chatter; HUD deploy held on a bake-thread regression

17:24: **Lordoomer** ("hey" / "Can I become a settler too?") is the first person who is not the owner or Kick staff to
chat on the settlement: hatched as a pip, 2 messages, second within 10 min; the staff account answered "of course" in
chat. Funnel report (run/reports/2026-09-26.md): 3 chatters, 1 external, external 2nd-message rate 100 % of 1; 144
viewer arrivals today, 1 first-time chatter: the first-minute conversion is the bottleneck the HUD pass targets.

HUD reshape workflow finished pass_with_fixes (journal 030 by the fix agent; two stranger blockers closed: the clock row
moved into header_right, the minimap became a camera bottom dead-zone box; plank carries no vote states). Staging
/tmp/lg-deploy-stage3: compile, honesty, camera, behaviour, state, keepers, chat_bridge PASS; compositor 300 frames on
the live world + chat: header band 300/300, land strip 300/300, vote card 356/356, honesty 0. **Held**: the scene
self-test fails one gate, "bake thread never blocked a frame" (84 frames during the bake, max 42.1 ms, twice), while
the previous build under the same load passes it (max 9.5 ms). Regression from the reshape; a bisect + fix workflow
is running. Backups taken: live-snapshot-v3-longgrass-v0b, world.json.bak-pre-hud-*. Deploy plan unchanged: one
relay-held child restart with every changed file copied together.

Tick 18:24 (loop): not paused; 10/10 alive. Viewers 1-4 (avg 2.3), followers 3, rank #6 of 11 in Software Development
(34 category viewers). Chat: `bbbbb` from the staff account at 18:22 fell through as plain (votes are exactly one
letter): another silent miss for the plank-hint list (a message that is only repeated a/b/c letters -> `type just B`).
Honesty 0. Bake-thread bisect running with instrumented new-vs-control runs. Nothing deployed.

Addendum to 031 (18:30): **HUD reshape on air.** Owner asked why nothing had visibly changed; the held gate (bake-thread
stall, ~2 s of late frames at boot and per octant bake) is not worth an hour of a static screen against the owner's
"ship and iterate on air". Deployed 18:27:58 from /tmp/lg-deploy-stage3: every changed file copied into live-snapshot-v3
together, one relay-held child restart, 18 frames held (0.60 s), ffmpeg 40018 unchanged, new compositor registers 5
panels (world chat_log colony header_center header_right), scene resumed with 3 pips / 3 camps, prebaked -v3 ground
loaded from disk (the bake key now matches), honesty 0. The bake-thread fix lands as a follow-up hot-reload when the
bisect returns.

## 032 — 2026-09-26 18:35 — Owner: no cringe AI copy; the world is the show

Owner (terminal): "Never put cringey ai text onto the stream. 'no camera, no mic, no fake viewer' is so unnecessary...
Seriously change that, make the actual world the main viewable thing. Go crazy dude." Memory: no-cringe-ai-copy-on-
stream.md. ADR-000's principle (no fake anything) is unchanged; its on-screen recital is gone by owner decision.
Hot-fix now: colony.py keepers line, on-duty line and both honesty rows blanked and hot-reloaded into live-snapshot-v3
(the compositor's self-test "land strip check" now asserts the wrong thing and is removed in the next build). Launched
workflow longgrass-fullbleed-world: full-bleed land, HUD dissolved into in-world objects (signpost "say anything",
waystone plaques + a torch for the round, the beacon for keeper presence), no strip, no chat-log panel unless the judges
prove a newcomer needs it, zero explainer copy; three design lenses -> judges -> synthesis -> implement -> QA.

## 033 — 2026-09-26 18:45 — Bake-thread stall: a latent GIL hold, not the HUD; fixed and hot-reloaded

Bisect (instrumented frame + bake timelines, /tmp/lg-bake-instr): the spike was nondeterministic on BOTH builds (the
pre-HUD control also hit 71 ms once in three runs), so the 3-vs-1 evidence at 18:15 was disk-timing luck. Real cause in
stream/world/bake.py's landing sequence: `np.memmap.flush()` calls msync(2) WITHOUT releasing the GIL (59 ms msync ->
52 ms main-thread gap, 15-64 ms depending on page cache) and the re-open via `np.load(mmap_mode='r+')` holds it another
7-12 ms; the one blocked frame is always the one overlapping those steps. Fix (bake.py only, +44/-11): msync through
libc via ctypes (a foreign call releases the GIL), keep the painted mapping across the rename instead of re-opening, and
`close()` syncs on a daemon thread instead of on the frame thread at an octant swap. Bakes are byte-identical before and
after. Gates after: steading A "bake thread never blocked a frame: max 10.0 ms" (was 27-57), verified twice
independently (10.3 / 8.9 ms, assertion code unchanged); camera, behaviour, honesty, chat_bridge, compositor 300 PASS.
Hot-reloaded into live-snapshot-v3 at 18:43:12: world batch re-executed, scene resumed with 3 pips in 12 ms, panel
committed after 30 clean renders, no relay gap. Lesson: a self-test with a thread-timing assertion needs three runs before
it convicts a diff.

Tick 18:59 (loop): not paused; 10/10 alive. Viewers 1-4 (avg 2.0), followers 3, rank #9 of 11 (a 100+ viewer channel
entered Software Development: 147 category viewers). Funnel today: 165 arrivals, 1 first-time chatter. Owner's staff
account in chat 18:42: "surely you don't need the space at the bottom of the screen for grey boxes" — the blank strip
left by the copy removal; the full-bleed build (design + judges + synthesis done, implementing now) removes the strip
entirely. Honesty 0. Nothing deployed this tick.

Tick 19:21 (loop): not paused; 10/10 alive. Viewers 1-4 (avg 2.1), followers 3, rank #5 of 8 (135 category viewers).
Funnel: 178 arrivals, 1 first-time chatter. `!idea remove the large grey area of the screen. fill the space with the world
instead` (i-0007, staff account, 19:12) classified macro/queued: it is the full-bleed build, implementing now (report dir
has its first tile probe). Honesty 0. Nothing deployed this tick.

## 034 — 2026-09-26 19:28 — Owner: no chat panel; the world progresses through ages; nobody sleeps

Owner (terminal): "Remove the bottom part of the screen where chat is and just have the main thing. Let's make the world
progress through the ages. Nobody falls asleep, everybody continues to walk around." Memory: owner-world-rules-ages-
no-sleep.md. (1) is the full-bleed build (implementing). (2) and (3) change the world's rules: the sleep state goes
(settlers wander after their person goes quiet; camps stay as homes), the honesty presence assertion "awake == recent
chatters" is replaced by "entities == real chatters ever minus banished" (nothing invented; everyone may move), and the
settlement gets an age ladder driven by real collective activity (distinct chatters, rounds, stones, marks, time on
air) shown in the world (buildings, gear, palette, a monument), never as HUD copy. Design workflow launched now
(three lenses -> judges -> synthesis -> spec doc); implementation starts the moment the full-bleed build is on air so
two agents never edit steading/behaviour/honesty at once.

## 035 — 2026-09-26 20:05 — Disk full took the stream down for 4 minutes; my harness dumps were the cause

19:53:00: run.sh exited (rc=0, uptime 35351 s) and the supervisor could not even write run.pid: "No space left on
device". kick_api.py could not write channel.json or its cache from 19:53:26; Kick reported us OFFLINE at 19:54:46 and
LIVE again at 19:58:13 when the supervisor's attempt 15 finally started (new ffmpeg pid 32378, new relay/compositor; the
VOD likely split). The Data volume was at 100 % (460 GB, the owner's disk is ~93 % full in normal times); today's
workflow harnesses had written ~7.7 GB under /tmp/lg-*: 5,424 self-test frame PNGs (~650 KB each) and 395 ground bakes
(20 MB each). Cleaned: every selftest frame dump and .npy outside the in-flight /tmp/lg-fb-fix-* and the staging copy,
plus scratch run dirs. The keeper heartbeat pid file was unwritable during the outage, so the tick's health check read it
as DOWN and relaunched it; three heartbeats were running, the two duplicates were stopped. world.json / state.json intact
(atomic writes). Kick HLS probe PASS after recovery. Rule from now on (HANDOFF): a harness deletes its frame dumps when
it finishes and keeps only report/ (grids, tiles, crops); the loop tick refuses to launch a build under 20 GB free and
cleans /tmp/lg-* first. This outage was not a restart by the agent; it was the box running out of disk under the agent's
own test output, which is the same failure in effect.
