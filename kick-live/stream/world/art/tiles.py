"""tiles.py - terrain tiles, the tile atlas and the GROUND painter for the SETTLEMENT world (canonical art module).

Flat, two-tone, bold (Studio C) with Studio B's richness: every 32 px tile is a flat base colour plus a few chunky
marks (grass tufts, flower drifts, ripple crests, pebbles, furrows) drawn at 3x and downsampled, so the world stays
clean through a 3 Mbps encode and reads as colour fields at 320x180. Nothing in a tile crosses its edge, so any tile
sits next to any other; the ground painter draws the organic biome boundaries (coast line, path edges, foam) itself
from the per-cell category map.

Motion is baked into the atlas as phases, never computed per frame:
    wind phase   0..3 (play 0 1 2 3 2 1): grass and meadow tufts lean, flowers bob
    ripple phase 0..3 (loop):             water crests drift down the tile (seamless vertically)
Season is a float 0..4 (spring, summer, autumn, winter, back to spring) that recolours grass, hills and trees.

    from stream.world.art import tiles
    at = tiles.atlas(season=1.0)                      # cached; at.stack(wind, ripple) -> (K, 32, 32, 3) uint8
    cells = np.full((216, 320), tiles.CAT["grass"], np.int8)      # category per 4x4 px cell (organic coasts)
    g = tiles.Ground(cells, season=1.0)               # 320x216 cells = 1280x864 px = 40x27 tiles
    rgb = g.paint(wind=0, ripple=0)                   # (864, 1280, 3) uint8; cached per (wind, ripple)
    rgb = g.repaint((x0, y0, x1, y1), wind, ripple)   # re-gather one cell rectangle after the map changed
    rgb = tiles.grade(rgb, hour=23.0, water=g.water)  # time-of-day grade (night never darker than the 0.55 floor)

numpy + pillow only, Python 3.9.
"""
from __future__ import annotations

import hashlib
import math
from typing import Dict, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw

T = 32                      # tile edge in px
CELL = 4                    # ground-painter cell in px (a category map at 4 px/cell gives organic coasts)
SS = 3
WIND_LEAN = (-0.55, -0.18, 0.18, 0.55)
WIND_PLAY = (0, 1, 2, 3, 2, 1)            # ping-pong order for a smooth sway
OUTLINE = (44, 36, 30)

_KEYS = {  # spring, summer, autumn, winter
    "grass": ((118, 178, 92), (104, 164, 78), (170, 152, 78), (186, 194, 182)),
    "tree": ((70, 138, 76), (58, 122, 66), (182, 106, 52), (74, 100, 84)),
    "tree_light": ((120, 190, 104), (104, 172, 92), (226, 156, 72), (120, 146, 126)),
    "hill": ((162, 172, 108), (156, 166, 100), (176, 156, 96), (196, 198, 186)),
}
FLAT = {
    "sand": (234, 214, 160), "sand_dark": (204, 180, 124),
    "water_shallow": (92, 178, 206), "water_deep": (46, 112, 166), "ripple": (206, 236, 244),
    "rock": (146, 142, 130), "rock_light": (184, 180, 166), "rock_dark": (92, 88, 80),
    "dirt": (200, 172, 118), "dirt_dark": (160, 130, 86), "cobble": (188, 170, 138), "cobble_light": (214, 198, 166), "grout": (132, 108, 80),
    "soil": (128, 90, 58), "soil_dark": (98, 66, 42), "sprout": (160, 216, 112), "leaf": (86, 152, 68), "ripe": (244, 172, 64),
    "trunk": (96, 66, 44), "litter": (150, 110, 70),
}
FLOWERS = ((252, 246, 232), (250, 210, 96), (246, 166, 184), (200, 170, 250), (255, 138, 110))

CATEGORIES = (  # name, variants   (the order fixes the category ids in CAT)
    ("water_deep", 1), ("water_shallow", 1), ("sand", 3), ("grass", 4), ("meadow", 4), ("forest_floor", 3),
    ("hill", 3), ("rock", 3), ("path0", 2), ("path1", 2), ("path2", 2), ("farm0", 1), ("farm1", 1), ("farm2", 1), ("farm3", 1),
)
CAT: Dict[str, int] = {name: i for i, (name, _) in enumerate(CATEGORIES)}
# edge groups: a dark boundary line is drawn where the group changes (water has none; path0 blends into grass)
GROUP = np.array([0, 0, 1, 2, 2, 2, 3, 4, 2, 5, 5, 6, 6, 6, 6], np.int8)
WATER_IDS = (CAT["water_deep"], CAT["water_shallow"])


