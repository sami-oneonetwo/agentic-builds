"""render_mockup.py - 1280x720 SETTLEMENT frames rendered FROM the studio-a generators.

    python render_mockup.py          -> mockup_busy.png, mockup_dawn.png, thumb_320x180.png + bench line

Layout (hud.py): 72 px header, 1280x440 world (y 72..512), 208 px footer. Terrain: the atlas textures
(tiles.Atlas, 4 wind/ripple phases) are SPLATTED with per-pixel masks from the same elevation/moisture
fields that classify the tiles, so coastlines, forest edges and hill lips are smooth curves rather than
32 px stairs (the pure tile-blit path is still available through WorldMap.tile_name for a strict
atlas compositor). Four full-region frames are baked once per camera move; the time-of-day tint and
drifting cloud shadow are re-applied in 1/8-region slices, one slice per frame, so nothing spikes.
Buildings are baked into the frames; creatures (creatures.SpriteCache), their dusk glows, lantern
flicker and speech plates (pre-rendered to small sprites) are blitted per frame. `bench()` times that
per-frame path with 20 creatures.

CONCEPT RENDER. Names are examples. Never touches the stream.
"""
import hashlib
import math
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import creatures  # noqa: E402
import tiles  # noqa: E402
import buildings  # noqa: E402
import hud  # noqa: E402
from paint import blit, blit_add  # noqa: E402

W, H = hud.W, hud.H
WY0, WH = hud.WORLD_Y0, hud.WORLD_H
T = tiles.T
COLS, ROWS = W // T, int(math.ceil(WH / T))       # 40 x 14 tiles in view
MX, MY = 3, 3                                     # margin for neighbour lookups
GW, GH = COLS + 2 * MX, ROWS + 2 * MY
SEED = 4471
PLAZA = (17, 7)                                   # tile coords of the village centre (view space)
SWAY = [1, 2, 1, 0]                               # tree sway index per phase (0 / +1 / 0 / -1)
SLICES = 8                                        # relight slices per phase (one per frame)


# ----------------------------------------------------------------------------- noise
def _hash2(i, j, seed):
    n = (i.astype(np.int64) * 374761393 + j.astype(np.int64) * 668265263 + int(seed) * 1013904223) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    n = (n ^ (n >> 16)) & 0xFFFFFFFF
    return n.astype(np.float32) / np.float32(4294967295.0)


def vnoise(u, v, freq, seed):
    x, y = u * freq, v * freq
    xi, yi = np.floor(x), np.floor(y)
    fx, fy = (x - xi).astype(np.float32), (y - yi).astype(np.float32)
    sx = fx * fx * (3 - 2 * fx)
    sy = fy * fy * (3 - 2 * fy)
    a, b = _hash2(xi, yi, seed), _hash2(xi + 1, yi, seed)
    c, d = _hash2(xi, yi + 1, seed), _hash2(xi + 1, yi + 1, seed)
    return (a * (1 - sx) + b * sx) * (1 - sy) + (c * (1 - sx) + d * sx) * sy


def fbm(u, v, freq, octaves, seed):
    tot, amp, norm = np.zeros_like(u, dtype=np.float32), 1.0, 0.0
    for o in range(octaves):
        tot += amp * vnoise(u, v, freq, seed + 101 * o)
        norm += amp
        amp *= 0.5
        freq *= 2
    return tot / norm


