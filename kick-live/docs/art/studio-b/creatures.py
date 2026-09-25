"""creatures.py - studio-b pips: glossy pebble-bodied creatures grown from a username.

Silhouette language ("things that grow"): every pip is a compact, glossy pebble body with a SPROUT
growing from the crown (leaf / twin-leaf / fern curl / grass tuft / bud / twig), optional side motifs
(nubs / fins / flaps), a back tuft or curl, two peeking feet and big glazed eyes low on the face.
Hue, shape, sprout, ears, tail, pattern, eye size and blush are all deterministic from the name.

    sheet(name)                  -> {tier: {frame: RGBA np.uint8 (box x box x 4)}}
    render(name, tier, frame)    -> one RGBA frame (cached)
    FRAMES                       = idle0 idle1 walk0 walk1 hop blink speak sleep emote0 emote1
    TIERS                        = 0 sprig (36 px), 1 pip (48 px), 2 grown (58 px), 3 elder (70 px)
    sheet_image(names, path)     -> writes a contact sheet PNG

    python creatures.py [name ...]   # writes creature_sheet.png next to this file

Python 3.9, numpy + pillow only. Deterministic. No external assets.
"""
from __future__ import annotations

import math
import os
import sys
from typing import Dict, List, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SS, Canvas, Genes, RGB, hls, mix, rgba, shade, soft_shadow  # noqa: E402

FRAMES = ["idle0", "idle1", "walk0", "walk1", "hop", "blink", "speak", "sleep", "emote0", "emote1"]
TIERS = [0, 1, 2, 3]
TIER_NAMES = {0: "sprig", 1: "pip", 2: "grown", 3: "elder"}
TIER_SCALE = {0: 0.74, 1: 1.0, 2: 1.2, 3: 1.45}
BASE_BOX = 48

SPROUTS = ["leaf", "twinleaf", "curl", "tuft", "bud", "twig"]
EARS = ["none", "nubs", "fins", "flaps"]
TAILS = ["none", "tuft", "curl"]
PATTERNS = ["plain", "belly", "spots", "saddle", "stripes"]
SHAPES = ["pebble", "drop", "bean", "pear"]

INK = (36, 30, 40)
EYE_WHITE = (252, 250, 244)


# ----------------------------------------------------------------------------- genome
def genome(name: str) -> Dict:
    g = Genes(name, "pip-v2")
    # hue: 24 stops around the wheel so two names rarely collide, nudged away from mud
    hue = (g.pick(24) * 15 + g.pick(8)) % 360
    light = 0.50 + 0.12 * g.unit()
    sat = 0.42 + 0.26 * g.unit()
    body = hls(hue, light, sat)
    acc_kind = g.pick(4)
    acc_shift = (35, -35, 150, 185)[acc_kind]
    accent = hls(hue + acc_shift, 0.52, 0.62)
    return {
        "name": (name or "").strip().lower(),
        "hue": hue,
        "body": body,
        "dark": shade(body, 0.62),
        "light": shade(body, 1.30),
        "accent": accent,
        "accent_dark": shade(accent, 0.62),
        "shape": SHAPES[g.pick(4)],
        "sprout": SPROUTS[g.pick(6)],
        "ears": EARS[g.pick(4)],
        "tail": TAILS[g.pick(3)],
        "pattern": PATTERNS[g.pick(5)],
        "eye": (3.8, 4.4, 5.0)[g.pick(3)],
        "eye_gap": 0.40 + 0.16 * g.unit(),
        "blush": g.unit() < 0.65,
        "pupil_tint": hls(hue + 180, 0.35, 0.5),
        "hand": g.pick(2),  # which side the sprout leans
    }


