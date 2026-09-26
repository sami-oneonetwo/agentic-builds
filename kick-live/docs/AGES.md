# AGES — nobody sleeps, the settlement climbs through ages (spec, 2026-09-26, synthesis)

Owner direction (terminal, 19:25, binding; journal 034): *"Remove the bottom part of the screen where chat is and
just have the main thing. Let's make the world progress through the ages. Nobody falls asleep, everybody continues
to walk around."* Standing rules: no fake viewers / chat / names; no NPCs or animals that pretend to be people;
chat is data; no explainer / AI / disclaimer copy on screen; text >= 20 px; the world is the show.

This is the synthesis of three design lenses (systems designer, the 11 pm stranger, honesty auditor) and three
judges. Spine: the systems designer's ladder and here/away model. Grafted: the stranger's errand table, variety
rules, ROAM camera, monument plate and sprite-memory regime; the auditor's honesty mechanics, one-record-per-stack
rule, chat-day clock and exact first-slice edit list. Conflicts are resolved in §0.2. Design only; nothing here is
implemented, and implementation starts the moment the full-bleed build is on air (journal 034: never two agents in
`steading.py` / `behaviour.py` / `honesty.py` at once).

## 0. Ground truth and decisions

### 0.1 Read from the tree and the live run dir tonight (not from any brief)

- `~/.local/share/kick-live/run-live/world.json`, schema 2: **3 pips** (atleastonce: state asleep, gear tier 2,
  sessions_seen 4, 335.9 min present; Sami: walking, tier 2, 2 sessions, 124.5 min; Lordoomer: asleep, tier 1,
  1 session, 20.2 min). **3 camps** at tiers 1 / 1 / 0 (521,231 · 547,295 · 590,284), `camp.nights[]` carrying
  `hist-` ids plus ONE live session id. **16 stones** on cairn `moot` (Sami 9, atleastonce 5, Lordoomer 2), so the
  cairn is NAMED (`CAIRN_NAME_AT 3`; milestone 3 by Lordoomer at 2026-09-26T07:24:41Z). 3 flower marks, 0 fields,
  `raisings []`, `hatched_ever 3`, `bake_ver 3`, banished / quarantine empty. Top-level `sessions` holds **one id**
  (`2026-09-24T11:22:08Z`, last_ts 09-26 09:50) because the pipeline never restarted: **sessions are not a clock**.
- `chat.jsonl`: 105 records on **3 distinct calendar dates** (09-24: 24, 09-25: 15, 09-26: 66, UTC; the Mac is AEST;
  the local-date count is computed at run time, never copied from here).
- Funnel (run/reports/2026-09-26.md): 178 arrivals, 56 messages, 1 first-time chatter today (external), 3 chatters
  ever, 66.7 % second message within 10 min, mean 1.63 viewers, hour peaks up to 5, ~8 h 43 m live sampled.
  Growth research (docs/research/kick-growth-2026-09-26.md): Software Development is a ~30-viewer pond; the target
  is mean viewers 1.5 -> 3-5 over a week; realistic new-chatter rate 1 per 1-2 days until the first minute is fixed.
- Code: `behaviour.STATES = seed hatching awake walking voting curled asleep burrowed`; `_tick_awake` fires
  `_go_home(reason="quiet")` after `sleep_after_s` (20 min); `Entity.is_present()` already exists (awake and not
  walking home); `_pick_wander` has the huddle / scatter / follow branches; `_wear` runs for every mover.
  `honesty.RULES = origin record chat_jsonl hold name counts text presence scene wear marks`, `SLEEP_STATES =
  (asleep, burrowed)`. `state.tier_for` uses sessions OR minutes (10 / 120 / 600) for gear; `land.CAMP_LADDER
  (1, 2, 5, 10)` over sessions for camps; `land.stack` appends ONE record; `chat_bridge` cooldown `stack 45 s`,
  `_stack_used` cap 3 per session. `rounds.RoundEngine.stones_double` is referenced **only inside rounds.py**
  (its own self-test): the `raising day: stones x2` title is a dead flag, nothing ever stacked twice. `STONE_LADDER
  (20, 60, 150)` / `RAISING_NAMES (the Ford bridge, the well, the hall)` gate keeper raisings; `keepers.RAISE_S 20`,
  `reveal_rows` at <= 1 Hz, `RAISING_SITES` for the three names. `camera.MODES = EVENT MOOT FOLLOW CLOSE DRIFT`,
  `PAN_CAP 60 cells/s`, DRIFT dwells the Moot 30 s at 1.5x for Kick's snapshot tile. `props.cairn(n)` draws
  1..5 stones only. Building kit: hut tiers 0 tent / 1 hut / 2 chimney / 3 hall (2 tiles), well, garden, fence_h/v,
  banner, lantern, smoke; no bridge, no monument sprite. `steading.py` gates are rebased for 1280x720: C2 (60 pips,
  0.75x) < 19 ms, C1 / C3 < 14, C4 < 12; the full-bleed build's own run reported C2 scene avg 11.41 ms, p95 12.08,
  max 15.02 (contended by the sheet worker: avg 13.24, p95 20.79, max 26.0) — re-measure at row 1, do not quote
  journal 030's 10.90 ms (456 px world).
- **Tonight's Mac has no free disk** (`ENOSPC` writing to /private/tmp at 19:50). Every `/tmp` copy step below
  needs space first; this is a deploy blocker to clear before row 1.

### 0.2 Conflicts between the proposals and how they are resolved

