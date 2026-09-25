"""buildings.py - SETTLEMENT building kit (studio-a).

Buildings are composed from PARTS in the builder's name colour (the same hue the creature wears, so a
hut and its owner match at a glance): roof = builder primary, trim/banner = builder secondary, walls =
one of three warm materials picked by the name hash. Top-down 3/4 camera: the roof is most of the
sprite, a strip of front wall with the door shows below it.

Parts (part(name, kind, ...) -> RGBA):
    wall_round, wall_square, roof_cone, roof_hip, roof_dome, door, window, chimney, banner, fence,
    garden_bed, lantern, well, sign, cairn
Compositions:
    hut(username, tier 0-2) -> RGBA sprite (tier: 64 / 80 / 96 px; a creature is 40) ; well() ; cairn() ; lantern()
    python buildings.py -> building_kit.png
"""
import hashlib
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from paint import Canvas, hsv, lerp, ell, circ, seg, box, union, smin, ring, rot
import creatures

HERE = os.path.dirname(os.path.abspath(__file__))
HUT_PX = {0: 64, 1: 80, 2: 96}
WALLS = [
    dict(name="plaster", fill=(234, 216, 184), dk=(196, 172, 136), line=(112, 84, 60)),
    dict(name="timber", fill=(184, 140, 92), dk=(146, 104, 66), line=(84, 56, 34)),
    dict(name="stone", fill=(176, 170, 160), dk=(136, 128, 118), line=(78, 72, 68)),
]
SHADOW = (32, 22, 34)
GLASS = (255, 214, 130)
GLASS_DK = (214, 150, 70)


def builder(name):
    g = creatures.genome(name)
    pal = creatures.palette(g)
    h = hashlib.sha1(("hut:" + g["name"]).encode()).digest()
    return dict(g=g, pal=pal, wall=WALLS[h[0] % 3], shape=h[1] % 3, door_side=(h[2] % 3) - 1,
                chimney=h[3] % 2, seed=h[4])


# ----------------------------------------------------------------------------- parts on a canvas
def _roof_cone(cv, X, Y, cx, cy, r, pal, line):
    d = circ(X, Y, cx, cy, r)
    cv.paint(d - 0.02, line)
    ang = np.arctan2(Y - cy, X - cx)
    rr = np.clip(np.hypot(X - cx, Y - cy) / r, 0, 1)
    light = 0.5 + 0.5 * np.cos(ang - math.radians(-125))          # light from upper-left
    col = lerp(pal["primary_dk"], pal["primary_lt"], np.clip(light ** 1.4 * (0.5 + 0.5 * (1 - rr)) + 0.15 * (1 - rr), 0, 1))
    cv.paint(d, np.clip(col, 0, 255))
    # thatch: two faint rings + a scalloped eave in the secondary colour
    for k in (0.50, 0.80):
        cv.paint(ring(circ(X, Y, cx, cy, r * k), 0.0035), pal["line"], alpha=0.16)
    eave = np.maximum(circ(X, Y, cx, cy, r), -circ(X, Y, cx, cy, r * 0.86))
    scallop = np.sin(ang * 12) * 0.012
    cv.paint(np.maximum(eave, -(circ(X, Y, cx, cy, r * 0.86) - scallop)), pal["secondary"], alpha=0.85)
    cv.paint(circ(X, Y, cx, cy - 0.01, 0.022), pal["secondary_dk"])


