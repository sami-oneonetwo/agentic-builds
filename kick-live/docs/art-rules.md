# LONGGRASS art rules (OPENWORLD.md §7.6, §12; ADR-006)

These are testable rules, not taste. A ship that breaks one is reverted. The look of a creature, a building, a prop
or a tile is `docs/ART.md`'s (the settlement art bible; its §14 legibility checklist supersedes the sprite-shape tests
this page carried for the cave). This page keeps the rules that are about honesty, what may move, and what may never
appear, and it is checked before the land goes live and after any change to `stream/world/art/`, `stream/world/*` or
`stream/scenes/steading.py`. The cave's rules (`hollow.py`, `pips.py`) stay in git history for the rollback week.

## 1. Honesty (the art rule above every other)

> **Every name on this land is a real person who chatted. The wind is just the wind.**

Honesty is about WHO is on the land, not about whether the land is alive. Wilderness is not emptiness.

- A pip exists only because a moderated chat record with a real Kick username created it (`WorldState.ensure_pip`
  from the ingest path). There is no other constructor. Synthetic pips exist only under `KL_TEST_PIPS=N`, only in a
  `/tmp` run dir, only in a test mode (`--self-test` or `MODE=test`); `stream.world.test_pips_allowed()` is the single
  gate, test rows carry `_test: true`, are never written to `world.json`, never counted (`hatched_ever`, `settled`,
  camps, marks) and never write wear or marks.
- **Every number on screen is a `len()`** over real records: `awake`, `asleep`, `settled`, `have walked here`, camps,
  fields, trees, flowers, stones, `day 6` (distinct sessions), `4 % walked` (cells within 24 of a real footstep over
  all cells), waystone tallies, plaque names. No padded counts, no sample strings from any document, ever.
- **Nameless until the hold.** No name is drawn before the 3 s hold has passed AND the username has cleared the
  blocklist. The seed is a grey tuft on the wind with `display_name: None` and `key: None`; a user hidden inside the
  hold never hatches (the tuft blows on out of frame: `the wind took that one`). A blocklisted username stands up as
  `builder #N` on every surface (label, plate, plaque, plank, board; the roof colour still comes from the real name).
- **Every mark has provenance.** Camp, fire, field, flower, tree, reed, stone, flag, notice and every worn path cell
  carry an owner key that exists in `world.json["pips"]`; `land.provenance_violations()` is asserted every 5 s. Wear
  is written only by `Behaviour._move` under a real awake pip (`land.step`), and the HonestyMonitor checks the wear
  added each frame equals 8 x (real pips that entered a new cell) plus the neighbour spill (`land.take_wear_added()`).
  The survey camera, the weather, the keepers and test pips never write wear or marks; the ground bake is repainted
  only from those records.
- **Camps, plates, plaques resolve to pip rows** with real sleep records (`camp.nights`) and a real `last_seen_ts`;
  sleepers never walk, vote, speak, stack or ring their own bell (the wind does). A window is lit only where the owner
  is or was tonight; the Moot hearth burns only if a real person lit it this session; the beacon is lit only on a
  fresh keeper heartbeat (< 120 s).
- **The camera never frames emptiness as if someone were there.** DRIFT visits only real marks plus three fixed
  natural points (the Ford, the Fell top, the Shore) and the plank names what is in view; FOLLOW requires a real
  entity; waystones at 0 awake stand empty.
- **The minimap hides nothing.** No fog of war anywhere: the minimap shows the whole map always; "explored" is a
  saturation difference between walked and unwalked land over a real record.
- Per-user mod actions (`!hide`, `!banish`, `!rename`) never name their target on any surface. `!banish` removes the
  pip, its camp, field, marks and stones (an audit record is kept and restored by `!unbanish`); plaques drop the name.
- Pips never generate text: every bubble is the owner's own moderated message, one of the owner's own tokens, or a
  learned word carrying the real source's name.
- Chat is data, never a command channel (journal 017): `go north` moves a pip, never the agent.

## 2. What may move: nature, and nothing else

