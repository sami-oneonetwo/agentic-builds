"""creatures.py - studio-c creature sprite generator (SETTLEMENT top-down, motion + readability first).

Every creature is a real chatter. Identity is procedural and deterministic from the username:

    hue      31-multiplier hash of the lower-cased name -> a hue on a 290 degree wheel that SKIPS the grass
             band (70-160 deg) so no creature ever vanishes into the meadow, even as a 2 px dot at 320x180
    genome   sha1(name) -> body profile (pebble / kite / bell / pear), crest (sprout / horns / fan / curl / tuft),
             tail (tuft / ribbon / fan), face patch (goggle / bib / blaze / face), eyes (round / tall / wide / big)

Silhouette language ("lanterns"): a tapered, bottom-heavy body seen from the front in 3/4 top-down, two big
ink button-eyes with one highlight on a cream face patch, a crest on the crown and a tail peeking out one side,
two stub feet, and a 1-2 px dark outline around EVERY part so the shape survives a 3 Mbps encode.
Two colours per creature (main + accent) plus cream and ink. No arms, no yellow default, no round blob.

Frames (10): idle0 idle1 walk0 walk1 hop blink speak sleep emote0(joy) emote1(love)
Tiers (body height S px): 0 seedling 26 · 1 hatchling 32 · 2 settler 40 · 3 elder 48 (crest grows; elder gets a band)

    import creatures
    sh = creatures.sheet("sami.exe")                     # {"tiers": {t: {"size","anchor","frames": {name: (H,W,4) uint8}}}}
    arr = creatures.frame("sami.exe", 2, "hop", facing=-1)
    creatures.sheet_image(["kai_dnb", ...]).save("creature_sheet.png")

numpy + pillow only. Shapes are drawn at 4x and downsampled premultiplied, so edges are smooth and fringe-free.
"""
from __future__ import annotations

import colorsys
import hashlib
import math
from typing import Dict, List, Sequence, Tuple

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

FRAMES = ("idle0", "idle1", "walk0", "walk1", "hop", "blink", "speak", "sleep", "emote0", "emote1")
TIERS: Dict[int, int] = {0: 26, 1: 32, 2: 40, 3: 48}
TIER_NAMES = ("seedling", "hatchling", "settler", "elder")
BODY_NAMES = ("pebble", "kite", "bell", "pear")
CREST_NAMES = ("sprout", "horns", "fan", "curl", "tuft")
TAIL_NAMES = ("tuft", "ribbon", "fan")
MASK_NAMES = ("goggle", "bib", "blaze", "face")
EYE_NAMES = ("round", "tall", "wide", "big")

SS = 4
CREAM = (250, 240, 220)
INK = (36, 28, 26)
WHITE = (255, 252, 246)
BLUSH = (240, 122, 128)
HEART = (236, 84, 104)
SHADOW = (24, 18, 12)

_CACHE: Dict[Tuple, np.ndarray] = {}


# ----------------------------------------------------------------------------- identity
def name_hash(name: str) -> int:
    s = 0
    for ch in (name or "").lower():
        s = (s * 31 + ord(ch)) & 0xFFFFFFFF
    return s


def genome(name: str) -> Dict[str, int]:
    h = hashlib.sha1((name or "").lower().encode("utf-8")).digest()
    return {"body": h[0] % 4, "crest": h[1] % 5, "tail": h[2] % 3, "mask": h[3] % 4, "eyes": h[4] % 4,
            "side": 1 if h[5] % 2 else -1, "accent_shift": h[6] % 3}


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


def palette(name: str) -> Dict[str, Tuple[int, int, int]]:
    g = genome(name)
    h = hue(name)
    main = _hsv(h, 0.66, 0.90)
    ah = (h + 150 + 40 * g["accent_shift"]) % 360
    if 70 <= ah <= 160:
        ah = (ah + 90) % 360
    accent = _hsv(ah, 0.62, 0.92)
    outline = _mix(_hsv(h, 0.60, 0.30), INK, 0.45)
    feet = _hsv(h, 0.62, 0.62)
    return {"main": main, "accent": accent, "outline": outline, "feet": feet, "hue": h}