def _roof_hip(cv, X, Y, cx, cy, hx, hy, pal, line):
    d = box(X, Y, cx, cy, hx, hy, 0.03)
    cv.paint(d - 0.02, line)
    # four faces by the diagonals
    dx, dy = (X - cx) / hx, (Y - cy) / hy
    top = (dy < 0) & (np.abs(dy) >= np.abs(dx))
    bot = (dy >= 0) & (np.abs(dy) >= np.abs(dx))
    left = (dx < 0) & (np.abs(dx) > np.abs(dy))
    shade = np.where(top, 1.0, np.where(left, 0.68, np.where(bot, 0.30, 0.52)))
    col = lerp(pal["primary_dk"], pal["primary_lt"], shade)
    cv.paint(d, np.clip(col, 0, 255))
    ridge_hx = max(0.0, hx - hy)
    cv.paint(seg(X, Y, cx - ridge_hx, cy, cx + ridge_hx, cy, 0.008), pal["secondary"])
    for (sx, sy) in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        cv.paint(seg(X, Y, cx + sx * ridge_hx, cy, cx + sx * hx, cy + sy * hy, 0.004), pal["line"], alpha=0.35)
    # shingle rows
    for k in range(1, 4):
        yy = cy - hy + (2 * hy) * k / 4
        cv.paint(np.maximum(np.abs(Y - yy) - 0.003, d + 0.02), pal["line"], alpha=0.16)


def _roof_dome(cv, X, Y, cx, cy, r, pal, line):
    d = ell(X, Y, cx, cy, r, r * 0.86)
    cv.paint(d - 0.02, line)
    rr = np.clip(np.sqrt(((X - cx) / r) ** 2 + ((Y - cy) / (r * 0.86)) ** 2), 0, 1)
    spec = np.exp(-(((X - (cx - r * 0.35)) / (r * 0.55)) ** 2 + ((Y - (cy - r * 0.35)) / (r * 0.45)) ** 2))
    col = lerp(pal["primary"], pal["primary_dk"], rr ** 2.2)
    col = col + spec[..., None] * 0.5 * (255 - col)
    cv.paint(d, np.clip(col, 0, 255))
    cv.paint(ring(ell(X, Y, cx, cy, r * 0.62, r * 0.55), 0.0035), pal["line"], alpha=0.18)
    for a in (-60, -20, 20, 60):
        ex, ey = cx + r * 0.98 * math.sin(math.radians(a)), cy + r * 0.86 * 0.98 * math.cos(math.radians(a))
        cv.paint(np.maximum(seg(X, Y, cx, cy, ex, ey, 0.0035), d + 0.01), pal["line"], alpha=0.16)
    eave = np.maximum(d, -(ell(X, Y, cx, cy, r * 0.90, r * 0.86 * 0.90)))
    cv.paint(eave, pal["secondary"], alpha=0.9)
    cv.paint(circ(X, Y, cx, cy - r * 0.55, 0.05) - 0.01, line, alpha=0.6)
    cv.paint(circ(X, Y, cx, cy - r * 0.55, 0.05), pal["secondary"])
    cv.paint(circ(X, Y, cx - 0.015, cy - r * 0.55 - 0.015, 0.018), (255, 255, 255), alpha=0.6)


def _wall(cv, X, Y, cx, y_top, y_bot, half_w, wall, round_=False):
    if round_:
        d = np.maximum(ell(X, Y, cx, y_top, half_w, 0.5 * (y_bot - y_top) * 1.4), -(Y - y_top))
        d = np.maximum(d, Y - y_bot)
    else:
        d = box(X, Y, cx, (y_top + y_bot) / 2, half_w, (y_bot - y_top) / 2, 0.01)
    cv.paint(d - 0.016, wall["line"])
    t = np.clip((Y - y_top) / max(1e-3, (y_bot - y_top)), 0, 1)
    cv.paint(d, np.clip(lerp(wall["fill"], wall["dk"], t * 0.8), 0, 255))
    if wall["name"] == "timber":
        for k in range(3):
            yy = y_top + (y_bot - y_top) * (k + 0.5) / 3
            cv.paint(np.maximum(np.abs(Y - yy) - 0.003, d + 0.01), wall["line"], alpha=0.35)
    elif wall["name"] == "stone":
        rs = np.random.RandomState(7)
        for _ in range(10):
            sx, sy = rs.uniform(cx - half_w, cx + half_w), rs.uniform(y_top, y_bot)
            cv.paint(np.maximum(ell(X, Y, sx, sy, 0.04, 0.02), d + 0.01), wall["dk"], alpha=0.5)


