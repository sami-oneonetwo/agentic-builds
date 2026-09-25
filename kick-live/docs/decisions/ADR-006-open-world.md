# ADR-006: Open-world redesign — LONGGRASS replaces the cave

Status: accepted (2026-09-25, synthesizer step of the `kick-live-open-world` workflow; owner-invited,
owner may overturn after the mock-frame gate). ADR-005 is not in the tree at the time of writing;
this number follows the workflow brief.

## Context

PIP HOLLOW (ADR-004, `docs/WORLD.md`) went on air at 17:58 local as macro-ship v0.5.0 (journal 019).
The plumbing held: honesty self-test PASS, a phantom pip quarantined at boot, a user hidden inside the
3 s hold never drew a name, 0 honesty violations over 330 frames, HLS probe PASS, 0 secrets in the
render processes' environment. The owner's first live minutes worked as designed (`hello` woke their
pip, header 0 → 1 AWAKE verified from Kick playback).

The owner's verdict minutes later (journal 020): *"this feels less like a world and more like a
prison. Can't we make this more open? Outside and with space. Age of Empires style maybe? Big open
areas that the living things chat creates can move around. I need some fresher ideas, this is cold
and stagnant."* In the addendum the owner picked the Settlement direction, asked for renders first,
and asked whether the world is fully procedural and whether a huge number of chatters could build
their own spaces.

Diagnosis shared by the workflow: the cave's art rule *"darkness means nobody"* turned honesty about
PEOPLE into emptiness on SCREEN. A sealed 320x110 box with a ceiling, a floor line and sleepers in
numbered burrows reads as a cell, and at this channel's size (two humans ever) the dark empty state
is the default state. The correction is a distinction, not a loosening: honesty applies to WHO is on
the land (every named creature and every mark is a real chatter); the land itself may be alive
(wind, water, sun, seasons, growth). No animate non-person creatures, no fake people, ever.

What stays fixed: the headless Python 3.9 pillow/numpy compositor at 1280x720 30 fps with a low-res
sim grid upscaled by integer NEAREST (proven cheap); relay + hot-reload deploys; real Kick chat as
`{name, text}` in 1-3 s; the 3 s moderation hold (nameless until cleared); `world.json` and
`builders.json` persistence; the 3-minute embodied A/B/C round; keepers building `!idea`s live as
real code; exact-token verbs (now with a leading-verb rule for short natural phrasings, from the
owner's `plant a flower` in journal 019); generated audio only; no IP (nothing that looks like Age
of Empires assets, Thronglets or any franchise); ADR-000; the never-restart-the-live-stream rule.

The workflow ran five concepts against that brief and three judges scored each on six criteria
(open, alive at zero, first message, return, together, feasibility; 10 each, 60 per judge, 180 total),
named grafts and listed fatal flaws.

## Decision

Build **LONGGRASS** as specified in `docs/OPENWORLD.md`: a wide, windy valley seen from a slow camera
that follows the life in it. The frame is a 320x90-cell ground window (at the standard 4x zoom, with
3x and 6x) over a 960x270-cell procedurally generated map that widens at head-count milestones,
under a 20-row sky band with the real sun and moon, drifting clouds and a far ridge that parallaxes
with every camera move. Any message tumbles a nameless seed-pod in from the upwind edge for the 3 s
hold; when it clears, a pip steps out of the grass with the chatter's name and colour, walks where
they say (`go north`, `go river`, `go home`), wears a path that never fades, plants a tree that grows
by real calendar days, lights a fire that becomes their camp (hollow → stone ring → lean-to → hut by
real sessions), and stacks a stone on the moot cairn that the whole chat is raising toward a keeper
bridge. The land is alive at zero: wind whose base speed is the real chat rate, a river, cloud
shadows, a sun crossing the sky on the real clock, seasons, a seeded weather chain, and a camera that
drifts over real marks when nobody is awake. Night has a hard 0.55 luminance floor. Sleepers are camps
under the open sky with wind-rung bells, not silhouettes in holes. The keepers are a lantern on a tall
pole (the beacon) and raise structures or open new land instead of carving rock.

The new one-sentence rule, which is also the art rule:

> **Every name on this land is a real person who chatted. The wind is just the wind.**

The world lands as macro-ship **v0.6.0** by hot-reload while the cave is on air (`layout.py` is
untouched), after a 3-hour mock-frame gate in which the owner judges dawn, noon and 23:00 renders
from the real terrain and nature modules. Stream title: `Say anything in chat. A creature walks out
with your name` (57 chars). Category stays Software & Game Development for the first session, then
the A/B on real `viewer_count` as before.

### Grafts adopted from the other four concepts (all three judges' lists, merged)

