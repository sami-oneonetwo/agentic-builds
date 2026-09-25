# World API — what the verbs / rounds / text-layer / panels / audio agents code against

Owner: the world core (`stream/scenes/hollow.py`, `stream/world/*`). Spec: `docs/WORLD.md` §3, §6, §11; art
rule: `docs/art-rules.md`. Python 3.9, pillow 11, numpy 2, stdlib. Nothing here reads `time.time()` in the frame
path: `ctx.now` only, so `--self-test` stays deterministic from a seed.

## 1. The flow, one frame

```
chat.jsonl  ──StateStore.drain_chat()──►  ChatBridge.ingest()  (hold 3 s, blocklist, hidden, builder #N)
                       │                           │
                 ctx.chat_raw (≤20, unmoderated)    ctx.chat (≤10, moderated, past the hold, display_name)
                       │                           │
   CaveScene.frame(ctx, size):                     │
     _ingest:  raw record, no pip  → Behaviour.seed_drop(key)        nameless seed drops THIS frame at sha1(name) x
               raw record, has pip → Behaviour.message(key)          hop + brighten this frame; a sleeper wakes
               moderated record    → WorldState.ensure_pip(...)      identity frozen once (name, n, colour_idx, genome+salt)
                                     Behaviour.hold_cleared(...)     egg finishes cracking ≥ 3 s after the seed → "hatch"
                                     Behaviour.speak(key, text)      bubble text for 6 s → "speak"; awake pips face it
               ctx.recent_votes    → Behaviour.walk_to(key, "A")     → "walk", then "arrive" on the platform
               ctx.round.number ↑  → Behaviour.release_votes()       → "leave_platform" for everyone standing
               ctx.mod.hidden_users→ burrow / sink                    a seed hidden inside the hold never hatches
               ctx.session.ending  → Behaviour.start_credits()       one by one to the burrows → "credits" (minutes tonight)
     _honesty_check                every entity is origin "chat" (or "test" under KL_TEST_PIPS in /tmp + test mode)
     Behaviour.tick(now, dt)  →  events (list of dicts)   →  scene.events
     _persist                  world.json (atomic, ≤ every 5 s), minutes_present, tiers, care-log playback on wake
     render 320x110  →  static cave (rock, floor, soil, burrows, platforms, Ledge, sky + moon)  →  drips, moss,
                        lantern  →  glow buffer  →  sprites  →  NEAREST ×4  →  RGBA `size`
```

The scene draws **no text**. Names, bubbles, platform letters and counts, the plank, moss labels, wall scrolls are the
text layer's job at screen scale (≥ 20 px), using `scene.entities()` and `scene.events`.

## 2. `CaveScene` (stream/scenes/hollow.py)

```python
from stream.scenes.hollow import CaveScene
scene = CaveScene(run_dir=None, seed=None, log=None, sleep_after_s=1200.0, hold_s=3.0, name_filter=None)
```
| member | type | meaning |
|---|---|---|
| `frame(ctx, size) -> PIL.Image` | RGBA, exactly `size` | never raises; last good frame (or a dark cave with the sky) on an internal error, one stderr line. The sim is upscaled by the largest integer that fits (4 for 1280x440) and centred; `scene.scale`, `scene.origin` say how. Call once per frame from the `world` panel's `render()` (put `ctx.frame` in that panel's `inputs()`). |
| `events` | `list[dict]` | events produced by THIS frame (see §5). Read after `frame()`; replaced next frame. |
| `entities(now=None) -> list[dict]` | | one per entity, see §4. Seeds have `display_name: None` and `key: None`. |
| `awake_count()`, `asleep_count()`, `hatched_ever()` | int | `len()` over real records. `awake` = state in (awake, walking, voting, curled). Test pips never count in `hatched_ever`. |
| `platform_counts() -> {"A": [keys], "B": [...], "C": [...]}` | | who is STANDING on each platform (state `voting`). Rounds: this is the embodied tally; keys are lowercase usernames, run them through `display_name` before drawing. |
| `command(verb, actor, target=None, arg=None, now=None) -> (ok, reason)` | | see §6 (verbs agent). |
| `sim_to_screen(x, y) -> (sx, sy)` | | sim px → region px. |
| `degrade -> {"glow": bool, "labels_on_speak": bool, "bubbles_single": bool, "level": int}` | | ladder state (§7); the text layer obeys the two flags, the readout shows `world: glow off` when `glow` is False. |
| `stats() -> dict` | | `frames, errors, last_ms, avg_ms, degrade, entities, awake, asleep, hatched_ever, honesty_violations, test_pips, sprite_cache, drips, moss` |
| `distinct_recent_chatters(ctx, now) -> int` | | honesty reference: distinct real chatters in the last 20 min of this session (self-test asserts `== awake real entities`). |
| `world` | `WorldState` | §3. Read freely; write only through its methods. |
| `behaviour` | `Behaviour` | §5. |

