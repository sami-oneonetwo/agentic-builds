"""tiles.py - studio-b tile atlas: a rich, readable top-down land language (32 px tiles).

    build_atlas()     -> (atlas: np.uint8 (N,32,32,3), index: {name: id})
    props()           -> {name: RGBA sprite}   trees (3 sizes x 2 sway), bushes, rocks, flower clumps, reeds
    light_atlas(atlas, tint) -> the same atlas under a time-of-day light (multiply once, not per frame)
    compose(atlas, ids)      -> RGB image from a (rows, cols) id grid in ONE numpy gather (~1 ms for 40x17)

Tile families and their ids (see index):
    grass.{meadow,grass,lush,dry}.w{0..3}   wind phase 0-3: blades lean and a brightness wave passes
    grass.flowers.{0,1}                      meadow with flower clumps
    forest.floor.{0,1}                       dark mossy floor under the canopy (trees are props)
    water.{deep,shallow}.{0,1}.r{0..3}       2 variants x ripple phase: arcs drift, glints blink
    water.edge.m{0..15}.r{0,1}               shallow water with foam on the land side(s) (bitmask N=1 E=2 S=4 W=8)
    shore.sand.{0,1}                         warm sand with pebbles
    hill.top.{0,1} / hill.edge.s             raised rocky grass; south-facing slope band
    path.grass.{1,2,3}                       trail wear levels on grass
    farm.{bare,sprout,ripe}                  furrows -> green sprouts -> golden crop

Python 3.9, numpy + pillow only. Deterministic (seeded per tile name).
"""
from __future__ import annotations

import math
import os
import sys
from typing import Dict, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SS, Canvas, hex_rgb, mix, rgba, shade  # noqa: E402

T = 32  # tile size in px

# ----------------------------------------------------------------------------- palette (studio-b land)
P = {
    "meadow": hex_rgb("#86BC58"),
    "grass": hex_rgb("#74B04F"),
    "lush": hex_rgb("#5FA34A"),
    "dry": hex_rgb("#9DB85A"),
    "blade_light": hex_rgb("#BFE07A"),
    "blade_dark": hex_rgb("#4C8A38"),
    "forest_floor": hex_rgb("#3E7A3A"),
    "canopy": hex_rgb("#3E8E45"),
    "canopy_dark": hex_rgb("#2C6B36"),
    "canopy_light": hex_rgb("#7BC262"),
    "trunk": hex_rgb("#6E4A2E"),
    "deep": hex_rgb("#2E6FB0"),
    "shallow": hex_rgb("#4E9AD0"),
    "ripple": hex_rgb("#9CD3F0"),
    "foam": hex_rgb("#EAF6FF"),
    "sand": hex_rgb("#E3CF98"),
    "sand_dark": hex_rgb("#C9B078"),
    "rock": hex_rgb("#9A9A8C"),
    "rock_dark": hex_rgb("#6E6E64"),
    "dirt": hex_rgb("#B08A58"),
    "dirt_dark": hex_rgb("#8E6A3E"),
    "furrow": hex_rgb("#8C6A42"),
    "crop_green": hex_rgb("#7FC24F"),
    "crop_gold": hex_rgb("#E5B84A"),
    "flower": [hex_rgb("#FF8FB1"), hex_rgb("#FFE066"), hex_rgb("#FFFFFF"), hex_rgb("#C9A7FF")],
}


def _rng(name: str) -> np.random.RandomState:
    import hashlib
    return np.random.RandomState(int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "little"))


def _wrap_offsets(x, y, w, h, margin=8):
    """Positions to paint a texture element so it wraps toroidally (seamless tile edges)."""
    out = [(x, y)]
    if x < margin:
        out.append((x + w, y))
    if x > w - margin:
        out.append((x - w, y))
    if y < margin:
        out.append((x, y + h))
    if y > h - margin:
        out.append((x, y - h))
    if len(out) == 3:  # corner
        out.append((out[1][0], out[2][1]))
    return out


def _mottle(c: Canvas, base, rng, amount=0.08, n=60, r=(1.5, 3.5)):
    """Soft blotches of lighter/darker base to break the flat fill (painted then blurred, wrapping)."""
    m = Canvas(c.w, c.h)
    for _ in range(n):
        x, y = rng.uniform(0, c.w), rng.uniform(0, c.h)
        k = 1 + rng.uniform(-amount, amount)
        rx, ry = rng.uniform(*r), rng.uniform(*r)
        col = rgba(shade(base, k), 150)
        for px, py in _wrap_offsets(x, y, c.w, c.h):
            m.ellipse(px, py, rx, ry, col)
    m.blur(0.9)
    c.paste(m)