def _door(cv, X, Y, cx, y_bot, pal, wall, h=0.13, w=0.045):
    d = np.maximum(smin(box(X, Y, cx, y_bot - h / 2, w, h / 2, 0.0), circ(X, Y, cx, y_bot - h + w, w), 0.02), Y - y_bot)
    cv.paint(d - 0.012, wall["line"])
    cv.paint(d, pal["secondary_dk"])
    cv.paint(np.maximum(d + 0.012, -(Y - (y_bot - h * 0.45))), pal["secondary"], alpha=0.35)
    cv.paint(circ(X, Y, cx + w * 0.45, y_bot - h * 0.45, 0.008), (250, 220, 120))


def _window(cv, X, Y, cx, cy, wall, w=0.035, h=0.04):
    d = box(X, Y, cx, cy, w, h, 0.008)
    cv.paint(d - 0.012, wall["line"])
    cv.paint(d, GLASS)
    cv.paint(np.maximum(d, -(Y - cy)), GLASS_DK, alpha=0.35)
    cv.paint(np.maximum(np.abs(X - cx) - 0.004, d), wall["line"], alpha=0.7)


def _chimney(cv, X, Y, cx, cy, wall):
    d = box(X, Y, cx, cy, 0.03, 0.035, 0.005)
    cv.paint(d - 0.012, wall["line"])
    cv.paint(d, wall["dk"])
    cv.paint(np.maximum(d, Y - cy + 0.02), (66, 50, 54))
    for k, (ox, oy, r) in enumerate([(0.0, -0.06, 0.022), (0.03, -0.11, 0.03), (0.075, -0.16, 0.036)]):
        cv.paint(circ(X, Y, cx + ox, cy + oy, r), (236, 230, 226), alpha=0.55 - 0.12 * k, soft=3.0)


def _banner(cv, X, Y, x, y_bot, pal, line, h=0.22):
    cv.paint(seg(X, Y, x, y_bot, x, y_bot - h, 0.008) - 0.008, line)
    cv.paint(seg(X, Y, x, y_bot, x, y_bot - h, 0.008), (120, 90, 60))
    ty = y_bot - h
    flag = union(seg(X, Y, x, ty + 0.01, x + 0.11, ty + 0.035, 0.028), seg(X, Y, x, ty + 0.045, x + 0.08, ty + 0.05, 0.02))
    flag = np.maximum(flag, -(X - x))
    cv.paint(flag - 0.01, line)
    cv.paint(flag, pal["secondary"])
    cv.paint(circ(X, Y, x, ty - 0.01, 0.016), pal["primary_lt"])


def _shadow(cv, X, Y, cx, cy, rx, ry):
    cv.paint(ell(X, Y, cx, cy, rx, ry), SHADOW, alpha=0.32, soft=6.0)


