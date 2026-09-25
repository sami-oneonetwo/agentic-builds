"""buildings.py - the building kit of the SETTLEMENT world (canonical art module, 3/4 top-down view).

Every building is drawn procedurally in its OWNER's colours (creatures.palette(username)): the roof is the owner's
main colour, trim is their accent, so at 320x180 a hut is a lit colour dot that says whose it is. Walls are cream
plaster with a shade side away from the sun; wood is wood; everything carries the same dark outline as the settlers.

    from stream.world.art import buildings
    spr, (dx, dy) = buildings.render("hut", tier=2, colour="kai_dnb", seed=0, lit=True, sun=(-0.6, -0.8))
    # blit at (footprint_x - dx, footprint_y - dy); the footprint is w x 1 tiles (32 px), see footprint()

kinds and what the tier does
    hut       tier 0 a tent (1 tile) · 1 a hut (1 tile) · 2 a hut with a chimney and a sign (1 tile) · 3 a hall (2 tiles)
    well      the plaza well (tier ignored)          garden     a fenced bed of the owner's flowers
    fence_h / fence_v   n tiles long (tier = tiles)   banner     pole + flag, 3 flutter phases (seed = phase)
    lantern   post lantern, lit or not                smoke      chimney smoke, 3 phases (seed = phase)
colour is a username (palette from the name) or an (r, g, b) tuple (accent derived). Sprites are RGBA uint8 arrays,
cached per argument tuple. numpy + pillow only, Python 3.9.
"""
from __future__ import annotations

import hashlib
import math
from typing import Dict, Optional, Tuple, Union

import numpy as np
from PIL import Image

from . import creatures
from .tiles import FLAT, OUTLINE, T, _D, _mix, _scale

PLASTER = (238, 224, 192)
PLASTER_DARK = (214, 196, 160)
WOOD = (156, 112, 70)
WOOD_DARK = (110, 76, 46)
DOOR = (92, 62, 42)
PANE_LIT = (255, 232, 150)
PANE_DARK = (112, 150, 176)
STONE = (168, 164, 152)
LANTERN = (250, 204, 92)
CANVAS = (226, 206, 168)
ROOF_RISE, OVERHANG, WALL_H = 10, 3, 10
DEFAULT_SUN = (-0.62, -0.78)
KINDS = ("hut", "well", "garden", "fence_h", "fence_v", "banner", "lantern", "smoke")
_CACHE: Dict[Tuple, Tuple[np.ndarray, Tuple[int, int]]] = {}

ColourLike = Union[str, Tuple[int, int, int]]


def _h(seed: str, k: int) -> int:
    return hashlib.sha1(("%s#%d" % (seed, k)).encode()).digest()[0]


def _sun_bucket(sun) -> Tuple[float, float]:
    sx, sy = sun
    n = math.hypot(sx, sy) or 1.0
    a = round(math.atan2(sy / n, sx / n) / (math.pi / 4)) * (math.pi / 4)
    return (round(math.cos(a), 3), round(math.sin(a), 3))


def colours(colour: ColourLike) -> Dict:
    """Roof / trim colours for an owner: from a username (the settler palette) or a plain RGB main colour."""
    if isinstance(colour, str):
        pal = creatures.palette(colour)
        main, accent, outline = pal["main"], pal["accent"], pal["outline"]
    else:
        main = tuple(int(v) for v in colour[:3])
        accent = _mix((255, 255, 255), (main[1], main[2], main[0]), 0.7)
        outline = _mix(_scale(main, 0.35), (38, 30, 28), 0.5)
    return {"main": main, "light": _mix(main, (255, 255, 240), 0.28), "dark": _mix(main, outline, 0.30),
            "accent": accent, "outline": outline}


def footprint(kind: str, tier: int) -> Tuple[int, int]:
    """(w_tiles, h_tiles) of the ground a building occupies."""
    if kind == "hut":
        return (2 if tier >= 3 else 1, 1)
    if kind in ("fence_h",):
        return (max(1, tier), 1)
    if kind in ("fence_v",):
        return (1, max(1, tier))
    return (1, 1)


