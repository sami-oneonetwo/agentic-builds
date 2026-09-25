"""creatures.py - SPROUTS: the SETTLEMENT creature family (studio-a).

Every creature is a real chatter, procedural and deterministic from the username. Silhouette
language: a soft PEAR-POD body (wide hips, rounder head) seen from a 3/4 top-down camera, a growing
SPROUT on the crown (seedling -> leaf -> bloom across growth tiers; it also perks up or droops
with mood and bends toward whoever they talk to), name-family EARS (none / nubs / petal-ears),
a secondary-colour TAIL TUFT behind, big lidded eyes with a glint, stubby nub feet and a soft
ground shadow. Hue and the secondary colour come from the name; the sprout, ears and tail variants
come from the same hash, so a name always hatches the same creature.

    sheet(names)             -> dict name -> {frame: RGBA (B,B,4)} at a tier
    SpriteCache().get(name, tier, frame, facing)   (compositor side, pre-rendered, flips cached)
    python creatures.py      -> writes creature_sheet.png next to this file

numpy + pillow only. Base size: tier 1 = 40 px (tiers 0/1/2 = 32/40/48 px boxes).
"""
import hashlib
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from paint import Canvas, hsv, lerp, ell, circ, seg, union, smin, ring, rot

HERE = os.path.dirname(os.path.abspath(__file__))
FRAMES = ["idle0", "idle1", "walk0", "walk1", "hop", "blink", "speak", "sleep", "emote0", "emote1"]
TIER_PX = {0: 32, 1: 40, 2: 48}
ASPECT = 1.22          # canvas is B wide, B*ASPECT tall: headroom for the sprout / bloom / marks
Y_SHIFT = 0.19         # unit geometry is shifted down by this so the foot anchor sits near the bottom
TIER_NAME = {0: "seedling", 1: "sprout", 2: "bloom"}
HEAD_NAMES = ["round", "tall", "wide", "crown"]
SPROUT_NAMES = ["leaf", "curl", "twin", "bell"]
EAR_NAMES = ["none", "nubs", "petals"]
TAIL_NAMES = ["tuft", "curl", "fan"]


# ----------------------------------------------------------------------------- identity
def clean(name):
    return (name or "").strip().lstrip("@").lower()


def genome(name):
    n = clean(name)
    h = hashlib.sha1(n.encode("utf-8")).digest()
    return {
        "name": n,
        "hue": h[0] / 255.0,
        "sat": 0.56 + 0.24 * h[1] / 255.0,
        "val": 0.84 + 0.13 * h[2] / 255.0,
        "sec_off": (36 + (h[3] % 52)) * (1 if h[4] & 1 else -1),   # degrees
        "head": h[5] % 4,
        "sprout": h[6] % 4,
        "ears": h[7] % 3,
        "tail": h[8] % 3,
        "cheek": h[9] % 3,            # 0 blush, 1 freckles, 2 plain
        "bigeyes": h[10] % 2,
        "belly": (h[11] % 4) != 0,
        "seed": h[12] | (h[13] << 8),
    }


def palette(g):
    hue, sat, val = g["hue"], g["sat"], g["val"]
    sh = hue + g["sec_off"] / 360.0
    return {
        "primary": hsv(hue, sat, val),
        "primary_lt": hsv(hue, sat * 0.72, min(1.0, val * 1.08)),
        "primary_dk": hsv(hue, min(1.0, sat * 1.08), val * 0.70),
        "line": hsv(hue, sat * 0.85, val * 0.34),
        "secondary": hsv(sh, sat * 0.72, min(1.0, val * 1.02)),
        "secondary_dk": hsv(sh, sat * 0.85, val * 0.62),
        "belly": hsv(hue, sat * 0.28, min(1.0, val * 1.10)),
        "eye_white": (253, 249, 240),
        "pupil": (38, 28, 44),
        "glint": (255, 255, 255),
        "cheek": (242, 118, 118),
        "mouth": (74, 34, 50),
        "tongue": (236, 118, 130),
        "shadow": (32, 22, 34),
    }


def dot_colour(name):
    """The lit-dot colour a creature shows at 320x180 and in chat."""
    return palette(genome(name))["primary"]


