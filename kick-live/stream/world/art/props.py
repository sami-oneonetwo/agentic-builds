"""props.py - nature and landmark sprites for the SETTLEMENT world (canonical art module).

Everything here is scenery: trees by age, bushes, flower clumps, stones, a cairn, waystones, the campfire and the
beacon. No animals, no NPCs: the only animate things in the world are the settlers (creatures.py). Every sprite is
an (H, W, 4) uint8 RGBA array drawn at 3x and downsampled, lit by the sun vector the compositor passes in (lit lobes
toward the sun, ground shadow thrown away from it), with Studio C's dark outline so it survives a 3 Mbps encode.

Anchor convention: the ground point of every prop is (W // 2, H - 4) -> use anchor(spr).

    from stream.world.art import props
    spr = props.tree(age=2, variant=0, wind=1, season=1.0, sun=(-0.6, -0.8))   # age 0 sapling .. 3 old
    spr = props.campfire(phase=2, lit=True)                                     # 4 flame phases + embers
    spr = props.beacon(phase=1, lit=True, colour=(229, 82, 183))                # the settlement's tall fire basket
    glow = props.glow(radius=46, colour=(255, 186, 96), strength=0.42)          # additive RGBA disc for lit things
    ax, ay = props.anchor(spr)

Cached per argument tuple. numpy + pillow only, Python 3.9.
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

import numpy as np

from .tiles import FLAT, FLOWERS, OUTLINE, SS, WIND_LEAN, _D, _mix, _rng, _scale, season_colour

DEFAULT_SUN = (-0.62, -0.78)
TREE_R = {0: 6, 1: 9, 2: 12, 3: 16}          # canopy radius by age: sapling, young, grown, old
FIRE = ((255, 236, 150), (255, 190, 70), (236, 110, 48), (170, 52, 34))
_CACHE: Dict[Tuple, np.ndarray] = {}


def _sun_bucket(sun) -> Tuple[float, float]:
    sx, sy = sun
    n = math.hypot(sx, sy) or 1.0
    a = round(math.atan2(sy / n, sx / n) / (math.pi / 4)) * (math.pi / 4)
    return (round(math.cos(a), 3), round(math.sin(a), 3))


def _cached(fn):
    def wrap(*args, **kw):
        key = (fn.__name__, args, tuple(sorted(kw.items())))
        a = _CACHE.get(key)
        if a is None:
            a = fn(*args, **kw)
            _CACHE[key] = a
        return a
    wrap.__name__ = fn.__name__
    wrap.__doc__ = fn.__doc__
    return wrap


def anchor(spr: np.ndarray) -> Tuple[int, int]:
    """Ground point of a prop sprite: bottom centre, 4 px up."""
    return spr.shape[1] // 2, spr.shape[0] - 4


def _shadow(d: _D, cx: float, base_y: float, rx: float, ry: float, sun, alpha: int = 96):
    d.ellipse(cx - sun[0] * rx * 0.45, base_y - sun[1] * ry * 0.3 + 0.5, rx, ry, (20, 24, 12, alpha))


# ----------------------------------------------------------------------------- trees and bushes
@_cached
def tree(age: int, variant: int, wind: int, season: float, sun: Tuple[float, float] = DEFAULT_SUN) -> np.ndarray:
    """Canopy cloud with DEPTH: a dark under-canopy toward the shade, mid lobes, relit sun sides so each lobe reads
    as a sphere, lit lobes and leaf scallops toward the sun, a light crown; a peeking trunk with a trunk shadow;
    ground shadow thrown away from the sun. Sway follows the wind phase (0..3). age 0 is a sapling (a few leaves on a
    stick), 3 an old tree with a wide crown."""
    sun = _sun_bucket(sun)
    R = TREE_R[age]
    W, H = int(R * 3.0) + 4, int(R * 3.1) + 4
    d = _D(W, H)
    rng = _rng("tree", age, variant)
    cx, base_y = W / 2.0, H - 4.0
    sway = WIND_LEAN[wind] * (0.8 + 0.5 * age)
    col = season_colour("tree", season)
    light = season_colour("tree_light", season)
    dark = _scale(col, 0.72)
    _shadow(d, cx, base_y, R * 0.95, R * 0.34, sun)
    if age == 0:                                   # sapling: a stick with three leaves
        d.line([(cx, base_y), (cx + sway * 0.6, base_y - R * 1.6)], OUTLINE, 2.6)
        d.line([(cx, base_y), (cx + sway * 0.6, base_y - R * 1.6)], FLAT["trunk"], 1.2)
        for (dx, dy, r) in ((-0.55, 1.2, 0.5), (0.55, 1.45, 0.5), (0.0, 1.9, 0.55)):
            x, y = cx + sway * 0.6 + dx * R, base_y - dy * R
            d.ellipse(x, y, r * R, r * R * 0.85, col, OUTLINE, 0.9)
            d.ellipse(x + sun[0] * r * R * 0.3, y + sun[1] * r * R * 0.3, r * R * 0.4, r * R * 0.3, light)
        return d.out_rgba()
    d.rect(cx - R * 0.16, base_y - R * 0.75, cx + R * 0.16, base_y, FLAT["trunk"], OUTLINE, 0.8, r=1.0)
    d.rect(cx - sun[0] * R * 0.06, base_y - R * 0.7, cx - sun[0] * R * 0.06 + R * 0.12, base_y - 0.5, _scale(FLAT["trunk"], 0.72), r=0.6)
    ccx, ccy = cx + sway, base_y - R * 1.2
    lobes = []
    n = 4 + age
    for k in range(n):
        a = 2 * math.pi * k / n + rng.uniform(-0.3, 0.3)
        rr = R * rng.uniform(0.36, 0.55)
        lobes.append((ccx + math.cos(a) * R * 0.58, ccy + math.sin(a) * R * 0.48, rr))
    lobes.append((ccx, ccy, R * 0.72))
    ow = 1.0 + 0.15 * age
    for (x, y, rr) in lobes:
        d.ellipse(x, y, rr, rr, OUTLINE)
    for (x, y, rr) in lobes:            # base canopy
        d.ellipse(x, y, rr - ow, rr - ow, col)
    for (x, y, rr) in lobes:            # under-canopy: the part of each lobe away from the sun goes dark
        d.ellipse(x - sun[0] * rr * 0.32, y - sun[1] * rr * 0.32, (rr - ow) * 0.78, (rr - ow) * 0.7, dark)
    for (x, y, rr) in lobes:            # relight the sun side so the lobe reads as a sphere
        d.ellipse(x + sun[0] * rr * 0.12, y + sun[1] * rr * 0.12, (rr - ow) * 0.72, (rr - ow) * 0.66, col)
    lit = sorted(lobes, key=lambda l: l[0] * sun[0] + l[1] * sun[1], reverse=True)[:len(lobes) // 2 + 1]
    for (x, y, rr) in lit:
        d.ellipse(x + sun[0] * rr * 0.30, y + sun[1] * rr * 0.34, rr * 0.42, rr * 0.34, light)
    for _ in range(3 + 2 * age):        # leaf scallops on the lit crown
        a = rng.uniform(0, 6.283)
        rr = rng.uniform(0.15, 0.75) * R
        x, y = ccx + math.cos(a) * rr + sun[0] * R * 0.15, ccy + math.sin(a) * rr * 0.8 + sun[1] * R * 0.15
        d.arc(x, y, 2.0, 1.5, 200, 340, _mix(light, (255, 255, 230), 0.25), 0.9)
    d.ellipse(ccx + sun[0] * R * 0.25, ccy + sun[1] * R * 0.30, R * 0.22, R * 0.16, _mix(light, (255, 255, 230), 0.35))
    return d.out_rgba()


@_cached
def bush(variant: int, wind: int, season: float, sun: Tuple[float, float] = DEFAULT_SUN) -> np.ndarray:
    """Low shrub for meadow edges and hut gardens: three lobes, lit side toward the sun, sometimes berries."""
    sun = _sun_bucket(sun)
    d = _D(22, 18)
    rng = _rng("bush", variant)
    col = season_colour("tree", season)
    light = season_colour("tree_light", season)
    sway = WIND_LEAN[wind] * 0.8
    _shadow(d, 11, 14, 8, 2.4, sun, 80)
    lobes = [(7 + sway, 9.5, 4.6), (15 + sway, 10, 4.2), (11 + sway, 7, 4.8)]
    for (x, y, r) in lobes:
        d.ellipse(x, y, r, r, OUTLINE)
    for (x, y, r) in lobes:
        d.ellipse(x, y, r - 0.9, r - 0.9, col)
    for (x, y, r) in lobes:
        d.ellipse(x + sun[0] * r * 0.3, y + sun[1] * r * 0.3, r * 0.42, r * 0.34, light)
    if variant % 2 == 1:
        for _ in range(3):
            d.ellipse(rng.uniform(6, 16) + sway, rng.uniform(5, 11), 1.1, 1.1, (222, 64, 84), OUTLINE, 0.4)
    return d.out_rgba()


@_cached
def flowers(variant: int, wind: int) -> np.ndarray:
    """A clump of 4-6 flowers on stems in ONE colour (drifts are many clumps along a curve). Bobs with the wind."""
    d = _D(22, 18)
    rng = _rng("flowers", variant)
    col = FLOWERS[variant % len(FLOWERS)]
    bob = WIND_LEAN[wind] * 1.4
    for _ in range(4 + variant % 3):
        x, y = rng.uniform(4, 18), rng.uniform(6, 14)
        d.line([(x, y + 3.5), (x + bob * 0.5, y)], (74, 122, 58), 1.2)
        d.ellipse(x + bob, y, 2.2, 2.2, col, OUTLINE, 0.7)
        d.ellipse(x + bob, y, 0.85, 0.85, (214, 150, 46))
    return d.out_rgba()


# ----------------------------------------------------------------------------- stones and landmarks
def _boulder(d: _D, cx, cy, rx, ry, sun, tone=1.0):
    base = _scale(FLAT["rock_light"], tone)
    d.ellipse(cx, cy, rx, ry, base, FLAT["rock_dark"], 1.0)
    d.ellipse(cx + sun[0] * rx * 0.35, cy + sun[1] * ry * 0.35, rx * 0.45, ry * 0.4, _mix(base, (255, 255, 255), 0.4))
    d.ellipse(cx - sun[0] * rx * 0.3, cy - sun[1] * ry * 0.3 + 1, rx * 0.5, ry * 0.35, _scale(FLAT["rock"], tone))


@_cached
def stone(variant: int, sun: Tuple[float, float] = DEFAULT_SUN) -> np.ndarray:
    """A field boulder, 3 sizes by variant % 3."""
    sun = _sun_bucket(sun)
    d = _D(22, 16)
    rng = _rng("stone", variant)
    k = (0.7, 0.85, 1.0)[variant % 3]
    rx, ry = rng.uniform(6.5, 8.5) * k, rng.uniform(4.5, 5.5) * k
    _shadow(d, 11, 12, rx * 1.1, 3, sun, 90)
    _boulder(d, 11, 12 - ry * 0.8, rx, ry, sun)
    return d.out_rgba()


@_cached
def cairn(n: int, sun: Tuple[float, float] = DEFAULT_SUN) -> np.ndarray:
    """A stack of n (1..5) stones: the settlers' progress marker (each stone a milestone)."""
    sun = _sun_bucket(sun)
    n = max(1, min(5, n))
    d = _D(24, 12 + 5 * n)
    base_y = d.h - 4
    _shadow(d, 12, base_y, 9, 3, sun, 90)
    y = base_y - 3
    for i in range(n):
        rx = 8.0 - i * 1.3
        ry = 3.6 - i * 0.35
        _boulder(d, 12 + (0.6 if i % 2 else -0.4), y - ry * 0.6, rx, ry, sun, tone=1.0 - 0.05 * i)
        y -= ry * 1.35
    return d.out_rgba()