# ----------------------------------------------------------------------------- parts
def _roof(d: _D, kind: int, x0: float, y0: float, x1: float, y1: float, col, sun):
    ow = 1.2
    cx = (x0 + x1) / 2.0
    shade_right = sun[0] < 0            # the sun is on the left: the right slope / side is the shade side
    if kind == 0:      # pitched: a trapezoid seen from above-front, ridge cap in the accent, eave shadow
        rise = (y1 - y0) * 0.40
        top = [(x0 + 4, y0), (x1 - 4, y0), (x1, y0 + rise), (x0, y0 + rise)]
        d.poly([(x0, y0 + rise), (x1, y0 + rise), (x1, y1), (x0, y1)], col["main"], col["outline"], ow)
        d.poly(top, col["light"], col["outline"], ow)
        d.line([(x0 + 4, y0), (x1 - 4, y0)], col["accent"], 2.2)
        d.line([(x0 + 0.5, y0 + rise), (x1 - 0.5, y0 + rise)], col["outline"], 1.0)
        d.line([(x0 + 2, y1 - 2.2), (x1 - 2, y1 - 2.2)], col["dark"], 1.6)
        for k in range(1, 3):                       # two shingle rows on the lower slope
            yy = y0 + rise + (y1 - y0 - rise) * k / 3.0
            d.line([(x0 + 1.5, yy), (x1 - 1.5, yy)], col["dark"], 0.8)
        sx0, sx1 = (x1 - 4, x1 - 0.8) if shade_right else (x0 + 0.8, x0 + 4)
        d.rect(sx0, y0 + rise + 1, sx1, y1 - 1, col["dark"], r=0.5)
    elif kind == 1:    # dome with a finial
        cy = y1 - (y1 - y0) * 0.48
        rx, ry = (x1 - x0) / 2.0, (y1 - y0) * 0.58
        d.ellipse(cx, cy, rx, ry, col["main"], col["outline"], ow)
        d.ellipse(cx - sun[0] * rx * 0.35, cy - ry * 0.25, rx * 0.5, ry * 0.5, col["dark"])
        d.ellipse(cx + sun[0] * rx * 0.28, cy + sun[1] * ry * 0.36, rx * 0.40, ry * 0.30, col["light"])
        d.line([(x0 + 2, cy + ry * 0.55), (x1 - 2, cy + ry * 0.55)], col["dark"], 1.2)
        d.ellipse(cx, cy - ry * 0.98, 2.4, 2.4, col["accent"], col["outline"], 0.9)
    else:              # tent / pyramid: four faces meeting at an accent peak
        cy = (y0 + y1) / 2.0
        d.rect(x0, y0, x1, y1, col["main"], col["outline"], ow, r=1.0)
        d.poly([(x0, y0), (x1, y0), (cx, cy)], col["light"])
        d.poly([(x0, y1), (x1, y1), (cx, cy)], col["dark"])
        if shade_right:
            d.poly([(x1, y0), (x1, y1), (cx, cy)], col["dark"])
        else:
            d.poly([(x0, y0), (x0, y1), (cx, cy)], col["dark"])
        d.line([(x0, y0), (cx, cy), (x1, y0)], col["outline"], 0.9)
        d.line([(x0, y1), (cx, cy), (x1, y1)], col["outline"], 0.9)
        d.ellipse(cx, cy, 2.4, 2.4, col["accent"], col["outline"], 0.9)


def _wall(d: _D, x0: float, y0: float, x1: float, y1: float, col, door_pos: int, windows: int, lit: bool, sun):
    d.rect(x0, y0, x1, y1, PLASTER, col["outline"], 1.2, r=1.0)
    d.line([(x0 + 1, y1 - 1.2), (x1 - 1, y1 - 1.2)], PLASTER_DARK, 1.4)
    if sun[0] < 0:
        d.rect(x1 - 3.2, y0 + 0.8, x1 - 0.8, y1 - 1.2, PLASTER_DARK, r=0.6)            # shade side (away from the sun)
        d.line([(x0 + 1.2, y0 + 1.6), (x1 - 3.5, y0 + 1.6)], _mix(PLASTER, (255, 255, 245), 0.5), 1.0)
    else:
        d.rect(x0 + 0.8, y0 + 0.8, x0 + 3.2, y1 - 1.2, PLASTER_DARK, r=0.6)
        d.line([(x0 + 3.5, y0 + 1.6), (x1 - 1.2, y0 + 1.6)], _mix(PLASTER, (255, 255, 245), 0.5), 1.0)
    w = x1 - x0
    dx = {0: x0 + 5, 1: (x0 + x1) / 2.0, 2: x1 - 5}[door_pos]
    d.rect(dx - 3.2, y0 + 1.5, dx + 3.2, y1 - 0.6, DOOR, col["outline"], 1.0, r=2.6)
    d.ellipse(dx + 1.6, y0 + 5.5, 0.7, 0.7, LANTERN)
    pane = PANE_LIT if lit else PANE_DARK
    slots = [x0 + w * 0.25, x0 + w * 0.75] if windows >= 2 else [x0 + w * (0.72 if door_pos != 2 else 0.28)]
    for wx in slots:
        if abs(wx - dx) < 7:
            wx = x0 + w * 0.5 + (w * 0.3 if dx < (x0 + x1) / 2 else -w * 0.3)
        d.rect(wx - 2.6, y0 + 2.2, wx + 2.6, y0 + 7.2, pane, col["outline"], 1.0, r=0.8)
        d.line([(wx, y0 + 2.2), (wx, y0 + 7.2)], col["outline"], 0.7)


