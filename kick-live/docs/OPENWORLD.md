# LONGGRASS — build-ready spec for the open-world redesign (top-down settlement)

Channel `atleastonce` on kick.com. Written 2026-09-25 by the synthesizer step of the
`kick-live-open-world` workflow (5 concepts, 3 judges, this document), re-run under an **owner
directive** after the mockup review (journal 020, 18:40 addendum). The owner's verdict on PIP
HOLLOW live: *"this feels less like a world and more like a prison. Can't we make this more open?
Outside and with space. Age of Empires style maybe? Big open areas that the living things chat
creates can move around. I need some fresher ideas, this is cold and stagnant."* The owner then
picked the **Settlement** direction, reviewed three rendered camera styles
(`docs/mockups/topdown_*`, `isometric_*`, `sidescroll_*`) and chose **top-down**: *"The top down
style is the best"*, adding that *"the actual design of the individual parts needs to be massively
improved"*, aligned with the appeal of Plaything's Thronglets while staying our own.

The judged winner was **LONGGRASS** (154/180), a side-view valley with a sky band. This document
keeps its name and re-projects every judged mechanic onto the top-down camera the owner chose:
the nature-is-alive rule and its exact wording, wind driven by the real chat rate, the real sun,
moon and seasons as light and shadow over the ground (no sky band), the damped never-cut camera,
the camp ladder, path wear, cairns and keeper raisings, the leading-verb rule, the disclosed
compressed-day switch and the tile QA gate. Grafts from THE COMMONS, WIDE COMMONS, THE WIDE LEA and
BROADFELL are folded in; every flagged fatal flaw is removed. ADR-006 records the choice. ADR-000
still governs everything below. The cave's one-sentence rule is replaced, because it was the bug:

> **Every name on this land is a real person who chatted. The wind is just the wind.**

Honesty is about WHO is on the land: every creature, hut, field, tree, flower, stone and worn path is
a real chatter. The land itself is always alive (wind in the grass, a river, cloud shadows, a sun that
swings the shadows round, tides, seasons, growth) whether anyone is there or not. There are still no
animate non-persons (no birds, animals, fish, NPCs, mascots) and no fake people, ever. The empty state
is untouched living wilderness, never a cell.

**Art source of truth.** A separate workflow (working dirs `docs/art/studio-a`, `docs/art/studio-b`)
is producing `stream/world/art/` and `docs/ART.md`: creatures, buildings, props, ground tiles and HUD
chrome. This spec does **not** re-specify sprites; §7.2 states only the interface the scene needs
from that atlas and the rules it must pass. Where `docs/art-rules.md` §3 and `docs/ART.md` disagree
on the look of a creature, `ART.md` wins; the honesty and no-IP principles in art-rules stay.

What this document supersedes in `WORLD.md`: §1 identity, §2.2 first 60 s, §3.4 colony state, §4
verbs (extended), §5 region-5 content and region copy, §6 art direction and budget, §7 audio
(extended), §8.1 MENU, §8.2 milestone actions, §9 keeper representation, §10 empty states, §12
build order, §13 risks. What it keeps: `WORLD.md` §2.1 (the six wants), §3.1-§3.3 (files, pip
identity, presence, energy, growth tiers, memory, bonds, care log, strikes), §11 (honesty and
moderation, extended in §12), and `stream/WORLD_API.md` as the contract shape (frame / entities /
events / command / platform_counts; the class is renamed and gains a camera). The pipeline is
fixed: headless Python 3.9 pillow/numpy compositor, 1280x720 at 30 fps, one 1600-sample audio block
per frame through `stream/relay.py`, real Kick chat as `{name, text}` in 1-3 s, the 3 s moderation
hold, `world.json` + `builders.json`, the 180 s A/B/C RoundEngine, keepers building `!idea`s as real
code by hot-reload, exact-token verbs (now with a leading-verb rule), generated audio only, no IP.
The previous revision of this file (side-view LONGGRASS) is superseded in full.

---

## 1. Identity

| Field | Value |
|---|---|
| **Name** | **LONGGRASS** (the land). The settlement chat raises on it is **the Steading**. Creatures stay **pips**. A person's home is their **camp** (hollow → tent → hut → hut with a chimney). The vote markers are three **waystones** on **the Moot** (the village green). The keepers' lantern is the **beacon** on a post at the Moot. The monument is the **cairn**. |
| **One-liner** | A sunlit land seen from above, where wind combs the grass, a river runs to a tidal shore and the sun swings the shadows round even when nobody is there. Say anything in Kick chat and a creature with your name walks out onto that land; it goes where you tell it, wears a trail into the grass, pitches a camp where you choose, plants trees that are taller next week, sows a field, carries stones toward a bridge the whole chat is raising, and is still there tomorrow. Every name on the land is a real person. |
| **Stream title** (57 chars) | `Say anything in chat. A creature walks out with your name` |
| **Fallback title** (54 chars) | `Say anything. A creature with your name walks the land` |
| **Kick category** | Keep **Software & Game Development** for the first Longgrass session (the keepers-build-it-live differentiator is what the category rewards and the channel already sits there). Then A/B one games/creative category over two sessions on real `viewer_count` only; the candidate name is read from Kick's category API through the OAuth app, never guessed. |
| **Channel description** | A living pixel land that only people can populate. Say anything in chat and a creature with your name walks out onto the grass; it goes where you say, leaves a trail, pitches a camp, plants and sows, and is still there tomorrow. Every 3 minutes chat votes on the weather and the day. AI keepers raise new things live from chat's ideas. No camera, no mic, no fake viewers: every name on this land is a real person. |
| **Version** | Lands as macro-ship **v0.6.0** (`v{major}.{macro}.{micro}`); rounds keep bumping `micro`, keeper builds keep bumping `macro`. `hollow.py` stays on disk one week as the rollback. |
| **Age of Empires** | Named by the owner as a mood: open ground seen from above, a settlement that grows over days, a minimap, a structure rising from a stockpile, roads nobody designed. Nothing here is an asset, a unit, a villager, an isometric diamond tile, a resource counter in a top bar or a franchise word. `docs/art-rules.md` §3 gets a row for it. |
| **Thronglets** | Named by the owner as the bar for appeal (small, expressive, alive, warm), not as a look. `docs/ART.md` owns the silhouette language; the rule is our own shapes, name-derived colour, no single default colour, no round-yellow look-alike, no multiplication, no morality. |

Invented plain words only: pip, Longgrass, the Steading, the Moot, waystone, camp, beacon, cairn, the
Ford, the Shore, the Fell, the Wood, the Reed Marsh, the Orchard Slope. Nothing references Age of
Empires, Plaything, Thronglets or any franchise.

---

## 2. Why it is not a prison, and what is alive at zero

### 2.1 The five reversals (mechanical, not tonal)

The cave failed for five reasons an open-world game never allows. Each is inverted by a mechanism,
not by copy.

1. **Window, not box.** The frame is a 320x110-cell window (at the standard zoom) onto a 960x440-cell
   map: twelve screens of land, growing at head-count milestones. Every frame edge is more land; the
   camera proves it by panning, and an always-on minimap shows the viewport as a small rectangle
   inside the whole map, which is the trick that makes a player feel the size of a world they cannot
   see. The map edge is never on screen.
2. **Two axes of freedom.** Pips move anywhere on the ground plane, y-sorted, with sun shadows; a
   lone pip standing in a meadow reads as a figure in a landscape, not a token on a rail. `go river`,
   `go north`, `go home`, `go @name` walk your creature out of frame and the camera follows it across
   the land, revealing the Ford, the Wood, a stranger's hut with a real name plate.
3. **Forces that are not people.** Wind moves the grass in travelling bands, cloud shadows drift,
   the river flows, the tide creeps up the Shore, the sun crosses the sky on the real clock and swings
   every shadow round, seasons repaint the land, weather changes on its own between rounds. The world
   does not wait for a viewer, so an empty frame reads as wilderness, not as a room with the lights
   off. The art rule: **nothing moves itself except a real person's pip; everything else is moved by
   wind, water or the sun.**
4. **A settlement, not cells.** Sleepers are not silhouettes in numbered holes; they lie at their own
   camp, where they chose to pitch it, with a name plate, and over sessions the camps become huts, the
   huts get fields, and the trails between them become roads. The Steading at 3 am reads as a village
   at night with a few lit windows, not a graveyard.
5. **Warmth.** A sunlit meadow palette inside the dark UI chrome; night is moonlit blue with a hard
   luminance floor of 0.55 (never black), moon glitter on the water, and warm light only where it is
   honest (a real person's fire, a real person's window). Sound is wind, water, bells and footsteps,
   not drips in rock.

### 2.2 Alive at zero (explicit list; every item is nature, light, the clock or a real person's mark; none is an animate non-person)

