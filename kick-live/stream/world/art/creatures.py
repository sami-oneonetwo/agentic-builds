"""creatures.py - SETTLERS: the people-shaped sprites of the SETTLEMENT world (canonical art module).

Every settler is a real chatter. Identity is procedural and deterministic from the username; nothing is hand-picked:

    hue        31-multiplier hash of the lower-cased name -> a hue on a 270 degree wheel that SKIPS the grass band
               (70-160) so a settler is always a lit colour against the meadow, even as a dot at 320x180.
               The hue is the TUNIC and stays the dominant colour, so labels, roofs, banners and fields match.
    genome     sha1(name) -> hair style, hair yarn, hat (worn from the builder tier), accessory / kit, cheeks, eye set,
               the side things hang on, the elder hat, the accent offset. See ART.md for the table.

Silhouette language ("small people"): a big ROUND head on a short neck (2.5 heads tall at the settler tier), a tunic
with a belt, two arms that really gesture (mitten hands), two legs with round shoes and a real contact/pass walk.
One warm toy-cream face for everyone (tinted 10 % toward the tunic): stylised, friendly, gender-neutral, never a
skin tone or an ethnicity. Bold 1-px sticker outlines on every part (drawn at 4x, downsampled premultiplied), a
warm rim on the sun side and a cool shade on the far side from the sun vector the compositor passes in.

Frames (23):
    idle0 idle1 blink look_l look_r         breath, blink, gaze toward a speaker on either side (no flip needed)
    walk0 walk1 walk2 walk3                 contact L (knee + boot tilt on the lifted leg, arms swing opposite),
                                            pass (bob up), contact R, pass
    hop0 hop1                               anticipation squash (knees bent, arms back), airborne stretch (tucked)
    wave0 wave1 point                       long-arm gestures
    sit sleep                               hands on knees; curled under an accent blanket with a Z
    carry_berry carry_stone carry_tool      two-handed carry
    speak0 speak1                           mouth notch + head bob + a gesture hand
    joy love                                arms up + sparkles; heart + big highlights
Tiers: 0 sprout 26 px / 2.1 heads · 1 settler 30 px / 2.5 · 2 builder 34 px / 2.5 (+ hat, kit) · 3 elder 42 px / 3.0
       (+1 head of stature, elder hat, accent cape).

    from stream.world.art import creatures
    arr = creatures.render("sami", tier=2, frame="walk1", zoom=1, facing=-1, sun=(-0.6, -0.8))  # (H, W, 4) uint8
    sh = creatures.shadow(2, "hop1", zoom=1, sun=(-0.6, -0.8))                                 # ground shadow only
    g = creatures.genome("sami")          # colour, hair, hat, cloak, accessory, ... (strings + hex)
    sheet = creatures.settler_sheet("sami", 2, 1, sun)                                           # {frame: PIL RGBA}
    ax, ay = creatures.anchor(2)          # ground point inside every frame of the tier

Cached per (name, tier, frame, zoom, sun octant). numpy + pillow only, Python 3.9.
"""
from __future__ import annotations

import colorsys
import hashlib
import math
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

FRAMES = ("idle0", "idle1", "blink", "look_l", "look_r", "walk0", "walk1", "walk2", "walk3", "hop0", "hop1",
          "wave0", "wave1", "point", "sit", "sleep", "carry_berry", "carry_stone", "carry_tool", "speak0", "speak1",
          "joy", "love")
TIERS: Dict[int, Dict] = {
    0: {"name": "sprout", "h": 26, "heads": 2.1},
    1: {"name": "settler", "h": 30, "heads": 2.5},
    2: {"name": "builder", "h": 34, "heads": 2.5},
    3: {"name": "elder", "h": 42, "heads": 3.0},
}
TIER_NAMES = tuple(TIERS[t]["name"] for t in range(4))
HAIR_NAMES = ("bob", "tuft", "crop", "bun", "flower", "curlcap")
HAT_NAMES = ("none", "beanie", "hood")                    # worn from the builder tier
ELDER_HAT_NAMES = ("brim", "stocking")                    # elders always wear one (over the hair, replacing the hat)
ACC_NAMES = ("scarf", "belt", "satchel", "badge", "apron", "staff", "lantern", "tool")   # builder tier and up
CHEEK_NAMES = ("blush", "freckles", "plain")
EYE_NAMES = ("dots", "tall", "wide")
YARN_NAMES = ("cocoa", "rust", "straw", "cream", "plum", "accent")

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
LANTERN = (252, 210, 96)
YARN = ((74, 52, 46), (170, 98, 60), (236, 198, 100), (246, 238, 222), (96, 64, 92), None)   # None = accent colour
DEFAULT_SUN = (-0.62, -0.78)       # screen-space unit vector toward the sun (x right, y down): evening, top-left

_CACHE: Dict[Tuple, np.ndarray] = {}
_SHADOWS: Dict[Tuple, np.ndarray] = {}
_SHEETS: Dict[Tuple, Dict[str, Image.Image]] = {}
_ICONS: Dict[Tuple, Image.Image] = {}


# ----------------------------------------------------------------------------- identity
def name_hash(name: str) -> int:
    s = 0
    for ch in (name or "").lower():
        s = (s * 31 + ord(ch)) & 0xFFFFFFFF
    return s


def _genes(name: str) -> Dict[str, int]:
    h = hashlib.sha1((name or "").lower().encode("utf-8")).digest()
    return {"hair": (h[0] + h[9]) % len(HAIR_NAMES), "yarn": h[1] % 6, "acc": h[2] % len(ACC_NAMES),
            "cheeks": h[3] % 3, "eyes": h[4] % 3, "side": 1 if h[5] % 2 else -1, "accent_shift": h[6] % 3,
            "elder_hat": h[7] % 2, "hat": (0, 0, 0, 1, 1, 2, 0, 1)[h[8] % 8]}


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


def _hex(c) -> str:
    return "#%02X%02X%02X" % tuple(c[:3])


def palette(name: str) -> Dict:
    g = _genes(name)
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
            "belt": _mix(main, outline, 0.45),
            "legs": _mix(_hsv(h, 0.45, 0.42), (90, 70, 60), 0.5),
            "shoes": _mix(outline, (70, 48, 40), 0.5),
            "face": _mix(CREAM, main, 0.06),
            "hair": yarn, "hair_outline": _mix(yarn, INK, 0.55),
            "cape": _mix(accent, outline, 0.35)}


def colour_hex(name: str) -> str:
    return _hex(palette(name)["main"])


