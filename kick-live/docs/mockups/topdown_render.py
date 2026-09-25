"""topdown_render.py - concept render for the SETTLEMENT redesign (style: topdown).

Everything is procedural: value-noise terrain (elevation + moisture -> water, shore, grassland,
meadow, forest, hills), a river traced downhill from the hills to the sea, wind-bent grass, ripples,
cloud shadows, a village of huts composed from each builder's name colour, worn trails, farms and a
monument. Creatures are the real pip sprites from stream/world/pips.py (4x). No external assets.

    python docs/mockups/topdown_render.py            # writes A, B and the 320x180 thumb

CONCEPT RENDER ONLY. Names are examples. Never touches the stream.
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = "/Users/sandy/Workspace/agentic-builds/kick-live"
OUT = os.path.join(ROOT, "docs", "mockups")
sys.path.insert(0, ROOT)
from stream.world import pips  # noqa: E402

W, H = 1280, 720
HEADER_H, BAR_H = 66, 6
WY0 = HEADER_H + BAR_H          # world starts at y=72
WH = H - WY0                    # 648
TW, TH = 32, 24                 # 3/4 top-down tile: 32 wide, 24 tall
MAP_T = 256                     # tiles per side of the whole map
VTW, VTH = W // TW, WH // TH    # 40 x 27 tiles in view
SEA = 0.30
SEED = 4471
HUD_Y0, CAP_Y0 = 600, 696

MENLO = "/System/Library/Fonts/Menlo.ttc"
HN = "/System/Library/Fonts/HelveticaNeue.ttc"
AB = "/System/Library/Fonts/Supplemental/Arial Black.ttf"

CREAM = (247, 240, 226)
INK = (34, 26, 16)
MUTED = (214, 196, 160)
GOLD = (240, 190, 90)

_FONTS = {}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    key = (kind, size)
    if key not in _FONTS:
        if kind == "menlo":
            _FONTS[key] = ImageFont.truetype(MENLO, size, index=0)
        elif kind == "menlob":
            _FONTS[key] = ImageFont.truetype(MENLO, size, index=1)
        elif kind == "hn":
            _FONTS[key] = ImageFont.truetype(HN, size, index=10)  # Medium
        elif kind == "ab":
            _FONTS[key] = ImageFont.truetype(AB, size)
    return _FONTS[key]


def hex_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))


def scale(c, k):
    return tuple(max(0, min(255, int(round(v * k)))) for v in c)


# ----------------------------------------------------------------------------- noise
def _hash2(i, j, seed):
    i = i.astype(np.int64)
    j = j.astype(np.int64)
    n = (i * 374761393 + j * 668265263 + int(seed) * 1013904223) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    n = (n ^ (n >> 16)) & 0xFFFFFFFF
    return n.astype(np.float32) / np.float32(4294967295.0)


def vnoise(u, v, freq, seed):
    x = u * freq
    y = v * freq
    xi = np.floor(x)
    yi = np.floor(y)
    fx = (x - xi).astype(np.float32)
    fy = (y - yi).astype(np.float32)
    sx = fx * fx * fx * (fx * (fx * 6 - 15) + 10)
    sy = fy * fy * fy * (fy * (fy * 6 - 15) + 10)
    a = _hash2(xi, yi, seed)
    b = _hash2(xi + 1, yi, seed)
    c = _hash2(xi, yi + 1, seed)
    d = _hash2(xi + 1, yi + 1, seed)
    return (a * (1 - sx) + b * sx) * (1 - sy) + (c * (1 - sx) + d * sx) * sy


def fbm(u, v, freq, octaves, seed, gain=0.5, lac=2.0):
    total = np.zeros_like(u, dtype=np.float32)
    amp = 1.0
    norm = 0.0
    for o in range(octaves):
        total += amp * vnoise(u, v, freq, seed + o * 101)
        norm += amp
        amp *= gain
        freq *= lac
    return total / norm


def box_blur(a, r, passes=3):
    """Separable float box blur (cumsum), repeated to approximate a gaussian. No 8-bit quantisation."""
    out = a.astype(np.float32)
    for _ in range(passes):
        for axis in (0, 1):
            pad = [(0, 0), (0, 0)]
            pad[axis] = (r, r)
            p = np.pad(out, pad, mode="edge")
            c = np.cumsum(p, axis=axis, dtype=np.float32)
            c = np.concatenate([np.zeros_like(np.take(c, [0], axis=axis)), c], axis=axis)
            n = out.shape[axis]
            hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
            lo = np.take(c, np.arange(0, n), axis=axis)
            out = (hi - lo) / (2 * r + 1)
    return out


def elevation(u, v):
    base = fbm(u, v, 1 / 30.0, 2, SEED)
    g = ((MAP_T - u) + (MAP_T - v)) / (2.0 * MAP_T)     # sea to the south-east
    b = 1.0 * base + 0.45 * g - 0.26
    detail = fbm(u, v, 1 / 9.0, 3, SEED + 50) - 0.5
    land = np.clip((b - SEA) / 0.08, 0, 1)
    e = b + 0.18 * detail * land
    return np.clip(e, 0, 1).astype(np.float32)


def moisture(u, v):
    return fbm(u, v, 1 / 19.0, 4, SEED + 7000).astype(np.float32)


# ----------------------------------------------------------------------------- world model
class World:
    def __init__(self, frame: str):
        self.frame = frame
        self.evening = frame == "B"
        self.rng = np.random.RandomState(SEED + (1 if frame == "A" else 2))
        tv, tu = np.mgrid[0:MAP_T, 0:MAP_T].astype(np.float32)
        self.tu, self.tv = tu, tv
        self.E_t = elevation(tu + 0.5, tv + 0.5)
        self.M_t = moisture(tu + 0.5, tv + 0.5)
        self._sea_fields()
        su, sv = self._pick_site_world()
        self.cam = (int(np.clip(su - 18, 0, MAP_T - VTW)), int(np.clip(sv - 12, 0, MAP_T - VTH)))
        self._pixel_fields()
        self.site = (su + 0.5 - self.cam[0], sv + 0.5 - self.cam[1])
        self.river = self._trace_river()
        self._carve_river()

    def _sea_fields(self):
        """Sea = water connected to the map border; ponds are the rest. D_t = tile distance to the sea."""
        water = self.E_t < SEA
        sea = np.zeros_like(water)
        sea[0, :] = sea[-1, :] = True
        sea[:, 0] = sea[:, -1] = True
        sea &= water
        for _ in range(MAP_T):
            grown = sea.copy()
            grown[1:, :] |= sea[:-1, :]
            grown[:-1, :] |= sea[1:, :]
            grown[:, 1:] |= sea[:, :-1]
            grown[:, :-1] |= sea[:, 1:]
            grown &= water
            if (grown == sea).all():
                break
            sea = grown
        self.sea_t = sea
        self.pond_t = water & ~sea
        D = np.where(sea, 0.0, np.inf).astype(np.float32)
        front = sea.copy()
        for k in range(1, 3 * MAP_T):
            grown = front.copy()
            grown[1:, :] |= front[:-1, :]
            grown[:-1, :] |= front[1:, :]
            grown[:, 1:] |= front[:, :-1]
            grown[:, :-1] |= front[:, 1:]
            newly = grown & ~front
            if not newly.any():
                break
            D[newly] = k
            front = grown
        self.D_t = D

    def _pick_site_world(self):
        """Whole-map search: flat grassland ~9 tiles from the sea (sea to the lower-right), hills to the
        upper-left, forest close by, no ponds in the frame."""
        E, M, D = self.E_t, self.M_t, self.D_t
        tu, tv = self.tu, self.tv
        sea_y, sea_x = np.nonzero(self.sea_t)
        hill_y, hill_x = np.nonzero(E > 0.62)
        for_y, for_x = np.nonzero((M > 0.58) & (E > SEA + 0.03) & (E < 0.62))
        pond_y, pond_x = np.nonzero(self.pond_t)
        best, best_s = None, 1e9
        for ty in range(16, MAP_T - 16, 2):
            for tx in range(22, MAP_T - 22, 2):
                e = E[ty, tx]
                if e < 0.36 or e > 0.58:
                    continue
                d = D[ty, tx]
                if not (9 <= d <= 12):
                    continue
                win = E[ty - 3:ty + 4, tx - 3:tx + 4]
                slope = float(win.max() - win.min())
                if slope > 0.10:
                    continue
                if len(pond_x) and np.min(np.hypot(pond_x - tx, pond_y - ty)) < 15:
                    continue
                near = np.hypot(sea_x - tx, sea_y - ty) < 18
                if near.sum() < 30:
                    continue
                wx, wy = sea_x[near].mean() - tx, sea_y[near].mean() - ty
                if wx < 4 or wy < 3:
                    continue
                hn = ((np.hypot(hill_x - tx, hill_y - ty) < 17) & (hill_x <= tx) & (hill_y <= ty)).sum()
                if hn < 12:
                    continue
                fn = (np.hypot(for_x - tx, for_y - ty) < 13).sum()
                if fn < 40:
                    continue
                sc = slope * 6 + abs(d - 10.5) * 0.3 - min(hn, 60) * 0.01 - min(fn, 120) * 0.004
                if sc < best_s:
                    best, best_s = (tx, ty), sc
        if best is None:
            # relax: any flat coast site with sea to the lower-right
            for ty in range(16, MAP_T - 16, 2):
                for tx in range(22, MAP_T - 22, 2):
                    e = E[ty, tx]
                    if e < 0.34 or e > 0.6 or not (6 <= D[ty, tx] <= 12):
                        continue
                    near = np.hypot(sea_x - tx, sea_y - ty) < 18
                    if near.sum() < 20:
                        continue
                    wx, wy = sea_x[near].mean() - tx, sea_y[near].mean() - ty
                    if wx < 3 or wy < 2:
                        continue
                    win = E[ty - 3:ty + 4, tx - 3:tx + 4]
                    sc = float(win.max() - win.min())
                    if sc < best_s:
                        best, best_s = (tx, ty), sc
        return best or (MAP_T // 2, MAP_T // 2)

    def _pixel_fields(self):
        cx0, cy0 = self.cam
        py, px = np.mgrid[0:WH, 0:W].astype(np.float32)
        self.U = cx0 + px / TW
        self.V = cy0 + py / TH
        self.E = elevation(self.U, self.V)
        self.M = moisture(self.U, self.V)

    def _trace_river(self):
        cx0, cy0 = self.cam
        su, sv = self.site[0] + cx0, self.site[1] + cy0
        E = self.E_t
        tu, tv = self.tu, self.tv
        dd = np.hypot(tu - su, tv - sv)
        cand = (dd > 7) & (dd < 17) & (tu <= su + 2) & (tv <= sv + 1)
        if not cand.any():
            cand = (dd > 7) & (dd < 20)
        score = np.where(cand, E, -1)
        sy, sx = np.unravel_index(np.argmax(score), score.shape)
        u, v = sx + 0.5, sy + 0.5
        # target: the sea that is actually in frame (fallback: the global sea-distance field)
        e_view = E[cy0:cy0 + VTH, cx0:cx0 + VTW]
        ys, xs = np.nonzero(e_view < SEA)
        in_view_sea = len(xs) > 40
        if in_view_sea:
            sea_u, sea_v = cx0 + xs.mean(), cy0 + ys.mean()
        pts = [(u, v)]
        du, dv = 0.0, 0.0
        step = 0.5
        for _ in range(900):
            angs = np.linspace(0, 2 * math.pi, 24, endpoint=False)
            cu = u + step * np.cos(angs)
            cv = v + step * np.sin(angs)
            e = elevation(cu, cv) + 0.02 * vnoise(cu, cv, 0.7, SEED + 99)
            ti = np.clip(cv.astype(int), 0, MAP_T - 1)
            tj = np.clip(cu.astype(int), 0, MAP_T - 1)
            dsea = np.hypot(cu - sea_u, cv - sea_v) / 40.0 if in_view_sea else self.D_t[ti, tj] / 40.0
            align = np.cos(angs) * du + np.sin(angs) * dv
            dsite = np.hypot(cu - su, cv - sv)
            prev = np.array(pts[:-1]) if len(pts) > 1 else None
            revisit = np.zeros_like(cu)
            if prev is not None:
                dmin = np.min(np.hypot(cu[:, None] - prev[None, :, 0], cv[:, None] - prev[None, :, 1]), axis=1)
                revisit = np.clip(1 - dmin / 1.4, 0, 1)
            cost = e + 0.08 * dsea - 0.015 * align + 1.2 * np.clip(1 - dsite / 8.5, 0, 1) + 0.5 * revisit
            k = int(np.argmin(cost))
            nu, nv = float(cu[k]), float(cv[k])
            du, dv = (nu - u) / step, (nv - v) / step
            u, v = nu, nv
            pts.append((u, v))
            if elevation(np.array([u]), np.array([v]))[0] < SEA - 0.012:
                break
            if not (1 < u < MAP_T - 1 and 1 < v < MAP_T - 1):
                break
        return pts[6:] if len(pts) > 12 else pts

    def to_px(self, u, v):
        cx0, cy0 = self.cam
        return (u - cx0) * TW, (v - cy0) * TH

    def _carve_river(self):
        mask = Image.new("L", (W, WH), 0)
        d = ImageDraw.Draw(mask)
        n = len(self.river)
        for i in range(n - 1):
            a = self.to_px(*self.river[i])
            b = self.to_px(*self.river[i + 1])
            t = i / max(1, n - 1)
            wdt = int(7 + 13 * t)
            d.line([a, b], fill=255, width=wdt)
            d.ellipse([a[0] - wdt / 2, a[1] - wdt / 2, a[0] + wdt / 2, a[1] + wdt / 2], fill=255)
        field = np.asarray(mask.filter(ImageFilter.GaussianBlur(4)), dtype=np.float32) / 255.0
        self.river_field = field
        self.E = np.clip(self.E - 0.10 * np.clip(field * 1.6, 0, 1), 0, 1)
        self.water = (self.E < SEA) | (field > 0.5)
        self.river_pts_px = [self.to_px(*p) for p in self.river]

    def _pick_site(self):
        # tile-res within the scouting view: flat, grassy, 5-8 tiles from water, water to the lower-right
        E = self.E[::TH, ::TW]
        Wt = self.water[::TH, ::TW]
        best, best_s = None, 1e9
        ys, xs = np.nonzero(Wt)
        for ty in range(3, VTH - 3):
            for tx in range(3, VTW - 3):
                e = E[ty, tx]
                if e < 0.33 or e > 0.62:
                    continue
                if not len(xs):
                    continue
                dd = np.hypot(xs - tx, ys - ty)
                dwater = float(dd.min())
                if dwater < 5.0:
                    continue
                near = dd < 12
                if near.sum() < 20:
                    continue
                wx, wy = xs[near].mean() - tx, ys[near].mean() - ty
                if wx < 3 or wy < 2:
                    continue
                win = E[max(0, ty - 3):ty + 4, max(0, tx - 3):tx + 4]
                slope = float(win.max() - win.min())
                s = slope * 6 + abs(dwater - 6.5) * 0.5
                if s < best_s:
                    best, best_s = (tx + 0.5, ty + 0.5), s
        if best is None:
            best = (VTW / 2 + 0.5, 13.5)
        return best  # view-tile coords

    def dry_box(self, x0, y0, x1, y1, margin=14):
        """True when a screen box (world px) holds no water or river bank (exact, every pixel)."""
        xa, xb = int(np.clip(x0 - margin, 0, W - 1)), int(np.clip(x1 + margin, 1, W))
        ya, yb = int(np.clip(y0 - margin, 0, WH - 1)), int(np.clip(y1 + margin, 1, WH))
        if xb <= xa or yb <= ya:
            return False
        sub = self.water[ya:yb, xa:xb] | (self.river_field[ya:yb, xa:xb] > 0.12)
        return not sub.any()

    def dry_segment(self, x0, y0, x1, y1):
        n = max(2, int(math.hypot(x1 - x0, y1 - y0) / 6))
        for i in range(n + 1):
            t = i / n
            xi = int(np.clip(x0 + (x1 - x0) * t, 0, W - 1))
            yi = int(np.clip(y0 + (y1 - y0) * t, 0, WH - 1))
            if self.water[yi, xi] or self.river_field[yi, xi] > 0.3:
                return False
        return True

    def site_px(self):
        return self.site[0] * TW, self.site[1] * TH

    def px_water(self, x, y):
        xi, yi = int(np.clip(x, 0, W - 1)), int(np.clip(y, 0, WH - 1))
        return bool(self.water[yi, xi])


# ----------------------------------------------------------------------------- terrain paint
def paint_terrain(w: World) -> np.ndarray:
    E, M = w.E, w.M
    mott = fbm(w.U, w.V, 1.7, 2, SEED + 300) - 0.5
    dry = np.array(hex_rgb("#A9B25E"), np.float32)
    lush = np.array(hex_rgb("#5C9A41"), np.float32)
    mid = np.array(hex_rgb("#7FAE4E"), np.float32)
    t = np.clip((M - 0.30) / 0.45, 0, 1)[..., None]
    grass = dry * (1 - t) + mid * t
    t2 = np.clip((M - 0.55) / 0.30, 0, 1)[..., None]
    grass = grass * (1 - t2) + lush * t2
    grass *= (1 + 0.14 * mott[..., None])
    # hills
    hill = np.array(hex_rgb("#7E8F58"), np.float32)
    rock = np.array(hex_rgb("#76735F"), np.float32)
    th = np.clip((E - 0.60) / 0.10, 0, 1)[..., None]
    col = grass * (1 - th) + hill * th
    tr = np.clip((E - 0.70) / 0.08, 0, 1)[..., None]
    col = col * (1 - tr) + rock * tr
    speck = 0.55 * np.clip((fbm(w.U, w.V, 2.6, 2, SEED + 610) - 0.62) / 0.12, 0, 1) * np.clip((E - 0.66) / 0.06, 0, 1)
    col = col * (1 - speck[..., None]) + rock * 0.92 * speck[..., None]
    # stepped terraces on the high ground (the 3/4 RTS elevation read)
    q = ((E - 0.58) / 0.045) % 1.0
    edge = np.clip((0.10 - q) / 0.10, 0, 1) * np.clip((E - 0.58) / 0.03, 0, 1)
    col = col * (1 - 0.16 * edge[..., None])
    # shore sand
    sand = np.array(hex_rgb("#E6D5A2"), np.float32)
    ts = np.clip(1 - (E - SEA) / 0.035, 0, 1)[..., None]
    col = col * (1 - ts) + sand * ts
    rb = np.clip((w.river_field - 0.30) / 0.20, 0, 1)[..., None]
    col = col * (1 - rb) + sand * rb
    # water
    shallow = np.array(hex_rgb("#6FB3CF"), np.float32)
    deep = np.array(hex_rgb("#2F6F9E"), np.float32)
    depth = np.clip((SEA - E) / 0.10, 0, 1)
    depth = np.maximum(depth, np.clip((w.river_field - 0.5) / 0.4, 0, 1) * 0.55)
    wcol = shallow * (1 - depth[..., None]) + deep * depth[..., None]
    wm = w.water[..., None]
    col = np.where(wm, wcol, col)
    # relief: light from top-left
    Eb = box_blur(E, 4)
    gy, gx = np.gradient(Eb)
    steep = 44.0 + 40.0 * np.clip((Eb - 0.52) / 0.12, 0, 1)
    shade = 1.0 + steep * (-gx * (TW / 8.0) - gy * (TH / 8.0))
    shade = np.clip(shade, 0.66, 1.26)
    shade = np.where(w.water, 1.0, shade)
    col = col * shade[..., None]
    # ripples
    rip = np.sin(w.U * 9.0 + w.V * 4.0 + 6 * vnoise(w.U, w.V, 0.9, SEED + 5))
    rip2 = np.sin(w.U * 3.0 - w.V * 11.0 + 5 * vnoise(w.U, w.V, 1.3, SEED + 6))
    glint = np.clip((rip - 0.86) / 0.14, 0, 1) * 34 + np.clip((rip2 - 0.90) / 0.10, 0, 1) * 22
    col = np.where(wm, col + glint[..., None] * np.array([1.0, 1.0, 0.92]), col)
    # foam line at the water edge
    wf = np.asarray(Image.fromarray((w.water * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2)),
                    np.float32) / 255.0
    foam = np.clip(1 - np.abs(wf - 0.5) / 0.22, 0, 1) ** 2
    col = col * (1 - 0.55 * foam[..., None]) + np.array([236, 244, 240], np.float32) * (0.55 * foam[..., None])
    # dither
    col += (w.rng.rand(*col.shape) - 0.5) * 3.0
    return np.clip(col, 0, 255)


def draw_grass_and_flowers(img: Image.Image, w: World, n_tufts=6500):
    d = ImageDraw.Draw(img, "RGBA")
    rng = np.random.RandomState(SEED + 11)
    xs = rng.randint(0, W, n_tufts)
    ys = rng.randint(0, WH, n_tufts)
    wind = fbm(w.U[ys, xs], w.V[ys, xs], 1 / 7.0, 2, SEED + 900)
    for x, y, wd in zip(xs, ys, wind):
        if w.water[y, x] or w.E[y, x] > 0.68 or w.river_field[y, x] > 0.2:
            continue
        m = w.M[y, x]
        if rng.rand() > 0.35 + m * 0.7:
            continue
        lean = 1.5 + 4.5 * wd
        base = img.getpixel((x, y))[:3]
        light = scale(base, 1.34)
        dark = scale(base, 0.76)
        hgt = 5 + int(4 * m)
        d.line([(x, y), (x + lean, y - hgt)], fill=light + (200,), width=1)
        d.line([(x - 2, y), (x - 2 + lean * 0.7, y - hgt + 1)], fill=dark + (170,), width=1)
        d.line([(x + 2, y), (x + 2 + lean * 1.2, y - hgt + 2)], fill=light + (150,), width=1)
    # flowers in mid-moisture meadows
    fl = [(244, 170, 200), (250, 226, 120), (246, 246, 236), (200, 170, 240)]
    for i in range(1400):
        x, y = rng.randint(0, W), rng.randint(0, WH)
        if w.water[y, x] or w.river_field[y, x] > 0.2 or w.E[y, x] > 0.62:
            continue
        m = w.M[y, x]
        if 0.40 < m < 0.62 and rng.rand() < 0.75:
            c = fl[rng.randint(0, len(fl))]
            d.ellipse([x - 1, y - 1, x + 1, y + 1], fill=c + (230,))


def draw_cloud_shadows(img: Image.Image, w: World):
    lay = Image.new("L", (W, WH), 0)
    d = ImageDraw.Draw(lay)
    rng = np.random.RandomState(SEED + 21 + (3 if w.evening else 0))
    for i in range(4):
        cx, cy = rng.randint(-100, W + 100), rng.randint(-60, WH + 60)
        for k in range(7):
            rx, ry = rng.randint(60, 150), rng.randint(25, 60)
            ox, oy = rng.randint(-120, 120), rng.randint(-40, 40)
            d.ellipse([cx + ox - rx, cy + oy - ry, cx + ox + rx, cy + oy + ry], fill=255)
    lay = lay.filter(ImageFilter.GaussianBlur(22))
    a = np.asarray(lay, np.float32) / 255.0
    arr = np.asarray(img, np.float32)
    arr = arr * (1 - 0.16 * a[..., None])
    img.paste(Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)))
    return lay


# ----------------------------------------------------------------------------- objects
class Scene:
    def __init__(self, w: World):
        self.w = w
        self.items = []     # (sort_y, callable)
        self.rng = np.random.RandomState(SEED + 77)
        self.shadow_dx, self.shadow_dy = (1.7, 0.6) if not w.evening else (1.5, 0.6)

    def add(self, y, fn):
        self.items.append((y, fn))

    def draw_all(self, img):
        for _, fn in sorted(self.items, key=lambda t: t[0]):
            fn(img)


def shadow_ellipse(d, x, y, rx, ry, sc, alpha=80):
    dx, dy = sc.shadow_dx, sc.shadow_dy
    d.ellipse([x - rx + rx * dx * 0.6, y - ry * 0.7 + ry * dy, x + rx + rx * dx * 0.6, y + ry * 0.7 + ry * dy],
              fill=(30, 22, 10, alpha))


def tree(sc: Scene, x, y, kind, size, tone):
    def fn(img):
        d = ImageDraw.Draw(img, "RGBA")
        shadow_ellipse(d, x + size * 0.35, y + 3, size * 0.95, size * 0.38, sc, 48)
        trunk = (92, 64, 40, 255)
        d.rectangle([x - 2, y - size * 0.3, x + 2, y + 1], fill=trunk)
        base = tone
        hi = scale(base, 1.28)
        lo = scale(base, 0.72)
        if kind == 0:   # broadleaf: 3 overlapping blobs
            for ox, oy, r in ((0, -size * 0.75, size * 0.62), (-size * 0.42, -size * 0.45, size * 0.5),
                              (size * 0.42, -size * 0.5, size * 0.52)):
                d.ellipse([x + ox - r, y + oy - r * 0.85, x + ox + r, y + oy + r * 0.85], fill=lo + (255,))
            for ox, oy, r in ((0, -size * 0.8, size * 0.52), (-size * 0.38, -size * 0.5, size * 0.4),
                              (size * 0.4, -size * 0.55, size * 0.42)):
                d.ellipse([x + ox - r, y + oy - r * 0.85, x + ox + r, y + oy + r * 0.85], fill=base + (255,))
            r = size * 0.36
            d.ellipse([x - r - size * 0.2, y - size * 1.05 - r * 0.7, x + r - size * 0.2, y - size * 1.05 + r * 0.7],
                      fill=hi + (255,))
        else:           # conifer: stacked wedges, lit left
            for i, (wd, top, bot) in enumerate(((0.55, -1.7, -1.0), (0.75, -1.25, -0.55), (0.95, -0.8, -0.05))):
                pts = [(x, y + top * size), (x - wd * size, y + bot * size), (x + wd * size, y + bot * size)]
                d.polygon(pts, fill=lo + (255,))
                pts2 = [(x, y + top * size), (x - wd * size, y + bot * size), (x, y + bot * size)]
                d.polygon(pts2, fill=base + (255,))
                pts3 = [(x, y + top * size), (x - wd * size * 0.55, y + (bot - 0.15) * size), (x, y + (bot - 0.25) * size)]
                d.polygon(pts3, fill=hi + (255,))
    sc.add(y, fn)


def rock(sc: Scene, x, y, size):
    def fn(img):
        d = ImageDraw.Draw(img, "RGBA")
        shadow_ellipse(d, x + size * 0.4, y + 1, size * 0.9, size * 0.4, sc, 70)
        pts = [(x - size, y), (x - size * 0.5, y - size * 0.8), (x + size * 0.3, y - size * 0.9),
               (x + size, y - size * 0.2), (x + size * 0.7, y + size * 0.3), (x - size * 0.6, y + size * 0.3)]
        d.polygon(pts, fill=(128, 124, 112, 255))
        d.polygon([(x - size, y), (x - size * 0.5, y - size * 0.8), (x + size * 0.3, y - size * 0.9), (x, y - size * 0.2)],
                  fill=(178, 174, 160, 255))
    sc.add(y, fn)


def hut(sc: Scene, x, y, name, awake, building=False, tag=None, label=None):
    """A hut composed from the builder's name: base shape, roof style, door side, chimney, pennant."""
    col = hex_rgb(pips.colour_hex(name.lower(), "kick"))
    h = pips.name_hash(name.lower())
    wall = hex_rgb(("#CFAE82", "#C39B6E", "#B8906A", "#D6B98F")[h % 4])
    roof_style = (h >> 3) % 3        # 0 pitched, 1 cone (round base), 2 flat with parapet
    bw = 58 + (h >> 6) % 16          # base width
    bh = 22 + (h >> 9) % 8           # front-wall height
    door_left = ((h >> 12) & 1) == 0
    chimney = ((h >> 13) & 1) == 0
    roof = mix(col, (120, 90, 60), 0.28)
    roof_hi = scale(roof, 1.22)
    roof_lo = scale(roof, 0.70)

    def fn(img):
        d = ImageDraw.Draw(img, "RGBA")
        # ground shadow (long, to the lower right)
        d.polygon([(x - bw * 0.5, y), (x + bw * 0.5, y), (x + bw * 0.5 + bw * 0.45 * sc.shadow_dx, y + bh * 0.5 * sc.shadow_dy + 8),
                   (x - bw * 0.5 + bw * 0.45 * sc.shadow_dx, y + bh * 0.5 * sc.shadow_dy + 8)], fill=(30, 22, 10, 75))
        if building:
            # frame only: posts and two beams, a pile of logs
            post = (110, 78, 46, 255)
            for px_ in (x - bw * 0.5, x + bw * 0.5):
                d.rectangle([px_ - 2, y - bh - 14, px_ + 2, y], fill=post)
            d.line([(x - bw * 0.5, y - bh - 12), (x, y - bh - 26), (x + bw * 0.5, y - bh - 12)], fill=post, width=4)
            d.line([(x - bw * 0.5, y - bh), (x + bw * 0.5, y - bh)], fill=post, width=3)
            for i in range(3):
                d.rounded_rectangle([x - bw * 0.25 + i * 3, y + 4 + i * 4, x + bw * 0.25 + i * 3, y + 10 + i * 4],
                                    3, fill=(122, 86, 52, 255), outline=(80, 56, 32, 255))
            return
        # front wall (3/4 view shows one face)
        d.rectangle([x - bw * 0.5, y - bh, x + bw * 0.5, y], fill=wall + (255,), outline=scale(wall, 0.6) + (255,))
        # plank lines
        for i in range(1, 4):
            yy = y - bh + i * bh / 4
            d.line([(x - bw * 0.5 + 1, yy), (x + bw * 0.5 - 1, yy)], fill=scale(wall, 0.85) + (255,), width=1)
        # door
        dx0 = x - bw * 0.5 + 6 if door_left else x + bw * 0.5 - 16
        d.rectangle([dx0, y - bh * 0.75, dx0 + 10, y], fill=(78, 54, 34, 255))
        if awake:
            d.rectangle([dx0 + 2, y - bh * 0.7, dx0 + 8, y - bh * 0.35], fill=(255, 205, 120, 255))
        # roof
        rt = y - bh
        if roof_style == 0:
            ov = 5
            d.polygon([(x - bw * 0.5 - ov, rt), (x + bw * 0.5 + ov, rt), (x + bw * 0.5 + ov, rt - 10), (x, rt - 26),
                       (x - bw * 0.5 - ov, rt - 10)], fill=roof_lo + (255,))
            d.polygon([(x - bw * 0.5 - ov, rt), (x, rt), (x, rt - 26), (x - bw * 0.5 - ov, rt - 10)], fill=roof + (255,))
            d.polygon([(x - bw * 0.5 - ov, rt - 10), (x, rt - 26), (x - bw * 0.15, rt - 21), (x - bw * 0.5 - ov + 6, rt - 11)],
                      fill=roof_hi + (255,))
            d.line([(x - bw * 0.5 - ov, rt), (x + bw * 0.5 + ov, rt)], fill=scale(roof, 0.5) + (255,), width=2)
        elif roof_style == 1:
            ov = 6
            d.polygon([(x - bw * 0.5 - ov, rt), (x + bw * 0.5 + ov, rt), (x, rt - 30)], fill=roof_lo + (255,))
            d.polygon([(x - bw * 0.5 - ov, rt), (x + 4, rt), (x, rt - 30)], fill=roof + (255,))
            d.polygon([(x - bw * 0.5 - ov + 8, rt - 3), (x - bw * 0.2, rt - 6), (x - 2, rt - 26)], fill=roof_hi + (255,))
            d.ellipse([x - bw * 0.5 - ov, rt - 5, x + bw * 0.5 + ov, rt + 5], outline=scale(roof, 0.5) + (255,), width=2)
        else:
            ov = 3
            d.polygon([(x - bw * 0.5 - ov, rt), (x + bw * 0.5 + ov, rt), (x + bw * 0.5 + ov - 6, rt - 14), (x - bw * 0.5 - ov + 6, rt - 14)],
                      fill=roof + (255,))
            d.polygon([(x - bw * 0.5 - ov, rt), (x - bw * 0.5 - ov + 6, rt - 14), (x - bw * 0.1, rt - 14), (x - bw * 0.1, rt)],
                      fill=roof_hi + (255,))
            d.rectangle([x - bw * 0.5 - ov + 6, rt - 17, x + bw * 0.5 + ov - 6, rt - 13], fill=roof_lo + (255,))
        if chimney:
            cx = x + bw * 0.3
            d.rectangle([cx - 3, rt - 18, cx + 3, rt - 6], fill=(120, 110, 100, 255))
            if awake:
                for i, r in enumerate((3, 4, 5)):
                    d.ellipse([cx - r + i * 3, rt - 24 - i * 8 - r, cx + r + i * 3, rt - 24 - i * 8 + r], fill=(235, 232, 226, 120 - i * 30))
        # pennant in the builder's colour
        px_ = x - bw * 0.5 - 8
        d.line([(px_, y), (px_, y - bh - 20)], fill=(90, 70, 50, 255), width=2)
        d.polygon([(px_, y - bh - 20), (px_ + 14, y - bh - 15), (px_, y - bh - 10)], fill=col + (255,))
        if label:
            text_stroke(d, (x, y + 6), label, font("menlo", 20), col, anchor="mt")
    sc.add(y, fn)