@_cached
def waystone(colour: Tuple[int, int, int], variant: int = 0, sun: Tuple[float, float] = DEFAULT_SUN) -> np.ndarray:
    """A standing stone with a carved mark in a settler's colour: marks a claim, a path fork, a named place."""
    sun = _sun_bucket(sun)
    d = _D(18, 30)
    rng = _rng("waystone", variant)
    base_y = d.h - 4
    _shadow(d, 9, base_y, 7, 2.6, sun, 90)
    top = 6 + rng.uniform(-1, 1)
    pts = [(4.5, base_y - 1), (13.5, base_y - 1), (13 + rng.uniform(-1, 0.5), top + 3), (9 + rng.uniform(-1, 1), top), (5 + rng.uniform(-0.5, 1), top + 4)]
    d.poly(pts, FLAT["rock_light"], FLAT["rock_dark"], 1.0)
    d.line([(6, base_y - 3), (7, top + 5)], _mix(FLAT["rock_light"], (255, 255, 255), 0.35 if sun[0] < 0 else 0.0), 1.4)
    d.line([(12, base_y - 3), (11.5, top + 5)], FLAT["rock"] if sun[0] < 0 else _mix(FLAT["rock_light"], (255, 255, 255), 0.35), 1.6)
    d.ellipse(9, base_y - 12, 2.8, 2.8, colour, OUTLINE, 0.8)
    d.ellipse(9, base_y - 12, 1.0, 1.0, _mix(colour, (255, 255, 240), 0.5))
    return d.out_rgba()


