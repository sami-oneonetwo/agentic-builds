"""buildings.py - settlers-round building kit (from studio-c; shadows now fall away from the sun, walls carry a shade side) (SETTLEMENT top-down, 3/4 view).

Every building part is drawn procedurally in the BUILDER's colours (creatures.palette(username)): the roof is
the builder's main colour, trim is their accent, so at 320x180 a hut is a lit colour dot that says whose it is.
Walls are cream plaster; wood is wood; everything carries the same dark outline as the creatures.

Parts (all RGBA sprites): roof_pitched, roof_dome, roof_tent, wall (with door + windows), chimney, smoke(phase),
banner(phase), fence(h/v), lantern(lit) + glow, well, garden.  hut() composes them from the username hash.

3/4 top-down convention: a hut's FOOTPRINT is w x 1 tiles (32 px each); the roof rises 10 px above the footprint
and overhangs 3 px each side, the front wall strip is the bottom 10 px of the footprint. hut() returns the sprite
and the (dx, dy) to subtract from the footprint's top-left pixel when blitting.

    import buildings
    spr, (dx, dy) = buildings.hut("kai_dnb", w_tiles=2, lit=True)
    buildings.kit_image(["kai_dnb", "sami.exe", "noor.wav", "luca_99"]).save("building_kit.png")
"""
from __future__ import annotations

import hashlib
import math
import os
import sys
from typing import Tuple

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import creatures  # noqa: E402
from tiles import _D, _mix, _scale, OUTLINE, T, FLAT, SUN  # noqa: E402

PLASTER = (238, 224, 192)
PLASTER_DARK = (214, 196, 160)
WOOD = (156, 112, 70)
WOOD_DARK = (110, 76, 46)
DOOR = (92, 62, 42)
PANE_LIT = (255, 232, 150)
PANE_DARK = (112, 150, 176)
STONE = (168, 164, 152)
LANTERN = (250, 204, 92)
ROOF_RISE, OVERHANG, WALL_H = 10, 3, 10


def _h(name: str, k: int) -> int:
    return hashlib.sha1(("%s#%d" % (name.lower(), k)).encode()).digest()[0]


def colours(name: str):
    pal = creatures.palette(name)
    main = pal["main"]
    return {"main": main, "light": _mix(main, (255, 255, 240), 0.28), "dark": _mix(main, pal["outline"], 0.30),
            "accent": pal["accent"], "outline": pal["outline"]}


# ----------------------------------------------------------------------------- parts
def _roof(d: _D, kind: int, x0: float, y0: float, x1: float, y1: float, col):
    ow = 1.2
    cx = (x0 + x1) / 2.0
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
    elif kind == 1:    # dome with a finial
        cy = y1 - (y1 - y0) * 0.48
        rx, ry = (x1 - x0) / 2.0, (y1 - y0) * 0.58
        d.ellipse(cx, cy, rx, ry, col["main"], col["outline"], ow)
        d.ellipse(cx - rx * 0.28, cy - ry * 0.36, rx * 0.40, ry * 0.30, col["light"])
        d.line([(x0 + 2, cy + ry * 0.55), (x1 - 2, cy + ry * 0.55)], col["dark"], 1.2)
        d.ellipse(cx, cy - ry * 0.98, 2.4, 2.4, col["accent"], col["outline"], 0.9)
    else:              # tent / pyramid: four faces meeting at an accent peak
        cy = (y0 + y1) / 2.0
        d.rect(x0, y0, x1, y1, col["main"], col["outline"], ow, r=1.0)
        d.poly([(x0, y0), (x1, y0), (cx, cy)], col["light"])
        d.poly([(x0, y1), (x1, y1), (cx, cy)], col["dark"])
        d.line([(x0, y0), (cx, cy), (x1, y0)], col["outline"], 0.9)
        d.line([(x0, y1), (cx, cy), (x1, y1)], col["outline"], 0.9)
        d.ellipse(cx, cy, 2.4, 2.4, col["accent"], col["outline"], 0.9)


def _wall(d: _D, x0: float, y0: float, x1: float, y1: float, col, door_pos: int, windows: int, lit: bool):
    d.rect(x0, y0, x1, y1, PLASTER, col["outline"], 1.2, r=1.0)
    d.line([(x0 + 1, y1 - 1.2), (x1 - 1, y1 - 1.2)], PLASTER_DARK, 1.4)
    d.rect(x1 - 3.2, y0 + 0.8, x1 - 0.8, y1 - 1.2, PLASTER_DARK, r=0.6)                # shade side (away from the sun)
    d.line([(x0 + 1.2, y0 + 1.6), (x1 - 3.5, y0 + 1.6)], _mix(PLASTER, (255, 255, 245), 0.5), 1.0)   # lit eave line
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