def _blades(c: Canvas, base, rng, phase: int, n=26, light=None, dark=None):
    """Grass blades: short strokes that lean with the wind phase (0..3 = a passing wave)."""
    lean = (0.0, 1.6, 2.6, 1.2)[phase]
    light = light or mix(base, P["blade_light"], 0.55)
    dark = dark or mix(base, P["blade_dark"], 0.5)
    for i in range(n):
        x, y = rng.uniform(0, c.w), rng.uniform(0, c.h)
        h = rng.uniform(3.0, 6.0)
        col = light if rng.rand() < 0.55 else dark
        jit = rng.uniform(-0.6, 0.6)
        for px, py in _wrap_offsets(x, y, c.w, c.h):
            c.line([(px, py), (px + lean * 0.4, py - h * 0.55), (px + lean + jit, py - h)], rgba(col), 1.0)


def _wind_wave(c: Canvas, phase: int):
    """Brightness wave: the whole tile is lit a touch more at phase 1-2 (a gust passing) -> visible waves."""
    k = (1.0, 1.03, 1.06, 1.02)[phase]
    if k == 1.0:
        return
    a = c.array().astype(np.float32)
    a[..., :3] = np.clip(a[..., :3] * k, 0, 255)
    c.set_array(a)


# ----------------------------------------------------------------------------- tiles
def tile_grass(kind: str, phase: int, flowers=False, fl_seed=0) -> np.ndarray:
    base = P[kind]
    rng = _rng("grass:%s:%d" % (kind, fl_seed))  # same layout per variant so phases animate in place
    c = Canvas(T, T)
    c.rect(0, 0, T, T, rgba(base))
    _mottle(c, base, rng, 0.07)
    _blades(c, base, rng, phase, n=28 if kind != "dry" else 20)
    if flowers:
        frng = _rng("flowers:%d" % fl_seed)
        for _ in range(4):
            x, y = frng.uniform(3, T - 3), frng.uniform(3, T - 3)
            col = P["flower"][frng.randint(0, 4)]
            for a in range(5):
                ang = a * 72 + phase * 6
                c.ellipse(x + math.cos(math.radians(ang)) * 1.6, y + math.sin(math.radians(ang)) * 1.6, 1.2, 1.2,
                          rgba(col))
            c.ellipse(x, y, 0.9, 0.9, rgba((255, 235, 120)))
    _wind_wave(c, phase)
    return c.finish()[..., :3]


def tile_forest_floor(v: int) -> np.ndarray:
    base = P["forest_floor"]
    rng = _rng("floor:%d" % v)
    c = Canvas(T, T)
    c.rect(0, 0, T, T, rgba(base))
    _mottle(c, base, rng, 0.10, n=70)
    for _ in range(14):  # moss dots + fallen leaves
        x, y = rng.uniform(0, T), rng.uniform(0, T)
        c.ellipse(x, y, rng.uniform(1, 2), rng.uniform(0.8, 1.5), rgba(shade(base, rng.choice([0.85, 1.18]))))
    return c.finish()[..., :3]