def farm(sc: Scene, x, y, cols, rows, grown, name):
    col = hex_rgb(pips.colour_hex(name.lower(), "kick"))

    def fn(img):
        d = ImageDraw.Draw(img, "RGBA")
        pw, ph = cols * TW, rows * TH
        x0, y0 = x - pw / 2, y - ph
        d.rectangle([x0 - 4, y0 - 4, x0 + pw + 4, y0 + ph + 4], fill=(150, 118, 78, 200))
        for r in range(int(ph // 6)):
            yy = y0 + r * 6
            c = (139, 106, 68) if r % 2 == 0 else (165, 128, 84)
            d.rectangle([x0, yy, x0 + pw, yy + 5], fill=c + (255,))
            if r % 2 == 1 and grown > 0:
                for k in range(int(pw // 9)):
                    xx = x0 + 4 + k * 9
                    if (k * 7 + r * 3) % 5 < grown:
                        d.ellipse([xx - 2, yy - 1, xx + 2, yy + 3], fill=(110, 170, 70, 255))
                        d.line([(xx, yy + 1), (xx + 2, yy - 3)], fill=(140, 200, 90, 255), width=1)
        # fence posts
        for k in range(0, int(pw) + 1, 16):
            for yy in (y0 - 4, y0 + ph + 4):
                d.rectangle([x0 + k - 1, yy - 7, x0 + k + 1, yy], fill=(112, 84, 52, 255))
            d.line([(x0, y0 - 8), (x0 + pw, y0 - 8)], fill=(112, 84, 52, 255), width=2)
            d.line([(x0, y0 + ph), (x0 + pw, y0 + ph)], fill=(112, 84, 52, 255), width=2)
        # owner pennant
        d.line([(x0 + pw + 8, y0 + ph + 4), (x0 + pw + 8, y0 + ph - 20)], fill=(90, 70, 50, 255), width=2)
        d.polygon([(x0 + pw + 8, y0 + ph - 20), (x0 + pw + 20, y0 + ph - 16), (x0 + pw + 8, y0 + ph - 12)], fill=col + (255,))
    sc.add(y - rows * TH, fn)   # farms lie flat: draw early


def monument(sc: Scene, x, y, raised_by):
    def fn(img):
        d = ImageDraw.Draw(img, "RGBA")
        # long shadow
        d.polygon([(x - 9, y), (x + 9, y), (x + 9 + 46 * sc.shadow_dx, y + 22 * sc.shadow_dy), (x - 9 + 46 * sc.shadow_dx, y + 22 * sc.shadow_dy)],
                  fill=(30, 22, 10, 80))
        # pebble ring
        for k in range(14):
            a = k / 14 * 2 * math.pi
            px_, py_ = x + 34 * math.cos(a), y + 14 * math.sin(a) + 4
            d.ellipse([px_ - 3, py_ - 2, px_ + 3, py_ + 2], fill=(200, 196, 184, 255))
        # plinth
        d.ellipse([x - 20, y - 6, x + 20, y + 8], fill=(150, 146, 134, 255), outline=(110, 106, 96, 255))
        # standing stone: lit left face, dark right face, top
        d.polygon([(x - 9, y), (x - 8, y - 58), (x - 2, y - 66), (x + 1, y - 64), (x + 1, y)], fill=(190, 186, 172, 255))
        d.polygon([(x + 1, y - 64), (x + 8, y - 56), (x + 9, y), (x + 1, y)], fill=(120, 116, 106, 255))
        d.line([(x - 8, y - 58), (x - 2, y - 66)], fill=(220, 216, 204, 255), width=2)
        # carved marks: one notch per settler who raised it
        for k in range(raised_by):
            yy = y - 12 - k * 5
            d.line([(x - 6, yy), (x - 1, yy)], fill=(120, 116, 106, 255), width=1)
        text_stroke(d, (x, y + 12), "FIRST STONE · raised by %d" % raised_by, font("menlo", 20), CREAM, anchor="mt")
    sc.add(y, fn)


def vote_stones(sc: Scene, x, y, counts, voters):
    """Three flat stones; each vote is a pennant in the voter's colour planted at the stone."""
    def fn(img):
        d = ImageDraw.Draw(img, "RGBA")
        for i, (letter, n) in enumerate(zip("ABC", counts)):
            sx = x + (i - 1) * 118
            shadow_ellipse(d, sx + 8, y + 2, 34, 14, sc, 70)
            d.ellipse([sx - 34, y - 14, sx + 34, y + 12], fill=(142, 138, 126, 255), outline=(96, 92, 84, 255), width=2)
            d.ellipse([sx - 30, y - 14, sx + 22, y + 2], fill=(176, 172, 158, 255))
            text_stroke(d, (sx, y - 3), letter, font("ab", 30), (58, 54, 48), stroke=0, anchor="mm")
            # pennants around the stone, one per real voter
            rng = np.random.RandomState(SEED + 500 + i)
            for k in range(n):
                a = -0.2 + k * (2 * math.pi / max(n, 6)) + rng.rand() * 0.3
                px_, py_ = sx + 46 * math.cos(a), y + 20 * math.sin(a) - 2
                c = hex_rgb(pips.colour_hex(voters[i][k % len(voters[i])].lower(), "kick"))
                d.line([(px_, py_), (px_, py_ - 16)], fill=(90, 70, 50, 255), width=2)
                d.polygon([(px_, py_ - 16), (px_ + 9, py_ - 13), (px_, py_ - 9)], fill=c + (255,))
            text_stroke(d, (sx, y + 28), "%d" % n, font("menlo", 22), CREAM, anchor="mt")
    sc.add(y, fn)


def creature(sc: Scene, x, y, name, frame="idle0", facing=1, tier=1, carry=None, label=True, dim=False):
    nl = name.lower()
    g, salt = pips.resolve_genome(nl, preset="kick")
    rgb, mask = pips.sprite(nl, salt, tier=tier, frame=frame, preset="kick", facing=facing)
    col = hex_rgb(pips.colour_hex(nl, "kick"))
    S = 4
    sp = np.zeros((rgb.shape[0], rgb.shape[1], 4), np.uint8)
    sp[..., :3] = rgb
    sp[..., 3] = mask.astype(np.uint8) * 255
    if dim:
        sp[..., :3] = (sp[..., :3] * 0.72).astype(np.uint8)
    im = Image.fromarray(sp).resize((rgb.shape[1] * S, rgb.shape[0] * S), Image.NEAREST)
    sw, sh = im.size
    rows = np.nonzero(mask.any(axis=1))[0]
    top = int(rows[0]) * S if len(rows) else 0
    vis_h = sh - top - 4          # visible sprite height above the feet line
    label_y = y - vis_h - (18 if carry else 4)

    def fn(img):
        d = ImageDraw.Draw(img, "RGBA")
        shadow_ellipse(d, x + 4, y + 2, sw * 0.45, 6, sc, 70)
        img.paste(im, (int(x - sw / 2), int(y - sh + 4)), im)
        ty_ = y - vis_h
        if carry == "log":
            d.rounded_rectangle([x - 16, ty_ - 10, x + 16, ty_ - 2], 4, fill=(122, 86, 52, 255), outline=(80, 56, 32, 255))
        elif carry == "pot":
            d.ellipse([x - 7, ty_ - 13, x + 7, ty_ - 1], fill=(90, 150, 200, 255), outline=(50, 90, 130, 255))
        elif carry == "hammer":
            d.line([(x + 4, ty_ - 2), (x + 12, ty_ - 16)], fill=(110, 80, 50, 255), width=3)
            d.rectangle([x + 8, ty_ - 20, x + 18, ty_ - 12], fill=(140, 140, 140, 255))
        if label:
            txt = "@" + name + (" · asleep" if frame.startswith("asleep") else "")
            text_stroke(d, (x, label_y), txt, font("menlo", 20), scale(col, 0.6) if dim else col, anchor="mb")
    sc.add(y, fn)
    return (x, label_y - 24)


# ----------------------------------------------------------------------------- text helpers
def text_stroke(d, xy, txt, f, fill, stroke=2, anchor="la", stroke_fill=(28, 20, 12)):
    d.text(xy, txt, font=f, fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=stroke_fill)


_BUBBLE_RECTS = []      # placed bubbles
_KEEP_OUT = []          # huts, plaza, stones: bubbles never cover these


def _hits(x0, y0, x1, y1):
    for r in _BUBBLE_RECTS + _KEEP_OUT:
        if not (x1 < r[0] or x0 > r[2] or y1 < r[1] or y0 > r[3]):
            return True
    return False


def bubble(img, anchor_xy, txt, maxw=330):
    d = ImageDraw.Draw(img, "RGBA")
    f = font("menlo", 22)
    words = txt.split()
    lines, cur = [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if d.textlength(t, font=f) > maxw - 24 and cur:
            lines.append(cur)
            cur = wd
        else:
            cur = t
    lines.append(cur)
    lw = max(d.textlength(l, font=f) for l in lines)
    bw, bh = lw + 24, len(lines) * 27 + 14
    ax, ay = anchor_xy
    cands = []
    for dy in (6, -30, -66, 60, -100, 100, -140, -190):
        for dx in (18, 60, 110, 170):
            cands.append((ax + dx, max(16, ay - bh + dy), True))
            cands.append((ax - bw - dx, max(16, ay - bh + dy), False))
        cands.append((ax - bw / 2, max(16, ay - bh + dy - 30), True))
    pick = None
    for x0, y0, right in cands:
        if x0 < 8 or x0 + bw > W - 8 or y0 + bh > HUD_Y0 - WY0 - 8:
            continue
        if not _hits(x0, y0, x0 + bw, y0 + bh):
            pick = (x0, y0, right)
            break
    if pick is None:
        x0 = ax + 18 if ax + 18 + bw < W - 8 else ax - bw - 18
        pick = (x0, max(16, ay - bh + 6), x0 > ax)
    x0, y0, right = pick
    _BUBBLE_RECTS.append((x0, y0, x0 + bw, y0 + bh))
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], 8, fill=(251, 244, 230, 240), outline=(59, 46, 30, 255), width=2)
    cx = x0 + 10 if right else x0 + bw - 10
    d.polygon([(cx, y0 + bh - 12), (cx + (14 if right else -14), y0 + bh - 4), (ax, ay + 6)], fill=(251, 244, 230, 240))
    d.line([(cx, y0 + bh - 12), (ax, ay + 6), (cx + (14 if right else -14), y0 + bh - 4)], fill=(59, 46, 30, 255), width=2)
    for i, l in enumerate(lines):
        d.text((x0 + 12, y0 + 8 + i * 27), l, font=f, fill=INK)


def chip(img, xy, txt, f, fill=CREAM, pad=10, bg=(34, 26, 16, 165)):
    d = ImageDraw.Draw(img, "RGBA")
    tw = d.textlength(txt, font=f)
    x, y = xy
    hgt = f.size + pad
    d.rounded_rectangle([x, y, x + tw + pad * 2, y + hgt + 2], 7, fill=bg)
    d.text((x + pad, y + pad / 2 + 1), txt, font=f, fill=fill)
    return tw + pad * 2, hgt + 2


# ----------------------------------------------------------------------------- trails
def draw_trails(img, w: World, paths, plaza=None, plaza_r=0.0):
    lay = Image.new("RGBA", (W, WH), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    rng = np.random.RandomState(SEED + 33)
    if plaza is not None:
        px_, py_ = plaza
        d.ellipse([px_ - plaza_r, py_ - plaza_r * 0.72, px_ + plaza_r, py_ + plaza_r * 0.72], fill=(176, 146, 100, 200))
    for pts, use in paths:
        # wobble the polyline
        wob = []
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 18))
            for k in range(n):
                t = k / n
                x = a[0] + (b[0] - a[0]) * t + rng.randn() * 2.2
                y = a[1] + (b[1] - a[1]) * t + rng.randn() * 1.6
                wob.append((x, y))
        wob.append(pts[-1])
        d.line(wob, fill=(176, 146, 100, int(90 + 110 * use)), width=int(8 + 8 * use), joint="curve")
        d.line(wob, fill=(196, 166, 118, int(60 + 80 * use)), width=int(3 + 3 * use), joint="curve")
    lay = lay.filter(ImageFilter.GaussianBlur(1.6))
    img.paste(lay, (0, 0), lay)


# ----------------------------------------------------------------------------- overlays
def time_grade(img: Image.Image, w: World):
    arr = np.asarray(img.convert("RGB"), np.float32)
    py, px = np.mgrid[0:WH, 0:W].astype(np.float32)
    if not w.evening:
        # dawn: gold from the top-left, cool blue in the far right, mist in the low ground
        glow = np.clip(1 - np.hypot(px / W, py / WH) / 0.9, 0, 1) ** 1.6
        arr = arr * np.array([0.94, 0.93, 0.98]) + glow[..., None] * np.array([62, 36, 0])
        cool = np.clip((px / W - 0.45) / 0.55, 0, 1) ** 1.4
        arr = arr + cool[..., None] * np.array([-8, 2, 18])
        mist = np.clip((0.37 - w.E) / 0.10, 0, 1) * (0.45 + 0.55 * fbm(w.U, w.V, 1 / 5.0, 2, SEED + 41))
        mist = np.asarray(Image.fromarray((np.clip(mist, 0, 1) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(9)),
                          np.float32) / 255.0 * 0.22
        arr = arr * (1 - mist[..., None]) + np.array([236, 236, 240]) * mist[..., None]
    else:
        # evening: amber from the top-left, violet in the shadowed east, warmer overall
        glow = np.clip(1 - np.hypot(px / W, (py / WH) * 0.8) / 0.95, 0, 1) ** 1.6
        arr = arr * np.array([0.96, 0.87, 0.78]) + glow[..., None] * np.array([34, 10, -8])
        vio = np.clip((px / W - 0.35) / 0.65, 0, 1) ** 1.3
        arr = arr * (1 - 0.10 * vio[..., None]) + vio[..., None] * np.array([4, -6, 26])
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def draw_cloud_wisps(img, lay):
    a = (np.asarray(lay, np.float32) / 255.0)
    wisps = np.roll(np.roll(a, -90, axis=1), -60, axis=0) * 0.16
    arr = np.asarray(img.convert("RGB"), np.float32)
    arr = arr * (1 - wisps[..., None]) + 255 * wisps[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def minimap(img, w: World, explored_centres, explored_r, village_px):
    size = 128
    scl = size / MAP_T
    E, M = w.E_t, w.M_t
    col = np.zeros((MAP_T, MAP_T, 3), np.float32)
    col[:] = hex_rgb("#8FB552")
    col[M > 0.58] = hex_rgb("#4F8A3C")
    col[E > 0.62] = hex_rgb("#A7A67E")
    col[E > 0.74] = hex_rgb("#8B8676")
    col[(E >= SEA) & (E < SEA + 0.03)] = hex_rgb("#E6D5A2")
    col[E < SEA] = hex_rgb("#3F80AE")
    tv, tu = np.mgrid[0:MAP_T, 0:MAP_T].astype(np.float32)
    expl = np.zeros((MAP_T, MAP_T), bool)
    for (cu, cv), r in zip(explored_centres, explored_r):
        expl |= np.hypot(tu - cu, tv - cv) < r
    cx0, cy0 = w.cam
    expl[cy0:cy0 + VTH, cx0:cx0 + VTW] = True
    for (u, v) in w.river[::4]:
        expl |= np.hypot(tu - u, tv - v) < 3.0
    parch = np.array(hex_rgb("#E4D9C0"), np.float32)
    hatch = ((tu + tv) % 6 < 1.0)
    unexp = np.where(hatch[..., None], parch * 0.93, parch)
    out = np.where(expl[..., None], col, unexp)
    # soft edge of the explored area
    em = Image.fromarray((expl * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2))
    ea = np.asarray(em, np.float32)[..., None] / 255.0
    out = out * ea + unexp * (1 - ea)
    vu, vv = village_px[0] / TW + cx0, village_px[1] / TH + cy0
    wx0 = int(np.clip(vu - size / 2, 0, MAP_T - size))
    wy0 = int(np.clip(vv - size / 2, 0, MAP_T - size))
    mm = Image.fromarray(out[wy0:wy0 + size, wx0:wx0 + size].astype(np.uint8)).convert("RGBA")
    scl = 1.0
    cx0, cy0 = cx0 - wx0, cy0 - wy0
    vu, vv = vu - wx0, vv - wy0
    x0, y0 = W - size - 16, WY0 + 14
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([x0 - 14, y0 - 6, x0 + size + 14, y0 + size + 36], 8, fill=(34, 26, 16, 165))
    img.paste(mm, (x0, y0), mm)
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([x0, y0, x0 + size - 1, y0 + size - 1], outline=(59, 46, 30, 255), width=2)
    d.rectangle([x0 + cx0 * scl, y0 + cy0 * scl, x0 + (cx0 + VTW) * scl, y0 + (cy0 + VTH) * scl], outline=(255, 255, 255, 230), width=1)
    d.ellipse([x0 + vu * scl - 2, y0 + vv * scl - 2, x0 + vu * scl + 2, y0 + vv * scl + 2], fill=(255, 235, 120, 255))
    pct = 100.0 * expl.mean()
    d.text((x0 + size / 2, y0 + size + 6), "%.0f%% explored" % pct, font=font("menlo", 20), fill=CREAM, anchor="mt")


def time_dial(img, xy, evening):
    x, y = xy
    r = 30
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([x - 6, y - 6, x + 2 * r + 6, y + 2 * r + 6], 8, fill=(34, 26, 16, 165))
    disc = Image.new("RGBA", (2 * r, 2 * r), (0, 0, 0, 0))
    arr = np.zeros((2 * r, 2 * r, 4), np.uint8)
    yy = np.linspace(0, 1, 2 * r)[:, None, None]
    if not evening:
        top, bot = np.array([120, 160, 220]), np.array([255, 196, 130])
    else:
        top, bot = np.array([70, 60, 130]), np.array([250, 140, 80])
    grad = top[None, None, :] * (1 - yy) + bot[None, None, :] * yy
    arr[..., :3] = np.repeat(grad, 2 * r, axis=1)
    arr[..., 3] = 255
    disc = Image.fromarray(arr)
    dd = ImageDraw.Draw(disc, "RGBA")
    if not evening:
        dd.ellipse([12, r - 4, 28, r + 12], fill=(255, 226, 140, 255))
        dd.rectangle([0, r + 8, 2 * r, 2 * r], fill=(74, 100, 50, 255))
    else:
        dd.ellipse([32, r - 8, 46, r + 6], fill=(255, 170, 80, 255))
        dd.ellipse([10, 8, 22, 20], fill=(235, 235, 225, 255))
        dd.ellipse([14, 6, 25, 17], fill=(70, 60, 130, 255))
        for (sx, sy) in ((30, 10), (40, 16), (24, 22)):
            dd.point((sx, sy), fill=(255, 255, 255, 255))
        dd.rectangle([0, r + 8, 2 * r, 2 * r], fill=(50, 70, 40, 255))
    dd.line([(0, r + 8), (2 * r, r + 8)], fill=(40, 56, 30, 255), width=2)
    m = Image.new("L", (2 * r, 2 * r), 0)
    ImageDraw.Draw(m).ellipse([0, 0, 2 * r - 1, 2 * r - 1], fill=255)
    disc.putalpha(m)
    img.paste(disc, (x, y), disc)


def header(img, left_lines, count_txt, next_txt, watching):
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, W, HEADER_H], fill=(38, 28, 18, 255))
    d.rectangle([0, HEADER_H, W, HEADER_H + BAR_H], fill=(64, 50, 34, 255))
    d.rectangle([0, HEADER_H, int(W * 0.46), HEADER_H + BAR_H], fill=GOLD)
    d.text((16, 8), left_lines[0], font=font("menlo", 20), fill=MUTED)
    d.text((16, 34), left_lines[1], font=font("hn", 22), fill=CREAM)
    # 56 px count, shrink only if it will not fit the centre band
    f = font("ab", 56)
    tw = d.textlength(count_txt, font=f)
    if tw > 660:
        f = font("ab", 50)
    d.text((W // 2 - 20, HEADER_H // 2 + 2), count_txt, font=f, fill=CREAM, anchor="mm")
    # right block: LIVE + watching, next event under it
    d.ellipse([W - 250, 14, W - 236, 28], fill=(230, 60, 60, 255))
    d.text((W - 226, 9), "LIVE · %s watching" % watching, font=font("menlo", 22), fill=CREAM)
    d.text((W - 250, 36), next_txt, font=font("menlo", 22), fill=GOLD)


def hud(img, colony, keeper, chat):
    d = ImageDraw.Draw(img, "RGBA")
    boxes = [(0, 420), (420, 420), (840, 440)]
    titles = ("COLONY", "KEEPER", "CHAT LOG")
    for (x0, bw), title, lines in zip(boxes, titles, (colony, keeper, chat)):
        d.rounded_rectangle([x0 + 6, HUD_Y0 + 2, x0 + bw - 6, CAP_Y0 - 4], 8, fill=(34, 26, 16, 170))
        d.text((x0 + 16, HUD_Y0 + 6), title, font=font("hn", 20), fill=GOLD)
        for i, ln in enumerate(lines[:3]):
            if isinstance(ln, tuple):
                name, col, msg = ln
                d.text((x0 + 16, HUD_Y0 + 30 + i * 22), name, font=font("menlo", 20), fill=col)
                nw = d.textlength(name, font=font("menlo", 20))
                d.text((x0 + 16 + nw, HUD_Y0 + 30 + i * 22), msg, font=font("menlo", 20), fill=CREAM)
            else:
                d.text((x0 + 16, HUD_Y0 + 30 + i * 22), ln, font=font("menlo", 20), fill=CREAM)
    d.rectangle([0, CAP_Y0, W, H], fill=(30, 22, 14, 255))
    d.text((16, CAP_Y0 + 2), "concept render · names are examples", font=font("menlo", 20), fill=MUTED)
    d.text((W - 16, CAP_Y0 + 2), "topdown · seed %d · viewing 40x27 of 256x256 tiles" % SEED, font=font("menlo", 20),
           fill=MUTED, anchor="ra")


# ----------------------------------------------------------------------------- frames
NAMES = ["kai_dnb", "mira_9", "sami.exe", "lowkeyjord", "noor.wav", "pixelpaul", "tinytash", "gav1n",
         "holly_hz", "zed_ttv", "luca_99", "bigmarcus", "dev_rin", "xX_tobi_Xx"]


def find_spot(w, sx, sy, r_tiles, half_w, up, down, prefer_deg, occupied, spread=(0, 15, -15, 30, -30, 45, -45, 60, -60, 90, -90, 120, -120, 150, -150, 180)):
    """First dry spot on a ring around the plaza whose box (half_w wide, up above / down below the anchor)
    is clear of water, river, frame edges and the occupied rects. Angles fan out from prefer_deg."""
    for dr in (0, 1.0, -0.8, 2.0, 3.0):
        for da in spread:
            a = math.radians(prefer_deg + da)
            x = sx + (r_tiles + dr) * TW * math.cos(a)
            y = sy + (r_tiles + dr) * TH * math.sin(a)
            box = (x - half_w, y - up, x + half_w, y + down)
            if box[0] < 24 or box[2] > W - 24 or box[1] < 90 or box[3] > WH - 130:
                continue
            if not w.dry_box(*box, margin=10):
                continue
            if any(not (box[2] < o[0] or box[0] > o[2] or box[3] < o[1] or box[1] > o[3]) for o in occupied):
                continue
            if not w.dry_segment(sx, sy, x, y):
                continue
            return (x, y)
    return None


def build_frame(frame: str):
    w = World(frame)
    base = paint_terrain(w)
    img = Image.fromarray(base.astype(np.uint8))  # RGB: ImageDraw "RGBA" mode blends onto RGB
    sx, sy = w.site_px()
    sc = Scene(w)
    occupied = [(sx - 70, sy - 70, sx + 70, sy + 40),      # plaza core
                (0, 0, 830, 112), (0, 0, 300, 190), (W - 200, 0, W, 200)]   # chips, dial, minimap

    # ---- village ring (same site both frames; B is day 5)
    hut_pos = []
    rng = np.random.RandomState(SEED + 88)
    ring_names = NAMES[:2] if frame == "A" else NAMES[:8] + ["luca_99"]
    for i, nm in enumerate(ring_names):
        slot = (0, 4)[i] if frame == "A" else i
        a = -math.pi / 2 + slot * (2 * math.pi / 9) + rng.uniform(-0.15, 0.15)
        r = 6.6 + rng.uniform(-0.3, 0.4)
        hx, hy = sx + r * TW * math.cos(a), sy + r * TH * 0.72 * math.sin(a)
        for _ in range(8):
            if w.dry_box(hx - 40, hy - 50, hx + 40, hy + 12, margin=10):
                break
            r -= 0.45
            hx, hy = sx + r * TW * math.cos(a), sy + r * TH * 0.72 * math.sin(a)
        hut_pos.append((hx, hy, nm))
        occupied.append((hx - 48, hy - 78, hx + 48, hy + 16))

    # nearest river point (for the water trail) and the sea direction
    rp = np.array(w.river_pts_px)
    dists = np.hypot(rp[:, 0] - sx, rp[:, 1] - sy)
    hidden = (rp[:, 1] < 150) | (rp[:, 1] > WH - 150) | (rp[:, 0] < 60) | (rp[:, 0] > W - 60)
    dists = np.where(hidden, 1e9, dists)
    k = int(np.argmin(dists))
    river_pt = tuple(rp[k])
    vx, vy = sx - river_pt[0], sy - river_pt[1]
    L = math.hypot(vx, vy) or 1
    water_pt = (river_pt[0] + vx / L * 30, river_pt[1] + vy / L * 22)
    ys_, xs_ = np.nonzero(w.E < SEA)
    sea_deg = math.degrees(math.atan2((ys_.mean() - sy) / TH, (xs_.mean() - sx) / TW)) if len(xs_) else 45.0

    # trees: forest where moisture is high, thinned around the village and away from the water
    trees = []
    trng = np.random.RandomState(SEED + 55)
    for ty in range(-1, VTH + 1):
        for tx in range(-1, VTW + 1):
            for _ in range(2):
                x = (tx + trng.rand()) * TW
                y = (ty + trng.rand()) * TH
                xi, yi = int(np.clip(x, 0, W - 1)), int(np.clip(y, 0, WH - 1))
                m, e = w.M[yi, xi], w.E[yi, xi]
                if w.water[yi, xi] or w.river_field[yi, xi] > 0.12 or e < SEA + 0.03 or e > 0.70:
                    continue
                dens = (m - 0.56) * 4.0 + (0.12 if e > 0.60 else 0)
                dv = math.hypot((x - sx) / TW, (y - sy) / TH)
                if dv < 7.8:
                    dens -= 0.6
                if trng.rand() < dens:
                    kind = 1 if (e > 0.56 and trng.rand() < 0.65) else 0
                    tone = mix(hex_rgb("#3E7C3C"), hex_rgb("#7BAE4E"), trng.rand() * 0.8)
                    if kind == 1:
                        tone = mix(hex_rgb("#2F6B3A"), hex_rgb("#5F9A4A"), trng.rand() * 0.7)
                    trees.append((x, y, kind, 12 + trng.rand() * 10, tone))
    if trees:
        ta = np.array([(t[0], t[1]) for t in trees])
        dm = np.hypot(ta[:, None, 0] - ta[None, :, 0], ta[:, None, 1] - ta[None, :, 1])
        company = (dm < 70).sum(axis=1) >= 4
        dsite = np.hypot(ta[:, 0] - sx, ta[:, 1] - sy)
        dsite = np.where(company & (dsite > 9.5 * TW), dsite, 1e9)
        kk = int(np.argmin(dsite))
        forest_pt = (ta[kk, 0] - 30, ta[kk, 1] + 14)
    else:
        forest_pt = (sx + 300, sy - 200)
    for _ in range(90):
        x, y = trng.randint(0, W), trng.randint(0, WH)
        if w.E[y, x] > 0.64 and not w.water[y, x] and trng.rand() < 0.5:
            rock(sc, x, y, 5 + trng.rand() * 7)

    # ---- farms and vote stones: searched spots on dry land, clear of everything placed so far
    farm_pts, stone_pt = [], None
    if frame == "A":
        paths = [([(hut_pos[0][0], hut_pos[0][1] + 4), (sx, sy), (hut_pos[1][0], hut_pos[1][1] + 4)], 0.25),
                 ([(sx, sy), water_pt], 0.2)]
        draw_trails(img, w, paths)
    else:
        paths = [([(hx, hy + 4), (sx, sy)], 0.45) for hx, hy, _ in hut_pos]
        paths.append(([(sx, sy), water_pt], 1.0))
        paths.append(([(sx, sy), forest_pt], 0.7))
        for nm, pref in (("holly_hz", sea_deg + 12), ("noor.wav", sea_deg - 70)):
            spot = find_spot(w, sx, sy, 8.0, 56, 56, 6, pref, occupied)
            if spot is None:
                spot = find_spot(w, sx, sy, 8.0, 56, 56, 6, pref, occupied[:1])
            if spot is None:
                continue
            fx, fy = spot
            farm_pts.append((fx, fy, nm))
            occupied.append((fx - 70, fy - 70, fx + 70, fy + 12))
            paths.append(([(sx, sy), (fx, fy)], 0.6))
        stone_pt = find_spot(w, sx, sy, 9.5, 180, 40, 40, 180, occupied)
        if stone_pt is None:
            stone_pt = find_spot(w, sx, sy, 9.5, 180, 40, 40, 180, occupied[:1])
        if stone_pt is None:
            stone_pt = (sx - 9 * TW, sy)
        occupied.append((stone_pt[0] - 190, stone_pt[1] - 50, stone_pt[0] + 190, stone_pt[1] + 50))
        paths.append(([(sx, sy), stone_pt], 0.5))
        draw_trails(img, w, paths, plaza=(sx, sy), plaza_r=58)
        for fx, fy, nm in farm_pts:
            farm(sc, fx, fy, 3, 2, 3 if nm == "holly_hz" else 1, nm)

    draw_grass_and_flowers(img, w)
    cloud_lay = draw_cloud_shadows(img, w)

    # ---- objects
    for x, y, kind, size, tone in trees:
        if any(abs(x - hx) < 64 and -80 < y - hy < 44 for hx, hy, _ in hut_pos):
            continue
        if any(abs(x - fx) < 84 and -84 < y - fy < 30 for fx, fy, _ in farm_pts):
            continue
        if stone_pt and abs(x - stone_pt[0]) < 200 and -56 < y - stone_pt[1] < 64:
            continue
        tree(sc, x, y, kind, size, tone)

    bubbles = []
    if frame == "A":
        for hx, hy, nm in hut_pos:
            hut(sc, hx, hy, nm, awake=False)
            side = -1 if hx > sx else 1
            creature(sc, hx + side * 30, hy + 30, nm, frame="asleep", facing=side, tier=1)

        def stake(img_):
            d = ImageDraw.Draw(img_, "RGBA")
            d.line([(sx, sy), (sx, sy - 26)], fill=(120, 90, 60, 255), width=3)
            d.polygon([(sx, sy - 26), (sx + 16, sy - 21), (sx, sy - 15)], fill=hex_rgb(pips.colour_hex("kai_dnb", "kick")) + (255,))
        sc.add(sy, stake)
    else:
        awake_names = set(NAMES) - {"mira_9", "gav1n"}
        for hx, hy, nm in hut_pos:
            hut(sc, hx, hy, nm, awake=nm in awake_names, building=(nm == "luca_99"))
        for hx, hy, nm in hut_pos:
            if nm in ("mira_9", "gav1n"):
                side = -1 if hx > sx else 1
                creature(sc, hx + side * 30, hy + 30, nm, frame="asleep", facing=side, tier=2)
        monument(sc, sx, sy - 6, raised_by=9)
        occupied.append((sx - 160, sy - 80, sx + 160, sy + 34))
        vx_, vy_ = stone_pt
        voters = (["sami.exe", "pixelpaul", "dev_rin", "zed_ttv"],
                  ["kai_dnb", "noor.wav", "holly_hz", "lowkeyjord", "tinytash", "bigmarcus", "xX_tobi_Xx"],
                  ["luca_99"])
        vote_stones(sc, vx_, vy_, (4, 7, 1), voters)
        # builders at the unfinished hut
        lh = [h for h in hut_pos if h[2] == "luca_99"][0]
        creature(sc, lh[0] - 50, lh[1] + 10, "luca_99", frame="walk0", facing=1, tier=1, carry="hammer")
        creature(sc, lh[0] + 78, lh[1] + 30, "xX_tobi_Xx", frame="idle1", facing=-1, tier=1, carry="log")
        # gatherers at the forest edge
        a1 = creature(sc, forest_pt[0] - 10, forest_pt[1] + 8, "pixelpaul", frame="walk1", facing=-1, tier=2, carry="log")
        bubbles.append((a1, "3 more logs and the mill stands"))
        creature(sc, forest_pt[0] + 70, forest_pt[1] + 40, "dev_rin", frame="idle0", facing=-1, tier=1)
        # at the water
        creature(sc, water_pt[0], water_pt[1], "sami.exe", frame="idle0", facing=1, tier=2, carry="pot")
        # farmers
        for fx, fy, nm in farm_pts:
            a3 = creature(sc, fx - 72, fy + 14, nm, frame="walk0", facing=1, tier=2)
            if nm == "noor.wav":
                bubbles.append((a3, "planting by the water, who's with me"))
        # voters at the stones
        a4 = creature(sc, vx_ + 30, vy_ + 40, "kai_dnb", frame="wave0", facing=-1, tier=2)
        bubbles.append((a4, "B! the well goes by the plaza"))
        creature(sc, vx_ - 118 - 62, vy_ + 24, "zed_ttv", frame="idle1", facing=1, tier=1)
        # on the trails and at the stone
        mid = ((sx * 0.35 + water_pt[0] * 0.65), (sy * 0.35 + water_pt[1] * 0.65))
        creature(sc, mid[0], mid[1] + 10, "lowkeyjord", frame="walk1", facing=-1, tier=2)
        creature(sc, sx - 20, sy + 72, "tinytash", frame="sit0", facing=1, tier=2)
        fm = (sx * 0.3 + forest_pt[0] * 0.7, sy * 0.3 + forest_pt[1] * 0.7)
        creature(sc, fm[0], fm[1] + 12, "bigmarcus", frame="walk0", facing=1, tier=2)

    sc.draw_all(img)

    # ---- grade and sky wisps (world only)
    img = time_grade(img, w)
    img = draw_cloud_wisps(img, cloud_lay)

    # ---- screen-scale text layer: bubbles keep clear of huts, plaza and stones
    _BUBBLE_RECTS.clear()
    _KEEP_OUT.clear()
    _KEEP_OUT.extend(occupied)
    _KEEP_OUT.append((0, 0, 820, 100))            # the plank chips
    for anchor, txt in bubbles:
        bubble(img, anchor, txt)

    full = Image.new("RGB", (W, H), (0, 0, 0))
    full.paste(img, (0, WY0))

    if frame == "A":
        chip(full, (16, WY0 + 14), "say anything in chat. a creature hatches with your name and walks out here.", font("hn", 22))
        chip(full, (16, WY0 + 58), "2 settled here · nobody awake · day 2 · dawn", font("menlo", 20))
    else:
        chip(full, (16, WY0 + 14), "@luca_99 settled · 18:02 · builder #14 · raising a hut on the east ring", font("hn", 22))
        chip(full, (16, WY0 + 58), "NEXT EVENT · where does the well go?  A river · B plaza · C hill", font("menlo", 20))
    time_dial(full, (16, WY0 + 104), w.evening)
    d = ImageDraw.Draw(full, "RGBA")
    d.text((16 + 76, WY0 + 118), ("06:41 · dawn" if frame == "A" else "18:07 · evening"), font=font("menlo", 20), fill=CREAM,
           stroke_width=2, stroke_fill=(28, 20, 12))
    d.text((16 + 76, WY0 + 142), ("wind NE · light" if frame == "A" else "wind E · fresh"), font=font("menlo", 20), fill=MUTED,
           stroke_width=2, stroke_fill=(28, 20, 12))

    cx0, cy0 = w.cam
    su, sv = cx0 + sx / TW, cy0 + sy / TH
    if frame == "A":
        minimap(full, w, [(su, sv)], [9], (sx, sy))
    else:
        minimap(full, w, [(su, sv), (su + 20, sv - 10), (su - 14, sv + 12), (su + 8, sv + 16)], [22, 10, 9, 8], (sx, sy))

    cc = lambda n: hex_rgb(pips.colour_hex(n, "kick"))
    if frame == "A":
        colony = ["2 settled · 3 more: Well opens",
                  "nobody awake · 2 asleep · day 2",
                  "last night: @kai_dnb built first"]
        keeper = ["no keeper on duty", "scrolls kept for next time", "last raised: stake · by @kai_dnb"]
        chat = ["chat is quiet. say anything.", "", ""]
        header(full, ("atleastonce", "SETTLEMENT · v0.6.0"), "2 SETTLED · 0 AWAKE", "NEXT EVENT 02:41", "1")
    else:
        colony = ["14 settled · 6 more: Mill opens",
                  "12 awake · 2 asleep · day 5",
                  "last event: rain · by @sami.exe"]
        keeper = ["keeper on duty", "surveying: East Field · @noor.wav", "12:40 left · then the well vote"]
        chat = [("@kai_dnb ", cc("kai_dnb"), "B"), ("@pixelpaul ", cc("pixelpaul"), "3 more logs, mill stands"),
                ("@noor.wav ", cc("noor.wav"), "planting by the water")]
        header(full, ("atleastonce", "SETTLEMENT · v0.6.3"), "14 SETTLED · 12 AWAKE", "NEXT EVENT 01:23", "7")
    hud(full, colony, keeper, chat)
    return full, w


def main():
    os.makedirs(OUT, exist_ok=True)
    a, wa = build_frame("A")
    a.save(os.path.join(OUT, "topdown_A_dawn_empty.png"))
    b, wb = build_frame("B")
    b.save(os.path.join(OUT, "topdown_B_busy.png"))
    b.resize((320, 180), Image.LANCZOS).save(os.path.join(OUT, "topdown_thumb_320x180.png"))
    print("cam", wa.cam, "site", wa.site, "river pts", len(wa.river), "site px", wa.site_px(), "sea", wa.sea_t.mean(), "ponds", wa.pond_t.sum())


if __name__ == "__main__":
    main()
