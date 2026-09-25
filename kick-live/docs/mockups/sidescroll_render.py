#!/usr/bin/env python3
"""sidescroll concept render for the SETTLEMENT redesign (journal 020).

Concept render, not the product. Draws two 1280x720 frames + a 320x180 thumb with numpy + Pillow
only: procedural sky, clouds, parallax hills / forest / plain, a downhill river, a near meadow with
wind-bent grass, chat-raised huts, and real-person creatures from stream/world/pips.py.
Everything is rendered at 2x and downsampled (anti-aliased shapes); text is drawn at screen scale.

    ~/.local/share/kick-live/venv/bin/python docs/mockups/sidescroll_render.py
"""
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = "/Users/sandy/Workspace/agentic-builds/kick-live"
sys.path.insert(0, ROOT)
try:
    from stream.world import pips  # noqa: E402
except Exception as e:  # pragma: no cover
    print("pips.py did not import, falling back to plain shapes:", e)
    pips = None

OUT = os.path.join(ROOT, "docs", "mockups")
W, H = 1280, 720
S = 2                        # supersample factor for the world layer
WS, HS = W * S, H * S
FONT_DIR = "/System/Library/Fonts/"


# ----------------------------------------------------------------------------- fonts
def _hn_medium_index():
    for i in range(0, 24):
        try:
            f = ImageFont.truetype(FONT_DIR + "HelveticaNeue.ttc", 20, index=i)
            if f.getname()[1].lower() == "medium":
                return i
        except Exception:
            break
    return 0


HN_IDX = _hn_medium_index()
_FONTS = {}


def font(kind, size):
    key = (kind, size)
    if key not in _FONTS:
        if kind == "menlo":
            _FONTS[key] = ImageFont.truetype(FONT_DIR + "Menlo.ttc", size, index=0)
        elif kind == "hn":
            _FONTS[key] = ImageFont.truetype(FONT_DIR + "HelveticaNeue.ttc", size, index=HN_IDX)
        else:
            _FONTS[key] = ImageFont.truetype(FONT_DIR + "Supplemental/Arial Black.ttf", size)
    return _FONTS[key]


# ----------------------------------------------------------------------------- noise
def noise1d(n, period, seed, octaves=3, persistence=0.5, offset=0.0):
    """Smoothed value noise in [0,1], sampled at n points; `offset` shifts along x (camera)."""
    rng = np.random.RandomState(seed)
    out = np.zeros(n)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        p = max(2.0, period / (2 ** o))
        lattice = rng.rand(4096)
        x = (np.arange(n) + offset) / p
        i = np.floor(x).astype(int)
        t = x - i
        t = t * t * (3 - 2 * t)
        v = lattice[i % 4096] * (1 - t) + lattice[(i + 1) % 4096] * t
        out += v * amp
        total += amp
        amp *= persistence
    return out / total


