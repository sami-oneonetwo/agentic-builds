"""creatures.py - settlers-tall: people-shaped SETTLER sprites (SETTLEMENT top-down, 3/4 front view).

Every settler is a real chatter. Identity is procedural and deterministic from the username:

    hue      31-multiplier hash of the lower-cased name -> a hue on a 270 degree wheel that SKIPS the grass band
             (70-160 deg). The name colour is the TUNIC and stays the dominant colour, so labels, roofs and fields match.
    genome   sha1(name) -> hair (crop / bob / tuft / bun / ponytail / curls), hat (none / hood / cap / wide hat),
             scarf, accessory (satchel / staff / lantern / shoulder tool), stylised skin tone (5), hair colour (6),
             which side things hang on, eye shape. Nothing is hand-picked, nothing is a caricature: identical
             friendly features for everyone, gender-neutral by default.

Silhouette language ("travellers"): TALL-LEAN figures, about 3 heads high at the settler tier (2.5 as a child,
3.2 as an elder), a big round head with two ink dot eyes (2-3 px pupils with a 1 px glint) that blink and look
toward the speaker, a straight tunic in the name colour with a belt, long narrow arms that gesture (wave, point,
carry), narrow legs with real 4-frame walk, small boots. Hoods, scarves, satchels and tools in the accent colour.
Bold 1 px outlines on EVERY part (drawn at 4x, downsampled premultiplied), a warm rim on the sun side and a cool
shade on the far side so the figure sits in the same light as the land (sun vector passed in).

Frames (22):
    idle0 idle1 look_l look_r blink               idle sway / breath, gaze, blink
    walk0 walk1 walk2 walk3                        contact, passing (bob up), contact, passing
    hop0 hop1                                       anticipation squash, airborne stretch
    wave0 wave1 point                               long-arm gestures
    sit sleep                                       resting on the ground, curled asleep
    carry_berry carry_stone carry_tool              two-handed carry poses
    speak0 speak1                                   mouth notch + head bob
    joy                                             arms up, squint, grin, sparkles

Tiers (standing height S px at zoom 1): 0 child 26 · 1 youth 31 · 2 settler 36 · 3 elder 40 (+ hat, cape, staff).

    import creatures
    frames = creatures.settler_sheet("sami.exe", tier=2, zoom=1)      # {frame: PIL RGBA}
    arr = creatures.frame("sami.exe", 2, "walk1", facing=-1, zoom=2)  # (H, W, 4) uint8, cached
    creatures.genome("sami.exe"); creatures.palette("sami.exe")["main"]

numpy + pillow only. Python 3.9.
"""
from __future__ import annotations

import colorsys
import hashlib
import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

FRAMES = ("idle0", "idle1", "look_l", "look_r", "blink", "walk0", "walk1", "walk2", "walk3", "hop0", "hop1",
          "wave0", "wave1", "point", "sit", "sleep", "carry_berry", "carry_stone", "carry_tool", "speak0", "speak1", "joy")
TIERS: Dict[int, int] = {0: 26, 1: 31, 2: 36, 3: 40}
TIER_NAMES = ("child", "youth", "settler", "elder")
HAIR_NAMES = ("crop", "bob", "tuft", "bun", "ponytail", "curls")
HAT_NAMES = ("none", "hood", "cap", "widehat")
ACC_NAMES = ("satchel", "staff", "lantern", "tool")

INK = (36, 28, 26)
WHITE = (255, 252, 246)
BLUSH = (240, 122, 128)
SHADOW = (24, 18, 12)
BOOT = (62, 46, 40)
LEATHER = (150, 104, 62)
WOOD = (160, 118, 72)
STONE = (168, 164, 152)
BERRY = (222, 64, 84)
LANTERN = (252, 210, 96)
SKINS = ((250, 226, 200), (238, 204, 168), (214, 170, 126), (176, 124, 88), (136, 96, 70))
HAIRS = ((50, 42, 46), (120, 72, 44), (228, 194, 108), (206, 116, 58), (176, 170, 164), (96, 62, 92))

_CACHE: Dict[Tuple, np.ndarray] = {}
DEFAULT_SUN = (-0.75, -0.66)     # screen-space unit-ish vector TOWARD the sun (x right, y down): evening, west-north-west


# ----------------------------------------------------------------------------- identity
def name_hash(name: str) -> int:
    s = 0
    for ch in (name or "").lower():
        s = (s * 31 + ord(ch)) & 0xFFFFFFFF
    return s


def genome(name: str) -> Dict[str, int]:
    h = hashlib.sha1((name or "").lower().encode("utf-8")).digest()
    return {"hair": h[0] % 6, "hat": (0, 0, 0, 1, 2, 3, 0, 1)[h[1] % 8], "scarf": int(h[2] % 3 == 0),
            "acc": h[3] % 4, "skin": h[4] % 5, "hair_col": h[5] % 6, "side": 1 if h[6] % 2 else -1,
            "eyes": h[7] % 2, "accent_shift": h[8] % 3, "trouser": h[9] % 3}


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


def _scale(c, k: float) -> Tuple[int, int, int]:
    return tuple(max(0, min(255, int(round(v * k)))) for v in c)


def palette(name: str) -> Dict[str, Tuple[int, int, int]]:
    g = genome(name)
    h = hue(name)
    main = _hsv(h, 0.66, 0.90)
    ah = (h + 150 + 40 * g["accent_shift"]) % 360
    if 70 <= ah <= 160:
        ah = (ah + 90) % 360
    accent = _hsv(ah, 0.62, 0.92)
    outline = _mix(_hsv(h, 0.60, 0.30), INK, 0.45)
    trouser = (_hsv(h, 0.40, 0.42), (84, 88, 106), (108, 82, 60))[g["trouser"]]
    return {"main": main, "accent": accent, "outline": outline, "trouser": trouser, "skin": SKINS[g["skin"]],
            "hair": HAIRS[g["hair_col"]], "hue": h}


def colour_hex(name: str) -> str:
    return "#%02X%02X%02X" % palette(name)["main"]


# ----------------------------------------------------------------------------- proportions (body units: 1.0 = S)
# head_r: head radius · sh_y: shoulder line · sh_w: half shoulder width · hem_y: tunic hem · hem_w: half hem width
_PROP = {
    0: dict(head_r=0.215, sh_y=0.575, sh_w=0.150, hem_y=0.320, hem_w=0.165, waist_w=0.135, leg_w=0.080, leg_x=0.070, arm_w=0.062, hand=0.050, foot=(0.075, 0.040)),
    1: dict(head_r=0.195, sh_y=0.620, sh_w=0.150, hem_y=0.345, hem_w=0.160, waist_w=0.130, leg_w=0.075, leg_x=0.070, arm_w=0.060, hand=0.048, foot=(0.075, 0.038)),
    2: dict(head_r=0.180, sh_y=0.650, sh_w=0.150, hem_y=0.360, hem_w=0.160, waist_w=0.125, leg_w=0.072, leg_x=0.072, arm_w=0.058, hand=0.046, foot=(0.075, 0.036)),
    3: dict(head_r=0.168, sh_y=0.670, sh_w=0.155, hem_y=0.370, hem_w=0.165, waist_w=0.128, leg_w=0.072, leg_x=0.074, arm_w=0.058, hand=0.046, foot=(0.078, 0.036)),
}