def colour_hex(name: str) -> str:
    return "#%02X%02X%02X" % palette(name)["main"]


# ----------------------------------------------------------------------------- body profiles
def _lobe(t: float, c: float, r: float, a: float) -> float:
    u = (t - c) / r
    return a * math.sqrt(max(0.0, 1.0 - u * u))


def _profile(body: int, t: float) -> float:
    """Half-width (in body heights) of profile `body` at height fraction t (0 ground, 1 crown)."""
    if body == 0:      # pebble: an upside-down egg, round and low, tapering crown
        c, a = 0.40, 0.43
        if t < c:
            return a * (max(0.0, 1 - ((c - t) / c) ** 2.0)) ** 0.5
        return a * (max(0.0, 1 - ((t - c) / (1 - c)) ** 2.0)) ** 0.62
    if body == 1:      # kite: straight diagonal sides, a shoulder at 45%, pointed crown
        c, a = 0.45, 0.42
        if t < c:
            return a * (max(0.0, 1 - ((c - t) / (c * 1.35)) ** 1.3)) ** (1 / 1.3)
        return a * (max(0.0, 1 - ((t - c) / (1 - c)) ** 1.25)) ** (1 / 1.25)
    if body == 2:      # bell: wide flat skirt, straight-ish sides, domed crown
        c, a = 0.28, 0.47
        if t < c:
            return a * (max(0.0, 1 - ((c - t) / c) ** 8.0)) ** 0.5
        return a * (max(0.0, 1 - ((t - c) / (1 - c)) ** 2.4)) ** 0.5
    # pear: a wide body lobe, a neck, and a smaller head lobe
    return max(_lobe(t, 0.28, 0.36, 0.42), _lobe(t, 0.74, 0.28, 0.31))


_EYE_POS = {0: (0.16, 0.62), 1: (0.15, 0.58), 2: (0.17, 0.60), 3: (0.13, 0.74)}
_EYE_SIZE = {0: (0.095, 0.095), 1: (0.08, 0.115), 2: (0.115, 0.085), 3: (0.115, 0.115)}

_ANIM = {
    "idle0": dict(sx=1.00, sy=1.00, dy=0.00, rot=0, eyes="open", mouth="smile", crest="normal", feet="both", shadow=1.00),
    "idle1": dict(sx=1.06, sy=0.94, dy=0.00, rot=0, eyes="open", mouth="smile", crest="normal", feet="both", shadow=1.02),
    "walk0": dict(sx=1.00, sy=1.00, dy=0.03, rot=-5, eyes="open", mouth="smile", crest="normal", feet="L", shadow=1.00),
    "walk1": dict(sx=1.00, sy=1.00, dy=0.03, rot=5, eyes="open", mouth="smile", crest="normal", feet="R", shadow=1.00),
    "hop": dict(sx=0.90, sy=1.12, dy=0.30, rot=0, eyes="big", mouth="o", crest="up", feet="tuck", shadow=0.70),
    "blink": dict(sx=1.00, sy=1.00, dy=0.00, rot=0, eyes="blink", mouth="smile", crest="normal", feet="both", shadow=1.00),
    "speak": dict(sx=1.02, sy=1.00, dy=0.02, rot=0, eyes="open", mouth="o", crest="normal", feet="both", shadow=1.00),
    "sleep": dict(sx=1.08, sy=0.90, dy=0.00, rot=0, eyes="sleep", mouth="flat", crest="droop", feet="none", shadow=1.05),
    "emote0": dict(sx=0.98, sy=1.06, dy=0.06, rot=0, eyes="joy", mouth="grin", crest="up", feet="both", shadow=0.95, extra="sparkle"),
    "emote1": dict(sx=1.02, sy=1.00, dy=0.02, rot=0, eyes="big", mouth="w", crest="normal", feet="both", shadow=1.00, extra="heart"),
}