def th(*k):
    """small deterministic hash 0..1 for placement jitter"""
    return int(hashlib.sha1(repr(k).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def sstep(x, a, b):
    """smoothstep from a to b (a may be > b for a falling edge)"""
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def fields(u, v, seed):
    """elevation + moisture in tile units (view space). Shared by tile classification, pixel splatting
    and the minimap so they always agree."""
    n = fbm(u, v, 1 / 9.0, 3, seed)
    sea = np.clip((u - 25) / 13.0, 0, 1) * 0.60 + np.clip((v - 9) / 6.0, 0, 1) * 0.22
    hill = np.clip((10 - u) / 10.0, 0, 1) * np.clip((6 - v) / 6.0, 0, 1) * 0.55
    E = (0.52 + (n - 0.5) * 0.55 - sea + hill).astype(np.float32)
    m = fbm(u, v, 1 / 7.0, 3, seed + 7000)
    M = (m + np.clip((9 - u) / 9.0, 0, 1) * 0.28 + np.clip((v - 10) / 5.0, 0, 1) * 0.1).astype(np.float32)
    return E, M


# ----------------------------------------------------------------------------- world model
WATER, SAND, GRASS, MEADOW, FOREST, HILL, FARM = range(7)
E_WATER, E_SAND, E_HILL, M_FOREST, M_MEADOW = 0.30, 0.345, 0.80, 0.60, 0.38


class WorldMap:
    def __init__(self, seed=SEED, village=True):
        self.seed = seed
        v, u = np.mgrid[0:GH, 0:GW].astype(np.float32)
        self.u, self.v = u - MX, v - MY
        self.E, self.M = fields(self.u + 0.5, self.v + 0.5, seed)
        self.village = village
        self._classify()
        self._river()
        self._shoreline()
        self.paths = {}
        self.farm = {}
        self.huts = []
        self.props = []
        self.statics = []
        self.lanterns = []

    def _classify(self):
        E, M = self.E, self.M
        c = np.full(E.shape, GRASS, np.int8)
        c[M < M_MEADOW] = MEADOW
        c[M > M_FOREST] = FOREST
        c[E > E_HILL] = HILL
        c[E < E_SAND] = SAND
        c[E < E_WATER] = WATER
        if self.village:
            d = np.hypot(self.u - PLAZA[0], self.v - PLAZA[1])
            clear = (d < 6.5) & (c != WATER) & (c != SAND) & (c != HILL)
            c[clear] = GRASS
        self.C = c

    def _river(self):
        E, C = self.E, self.C
        hy, hx = np.unravel_index(np.argmax(np.where((self.u < 8) & (self.v < 5), E, -1)), E.shape)
        x, y = int(hx), int(hy)
        seen, order = set(), []
        for _ in range(90):
            seen.add((x, y))
            order.append((x - MX, y - MY))
            if C[y, x] == WATER:
                break
            best, bs = None, 1e9
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if not (dx or dy):
                        continue
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < GW and 0 <= ny < GH) or (nx, ny) in seen:
                        continue
                    pen = 0.35 * max(0.0, 1 - np.hypot(nx - MX - PLAZA[0], ny - MY - PLAZA[1]) / 6.0)
                    s = E[ny, nx] - 0.015 * dx + pen + 0.02 * th("r", nx, ny)
                    if s < bs:
                        best, bs = (nx, ny), s
            if best is None:
                break
            x, y = best
            C[y, x] = WATER
            E[y, x] = min(E[y, x], 0.29)
        self.river = order

    def _shoreline(self):
        C = self.C
        nb = np.zeros(C.shape, bool)
        nb[1:, :] |= C[:-1, :] == WATER
        nb[:-1, :] |= C[1:, :] == WATER
        nb[:, 1:] |= C[:, :-1] == WATER
        nb[:, :-1] |= C[:, 1:] == WATER
        C[(C != WATER) & nb & (C != HILL)] = SAND

    # ------------------------------------------------------------ village layout
    def cls(self, tx, ty):
        return int(self.C[ty + MY, tx + MX])

    def mark_path(self, a, b, wear, join=True):
        """Wear a trail from a to b. With join=True it stops at the nearest existing trail tile instead
        of running all the way, so trails branch like footpaths rather than forming a grid. Steps
        alternate x/y by the slope, so the line meanders instead of one hard L."""
        (x0, y0), (x1, y1) = a, b
        if join and self.paths:
            near = min(self.paths, key=lambda p: abs(p[0] - x0) + abs(p[1] - y0) + 0.35 * (abs(p[0] - x1) + abs(p[1] - y1)))
            x1, y1 = near
        x, y = x0, y0
        pts = [(x, y)]
        guard = 0
        while (x, y) != (x1, y1) and guard < 200:
            guard += 1
            dx, dy = x1 - x, y1 - y
            jitter = th("j", x, y, wear) < 0.5
            if dx and (not dy or abs(dx) > abs(dy) or (abs(dx) == abs(dy) and jitter)):
                x += 1 if dx > 0 else -1
            else:
                y += 1 if dy > 0 else -1
            pts.append((x, y))
        for p in pts:
            if self.cls(*p) in (GRASS, MEADOW, FOREST, SAND):
                self.paths[p] = max(self.paths.get(p, 0), wear)

    def layout(self, builders, farm_at=(6, 3), dawn=False):
        px, py = PLAZA
        self.mark_path((px - 1, py), (px + 1, py), 2, join=False)
        self.statics.append(("well", (px * T + T // 2, py * T + T // 2 + 14)))
        taken = {(px, py), (px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)}
        n = len(builders)
        for i, (name, tier) in enumerate(builders):
            a = -math.pi / 2 + i * 2 * math.pi / max(n, 1) + (th("a", name) - 0.5) * 0.5
            r = 4.6 + th("r", name) * 1.6
            tx, ty = px, py
            for _ in range(14):
                tx = int(round(px + r * math.cos(a) * 1.25))
                ty = int(round(py + r * math.sin(a) * 0.85))
                ok = (2 <= tx < COLS - 2 and 2 <= ty < ROWS - 1 and self.cls(tx, ty) in (GRASS, MEADOW, FOREST)
                      and all(abs(tx - qx) + abs(ty - qy) > 3 for (qx, qy) in taken))
                if ok:
                    break
                a += 0.35
                r += 0.15
            taken.add((tx, ty))
            self.huts.append((name, tier, (tx * T + T // 2, ty * T + T // 2 + 14)))
            for dx in (-1, 0, 1):
                for dy in (-2, -1, 0):
                    cy, cx = ty + dy + MY, tx + dx + MX
                    if self.C[cy, cx] in (FOREST, MEADOW):
                        self.C[cy, cx] = GRASS
            self.mark_path((tx, ty + 1), (px, py), 1)
        if not dawn:
            fx, fy = px + farm_at[0], py + farm_at[1]
            k = 0
            for dy in range(2):
                for dx in range(3):
                    if self.cls(fx + dx, fy + dy) in (GRASS, MEADOW):
                        self.farm[(fx + dx, fy + dy)] = [1, 2, 3, 2, 1, 0][k]
                        self.C[fy + dy + MY, fx + dx + MX] = FARM
                    k += 1
            self.mark_path((fx - 1, fy + 1), (px, py), 1)
            self.mark_path((px + 11, py + 2), (px, py), 1)          # trail from the water
            self.mark_path((px - 9, py - 1), (px, py), 1)           # trail from the forest
            self.statics.append(("cairn", ((px - 6) * T + 16, (py - 3) * T + 24)))
            self.statics.append(("sign", ((px + 10) * T + 20, (py + 2) * T + 8)))
            for (lx, ly) in ((px + 3, py + 1), (px + 7, py + 2), (px - 4, py - 1)):
                self.lanterns.append((lx * T + 8, ly * T + 10))
            self.statics.append(("garden", ((px + 2) * T, (py - 3) * T + 20)))
        hut_tiles = {((x - T // 2) // T, (y - 14 - T // 2) // T) for (_, _, (x, y)) in self.huts}
        for ty in range(-2, ROWS + 2):
            for tx in range(-2, COLS + 2):
                c = self.cls(tx, ty)
                h = th("p", tx, ty)
                near_v = math.hypot(tx - px, ty - py) < 3.2
                near_hut = any(abs(tx - hx) <= 1 and -2 <= ty - hy <= 1 for (hx, hy) in hut_tiles)
                if (tx, ty) in self.paths or (tx, ty) in self.farm or near_v or near_hut:
                    continue
                cx, cy = tx * T + int(6 + h * 20), ty * T + int(10 + th("q", tx, ty) * 20)
                if c == FOREST:
                    size = 2 if h > 0.55 else (1 if h > 0.2 else 0)
                    kind = "pine" if (th("k", tx, ty) < 0.30 or self.E[ty + MY, tx + MX] > 0.66) else "tree"
                    self.props.append((kind, (size, int(th("s", tx, ty) * 3)), (cx, cy)))
                    if th("t2", tx, ty) > 0.55:
                        self.props.append(("tree", (0 if h > 0.5 else 1, int(th("s2", tx, ty) * 3)), (cx + 14 - int(28 * th("t3", tx, ty)), cy + 10)))
                elif c == GRASS and h > 0.955:
                    self.props.append(("tree", (1 if h > 0.98 else 0, int(th("s", tx, ty) * 3)), (cx, cy)))
                elif c in (GRASS, MEADOW) and 0.90 < h <= 0.955:
                    self.props.append(("bush", int(th("b", tx, ty) * 2), (cx, cy)))
                elif c == HILL and h > 0.72:
                    self.props.append(("rock", int(h * 2) % 2, (cx, cy)))
                elif c == SAND and h > 0.5:
                    wet = any(self.cls(tx + dx, ty + dy) == WATER for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                    if wet:
                        self.props.append(("reeds", int(h * 2) % 2, (cx, cy)))

    # ------------------------------------------------------------ strict tile-blit naming (autotile path)
    def tile_name(self, tx, ty, phase):
        c = self.cls(tx, ty)
        h = th("v", tx, ty)
        e = float(self.E[ty + MY, tx + MX])

        def nb(pred):
            m = 0
            for bit, (dx, dy) in ((1, (0, -1)), (2, (1, 0)), (4, (0, 1)), (8, (-1, 0))):
                if pred(self.cls(tx + dx, ty + dy)):
                    m |= bit
            return m
        if c == WATER:
            return "water:%s:p%d" % ("deep" if e < 0.20 else "shallow", phase)
        if c == SAND:
            m = nb(lambda k: k == WATER)
            return "shore:%d:p%d" % (m, phase) if m else "sand:v%d" % int(h * 2)
        if c == FARM:
            return "farm:%d" % self.farm.get((tx, ty), 0)
        m_sand = nb(lambda k: k in (SAND, WATER))
        if m_sand:
            return "sandgrass:%d" % m_sand
        if c == HILL:
            m = nb(lambda k: k != HILL)
            return "hilledge:%d" % m if m else "hill:v%d" % int(h * 2)
        if c == FOREST:
            m = nb(lambda k: k in (GRASS, MEADOW, FARM))
            return "forestedge:%d" % m if m else "forest:v%d" % int(h * 2)
        if c == MEADOW:
            return "meadow:v%d:p%d" % (int(h * 2), phase)
        return "grass:v%d:p%d" % (int(h * 4), phase)

    def path_name(self, tx, ty):
        wear = self.paths[(tx, ty)]
        m = 0
        for bit, (dx, dy) in ((1, (0, -1)), (2, (1, 0)), (4, (0, 1)), (8, (-1, 0))):
            if (tx + dx, ty + dy) in self.paths:
                m |= bit
        return "path:%d:%d" % (wear, m)

    # ------------------------------------------------------------ pixel fields for splatting
    def pixel_fields(self):
        Hp, Wp = ROWS * T, COLS * T
        py, px = np.mgrid[0:Hp, 0:Wp].astype(np.float32)
        E, M = fields((px + 0.5) / T, (py + 0.5) / T, self.seed)
        # carve the river in pixel space along the traced tile centres
        if len(self.river) > 1:
            mask = Image.new("L", (Wp, Hp), 0)
            d = ImageDraw.Draw(mask)
            pts = [(tx * T + T // 2, ty * T + T // 2) for (tx, ty) in self.river]
            for i in range(len(pts) - 1):
                wdt = int(9 + 9 * i / len(pts))
                d.line([pts[i], pts[i + 1]], fill=255, width=wdt)
                d.ellipse([pts[i][0] - wdt // 2, pts[i][1] - wdt // 2, pts[i][0] + wdt // 2, pts[i][1] + wdt // 2], fill=255)
            f = np.asarray(mask.filter(ImageFilter.GaussianBlur(5)), np.float32) / 255.0
            f = np.clip(f * 1.5, 0, 1)
            E = E * (1 - f) + np.minimum(E, 0.262) * f
        if self.village:
            d = np.hypot(px / T - PLAZA[0] - 0.5, py / T - PLAZA[1] - 0.5)
            clear = sstep(d, 6.8, 5.6)
        else:
            clear = np.zeros_like(E)
        return E, M, clear


# ----------------------------------------------------------------------------- the view (compositor side)
class WorldView:
    def __init__(self, wm, atlas, evening=True, dawn=False):
        self.wm, self.atlas = wm, atlas
        self.evening, self.dawn = evening, dawn
        self.cache = creatures.SpriteCache()
        self.hut_sprites = {(n, t): buildings.hut(n, t) for (n, t, _) in wm.huts}
        self.static_sprites = {"well": buildings.well(), "cairn": buildings.cairn(), "sign": buildings.sign(),
                               "garden": buildings.garden_bed(), "lantern": buildings.lantern()}
        self.Ep, self.Mp, self.clear = wm.pixel_fields()
        self.base = [self._bake(p) for p in range(4)]
        self.tinted = [self._tint(b) for b in self.base]       # time-of-day applied once (re-run on a tint change)
        self.lit = [b.copy() for b in self.tinted]
        self.slice_h = int(math.ceil(WH / SLICES))
        for p in range(4):
            for k in range(SLICES):
                self.relight_slice(p, k, 0.0)
        self.plates = {}
        self._lant = self._glow_sprite(34, (255, 190, 90), 0.75)
        self._win = self._glow_sprite(22, (255, 200, 110), 0.45)

    # ---- terrain splat
    def _texture(self, family, phase):
        """full-region texture tiled from the atlas family, variant per tile by hash."""
        A = self.atlas.tiles
        img = np.zeros((ROWS * T, COLS * T, 3), np.uint8)
        for ty in range(ROWS):
            for tx in range(COLS):
                h = th("v", tx, ty)
                if family == "grass":
                    n = "grass:v%d:p%d" % (int(h * 4), phase)
                elif family == "meadow":
                    n = "meadow:v%d:p%d" % (int(h * 2), phase)
                elif family == "water":
                    n = "water:shallow:p%d" % phase
                else:
                    n = "%s:v%d" % (family, int(h * 2))
                img[ty * T:(ty + 1) * T, tx * T:(tx + 1) * T] = A[n][..., :3]
        return img.astype(np.float32)

    def _bake(self, phase):
        wm, A = self.wm, self.atlas.tiles
        E, M, clear = self.Ep, self.Mp, self.clear
        img = self._texture("grass", phase)
        m_meadow = sstep(M, M_MEADOW + 0.02, M_MEADOW - 0.02) * (1 - clear)
        m_forest = sstep(M, M_FOREST - 0.02, M_FOREST + 0.02) * (1 - clear)
        m_hill = sstep(E, E_HILL - 0.015, E_HILL + 0.015)
        m_sand = sstep(E, E_SAND + 0.012, E_SAND - 0.012)
        m_water = sstep(E, E_WATER + 0.008, E_WATER - 0.008)
        def mixin(fam, m):
            nonlocal img
            tex = self._texture(fam, phase)
            img = img * (1 - m[..., None]) + tex * m[..., None]
        mixin("meadow", m_meadow)
        mixin("forest", m_forest)
        # hill lip: a darker line just below the hill threshold, lighter just above (reads as a step)
        lip = np.clip(1 - np.abs(E - (E_HILL - 0.012)) / 0.012, 0, 1)
        img = img * (1 - 0.35 * lip[..., None])
        mixin("hill", m_hill)
        # wet sand next to the water
        img_sand = self._texture("sand", phase)
        wet = sstep(E, E_WATER + 0.035, E_WATER + 0.008)
        img_sand = img_sand * (1 - 0.18 * wet[..., None])
        img = img * (1 - m_sand[..., None]) + img_sand * m_sand[..., None]
        # water with depth shading and a foam line
        wat = self._texture("water", phase)
        deep = np.clip((E_WATER - E) / 0.11, 0, 1)
        wat = wat * (1 - 0.55 * deep[..., None]) + np.array(tiles.WATER_DEEP, np.float32) * 0.55 * deep[..., None] * 0.6
        foam = np.clip(1 - np.abs(E - (E_WATER - 0.006)) / 0.010, 0, 1)
        foam = foam * (0.55 + 0.45 * np.sin(np.arange(img.shape[1], dtype=np.float32)[None, :] / 5.0 + phase * math.pi / 2 + np.arange(img.shape[0], dtype=np.float32)[:, None] / 7.0))
        wat = wat * (1 - foam[..., None] * 0.6) + np.array((236, 246, 250), np.float32) * foam[..., None] * 0.6
        img = img * (1 - m_water[..., None]) + wat * m_water[..., None]
        img = np.clip(img, 0, 255).astype(np.uint8)
        self.water_mask = np.ascontiguousarray(m_water[:WH, :, None])
        # man-made, tile aligned: farm plots and worn paths
        for (tx, ty), stage in wm.farm.items():
            if 0 <= tx < COLS and 0 <= ty < ROWS:
                img[ty * T:(ty + 1) * T, tx * T:(tx + 1) * T] = A["farm:%d" % stage][..., :3]
        for (tx, ty) in wm.paths:
            if 0 <= tx < COLS and 0 <= ty < ROWS:
                blit(img, A[wm.path_name(tx, ty)], tx * T, ty * T)
        items = []
        for kind, var, (x, y) in wm.props:
            if kind == "tree":
                spr = self.atlas.props["tree:%d:%d:s%d" % (var[0], var[1], SWAY[phase])]
            elif kind == "pine":
                spr = self.atlas.props["pine:%d:s%d" % (var[0], SWAY[phase])]
            else:
                spr = self.atlas.props["%s:%d" % (kind, var)]
            items.append((y, spr, x - spr.shape[1] // 2, y - spr.shape[0]))
        for kind, (x, y) in wm.statics:
            spr = self.static_sprites[kind]
            items.append((y, spr, x - spr.shape[1] // 2, y - spr.shape[0]))
        for (x, y) in wm.lanterns:
            spr = self.static_sprites["lantern"]
            items.append((y, spr, x - spr.shape[1] // 2, y - spr.shape[0]))
        for name, tier, (x, y) in wm.huts:
            spr = self.hut_sprites[(name, tier)]
            items.append((y, spr, x - spr.shape[1] // 2, y - spr.shape[0]))
        items.sort(key=lambda it: it[0])
        for _, spr, x, y in items:
            blit(img, spr, x, y)
        return np.ascontiguousarray(img[:WH])

    # ---- lighting
    def _lowres_rows(self, field_fn, y0, y1):
        """Evaluate a 1/8-res field only for the low-res rows covering [y0, y1), upsample, crop. Cheap."""
        ly0 = max(0, y0 // 8 - 1)
        ly1 = min(WH // 8 + 1, (y1 + 7) // 8 + 1)
        v, u = np.mgrid[ly0:ly1, 0:W // 8].astype(np.float32)
        f = np.clip(field_fn(u, v), 0, 1)
        up = Image.fromarray((f * 255).astype(np.uint8)).resize((W, (ly1 - ly0) * 8), Image.BILINEAR)
        arr = np.asarray(up, np.float32)
        return arr[y0 - ly0 * 8:y1 - ly0 * 8, :, None] * (1.0 / 255.0)

    def _tint(self, base):
        """Time-of-day grade, whole region, float once. Water takes its own tint so dusk stays blue on
        the sea and warm on the land; dawn adds a mist bank toward the water. Runs when the hour changes
        (a few times a session), never per frame."""
        img = base.astype(np.float32)
        if self.evening:
            land = img * np.array([1.06, 0.82, 0.62], np.float32) + np.array([12, 2, 0], np.float32)
            water = img * np.array([0.82, 0.84, 1.02], np.float32) + np.array([4, 8, 24], np.float32)
            img = land * (1 - self.water_mask) + water * self.water_mask
        elif self.dawn:
            img = img * np.array([0.90, 0.93, 1.04], np.float32) + np.array([6, 6, 14], np.float32)
            def mist_fn(u, v):
                m = np.clip((u - 16) / 90.0, 0, 1) * 0.45 + np.clip((v - 30) / 40.0, 0, 1) * 0.25
                return m * (0.7 + 0.3 * fbm(u, v, 1 / 12.0, 2, SEED + 5))
            mist = self._lowres_rows(mist_fn, 0, WH)
            img = img * (1 - mist) + np.array([222, 226, 236], np.float32) * mist
        return np.clip(img, 0, 255).astype(np.uint8)

    def relight_slice(self, phase, k, t):
        """Drifting cloud shadow over rows [k*slice_h, (k+1)*slice_h) of one phase, integer math on the
        pre-tinted frame: about 1 ms per slice, one slice per frame."""
        y0 = k * self.slice_h
        y1 = min(WH, y0 + self.slice_h)
        if y1 <= y0:
            return
        amp = 0.18 if not self.dawn else 0.10
        cl = self._lowres_rows(lambda u, v: (fbm(u + t * 1.5, v + t * 0.4, 1 / 22.0, 3, SEED + 99) - 0.50) * 3.2, y0, y1)
        k16 = (256 - (cl * (amp * 256)).astype(np.uint16))
        src = self.tinted[phase][y0:y1].astype(np.uint16)
        self.lit[phase][y0:y1] = ((src * k16) >> 8).astype(np.uint8)

    def _glow_sprite(self, r, col, k):
        ys, xs = np.mgrid[0:2 * r, 0:2 * r].astype(np.float32)
        d = np.hypot(xs - r + 0.5, ys - r + 0.5) / r
        a = np.clip(1 - d, 0, 1) ** 2.0 * k
        return (a[..., None] * np.asarray(col, np.float32)).astype(np.float32)

    # ---- speech plates (pre-rendered, cached)
    def plate(self, name, text):
        key = (name, text)
        s = self.plates.get(key)
        if s is None:
            layer = Image.new("RGBA", (W, 60), (0, 0, 0, 0))
            box = hud.speech_plate(layer, (W // 2, 50), text, name, creatures.dot_colour(name), above=True)
            arr = np.asarray(layer.crop((box[0], box[1], box[2] + 1, box[3] + 9)))
            self.plates[key] = (arr, W // 2 - box[0])
        return self.plates[key]

    # ---- per-frame composite
    def frame(self, actors, phase, plates=(), t=0.0):
        """actors: list of dicts(name, tier, frame, x, y, facing). plates: (name, text, x, y_top_of_creature).
        Returns the 1280x440 world RGB uint8."""
        out = self.lit[phase].copy()
        if self.evening:
            fl = 0.9 + 0.1 * math.sin(t * 9.0)
            for i, (x, y) in enumerate(self.wm.lanterns):
                g = self._lant if (i + int(t * 7)) % 3 else (self._lant * fl)
                blit_add(out, g, x - 34, y - 34 - 20)
            for name, tier, (x, y) in self.wm.huts:
                if tier >= 1:
                    blit_add(out, self._win, x - 22, y - 22 - 6)
        order = sorted(actors, key=lambda a: a["y"])
        if self.evening:
            for a in order:
                blit_add(out, self.cache.glow(a["name"], 26), a["x"] - 26, a["y"] - 26 - 14)
        for a in order:
            spr = self.cache.get(a["name"], a["tier"], a["frame"], a.get("facing", 1))
            ax, ay = creatures.anchor(a["tier"])
            blit(out, spr, a["x"] - ax, a["y"] - ay)
        placed = []
        for (name, text, x, ytop) in sorted(plates, key=lambda p: p[3]):
            s, tail_dx = self.plate(name, text)
            h, w = s.shape[:2]
            px = min(max(int(x - tail_dx), 4), W - w - 4)
            py = int(ytop) - h - 2
            for _ in range(6):   # nudge up while overlapping an earlier plate
                if any(px < bx + bw and px + w > bx and py < by + bh and py + h > by for (bx, by, bw, bh) in placed):
                    py -= h + 4
                else:
                    break
            py = max(4, py)
            blit(out, s, px, py)
            placed.append((px, py, w, h))
        return out


# ----------------------------------------------------------------------------- frames
BUSY = [  # name, tier, frame, offset from the plaza centre (px) or None = beside own hut, facing
    ("kai_dnb", 2, "speak", (-56, 30), 1),
    ("sami.exe", 1, "emote1", (34, 34), -1),
    ("noor.wav", 1, "walk0", (150, 96), 1),
    ("xXvtobiXx", 1, "hop", (-10, -70), 1),
    ("mira_9", 1, "sleep", None, 1),
    ("lowkeyjord", 2, "idle1", (-290, -30), 1),
    ("zed_ttv", 1, "emote0", (-160, -96), -1),
    ("luca_99", 0, "walk1", (300, 70), 1),
    ("pixel_dude", 1, "idle0", (420, 36), -1),
    ("ana.banana", 1, "speak", (110, -48), -1),
    ("tobes", 0, "blink", (60, -58), 1),
    ("mxrkus", 1, "walk0", (-140, 44), -1),
    ("Quill_", 2, "idle0", (222, 128), -1),
    ("hey_its_ren", 0, "sleep", None, 1),
]
BUILDERS_BUSY = [("kai_dnb", 2), ("sami.exe", 1), ("noor.wav", 1), ("xXvtobiXx", 1), ("mira_9", 1),
                 ("lowkeyjord", 2), ("zed_ttv", 1), ("Quill_", 2), ("hey_its_ren", 0)]
BUILDERS_DAWN = [("kai_dnb", 1), ("mira_9", 0)]
CHAT_BUSY = [("kai_dnb", "B"), ("sami.exe", "we need a bridge over it"), ("noor.wav", "planting by the water"),
             ("zed_ttv", "hop hop hop"), ("ana.banana", "bridge!! yes")]


def actors_for(wm, roster):
    px, py = PLAZA[0] * T + T // 2, PLAZA[1] * T + T // 2
    huts = {n: pos for (n, t, pos) in wm.huts}
    out = []
    for name, tier, frame, off, facing in roster:
        if off is None:
            hx, hy = huts.get(name, (px, py))
            x, y = hx + 50, hy + 6
        else:
            x, y = px + off[0], py + off[1]
        out.append(dict(name=name, tier=tier, frame=frame, x=int(x), y=int(y), facing=facing))
    return out


def minimap(wm, box_wh):
    """A class map of a wider area with the viewport marked. Pure colour, no text."""
    mw, mh = box_wh
    v, u = np.mgrid[0:60, 0:120].astype(np.float32)
    E, M = fields(u - 40 + 0.5, v - 22 + 0.5, wm.seed)
    img = np.zeros((60, 120, 3), np.uint8)
    img[...] = (110, 150, 84)
    img[M > M_FOREST] = (78, 120, 64)
    img[E > E_HILL] = (150, 156, 96)
    img[E < E_SAND] = (222, 200, 150)
    img[E < E_WATER] = (70, 124, 160)
    seen = np.zeros((60, 120), bool)
    seen[22:22 + ROWS, 40:40 + COLS] = True
    img[~seen] = (img[~seen] * 0.45 + np.array([46, 32, 52]) * 0.55).astype(np.uint8)
    im = Image.fromarray(img).resize((mw, mh), Image.NEAREST)
    d = ImageDraw.Draw(im)
    sx, sy = mw / 120.0, mh / 60.0
    d.rectangle([40 * sx, 22 * sy, (40 + COLS) * sx, (22 + ROWS) * sy], outline=(246, 196, 100), width=2)
    return im


def compose(world_rgb, mode, wm):
    """Full 1280x720 frame: header + world + footer (hud.py). The only text over the world is creature
    speech (already in world_rgb) and the three vote markers."""
    frame = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    frame.paste(Image.fromarray(world_rgb), (0, WY0))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    S = hud.STYLE
    busy = mode == "busy"
    if busy:
        hud.header(layer, "atleastonce", "SETTLEMENT  ·  studio-a", "14 SETTLED · 12 AWAKE", "LIVE  ·  7 watching", "NEXT EVENT  01:23")
    else:
        hud.header(layer, "atleastonce", "SETTLEMENT  ·  studio-a", "2 SETTLED · 0 AWAKE", "LIVE  ·  1 watching", "NEXT EVENT  02:41")
    hud.footer_base(layer, "concept render  ·  names are examples  ·  studio-a  ·  seed %d  ·  40x14 tiles of 256x256" % wm.seed)
    y0, y1 = hud.PANEL_Y0, hud.PANEL_Y1
    c1 = hud.panel(layer, (12, y0, 372, y1), "COLONY")
    c2 = hud.panel(layer, (384, y0, 744, y1), "KEEPER")
    c3 = hud.panel(layer, (756, y0, 1116, y1), "CHAT")
    hud.sun_dial(layer, (1128, y0, 1268, y0 + 52), 18.1 if busy else 6.7, busy)
    mm = minimap(wm, (138, 68))
    layer.paste(mm, (1129, y0 + 59))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([1128, y0 + 58, 1268, y0 + 128], radius=6, outline=S["panel_border"], width=1)
    d.text((1128, y0 + 134), "3% explored" if busy else "2% explored", font=hud.font("body", 20), fill=S["ink_muted"])
    ink, mut, acc = S["ink"], S["ink_muted"], S["accent"]
    col = creatures.dot_colour
    if busy:
        hud.lines(layer, c1, [
            [("14 settled", ink), ("  ·  12 awake  ·  2 asleep", mut)],
            [("day 5  ·  evening  ·  wind E, fresh", mut)],
            [("6 more settle ", mut), ("and the Mill opens", ink)],
            [("last event: rain, by ", mut), ("@sami.exe", col("sami.exe"))],
        ])
        hud.lines(layer, c2, [
            [("keeper on duty", ink), ("  ·  carving lanterns", mut)],
            [("event: where does the well go?", ink)],
            [("A", acc), (" river 4   ", ink), ("B", acc), (" plaza 7   ", ink), ("C", acc), (" hill 1", ink)],
            [("say A, B or C in chat", mut)],
        ])
        hud.lines(layer, c3, [[("@" + n, col(n)), ("  " + t, ink)] for n, t in CHAT_BUSY[-4:]])
    else:
        hud.lines(layer, c1, [
            [("2 settled", ink), ("  ·  nobody awake  ·  day 2", mut)],
            [("06:41  ·  dawn  ·  wind NE, light", mut)],
            [("say anything in chat.", ink)],
            [("a creature hatches with your name.", ink)],
        ])
        hud.lines(layer, c2, [
            [("no keeper on duty", mut)],
            [("scrolls kept for next time", mut)],
            [("last raised: a stake, by ", mut), ("@mira_9", col("mira_9"))],
        ])
        hud.lines(layer, c3, [[("chat is quiet. say anything.", mut)]])
    if busy:
        px, py = PLAZA[0] * T + T // 2, WY0 + PLAZA[1] * T + T // 2
        for letter, count, (x, y) in (("A", 4, (px + 250, py - 74)), ("B", 7, (px + 66, py + 66)), ("C", 1, (px - 300, py - 130))):
            d.ellipse([x - 16, y - 16, x + 16, y + 16], fill=S["plate_fill"], outline=acc, width=2)
            d.text((x - 7, y - 12), letter, font=hud.font("title", 20), fill=acc)
            d.text((x + 20, y - 12), str(count), font=hud.font("body_bold", 20), fill=ink)
    return Image.alpha_composite(frame, layer).convert("RGB")


def render_all():
    atlas = tiles.Atlas("summer")
    wm = WorldMap(SEED)
    wm.layout(BUILDERS_BUSY)
    view = WorldView(wm, atlas, evening=True)
    actors = actors_for(wm, BUSY)
    pos = {a["name"]: (a["x"], a["y"]) for a in actors}
    plates = [("kai_dnb", "B! the well goes by the plaza", pos["kai_dnb"][0], pos["kai_dnb"][1] - 52),
              ("noor.wav", "planting by the water, who's with me", pos["noor.wav"][0], pos["noor.wav"][1] - 44),
              ("ana.banana", "we need a bridge over it", pos["ana.banana"][0], pos["ana.banana"][1] - 44)]
    world = view.frame(actors, 1, plates, t=3.0)
    busy = compose(world, "busy", wm)
    busy.save(os.path.join(HERE, "mockup_busy.png"))
    busy.resize((320, 180), Image.LANCZOS).save(os.path.join(HERE, "thumb_320x180.png"))
    wm2 = WorldMap(SEED)
    wm2.layout(BUILDERS_DAWN, dawn=True)
    view2 = WorldView(wm2, atlas, evening=False, dawn=True)
    actors2 = actors_for(wm2, [("kai_dnb", 1, "sleep", None, 1), ("mira_9", 0, "sleep", None, -1)])
    compose(view2.frame(actors2, 0), "dawn", wm2).save(os.path.join(HERE, "mockup_dawn.png"))
    return view, wm


def bench(view, n=300, creatures_n=20):
    names = [r[0] for r in BUSY] + ["qwerty_uiop", "big_mood", "jinx.exe", "ok_boomer", "lil_sprout", "marrow"]
    names = names[:creatures_n]
    for nm in names:
        view.cache.warm(nm, tiers=(1,))
    rs = np.random.RandomState(1)
    actors = [dict(name=nm, tier=1, frame="idle0", x=int(rs.randint(40, W - 40)), y=int(rs.randint(40, WH - 10)), facing=1) for nm in names]
    plates = [("kai_dnb", "B! the well goes by the plaza", 400, 200), ("noor.wav", "planting by the water", 800, 300),
              ("ana.banana", "we need a bridge over it", 600, 380)]
    view.frame(actors, 0, plates)
    ts = []
    for f in range(n):
        t0 = time.perf_counter()
        phase = (f // 8) % 4
        for a in actors:
            a["frame"] = creatures.FRAMES[(f // 6 + hash(a["name"])) % len(creatures.FRAMES)]
            a["x"] = (a["x"] + 1) % W
        view.relight_slice((phase + 1) % 4, f % SLICES, f / 30.0)      # one slice per frame
        view.frame(actors, phase, plates, t=f / 30.0)
        ts.append((time.perf_counter() - t0) * 1000)
    ts = np.array(ts)
    return dict(avg=float(ts.mean()), p95=float(np.percentile(ts, 95)), max=float(ts.max()))


if __name__ == "__main__":
    t0 = time.time()
    view, wm = render_all()
    print("rendered in %.1fs" % (time.time() - t0))
    b = bench(view)
    print("world frame ms (20 creatures, glows, 3 plates, lantern flicker, 1 relight slice): avg %.2f  p95 %.2f  max %.2f" % (b["avg"], b["p95"], b["max"]))