# ----------------------------------------------------------------------------- pose table
def frame_params(frame):
    P = dict(sx=1.0, sy=1.0, dy=0.0, tilt=0.0, eyes="open", mouth="smile", perk=0.72,
             feet=0, shadow=1.0, lid=0.14, mark=None)
    if frame == "idle1":
        P.update(sx=1.04, sy=0.965, lid=0.22, perk=0.62)
    elif frame == "walk0":
        P.update(feet=1, tilt=-4, dy=-0.012, sx=0.99, sy=1.02, perk=0.8)
    elif frame == "walk1":
        P.update(feet=-1, tilt=4, dy=-0.012, sx=0.99, sy=1.02, perk=0.66)
    elif frame == "hop":
        P.update(sx=0.86, sy=1.18, dy=-0.14, feet=2, shadow=0.72, eyes="happy", mouth="open", perk=1.0)
    elif frame == "blink":
        P.update(eyes="closed")
    elif frame == "speak":
        P.update(tilt=10, mouth="open", perk=1.0, sx=1.02, lid=0.06)
    elif frame == "sleep":
        P.update(sx=1.10, sy=0.86, eyes="closed", mouth="flat", perk=0.12, feet=3, tilt=-7, mark="zz")
    elif frame == "emote0":   # joy
        P.update(eyes="happy", mouth="grin", sx=0.95, sy=1.07, perk=1.0, dy=-0.035, mark="sparkle")
    elif frame == "emote1":   # curious
        P.update(eyes="wide", mouth="o", tilt=13, perk=1.0, sy=1.03, lid=0.0, mark="bang")
    return P


# ----------------------------------------------------------------------------- renderer
FOOT = (0.5, 0.905)
NECK = (0.5, 0.60)


def anchor(tier):
    """(dx, dy) from the sprite's top-left to its foot point, in px."""
    B = TIER_PX[tier]
    return int(round(B * 0.5)), int(round(B * (FOOT[1] + Y_SHIFT)))


