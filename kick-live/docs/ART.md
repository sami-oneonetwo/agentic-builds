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

## 2. Silhouette language: small people on a pixel grid

A settler is a **person**, not a shape: a wide rounded-square head about half the figure, a short belted tunic with
1-px sleeves and cream mitten hands, two short legs with dark shoes. Seen from the front in the 3/4 top-down view and
drawn as **chunky pixel art on a hard integer grid** (owner brief 2026-09-27 12:05, "rebuild the character models to be
a bit cooler", with the four-figure pixel reference): one art pixel = 2 screen px at 1x (`creatures.ART_PX`), 4 at 2x,
nearest-neighbour, no anti-aliasing, no supersample, no rotation. Head wider than the shoulders (the lovability lives
in the head); feet and hands visible in every standing frame; at 320x180 a settler is a coloured figure with a cream
dot on top, not a blob.

| | sprout (tier 0) | settler (1) | builder (2) | elder (3) |
|---|---|---|---|---|
| standing height S at 1x (fill rows x 2 px) | 26 px = 13 rows | 30 px = 15 rows | 34 px = 17 rows | 42 px = 21 rows |
| legs (rows; the bottom row is the shoe) | 2 | 2 | 3 | 4 |
| torso (rows x columns) | 3 x 6 | 4 x 8 | 5 x 8 | 8 x 10 |
| head (rows x columns, corners cut) | 7 x 8 | 8 x 10 | 8 x 10 | 8 x 10 |
| legs (width, columns) | 1 at -2 and 1 | 2 at -3..-2 and 1..2 | 2 at -3..-2 and 1..2 | 3 at -4..-2 and 1..3 |
| visual height with both outline rows | 15 rows = 30 px | 17 = 34 px | 19 = 38 px | 23 = 46 px (+2 hat rows) |
| worn | hair only | hair, belt row | + hat (beanie / hood) + kit | + elder hat, accent cape, collar step |
| frame box (W x H) | 1.6 S x 1.72 S, ground line at (W/2, H - 0.14 S): unchanged | | | |

Rows count up from the ground line (`creatures.GEO`, `creatures.art_rows(tier)`): row 0 is the bottom outline row and
sits ON the ground line, so the feet, the ground shadow and the label anchor agree on air; fill rows 1..S/2; the top
outline row above. The head sits over one outline row (the neck) above the tunic; between every two parts there is
exactly one outline pixel. Figures are even widths centred on the ground point (x = -1 | 0 is the centre boundary), so
`facing = -1` is an exact mirror. Hats add up to 4 art rows above the head's top outline (beanie 1 + its outline, hood
point 2, elder brim crown 2 + outline; `creatures.HAT_ROWS`): a label sits above `anchor_y - S - 8 px`. Growth is taller
and more dressed, never bigger-headed: sprout -> settler adds a torso row, the belt row and two head columns; the builder
adds a leg row, a torso row, hat + kit; the elder adds a leg row, three torso rows, a 10-wide tunic, the collar step,
an elder hat and a cape (the head stays 8 x 10 from the settler up).

Zoom 2 shares the zoom-1 art grid (cached per name / tier / frame / sun octant); only the nearest-neighbour blow-up
differs, so a frame costs the same at both. The scene (`steading.py`) renders the atlas at zoom 2 and scales it by
`SETTLER_SCALE` (1.0) x camera zoom / 2: exactly 2 screen px per art px at 1x and 3 at 1.5x (NEAREST on a canvas padded
to the art pixel, every art pixel one uniform block) and 1.5 px at 0.75x (BOX, the wide view).

## 3. Genome: everything from the name, nothing hand-picked

`creatures.genome(username)` returns readable values; `render()` reads the same genes.

