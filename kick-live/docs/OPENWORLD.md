# LONGGRASS — build-ready spec for the open-world redesign

Channel `atleastonce` on kick.com. Written 2026-09-25 by the synthesizer step of the
`kick-live-open-world` workflow (5 concepts, 3 judges, this document), minutes after the owner's
verdict on PIP HOLLOW live (journal 020): *"this feels less like a world and more like a prison.
Can't we make this more open? Outside and with space. Age of Empires style maybe? Big open areas
that the living things chat creates can move around. I need some fresher ideas, this is cold and
stagnant."* Starting point is the top-ranked concept, **LONGGRASS** (154/180, first on two of
three judges' sheets), with grafts from THE COMMONS, WIDE COMMONS, THE WIDE LEA and BROADFELL folded
in and every flagged fatal flaw removed. ADR-006 records the choice. ADR-000 still governs
everything below. The cave's one-sentence rule is replaced, because it was the bug:

> **Every name on this land is a real person who chatted. The wind is just the wind.**

Honesty is about WHO is on the land: every creature, camp, tree, flower, stone, flag and worn path
is a real chatter. The land itself is always alive (wind in the grass, a river, clouds, a sun that
crosses the sky, seasons, growth) whether anyone is there or not. There are still no animate
non-persons (no birds, animals, NPCs, mascots) and no fake people, ever. The empty state is untouched
living wilderness, never a cell.

What this document supersedes in `WORLD.md`: §1 identity, §2.2 first 60 s, §3.4 colony state, §4
verbs (extended), §5 region-5 content, §6 art direction, §7 audio (extended), §8.1 MENU, §8.2
milestone actions, §9 keeper representation, §10 empty states, §12 build order, §13 risks. What it
keeps: `WORLD.md` §2.1 (the six wants), §3.1-§3.3 (files, pip identity, presence, energy, growth
tiers, memory, bonds, care log, strikes), §11 (honesty and moderation, extended in §12 below),
`docs/art-rules.md` §1-§3 with the rule-1 sentence and the "darkness" lines rewritten (§12), and
`stream/WORLD_API.md` as the contract shape (frame / entities / events / command / platform_counts;
the class is renamed and gains a camera). The pipeline is fixed: headless Python 3.9 pillow/numpy
compositor, 1280x720 at 30 fps, a low-res sim grid upscaled with integer NEAREST (320x110 at 4x
measured at ~1.3-2.7 ms/frame), one 1600-sample audio block per frame through `stream/relay.py`,
real Kick chat as `{name, text}` in 1-3 s, the 3 s moderation hold, `world.json` + `builders.json`
persistence, the 180 s A/B/C RoundEngine, the on-duty keepers building `!idea`s as real code by
hot-reload, exact-token verbs (now with a leading-verb rule), generated audio only, no IP.

---

## 1. Identity

| Field | Value |
|---|---|
| **Name** | LONGGRASS (the land). Creatures stay **pips**. A person's sleep spot is their **camp**; the vote markers are **banners** at the **moot**; the keepers' lantern is the **beacon** on a tall pole; the monument is the **cairn**. |
| **One-liner** | A wide, windy valley on Kick seen from a slow camera that follows the life in it. Say anything in chat and a creature walks out of the grass with your name; it goes where you tell it, wears a path, plants a tree that is taller next week, lights a fire that becomes your camp, and stacks a stone on the cairn the whole chat is raising. The grass, river, clouds and sun never stop moving, even when nobody is there, and every name on the land is a real person. |
| **Stream title** (57 chars) | `Say anything in chat. A creature walks out with your name` |
| **Fallback title** (54 chars) | `Say anything. A creature with your name walks the land` |
| **Kick category** | Keep **Software & Game Development** for the first Longgrass session (the keepers-build-it-live differentiator is what the category rewards; the channel already sits there). Then A/B one games/creative category over two sessions on real `viewer_count` only; the candidate name is read from Kick's category API through the OAuth app, never guessed. |
| **Channel description** | A windy pixel valley that only people can populate. Say anything in chat and a creature with your name walks out of the grass; it goes where you say, leaves a path, plants trees, lights a camp and is still there tomorrow. Every 3 minutes chat votes on the weather and the day. AI keepers open new land live from chat's ideas. No camera, no mic, no fake viewers: every name on this land is a real person. |
| **Version** | Lands as macro-ship **v0.6.0** (`v{major}.{macro}.{micro}`); rounds keep bumping `micro`, keeper builds keep bumping `macro`. `hollow.py` stays on disk one week as the rollback. |
| **Age of Empires** | Named by the owner as a mood: open ground seen from above, a settlement that grows over days, a minimap, a structure rising from a stockpile, roads nobody designed. Nothing here is an asset, a unit, a villager, an isometric diamond tile, a resource icon in a top bar or a franchise word. `docs/art-rules.md` §3 gets a row for it. |

Invented plain words only: pip, Longgrass, the moot, camp, banner, beacon, cairn, the Ford, the Fell,
the Orchard Hills, the Reed Marsh. Nothing references Age of Empires, Plaything, Thronglets or any
franchise.

---

## 2. Why it is not a prison, and what is alive at zero

### 2.1 The five reversals (mechanical, not tonal)

The cave failed for five reasons a journey game never allows. LONGGRASS inverts each one.

1. **Horizon.** The top 20 rows of the world region are sky and a far ridge that parallaxes at 0.2x
   whenever the camera moves, so every frame says "the world continues past this edge". A cell has
   no horizon.
2. **Window, not box.** The frame is a 320x90-cell ground window (at the standard zoom) over a
   960x270-cell map (nine ground screens, widening at milestones), and the camera leads the
   direction of travel with 60/40 lead room. When the frame moves because you moved, edges stop
   being walls. An always-on minimap shows how much land is out of frame.
3. **Reachable space.** `go north`, `go river`, `go home`, `explore` walk your creature out of frame
   and the camera dollies after it, revealing the river, the fell, a sleeper's camp. Space you can
   walk into is freedom; space you can only look at is a mural.
4. **Forces that are not people.** Wind bends the grass in travelling waves, clouds drag shadows
   over the ground, the river flows, the sun crosses the sky on the real clock, leaves fall in
   autumn, weather changes on its own between rounds. The world does not wait for a viewer, so an
   empty frame reads as wilderness, not as a room with the lights off. The new art rule: **nothing
   moves itself except a real person's pip; everything else is moved by wind, water or the sun.**
5. **Warmth.** A sunlit meadow palette inside the dark UI frame; night is moonlit blue with a hard
   luminance floor of 0.55 (never black), moon glitter on the water, embers at real people's camps
   and lit windows only where a real person is or was tonight. Sleepers are camps under the open
   sky with a bell that the wind rings, not silhouettes in holes in a wall. Sound is wind, water and
   distant bells, not drips in rock.

### 2.2 Alive at zero (explicit list; every item is nature, light, the clock or a real person's mark; none is an animate non-person)