def genome(name: str) -> Dict:
    """The settler's deterministic identity as readable values (the compositor and HUD read these; render() reads the
    same genes). colour = the tunic / label colour; cloak = the elder cape colour; hat is worn from the builder tier."""
    g = _genes(name)
    pal = palette(name)
    return {"name": (name or "").lower(), "hue": round(pal["hue"], 1), "colour": _hex(pal["main"]),
            "accent": _hex(pal["accent"]), "outline": _hex(pal["outline"]),
            "hair": HAIR_NAMES[g["hair"]], "hair_colour": _hex(pal["hair"]), "yarn": YARN_NAMES[g["yarn"]],
            "hat": HAT_NAMES[g["hat"]], "elder_hat": ELDER_HAT_NAMES[g["elder_hat"]], "cloak": _hex(pal["cape"]),
            "accessory": ACC_NAMES[g["acc"]], "cheeks": CHEEK_NAMES[g["cheeks"]], "eyes": EYE_NAMES[g["eyes"]],
            "side": g["side"]}


def describe(name: str) -> str:
    G = genome(name)
    return "%s · %s hair · %s · %s · %s cheeks · %s eyes · hue %d" % (
        G["colour"], G["hair"], G["hat"], G["accessory"], G["cheeks"], G["eyes"], int(G["hue"]))


# ----------------------------------------------------------------------------- drawing helpers
class _Canvas:
    def __init__(self, S: float, ss: int = SS):
        self.S = S
        self.ss = ss
        self.W = int(round(1.6 * S))
        self.H = int(round(1.72 * S))
        self.ow = max(1.0, S / 26.0)                   # outline width in output px (1.0 at 26, 1.3 at 34, 2.6 at 2x)
        self.cx = self.W * ss / 2.0
        self.gy = (self.H - 0.14 * S) * ss             # ground line (ss px)
        self.layer = Image.new("RGBA", (self.W * ss, self.H * ss), (0, 0, 0, 0))
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

    def inner(self, m: Image.Image) -> Image.Image:
        """The mask shrunk by one outline width (to keep decoration inside a part's outline)."""
        return _morph(m, int(2 * round(self.ow * self.ss) + 1), ImageFilter.MinFilter)

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

    def below(self, m: Image.Image, y: float) -> Image.Image:
        """Keep only the part of the mask below body height y."""
        cutm = self.mask()
        _, py = self.P(0, y)
        ImageDraw.Draw(cutm).rectangle([0, py, m.width, m.height], fill=255)
        return ImageChops.multiply(m, cutm)

    def above(self, m: Image.Image, y: float) -> Image.Image:
        cutm = self.mask()
        _, py = self.P(0, y)
        ImageDraw.Draw(cutm).rectangle([0, 0, m.width, py], fill=255)
        return ImageChops.multiply(m, cutm)


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
    """Proportions in body heights for one tier. y is up from the ground point, x right."""

    def __init__(self, tier: int):
        t = TIERS[tier]
        self.tier = tier
        self.heads = t["heads"]
        self.R = 0.5 / self.heads                       # head radius (0.238 / 0.20 / 0.20 / 0.167)
        self.hy = 1.0 - self.R                          # head centre
        self.neck = 0.05 if tier else 0.035             # neck height under the chin
        self.top = self.hy - self.R - self.neck + 0.03  # tunic top (shoulder line); tucks 0.03 under the chin outline
        self.hem = {0: 0.24, 1: 0.27, 2: 0.27, 3: 0.29}[tier]
        self.ws = 0.165 if tier else 0.155              # shoulder half width (head R 0.20 > 0.165: head wider)
        self.wh = 0.20 if tier else 0.195               # hem half width
        self.leg_x = 0.082
        self.leg_w = 0.10 if tier else 0.105
        self.arm_w = 0.085 if tier else 0.09
        self.hand_r = 0.055 if tier else 0.058
        self.shoe = (0.078, 0.046)
        self.sh_y = self.top - 0.045                    # shoulder pivot
        self.hip_y = self.hem + 0.03