def tile_water(kind: str, phase: int, edge_mask: int = 0, variant: int = 0) -> np.ndarray:
    base = P[kind] if kind in P else P["shallow"]
    rng = _rng("water:%s:%d" % (kind, variant))
    c = Canvas(T, T)
    c.rect(0, 0, T, T, rgba(base))
    _mottle(c, base, rng, 0.06, n=40, r=(3, 6))
    # ripples: thin bright arcs drifting right with phase; glints blink on phase 1/3
    rr = _rng("ripples:%s:%d" % (kind, variant))
    for i in range(4):
        x = (rr.uniform(0, T) + phase * 2.0) % T
        y = (rr.uniform(0, T) + phase * 0.6) % T
        w = rr.uniform(5, 10)
        col = mix(base, P["ripple"], 0.75 if kind == "shallow" else 0.55)
        for px, py in _wrap_offsets(x, y, T, T, margin=12):
            c.arc(px, py, w, 1.8, 205, 335, rgba(col, 220), 0.9)
    gr = _rng("glints:%s:%d" % (kind, variant))
    for i in range(2):
        if (i + phase + variant) % 4 in (1, 3):
            x, y = gr.uniform(2, T - 2), gr.uniform(2, T - 2)
            c.ellipse(x, y, 1.3, 0.8, rgba((255, 255, 255), 235))
            c.ellipse(x, y, 2.6, 1.4, rgba((255, 255, 255), 70))
    if edge_mask:
        # foam bands along the land side(s): N=1 E=2 S=4 W=8, wobbling with phase
        f = Canvas(T, T)
        foam = rgba(P["foam"], 235)
        pale = rgba(mix(base, P["foam"], 0.45), 255)
        wob = 0.8 if phase else -0.8
        for bit, pts in ((1, [(0, 0), (T, 0)]), (4, [(0, T), (T, T)]), (8, [(0, 0), (0, T)]), (2, [(T, 0), (T, T)])):
            if edge_mask & bit:
                (x0, y0), (x1, y1) = pts
                f.line([(x0, y0), (x1, y1)], pale, 5.0)
                f.line([(x0, y0), (x1, y1)], foam, 2.2)
                # scalloped foam bubbles just inside the edge
                for t in np.linspace(0.1, 0.9, 4):
                    px, py = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
                    nx, ny = (0, 1) if bit == 1 else (0, -1) if bit == 4 else (1, 0) if bit == 8 else (-1, 0)
                    f.ellipse(px + nx * (2.4 + wob), py + ny * (2.4 + wob), 1.6, 1.6, rgba(P["foam"], 170))
        f.blur(0.5)
        c.paste(f)
    return c.finish()[..., :3]


def tile_sand(v: int) -> np.ndarray:
    base = P["sand"]
    rng = _rng("sand:%d" % v)
    c = Canvas(T, T)
    c.rect(0, 0, T, T, rgba(base))
    _mottle(c, base, rng, 0.035, n=40, r=(2.5, 5))
    for _ in range(8):
        x, y = rng.uniform(0, T), rng.uniform(0, T)
        c.ellipse(x, y, rng.uniform(0.6, 1.4), rng.uniform(0.5, 1.0), rgba(P["sand_dark"], 180))
    for _ in range(3):  # dune ripples
        y = rng.uniform(4, T - 4)
        c.arc(rng.uniform(4, T - 4), y, rng.uniform(5, 9), 1.5, 190, 350, rgba(shade(base, 1.10)), 0.9)
    return c.finish()[..., :3]


def tile_hill(v: int, edge_s=False) -> np.ndarray:
    base = shade(P["grass"], 1.08)
    rng = _rng("hill:%d:%d" % (v, edge_s))
    c = Canvas(T, T)
    c.rect(0, 0, T, T, rgba(base))
    _mottle(c, base, rng, 0.08)
    _blades(c, base, rng, 0, n=12)
    for _ in range(4):  # rock speckle
        x, y = rng.uniform(2, T - 2), rng.uniform(2, T - 2)
        c.ellipse(x, y, rng.uniform(1.4, 2.6), rng.uniform(1.0, 1.8), rgba(P["rock"]), rgba(P["rock_dark"]), 0.5)
    if edge_s:
        # south slope: darker band with a lit lip at the top -> the hill reads as raised
        s = Canvas(T, T)
        s.rect(0, T * 0.5, T, T, rgba(shade(base, 0.62), 255))
        s.rect(0, T * 0.5, T, T * 0.5 + 2.5, rgba(shade(base, 1.35), 255))
        s.rect(0, T - 2.0, T, T, rgba(shade(base, 0.5), 255))
        for i in range(5):
            x = 3 + i * 6.5 + rng.uniform(-1, 1)
            s.line([(x, T * 0.62), (x + rng.uniform(-1, 1), T - 2)], rgba(shade(base, 0.6), 150), 1.2)
        s.blur(0.3)
        c.paste(s)
    return c.finish()[..., :3]


