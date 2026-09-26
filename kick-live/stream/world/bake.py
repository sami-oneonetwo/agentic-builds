"""bake.py - the painted ground of LONGGRASS (docs/OPENWORLD.md section 7.3 steps 1-3).

The display is PAINTED ONCE at screen resolution (4 px per cell, 3840x1760x3 uint8 = 20.3 MB) into a memory-mapped
file under $RUN_DIR/bake/, and CROPPED per frame; the simulation and every per-frame effect stay at cell resolution
(nature.Nature.modulation) and are multiplied into the crop in fixed point. Whole-map work never runs on the frame
path: the bake runs in a background thread (numpy releases the GIL), a mark change repaints only its region.

    ground-<seed>-<season>-o<octant>-v<bake_ver>.npy      one file per (map seed, season 0-3, sun octant, bake_ver)

`bake_ver` is bumped by the world state when a mark that lives in the ground changes (hut tier, field stage, trail
threshold); the octant is the sun's (every sprite in the atlas is lit per octant, ~1.75 h of world time), so the
props on the ground are lit by the same sun as the live sprites. A booting scene finds its file in ~20 ms; a missing
one shows the cell-res biome colours x4 (`fallback`) until the thread lands it (~1.5 s here).

    from stream.world import terrain, nature, bake
    T = terrain.generate(4471)
    B = bake.GroundBake("/tmp/lg-x", T, season_idx=0, sun=nature.sun_vector(12.0), bake_ver=0, marks=marks)
    B.start()                                     # background thread; B.ready flips when the memmap is open
    rgb = B.ground(bx0, by0, 1280, 440)           # the crop (or the fallback), uint8 (440, 1280, 3), ~0.4 ms
    cx, cy, cw, ch, ox, oy = bake.view_cells(bx0, by0, 1280, 440)
    field = N.modulation((cx, cy, cw, ch), now, caster=bake.casters_for_marks(T, marks))
    out = bake.apply(rgb, field, ox, oy)          # fixed-point x4 multiply, uint8 (440, 1280, 3)
    B.repaint((x0, y0, x1, y1), marks)            # after a mark changed inside that cell rectangle

MARKS (what the land/state agent hands in; every owner is a real chatter, honesty is checked upstream):
    {"wear":    uint8 (H, W) or None      # trail wear per cell: >= 8 pressed grass, >= 48 bare earth, >= 160 road
     "huts":    [{"x", "y", "tier", "owner", "lit"}]   # camp tier 0 hollow / 1 tent / 2 hut / 3 chimney; x, y = the
                                                       # footprint's top-left cell (8x6 hollow, 8 wide otherwise)
     "fields":  [{"x", "y", "stage", "owner"}]         # 3x2 cells, stage 0-3 (nature.field_stage)
     "flowers": [{"x", "y", "owner", "variant"}]       # planted flowers (static, baked)
     "stones":  []}                                     # reserved (the cairn is a live sprite: its height changes)
Planted TREES are live sprites (few, they grow), not baked; `casters_for_marks` still counts their shadows.

numpy + pillow only, Python 3.9.
"""
from __future__ import annotations

import math
import os
import threading
import time
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from stream.world import terrain as _terrain
from stream.world.art import buildings, props, tiles

CELL = 4
TILE_CELLS = 8
STRIP_CELLS = 88                     # 11 tiles per painting strip (5 strips over 440 cells)
WEAR_PRESSED, WEAR_BARE, WEAR_ROAD = 8, 48, 160
BAKE_WIND_PHASE, BAKE_RIPPLE_PHASE = 1, 0          # the atlas phase baked in; motion comes from the modulation
KEEP_FILES = 4
HOLLOW_W, HOLLOW_H = 8, 6            # pressed grass of a tier-0 camp, in cells
CAMP_TO_BUILDING = {0: None, 1: 0, 2: 1, 3: 2}     # camp tier -> buildings.render("hut", tier): tent / hut / chimney
HUT_CASTER = {1: 3, 2: 4, 3: 4}


# ----------------------------------------------------------------------------- naming
def sun_octant(sun: Sequence[float]) -> int:
    """0..7 index of the atlas's sun bucket (the same rounding as the art module's _sun_bucket)."""
    sx, sy = sun
    n = math.hypot(sx, sy) or 1.0
    a = round(math.atan2(sy / n, sx / n) / (math.pi / 4))
    return int(a) % 8