| gene | source | values |
|---|---|---|
| **tone** (tunic = the name colour) | `(name_hash(name) % 1000) % 24` | Natural earth, plant and mineral palette: ochre, rust, terracotta, sand, olive, moss, teal, slate, plum-brown, brick, cream, charcoal, mustard, pine, clay, indigo, walnut, fern, storm, wine, honey, ash, copper, heather. Hue is derived from the selected RGB, not a saturated wheel. |
| accent | `sha1[6] % 3` selects paired accent or tone rows +5 / +11 | Muted coordinated hats, scarf, belt, badge, cape and hut trim; no neon accent wheel |
| outline | Main tone mixed toward ink in two steps | Never pure black; high-contrast edge separates moss/pine garments from grass |
| hair | (sha1[0] + sha1[9]) % 6 | bob, tuft, crop, bun, flower, curlcap |
| hair colour (yarn) | sha1[1] % 6 | cocoa #4A342E, rust #AA623C, straw #ECC664, cream #F6EEDE, plum #60405C, or the accent |
| hat (worn from builder) | sha1[8] % 8 -> (0,0,0,1,1,2,0,1) | none 4/8, beanie 3/8, hood 1/8 |
| elder hat | sha1[7] % 2 | brim, stocking (replaces the hat at tier 3) |
| accessory / kit (from builder) | sha1[2] % 8 | scarf, belt, satchel, badge, apron, staff, lantern, tool |
| cheeks | sha1[3] % 3 | blush, freckles, plain |
| eyes | sha1[4] % 3 | dots, tall, wide (pupil spacing / shape only) |
| side | sha1[5] % 2 | which side things hang on, which hand waves |

Under a hat only bob drops and the flower stay; spikes and buns never poke through a crown. The legacy lying pose is used only for moderation hiding, never absence.

## 4. Palette

Per settler at most five colours plus cream and ink: main, accent, outline (+ derived darks), yarn, face.

| role | value |
|---|---|
| face and hands (everyone) | cream #FAECD4 tinted 6 % toward the tunic. **A toy colour, never a skin tone** |
| ink (pupils, mouth) | #261E1C · glint #FFFCF6 |
| blush #EE7E82 (alpha 125) · freckles #C48468 · heart #EC5468 · sparkle #FFE478 | |
| legs | Main tone mixed with earth brown, then darkened; shoes use the outline mixed with brown |
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

Eyes are two INK bars of 1 x 2 art px (2 x 4 screen px at 1x) on rows 2-3 of the head fill: `dots` two columns apart,
`wide` four apart, `tall` 1 x 3. No eye whites (they read as goggles), no glint, no eyelid: the bar on the cream block
is the eye. `blink` = one pixel each, `sleep` = 2-px flat bars, `joy` = a "^" of three pixels, `big` (hop1, love) = one
row taller. `look_l` / `look_r` shift the head one column and the bars one more toward the speaker so no flip (and no
mirrored satchel) is needed. **The mouth is drawn only when it means something**: `speak0` an open 2 x 2 "o" from the
chin row, `speak1` a 1-px notch, `hop1` the "o", `joy` a 4-px grin line, `love` and the lying pose a 2-px line. Idle,
walk, wave, point, carry and sit are mouthless like the reference, so chatter never looks like shouting. Blush = two
pixels each side under the eyes (one on `wide`), freckles = one pixel, by gene. Everyone has the same face; only colour
and kit vary.

## 6. Outlines and light on the grid

Every part is a boolean mask on the art grid. Painting it writes its 4-neighbour ring in the palette OUTLINE colour
(the tunic darkened toward ink, never pure black) over whatever is already there, then its flat fill: that ring is the
one-art-pixel line between head and tunic, tunic and legs, sleeve and body, item and hands, and a final ring around
every fill outlines the whole silhouette, so hair spikes, buns and hats that poke out are outlined too. The outline is
2 screen px at 1x, 3 at the 1.5x Moot dwell, and stays a line through a 60 % JPEG at 1280 (the 3 Mbps proxy).

Light is one sun for the whole world: `sun=(sx, sy)` is the screen-space unit vector toward the sun. A part takes ONE
darker shade step (its fill mixed toward the outline: tunic 22 %, face 22 %, legs 30 %, accent / cape 28-30 %, hair
40 % toward its own outline) on the column away from the sun (|sx| >= 0.5) or on its bottom row (noon, moonlight from
above); the deep tunics (builder, elder) take the same step as a collar row under the chin. No rim, no gradient, no
blur, nothing in between. Ground shadows are a two-row pixel ellipse under the feet (row 0 behind the bottom outline
and the row below the ground line) at 36 % ink, 24 % on hop1, one art pixel wider on sit and the lying pose, sliding
one art px away from the sun; tree lobes, hut walls and roofs shade the same way. `tiles.sun_vector(hour)` gives east
low at dawn, high at noon, west low at dusk, moon high at night. Settler frames are cached per sun OCTANT (8 buckets); a
compositor that moves the sun through the day rebuilds sheets at octant changes only (roughly every 1.75 h of world
time), so cache memory is 1 octant x settlers x tiers, not 8x.