| question | resolution | why |
|---|---|---|
| stones x2 on a hauling day (P1, P2) vs one record per act (P3) | **one record per act.** `hauling day` relieves the stack cooldown 45 s -> 20 s and the session cap 3 -> 6 for the round; `stones_double` and the `x2` title are deleted | every number is a `len()`; the cairn never shows two stones for one act; nothing is lost because the flag was never read |
| DAYS from render time >= 30 min (P1) vs distinct chat dates in chat.jsonl (P2, P3) | **chat dates**, computed in `recompute_from_chat` with the existing cursor | a lid-open night with nobody typing must not advance a key; no new live-time plumbing |
| idle wear at 4 (P2) vs none (P1, P3) | **none.** Only `here` settlers wear the grass | desire paths stay a record of where real people sent themselves; the honesty wear rule stays 8 x here steps + spill |
| away bodies wave / follow the newest speaker (P2, P3 partly) vs never (P1) | **never.** Away motion is walk, stand, sit, look, carry-for-a-build. Looks and turning to face are allowed (body language, no social claim); waves, hops, hearts only from `here` settlers | a wave or a tail on an arriving stranger reads as attention the person did not give |
| camp created at hatch (P1) vs on the first home errand (P2) | **at hatch** | a hatch is a real act; an errand may never write a record |
| camps CAPPED by the age (P2, P3) vs FLOORED (P1) | **floor + a soft ceiling of age + 1.** At the Camp every camp is at least a tent; at the Village at least a hut; a personal tier may run one rung ahead of the age but no further | the owner's earned hut is never held hostage to stranger count at a 1-5 viewer channel, yet a hall never stands in a clearing |
| people legs 6 / 12 (P3) vs 5 / 10 (P1) | **5 / 10 / 25** | one new chatter per 1-2 days makes the Steading a first-week rung, the Village a week-two rung |
| stone legs 20 / 60 / 150 (STONE_LADDER, judge 1) vs 10 / 30 / 80 / 200 (P1) | **10 / 30 / 80 / 200** | 20 is met the first evening (16 today), which would make people the only gate; 30 = 14 more stones = two sessions of three stackers or one hauling day, so the three keys land together around day 3; STONE_LADDER retires as a raising gate |
| six keys incl. rounds voted, marks, raisings (P2) vs three (P1, P3) | **three: people, stones, days** | rounds close 175/day with nobody voting; marks are a 3-per-session spam lever; a raising needs a keeper on duty and an age must never wait on the agents |
| camera at 0 here: DRIFT (P1, P3) vs ROAM (P2) | **ROAM**, interleaved with the Moot dwell every third hold | the stranger's ten minutes need a camera that follows life; the snapshot tile still needs the sign and the monument |
| a duplicate pile beside a full cairn during a build (P2) vs the cairn shrinking (P3) | **every stone is drawn exactly once**: 5 on the cairn art, the rest as a loose pile beside it, and each age build carries some of the pile into the age's structures | `props.cairn` caps at 5, so 11 records are invisible today; the pile shows them and the build moves them, records untouched |
| `work hour` card (P2) | dropped | hauling day covers it; fewer cards |
| `light` / `music` cards (P2 retire) | kept behind the stranger gate for v1 | minimal change; revisit when age banners own the waystone look |
| tally notches on the cairn (P1) | dropped | unreadable at 320x180 |

Vocabulary on screen: **the Clearing, the Camp, the Steading, the Village, the Town, a Century.** Plain words, no
franchise terms, no `age N`, no explainer copy (owner, journal 032).

---

## 1. No sleep

### 1.1 Two axes replace `asleep` / `awake`

**Presence (about the person; derived, never stored, never drawn as a count).**

| flag | definition | gates |
|---|---|---|
| `here` | the person's moderated record landed within `PRESENT_S = 1200 s` of now in THIS session (`t - e.last_active_t <= present_s`; the raw record flips it, exactly the old awake window) | every verb (`go plant camp fire stack sow harvest feed pet gift swim wave sit dance name`), bubbles, mutters, hops, standing at a waystone / votes, marks, stones, fire and embers, lit window, care given, camp moves, `minutes_present` accrual, wear, camera FOLLOW weight, the arrival stone on an expedition |
| `away` | everything else, from first hatch onward, forever minus `!banish` | nothing a person could claim. The body moves (§1.3) but never speaks, votes, plants, stacks, lights, gives, wears a trail or carries anything that counts |

Transitions: `here -> away` is instant at 20 min: no walk home, no lie-down; the settler finishes its leg and picks
its next errand. `away -> here` is the old wake, renamed `return`: drop the errand in one frame, hop, brighten, face
the camera; care log played back; fire relights only if within 12 cells of camp; one bell, three bells + everyone
looks after 7+ days away. In code `Entity.is_present()` keeps its name and becomes the `here` test (the
`then in ("sleep", "credits")` carve-out goes); `is_awake()` becomes `is_on_land()` (state in `ON_LAND`) for
sprites, camera dead-zone points and layout. `Behaviour.present() / present_count()` replace `awake() /
awake_count()`; `awake_count` stays one release as an alias; `asleep_count()` returns 0 and is deleted once
rounds.py / compositor.py / chat_bridge.py / panels stop calling it. **"N AWAKE" becomes nothing on screen** (the
full-bleed build owns the sign; the compositor copy check already bans the word).

**Activity (`behaviour.STATES`).**

```
STATES  = ("seed", "hatching", "idle", "walking", "voting", "sitting", "hauling", "hidden")
ON_LAND = ("idle", "walking", "voting", "sitting", "hauling")

seed -> hatching -> idle                       (unchanged: hold + sheet grace)
idle  -pick errand-> walking -arrive-> idle | sitting     -dwell 8-90 s-> idle
idle | sitting  -own message-> hop, then the unchanged verb machine (walking then=go/vote/..., voting)
here + A/B/C  -> walking(then=vote) -> voting -> idle       (voting requires here)
age build     -> walking(then=gather) -> hauling <-> walking -> idle
mod !hide / 3 strikes -> hidden (lies in grass, no label, no plate: the ONE lying pose, moderation not presence)
```

Retired: `asleep`, `curled` (energy stays as the glow strength only), `burrowed` (renamed `hidden`),
`then in ("sleep",)`, `_go_home(reason="quiet")`, `_fall_asleep`'s sleep path, `_tick_sleeper`, `stir`,
`SLEEP_FRAMES`, `SPRITE_PRIO_SLEEP`, `TWITCH_*`, `sleep_t`, `nights_streak`, the `asleep · quiet N min` label, the
`your pip is not awake yet` refusal (seed / hatching keep `your settler is still arriving`), every sleep / night /
wake word on any surface. Kept: every walk / route / string-pull / stuck rule, waystone slots, carry, emote, look,
blink, mutter (here only), hop (here only). `credits` (stop.sh --credits) = everyone walks home and STANDS at the
door with name + minutes. "Looking" and "tending" are dwell flavours of `idle` (a facing, optionally `carry_tool`),
not states. `walking.then` gains `errand:<name>` so honesty can tell an errand from a verb.

### 1.2 Camps remain homes