# ----------------------------------------------------------------------------- drawing helpers
class _Canvas:
    def __init__(self, S: int):
        self.S = S
        self.W = int(round(1.5 * S))
        self.H = int(round(1.8 * S))
        self.ow = max(1, int(round(S / 22.0)))          # outline width in output px
        self.cx = self.W * SS / 2.0
        self.gy = (self.H - 0.18 * S) * SS              # ground line (SS px)
        self.layer = Image.new("RGBA", (self.W * SS, self.H * SS), (0, 0, 0, 0))
        self.shadow = Image.new("RGBA", (self.W * SS, self.H * SS), (0, 0, 0, 0))
        self.sx = self.sy = 1.0
        self.dy = 0.0

    def P(self, x: float, y: float) -> Tuple[float, float]:
        """Body units (x right, y up from the ground, in body heights) -> SS pixel coords."""
        return (self.cx + x * self.S * self.sx * SS, self.gy - (y * self.sy + self.dy) * self.S * SS)

    def mask(self) -> Image.Image:
        return Image.new("L", self.layer.size, 0)

    def paint(self, m: Image.Image, fill, outline=None, ow: float = None, alpha: int = 255):
        ow = self.ow if ow is None else ow
        if outline is not None and ow > 0:
            dil = _morph(m, int(2 * round(ow * SS) + 1), ImageFilter.MaxFilter)
            self.layer.paste(outline + (255,), (0, 0), dil)
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
            for k in range(36):
                a = 2 * math.pi * k / 36
                ex, ey = rx * math.cos(a), ry * math.sin(a)
                rr = math.radians(rot)
                px = cx + ex * math.cos(rr) - ey * math.sin(rr)
                py = cy + ex * math.sin(rr) + ey * math.cos(rr)
                pts.append(self.P(px, py))
            d.polygon(pts, fill=255)
        return m

    def poly(self, m, pts):
        ImageDraw.Draw(m).polygon([self.P(*p) for p in pts], fill=255)
        return m

    def stroke(self, m, pts, width):
        d = ImageDraw.Draw(m)
        w = max(1, int(round(width * self.S * SS)))
        p = [self.P(*q) for q in pts]
        d.line(p, fill=255, width=w, joint="curve")
        r = w / 2.0
        for (x, y) in (p[0], p[-1]):
            d.ellipse([x - r, y - r, x + r, y + r], fill=255)
        return m

    def arc(self, m, cx, cy, rx, ry, a0, a1, width):
        """Arc in body units; angles in degrees, PIL convention (0 = 3 o'clock, clockwise on screen)."""
        d = ImageDraw.Draw(m)
        x0, y0 = self.P(cx - rx, cy + ry)
        x1, y1 = self.P(cx + rx, cy - ry)
        w = max(1, int(round(width * self.S * SS)))
        d.arc([x0, y0, x1, y1], a0, a1, fill=255, width=w)
        return m


def _morph(m: Image.Image, size: int, flt) -> Image.Image:
    """Max/Min filter applied only around the mask's bounding box (10-20x faster than the full canvas)."""
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


def _body_points(body: int, n: int = 44) -> List[Tuple[float, float]]:
    left, right = [], []
    for i in range(n + 1):
        t = i / n
        hw = _profile(body, t)
        left.append((-hw, t))
        right.append((hw, t))
    return left + right[::-1]


