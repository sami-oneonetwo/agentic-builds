"""tiles.py - settlers-round tile atlas generator (SETTLEMENT top-down). Studio C's flat chunky tiles plus
Studio B's ground richness: canopy depth on trees, flower drifts in the meadow, worn paths with crumbled edges.

Flat, two-tone, bold: every tile is a flat base colour plus a few chunky marks (grass tufts, ripple crests,
pebbles, furrows) drawn at 3x and downsampled, so the world stays clean through a 3 Mbps encode and reads as
colour fields at 320x180. Nothing in a tile crosses its edge, so any tile sits next to any other; the renderer
draws the organic biome boundaries (coast line, path edges) itself from the per-pixel category map.

Motion lives in phases baked into the atlas, never computed per frame:
    wind phase   0..3 (play 0 1 2 3 2 1): grass and meadow tufts lean, flowers bob, tree canopies sway
    ripple phase 0..3 (loop):             water crests drift down the tile (seamless vertically)
Season is a float 0..4 (spring, summer, autumn, winter, back to spring) that recolours grass and trees.

    import tiles
    A, CAT = tiles.terrain_stack(season=1.0, wind=2, ripple=0)   # (K, 32, 32, 3) uint8 + {name: (start, count)}
    tiles.tree(size=2, variant=0, phase=1, season=1.0)           # (H, W, 4) uint8 sprite, anchor at bottom centre
    tiles.atlas_image(1.0).save("tile_atlas.png")
"""
from __future__ import annotations

import hashlib
import math
from typing import Dict, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

T = 32
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
SUN = (-0.62, -0.78)     # toward the sun (top-left); shadows fall to the bottom-right

CATEGORIES = (  # name, variants
    ("water_deep", 1), ("water_shallow", 1), ("sand", 3), ("grass", 4), ("meadow", 4), ("forest_floor", 3),
    ("hill", 3), ("rock", 3), ("path0", 2), ("path1", 2), ("path2", 2), ("farm0", 1), ("farm1", 1), ("farm2", 1), ("farm3", 1),
)


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
    """Tiny SS-scaled drawing context over an RGB or RGBA image."""

    def __init__(self, w: int, h: int, base=None):
        mode = "RGB" if base is not None else "RGBA"
        self.img = Image.new(mode, (w * SS, h * SS), (base + (255,)) if base is not None and mode == "RGBA" else (base if base is not None else (0, 0, 0, 0)))
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
    rng = _rng("path", wear, variant)
    if wear == 0:
        base = season_colour("grass", season)
        d = _D(T, T, base)
        for _ in range(3):
            d.ellipse(rng.uniform(6, T - 6), rng.uniform(6, T - 6), rng.uniform(5, 8), rng.uniform(3, 5), _mix(base, FLAT["dirt"], 0.55))
        _tufts(d, rng, 2, 1, base, length=(3, 5))
        return d.out()
    if wear == 1:
        # worn dirt: a paler trodden centre, darker crumbs, and two grass tufts creeping in from the edges
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
    d = _D(T, T, FLAT["soil"])
    rng = _rng("farm", stage)
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


# ----------------------------------------------------------------------------- tree sprites (RGBA)
TREE_R = {0: 9, 1: 12, 2: 16}