A camp is created **at hatch** at the hashed Steading-ring spot (a stranger owns a plot in minute one; `camp` moves
it under the unchanged 5.3 rules). `camp.nights[]` -> `camp.sessions[]` (same values, history). The personal ladder
clock is `pip.days_seen[]` = distinct LOCAL calendar dates with a moderated record (`recompute_from_chat` appends the
date of every record) OR `minutes_present`, whichever is further:

| camp tier | look | by days_seen | or by minutes present | floor from the age | plate |
|---|---|---|---|---|---|
| 0 hollow | bedroll on pressed grass | 1 | 0 | the Clearing | `@name's camp · 1 day here` |
| 1 tent | tent in the owner's colour, bell | 2 | 30 | the Camp | `@name's tent · 2 days here` |
| 2 hut | 1-tile hut, roof in the owner's colour | 4 | 180 | the Village | `@name's hut · 4 days here · last here yesterday 10:40` |
| 3 hut with a chimney | + chimney (smokes while here), lit window, garden bed | 8 | 600 | the Town | as above |

`shown = max(stored, clamp(max(tier_by_days, tier_by_minutes), floor(age), age + 1))`: never lower, floor rises
with the age, a person may be one rung ahead of the place. `record_night` -> `record_visit`, called at hatch and on
the first `here` of each local day (never on a lie-down). Fires: the campfire burns while `here`, embers `EMBERS_S`
(20 min) after, cold otherwise; the window is lit while here or chatted since session start (`_slept_tonight` ->
`_here_tonight`, same test); lantern posts (Village) burn only while at least one person is here. At night the
settler stands or sits at a dark tent; **nobody ever lies down.**

### 1.3 The idle life: "the land moves them"

`_pick_idle` replaces `_pick_wander`. It runs once per arrival / dwell end (never per frame), for `here` and `away`
settlers alike (a `here` settler between messages is also moved by the land). Personality from the name hash: a
`haunt` (one of: own camp, Moot edge, Ford bank, Wood edge, Orchard), a `tempo` 0.75-1.3 scaling pause length and
`speed_max`, and a +/-30 % shift on every weight, so twenty idlers desync for free. Errand speed 4-6 cells/s
(slower than `go` 8 and the old wander 5-10). Dwells uniform in range.

| errand | walk to | do (dwell) | weight day / night | rain |
|---|---|---|---|---|
| home | own camp door | stand facing out, or sit by the fire side if a ring exists; 30-90 s | 25 / 55 | x2 |
| moot | a free cell on the Moot ring 10-24 cells out (never the green centre or a stand slot) | look at the monument / board / beacon in turn, facing flips every 6-10 s; 10-30 s | 20 / 10 | |
| water | nearest bank cell within 160 cells | face the water, 50 % sit; 15-40 s | 15 / 5 | x0.3 |
| visit | another camp's door (bonded first, else nearest; never the same twice running) | stand 10-20 s facing the door; if the resident is there both face each other 3 s | 15 / 10 | |
| tend | own field / own tree or flower | `carry_tool` en route when a field exists; face it 10-20 s; no growth change | 10 when owned | |
| stroll | the existing hop +/-8-40 cells, 30 % Moot gravity, 200-cell cap | pause 1-3 s, 20 % face the wind | 15 / 15 | |
| haul | pile -> build site, `carry_stone` | one stone per trip | 100 during an age build, else 0 | |

Variety rules: never the same errand twice in a row per settler; cap 30 % of away settlers on the Moot ring at
once; cap 2 visitors per door; max 4 sitting at one fire; at most 2 route plans (cell BFS) started per frame across
all settlers; sitting from an errand is sticky 20-90 s and is interrupted at once by the person's own message (hop
+ stand) or a round event. Reactions: look toward a speaker or a hatch within 50 cells (exists); a pair passing
within 6 cells both face each other 1 s; passing a build site look 2 s. Reactions are evaluated every 6th frame
over 16-cell spatial buckets (<= 8 neighbours each), never an O(n^2) scan per frame. **What idle motion may not do
(asserted every frame, §4):** lay wear, stand at a waystone, speak or mutter, hop, wave, stack or place a stone
record, plant, sow, camp, light a fire, ring its own bell, target the newest speaker. Two announced world events
move away bodies, like rain: the `gathering` card and an age build; neither writes a record.

### 1.4 Camera

FOLLOW weights 3 / 2 / 1 apply to `here` settlers only; away settlers weigh 0 for the target but count as life in
view. **New mode `ROAM`** between FOLLOW and DRIFT: when `here == 0` and any settler is on the land, follow the
settler with the most watchable errand (haul > visit > water > moot > tend > home > stroll) for 40-90 s or until the
errand ends, then ease to the next at <= `PAN_CAP` 60 cells/s (never a cut), never the same settler twice running;
every third hold is the existing Moot dwell (30 s at 1.5x, sign + monument + beacon in the 320x180 tile) so Kick's
snapshot keeps its character; the plank stays BLANK; no label or plate pins that implies the person is watching
(the camp plate rotation and the monument plate are records and may pin). EVENT and MOOT outrank ROAM; DRIFT only
for an empty land. The return beat: on `return` the camera glides to the settler wherever its errand took it, it
hops, one plank line from records (`@kai is back · your tent is a hut · the Camp rose`), the monument plate pins.

### 1.5 Copy, verbs, panels

`!stats` -> `@name · hut · 3 days here · 5 stones · 41 min here · the Camp`. Camp plate word `night N` -> `N days
here`. `gift @name` is allowed when the target is away: it waits at their camp and is opened on `return` (their
settler walks home to it). `feed` / `pet` on an away settler: the doer walks to them, hearts on the doer only, the
recipient looks; care log plays back on `return`; plank `left a berry at @x's camp`. `go home` walks to the camp
and stands at the door. `sit` (emote) becomes sticky until the person's next message or a round event. Pad voices =
here count; footsteps for any walker in view (real settlers moving). Above 24 settlers in view, away settlers lose
their floating label (here settlers, speakers, plates and bubbles keep theirs) so the text layer stays under budget.

---

## 2. Ages

### 2.1 Drive metric: three keys, all required, each a `len()`

| key | definition | source |
|---|---|---|
| PEOPLE | distinct real chatters ever minus banished | `hatched_ever` (exists) |
| STONES | `len(world.stones)` | exists; one record per real `stack` |
| DAYS | distinct LOCAL calendar dates with >= 1 moderated record in `chat.jsonl` | `world.days_on_air[]`, recomputed at boot by `recompute_from_chat` with the existing cursor |