def _crest(c: _Canvas, kind: int, tier: int, state: str, colour, outline, side: int):
    k = {0: 0.0, 1: 0.72, 2: 1.0, 3: 1.22}[tier]
    ax, ay = 0.0, 1.0
    m = c.mask()
    if tier == 0:
        c.ellipse(m, ax, ay + 0.04, 0.055, 0.055)
        c.paint(m, colour, outline)
        return
    lean = {"normal": 0.0, "up": 0.0, "droop": 0.55}[state]
    scale = 1.15 if state == "up" else 1.0
    k *= scale

    def R(x, y):  # lean the crest sideways when drooping (sleep)
        if lean == 0.0:
            return (ax + x * k, ay + y * k)
        return (ax + (x * math.cos(lean) + y * math.sin(lean) * side) * k, ay + (y * math.cos(lean) - abs(x) * math.sin(lean) * 0.3) * k)

    if kind == 0:      # sprout: stalk + one leaf
        c.stroke(m, [R(0, -0.02), R(0.03 * side, 0.15)], 0.045 * k)
        c.ellipse(m, *R(0.11 * side, 0.20), 0.105 * k, 0.055 * k, rot=-32 * side)
    elif kind == 1:    # horns: two nubs
        c.ellipse(m, *R(-0.13, 0.08), 0.05 * k, 0.105 * k, rot=22)
        c.ellipse(m, *R(0.13, 0.08), 0.05 * k, 0.105 * k, rot=-22)
    elif kind == 2:    # fan: three spikes
        for j in (-1, 0, 1):
            c.ellipse(m, *R(0.12 * j, 0.13 - 0.02 * abs(j)), 0.045 * k, 0.125 * k, rot=-28 * j)
    elif kind == 3:    # curl: an antenna that curls to one side
        pts = [R(0, -0.02), R(0.02 * side, 0.10), R(0.08 * side, 0.19), R(0.17 * side, 0.20), R(0.21 * side, 0.13)]
        c.stroke(m, pts, 0.045 * k)
        c.ellipse(m, *R(0.21 * side, 0.12), 0.045 * k, 0.045 * k)
    else:              # tuft: three hair strokes
        c.stroke(m, [R(0, -0.02), R(-0.11, 0.14)], 0.05 * k)
        c.stroke(m, [R(0, -0.02), R(0.0, 0.19)], 0.05 * k)
        c.stroke(m, [R(0, -0.02), R(0.11, 0.13)], 0.05 * k)
    c.paint(m, colour, outline)


def _tail(c: _Canvas, kind: int, colour, outline, side: int, tier: int):
    k = {0: 0.7, 1: 0.85, 2: 1.0, 3: 1.1}[tier]
    bx, by = 0.30 * side, 0.20
    m = c.mask()
    if kind == 0:      # tuft
        c.poly(m, [(bx, by + 0.10 * k), (bx + 0.26 * k * side, by + 0.16 * k), (bx + 0.22 * k * side, by - 0.06 * k)])
        c.ellipse(m, bx + 0.23 * k * side, by + 0.05 * k, 0.07 * k, 0.10 * k)
    elif kind == 1:    # ribbon
        pts = [(bx, by), (bx + 0.14 * k * side, by + 0.10 * k), (bx + 0.28 * k * side, by - 0.02 * k), (bx + 0.40 * k * side, by + 0.08 * k)]
        c.stroke(m, pts, 0.07 * k)
    else:              # fan of three leaves
        for j, ang in enumerate((-22, 8, 38)):
            c.ellipse(m, bx + 0.22 * k * side, by + 0.02 * k + 0.06 * k * (j - 1), 0.14 * k, 0.055 * k, rot=ang * side)
    c.paint(m, colour, outline)


def _feet(c: _Canvas, state: str, colour, outline):
    if state == "none":
        return
    m = c.mask()
    if state == "tuck":
        c.ellipse(m, -0.09, -0.01, 0.09, 0.055)
        c.ellipse(m, 0.09, -0.01, 0.09, 0.055)
    else:
        ly = 0.05 if state == "L" else (-0.03 if state == "R" else 0.0)
        ry = 0.05 if state == "R" else (-0.03 if state == "L" else 0.0)
        c.ellipse(m, -0.18, ly, 0.10, 0.06)
        c.ellipse(m, 0.18, ry, 0.10, 0.06)
    c.paint(m, colour, outline)