# ----------------------------------------------------------------------------- poses
def _pose(frame_name: str, g: _Geo, side: int) -> Dict:
    """Concrete geometry for one frame, in body units.
    legs: list of dicts hip / knee (optional) / ankle / shoe (x, y, rot) / sole.  arms: polylines shoulder -> [elbow] -> hand.
    up: whole-body vertical drop (sit).  sx/sy/dy: squash-stretch about the ground point.  rot: lean in degrees."""
    lx, hip_y, ws, wh, sh_y, hem = g.leg_x, g.hip_y, g.ws, g.wh, g.sh_y, g.hem
    A = dict(sx=1.0, sy=1.0, dy=0.0, rot=0, up=0.0, head=(0.0, 0.0), eyes="open", mouth="smile", look=0.0,
             shadow=1.0, extra=None, item=None, lying=False, hands={}, cape_flare=0.0)

    def leg(x0, x1, y1, knee=None, rot=0.0, sole=False):
        return dict(hip=(x0, hip_y), knee=knee, ankle=(x1, y1), shoe=(x1, y1 - 0.012, rot), sole=sole)

    rest_y = hem + 0.10
    down_l = [(-ws * 0.92, sh_y), (-(wh + 0.02), hem + 0.20), (-(wh + 0.04), rest_y)]
    down_r = [(ws * 0.92, sh_y), ((wh + 0.02), hem + 0.20), ((wh + 0.04), rest_y)]
    A["legs"] = [leg(-lx, -lx - 0.005, 0.046), leg(lx, lx + 0.005, 0.046)]
    A["arms"] = [down_l, down_r]

    if frame_name == "idle1":                       # breath: a touch wider and lower, head dips
        A.update(sx=1.03, sy=0.97, head=(0.0, -0.008))
    elif frame_name == "blink":
        A.update(eyes="blink")
    elif frame_name in ("look_l", "look_r"):
        s = -1 if frame_name == "look_l" else 1
        A.update(head=(0.04 * s, 0.0), look=0.03 * s)
    elif frame_name.startswith("walk"):
        k = int(frame_name[4])
        if k in (0, 2):                             # contact: one leg planted forward, the other lifted behind with a knee
            f = -1 if k == 0 else 1                 # side of the planted (forward) leg
            A["rot"] = 4 * f
            planted = leg(f * lx, f * (lx + 0.035), 0.040)
            lifted = leg(-f * lx, -f * (lx + 0.015), 0.165, knee=(-f * (lx + 0.05), hip_y - 0.10), rot=-f * 22)
            lifted["shoe"] = (-f * (lx + 0.035), 0.155, -f * 22)
            A["legs"] = [planted, lifted] if f == -1 else [lifted, planted]
            # arms swing opposite: the arm on the lifted-leg side comes forward (out and up), the other hangs back
            fwd = [(-f * ws * 0.92, sh_y), (-f * (ws + 0.09), sh_y - 0.10), (-f * (ws + 0.13), hem + 0.17)]
            back = [(f * ws * 0.92, sh_y), (f * (ws + 0.04), hem + 0.16), (f * (wh + 0.01), hem - 0.03)]
            A["arms"] = [fwd, back] if f == 1 else [back, fwd]
        else:                                       # passing: legs together-ish, body bobs up
            A.update(dy=0.025, sy=1.01)
            A["legs"] = [leg(-lx, -lx, 0.075), leg(lx, lx, 0.046)] if k == 1 else [leg(-lx, -lx, 0.046), leg(lx, lx, 0.075)]
    elif frame_name == "hop0":                      # anticipation: squash, knees bent out, arms swept back
        A.update(sy=0.86, sx=1.06, mouth="o", shadow=1.05, head=(0.0, -0.01))
        A["legs"] = [leg(-lx, -(lx + 0.03), 0.046, knee=(-(lx + 0.075), hip_y - 0.12)),
                     leg(lx, (lx + 0.03), 0.046, knee=((lx + 0.075), hip_y - 0.12))]
        A["arms"] = [[(-ws * 0.92, sh_y), (-(ws + 0.13), sh_y - 0.13), (-(ws + 0.20), hem + 0.05)],
                     [(ws * 0.92, sh_y), ((ws + 0.13), sh_y - 0.13), ((ws + 0.20), hem + 0.05)]]
    elif frame_name == "hop1":                      # airborne: stretch, legs tucked, arms up, mouth "o", big eyes
        A.update(dy=0.27, sy=1.08, sx=0.95, eyes="big", mouth="o", shadow=0.62, cape_flare=0.06)
        A["legs"] = [leg(-lx, -(lx + 0.02), 0.13, knee=(-(lx + 0.05), hip_y - 0.10), rot=-28),
                     leg(lx, (lx + 0.02), 0.13, knee=((lx + 0.05), hip_y - 0.10), rot=28)]
        A["arms"] = [[(-ws * 0.92, sh_y), (-(ws + 0.14), sh_y + 0.12), (-(g.R + 0.15), g.hy + g.R * 0.45)],
                     [(ws * 0.92, sh_y), ((ws + 0.14), sh_y + 0.12), ((g.R + 0.15), g.hy + g.R * 0.45)]]
    elif frame_name in ("wave0", "wave1"):
        s = side
        wob = 0.0 if frame_name == "wave0" else 0.07
        raised = [(s * ws * 0.92, sh_y), (s * (ws + 0.13), sh_y + 0.12), (s * (g.R + 0.13 + wob), g.hy + g.R + 0.02 - wob * 0.7)]
        A["arms"] = [down_l, raised] if s == 1 else [raised, down_r]
        A["hands"] = {1 if s == 1 else 0: "open"}
        A.update(head=(-0.012 * s, 0.0), mouth="grin" if frame_name == "wave1" else "smile")
    elif frame_name == "point":                     # arm straight out toward +x, other hand on the hip, gaze right
        ext = [(ws * 0.92, sh_y), ((ws + 0.16), sh_y - 0.005), ((ws + 0.31), sh_y + 0.01)]
        hip = [(-ws * 0.92, sh_y), (-(ws + 0.10), hem + 0.15), (-(wh - 0.01), hem + 0.06)]
        A["arms"] = [hip, ext]
        A["hands"] = {1: "point"}
        A.update(head=(0.03, 0.0), look=0.03, mouth="o")
    elif frame_name == "sit":                       # upper body drops by the leg length, legs out toward the camera
        drop = -(hem - 0.09)
        A.update(up=drop, shadow=1.12)
        A["legs"] = [dict(hip=(-lx, hip_y + drop), knee=(-(lx + 0.035), hip_y + drop - 0.05), ankle=(-(lx + 0.065), 0.02),
                          shoe=(-(lx + 0.07), 0.03, 0.0), sole=True),
                     dict(hip=(lx, hip_y + drop), knee=((lx + 0.035), hip_y + drop - 0.05), ankle=((lx + 0.065), 0.02),
                          shoe=((lx + 0.07), 0.03, 0.0), sole=True)]
        A["arms"] = [[(-ws * 0.92, sh_y + drop), (-(ws + 0.07), sh_y + drop - 0.15), (-(lx + 0.05), hip_y + drop - 0.02)],
                     [(ws * 0.92, sh_y + drop), ((ws + 0.07), sh_y + drop - 0.15), ((lx + 0.05), hip_y + drop - 0.02)]]
    elif frame_name == "sleep":
        A.update(lying=True, eyes="sleep", mouth="flat", shadow=1.25, extra="zz")
    elif frame_name.startswith("carry"):
        A["item"] = frame_name.split("_")[1]
        hy_ = hem + 0.19
        A["arms"] = [[(-ws * 0.92, sh_y), (-(ws + 0.07), hem + 0.24), (-0.115, hy_)],
                     [(ws * 0.92, sh_y), ((ws + 0.07), hem + 0.24), (0.115, hy_)]]
        if A["item"] == "stone":
            A.update(sx=1.02, sy=0.98, mouth="flat")
        elif A["item"] == "tool":
            A["arms"] = [[(-ws * 0.92, sh_y), (-(ws + 0.08), hem + 0.22), (-side * 0.10, hem + 0.12)],
                         [(ws * 0.92, sh_y), ((ws + 0.10), sh_y - 0.02), (side * 0.11, sh_y + 0.02)]]
            if side < 0:
                A["arms"] = [[(-ws * 0.92, sh_y), (-(ws + 0.10), sh_y - 0.02), (side * 0.11, sh_y + 0.02)],
                             [(ws * 0.92, sh_y), ((ws + 0.08), hem + 0.22), (-side * 0.10, hem + 0.12)]]
    elif frame_name in ("speak0", "speak1"):
        k = 0 if frame_name == "speak0" else 1
        A.update(mouth="o" if k == 0 else "notch", head=(0.0, 0.02 if k == 0 else -0.006))
        s = side
        gesture = [(s * ws * 0.92, sh_y), (s * (ws + 0.09), sh_y - 0.14), (s * (ws + 0.11 + 0.05 * k), sh_y - 0.10 + 0.07 * k)]
        A["arms"] = [down_l, gesture] if s == 1 else [gesture, down_r]
        A["hands"] = {1 if s == 1 else 0: "open"}
    elif frame_name == "joy":
        A.update(dy=0.04, sy=1.04, sx=0.98, eyes="joy", mouth="grin", extra="sparkle", shadow=0.92)
        A["arms"] = [[(-ws * 0.92, sh_y), (-(ws + 0.13), sh_y + 0.12), (-(g.R + 0.14), g.hy + g.R * 0.5)],
                     [(ws * 0.92, sh_y), ((ws + 0.13), sh_y + 0.12), ((g.R + 0.14), g.hy + g.R * 0.5)]]
        A["hands"] = {0: "open", 1: "open"}
    elif frame_name == "love":
        A.update(sx=1.01, dy=0.01, eyes="big", mouth="w", extra="heart", head=(0.01 * side, 0.0))
        clasp = [[(-ws * 0.92, sh_y), (-(ws + 0.06), hem + 0.22), (-0.04, hem + 0.26)],
                 [(ws * 0.92, sh_y), ((ws + 0.06), hem + 0.22), (0.04, hem + 0.26)]]
        A["arms"] = clasp
    return A


