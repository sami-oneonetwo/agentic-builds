# SHIP IT LIVE — build-ready spec

Channel `atleastonce` on kick.com. Written 2026-09-24 by the synthesizer step of Workflow 1
(5 persona concepts, 3 judges, this document). Starting point is the top-ranked concept
("SHIP IT LIVE — chat rebuilds this stream every 3 minutes", 96/102 across three judges) with the
judges' grafts folded in and every flagged fatal flaw removed. See ADR-003 for the choice and
ADR-000 for the rule that governs everything below: **every number, name and vote on screen is real.**

Companion files this spec assumes: `scripts/env.sh` (paths), `monitor/chat_listener.py`
(`run/chat.jsonl`), `monitor/kick_api.py` (`run/metrics.jsonl`), `stream/run.sh` (one ffmpeg),
`stream/supervisor.sh`, and the proven two-FIFO harness at `/tmp/kl-avtest/gen.py` + `run.sh`
(150 frames, 0 over budget, speed 0.999x, 5.00 s video and 5.00 s audio, h264_videotoolbox + aac).

---

## 1. Identity

| Field | Value |
|---|---|
| **Name** | SHIP IT LIVE |
| **One-liner** | A stream whose only content is itself: every 3 minutes chat votes with a single letter on what changes next, AI agents apply or build it on screen, the version number ticks up, and the voter's name goes into the patch notes. |
| **Stream title** (57 chars) | `AI rebuilds this stream every 3 min. Chat votes A, B or C` |
| **Kick category** | Software & Game Development (never Just Chatting: a text screen at 0 viewers is invisible there and on page one here) |
| **Channel description** | This stream rebuilds itself while you watch. Every 3 minutes chat votes A, B or C on what changes next, AI agents build it live, and the person who picked it goes into the patch notes. No camera, no mic, no fake viewers: every number on screen is real. |

Fallback title for A/B in later rounds (the loop may test both): `This stream rebuilds itself every 3 min. You pick: A, B or C` (60 chars).

---

## 2. The pitch

### Hook in 5 seconds
A scroller in the Kick directory sees a 320x180 thumbnail. Only the header survives that size, so
the header is the whole hook: a **56 px version number** (`v0.3.12`), a **full-width countdown bar**
shrinking toward zero, and the words **NEXT SHIP 01:23** ticking. Something is about to happen and
you can see exactly when. On opening the stream, within 5 s: the stage is typing a real diff (or
evolving a generative canvas), the activity feed lands a new line every few seconds with a soft
click, the ballot at the bottom shows three big letter cards and the instruction in 40 px type,
**TYPE A, B or C IN CHAT. MOST VOTES SHIPS.**, and an 85 BPM lo-fi pulse is already playing. If the
viewer lands in the last 10 s of a round they hear the rising tick and see the reveal. If they land
on an empty chat they read, honestly, `chat is empty. be the first: type A`.

### Reason to stay
Two-tier cadence, because an agent cannot honestly build an arbitrary idea in 3 minutes:

- **Micro-ships every 180 s, guaranteed.** The ballot options are parameter patches the compositor
  applies itself from `state.json` (palette, canvas rules, audio pattern, ticker wording, and so on).
  They need no agent to finish anything, so the countdown never lies and a stranger is never more
  than 3 minutes from a visible reveal.
- **Macro-ships on a 15-20 min clock, real code.** The agent takes the top `!idea`, writes Python in
  `stream/scenes/`, and the compositor hot-reloads it without dropping ingest. If the reload throws
  or blows the frame budget, the stage shows `BUILD FAILED, reverting to v0.3.11` with the traceback.
  Failure is content, and the header keeps a running `SHIPPED 12 · FAILED 2` scoreline.
- **Social proof.** The ticker scrolls the last ten versions with the real chatter who picked each
  (`v0.3.11 @sam: palette ember`). Seeing other people's names on the product is what turns a
  visitor into a voter. The Founders strip keeps the first ten chatters of the session on screen for
  the whole stream. First-ever chatters get a permanent builder number that persists across sessions.
- **Empty-state honesty.** At 0 votes the ballot says `Nobody voted. Agent picked C. Next one is
  yours.` Never a fake voter, never a fake name, never a padded number.

### Reason to chat
The lowest friction on the platform: **a single bare letter counts**. Not `!vote a`, just `A`.
Within one second the voter's name appears under the card, the tally bar grows, and a blip plays a
semitone higher than the last vote. Name-on-screen within one second of one keystroke is the whole
lurker-to-chatter conversion. Every plain message (not just votes) gets a visible pulse in the chat
pane and a Karplus-Strong pluck pitched from the username, so typing anything is acknowledged.
Second ask: `!idea <text>` puts your text on screen as NOMINATED and makes it a real option within
3 minutes or a real code change within 20. Third: `!theme <preset>` repaints the whole stream for
everyone on the next frame with `@name set theme: ember` in the header. When a rate-limited command
is rejected, the screen says why (`theme cooldown 41 s`) so the second person to try never sees
nothing happen. The stream cannot post in chat, so the screen is the only reply, which forces every
reaction to be visual, public and immediate.

---

## 3. Layout (1280x720)

Canvas 1280x720, base `#0B0E14`, 16 px inner padding in every region, regions never move and never
change font scale (micro-ships may change colour, content and mode, never geometry). Body text is
22 px minimum; nothing on screen is under 20 px. `HN` = Helvetica Neue, `AB` = Arial Black.