def octant_sun(octant: int) -> Tuple[float, float]:
    a = (int(octant) % 8) * (math.pi / 4)
    return (math.cos(a), math.sin(a))


def bake_dir(run_dir: str) -> str:
    return os.path.join(run_dir, "bake")


def bake_path(run_dir: str, seed: int, season_idx: int, octant: int, bake_ver: int, px_per_cell: int = CELL) -> str:
    tail = "" if int(px_per_cell) == CELL else "-p%d" % int(px_per_cell)
    return os.path.join(bake_dir(run_dir), "ground-%d-%d-o%d-v%d%s.npy" % (int(seed), int(season_idx) % 4, int(octant) % 8, int(bake_ver), tail))


def prune(run_dir: str, keep: Sequence[str] = (), max_files: int = KEEP_FILES) -> List[str]:
    """Delete the oldest bake files beyond `max_files`, never the ones in `keep`. Returns what was removed."""
    d = bake_dir(run_dir)
    if not os.path.isdir(d):
        return []
    files = [os.path.join(d, f) for f in os.listdir(d) if f.startswith("ground-") and f.endswith(".npy")]
    files = [f for f in files if f not in set(keep)]
    files.sort(key=lambda f: os.path.getmtime(f))
    removed = []
    while len(files) + len(keep) > max_files and files:
        f = files.pop(0)
        try:
            os.remove(f)
            removed.append(f)
        except OSError:
            pass
    return removed