def _mix(a, b, t):
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))


def _scale(c, k):
    return tuple(max(0, min(255, int(round(v * k)))) for v in c)


def season_colour(key: str, season: float) -> Tuple[int, int, int]:
    ks = _KEYS[key]
    s = season % 4.0
    i = int(math.floor(s))
    return _mix(ks[i], ks[(i + 1) % 4], s - i)


def _rng(*keys) -> np.random.RandomState:
    h = hashlib.sha1(("|".join(str(k) for k in keys)).encode()).digest()
    return np.random.RandomState(int.from_bytes(h[:4], "little"))


class _D:
    """Tiny SS-scaled drawing context over an RGB or RGBA image (shared with props and buildings)."""

    def __init__(self, w: int, h: int, base=None):
        mode = "RGB" if base is not None else "RGBA"
        self.img = Image.new(mode, (w * SS, h * SS), base if base is not None else (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img, "RGBA")
        self.w, self.h = w, h

    def ellipse(self, cx, cy, rx, ry, fill, outline=None, ow=0.0):
        if outline is not None and ow > 0:
            self.d.ellipse([(cx - rx - ow) * SS, (cy - ry - ow) * SS, (cx + rx + ow) * SS, (cy + ry + ow) * SS], fill=outline)
        self.d.ellipse([(cx - rx) * SS, (cy - ry) * SS, (cx + rx) * SS, (cy + ry) * SS], fill=fill)

    def line(self, pts, fill, width):
        self.d.line([(x * SS, y * SS) for x, y in pts], fill=fill, width=max(1, int(round(width * SS))), joint="curve")

    def poly(self, pts, fill, outline=None, ow=0.0):
        p = [(x * SS, y * SS) for x, y in pts]
        if outline is not None and ow > 0:
            self.d.polygon(p, fill=outline, outline=outline, width=max(1, int(round(ow * SS * 2))))
        self.d.polygon(p, fill=fill)

    def rect(self, x0, y0, x1, y1, fill, outline=None, ow=0.0, r=0.0):
        if outline is not None and ow > 0:
            self.d.rounded_rectangle([(x0 - ow) * SS, (y0 - ow) * SS, (x1 + ow) * SS, (y1 + ow) * SS], radius=(r + ow) * SS, fill=outline)
        self.d.rounded_rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], radius=r * SS, fill=fill)

    def arc(self, cx, cy, rx, ry, a0, a1, fill, width):
        self.d.arc([(cx - rx) * SS, (cy - ry) * SS, (cx + rx) * SS, (cy + ry) * SS], a0, a1, fill=fill, width=max(1, int(round(width * SS))))

    def out(self) -> np.ndarray:
        im = self.img.resize((self.w, self.h), Image.Resampling.LANCZOS)
        return np.asarray(im, dtype=np.uint8).copy()

    def out_rgba(self) -> np.ndarray:
        a = np.asarray(self.img, dtype=np.float32)
        al = a[..., 3:4] / 255.0
        pm = a[..., :3] * al
        ch = [np.asarray(Image.fromarray(np.ascontiguousarray(pm[..., k])).resize((self.w, self.h), Image.Resampling.LANCZOS)) for k in range(3)]
        alpha = np.clip(np.asarray(Image.fromarray(np.ascontiguousarray(a[..., 3])).resize((self.w, self.h), Image.Resampling.LANCZOS)), 0, 255)
        rgb = np.stack(ch, -1)
        nz = alpha > 0.5
        rgb[nz] = rgb[nz] / (alpha[nz][..., None] / 255.0)
        out = np.zeros((self.h, self.w, 4), np.uint8)
        out[..., :3] = np.clip(rgb, 0, 255)
        out[..., 3] = alpha
        return out


# ----------------------------------------------------------------------------- terrain tiles (RGB 32x32)
def _tufts(d: _D, rng, n, phase, base, length=(5, 8), spread=1.6):
    dark = _scale(base, 0.74)
    light = _mix(base, (255, 255, 240), 0.22)
    lean = WIND_LEAN[phase]
    for _ in range(n):
        x = rng.uniform(4, T - 4)
        y = rng.uniform(6, T - 2)
        L = rng.uniform(*length)
        for j, col in ((-1, dark), (0, light), (1, dark)):
            tip = (x + lean * L + spread * j + 0.4 * lean * j, y - L * (0.8 if j else 1.0))
            d.line([(x, y), tip], col, 1.3)


