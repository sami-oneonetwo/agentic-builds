"""Concept render: SETTLEMENT, isometric style. numpy + pillow only; every asset is procedural.

    ~/.local/share/kick-live/venv/bin/python docs/mockups/isometric_render.py

Writes isometric_A_dawn_empty.png, isometric_B_busy.png, isometric_thumb_320x180.png next to itself.
World geometry is drawn at 2x and downsampled (anti-aliased); text, HUD and pip sprites are drawn at 1x.
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = "/Users/sandy/Workspace/agentic-builds/kick-live"
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    from stream.world import pips as PIPS
except Exception:  # pragma: no cover
    PIPS = None

OUT = os.path.dirname(os.path.abspath(__file__))
W, H = 1280, 720
S = 2                      # supersample for world geometry
TW, TH, STEP = 48, 24, 12  # iso tile (1x): width, height, px per elevation level
OX, OY = 640, 214          # screen position of tile (i+j=0, i-j=0) at level 0
K0, K1 = 0, 46             # depth rows (back..front)
D0, D1 = -30, 30           # lateral columns
MENLO = "/System/Library/Fonts/Menlo.ttc"
HN = "/System/Library/Fonts/HelveticaNeue.ttc"
AB = "/System/Library/Fonts/Supplemental/Arial Black.ttf"

NAME_COLOURS = ["#53FC18", "#7DD3FC", "#FCD34D", "#F9A8D4", "#C4B5FD", "#FDBA74"]


# ----------------------------------------------------------------------------- helpers
def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def shade(c, k):
    return tuple(int(max(0, min(255, round(v * k)))) for v in c)


def name_hash(name):
    s = 0
    for ch in name.lower():
        s = (s * 31 + ord(ch)) & 0xFFFFFFFF
    return s


def name_colour(name):
    return hex_rgb(NAME_COLOURS[name_hash(name) % 6])


_FONT_CACHE = {}


def font(kind, size):
    key = (kind, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    if kind == "menlo":
        f = ImageFont.truetype(MENLO, size, index=0)
    elif kind == "menlo_b":
        f = ImageFont.truetype(MENLO, size, index=1)
    elif kind == "hn":
        f = None
        for idx in range(0, 14):
            try:
                cand = ImageFont.truetype(HN, size, index=idx)
            except Exception:
                break
            if "Medium" == cand.getname()[1]:
                f = cand
                break
        if f is None:
            f = ImageFont.truetype(HN, size, index=0)
    else:
        f = ImageFont.truetype(AB, size)
    _FONT_CACHE[key] = f
    return f


def text_w(draw, s, f):
    b = draw.textbbox((0, 0), s, font=f)
    return b[2] - b[0]


def fit(draw, s, f, max_w):
    """Truncate with an ellipsis so the string fits max_w (the real HUD does the same per region)."""
    if text_w(draw, s, f) <= max_w:
        return s
    while s and text_w(draw, s + "…", f) > max_w:
        s = s[:-1]
    return s.rstrip() + "…"


def text_shadow(draw, xy, s, f, fill, shadow=(30, 22, 18, 170), off=1):
    x, y = xy
    draw.text((x + off, y + off), s, font=f, fill=shadow)
    draw.text((x, y), s, font=f, fill=fill)


# ----------------------------------------------------------------------------- noise
def value_noise(shape, cell, rng):
    """Smooth value noise in [0,1]: random lattice + smoothstep bilinear interpolation."""
    h, w = shape
    gh, gw = h // cell + 3, w // cell + 3
    g = rng.random((gh, gw))
    ys = np.arange(h) / cell
    xs = np.arange(w) / cell
    y0 = np.floor(ys).astype(int)
    x0 = np.floor(xs).astype(int)
    fy = ys - y0
    fx = xs - x0
    fy = fy * fy * (3 - 2 * fy)
    fx = fx * fx * (3 - 2 * fx)
    a = g[y0][:, x0]
    b = g[y0][:, x0 + 1]
    c = g[y0 + 1][:, x0]
    d = g[y0 + 1][:, x0 + 1]
    top = a + (b - a) * fx[None, :]
    bot = c + (d - c) * fx[None, :]
    return top + (bot - top) * fy[:, None]


def fbm(shape, cells, weights, rng):
    out = np.zeros(shape)
    tot = 0.0
    for c, wgt in zip(cells, weights):
        out += wgt * value_noise(shape, c, rng)
        tot += wgt
    return out / tot


# ----------------------------------------------------------------------------- terrain
class Terrain:
    """Tile grid in (v=depth k, u=lateral d) space, K0..K1 x D0..D1. Only tiles with (k+d) even exist."""

    def __init__(self, seed=7):
        rng = np.random.default_rng(seed)
        nk, nd = K1 - K0 + 1, D1 - D0 + 1
        self.nk, self.nd = nk, nd
        v = np.arange(K0, K1 + 1)[:, None].astype(float)
        u = np.arange(D0, D1 + 1)[None, :].astype(float)
        n1 = fbm((nk, nd), (9, 4, 2), (1.0, 0.5, 0.2), rng)
        n2 = fbm((nk, nd), (7, 3), (1.0, 0.4), np.random.default_rng(seed + 11))
        elev = 1.4 + 2.4 * (n1 - 0.45)
        elev += 2.6 / (1 + np.exp((v - 8) / 2.4))                                  # back ridge (wooded hills)
        elev += 3.0 * np.exp(-((u - 17) ** 2 / 120 + (v - 20) ** 2 / 130))         # windwheel hill
        elev += 1.2 * np.exp(-((u + 26) ** 2 / 90 + (v - 12) ** 2 / 200))          # gentle left rise
        elev += 0.9 * np.exp(-((u - 4) ** 2 / 200 + (v - 42) ** 2 / 90))           # front meadow rise
        # river valley: snakes from the back centre to the front right, stepping down at two falls
        uc = 1 + 4.5 * np.sin(v * 0.13 + 0.8) + 0.18 * (v - 23)
        dist = np.abs(u - uc) * np.ones_like(v)
        bed = np.clip(2 - np.floor(v / 17.0), 0, 2) * np.ones_like(u)
        elev = elev - 2.4 * np.exp(-((dist / 4.5) ** 2))
        near = dist < 6.5
        elev = np.where(near, np.maximum(elev, bed), elev)
        # village terrace (front-left) flattened to level 1
        vill = np.exp(-(((u + 16) / 7.5) ** 2 + ((v - 22) / 6.5) ** 2) * 1.0)
        elev = elev * (1 - vill) + 1.0 * vill
        level = np.clip(np.round(elev), 0, 5).astype(int)
        water = dist < 1.7
        bank = (dist >= 1.7) & (dist < 2.9)
        level = np.where(water | bank, bed.astype(int), level)
        self.level = level
        self.water = water
        self.moist = 0.6 * n2 + 0.4 * np.clip(1 - dist / 9.0, 0, 1)
        self.n1, self.n2 = n1, n2
        biome = np.full((nk, nd), "grass", dtype=object)
        biome[(self.moist > 0.56) & (level >= 1) & (level <= 4)] = "forest"
        biome[(self.moist > 0.47) & (v < 11) & (level >= 2)] = "forest"
        biome[(self.moist < 0.42) & (level >= 4)] = "dry"
        biome[(level >= 5) & (self.moist < 0.38)] = "rock"
        biome[(n2 > 0.55) & (self.moist > 0.45) & (level <= 3) & (biome == "grass")] = "meadow"
        biome[bank] = "sand"
        biome[vill > 0.35] = "grass"
        biome[water] = "water"
        self.biome = biome
        self.vill = vill
        self.rng = rng
        self.objects = {}   # (k, d) -> list of ("tree"|"hut"|"field"|"wheel"|"stone", data)
        self.path = set()
        self.bridge = set()

    def idx(self, k, d):
        return k - K0, d - D0

    def get(self, arr, k, d):
        kk, dd = self.idx(k, d)
        if 0 <= kk < self.nk and 0 <= dd < self.nd:
            return arr[kk, dd]
        return None

    def lvl(self, k, d):
        r = self.get(self.level, k, d)
        return 0 if r is None else int(r)

    def set_path(self, pts):
        """pts: list of (k, d) waypoints (same parity). Walk between them on the tile lattice."""
        for (k0, d0), (k1, d1) in zip(pts, pts[1:]):
            k, d = k0, d0
            self.path.add((k, d))
            while (k, d) != (k1, d1):
                dk, dd = np.sign(k1 - k), np.sign(d1 - d)
                if dk != 0 and dd != 0:
                    k += dk
                    d += dd
                elif dk != 0:
                    k += 2 * dk if abs(k1 - k) >= 2 else dk
                    if abs(k1 - k) % 2 == 1:
                        d += 1 if d < 0 else -1
                        k -= dk
                else:
                    d += 2 * dd if abs(d1 - d) >= 2 else dd
                    if abs(d1 - d) % 2 == 1:
                        k += 1
                        d -= dd
                self.path.add((k, d))
        for (k, d) in list(self.path):
            if self.get(self.water, k, d):
                self.bridge.add((k, d))

    def add(self, k, d, kind, data=None):
        self.objects.setdefault((k, d), []).append((kind, data))


# ----------------------------------------------------------------------------- palettes
PAL = {
    "A": dict(  # dawn
        sky_top=(96, 112, 168), sky_mid=(214, 160, 140), sky_hor=(252, 226, 176),
        haze=(206, 196, 200), haze2=(178, 170, 186), fog=(226, 214, 208),
        grass=(122, 158, 84), meadow=(140, 168, 92), forest=(96, 138, 78), dry=(168, 160, 96),
        rock=(174, 156, 130), sand=(214, 192, 142), water=(122, 160, 190), path=(184, 158, 112),
        top_tint=(255, 214, 170), tint_k=0.22, face_l=0.86, face_r=0.62,
        tree=(84, 128, 70), tree_hi=(132, 168, 92), trunk=(96, 70, 48),
        cloud=(255, 236, 226), sun=(255, 226, 170), mist=True,
    ),
    "B": dict(  # afternoon
        sky_top=(72, 142, 214), sky_mid=(140, 194, 236), sky_hor=(212, 232, 244),
        haze=(178, 204, 224), haze2=(146, 180, 206), fog=(200, 220, 232),
        grass=(118, 172, 82), meadow=(142, 186, 94), forest=(84, 146, 76), dry=(178, 172, 100),
        rock=(180, 164, 140), sand=(226, 204, 150), water=(84, 152, 204), path=(196, 168, 118),
        top_tint=(255, 250, 220), tint_k=0.08, face_l=0.84, face_r=0.60,
        tree=(74, 136, 68), tree_hi=(126, 184, 92), trunk=(102, 74, 50),
        cloud=(255, 255, 255), sun=(255, 244, 200), mist=False,
    ),
}


# ----------------------------------------------------------------------------- iso geometry (2x coords)
def tile_center(k, d, level):
    x = OX + d * (TW // 2)
    y = OY + k * (TH // 2) - level * STEP
    return x * S, y * S


def diamond(cx, cy):
    hw, hh = TW * S // 2, TH * S // 2
    return [(cx, cy - hh), (cx + hw, cy), (cx, cy + hh), (cx - hw, cy)]


def draw_tile(dr, T, k, d, pal, rng, frame):
    lv = T.lvl(k, d)
    b = T.get(T.biome, k, d)
    cx, cy = tile_center(k, d, lv)
    base = pal[b]
    if (k, d) in T.path and b != "water":
        base = pal["path"]
    # per-tile variation
    var = 0.92 + 0.16 * T.get(T.n2, k, d)
    top = shade(base, var)
    top = mix(top, pal["top_tint"], pal["tint_k"])
    hw, hh = TW * S // 2, TH * S // 2
    poly = diamond(cx, cy)
    # cliff faces: left face shared with (k+1, d-1), right face with (k+1, d+1)
    for side, (nk, nd) in (("l", (k + 1, d - 1)), ("r", (k + 1, d + 1))):
        nl = T.lvl(nk, nd)
        if T.get(T.water, nk, nd) and nl > lv:
            nl = lv
        drop = lv - nl
        if drop <= 0:
            continue
        hpx = drop * STEP * S
        fc = shade(mix(base if b != "water" else pal["sand"], pal["rock"], 0.45),
                   pal["face_l"] if side == "l" else pal["face_r"])
        if side == "l":
            pts = [(cx - hw, cy), (cx, cy + hh), (cx, cy + hh + hpx), (cx - hw, cy + hpx)]
        else:
            pts = [(cx + hw, cy), (cx, cy + hh), (cx, cy + hh + hpx), (cx + hw, cy + hpx)]
        dr.polygon(pts, fill=fc)
        # strata lines on tall faces
        if drop >= 2:
            for s_ in range(1, drop):
                yy = s_ * STEP * S
                if side == "l":
                    dr.line([(cx - hw, cy + yy), (cx, cy + hh + yy)], fill=shade(fc, 0.9), width=S)
                else:
                    dr.line([(cx + hw, cy + yy), (cx, cy + hh + yy)], fill=shade(fc, 0.9), width=S)
    dr.polygon(poly, fill=top)
    # water: ripple streaks along flow (toward front-left), phase by frame
    if b == "water":
        rr = np.random.default_rng(abs(k * 131 + d * 17) + 3)
        for _ in range(3):
            fx = cx + int(rr.uniform(-hw * 0.6, hw * 0.5))
            fy = cy + int(rr.uniform(-hh * 0.5, hh * 0.5))
            ln = int(rr.uniform(6, 14)) * S
            dr.line([(fx, fy), (fx + ln, fy + ln // 2)], fill=mix(top, (255, 255, 255), 0.42), width=S)
        # bright rim on the upstream (back) edge = reflected sky
        dr.line([poly[3], poly[0]], fill=mix(top, pal["sky_hor"], 0.5), width=S)
        # bridge planks
        if (k, d) in T.bridge:
            pk = pal["trunk"]
            dr.polygon([(cx - hw * 0.55, cy - hh * 0.28), (cx + hw * 0.55, cy + hh * 0.28),
                        (cx + hw * 0.55, cy + hh * 0.28 + 3 * S), (cx - hw * 0.55, cy - hh * 0.28 + 3 * S)],
                       fill=shade(pk, 0.8))
            dr.polygon([(cx - hw * 0.55, cy - hh * 0.28), (cx + hw * 0.55, cy + hh * 0.28),
                        (cx + hw * 0.55 - 2 * S, cy + hh * 0.28 + S), (cx - hw * 0.55 - 2 * S, cy - hh * 0.28 + S)],
                       fill=mix(pk, (255, 230, 190), 0.45))
            for t in np.linspace(0.05, 0.95, 7):
                px = cx - hw * 0.55 + t * hw * 1.1
                py = cy - hh * 0.28 + t * hh * 0.56
                dr.line([(px - 4 * S, py + 2 * S), (px + 3 * S, py - 2 * S)], fill=shade(pk, 0.62), width=S)
        return
    # sand ripple
    if b == "sand":
        dr.line([(cx - hw * 0.5, cy + 2 * S), (cx - hw * 0.1, cy - hh * 0.2)], fill=shade(top, 0.93), width=S)
    # grass tufts leaning with the wind (to the right / +x)
    if b in ("grass", "meadow", "dry", "forest") and (k, d) not in T.path:
        rr = np.random.default_rng(abs(k * 977 + d * 31) + 5)
        n = 6 if b != "dry" else 3
        gcol = mix(top, (255, 255, 200), 0.28)
        for _ in range(n):
            ang = rr.uniform(0, 2 * math.pi)
            rad = rr.uniform(0, 0.75)
            gx = cx + math.cos(ang) * rad * hw
            gy = cy + math.sin(ang) * rad * hh
            bend = 3 * S + 2 * S * math.sin(frame * 0.7 + gx * 0.01)
            dr.line([(gx, gy), (gx + bend, gy - 4 * S)], fill=gcol, width=S)
        if b == "meadow":
            fl = [(246, 190, 210), (250, 244, 200), (255, 255, 255), (230, 170, 230)]
            for _ in range(4):
                ang = rr.uniform(0, 2 * math.pi)
                rad = rr.uniform(0, 0.7)
                fx = cx + math.cos(ang) * rad * hw
                fy = cy + math.sin(ang) * rad * hh
                dr.rectangle([fx, fy, fx + S, fy + S], fill=fl[int(rr.integers(0, 4))])
    if b == "rock":
        rr = np.random.default_rng(abs(k * 51 + d * 7))
        for _ in range(2):
            fx = cx + int(rr.uniform(-hw * 0.5, hw * 0.4))
            fy = cy + int(rr.uniform(-hh * 0.4, hh * 0.4))
            dr.line([(fx, fy), (fx + 8 * S, fy + 3 * S)], fill=shade(top, 0.85), width=S)
    if (k, d) in T.path:
        rr = np.random.default_rng(abs(k * 7 + d * 13))
        for _ in range(3):
            fx = cx + int(rr.uniform(-hw * 0.5, hw * 0.5))
            fy = cy + int(rr.uniform(-hh * 0.5, hh * 0.5))
            dr.ellipse([fx, fy, fx + 2 * S, fy + S], fill=shade(top, 0.86))


# ----------------------------------------------------------------------------- objects (2x coords)
def draw_shadow(dr, cx, cy, rx, ry):
    dr.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(40, 40, 30, 70))


def draw_tree(dr, cx, cy, pal, size, seed):
    rr = np.random.default_rng(seed)
    trunk = pal["trunk"]
    th = int((10 + 6 * size) * S)
    tw = int(2 * S + size * S)
    draw_shadow(dr, cx + 4 * S, cy + S, int(9 * S * size + 6 * S), int(3 * S))
    dr.rectangle([cx - tw // 2, cy - th, cx + tw // 2, cy], fill=trunk)
    dr.rectangle([cx - tw // 2, cy - th, cx - tw // 2 + S, cy], fill=shade(trunk, 1.25))
    base_r = int((9 + 6 * size) * S)
    cols = (pal["tree"], mix(pal["tree"], pal["tree_hi"], 0.5), pal["tree_hi"])
    y = cy - th
    for lvl_ in range(3):
        r = int(base_r * (1 - lvl_ * 0.28))
        hh = int(r * 0.62)
        yy = y - lvl_ * int(hh * 1.05)
        jitter = int(rr.integers(-2, 3)) * S
        # angular canopy: hexagon-ish diamond
        pts = [(cx + jitter, yy - hh - hh // 2), (cx + jitter + r, yy - hh // 3), (cx + jitter + r * 0.55, yy + hh // 2),
               (cx + jitter - r * 0.55, yy + hh // 2), (cx + jitter - r, yy - hh // 3)]
        dr.polygon(pts, fill=shade(cols[0], 0.9))
        # lit left-top facet
        lit = [(cx + jitter, yy - hh - hh // 2), (cx + jitter - r, yy - hh // 3), (cx + jitter - r * 0.55, yy + hh // 2),
               (cx + jitter - r * 0.1, yy)]
        dr.polygon(lit, fill=cols[1 + (lvl_ % 2)])


def draw_hut(dr, cx, cy, pal, colour, seed, size=1.0):
    """Iso hut on one tile: two walls + pitched roof in the builder's colour."""
    hw, hh = TW * S // 2, TH * S // 2
    wall_h = int(16 * S * size)
    wall = (232, 214, 178)
    wall_l = shade(wall, 0.97)
    wall_r = shade(wall, 0.78)
    inset = 0.78
    L_, R_, B_, Tp = (cx - hw * inset, cy), (cx + hw * inset, cy), (cx, cy + hh * inset), (cx, cy - hh * inset)
    draw_shadow(dr, cx + 6 * S, cy + 3 * S, int(hw * 0.9), int(hh * 0.7))
    # walls
    dr.polygon([L_, B_, (B_[0], B_[1] - wall_h), (L_[0], L_[1] - wall_h)], fill=wall_l)
    dr.polygon([R_, B_, (B_[0], B_[1] - wall_h), (R_[0], R_[1] - wall_h)], fill=wall_r)
    # timber line
    dr.line([(L_[0], L_[1] - wall_h), (B_[0], B_[1] - wall_h), (R_[0], R_[1] - wall_h)], fill=shade(wall, 0.6), width=S)
    # door on right wall
    dx = (R_[0] + B_[0]) / 2 + 2 * S
    dy = (R_[1] + B_[1]) / 2 + S
    dr.polygon([(dx - 4 * S, dy - 2 * S - 9 * S), (dx + 4 * S, dy - 4 * S - 9 * S), (dx + 4 * S, dy - 4 * S), (dx - 4 * S, dy - 2 * S)],
               fill=(88, 62, 44))
    # roof: ridge runs left-right (from L to R side), two slopes front/back; we see the front slope + gable
    ridge_h = wall_h + int(11 * S * size)
    rl = (L_[0] - 3 * S, L_[1] - ridge_h + 5 * S)
    rr_ = (R_[0] + 3 * S, R_[1] - ridge_h + 5 * S)
    peak_l = (L_[0] - 3 * S, L_[1] - ridge_h - 2 * S)
    roof_front = shade(colour, 0.88)
    roof_back = mix(colour, (255, 255, 255), 0.18)
    # front slope (toward viewer): from ridge to bottom edge B
    ridge = ((L_[0] + R_[0]) / 2, (L_[1] + R_[1]) / 2 - ridge_h)
    # ridge line goes from back-left to right through the centre: define two ridge ends
    ridge_a = ((L_[0] + Tp[0]) / 2 - 2 * S, (L_[1] + Tp[1]) / 2 - ridge_h)   # back-left end
    ridge_b = ((R_[0] + B_[0]) / 2 + 2 * S, (R_[1] + B_[1]) / 2 - ridge_h)   # front-right end
    eave_l = (L_[0] - 3 * S, L_[1] - wall_h + 3 * S)
    eave_b = (B_[0] - 0, B_[1] - wall_h + 4 * S)
    eave_t = (Tp[0], Tp[1] - wall_h + 2 * S)
    eave_r = (R_[0] + 3 * S, R_[1] - wall_h + 3 * S)
    # left slope (lit): ridge_a -> ridge_b -> eave_b -> eave_l
    dr.polygon([ridge_a, ridge_b, eave_b, eave_l], fill=roof_back)
    # right/back slope (darker): ridge_a -> ridge_b -> eave_r -> eave_t
    dr.polygon([ridge_a, ridge_b, eave_r, eave_t], fill=roof_front)
    dr.line([ridge_a, ridge_b], fill=mix(colour, (255, 255, 255), 0.45), width=S)
    # shingle lines on the lit slope
    for t in (0.35, 0.7):
        pa = (ridge_a[0] + (eave_l[0] - ridge_a[0]) * t, ridge_a[1] + (eave_l[1] - ridge_a[1]) * t)
        pb = (ridge_b[0] + (eave_b[0] - ridge_b[0]) * t, ridge_b[1] + (eave_b[1] - ridge_b[1]) * t)
        dr.line([pa, pb], fill=shade(roof_back, 0.9), width=S)