`ctx` fields the scene reads: `now`, `session{id, started_ts, ending}`, `micro{canvas_seed, weather, colony_rule}`,
`preset`, `chat_raw`, `chat`, `recent_votes`, `round{number}`, `mod{hidden_users}`, `mod_paused`, `agent{heartbeat_ts}`,
`macro{active}`, `compositor_live{selftest}`. Everything else is ignored. `run_dir` defaults to `$RUN_DIR`;
`world.json` lives there (the run-dir guard keeps test runs out of the live dirs).

Weather hooks the rounds agent may set in `state.micro` today: `weather` = `fog` (glow radius halves) or `lights-out`
(pip glow off, moss and sky only) or anything else (clear); `colony_rule` = `free | follow | scatter | huddle`.

## 3. `WorldState` (stream/world/state.py) — world.json

```python
ws = scene.world
ws.pips -> {name_lower: pip}          ws.pip(key) -> pip | None        ws.hatched_ever -> int (real pips only)
ws.ensure_pip(key, name, display_name, n, t) -> (pip, created)        # identity frozen on create; never recomputed
ws.record_message(key, t, session_id, text, history=False)            # own_messages, energy +0.15, words, session set
ws.presence(key, dt_s) ; ws.tier_for(pip) ; ws.update_tier(pip) -> new tier | None
ws.care(key, by, verb, t) ; ws.take_care_log(key) -> [{by, verb, ts}] ; ws.gift(key, frm, t) ; ws.bond(a, b) ; ws.forget(key)
ws.terrain() -> np.bool_ (110, 320) carved mask ; ws.set_terrain(mask) ; ws.dig(key, cx, cy, protected, cap=40) -> (cells, reason)
ws.moss -> [{x, y, planter, ts, size}] ; ws.plant_moss(key, x, y, t) ; ws.grow_moss(now)
ws.milestone_check() -> int | None ; ws.mark_milestone(m, by, t) ; ws.woke(key, t) ; ws.visit(key, t) ; ws.log_event(text, t)
ws.banish(key, t) ; ws.unbanish(key) ; ws.top_words(pip, n=8) -> [str]
ws.quarantine(key, t, reason) ; ws.quarantine_orphans(t, chat_names) -> [keys]   # world.json rows with no chat.jsonl chatter (fix 2026-09-25)
ws.dig_cells(cx, cy, protected) -> int ; ws.dig(key, cx, cy, protected, cap=40, radius=8)
ws.save(now, force=False) ; ws.backup(now) ; ws.recompute_from_chat(now, session_id) -> {records, new_pips, pairs, skipped}
ws.data -> the whole document (schema 1, WORLD.md §3.2 shape) ; ws.builders -> builders.json (read-only join for #N)
```
Pip record fields (WORLD.md §3.2): `name, display_name, n, colour_idx, genome{salt, body, eyes, antenna, tail, motif},
born_ts, sessions_seen, session_ids[], minutes_present, own_messages, nights_streak, last_seen_ts, first_seen_ts, tier,
energy, state, x, y, burrow, vote, words{}, learned[], bonds{}, nickname, care_log[], gifts_pending[], moss_planted,
digs, votes_cast, events_picked, raised_in_nest, strikes`. `world`: `terrain_b64, moss, nests, chambers, milestones,
milestones_reached, hatched_ever, woke_log, visits, board{session_id, fed, dug, hatched}, last_board, event_log`.
`sessions`: every session id this module has seen with `started_ts`/`last_ts`. `cursor`: chat.jsonl byte offset + last id.
`quarantine`: `{key: {record, reason, ts}}`, pip rows whose name has no chatter in chat.jsonl (moved there by
`recompute_from_chat` at boot or by the HonestyMonitor after a 5 s grace); never placed, counted or drawn; restored by
`ensure_pip` when a real record for that name arrives. `hatched_ever` = real rows whose `state` is not seed/hatching.

