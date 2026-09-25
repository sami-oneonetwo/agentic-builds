"""tiles.py - SETTLEMENT tile atlas generator (studio-a).

32 px top-down tiles built from PERIODIC noise (integer wave numbers over the tile), so every tile
wraps seamlessly against its neighbours and every animated family loops over its phases.

Families (name -> RGBA (32,32,4) uint8):
    grass:v{0-3}:p{0-3}        four variants, four wind phases (tufts lean 0,+1,0,-1 px; sheen shifts)
    meadow:v{0-1}:p{0-3}       lighter grass with flower dots
    forest:v{0-1}               forest floor (darker, mossy, leaf litter)
    hill:v{0-1}                 dry upland grass with contour strokes and stones
    water:deep:p{0-3}           ripple highlights loop over four phases
    water:shallow:p{0-3}
    sand:v{0-1}
    shore:{m}:p{0-3}            sand with water encroaching from the 4-bit edge mask m (N=1,E=2,S=4,W=8)
    sandgrass:{m}               grass with sand encroaching
    hilledge:{m}                hill with grass below it (drop shade on the lower side)
    forestedge:{m}              forest floor with grass encroaching
    path:{wear 1-2}:{m}         RGBA overlay: worn trail connecting the flagged edges (0 = a patch)
    farm:{0-3}                  tilled, seedlings, growing, ripe

Props (name -> RGBA, bigger than a tile, anchored at the bottom centre):
    tree:{size 0-2}:{shape 0-2}:s{0-2}   broadleaf, canopy sway phases (-1,0,+1 px)
    pine:{size 0-2}:s{0-2}      conifer star silhouette ; rock:{0-1} ; bush:{0-1} ; reeds:{0-1}

season in {"spring","summer","autumn"} shifts the grass/leaf palette. numpy + pillow only.
    python tiles.py -> tile_atlas.png next to this file
"""
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
T = 32
MASKS = range(16)

SEASONS = {
    "spring": dict(grass=(126, 176, 92), grass_dk=(98, 148, 76), meadow=(160, 194, 104), forest=(84, 128, 70),
                   canopy=((58, 112, 62), (92, 150, 78), (132, 184, 96)), hill=(150, 162, 96), flower=[(250, 200, 220), (255, 250, 230), (250, 226, 120), (200, 180, 240)]),
    "summer": dict(grass=(120, 168, 84), grass_dk=(92, 140, 70), meadow=(158, 188, 96), forest=(78, 120, 64),
                   canopy=((54, 104, 58), (86, 142, 72), (124, 176, 90)), hill=(156, 160, 92), flower=[(250, 190, 210), (255, 248, 226), (252, 214, 100), (196, 176, 236)]),
    "autumn": dict(grass=(146, 158, 78), grass_dk=(114, 128, 64), meadow=(176, 176, 92), forest=(104, 112, 60),
                   canopy=((120, 84, 44), (190, 120, 56), (226, 168, 84)), hill=(168, 150, 88), flower=[(250, 200, 160), (255, 244, 220), (240, 200, 100), (230, 160, 130)]),
}
WATER_DEEP = (58, 112, 156)
WATER_SHALLOW = (86, 156, 176)
WATER_HI = (196, 228, 236)
SAND = (222, 206, 164)
SAND_DK = (198, 180, 136)
DIRT = (176, 142, 100)
DIRT_DK = (148, 114, 78)
SOIL = (122, 90, 62)
SOIL_LT = (150, 116, 84)
STONE = (168, 160, 150)
STONE_DK = (120, 112, 104)
TRUNK = (110, 78, 50)

_yy, _xx = np.mgrid[0:T, 0:T].astype(np.float32)
_u = (_xx + 0.5) / T
_v = (_yy + 0.5) / T


def _rs(*key):
    return np.random.RandomState(abs(hash(("studio-a",) + key)) % (2 ** 31))