def draw_field(dr, cx, cy, pal, colour, seed, grown=0.6):
    """Farmed plot: tilled diamond with crop rows tinted by the builder's colour."""
    hw, hh = TW * S // 2, TH * S // 2
    soil = (150, 116, 80)
    dr.polygon([(cx, cy - hh * 0.9), (cx + hw * 0.9, cy), (cx, cy + hh * 0.9), (cx - hw * 0.9, cy)], fill=soil)
    crop = mix((150, 190, 90), colour, 0.35)
    for t in np.linspace(0.12, 0.88, 6):
        # rows parallel to the left edge (from top-left edge to bottom-right edge)
        ax = cx - hw * 0.9 + t * hw * 0.9
        ay = cy - t * hh * 0.9
        bx = cx + t * hw * 0.9
        by = cy + hh * 0.9 - t * hh * 0.9
        dr.line([(ax, ay), (bx, by)], fill=shade(soil, 0.8), width=S)
        # crop tufts along the row
        n = int(5 * grown) + 2
        for u in np.linspace(0.1, 0.9, n):
            px = ax + (bx - ax) * u
            py = ay + (by - ay) * u
            hgt = int((2 + 4 * grown) * S)
            dr.line([(px, py), (px + S, py - hgt)], fill=crop, width=S)
            dr.point((px + S, py - hgt), fill=mix(crop, (255, 255, 200), 0.4))