- **From THE COMMONS:** plants grow by **real calendar days** even while the stream is off (the
  concept as proposed grew trees by attended sessions, so there was no "grew while you were gone");
  the camp ladder compressed to this channel's scale with a hut at 10 sessions, not 25, using the
  "hut from real sleep records with a rotating plate" idea; one shared **stone ladder** (20 / 60 /
  150 stones → the Ford bridge, the well, the hall roof) with a plaque naming the top stackers, so the
  Age-of-Empires feeling of a structure rising from a stockpile exists without an economy; `raising
  day` as a round event; the **3 h mock-frame gate** before the build; the ticker honesty line and the
  "nature is declared, not counted" list; the hearth lit only when a real person lit it this session.
- **From WIDE COMMONS:** the seeded **Markov weather chain** per world-hour so weather changes on its
  own between rounds; the off-frame **edge arrow** `@sami →` in the speaker's colour; **trail
  naming** when 3+ people walk the same route in a session; `swim` (40 cells downstream and out);
  the "wind took that one" line for a seed hidden inside the hold; the **compressed 60-minute world
  day** kept as a single config switch, off by default, disclosed on the ticker when on, moon phase
  real either way, as the lever if the moonlit evening frames still read cold.
- **From THE WIDE LEA:** `camp` so a person chooses where they live (placement inside the actor's
  radius, never crowding another's camp); `water @name` as a care verb written to the target's
  care log (v1.1); the **always-on minimap** with the camera rectangle, name-coloured dots and camp
  squares; the plank copy `surveying the valley · last here: @sami yesterday 10:40` and the
  pooled-goal readout `stone 13 of 20 · 4 people`; the QA gate that renders 00:00 / 06:00 / 12:00 /
  18:00 in all four seasons.
- **From BROADFELL:** the camera and render engineering as the implementation of `camera.py`:
  integer zooms only, sub-cell pan by cropping `(vw+1)x(vh+1)` and pasting at the fractional offset,
  a 0.8 s time constant with a 60 cells/s cap, zoom only at rest with hysteresis, camera pos and zoom
  persisted every 5 s so a hot-reload resumes without a jump; the **6x close-up** when exactly one
  pip is awake and still (72x60 px creature); the **coarse 30x11 BFS** route grid with a slide rule
  and a 3 s stuck detector plus the 5-minute random-target pathing test; the **night floor raised to
  0.55** with moon glitter on water; the **migration guard** (run on a `/tmp` copy, identity fields
  byte-identical, refuse to boot on a pip count mismatch, `hollow.py` kept a week); the rule that no
  whole-map operation may run in the per-frame path, asserted as scene avg under 8 ms at 3x with 60
  test pips after every reload; footstep timbre by the ground cell under the pip and the river bed
  mixed by the camera's distance to water.

### Fatal flaws removed from the winning concept as proposed

- **Return too slow for this channel:** a hut at 25 sessions and trees that grew only across attended
  sessions. Now the camp ladder is 1 / 2 / 5 / 10 sessions and growth is by real days.
- **Mild decay:** path wear lost 1 per stream-hour above 40, a real mark fading, against the written
  absence-never-punished rule. Now wear never decrements.
- **The kite:** an object moved by wind and legal under the rule as written, but the one thing on any
  of the five screens a viewer could read as a bird. Replaced by the beacon, a lantern on a tall pole,
  with a lit dot on the minimap so it is visible from anywhere; the art rule names it.
- **The zoom table ignored the sky band:** 3x was specified as 426x146 cells but the ground window is
  1280x360 px, so 3x is 427x120 (4x 320x90, 6x 214x60). Corrected; no 2x, no 5x.
- **A camera cut to the moot at 0:00** broke the no-cuts rule. Now an ease at the pan cap; the only
  cut is the first frame of a session.
- **No build, resources or structures**, the opposite of the owner's Settlement pick. Now one
  resource (stone), the cairn, three keeper raisings and `camp`, capped there so it never becomes an
  RTS economy.
- **No minimap** and a wander cap of 140 cells that made the nine screens smaller than they felt. Now
  an always-on minimap, a 200-cell idle radius with 30 % moot gravity, and land opening at 10 / 25 / 50.
- **2D pathing under-specified.** Now BROADFELL's BFS grid, slide rule, stuck detector and test.
- **The cairn needed five distinct people** in one graft (unreachable at a channel with two humans).
  Now a cairn is named at three distinct stackers, the first milestone.

## Alternatives considered

Scores per judge out of 60 (open, alive at zero, first message, return, together, feasibility; 10 each).

| Concept | Judge 1 | Judge 2 | Judge 3 | Total /180 | Why not |
|---|---|---|---|---|---|
| **LONGGRASS** (valley, horizon band, lead-room camera, camps and bells) | 48 | **54** | **52** | **154** | Chosen: first on two of three sheets, best on open and first message. The only concept that puts a horizon on screen (the far ridge parallaxing with every camera move is what turns frame edges into "the world continues"), the best first minute for a lone stranger at 11 pm (the pod on the wind, lead room, `the wind was already blowing`, every real sleeper's bell ringing west to east), wind-rung bells pitched by each sleeper's name so an empty valley sounds like the people who have been there, wind speed as chat rate, land that literally widens at milestones (the owner's "chunked map that grows outward"), the cheapest full concept (34 h) with `layout.py` untouched. Its flaws (slow camp ladder, session-based growth, mild path decay, the kite, the zoom table, no build, no minimap) are all fixed above. |
| THE COMMONS (16-screen map, huts on first sleep, stone ladder, plaques) | **49** | 51 | 49 | 149 | Judge 1's winner and the best return design (huts with name plates, real-day growth, plaques, desire paths, the settlement footprint as history), all grafted. But it carried the darkest empty state proposed: real-clock night tint 0.4, the hearth out and hut windows dark at 0 awake on a fresh evening, exactly when the owner watches; the largest scope (46 h full, 30 h v1) for a channel whose owner judged the last build within minutes; a 2x zoom that dropped pips to 24x20 px under its own 20 px rule; a 30 ms static-layer rebuild on every mark event that lands inside a single-threaded frame; huts auto-placed by arrival order rather than chosen. |
| THE WIDE LEA (gather / build / fence / sow / water, pooled bridge, the Ring) | 47 | 47 | 48 | 142 | The most direct answer to "can chatters build their own spaces" (`camp`, `water @name`, the minimap, the surveying plank and the four-hours QA gate are grafted). But it was the most Age-of-Empires-as-GAME: ~20 verbs and a pouch economy, the largest griefing and moderation surface (carved words, fences that could enclose), trail wear that decayed one level per stream-hour, a 2x zoom in the last 30 s of every round breaking the legibility floor three times an hour, a pooled bridge that needs 5+ contributors the channel does not have, no sky or horizon so "outside" was asserted by palette alone, and a 22 h v1 estimate not credible for that verb count. |
| WIDE COMMONS (compressed 60-minute day, Markov weather, three screens) | 41 | 46 | 46 | 133 | Best alive-at-zero mechanics (the compressed day keeps 80 % of watch time in daylight regardless of the real hour; Markov weather, tide, dawn flowers, weekly seasons all grafted or offered as a switch). But the least open: three screens, no sky, minimap hidden by default; no home or hut (sleepers curl in grass); a cairn that needs five distinct people; paths that heal over 7 days (a mark decaying); and the compressed sun asserts a false time on a stream whose brand is that nothing on screen is fake, so it is kept only as a disclosed, off-by-default lever. |
| BROADFELL (the cave logic moved outdoors, measured engineering) | 42 | 45 | 45 | 132 | The strongest engineering (integer zooms, sub-cell pan, BFS with a stuck detector, camera persistence, migration guard, whole-map ops forbidden, the brightest night floor, all grafted). But the least fresh, for an owner who asked for fresher: no sky or horizon, impassable copse / boulders / river reintroducing enclosure, zoom changes as cuts softened by a luminance dip, sleep-where-you-stop so nobody has a chosen home and sleepers scatter as unlabelled humps across nine screens, the camp fire, cairns, harvest and seasons all deferred to v1.1, and the camera clamped so the map edge could appear on screen. Its "measured on this Mac" timings could not be verified from the brief and are treated as a reference, not a fact. |

Also rejected, as always: any animate non-person (bird, animal, fish, firefly, NPC, keeper avatar),
fake people or synthetic chat to fill the land (ADR-000), cutting or bypassing the moderation hold,
any breeding or child creature, hunger / death / decay, a fog-of-war that hides the land, isometric
diamond tiles, villagers or resource icons that would read as Age of Empires assets, and a 2x zoom.

## Consequences

- **`docs/WORLD.md` sections superseded by `docs/OPENWORLD.md`:** §1 (identity: name, title,
  description, version), §2.2 (first 60 s), §3.4 (colony state: terrain, moss, nests, chambers →
  wear, marks, camps, stones, raisings, land strips, camera), §4 (verbs: table replaced; `dig`
  removed, `go` / `fire` / `camp` / `stack` / `swim` / `water` / `explore` added, leading-verb rule),
  §5 region-5 content (the scene inside the unchanged box; regions 6, 7, 9 copy), §6 (art direction
  and budget), §7 (audio: beds replaced, stings extended), §8.1 (MENU), §8.2 (milestone actions:
  carve → raise / open), §9 (keeper representation: lantern on a chain → beacon on a pole), §10
  (empty states), §12 (build order), §13 (risks). **Still normative:** `WORLD.md` §2.1 (the six
  wants), §3.1-§3.3 (files, identity, presence, energy, tiers, memory, bonds, care log, strikes),
  §8.3 (emergent events, extended), §11 (honesty and moderation, extended). `WORLD.md` gets a banner
  at the top pointing here. `CONCEPT.md` §5-§8 and §10 remain normative as ADR-004 stated.
- **`docs/art-rules.md` changes:** the rule-1 sentence becomes *"Every name on this land is a real
  person who chatted. The wind is just the wind."*; the "darkness means nobody / light means someone"
  lines and §4's cave-texture and 0-awake-light-source rules are replaced by the nature rule (nothing
  moves itself except a real person's pip; everything else is moved by wind, water or the sun), the
  no-animate-non-person list, "nature is declared, not counted", the no-whole-map-ops rule, the
  no-decay rule and an Age-of-Empires row under §3. §2 (absence is never punished) and the sprite
  rules in §3 are unchanged.
- **`stream/WORLD_API.md`** is updated for `LonggrassScene` (same contract shape: `frame`,
  `entities`, `events`, `command`, `platform_counts` reading banner slots, `sim_to_screen` now
  camera-aware and returning `None` off-view), a `camera` member, `entities()` gaining `y`, `facing`
  and `camp`, and new events (`pod`, `camp_built`, `camp_tier`, `stack`, `raising_*`, `land_open`,
  `march`, `weather`). `stream/COMPOSITOR_API.md` is unchanged: no region moves.
- **`stream/layout.py` does not change**, so the redesign lands by hot-reload of `stream/world/*`,
  `stream/scenes/longgrass.py`, `stream/panels/world.py` and `stream/panels/colony.py` into the live
  snapshot while the cave is on air; `scripts/swap-build.sh` is the fallback; the owner is told
  before either; ingest never drops. `hollow.py` and `world.json.bak` are the one-week rollback.
- **Persistence:** `world.json` moves to schema 2 with a guarded migration (identity fields
  byte-identical, pip count must match or the scene refuses to boot). The two existing pips keep
  their names, colours and genomes; their burrows become camps; their moss becomes credited flowers.
- **The honesty rule gains a mark rule:** every camp, fire, flower, tree, reed, stone, flag and path
  cell carries an owner that must exist in `pips`, asserted every 5 s; wear is written only under a
  real pip's step and the per-frame wear sum is checked; the camera never frames emptiness as if
  someone were there. The two every-frame assertions from ADR-004 continue unchanged.
- **The QA tile gate changes** from "a light source at 0 awake" (which the cave failed at 3.9 % lit
  pixels) to renders at 00:00 / 06:00 / 12:00 / 18:00 in four seasons with a midnight mean ≥ 0.5 x
  noon and ≥ 60 % of world-band pixels above 0.12 luminance, the header legible, and no name drawn
  except real camp plates.
- **A 3-hour mock-frame gate precedes the build** (the owner asked for renders first): dawn, noon
  and 23:00 at 0 and 3 awake from the real `terrain.py` and `nature.py`, not from the
  `docs/mockups/` scripts. If 23:00 reads cold the `world_day: "hour"` switch is flipped and
  re-rendered before anything else is built.
- **Cost.** Full concept about 41 agent-hours including the gate; v1 (a complete alive show) about
  28, two to three parallel agents over a working day plus a morning; v1.1 (`explore`, `water`,
  `sing`, `sow`, the first raising, land strips) as keeper ships on air. Frame cost is estimated at
  ~6 ms with 20 creatures and a moving camera at 4x and gated at under 8 ms scene average at 3x with
  60 test pips.
- **The channel's identity changes again.** Title, description and thumbnail move; `docs/promo/` is
  redone after the first Longgrass session with real frames; the version scheme continues (v0.6.0).
- **The owner's 020 questions are answered in the spec:** fully procedural (seed → height and
  moisture → biomes, river carved downhill, deterministic and committed; chat changes are deltas);
  a huge number of chatters can build their own spaces (`camp` where you stand, land opening in
  320-cell strips, render cost per visible window not per chatter, the camera touring real marks,
  `go home` panning to your camp, labels on speak in crowds).
- **What does not change.** ADR-000 (no synthetic engagement), ADR-001 (RTMPS), ADR-002 (secrets
  outside the repo; the 017 scrub is already applied to the live processes), the two-FIFO lockstep
  A/V pipeline, the RoundEngine lifecycle, `agents/duty.py` and the 017 trust boundary (chat is data;
  keeper builds stay inside the world sandbox), the 8 legible palette presets, the -18 dBFS master,
  the 20 px legibility floor, the 3 s hold, absence-never-punished, no animate non-persons, the
  never-restart-the-live-stream rule, and the fact that the 100-viewer target is the owner's and the
  report will state the real numbers.