# ----------------------------------------------------------------------------- frame recipe
def _pose(frame: str) -> Dict:
    p = dict(sx=1.0, sy=1.0, dy=0.0, feet="both", eyes="open", mouth="smile", sway=0.0, lift=0.0,
             look=0.0, fx=0)
    if frame == "idle1":
        p.update(sx=1.04, sy=0.96, dy=1.0, sway=1.0, look=0.6)
    elif frame == "walk0":
        p.update(sx=0.96, sy=1.04, dy=-1.5, feet="left", sway=-2.0, look=-0.5)
    elif frame == "walk1":
        p.update(sx=0.96, sy=1.04, dy=-1.5, feet="right", sway=2.0, look=0.5)
    elif frame == "hop":
        p.update(sx=0.90, sy=1.14, dy=-2.0, feet="tuck", lift=7.0, mouth="open", sway=-1.5, eyes="wide")
    elif frame == "blink":
        p.update(eyes="closed")
    elif frame == "speak":
        p.update(sx=1.02, sy=0.98, dy=0.5, mouth="talk", fx=1)
    elif frame == "sleep":
        p.update(sx=1.08, sy=0.86, dy=3.0, feet="none", eyes="sleep", mouth="rest", sway=2.2, fx=2)
    elif frame == "emote0":
        p.update(sx=1.03, sy=0.99, eyes="happy", mouth="grin", fx=3, sway=-0.8)
    elif frame == "emote1":
        p.update(sx=0.98, sy=1.04, dy=-1.0, eyes="wide", mouth="o", fx=4, sway=1.0)
    return p


# ----------------------------------------------------------------------------- shading
def _gloss(c: Canvas, mask: np.ndarray, strength=0.42, spec=(0.34, 0.30, 0.20), rim=0.16) -> None:
    """Glossy convex shading over every pixel in `mask` (SS resolution)."""
    a = c.array().astype(np.float32)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    gx = (xs - x0) / w - 0.5
    gy = (ys - y0) / h - 0.5
    grad = 1.0 + strength * (-(gx * 0.55 + gy * 0.95)) * 1.4
    grad = np.clip(grad, 1 - strength, 1 + strength * 0.6)
    dx = (xs - x0) / w - spec[0]
    dy = (ys - y0) / h - spec[1]
    d = np.sqrt(dx * dx * 1.2 + dy * dy)
    sp = np.clip(1 - d / spec[2], 0, 1) ** 2.2 * 0.75
    rim_v = np.clip((gx * 0.7 + gy) - 0.42, 0, 1) * rim * 2.2
    col = a[ys, xs, :3] * grad[:, None]
    col = col + (255 - col) * sp[:, None]
    col = col + (255 - col) * rim_v[:, None]
    a[ys, xs, :3] = np.clip(col, 0, 255)
    c.set_array(a)


def _body_mask(shape: str, cx, cy, rx, ry) -> Canvas:
    """Paint the body silhouette (opaque white) as a union of ellipses -> mask canvas."""
    m = Canvas(BASE_BOX * 2, BASE_BOX * 2)  # generous, we only read the alpha
    W = (255, 255, 255, 255)
    if shape == "pebble":
        m.ellipse(cx, cy, rx, ry, W)
    elif shape == "drop":
        m.ellipse(cx, cy + ry * 0.15, rx, ry * 0.88, W)
        m.polygon([(cx - rx * 0.92, cy + ry * 0.1), (cx - rx * 0.3, cy - ry * 0.95), (cx, cy - ry * 1.25),
                   (cx + rx * 0.3, cy - ry * 0.95), (cx + rx * 0.92, cy + ry * 0.1)], W)
    elif shape == "bean":
        m.ellipse(cx, cy + ry * 0.05, rx * 1.12, ry * 0.85, W)
        m.ellipse(cx - rx * 0.52, cy - ry * 0.28, rx * 0.6, ry * 0.72, W)
        m.ellipse(cx + rx * 0.52, cy - ry * 0.28, rx * 0.6, ry * 0.72, W)
    else:  # pear
        m.ellipse(cx, cy + ry * 0.25, rx * 1.05, ry * 0.78, W)
        m.ellipse(cx, cy - ry * 0.45, rx * 0.68, ry * 0.62, W)
        m.polygon([(cx - rx * 0.68, cy - ry * 0.45), (cx + rx * 0.68, cy - ry * 0.45), (cx + rx * 1.0, cy + ry * 0.3),
                   (cx - rx * 1.0, cy + ry * 0.3)], W)
    return m