def draw_marker(dr, cx, cy, colour):
    """Plot marker post in the owner's colour (the 'this is mine' sign)."""
    dr.rectangle([cx - S, cy - 14 * S, cx + S, cy], fill=(90, 70, 50))
    dr.polygon([(cx + S, cy - 14 * S), (cx + 8 * S, cy - 12 * S), (cx + S, cy - 9 * S)], fill=colour)


def draw_windwheel(dr, cx, cy, pal, frame):
    """Invented landmark: tapered stone tower, cone roof, a 4-blade wind-wheel on the side facing the wind."""
    stone = (216, 200, 168)
    stone_r = shade(stone, 0.72)
    hgt = 92 * S
    bw, tw_ = 26 * S, 16 * S
    draw_shadow(dr, cx + 14 * S, cy + 3 * S, 30 * S, 8 * S)
    # tower: left (lit) and right (dark) halves, tapering
    dr.polygon([(cx - bw, cy), (cx, cy + 8 * S), (cx, cy - hgt + 4 * S), (cx - tw_, cy - hgt)], fill=stone)
    dr.polygon([(cx + bw, cy), (cx, cy + 8 * S), (cx, cy - hgt + 4 * S), (cx + tw_, cy - hgt)], fill=stone_r)
    for yy in range(12, 92, 12):
        y = cy - yy * S
        f = yy / 92
        dr.line([(cx - (bw + (tw_ - bw) * f), y), (cx, y + 6 * S * (1 - f) + S)], fill=shade(stone, 0.9), width=S)
        dr.line([(cx, y + 6 * S * (1 - f) + S), (cx + (bw + (tw_ - bw) * f), y)], fill=shade(stone_r, 0.9), width=S)
    # door + window
    dr.rectangle([cx + 6 * S, cy - 16 * S, cx + 12 * S, cy + 2 * S], fill=(80, 58, 40))
    dr.rectangle([cx - 8 * S, cy - 60 * S, cx - 4 * S, cy - 52 * S], fill=(70, 60, 60))
    # cap
    cap = (176, 88, 62)
    dr.polygon([(cx - tw_ - 4 * S, cy - hgt + 2 * S), (cx, cy - hgt - 18 * S), (cx + tw_ + 4 * S, cy - hgt + 2 * S), (cx, cy - hgt + 6 * S)],
               fill=cap)
    dr.polygon([(cx - tw_ - 4 * S, cy - hgt + 2 * S), (cx, cy - hgt - 18 * S), (cx, cy - hgt + 6 * S)], fill=mix(cap, (255, 220, 190), 0.25))
    # wheel: hub in front of the tower's upper-left, 4 blades
    hx, hy = cx - 4 * S, cy - hgt + 22 * S
    ang0 = frame * 0.3 + 0.35
    blade_len = 44 * S
    for b in range(4):
        a = ang0 + b * math.pi / 2
        ex, ey = hx + math.cos(a) * blade_len, hy + math.sin(a) * blade_len * 0.92
        nx, ny = -math.sin(a) * 5 * S, math.cos(a) * 5 * S
        sail = [(hx + math.cos(a) * 8 * S, hy + math.sin(a) * 8 * S), (ex, ey), (ex + nx, ey + ny),
                (hx + math.cos(a) * 8 * S + nx, hy + math.sin(a) * 8 * S + ny)]
        dr.polygon(sail, fill=(242, 232, 210))
        dr.line([(hx, hy), (ex, ey)], fill=(92, 66, 46), width=2 * S)
        for t in (0.35, 0.6, 0.85):
            px, py = hx + math.cos(a) * blade_len * t, hy + math.sin(a) * blade_len * t * 0.92
            dr.line([(px, py), (px + nx, py + ny)], fill=(130, 100, 70), width=S)
    dr.ellipse([hx - 4 * S, hy - 4 * S, hx + 4 * S, hy + 4 * S], fill=(92, 66, 46))