# ----------------------------------------------------------------------------- part painters
def _paint_legs(c: _Canvas, g: _Geo, legs, pal):
    for L in legs:
        m = c.mask()
        pts = [L["hip"]] + ([L["knee"]] if L.get("knee") else []) + [L["ankle"]]
        c.stroke(m, pts, g.leg_w)
        c.paint(m, pal["legs"], pal["outline"])
    for L in legs:
        m = c.mask()
        sx_, sy_, rot = L["shoe"]
        rx, ry = g.shoe
        if L.get("sole"):
            c.ellipse(m, sx_, sy_, rx * 0.9, ry * 1.7)
        else:
            c.ellipse(m, sx_, sy_, rx, ry, rot=rot)
        c.paint(m, pal["shoes"], pal["outline"])


def _torso(c: _Canvas, g: _Geo, pal, up: float, tier: int) -> Image.Image:
    top, hem = g.top + up, g.hem + up
    m = c.mask()
    c.poly(m, [(-g.ws, top), (g.ws, top), (g.wh, hem), (-g.wh, hem)])
    c.ellipse(m, 0.0, hem, g.wh, 0.04)
    c.ellipse(m, 0.0, top, g.ws, 0.05)
    c.paint(m, pal["main"], pal["outline"])
    inner = c.inner(m)
    # hem shade band (fold) and a belt with a small buckle: clothing, not a cone
    band = c.mask()
    c.poly(band, [(-0.4, hem + 0.045), (0.4, hem + 0.045), (0.4, hem - 0.06), (-0.4, hem - 0.06)])
    c.paint(ImageChops.multiply(band, inner), pal["tunic_dark"])
    if tier >= 1:
        by = hem + (top - hem) * 0.34
        belt = c.mask()
        c.poly(belt, [(-0.4, by - 0.02), (0.4, by - 0.02), (0.4, by + 0.02), (-0.4, by + 0.02)])
        c.paint(ImageChops.multiply(belt, inner), pal["belt"])
        c.paint(c.ellipse(c.mask(), 0.0, by, 0.02, 0.02), pal["accent"])
    return m


def _cape(c: _Canvas, g: _Geo, pal, up: float, flare_extra: float):
    top, bottom = g.sh_y + up + 0.02, 0.06
    flare = 0.29 + flare_extra
    m = c.mask()
    c.poly(m, [(-g.ws - 0.02, top), (g.ws + 0.02, top), (flare, bottom), (-flare, bottom)])
    c.ellipse(m, 0.0, bottom, flare, 0.05)
    c.paint(m, pal["cape"], pal["outline"])


def _arm(c: _Canvas, g: _Geo, pts, pal):
    m = c.mask()
    c.stroke(m, pts, g.arm_w)
    c.paint(m, pal["main"], pal["outline"])


def _hand(c: _Canvas, g: _Geo, pos: Tuple[float, float], pal, kind: Optional[str] = None):
    m = c.mask()
    r = g.hand_r
    if kind == "open":
        c.ellipse(m, pos[0], pos[1], r * 1.2, r * 1.2)
    elif kind == "point":
        c.ellipse(m, pos[0] + r * 0.5, pos[1], r * 1.45, r * 0.9)
    else:
        c.ellipse(m, pos[0], pos[1], r, r)
    c.paint(m, pal["face"], pal["outline"])


def _neck(c: _Canvas, g: _Geo, hx: float, hy: float, pal):
    m = c.mask()
    c.stroke(m, [(hx, hy - g.R * 0.5), (hx, hy - g.R - g.neck)], 0.085)
    c.paint(m, pal["face"], pal["outline"])


def _head(c: _Canvas, g: _Geo, hx: float, hy: float, pal) -> Image.Image:
    m = c.mask()
    c.ellipse(m, hx, hy, g.R, g.R)
    c.paint(m, pal["face"], pal["outline"])
    return m


def _hair(c: _Canvas, g: _Geo, kind: int, hx: float, hy: float, pal, side: int, sleeping: bool):
    R = g.R
    col, oc = pal["hair"], pal["hair_outline"]
    if kind == 0:      # bob: a cap that wraps the top and both sides, face window in front
        m = c.ellipse(c.mask(), hx, hy + 0.015, R + 0.02, R + 0.02)
        for sgn in (-1, 1):
            c.ellipse(m, hx + sgn * (R - 0.02), hy - R * 0.45, 0.07, R * 0.55)
        win = c.ellipse(c.mask(), hx, hy - R * 0.22, R * 0.80, R * 0.86)
        c.paint(c.cut(m, win), col, oc)
    elif kind == 1:    # tuft: three lively strokes from the crown over a short cap
        m = c.mask()
        k = 1.0 if not sleeping else 0.6
        for (dx, dyy) in ((-0.11, 0.11), (0.0, 0.16), (0.11, 0.10)):
            c.stroke(m, [(hx + dx * 0.4, hy + R - 0.02), (hx + dx * k + (0.03 * side if sleeping else 0), hy + R + dyy * k)], 0.05)
        cap = c.ellipse(c.mask(), hx, hy + R * 0.55, R * 0.72, R * 0.36)
        c.paint(ImageChops.lighter(m, cap), col, oc)
    elif kind == 2:    # crop: a close cap with a scalloped fringe
        cap = c.ellipse(c.mask(), hx, hy + R * 0.10, R * 1.04, R * 1.0)
        cap = c.above(cap, hy + R * 0.22)
        fringe = c.mask()
        for k in (-0.6, 0.0, 0.6):
            c.ellipse(fringe, hx + k * R, hy + R * 0.20, R * 0.40, R * 0.28)
        disc = c.ellipse(c.mask(), hx, hy, R * 1.02, R * 1.02)
        cap = ImageChops.lighter(cap, ImageChops.multiply(fringe, disc))
        c.paint(cap, col, oc)
    elif kind == 3:    # bun: a short cap and a bun on top, tilted to one side
        cap = c.above(c.ellipse(c.mask(), hx, hy + R * 0.08, R * 1.03, R * 0.98), hy + R * 0.30)
        c.ellipse(cap, hx + side * R * 0.15, hy + R * 1.08, R * 0.40, R * 0.36)
        c.paint(cap, col, oc)
    elif kind == 4:    # flower: a short hair cap and a blossom tucked over one ear
        m = c.above(c.ellipse(c.mask(), hx, hy + R * 0.30, R + 0.015, R * 0.74), hy + R * 0.28)
        c.paint(m, col, oc)
        fx, fy = hx + side * (R * 0.78), hy + R * 0.42
        fm = c.mask()
        for k in range(5):
            a = 2 * math.pi * k / 5
            c.ellipse(fm, fx + 0.042 * math.cos(a), fy + 0.042 * math.sin(a), 0.032, 0.032)
        c.paint(fm, pal["accent"], pal["outline"], ow=c.ow * 0.7)
        c.paint(c.ellipse(c.mask(), fx, fy, 0.024, 0.024), SPARK)
    else:              # curlcap: bumps along the crown (a yarn pom cap, toy-like)
        cap = c.above(c.ellipse(c.mask(), hx, hy + R * 0.10, R * 1.02, R * 0.98), hy + R * 0.25)
        for k in range(5):
            a = math.pi * (0.12 + 0.76 * k / 4)
            c.ellipse(cap, hx + math.cos(a) * R * 0.92, hy + R * 0.05 + math.sin(a) * R * 0.92, R * 0.32, R * 0.32)
        c.paint(cap, col, oc)


