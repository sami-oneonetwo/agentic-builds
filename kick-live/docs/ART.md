# SETTLEMENT art bible

The canonical art module is `stream/world/art/` (`creatures`, `tiles`, `buildings`, `props`, `hud`). Every picture in
`docs/art/final/` is rendered FROM it by `docs/art/final/render_final.py`. This page is the contract the module keeps:
a change that breaks a rule here is reverted, and the module's review sheets (`creatures.sheet_image`,
`buildings.kit_image`, `props.kit_image`, `hud.style_sheet_image`, `tiles.atlas_image`) are checked against it.

Lineage: Studio C's world (bold clean 1-px outlines, flat chunky tiles, text off the world) chosen by the owner, with
the settlers-round people ("small toy-people", the tally winner) as the base, and these grafts folded in from
settlers-tall: the contact/pass walk with knee and boot tilt and opposite arm swing, the two-frame hop, `look_l` /
`look_r`, `point`, the sun-vector parameter with per-octant caching, kit-as-identity (staff, lantern, shoulder tool),
canopy scallops. The fatal flaws of both are gone: no skin-tone table, no goggle eye-whites, a walk that moves, a hop
with anticipation, a hood with a real face window, sprites lit by the same sun as the land in every scenario.

---

## 1. The one rule above the others

**Every named settler is a real person who chatted.** A settler exists only because a moderated chat record with a
real Kick username created it; its look is a pure function of that username. There are no animals, no NPCs, no
villagers, no mascots. Nature (trees, flowers, water, fire) supplies the rest of the life. Every number on the HUD is a
`len()` over real records. Seeds have no name and no colour until the hold clears.

## 2. Silhouette language: small people

A settler is a **person**, not a shape: a big round head on a short neck, a belted tunic, two arms that gesture with
mitten hands, two legs with round shoes. Seen from the front in the 3/4 top-down view. Head slightly wider than the
shoulders (the lovability lives in the head); feet and hands visible in every standing frame; at 320x180 a settler is a
coloured figure with a cream dot on top, not a blob.

| | sprout (tier 0) | settler (1) | builder (2) | elder (3) |
|---|---|---|---|---|
| standing height S at 1x | 26 px | 30 px | 34 px | 42 px |
| heads tall | 2.1 | 2.5 | 2.5 | 3.0 |
| head radius R (body units, 1.0 = S) | 0.238 | 0.20 | 0.20 | 0.167 |
| hem (leg length) | 0.24 | 0.27 | 0.27 | 0.29 |
| worn | hair only | hair, belt | + hat (beanie / hood) + kit | + elder hat + accent cape |
| frame box (W x H) | 1.6 S x 1.72 S, ground point at (W/2, H - 0.14 S) | | | |

Body units (x right, y up from the ground point): head centre `1 - R`; neck 0.05 under the chin (0.035 for sprouts);
tunic top `head_bottom - neck + 0.03` (tucks under the chin outline); shoulders +/-0.165, hem +/-0.20, a hem shade band
and a belt at 34 % of the torso with a 0.02 accent buckle; legs at +/-0.082, stroke 0.10, shoes 0.078 x 0.046
ellipses; arms stroke 0.085 from the shoulder pivot (`top - 0.045`) with an elbow, hands r 0.055. Growth is taller and
more dressed, never bigger-headed: sprout -> settler adds the belt, builder adds hat + kit, elder adds one head of
stature, an elder hat and a cape.

Zoom 2 renders at the same working resolution (4x supersample at 1x, 2x at zoom 2) so a frame costs the same at both.

## 3. Genome: everything from the name, nothing hand-picked

`creatures.genome(username)` returns readable values; `render()` reads the same genes.

