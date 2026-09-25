"""creatures.py - settlers-round: ROUND-HEAD SETTLERS for the SETTLEMENT top-down world.

Every settler is a real chatter. Identity is procedural and deterministic from the username:

    hue        31-multiplier hash of the lower-cased name -> a hue on a 270 degree wheel that SKIPS the grass band
               (70-160) so a settler is always a lit colour against the meadow, even as a dot at 320x180.
               The hue is the TUNIC, so labels, roofs and fields match the person.
    genome     sha1(name) -> hair style (bob / tuft / cap / hood / flower), hair yarn colour, accessory
               (none / scarf / belt / satchel / badge / apron), cheeks (blush / freckles / plain), eye set,
               which side things lean to, the elder's hat, and the accent colour offset.

Silhouette language ("toy people"): a big ROUND head (~45 % of the height), a short flared tunic torso, two
stubby legs with round shoes, two noodle arms with mitten hands, all seen from the front in the 3/4 top-down view.
Face is a warm cream (not a skin tone: the same cream for everyone, tinted 10 % toward the tunic), two ink dot
eyes with eyelids, a small mouth, blush. Hair is a yarn colour, hats are the accent. Every part carries its own
1-2 px dark outline (drawn at 4x, downsampled premultiplied) so a 30 px person survives a 3 Mbps encode.
Stylised, friendly, gender-neutral by default: nothing here is a real-world ethnicity, nothing is a franchise.

Frames (19):
    idle0 idle1 (breath)  look (head + pupils toward +x; flip for -x)  blink
    walk0 walk1 walk2 walk3 (real 4-frame cycle: contact L, pass, contact R, pass; arms swing opposite)
    hop (squash 0.90 x 1.12, lift 0.30, arms up, legs tucked, shadow shrinks)
    wave (one arm over the head)   sit (legs forward, body lowered)   sleep (curled on the ground, zz)
    carry_berry carry_stone carry_tool (arms forward around the item)
    speak0 speak1 (mouth notch + head bob)   joy (arc eyes, arms up, sparkles)   love (heart)
Tiers: 0 sprout 26 px / 2.0 heads · 1 settler 30 px / 2.25 · 2 builder 34 px / 2.25 (+ accessory) ·
       3 elder 42 px / 2.9 heads (+1 head of height, hat and cape).

    import creatures
    sheet = creatures.settler_sheet("sami.exe", tier=2, zoom=1)     # {frame: PIL RGBA}, cached
    g = creatures.genome("sami.exe")
    arr = creatures.frame("sami.exe", 2, "walk1", facing=-1)         # numpy (H, W, 4), cached
    ax, ay = creatures.anchor(2)                                     # ground point inside the frame

numpy + pillow only. Light comes from the top-left (Studio A's dusk convention): a warm rim on the sun side,
a cool shade band on the far side, and the ground shadow slides away from the sun.
"""
from __future__ import annotations

import colorsys
import hashlib
import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

FRAMES = ("idle0", "idle1", "look", "blink", "walk0", "walk1", "walk2", "walk3", "hop", "wave", "sit", "sleep",
          "carry_berry", "carry_stone", "carry_tool", "speak0", "speak1", "joy", "love")
TIERS: Dict[int, Dict] = {
    0: {"name": "sprout", "h": 26, "heads": 2.0},
    1: {"name": "settler", "h": 30, "heads": 2.25},
    2: {"name": "builder", "h": 34, "heads": 2.25},
    3: {"name": "elder", "h": 42, "heads": 2.9},
}
TIER_NAMES = tuple(TIERS[t]["name"] for t in range(4))
HAIR_NAMES = ("bob", "tuft", "cap", "hood", "flower")
ACC_NAMES = ("none", "scarf", "belt", "satchel", "badge", "apron")
CHEEK_NAMES = ("blush", "freckles", "plain")
EYE_NAMES = ("dots", "tall", "wide")
HAT_NAMES = ("brim", "tall")

SS = 4
CREAM = (250, 236, 212)
INK = (38, 30, 28)
WHITE = (255, 252, 246)
BLUSH = (238, 126, 130)
FRECKLE = (196, 132, 104)
HEART = (236, 84, 104)
SHADOW = (24, 18, 12)
SPARK = (255, 228, 120)
BERRY = (222, 64, 82)
STONE = (160, 156, 146)
WOOD = (150, 106, 66)
IRON = (120, 124, 132)
YARN = ((74, 52, 46), (170, 98, 60), (236, 198, 100), (246, 238, 222), (96, 64, 92), None)   # None = accent
SUN = (-0.62, -0.78)       # screen-space unit vector toward the sun (top-left)

_CACHE: Dict[Tuple, np.ndarray] = {}
_SHEETS: Dict[Tuple, Dict[str, Image.Image]] = {}


# ----------------------------------------------------------------------------- identity
def name_hash(name: str) -> int:
    s = 0
    for ch in (name or "").lower():
        s = (s * 31 + ord(ch)) & 0xFFFFFFFF
    return s


def genome(name: str) -> Dict[str, int]:
    h = hashlib.sha1((name or "").lower().encode("utf-8")).digest()
    return {"hair": (h[0] + h[9]) % 5, "yarn": h[1] % 6, "acc": 1 + h[2] % 5, "cheeks": h[3] % 3, "eyes": h[4] % 3,
            "side": 1 if h[5] % 2 else -1, "accent_shift": h[6] % 3, "hat": h[7] % 2, "item": h[8] % 3}


def hue(name: str) -> float:
    frac = (name_hash(name) % 1000) / 1000.0
    h = frac * 270.0
    if h >= 70.0:
        h += 90.0          # skip the grass band 70-160 (lime to teal-green)
    return h % 360.0


def _hsv(h: float, s: float, v: float) -> Tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def _mix(a, b, t: float) -> Tuple[int, int, int]:
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))


def palette(name: str) -> Dict:
    g = genome(name)
    h = hue(name)
    main = _hsv(h, 0.64, 0.90)
    ah = (h + 150 + 40 * g["accent_shift"]) % 360
    if 70 <= ah <= 160:
        ah = (ah + 90) % 360
    accent = _hsv(ah, 0.60, 0.92)
    outline = _mix(_hsv(h, 0.60, 0.30), INK, 0.50)
    yarn = YARN[g["yarn"]] or accent
    return {"main": main, "accent": accent, "outline": outline, "hue": h,
            "tunic_dark": _mix(main, outline, 0.22),
            "legs": _mix(_hsv(h, 0.45, 0.42), (90, 70, 60), 0.5),
            "shoes": _mix(outline, (70, 48, 40), 0.5),
            "face": _mix(CREAM, main, 0.10),
            "hair": yarn, "hair_outline": _mix(yarn, INK, 0.55),
            "cape": _mix(accent, outline, 0.35)}