| Layer | What moves at 0 awake | Source |
|---|---|---|
| **Wind on the grass** | Two travelling brightness fronts (wavelengths 40 and 90 cells, ±8 % luminance) plus gust pulses every 6-20 s roll across the grass along the wind vector at 6-14 cells/s, so a wave of light visibly crosses the frame in ~8 s; smoke, banners on the waystones, rain and leaves ride the same vector. **Base wind speed = real chat rate** (msgs/min over 5 min) with a floor so still air never happens; above 20 msg/min it is a gale. The wind direction drifts on a 40 s LFO and is shown on the time dial (`wind NE · fresh`) | wind sim, real chat rate |
| **Cloud shadows** | 2-3 soft angular shadow blobs 60-140 cells wide drift over the ground at the wind speed, darkening what they cover to 85 %; you never see the cloud, only its shadow, which is what a top-down view shows | wind sim |
| **Water** | The river flows from the Fell to the Shore with a scrolled sparkle pattern and foam at the Ford stones; the sea has slow swell bands and a wet-sand line that moves 0-3 cells on the real 12 h 25 m tide; moon glitter on water at night; the river swells 30 % during rain | clock, weather |
| **Sun and moon as light and shadow** | The real local hour drives a tint over the whole ground (dawn warm, noon neutral, dusk rose, night blue-grey with the 0.55 floor plus up to 0.05 from the real moon phase) and the **shadow vector**: every hut, tree, stone and creature casts a shadow whose direction and length swing with the hour (long west at dawn, short at noon, long east at dusk, faint moon shadows at night). A small **time dial** in the world region shows the sun or the real-phase moon on an arc with the local time, the day part and the wind. There is no sky band: the sky is read from the ground, the way a top-down view has to | real clock |
| **Weather** | A seeded Markov chain per world-hour over clear / breeze / overcast / rain / gale (snow in winter) so the weather changes on its own between rounds; a round pick overrides it for 3 min. Rain = streaks on the wind vector, darker ground, puddle sparkle in worn trails; gale = grass bands flatten and speed up, pips lean; fog = a soft haze that thickens with distance from the camera centre | seeded chain, rounds |
| **Seasons** | The real date selects one of four ground bakes (spring green with wildflowers, summer gold-green with wheat-coloured meadow, autumn straw with leaf particles near the Wood, winter frost with snow on the Fell and bare canopies); hemisphere defaults to southern from the machine timezone (`Australia/*`), overridable; the land line names the season so a mistake is visible | real date |
| **Growth** | Planted trees grow by **real calendar days** whether or not the stream is live (sapling → young tree at day 3 → canopy at day 14); sown fields advance by real days too (sprout day 1, green day 3, gold day 7), so a returner always sees "your tree grew" or "your field is gold" | real timestamps |
| **Real people's marks at rest** | Camps of real past chatters (a hollow, a tent, a hut or a hut with a chimney, by their real session count) with a plate on a 5 s rotation `@sami's hut · night 4 · last here yesterday 10:40`; a window lit only if the owner was awake this session, dark otherwise; a wind-bell at each camp pitched by the owner's name hash, rung by gusts; fields in the owner's colour at their real growth stage; planted trees and flowers; the cairn with its plaque; worn trails; the notice board | `world.json` rows |
| **The camera** | DRIFT (§4.4): a slow survey at 4 cells/s (16 screen px/s) along a loop over every real mark plus three fixed natural points (the Ford, the Fell top, the Shore), pausing 20 s at each camp so the plate reads; a full lap in 8-12 min; the shadows move while it surveys; the plank reads `surveying · @sami's tent · last here yesterday 10:40` / `surveying · the Ford` | camera state machine |
| **Rounds** | Three waystones on the Moot carry their letters each round and stand empty; at 0:00 the picked weather lands on the whole land with the honest `nobody voted. the keepers picked B.` | RoundEngine |
| **Beacon** | The keepers' lantern on a post at the Moot: lit and swinging gently on a fresh heartbeat, dark and still otherwise; a lit amber dot on the minimap so a viewer knows from anywhere whether someone is tending the land | `agent.heartbeat_ts` |
| **Audio** | Wind bed following the sim wind; river and shore beds by the camera's distance to water; camp bells on gusts; rain when it rains; a single soft bell at real sunrise and sunset; pad silent (voices = awake count = 0) | same sources |

**Header at zero:** `SAY ANYTHING` with `a creature walks out / with your name` beside it (HUD pass,
journal 028: the instruction, not `NOBODY AWAKE`). **The 320x180 tile at zero** is a green-and-blue
land with moving cloud shadows, a river line and a few coloured roofs under a legible 56 px headline (§4.5).

**Optional lever, off by default (WIDE COMMONS graft):** `world_day: "real" | "hour"`. On `"hour"`
the sun runs a 60-real-minute day (36 day / 6 dusk / 12 night / 6 dawn, noon at :30) so 80 % of any
watch is daylight; the time dial then carries `1 h = 1 day` and the ticker says `a day here is one
hour` in its rotation; the moon phase stays real. The owner streams and judges in the evening; if the
moonlit frames from the mock gate (§14) still read cold, this is the switch to flip. Seasons, tree
and field growth stay on real days either way.

---

## 3. The first 60 seconds

### 3.1 A stranger, dead night