def _hat(c: _Canvas, g: _Geo, kind: int, hx: float, hy: float, pal, side: int) -> Optional[Image.Image]:
    """Builder-tier hat over the hair: beanie (accent, band, bobble) or hood (accent ring, wide face window).
    Returns the face window mask for a hood (the face is repainted inside it), else None."""
    R = g.R
    if kind == 1:      # beanie
        m = c.above(c.ellipse(c.mask(), hx, hy + R * 0.24, R * 1.06, R * 0.92), hy + R * 0.30)
        c.paint(m, pal["accent"], pal["outline"])
        band = c.rrect(c.mask(), hx - R * 1.1, hy + R * 0.30, hx + R * 1.1, hy + R * 0.48, 0.02)
        c.paint(ImageChops.multiply(band, c.inner(m)), _mix(pal["accent"], pal["outline"], 0.25))
        c.paint(c.ellipse(c.mask(), hx + side * R * 0.05, hy + R * 1.14, R * 0.24, R * 0.24), _mix(pal["accent"], WHITE, 0.4), pal["outline"])
        return None
    if kind == 2:      # hood: thin rim, big face window, soft point
        m = c.ellipse(c.mask(), hx, hy + 0.01, R * 1.16, R * 1.16)
        c.poly(m, [(hx - R * 0.6, hy + R * 0.8), (hx + R * 0.6, hy + R * 0.8), (hx + side * R * 0.25, hy + R * 1.38)])
        c.poly(m, [(hx - R * 1.16, hy), (hx + R * 1.16, hy), (hx + R * 0.95, hy - R * 1.25), (hx - R * 0.95, hy - R * 1.25)])
        win = c.ellipse(c.mask(), hx, hy - R * 0.06, R * 0.90, R * 0.94)
        c.paint(c.cut(m, win), pal["accent"], pal["outline"])
        return win
    return None


def _elder_hat(c: _Canvas, g: _Geo, hx: float, hy: float, pal, side: int, kind: int):
    R = g.R
    if kind == 0:      # brim hat: wide oval brim + a domed crown, band in the tunic colour
        brim = c.ellipse(c.mask(), hx, hy + R * 0.62, R * 1.5, R * 0.30)
        c.paint(brim, _mix(pal["accent"], pal["outline"], 0.2), pal["outline"])
        crown = c.ellipse(c.mask(), hx, hy + R * 0.95, R * 0.80, R * 0.56)
        c.paint(crown, pal["accent"], pal["outline"])
        band = c.rrect(c.mask(), hx - R * 0.8, hy + R * 0.62, hx + R * 0.8, hy + R * 0.76, 0.01)
        c.paint(ImageChops.multiply(band, c.inner(crown)), pal["main"])
    else:              # stocking cap: a soft dome that folds over to one side and ends in a bobble
        m = c.mask()
        c.ellipse(m, hx, hy + R * 0.62, R * 1.0, R * 0.62)
        c.stroke(m, [(hx, hy + R * 1.15), (hx + side * R * 0.55, hy + R * 1.45), (hx + side * R * 1.05, hy + R * 1.15)], R * 0.62)
        c.paint(m, pal["accent"], pal["outline"])
        c.paint(c.ellipse(c.mask(), hx + side * R * 1.15, hy + R * 1.05, 0.055, 0.055), pal["face"], pal["outline"])
        band = c.rrect(c.mask(), hx - R * 1.04, hy + R * 0.48, hx + R * 1.04, hy + R * 0.72, 0.03)
        c.paint(band, _mix(pal["accent"], pal["outline"], 0.25), pal["outline"])


def _face(c: _Canvas, g: _Geo, hx: float, hy: float, gn: Dict, eyes: str, mouth: str, look: float):
    """Lidded ink-dot eyes (a 2 px pupil under a faint eyelid hairline, a glint when wide), cheeks, a small mouth."""
    R = g.R
    ex = {0: 0.075, 1: 0.070, 2: 0.095}[gn["eyes"]] * (R / 0.20)
    ey = hy - R * 0.10
    pr = 0.033 if gn["eyes"] != 1 else 0.030          # pupil radius: ~2 px at 34 px, 4 px at 2x
    pry = pr * (1.25 if gn["eyes"] == 1 else 1.0)
    m = c.mask()
    if eyes in ("open", "big"):
        k = 1.25 if eyes == "big" else 1.0
        for sgn in (-1, 1):
            c.ellipse(m, hx + sgn * ex + look, ey, pr * k, pry * k)
        c.paint(m, INK)
        if eyes == "big" or c.S >= 60:
            hm = c.mask()
            for sgn in (-1, 1):
                c.ellipse(hm, hx + sgn * ex + look - pr * 0.35, ey + pry * 0.4, pr * 0.40, pr * 0.40)
            c.paint(hm, WHITE)
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


def _accessory_torso(c: _Canvas, g: _Geo, kind: int, pal, side: int, up: float, torso: Image.Image):
    """Kit worn on the tunic (builder tier and up): belt, badge, apron, satchel."""
    inner = c.inner(torso)
    top, hem = g.top + up, g.hem + up
    if kind == 1:      # wide accent belt with a bright buckle (replaces the plain belt)
        by = hem + (top - hem) * 0.34
        m = c.rrect(c.mask(), -0.4, by - 0.03, 0.4, by + 0.03, 0.01)
        c.paint(ImageChops.multiply(m, inner), pal["accent"])
        c.paint(c.ellipse(c.mask(), 0.0, by, 0.028, 0.028), SPARK, pal["outline"], ow=c.ow * 0.6)
    elif kind == 3:    # badge
        c.paint(c.ellipse(c.mask(), side * 0.08, top - 0.09, 0.034, 0.034), pal["accent"], pal["outline"], ow=c.ow * 0.7)
    elif kind == 4:    # apron
        m = c.mask()
        c.poly(m, [(-g.ws * 0.55, top - 0.04), (g.ws * 0.55, top - 0.04), (g.wh * 0.75, hem - 0.01), (-g.wh * 0.75, hem - 0.01)])
        c.paint(ImageChops.multiply(m, inner), CREAM)
        c.paint(c.stroke(c.mask(), [(-g.ws * 0.55, top - 0.04), (g.ws * 0.55, top - 0.04)], 0.022), pal["accent"])
    elif kind == 2:    # satchel: a small bag on the hip with a strap across the chest
        c.paint(c.stroke(c.mask(), [(-side * g.ws * 0.8, top + 0.01), (side * g.wh * 0.9, hem + 0.06)], 0.035), WOOD, pal["outline"], ow=c.ow * 0.7)
        bx = side * g.wh * 0.6
        c.paint(c.rrect(c.mask(), bx - 0.06, hem - 0.02, bx + 0.06, hem + 0.09, 0.025), WOOD, pal["outline"])
        c.paint(c.rrect(c.mask(), bx - 0.06, hem + 0.05, bx + 0.06, hem + 0.09, 0.02), pal["accent"])