Writes are atomic (`tmp + os.replace`), flushed at most every 5 s and on `force`; `world.json.bak-YYYYMMDD` once per
session start, 7 kept. A missing or corrupt `world.json` loads defaults (then the newest `.bak`). Counts come from
`chat.jsonl` by distinct `(session, owner)`: the second `recompute_from_chat` on the same file adds nothing.
**The words a pip may mutter (`top_words`) still have to pass the dictionary allowlist and the blocklist in the text
layer** (WORLD.md §11.3); this module only removes stop-words and other chatters' usernames.

## 4. `scene.entities()` item

```python
{"key": "sami", "origin": "chat", "state": "walking", "display_name": "Sami", "tier": 1, "energy": 0.62, "salt": 0,
 "x": 212.4, "y": 88.0,                  # sim px, y = feet row (88 floor, 85 on a platform, ~103 in a burrow)
 "sx": 828, "sy": 308, "sw": 48, "sh": 44,   # screen box of the sprite inside the world region (label goes above sy)
 "facing": 1, "frame": "walk1", "platform": None, "burrow": None,
 "text": "hello cave", "speaking": True, "learned_from": None,     # bubble text ONLY while speaking (6 s), else None
 "first_ever": True, "minutes_tonight": 3.2, "awake": True, "colour": "#C4B5FD"}
```
States: `seed hatching awake walking voting curled asleep burrowed`. For `seed`/`hatching` the dict has
`display_name: None` and `key: None`: **nothing about a seed may be drawn as a name.** `burrowed` = hidden by a mod
(draw no label). `display_name` is already the filtered name (`builder #N` on a blocklist hit); if `ctx.chat_display`
is False the text layer draws no names at all (WORLD.md §4 `!kill`).

## 5. Events (`scene.events`, one list per frame)

| type | fields | who consumes |
|---|---|---|
| `seed` | `key, x` | audio (soft thud on `seed_land`), nobody draws a name |
| `seed_land` | `key, x` | audio |
| `sink` | `key` | text layer plank `the soil did not take that one` |
| `hatch` | `pip, display_name, first_ever, x, only_light` | audio (new-builder rise + motif), text layer (`#N` shell tag 3 s, `you are the only light in the cave` when `only_light`), colony bar |
| `first_light` | `pip` | audio (first pad voice), plank `@name woke the Hollow · HH:MM` |
| `speak` | `pip, text, learned_from` | audio (motif per word chunk ≤ 6), text layer bubble |
| `hop` | `pip` | audio (tick) |
| `walk` | `pip, to` (`"A"/"B"/"C"`, `"burrow"`, or an int x), `reason?` | audio footsteps |
| `arrive` | `pip, at` | rounds (platform tally changed), audio vote blip |
| `leave_platform` | `pip, platform` | rounds |
| `wake` | `pip, burrow, care_log[], away_s` | text layer care-log bubble (`back after N nights · fed by @kai x2`), audio rising third |
| `sleep` | `pip, burrow, quiet_s` | text layer `asleep · quiet 20 min`, audio descending third |
| `curl` / `uncurl` | `pip` | cosmetic |
| `blink` | `pip` | nothing (kept for completeness) |
| `tier_up` | `pip, tier` | audio rising third + sweep, ticker |
| `emote` | `pip, kind` | audio |
| `feed` / `pet` / `gift` | `pip, by, asleep` | audio pop / duet, text layer hearts |
| `dig` | `pip, cells` | audio thud |
| `plant` | `pip, x, y` | audio thud + sparkle |
| `forget`, `banish`, `burrowed` | `pip`, `reason?` | plank |
| `credits_start` / `credits` / `credits_end` | `count` / `pip, minutes_tonight` | text layer credits line |
| `drip_land` | `x` | audio drip plink |
| `world_error` | `count` | readout |