# ----------------------------------------------------------------------------- parts
def _sprout(c: Canvas, g: Dict, x, y, k, sway, tier, droop=False):
    """Crown growth at (x,y) on the top rim. k = tier scale. sway in px (base)."""
    acc, accd = rgba(g["accent"]), rgba(g["accent_dark"])
    kind = g["sprout"]
    side = 1 if g["hand"] else -1
    lw = 1.9 * k
    if droop:
        sway += 4.5 * side
    top = y - (7.5 if not droop else 4.0) * k
    stem = [(x, y + 1.5 * k), (x + sway * 0.4 * k, y - 3 * k), (x + sway * k, top)]
    c.line(stem, accd, lw)
    tx, ty = stem[-1]

    def leaf(bx, by, dxl, dyl, wd):  # pointed leaf polygon from (bx,by) to tip (bx+dxl, by+dyl)
        mx, my = bx + dxl * 0.5, by + dyl * 0.5
        nx, ny = -dyl, dxl
        n = math.hypot(nx, ny) or 1
        nx, ny = nx / n * wd, ny / n * wd
        c.polygon([(bx, by), (mx + nx, my + ny), (bx + dxl, by + dyl), (mx - nx, my - ny)], acc, accd, 0.9 * k)
        c.line([(bx, by), (bx + dxl * 0.8, by + dyl * 0.8)], accd, 0.7 * k)

    if kind == "leaf":
        leaf(tx, ty, (7.0 * side + sway * 0.6) * k, -6.0 * k, 3.6 * k)
        if tier >= 2:
            leaf(tx - sway * 0.2 * k, ty + 2.5 * k, (-6 * side) * k, -4.2 * k, 2.8 * k)
    elif kind == "twinleaf":
        leaf(tx, ty, (6.5 + sway * 0.4) * k, -5.0 * k, 3.2 * k)
        leaf(tx, ty, (-6.5 + sway * 0.4) * k, -5.0 * k, 3.2 * k)
        if tier >= 2:
            leaf(tx, ty, sway * 0.5 * k, -7.5 * k, 2.8 * k)
    elif kind == "curl":
        r = (4.4 + 0.8 * (tier >= 2)) * k
        cx0 = tx + side * r
        c.arc(cx0, ty - r * 0.2, r, r, 90 if side > 0 else -90, 400 if side > 0 else 220, acc, lw * 1.25)
        c.ellipse(cx0 + side * r * 0.1, ty - r * 0.2, 1.6 * k, 1.6 * k, acc)
        if tier >= 3:
            c.arc(tx - side * r * 0.9, ty + 1.5 * k, r * 0.6, r * 0.6, -90 if side > 0 else 90, 220 if side > 0 else 400,
                  acc, lw)
    elif kind == "tuft":
        n = 3 + (tier >= 2)
        for i in range(n):
            ang = -90 + (i - (n - 1) / 2) * 34 + sway * 3
            L = (8.5 - 1.0 * abs(i - (n - 1) / 2)) * k
            ex, ey = tx + math.cos(math.radians(ang)) * L, ty + math.sin(math.radians(ang)) * L
            c.polygon([(tx - 1.7 * k, ty + 1 * k), (ex, ey), (tx + 1.7 * k, ty + 1 * k)], acc, accd, 0.7 * k)
    elif kind == "bud":
        r = (3.6 + 0.6 * (tier >= 2)) * k
        c.ellipse(tx, ty - r * 0.6, r, r, acc, accd, 0.8 * k)
        c.ellipse(tx - r * 0.35, ty - r * 0.95, r * 0.36, r * 0.3, (255, 255, 255, 210))
        if tier >= 3:
            c.ellipse(tx + side * 3.4 * k, ty + 1.2 * k, r * 0.6, r * 0.6, acc, accd, 0.5 * k)
            c.ellipse(tx - side * 3.0 * k, ty + 0.8 * k, r * 0.55, r * 0.55, acc, accd, 0.5 * k)
    else:  # twig
        c.line([(tx, ty), (tx + 4.5 * side * k, ty - 4.5 * k)], accd, lw)
        c.line([(tx + 0.5 * side * k, ty - 1.5 * k), (tx - 3.8 * side * k, ty - 4.4 * k)], accd, lw * 0.9)
        c.ellipse(tx + 4.5 * side * k, ty - 4.5 * k, 1.9 * k, 1.9 * k, acc, accd, 0.6 * k)
        c.ellipse(tx - 3.8 * side * k, ty - 4.4 * k, 1.6 * k, 1.6 * k, acc, accd, 0.6 * k)
        if tier >= 2:
            c.line([(tx - 0.3 * side * k, ty - 4 * k), (tx + 0.3 * side * k, ty - 8.5 * k)], accd, lw * 0.8)
            c.ellipse(tx + 0.3 * side * k, ty - 8.5 * k, 1.7 * k, 1.7 * k, acc, accd, 0.6 * k)