# ----------------------------------------------------------------------------- drawing helpers
class _Canvas:
    def __init__(self, S: float, ss: int):
        self.S = S
        self.ss = ss
        self.W = int(round(1.30 * S))
        self.H = int(round(1.62 * S))
        self.ow = 1.15 * max(1.0, S / 34.0)            # outline width in output px (1 px at 1x, 2 px at 2x)
        self.cx = self.W * ss / 2.0
        self.gy = (self.H - 0.14 * S) * ss              # ground line (SS px)
        self.layer = Image.new("RGBA", (self.W * ss, self.H * ss), (0, 0, 0, 0))
        self.shadow = Image.new("RGBA", (self.W * ss, self.H * ss), (0, 0, 0, 0))
        self.sx = self.sy = 1.0
        self.dy = 0.0

    def P(self, x: float, y: float) -> Tuple[float, float]:
        """Body units (x right, y up from the ground, in standing heights) -> supersampled pixel coords."""
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

    def shade(self, m: Image.Image, fill, sun: Tuple[float, float], depth: float = 0.05, light_k: float = 1.16, dark_k: float = 0.84):
        """Warm rim on the sun side, cool shade on the far side: the fill mask minus itself shifted along the sun vector."""
        k = depth * self.S * self.ss
        dx, dy = int(round(-sun[0] * k)), int(round(-sun[1] * k))
        if dx == 0 and dy == 0:
            return
        lit = ImageChops.subtract(m, ImageChops.offset(m, dx, dy))
        dark = ImageChops.subtract(m, ImageChops.offset(m, -dx, -dy))
        self.layer.paste(_mix(_scale(fill, light_k), (255, 236, 200), 0.18) + (255,), (0, 0), lit)
        self.layer.paste(_mix(_scale(fill, dark_k), (60, 60, 110), 0.16) + (255,), (0, 0), dark)

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

    def halfplane_below(self, m, y):
        """Keep only the part of the mask below body height y (used to cut hair caps)."""
        cut = self.mask()
        _, py = self.P(0, y)
        ImageDraw.Draw(cut).rectangle([0, py, m.width, m.height], fill=255)
        return ImageChops.multiply(m, cut)

    def halfplane_above(self, m, y):
        cut = self.mask()
        _, py = self.P(0, y)
        ImageDraw.Draw(cut).rectangle([0, 0, m.width, py], fill=255)
        return ImageChops.multiply(m, cut)


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


