# ADR-006: Open-world redesign — LONGGRASS, top-down, replaces the cave

Status: accepted (2026-09-25, synthesizer step of the `kick-live-open-world` workflow, re-run under an
owner directive after the mockup review; owner-invited, owner may overturn after the mock-frame gate).
ADR-005 is not in the tree at the time of writing; this number follows the workflow brief. This
revision supersedes the earlier ADR-006 text of the same day, which chose the side-view projection.

## Context

PIP HOLLOW (ADR-004, `docs/WORLD.md`) went on air at 17:58 local as macro-ship v0.5.0 (journal 019).
The plumbing held: honesty self-test PASS, a phantom pip quarantined at boot, a user hidden inside the
3 s hold never drew a name, 0 honesty violations over 330 frames, HLS probe PASS, 0 secrets in the
render processes' environment. The owner's first live minutes worked as designed (`hello` woke their
pip, header 0 → 1 AWAKE verified from Kick playback); natural phrasings such as `plant a flower` fell
through to plain chat by design and a refused repeat `plant` was easy to miss.

**The owner's verdict** minutes later (journal 020): *"this feels less like a world and more like a
prison. Can't we make this more open? Outside and with space. Age of Empires style maybe? Big open
areas that the living things chat creates can move around. I need some fresher ideas, this is cold
and stagnant."* Then, in sequence: the owner picked the **Settlement** direction over Migration and
Island, asked for renders first, and asked whether the world is fully procedural and whether a huge
number of chatters could build their own spaces (18:22); reviewed three rendered camera styles in
`docs/mockups/` (top-down settlement, isometric, side-scroll parallax, each at empty dawn and busy
evening) and chose **top-down**: *"The top down style is the best"*; and set the art bar: *"the
actual design of the individual parts needs to be massively improved. Align yourself with the
thronglets. Don't make the characters exactly like that though. Make them our own."* (18:40).

**Diagnosis** shared by the workflow: the cave's art rule *"darkness means nobody"* turned honesty
about PEOPLE into emptiness on SCREEN. A sealed 320x110 box with a ceiling, a floor line and sleepers
in numbered burrows reads as a cell, and at this channel's size (two humans ever) the dark empty
state is the default state. The correction is a distinction, not a loosening: honesty applies to WHO
is on the land (every named creature and every mark is a real chatter); the land itself may be alive
(wind, water, sun, seasons, growth). No animate non-person creatures, no fake people, ever.

**What stays fixed:** the headless Python 3.9 pillow/numpy compositor at 1280x720 30 fps; relay +
hot-reload deploys; real Kick chat as `{name, text}` in 1-3 s; the 3 s moderation hold (nameless
until cleared); `world.json` and `builders.json` persistence; the 3-minute embodied A/B/C round;
keepers building `!idea`s live as real code; exact-token verbs (now with a leading-verb rule for
short natural phrasings); generated audio only; no IP (nothing that looks like Age of Empires assets,
Thronglets or any franchise); ADR-000; the never-restart-the-live-stream rule.

**How the decision was made.** The workflow ran five concepts against the brief and three judges
scored each on six criteria (open, alive at zero, first message, return, together, feasibility; 10
each, 60 per judge, 180 total), named grafts and listed fatal flaws. The tally put **LONGGRASS**
first (154/180), a side-view valley with a sky band; the first synthesis wrote it up as such. The
owner had meanwhile chosen the top-down camera from the mockups, so the synthesis was re-run with an
owner directive: keep the judged mechanics, re-project them onto a top-down open map, fold in the
grafts, remove the fatal flaws, and defer the look of creatures, buildings and tiles to the separate
settlement-art workflow (`stream/world/art/`, `docs/ART.md`).

## Decision