@_cached
def campfire(phase: int, lit: bool = True, sun: Tuple[float, float] = DEFAULT_SUN) -> np.ndarray:
    """A ring of stones around crossed logs; lit: a 4-phase flame (play 0 1 2 3) with embers. Anchor bottom centre."""
    sun = _sun_bucket(sun)
    d = _D(26, 28)
    base_y = d.h - 4
    _shadow(d, 13, base_y, 10, 3.2, sun, 80)
    for k in range(7):
        a = math.pi * (0.12 + 0.76 * k / 6) + math.pi
        x, y = 13 + math.cos(a) * 9.5, base_y - 2.5 + math.sin(a) * 3.6 * -1
        d.ellipse(x, y, 2.2, 1.6, FLAT["rock_light"], FLAT["rock_dark"], 0.8)
    d.line([(7, base_y - 5.5), (19, base_y - 2.5)], OUTLINE, 3.6)
    d.line([(7, base_y - 2.5), (19, base_y - 5.5)], OUTLINE, 3.6)
    d.line([(7, base_y - 5.5), (19, base_y - 2.5)], FLAT["trunk"], 2.0)
    d.line([(7, base_y - 2.5), (19, base_y - 5.5)], FLAT["trunk"], 2.0)
    if not lit:
        d.ellipse(13, base_y - 4, 3.5, 1.6, (70, 60, 56), OUTLINE, 0.6)
        return d.out_rgba()
    ph = phase % 4
    wob = (0.0, 1.2, 0.0, -1.2)[ph]
    hgt = (1.0, 1.15, 0.92, 1.1)[ph]
    fy = base_y - 5
    flame = [(13 - 5.5, fy), (13 + 5.5, fy), (13 + 3.0 + wob * 0.5, fy - 6 * hgt), (13 + wob, fy - 12 * hgt), (13 - 3.0 + wob * 0.5, fy - 6.5 * hgt)]
    d.poly(flame, FIRE[1], FIRE[3], 0.9)
    inner = [(13 - 3.0, fy), (13 + 3.0, fy), (13 + 1.2 + wob * 0.4, fy - 4 * hgt), (13 + wob * 0.6, fy - 7.5 * hgt), (13 - 1.4 + wob * 0.4, fy - 4.2 * hgt)]
    d.poly(inner, FIRE[0])
    rng = _rng("ember", ph)
    for _ in range(3):
        d.ellipse(13 + rng.uniform(-4, 4) + wob, fy - rng.uniform(9, 16) * hgt, 0.7, 0.7, FIRE[0])
    return d.out_rgba()