def _ears(c: Canvas, g: Dict, cx, cy, rx, ry, k, front: bool):
    kind = g["ears"]
    if kind == "none":
        return
    body, dark, acc = rgba(g["body"]), rgba(g["dark"]), rgba(g["accent"])
    ey = cy - ry * 0.28
    for s in (-1, 1):
        ex = cx + s * rx * 0.92
        if kind == "nubs" and not front:
            c.ellipse(ex + s * 1.0 * k, ey - 1.0 * k, 4.2 * k, 4.4 * k, body, dark, 0.8 * k)
            c.ellipse(ex + s * 1.3 * k, ey - 1.0 * k, 2.0 * k, 2.2 * k, acc)
        elif kind == "fins" and not front:
            c.polygon([(ex - s * 3.0 * k, ey + 4.5 * k), (ex + s * 7.5 * k, ey - 8.5 * k), (ex - s * 1.0 * k, ey - 3.5 * k)],
                      body, dark, 0.8 * k)
            c.polygon([(ex + s * 0.2 * k, ey + 2.0 * k), (ex + s * 5.0 * k, ey - 5.8 * k), (ex + s * 0.3 * k, ey - 2.2 * k)],
                      acc)
        elif kind == "flaps" and front:
            c.ellipse(ex + s * 2.2 * k, ey + 6.0 * k, 3.2 * k, 6.5 * k, body, dark, 0.8 * k)
            c.ellipse(ex + s * 2.2 * k, ey + 7.0 * k, 1.5 * k, 3.8 * k, acc)


def _tail(c: Canvas, g: Dict, cx, cy, rx, ry, k, sway):
    kind = g["tail"]
    if kind == "none":
        return
    body, dark, acc = rgba(g["body"]), rgba(g["dark"]), rgba(g["accent"])
    side = -1 if g["hand"] else 1
    bx, by = cx + side * rx * 0.55, cy - ry * 0.72
    if kind == "tuft":
        tip = (bx + side * (7.0 + sway * 0.5) * k, by - 7.5 * k)
        c.polygon([(bx - side * 3.5 * k, by + 2.5 * k), tip, (bx + side * 3.5 * k, by + 3.0 * k)], body, dark, 0.8 * k)
        c.ellipse(tip[0], tip[1], 2.4 * k, 2.4 * k, acc, dark, 0.6 * k)
    else:
        r = 5.0 * k
        c.arc(bx + side * r * 0.9, by - r * 0.6, r, r, 180 if side > 0 else 0, 360 + 30 if side > 0 else 210, dark,
              2.2 * k)
        c.ellipse(bx + side * r * 1.8, by - r * 0.6 + r * 0.1, 2.2 * k, 2.2 * k, acc, dark, 0.6 * k)


def _feet(c: Canvas, g: Dict, cx, cy, rx, ry, k, mode):
    if mode in ("none", "tuck"):
        return
    dark = rgba(shade(g["body"], 0.72))
    line = rgba(g["dark"])
    fy = cy + ry * 0.86
    off = {"both": (0, 0), "left": (2.2 * k, -2.0 * k), "right": (-2.0 * k, 2.2 * k)}[mode]
    c.ellipse(cx - rx * 0.45 - off[0] * 0.3, fy + off[0] * 0.75, 4.0 * k, 2.6 * k, dark, line, 0.7 * k)
    c.ellipse(cx + rx * 0.45 + off[1] * 0.3, fy + off[1] * 0.75, 4.0 * k, 2.6 * k, dark, line, 0.7 * k)


