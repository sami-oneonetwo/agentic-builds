# settlers-round · SETTLEMENT art direction (people-shaped, round-head, toy-warm)

Studio C's world (bold clean 1-px outlines, flat chunky tiles, text off the world) with PEOPLE instead of lanterns,
Studio A's dusk light and Studio B's ground richness grafted on. Every named settler is a real chatter; nature, not NPCs,
supplies the rest of the life.

1. **Silhouette language: "toy people".** A settler is a big ROUND head (45 % of the height), a short flared tunic
   torso, two stubby legs with round shoes, two noodle arms with mitten hands, seen from the front in the 3/4 top-down
   view. Head wider than the shoulders, feet visible, hands visible: at 320x180 it is a coloured figure with a cream
   dot on top, not a blob. No tails, no crests, no animal parts.
2. **Proportions (body heights, y up from the ground point).** Head radius R = 0.5 / heads; head centre 1 - R;
   torso from 0.19 (hem) to just under the chin; shoulders ±0.155, hem ±0.205; legs at ±0.085, width 0.10;
   arms 0.085 wide from the shoulder pivot to hands at ±0.24; hands r 0.052; pupils r 0.033 (~2 px at 34 px, 4 px at 2x).
   Tiers: **sprout** 26 px / 2.0 heads · **settler** 30 px / 2.25 · **builder** 34 px / 2.25 + accessory ·
   **elder** 42 px / 2.9 heads (+1 head of height, hat and cape). Growth is taller and more dressed, never bigger-headed.
3. **Everything from the name, nothing hand-picked.** The 31-multiplier name hash picks the TUNIC hue on a 270°
   wheel that skips grass (70-160°), so labels, roofs, fields and the person match and always pop off the meadow.
   sha1(name) picks: hair style (bob / tuft / cap / hood / flower), hair yarn (cocoa / rust / straw / cream / plum /
   accent), accessory (scarf / belt / satchel / badge / apron; builders and up), cheeks (blush / freckles / plain),
   eye set (dots / tall / wide), the side things lean to, the elder hat (brim / stocking cap), and the accent offset.
4. **Palette rules per settler:** tunic = main; hats, scarf, belt, badge, cape, blanket = accent (+150° ± 40°,
   also grass-skipping); face and hands = ONE warm cream for everyone, tinted 10 % toward the tunic (a toy colour,
   not a skin tone: stylised, friendly, gender-neutral, never an ethnicity); hair = yarn; legs a desaturated dark of the
   hue; shoes near-ink; outline = hue darkened toward ink (never pure black). Five colours plus cream and ink, max.
5. **Sticker outlines on every part.** Each part carries its own 1-2 px outline (1.0 px at 26, 1.3 px at 34, 2.6 px at
   2x), drawn at 4x supersample (2x at zoom 2, so cost is constant) and downsampled premultiplied. Overlaps read as
   lines, so arms, legs and hands stay separate after a 3 Mbps encode.
6. **Faces that read at 30 px.** Two ink pupils under a faint eyelid hairline (the lid is what makes a dot look like an
   eye), blush or freckles, a small smile. Blink = flat lines, sleep = "u" arcs, joy = "n" arcs, surprise = bigger
   pupils with a highlight. `look` turns the head 0.045 and shifts the pupils 0.03 toward +x; flip for -x, so idle
   settlers face whoever is speaking.
7. **Designed for how it moves (19 frames):** idle0/idle1 breath (1.03 x 0.97, head dips), look, blink,
   **walk0-3** a real cycle (contact L: left leg lifted 0.075 and left arm forward, ±3° lean; pass: both down, body up
   0.02; contact R; pass), **hop** (0.90 x 1.12, lift 0.30, arms up, legs tucked, shadow to 65 %), **wave** (one arm over
   the head, head tilts), **sit** (body drops 0.13, legs forward, hands on knees), **sleep** (curled on the ground under
   an accent blanket, zz), **carry_berry / carry_stone / carry_tool** (arms forward around the item), **speak0/1** (mouth
   notch, head bob 0.02), **joy** (arc eyes, arms up, sparkles), **love** (heart). Squash-and-stretch happens in
   geometry, not by scaling the bitmap. Elder capes flare on hop.
8. **Timings are the compositor's job;** the sheet supplies poses: idle0↔idle1 every ~0.8 s, blink 1 in 6 idles for
   4 ticks, walk 4 frames at 8 fps (each frame 4 ticks) with facing = direction of travel, hop = 4 ticks on a
   parabolic offset, speak0↔speak1 every 6 ticks while the pill shows, look while someone within ~200 px speaks,
   sleep alternates with a 1 % breath scale, carry frames when walking to/from a farm, quarry or build site.
9. **Light is directional and warm (Studio A).** Sun vector (-0.62, -0.78): every sprite gets a warm rim on the
   sun edge and a cool violet shade band on the far edge, baked in the sheet; ground shadows slide away from the sun;
   evening adds a warm multiply, a top-left sun wash, a bottom-right violet shade, lantern and window glows.
   Dawn: cool wash, low mist over low ground, a soft sun top-right.
10. **The ground is rich, not busy (Studio B).** Trees have canopy DEPTH (dark under-canopy toward the shade,
    relit sun side, light crown, trunk shadow, offset ground shadow). Meadow tiles carry flower DRIFTS: 3-5 blooms of
    one colour strung along a curve, so flowers read as coloured streaks at 320x180. Worn paths: a paler trodden
    centre, dark crumbs and grass creeping in from the edges; cobbles have a polished centre stone. Bushes sit on
    meadow edges. Grass has soft lighter patches. Nothing crosses a tile edge; wind and ripple phases are baked.
11. **Buildings say whose they are.** Roof = builder's main, trim = accent, cream plaster with a shade side away
    from the sun and a lit eave line; ground shadow offset like everything else.
12. **Text stays off the world.** 64 px header, 192 px bottom band, 20 px caption. On the world only show-on-speak
    pills: the settler's HEAD ICON (rendered from the sheet), their name in their colour (20 px bold), a tail to them,
    placed above the figure and stacked when two would overlap. Everything text is >= 20 px.
13. **Fonts:** Arial Rounded Bold for display, Verdana / Verdana Bold for body and pills.
14. **What makes them ours:** the round-head toy-people proportions (2.25 heads, head wider than shoulders), one
    shared cream face for everyone, yarn hair + accent hats as the identity layer over a name-coloured tunic, sticker
    outlines on limbs, a growth ladder that adds height and clothes rather than size, the blanket sleep, and a
    village that is a crowd of chatters' colours. Nothing here is a franchise creature or a franchise villager.
15. **Budget (measured, this Mac, Python 3.9, numpy + pillow):** a frame renders in ~26 ms at 1x AND 2x
    (constant working resolution), so a settler's 19-frame sheet at one tier/zoom is ~0.5 s at hatch, cached forever
    (`settler_sheet(username, tier, zoom) -> {frame: PIL RGBA}`); world compose with 20 settlers, 3 cloud shadows,
    3 pills and smoke on 1280x440 is 2.4 ms mean / 2.6 ms p95; one background bake is ~130 ms, off the frame clock.