def noise2d(h, w, period, seed, octaves=3, persistence=0.5, offset=0.0):
    rng = np.random.RandomState(seed)
    out = np.zeros((h, w))
    amp, total = 1.0, 0.0
    for o in range(octaves):
        p = max(2.0, period / (2 ** o))
        lattice = rng.rand(512, 512)
        ys = np.arange(h) / p
        xs = (np.arange(w) + offset) / p
        yi = np.floor(ys).astype(int)[:, None]
        xi = np.floor(xs).astype(int)[None, :]
        ty = (ys - np.floor(ys))[:, None]
        tx = (xs - np.floor(xs))[None, :]
        ty = ty * ty * (3 - 2 * ty)
        tx = tx * tx * (3 - 2 * tx)
        a = lattice[yi % 512, xi % 512]
        b = lattice[yi % 512, (xi + 1) % 512]
        c = lattice[(yi + 1) % 512, xi % 512]
        d = lattice[(yi + 1) % 512, (xi + 1) % 512]
        v = (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty
        out += v * amp
        total += amp
        amp *= persistence
    return out / total


def lerp(a, b, t):
    return np.asarray(a, float) * (1 - t) + np.asarray(b, float) * t


def col(c, k=1.0):
    return tuple(int(max(0, min(255, v * k))) for v in c)


# ----------------------------------------------------------------------------- scene parameters
def scene_params(kind, cam_x):
    p = {"kind": kind, "cam": cam_x}
    if kind == "dawn":
        p.update(
            sky_top=(96, 138, 186), sky_mid=(178, 198, 216), sky_low=(252, 214, 168),
            sun=(1010, 396), sun_r=28, sun_col=(255, 246, 214), glow_col=(255, 214, 150), glow=0.55,
            sun_dir=+1,                       # light from the right
            cloud_lit=(255, 250, 240), cloud_shade=(214, 196, 200),
            far1=(158, 176, 200), far2=(128, 152, 170), forest_back=(104, 140, 122),
            forest=(72, 112, 86), plain_top=(150, 178, 128), plain_low=(128, 168, 96),
            grass=(118, 168, 84), grass_lit=(190, 212, 110), grass_dark=(84, 132, 66),
            soil=(112, 84, 58), soil_dark=(84, 62, 44),
            water_far=(170, 196, 214), water=(96, 150, 190), ripple=(220, 236, 240),
            mist=0.35, wind=0.42, moon=None,
        )
    else:
        p.update(
            sky_top=(64, 66, 126), sky_mid=(216, 128, 116), sky_low=(255, 198, 104),
            sun=(236, 424), sun_r=34, sun_col=(255, 236, 190), glow_col=(255, 170, 90), glow=0.85,
            sun_dir=-1,                       # light from the left
            cloud_lit=(255, 214, 178), cloud_shade=(150, 108, 132),
            far1=(140, 118, 156), far2=(112, 96, 134), forest_back=(96, 98, 106),
            forest=(60, 80, 74), plain_top=(160, 150, 104), plain_low=(140, 156, 88),
            grass=(126, 154, 74), grass_lit=(222, 190, 96), grass_dark=(88, 112, 60),
            soil=(108, 78, 56), soil_dark=(78, 56, 42),
            water_far=(214, 170, 150), water=(110, 130, 170), ripple=(255, 220, 170),
            mist=0.12, wind=0.30, moon=(1130, 150),
        )
    return p


# ----------------------------------------------------------------------------- terrain (world x)
GROUND_Y = 566
RIVER_W = 96
CREATURE_K = 6               # screen px per sim px (the cave used 4; the open frame needs bigger bodies)


def ground_y(world_x):
    """Near-ground line in screen px for an array of WORLD x positions (camera-independent)."""
    n = noise1d(len(world_x), 260, 11, octaves=2, offset=float(world_x[0]))
    return GROUND_Y + (n - 0.5) * 18


def river_x(kind):
    """World x of the near river channel centre for each frame's stretch of world."""
    return 3160 if kind == "dawn" else 5000


# ----------------------------------------------------------------------------- numpy layers
def paint_sky(img, p):
    y = np.linspace(0, 1, HS)[:, None, None]
    hz = 0.63
    t1 = np.clip(y / hz, 0, 1)
    t2 = np.clip((y - hz) / (1 - hz), 0, 1)
    sky = lerp(p["sky_top"], p["sky_mid"], t1)
    sky = np.where(y < hz, sky, lerp(p["sky_mid"], p["sky_low"], t2))
    img[:] = sky + np.random.RandomState(3).uniform(-1.2, 1.2, (HS, WS, 1))  # dither


def paint_sun(img, p):
    sx, sy = p["sun"][0] * S, p["sun"][1] * S
    yy, xx = np.mgrid[0:HS, 0:WS]
    d = np.sqrt((xx - sx) ** 2 + (yy - sy) ** 2) / S
    glow = np.exp(-(d / 210.0) ** 2) * p["glow"] + np.exp(-(d / 60.0) ** 2) * 0.6
    img[:] = np.clip(img + glow[..., None] * (np.asarray(p["glow_col"]) - img) * 0.9, 0, 255)
    disc = np.clip((p["sun_r"] + 1.5 - d) / 3.0, 0, 1)[..., None]
    img[:] = img * (1 - disc) + np.asarray(p["sun_col"]) * disc


def paint_moon(img, p):
    if not p["moon"]:
        return
    mx, my = p["moon"][0] * S, p["moon"][1] * S
    yy, xx = np.mgrid[0:HS, 0:WS]
    d = np.sqrt((xx - mx) ** 2 + (yy - my) ** 2) / S
    disc = np.clip((16 - d) / 1.5, 0, 1)
    # waxing crescent: subtract an offset disc
    d2 = np.sqrt((xx - mx - 9 * S) ** 2 + (yy - my + 3 * S) ** 2) / S
    disc = disc * (1 - np.clip((15 - d2) / 1.5, 0, 1))
    disc = disc[..., None] * 0.75
    img[:] = img * (1 - disc) + np.asarray((246, 240, 224)) * disc


def paint_clouds(img, p, seed, cam):
    """Two banks of soft clouds; tops lit by the sun, undersides shaded."""
    sky_h = int(HS * 0.62)
    lo_h, lo_w = sky_h // 16, WS // 16
    n = noise2d(lo_h, lo_w, 18, seed, octaves=3, persistence=0.5, offset=cam * 0.04 / 16)
    band = np.exp(-((np.linspace(0, 1, lo_h) - 0.40) / 0.26) ** 2)[:, None]
    a = np.clip((n - 0.53) * 4.0, 0, 1) * band
    a = np.asarray(Image.fromarray((a * 255).astype(np.uint8)).resize((WS, sky_h), Image.BICUBIC)) / 255.0
    # long thin wisps lower in the sky
    n2 = noise2d(lo_h, lo_w, 7, seed + 7, octaves=2, offset=cam * 0.06 / 16)
    band2 = np.exp(-((np.linspace(0, 1, lo_h) - 0.72) / 0.12) ** 2)[:, None]
    a2 = np.clip((n2 - 0.58) * 4, 0, 1) * band2 * 0.45
    a2 = np.asarray(Image.fromarray((a2 * 255).astype(np.uint8)).resize((WS, sky_h), Image.BICUBIC)) / 255.0
    a = np.clip(a + a2, 0, 0.95)
    above = np.roll(a, 10 * S, axis=0)
    above[: 10 * S] = 0
    lit = np.clip(1.0 - above * 1.4, 0, 1)
    if p["sun_dir"] < 0:
        side = np.roll(a, 6 * S, axis=1)
    else:
        side = np.roll(a, -6 * S, axis=1)
    lit = np.clip(lit * 0.7 + (1 - side) * 0.3, 0, 1)[..., None]
    colr = lerp(p["cloud_shade"], p["cloud_lit"], lit)
    a3 = a[..., None]
    img[:sky_h] = img[:sky_h] * (1 - a3) + colr * a3


def fill_below(img, ys, colour, y_cap=None):
    """Fill everything below the heightline ys (screen px, len WS) with colour."""
    yy = np.arange(HS)[:, None]
    line = (np.asarray(ys) * S)[None, :]
    mask = (yy >= line).astype(float)
    # 1.5 px anti-aliased edge
    edge = np.clip((yy - line) / 1.5 + 0.5, 0, 1)
    mask = np.minimum(mask + edge * (yy >= line - 2), 1)
    if y_cap is not None:
        mask = mask * (yy < y_cap * S)
    m = mask[..., None]
    img[:] = img * (1 - m) + np.asarray(colour) * m


def paint_far_hills(img, p, cam):
    """Three hill layers; the farthest is the haziest (colour already carries the atmosphere)."""
    far_mid = lerp(p["far1"], p["far2"], 0.5)
    layers = [(442, 74, 21, 0.10, lerp(p["far1"], p["sky_low"], 0.25)),
              (456, 48, 22, 0.16, far_mid),
              (468, 30, 23, 0.22, p["far2"])]
    for base, amp, seed, par, colr in layers:
        h = base - noise1d(WS, 460 * S, seed, octaves=3, offset=cam * par * S) * amp
        fill_below(img, h, colr)


# ----------------------------------------------------------------------------- PIL helpers
def P(pts):
    return [(x * S, y * S) for x, y in pts]


def poly(d, pts, fill, outline=None):
    d.polygon(P(pts), fill=fill, outline=outline)


def line(d, pts, fill, w=1.0):
    d.line(P(pts), fill=fill, width=max(1, int(round(w * S))))


def rect(d, x0, y0, x1, y1, fill, outline=None):
    d.rectangle([x0 * S, y0 * S, x1 * S, y1 * S], fill=fill, outline=outline)


def ellipse(d, x0, y0, x1, y1, fill):
    d.ellipse([x0 * S, y0 * S, x1 * S, y1 * S], fill=fill)


def shaded(base, lit, k_lit=1.18, k_dark=0.82):
    return col(base, k_lit) if lit else col(base, k_dark)


# ----------------------------------------------------------------------------- mid layers (PIL)
def draw_forest(d, p, cam):
    rng = np.random.RandomState(31)
    ridge = 472 - noise1d(WS, 500, 41, octaves=2, offset=cam * 0.35 * S) * 16
    # back row (hazier), front row (darker)
    for row, (colr, step, hmin, hmax, dy) in enumerate((
            (p["forest_back"], 13, 18, 30, -6), (p["forest"], 15, 22, 40, 4))):
        x = -20 + rng.uniform(0, step)
        while x < W + 20:
            xi = int(min(max(x * S, 0), WS - 1))
            base = ridge[xi] + dy + rng.uniform(-3, 3)
            h = rng.uniform(hmin, hmax)
            w = h * rng.uniform(0.45, 0.7)
            k = rng.uniform(0.92, 1.08)
            c = col(colr, k)
            # angular conifer / broadleaf mix
            if rng.rand() < 0.6:
                poly(d, [(x, base - h), (x - w / 2, base), (x + w / 2, base)], c)
                poly(d, [(x, base - h * 0.62), (x - w * 0.36, base - h * 0.2), (x + w * 0.36, base - h * 0.2)],
                     col(colr, k * (1.1 if p["sun_dir"] > 0 else 1.1)))
            else:
                poly(d, [(x - w * 0.5, base - h * 0.45), (x - w * 0.25, base - h), (x + w * 0.3, base - h * 0.95),
                         (x + w * 0.55, base - h * 0.4), (x + w * 0.2, base), (x - w * 0.2, base)], c)
                # lit cap
                lit_pts = [(x - w * 0.25, base - h), (x + w * 0.3, base - h * 0.95),
                           (x + w * 0.1, base - h * 0.7), (x - w * 0.15, base - h * 0.72)]
                poly(d, lit_pts, col(colr, k * 1.15))
            x += step * rng.uniform(0.7, 1.3)
    # forest floor band
    d.polygon(P([(0, 0), (0, 0)]), fill=None)


def draw_plain(img, p, cam):
    """The receding meadow between the forest base and the near ground: numpy gradient + hedgerows."""
    yy = np.arange(HS)[:, None, None] / S
    top, low = 468, GROUND_Y - 6
    t = np.clip((yy - top) / (low - top), 0, 1)
    colr = lerp(p["plain_top"], p["plain_low"], t)
    band = ((yy >= top) & (yy <= low + 14)).astype(float)
    band = band[..., None] if band.ndim == 2 else band
    img[:] = img * (1 - band) + colr * band
    # subtle field texture
    n = noise2d(HS // 4, WS // 4, 40, 51, octaves=2, offset=cam * 0.5 / 4)
    n = np.asarray(Image.fromarray((n * 255).astype(np.uint8)).resize((WS, HS), Image.BILINEAR)) / 255.0
    tex = ((n - 0.5) * 14)[..., None] * band
    img[:] = np.clip(img + tex, 0, 255)


def draw_hedgerows(d, p, cam):
    rng = np.random.RandomState(61)
    for i in range(7):
        y = 478 + i * 12 + rng.uniform(-3, 3)
        x0 = rng.uniform(-100, W)
        length = rng.uniform(90, 320)
        depth = (y - 470) / 96.0
        c = col(lerp(p["forest_back"], p["grass_dark"], depth), 0.95)
        line(d, [(x0, y), (x0 + length, y + rng.uniform(-1, 1))], c, 1.5 + depth * 2)


def river_points(p, cam):
    """Winding river from the forest base down to the near channel (screen coords)."""
    rx = river_x(p["kind"]) - cam
    pts = []
    n = 14
    for i in range(n + 1):
        t = i / n
        y = 470 + (GROUND_Y - 470) * (t ** 1.25)
        wob = math.sin(t * 9.0 + 1.3) * 60 * (1 - t) ** 0.8 + math.sin(t * 4.0) * 30 * (1 - t)
        x = rx + wob + (1 - t) * 40
        w = 5 + (RIVER_W - 5) * (t ** 1.6)
        pts.append((x, y, w))
    return pts


def draw_river(d, p, cam):
    pts = river_points(p, cam)
    for i in range(len(pts) - 1):
        x0, y0, w0 = pts[i]
        x1, y1, w1 = pts[i + 1]
        t = i / (len(pts) - 1)
        c = col(lerp(p["water_far"], p["water"], t ** 0.8))
        poly(d, [(x0 - w0 / 2, y0), (x1 - w1 / 2, y1 + 1), (x1 + w1 / 2, y1 + 1), (x0 + w0 / 2, y0)], c)
        # bank highlight (lit side)
        bank = col(p["grass_lit"], 0.9)
        if p["sun_dir"] > 0:
            line(d, [(x0 + w0 / 2, y0), (x1 + w1 / 2, y1)], bank, 1.0 + t)
        else:
            line(d, [(x0 - w0 / 2, y0), (x1 - w1 / 2, y1)], bank, 1.0 + t)
    # ripples on the near half
    rng = np.random.RandomState(71)
    for i in range(6, len(pts) - 1):
        x0, y0, w0 = pts[i]
        for _ in range(3):
            ry = y0 + rng.uniform(0, 6)
            rx = x0 + rng.uniform(-w0 * 0.4, w0 * 0.4)
            line(d, [(rx - w0 * 0.12, ry), (rx + w0 * 0.12, ry)], col(p["ripple"]), 1.0)


def draw_ground(d, p, cam, path=None):
    """Near meadow: grass top, soil cross-section below, river channel with water."""
    xs = np.arange(-4, W + 5, 4)
    gy = ground_y(xs + cam)
    rx = river_x(p["kind"]) - cam
    half = RIVER_W / 2
    # soil body
    soil_pts = [(x, y) for x, y in zip(xs, gy)] + [(W + 4, H), (-4, H)]
    poly(d, soil_pts, col(p["soil"]))
    # darker soil deeper down
    deep = [(x, y + 26) for x, y in zip(xs, gy)] + [(W + 4, H), (-4, H)]
    poly(d, deep, col(p["soil_dark"]))
    # grass cap (thick band) then lit edge
    cap = [(x, y) for x, y in zip(xs, gy)] + [(x, y + 12) for x, y in zip(xs[::-1], gy[::-1])]
    poly(d, cap, col(p["grass"]))
    edge = [(x, y) for x, y in zip(xs, gy)] + [(x, y + 3) for x, y in zip(xs[::-1], gy[::-1])]
    poly(d, edge, col(p["grass_lit"], 0.95))
    # path (chat-worn) along the village
    if path:
        x0, x1 = path
        pth = [(x, ground_y(np.array([x + cam]))[0] + 2) for x in range(int(x0), int(x1), 8)]
        pth += [(x, ground_y(np.array([x + cam]))[0] + 7) for x in range(int(x1), int(x0), -8)]
        poly(d, pth, col((196, 168, 120)))
    # river channel in cross-section: sloping soil banks down to a stony bed, water part-way up
    gl = ground_y(np.array([rx - half + cam]))[0]
    gr = ground_y(np.array([rx + half + cam]))[0]
    bed_y = GROUND_Y + 58
    bed_half = 22
    wtop = GROUND_Y + 16
    # channel cut (dark soil walls)
    poly(d, [(rx - half, gl), (rx - bed_half, bed_y), (rx + bed_half, bed_y), (rx + half, gr)], col(p["soil_dark"]))
    # water: three depth bands, lighter at the surface
    def wx(y):  # channel half-width at depth y (linear bank)
        t = (y - GROUND_Y) / (bed_y - GROUND_Y)
        return half + (bed_half - half) * t
    bands = [(wtop, wtop + 12, 1.0), (wtop + 12, wtop + 26, 0.82), (wtop + 26, bed_y, 0.66)]
    for y0, y1, k in bands:
        poly(d, [(rx - wx(y0), y0), (rx + wx(y0), y0), (rx + wx(y1), y1), (rx - wx(y1), y1)], col(p["water"], k))
    # surface highlight + ripples
    line(d, [(rx - wx(wtop), wtop), (rx + wx(wtop), wtop)], col(p["ripple"]), 1.5)
    rng = np.random.RandomState(81)
    for i in range(7):
        ry = wtop + 5 + i * 6 + rng.uniform(-1, 1)
        rxx = rx + rng.uniform(-wx(ry) * 0.6, wx(ry) * 0.6)
        line(d, [(rxx - 9, ry), (rxx + 9, ry)], col(p["ripple"], 0.9), 1.0)
    # bed stones
    for i in range(6):
        sx = rx - bed_half + 4 + i * 7.5 + rng.uniform(-1, 1)
        ellipse(d, sx - 4, bed_y - 6, sx + 4, bed_y - 1, col((120, 120, 118)))
    # grass lips on both banks
    poly(d, [(rx - half - 2, gl), (rx - wx(wtop) + 2, wtop), (rx - wx(wtop) - 3, wtop + 2), (rx - half - 2, gl + 4)],
         col(p["grass_dark"]))
    poly(d, [(rx + half + 2, gr), (rx + wx(wtop) - 2, wtop), (rx + wx(wtop) + 3, wtop + 2), (rx + half + 2, gr + 4)],
         col(p["grass_dark"]))
    return rx


def draw_stones(d, p, rx):
    """A natural ford: stepping stones (frame A, before chat raised a bridge)."""
    rng = np.random.RandomState(91)
    for i in range(4):
        x = rx - RIVER_W / 2 + 20 + i * 18 + rng.uniform(-3, 3)
        y = GROUND_Y + 20 + rng.uniform(-2, 2)
        poly(d, [(x - 8, y + 4), (x - 5, y - 2), (x + 6, y - 3), (x + 9, y + 3), (x + 4, y + 6), (x - 5, y + 6)],
             col((150, 146, 138)))
        poly(d, [(x - 5, y - 2), (x + 6, y - 3), (x + 3, y), (x - 3, y)], col((196, 190, 176)))


def draw_bridge(d, p, rx):
    half = RIVER_W / 2 + 14
    timber, timber_d, timber_l = (176, 122, 72), (120, 82, 48), (214, 164, 104)
    y0 = GROUND_Y - 2
    n = 12
    pts_top, pts_bot = [], []
    for i in range(n + 1):
        t = i / n
        x = rx - half + t * 2 * half
        y = y0 - math.sin(t * math.pi) * 10
        pts_top.append((x, y))
        pts_bot.append((x, y + 9))
    # piers into the water (behind the deck)
    for x in (rx - half + 24, rx + half - 24):
        rect(d, x - 4, y0 + 4, x + 4, GROUND_Y + 44, col(timber_d))
    poly(d, pts_top + pts_bot[::-1], col(timber))
    # plank lines
    for i in range(1, n):
        x, y = pts_top[i]
        line(d, [(x, y), (x, y + 9)], col(timber_d), 1.0)
    # top lit edge
    line(d, pts_top, col(timber_l), 1.5)
    # railings: posts every third plank, two rails
    for i in range(0, n + 1, 3):
        x, y = pts_top[i]
        rect(d, x - 2, y - 26, x + 2, y, col(timber_d))
        rect(d, x - 2, y - 26, x - 0.5, y, col(timber_l))
    for dy in (25, 13):
        rail = [(x, y - dy) for x, y in pts_top]
        line(d, rail, col(timber), 2.5)
        line(d, [(x, y - 1) for x, y in rail], col(timber_l), 0.8)


def draw_grass(d, p, cam, seed, exclude=()):
    rng = np.random.RandomState(seed)
    n = 1500
    wind = p["wind"] * p["sun_dir"] * -1  # blows away from the sun, one direction
    gust = noise1d(W + 8, 180, seed + 1, octaves=2, offset=cam)
    rx = river_x(p["kind"]) - cam
    for _ in range(n):
        x = rng.uniform(-4, W + 4)
        if abs(x - rx) < RIVER_W / 2 + 4:
            continue
        skip = False
        for ex0, ex1 in exclude:
            if ex0 < x < ex1:
                skip = True
                break
        if skip:
            continue
        gy = ground_y(np.array([x + cam]))[0]
        h = rng.uniform(6, 16)
        g = gust[int(min(max(x, 0), W + 7))]
        bend = (wind + (g - 0.5) * 0.5) * h
        c = [p["grass_dark"], p["grass"], p["grass_lit"]][rng.choice(3, p=[0.35, 0.4, 0.25])]
        c = col(c, rng.uniform(0.9, 1.1))
        mid = (x + bend * 0.35, gy - h * 0.55)
        tip = (x + bend, gy - h)
        line(d, [(x, gy + 1), mid, tip], c, 1.0)
    # flowers
    for _ in range(70):
        x = rng.uniform(0, W)
        if abs(x - rx) < RIVER_W / 2 + 6:
            continue
        if any(ex0 < x < ex1 for ex0, ex1 in exclude):
            continue
        gy = ground_y(np.array([x + cam]))[0]
        c = [(255, 220, 90), (255, 160, 120), (236, 236, 250), (210, 130, 200)][rng.randint(4)]
        ellipse(d, x - 2, gy - 8 - rng.uniform(0, 4), x + 2, gy - 4, col(c))


def draw_tree(d, p, x, base, scale=1.0):
    """A big angular broadleaf: trunk + 3 stacked faceted canopy slabs, lit on the sun side."""
    sd = p["sun_dir"]
    trunk, trunk_l = (104, 74, 50), (140, 102, 70)
    tw, th = 24 * scale, 74 * scale
    poly(d, [(x - tw / 2, base), (x - tw / 2 + 4, base - th), (x + tw / 2 - 4, base - th), (x + tw / 2, base)],
         col(trunk))
    # lit trunk edge
    poly(d, [(x + sd * (tw / 2 - 4), base - th), (x + sd * tw / 2, base), (x + sd * (tw / 2 - 6), base),
             (x + sd * (tw / 2 - 8), base - th)], col(trunk_l))
    # roots
    poly(d, [(x - tw / 2 - 12, base), (x - tw / 2, base - 8), (x + tw / 2, base - 8), (x + tw / 2 + 12, base)],
         col(trunk, 0.9))
    greens = [(66, 118, 70), (86, 146, 78), (120, 176, 90)]
    if p["kind"] == "sunset":
        greens = [(72, 104, 68), (104, 134, 74), (176, 160, 84)]
    layers = [(190, 58, 0), (150, 52, 42), (100, 46, 84)]
    for (w, h, dy), g in zip(layers, greens):
        w, h, dy = w * scale, h * scale, dy * scale
        cy = base - th + 10 - dy
        pts = [(x - w / 2, cy), (x - w * 0.35, cy - h * 0.8), (x - w * 0.1, cy - h), (x + w * 0.25, cy - h * 0.92),
               (x + w / 2, cy - h * 0.35), (x + w * 0.3, cy + h * 0.15), (x - w * 0.25, cy + h * 0.2)]
        poly(d, pts, col(g))
        # lit facet on the sun side
        lit = col(g, 1.2)
        if sd > 0:
            poly(d, [(x + w * 0.25, cy - h * 0.92), (x + w / 2, cy - h * 0.35), (x + w * 0.2, cy - h * 0.3),
                     (x + w * 0.05, cy - h * 0.7)], lit)
        else:
            poly(d, [(x - w * 0.35, cy - h * 0.8), (x - w * 0.1, cy - h), (x - w * 0.05, cy - h * 0.65),
                     (x - w * 0.3, cy - h * 0.35)], lit)


def draw_shadow(d, p, x, base, w, h=6):
    off = -p["sun_dir"] * w * 0.35
    ov = Image.new("RGBA", d._image.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.ellipse([(x - w / 2 + off) * S, (base - h / 2) * S, (x + w / 2 + off) * S, (base + h / 2) * S],
               fill=(40, 30, 20, 70))
    d._image.paste(Image.alpha_composite(d._image.convert("RGBA"), ov).convert("RGB"))


def draw_hut(d, p, x, base, w, h, roof_col, wall_col, lit_window, chimney=True, roof_kind=0):
    sd = p["sun_dir"]
    draw_shadow(d, p, x, base, w * 1.3, 8)
    wall_l = col(wall_col, 1.15)
    wall_d = col(wall_col, 0.82)
    # body
    rect(d, x - w / 2, base - h, x + w / 2, base, col(wall_col))
    # lit wall side strip
    if sd > 0:
        rect(d, x + w / 2 - 6, base - h, x + w / 2, base, wall_l)
    else:
        rect(d, x - w / 2, base - h, x - w / 2 + 6, base, wall_l)
    # timber frame lines
    for fx in (x - w / 2 + 2, x + w / 2 - 2):
        rect(d, fx - 1, base - h, fx + 1, base, wall_d)
    rect(d, x - w / 2, base - h * 0.55, x + w / 2, base - h * 0.55 + 2, wall_d)
    # door
    dw, dh = w * 0.22, h * 0.6
    dx = x + sd * w * 0.18
    rect(d, dx - dw / 2, base - dh, dx + dw / 2, base, col((70, 48, 34)))
    rect(d, dx - dw / 2 + 2, base - dh + 2, dx + dw / 2 - 2, base, col((96, 66, 44)))
    # window
    wx = x - sd * w * 0.2
    wy = base - h * 0.62
    ww = w * 0.2
    wc = (255, 214, 120) if lit_window else (150, 190, 214)
    rect(d, wx - ww / 2, wy - ww / 2, wx + ww / 2, wy + ww / 2, col((60, 44, 34)))
    rect(d, wx - ww / 2 + 2, wy - ww / 2 + 2, wx + ww / 2 - 2, wy + ww / 2 - 2, col(wc))
    line(d, [(wx, wy - ww / 2 + 2), (wx, wy + ww / 2 - 2)], col((60, 44, 34)), 1.0)
    # roof
    ry = base - h
    over = 8
    peak = h * 0.62
    if roof_kind == 0:   # gable
        pts = [(x - w / 2 - over, ry + 2), (x, ry - peak), (x + w / 2 + over, ry + 2)]
        poly(d, pts, col(roof_col))
        # lit half
        if sd > 0:
            poly(d, [(x, ry - peak), (x + w / 2 + over, ry + 2), (x + w * 0.1, ry + 2)], col(roof_col, 1.18))
        else:
            poly(d, [(x, ry - peak), (x - w / 2 - over, ry + 2), (x - w * 0.1, ry + 2)], col(roof_col, 1.18))
        # thatch lines
        for i in range(1, 4):
            t = i / 4
            line(d, [(x - (w / 2 + over) * t, ry + 2 - peak * (1 - t)), (x + (w / 2 + over) * t, ry + 2 - peak * (1 - t))],
                 col(roof_col, 0.8), 1.0)
        roof_top = ry - peak
    else:                # lean / hip roof (flat-topped)
        pts = [(x - w / 2 - over, ry + 2), (x - w * 0.22, ry - peak * 0.7), (x + w * 0.22, ry - peak * 0.7),
               (x + w / 2 + over, ry + 2)]
        poly(d, pts, col(roof_col))
        if sd > 0:
            poly(d, [(x + w * 0.22, ry - peak * 0.7), (x + w / 2 + over, ry + 2), (x + w * 0.1, ry + 2),
                     (x - w * 0.05, ry - peak * 0.7)], col(roof_col, 1.18))
        else:
            poly(d, [(x - w * 0.22, ry - peak * 0.7), (x - w / 2 - over, ry + 2), (x - w * 0.1, ry + 2),
                     (x + w * 0.05, ry - peak * 0.7)], col(roof_col, 1.18))
        roof_top = ry - peak * 0.7
    # ridge line
    line(d, [(x - w / 2 - over, ry + 2), (x + w / 2 + over, ry + 2)], col(roof_col, 0.7), 1.0)
    if chimney:
        cx = x - sd * w * 0.28
        rect(d, cx - 4, roof_top + 6, cx + 4, ry - peak * 0.3, col((120, 100, 96)))
        rect(d, cx - 5, roof_top + 4, cx + 5, roof_top + 8, col((150, 130, 124)))
        # smoke drifting with the wind
        ov = Image.new("RGBA", d._image.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        wind = -sd * p["wind"]
        for i in range(5):
            sy = roof_top - 6 - i * 11
            sx = cx + wind * (i * i) * 3.2 + math.sin(i * 1.7) * 3
            r = 5 + i * 2.2
            od.ellipse([(sx - r) * S, (sy - r) * S, (sx + r) * S, (sy + r) * S],
                       fill=(240, 236, 232, int(110 - i * 18)))
        d._image.paste(Image.alpha_composite(d._image.convert("RGBA"), ov).convert("RGB"))
    return roof_top


def draw_garden(d, p, x0, x1, base, kind):
    fence, fence_l = (150, 112, 70), (200, 160, 104)
    # fence
    for fx in np.arange(x0, x1 + 1, 14):
        rect(d, fx - 1.5, base - 16, fx + 1.5, base, col(fence))
        rect(d, fx - 1.5, base - 16, fx, base, col(fence_l))
    line(d, [(x0, base - 12), (x1, base - 12)], col(fence), 2.0)
    line(d, [(x0, base - 5), (x1, base - 5)], col(fence), 2.0)
    rng = np.random.RandomState(int(x0))
    if kind == "wheat":
        for fx in np.arange(x0 + 6, x1 - 4, 5):
            h = rng.uniform(16, 24)
            bend = -p["sun_dir"] * p["wind"] * h * 0.8
            line(d, [(fx, base), (fx + bend * 0.4, base - h * 0.6), (fx + bend, base - h)], col((214, 176, 84)), 1.2)
            ellipse(d, fx + bend - 2, base - h - 5, fx + bend + 2, base - h + 2, col((240, 200, 100)))
    elif kind == "sunflower":
        for fx in np.arange(x0 + 8, x1 - 6, 13):
            h = rng.uniform(26, 38)
            bend = -p["sun_dir"] * p["wind"] * h * 0.25
            line(d, [(fx, base), (fx + bend, base - h)], col((80, 130, 60)), 2.0)
            poly(d, [(fx + bend - 9, base - h), (fx + bend, base - h - 9), (fx + bend + 9, base - h),
                     (fx + bend, base - h + 9)], col((250, 200, 60)))
            ellipse(d, fx + bend - 4, base - h - 4, fx + bend + 4, base - h + 4, col((110, 70, 40)))
    else:   # veg rows
        for fx in np.arange(x0 + 6, x1 - 4, 9):
            h = rng.uniform(6, 12)
            poly(d, [(fx - 5, base), (fx, base - h), (fx + 5, base)], col((96, 150, 80)))
            poly(d, [(fx - 3, base), (fx, base - h * 0.7), (fx + 3, base)], col((130, 180, 96)))


def draw_festival_poles(d, p, cx, base, names):
    pole = (120, 88, 56)
    xs = [cx - 120, cx, cx + 120]
    tops = [base - 60, base - 84, base - 60]
    for x, top in zip(xs, tops):
        rect(d, x - 2.5, top, x + 2.5, base, col(pole))
        poly(d, [(x - 6, top), (x, top - 10), (x + 6, top)], col((214, 90, 70)))
    # lantern strings (catenary) with lanterns in settlers' colours
    ci = 0
    for (xa, ya), (xb, yb) in (((xs[0], tops[0]), (xs[1], tops[1])), ((xs[1], tops[1]), (xs[2], tops[2]))):
        pts = []
        n = 16
        for i in range(n + 1):
            t = i / n
            x = xa + (xb - xa) * t
            y = ya + (yb - ya) * t + math.sin(t * math.pi) * 14
            pts.append((x, y))
        line(d, pts, col((70, 50, 40)), 1.0)
        for i in range(2, n - 1, 2):
            x, y = pts[i]
            c = lantern_colour(names[ci % len(names)])
            ci += 1
            rect(d, x - 4, y + 2, x + 4, y + 12, col(c))
            rect(d, x - 2, y + 4, x + 2, y + 10, col(c, 1.35))
    # fire bowl at the centre
    bx, by = cx, base
    poly(d, [(bx - 16, by - 10), (bx + 16, by - 10), (bx + 10, by), (bx - 10, by)], col((120, 112, 104)))
    poly(d, [(bx - 12, by - 10), (bx - 4, by - 30), (bx, by - 18), (bx + 5, by - 34), (bx + 12, by - 10)],
         col((250, 140, 50)))
    poly(d, [(bx - 6, by - 10), (bx - 2, by - 22), (bx + 2, by - 16), (bx + 6, by - 10)], col((255, 220, 110)))


def lantern_colour(name):
    if pips is not None:
        hx = pips.colour_hex(name.lower(), None)
        return tuple(int(hx[i:i + 2], 16) for i in (1, 3, 5))
    h = abs(hash(name)) % 6
    return [(255, 120, 120), (120, 200, 255), (255, 200, 90), (150, 240, 150), (220, 150, 255), (255, 170, 210)][h]


# ----------------------------------------------------------------------------- creatures
def creature_sprite(name, frame, facing=1, tier=2):
    """(rgb, mask) from pips.py at sim scale; plain angular fallback if unavailable."""
    if pips is not None:
        g, salt = pips.resolve_genome(name.lower())
        rgb, mask = pips.sprite(name.lower(), salt, tier, frame, preset=None, facing=facing)
        return rgb, mask
    c = np.array(lantern_colour(name), np.uint8)
    rgb = np.zeros((11, 12, 3), np.uint8)
    mask = np.zeros((11, 12), bool)
    for y in range(3, 10):
        x0 = 1 + (y - 3) // 2
        rgb[y, x0:12 - x0] = c
        mask[y, x0:12 - x0] = True
    return rgb, mask


def place_creature(base_img, name, x, base, frame="idle0", facing=1, tier=2, p=None):
    """Paste a 4x-scaled creature with its feet on `base`. Returns (top_y, w) in screen px."""
    rgb, mask = creature_sprite(name, frame, facing, tier)
    h, w = mask.shape
    k = CREATURE_K * S
    im = Image.fromarray(np.dstack([rgb, (mask * 255).astype(np.uint8)]))
    im = im.resize((w * k, h * k), Image.NEAREST)
    sw, sh = w * CREATURE_K, h * CREATURE_K
    x0 = int(round((x - sw / 2) * S))
    y0 = int(round((base - sh) * S))
    if p is not None:
        d = ImageDraw.Draw(base_img)
        draw_shadow(d, p, x, base, sw * 0.9, 5)
    base_img.paste(im, (x0, y0), im)
    first_row = int(np.argmax(mask.any(axis=1)))  # visible top (asleep / sit frames are shorter)
    return base - (h - first_row) * CREATURE_K, sw


# ----------------------------------------------------------------------------- post (numpy)
def add_glow(img, cx, cy, radius, colour, strength):
    yy, xx = np.mgrid[0:HS, 0:WS]
    d = np.sqrt((xx - cx * S) ** 2 + (yy - cy * S) ** 2) / S
    g = np.exp(-(d / radius) ** 2) * strength
    img[:] = np.clip(img + g[..., None] * (np.asarray(colour) - img * 0.4), 0, 255)


def add_mist(img, p):
    if p["mist"] <= 0:
        return
    yy = np.arange(HS)[:, None, None] / S
    band = np.exp(-((yy - 548) / 22.0) ** 2) * p["mist"]
    n = noise2d(HS // 4, WS // 4, 60, 101, octaves=2)
    n = np.asarray(Image.fromarray((n * 255).astype(np.uint8)).resize((WS, HS), Image.BILINEAR)) / 255.0
    band = band * (0.5 + n[..., None])
    img[:] = img * (1 - band) + np.asarray((255, 240, 224)) * band


# ----------------------------------------------------------------------------- HUD (1x)
def text_w(d, s, f):
    return d.textlength(s, font=f)


def shadow_text(d, xy, s, f, fill, shadow=(30, 22, 20), stroke=0):
    x, y = xy
    if stroke:
        d.text((x, y), s, font=f, fill=fill, stroke_width=stroke, stroke_fill=shadow)
    else:
        d.text((x + 1, y + 1), s, font=f, fill=shadow)
        d.text((x, y), s, font=f, fill=fill)


def fit(d, s, f, maxw):
    """Truncate s with an ellipsis so it fits maxw px in font f."""
    if text_w(d, s, f) <= maxw:
        return s
    while s and text_w(d, s + "…", f) > maxw:
        s = s[:-1]
    return s.rstrip() + "…"


STRIP_Y = 634


def draw_hud(img, p, hud):
    """Header (hook) + countdown + position bar + translucent bottom strip + caption bar."""
    base = img.convert("RGBA")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    # header band
    od.rectangle([0, 0, W, 66], fill=(38, 28, 40, 168))
    od.rectangle([0, 66, W, 72], fill=(60, 48, 58, 220))
    od.rectangle([0, 66, int(W * hud["countdown"]), 72], fill=(248, 190, 82, 255))
    # position bar (camera along the long world) with one dot per settled plot
    od.rounded_rectangle([16, 79, W - 16, 85], radius=3, fill=(20, 16, 22, 130))
    for frac, c in hud.get("plots", []):
        px = 16 + int((W - 32) * frac)
        od.rectangle([px - 1, 80, px + 1, 84], fill=c + (230,))
    vx0 = 16 + int((W - 32) * hud["cam_frac"])
    vw = max(16, int((W - 32) * hud["view_frac"]))
    od.rounded_rectangle([vx0, 76, vx0 + vw, 88], radius=4, fill=(255, 236, 190, 235))
    # bottom strip
    od.rectangle([0, STRIP_Y, W, 692], fill=(38, 28, 40, 165))
    for x in (420, 840):
        od.rectangle([x, STRIP_Y + 8, x + 1, 686], fill=(255, 240, 220, 60))
    od.rectangle([0, 692, W, H], fill=(24, 18, 24, 225))
    img = Image.alpha_composite(base, ov).convert("RGB")
    d = ImageDraw.Draw(img)
    cream = (250, 244, 232)
    warm = (255, 214, 140)
    dim = (214, 200, 190)
    # header left
    shadow_text(d, (16, 20), "atleastonce · SETTLEMENT", font("hn", 22), cream)
    # header centre: the hook
    x = 312
    ab56, ab40, m24 = font("ab", 56), font("ab", 40), font("menlo", 24)
    d.text((x, -2), hud["settled"], font=ab56, fill=cream)
    x += text_w(d, hud["settled"], ab56) + 10
    d.text((x, 30), "SETTLED", font=m24, fill=warm)
    x += text_w(d, "SETTLED", m24) + 14
    d.text((x, 30), "·", font=m24, fill=dim)
    x += 24
    if hud["awake"] == "0":
        d.text((x, 12), "NOBODY AWAKE", font=ab40, fill=dim)
        x += text_w(d, "NOBODY AWAKE", ab40) + 22
    else:
        d.text((x, -2), hud["awake"], font=ab56, fill=cream)
        x += text_w(d, hud["awake"], ab56) + 10
        d.text((x, 30), "AWAKE", font=m24, fill=warm)
        x += text_w(d, "AWAKE", m24) + 22
    d.text((x, 12), "NEXT EVENT", font=font("menlo", 20), fill=dim)
    d.text((x, 34), hud["next"], font=m24, fill=cream)
    # header right
    m22 = font("menlo", 22)
    d.ellipse([W - 250, 22, W - 236, 36], fill=(236, 60, 60))
    d.text((W - 226, 16), "LIVE", font=m22, fill=cream)
    d.text((W - 160, 16), hud["watching"], font=m22, fill=cream)
    d.text((W - 96, 40), "v0.6.0", font=font("menlo", 20), fill=dim)
    # position bar label
    m20 = font("menlo", 20)
    lab = hud["cam_label"]
    shadow_text(d, (W - 16 - text_w(d, lab, m20), 88), lab, m20, cream)
    # plank line (top-left of the world)
    shadow_text(d, (16, 92), hud["plank"], font("hn", 22), cream)
    # bottom strip columns (each line truncated to its column)
    colw = 388
    for i, (c0, lines) in enumerate(((16, hud["colony"]), (436, hud["keeper"]), (856, hud["chat"]))):
        for j, ln in enumerate(lines[:2]):
            y = STRIP_Y + 5 + j * 24
            if isinstance(ln, tuple):  # (name, colour, message)
                name, ncol, msg = ln
                d.text((c0, y), name, font=m20, fill=ncol)
                nw = text_w(d, name + " ", m20)
                d.text((c0 + nw, y), fit(d, msg, m20, colw - nw), font=m20, fill=cream)
            else:
                f = font("hn", 22) if j == 0 else m20
                d.text((c0, y if j else y - 1), fit(d, ln, f, colw), font=f, fill=cream if j == 0 else dim)
    # colony progress bar
    if hud.get("colony_frac") is not None:
        d.rectangle([16, 686, 16 + colw, 689], fill=(90, 70, 70))
        d.rectangle([16, 686, 16 + int(colw * hud["colony_frac"]), 689], fill=(248, 190, 82))
    # caption bar (very bottom)
    d.text((16, 695), "concept render · names are examples", font=m20, fill=(230, 210, 190))
    right = "no camera, no mic, no fake viewers · every creature is a real person"
    d.text((W - 16 - text_w(d, right, m20), 695), right, font=m20, fill=(200, 184, 176))
    return img


def label(d, x, top, name, colour, y=None):
    f = font("menlo", 20)
    s = "@" + name
    w = text_w(d, s, f)
    ly = top - 26 if y is None else y
    d.text((x - w / 2, ly), s, font=f, fill=colour, stroke_width=2, stroke_fill=(36, 26, 24))
    return ly


def place_labels(d, items):
    """items: [(x, top, name, colour)]. Labels that would overlap a neighbour step up a row (the
    product rule above 40 awake is label-on-speak; below it, two rows suffice). Returns {name: label_y}."""
    f = font("menlo", 20)
    placed, out = [], {}
    for x, top, name, colour in sorted(items, key=lambda t: t[0]):
        w = text_w(d, "@" + name, f) + 8
        x0, x1 = x - w / 2, x + w / 2
        y = top - 26
        for _ in range(3):
            clash = any(px0 < x1 and px1 > x0 and abs(py - y) < 22 for px0, px1, py in placed)
            if not clash:
                break
            y -= 24
        placed.append((x0, x1, y))
        out[name] = label(d, x, top, name, colour, y=y)
    return out


def bubble(d, x, top, text, tail_dx=0):
    f = font("menlo", 22)
    maxw = 408 - 24
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if text_w(d, t, f) > maxw and cur:
            lines.append(cur)
            cur = wd
        else:
            cur = t
    if cur:
        lines.append(cur)
    lines = lines[:3]
    w = max(text_w(d, ln, f) for ln in lines) + 24
    h = 26 * len(lines) + 14
    x0 = int(min(max(x - w / 2, 8), W - 8 - w))
    y0 = int(top - 12 - h)
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=6, fill=(255, 250, 236), outline=(140, 104, 72), width=1)
    tx = int(min(max(x + tail_dx, x0 + 14), x0 + w - 14))
    d.polygon([(tx - 7, y0 + h), (tx + 7, y0 + h), (tx, y0 + h + 9)], fill=(255, 250, 236))
    d.line([(tx - 7, y0 + h), (tx, y0 + h + 9), (tx + 7, y0 + h)], fill=(140, 104, 72), width=1)
    for i, ln in enumerate(lines):
        d.text((x0 + 12, y0 + 7 + i * 26), ln, font=f, fill=(44, 34, 30))
    return y0


# ----------------------------------------------------------------------------- frames
def frame_dawn():
    cam = 2400
    p = scene_params("dawn", cam)
    img = np.zeros((HS, WS, 3), float)
    paint_sky(img, p)
    paint_sun(img, p)
    paint_clouds(img, p, 5, cam)
    paint_far_hills(img, p, cam)
    draw_plain(img, p, cam)
    pil = Image.fromarray(img.clip(0, 255).astype(np.uint8))
    d = ImageDraw.Draw(pil)
    draw_forest(d, p, cam)
    draw_hedgerows(d, p, cam)
    draw_river(d, p, cam)
    rx = draw_ground(d, p, cam)
    draw_stones(d, p, rx)
    tree_x = 400
    tree_base = ground_y(np.array([tree_x + cam]))[0] + 1
    draw_grass(d, p, cam, 201)
    draw_shadow(d, p, tree_x, tree_base, 150, 10)
    draw_tree(d, p, tree_x, tree_base, 1.0)
    # one sleeping creature under the tree, on the shaded side
    cx = tree_x - 70
    cbase = ground_y(np.array([cx + cam]))[0] + 1
    top, sw = place_creature(pil, "kaifrost", cx, cbase, frame="asleep", facing=1, p=p)
    # a few taller grass tufts in front for depth
    img = np.asarray(pil).astype(float)
    add_mist(img, p)
    pil = Image.fromarray(img.clip(0, 255).astype(np.uint8)).resize((W, H), Image.LANCZOS)
    hud = dict(
        settled="1", awake="0", next="02:41", countdown=0.9, watching="2 watching",
        cam_frac=0.31, view_frac=0.045, cam_label="camera 2.4 km · world 7.6 km · drifting east",
        plots=[(0.31 + (cx / W) * 0.045, lantern_colour("kaifrost"))],
        plank="say anything in chat. a creature hatches with your name.",
        colony=["1 settled · 4 more to the first hut", "1 asleep · night 2 for @kaifrost"],
        keeper=["keeper on duty", "next: footbridge · when 3 ask"],
        chat=["chat is quiet. say anything.", ""],
        colony_frac=0.2,
    )
    out = draw_hud(pil, p, hud)
    d = ImageDraw.Draw(out)
    place_labels(d, [(cx, top - 2, "kaifrost", lantern_colour("kaifrost"))])
    f = font("menlo", 20)
    s = "asleep · night 2 · fed by nobody yet"
    shadow_text(d, (cx - text_w(d, s, f) / 2, cbase + 8), s, f, (250, 244, 232))
    return out


def frame_busy():
    cam = 4100
    p = scene_params("sunset", cam)
    names = ["sami_dev", "Mxrbles", "luna.exe", "tomo_99", "GrapeJam", "pixelrae", "oskr", "benny_b",
             "nova_kt", "hollowfox", "kaifrost", "rzn", "dottie", "quillan"]
    img = np.zeros((HS, WS, 3), float)
    paint_sky(img, p)
    paint_moon(img, p)
    paint_sun(img, p)
    paint_clouds(img, p, 9, cam)
    paint_far_hills(img, p, cam)
    draw_plain(img, p, cam)
    pil = Image.fromarray(img.clip(0, 255).astype(np.uint8))
    d = ImageDraw.Draw(pil)
    draw_forest(d, p, cam)
    draw_hedgerows(d, p, cam)
    draw_river(d, p, cam)
    rx = draw_ground(d, p, cam, path=(180, 1180))
    gy = lambda x: ground_y(np.array([x + cam]))[0] + 1  # noqa: E731
    # settlement strip along the ground line
    # settlement strip: huts either side of an open square (fire + lantern poles), bridge at rx=900
    huts = [  # (x, w, h, roof, wall, roof_kind)
        (130, 92, 62, (196, 150, 84), (222, 196, 160), 0),
        (360, 110, 72, (150, 110, 96), (228, 206, 176), 1),
        (790, 90, 78, (170, 90, 76), (232, 214, 186), 0),
        (1110, 96, 66, (196, 150, 84), (222, 196, 160), 1),
    ]
    gardens = [(205, 295, "wheat"), (680, 735, "sunflower"), (985, 1055, "veg")]
    exclude = [(x - w / 2 - 6, x + w / 2 + 6) for x, w, *_ in huts] + [(g0 - 4, g1 + 4) for g0, g1, _ in gardens]
    tree_x = 1235
    draw_tree(d, p, tree_x, gy(tree_x), 0.8)
    draw_grass(d, p, cam, 301, exclude=exclude)
    for g0, g1, kind in gardens:
        draw_garden(d, p, g0, g1, gy((g0 + g1) / 2), kind)
    roof_tops = {}
    for x, w, h, roof, wall, rk in huts:
        roof_tops[x] = draw_hut(d, p, x, gy(x), w, h, roof, wall, lit_window=True, roof_kind=rk)
    draw_bridge(d, p, rx)
    festival_x = 570
    draw_festival_poles(d, p, festival_x, gy(festival_x), names)
    # creatures: ground line, bridge deck, rooftops
    placements = [  # (name, x, frame, facing, where, tier)
        ("sami_dev", 78, "walk0", 1, None, 3), ("Mxrbles", 230, "speak", 1, None, 2),
        ("luna.exe", 440, "idle0", 1, None, 2), ("tomo_99", 505, "wave0", 1, None, 2),
        ("GrapeJam", 640, "idle1", -1, None, 2), ("pixelrae", 725, "speak", -1, None, 2),
        ("benny_b", rx + 8, "sit0", -1, "bridge", 2), ("oskr", 985, "walk1", -1, None, 2),
        ("nova_kt", 1075, "walk0", 1, None, 1), ("hollowfox", 1168, "idle0", -1, None, 2),
        ("quillan", 1226, "walk0", -1, None, 2), ("rzn", 360, "sit0", 1, "roof", 3),
        ("dottie", 790 + 14, "sit1", -1, "roof", 2), ("kaifrost", 1110, "speak", -1, "roof", 3),
    ]
    tops = {}
    for name, x, fr, facing, where, tier in placements:
        if where == "roof":
            hx = min(roof_tops, key=lambda k: abs(k - x))
            base = roof_tops[hx] + 3
            top, sw = place_creature(pil, name, x, base, fr, facing, tier)
        elif where == "bridge":
            half = RIVER_W / 2 + 14
            base = GROUND_Y - 2 - 9 * math.sin(((x - (rx - half)) / (2 * half)) * math.pi) + 0.5
            top, sw = place_creature(pil, name, x, base, fr, facing, tier)
        else:
            top, sw = place_creature(pil, name, x, gy(x), fr, facing, tier, p=p)
        tops[name] = (x, top)
    img = np.asarray(pil).astype(float)
    add_glow(img, festival_x, gy(festival_x) - 26, 140, (255, 170, 80), 0.34)
    add_glow(img, festival_x, gy(festival_x) - 20, 42, (255, 214, 130), 0.45)
    for x, w, h, roof, wall, rk in huts:
        add_glow(img, x - p["sun_dir"] * w * 0.2, gy(x) - h * 0.62, 18, (255, 200, 110), 0.2)
    add_mist(img, p)
    pil = Image.fromarray(img.clip(0, 255).astype(np.uint8)).resize((W, H), Image.LANCZOS)
    rng = np.random.RandomState(5)
    plots = [(0.54 + (x / W) * 0.045, lantern_colour(n)) for n, (x, _) in tops.items()]
    plots += [(float(f), lantern_colour(n)) for f, n in zip(rng.uniform(0.05, 0.95, 9), names)]
    hud = dict(
        settled="14", awake="9", next="01:23", countdown=0.46, watching="31 watching",
        cam_frac=0.54, view_frac=0.045, cam_label="camera 4.1 km · world 7.6 km · following @kaifrost",
        plots=plots,
        plank="festival at the fire in 01:23 · say A B or C to pick the song",
        colony=["14 settled · 6 more to the mill", "night 4 for @sami_dev · 5 asleep"],
        keeper=["keeper on duty", "bridge raised · asked by @oskr"],
        chat=[("@Mxrbles", lantern_colour("Mxrbles"), "the bridge is DONE come look"),
              ("@luna.exe", lantern_colour("luna.exe"), "A")],
        colony_frac=0.7,
    )
    out = draw_hud(pil, p, hud)
    d = ImageDraw.Draw(out)
    ly = place_labels(d, [(x, top - 2, name, lantern_colour(name)) for name, (x, top) in tops.items()])
    # bubbles for the speakers (real chat lines live in the world, not in a side pane)
    bubble(d, tops["Mxrbles"][0] - 30, ly["Mxrbles"] - 4, "the bridge is DONE come look", 30)
    bubble(d, tops["luna.exe"][0], ly["luna.exe"] - 4, "A", 0)
    bubble(d, tops["pixelrae"][0] - 35, ly["pixelrae"] - 4, "who planted the sunflowers??", 35)
    bubble(d, tops["benny_b"][0] + 10, ly["benny_b"] - 4, "A", -10)
    bubble(d, tops["dottie"][0] - 50, ly["dottie"] - 4, "brb feeding @oskr", 50)
    bubble(d, tops["kaifrost"][0] + 40, ly["kaifrost"] - 4, "gm from the roof", -40)
    # who raised the bridge (a mark with real names)
    f = font("menlo", 20)
    s = "raised by @oskr @Mxrbles @tomo_99"
    shadow_text(d, (rx - text_w(d, s, f) / 2, GROUND_Y + 30), s, f, (250, 244, 232))
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    a = frame_dawn()
    a.save(os.path.join(OUT, "sidescroll_A_dawn_empty.png"))
    b = frame_busy()
    b.save(os.path.join(OUT, "sidescroll_B_busy.png"))
    b.resize((320, 180), Image.LANCZOS).save(os.path.join(OUT, "sidescroll_thumb_320x180.png"))
    print("ok", HN_IDX)


if __name__ == "__main__":
    main()