# ----------------------------------------------------------------------------- compositions
def hut(name, tier=1, B=None):
    """Builder's hut. tier 0: a stake and a tent-roof; tier 1: hut; tier 2: hut + chimney + banner."""
    b = builder(name)
    pal, wall, line = b["pal"], b["wall"], b["wall"]["line"]
    B = B or HUT_PX[tier]
    cv = Canvas(B, 1.0)
    X, Y = cv.x, cv.y
    shape = b["shape"]
    _shadow(cv, X, Y, 0.53, 0.90, 0.42, 0.08)
    y_bot = 0.90
    if tier == 0:       # stake camp: a small tent (cone to the ground), a flap for a door, a stake
        _roof_cone(cv, X, Y, 0.5, 0.62, 0.30, pal, line)
        flap = np.maximum(box(X, Y, 0.5, 0.86, 0.06, 0.09, 0.02), circ(X, Y, 0.5, 0.62, 0.31))
        cv.paint(flap, pal["secondary_dk"])
        cv.paint(seg(X, Y, 0.84, 0.90, 0.84, 0.62, 0.014) - 0.008, line)
        cv.paint(seg(X, Y, 0.84, 0.90, 0.84, 0.62, 0.014), (140, 100, 62))
        cv.paint(circ(X, Y, 0.84, 0.60, 0.028), pal["secondary"])
        return cv.out()
    if shape == 0:      # round hut, cone roof
        _wall(cv, X, Y, 0.5, 0.62, y_bot, 0.32, wall, round_=True)
        _door(cv, X, Y, 0.5 + 0.08 * b["door_side"], y_bot, pal, wall, h=0.17, w=0.06)
        _window(cv, X, Y, 0.5 - 0.19 * (1 if b["door_side"] >= 0 else -1), 0.80, wall)
        _roof_cone(cv, X, Y, 0.5, 0.38, 0.36, pal, line)
    elif shape == 1:    # long house, hip roof
        _wall(cv, X, Y, 0.5, 0.62, y_bot, 0.40, wall)
        _door(cv, X, Y, 0.5 + 0.1 * b["door_side"], y_bot, pal, wall, h=0.17, w=0.06)
        _window(cv, X, Y, 0.5 - 0.27, 0.80, wall)
        _window(cv, X, Y, 0.5 + 0.27, 0.80, wall)
        _roof_hip(cv, X, Y, 0.5, 0.42, 0.44, 0.26, pal, line)
    else:               # dome
        _wall(cv, X, Y, 0.5, 0.64, y_bot, 0.33, wall, round_=True)
        _door(cv, X, Y, 0.5 + 0.07 * b["door_side"], y_bot, pal, wall, h=0.17, w=0.06)
        _window(cv, X, Y, 0.5 + 0.19 * (1 if b["door_side"] <= 0 else -1), 0.80, wall)
        _roof_dome(cv, X, Y, 0.5, 0.40, 0.36, pal, line)
    if b["chimney"]:
        _chimney(cv, X, Y, 0.70, 0.34, wall)
    if tier >= 2:
        _banner(cv, X, Y, 0.12, 0.90, pal, line)
    return cv.out()


def well(B=56):
    cv = Canvas(B, 1.0)
    X, Y = cv.x, cv.y
    _shadow(cv, X, Y, 0.52, 0.86, 0.36, 0.08)
    # posts + little roof
    for x in (0.28, 0.72):
        cv.paint(seg(X, Y, x, 0.78, x, 0.30, 0.02) - 0.01, (70, 48, 30))
        cv.paint(seg(X, Y, x, 0.78, x, 0.30, 0.02), (140, 100, 62))
    rim = ell(X, Y, 0.5, 0.72, 0.30, 0.16)
    inner = ell(X, Y, 0.5, 0.72, 0.20, 0.10)
    cv.paint(rim - 0.016, (78, 72, 68))
    cv.paint(rim, (176, 170, 160))
    cv.paint(inner, (52, 96, 140))
    cv.paint(np.maximum(inner + 0.03, -(X - 0.5 + 0.05)), (110, 170, 190), alpha=0.5)
    cv.paint(box(X, Y, 0.5, 0.30, 0.30, 0.08, 0.02) - 0.014, (78, 72, 68))
    cv.paint(box(X, Y, 0.5, 0.30, 0.30, 0.08, 0.02), (176, 92, 70))
    cv.paint(np.maximum(box(X, Y, 0.5, 0.30, 0.30, 0.08, 0.02), Y - 0.30), (214, 130, 96), alpha=0.6)
    cv.paint(seg(X, Y, 0.5, 0.38, 0.5, 0.55, 0.006), (80, 70, 60))
    cv.paint(box(X, Y, 0.5, 0.58, 0.04, 0.04, 0.01), (120, 90, 60))
    return cv.out()


def cairn(B=56):
    cv = Canvas(B, 1.0)
    X, Y = cv.x, cv.y
    _shadow(cv, X, Y, 0.52, 0.88, 0.34, 0.08)
    for (cx, cy, rx, ry, c) in [(0.5, 0.78, 0.30, 0.13, (150, 142, 132)), (0.48, 0.62, 0.23, 0.11, (168, 160, 150)),
                                (0.51, 0.48, 0.17, 0.09, (184, 176, 166)), (0.5, 0.37, 0.11, 0.07, (200, 194, 186))]:
        d = ell(X, Y, cx, cy, rx, ry)
        cv.paint(d - 0.014, (78, 72, 68))
        cv.paint(d, c)
        cv.paint(np.maximum(d + 0.02, Y - cy), (110, 104, 98), alpha=0.35)
    cv.paint(ell(X, Y, 0.62, 0.72, 0.06, 0.03), (120, 160, 80), alpha=0.8)   # moss
    return cv.out()