def pnoise(seed, waves=3, kmax=3, phase=0.0, shape=None):
    """Periodic noise on the tile: a sum of sin waves with integer wave numbers -> seamless tiling.
    Result is roughly -1..1."""
    rs = np.random.RandomState(seed)
    u, v = (_u, _v) if shape is None else shape
    out = np.zeros_like(u)
    for _ in range(waves):
        kx, ky = rs.randint(-kmax, kmax + 1), rs.randint(-kmax, kmax + 1)
        if kx == 0 and ky == 0:
            kx = 1
        out += rs.uniform(0.6, 1.0) * np.sin(2 * math.pi * (kx * u + ky * v) + rs.uniform(0, 6.28) + phase * rs.choice([-1, 1]))
    return out / waves


def grain(seed, amp):
    return np.random.RandomState(seed).uniform(-amp, amp, (T, T)).astype(np.float32)


def rgba(rgb, a=None):
    rgb = np.clip(rgb, 0, 255)
    if a is None:
        a = np.full((T, T), 255.0)
    return np.dstack([rgb, np.clip(a, 0, 255)]).astype(np.uint8)


def flat(col, seed, mottle=8, g=5):
    base = np.asarray(col, np.float32)[None, None, :]
    n = pnoise(seed, 3, 2)[..., None] * mottle + grain(seed + 1, g)[..., None]
    return np.repeat(base, T, 0).repeat(T, 1) + n


def _lerp(a, b, t):
    t = np.asarray(t, np.float32)
    if t.ndim == 2:
        t = t[..., None]
    return np.asarray(a, np.float32) * (1 - t) + np.asarray(b, np.float32) * t


def _stroke(img, x, y, dx, dy, n, col, alpha=1.0):
    """tiny pixel strokes for tufts/stems; img is float (T,T,3); wraps horizontally so tiles stay seamless."""
    for k in range(n):
        xi = int(x + dx * k) % T
        yi = int(y + dy * k)
        if 0 <= yi < T:
            img[yi, xi] = img[yi, xi] * (1 - alpha) + np.asarray(col, np.float32) * alpha


# ----------------------------------------------------------------------------- base families
def grass_tile(S, variant, phase, base=None, dark=None):
    base = base or S["grass"]
    dark = dark or S["grass_dk"]
    img = flat(base, 100 + variant, mottle=9, g=6)
    # a slow sheen band that travels with the wind phase (subtle: alive, not blinking)
    sheen = pnoise(400 + variant, 2, 1, phase=phase * math.pi / 2)
    img += (sheen[..., None] * 5)
    rs = _rs("grass", variant)
    lean = [0, 1, 0, -1][phase % 4]
    lt = _lerp(base, (255, 250, 200), 0.32)
    for _ in range(11):
        x, y = rs.randint(0, T), rs.randint(2, T)
        h = rs.randint(2, 4)
        _stroke(img, x, y, lean * 0.5, -1, h, lt, 0.85)
        _stroke(img, x + 1, y, lean * 0.5, -1, max(1, h - 1), dark, 0.55)
    return rgba(img)


def meadow_tile(S, variant, phase):
    t = grass_tile(S, variant + 2, phase, base=S["meadow"], dark=S["grass_dk"]).astype(np.float32)
    img = t[..., :3]
    rs = _rs("meadow", variant)
    for _ in range(5):
        x, y = rs.randint(1, T - 1), rs.randint(2, T - 1)
        col = S["flower"][rs.randint(0, len(S["flower"]))]
        lean = [0, 1, 0, -1][phase % 4]
        _stroke(img, x, y, 0, 1, 2, S["grass_dk"], 0.6)
        img[y - 1, (x + lean) % T] = col
        img[y - 1, (x + lean + 1) % T] = _lerp(col, (255, 255, 255), 0.3)
        img[y - 2, (x + lean) % T] = _lerp(col, (255, 255, 255), 0.2)
    return rgba(img)


def forest_tile(S, variant):
    img = flat(S["forest"], 200 + variant, mottle=10, g=7)
    rs = _rs("forest", variant)
    for _ in range(7):   # leaf litter + moss
        x, y = rs.randint(0, T), rs.randint(0, T)
        col = (118, 96, 58) if rs.rand() < 0.5 else _lerp(S["forest"], (200, 230, 140), 0.35)
        img[y, x] = col
        img[y, (x + 1) % T] = _lerp(col, img[y, (x + 1) % T], 0.5)
    return rgba(img)