def colour_hex(name: str) -> str:
    return "#%02X%02X%02X" % palette(name)["main"]


def describe(name: str) -> str:
    g = genome(name)
    return "%s hair · %s · %s cheeks · %s eyes · hue %d" % (
        HAIR_NAMES[g["hair"]], ACC_NAMES[g["acc"]], CHEEK_NAMES[g["cheeks"]], EYE_NAMES[g["eyes"]], int(hue(name)))


# ----------------------------------------------------------------------------- animation table
# body: sx sy squash about the ground point, dy lift (body heights). head_dx/head_dy: extra head offset (turn/bob).
# arms: rest swingL swingR up wave carry sit.  legs: stand liftL liftR pass tuck sit.  pose: stand | sleep.
_ANIM: Dict[str, Dict] = {
    "idle0": dict(sx=1.00, sy=1.00, dy=0.0, arms="rest", legs="stand", eyes="open", mouth="smile"),
    "idle1": dict(sx=1.03, sy=0.97, dy=0.0, arms="rest", legs="stand", eyes="open", mouth="smile", head_dy=-0.01),
    "look": dict(sx=1.00, sy=1.00, dy=0.0, arms="rest", legs="stand", eyes="open", mouth="smile", head_dx=0.045, look=0.03),
    "blink": dict(sx=1.00, sy=1.00, dy=0.0, arms="rest", legs="stand", eyes="blink", mouth="smile"),
    "walk0": dict(sx=1.00, sy=1.00, dy=0.0, arms="swingL", legs="liftL", eyes="open", mouth="smile", rot=-3),
    "walk1": dict(sx=0.99, sy=1.02, dy=0.02, arms="rest", legs="pass", eyes="open", mouth="smile"),
    "walk2": dict(sx=1.00, sy=1.00, dy=0.0, arms="swingR", legs="liftR", eyes="open", mouth="smile", rot=3),
    "walk3": dict(sx=0.99, sy=1.02, dy=0.02, arms="rest", legs="pass", eyes="open", mouth="smile"),
    "hop": dict(sx=0.90, sy=1.12, dy=0.30, arms="up", legs="tuck", eyes="big", mouth="o", shadow=0.65),
    "wave": dict(sx=1.00, sy=1.00, dy=0.0, arms="wave", legs="stand", eyes="open", mouth="grin", head_dx=-0.012),
    "sit": dict(sx=1.02, sy=1.00, dy=0.0, arms="sit", legs="sit", eyes="open", mouth="smile", drop=0.13, shadow=1.05),
    "sleep": dict(pose="sleep", eyes="sleep", mouth="flat", shadow=1.15, extra="zz"),
    "carry_berry": dict(sx=1.00, sy=1.00, dy=0.0, arms="carry", legs="stand", eyes="open", mouth="smile", item="berry"),
    "carry_stone": dict(sx=1.02, sy=0.98, dy=0.0, arms="carry", legs="stand", eyes="open", mouth="flat", item="stone"),
    "carry_tool": dict(sx=1.00, sy=1.00, dy=0.0, arms="carry", legs="stand", eyes="open", mouth="smile", item="tool"),
    "speak0": dict(sx=1.00, sy=1.00, dy=0.0, arms="rest", legs="stand", eyes="open", mouth="o", head_dy=0.02),
    "speak1": dict(sx=1.01, sy=1.00, dy=0.0, arms="rest", legs="stand", eyes="open", mouth="notch", head_dy=0.0),
    "joy": dict(sx=0.98, sy=1.05, dy=0.05, arms="up", legs="stand", eyes="joy", mouth="grin", extra="sparkle"),
    "love": dict(sx=1.01, sy=1.00, dy=0.01, arms="rest", legs="stand", eyes="big", mouth="w", extra="heart"),
}