# ----------------------------------------------------------------------------- poses
def _pose(frame_name: str, p: Dict[str, float], side: int) -> Dict:
    """Concrete geometry for one frame, in body units. Arms are polylines shoulder -> [elbow] -> hand."""
    sh_y, sh_w, hem_y, hem_w, lx = p["sh_y"], p["sh_w"], p["hem_y"], p["hem_w"], p["leg_x"]
    hip_y = hem_y + 0.02
    A = dict(sx=1.0, sy=1.0, dy=0.0, rot=0, up=0.0, head=(0.0, 0.0), eyes="open", mouth="smile", shadow=1.0,
             extra=None, item=None, legs=None, arms=None, hands=None, lying=False)

    def leg(x0, x1, y1, lift=0.0, knee=None):
        return dict(hip=(x0, hip_y), knee=knee, ankle=(x1, y1), foot=(x1, y1 - 0.01 + lift * 0.0), rot=0.0)

    stand = [leg(-lx, -lx - 0.01, 0.045), leg(lx, lx + 0.01, 0.045)]
    down_l = [(-sh_w, sh_y - 0.02), (-(sh_w + 0.045), hem_y + 0.20), (-(sh_w + 0.055), hem_y + 0.02)]
    down_r = [(sh_w, sh_y - 0.02), ((sh_w + 0.045), hem_y + 0.20), ((sh_w + 0.055), hem_y + 0.02)]
    A["legs"], A["arms"] = stand, [down_l, down_r]

    if frame_name == "idle1":                       # breath: a touch wider, a touch lower, head tilts
        A.update(sx=1.025, sy=0.975, head=(0.008 * side, -0.006))
    elif frame_name == "look_l":
        A.update(eyes="look_l")
    elif frame_name == "look_r":
        A.update(eyes="look_r")
    elif frame_name == "blink":
        A.update(eyes="blink")
    elif frame_name.startswith("walk"):
        k = int(frame_name[4])
        A["rot"] = 4
        if k in (0, 2):                             # contact: one leg planted forward, the other lifted behind
            f = -1 if k == 0 else 1                 # which leg is forward (screen left = -1)
            planted = leg(f * lx, f * (lx + 0.03), 0.03)
            lifted = dict(hip=(-f * lx, hip_y), knee=(-f * (lx + 0.02), hip_y - 0.15), ankle=(-f * (lx + 0.005), 0.12), foot=(-f * (lx + 0.02), 0.115), rot=f * 22)
            A["legs"] = [planted, lifted] if f == -1 else [lifted, planted]
            # arms swing opposite to the legs: the arm on the lifted-leg side goes forward (out and up)
            fwd = [(-f * sh_w, sh_y - 0.02), (-f * (sh_w + 0.08), sh_y - 0.14), (-f * (sh_w + 0.11), hem_y + 0.16)]
            back = [(f * sh_w, sh_y - 0.02), (f * (sh_w + 0.03), hem_y + 0.18), (f * (sh_w + 0.02), hem_y + 0.00)]
            A["arms"] = [back, fwd] if f == 1 else [fwd, back]
        else:                                       # passing: legs together-ish, body bobs up
            A.update(dy=0.025, sy=1.01)
            A["legs"] = [leg(-lx, -lx, 0.06), leg(lx, lx, 0.045)] if k == 1 else [leg(-lx, -lx, 0.045), leg(lx, lx, 0.06)]
    elif frame_name == "hop0":                      # anticipation: squash, knees bent, arms back
        A.update(sy=0.86, sx=1.06, eyes="open", mouth="o", shadow=1.05)
        A["legs"] = [dict(hip=(-lx, hip_y), knee=(-(lx + 0.06), hip_y - 0.16), ankle=(-(lx + 0.02), 0.045), foot=(-(lx + 0.02), 0.035), rot=0),
                     dict(hip=(lx, hip_y), knee=((lx + 0.06), hip_y - 0.16), ankle=((lx + 0.02), 0.045), foot=((lx + 0.02), 0.035), rot=0)]
        A["arms"] = [[(-sh_w, sh_y - 0.02), (-(sh_w + 0.12), sh_y - 0.14), (-(sh_w + 0.18), hem_y + 0.08)],
                     [(sh_w, sh_y - 0.02), ((sh_w + 0.12), sh_y - 0.14), ((sh_w + 0.18), hem_y + 0.08)]]
    elif frame_name == "hop1":                      # airborne: stretch, legs tucked, arms up, mouth "o"
        A.update(dy=0.27, sy=1.08, sx=0.95, eyes="big", mouth="o", shadow=0.62)
        A["legs"] = [dict(hip=(-lx, hip_y), knee=(-(lx + 0.02), hip_y - 0.12), ankle=(-(lx - 0.01), 0.13), foot=(-(lx), 0.12), rot=-25),
                     dict(hip=(lx, hip_y), knee=((lx + 0.02), hip_y - 0.12), ankle=((lx - 0.01), 0.13), foot=((lx), 0.12), rot=25)]
        A["arms"] = [[(-sh_w, sh_y - 0.02), (-(sh_w + 0.13), sh_y + 0.10), (-(sh_w + 0.10), sh_y + 0.30)],
                     [(sh_w, sh_y - 0.02), ((sh_w + 0.13), sh_y + 0.10), ((sh_w + 0.10), sh_y + 0.30)]]
    elif frame_name in ("wave0", "wave1"):
        s = side
        wobble = 0.0 if frame_name == "wave0" else 0.07
        raised = [(s * sh_w, sh_y - 0.02), (s * (sh_w + 0.12), sh_y + 0.10), (s * (sh_w + 0.13 + wobble), sh_y + 0.31 - wobble * 0.6)]
        A["arms"] = [down_l, raised] if s == 1 else [raised, down_r]
        A["hands"] = {1 if s == 1 else 0: "open"}
        A.update(head=(0.012 * s, 0.0), mouth="grin" if frame_name == "wave1" else "smile")
    elif frame_name == "point":                     # long arm straight out toward facing (+x), other hand on the hip
        ext = [(sh_w, sh_y - 0.02), ((sh_w + 0.16), sh_y - 0.02), ((sh_w + 0.30), sh_y + 0.005)]
        hip = [(-sh_w, sh_y - 0.02), (-(sh_w + 0.09), hem_y + 0.14), (-(hem_w - 0.02), hem_y + 0.06)]
        A["arms"] = [hip, ext]
        A["hands"] = {1: "point"}
        A.update(eyes="look_r", head=(0.012, 0.0), mouth="o")
    elif frame_name == "sit":                       # upper body drops by the leg length, legs out toward the camera
        drop = -(hem_y - 0.11)
        A.update(up=drop, shadow=1.15)
        A["legs"] = [dict(hip=(-lx, hip_y + drop), knee=(-(lx + 0.03), hip_y + drop - 0.06), ankle=(-(lx + 0.06), -0.02), foot=(-(lx + 0.06), -0.04), rot=0, sole=True),
                     dict(hip=(lx, hip_y + drop), knee=((lx + 0.03), hip_y + drop - 0.06), ankle=((lx + 0.06), -0.02), foot=((lx + 0.06), -0.04), rot=0, sole=True)]
        A["arms"] = [[(-sh_w, sh_y - 0.02 + drop), (-(sh_w + 0.06), sh_y - 0.16 + drop), (-(lx + 0.04), hip_y + drop - 0.05)],
                     [(sh_w, sh_y - 0.02 + drop), ((sh_w + 0.06), sh_y - 0.16 + drop), ((lx + 0.04), hip_y + drop - 0.05)]]
        A.update(eyes="open", mouth="smile")
    elif frame_name == "sleep":
        A.update(lying=True, eyes="sleep", mouth="flat", shadow=1.3, extra="zz")
    elif frame_name.startswith("carry"):
        A["item"] = frame_name.split("_")[1]
        hy = hem_y + 0.13
        A["arms"] = [[(-sh_w, sh_y - 0.02), (-(sh_w + 0.05), hem_y + 0.20), (-0.075, hy)],
                     [(sh_w, sh_y - 0.02), ((sh_w + 0.05), hem_y + 0.20), (0.075, hy)]]
        if A["item"] == "tool":
            A["arms"] = [[(-sh_w, sh_y - 0.02), (-(sh_w + 0.06), hem_y + 0.20), (-0.09, hem_y + 0.10)],
                         [(sh_w, sh_y - 0.02), ((sh_w + 0.09), sh_y - 0.06), (0.12, sh_y - 0.02)]]
        A.update(sy=0.99, sx=1.01)
    elif frame_name in ("speak0", "speak1"):
        k = 0 if frame_name == "speak0" else 1
        A.update(mouth="o" if k == 0 else "O", head=(0.0, 0.018 if k == 0 else -0.008))
        s = side
        gesture = [(s * sh_w, sh_y - 0.02), (s * (sh_w + 0.08), sh_y - 0.16), (s * (sh_w + 0.10 + 0.05 * k), sh_y - 0.12 + 0.06 * k)]
        A["arms"] = [down_l, gesture] if s == 1 else [gesture, down_r]
        A["hands"] = {1 if s == 1 else 0: "open"}
    elif frame_name == "joy":
        A.update(dy=0.04, sy=1.03, eyes="joy", mouth="grin", extra="sparkle", shadow=0.92)
        A["arms"] = [[(-sh_w, sh_y - 0.02), (-(sh_w + 0.12), sh_y + 0.12), (-(sh_w + 0.09), sh_y + 0.31)],
                     [(sh_w, sh_y - 0.02), ((sh_w + 0.12), sh_y + 0.12), ((sh_w + 0.09), sh_y + 0.31)]]
        A["hands"] = {0: "open", 1: "open"}
    return A


# ----------------------------------------------------------------------------- part painters
def _paint_legs(c: _Canvas, legs, pal, p, sun):
    for L in legs:
        m = c.mask()
        pts = [L["hip"]] + ([L["knee"]] if L.get("knee") else []) + [L["ankle"]]
        c.stroke(m, pts, p["leg_w"])
        c.paint(m, pal["trouser"], pal["outline"])
    for L in legs:
        m = c.mask()
        fx, fy = L["foot"]
        rx, ry = p["foot"]
        if L.get("sole"):
            c.ellipse(m, fx, fy, rx * 0.95, ry * 1.9)
        else:
            c.ellipse(m, fx, fy, rx, ry, rot=L.get("rot", 0.0))
        c.paint(m, BOOT, pal["outline"])


