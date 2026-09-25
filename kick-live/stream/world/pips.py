"""stream/world/pips.py - pip sprite generator (WORLD.md 6.2, docs/art-rules.md).

Every pip is drawn from numpy stencils at startup; no asset files. Identity comes from the Kick username:

    colour_idx  = hash(name_lower) % 6                 -> the preset's 6-colour username set (L.PRESETS[..]["names"])
    genome      = sha1(name_lower + ":" + str(salt))   -> body 0-3, eyes 0-3, antenna 0-3, tail 0-2
    salt        starts at 0; `resolve_genome()` increments it (deterministically) until the reject-and-reseed
                check passes, and the caller STORES it (world.json), so the creature is identical every night.

Side view, low to the ground, angular: a wedge/slab/rhombus/ramp body with a 1 px darker outline (the
colour at 55 %), 2 one-pixel legs, a tail (stub / curl / fin), an antenna (none / single / twin / fan), a
2 px eye with a 1 px #E6E8EE highlight. No round bodies, no faces, no yellow default (art-rules.md).

Tiers (sim px, body box): 0 seedling 10x8 · 1 hatchling 12x10 · 2 pip 12x10 + longer antenna · 3 elder 14x12 + crest.
The sprite array is one row taller than the tier box (bob headroom): shape (h + 1, w).

Frames: idle0 idle1 walk0 walk1 blink speak curled asleep wave0 wave1 sit0 sit1 duck0 duck1 egg0 egg1 egg2.
The egg frames use no name colour at all (the seed is nameless until the hold clears).

    from stream.world import pips
    g, salt = pips.resolve_genome("sami")                       # deterministic; salt is stored in world.json
    rgb, mask = pips.sprite("sami", salt, tier=1, frame="idle0", preset="kick", facing=1)   # (H, W, 3) uint8, (H, W) bool
    pips.colour_idx("sami") ; pips.colour_hex("sami", "kick") ; pips.tier_box(tier) -> (w, h)
    pips.egg("egg1") -> (rgb, mask)                              # nameless seed, 6x7
    python stream/world/pips.py --sheet /tmp/x/pips_sheet.png [--names 48]

Cache: every (name_lower, salt, tier, preset, frame, facing) is kept as a small RGB array + mask; bounded at
2 000 entries (oldest evicted).
"""
from __future__ import annotations

import hashlib
import os
import sys
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stream import layout as L  # noqa: E402

TIER_BOX: Dict[int, Tuple[int, int]] = {0: (10, 8), 1: (12, 10), 2: (12, 10), 3: (14, 12)}
TIER_NAMES = ("seedling", "hatchling", "pip", "elder")
FRAMES = ("idle0", "idle1", "walk0", "walk1", "blink", "speak", "curled", "asleep",
          "wave0", "wave1", "sit0", "sit1", "duck0", "duck1", "egg0", "egg1", "egg2")
BODY_NAMES = ("wedge", "slab", "rhombus", "ramp")
TAIL_NAMES = ("stub", "curl", "fin")
ANTENNA_NAMES = ("none", "single", "twin", "fan")
EGG_W, EGG_H = 6, 7
OUTLINE_MUL = 0.55
FILL_MIN, FILL_MAX = 0.35, 0.70
CACHE_MAX = 2000
MAX_SALT_TRIES = 64

_EYE_HI = L.hex_rgb(L.COLORS["text"])          # #E6E8EE
_VOID = L.hex_rgb(L.COLORS["bg"])              # #0B0E14
_EGG_FILL = L.hex_rgb(L.COLORS["hairline"])    # #1C2130  (nameless: no name colour)
_EGG_EDGE = L.hex_rgb(L.COLORS["text2"])       # #8A90A0


# ----------------------------------------------------------------------------- identity
def name_hash(name_lower: str) -> int:
    """The same 31-multiplier hash stream.layout.name_color uses (so the pluck pitch and chat colour agree)."""
    s = 0
    for ch in (name_lower or ""):
        s = (s * 31 + ord(ch)) & 0xFFFFFFFF
    return s