```
 x: 0                                                        840                  1280
+-------------------------------------------------------------+----------------------+ y=0
| HEADER  wordmark | v0.3.12  NEXT SHIP 01:23 | SHIPPED 12 FAILED 2 | LIVE 3 watching |
|============================ countdown bar (y 66-72) ===============================| 72
| STAGE title: BUILDING v0.3.13: palette ember, picked by @sam | CHAT pinned strip    | 72-112
|       step bar 3/5 rendering test frame                      | CHAT messages        |
|       body: diff typewriter | canvas | test | Q&A | result   |   (10 lines, 22 px)  |
|                                                             |                      | 372 / 384
| ACTIVITY FEED  4 lines from activity.jsonl                  | founders strip       | 384-412
|                                                             | ASK / ANSWER card    | 412-536
|                                                             |                      | 492
| BALLOT  [A ....] [B ....] [C ....]                          | NEXT UP (macro queue)| 536-656
|         TYPE A, B or C IN CHAT. MOST VOTES SHIPS.           |                      | 656
| TICKER  patch notes / commands / honesty line        | SCOPE  | chat 0.4/min 30 fps |
+-------------------------------------------------------------+--------+-------------+ 720
                                                       880      1040
```

| # | Region | Box (x, y, w, h) | Content | Font | Updates |
|---|---|---|---|---|---|
| 1 | **Header, left** | 0, 0, 300, 66 | `atleastonce · SHIP IT LIVE` wordmark; chat-link dot (green live / amber reconnecting, driven by Pusher ping/pong) | HN Medium 22 | On state change |
| 2 | **Header, centre** (the thumbnail) | 300, 0, 620, 66 | Version `v0.3.12` at 56 px; to its right `NEXT SHIP 01:23` at 24 px; during a macro build a second line `MACRO v0.4.0 in 14:02` at 20 px | AB 56 / Menlo 24 / Menlo 20 | Every frame (clock) |
| 3 | **Header, right** | 920, 0, 360, 66 | `SHIPPED 12 · FAILED 2` scoreline; red LIVE dot + `3 watching` (real `viewer_count`, `--` if the poll fails or the stream is not live) | Menlo 22 | Scoreline on ship; viewers every 15 s |
| 4 | **Countdown bar** | 0, 66, 1280, 6 | Full-width bar shrinking right-to-left across the 180 s round; accent, amber under 30 s, red under 10 s | none | Every frame |
| 5 | **Stage, title row** (current task) | 0, 72, 840, 48 | `BUILDING v0.3.13: <option title>, picked by @name` or `agent's pick`; right end: current scene name chip | HN Bold 28 / Menlo 20 | On round start / ship |
| 6 | **Stage, step bar** | 0, 120, 840, 16 | 5-segment PLAN › EDIT › TEST › SHIP › LIVE rail, active segment pulses (1 Hz sine, no strobe); label `3/5 rendering test frame` | Menlo 20 | Every frame (pulse), label on step |
| 7 | **Stage, body** (what the agents are doing) | 0, 136, 840, 236 | Mode-switching (see §4): DIFF typewriter of the real `git diff` at 40 chars/s, 8 lines; CANVAS generative sim; TEST/STATUS output; ANSWER card; RESULT card; ATTRACT card | Menlo 22 (code), HN 26/24 (cards) | Every frame |
| 8 | **Activity feed** | 0, 372, 840, 120 | Last 4 lines of `run/activity.jsonl`: `20:14:07 builder  Edit stream/scenes/ballot.py +18 -2`; actor coloured (builder white, qa cyan, supervisor grey, ship accent, mod amber, fail red); new line slides up over 8 frames with a click | Menlo 22, 28 px line height | On new line (tail every 250 ms) |
| 9 | **Ballot** | 0, 492, 840, 164 | Three cards 264x140 at x 16 / 288 / 560, y 500: letter 56 px top-left; option title 22 px (2 lines max); tally bar 8 px; `4 votes` 22 px; last 3 voter names 20 px. Leading card gets a 2 px accent border. Instruction line at y 644: `TYPE A, B or C IN CHAT. MOST VOTES SHIPS.` 20 px. At zero: `Nobody voted. Agent picked C. Next one is yours.` | AB 56 / HN 22 / Menlo 22 / Menlo 20 | Under 1 s of a vote; bar eases over 10 frames |
| 10 | **Chat, pinned strip** | 840, 72, 440, 40 | Rotates every 20 s: `Type A, B or C to vote` / `!idea <what should change>` / `!theme ember` (plus `!ask <anything>` only when `ask.enabled`). Amber `0 votes, your letter decides this one` when votes = 0 with under 30 s left. Cooldown notices override for 4 s: `theme cooldown 41 s` | HN Medium 22 | 20 s / on event |
| 11 | **Chat, messages** | 840, 112, 440, 272 | Last 10 real Pusher messages, newest at bottom, wrapped at 408 px, 26 px line height. Username in a hashed colour from the palette's 6-colour set, `#N` builder tag on a user's first-ever message, letter chip on votes, NOMINATED tag on ideas, shield chip on mod actions. Newest message has a 1 s highlight fade. Empty: `chat is empty. be the first: type A` | Menlo 22 | Under 1 s of a message (after the 3 s moderation hold) |
| 12 | **Founders strip** | 840, 384, 440, 28 | `founders: sam kai … (7)`: the first 10 real chatters of the session, in order, for the whole stream. Empty: `founders: nobody yet. first message takes #1` | Menlo 20 | On new founder |
| 13 | **Ask / answer card** ("your question here") | 840, 412, 440, 124 | When `ask.enabled`: `@name asked: <q>` + `answering… (queue 2)` or the answer (280 chars max, 24 px wrapped, 4 lines). Idle: `your question here: !ask <anything>, answered on screen`. When `ask.enabled=false` (v1 default): the card shows the last shipped version card instead: `v0.3.12 · palette ember · @sam · 7f3a1c2` | HN 24 / Menlo 20 | On ask state change |
| 14 | **Next up** (agenda) | 840, 536, 440, 120 | `NEXT UP (macro)`: top 3 `!idea` entries with requester and `+N`, or `declined: <reason>` in grey; when no agent is attached: `no agent on duty. backlog open, next session ships it` | HN Medium 22 / Menlo 20 | On idea / classification |
| 15 | **Ticker** | 0, 656, 880, 64 | Right-to-left crawl at 120 px/s, items separated by ` · `: last 10 patch notes (`v0.3.11 @sam: palette ember`), the honesty line (`no camera, no mic, no fake viewers, every number on screen is real`), the command legend, the rule (`this stream rebuilds itself. you pick what changes.`) | HN Medium 24 | Every frame |
| 16 | **Scope** | 880, 656, 160, 64 | Real oscilloscope: 1 px accent polyline of the 1600-sample block handed to ffmpeg this frame (left channel), 144 px wide | none | Every frame |
| 17 | **Footer readout** | 1040, 656, 240, 64 | Two lines: `chat 0.4/min · 2 chatting` (Pusher, 5 min window) / `30.0 fps · 11 ms · up 01:23:45` (compositor's own counters) | Menlo 20 | 1 s |

Legibility gates (QA agent, every round): downscale a captured frame to 320x180 and confirm the
version number and `NEXT SHIP` read; confirm every text item is ≥ 20 px in the 720p frame; confirm
the header is drawn over every stage state including the ship flash.

---

## 4. Scenes and switching

The stage body (region 7) is the only region that changes mode. Everything else keeps moving in
every scene so the frame is never static.

| Scene | Stage body shows | Enter when | Leave when |
|---|---|---|---|
| **BUILDING** (default) | DIFF view: header line `live diff · stream/scenes/ballot.py`, `git diff` of `build.file` polled every 2 s, new hunks typed at 40 chars/s, `+` green `-` red, blinking cursor. If typing lags the real edit by > 10 s the header reads `replaying patch`. | An agent heartbeat is fresh (`agent.heartbeat_ts` < 120 s old) and the diff changed in the last 20 s | Diff unchanged 20 s → STATUS; `ask.current` set → ANSWERING; round ends → SHIP |
| **STATUS** | Last test / build output from `build.status_lines` (pytest, py_compile, frame-time guard readings) with pass/fail counts; if none, the CANVAS sim with the caption `agents are thinking… 0:47` (real elapsed idle time) | Diff unchanged for 20 s, or `build.step` = TEST | Diff changes → BUILDING; `ask.current` → ANSWERING; round ends → SHIP |
| **CANVAS** | Generative sim from `canvas.scene` (Gray-Scott reaction-diffusion 3.1 ms or 20k-particle flow field 3.5 ms, measured; simulated at 420x118 and upscaled 2x), single accent on black, `scene v0.3 · <name> · seed @kai` chip | Chat has voted the canvas in as the stage default (`stage.default = canvas`), or STATUS idle > 60 s | Any BUILDING/ANSWERING/SHIP trigger; returns after |
| **ANSWERING** | Q&A card: `@name asked:` question 26 px, answer typed at 40 chars/s 24 px, 20 s hold after the last character | `ask.current.answer` becomes non-null (only possible when `ask.enabled`) | 20 s after answer complete, or round end (SHIP has priority, answer resumes after) |
| **SHIP** | RESULT card for 5 s: `SHIPPED v0.3.13 · palette ember · picked by @sam · 7f3a1c2` on accent tint, or `BUILD FAILED · reverting to v0.3.12` with the first 3 traceback lines on red tint. A single ≤ 400 ms accent fade over the stage body only (never full frame, never repeated, header untouched) | `round.deadline` reached, or a macro reload completes / fails | 5 s → previous scene |
| **ATTRACT** | CANVAS sim at full stage with the hook sentence `THIS STREAM REBUILDS ITSELF. TYPE A, B OR C.` 34 px HN Bold, plus a `how to drive this stream` card (3 lines) | No chat message for 5 min AND no fresh agent heartbeat, or `agent.on_duty=false` at session start | First chat message or heartbeat → STATUS/BUILDING |
| **CREDITS** | Every real chatter of the session scrolls up the stage (name, builder #, votes cast, ships picked), then `see you next session` | `session.ending=true` written by `scripts/stop.sh --credits` | Compositor exits after the roll (≈ 30 s) |

Rules that hold in every scene: header clock, countdown bar, ticker and scope update every frame;
micro-ship rounds keep running (the compositor owns them, no agent required); the chat pane keeps
rendering unless `chat.display=false` or `!pause`.

Round lifecycle (compositor-owned, 180 s): `open` (0-150 s, votes accepted) → `closing` (150-180 s,
amber strip if 0 votes, rising tick from 170 s) → `ship` (apply winner, or agent-pick labelled
`agent`, append `ships.jsonl`, commit CHANGELOG line, bump version, SHIP scene 5 s) → next `open`.
Ballot options for the next round are drawn when the current round ships: 1 from chat `!idea`
entries classified `instant` if any exist, the rest from the micro menu, never the same parameter
in two consecutive rounds. Macro-ships are agent-owned: the agent writes `macro.*` to `state.json`
when it starts (deadline 15-20 min out) and the compositor reloads `stream/scenes/<module>.py` on
mtime change; the last 60 s before `macro.deadline` get the quarter-note tick.

---

## 5. Palette, fonts, motion

### Colours
| Role | Hex |
|---|---|
| Background | `#0B0E14` |
| Panel fill | `#11151D` |
| Hairline / borders | `#1C2130` |
| Text primary | `#E6E8EE` |
| Text secondary | `#8A90A0` |
| Diff add / test pass | `#3DDC84` |
| Diff remove / fail | `#FF6B6B` |
| Warning (under 30 s, cooldowns) | `#FFB020` |
| Danger (under 10 s, FAILED) | `#FF4D4D` |
| Accent default | `#53FC18` (Kick green) |

`!theme` and the micro menu pick from **8 fixed accent presets**, each verified ≥ 4.5:1 contrast
on `#0B0E14` by `stream/palette_check.py` at startup; no user hex is ever accepted:

| Preset | Accent | Username colour set (6) |
|---|---|---|
| kick | `#53FC18` | `#53FC18 #7DD3FC #FCD34D #F9A8D4 #C4B5FD #FDBA74` |
| ember | `#FF6A2B` | `#FF6A2B #FFB020 #FDE68A #FCA5A5 #F9A8D4 #FDBA74` |
| ice | `#5AD1FF` | `#5AD1FF #93C5FD #A5F3FC #C4B5FD #E0F2FE #BAE6FD` |
| violet | `#A78BFA` | `#A78BFA #C4B5FD #F9A8D4 #7DD3FC #FCD34D #DDD6FE` |
| gold | `#FFC53D` | `#FFC53D #FDE68A #FDBA74 #FCD34D #FFE8A3 #FBBF24` |
| magenta | `#FF5CA8` | `#FF5CA8 #F9A8D4 #FBCFE8 #C4B5FD #FCA5A5 #FDA4AF` |
| cyan | `#22D3EE` | `#22D3EE #67E8F9 #A5F3FC #7DD3FC #5EEAD4 #99F6E4` |
| paper | `#E8E2D0` | `#E8E2D0 #D6D3C4 #FDE68A #BAE6FD #FBCFE8 #C7D2FE` |

Ship flash: stage body only, accent at 35 % alpha fading to 0 over ≤ 400 ms, once per ship.

### Fonts (all from `/System/Library/Fonts`)
| Use | Font | Sizes |
|---|---|---|
| Version number, ballot letters | Arial Black (`ArialHB.ttc`, index for Arial Black) | 56 |
| Titles, task row, instruction, ticker, hook sentence | Helvetica Neue Bold / Medium (`HelveticaNeue.ttc`) | 34, 28, 26, 24, 22 |
| Everything data-like: chat, activity, diff, counters, chips | Menlo Regular / Bold (`Menlo.ttc`) | 24, 22, 20 |
| Fallback if a face fails to load | Monaco (`Monaco.ttf`), Avenir Next (`Avenir Next.ttc`) | same |

Text rendering: every panel renders to a cached RGBA image only when its content changes; the
per-frame loop pastes cached panels and draws only the moving elements (clock digits, bar, ticker
offset, scope, stage body, chat slide). Strip non-BMP codepoints (emoji) before rendering; Kick
emotes `[emote:123:name]` render as `:name:`.

### Motion rules
- Something moves every frame: countdown bar, ticker, scope, step-bar pulse, stage cursor or sim.
  A watchdog checks that at least one of these changed pixels in the last 30 frames.
- Nothing flashes faster than 1 Hz. The ship fade happens once per ship (≥ 10 s apart by
  construction) and never covers the header. No inversions, no full-frame colour fills.
- Easing: tally bars and slides use 8-10 frame ease-out; no element jumps except the typewriter.
- Frame budget 33.3 ms at 30 fps; frame-time guard rolls back any scene that exceeds 20 ms for 30
  consecutive frames; if the whole frame exceeds budget for 5 s the compositor switches to 24 fps
  (`-r 24` restart) and logs it to the activity feed.

---

## 6. Generated audio

All synthesised in numpy inside the compositor loop: 48 kHz stereo s16le, **exactly 1600 samples
per video frame**, written to the audio FIFO in lockstep with each frame (one frame, one block, so
A/V cannot drift by construction; proven in `/tmp/kl-avtest`). Nothing sampled, nothing copyrighted.

| Layer | Design | Level |
|---|---|---|
| Pad | 3 detuned sine/triangle voices per chord tone, 4-chord minor loop (i · VI · III · VII in A minor: Am F C G), chord change every 8 bars, one-pole low-pass at 1.2 kHz with a 0.1 Hz LFO on cutoff, 8 ms Haas offset for width, 6 s attack on chord changes | -24 dBFS |
| Pulse | Tempo 85 BPM default (`audio.tempo` ∈ {72, 85, 100}); sine kick 60→40 Hz sweep with exponential decay on beats 1 and 3, filtered-noise hat on off-beat 8ths; sidechain-style 3 dB dip of the pad on the kick | -30 dBFS |
| Texture | Sparse impulse noise through a 2 kHz low-pass ("vinyl crackle") | -40 dBFS |
| Chat pluck | Karplus-Strong string per rendered chat message, pitch = pentatonic degree from `hash(username) % 10` over two octaves (so regulars have an audible identity), 300 ms, through a 375 ms comb delay (0.35 feedback); rate-limited to 1 per 250 ms and auto-muted above 10 msg/min | -20 dBFS |
| Vote blip | 30 ms sine, starts at A4 and rises one semitone per vote in the round, resets each round | -20 dBFS |
| Round tick | Filtered click each second for the last 10 s of a micro round; quarter-note tick rising a semitone every 10 s for the last 60 s of a macro deadline | -22 dBFS |
| Ship chime | Major arpeggio A-C#-E over 400 ms | -16 dBFS |
| Fail buzz | Descending minor third on a detuned saw, 300 ms, plus a 80 Hz thud | -16 dBFS |
| New builder | Two ascending notes (G5-C6, 200 ms) on a user's first-ever message | -20 dBFS |
| Theme sweep | 600 ms low-pass sweep on the pad when `!theme` lands | n/a |

Master: fixed gain to **-18 dBFS integrated** (RMS over the bed measured by the QA agent decoding
HLS audio; target window -20 to -16), `tanh` soft limiter with a -6 dBFS peak ceiling, so it sits
under a viewer's other tabs and Kick's player never clips. Tempo changes land at the next bar
boundary. Measured cost of the oscillator core: 0.05 ms per block; the full chain stays under 1 ms.

Fallbacks, in order: (1) `stream/run.sh AUDIO_SOURCE=generated` already produces an ffmpeg
`aevalsrc` bed (`aevalsrc='0.04*sin(2*PI*110*t)*(0.6+0.4*sin(2*PI*0.1*t))+0.02*sin(2*PI*165*t)':s=48000:c=stereo`,
about -25 dBFS mean) and is wired from minute one so the stream never goes out silent if the FIFO
misbehaves; (2) a pre-rendered 10-minute numpy WAV looped with `-stream_loop -1`. Both lose chat
reactivity; the scope then shows the bed and the footer says `audio: fallback bed`.

---

## 7. Chat commands

Parsing runs on `run/chat.jsonl` records after the moderation pipeline (§7.1). Case-insensitive.

| Command | Effect on screen | Rate limit | Who |
|---|---|---|---|
| `A` / `B` / `C` / `!a` / `!b` / `!c` (the **trimmed message must be exactly** `^!?[abc]$`; anything else, including emote-only messages and words that start with a letter, is not a vote) | Within 1 s: tally bar grows, count increments, voter's name appears under the card, letter chip on the chat line, vote blip. One vote per user per round; a new letter moves it. | 1 vote per user per round | Everyone (hidden users ignored) |
| `!idea <text>` (≤ 60 chars displayed) | Line gets a NOMINATED tag; entry appears in NEXT UP with the requester's name and `+N` when others repeat it; agent classifies it `instant` (goes on a ballot within 3 min), `macro` (queued for real code), or `declined: <reason>` (shown, never silently dropped) | 1 per user per 3 min, 3 open per user | Everyone |
| `!theme <kick|ember|ice|violet|gold|magenta|cyan|paper>` | Whole stream repaints on the next frame with a 400 ms fade, header toast `@name set theme: ember` 10 s, theme sweep sound. Unknown preset → strip shows the list for 4 s. During cooldown → strip shows `theme cooldown 41 s` | 60 s global | Everyone |
| `!stats` | Stage shows a 10 s stats card: viewers now / peak, msgs per min, unique chatters (5 min), uptime, ships / fails, versions today, fps, frame ms, dropped frames. All from `metrics.jsonl`, `chat_stats.json` and compositor counters; unavailable → `--` | 30 s global | Everyone |
| `!help` | Pinned strip cycles the full legend for 20 s; also auto-shown after 5 min of chat silence | 30 s global | Everyone |
| `!ask <question>` (≤ 140 chars) | **Hidden from the ticker and pinned strip until `ask.enabled=true`** (responder running and measured latency < 60 s). Then: card shows `@name asked: …` + `answering… (queue 2)`, answer typed on screen, 20 s hold. Queue depth 3; overflow → `queue full, try in a minute` | 1 per user per 5 min | Everyone |
| `!revert` | **Not in v1, not advertised.** v2: 2 distinct chatters within 60 s of a ship roll it back, progress shown `1/2 to revert (@sam)`; version becomes `v0.3.13-r` | once per ship | Everyone |
| `!hide <user>` / `!unhide <user>` | Stops rendering that user's messages, votes and ideas for the session; chat line shows a shield chip `mod action` | none | broadcaster / moderator badge (`badges` in the chat record) |
| `!pause` / `!resume` | Freezes / resumes the chat pane (votes still count) during a flood; strip shows `chat paused by mod` | none | broadcaster / moderator |
| `!clear` | Wipes the NEXT UP queue and open ideas; ticker notes `backlog cleared by mod` | none | broadcaster / moderator |
| `!kill` / `!unkill` | Sets `chat.display=false/true`: the chat pane, founders strip, voter names and ticker names are replaced with `chat hidden by mod` instantly | none | broadcaster only |

### 7.1 Moderation pipeline (mandatory before the first live frame)
Every chat record passes, in order, before any pixel is drawn or any name is shown:
1. **3 s hold** (render at `ts + 3 s`) so the filter and a human `!hide` can beat the render.
2. **Hidden / paused check** against `mod.hidden_users` and `mod.paused`.
3. **URL strip**: any token with a scheme or a `.tld` pattern is replaced by `[link]`.
4. **Non-BMP strip** and emote normalisation.
5. **Word filter**: `stream/moderation/blocklist.txt` (slurs, hate terms, sexual terms), matched on a
   leet-normalised lowercase form; a hit drops the message and its vote/idea and increments a
   `moderation.dropped` counter shown in `!stats`.
6. **Username filter**: the same list applied to the username; a hit renders the user as
   `builder #N` everywhere (name never drawn).
7. **Length cap** 120 chars displayed (60 for `!idea`, 140 for `!ask`).
8. **Per-user render rate** 1 message per 2 s; excess lines are dropped from the pane (votes still count).
9. **Kill switch** `chat.display` honoured on every frame.
Votes are counted instantly (a bare letter cannot be offensive) but the voter's name still goes
through steps 2, 6 and 9 before it is drawn.

---

## 8. Data contracts

### 8.1 `run/state.json` (read by the compositor every 250 ms, hot-applied; written atomically)

```json
{
  "schema": 1,
  "updated_ts": "2026-09-24T10:31:02.512Z",
  "session": {
    "id": "2026-09-24T09:58Z",
    "started_ts": "2026-09-24T09:58:10Z",
    "ending": false
  },
  "version": {
    "string": "v0.3.12",
    "major": 0,
    "macro": 3,
    "micro": 12,
    "commit": "7f3a1c2",
    "shipped": 15,
    "failed": 2
  },
  "theme": {
    "preset": "kick",
    "set_by": "sam",
    "set_ts": "2026-09-24T10:29:40Z",
    "cooldown_until": "2026-09-24T10:30:40Z"
  },
  "round": {
    "number": 16,
    "phase": "open",
    "opened_ts": "2026-09-24T10:30:00Z",
    "deadline_ts": "2026-09-24T10:33:00Z",
    "options": [
      {"letter": "A", "id": "palette.ember", "title": "palette: ember", "source": "menu", "votes": 2, "voters": ["sam", "kai"]},
      {"letter": "B", "id": "canvas.scene.flowfield", "title": "stage canvas: flow field", "source": "idea", "requested_by": "kai", "votes": 1, "voters": ["lu"]},
      {"letter": "C", "id": "audio.tempo.100", "title": "tempo: 100 bpm", "source": "menu", "votes": 0, "voters": []}
    ],
    "last_result": {"letter": "B", "title": "ticker: 160 px/s", "picked_by": null, "agent_pick": true, "version": "v0.3.12", "ts": "2026-09-24T10:30:00Z"}
  },
  "micro": {
    "palette": "kick",
    "canvas_scene": "reaction_diffusion",
    "canvas_rule": "coral",
    "canvas_seed": 41370704,
    "audio_tempo": 85,
    "audio_pattern": "pad_pulse",
    "ticker_speed": 120,
    "header_tagline": "SHIP IT LIVE",
    "typewriter_cps": 40,
    "scope_style": "line",
    "stage_default": "diff",
    "chime_variant": "arpeggio"
  },
  "macro": {
    "active": true,
    "title": "chat-picked username colours",
    "requested_by": "kai",
    "module": "stream/scenes/chat_pane.py",
    "started_ts": "2026-09-24T10:22:00Z",
    "deadline_ts": "2026-09-24T10:40:00Z",
    "step": "EDIT",
    "step_index": 2,
    "step_label": "2/5 editing chat_pane.py",
    "file": "stream/scenes/chat_pane.py",
    "status_lines": ["py_compile ok", "render test: 11.2 ms avg over 300 frames"],
    "last_reload": {"ts": "2026-09-24T10:12:31Z", "ok": true, "module": "stream/scenes/ballot.py", "error": null, "frame_ms_p95": 12.4}
  },
  "agent": {
    "on_duty": true,
    "heartbeat_ts": "2026-09-24T10:30:58Z",
    "name": "builder"
  },
  "ideas": [
    {"id": "i-0041", "text": "show the diff bigger", "by": "lu", "ts": "2026-09-24T10:28:10Z", "plus": 1, "class": "macro", "status": "queued", "reason": null},
    {"id": "i-0042", "text": "play despacito", "by": "zed", "ts": "2026-09-24T10:28:55Z", "plus": 0, "class": "declined", "status": "declined", "reason": "copyrighted audio"}
  ],
  "ask": {
    "enabled": false,
    "current": null,
    "queue": [],
    "last": {"by": "sam", "question": "what language is this", "answer": "Python 3.9 with Pillow and numpy, piped to ffmpeg.", "asked_ts": "2026-09-24T10:20:01Z", "answered_ts": "2026-09-24T10:20:38Z"}
  },
  "chat": {
    "display": true,
    "connected": true,
    "founders": ["sam", "kai", "lu"],
    "msgs_per_min_5m": 0.4,
    "unique_chatters_5m": 2
  },
  "mod": {
    "paused": false,
    "hidden_users": [],
    "actions": [{"ts": "2026-09-24T10:05:00Z", "by": "atleastonce", "action": "hide", "target": "spammer1"}]
  },
  "metrics": {
    "is_live": true,
    "viewer_count": 3,
    "viewer_peak": 5,
    "polled_ts": "2026-09-24T10:30:50Z",
    "poll_ok": true
  },
  "audio": {
    "source": "fifo",
    "tempo": 85,
    "pattern": "pad_pulse",
    "muted_plucks": false
  },
  "compositor": {
    "fps_target": 30,
    "fps_actual": 30.0,
    "frame_ms_avg": 11.2,
    "frame_ms_p95": 14.9,
    "dropped_frames": 0,
    "scene": "BUILDING",
    "uptime_s": 1972
  }
}
```

Field rules: any field the compositor cannot read falls back to a safe default and the footer shows
`state: stale` if `updated_ts` is older than 10 s. Numbers that come from the outside world
(`metrics.*`, `chat.*`) are copied from `run/metrics.jsonl` and `run/chat_stats.json` by the
compositor itself, never typed by hand. `version.*` is derived from `run/ships.jsonl` (one line per
ship: `{ts, version, kind: micro|macro, option_id, title, picked_by, agent_pick, ok, commit, error}`);
every ship also appends one line to `docs/CHANGELOG.md` and commits it
(`ship v0.3.12: palette ember (voted by @sam)`) so each version maps to a real commit whose short
hash is shown on the card. `builders.json` (`{"sam": {"n": 1, "first_seen": "...", "sessions": 3, "votes": 41, "ships": 6}}`)
persists across sessions and is the source of `#N` tags and the credits roll.

### 8.2 `run/activity.jsonl` (append-only, one JSON object per line)

```
{"ts":"2026-09-24T10:14:07.120Z","actor":"builder","text":"Edit stream/scenes/ballot.py +18 -2"}
{"ts":"2026-09-24T10:14:12.004Z","actor":"builder","text":"Bash pytest -q stream/tests  14 passed"}
{"ts":"2026-09-24T10:14:30.551Z","actor":"compositor","text":"reload stream/scenes/ballot.py ok, 12.4 ms p95"}
{"ts":"2026-09-24T10:15:00.000Z","actor":"ship","text":"v0.3.12 palette ember, voted by @sam, 7f3a1c2"}
{"ts":"2026-09-24T10:15:03.200Z","actor":"qa","text":"hls probe: 30 fps, no black, audio -18.4 dBFS"}
{"ts":"2026-09-24T10:16:41.000Z","actor":"mod","text":"hide spammer1 (broadcaster)"}
```

Exactly three fields: `ts` (UTC ISO-8601, ms optional), `actor` (one of `builder`, `critic`, `qa`,
`supervisor`, `chat`, `compositor`, `ship`, `mod`, `agent`), `text` (one line, ≤ 200 chars, already
filtered: it is drawn verbatim). Writers: `scripts/env.sh kl_activity`, the chat listener, the
supervisor, the compositor, and a Claude Code `PostToolUse` hook (`.claude/hooks/activity.sh`) that
appends one line per Edit/Write/Bash/commit from the building session and touches
`agent.heartbeat_ts`. Without the hook the "agents are building this live" claim is hollow, so the
hook is part of the go-live checklist, not a nice-to-have.

---

## 9. Feasibility, risks, cut list

### What is already proven on this Mac (Apple M3 Pro, static ffmpeg 9.0.2, Python 3.9 venv)
- Two FIFOs (rawvideo rgb24 + s16le 1600 samples/frame) into one ffmpeg with `h264_videotoolbox
  3000k -g 60` + `aac 128k`: 150 frames, 0 over budget, speed 0.999x, 5.00 s A and 5.00 s V. FIFO
  must be opened before ffmpeg probes (deadlock otherwise, already hit and fixed); one queue-backed
  writer thread per pipe; add `-color_range tv` for the live run.
- Per-frame costs: Gray-Scott 3.1 ms, flow field 3.5 ms, worst-case uncached 18-line Pillow text
  14.4 ms, audio block 0.05 ms. Worst total 17.6 ms against 33.3 ms.
- Chat listener to `chatrooms.41370704.v2` connects, subscribes and writes `chat.jsonl` with
  `username`, `content`, `badges`. API poller writes `metrics.jsonl`. `run.sh` refuses live mode
  without a key and already has the `aevalsrc` bed.

### Build order (one session, honest hours)
| Step | Work | Hours |
|---|---|---|
| 1 | Lift `/tmp/kl-avtest/gen.py` into `stream/compositor.py`: frame loop, audio thread, FIFOs, `run.sh SOURCE=compositor AUDIO_SOURCE=pipe:`, supervisor restart | 1.0 |
| 2 | Panel system with per-panel cache: header, countdown bar, stage title/step, activity feed, ballot, chat pane, founders, ask card, next-up, ticker, scope, readout | 2.0 |
| 3 | Chat bridge: tail `chat.jsonl`, moderation pipeline, vote/idea/theme/stats/help parser, mod commands, builders.json | 1.5 |
| 4 | Round engine: 180 s rounds, micro menu (12 params), `ships.jsonl`, CHANGELOG commit, version derivation, SHIP scene | 1.0 |
| 5 | Hot reload: `state.json` watcher, `importlib.reload` of `stream/scenes/*` on mtime with syntax check, frame-time guard (20 ms x 30 frames → rollback), watchdog (no frame 2 s → restart) | 1.0 |
| **Go-live cut** (steps 1-5, `aevalsrc` bed audio, no canvas, no !ask) | | **6.5** |
| 6 | numpy audio: pad, pulse, blips, plucks, chime, fail, ticks, master | 1.5 |
| 7 | Canvas panel (reuse measured sims) as a micro option and ATTRACT background | 0.5 |
| 8 | `!ask` responder: separate process calling `~/.local/bin/claude -p` with a 280-char system prompt, writes `ask.current.answer`; enable only after 5 measured answers under 60 s | 1.0 |
| 9 | Credits roll, `!stats` card, 320x180 legibility check in `validate/hls_probe.py` | 0.5 |
| Full concept | | **10** |

Steps 6-9 are themselves the first macro-ships and belong on air; the go-live cut is a complete show.

### Risks (and what the spec does about them)
| Risk | Mitigation in this spec |
|---|---|
| Nobody arrives (2 followers, no token, no self-promotion) | Empty states are honest and specific; micro rounds run with agent picks labelled `agent`; promo pack and featured-slot pack are the owner's (journal 002). The 100-viewer target will not be met by content alone and the report will say so. |
| A slur or URL on a public VOD with no human present (the real ban vector) | §7.1 pipeline before the first live frame; 3 s hold; badge-gated `!hide/!pause/!kill`; username filter; everything logged. |
| Kick's tolerance of a fully automated no-human stream is unverified | Owner checks terms before a multi-hour run; on-screen text says plainly that it is an AI-built stream; the owner's account stays reachable for mod commands. |
| Hot-reloaded agent code hangs the loop (try/except cannot catch it) | Frame-time guard plus 2 s watchdog restart, accepted 3-5 s on-air stall; v2 splits the compositor into a pipe-owning parent that repeats the last good frame while a render child restarts. |
| A/V drift or a blocked FIFO stalls video | Lockstep 1600 samples/frame, bounded queues, wallclock pacing (duplicate a frame rather than fall behind), alert when ffmpeg `speed` < 0.98x, `aevalsrc` fallback wired from minute one. |
| Frame rate collapse from Pillow text | Per-panel cache, measured worst case 17.6 ms, automatic 24 fps fallback. |
| Micro-tweaks feel trivial after an hour | Menu mixes visual (palette, canvas), audio (tempo, pattern) and content (tagline, stage default) changes; every third round must include a chat `!idea`; macro-ships carry the real novelty. |
| Macro-ships fail or overrun | Failure is a designed state with a scoreline; macro scope is one panel or one behaviour; `still building` past zero is shown honestly, never a fake ship. |
| Kick's random auto-thumbnail catches a bad frame | Header is drawn last in every scene; ship fade ≤ 400 ms on the stage only; no black frames (last good frame repeats during any restart). |
| `kick.com/api/v2` gets Cloudflare-challenged | Viewer count shows `--`, liveness falls back to the HLS manifest, never a stale or invented number. |
| Bare-letter votes miscount | Exact-match rule `^!?[abc]$` on the trimmed message; logged for audit. |
| Copyright | No samples, no music, generated audio only; `!idea` requests for songs are `declined: copyrighted audio`. |

### Cut list (first to go if time runs out)
1. `!ask` responder (already hidden until it works).
2. Canvas panel (stage falls back to STATUS text).
3. Karplus-Strong plucks (keep the vote blip and click).
4. Credits roll and `!stats` card.
5. Oscilloscope → 8-bar level meter from the same buffer.
6. Typewriter diff → plain tail of the activity feed in the stage.
7. numpy audio → `aevalsrc` bed (already in `run.sh`).
8. Scene-module hot reload → macro-ships restart the compositor behind a 3 s `deploying…` card (last frame held).
9. 30 fps → 24 fps.

Never cut: the moderation pipeline, real-numbers-only, the header with countdown, the ballot with
bare-letter voting, the chat pane, the `aevalsrc` audio fallback.

---

## 10. What the owner must do manually

1. **Fill `STREAM_KEY`** at `~/.config/kick-live/env` (mode 600), not in chat. `scripts/start.sh`
   goes live the moment it is present; until then everything validates against local HLS. Rotate the
   key after this project (it was pasted into an earlier chat).
2. **Set title and category in the Kick dashboard** (no token on the box): title
   `AI rebuilds this stream every 3 min. Chat votes A, B or C`, category **Software & Game
   Development**, description from §1. Confirm the stream is not still tagged Just Chatting.
3. **Keep the `atleastonce` account open in chat** during the first sessions for `!hide`, `!pause`
   and `!kill`; the compositor recognises the broadcaster badge.
4. **Check Kick's terms** for a fully automated, no-human-present broadcast before a multi-hour run.
5. Optional: provide `KICK_TOKEN` only if the stream's own account may post replies, clearly labelled
   as the stream's bot (Phase 4, off by default); post the promo copy and featured-slot pack from
   `docs/promo/` yourself (journal 002).