# ----------------------------------------------------------------------------- drawing helpers
class _Canvas:
    def __init__(self, S: float, ss: int = SS):
        self.S = S
        self.ss = ss
        self.W = int(round(1.6 * S))
        self.H = int(round(1.72 * S))
        self.ow = max(1.0, S / 26.0)                   # outline width in output px (1.0 at 26 px, 1.3 at 34, 2.6 at 2x)
        self.cx = self.W * ss / 2.0
        self.gy = (self.H - 0.14 * S) * ss             # ground line (ss px)
        self.layer = Image.new("RGBA", (self.W * ss, self.H * ss), (0, 0, 0, 0))
        self.shadow = Image.new("RGBA", (self.W * ss, self.H * ss), (0, 0, 0, 0))
        self.sx = self.sy = 1.0
        self.dy = 0.0

    def P(self, x: float, y: float) -> Tuple[float, float]:
        return (self.cx + x * self.S * self.sx * self.ss, self.gy - (y * self.sy + self.dy) * self.S * self.ss)

    def mask(self) -> Image.Image:
        return Image.new("L", self.layer.size, 0)

    def paint(self, m: Image.Image, fill, outline=None, ow: float = None, alpha: int = 255):
        ow = self.ow if ow is None else ow
        if outline is not None and ow > 0:
            dil = _morph(m, int(2 * round(ow * self.ss) + 1), ImageFilter.MaxFilter)
            self.layer.paste(tuple(outline) + (255,), (0, 0), dil)
        if alpha < 255:
            m = m.point(lambda v: v * alpha // 255)
        self.layer.paste(tuple(fill) + (255,), (0, 0), m)

    def ellipse(self, m, cx, cy, rx, ry, rot=0.0):
        d = ImageDraw.Draw(m)
        if abs(rot) < 1e-6:
            x0, y0 = self.P(cx - rx, cy + ry)
            x1, y1 = self.P(cx + rx, cy - ry)
            d.ellipse([x0, y0, x1, y1], fill=255)
        else:
            pts = []
            rr = math.radians(rot)
            for k in range(40):
                a = 2 * math.pi * k / 40
                ex, ey = rx * math.cos(a), ry * math.sin(a)
                pts.append(self.P(cx + ex * math.cos(rr) - ey * math.sin(rr), cy + ex * math.sin(rr) + ey * math.cos(rr)))
            d.polygon(pts, fill=255)
        return m

    def poly(self, m, pts):
        ImageDraw.Draw(m).polygon([self.P(*p) for p in pts], fill=255)
        return m

    def rrect(self, m, x0, y0, x1, y1, r):
        d = ImageDraw.Draw(m)
        ax, ay = self.P(x0, y1)
        bx, by = self.P(x1, y0)
        d.rounded_rectangle([ax, ay, bx, by], radius=r * self.S * self.ss, fill=255)
        return m

    def stroke(self, m, pts, width):
        d = ImageDraw.Draw(m)
        w = max(1, int(round(width * self.S * self.ss)))
        p = [self.P(*q) for q in pts]
        d.line(p, fill=255, width=w, joint="curve")
        r = w / 2.0
        for (x, y) in (p[0], p[-1]):
            d.ellipse([x - r, y - r, x + r, y + r], fill=255)
        return m

    def arc(self, m, cx, cy, rx, ry, a0, a1, width):
        d = ImageDraw.Draw(m)
        x0, y0 = self.P(cx - rx, cy + ry)
        x1, y1 = self.P(cx + rx, cy - ry)
        w = max(1, int(round(width * self.S * self.ss)))
        d.arc([x0, y0, x1, y1], a0, a1, fill=255, width=w)
        return m

    def cut(self, m: Image.Image, hole: Image.Image) -> Image.Image:
        return ImageChops.subtract(m, hole)


def _morph(m: Image.Image, size: int, flt) -> Image.Image:
    bb = m.getbbox()
    if bb is None:
        return m
    pad = size
    x0, y0 = max(0, bb[0] - pad), max(0, bb[1] - pad)
    x1, y1 = min(m.width, bb[2] + pad), min(m.height, bb[3] + pad)
    crop = m.crop((x0, y0, x1, y1)).filter(flt(size))
    out = Image.new("L", m.size, 0)
    out.paste(crop, (x0, y0))
    return out


# ----------------------------------------------------------------------------- body geometry
class _Geo:
    """Proportions in body heights for one tier. y is up from the ground point."""

    def __init__(self, tier: int):
        t = TIERS[tier]
        self.tier = tier
        self.heads = t["heads"]
        self.R = 0.5 / self.heads                       # head radius
        self.hy = 1.0 - self.R                          # head centre
        self.top = self.hy - self.R + 0.10 * self.R * 2  # torso top tucks under the head
        self.hem = 0.19 if tier else 0.21
        self.ws = 0.155 if tier else 0.15               # shoulder half width
        self.wh = 0.205 if tier else 0.20               # hem half width
        self.leg_x = 0.085
        self.leg_w = 0.052 if tier else 0.058
        self.arm_w = 0.085 if tier else 0.09
        self.hand_r = 0.052 if tier else 0.056
        self.sh_y = self.top - 0.05                     # shoulder pivot


# ----------------------------------------------------------------------------- parts
def _legs(c: _Canvas, g: _Geo, state: str, pal, drop: float):
    lx, lw = g.leg_x, g.leg_w
    m = c.mask()
    shoes = c.mask()
    if state == "sit":
        # legs forward: two short strokes from the hip down and toward the viewer, shoes at the front
        for sgn in (-1, 1):
            c.stroke(m, [(sgn * lx, g.hem - drop + 0.02), (sgn * (lx + 0.06), 0.045)], lw * 2)
            c.ellipse(shoes, sgn * (lx + 0.075), 0.035, 0.075, 0.045)
        c.paint(m, pal["legs"], pal["outline"])
        c.paint(shoes, pal["shoes"], pal["outline"])
        return
    if state == "tuck":
        for sgn in (-1, 1):
            c.stroke(m, [(sgn * lx, g.hem + 0.02), (sgn * (lx + 0.02), 0.09)], lw * 2)
            c.ellipse(shoes, sgn * (lx + 0.04), 0.06, 0.07, 0.042, rot=-25 * sgn)
        c.paint(m, pal["legs"], pal["outline"])
        c.paint(shoes, pal["shoes"], pal["outline"])
        return
    lift = {"stand": (0.0, 0.0), "pass": (0.0, 0.0), "liftL": (0.075, 0.0), "liftR": (0.0, 0.075)}[state]
    for sgn, up in ((-1, lift[0]), (1, lift[1])):
        c.stroke(m, [(sgn * lx, g.hem + 0.03), (sgn * lx, 0.05 + up)], lw * 2)
        c.ellipse(shoes, sgn * lx + (0.012 * sgn if up else 0), 0.03 + up, 0.072, 0.042)
    c.paint(m, pal["legs"], pal["outline"])
    c.paint(shoes, pal["shoes"], pal["outline"])


def _torso(c: _Canvas, g: _Geo, pal, drop: float) -> Image.Image:
    top, hem = g.top - drop, g.hem - drop
    m = c.mask()
    c.poly(m, [(-g.ws, top), (g.ws, top), (g.wh, hem), (-g.wh, hem)])
    c.ellipse(m, 0.0, hem, g.wh, 0.045)
    c.ellipse(m, 0.0, top, g.ws, 0.05)
    c.paint(m, pal["main"], pal["outline"])
    # hem shade: a darker band along the bottom of the tunic (rim/fold)
    band = c.mask()
    c.poly(band, [(-g.wh - 0.02, hem + 0.045), (g.wh + 0.02, hem + 0.045), (g.wh + 0.02, hem - 0.06), (-g.wh - 0.02, hem - 0.06)])
    inner = _morph(m, int(2 * round(c.ow * c.ss) + 1), ImageFilter.MinFilter)
    c.paint(ImageChops.multiply(band, inner), pal["tunic_dark"])
    return m


def _cape(c: _Canvas, g: _Geo, pal, drop: float, arms: str):
    top, bottom = g.sh_y - drop + 0.02, 0.06
    flare = 0.30 if arms != "hop" else 0.34
    m = c.mask()
    c.poly(m, [(-g.ws - 0.02, top), (g.ws + 0.02, top), (flare, bottom), (-flare, bottom)])
    c.ellipse(m, 0.0, bottom, flare, 0.05)
    c.paint(m, pal["cape"], pal["outline"])


def _arm(c: _Canvas, g: _Geo, sgn: int, hand: Tuple[float, float], pal, drop: float, elbow: Optional[Tuple[float, float]] = None):
    sh = (sgn * g.ws * 0.92, g.sh_y - drop)
    m = c.mask()
    pts = [sh, elbow, hand] if elbow else [sh, hand]
    c.stroke(m, pts, g.arm_w)
    c.paint(m, pal["main"], pal["outline"])


def _hand(c: _Canvas, g: _Geo, pos: Tuple[float, float], pal):
    m = c.mask()
    c.ellipse(m, pos[0], pos[1], g.hand_r, g.hand_r)
    c.paint(m, pal["face"], pal["outline"])


def _arm_targets(g: _Geo, state: str, side: int, drop: float) -> Dict[int, Tuple]:
    """Hand position (and optional elbow) per arm sign for an arm pose."""
    rest_y = g.hem + 0.10
    out = {-1: ((-g.wh - 0.035, rest_y - drop), None), 1: ((g.wh + 0.035, rest_y - drop), None)}
    if state == "swingL":
        out[-1] = ((-g.wh - 0.06, rest_y + 0.06), None)
        out[1] = ((g.wh + 0.02, rest_y - 0.05), None)
    elif state == "swingR":
        out[1] = ((g.wh + 0.06, rest_y + 0.06), None)
        out[-1] = ((-g.wh - 0.02, rest_y - 0.05), None)
    elif state == "up":
        for sgn in (-1, 1):
            out[sgn] = ((sgn * (g.R + 0.14), g.hy + g.R * 0.35), (sgn * (g.ws + 0.10), g.sh_y + 0.06))
    elif state == "wave":
        out[side] = ((side * (g.R + 0.13), g.hy + g.R + 0.02), (side * (g.ws + 0.12), g.sh_y + 0.10))
    elif state == "carry":
        for sgn in (-1, 1):
            out[sgn] = ((sgn * 0.075, g.hem + 0.20), (sgn * (g.ws + 0.06), g.sh_y - 0.09))
    elif state == "sit":
        for sgn in (-1, 1):
            out[sgn] = ((sgn * (g.leg_x + 0.05), 0.12), None)
    return out


def _head(c: _Canvas, g: _Geo, hx: float, hy: float, pal) -> Image.Image:
    m = c.mask()
    c.ellipse(m, hx, hy, g.R, g.R)
    c.paint(m, pal["face"], pal["outline"])
    return m


def _hair(c: _Canvas, g: _Geo, kind: int, hx: float, hy: float, pal, side: int, tier: int, state: str):
    R = g.R
    col, oc = pal["hair"], pal["hair_outline"]
    droop = state == "sleep"
    if kind == 0:      # bob: a cap that wraps the top and both sides, face window in front
        m = c.ellipse(c.mask(), hx, hy + 0.015, R + 0.02, R + 0.02)
        for sgn in (-1, 1):
            c.ellipse(m, hx + sgn * (R - 0.02), hy - R * 0.45, 0.07, R * 0.55)
        win = c.ellipse(c.mask(), hx, hy - R * 0.22, R * 0.80, R * 0.86)
        c.paint(c.cut(m, win), col, oc)
    elif kind == 1:    # tuft: three lively strokes from the crown
        m = c.mask()
        k = 1.0 if not droop else 0.6
        for j, (dx, dyy) in enumerate(((-0.11, 0.11), (0.0, 0.16), (0.11, 0.10))):
            c.stroke(m, [(hx + dx * 0.4, hy + R - 0.02), (hx + dx * k + (0.03 * side if droop else 0), hy + R + dyy * k)], 0.05)
        cap = c.ellipse(c.mask(), hx, hy + R * 0.55, R * 0.72, R * 0.36)
        m = ImageChops.lighter(m, cap)
        c.paint(m, col, oc)
    elif kind == 2:    # cap: a beanie with a rolled brim and a small bobble, in the accent colour
        m = c.ellipse(c.mask(), hx, hy + R * 0.28, R + 0.012, R * 0.78)
        lid = c.mask()
        c.poly(lid, [(hx - R - 0.1, hy - 0.5), (hx + R + 0.1, hy - 0.5), (hx + R + 0.1, hy + R * 0.22), (hx - R - 0.1, hy + R * 0.22)])
        m = c.cut(m, lid)
        c.paint(m, pal["accent"], pal["outline"])
        brim = c.rrect(c.mask(), hx - R - 0.02, hy + R * 0.16, hx + R + 0.02, hy + R * 0.34, 0.03)
        c.paint(brim, _mix(pal["accent"], pal["outline"], 0.25), pal["outline"])
        bob = c.ellipse(c.mask(), hx, hy + R + 0.03, 0.045, 0.045)
        c.paint(bob, pal["face"], pal["outline"])
    elif kind == 3:    # hood: a ring around the face with a soft point, in the accent colour
        m = c.ellipse(c.mask(), hx, hy + 0.02, R + 0.05, R + 0.05)
        c.poly(m, [(hx - 0.06, hy + R), (hx + 0.06, hy + R), (hx + 0.02 * side, hy + R + 0.10)])
        c.poly(m, [(hx - R - 0.05, hy), (hx + R + 0.05, hy), (hx + R * 0.7, hy - R - 0.06), (hx - R * 0.7, hy - R - 0.06)])
        win = c.ellipse(c.mask(), hx, hy - 0.01, R * 0.86, R * 0.90)
        c.paint(c.cut(m, win), pal["accent"], pal["outline"])
    else:              # flower: a short hair cap and a blossom tucked over one ear
        m = c.ellipse(c.mask(), hx, hy + R * 0.30, R + 0.015, R * 0.74)
        lid = c.mask()
        c.poly(lid, [(hx - R - 0.1, hy - 0.5), (hx + R + 0.1, hy - 0.5), (hx + R + 0.1, hy + R * 0.28), (hx - R - 0.1, hy + R * 0.28)])
        c.paint(c.cut(m, lid), col, oc)
        fx, fy = hx + side * (R * 0.78), hy + R * 0.42
        fm = c.mask()
        for k in range(5):
            a = 2 * math.pi * k / 5
            c.ellipse(fm, fx + 0.042 * math.cos(a), fy + 0.042 * math.sin(a), 0.032, 0.032)
        c.paint(fm, pal["accent"], pal["outline"], ow=c.ow * 0.7)
        c.paint(c.ellipse(c.mask(), fx, fy, 0.024, 0.024), SPARK)
    if tier == 3:      # elder hat, over the hair
        _hat(c, g, hx, hy, pal, side)


def _hat(c: _Canvas, g: _Geo, hx: float, hy: float, pal, side: int):
    R = g.R
    kind = pal.get("hat", 0)
    if kind == 0:      # brim hat: wide oval brim + a domed crown
        brim = c.ellipse(c.mask(), hx, hy + R * 0.62, R * 1.45, R * 0.30)
        c.paint(brim, _mix(pal["accent"], pal["outline"], 0.2), pal["outline"])
        crown = c.ellipse(c.mask(), hx, hy + R * 0.95, R * 0.78, R * 0.55)
        c.paint(crown, pal["accent"], pal["outline"])
        band = c.rrect(c.mask(), hx - R * 0.8, hy + R * 0.62, hx + R * 0.8, hy + R * 0.76, 0.01)
        c.paint(ImageChops.multiply(band, _morph(crown, int(2 * round(c.ow * c.ss) + 1), ImageFilter.MinFilter)), pal["main"])
    else:              # stocking cap: a soft dome that folds over to one side and ends in a bobble
        m = c.mask()
        c.ellipse(m, hx, hy + R * 0.62, R * 0.98, R * 0.62)
        c.stroke(m, [(hx, hy + R * 1.15), (hx + side * R * 0.55, hy + R * 1.45), (hx + side * R * 1.05, hy + R * 1.15)], R * 0.62)
        c.paint(m, pal["accent"], pal["outline"])
        c.paint(c.ellipse(c.mask(), hx + side * R * 1.15, hy + R * 1.05, 0.055, 0.055), pal["face"], pal["outline"])
        band = c.rrect(c.mask(), hx - R * 1.02, hy + R * 0.48, hx + R * 1.02, hy + R * 0.72, 0.03)
        c.paint(band, _mix(pal["accent"], pal["outline"], 0.25), pal["outline"])


def _face(c: _Canvas, g: _Geo, hx: float, hy: float, gn: Dict, eyes: str, mouth: str, look: float):
    R = g.R
    ex = {0: 0.075, 1: 0.070, 2: 0.095}[gn["eyes"]] * (R / 0.222)
    ey = hy - R * 0.10
    pr = 0.033 if gn["eyes"] != 1 else 0.030          # pupil radius: ~2 px at 34 px, 4 px at 2x
    pry = pr * (1.25 if gn["eyes"] == 1 else 1.0)
    m = c.mask()
    if eyes in ("open", "big"):
        k = 1.25 if eyes == "big" else 1.0
        for sgn in (-1, 1):
            c.ellipse(m, hx + sgn * ex + look, ey, pr * k, pry * k)
        c.paint(m, INK)
        if eyes == "big":
            hm = c.mask()
            for sgn in (-1, 1):
                c.ellipse(hm, hx + sgn * ex + look - pr * 0.35, ey + pry * 0.4, pr * 0.42, pr * 0.42)
            c.paint(hm, WHITE)
        # eyelid: a hairline over the top of each eye gives the "lid" read without covering the pupil
        lid = c.mask()
        for sgn in (-1, 1):
            c.arc(lid, hx + sgn * ex + look, ey + pry * 0.2, pr * 1.7, pry * 1.6, 205, 335, 0.016)
        c.paint(lid, INK, alpha=150)
    elif eyes == "blink":
        for sgn in (-1, 1):
            c.stroke(m, [(hx + sgn * ex - pr * 1.6, ey), (hx + sgn * ex + pr * 1.6, ey)], 0.026)
        c.paint(m, INK)
    elif eyes == "sleep":
        for sgn in (-1, 1):
            c.arc(m, hx + sgn * ex, ey + 0.02, pr * 1.8, pr * 1.6, 20, 160, 0.026)
        c.paint(m, INK)
    elif eyes == "joy":
        for sgn in (-1, 1):
            c.arc(m, hx + sgn * ex, ey - 0.025, pr * 1.9, pr * 1.9, 200, 340, 0.03)
        c.paint(m, INK)
    # cheeks
    cm = c.mask()
    if gn["cheeks"] == 0:
        for sgn in (-1, 1):
            c.ellipse(cm, hx + sgn * (ex + 0.055), ey - 0.05, 0.045, 0.03)
        c.paint(cm, BLUSH, alpha=125)
    elif gn["cheeks"] == 1:
        for sgn in (-1, 1):
            for (dx, dyy) in ((-0.02, -0.04), (0.012, -0.055), (0.035, -0.035)):
                c.ellipse(cm, hx + sgn * (ex + 0.05) + dx, ey + dyy, 0.011, 0.011)
        c.paint(cm, FRECKLE, alpha=200)
    # mouth
    my = ey - R * 0.48
    mm = c.mask()
    if mouth == "smile":
        c.arc(mm, hx, my + 0.035, 0.05, 0.04, 25, 155, 0.022)
    elif mouth == "o":
        c.ellipse(mm, hx, my, 0.036, 0.03)
    elif mouth == "notch":
        c.ellipse(mm, hx, my - 0.004, 0.026, 0.018)
    elif mouth == "grin":
        d = ImageDraw.Draw(mm)
        x0, y0 = c.P(hx - 0.07, my + 0.015)
        x1, y1 = c.P(hx + 0.07, my - 0.06)
        d.chord([x0, y0 - (y1 - y0), x1, y1], 0, 180, fill=255)
    elif mouth == "w":
        c.arc(mm, hx - 0.032, my + 0.03, 0.032, 0.032, 25, 155, 0.02)
        c.arc(mm, hx + 0.032, my + 0.03, 0.032, 0.032, 25, 155, 0.02)
    elif mouth == "flat":
        c.stroke(mm, [(hx - 0.028, my), (hx + 0.028, my)], 0.02)
    c.paint(mm, INK)


def _accessory(c: _Canvas, g: _Geo, kind: int, pal, side: int, drop: float, torso: Image.Image):
    inner = _morph(torso, int(2 * round(c.ow * c.ss) + 1), ImageFilter.MinFilter)
    top, hem = g.top - drop, g.hem - drop
    if kind == 2:      # belt
        m = c.rrect(c.mask(), -0.4, hem + (top - hem) * 0.36, 0.4, hem + (top - hem) * 0.36 + 0.045, 0.01)
        c.paint(ImageChops.multiply(m, inner), pal["accent"])
        c.paint(c.ellipse(c.mask(), 0.0, hem + (top - hem) * 0.36 + 0.022, 0.028, 0.028), SPARK, pal["outline"], ow=c.ow * 0.6)
    elif kind == 4:    # badge
        c.paint(c.ellipse(c.mask(), side * 0.08, top - 0.09, 0.034, 0.034), pal["accent"], pal["outline"], ow=c.ow * 0.7)
    elif kind == 5:    # apron
        m = c.mask()
        c.poly(m, [(-g.ws * 0.55, top - 0.04), (g.ws * 0.55, top - 0.04), (g.wh * 0.75, hem - 0.01), (-g.wh * 0.75, hem - 0.01)])
        c.paint(ImageChops.multiply(m, inner), CREAM)
        c.paint(c.stroke(c.mask(), [(-g.ws * 0.55, top - 0.04), (g.ws * 0.55, top - 0.04)], 0.022), pal["accent"])
    elif kind == 3:    # satchel: a small bag on the hip with a strap across the chest
        c.paint(c.stroke(c.mask(), [(-side * g.ws * 0.8, top + 0.01), (side * g.wh * 0.9, hem + 0.06)], 0.035), WOOD, pal["outline"], ow=c.ow * 0.7)
        c.paint(c.rrect(c.mask(), side * g.wh * 0.55 - 0.06, hem - 0.02, side * g.wh * 0.55 + 0.06, hem + 0.09, 0.025), WOOD, pal["outline"])
        c.paint(c.rrect(c.mask(), side * g.wh * 0.55 - 0.06, hem + 0.05, side * g.wh * 0.55 + 0.06, hem + 0.09, 0.02), _mix(WOOD, INK, 0.3))


def _scarf(c: _Canvas, g: _Geo, pal, side: int, drop: float):
    top = g.top - drop
    m = c.rrect(c.mask(), -g.ws - 0.03, top - 0.02, g.ws + 0.03, top + 0.06, 0.04)
    c.paint(m, pal["accent"], pal["outline"])
    tail = c.stroke(c.mask(), [(side * g.ws * 0.6, top + 0.01), (side * (g.ws + 0.10), top - 0.12)], 0.06)
    c.paint(tail, pal["accent"], pal["outline"])


def _item(c: _Canvas, g: _Geo, kind: str, pal, side: int):
    y = g.hem + 0.21
    if kind == "berry":
        m = c.mask()
        for (dx, dyy) in ((-0.04, 0.0), (0.04, 0.0), (0.0, 0.05), (0.0, -0.03)):
            c.ellipse(m, dx, y + dyy, 0.038, 0.038)
        c.paint(m, BERRY, pal["outline"], ow=c.ow * 0.8)
        c.paint(c.ellipse(c.mask(), -0.015, y + 0.03, 0.035, 0.016, rot=-30), (120, 170, 80), pal["outline"], ow=c.ow * 0.6)
    elif kind == "stone":
        m = c.ellipse(c.mask(), 0.0, y, 0.10, 0.07)
        c.paint(m, STONE, pal["outline"])
        c.paint(c.ellipse(c.mask(), -0.03, y + 0.02, 0.04, 0.02), _mix(STONE, WHITE, 0.4))
    else:  # tool: a hafted mallet, held diagonally
        c.paint(c.stroke(c.mask(), [(-side * 0.13, y - 0.13), (side * 0.10, y + 0.12)], 0.035), WOOD, pal["outline"], ow=c.ow * 0.8)
        c.paint(c.rrect(c.mask(), side * 0.10 - 0.07, y + 0.07, side * 0.10 + 0.07, y + 0.16, 0.02), IRON, pal["outline"])


def _extras(c: _Canvas, g: _Geo, kind: str, pal, side: int, hx: float, hy: float):
    R = g.R
    if kind == "sparkle":
        m = c.mask()
        for (x, y, r) in ((-R - 0.20, hy + R * 0.6, 0.07), (R + 0.20, hy + R * 0.2, 0.055)):
            pts = []
            for k in range(8):
                a = math.pi / 4 * k
                rr = r if k % 2 == 0 else r * 0.38
                pts.append((x + rr * math.cos(a), y + rr * math.sin(a)))
            c.poly(m, pts)
        c.paint(m, SPARK, pal["outline"], ow=c.ow * 0.6)
    elif kind == "heart":
        m = c.mask()
        x, y, r = hx + side * (R + 0.16), hy + R * 0.9, 0.075
        c.ellipse(m, x - r * 0.55, y + r * 0.35, r * 0.6, r * 0.6)
        c.ellipse(m, x + r * 0.55, y + r * 0.35, r * 0.6, r * 0.6)
        c.poly(m, [(x - r * 1.12, y + r * 0.25), (x + r * 1.12, y + r * 0.25), (x, y - r * 0.95)])
        c.paint(m, HEART, pal["outline"], ow=c.ow * 0.6)
    elif kind == "zz":
        m = c.mask()
        for j, (x, y, s) in enumerate(((hx + 0.16, hy + 0.20, 0.06), (hx + 0.27, hy + 0.32, 0.08))):
            c.stroke(m, [(x - s / 2, y + s / 2), (x + s / 2, y + s / 2), (x - s / 2, y - s / 2), (x + s / 2, y - s / 2)], 0.022)
        c.paint(m, WHITE, pal["outline"], ow=c.ow * 0.5)


# ----------------------------------------------------------------------------- lighting + downsample
def _light(layer: Image.Image, S: float, ss: int) -> Image.Image:
    """Directional shading from the sun vector: a warm rim on the lit edge, a cool shade band on the far edge."""
    a = np.asarray(layer, dtype=np.float32)
    alpha = a[..., 3]
    mask = alpha > 100
    k = max(2, int(round(0.055 * S * ss)))
    dx, dy = int(round(SUN[0] * k)), int(round(SUN[1] * k))

    def shift(m, sx, sy):
        out = np.zeros_like(m)
        h, w = m.shape
        ys0, ys1 = max(0, sy), min(h, h + sy)
        xs0, xs1 = max(0, sx), min(w, w + sx)
        out[ys0:ys1, xs0:xs1] = m[ys0 - sy:ys1 - sy, xs0 - sx:xs1 - sx]
        return out

    rim = mask & ~shift(mask, -dx, -dy)          # pixels whose sun-side neighbour is empty: the lit edge
    shade = mask & ~shift(mask, dx, dy)          # far edge
    rim_f = np.asarray(Image.fromarray((rim * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6 * ss)), np.float32) / 255.0
    shade_f = np.asarray(Image.fromarray((shade * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8 * ss)), np.float32) / 255.0
    rgb = a[..., :3]
    warm = np.array((255, 226, 170), np.float32)
    cool = np.array((60, 50, 90), np.float32)
    rgb = rgb * (1 - 0.30 * rim_f[..., None]) + warm * 0.30 * rim_f[..., None] * (rgb / 255.0 * 0.6 + 0.4)
    rgb = rgb * (1 - 0.28 * shade_f[..., None]) + cool * 0.28 * shade_f[..., None] * (rgb / 255.0)
    a[..., :3] = np.clip(rgb, 0, 255)
    return Image.fromarray(a.astype(np.uint8))


def _downsample_premult(img: Image.Image, W: int, H: int) -> np.ndarray:
    a = np.asarray(img, dtype=np.float32)
    al = a[..., 3:4] / 255.0
    pm = a[..., :3] * al
    chans = [np.asarray(Image.fromarray(np.ascontiguousarray(pm[..., k])).resize((W, H), Image.Resampling.LANCZOS)) for k in range(3)]
    alpha = np.clip(np.asarray(Image.fromarray(np.ascontiguousarray(a[..., 3])).resize((W, H), Image.Resampling.LANCZOS)), 0, 255)
    rgb = np.stack(chans, -1)
    out = np.zeros((H, W, 4), np.uint8)
    nz = alpha > 0.5
    rgb[nz] = rgb[nz] / (alpha[nz][..., None] / 255.0)
    out[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    out[..., 3] = alpha.astype(np.uint8)
    return out


# ----------------------------------------------------------------------------- frame render
def _ground_shadow(c: _Canvas, S: float, scale: float, lifted: bool, wide: float = 0.34):
    sm = Image.new("L", c.shadow.size, 0)
    d = ImageDraw.Draw(sm)
    rx, ry = wide * S * c.ss * scale, 0.10 * S * c.ss * scale
    ox = -SUN[0] * 0.05 * S * c.ss     # the shadow slides away from the sun
    d.ellipse([c.cx + ox - rx, c.gy - ry, c.cx + ox + rx, c.gy + ry], fill=255)
    sm = sm.filter(ImageFilter.GaussianBlur(1.1 * c.ss))
    c.shadow.paste(SHADOW + (255,), (0, 0), sm.point(lambda v: v * (60 if lifted else 92) // 255))


def _render_sleep(c: _Canvas, g: _Geo, gn: Dict, pal, tier: int):
    side = gn["side"]
    # curled on the ground: a rounded tunic lump, head at one end, tucked legs, one hand under the cheek
    hx, hy = -side * 0.19, g.R * 0.88
    body = c.mask()
    c.ellipse(body, side * 0.10, 0.12, 0.30, 0.13)
    c.paint(body, pal["main"], pal["outline"])
    legs = c.mask()
    for j in (0, 1):
        c.ellipse(legs, side * (0.34 + 0.02 * j), 0.05 + 0.055 * j, 0.075, 0.042)
    c.paint(legs, pal["shoes"], pal["outline"])
    # blanket: a soft rounded cover over the body in the accent colour, with a folded edge toward the head
    blanket = c.mask()
    c.rrect(blanket, side * 0.10 - 0.26 if side > 0 else -side * 0.10 - 0.30, 0.03, side * 0.10 + 0.30 if side > 0 else -side * 0.10 + 0.26, 0.24, 0.09)
    c.paint(blanket, pal["accent"], pal["outline"])
    fold = c.mask()
    fx = -side * 0.16
    c.rrect(fold, min(fx - 0.03, fx + 0.03 * side), 0.16, max(fx - 0.03, fx + 0.03 * side) + 0.02, 0.24, 0.02)
    c.paint(ImageChops.multiply(fold, _morph(blanket, int(2 * round(c.ow * c.ss) + 1), ImageFilter.MinFilter)), _mix(pal["accent"], WHITE, 0.35))
    _head(c, g, hx, hy, pal)
    _hair(c, g, gn["hair"], hx, hy, pal, side, tier, "sleep")
    _hand(c, g, (hx + side * (g.R * 0.75), hy - g.R * 0.55), pal)
    _face(c, g, hx, hy, gn, "sleep", "flat", 0.0)
    _extras(c, g, "zz", pal, side, hx + (0.05 if side > 0 else -0.55), hy)


def _render(name: str, tier: int, frame_name: str, zoom: int) -> np.ndarray:
    gn = genome(name)
    pal = dict(palette(name))
    pal["hat"] = gn["hat"]
    an = _ANIM[frame_name]
    S = TIERS[tier]["h"] * zoom
    g = _Geo(tier)
    c = _Canvas(S, max(2, SS // zoom))          # constant working resolution: 2x zoom renders at 2x supersample
    side = gn["side"]
    if an.get("pose") == "sleep":
        _ground_shadow(c, S, an.get("shadow", 1.0), False, wide=0.46)
        _render_sleep(c, g, gn, pal, tier)
        out = Image.alpha_composite(c.shadow, _light(c.layer, S, c.ss))
        return _downsample_premult(out, c.W, c.H)

    c.sx, c.sy, c.dy = an["sx"], an["sy"], an["dy"]
    drop = an.get("drop", 0.0)
    _ground_shadow(c, S, an.get("shadow", 1.0), frame_name == "hop")
    arms = an["arms"]
    targets = _arm_targets(g, arms, side, drop)
    if tier == 3:
        _cape(c, g, pal, drop, "hop" if frame_name == "hop" else arms)
    _legs(c, g, an["legs"], pal, drop)
    torso = _torso(c, g, pal, drop)
    if tier >= 2:
        _accessory(c, g, gn["acc"], pal, side, drop, torso)
    for sgn in (-1, 1):
        hand, elbow = targets[sgn]
        _arm(c, g, sgn, hand, pal, drop, elbow)
    if an.get("item"):
        _item(c, g, an["item"], pal, side)
    for sgn in (-1, 1):
        _hand(c, g, targets[sgn][0], pal)
    if tier >= 2 and gn["acc"] == 1:
        _scarf(c, g, pal, side, drop)
    hx = an.get("head_dx", 0.0)
    hy = g.hy - drop + an.get("head_dy", 0.0)
    _head(c, g, hx, hy, pal)
    _hair(c, g, gn["hair"], hx, hy, pal, side, tier, frame_name)
    _face(c, g, hx, hy, gn, an["eyes"], an["mouth"], an.get("look", 0.0))
    if an.get("extra"):
        _extras(c, g, an["extra"], pal, side, hx, hy)
    layer = _light(c.layer, S, c.ss)
    if an.get("rot"):
        layer = layer.rotate(an["rot"], resample=Image.Resampling.BICUBIC, center=(c.cx, c.gy))
    out = Image.alpha_composite(c.shadow, layer)
    return _downsample_premult(out, c.W, c.H)


# ----------------------------------------------------------------------------- public API
def frame(name: str, tier: int, frame_name: str, facing: int = 1, zoom: int = 1) -> np.ndarray:
    key = ((name or "").lower(), int(tier), frame_name, int(zoom))
    arr = _CACHE.get(key)
    if arr is None:
        arr = _render(name, tier, frame_name, zoom)
        _CACHE[key] = arr
    return arr if facing >= 0 else arr[:, ::-1].copy()


def size(tier: int, zoom: int = 1) -> Tuple[int, int]:
    S = TIERS[tier]["h"] * zoom
    return int(round(1.6 * S)), int(round(1.72 * S))


def anchor(tier: int, zoom: int = 1) -> Tuple[int, int]:
    """(x, y) of the ground point inside a frame of this tier (the feet touch here)."""
    S = TIERS[tier]["h"] * zoom
    W, H = size(tier, zoom)
    return W // 2, int(round(H - 0.14 * S))


def settler_sheet(username: str, tier: int, zoom: int = 1) -> Dict[str, Image.Image]:
    """All frames of one settler at one tier and zoom, as PIL RGBA images. Cached; the compositor blits these."""
    key = ((username or "").lower(), int(tier), int(zoom))
    sh = _SHEETS.get(key)
    if sh is None:
        sh = {f: Image.fromarray(frame(username, tier, f, 1, zoom)) for f in FRAMES}
        _SHEETS[key] = sh
    return sh


def sheet(name: str, tiers: Sequence[int] = (0, 1, 2, 3), frames: Sequence[str] = FRAMES, zoom: int = 1) -> Dict:
    out = {"name": name, "genome": genome(name), "palette": palette(name), "tiers": {}}
    for t in tiers:
        out["tiers"][t] = {"size": size(t, zoom), "anchor": anchor(t, zoom), "frames": {f: frame(name, t, f, 1, zoom) for f in frames}}
    return out


def head_icon(name: str, px: int = 22) -> Image.Image:
    """The settler's head only (hair + face), for name pills and chat rows. Rendered from the idle0 frame at 2x."""
    t = 2
    arr = frame(name, t, "idle0", 1, 2)
    S = TIERS[t]["h"] * 2
    ax, ay = anchor(t, 2)
    g = _Geo(t)
    R = g.R * S
    cy = ay - g.hy * S
    x0, x1 = int(ax - R * 1.35), int(ax + R * 1.35)
    y0, y1 = int(cy - R * 1.6), int(cy + R * 1.15)
    im = Image.fromarray(arr).crop((x0, y0, x1, y1))
    return im.resize((px, int(px * im.height / im.width)), Image.Resampling.LANCZOS)


# ----------------------------------------------------------------------------- contact sheet
def sheet_image(names: Sequence[str], bg=(98, 152, 82)) -> Image.Image:
    """12 settlers x all 19 frames at 1x and 2x, plus the four tiers. Names are examples."""
    from PIL import ImageFont
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Verdana Bold.ttf", 20)
    small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Verdana.ttf", 20)
    label_w = 250
    c2 = 118
    row1, row2 = 78, 150
    W = label_w + len(FRAMES) * c2 + 4 * 130 + 30
    block = row1 + row2 + 14
    H = 44 + len(names) * block
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    for i, f in enumerate(FRAMES):
        d.text((label_w + i * c2 + 4, 10), f, font=small, fill=(20, 30, 16))
    d.text((label_w + len(FRAMES) * c2 + 8, 10), "tiers 0-3 (idle0)", font=small, fill=(20, 30, 16))
    for r, name in enumerate(names):
        y0 = 44 + r * block
        if r % 2 == 0:
            d.rectangle([0, y0, W, y0 + block - 4], fill=tuple(int(v * 0.93) for v in bg))
        pal = palette(name)
        gn = genome(name)
        tier = 2 if r % 4 != 3 else 3
        d.rectangle([12, y0 + 10, 40, y0 + 38], fill=pal["main"], outline=pal["outline"], width=2)
        d.rectangle([12, y0 + 44, 40, y0 + 72], fill=pal["accent"], outline=pal["outline"], width=2)
        d.rectangle([12, y0 + 78, 40, y0 + 106], fill=pal["hair"], outline=pal["hair_outline"], width=2)
        d.text((50, y0 + 8), "@" + name, font=font, fill=(250, 244, 226))
        d.text((50, y0 + 36), "%s · %s" % (HAIR_NAMES[gn["hair"]], ACC_NAMES[gn["acc"]]), font=small, fill=(232, 236, 220))
        d.text((50, y0 + 60), "%s · %s eyes" % (CHEEK_NAMES[gn["cheeks"]], EYE_NAMES[gn["eyes"]]), font=small, fill=(232, 236, 220))
        d.text((50, y0 + 84), "tier %d %s · 1x / 2x" % (tier, TIER_NAMES[tier]), font=small, fill=(232, 236, 220))
        for zoom, ybase in ((1, y0 + row1 - 8), (2, y0 + row1 + row2 - 4)):
            for i, f in enumerate(FRAMES):
                sp = Image.fromarray(frame(name, tier, f, 1, zoom))
                ax, ay = anchor(tier, zoom)
                img.paste(sp, (label_w + i * c2 + c2 // 2 - ax, ybase - ay), sp)
            xt = label_w + len(FRAMES) * c2 + 10
            for t in range(4):
                sp = Image.fromarray(frame(name, t, "idle0", 1, zoom))
                ax, ay = anchor(t, zoom)
                img.paste(sp, (xt + t * 130 + 65 - ax, ybase - ay), sp)
    return img


if __name__ == "__main__":
    import sys
    import time
    names = sys.argv[1:] or ["kai_dnb", "sami.exe", "noor.wav", "luca_99", "mira_9", "zed_ttv", "xX_tobi_Xx", "atleastonce",
                             "lowkeyjord", "tinytash", "pixel_dude", "gg_nora"]
    t0 = time.perf_counter()
    for n in names:
        settler_sheet(n, 2, 1)
    dt = time.perf_counter() - t0
    print("rendered %d sheets (%d frames) at 1x in %.2fs = %.1f ms/frame" % (len(names), len(names) * len(FRAMES), dt, dt * 1000 / (len(names) * len(FRAMES))))
    for n in names:
        print("%-14s %s" % (n, describe(n)))
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    sheet_image(names).save(os.path.join(here, "settler_sheet.png"))
    print("sheet written")
