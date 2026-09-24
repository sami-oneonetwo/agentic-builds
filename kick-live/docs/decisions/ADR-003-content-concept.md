# ADR-003: Content concept — SHIP IT LIVE (chat rebuilds the stream every 3 minutes)

Status: accepted (2026-09-24, synthesizer step of Workflow 1; owner may overturn)

## Context
PLAN.md Phase 3 called for a judge panel to pick a stream concept that a headless Mac can run with
no camera, no mic, no copyrighted music, no fake engagement (ADR-000), and that a channel with 2
followers can use to convert directory drive-bys into chatters. Five persona agents each proposed a
concept as a reframe of the plan's "AI Live Lab" candidate. Three judge agents scored each on
hook-in-5-seconds, reason-to-stay, reason-to-chat and feasibility (10 each, 40 per judge, 120 total),
named grafts worth taking from the losers, and listed fatal flaws. Two judges picked Concept 3;
one picked Concept 5 with Concept 3 second. The judges also had the measured A/V harness from
Concept 5's author (`/tmp/kl-avtest`: two FIFOs into ffmpeg, 150 frames, 0 over budget, 0.999x).

## Decision
Build **SHIP IT LIVE** as specified in `docs/CONCEPT.md`: a stream whose content is itself. A
compositor-owned 180 s round lets chat vote with a bare letter (A/B/C) on a parameter patch that is
applied instantly from `state.json` (micro-ship), while the building agent works real code changes
on a 15-20 min clock that hot-reload into the running compositor (macro-ship). Version number,
scoreline, patch-note ticker and voter names are all derived from real events and real chat.

Grafts adopted from the other four concepts:
- From HOT RELOAD (5): the proven two-FIFO lockstep A/V pipeline (1600 samples per frame,
  h264_videotoolbox), frame-time guard and 2 s watchdog, generative canvas as a stage option and
  attract background, real oscilloscope, non-BMP stripping.
- From SHIP CLOCK (2): SHIPPED/FAILED scoreline in the header, auto-cut of the stage to a status
  view after 20 s without diff changes, rising tick for the last 60 s of a macro deadline,
  Karplus-Strong pluck per chat message pitched from the username, 8 fixed legible theme presets,
  `!ask` responder via the local `claude` CLI (no API key on the box).
- From SHIP IT LIVE v1 (1): Founders strip, honesty ticker line, chat-link dot from Pusher
  ping/pong, `aevalsrc` fallback bed from minute one, 320x180 legibility QA, commit hash on cards,
  cooldown notices when a rate-limited command is rejected.
- From Built By Chat (4): persistent builder numbers in `builders.json`, requester name in the
  CHANGELOG commit, badge-gated moderator commands with a 3 s render hold, visible
  `declined: <reason>` for ideas, explicit `no agent on duty` state, pre-rendered WAV loop as a
  second audio fallback, end-of-session credits roll.

Fatal flaws removed from the winning concept as proposed:
- Bare-letter votes count only when the trimmed message is exactly `^!?[abc]$`.
- The ballot instruction reads `MOST VOTES SHIPS`, not `FIRST VOTE DECIDES`.
- Micro-ships never move regions or change font scale (the proposal's chat-side and panel-toggle
  swaps wrecked thumbnail consistency); they change colour, content, audio and stage mode only.
- The 2 s full-frame ship flash becomes a ≤ 400 ms fade over the stage body with the header intact.
- `!revert` (3 chatters in 60 s) is deferred to v2 and not advertised.
- `!ask` is hidden from all on-screen copy until a responder is running with measured latency
  under 60 s.
- Word filter, URL strip, non-BMP strip, length cap, per-user rate limit, 3 s hold, username
  filter and a mod kill switch are go-live prerequisites, not later ships.

## Alternatives considered

| Concept | Judge 1 | Judge 2 | Judge 3 | Total /120 | Why not |
|---|---|---|---|---|---|
| **3. SHIP IT LIVE — chat rebuilds this stream every 3 minutes** | 34 | 32 | 30 | **96** | Chosen. Only concept whose cadence promise is keepable by construction (micro/macro split) and the lowest-friction chat mechanic on the panel. |
| 5. HOT RELOAD — the stream that rewrites itself | 30 | 31 | 32 | 93 | Best thumbnail (a picture, not text) and best-evidenced feasibility, but a generative canvas is a screensaver: weakest stay, the hook sentence was on screen only 20 s in 3 min, and viewers have no personal stake in a canvas. Its pipeline and canvas are grafted in. |
| 2. SHIP CLOCK — timed rounds | 29 | 29 | 29 | 87 | Strongest dramatic frame (match, scoreline, FAILED state) but 12-minute rounds of real code will fail repeatedly under one agent that is also building the stream, 9 regions at 18 px is the densest layout, and a 40 px clock is ~10 px in the thumbnail. Scoreline, auto-cut, ticks and plucks are grafted in. |
| 1. SHIP IT LIVE — chat is the product manager | 28 | 27 | 27 | 82 | Good 56 px headline, but a real-code deploy every 5 minutes is not keepable so the countdown would lie, arbitrary `#hex` themes produce illegible frames, and `-use_wallclock_as_timestamps` on both piped inputs causes drift with a FIFO. Its Founders strip, honesty line and fallbacks are grafted in. |
| 4. Built By Chat | 27 | 26 | 26 | 79 | Best community layer and safest engineering (looped WAV, badge moderation) but a 20-minute cadence with a 34 px largest text is retention-fatal for drive-bys. Its builder numbers, moderation design and fallbacks are grafted in. |

Also considered and rejected: staying with the plan's original "AI Live Lab" activity-log framing
(all five personas independently reframed it because code scrolling has no stakes and no moment);
and any form of synthetic viewers or chat to seed the empty state (ADR-000).

## Consequences
- The compositor owns the 3-minute cadence and needs no agent to keep it, so the stream stays
  honest and alive when no Claude Code session is attached; the `no agent on duty` state is shown
  whenever `agent.heartbeat_ts` is stale.
- Every ship is a real commit (`docs/CHANGELOG.md` line with the requester's name), so the repo
  will accumulate roughly 20 small commits per streamed hour on the live branch. Accepted: the
  version number must map to something a viewer could check.
- Hot-reloading agent-written code into the encoder-feeding process is a self-inflicted outage
  risk; the frame-time guard, watchdog and last-good-frame rule are mandatory and a parent/child
  compositor split is the v2 hardening.
- Rendering stranger text on a public VOD from a brand-new account with no human present is the
  main ban vector; the §7.1 moderation pipeline blocks the first live frame until it exists, and the
  owner keeps the broadcaster account open for `!hide`, `!pause` and `!kill`.
- Kick's tolerance of a fully automated no-human broadcast is an unverified assumption the owner
  must check before a multi-hour run.
- Discovery is unchanged by this decision: without the owner's title/category change, `STREAM_KEY`
  and promotion (journal 002), the concept converts only the handful who arrive. The 100-viewer
  target is the owner's and the report will state the real numbers.
- The go-live cut (about 6.5 h) ships with `aevalsrc` audio, no canvas and no `!ask`; those land
  afterwards as the first on-air macro-ships, which is the content the concept promises.