def _accessory_hand(c: _Canvas, g: _Geo, kind: int, pal, side: int, arms, pose: Dict):
    """Kit held in the hand (builder tier and up): a walking staff or a hand lantern, in the side hand when that hand is
    free (rest / walk / look / speak on the other side); skipped in carry, wave, point, hop and joy frames."""
    if pose["item"] or pose["hands"] or pose["dy"] > 0.1 or pose["up"]:
        return
    arm = arms[1 if side == 1 else 0]
    hx, hy = arm[-1]
    if kind == 5:      # staff through the hand, knob at head height
        top = min(1.02, g.hy + g.R * 0.7)
        c.paint(c.stroke(c.mask(), [(hx + side * 0.03, 0.0), (hx + side * 0.03, top)], 0.034), WOOD, pal["outline"])
        c.paint(c.ellipse(c.mask(), hx + side * 0.03, top, 0.032, 0.032), pal["accent"], pal["outline"])
    elif kind == 6:    # lantern hanging from the hand
        c.paint(c.stroke(c.mask(), [(hx, hy - 0.02), (hx, hy - 0.08)], 0.018), pal["outline"])
        c.paint(c.rrect(c.mask(), hx - 0.048, hy - 0.20, hx + 0.048, hy - 0.08, 0.015), LANTERN, pal["outline"])
        c.paint(c.rrect(c.mask(), hx - 0.026, hy - 0.175, hx + 0.026, hy - 0.105, 0.01), (255, 246, 200))


def _accessory_back(c: _Canvas, g: _Geo, kind: int, pal, side: int, up: float):
    """Kit behind the body: the shoulder tool (a mallet slung over the shoulder)."""
    if kind == 7:
        c.paint(c.stroke(c.mask(), [(-side * 0.08, g.hem + up + 0.06), (side * 0.22, g.top + up + 0.30)], 0.035), WOOD, pal["outline"])
        bx, by = side * 0.22, g.top + up + 0.30
        c.paint(c.rrect(c.mask(), bx - 0.07, by - 0.04, bx + 0.07, by + 0.05, 0.02), IRON, pal["outline"])


def _scarf(c: _Canvas, g: _Geo, pal, side: int, up: float):
    top = g.top + up
    c.paint(c.rrect(c.mask(), -g.ws - 0.03, top - 0.02, g.ws + 0.03, top + 0.06, 0.04), pal["accent"], pal["outline"])
    c.paint(c.stroke(c.mask(), [(side * g.ws * 0.6, top + 0.01), (side * (g.ws + 0.11), top - 0.12)], 0.06), pal["accent"], pal["outline"])


def _item(c: _Canvas, g: _Geo, kind: str, pal, side: int):
    y = g.hem + 0.21
    if kind == "berry":   # a small wooden basket heaped with berries
        c.paint(c.poly(c.mask(), [(-0.10, y + 0.02), (0.10, y + 0.02), (0.08, y - 0.08), (-0.08, y - 0.08)]), WOOD, pal["outline"])
        c.paint(c.ellipse(c.mask(), 0.0, y + 0.02, 0.105, 0.03), _mix(WOOD, WHITE, 0.25), pal["outline"], ow=c.ow * 0.7)
        m = c.mask()
        for (dx, dyy) in ((-0.05, 0.035), (0.05, 0.035), (0.0, 0.06), (-0.015, 0.03), (0.03, 0.03)):
            c.ellipse(m, dx, y + dyy, 0.03, 0.03)
        c.paint(m, BERRY, pal["outline"], ow=c.ow * 0.6)
    elif kind == "stone":
        c.paint(c.ellipse(c.mask(), 0.0, y, 0.12, 0.085), STONE, pal["outline"])
        c.paint(c.ellipse(c.mask(), -0.035, y + 0.03, 0.045, 0.022), _mix(STONE, WHITE, 0.4))
    else:  # tool: a hafted mallet held diagonally
        c.paint(c.stroke(c.mask(), [(-side * 0.12, y - 0.12), (side * 0.11, y + 0.14)], 0.035), WOOD, pal["outline"], ow=c.ow * 0.8)
        c.paint(c.rrect(c.mask(), side * 0.11 - 0.07, y + 0.09, side * 0.11 + 0.07, y + 0.18, 0.02), IRON, pal["outline"])


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
        for (x, y, s) in ((hx + 0.16, hy + 0.20, 0.06), (hx + 0.27, hy + 0.32, 0.08)):
            c.stroke(m, [(x - s / 2, y + s / 2), (x + s / 2, y + s / 2), (x - s / 2, y - s / 2), (x + s / 2, y - s / 2)], 0.022)
        c.paint(m, WHITE, pal["outline"], ow=c.ow * 0.5)


# ----------------------------------------------------------------------------- lighting + downsample
def _light(layer: Image.Image, S: float, ss: int, sun: Tuple[float, float]) -> Image.Image:
    """Directional shading from the sun vector: a warm rim on the lit edge, a cool shade band on the far edge."""
    a = np.asarray(layer, dtype=np.float32)
    alpha = a[..., 3]
    mask = alpha > 100
    k = max(2, int(round(0.055 * S * ss)))
    dx, dy = int(round(sun[0] * k)), int(round(sun[1] * k))

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


def _sun_bucket(sun) -> Tuple[float, float]:
    sx, sy = sun
    n = math.hypot(sx, sy) or 1.0
    a = round(math.atan2(sy / n, sx / n) / (math.pi / 4)) * (math.pi / 4)
    return (round(math.cos(a), 3), round(math.sin(a), 3))