| gene | source | values |
|---|---|---|
| **hue** (tunic = the name colour) | 31-multiplier hash of the lower-cased name, `% 1000 / 1000 * 270`, +90 when >= 70 | a 270 degree wheel that SKIPS the grass band 70-160. HSV(hue, 0.64, 0.90). Labels, roofs, banners, fields use it |
| accent | hue + 150 + 40 * sha1[6] % 3, grass band skipped | HSV(., 0.60, 0.92): hats, scarf, belt, badge, cape, blanket, hut trim |
| outline | hue at (0.60, 0.30) mixed 50 % toward ink | never pure black |
| hair | (sha1[0] + sha1[9]) % 6 | bob, tuft, crop, bun, flower, curlcap |
| hair colour (yarn) | sha1[1] % 6 | cocoa #4A342E, rust #AA623C, straw #ECC664, cream #F6EEDE, plum #60405C, or the accent |
| hat (worn from builder) | sha1[8] % 8 -> (0,0,0,1,1,2,0,1) | none 4/8, beanie 3/8, hood 1/8 |
| elder hat | sha1[7] % 2 | brim, stocking (replaces the hat at tier 3) |
| accessory / kit (from builder) | sha1[2] % 8 | scarf, belt, satchel, badge, apron, staff, lantern, tool |
| cheeks | sha1[3] % 3 | blush, freckles, plain |
| eyes | sha1[4] % 3 | dots, tall, wide (pupil spacing / shape only) |
| side | sha1[5] % 2 | which side things hang on, which hand waves |

Under a hat only bob drops and the flower stay; spikes and buns never poke through a crown. Hats come off for sleep.

## 4. Palette

Per settler at most five colours plus cream and ink: main, accent, outline (+ derived darks), yarn, face.

| role | value |
|---|---|
| face and hands (everyone) | cream #FAECD4 tinted 6 % toward the tunic. **A toy colour, never a skin tone** |
| ink (pupils, mouth) | #261E1C · glint #FFFCF6 |
| blush #EE7E82 (alpha 125) · freckles #C48468 · heart #EC5468 · sparkle #FFE478 | |
| legs | hue at (0.45, 0.42) mixed 50 % with #5A463C · shoes = outline mixed 50 % with #46302E |
| props on people | berry #DE4052, stone #A09C92, wood #966A42, iron #787C84, lantern #FCD260 |
| ground shadow | #18120C at 36 % (60 % on hop1 = 24 %) |

Terrain (`tiles.FLAT` / `_KEYS`, summer values): grass #68A44E (spring #76B25C, autumn #AA984E, winter #BAC2B6),
meadow = grass + 5 % toward #FFFFC8, forest floor = grass x 0.78, hill #9CA664, tree #3A7A42 / lit #68AC5C, sand
#EAD6A0 / #CCB47C, water shallow #5CB2CE, deep #2E70A6, ripple #CEECF4, rock #928E82 / #B8B4A6 / #5C5850, dirt
#C8AC76 / #A08256, cobble #BCAA8A / #D6C6A6, grout #846C50, soil #805A3A / #62422A, sprout #A0D870, leaf #569844,
ripe #F4AC40, trunk #60422C, tile outline #2C241E. Flowers: #FCF6E8, #FAD260, #F6A6B8, #C8AAFA, #FF8A6E.

Buildings: plaster #EEE0C0 / shade #D6C4A0, door #5C3E2A, pane lit #FFE896 / dark #7096B0, tent canvas #E2CEA8,
roof = owner main, roof light = main + 28 % white, roof dark = main + 30 % outline, trim = owner accent.

Fire: #FFEC96 core, #FFBE46, #EC6E30, #AA3422 rim. Glows: lantern (255,186,96) r 46 @ 0.42; window (255,214,130)
r 22 @ 0.30; campfire (255,170,80) r 70 @ 0.50; beacon (255,180,90) r 110 @ 0.35 (night: 0.55 / 0.42 / 0.70 / 0.55).

HUD: header #1A1410, panel (28,22,18) @ 226, border #E8D6B2, cream #F8F0E0, muted #C0B296, gold #F7C456, live #EE483C,
ok #7ECE80.

## 5. Faces

Two ink pupils (r 0.033, ~2 px at 34 px, 4 px at 2x) under a faint eyelid hairline at 59 % alpha: the lid is what makes a
dot read as an eye. No eye whites (they read as goggles). A glint appears on `big` eyes and at zoom 2. Blink = flat
lines, sleep = shallow "u" arcs, joy = "n" arcs. `look_l` / `look_r` shift the head 0.04 and the pupils 0.03 toward
the speaker so no flip (and no mirrored satchel) is needed. Mouth: smile arc, "o", speak notch, grin chord, "w"
(love), flat (sleep / effort). Blush or freckles by gene. Everyone has the same face; only colour and kit vary.