def _face(c: Canvas, g: Dict, cx, cy, rx, ry, k, pose):
    er = g["eye"] * k
    gap = rx * g["eye_gap"]
    ey = cy + ry * 0.10
    look = pose["look"] * k
    mode = pose["eyes"]
    ink = rgba(INK)
    for s in (-1, 1):
        ex = cx + s * gap
        if mode == "closed":
            c.arc(ex, ey - er * 0.2, er * 0.95, er * 0.8, 15, 165, ink, 1.2 * k)
        elif mode == "sleep":
            c.arc(ex, ey - er * 0.5, er * 0.95, er * 0.7, 20, 160, ink, 1.2 * k)
        elif mode == "happy":
            c.arc(ex, ey + er * 0.35, er * 0.95, er * 0.9, 200, 340, ink, 1.35 * k)
        else:
            scale = 1.15 if mode == "wide" else 1.0
            r = er * scale
            c.ellipse(ex, ey, r * 1.02, r * 1.10, rgba(EYE_WHITE))
            c.ellipse(ex + look * 0.35, ey + 0.15 * k, r * 0.86, r * 0.94, rgba(g["pupil_tint"]))
            c.ellipse(ex + look * 0.45, ey + 0.25 * k, r * 0.66, r * 0.74, ink)
            c.ellipse(ex - r * 0.30 + look * 0.2, ey - r * 0.36, r * 0.30, r * 0.28, (255, 255, 255, 235))
            c.ellipse(ex + r * 0.30 + look * 0.2, ey + r * 0.38, r * 0.14, r * 0.13, (255, 255, 255, 170))
    # blush
    if g["blush"] or mode == "happy":
        bl = rgba(mix(g["body"], (255, 120, 140), 0.55), 150)
        for s in (-1, 1):
            c.ellipse(cx + s * (gap + er * 1.05), ey + er * 0.85, er * 0.62, er * 0.36, bl)
    # mouth
    my = ey + er * 1.55
    m = pose["mouth"]
    if m == "smile":
        c.arc(cx, my - 1.2 * k, 2.3 * k, 2.0 * k, 25, 155, ink, 1.0 * k)
    elif m == "rest":
        c.arc(cx, my - 0.5 * k, 1.8 * k, 1.0 * k, 25, 155, ink, 0.9 * k)
    elif m == "open":
        c.ellipse(cx, my, 2.2 * k, 2.4 * k, ink)
        c.ellipse(cx, my + 1.1 * k, 1.3 * k, 1.0 * k, (235, 110, 120, 255))
    elif m == "talk":
        c.ellipse(cx, my, 2.6 * k, 1.9 * k, ink)
        c.ellipse(cx, my + 0.9 * k, 1.5 * k, 0.8 * k, (235, 110, 120, 255))
    elif m == "grin":
        c.polygon([(cx - 3.4 * k, my - 1.2 * k), (cx + 3.4 * k, my - 1.2 * k), (cx, my + 2.4 * k)], ink)
        c.ellipse(cx, my + 1.0 * k, 1.6 * k, 0.9 * k, (235, 110, 120, 255))
    elif m == "o":
        c.ellipse(cx, my, 1.6 * k, 1.8 * k, ink)