Build **LONGGRASS as a top-down settlement**, as specified in `docs/OPENWORLD.md`: a sunlit land
seen from above through a moving window. The `world` region `(0, 72, 1280, 440)` shows a 320x110-cell
window (at the standard zoom, with 0.75x wide and 1.5x close) onto a 960x440-cell map generated once
from a seed by the approved mockup's method (elevation and moisture noise, a sea to the south-east, a
whole-map site search for the Steading, a river traced downhill past it with a Ford). Any message
drifts a nameless seed tuft in on the real wind for the 3 s hold; when it clears, a pip stands up on
the Moot green with the chatter's name and name-derived colour, walks where they say in two axes
(`go river`, `go north`, `go home`, `go @name`), wears a trail that never fades and is painted into
the ground, pitches a camp where they choose (hollow → tent → hut → hut with a chimney by real
sessions), plants trees that grow by real calendar days, sows a field in their colour, and carries
stones toward a cairn whose ladder queues keeper raisings (the Ford bridge, the well, the hall). The
land is alive at zero: wind bands on the grass whose base speed is the real chat rate, cloud shadows,
a river and a tidal shore, the real sun and moon as a tint and a swinging shadow vector over the
ground (no sky band; a small time dial shows the sun or the real-phase moon), seasons by real date, a
seeded weather chain, and a camera that surveys real marks when nobody is awake. Night has a hard
0.55 luminance floor. An always-on minimap shows the whole map with walked land saturated and
unwalked land pale (`4 % walked`, a real record), never a fog of war. The keepers are a lantern on a
post (the beacon) and raise structures or open new land instead of carving rock.

The new one-sentence rule, which is also the art rule:

> **Every name on this land is a real person who chatted. The wind is just the wind.**

with its mechanical corollary: **nothing moves itself except a real person's pip; everything else is
moved by wind, water or the sun.**

**Rendering.** The simulation and every per-frame effect stay at cell resolution (1 cell = 4 screen
px at 1x, the proven `np.repeat` path), but the display is no longer a nearest-upscaled pixel grid:
the ground is painted once at screen resolution per season (a memory-mapped bake built in a
background thread and repainted locally when a mark changes) and cropped per frame, then modulated by
one cell-resolution light field (tint, cloud shadow, wind, the shadow layer, water, tide). Creatures,
buildings and props come from `stream/world/art/` at three zooms. This is the one engineering bet the
mock-frame gate must time before the build; the fallback is a half-resolution bake.

The world lands as macro-ship **v0.6.0** by hot-reload while the cave is on air (`layout.py` is
untouched), after a 3-hour mock-frame gate in which the owner judges dawn, noon and 23:00 renders
from the real terrain, nature and atlas modules and the per-frame path is timed on this Mac. A ~12 h
**v0 preview** (bake, camera, light, camps from migration, hatch and `go`) can be on air the same
evening so the VOD shows the cave opening onto the land, with the rest shipping as keeper builds.
Stream title: `Say anything in chat. A creature walks out with your name` (57 chars). Category stays
Software & Game Development for the first session, then the A/B on real `viewer_count` as before.

### Judged mechanics of the winner carried into top-down

- The nature-is-alive rule and its exact wording; nature declared, not counted.
- Wind driven by the real chat rate, visible as travelling bands on the grass and audible as the bed.
- The real sun and moon and the real-date seasons, now as light and shadow over the ground (the tint
  curve, the swinging shadow vector, four season bakes) rather than a sky band; the time dial carries
  the sun or moon disc.
- The damped, never-cut camera (0.8 s spring, 60 cells/s cap, dead zone, zoom only at rest,
  crossfade), now with lead room in two axes and a survey loop over real marks at 0 awake.