# ----------------------------------------------------------------------------- blits (uint16 alpha math, clipped)
def blit(dst: np.ndarray, spr: np.ndarray, x: int, y: int) -> None:
    h, w = spr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(dst.shape[1], x + w), min(dst.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return
    s = spr[y0 - y:y1 - y, x0 - x:x1 - x]
    a = s[..., 3:4].astype(np.uint16)
    if not a.any():
        return
    d = dst[y0:y1, x0:x1]
    d[...] = ((s[..., :3].astype(np.uint16) * a + d.astype(np.uint16) * (255 - a)) // 255).astype(np.uint8)


def blit_shade(dst: np.ndarray, spr: np.ndarray, x: int, y: int) -> None:
    """Darken-only blit (cloud shadows drawn as sprites, if ever needed at pixel scale)."""
    h, w = spr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(dst.shape[1], x + w), min(dst.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return
    a = spr[y0 - y:y1 - y, x0 - x:x1 - x, 3:4].astype(np.uint16)
    d = dst[y0:y1, x0:x1]
    d[...] = ((d.astype(np.uint16) * (256 - a)) >> 8).astype(np.uint8)


def blit_add(dst: np.ndarray, spr: np.ndarray, x: int, y: int) -> None:
    """Additive blit for glow kernels (fires, lit windows, the beacon) after dusk."""
    h, w = spr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(dst.shape[1], x + w), min(dst.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return
    s = spr[y0 - y:y1 - y, x0 - x:x1 - x]
    add = (s[..., :3].astype(np.uint16) * s[..., 3:4].astype(np.uint16)) // 255
    d = dst[y0:y1, x0:x1]
    d[...] = np.minimum(255, d.astype(np.uint16) + add).astype(np.uint8)


def put(dst: np.ndarray, spr: np.ndarray, gx: int, gy: int) -> None:
    """Blit a prop by its ground point (props.anchor convention)."""
    ax, ay = props.anchor(spr)
    blit(dst, spr, int(gx) - ax, int(gy) - ay)


# ----------------------------------------------------------------------------- marks into cells / casters
def cells_with_marks(T: "_terrain.Terrain", marks: Optional[Dict]) -> np.ndarray:
    """The int8 tiles.CAT map with every mark that is a GROUND texture: trails by wear threshold, fields by stage,
    the pressed grass of hollow camps. Huts, flowers and trees are sprites blitted afterwards."""
    C = tiles.CAT
    cells = T.cells().copy()
    if not marks:
        return cells
    land = np.isin(T.biome, (_terrain.B_GRASS, _terrain.B_MEADOW, _terrain.B_FOREST, _terrain.B_MARSH, _terrain.B_HILL))
    wear = marks.get("wear")
    if wear is not None:
        wear = np.asarray(wear)
        cells[(wear >= WEAR_PRESSED) & land] = C["path0"]
        cells[(wear >= WEAR_BARE) & land] = C["path1"]
        cells[(wear >= WEAR_ROAD) & land] = C["path2"]
    for h in marks.get("huts", ()):
        if int(h.get("tier", 0)) == 0:
            x, y = int(h["x"]), int(h["y"])
            sub = cells[y:y + HOLLOW_H, x:x + HOLLOW_W]
            sub[land[y:y + HOLLOW_H, x:x + HOLLOW_W]] = C["path0"]
    for f in marks.get("fields", ()):
        x, y, st = int(f["x"]), int(f["y"]), int(np.clip(f.get("stage", 0), 0, 3))
        cells[y:y + 2, x:x + 3] = C["farm%d" % st]
    return cells


def casters_for_marks(T: "_terrain.Terrain", marks: Optional[Dict], trees: Sequence[Dict] = ()) -> np.ndarray:
    """The terrain's caster layer plus huts (height 3-4 over their footprint) and planted trees (2 + stage)."""
    caster = T.caster
    if not marks and not trees:
        return caster
    caster = caster.copy()
    for h in (marks or {}).get("huts", ()):
        t = int(h.get("tier", 0))
        if t <= 0:
            continue
        x, y = int(h["x"]), int(h["y"])
        w = 16 if t >= 3 else 8
        caster[y + 2:y + 8, x + 1:x + w - 1] = HUT_CASTER.get(t, 3)
    for tr in list((marks or {}).get("trees", ())) + list(trees):
        x, y = int(tr["x"]), int(tr["y"])
        r = 1 + int(tr.get("stage", tr.get("age", 0)))
        caster[max(0, y - 1):y + 1, max(0, x - r // 2):x + r // 2 + 1] = np.maximum(caster[max(0, y - 1):y + 1, max(0, x - r // 2):x + r // 2 + 1], 2 + r)
    return caster


# ----------------------------------------------------------------------------- the painter
class GroundBake:
    """One painted season / sun octant / bake_ver of one land, memory-mapped. See the module docstring."""

    def __init__(self, run_dir: str, T: "_terrain.Terrain", season_idx: int, sun: Sequence[float], bake_ver: int = 0,
                 marks: Optional[Dict] = None, log=None, px_per_cell: int = CELL):
        """`px_per_cell` 4 (the 1x bake, 3840x1760) or 3 (the 0.75x wide-zoom bake, 2880x1320, 11.4 MB: painted at
        4 px/cell per strip and BOX-reduced once, so the wide zoom is a straight 1280x440 crop with no per-frame
        resample)."""
        self.run_dir = run_dir
        self.px = int(px_per_cell)
        self.T = T
        self.season_idx = int(season_idx) % 4
        self.season = float(self.season_idx)
        self.octant = sun_octant(sun)
        self.sun = octant_sun(self.octant)
        self.bake_ver = int(bake_ver)
        self.marks = marks or {}
        self.log = log or (lambda *a: None)
        self.path = bake_path(run_dir, T.seed, self.season_idx, self.octant, self.bake_ver, self.px)
        self.tmp = self.path + ".tmp-%d" % os.getpid()
        self.H, self.W = T.h * self.px, T.w * self.px
        self.arr: Optional[np.memmap] = None
        self.ready = False
        self.baking = False
        self.progress = 0.0
        self.error: Optional[str] = None
        self.ms = 0.0
        self.loaded_from_disk = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._fallback: Optional[np.ndarray] = None
        self._spr_cache: Dict[int, np.ndarray] = {}

    # -- lifecycle
    def start(self, background: bool = True) -> "GroundBake":
        """Open the file if it exists (~20 ms), else paint it: in a thread by default, inline for tests / pre-bakes."""
        if self.ready or self.baking:
            return self
        if os.path.exists(self.path):
            try:
                self._open()
                self.loaded_from_disk = True
                self.log("bake: loaded %s" % os.path.basename(self.path))
                return self
            except Exception as e:                       # a torn file: repaint it
                self.log("bake: reopen failed (%s), repainting" % e)
                try:
                    os.remove(self.path)
                except OSError:
                    pass
        self.baking = True
        if background:
            self._thread = threading.Thread(target=self._paint_safe, name="ground-bake", daemon=True)
            self._thread.start()
        else:
            self._paint_safe()
        return self

    def wait(self, timeout: Optional[float] = None) -> bool:
        if self._thread is not None:
            self._thread.join(timeout)
        return self.ready

    def close(self) -> None:
        with self._lock:
            if self.arr is not None:
                try:
                    self.arr.flush()
                except Exception:
                    pass
                self.arr = None
            self.ready = False

    def _open(self) -> None:
        arr = np.load(self.path, mmap_mode="r+")
        if arr.shape != (self.H, self.W, 3) or arr.dtype != np.uint8:
            raise ValueError("bake shape %s" % (arr.shape,))
        with self._lock:
            self.arr = arr
            self.ready = True

    def _paint_safe(self) -> None:
        t0 = time.perf_counter()
        try:
            self._paint()
            self.ms = (time.perf_counter() - t0) * 1000
            self.log("bake: painted %s in %.0f ms" % (os.path.basename(self.path), self.ms))
        except Exception as e:
            self.error = "%s: %s" % (type(e).__name__, e)
            self.log("bake: FAILED %s" % self.error)
            try:
                os.remove(self.tmp)
            except OSError:
                pass
        finally:
            self.baking = False

    # -- painting
    def _paint(self) -> None:
        os.makedirs(bake_dir(self.run_dir), exist_ok=True)
        T = self.T
        cells = cells_with_marks(T, self.marks)
        arr = np.lib.format.open_memmap(self.tmp, mode="w+", dtype=np.uint8, shape=(self.H, self.W, 3))
        n_strips = int(math.ceil(T.h / STRIP_CELLS))
        for k in range(n_strips):
            self.paint_strip(arr, cells, k * STRIP_CELLS, min(T.h, (k + 1) * STRIP_CELLS))
            self.progress = 0.7 * (k + 1) / n_strips
        self.paint_props(arr, (0, 0, T.w, T.h))
        self.progress = 1.0
        arr.flush()
        del arr
        os.replace(self.tmp, self.path)
        self._open()
        prune(self.run_dir, keep=(self.path,))

    def paint_strip(self, arr: np.ndarray, cells: np.ndarray, y0: int, y1: int, x0: int = 0, x1: Optional[int] = None) -> None:
        """Ground texture for cell rows [y0, y1) x cols [x0, x1) via tiles.Ground, painted with a one-TILE overlap so
        edges and foam at the seam match; only the interior is written. Rows / cols are snapped to tile boundaries."""
        T = self.T
        x1 = T.w if x1 is None else x1
        ty0, ty1 = max(0, (y0 // TILE_CELLS - 1) * TILE_CELLS), min(T.h, ((y1 + TILE_CELLS - 1) // TILE_CELLS + 1) * TILE_CELLS)
        tx0, tx1 = max(0, (x0 // TILE_CELLS - 1) * TILE_CELLS), min(T.w, ((x1 + TILE_CELLS - 1) // TILE_CELLS + 1) * TILE_CELLS)
        sub = cells[ty0:ty1, tx0:tx1]
        shade = T.shade[ty0:ty1, tx0:tx1]
        g = tiles.Ground(sub, self.season, origin=(tx0 // TILE_CELLS, ty0 // TILE_CELLS), shade=shade, seed=T.seed)
        rgb = g.paint(BAKE_WIND_PHASE, BAKE_RIPPLE_PHASE)
        px = self.px
        if px != CELL:
            rgb = resample(rgb, (rgb.shape[1] * px // CELL, rgb.shape[0] * px // CELL))
        ly0, ly1 = (y0 - ty0) * px, (y1 - ty0) * px
        lx0, lx1 = (x0 - tx0) * px, (x1 - tx0) * px
        arr[y0 * px:y1 * px, x0 * px:x1 * px] = rgb[ly0:ly1, lx0:lx1]

    def _objects(self, region: Tuple[int, int, int, int]) -> List[Tuple[int, str, tuple]]:
        """Everything blitted over the ground inside a cell rectangle (with a sprite-sized margin), y-sorted."""
        x0, y0, x1, y1 = region
        m = 20                                            # cells: the largest sprite reaches ~16 cells above its foot
        objs = []
        for (x, y, age, var) in self.T.trees:
            if x0 - m <= x < x1 + m and y0 - m <= y < y1 + m:
                objs.append((y, "tree", (x, y, age, var)))
        for (x, y, var) in self.T.boulders:
            if x0 - m <= x < x1 + m and y0 - m <= y < y1 + m:
                objs.append((y, "stone", (x, y, var)))
        for (x, y) in self.T.ford_stones:
            if x0 - m <= x < x1 + m and y0 - m <= y < y1 + m:
                objs.append((y, "fordstone", (x, y)))
        for h in self.marks.get("huts", ()):
            t = int(h.get("tier", 0))
            if t <= 0:
                continue
            hx, hy = int(h["x"]), int(h["y"])
            if x0 - m <= hx < x1 + m and y0 - m <= hy < y1 + m:
                objs.append((hy + 8, "hut", (hx, hy, t, h.get("owner") or "", bool(h.get("lit", False)))))
        for f in self.marks.get("flowers", ()):
            fx, fy = int(f["x"]), int(f["y"])
            if x0 - m <= fx < x1 + m and y0 - m <= fy < y1 + m:
                objs.append((fy, "flower", (fx, fy, int(f.get("variant", 0)), f.get("owner") or "")))
        objs.sort(key=lambda o: o[0])
        return objs

    def _sprite(self, spr: np.ndarray) -> np.ndarray:
        """A prop at this bake's scale (BOX-reduced once and cached for the 3 px/cell bake)."""
        if self.px == CELL:
            return spr
        key = id(spr)
        out = self._spr_cache.get(key)
        if out is None:
            from PIL import Image
            im = Image.fromarray(spr).resize((max(1, spr.shape[1] * self.px // CELL), max(1, spr.shape[0] * self.px // CELL)), Image.Resampling.BOX)
            out = np.asarray(im)
            self._spr_cache[key] = out
        return out

    def paint_props(self, arr: np.ndarray, region: Tuple[int, int, int, int]) -> int:
        """Blit the wild Wood, boulders, ford stones, huts and flowers whose ground point lies near `region` (cells),
        clipped to the region's pixels so a repaint never double-composites a sprite's edge. Returns the count."""
        x0, y0, x1, y1 = region
        px = self.px
        px0, py0, px1, py1 = x0 * px, y0 * px, x1 * px, y1 * px
        dst = arr[py0:py1, px0:px1]
        sun, season = self.sun, self.season
        n = 0
        for _, kind, data in self._objects(region):
            if kind == "tree":
                x, y, age, var = data
                put(dst, self._sprite(props.tree(age, var, BAKE_WIND_PHASE, season, sun)), x * px + px // 2 - px0, y * px + px - 1 - py0)
            elif kind == "stone":
                x, y, var = data
                put(dst, self._sprite(props.stone(var, sun)), x * px + px // 2 - px0, y * px + px - 1 - py0)
            elif kind == "fordstone":
                x, y = data
                put(dst, self._sprite(props.stone(0, sun)), x * px + px // 2 - px0, y * px + px - py0)
            elif kind == "hut":
                hx, hy, t, owner, lit = data
                bt = CAMP_TO_BUILDING.get(t, 1)
                if bt is None:
                    continue
                colour = owner if owner else (180, 120, 90)
                spr, (dx, dy) = buildings.render("hut", bt, colour, None, False, sun)
                blit(dst, self._sprite(spr), hx * px - dx * px // CELL - px0, hy * px - dy * px // CELL - py0)
            elif kind == "flower":
                fx, fy, var, owner = data
                put(dst, self._sprite(props.flowers(var, BAKE_WIND_PHASE)), fx * px + px // 2 - px0, fy * px + px - 1 - py0)
            n += 1
        return n

    # -- repaint
    def repaint(self, region: Tuple[int, int, int, int], marks: Optional[Dict] = None) -> float:
        """Repaint one cell rectangle (x0, y0, x1, y1) after a mark changed there: ground texture (tile-snapped) and
        every sprite reaching into it. Index writes into the memmap; returns the ms it took. Safe to call from any
        thread; the frame path only ever reads."""
        if marks is not None:
            self.marks = marks
        if not self.ready or self.arr is None:
            return 0.0
        t0 = time.perf_counter()
        T = self.T
        x0, y0, x1, y1 = region
        # widen by the tallest sprite so a hut / tree whose foot is outside but whose crown is inside gets redrawn
        x0, y0 = max(0, x0 - 4), max(0, y0 - 18)
        x1, y1 = min(T.w, x1 + 4), min(T.h, y1 + 4)
        cells = cells_with_marks(T, self.marks)
        with self._lock:
            self.paint_strip(self.arr, cells, y0, y1, x0, x1)
            self.paint_props(self.arr, (x0, y0, x1, y1))
        return (time.perf_counter() - t0) * 1000

    # -- reads
    def crop(self, bx0: int, by0: int, w: int, h: int) -> np.ndarray:
        """The (h, w, 3) uint8 window of the bake at bake-pixel (bx0, by0); a copy when it crosses the map edge
        (edge-padded), else a view into the memmap (copy() it before drawing on it)."""
        arr = self.arr
        if bx0 >= 0 and by0 >= 0 and bx0 + w <= self.W and by0 + h <= self.H:
            return arr[by0:by0 + h, bx0:bx0 + w]
        out = np.empty((h, w, 3), np.uint8)
        ax0, ay0 = max(0, bx0), max(0, by0)
        ax1, ay1 = min(self.W, bx0 + w), min(self.H, by0 + h)
        if ax1 <= ax0 or ay1 <= ay0:
            out[:] = 40
            return out
        sub = arr[ay0:ay1, ax0:ax1]
        oy, ox = ay0 - by0, ax0 - bx0
        out[oy:oy + sub.shape[0], ox:ox + sub.shape[1]] = sub
        if oy > 0:
            out[:oy] = out[oy:oy + 1]
        if oy + sub.shape[0] < h:
            out[oy + sub.shape[0]:] = out[oy + sub.shape[0] - 1:oy + sub.shape[0]]
        if ox > 0:
            out[:, :ox] = out[:, ox:ox + 1]
        if ox + sub.shape[1] < w:
            out[:, ox + sub.shape[1]:] = out[:, ox + sub.shape[1] - 1:ox + sub.shape[1]]
        return out

    def fallback(self, bx0: int, by0: int, w: int, h: int) -> np.ndarray:
        """Cell-res biome colours x4 (the cave's proven path) for the same window: what shows until the bake exists."""
        if self._fallback is None:
            self._fallback = self.T.biome_rgb()
        px = self.px
        cx0, cy0 = bx0 // px, by0 // px
        cw, ch = (bx0 % px + w + px - 1) // px, (by0 % px + h + px - 1) // px
        cells = np.empty((ch, cw, 3), np.uint8)
        cells[:] = 40
        ax0, ay0 = max(0, cx0), max(0, cy0)
        ax1, ay1 = min(self.T.w, cx0 + cw), min(self.T.h, cy0 + ch)
        if ax1 > ax0 and ay1 > ay0:
            cells[ay0 - cy0:ay1 - cy0, ax0 - cx0:ax1 - cx0] = self._fallback[ay0:ay1, ax0:ax1]
        big = np.repeat(np.repeat(cells, px, 0), px, 1)
        ox, oy = bx0 % px, by0 % px
        return big[oy:oy + h, ox:ox + w]

    def ground(self, bx0: int, by0: int, w: int, h: int) -> np.ndarray:
        return self.crop(bx0, by0, w, h) if self.ready else self.fallback(bx0, by0, w, h)

    def stats(self) -> Dict:
        return {"path": os.path.basename(self.path), "ready": self.ready, "baking": self.baking, "progress": round(self.progress, 2),
                "ms": round(self.ms), "octant": self.octant, "season": self.season_idx, "ver": self.bake_ver,
                "from_disk": self.loaded_from_disk, "error": self.error}


class BakeManager:
    """Keeps the CURRENT bake and lands the next one (new season / sun octant / bake_ver) in the background; the frame
    path always reads a ready bake (or the fallback before the very first one). `want()` once per frame is cheap."""

    def __init__(self, run_dir: str, T: "_terrain.Terrain", log=None, px_per_cell: int = CELL):
        self.run_dir, self.T, self.log = run_dir, T, log or (lambda *a: None)
        self.px = int(px_per_cell)
        self.current: Optional[GroundBake] = None
        self.pending: Optional[GroundBake] = None
        self.marks: Dict = {}

    def want(self, season_idx: int, sun: Sequence[float], bake_ver: int, marks: Optional[Dict] = None) -> GroundBake:
        if marks is not None:
            self.marks = marks
        key = (int(season_idx) % 4, sun_octant(sun), int(bake_ver))
        if self.pending is not None:
            if self.pending.ready:
                old, self.current, self.pending = self.current, self.pending, None
                if old is not None:
                    old.close()
            elif self.pending.error:
                self.pending = None
        cur = self.current
        if cur is not None and (cur.season_idx, cur.octant, cur.bake_ver) == key:
            return cur
        if self.pending is not None and (self.pending.season_idx, self.pending.octant, self.pending.bake_ver) == key:
            return cur if cur is not None else self.pending
        b = GroundBake(self.run_dir, self.T, key[0], sun, key[2], self.marks, self.log, self.px).start(background=True)
        if b.ready and cur is None:
            self.current = b
            return b
        if b.ready:
            old, self.current = self.current, b
            if old is not None:
                old.close()
            return b
        if cur is None:
            self.current = b                       # first ever bake: the frame path uses its fallback until ready
            return b
        self.pending = b
        return cur

    @property
    def baking(self) -> bool:
        return bool((self.pending and self.pending.baking) or (self.current and self.current.baking))


# ----------------------------------------------------------------------------- per-frame helpers
def view_cells(bx0: int, by0: int, w: int, h: int, cell_px: int = CELL) -> Tuple[int, int, int, int, int, int]:
    """The cell window that covers a bake-pixel crop: (cx0, cy0, cw, ch, ox, oy) with (ox, oy) the crop's offset
    inside its first cell (0..cell_px-1). `cell_px` is the bake's px per cell (4 at 1x, 3 for the 0.75x bake)."""
    cx0, cy0 = bx0 // cell_px, by0 // cell_px
    ox, oy = bx0 - cx0 * cell_px, by0 - cy0 * cell_px
    cw, ch = (ox + w + cell_px - 1) // cell_px, (oy + h + cell_px - 1) // cell_px
    return cx0, cy0, cw, ch, ox, oy


class Applier:
    """The fixed-point multiply with reusable buffers (no per-frame allocation):
         crop (ch*px, cw*px, 3) uint8  x  field (ch, cw, 3) <= 1.0  ->  uint8, three passes over the pixels:
         1. the field x255 as uint8, repeated to pixel size (two cheap repeats, uint8)
         2. one uint16 multiply of the two uint8 arrays
         3. the HIGH BYTE of the product is the result (crop * field * 255/256): no shift, no clamp, no cast
       plus the water sparkle, added per 4x4 (or 3x3) block for the few cells that glint this frame.
       `bake.apply()` wraps a module-level Applier."""

    def __init__(self):
        self._buf16: Optional[np.ndarray] = None
        self._big8: Optional[np.ndarray] = None

    def __call__(self, crop: np.ndarray, field: np.ndarray, ox: int = 0, oy: int = 0, w: Optional[int] = None,
                 h: Optional[int] = None, sparkle=None, cell_px: int = CELL) -> np.ndarray:
        ch, cw = field.shape[:2]
        H, W = ch * cell_px, cw * cell_px
        if crop.shape[0] < H or crop.shape[1] < W:                  # a short crop (map edge): pad with its edge
            crop = np.pad(crop, ((0, H - crop.shape[0]), (0, W - crop.shape[1]), (0, 0)), mode="edge")
        crop = crop[:H, :W]
        f8 = np.clip(field * np.float32(255.0), 0, 255).astype(np.uint8)
        big8 = np.repeat(np.repeat(f8, cell_px, 1), cell_px, 0)
        if self._buf16 is None or self._buf16.shape != (H, W, 3):
            self._buf16 = np.empty((H, W, 3), np.uint16)
        buf = self._buf16
        np.multiply(crop, big8, out=buf, dtype=np.uint16)
        if sparkle is not None:
            ys, xs, gain = sparkle
            keep = (ys >= 0) & (ys < ch) & (xs >= 0) & (xs < cw)
            if keep.any():
                ys, xs = ys[keep], xs[keep]
                b5 = buf.reshape(ch, cell_px, cw, cell_px, 3)
                blocks = b5[ys, :, xs, :, :]                        # (n, px, px, 3) gathered copies
                blocks = np.minimum(blocks.astype(np.uint32) + int(gain * 256), 65535).astype(np.uint16)
                b5[ys, :, xs, :, :] = blocks
        hi = buf.view(np.uint8)[..., 1::2]                          # little-endian: byte 1 = the high byte
        w = W - ox if w is None else w
        h = H - oy if h is None else h
        return np.ascontiguousarray(hi[oy:oy + h, ox:ox + w])


_APPLIER = Applier()


def apply(crop: np.ndarray, field: np.ndarray, ox: int = 0, oy: int = 0, w: Optional[int] = None, h: Optional[int] = None,
          sparkle=None, cell_px: int = CELL) -> np.ndarray:
    """Multiply the cell-res modulation field (ch, cw, 3 float32, <= 1.0) into the cell-ALIGNED pixel crop
    (ch*cell_px, cw*cell_px, 3 uint8) and return the (h, w) window at (ox, oy) inside it, uint8. `sparkle` is
    Nature.last_sparkle. See Applier."""
    return _APPLIER(crop, field, ox, oy, w, h, sparkle, cell_px)


def resample(rgb: np.ndarray, size: Tuple[int, int]) -> np.ndarray:
    """0.75x: BOX down to (w, h); 1.5x: BILINEAR up. Identity when the size already matches."""
    from PIL import Image
    h, w = rgb.shape[:2]
    if (w, h) == tuple(size):
        return rgb
    method = Image.Resampling.BOX if size[0] < w else Image.Resampling.BILINEAR
    return np.asarray(Image.fromarray(np.ascontiguousarray(rgb)).resize(size, method))


if __name__ == "__main__":
    import sys
    run_dir = os.environ.get("RUN_DIR") or "/tmp/lg-bake"
    if not os.path.realpath(run_dir).startswith(("/tmp/", "/private/tmp/")):
        print("refusing: RUN_DIR must be under /tmp for this test", file=sys.stderr)
        sys.exit(2)
    from stream.world import nature
    T = _terrain.generate(4471)
    marks = {"wear": None, "huts": [{"x": T.site[0] - 40, "y": T.site[1] + 30, "tier": 2, "owner": "test-pip-01", "lit": False}],
             "fields": [{"x": T.site[0] - 40, "y": T.site[1] + 40, "stage": 3, "owner": "test-pip-01"}], "flowers": []}
    for f in os.listdir(bake_dir(run_dir)) if os.path.isdir(bake_dir(run_dir)) else []:
        os.remove(os.path.join(bake_dir(run_dir), f))
    B = GroundBake(run_dir, T, 0, nature.sun_vector(12.0), 0, marks, log=print)
    t0 = time.perf_counter()
    B.start(background=True)
    frames_during, fmax = 0, 0.0
    while B.baking:
        t1 = time.perf_counter()
        g = B.ground(T.site[0] * 4 - 640, T.site[1] * 4 - 220, 1280, 440)     # fallback path while baking
        fmax = max(fmax, (time.perf_counter() - t1) * 1000)
        frames_during += 1
        time.sleep(0.01)
    B.wait()
    print("bake: %.0f ms total wall; %d fallback frames read meanwhile, max %.2f ms; stats %s" % ((time.perf_counter() - t0) * 1000, frames_during, fmax, B.stats()))
    t0 = time.perf_counter()
    B2 = GroundBake(run_dir, T, 0, nature.sun_vector(12.0), 0, marks).start()
    print("reopen from disk: %.1f ms ready=%s" % ((time.perf_counter() - t0) * 1000, B2.ready))
    ms = B.repaint((T.site[0] - 40, T.site[1] + 30, T.site[0] - 26, T.site[1] + 42))
    print("repaint 14x12-cell hut region: %.1f ms" % ms)
    N = nature.Nature(T, 4471)
    now = time.time()
    N.update(now, 2.0)
    B3 = GroundBake(run_dir, T, 0, nature.sun_vector(12.0), 0, marks, log=print, px_per_cell=3).start(background=False)
    print("3 px/cell bake: %s" % B3.stats())
    for label, bk, (w, h) in (("1x 1280x440 (4 px bake)", B, (1280, 440)), ("0.75x 1707x587 crop -> BOX (4 px bake)", B, (1707, 587)),
                              ("0.75x 1280x440 straight (3 px bake)", B3, (1280, 440))):
        px = bk.px
        bx0, by0 = T.site[0] * px - w // 2 + 1, T.site[1] * px - h // 2 + 2
        cx, cy, cw, ch, ox, oy = view_cells(bx0, by0, w, h, px)
        ts = {"crop": [], "field": [], "apply": [], "resample": []}
        for i in range(60):
            t1 = time.perf_counter(); crop = bk.crop(cx * px, cy * px, cw * px, ch * px); t2 = time.perf_counter()
            field = N.modulation((cx, cy, cw, ch), now + i / 30.0); t3 = time.perf_counter()
            out = apply(crop, field, ox, oy, w, h, N.last_sparkle, px); t4 = time.perf_counter()
            out3 = resample(out, (1280, 440)); t5 = time.perf_counter()
            for k, v in zip(ts, ((t2 - t1), (t3 - t2), (t4 - t3), (t5 - t4))):
                ts[k].append(v * 1000)
        tot = sum(float(np.mean(v[10:])) for v in ts.values())
        print("%-40s %s · total %.2f ms" % (label, " · ".join("%s %.2f" % (k, float(np.mean(v[10:]))) for k, v in ts.items()), tot))
        assert out3.shape == (440, 1280, 3), out3.shape
    from PIL import Image
    Image.fromarray(out3).save(os.path.join(run_dir, "bake_test_frame.png"))
    print("wrote", os.path.join(run_dir, "bake_test_frame.png"))