**T+0 after their record lands** (Kick delivery 1-3 s after the keypress). Within one frame a
nameless seed tuft (grey, no colour, `display_name: None`, `key: None`) drifts in from the **upwind**
edge of the frame along the real wind vector, its shadow travelling under it, and the camera leaves
DRIFT and eases toward its landing spot on the Moot green (an x, y hashed from the username inside a
30-cell ring around the green's centre), so a newcomer is on screen before they hatch and never lands
at a far edge. The drift is exactly the 3 s moderation hold, as the egg crack was: the tuft settles
and splits in three 1 Hz frames. The header does not change yet.

**T+3 s, hold cleared and blocklist passed.** The tuft pops and the pip stands there in its
name-derived colour with its deterministic parts from `stream/world/art/`, a soft sun shadow under
it, the grass around it bends outward once, its two-note motif plays, the new-builder rise plays on a
first-ever message, `@name` fades in above it (Menlo 20, stroked, on a 60 % dark chip), the label
carries `#N` (the real builder number) for 3 s, and the bubble shows their actual text for 6 s.
Header flips `SAY ANYTHING` to `1 AWAKE` in the same frame (the newcomer's first ack). The camera
settles into FOLLOW with lead room in the direction the pip faces. Plank: `@name walked into
Longgrass · 21:14` (real local time). If they are
the only awake person, under the pip for 10 s: `you're the only one out here right now. the wind was
already blowing.` If it is the session's first message, **first breath**: the pad's first voice fades
in under the wind over 2 s and every camp's bell rings once in sequence, west to east (each bell is a
real sleeper's mark acknowledging the arrival; no fake presence). A blocklisted username stands up as
`builder #N`; a user hidden inside the hold: the tuft blows on out of frame (`the wind took that one`).

**T+4 to T+10 s.** Plank: `that's you, @name · try: go river · plant a flower · camp · or A, B, C`
(by name, once, while awake ≤ 1, until their first verb; row 2 while an ack holds row 1). After each
verb completes the plank offers the next two things for 8 s (`next: camp pitches your tent here ·
plant a flower leaves your mark`). A short message that carries one of our words but does not parse
gets the exact token (`to do that, type: go north`), never the typed words. The pip
wanders in 2D, pauses, turns to face the wind now and then; the grass under its feet is pressed, so a
faint trail follows it within ten seconds (a mark in the first minute).

**T+10 to T+30 s.** They type `go river` (or `go to the river`, leading-verb rule): the pip sets off
at 8 cells/s along the coarse route, the camera leads it by a third of a screen, footsteps change from
grass hush to ford splash as it reaches the crossing, and behind it a faint line of pressed grass is
visibly a trail. On the way something real enters frame: a hut with a real name plate and `last here
yesterday 10:40 · window dark`. They can `gift` at that hut (a wrapped pixel by the door, played back
when the owner returns). `plant a flower` puts a flower in their colour at their feet with the plate
`flower · @name · day 1` on a 5 s rotation. `camp` pitches a tent where they stand: their sleep spot
from now on, on the map, at a place they chose, with a plate `@name's camp · night 1`.

**T+30 to T+60 s.** The round closes; the three waystones on the Moot carry A, B and C in AB 56 above
them; their single letter walks them to one, the count under it reads 1, and at 0:00 the whole land
reacts: rain sweeps in from the west with the camera easing out to the wide zoom for the sweep, the
river brightens, the grass bands darken and lean. `nobody else voted. your letter decided this one.`
By minute 10 the pip grows a size (tier 1, first night by design). Between messages the frame never
stops: wind bands, cloud shadows, the shadow vector edging round, the camera holding a breathing lead
room. At 20 min of silence the pip walks to its camp and lies down, its fire drops to embers, and the
camera resumes its survey. Nothing dims, nothing nags.

### 3.2 A returning chatter

Their sleeping pip stands up at its own camp (out of the tent flap or the hut door); the camera pans
there before their text arrives; their fire relights; their bell rings once (three times, and every
awake pip turns toward the camp, on a homecoming after 7+ days). The care log bubbles first, from real
records: `back after 2 nights · your tree grew · your field is gold · @kai watered your field · gift
from @sami`. Then their text. If the camp tier crossed a session threshold (§5.3) the upgrade is
raised over 12 frames while they stand there: `@name's camp · hut · night 5`. If their field is gold
the plank says `harvest when you're ready`.

---

## 4. Map and camera

### 4.1 Map

**Size and storage.** **960x440 cells** (1 cell = 4x4 screen px at the standard zoom; 3 screens wide
by 4 tall; 3840x1760 screen px laid flat), generated once from `world.map_seed` and committed after a
PNG review. Layers as numpy arrays: `biome uint8`, `height uint8`, `moisture uint8`, `water bool`,
`passable bool`, `cost uint8` (marsh and ford slow), `caster uint8` (shadow-caster height per cell for
the Wood, huts, stones), a coarse **60x28 BFS route grid** (16-cell blocks) derived from `passable`, a
places registry `{name, x, y, radius}`. Mutable layers in `world.json`: `wear_b64` (uint8 960x440,
zlib + base64, mostly zeros), `marks[]`, camps (derived from pips), `fields[]`, `stones[]`,
`raisings[]`, `land_strips[]`, `camera`, `weather`. The **painted ground** is a screen-resolution bake
per season (§7.3) that a mark change repaints locally (a hut is a 56x48 px region, index writes);
whole-map work in the per-frame path is forbidden by art rule.

**Generation (fully procedural, deterministic, persistent; the owner's 020 question).**
`terrain.py` reuses the method of the approved mockup (`docs/mockups/topdown_render.py`): fbm value
noise → elevation with a gradient so the sea lies to the south-east, a second noise for moisture;
sea = water connected to the map border (ponds are the rest); a whole-map **site search** picks the
Steading: flat grassland 9-12 tiles from the sea, hills to the north-west, forest within reach, no
pond in the first frame; the river is traced downhill from the hills past the site to the sea and
carved 6-14 cells wide, with one shallow **Ford** beside the Steading; obstacles (the Wood's trunks,
boulders on the Fell) are generated as convex blobs so the slide rule cannot stick; the Moot green is
the largest flat short-grass disc at the site. Rendered to a PNG, reviewed, seed committed; never
regenerated in place, so marks stay where people left them. The seed of the approved mockup
(`4471`) is the first candidate.

**Places.** The **MOOT** (the village green at the site: waystones, the beacon post, the notice
board, the cairn; where seeds land), the **STEADING** ring around it (where camps cluster; the
default `camp` radius is 24-60 cells from the green), the **FORD** on the river beside the Steading,
the **RIVER** from the Fell to the sea, the **SHORE** (sea to the south-east with the tidal sand
band), the **FELL** (hills to the north-west: thin grass, rock, stronger wind; stones for `stack`),
the **WOOD** (dense trees to the east; trunks impassable, edges passable), the **REED MARSH** on the
river's inner bends (passable, slow, reeds sway), the **ORCHARD SLOPE** (the gentle rise between the
Steading and the Wood where planted trees grow 1.5x faster). Passability: grass, meadow, marsh, ford,
sand, trail walkable; deep water only via `swim`; trunks and boulders solid. `go <place>` and the
screen-scale place labels read the registry.

**Land opening (v1.1, the owner's "chunked map that grows outward").** Head-count milestones 10 /
25 / 50 distinct real people let the keepers open a new 320x440 strip east or west (the Coast with
its own tides, the Birch Wood, the Tarn) as a hot-reloaded module; the strip is baked in a background
thread, becomes walkable when it ships, the minimap rescales and the camera clamp moves. The map edge
is never on screen (§4.4), so an unopened side reads as more land, not a wall.

### 4.2 The explored minimap (honest, never fog)

The minimap always shows the **whole** map's terrain: nothing is hidden, there is no fog of war (a
rule in `docs/art-rules.md`). What it distinguishes is **walked** from **unwalked** land: cells
within 24 cells of any real footstep (`dilate(wear > 0, 24)`) are drawn at full saturation, the rest
at 55 % saturation, with the caption `4 % walked` (a `len()` over cells). That is a real record of
where real people have been, which is what "explored" honestly means here, and it makes a viewer
want to walk somewhere nobody has.

### 4.3 View and zoom

The `world` region stays `(0, 72, 1280, 440)`. The camera is a float centre `(cx, cy)` in cells and a
zoom from a fixed set. The ground is painted at 4 px/cell once (§7.3); the viewport is a crop of that
painting resampled to 1280x440, so zoom is a crop size, not a re-render:

| zoom | window (cells) | crop of the bake (px) | resample | creature on screen (tiers 0-3) | tile px | when |
|---|---|---|---|---|---|---|
| **0.75x** wide | 427x147 | 1707x587 | BOX down | 27-52 px | 7-13 | awake spread > 70 % of the 1x window, a weather sweep, `expedition`, the last 30 s of a round if the waystones and voters do not fit at 1x |
| **1x** standard | 320x110 | 1280x440 | none | 36-70 px | 9-17 | default; DRIFT always |
| **1.5x** close | 213x73 | 853x293 | BILINEAR up | 54-105 px | 13-26 | exactly one pip awake and it has moved < 40 cells in 30 s (BROADFELL graft) |

No 0.5x (creatures would drop to 18 px) and nothing below 0.75x. Creature and prop sprites are
supplied by the atlas at each of the three zooms and cached; text is always drawn at screen scale.
Panning is in whole bake pixels (0.75 / 1 / 1.5 screen px per step through the resampler), smooth on
a painted ground; the text layer receives the float camera so labels move with the sprites.
`sim_to_screen(x, y)` = `origin + (x - view_x0) * 4 * zoom`, returns `None` off-view; the text layer
culls off-view labels and clamps bubbles inside the region. A zoom change is a 12-frame crossfade
between the two crops (two resamples for 12 frames, +2 ms), never a jump.

### 4.4 Camera state machine (`stream/world/camera.py`, pure functions of state and `ctx.now`)

State: `pos (cx, cy)`, `zoom`, `target`, `target_zoom`, `last_zoom_change`, `mode`. Persisted to
`world.json["camera"]` every 5 s so a scene hot-reload resumes without a jump. Evaluated each frame
in priority order:

| # | mode | trigger | target and framing |
|---|---|---|---|
| 1 | **EVENT** | seed landing, hatch, wake, camp raised, raising ship, land opening, cairn naming | that point, hold 4 s, 1x (1.5x for a 3 s hatch close-up when only one pip is awake) |
| 2 | **MOOT** | last 30 s of a round with anyone standing at a waystone, or any pip walking to one | the three waystones plus every awake pip within 120 cells; 0.75x if they do not fit at 1x |
| 3 | **FOLLOW** | awake ≥ 1 or a pending seed | target = weighted mean of awake pips (weight 3 for anyone who spoke in the last 10 s, 2 for a pip currently walking, 2 for a seed, 1 otherwise). **Lead room in two axes:** the target sits 15 % of the window ahead of the newest mover's facing vector (so 60 % of the frame is in front of it, top-down), the offset flipping only after the facing has held 2 s. Zoom by bounding box with a 24-cell margin; if the group does not fit at 0.75x, follow the connected cluster containing the last speaker (link radius 60 cells) and let the minimap and edge arrows show the rest |
| 4 | **CLOSE** | exactly one pip awake and it has moved < 40 cells in 30 s | 1.5x on that pip with lead room; a lone viewer sees their creature at 54-105 px, not 36-70 |
| 5 | **DRIFT** | 0 awake, no seed | the survey loop over real marks plus the three natural points at 4 cells/s, 20 s dwell at each camp, 12 s elsewhere; never repeats a route inside 10 min; plank `surveying the steading · last here: @sami yesterday 10:40` |

**Motion rules (why the frame is never still and never nauseating).**
- A critically damped spring with a 0.8 s time constant (~1.5 s settle), pan speed capped at
  **60 cells/s** (240 screen px/s at 1x, readable on Kick's ~3 Mbps encode), a 1.5 s dead zone so the
  camera does not chase a pip that wanders 10 cells.
- **Never a cut**, including at 0:00: a round event that needs the Moot is an ease at the cap. The
  only cut is the first frame of a session.
- Zoom changes only when pan speed is under 2 cells/s and at least 20 s since the last change, as a
  12-frame crossfade.
- **Off-frame life:** a message from a pip outside the window glides the camera to include it within
  1.5 s, widening to 0.75x if two groups are far apart; if it still cannot fit, the newest speaker is
  followed and the other gets an edge arrow `@kai · 210 paces →` in their colour at the nearest
  frame edge, plus its dot on the minimap.
- **Gravity:** idle wander is biased 30 % toward the Moot and capped at 200 cells from it unless a
  `go` / `explore` target says otherwise, so life stays findable and the camera rarely needs 0.75x.
- **Clamp:** the window never shows the map edge (a 12-cell margin; the outermost cells are tall
  grass fading toward the horizon haze), so an edge never reads as a wall.
- At 0 awake the DRIFT survey plus wind, cloud shadows and the shadow vector mean the frame changes
  every frame; at 1 awake the wander breathes the lead room; at 1.5x the pip's own idle bob moves
  the framing.

### 4.5 The 320x180 directory tile

The frame at 1:4. Rows 0-16: the header, `3 AWAKE` at 56 px → 14 px, still legible; row 17 the
countdown. Rows 18-128: the world at 1x is the cell grid **1:1** in tile pixels: grass with moving
wind bands and cloud shadows, the river line, the sea, huts as 3-4 px coloured roofs, fields as
coloured squares, pips as 9-17 px name-coloured shapes, the minimap a 36x25 smudge that still reads
as "a map". Rows 128-164 the three strips, 164-180 the footer. The gate (§7.5) replaces the cave's
"a light source at 0 awake" (which the cave failed at 3.9 % lit pixels): at 0 awake the tile shows a
moving land, a legible header count, and no name except camp plates from real rows.

---

## 5. Entity model deltas versus `WORLD.md` §3

`WORLD.md` §3.1 (files), §3.2 identity fields and §3.3 rules (identity immutable, awake = chatted in
the last 20 min, energy cosmetic, tiers by sessions or minutes, memory, bonds, care log, strikes)
carry over unchanged. Schema bumps to **2**. Deltas:

### 5.1 Pip record

| field | change |
|---|---|
| `y` | new: feet row in map cells (2D position; `x` is now a map column, not a floor x) |
| `facing` | new: unit vector `(fx, fy)` quantised to 8 directions, used by the camera's lead room and the sprite flip (the atlas supplies front-facing frames with a horizontal flip; `ART.md` may add back frames) |
| `colour` | new: the creature's body colour from the art genome (`art.creatures.genome(name)["body"]`), used for labels, plates, roofs, field borders and minimap dots so a person's things match their creature. `colour_idx` is kept for the chat pluck and the chat log; `!theme` no longer retints creatures (the land and its people are real; the UI accent is themed) |
| `camp` | new: `{x, y, tier, built_ts, nights[]}` replaces `burrow`. Created on the first real sleep (hollow, tier 0) at the spot the pip stood, or chosen by `camp`; `nights` is the list of session ids slept there |
| `field` | new: `{x, y, sown_ts, stage, harvests, waterers[]}` or `null`; one field per person, 3x2 cells beside the camp |
| `carry` | new: `null | "berry" | "stone"` with `since_ts` |
| `home` | new: alias of `camp.x, camp.y` for `go home` |
| `marks_planted` | replaces `moss_planted`: `{flower, tree, reed, stone}` counts |
| `digs`, `burrow` | dropped (`digs` kept as a stat in `history` for the two existing pips) |
| `state` | same names: `seed hatching awake walking voting curled asleep burrowed`. `walking` gains `target (x, y)` and a `route[]` of coarse-grid waypoints; `asleep` = lying at own camp; `burrowed` (hidden by a mod) = lying in grass with no label and no plate |

### 5.2 World block

| key | meaning |
|---|---|
| `map_seed`, `map_w`, `map_h`, `hemisphere`, `world_day` | generation seed and dimensions; `"south"` default; `"real"` default |
| `wear_b64` | uint8 wear per cell, zlib + b64. **Never decrements** (absence is never punished: a real mark does not fade). +8 on the exact cell and +2 on its 4 neighbours per step into a new cell, only from `Behaviour._move` under a real awake pip; cap 255. Thresholds: 8 pressed grass (one walk is visible), 48 bare earth, 160 a stone-edged road |
| `marks[]` | `{id, type: flower|tree|reed|flag|notice, x, y, owner, ts, extra}`; every owner must exist in `pips` (honesty §12) |
| `fields[]` | derived index of every pip's `field` for the renderer and the minimap |
| `stones[]` | one record per `stack`: `{by, ts, cairn_id}`; the cairn's height is `len()` and its plaque lists distinct stackers; a cairn is **named** when 3 distinct real people have stacked (reachable at this channel, not five) |
| `stock` | derived: `len(stones)`; the ladder 20 / 60 / 150 queues keeper raisings (§10) |
| `raisings[]` | `{name, at_stock, shipped_ts, version, plaque: [top 3 stackers]}` |
| `land_strips[]` | opened strips `{side, biome, opened_ts, by, version}` |
| `camera` | `{x, y, zoom, mode}` every 5 s |
| `weather` | `{state, since_ts, chain_seed}` |
| `days` | distinct session ids seen (`day 6 of Longgrass`) |
| `hearth` | `{lit_ts, by}`; the Moot hearth burns only if a real person lit it (first breath or `fire` at the Moot) this session |
| `bake_ver` | bumped when a mark that lives in the painted ground changes (hut tier, field stage, tree stage, trail threshold), so a booting scene knows whether its cached bake is current |
| dropped | `terrain_b64`, `moss`, `nests`, `chambers` |

### 5.3 Camps (the return hook, compressed to this channel's scale)

| camp tier | look (from the atlas) | reached at | plate |
|---|---|---|---|
| 0 hollow | pressed grass 8x6 cells with a bedroll | first real sleep (night 1) | `@name's camp · night 1` |
| 1 tent | 10x8 tent in the owner's colour, a bell on a stick | 2 sessions | `@name's tent · night 2` |
| 2 hut | 14x12 hut with a roof in the owner's colour and a door plate | 5 sessions | `@name's hut · night 5` |
| 3 hut with a chimney | 14x12 plus chimney (smokes while the owner is awake), a window lit while the owner is awake or asleep tonight, room for a garden | 10 sessions | `@name's hut · built night 10 · last here yesterday 10:40` |

Sessions count exactly as `sessions_seen` (§3.3), so two regulars see a village within a fortnight
and huts never appear from nothing (THE COMMONS graft: every plate resolves to a pip row with real
sleep records). `camp` moves the home to where the pip stands (THE WIDE LEA graft: a person chooses
where they live), within the Steading ring or anywhere passable, never on water, trail, the Moot
green or within 12 cells of another's camp unless the two are bonded (3+ both ways), in which case
they may sit within 6 cells and a shared trail is drawn between them. Existing sleepers get camps on
migration because they did sleep (§5.4).

### 5.4 Migration, schema 1 → 2

Runs on a `/tmp` copy first, then live with `.bak` written first. Every pre-migration pip's `name`,
`n`, `colour_idx`, `genome`, `salt` must be byte-identical afterwards and the pip count must match
or the scene **refuses to boot** and the world panel keeps rendering the last good frame (BROADFELL
graft). `burrow` → `camp` at a position hashed from the name inside the Steading ring, tier from
`sessions_seen`; each `moss` row → a `flower` mark credited to its planter beside that camp (a real
mark keeps its owner); `nests` → bonded camps adjacent; `terrain_b64` dropped; `digs` kept as history.
`hollow.py` stays on disk one week; rollback = the world panel importing `hollow` again against
`world.json.bak-YYYYMMDD`.

---

## 6. Verbs

Parsing runs on moderated `chat.jsonl` records. The **exact-token rule** stays: a plain-word verb
matches when the trimmed lower-cased message is exactly the verb, the verb plus one `@name`, the verb
plus one object word, or is `!`-prefixed. **New leading-verb rule (owner feedback, journal 019
addendum):** a message of at most 4 tokens, no URL, whose first token is a verb below, is parsed as
that verb after the stop-words `a an the to at my some on` are dropped, **only if every remaining
token is a known object word for that verb** (place, direction, `@name` where the verb takes one,
`flower|tree|reed`, `hut|tent`); otherwise it is plain chat. So `plant a flower` → plant flower, `go
to the river` → go river, `light the fire` → fire (`light` is an alias), `walk north` → go north,
while `go away` and `plant based` do nothing and a longer sentence never triggers anything. The
message still bubbles as chat. Every refusal prints its reason on the plank for 4 s in amber
(unmissable: the owner's `plant` repeat was refused quietly enough to be missed).

| Word | Effect on screen | Latency | Rate limit |
|---|---|---|---|
| **any message** | First ever: nameless tuft drifts in on the wind for the 3 s hold, splits, pip stands up with name and `#N`, camera arrives first. Otherwise: hop + brighten within 1 frame, bubble after the hold, motif per word chunk (max 6), wakes a sleeper (stands up at its camp, fire relights). Session's first message = **first breath** (pad's first voice, every camp bell west to east, hearth lit, plank line with real time). +0.15 energy | 1 frame; text at +3 s | render 1 per 2 s per user |
| **A / B / C** | Pip walks to that waystone on the Moot; count under the letter = `len(pips standing there)` (`platform_counts()` API kept, reading waystone slots); the leading stone's crowd bounces in the last 30 s; camera MOOT mode. Arrives in 1-3 s | walk starts in 1 frame | 1 vote per user per round |
| **go `<north|south|east|west|river|ford|moot|fell|wood|shore|marsh|orchard|home|@name>`** (aliases `walk`, `head`, bare direction word) | Walks up to 60 cells that way, or to the named place, or to `@name`'s pip or camp, along the coarse BFS route around water and trunks; the camera leads it; wear is laid under every step; footsteps change by ground. `home` walks to the camp. Refusal names the place list | 1 frame | 1 per 5 s per user |
| **explore** *(v1.1)* | Walks to the least-walked cell within 120 cells; a first arrival within 20 cells of a fixed landmark plants a flag in the walker's colour: `the Ford · first reached by @name · day 4` | 1 frame | 1 per 60 s |
| **plant `[flower|tree|reed]`** | At the pip's feet in its colour: a flower (forever, plate on rotation), a tree (grows by real days: sapling → young at day 3 → canopy at day 14, 1.5x on the Orchard Slope, sways, casts a swinging shadow), reeds by water. Never on water, trail, the Moot green or within 4 cells of another person's mark. Trees 1 per user per session, flowers 3 per session, 40 marks lifetime | immediate | as stated |
| **camp** | Pitches or moves your camp to where you stand (rules in §5.3); the old spot keeps its wear. A stranger owns a spot on the map in minute two | immediate | 1 per session |
| **fire** (alias `light`) | Lights a campfire at your camp (walks there first) or, standing on the Moot, lights the hearth for everyone: warm glow kernel, smoke on the wind, crackle; embers when the owner sleeps; cold on sessions the owner is absent | immediate | 1 per 10 min |
| **sow** | Tills a 3x2-cell field beside your camp in your colour (one per person); stages by real days: sprout day 1, green day 3, gold day 7; rain rounds advance a fraction. `harvest` when gold: a feast for every awake pip (chord, hearts), the field returns to tilled and the ticker credits you; `harvests` counts on the plate | immediate | sow 1 per session; harvest when gold |
| **water @name** *(v1.1, WIDE LEA graft)* | Walks to the target's field or tree, advances its growth by 6 real hours (cap one waterer per mark per session), care log `@kai watered your field`: a reason to visit someone else's corner | walk | 1 per 60 s |
| **stack** | Pip walks to the Fell or the river bank, picks up a stone (carried above the head), carries it to the Moot cairn and places it in its colour; `stones` += 1 with the stacker. Land strip: `stone 13 of 20 · the Ford bridge · last by @kai`. One resource, three raisings (§10); never an economy | walk 5-20 s | 1 per 45 s, 3 per session |
| **feed [@name] / pet [@name] / gift @name** | Unchanged semantics across open ground: berry carried, boop with hearts and duet, wrapped gift only at a sleeper's or absent pip's camp; bonds; care log played back on wake | 1-3 s walk | 30 s / 30 s / 1 per target per session |
| **swim** | Only inside river or sea cells: the pip bobs, floats 40 cells with the flow and climbs out at the bank; splash | immediate | 1 per 30 s |
| **sing** *(v1.1)* | 2-bar motif; awake pips within 40 cells echo one bar later; 3+ within 10 s make a chorus and the grass wave doubles | < 0.7 s | 1 per 60 s |
| **wave / sit / dance** | 2-frame emotes from the atlas (`duck` dropped: nothing to duck under outside) | 1 frame | 1 per 5 s |
| **name `<word>` / forget** | Unchanged (nickname never equals a username, shown `Muffin (@sam)`; `forget` purges words, learned, care log; marks stay, credited) | +3 s | 10 min / none |
| **!idea `<text>`** | A notice pinned to the board on the Moot with the requester's name; keepers classify instant / raising next / declined with reason; built as real code by hot-reload | 1 frame | 1 per 3 min, 3 open |
| **!theme `<preset>`** | Retints the UI accent, waystone caps and the beacon; the land keeps its real season palette and creatures keep their own colours | next frame | 60 s global |
| **!help / !stats** | Plank legend 20 s; stats card (camp tier, field, marks, stones, minutes, tier) 10 s in the land strip | 1 frame | 30 s global |
| **!hide / !unhide / !banish / !unbanish / !rename / !pause / !clear / !kill** | Unchanged mod primitives; a hidden pip lies in the grass unlabelled with its plates blanked; `!banish` removes the pip, its camp, field, marks and stones (audit record kept), plaques drop the name; mod actions never name the target on any surface | immediate | broadcaster / moderator badge |

Removed: `dig` (nothing to carve outdoors; `camp`, `sow` and `stack` are the marks); `teach` stays
v2. Verbs remain positive-only: nothing a viewer types can harm another person's pip, camp, field or
mark; no fences, no carving of words (the two griefing surfaces the judges flagged in THE WIDE LEA).

---

## 7. Art direction and frame budget

### 7.1 Direction (the look is `docs/ART.md`'s; these are the constraints it works inside)

**View:** 3/4 top-down. The ground is a plane seen from above at a steep angle; huts, trees, stones
and creatures are drawn with a visible top or roof and a front face, foreshortened so a 14x12-cell hut
footprint carries a taller sprite; everything casts a shadow along the shared sun vector; sprites are
y-sorted by feet so overlap reads as depth. Nothing isometric: no diamond tiles, no 2:1 rhombus grid.

**Palette:** the world region goes daylit while the UI chrome (header, strips, footer) keeps CONCEPT
§5's dark set, so names and the header count stay legible and the bright land pops in the tile.
`ART.md` owns the ground and prop palette; the constraints are: grass luminance never above ~55 % so
labels keep contrast; four season ramps chosen by real date; water and sky-reflection blues distinct
from every creature hue; warm light (fire `#FF6A2B`, window `#FFB347`) reserved for honest sources.
Creature colour comes from the name (`art.creatures.genome`), never from a preset and never a single
default; every person's roof, field border, flowers, plates and minimap dot use that colour.

**Motion rules kept:** something moves every frame, nothing flashes above 1 Hz, walks ease over ~9
frames, event transitions fade over 1 s under the header, no full-frame fills.

### 7.2 What the scene needs from the atlas (`stream/world/art/`, interface only)

| module | function | returns | notes |
|---|---|---|---|
| `creatures` | `render(name, tier, frame, zoom) -> RGBA` and `genome(name) -> {body, accent, ...}` | one frame, foot anchor at the bottom centre | `FRAMES = idle0 idle1 walk0 walk1 hop blink speak sleep emote0 emote1 carry` (the studio-b set plus `carry`); tiers 0-3 at 36 / 48 / 58 / 70 px at 1x, supplied at 0.75x and 1.5x too; deterministic from the name; `shadow(name, tier, zoom)` an alpha blob |
| `buildings` | `render(kind, tier, colour, zoom, lit=False)` | hollow / tent / hut / hut-chimney, waystone, beacon post, notice board, cairn (by stone count), bridge, well, hall, survey stakes, scaffold rows | roofs and doors in the owner's colour; a `lit` variant for the window |
| `props` | `render(kind, stage, season, zoom)` | tree (4 stages), flower (3), reed, stone, flag, bedroll, campfire (3 frames), smoke puff, berry, wrapped gift | planted trees are live sprites (few); the wild Wood is baked (§7.3) |
| `ground` | `paint(layers, season, marks, px_per_cell=4) -> RGB array` and `repaint(bake, region, ...)` | the painted terrain from the cell layers (grass tufts, wildflowers, shore, water base, trails by wear threshold, huts, fields, wild trees, boulders) | the mockup's `paint_terrain` is the starting point; deterministic from the seed and the marks |
| `hud` | fonts and chrome tokens for the plank, plates, chips, time dial, minimap frame | | screen scale only, nothing under 20 px |

Rules every atlas piece must pass (kept from art-rules, applied to the new look): colour from the
name, no single default colour; no Thronglet look-alike (our own silhouette language; `ART.md` states
it); one row in `pips` per creature, no multiplication; no morality; no animate non-person anywhere
in props or ground (no birds, fish, insects, livestock); every frame deterministic and cached; a
review sheet (`creature_sheet.png`, a buildings sheet, a props sheet on each season's grass) checked
against `ART.md`'s checklist before go-live and after any atlas change.

### 7.3 How the frame is made (painted once, modulated per frame)

The cave rendered a 320x110 cell grid and upscaled it 4x with NEAREST. That path is proven cheap but
its look is blocky, and the owner chose a painted top-down mockup and asked for massively improved
art. So the **display** is painted at screen resolution once and cropped per frame, while the
**simulation and every per-frame effect stay at cell resolution** and use the proven `np.repeat` x4
path where nearest upscaling is invisible (soft light fields):

1. **Ground bake** (`$RUN_DIR/bake/ground-<seed>-<season>-v<bake_ver>.npy`, uint8 3840x1760x3,
   20.3 MB, memory-mapped): `art.ground.paint()` renders the whole map at 4 px/cell for the current
   season with every mark that lives in the ground (trails by wear threshold, huts by tier, fields by
   stage, wild Wood, boulders, shore). Built in a **background thread** at first boot (~3-6 s,
   numpy releases the GIL) and cached on disk, so a hot-reload boot loads it in ~20 ms. A mark change
   repaints only its region (index writes into the memmap, microseconds to a millisecond) and bumps
   `bake_ver`. The other three seasons are baked lazily in the same thread. Until a bake exists the
   scene shows the cell-res biome colours x4 nearest (the cave's path) so the land is never blank.
2. **Viewport crop:** `bake[y0:y1, x0:x1]` at the camera's bake-pixel offset; at 0.75x / 1.5x the
   crop is resampled to 1280x440 (BOX / BILINEAR, ~1-2 ms).
3. **Modulation field** at cell resolution, one `float32 (110, 320, 3)` array per frame (0.75x:
   147x427): daylight tint by real hour with the 0.55 floor x cloud shadow (blob slice, 0.85) x wind
   bands (two travelling sines, ±8 % on grass cells only) x **shadow layer** (the `caster` mask
   shifted by the sun vector in cells, 0.8 where a hut or wild tree throws its shadow, so every shadow
   on the land swings with the hour without a single blit) x water sparkle (scrolled pattern on water
   cells, +) x tide wet band (shore cells within the tide offset, 0.9) x rain darkening x fog haze.
   Converted to fixed-point `uint16` (x256), `np.repeat`ed x4 both axes and multiplied into the crop
   with a shift, one integer pass over 1.7 M pixels.
4. **Glow buffer** after dusk only: additive kernels at screen scale for fires, lit windows, the
   beacon and awake pips (existing slicing code, larger kernels).
5. **Live sprites**, y-sorted: creatures with their sun shadows, planted trees (few), campfires,
   smoke puffs, banners on the waystones, carried items, hearts, the survey stakes and scaffold of a
   raising; **particles** (rain, leaves, sparkle, snow) as index writes.
6. `Image.fromarray` → RGBA `size`; the text layer draws everything with letters on top.

### 7.4 Per-frame budget (target at 20 creatures with a moving camera)

| pass | 1x, 20 pips | 0.75x wide |
|---|---|---|
| viewport crop from the memmapped bake (1280x440x3 copy) | 0.4 ms | 0.9 (1707x587) |
| resample to 1280x440 | 0 | 1.8 (BOX) |
| modulation field at cell res (tint, clouds, wind, shadows, water, tide) | 0.5 | 0.8 |
| `np.repeat` x4 + fixed-point multiply into the crop | 2.5 | 2.5 |
| glow buffer after dusk (30 kernels) | 0.5 | 0.5 |
| live sprites + shadows, y-sorted alpha blits (~50 in view) | 1.2 | 1.2 |
| particles | 0.3 | 0.3 |
| `Image.fromarray` | 0.3 | 0.3 |
| minimap every 10 frames (amortised) | 0.1 | 0.1 |
| **scene total** | **~5.8 ms** | **~8.4 ms** |
| text layer (labels, bubbles, plates, plank, time dial, minimap paste; cached strips) at 20 labels | 2.0 | 2.0 |
| **frame total** | **~8 ms** | **~10.5 ms** |

Reference points: the cave measured 1.5 ms at 20 pips and 2.7 ms at 60 (WORLD_API §7); the fixed
costs here are the full-resolution multiply and the crop, which do not grow with pip count. These are
**estimates**; the 3 h mock-frame gate (§14) times steps 2-4 on this Mac before anything else is
built. **Gate:** scene average under 12 ms at 0.75x with 60 test pips in test mode after every reload
(self-test); `budget_ms 24` unchanged. **Fallback if the gate fails:** bake at 2 px/cell (5 MB per
season) and BILINEAR x2 per frame (softer, ~2 ms cheaper), or run the modulation at half resolution.
**Degrade ladder** (scene ms averaged over 30 frames): > 14 cloud shadows off and wind bands static;
> 18 glow off, then the shadow layer; > 20 labels-on-speak, plates stop rotating; > 24 bubbles single;
> 28 pin the zoom at 1x; one step back per 300 clean frames; last-good-frame on any error with one
stderr line. The compositor's frame-time guard stays as the last resort and is designed never to fire
here. Whole-map operations in the per-frame path are forbidden by art rule and asserted by the gate.

### 7.5 QA gates (every round, plus before the swap)

1. **Tile at four hours x four seasons:** render 00:00 / 06:00 / 12:00 / 18:00 in spring, summer,
   autumn and winter at 0 awake and 3 awake (test mode); assert for each: the header count reads;
   mean luminance of the tile's world band at 00:00 ≥ 0.5 x the same season's noon mean (the 0.55
   floor guarantees this by construction; the gate catches a regression); ≥ 60 % of world-band
   pixels above 0.12 luminance at midnight (the cave failed a 10 % gate at 3.9 %); no name drawn
   except camp plates from real rows.
2. **Contrast sweep:** every creature hue the genome can produce (24 stops) over the brightest grass,
   sand and gold-field of each season ≥ 4.5:1 for its label with the stroke and chip; a failing hue
   gets a darker chip, never a different colour.
3. **Camera:** a 60 s recorded pan judged at 320x180 and 720p through the same ffmpeg settings;
   frame-to-frame motion ≤ 4 screen px in DRIFT; no cut inside a round; zoom changes only at rest.
4. **Pathing:** 60 test pips given random `go` targets for 5 min, assert zero stuck (the 3 s detector
   never fires twice on one pip) and zero in-water positions.
5. **Budget:** 0.75x / 1x / 1.5x with 60 test pips under `/tmp`, scene avg < 12 ms at 0.75x; the bake
   thread never blocks a frame (frame max during a bake < 24 ms).
6. **Honesty** (§12) every frame; **migration** on a copy (§5.4); **HLS probe** as today; the
   **art review sheets** (§7.2) on each season's grass.

### 7.6 Art-rules changes (`docs/art-rules.md`)

Rule-1 sentence becomes *"Every name on this land is a real person who chatted. The wind is just the
wind."*; the "darkness means nobody" lines and §4's cave texture rules are replaced by: nothing moves
itself except a real person's pip, everything else is moved by wind, water or the sun; no birds,
animals, fish, insects, NPCs, figures or mascots (the keeper is a lantern on a post, never anything a
viewer could read as flying or walking); nature is declared, not counted; no fog of war (the minimap
shows the whole map; walked / unwalked is a real record); no isometric diamond tiles, villagers,
resource counters or franchise vocabulary; no whole-map operation in the per-frame path; no decay of
any mark; fire and light only where a real person is or was tonight. §3's sprite-shape tests (angular
side-view bodies, no round faces, 2 px eye) are **superseded by `docs/ART.md`'s checklist**; §3's
principles (colour from the name, no default colour, no look-alike, no multiplication, no morality)
stay and are restated there.

---

## 8. Layout (1280x720): the full-bleed land (2026-09-26, journal 032 / 034; supersedes the HUD pass, journal 028 / 030)

The owner, 18:35: *"Never put cringey ai text onto the stream. 'no camera, no mic, no fake viewer' is so
unnecessary... Seriously change that, make the actual world the main viewable thing. Go crazy dude."* And
19:28: *"Remove the bottom part of the screen where chat is and just have the main thing."* ADR-000's
principle (nothing fake, ever) is unchanged; its on-screen recital is gone. The land IS the frame: `world`
is the ONE region (0, 0, 1280, 720). The header band, the land strip, the chat log, the vote card and the
minimap are gone as panels; every fact a stranger needs is an object in the world the camera can frame,
in ONE wood material, plus the plank (the land's single voice, blank at idle). Kick prints the channel
name, LIVE and the viewer count beside the player; the tint, cast shadows and the moon are the clock. The
320x180 directory tile is the whole frame, so the sign's AB 56 is 14 px there and reads.
`stream/layout.py` changed (regions removed), so this ships as ONE relay-held compositor child restart
(`scripts/deploy.sh`) with every changed file copied together, never as a hot-reload of single panels.

```
 +-----------------------------------------------------------------------------+ y=0
 | [plank (16,16): one HN Medium 22 row on wood, 5 s, blank at idle]           |
 |                                                                             |
 |                  +-----------------------------------+                      |
 |                  | type A, B or C               1:27 |  <- MOOT BOARD, stacked |
 |                  | A  expedition to the Ford         |     (top rail: text at  |
 |                  | B  harvest day                    |      0 standing, timer) |
 |                  | C  wind                           |                         |
 |                  +== fuse cord ======================+                      |
 |                        A      B      C           <- AB 56 letters + counts    |
 |                        0      1      0              over the three stones     |
 |                             @kai_dnb                                        |
 |        [beacon]     [hearth]     [cairn + its plate `3 have walked here`]   |
 |                                                                             |
 |                        +---------------------+                              |
 |                        |    SAY ANYTHING     |  <- the sign at the spawn     |
 |                        +--+---------------+--+     (AB 56 on wood, posts)    |
 +-----------------------------------------------------------------------------+ 720
```

| Object | Where | What it says |
|---|---|---|
| **plank** | canvas (16, 16), HN Medium 22 cream on wood, one row, `PLANK_MAX_W` 820 | the land's single voice, newest person line wins, 5 s then a 0.5 s fade, sticky lines never fade, BLANK at idle. `chat is reconnecting…` (amber) > person lines (`@kai stands at B · harvest day · closes in 1:27`, `try: go river`, `@kai left B · that vote is dropped`, `someone new walked in`, `that's you, @kai`, `@kai walked in · 4 have walked here`, `next: camp · plant a flower`, `stack · not yet · try: go river · plant a flower · camp`, `!stats`) > world events (`new round · type A, B or C`, `the cairn is named`, `the Coast is open`). Never a vote state, a result sentence, a raising notice, a caption, a clock |
| **SIGN** | world-anchored at `MOOT_LAYOUT["sign"]` = Moot + (0, +46) cells, AB 56 cream on wood <= 480x70 with two posts | `SAY ANYTHING`: the one instruction, at the spot where it comes true; carved blend once anyone is awake |
| **waystone letters** | AB 56 (AB 40 at 0.75x) 128 px above each stone, count Menlo 22 under each | the leader in the accent; `0 +1` while a voter walks; up to 3 names else `4 standing`; a glyph fades to 40 % while a settler's body crosses it |
| **MOOT BOARD** | one wood board centred on the letters' x span, bottom 6 px above them (place_up 4 steps, culled with the stones), STACKED | top rail 30 px: `type A, B or C` (Menlo 20, only at 0 standing) left, the timer Menlo Bold 24 right (cream / amber < 30 s / red < 10 s / amber `closing` once the deadline passed and the manager has not shipped: never a frozen 0:00); one 34 px row per option `[AB 28 letter][HN Medium 22 title WHOLE up to 560 px]`: every menu title fits (the longest, `chaos · expedition to the Shore`, is ~320 px; only a 60-char `!idea` title can be cut), `→` never reaches the board (HelveticaNeue has no arrow; `hn_safe()` maps it to `·`, rounds.py writes `chaos · …`); the leading row on a band of the accent, its letter accent, its title cream, the others burnt dim; a 4 px fuse cord along the bottom rail shrinking left to right with an ember, gone while `closing`, full during the ship hold (winner lit, losers dimmed 40 %, a 1 s white flare; a land pick lights muted amber). Nothing between rounds. No result prose. The compositor's board check asserts, per drawn frame, the lit letter == the unique max standing count and every drawn title == `world.board_title(option title)` |
| **Moot marker** | Menlo 22 on wood at the frame edge toward the stones | `◂ A B C · 1:27` only while a round is open, anyone is awake and no stone is in view |
| **labels / bubbles** | Menlo 20 on a contrast chip / Menlo 22 bubble (max 408 px, 3 lines, 8 s, one per pip) | the person's own name and words verbatim (the on-frame echo of chat now the log is gone); a speech line with no room anywhere rides the shared bottom line IN THE SAME BUBBLE STYLE (never dim text over grass) |
| **plates** | HN Medium 22 on wood, ONE at a time, whole inside the frame, 5 s rotation | `@sami's tent · night 4`, `flower · @moss_m · today`, the cairn's `3 have walked here · 2 more and the cairn is named` (pinned 10 s after every hatch and during the DRIFT Moot dwell), a raising's site plate; a camp plate rotates only while its owner is awake or the DRIFT stop pins it |
| **edge arrows** | Menlo 22 on wood at the nearest edge | `@kai · 210 paces →` for awake pips outside the window |
| **beacon / hearth / cairn** | the scene's sprites | the keeper presence is the beacon, lit or dark, no words; the cairn grows stone by stone |

Zero explainer copy: `compositor.BANNED_COPY` is the owner's rule as a per-frame gate over every string the
world panel writes itself (`ai`, `keeper(s)`, `on duty`, `build(s)`, `show`, `live`, `version`, `fps`, `ms`,
`viewer(s)`, `watching`, `camera`, `mic`, `fake`, `honest(y)`, `surveying`, `awake`, `longgrass`, `leads`,
`tied`, `reverting`, `picked`, `failed`, a `vN.N`, `day N`, a wall clock outside the timer forms). A person's
own words (labels, bubbles) are theirs and excluded. `hollow.py` / `pips.py` stay on disk for the rollback.

Removed regions (`layout.REMOVED_REGIONS`; a module still registering one is dropped in words, never a boot
error, so a stale `colony.py` / `header.py` / `chat_log.py` left in a snapshot paints nothing): everything
from the living-world pivot and the HUD pass, plus `header`, `header_center`, `header_right`, `land`,
`chat_log`. Telemetry lives in the compositor log, `state.json` and `scripts/status.sh`; the moderation
record lives in `chat.jsonl`, not on screen.

Camera: `camera.py` SCREEN (1280, 720), CROP_PX 1707x960 / 1280x720 / 853x480, `HUD_TOP_PX` 54 (the plank
row; the panel refreshes `hud_boxes` from what it actually drew, an empty list when the plank is blank), no
bottom box; `STONE_TOP_PX` 274 = the letters (128) + 6 + the stacked board (138) + 2, so MOOT / FOLLOW
framing never clips the board under the plank (self-test 4e). Frame budget at 60 test pips / 0.75x: scene
avg < 12 ms (steading self-test C2). Compositor `WORLD_BAND` (0, 720). Copy for every interaction is in
`stream/panels/world.py` (plank, board, sign, plates) and `stream/chat_bridge.py` (acks, hints).

---

## 9. Audio (numpy, 1600 samples per frame, engine unchanged)

| Layer | Design | Level |
|---|---|---|
| **Wind bed** (replaces drips as the constant layer) | Filtered noise, cutoff and level follow the sim wind (chat rate base + weather), gusts as 2-4 s swells, panned slightly with the wind direction | -28 dBFS |
| **River / shore** | Band-passed noise burble, level `1 / (1 + d / 40)` where `d` is the camera's distance in cells to the nearest water cell; shore wash near the sea with a 6 s swell | -32 / -34 dBFS |
| **Camp bells** | Each camp has a wind-bell pitched by the owner's name hash (the existing pluck degree); gusts ring bells in or near the window softly; first breath rings every bell west to east once; homecoming rings the returner's three times | -30 dBFS |
| **Fire** | The existing crackle, only near a lit camp, the hearth or a bonfire in view | -34 dBFS |
| **Rain / thunder** | `_rain_block` during rain; one filtered burst per gale round at most, never above -20 dBFS | -34 dBFS |
| **Pad** | Voices = awake count (0 = wind, water and bells only), under the wind; mode major in spring/summer, minor in autumn/winter; first voice fades in on first breath | -24 dBFS |
| **Pip voices** | Karplus-Strong motifs by name hash, hatch rise, wake/sleep thirds, tier-up sweep, feed pop, pet duet, gift two-note, vote blip rising per vote, round-close ticks: unchanged | as today |
| **Footsteps** | Two noise-burst timbres by the cell under the pip: grass hush, trail click, ford splash (through the drip resonator), sand crunch, marsh squelch; rate-limited | -26 dBFS |
| **New stings** | tuft landing (reuses `seed_land`); tent pitched (cloth flap + peg tap), hut raised (three soft hammer ticks); sow (three earthy taps), harvest (the major chord chime); stone pick-up and drop (two low thuds), stone on the cairn (a click; the naming stone a short bell); raising progress (a soft hammer tick every 2 s while it fills), raising ship (chime + rumble, exists); land opening (chime + rumble); sunrise and sunset (a single soft bell at the real times); `expedition` (N soft footsteps as a rhythmic bed); camera retarget = silence | -22 to -26 dBFS |

Master unchanged (-18 dBFS integrated, tanh limiter, -6 dBFS ceiling). Nothing sampled; no birdsong,
insects or crowd noise (nothing implies life that is not real). Pluck auto-mute above 10 msg/min stays.

---

## 10. Keepers in fiction: the beacon, raisings and land opening

The keepers stay AI agents labelled as exactly that and never appear as a figure. **The beacon**
replaces the cave lantern on a chain: a lantern on a post at the Moot, reusing `lantern_state()`: lit
with a 0.25 Hz flicker on a fresh heartbeat (< 120 s), dark when no keeper is on duty, swinging at
0.5 Hz during a macro build, flaring 1 s with the chime and low rumble on a ship, one red flicker on a
failure with the first three traceback lines in the keeper strip for 20 s. Its lit state is an amber
dot at the Moot on the minimap, visible from anywhere on the land.

**Raising (replaces carving).** The stone ladder 20 / 60 / 150 cumulative stones queues keeper
raisings, the Age-of-Empires moment of a structure rising from a stockpile: the **Ford bridge**
(opens the far bank to walkers), the **well** on the Moot (a place label, water sparkle), the
**hall** by the Moot. When a raising lands, survey stakes appear at the site, then over the build
window the atlas's scaffold rows and the finished sprite are revealed bottom-up at most 1 Hz (the
existing `carve_order` stepping on a reveal mask) while every awake pip turns to look; the plaque
credits the top three stackers and the date: `the Ford bridge · raised v0.7.0 · stones by @kai @sami
@atleastonce · 3 Oct`. Cap: one resource, three raisings; anything further is v2 and must survive the
art rules.

**Land opening (v1.1).** Head-count milestones 10 / 25 / 50 open a 320x440 strip (§4.1), credited
on the notice board: `the Coast · opened by @kai's arrival · v0.8.0`. Milestones 3 and 5 name the
cairn and add a stone ring around the Moot hearth. If no keeper is on duty at a milestone: `land
reached · keepers will open it next session`.

`!idea` notices pin to the board on the Moot; `agents/duty.py` classification is unchanged (instant =
a waystone option next round; raising next = macro; declined with reason). The 017 trust boundary
holds: keeper builds change only the world (biomes, marks, verbs, weather, events, cosmetics, atlas
pieces) under `stream/scenes/`, `stream/world/`, `stream/panels/`; never the repo, pipeline, auth,
moderation or honesty code; idea text is data, never executed; a build that adds an animal, an NPC,
hunger, death, decay, a fog of war, fences, carved words or any franchise look is reverted. Ticker:
`the keepers are AI agents. they raise this land live, from your !ideas, and you watch it go up.`

---

## 11. The collective: rounds as world events, plus emergence

The RoundEngine lifecycle is untouched (`open` 0-150 s → `closing` → `ship` 5 s → next). Voting is
embodied at the three **waystones** on the Moot (standing stones with letters in AB 56 above them);
pips walk to them; the tally is the crowd (`platform_counts()` API kept, reading waystone slots);
the camera frames the Moot in the last 30 s if anyone stands; at 0:00 the event lands on the whole
land in one second. Zero votes: `nobody voted. the keepers picked B.` on a fresh heartbeat, else
`nobody voted. the land picked B itself.`

| param | values | what happens (3 min unless once) |
|---|---|---|
| `weather` | rain / wind / fog / clear | rain sweeps west to east with the camera easing to 0.75x, swells the river, advances fields and trees a fraction, puddles in trails; wind speeds the grass bands, flattens them in gusts and blows leaves and smoke; fog hazes the far ground and camps glow through it; clear. Overrides the Markov chain for the window |
| `expedition` | to the Ford / the Fell / the Shore / the Wood | every awake pip walks together to the landmark and the camera follows the herd at 0.75x; a cairn stone is placed at arrival with the walkers' names (the Migration idea as a round outcome) |
| `bonfire` | now | a big fire on the Moot, everyone gathers and sways, feast chord, hearts; lights the hearth |
| `harvest day` | now | every gold field is harvested at once and everyone is fed; sowers credited on the ticker |
| `raising day` | on | stones stacked count double for 3 min (THE COMMONS graft) |
| `colony rule` | follow / scatter / huddle / free | unchanged semantics in 2D |
| `light` / `music` | 8 presets / tempo, pattern | unchanged (`light` themes the UI accent and waystone caps, not the land) |
| `anarchy` | hour, rare | bare direction words from anyone steer every awake pip together in 2D, each move attributed on the ticker |
| `chaos` | roll | unchanged |

**Emergence, from real inputs only:** wind speed is chat rate (a storm of 200 people typing is a gale
the whole land shows and hears; it doubles as the bubble-density fallback); desire paths from real
footsteps, drawn into the ground bake at the wear thresholds so the Steading's roads are a heat map
of where people actually went; trail naming when 3+ people walk the same route in a session (`the
moot-to-ford road · worn by @a @b @c`); the cairn naming at 3 distinct stackers; a village layout
nobody designed (regulars near the waystones, wanderers across the Ford once the bridge stands);
chorus (v1.1); word spread with attribution (v2); bonded camps drawing adjacent with a shared trail;
homecoming bells; the nightly board (`last night: @sami stacked 3 stones · @kai walked the farthest ·
1 arrived · 2 fields went gold`); credits as a camp-to-camp survey with names and minutes; and the
shadows swinging round during a long session, which everyone sees at once.

---

## 12. Honesty and moderation

The hold, filters and mod primitives are unchanged (`WORLD.md` §11 items 1-9 apply in full). The new
nature rule and the mark rule are added and made mechanical:

- **The rule:** *Every name on this land is a real person who chatted. The wind is just the wind.*
  Honesty is about WHO; wilderness is not emptiness. **Nothing moves itself except a real person's
  pip; everything else is moved by wind, water or the sun.**
- **Nature is declared, not counted.** Sun, moon, seasons, wind, cloud shadows, water, tide, weather,
  wild flowers, the wild Wood and the growth of planted things are "world", listed as such in the
  ticker honesty line: `no camera, no mic, no fake viewers. every name on this land is a real person
  in chat. the wind is just the wind.` A viewer is never led to read weather as people.
- **Every animate thing is a pip** created only in the chat-ingest path from a moderated record;
  the self-test asserts every frame `awake == distinct real chatters whose record cleared the 3 s hold
  in the last 20 min` (a chatter still inside the hold is a nameless tuft, not awake: the header ticks
  at the hatch, §3.1, and reads `SAY ANYTHING` over a first message's hold while the chat log says
  `someone is arriving...`) and `len(pips) == distinct chatters ever minus banished`; the
  HonestyMonitor flags any moving sprite without a key, and the world panel asserts per frame that
  no string it drew carries a raw hidden, blocklisted or quarantined username.
- **Every mark has provenance:** camp, fire, field, flower, tree, reed, stone, flag and path cell
  carry an owner key that must exist in `world.json["pips"]`; the monitor asserts every 5 s that no
  mark has an owner without a chat record; `wear` is incremented only by `Behaviour._move` under a
  real awake pip and the monitor checks that the wear added this frame equals 8 x (real pips that
  entered a new cell) + neighbour spill; the survey camera, the weather and test pips never write
  wear or marks; the ground bake is repainted only from those records.
- **Camps, plates, plaques** resolve to pip rows with real sleep records and real `last_seen`;
  sleepers never walk, vote, speak, stack or ring their own bell (the wind does); a window is lit
  only where the owner is or was tonight; the hearth burns only if a real person lit it this session;
  the beacon only on a fresh heartbeat.
- **The minimap hides nothing** and its "walked" fraction is a `len()` over cells near real
  footsteps; there is no fog of war in the world view either.
- **The camera never frames emptiness as if someone were there:** DRIFT visits only real marks and
  three fixed natural points, and the plank names what is in view; FOLLOW requires a real entity;
  waystones at 0 awake stand empty.
- **Every number is a `len()`:** awake, asleep, settled, camps, fields, trees, stones, `17 have
  walked here`, `4 % walked`, `day 6` (distinct sessions), waystone tallies, plaque names. No sample
  string is drawn.
- **Nameless until the hold** (the tuft), `builder #N` on a blocklist hit on every surface (label,
  plate, plaque, plank, board, roof colour still from the real name), a user hidden inside the hold
  blows away, three strikes lay the pip down unlabelled for the session, no impersonation in
  nicknames, per-user mod actions never name the target, `!banish` reverts every mark. Verbs are
  exact-token or the leading-verb rule on ≤ 4 tokens with known object words only; ordinary
  sentences never trigger anything.
- **Absence is never punished:** wear never decrements, trees never die, fields never rot (gold
  waits), camps are never dismantled, fires go to embers, no hunger, no blaming copy. A keeper ship
  that adds decay, animals, NPCs, hunger or death is reverted.
- **Chat is data** (journal 017): `go north` moves a pip, never the agent; keeper builds from `!idea`
  stay inside the world sandbox.
- Viewer count is the real API value or `--`. Test pips only under `KL_TEST_PIPS` in a `/tmp` run dir
  in test mode, never persisted.

---

## 13. Build order (agent-hours) and the v1 cut

**Gate before the build (3 h, THE COMMONS graft; the owner asked for renders first in journal 020):**
`terrain.py` + `nature.py` + the atlas as it stands render six 1280x720 frames from the real modules,
not the mockup scripts: dawn, noon and 23:00 at 0 awake and 3 awake (test mode), in the current
season, plus the 320x180 tiles, **and time the per-frame path (§7.3 steps 2-4) on this Mac**. The
owner gives a warm/cold verdict; if 23:00 reads cold, flip `world_day` to `"hour"` and re-render
before anything else is built; if the timing misses 12 ms at 0.75x, switch to the 2 px/cell bake
before anything else is built. Palette and frame cost are the whole bet.

| # | Work | Hours | v1 |
|---|---|---|---|
| 1 | `stream/scenes/steading.py`: bake pipeline (thread, memmap cache, local repaint, `bake_ver`), viewport crop and resample, modulation field (tint with floor, clouds, wind, shadow layer, water, tide, rain, fog), fixed-point multiply, glow after dusk, y-sorted live sprites, particles, zoom crossfade, degrade ladder, last-good frame; ~450 of `hollow.py`'s lines carry over (ingest, history, persist, honesty check, entities, stats, command dispatch) | 7 | yes (crossfade v1.1) |
| 2 | `stream/world/terrain.py`: seeded generation from the mockup's method (elevation, moisture, sea, site search, river trace and carve, Ford), biomes, convex obstacles, `passable` / `cost` / `caster`, coarse BFS grid, places registry, PNG review | 4 | yes |
| 3 | `stream/world/nature.py`: wind field from chat rate, cloud blobs, sun vector and tint by hour with the floor, tide, Markov weather chain, seasons by date and hemisphere, growth by real days | 2.5 | yes (Markov chain v1.1: rounds only in v1) |
| 4 | `stream/world/camera.py`: state machine, 2D lead room, spring, caps, zoom hysteresis, edge-arrow data, DRIFT loop, minimap data, persistence | 3 | yes |
| 5 | `stream/world/behaviour.py`: 2D targets with easing, BFS routes + slide rule + 3 s stuck detector, wander with Moot gravity, camps instead of burrows, waystone slots, carry (berry / stone), tuft on the wind, sleep / wake / credits semantics preserved | 5 | yes |
| 6 | `stream/world/state.py` schema 2 + `stream/world/land.py`: wear, marks, camps ladder, fields, stones / ladder, raisings, land strips, weather state, camera, `bake_ver`; migration on a copy with the identity / count guard | 4 | yes |
| 7 | Atlas integration: wiring `stream/world/art/` into the scene (per-zoom sprite cache, anchors, shadows, `ground.paint` / `repaint`, `lit` windows, campfire frames), the review sheets on grass | 2.5 | yes |
| 8 | `stream/panels/world.py` text layer: camera transform with culling, plank + land line + time dial, plates / plaques / place labels, waystone rows, edge arrows, minimap with walked fraction, contrast chip | 4 | yes |
| 9 | `stream/chat_bridge.py` verbs: leading-verb rule with object tables, `go`, `plant <obj>`, `camp`, `fire`, `sow` / `harvest`, `stack`, `swim`, `home`, refusals in amber; `explore`, `water`, `sing` v1.1 | 3 | yes (v1.1 items later) |
| 10 | `stream/rounds.py`: MENU weather / expedition / bonfire / harvest day / raising day / colony rule / light / music / anarchy / chaos; waystone tallies; effects | 2 | yes |
| 11 | `stream/world/keepers.py`: beacon, notice board, raisings via reveal masks on atlas sprites, land-opening strips with a background bake | 2.5 | beacon + notices yes; raisings and strips v1.1 |
| 12 | `stream/audio.py`: wind, river / shore, bells, fire beds; footstep timbres by cell; new stings; sunrise / sunset bell | 3.5 | yes |
| 13 | `stream/panels/colony.py` (the land), `header.py` copy (`SETTLED`), `keeper.py` copy, `readout.py` flags, ticker line | 1 | yes |
| 14 | QA: honesty extensions (marks, wear sum, camera, minimap), tile gate 4 hours x 4 seasons, contrast sweep over 24 hues, pathing test, budget at three zooms with 60 test pips, bake-thread frame-max test, camera clip, migration test, HLS probe, art sheets | 4 | yes |
| 15 | `docs/art-rules.md` rewrite, `WORLD_API.md` update (`SteadingScene`, camera, atlas interface, new events), `WORLD.md` banner | 1 | yes |
| | **Full concept (incl. the 3 h gate)** | **52** | |
| | **v1: a complete alive show** (rows 1-8, 10, 12-15, the v1 parts of 9 and 11, the gate) | **~40** | 3 parallel agents, about a day and a half |
| | **v0 preview** (the gate's modules made live: bake, camera DRIFT + FOLLOW at 1x, tint / wind / clouds / shadows, camps from migration, hatch, `go`, existing verbs; no new verbs, no fields, no rounds re-skin) | **~12** | 2 agents, the same evening: the VOD shows the cave opening onto the land while the rest ships as keeper builds |

**v1 contains:** the painted map with the honest minimap, all of §2.2 alive at zero, the camera with
all five modes and three zooms (crossfade as a luminance dip until v1.1), 2D behaviour with pathing,
camps with the compressed ladder, `camp` / `fire`, trails that never fade and repaint the ground,
`plant flower|tree` growing by real days, `sow` / `harvest` with fields in the owner's colour,
`stack` with the cairn and the ladder readout, `go` / `home` / `swim` and the leading-verb rule,
`feed` / `pet` / `gift`, embodied votes at the waystones, the new MENU, wind / water / bells /
footsteps audio, the land strip, the time dial, honesty, migration, the QA gates. **v1.1 by keeper
ships on air:** `explore` + flags, `water @name`, `sing` + chorus, the Markov weather chain, the zoom
crossfade, the first raising landing (the ladder needs 20 stones first), land-opening strips, trail
naming, nightly board copy, leaf and snow particles. **v2:** word spread, `teach`, chatter-named
places, tides on the Coast.

**Cut list (first to go):** swim → raising day → harvest day (fields still grow) → 1.5x CLOSE (pin at
1x) → the 0.75x wide zoom (pin at 1x, edge arrows carry the rest) → Markov weather (rounds only) →
season particles → the tide band → camp bells → footstep timbres. **Never cut:** the moving camera,
the 0.55 night floor, alive-at-zero wind / clouds / shadows / water, the honest minimap, the nameless
tuft until the hold, filtered names everywhere, the honesty and mark-provenance assertions, the tile
gate, graceful degrade, the compact chat log, `world.json` in the isolated run dir with backups and
the migration guard, absence-never-punished, no animate non-persons, no fog of war.

### Files: unchanged / changed / new

| status | file | note |
|---|---|---|
| unchanged | `stream/compositor.py`, `stream/relay.py`, `stream/state_store.py`, `stream/layout.py`, `stream/moderation/*`, `stream/world/honesty.py` core (+ mark, wear and minimap checks), `stream/panels/chat_log.py`, `countdown.py`, `ticker.py` (line), `scope.py`, `agents/duty.py`, `scripts/*` | geometry, plumbing, moderation |
| changed | `stream/world/behaviour.py` (~60 % kept: entity state machine, hold timing, speak / hop / blink / curl, sleep / wake, care, credits; ~250 lines rewritten for 2D), `stream/world/state.py` (schema 2, migration), `stream/world/keepers.py` (beacon, notices, raisings, strips), `stream/panels/world.py` (camera-aware text layer, time dial, minimap), `stream/panels/colony.py` (the land), `stream/panels/header.py` / `keeper.py` / `readout.py` (copy and flags), `stream/chat_bridge.py` (verb table + leading-verb rule, ~180 lines), `stream/rounds.py` (MENU + effects, ~90 lines), `stream/audio.py` (beds + stings, ~220 lines), `docs/art-rules.md`, `stream/WORLD_API.md`, `docs/WORLD.md` (banner) | |
| retired | `stream/world/pips.py` (the angular 4x sprite generator) is replaced as the creature source by `stream/world/art/creatures`; it stays on disk with `hollow.py` for the rollback week and its `genome` / `salt` fields stay frozen in `world.json` | |
| new | `stream/scenes/steading.py`, `stream/world/terrain.py`, `stream/world/nature.py`, `stream/world/camera.py`, `stream/world/land.py`, `stream/world/art/*` (from the art workflow), `docs/ART.md` (from the art workflow), `docs/OPENWORLD.md` (this), `docs/decisions/ADR-006-open-world.md` | `hollow.py` stays on disk one week as rollback |

---

## 14. Deploy

Because `layout.py` is untouched, LONGGRASS lands by **hot-reload while PIP HOLLOW is on air**:

1. Run the migration on a `/tmp` copy of the live `world.json` (§5.4); the guard must pass.
2. Pre-bake the ground for the current season into the live run dir's `bake/` from the migrated copy
   (~3-6 s, offline), so the booting scene loads it in ~20 ms and no frame waits on a bake.
3. Copy `stream/world/*.py`, `stream/world/art/`, `stream/scenes/steading.py`, `stream/panels/world.py`
   and the copy-changed panels into the live snapshot. The HotReloader executes the world modules
   fresh, rebinds the package, and re-executes every panel that mentions `stream.scenes` (WORLD_API
   §9); the world panel now imports `stream.scenes.steading` and creates a `SteadingScene`, which
   writes `world.json.bak-YYYYMMDD`, migrates in place, restores sleepers at their camps and an owner
   who chatted inside the awake window at their saved x / y with the sleep timer counting from their
   real last message; the camera resumes from the persisted position. The relay never sees a gap; the
   VOD records the cave opening onto the land, announced by the keepers on the ticker as
   `SHIPPED v0.6.0 · Longgrass`.
4. Fallback if the reload trips the self-test gate: `scripts/swap-build.sh live-snapshot-v4` (freeze,
   compile, honesty gate, title, `stop.sh` → `start.sh` inside Kick's ~100 s window, same VOD; the
   path used for the cave in journal 019, which also carries the 017 secrets scrub). Never a bare
   compositor restart while live; the owner is told before either path (memory rule: never restart
   the live stream without asking).
5. Title set through the OAuth app to the §1 title. Everything after (v1.1 verbs, raisings, land
   strips, atlas improvements) ships as keeper macro-ships on air, which is the content the fiction
   promises.

Rollback: the world panel re-imports `hollow` and `world.json.bak-YYYYMMDD` is restored; both stay
available for a week.

---

## 15. Risks

| Risk | What this spec does about it |
|---|---|
| **The per-frame cost of a painted full-resolution viewport is estimated, not measured** (the cave's 1.5 ms was for a 4x nearest grid) | The 3 h gate times the crop, modulation and multiply first; fixed-point integer math; fallback to a 2 px/cell bake with BILINEAR x2 or a half-res modulation; the degrade ladder pins the zoom; `budget_ms 24` and last-good-frame stay |
| **The ground bake blocks a frame** (a season repaint is seconds) | Bakes run in a background thread and are memory-mapped from disk; a boot without a cache shows the cell-res biome fill until the bake lands; the QA gate asserts frame max < 24 ms during a bake |
| **Creature labels on bright grass and gold fields** | Grass luminance capped near 55 %, a stroke plus a 60 % dark chip under every label, the 24-hue contrast sweep per season; a failing hue gets a darker chip |
| **Night reads cold at the owner's hour** (evenings are when he watches; the cave's darkest complaint) | 0.55 luminance floor, blue not black, moon glitter on water, honest warm windows and fires, the 4-hours x 4-seasons tile gate, the mock-frame verdict before the build, and the `world_day: "hour"` switch as the disclosed lever |
| **The art bar** ("massively improved") is set by another workflow and may land late or not match the scene's interface | §7.2 states the interface; the scene is built against it with the studio-b sheet as a stand-in; the review sheets on grass are a go-live gate; atlas improvements ship as keeper builds afterwards |
| **The 2D rewrite of `behaviour.py`** touches the honesty-critical sleep / wake, credits and hold paths | Entity fields and event names kept, `y`, `facing` and `target` added; the behaviour self-test is ported first and the 60-pip harness runs with the camera moving before the swap |
| **Pathing sticks** at the Wood's edge and the river banks | Convex obstacles by construction, a one-cell slide rule, the 3 s stuck detector re-routing on the 60x28 BFS grid, never teleport, never through water except the Ford (and the bridge once raised); the 5-min random-target test asserts zero stuck and zero in-water |
| **Twelve screens for two people** scatter life so the camera lives at 0.75x with small sprites | 30 % Moot gravity and a 200-cell idle radius, seeds land on the green, camps cluster in the Steading ring, `expedition` as the sanctioned way to travel far together, and the honest acceptance that a sunlit land with two real camps, moving shadows and a beacon is alive in a way the cave was not |
| **Camera motion reads as nausea or smears labels on 3 Mbps** | Critically damped spring, 60 cells/s cap, 1.5 s dead zone, three fixed zooms, changes only at rest with hysteresis, never a cut inside a round, the recorded-pan QA clip judged at tile and 720p; DRIFT falls back to a slow hold on the Moot if a viewer QA flags it |
| **Schema 2 migration on a live file two real people care about** | `/tmp` copy first, identity byte-identical assertion, refuse-to-boot on a pip count mismatch, `.bak` before, `hollow.py` and `pips.py` on disk for a week |
| **Hot-reloading the largest scene module the compositor has taken on air**, plus a 20 MB memmap | Compile + self-test gate, the bake pre-built offline, last-good-frame on error, `swap-build.sh` as the fallback, owner told before either |
| **Empty land reads as abandoned** rather than wild | No ruins, no decay, no weeds; tidy camps with plates; wild flowers by season; the honesty line says the wind is just the wind; the plank names what the camera is surveying; the minimap's walked fraction frames the rest as unwalked, not dead |
| **Leading-verb rule widens what triggers actions** | ≤ 4 tokens, verb first, no URL, stop-words dropped, every remaining token must be a known object word for that verb, the plank says what was understood; ordinary sentences never match |
| **Scope creep toward a real RTS economy** | One resource (stone), three raisings, one field per person, no fences, no carving, no hunger or combat; every structure is a keeper ship tied to a real ladder; the art rules revert the rest |
| **"Explored" invites fog of war** | The minimap shows the whole map always; walked / unwalked is a saturation difference over a real record; the art rule forbids hiding land |
| **The beacon is the one keeper object; someone will propose a kite, an owl, a dog** | The art rule names the lantern and bans anything a viewer could read as flying or walking; the monitor flags any moving sprite without a key |
| **Hemisphere and latitude wrong** (winter in October) | Default from the machine timezone, one config value, the land line names the season and the readout shows the setting at boot |
| **The host is a MacBook on battery that sleeps on lid close** (journal 018) | Unchanged: `caffeinate` for now; an always-on host is outside this design. A clock jump only moves the light, never entities |
| **Kick's tolerance of a no-human broadcast** | Unchanged from CONCEPT §9: the ticker says plainly what the show is; the owner's account stays reachable for mod commands |