- The camp ladder by real sessions, path wear that never fades, the cairn and stone ladder, keeper
  raisings, first breath (every real sleeper's bell rings west to east), homecoming bells.
- The leading-verb rule for ≤ 4-token messages with known object words only.
- The disclosed compressed-day switch (`world_day: "hour"`, off by default, on the ticker and the
  dial when on, moon phase real either way).
- The tile QA gate at four hours x four seasons with the midnight luminance floor.

### Grafts adopted from the other four concepts (all three judges' lists, merged)

- **From THE COMMONS:** plants and fields grow by **real calendar days** even while the stream is
  off; the camp ladder compressed to this channel's scale (hut at 5 sessions, chimney at 10, not 25)
  using the "hut from real sleep records with a rotating plate" idea; one shared **stone ladder**
  (20 / 60 / 150 → the Ford bridge, the well, the hall) with a plaque naming the top stackers; `raising
  day` as a round event; the **3 h mock-frame gate** before the build; the ticker honesty line and the
  "nature is declared, not counted" list; the hearth lit only when a real person lit it this session;
  the minimap as the answer to "how big is this world".
- **From WIDE COMMONS:** the seeded **Markov weather chain** per world-hour (v1.1); the off-frame
  **edge arrow** `@sami →` in the speaker's colour; **trail naming** when 3+ people walk the same route
  in a session; `swim`; the "wind took that one" line for a seed hidden inside the hold; the
  **compressed 60-minute world day** as a single disclosed switch; the tide as a living shoreline.
- **From THE WIDE LEA:** `camp` so a person chooses where they live (placement rules, never crowding
  another's camp); `sow` / `harvest` with one field per person in the owner's colour (the owner's
  directive names "huts and fields on the ground in builders' colours"); `water @name` as a care verb
  written to the target's care log (v1.1); the **always-on minimap** with the camera rectangle,
  name-coloured dots and camp squares; the plank copy `surveying the steading · last here: @sami
  yesterday 10:40` and the pooled-goal readout `stone 13 of 20 · 4 people`; the QA gate that renders
  00:00 / 06:00 / 12:00 / 18:00 in all four seasons.
- **From BROADFELL:** the camera and render engineering as the implementation of `camera.py`: a 0.8 s
  time constant with a 60 cells/s cap, zoom only at rest with hysteresis, camera pos and zoom
  persisted every 5 s so a hot-reload resumes without a jump; the **close-up** when exactly one pip is
  awake and still (54-105 px creature); the **coarse BFS** route grid with a slide rule and a 3 s stuck
  detector plus the 5-minute random-target pathing test; the **night floor raised to 0.55** with moon
  glitter on water; the **migration guard** (run on a `/tmp` copy, identity fields byte-identical,
  refuse to boot on a pip count mismatch, `hollow.py` kept a week); the rule that no whole-map
  operation may run in the per-frame path, asserted after every reload; footstep timbre by the cell
  under the pip and the river bed mixed by the camera's distance to water; the shadow that swings with
  the real hour.
- **From the approved mockup itself** (`docs/mockups/topdown_render.py`): the terrain generation
  method, the site search, the river trace, the corner placement of plank, land line, time dial and
  minimap, `SETTLED` as the header's second count, and the seed `4471` as the first candidate map.

### Fatal flaws removed from the winning concept as proposed

- **Side view with a sky band** that ate 20 of 110 rows and left the smallest ground viewport: the
  owner rejected the side-scroll render; the sky is now read from the ground (tint, shadows, the time
  dial) and the whole 1280x440 region is land.
- **Return too slow for this channel:** a hut at 25 sessions and trees that grew only across attended
  sessions. Now the camp ladder is 1 / 2 / 5 / 10 sessions and growth is by real days.
- **Mild decay:** path wear lost 1 per stream-hour above 40, a real mark fading, against the written
  absence-never-punished rule. Now wear never decrements.
- **The kite:** an object moved by wind and legal under the rule as written, but the one thing on any
  of the five screens a viewer could read as a bird. Replaced by the beacon, a lantern on a post, with
  a lit dot on the minimap; the art rule names it.
- **A camera cut to the moot at 0:00** broke the no-cuts rule. Now an ease at the pan cap; the only
  cut is the first frame of a session.
- **No build, resources or structures**, the opposite of the owner's Settlement pick. Now `camp`,
  `sow`, one resource (stone), the cairn and three keeper raisings, capped there so it never becomes
  an RTS economy (no fences, no carved words, no pouch, the WIDE LEA griefing surfaces).
- **No minimap** and a wander cap of 140 cells that made the map smaller than it felt. Now an always-on
  honest minimap, a 200-cell idle radius with 30 % Moot gravity, and land opening at 10 / 25 / 50.
- **2D pathing under-specified.** Now BROADFELL's BFS grid, slide rule, stuck detector and test.
- **The cairn needed five distinct people** in one graft (unreachable at a channel with two humans).
  Now a cairn is named at three distinct stackers, the first milestone.
- **The 4x nearest pixel look** that every concept inherited from the cave: the owner asked for
  massively improved art; the display is now painted at screen resolution and the creature look is
  owned by `docs/ART.md`.

## Alternatives considered

### Concepts (scores per judge out of 60: open, alive at zero, first message, return, together, feasibility; 10 each)

| Concept | Judge 1 | Judge 2 | Judge 3 | Total /180 | Outcome |
|---|---|---|---|---|---|
| **LONGGRASS** (valley, lead-room camera, camps and bells, chat-rate wind, land that widens) | 48 | **54** | **52** | **154** | **Chosen, re-projected to top-down.** First on two of three sheets, best on open and first message: the best first minute for a lone stranger at 11 pm (the seed on the wind, lead room, `the wind was already blowing`, every real sleeper's bell ringing west to east), wind-rung bells so an empty land sounds like the people who have been there, wind speed as chat rate, land that widens at milestones (the owner's "chunked map that grows outward"), the cheapest full concept with `layout.py` untouched. Its projection (side view, sky band) was overruled by the owner's mockup choice; its flaws (slow camp ladder, session-based growth, mild path decay, the kite, no build, no minimap) are fixed above. |
| THE COMMONS (16-screen top-down map, huts on first sleep, stone ladder, plaques) | **49** | 51 | 49 | 149 | Judge 1's winner and the best return design (huts with name plates, real-day growth, plaques, desire paths, the settlement footprint as history), all grafted, and the concept closest to the camera the owner chose. But it carried the darkest empty state proposed: real-clock night tint 0.4, the hearth out and hut windows dark at 0 awake on a fresh evening, exactly when the owner watches; the largest scope (46 h full, 30 h v1); a 2x zoom that dropped pips to 24x20 px under its own 20 px rule; a 30 ms static-layer rebuild on every mark event inside a single-threaded frame; huts auto-placed by arrival order rather than chosen. |
| THE WIDE LEA (gather / build / fence / sow / water, pooled bridge, the Ring) | 47 | 47 | 48 | 142 | The most direct answer to "can chatters build their own spaces" (`camp`, `sow`, `water @name`, the minimap, the surveying plank and the four-hours QA gate are grafted). But it was the most Age-of-Empires-as-GAME: ~20 verbs and a pouch economy, the largest griefing and moderation surface (carved words, fences that could enclose), trail wear that decayed one level per stream-hour, a 2x zoom in the last 30 s of every round breaking the legibility floor three times an hour, a pooled bridge that needs 5+ contributors the channel does not have, and a 22 h v1 estimate not credible for that verb count. |
| WIDE COMMONS (compressed 60-minute day, Markov weather, three screens) | 41 | 46 | 46 | 133 | Best alive-at-zero mechanics (the compressed day keeps 80 % of watch time in daylight regardless of the real hour; Markov weather, tide, dawn flowers, weekly seasons all grafted or offered as a switch). But the least open: three screens, minimap hidden by default; no home or hut (sleepers curl in grass); a cairn that needs five distinct people; paths that heal over 7 days (a mark decaying); and the compressed sun asserts a false time on a stream whose brand is that nothing on screen is fake, so it is kept only as a disclosed, off-by-default lever. |
| BROADFELL (the cave logic moved outdoors, measured engineering) | 42 | 45 | 45 | 132 | The strongest engineering (sub-cell pan, BFS with a stuck detector, camera persistence, migration guard, whole-map ops forbidden, the brightest night floor, all grafted). But the least fresh, for an owner who asked for fresher: impassable copse / boulders / river reintroducing enclosure, zoom changes as cuts softened by a luminance dip, sleep-where-you-stop so nobody has a chosen home, the camp fire, cairns, harvest and seasons all deferred to v1.1, and the camera clamped so the map edge could appear on screen. Its "measured on this Mac" timings could not be verified from the brief and are treated as a reference, not a fact. |

### Camera styles (rendered mockups reviewed by the owner, `docs/mockups/`)

| Style | Owner verdict | Notes |
|---|---|---|
| **Top-down 3/4 settlement** (`topdown_A_dawn_empty.png`, `topdown_B_busy.png`) | **Chosen** ("the top down style is the best") | Whole region is land; huts, fields, trails and a river read at a glance and in the 320x180 tile; the minimap, time dial and land line sit in the corners; creatures front-facing with a flip; the cheapest projection for a moving 2D camera and for y-sorted painted props. |
| Isometric | Rejected | Diamond tiles read as franchise-adjacent (the one look art-rules bans by name), eight-direction sprites multiply the art cost, and isometric depth-sorting and pathing are the most expensive of the three for numpy/pillow. |
| Side-scroll with parallax (the judged winner's projection) | Rejected | A sky band and a horizon are handsome in a still but cost 20 of 110 rows, a 1D-ish wander and the smallest ground viewport; the owner's "big open areas that the living things move around" wants two axes. |

Also rejected, as always: any animate non-person (bird, animal, fish, insect, NPC, keeper avatar),
fake people or synthetic chat to fill the land (ADR-000), cutting or bypassing the moderation hold,
any breeding or child creature, hunger / death / decay, a fog of war that hides the land, isometric
diamond tiles, villagers or resource counters that would read as Age of Empires assets, a zoom below
0.75x, fences and carved words.

## Consequences

- **`docs/WORLD.md` sections superseded by `docs/OPENWORLD.md`:** §1 (identity: name, title,
  description, version), §2.2 (first 60 s), §3.4 (colony state: terrain, moss, nests, chambers →
  wear, marks, camps, fields, stones, raisings, land strips, camera, `bake_ver`), §4 (verbs: table
  replaced; `dig` removed; `go` / `camp` / `fire` / `sow` / `harvest` / `stack` / `swim` / `water` /
  `explore` added; the leading-verb rule), §5 region-5 content and region copy (the scene inside the
  unchanged box; the time dial and minimap; `SETTLED`; regions 6, 7, 9, 11 copy), §6 (art direction
  and budget: the painted-bake render path, the atlas interface, the modulation field), §7 (audio:
  beds replaced, stings extended), §8.1 (MENU), §8.2 (milestone actions: carve → raise / open), §9
  (keeper representation: lantern on a chain → beacon on a post), §10 (empty states), §12 (build
  order), §13 (risks). **Still normative:** `WORLD.md` §2.1 (the six wants), §3.1-§3.3 (files,
  identity, presence, energy, tiers, memory, bonds, care log, strikes), §8.3 (emergent events,
  extended), §11 (honesty and moderation, extended). `WORLD.md` gets a banner at the top pointing
  here. `CONCEPT.md` §5-§8 and §10 remain normative as ADR-004 stated.
- **The art of the individual parts moves to `docs/ART.md` and `stream/world/art/`** (the
  settlement-art workflow). `stream/world/pips.py`, the angular 4x sprite generator, is retired as
  the creature source (kept on disk for the rollback week; its frozen `genome` / `salt` fields stay in
  `world.json`). A creature's colour now comes from the art genome rather than a preset's six-colour
  set, so `!theme` themes the UI accent, not the people. `docs/art-rules.md` §3's sprite-shape tests
  are superseded by `ART.md`'s checklist; its principles (colour from the name, no default colour, no
  look-alike, no multiplication, no morality) stay.
- **`docs/art-rules.md` changes:** the rule-1 sentence becomes *"Every name on this land is a real
  person who chatted. The wind is just the wind."*; the "darkness means nobody / light means someone"
  lines and §4's cave-texture and 0-awake-light-source rules are replaced by the nature rule (nothing
  moves itself except a real person's pip; everything else is moved by wind, water or the sun), the
  no-animate-non-person list, "nature is declared, not counted", the no-fog-of-war rule, the
  no-whole-map-ops rule, the no-decay rule and an Age-of-Empires row under §3. §2 (absence is never
  punished) is unchanged.
- **`stream/WORLD_API.md`** is updated for `SteadingScene` (same contract shape: `frame`, `entities`,
  `events`, `command`, `platform_counts` reading waystone slots, `sim_to_screen` now camera-aware and
  returning `None` off-view), a `camera` member, the atlas interface, `entities()` gaining `y`,
  `facing`, `colour`, `camp` and `field`, and new events (`tuft`, `camp_built`, `camp_tier`, `sow`,
  `harvest`, `stack`, `raising_*`, `land_open`, `expedition`, `weather`, `bake_ready`).
  `stream/COMPOSITOR_API.md` is unchanged: no region moves.
- **`stream/layout.py` does not change**, so the redesign lands by hot-reload of `stream/world/*`,
  `stream/world/art/`, `stream/scenes/steading.py`, `stream/panels/world.py` and the copy-changed
  panels into the live snapshot while the cave is on air, with the ground bake pre-built offline;
  `scripts/swap-build.sh` is the fallback; the owner is told before either; ingest never drops.
  `hollow.py` and `world.json.bak` are the one-week rollback.
- **Render path.** The display is a painted, memory-mapped, per-season ground bake cropped per frame
  and modulated by a cell-resolution light field, not a 4x nearest-upscaled grid. Estimated ~8 ms per
  frame at 1x with 20 creatures and a moving camera (~10.5 ms at 0.75x), gated at under 12 ms scene
  average at 0.75x with 60 test pips after every reload; the 3 h gate measures it first and the
  fallback is a 2 px/cell bake. The bake runs in a background thread and never blocks a frame.
- **Persistence:** `world.json` moves to schema 2 with a guarded migration (identity fields
  byte-identical, pip count must match or the scene refuses to boot). The two existing pips keep
  their names and genomes; their burrows become camps in the Steading ring; their moss becomes
  credited flowers.
- **The honesty rule gains a mark rule:** every camp, fire, field, flower, tree, reed, stone, flag and
  path cell carries an owner that must exist in `pips`, asserted every 5 s; wear is written only under
  a real pip's step and the per-frame wear sum is checked; the ground bake is repainted only from those
  records; the minimap hides nothing and its walked fraction is a `len()`; the camera never frames
  emptiness as if someone were there. The two every-frame assertions from ADR-004 continue unchanged.
- **The QA tile gate changes** from "a light source at 0 awake" (which the cave failed at 3.9 % lit
  pixels) to renders at 00:00 / 06:00 / 12:00 / 18:00 in four seasons with a midnight mean ≥ 0.5 x
  noon and ≥ 60 % of world-band pixels above 0.12 luminance, the header legible, and no name drawn
  except real camp plates; plus a contrast sweep over every creature hue on each season's grass.
- **A 3-hour mock-frame gate precedes the build** (the owner asked for renders first): dawn, noon
  and 23:00 at 0 and 3 awake from the real `terrain.py`, `nature.py` and the atlas, not from the
  `docs/mockups/` scripts, with the per-frame path timed. If 23:00 reads cold the `world_day:
  "hour"` switch is flipped and re-rendered before anything else is built; if the timing misses, the
  bake resolution drops before anything else is built.
- **Cost.** Full concept about 52 agent-hours including the gate; v1 (a complete alive show) about
  40, three parallel agents over about a day and a half; a ~12 h v0 preview can be on air the same
  evening; v1.1 (`explore`, `water`, `sing`, the Markov chain, the zoom crossfade, the first raising,
  land strips) as keeper ships on air. The art workflow's hours are separate.
- **The channel's identity changes again.** Title, description and thumbnail move; `docs/promo/` is
  redone after the first Longgrass session with real frames; the version scheme continues (v0.6.0).
- **The owner's 020 questions are answered in the spec:** fully procedural (seed → elevation and
  moisture → biomes, sea, site, river carved downhill; deterministic and committed; chat changes are
  deltas painted into the ground); a huge number of chatters can build their own spaces (`camp` where
  you stand, one field each, land opening in 320-cell strips, render cost per visible window not per
  chatter, the camera surveying real marks, `go home` panning to your camp, labels on speak in
  crowds).
- **What does not change.** ADR-000 (no synthetic engagement), ADR-001 (RTMPS), ADR-002 (secrets
  outside the repo; the 017 scrub is already applied to the live processes), the two-FIFO lockstep
  A/V pipeline, the RoundEngine lifecycle, `agents/duty.py` and the 017 trust boundary (chat is data;
  keeper builds stay inside the world sandbox), the -18 dBFS master, the 20 px legibility floor, the
  3 s hold, absence-never-punished, no animate non-persons, the never-restart-the-live-stream rule,
  and the fact that the 100-viewer target is the owner's and the report will state the real numbers.