def render(g, frame, tier=1, B=None):
    """Return RGBA uint8 (B*ASPECT, B, 4) for genome g at `frame`, facing right. Foot at anchor(tier)."""
    B = B or TIER_PX[tier]
    pal = palette(g)
    P = frame_params(frame)
    cv = Canvas(B, ASPECT)
    X, Y = cv.x, cv.y - Y_SHIFT
    face = 0.035                                          # face offset toward facing (right)

    # body space: inverse squash/stretch about the foot pivot, then lift
    bx = FOOT[0] + (X - FOOT[0]) / P["sx"]
    by = FOOT[1] + (Y - P["dy"] - FOOT[1]) / P["sy"]
    # head space: additionally rotated about the neck (tilt toward facing)
    hx, hy = rot(bx, by, NECK[0], NECK[1], -P["tilt"])

    # geometry in rest space
    body = ell(bx, by, 0.5, 0.705, 0.29, 0.205)
    if g["head"] == 0:    # round
        hcx, hcy, hrx, hry = 0.5, 0.475, 0.255, 0.245
        head = ell(hx, hy, hcx, hcy, hrx, hry)
    elif g["head"] == 1:  # tall
        hcx, hcy, hrx, hry = 0.5, 0.455, 0.225, 0.27
        head = ell(hx, hy, hcx, hcy, hrx, hry)
    elif g["head"] == 2:  # wide
        hcx, hcy, hrx, hry = 0.5, 0.49, 0.29, 0.225
        head = ell(hx, hy, hcx, hcy, hrx, hry)
    else:                 # crown: round with a soft peak
        hcx, hcy, hrx, hry = 0.5, 0.48, 0.25, 0.24
        head = smin(ell(hx, hy, hcx, hcy, hrx, hry), ell(hx, hy, 0.5, 0.31, 0.10, 0.11), 0.05)
    head_top = hcy - hry
    pod = smin(body, head, 0.07)
    fx, fy = hcx + face, hcy + 0.045                      # face centre

    # ------------------------------------------------ shadow (ground space)
    sh = P["shadow"]
    cv.paint(ell(X, Y, 0.5 + 0.01, 0.925, 0.27 * sh, 0.06 * sh), pal["shadow"], alpha=0.30, soft=6.0)

    # ------------------------------------------------ tail (behind, opposite the facing side)
    tx, ty = 0.5 - 0.30, 0.76
    sec, secd = pal["secondary"], pal["secondary_dk"]
    if g["tail"] == 0:      # tuft
        tail = union(circ(bx, by, tx, ty, 0.065), circ(bx, by, tx - 0.03, ty + 0.05, 0.045))
    elif g["tail"] == 1:    # curl
        tail = union(circ(bx, by, tx, ty, 0.06), circ(bx, by, tx - 0.06, ty + 0.045, 0.045),
                     circ(bx, by, tx - 0.10, ty + 0.10, 0.03))
    else:                   # fan
        tail = union(ell(bx, by, tx - 0.03, ty - 0.06, 0.055, 0.035), ell(bx, by, tx - 0.06, ty + 0.01, 0.06, 0.035),
                     ell(bx, by, tx - 0.03, ty + 0.08, 0.055, 0.035))
    cv.paint(tail - 0.012, secd)
    cv.paint(tail, sec)

    # ------------------------------------------------ feet
    if P["feet"] != 3:
        lf = (0.5 - 0.135, 0.905)
        rf = (0.5 + 0.135, 0.905)
        if P["feet"] == 1:
            lf, rf = (lf[0] - 0.02, lf[1] - 0.03), (rf[0] + 0.02, rf[1] + 0.005)
        elif P["feet"] == -1:
            lf, rf = (lf[0] - 0.02, lf[1] + 0.005), (rf[0] + 0.02, rf[1] - 0.03)
        elif P["feet"] == 2:   # tucked mid-hop
            lf, rf = (0.5 - 0.10, 0.905 + P["dy"] + 0.05), (0.5 + 0.10, 0.905 + P["dy"] + 0.05)
        feet = union(ell(X, Y, lf[0], lf[1], 0.075, 0.042), ell(X, Y, rf[0], rf[1], 0.075, 0.042))
        cv.paint(feet - 0.012, pal["line"])
        cv.paint(feet, pal["primary_dk"])

    # ------------------------------------------------ ears (behind head, in front of body)
    if g["ears"] == 1:      # nubs
        ears = union(circ(hx, hy, hcx - hrx * 0.92, hcy - hry * 0.45, 0.055),
                     circ(hx, hy, hcx + hrx * 0.92, hcy - hry * 0.45, 0.055))
        cv.paint(ears - 0.012, pal["line"])
        cv.paint(ears, pal["primary"])
    elif g["ears"] == 2:    # petal ears, drooping outward
        lx, ly = rot(hx, hy, hcx - hrx * 0.95, hcy - hry * 0.25, -38)
        rx_, ry_ = rot(hx, hy, hcx + hrx * 0.95, hcy - hry * 0.25, 38)
        ears = union(ell(lx, ly, hcx - hrx * 0.95 - 0.07, hcy - hry * 0.25, 0.10, 0.05),
                     ell(rx_, ry_, hcx + hrx * 0.95 + 0.07, hcy - hry * 0.25, 0.10, 0.05))
        cv.paint(ears - 0.012, pal["line"])
        cv.paint(ears, pal["primary"])
        inner = union(ell(lx, ly, hcx - hrx * 0.95 - 0.075, hcy - hry * 0.25, 0.055, 0.022),
                      ell(rx_, ry_, hcx + hrx * 0.95 + 0.075, hcy - hry * 0.25, 0.055, 0.022))
        cv.paint(inner, pal["secondary"], alpha=0.85)

    # ------------------------------------------------ pod (body + head) with shading
    cv.paint(pod - 0.014, pal["line"])                    # soft outline in a dark of the same hue
    t = np.clip((by - head_top) / (0.91 - head_top), 0, 1)
    col = lerp(pal["primary_lt"], pal["primary_dk"], t ** 1.5)
    spec = np.exp(-(((hx - (hcx - 0.09)) / 0.11) ** 2 + ((hy - (hcy - 0.12)) / 0.085) ** 2)) * 0.42
    col = col + spec[..., None] * (255 - col)
    cv.paint(pod, np.clip(col, 0, 255))
    # rim shade toward the bottom of the pod (reads as roundness at 32 px)
    cv.paint(np.maximum(pod, -(pod + 0.03)), pal["primary_dk"], alpha=0.35 * np.clip((by - 0.62) / 0.25, 0, 1))
    if g["belly"]:
        belly = np.maximum(ell(bx, by, 0.5 + face * 0.5, 0.735, 0.165, 0.12), pod + 0.035)
        cv.paint(belly, pal["belly"], alpha=0.9)

    # ------------------------------------------------ sprout on the crown
    perk = P["perk"]
    bend = (1.0 - perk) * 58.0                            # degrees from vertical, toward facing
    slen = [0.085, 0.13, 0.165][tier]
    sxp, syp = hcx, head_top + 0.012
    ang = math.radians(bend)
    tipx, tipy = sxp + slen * math.sin(ang), syp - slen * math.cos(ang)
    midx, midy = sxp + slen * 0.5 * math.sin(ang * 0.6), syp - slen * 0.5 * math.cos(ang * 0.6)
    stem = union(seg(hx, hy, sxp, syp, midx, midy, 0.016), seg(hx, hy, midx, midy, tipx, tipy, 0.015))
    cv.paint(stem - 0.010, pal["line"])
    cv.paint(stem, secd)
    if tier == 0:
        bud = circ(hx, hy, tipx, tipy, 0.035)
        cv.paint(bud - 0.011, pal["line"])
        cv.paint(bud, sec)
    else:
        dx, dy = math.sin(ang), -math.cos(ang)
        if g["sprout"] == 0:    # leaf
            lx, ly = rot(hx, hy, tipx, tipy, -(bend + 40))
            leaf = ell(lx, ly, tipx, tipy - 0.03, 0.04, 0.075)
            cv.paint(leaf - 0.011, pal["line"])
            cv.paint(leaf, sec)
            cv.paint(seg(lx, ly, tipx, tipy + 0.03, tipx, tipy - 0.09, 0.006), secd, alpha=0.7)
        elif g["sprout"] == 1:  # curl
            curl = union(circ(hx, hy, tipx, tipy, 0.045), circ(hx, hy, tipx + 0.055 * dx + 0.03, tipy + 0.055 * dy + 0.035, 0.03))
            cv.paint(curl - 0.011, pal["line"])
            cv.paint(curl, sec)
            cv.paint(circ(hx, hy, tipx, tipy, 0.018), secd)
        elif g["sprout"] == 2:  # twin blades
            lx, ly = rot(hx, hy, tipx, tipy, -(bend + 42))
            rx_, ry_ = rot(hx, hy, tipx, tipy, -(bend - 42))
            twin = union(ell(lx, ly, tipx, tipy - 0.05, 0.03, 0.065), ell(rx_, ry_, tipx, tipy - 0.05, 0.03, 0.065))
            cv.paint(twin - 0.011, pal["line"])
            cv.paint(twin, sec)
        else:                   # bell (drooping teardrop)
            bell = smin(ell(hx, hy, tipx + 0.01, tipy + 0.03, 0.042, 0.055), circ(hx, hy, tipx, tipy - 0.01, 0.02), 0.03)
            cv.paint(bell - 0.011, pal["line"])
            cv.paint(bell, sec)
            cv.paint(circ(hx, hy, tipx + 0.01, tipy + 0.075, 0.014), pal["primary_lt"])
        if tier == 2:           # bloom: a five-petal flower crowns the tip
            petals = None
            for k in range(5):
                a = math.radians(90 + k * 72 + bend)
                pc = circ(hx, hy, tipx + 0.05 * math.cos(a), tipy - 0.02 + 0.05 * math.sin(a), 0.03)
                petals = pc if petals is None else union(petals, pc)
            cv.paint(petals - 0.010, pal["line"], alpha=0.8)
            cv.paint(petals, lerp(sec, (255, 255, 255), 0.35))
            cv.paint(circ(hx, hy, tipx, tipy - 0.02, 0.024), pal["primary_lt"])

    # ------------------------------------------------ face
    ex = 0.115
    er = (0.072, 0.088)
    if g["bigeyes"]:
        er = (er[0] * 1.17, er[1] * 1.17)
    if P["eyes"] == "wide":
        er = (er[0] * 1.12, er[1] * 1.12)
    eyes_pos = [(fx - ex, fy), (fx + ex, fy)]
    # cheeks first (under eyes)
    if g["cheek"] == 0:
        for sgn in (-1, 1):
            cv.paint(ell(hx, hy, fx + sgn * 0.175, fy + 0.085, 0.05, 0.03), pal["cheek"], alpha=0.42, soft=3.0)
    elif g["cheek"] == 1:
        rs = np.random.RandomState(g["seed"])
        for sgn in (-1, 1):
            for _ in range(3):
                ox, oy = rs.uniform(-0.03, 0.03), rs.uniform(-0.02, 0.02)
                cv.paint(circ(hx, hy, fx + sgn * 0.17 + ox, fy + 0.08 + oy, 0.009), pal["line"], alpha=0.55)

    for (ecx, ecy) in eyes_pos:
        eye = ell(hx, hy, ecx, ecy, er[0], er[1])
        if P["eyes"] in ("open", "wide"):
            cv.paint(eye - 0.008, pal["line"], alpha=0.9)
            cv.paint(eye, pal["eye_white"])
            pup_r = 0.040 if P["eyes"] == "open" else 0.046
            px_, py_ = ecx + 0.012, ecy + 0.012
            cv.paint(circ(hx, hy, px_, py_, pup_r), pal["pupil"])
            cv.paint(circ(hx, hy, px_ - 0.014, py_ - 0.016, 0.014), pal["glint"])
            cv.paint(circ(hx, hy, px_ + 0.012, py_ + 0.014, 0.007), pal["glint"], alpha=0.7)
            # upper eyelid: body colour cutting into the eye
            lid = P["lid"]
            if lid > 0:
                lid_line = ecy - er[1] + lid * 2 * er[1]
                lidsdf = np.maximum(eye - 0.008, hy - lid_line)
                cv.paint(lidsdf, pal["primary"])
                cv.paint(np.maximum(eye + 0.002, np.abs(hy - lid_line) - 0.007), pal["line"], alpha=0.9)
        elif P["eyes"] == "closed":     # sleepy "u" arc
            arc = np.maximum(ring(eye, 0.009), -(hy - ecy - 0.01))
            cv.paint(arc, pal["line"])
        else:                            # happy "^" arc
            arc = np.maximum(ring(ell(hx, hy, ecx, ecy + 0.03, er[0], er[1] * 0.9), 0.009), (hy - ecy - 0.02))
            cv.paint(arc, pal["line"])

    # mouth
    mx, my = fx, fy + 0.125
    m = P["mouth"]
    if m == "smile":
        arc = np.maximum(ring(ell(hx, hy, mx, my - 0.02, 0.05, 0.04), 0.0075), -(hy - my + 0.005))
        cv.paint(arc, pal["mouth"])
    elif m == "open":
        mo = ell(hx, hy, mx, my + 0.005, 0.046, 0.042)
        cv.paint(mo, pal["mouth"])
        cv.paint(np.maximum(ell(hx, hy, mx, my + 0.035, 0.03, 0.022), mo + 0.004), pal["tongue"])
    elif m == "grin":
        mo = np.maximum(ell(hx, hy, mx, my - 0.01, 0.075, 0.05), -(hy - my + 0.012))
        cv.paint(mo, pal["mouth"])
        cv.paint(np.maximum(ell(hx, hy, mx, my + 0.03, 0.04, 0.02), mo + 0.004), pal["tongue"])
    elif m == "o":
        cv.paint(circ(hx, hy, mx, my, 0.024), pal["mouth"])
    elif m == "flat":
        cv.paint(seg(hx, hy, mx - 0.03, my, mx + 0.03, my, 0.007), pal["mouth"])

    # ------------------------------------------------ marks (floating cues)
    mk = P["mark"]
    if mk == "zz":
        for i, (ox, oy, r) in enumerate([(0.36, 0.30, 0.02), (0.30, 0.20, 0.028)]):
            cv.paint(circ(X, Y, ox, oy, r + 0.008), pal["line"], alpha=0.6)
            cv.paint(circ(X, Y, ox, oy, r), pal["eye_white"], alpha=0.95)
    elif mk == "sparkle":
        for (ox, oy, r) in [(0.16, 0.36, 0.05), (0.85, 0.28, 0.038)]:
            star = union(seg(X, Y, ox - r, oy, ox + r, oy, 0.010), seg(X, Y, ox, oy - r, ox, oy + r, 0.010))
            cv.paint(star, lerp(pal["secondary"], (255, 255, 255), 0.5))
    elif mk == "bang":
        cv.paint(seg(X, Y, 0.86, 0.16, 0.86, 0.30, 0.02) - 0.008, pal["line"], alpha=0.7)
        cv.paint(seg(X, Y, 0.86, 0.16, 0.86, 0.30, 0.02), pal["eye_white"])
        cv.paint(circ(X, Y, 0.86, 0.37, 0.02), pal["eye_white"])

    return cv.out()