def _torso_mask(c: _Canvas, p, up: float) -> Image.Image:
    sh_y, sh_w, hem_y, hem_w, ww = p["sh_y"] + up, p["sh_w"], p["hem_y"] + up, p["hem_w"], p["waist_w"]
    mid = (sh_y + hem_y) / 2.0
    pts = [(-sh_w, sh_y), (-sh_w * 0.55, sh_y + 0.035), (sh_w * 0.55, sh_y + 0.035), (sh_w, sh_y),
           (ww, mid), (hem_w, hem_y), (-hem_w, hem_y), (-ww, mid)]
    m = c.mask()
    c.poly(m, pts)
    # rounded shoulders
    c.ellipse(m, -sh_w * 0.55, sh_y - 0.005, sh_w * 0.47, 0.045)
    c.ellipse(m, sh_w * 0.55, sh_y - 0.005, sh_w * 0.47, 0.045)
    return m


def _paint_cape(c: _Canvas, p, up, pal, side):
    sh_y, sh_w, hem_y, hem_w = p["sh_y"] + up, p["sh_w"], p["hem_y"] + up, p["hem_w"]
    m = c.mask()
    c.poly(m, [(-sh_w - 0.03, sh_y + 0.02), (sh_w + 0.03, sh_y + 0.02), (hem_w + 0.13, hem_y - 0.04 + 0.02 * side),
               (hem_w + 0.04, hem_y - 0.09), (-hem_w - 0.04, hem_y - 0.09), (-hem_w - 0.13, hem_y - 0.04 - 0.02 * side)])
    c.paint(m, pal["accent"], pal["outline"])


def _paint_arm(c: _Canvas, pts, pal, p, hand_kind, sun, sleeve=None):
    m = c.mask()
    c.stroke(m, pts, p["arm_w"])
    c.paint(m, sleeve or pal["main"], pal["outline"])
    hx, hy = pts[-1]
    hm = c.mask()
    r = p["hand"]
    if hand_kind == "open":
        c.ellipse(hm, hx, hy, r * 1.25, r * 1.25)
    elif hand_kind == "point":
        c.ellipse(hm, hx + r * 0.6, hy, r * 1.5, r * 0.9)
    else:
        c.ellipse(hm, hx, hy, r, r)
    c.paint(hm, pal["skin"], pal["outline"])


def _paint_head(c: _Canvas, g, pal, p, head_c, sun, pose):
    hx, hy = head_c
    r = p["head_r"]
    # neck (a short skin stroke behind the chin)
    m = c.mask()
    c.stroke(m, [(hx, hy - r * 0.6), (hx, hy - r - 0.03)], 0.075)
    c.paint(m, pal["skin"], pal["outline"])
    # ponytail behind the head
    if g["hat"] != 1 and g["hair"] == 4:
        m = c.mask()
        c.stroke(m, [(hx + 0.55 * r * g["side"], hy + 0.55 * r), (hx + 1.15 * r * g["side"], hy + 0.15 * r), (hx + 1.05 * r * g["side"], hy - 0.95 * r)], r * 0.42)
        c.paint(m, pal["hair"], pal["outline"])
    # hood is drawn before the face so the face opening sits on top
    face = c.mask()
    c.ellipse(face, hx, hy, r, r * 1.02)
    if g["hat"] == 1:
        m = c.mask()
        c.ellipse(m, hx, hy + 0.06 * r, 1.22 * r, 1.20 * r)
        c.poly(m, [(hx - 0.7 * r, hy + 0.7 * r), (hx + 0.7 * r, hy + 0.7 * r), (hx + 0.35 * r * g["side"], hy + 1.78 * r)])
        c.paint(m, pal["accent"], pal["outline"])
        c.shade(m, pal["accent"], sun, depth=0.045)
        opening = c.mask()
        c.ellipse(opening, hx, hy - 0.10 * r, 0.86 * r, 0.82 * r)
        c.paint(opening, pal["skin"], _scale(pal["accent"], 0.55), ow=c.ow * 0.8)
        face = opening
    else:
        c.paint(face, pal["skin"], pal["outline"])
        c.shade(face, pal["skin"], sun, depth=0.04, light_k=1.06, dark_k=0.90)
        _paint_hair(c, g, pal, hx, hy, r, sun)
    return face


def _paint_hair(c: _Canvas, g, pal, hx, hy, r, sun):
    s = g["side"]
    kind = g["hair"]
    hair = pal["hair"]
    if g["hat"] == 3:                                # wide hat: only a little hair peeks at the sides
        m = c.mask()
        c.ellipse(m, hx - 0.86 * r, hy + 0.05 * r, 0.28 * r, 0.40 * r)
        c.ellipse(m, hx + 0.86 * r, hy + 0.05 * r, 0.28 * r, 0.40 * r)
        c.paint(m, hair, pal["outline"])
    else:
        cap = c.mask()
        c.ellipse(cap, hx, hy + 0.10 * r, 1.06 * r, 1.02 * r)
        cap = c.halfplane_above(cap, hy + 0.22 * r)  # keep the top of the cap
        # fringe: a scalloped lower edge
        fringe = c.mask()
        for k in (-0.6, 0.0, 0.6):
            c.ellipse(fringe, hx + k * r, hy + 0.20 * r, 0.42 * r, 0.30 * r)
        cap = ImageChops.lighter(cap, ImageChops.multiply(fringe, _disc(c, hx, hy, r * 1.04)))
        if kind == 1:                                # bob: side drops framing the face
            c.ellipse(cap, hx - 0.92 * r, hy - 0.05 * r, 0.30 * r, 0.62 * r)
            c.ellipse(cap, hx + 0.92 * r, hy - 0.05 * r, 0.30 * r, 0.62 * r)
        elif kind == 2:                              # tuft: three spikes
            for k, (dx, h) in enumerate(((-0.45, 0.55), (0.05, 0.75), (0.5, 0.5))):
                c.poly(cap, [(hx + (dx - 0.28) * r, hy + 0.75 * r), (hx + (dx + 0.28) * r, hy + 0.75 * r), (hx + (dx + 0.12 * s) * r, hy + (1.0 + h) * r)])
        elif kind == 3:                              # bun on top
            c.ellipse(cap, hx + 0.12 * r * s, hy + 1.12 * r, 0.40 * r, 0.36 * r)
        elif kind == 5:                              # curls: bumps along the crown
            for k in range(5):
                a = math.pi * (0.12 + 0.76 * k / 4)
                c.ellipse(cap, hx + math.cos(a) * 0.95 * r, hy + 0.05 * r + math.sin(a) * 0.95 * r, 0.34 * r, 0.34 * r)
        c.paint(cap, hair, pal["outline"])
        c.shade(cap, hair, sun, depth=0.035, light_k=1.22, dark_k=0.86)
    if g["hat"] == 2:                                # cap / beanie in the accent colour with a band and a bobble
        m = c.mask()
        c.ellipse(m, hx, hy + 0.22 * r, 1.08 * r, 0.95 * r)
        m = c.halfplane_above(m, hy + 0.34 * r)
        c.paint(m, pal["accent"], pal["outline"])
        c.shade(m, pal["accent"], sun, depth=0.04)
        band = c.mask()
        c.poly(band, [(hx - 1.1 * r, hy + 0.34 * r), (hx + 1.1 * r, hy + 0.34 * r), (hx + 1.1 * r, hy + 0.52 * r), (hx - 1.1 * r, hy + 0.52 * r)])
        c.paint(ImageChops.multiply(band, m), _scale(pal["accent"], 0.78))
        bob = c.mask()
        c.ellipse(bob, hx + 0.05 * r * s, hy + 1.18 * r, 0.26 * r, 0.26 * r)
        c.paint(bob, _mix(pal["accent"], WHITE, 0.4), pal["outline"])
    elif g["hat"] == 3:                              # wide hat: brim + crown, accent, band in the main colour
        m = c.mask()
        c.ellipse(m, hx, hy + 0.42 * r, 1.80 * r, 0.52 * r)
        c.paint(m, pal["accent"], pal["outline"])
        c.shade(m, pal["accent"], sun, depth=0.04)
        crown = c.mask()
        c.ellipse(crown, hx, hy + 0.92 * r, 0.86 * r, 0.62 * r)
        c.paint(crown, pal["accent"], pal["outline"])
        c.shade(crown, pal["accent"], sun, depth=0.035)
        band = c.mask()
        c.poly(band, [(hx - 0.9 * r, hy + 0.48 * r), (hx + 0.9 * r, hy + 0.48 * r), (hx + 0.9 * r, hy + 0.66 * r), (hx - 0.9 * r, hy + 0.66 * r)])
        c.paint(ImageChops.multiply(band, crown), pal["main"])