## 6. Sticker outlines and light

Every part carries its own outline (1.0 px at 26 px, 1.3 px at 34, 2.6 px at 2x) drawn at supersample and
downsampled premultiplied, so arm over torso over leg stays legible after a 3 Mbps encode.

Light is one sun for the whole world: `sun=(sx, sy)` is the screen-space unit vector toward the sun. Sprites get a warm
rim (#FFE2AA, 30 %) on the sun edge and a cool violet shade band (#3C325A, 28 %) on the far edge; ground shadows slide
0.05 S away from the sun; tree lobes, hut walls and roofs shade the same way. `tiles.sun_vector(hour)` gives east low
at dawn, high at noon, west low at dusk, moon high at night. Settler frames are cached per sun OCTANT (8 buckets); a
compositor that moves the sun through the day rebuilds sheets at octant changes only (roughly every 1.75 h of world
time), so cache memory is 1 octant x settlers x tiers, not 8x.

## 7. Animation: 23 frames, squash-and-stretch in the geometry

| frame | pose | timing (compositor plays; the sheet supplies poses) |
|---|---|---|
| idle0 / idle1 | breath: 1.03 x 0.97, head dips 0.008 | alternate every ~0.8 s |
| blink | flat lines | 1 in 6 idles, 4 ticks |
| look_l / look_r | head 0.04 + pupils 0.03 toward the side | while someone within ~200 px speaks |
| walk0 walk1 walk2 walk3 | **contact L**: left leg planted forward (+0.035), right leg lifted behind with a knee at hip-0.10 and the shoe at 0.155 tilted 22 deg, arms swing opposite (forward arm out + up, back arm low), lean 4 deg toward travel · **pass**: legs together, one at 0.075, body up 0.025 · contact R · pass | 8 fps (4 ticks per frame at 30 fps); facing = direction of travel (mirror) |
| hop0 / hop1 | anticipation squash 1.06 x 0.86, knees bent out, arms swept back, mouth "o" · airborne 0.95 x 1.08, lift 0.27, legs tucked (shoes tilted 28 deg), arms up, big eyes, shadow 62 % | hop0 x3 ticks, hop1 x6 on a parabola, hop0 x2 |
| wave0 / wave1 | one arm over the head, open hand, wobble 0.07, grin on wave1 | alternate every 0.25 s |
| point | arm straight out toward +x, other hand on the hip, gaze right, mouth "o" | hold (mirror for -x) |
| sit | upper body drops by the leg length, legs out toward the camera with soles, hands on knees, shadow 112 % | hold |
| sleep | curled on one side under an accent blanket with a folded edge, shoes peeking, hand under the cheek, hat off, zz | alternate with a 1 % breath scale |
| carry_berry / carry_stone / carry_tool | two-handed hold at belly height (a basket heaped with berries, a boulder, a mallet held diagonally); hands 0.115 apart, item in FRONT of the hands | while walking to / from a farm, quarry, build site |
| speak0 / speak1 | mouth "o" then notch, head bob +0.02 / -0.006, one gesture hand | alternate every 6 ticks while the pill shows |
| joy | both arms up, "n" eyes, grin, two sparkles, up 0.04 | 1 s on a tier-up, a vote win |
| love | hands clasped, big eyes with glints, "w" mouth, a heart at the side | 1 s on feed / pet / gift |

Elder capes flare +0.06 on hop1. `creatures.shadow()` returns the ground ellipse alone so a hop can move the body up
the parabola while the shadow stays on the ground.

## 8. Tile rules

- 32 px tiles, flat base + chunky marks, drawn at 3x and downsampled. **Nothing crosses a tile edge.**
- Categories (`tiles.CAT`): water_deep, water_shallow, sand x3, grass x4, meadow x4, forest_floor x3, hill x3, rock x3,
  path0/1/2 x2 (grass with trodden patches / worn dirt with a pale centre, crumbs and grass creeping in / cobbles with a
  polished centre stone), farm0-3 (tilled, sprouts, leafy, ripe).
- Wind phase 0-3 played 0 1 2 3 2 1 (tufts lean, flowers bob); ripple phase 0-3 looped (crests drift down, seamless).
  Season 0..4 recolours grass, hill, trees.
- Meadow tiles carry a flower DRIFT: 3-5 blooms of one colour on a curve plus one stray, so flowers read as coloured
  streaks at 320x180 rather than confetti.
- The ground painter (`tiles.Ground`) takes a category map at **4 px per cell**: tile textures continue across cells
  (indexed by world pixel mod 32, variant hashed per tile), biome-group edges get a 1 px dark line (x0.70), water
  within 2 cells of land gets foam dithered by the ripple phase, and an optional per-cell shade map (relief along the
  sun, mottle) multiplies the land. `repaint(region)` re-gathers one cell rectangle after a path wears in or a farm is
  tilled.
- `tiles.grade(rgb, hour, water)`: 10:00-16:00 untouched; dusk ramp 16:00-18:00 to land x(1.06, 0.84, 0.64) + (12, 2, 0)
  while water keeps x(0.84, 0.86, 1.02) + (4, 8, 24); dawn 05:00-10:00 cool (#D6CCEC) fading out; night 20:00-05:00 a
  blue-violet multiply (0.80, 0.86, 1.18) whose brightness never drops below the **0.55 floor**. Sprites are not graded:
  the sun-vector rim/shade and the lit props carry the hour on the figures.

## 9. Building kit

`buildings.render(kind, tier, colour, seed, lit, sun) -> (RGBA, (dx, dy))`; blit at `(ground - d)`. Roof = owner main,
trim = owner accent, so a hut is a colour dot that says whose it is.

| kind | tiers |
|---|---|
| hut | 0 tent (canvas walls, colour pyramid, peg ropes) · 1 hut, 1 tile (pitched / dome / tent roof by seed) · 2 + chimney + accent sign · 3 hall, 2 tiles, pitched, two signs |
| well · garden (owner's flowers in a bed) · fence_h / fence_v (tier = tiles) · banner (seed = flutter phase 0-2) · lantern (lit) · smoke (seed = phase 0-2) | |

Footprint: a hut is w x 1 tiles; the roof rises 10 px above and overhangs 3 px; the front wall strip is the bottom 10 px.
Walls are cream plaster with the shade side away from the sun and a lit eave line; ground shadows away from the sun.

## 10. Props

`props.*` return RGBA arrays; ground point = `props.anchor(spr)` = (W/2, H-4). Trees by **age** 0-3 (sapling: a stick
with three leaves; young; grown; old, canopy R 6/9/12/16) with a dark under-canopy, relit lobes, lit lobes and leaf
scallops toward the sun, a light crown, trunk + trunk shadow, sway by wind phase. Bushes (3 lobes, berries on odd
variants), flower clumps (one colour each), stones (3 sizes), the **cairn** (1-5 stacked stones = milestones), the
**waystone** (a standing stone with a colour mark in a settler's colour), the **campfire** (stone ring, crossed logs,
4 flame phases + embers, or cold), the **beacon** (a tall post banded in the founder's colour with an iron fire basket,
4 flame phases). Glows are additive discs; cloud shadows are darken-only.

## 11. HUD rules

- Text lives in the frame, never on the world. Header 64 px (opaque), band 192 px of three translucent panels, caption
  24 px. **Every text size >= 20 px** (`hud.font` raises below 20). Sizes: title 40, header 22, panel title 22, body 22,
  pill 20, caption 20. Fonts: Arial Rounded Bold (display), Verdana / Verdana Bold (body, pills).
- The world carries only show-on-speak pills: the settler's **head portrait** (`creatures.head_icon`, 24 px) + the name
  in the settler's colour (20 px bold) + a tail, placed above the head and pushed upward by `hud.place_pills` when two
  would overlap. Bubbles are rare; chat text goes to the log.
- Panel lines are truncated with an ellipsis (`fit_segments`); nothing runs under the minimap.

## 12. What makes ours ours (and explicitly not Thronglets)

- **People, not creatures.** Thronglets are yellow bipedal critters with animal proportions and a single species look;
  ours are small people with a belted tunic, a neck, hats, hair and hand-held kit, in a 270-hue wheel where the colour is
  the person's name colour. No default yellow, no shared species body.
- **One toy face for everyone.** Not a skin tone, not a species face: cream, tinted toward the tunic. Identity is hair,
  hat, kit and colour, never features.
- **Kit as identity.** Staff, lantern, satchel, shoulder mallet, apron, scarf, badge, belt: a settler looks like they do a
  job in the settlement. Elders get stature, a hat and a cape, not size.
- **Real gestures.** Long enough arms to wave over the head, point, carry a basket; a walk with a knee; a hop with an
  anticipation frame. Squash-and-stretch happens in the geometry, never by scaling the bitmap.
- **The village is the chatters' colours.** Roofs, banners, fields, waystones and pills all carry the name hue.
- **Light is shared.** People, trees, huts and fire sit in one sun; night keeps a floor so no one disappears.
- Nothing here is a franchise sprite: no Pokémon, Stardew, Age of Empires, Thronglets shapes, names or palettes.

## 13. Caricature-avoidance rule

The face is one cream for everyone; there is no skin-tone gene and none may be added. Hair colours are yarn colours
(cocoa, rust, straw, cream, plum, accent) drawn independently of everything else, and hair styles are toy shapes (a bob
cap, tufts, a crop with a scalloped fringe, a bun, a flower, a pom cap). No beards, dresses, jewellery, headwear or
features that map onto a real-world ethnicity, religion, gender or costume; the hood is a traveller's cloak hood with a
wide face window and appears on 1 in 8. Gender-neutral by default: nothing in the genome names or implies one. A
reviewer who can screenshot a settler and caption it as a real-world group has found a bug; fix the generator, not
the hash.

## 14. Legibility checklist

Before a ship, on the final renders:

- [ ] **1x (1280x720):** every settler shows head + torso + two legs; hands visible in idle; the walk contact frame
      differs from idle by a lifted shoe (>= 3 px) and a raised arm; pupils are 2 px dots; the pill portrait is a face.
- [ ] **320x180 thumb:** every settler is a coloured figure with a cream dot; every hut a colour dot; the header title
      and the three panel titles are readable shapes; the water is blue, the sand a line.
- [ ] **3 Mbps encode (or a 60 % JPEG at 1280):** outlines still separate arms from torso; no tile edges show;
      flower drifts still read as streaks; night frame still shows every settler (0.55 floor).
- [ ] Sun consistency: sprites, trees, huts and ground shadows all lit from the same side in dawn, dusk and night.
- [ ] No text on the world except pills; every text >= 20 px.
- [ ] `genome()` of 50 random names: no two identical, no name yields a green (70-160) tunic.

## 15. Frame budget (measured 2026-09-25, M3 Pro, Python 3.9, numpy 2.0, Pillow 11)

| item | cost |
|---|---|
| one settler frame | 31.9 ms at 1x, 33.9 ms at 2x (constant working resolution) |
| one settler sheet (23 frames, one tier / zoom / sun octant) | ~0.75 s at hatch, cached forever; ~14 KB per 1x frame (34 px tier) |
| ground paint, 40x27 tiles (320x216 cells at 4 px) | 49 ms; repaint of an 80x40-cell region 19 ms |
| background bake (ground + ~110 props + 9 huts + grade + glows), 1280x440 | 49 ms, off the frame clock, 16 phase pairs |
| world compose: 20 settlers + 3 cloud shadows + 3 pills + smoke on 1280x440 | 2.18 ms mean, 2.41 ms p95, 2.68 ms max |
| tile stack (32 tiles) | 27 ms per (wind, ripple) pair, 16 pairs per season |

Rules: sheets are rendered at hatch (or at a sun-octant change) in a worker step, never inside the frame path; the
background is baked per (wind, ripple) and re-baked on a map change via `Ground.repaint`; the frame path only blits
cached arrays. Budget for the world panel: 24 ms; the art module needs ~2.5 ms of it.
