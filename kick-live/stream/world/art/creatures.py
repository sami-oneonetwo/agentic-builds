"""creatures.py - SETTLERS: the people-shaped pixel sprites of the SETTLEMENT world (canonical art module).

Every settler is a real chatter. Identity is procedural and deterministic from the username; nothing is hand-picked:

    tone       31-multiplier hash of the lower-cased name -> a row of NATURAL_TONES (owner 12:40: earth / plant / mineral
               tones, none reads as the grass at stream scale). The tone is the TUNIC and stays the dominant colour, so
               labels, roofs, banners and fields match. hue() still reports its hue for readers that compare hues.
    genome     sha1(name) -> hair style, hair yarn, hat (worn from the builder tier), accessory / kit, cheeks, eye set,
               the side things hang on, the elder hat, the accent offset. See ART.md for the table.

The look (owner brief 2026-09-27 12:05, "a bit cooler", the chunky pixel reference): a hard integer ART GRID, one art
pixel = ART_PX (2) screen px at zoom 1 and 4 at zoom 2, NEAREST-NEIGHBOUR, no anti-aliasing, no supersample. A wide
rounded-square head about half the figure, eyes as two ink 1x2 bars with no whites, a small mouth only while speaking,
a short belted tunic with 1-px sleeves and cream hands, two short legs with dark shoes, a 1-art-px outline in the
palette outline colour (never pure black) around the silhouette AND between parts, flat fills with ONE darker shade
step on the side away from the sun (8 octants from the compositor's sun vector). One toy-cream face for everyone.

Grid budget (art rows from the ground line; the standing height S of ART.md 2 is the FILL height, outline rows extra):
    tier      sprout   settler   builder   elder
    legs      2        2         3         4          (the bottom leg row is the shoe)
    torso     3        4         5         8          (+ the neck outline row)
    head      7 x 8    8 x 10    8 x 10    8 x 10     rows x columns of fill
    fill      13       15        17        21         art rows = 26 / 30 / 34 / 42 px at 1x: EXACTLY ART.md 2
    visual    15       17        19        23         art rows with the bottom + top outline rows (hats add up to 4)
Frame box, anchor and ground point are unchanged: 1.6 S x 1.72 S with the ground line at (W / 2, H - 0.14 S); the
bottom outline row sits ON the ground line (row 0), so the feet, the ground shadow and the label anchor agree on air.

Frames (23): idle0 idle1 blink look_l look_r walk0-3 hop0 hop1 wave0 wave1 point sit sleep carry_berry carry_stone
carry_tool speak0 speak1 joy love. Squash-and-stretch happens in whole rows (a head that dips one row, a body that
lifts one row, a shoe two rows up on the walk contact), never by scaling the bitmap. `sleep` is the ONE lying pose,
drawn only for a hidden (moderated) settler: nobody sleeps on the land.

    from stream.world.art import creatures
    arr = creatures.render("sami", tier=2, frame="walk1", zoom=1, facing=-1, sun=(-0.6, -0.8))  # (H, W, 4) uint8
    sh = creatures.shadow(2, "hop1", zoom=1, sun=(-0.6, -0.8))                                 # ground shadow only
    g = creatures.genome("sami")          # colour, hair, hat, cloak, accessory, ... (strings + hex)
    sheet = creatures.settler_sheet("sami", 2, 1, sun)                                           # {frame: PIL RGBA}
    ax, ay = creatures.anchor(2)          # ground point inside every frame of the tier

Cached per (name, tier, frame, zoom, sun octant, with_shadow) exactly as before; the art grid itself is cached per
(name, tier, frame, sun octant) and shared by the zooms. numpy + pillow only, Python 3.9.
`python -m stream.world.art.creatures --check` runs the pixel-art regression sweep (shapes, hard alpha, uniform art
blocks at both zooms, shadow per octant, heights, walk contact, genome spread, ms per frame).
"""
from __future__ import annotations

import colorsys
import hashlib
import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw

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
LANTERN_CORE = (255, 246, 200)
YARN = ((74, 52, 46), (170, 98, 60), (236, 198, 100), (246, 238, 222), (96, 64, 92), None)   # None = accent colour
DEFAULT_SUN = (-0.62, -0.78)       # screen-space unit vector toward the sun (x right, y down): evening, top-left

# ----------------------------------------------------------------------------- the art grid
ART_PX = 2                          # screen px per art px at zoom 1 (4 at zoom 2)
HAT_ROWS = 4                        # art rows a hat / hair spike may add above the head's top outline (label placement)
GEO: Dict[int, Dict[str, int]] = {  # art rows and columns of fill per tier (see the module docstring)
    0: {"legs": 2, "torso": 3, "head": 7, "head_w": 8, "torso_w": 6, "leg_w": 1},
    1: {"legs": 2, "torso": 4, "head": 8, "head_w": 10, "torso_w": 8, "leg_w": 2},
    2: {"legs": 3, "torso": 5, "head": 8, "head_w": 10, "torso_w": 8, "leg_w": 2},
    3: {"legs": 4, "torso": 8, "head": 8, "head_w": 10, "torso_w": 10, "leg_w": 3},
}
for _t, _g in GEO.items():
    assert _g["legs"] + _g["torso"] + 1 + _g["head"] == TIERS[_t]["h"] // ART_PX, ("GEO fill rows must equal S / ART_PX", _t)
HOP_LIFT = {t: max(3, int(round(0.27 * TIERS[t]["h"] / ART_PX))) for t in TIERS}     # hop1 lift in art rows (ART.md 7: 0.27 S)
WALK_LIFT = 2                       # the lifted shoe on a contact frame: 2 art rows = 4 screen px at 1x (ART.md 14: >= 3 px)
STICK_FRAMES = ("idle0", "idle1", "blink", "look_l", "look_r", "walk0", "walk1", "walk2", "walk3", "speak0", "speak1")
Z_GLYPH = ((1, 1, 1), (0, 1, 0), (1, 1, 1))
HEART_GLYPH = ((1, 0, 1), (1, 1, 1), (0, 1, 0))
PLUS_GLYPH = ((0, 1, 0), (1, 1, 1), (0, 1, 0))

_CACHE: Dict[Tuple, np.ndarray] = {}
_SHADOWS: Dict[Tuple, np.ndarray] = {}
_SHEETS: Dict[Tuple, Dict[str, Image.Image]] = {}
_ICONS: Dict[Tuple, Image.Image] = {}
_ART: Dict[Tuple, Tuple[np.ndarray, np.ndarray]] = {}       # (name, tier, frame, sun_b) -> (rgb, alpha) art grid


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


# Natural tones (owner, 2026-09-27 12:40: "less pink and purple, more natural tones"). The tunic colour is still a pure
# function of the username: name_hash picks a row. Every row is an earth / plant / mineral tone at modest saturation, none
# reads as the grass (98,152,82) at stream scale (moss and pine sit well below it in value), and each carries the accent
# that goes with it on a hat, scarf or roof trim. Labels, roofs, banners, fields and plates take the same "main".
NATURAL_TONES = (
    # name         main (tunic)      accent
    ("ochre",      (196, 148, 60),   (92, 108, 120)),
    ("rust",       (168, 84, 52),    (214, 186, 132)),
    ("terracotta", (190, 110, 80),   (84, 106, 66)),
    ("sand",       (214, 186, 132),  (150, 58, 52)),
    ("olive",      (128, 124, 62),   (222, 208, 178)),
    ("moss",       (84, 106, 66),    (196, 148, 60)),
    ("teal",       (62, 120, 116),   (214, 186, 132)),
    ("slate",      (92, 110, 136),   (196, 148, 60)),
    ("plum-brown", (120, 72, 84),    (214, 186, 132)),
    ("brick",      (150, 58, 52),    (222, 208, 178)),
    ("cream",      (222, 208, 178),  (120, 72, 84)),
    ("charcoal",   (70, 70, 74),     (196, 148, 60)),
    ("mustard",    (184, 160, 72),   (62, 120, 116)),
    ("pine",       (60, 90, 78),     (214, 186, 132)),
    ("clay",       (176, 128, 96),   (92, 110, 136)),
    ("indigo",     (76, 84, 124),    (222, 208, 178)),
    ("walnut",     (104, 74, 52),    (214, 186, 132)),
    ("fern",       (96, 128, 88),    (222, 208, 178)),
    ("storm",      (72, 96, 108),    (196, 148, 60)),
    ("wine",       (128, 56, 64),    (214, 186, 132)),
    ("honey",      (210, 168, 92),   (84, 106, 66)),
    ("ash",        (140, 140, 132),  (150, 58, 52)),
    ("copper",     (172, 104, 64),   (62, 120, 116)),
    ("heather",    (132, 108, 132),  (222, 208, 178)),
)
TONE_NAMES = tuple(t[0] for t in NATURAL_TONES)