def colour_idx(name_lower: str) -> int:
    return name_hash((name_lower or "").lower()) % 6


def colour_hex(name_lower: str, preset: Optional[str]) -> str:
    return L.preset(preset)["names"][colour_idx(name_lower)]


def genome(name_lower: str, salt: int = 0) -> Dict[str, int]:
    h = hashlib.sha1(("%s:%d" % ((name_lower or "").lower(), int(salt))).encode("utf-8")).digest()
    return {"salt": int(salt), "body": h[0] % 4, "eyes": h[1] % 4, "antenna": h[2] % 4, "tail": h[3] % 3,
            "motif": h[4] % 10}


def _lum(rgb) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _scale(rgb, k: float) -> Tuple[int, int, int]:
    return (int(min(255, max(0, rgb[0] * k))), int(min(255, max(0, rgb[1] * k))), int(min(255, max(0, rgb[2] * k))))


# ----------------------------------------------------------------------------- stencils
def body_mask(body: int, w: int, h: int) -> np.ndarray:
    """Boolean (h, w) body box for stencil `body`, facing right (the head is at the right edge).
    Angular row spans only (art-rules.md: wedge / slab / rhombus / ramp, never a disc)."""
    m = np.zeros((h, w), dtype=bool)
    n = h
    for i in range(n):
        f = i / max(1, n - 1)                 # 0 at the top row, 1 at the bottom row
        if body == 0:      # wedge: low at the back, rising to a head at the front
            x0 = int(round((1.0 - f) * w * 0.75))
            x1 = w
        elif body == 1:    # slab: a chamfered low block with a raised 3 px head block at the front
            if f < 0.4:
                if i == 0:
                    x0, x1 = w, w             # empty top row (antenna room)
                else:
                    x0, x1 = w - 4, w - 1
            else:
                x0 = 2 if i == n - 1 else 1
                x1 = w - (1 if i == n - 1 else 0)
        elif body == 2:    # rhombus: widest in the middle, pointed front and back
            mid = (n - 1) / 2.0
            d = abs(i - mid)
            x0 = int(round(d * 1.4))
            x1 = w - int(round(d * 1.0))
        else:              # ramp: tall at the back, sloping down to a low nose at the front
            x0 = 0
            x1 = int(round(w * (0.25 + 0.75 * f)))
        if x0 >= w:
            continue
        x0 = max(0, min(w - 1, x0))
        x1 = max(x0 + 1, min(w, x1))
        m[i, x0:x1] = True
    return m


def _outline(mask: np.ndarray) -> np.ndarray:
    """1 px inner boundary of a boolean mask (pixels with a non-mask 4-neighbour)."""
    p = np.pad(mask, 1, mode="constant", constant_values=False)
    inner = p[1:-1, 1:-1] & p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
    return mask & ~inner


def _eye_pos(g: Dict[str, int], bm: np.ndarray) -> Tuple[int, int]:
    """(row, col) of the eye's FRONT pixel inside the body mask (facing right), relative to the body's own
    front edge on that row, so every stencil (including the low-nosed ramp) carries its eye on its head.
    Placements: 0 high and forward, 1 a row lower and further back, 2 mid-height forward, 3 high and back."""
    bh, bw = bm.shape
    rows = np.where(bm.any(axis=1))[0]
    top = int(rows[0]) if len(rows) else 0
    e = g["eyes"]
    if e == 0:
        r, back = top + 1, 1
    elif e == 1:
        r, back = top + 2, 2
    elif e == 2:
        r, back = (top + bh) // 2, 1
    else:
        r, back = top + 1, 3
    r = min(bh - 1, max(0, r))
    cols = np.where(bm[r])[0]
    front = int(cols[-1]) if len(cols) else bw - 1
    return (r, front - back)