def _eyes(c: _Canvas, body: int, eyes: int, state: str):
    ex, ey = _EYE_POS[body]
    rx, ry = _EYE_SIZE[eyes]
    if state == "big":
        rx, ry = rx * 1.12, ry * 1.12
    m = c.mask()
    if state in ("open", "big"):
        for sgn in (-1, 1):
            c.ellipse(m, sgn * ex, ey, rx, ry)
        c.paint(m, INK)
        hm = c.mask()
        hr = 0.038 if state == "open" else 0.048
        for sgn in (-1, 1):
            c.ellipse(hm, sgn * ex - 0.30 * rx, ey + 0.32 * ry, hr, hr)
        c.paint(hm, WHITE)
    elif state == "blink":
        for sgn in (-1, 1):
            c.stroke(m, [(sgn * ex - rx, ey), (sgn * ex + rx, ey)], 0.035)
        c.paint(m, INK)
    elif state == "sleep":   # content closed eyes, a shallow "u"
        for sgn in (-1, 1):
            c.arc(m, sgn * ex, ey + 0.06, rx, ry * 0.8, 20, 160, 0.035)
        c.paint(m, INK)
    elif state == "joy":     # happy squint, a "n"
        for sgn in (-1, 1):
            c.arc(m, sgn * ex, ey - 0.06, rx, ry * 0.9, 200, 340, 0.04)
        c.paint(m, INK)


def _mouth(c: _Canvas, body: int, state: str):
    my = _EYE_POS[body][1] - 0.15
    m = c.mask()
    if state == "smile":
        c.arc(m, 0.0, my + 0.05, 0.07, 0.06, 20, 160, 0.028)
    elif state == "o":
        c.ellipse(m, 0.0, my, 0.055, 0.045)
    elif state == "grin":
        d = ImageDraw.Draw(m)
        x0, y0 = c.P(-0.10, my + 0.02)
        x1, y1 = c.P(0.10, my - 0.10)
        d.chord([x0, y0 - (y1 - y0), x1, y1], 0, 180, fill=255)
    elif state == "w":
        c.arc(m, -0.045, my + 0.04, 0.045, 0.045, 20, 160, 0.026)
        c.arc(m, 0.045, my + 0.04, 0.045, 0.045, 20, 160, 0.026)
    elif state == "flat":
        c.stroke(m, [(-0.04, my), (0.04, my)], 0.026)
    c.paint(m, INK)


def _blush(c: _Canvas, body: int):
    ex, ey = _EYE_POS[body]
    m = c.mask()
    for sgn in (-1, 1):
        c.ellipse(m, sgn * (ex + 0.10), ey - 0.12, 0.05, 0.04)
    c.paint(m, BLUSH, alpha=135)


def _patch(c: _Canvas, body_mask: Image.Image, kind: int):
    m = c.mask()
    if kind == 0:
        c.ellipse(m, 0.0, 0.62, 0.42, 0.17)
    elif kind == 1:
        c.ellipse(m, 0.0, 0.24, 0.30, 0.20)
    elif kind == 2:
        c.poly(m, [(-0.07, 0.44), (0.07, 0.44), (0.07, 1.06), (-0.07, 1.06)])
        c.ellipse(m, 0.0, 0.44, 0.07, 0.07)
    else:
        c.ellipse(m, 0.0, 0.56, 0.32, 0.30)
    inner = _morph(body_mask, int(2 * round(c.ow * SS) + 1), ImageFilter.MinFilter)
    c.paint(ImageChops.multiply(m, inner), CREAM)


def _band(c: _Canvas, body_mask: Image.Image, colour):
    m = c.mask()
    c.poly(m, [(-0.6, 0.30), (0.6, 0.30), (0.6, 0.37), (-0.6, 0.37)])
    inner = _morph(body_mask, int(2 * round(c.ow * SS) + 1), ImageFilter.MinFilter)
    c.paint(ImageChops.multiply(m, inner), colour)


def _extras(c: _Canvas, kind: str, accent, outline):
    if kind == "sparkle":
        m = c.mask()
        for (x, y, r) in ((-0.42, 1.02, 0.075), (0.44, 0.90, 0.06)):
            pts = []
            for k in range(8):
                a = math.pi / 4 * k
                rr = r if k % 2 == 0 else r * 0.38
                pts.append((x + rr * math.cos(a), y + rr * math.sin(a)))
            c.poly(m, pts)
        c.paint(m, (255, 226, 120), outline, ow=c.ow * 0.6)
    elif kind == "heart":
        m = c.mask()
        x, y, r = 0.40, 1.10, 0.075
        c.ellipse(m, x - r * 0.55, y + r * 0.35, r * 0.6, r * 0.6)
        c.ellipse(m, x + r * 0.55, y + r * 0.35, r * 0.6, r * 0.6)
        c.poly(m, [(x - r * 1.12, y + r * 0.25), (x + r * 1.12, y + r * 0.25), (x, y - r * 0.95)])
        c.paint(m, HEART, outline, ow=c.ow * 0.6)


