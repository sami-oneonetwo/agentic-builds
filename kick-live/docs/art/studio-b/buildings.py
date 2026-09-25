"""buildings.py - studio-b building kit: cosy cottages composed from parts in the builder's colour.

Parts (each returns an RGBA sprite; see PARTS):
    wall(w, h, palette)          plaster / stone / timber / whitewash-with-beams front wall
    roof_gable(w, h, colour)     ridge-front gable seen from above, shingle rows, lit front slope
    roof_hip(w, h, colour)       four-sided hip roof with a sun-lit ridge
    roof_round(w, h, colour)     thatched dome for round huts
    chimney(colour)              stone stack with a soot-dark cap (smoke is a separate prop)
    door(palette)                arched plank door with a step
    window(lit)                  cross-framed window; lit = warm glass + glow halo (night)
    fence(n)                     n pickets
    well(colour)                 stone ring + little roof in the builder's colour
    banner(colour)               post + pennant in the builder's colour
    planter()                    flower box
    lantern(lit)                 lamp post; lit at night
    smoke(frame)                 3 puffs (0..2) drifting up

Composer:
    cottage(name, stage=1..3, night=False) -> RGBA sprite; footprint() -> (w_tiles, h_tiles)
    Roof colour = the builder's pip body colour (creatures.genome), so a pip and its home match.
    Stage 1 hut (~48x46), 2 cottage (~64x60), 3 house with annex (~88x64). Deterministic from name.

    python buildings.py    # writes building_kit.png (parts + 6 example cottages, day and night)
Python 3.9, numpy + pillow only.
"""
from __future__ import annotations

import math
import os
import sys
from typing import Dict, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SS, Canvas, Genes, RGB, hex_rgb, mix, rgba, shade  # noqa: E402
from creatures import genome  # noqa: E402

WALLS = {
    "plaster": dict(base=hex_rgb("#EADFC4"), line=hex_rgb("#B9A47C"), beams=None),
    "stone": dict(base=hex_rgb("#B9B4A4"), line=hex_rgb("#7E7A6C"), beams=None),
    "timber": dict(base=hex_rgb("#A97B4F"), line=hex_rgb("#6E4A2E"), beams=None),
    "whitewash": dict(base=hex_rgb("#F2EBDD"), line=hex_rgb("#7A5A3A"), beams=hex_rgb("#6E4A2E")),
}
WOOD = hex_rgb("#6E4A2E")
WOOD_L = hex_rgb("#9A6C42")
GLASS_NIGHT = hex_rgb("#FFD98A")
GLASS_DAY = hex_rgb("#7FA6C9")
STONE = hex_rgb("#9A9A8C")
STONE_D = hex_rgb("#6E6E64")
STRAW = hex_rgb("#D9B25A")