def tree(size: int, variant: int, phase: int, season: float) -> np.ndarray:
    """Canopy cloud with DEPTH: a dark under-canopy toward the bottom-right, mid lobes, lit lobes toward the sun
    (top-left) and a light crown; a peeking trunk with a trunk shadow; ground shadow offset away from the sun.
    Anchor = (W//2, H-4). Sway follows the wind phase."""
    R = TREE_R[size]
    W, H = int(R * 3.0), int(R * 3.1)
    d = _D(W, H)
    rng = _rng("tree", size, variant)
    cx, base_y = W / 2.0, H - 4.0
    sway = WIND_LEAN[phase] * (1.2 + 0.6 * size)
    # ground shadow slides away from the sun
    d.ellipse(cx - SUN[0] * R * 0.35, base_y + 0.5, R * 0.95, R * 0.34, (20, 24, 12, 96))
    # trunk + trunk shadow
    d.rect(cx - R * 0.16, base_y - R * 0.75, cx + R * 0.16, base_y, FLAT["trunk"], OUTLINE, 0.8, r=1.0)
    d.rect(cx + R * 0.02, base_y - R * 0.7, cx + R * 0.14, base_y - 0.5, _scale(FLAT["trunk"], 0.72), r=0.6)
    col = season_colour("tree", season)
    light = season_colour("tree_light", season)
    dark = _scale(col, 0.72)
    ccx, ccy = cx + sway, base_y - R * 1.2
    lobes = []
    n = 5 + size
    for k in range(n):
        a = 2 * math.pi * k / n + rng.uniform(-0.3, 0.3)
        rr = R * rng.uniform(0.36, 0.55)
        lobes.append((ccx + math.cos(a) * R * 0.58, ccy + math.sin(a) * R * 0.48, rr))
    lobes.append((ccx, ccy, R * 0.72))
    ow = 1.0 + 0.2 * size
    for (x, y, rr) in lobes:
        d.ellipse(x, y, rr, rr, OUTLINE)
    for (x, y, rr) in lobes:            # base canopy
        d.ellipse(x, y, rr - ow, rr - ow, col)
    for (x, y, rr) in lobes:            # under-canopy: the part of each lobe away from the sun goes dark
        d.ellipse(x - SUN[0] * rr * 0.32, y - SUN[1] * rr * 0.32, (rr - ow) * 0.78, (rr - ow) * 0.7, dark)
    for (x, y, rr) in lobes:            # then relight the sun side so the lobe reads as a sphere
        d.ellipse(x + SUN[0] * rr * 0.12, y + SUN[1] * rr * 0.12, (rr - ow) * 0.72, (rr - ow) * 0.66, col)
    for (x, y, rr) in sorted(lobes, key=lambda l: l[0] * SUN[0] + l[1] * SUN[1], reverse=True)[:len(lobes) // 2 + 1]:
        d.ellipse(x + SUN[0] * rr * 0.30, y + SUN[1] * rr * 0.34, rr * 0.42, rr * 0.34, light)
    d.ellipse(ccx + SUN[0] * R * 0.25, ccy + SUN[1] * R * 0.30, R * 0.22, R * 0.16, _mix(light, (255, 255, 230), 0.35))
    return d.out_rgba()


def bush(variant: int, phase: int, season: float) -> np.ndarray:
    """Low shrub for meadow edges and hut gardens: three lobes, lit side toward the sun. Anchor bottom centre."""
    d = _D(20, 16)
    rng = _rng("bush", variant)
    col = season_colour("tree", season)
    light = season_colour("tree_light", season)
    sway = WIND_LEAN[phase] * 0.8
    d.ellipse(10.5, 14, 8, 2.4, (20, 24, 12, 80))
    lobes = [(6 + sway, 9, 4.6), (14 + sway, 9.5, 4.2), (10 + sway, 6.5, 4.8)]
    for (x, y, r) in lobes:
        d.ellipse(x, y, r, r, OUTLINE)
    for (x, y, r) in lobes:
        d.ellipse(x, y, r - 0.9, r - 0.9, col)
    for (x, y, r) in lobes:
        d.ellipse(x + SUN[0] * r * 0.3, y + SUN[1] * r * 0.3, r * 0.42, r * 0.34, light)
    if rng.rand() < 0.5:
        for k in range(2):
            d.ellipse(rng.uniform(5, 15) + sway, rng.uniform(5, 11), 1.1, 1.1, FLOWERS[rng.randint(len(FLOWERS))], OUTLINE, 0.4)
    return d.out_rgba()


def tree_anchor(size: int) -> Tuple[int, int]:
    R = TREE_R[size]
    return int(R * 3.0) // 2, int(R * 3.1) - 4


# ----------------------------------------------------------------------------- stacks for the renderer
def category_index() -> Dict[str, Tuple[int, int]]:
    idx, start = {}, 0
    for name, n in CATEGORIES:
        idx[name] = (start, n)
        start += n
    return idx


def terrain_stack(season: float, wind: int, ripple: int) -> Tuple[np.ndarray, Dict[str, Tuple[int, int]]]:
    """All terrain tiles for one (wind, ripple) phase pair as one (K, 32, 32, 3) array."""
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
    H = 20 + len(rows) * (T * scale + 46) + 190
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
    d.text((20, y), "trees with canopy depth · size 0/1/2 x wind 0-3 (sway) · autumn / winter · bushes", font=bold, fill=(240, 228, 200))
    y += 30
    x = 20
    for size in range(3):
        for p in range(4):
            sp = tree(size, p % 2, p, season)
            im = Image.fromarray(sp).resize((sp.shape[1] * scale, sp.shape[0] * scale), Image.Resampling.NEAREST)
            img.paste(im, (x, y + 96 - im.height), im)
            x += im.width + 8
    for s in (2.0, 3.0):
        sp = tree(2, 0, 1, s)
        im = Image.fromarray(sp).resize((sp.shape[1] * scale, sp.shape[0] * scale), Image.Resampling.NEAREST)
        img.paste(im, (x, y + 96 - im.height), im)
        x += im.width + 8
    for v in range(3):
        sp = bush(v, 1, season)
        im = Image.fromarray(sp).resize((sp.shape[1] * scale, sp.shape[0] * scale), Image.Resampling.NEAREST)
        img.paste(im, (x, y + 96 - im.height), im)
        x += im.width + 8
    d.text((20, y + 108), "32 px tiles shown at 2x. Flat base + chunky marks; edges never cross the tile. Wind plays 0 1 2 3 2 1.", font=font, fill=(200, 188, 160))
    return img


if __name__ == "__main__":
    import time
    t0 = time.perf_counter()
    A, cat = terrain_stack(1.0, 0, 0)
    print("terrain_stack: %d tiles in %.0f ms" % (A.shape[0], (time.perf_counter() - t0) * 1000))
    atlas_image(1.0).save("/Users/sandy/Workspace/agentic-builds/kick-live/docs/art/settlers-round/tile_atlas.png")