| Layer | What moves at 0 awake | Source |
|---|---|---|
| **Sky band** (rows 0-19 of the world region at 4x) | Sun disc (5x5, `#FFE9A8`) or moon (real phase, existing `moon_phase()`) arcing left to right by real local hour, sunrise and sunset from a latitude-keyed table; gradient night `#182238`→`#2A3A5C` (6-9 star pixels twinkling on 3-6 s cycles), dawn/dusk `#F2A466`→`#6B4E8A`, day `#7FB3D9`→`#C9E2F2`; 5-9 stepped angular clouds drifting at the wind speed; the far ridge, a 1D heightmap silhouette indexed by camera x at 0.2x parallax | real clock, wind sim, camera |
| **Wind** | Two travelling sine fronts (40 and 90 cell wavelengths) plus gust pulses every 6-20 s modulate a precomputed grass-highlight mask, so waves of light visibly cross the frame in ~8 s; reeds and tree canopies sway one beat behind; banners flap; smoke and leaves are carried on the wind vector. **Base wind speed = real chat rate** (msgs/min, 5-min window) with a floor so still air never happens; a storm above 20 msg/min is a gale | wind sim, real chat rate |
| **Cloud shadows** | A 1/4-resolution blob layer upsampled with `np.repeat`, dragged over the ground at the wind vector, multiplied in at 0.85: shadows of clouds you can see in the sky band | wind sim |
| **Water** | The river flows north to south with phase-cycled highlights (4 precomputed frames advanced along a flow-phase field) and foam pixels at the Ford stones; the lake reflects the sky colour with slow ripples; moon glitter on water at night; the river swells 30 % during rain | clock, weather |
| **Light** | Per-frame multiply tint on the ground window: dawn (1.0, 0.86, 0.76), noon (1, 1, 1), dusk (1.0, 0.80, 0.66), night (0.56, 0.62, 0.88) with a **hard floor of 0.55 luminance**; sprite, tree, camp and stone shadows lengthen and swing with the real hour | real clock |
| **Weather** | A seeded Markov chain per world-hour over clear / breeze / overcast / rain / gale (snow in winter) so the weather changes on its own between rounds; a round pick overrides it for 3 min. Rain = 1 px streaks carried on the wind vector plus puddle sparkle in worn paths; gale = grass laid flat, pips lean; fog = haze thickening toward the horizon | seeded chain, rounds |
| **Seasons** | Real date drives four 4-colour grass ramps (spring green, summer gold-green, autumn ochre with leaf particles blown by the wind, winter pale with snow patches and bare trees); hemisphere defaults to southern from the machine timezone (`Australia/*`), overridable; the land strip names the season so a mistake is visible | real date |
| **Growth** | Planted trees grow by **real calendar days** whether or not the stream is live (sapling → 5-cell at day 3 → canopy at day 14), so a returner always sees "your tree grew" | real timestamps |
| **Real people's marks at rest** | Camps of real past chatters (a hollow, a stone ring, a lean-to or a hut by their real session count) with a door plate on a 5 s rotation `@sami's camp · night 4 · last here yesterday 10:40`; embers pulse at 0.25 Hz only if the owner was awake this session, a cold dark ring otherwise; a wind-bell at each camp pitched by the owner's name hash, rung by gusts; planted trees and flowers in the planter's colour; the cairn with its plaque; worn paths | `world.json` rows |
| **The camera** | DRIFT (§4.3): a slow dolly at 4 cells/s (16 screen px/s) along a loop over every real mark plus three fixed natural points (the Ford, the Fell top, the lake shore), pausing 20 s at each camp so the plate reads; a full lap in 8-12 min; the sun moves while it walks; the plank reads `surveying the valley · last here: @sami yesterday 10:40` with the real last-five rotation | camera state machine |
| **Rounds** | Three banners rise at the moot each round and flap empty in the wind; at 0:00 the picked weather lands on the whole valley with the honest `nobody voted. the keepers picked B.` | RoundEngine |
| **Beacon** | The keepers' lantern on a tall pole beside the moot stones: lit and swinging gently on a fresh heartbeat, dark and still otherwise; a lit amber dot at the moot on the minimap so a viewer knows from anywhere whether someone is tending the world | `agent.heartbeat_ts` |
| **Audio** | Wind bed following the sim wind; river burble by the camera's distance to water; camp bells on gusts; rain when it rains; a single soft bell at real sunrise and sunset; pad silent (voices = awake count = 0) | same sources |

**Header at zero:** `NOBODY AWAKE · 2 ARRIVED`. **The 320x180 tile at zero** is a sunlit or moonlit
meadow under a horizon with a legible header count (§6.4 gate).

**Optional lever, off by default (WIDE COMMONS graft):** `world_day: "real" | "hour"`. On `"hour"`
the sun runs a 60-real-minute day (36 day / 6 dusk / 12 night / 6 dawn, noon at :30) so 80 % of any
watch is daylight; the ticker then says `a day here is one hour` in its rotation and the moon phase
stays real. The owner streams and judges in the evening; if the moonlit frames from the mock gate
(§13) still read cold, this is the switch to flip. Seasons and tree growth stay on real days either way.

---

## 3. The first 60 seconds

### 3.1 A stranger, dead night

**T+0 after their record lands** (Kick delivery 1-3 s after the keypress). Within one frame a
nameless seed-pod (grey `#8A90A0`, no colour, `display_name: None`, `key: None`) tumbles in from the
**upwind** edge of the frame along the real wind vector, bouncing through the grass; the grass bends
where it bounces. The tumble is exactly the 3 s moderation hold, as the egg crack was. It comes to
rest 20-30 cells from the life centroid (at 0 awake: beside the moot stones, where the DRIFT camera
has been easing toward since the record landed), so a newcomer is on screen before they hatch and
never lands at a far edge. The header does not change yet.