def hill_tile(S, variant):
    img = flat(S["hill"], 300 + variant, mottle=9, g=6)
    rs = _rs("hill", variant)
    # contour strokes (dry ridges) that wrap horizontally
    for _ in range(2):
        y0 = rs.randint(4, T - 4)
        for x in range(T):
            y = int(y0 + 2.0 * math.sin(2 * math.pi * x / T * rs.choice([1, 2]) + variant)) % T
            img[y, x] = _lerp(img[y, x], (120, 116, 70), 0.55)
            img[(y + 1) % T, x] = _lerp(img[(y + 1) % T, x], (210, 206, 150), 0.30)
    for _ in range(3):
        x, y = rs.randint(1, T - 1), rs.randint(1, T - 1)
        img[y, x] = STONE
        img[y, x - 1] = STONE_DK
        img[y + 1, x] = STONE_DK
    return rgba(img)


def sand_tile(variant):
    img = flat(SAND, 500 + variant, mottle=8, g=5)
    rs = _rs("sand", variant)
    for _ in range(9):
        x, y = rs.randint(0, T), rs.randint(0, T)
        img[y, x] = _lerp(img[y, x], SAND_DK, 0.7)
    return rgba(img)


def water_tile(kind, phase):
    base = WATER_DEEP if kind == "deep" else WATER_SHALLOW
    ph = phase * math.pi / 2
    img = flat(base, 600, mottle=7, g=3)
    # two travelling ripple trains; integer wave numbers keep the tile seamless, phase loops in 4
    # crests: thin bands where two wave trains add up; mostly horizontal so they read as ripples
    r1 = np.sin(2 * math.pi * (1 * _u + 3 * _v) + ph) + 0.45 * np.sin(2 * math.pi * (2 * _u + 0 * _v) + ph + 1.3)
    r2 = np.sin(2 * math.pi * (-1 * _u + 2 * _v) - ph + 0.7) + 0.35 * np.sin(2 * math.pi * (3 * _u + 1 * _v) + 2.1)
    hi = np.clip(1 - np.abs(r1 - 1.0) * 2.6, 0, 1) * 0.55 + np.clip(1 - np.abs(r2 - 1.0) * 3.5, 0, 1) * 0.28
    hi = hi * (0.6 + 0.4 * np.clip(pnoise(610, 2, 1, phase=ph), 0, 1))
    dk = np.clip((-r1 - 1.05) * 1.6, 0, 1) * 0.30
    img = _lerp(img, WATER_HI, hi)
    img = _lerp(img, _lerp(base, (20, 40, 80), 0.5), dk)
    return rgba(img)


# ----------------------------------------------------------------------------- autotiles
def edge_cov(mask, depth=11.0, wob=2.0, seed=0):
    """Coverage 0..1 of the 'lower' material encroaching from the flagged edges (N=1,E=2,S=4,W=8).
    The wobble is periodic along each edge so neighbouring tiles agree on the boundary."""
    cov = np.zeros((T, T), np.float32)
    px, py = _xx + 0.5, _yy + 0.5
    def w(t):
        return wob * np.sin(2 * math.pi * t / T * 2 + seed) + wob * 0.5 * np.sin(2 * math.pi * t / T * 3 + 1.7 + seed)
    fields = []
    if mask & 1:
        fields.append(depth + w(px) - py)
    if mask & 4:
        fields.append(depth + w(px + 9) - (T - py))
    if mask & 2:
        fields.append(depth + w(py + 4) - (T - px))
    if mask & 8:
        fields.append(depth + w(py + 13) - px)
    if not fields:
        return cov
    f = np.maximum.reduce(fields)
    # round the inner corner where two adjacent edges meet
    if (mask & 1 and mask & 2) or (mask & 1 and mask & 8) or (mask & 4 and mask & 2) or (mask & 4 and mask & 8):
        f = f + 0.0
    return np.clip(f / 3.0 + 0.5, 0, 1)


def autotile(hi, lo, mask, seed=0, depth=11.0, foam=None, shade=None):
    """hi/lo: RGBA tiles; returns hi with lo encroaching from the flagged edges."""
    cov = edge_cov(mask, depth=depth, seed=seed)
    h = hi[..., :3].astype(np.float32)
    l = lo[..., :3].astype(np.float32)
    img = _lerp(h, l, cov)
    band = np.clip(1 - np.abs(cov - 0.5) * 4, 0, 1)
    if foam is not None:
        img = _lerp(img, foam, band * 0.55)
    if shade is not None:
        # darker band on the hi side of the boundary (elevation step)
        inner = np.clip((0.5 - cov) * 3, 0, 1) * np.clip(cov * 8, 0, 1)
        img = _lerp(img, shade, inner * 0.30)
    return rgba(img)