## 7. Animation: 23 frames, squash-and-stretch in whole art rows

Poses are integer moves on the grid (`creatures._pose`): a head that drops one row, a body that lifts one row, a shoe
two rows up. Nothing scales or rotates the bitmap; there is no lean, no tilt, no sub-pixel.

| frame | pose (art rows / columns) | timing (compositor plays; the sheet supplies poses) |
|---|---|---|
| idle0 / idle1 | breath: the head drops one row onto the shoulders (the neck row closes) | alternate every ~0.8 s |
| blink | 1-px eyes | 1 in 6 idles, 4 ticks |
| look_l / look_r | head one column + eyes one more toward the side | while someone within ~200 px speaks |
| walk0 walk1 walk2 walk3 | **contact L**: the left shoe strides one column out, the right shoe is lifted `WALK_LIFT` = 2 rows (4 px at 1x) under the hem as a raised knee, the head waddles one column over the planted leg, the arm on the lifted side swings forward (out one column, hand up one row) and the other hand swings down below the hem · **pass**: body up one row, one leg reaches the ground · contact R · pass. Contact differs from idle by ~420 px at 1x (settler) | 8 fps (4 ticks per frame at 30 fps); facing = direction of travel (mirror) |
| hop0 / hop1 | anticipation: legs one row shorter, shoes out one column, head down one row, hands below the hem · airborne: lift 0.27 S = 4 / 4 / 5 / 6 rows (`HOP_LIFT`), shoes tucked one row up and out, arms up beside the head, big eyes, "o", shadow 62 % | hop0 x3 ticks, hop1 x6 on a parabola, hop0 x2 |
| wave0 / wave1 | the side arm up beside the head with the hand at the head's top row; wave1 one row higher and one column out, head tilts one column | alternate every 0.25 s |
| point | the right arm 3 px straight out toward +x with the hand, gaze right (head + eyes), other hand down | hold (mirror for -x) |
| sit | the tunic drops onto a sole row (the legs fold away as two soles beside the hem), hands on the hem, shadow 112 % | hold |
| sleep | **the ONE lying pose, a hidden (moderated) settler only** (`behaviour.frame_name`): seen from above lying on the back, so the face is upright at ground level with closed eyes, an accent blanket with a light folded edge tucked under the chin covers the body, shoes peek out at the far end, a hand rests on the blanket, hat off, two Zs | never on the land; nobody sleeps |
| carry_berry / carry_stone / carry_tool | hands joined one row above the hem, the item above them over the tunic (a basket + four berries, a boulder with a highlight, a mallet held diagonally) | while walking to / from a farm, quarry, build site |
| speak0 / speak1 | head up one row on a cream neck with the 2 x 2 "o", gesture hand raised beside the chin · notch mouth, hand out at the side | alternate every 6 ticks while the pill shows |
| joy | body up one row, both arms up beside the head, "^" eyes, grin line, two sparkles | 1 s on a tier-up, a vote win |
| love | hands clasped at the belly, big eyes, a small mouth line, a heart glyph beside the head | 1 s on feed / pet / gift |

Elder capes flare one column each side on hop1. `creatures.shadow()` returns the ground ellipse alone so a hop can move
the body up the parabola while the shadow stays on the ground.

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
  ours are small people with a belted tunic, a neck, hats, hair and hand-held kit, in the natural-tone table where the
  colour is the person's name colour. No default yellow, no shared species body.
- **Chunky pixel people, our own grid.** The owner's reference set the vocabulary (a hard grid, one dark outline around
  and between parts, one shade step, bar eyes, a wide head, big hats); ours keeps it but with the toy-cream face instead
  of the reference's skin tones, the natural-tone tunics, yarn hair, kit and the 23-frame life. Not a sprite from any game.
- **One toy face for everyone.** Not a skin tone, not a species face: cream, tinted toward the tunic. Identity is hair,
  hat, kit and colour, never features.
- **Kit as identity.** Staff, lantern, satchel, shoulder mallet, apron, scarf, badge, belt: a settler looks like they do a
  job in the settlement. Elders get stature, a hat and a cape, not size.