def hut(name: str, w_tiles: int = 1, lit: bool = False) -> Tuple[np.ndarray, Tuple[int, int]]:
    col = colours(name)
    fw = T * w_tiles
    W, H = fw + 2 * OVERHANG + 4, T + ROOF_RISE + 4
    d = _D(W, H)
    ox, oy = OVERHANG + 2, ROOF_RISE + 2          # footprint origin inside the sprite
    kind = _h(name, 1) % 3
    d.ellipse(ox + fw / 2.0 - SUN[0] * 5, oy + T - 2.5, fw / 2.0 + 4, 5.5, (20, 24, 12, 78))   # ground shadow, away from the sun
    _wall(d, ox + 1.5, oy + T - WALL_H, ox + fw - 1.5, oy + T - 0.5, col, _h(name, 2) % 3, 1 + (w_tiles > 1 or _h(name, 3) % 2), lit)
    _roof(d, kind, ox - OVERHANG, oy - ROOF_RISE, ox + fw + OVERHANG, oy + T - WALL_H + 1.5, col)
    if _h(name, 4) % 3 != 0 and kind != 1:
        _chimney(d, ox + fw - 7, oy - ROOF_RISE + 6, col)
    if _h(name, 5) % 2 == 0:                       # accent trim mark on the roof: the builder's sign
        cx, cy = ox + fw * 0.28, oy + (T - WALL_H) * 0.45
        d.ellipse(cx, cy, 3.0, 3.0, col["accent"], col["outline"], 0.9)
    return d.out_rgba(), (ox, oy)


def smoke(phase: int) -> np.ndarray:
    d = _D(16, 20)
    for k in range(3):
        t = (phase / 3.0 + k / 3.0) % 1.0
        y = 17 - t * 15
        r = 1.6 + t * 2.4
        a = int(200 * (1 - t) ** 0.8)
        d.ellipse(8 + math.sin(t * 6.0 + k) * 2.5, y, r, r, (236, 232, 224, a))
    return d.out_rgba()


def banner(name: str, phase: int) -> np.ndarray:
    """Pole + flag in the builder's main colour with an accent stripe; 3 flutter phases. Anchor bottom-left+1."""
    col = colours(name)
    d = _D(20, 30)
    d.line([(2.5, 29), (2.5, 3)], OUTLINE, 2.0)
    d.line([(2.5, 28), (2.5, 4)], WOOD, 1.0)
    d.ellipse(2.5, 2.5, 1.6, 1.6, col["accent"], OUTLINE, 0.8)
    wave = (0.0, 1.6, -1.2)[phase % 3]
    pts = [(3.5, 4), (16 + wave, 6.5 + wave * 0.4), (13 + wave * 0.5, 9.5), (16 + wave, 12.5 - wave * 0.4), (3.5, 14.5)]
    d.poly(pts, col["main"], OUTLINE, 0.8)
    d.line([(4, 9.3), (13.5 + wave * 0.6, 9.3)], col["accent"], 1.6)
    return d.out_rgba()


def fence(vertical: bool, n_tiles: int = 1) -> np.ndarray:
    L = T * n_tiles
    if vertical:
        d = _D(8, L)
        d.line([(4, 2), (4, L - 2)], OUTLINE, 3.2)
        d.line([(4, 2), (4, L - 2)], WOOD, 1.6)
        for y in range(4, L, 8):
            d.rect(2.2, y - 2.5, 5.8, y + 2.5, WOOD_DARK, OUTLINE, 0.8, r=0.8)
    else:
        d = _D(L, 10)
        d.line([(2, 6), (L - 2, 6)], OUTLINE, 3.2)
        d.line([(2, 6), (L - 2, 6)], WOOD, 1.6)
        for x in range(4, L, 8):
            d.rect(x - 1.8, 2, x + 1.8, 9.2, WOOD_DARK, OUTLINE, 0.8, r=0.8)
    return d.out_rgba()


def lantern(lit: bool) -> np.ndarray:
    d = _D(10, 20)
    d.line([(5, 19), (5, 6)], OUTLINE, 2.4)
    d.line([(5, 18), (5, 7)], WOOD_DARK, 1.0)
    d.rect(2.2, 2, 7.8, 8.5, LANTERN if lit else (150, 132, 96), OUTLINE, 1.0, r=1.2)
    if lit:
        d.rect(3.6, 3.5, 6.4, 6.8, (255, 248, 210), r=0.8)
    return d.out_rgba()


def glow(radius: int = 44, colour=(255, 190, 90), strength: float = 0.55) -> np.ndarray:
    """Radial additive glow for lit lanterns / windows at dusk. RGBA with a soft falloff."""
    yy, xx = np.mgrid[-radius:radius + 1, -radius:radius + 1].astype(np.float32)
    r = np.sqrt(xx * xx + yy * yy) / radius
    a = np.clip(1.0 - r, 0, 1) ** 2.2 * strength
    out = np.zeros((2 * radius + 1, 2 * radius + 1, 4), np.uint8)
    out[..., :3] = colour
    out[..., 3] = (a * 255).astype(np.uint8)
    return out