# ----------------------------------------------------------------------------- frame render
def _render_sleep(c: _Canvas, g: _Geo, gn: Dict, pal, tier: int):
    """Curled on the ground under an accent blanket: head at one end, shoes peeking, one hand under the cheek."""
    side = gn["side"]
    hx, hy = -side * 0.19, g.R * 0.88
    body = c.mask()
    c.ellipse(body, side * 0.10, 0.12, 0.30, 0.13)
    c.paint(body, pal["main"], pal["outline"])
    legs = c.mask()
    for j in (0, 1):
        c.ellipse(legs, side * (0.34 + 0.02 * j), 0.05 + 0.055 * j, 0.075, 0.042)
    c.paint(legs, pal["shoes"], pal["outline"])
    blanket = c.mask()
    x0 = side * 0.10 - 0.26 if side > 0 else -side * 0.10 - 0.30
    x1 = side * 0.10 + 0.30 if side > 0 else -side * 0.10 + 0.26
    c.rrect(blanket, x0, 0.03, x1, 0.24, 0.09)
    c.paint(blanket, pal["accent"], pal["outline"])
    fold = c.mask()
    fx = -side * 0.16
    c.rrect(fold, min(fx - 0.03, fx + 0.03 * side), 0.16, max(fx - 0.03, fx + 0.03 * side) + 0.02, 0.24, 0.02)
    c.paint(ImageChops.multiply(fold, c.inner(blanket)), _mix(pal["accent"], WHITE, 0.35))
    _head(c, g, hx, hy, pal)
    _hair(c, g, gn["hair"], hx, hy, pal, side, True)        # hats come off for sleep, hair stays
    _hand(c, g, (hx + side * (g.R * 0.75), hy - g.R * 0.55), pal)
    _face(c, g, hx, hy, gn, "sleep", "flat", 0.0)
    _extras(c, g, "zz", pal, side, hx + (0.05 if side > 0 else -0.55), hy)