def _chimney(d: _D, x: float, y: float, col):
    d.rect(x - 2.6, y - 3.5, x + 2.6, y + 3.5, (128, 122, 114), col["outline"], 1.0, r=0.6)
    d.rect(x - 2.6, y - 3.5, x + 2.6, y - 1.5, (168, 162, 152), r=0.6)


# ----------------------------------------------------------------------------- buildings
def _hut(col, seed: str, tier: int, lit: bool, sun) -> Tuple[np.ndarray, Tuple[int, int]]:
    w_tiles = footprint("hut", tier)[0]
    fw = T * w_tiles
    W, H = fw + 2 * OVERHANG + 4, T + ROOF_RISE + 4
    d = _D(W, H)
    ox, oy = OVERHANG + 2, ROOF_RISE + 2          # footprint origin inside the sprite
    d.ellipse(ox + fw / 2.0 - sun[0] * 5, oy + T - 2.5 - sun[1] * 1.5, fw / 2.0 + 4, 5.5, (20, 24, 12, 78))
    if tier == 0:      # tent: canvas walls, a colour roof, a flap door, a peg rope
        d.poly([(ox + 3, oy + T - 1), (ox + fw - 3, oy + T - 1), (ox + fw - 5, oy + T - WALL_H), (ox + 5, oy + T - WALL_H)], CANVAS, col["outline"], 1.1)
        d.poly([(ox + fw / 2 - 3.5, oy + T - 1), (ox + fw / 2 + 3.5, oy + T - 1), (ox + fw / 2, oy + T - WALL_H + 1)], _scale(CANVAS, 0.6), col["outline"], 0.8)
        _roof(d, 2, ox - OVERHANG + 2, oy - ROOF_RISE + 4, ox + fw + OVERHANG - 2, oy + T - WALL_H + 1.5, col, sun)
        d.line([(ox + 2, oy + T - 3), (ox - 2, oy + T + 0.5)], WOOD_DARK, 1.0)
        d.line([(ox + fw - 2, oy + T - 3), (ox + fw + 2, oy + T + 0.5)], WOOD_DARK, 1.0)
        return d.out_rgba(), (ox, oy)
    kind = _h(seed, 1) % 3 if tier < 3 else 0
    _wall(d, ox + 1.5, oy + T - WALL_H, ox + fw - 1.5, oy + T - 0.5, col, _h(seed, 2) % 3, 1 + (w_tiles > 1 or _h(seed, 3) % 2), lit, sun)
    _roof(d, kind, ox - OVERHANG, oy - ROOF_RISE, ox + fw + OVERHANG, oy + T - WALL_H + 1.5, col, sun)
    if tier >= 2 and kind != 1:
        _chimney(d, ox + fw - 7, oy - ROOF_RISE + 6, col)
    if tier >= 2:                                  # accent trim mark on the roof: the owner's sign
        cx, cy = ox + fw * 0.28, oy + (T - WALL_H) * 0.45
        d.ellipse(cx, cy, 3.0, 3.0, col["accent"], col["outline"], 0.9)
    if tier >= 3:                                  # hall: a second sign and a lantern by the door
        d.ellipse(ox + fw * 0.72, oy + (T - WALL_H) * 0.45, 3.0, 3.0, col["accent"], col["outline"], 0.9)
    return d.out_rgba(), (ox, oy)


def _smoke(phase: int) -> Tuple[np.ndarray, Tuple[int, int]]:
    d = _D(16, 20)
    for k in range(3):
        t = (phase / 3.0 + k / 3.0) % 1.0
        y = 17 - t * 15
        r = 1.6 + t * 2.4
        a = int(200 * (1 - t) ** 0.8)
        d.ellipse(8 + math.sin(t * 6.0 + k) * 2.5, y, r, r, (236, 232, 224, a))
    return d.out_rgba(), (8, 19)