def _pattern(c: Canvas, g: Dict, cx, cy, rx, ry, k, mask_ss: np.ndarray):
    kind = g["pattern"]
    if kind == "plain":
        return
    p = Canvas(c.w, c.h)
    if kind == "belly":
        p.ellipse(cx, cy + ry * 0.42, rx * 0.62, ry * 0.5, rgba(g["light"], 210))
    elif kind == "spots":
        rng = Genes(g["name"], "spots").rng()
        col = rgba(g["light"], 210)
        for _ in range(4):
            sx = cx + (rng.uniform(-0.75, 0.75)) * rx
            sy = cy + (rng.uniform(-0.85, -0.15)) * ry
            r = rng.uniform(1.7, 2.6) * k
            p.ellipse(sx, sy, r, r * 0.9, col)
    elif kind == "saddle":
        p.ellipse(cx, cy - ry * 0.55, rx * 0.95, ry * 0.62, rgba(g["accent"], 200))
    elif kind == "stripes":
        col = rgba(g["dark"], 220)
        for i in range(3):
            yy = cy - ry * (0.78 - i * 0.22)
            p.arc(cx, yy + ry * 0.55, rx * (0.85 - i * 0.05), ry * 0.6, 215, 325, col, 1.6 * k)
    a = p.array()
    a[..., 3] = (a[..., 3].astype(np.uint16) * mask_ss // 255).astype(np.uint8)
    p.set_array(a)
    c.paste(p)


def _fx(c: Canvas, g: Dict, cx, cy, rx, ry, k, kind: int):
    acc = rgba(g["accent"])
    if kind == 1:  # speak: two chirp arcs beside the mouth
        side = 1 if g["hand"] else -1
        for i in range(2):
            r = (2.6 + i * 2.4) * k
            c.arc(cx + side * (rx * 1.05 + 1 * k), cy + ry * 0.25, r, r, -45 if side > 0 else 135,
                  45 if side > 0 else 225, acc, 1.1 * k)
    elif kind == 2:  # sleep: rising bubbles
        side = -1 if g["hand"] else 1
        for i, (dx, dy, r, al) in enumerate([(4, -4, 1.4, 230), (7.5, -9, 2.0, 190), (12, -15, 2.7, 140)]):
            c.ellipse(cx + side * (rx * 0.6 + dx * k), cy - ry * 0.5 + dy * k, r * k, r * k, rgba(g["accent"], al),
                      rgba(g["accent_dark"], al), 0.5 * k)
    elif kind == 3:  # joy: sparkles
        for (dx, dy, s) in [(-rx * 1.15, -ry * 0.95, 3.2), (rx * 1.2, -ry * 0.55, 2.4), (rx * 0.95, -ry * 1.25, 1.8)]:
            x, y, s = cx + dx, cy + dy, s * k
            c.polygon([(x, y - s), (x + s * 0.3, y - s * 0.3), (x + s, y), (x + s * 0.3, y + s * 0.3), (x, y + s),
                       (x - s * 0.3, y + s * 0.3), (x - s, y), (x - s * 0.3, y - s * 0.3)], (255, 240, 170, 255))
    elif kind == 4:  # wow: two floating rings
        side = 1 if g["hand"] else -1
        c.ellipse(cx + side * rx * 1.05, cy - ry * 1.15, 2.4 * k, 2.4 * k, None, acc, 1.0 * k)
        c.ellipse(cx + side * rx * 1.35, cy - ry * 1.55, 1.4 * k, 1.4 * k, None, acc, 0.9 * k)


# ----------------------------------------------------------------------------- render
_CACHE: Dict[Tuple[str, int, str], np.ndarray] = {}


def box_size(tier: int) -> int:
    return int(round(BASE_BOX * TIER_SCALE[tier]))


def render(name: str, tier: int = 1, frame: str = "idle0") -> np.ndarray:
    key = ((name or "").strip().lower(), tier, frame)
    if key in _CACHE:
        return _CACHE[key]
    g = genome(name)
    pose = _pose(frame)
    k = TIER_SCALE[tier]
    box = box_size(tier)
    c = Canvas(box, box)
    # body geometry (base units * k)
    rx0, ry0 = {"pebble": (14.5, 12.5), "drop": (13.5, 13.5), "bean": (15.5, 11.5), "pear": (14.0, 13.0)}[g["shape"]]
    rx, ry = rx0 * k * pose["sx"], ry0 * k * pose["sy"]
    cx = box / 2.0
    ground = box - 4.5 * k                      # where the feet touch
    cy = ground - ry * 0.9 - pose["lift"] * k + pose["dy"] * k
    # shadow (stays on the ground; shrinks when airborne)
    sh = 1.0 - 0.35 * (pose["lift"] > 0)
    soft_shadow(c, cx, ground + 1.5 * k, rx * 0.9 * sh, 3.2 * k * sh, alpha=95, blur=1.1 * k)
    # back parts
    _tail(c, g, cx, cy, rx, ry, k, pose["sway"])
    _ears(c, g, cx, cy, rx, ry, k, front=False)
    _feet(c, g, cx, cy, rx, ry, k, pose["feet"])
    # body: silhouette -> fill -> outline -> pattern -> gloss
    m = _body_mask(g["shape"], cx, cy, rx, ry)
    mask = m.array()[: box * SS, : box * SS, 3]
    bodyc = Canvas(box, box)
    arr = np.zeros((box * SS, box * SS, 4), np.uint8)
    arr[..., 0], arr[..., 1], arr[..., 2] = g["body"]
    arr[..., 3] = mask
    bodyc.set_array(arr)
    _pattern(bodyc, g, cx, cy, rx, ry, k, mask)
    _gloss(bodyc, mask > 0, strength=0.40, spec=(0.33, 0.24, 0.24), rim=0.15)
    # soft outline: dilate mask by ~1px and paint dark ring underneath
    ring = Canvas(box, box)
    from PIL import Image, ImageFilter  # local import keeps module header tidy
    mimg = Image.fromarray(mask).filter(ImageFilter.MaxFilter(2 * max(2, int(round(0.9 * k * SS))) + 1))
    ra = np.zeros_like(arr)
    ra[..., 0], ra[..., 1], ra[..., 2] = g["dark"]
    ra[..., 3] = np.array(mimg)
    ring.set_array(ra)
    c.paste(ring)
    c.paste(bodyc)
    # front parts
    _ears(c, g, cx, cy, rx, ry, k, front=True)
    _sprout(c, g, cx + (0.12 * rx if g["shape"] != "drop" else 0), cy - ry * (0.98 if g["shape"] != "drop" else 1.0),
            k, pose["sway"], tier, droop=(frame == "sleep"))
    _face(c, g, cx, cy, rx, ry, k, pose)
    _fx(c, g, cx, cy, rx, ry, k, pose["fx"])
    out = c.finish()
    _CACHE[key] = out
    return out


def sheet(name: str, tiers: List[int] = None) -> Dict[int, Dict[str, np.ndarray]]:
    return {t: {f: render(name, t, f) for f in FRAMES} for t in (tiers or TIERS)}


def describe(name: str) -> str:
    g = genome(name)
    return "%s: %s body, %s sprout, ears %s, tail %s, %s, hue %d" % (
        g["name"], g["shape"], g["sprout"], g["ears"], g["tail"], g["pattern"], g["hue"])


# ----------------------------------------------------------------------------- contact sheet
def sheet_image(names: List[str], path: str, bg=(78, 124, 70)) -> str:
    from PIL import Image, ImageDraw, ImageFont
    from common import alpha_blit
    cell = 74
    label_w = 150
    tiers_w = sum(box_size(t) + 10 for t in TIERS) + 16
    W = label_w + len(FRAMES) * cell + tiers_w
    H = 24 + len(names) * (cell + 6) + 8
    img = np.zeros((H, W, 3), np.uint8)
    img[...] = bg
    # subtle checker so alpha edges are judged against the land colour
    yy, xx = np.mgrid[0:H, 0:W]
    img[((yy // 8 + xx // 8) % 2) == 0] = tuple(int(v * 0.94) for v in bg)
    for r, n in enumerate(names):
        y0 = 24 + r * (cell + 6)
        for i, f in enumerate(FRAMES):
            s = render(n, 1, f)
            alpha_blit(img, s, label_w + i * cell + (cell - s.shape[1]) // 2, y0 + (cell - s.shape[0]) // 2)
        x = label_w + len(FRAMES) * cell + 8
        for t in TIERS:
            s = render(n, t, "idle0")
            alpha_blit(img, s, x, y0 + cell - s.shape[0] - 2)
            x += s.shape[1] + 10
    pil = Image.fromarray(img)
    d = ImageDraw.Draw(pil)
    f = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf", 15)
    for i, fr in enumerate(FRAMES):
        d.text((label_w + i * cell + 8, 4), fr, font=f, fill=(240, 236, 220))
    d.text((label_w + len(FRAMES) * cell + 10, 4), "growth: sprig  pip  grown  elder", font=f, fill=(240, 236, 220))
    for r, n in enumerate(names):
        y0 = 24 + r * (cell + 6)
        d.text((8, y0 + 8), "@" + n, font=f, fill=(255, 250, 235))
        g = genome(n)
        d.text((8, y0 + 28), g["shape"] + " / " + g["sprout"], font=f, fill=(215, 225, 205))
        d.text((8, y0 + 46), g["ears"] + " / " + g["tail"] + " / " + g["pattern"], font=f, fill=(215, 225, 205))
    pil.save(path)
    return path


EXAMPLES = ["kai_dnb", "mira_9", "luca_99", "xXvtobiXx", "noor.wav", "sami.exe", "zed_ttv", "lowkeyjord"]

if __name__ == "__main__":
    names = sys.argv[1:] or EXAMPLES
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "creature_sheet.png")
    import time
    t0 = time.perf_counter()
    p = sheet_image(names, out)
    dt = time.perf_counter() - t0
    for n in names:
        print(describe(n))
    print("wrote", p, "in %.2fs (%d frames)" % (dt, len(names) * (len(FRAMES) + len(TIERS) - 1)))