def path_tile(wear, mask, seed=0):
    """RGBA overlay. Connects the centre to each flagged edge; mask 0 is a lone worn patch."""
    px, py = _xx + 0.5, _yy + 0.5
    c = T / 2.0
    r = 5.0 if wear == 1 else 7.0
    d = np.hypot(px - c, py - c) - r * 0.9
    def cap(ax, ay, bx, by):
        vx, vy = bx - ax, by - ay
        h = np.clip(((px - ax) * vx + (py - ay) * vy) / (vx * vx + vy * vy), 0, 1)
        return np.hypot(px - ax - vx * h, py - ay - vy * h) - r
    if mask & 1:
        d = np.minimum(d, cap(c, c, c, -1))
    if mask & 4:
        d = np.minimum(d, cap(c, c, c, T + 1))
    if mask & 2:
        d = np.minimum(d, cap(c, c, T + 1, c))
    if mask & 8:
        d = np.minimum(d, cap(c, c, -1, c))
    d = d + pnoise(900 + seed, 3, 3) * 1.6
    cov = np.clip(0.5 - d / 2.0, 0, 1)
    g = grain(950 + seed, 0.35) + 1.0
    alpha = cov * (0.55 if wear == 1 else 0.9) * np.clip(g, 0.5, 1.0)
    col = flat(DIRT if wear == 1 else DIRT_DK, 960 + seed, mottle=8, g=6)
    # worn ruts: two faint lighter lines along the centre for wear 2
    if wear == 2:
        col = _lerp(col, DIRT, np.clip(1 - np.abs(np.hypot(px - c, py - c) - 3) / 1.2, 0, 1) * 0.5)
    return rgba(col, alpha * 255)