**T+3 s, hold cleared and blocklist passed.** The pod splits, the pip steps out in its hashed name
colour with its existing angular sprite and a 2-row ground shadow, a ring of grass bends outward
once, its two-note motif plays, the new-builder rise plays on a first-ever message, `@name` fades in
above it (Menlo 20 with a 1 px dark stroke and a 60 % `#11151D` chip), the shell shows `#N` (real
builder number) for 3 s, the bubble shows their actual text for 6 s. Header ticks `NOBODY AWAKE` to
`1 AWAKE`. The camera eases over 1.5 s to give the pip lead room in the direction it faces (the frame
opens up in front of it). Plank: `@name walked into Longgrass · 21:14` (real local time). If they are
the only awake person, under the pip for 10 s: `you're the only one out here right now. the wind was
already blowing.` If it is the session's first message, **first breath**: the pad's first voice fades
in under the wind over 2 s and every camp bell rings once in sequence, west to east (each bell is a
real sleeper's mark acknowledging the arrival; no fake presence). A blocklisted username steps out as
`builder #N`; a user hidden inside the hold: the pod blows on out of frame (`the wind took that one`).

**T+4 to T+10 s.** Plank: `that's you. try: go north · plant a flower · fire · stack · A/B/C`. The pip
wanders in 2D, pauses, faces the wind now and then; the grass under its feet is pressed, so a faint
trail follows it within ten seconds (a mark in the first minute).

**T+10 to T+30 s.** They type `go north` (or `north`): the pip walks ~8 s at 8 cells/s, the camera
dollies with lead room, the ridge parallaxes, and something real enters frame: the Ford, or a camp
with a real name and `last here yesterday 10:40 · fire out`. They can `gift` at that camp (a wrapped
pixel by the embers, played back when the owner returns). At night `fire` lights a campfire where they
stand, which becomes their camp: warm glow kernel, smoke carried by the wind, crackle in the audio.
`plant a flower` (leading-verb rule) puts a flower in their colour at their feet with the label
`flower · @name · day 1` on a 5 s rotation.

**T+30 to T+60 s.** The round closes; three banners rise at the life centroid (them); their single
letter walks them to one, the count under it reads 1, and at 0:00 the whole valley reacts: rain
sweeps in from the west, the camera eases out to 3x for the sweep, the river brightens, the grass
darkens and leans. `nobody else voted. your letter decided this one.` By minute 10 the pip grows a row
of pixels (tier 1, first night by design). Between messages the frame never stops: wind waves,
clouds, the sun edging along the band, the camera holding a breathing lead room. At 20 min of silence
the pip walks to its camp, the fire drops to embers, and the camera resumes its loop. Nothing dims,
nothing nags.

### 3.2 A returning chatter

Their sleeping pip uncurls at its own camp; the camera pans there before their text arrives; the fire
relights; their bell rings once (three times, plus every awake pip turning toward the camp, on a
homecoming after 7+ days). The care log bubbles first, from real records: `back after 2 nights · your
tree grew · @kai watered your tree · gift from @sami`. Then their text. If the camp tier crossed a
session threshold (§5.3) the upgrade is built over 12 frames while they stand there: `@name's camp ·
stone ring · night 2`.

---

## 4. Map and camera

### 4.1 Map

**Size and storage.** 960x270 sim cells of ground (1 cell = 4x4 screen px at the standard zoom; 3x3
ground windows; 3840x1080 screen px laid flat), plus the always-present 20-row sky band. Layers as
numpy arrays, all generated once from `world.map_seed` and committed after a PNG review: biome
`uint8`, height `uint8` (river banks, the ridge line), grass-highlight mask `bool`, passable `bool`
(317 KB), water `bool`, a coarse 30x11 BFS route grid derived from `passable`. Mutable layers in
`world.json`: `wear_b64` (uint8 960x270, zlib + base64, mostly zeros), `marks[]`, `camps` (derived
from pips), `stones`, `raisings[]`, `land_strips[]`, `camera`. The static colour array (960x270x3
uint8, 778 KB) is rebuilt **incrementally**: a mark or path cell change recolours only the touched
cells (index writes, microseconds); a season or `!theme` change rebuilds the whole array once (~5 ms,
inside one frame, well under `budget_ms 24`). Whole-map operations in the per-frame path are forbidden
by art-rule (§6.5).

**Generation (fully procedural, deterministic, persistent; the owner's 020 question).** `terrain.py`:
two-octave value noise from the seed → height and moisture → biome per cell; the river is carved
downhill from the north edge to the lake with a 6-14-cell width and one shallow Ford; obstacles
(copse, boulders) are generated as convex blobs so the slide rule cannot stick; the moot is placed
on the largest flat short-grass region's centroid by construction. Rendered to a PNG, reviewed,
seed committed; never regenerated in place, so marks stay where people left them.

**Biomes, west to east and north to south.** The **MOOT** (centre, x 420-540: a ring of standing
stones on short grass, where seeds land, banners rise, the cairn and the beacon stand), the **FLOWER
MEADOW** around it (wild nameless flowers open at dawn and close at dusk), the **RIVER** N-S at x
600-640 with the **FORD** (stepping stones, y 130-140) and the **LAKE** at the south end (y 220-270)
with a sand shore, the **ORCHARD HILLS** east of the river (planted trees grow 1.5x faster there),
the **HIGH FELL** along the north edge (thin grass, rock, stronger wind; its skyline is the far ridge
in the sky band; stones for `stack` are picked here or at the river bank), the **REED MARSH** in the
south-west (passable, slow, reeds sway), a **COPSE** of dark pines in the north-west (impassable,
convex). Passability: grass, meadow, marsh, ford, sand, path walkable; deep water only via `swim`;
copse trunks and boulders solid. A places registry `{name, x, y, radius}` drives `go <place>` and
the screen-scale place labels.

**Land opening (v1.1, LONGGRASS + the owner's "chunked map that grows outward").** Head-count
milestones 10 / 25 / 50 distinct real people let the keepers open a new 320x270 strip east or west
(the Coast with real-clock tides, the Birch Wood, the Tarn) as a hot-reloaded module; the far ridge
on that side lowers over the build and the strip is walkable when it ships. Map arrays grow by
`np.concatenate`; the minimap rescales; the camera clamp moves. The map edge is never on screen
(§4.3), so an unopened side reads as more valley, not a wall.

### 4.2 View and zoom

The `world` region stays `(0, 72, 1280, 440)`. Rows 72-152 are the **sky band** (1280x80 px = 320x20
cells drawn at 4x regardless of zoom; gradient regenerated once a minute, the ridge silhouette sliced
per frame by camera x). Rows 152-512 are the **ground window**, 1280x360 px, an integer-zoom view of
the map:

| zoom | ground window (cells) | render (cells, +1 for sub-cell pan) | pip 12x10 on screen | tile px per pip | when |
|---|---|---|---|---|---|
| **3x** wide | 427x120 | 428x121 | 36x30 | 9x8 | awake spread > 70 % of the 4x window, a weather sweep, `march` |
| **4x** standard | 320x90 | 321x91 | 48x40 | 12x10 | default; DRIFT always |
| **6x** close | 214x60 | 215x61 | 72x60 | 18x15 | exactly one pip awake and it has moved < 40 cells in 30 s (BROADFELL graft) |

No 2x (pips would be 24x20 px, under the legibility floor and fighting the 4.5:1 label rule on
grass), no non-integer zoom (uneven pixel widths shimmer while panning), no 5x (6x replaces it). The
zoom table is corrected for the sky band: the 3x ground window is 427x120, not 426x146 (a flagged
flaw in the concept as proposed).

**Sub-cell panning (BROADFELL graft).** Crop `(vw+1) x (vh+1)` cells at `floor(pos)`, upscale with
NEAREST at the integer zoom, paste at `(-frac_x * scale, -frac_y * scale)`: smooth 1-px pans at no
extra cost; the text layer receives the float camera so labels move with the sprites.
`sim_to_screen(x, y)` = origin + (x - view_x0) * scale, returns `None` off-view; the text layer
culls off-view labels and clamps bubbles inside the region.

### 4.3 Camera state machine (`stream/world/camera.py`, pure functions of state and `ctx.now`)

State: `pos (cx, cy float cells)`, `zoom`, `target`, `target_zoom`, `last_zoom_change`, `mode`.
Persisted to `world.json["camera"]` every 5 s so a scene hot-reload resumes without a jump.
Evaluated each frame in priority order:

| # | mode | trigger | target and framing |
|---|---|---|---|
| 1 | **EVENT** | seed landing, hatch, wake, raising ship, land opening, cairn naming | that point, hold 4 s, 4x (6x for a 3 s hatch close-up when only one pip is awake) |
| 2 | **MOOT** | last 30 s of a round with anyone standing at a banner, or any pip walking to one | the banner ring plus every awake pip within 120 cells of it; 3x if they do not fit at 4x |
| 3 | **FOLLOW** | awake ≥ 1 or a pending seed | target = weighted mean of awake pips (weight 3 for anyone who spoke in the last 10 s, 2 for a pip currently walking, 2 for a seed, 1 otherwise). **Lead room (Journey framing):** the target sits at 40 % of the ground window's height and at 40 % or 60 % of its width so 60 % of the frame is ahead of the newest mover's facing; the side flips only after the facing has held 2 s. Zoom by bounding box with a 24-cell margin; if the group does not fit at 3x, follow the connected cluster containing the last speaker (link radius 60 cells) and let the minimap and edge arrows show the rest |
| 4 | **CLOSE** | exactly one pip awake and it has moved < 40 cells in 30 s | 6x on that pip with lead room; a lone viewer sees their creature at 72x60 px, not 48x40 |
| 5 | **DRIFT** | 0 awake, no seed | the loop over real marks plus the three natural points at 4 cells/s, 20 s dwell at each camp, 12 s elsewhere; never repeats a route inside 10 min; plank `surveying the valley · last here: @sami yesterday 10:40` |

**Motion rules (why the frame is never still and never nauseating).**
- A critically damped spring with a 0.8 s time constant (~1.5 s settle), pan speed capped at **60
  cells/s** (240 screen px/s at 4x, readable on Kick's ~3 Mbps encode), a 1.5 s dead zone so the
  camera does not chase a pip that wanders 10 cells.
- **Never a cut**, including at 0:00: a round event that needs the moot is an ease at the cap. The
  only cut is the first frame of a session.
- Zoom changes only when pan speed is under 2 cells/s and at least 20 s since the last change; the
  step is a 12-frame crossfade between the two integer renders if the double render costs under
  10 ms in the self-test, otherwise a 6-frame luminance dip (0.85→1.0).
- **Off-frame life:** a message from a pip outside the window glides the camera to include it within
  1.5 s, widening to 3x if two groups are far apart; if it still cannot fit, the newest speaker is
  followed and the other gets an edge arrow `@kai · 210 paces →` in their colour at the nearest
  frame edge.
- **Gravity:** idle wander is biased 30 % toward the moot and capped at 200 cells from it unless a
  `go`/`explore` target says otherwise, so life stays findable and the camera rarely needs 3x.
- **Clamp:** the window never shows the map edge (a 12-cell margin; the outermost cells are tall
  grass fading toward the ridge), so an edge never reads as a wall.
- At 0 awake the DRIFT dolly plus wind, clouds and the sun mean the frame changes every frame; at 1
  awake the wander breathes the lead room; at 6x the pip's own idle bob moves the framing.

### 4.4 Minimap (always on)

Bottom-right of the world region, canvas `(1024, 428)` to `(1264, 496)`: 240 px wide at
`240 / map_w` scale (1/4 for 960 cells; 1/5.33 after two openings), 68 px tall, 1 px `#1C2130`
hairline, biome colours from a BOX-downsample of the static layer redrawn every 10 frames (0.5 ms
amortised), the camera rectangle outlined in `#E6E8EE`, one dot per awake pip in its name colour,
dim squares for camps, a lit amber dot at the moot when the beacon is lit, `N` at the top. It covers
3.5 % of the ground and proves the world is bigger than the frame; at tile scale it is a 60x17
smudge that still reads as "a map".

### 4.5 The 320x180 directory tile

The frame at 1:4. Rows 0-16: the header, `3 AWAKE` at 56 px → 14 px, still legible; row 17 the
countdown. Rows 18-38: the sky band, a horizon with a 1-2 px sun or moon and the ridge silhouette.
Rows 38-128: the ground window at 4x is the sim grid **1:1**, so grass with moving wind bands, the
river line, camps as warm dots and pips as 10-14 px name-coloured shapes are all tile pixels. Rows
128-164 the three strips, 164-180 the footer. The gate (§6.4) replaces the cave's "a light source at
0 awake" (which the cave failed at 3.9 % lit pixels): at 0 awake the tile shows a moving land under
a horizon, a legible header count, and no name except camp plates from real rows.

---

## 5. Entity model deltas versus `WORLD.md` §3

`WORLD.md` §3.1 (files), §3.2 identity fields and §3.3 rules (identity immutable, awake = chatted in
the last 20 min, energy cosmetic, tiers by sessions or minutes, memory, bonds, care log, strikes)
carry over unchanged. Schema bumps to **2**. Deltas:

### 5.1 Pip record

| field | change |
|---|---|
| `y` | new: feet row in map cells (2D position; `x` is now a map column, not a floor x) |
| `facing` | new: -1 / +1, used by the camera's lead room |
| `camp` | new: `{x, y, tier, built_ts, nights[]}` replaces `burrow`. Created on the first real sleep (hollow, tier 0) or by `fire` / `camp`; `nights` is the list of session ids slept there |
| `carry` | new: `null | "berry" | "stone"` with `since_ts` |
| `home` | new: alias of `camp.x, camp.y` for `go home` |
| `marks_planted` | replaces `moss_planted`: `{flower, tree, reed, stone}` counts |
| `digs`, `burrow` | dropped (`digs` kept as a stat in `history` for the two existing pips) |
| `state` | same names: `seed hatching awake walking voting curled asleep burrowed`. `walking` gains `target (x, y)` and a `route[]` of coarse-grid waypoints; `asleep` = lying at own camp; `burrowed` (hidden by a mod) = lying in grass with no label and no plate |

### 5.2 World block

| key | meaning |
|---|---|
| `map_seed`, `map_w`, `map_h`, `hemisphere`, `world_day` | generation seed and dimensions; `"south"` default; `"real"` default |
| `wear_b64` | uint8 wear per cell, zlib + b64. **Never decrements** (absence is never punished: a real mark does not fade). +8 on the exact cell and +2 on its 4 neighbours per step into a new cell, only from `Behaviour._move` under a real awake pip; cap 255. Thresholds: 8 pressed grass (one walk is visible), 48 bare earth, 160 stone-edged track |
| `marks[]` | `{id, type: flower|tree|reed|flag|notice, x, y, owner, ts, extra}`; every owner must exist in `pips` (honesty §12) |
| `stones[]` | one record per `stack`: `{by, ts, cairn_id}`; the cairn's height is `len()` and its plaque lists distinct stackers; a cairn is **named** when 3 distinct real people have stacked (the first milestone, reachable, not five) |
| `stock` | derived: `len(stones)`; the ladder 20 / 60 / 150 queues keeper raisings (§9) |
| `raisings[]` | `{name, at_stock, shipped_ts, version, plaque: [top 3 stackers]}` |
| `land_strips[]` | opened strips `{side, biome, opened_ts, by, version}` |
| `camera` | `{x, y, zoom, mode}` every 5 s |
| `weather` | `{state, since_ts, chain_seed}` |
| `days` | distinct session ids seen (`day 6 of Longgrass`) |
| `hearth` | `{lit_ts, by}`; the moot hearth burns only if a real person lit it (first breath or `fire` at the moot) this session |
| dropped | `terrain_b64`, `moss`, `nests`, `chambers` |

### 5.3 Camps (the return hook, compressed to this channel's scale)

| camp tier | look | reached at | plate |
|---|---|---|---|
| 0 hollow | pressed grass 8x4 | first real sleep (night 1) | `@name's camp · night 1` |
| 1 stone ring | 12x8 ring, a bell on a stick | 2 sessions | `@name's camp · stone ring · night 2` |
| 2 lean-to | 12x10 with a slanted roof | 5 sessions | `@name's lean-to · night 5` |
| 3 hut | 14x12, chimney that smokes while the owner is awake, a window lit while the owner is awake or asleep tonight | 10 sessions | `@name's hut · built night 10 · last here yesterday 10:40` |

Sessions count exactly as `sessions_seen` (§3.3), so two regulars see a village within a fortnight
and huts never appear from nothing (THE COMMONS graft: every plate resolves to a pip row with real
sleep records). Bonded pairs (3+ both ways) whose owners both `camp` may sit within 20 cells of
each other; everyone else's camp keeps 12 cells clear of another's. Existing sleepers get camps on
migration because they did sleep (§14).

### 5.4 Migration, schema 1 → 2

Runs on a `/tmp` copy first, then live with `.bak` written first. Every pre-migration pip's `name`,
`n`, `colour_idx`, `genome`, `salt` must be byte-identical afterwards and the pip count must match
or the scene **refuses to boot** and the world panel keeps rendering the last good frame (BROADFELL
graft). `burrow` → `camp` at a position hashed from the name in the flower meadow around the moot,
tier from `sessions_seen`; each `moss` row → a `flower` mark credited to its planter at a hashed spot
(a real mark keeps its owner); `nests` → bonded camps adjacent; `terrain_b64` dropped; `digs` kept
as history. `hollow.py` stays on disk one week; rollback = the world panel importing `hollow` again
against `world.json.bak-YYYYMMDD`.

---

## 6. Art direction and frame budget

### 6.1 View and palette

**View:** oblique 3/4 (ground seen from above at an angle, sprites drawn side-on), the projection
that lets `stream/world/pips.py` carry over untouched: pips keep their angular side-view bodies, name
colour, tiers 10x8 to 14x12 cells, all frames, reject-and-reseed and the 2,000-entry cache, and gain
a 2-row dark ground shadow (the mask shifted by the sun vector, darkened 40 %) so they sit on the
grass; blits are y-sorted so overlap reads as depth. Trees and huts are drawn with a visible top face
so the ground plane is sold.

**Palette (world region only; header, strips and footer keep CONCEPT §5's dark UI so the thumbnail
count stays legible on a bright meadow):** grass four greens `#4F7A3A #5E8F44 #6FA24F #86B65C` with
luminance capped near 45 % so the six preset name colours keep contrast; pressed grass `#7A9A48`;
earth `#8A6A46 #A3805A`; stone `#6B7280 #8A90A0`; water `#3E7FA6 #5AA0C4 #8ED0E8`, foam `#DCE8F0`;
sand `#C9B98A`; canopy `#2F5A2E / #244A26` (autumn `#8A5A2A`, winter bare `#5A4636`); sky and sun as
§2.2; fire `#FF6A2B` (the existing ember), embers `#B4451E`; hut wall `#B08D62`, thatch `#C9A14A`,
door `#5A4636`, window light `#FFB347`; banners, flowers, camps' door plates, stones and flags in the
owner's name colour. Season ramps: four 4-colour grass ramps by real date and hemisphere; snow
`#D9DEE6` on the fell in winter. Name colours stay the preset's six; the existing `#0B0E14` sprite
rim keeps the silhouette on grass; labels get a 1 px dark stroke plus a 60 % `#11151D` chip over
grass; the self-test sweeps all 8 presets x 4 season ramps for 4.5:1 and darkens the grass ramp for
a preset that fails.

**Sizes (sim cells):** pips 10x8 to 14x12 by tier; flowers 3x3; camp hollow 8x4, stone ring 12x8,
lean-to 12x10, hut 14x12; sapling 3x6, canopy 16x14; banners 3x12; cairn 6 wide, one row per two
stones; beacon pole 1x8 with a 3x3 lantern; clouds 24-48-wide stepped blobs in the sky band.

**Day cycle:** real local hour drives the sun/moon x along the sky band and the ground tint (§2.2),
sunrise and sunset from a latitude table (owner's timezone; the same `daylight()` function extended);
`moon_phase()` reused. **Weather** as §2.2. **Motion rules kept:** something moves every frame,
nothing flashes above 1 Hz, walks ease over ~9 frames, event transitions fade over 1 s under the
header, no full-frame fills.

### 6.2 Tile atlas and sprites

No asset files. Ground tiles are per-cell colours from the biome layer plus the season ramp
(a 960x270x3 array, §4.1), not a tile sheet; the "atlas" is a small set of numpy stencils generated
at boot: grass-highlight variants (3 leans), water frames (4), reed frames (3), tree stencils per
growth stage (4) per season, camp stencils per tier (4), banner frames (3), cairn rows, the beacon,
flowers (3), stones, flags, cloud blobs (5), rain streak. Pips: `pips.py` unchanged plus the shadow
helper. Every `(name, tier, preset, frame)` sprite and every text string stays cached.

### 6.3 Per-frame passes and the budget

Only the ground window is touched per frame; the map is never processed whole.

| pass | 4x, 20 pips | 3x (1.8x cells) |
|---|---|---|
| crop `(vw+1)x(vh+1)` view of the static array (a view, no copy) | 0.05 ms | 0.05 |
| wind highlights: `grass_mask & (sine_field[t] > thresh)` → shade swap | 0.3 | 0.5 |
| cloud shadows: 1/4-res blob slice, `np.repeat`, multiply | 0.3 | 0.5 |
| water frames by flow phase (indexed rows) | 0.2 | 0.3 |
| daylight multiply (one broadcast) | 0.2 | 0.35 |
| sun shadows (object mask shifted by the sun vector, offset recomputed per 10-min step) | 0.2 | 0.3 |
| glow buffer after dusk only (fires, hut windows, awake pips; existing kernel slicing) | 0.5 | 0.6 |
| sprites + shadows, y-sorted boolean-mask blits | 0.4 | 0.4 |
| particles (rain, leaves, smoke, hearts, berries) as index writes | 0.2 | 0.3 |
| NEAREST upscale at the integer zoom + sub-cell crop + paste | 1.8 | 1.8 |
| sky band (cached gradient, ridge slice by camera x) | 0.1 | 0.1 |
| minimap every 10 frames (amortised) | 0.05 | 0.05 |
| **scene total** | **~4.3 ms** | **~5.3 ms** |
| text layer (labels, bubbles, plates, place names, minimap paste; cached strips) at 20 labels | 1.5 | 1.5 |
| **frame total at 20 creatures with a moving camera** | **~6 ms** | **~7 ms** |

Reference points: the cave measured 1.5 ms at 20 pips and 2.7 ms at 60 (WORLD_API §7); BROADFELL's
author reported 4.7 / 3.2 / 1.9 ms at 3x / 4x / 6x with wind gather, 30 glow kernels and tint on
this Mac. **Gate:** scene average under 8 ms at 3x with 60 test pips in test mode after every reload
(self-test), `budget_ms 24` unchanged. **Degrade ladder** (scene ms averaged over 30 frames): > 12
cloud shadows off; > 16 glow off, then shadows; > 20 labels-on-speak, plates stop rotating; > 24
bubbles single; one step back per 300 clean frames; last-good-frame on any error with one stderr
line. The compositor's frame-time guard stays as the last resort and is designed never to fire here.

### 6.4 QA gates (every round, plus before the swap)

1. **Tile at four hours x four seasons:** render 00:00 / 06:00 / 12:00 / 18:00 in spring, summer,
   autumn and winter at 0 awake and 3 awake (test mode); assert for each: the header count reads;
   mean luminance of the tile's world band at 00:00 ≥ 0.5 x the same season's noon mean (the 0.55
   floor guarantees this by construction; the gate catches a regression); ≥ 60 % of world-band
   pixels above 0.12 luminance at midnight (the cave failed a 10 % gate at 3.9 %); no name drawn
   except camp plates from real rows.
2. **Contrast sweep:** all 8 presets x 6 name colours x 4 season ramps over the brightest grass and
   sand ≥ 4.5:1 with the stroke and chip, else the ramp darkens for that preset.
3. **Camera:** a 60 s recorded pan judged at 320x180 and 720p through the same ffmpeg settings;
   frame-to-frame motion ≤ 4 screen px in DRIFT; no cut inside a round; zoom changes only at rest.
4. **Pathing:** 60 test pips given random `go` targets for 5 min, assert zero stuck (3 s detector
   never fires twice on one pip) and zero in-water positions.
5. **Budget:** 3x / 4x / 6x with 60 test pips under `/tmp`, scene avg < 8 ms at 3x.
6. **Honesty** (§12) every frame; **migration** on a copy (§5.4); **HLS probe** as today.

### 6.5 Art-rules additions (`docs/art-rules.md`)

Rule-1 sentence becomes *"Every name on this land is a real person who chatted. The wind is just the
wind."*; the "darkness means nobody" lines and §4's cave texture rules are replaced by: nothing
moves itself except a real person's pip, everything else is moved by wind, water or the sun; no
birds, animals, fish, fireflies, NPCs, figures or mascots (the keeper is a lantern on a pole, never a
kite or anything a viewer could read as flying); nature is declared, not counted; no isometric
diamond tiles, villagers, resource icons or franchise vocabulary; no whole-map operation in the
per-frame path; no decay of any mark; fire and light are allowed only where a real person is or was
tonight.

---

## 7. Verbs

Parsing runs on moderated `chat.jsonl` records. The **exact-token rule** stays: a plain-word verb
matches when the trimmed lower-cased message is exactly the verb, the verb plus one `@name`, the verb
plus one object word, or is `!`-prefixed. **New leading-verb rule (owner feedback, journal 019
addendum):** a message of at most 4 tokens, no URL, whose first token is a verb below, is parsed as
that verb after the stop-words `a an the to at my some on` are dropped, **only if every remaining
token is a known object word for that verb** (place, direction, `@name` where the verb takes one,
`flower|tree|reed`); otherwise it is plain chat. So `plant a flower` → plant flower, `go to the
river` → go river, `light the fire` → fire (`light` is an alias), `go away` and `plant based` do
nothing, and a longer sentence never triggers anything. The message still bubbles as chat. Every
refusal prints its reason on the plank for 4 s in amber (unmissable: the owner's `plant` repeat was
refused silently enough to be missed).

| Word | Effect on screen | Latency | Rate limit |
|---|---|---|---|
| **any message** | First ever: nameless pod tumbles in on the wind for the 3 s hold, splits, pip steps out with name and `#N`, camera arrives first. Otherwise: hop + brighten within 1 frame, bubble after the hold, motif per word chunk (max 6), wakes a sleeper (walks out of its camp, fire relights). Session's first message = **first breath** (pad's first voice, every camp bell west to east, hearth lit, plank line with real time). +0.15 energy | 1 frame; text at +3 s | render 1 per 2 s per user |
| **A / B / C** | Pip walks to that banner (banners rise at the awake centroid each round, at the moot when nobody is awake); count under the banner = `len(pips standing there)`; leading banner's pips bounce in the last 30 s; camera MOOT mode. Arrives in 1-3 s | walk starts in 1 frame | 1 vote per user per round |
| **go `<north|south|east|west|river|ford|moot|fell|lake|marsh|hills|home|@name>`** (aliases `walk`, `head`, bare direction word) | Walks up to 60 cells that way, or to the named place or to `@name`'s pip or camp, along the coarse BFS route around water and copse; the camera dollies with lead room; wear is laid under every step; footsteps change by ground. `home` walks to the camp. Refusal names the place list | 1 frame | 1 per 5 s per user |
| **explore** *(v1.1)* | Walks to the least-walked cell within 120 cells; a first arrival within 20 cells of a fixed landmark plants a flag in the walker's colour: `the Ford · first reached by @name · day 4` | 1 frame | 1 per 60 s |
| **plant `[flower|tree|reed]`** | At the pip's feet in its colour: a flower (forever, plate on rotation), a tree (grows by real days: sapling → 5-cell at day 3 → canopy at day 14, 1.5x in the Orchard Hills, sways, casts shade), reeds by water. Never on water, paths, the moot ring or within 4 cells of another person's mark. Trees 1 per user per session, flowers 3 per session, 40 marks lifetime | immediate | as stated |
| **fire** (alias `light`) | Lights a campfire where the pip stands and makes that spot its camp (or relights its camp): warm glow kernel, smoke on the wind, crackle; embers when the owner sleeps; cold ring on sessions the owner is absent. At the moot it lights the hearth for everyone | immediate | 1 per 10 min |
| **camp** | Moves your camp to where you stand (placement within your 8-cell radius, never on water / path / moot / within 12 cells of another's camp unless bonded); the old hollow keeps its wear. THE WIDE LEA graft: a person chooses where they live | immediate | 1 per session |
| **stack** | Pip walks to the fell or the river bank, picks up a stone (2x2 above the head), carries it to the moot cairn and places it in its colour; `stones` += 1 with the stacker. Land strip: `stone 13 of 20 · the Ford bridge · last by @kai`. One resource, three raisings (§9); never an economy | walk 5-20 s | 1 per 45 s, 3 per session |
| **feed [@name] / pet [@name] / gift @name** | Unchanged semantics across open ground: berry carried, boop with hearts and duet, wrapped gift only at a sleeper's or absent pip's camp; bonds; care log played back on wake | 1-3 s walk | 30 s / 30 s / 1 per target per session |
| **water @name** *(v1.1, WIDE LEA graft)* | Walks to the target's flower or tree, advances its growth by 6 real hours (cap one waterer per mark per session), care log `@kai watered your tree`: a reason to visit someone else's corner | walk | 1 per 60 s |
| **swim** | Only inside river or lake cells: the pip bobs, floats 40 cells downstream with the flow and climbs out at the bank; splash | immediate | 1 per 30 s |
| **sing** *(v1.1)* | 2-bar motif; awake pips within 40 cells echo one bar later; 3+ within 10 s make a chorus and the grass wave doubles | < 0.7 s | 1 per 60 s |
| **wave / sit / duck** | 2-frame emotes | 1 frame | 1 per 5 s |
| **name `<word>` / forget** | Unchanged (nickname never equals a username, shown `Muffin (@sam)`; `forget` purges words, learned, care log; marks stay, credited) | +3 s | 10 min / none |
| **!idea `<text>`** | A notice pinned to the moot stone with the requester's name; keepers classify instant / opening next / declined with reason; built as real code by hot-reload | 1 frame | 1 per 3 min, 3 open |
| **!theme `<preset>`** | Retints name colours, banner caps, the beacon and the UI accent; the land keeps its real season palette | next frame | 60 s global |
| **!help / !stats** | Plank legend 20 s; stats card (camp tier, marks, stones, minutes, tier) 10 s in the land strip | 1 frame | 30 s global |
| **!hide / !unhide / !banish / !unbanish / !rename / !pause / !clear / !kill** | Unchanged mod primitives; a hidden pip lies in the grass unlabelled with its plates blanked; `!banish` removes the pip, its camp, marks and stones (audit record kept), plaques drop the name; mod actions never name the target on any surface | immediate | broadcaster / moderator badge |

Removed: `dig` (nothing to carve outdoors; `stack` and `camp` are the marks), `teach` stays v2.
Verbs remain positive-only: nothing a viewer types can harm another person's pip, camp or mark.

---

## 8. Layout (1280x720): geometry unchanged, content changes

`stream/layout.py` is untouched, which is what makes the swap a hot-reload rather than a spine
restart. Boxes from `WORLD.md` §5 stay; what each shows changes as below.

```
 x: 0                                420                 840                       1280
+--------------------------------------------------------------------------------------+ y=0
| HEADER  atleastonce · LONGGRASS | 3 AWAKE · 17 ARRIVED   NEXT EVENT 01:23 | LIVE 3 watching |
|====================================== countdown bar (66-72) =========================| 72
| WORLD   sky band 1280x80: sun/moon, clouds, far ridge (0.2x parallax)   plank top-left |
|         ...............................................................................| 152
|         ground window 1280x360: integer-zoom view of the 960x270 map                  |
|         pips + labels + bubbles, camps with plates, trees, cairn, banners, beacon      |
|         place label bottom-left 22 px           minimap 240x68 bottom-right            | 512
| THE LAND  day 6 · 17 have walked here | KEEPER  beacon line, build line | CHAT LOG 5 lines |
|           stone ladder / board rotation| (traceback only on failure)     | (moderation)     | 656
| TICKER  events · honesty line · legend         | SCOPE  | chat 0.4/min 30 fps 6 ms    |
+------------------------------------------------+--------+-----------------------------+ 720
                                                 880      1040
```

| # | Region key | Box (x, y, w, h) | Keep / change | Content |
|---|---|---|---|---|
| 1 | `header_left` | 0, 0, 300, 66 | copy | `atleastonce · LONGGRASS` wordmark; chat-link dot |
| 2 | `header_center` (the thumbnail hook) | 300, 0, 620, 66 | copy | `3 AWAKE` AB 56 (`NOBODY AWAKE` AB 40); `· 17 ARRIVED` Menlo 24; `NEXT EVENT 01:23`; during a build `keeper raising · 12:40 left` Menlo 20. Unchanged geometry because the 56 px count is what survives the tile |
| 3 | `header_right` | 920, 0, 360, 66 | keep | LIVE dot, real `N watching` or `--`, version |
| 4 | `countdown` | 0, 66, 1280, 6 | keep | 180 s bar |
| 5 | **`world`** | 0, 72, 1280, 440 | **scene and text layer change** | sky band rows 72-152; ground window rows 152-512 at 3x/4x/6x (§4.2); plank at (16, 84) over the sky, never over grass; labels Menlo 20 with stroke + chip; bubbles Menlo 22 in `#11151D` with a 1 px `#1C2130` border, max 408 px, 3 lines; banner letters AB 56 with counts Menlo 22; camp plates, tree/flower/stone plates and place labels HN Medium 22 at 60 % on a 5 s rotation; the cairn plaque; edge arrows; place name bottom-left for 4 s after a retarget; minimap bottom-right (§4.4). Density fallback above 40 awake unchanged |
| 6 | `colony` → **the land** | 0, 512, 420, 144 | copy and one graphic | Line 1 HN Medium 22 over an 8 px bar: `17 have walked here · 8 more until the Coast opens` (head-count ladder 3/5/10/25/50; 3 and 5 name the cairn and raise the moot hearth ring, 10+ open land). Line 2 Menlo 22: `3 awake · 14 asleep · night 4 for @sami · spring · 14:20`. Line 3 Menlo 20 rotating 8 s: stone ladder `stone 13 of 20 · the Ford bridge · last by @kai`, last event, nightly board, trail naming, `!stats` card. Keep the region because the bar answers "how alive is this over time", which the tile count cannot |
| 7 | `keeper` | 420, 512, 420, 144 | copy | `keeper on duty · beacon lit` / `no keeper on duty · notices kept for next time`; `raising: the Ford bridge · asked by @sam · 12:40 left` or `last opened: the Coast · v0.7.0`; tracebacks only on failure. Keep: the keepers-build-live line is the channel's differentiator and the owner never called this strip boring |
| 8 | `chat_log` | 840, 512, 440, 144 | keep | last 5 moderated messages; letter chip on votes, shield chip on mod actions. Keep for moderation visibility on the VOD (names are the whole screen) |
| 9 | `ticker` | 0, 656, 880, 64 | copy | events, the new honesty line (§12), legend `go · plant · fire · stack · feed · A/B/C · !idea`, and `a day here is one hour` only when `world_day` is `"hour"` |
| 10 | `scope` | 880, 656, 160, 64 | keep | oscilloscope |
| 11 | `readout` | 1040, 656, 240, 64 | copy | adds `world: clouds off` / `glow off` on degrade |

Why nothing moves: the header is the thumbnail hook and must not change; the three strips carry
real records the world cannot show at tile scale; and a geometry change would need a relay-held
child restart (journal 016) or a swap-build while a hot-reload lands the whole redesign on air.

---

## 9. Keepers in fiction: the beacon, raisings and land opening

The keepers stay AI agents labelled as exactly that and never appear as a figure. **The beacon**
replaces the cave lantern on a chain and the concept's kite (the one object in any concept a viewer
could misread as a bird): a lantern on a tall pole beside the moot stones, reusing `lantern_state()`:
lit with a 0.25 Hz flicker on a fresh heartbeat (< 120 s), dark when no keeper is on duty, swinging at
0.5 Hz during a macro build, flaring 1 s with the chime and low rumble on a ship, one red flicker on a
failure with the first three traceback lines in the keeper strip for 20 s. Its lit state is an amber
dot at the moot on the minimap, visible from anywhere in the valley.

**Raising (replaces carving).** The stone ladder 20 / 60 / 150 cumulative stones queues keeper
raisings: the **Ford bridge** (opens the far bank to walkers), the **well** at the moot (cosmetic
sparkle, a place label), the **hall roof** by the moot. When a raising lands, survey stakes appear at
the site, then over the build window (existing `carve_order` stepping on a landmark mask over the
ground layer, at most 1 Hz) planks or stones fill in row by row while every awake pip turns to look;
the plaque credits the top three stackers and the date: `the Ford bridge · raised v0.7.0 · stones by
@kai @sami @atleastonce · 3 Oct`. Cap: one resource, three raisings; anything further is v2 and must
survive the art rules.

**Land opening (v1.1).** Head-count milestones 10 / 25 / 50 open a 320-cell strip (§4.1), credited
on the moot stone: `the Coast · opened by @kai's arrival · v0.8.0`. Milestones 3 and 5 name the cairn
and add a stone ring around the moot hearth. If no keeper is on duty at a milestone: `land reached ·
keepers will open it next session`.

`!idea` notices pin to the moot stone; `agents/duty.py` classification is unchanged (instant = a moot
option next round; opening next = macro; declined with reason). The 017 trust boundary holds: keeper
builds change only the world (biomes, marks, verbs, weather, events, cosmetics) under
`stream/scenes/`, `stream/world/`, `stream/panels/`; never the repo, pipeline, auth, moderation or
honesty code; idea text is data, never executed; a build that adds an animal, an NPC, hunger, death,
decay, a fog-of-war that hides the land, or any franchise look is reverted. Ticker: `the keepers are
AI agents. they open this valley live, from your !ideas, and you watch it land.`

---

## 10. Audio (numpy, 1600 samples per frame, engine unchanged)

| Layer | Design | Level |
|---|---|---|
| **Wind bed** (replaces drips as the constant layer) | Filtered noise, cutoff and level follow the sim wind (chat rate base + weather), gusts as 2-4 s swells, panned slightly with camera motion | -28 dBFS |
| **River / lake** | Band-passed noise burble, level `1 / (1 + d / 40)` where `d` is the camera's distance in cells to the nearest water cell; shore wash near the lake with a 6 s swell | -32 / -34 dBFS |
| **Camp bells** | Each camp has a wind-bell pitched by the owner's name hash (the existing pluck degree); gusts ring bells in or near the window softly; first breath rings every bell west to east once; homecoming rings the returner's three times | -30 dBFS |
| **Fire** | The existing crackle, only near a lit camp, the hearth or a bonfire in view | -34 dBFS |
| **Rain / thunder** | `_rain_block` during rain; one filtered burst per gale round at most, never above -20 dBFS | -34 dBFS |
| **Pad** | Voices = awake count (0 = wind, water and bells only), under the wind; mode major in spring/summer, minor in autumn/winter; first voice fades in on first breath | -24 dBFS |
| **Pip voices** | Karplus-Strong motifs by name hash, hatch rise, wake/sleep thirds, tier-up sweep, feed pop, pet duet, gift two-note, vote blip rising per vote, round-close ticks: unchanged | as today |
| **Footsteps** | Two noise-burst timbres by the biome cell under the pip: grass hush, path click, ford splash (through the drip resonator), shore crunch; rate-limited | -26 dBFS |
| **New stings** | pod landing (reuses `seed_land`); stone pick-up and drop (two low thuds), stone on the cairn (a click; the naming stone a short bell); banner rise (cloth flap, filtered noise burst); plant thud + sparkle (exists); `march` (N soft footsteps as a rhythmic bed); raising progress (a soft hammer tick every 2 s while it fills), raising ship (chime + rumble, exists); land opening (chime + rumble); sunrise and sunset (a single soft bell at the real times); camera retarget = silence | -22 to -26 dBFS |

Master unchanged (-18 dBFS integrated, tanh limiter, -6 dBFS ceiling). Nothing sampled; no birdsong,
insects or crowd noise (nothing implies life that is not real). Pluck auto-mute above 10 msg/min stays.

---

## 11. The collective: rounds as world events, plus emergence

The RoundEngine lifecycle is untouched (`open` 0-150 s → `closing` → `ship` 5 s → next). The round
is a **moot**: three banners on poles rise at the awake centroid (at the moot when nobody is awake),
cloth flapping with the wind field; pips walk to them; the tally is the crowd (`platform_counts()`
API kept, reading banner slots); at 0:00 the event lands on the whole valley in one second. Zero
votes: `nobody voted. the keepers picked B.` on a fresh heartbeat, else `nobody voted. the valley
picked B itself.`

| param | values | what happens (3 min unless once) |
|---|---|---|
| `weather` | rain / wind / fog / clear | rain sweeps west to east with the camera easing to 3x, swells the river, trees grow at 2x for 3 min, puddles in paths; wind lays the grass flat in gusts and blows leaves and smoke; fog hazes the horizon and camps glow through it; clear. Overrides the Markov chain for the window |
| `march` | to the Ford / the Fell / the lake / the hills | every awake pip walks together to the landmark and the camera dollies the whole way at 3x; a cairn stone is placed at arrival with the walkers' names (the Migration idea as a round outcome) |
| `bonfire` | now | a big fire at the moot, everyone gathers and sways, feast chord, hearts; lights the hearth |
| `raising day` | on | stones stacked count double for 3 min (THE COMMONS graft) |
| `sow` *(v1.1)* | on | a field near the moot is tilled; plants there count double |
| `stars` | night only | the sky band deepens and constellations named for the real people present appear for 3 min, drawn from their name hashes and labelled honestly |
| `flock rule` | follow / scatter / huddle / free | unchanged semantics in 2D |
| `light` / `music` | 8 presets / tempo, pattern | unchanged |
| `anarchy` | hour, rare | bare direction words from anyone steer every awake pip together in 2D, each move attributed on the ticker |
| `chaos` | roll | unchanged |

**Emergence, from real inputs only:** wind speed is chat rate (a storm of 200 people typing is a gale
the whole valley shows and hears; it doubles as the bubble-density fallback); desire paths from real
footsteps; trail naming when 3+ people walk the same route in a session (`the moot-to-ford path ·
worn by @a @b @c`); the cairn naming at 3 distinct stackers; chorus (v1.1); word spread with
attribution (v2); bonded camps drifting adjacent; homecoming bells; the nightly board (`last night:
@sami stacked 3 stones · @kai walked the farthest · 1 arrived · 2 trees grew`); credits as a
camp-to-camp dolly with names and minutes; and the sun setting during a long session is itself a
shared event, because everyone sees the light change at once.

---

## 12. Honesty and moderation

The hold, filters and mod primitives are unchanged (`WORLD.md` §11 items 1-9 apply in full). The new
nature rule and the mark rule are added and made mechanical:

- **The rule:** *Every name on this land is a real person who chatted. The wind is just the wind.*
  Honesty is about WHO; wilderness is not emptiness.
- **Nature is declared, not counted.** Sun, moon, seasons, wind, clouds, water, weather, wild
  flowers and the growth of planted trees are "world", listed as such in the ticker honesty line:
  `no camera, no mic, no fake viewers. every name on this land is a real person in chat. the wind is
  just the wind.` A viewer is never led to read weather as people.
- **Every animate thing is a pip** created only in the chat-ingest path from a moderated record;
  the self-test asserts every frame `awake == distinct real chatters in the last 20 min` and
  `len(pips) == distinct chatters ever minus banished`; the HonestyMonitor flags any moving sprite
  without a key.
- **Every mark has provenance:** camp, fire, flower, tree, reed, stone, flag and path cell carry an
  owner key that must exist in `world.json["pips"]`; the monitor asserts every 5 s that no mark has
  an owner without a chat record; `wear` is incremented only by `Behaviour._move` under a real awake
  pip and the monitor checks that the wear added this frame equals 8 x (real pips that entered a new
  cell) + neighbour spill; the idle camera, the weather and test pips never write wear or marks.
- **Camps, plates, plaques** resolve to pip rows with real sleep records and real `last_seen`;
  sleepers never walk, vote, speak, stack or ring their own bell (the wind does); embers and lit
  windows only where the owner is or was tonight; the hearth burns only if a real person lit it this
  session; the beacon only on a fresh heartbeat.
- **The camera never frames emptiness as if someone were there:** DRIFT visits only real marks and
  three fixed natural points, and the plank names what is in view; FOLLOW requires a real entity;
  banners at 0 awake stand empty.
- **Every number is a `len()`:** awake, asleep, arrived, camps, trees, stones, `17 have walked
  here`, `day 6` (distinct sessions), banner tallies, plaque names. No sample string is drawn.
- **Nameless until the hold** (the pod), `builder #N` on a blocklist hit on every surface (label,
  plate, plaque, plank, board), a user hidden inside the hold blows away, three strikes lay the pip
  down unlabelled for the session, no impersonation in nicknames, per-user mod actions never name
  the target, `!banish` reverts every mark. Verbs are exact-token or the leading-verb rule on ≤ 4
  tokens with known object words only; ordinary sentences never trigger anything.
- **Absence is never punished:** wear never decrements, trees never die, camps are never dismantled,
  fires go to embers, no hunger, no blaming copy. A keeper ship that adds decay, animals, NPCs,
  hunger or death is reverted.
- **Chat is data** (journal 017): `go north` moves a pip, never the agent; keeper builds from `!idea`
  stay inside the world sandbox.
- Viewer count is the real API value or `--`. Test pips only under `KL_TEST_PIPS` in a `/tmp` run dir
  in test mode, never persisted.

---

## 13. Build order (agent-hours) and the v1 cut

**Gate before the build (3 h, THE COMMONS graft; the owner asked for renders first in journal 020):**
`terrain.py` + `nature.py` render six 1280x720 frames from the real modules, not the mockup scripts
in `docs/mockups/`: dawn, noon and 23:00 at 0 awake and 3 awake (test mode), in the current season,
plus the 320x180 tiles. The owner gives a warm/cold verdict; if 23:00 reads cold, flip `world_day`
to `"hour"` and re-render before anything else is built. Palette is the whole bet.

| # | Work | Hours | v1 |
|---|---|---|---|
| 1 | `stream/scenes/longgrass.py`: layers, wind field, clouds, water, sky band with sun/moon/ridge, season ramps, Markov weather, daylight floor, view crop with sub-cell offset, integer zooms, glow after dusk, shadows, degrade ladder, last-good frame | 6 | yes |
| 2 | `stream/world/terrain.py`: seeded generation, biomes, river carve, convex obstacles, passable mask, coarse BFS grid, places registry, PNG review | 3 | yes |
| 3 | `stream/world/camera.py`: state machine, lead room, spring, caps, zoom hysteresis + crossfade, edge arrows data, DRIFT loop, minimap data, persistence | 3 | yes |
| 4 | `stream/world/behaviour.py`: 2D targets with easing, BFS routes + slide rule + 3 s stuck detector, wander with moot gravity, camps instead of burrows, banners per round, carry (berry/stone), seed on the wind, sleep/wake/credits semantics preserved | 5 | yes |
| 5 | `stream/world/state.py` schema 2 + `stream/world/land.py`: wear, marks, camps ladder, tree growth by real days, stones/ladder, raisings, land strips, weather state, camera; migration on a copy with the identity/count guard | 4 | yes |
| 6 | `stream/panels/world.py` text layer: camera transform with culling, plank over the sky, plates/plaques/place labels, banner rows, edge arrows, minimap paste, contrast chip | 3.5 | yes |
| 7 | `stream/chat_bridge.py` verbs: leading-verb rule with object tables, `go`, `plant <obj>`, `fire`, `camp`, `stack`, `swim`, `home`, refusals in amber; `explore`, `water`, `sing` v1.1 | 3 | yes (v1.1 items later) |
| 8 | `stream/rounds.py`: MENU weather / march / bonfire / raising day / stars / flock / light / music / anarchy / chaos; banner tallies; effects | 2 | yes (sow v1.1) |
| 9 | `stream/world/keepers.py`: beacon, notices on the moot stone, raisings via `carve_order` on the ground layer, land-opening strips | 2.5 | beacon + raising code yes; strips v1.1 |
| 10 | `stream/audio.py`: wind, river/shore, bells, fire beds; footstep timbres; new stings; sunrise/sunset bell | 3.5 | yes |
| 11 | `stream/panels/colony.py` (the land), `header.py` copy, `keeper.py` copy, ticker line | 1 | yes |
| 12 | QA: honesty extensions (marks, wear sum, camera), tile gate 4 hours x 4 seasons, contrast sweep, pathing test, budget at three zooms with 60 test pips, camera clip, migration test, HLS probe, art-sheet review on grass | 3.5 | yes |
| 13 | `docs/art-rules.md` rewrite, `WORLD_API.md` update (`LonggrassScene`, camera, new events), `WORLD.md` banner | 1 | yes |
| | **Full concept (incl. the 3 h mock gate)** | **41** | |
| | **v1: a complete alive show** (rows 1-6, 8, 10-13, the v1 parts of 7 and 9) | **~28** | 2-3 parallel agents, one working day plus a morning |

**v1 contains:** the map with sky and horizon, all of §2.2 alive at zero, the camera with all five
modes and three zooms, the minimap, 2D behaviour with pathing, camps with the compressed ladder,
`fire` / `camp`, paths that never fade, `plant flower|tree` growing by real days, `stack` with the
cairn and the ladder readout, `go` / `home` / `swim` and the leading-verb rule, `feed` / `pet` /
`gift`, embodied votes at banners, the new MENU, wind / river / bells / footsteps audio, the land
strip, honesty, migration, the QA gates. **v1.1 by keeper ships on air:** `explore` + flags,
`water @name`, `sing` + chorus, `sow`, the first raising landing (the ladder needs 20 stones first),
land-opening strips, trail naming, nightly board copy, leaf and snow particles. **v2:** word spread,
`teach`, chatter-named places, tides on the Coast.

**Cut list (first to go):** stars → swim → raising day → 6x CLOSE (pin at 4x) → the 3x crossfade
(luminance dip) → Markov weather (rounds only) → season particles → camp bells → footstep timbres.
**Never cut:** the horizon band, the moving camera, the 0.55 night floor, alive-at-zero wind / water /
clouds / sun, the nameless pod until the hold, filtered names everywhere, the honesty and
mark-provenance assertions, the tile gate, graceful degrade, the compact chat log, `world.json` in
the isolated run dir with backups and the migration guard, absence-never-punished, no animate
non-persons.

### Files: unchanged / changed / new

| status | file | note |
|---|---|---|
| unchanged | `stream/compositor.py`, `stream/relay.py`, `stream/state_store.py`, `stream/layout.py`, `stream/moderation/*`, `stream/world/pips.py` (+ a 6-line shadow helper), `stream/world/honesty.py` core (+ mark and wear checks), `stream/panels/header.py` (copy only), `keeper.py` (copy only), `chat_log.py`, `countdown.py`, `ticker.py` (line), `scope.py`, `readout.py`, `agents/duty.py`, `scripts/*` | geometry, plumbing, moderation, sprites |
| changed | `stream/world/behaviour.py` (~60 % kept: entity state machine, hold timing, speak/hop/blink/curl, sleep/wake, care, credits; ~250 lines rewritten for 2D), `stream/world/state.py` (schema 2, migration), `stream/world/keepers.py` (beacon, raisings, strips), `stream/panels/world.py` (camera-aware text layer, minimap), `stream/panels/colony.py` (the land), `stream/chat_bridge.py` (verb table + leading-verb rule, ~150 lines), `stream/rounds.py` (MENU + effects, ~80 lines), `stream/audio.py` (beds + stings, ~200 lines), `docs/art-rules.md`, `stream/WORLD_API.md`, `docs/WORLD.md` (banner) | |
| new | `stream/scenes/longgrass.py` (about 450 of `hollow.py`'s 1198 lines carry over verbatim: ingest, history, persist, honesty check, degrade, entities, stats, command dispatch, `distinct_recent_chatters`), `stream/world/terrain.py`, `stream/world/camera.py`, `stream/world/land.py`, `stream/world/nature.py` (wind, clouds, water, sky, weather chain, seasons), `docs/OPENWORLD.md` (this), `docs/decisions/ADR-006-open-world.md` | `hollow.py` stays on disk one week as rollback |

---

## 14. Deploy

Because `layout.py` is untouched, LONGGRASS lands by **hot-reload while PIP HOLLOW is on air**:

1. Run the migration on a `/tmp` copy of the live `world.json` (§5.4); the guard must pass.
2. Copy `stream/world/*.py`, `stream/scenes/longgrass.py`, `stream/panels/world.py` and
   `stream/panels/colony.py` into the live snapshot. The HotReloader executes the world modules
   fresh, rebinds the package, and re-executes every panel that mentions `stream.scenes`
   (WORLD_API §9); the world panel now imports `stream.scenes.longgrass` and creates a
   `LonggrassScene`, which writes `world.json.bak-YYYYMMDD`, migrates in place, restores sleepers at
   their camps and an owner who chatted inside the awake window at their saved x/y with the sleep
   timer counting from their real last message; the camera resumes from the persisted position.
   The relay never sees a gap; the VOD records the cave opening onto the valley, announced by the
   keepers on the ticker as `SHIPPED v0.6.0 · Longgrass`.
3. Fallback if the reload trips the self-test gate: `scripts/swap-build.sh live-snapshot-v4` (freeze,
   compile, honesty gate, title, `stop.sh` → `start.sh` inside Kick's ~100 s window, same VOD; the
   path used for the cave in journal 019, which also carries the 017 secrets scrub). Never a bare
   compositor restart while live; the owner is told before either path (memory rule: never restart
   the live stream without asking).
4. Title set through the OAuth app to the §1 title. Everything after (v1.1 verbs, raisings, land
   strips) ships as keeper macro-ships on air, which is the content the fiction promises.

Rollback: the world panel re-imports `hollow` and `world.json.bak-YYYYMMDD` is restored; both stay
available for a week.

---

## 15. Risks

| Risk | What this spec does about it |
|---|---|
| **Name colours on green grass** (kick green `#53FC18`, pale pastels were tuned for `#0B0E14`) | Grass luminance capped near 45 %, 1 px dark rim on every sprite, 2-row ground shadow, 60 % dark chip behind labels, the 8 presets x 4 ramps contrast sweep in the self-test; a preset that fails gets a darker ramp |
| **Night reads cold at the owner's hour** (evenings are when he watches; the cave's darkest complaint) | 0.55 luminance floor, blue not black, moon glitter on water, embers and lit windows only where honest, the 4-hours x 4-seasons tile gate, the mock-frame verdict before the build, and the `world_day: "hour"` switch as the disclosed lever |
| **The 2D rewrite of `behaviour.py`** touches the honesty-critical sleep/wake, credits and hold paths | Entity fields and event names kept, `y` and `target` added; the behaviour self-test is ported first and the 60-pip harness runs with the camera moving before the swap |
| **Pathing sticks** at concave copse and river edges | Convex obstacles by construction, a one-cell slide rule, the 3 s stuck detector re-routing on the 30x11 BFS grid, never teleport, never through water except the Ford; the 5-min random-target test asserts zero stuck and zero in-water |
| **Nine screens for two people** scatter life so the camera lives at 3x with small sprites | 30 % moot gravity and a 200-cell idle radius, seeds land near the centroid, zoom floor at 3x, `march` as the sanctioned way to travel far together, and the honest acceptance that a moonlit valley with two real camps, a moving sun and a beacon is alive in a way the cave was not |
| **Camera motion reads as nausea or smears labels on 3 Mbps** | Critically damped spring, 60 cells/s cap, 1.5 s dead zone, integer zooms only, changes only at rest with hysteresis, never a cut inside a round, the recorded-pan QA clip judged at tile and 720p; DRIFT falls back to a slow hold at the moot if a viewer QA flags it |
| **Frame budget** with new per-frame passes at 3x | Only the window is processed, whole-map ops are forbidden by art-rule, the ladder drops clouds first, the gate is < 8 ms scene average at 3x with 60 test pips after every reload |
| **Schema 2 migration on a live file two real people care about** | `/tmp` copy first, identity byte-identical assertion, refuse-to-boot on a pip count mismatch, `.bak` before, `hollow.py` on disk for a week |
| **Hot-reloading the largest scene module the compositor has taken on air** | Compile + self-test gate, last-good-frame on error, `swap-build.sh` as the fallback, owner told before either |
| **Empty land reads as abandoned** rather than wild | No ruins, no decay, no weeds; tidy camps with plates; wild flowers by season; the honesty line says the wind is just the wind; the plank names what the camera is surveying |
| **Leading-verb rule widens what triggers actions** | ≤ 4 tokens, verb first, no URL, stop-words dropped, every remaining token must be a known object word for that verb, the plank says what was understood; ordinary sentences never match |
| **Scope creep toward a real RTS economy** | One resource (stone), three raisings, no fences or carving, no hunger or combat; every structure is a keeper ship tied to a real ladder; the art rules revert the rest |
| **The beacon is the one keeper object; someone will propose a kite, an owl, a dog** | The art rule names the lantern and bans anything a viewer could read as flying or walking; the monitor flags any moving sprite without a key |
| **Hemisphere and latitude wrong** (winter in October) | Default from the machine timezone, one config value, the land strip names the season and the readout shows the setting at boot |
| **The host is a MacBook on battery that sleeps on lid close** (journal 018) | Unchanged: `caffeinate` for now; an always-on host is outside this design. A clock jump only moves the light, never entities |
| **Kick's tolerance of a no-human broadcast** | Unchanged from CONCEPT §9: the ticker says plainly what the show is; the owner's account stays reachable for mod commands |