def _banner(col, phase: int) -> Tuple[np.ndarray, Tuple[int, int]]:
    """Pole + flag in the owner's main colour with an accent stripe; 3 flutter phases. Anchor = pole foot."""
    d = _D(20, 30)
    d.line([(2.5, 29), (2.5, 3)], OUTLINE, 2.0)
    d.line([(2.5, 28), (2.5, 4)], WOOD, 1.0)
    d.ellipse(2.5, 2.5, 1.6, 1.6, col["accent"], OUTLINE, 0.8)
    wave = (0.0, 1.6, -1.2)[phase % 3]
    pts = [(3.5, 4), (16 + wave, 6.5 + wave * 0.4), (13 + wave * 0.5, 9.5), (16 + wave, 12.5 - wave * 0.4), (3.5, 14.5)]
    d.poly(pts, col["main"], OUTLINE, 0.8)
    d.line([(4, 9.3), (13.5 + wave * 0.6, 9.3)], col["accent"], 1.6)
    return d.out_rgba(), (3, 29)


def _fence(vertical: bool, n_tiles: int) -> Tuple[np.ndarray, Tuple[int, int]]:
    L = T * n_tiles
    if vertical:
        d = _D(8, L)
        d.line([(4, 2), (4, L - 2)], OUTLINE, 3.2)
        d.line([(4, 2), (4, L - 2)], WOOD, 1.6)
        for y in range(4, L, 8):
            d.rect(2.2, y - 2.5, 5.8, y + 2.5, WOOD_DARK, OUTLINE, 0.8, r=0.8)
        return d.out_rgba(), (4, 0)
    d = _D(L, 10)
    d.line([(2, 6), (L - 2, 6)], OUTLINE, 3.2)
    d.line([(2, 6), (L - 2, 6)], WOOD, 1.6)
    for x in range(4, L, 8):
        d.rect(x - 1.8, 2, x + 1.8, 9.2, WOOD_DARK, OUTLINE, 0.8, r=0.8)
    return d.out_rgba(), (0, 5)


def _lantern(lit: bool) -> Tuple[np.ndarray, Tuple[int, int]]:
    d = _D(10, 20)
    d.line([(5, 19), (5, 6)], OUTLINE, 2.4)
    d.line([(5, 18), (5, 7)], WOOD_DARK, 1.0)
    d.rect(2.2, 2, 7.8, 8.5, LANTERN if lit else (150, 132, 96), OUTLINE, 1.0, r=1.2)
    if lit:
        d.rect(3.6, 3.5, 6.4, 6.8, (255, 248, 210), r=0.8)
    return d.out_rgba(), (5, 19)


def _well(col, sun) -> Tuple[np.ndarray, Tuple[int, int]]:
    d = _D(26, 30)
    d.ellipse(13 - sun[0] * 3, 24, 11, 4.5, (20, 24, 12, 70))
    d.ellipse(13, 21, 10, 6, STONE, OUTLINE, 1.2)
    d.ellipse(13, 21, 6.5, 3.6, (46, 112, 166), OUTLINE, 0.9)
    d.line([(13 - 4, 21.5), (13 + 3, 21.5)], (120, 190, 214), 1.0)
    d.line([(4, 20), (4, 8)], OUTLINE, 2.4)
    d.line([(22, 20), (22, 8)], OUTLINE, 2.4)
    d.line([(4, 19), (4, 9)], WOOD, 1.0)
    d.line([(22, 19), (22, 9)], WOOD, 1.0)
    d.rect(1, 3, 25, 9.5, col["main"], OUTLINE, 1.1, r=1.5)
    d.rect(1.3, 3.3, 24.7, 6.0, col["light"], r=1.5)
    return d.out_rgba(), (13, 24)


def _garden(col) -> Tuple[np.ndarray, Tuple[int, int]]:
    d = _D(26, 18)
    d.rect(1, 3, 25, 17, FLAT["soil"], OUTLINE, 1.1, r=2.0)
    for x in (5, 11, 17, 23):
        d.line([(x, 14), (x, 9)], FLAT["leaf"], 1.3)
        d.ellipse(x, 8, 2.3, 2.3, col["accent"], OUTLINE, 0.7)
        d.ellipse(x, 8, 0.8, 0.8, (120, 80, 40))
    return d.out_rgba(), (0, 0)