def tile_path(level: int, phase: int = 0) -> np.ndarray:
    """Trail wear on grass: level 1 = a few bare patches, 3 = a worn dirt band."""
    rng = _rng("path:%d" % level)
    g = tile_grass("grass", phase, fl_seed=0)
    c = Canvas(T, T)
    c.set_array(np.dstack([np.kron(g, np.ones((SS, SS, 1), np.uint8)), np.full((T * SS, T * SS), 255, np.uint8)]))
    d = Canvas(T, T)
    cover = (0.35, 0.6, 0.95)[level - 1]
    for _ in range(int(14 * cover) + 2):
        x, y = rng.uniform(2, T - 2), rng.uniform(T * 0.2, T * 0.8)
        rx, ry = rng.uniform(4, 9) * cover + 3, rng.uniform(2.5, 4.5) * cover + 1.5
        d.ellipse(x, y, rx, ry, rgba(P["dirt"], 230))
    d.blur(1.0)
    if level == 3:
        d.rect(0, T * 0.3, T, T * 0.7, rgba(P["dirt"], 240))
        d.blur(0.6)
    c.paste(d)
    if level >= 2:
        for _ in range(6):  # small stones & footprints
            x, y = rng.uniform(1, T - 1), rng.uniform(T * 0.32, T * 0.68)
            c.ellipse(x, y, rng.uniform(0.7, 1.3), rng.uniform(0.5, 0.9), rgba(P["dirt_dark"], 200))
    return c.finish()[..., :3]


def tile_farm(stage: str) -> np.ndarray:
    rng = _rng("farm:%s" % stage)
    c = Canvas(T, T)
    c.rect(0, 0, T, T, rgba(P["dirt"]))
    _mottle(c, P["dirt"], rng, 0.06)
    for i in range(4):  # furrows
        y = 4 + i * 8
        c.rect(0, y, T, y + 3.2, rgba(P["furrow"]))
        c.rect(0, y + 3.2, T, y + 4.0, rgba(shade(P["dirt"], 1.12)))
        if stage != "bare":
            col = P["crop_green"] if stage == "sprout" else P["crop_gold"]
            for j in range(5):
                x = 3.5 + j * 6.5 + rng.uniform(-1, 1)
                if stage == "sprout":
                    c.line([(x, y + 2.5), (x - 1.5, y - 1.5)], rgba(col), 1.0)
                    c.line([(x, y + 2.5), (x + 1.5, y - 1.8)], rgba(col), 1.0)
                else:
                    c.line([(x, y + 2.8), (x, y - 3.2)], rgba(shade(col, 0.8)), 1.1)
                    c.ellipse(x, y - 3.0, 1.6, 2.2, rgba(col), rgba(shade(col, 0.75)), 0.5)
    return c.finish()[..., :3]


# ----------------------------------------------------------------------------- props (RGBA sprites)
def prop_tree(size: int, sway: int) -> np.ndarray:
    """Round-canopy tree with depth: dark under-canopy, two lit lobes, a lighter crown, trunk shadow.
    size 0/1/2 -> ~34/44/56 px; sway 0/1 shifts the crown 1-2 px (wind)."""
    w = (34, 44, 56)[size]
    c = Canvas(w, w + 8)
    rng = _rng("tree:%d" % size)
    cx, cy = w / 2, w / 2 + 2
    R = w * 0.44
    dx = (0.0, 1.5 + 0.5 * size)[sway]
    # ground shadow (canopy shadow offset to the south-east as the sun is in the west/north-west)
    sh = Canvas(w, w + 8)
    sh.ellipse(cx + R * 0.25, cy + R * 0.95, R * 0.95, R * 0.42, (20, 40, 20, 120))
    sh.blur(1.6)
    c.paste(sh)
    c.rect(cx - 2.5, cy + R * 0.4, cx + 2.5, cy + R * 1.0, rgba(P["trunk"]))
    dark, mid, light = P["canopy_dark"], P["canopy"], P["canopy_light"]
    c.ellipse(cx + dx * 0.3, cy + R * 0.15, R, R * 0.92, rgba(dark))
    lobes = [(-0.42, -0.05, 0.62), (0.42, -0.02, 0.60), (0.0, -0.40, 0.66), (-0.1, 0.25, 0.55), (0.3, 0.32, 0.5)]
    for lx, ly, lr in lobes:
        c.ellipse(cx + lx * R + dx, cy + ly * R, lr * R, lr * R * 0.92, rgba(mid))
    for lx, ly, lr in lobes[:3]:
        c.ellipse(cx + lx * R + dx - lr * R * 0.15, cy + ly * R - lr * R * 0.2, lr * R * 0.55, lr * R * 0.45,
                  rgba(light, 190))
    # leaf texture: little scallops on the crown
    for _ in range(10 + size * 4):
        ang = rng.uniform(0, 6.283)
        rr = rng.uniform(0.2, 0.85) * R
        x, y = cx + math.cos(ang) * rr + dx, cy + math.sin(ang) * rr * 0.9 - R * 0.1
        c.arc(x, y, 2.2, 1.6, 200, 340, rgba(shade(mid, 1.25), 200), 0.9)
    return c.finish()