def lantern(B=24):
    cv = Canvas(B, 1.6)
    X, Y = cv.x, cv.y
    cv.paint(seg(X, Y, 0.5, 1.5, 0.5, 0.55, 0.05) - 0.02, (60, 44, 30))
    cv.paint(seg(X, Y, 0.5, 1.5, 0.5, 0.55, 0.05), (120, 90, 60))
    cv.paint(box(X, Y, 0.5, 0.42, 0.18, 0.16, 0.04) - 0.02, (60, 44, 30))
    cv.paint(box(X, Y, 0.5, 0.42, 0.18, 0.16, 0.04), (255, 214, 130))
    cv.paint(circ(X, Y, 0.5, 0.42, 0.09), (255, 245, 210))
    cv.paint(box(X, Y, 0.5, 0.22, 0.14, 0.04, 0.02), (60, 44, 30))
    return cv.out()


def fence(B=32):
    cv = Canvas(B, 0.6)
    X, Y = cv.x, cv.y
    cv.paint(seg(X, Y, 0.0, 0.32, 1.0, 0.32, 0.03), (140, 100, 62))
    for x in (0.15, 0.5, 0.85):
        cv.paint(seg(X, Y, x, 0.52, x, 0.12, 0.045) - 0.012, (70, 48, 30))
        cv.paint(seg(X, Y, x, 0.52, x, 0.12, 0.045), (176, 130, 84))
    return cv.out()


def garden_bed(B=40):
    cv = Canvas(B, 0.8)
    X, Y = cv.x, cv.y
    d = box(X, Y, 0.5, 0.42, 0.44, 0.30, 0.06)
    cv.paint(d - 0.016, (84, 56, 34))
    cv.paint(d, (150, 116, 84))
    cv.paint(d + 0.05, (122, 90, 62))
    rs = np.random.RandomState(3)
    for _ in range(7):
        x, y = rs.uniform(0.15, 0.85), rs.uniform(0.22, 0.62)
        cv.paint(circ(X, Y, x, y, 0.05), (92, 156, 70))
        cv.paint(circ(X, Y, x - 0.015, y - 0.02, 0.025), (150, 200, 100), alpha=0.9)
        if rs.rand() < 0.5:
            cv.paint(circ(X, Y, x, y - 0.03, 0.018), (250, 190, 210))
    return cv.out()


def sign(B=24):
    cv = Canvas(B, 1.2)
    X, Y = cv.x, cv.y
    cv.paint(seg(X, Y, 0.5, 1.1, 0.5, 0.5, 0.05) - 0.014, (70, 48, 30))
    cv.paint(seg(X, Y, 0.5, 1.1, 0.5, 0.5, 0.05), (140, 100, 62))
    cv.paint(box(X, Y, 0.5, 0.36, 0.42, 0.22, 0.04) - 0.016, (70, 48, 30))
    cv.paint(box(X, Y, 0.5, 0.36, 0.42, 0.22, 0.04), (204, 160, 104))
    for yy in (0.30, 0.42):
        cv.paint(seg(X, Y, 0.25, yy, 0.72, yy, 0.02), (110, 76, 46), alpha=0.7)
    return cv.out()


def smoke_puff(r=6):
    cv = Canvas(r * 2 + 4, 1.0)
    X, Y = cv.x, cv.y
    cv.paint(circ(X, Y, 0.5, 0.5, 0.36), (236, 230, 226), alpha=0.5, soft=4.0)
    return cv.out()


PARTS = ["wall_round", "wall_square", "roof_cone", "roof_hip", "roof_dome", "door", "window", "chimney", "banner",
         "fence", "garden_bed", "lantern", "well", "sign", "cairn"]