def _downsample_premult(img: Image.Image, W: int, H: int) -> np.ndarray:
    a = np.asarray(img, dtype=np.float32)
    al = a[..., 3:4] / 255.0
    pm = a[..., :3] * al
    chans = []
    for k in range(3):
        chans.append(np.asarray(Image.fromarray(np.ascontiguousarray(pm[..., k])).resize((W, H), Image.Resampling.LANCZOS)))
    alpha = np.asarray(Image.fromarray(np.ascontiguousarray(a[..., 3])).resize((W, H), Image.Resampling.LANCZOS))
    alpha = np.clip(alpha, 0, 255)
    rgb = np.stack(chans, -1)
    out = np.zeros((H, W, 4), np.uint8)
    nz = alpha > 0.5
    rgb[nz] = rgb[nz] / (alpha[nz][..., None] / 255.0)
    out[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    out[..., 3] = alpha.astype(np.uint8)
    return out


# ----------------------------------------------------------------------------- frame render
def _render(name: str, tier: int, frame_name: str) -> np.ndarray:
    g = genome(name)
    pal = palette(name)
    an = _ANIM[frame_name]
    S = TIERS[tier]
    c = _Canvas(S)
    c.sx, c.sy, c.dy = an["sx"], an["sy"], an["dy"]

    # ground shadow (never rotated)
    sm = Image.new("L", c.shadow.size, 0)
    d = ImageDraw.Draw(sm)
    k = an["shadow"]
    rx, ry = 0.40 * S * SS * k, 0.12 * S * SS * k
    d.ellipse([c.cx - rx, c.gy - ry, c.cx + rx, c.gy + ry], fill=255)
    sm = sm.filter(ImageFilter.GaussianBlur(1.2 * SS))
    c.shadow.paste(SHADOW + (255,), (0, 0), sm.point(lambda v: v * (70 if frame_name == "hop" else 95) // 255))

    side = g["side"]
    _tail(c, g["tail"], pal["accent"], pal["outline"], side, tier)
    _feet(c, an["feet"], pal["feet"], pal["outline"])
    bm = c.poly(c.mask(), _body_points(g["body"]))
    c.paint(bm, pal["main"], pal["outline"])
    _patch(c, bm, g["mask"])
    if tier == 3:
        _band(c, bm, pal["accent"])
    _crest(c, g["crest"], tier, an["crest"], pal["accent"], pal["outline"], side)
    _eyes(c, g["body"], g["eyes"], an["eyes"])
    _blush(c, g["body"])
    _mouth(c, g["body"], an["mouth"])
    if an.get("extra"):
        _extras(c, an["extra"], pal["accent"], pal["outline"])

    layer = c.layer
    if an["rot"]:
        layer = layer.rotate(an["rot"], resample=Image.Resampling.BICUBIC, center=(c.cx, c.gy))
    out = Image.alpha_composite(c.shadow, layer)
    return _downsample_premult(out, c.W, c.H)


def frame(name: str, tier: int, frame_name: str, facing: int = 1) -> np.ndarray:
    key = ((name or "").lower(), int(tier), frame_name)
    arr = _CACHE.get(key)
    if arr is None:
        arr = _render(name, tier, frame_name)
        _CACHE[key] = arr
    return arr if facing >= 0 else arr[:, ::-1].copy()


def anchor(tier: int) -> Tuple[int, int]:
    """(x, y) of the ground point inside a frame of this tier (feet touch here)."""
    S = TIERS[tier]
    return int(round(1.5 * S)) // 2, int(round((int(round(1.8 * S)) - 0.18 * S)))


def sheet(name: str, tiers: Sequence[int] = (0, 1, 2, 3), frames: Sequence[str] = FRAMES) -> Dict:
    out = {"name": name, "genome": genome(name), "palette": palette(name), "tiers": {}}
    for t in tiers:
        S = TIERS[t]
        out["tiers"][t] = {"size": (int(round(1.5 * S)), int(round(1.8 * S))), "anchor": anchor(t),
                           "frames": {f: frame(name, t, f) for f in frames}}
    return out


def describe(name: str) -> str:
    g = genome(name)
    return "%s body · %s crest · %s tail · %s patch · %s eyes · hue %d" % (
        BODY_NAMES[g["body"]], CREST_NAMES[g["crest"]], TAIL_NAMES[g["tail"]], MASK_NAMES[g["mask"]],
        EYE_NAMES[g["eyes"]], int(hue(name)))


# ----------------------------------------------------------------------------- contact sheet
def sheet_image(names: Sequence[str], tier: int = 2, bg=(96, 150, 78)) -> Image.Image:
    from PIL import ImageFont
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Verdana Bold.ttf", 20)
    small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Verdana.ttf", 20)
    cell_w, cell_h = 78, 92
    label_w = 300
    tier_w = 4 * 80
    W = label_w + len(FRAMES) * cell_w + tier_w + 20
    H = 44 + len(names) * (cell_h + 6)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    for i, f in enumerate(FRAMES):
        d.text((label_w + i * cell_w + 6, 12), f, font=small, fill=(20, 30, 16))
    d.text((label_w + len(FRAMES) * cell_w + 8, 12), "tiers 0-3 (idle0)", font=small, fill=(20, 30, 16))
    for r, name in enumerate(names):
        y0 = 44 + r * (cell_h + 6)
        if r % 2 == 0:
            d.rectangle([0, y0, W, y0 + cell_h], fill=tuple(int(v * 0.94) for v in bg))
        pal = palette(name)
        d.rectangle([12, y0 + 10, 40, y0 + 38], fill=pal["main"], outline=pal["outline"], width=2)
        d.rectangle([12, y0 + 44, 40, y0 + 72], fill=pal["accent"], outline=pal["outline"], width=2)
        d.text((50, y0 + 8), "@" + name, font=font, fill=(250, 244, 226))
        g = genome(name)
        d.text((50, y0 + 36), "%s/%s" % (BODY_NAMES[g["body"]], CREST_NAMES[g["crest"]]), font=small, fill=(232, 236, 220))
        d.text((50, y0 + 60), "%s/%s" % (TAIL_NAMES[g["tail"]], MASK_NAMES[g["mask"]]), font=small, fill=(232, 236, 220))
        for i, f in enumerate(FRAMES):
            arr = frame(name, tier, f)
            sp = Image.fromarray(arr)
            ax, ay = anchor(tier)
            px = label_w + i * cell_w + cell_w // 2 - ax
            py = y0 + cell_h - 10 - ay
            img.paste(sp, (px, py), sp)
        for t in range(4):
            arr = frame(name, t, "idle0")
            sp = Image.fromarray(arr)
            ax, ay = anchor(t)
            px = label_w + len(FRAMES) * cell_w + 10 + t * 80 + 40 - ax
            py = y0 + cell_h - 10 - ay
            img.paste(sp, (px, py), sp)
    return img


if __name__ == "__main__":
    import sys
    import time
    names = sys.argv[1:] or ["kai_dnb", "sami.exe", "noor.wav", "luca_99", "mira_9", "zed_ttv", "xX_tobi_Xx", "atleastonce"]
    t0 = time.perf_counter()
    for n in names:
        sheet(n)
    dt = time.perf_counter() - t0
    print("rendered %d sheets (%d frames) in %.2fs = %.1f ms/frame" % (len(names), len(names) * 40, dt, dt * 1000 / (len(names) * 40)))
    for n in names:
        print("%-14s %s" % (n, describe(n)))
    sheet_image(names).save("/Users/sandy/Workspace/agentic-builds/kick-live/docs/art/studio-c/creature_sheet.png")
