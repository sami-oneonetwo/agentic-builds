# ADR-004: Living-world pivot — PIP HOLLOW replaces the text show

Status: accepted (2026-09-25, synthesizer step of the `kick-live-world-concept` workflow; owner-invited, owner may overturn)

## Context

SHIP IT LIVE (ADR-003, `docs/CONCEPT.md`) went on air on 2026-09-24 and ran two sessions (journal
008-014): ~28 min on day one, peak 3 concurrent viewers, 8 ships, 24 chat lines all from the owner;
day two resumed from the isolated run dir with the 79-term blocklist installed live. The pipeline
worked (30 fps, 0 drops, HLS probe PASS, agent macro-ship built live from a chat `!idea`). The
content did not.

The owner's verdict after watching both sessions (journal 015): *"This is a very boring stream.
Concept is fine, but no one would want to interact with static text. Think about what people want
deep down. Make this livestream something they want deep down. Something they interact with."* They
pointed at Black Mirror's "Plaything" (the Thronglets: a colony of small digital creatures the
player raises) as an idea, not an order. Their two chat `!idea`s during the sessions were
`build a pixel art bot that responds` and `build a little pixel dude on screen`. In the 015 addendum
the owner approved restarting the stream to switch builds and asked for a new stream per major
stage so the VODs show the progression.

Diagnosis shared by the workflow: the object of care in SHIP IT LIVE was the stream's own settings;
nobody feels anything about ticker speed. The response to a person was a line of text about code:
no body, no memory, nothing depending on them. A lone viewer saw a dead screen until they acted,
which is the moment people leave.

What stays fixed: the headless pillow/numpy compositor at 1280x720 30 fps piped to ffmpeg through
`stream/relay.py`; real Kick chat within 1-3 s; the 180 s A/B/C `RoundEngine`; per-viewer
persistence (`builders.json`); agents hot-reloading scene code live; generated audio only; the
absolute rule that every entity on screen corresponds to a real person who chatted and that empty
states are honest (ADR-000); no camera, no mic, no copyrighted characters or assets.