def farm_tile(S, stage):
    img = flat(SOIL, 700 + stage, mottle=6, g=6)
    rows = ((_yy // 4) % 2 == 0)
    img = _lerp(img, SOIL_LT, rows.astype(np.float32) * 0.55)
    if stage >= 1:
        rs = _rs("farm", stage)
        crop = [(120, 176, 84), (92, 156, 70), (222, 190, 88)][stage - 1]
        for y in range(1, T, 4):
            for x in range(rs.randint(0, 3), T, 3):
                h = [1, 2, 3][stage - 1]
                _stroke(img, x, y + 1, 0, -1, h, crop, 0.95)
                if stage == 3:
                    img[max(0, y - 2), x] = (240, 214, 120)
    return rgba(img)


# ----------------------------------------------------------------------------- props
def _blank(w, h):
    return np.zeros((h, w, 4), np.float32)


def _disc(img, cx, cy, r, col, alpha=1.0, soft=1.0):
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.hypot(xx + 0.5 - cx, yy + 0.5 - cy) - r
    cov = np.clip(0.5 - d / soft, 0, 1) * alpha
    a = cov[..., None]
    img[..., :3] = np.asarray(col, np.float32) * a + img[..., :3] * (1 - a)
    img[..., 3] = cov + img[..., 3] * (1 - cov)


def _ellipse(img, cx, cy, rx, ry, col, alpha=1.0, soft=1.0):
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = (np.sqrt(((xx + 0.5 - cx) / rx) ** 2 + ((yy + 0.5 - cy) / ry) ** 2) - 1) * min(rx, ry)
    cov = np.clip(0.5 - d / soft, 0, 1) * alpha
    a = cov[..., None]
    img[..., :3] = np.asarray(col, np.float32) * a + img[..., :3] * (1 - a)
    img[..., 3] = cov + img[..., 3] * (1 - cov)


def _finish(img):
    a = np.maximum(img[..., 3:4], 1e-4)
    rgb = np.where(img[..., 3:4] > 1e-4, img[..., :3], 0)
    return np.dstack([np.clip(rgb, 0, 255), np.clip(img[..., 3] * 255, 0, 255)]).astype(np.uint8)


def tree_prop(S, size, shape, sway):
    """Top-down 3/4 broadleaf: a cluster of lobes (silhouette varies by `shape`), lit from the upper-left,
    dark crevices between lobes, trunk peeking below, soft shadow. Sway shifts the canopy 1 px."""
    R = [11, 14, 18][size]
    w, h = R * 2 + 14, R * 2 + 18
    img = _blank(w, h)
    cx, cy = w / 2.0, h - R - 5
    dx = [-1, 0, 1][sway]
    dk, md, lt = S["canopy"]
    _ellipse(img, cx + 3, h - 4, R * 0.95, R * 0.32, (30, 26, 34), alpha=0.35, soft=4.0)
    _ellipse(img, cx, h - 6, 2.2, 2.6, TRUNK)
    rs = _rs("tree", size, shape)
    n = 5 + shape
    lobes = []
    for i in range(n):
        a = 2 * math.pi * i / n + rs.uniform(-0.3, 0.3)
        d = R * rs.uniform(0.35, 0.62)
        lobes.append((d * math.cos(a), d * math.sin(a) * 0.85, R * rs.uniform(0.42, 0.62)))
    lobes.append((0, -R * 0.1, R * 0.62))
    for (ox, oy, r) in lobes:
        _disc(img, cx + ox + dx, cy + oy, r + 1.2, tuple(int(c * 0.55) for c in dk), soft=1.5)
    for (ox, oy, r) in lobes:
        _disc(img, cx + ox + dx, cy + oy, r, dk, soft=1.2)
    for (ox, oy, r) in lobes:
        _disc(img, cx + ox + dx - r * 0.20, cy + oy - r * 0.24, r * 0.74, md, soft=1.5)
    # crevices: dark seams where lobes meet, so the canopy reads as foliage not a ball
    for i in range(n):
        (ax, ay, ar), (bx, by, br) = lobes[i], lobes[(i + 1) % n]
        mx, my = (ax + bx) / 2, (ay + by) / 2
        _disc(img, cx + mx + dx, cy + my + 1, 1.6, tuple(int(c * 0.7) for c in dk), alpha=0.7, soft=2.0)
    for (ox, oy, r) in lobes:
        _disc(img, cx + ox + dx - r * 0.34, cy + oy - r * 0.40, r * 0.40, lt, alpha=0.9, soft=2.0)
    for _ in range(4 + size * 2):
        _disc(img, cx + dx + rs.uniform(-R * 0.7, R * 0.7), cy + rs.uniform(-R * 0.7, R * 0.5), 1.1, _lerp(lt, (255, 255, 230), 0.4), alpha=0.8)
    return _finish(img)


def pine_prop(S, size, sway):
    """Top-down conifer: a spiky star silhouette in three rings (dark rim, mid, light crown) rotating
    inward, so forests mix round broadleaf canopies with pointed pines."""
    R = [10, 13, 17][size]
    w, h = R * 2 + 10, R * 2 + 16
    img = _blank(w, h)
    cx, cy = w / 2.0, h - R - 4
    dx = [-1, 0, 1][sway]
    dk, md, lt = S["canopy"]
    dk = tuple(int(c * 0.85) for c in dk)
    _ellipse(img, cx + 3, h - 4, R * 0.8, R * 0.28, (30, 26, 34), alpha=0.35, soft=4.0)
    _ellipse(img, cx, h - 6, 2.0, 2.4, TRUNK)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ang = np.arctan2(yy + 0.5 - cy, xx + 0.5 - cx - dx)
    rad = np.hypot(xx + 0.5 - cx - dx, yy + 0.5 - cy)
    arms = 8 + size
    for k, (scale, col, rot) in enumerate(((1.0, tuple(int(c * 0.6) for c in dk), 0.0), (0.96, dk, 0.0), (0.70, md, 0.35), (0.42, lt, 0.7))):
        rr = R * scale * (0.72 + 0.28 * np.cos(arms * (ang + rot)))
        d = rad - rr
        cov = np.clip(0.5 - d / 1.2, 0, 1)
        if k >= 2:
            # shift inner rings toward the light
            cov = np.roll(np.roll(cov, -1, axis=0), -1, axis=1)
        a = cov[..., None]
        img[..., :3] = np.asarray(col, np.float32) * a + img[..., :3] * (1 - a)
        img[..., 3] = cov + img[..., 3] * (1 - cov)
    return _finish(img)


def rock_prop(v):
    w, h = 18, 14
    img = _blank(w, h)
    _ellipse(img, w / 2 + 2, h - 3, 7, 2.5, (30, 26, 34), alpha=0.3, soft=3.0)
    _ellipse(img, w / 2, h / 2 + 1, 7 - v, 5, STONE_DK, soft=1.2)
    _ellipse(img, w / 2 - 1.5, h / 2 - 0.5, 5 - v, 3.4, STONE, soft=1.5)
    _ellipse(img, w / 2 - 3, h / 2 - 2, 2.2, 1.4, (214, 208, 198), alpha=0.8, soft=2.0)
    return _finish(img)


def bush_prop(S, v):
    w, h = 22, 18
    img = _blank(w, h)
    dk, md, lt = S["canopy"]
    _ellipse(img, w / 2 + 2, h - 3, 9, 3, (30, 26, 34), alpha=0.3, soft=3.0)
    for (ox, oy, r) in [(0, 0, 7), (-5, 2, 5), (5, 2, 5.5), (-2, -3, 4.5)]:
        _disc(img, w / 2 + ox, h / 2 + oy - v, r + 1, tuple(int(c * 0.6) for c in dk), soft=1.5)
    for (ox, oy, r) in [(0, 0, 7), (-5, 2, 5), (5, 2, 5.5), (-2, -3, 4.5)]:
        _disc(img, w / 2 + ox, h / 2 + oy - v, r, md, soft=1.2)
        _disc(img, w / 2 + ox - 1.5, h / 2 + oy - v - 1.5, r * 0.5, lt, alpha=0.85, soft=2.0)
    if v == 1:
        for (ox, oy) in [(-4, -1), (3, -2), (0, 3)]:
            _disc(img, w / 2 + ox, h / 2 + oy - 1, 1.2, (240, 120, 130))
    return _finish(img)


def reeds_prop(v):
    w, h = 16, 22
    img = _blank(w, h)
    rs = _rs("reeds", v)
    for i in range(6):
        x = 3 + i * 2 + rs.uniform(-0.5, 0.5)
        top = 4 + rs.randint(0, 6)
        for y in range(top, h - 2):
            xi = int(x + (y - top) * 0.08 * (1 if i % 2 else -1))
            if 0 <= xi < w:
                img[y, xi, :3] = (96, 150, 76) if y > top + 3 else (150, 120, 70)
                img[y, xi, 3] = 1.0
    return _finish(img)


# ----------------------------------------------------------------------------- atlas
class Atlas:
    def __init__(self, season="summer"):
        S = SEASONS[season]
        self.season = season
        self.S = S
        t = {}
        for v in range(4):
            for p in range(4):
                t["grass:v%d:p%d" % (v, p)] = grass_tile(S, v, p)
        for v in range(2):
            for p in range(4):
                t["meadow:v%d:p%d" % (v, p)] = meadow_tile(S, v, p)
            t["forest:v%d" % v] = forest_tile(S, v)
            t["hill:v%d" % v] = hill_tile(S, v)
            t["sand:v%d" % v] = sand_tile(v)
        for p in range(4):
            t["water:deep:p%d" % p] = water_tile("deep", p)
            t["water:shallow:p%d" % p] = water_tile("shallow", p)
        foam = _lerp(WATER_HI, (255, 255, 255), 0.4)
        for m in MASKS:
            for p in range(4):
                t["shore:%d:p%d" % (m, p)] = autotile(t["sand:v0"], t["water:shallow:p%d" % p], m, seed=1, depth=11, foam=foam)
            t["sandgrass:%d" % m] = autotile(t["grass:v0:p0"], t["sand:v1"], m, seed=2, depth=10)
            t["hilledge:%d" % m] = autotile(t["hill:v0"], t["grass:v1:p0"], m, seed=3, depth=10, shade=(70, 80, 40))
            t["forestedge:%d" % m] = autotile(t["forest:v0"], t["grass:v2:p0"], m, seed=4, depth=12)
            for w in (1, 2):
                t["path:%d:%d" % (w, m)] = path_tile(w, m, seed=m)
        for s in range(4):
            t["farm:%d" % s] = farm_tile(S, s)
        self.tiles = t
        pr = {}
        for size in range(3):
            for sw in range(3):
                for shape in range(3):
                    pr["tree:%d:%d:s%d" % (size, shape, sw)] = tree_prop(S, size, shape, sw)
                pr["pine:%d:s%d" % (size, sw)] = pine_prop(S, size, sw)
        for v in range(2):
            pr["rock:%d" % v] = rock_prop(v)
            pr["bush:%d" % v] = bush_prop(S, v)
            pr["reeds:%d" % v] = reeds_prop(v)
        self.props = pr

    def get(self, name):
        return self.tiles[name]

    # ------------------------------------------------------------ export
    def save_png(self, path=None, zoom=2):
        path = path or os.path.join(HERE, "tile_atlas.png")
        groups = [
            ("grass  (4 variants x 4 wind phases)", ["grass:v%d:p%d" % (v, p) for v in range(4) for p in range(4)]),
            ("meadow (2 x 4)  forest  hill  sand", ["meadow:v%d:p%d" % (v, p) for v in range(2) for p in range(4)] + ["forest:v0", "forest:v1", "hill:v0", "hill:v1", "sand:v0", "sand:v1"]),
            ("water deep / shallow x 4 ripple phases", ["water:deep:p%d" % p for p in range(4)] + ["water:shallow:p%d" % p for p in range(4)]),
            ("shore autotile, 16 edge masks (phase 0)", ["shore:%d:p0" % m for m in MASKS]),
            ("sand->grass autotile", ["sandgrass:%d" % m for m in MASKS]),
            ("hill edge autotile (drop shade)", ["hilledge:%d" % m for m in MASKS]),
            ("forest edge autotile", ["forestedge:%d" % m for m in MASKS]),
            ("path wear 1 (16 masks)", ["path:1:%d" % m for m in MASKS]),
            ("path wear 2 (16 masks)", ["path:2:%d" % m for m in MASKS]),
            ("farm stages 0-3", ["farm:%d" % s for s in range(4)]),
        ]
        cell = T * zoom + 4
        label_h = 22
        Wd = 16 * cell + 24
        Hd = sum(label_h + cell for _ in groups) + 320
        im = Image.new("RGB", (Wd, Hd), (52, 44, 58))
        d = ImageDraw.Draw(im)
        f = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 14)
        y = 8
        grassbg = Image.fromarray(self.tiles["grass:v0:p0"][..., :3]).resize((T * zoom, T * zoom), Image.NEAREST)
        for title, names in groups:
            d.text((12, y), title, font=f, fill=(230, 220, 200))
            y += label_h
            for j, n in enumerate(names):
                x = 12 + j * cell
                tile = self.tiles[n]
                if n.startswith("path"):
                    im.paste(grassbg, (x, y))
                ti = Image.fromarray(tile).resize((T * zoom, T * zoom), Image.NEAREST)
                im.paste(ti, (x, y), ti)
            y += cell
        d.text((12, y), "props (sway 1 only): broadleaf 3 sizes x 3 shapes, pines 3 sizes, rocks, bushes, reeds", font=f, fill=(230, 220, 200))
        y += label_h
        x = 12
        for n in sorted(self.props):
            if ":s" in n and not n.endswith(":s1"):
                continue
            p = self.props[n]
            pi = Image.fromarray(p).resize((p.shape[1] * zoom, p.shape[0] * zoom), Image.LANCZOS)
            if x + pi.size[0] > Wd - 12:
                x = 12
                y += 124
            im.paste(pi, (x, y + 120 - pi.size[1]), pi)
            x += pi.size[0] + 10
        d.text((12, Hd - 22), "SETTLEMENT tile atlas  studio-a  season=%s  32 px tiles at %dx nearest" % (self.season, zoom), font=f, fill=(200, 190, 175))
        im.save(path)
        return path


if __name__ == "__main__":
    import time
    t0 = time.time()
    a = Atlas("summer")
    print("atlas built in %.2fs: %d tiles, %d props" % (time.time() - t0, len(a.tiles), len(a.props)))
    print(a.save_png())