def grass(variant: int, phase: int, season: float) -> np.ndarray:
    base = season_colour("grass", season)
    d = _D(T, T, base)
    rng = _rng("grass", variant)
    for _ in range(2):                     # soft lighter patches: the ground is not one flat colour
        d.ellipse(rng.uniform(6, T - 6), rng.uniform(6, T - 6), rng.uniform(5, 9), rng.uniform(3, 5), _mix(base, (255, 255, 230), 0.07))
    _tufts(d, rng, 6, phase, base)
    return d.out()


def meadow(variant: int, phase: int, season: float) -> np.ndarray:
    """Meadow with a flower DRIFT: 3-5 blooms of one colour strung along a gentle curve, plus a stray of another
    colour, so flowers read as coloured streaks across the field at 320x180 rather than confetti."""
    base = _mix(season_colour("grass", season), (255, 255, 200), 0.05)
    d = _D(T, T, base)
    rng = _rng("meadow", variant)
    _tufts(d, rng, 3, phase, base)
    bob = WIND_LEAN[phase] * 1.6
    col = FLOWERS[rng.randint(len(FLOWERS))]
    n = rng.randint(3, 6)
    x0, y0 = rng.uniform(4, 10), rng.uniform(6, T - 6)
    ang = rng.uniform(-0.5, 0.5)
    for k in range(n):
        x = x0 + k * (T - 8) / max(1, n - 1) * 0.9
        y = y0 + math.sin(ang + k * 0.9) * 4.0
        x, y = min(T - 4, max(4, x)), min(T - 4, max(4, y))
        r = rng.uniform(1.9, 2.6)
        d.line([(x, y + 3.2), (x + bob * 0.5, y)], _scale(base, 0.68), 1.2)
        d.ellipse(x + bob, y, r, r, col, OUTLINE, 0.6)
        d.ellipse(x + bob, y, 0.9, 0.9, (214, 150, 46))
    sx, sy = rng.uniform(4, T - 4), rng.uniform(4, T - 4)
    d.ellipse(sx + bob, sy, 1.8, 1.8, FLOWERS[(rng.randint(len(FLOWERS)) + 1) % len(FLOWERS)], OUTLINE, 0.5)
    return d.out()


def forest_floor(variant: int, season: float) -> np.ndarray:
    base = _scale(season_colour("grass", season), 0.78)
    d = _D(T, T, base)
    rng = _rng("floor", variant)
    for _ in range(5):
        d.ellipse(rng.uniform(3, T - 3), rng.uniform(3, T - 3), 1.6, 1.1, _scale(base, 0.8))
    for _ in range(2):
        d.ellipse(rng.uniform(3, T - 3), rng.uniform(3, T - 3), 1.8, 1.2, FLAT["litter"])
    return d.out()


def sand(variant: int) -> np.ndarray:
    d = _D(T, T, FLAT["sand"])
    rng = _rng("sand", variant)
    d.ellipse(rng.uniform(8, T - 8), rng.uniform(8, T - 8), rng.uniform(5, 9), rng.uniform(3, 5), _mix(FLAT["sand"], (255, 250, 236), 0.35))
    for _ in range(5):
        d.ellipse(rng.uniform(2, T - 2), rng.uniform(2, T - 2), 0.9, 0.9, FLAT["sand_dark"])
    return d.out()


def water(depth: str, phase: int) -> np.ndarray:
    base = FLAT["water_deep"] if depth == "deep" else FLAT["water_shallow"]
    d = _D(T, T, base)
    crest = _mix(base, FLAT["ripple"], 0.55 if depth == "deep" else 0.8)
    for k in range(2):
        y0 = (k * T / 2.0 + phase * T / 4.0) % T
        for wrap in (-T, 0, T):
            pts = []
            for i in range(0, 17):
                x = i * 2.0
                pts.append((x, y0 + wrap + 1.4 * math.sin(2 * math.pi * x / 16.0 + k * 1.3)))
            seg = pts[3:12] if k == 0 else pts[9:17]
            d.line(seg, crest, 1.5)
    return d.out()


def hill(variant: int, season: float) -> np.ndarray:
    base = season_colour("hill", season)
    d = _D(T, T, base)
    rng = _rng("hill", variant)
    dark = _scale(base, 0.82)
    for _ in range(2):
        x, y = rng.uniform(4, T - 10), rng.uniform(6, T - 6)
        d.line([(x, y), (x + rng.uniform(5, 9), y + rng.uniform(-1.5, 1.5))], dark, 1.4)
    _tufts(d, rng, 2, 1, base, length=(3, 5))
    return d.out()