def draw_stone(dr, cx, cy, pal, letter_col):
    stone = (188, 178, 160)
    draw_shadow(dr, cx + 4 * S, cy + 2 * S, 12 * S, 4 * S)
    dr.polygon([(cx - 9 * S, cy + 2 * S), (cx - 8 * S, cy - 30 * S), (cx - 2 * S, cy - 34 * S), (cx + 8 * S, cy - 31 * S), (cx + 9 * S, cy + 2 * S)],
               fill=stone)
    dr.polygon([(cx - 9 * S, cy + 2 * S), (cx - 8 * S, cy - 30 * S), (cx - 2 * S, cy - 34 * S), (cx - 1 * S, cy + 2 * S)],
               fill=shade(stone, 1.08))


# ----------------------------------------------------------------------------- sky, haze, clouds, mist
def sky_layer(pal, frame_id):
    img = Image.new("RGB", (W, H))
    arr = np.zeros((H, W, 3), dtype=np.float64)
    ys = np.arange(H)[:, None, None].astype(float)
    hor = 205.0
    t = np.clip(ys / hor, 0, 1) ** 1.1
    top = np.array(pal["sky_top"], float)
    midc = np.array(pal["sky_mid"], float)
    horc = np.array(pal["sky_hor"], float)
    c = np.where(t[..., :1] < 0.6, top + (midc - top) * (t / 0.6), midc + (horc - midc) * ((t - 0.6) / 0.4))
    arr[:] = c
    arr[int(hor):] = horc
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    # sun + glow
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    if frame_id == "A":
        sx, sy, r = 170, 196, 30
    else:
        sx, sy, r = 128, 112, 20
    for i, a in ((6.0, 26), (3.4, 50), (2.0, 80)):
        gd.ellipse([sx - r * i, sy - r * i, sx + r * i, sy + r * i], fill=pal["sun"] + (a,))
    glow = glow.filter(ImageFilter.GaussianBlur(18))
    img = Image.alpha_composite(img.convert("RGBA"), glow)
    d = ImageDraw.Draw(img)
    d.ellipse([sx - r, sy - r, sx + r, sy + r], fill=(255, 250, 232, 255))
    if frame_id == "A":  # setting moon, pale, on the right
        mx, my, mr = 1085, 118, 15
        moon = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        md = ImageDraw.Draw(moon)
        md.ellipse([mx - mr, my - mr, mx + mr, my + mr], fill=(250, 246, 240, 150))
        md.ellipse([mx - mr + 7, my - mr - 3, mx + mr + 7, my + mr - 3], fill=(0, 0, 0, 0))
        # crescent via cut: redraw as two ellipses using mask
        cres = Image.new("L", (W, H), 0)
        cd = ImageDraw.Draw(cres)
        cd.ellipse([mx - mr, my - mr, mx + mr, my + mr], fill=150)
        cd.ellipse([mx - mr + 8, my - mr - 4, mx + mr + 8, my + mr - 4], fill=0)
        moon = Image.new("RGBA", (W, H), (250, 246, 240, 0))
        moon.putalpha(cres)
        img = Image.alpha_composite(img, moon)
    # haze hills (two layers) above the terrain's back ridge
    rng = np.random.default_rng(3)
    for base, amp, col, cell in ((214, 58, mix(pal["haze"], pal["sky_hor"], 0.35), 90), (222, 40, pal["haze"], 55)):
        n = fbm((1, W), (cell, cell // 3), (1.0, 0.35), rng)[0]
        pts = [(x, base - amp * n[x] ** 1.3) for x in range(0, W, 4)] + [(W, base), (W, 320), (0, 320)]
        ImageDraw.Draw(img).polygon(pts, fill=col + (255,))
    return img


def clouds_layer(pal, frame_id):
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    rng = np.random.default_rng(21 if frame_id == "A" else 22)
    n = 5 if frame_id == "A" else 7
    for i in range(n):
        cx = int(rng.uniform(40, W - 40))
        cy = int(rng.uniform(88, 175))
        scale = rng.uniform(0.6, 1.3) * (0.6 + 0.6 * (cy - 88) / 90)
        for j in range(int(rng.integers(4, 8))):
            ox = int(rng.normal(0, 38 * scale))
            oy = int(rng.normal(0, 6 * scale))
            rx = int(rng.uniform(22, 48) * scale)
            ry = int(rx * rng.uniform(0.32, 0.5))
            a = int(rng.uniform(120, 200))
            d.ellipse([cx + ox - rx, cy + oy - ry, cx + ox + rx, cy + oy + ry], fill=pal["cloud"] + (a,))
        # flat, slightly shaded underside
        d.ellipse([cx - 60 * scale, cy - 4, cx + 60 * scale, cy + 10 * scale],
                  fill=mix(pal["cloud"], pal["sky_top"], 0.25) + (110,))
    return lay.filter(ImageFilter.GaussianBlur(4))


def mist_layer(T, pal, positions):
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    for (k, d_), lv in positions:
        if lv <= 1:
            cx, cy = tile_center(k, d_, lv)
            cx //= S
            cy //= S
            a = 88 if lv == 0 else 46
            d.ellipse([cx - 70, cy - 14, cx + 70, cy + 14], fill=(244, 236, 236, a))
    return lay.filter(ImageFilter.GaussianBlur(22))


# ----------------------------------------------------------------------------- pips (1x)
def pip_sprite(name, frame, facing=1, tier=1, scale=4):
    if PIPS is not None:
        g, salt = PIPS.resolve_genome(name.lower())
        rgb, mask = PIPS.sprite(name.lower(), salt, tier, frame, preset="kick", facing=facing)
    else:
        col = name_colour(name)
        rgb = np.zeros((11, 12, 3), np.uint8)
        mask = np.zeros((11, 12), bool)
        for y in range(3, 11):
            for x in range(1, 11):
                if x - 1 >= (10 - y):
                    mask[y, x] = True
                    rgb[y, x] = col
        if facing < 0:
            rgb, mask = rgb[:, ::-1], mask[:, ::-1]
    rgb = np.repeat(np.repeat(rgb, scale, 0), scale, 1)
    mask = np.repeat(np.repeat(mask, scale, 0), scale, 1)
    rgba = np.dstack([rgb, (mask * 255).astype(np.uint8)])
    return Image.fromarray(rgba)


def draw_pip(img, x, y, name, frame="idle0", facing=1, tier=1, label=True, sub=None, dim=False):
    """x, y: screen (1x) point where the feet touch the ground."""
    spr = pip_sprite(name, frame, facing, tier)
    if dim:
        a = np.array(spr).astype(float)
        a[..., :3] = a[..., :3] * 0.8 + 30
        spr = Image.fromarray(a.astype(np.uint8))
    sw, sh = spr.size
    d = ImageDraw.Draw(img)
    d.ellipse([x - sw // 2 - 2, y - 5, x + sw // 2 + 2, y + 4], fill=(40, 36, 28, 80))
    # 1 px dark outline so the creature reads on bright grass
    outline = Image.new("RGBA", (sw + 2, sh + 2), (0, 0, 0, 0))
    m = spr.split()[3]
    for ox, oy in ((0, 1), (2, 1), (1, 0), (1, 2)):
        outline.paste((46, 36, 28, 200), (ox, oy), m)
    img.alpha_composite(outline, (x - sw // 2 - 1, y - sh - 1))
    img.alpha_composite(spr, (x - sw // 2, y - sh))
    if label:
        f = font("menlo", 20)
        s = "@" + name
        col = name_colour(name)
        tw = text_w(d, s, f)
        ty = y - sh - 27
        text_shadow(d, (x - tw // 2, ty), s, f, col + (255,), shadow=(36, 28, 22, 220), off=1)
        if sub:
            f2 = font("menlo", 20)
            tw2 = text_w(d, sub, f2)
            text_shadow(d, (x - tw2 // 2, ty - 24), sub, f2, (246, 236, 220, 255), shadow=(36, 28, 22, 220))
    return sw, sh


def bubble_box(d, x, y_top, text, dx=0, max_w=408):
    f = font("menlo", 22)
    words = text.split()
    lines, cur = [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if text_w(d, t, f) > max_w - 28 and cur:
            lines.append(cur)
            cur = wd
        else:
            cur = t
    if cur:
        lines.append(cur)
    lines = lines[:3]
    lw = max(text_w(d, ln, f) for ln in lines)
    bw, bh = lw + 28, 30 * len(lines) + 12
    bx = int(min(max(8, x + dx - bw // 2), W - bw - 8))
    by = y_top - 12 - bh
    return (bx, by, bx + bw, by + bh), lines


def draw_bubble(img, x, y_top, text, max_w=408, dx=0):
    """Cream speech bubble whose tail points down at (x, y_top); the box may sit dx to the side."""
    d = ImageDraw.Draw(img)
    f = font("menlo", 22)
    (bx, by, bx2, by2), lines = bubble_box(d, x, y_top, text, dx, max_w)
    bw, bh = bx2 - bx, by2 - by
    tx = int(min(max(x, bx + 16), bx + bw - 16))
    d.rounded_rectangle([bx + 2, by + 3, bx + bw + 2, by + bh + 3], radius=9, fill=(40, 30, 24, 60))
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=9, fill=(255, 248, 232, 240), outline=(120, 96, 72, 255), width=1)
    d.polygon([(tx - 8, by + bh - 1), (tx + 8, by + bh - 1), (x, by + bh + 10)], fill=(255, 248, 232, 240))
    d.line([(tx - 8, by + bh), (x, by + bh + 10), (tx + 8, by + bh)], fill=(120, 96, 72, 255), width=1)
    for i, ln in enumerate(lines):
        d.text((bx + 14, by + 6 + i * 30), ln, font=f, fill=(58, 44, 34, 255))
    return


def _old_draw_bubble(img, x, y_top, text, max_w=408, above=True):
    d = ImageDraw.Draw(img)
    f = font("menlo", 22)
    words = text.split()
    lines, cur = [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if text_w(d, t, f) > max_w - 28 and cur:
            lines.append(cur)
            cur = wd
        else:
            cur = t
    if cur:
        lines.append(cur)
    lines = lines[:3]
    lw = max(text_w(d, ln, f) for ln in lines)
    bw, bh = lw + 28, 30 * len(lines) + 12
    bx = int(min(max(8, x - bw // 2), W - bw - 8))
    by = y_top - 12 - bh
    d.rounded_rectangle([bx + 2, by + 3, bx + bw + 2, by + bh + 3], radius=9, fill=(40, 30, 24, 60))
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=9, fill=(255, 248, 232, 240), outline=(120, 96, 72, 255), width=1)
    d.polygon([(x - 8, by + bh - 1), (x + 8, by + bh - 1), (x, by + bh + 10)], fill=(255, 248, 232, 240))
    d.line([(x - 8, by + bh), (x, by + bh + 10), (x + 8, by + bh)], fill=(120, 96, 72, 255), width=1)
    for i, ln in enumerate(lines):
        d.text((bx + 14, by + 6 + i * 30), ln, font=f, fill=(58, 44, 34, 255))


# ----------------------------------------------------------------------------- HUD (1x)
def panel(d, box, alpha=150):
    x0, y0, x1, y1 = box
    d.rounded_rectangle([x0, y0, x1, y1], radius=10, fill=(38, 28, 24, alpha))


def draw_header(img, count_big, next_event, watching, wordmark="atleastonce · THE VALE", bar_frac=0.62):
    d = ImageDraw.Draw(img)
    # translucent warm gradient band 0..66 + countdown bar 66..72
    band = Image.new("RGBA", (W, 72), (0, 0, 0, 0))
    ba = np.zeros((72, W, 4), np.uint8)
    for y in range(66):
        a = int(210 - 60 * (y / 66))
        ba[y] = (44, 32, 28, a)
    ba[66:72] = (44, 32, 28, 200)
    band = Image.fromarray(ba)
    img.alpha_composite(band, (0, 0))
    d = ImageDraw.Draw(img)
    cream = (250, 240, 222, 255)
    f_word = font("hn", 22)
    d.ellipse([14, 26, 26, 38], fill=(83, 252, 24, 255))   # chat-link dot (unchanged from the cave)
    d.text((34, 20), wordmark, font=f_word, fill=cream)
    f_big = font("ab", 56)
    bw_ = text_w(d, count_big, f_big)
    x_big = 288
    d.text((x_big + 2, 2 + 2), count_big, font=f_big, fill=(30, 20, 16, 160))
    d.text((x_big, 2), count_big, font=f_big, fill=(255, 224, 150, 255))
    f20 = font("menlo", 20)
    rx = max(x_big + bw_ + 16, 1000)
    d.text((rx, 8), "NEXT EVENT " + next_event, font=f20, fill=cream)
    d.ellipse([rx, 42, rx + 12, 54], fill=(236, 64, 64, 255))
    d.text((rx + 20, 36), "LIVE " + watching, font=f20, fill=cream)
    # countdown bar (gold, shrinking right to left)
    d.rectangle([0, 66, int(W * bar_frac), 72], fill=(255, 196, 92, 255))


def draw_hud_bottom(img, colony, keeper, chat, frame_id):
    d = ImageDraw.Draw(img)
    y0, y1 = 592, 692
    panel(d, (12, y0, 384, y1))
    panel(d, (396, y0, 768, y1))
    panel(d, (780, y0, 1268, y1))
    cream = (250, 240, 222, 255)
    dim = (214, 200, 184, 255)
    f22h = font("hn", 22)
    f22 = font("menlo", 22)
    f20 = font("menlo", 20)
    # colony
    d.text((26, y0 + 8), fit(d, colony["line1"], f22h, 346), font=f22h, fill=cream)
    d.rectangle([26, y0 + 38, 370, y0 + 44], fill=(80, 64, 56, 255))
    d.rectangle([26, y0 + 38, 26 + int(344 * colony["frac"]), y0 + 44], fill=(255, 196, 92, 255))
    d.text((26, y0 + 48), fit(d, colony["line2"], f22, 346), font=f22, fill=cream)
    d.text((26, y0 + 74), fit(d, colony["line3"], f20, 346), font=f20, fill=dim)
    # keeper
    d.text((410, y0 + 8), fit(d, keeper["line1"], f22h, 346), font=f22h, fill=cream)
    d.text((410, y0 + 40), fit(d, keeper["line2"], f22, 346), font=f22, fill=cream)
    d.text((410, y0 + 70), fit(d, keeper["line3"], f20, 346), font=f20, fill=dim)
    # chat log (5 lines, 26 px pitch would need 130; panel is 100 -> show 4 lines at 22 px: still >= 20 px)
    for i, (who, msg, chip) in enumerate(chat[:4]):
        yy = y0 + 6 + i * 23
        x = 794
        if who:
            col = name_colour(who) + (255,)
            d.text((x, yy), "@" + who, font=f20, fill=col)
            x += text_w(d, "@" + who, f20) + 8
            if chip:
                d.rounded_rectangle([x, yy + 1, x + 26, yy + 21], radius=4, fill=(255, 196, 92, 255))
                d.text((x + 6, yy - 1), chip, font=font("menlo_b", 20), fill=(50, 34, 24, 255))
                x += 34
            d.text((x, yy), fit(d, msg, f20, 1254 - x), font=f20, fill=cream)
        else:
            d.text((x, yy), msg, font=f20, fill=dim)
    # caption bar (very bottom): concept render notice
    d.rectangle([0, 696, W, 720], fill=(38, 28, 24, 235))
    cap = "concept render · names are examples"
    d.text((14, 698), cap, font=f20, fill=(230, 214, 190, 255))
    right = "isometric · settlement direction · frame " + frame_id + " · v0.6 mock"
    d.text((W - 14 - text_w(d, right, f20), 698), right, font=f20, fill=(190, 176, 160, 255))


def draw_plank(img, text):
    d = ImageDraw.Draw(img)
    f = font("hn", 22)
    tw = text_w(d, text, f)
    d.rounded_rectangle([16, 84, 16 + tw + 24, 84 + 34], radius=8, fill=(255, 246, 228, 200), outline=(140, 110, 80, 255), width=1)
    d.text((28, 88), text, font=f, fill=(66, 48, 36, 255))


# ----------------------------------------------------------------------------- world assembly
STONES = (("A", (26, 6)), ("B", (27, 9)), ("C", (28, 12)))


def build_world(frame_id):
    T = Terrain(seed=7)
    rng = np.random.default_rng(99)
    # trees on forest tiles (skip village/path), a few singles on grass
    for k in range(K0, K1 + 1):
        for d in range(D0, D1 + 1):
            if (k + d) % 2:
                continue
            b = T.get(T.biome, k, d)
            if (k, d) in T.path or T.vill[T.idx(k, d)] > 0.25:
                continue
            if b == "forest" and rng.random() < 0.7:
                T.add(k, d, "tree", dict(size=rng.uniform(0.75, 1.35), seed=int(rng.integers(0, 1 << 30))))
            elif (b in ("grass", "meadow") and rng.random() < 0.035) or (b == "dry" and rng.random() < 0.10):
                T.add(k, d, "tree", dict(size=rng.uniform(0.5, 0.9), seed=int(rng.integers(0, 1 << 30))))
    # trail: village square -> bridge -> windwheel hill
    village_sq = (22, -10)
    wheel = (20, 16)
    T.set_path([village_sq, (22, -2), (22, 2), (21, 7), (20, 12), wheel])
    # the path must not run through trees
    for p in T.path:
        T.objects.pop(p, None)
    T.add(*wheel, "wheel")
    huts_A = [("kaiwren", (20, -16)), ("mossyquill", (22, -20)), ("dvn_north", (24, -14)), ("pixel_tova", (18, -12)),
              ("rue.exe", (26, -18)), ("halcyon_b", (20, -22))]
    huts_B = huts_A + [("saltmarsh", (24, -8)), ("junipr", (16, -16)), ("oatley", (28, -14)), ("fennwick", (26, -22))]
    huts = huts_A if frame_id == "A" else huts_B
    for name, (k, d) in huts:
        T.objects.pop((k, d), None)
        T.add(k, d, "hut", dict(name=name))
        T.path.discard((k, d))
    # fields next to huts (owner colour), grown more in B
    fields = [("kaiwren", (18, -18)), ("kaiwren", (18, -20)), ("dvn_north", (26, -12)), ("mossyquill", (24, -22)),
              ("rue.exe", (28, -20)), ("halcyon_b", (22, -24))]
    if frame_id == "B":
        fields += [("saltmarsh", (26, -6)), ("junipr", (16, -20)), ("oatley", (30, -16)), ("pixel_tova", (16, -10)), ("kaiwren", (20, -18))]
    for name, (k, d) in fields:
        if (k, d) in T.path or T.get(T.water, k, d):
            continue
        T.objects.pop((k, d), None)
        T.add(k, d, "field", dict(name=name, grown=0.45 if frame_id == "A" else 0.85))
    # standing stones (votes) on the meadow east of the square
    for letter, (k, d) in STONES:
        T.objects.pop((k, d), None)
        T.path.discard((k, d))
        T.add(k, d, "stone", dict(letter=letter))
    return T


def render_world(T, pal, frame_id):
    lay = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    dr = ImageDraw.Draw(lay)
    frame = 0.0 if frame_id == "A" else 1.7
    rng = np.random.default_rng(5)
    low_tiles = []
    for k in range(K0, K1 + 1):
        for d in range(D0, D1 + 1):
            if (k + d) % 2:
                continue
            draw_tile(dr, T, k, d, pal, rng, frame)
            lv = T.lvl(k, d)
            low_tiles.append(((k, d), lv))
            for kind, data in T.objects.get((k, d), []):
                cx, cy = tile_center(k, d, lv)
                if kind == "tree":
                    draw_tree(dr, cx, cy, pal, data["size"], data["seed"])
                elif kind == "hut":
                    draw_hut(dr, cx, cy, pal, name_colour(data["name"]), 0)
                elif kind == "field":
                    draw_field(dr, cx, cy, pal, name_colour(data["name"]), 0, data["grown"])
                    draw_marker(dr, cx - TW * S // 2 + 6 * S, cy + 2 * S, name_colour(data["name"]))
                elif kind == "wheel":
                    draw_windwheel(dr, cx, cy, pal, frame)
                elif kind == "stone":
                    draw_stone(dr, cx, cy, pal, None)
    # subtle dither/grain on the world layer
    arr = np.array(lay).astype(np.int16)
    grain = np.random.default_rng(1).integers(-4, 5, size=(H * S, W * S, 1))
    arr[..., :3] = np.clip(arr[..., :3] + grain, 0, 255)
    # distance fog toward the haze colour (only where the layer is opaque)
    ys = np.arange(H * S)[:, None, None] / S
    fog_t = np.clip((410 - ys) / 300.0, 0, 1) ** 1.5 * 0.72
    fogc = np.array(pal["fog"], dtype=np.int16)[None, None, :]
    rgb = arr[..., :3].astype(np.float64)
    rgb = rgb * (1 - fog_t) + fogc * fog_t
    arr[..., :3] = np.clip(rgb, 0, 255).astype(np.int16)
    lay = Image.fromarray(arr.astype(np.uint8))
    lay = lay.resize((W, H), Image.LANCZOS)
    return lay, low_tiles


def pick_tile(T, near, biomes):
    """Nearest tile to `near` whose biome is allowed and that holds no object (used to keep creatures off water/huts)."""
    k0, d0 = near
    best = None
    for k in range(k0 - 4, k0 + 5):
        for d in range(d0 - 6, d0 + 7):
            if (k + d) % 2 or (k, d) in T.objects:
                continue
            b = T.get(T.biome, k, d)
            if b in biomes:
                dist = abs(k - k0) + abs(d - d0) * 0.5
                if best is None or dist < best[0]:
                    best = (dist, k, d)
    return (best[1], best[2]) if best else near


def boxes_hit(a, b, pad=4):
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])


class Placer:
    """Puts creatures on free tiles so labels never overlap (the live HUD does the same by switching to
    label-on-speak above 40 awake; a concept frame should simply not collide)."""

    def __init__(self, T, img):
        self.T, self.img = T, img
        self.d = ImageDraw.Draw(img)
        self.occupied = []       # text boxes (labels, bubbles, signs) + sprites: nothing may cross these
        self.solid = []          # huts, the wheel, stones: sprites may not stand in them, text may pass over roofs
        self.used = set()
        # huts and the windwheel claim their silhouettes
        for (k, d_), objs in T.objects.items():
            for kind, _ in objs:
                cx, cy = ground_point(T, k, d_)
                if kind == "hut":
                    self.solid.append((cx - 22, cy - 46, cx + 22, cy + 4))
                elif kind == "wheel":
                    self.solid.append((cx - 44, cy - 125, cx + 36, cy + 8))
                    self.occupied.append((cx - 44, cy - 125, cx + 36, cy + 8))
                elif kind == "stone":
                    self.solid.append((cx - 12, cy - 36, cx + 12, cy + 24))

    def reserve(self, box):
        self.occupied.append(box)

    def label_box(self, x, y, name, sh):
        f = font("menlo", 20)
        tw = text_w(self.d, "@" + name, f)
        ty = y - sh - 27
        return (x - tw // 2, ty, x + tw // 2, ty + 22)

    def place(self, name, near, frame="idle0", facing=1, tier=1, biomes=("grass", "meadow", "sand", "dry", "path"),
              allow_water=False, sub=None, dim=False):
        k0, d0 = near
        sw, sh = pip_sprite(name, frame, facing, tier).size
        cands = []
        for k in range(k0 - 7, k0 + 8):
            for d_ in range(d0 - 14, d0 + 15):
                if (k + d_) % 2 or (k, d_) in self.used:
                    continue
                objs = self.T.objects.get((k, d_), [])
                if any(kind in ("hut", "wheel", "stone", "tree") for kind, _ in objs):
                    continue
                b = self.T.get(self.T.biome, k, d_)
                if b is None:
                    continue
                if b == "water" and not (allow_water and (k, d_) in self.T.bridge):
                    continue
                if b != "water" and b not in biomes and (k, d_) not in self.T.path:
                    continue
                cands.append((abs(k - k0) * 1.0 + abs(d_ - d0) * 0.55, k, d_))
        cands.sort()
        for _, k, d_ in cands:
            x, y = ground_point(self.T, k, d_, 0.0, 0.2)
            lb = self.label_box(x, y, name, sh)
            sb = (x - sw // 2, y - sh, x + sw // 2, y + 4)
            if sub:
                lb = (lb[0], lb[1] - 24, lb[2], lb[3])
            if lb[1] < 126 or y > 578 or lb[0] < 8 or lb[2] > W - 8:
                continue
            if any(boxes_hit(lb, o) or boxes_hit(sb, o) for o in self.occupied):
                continue
            if any(boxes_hit(sb, o, pad=0) for o in self.solid):
                continue
            self.used.add((k, d_))
            self.occupied.append(lb)
            self.occupied.append(sb)
            draw_pip(self.img, x, y, name, frame=frame, facing=facing, tier=tier, sub=sub, dim=dim)
            return dict(name=name, x=x, y=y, sw=sw, sh=sh, k=k, d=d_)
        print("WARN: no free tile for", name, "near", near, "candidates", len(cands))
        return None

    def bubble(self, pip, text):
        x, y0 = pip["x"], pip["y"] - pip["sh"] - 30
        for rise in (0, 28, 56):
            for dx in (0, -70, 70, -140, 140, -210, 210):
                y_top = y0 - rise
                box, _ = bubble_box(self.d, x, y_top, text, dx)
                box2 = (box[0], box[1], box[2], box[3] + 10 + rise)
                if box[1] < 126:
                    continue
                if not any(boxes_hit(box2, o) for o in self.occupied):
                    self.occupied.append(box2)
                    draw_bubble(self.img, x, y_top, text, dx=dx)
                    if rise:
                        self.d.line([(x, box[3] + 10), (x, pip["y"] - pip["sh"] - 20)], fill=(120, 96, 72, 255), width=1)
                    return True
        return False


def ground_point(T, k, d, fx=0.0, fy=0.0):
    """1x screen point on a tile's top face; fx, fy in [-1,1] across the diamond."""
    lv = T.lvl(k, d)
    cx, cy = tile_center(k, d, lv)
    return cx // S + int(fx * TW / 2), cy // S + int(fy * TH / 2)


def render_frame(frame_id):
    pal = PAL[frame_id]
    T = build_world(frame_id)
    img = sky_layer(pal, frame_id)
    world, low_tiles = render_world(T, pal, frame_id)
    # cloud shadows on the ground (afternoon), then the world, then clouds in the sky
    img = Image.alpha_composite(img, world)
    if frame_id == "B":
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        for cx, cy, r in ((260, 470, 120), (900, 380, 90), (1120, 600, 110)):
            sd.ellipse([cx - r, cy - r * 0.45, cx + r, cy + r * 0.45], fill=(30, 40, 60, 40))
        img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(22)))
    img = Image.alpha_composite(img, clouds_layer(pal, frame_id))
    if pal["mist"]:
        img = Image.alpha_composite(img, mist_layer(T, pal, low_tiles))
    d = ImageDraw.Draw(img)

    # ---- creatures + text (1x, screen scale)
    if frame_id == "A":
        # one sleeper who has no hut yet: curled on the riverbank by the trail
        P = Placer(T, img)
        P.place("wrenlow", (24, 4), frame="asleep", facing=-1, tier=1, sub="asleep · settled last night", dim=True)
        draw_plank(img, "14 settled here. nobody awake. say anything and yours wakes at its hearth.")
        # standing stones letters (carved, no counts at dawn)
        for letter, (k, d_) in STONES:
            x, y = ground_point(T, k, d_)
            f = font("ab", 24)
            text_shadow(d, (x - text_w(d, letter, f) // 2 - 3, y - 30), letter, f, (96, 84, 70, 255), shadow=(230, 222, 206, 200), off=1)
        draw_header(img, "14 SETTLED · 0 AWAKE", "02:41", "2 watching", bar_frac=0.9)
        draw_hud_bottom(img,
                        colony=dict(line1="14 settled · the wheel turns at 20", frac=14 / 20,
                                    line2="nobody awake · 14 asleep",
                                    line3="@kaiwren tilled 2 fields"),
                        keeper=dict(line1="no keeper on duty · plans kept",
                                    line2="built: footbridge · v0.6.1",
                                    line3="asked by @dvn_north · seed 7"),
                        chat=[(None, "chat is quiet. say anything.", None)], frame_id="A")
    else:
        # villagers
        P = Placer(T, img)
        # reserve the two world signs first so nothing lands on them
        wx, wy = ground_point(T, 20, 16)
        wheel_sign = "the wheel · turned at 20"
        f20 = font("menlo", 20)
        wsx = wx - text_w(d, wheel_sign, f20) // 2 + 30
        P.reserve((wsx - 4, wy + 12, wsx + text_w(d, wheel_sign, f20) + 4, wy + 36))
        fx_, fy_ = ground_point(T, 18, -20, 0.0, -0.9)
        field_sign = "@kaiwren's field"
        P.reserve((fx_ - text_w(d, field_sign, f20) // 2 - 4, fy_ - 36, fx_ + text_w(d, field_sign, f20) // 2 + 4, fy_ - 12))
        for (letter, (k, d_)) in STONES:
            x, y = ground_point(T, k, d_)
            P.reserve((x - 16, y - 34, x + 16, y + 28))
        # caravan first (it owns the trail), then villagers around the square, then the wanderers
        caravan = [("tessa_r", (20, 10), "walk0", "to the wheel, bring berries"), ("brigsy", (21, 5), "walk1", None), ("quill", (22, 0), "walk0", None)]
        villagers = [
            ("kaiwren", (22, -16), "idle0", 1, None),
            ("rue.exe", (28, -18), "sit0", 1, "kaiwren your wheat is huge"),
            ("junipr", (14, -14), "idle1", -1, "planting berries by the water"),
            ("mossyquill", (24, -20), "wave0", 1, None),
            ("dvn_north", (22, -10), "walk0", -1, None),
            ("pixel_tova", (18, -6), "idle1", -1, None),
            ("halcyon_b", (20, -24), "idle0", 1, None),
            ("saltmarsh", (28, -8), "walk1", 1, None),
            ("oatley", (30, -14), "idle0", 1, None),
            ("wrenlow", (24, 12), "idle0", -1, None),
            ("fennwick", (26, 4), "idle1", 1, None),   # standing at stone A: a vote you can see
        ]
        placed = {}
        order = [(n, near, fr, 1, bub, True) for n, near, fr, bub in caravan] + \
                [(n, near, fr, facing, bub, False) for n, near, fr, facing, bub in villagers]
        order.sort(key=lambda t: 0 if t[4] else 1)     # speakers first: their bubbles reserve space
        for name, near, fr, facing, bub, water in order:
            tier = 0 if name in ("wrenlow", "fennwick") else 1
            pip = P.place(name, near, frame=fr, facing=facing, tier=tier, allow_water=water)
            if pip is None:
                continue
            if bub and not P.bubble(pip, bub):
                print("bubble skipped for", name)
        d = ImageDraw.Draw(img)
        # stone letters + counts
        for (letter, (k, d_)), cnt in zip(STONES, ("4", "1", "0")):
            x, y = ground_point(T, k, d_)
            f = font("ab", 24)
            text_shadow(d, (x - text_w(d, letter, f) // 2 - 3, y - 30), letter, f, (96, 84, 70, 255), shadow=(230, 222, 206, 200), off=1)
            f2 = font("menlo", 20)
            text_shadow(d, (x - text_w(d, cnt, f2) // 2, y + 4), cnt, f2, (250, 240, 222, 255), shadow=(36, 28, 22, 220))
        # plot sign for one field ("your own space")
        text_shadow(d, (fx_ - text_w(d, field_sign, f20) // 2, fy_ - 34), field_sign, f20, name_colour("kaiwren") + (255,), shadow=(36, 28, 22, 220))
        text_shadow(d, (wsx, wy + 14), wheel_sign, f20, (250, 240, 222, 255), shadow=(36, 28, 22, 220))
        draw_plank(img, "say anything in chat. a creature hatches with your name. build, and the plot is yours.")
        draw_header(img, "22 SETTLED · 14 AWAKE", "01:23", "9 watching", bar_frac=0.46)
        draw_hud_bottom(img,
                        colony=dict(line1="22 settled · the mill opens at 30", frac=22 / 30,
                                    line2="14 awake · 8 asleep",
                                    line3="rain · picked by @rue.exe"),
                        keeper=dict(line1="keeper on duty",
                                    line2="east terrace · 12:40 left",
                                    line3="@saltmarsh asked · 3 walking"),
                        chat=[("rue.exe", "kaiwren your wheat is huge", None),
                              ("fennwick", "", "A"),
                              ("tessa_r", "to the wheel, bring berries", None),
                              ("junipr", "planting berries by the water", None)], frame_id="B")
    return img.convert("RGB")


def main():
    a = render_frame("A")
    a.save(os.path.join(OUT, "isometric_A_dawn_empty.png"), optimize=True)
    b = render_frame("B")
    b.save(os.path.join(OUT, "isometric_B_busy.png"), optimize=True)
    b.resize((320, 180), Image.LANCZOS).save(os.path.join(OUT, "isometric_thumb_320x180.png"), optimize=True)
    print("ok")


if __name__ == "__main__":
    main()
