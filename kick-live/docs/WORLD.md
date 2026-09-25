# PIP HOLLOW — build-ready spec for the living-world pivot

Channel `atleastonce` on kick.com. Written 2026-09-25 by the synthesizer step of the
`kick-live-world-concept` workflow (5 persona concepts, 3 judges, this document). Starting point is
the top-ranked concept, **PIP HOLLOW** (149/180 across three judges, first on every judge's sheet),
with the judges' grafts from LOAM (both variants), TIDEPOOL and HEARTH folded in and every flagged
fatal flaw removed. ADR-004 records the choice. ADR-000 still governs everything below, and the
pivot sharpens it into one sentence that is also the art rule:

> **Every creature on screen is a real person who chatted. Darkness means nobody. Light means someone.**

What this document replaces: CONCEPT.md §1-§4 (identity, pitch, layout, scenes). What it keeps and
builds on: CONCEPT.md §5 (palette, fonts, motion rules), §6 (generated audio, extended here), §7.1
(moderation pipeline, mandatory), §8 (state.json, activity.jsonl, ships.jsonl, builders.json) and
the compositor contract in `stream/COMPOSITOR_API.md`. The pipeline is fixed: headless Python 3.9
(pillow/numpy) compositor, 1280x720 at 30 fps, one 1600-sample audio block per frame, piped to
ffmpeg through `stream/relay.py`; real Kick chat arrives as `{name, text}` within 1-3 s; hot-reload
of `stream/panels/*` and `stream/scenes/*` is the deploy path; no compositor restart without the
relay holding the frame, and no stream restart without the owner.

---

## 1. Identity

| Field | Value |
|---|---|
| **Name** | PIP HOLLOW |
| **One-liner** | A dark pixel cave on Kick that only lights up with real people. Say anything in chat and a small glowing creature (a pip) hatches carrying your name; it speaks your words, remembers you tomorrow, walks to the platform you vote for, and the whole colony is tended by visible AI keepers who carve new chambers live from chat's ideas. |
| **Stream title** (55 chars) | `Say anything in chat. A creature hatches with your name` |
| **Fallback title** (53 chars) | `Say anything. A creature hatches with your name on it` |
| **Kick category** | Keep **Software & Game Development** for the first world session, because the keepers-carve-it-live differentiator is what that category rewards and the channel already sits there. Then A/B one games/creative category over two sessions using real `viewer_count` only; the candidate category name must be read from Kick's category API through the OAuth app (never guessed), because Kick renames categories. |
| **Channel description** | A pixel cave that only lights up with real people. Say anything in chat and a creature hatches with your name on it; it remembers you tomorrow. Every 3 minutes chat votes on what happens to the colony. AI keepers carve new chambers live from chat's ideas. No camera, no mic, no fake viewers: every light in this cave is a real person. |
| **Version** | The world lands as macro-ship **v0.5.0** in the existing scheme (`v{major}.{macro}.{micro}`); rounds keep bumping `micro`, keeper builds keep bumping `macro`. |

Names: "pip", "the Hollow", "keeper", "glowmoss", "seed", "burrow", "platform", "chamber". All
invented plain words; nothing references Plaything, Thronglets, or any pet franchise, and the
art rule in §6 keeps the creatures visibly distinct from them.

---

## 2. The deep want, and the first 60 seconds

### 2.1 What people want deep down (and which mechanic serves it)

The owner's verdict was that nobody wants to interact with static text. The judges' diagnosis of
SHIP IT LIVE agrees: the object of care was the stream's own settings, the response to a person was
a line of text about code, and a lone viewer saw a dead screen until they acted, which is when
people leave. Every chat-driven format that has actually worked serves one of six wants, and PIP
HOLLOW borrows the mechanic that serves each:

| Want | Borrowed from | Mechanic here | Why it works psychologically |
|---|---|---|---|
| **Being seen**, with zero skill | Marbles on Stream (`!play` puts a ball with your name in the race within a second), Stream Avatars (a body with your name walks the bottom strip) | Any message drops a seed within one frame; three seconds later a creature with your name is saying your words in the middle of the screen. Chat text lives in the world as speech bubbles, not in a side pane. | Contingent responsiveness: something reacts to you, specifically, within seconds, where others can see it. A body reads as presence; a log line reads as a record. |
| **Nurture without guilt** | Tamagotchi (return because something depends on you), Neopets (retention is higher when the pet cannot die), community-pet streams ("who fed it last night") | Your pip's glow brightens when fed or petted and dims when ignored; at zero it curls up and sleeps. Nothing dies. Nothing decays while the stream is off. Anyone can feed anyone's pip, and the owner sees who did on wake. | Warmth, not compulsion. Guilt drives return visits for a week and churn after; a creature that is simply waiting for you drives return for months. Written rule (§10): absence is never punished. |
| **Agency you can watch land** | Twitch Plays Pokémon (one keystroke moves a shared thing), the existing A/B/C round | A bare letter makes your pip walk to a stone platform; the crowd standing there is the tally. `dig` and `plant` change terrain that is still there tomorrow. | People will type one letter if they can see their own thing move because of it. Embodied votes turn a number into a crowd you can find yourself in. |
| **Leaving a mark** | r/place (a pixel you guard for others to find) | Glowmoss planted with your name, dug tunnels confined to your own radius, learned words attributed to you, a plank of who woke the Hollow and when. | Territory and legacy. The r/place lesson also says griefing kills it, so every mark is positive-only and confined. |
| **Emergence and lore** | Twitch Plays Pokémon (Helix), Conway-life art streams (something alive to stare at) | Pips copy one another's real words with attribution, bonded pairs drift together and build nests, pad voices scale with awake count, a chat storm makes the drips race, anarchy hour. | Behaviour nobody designed, made only of real inputs, is what chat builds stories around. And the cave breathes (drips, moss pulse, sleepers) so the frame is never static between messages. |
| **Status and return** | Neopets/Tamagotchi (it noticed you came back), Marbles (regulars are known), cookie clicker (number goes up, visibly) | Tiers by sessions or minutes present, night streak, builder number, nest badge, `'ratio' learned by 4 pips, from @sam`, a nightly board, homecoming after 7+ days, "while you were gone" playback. | Endowed progress you cannot buy and other people can see. Being thought of in your absence is the strongest return signal in any community, and it costs the other person one word. |

Not borrowed, deliberately: Tamagotchi's death, cookie clicker's grind (tiers are gated on
sessions or real minutes, never on message count alone), Thronglets' look, morality or
multiplication (no breeding: every creature is one real person; lineage is a graph of real people),
and any animate non-person (the keepers are a lantern, never a figure).

### 2.2 The first 60 seconds for a stranger

**Directory tile (320x180).** The frame downscaled 4x is the sim grid at 1:1 (§5), so the tile IS
the cave: a dark rock cross-section, a jagged cave mouth top-right showing the real-clock sky and
the real moon phase, N points of coloured light (each a pip), glowmoss pulsing, and a 56 px header
count that survives the downscale: `3 AWAKE` (or `NOBODY AWAKE`) with the countdown bar under it.
Light density answers "how alive is this?" without a number. At 0 awake the tile is dark but never
dead: sky, moon, moss and the header count are all still legible (QA gate, §11).

**T+0 s, stream opens.** Pixel creatures wander a lit cavern with soft glows, one has a speech
bubble with a real chatter's last line, water drips fall and plink, the countdown bar shrinks, a
lantern hangs lit from the ceiling if a keeper is on duty. Audio is already running: a pad whose
voice count equals the awake count, drips, a chirp when a pip speaks. The wall plank at the top-left
of the world reads in 22 px: `say anything in chat. a pip hatches with your name.` If nobody is
awake: `2 pips sleep here. nobody awake. say anything and yours wakes.` (counts from `len()`).

**T+0 s after their message "hello" arrives (Kick delivery 1-3 s after the keypress).**
Within one frame: a seed drops from the ceiling at an x-position hashed from the username, lands with
a soft thud, and starts to crack. **No name is drawn yet.** The seed is nameless for exactly the 3 s
moderation hold, which the fiction hides as the egg cracking (3 sprite frames, one per second, under
the 1 Hz rule). The header count does not change yet either.

**T+3 s, hold clears.** The username has passed the blocklist (or is rendered as `builder #N`), no
mod has hidden the user. The seed pops: a pip hatches in the owner's hashed colour with its
deterministic parts, its two-note motif plays pitched from the name hash, the two-note new-builder
chime plays on a first-ever message, the label `@name` fades in above it (Menlo 20, hashed colour),
the shell fragment shows `#3` (the real builder number) for 3 s, and the pip's first bubble shows
their actual text for 6 s. Header ticks `NOBODY AWAKE` to `1 AWAKE`. Colony bar advances:
`3 have hatched here · 2 more until the Ledge opens` (from `len()`, milestone ladder §8).
If this is the session's first message: **first light**. The moss flares from ember to full glow
over 1 s, the pad's first voice rises from drips-only, and the plank writes
`@name woke the Hollow · 21:14` (real local time). If they are the only awake pip, a 20 px line
sits under their pip for 10 s: `you are the only light in the cave.`

**T+4 to T+10 s.** The plank switches for 8 s to `that's you. try: feed · pet · dig · plant · sing`.
The pip wanders (2-frame walk, 20-40 px/s on screen), blinks every 4-7 s, faces the newest speaker.

**T+10 to T+60 s.** Every further message: the pip hops once and its glow brightens within one
frame (acknowledgement before the hold), then bubbles the text after the hold with one motif note
per word chunk (capped at 6). `feed` makes the pip carry a glow-berry; `A` makes it walk to a
platform and stand there, the platform count under the letter increments, and the vote blip rises a
semitone. At 5 own messages or 10 minutes present (whichever first) the pip visibly grows a row of
pixels with a soft rising third: the first size change happens on the first night. If the round
closes in this window they see the whole colony react to one event at once (glow-rain falling on
every pip, or lights-out with only the moss showing). Nothing in these 60 s is text about the
stream itself.

**Returning chatter instead of a stranger.** Their sleeping pip (dim silhouette with label in a
burrow) stretches, glows, walks to the floor and bubbles, before their own text, the real care log:
`back after 2 nights · fed by @kai x2 · gift from @sami`. Then the bubble with their text. Cleared
after display.

---

## 3. Entity model

### 3.1 Files under `$RUN_DIR` (the isolated live run dir, `~/.local/share/kick-live/run-live`)

| File | Writer | Notes |
|---|---|---|
| `world.json` | the world module only (`stream/scenes/hollow.py`), atomic tmp + `os.replace`, flushed at most every 5 s and on session end | Pips, terrain, moss, nests, milestones, event log. Separate file, so no `state.json` ownership collision. Test runs are refused in canonical dirs by the existing run-dir guard (finding 012.1). |
| `world.json.bak-YYYYMMDD` | world module, once per session start | One bad write must never erase everyone's creature. Keep 7. |
| `builders.json` | ChatBridge (unchanged) | Source of `n` (builder number) and `first_seen`. The pip record joins on `name_lower`. |
| `chat.jsonl` | listener + webhook receiver (unchanged) | **Source of truth for `sessions_seen`, `hatched_ever` and `awake`.** Recomputed at boot by distinct `(session_id, name_lower)` with a high-water-mark cursor (`world.cursor`), never incremented on start, so the 014.2 double count cannot recur. |
| `state.json` | RoundEngine / agent (unchanged ownership) | The world reads `round`, `macro`, `agent`, `ideas`, `theme`, `micro` through `ctx`. It adds nothing to `state.json`. |
| `ships.jsonl`, `activity.jsonl` | unchanged | Event ships and keeper builds are still ships; wall scrolls quote them. |

`session_id` is `state.session.id` (set by the RoundEngine at boot); the listener's records carry
a timestamp, and the world module stamps each ingested record with the session that was live at
`t`, so history re-ingest is idempotent.

### 3.2 `world.json` example (real shape, invented values for illustration only; on screen every string comes from these records or from `len()`)

```json
{
  "schema": 1,
  "updated_ts": "2026-09-25T11:40:02.512Z",
  "cursor": {"chat_jsonl_offset": 184213, "last_id": "c7f2..."},
  "pips": {
    "sami": {
      "name": "Sami",
      "n": 2,
      "colour_idx": 3,
      "genome": {"salt": 0, "eyes": 1, "antenna": 2, "tail": 0},
      "born_ts": "2026-09-25T00:40:58.365Z",
      "sessions_seen": 2,
      "minutes_present": 47.5,
      "own_messages": 14,
      "nights_streak": 2,
      "last_seen_ts": "2026-09-25T01:12:10.000Z",
      "tier": 1,
      "energy": 0.62,
      "state": "asleep",
      "x": 212, "y": 96,
      "burrow": 1,
      "vote": null,
      "words": {"stream": 3, "cave": 2},
      "learned": [{"word": "ratio", "from": "atleastonce", "ts": "2026-09-25T00:58:00Z"}],
      "bonds": {"atleastonce": 4},
      "nickname": null,
      "care_log": [{"by": "atleastonce", "verb": "feed", "ts": "2026-09-25T11:20:00Z"}],
      "gifts_pending": [{"from": "atleastonce", "ts": "2026-09-25T11:21:00Z"}],
      "moss_planted": 1, "digs": 3, "votes_cast": 5, "events_picked": 1,
      "raised_in_nest": null,
      "strikes": 0
    }
  },
  "world": {
    "terrain_b64": "<320x110 bit-packed carved/solid mask, 4.4 KB>",
    "moss": [{"x": 140, "y": 90, "planter": "sami", "ts": "2026-09-25T00:50:00Z", "size": 2}],
    "nests": [{"x": 180, "y": 92, "parents": ["atleastonce", "sami"], "built_ts": "...", "hatched": []}],
    "chambers": [{"name": "the Hollow", "opened_ts": "2026-09-25T11:30:00Z", "by": null, "milestone": 0}],
    "milestones": [3, 5, 10, 25, 50],
    "hatched_ever": 2,
    "woke_log": [{"name": "atleastonce", "ts": "2026-09-25T11:31:04Z"}],
    "visits": [{"name": "sami", "ts": "2026-09-25T01:12:10Z"}],
    "board": {"session_id": "2026-09-25T11:30Z", "fed": {"atleastonce": 3}, "dug": {"sami": 2}, "hatched": ["kai"]},
    "event_log": [{"ts": "...", "text": "glow-rain, picked by @sami"}]
  }
}
```

### 3.3 Field rules

**Identity (immutable after hatch).** `name` (display case as Kick sent it), `n` (from
`builders.json`), `colour_idx` = `hash(name_lower) % 6` into the active preset's 6-colour username
set (so `!theme` retints the whole colony coherently and the colour is the same one the chat pluck
already uses), `genome` derived from `sha1(name_lower + salt)`: eyes 0-3, antenna 0-3, tail 0-2, body
stencil 0-3. `salt` starts at 0 and is incremented only by the reject-and-reseed check at hatch
(§6.2), then stored, so the creature is identical every night. Pip identity fields are never
recomputed: people who care about their pip will notice a wrong colour.

**Presence (honest, derived).** `state` is one of `seed / hatching / awake / walking / voting /
curled / asleep / burrowed`. **Awake = the owner chatted in the last 20 min of this session.** At 20
min of silence the pip yawns, walks to its burrow and sleeps with the label `asleep · quiet 20 min`.
A sleeping pip never walks, votes, speaks or eats; it may twitch (2-frame, every 8-15 s). Any
message wakes it. `awake` on screen is always `len([p for p in pips if p.state not in (asleep,
burrowed)])`, and the self-test asserts every frame that this equals the number of distinct chatters
in the last 20 min of the session.

**Energy (cosmetic only).** 0.0-1.0. +0.15 per own message, +0.10 per feed or pet received, -0.01
per minute awake with no attention. Below 0.2 the pip curls up and its glow dims to 40%. It never
reaches a state a viewer could read as punishment: no hunger bubble, no sad face, no death. **No
decay while the stream is off**, and no decay while asleep. A future keeper who adds hunger or
death is reverted (rule in §10).

**Growth (sessions or minutes, never message grinding alone).**

| Tier | Name | Sim size | Reached when (any one) | First-night reachable |
|---|---|---|---|---|
| 0 | seedling | 10x8 | hatch | yes |
| 1 | hatchling | 12x10 | 5 own messages **or** 10 min present | **yes, by design** (LOAM graft) |
| 2 | pip | 12x10, longer antenna, glow radius +2 | 3 distinct sessions **or** 120 min present | no |
| 3 | elder | 14x12 + crest | 10 distinct sessions **or** 600 min present | no |

`minutes_present` accumulates from timestamps only while the stream is live and the pip is awake
(HEARTH graft: a lurker who typed once and then watched still grows). `nights_streak` counts
consecutive stream sessions attended. Tier-ups play on screen (pixel rows grow over 12 frames, soft
rising third) and log to the ticker.

**Memory.** `words`: the owner's top 8 real tokens (stop-words and blocklist removed; a token that
equals another chatter's username is excluded, no impersonation). An idle awake pip mutters one
every ~90 s in a small bubble. `learned`: up to 3 tokens copied from a neighbouring awake pip within
3 sim tiles, each carrying the source name and time; a learned word is spoken as `ratio · from
@sam`. Words that pips repeat unprompted must be in a dictionary allowlist **and** pass the
blocklist (§10). `forget` purges both lists.

**Bonds and lineage (a graph of real people, never a creature).** `bonds[other] += 1` per feed or
pet in either direction. Bonded pairs (3+ both ways) drift toward each other when both are awake
and, at 3+ both ways, **build a nest** (a 6x4 twig sprite on the floor). The next new chatter's seed
lands in the oldest empty nest; their hatch bubble adds one lore line for 6 s (`hatched in @a and
@b's nest`), the nest records the hatchling, and the two godparents get a permanent nest badge (a 2
px twig on their label). The newcomer's label does **not** carry the godparents forever; lineage
is visible status for regulars and optional lore for the newcomer, never imposed identity (judge 2's
condition). No breeding, no child creatures.

**Care log and gifts.** `care_log` accumulates verbs done to a sleeping or absent pip (`feed`,
`pet`, `gift`) with the real doer and time; shown once as a bubble on wake, then cleared.
`gifts_pending` render as a small wrapped pixel at the burrow until the owner returns.

**Strikes.** `strikes` counts blocklist hits on the owner's text this session; at 3 the pip burrows
for the rest of the session with the on-screen reason `burrowed: 3 filtered messages` (§10).

### 3.4 Colony state

`terrain` is a 320x110 bit-packed mask of carved (1) versus solid (0) rock, persisted; `dig`
flips 3x3 cells inside the digger's own radius (8 sim px around their pip), so nobody can deface
another person's work. `moss` is planted glowmoss with planter and size 0-3 (grows over 10 min of
stream time, then stays lit forever). `chambers` are the keeper-carved regions unlocked by the
milestone ladder (§8). `woke_log` and `visits` feed the plank; `board` accumulates the nightly board
(§8). `hatched_ever` is `len(pips)` and is recomputed from `chat.jsonl` at boot.

