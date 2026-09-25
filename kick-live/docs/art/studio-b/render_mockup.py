"""render_mockup.py - studio-b SETTLEMENT mockups rendered FROM the generators (no hand-placed pixels).

    python render_mockup.py          # mockup_busy.png (evening, 14 pips), mockup_dawn.png (empty dawn),
                                     # thumb_320x180.png, and a per-frame timing report on stdout
    python render_mockup.py --ascii  # print the tile map as text (layout check)

World: value-noise elevation + moisture -> grass kinds, forest patches, hills; an explicit coast to the
east and a river traced from the hills to the sea; a village on a plaza with connected worn trails, a
well, farms; cottages composed per builder (buildings.py); trees, bushes, rocks, reeds, flowers (tiles.py
props); pips from creatures.py. Evening light = a tinted copy of the atlas and sprites (done once).

Per-frame path (what the compositor would run at 30 fps) is `Scene.compose(t)`:
    1. tile ids for this frame (wind / ripple / foam phases + cloud-shadow variant), ~700 ints
    2. ONE numpy gather from the atlas -> the terrain
    3. tiles that have static sprites on them (trees, cottages, rocks...) are replaced from a per-position
       cache keyed by (tile id, sway phase): the composite of terrain + sprites for that tile, built lazily.
       So static props cost nothing per frame after warm-up.
    4. the pips: ~20 alpha blits, plus re-blits of the few static sprites that stand in front of a pip.
`bench()` times it with 20 animated pips on the 1280x532 world region.
"""
from __future__ import annotations

import math
import os
import sys
import time
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import buildings  # noqa: E402
import creatures  # noqa: E402
import hud  # noqa: E402
import tiles  # noqa: E402
from common import alpha_blit, tint_rgba  # noqa: E402

T = tiles.T
SEED = 4471
MAP_W, MAP_H = 64, 34
VIEW_W, VIEW_H = 40, 17           # tiles in view (1280 x 544, cropped to the 532 px world region)
WX0, WY0, WX1, WY1 = hud.WORLD
WORLD_H = WY1 - WY0
VC = (24, 17)                     # village centre tile
CAM = (VC[0] - 15, VC[1] - 8)     # camera: village left of centre, coast on the right third


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


def fbm(u, v, freq, octaves, seed, gain=0.5):
    total = np.zeros_like(u, dtype=np.float32)
    amp, norm = 1.0, 0.0
    for o in range(octaves):
        total += amp * vnoise(u, v, freq, seed + o * 101)
        norm += amp
        amp *= gain
        freq *= 2.0
    return total / norm