def _render_body(name: str, tier: int, frame_name: str, zoom: int, sun: Tuple[float, float]) -> np.ndarray:
    gn = _genes(name)
    pal = palette(name)
    S = TIERS[tier]["h"] * zoom
    g = _Geo(tier)
    c = _Canvas(S, max(2, SS // zoom))          # constant working resolution: 2x zoom renders at 2x supersample
    side = gn["side"]
    pose = _pose(frame_name, g, side)
    if pose["lying"]:
        _render_sleep(c, g, gn, pal, tier)
        return _downsample_premult(_light(c.layer, S, c.ss, sun), c.W, c.H)

    c.sx, c.sy, c.dy = pose["sx"], pose["sy"], pose["dy"]
    up = pose["up"]
    hat = gn["hat"] if tier >= 2 else 0
    acc = gn["acc"] if tier >= 2 else -1
    hx = pose["head"][0]
    hy = g.hy + up + pose["head"][1]

    _accessory_back(c, g, acc, pal, side, up)
    if tier == 3:
        _cape(c, g, pal, up, pose["cape_flare"])
    _paint_legs(c, g, pose["legs"], pal)
    torso = _torso(c, g, pal, up, tier)
    if acc >= 0:
        _accessory_torso(c, g, acc, pal, side, up, torso)
    _neck(c, g, hx, hy, pal)
    for arm in pose["arms"]:
        _arm(c, g, arm, pal)
    for i, arm in enumerate(pose["arms"]):
        _hand(c, g, arm[-1], pal, pose["hands"].get(i))
    if pose["item"]:
        _item(c, g, pose["item"], pal, side)
    if acc >= 0:
        _accessory_hand(c, g, acc, pal, side, pose["arms"], pose)
    if acc == 0:
        _scarf(c, g, pal, side, up)
    _head(c, g, hx, hy, pal)
    under = gn["hair"] if gn["hair"] in (0, 4) else 2          # under a hat: bob drops / flower stay, spikes and buns do not
    if tier == 3:
        _hair(c, g, under, hx, hy, pal, side, False)
        _elder_hat(c, g, hx, hy, pal, side, gn["elder_hat"])
    elif hat == 2:
        win = _hat(c, g, 2, hx, hy, pal, side)
        c.paint(win, pal["face"])                    # the face window sits on top of the hood
    else:
        _hair(c, g, under if hat == 1 else gn["hair"], hx, hy, pal, side, False)
        if hat == 1:
            _hat(c, g, 1, hx, hy, pal, side)
    _face(c, g, hx, hy, gn, pose["eyes"], pose["mouth"], pose["look"])
    if pose["extra"]:
        _extras(c, g, pose["extra"], pal, side, hx, hy)
    layer = _light(c.layer, S, c.ss, sun)
    if pose["rot"]:
        layer = layer.rotate(pose["rot"], resample=Image.Resampling.BICUBIC, center=(c.cx, c.gy))
    return _downsample_premult(layer, c.W, c.H)


def _render_shadow(tier: int, frame_name: str, zoom: int, sun: Tuple[float, float]) -> np.ndarray:
    S = TIERS[tier]["h"] * zoom
    g = _Geo(tier)
    c = _Canvas(S, max(2, SS // zoom))
    pose = _pose(frame_name, g, 1)
    scale = pose["shadow"]
    wide = 0.46 if pose["lying"] else 0.34
    sm = Image.new("L", c.layer.size, 0)
    d = ImageDraw.Draw(sm)
    rx, ry = wide * S * c.ss * scale, 0.10 * S * c.ss * scale
    ox = -sun[0] * 0.05 * S * c.ss                 # the shadow slides away from the sun
    oy = -sun[1] * 0.02 * S * c.ss
    d.ellipse([c.cx + ox - rx, c.gy + oy - ry, c.cx + ox + rx, c.gy + oy + ry], fill=255)
    sm = sm.filter(ImageFilter.GaussianBlur(1.1 * c.ss))
    strength = 60 if frame_name == "hop1" else 92
    out = Image.new("RGBA", c.layer.size, (0, 0, 0, 0))
    out.paste(SHADOW + (255,), (0, 0), sm.point(lambda v: v * strength // 255))
    return _downsample_premult(out, c.W, c.H)


# ----------------------------------------------------------------------------- public API
def shadow(tier: int, frame: str = "idle0", zoom: int = 1, sun: Optional[Tuple[float, float]] = None) -> np.ndarray:
    """The ground shadow alone (RGBA, same frame size and anchor as render()). Shrinks for hop1, widens for sit and
    sleep, slides away from the sun. Draw it under the body when the body is offset on a hop parabola."""
    sun_b = _sun_bucket(sun or DEFAULT_SUN)
    key = (int(tier), frame, int(zoom), sun_b)
    arr = _SHADOWS.get(key)
    if arr is None:
        arr = _render_shadow(tier, frame, zoom, sun_b)
        _SHADOWS[key] = arr
    return arr


def render(username: str, tier: int, frame: str, zoom: int = 1, facing: int = 1, sun: Optional[Tuple[float, float]] = None,
           with_shadow: bool = True) -> np.ndarray:
    """One settler frame as an (H, W, 4) uint8 RGBA array, cached per (name, tier, frame, zoom, sun octant).
    facing -1 mirrors the sprite (a walk to the left). with_shadow=False gives the body alone."""
    sun_b = _sun_bucket(sun or DEFAULT_SUN)
    key = ((username or "").lower(), int(tier), frame, int(zoom), sun_b, bool(with_shadow))
    arr = _CACHE.get(key)
    if arr is None:
        body = _render_body(username, tier, frame, zoom, sun_b)
        if with_shadow:
            arr = _downsample_premult(Image.alpha_composite(Image.fromarray(shadow(tier, frame, zoom, sun_b)), Image.fromarray(body)),
                                      body.shape[1], body.shape[0])
        else:
            arr = body
        _CACHE[key] = arr
    return arr if facing >= 0 else arr[:, ::-1].copy()


frame = render      # alias: the mockup generators called it frame(name, tier, frame_name, facing, zoom, sun)


def size(tier: int, zoom: int = 1) -> Tuple[int, int]:
    S = TIERS[tier]["h"] * zoom
    return int(round(1.6 * S)), int(round(1.72 * S))


def anchor(tier: int, zoom: int = 1) -> Tuple[int, int]:
    """(x, y) of the ground point inside a frame of this tier (the feet touch here)."""
    S = TIERS[tier]["h"] * zoom
    W, H = size(tier, zoom)
    return W // 2, int(round(H - 0.14 * S))


def height(tier: int, zoom: int = 1) -> int:
    """Standing height in px (the label goes above anchor_y - height - hat)."""
    return int(TIERS[tier]["h"] * zoom)


def settler_sheet(username: str, tier: int, zoom: int = 1, sun: Optional[Tuple[float, float]] = None,
                  frames: Sequence[str] = FRAMES) -> Dict[str, Image.Image]:
    """All frames of one settler at one tier / zoom / sun octant as PIL RGBA images. Cached; the compositor blits these."""
    sun_b = _sun_bucket(sun or DEFAULT_SUN)
    key = ((username or "").lower(), int(tier), int(zoom), sun_b, tuple(frames))
    sh = _SHEETS.get(key)
    if sh is None:
        sh = {f: Image.fromarray(render(username, tier, f, zoom, 1, sun_b)) for f in frames}
        _SHEETS[key] = sh
    return sh


def head_icon(username: str, px: int = 24, tier: int = 2) -> Image.Image:
    """The settler's head only (hair / hat + face) for name pills and chat rows, from the idle0 frame at 2x."""
    key = ((username or "").lower(), px, tier)
    im = _ICONS.get(key)
    if im is None:
        arr = render(username, tier, "idle0", 2, 1, None, with_shadow=False)
        S = TIERS[tier]["h"] * 2
        ax, ay = anchor(tier, 2)
        g = _Geo(tier)
        R = g.R * S
        cy = ay - g.hy * S
        crop = Image.fromarray(arr).crop((int(ax - R * 1.6), int(cy - R * 1.75), int(ax + R * 1.6), int(cy + R * 1.05)))
        bb = crop.getbbox()
        if bb:
            crop = crop.crop(bb)
        k = px / float(max(crop.width, crop.height))
        crop = crop.resize((max(1, int(crop.width * k)), max(1, int(crop.height * k))), Image.Resampling.LANCZOS)
        im = Image.new("RGBA", (px, px), (0, 0, 0, 0))
        im.paste(crop, ((px - crop.width) // 2, (px - crop.height) // 2), crop)
        _ICONS[key] = im
    return im


def cache_stats() -> Dict[str, int]:
    return {"frames": len(_CACHE), "shadows": len(_SHADOWS), "sheets": len(_SHEETS), "icons": len(_ICONS),
            "bytes": sum(a.nbytes for a in _CACHE.values())}


def clear_cache() -> None:
    _CACHE.clear()
    _SHADOWS.clear()
    _SHEETS.clear()
    _ICONS.clear()


# ----------------------------------------------------------------------------- contact sheet
def sheet_image(names: Sequence[str], bg=(98, 152, 82), sun: Optional[Tuple[float, float]] = None,
                tiers: Optional[Sequence[int]] = None) -> Image.Image:
    """12 settlers x all frames at 1x and 2x, plus the four tiers (idle0). Names are examples."""
    from PIL import ImageFont
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Verdana Bold.ttf", 20)
    small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Verdana.ttf", 20)
    label_w = 262
    c2 = 118
    row1, row2 = 80, 156
    W = label_w + len(FRAMES) * c2 + 4 * 130 + 30
    block = row1 + row2 + 14
    H = 44 + len(names) * block
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    for i, f in enumerate(FRAMES):
        d.text((label_w + i * c2 + 4, 10), f if len(f) < 10 else f.replace("carry_", "c_"), font=small, fill=(20, 30, 16))
    d.text((label_w + len(FRAMES) * c2 + 8, 10), "tiers 0-3 (idle0)", font=small, fill=(20, 30, 16))
    for r, name in enumerate(names):
        y0 = 44 + r * block
        if r % 2 == 0:
            d.rectangle([0, y0, W, y0 + block - 4], fill=tuple(int(v * 0.93) for v in bg))
        pal = palette(name)
        G = genome(name)
        tier = tiers[r] if tiers else (2 if r % 4 != 3 else 3)
        d.rectangle([12, y0 + 10, 40, y0 + 38], fill=pal["main"], outline=pal["outline"], width=2)
        d.rectangle([12, y0 + 44, 40, y0 + 72], fill=pal["accent"], outline=pal["outline"], width=2)
        d.rectangle([12, y0 + 78, 40, y0 + 106], fill=pal["hair"], outline=pal["hair_outline"], width=2)
        d.text((50, y0 + 8), "@" + name, font=font, fill=(250, 244, 226))
        d.text((50, y0 + 36), "%s · %s · %s" % (G["hair"], G["hat"], G["accessory"]), font=small, fill=(232, 236, 220))
        d.text((50, y0 + 60), "%s · %s eyes" % (G["cheeks"], G["eyes"]), font=small, fill=(232, 236, 220))
        d.text((50, y0 + 84), "tier %d %s · 1x / 2x" % (tier, TIER_NAMES[tier]), font=small, fill=(232, 236, 220))
        for zoom, ybase in ((1, y0 + row1 - 8), (2, y0 + row1 + row2 - 6)):
            for i, f in enumerate(FRAMES):
                sp = Image.fromarray(render(name, tier, f, zoom, 1, sun))
                ax, ay = anchor(tier, zoom)
                img.paste(sp, (label_w + i * c2 + c2 // 2 - ax, ybase - ay), sp)
            xt = label_w + len(FRAMES) * c2 + 10
            for t in range(4):
                sp = Image.fromarray(render(name, t, "idle0", zoom, 1, sun))
                ax, ay = anchor(t, zoom)
                img.paste(sp, (xt + t * 130 + 65 - ax, ybase - ay), sp)
    return img


if __name__ == "__main__":
    import sys
    import time
    names = sys.argv[1:] or ["atleastonce", "sami", "kai_dnb", "noor.wav", "luca_99", "mira_9", "zed_ttv", "xX_tobi_Xx",
                             "lowkeyjord", "tinytash", "pixel_dude", "gg_nora"]
    t0 = time.perf_counter()
    for n in names:
        settler_sheet(n, 2, 1)
    dt = time.perf_counter() - t0
    print("rendered %d sheets (%d frames) at 1x in %.2fs = %.1f ms/frame" % (len(names), len(names) * len(FRAMES), dt, dt * 1000 / (len(names) * len(FRAMES))))
    for n in names:
        print("%-14s %s" % (n, describe(n)))
