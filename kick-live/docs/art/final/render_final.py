"""render_final.py - the SETTLEMENT reference renders, produced FROM the canonical art module (stream/world/art).

Pipeline (mirrors the intended 30 fps compositor):
  bake  (once per camera / season / hour, off the frame clock):
        per-pixel biome map -> 4 px cells -> tiles.Ground.paint(wind, ripple) (tile gather, edges, foam, relief) ->
        props / buildings blitted in painter's order -> tiles.grade(hour) + sun wash -> lantern / fire glows
        => bg[wind][ripple] (440x1280x3 uint8)
  frame (every tick): pick bg by the wind clock (0 1 2 3 2 1) and ripple clock -> cloud shadows -> settler frames from
        creatures.render() cache (y-sorted) -> chimney smoke -> show-on-speak pills (hud.place_pills).
  HUD:  hud.header / hud.panel / hud.caption around the world.

    $PYTHON docs/art/final/render_final.py
        writes final_mockup_busy.png (18:07), final_mockup_dawn.png (06:41), final_mockup_night.png (23:04, 0.55 floor),
        final_thumb_320x180.png, final_settler_sheet.png and prints the frame budget numbers.
Concept render only. Names are examples. Never touches the stream.
"""
from __future__ import annotations

import hashlib
import math
import os
import sys
import time
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, ROOT)
from stream.world.art import buildings, creatures, hud, props, tiles  # noqa: E402

W, H = 1280, 720
WY0, WW, WH = hud.LAYOUT["world_y0"], 1280, hud.LAYOUT["world_h"]
T = tiles.T
TX, TY = WW // T, int(math.ceil(WH / T))
SEED = 4471
SEA = 0.36
CAM = (60.0, 40.0)
CAT = tiles.CAT
C_WDEEP, C_WSHAL, C_SAND, C_GRASS, C_MEADOW, C_FLOOR, C_HILL, C_ROCK, C_P0, C_P1, C_P2, C_F0 = (
    CAT["water_deep"], CAT["water_shallow"], CAT["sand"], CAT["grass"], CAT["meadow"], CAT["forest_floor"], CAT["hill"],
    CAT["rock"], CAT["path0"], CAT["path1"], CAT["path2"], CAT["farm0"])

NAMES = ["atleastonce", "sami", "kai_dnb", "noor.wav", "luca_99", "mira_9", "zed_ttv", "xX_tobi_Xx", "lowkeyjord", "tinytash",
         "pixel_dude", "gg_nora", "hollowbyte", "june.mp4"]
SCENARIOS = {
    "busy": dict(hour=18.1, label="18:07 evening", season=1.0),
    "dawn": dict(hour=6.7, label="06:41 dawn", season=0.5),
    "night": dict(hour=23.07, label="23:04 night", season=1.0),
}


# ----------------------------------------------------------------------------- noise
def _hash2(i, j, seed):
    i = i.astype(np.int64)
    j = j.astype(np.int64)
    n = (i * 374761393 + j * 668265263 + int(seed) * 1013904223) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    n = (n ^ (n >> 16)) & 0xFFFFFFFF
    return n.astype(np.float32) / np.float32(4294967295.0)


def vnoise(u, v, freq, seed):
    x, y = u * freq, v * freq
    xi, yi = np.floor(x), np.floor(y)
    fx, fy = (x - xi).astype(np.float32), (y - yi).astype(np.float32)
    sx = fx * fx * fx * (fx * (fx * 6 - 15) + 10)
    sy = fy * fy * fy * (fy * (fy * 6 - 15) + 10)
    a, b = _hash2(xi, yi, seed), _hash2(xi + 1, yi, seed)
    c, d = _hash2(xi, yi + 1, seed), _hash2(xi + 1, yi + 1, seed)
    return (a * (1 - sx) + b * sx) * (1 - sy) + (c * (1 - sx) + d * sx) * sy


def fbm(u, v, freq, octaves, seed, gain=0.5):
    total, amp, norm = np.zeros_like(u, dtype=np.float32), 1.0, 0.0
    for o in range(octaves):
        total += amp * vnoise(u, v, freq, seed + o * 101)
        norm += amp
        amp *= gain
        freq *= 2.0
    return total / norm


def elevation(U, V):
    base = np.clip((fbm(U, V, 1 / 13.0, 3, SEED) - 0.5) * 1.9 + 0.5, 0, 1)
    gx = 1.0 - (U - CAM[0]) / TX
    gy = 1.0 - (V - CAM[1]) / TY
    g = 0.62 * gx + 0.38 * gy
    return np.clip(0.55 * base + 0.56 * g - 0.13, 0, 1).astype(np.float32)


def moisture(U, V):
    return fbm(U, V, 1 / 9.0, 3, SEED + 7000).astype(np.float32)


def box_blur(a, r, passes=2):
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


def hsh(*keys) -> float:
    h = hashlib.sha1(("|".join(str(k) for k in keys)).encode()).digest()
    return int.from_bytes(h[:4], "little") / 4294967295.0