Session end (`scripts/stop.sh --credits`): every awake pip walks to its burrow one by one with its
name and minutes tonight (real credits), `world.json` is flushed, nothing decays. Next session
starts from the sleeping colony.

---

## 4. Verbs

Parsing runs on moderated `chat.jsonl` records (§10). **Exact-token rule:** a plain-word verb
matches only when the trimmed, lower-cased message is exactly the verb, or the verb followed by one
`@name` argument, or is `!`-prefixed: `^!?(feed|pet|dig|plant|sing|wave|sit|duck|gift|name|teach|forget)(\s+@?[a-z0-9_]{1,25})?(\s+[a-z0-9]{1,12})?$`.
"sing" inside a sentence, "right?", "I dug it" do nothing. Every refusal (cooldown, cap, unknown
target) prints its reason on the plank for 4 s, so a second person trying never sees nothing happen.
Plain-word verbs still count as messages (they wake, brighten and bubble). "Latency" below is time
from the record landing in the compositor; Kick delivery adds 1-3 s before that.

| Word | Effect on screen | Latency | Rate limit | Who |
|---|---|---|---|---|
| **any message** | First ever: seed drops within 1 frame, hatches at hold +3 s with name and builder `#N`. Otherwise: pip hops and brightens within 1 frame; after the hold, bubble with the text (Menlo 22, wrapped 3 lines, 6 s, one bubble per pip at a time) and motif chirp per word chunk (max 6). Wakes a sleeping pip. +0.15 energy. First message of the session: first light. | acknowledgement 1 frame; text at +3 s | render 1 per 2 s per user (existing) | everyone |
| **A / B / C** (`^!?[abc]$`, unchanged) | Pip walks to that stone platform and stands there for the round; platform count = pips standing on it; a new letter makes it walk over; vote blip rises a semitone per vote. | walk starts within 1 frame, arrives in 1-3 s | 1 vote per user per round | everyone |
| **feed [@name]** | Pip carries a glow-berry (walk) to its own spot or to the target; both flash, target +0.10 energy, soft pop, `bonds` +1. Target asleep or absent: the berry is left at the burrow and goes into their `care_log`. | 1-3 s walk | 1 per 30 s per user | everyone |
| **pet [@name]** | Pip boops the target; both bob twice, hearts (3 pixels), two-note duet from both name hashes; `bonds` +1. Asleep target: logged to `care_log`, pip yawns once (honest: owner absent). | 1-3 s walk | 1 per 30 s per user | everyone |
| **gift @name** | Only at a **sleeping or absent** pip: a wrapped 3x3 pixel is left at their burrow and shown there until the owner returns; played back on wake as `gift from @you`. | 1-3 s walk | 1 per target per session | everyone |
| **dig** | Pip carves 3x3 sim cells beside or below itself, within its own 8-px radius; terrain persists. Floor cells under platforms and the cave mouth are protected. Cap 40 cells per user per session (`dig cap reached tonight`). | immediate, 1 s animation | 1 per 10 s per user | everyone |
| **plant** | Plants glowmoss at the pip's feet labelled on a 5 s rotation `moss · @name · night 3`; grows over 10 min, lit forever even when the planter sleeps. | immediate | 1 per user per session | everyone |
| **sing** | Pip's motif as a 2-bar phrase; awake pips within 6 tiles echo one bar later in their own pitch (audible colony size). | next beat (< 0.7 s) | 1 per 60 s per pip, 1 per 10 s globally | everyone |
| **wave / sit / duck** | 2-frame emote on your own pip (wave at camera, sit, duck under a ledge). Cheap identity play. | 1 frame | 1 per 5 s per user | everyone |
| **name <word>** | Nickname (12 chars, blocklist, dictionary allowlist not required, **may not equal any chatter's username**); label becomes `Muffin (@sam)`, 20 px. The `@username` part never disappears. | +3 s (hold) | 1 per 10 min per user | everyone |
| **teach <word>** *(v2)* | Adds one word to your pip's `words` for neighbours to learn; dictionary allowlist + blocklist. | +3 s (hold) | 1 per 5 min per user | everyone |
| **forget** | Purges your `words`, `learned` and `care_log`; plank confirms `@name's pip forgot everything`. | 1 frame | none | everyone |
| **!idea <text>** (unchanged) | A scroll is pinned to the cave wall with your name; keepers classify it `instant` (a platform option next round), `carving next` (macro), or `declined: <reason>`. | 1 frame; built in 15-20 min if a keeper is on duty | 1 per 3 min per user, 3 open | everyone |
| **!theme <preset>** (unchanged) | Cave light, moss and every pip retint to the preset on the next frame; plank `@name changed the light: ember`. | next frame | 60 s global | everyone |
| **!help**, **!stats** (unchanged) | Plank cycles the legend 20 s; stats card in the colony panel 10 s. | 1 frame | 30 s global | everyone |
| **!hide <user>** / **!unhide** | Existing mod primitive, now also: the pip burrows (silhouette + label removed), its bubbles, moss labels and learned words vanish, its votes are ignored for the session. | immediate | none | broadcaster / moderator badge |
| **!banish <user>** | `!hide` plus: the pip is removed from `world.json` (record kept in `world.json.banished` for audit, never rendered again until `!unbanish`), its moss and digs are reverted, its nickname deleted. Chat log shows a shield chip. | immediate | none | broadcaster / moderator badge |
| **!pause / !resume, !clear, !kill / !unkill** | Unchanged. `!kill` replaces every label with nothing and every bubble with `chat hidden by mod`; pips stay as unlabelled lights (they are still real people, only names are hidden). | immediate | none | as CONCEPT §7 |

Verbs are positive-only by construction: nothing a viewer can type harms another viewer's pip,
moss or terrain. In chat floods the existing pluck auto-mute (>10 msg/min) applies to chirps too.

---

## 5. Layout (1280x720)

The world takes the stage. The header and countdown stay as the thumbnail hook; the chat pane,
ballot, stage, activity feed, founders, ask card and next-up regions go: chat becomes bubbles in the
world, the ballot becomes three stone platforms, the stage becomes the lantern and one plain line,
ideas become wall scrolls. A compact 5-line chat log survives at bottom-right for moderation
visibility. Canvas 1280x720, base `#0B0E14`, geometry fixed (rounds may change colour, content and
behaviour, never geometry). **Every text item is drawn at screen scale, never inside the sim grid**,
so no pixel-font smear on Kick's 3 Mbps encode; nothing on screen is under 20 px.

```
 x: 0                                420                 840                       1280
+--------------------------------------------------------------------------------------+ y=0
| HEADER  atleastonce · PIP HOLLOW | 3 AWAKE · 17 HATCHED  NEXT EVENT 01:23 | LIVE 3 watching |
|====================================== countdown bar (66-72) =========================| 72
| WORLD  sim 320x110 at 4x                                                             |
|   plank (top-left, 22 px)      cave mouth: real sky + moon (top-right)   lantern      |
|   pips + labels + bubbles wander the cavern; platforms A B C on the floor            |
|   sleeping pips in burrows along the lower wall; moss; drips                         |
|                                                                                      | 512
| COLONY  bar · awake/asleep · last event | KEEPER  lantern line, build line | CHAT LOG 5 lines |
|         nightly board rotation          | (traceback only on failure)      | (moderation)     | 656
| TICKER  events · honesty line · legend         | SCOPE  | chat 0.4/min 30 fps 11 ms   |
+------------------------------------------------+--------+-----------------------------+ 720
                                                 880      1040
```

| # | Region key | Box (x, y, w, h) | Content | Font | Updates |
|---|---|---|---|---|---|
| 1 | `header_left` | 0, 0, 300, 66 | `atleastonce · PIP HOLLOW` wordmark; chat-link dot (unchanged) | HN Medium 22 | on state change |
| 2 | `header_center` (the thumbnail) | 300, 0, 620, 66 | `3 AWAKE` at **56 px** (`NOBODY AWAKE` at 40 px when 0); right of it `· 17 HATCHED` 24 px and `NEXT EVENT 01:23` 24 px; during a keeper build a 20 px line `keeper carving · 12:40 left` | AB 56 / Menlo 24 / Menlo 20 | every frame (clock) |
| 3 | `header_right` | 920, 0, 360, 66 | red LIVE dot + `3 watching` (real `viewer_count` or `--`); version `v0.5.3` at 22 px (moved here from centre) | Menlo 22 | viewers every 15 s |
| 4 | `countdown` | 0, 66, 1280, 6 | unchanged: shrinks right-to-left over the 180 s round; amber < 30 s, red < 10 s | none | every frame |
| 5 | **`world`** (new) | 0, 72, 1280, 440 | The cave: 320x110 sim upscaled 4x (§6), then the screen-scale text layer: plank at (16, 84) 22 px; pip labels Menlo 20 centred above each awake pip (sleepers labelled on a 5 s rotation); bubbles Menlo 22 in a `#11151D` box with 1 px `#1C2130` border, max 408 px wide, 3 lines; platform letters AB 56 carved above each platform with the count Menlo 22 and last 3 names Menlo 20 under it; wall scrolls (ideas) HN Medium 22, max 3 visible on the right wall; moss labels Menlo 20 on rotation; keeper lantern at sim (300, 2). Density fallback: above 40 awake, labels switch to label-on-speak (6 s) and sleepers stop rotating labels. | Menlo 20/22, HN Medium 22, AB 56 | every frame (sim), text cached per string |
| 6 | **`colony`** (new) | 0, 512, 420, 144 | Line 1 HN Medium 22: `17 have hatched here · 3 more until the Pool opens` over an 8 px bar (real fraction). Line 2 Menlo 22: `3 awake · 14 asleep · night 4 for @sami`. Line 3 Menlo 20 rotating every 8 s: last event (`glow-rain · picked by @sami · v0.5.3`), nightly board (`last night: @sami fed 6 pips · @kai dug the most · 1 hatched`), storm notice, or `!stats` card for 10 s. | HN Medium 22 / Menlo 22 / Menlo 20 | on change, 8 s rotation |
| 7 | **`keeper`** (new) | 420, 512, 420, 144 | Line 1 HN Medium 22: `keeper on duty` / `no keeper on duty · scrolls kept for next time` (from `agent.heartbeat_ts`). Line 2 Menlo 22: `carving: the Pool · asked by @sam · 12:40 left` or `last carved: East Chamber · v0.5.0 · asked by @sam`. Lines 3-5 Menlo 20 **only on failure**, for 20 s: first 3 traceback lines + `reverting to v0.4.2`. Never a live diff during normal play. | HN Medium 22 / Menlo 22 / Menlo 20 | on macro state change |
| 8 | **`chat_log`** (new, replaces `chat_pane`) | 840, 512, 440, 144 | Last 5 moderated messages past the hold, newest at bottom, Menlo 22 at 26 px line height, username in hashed colour, letter chip on votes, shield chip on mod actions. Empty: `chat is quiet. say anything.` `!kill`: `chat hidden by mod`. Exists for moderation visibility on the VOD; the show does not depend on it. | Menlo 22 | under 1 s of a message (after the hold) |
| 9 | `ticker` | 0, 656, 880, 64 | unchanged crawl: last 10 events/ships with real pickers, honesty line `no camera, no mic, no fake viewers. every light in this cave is a real person.`, command legend (`feed · pet · dig · plant · sing · A/B/C · !idea`) | HN Medium 24 | every frame |
| 10 | `scope` | 880, 656, 160, 64 | unchanged | none | every frame |
| 11 | `readout` | 1040, 656, 240, 64 | unchanged (`chat 0.4/m · 2 ppl` / `30fps 11ms up 01:23`), plus `world: glow off` when degraded (§6.5) | Menlo 20 | 1 s |

Removed regions: `stage_title`, `stage_step`, `stage_body`, `activity_feed`, `ballot`, `chat_pinned`,
`chat_pane`, `founders`, `ask_card`, `next_up`. Their information moves: stage → lantern + keeper
strip; activity feed → keeper strip line 2 and the ticker; ballot → platforms; pinned strip → plank;
chat → bubbles + chat log; founders → plank `woke the Hollow` line and nightly board; next up → wall
scrolls; ask card → not carried (`!ask` stays hidden until a responder exists, as before).

Legibility gates (QA agent, every round, extended): downscale a captured frame to 320x180 and
confirm (a) the awake count reads, (b) at least one light source (pip glow **or** moss **or** the
cave-mouth sky) is visible when 0 pips are awake, so the tile never reads as offline, (c) every text
item in the 720p frame is ≥ 20 px, (d) the header is drawn over every world state including event
transitions.

---

## 6. Art direction and frame budget

### 6.1 The cave (sim grid 320x110, 1 sim px = 4x4 screen px = 1 thumbnail px)

Side-view cross-section. Sim rows: ceiling rock 0-13 with the **cave mouth** at x 236-268, rows
0-12, a jagged opening showing the sky; cavern void 14-87; floor 88-91; soil and lower wall 92-109
with 16 burrow slots (each 14x8) for sleeping pips and room for moss. Three stone platforms on the
floor at x 40, 160, 280 (each 24 wide, 3 tall). The lantern chain hangs from (300, 0) to (300, 10).
Wall scrolls occupy the right wall x 290-318, rows 20-60 (drawn at screen scale). A carved region
for the first keeper chamber starts solid at x 0-40 (the Ledge) so the first milestone visibly opens
rock that a viewer has been looking at.

Colours (from CONCEPT §5, no new hexes): solid rock `#11151D` with 1 px hairline edges `#1C2130`,
void `#0B0E14`, floor `#1C2130`, platform tops the preset accent at 60%, moss the accent, pip bodies
from the preset's 6-colour username set, eyes `#E6E8EE`. The sky in the mouth is a 3-stop gradient
keyed to the real local hour (night `#0B0E14` → `#141A2A` with 6 twinkling star pixels on a 3-6 s
cycle; day `#1D2B4A` → `#3A5F8A`, muted so light-coloured names keep 4.5:1 over rock), with a 5x5
pixel moon whose phase is computed from the date (synodic period 29.53 d from the 2000-01-06 new
moon). Water drips: 1 px lines falling from the ceiling to the floor at 2 px/frame, 2-6 s apart,
seeded per session.

### 6.2 Pips (the only animate things, one per real person)

Side-view, low to the ground, **angular**: a wedge body drawn from one of 4 mirrored-row stencils
with a darker outline (the preset colour at 55%), 1 px legs (2), a tail (3 variants: stub, curl,
fin), an antenna or ear pair (4 variants: none, single, twin, fan), and a 2 px eye (4 placements)
with a 1 px `#E6E8EE` highlight, which is what makes a 12x10 blob read as alive. Sizes by tier
10x8 / 12x10 / 12x10 / 14x12 sim px (40x32 to 56x48 on screen; 10-14 px light dots on the tile).
Frames: idle 2 (1 px bob at 0.5 Hz), walk 2 (alternate legs, 1 px bob), blink 1 (every 4-7 s),
speak 1 (mouth notch), curled 1, asleep 1 (flat, eye closed), emote 2 each (wave, sit, duck), egg 3.
All frames are generated at startup from numpy stencils, no asset files.

**Reject-and-reseed at hatch** (LOAM graft): a genome is rejected when body fill is outside 35-70%
of the stencil box, the outline has no contrast against the void, or the eye lands outside the body;
`salt` increments (deterministically) until it passes, then is stored. Every `(name, tier, preset,
frame)` sprite is cached as a small RGB array plus alpha mask; the cache is bounded at 2,000 entries.

**Art note, kept in the repo as `docs/art-rules.md`:** pips are not Thronglets or any pet franchise.
Concretely: no yellow default (colour comes from the name and the preset), no round bodies, no big
round faces, no fur, no upright stance, no plant-headed helpers, no multiplication, no morality
mechanic. Review the 288-look sheet (`--self-test` writes `selftest/pips_sheet.png`) against this
note before the world goes live.

### 6.3 Glow

Each awake pip adds a precomputed 24x24 radial kernel in its colour into a float32 light buffer
(320x110x3) by slicing (50 pips is ~85k float adds, well under 1 ms); brightness = 0.4 + 0.6 ×
energy; curled pips at 40%. Moss adds a smaller 12x12 kernel pulsing at 0.25 Hz. The buffer is
clipped and added over the cave. **Light density is the honest population meter**: at 0 awake only
moss and the sky light the cave.

### 6.4 Motion rules (CONCEPT §5 kept)

Something moves every frame (drips, bob, glow LFO, sky twinkle). Nothing flashes faster than 1 Hz.
Walks ease over 8-10 frames; event transitions (rain starting, lights-out) fade over 1 s and never
cover the header; no full-frame fills. Pips wander at 20-40 screen px/s with pauses, drift toward the
newest speaker, and bonded pairs drift together.

### 6.5 Staying under ~10 ms per frame in numpy/pillow

| Step | Cost (estimated on this Mac; measure in `--self-test` with 60 synthetic pips in **test mode only**) |
|---|---|
| Static cave layer (rock, floor, burrows, sky) rebuilt only when terrain, preset or the minute changes; kept as a uint8 320x110x3 array | 0 ms per frame typical |
| Glow buffer: N kernel slices + moss + clip | < 1 ms |
| Sprite blits: N cached frames via boolean-mask slicing | ~0.02 ms each, ~1 ms at 50 |
| Drips, hearts, berries, rain particles as index writes | < 0.5 ms |
| Upscale: `np.repeat(np.repeat(a, 4, 0), 4, 1)` → 1280x440x3, `Image.fromarray` | ~1.5-2 ms |
| Text layer: labels and bubbles are cached RGBA images per string; pasted at screen scale | ~0.05 ms each, ~2 ms at 40 |
| Total, 50 awake pips | **~6-8 ms**, `budget_ms = 24` |

**Graceful degrade is a prerequisite, not a nice-to-have.** The world panel never returns a
placeholder: `render()` wraps everything, and on an internal error returns the last good frame plus
one activity line. If its own render time exceeds 16 ms averaged over 30 renders it drops glow
(`world: glow off` in the readout); over 20 ms it switches to label-on-speak and drops moss labels;
over 24 ms it drops bubbles to a single shared line. It restores one step every 300 clean frames.
The frame-time guard in the compositor stays as the last resort but the ladder is designed so it
never fires on this panel.

---

## 7. Audio (numpy, 1600 samples per frame, unchanged plumbing)

| Layer | Design | Level |
|---|---|---|
| Pad | The existing A-minor pad, but the **number of voices equals the awake count** (0 awake = no pad, drips and crackle only; each awake pip adds one detuned voice up to 8). The colony's size is audible; an empty cave sounds empty. First light = the first voice fading in over 2 s. | -24 dBFS |
| Drips | Seeded impulses through a 2-pole resonator at random pentatonic pitches, every 2-6 s; storms (§8) shorten the interval to 0.3-1 s. | -30 dBFS |
| Crackle | Kept (sparse impulse noise through a 2 kHz low-pass). | -40 dBFS |
| Pip voice | The existing Karplus-Strong pluck pitched by `hash(name) % 10` over two octaves (regulars keep the audible identity they already have). Speaking = its two-note motif (degree, degree+2), one note per word chunk, max 6, rate-limited 1 per 250 ms and auto-muted above 10 msg/min. | -20 dBFS |
| Hatch | The existing G5-C6 two-note new-builder rise, then the pip's motif. | -20 dBFS |
| Wake / sleep | Soft rising third / descending third. | -26 dBFS |
| Tier-up | Rising third with a 300 ms low-pass sweep. | -20 dBFS |
| Feed / pet | Soft pop / two-note duet built from both pips' degrees (a dyad). | -22 dBFS |
| Gift left | 200 ms triangle two-note. | -24 dBFS |
| Dig / plant | Low thud / low thud then a high sparkle. | -22 dBFS |
| Sing | 2-bar phrase on the pip's degree; neighbours echo one bar later in their own pitch. | -20 dBFS |
| Vote | Footstep click per step while walking (rate-limited), then the existing vote blip on platform arrival, rising a semitone per vote. | -22 dBFS |
| Round close | Existing ticks for the last 10 s. | -22 dBFS |
| Event ship | Existing major arpeggio chime plus a 600 ms low-pass sweep; lights-out drops the pad to the sub voice; feast = the chime as a full chord; glow-rain = pink noise through a 1.5 kHz low-pass at -34 dBFS while it falls. | -16 dBFS |
| Keeper | Lantern lowering = slow chain rattle (filtered noise bursts); carve ship = chime + a low rock rumble; fail = the existing descending saw and thud. | -20 dBFS |

Master unchanged: -18 dBFS integrated, tanh limiter, -6 dBFS ceiling. Fallbacks unchanged
(`aevalsrc` bed, looped WAV). Everything synthesised; nothing sampled.

---

## 8. The collective: rounds as world events, plus emergence

### 8.1 The 3-minute round, re-skinned (RoundEngine lifecycle untouched)

`open` (0-150 s) → `closing` (150-180 s) → `ship` (5 s) → next `open`, exactly as today. Only the
MENU and the rendering change. Voting is embodied: a bare letter walks your pip to the platform, the
count under each letter is `len(pips standing there)`, the leading platform's pips bounce during the
last 30 s. At 0:00 the event lands on the whole colony at once, so every viewer's creature reacts in
the same second. Zero votes: platforms stay empty and the plank says `nobody voted. the keepers
picked B.` when a keeper heartbeat is fresh, otherwise `nobody voted. the Hollow picked B itself.`
(the existing `agent_pick: true` record, honestly labelled). Ships still write `ships.jsonl`,
CHANGELOG and bump `micro`.

New MENU (world events; one option per round may still be an `instant`-classified `!idea`):

| param | values | what happens for 3 min (or once) | title on the platform |
|---|---|---|---|
| `weather` | glow-rain, fog, lights-out, clear | glow-rain: falling accent pixels, every awake pip +0.3 energy; fog: light radius halves; lights-out: only moss and the sky light the cave; clear | `glow-rain`, `fog`, `lights out`, `clear` |
| `colony_rule` | follow, scatter, huddle, free | pips follow the most recent speaker / spread out / gather at the centre / wander | `follow the newest voice`, ... |
| `feast` | now | every awake pip is fed at once, chord chime, hearts | `feast: everyone eats` |
| `dig_site` | open | a 20x8 region glows; digs there count double for 3 min | `open a dig site` |
| `music` | tempo 72/85/100, pattern | as today (`audio_tempo`, `audio_pattern`) | `tempo: 100 bpm` |
| `light` | 8 presets | the existing palette ship (`theme.preset`) | `light: ember` |
| `anarchy` | hour | rare (never two rounds running): for 3 min bare direction words (`left`, `right`, `up`, `down`, exact-token) from anyone move **all** awake pips together; each move is attributed on the ticker to the real typist | `anarchy: everyone steers everyone` |
| `chaos` | roll | kept from v0.4.0: rolls one other parameter, title rewritten to what actually changed | `chaos: randomise one thing` |
| `migration` *(v2, when a second chamber exists)* | go | all awake pips walk to the edge and the camera pans to the newest keeper-carved chamber | `migrate to the Pool` |

### 8.2 Colony milestones (real humans only)

The colony bar counts **distinct real people who have ever hatched** (`len(pips)`). Ladder:
**3, 5, 10, 25, 50** (corrected for reality: `builders.json` holds two humans today, so the first
milestone is one stranger away and reads as reachable, not stalled). Reaching one queues a keeper
macro-ship that carves a named chamber (the Ledge, East Chamber, the Pool, the Deep, ...); the
lantern descends, the rock is carved live over the build, every awake pip turns to look, and the
wall scroll credits the person whose hatch crossed the line: `the Ledge · opened by @kai's hatch ·
v0.6.0`. If no keeper is on duty when a milestone lands, the bar says `milestone reached · keepers
will carve it next session` and the scroll waits.

### 8.3 Emergent events (from real inputs only)

- **First light**: the session's first message wakes the Hollow (§2.2).
- **Storm**: when real chat rate exceeds 20 msg/min (from `chat_stats.msgs_per_min_5m` and the
  live 1-min window), drips race, glow flickers at ≤ 1 Hz, bubbles shorten to 4 s. An honest
  visualisation of load that gives 200 people typing a shared effect and doubles as the bubble
  density fallback.
- **Chorus**: 3+ distinct pips `sing` within 10 s → their motifs stack into a sustained chord and
  every awake pip sways.
- **Word spread**: pips within 3 tiles pick up one real word from a neighbour; the ticker notes
  `'ratio' learned by 4 pips, from @sam` when a word reaches 3+ pips.
- **Nest built**: two bonded regulars' pips carry twigs to a spot and build a nest (§3.3).
- **Homecoming**: a returner after 7+ days: every awake pip turns to face their burrow for 3 s.
- **Nightly board**: at session start the colony panel rotates `last night: @sami fed 6 pips ·
  @kai dug the most · 1 hatched`, from `world.board` of the previous session.
- **Credits**: at `stop.sh --credits`, pips walk to their burrows one by one with name and minutes.

---

## 9. Keepers: agents as the world's tenders (never creatures)

The AI agents are the only non-chatter presence on screen and they are labelled for exactly what
they are. Representation: a **lantern on a chain** in the ceiling at sim (300, 2). Never a figure,
hooded or otherwise; the entity rule admits objects and weather, not animate non-persons.

| Agent state | Lantern | Keeper strip (region 7) |
|---|---|---|
| `agent.heartbeat_ts` fresh (< 120 s) | lowered, lit, gentle 0.25 Hz flicker | `keeper on duty` |
| stale / absent | raised, dark | `no keeper on duty · scrolls kept for next time` |
| `macro.active` | swings slowly (0.5 Hz), chain rattle once on start | `carving: <macro.title> · asked by @<requested_by> · 12:40 left`. **No diff strip.** Plain language only. |
| macro ships (`last_reload.ok`) | flares for 1 s, chime + rumble | `last carved: <title> · v0.5.0 · asked by @sam`; in the world: rock crumbles into the new chamber / the new object appears / a wall scroll announces a new verb (`new: gift @name — leave something at a sleeping pip`); every awake pip turns to look; ticker `SHIPPED v0.5.0 · East Chamber · asked by @sam` |
| macro fails | flickers red once | first 3 traceback lines + `reverting to v0.4.2` for 20 s (failure is still content, only shown when it happens); header scoreline unchanged in `ships.jsonl` |

`!idea` pins a wall scroll with the requester's name; the keeper's `classify` (existing
`agents/duty.py`) moves it to `carving next`, makes it an `instant` platform option, or marks it
`declined: <reason>` in grey. Keepers never speak in chat (they cannot post), never appear as a
creature, and every line they write on screen is labelled `keeper`. The hot-reload path
(`stream/scenes/`, `stream/panels/`, register-replace by key) is literally how keepers carve: a new
chamber, verb, event or behaviour is a new or edited module that lands without touching ingest, and
the fiction says so in one sentence on the ticker: `the keepers are AI agents. they build this cave
live, from your !ideas, and you watch it land.`

Owner's two chat ideas map here directly: "a pixel art bot that responds" is your pip speaking your
words; "a little pixel dude on screen" is your pip (yours, not a mascot).

---

## 10. Empty, alone, and honest

**Nobody has ever chatted** (a fresh run dir): a dark cave with the sky in the mouth, moss-less,
plank `nobody has hatched here yet. say anything and you are the first.`, header `NOBODY AWAKE · 0
HATCHED`, drips only.

**Nobody awake, N asleep** (the normal state at this channel's size): sleeping silhouettes in
burrows with labels on a 5 s rotation (`@sami · asleep · last seen yesterday 10:40`), moss pulsing,
the sky and moon in the mouth, gifts wrapped at burrows, the lantern honest, the round running with
empty platforms and the amber plank under 30 s `nobody voted yet. your letter alone decides this
one.` The plank's idle rotation shows the **last five real visitors with real timestamps** (HEARTH
graft) so an empty cave reads as waiting for someone, not offline. Header `NOBODY AWAKE · 2 HATCHED`.
Pad silent; drips and crackle only.

**One person, dead night.** Their message is first light: the moss flares, the first pad voice
rises, the plank writes `@name woke the Hollow · 23:14`, and under their pip for 10 s:
`you are the only light in the cave.` Being the lone waker of a sleeping colony is a stronger moment
than being one of fifty, and it is true. Within ten minutes they see their pip grow a row of pixels,
they can `dig` and `plant` marks that are still there tomorrow, `gift` a sleeper (a small act toward
a real person who is not there), and their one letter decides the next event for the whole colony.
The cave keeps breathing between their messages (drips, sky, moss, sleepers' twitches), so the frame
is never static.

**Written rule, added to the top of this spec and to `docs/art-rules.md`: absence is never
punished.** No decay while the stream is off, no hunger, no death, no copy that blames the viewer
(`nobody voted` is a fact, `you let it die` never appears). A future keeper who adds any of these
"to improve engagement" is reverted.

---

## 11. Honesty and moderation

**Honesty, made mechanical**
- A pip is created only inside the chat-ingest path from a moderated record with a real Kick
  username; there is no other constructor. `--self-test` asserts every frame:
  `len(awake pips) == len(distinct chatters in the last 20 min of this session)` and
  `len(pips) == len(distinct chatters ever in chat.jsonl minus banished)`.
- Every count on screen (awake, asleep, hatched, platform tallies, colony bar, `learned by 4
  pips`) is a `len()` over real records. No sample string from this document is ever drawn.
- Sleeping pips are real past chatters with `last seen` computed from stored timestamps; they never
  act as if present.
- Pips never generate text: every word is the owner's own message, one of the owner's own tokens,
  or a learned word carrying the real source's name. Keepers never speak as a creature.
- The lantern is lit only on a fresh heartbeat. Zero-vote picks say who picked.
- Viewer count is the real API value or `--`. Ticker keeps the honesty line.
- `sessions_seen`, `hatched_ever` and `awake` are recomputed from `chat.jsonl` by distinct
  `(session, owner)` with a cursor (fixes 014.2); `world.json` lives only in the isolated run dir
  and test runs are refused there (012.1).

**Moderation (CONCEPT §7.1 applies in full; the new surface adds these)**
1. **No name is drawn before the 3 s hold clears and the username has passed the blocklist**
   (closes 014.1 for the new surface instead of widening it). The pre-hold seed is nameless. A
   username that hits the blocklist hatches as `builder #N` everywhere (label, plank, bubbles,
   moss, scrolls, board, ticker). A user hidden by a mod inside the hold never hatches: the seed sinks
   (`the soil did not take that one`).
2. `chat_bridge.tallies()` and every other name accessor used by the world go through the same
   `display_name` filter as `visible()`; the raw-name path is deleted, not bypassed.
3. Bubbles, nicknames, taught words and idea scrolls pass the text blocklist (79 terms today,
   leet-normalised, whole-token). Words a pip repeats unprompted (`words`, `learned`, `teach`) must
   also be in a **dictionary allowlist** (`stream/moderation/allowlist_words.txt`, plain English
   words plus the channel's harmless slang, hot-reloaded like the blocklist).
4. **No impersonation**: a nickname or taught word may not equal any chatter's username
   (case-insensitive) or `keeper`, `mod`, `atleastonce`.
5. **Three strikes**: three blocklist hits on one user's text in a session burrow their pip for the
   session with the reason on the plank (`@name's pip burrowed: 3 filtered messages`); the message
   drop counter in `!stats` still increments.
6. **What a mod can do** (broadcaster or moderator badge, immediate, mirrored to `state.mod`):
   `!hide` (burrow + remove label, bubbles, votes, moss labels for the session), `!banish` (remove
   from the world and revert marks; audit record kept), `!unhide` / `!unbanish`, `!pause`
   (bubbles stop, pips keep moving), `!clear` (scrolls), `!kill` (every name off screen, pips stay
   as unlabelled lights), plus `!rename <user>` to strip a nickname. The compact chat log keeps the
   moderator's visibility of raw-ish chat on the VOD.
7. Verbs match exact tokens only (§4), so ordinary chat never triggers anything.
8. Positive-only verbs, per-user and global rate limits shown on refusal, digging confined to the
   digger's radius, one bubble per pip, pluck/chirp auto-mute above 10 msg/min: nobody can grief
   another person's pip, and a flood cannot turn the cave into noise.
9. Webhook test messages, the compositor's own activity lines and keeper `say` lines never create
   or wake a pip.

---

## 12. Build order (agent-hours) and the v1 cut

Prerequisites before any name is drawn on a body (all already scoped in the Harden phase):
014.1 filtered-name path, 014.2 recompute-from-chat.jsonl, 012.1 run-dir guard, write ownership,
relay + hot-reload proven. **Do not cut the hold to 1 s** (LOAM-5 proposed it; rejected).

| # | Work | Hours | In v1? |
|---|---|---|---|
| 1 | `stream/scenes/hollow.py`: sim grid, cave layer, cave mouth with real sky + moon, glow buffer, drips, 4x upscale, graceful-degrade ladder, last-good-frame on error | 4 | yes |
| 2 | Pip sprite generator: 4 stencils × parts, tiers, frames, reject-and-reseed, cache, `pips_sheet.png` in self-test | 3 | yes |
| 3 | Pip behaviour: seed → hatch (nameless until hold), wander, face speaker, walk-to, hop, blink, curl, sleep/wake at 20 min, credits walk | 3 | yes |
| 4 | `world.json` persistence: schema, atomic writes, `.bak`, join with `builders.json`, recompute from `chat.jsonl` by `(session, owner)` with cursor, minutes-present accounting, tier logic | 3 | yes |
| 5 | Chat bridge: exact-token verb parser, `feed`, `pet`, `dig`, `plant`, `wave/sit/duck`, `forget`, rate limits with plank reasons, care log, filtered name path everywhere, three strikes, `!banish`, `!rename` | 4 | v1: feed, pet, dig, plant, forget, `!banish`; rest v1.1 |
| 6 | Text layer: plank (rotation, notices, first light, last five visitors), labels, bubbles, platform letters and counts, wall scrolls, moss labels, density fallback | 3 | yes (scrolls v1.1) |
| 7 | Rounds: new MENU (weather, colony_rule, feast, dig_site, music, light, chaos), embodied tally from platform positions, zero-vote copy, event effects in the world | 3 | yes (anarchy v1.1) |
| 8 | Colony panel, keeper strip, chat log panels; header rework (56 px awake count); `layout.py` `world`/`colony`/`keeper`/`chat_log` regions | 3 | yes |
| 9 | Audio: pad voices = awake count, drips, motifs, hatch/wake/sleep/tier stings, duet, footsteps, event stings, lantern rattle | 3 | yes (sing/chorus v1.1) |
| 10 | Keepers: lantern states, plain-language build line, failure lines, chamber carve on milestone, scroll classification, `docs/art-rules.md` | 2 | yes |
| 11 | Grafts: `gift`, nests + badges, homecoming, nightly board, storms, word spread with attribution, `teach` + allowlist, migration + camera pan | 5 | v2 |
| 12 | QA: self-test honesty assertions, 320x180 gate incl. 0-awake light check, 60-synthetic-pip budget run (test mode), moderation tests (blocked name, hidden-in-hold, strikes, impersonation), HLS probe, art-note review | 3 | yes |
| | **Full concept** | **39** | |
| | **v1 (a complete, alive show: rows 1-4, 6-10, 12 and the v1 parts of 5)** | **~26** | 2-3 parallel agents, one working day |

**v0 trial (optional, ~6 h, tonight, no restart).** `stream/panels/hollow_trial.py` registers a
panel with `key = "stage_body"` (same region, 840x236 → 210x59 sim at 4x) and hot-reloads into the
running hardened build: hatch, bubbles, wander, glow, sleep/wake with `world.json`, darkness as the
empty state, walk-to-platform voting drawn inside the stage body. Everything else on screen stays
the text show. The VOD then records the cave appearing inside the old stage and growing to take
over the screen, announced by the keepers, which is what the owner asked for in the 015 addendum.

**Deploy sequence** (journal 015 addendum, owner's stated preference):
1. Stop the snapshot show; start the hardened build (relay + hot-reload + Harden fixes) as a fresh
   stream (VOD 2). This is the one owed visible restart.
2. Optional v0 trial via hot-reload inside `stage_body`.
3. Full layout: the `world` regions live in `layout.py`, which is spine, so the swap is a compositor
   **child** restart under the relay (`scripts/deploy.sh`): ffmpeg keeps its pid and ingest, the
   relay holds the last frame for ≤ 2 s, then the cave is on air. The owner is told before it
   happens and may prefer a fresh stream (VOD 3) instead; either is allowed by the addendum, and the
   never-restart rule (journal 011) is respected because ingest never drops.
4. Everything after that (verbs, events, chambers, grafts) ships as keeper macro-ships via
   hot-reload, on air, which is the content the fiction promises.

**Cut list (first to go if time runs out):** `teach`/word spread → nests → migration → storms →
nightly board → `sing`/chorus → emotes → wall scrolls (ideas stay in the keeper strip as text) →
`gift` → moss labels on rotation (moss stays, unlabelled) → pad-voice scaling (pad on/off with awake
> 0). **Never cut:** the nameless-seed-until-hold rule, filtered names everywhere, the honesty
assertions, the 0-awake light check, graceful degrade, the compact chat log, `world.json` in the
isolated run dir with backups, absence-never-punished.

---

## 13. Risks

| Risk | What this spec does about it |
|---|---|
| **Dead nights still look dead.** Two humans have ever chatted; 0 awake is the default state. | Honesty forbids padding, so the cave is dark, but never dead: sky and moon in the mouth, moss, sleepers with real names, the last-five-visitors plank, the countdown, drips. The title says what one message does. The first milestone is one stranger away. Accept that a colony stream is exactly as alive as its real chatters, and the report will say the real numbers. |
| **Names are now the whole screen.** A slur username under a 48 px creature is worse than under a card. | Nameless seed until the 3 s hold and blocklist clear; `builder #N` fallback; the raw-name path deleted; `!hide`/`!banish` burrow the pip; three strikes; the chat log stays for VOD visibility. 014.1 is a go-live prerequisite. |
| **Novelty decay.** A cute reaction wears off in ten minutes. | Progression is the content: first-night tier-up, session tiers, moss, digs, nests, learned words, milestones that carve rock, a new event every 3 min and a keeper ship most sessions. If these slip from v1 the stream is boring again in a costume; rows 4, 7 and 10 are not cuttable. |
| **Frame budget with crowds.** Glow + upscale + labels unmeasured; the compositor's placeholder would blank the whole world. | Cached sprites and text, numpy slicing, `budget_ms 24`, the degrade ladder (glow → labels → bubbles) and last-good-frame on error; QA runs 60 synthetic pips in test mode only. |
| **Persistence loss.** One bad write erases everyone's creature; attachment makes every state bug a complaint. | `world.json` written by one module, atomically, in the isolated run dir, with daily `.bak`; identity fields immutable after hatch; counts recomputed from `chat.jsonl`, never incremented on boot. |
| **Griefing via verbs.** | Positive-only verbs, exact-token match, per-user and global limits with visible reasons, digging in own radius, one bubble per pip, `gift` only at sleepers, `!banish` for the owner. |
| **Label clutter above ~40 awake.** | Label-on-speak fallback, sleepers stop rotating labels, storms shorten bubbles; QA gate at 60. |
| **Guilt creep.** Any nurture loop can slide into Tamagotchi nagging, and a future keeper may "improve engagement" with hunger. | Energy is cosmetic, sleep is the only floor, no offline decay, no blaming copy, the rule is written in this spec and `docs/art-rules.md`, and violating ships are reverted. |
| **Entity-rule creep.** Someone will propose an owl, a dog, a keeper avatar. | The keepers are a lantern; v1 allows only objects and weather; every animate thing maps to a row in `pips` created by a real message, asserted every frame. |
| **IP adjacency.** The owner cited Plaything. | Invented names and lore; angular side-view sprites in the name colour, no yellow default, no round faces, no multiplication or morality; `docs/art-rules.md` and a sprite-sheet review before going live. |
| **Moderation lag vs instant feedback.** The hold delays text by 3 s. | The seed drops and the pip hops within one frame, so nobody thinks their message vanished; the crack animation is exactly the hold. |
| **Brand and category change.** Title, thumbnail and category all move; `docs/promo/` goes stale. | Version scheme continues (v0.5.0); promo pack is redone after the first world session with real frames; category A/B uses real `viewer_count` only. |
| **Deploy.** Layout is spine; the world cannot fully land by hot-reload alone. | v0 trial by hot-reload inside `stage_body`; full layout via a relay-held child restart or a fresh stream per the owner's addendum; never a bare compositor restart while live. |
| **Kick's tolerance of a no-human broadcast** is still unverified. | Unchanged from CONCEPT §9: the owner checks terms before a multi-hour run; the ticker says plainly what the show is; the owner's account stays reachable for mod commands. |