def prop_bush(v: int) -> np.ndarray:
    w = 24
    c = Canvas(w, w)
    rng = _rng("bush:%d" % v)
    sh = Canvas(w, w)
    sh.ellipse(w / 2 + 1, w * 0.78, w * 0.42, w * 0.16, (20, 40, 20, 110))
    sh.blur(1.2)
    c.paste(sh)
    for (lx, ly, lr) in [(-0.22, 0.05, 0.36), (0.22, 0.05, 0.36), (0.0, -0.15, 0.38)]:
        c.ellipse(w / 2 + lx * w, w * 0.55 + ly * w, lr * w, lr * w * 0.85, rgba(P["canopy"]), rgba(P["canopy_dark"]), 0.6)
        c.ellipse(w / 2 + lx * w - 1.5, w * 0.55 + ly * w - 2.5, lr * w * 0.5, lr * w * 0.4, rgba(P["canopy_light"], 190))
    if v == 1:
        for _ in range(5):
            x, y = rng.uniform(6, w - 6), rng.uniform(4, w - 8)
            c.ellipse(x, y, 1.3, 1.3, rgba((220, 60, 80)))
    return c.finish()


def prop_rock(v: int) -> np.ndarray:
    w = 22
    c = Canvas(w, w)
    rng = _rng("rock:%d" % v)
    sh = Canvas(w, w)
    sh.ellipse(w / 2 + 1, w * 0.75, w * 0.42, w * 0.18, (20, 30, 20, 110))
    sh.blur(1.1)
    c.paste(sh)
    pts = []
    n = 7
    for i in range(n):
        a = i / n * 6.283
        r = w * rng.uniform(0.30, 0.42)
        pts.append((w / 2 + math.cos(a) * r, w * 0.55 + math.sin(a) * r * 0.75))
    c.polygon(pts, rgba(P["rock"]), rgba(P["rock_dark"]), 0.8)
    c.polygon([(w / 2 - 4, w * 0.4), (w / 2 + 2, w * 0.33), (w / 2 + 5, w * 0.45), (w / 2 - 1, w * 0.5)],
              rgba(shade(P["rock"], 1.25)))
    return c.finish()


def prop_flowers(v: int) -> np.ndarray:
    w = 20
    c = Canvas(w, w)
    rng = _rng("flowers-prop:%d" % v)
    for _ in range(5):
        x, y = rng.uniform(3, w - 3), rng.uniform(4, w - 3)
        c.line([(x, y + 3), (x, y)], rgba(P["blade_dark"]), 1.0)
        col = P["flower"][rng.randint(0, 4)]
        for a in range(5):
            ang = a * 72
            c.ellipse(x + math.cos(math.radians(ang)) * 1.7, y + math.sin(math.radians(ang)) * 1.7, 1.3, 1.3, rgba(col))
        c.ellipse(x, y, 0.9, 0.9, rgba((255, 235, 120)))
    return c.finish()


def prop_reeds(sway: int) -> np.ndarray:
    w = 22
    c = Canvas(w, w + 6)
    rng = _rng("reeds")
    lean = (0, 2.2)[sway]
    for i in range(7):
        x = 3 + i * 2.6 + rng.uniform(-0.5, 0.5)
        h = rng.uniform(12, 20)
        c.line([(x, w + 4), (x + lean * 0.5, w + 4 - h * 0.6), (x + lean, w + 4 - h)], rgba(shade(P["lush"], 0.9)), 1.2)
        if i % 3 == 0:
            c.ellipse(x + lean, w + 4 - h - 1, 1.2, 3.0, rgba(P["dirt_dark"]))
    return c.finish()


def props() -> Dict[str, np.ndarray]:
    out = {}
    for s in range(3):
        for sw in range(2):
            out["tree.%d.s%d" % (s, sw)] = prop_tree(s, sw)
    for v in range(2):
        out["bush.%d" % v] = prop_bush(v)
        out["rock.%d" % v] = prop_rock(v)
        out["flowers.%d" % v] = prop_flowers(v)
    for sw in range(2):
        out["reeds.s%d" % sw] = prop_reeds(sw)
    return out