def _disc(c: _Canvas, hx, hy, r) -> Image.Image:
    m = c.mask()
    c.ellipse(m, hx, hy, r, r)
    return m


def _paint_face(c: _Canvas, g, pal, hx, hy, r, state_eyes, state_mouth, face_mask):
    ex = 0.40 * r
    ey = hy - 0.10 * r
    wr = 0.30 * r if g["eyes"] == 0 else 0.26 * r
    wry = wr * 1.05 if g["eyes"] == 0 else wr * 1.35
    pr = 0.175 * r
    gaze = {"look_l": -0.11 * r, "look_r": 0.11 * r}.get(state_eyes, 0.0)
    er = wr
    if state_eyes in ("open", "big", "look_l", "look_r"):
        k = 1.15 if state_eyes == "big" else 1.0
        wm = c.mask()
        for sgn in (-1, 1):
            c.ellipse(wm, hx + sgn * ex, ey, wr * k, wry * k)
        c.paint(wm, (252, 248, 236), pal["outline"], ow=c.ow * 0.55)
        m = c.mask()
        for sgn in (-1, 1):
            c.ellipse(m, hx + sgn * ex + gaze, ey - 0.02 * r, pr * k, pr * k * 1.1)
        c.paint(m, INK)
        hm = c.mask()
        for sgn in (-1, 1):
            c.ellipse(hm, hx + sgn * ex + gaze - 0.35 * pr, ey + 0.35 * pr, pr * 0.34, pr * 0.34)
        c.paint(hm, WHITE)
    elif state_eyes == "blink":
        m = c.mask()
        for sgn in (-1, 1):
            c.stroke(m, [(hx + sgn * ex - er, ey), (hx + sgn * ex + er, ey)], 0.02)
        c.paint(m, INK)
    elif state_eyes == "sleep":
        m = c.mask()
        for sgn in (-1, 1):
            c.arc(m, hx + sgn * ex, ey + 0.10 * r, er * 1.1, er * 0.9, 20, 160, 0.02)
        c.paint(m, INK)
    elif state_eyes == "joy":
        m = c.mask()
        for sgn in (-1, 1):
            c.arc(m, hx + sgn * ex, ey - 0.12 * r, er * 1.15, er * 1.0, 200, 340, 0.024)
        c.paint(m, INK)
    # blush
    bm = c.mask()
    for sgn in (-1, 1):
        c.ellipse(bm, hx + sgn * 0.62 * r, hy - 0.45 * r, 0.20 * r, 0.14 * r)
    c.paint(ImageChops.multiply(bm, face_mask), BLUSH, alpha=120)
    # mouth
    my = hy - 0.50 * r
    m = c.mask()
    if state_mouth == "smile":
        c.arc(m, hx, my + 0.12 * r, 0.26 * r, 0.20 * r, 25, 155, 0.02)
    elif state_mouth == "o":
        c.ellipse(m, hx, my, 0.16 * r, 0.14 * r)
    elif state_mouth == "O":
        c.ellipse(m, hx, my - 0.03 * r, 0.20 * r, 0.19 * r)
    elif state_mouth == "grin":
        d = ImageDraw.Draw(m)
        x0, y0 = c.P(hx - 0.34 * r, my + 0.10 * r)
        x1, y1 = c.P(hx + 0.34 * r, my - 0.24 * r)
        d.chord([x0, y0 - (y1 - y0), x1, y1], 0, 180, fill=255)
    elif state_mouth == "flat":
        c.stroke(m, [(hx - 0.14 * r, my), (hx + 0.14 * r, my)], 0.02)
    c.paint(m, INK)


def _paint_scarf(c: _Canvas, pal, p, head_c, side, up):
    hx, hy = head_c
    r = p["head_r"]
    y = hy - r - 0.005
    m = c.mask()
    c.ellipse(m, hx, y, 0.165, 0.045)
    c.stroke(m, [(hx + side * 0.10, y - 0.01), (hx + side * 0.22, y - 0.05), (hx + side * 0.30, y - 0.02)], 0.055)
    c.paint(m, pal["accent"], pal["outline"])


def _paint_accessory_back(c: _Canvas, g, pal, p, up, tier):
    """Things that sit behind the body: the shoulder tool."""
    if tier >= 2 and g["acc"] == 3:
        s = g["side"]
        m = c.mask()
        c.stroke(m, [(-s * 0.10, p["hem_y"] + up + 0.06), (s * 0.20, 1.06 + up)], 0.035)
        c.paint(m, WOOD, pal["outline"])
        blade = c.mask()
        c.poly(blade, [(s * 0.17, 1.02 + up), (s * 0.30, 1.00 + up), (s * 0.31, 1.07 + up), (s * 0.20, 1.09 + up)])
        c.paint(blade, STONE, pal["outline"])