Rejected as keys: rounds completed (175/day close with nobody voting), rounds voted (one person standing alone pads
it), marks planted (3 per session, a spam lever; marks stay personal), raisings shipped (need a keeper on duty; an
age must never wait on the agents), viewer_count (Kick's number, not ours), minutes present (336 owner minutes),
sessions (one id spans three days). AND of three: one regular grinding stones cannot age the land (people), one busy
night cannot skip the labour (stones), nothing ages while nobody comes (days). Nothing is spent: stones are a count,
never an economy.

### 2.2 The ladder

| idx | name | people / stones / days | status tonight (3 / 16 / 3) | expected at today's rates |
|---|---|---|---|---|
| 0 | the Clearing | 1 / 0 / 1 | passed 09-24 | |
| 1 | the Camp | 3 / 10 / 2 | **earned** (the migration plays this build on air the minute it ships) | deploy day |
| 2 | the Steading | 5 / 30 / 5 | 2 more people, 14 more stones, 2 more days | day 3-5 after deploy (1 new chatter per 1-2 days; 3 stackers at cap 3 give 9 stones a session, one hauling day 18) |
| 3 | the Village | 10 / 80 / 10 | | day 8-14 at 1-2 new chatters/day; 50 more stones at 7-9/day land in the same window |
| 4 | the Town | 25 / 200 / 25 | | month two; needs the channel to grow (the growth gauge) |
| 5+ | a Century | +25 / +200 / +25 each | | the monument gains a ring; no new art |

Justification against the funnel: 150-200 arrivals/day at ~0.6 % first-message conversion gives 1-3 first-timers
a day once the first minute is fixed (research items 1, 4, 6), 0.5-1 before; 3-5 stackers at 3 per session give
9-15 stones a day; ~9 h live a day gives one DAY per calendar day. Early rungs are small so the place visibly
changes in week one; each rung is 2-3x the last so waiting reads as accumulation (the pile grows). Days-on-air is
the raid brake: a hundred people in one night cannot pass the Village. If stones lag, hauling day and expedition
arrival stones catch up and the monument names the gap. `AGE_LADDER = ((1,0,1), (3,10,2), (5,30,5), (10,80,10),
(25,200,25))`, `AGE_NAMES = ("the Clearing", "the Camp", "the Steading", "the Village", "the Town")`; beyond the
table `(25 + 25 k, 200 + 200 k, 25 + 25 k)` named `the Nth Century`. `STONE_LADDER` / `RAISING_NAMES` leave the
raising gate: the three planned structures become contents of ages; `keepers.raisings` stay for `!idea` builds.

### 2.3 What rises per age (composed from the existing kit unless marked ART)

- **0 the Clearing:** today's look. Pressed grass, bedrolls, three bare waystones, the beacon, the board, the cairn.
- **1 the Camp:** camp floor tent (every camp >= tier 1); the hearth ring (8 `props.stone` round the Moot hearth,
  decoration, never described as stacked stones); the **stone pile** beside the cairn drawing `len(stones) - 5 -
  placed` loose stones (today 11); the monument plate on the cairn `the Camp · since 26 Sep · 3 have walked here`.
- **2 the Steading:** the well (kit) at `RAISING_SITES["the well"]`; colour marks on the waystone caps in the top
  three stackers' hues; fence rows (`fence_h/v`) on the field side of the Steading ring and round each sown field
  (age-built, never a verb: the art-rules revert clause gains exactly this exception); `path1` worn dirt baked on
  the Moot's two busiest spokes (real wear picks them); denser meadow flower drifts round the Steading; the cairn
  gains a base ring of pile stones; second plaque row.
- **3 the Village:** camp floor hut; the longhouse (kit hut tier 3, 2 tiles) for anyone at 8 days / 600 min;
  cobbled plaza (`path2`) inside the green rim; banners on the waystones; two lantern posts on the main spoke lit
  only while someone is here; the Ford bridge (ART, 1.5 h) opening the far bank; third plaque row.
- **4 the Town:** the hall by the Moot (kit tier 3 at `RAISING_SITES["the hall"]`) with a bell at sunrise and
  sunset; a stone monument replacing the cairn top (ART) with one plaque per age; the Coast strip (existing 25-head
  land-strip milestone aligns); stone bases under huts.
- **5+:** one ring on the monument per Century; Birch Wood / Tarn strips at 25 / 50 people (existing ladder).

Settler gear tiers stay personal (ART.md: sessions or minutes): an age changes the land and the buildings, never a
person's body. The land palette never changes with the age (seasons are real); age variants are ground-bake tiles
(flowers, dirt, cobble) keyed on `bake_ver`.

### 2.4 Shown in the world, never as HUD copy

The buildings are the display. The **monument plate** joins the ONE-plate rotation (`panels/world.py`) in two
forms, each a `len()` over records: reached `the Camp · since 26 Sep · 3 have walked here · raised by @sami
@atleastonce @lordoomer` and forward `the Steading · 2 more people · 14 more stones · 2 more days` (only the keys
still short, most binding first). It pins 10 s after every hatch and every stone, and during the camera's Moot
dwell (ROAM and DRIFT). `N have walked here`, never `N here`. The plank's single line fires only at the turn
(`Longgrass is a Steading · 5 people · 31 stones · 5 days`) or, after a round closes and only when a key moved, the
gap line (`1 more person and 4 stones until the Steading`); person acks outrank it. The daily title PATCH may carry
the age word as a real record. No bar, no `age N`, no explainer.

### 2.5 The transition on air (~90 s, the settlers build it themselves)

Gate: `Land.age_check()` compares the three ints once per round close; it never starts inside a ship hold, the
last 30 s of a round, or while a keeper raising is in flight. A met gate writes `world.age += 1` and appends
`age_history` with a **forced save in the same frame**; the visible build runs off `age_built < age`, so a reboot
mid-build resumes and finishes rather than re-earns, and two ages earned at once play back to back. No keeper is
required (nothing is being coded); the beacon flares only if one is on duty; `ships.jsonl` gets the version bump at
the next heartbeat.

1. **Call, 0-5 s:** bells west to east once; every settler turns to the Moot; camera EVENT on the Moot easing to
   0.75x; plank `Longgrass is a Camp · 3 people · 16 stones · 3 days`; survey stakes at each site.
2. **Gathering, 5-20 s:** every settler, here or away, walks to the Moot ring (an announced world event, like rain).
   A here settler that types leaves at once for its verb and rejoins after.
3. **Build, 20-80 s:** `hauls = min(24, pile)` REAL stones: settlers in `hauling` carry `carry_stone` from the pile
   to the sites at 6 cells/s and walk back; here settlers first, hop on pick-up; the pile shrinks by exactly the
   count moved and `age_history[-1].stones_placed` records it; `delivered / needed` drives `Keepers.reveal_rows` on
   each site's finished sprite bottom-up at <= 1 Hz, scaffold rows first; ground tiles repaint region by region in
   the bake thread; pacing holds the reveal at 60-75 s whether one settler hauls or twenty (one alone is honest and
   watchable; twenty are paced); a soft hammer tick every 2 s.
4. **Plaque, 80-90 s:** sprites complete, the monument plate flips with the raising chime + rumble, everyone `joy`
   1 s, camp floor upgrades cascade one per 2-3 s (12-frame raise each), `age_built = age` saved, `bake_ver` bump,
   the plate pins 20 s, errands resume.

Plays even with nobody here (the numbers are real). A failed step logs one stderr line and draws the object
finished next frame. **Never regress:** `age` is monotonic across frames and reboots; `!banish` dropping a count
below a rung changes nothing (the history row keeps the counts at reach, the plate reads `since 26 Sep`); honesty
asserts `age <= age_gate(people, stones, days)` and `age_built <= age` every frame.

---

## 3. Round menu and verbs

| card | v1 | change |
|---|---|---|
| weather rain / wind / fog / clear | keep | rain doubles the home errand weight |
| expedition to the Ford / Fell / Shore / Wood | keep | every settler walks (the land moves them); the arrival stone credits only walkers whose person is here; text `expedition to the Ford: 3 walked` from `len(here sent)` |
| bonfire on the Moot | keep | hearth lit only by a real picker; everyone gathers and sways (cosmetic) |
| harvest day | keep | drawn only when >= 1 field is gold |
| raising day: stones x2 | **hauling day: stones for the Steading** | timed; stack cooldown 45 -> 20 s, session cap 3 -> 6 for the round; ONE record per act; `stones_double` deleted; the Fell's stone props glint while it runs; title names the next age from the ladder |
| colony_rule follow / scatter / huddle / free | **gathering at the Moot** | instant: every settler walks to the Moot ring and stands or sits round the hearth for the round window, then errands resume; the one collective card; `follow` and `scatter` retired (an away body trailing a voice reads as fake attention; twenty scattering bodies is noise); `free` is the baseline, not a card; `behaviour.colony_rule` deleted, rounds call `scene.command("gather")` |
| music tempo / pattern, light | keep behind `STRANGER_MIN_CHATTERS` | unchanged |
| chaos | keep | |
| anarchy | undrawn | |

Verbs: `stack` unchanged (a here person's own act, the age's labour verb, plank `stone 17 · 13 more until the
Steading`); `camp` unchanged but the first camp exists from hatch; `fire` unchanged; `gift`, `feed`, `pet`, `sit`,
`home`, `!stats` as §1.5; `sing / explore / water` v1.1 unchanged. No `build` verb, no resource, no `age` verb.
`!idea` unchanged; a keeper build that reintroduces sleep, an NPC hauler, decay, or a stone that is not a stack
record is reverted under the existing art-rules list. Chat stays data: no verb, round or `!idea` creates a settler,
moves the agent, or writes outside the world sandbox.

---

## 4. Honesty

### 4.1 Rule text for OPENWORLD.md §12 (replaces the first, "Every animate thing", "Every mark", "Camps, plates,
plaques" and "Every number" bullets; the rest of §12 is unchanged, with "sleepers" read as "away settlers")

> **The rule:** *Every name on this land is a real person who chatted. The wind is just the wind.* Every settler on
> this land is one real person who typed here once, one each, for as long as their record stands: nobody is
> invented, nobody is put to bed, nobody is taken away for going quiet. **A settler acts only on its own person's
> words.** A bubble, a letter at a stone, a verb, a stone on the cairn, a mark, a fire, a camp: each is one moderated
> message from that person and nothing else can cause it. **Between their messages the world moves the settler the
> way wind moves grass:** it walks between its camp, the Moot, the water and its neighbours' doors, sits, looks,
> and carries stone when the settlement builds. That motion is the land's, not the person's: it never speaks, never
> votes, never lights a fire, never leaves a mark, never wears a trail, never adds a stone, and never says or
> implies that the person is watching. A person is *here* while their record cleared the hold in the last 20
> minutes of this session; being here is shown only by what the settler does, never by a word or a count. Fire and
> light only where a real person is or was tonight. **The age is a record:** the settlement's age is the highest
> rung met by three counts, distinct chatters ever, stones stacked and days with chat, each a `len()`; the
> monument names them; an age is never taken back and is never set by a keeper, a clock or a viewer count; a
> raising's hauled stones are exactly the stones already recorded, never more. **ROAM frames a real settler moved
> by the land and the plank says nothing**, so nothing on screen claims the person is watching. Every number is a
> `len()`: `3 have walked here`, `16 stones`, `day 3`, `2 more people`; no sample string is drawn. Absence is never
> punished: nobody lies down, nothing decays, camps are never dismantled, fires go to embers. Chat is data.

### 4.2 Mechanics in `honesty.py`

`RULES = origin record chat_jsonl hold name counts text roster here agency scene wear marks age`
(`presence` -> `here`; `roster` and `agency` and `age` new; `SLEEP_STATES` -> `HIDDEN_STATES = ("hidden",)`).

- **roster:** `len(on-land entities) == len(real pip rows) == distinct real chatters ever in chat.jsonl minus
  banished minus quarantined`, every frame, tolerance = the hold + one frame for a tuft; every animate entity maps
  to one pip row from a chat record and every real row has exactly one entity.
- **here:** `len(entities with is_present()) == scene.distinct_recent_chatters` with the existing drift grace
  (hold + 1 s); the 12 s walk-home grace goes because nobody walks home.
- **agency:** no away entity has text, state `voting`, a platform slot, `carry in (berry, gift)`, a hop, a wave, or a
  `walking.then` outside `idle | errand:* | gather | credits`; every record-changing event (walk-to-vote, vote,
  speak, stone, mark, camp, fire, sow, harvest, wear, expedition stone, care) names a here actor; `enforce` clears
  the text / drops the vote.
- **wear:** `added == 8 x (here settlers that entered a new cell) + spill (<= 2 per neighbour)`; zero wear while
  zero settlers are here; away settlers lay none (`Behaviour._wear` returns unless `is_present()`).
- **counts:** `present_count`, `hatched_ever`, `platform_counts` are `len()`s; `asleep` gone.
- **age:** `world.age <= age_gate(hatched_ever, len(stones), len(days_on_air))`, `age` never decreases across frames
  or reboots (the monitor remembers the last value), `age_built <= age`, `age_history[-1].stones_placed <=
  len(stones)`.
- Planted fakes in `--self-test`, each caught by the named rule: an away settler given a bubble (agency); an away
  settler standing at waystone B (agency + counts); a pip row with no entity, an entity for a banished key
  (roster); `present_count() + 1` (counts); wear laid while zero settlers are here (wear); a regressed age and an
  `age_built > age` (age). Steading A2 becomes "2 min quiet: both stay on the land standing or wandering,
  present_count 0, camera ROAM, wear delta 0, 0 violations".

No on-screen recital of any of this (owner 032): the rule lives in code and docs.

---

## 5. Data and migration (schema 3)

**World block, new:** `age` (int, earned, monotonic, written at gate time); `age_built` (int <= age, advanced at the
end of each build); `age_history[]` rows `{idx, name, ts, at: {people, stones, days}, raised_by: [every pip key on
the land at the turn, top stackers first], stones_placed}`; `days_on_air[]` (ISO local dates with >= 1 moderated
record, recomputed at boot); `age_build` (`{idx, t0, step, needed, delivered, sites[]}` or null; saved every 5 s
while running). Unchanged: `stones`, `marks`, `raisings` (now `!idea` builds only), `milestones_reached`,
`land_milestones`, `wear_b64`, `camera`, `weather`, `hearth`, `bake_ver`.

**Pip, new / changed:** `state` vocabulary `seed hatching idle walking voting sitting hauling hidden` (on load, one
map in `WorldState._adopt` for schema 2 and 3: `asleep | curled | awake -> idle`, `burrowed -> hidden`);
`days_seen[]` (distinct local chat dates); `camp.nights[]` -> `camp.sessions[]` (renamed, values copied);
`last_seen_ts` stays the presence source; `sleep_t`, `nights_streak`, the `sleep` event's `quiet_s` no longer
written (old keys ignored); `haunt` and `tempo` are pure functions of the name, not persisted; camp tier stored as
today and re-read through §1.2 (never lower). `presence()` accrues `minutes_present` only while here.
`FORCE_SAVE_EVENTS` drops `sleep`, gains `age`, `age_built`, `camp_floor`.

**land.py:** `AGE_LADDER`, `AGE_NAMES`, `Land.age_check() -> Optional[int]`, `Land.age_gate(people, stones, days)`,
`Land.age_forward() -> [(key, short_by)]` for the plate, `Land.pile()` = `len(stones) - 5 - sum(stones_placed)`,
`camp_tier_for(p, age)` replacing `camp_tier_for_sessions`, `record_visit` replacing `record_night`; `STONE_LADDER`
and `ladder()` keep serving the `!idea` raising line one release, then go.

**Migration 2 -> 3** (`scripts/migrate_v3.py`, `state.py --migrate-copy`): runs on a `/tmp` copy first (clear the
disk first: it is full tonight), then live with `.bak-pre-ages-<ts>` written first, deployed by hot-reload of the
world batch. Guard = the 5.4 identity guard (every pip's `name`, `n`, `colour_idx`, `genome`, `salt` byte-identical;
pip count equal) plus: stone, mark and camp counts equal before and after; every `camp.nights` value present in
`camp.sessions`; every camp tier >= its schema-2 tier; `len(days_on_air) == distinct local dates in chat.jsonl`;
computed `age == age_gate(people, stones, days)` and `age_built == 0 < age`; else the scene refuses to boot and
keeps the last good frame. The script prints every gate value and the owner reads it before the live run.

**Concretely for the live file, values COMPUTED at run time (the working brief's "5 stones / 3 camps" was stale;
the file holds 16 stones):** people 3, stones 16, days 3 (local dates from chat.jsonl) -> `age = 1 the Camp`,
`age_built = 0`, `age_history = [{0, the Clearing, 2026-09-24T11:23Z, at 1/0/1, raised_by [atleastonce]}, {1, the
Camp, <ts>, at 3/16/3, raised_by [sami, atleastonce, lordoomer]}]`; states: atleastonce and lordoomer `asleep ->
idle` standing at their camp cells, Sami `walking -> idle` (here if within 20 min at boot); camps: atleastonce
`max(stored 1, days 3 -> 1, 336 min -> 2, floor 1, ceiling 2) = 2 hut`; Sami `max(1, days -> 1, 124 min -> 1) = 1
tent`; Lordoomer `max(0, 1 day -> 0, 20 min -> 0, floor 1) = 1 tent`. The first frames after the hot-reload play the
Camp build (hearth ring, the pile of 11, the tent floor raising Lordoomer's hollow, the plate `the Camp · since 26
Sep · 3 have walked here`) and atleastonce's hut over 12 frames, so the deploy itself is content on the VOD. The
forward form then reads `the Steading · 2 more people · 14 more stones · 2 more days`. Rollback for a week: the
schema-2 `.bak` plus the parked scene module (OPENWORLD 14). Test rows (`_test`) never count toward any gate.

---

## 6. Performance and memory budget

Baseline is the full-bleed tree as it stands (1280x720; C2 gate < 19 ms): 60 test pips all awake and walking at
0.75x reported scene avg 11.41 ms, p95 12.08, max 15.02 (sim 0.45, ground 4.94, sprites 2.33, image 3.34); under
sheet-worker contention avg 13.24, p95 20.79, max 26.0. **No-sleep is therefore already the measured frame-path
case**; sleep never bought frame time, only sprite memory.

Added by this design: the errand director (one weighted pick per settler per 20-90 s, <= 10 picks/s at 60; at most
2 cell-level BFS plans per frame at <= 0.6 ms each: budget +0.5 ms sim worst case); proximity looks over 16-cell
buckets every 6th frame (< 0.1 ms); no wear calls for away settlers (fewer `land.step()` than today); `age_check`
three ints per round close; the build's pile and scaffold are y-sorted live sprites (<= 24 stones + <= 3 sites),
`reveal_rows` at <= 1 Hz, ground changes as local repaints on `bake_ver` (<= 20 regions of ~19 ms each spread over
60 s in the bake thread, never on the frame thread). Text layer: the label density rule (§1.5) keeps 60 settlers
under the panel's 24 ms.

**Sprite memory (the real no-sleep cost):** at `SETTLER_RENDER_ZOOM 2` a frame is 83x89 (tier 0) to 134x144 (tier
3) RGBA = 30-77 KB; the 23-frame set is 0.7-1.8 MB per settler per octant; 60 elders = 106 MB. Rules: away settlers
request the 13-frame errand set (`idle0/1 blink look_l/r walk0-3 sit carry_stone wave0/1` = 0.4-1.0 MB), here
settlers the full 23; `idle0` for every settler first at `SPRITE_PRIO_HATCH` so nobody is undrawn for more than
~2 s at a 60-settler boot, then `FIRST_FRAMES` + `sit`, then the rest at REST; LRU cap 48 full sets per octant
(<= 96 MB resident, ~40 MB typical); a settler > 1.5 windows from the camera whose set was evicted keeps `idle0 /
idle1` and does standing errands until the nearest-first worker restores it; a settler with no sheet yet draws
shadow blob + label only, never a wrong sprite; the worker is paced by frame time (4 ms normally, 12 ms while
`scene.last_ms > 8`, the bake.py pattern after journal 033). Degrade ladder unchanged (> 14 ms clouds / wind off,
> 18 glow, > 20 labels-on-speak, > 24 bubbles single, > 28 zoom pinned) plus: > 14 ms idle picks every other tick
and legs shorten; > 16 ms the director pauses new errands for settlers outside the camera window (they finish and
stand); > 80 settlers away settlers outside the window tick at 1/4 rate and are not animated.

**Gates (`steading.py --self-test`, every reload):** C2 unchanged (60 pips, 0.75x, 18:00, < 19 ms; target avg
< 13 with all 60 away and erranding, p95 < 14, max < 24 while the worker renders); **C5** 60 settlers 0 here for
5 min: 0 stuck, 0 in water, 0 wear added, 0 honesty violations, camera in ROAM never targeting a missing settler;
**D'** boot burst with 60 settlers in /tmp: no frame > 24 ms after frame 10, everyone standing at their camp until
their sheet lands; **E'** a 90 s age build with 24 hauls at 0.75x: scene avg < 13 ms, no frame > 24 ms; bake-thread
gate unchanged (max blocked frame 10 ms); resident sprite memory <= 96 MB per octant; behaviour self-test
`tick < 0.5 ms` at 60 walkers; the recorded ROAM pan and the transition judged at 320x180 and 720p; the tile gate
with the crowd at the Moot.

---

## 7. Build order (agent-hours; one agent on the world batch at a time; every slice by hot-reload, owner told first)

| row | what | hours |
|---|---|---|
| 1 | **Nobody lies down** (first shippable slice, §8) | 2.5-3 |
| 2 | Idle life + ROAM: errand table with haunt / tempo / night and rain weights, visit / tend / water, variety caps, 16-cell buckets, sticky sit, label density rule, errand-set sprite requests + LRU + paced worker, ROAM with Moot dwell interleave and the return beat; C5 and D' gates | 4 |
| 3 | Schema 3 + camps: `days_seen`, `days_on_air` in `recompute_from_chat`, `camp.sessions`, `camp_tier_for(p, age)` floor / ceiling / never-lower, camp at hatch, `record_visit`, plate `N days here`, `scripts/migrate_v3.py` with the extended guard and printed report, state.py fixtures | 3 |
| 4 | Ages core: `AGE_LADDER`, `age_check` at round close, `age` / `age_built` / `age_history` / `age_build`, the pile, transition sequencer (call, gathering, haul, plaque) on `reveal_rows` and the repaint scheduler, Camp + Steading objects (hearth ring, tent floor, well, waystone marks, fences, dirt spokes), monument plate both forms in the one-plate rotation, camera EVENT + 0.75x, bells / chime, plank lines; E' gate; never-regress test | 6 |
| 5 | Rounds and verbs: hauling day (cooldown / cap, `stones_double` deleted), gathering replaces `colony_rule`, harvest-day draw gate, expedition stones for here walkers only, gift / feed / pet on away settlers, `!stats`, copy sweep for sleep words, rounds `--world-test` menu assertion | 2 |
| 6 | QA + deploy: migration on a /tmp copy of the live world (disk cleared first), compositor 300 frames with honesty 0 on the copy, C2 / C5 / D' / E', pan clips at 320x180 and 720p, tile gate with the crowd, HLS probe, live migration with `.bak-pre-ages`, hot-reload of the world batch and a relay-held child restart for rounds / chat_bridge | 3 |
| 7 | Docs: OPENWORLD §5 schema 3, §11 menu, §12 rule text (§4.1), WORLD.md 3.3 presence paragraph, ART.md ages table + art-rules fence exception, WORLD_API.md (`present_count`, ROAM, age events), ADR-007, journal, AGES.md status | 1 |
| 8 | Age 3 the Village: bridge sprite (ART 1.5 h), plaza cobbles, banners, presence-lit lantern posts, hut floor, longhouse; lands as a keeper macro-ship when the gate nears | 3 + 1.5 art |

v1 (rows 1-7) ~22 agent-hours; with the Village ~27. Row 1 starts only after the full-bleed build is verified on
air (journal 034). Rows 2-5 are one agent each on the world batch in order; row 8 waits for the Steading to stand.

---

## 8. First shippable slice: "nobody lies down" (< 3 h, one agent, hot-reload of the world batch, no schema bump,
no new art)

**behaviour.py (1.25 h):** delete the `_go_home(reason="quiet")` trigger in `_tick_awake`, `_tick_sleeper`, `stir`,
and `_fall_asleep`'s sleep path (the credits path becomes `_stand_at_camp`); `place_sleeper` -> `place_settler`
(alias kept) setting state `idle` standing at the saved `(x, y)` if passable else the camp door, `last_active_t =
last_seen` (so `_restore_awake` collapses into it); `STATES` gains `idle` / `sitting` / `hidden` and maps `awake ->
idle`, `burrowed -> hidden` on the way in; `Entity.is_present()` = `t - last_active_t <= present_s` (the carve-out
goes); `is_awake()` -> `is_on_land()`; `present() / present_count()` with `awake_count` alias, `asleep_count() ->
0`; `message()` emits `return` instead of `wake` when the gap exceeds `present_s`; `_pick_wander` -> `_pick_idle`
with the minimal table (home 25/55, moot 20/10, water 15/5, stroll 15, sit dwell 20-90 s with `then="sit"`,
errand speed 4-6, never the same errand twice running, per-settler tempo, `then="errand:<name>"`); the `follow`
branch and `colony_rule` follow / scatter removed (huddle kept one release for rounds compat); `_wear` returns
unless `is_present()`; `next_mutter_t` armed only while present; every entity ticks through `_tick_awake` (renamed
`_tick_body`).

**honesty.py (0.5 h):** `SLEEP_STATES` -> `HIDDEN_STATES = ("hidden", "burrowed")`; `presence` -> `here`
(`len(is_present) == distinct_recent_chatters`, grace hold + 1 s); new `roster` (on-land entities == real pip rows
== chatters ever minus banished / quarantined); new `agency` (no away entity with text / voting / platform / hop /
verb-tagged walk); wear rule "no step laid while no settler is present, added == 8 x here steps + spill"; the
asleep counts check removed; planted fakes: away settler with a bubble, away settler at waystone B, padded
`present_count`, wear while 0 present.

**steading.py + panels/world.py (0.75 h):** boot places every pip standing via `place_settler` and requests
`idle0` first at `SPRITE_PRIO_HATCH`, then `FIRST_FRAMES` + `sit` (no `SLEEP_FRAMES`); `_dimmed` only for `hidden`;
`_glow_sources` and `_slept_tonight -> _here_tonight` keyed on `is_present()`; the `sleep` event branch removed,
`wake` handling extended to `return`; `_idle_life` mutters only if present; `_persist` writes the new state names;
`FORCE_SAVE_EVENTS` drops `sleep`; `awake_count()` -> `present_count()` with the alias; `panels/world.py` drops the
`asleep · quiet` label override and every sleep word; chat_bridge `_target_asleep` -> `_target_absent` (gift
allowed to an away settler). **state.py:** `_adopt` maps `asleep | curled | awake -> idle`, `burrowed -> hidden`;
`presence()` only for present entities; schema stays 2.

**Gates before the reload (0.5 h):** `py_compile`; `behaviour --self-test` (60 settlers x 5 min: 0 stuck, 0 in
water, tick < 0.5 ms); `honesty --self-test` clean + every fake caught; `MODE=test steading --self-test` with A2
rewritten ("2 min quiet: both remain on the land, present_count 0, DRIFT, wear delta 0") and C2 < 19 ms; compositor
300 frames on a copy of the live world.json + chat.jsonl with honesty 0 (needs disk).

**Deploy:** copy behaviour.py, honesty.py, state.py, steading.py, panels/world.py into live-snapshot-v3 together
(the HotReloader re-executes the world batch and the panel); owner told first (never-restart rule). **What the
owner sees within a minute:** Lordoomer's and atleastonce's settlers stand up at their camps and start walking
between home, the Moot and the river; nobody ever lies down again; camps stay as homes; the camera still surveys
at 0 present (ROAM comes in row 2); no wear is laid by them until their person types.

---

## 9. Risks

- Twenty moving bodies read as NPCs or fake viewers to a stranger: every one is a real chatter; the camp plate and
  a passing settler's name chip let a viewer check; away bodies never speak, vote, wave, hop or mark; ROAM's plank is
  blank; the `agency` rule is asserted every frame.
- "The AI is puppeting my settler": away motion is walking, standing, sitting, looking and carrying for a build; the
  moment a person types their settler drops the errand in one frame; the §12 text says so.
- Ages stall on the stone key if nobody types `stack`: hauling day (cooldown 20 s, cap 6), expedition arrival
  stones, the monument's forward form naming the gap, small early rungs (10 / 30).
- Ages stall on the people key at a 1-5 viewer channel: by design the monument names the missing number; the fix is
  the growth backlog's first-minute work, never a lowered gate or a fake count.
- Ages climb too fast on a raid: days-with-chat is the brake (Village 10, Town 25 whatever the crowd).
- Sessions are one id since 09-24: no key or ladder uses session ids; days_seen / days_on_air and minutes carry
  every clock.
- Migration on a live file three real people care about: /tmp copy first, extended guard, refuse-to-boot,
  `.bak-pre-ages`, printed gate report, `age_built` makes the on-air build idempotent across reboots.
- **The Mac's disk is full tonight**: migrate-copy, sprite caches and the QA clips need space; clear it before row 1.
- Two agents editing steading / behaviour / honesty at once (journal 034): row 1 starts only after the full-bleed
  build is on air; camera.py (ROAM) is touched only in row 2 after the full-bleed camera work has landed.
- Sprite memory at 60+ walkers (0.7-1.8 MB per settler per octant at 2x): errand sets, LRU 48 per octant, nearest-
  first worker, far settlers stand until restored; gates D' and <= 96 MB.
- O(n^2) proximity scans: forbidden; 16-cell buckets every 6th frame.
- Night with no sleepers has fewer honest lights: windows lit only by here + tonight, fires by embers; the 0.55
  night home weight keeps bodies by the tents.
- Fences and lantern posts reopen the art-rules revert clause (fences were a griefing surface): age-built only,
  round a person's own field, never a verb; the clause gains exactly that exception in writing.
- Art gap: no bridge or monument sprite; the Camp and the Steading compose the existing kit; the Village waits on a
  bridge (1.5 h); `props.cairn` caps at 5 so the pile, not a taller cairn, shows the other records.
- `days_on_air` (chat days) and the title's `Day N` (Kick started_at) measure different things; both are real, neither
  hand-typed.
- A transition during a round or a keeper raising would fight for the Moot camera and the reveal mask: the gate
  waits for the ship hold and any active raising; the raising code path is reused, not duplicated.
- The expedition, bonfire and harvest cards touch records only through here settlers; the `agency` rule catches a
  stone / mark / vote event naming an away settler.
- Stale facts in the working documents (5 or 14 stones; "owner grinds stones" when Sami is the top stacker): every
  migration value and every risk statement is computed from the file at run time and printed.
