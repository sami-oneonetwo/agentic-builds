# PIP HOLLOW art rules (WORLD.md §6.2 art note, §10, §13)

These are testable rules, not taste. A ship that breaks one is reverted. The sprite sheet
(`$PYTHON stream/world/pips.py --sheet <png>`; `--self-test` writes `selftest/pips_sheet.png`) is reviewed against
this page before the world goes live and after any change to `stream/world/pips.py`.

## 1. Honesty (the art rule above every other)

> Every creature on screen is a real person who chatted. Darkness means nobody. Light means someone.

- A pip exists only because a moderated chat record with a real Kick username created it. There is no other
  constructor. Synthetic pips exist only under `KL_TEST_PIPS=N`, only in a `/tmp` run dir, only in a test mode
  (`--self-test` or `MODE=test`); `stream.world.test_pips_allowed()` is the single gate and the scene checks every
  frame that every entity is real (or test, when allowed) and counts violations in `stats()["honesty_violations"]`.
  Test pips are never written to `world.json` and never counted in `hatched_ever`.
- Every number on screen is a `len()` over real records: `awake`, `asleep`, `hatched`, platform tallies, milestones.
  No padded counts, no sample strings from any document, ever.
- No name is drawn before the 3 s hold has passed AND the username has cleared the blocklist. The seed is nameless
  (grey shell, no name colour, `entities()` returns `display_name: None` and `key: None` for it). A user hidden
  inside the hold never hatches: the seed sinks.
- Sleeping pips are real past chatters with a real `last_seen`; they never walk, vote, speak or eat.
- Pips never generate text: every bubble is the owner's own message, one of the owner's own tokens, or a learned
  word carrying the real source's name.
- Keepers (the AI agents) are a lantern on a chain, never a figure. The only animate things are pips.

## 2. Absence is never punished

- Energy is cosmetic (glow 40 % to 100 %). Below 0.2 the pip curls up and dims. That is the floor.
- No hunger, no sadness face, no death, no decay while asleep, no decay while the stream is off, no copy that
  blames a viewer (`nobody voted` is a fact; `you let it die` never appears).
- A future keeper who adds hunger, death, guilt copy, or multiplication "to improve engagement" is reverted.

## 3. No IP adjacency (Plaything / Thronglets, any pet franchise)

Invented names only: pip, the Hollow, keeper, glowmoss, seed, burrow, platform, chamber. Concretely, every sprite:

| Rule | Test |
|---|---|
| Colour comes from the name and the preset; **no yellow default** | `colour_idx = hash(name_lower) % 6` into `L.PRESETS[preset]["names"]`; the egg uses only `#1C2130` / `#8A90A0` |
| **Angular** side-view bodies: wedge, slab, rhombus, ramp | `pips.body_mask()` builds row spans only; no disc or ellipse anywhere in `pips.py` |
| No round faces, no big eyes, no fur, no mouth except a 1 px speak notch | the eye is 2 px (1 dark + 1 `#E6E8EE` highlight); the only face pixel |
| Low to the ground, never upright | body box 10x8 to 14x12 sim px, always wider than tall |
| Body fill 35-70 % of the stencil box, outline contrast against the void, eye inside the body | `pips.check_genome()`; `resolve_genome()` reseeds deterministically until it passes and the salt is stored |
| **No multiplication, no breeding, no child creatures** | every entity maps to one row in `world.json["pips"]`; nests (v2) record real godparents only |
| No morality mechanic | no field in `world.json` grades a pip or an owner |
| No plant-headed helpers, no mascots, no animate non-persons | the keeper is the lantern at sim (300, 0-10) |

## 4. Motion and legibility (CONCEPT §5 kept)

- Something moves every frame: drips, the 1 px idle bob at 0.5 Hz, the moss pulse at 0.25 Hz, star twinkle on
  3-6 s cycles, sleepers' twitch every 8-15 s.
- Nothing flashes faster than 1 Hz (egg cracks 1 per second, blink 150 ms once per 4-7 s, lantern flicker 0.25 Hz).
- Walks ease over ~9 frames; speeds 20-40 screen px/s.
- Every text item is drawn at screen scale by the text layer, never inside the 320x110 sim; nothing under 20 px.
- The 320x180 tile must still show a light source at 0 awake (sky and moon in the mouth, moss); the empty cave is
  dark but never black.

## 5. Review checklist (before go-live, and after any pips.py change)

1. `$PYTHON stream/world/pips.py --check --names 48` prints the reseed table; every row must pass within 64 salts.
2. Open the sheet: no row reads as a face, a ball, a yellow blob, an upright figure, or anything from a franchise.
3. Render the 0-pip frame: sky visible, no creature, no name.
4. Render with real chat only (no `KL_TEST_PIPS`): `stats()["entities"] == hatched pips from chat.jsonl`.