## 6. Commands (verbs agent → world)

```python
ok, reason = scene.command("feed", actor="atleastonce", target="sami", now=ctx.now)
```
Verbs the world implements: `feed [target]`, `pet [target]`, `gift target` (only at a sleeping/absent pip),
`dig`, `plant`, `wave|sit|duck`, `hop`, `vote` (`arg="A"`), `walk` (`arg=x`), `forget`, `credits`, `banish target`.
`reason` is plank-ready plain words on refusal (`your pip is not awake yet`, `no pip called @x here`,
`gifts are for sleeping pips`, `dig cap reached tonight`, `too far from your pip`, `nothing to dig there`).
**Rate limits, cooldown copy, exact-token parsing, the text blocklist and three-strikes stay in the verbs agent**
(WORLD.md §4, §11); the world only refuses what it cannot do. Feed/pet on a sleeper go to the target's `care_log`
and are played back by the `wake` event.

## 7. Budget and degrade (measured 2026-09-25, this Mac, 1280x440)

| pips | avg ms | p95 ms | max ms (steady) |
|---|---|---|---|
| 12 | 1.4 | 1.6 | 2.5 |
| 20 | 1.5 | 1.6 | 2.6 |
| 60 | 2.7 | 2.8 | 3.7 |

Frame 0 is 5-15 ms (sprite cache + fonts). Ladder on the scene's own render ms averaged over 30 frames: > 16 ms →
`glow` off; > 20 ms → `labels_on_speak`; > 24 ms → `bubbles_single`; one step back every 300 clean frames. The world
panel should set `budget_ms = 24`.

## 8. Test hooks

- `KL_TEST_PIPS=N`: N synthetic pips (origin `test`, names `test-pip-NN`, display `test pip N`), honoured only when
  `run_dir` is under `/tmp` AND (`ctx.compositor_live["selftest"]` or `MODE=test`). Refused everywhere else
  (`stream.world.test_pips_allowed()`); never written to `world.json`, never counted in `hatched_ever`.
- `CaveScene(sleep_after_s=60)` shortens the 20 min sleep window for a harness; `hold_s` likewise (never on air).
- Standalone harness used for the numbers above: `/tmp/pip-core/harness.py` (`RUN_DIR=/tmp/pip-core $PYTHON harness.py all`).
- `$PYTHON stream/world/pips.py --check --sheet /tmp/x/pips_sheet.png` writes the art-review sheet.

## 9. Hot reload note

`stream/scenes/hollow.py`, `stream/panels/*.py` AND `stream/world/*.py` are watched by the compositor's HotReloader
(integration 2026-09-25). A changed world module is executed fresh under its name, the `stream.world` package attribute is
rebound, then `stream.scenes.hollow` is re-executed and every panel module that mentions `stream.scenes` (the world panel)
re-executes too, so `from stream.world import pips as P` and `from stream.scenes import hollow as H` see the new objects.
A re-executed scene module creates a fresh `CaveScene` in the world panel (`stream.panels._WORLD_SCENE` is replaced when
the class object changed): the world re-boots from `world.json`, sleepers in their burrows, and an owner who chatted inside
the awake window resumes at the saved x / platform with the sleep timer counting from their real last message
(`CaveScene._restore_awake`, no wake event). A panel-only reload keeps the scene instance and the colony.