# ----------------------------------------------------------------------------- atlas
def build_atlas() -> Tuple[np.ndarray, Dict[str, int]]:
    tiles = []
    index: Dict[str, int] = {}

    def add(name, arr):
        index[name] = len(tiles)
        tiles.append(arr)

    for kind in ("meadow", "grass", "lush", "dry"):
        for ph in range(4):
            add("grass.%s.w%d" % (kind, ph), tile_grass(kind, ph))
    for v in range(2):
        for ph in range(4):
            add("grass.flowers.%d.w%d" % (v, ph), tile_grass("meadow", ph, flowers=True, fl_seed=v + 1))
    for v in range(2):
        add("forest.floor.%d" % v, tile_forest_floor(v))
    for kind in ("deep", "shallow"):
        for v in range(2):
            for ph in range(4):
                add("water.%s.%d.r%d" % (kind, v, ph), tile_water(kind, ph, variant=v))
    for m in range(16):
        for ph in range(2):
            add("water.edge.m%d.r%d" % (m, ph), tile_water("shallow", ph * 2, edge_mask=m))
    for v in range(2):
        add("shore.sand.%d" % v, tile_sand(v))
    for v in range(2):
        add("hill.top.%d" % v, tile_hill(v))
    add("hill.edge.s", tile_hill(0, edge_s=True))
    for lv in (1, 2, 3):
        add("path.grass.%d" % lv, tile_path(lv))
    for st in ("bare", "sprout", "ripe"):
        add("farm.%s" % st, tile_farm(st))
    atlas = np.stack(tiles).astype(np.uint8)
    return atlas, index


def light_atlas(atlas: np.ndarray, tint=(1.0, 1.0, 1.0)) -> np.ndarray:
    return np.clip(atlas.astype(np.float32) * np.array(tint, np.float32)[None, None, None, :], 0, 255).astype(np.uint8)


def compose(atlas: np.ndarray, ids: np.ndarray) -> np.ndarray:
    """ids: (rows, cols) int -> RGB (rows*T, cols*T, 3). One gather + one transpose."""
    r, c = ids.shape
    g = atlas[ids]  # (r, c, T, T, 3)
    return g.transpose(0, 2, 1, 3, 4).reshape(r * T, c * T, 3)


def atlas_image(path: str) -> str:
    from PIL import Image, ImageDraw, ImageFont
    from common import alpha_blit
    atlas, index = build_atlas()
    pr = props()
    cols = 16
    rows = (len(atlas) + cols - 1) // cols
    cell = T + 6
    prop_h = 80
    W, H = cols * cell + 12, rows * cell + 40 + prop_h * 2 + 30
    img = np.full((H, W, 3), (46, 52, 44), np.uint8)
    for i, t in enumerate(atlas):
        x, y = 6 + (i % cols) * cell, 30 + (i // cols) * cell
        img[y:y + T, x:x + T] = t
    y0 = 30 + rows * cell + 24
    x = 6
    for k, s in pr.items():
        alpha_blit(img, s, x, y0 + (prop_h - s.shape[0]))
        x += s.shape[1] + 10
        if x > W - 70:
            x = 6
            y0 += prop_h + 6
    pil = Image.fromarray(img)
    d = ImageDraw.Draw(pil)
    f = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf", 15)
    d.text((6, 6), "studio-b tile atlas: %d tiles x %dpx (grass wind x4, water ripple x4, foam edges x16x2, hills, "
            "paths, farm) + props" % (len(atlas), T), font=f, fill=(235, 232, 220))
    d.text((6, 30 + rows * cell + 4), "props: trees (3 sizes x 2 sway), bushes, rocks, flower clumps, reeds",
           font=f, fill=(235, 232, 220))
    pil.save(path)
    return path


if __name__ == "__main__":
    import time
    t0 = time.perf_counter()
    out = atlas_image(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tile_atlas.png"))
    print("wrote", out, "in %.2fs" % (time.perf_counter() - t0))
    atlas, index = build_atlas()
    ids = np.random.RandomState(1).randint(0, len(atlas), (17, 40))
    t0 = time.perf_counter()
    for _ in range(50):
        img = compose(atlas, ids)
    print("compose 40x17: %.2f ms" % ((time.perf_counter() - t0) / 50 * 1000))