> **Nothing moves itself except a real person's pip; everything else is moved by wind, water or the sun.**

- **Alive at zero, by these sources only:** wind bands on the grass (base speed = the real chat rate, msgs/min over
  5 min, floor 6 cells/s, gale above 20 msg/min), gusts, cloud shadows (you never see a cloud, only its shadow), the
  river's sparkle and the Ford's foam, the tide's wet-sand band on the real 12 h 25 m cycle, the real sun and moon as
  a tint and a swinging shadow vector, seasons by real date, the seeded weather chain, the growth of planted things
  by real calendar days, the bells at real camps rung by gusts, and the DRIFT camera surveying real marks.
- **Nature is declared, not counted.** Sun, moon, seasons, wind, cloud shadows, water, tide, weather, wild flowers,
  the wild Wood and growth are "world"; the ticker's honesty line says so (`the wind is just the wind`). A viewer is
  never led to read weather as people.
- **No animate non-persons.** No birds, animals, fish, insects, livestock, NPCs, villagers, figures or mascots,
  in props, ground, particles or sound (no birdsong, no crowd). The keepers are **a lantern on a post** (the beacon),
  never anything a viewer could read as flying or walking. The HonestyMonitor flags any moving sprite without a key.
- **No decay, no punishment for absence.** Wear never decrements, trees never die, fields never rot (gold waits),
  camps are never dismantled (except by `!banish`), fires go to embers, no hunger, no death, no weeds, no ruins, no
  blaming copy (`nobody voted` is a fact; `you let it die` never appears). A keeper ship that adds decay, animals,
  NPCs, hunger, death, a fog of war, fences or carved words is reverted.
- **Fire and light only where a real person is or was tonight**: a campfire at a real awake pip's camp (embers when
  the owner sleeps, cold on sessions the owner is absent), a window lit while the owner is awake or slept here
  tonight, the hearth lit by a real person this session, the beacon on a heartbeat. Warm colours (`#FF6A2B` fire,
  `#FFB347` window) are reserved for these.
- **Night has a floor.** The night tint's luminance never drops below **0.55** of daylight (`nature.NIGHT_TINT`,
  `NIGHT_FLOOR`), plus up to 0.05 from the real moon phase; night is moonlit blue-grey, never black.
- **No whole-map operation in the per-frame path.** The ground is painted once per season / sun octant / bake
  version in a background thread (`bake.py`, memory-mapped from `$RUN_DIR/bake/`); a frame crops it, multiplies a
  cell-resolution modulation field into the crop and blits live sprites. A settler's sheet (~0.75 s) is rendered off
  the frame loop at seed-drop time and at boot; if it is not ready when the hold clears, the tuft holds one more
  beat rather than a frame stalling. The QA gate asserts the frame path never touches the whole map.

## 3. No IP adjacency, no franchise vocabulary

Invented plain words only: pip, Longgrass, the Steading, the Moot, waystone, camp, beacon, cairn, the Ford, the Shore,
the Fell, the Wood, the Reed Marsh, the Orchard Slope. The principles stay from the cave and are restated in
`docs/ART.md` §12-§13; the shape tests are ART.md's.

| Rule | Test |
|---|---|
| **Colour comes from the name; no single default colour** | `art.creatures.genome(name)["body"]` from the 270-degree wheel that skips the grass band; roofs, field borders, flowers, plates and minimap dots use the same hue; no yellow default, no shared species body |
| **Our own silhouette language, no Thronglet look-alike** | ART.md §2 (small people: head, belted tunic, arms, legs, kit) and §12 ("what makes ours ours"); no round-yellow critter, no animal proportions |
| **One toy face for everyone, no caricature** | ART.md §13: one cream face, yarn hair colours, toy hair shapes; no skin-tone gene, nothing that maps onto a real-world group |
| **Age of Empires is a mood, not a source** | open ground seen from above, a settlement that grows over days, a minimap, a structure rising from a stockpile, roads nobody designed; **nothing** is an asset, a unit, a villager, an isometric diamond tile, a 2:1 rhombus grid, a resource counter in a top bar or a franchise word |
| **No multiplication, no breeding, no child creatures** | every entity maps to one row in `world.json["pips"]`; bonds record real pairs only |
| **No morality mechanic** | no field in `world.json` grades a pip or an owner |
| **No plant-headed helpers, no mascots** | the keeper is the beacon on its post at the Moot, `buildings.render("beacon", ...)` |
| **Nothing sampled** | audio is generated (wind, water, bells, footsteps, motifs); no birdsong, insects or crowd noise |