# ----------------------------------------------------------------------------- assembly
def _assemble(g: Dict[str, int], tier: int, frame: str, colour: Tuple[int, int, int]) -> Tuple[np.ndarray, np.ndarray]:
    """Build one frame facing right. Returns (rgb (H, W, 3) uint8, mask (H, W) bool), H = tier h + 1."""
    w, h = TIER_BOX.get(int(tier), TIER_BOX[1])
    H = h + 1
    rgb = np.zeros((H, w, 3), dtype=np.uint8)
    mask = np.zeros((H, w), dtype=bool)
    fill = colour
    line = _scale(colour, OUTLINE_MUL)

    ant_rows = 2 if tier >= 2 else 1              # antenna headroom (tier 2+: longer antenna)
    tail_w = 2
    bw = w - tail_w                               # body columns tail_w .. w-1
    bh = h - 1 - ant_rows                         # body rows: below the antenna, above the leg row
    bob = 1 if frame in ("idle1", "walk1", "wave1") else 0
    top = 1 + ant_rows - bob                      # body top row in the sprite (row 0 is bob headroom)
    legs_row = H - 1
    eyes_closed = frame in ("blink", "curled", "asleep")

    if frame == "asleep":                         # flat: bottom half of the body, no antenna, legs tucked
        bm = body_mask(g["body"], bw, bh)
        keep = max(3, bh // 2)
        bm = bm[bh - keep:, :]
        top = H - 1 - keep
        _paint_body(rgb, mask, bm, top, tail_w, fill, line)
        _paint_tail(rgb, mask, g["tail"], top, keep, tail_w, fill, line, curled=True)
        return rgb, mask
    if frame == "curled":                         # compressed: 0.7 height, tail tucked over the back, eye shut
        bm = body_mask(g["body"], bw, bh)
        keep = max(3, int(round(bh * 0.7)))
        bm = bm[bh - keep:, :]
        top = H - 2 - keep
        _paint_body(rgb, mask, bm, top, tail_w, fill, line)
        _paint_tail(rgb, mask, g["tail"], top, keep, tail_w, fill, line, curled=True)
        _paint_legs(rgb, mask, legs_row, tail_w, bw, line, frame="sit0")
        return rgb, mask

    if frame.startswith("sit") or frame.startswith("duck"):
        top += 1                                  # lowered by one row; legs hidden (sit) or spread (duck)
        bh = max(3, bh - 1)
    bm = body_mask(g["body"], bw, bh)
    _paint_body(rgb, mask, bm, top, tail_w, fill, line)
    _paint_tail(rgb, mask, g["tail"], top, bh, tail_w, fill, line, curled=False)
    if not frame.startswith("duck"):
        _paint_antenna(rgb, mask, g["antenna"], top, tail_w, bw, ant_rows, fill, line, frame)
    if tier >= 3:
        _paint_crest(rgb, mask, top, tail_w, bw, line)
    if not frame.startswith("sit"):
        _paint_legs(rgb, mask, legs_row, tail_w, bw, line, frame)
    # eye: 2 px dark (outline colour) with a 1 px highlight on the front pixel; closed = body colour
    er, ec = _eye_pos(g, bm)
    r, c = top + er, tail_w + ec
    if 0 <= r < H and 1 <= c < w and bm[er, ec] and bm[er, ec - 1]:
        if eyes_closed:
            rgb[r, c - 1:c + 1] = line
        else:
            rgb[r, c - 1] = line
            rgb[r, c] = _EYE_HI
        mask[r, c - 1:c + 1] = True
    if frame == "speak":                          # mouth notch: one void pixel at the front, below the eye
        mr, mc = min(H - 2, top + bh - 2), w - 1
        if mask[mr, mc]:
            mask[mr, mc] = False
            rgb[mr, mc] = 0
    if frame.startswith("wave"):                  # a raised front limb, alternating 2 rows
        lift = 2 if frame == "wave0" else 3
        r = top + bh - lift
        c = w - 1
        if 0 <= r < H:
            rgb[r, c] = fill
            mask[r, c] = True
            rgb[r - 1, c] = line
            mask[r - 1, c] = True
    return rgb, mask


def _paint_body(rgb, mask, bm, top, x0, fill, line) -> None:
    H, w = mask.shape
    bh, bw = bm.shape
    r1 = min(H, top + bh)
    if top < 0 or r1 <= top:
        return
    sub = bm[: r1 - top]
    ol = _outline(sub)
    region_m = mask[top:r1, x0:x0 + bw]
    region_c = rgb[top:r1, x0:x0 + bw]
    region_c[sub] = fill
    region_c[ol] = line
    region_m[sub] = True


def _paint_tail(rgb, mask, tail, top, bh, tail_w, fill, line, curled) -> None:
    H = mask.shape[0]
    mid = top + bh // 2
    if curled:                                    # hooked over the back
        pts = [(mid, 1), (mid - 1, 1), (mid - 1, 0)]
    elif tail == 0:                               # stub
        pts = [(mid, 1)]
    elif tail == 1:                               # curl
        pts = [(mid, 1), (mid - 1, 0)]
    else:                                         # fin: vertical 3 px at the back
        pts = [(mid - 1, 0), (mid, 0), (mid + 1, 0), (mid, 1)]
    for i, (r, c) in enumerate(pts):
        if 0 <= r < H and 0 <= c < tail_w:
            rgb[r, c] = line if i % 2 else fill
            mask[r, c] = True


def _paint_antenna(rgb, mask, kind, top, x0, bw, rows, fill, line, frame) -> None:
    if kind == 0:
        return
    head = x0 + bw - 3
    for k in range(rows):
        r = top - 1 - k
        if r < 0:
            break
        if kind == 1:
            cols = [head]
        elif kind == 2:
            cols = [head - 2, head]
        else:
            cols = [head - 2, head - 1, head] if k == 0 else [head - 1]
        for c in cols:
            if 0 <= c < mask.shape[1]:
                rgb[r, c] = fill if k == rows - 1 else line
                mask[r, c] = True


def _paint_crest(rgb, mask, top, x0, bw, line) -> None:
    """Elder crest: a 3 px zigzag on the back half of the body top."""
    r = top - 1
    if r < 0:
        return
    for i, c in enumerate(range(x0 + 1, x0 + 1 + min(5, bw // 2))):
        rr = r if i % 2 == 0 else r + 0
        if i % 2 == 0 and 0 <= c < mask.shape[1] and not mask[rr, c]:
            rgb[rr, c] = line
            mask[rr, c] = True


def _paint_legs(rgb, mask, row, x0, bw, line, frame) -> None:
    if frame.startswith("sit"):
        return
    back, front = x0 + 1, x0 + bw - 2
    if frame == "walk0":
        back, front = back + 1, front - 1
    elif frame == "walk1":
        back, front = back - 1, front + 1
    elif frame.startswith("duck"):
        back, front = back - 1, front + 1
    for c in (back, front):
        if 0 <= c < mask.shape[1]:
            rgb[row, c] = line
            mask[row, c] = True


# ----------------------------------------------------------------------------- reject and reseed
def check_genome(g: Dict[str, int], tier: int = 1, preset: Optional[str] = None, name_lower: str = "") -> Optional[str]:
    """None when the genome passes; else the reason. Fill 35-70 % of the stencil box, outline contrast against
    the void, eye inside the body."""
    w, h = TIER_BOX.get(int(tier), TIER_BOX[1])
    ant_rows = 2 if tier >= 2 else 1
    bw, bh = w - 2, h - 1 - ant_rows
    bm = body_mask(g["body"], bw, bh)
    fill = float(bm.sum()) / float(bw * bh)
    if fill < FILL_MIN or fill > FILL_MAX:
        return "fill %.2f outside %.2f-%.2f" % (fill, FILL_MIN, FILL_MAX)
    colour = L.hex_rgb(colour_hex(name_lower, preset))
    if _lum(_scale(colour, OUTLINE_MUL)) - _lum(_VOID) < 24.0:
        return "outline has no contrast against the void"
    er, ec = _eye_pos(g, bm)
    if not (0 <= er < bh and 1 <= ec < bw and bm[er, ec] and bm[er, ec - 1]):
        return "eye outside the body"
    return None


def resolve_genome(name_lower: str, start_salt: int = 0, preset: Optional[str] = None) -> Tuple[Dict[str, int], int]:
    """Deterministic reject-and-reseed: the first salt >= start_salt whose genome passes check_genome()."""
    key = (name_lower or "").lower()
    salt = int(start_salt)
    for _ in range(MAX_SALT_TRIES):
        g = genome(key, salt)
        if check_genome(g, 1, preset, key) is None:
            return g, salt
        salt += 1
    return genome(key, salt), salt


# ----------------------------------------------------------------------------- cache + public sprite()
_CACHE: "OrderedDict[Tuple, Tuple[np.ndarray, np.ndarray]]" = OrderedDict()
_STATS = {"hits": 0, "misses": 0}


def cache_size() -> int:
    return len(_CACHE)


def sprite(name_lower: str, salt: int, tier: int, frame: str, preset: Optional[str] = None,
           facing: int = 1) -> Tuple[np.ndarray, np.ndarray]:
    """Cached (rgb (H, W, 3) uint8, mask (H, W) bool) for one frame. `facing` 1 = right, -1 = left (mirrored).
    Egg frames come from egg() and carry no name colour."""
    if frame.startswith("egg"):
        return egg(frame)
    key = ((name_lower or "").lower(), int(salt), int(tier), preset or L.DEFAULT_PRESET, frame, 1 if facing >= 0 else -1)
    hit = _CACHE.get(key)
    if hit is not None:
        _STATS["hits"] += 1
        _CACHE.move_to_end(key)
        return hit
    _STATS["misses"] += 1
    if frame not in FRAMES:
        frame = "idle0"
    g = genome(key[0], key[1])
    colour = L.hex_rgb(colour_hex(key[0], key[3]))
    rgb, mask = _assemble(g, key[2], frame, colour)
    if key[5] < 0:
        rgb, mask = rgb[:, ::-1].copy(), mask[:, ::-1].copy()
    _CACHE[key] = (rgb, mask)
    while len(_CACHE) > CACHE_MAX:
        _CACHE.popitem(last=False)
    return rgb, mask


def tier_box(tier: int) -> Tuple[int, int]:
    return TIER_BOX.get(int(tier), TIER_BOX[1])


_EGG_CACHE: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}


def egg(frame: str = "egg0") -> Tuple[np.ndarray, np.ndarray]:
    """The nameless seed: an angular 6x7 shell in panel greys (no name colour), cracking over 3 frames."""
    hit = _EGG_CACHE.get(frame)
    if hit is not None:
        return hit
    w, h = EGG_W, EGG_H
    m = np.zeros((h, w), dtype=bool)
    spans = [(2, 4), (1, 5), (0, 6), (0, 6), (0, 6), (1, 5), (2, 4)]   # hexagonal, not round
    for r, (a, b) in enumerate(spans):
        m[r, a:b] = True
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    rgb[m] = _EGG_FILL
    rgb[_outline(m)] = _EGG_EDGE
    n = {"egg0": 1, "egg1": 3, "egg2": 6}.get(frame, 1)
    cracks = [(1, 3), (2, 2), (3, 3), (3, 4), (4, 2), (5, 3)]
    for (r, c) in cracks[:n]:
        rgb[r, c] = _VOID
    _EGG_CACHE[frame] = (rgb, m)
    return rgb, m


# ----------------------------------------------------------------------------- review sheet
def sheet(path: str, names: Optional[List[str]] = None, preset: Optional[str] = None, scale: int = 4) -> str:
    """Write a review sheet: one row per name (genome + salt shown as the row's first cell colour), one column
    per frame, every tier. Used by --self-test and by hand before the world goes live (art-rules.md)."""
    from PIL import Image, ImageDraw
    if not names:
        names = ["sample-%02d" % i for i in range(48)]
    frames = ("idle0", "idle1", "walk0", "walk1", "blink", "speak", "curled", "asleep", "wave0", "sit0", "duck0")
    tiers = (0, 1, 2, 3)
    cw, ch = 16 * scale, 14 * scale
    cols = len(frames) * len(tiers) + 3
    W, Hh = cw * cols, ch * (len(names) + 1) + 2 * scale
    img = Image.new("RGB", (W, Hh), L.COLORS["bg"])
    d = ImageDraw.Draw(img)
    f = L.font("Menlo", 20)
    for c, (fr, tr) in enumerate([(fr, tr) for tr in tiers for fr in frames]):
        d.text((cw * (c + 3) + 2, 2), "%s%d" % (fr[:3], tr), font=f, fill=L.COLORS["text2"])
    for r, nm in enumerate(names):
        key = nm.lower()
        g, salt = resolve_genome(key, 0, preset)
        y = ch * (r + 1) + 2 * scale
        d.text((2, y + 2), "%s s%d b%d e%d a%d t%d" % (nm[:10], salt, g["body"], g["eyes"], g["antenna"], g["tail"]),
               font=f, fill=colour_hex(key, preset))
        c = 3
        for tr in tiers:
            for fr in frames:
                rgb, mask = sprite(key, salt, tr, fr, preset, 1)
                tile = np.zeros((ch // scale, cw // scale, 3), dtype=np.uint8)
                tile[:] = L.hex_rgb(L.COLORS["bg"])
                hh, ww = mask.shape
                oy, ox = tile.shape[0] - hh - 1, 1
                sub = tile[oy:oy + hh, ox:ox + ww]
                sub[mask] = rgb[mask]
                big = np.repeat(np.repeat(tile, scale, 0), scale, 1)
                img.paste(Image.fromarray(big, "RGB"), (cw * c, y))
                c += 1
        eg, em = egg("egg2")
        tile = np.zeros((ch // scale, cw // scale, 3), dtype=np.uint8)
        tile[:] = L.hex_rgb(L.COLORS["bg"])
        sub = tile[tile.shape[0] - EGG_H - 1: tile.shape[0] - 1, 1:1 + EGG_W]
        sub[em] = eg[em]
        img.paste(Image.fromarray(np.repeat(np.repeat(tile, scale, 0), scale, 1), "RGB"), (cw * 2, y))
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    img.save(path)
    return path


def _main(argv: List[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="pip sprite generator")
    ap.add_argument("--sheet", metavar="PNG", help="write the review sheet here")
    ap.add_argument("--names", type=int, default=48)
    ap.add_argument("--preset", default=None)
    ap.add_argument("--check", action="store_true", help="print the reject-and-reseed table for the sample names")
    a = ap.parse_args(argv)
    names = ["sample-%02d" % i for i in range(a.names)]
    if a.check:
        rej = 0
        for nm in names:
            g0 = genome(nm, 0)
            why = check_genome(g0, 1, a.preset, nm)
            g, salt = resolve_genome(nm, 0, a.preset)
            if salt:
                rej += 1
            print("%-10s salt=%d body=%s eyes=%d antenna=%s tail=%s %s" % (
                nm, salt, BODY_NAMES[g["body"]], g["eyes"], ANTENNA_NAMES[g["antenna"]], TAIL_NAMES[g["tail"]],
                ("(salt 0 rejected: %s)" % why) if why else ""))
        print("reseeded %d/%d" % (rej, len(names)))
    if a.sheet:
        print(sheet(a.sheet, names, a.preset))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