def rock(variant: int) -> np.ndarray:
    d = _D(T, T, FLAT["rock"])
    rng = _rng("rock", variant)
    for _ in range(2):
        x, y = rng.uniform(7, T - 7), rng.uniform(7, T - 7)
        rx, ry = rng.uniform(4, 7), rng.uniform(3, 5)
        d.ellipse(x, y, rx, ry, FLAT["rock_light"], FLAT["rock_dark"], 1.0)
        d.ellipse(x - rx * 0.3, y - ry * 0.35, rx * 0.45, ry * 0.35, _mix(FLAT["rock_light"], (255, 255, 255), 0.35))
    return d.out()


def path(wear: int, variant: int, season: float) -> np.ndarray:
    """wear 0: grass with trodden patches · 1: worn dirt (pale centre, crumbs, grass creeping in) · 2: cobbles."""
    rng = _rng("path", wear, variant)
    if wear == 0:
        base = season_colour("grass", season)
        d = _D(T, T, base)
        for _ in range(3):
            d.ellipse(rng.uniform(6, T - 6), rng.uniform(6, T - 6), rng.uniform(5, 8), rng.uniform(3, 5), _mix(base, FLAT["dirt"], 0.55))
        _tufts(d, rng, 2, 1, base, length=(3, 5))
        return d.out()
    if wear == 1:
        grass_c = season_colour("grass", season)
        d = _D(T, T, FLAT["dirt"])
        d.ellipse(T / 2.0 + rng.uniform(-3, 3), T / 2.0 + rng.uniform(-3, 3), 11, 7, _mix(FLAT["dirt"], (255, 250, 230), 0.22))
        for _ in range(5):
            d.ellipse(rng.uniform(3, T - 3), rng.uniform(3, T - 3), 1.5, 1.0, FLAT["dirt_dark"])
        for _ in range(2):
            d.ellipse(rng.uniform(2, T - 2), rng.uniform(2, T - 2), 1.1, 1.1, _mix(FLAT["dirt"], FLAT["rock_light"], 0.5))
        for (x, y) in ((rng.uniform(2, 6), rng.uniform(4, T - 4)), (rng.uniform(T - 6, T - 2), rng.uniform(4, T - 4))):
            d.line([(x, y + 2), (x - 1.2, y - 2.5)], _scale(grass_c, 0.8), 1.2)
            d.line([(x, y + 2), (x + 1.4, y - 2.2)], grass_c, 1.2)
        return d.out()
    d = _D(T, T, FLAT["grout"])
    for j in range(3):
        for i in range(3):
            x0, y0 = i * T / 3.0 + 1.2, j * T / 3.0 + 1.2
            col = FLAT["cobble_light"] if (i + j + variant) % 2 == 0 else FLAT["cobble"]
            wornc = _mix(col, (255, 250, 236), 0.18) if (i == 1 and j == 1) else col      # polished centre stone
            d.rect(x0, y0, x0 + T / 3.0 - 2.4, y0 + T / 3.0 - 2.4, wornc, r=3.0)
            d.line([(x0 + 1.5, y0 + T / 3.0 - 3.2), (x0 + T / 3.0 - 3.5, y0 + T / 3.0 - 3.2)], _scale(col, 0.86), 0.9)
    return d.out()


def farm(stage: int) -> np.ndarray:
    """stage 0 tilled · 1 sprouts · 2 leafy · 3 ripe (orange fruit)."""
    d = _D(T, T, FLAT["soil"])
    for r in range(4):
        y = 4 + r * 8
        d.line([(1, y), (T - 1, y)], FLAT["soil_dark"], 2.2)
        if stage >= 1:
            for x in (5, 13, 21, 29):
                if stage == 1:
                    d.line([(x, y - 3), (x - 1.5, y - 5.5)], FLAT["sprout"], 1.3)
                    d.line([(x, y - 3), (x + 1.5, y - 5.5)], FLAT["sprout"], 1.3)
                else:
                    d.ellipse(x, y - 3.2, 3.2, 2.6, FLAT["leaf"], OUTLINE, 0.6)
                    d.ellipse(x - 1, y - 4, 1.2, 0.9, _mix(FLAT["leaf"], (255, 255, 220), 0.3))
                    if stage == 3:
                        d.ellipse(x + 1.2, y - 2.2, 1.4, 1.4, FLAT["ripe"], OUTLINE, 0.5)
    return d.out()