# ----------------------------------------------------------------------------- public API
def render(kind: str, tier: int = 1, colour: ColourLike = (229, 82, 183), seed: Optional[int] = None,
           lit: bool = False, sun: Tuple[float, float] = DEFAULT_SUN) -> Tuple[np.ndarray, Tuple[int, int]]:
    """One building sprite and its anchor offset (dx, dy): blit the sprite at (ground_x - dx, ground_y - dy) where the
    ground point is the footprint's top-left for hut / garden / fences and the foot of the pole for banner / lantern /
    well. `seed` picks roof shape, door and windows (default: from the colour / name); for smoke and banner it is
    the animation phase. Cached per argument tuple."""
    if kind not in KINDS:
        raise ValueError("unknown building kind %r (one of %s)" % (kind, ", ".join(KINDS)))
    sun_b = _sun_bucket(sun)
    ckey = colour if isinstance(colour, str) else tuple(int(v) for v in colour[:3])
    seed_s = str(seed if seed is not None else (colour.lower() if isinstance(colour, str) else ckey))
    key = (kind, int(tier), ckey, seed_s, bool(lit), sun_b)
    out = _CACHE.get(key)
    if out is not None:
        return out
    col = colours(colour)
    if kind == "hut":
        out = _hut(col, seed_s, tier, lit, sun_b)
    elif kind == "well":
        out = _well(col, sun_b)
    elif kind == "garden":
        out = _garden(col)
    elif kind == "fence_h":
        out = _fence(False, max(1, tier))
    elif kind == "fence_v":
        out = _fence(True, max(1, tier))
    elif kind == "banner":
        out = _banner(col, int(seed or 0))
    elif kind == "lantern":
        out = _lantern(lit)
    else:
        out = _smoke(int(seed or 0))
    _CACHE[key] = out
    return out


def hut(name: str, tier: int = 1, lit: bool = False, sun: Tuple[float, float] = DEFAULT_SUN) -> Tuple[np.ndarray, Tuple[int, int]]:
    """Convenience: the hut of a named settler at a tier."""
    return render("hut", tier, name, None, lit, sun)


# ----------------------------------------------------------------------------- kit sheet
def kit_image(names, sun=DEFAULT_SUN) -> Image.Image:
    from PIL import ImageDraw, ImageFont
    bold = ImageFont.truetype("/System/Library/Fonts/Supplemental/Verdana Bold.ttf", 20)
    scale = 2
    img = Image.new("RGB", (1240, 560), (104, 164, 78))
    d = ImageDraw.Draw(img)

    def put(spr, x, y):
        im = Image.fromarray(spr).resize((spr.shape[1] * scale, spr.shape[0] * scale), Image.Resampling.NEAREST)
        img.paste(im, (x, y), im)
        return im.width

    d.text((20, 12), "huts by tier 0-3 (tent, hut, hut + chimney + sign, hall) · unlit / lit", font=bold, fill=(250, 244, 226))
    for i, n in enumerate(names[:4]):
        x = 20 + i * 300
        d.text((x, 44), "@" + n, font=bold, fill=(250, 244, 226))
        for t in range(4):
            spr, _ = render("hut", t, n, None, t % 2 == 1, sun)
            put(spr, x + (t % 2) * 130, 74 + (t // 2) * 100)
    d.text((20, 290), "well · garden · fence h/v · banner x3 · lantern lit/unlit · smoke x3", font=bold, fill=(250, 244, 226))
    x, y = 20, 330
    x += put(render("well", 1, names[0], None, False, sun)[0], x, y) + 14
    x += put(render("garden", 1, names[1])[0], x, y + 20) + 14
    x += put(render("fence_h", 1)[0], x, y + 30) + 14
    x += put(render("fence_v", 1)[0], x, y) + 14
    for p in range(3):
        x += put(render("banner", 1, names[2], p)[0], x, y) + 8
    x += put(render("lantern", 1, lit=True)[0], x, y) + 8
    x += put(render("lantern", 1, lit=False)[0], x, y) + 14
    for p in range(3):
        x += put(render("smoke", 1, seed=p)[0], x, y) + 6
    return img


if __name__ == "__main__":
    kit_image(["kai_dnb", "sami", "noor.wav", "atleastonce"]).save("/tmp/building_kit.png")
    print("wrote /tmp/building_kit.png")