def well(name: str) -> np.ndarray:
    col = colours(name)
    d = _D(26, 30)
    d.ellipse(13, 24, 11, 4.5, (20, 24, 12, 70))
    d.ellipse(13, 21, 10, 6, STONE, OUTLINE, 1.2)
    d.ellipse(13, 21, 6.5, 3.6, (46, 112, 166), OUTLINE, 0.9)
    d.line([(13 - 4, 21.5), (13 + 3, 21.5)], (120, 190, 214), 1.0)
    d.line([(4, 20), (4, 8)], OUTLINE, 2.4)
    d.line([(22, 20), (22, 8)], OUTLINE, 2.4)
    d.line([(4, 19), (4, 9)], WOOD, 1.0)
    d.line([(22, 19), (22, 9)], WOOD, 1.0)
    d.rect(1, 3, 25, 9.5, col["main"], OUTLINE, 1.1, r=1.5)
    d.rect(1.3, 3.3, 24.7, 6.0, col["light"], r=1.5)
    return d.out_rgba()


def garden(name: str) -> np.ndarray:
    col = colours(name)
    d = _D(26, 18)
    d.rect(1, 3, 25, 17, FLAT["soil"], OUTLINE, 1.1, r=2.0)
    for x in (5, 11, 17, 23):
        d.line([(x, 14), (x, 9)], FLAT["leaf"], 1.3)
        d.ellipse(x, 8, 2.3, 2.3, col["accent"], OUTLINE, 0.7)
        d.ellipse(x, 8, 0.8, 0.8, (120, 80, 40))
    return d.out_rgba()


# ----------------------------------------------------------------------------- kit sheet
def kit_image(names) -> Image.Image:
    from PIL import ImageFont
    bold = ImageFont.truetype("/System/Library/Fonts/Supplemental/Verdana Bold.ttf", 20)
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Verdana.ttf", 20)
    scale = 2
    grass_col = (104, 164, 78)
    W, H = 1180, 700
    img = Image.new("RGB", (W, H), grass_col)
    d = ImageDraw.Draw(img)

    def put(spr, x, y):
        im = Image.fromarray(spr).resize((spr.shape[1] * scale, spr.shape[0] * scale), Image.Resampling.NEAREST)
        img.paste(im, (x, y), im)
        return im.width

    d.text((20, 12), "parts (2x): roofs pitched / dome / tent · smoke x3 · banner x3 · fence h/v · lantern · well · garden", font=bold, fill=(250, 244, 226))
    x, y = 20, 50
    for k, n in enumerate(names[:3]):
        col = colours(n)
        dd = _D(44, 30)
        _roof(dd, k, 4, 3, 40, 27, col)
        x += put(dd.out_rgba(), x, y) + 14
    for p in range(3):
        x += put(smoke(p), x, y) + 6
    x += 10
    for p in range(3):
        x += put(banner(names[0], p), x, y) + 8
    x += put(fence(False, 1), x, y + 20) + 12
    x += put(fence(True, 1), x, y - 10) + 12
    x += put(lantern(True), x, y) + 8
    x += put(lantern(False), x, y) + 14
    x += put(well(names[1]), x, y) + 14
    x += put(garden(names[2]), x, y + 10) + 14

    d.text((20, 150), "huts composed from the username · 1 and 2 tiles wide · unlit (day) and lit (evening)", font=bold, fill=(250, 244, 226))
    y = 190
    for i, n in enumerate(names):
        x = 20 + i * 290
        d.text((x, y), "@" + n, font=bold, fill=(250, 244, 226))
        spr, _ = hut(n, 1, False)
        put(spr, x, y + 34)
        spr, _ = hut(n, 2, True)
        put(spr, x + 100, y + 34)
        spr, _ = hut(n, 1, True)
        put(spr, x, y + 150)
    d.text((20, 420), "1x scale, as on stream (32 px footprint), with fences, banners, lanterns and the well:", font=font, fill=(236, 240, 220))
    y = 460
    base = np.zeros((200, 1140, 3), np.uint8)
    base[:] = grass_col
    scene = Image.fromarray(base)
    for i, n in enumerate(names):
        spr, (dx, dy) = hut(n, 1 + (i % 2), i % 2 == 1)
        im = Image.fromarray(spr)
        scene.paste(im, (40 + i * 240 - dx, 60 - dy), im)
        b = Image.fromarray(banner(n, i % 3))
        scene.paste(b, (40 + i * 240 + 60 + 32 * (i % 2), 40), b)
        f = Image.fromarray(fence(False, 2))
        scene.paste(f, (40 + i * 240 - 6, 112), f)
        ln = Image.fromarray(lantern(True))
        scene.paste(ln, (40 + i * 240 - 18, 78), ln)
    wl = Image.fromarray(well(names[0]))
    scene.paste(wl, (1000, 60), wl)
    gd = Image.fromarray(garden(names[1]))
    scene.paste(gd, (1000, 120), gd)
    img.paste(scene, (20, y))
    return img


if __name__ == "__main__":
    names = ["kai_dnb", "sami.exe", "noor.wav", "luca_99"]
    kit_image(names).save("/Users/sandy/Workspace/agentic-builds/kick-live/docs/art/settlers-round/building_kit.png")
    print("ok")