# ----------------------------------------------------------------------------- atlas
def category_index() -> Dict[str, Tuple[int, int]]:
    idx, start = {}, 0
    for name, n in CATEGORIES:
        idx[name] = (start, n)
        start += n
    return idx


def terrain_stack(season: float, wind: int, ripple: int) -> Tuple[np.ndarray, Dict[str, Tuple[int, int]]]:
    """All terrain tiles for one (wind, ripple) phase pair as one (K, 32, 32, 3) array plus {name: (start, count)}."""
    cat = category_index()
    K = sum(n for _, n in CATEGORIES)
    A = np.zeros((K, T, T, 3), np.uint8)
    for name, n in CATEGORIES:
        s0 = cat[name][0]
        for v in range(n):
            if name == "water_deep":
                A[s0 + v] = water("deep", ripple)
            elif name == "water_shallow":
                A[s0 + v] = water("shallow", ripple)
            elif name == "sand":
                A[s0 + v] = sand(v)
            elif name == "grass":
                A[s0 + v] = grass(v, wind, season)
            elif name == "meadow":
                A[s0 + v] = meadow(v, wind, season)
            elif name == "forest_floor":
                A[s0 + v] = forest_floor(v, season)
            elif name == "hill":
                A[s0 + v] = hill(v, season)
            elif name == "rock":
                A[s0 + v] = rock(v)
            elif name.startswith("path"):
                A[s0 + v] = path(int(name[4]), v, season)
            elif name.startswith("farm"):
                A[s0 + v] = farm(int(name[4]))
    return A, cat


class Atlas:
    """The tile stacks for one season, built lazily per (wind, ripple) phase pair (16 stacks, ~35 ms each)."""

    def __init__(self, season: float):
        self.season = season
        self.index = category_index()
        self.K = sum(n for _, n in CATEGORIES)
        self._stacks: Dict[Tuple[int, int], np.ndarray] = {}
        self.start = np.zeros(len(CATEGORIES), np.int32)
        self.count = np.ones(len(CATEGORIES), np.int32)
        for name, i in CAT.items():
            self.start[i], self.count[i] = self.index[name]

    def stack(self, wind: int = 0, ripple: int = 0) -> np.ndarray:
        key = (int(wind) % 4, int(ripple) % 4)
        A = self._stacks.get(key)
        if A is None:
            A = terrain_stack(self.season, key[0], key[1])[0]
            self._stacks[key] = A
        return A

    def prebake(self) -> None:
        for w in range(4):
            for r in range(4):
                self.stack(w, r)


_ATLAS: Dict[float, Atlas] = {}


def atlas(season: float = 1.0) -> Atlas:
    key = round(float(season) * 20) / 20.0
    a = _ATLAS.get(key)
    if a is None:
        a = Atlas(key)
        _ATLAS[key] = a
    return a


# ----------------------------------------------------------------------------- ground painter
def _hash2(i: np.ndarray, j: np.ndarray, seed: int) -> np.ndarray:
    i = i.astype(np.int64)
    j = j.astype(np.int64)
    n = (i * 374761393 + j * 668265263 + int(seed) * 1013904223) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    n = (n ^ (n >> 16)) & 0xFFFFFFFF
    return n.astype(np.float32) / np.float32(4294967295.0)