def _paint_accessory_front(c: _Canvas, g, pal, p, arms, up, tier, pose):
    if tier < 2 or pose["lying"]:
        return
    s = g["side"]
    hand = arms[1 if s == 1 else 0][-1]
    if g["acc"] == 0:                                 # satchel on the hip with a strap across the tunic
        m = c.mask()
        c.stroke(m, [(-s * p["sh_w"] * 0.7, p["sh_y"] + up - 0.01), (s * (p["hem_w"] + 0.02), p["hem_y"] + up + 0.08)], 0.028)
        c.paint(m, pal["accent"], pal["outline"], ow=c.ow * 0.7)
        bag = c.mask()
        bx, by = s * (p["hem_w"] + 0.03), p["hem_y"] + up + 0.07
        c.poly(bag, [(bx - 0.06, by - 0.05), (bx + 0.06, by - 0.05), (bx + 0.06, by + 0.045), (bx - 0.06, by + 0.045)])
        c.paint(bag, LEATHER, pal["outline"])
        flap = c.mask()
        c.poly(flap, [(bx - 0.06, by + 0.045), (bx + 0.06, by + 0.045), (bx + 0.06, by + 0.005), (bx - 0.06, by + 0.005)])
        c.paint(ImageChops.multiply(flap, bag), pal["accent"])
    elif g["acc"] == 1:                               # walking staff through the hand
        hx, hy = hand
        m = c.mask()
        c.stroke(m, [(hx + s * 0.02, 0.0), (hx + s * 0.02, hy + 0.05), (hx + s * 0.03, min(1.02, hy + 0.66))], 0.032)
        c.paint(m, WOOD, pal["outline"])
        knob = c.mask()
        c.ellipse(knob, hx + s * 0.03, min(1.02, hy + 0.66), 0.03, 0.03)
        c.paint(knob, pal["accent"], pal["outline"])
    elif g["acc"] == 2:                               # lantern hanging from the hand
        hx, hy = hand
        m = c.mask()
        c.stroke(m, [(hx, hy - 0.02), (hx, hy - 0.08)], 0.018)
        c.paint(m, pal["outline"])
        box = c.mask()
        c.poly(box, [(hx - 0.045, hy - 0.08), (hx + 0.045, hy - 0.08), (hx + 0.045, hy - 0.19), (hx - 0.045, hy - 0.19)])
        c.paint(box, LANTERN, pal["outline"])
        glass = c.mask()
        c.poly(glass, [(hx - 0.025, hy - 0.10), (hx + 0.025, hy - 0.10), (hx + 0.025, hy - 0.17), (hx - 0.025, hy - 0.17)])
        c.paint(glass, (255, 246, 200))


def _paint_item(c: _Canvas, item, pal, p, up):
    if not item:
        return
    y = p["hem_y"] + 0.13
    if item == "berry":
        m = c.mask()
        c.poly(m, [(-0.10, y + 0.05), (0.10, y + 0.05), (0.08, y - 0.06), (-0.08, y - 0.06)])
        c.paint(m, LEATHER, pal["outline"])
        rim = c.mask()
        c.ellipse(rim, 0.0, y + 0.05, 0.105, 0.03)
        c.paint(rim, _scale(LEATHER, 1.18), pal["outline"], ow=c.ow * 0.7)
        b = c.mask()
        for (dx, dy) in ((-0.05, 0.055), (0.0, 0.075), (0.05, 0.055), (-0.02, 0.05), (0.03, 0.05)):
            c.ellipse(b, dx, y + dy, 0.024, 0.024)
        c.paint(b, BERRY, pal["outline"], ow=c.ow * 0.6)
    elif item == "stone":
        m = c.mask()
        c.ellipse(m, 0.0, y + 0.02, 0.11, 0.075)
        c.paint(m, STONE, pal["outline"])
        hl = c.mask()
        c.ellipse(hl, -0.035, y + 0.045, 0.045, 0.025)
        c.paint(hl, _mix(STONE, WHITE, 0.4))
    elif item == "tool":
        m = c.mask()
        c.stroke(m, [(-0.12, p["hem_y"] + 0.08), (0.16, p["sh_y"] + 0.02)], 0.035)
        c.paint(m, WOOD, pal["outline"])
        blade = c.mask()
        c.poly(blade, [(0.13, p["sh_y"] - 0.02), (0.24, p["sh_y"] - 0.01), (0.25, p["sh_y"] + 0.06), (0.16, p["sh_y"] + 0.07)])
        c.paint(blade, STONE, pal["outline"])


def _extras(c: _Canvas, kind: str, pal, top_y: float):
    if kind == "sparkle":
        m = c.mask()
        for (x, y, r) in ((-0.40, top_y + 0.02, 0.055), (0.42, top_y - 0.10, 0.045)):
            pts = []
            for k in range(8):
                a = math.pi / 4 * k
                rr = r if k % 2 == 0 else r * 0.38
                pts.append((x + rr * math.cos(a), y + rr * math.sin(a)))
            c.poly(m, pts)
        c.paint(m, (255, 226, 120), pal["outline"], ow=c.ow * 0.6)
    elif kind == "zz":
        m = c.mask()
        for (x, y, k) in ((0.30, 0.40, 0.05), (0.40, 0.52, 0.065)):
            c.stroke(m, [(x - k, y + k), (x + k, y + k), (x - k, y - k), (x + k, y - k)], 0.02)
        c.paint(m, WHITE, pal["outline"], ow=c.ow * 0.7)


# ----------------------------------------------------------------------------- frame render
def _sun_bucket(sun) -> Tuple[float, float]:
    sx, sy = sun
    n = math.hypot(sx, sy) or 1.0
    a = round(math.atan2(sy / n, sx / n) / (math.pi / 4)) * (math.pi / 4)
    return (round(math.cos(a), 3), round(math.sin(a), 3))


def genome_at(name: str, tier: int) -> Dict[str, int]:
    """Genome as worn at a tier: children go bare-headed with a tuft or crop, elders always wear a hood or a wide hat."""
    g = dict(genome(name))
    if tier == 0:
        g["hat"] = 0
        g["hair"] = 2 if g["hair"] in (1, 3, 4) else g["hair"]
        g["scarf"] = 0
    elif tier == 3 and g["hat"] == 0:
        g["hat"] = 1 if g["side"] > 0 else 3
    return g