# ----------------------------------------------------------------------------- parts
def wall(w: float, h: float, palette: str, seed: str = "") -> np.ndarray:
    pal = WALLS[palette]
    c = Canvas(int(math.ceil(w)), int(math.ceil(h)))
    base = pal["base"]
    c.rect(0, 0, w, h, rgba(base))
    rng = Genes(seed or palette, "wall").rng()
    if palette == "stone":
        y = 0
        row = 0
        while y < h:
            x = -3 if row % 2 else 0
            while x < w:
                bw = rng.uniform(5, 9)
                x0, x1 = max(0.0, x + 0.4), min(w, x + bw) - 0.4
                y0, y1 = y + 0.4, min(h, y + 4.5) - 0.4
                if x1 - x0 > 1.5 and y1 - y0 > 1.5:
                    c.rounded_rect(x0, y0, x1, y1, 1.0, rgba(shade(base, rng.uniform(0.9, 1.1))), rgba(pal["line"]), 0.4)
                x += bw
            y += 4.5
            row += 1
    elif palette == "timber":
        for i in range(int(h // 3.5) + 1):
            y = i * 3.5
            c.line([(0, y), (w, y)], rgba(pal["line"], 160), 0.6)
            c.line([(0, y + 1.2), (w, y + 1.2)], rgba(shade(base, 1.12), 120), 0.5)
    else:
        for _ in range(int(w * h / 40)):
            c.ellipse(rng.uniform(0, w), rng.uniform(0, h), rng.uniform(1, 2.5), rng.uniform(1, 2),
                      rgba(shade(base, rng.uniform(0.93, 1.05)), 140))
        if pal["beams"]:
            b = rgba(pal["beams"])
            c.rect(0, 0, w, 1.6, b)
            c.rect(0, h - 1.6, w, h, b)
            for x in np.linspace(0, w, max(2, int(w // 14)) + 1):
                c.rect(x - 0.8, 0, x + 0.8, h, b)
            c.line([(0, h), (w * 0.5, 0)], b, 1.2)
    # ground shadow line at the foot, eave shadow at the top
    c.rect(0, 0, w, 2.0, rgba((0, 0, 0), 70))
    c.rect(0, h - 1.2, w, h, rgba(pal["line"]))
    return c.finish()


def _shingles(c: Canvas, x0, y0, x1, y1, colour, rows: int, light_k: float):
    """Rows of shingle scallops across a roof face."""
    col = rgba(shade(colour, light_k * 0.86), 200)
    h = (y1 - y0) / rows
    for i in range(rows):
        y = y0 + h * (i + 1)
        c.line([(x0, y), (x1, y)], col, 0.8)
        for x in np.arange(x0 + (h * 0.8 if i % 2 else 0), x1, h * 1.6):
            c.arc(x, y - h * 0.15, h * 0.75, h * 0.45, 180, 360, col, 0.7)


def roof_gable(w: float, h: float, colour: RGB) -> np.ndarray:
    """Seen from above: ridge across the middle; the front (south) slope faces the camera and is lit."""
    c = Canvas(int(math.ceil(w)), int(math.ceil(h)))
    ridge = h * 0.42
    back, front = shade(colour, 0.78), shade(colour, 1.08)
    c.polygon([(0, 0), (w, 0), (w, ridge), (0, ridge)], rgba(back))
    c.polygon([(0, ridge), (w, ridge), (w, h), (0, h)], rgba(front))
    _shingles(c, 0, 0, w, ridge, colour, 3, 0.85)
    _shingles(c, 0, ridge, w, h, colour, 4, 1.05)
    # ridge cap with sun highlight, eave lines
    c.rect(0, ridge - 1.4, w, ridge + 1.0, rgba(shade(colour, 1.35)))
    c.rect(0, ridge + 1.0, w, ridge + 1.8, rgba(shade(colour, 0.6), 160))
    c.rect(0, h - 1.5, w, h, rgba(shade(colour, 0.55)))
    c.rect(0, 0, w, 1.2, rgba(shade(colour, 0.6)))
    # glossy sheen (toy-like), matches the pips
    g = Canvas(c.w, c.h)
    g.ellipse(w * 0.3, ridge + (h - ridge) * 0.35, w * 0.28, (h - ridge) * 0.22, (255, 255, 255, 45))
    g.blur(1.6)
    c.paste(g)
    return c.finish()


def roof_hip(w: float, h: float, colour: RGB) -> np.ndarray:
    c = Canvas(int(math.ceil(w)), int(math.ceil(h)))
    cx, cy = w / 2, h * 0.42
    rx = w * 0.18
    L = [(0, 0), (cx - rx, cy), (cx + rx, cy), (w, 0)]
    c.polygon([(0, 0), (w, 0), (cx + rx, cy), (cx - rx, cy)], rgba(shade(colour, 0.78)))          # back
    c.polygon([(0, h), (w, h), (cx + rx, cy), (cx - rx, cy)], rgba(shade(colour, 1.08)))          # front
    c.polygon([(0, 0), (cx - rx, cy), (0, h)], rgba(shade(colour, 0.95)))                          # left
    c.polygon([(w, 0), (cx + rx, cy), (w, h)], rgba(shade(colour, 0.88)))                          # right
    _shingles(c, 0, cy, w, h, colour, 4, 1.05)
    for a, b in (((0, 0), (cx - rx, cy)), ((w, 0), (cx + rx, cy)), ((0, h), (cx - rx, cy)), ((w, h), (cx + rx, cy))):
        c.line([a, b], rgba(shade(colour, 1.3)), 1.1)
    c.rect(cx - rx, cy - 1.2, cx + rx, cy + 1.0, rgba(shade(colour, 1.35)))
    c.rect(0, h - 1.5, w, h, rgba(shade(colour, 0.55)))
    g = Canvas(c.w, c.h)
    g.ellipse(w * 0.35, cy + (h - cy) * 0.35, w * 0.25, (h - cy) * 0.22, (255, 255, 255, 45))
    g.blur(1.6)
    c.paste(g)
    return c.finish()


def roof_round(w: float, h: float, colour: RGB) -> np.ndarray:
    """Thatched dome (round hut). Straw base tinted a little towards the builder colour, colour band at the eave."""
    c = Canvas(int(math.ceil(w)), int(math.ceil(h)))
    straw = mix(STRAW, colour, 0.35)
    c.ellipse(w / 2, h * 0.55, w / 2, h * 0.5, rgba(shade(straw, 0.85)))
    c.ellipse(w / 2, h * 0.5, w / 2 - 1, h * 0.46, rgba(straw))
    # straw strands radiating from the crown
    for i in range(18):
        a = i / 18 * 6.283
        x0, y0 = w / 2 + math.cos(a) * w * 0.12, h * 0.42 + math.sin(a) * h * 0.1
        x1, y1 = w / 2 + math.cos(a) * w * 0.48, h * 0.5 + math.sin(a) * h * 0.45
        c.line([(x0, y0), (x1, y1)], rgba(shade(straw, 0.8), 150), 0.8)
    c.ellipse(w / 2, h * 0.5, w / 2 - 1, h * 0.46, None, rgba(colour), 2.2)  # colour band
    c.ellipse(w / 2 - w * 0.12, h * 0.32, w * 0.2, h * 0.14, (255, 255, 255, 70))
    c.ellipse(w / 2, h * 0.36, 2.2, 2.2, rgba(shade(colour, 0.8)))  # crown knot
    return c.finish()


def chimney(colour: RGB) -> np.ndarray:
    c = Canvas(10, 12)
    c.rect(1, 2, 9, 12, rgba(STONE))
    for y in (4.5, 7.5, 10.5):
        c.line([(1, y), (9, y)], rgba(STONE_D, 150), 0.6)
    c.rect(0.4, 0.6, 9.6, 3.0, rgba(STONE_D))
    c.ellipse(5, 1.8, 3.0, 1.0, rgba((40, 36, 34)))
    return c.finish()


def door(palette: str) -> np.ndarray:
    c = Canvas(13, 17)
    c.rounded_rect(1, 0.5, 12, 16.5, 5.5, rgba(WOOD), rgba(shade(WOOD, 0.6)), 0.7)
    for x in (4.6, 8.4):
        c.line([(x, 2), (x, 16)], rgba(shade(WOOD, 0.75)), 0.6)
    c.ellipse(9.6, 10, 1.1, 1.1, rgba((230, 200, 110)))
    c.rect(0, 16, 13, 17, rgba(STONE))
    return c.finish()


def window(lit: bool) -> np.ndarray:
    c = Canvas(13, 13)
    glass = GLASS_NIGHT if lit else GLASS_DAY
    c.rounded_rect(1, 1, 12, 12, 1.2, rgba(glass), rgba(WOOD), 1.0)
    c.line([(6.5, 1), (6.5, 12)], rgba(WOOD), 0.9)
    c.line([(1, 6.5), (12, 6.5)], rgba(WOOD), 0.9)
    if lit:
        c.ellipse(4, 4, 1.5, 1.2, (255, 255, 255, 150))
    else:
        c.polygon([(2, 2), (5.5, 2), (2, 7.5)], (255, 255, 255, 80))
    c.rect(0, 12, 13, 13, rgba(shade(WOOD, 1.2)))  # sill
    return c.finish()


def window_glow() -> np.ndarray:
    g = Canvas(28, 28)
    g.ellipse(14, 15, 11, 9, rgba(GLASS_NIGHT, 120))
    g.blur(3.0)
    return g.finish()


def fence(n: int) -> np.ndarray:
    w = n * 6 + 2
    c = Canvas(w, 10)
    c.rect(0, 4, w, 5.2, rgba(WOOD_L))
    c.rect(0, 7, w, 8.2, rgba(WOOD_L))
    for i in range(n):
        x = 1 + i * 6
        c.polygon([(x, 2.5), (x + 1.5, 0.5), (x + 3, 2.5), (x + 3, 10), (x, 10)], rgba(shade(WOOD_L, 1.15)),
                  rgba(WOOD), 0.4)
    return c.finish()


def well(colour: RGB) -> np.ndarray:
    c = Canvas(22, 24)
    sh = Canvas(22, 24)
    sh.ellipse(11, 21, 9, 3, (0, 0, 0, 90))
    sh.blur(1.0)
    c.paste(sh)
    c.ellipse(11, 17, 8.5, 5.0, rgba(STONE), rgba(STONE_D), 0.8)
    c.ellipse(11, 16.5, 5.5, 3.0, rgba(hex_rgb("#2E6FB0")))
    c.ellipse(9.5, 15.8, 1.6, 0.8, (255, 255, 255, 170))
    c.rect(3, 4, 4.5, 16, rgba(WOOD))
    c.rect(17.5, 4, 19, 16, rgba(WOOD))
    c.polygon([(0.5, 6), (11, 0.5), (21.5, 6), (21.5, 8.5), (11, 3.5), (0.5, 8.5)], rgba(colour), rgba(shade(colour, 0.6)),
              0.6)
    c.line([(11, 6), (11, 12)], rgba(WOOD), 0.8)
    c.ellipse(11, 12.5, 1.5, 1.5, rgba(WOOD_L), rgba(WOOD), 0.5)
    return c.finish()


def banner(colour: RGB) -> np.ndarray:
    c = Canvas(16, 26)
    c.rect(3, 2, 4.4, 26, rgba(WOOD))
    c.polygon([(4.4, 2.5), (15.5, 6.5), (4.4, 11)], rgba(colour), rgba(shade(colour, 0.6)), 0.6)
    c.polygon([(4.4, 3.5), (10, 5.5), (4.4, 7.5)], (255, 255, 255, 70))
    c.ellipse(3.7, 1.8, 1.6, 1.6, rgba(shade(colour, 1.3)))
    return c.finish()


def planter() -> np.ndarray:
    c = Canvas(16, 10)
    c.rounded_rect(1, 5, 15, 9.5, 1.0, rgba(WOOD_L), rgba(WOOD), 0.6)
    rng = Genes("planter", "").rng()
    cols = [hex_rgb("#FF8FB1"), hex_rgb("#FFE066"), hex_rgb("#FFFFFF"), hex_rgb("#C9A7FF"), hex_rgb("#FF6F61")]
    for i in range(5):
        x = 2.8 + i * 2.6
        c.ellipse(x, 5.5 - rng.uniform(0, 1.5), 1.5, 1.5, rgba(hex_rgb("#6FAE4B")))
        c.ellipse(x, 3.6 - rng.uniform(0, 1.2), 1.6, 1.6, rgba(cols[i % 5]))
    return c.finish()


def lantern(lit: bool) -> np.ndarray:
    c = Canvas(24, 30)
    if lit:
        g = Canvas(24, 30)
        g.ellipse(12, 9, 10, 8, rgba(GLASS_NIGHT, 110))
        g.blur(2.6)
        c.paste(g)
    c.rect(11, 8, 13, 28, rgba((60, 54, 50)))
    c.rounded_rect(9, 4, 15, 11, 1.2, rgba(GLASS_NIGHT if lit else hex_rgb("#8FA8BF")), rgba((60, 54, 50)), 0.8)
    c.polygon([(8, 4.5), (12, 1.5), (16, 4.5)], rgba((60, 54, 50)))
    c.ellipse(12, 28, 3.5, 1.5, rgba((60, 54, 50)))
    return c.finish()


def smoke(frame: int) -> np.ndarray:
    c = Canvas(24, 28)
    for i in range(3):
        t = (i + frame * 0.34) % 3
        y = 24 - t * 7.5
        r = 2.6 + t * 1.6
        x = 12 + math.sin((t + frame) * 1.3) * 3.0
        c.ellipse(x, y, r, r * 0.85, rgba((242, 242, 238), int(200 - t * 55)))
        c.ellipse(x - r * 0.3, y - r * 0.3, r * 0.45, r * 0.4, (255, 255, 255, int(120 - t * 30)))
    c.blur(0.6)
    return c.finish()


PARTS = ["wall", "roof_gable", "roof_hip", "roof_round", "chimney", "door", "window", "fence", "well", "banner",
         "planter", "lantern", "smoke"]


# ----------------------------------------------------------------------------- composer
_CACHE: Dict[Tuple[str, int, bool], np.ndarray] = {}


def plan(name: str) -> Dict:
    g = Genes(name, "cottage-v1")
    col = genome(name)["body"]
    return {
        "colour": col,
        "wall": ("plaster", "stone", "timber", "whitewash")[g.pick(4)],
        "roof": ("gable", "gable", "hip", "round")[g.pick(4)],
        "chimney_side": g.pick(2),
        "door_side": g.pick(3),  # 0 left, 1 centre, 2 right
        "deco": g.pick(4),        # 0 planter, 1 fence, 2 banner, 3 lantern
        "windows": 1 + g.pick(2),
    }


def footprint(stage: int) -> Tuple[int, int]:
    return {1: (62, 56), 2: (80, 70), 3: (110, 78)}[stage]


def cottage(name: str, stage: int = 2, night: bool = False, smoke_frame: int = -1) -> np.ndarray:
    key = ((name or "").lower(), stage, night, smoke_frame)
    if key in _CACHE:
        return _CACHE[key]
    from common import alpha_blit
    p = plan(name)
    W, H = footprint(stage)
    out = np.zeros((H + 14, W + 12, 4), np.uint8)  # margin for glow/smoke/banner
    ox, oy = 6, 12

    def put(spr, x, y):
        _blit_rgba(out, spr, int(round(ox + x)), int(round(oy + y)))

    # ground shadow
    sh = Canvas(W + 12, H + 14)
    sh.rounded_rect(ox - 1, oy + H * 0.35, ox + W + 2, oy + H + 1.5, 3, (10, 20, 10, 110))
    sh.blur(1.6)
    _blit_rgba(out, sh.finish(), 0, 0)

    wall_h = H * 0.34
    if p["roof"] == "round" and stage < 3:
        rw = W
        put(wall(rw * 0.8, wall_h, p["wall"], name), rw * 0.1, H - wall_h)
        put(roof_round(rw, H - wall_h + 6, p["colour"]), 0, 0)
        door_x = rw * 0.5 - 6
    else:
        main_w = W if stage < 3 else W * 0.62
        put(wall(main_w, wall_h, p["wall"], name), 0, H - wall_h)
        roof = roof_hip if p["roof"] == "hip" else roof_gable
        put(roof(main_w + 4, H - wall_h + 3, p["colour"]), -2, 0)
        if stage == 3:  # annex: lower, on the right, same colour a shade different
            ax = main_w - 2
            aw = W - ax
            put(wall(aw, wall_h * 0.85, p["wall"], name + "x"), ax, H - wall_h * 0.85)
            put(roof_gable(aw + 3, (H - wall_h) * 0.7, shade(p["colour"], 0.92)), ax - 1, (H - wall_h) * 0.3 + 3)
        door_x = (main_w * 0.18, main_w * 0.5 - 6, main_w * 0.82 - 13)[p["door_side"]]
        # chimney sits on the back slope
        chx = main_w * 0.18 if p["chimney_side"] else main_w * 0.72
        put(chimney(p["colour"]), chx, 3)
        if smoke_frame >= 0:
            put(smoke(smoke_frame), chx - 7, -20)
    # door + windows on the front wall
    put(door(p["wall"]), door_x, H - 17)
    wy = H - wall_h + 4
    slots = [x for x in (W * 0.10, W * 0.36, W * 0.62, W * 0.84) if abs(x - door_x) > 15][: p["windows"] + (stage >= 3)]
    win = window(night)
    for x in slots:
        if night:
            put(window_glow(), x - 9, wy - 9)
        put(win, x, wy)
    if night:  # the door leaks light too
        put(window_glow(), door_x - 8, H - 20)
    # decoration
    d = p["deco"]
    if d == 0:
        put(planter(), max(2, door_x - 20) if door_x > W * 0.4 else door_x + 16, H - 9)
    elif d == 1:
        put(fence(4), W - 30, H - 4)
    elif d == 2:
        put(banner(p["colour"]), W - 8, H - 30)
    else:
        put(lantern(night), W - 6, H - 22)
    _CACHE[key] = out
    return out


def _blit_rgba(dst: np.ndarray, src: np.ndarray, x: int, y: int) -> None:
    """RGBA-over-RGBA composite (premultiplied-free 'over')."""
    H, W = dst.shape[:2]
    h, w = src.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    s = src[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32) / 255.0
    d = dst[y0:y1, x0:x1].astype(np.float32) / 255.0
    sa, da = s[..., 3:4], d[..., 3:4]
    oa = sa + da * (1 - sa)
    rgb = (s[..., :3] * sa + d[..., :3] * da * (1 - sa)) / np.maximum(oa, 1e-6)
    dst[y0:y1, x0:x1, :3] = np.clip(rgb * 255, 0, 255).astype(np.uint8)
    dst[y0:y1, x0:x1, 3] = np.clip(oa[..., 0] * 255, 0, 255).astype(np.uint8)


# ----------------------------------------------------------------------------- kit sheet
def kit_image(path: str) -> str:
    from PIL import Image, ImageDraw, ImageFont
    from common import alpha_blit
    names = ["kai_dnb", "mira_9", "luca_99", "noor.wav", "sami.exe", "zed_ttv"]
    # make sure a round hut is on the sheet
    if not any(plan(n)["roof"] == "round" for n in names):
        for cand in ("xXvtobiXx", "lowkeyjord", "tinytash", "pixel_dude", "quietnoodle", "hollowghost", "ash", "bee"):
            if plan(cand)["roof"] == "round":
                names[-1] = cand
                break
    W, H = 1880, 560
    img = np.zeros((H, W, 3), np.uint8)
    img[...] = (116, 176, 79)
    img[H // 2:] = (52, 70, 60)  # night half
    f = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf", 15)
    col = genome("kai_dnb")["body"]
    parts = [("wall x4", None), ("roof_gable", roof_gable(44, 30, col)), ("roof_hip", roof_hip(44, 30, col)),
             ("roof_round", roof_round(44, 34, col)), ("chimney", chimney(col)), ("door", door("plaster")),
             ("window", window(False)), ("window lit", window(True)), ("fence", fence(5)), ("well", well(col)),
             ("banner", banner(col)), ("planter", planter()), ("lantern", lantern(False)), ("lantern lit", lantern(True)),
             ("smoke x3", None)]
    x = 10
    for label, spr in parts:
        if label == "wall x4":
            xx = x
            for pal in WALLS:
                alpha_blit(img, wall(24, 18, pal), xx, 40)
                xx += 26
            x = xx + 6
        elif label == "smoke x3":
            xx = x
            for fr in range(3):
                alpha_blit(img, smoke(fr), xx, 30)
                xx += 22
            x = xx + 6
        else:
            alpha_blit(img, spr, x, 60 - spr.shape[0])
            x += spr.shape[1] + 14
    pil = Image.fromarray(img)
    d = ImageDraw.Draw(pil)
    d.text((10, 6), "parts: walls (plaster/stone/timber/whitewash), gable, hip, round roof, chimney, door, window (day/lit),"
                    " fence, well, banner, planter, lantern, smoke", font=f, fill=(250, 246, 236))
    img = np.array(pil)
    label_x = []
    for row, night in enumerate((False, True)):
        y0 = 90 + row * (H // 2)
        x = 14
        for n in names:
            if row == 0:
                label_x.append(x)
            for stage in (1, 2, 3):
                spr = cottage(n, stage, night, smoke_frame=1 if (stage > 1 and night) else -1)
                alpha_blit(img, spr, x, y0 + 90 - spr.shape[0] + 14)
                x += spr.shape[1] + 6
            x += 10
    pil = Image.fromarray(img)
    d = ImageDraw.Draw(pil)
    d.text((10, 80), "cottages, day: 6 builders x stage 1 hut / 2 cottage / 3 house (roof = the builder's pip colour)",
           font=f, fill=(250, 246, 236))
    d.text((10, H // 2 + 6), "the same at night: windows and lanterns lit, chimneys smoking", font=f,
           fill=(250, 246, 236))
    y = 210
    for n, lx in zip(names, label_x):
        p = plan(n)
        d.text((lx, y), "@%s: %s %s" % (n, p["wall"], p["roof"]), font=f, fill=(250, 246, 236))
    pil.save(path)
    return path


if __name__ == "__main__":
    import time
    t0 = time.perf_counter()
    out = kit_image(os.path.join(os.path.dirname(os.path.abspath(__file__)), "building_kit.png"))
    print("wrote", out, "in %.2fs" % (time.perf_counter() - t0))