def _bezier(pts, n):
    """Catmull-Rom through pts, n samples per segment."""
    out = []
    P = [pts[0]] + list(pts) + [pts[-1]]
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for k in range(n):
            t = k / n
            t2, t3 = t * t, t * t * t
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 +
                       (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 +
                       (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            out.append((x, y))
    return out


# ----------------------------------------------------------------------------- world model
class World:
    def __init__(self, busy: bool):
        self.busy = busy
        self.rng = np.random.RandomState(SEED)
        v, u = np.mgrid[0:MAP_H, 0:MAP_W].astype(np.float32)
        self.u, self.v = u, v
        self.M = fbm(u, v, 1 / 7.0, 3, SEED + 7000)
        # coast: land for x < ~44, wobbling; sea beyond
        coast = 44 + 3.5 * (fbm(u * 0 + v, v * 0, 1 / 9.0, 2, SEED + 3) - 0.5) * 2
        self.sea = u > coast
        self.pond = ((u - 12) ** 2 / 5.0 + (v - 26) ** 2 / 2.2) < 1.7          # pond south-west
        self.water = self.sea | self.pond
        self.E = np.clip(0.5 + 0.35 * (fbm(u, v, 1 / 10.0, 2, SEED) - 0.5) + 0.42 * np.exp(-(((u - 12) ** 2) / 45 + ((v - 10) ** 2) / 18)), 0, 1)
        self._river()
        self._classify()
        self._village()
        self._props()

    def _river(self):
        pts = [(9, 6), (13, 10), (15, 14), (18, 21), (26, 24), (34, 23), (42, 21), (48, 20)]
        self.river = _bezier(pts, 10)
        for (x, y) in self.river:
            xi, yi = int(round(x)), int(round(y))
            if 0 <= xi < MAP_W and 0 <= yi < MAP_H:
                self.water[yi, xi] = True
                if x > 30 and 0 <= yi + 1 < MAP_H:  # widens towards the mouth
                    self.water[yi + 1, xi] = True

    def _classify(self):
        W = self.water
        pad = np.pad(W, 1, mode="edge")
        n8 = pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:] | pad[:-2, :-2] | pad[:-2, 2:] | pad[2:, :-2] | pad[2:, 2:]
        Sp = np.pad(self.sea | self.pond, 1, mode="edge")
        near_sea = Sp[:-2, 1:-1] | Sp[2:, 1:-1] | Sp[1:-1, :-2] | Sp[1:-1, 2:] | Sp[:-2, :-2] | Sp[:-2, 2:] | Sp[2:, :-2] | Sp[2:, 2:]
        self.sand = (~W) & near_sea
        landpad = np.pad(~W, 1, mode="edge")
        land8 = landpad[:-2, 1:-1] | landpad[2:, 1:-1] | landpad[1:-1, :-2] | landpad[1:-1, 2:] | landpad[:-2, :-2] | \
            landpad[:-2, 2:] | landpad[2:, :-2] | landpad[2:, 2:]
        land8b = np.pad(land8 | ~W, 1, mode="edge")
        land16 = land8b[:-2, 1:-1] | land8b[2:, 1:-1] | land8b[1:-1, :-2] | land8b[1:-1, 2:]
        self.shallow = W & land16
        self.edge_mask = (landpad[:-2, 1:-1] * 1 + landpad[1:-1, 2:] * 2 + landpad[2:, 1:-1] * 4 + landpad[1:-1, :-2] * 8)
        self.edge_mask = np.where(W, self.edge_mask, 0).astype(np.int32)
        self.hill = (~W) & (~self.sand) & (self.E > 0.78)
        hp = np.pad(self.hill, 1)
        self.hill_edge = self.hill & ~hp[2:, 1:-1]
        vx, vy = VC
        clearing = ((self.u - vx) ** 2 / 90.0 + (self.v - vy) ** 2 / 42.0) < 1.0
        self.forest = (~W) & (~self.sand) & (~self.hill) & (self.M > 0.60) & ~clearing
        kind = np.full(W.shape, 1, np.int32)  # 0 meadow 1 grass 2 lush 3 dry
        kind[self.M < 0.34] = 0
        kind[self.M >= 0.52] = 2
        kind[(self.E > 0.72) & (self.M < 0.40)] = 3
        kind[np.abs(self.u - self.water.argmax(axis=1)[:, None]) < 3] = 0   # meadow strip inland of the coast
        self.grass_kind = kind
        fl = fbm(self.u, self.v, 1 / 3.0, 2, 99)
        self.flowers = (kind == 0) & (fl > 0.66) & ~clearing
        self.path = np.zeros(W.shape, np.int32)
        self.farm = np.zeros(W.shape, np.int32)

    def _village(self):
        rng = self.rng
        vx, vy = VC
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                self.path[vy + dy, vx + dx] = 3 if abs(dx) + abs(dy) <= 1 else 2
        names = creatures.EXAMPLES + ["tinytash", "pixel_dude", "quietnoodle"]
        self.builders: List[Tuple[str, int, int, int]] = []  # name, tile x, tile y (footprint top-left), stage
        ring = [(-6, -5), (2, -6), (7, -3), (6, 3), (-1, 5), (-7, 2), (-9, -2), (9, -1)]
        stages = (2, 3, 1, 2, 2, 3, 1, 2)
        n_houses = 8 if self.busy else 2
        for i in range(n_houses):
            dx, dy = ring[i]
            hx, hy = vx + dx, vy + dy
            while self.water[hy:hy + 3, hx:hx + 4].any() or self.sand[hy:hy + 3, hx:hx + 4].any():
                hx -= 1
            self.builders.append((names[i], hx, hy, stages[i] if self.busy else (2, 1)[i]))
            self.forest[hy - 1:hy + 4, hx - 1:hx + 5] = False
            self._trail((hx + 1, hy + 3), (vx, vy), rng, level=2 if self.busy else 1)
        # farm strip
        fx, fy = vx + 3, vy + 3
        if self.busy:
            for dy in range(2):
                for dx in range(3):
                    if not (self.water[fy + dy, fx + dx] or self.sand[fy + dy, fx + dx]):
                        self.farm[fy + dy, fx + dx] = (3, 2, 3, 2, 1, 3)[dy * 3 + dx]
            self._trail((fx - 1, fy), (vx, vy), rng)
        else:
            self.farm[fy, fx] = 2
        # trail to the river and one to the sea shore
        self._trail((vx, vy), (vx + 1, vy + 6), rng, level=2 if self.busy else 1)
        if self.busy:
            self._trail((vx + 3, vy - 2), (vx + 17, vy - 3), rng, level=1)
        self.path[self.water] = 0
        self.path[self.farm > 0] = 0
        self.forest[self.path > 0] = False
        # connection masks for the trail tiles
        P = self.path > 0
        pp = np.pad(P, 1)
        self.path_mask = (pp[:-2, 1:-1] * 1 + pp[1:-1, 2:] * 2 + pp[2:, 1:-1] * 4 + pp[1:-1, :-2] * 8).astype(np.int32)

    def _trail(self, a, b, rng, level=2):
        x0, y0 = a
        x1, y1 = b
        n = int(max(abs(x1 - x0), abs(y1 - y0)) * 3) + 1
        lx, ly = None, None
        for i in range(n + 1):
            t = i / n
            wob = math.sin(t * math.pi) * 1.4 * math.sin(x0 * 0.7 + y0 * 1.3)
            x = int(round(x0 + (x1 - x0) * t + wob * 0.5))
            y = int(round(y0 + (y1 - y0) * t - wob * 0.5))
            if lx is not None and x != lx and y != ly:   # keep 4-connected
                x = lx
            if 0 <= x < MAP_W and 0 <= y < MAP_H and not self.water[y, x]:
                self.path[y, x] = max(self.path[y, x], level)
            lx, ly = x, y

    def _props(self):
        rng = np.random.RandomState(SEED + 5)
        self.tree_list = []   # (x_px, y_px, size)
        self.prop_list = []   # (x_px, y_px, key)
        vx, vy = VC
        for y in range(MAP_H):
            for x in range(MAP_W):
                px, py = x * T, y * T
                near_house = any(hx - 1 <= x <= hx + 4 and hy - 1 <= y <= hy + 3 for _, hx, hy, _ in self.builders)
                if self.forest[y, x]:
                    edge = not (self.forest[max(0, y - 1), x] and self.forest[min(MAP_H - 1, y + 1), x] and
                                self.forest[y, max(0, x - 1)] and self.forest[y, min(MAP_W - 1, x + 1)])
                    size = 1 if edge else (2 if self.M[y, x] > 0.70 else int(rng.choice([1, 2])))
                    self.tree_list.append((px + rng.randint(-6, 8), py + rng.randint(-6, 8), size))
                    if rng.rand() < 0.4 and not edge:
                        self.tree_list.append((px + rng.randint(8, 22), py + rng.randint(6, 20), 0))
                    if edge and rng.rand() < 0.35:
                        self.prop_list.append((px + rng.randint(0, 12), py + rng.randint(12, 22), "bush.%d" % rng.randint(0, 2)))
                elif not self.water[y, x] and self.path[y, x] == 0 and self.farm[y, x] == 0 and not near_house:
                    r = rng.rand()
                    if self.sand[y, x]:
                        if r < 0.25:
                            self.prop_list.append((px + rng.randint(2, 10), py + rng.randint(0, 6), "reeds.s%d" % rng.randint(0, 2)))
                        elif r < 0.33:
                            self.prop_list.append((px + rng.randint(2, 10), py + rng.randint(2, 10), "rock.%d" % rng.randint(0, 2)))
                    elif self.hill[y, x]:
                        if r < 0.20:
                            self.prop_list.append((px + rng.randint(2, 10), py + rng.randint(2, 10), "rock.%d" % rng.randint(0, 2)))
                        elif r < 0.32:
                            self.tree_list.append((px + rng.randint(-4, 6), py + rng.randint(-8, 4), 0))
                    else:
                        far = abs(x - vx) + abs(y - vy) > 8
                        if self.grass_kind[y, x] == 0 and r < 0.10:
                            self.prop_list.append((px + rng.randint(2, 12), py + rng.randint(2, 12), "flowers.%d" % rng.randint(0, 2)))
                        elif r < 0.045 and far:
                            self.tree_list.append((px + rng.randint(-4, 6), py + rng.randint(-8, 4), int(rng.randint(0, 3))))
                        elif r < 0.07 and far:
                            self.prop_list.append((px + rng.randint(2, 10), py + rng.randint(2, 10), "bush.%d" % rng.randint(0, 2)))

    def ascii(self) -> str:
        rows = []
        for y in range(MAP_H):
            row = ""
            for x in range(MAP_W):
                ch = "."
                if self.water[y, x]:
                    ch = "~"
                elif self.farm[y, x]:
                    ch = "#"
                elif self.path[y, x]:
                    ch = "="
                elif self.sand[y, x]:
                    ch = ":"
                elif self.hill[y, x]:
                    ch = "^"
                elif self.forest[y, x]:
                    ch = "T"
                elif self.flowers[y, x]:
                    ch = "*"
                for name, hx, hy, st in self.builders:
                    if hx <= x < hx + 3 and hy <= y < hy + 3:
                        ch = "H"
                if (x, y) == VC:
                    ch = "O"
                if CAM[0] <= x < CAM[0] + VIEW_W and CAM[1] <= y < CAM[1] + VIEW_H:
                    row += ch
                else:
                    row += ch.lower() if ch != "." else " "
            rows.append(row)
        return "\n".join(rows)


# ----------------------------------------------------------------------------- scene (per-frame path)
class Scene:
    def __init__(self, world: World, evening: bool, cam: Tuple[int, int]):
        self.w = world
        self.evening = evening
        self.cam = cam
        atlas, self.idx = tiles.build_atlas()
        tint = (1.10, 0.90, 0.72) if evening else (0.93, 0.98, 1.06)
        self.tint = tint
        lit = tiles.light_atlas(atlas, tint)
        shaded = tiles.light_atlas(atlas, tuple(t * 0.87 for t in tint))
        self.atlas = np.concatenate([lit, shaded])          # [id] sunlit, [id + n] under a cloud
        self.n_tiles = len(atlas)
        self.props = {k: tint_rgba(v, tint) for k, v in tiles.props().items()}
        self._bake_ids()
        self._bake_sprites()
        self.tile_cache: Dict[Tuple[int, int], Dict[Tuple[int, int], np.ndarray]] = {}

    # ---- tiles
    def _bake_ids(self):
        w, cx, cy = self.w, self.cam[0], self.cam[1]
        rows, cols = VIEW_H, VIEW_W
        base = np.zeros((rows, cols), np.int32)
        anim = np.zeros((rows, cols), np.int32)     # 0 static, 1 grass x4, 2 water x4, 3 edge x2
        off = np.zeros((rows, cols), np.float32)
        I = self.idx
        for r in range(rows):
            for c in range(cols):
                x, y = cx + c, cy + r
                if w.water[y, x]:
                    m = w.edge_mask[y, x]
                    if m:
                        base[r, c], anim[r, c] = I["water.edge.m%d.r0" % m], 3
                    elif w.shallow[y, x]:
                        base[r, c], anim[r, c] = I["water.shallow.%d.r0" % ((x * 7 + y * 3) % 3)], 2
                    else:
                        base[r, c], anim[r, c] = I["water.deep.%d.r0" % ((x * 5 + y * 3) % 3)], 2
                    off[r, c] = (x * 0.9 + y * 1.7) % 4
                elif w.farm[y, x]:
                    base[r, c] = I["farm.%s" % ("bare", "sprout", "ripe")[w.farm[y, x] - 1]]
                elif w.path[y, x]:
                    base[r, c] = I["path.m%d.%d" % (w.path_mask[y, x], w.path[y, x])]
                elif w.sand[y, x]:
                    base[r, c] = I["shore.sand.%d" % ((x + y) % 2)]
                elif w.hill[y, x]:
                    base[r, c] = I["hill.edge.s"] if w.hill_edge[y, x] else I["hill.top.%d" % ((x * 3 + y) % 2)]
                elif w.forest[y, x]:
                    base[r, c] = I["forest.floor.%d" % ((x + y) % 2)]
                else:
                    if w.flowers[y, x]:
                        base[r, c] = I["grass.flowers.%d.w0" % ((x + y) % 2)]
                    else:
                        base[r, c] = I["grass.%s.w0" % ("meadow", "grass", "lush", "dry")[w.grass_kind[y, x]]]
                    anim[r, c] = 1
                    off[r, c] = (x * 0.55 + y * 0.35)
        self.base, self.anim, self.off = base, anim, off
        gv, gu = np.mgrid[0:rows, 0:cols].astype(np.float32)
        self._cloud_u, self._cloud_v = gu + cx, gv + cy

    def tile_ids(self, t: float) -> np.ndarray:
        ids = self.base.copy()
        g = self.anim == 1
        ids[g] += (np.floor(self.off[g] + t * 1.6) % 4).astype(np.int32)
        wtr = self.anim == 2
        ids[wtr] += (np.floor(self.off[wtr] + t * 2.0) % 4).astype(np.int32)
        e = self.anim == 3
        ids[e] += (np.floor(self.off[e] * 0.5 + t * 1.2) % 2).astype(np.int32)
        cl = fbm(self._cloud_u + t * 0.35, self._cloud_v + t * 0.12, 1 / 7.0, 2, 4242)
        ids[cl > 0.62] += self.n_tiles
        return ids

    # ---- sprites
    def _bake_sprites(self):
        w = self.w
        cx, cy = self.cam[0] * T, self.cam[1] * T
        st: List[Tuple[float, int, int, object]] = []   # (sort_y, x, y, sprite | ("tree", size))
        for (px, py, size) in w.tree_list:
            st.append((py - cy + T, px - cx, py - cy, ("tree", size)))
        for (px, py, key) in w.prop_list:
            spr = self.props[key]
            st.append((py - cy + spr.shape[0] * 0.8, px - cx, py - cy, spr))
        night = self.evening
        self.house_pos: Dict[str, Tuple[int, int]] = {}
        for i, (name, hx, hy, stage) in enumerate(w.builders):
            spr = tint_rgba(buildings.cottage(name, stage, night=night, smoke_frame=(i % 3) if night else -1), self.tint)
            fw, fh = buildings.footprint(stage)
            x, y = hx * T - cx - 6, hy * T - cy - 12 + (T * 3 - fh)
            st.append((hy * T - cy + T * 3 - 2, x, y, spr))
            self.house_pos[name] = (hx * T - cx + fw // 2, hy * T - cy + T * 3 + 4)
        vx, vy = VC
        wl = tint_rgba(buildings.well(hud.C["honey"][:3]), self.tint)
        st.append((vy * T - cy + T - 2, vx * T - cx + 5, vy * T - cy + 2, wl))
        self.well_px = (vx * T - cx + T // 2, vy * T - cy + T // 2)
        if night:
            lan = buildings.lantern(True)
            for dx, dy in ((-48, 26), (52, 22)):
                st.append((vy * T - cy + T + dy, vx * T - cx + dx, vy * T - cy + dy - 24, lan))
        st.sort(key=lambda s: s[0])
        self.static = st
        # full static layers (one per tree-sway phase) and the set of tiles they touch
        self.static_layer = []
        for sway in range(2):
            layer = np.zeros((VIEW_H * T, VIEW_W * T, 4), np.uint8)
            for _, x, y, spr in st:
                s, xx, yy = self._resolve(spr, x, y, sway)
                buildings._blit_rgba(layer, s, xx, yy)
            self.static_layer.append(layer)
        occ = self.static_layer[0][..., 3].reshape(VIEW_H, T, VIEW_W, T).max(axis=(1, 3)) > 0
        occ |= self.static_layer[1][..., 3].reshape(VIEW_H, T, VIEW_W, T).max(axis=(1, 3)) > 0
        self.static_tiles = [(int(r), int(c)) for r, c in zip(*np.nonzero(occ))]
        # bounds for the occlusion re-blit test
        self.static_boxes = np.array([[x, y, x + self._resolve(spr, x, y, 0)[0].shape[1],
                                       y + self._resolve(spr, x, y, 0)[0].shape[0], sy] for sy, x, y, spr in st],
                                     dtype=np.float32) if st else np.zeros((0, 5), np.float32)

    def _resolve(self, spr, x, y, sway):
        if isinstance(spr, tuple):
            s = self.props["tree.%d.s%d" % (spr[1], sway)]
            return s, x - s.shape[1] // 2 + T // 2, y - s.shape[0] + T
        return spr, x, y

    def compose(self, t: float, pips: List[Tuple[str, int, str, int, int]]) -> np.ndarray:
        """pips: (name, tier, frame, x_px, y_px ground point) in world-region coordinates. Returns RGB (532,1280,3)."""
        ids = self.tile_ids(t)
        sway = int(t * 1.5) % 2
        blocks = self.atlas[ids]                              # (rows, cols, T, T, 3) gather
        layer = self.static_layer[sway]
        for (r, c) in self.static_tiles:                      # terrain + static sprites, cached per position
            key = (int(ids[r, c]), sway)
            cache = self.tile_cache.get((r, c))
            if cache is None:
                cache = self.tile_cache[(r, c)] = {}
            blk = cache.get(key)
            if blk is None:
                blk = blocks[r, c].copy()
                alpha_blit(blk, layer[r * T:(r + 1) * T, c * T:(c + 1) * T], 0, 0)
                cache[key] = blk
            blocks[r, c] = blk
        img = blocks.transpose(0, 2, 1, 3, 4).reshape(VIEW_H * T, VIEW_W * T, 3)[:WORLD_H]
        # pips, back to front, each followed by the static sprites that stand in front of it
        for (name, tier, frame, x, y) in sorted(pips, key=lambda p: p[4]):
            spr = self._pip(name, tier, frame)
            px, py = x - spr.shape[1] // 2, y - spr.shape[0] + 3
            alpha_blit(img, spr, px, py)
            if len(self.static_boxes):
                b = self.static_boxes
                hit = (b[:, 4] > y) & (b[:, 0] < px + spr.shape[1]) & (b[:, 2] > px) & (b[:, 1] < py + spr.shape[0]) & (b[:, 3] > py)
                for i in np.nonzero(hit)[0]:
                    _, sx, sy, sspr = self.static[i]
                    s, xx, yy = self._resolve(sspr, sx, sy, sway)
                    alpha_blit(img, s, xx, yy)
        if self.evening:
            self._glints(img, t)
        return img

    _pip_cache: Dict = {}

    def _pip(self, name, tier, frame):
        key = (name, tier, frame, self.tint)
        s = self._pip_cache.get(key)
        if s is None:
            s = tint_rgba(creatures.render(name, tier, frame), tuple(0.55 + 0.45 * c for c in self.tint))
            self._pip_cache[key] = s
        return s

    def _glints(self, img, t):
        rows, cols = np.nonzero(self.anim == 2)
        if len(rows) == 0:
            return
        rng = np.random.RandomState(int(t * 2) % 97)
        pick = rng.choice(len(rows), min(22, len(rows)), replace=False)
        for i in pick:
            x, y = cols[i] * T + rng.randint(4, 28), rows[i] * T + rng.randint(4, 28)
            if 2 < y + 3 < WORLD_H and x + 6 < img.shape[1]:
                img[y:y + 2, x:x + 6] = (255, 246, 210)
                img[y - 1:y + 3, x + 2:x + 4] = (255, 240, 200)


# ----------------------------------------------------------------------------- frames
def busy_pips(scene: Scene) -> List[Tuple[str, int, str, int, int]]:
    wx, wy = scene.well_px
    hp = scene.house_pos
    P = [
        ("kai_dnb", 2, "speak", wx - 60, wy + 40),
        ("noor.wav", 1, "emote0", wx + 48, wy + 44),
        ("sami.exe", 1, "idle1", wx + 4, wy + 66),
        ("zed_ttv", 3, "idle0", wx - 120, wy + 20),
        ("mira_9", 1, "walk0", wx + 150, wy - 30),
        ("luca_99", 2, "walk1", wx - 170, wy + 120),
        ("xXvtobiXx", 0, "hop", wx + 110, wy + 120),
        ("lowkeyjord", 1, "speak", wx + 330, wy + 60),
        ("tinytash", 1, "walk0", wx - 280, wy - 60),
        ("pixel_dude", 0, "emote1", wx + 24, wy - 60),
        ("quietnoodle", 2, "blink", wx - 60, wy - 110),
        ("bee", 1, "idle0", wx + 520, wy + 150),
        ("ash", 0, "walk1", wx + 560, wy + 175),
        ("hollow_pete", 1, "sleep", hp["mira_9"][0] + 52, hp["mira_9"][1] + 4),
    ]
    return [(n, t, f, int(x), int(y)) for (n, t, f, x, y) in P]


def dawn_pips(scene: Scene) -> List[Tuple[str, int, str, int, int]]:
    out = []
    for name in ("kai_dnb", "mira_9"):
        hx, hy = scene.house_pos[name]
        out.append((name, 1, "sleep", hx + 52, hy + 4))
    return out


def minimap(world: World, cam, size=(128, 68)) -> Image.Image:
    col = np.zeros((MAP_H, MAP_W, 3), np.uint8)
    col[...] = (116, 176, 79)
    col[world.grass_kind == 0] = (134, 188, 88)
    col[world.forest] = (62, 122, 58)
    col[world.hill] = (170, 180, 110)
    col[world.sand] = (227, 207, 152)
    col[world.water] = (46, 111, 176)
    col[world.path > 0] = (176, 138, 88)
    for name, hx, hy, st in world.builders:
        col[hy:hy + 2, hx:hx + 2] = creatures.genome(name)["body"]
    im = Image.fromarray(col).resize(size, Image.NEAREST)
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    sx, sy = size[0] / MAP_W, size[1] / MAP_H
    d.rectangle([cam[0] * sx, cam[1] * sy, (cam[0] + VIEW_W) * sx - 1, (cam[1] + VIEW_H) * sy - 1],
                outline=(255, 245, 220), width=1)
    return im


def _place_bubbles(ov, speakers):
    """Speech bubbles for the pips speaking now; pushed up when they would overlap an earlier one."""
    placed = []
    for head, msg in speakers:
        y = head[1] - 26
        scratch = Image.new("RGBA", ov.size, (0, 0, 0, 0))
        for _ in range(6):
            box = hud.bubble(scratch, (head[0], y), msg)   # dry run for the geometry only
            if not any(box[0] < b[2] and box[2] > b[0] and box[1] < b[3] and box[3] > b[1] for b in placed) and box[1] > WY0 + 4:
                break
            y -= 30
        placed.append(hud.bubble(ov, (head[0], y), msg))
    return placed


def render(busy: bool, path: str, t: float = 3.7) -> Tuple[Image.Image, Scene, World]:
    world = World(busy)
    scene = Scene(world, evening=busy, cam=CAM)
    pips = busy_pips(scene) if busy else dawn_pips(scene)
    region = scene.compose(t, pips)
    frame = Image.new("RGBA", (hud.W, hud.H), (26, 33, 29, 255))
    frame.paste(Image.fromarray(region), (WX0, WY0))
    if not busy:  # dawn mist: a thin pale veil drifting over the low ground and the water
        m = np.zeros((WORLD_H, hud.W, 4), np.uint8)
        gv, gu = np.mgrid[0:WORLD_H, 0:hud.W].astype(np.float32)
        n = fbm(gu / 8, gv / 8, 1 / 44.0, 2, 77)
        a = np.clip((n - 0.40) * 200, 0, 1) * (28 + 40 * gv / WORLD_H)
        m[..., :3] = (238, 242, 246)
        m[..., 3] = a.astype(np.uint8)
        mist = Image.new("RGBA", (hud.W, hud.H), (0, 0, 0, 0))
        mist.paste(Image.fromarray(m), (WX0, WY0))
        frame = Image.alpha_composite(frame, mist)
    ov = Image.new("RGBA", (hud.W, hud.H), (0, 0, 0, 0))
    C = hud.C
    heads = {n: (x + WX0, y + WY0 - creatures.box_size(tier) + 8) for (n, tier, fr, x, y) in pips}
    if busy:
        hud.header(ov, ["atleastonce · SETTLEMENT · v0.7", "concept render · names are examples"],
                   "14 SETTLED | 12 AWAKE", [("LIVE · 7 watching", C["live"]), ("NEXT EVENT 01:23", C["honey"])], 0.58)
        msgs = {"kai_dnb": "B! the well goes by the plaza", "lowkeyjord": "planting by the water, who's with me"}
        for n in msgs:
            hud.name_tag(ov, (heads[n][0], heads[n][1] + 2), n, creatures.genome(n)["body"])
        _place_bubbles(ov, [((heads[n][0], heads[n][1] - 24), msgs[n]) for n in msgs])
        for n in ("zed_ttv", "hollow_pete"):
            hud.name_tag(ov, heads[n], n + (" · asleep" if n == "hollow_pete" else ""), creatures.genome(n)["body"])
        hud.footer_panels(ov, [
            ("COLONY", [("14 settled · 6 more: the Mill opens", C["text"]), ("12 awake · 2 asleep · day 5 · evening", C["text"]),
                        ("last event: rain · by @sami.exe", C["muted"])]),
            ("KEEPER", [("keeper on duty · surveying East Field", C["text"]), ("12:40 left · then the well vote", C["text"]),
                        ("keepers are AI agents", C["muted"])]),
            ("CHAT LOG", [("@kai_dnb  B", C["text"]), ("@sami.exe  we need a bridge over it", C["text"]),
                          ("@noor.wav  planting by the water", C["text"])]),
        ], [(8, 400), (410, 770), (780, 1118)])
    else:
        hud.header(ov, ["atleastonce · SETTLEMENT · v0.7", "concept render · names are examples"],
                   "2 SETTLED | NOBODY AWAKE", [("LIVE · 1 watching", C["live"]), ("NEXT EVENT 02:41", C["honey"])], 0.12)
        for n in heads:
            hud.name_tag(ov, heads[n], n + " · asleep", creatures.genome(n)["body"])
        hud.footer_panels(ov, [
            ("COLONY", [("say anything in chat. a creature", C["honey"]), ("hatches with your name, out here.", C["honey"]),
                        ("2 settled · nobody awake · day 2 · dawn", C["muted"])]),
            ("KEEPER", [("no keeper on duty", C["text"]), ("scrolls kept for next time", C["text"]),
                        ("last raised: hut · by @kai_dnb", C["muted"])]),
            ("CHAT LOG", [("chat is quiet. say anything.", C["muted"])]),
        ], [(8, 400), (410, 770), (780, 1118)])
    hud.minimap_panel(ov, (1128, hud.FOOTER_Y + 6, 1272, hud.H - 6), minimap(world, CAM),
                      "3% explored" if busy else "2% explored")
    out = Image.alpha_composite(frame, ov).convert("RGB")
    out.save(path)
    return out, scene, world


def bench(scene: Scene, n_frames=150, n_pips=20) -> Dict[str, float]:
    names = creatures.EXAMPLES + ["tinytash", "pixel_dude", "quietnoodle", "bee", "ash", "hollow_pete", "sol", "ivy",
                                  "moss", "rook", "fenn", "wren"]
    rng = np.random.RandomState(3)
    pos = [(rng.randint(60, 1220), rng.randint(80, 500)) for _ in range(n_pips)]
    frames = creatures.FRAMES
    for i in range(n_pips):            # the compositor pre-renders a pip's sheet when it hatches
        for f in frames:
            scene._pip(names[i], i % 4, f)
    times = []
    for k in range(n_frames):
        t = k / 30.0
        pips = [(names[i], i % 4, frames[(k // 8 + i) % len(frames)], pos[i][0] + int(k * 0.7), pos[i][1]) for i in range(n_pips)]
        t0 = time.perf_counter()
        scene.compose(t, pips)
        times.append((time.perf_counter() - t0) * 1000)
    a = np.array(times)
    warm = a[30:]
    return {"first_frame_ms": float(a[0]), "avg_ms": float(warm.mean()), "p95_ms": float(np.percentile(warm, 95)),
            "max_ms": float(warm.max()), "cache_tiles": len(scene.tile_cache),
            "cache_mb": sum(len(v) for v in scene.tile_cache.values()) * T * T * 3 / 1e6}


if __name__ == "__main__":
    if "--ascii" in sys.argv:
        print(World(True).ascii())
        sys.exit(0)
    t0 = time.perf_counter()
    busy, scene, world = render(True, os.path.join(HERE, "mockup_busy.png"))
    busy.resize((320, 180), Image.LANCZOS).save(os.path.join(HERE, "thumb_320x180.png"))
    render(False, os.path.join(HERE, "mockup_dawn.png"))
    print("rendered mockups in %.1fs (includes building every atlas/sprite from scratch)" % (time.perf_counter() - t0))
    print("bench (1280x532 world, 20 pips, trees+cottages, wind/ripple/cloud phases):", bench(scene))