class Ground:
    """Paints a category map (int8 per 4x4 px cell) into RGB from the atlas: tile textures continue across cells
    (indexed by world pixel position mod 32, variant hashed per tile), biome edges get a dark line, water next to land
    gets foam that drifts with the ripple phase, an optional per-cell shade map (relief, mottle) multiplies the land.

        g = Ground(cells, season, origin=(0, 0), shade=None, seed=0)
        g.paint(wind, ripple) -> (H*4, W*4, 3) uint8  (cached per phase pair)
        g.repaint(region, wind, ripple)               region = (x0, y0, x1, y1) in cells, after set_cells()
        g.set_cells(cells)                            new map, drops the cache
        g.water                                       bool (H, W) cell mask
    `origin` is the world tile offset of cell (0, 0) so a scrolling camera keeps the same texture under the same
    ground."""

    def __init__(self, cells: np.ndarray, season: float = 1.0, origin: Tuple[int, int] = (0, 0),
                 shade: Optional[np.ndarray] = None, seed: int = 0):
        self.atlas = atlas(season)
        self.season = season
        self.origin = origin
        self.seed = seed
        self.shade = None if shade is None else shade.astype(np.float32)
        self._cache: Dict[Tuple[int, int], np.ndarray] = {}
        self.set_cells(cells)

    # -- static lookups
    def set_cells(self, cells: np.ndarray) -> None:
        self.cells = cells.astype(np.int8)
        Hc, Wc = self.cells.shape
        self.H, self.W = Hc * CELL, Wc * CELL
        self.water = np.isin(self.cells, WATER_IDS)
        self._cache.clear()
        self._prep(0, 0, Wc, Hc, full=True)

    def _prep(self, x0: int, y0: int, x1: int, y1: int, full: bool = False) -> None:
        """Per-pixel tile index and edge / foam masks for a cell rectangle."""
        ox, oy = self.origin
        cells = self.cells
        Hc, Wc = cells.shape
        px0, py0, px1, py1 = x0 * CELL, y0 * CELL, x1 * CELL, y1 * CELL
        py, px = np.mgrid[py0:py1, px0:px1].astype(np.int32)
        c = np.repeat(np.repeat(cells[y0:y1, x0:x1], CELL, 0), CELL, 1).astype(np.int32)
        tx, ty = px // T + ox, py // T + oy
        var = _hash2(tx, ty, self.seed + 5)
        idx = self.atlas.start[c] + (var * self.atlas.count[c]).astype(np.int32) % self.atlas.count[c]
        # edges: group changes across 4-neighbours at cell level, one pixel on each side of the boundary
        G = GROUP[cells]
        pad = np.pad(G, 1, mode="edge")
        e = np.zeros_like(G, dtype=bool)
        e |= G != pad[:-2, 1:-1]
        e |= G != pad[2:, 1:-1]
        e |= G != pad[1:-1, :-2]
        e |= G != pad[1:-1, 2:]
        e &= ~self.water
        # the edge line lives on the boundary pixels of the cell: the row/column facing the other group
        Ep = np.zeros((Hc * CELL, Wc * CELL), bool)
        up = (G != pad[:-2, 1:-1]) & ~self.water
        dn = (G != pad[2:, 1:-1]) & ~self.water
        lf = (G != pad[1:-1, :-2]) & ~self.water
        rt = (G != pad[1:-1, 2:]) & ~self.water
        Ep[0::CELL, :] |= np.repeat(up, CELL, 1)
        Ep[CELL - 1::CELL, :] |= np.repeat(dn, CELL, 1)
        Ep[:, 0::CELL] |= np.repeat(lf, CELL, 0)
        Ep[:, CELL - 1::CELL] |= np.repeat(rt, CELL, 0)
        # foam: water cells with land within 2 cells
        land = ~self.water
        near = land.copy()
        for _ in range(2):
            g2 = near.copy()
            g2[1:, :] |= near[:-1, :]
            g2[:-1, :] |= near[1:, :]
            g2[:, 1:] |= near[:, :-1]
            g2[:, :-1] |= near[:, 1:]
            near = g2
        foam = np.repeat(np.repeat(near & self.water, CELL, 0), CELL, 1)
        noise_all = _hash2(np.mgrid[0:Hc * CELL, 0:Wc * CELL][1] // 2 + ox * T, np.mgrid[0:Hc * CELL, 0:Wc * CELL][0] // 2 + oy * T, self.seed + 900)
        if full:
            self.idx = idx
            self.ym, self.xm = (py % T), (px % T)
            self.edge = Ep
            self.foam_zone = foam
            self.foam_noise = noise_all
            self.shade_px = None if self.shade is None else np.repeat(np.repeat(self.shade, CELL, 0), CELL, 1)
        else:
            self.idx[py0:py1, px0:px1] = idx
            self.edge[py0:py1, px0:px1] = Ep[py0:py1, px0:px1]
            self.foam_zone[py0:py1, px0:px1] = foam[py0:py1, px0:px1]

    def _gather(self, wind: int, ripple: int, sl_y: slice, sl_x: slice) -> np.ndarray:
        A = self.atlas.stack(wind, ripple)
        bg = A[self.idx[sl_y, sl_x], self.ym[sl_y, sl_x], self.xm[sl_y, sl_x]].astype(np.float32)
        if self.shade_px is not None:
            sh = self.shade_px[sl_y, sl_x].copy()
            sh[np.repeat(np.repeat(self.water, CELL, 0), CELL, 1)[sl_y, sl_x]] = 1.0
            bg *= sh[..., None]
        bg[self.edge[sl_y, sl_x]] *= 0.70
        foam = self.foam_zone[sl_y, sl_x] & ((self.foam_noise[sl_y, sl_x] + 0.11 * ripple) % 1.0 > 0.45)
        bg[foam] = bg[foam] * 0.35 + np.array(FLAT["ripple"], np.float32) * 0.65
        return np.clip(bg, 0, 255).astype(np.uint8)

    def paint(self, wind: int = 0, ripple: int = 0) -> np.ndarray:
        """The whole ground for one phase pair (cached). Do not write into the result: copy() before blitting props."""
        key = (int(wind) % 4, int(ripple) % 4)
        bg = self._cache.get(key)
        if bg is None:
            bg = self._gather(key[0], key[1], slice(0, self.H), slice(0, self.W))
            self._cache[key] = bg
        return bg

    def repaint(self, region: Tuple[int, int, int, int], wind: int = 0, ripple: int = 0) -> np.ndarray:
        """Re-gather one cell rectangle (x0, y0, x1, y1) after set_cells() changed the map there (a path worn in,
        a farm tilled) and patch it into the cached image for that phase pair. Returns the full image."""
        x0, y0, x1, y1 = region
        Hc, Wc = self.cells.shape
        x0, y0 = max(0, x0 - 1), max(0, y0 - 1)
        x1, y1 = min(Wc, x1 + 1), min(Hc, y1 + 1)
        self._prep(x0, y0, x1, y1)
        key = (int(wind) % 4, int(ripple) % 4)
        bg = self._cache.get(key)
        if bg is None:
            return self.paint(*key)
        sy, sx = slice(y0 * CELL, y1 * CELL), slice(x0 * CELL, x1 * CELL)
        bg[sy, sx] = self._gather(key[0], key[1], sy, sx)
        return bg

    def update_cells(self, region: Tuple[int, int, int, int], new_cells: np.ndarray) -> None:
        """Write a cell rectangle into the map and refresh every cached phase image there."""
        x0, y0, x1, y1 = region
        self.cells[y0:y1, x0:x1] = new_cells
        self.water = np.isin(self.cells, WATER_IDS)
        for key in list(self._cache.keys()):
            self.repaint(region, *key)


def paint(cells: np.ndarray, season: float = 1.0, wind: int = 0, ripple: int = 0, shade: Optional[np.ndarray] = None) -> np.ndarray:
    """One-shot ground paint (RGB uint8 at 4 px per cell). For a running world keep a Ground and call paint() on it."""
    return Ground(cells, season, shade=shade).paint(wind, ripple)


# ----------------------------------------------------------------------------- time of day
def sun_vector(hour: float) -> Tuple[float, float]:
    """Screen-space unit vector TOWARD the sun (x right, y down) for a local hour: east (right) at dawn, high at noon,
    west (left) at dusk; at night the moon sits high in the north (top). Sprites are cached per octant of this."""
    h = hour % 24.0
    if 5.5 <= h <= 19.5:
        t = (h - 5.5) / 14.0                              # 0 at dawn -> 1 at dusk
        x = math.cos(t * math.pi)                          # +1 east ... -1 west
        y = -(0.35 + 0.65 * math.sin(t * math.pi))         # low at the ends, high at noon
    else:
        x, y = 0.15, -0.99
    n = math.hypot(x, y)
    return (x / n, y / n)


def grade(rgb: np.ndarray, hour: float, water: Optional[np.ndarray] = None, floor: float = 0.55) -> np.ndarray:
    """Time-of-day grade for a baked ground (Studio A): dusk goes warm-orange on land while water keeps its own blue,
    dawn is cool and pale, night is a blue-violet multiply that never drops below `floor` of the daylight value (so
    a 3 Mbps encode still shows every colour and every settler). Runs at bake time, never per frame.
    `water` is a bool mask at cell (H/4, W/4) or pixel resolution."""
    f = rgb.astype(np.float32)
    h = hour % 24.0
    if water is not None:
        wm = water
        if wm.shape != f.shape[:2]:
            wm = np.repeat(np.repeat(wm, CELL, 0), CELL, 1)[:f.shape[0], :f.shape[1]]
        wm = wm[..., None].astype(np.float32)
    else:
        wm = np.zeros(f.shape[:2] + (1,), np.float32)

    def daylight(k):
        return f * k

    if 10.0 <= h <= 16.0:                                  # full day: untouched
        return rgb
    if 16.0 < h <= 20.0:                                   # dusk ramp
        t = min(1.0, (h - 16.0) / 2.0)
        land = f * (1 + t * np.array((0.06, -0.16, -0.36), np.float32)) + t * np.array((12, 2, 0), np.float32)
        wat = f * (1 + t * np.array((-0.16, -0.14, 0.02), np.float32)) + t * np.array((4, 8, 24), np.float32)
        out = land * (1 - wm) + wat * wm
        night = max(0.0, (h - 19.0) / 1.0)
        if night > 0:
            out = _nightfall(out, min(1.0, night) * 0.6, floor)
        return np.clip(out, 0, 255).astype(np.uint8)
    if 5.0 <= h < 10.0:                                    # dawn ramp: cool and pale, then clearing
        t = 1.0 - min(1.0, max(0.0, (h - 5.0) / 4.0))
        cool = np.array((214, 204, 236), np.float32)
        out = f * (1 - 0.28 * t) + cool * 0.28 * t * (f / 255.0) * 1.15
        if h < 6.0:
            out = _nightfall(out, (6.0 - h) * 0.6, floor)
        return np.clip(out, 0, 255).astype(np.uint8)
    return np.clip(_nightfall(f, 1.0, floor), 0, 255).astype(np.uint8)   # 20:00 .. 05:00


def _nightfall(f: np.ndarray, t: float, floor: float) -> np.ndarray:
    k = 1.0 - t * (1.0 - floor)                            # brightness multiplier, never below the floor at t = 1
    tint = np.array((0.80, 0.86, 1.18), np.float32)        # blue-violet moonlight
    tint = 1.0 + (tint - 1.0) * t
    return f * k * tint


# ----------------------------------------------------------------------------- atlas review image
def atlas_image(season: float = 1.0) -> Image.Image:
    from PIL import ImageFont
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Verdana.ttf", 20)
    bold = ImageFont.truetype("/System/Library/Fonts/Supplemental/Verdana Bold.ttf", 20)
    rows = [
        ("grass · 4 variants x wind 0-3", [grass(v, p, season) for v in range(4) for p in range(4)]),
        ("meadow flower drifts · 4 variants x wind 0-3", [meadow(v, p, season) for v in range(4) for p in range(4)]),
        ("water deep / shallow · ripple 0-3", [water("deep", p) for p in range(4)] + [water("shallow", p) for p in range(4)]),
        ("sand x3 · forest floor x3 · hill x3 · rock x3", [sand(v) for v in range(3)] + [forest_floor(v, season) for v in range(3)] + [hill(v, season) for v in range(3)] + [rock(v) for v in range(3)]),
        ("path wear 0/1/2 (x2) · farm growth 0-3", [path(w, v, season) for w in range(3) for v in range(2)] + [farm(s) for s in range(4)]),
        ("seasons: grass spring/summer/autumn/winter · hill · forest floor", [grass(0, 1, s) for s in (0, 1, 2, 3)] + [hill(0, s) for s in (0, 1, 2, 3)] + [forest_floor(0, s) for s in (0, 1, 2, 3)]),
    ]
    scale = 2
    W = 40 + 17 * (T * scale + 6)
    H = 20 + len(rows) * (T * scale + 46) + 40
    img = Image.new("RGB", (W, H), (38, 32, 28))
    d = ImageDraw.Draw(img)
    y = 12
    for title, tls in rows:
        d.text((20, y), title, font=bold, fill=(240, 228, 200))
        y += 30
        for i, t in enumerate(tls):
            im = Image.fromarray(t).resize((T * scale, T * scale), Image.Resampling.NEAREST)
            img.paste(im, (20 + i * (T * scale + 6), y))
        y += T * scale + 16
    d.text((20, y), "32 px tiles shown at 2x. Flat base + chunky marks; edges never cross the tile. Wind plays 0 1 2 3 2 1.", font=font, fill=(200, 188, 160))
    return img


if __name__ == "__main__":
    import time
    t0 = time.perf_counter()
    A, cat = terrain_stack(1.0, 0, 0)
    print("terrain_stack: %d tiles in %.0f ms" % (A.shape[0], (time.perf_counter() - t0) * 1000))
    cells = np.full((216, 320), CAT["grass"], np.int8)
    cells[:, 250:] = CAT["water_shallow"]
    cells[:, 280:] = CAT["water_deep"]
    cells[100:140, 40:120] = CAT["meadow"]
    g = Ground(cells, 1.0)
    t0 = time.perf_counter()
    rgb = g.paint(0, 0)
    print("ground paint 320x216 cells (40x27 tiles): %.1f ms" % ((time.perf_counter() - t0) * 1000))
    t0 = time.perf_counter()
    g.repaint((40, 100, 120, 140), 0, 0)
    print("repaint 80x40 cells: %.1f ms" % ((time.perf_counter() - t0) * 1000))
