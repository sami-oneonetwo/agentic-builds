# settlers-tall · SETTLEMENT art direction (people-shaped settlers, tall-lean)

Studio C's world (bold clean outlines, flat chunky tiles, text off the world) with the creatures replaced by small
PEOPLE: travellers and villagers, not toys. Studio A's dusk light and Studio B's ground richness are grafted in.

1. **Silhouette language: "travellers".** A settler is a tall-lean figure seen from the front in 3/4 top-down: a big
   round head on a short neck, a straight tunic with a belt, two long narrow arms that gesture, two narrow legs, small
   dark boots. About 3 heads tall at the settler tier (2.5 as a child, 3.2 as an elder). Hoods, scarves, caps and wide
   hats, a satchel on the hip, a walking staff, a hand lantern or a tool over the shoulder give each one a job and a
   journey. No animals, no NPCs: every named settler is a real chatter.
2. **Proportions (body units, 1.0 = standing height S).** Settler tier: head radius 0.18, shoulders at 0.65 (half
   width 0.15), hem at 0.36, legs 0.36 → 0.03, arm length ~0.30 so a raised hand reaches head height. Standing heights
   at 1x: child 26 px, youth 31, settler 36, elder 40 (+ the hat). Frames are 1.30 S × 1.62 S with the ground point at
   0.14 S above the bottom edge, so hop, wave and hats never clip. Zoom 2 doubles everything including the outline.
3. **Everything from the name, nothing hand-picked.** The 31-multiplier name hash picks the tunic hue on Studio C's
   270° wheel that skips lime-to-teal, so the tunic (the dominant colour) is the same colour as the settler's roof,
   banner, chat name and pill dot. sha1(name) picks hair (crop / bob / tuft / bun / ponytail / curls), hat (none /
   hood / cap / wide hat), scarf, accessory (satchel / staff / lantern / shoulder tool), one of five stylised skin
   tones, one of six hair colours, the side things hang on, eye shape and trouser tone (a dark of the tunic hue, slate
   or umber). Accent colour (+150° ± 40°) is the hood/scarf/cape/hat/satchel-flap colour.
4. **Friendly, gender-neutral, never a caricature.** Everyone has the same face: two cream eyes with 2-3 px ink pupils
   and a 1 px glint, a tiny smile, soft blush. Skin and hair vary only in colour; no beards, dresses, or feature
   changes by type. Tiers change stature and kit, not people.
5. **Faces that read at 36 px.** Eye whites make the pupils pop on every skin tone and make gaze visible: `look_l` /
   `look_r` shift the pupils toward the speaker, `blink` is a line, sleep a shallow "u", joy an "n" arc. Speaking is a
   mouth notch ("o"/"O") plus a head bob; the 1 px outline around the eye whites is a half-weight line so the eyes
   stay soft.
6. **Sticker outlines.** Every part carries its own 1 px dark outline of the tunic hue mixed toward ink (drawn at 4x,
   downsampled premultiplied, 3x at zoom 2), so hair over head over torso over legs stays legible after a 3 Mbps
   encode and at the 320x180 thumb a settler is still a coloured dot with a dark rim.
7. **Lit by the same sun as the land.** `frame(..., sun=(sx, sy))` takes the screen-space direction toward the sun.
   Each filled part gets a warm rim on the sun side and a cool violet shade on the far side (mask minus itself shifted
   along the sun vector), and the ground shadow is thrown away from the sun. Evening sun is west-north-west, dawn sun is
   east. Trees, bushes, boulders and huts throw their shadows the same way. Sheets are cached per sun octant.
8. **Animation: 22 frames, squash-and-stretch in the geometry.**
   - idle0 / idle1: breath (1.025 wide, 0.975 tall) and a head tilt; play ~0.8 s each. blink 1 in 6 idles.
   - walk0-3: a real 4-frame cycle: contact (planted leg forward, other leg lifted with the boot tilted 22°), passing
     (legs together, body bobs up 0.025), contact mirrored, passing. Arms swing opposite. 4° lean toward travel;
     facing is a horizontal flip. ~8 frames per step at 30 fps.
   - hop0 / hop1: anticipation squash (0.86 tall, knees bent, arms back) then airborne stretch (1.08 tall, 0.27 lift,
     legs tucked, arms up, shadow shrinks to 0.62). Compositor plays hop0 ×3 ticks, hop1 on a parabola ×6, hop0 ×2.
   - wave0 / wave1: one long arm above the head with an open hand, alternate every 0.25 s; point: arm straight out
     toward facing, other hand on the hip, eyes toward the target.
   - sit: upper body drops by the leg length, legs out toward the camera with soles showing, hands on the knees.
   - sleep: curled on one side under an accent-colour blanket, hat off, hand under the cheek, zz shapes.
   - carry_berry / carry_stone / carry_tool: two-handed hold at belly height (basket of berries, boulder, hoe).
   - speak0 / speak1: mouth notch + head bob + a gesture hand; alternate ~0.15 s while the chat line is shown.
   - joy: both arms up, squint, grin, sparkles.
9. **Growth is visible from across the map.** Child (26 px, big head, bare-headed, tuft or crop hair, no kit) →
   youth (31, hair, maybe a scarf) → settler (36, accessory: satchel / staff / lantern / tool) → elder (40, always a
   hood or a wide hat, an accent cape, +1 head of stature). Same face, more presence.
10. **Ground (from Studio B).** Trees have depth: a dark under-canopy, mid lobes, lit lobes shifted toward the sun and
    leaf scallops on the crown. Flower clumps gather in drifts along a low-frequency noise ridge instead of sprinkling;
    bushes stand at the forest edge, boulders on the hills; worn paths have two faint ruts and grass scuffs at the
    edges. Nothing crosses a tile edge; wind (4 phases) sways canopies, flowers and grass together.
11. **Light (from Studio A).** Dusk grades the land warm-orange (×1.06, 0.84, 0.64) while water keeps its own blue
    grade; a warm wash on the sun side of the frame and a cool violet in the far corner give the low sun a direction.
    Lantern and window glows are additive. Dawn is cool with low mist over low ground.
12. **Text stays off the world.** Studio C's HUD (64 px header, 192 px band of three translucent panels, 20 px caption,
    everything >= 20 px). The one change: show-on-speak name pills carry a 26 px portrait of the settler's head
    (`creatures.portrait`) on a dot of their colour, so the pill says who is talking even before you read the name.
    Pills push upward when they would overlap another pill or cover another settler.
13. **What makes them ours.** The tall-lean 3-head traveller silhouette with long gesturing arms; the hue wheel that
    skips grass; identical friendly faces with cream eyes and colour-only diversity; kit as identity (staff, lantern,
    satchel, shoulder tool, hood, scarf, wide hat); sun-vector rim light shared by people, trees and huts; the rule
    that every named settler is a real chatter and nature (not NPCs) supplies the rest of the life. Nothing here is a
    blob, a franchise sprite or a real-world costume.
14. **Budget (measured, M-series Mac, Python 3.9, numpy 2.0, Pillow 11).** A settler's 22-frame sheet at one tier
    renders in ~0.5 s at 1x (23 ms/frame) and ~1.4 s at 2x, cached forever per (name, tier, zoom, sun octant). World
    compose at 20 settlers + 3 cloud shadows + 3 pills + smoke: 2.2 ms mean, 2.3 ms p95 on 1280x440. A background bake
    (terrain gather, props, trees, huts, tint, glows) is ~150-190 ms and happens off the frame clock.