The workflow ran five persona concepts, all grounded in what has worked for chat-driven interaction
(Twitch Plays Pokémon, r/place, Marbles on Stream, Stream Avatars, Tamagotchi/Neopets, cookie
clickers, community-pet streams, Conway-life streams, Plaything's Thronglets as an idea), and three
judges scored each on six criteria (want, first message, alone, together, return, feasibility;
10 each, 60 per judge, 180 total).

## Decision

Build **PIP HOLLOW** as specified in `docs/WORLD.md`: a dark pixel cave that only lights up with
real people. Any message drops a nameless seed within one frame; when the 3 s moderation hold clears
and the username passes the blocklist, a small glowing creature (a pip) hatches carrying the
chatter's name and colour, speaks their words as an in-world bubble, walks to a stone platform when
they vote a bare letter, brightens when fed or petted, sleeps in a burrow when they leave, and is
still there tomorrow. The 3-minute round becomes world events; colony milestones (3/5/10/25/50 real
people ever hatched) trigger keeper macro-ships that carve new chambers live; the AI agents are the
keepers, shown as a lantern on a chain and one plain-language line, never as a creature. Darkness
means nobody; light means someone.

The world lands as macro-ship v0.5.0 in the existing version scheme. New stream title:
`Say anything in chat. A creature hatches with your name` (55 chars). Category stays Software &
Game Development for the first world session, then an A/B against a games/creative category read
from Kick's category API, judged on real `viewer_count` only.

### Grafts adopted from the other four concepts (all three judges' lists, merged)
- **From HEARTH:** *first light* (the session's first message visibly wakes the Hollow: moss
  flares, the first pad voice rises, the plank writes `@name woke the Hollow · 21:14`); the dark
  state shows the last five real visitors with real timestamps, so an empty cave reads as waiting,
  not offline; *homecoming* (every awake pip turns to face a 7+ day returner); a nightly board at
  session start; growth credit for **minutes present**, so a quiet regular still tiers up; the
  written rule *absence is never punished* so no future keeper adds hunger or death.
- **From LOAM (glims):** the egg-crack-before-hold-clears timing as the explicit T+0 spec, with
  the stricter reading adopted: the seed is nameless until the hold **and** the username blocklist
  clear; the per-pip `care_log` shown once on wake (`fed by @sami, petted by @atleastonce`);
  `forget` to purge stored words; reject-and-reseed for procedural sprites that fail a fill,
  symmetry or contrast check; a first visible size change within the first night (5 messages or 10
  minutes).
- **From TIDEPOOL:** `gift @name` at a sleeping pip, played back on the owner's next wake; the
  every-frame self-test assertion `len(awake pips) == len(distinct chatters this session)`;
  *storms* when real chat rate exceeds 20 msg/min (an honest visualisation of load that doubles as
  the bubble-density fallback); 2-frame emote verbs (`wave`, `sit`, `duck`) at 1 per 5 s; the
  directory tile as the world (sim 320x110 at 4x, so the 320x180 thumbnail shows the cave 1:1) with
  a QA gate that at least one light source is visible at 0 awake.
- **From LOAM (pips / Keepers):** nests: two owners with 3+ mutual feed/pet build a nest, the next
  newcomer's seed lands in it, the godparents get a permanent badge and the newcomer gets one
  optional lore line (not an immutable tag); the richer world-event menu (glow-rain, fog,
  lights-out, feast, migration with camera pan in v2); recompute awake/hatched/sessions from
  `chat.jsonl` by distinct `(session, owner)` so bug 014.2 cannot recur; the no-impersonation rule
  (no nickname or taught word may equal another chatter's username); a dictionary allowlist plus
  blocklist for any word a pip repeats unprompted.
- **From HEARTH's restraint:** PIP HOLLOW's 4-line live diff strip is removed from normal play.
  Keeper work is the lantern swing plus one plain line (`carving: East Chamber · asked by @sam`);
  the diff/traceback appears only on failure. Text about the codebase is what the owner called boring.
- **Cross-cutting from all judges:** verbs match only when the message is exactly the verb token
  (or `!`-prefixed), never as a substring; a username that fails the blocklist hatches as
  `builder #N`; three blocklist hits on a user's text burrow their pip for the session with the
  reason on screen; `!banish` for the owner/mods through the existing `!mod` path; a compact 5-line
  chat log stays on screen for moderation visibility.

### Fatal flaws removed from the winning concept as proposed
- The username was drawn at T+0, before the 3 s hold, widening bug 014.1 onto a 48 px body. Now
  the seed is nameless for the hold and the label is drawn only after the hold and blocklist clear;
  the raw-name `tallies()` path is deleted, not bypassed.
- The 0-awake thumbnail was near-black and, with two humans ever, that is the default state. Now
  the cave has a mouth showing the real-clock sky and real moon phase, moss glows, the 56 px header
  count reads, and the QA gate checks a light source survives the downscale.
- The 4-line live diff strip was text about itself; replaced as above.
- The 5/10/25/50/100 milestone ladder was unreachable at this channel size and would read as a
  stalled bar; corrected to 3/5/10/25/50, and every on-screen number comes from `len()`, never from
  sample copy (no `41/50 pips`).
- No mod-only removal verb before names became creatures; `!hide` now burrows the pip and
  `!banish` removes it with an audit record.
- Bare-word verbs collided with ordinary chat at volume; exact-token rule.
- Awake-but-ignored energy decay could read as punishment; it is cosmetic only (dim, curl, sleep),
  frozen while asleep and while the stream is off.
- The compositor's frame-time guard would have placeholdered the whole world; the world panel now
  has a graceful-degrade ladder (glow → labels → bubbles) and returns its last good frame on error,
  as a prerequisite rather than a nice-to-have.
- "Bioluminescent blob with eyes" needed an art note keeping it clear of Thronglets; `docs/art-rules.md`
  (angular side-view sprites in the name colour, no yellow default, no round faces, no
  multiplication or morality) and a sprite-sheet review before going live.

## Alternatives considered

Scores are per judge out of 60 (want, first message, alone, together, return, feasibility, 10 each).

| Concept | Judge 1 | Judge 2 | Judge 3 | Total /180 | Why not |
|---|---|---|---|---|---|
| **PIP HOLLOW** (cave, pips, lantern keepers) | 49 | 52 | 48 | **149** | Chosen: first on every judge's sheet. The only concept where something with the viewer's name exists within one frame of their message, where the lone-viewer state is a feeling (`the only light in the cave`) rather than an apology, where the chat pane is gone so the screen is never text about itself, and where emergence is real (colony bar of real humans, attributed learned words, audible colony size, anarchy hour). Most shippable: v1 trialable as a hot-reloaded scene inside `stage_body` with no restart, the deploy path journal 015 already chose. |
| LOAM (glims / mounds / sprigs / keepers) | 39 | 45 | 47 | 131 | Best latency masking (egg cracks before the hold) and best dead-night design (named mounds as a village at night), both grafted. But it kept a 360 px chat pane, a ticker command legend and `!`-prefixed verbs, printed raw `Edit stream/scenes/x.py +18 -2` lines in-world, and its quote memory (your creature repeats your dated old messages to strangers while you are away) was the creepiest and most moderation-heavy mechanic in the set and contradicted its own inert-sleeper rule. 30-36 h. |
| TIDEPOOL (rockpool, pips) | 36 | 46 | 46 | 128 | Cleanest engineering (native 320x180 sim, honesty unit test, palette from presets) and the best return hook (`!gift` at a sleeping burrow), both grafted. But nothing appeared on screen for ~4 s after a stranger's first message (everything waited for the hold), it had ten `!`-commands plus a `!me` stats card, `0 watching besides you` pushed people out, message-count growth was grindable in one night, `!plant <word>` put arbitrary persistent text on the floor with no chat log for mods, and 5x7 pixel-font bubbles at 20 px would smear at Kick's 3 Mbps. |
| LOAM (pips / the Keepers) | 41 | 44 | 42 | 127 | Best return design (session-gated stages, nests, `raised by`, streak hat) and honest `teach` emergence, both grafted. Fatal as written: the Keeper was a hooded humanoid sprite walking to a signpost on zero votes, an animate non-chatter that breaks the one absolute rule on its face; it proposed cutting the 3 s moderation hold to 1 s one day after bug 014.1 surfaced; `left`/`right` as bare verbs herd pips on every "right?"; no awake cap or label fallback; its 22 h "v1" was the heaviest first ship and its no-restart deploy claim was false for the live snapshot. |
| HEARTH (campfire, kin) | 42 | 43 | 40 | 125 | The fire is the strongest emotional primitive in the set and its psychology (contingent responsiveness, endowed progress, absence never punished) is the best argued; first light, homecoming, while-away hugs, minutes-present growth and the nightly board are all grafted. But it kept the chat pane, ballot cards, ticker and a diff workbench (the current text show with a fire in the middle); its fuel decayed 1 s/s with +10 s per message, so a lone viewer fed logs every 45 s or watched coals, the Tamagotchi nag it forbade itself; 12 ring slots could not seat a crowd; 40 agent-hours, the most expensive, with the embodied vote deferred to v2. |

Also rejected: any breeding or child creature (an entity with no real person behind it), any
keeper avatar or ambient animal, cutting the moderation hold, and, as always, synthetic viewers or
chat to seed the empty state (ADR-000).

## Consequences

- **`docs/CONCEPT.md` becomes the pipeline and text-show record, not the content spec.** Its §1-§4
  (identity, pitch, layout, scenes) are superseded by `WORLD.md` §1, §2, §5 and §8-§9 and should
  get a banner at the top pointing to `WORLD.md`. Its §5 (palette, fonts, motion rules), §6 (audio
  layers; extended, not replaced), §7 and §7.1 (chat commands and the mandatory moderation pipeline;
  `WORLD.md` §4 and §11 add to them), §8 (state.json, activity.jsonl, ships.jsonl, builders.json
  contracts) and §10 (owner's manual steps) remain normative. `stream/COMPOSITOR_API.md` is
  unchanged except for the region table, which gains `world`, `colony`, `keeper` and `chat_log` and
  loses the ten text-show regions. The CHANGELOG and version scheme continue: the world is v0.5.0.
- **Journal 015's deploy plan is the sequencing.** Stop the snapshot show; start the hardened build
  (relay + hot-reload + Harden fixes) as a fresh stream (VOD 2), the one owed visible restart.
  Optionally trial the cave inside `stage_body` by hot-reload. Land the full-width layout via a
  relay-held compositor child restart (ffmpeg keeps its pid and ingest) or, if the owner prefers per
  the addendum, a fresh stream (VOD 3). Every later verb, event, chamber and graft ships as a keeper
  macro-ship on air, which is the content the fiction promises. The never-restart rule (journal 011)
  holds: ingest never drops.
- **Go-live prerequisites are moderation and persistence fixes, not features.** Bug 014.1
  (raw names bypass hold and blocklist) must be closed by deleting the raw path; bug 014.2 (double
  counts on re-ingest) by recomputing from `chat.jsonl`; finding 012.1 (state contamination) is
  covered by the isolated run dir and the run-dir guard. Creatures with names are a far larger
  moderation and persistence surface than vote cards, and the owner's account must stay reachable
  for `!hide`, `!banish` and `!kill`.
- **The honesty rule gets teeth.** Two self-test assertions run every frame: awake pips equal
  distinct chatters in the last 20 min; total pips equal distinct chatters ever (minus banished).
  A near-black tile is treated as a QA failure. Every on-screen number is a `len()`.
- **A written non-goal is added: absence is never punished** (no offline decay, no hunger, no
  death, no blaming copy). A keeper ship that violates it is reverted. This is the guard against the
  Tamagotchi guilt loop that two of the five concepts drifted into.
- **The channel's identity changes.** Title, thumbnail, description and possibly category move; the
  featured-slot promo pack in `docs/promo/` goes stale and is redone after the first world session
  with real frames. The keepers-build-live differentiator survives as the lantern and the carved
  chambers, and the ticker says in one sentence that the keepers are AI agents building the cave live.
- **Cost.** Full concept about 39 agent-hours; v1 (a complete, alive show) about 26, two or three
  parallel agents over one working day; optional v0 trial about 6 hours. Frame cost is estimated at
  6-8 ms with 50 awake pips and must be measured with 60 synthetic pips in test mode before the
  layout lands.
- **What does not change.** ADR-000 (no synthetic engagement), ADR-001 (RTMPS), ADR-002 (secrets
  outside the repo), the two-FIFO lockstep A/V pipeline, the RoundEngine lifecycle, `agents/duty.py`
  and the macro path, the 8 legible palette presets, the -18 dBFS master, the 20 px legibility floor,
  and the fact that the 100-viewer target is the owner's and the report will state the real numbers.