@_cached
def beacon(phase: int, lit: bool = True, colour: Optional[Tuple[int, int, int]] = None, sun: Tuple[float, float] = DEFAULT_SUN) -> np.ndarray:
    """The settlement's beacon: a tall timber post with a fire basket, banded in a settler's colour (the founder's).
    Lit: a 4-phase flame. Visible from across the map, the thing the night mockup is lit by."""
    sun = _sun_bucket(sun)
    d = _D(24, 52)
    base_y = d.h - 4
    _shadow(d, 12, base_y, 8, 3, sun, 90)
    for k in range(5):                                       # stone footing
        a = math.pi * (0.1 + 0.8 * k / 4) + math.pi
        d.ellipse(12 + math.cos(a) * 6.5, base_y - 2 - math.sin(a) * -2.2, 2.0, 1.4, FLAT["rock_light"], FLAT["rock_dark"], 0.7)
    d.line([(12, base_y - 2), (12, 16)], OUTLINE, 4.6)
    d.line([(12, base_y - 2), (12, 16)], FLAT["trunk"], 2.6)
    d.line([(12 - sun[0] * 0.6, base_y - 3), (12 - sun[0] * 0.6, 17)], _scale(FLAT["trunk"], 0.75), 0.9)
    band = colour or (229, 82, 183)
    d.rect(10, 30, 14, 34, band, OUTLINE, 0.6, r=0.6)
    d.rect(10, 38, 14, 42, band, OUTLINE, 0.6, r=0.6)
    # fire basket: an iron bowl on the post
    d.poly([(5, 17), (19, 17), (16.5, 24), (7.5, 24)], (96, 92, 100), OUTLINE, 0.9)
    d.line([(6, 19.5), (18, 19.5)], (150, 146, 156), 0.9)
    if lit:
        ph = phase % 4
        wob = (0.0, 1.0, 0.0, -1.0)[ph]
        hgt = (1.0, 1.15, 0.9, 1.1)[ph]
        fy = 17.5
        d.poly([(12 - 6, fy), (12 + 6, fy), (12 + 3 + wob * 0.5, fy - 6.5 * hgt), (12 + wob, fy - 13 * hgt), (12 - 3 + wob * 0.5, fy - 7 * hgt)], FIRE[1], FIRE[3], 0.9)
        d.poly([(12 - 3.2, fy), (12 + 3.2, fy), (12 + 1.2 + wob * 0.4, fy - 4.2 * hgt), (12 + wob * 0.6, fy - 8 * hgt), (12 - 1.4 + wob * 0.4, fy - 4.5 * hgt)], FIRE[0])
    else:
        d.ellipse(12, 19, 4, 1.4, (70, 60, 56))
    return d.out_rgba()