# ----------------------------------------------------------------------------- sheets and cache
def sheet(names, tier=1):
    return {n: {f: render(genome(n), f, tier) for f in FRAMES} for n in names}


class SpriteCache:
    """Compositor-side cache: frames are rendered once per (name, tier) and flipped copies are stored.
    Pre-warm with warm(name) when a creature hatches (about 0.25 s for all 10 frames x 3 tiers)."""

    def __init__(self):
        self._c = {}

    def warm(self, name, tiers=(0, 1, 2)):
        g = genome(name)
        for t in tiers:
            for f in FRAMES:
                self.get(name, t, f, 1, g)
                self.get(name, t, f, -1, g)

    def get(self, name, tier, frame, facing=1, g=None):
        key = (clean(name), tier, frame, facing)
        s = self._c.get(key)
        if s is None:
            if facing == -1:
                s = np.ascontiguousarray(self.get(name, tier, frame, 1, g)[:, ::-1])
            else:
                s = render(g or genome(name), frame, tier)
            self._c[key] = s
        return s

    def glow(self, name, radius=26):
        """Soft additive lantern glow in the creature's colour (float32 rgb), for dusk and the thumb."""
        key = ("glow", clean(name), radius)
        s = self._c.get(key)
        if s is None:
            col = np.asarray(dot_colour(name), np.float32)
            ys, xs = np.mgrid[0:2 * radius, 0:2 * radius].astype(np.float32)
            d = np.hypot(xs - radius + 0.5, ys - radius + 0.5) / radius
            a = np.clip(1 - d, 0, 1) ** 2.2 * 0.55
            s = (a[..., None] * col).astype(np.float32)
            self._c[key] = s
        return s