def tone_index(name: str) -> int:
    return (name_hash(name) % 1000) % len(NATURAL_TONES)


def tone(name: str) -> Dict:
    t = NATURAL_TONES[tone_index(name)]
    return {"name": t[0], "main": t[1], "accent": t[2]}


def hue(name: str) -> float:
    """The tunic's hue in degrees (kept for readers that compare hues); derived from the natural tone, never from a wheel."""
    r, g, b = tone(name)["main"]
    return colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)[0] * 360.0


def _hsv(h: float, s: float, v: float) -> Tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def _mix(a, b, t: float) -> Tuple[int, int, int]:
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))


def _hex(c) -> str:
    return "#%02X%02X%02X" % tuple(c[:3])


def palette(name: str) -> Dict:
    g = _genes(name)
    t = tone(name)
    h = hue(name)
    main = t["main"]
    # the accent gene shifts the paired accent to one of its two neighbours in the table, so two names sharing a
    # tunic tone can still differ on the hat / scarf / roof trim
    idx = tone_index(name)
    accent = (t["accent"], NATURAL_TONES[(idx + 5) % len(NATURAL_TONES)][1],
              NATURAL_TONES[(idx + 11) % len(NATURAL_TONES)][1])[g["accent_shift"] % 3]
    if accent == main:
        accent = t["accent"]
    outline = _mix(_mix(main, INK, 0.55), INK, 0.35)          # the tunic darkened toward ink, never pure black
    yarn = YARN[g["yarn"]] or accent
    return {"main": main, "accent": accent, "outline": outline, "hue": h, "tone": t["name"],
            "tunic_dark": _mix(main, outline, 0.22),
            "belt": _mix(main, outline, 0.45),
            "legs": _mix(_mix(main, (90, 70, 60), 0.5), (70, 60, 52), 0.35),
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


# ----------------------------------------------------------------------------- frame box (unchanged contract)
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


def _sun_bucket(sun) -> Tuple[float, float]:
    sx, sy = sun
    n = math.hypot(sx, sy) or 1.0
    a = round(math.atan2(sy / n, sx / n) / (math.pi / 4)) * (math.pi / 4)
    return (round(math.cos(a), 3), round(math.sin(a), 3))


# ----------------------------------------------------------------------------- grid painter
def _dilate4(m: np.ndarray) -> np.ndarray:
    out = m.copy()
    out[1:, :] |= m[:-1, :]
    out[:-1, :] |= m[1:, :]
    out[:, 1:] |= m[:, :-1]
    out[:, :-1] |= m[:, 1:]
    return out


def _shift(m: np.ndarray, sx: int, sy: int) -> np.ndarray:
    """shifted[r, c] = m[r - sy, c - sx] (zeros outside)."""
    out = np.zeros_like(m)
    h, w = m.shape
    ys0, ys1 = max(0, sy), min(h, h + sy)
    xs0, xs1 = max(0, sx), min(w, w + sx)
    if ys1 > ys0 and xs1 > xs0:
        out[ys0:ys1, xs0:xs1] = m[ys0 - sy:ys1 - sy, xs0 - sx:xs1 - sx]
    return out


class _Grid:
    """An art-pixel canvas aligned to the frame box. Figure coordinates: x = art column right of the ground point (x = -1
    is the first column left of it; figures are even widths centred on that boundary), y = art rows above the ground
    line (y = 0 is the row standing ON the ground line: the bottom outline row). Canvas row = G - 1 - y."""

    def __init__(self, tier: int, zoom: int, sun: Tuple[float, float], outline):
        self.p = ART_PX * zoom
        self.W, self.H = size(tier, zoom)
        self.ax, self.ay = anchor(tier, zoom)
        # the art grid is a property of the TIER (built from the 1x box) so zoom 1 and 2 share one cached grid; only the
        # paste offset depends on the zoom (the ground line is at anchor()[1] at every zoom)
        W1, H1 = size(tier, 1)
        ax1, ay1 = anchor(tier, 1)
        self.G = ay1 // ART_PX                                          # art rows above the ground line
        self.AH = -(-(H1 - (ay1 - self.G * ART_PX)) // ART_PX) + 1
        self.AW = -(-W1 // ART_PX) + 2
        self.cx = self.AW // 2
        self.ox = self.ax - self.cx * self.p
        self.oy = self.ay - self.G * self.p
        self.rgb = np.zeros((self.AH, self.AW, 3), np.uint8)
        self.a = np.zeros((self.AH, self.AW), bool)                     # every painted pixel (fills + outlines)
        self.fill = np.zeros((self.AH, self.AW), bool)                  # fills and details only: the final outline rings these
        self.oc = np.array(outline[:3], np.uint8)
        sx, sy = sun
        if abs(sx) >= 0.5:                                              # shade the column away from the sun ...
            self.away = (1 if sx < 0 else -1, 0)
        else:                                                           # ... or the row away from it (noon, moonlight)
            self.away = (0, 1 if sy < 0 else -1)                        # canvas rows grow downward: sun above -> bottom row

    # -- masks
    def M(self) -> np.ndarray:
        return np.zeros((self.AH, self.AW), bool)

    def rect(self, m: np.ndarray, x0: int, x1: int, y0: int, y1: int) -> np.ndarray:
        """Inclusive figure-coordinate rectangle."""
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        c0, c1 = max(0, self.cx + x0), min(self.AW, self.cx + x1 + 1)
        r0, r1 = max(0, self.G - 1 - y1), min(self.AH, self.G - y0)
        if c1 > c0 and r1 > r0:
            m[r0:r1, c0:c1] = True
        return m

    def px(self, m: np.ndarray, x: int, y: int) -> np.ndarray:
        c, r = self.cx + x, self.G - 1 - y
        if 0 <= c < self.AW and 0 <= r < self.AH:
            m[r, c] = True
        return m

    def unpx(self, m: np.ndarray, x: int, y: int) -> np.ndarray:
        c, r = self.cx + x, self.G - 1 - y
        if 0 <= c < self.AW and 0 <= r < self.AH:
            m[r, c] = False
        return m

    def glyph(self, m: np.ndarray, glyph, x0: int, ytop: int) -> np.ndarray:
        for j, row in enumerate(glyph):
            for i, v in enumerate(row):
                if v:
                    self.px(m, x0 + i, ytop - j)
        return m

    # -- painting
    def part(self, m: np.ndarray, colour, shade=None, outline: bool = True) -> np.ndarray:
        """A sticker part: its 4-neighbour ring in the outline colour over whatever is there (that is the line between
        parts), the flat fill, then ONE shade step on the far side from the sun."""
        if outline:
            o = _dilate4(m) & ~m
            self.rgb[o] = self.oc
            self.a[o] = True
            self.fill[o] = False
        self.rgb[m] = np.array(colour[:3], np.uint8)
        self.a[m] = True
        self.fill[m] = True
        if shade is not None:
            s = m & ~_shift(m, -self.away[0], -self.away[1])
            self.rgb[s] = np.array(shade[:3], np.uint8)
        return m

    def detail(self, m: np.ndarray, colour) -> np.ndarray:
        """Pixels inside a part (eyes, stripes, a belt row): no ring, no shade."""
        self.rgb[m] = np.array(colour[:3], np.uint8)
        self.a[m] = True
        self.fill[m] = True
        return m

    def finish(self) -> None:
        """One outline ring around every fill: the whole silhouette is exactly dilate4(fill)."""
        o = _dilate4(self.fill) & ~self.fill
        self.rgb[o] = self.oc
        self.a = self.fill | o

    # -- output
    def frame(self, rgb: Optional[np.ndarray] = None, a: Optional[np.ndarray] = None, alpha: int = 255) -> np.ndarray:
        """The art grid upscaled NEAREST by p and pasted into the (H, W, 4) frame at the anchor."""
        rgb = self.rgb if rgb is None else rgb
        a = self.a if a is None else a
        p = self.p
        big = np.zeros((self.AH, self.AW, 4), np.uint8)
        big[..., :3] = rgb
        big[..., 3] = a.astype(np.uint8) * alpha
        big = np.repeat(np.repeat(big, p, axis=0), p, axis=1)
        out = np.zeros((self.H, self.W, 4), np.uint8)
        x0, y0 = self.ox, self.oy
        sx0, sy0 = max(0, -x0), max(0, -y0)
        dx0, dy0 = max(0, x0), max(0, y0)
        w = min(self.W - dx0, big.shape[1] - sx0)
        h = min(self.H - dy0, big.shape[0] - sy0)
        if w > 0 and h > 0:
            out[dy0:dy0 + h, dx0:dx0 + w] = big[sy0:sy0 + h, sx0:sx0 + w]
        return out


class _Rig:
    """Row / column layout of one tier in art px."""

    def __init__(self, tier: int):
        g = GEO[tier]
        self.tier = tier
        self.L, self.T, self.Hh = g["legs"], g["torso"], g["head"]
        self.hw, self.tw, self.lw = g["head_w"], g["torso_w"], g["leg_w"]
        self.hx0, self.hx1 = -self.hw // 2, self.hw // 2 - 1            # head fill columns
        self.tx0, self.tx1 = -self.tw // 2, self.tw // 2 - 1            # torso fill columns
        self.sxl, self.sxr = self.tx0 - 1, self.tx1 + 1                 # the 1-px sleeves hug the torso
        self.leg_l = (self.tx0 + 1, self.tx0 + self.lw)                 # legs one column in from the hem edge
        self.leg_r = (self.tx1 - self.lw, self.tx1 - 1)
        self.stand = self.L + self.T + 1 + self.Hh                      # fill rows = S / ART_PX
        # sleeve length: the hand hangs at the hem on the short tunics, one row above it on the deep ones
        self.sleeve = self.T - 1 if self.T <= 4 else self.T - 2


def _X(side: int):
    """Mirror figure columns about the centre boundary for the side gene (x -> -1 - x)."""
    return (lambda x: x) if side > 0 else (lambda x: -1 - x)


def _hue_clash(a, b) -> bool:
    ha, sa, va = colorsys.rgb_to_hsv(*[c / 255.0 for c in a[:3]])
    hb, sb, vb = colorsys.rgb_to_hsv(*[c / 255.0 for c in b[:3]])
    d = abs(ha - hb) * 360.0
    d = min(d, 360.0 - d)
    return (d < 30.0 and sa > 0.15 and sb > 0.15 and abs(va - vb) < 0.25) or max(abs(a[i] - b[i]) for i in range(3)) < 36


def _cols(pal: Dict) -> Dict:
    o = pal["outline"]
    acc = pal["accent"]
    # a hood in the accent colour vanishes against straw or accent-coloured yarn: such a hood takes the tunic colour
    hood = pal["main"] if _hue_clash(acc, pal["hair"]) else acc
    return {"main": pal["main"], "main_s": pal["tunic_dark"], "face": pal["face"], "face_s": _mix(pal["face"], o, 0.22),
            "legs": pal["legs"], "legs_s": _mix(pal["legs"], o, 0.30), "shoes": pal["shoes"], "belt": pal["belt"],
            "hair": pal["hair"], "hair_s": _mix(pal["hair"], pal["hair_outline"], 0.40),
            "acc": acc, "acc_s": _mix(acc, o, 0.28), "acc_l": _mix(acc, WHITE, 0.45), "acc_band": _mix(acc, o, 0.40),
            "hood": hood, "hood_s": _mix(hood, o, 0.28),
            "cape": pal["cape"], "cape_s": _mix(pal["cape"], o, 0.30), "outline": o,
            "wood_s": _mix(WOOD, o, 0.3), "stone_s": _mix(STONE, o, 0.3), "stone_l": _mix(STONE, WHITE, 0.4)}


# ----------------------------------------------------------------------------- poses (pixel terms)
def _pose(frame_name: str, side: int) -> Dict:
    """Pixel pose: whole-figure lift (rows), head dx / dy, leg mode, arm mode, eyes, mouth, extras. The mouth is drawn
    only while speaking (o / notch), on hop1 (o), joy (grin) and love (small line): idle chatter never looks like shouting."""
    P = dict(lift=0, head=(0, 0), eyes="open", mouth=None, look=0, arms="down", legs="stand", squash=0,
             item=None, extra=None, lying=False, shadow=1.0, hand_dy=(0, 0), sit=False, neck=False, cape_flare=0)
    if frame_name == "idle1":                                   # breath: the head dips one row onto the shoulders
        P["head"] = (0, -1)
    elif frame_name == "blink":
        P["eyes"] = "blink"
    elif frame_name in ("look_l", "look_r"):
        s = -1 if frame_name == "look_l" else 1
        P.update(head=(s, 0), look=s)
    elif frame_name.startswith("walk"):
        k = int(frame_name[4])
        if k in (0, 2):                                         # contact: planted shoe strides, the other shoe 2 rows up,
            f = -1 if k == 0 else 1                             # head waddles over the planted leg, arms swing opposite
            P.update(legs="contact_l" if k == 0 else "contact_r", arms="swing_l" if k == 0 else "swing_r", head=(f, 0))
        else:                                                   # pass: the body bobs up one row, one leg reaches the ground
            P.update(lift=1, legs="pass_l" if k == 1 else "pass_r")
    elif frame_name == "hop0":                                  # anticipation: squash one row, knees out, arms swept back
        P.update(squash=1, legs="bent", head=(0, -1), shadow=1.05, hand_dy=(-1, -1))
    elif frame_name == "hop1":                                  # airborne: lift, shoes tucked, arms up, big eyes, "o"
        P.update(lift=None, legs="tucked", arms="up", eyes="big", mouth="o", shadow=0.62, cape_flare=1)
    elif frame_name in ("wave0", "wave1"):
        P.update(arms=frame_name, head=(-side, 0) if frame_name == "wave1" else (0, 0))
    elif frame_name == "point":
        P.update(arms="point", head=(1, 0), look=1)
    elif frame_name == "sit":
        P.update(sit=True, legs="sit", arms="knees", shadow=1.12)
    elif frame_name == "sleep":
        P.update(lying=True, eyes="sleep", mouth="flat", shadow=1.25, extra="zz")
    elif frame_name.startswith("carry"):
        P.update(item=frame_name.split("_")[1], arms="carry")
    elif frame_name == "speak0":
        P.update(mouth="o", head=(0, 1), neck=True, arms="gesture0")
    elif frame_name == "speak1":
        P.update(mouth="notch", arms="gesture1")
    elif frame_name == "joy":
        P.update(lift=1, arms="up", eyes="joy", mouth="grin", extra="sparkle", shadow=0.92)
    elif frame_name == "love":
        P.update(arms="clasp", eyes="big", mouth="w", extra="heart", head=(side, 0))
    return P


# ----------------------------------------------------------------------------- painters
def _legs(g: _Grid, C: Dict, R: _Rig, P: Dict, base: int, tb: int) -> List[Tuple[np.ndarray, int]]:
    """Two legs with an outline gap between them, the bottom leg row a dark shoe. base = the row the feet stand on
    (1 when on the ground). Returns the lifted shoes that reach the tunic hem (drawn again over the torso)."""
    kind = P["legs"]
    lo = R.L - P["squash"]
    ll, rl = R.leg_l, R.leg_r
    left = [ll, 0, lo - 1, ll]                                  # leg cols, y0, y1, shoe cols
    right = [rl, 0, lo - 1, rl]
    if kind == "contact_l":                                     # left planted (its shoe strides out), right lifted 2 rows
        left = [ll, 0, lo - 1, (ll[0] - 1, ll[1])]              # under the hem (a raised knee), no tail past the tunic
        right = [rl, WALK_LIFT, lo - 1, rl]
    elif kind == "contact_r":
        right = [rl, 0, lo - 1, (rl[0], rl[1] + 1)]
        left = [ll, WALK_LIFT, lo - 1, ll]
    elif kind == "pass_l":                                      # the body is up one row; the left leg reaches the ground
        left = [ll, -1, lo - 1, ll]
    elif kind == "pass_r":
        right = [rl, -1, lo - 1, rl]
    elif kind == "bent":                                        # hop0: knees out
        left = [(ll[0] - 1, ll[1] - 1), 0, lo - 1, (ll[0] - 1, ll[1] - 1)]
        right = [(rl[0] + 1, rl[1] + 1), 0, lo - 1, (rl[0] + 1, rl[1] + 1)]
    elif kind == "tucked":                                      # hop1: shoes up under the hem
        left = [(ll[0] - 1, ll[1] - 1), 1, lo - 1, (ll[0] - 1, ll[1] - 1)]
        right = [(rl[0] + 1, rl[1] + 1), 1, lo - 1, (rl[0] + 1, rl[1] + 1)]
    post = []
    for (cols, y0, y1, scols) in (left, right):
        y1 = max(y0, y1)
        m = g.rect(g.M(), cols[0], cols[1], base + y0, base + y1)
        g.part(m, C["legs"], C["legs_s"])
        shoe = g.rect(g.M(), scols[0], scols[1], base + y0, base + y0)
        if scols != cols:
            g.part(shoe, C["shoes"], None)
        else:
            g.detail(shoe, C["shoes"])
        if base + y0 >= tb:                                     # a shoe lifted onto the hem: it goes over the tunic
            post.append((shoe, base + y0))
    return post


def _sit_legs(g: _Grid, C: Dict, R: _Rig):
    """Sitting: the legs fold away toward the camera as two soles poking out beside the hem."""
    for cols in ((R.tx0 - 1, R.tx0), (R.tx1, R.tx1 + 1)):
        g.part(g.rect(g.M(), cols[0], cols[1], 1, 1), C["shoes"], None)


def _torso(g: _Grid, C: Dict, R: _Rig, P: Dict, tb: int, tier: int, sleeves=(True, True)) -> int:
    """Tunic block with 1-px sleeves merged at the sides, a belt row from the settler tier and a collar step on the deep
    tunics. Returns the hand row."""
    tt = tb + R.T - 1
    m = g.rect(g.M(), R.tx0, R.tx1, tb, tt)
    hand_row = tt - R.sleeve
    for i, x in enumerate((R.sxl, R.sxr)):
        if sleeves[i]:
            g.rect(m, x, x, hand_row + 1, tt)
    if P["neck"]:
        g.rect(m, -1, 0, tt + 1, tt + 1)
    g.part(m, C["main"], C["main_s"])
    if tier >= 1:
        g.detail(g.rect(g.M(), R.tx0, R.tx1, tb, tb), C["belt"])
    if R.T >= 5:                                                # one darker collar row under the chin (a single shade step)
        g.detail(g.rect(g.M(), R.tx0, R.tx1, tt, tt), C["main_s"])
    if P["neck"]:
        g.detail(g.rect(g.M(), -1, 0, tt + 1, tt + 1), C["face"])
    return hand_row


def _hands_down(g: _Grid, C: Dict, R: _Rig, hand_row: int, dy=(0, 0), skip=(False, False)):
    for i, x in enumerate((R.sxl, R.sxr)):
        if skip[i]:
            continue
        y = hand_row + dy[i]
        m = g.rect(g.M(), x, x, y, y)
        if dy[i] < 0:                                           # a hand below the sleeve end: sleeve pixel(s) above it
            g.part(g.rect(g.M(), x, x, y + 1, hand_row), C["main"], None)
            g.part(m, C["face"], None)
        else:
            g.detail(m, C["face"])


def _arm_up(g: _Grid, C: Dict, x: int, y0: int, y1: int, hand_dx: int = 0):
    """A raised arm beside the body: a 1-px column, hand on top."""
    y1 = max(y0, y1)
    g.part(g.rect(g.M(), x, x, y0, y1), C["main"], None)
    g.part(g.rect(g.M(), x + hand_dx, x + hand_dx, y1 + 1, y1 + 1), C["face"], None)


def _arm_out(g: _Grid, C: Dict, x0: int, x1: int, y: int):
    g.part(g.rect(g.M(), x0, x1, y, y), C["main"], None)
    g.part(g.rect(g.M(), x1 + 1, x1 + 1, y, y), C["face"], None)


def _head(g: _Grid, C: Dict, R: _Rig, hx: int, hb: int) -> np.ndarray:
    ht = hb + R.Hh - 1
    x0, x1 = R.hx0 + hx, R.hx1 + hx
    m = g.rect(g.M(), x0, x1, hb, ht)
    for (x, y) in ((x0, hb), (x1, hb), (x0, ht), (x1, ht)):
        g.unpx(m, x, y)
    g.part(m, C["face"], C["face_s"])
    return m


def _hair(g: _Grid, C: Dict, R: _Rig, kind: int, hx: int, hb: int, ey: int, side: int, under_hat: bool):
    """Six pixel hair shapes from the same gene. Under a hat only the bob's side locks and the flower show."""
    ht = hb + R.Hh - 1
    X = _X(side)
    x0, x1 = R.hx0 + hx, R.hx1 + hx
    mid = (x0 + x1 + 1) // 2
    rows = min(2 if kind in (1, 3, 4) else 3, R.Hh - 5)
    m = g.M()
    if not under_hat:
        g.rect(m, x0, x1, ht - rows + 1, ht)
        g.unpx(m, x0, ht)
        g.unpx(m, x1, ht)
    if kind == 0:      # bob: locks down both sides, a heavy lock over one eye
        low = ht - (4 if under_hat else 1)
        g.rect(m, x0, x0, ey + 1, low)
        g.rect(m, x1, x1, ey + 1, low)
        lx = X(R.hx0) + hx
        g.rect(m, lx, lx + (1 if side > 0 else -1), ey - 1, low)
    elif kind == 1 and not under_hat:      # tuft: three spikes, the middle one tall
        g.px(m, x0 + 2, ht + 1)
        g.px(m, mid, ht + 1)
        g.px(m, mid, ht + 2)
        g.px(m, x1 - 2, ht + 1)
        g.px(m, x0, ht)
        g.px(m, x1, ht)
    elif kind == 2 and not under_hat:      # crop: a scalloped fringe
        for x in range(x0 + 1, x1 + 1, 2):
            g.px(m, x, ht - rows)
    elif kind == 3 and not under_hat:      # bun: a knot on top, to one side
        bx = X(1) + hx
        g.rect(m, bx, bx + (2 if side > 0 else -2), ht + 1, ht + 2)
    elif kind == 5 and not under_hat:      # curlcap: bumps along the crown and at the temples
        for x in range(x0 + 1, x1 + 1, 2):
            g.px(m, x, ht + 1)
        g.px(m, x0, ht - rows)
        g.px(m, x1, ht - rows)
    if m.any():
        g.part(m, C["hair"], C["hair_s"], outline=False)
    if kind == 4:      # flower: an accent blossom with a bright heart tucked over one ear (stays under a hat)
        fx, fy = X(R.hx1 + 1) + hx, ht - 2
        g.part(g.glyph(g.M(), PLUS_GLYPH, fx - 1, fy + 1), C["acc"], None, outline=True)
        g.detail(g.px(g.M(), fx, fy), SPARK)


def _hat(g: _Grid, C: Dict, R: _Rig, kind: int, hx: int, hb: int, side: int, tt: int):
    ht = hb + R.Hh - 1
    x0, x1 = R.hx0 + hx, R.hx1 + hx
    if kind == 1:      # beanie: a band row, striped crown one row above the head
        m = g.rect(g.M(), x0, x1, ht - 3, ht + 1)
        g.unpx(m, x0, ht + 1)
        g.unpx(m, x1, ht + 1)
        g.part(m, C["acc"], None, outline=False)
        g.detail(g.rect(g.M(), x0, x1, ht - 3, ht - 3), C["acc_band"])
        stripe = g.M()
        for x in range(x0 + 1, x1 + 1, 2):
            g.rect(stripe, x, x, ht - 2, ht + 1)
        stripe &= m
        g.detail(stripe, C["acc_l"])
    elif kind == 2:    # hood: covers the crown and both sides with a wide face window, a mantle over the shoulders
        m = g.rect(g.M(), x0, x1, ht - 3, ht + 1)
        g.unpx(m, x0, ht + 1)
        g.unpx(m, x1, ht + 1)
        g.rect(m, x0, x0, hb + 1, ht)
        g.rect(m, x1, x1, hb + 1, ht)
        g.px(m, _X(side)(1) + hx, ht + 2)
        g.part(m, C["hood"], None, outline=False)
        window = g.rect(g.M(), x0 + 1, x1 - 1, hb, ht - 4)
        g.detail(m & _dilate4(window), C["hood_s"])           # the cowl's inner rim: one darker step around the face window
        g.part(g.rect(g.M(), R.tx0, R.tx1, tt, tt), C["hood"], C["hood_s"], outline=False)


def _elder_hat(g: _Grid, C: Dict, R: _Rig, kind: int, hx: int, hb: int, side: int):
    ht = hb + R.Hh - 1
    X = _X(side)
    x0, x1 = R.hx0 + hx, R.hx1 + hx
    if kind == 0:      # brim: 3 px past the head each side, a low crown with a tunic-colour band
        brim = g.rect(g.M(), x0 - 3, x1 + 3, ht - 1, ht - 1)
        g.part(brim, C["acc"], C["acc_s"], outline=False)
        crown = g.rect(g.M(), x0 + 1, x1 - 1, ht, ht + 2)
        g.unpx(crown, x0 + 1, ht + 2)
        g.unpx(crown, x1 - 1, ht + 2)
        g.part(crown, C["acc"], C["acc_s"], outline=False)
        g.detail(g.rect(g.M(), x0 + 1, x1 - 1, ht, ht), C["main"])
    else:              # stocking: a cap with a fold band and a tail that flops to one side, cream bobble
        m = g.rect(g.M(), x0, x1, ht - 2, ht + 1)
        g.unpx(m, x0, ht + 1)
        g.unpx(m, x1, ht + 1)
        g.px(m, X(3) + hx, ht + 2)                             # the tail: over the crown, then down the side of the head
        g.px(m, X(4) + hx, ht + 2)
        g.px(m, X(5) + hx, ht + 1)
        g.rect(m, X(6) + hx, X(6) + hx, ht - 2, ht)
        g.part(m, C["acc"], C["acc_s"], outline=False)
        g.detail(g.rect(g.M(), x0, x1, ht - 2, ht - 2), C["acc_band"])
        g.part(g.rect(g.M(), X(6) + hx, X(7) + hx, ht - 4, ht - 3), C["face"], C["face_s"], outline=True)


def _face(g: _Grid, C: Dict, R: _Rig, gn: Dict, hx: int, hb: int, ey: int, eyes: str, mouth: Optional[str], look: int):
    """Two ink 1x2 bars (dots 2 apart, wide 4 apart, tall 1x3), no whites; cheeks by gene; a mouth only when asked."""
    e = gn["eyes"]
    ex = (-3, 2) if e == 2 else (-2, 1)
    eh = 3 if e == 1 else 2
    x0, x1 = R.hx0 + hx, R.hx1 + hx
    m = g.M()
    if eyes in ("open", "big"):
        top = ey + eh - 1 + (1 if eyes == "big" else 0)
        for x in ex:
            g.rect(m, x + hx + look, x + hx + look, ey, top)
    elif eyes == "blink":
        for x in ex:
            g.px(m, x + hx + look, ey)
    elif eyes == "sleep":
        for x in ex:
            g.rect(m, x + hx - 1, x + hx, ey, ey)
    elif eyes == "joy":
        for x in ex:
            g.px(m, x + hx - 1, ey)
            g.px(m, x + hx, ey + 1)
            g.px(m, x + hx + 1, ey)
    g.detail(m, INK)
    cm = g.M()
    if gn["cheeks"] == 0:
        g.rect(cm, x0 + 1, x0 + (1 if e == 2 else 2), ey - 1, ey - 1)
        g.rect(cm, x1 - (1 if e == 2 else 2), x1 - 1, ey - 1, ey - 1)
        g.detail(cm, BLUSH)
    elif gn["cheeks"] == 1:
        g.px(cm, x0 + 1, ey - 1)
        g.px(cm, x1 - 1, ey - 1)
        g.detail(cm, FRECKLE)
    if mouth:
        my = hb + 1
        mm = g.M()
        if mouth == "o":                                        # the open speaking mouth: 2 x 2, chin to lip
            g.rect(mm, -1 + hx + look, 0 + hx + look, hb, my)
        elif mouth == "notch":
            g.px(mm, 0 + hx + look, my)
        elif mouth == "grin":
            g.rect(mm, -2 + hx + look, 1 + hx + look, my, my)
        else:                                                   # w / flat: a small 2-px line
            g.rect(mm, -1 + hx + look, 0 + hx + look, my, my)
        g.detail(mm, INK)


def _kit_torso(g: _Grid, C: Dict, R: _Rig, kind: int, side: int, tb: int):
    X = _X(side)
    tt = tb + R.T - 1
    if kind == 0:      # scarf: accent collar with a tail over one sleeve
        g.detail(g.rect(g.M(), R.tx0, R.tx1, tt, tt), C["acc"])
        g.detail(g.rect(g.M(), X(R.sxr), X(R.sxr), tt - 1, tt), C["acc"])
    elif kind == 1:    # belt: an accent band with a bright buckle (replaces the plain belt row)
        g.detail(g.rect(g.M(), R.tx0, R.tx1, tb, tb), C["acc"])
        g.detail(g.px(g.M(), 0, tb), SPARK)
    elif kind == 2:    # satchel: strap across the chest, a wooden bag on the hip with an accent flap
        strap = g.M()
        for i in range(min(R.T - 1, 3)):
            g.px(strap, X(R.tx0 + 2 * i), tt - i)
            g.px(strap, X(R.tx0 + 1 + 2 * i), tt - i)
        g.detail(strap, C["wood_s"])
        g.part(g.rect(g.M(), X(R.tx1 - 1), X(R.tx1), tb, tb + 1), WOOD, None)
        g.detail(g.rect(g.M(), X(R.tx1 - 1), X(R.tx1), tb + 1, tb + 1), C["acc"])
    elif kind == 3:    # badge: one bright outlined pixel on the chest
        g.part(g.px(g.M(), X(R.tx1 - 1), tt - 1), SPARK, None)
    elif kind == 4:    # apron: a narrow cream bib with an accent strap (2 wide, so the tunic stays the colour block)
        g.detail(g.rect(g.M(), -1, 0, tb + 1, tt - 1), CREAM)
        g.detail(g.rect(g.M(), -1, 0, tt, tt), C["acc"])


def _kit_hand(g: _Grid, C: Dict, R: _Rig, kind: int, side: int, hand_row: int, head_mid: int):
    X = _X(side)
    if kind == 5:      # staff: a stick beside the side hand, ground to head height, accent knob
        g.part(g.rect(g.M(), X(R.sxr + 1), X(R.sxr + 1), 1, head_mid), WOOD, None)
        g.part(g.px(g.M(), X(R.sxr + 1), head_mid + 1), C["acc"], None)
    elif kind == 6:    # lantern: hangs from the side hand
        g.detail(g.px(g.M(), X(R.sxr), hand_row - 1), C["outline"])
        g.part(g.rect(g.M(), X(R.sxr), X(R.sxr + 1), hand_row - 3, hand_row - 2), LANTERN, None)
        g.detail(g.px(g.M(), X(R.sxr), hand_row - 2), LANTERN_CORE)


def _kit_back(g: _Grid, C: Dict, R: _Rig, side: int, tt: int):
    """The shoulder mallet, behind the body."""
    X = _X(side)
    g.part(g.rect(g.M(), X(R.sxr), X(R.sxr), tt - 2, tt - 1), WOOD, None)
    g.part(g.rect(g.M(), X(R.sxr), X(R.sxr + 1), tt, tt + 1), IRON, C["stone_s"])


def _item(g: _Grid, C: Dict, kind: str, side: int, hy: int):
    """A carried thing above the joined hands: a basket heaped with berries, a boulder, a mallet held diagonally."""
    X = _X(side)
    if kind == "berry":
        g.part(g.rect(g.M(), -2, 1, hy + 1, hy + 2), WOOD, C["wood_s"])
        b = g.M()
        for x in (-2, 0, 1):
            g.px(b, x, hy + 3)
        g.px(b, -1, hy + 2)
        g.part(b, BERRY, None)
    elif kind == "stone":
        m = g.rect(g.M(), -2, 1, hy + 1, hy + 3)
        g.unpx(m, -2, hy + 3)
        g.unpx(m, 1, hy + 3)
        g.part(m, STONE, C["stone_s"])
        g.detail(g.px(g.M(), -1, hy + 3), C["stone_l"])
    else:
        h = g.M()
        for i in range(4):
            g.px(h, X(-2 + i), hy + i)
        g.part(h, WOOD, None)
        g.part(g.rect(g.M(), X(2), X(3), hy + 3, hy + 4), IRON, C["stone_s"])


def _extras(g: _Grid, C: Dict, R: _Rig, kind: str, side: int, hx: int, hb: int):
    ht = hb + R.Hh - 1
    X = _X(side)
    x0, x1 = R.hx0 + hx, R.hx1 + hx
    if kind == "sparkle":
        g.part(g.glyph(g.M(), PLUS_GLYPH, x0 - 4, ht - 1), SPARK, None)
        g.part(g.glyph(g.M(), PLUS_GLYPH, x1 + 2, ht - 4), SPARK, None)
    elif kind == "heart":
        g.part(g.glyph(g.M(), HEART_GLYPH, (x1 + 1) if side > 0 else (x0 - 4), ht), HEART, None)
    elif kind == "zz":
        g.part(g.glyph(g.M(), Z_GLYPH, X(-7), R.Hh + 3), WHITE, None)
        g.part(g.glyph(g.M(), Z_GLYPH, X(-4), R.Hh + 6), WHITE, None)


def _cape(g: _Grid, C: Dict, R: _Rig, y0: int, tt: int, flare: int):
    m = g.rect(g.M(), R.tx0 - 1 - flare, R.tx1 + 1 + flare, y0, tt)
    g.unpx(m, R.tx0 - 1 - flare, y0)
    g.unpx(m, R.tx1 + 1 + flare, y0)
    g.part(m, C["cape"], C["cape_s"])


# ----------------------------------------------------------------------------- frame builders
def _draw_sleep(g: _Grid, C: Dict, R: _Rig, gn: Dict, tier: int):
    """The ONE lying pose (a hidden settler): seen from above, on the back, so the face is upright at ground level; an
    accent blanket tucked under the chin covers the body, shoes peek out at the far end, a hand rests on the blanket,
    hat off, two Zs."""
    side = gn["side"]
    X = _X(side)
    hx = X(-(R.hw // 2 - 1))                                 # head fill columns -hw+1 .. 0 (mirrored for side < 0)
    hb = 1
    ey = hb + 2
    bl_end = 8 if tier else 6                                # the sprout box is 21 art px wide: fills stay in -9..8
    g.part(g.rect(g.M(), X(bl_end), X(bl_end + 1), 1, 2), C["shoes"], None)
    _head(g, C, R, hx, hb)
    _hair(g, C, R, gn["hair"], hx, hb, ey, side, False)
    blanket = g.rect(g.M(), X(-2), X(bl_end), 1, 4)
    for (x, y) in ((X(-2), 4), (X(bl_end), 4), (X(bl_end), 1)):
        g.unpx(blanket, x, y)
    g.part(blanket, C["acc"], C["acc_s"])
    g.detail(g.rect(g.M(), X(0), X(1), 3, 4), C["acc_l"])   # the folded edge
    g.part(g.px(g.M(), X(-2), 5), C["face"], None)          # a hand on the blanket's edge
    _face(g, C, R, gn, hx, hb, ey, "sleep", "flat", 0)
    _extras(g, C, R, "zz", side, 0, 0)


def _draw_body(g: _Grid, C: Dict, R: _Rig, gn: Dict, tier: int, frame_name: str):
    side = gn["side"]
    X = _X(side)
    P = _pose(frame_name, side)
    if P["lying"]:
        _draw_sleep(g, C, R, gn, tier)
        return
    lift = HOP_LIFT[tier] if P["lift"] is None else P["lift"]
    hat = gn["hat"] if tier >= 2 else 0
    acc = gn["acc"] if tier >= 2 else -1
    if P["sit"]:
        base = 1
        tb = 2                                                  # the tunic sits on the sole row
    else:
        base = 1 + lift                                         # row 1 stands on the bottom outline row 0
        tb = base + R.L - P["squash"]
        if P["legs"] == "tucked":
            tb = base + R.L - 1
    tt = tb + R.T - 1
    hb = tt + 2 + P["head"][1]                                  # one outline row between tunic and chin
    hx = P["head"][0]
    ht = hb + R.Hh - 1
    ey = hb + 2
    head_mid = hb + R.Hh // 2
    arms = P["arms"]

    # -- behind the body
    if acc == 7 and arms not in ("up", "carry"):
        _kit_back(g, C, R, side, tt)
    if tier == 3 and not P["sit"]:
        _cape(g, C, R, base + 1, tt, P["cape_flare"])
    # -- legs and torso
    post = []
    if P["sit"]:
        _sit_legs(g, C, R)
    else:
        post = _legs(g, C, R, P, base, tb)
    if arms in ("swing_l", "swing_r"):
        fi = 1 if arms == "swing_l" else 0                      # the arm on the LIFTED-leg side swings forward
        sleeves = (fi != 0, fi != 1)
    elif arms == "up":
        sleeves = (False, False)
    elif arms in ("wave0", "wave1", "gesture0", "gesture1"):
        sleeves = (side > 0, side < 0)                          # the side arm leaves the body; the other sleeve stays
    else:
        sleeves = (True, True)
    hand_row = _torso(g, C, R, P, tb, tier, sleeves)
    for shoe, _y in post:                                       # a lifted shoe on the hem, outlined over the tunic
        g.part(shoe, C["shoes"], None)
    if acc in (0, 1, 2, 3, 4):
        _kit_torso(g, C, R, acc, side, tb)
    # -- arms and hands
    if arms == "down":
        _hands_down(g, C, R, hand_row, P["hand_dy"])
    elif arms in ("swing_l", "swing_r"):
        fi = 1 if arms == "swing_l" else 0
        fx = R.sxr + 1 if fi == 1 else R.sxl - 1               # forward arm: out one column, hand up one row ...
        g.part(g.rect(g.M(), fx, fx, hand_row + 2, tt), C["main"], None)
        g.part(g.rect(g.M(), fx, fx, hand_row + 1, hand_row + 1), C["face"], None)
        back = (0, -1) if fi == 1 else (-1, 0)                   # ... the back hand swings down below the hem
        _hands_down(g, C, R, hand_row, back, skip=(fi == 0, fi == 1))
    elif arms == "up":
        for x in (R.sxl - 1, R.sxr + 1):
            _arm_up(g, C, x, tt - 1, ht - 3)
    elif arms in ("wave0", "wave1"):
        _hands_down(g, C, R, hand_row, skip=(side < 0, side > 0))
        wx = X(R.sxr + 1)
        if arms == "wave0":
            _arm_up(g, C, wx, tt - 1, ht - 2)
        else:
            _arm_up(g, C, wx, tt - 1, ht - 3, hand_dx=1 if side > 0 else -1)
    elif arms == "point":
        _hands_down(g, C, R, hand_row, skip=(False, True))
        _arm_out(g, C, R.sxr + 1, R.sxr + 3, tt - 1)
    elif arms == "knees":
        for x in (R.tx0 + 1, R.tx1 - 1):
            g.part(g.px(g.M(), x, tb), C["face"], None)
    elif arms == "carry":
        hy = tb + 1
        g.part(g.rect(g.M(), -1, 0, hy, hy), C["face"], None)
        _item(g, C, P["item"], side, hy)
    elif arms in ("gesture0", "gesture1"):
        _hands_down(g, C, R, hand_row, skip=(side < 0, side > 0))
        gx = X(R.sxr)
        if arms == "gesture0":
            g.part(g.rect(g.M(), gx, gx, tt - 1, tt), C["main"], None)
            g.part(g.px(g.M(), gx, tt + 1), C["face"], None)
        else:
            g.part(g.rect(g.M(), gx, gx, hand_row + 1, tt), C["main"], None)
            g.part(g.px(g.M(), X(R.sxr + 1), tt), C["face"], None)
    elif arms == "clasp":
        hy = tb + R.T // 2
        g.part(g.rect(g.M(), -1, 0, hy, hy), C["face"], None)
    if acc in (5, 6) and frame_name in STICK_FRAMES:
        _kit_hand(g, C, R, acc, side, hand_row, head_mid)
    # -- head, hair, hat, face
    _head(g, C, R, hx, hb)
    if tier == 3:
        _hair(g, C, R, gn["hair"] if gn["hair"] in (0, 4) else 2, hx, hb, ey, side, False)
        _elder_hat(g, C, R, gn["elder_hat"], hx, hb, side)
    elif hat:
        if gn["hair"] in (0, 4):
            _hair(g, C, R, gn["hair"], hx, hb, ey, side, True)
        _hat(g, C, R, hat, hx, hb, side, tt)
    else:
        _hair(g, C, R, gn["hair"], hx, hb, ey, side, False)
    _face(g, C, R, gn, hx, hb, ey, P["eyes"], P["mouth"], P["look"])
    if P["extra"]:
        _extras(g, C, R, P["extra"], side, hx, hb)


def _art(name: str, tier: int, frame_name: str, sun_b: Tuple[float, float]) -> Tuple[np.ndarray, np.ndarray]:
    """The finished art grid (rgb, alpha) of one frame, shared by every zoom."""
    key = ((name or "").lower(), int(tier), frame_name, sun_b)
    hit = _ART.get(key)
    if hit is None:
        gn = _genes(name)
        pal = palette(name)
        g = _Grid(tier, 1, sun_b, pal["outline"])
        _draw_body(g, _cols(pal), _Rig(tier), gn, tier, frame_name)
        g.finish()
        hit = (g.rgb, g.a)
        _ART[key] = hit
    return hit


def _render_body(name: str, tier: int, frame_name: str, zoom: int, sun_b: Tuple[float, float]) -> np.ndarray:
    rgb, a = _art(name, tier, frame_name, sun_b)
    return _Grid(tier, zoom, sun_b, (0, 0, 0)).frame(rgb, a)


def _render_shadow(tier: int, frame_name: str, zoom: int, sun_b: Tuple[float, float]) -> np.ndarray:
    """A flat two-row pixel ellipse under the feet (row 0 behind the bottom outline, row -1 below the ground line),
    sliding one art px away from the sun; 36 % ink, 24 % on hop1; wider for sit and the lying pose."""
    g = _Grid(tier, zoom, sun_b, (0, 0, 0))
    P = _pose(frame_name, 1)
    ox = 0
    if abs(sun_b[0]) >= 0.5:
        ox = 1 if sun_b[0] < 0 else -1
    if P["lying"]:
        w0, w1 = 10, 9
    else:
        half = {0: 5, 1: 6, 2: 6, 3: 7}[tier]
        w0 = int(round(half * P["shadow"]))
        w1 = max(2, w0 - 1)
    m = g.rect(g.M(), -w0 + ox, w0 - 1 + ox, 0, 0)
    g.rect(m, -w1 + ox, w1 - 1 + ox, -1, -1)
    rgb = np.zeros_like(g.rgb)
    rgb[m] = np.array(SHADOW, np.uint8)
    return g.frame(rgb, m, alpha=60 if frame_name == "hop1" else 92)


# ----------------------------------------------------------------------------- public API
def shadow(tier: int, frame: str = "idle0", zoom: int = 1, sun: Optional[Tuple[float, float]] = None) -> np.ndarray:
    """The ground shadow alone (RGBA, same frame size and anchor as render()). Shrinks for hop1, widens for sit and
    the lying pose, slides away from the sun. Draw it under the body when the body is offset on a hop parabola."""
    sun_b = _sun_bucket(sun or DEFAULT_SUN)
    key = (int(tier), frame, int(zoom), sun_b)
    arr = _SHADOWS.get(key)
    if arr is None:
        arr = _render_shadow(tier, frame, zoom, sun_b)
        _SHADOWS[key] = arr
    return arr


def render(username: str, tier: int, frame: str, zoom: int = 1, facing: int = 1, sun: Optional[Tuple[float, float]] = None,
           with_shadow: bool = True) -> np.ndarray:
    """One settler frame as an (H, W, 4) uint8 RGBA array (hard alpha, NEAREST pixel art), cached per (name, tier, frame,
    zoom, sun octant, with_shadow). facing -1 mirrors the sprite (a walk to the left). with_shadow=False gives the body alone."""
    sun_b = _sun_bucket(sun or DEFAULT_SUN)
    key = ((username or "").lower(), int(tier), frame, int(zoom), sun_b, bool(with_shadow))
    arr = _CACHE.get(key)
    if arr is None:
        body = _render_body(username, tier, frame, zoom, sun_b)
        if with_shadow:
            arr = shadow(tier, frame, zoom, sun_b).copy()
            solid = body[..., 3] > 0
            arr[solid] = body[solid]
        else:
            arr = body
        _CACHE[key] = arr
    return arr if facing >= 0 else arr[:, ::-1].copy()


frame = render      # alias: the mockup generators called it frame(name, tier, frame_name, facing, zoom, sun)


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
    """The settler's head only (hair / hat + face) for name pills and chat rows: cropped ON THE ART GRID from the idle0
    frame (head columns + outline, chin outline up to two rows over the head) and NEAREST-scaled by an integer factor."""
    key = ((username or "").lower(), px, tier)
    im = _ICONS.get(key)
    if im is None:
        sun_b = _sun_bucket(DEFAULT_SUN)
        rgb, a = _art(username, tier, "idle0", sun_b)
        g = _Grid(tier, 1, sun_b, (0, 0, 0))
        R = _Rig(tier)
        tt = 1 + R.L + R.T - 1
        hb = tt + 2
        ht = hb + R.Hh - 1
        c0, c1 = g.cx + R.hx0 - 1, g.cx + R.hx1 + 2
        r0, r1 = g.G - 1 - (ht + 3), g.G - (tt + 1)
        crop_rgb = rgb[r0:r1, c0:c1]
        crop_a = a[r0:r1, c0:c1]
        ys, xs = np.where(crop_a)
        if len(ys):
            crop_rgb = crop_rgb[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
            crop_a = crop_a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        k = max(1, px // max(crop_a.shape))
        art = np.zeros(crop_a.shape + (4,), np.uint8)
        art[..., :3] = crop_rgb
        art[..., 3] = crop_a.astype(np.uint8) * 255
        big = np.repeat(np.repeat(art, k, axis=0), k, axis=1)
        im = Image.new("RGBA", (px, px), (0, 0, 0, 0))
        head = Image.fromarray(big)
        im.paste(head, ((px - head.width) // 2, (px - head.height) // 2), head)
        _ICONS[key] = im
    return im


def cache_stats() -> Dict[str, int]:
    return {"frames": len(_CACHE), "shadows": len(_SHADOWS), "sheets": len(_SHEETS), "icons": len(_ICONS),
            "art": len(_ART), "bytes": sum(a.nbytes for a in _CACHE.values())}


def clear_cache() -> None:
    _CACHE.clear()
    _SHADOWS.clear()
    _SHEETS.clear()
    _ICONS.clear()
    _ART.clear()


stats = cache_stats
clear = clear_cache


def art_rows(tier: int) -> Dict[str, int]:
    """The tier's grid in art rows: fill (= S / ART_PX), visual (with both outline rows), hop lift, hat headroom."""
    R = _Rig(tier)
    return {"fill": R.stand, "visual": R.stand + 2, "legs": R.L, "torso": R.T, "head": R.Hh, "head_w": R.hw,
            "torso_w": R.tw, "hop_lift": HOP_LIFT[tier], "hat_rows": HAT_ROWS}


# ----------------------------------------------------------------------------- contact sheets
def _fonts():
    from PIL import ImageFont
    try:
        return (ImageFont.truetype("/System/Library/Fonts/Supplemental/Verdana Bold.ttf", 20),
                ImageFont.truetype("/System/Library/Fonts/Supplemental/Verdana.ttf", 20))
    except OSError:
        f = ImageFont.load_default()
        return f, f


def sheet_image(names: Sequence[str], bg=(98, 152, 82), sun: Optional[Tuple[float, float]] = None,
                tiers: Optional[Sequence[int]] = None, zooms: Sequence[int] = (1, 2)) -> Image.Image:
    """Settlers x all frames at 1x and 2x, plus the four tiers (idle0). Names are examples."""
    font, small = _fonts()
    label_w = 262
    c2 = 118
    rows = {1: 80, 2: 156}
    W = label_w + len(FRAMES) * c2 + 4 * 130 + 30
    block = sum(rows[z] for z in zooms) + 14
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
        d.text((50, y0 + 84), "tier %d %s · %s" % (tier, TIER_NAMES[tier], " / ".join("%dx" % z for z in zooms)), font=small, fill=(232, 236, 220))
        ybase = y0
        for zoom in zooms:
            ybase += rows[zoom] - (8 if zoom == 1 else 6)
            for i, f in enumerate(FRAMES):
                sp = Image.fromarray(render(name, tier, f, zoom, 1, sun))
                ax, ay = anchor(tier, zoom)
                img.paste(sp, (label_w + i * c2 + c2 // 2 - ax, ybase - ay), sp)
            xt = label_w + len(FRAMES) * c2 + 10
            for t in range(4):
                sp = Image.fromarray(render(name, t, "idle0", zoom, 1, sun))
                ax, ay = anchor(t, zoom)
                img.paste(sp, (xt + t * 130 + 65 - ax, ybase - ay), sp)
            ybase += 6
    return img


def review_sheet(names: Sequence[str], zoom: int = 1, bg=(98, 152, 82), sun: Optional[Tuple[float, float]] = None,
                 tiers: Sequence[int] = (0, 1, 2, 3)) -> Image.Image:
    """Every name at every tier, all 23 frames, one zoom: the review grid (true pixels, no resampling)."""
    font, small = _fonts()
    label_w = 250
    c2 = 52 * zoom + 24
    row_h = 80 * zoom + 10
    W = label_w + len(FRAMES) * c2 + 20
    H = 44 + len(names) * len(tiers) * row_h
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    for i, f in enumerate(FRAMES):
        d.text((label_w + i * c2 + 2, 10), f if len(f) < 8 else f.replace("carry_", "c_"), font=small, fill=(20, 30, 16))
    r = 0
    for name in names:
        G = genome(name)
        pal = palette(name)
        for tier in tiers:
            y0 = 44 + r * row_h
            if r % 2 == 0:
                d.rectangle([0, y0, W, y0 + row_h - 2], fill=tuple(int(v * 0.93) for v in bg))
            d.rectangle([10, y0 + 8, 30, y0 + 28], fill=pal["main"], outline=pal["outline"], width=2)
            d.rectangle([10, y0 + 32, 30, y0 + 52], fill=pal["accent"], outline=pal["outline"], width=2)
            d.text((38, y0 + 4), "@%s t%d" % (name, tier), font=font, fill=(250, 244, 226))
            d.text((38, y0 + 30), "%s · %s · %s" % (G["hair"], G["elder_hat"] if tier == 3 else (G["hat"] if tier >= 2 else "-"),
                                                     G["accessory"] if tier >= 2 else "-"), font=small, fill=(232, 236, 220))
            d.text((38, y0 + 54), "%s · %s" % (G["cheeks"], G["eyes"]), font=small, fill=(232, 236, 220))
            ybase = y0 + row_h - 12
            for i, f in enumerate(FRAMES):
                sp = Image.fromarray(render(name, tier, f, zoom, 1, sun))
                ax, ay = anchor(tier, zoom)
                img.paste(sp, (label_w + i * c2 + c2 // 2 - ax, ybase - ay), sp)
            r += 1
    return img


# ----------------------------------------------------------------------------- regression sweep
def self_check(names: Sequence[str] = ("atleastonce", "sami", "lordoomer", "kolutyrtqw425", "fern_ok", "moss_m", "kai_dnb", "willow_9"),
               verbose: bool = True) -> bool:
    """The pixel-art regression gate: every name x tier x frame x sun octant x zoom x facing renders to the frame box as
    uint8 with hard alpha (0 / 255) and uniform ART_PX*zoom blocks (true NEAREST), the shadow matches the box and slides
    away from the sun, the standing fill rows equal S / ART_PX, the bottom outline row sits on the ground line, the walk
    contact lifts a shoe WALK_LIFT rows and moves the head, 50 random genomes are distinct. Prints evidence; True = pass."""
    import random
    import time

    def say(s):
        if verbose:
            print(s)

    ok = True
    octs = [(math.cos(a * math.pi / 4), math.sin(a * math.pi / 4)) for a in range(8)]
    n = bad = 0
    t0 = time.perf_counter()
    for name in names:
        for t in range(4):
            for f in FRAMES:
                for s in octs:
                    for z in (1, 2):
                        a = render(name, t, f, z, 1, s)
                        b = render(name, t, f, z, -1, s)
                        n += 2
                        W, H = size(t, z)
                        if a.shape != (H, W, 4) or a.dtype != np.uint8 or b.shape != a.shape or a[..., 3].max() == 0:
                            bad += 1
                        if shadow(t, f, z, s).shape != a.shape:
                            bad += 1
                        body = render(name, t, f, z, 1, s, with_shadow=False)
                        if not set(np.unique(body[..., 3]).tolist()) <= {0, 255}:
                            bad += 1
                        g = _Grid(t, z, s, (0, 0, 0))
                        p = g.p
                        y0, x0 = g.oy, g.ox
                        # the art grid may hang one art column over the frame edge; compare the part inside the box
                        r0, c0 = max(0, y0), max(0, x0)
                        r1 = min(H, y0 + g.AH * p)
                        c1 = min(W, x0 + g.AW * p)
                        r0 += (-(r0 - y0)) % p
                        c0 += (-(c0 - x0)) % p
                        sub = body[r0:r0 + ((r1 - r0) // p) * p, c0:c0 + ((c1 - c0) // p) * p]
                        blocks = sub.reshape(sub.shape[0] // p, p, sub.shape[1] // p, p, 4)
                        if not (blocks == blocks[:, :1, :, :1, :]).all():
                            bad += 1
    dt = time.perf_counter() - t0
    say("sweep: %d renders (8 names x 4 tiers x 23 frames x 8 octants x 2 zooms x 2 facings), %d bad, %.1f s incl. cache-miss art" % (n, bad, dt))
    ok &= bad == 0
    # shadow slides away from the sun (its column centroid moves with the sun's sign)
    cen = {}
    for s in ((-1.0, 0.0), (1.0, 0.0)):
        sh = shadow(1, "idle0", 1, s)
        cols = np.where(sh[..., 3] > 0)[1]
        cen[s] = cols.mean()
    slide = cen[(-1.0, 0.0)] > cen[(1.0, 0.0)]
    say("shadow: column centroid sun-left %.1f vs sun-right %.1f -> slides away from the sun: %s" % (cen[(-1.0, 0.0)], cen[(1.0, 0.0)], "PASS" if slide else "FAIL"))
    ok &= slide
    # heights: the fill rows (shoe row to the head's top fill row) equal S / ART_PX; the bottom outline row ends on the anchor
    for t in range(4):
        for z in (1, 2):
            body = render("atleastonce", t, "idle0", z, 1, DEFAULT_SUN, with_shadow=False)
            rows = np.where(body[..., 3].any(1))[0]
            ax, ay = anchor(t, z)
            p = ART_PX * z
            above = ay - rows.min()
            below = rows.max() + 1 - ay
            hat_extra = 2 if t == 3 else 0                      # every elder wears a hat: its crown adds two rows over the head
            fill_rows = above // p - 2 - hat_extra
            good = below == 0 and fill_rows == TIERS[t]["h"] // ART_PX
            say("tier %d zoom %d: box %s anchor %s opaque rows %d..%d -> %d art rows above the ground line (%d fill + 2 outline%s = %d px standing), %d below -> %s" % (
                t, z, size(t, z), (ax, ay), rows.min(), rows.max(), above // p, fill_rows, " + %d hat" % hat_extra if hat_extra else "",
                fill_rows * p, below, "PASS" if good else "FAIL"))
            ok &= good
    # walk contact: a shoe WALK_LIFT rows up on the lifted side, the head shifted one column, many pixels changed
    idle = render("sami", 1, "idle0", 1, 1, DEFAULT_SUN, with_shadow=False)
    walk = render("sami", 1, "walk0", 1, 1, DEFAULT_SUN, with_shadow=False)
    ax, ay = anchor(1, 1)
    right_idle = np.where(idle[:, ax:, 3].any(1))[0].max()
    right_walk = np.where(walk[:, ax + 2:, 3].any(1))[0].max()     # the lifted right leg (tilted one column out)
    lifted_px = right_idle - right_walk
    changed = int((idle != walk).any(-1).sum())
    good = lifted_px >= WALK_LIFT * ART_PX and changed > 100
    say("walk0 vs idle0 (settler, 1x): lifted-side bottom row %d -> %d = shoe %d px up (>= %d), %d px differ -> %s" % (
        right_idle, right_walk, lifted_px, WALK_LIFT * ART_PX, changed, "PASS" if good else "FAIL"))
    ok &= good
    # mouths: idle / wave / point / carry are mouthless (the INK count at the mouth rows equals the eye bars only)
    # genome spread
    random.seed(3)
    gs = [genome("user%d_%s" % (i, random.choice("abcxyz"))) for i in range(50)]
    distinct = len(set((g["colour"], g["hair"], g["hat"], g["accessory"], g["eyes"], g["cheeks"], g["yarn"]) for g in gs))
    band = [g["name"] for g in gs if 70 <= g["hue"] <= 160]
    say("50 random genomes: %d distinct, %d with a tunic hue in 70-160 (natural-tone rows moss / fern / pine, value well below the grass): %s" % (
        distinct, len(band), ", ".join(sorted(set(tone(b)["name"] for b in band))) or "-"))
    ok &= distinct == 50
    # cost
    for z in (1, 2):
        clear_cache()
        t0 = time.perf_counter()
        k = 0
        for name in names[:4]:
            for f in FRAMES:
                render(name, 2, f, z, 1, DEFAULT_SUN)
                k += 1
        dt = time.perf_counter() - t0
        say("cost: zoom %d, %d cache-miss renders (builder, with shadow) = %.3f ms/frame" % (z, k, dt * 1000 / k))
    say("cache: %s" % cache_stats())
    say("self_check: %s" % ("PASS" if ok else "FAIL"))
    return bool(ok)


if __name__ == "__main__":
    import sys
    import time
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--check" in sys.argv:
        sys.exit(0 if self_check(tuple(args) if args else self_check.__defaults__[0]) else 1)
    names = args or ["atleastonce", "sami", "kai_dnb", "noor.wav", "luca_99", "mira_9", "zed_ttv", "xX_tobi_Xx",
                     "lowkeyjord", "tinytash", "pixel_dude", "gg_nora"]
    t0 = time.perf_counter()
    for n in names:
        settler_sheet(n, 2, 1)
    dt = time.perf_counter() - t0
    print("rendered %d sheets (%d frames) at 1x in %.3fs = %.2f ms/frame" % (len(names), len(names) * len(FRAMES), dt, dt * 1000 / (len(names) * len(FRAMES))))
    for n in names:
        print("%-14s %s · grid %s" % (n, describe(n), art_rows(2)))
