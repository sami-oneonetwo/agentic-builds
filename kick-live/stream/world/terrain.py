"""terrain.py - LONGGRASS map generation (docs/OPENWORLD.md section 4.1): seed -> a persistent 960x440-cell land.

One cell = 4x4 screen px at the 1x zoom; 8 cells = one 32 px tile of the art atlas (stream/world/art/tiles). The map is
generated ONCE from `world.map_seed` and never regenerated in place, so every mark stays where a real person left it.
Generation is fully procedural and deterministic (numpy only): the method of the approved mockup
(docs/mockups/topdown_render.py) at cell resolution:

    fbm value noise -> elevation with a gradient so the sea lies to the south-east; a second noise for moisture
    sea = water connected to the map border (ponds are the rest); tile-res distance to the sea
    whole-map SITE SEARCH: flat grassland 9-12 tiles from the sea, hills to the north-west, forest in reach, no pond
        in the first frame, the first 320x110 frame never shows the map edge
    river TRACED downhill from the Fell past the site to the sea and CARVED 6-14 cells wide; one shallow FORD beside
        the Steading with stepping stones; sand banks; the Reed Marsh on the low wet river ground
    biomes; the Wood (dense trees to the east; trunks impassable, edges passable) and the Fell's boulders as CONVEX
        blobs so the behaviour slide rule cannot stick; the MOOT green = the largest flat short-grass disc at the site
    passable / cost / caster layers, a coarse 60x28 BFS route grid (16-cell blocks), a places registry

    from stream.world import terrain
    T = terrain.generate(4471)                   # cached per (seed, w, h); ~1-2 s on the M3 Pro
    T.biome[y, x]  T.passable[y, x]  T.cost[y, x]  T.caster[y, x]  T.water[y, x]      # uint8 / bool (440, 960)
    T.cells()                                    # int8 tiles.CAT map for the ground painter (bake.py adds marks)
    T.places["moot"] -> {"name", "x", "y", "radius"}; T.route((x0, y0), (x1, y1)) -> [(x, y), ...] cell waypoints
    T.save_png("/tmp/lg-gate/map.png")           # the review PNG the seed is committed from

Everything here is nature: no name, no mark, no person. Marks (wear, camps, fields, planted things) live in
world.json and are painted over this by bake.py. Python 3.9, numpy + pillow only.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np

MAP_W, MAP_H = 960, 440          # cells
CELL = 4                         # screen px per cell at 1x
TILE = 8                         # cells per 32 px atlas tile
SEA = 0.30                       # sea level in elevation units
BLOCK = 16                       # cells per coarse route block
VIEW_W, VIEW_H = 320, 110        # the 1x window in cells
EDGE_MARGIN = 12                 # the window never shows the outermost 12 cells (OPENWORLD 4.4 clamp)
NOISE = 4.0                      # cells per noise unit (see Terrain._fields)
COAST_G = 0.25                   # the sea lies where the NW->SE gradient drops under this (a bay over the SE corner)

# biome ids (uint8). Water first so `biome <= B_FORD` is "some kind of water".
B_DEEP, B_SHALLOW, B_RIVER, B_FORD, B_SAND, B_GRASS, B_MEADOW, B_FOREST, B_HILL, B_ROCK, B_MARSH = range(11)
BIOME_NAMES = ("deep", "shallow", "river", "ford", "sand", "grass", "meadow", "forest", "hill", "rock", "marsh")
WATER_BIOMES = (B_DEEP, B_SHALLOW, B_RIVER)            # the ford is water you can wade
PASSABLE_BIOMES = (B_FORD, B_SAND, B_GRASS, B_MEADOW, B_FOREST, B_HILL, B_MARSH)
COST = {B_FORD: 3, B_SAND: 2, B_GRASS: 1, B_MEADOW: 1, B_FOREST: 1, B_HILL: 2, B_MARSH: 3}
# review / fallback / minimap colours per biome (summer; the painted bake carries the real season)
BIOME_RGB = np.array([
    (46, 112, 166), (92, 178, 206), (98, 176, 204), (140, 196, 210), (234, 214, 160), (104, 164, 78), (122, 176, 84),
    (70, 128, 66), (156, 166, 100), (146, 142, 130), (92, 140, 96)], np.uint8)

_CACHE: Dict[Tuple[int, int, int], "Terrain"] = {}


# ----------------------------------------------------------------------------- noise (the mockup's, at cell res)
def _hash2(i: np.ndarray, j: np.ndarray, seed: int) -> np.ndarray:
    i = i.astype(np.int64)
    j = j.astype(np.int64)
    n = (i * 374761393 + j * 668265263 + int(seed) * 1013904223) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    n = (n ^ (n >> 16)) & 0xFFFFFFFF
    return n.astype(np.float32) / np.float32(4294967295.0)


def vnoise(u: np.ndarray, v: np.ndarray, freq: float, seed: int) -> np.ndarray:
    x, y = u * freq, v * freq
    xi, yi = np.floor(x), np.floor(y)
    fx, fy = (x - xi).astype(np.float32), (y - yi).astype(np.float32)
    sx = fx * fx * fx * (fx * (fx * 6 - 15) + 10)
    sy = fy * fy * fy * (fy * (fy * 6 - 15) + 10)
    a, b = _hash2(xi, yi, seed), _hash2(xi + 1, yi, seed)
    c, d = _hash2(xi, yi + 1, seed), _hash2(xi + 1, yi + 1, seed)
    return (a * (1 - sx) + b * sx) * (1 - sy) + (c * (1 - sx) + d * sx) * sy


def fbm(u: np.ndarray, v: np.ndarray, freq: float, octaves: int, seed: int, gain: float = 0.5) -> np.ndarray:
    total, amp, norm = np.zeros_like(u, dtype=np.float32), 1.0, 0.0
    for o in range(octaves):
        total += amp * vnoise(u, v, freq, seed + o * 101)
        norm += amp
        amp *= gain
        freq *= 2.0
    return total / norm


def box_blur(a: np.ndarray, r: int, passes: int = 2) -> np.ndarray:
    """Separable float box blur (cumsum), repeated to approximate a gaussian."""
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


def _grow(mask: np.ndarray) -> np.ndarray:
    g = mask.copy()
    g[1:, :] |= mask[:-1, :]
    g[:-1, :] |= mask[1:, :]
    g[:, 1:] |= mask[:, :-1]
    g[:, :-1] |= mask[:, 1:]
    return g


def dilate(mask: np.ndarray, r: int) -> np.ndarray:
    """4-neighbour dilation by r cells (a diamond); enough for margins and `walked` halos."""
    out = mask.copy()
    for _ in range(int(r)):
        out = _grow(out)
    return out


def distance_field(src: np.ndarray, limit: int) -> np.ndarray:
    """Chessboard-ish BFS distance (in cells) from `src` cells, capped at `limit` (float32, inf beyond)."""
    D = np.where(src, 0.0, np.inf).astype(np.float32)
    front = src.copy()
    for k in range(1, int(limit) + 1):
        grown = _grow(front)
        newly = grown & ~front
        if not newly.any():
            break
        D[newly] = k
        front = grown
    return D


def _disc(r: float) -> np.ndarray:
    n = int(math.ceil(r))
    yy, xx = np.mgrid[-n:n + 1, -n:n + 1]
    return (xx * xx + yy * yy) <= r * r


def _stamp(mask: np.ndarray, x: int, y: int, disc: np.ndarray, value=True) -> None:
    n = disc.shape[0] // 2
    H, W = mask.shape[:2]
    x0, y0, x1, y1 = x - n, y - n, x + n + 1, y + n + 1
    sx0, sy0 = max(0, -x0), max(0, -y0)
    sx1, sy1 = disc.shape[1] - max(0, x1 - W), disc.shape[0] - max(0, y1 - H)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    if x1 <= x0 or y1 <= y0:
        return
    sub = disc[sy0:sy1, sx0:sx1]
    if mask.dtype == bool:
        mask[y0:y1, x0:x1] |= sub
    else:
        region = mask[y0:y1, x0:x1]
        region[sub] = value


# ----------------------------------------------------------------------------- the land
class Terrain:
    """One generated land. Read the arrays freely; never write to them (marks live in world.json)."""

    def __init__(self, seed: int = 4471, w: int = MAP_W, h: int = MAP_H):
        self.seed, self.w, self.h = int(seed), int(w), int(h)
        self.trees: List[Tuple[int, int, int, int]] = []          # (x, y, age, variant), the wild Wood
        self.boulders: List[Tuple[int, int, int]] = []             # (x, y, variant), the Fell
        self.ford_stones: List[Tuple[int, int]] = []
        self.places: Dict[str, Dict] = {}
        self.notes: List[str] = []
        self._fields()
        self._sea()
        self._site()
        self._fell()
        self._river()
        self._biomes()
        self._obstacles()
        self._moot()
        self._layers()
        self._grid()
        self._places()

    # -- 1. noise fields ---------------------------------------------------------------------------------------------
    def _fields(self) -> None:
        yy, xx = np.mgrid[0:self.h, 0:self.w].astype(np.float32)
        self.xx, self.yy = xx, yy
        # noise in NOISE-cell units: the mockup's frequencies were tuned for a 256-tile map; this land is 120x55 tiles,
        # so a "unit" is half a tile and the same wavelengths give features 3-4 screens can hold
        u, v = (xx + 0.5) / NOISE, (yy + 0.5) / NOISE
        self.u, self.v = u, v
        base = fbm(u, v, 1 / 30.0, 2, self.seed)
        gx = 1.0 - xx / self.w                                           # 1 at the west edge, 0 at the east
        gy = 1.0 - yy / self.h                                           # 1 at the north edge, 0 at the south
        g = 0.55 * gx + 0.45 * gy                                        # high NW, low SE: the sea lies south-east
        self.g = g
        mean = 0.30 + 0.55 * (g - COAST_G)                               # sea level on the COAST_G isoline, hills at g > 0.8
        detail = fbm(u, v, 1 / 9.0, 3, self.seed + 50) - 0.5
        e = mean + 0.70 * (base - 0.5) + 0.12 * detail
        self.elevation = np.clip(e, 0, 1).astype(np.float32)
        self.moisture = fbm(u, v, 1 / 19.0, 4, self.seed + 7000).astype(np.float32)

    # -- 2. sea, ponds, distance to the sea --------------------------------------------------------------------------
    def _sea(self) -> None:
        E = self.elevation
        water = E < SEA
        sea = np.zeros_like(water)
        sea[0, :] = sea[-1, :] = True
        sea[:, 0] = sea[:, -1] = True
        sea &= water
        for _ in range(self.w + self.h):
            grown = _grow(sea) & water
            if (grown == sea).all():
                break
            sea = grown
        self.sea = sea
        self.pond = water & ~sea
        # tile-res distance to the sea (for the site search) and cell-res distance (for the shore band / tide)
        Et = E[TILE // 2::TILE, TILE // 2::TILE]
        sea_t = sea[TILE // 2::TILE, TILE // 2::TILE]
        self.E_t, self.sea_t = Et, sea_t
        self.pond_t = self.pond[TILE // 2::TILE, TILE // 2::TILE]
        self.M_t = self.moisture[TILE // 2::TILE, TILE // 2::TILE]
        self.D_t = distance_field(sea_t, 3 * max(Et.shape))

    # -- 3. site search ----------------------------------------------------------------------------------------------
    def _site(self) -> None:
        """Whole-map search at tile resolution (the mockup's criteria): flat grassland 9-12 tiles from the sea with the
        sea to the lower-right, forest within reach (the Wood to the east), no pond in the first frame, and the first
        320x110-cell frame inside the map with the 12-cell margin. The Fell is raised north-west of the site right
        after (`_fell`), so "hills to the north-west" holds by construction."""
        E, M, D = self.E_t, self.M_t, self.D_t
        TH, TW = E.shape
        sea_y, sea_x = np.nonzero(self.sea_t)
        for_y, for_x = np.nonzero((M > 0.58) & (E > SEA + 0.03) & (E < 0.62))
        pond_y, pond_x = np.nonzero(self.pond_t)
        half_w, half_h = VIEW_W // 2 + EDGE_MARGIN, VIEW_H // 2 + EDGE_MARGIN
        tx0, tx1 = int(math.ceil(half_w / TILE)), TW - int(math.ceil(half_w / TILE))
        ty0, ty1 = int(math.ceil(half_h / TILE)), TH - int(math.ceil(half_h / TILE))
        fw, fh = VIEW_W // TILE // 2 + 1, VIEW_H // TILE // 2 + 1               # half the first frame, in tiles

        def scan(strict: bool):
            best, best_s = None, 1e9
            for ty in range(ty0, ty1, 1):
                for tx in range(tx0, tx1, 1):
                    e = E[ty, tx]
                    if not ((0.38 <= e <= 0.56) if strict else (0.34 <= e <= 0.62)):
                        continue
                    d = D[ty, tx]
                    if not ((9 <= d <= 12) if strict else (6 <= d <= 14)):
                        continue
                    win = E[ty - 3:ty + 4, tx - 3:tx + 4]
                    slope = float(win.max() - win.min())
                    if slope > (0.10 if strict else 0.14):
                        continue
                    if len(pond_x) and self.pond_t[max(0, ty - fh):ty + fh + 1, max(0, tx - fw):tx + fw + 1].any():
                        continue
                    near = np.hypot(sea_x - tx, sea_y - ty) < 18
                    if near.sum() < (30 if strict else 15):
                        continue
                    wx, wy = sea_x[near].mean() - tx, sea_y[near].mean() - ty
                    if wx < (4 if strict else 2) or wy < (3 if strict else 1):
                        continue
                    fe = ((np.hypot(for_x - tx, for_y - ty) < 22) & (for_x > tx)).sum()        # the Wood to the east
                    fn = (np.hypot(for_x - tx, for_y - ty) < 16).sum()
                    if strict and (fn < 12 or fe < 12):
                        continue
                    sc = slope * 6 + abs(d - 10.5) * 0.3 - min(fn, 120) * 0.004 - min(fe, 80) * 0.004
                    if sc < best_s:
                        best, best_s = (tx, ty), sc
            return best

        best = scan(True)
        if best is None:
            self.notes.append("site search relaxed (no strict candidate)")
            best = scan(False)
        if best is None:
            self.notes.append("site search failed; map centre used")
            best = (TW // 2, TH // 2)
        self.site = (best[0] * TILE + TILE // 2, best[1] * TILE + TILE // 2)     # cells

    def _fell(self) -> None:
        """Raise the Fell: a hill mass north-west of the site (its top is the river's source), then refresh the water
        masks (the bump only ever lifts land, so the sea and the site's distance to it are unchanged)."""
        sx, sy = self.site
        fx = float(np.clip(sx - 130, 60, self.w - 60))
        fy = float(np.clip(sy - 105, 50, self.h - 50))
        self.fell_centre = (int(fx), int(fy))
        dd = np.hypot((self.xx - fx) / 1.25, self.yy - fy)
        bump = np.exp(-(dd / 66.0) ** 2)
        ridge = 0.06 * (fbm(self.u, self.v, 1 / 6.0, 2, self.seed + 909) - 0.5)
        land = np.clip((self.elevation - SEA) / 0.05, 0, 1)
        self.elevation = np.clip(self.elevation + (0.26 * bump + ridge * bump) * land, 0, 1).astype(np.float32)
        self.pond = (self.elevation < SEA) & ~self.sea
        self.E_t = self.elevation[TILE // 2::TILE, TILE // 2::TILE]

    # -- 4. the river: traced downhill from the Fell past the site to the sea, then carved --------------------------
    def _river(self) -> None:
        E = self.elevation
        sx, sy = self.site
        Eb = box_blur(E, 12)
        gy, gx = np.gradient(Eb)
        # source: the highest blurred ground in the north-west quarter around the site
        yy, xx = self.yy, self.xx
        fx0, fy0 = self.fell_centre
        region = (np.hypot(xx - fx0, yy - fy0) < 70) & (xx > EDGE_MARGIN + 8) & (yy > EDGE_MARGIN + 8)
        cand = np.where(region, Eb, -1.0)
        iy, ix = np.unravel_index(int(np.argmax(cand)), cand.shape)
        x, y = float(ix), float(iy)
        self.fell_top = (int(ix), int(iy))
        # the water passes beside the Steading (the Ford is where it comes closest), then runs to the sea
        waypoint = (sx + 58.0, sy - 10.0)
        keep_off = 44.0                                                   # the river never runs through the Moot ring
        sea_y, sea_x = np.nonzero(self.sea[::4, ::4])
        sea_x, sea_y = sea_x * 4.0, sea_y * 4.0
        pts = [(x, y)]
        vx, vy = 0.0, 1.0
        phase = 0
        for i in range(6000):
            xi, yi = int(np.clip(x, 0, self.w - 1)), int(np.clip(y, 0, self.h - 1))
            if self.sea[yi, xi]:
                break
            ddx, ddy = -gx[yi, xi], -gy[yi, xi]
            n = math.hypot(ddx, ddy) + 1e-6
            ddx, ddy = ddx / n, ddy / n
            if phase == 0:
                tx, ty = waypoint
                if math.hypot(tx - x, ty - y) < 10:
                    phase = 1
            if phase == 0:
                px_, py_ = tx - x, ty - y
                n2 = math.hypot(px_, py_) + 1e-6
                pull = 0.9
                ddx = ddx * 0.5 + pull * px_ / n2
                ddy = ddy * 0.5 + pull * py_ / n2
            elif len(sea_x):
                dd = np.hypot(sea_x - x, sea_y - y)
                k = int(np.argmin(dd))
                px_, py_ = sea_x[k] - x, sea_y[k] - y
                n2 = math.hypot(px_, py_) + 1e-6
                pull = min(1.0, 160.0 / n2) * 0.6 + 0.45
                ddx = ddx + pull * px_ / n2
                ddy = ddy + pull * py_ / n2
            dsx, dsy = x - sx, y - sy
            ds = math.hypot(dsx, dsy) + 1e-6
            if ds < keep_off:                                            # slide round the Steading, never through it
                push = (keep_off - ds) / keep_off * 2.0
                ddx += push * dsx / ds
                ddy += push * dsy / ds
            wig = math.sin(i * 0.02 + self.seed) * 0.5
            vx = 0.90 * vx + 0.10 * (ddx - wig * ddy)
            vy = 0.90 * vy + 0.10 * (ddy + wig * ddx)
            n = math.hypot(vx, vy) + 1e-6
            x += 1.0 * vx / n
            y += 1.0 * vy / n
            if not (1 <= x < self.w - 1 and 1 <= y < self.h - 1):
                break
            pts.append((x, y))
        self.river_path = pts
        # carve: width 6 -> 14 cells from source to mouth, the valley floor lowered so banks read as a valley
        river = np.zeros((self.h, self.w), bool)
        n = len(pts)
        disc_cache: Dict[int, np.ndarray] = {}
        for i, (px, py) in enumerate(pts):
            t = i / max(1, n - 1)
            wdt = 6 + 8 * t
            r = int(round(wdt / 2))
            if r not in disc_cache:
                disc_cache[r] = _disc(r)
            _stamp(river, int(round(px)), int(round(py)), disc_cache[r])
        river &= ~self.sea
        self.river = river
        near = box_blur(river.astype(np.float32), 4)
        self.elevation = np.clip(self.elevation - 0.10 * np.clip(near * 1.6, 0, 1), 0, 1).astype(np.float32)
        # the Ford: where the river comes closest to the Steading, a band of shallow wading water 5 cells along the flow
        dmin, kbest = 1e9, 0
        for i, (px, py) in enumerate(pts):
            d = math.hypot(px - sx, py - sy)
            if d < dmin:
                dmin, kbest = d, i
        self.ford_index = kbest
        fx, fy = pts[kbest]
        self.ford_centre = (int(round(fx)), int(round(fy)))
        ford = np.zeros_like(river)
        for i in range(max(0, kbest - 5), min(n, kbest + 6)):
            px, py = pts[i]
            _stamp(ford, int(round(px)), int(round(py)), _disc(9))
        self.ford = ford & river
        # stepping stones across the ford, perpendicular to the flow
        a = pts[max(0, kbest - 6)]
        b = pts[min(n - 1, kbest + 6)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) + 1e-6
        nx, ny = -dy / L, dx / L
        for k in range(-3, 4):
            px = fx + nx * k * 2.2
            py = fy + ny * k * 2.2
            if self.river[int(np.clip(py, 0, self.h - 1)), int(np.clip(px, 0, self.w - 1))]:
                self.ford_stones.append((int(round(px)), int(round(py))))

    # -- 5. biomes ---------------------------------------------------------------------------------------------------
    def _biomes(self) -> None:
        E, M = self.elevation, self.moisture
        sx, sy = self.site
        u, v = self.u, self.v
        dsite = np.hypot(self.xx - sx, self.yy - sy)
        water = (E < SEA) | self.river
        self.water_all = water
        biome = np.full((self.h, self.w), B_GRASS, np.uint8)
        patch = fbm(u, v, 1 / 4.5, 2, self.seed + 31)
        biome[(M < 0.42) & (patch > 0.60)] = B_MEADOW                    # dry sunny patches carry the flower drifts
        east = np.clip((self.xx - sx - 30) / 120.0, 0, 1)                # the Wood gathers east of the Steading
        wet = M + 0.10 * east - 0.06 * np.clip((sx - 30 - self.xx) / 200.0, 0, 1)
        forest = (wet > 0.60) & (E > SEA + 0.05) & (E < 0.62) & (dsite > 44)
        biome[forest] = B_FOREST
        biome[E > 0.62] = B_HILL
        biome[E > 0.76] = B_ROCK
        # the marsh: low wet ground within reach of the river, never at the site
        rd = distance_field(self.river, 7)
        marsh = (rd <= 6) & (M > 0.50) & (E < SEA + 0.10) & (dsite > 34) & ~water
        biome[marsh] = B_MARSH
        # shore band and river banks
        biome[(E < SEA + 0.03) & ~water] = B_SAND
        bank = dilate(self.river, 2) & ~water
        biome[bank] = B_SAND
        biome[E < SEA] = B_SHALLOW
        biome[E < SEA - 0.07] = B_DEEP
        biome[self.river] = B_RIVER
        biome[self.ford] = B_FORD
        self.biome = biome
        self.water = np.isin(biome, WATER_BIOMES)                         # what you cannot walk (the ford is not here)
        self.shore_dist = distance_field(self.sea, 4)                    # sand cells 1-4 from the sea: the tide's wet band

    # -- 6. obstacles as convex blobs: the Wood's trunks, the Fell's boulders ---------------------------------------
    def _obstacles(self) -> None:
        sx, sy = self.site
        H, W = self.h, self.w
        caster = np.zeros((H, W), np.uint8)
        solid = np.zeros((H, W), bool)
        forest = self.biome == B_FOREST
        # trunks on a jittered 6-cell lattice inside the Wood (dense), lone trees on grass (rare), a few on the Fell
        step = 6
        gy, gx = np.mgrid[3:H:step, 3:W:step]
        jit = _hash2(gx, gy, self.seed + 77)
        jit2 = _hash2(gx, gy, self.seed + 78)
        px = np.clip(gx + ((jit - 0.5) * 4).astype(np.int32), 0, W - 1)
        py = np.clip(gy + ((jit2 - 0.5) * 4).astype(np.int32), 0, H - 1)
        keep = _hash2(gx, gy, self.seed + 79)
        m_here = self.moisture[py, px]
        b_here = self.biome[py, px]
        d_here = np.hypot(px - sx, py - sy)
        in_wood = (b_here == B_FOREST) & (keep < 0.80)
        lone = ((b_here == B_GRASS) | (b_here == B_MEADOW)) & (keep < 0.012) & (d_here > 48)
        on_fell = (b_here == B_HILL) & (keep < 0.05)
        pick = in_wood | lone | on_fell
        trunk = _disc(1.5)
        for x, y, m, lw, k in zip(px[pick], py[pick], m_here[pick], in_wood[pick], keep[pick]):
            x, y = int(x), int(y)
            if x < 6 or y < 6 or x > W - 7 or y > H - 7:
                continue
            if lw:
                age = 3 if m > 0.66 else (2 if m > 0.58 else 1)
            else:
                age = 2 if k * 100 % 1 < 0.5 else 1
            variant = int(k * 1000) % 3
            self.trees.append((x, y, age, variant))
            _stamp(solid, x, y, trunk)
            _stamp(caster, x, y, _disc(1.0), value=min(255, 2 + age))
        # boulders on the Fell (hill cells), convex discs of 1-2 cells
        hy, hx = np.mgrid[4:H:9, 4:W:9]
        hk = _hash2(hx, hy, self.seed + 91)
        bx = np.clip(hx + ((_hash2(hx, hy, self.seed + 92) - 0.5) * 6).astype(np.int32), 0, W - 1)
        by = np.clip(hy + ((_hash2(hx, hy, self.seed + 93) - 0.5) * 6).astype(np.int32), 0, H - 1)
        pickb = (self.biome[by, bx] == B_HILL) & (hk < 0.16) & (np.hypot(bx - sx, by - sy) > 40)
        for x, y, k in zip(bx[pickb], by[pickb], hk[pickb]):
            x, y = int(x), int(y)
            variant = int(k * 1000) % 3
            self.boulders.append((x, y, variant))
            r = 1.0 + 0.5 * variant
            _stamp(solid, x, y, _disc(r))
            _stamp(caster, x, y, _disc(max(1.0, r - 0.5)), value=1 + variant)
        # ford stones are hop-over scenery: not solid, not casters
        self.solid = solid
        self.caster = caster

    # -- 7. the Moot green: the largest flat short-grass disc at the site (forced to at least 16 cells) --------------
    def _moot(self) -> None:
        sx, sy = self.site
        E = self.elevation
        ok = ((self.biome == B_GRASS) | (self.biome == B_MEADOW)) & ~self.solid
        r = 12
        for rr in range(12, 40):
            d = _disc(rr)
            n = d.shape[0] // 2
            y0, y1, x0, x1 = sy - n, sy + n + 1, sx - n, sx + n + 1
            if y0 < 0 or x0 < 0 or y1 > self.h or x1 > self.w:
                break
            sub_ok = ok[y0:y1, x0:x1][d]
            sub_e = E[y0:y1, x0:x1][d]
            if sub_ok.all() and float(sub_e.max() - sub_e.min()) < 0.06:
                r = rr
            else:
                break
        self.moot_r = int(max(16, r))
        # the green is short grass, clear of trunks, boulders and meadow drifts (seeds land here)
        d = _disc(self.moot_r)
        clear = np.zeros_like(self.solid)
        _stamp(clear, sx, sy, d)
        land = ~self.water & (self.biome != B_ROCK)
        self.biome[clear & land] = B_GRASS
        self.trees = [t for t in self.trees if math.hypot(t[0] - sx, t[1] - sy) > self.moot_r + 4]
        self.boulders = [b for b in self.boulders if math.hypot(b[0] - sx, b[1] - sy) > self.moot_r + 4]
        self.solid[clear] = False
        self.caster[clear] = 0
        # rebuild solid / caster from the surviving lists (a trunk on the ring edge may have been half cleared)
        solid = np.zeros_like(self.solid)
        caster = np.zeros_like(self.caster)
        trunk = _disc(1.5)
        for (x, y, age, _v) in self.trees:
            _stamp(solid, x, y, trunk)
            _stamp(caster, x, y, _disc(1.0), value=min(255, 2 + age))
        for (x, y, v) in self.boulders:
            r = 1.0 + 0.5 * v
            _stamp(solid, x, y, _disc(r))
            _stamp(caster, x, y, _disc(max(1.0, r - 0.5)), value=1 + v)
        self.solid, self.caster = solid, caster

    # -- 8. passable / cost / height / shade -------------------------------------------------------------------------
    def _layers(self) -> None:
        passable = np.isin(self.biome, PASSABLE_BIOMES) & ~self.solid
        # the outermost EDGE_MARGIN cells are never on screen and never walked
        passable[:EDGE_MARGIN, :] = passable[-EDGE_MARGIN:, :] = False
        passable[:, :EDGE_MARGIN] = passable[:, -EDGE_MARGIN:] = False
        self.passable = passable
        cost = np.zeros((self.h, self.w), np.uint8)
        for b, c in COST.items():
            cost[self.biome == b] = c
        cost[~passable] = 0
        self.cost = cost
        self.height = np.clip(self.elevation * 255, 0, 255).astype(np.uint8)
        self.moisture8 = np.clip(self.moisture * 255, 0, 255).astype(np.uint8)
        # ground painter shade: mottle + relief along a fixed north-west light on high ground (the mockup's terraces),
        # the marsh a touch darker; the hour's light and shadows are the per-frame modulation's job (nature.py)
        u, v = self.u, self.v
        mott = fbm(u, v, 1 / 3.5, 2, self.seed + 300) - 0.5
        shade = 1.0 + 0.09 * mott
        Eb = box_blur(self.elevation, 5)
        gy, gx = np.gradient(Eb)
        relief = np.clip(1.0 + 34.0 * (-0.62 * gx - 0.78 * gy) * np.clip((self.elevation - 0.58) / 0.12, 0, 1), 0.74, 1.26)
        shade = shade * relief
        shade = np.where(self.biome == B_MARSH, shade * 0.90, shade)
        shade = np.where(self.water | (self.biome == B_FORD), 1.0, shade)
        self.shade = shade.astype(np.float32)
        # a per-cell phase for water sparkle (nature.py scrolls it), hashed once here
        self.sparkle_phase = _hash2(self.xx.astype(np.int32), self.yy.astype(np.int32), self.seed + 555)

    # -- 9. coarse BFS route grid ------------------------------------------------------------------------------------
    def _grid(self) -> None:
        GW, GH = int(math.ceil(self.w / BLOCK)), int(math.ceil(self.h / BLOCK))
        self.grid_w, self.grid_h = GW, GH
        grid = np.zeros((GH, GW), bool)
        frac = np.zeros((GH, GW), np.float32)
        for gy in range(GH):
            for gx in range(GW):
                blk = self.passable[gy * BLOCK:(gy + 1) * BLOCK, gx * BLOCK:(gx + 1) * BLOCK]
                f = float(blk.mean()) if blk.size else 0.0
                frac[gy, gx] = f
                grid[gy, gx] = f >= 0.5
        self.grid = grid
        self.grid_frac = frac

    # -- 10. places --------------------------------------------------------------------------------------------------
    def _places(self) -> None:
        sx, sy = self.site
        P: Dict[str, Dict] = {}

        def add(name, x, y, radius, label):
            x, y = self.nearest_passable(int(x), int(y), 40)
            P[name] = {"name": name, "x": int(x), "y": int(y), "radius": int(radius), "label": label}

        add("moot", sx, sy, self.moot_r, "the Moot")
        add("steading", sx, sy, 60, "the Steading")
        fx, fy = self.ford_centre
        # the ford's bank on the Steading side: walk from the ford centre toward the site until land
        bx, by = fx, fy
        for k in range(1, 30):
            t = k / 30.0
            cx, cy = int(round(fx + (sx - fx) * t)), int(round(fy + (sy - fy) * t))
            if self.passable[cy, cx] and self.biome[cy, cx] != B_FORD:
                bx, by = cx, cy
                break
        P["ford"] = {"name": "ford", "x": int(fx), "y": int(fy), "radius": 8, "label": "the Ford"}
        add("river", bx, by, 10, "the river")
        # the shore: the nearest sand cell to the Steading with the sea beyond it
        sand = np.argwhere((self.biome == B_SAND) & (self.shore_dist <= 4))
        if len(sand):
            dd = np.hypot(sand[:, 1] - sx, sand[:, 0] - sy)
            k = int(np.argmin(dd))
            add("shore", sand[k, 1], sand[k, 0], 14, "the Shore")
        else:
            add("shore", sx + 100, sy + 100, 14, "the Shore")
        add("fell", self.fell_top[0], self.fell_top[1], 30, "the Fell")
        wood = np.argwhere((self.biome == B_FOREST) & (self.xx > sx))
        if len(wood) < 50:
            wood = np.argwhere(self.biome == B_FOREST)
        if len(wood):
            wy, wx = wood.mean(axis=0)
            add("wood", wx, wy, 40, "the Wood")
        else:
            add("wood", sx + 160, sy, 40, "the Wood")
        marsh = np.argwhere(self.biome == B_MARSH)
        if len(marsh):
            my, mx = marsh.mean(axis=0)
            dd = np.hypot(marsh[:, 1] - mx, marsh[:, 0] - my)
            k = int(np.argmin(dd))
            add("marsh", marsh[k, 1], marsh[k, 0], 16, "the Reed Marsh")
        wxp, wyp = P["wood"]["x"], P["wood"]["y"]
        add("orchard", (sx * 0.45 + wxp * 0.55), (sy * 0.45 + wyp * 0.55), 24, "the Orchard Slope")
        self.places = P
        # eight compass targets for `go north` etc. are the behaviour agent's job (60 cells that way); the registry is
        # only the named places
        self.notes.append("moot r=%d at (%d, %d); ford at (%d, %d); %d wild trees; %d boulders; sea %.1f%%; passable %.1f%%" % (
            self.moot_r, sx, sy, fx, fy, len(self.trees), len(self.boulders), 100.0 * self.sea.mean(), 100.0 * self.passable.mean()))

    # -- queries -----------------------------------------------------------------------------------------------------
    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def is_passable(self, x: float, y: float) -> bool:
        xi, yi = int(x), int(y)
        return self.in_bounds(xi, yi) and bool(self.passable[yi, xi])

    def nearest_passable(self, x: int, y: int, r: int = 24) -> Tuple[int, int]:
        """The closest passable cell to (x, y) within r (ring search); (x, y) itself when it is passable."""
        if self.is_passable(x, y):
            return (int(x), int(y))
        best, bd = (int(np.clip(x, 0, self.w - 1)), int(np.clip(y, 0, self.h - 1))), 1e9
        for rr in range(1, int(r) + 1):
            for dx in range(-rr, rr + 1):
                for dy in (-rr, rr):
                    for (cx, cy) in ((x + dx, y + dy), (x + dy, y + dx)):
                        if self.is_passable(cx, cy):
                            d = dx * dx + dy * dy
                            if d < bd:
                                best, bd = (int(cx), int(cy)), d
            if bd < 1e9:
                return best
        return best

    def block_of(self, x: float, y: float) -> Tuple[int, int]:
        return (int(np.clip(x // BLOCK, 0, self.grid_w - 1)), int(np.clip(y // BLOCK, 0, self.grid_h - 1)))

    def route(self, a: Tuple[float, float], b: Tuple[float, float]) -> List[Tuple[int, int]]:
        """BFS over the coarse 60x28 grid (8-connected, no corner cutting through blocked blocks). Returns cell
        waypoints (block centres) from a's block to b's block, ending at b itself; [] when no route exists.
        The behaviour agent walks the straight legs between waypoints with its one-cell slide rule."""
        ga, gb = self.block_of(*a), self.block_of(*b)
        if ga == gb:
            return [(int(b[0]), int(b[1]))]
        G = self.grid
        GH, GW = G.shape
        start = ga if G[ga[1], ga[0]] else self._nearest_block(ga)
        goal = gb if G[gb[1], gb[0]] else self._nearest_block(gb)
        prev = {start: None}
        q = deque([start])
        found = False
        while q:
            cur = q.popleft()
            if cur == goal:
                found = True
                break
            cx, cy = cur
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = cx + dx, cy + dy
                    if not (0 <= nx < GW and 0 <= ny < GH) or not G[ny, nx] or (nx, ny) in prev:
                        continue
                    if dx and dy and not (G[cy, nx] and G[ny, cx]):
                        continue
                    prev[(nx, ny)] = cur
                    q.append((nx, ny))
        if not found:
            return []
        path = []
        cur = goal
        while cur is not None:
            path.append(cur)
            cur = prev[cur]
        path.reverse()
        pts = [(gx * BLOCK + BLOCK // 2, gy * BLOCK + BLOCK // 2) for (gx, gy) in path[1:]]
        pts = [self.nearest_passable(x, y, BLOCK) for (x, y) in pts]
        if not pts or pts[-1] != (int(b[0]), int(b[1])):
            pts.append((int(b[0]), int(b[1])))
        return pts

    def _nearest_block(self, g: Tuple[int, int]) -> Tuple[int, int]:
        gx, gy = g
        best, bd = g, 1e9
        ys, xs = np.nonzero(self.grid)
        if len(xs):
            d = (xs - gx) ** 2 + (ys - gy) ** 2
            k = int(np.argmin(d))
            best = (int(xs[k]), int(ys[k]))
        return best

    def place(self, name: str) -> Optional[Dict]:
        return self.places.get(name)

    # -- exports -----------------------------------------------------------------------------------------------------
    def cells(self) -> np.ndarray:
        """The int8 tiles.CAT category map of the bare land (no marks) for tiles.Ground / bake.py."""
        from stream.world.art import tiles
        C = tiles.CAT
        lut = np.zeros(len(BIOME_NAMES), np.int8)
        lut[B_DEEP] = C["water_deep"]
        lut[B_SHALLOW] = C["water_shallow"]
        lut[B_RIVER] = C["water_shallow"]
        lut[B_FORD] = C["water_shallow"]
        lut[B_SAND] = C["sand"]
        lut[B_GRASS] = C["grass"]
        lut[B_MEADOW] = C["meadow"]
        lut[B_FOREST] = C["forest_floor"]
        lut[B_HILL] = C["hill"]
        lut[B_ROCK] = C["rock"]
        lut[B_MARSH] = C["grass"]                 # the atlas has no reed tile yet: marsh is darker grass (shade) + reeds later
        return lut[self.biome]

    def biome_rgb(self) -> np.ndarray:
        """Cell-res biome colours (H, W, 3) uint8: the fallback ground until a bake exists, and the minimap base."""
        return BIOME_RGB[self.biome]

    def grass_mask(self) -> np.ndarray:
        """Cells whose ground bends in the wind (the wind bands apply here only)."""
        return np.isin(self.biome, (B_GRASS, B_MEADOW, B_MARSH, B_HILL, B_FOREST))

    def summary(self) -> Dict:
        return {
            "seed": self.seed, "w": self.w, "h": self.h, "site": self.site, "moot_r": self.moot_r,
            "ford": self.ford_centre, "fell_top": self.fell_top, "trees": len(self.trees), "boulders": len(self.boulders),
            "sea_frac": round(float(self.sea.mean()), 4), "pond_frac": round(float(self.pond.mean()), 4),
            "passable_frac": round(float(self.passable.mean()), 4), "river_cells": int(self.river.sum()),
            "grid_open_frac": round(float(self.grid.mean()), 3), "places": {k: (v["x"], v["y"], v["radius"]) for k, v in self.places.items()},
            "notes": list(self.notes),
        }

    def save_png(self, path: str, scale: int = 1) -> None:
        """Review PNG: biome colours, trees / boulders as dots, the first frame and the margin, places labelled (20 px)."""
        from PIL import Image, ImageDraw, ImageFont
        rgb = self.biome_rgb().copy()
        sh = np.clip(self.shade, 0.7, 1.3)[..., None]
        rgb = np.clip(rgb.astype(np.float32) * sh, 0, 255).astype(np.uint8)
        for (x, y, age, _v) in self.trees:
            rgb[max(0, y - 1):y + 2, max(0, x - 1):x + 2] = (40, 90, 46) if age >= 2 else (60, 120, 60)
        for (x, y, _v) in self.boulders:
            rgb[max(0, y - 1):y + 2, max(0, x - 1):x + 2] = (120, 116, 110)
        for (x, y) in self.ford_stones:
            rgb[y, x] = (200, 196, 186)
        rgb[~self.passable & ~self.water & (self.biome != B_ROCK) & ~self.solid] //= 2     # the never-walked margin
        img = Image.fromarray(rgb).resize((self.w * scale, self.h * scale), Image.Resampling.NEAREST).convert("RGB")
        d = ImageDraw.Draw(img)
        sx, sy = self.site
        s = scale
        d.ellipse([(sx - self.moot_r) * s, (sy - self.moot_r) * s, (sx + self.moot_r) * s, (sy + self.moot_r) * s], outline=(255, 240, 200), width=1)
        d.rectangle([(sx - VIEW_W // 2) * s, (sy - VIEW_H // 2) * s, (sx + VIEW_W // 2) * s, (sy + VIEW_H // 2) * s], outline=(255, 255, 255), width=1)
        d.rectangle([EDGE_MARGIN * s, EDGE_MARGIN * s, (self.w - EDGE_MARGIN) * s, (self.h - EDGE_MARGIN) * s], outline=(255, 120, 120), width=1)
        try:
            f = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 20)
        except Exception:
            f = None
        for name, p in self.places.items():
            x, y = p["x"] * s, p["y"] * s
            d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 255, 255))
            d.text((x + 6, y - 12), p["label"], font=f, fill=(255, 255, 255), stroke_width=2, stroke_fill=(20, 20, 20))
        d.text((8, 8), "seed %d · %dx%d cells · %s" % (self.seed, self.w, self.h, "; ".join(self.notes[-1:])), font=f,
               fill=(255, 255, 255), stroke_width=2, stroke_fill=(20, 20, 20))
        img.save(path)


def generate(seed: int = 4471, w: int = MAP_W, h: int = MAP_H) -> Terrain:
    """The land for a seed (cached in-process). Deterministic: the same seed always gives the same arrays."""
    key = (int(seed), int(w), int(h))
    t = _CACHE.get(key)
    if t is None:
        t = Terrain(seed, w, h)
        _CACHE[key] = t
    return t


if __name__ == "__main__":
    import sys
    import time
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 4471
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/lg-terrain-%d.png" % seed
    t0 = time.perf_counter()
    T = generate(seed)
    print("generate(%d): %.0f ms" % (seed, (time.perf_counter() - t0) * 1000))
    for k, v in T.summary().items():
        print("  %s: %s" % (k, v))
    T.save_png(out, 2)
    print("wrote", out)
    r = T.route(T.places["moot"]["x"], T.places["moot"]["y"]) if False else T.route((T.places["moot"]["x"], T.places["moot"]["y"]), (T.places["shore"]["x"], T.places["shore"]["y"]))
    print("route moot -> shore: %d waypoints" % len(r), r[:6])