def _render(name: str, tier: int, frame_name: str, zoom: int, sun: Tuple[float, float]) -> np.ndarray:
    g = genome_at(name, tier)
    pal = palette(name)
    p = _PROP[tier]
    S = TIERS[tier] * zoom
    ss = 4 if S < 50 else 3
    c = _Canvas(S, ss)
    pose = _pose(frame_name, p, g["side"])
    c.sx, c.sy, c.dy = pose["sx"], pose["sy"], pose["dy"]
    up = pose["up"]

    # ground shadow, offset away from the sun
    sm = Image.new("L", c.shadow.size, 0)
    d = ImageDraw.Draw(sm)
    k = pose["shadow"]
    rx, ry = 0.24 * S * ss * k, 0.085 * S * ss * k
    ox, oy = -sun[0] * 0.05 * S * ss, -sun[1] * 0.02 * S * ss
    if pose["lying"]:
        rx, ry = 0.36 * S * ss, 0.12 * S * ss
    d.ellipse([c.cx - rx + ox, c.gy - ry + oy, c.cx + rx + ox, c.gy + ry + oy], fill=255)
    sm = sm.filter(ImageFilter.GaussianBlur(1.1 * ss))
    c.shadow.paste(SHADOW + (255,), (0, 0), sm.point(lambda v: v * (60 if frame_name == "hop1" else 92) // 255))

    if pose["lying"]:
        _render_sleeping(c, g, pal, p, tier, sun)
    else:
        hx, hy = pose["head"][0], 1.0 - p["head_r"] + up + pose["head"][1]
        _paint_accessory_back(c, g, pal, p, up, tier)
        if tier == 3:
            _paint_cape(c, p, up, pal, g["side"])
        _paint_legs(c, pose["legs"], pal, p, sun)
        tm = _torso_mask(c, p, up)
        c.paint(tm, pal["main"], pal["outline"])
        c.shade(tm, pal["main"], sun, depth=0.05)
        belt = c.mask()
        by = p["hem_y"] + up + 0.10
        c.poly(belt, [(-0.3, by - 0.02), (0.3, by - 0.02), (0.3, by + 0.02), (-0.3, by + 0.02)])
        c.paint(ImageChops.multiply(belt, _morph(tm, int(2 * round(c.ow * ss) + 1), ImageFilter.MinFilter)), _scale(pal["main"], 0.62))
        buckle = c.mask()
        c.ellipse(buckle, 0.0, by, 0.022, 0.022)
        c.paint(buckle, pal["accent"])
        hands = pose["hands"] or {}
        for i, arm in enumerate(pose["arms"]):
            _paint_arm(c, arm, pal, p, hands.get(i), sun)
        _paint_accessory_front(c, g, pal, p, pose["arms"], up, tier, pose)
        _paint_item(c, pose["item"], pal, p, up)
        if g["scarf"]:
            _paint_scarf(c, pal, p, (hx, hy), g["side"], up)
        face = _paint_head(c, g, pal, p, (hx, hy), sun, pose)
        _paint_face(c, g, pal, hx, hy, p["head_r"], pose["eyes"], pose["mouth"], face)
        if pose["extra"]:
            _extras(c, pose["extra"], pal, 1.0 + up + (0.2 if g["hat"] else 0.1))

    layer = c.layer
    if pose["rot"]:
        layer = layer.rotate(pose["rot"], resample=Image.Resampling.BICUBIC, center=(c.cx, c.gy))
    out = Image.alpha_composite(c.shadow, layer)
    return _downsample_premult(out, c.W, c.H)


def _render_sleeping(c: _Canvas, g, pal, p, tier, sun):
    """Curled on the ground on one side, seen from above: head to one side, tunic a rounded lump, knees drawn up."""
    s = g["side"]
    r = p["head_r"]
    cy = 0.13
    hx, hy = -s * 0.30, cy + 0.06
    # legs folded (behind the body), boots peeking
    m = c.mask()
    c.stroke(m, [(s * 0.10, cy + 0.03), (s * 0.26, cy - 0.01), (s * 0.20, cy - 0.11)], p["leg_w"])
    c.stroke(m, [(s * 0.08, cy - 0.01), (s * 0.24, cy - 0.05), (s * 0.17, cy - 0.13)], p["leg_w"])
    c.paint(m, pal["trouser"], pal["outline"])
    fm = c.mask()
    c.ellipse(fm, s * 0.19, cy - 0.13, p["foot"][1] * 1.2, p["foot"][0] * 0.9)
    c.ellipse(fm, s * 0.15, cy - 0.16, p["foot"][1] * 1.2, p["foot"][0] * 0.9)
    c.paint(fm, BOOT, pal["outline"])
    # body under a blanket in the accent colour (tunic peeks at the shoulder), folded edge toward the head
    tm = c.mask()
    c.ellipse(tm, s * 0.01, cy + 0.02, 0.25, 0.135)
    c.paint(tm, pal["main"], pal["outline"])
    bm = c.mask()
    c.ellipse(bm, s * 0.05, cy + 0.01, 0.22, 0.125)
    c.paint(bm, pal["accent"], pal["outline"])
    c.shade(bm, pal["accent"], sun, depth=0.05)
    fold = c.mask()
    c.stroke(fold, [(-s * 0.16, cy + 0.11), (-s * 0.17, cy - 0.09)], 0.03)
    c.paint(ImageChops.multiply(fold, bm), _mix(pal["accent"], WHITE, 0.35))
    # arm tucked under the cheek
    am = c.mask()
    c.stroke(am, [(-s * 0.10, cy + 0.06), (-s * 0.20, cy - 0.03)], p["arm_w"])
    c.paint(am, pal["main"], pal["outline"])
    hm = c.mask()
    c.ellipse(hm, -s * 0.21, cy - 0.04, p["hand"], p["hand"])
    c.paint(hm, pal["skin"], pal["outline"])
    # head (tilted onto the ground)
    face = c.mask()
    c.ellipse(face, hx, hy, r, r * 1.02)
    if g["hat"] == 1:
        m = c.mask()
        c.ellipse(m, hx, hy + 0.04 * r, 1.2 * r, 1.18 * r)
        c.paint(m, pal["accent"], pal["outline"])
        opening = c.mask()
        c.ellipse(opening, hx, hy - 0.08 * r, 0.84 * r, 0.80 * r)
        c.paint(opening, pal["skin"], _scale(pal["accent"], 0.55), ow=c.ow * 0.8)
        face = opening
    else:
        c.paint(face, pal["skin"], pal["outline"])
        c.shade(face, pal["skin"], sun, depth=0.04, light_k=1.06, dark_k=0.90)
        gg = dict(g)
        gg["hat"] = 0 if g["hat"] != 3 else 0        # hats come off for sleep, hair stays
        _paint_hair(c, gg, pal, hx, hy, r, sun)
    _paint_face(c, g, pal, hx, hy, r, "sleep", "flat", face)
    _extras(c, "zz", pal, 0.0)


# ----------------------------------------------------------------------------- public API
def frame(name: str, tier: int, frame_name: str, facing: int = 1, zoom: int = 1, sun: Optional[Tuple[float, float]] = None) -> np.ndarray:
    sun_b = _sun_bucket(sun or DEFAULT_SUN)
    key = ((name or "").lower(), int(tier), int(zoom), frame_name, sun_b)
    arr = _CACHE.get(key)
    if arr is None:
        arr = _render(name, tier, frame_name, zoom, sun_b)
        _CACHE[key] = arr
    return arr if facing >= 0 else arr[:, ::-1].copy()


def size(tier: int, zoom: int = 1) -> Tuple[int, int]:
    S = TIERS[tier] * zoom
    return int(round(1.30 * S)), int(round(1.62 * S))


def anchor(tier: int, zoom: int = 1) -> Tuple[int, int]:
    """(x, y) of the ground point inside a frame of this tier/zoom (the feet touch here)."""
    S = TIERS[tier] * zoom
    W, H = size(tier, zoom)
    return W // 2, int(round(H - 0.14 * S))


def settler_sheet(username: str, tier: int, zoom: int = 1, sun: Optional[Tuple[float, float]] = None,
                  frames: Sequence[str] = FRAMES) -> Dict[str, Image.Image]:
    """All frames for one settler at one tier and zoom, as PIL RGBA images (the compositor caches these per name)."""
    return {f: Image.fromarray(frame(username, tier, f, 1, zoom, sun)) for f in frames}


def portrait(name: str, tier: int = 2, px: int = 26) -> Image.Image:
    """The settler's head (hat included) as a small RGBA badge for name pills and chat rows."""
    arr = frame(name, tier, "idle0", 1, 2)
    S = TIERS[tier] * 2
    ax, ay = anchor(tier, 2)
    p = _PROP[tier]
    top = int(ay - (1.0 + (0.24 if genome_at(name, tier)["hat"] else 0.12)) * S)
    bot = int(ay - (1.0 - 2.05 * p["head_r"]) * S)
    im = Image.fromarray(arr).crop((0, max(0, top), arr.shape[1], bot))
    bb = im.getbbox()
    if bb:
        im = im.crop(bb)
    k = px / float(max(im.width, im.height))
    im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    out.paste(im, ((px - im.width) // 2, (px - im.height) // 2), im)
    return out


def sheet(name: str, tiers: Sequence[int] = (0, 1, 2, 3), zoom: int = 1, frames: Sequence[str] = FRAMES) -> Dict:
    out = {"name": name, "genome": genome(name), "palette": palette(name), "tiers": {}}
    for t in tiers:
        out["tiers"][t] = {"size": size(t, zoom), "anchor": anchor(t, zoom), "frames": {f: frame(name, t, f, 1, zoom) for f in frames}}
    return out


def describe(name: str) -> str:
    g = genome(name)
    return "%s hair · %s · %s%s · skin %d · hue %d" % (HAIR_NAMES[g["hair"]], HAT_NAMES[g["hat"]], ACC_NAMES[g["acc"]],
                                                        " · scarf" if g["scarf"] else "", g["skin"], int(hue(name)))


# ----------------------------------------------------------------------------- contact sheet
def sheet_image(names: Sequence[str], tier: int = 2, bg=(96, 150, 78)) -> Image.Image:
    """12 settlers x all frames at 1x (plus the 4 tiers) and again at 2x."""
    from PIL import ImageFont
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Verdana Bold.ttf", 20)
    small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Verdana.ttf", 20)
    label_w = 300
    blocks = [(1, 50, 74), (2, 96, 140)]
    W = label_w + len(FRAMES) * 96 + 20
    H = 0
    for zoom, cw, ch in blocks:
        H += 44 + len(names) * (ch + 6) + 30
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    y = 0
    for zoom, cell_w, cell_h in blocks:
        d.text((12, y + 10), "%dx · %s" % (zoom, "all 22 frames (settler tier) · then tiers child / youth / settler / elder" if zoom == 1 else "all 22 frames (settler tier)"), font=font, fill=(250, 244, 226))
        for i, f in enumerate(FRAMES):
            d.text((label_w + i * cell_w + 4, y + 36), f if zoom == 2 else str(i), font=small, fill=(20, 30, 16))
        y += 60
        for r, name in enumerate(names):
            y0 = y + r * (cell_h + 6)
            if r % 2 == 0:
                d.rectangle([0, y0, W, y0 + cell_h], fill=tuple(int(v * 0.94) for v in bg))
            pal = palette(name)
            d.rectangle([12, y0 + 8, 36, y0 + 32], fill=pal["main"], outline=pal["outline"], width=2)
            d.rectangle([12, y0 + 38, 36, y0 + 62], fill=pal["accent"], outline=pal["outline"], width=2)
            d.text((46, y0 + 6), "@" + name, font=font, fill=(250, 244, 226))
            g = genome_at(name, tier)
            d.text((46, y0 + 32), "%s/%s" % (HAIR_NAMES[g["hair"]], HAT_NAMES[g["hat"]]), font=small, fill=(232, 236, 220))
            if cell_h > 100:
                d.text((46, y0 + 58), "%s%s" % (ACC_NAMES[g["acc"]], " · scarf" if g["scarf"] else ""), font=small, fill=(232, 236, 220))
            ax, ay = anchor(tier, zoom)
            for i, f in enumerate(FRAMES):
                sp = Image.fromarray(frame(name, tier, f, 1, zoom))
                img.paste(sp, (label_w + i * cell_w + cell_w // 2 - ax, y0 + cell_h - 8 - ay), sp)
            if zoom == 1:
                x = label_w + len(FRAMES) * cell_w + 40
                for t in range(4):
                    sp = Image.fromarray(frame(name, t, "idle0", 1, 1))
                    tx, ty = anchor(t, 1)
                    img.paste(sp, (x + t * 60 + 30 - tx, y0 + cell_h - 8 - ty), sp)
        y += len(names) * (cell_h + 6) + 14
    return img


if __name__ == "__main__":
    import os
    import sys
    import time
    names = sys.argv[1:] or ["kai_dnb", "sami.exe", "noor.wav", "luca_99", "mira_9", "zed_ttv", "xX_tobi_Xx", "lowkeyjord",
                             "tinytash", "atleastonce", "pixel_dude", "gg_nora"]
    t0 = time.perf_counter()
    for n in names:
        settler_sheet(n, 2, 1)
    dt = time.perf_counter() - t0
    print("rendered %d settler sheets (%d frames, 1x) in %.2fs = %.1f ms/frame" % (len(names), len(names) * len(FRAMES), dt, dt * 1000 / (len(names) * len(FRAMES))))
    t0 = time.perf_counter()
    settler_sheet(names[0], 2, 2)
    print("one 2x sheet: %.2fs" % (time.perf_counter() - t0))
    for n in names:
        print("%-14s %s" % (n, describe(n)))
    here = os.path.dirname(os.path.abspath(__file__))
    sheet_image(names).save(os.path.join(here, "settler_sheet.png"))
    print("wrote settler_sheet.png")