# ----------------------------------------------------------------------------- blitting
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
    h, w = spr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(dst.shape[1], x + w), min(dst.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return
    a = spr[y0 - y:y1 - y, x0 - x:x1 - x, 3:4].astype(np.uint16)
    d = dst[y0:y1, x0:x1]
    d[...] = ((d.astype(np.uint16) * (256 - a)) >> 8).astype(np.uint8)


def blit_add(dst: np.ndarray, spr: np.ndarray, x: int, y: int) -> None:
    h, w = spr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(dst.shape[1], x + w), min(dst.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return
    s = spr[y0 - y:y1 - y, x0 - x:x1 - x]
    add = (s[..., :3].astype(np.uint16) * s[..., 3:4].astype(np.uint16)) // 255
    d = dst[y0:y1, x0:x1]
    d[...] = np.minimum(255, d.astype(np.uint16) + add).astype(np.uint8)


def put(dst, spr, gx, gy):
    """Blit a prop by its ground point."""
    ax, ay = props.anchor(spr)
    blit(dst, spr, int(gx) - ax, int(gy) - ay)


# ----------------------------------------------------------------------------- world model
class World:
    def __init__(self, scenario: str):
        self.scenario = scenario
        sc = SCENARIOS[scenario]
        self.hour = sc["hour"]
        self.season = sc["season"]
        self.sun = tiles.sun_vector(self.hour)
        self.night = scenario == "night"
        self.evening = scenario == "busy"
        self.lit = self.night or self.evening
        py, px = np.mgrid[0:WH, 0:WW].astype(np.float32)
        self.PX, self.PY = px, py
        self.U = CAM[0] + px / T
        self.V = CAM[1] + py / T
        self.E = elevation(self.U, self.V)
        self.M = moisture(self.U, self.V)
        self._sea()
        self._river()
        self.site = self._pick_site()
        self._categories()
        self._village()
        self._ground()

    def _sea(self):
        water = self.E < SEA
        small = water[::4, ::4]
        sea = np.zeros_like(small)
        sea[:, -1] = small[:, -1]
        sea[-1, :] = small[-1, :]
        for _ in range(small.shape[0] + small.shape[1]):
            g = sea.copy()
            g[1:, :] |= sea[:-1, :]
            g[:-1, :] |= sea[1:, :]
            g[:, 1:] |= sea[:, :-1]
            g[:, :-1] |= sea[:, 1:]
            g &= small
            if (g == sea).all():
                break
            sea = g
        big = np.repeat(np.repeat(sea, 4, axis=0), 4, axis=1)[:WH, :WW]
        big = Image.fromarray((big * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9))
        self.sea = (np.asarray(big) > 0) & water
        self.pond = water & ~self.sea

    def _pick_site(self) -> Tuple[float, float]:
        Et = self.E[T // 2::T, T // 2::T]
        water = (Et < SEA) | self.river[T // 2::T, T // 2::T]
        wy, wx = np.nonzero(water)
        best, best_s = None, 1e9
        for ty in range(4, 9):
            for tx in range(12, 22):
                e = Et[ty, tx]
                if not (0.40 <= e <= 0.64):
                    continue
                win = Et[ty - 2:ty + 3, tx - 2:tx + 3]
                slope = float(win.max() - win.min())
                if slope > 0.10 or not len(wx):
                    continue
                dd = np.hypot(wx - tx, wy - ty)
                dw = float(dd.min())
                if not (4.0 <= dw <= 9):
                    continue
                if (dd < 14).sum() < 6:
                    continue
                sc = slope * 5 + abs(dw - 6.5) * 0.4 + abs(tx - 17) * 0.08 + abs(ty - 6.2) * 0.12
                if sc < best_s:
                    best, best_s = (tx + 0.5, ty + 0.5), sc
        return best or (16.5, 6.5)

    def _river(self):
        Eb = box_blur(self.E, 28)
        gy, gx = np.gradient(Eb)
        band = Eb[0:T, T * 12:T * 26]
        iy, ix = np.unravel_index(np.argmax(band), band.shape)
        x, y = float(ix + T * 12), float(iy)
        sy_, sx_ = np.nonzero(self.sea[::8, ::8])
        pts = [(x, y)]
        vx, vy = 0.0, 1.0
        for i in range(3000):
            xi, yi = int(np.clip(x, 0, WW - 1)), int(np.clip(y, 0, WH - 1))
            if self.sea[yi, xi]:
                break
            ddx, ddy = -gx[yi, xi], -gy[yi, xi]
            n = math.hypot(ddx, ddy) + 1e-6
            ddx, ddy = ddx / n, ddy / n
            if self.pond[yi, xi]:
                ddx, ddy = 0.0, 0.0
            if len(sx_):
                dd = np.hypot(sx_ * 8 - x, sy_ * 8 - y)
                k = int(np.argmin(dd))
                px_, py_ = sx_[k] * 8 - x, sy_[k] * 8 - y
                n2 = math.hypot(px_, py_) + 1e-6
                pull = min(1.0, 260.0 / n2) * 0.6 + 0.45
                ddx = ddx + pull * px_ / n2
                ddy = ddy + pull * py_ / n2
            wig = math.sin(i * 0.035) * 0.45
            vx = 0.88 * vx + 0.12 * (ddx - wig * ddy)
            vy = 0.88 * vy + 0.12 * (ddy + wig * ddx)
            n = math.hypot(vx, vy) + 1e-6
            x += 2.0 * vx / n
            y += 2.0 * vy / n
            if not (0 <= x < WW and 0 <= y < WH):
                break
            pts.append((x, y))
        mask = Image.new("L", (WW, WH), 0)
        d = ImageDraw.Draw(mask)
        n = len(pts)
        for i in range(n - 1):
            d.line([pts[i], pts[i + 1]], fill=255, width=int(7 + 9 * i / max(1, n - 1)))
        self.river = np.asarray(mask) > 128
        bank = np.asarray(mask.filter(ImageFilter.MaxFilter(9))) > 128
        self.river_bank = bank & ~self.river

    def _categories(self):
        E, M = self.E.copy(), self.M
        zone = np.asarray(Image.fromarray((self.pond * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(15))) > 0
        E[zone] += 0.045
        self.E = E
        su, sv = self.site
        dsite = np.hypot(self.PX / T - su, self.PY / T - sv)
        cat = np.full((WH, WW), C_GRASS, np.int8)
        patch = fbm(self.U, self.V, 1 / 4.5, 2, SEED + 31)
        cat[(M < 0.38) & (patch > 0.66)] = C_MEADOW
        forest = (M > 0.55) & (E > SEA + 0.06) & (E < 0.72) & (dsite > 6.0)
        cat[forest] = C_FLOOR
        cat[E > 0.68] = C_HILL
        cat[E > 0.80] = C_ROCK
        cat[E < SEA + 0.022] = C_SAND
        cat[E < SEA] = C_WSHAL
        cat[E < SEA - 0.07] = C_WDEEP
        cat[self.river_bank & (E >= SEA)] = C_SAND
        cat[self.river] = C_WSHAL
        self.cat = cat
        self.water = (cat == C_WSHAL) | (cat == C_WDEEP)

    def _land_tile(self, tx: int, ty: int, w: int = 1) -> bool:
        for k in range(w):
            x, y = int(tx + k), int(ty)
            if not (0 <= x < TX and 0 <= y < TY - 1):
                return False
            c = self.cat[y * T:(y + 1) * T, x * T:(x + 1) * T]
            if np.any((c <= C_SAND) | (c == C_HILL) | (c == C_ROCK)):
                return False
        return True

    def _village(self):
        su, sv = self.site
        cx, cy = su * T, sv * T
        self.plaza_px = (cx, cy)
        self.huts: List[Dict] = []
        self.farms: List[Tuple[int, int, int]] = []
        self.paths: List[List[Tuple[float, float]]] = []
        self.fences: List[Tuple[int, int, int]] = []
        self.gardens: List[Tuple[int, int, str]] = []
        self.banners: List[Tuple[int, int, str]] = []
        self.lanterns: List[Tuple[int, int]] = []
        self.marks: List[Tuple[str, int, int, object]] = []
        occ = set()
        grown = self.scenario != "dawn"
        owners = NAMES[:9] if grown else ["kai_dnb", "mira_9"]
        n = len(owners)
        for i, name in enumerate(owners):
            tier = settler_tier(name)
            w = buildings.footprint("hut", tier)[0]
            placed = False
            radii = (3.4, 4.2, 5.0, 5.8, 6.6) if i % 2 == 0 else (5.0, 4.2, 5.8, 3.4, 6.6)
            for r in radii:
                ang = 2 * math.pi * (i + 0.5) / n + (hsh("ang", name) - 0.5) * 0.5 + math.pi * 0.15
                tx = int(round(su + r * math.cos(ang) * 1.45 - w / 2.0))
                ty = int(round(sv + r * math.sin(ang) * 0.80))
                cells = {(tx + k + dx, ty + dy) for k in range(w) for dx in (-2, -1, 0, 1, 2) for dy in (-1, 0, 1)}
                if self._land_tile(tx, ty, w) and not (cells & occ) and 1 <= ty <= TY - 3 and 1 <= tx <= TX - 3:
                    occ |= {(tx + k, ty) for k in range(w)} | {(tx + k, ty - 1) for k in range(w)}
                    self.huts.append({"name": name, "tx": tx, "ty": ty, "w": w, "tier": tier})
                    placed = True
                    break
            if not placed:
                ang = 2 * math.pi * (i + 0.5) / n + math.pi * 0.15
                ix, iy = su + 4.6 * math.cos(ang) * 1.45, sv + 4.6 * math.sin(ang) * 0.80
                cands = sorted(((math.hypot(tx - ix, ty - iy), tx, ty) for ty in range(1, TY - 3) for tx in range(1, TX - 3)
                                if math.hypot((tx - su) / 1.45, ty - sv) >= 2.6))
                for _, tx, ty in cands:
                    cells = {(tx + k + dx, ty + dy) for k in range(w) for dx in (-2, -1, 0, 1, 2) for dy in (-1, 0, 1)}
                    if self._land_tile(tx, ty, w) and not (cells & occ):
                        occ |= {(tx + k, ty) for k in range(w)} | {(tx + k, ty - 1) for k in range(w)}
                        self.huts.append({"name": name, "tx": tx, "ty": ty, "w": w, "tier": tier})
                        break
        self.occ = occ
        stages = [3, 2, 1] if grown else [0]
        k = 0
        for r in (6.0, 7.0, 8.0, 5.2):
            for ang_deg in (150, 210, 250, 110, 300, 30, 340, 190, 80):
                if k >= len(stages):
                    break
                a = math.radians(ang_deg)
                tx = int(round(su + r * math.cos(a) * 1.4))
                ty = int(round(sv + r * math.sin(a) * 0.8))
                if not (1 <= tx <= TX - 4 and 1 <= ty <= TY - 4):
                    continue
                cells = {(tx + dx, ty + dy) for dx in (-1, 0, 1, 2) for dy in (-1, 0, 1, 2)}
                if self._land_tile(tx, ty, 2) and self._land_tile(tx, ty + 1, 2) and not (cells & occ):
                    occ |= {(tx + dx, ty + dy) for dx in (0, 1) for dy in (0, 1)}
                    self.farms.append((tx, ty, stages[k]))
                    k += 1
        for hd in self.huts:
            door = ((hd["tx"] + hd["w"] / 2.0) * T, (hd["ty"] + 1) * T + 3)
            self.paths.append(self._bend((cx, cy), door))
        shore = self._nearest_shore()
        self.shore_pt = shore
        if shore:
            self.paths.append(self._bend((cx, cy), shore))
        for (tx, ty, st) in self.farms:
            self.paths.append(self._bend((cx, cy), ((tx + 1) * T, (ty + 2) * T + 2)))
        for i, hd in enumerate(self.huts):
            if i % 3 == 0:
                self.fences.append(((hd["tx"] - 1) * T + 6, (hd["ty"] + 1) * T + 14, 2))
            if i % 3 == 1:
                self.gardens.append(((hd["tx"] + hd["w"]) * T + 4, hd["ty"] * T + 10, hd["name"]))
        for j, ang_deg in enumerate((205, 335, 80) if grown else (335,)):
            a = math.radians(ang_deg)
            self.banners.append((int(cx + 62 * math.cos(a)), int(cy + 40 * math.sin(a)), owners[j % len(owners)]))
        if grown and shore:
            p = self.paths[len(self.huts)]
            for f in (0.35, 0.72):
                q = p[int(f * (len(p) - 1))]
                self.lanterns.append((int(q[0]) + 10, int(q[1]) - 2))
            for hd in self.huts[::3]:
                self.lanterns.append(((hd["tx"] + hd["w"]) * T + 8, (hd["ty"] + 1) * T + 6))
        # landmarks: the beacon on the plaza edge, a campfire by the plaza, a cairn of milestones, waystones at path forks
        self.marks.append(("beacon", int(cx - 64), int(cy - 6), NAMES[0]))
        self.marks.append(("campfire", int(cx - 58), int(cy + 66), None))
        self.marks.append(("cairn", int(cx + 96), int(cy + 58), 4 if grown else 1))
        for j, p in enumerate(self.paths[:6:2]):
            q = p[int(0.62 * (len(p) - 1))]
            self.marks.append(("waystone", int(q[0]) + 14, int(q[1]) + 6, creatures.palette(owners[j % len(owners)])["main"]))
        self.plaza_r = 1.25 if grown else 0.8
        tx0, ty0 = int(su), int(sv)
        for ty in range(ty0 - 3, ty0 + 4):
            for tx in range(tx0 - 3, tx0 + 4):
                if 0 <= tx < TX and 0 <= ty < TY and math.hypot((tx + 0.5 - su) / 1.25, ty + 0.5 - sv) <= self.plaza_r and self._land_tile(tx, ty):
                    self.cat[ty * T:(ty + 1) * T, tx * T:(tx + 1) * T] = C_P2
        pm = Image.new("L", (WW, WH), 0)
        d = ImageDraw.Draw(pm)
        for p in self.paths:
            d.line(p, fill=255, width=9)
        pm = np.asarray(pm.filter(ImageFilter.GaussianBlur(2.5)), np.float32) / 255.0
        land = (self.cat >= C_GRASS) & (self.cat <= C_FLOOR)
        self.cat[(pm > 0.18) & land] = C_P0
        self.cat[(pm > 0.62) & ((self.cat == C_P0) | land)] = C_P1
        for (tx, ty, st) in self.farms:
            self.cat[ty * T:(ty + 2) * T, tx * T:(tx + 2) * T] = C_F0 + st
        self.water = (self.cat == C_WSHAL) | (self.cat == C_WDEEP)

    def _bend(self, a, b) -> List[Tuple[float, float]]:
        pts = []
        n = 14
        mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) + 1e-6
        k = (hsh("bend", a, b) - 0.5) * 0.35 * L
        cx, cy = mx - dy / L * k, my + dx / L * k
        for i in range(n + 1):
            t = i / n
            pts.append(((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * cx + t * t * b[0], (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * cy + t * t * b[1]))
        return pts

    def _nearest_shore(self):
        cx, cy = self.plaza_px
        sand = np.argwhere(self.cat[::4, ::4] == C_SAND) * 4
        if not len(sand):
            return None
        dd = np.hypot(sand[:, 1] - cx, sand[:, 0] - cy)
        pref = dd + np.where(sand[:, 1] < cx, 200, 0)
        k = int(np.argmin(pref))
        y, x = sand[k]
        return (float(x), float(y))

    def _ground(self):
        """The canonical ground painter: the per-pixel biome map sampled to 4 px cells + a relief / mottle shade."""
        mott = fbm(self.U, self.V, 1 / 3.5, 2, SEED + 300) - 0.5
        shade = 1.0 + 0.09 * mott
        Eb = box_blur(self.E, 5)
        gy, gx = np.gradient(Eb)
        relief = np.clip(1.0 + 34.0 * (self.sun[0] * gx + self.sun[1] * gy) * np.clip((self.E - 0.58) / 0.12, 0, 1), 0.74, 1.26)
        shade = (shade * relief).astype(np.float32)
        cells = self.cat[2::4, 2::4]
        self.ground = tiles.Ground(cells, self.season, origin=(int(CAM[0]), int(CAM[1])), shade=shade[2::4, 2::4], seed=SEED)
        self.foam_noise = fbm(self.U, self.V, 3.0, 2, SEED + 900)

    def objects(self):
        """Static object list (trees, huts, dressing, landmarks) sorted by ground y for painter's order."""
        objs = []
        su, sv = self.site
        for ty in range(TY):
            for tx in range(TX):
                cc = self.cat[min(WH - 1, ty * T + T // 2), tx * T + T // 2]
                r = hsh("tree", tx, ty)
                if (tx, ty) in self.occ:
                    continue
                if cc == C_FLOOR and r < 0.88:
                    m = self.M[min(WH - 1, ty * T + T // 2), tx * T + T // 2]
                    age = 3 if m > 0.64 else (2 if m > 0.58 else 1)
                    if hsh("big", tx, ty) < 0.35:
                        age = min(3, age + 1)
                elif cc in (C_GRASS, C_MEADOW) and r < 0.035 and math.hypot(tx - su, ty - sv) > 5.5:
                    age = 2 if hsh("lone", tx, ty) < 0.5 else 1
                elif cc == C_HILL and r < 0.06:
                    age = 1
                elif cc == C_HILL and 0.06 <= r < 0.12:
                    x = tx * T + T // 2 + int((hsh("sx", tx, ty) - 0.5) * 16)
                    y = ty * T + T // 2 + int((hsh("sy", tx, ty) - 0.5) * 16)
                    objs.append(("stone", y, (x, y, int(hsh("sv", tx, ty) * 3))))
                    continue
                elif cc == C_MEADOW and r < 0.10 and math.hypot(tx - su, ty - sv) > 3.0:
                    x = tx * T + T // 2 + int((hsh("bx", tx, ty) - 0.5) * 16)
                    y = ty * T + T // 2 + int((hsh("by", tx, ty) - 0.5) * 16)
                    if not self.water[min(WH - 1, y), min(WW - 1, x)]:
                        objs.append(("bush", y, (x, y, int(hsh("bv", tx, ty) * 4))))
                    continue
                elif cc == C_GRASS and 0.035 <= r < 0.05 and math.hypot(tx - su, ty - sv) > 4.0:
                    x = tx * T + T // 2
                    y = ty * T + T // 2
                    objs.append(("sapling", y, (x, y)))
                    continue
                else:
                    continue
                x = tx * T + T // 2 + int((hsh("jx", tx, ty) - 0.5) * 14)
                y = ty * T + T // 2 + int((hsh("jy", tx, ty) - 0.5) * 14)
                if self.water[min(WH - 1, y), min(WW - 1, x)]:
                    continue
                objs.append(("tree", y, (x, y, age, int(hsh("tv", tx, ty) * 3))))
        for hd in self.huts:
            objs.append(("hut", (hd["ty"] + 1) * T, hd))
        for (x, y, n) in self.fences:
            objs.append(("fence", y + 10, (x, y, n)))
        for (x, y, name) in self.gardens:
            objs.append(("garden", y + 18, (x, y, name)))
        for (x, y, name) in self.banners:
            objs.append(("banner", y, (x, y, name)))
        for (x, y) in self.lanterns:
            objs.append(("lantern", y, (x, y)))
        for (kind, x, y, arg) in self.marks:
            objs.append((kind, y, (x, y, arg)))
        objs.append(("well", self.plaza_px[1] + 8, self.plaza_px))
        objs.sort(key=lambda o: o[1])
        return objs


def settler_tier(name: str) -> int:
    r = hsh("tier", name)
    return 0 if r < 0.15 else (1 if r < 0.42 else (2 if r < 0.85 else 3))


# ----------------------------------------------------------------------------- bake
class Baker:
    def __init__(self, world: World):
        self.w = world
        self.objs = world.objects()
        self.cache: Dict[Tuple[int, int], np.ndarray] = {}
        self.glow = props.glow(46, (255, 186, 96), 0.42 if not world.night else 0.55)
        self.window_glow = props.glow(22, (255, 214, 130), 0.30 if not world.night else 0.42)
        self.fire_glow = props.glow(70, (255, 170, 80), 0.5 if not world.night else 0.7)
        self.beacon_glow = props.glow(110, (255, 180, 90), 0.35 if not world.night else 0.55)

    def bake(self, wind: int, ripple: int) -> np.ndarray:
        key = (wind, ripple)
        if key in self.cache:
            return self.cache[key]
        w = self.w
        bg = w.ground.paint(wind, ripple).copy()
        sun, lit, season = w.sun, w.lit, w.season
        fire_phase = ripple
        for kind, _, data in self.objs:
            if kind == "tree":
                x, y, age, var = data
                put(bg, props.tree(age, var, wind, season, sun), x, y)
            elif kind == "sapling":
                put(bg, props.tree(0, 0, wind, season, sun), data[0], data[1])
            elif kind == "bush":
                x, y, var = data
                put(bg, props.bush(var, wind, season, sun), x, y)
            elif kind == "stone":
                x, y, var = data
                put(bg, props.stone(var, sun), x, y)
            elif kind == "hut":
                spr, (dx, dy) = buildings.render("hut", data["tier"], data["name"], None, lit, sun)
                blit(bg, spr, data["tx"] * T - dx, data["ty"] * T - dy)
            elif kind == "fence":
                x, y, n = data
                spr, (dx, dy) = buildings.render("fence_h", n)
                blit(bg, spr, x - dx, y - dy)
            elif kind == "garden":
                x, y, name = data
                spr, (dx, dy) = buildings.render("garden", 1, name)
                blit(bg, spr, x - dx, y - dy)
            elif kind == "banner":
                x, y, name = data
                spr, (dx, dy) = buildings.render("banner", 1, name, wind % 3)
                blit(bg, spr, x - dx, y - dy)
            elif kind == "lantern":
                x, y = data
                spr, (dx, dy) = buildings.render("lantern", 1, lit=lit)
                blit(bg, spr, x - dx, y - dy)
            elif kind == "well":
                x, y = data
                spr, (dx, dy) = buildings.render("well", 1, NAMES[0], None, False, sun)
                blit(bg, spr, int(x) - dx, int(y) - dy)
            elif kind == "beacon":
                x, y, owner = data
                put(bg, props.beacon(fire_phase, lit, creatures.palette(owner)["main"], sun), x, y)
            elif kind == "campfire":
                x, y, _ = data
                put(bg, props.campfire(fire_phase, lit, sun), x, y)
            elif kind == "cairn":
                x, y, n = data
                put(bg, props.cairn(n, sun), x, y)
            elif kind == "waystone":
                x, y, colour = data
                put(bg, props.waystone(colour, 0, sun), x, y)
        bg = self.tint(bg)
        if lit:
            for kind, _, data in self.objs:
                if kind == "lantern":
                    blit_add(bg, self.glow, data[0] - 46, data[1] - 12 - 46)
                elif kind == "hut":
                    cx = int((data["tx"] + data["w"] / 2.0) * T)
                    blit_add(bg, self.window_glow, cx - 22, (data["ty"] + 1) * T - 4 - 22)
                elif kind == "campfire":
                    blit_add(bg, self.fire_glow, data[0] - 70, data[1] - 8 - 70)
                elif kind == "beacon":
                    blit_add(bg, self.beacon_glow, data[0] - 110, data[1] - 34 - 110)
        self.cache[key] = bg
        return bg

    def tint(self, bg: np.ndarray) -> np.ndarray:
        """tiles.grade (the canonical hour grade) plus the scene-level Studio A wash: a warm gradient toward the sun,
        a cool violet in the far corner; dawn adds low mist over low ground."""
        w = self.w
        out = tiles.grade(bg, w.hour, w.ground.water).astype(np.float32)
        sx, sy = w.sun
        along = ((w.PX / WW - 0.5) * sx + (w.PY / WH - 0.5) * sy)[..., None]
        if w.evening:
            out = out * (1.0 + 0.10 * along) + np.array((255, 200, 120), np.float32) * np.clip(along, 0, 1) * 0.12
            out = out * (1.0 - 0.08 * np.clip(-along, 0, 1)) + np.array((50, 36, 96), np.float32) * np.clip(-along, 0, 1) * 0.10
        elif w.night:
            out = out * (1.0 - 0.05 * np.clip(-along, 0, 1)) + np.array((30, 30, 70), np.float32) * np.clip(-along, 0, 1) * 0.05
        else:
            mist = np.clip((0.50 - w.E) / 0.16, 0, 1) * (0.55 + 0.45 * w.foam_noise)
            mist = box_blur(mist, 14)[..., None] * 0.42
            out = out * (1 - mist) + np.array((236, 232, 244), np.float32) * mist
            out = out * (1.0 + 0.06 * along) + np.array((255, 214, 170), np.float32) * np.clip(along, 0, 1) * 0.18
        return np.clip(out, 0, 255).astype(np.uint8)


# ----------------------------------------------------------------------------- settlers on the map
def place_settlers(world: World) -> List[Dict]:
    """Deterministic example placement: name, frame, tier, facing, (x, y) ground point, speech."""
    cx, cy = world.plaza_px
    huts = {h["name"]: h for h in world.huts}
    sc = world.scenario

    def door(name, dx=0, dy=14):
        h = huts.get(name)
        if h is None:
            return (cx + dx * 3, cy + 50 + dy)
        return ((h["tx"] + h["w"] / 2.0) * T + dx, (h["ty"] + 1) * T + dy)

    def farm(i, dx=0, dy=0):
        if not world.farms:
            return (cx - 120 + i * 40 + dx, cy + 70 + dy)
        tx, ty, st = world.farms[i % len(world.farms)]
        return ((tx + 1) * T + dx, (ty + 2) * T + 8 + dy)

    def on_path(i, f, dx=0, dy=0):
        p = world.paths[i % len(world.paths)]
        q = p[int(f * (len(p) - 1))]
        return (q[0] + dx, q[1] + dy)

    fire = next(m for m in world.marks if m[0] == "campfire")
    fx, fy = fire[1], fire[2]
    if sc == "dawn":
        L = [
            {"name": "kai_dnb", "frame": "sleep", "pos": door("kai_dnb", 22, 6), "speech": None},
            {"name": "mira_9", "frame": "sleep", "pos": door("mira_9", -24, 8), "speech": None},
        ]
    elif sc == "night":
        L = [
            {"name": "atleastonce", "frame": "sit", "pos": (fx - 26, fy + 8), "speech": "last one up. night, all"},
            {"name": "sami", "frame": "speak0", "pos": (fx + 30, fy + 6), "speech": "the beacon stays lit"},
            {"name": "kai_dnb", "frame": "sleep", "pos": door("kai_dnb", 22, 6), "speech": None},
            {"name": "mira_9", "frame": "sleep", "pos": door("mira_9", 20, 6), "speech": None},
            {"name": "noor.wav", "frame": "sleep", "pos": door("noor.wav", -22, 8), "speech": None},
            {"name": "luca_99", "frame": "sleep", "pos": door("luca_99", 18, 8), "speech": None},
            {"name": "zed_ttv", "frame": "sleep", "pos": door("zed_ttv", -20, 6), "speech": None},
            {"name": "xX_tobi_Xx", "frame": "sleep", "pos": door("xX_tobi_Xx", 22, 8), "speech": None},
            {"name": "lowkeyjord", "frame": "sleep", "pos": door("lowkeyjord", -22, 6), "speech": None},
            {"name": "tinytash", "frame": "walk1", "pos": on_path(len(huts), 0.5, 0, 10), "speech": None},
            {"name": "gg_nora", "frame": "look_l", "pos": (fx + 2, fy - 22), "speech": None},
            {"name": "pixel_dude", "frame": "sleep", "pos": (cx + 120, cy + 90), "speech": None},
        ]
    else:
        L = [
            {"name": "kai_dnb", "frame": "speak0", "pos": (cx - 70, cy + 20), "speech": "B! the well goes by the plaza"},
            {"name": "sami", "frame": "speak1", "pos": on_path(len(huts), 0.55, 0, 12), "speech": "we need a bridge over it"},
            {"name": "noor.wav", "frame": "carry_berry", "pos": farm(0, -8, 4), "speech": "planting by the water, who's with me"},
            {"name": "luca_99", "frame": "hop1", "pos": on_path(3, 0.5, 6, 0), "speech": None},
            {"name": "mira_9", "frame": "sleep", "pos": door("mira_9", 20, 6), "speech": None},
            {"name": "zed_ttv", "frame": "walk0", "pos": on_path(0, 0.45, -4, 6), "speech": None},
            {"name": "xX_tobi_Xx", "frame": "walk2", "pos": on_path(len(huts), 0.25, 0, -10), "speech": None},
            {"name": "lowkeyjord", "frame": "sit", "pos": door("lowkeyjord", -22, 8), "speech": None},
            {"name": "tinytash", "frame": "joy", "pos": (cx + 66, cy + 34), "speech": None},
            {"name": "atleastonce", "frame": "wave0", "pos": (cx - 6, cy + 58), "speech": None},
            {"name": "pixel_dude", "frame": "carry_stone", "pos": on_path(len(huts) + 1, 0.7, 12, 0), "speech": None},
            {"name": "gg_nora", "frame": "carry_tool", "pos": farm(1, 30, -2), "speech": None},
            {"name": "hollowbyte", "frame": "look_r", "pos": farm(2, 40, -6), "speech": None},
            {"name": "june.mp4", "frame": "point", "pos": (cx + 30, cy - 30), "speech": None},
        ]
    for c in L:
        x, y = c["pos"]
        x = float(np.clip(x, 30, WW - 30))
        y = float(np.clip(y, 40, WH - 12))
        for _ in range(12):
            if not world.water[int(y), int(x)]:
                break
            x -= 8
        c["pos"] = (x, y)
        c["tier"] = settler_tier(c["name"])
        c["facing"] = 1
    speakers = [c for c in L if c.get("speech")]
    for c in L:
        if c["frame"].startswith("look") and speakers:      # idle settlers look toward the nearest speaker, no flip needed
            sp = min(speakers, key=lambda s_: math.hypot(s_["pos"][0] - c["pos"][0], s_["pos"][1] - c["pos"][1]))
            c["frame"] = "look_r" if sp["pos"][0] >= c["pos"][0] else "look_l"
        elif c["frame"].startswith("walk"):
            c["facing"] = 1 if c["pos"][0] < cx else -1        # walking toward the plaza
        elif c["frame"] == "point":
            c["facing"] = 1 if c["pos"][0] < cx else -1
    return L


# ----------------------------------------------------------------------------- frame compose
class Frame:
    def __init__(self, world: World, baker: Baker, actors: List[Dict]):
        self.w, self.b, self.actors = world, baker, actors
        self.cloud = props.cloud_shadow(strength=0.17 if not world.night else 0.08)
        self.smoke = [buildings.render("smoke", 1, seed=p)[0] for p in range(3)]
        self.sun = world.sun
        self.pills = {}
        for a in actors:
            if a.get("speech"):
                pal = creatures.palette(a["name"])
                self.pills[a["name"]] = np.asarray(hud.pill("@" + a["name"], icon=creatures.head_icon(a["name"], hud.LAYOUT["pill_icon"]), colour=pal["main"]))
        for a in actors:   # pre-warm the settler cache (what hatch does)
            creatures.settler_sheet(a["name"], a["tier"], 1, self.sun)

    def compose(self, t: float) -> np.ndarray:
        wind = tiles.WIND_PLAY[int(t * 3.6) % 6]
        ripple = int(t * 3.2) % 4
        bg = self.b.bake(wind, ripple).copy()
        for k, (x0, y0) in enumerate(((60, 20), (620, 150), (980, 40))):
            blit_shade(bg, self.cloud, int(x0 + (t * 9.0 + k * 40) % (WW + 400)) - 340, y0)
        order = sorted(self.actors, key=lambda a: a["pos"][1])
        for a in order:
            spr = creatures.render(a["name"], a["tier"], a["frame"], 1, a["facing"], self.sun)
            ax, ay = creatures.anchor(a["tier"])
            blit(bg, spr, int(a["pos"][0]) - ax, int(a["pos"][1]) - ay)
        wanted = []
        for a in order:
            if a["name"] in self.pills:
                top = int(a["pos"][1] - creatures.height(a["tier"]) * (1.45 if a["frame"] == "hop1" else (0.75 if a["frame"] == "sit" else 1.22)) - hud.LAYOUT["pill_gap_above_head"])
                wanted.append((self.pills[a["name"]], int(a["pos"][0]), top))
        for (p, _, _), (px, py) in zip(wanted, hud.place_pills(wanted, WW)):
            blit(bg, p, px, py)
        ph = int(t * 2.0) % 3
        for kind, _, hd in self.b.objs:
            if kind == "hut" and hd["tier"] >= 2 and hsh("smoke", hd["name"]) < 0.6 and self.w.lit:
                blit(bg, self.smoke[ph], (hd["tx"] + hd["w"]) * T - 12, hd["ty"] * T - 10 - 18)
        return bg


# ----------------------------------------------------------------------------- HUD
def minimap_rgb(world: World) -> np.ndarray:
    v, u = np.mgrid[-50:64, -40:80].astype(np.float32)
    U = CAM[0] + u + 0.5
    V = CAM[1] + v + 0.5
    E = elevation(U, V)
    M = moisture(U, V)
    out = np.zeros(E.shape + (3,), np.uint8)
    out[:] = (104, 164, 78)
    out[M > 0.56] = (58, 122, 66)
    out[E > 0.70] = (156, 166, 100)
    out[E > 0.80] = (146, 142, 130)
    out[E < SEA + 0.03] = (234, 214, 160)
    out[E < SEA] = (92, 178, 206)
    out[E < SEA - 0.07] = (46, 112, 166)
    return out


def hud_frame(world: World, frame_rgb: np.ndarray, scenario: str) -> Image.Image:
    img = Image.new("RGB", (W, H), hud.COLOURS["header_bg"])
    img.paste(Image.fromarray(frame_rgb), (0, WY0))
    C = hud.COLOURS
    L = hud.LAYOUT
    y0, y1 = L["band_y0"] + 6, L["band_y0"] + L["band_h"] - 6
    g = L["gap"]
    pw = (W - 4 * g) // 3
    mm = hud.minimap(minimap_rgb(world), (40, 50, 40 + TX, 50 + TY), (126, 96))
    name_col = lambda n: creatures.palette(n)["main"]  # noqa: E731
    label = SCENARIOS[scenario]["label"]
    left = [("atleastonce", C["muted"]), ("SETTLEMENT", C["cream"])]
    if scenario == "busy":
        hud.header(img, left, "14 SETTLED · 12 AWAKE", [("LIVE · 7 watching", C["cream"])], [("NEXT EVENT 01:23", C["gold"])], progress=0.54)
        hud.panel(img, (g, y0, g + pw, y1), "COLONY", [
            [("14 settled · ", C["cream"]), ("12 awake", C["ok"]), (" · 2 asleep", C["muted"])],
            [("day 5 · evening", C["muted"])],
            [("3 farms · 9 huts", C["muted"])],
            [("rain · by ", C["muted"]), ("@sami", name_col("sami"))]], right=mm)
        hud.panel(img, (2 * g + pw, y0, 2 * g + 2 * pw, y1), "KEEPER · NEXT EVENT", [
            [("keeper on duty · surveying east", C["cream"])],
            [("where does the well go?", C["gold"])],
            [("A river ", C["cream"]), ("4", C["muted"]), ("   B plaza ", C["cream"]), ("7", C["ok"]), ("   C hill ", C["cream"]), ("1", C["muted"])],
            [("say A, B or C in chat · 01:23 left", C["muted"])]])
        hud.panel(img, (3 * g + 2 * pw, y0, W - g, y1), "CHAT", [
            [("@kai_dnb ", name_col("kai_dnb")), ("B", C["cream"])],
            [("@sami ", name_col("sami")), ("we need a bridge", C["cream"])],
            [("@noor.wav ", name_col("noor.wav")), ("planting by the water", C["cream"])],
            [("@luca_99 ", name_col("luca_99")), ("hop hop hop", C["cream"])]])
    elif scenario == "night":
        hud.header(img, left, "14 SETTLED · 3 AWAKE", [("LIVE · 3 watching", C["cream"])], [("NEXT EVENT 04:10", C["gold"])], progress=0.2)
        hud.panel(img, (g, y0, g + pw, y1), "COLONY", [
            [("14 settled · ", C["cream"]), ("3 awake", C["ok"]), (" · 11 asleep", C["muted"])],
            [("day 5 · night", C["muted"])],
            [("beacon lit · cairn 4", C["muted"])],
            [("quiet since 22:40", C["muted"])]], right=mm)
        hud.panel(img, (2 * g + pw, y0, 2 * g + 2 * pw, y1), "KEEPER", [
            [("keeper on duty · night watch", C["cream"])],
            [("the fire is kept while anyone", C["cream"])],
            [("is awake. sleepers wake when", C["cream"])],
            [("their owner says anything.", C["cream"])]])
        hud.panel(img, (3 * g + 2 * pw, y0, W - g, y1), "CHAT", [
            [("@atleastonce ", name_col("atleastonce")), ("last one up. night, all", C["cream"])],
            [("@sami ", name_col("sami")), ("the beacon stays lit", C["cream"])],
            [("@tinytash ", name_col("tinytash")), ("heading home", C["cream"])]])
    else:
        hud.header(img, left, "2 SETTLED · 0 AWAKE", [("LIVE · 1 watching", C["cream"])], [("NEXT EVENT 02:41", C["gold"])], progress=0.1)
        hud.panel(img, (g, y0, g + pw, y1), "COLONY", [
            [("2 settled · ", C["cream"]), ("0 awake", C["muted"])],
            [("day 2 · dawn", C["muted"])],
            [("1 plot tilled · 2 huts", C["muted"])],
            [("first hut: ", C["muted"]), ("@kai_dnb", name_col("kai_dnb"))]], right=mm)
        hud.panel(img, (2 * g + pw, y0, 2 * g + 2 * pw, y1), "KEEPER", [
            [("no keeper on duty", C["muted"])],
            [("say anything in chat. a settler", C["cream"])],
            [("with your name wakes up and", C["cream"])],
            [("walks out here.", C["cream"])]])
        hud.panel(img, (3 * g + 2 * pw, y0, W - g, y1), "CHAT", [
            [("chat is quiet. say anything.", C["muted"])]])
    hud.caption(img, "concept render · names are examples", "topdown · seed %d · 40x14 of 256x256 tiles · %s" % (SEED, label))
    return img


# ----------------------------------------------------------------------------- main
def render(scenario: str) -> Tuple[Image.Image, "Frame"]:
    world = World(scenario)
    print("%s: sun %s · site %s · %d huts (%s) · %d farms · %d trees" % (
        scenario, tuple(round(v, 2) for v in world.sun), world.site, len(world.huts), " ".join(h["name"] for h in world.huts),
        len(world.farms), sum(1 for o in world.objects() if o[0] == "tree")))
    baker = Baker(world)
    actors = place_settlers(world)
    fr = Frame(world, baker, actors)
    t = {"busy": 0.35, "dawn": 0.1, "night": 0.6}[scenario]
    rgb = fr.compose(t)
    return hud_frame(world, rgb, scenario), fr


def bench(fr: Frame, n: int = 90) -> Tuple[float, float, float]:
    for wp in range(4):
        for rp in range(4):
            fr.b.bake(wp, rp)
    ts = []
    for i in range(n):
        t0 = time.perf_counter()
        fr.compose(i / 30.0)
        ts.append((time.perf_counter() - t0) * 1000)
    ts = np.array(ts)
    return float(ts.mean()), float(np.percentile(ts, 95)), float(ts.max())


if __name__ == "__main__":
    out = HERE
    t0 = time.perf_counter()
    busy, fr = render("busy")
    print("busy render %.1fs (includes settler cache warm-up + first bake)" % (time.perf_counter() - t0))
    busy.save(os.path.join(out, "final_mockup_busy.png"))
    busy.resize((320, 180), Image.Resampling.LANCZOS).save(os.path.join(out, "final_thumb_320x180.png"))
    dawn, _ = render("dawn")
    dawn.save(os.path.join(out, "final_mockup_dawn.png"))
    night, _ = render("night")
    night.save(os.path.join(out, "final_mockup_night.png"))
    # settler frame cost
    creatures.clear_cache()
    t1 = time.perf_counter()
    creatures.settler_sheet("sami", 2, 1, fr.sun)
    ms1 = (time.perf_counter() - t1) * 1000 / len(creatures.FRAMES)
    t1 = time.perf_counter()
    creatures.settler_sheet("sami", 2, 2, fr.sun)
    ms2 = (time.perf_counter() - t1) * 1000 / len(creatures.FRAMES)
    print("settler frame: %.1f ms at 1x, %.1f ms at 2x (%d frames per sheet)" % (ms1, ms2, len(creatures.FRAMES)))
    # ground paint cost at 40x27 tiles
    cells = np.full((27 * 8, 40 * 8), tiles.CAT["grass"], np.int8)
    cells[:, 260:] = tiles.CAT["water_shallow"]
    cells[60:120, 40:160] = tiles.CAT["meadow"]
    gr = tiles.Ground(cells, 1.0)
    t1 = time.perf_counter()
    gr.paint(0, 0)
    print("ground paint 40x27 tiles (320x216 cells): %.1f ms" % ((time.perf_counter() - t1) * 1000))
    # benchmark: 20 settlers on the busy world, all 16 backgrounds pre-baked
    extra = ["gg_marc", "vee.flac", "ollie_k", "sunspot", "n0va", "quietpete"]
    for i, n in enumerate(extra):
        fr.actors.append({"name": n, "frame": creatures.FRAMES[i % len(creatures.FRAMES)], "pos": (200 + i * 150, 300 + (i % 3) * 30),
                          "tier": settler_tier(n), "facing": 1, "speech": None})
        creatures.settler_sheet(n, settler_tier(n), 1, fr.sun)
    for a in fr.actors:
        creatures.settler_sheet(a["name"], a["tier"], 1, fr.sun)
    mean, p95, mx = bench(fr)
    print("world compose @ %d settlers, 3 cloud shadows, 3 pills, smoke: mean %.2f ms  p95 %.2f ms  max %.2f ms" % (len(fr.actors), mean, p95, mx))
    t1 = time.perf_counter()
    fr.b.cache.clear()
    fr.b.bake(0, 0)
    print("one background bake (ground + props + grade + glows): %.0f ms" % ((time.perf_counter() - t1) * 1000))
    print("creature cache: %s" % creatures.cache_stats())
    # contact sheet from the canonical module
    names = NAMES[:12]
    sheet = creatures.sheet_image(names, sun=fr.sun)
    sheet.save(os.path.join(out, "final_settler_sheet.png"))
    print("wrote final_settler_sheet.png %dx%d" % sheet.size)