def part(name, kind, B=48):
    """Render one part in isolation in the builder's colour (for the kit sheet and for keeper carvings)."""
    b = builder(name)
    pal, wall, line = b["pal"], b["wall"], b["wall"]["line"]
    if kind == "fence":
        return fence()
    if kind == "garden_bed":
        return garden_bed()
    if kind == "lantern":
        return lantern()
    if kind == "well":
        return well()
    if kind == "sign":
        return sign()
    if kind == "cairn":
        return cairn()
    cv = Canvas(B, 1.0)
    X, Y = cv.x, cv.y
    if kind == "wall_round":
        _wall(cv, X, Y, 0.5, 0.45, 0.8, 0.36, wall, round_=True)
    elif kind == "wall_square":
        _wall(cv, X, Y, 0.5, 0.45, 0.8, 0.40, wall)
    elif kind == "roof_cone":
        _roof_cone(cv, X, Y, 0.5, 0.5, 0.42, pal, line)
    elif kind == "roof_hip":
        _roof_hip(cv, X, Y, 0.5, 0.5, 0.44, 0.28, pal, line)
    elif kind == "roof_dome":
        _roof_dome(cv, X, Y, 0.5, 0.5, 0.42, pal, line)
    elif kind == "door":
        _door(cv, X, Y, 0.5, 0.8, pal, wall, h=0.36, w=0.12)
    elif kind == "window":
        _window(cv, X, Y, 0.5, 0.5, wall, w=0.12, h=0.14)
    elif kind == "chimney":
        _chimney(cv, X, Y, 0.5, 0.7, wall)
    elif kind == "banner":
        _banner(cv, X, Y, 0.35, 0.95, pal, line, h=0.7)
    return cv.out()


def write_kit(path=None, names=None, zoom=2):
    names = names or creatures.EXAMPLES[:6]
    path = path or os.path.join(HERE, "building_kit.png")
    f = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 14)
    fh = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf", 20)
    cell = 48 * zoom + 12
    Wd = max(len(PARTS) * cell, 170 + 3 * (96 * zoom + 12)) + 24
    Hd = 40 + cell + 40 + len(names) * (96 * zoom + 14) + 40
    im = Image.new("RGB", (Wd, Hd), (52, 44, 58))
    d = ImageDraw.Draw(im)
    d.text((12, 10), "parts (builder colour of @%s)" % names[0], font=f, fill=(230, 220, 200))
    for j, k in enumerate(PARTS):
        p = part(names[0], k)
        pi = Image.fromarray(p).resize((p.shape[1] * zoom, p.shape[0] * zoom), Image.LANCZOS)
        x = 12 + j * cell
        d.rectangle([x, 32, x + cell - 12, 32 + cell - 12], fill=(112, 142, 92))
        im.paste(pi, (x + (cell - 12 - pi.size[0]) // 2, 32 + (cell - 12 - pi.size[1]) // 2), pi)
        d.text((x, 32 + cell - 8), k, font=f, fill=(200, 190, 175))
    y = 32 + cell + 34
    d.text((12, y), "huts by builder: tier 0 stake-camp, 1 hut, 2 hut + chimney + banner   (2x lanczos)", font=f, fill=(230, 220, 200))
    y += 24
    for n in names:
        b = builder(n)
        d.rectangle([12, y + 8, 30, y + 26], fill=b["pal"]["primary"])
        d.text((36, y + 6), "@" + n, font=fh, fill=(245, 238, 226))
        d.text((12, y + 34), "%s / %s" % (["round", "long", "dome"][b["shape"]], b["wall"]["name"]), font=f, fill=(200, 190, 175))
        for t in range(3):
            p = hut(n, t)
            pi = Image.fromarray(p).resize((p.shape[1] * zoom, p.shape[0] * zoom), Image.LANCZOS)
            x = 170 + t * (96 * zoom + 12)
            d.rectangle([x, y, x + 96 * zoom, y + 96 * zoom], fill=(112, 142, 92))
            im.paste(pi, (x + (96 * zoom - pi.size[0]) // 2, y + 96 * zoom - pi.size[1]), pi)
        y += 96 * zoom + 14
    im.save(path)
    return path


if __name__ == "__main__":
    print(write_kit())