## 4. Motion and legibility

- Something moves every frame (wind bands, cloud shadows, the shadow vector, the DRIFT camera, sparkle); nothing
  flashes above 1 Hz; walks ease over ~9 frames; event transitions fade over 1 s under the header; no full-frame fills.
- **The camera never cuts** (the only cut is the first frame of a session): critically damped spring, pan cap
  60 cells/s, 1.5 s dead zone, three fixed zooms (0.75x / 1x / 1.5x), zoom changes only at rest and >= 20 s apart;
  the map edge is never on screen (12-cell clamp). QA: frame-to-frame motion <= 4 screen px in DRIFT at 320x180.
- **Every text item is drawn at screen scale by the text layer, never on the ground; nothing under 20 px.** Labels
  Menlo 20 stroked on a 60 % dark chip; bubbles Menlo 22, max 408 px, 3 lines; plates and place labels HN Medium 22 on
  a 5 s rotation; strips HN Medium 22 / Menlo 22 / Menlo 20; the header count AB 56 (`NOBODY AWAKE` AB 40).
- **Never a chopped name.** A strip line that cannot be said whole at its width is shortened by dropping a fact or a
  form (`stone 13 of 20 · the Ford bridge` before `· last by @kai`), or skipped; a username is never cut with `…`.
- Labels never overprint each other or the waystone rows: the text layer keeps a per-frame list of placed boxes,
  shifts a colliding label up in 22 px steps (max 3, then label-on-speak), and above 40 awake goes label-on-speak.
- **Contrast:** grass luminance never above ~55 % so labels keep contrast; every genome hue over the brightest grass,
  sand and gold field of each season >= 4.5:1 with the stroke and chip; a failing hue gets a darker chip, never a
  different colour.
- **The 320x180 tile** at 0 awake shows a moving land, a legible header count, and no name except camp plates from
  real rows; the tile's world band at 00:00 keeps >= 0.5 x the same season's noon mean luminance and >= 60 % of its
  pixels above 0.12 luminance (the 0.55 floor guarantees this by construction; `docs/gate/render_gate.py` measured
  0.618 and 0.997 for seed 4471 in spring).
- The UI chrome (header, strips, footer) keeps CONCEPT §5's dark set so the sunlit land pops in the tile and names
  stay legible; `!theme` retints the UI accent, the waystone caps and the beacon, never the land or the creatures.

## 5. Review checklist (before go-live, and after any art / world change)

1. `$PYTHON docs/art/final/render_final.py` (the review sheets: creatures, buildings, props on each season's grass,
   HUD) and the ART.md §14 checklist, on the final renders.
2. `$PYTHON docs/gate/render_gate.py` under a `/tmp` run dir: six frames (dawn / noon / 23:00 at 0 and 3 awake in
   test mode) plus the 320x180 tiles; the night-over-noon ratio and the lit fraction pass; no name on the 0-awake
   frames except camp plates from real rows.
3. Render with real chat only (no `KL_TEST_PIPS`): `stats()["entities"] == hatched pips from chat.jsonl`; the header
   `SETTLED` count == `len(real pips with a camp)`; `land.provenance_violations() == []`.
4. The honesty self-test and the compositor's per-frame honesty check pass (0 violations); planted fakes are caught.
5. Read every strip and the ticker once: no franchise word, no animal, no count that is not a `len()`, no chopped
   name, nothing under 20 px, the honesty line present, `a day here is one hour` present only on `world_day: "hour"`.