EXAMPLES = ["kai_dnb", "sami.exe", "noor.wav", "xXvtobiXx", "mira_9", "lowkeyjord", "zed_ttv", "luca_99"]


def write_sheet(path=None, names=None, zoom=2):
    names = names or EXAMPLES
    path = path or os.path.join(HERE, "creature_sheet.png")
    B = TIER_PX[1]
    Hs = int(round(B * ASPECT))
    cell = Hs * zoom + 6
    label_w = 150
    cols = len(FRAMES) + 3
    Wd = label_w + cols * cell + 20
    Hd = 60 + len(names) * (cell + 22)
    im = Image.new("RGB", (Wd, Hd), (52, 44, 58))
    d = ImageDraw.Draw(im)
    f_head = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf", 20)
    f_small = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 14)
    for j, fr in enumerate(FRAMES + ["tier0", "tier1", "tier2"]):
        d.text((label_w + j * cell + 4, 20), fr, font=f_small, fill=(230, 220, 200))
    for i, n in enumerate(names):
        g = genome(n)
        pal = palette(g)
        y0 = 50 + i * (cell + 22)
        d.rectangle([8, y0 + 4, label_w - 10, y0 + cell - 4], fill=(62, 54, 70), outline=None)
        d.rectangle([12, y0 + 8, 30, y0 + 26], fill=pal["primary"])
        d.text((36, y0 + 6), "@" + n, font=f_head, fill=(245, 238, 226))
        d.text((12, y0 + 34), "%s/%s" % (HEAD_NAMES[g["head"]], SPROUT_NAMES[g["sprout"]]), font=f_small, fill=(200, 190, 175))
        d.text((12, y0 + 52), "%s/%s" % (EAR_NAMES[g["ears"]], TAIL_NAMES[g["tail"]]), font=f_small, fill=(200, 190, 175))
        # checker so alpha is visible
        for j in range(cols):
            x0 = label_w + j * cell
            d.rectangle([x0, y0, x0 + cell - 6, y0 + cell - 6], fill=(112, 142, 92) if (i + j) % 2 else (104, 132, 86))
        for j, fr in enumerate(FRAMES):
            spr = render(g, fr, 1)
            simg = Image.fromarray(spr).resize((B * zoom, Hs * zoom), Image.LANCZOS)
            im.paste(simg, (label_w + j * cell + 3 + (cell - 6 - B * zoom) // 2, y0 + 3), simg)
        for k, t in enumerate((0, 1, 2)):
            spr = render(g, "idle0", t)
            bt = TIER_PX[t]
            ht = int(round(bt * ASPECT))
            simg = Image.fromarray(spr).resize((bt * zoom, ht * zoom), Image.LANCZOS)
            x0 = label_w + (len(FRAMES) + k) * cell + 3 + (cell - 6 - bt * zoom) // 2
            im.paste(simg, (x0, y0 + 3 + (Hs - ht) * zoom), simg)
    d.text((10, Hd - 24), "SPROUTS  studio-a  tier1 = 40 px shown at %dx  (lanczos)" % zoom, font=f_small, fill=(200, 190, 175))
    im.save(path)
    return path


if __name__ == "__main__":
    print(write_sheet())