- **Real gestures.** Arms that reach up beside the head to wave, point 3 px out, join to carry a basket; a walk with a
  raised knee, a waddle and swinging hands; a hop with an anticipation frame. Squash-and-stretch happens in whole art
  rows, never by scaling or rotating the bitmap.
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
      differs from idle by a shoe lifted 2 art px (4 screen px), a swung arm and a one-column head waddle; eyes are
      1 x 2 ink bars (2 x 4 px); the pill portrait is a face cropped on the art grid and NEAREST-scaled.
- [ ] **Pixel gate:** `PYTHONPATH=. $PY stream/world/art/creatures.py --check` passes: 23552 renders with hard alpha
      (0 / 255) and uniform ART_PX x zoom blocks at both zooms, shadow box + slide per octant, fill rows = S / 2 with the
      bottom outline row on the anchor and nothing below it, the walk contact lift, 50 distinct genomes, ms per frame.
- [ ] **320x180 thumb:** every settler is a coloured figure with a cream dot; every hut a colour dot; the header title
      and the three panel titles are readable shapes; the water is blue, the sand a line.
- [ ] **3 Mbps encode (or a 60 % JPEG at 1280):** outlines still separate arms from torso and head from body; no tile
      edges show; flower drifts still read as streaks; night frame still shows every settler (0.55 floor).
- [ ] Sun consistency: sprites (the shade column), trees, huts and ground shadows all lit from the same side in dawn,
      dusk and night.
- [ ] Scene scale: `steading.SETTLER_SCALE` x zoom / 2 maps an art pixel to a whole number of screen px at the camera's
      resting zooms (2 px at 1x, 3 px at 1.5x) so the prescale is NEAREST; only the 0.75x wide view BOX-averages.
- [ ] No text on the world except pills; every text >= 20 px.
- [ ] `genome()` of 50 random names: no two identical; no tunic reads as the grass (the natural tones moss / fern / pine
      fall in the 70-160 hue band but sit well below the grass in value; the check names them).

## 15. Frame budget (settlers measured 2026-09-27 on the live Mac at nice 15, Python 3.9, numpy 2, Pillow 11; the
rest 2026-09-25)

| item | cost |
|---|---|
| one settler frame (pixel grid, cache miss, with shadow) | **0.37 ms at 1x, 0.55 ms at 2x** (`creatures.py --check`: 92 builder frames); the vector renderer it replaces measured 28.5 ms the same hour |
| one settler sheet (23 frames, one tier / zoom / sun octant) | ~9 ms at hatch (was ~0.75 s), cached forever; 48 x 52 x 4 = 10 KB per 1x settler frame, 39 KB at 2x (the box is unchanged, so `creatures._CACHE` bytes per sheet are unchanged; the shared art grid adds ~3 KB per frame) |
| the pixel sweep (23552 renders, 8 names x 4 tiers x 23 frames x 8 octants x 2 zooms x 2 facings) | 6.4 s |
| scene budget, `steading.py --self-test` C1 / C2 / C3 / C4 (20 pips 1x 18:00 / 60 pips 0.75x / 20 pips 23:00 / 6 pips noon, 300 frames each) | 8.36 / 11.62 / 9.70 / 7.43 ms avg (limits 14 / 19 / 14 / 12); contended by the worker rendering sheets 8.24 / 11.61 / 9.60 / 7.37 |
| scene prescale copies (`SpriteCache._zoomed`) | 0.5 x the atlas at 1x (was 0.6): (1.0 / 1.2)^2 = 31 % fewer bytes per zoomed frame |
| ground paint, 40x27 tiles (320x216 cells at 4 px) | 49 ms; repaint of an 80x40-cell region 19 ms |
| background bake (ground + ~110 props + 9 huts + grade + glows), 1280x440 | 49 ms, off the frame clock, 16 phase pairs |
| world compose: 20 settlers + 3 cloud shadows + 3 pills + smoke on 1280x440 | 2.18 ms mean, 2.41 ms p95, 2.68 ms max |
| tile stack (32 tiles) | 27 ms per (wind, ripple) pair, 16 pairs per season |

Rules: sheets are rendered at hatch (or at a sun-octant change) in a worker step, never inside the frame path (a sheet
is cheap now, but the rule stays so a hatch storm cannot touch the frame clock); the background is baked per (wind,
ripple) and re-baked on a map change via `Ground.repaint`; the frame path only blits cached arrays. Budget for the
world panel: 24 ms; the art module needs ~2.5 ms of it.