def glow(radius: int = 44, colour=(255, 190, 90), strength: float = 0.55) -> np.ndarray:
    """Radial additive glow for lit lanterns, windows, fires (RGBA with a soft falloff; blit additively)."""
    key = ("glow", radius, tuple(colour), strength)
    out = _CACHE.get(key)
    if out is None:
        yy, xx = np.mgrid[-radius:radius + 1, -radius:radius + 1].astype(np.float32)
        r = np.sqrt(xx * xx + yy * yy) / radius
        a = np.clip(1.0 - r, 0, 1) ** 2.2 * strength
        out = np.zeros((2 * radius + 1, 2 * radius + 1, 4), np.uint8)
        out[..., :3] = colour
        out[..., 3] = (a * 255).astype(np.uint8)
        _CACHE[key] = out
    return out


def cloud_shadow(w: int = 340, h: int = 190, strength: float = 0.17) -> np.ndarray:
    """A soft cloud shadow (alpha = darkening) to drift over the ground with the wind; blit with a darken-only blit."""
    from PIL import Image, ImageDraw, ImageFilter
    key = ("cloud", w, h, strength)
    out = _CACHE.get(key)
    if out is None:
        m = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(m)
        d.ellipse([w * 0.15, h * 0.25, w * 0.85, h * 0.8], fill=255)
        d.ellipse([w * 0.05, h * 0.4, w * 0.55, h * 0.9], fill=255)
        d.ellipse([w * 0.45, h * 0.1, w * 0.95, h * 0.65], fill=255)
        m = m.filter(ImageFilter.GaussianBlur(22))
        out = np.zeros((h, w, 4), np.uint8)
        out[..., :3] = (30, 40, 30)
        out[..., 3] = (np.asarray(m, np.float32) * strength).astype(np.uint8)
        _CACHE[key] = out
    return out


def kit_image(season: float = 1.0, sun=DEFAULT_SUN):
    """Review sheet: trees by age x wind, bushes, flowers, stones, cairn 1-5, waystones, campfire, beacon (2x)."""
    from PIL import Image, ImageDraw, ImageFont
    bold = ImageFont.truetype("/System/Library/Fonts/Supplemental/Verdana Bold.ttf", 20)
    img = Image.new("RGB", (1900, 520), (104, 164, 78))
    d = ImageDraw.Draw(img)

    def put(spr, x, y):
        im = Image.fromarray(spr).resize((spr.shape[1] * 2, spr.shape[0] * 2), Image.Resampling.NEAREST)
        img.paste(im, (x, y - im.height), im)
        return im.width

    d.text((20, 12), "trees by age 0-3 x wind · autumn / winter · bushes · flower clumps", font=bold, fill=(250, 244, 226))
    x = 20
    for age in range(4):
        for p in range(4):
            x += put(tree(age, p % 2, p, season, sun), x, 180) + 6
    for s in (2.0, 3.0):
        x += put(tree(2, 0, 1, s, sun), x, 180) + 6
    for v in range(3):
        x += put(bush(v, 1, season, sun), x, 180) + 6
    for v in range(4):
        x += put(flowers(v, 1), x, 180) + 6
    d.text((20, 210), "stones · cairn 1-5 · waystones · campfire phases 0-3 + unlit · beacon phases 0-3 + unlit", font=bold, fill=(250, 244, 226))
    x = 20
    for v in range(3):
        x += put(stone(v, sun), x, 400) + 8
    for n in range(1, 6):
        x += put(cairn(n, sun), x, 400) + 8
    for c in ((229, 82, 183), (82, 180, 229), (240, 196, 80)):
        x += put(waystone(c, 0, sun), x, 400) + 8
    for p in range(4):
        x += put(campfire(p, True, sun), x, 400) + 8
    x += put(campfire(0, False, sun), x, 400) + 16
    for p in range(4):
        x += put(beacon(p, True, (229, 82, 183), sun), x, 400) + 8
    x += put(beacon(0, False, (229, 82, 183), sun), x, 400) + 8
    return img


if __name__ == "__main__":
    kit_image().save("/tmp/props_kit.png")
    print("wrote /tmp/props_kit.png")
