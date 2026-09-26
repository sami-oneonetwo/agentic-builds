"""render_gate.py - the OPENWORLD.md section 13 gate: six 1280x720 frames FROM the real modules + the art atlas, plus the
320x180 tiles, plus the per-frame timing of section 7.3 steps 2-4 (crop + modulation + sprite blit) on this Mac.

    source scripts/env.sh
    RUN_DIR=/tmp/lg-gate MODE=test KL_TEST_PIPS=3 PYTHONPATH=. $PYTHON docs/gate/render_gate.py [--no-bench]

Writes docs/gate/{dawn,noon,night}_{0,3}awake.png (+ _tile.png), night_3awake_hourmode.png (world_day="hour"),
map_4471.png (the terrain review PNG) and timings.json. Never touches a live run dir: refuses unless RUN_DIR is under
/tmp and MODE=test, and synthetic pips exist only through stream.world.test_pips_allowed().

Honesty in these frames: there are NO real chatters in a gate render. The only figures are test pips (origin "test",
names `test pip N`, allowed by KL_TEST_PIPS in test mode only) and the caption says so; every count is a len() over
them; the viewer count is `--`; no keeper heartbeat -> the beacon is dark; the hearth burns only in the 3-awake frames
(a test pip "lit" it). The land is nature: wind, clouds, sun, tide, wild Wood, boulders.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from stream import layout as L                                   # noqa: E402
from stream.world import bake, nature, terrain, test_pips_allowed  # noqa: E402
from stream.world.art import buildings, creatures, props          # noqa: E402

RUN_DIR = os.environ.get("RUN_DIR", "")
SEED = 4471
W, H = 1280, 720
WX, WY, WW, WH = L.region_box("world")                            # (0, 72, 1280, 440)
CELL = 4
VERSION = "v0.6.0-gate"
ACCENT = L.hex_rgb(L.PRESETS["kick"]["accent"])
CHIP = (11, 14, 20, 153)                                          # 60 % dark chip
TEXT, TEXT2 = L.hex_rgb(L.COLORS["text"]), L.hex_rgb(L.COLORS["text2"])
PANEL, HAIR, BG = L.hex_rgb(L.COLORS["panel"]), L.hex_rgb(L.COLORS["hairline"]), L.hex_rgb(L.COLORS["bg"])
HONESTY = "no camera, no mic, no fake viewers. every name on this land is a real person in chat. the wind is just the wind."
SCENARIOS = {
    "dawn": 6.67, "noon": 12.0, "night": 23.0,
}


def refuse(msg: str) -> None:
    print("REFUSED: " + msg, file=sys.stderr)
    sys.exit(2)


def hsh(*keys) -> float:
    h = hashlib.sha1(("|".join(str(k) for k in keys)).encode()).digest()
    return int.from_bytes(h[:4], "little") / 4294967295.0


def now_at(hour: float, base: Optional[float] = None) -> float:
    """A unix time TODAY (local) at the given local hour, so nature's clock, season, moon and tide are real."""
    t = time.localtime(base or time.time())
    midnight = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, t.tm_wday, t.tm_yday, t.tm_isdst))
    return midnight + hour * 3600.0


# ----------------------------------------------------------------------------- test pips (the only figures)
def test_pips(n: int) -> List[Dict]:
    """n synthetic pips, honoured only via stream.world.test_pips_allowed (KL_TEST_PIPS, /tmp run dir, test mode)."""
    env = dict(os.environ)
    env["KL_TEST_PIPS"] = str(n)
    allowed = test_pips_allowed(RUN_DIR, None, env)
    if allowed <= 0:
        refuse("test pips not allowed here (RUN_DIR=%r MODE=%r); nothing to draw" % (RUN_DIR, os.environ.get("MODE")))
    pips = []
    for i in range(1, allowed + 1):
        key = "test-pip-%02d" % i
        r = hsh("tier", key)
        pips.append({"key": key, "display": "test pip %d" % i, "origin": "test",
                     "tier": 0 if r < 0.3 else (1 if r < 0.7 else (2 if r < 0.92 else 3)),
                     "colour": creatures.palette(key)["main"]})
    return pips


def place_camps(T: terrain.Terrain, pips: List[Dict]) -> List[Dict]:
    """Camps in the Steading ring (24-60 cells from the green), >= 12 cells apart, on passable land off the green."""
    sx, sy = T.site
    huts, taken = [], []
    for p in pips:
        placed = None
        for k in range(24):
            ang = 2 * math.pi * hsh("ang", p["key"], k)
            r = T.moot_r + 8 + 28 * hsh("rad", p["key"], k)
            x, y = int(sx + r * math.cos(ang)), int(sy + r * math.sin(ang) * 0.8)
            ok = all(T.passable[yy, xx] and T.biome[yy, xx] in (terrain.B_GRASS, terrain.B_MEADOW)
                     for yy in range(y, y + 6) for xx in range(x, x + 8)) if (0 <= x < T.w - 8 and 0 <= y < T.h - 6) else False
            if ok and all(math.hypot(x - tx, y - ty) >= 12 for tx, ty in taken) and math.hypot(x + 4 - sx, y + 3 - sy) > T.moot_r + 4:
                placed = (x, y)
                break
        if placed is None:
            placed = T.nearest_passable(sx + 40 + 14 * len(huts), sy + 30, 30)
        taken.append(placed)
        huts.append({"x": placed[0], "y": placed[1], "tier": 1, "owner": p["key"], "lit": False, "display": p["display"], "colour": p["colour"]})
    return huts


# ----------------------------------------------------------------------------- the scene (what steading.py will do)
class GateScene:
    def __init__(self, T: terrain.Terrain, N: nature.Nature, bk: bake.GroundBake, pips: List[Dict], huts: List[Dict], awake: int):
        self.T, self.N, self.bk = T, N, bk
        self.px = bk.px
        self.zoom = 1.0 if bk.px == 4 else 0.75
        self.pips = pips[:awake]
        self.huts = huts if awake else []
        self.awake = awake
        sx, sy = T.site
        self.marks = {"wear": None, "huts": self.huts, "fields": [], "flowers": []}
        self.caster = bake.casters_for_marks(T, self.marks)
        # the Moot: three waystones, the beacon post (dark: no keeper heartbeat), the hearth (lit only when a test pip lit it)
        self.waystones = [(sx - 26, sy + 6, "A"), (sx, sy + 12, "B"), (sx + 26, sy + 6, "C")]
        self.beacon = (sx - 6, sy - 14)
        self.hearth = (sx + 10, sy - 4)
        self.hearth_lit = awake > 0
        # the awake pips: one at the Moot, one walking toward the Ford, one sitting by its camp fire
        ford = T.places["ford"]
        self.actors = []
        for i, p in enumerate(self.pips):
            camp = self.huts[i]
            if i % 3 == 0:
                pos, frame, facing = (sx - 6, sy + 22), "speak0", 1
            elif i % 3 == 1:
                bank = T.places["river"]                                   # `go river`: the Steading-side bank by the Ford
                pos, frame, facing = (bank["x"] - 3, bank["y"] + 2), "walk1", 1 if ford["x"] >= camp["x"] else -1
            else:
                pos, frame, facing = (camp["x"] + 11, camp["y"] + 8), "sit", 1
            self.actors.append({"pip": p, "x": float(pos[0]), "y": float(pos[1]), "frame": frame, "facing": facing})
        self.fires = [(h["x"] + 11, h["y"] + 4) for i, h in enumerate(self.huts) if i % 3 == 2]     # the sitter's fire
        self._spr_cache: Dict[Tuple, np.ndarray] = {}
        self.pills: Dict[str, Image.Image] = {}

    # -- camera (v0: DRIFT on the Moot at 0 awake, FOLLOW the mean at >= 1, both at this bake's zoom)
    def camera(self) -> Tuple[float, float]:
        T = self.T
        if not self.actors:
            cx, cy = float(T.site[0]), float(T.site[1])
        else:
            cx = sum(a["x"] for a in self.actors) / len(self.actors)
            cy = sum(a["y"] for a in self.actors) / len(self.actors)
            cx, cy = 0.35 * cx + 0.65 * T.site[0], 0.35 * cy + 0.65 * T.site[1]         # lead room toward the Moot
        vw, vh = WW / (self.px), WH / (self.px)
        cx = min(max(cx, vw / 2 + terrain.EDGE_MARGIN), T.w - vw / 2 - terrain.EDGE_MARGIN)
        cy = min(max(cy, vh / 2 + terrain.EDGE_MARGIN), T.h - vh / 2 - terrain.EDGE_MARGIN)
        return cx, cy

    def sprite(self, name: str, tier: int, frame: str, facing: int, sun) -> np.ndarray:
        spr = creatures.render(name, tier, frame, 1, facing, sun)
        if self.px == 4:
            return spr
        key = (name, tier, frame, facing, bake.sun_octant(sun))
        out = self._spr_cache.get(key)
        if out is None:
            im = Image.fromarray(spr).resize((max(1, spr.shape[1] * 3 // 4), max(1, spr.shape[0] * 3 // 4)), Image.Resampling.BOX)
            out = np.asarray(im)
            self._spr_cache[key] = out
        return out

    def warm(self, sun) -> None:
        """What a hatch does off the frame loop: pre-render the frames these pips will show."""
        for a in self.actors:
            for fr in (a["frame"], "idle0", "idle1", "walk0", "walk1", "walk2", "walk3"):
                self.sprite(a["pip"]["key"], a["pip"]["tier"], fr, a["facing"], sun)

    def compose(self, now: float, chat_rate: float = 0.0, timing: Optional[Dict[str, List[float]]] = None) -> Tuple[np.ndarray, Dict]:
        """Steps 2-6 of OPENWORLD 7.3 for one frame: crop, modulation, fixed-point multiply, glow, y-sorted sprites."""
        T, N, bk, px = self.T, self.N, self.bk, self.px
        t0 = time.perf_counter()
        N.update(now, chat_rate)
        cx, cy = self.camera()
        bx0, by0 = int(round(cx * px)) - WW // 2, int(round(cy * px)) - WH // 2
        cx0, cy0, cw, ch, ox, oy = bake.view_cells(bx0, by0, WW, WH, px)
        crop = bk.ground(cx0 * px, cy0 * px, cw * px, ch * px)
        t1 = time.perf_counter()
        field = N.modulation((cx0, cy0, cw, ch), now, caster=self.caster)
        t2 = time.perf_counter()
        rgb = bake.apply(crop, field, ox, oy, WW, WH, N.last_sparkle, px)
        t3 = time.perf_counter()
        sun = N.sun(now)
        hour = N.hour(now)
        dusk = nature.night_amount(hour) > 0.15
        fire_phase = int(now * 6) % 4

        def to_px(x: float, y: float) -> Tuple[int, int]:
            return int(round(x * px)) - bx0, int(round(y * px)) - by0

        # glow buffer after dusk (honest sources only: the lit hearth, the sitters' camp fires)
        if dusk:
            g = props.glow(int(70 * px / 4), (255, 170, 80), 0.55)
            if self.hearth_lit:
                hx, hy = to_px(*self.hearth)
                bake.blit_add(rgb, g, hx - g.shape[1] // 2, hy - 6 - g.shape[0] // 2)
            for (fx, fy) in self.fires:
                gx, gy = to_px(fx, fy)
                bake.blit_add(rgb, g, gx - g.shape[1] // 2, gy - 6 - g.shape[0] // 2)
        # live sprites, y-sorted by feet: waystones, beacon, hearth, camp fires, pips
        live: List[Tuple[float, str, tuple]] = []
        for (x, y, letter) in self.waystones:
            live.append((y, "waystone", (x, y, letter)))
        live.append((self.beacon[1], "beacon", self.beacon))
        live.append((self.hearth[1], "hearth", self.hearth))
        for f in self.fires:
            live.append((f[1], "fire", f))
        for a in self.actors:
            live.append((a["y"], "pip", a))
        live.sort(key=lambda o: o[0])
        for _, kind, data in live:
            if kind == "waystone":
                x, y, _ = data
                spr = props.waystone(ACCENT, 0, sun)
            elif kind == "beacon":
                x, y = data
                spr = props.beacon(0, False, (150, 150, 150), sun)
            elif kind == "hearth":
                x, y = data
                spr = props.campfire(fire_phase, self.hearth_lit, sun)
            elif kind == "fire":
                x, y = data
                spr = props.campfire(fire_phase, True, sun)
            else:
                a = data
                p = a["pip"]
                spr = self.sprite(p["key"], p["tier"], a["frame"], a["facing"], sun)
                ax, ay = creatures.anchor(p["tier"])
                sx_, sy_ = to_px(a["x"], a["y"])
                bake.blit(rgb, spr, sx_ - int(ax * px / 4), sy_ - int(ay * px / 4))
                continue
            if px != 4:
                spr = np.asarray(Image.fromarray(spr).resize((max(1, spr.shape[1] * 3 // 4), max(1, spr.shape[0] * 3 // 4)), Image.Resampling.BOX))
            gx, gy = to_px(x, y)
            bake.put(rgb, spr, gx, gy)
        t4 = time.perf_counter()
        if timing is not None:
            for k, v in (("crop", t1 - t0), ("field", t2 - t1), ("apply", t3 - t2), ("sprites", t4 - t3), ("total", t4 - t0)):
                timing.setdefault(k, []).append(v * 1000)
        cam = {"cx": cx, "cy": cy, "bx0": bx0, "by0": by0, "px": px, "zoom": self.zoom, "to_px": to_px}
        return rgb, cam


# ----------------------------------------------------------------------------- the text layer (layout.py geometry)
def chip_text(d: ImageDraw.ImageDraw, layer: Image.Image, xy: Tuple[int, int], text: str, face: str, size: int, fill,
              pad: int = 8, bg=CHIP, anchor_mid: bool = False) -> Tuple[int, int, int, int]:
    f = L.font(face, size)
    tw = L.text_width(face, size, text)
    x, y = xy
    if anchor_mid:
        x = x - tw // 2 - pad
    box = (x, y, x + tw + 2 * pad, y + size + 12)
    ImageDraw.Draw(layer, "RGBA").rounded_rectangle(box, 6, fill=bg)
    d.text((x + pad, y + 4), text, font=f, fill=fill)
    return box


def stroked(d: ImageDraw.ImageDraw, xy, text: str, face: str, size: int, fill, anchor="la") -> None:
    d.text(xy, text, font=L.font(face, size), fill=fill, stroke_width=2, stroke_fill=(11, 14, 20), anchor=anchor)


def time_dial(img: Image.Image, xy: Tuple[int, int], hour: float, moon_phase: float, night: float) -> None:
    """64x64: the sun or the real-phase moon on an arc over a ground stripe (no sky band on the land: the dial is where
    the sky is read)."""
    x, y = xy
    r = 32
    disc = Image.new("RGBA", (2 * r, 2 * r), (0, 0, 0, 0))
    dd = ImageDraw.Draw(disc)
    day_top, day_bot = np.array((120, 160, 220)), np.array((236, 200, 150))
    night_top, night_bot = np.array((34, 40, 78)), np.array((70, 76, 120))
    top = day_top * (1 - night) + night_top * night
    bot = day_bot * (1 - night) + night_bot * night
    for row in range(2 * r):
        t = row / (2 * r - 1)
        c = tuple(int(v) for v in (top * (1 - t) + bot * t))
        dd.line([(0, row), (2 * r, row)], fill=c + (255,))
    ground = tuple(int(v) for v in np.array((74, 100, 50)) * (1 - night) + np.array((40, 52, 60)) * night)
    dd.rectangle([0, r + 10, 2 * r, 2 * r], fill=ground + (255,))
    dd.line([(0, r + 10), (2 * r, r + 10)], fill=(30, 40, 30, 255), width=2)
    # the arc: east (right) at 06:00 to west (left) at 18:00 for the sun; the moon takes the night arc
    if night < 0.5:
        t = (hour - 6.0) / 12.0
        ang = math.pi * (1 - min(1.0, max(0.0, t)))
        px_, py_ = r + math.cos(ang) * (r - 12), r + 10 - math.sin(ang) * (r - 8)
        dd.ellipse([px_ - 7, py_ - 7, px_ + 7, py_ + 7], fill=(255, 226, 140, 255))
    else:
        t = ((hour - 18.0) % 24.0) / 12.0
        ang = math.pi * (1 - min(1.0, max(0.0, t)))
        px_, py_ = r + math.cos(ang) * (r - 12), r + 10 - math.sin(ang) * (r - 8)
        dd.ellipse([px_ - 7, py_ - 7, px_ + 7, py_ + 7], fill=(235, 235, 225, 255))
        # real phase: the dark part of the moon
        k = math.cos(2 * math.pi * moon_phase)
        if abs(k) > 0.05:
            off = 7 * k
            dd.ellipse([px_ - 7 + off, py_ - 7, px_ + 7 + off, py_ + 7], fill=(48, 54, 92, 255))
        for (sx, sy) in ((12, 10), (44, 16), (30, 6), (52, 30)):
            dd.point((sx, sy), fill=(255, 255, 255, 255))
    m = Image.new("L", (2 * r, 2 * r), 0)
    ImageDraw.Draw(m).ellipse([0, 0, 2 * r - 1, 2 * r - 1], fill=255)
    disc.putalpha(m)
    ImageDraw.Draw(img, "RGBA").rounded_rectangle([x - 4, y - 4, x + 2 * r + 4, y + 2 * r + 4], 8, fill=CHIP)
    img.paste(disc, (x, y), disc)


def minimap(img: Image.Image, T: terrain.Terrain, cam: Dict, walked_frac: float, awake_dots: List[Tuple[float, float, Tuple]],
            camps: List[Dict]) -> None:
    """(1120, 88) 148x104: the WHOLE map at 0.15 px/cell (144x66), walked land saturated / unwalked 55 %, the camera
    rectangle, one dot per awake pip in its colour, dim squares for camps, `N % walked` (a len() over cells)."""
    x0, y0 = 1120, 88
    rgb = T.biome_rgb().astype(np.float32)
    grey = rgb.mean(axis=2, keepdims=True)
    rgb = grey + (rgb - grey) * 0.55                                   # nothing walked yet in a gate render: 55 % everywhere
    mm = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).resize((144, 66), Image.Resampling.BOX).convert("RGBA")
    d = ImageDraw.Draw(mm)
    s = 144 / T.w
    for h in camps:
        d.rectangle([h["x"] * s - 1, h["y"] * s - 1, h["x"] * s + 1, h["y"] * s + 1], fill=tuple(h["colour"]) + (200,))
    for (px_, py_, col) in awake_dots:
        d.ellipse([px_ * s - 2, py_ * s - 2, px_ * s + 2, py_ * s + 2], fill=tuple(col) + (255,))
    vw, vh = WW / cam["px"], WH / cam["px"]
    d.rectangle([(cam["cx"] - vw / 2) * s, (cam["cy"] - vh / 2) * s, (cam["cx"] + vw / 2) * s, (cam["cy"] + vh / 2) * s],
                outline=TEXT + (230,), width=1)
    dd = ImageDraw.Draw(img, "RGBA")
    dd.rounded_rectangle([x0 - 4, y0 - 4, x0 + 148 + 4, y0 + 104 + 4], 6, fill=CHIP, outline=HAIR + (255,), width=1)
    img.paste(mm, (x0 + 2, y0 + 2), mm)
    dd.text((x0 + 74, y0 + 72), "%d %% walked" % int(round(walked_frac * 100)), font=L.font("Menlo", 20), fill=TEXT2, anchor="mt")


def header(img: Image.Image, awake: int, settled: int, countdown: str) -> None:
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 66], fill=BG)
    d.text((16, 8), "atleastonce", font=L.font("Menlo", 20), fill=TEXT2)
    d.text((16, 34), "LONGGRASS", font=L.font("HN Medium", 22), fill=TEXT)
    d.ellipse([L.text_width("HN Medium", 22, "LONGGRASS") + 24, 42, L.text_width("HN Medium", 22, "LONGGRASS") + 34, 52], fill=ACCENT)
    txt, size = ("NOBODY AWAKE", 40) if awake == 0 else ("%d AWAKE" % awake, 56)
    f = L.font("AB", size)
    bb = f.getbbox(txt)
    d.text((316, 33 - (bb[1] + bb[3]) // 2), txt, font=f, fill=TEXT)
    lx = 316 + bb[2] + 24
    d.text((lx, 7), "· %d SETTLED" % settled, font=L.font("Menlo", 24), fill=TEXT2)
    d.text((lx, 36), "NEXT EVENT %s" % countdown, font=L.font("Menlo", 24), fill=TEXT)
    ver = VERSION
    d.text((W - 16 - L.text_width("Menlo", 22, ver), 7), ver, font=L.font("Menlo", 22), fill=TEXT2)
    live = "LIVE · -- watching"
    lw = L.text_width("Menlo", 22, live)
    d.ellipse([W - 16 - lw - 22, 42, W - 16 - lw - 8, 56], fill=L.hex_rgb(L.COLORS["danger"]))
    d.text((W - 16 - lw, 36), live, font=L.font("Menlo", 22), fill=TEXT)
    d.rectangle([0, 66, W, 72], fill=HAIR)
    d.rectangle([0, 66, int(W * 0.46), 72], fill=ACCENT)


def strips(img: Image.Image, awake: int, camps: List[Dict], actors: List[Dict], season_name: str, ms: float,
           hour_mode: bool, chat_lines: List[Tuple[str, Tuple, str]]) -> None:
    d = ImageDraw.Draw(img)
    for key in ("colony", "keeper", "chat_log", "ticker", "scope", "readout"):
        x, y, w, h = L.region_box(key)
        d.rectangle([x, y, x + w - 1, y + h - 1], fill=PANEL, outline=HAIR)
    # the land (colony box): head-count bar, counts, a rotating line
    def line(x, y, w, yy, text, face, size, fill):
        d.text((x + 16, y + yy), L.truncate(face, size, text, w - 32), font=L.font(face, size), fill=fill)

    x, y, w, h = L.region_box("colony")
    walked = len(set(a["pip"]["key"] for a in actors))
    line(x, y, w, 10, "%d have walked here · %d more until the cairn is named" % (walked, max(0, 3 - walked)), "HN Medium", 22, TEXT)
    d.rectangle([x + 16, y + 42, x + w - 16, y + 50], fill=HAIR)
    d.rectangle([x + 16, y + 42, x + 16 + int((w - 32) * min(1.0, walked / 3.0)), y + 50], fill=ACCENT)
    line(x, y, w, 60, "%d awake · 0 asleep · %d camps · 0 fields · %s" % (awake, len(camps), season_name), "Menlo", 22, TEXT2)
    line(x, y, w, 96, "the wind was already blowing" if awake == 0 else "%s lit the hearth · night 1" % actors[0]["pip"]["display"], "Menlo", 20, TEXT2)
    # keeper (line 3 carries this render's provenance: text belongs in the frame, never on the land)
    x, y, w, h = L.region_box("keeper")
    line(x, y, w, 10, "no keeper on duty · notices kept for next time", "HN Medium", 22, TEXT2)
    line(x, y, w, 44, "beacon dark · last raised: nothing yet · %s" % VERSION, "Menlo", 22, TEXT2)
    line(x, y, w, 96, "gate render · test mode · figures are test pips", "Menlo", 20, L.hex_rgb(L.COLORS["warn"]))
    # chat log
    x, y, w, h = L.region_box("chat_log")
    if not chat_lines:
        d.text((x + 16, y + 12), "chat is quiet. say anything.", font=L.font("Menlo", 22), fill=TEXT2)
    for i, (name, col, text) in enumerate(chat_lines[:5]):
        d.text((x + 16, y + 10 + 26 * i), name, font=L.font("Menlo", 22), fill=col)
        d.text((x + 16 + L.text_width("Menlo", 22, name) + 12, y + 10 + 26 * i), L.truncate("Menlo", 22, text, w - 44 - L.text_width("Menlo", 22, name)), font=L.font("Menlo", 22), fill=TEXT)
    # ticker: the honesty line (+ the hour-mode disclosure)
    x, y, w, h = L.region_box("ticker")
    tick = HONESTY + ("  ·  a day here is one hour" if hour_mode else "")
    d.text((x + 16, y + 18), L.truncate("HN Medium", 24, tick, w - 32), font=L.font("HN Medium", 24), fill=TEXT)
    # scope: silence (no audio in a still render)
    x, y, w, h = L.region_box("scope")
    d.line([(x + 8, y + h // 2), (x + w - 8, y + h // 2)], fill=ACCENT, width=2)
    # readout
    x, y, w, h = L.region_box("readout")
    d.text((x + 12, y + 8), L.truncate("Menlo", 20, "chat 0.0/min · 0 chatters", w - 24), font=L.font("Menlo", 20), fill=TEXT2)
    d.text((x + 12, y + 34), L.truncate("Menlo", 20, "30 fps · %.1f ms · test" % ms, w - 24), font=L.font("Menlo", 20), fill=TEXT2)


def frame(scene: GateScene, now: float, label: str, hour_mode: bool = False) -> Tuple[Image.Image, Dict]:
    T, N = scene.T, scene.N
    rgb, cam = scene.compose(now, chat_rate=0.0)
    ms_total = None
    img = Image.new("RGB", (W, H), BG)
    img.paste(Image.fromarray(rgb), (WX, WY))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    info = N.describe(now)
    hour = info["hour"]
    to_px = cam["to_px"]

    def world_xy(x: float, y: float) -> Tuple[int, int]:
        px_, py_ = to_px(x, y)
        return WX + px_, WY + py_

    # camp plates and pip labels: one placer pushes a chip up when it would overlap an earlier one (hud.place_pills)
    chips: List[Tuple[int, int, str, str, int, Tuple]] = []           # (cx, top, text, face, size, fill)
    for h in scene.huts:
        cxp, cyp = world_xy(h["x"] + 4, h["y"] + 6)
        if 0 <= cxp < W and WY <= cyp < WY + WH:
            chips.append((cxp, cyp + 4, "%s's tent · night 1" % h["display"], "HN Medium", 22, TEXT))
    for a in scene.actors:
        p = a["pip"]
        hx, hy = world_xy(a["x"], a["y"])
        top = hy - creatures.height(p["tier"]) * (0.75 if a["frame"] == "sit" else 1.25) - 34
        chips.append((hx, int(top), "@%s" % p["display"], "Menlo", 20, tuple(p["colour"])))
    placed: List[Tuple[int, int, int, int]] = [(0, WY, 660, WY + 150), (1110, WY, W, WY + 210)]   # plank, land line, dial, minimap
    for (x, y, letter) in scene.waystones:                            # the letters are obstacles for the chips
        lx, ly = world_xy(x, y)
        placed.append((lx - 22, ly - 78, lx + 22, ly - 30))
    for (cx_, top, text, face, size, fill) in sorted(chips, key=lambda c: c[1], reverse=True):
        tw = L.text_width(face, size, text) + 16
        x0, x1 = cx_ - tw // 2, cx_ + tw // 2
        hgt = size + 12
        moved = 0
        for _ in range(8):
            if any(x0 < bx1 and x1 > bx0 and top < by1 and top + hgt > by0 for (bx0, by0, bx1, by1) in placed):
                top += (hgt + 4) if moved >= 3 else -(hgt + 4)         # up first; after three pushes, try below instead
                moved += 1
            else:
                break
        top = max(WY + 4, min(top, WY + WH - hgt - 4))
        x0 = max(4, min(x0, W - tw - 4))
        chip_text(d, layer, (x0, top), text, face, size, fill)
        placed.append((x0, top, x0 + tw, top + hgt))
    # the three waystones carry their letters (AB 44 here; the rounds panel owns the 56 px letters + counts)
    for (x, y, letter) in scene.waystones:
        lx, ly = world_xy(x, y)
        stroked(d, (lx, ly - 34), letter, "AB", 44, TEXT, anchor="ms")
    stroked(d, (16, WY + WH - 16 - 22), "the Moot", "HN Medium", 22, TEXT)
    # plank, land line, time dial
    if scene.awake == 0:
        plank = "surveying the steading · nobody has walked here yet"
    else:
        plank = "%s walked into Longgrass · %s" % (scene.actors[-1]["pip"]["display"], info["clock"])
    chip_text(d, layer, (16, WY + 12), plank, "HN Medium", 22, TEXT)
    land = "%d settled here · %s · day 1 · %s" % (len(scene.huts), ("nobody awake" if scene.awake == 0 else "%d awake" % scene.awake), info["day_part"])
    chip_text(d, layer, (16, WY + 44), land, "Menlo", 22, TEXT2)
    img.paste(layer, (0, 0), layer)
    time_dial(img, (16, WY + 80), hour, info["moon_phase"], info["night"])
    d2 = ImageDraw.Draw(img, "RGBA")
    layer2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d3 = ImageDraw.Draw(layer2)
    clock = "%s · %s" % (info["world_clock"] if hour_mode else info["clock"], info["day_part"])
    chip_text(d3, layer2, (92, WY + 80), clock + ("   1 h = 1 day" if hour_mode else ""), "Menlo", 22, TEXT)
    chip_text(d3, layer2, (92, WY + 114), "%s · %s · %s" % (info["wind"], info["season"], info["moon"]), "Menlo", 22, TEXT2)
    img.paste(layer2, (0, 0), layer2)
    minimap(img, T, cam, 0.0, [(a["x"], a["y"], a["pip"]["colour"]) for a in scene.actors], scene.huts)
    header(img, scene.awake, len(scene.huts), "01:23")
    chat = [] if scene.awake == 0 else [("@%s" % a["pip"]["display"], tuple(a["pip"]["colour"]), t) for a, t in
                                         zip(scene.actors, ("fire", "go river", "sit"))]
    strips(img, scene.awake, scene.huts, scene.actors, info["season"], 0.0, hour_mode, chat)
    return img, info


# ----------------------------------------------------------------------------- QA measures on the tile
def tile_measures(tile: Image.Image) -> Dict:
    a = np.asarray(tile.convert("RGB"), np.float32) / 255.0
    band = a[18:128]                                                   # the world band (OPENWORLD 4.5)
    lum = 0.2126 * band[..., 0] + 0.7152 * band[..., 1] + 0.0722 * band[..., 2]
    return {"world_mean_lum": round(float(lum.mean()), 3), "frac_above_0.12": round(float((lum > 0.12).mean()), 3)}


# ----------------------------------------------------------------------------- benchmark
def bench(T: terrain.Terrain, bakes: Dict[int, bake.GroundBake], n_pips: int, zoom: float, frames: int = 300, hour: float = 18.1) -> Dict:
    """Steps 2-4 with n synthetic pips walking, the camera drifting at 4 cells/s, wind from a 3 msg/min chat rate."""
    env = dict(os.environ)
    env["KL_TEST_PIPS"] = str(n_pips)
    n = test_pips_allowed(RUN_DIR, None, env)
    if n <= 0:
        refuse("bench: test pips not allowed")
    px = 4 if zoom == 1.0 else 3
    bk = bakes[px]
    N = nature.Nature(T, SEED)
    pips = []
    for i in range(1, n + 1):
        key = "test-pip-%02d" % i
        r = hsh("tier", key)
        pips.append({"key": key, "display": "test pip %d" % i, "origin": "test", "tier": 0 if r < 0.3 else (1 if r < 0.7 else (2 if r < 0.92 else 3)),
                     "colour": creatures.palette(key)["main"]})
    scene = GateScene(T, N, bk, pips, [], 0)
    sx, sy = T.site
    scene.actors = []
    for i, p in enumerate(pips):
        for k in range(40):
            x = sx + (hsh("bx", p["key"], k) - 0.5) * (300 if zoom == 1.0 else 400)
            y = sy + (hsh("by", p["key"], k) - 0.5) * (100 if zoom == 1.0 else 130)
            if T.is_passable(x, y):
                break
        scene.actors.append({"pip": p, "x": float(x), "y": float(y), "frame": "walk0", "facing": 1 if i % 2 else -1, "phase": i % 4})
    scene.huts = []
    t_warm = time.perf_counter()
    now0 = now_at(hour)
    N.update(now0, 3.0)
    scene.warm(N.sun(now0))
    warm_ms = (time.perf_counter() - t_warm) * 1000
    timing: Dict[str, List[float]] = {}
    fa = ("walk0", "walk1", "walk2", "walk3")
    t_all = time.perf_counter()
    for f in range(frames):
        now = now0 + f / 30.0
        for a in scene.actors:
            if f % 4 == 0:
                a["phase"] = (a["phase"] + 1) % 4
                a["frame"] = fa[a["phase"]]
            a["x"] += 0.27 * a["facing"]
            if not T.is_passable(a["x"], a["y"]):
                a["facing"] *= -1
        scene.compose(now, chat_rate=3.0, timing=timing)
    wall = (time.perf_counter() - t_all) * 1000 / frames
    out = {"zoom": zoom, "pips": n, "frames": frames, "px_per_cell": px, "warm_ms": round(warm_ms), "wall_ms_per_frame": round(wall, 2)}
    for k, v in timing.items():
        arr = np.array(v[10:])
        out[k] = {"mean": round(float(arr.mean()), 2), "p95": round(float(np.percentile(arr, 95)), 2), "max": round(float(arr.max()), 2)}
    return out


# ----------------------------------------------------------------------------- main
def main() -> None:
    rp = os.path.realpath(RUN_DIR or "")
    if not (rp.startswith("/tmp/") or rp.startswith("/private/tmp/")):
        refuse("RUN_DIR must be under /tmp (got %r)" % RUN_DIR)
    if os.environ.get("MODE") != "test":
        refuse("MODE=test required")
    do_bench = "--no-bench" not in sys.argv
    os.makedirs(RUN_DIR, exist_ok=True)
    t0 = time.perf_counter()
    T = terrain.generate(SEED)
    print("terrain: %.0f ms · %s" % ((time.perf_counter() - t0) * 1000, T.summary()["notes"][-1]))
    T.save_png(os.path.join(HERE, "map_%d.png" % SEED), 2)
    season_now = nature.season(time.time())
    sidx = nature.season_index(season_now)
    print("season now: %s (%.2f), hemisphere %s" % (nature.season_name(season_now), season_now, nature.hemisphere_default()))

    pips = test_pips(3)
    huts = place_camps(T, pips)
    print("test pips: %s" % ", ".join("%s(t%d)" % (p["display"], p["tier"]) for p in pips))
    print("camps: %s" % ", ".join("(%d,%d)" % (h["x"], h["y"]) for h in huts))
    marks = {"wear": None, "huts": huts, "fields": [], "flowers": []}

    results: Dict = {"seed": SEED, "site": T.site, "moot_r": T.moot_r, "season": nature.season_name(season_now), "frames": {}, "bench": []}
    bakes_by_hour: Dict[Tuple[int, int], bake.GroundBake] = {}

    def get_bake(hour: float, px: int, with_marks: bool) -> bake.GroundBake:
        sun = nature.sun_vector(hour)
        key = (bake.sun_octant(sun), px, with_marks)
        b = bakes_by_hour.get(key)
        if b is None:
            tb = time.perf_counter()
            b = bake.GroundBake(RUN_DIR, T, sidx, sun, bake_ver=1 if with_marks else 0, marks=marks if with_marks else {}, log=print, px_per_cell=px)
            b.start(background=True)
            # the frame path never waits on a bake: show the fallback until it lands (timed here for the record)
            fallback_frames = 0
            while b.baking:
                b.ground(T.site[0] * px - 640, T.site[1] * px - 220, WW, WH)
                fallback_frames += 1
                time.sleep(0.005)
            b.wait()
            print("bake %s: %.0f ms wall, %d fallback reads meanwhile" % (os.path.basename(b.path), (time.perf_counter() - tb) * 1000, fallback_frames))
            bakes_by_hour[key] = b
        return b

    for name, hour in SCENARIOS.items():
        for awake in (0, 3):
            bk = get_bake(hour, 4, awake > 0)
            N = nature.Nature(T, SEED, world_day="real")
            scene = GateScene(T, N, bk, pips, huts, awake)
            now = now_at(hour)
            N.update(now, 0.0)
            tw = time.perf_counter()
            scene.warm(N.sun(now))
            warm_ms = (time.perf_counter() - tw) * 1000
            # settle the wind / clouds for a few seconds of world time so bands and shadows are mid-flight
            for k in range(30):
                N.update(now - 3.0 + k * 0.1, 0.0)
            img, info = frame(scene, now, name)
            fn = "%s_%dawake" % (name, awake)
            img.save(os.path.join(HERE, fn + ".png"))
            tile = img.resize((320, 180), Image.Resampling.LANCZOS)
            tile.save(os.path.join(HERE, fn + "_tile.png"))
            tm = tile_measures(tile)
            results["frames"][fn] = {"hour": hour, "awake": awake, "clock": info["clock"], "day_part": info["day_part"], "tint": info["tint"],
                                     "tint_lum": round(nature.luminance(info["tint"]), 3), "wind": info["wind"], "moon": info["moon"],
                                     "sheet_warm_ms": round(warm_ms), "tile": tm}
            print("wrote %s.png (+tile) · %s %s · tint %s lum %.3f · tile world mean lum %.3f, >0.12: %.0f%%" % (
                fn, info["clock"], info["day_part"], info["tint"], nature.luminance(info["tint"]), tm["world_mean_lum"], 100 * tm["frac_above_0.12"]))
    # the disclosed lever: world_day="hour" at 23:20 real -> a world morning (at :00 it is world midnight; :12-:48 is day)
    hour = 23.0 + 20 / 60.0
    Nh = nature.Nature(T, SEED, world_day="hour")
    now = now_at(hour)
    wh = Nh.hour(now)
    bk = get_bake(wh, 4, True)
    scene = GateScene(T, Nh, bk, pips, huts, 3)
    Nh.update(now, 0.0)
    scene.warm(Nh.sun(now))
    for k in range(30):
        Nh.update(now - 3.0 + k * 0.1, 0.0)
    img, info = frame(scene, now, "night_hour", hour_mode=True)
    img.save(os.path.join(HERE, "night_3awake_hourmode.png"))
    img.resize((320, 180), Image.Resampling.LANCZOS).save(os.path.join(HERE, "night_3awake_hourmode_tile.png"))
    results["frames"]["night_3awake_hourmode"] = {"real_clock": info["clock"], "world_clock": info["world_clock"], "day_part": info["day_part"], "tint": info["tint"]}
    print("wrote night_3awake_hourmode.png · real %s -> world %s (%s)" % (info["clock"], info["world_clock"], info["day_part"]))
    # noon-tile vs midnight-tile QA (OPENWORLD 7.5 gate 1)
    noon = results["frames"]["noon_0awake"]["tile"]["world_mean_lum"]
    mid = results["frames"]["night_0awake"]["tile"]["world_mean_lum"]
    results["qa_tile"] = {"night_over_noon": round(mid / max(1e-6, noon), 3), "pass_ratio": mid >= 0.5 * noon,
                          "pass_frac": results["frames"]["night_0awake"]["tile"]["frac_above_0.12"] >= 0.60}
    print("tile gate: 23:00 mean / noon mean = %.2f (>= 0.5: %s); midnight >0.12 frac pass: %s" % (
        results["qa_tile"]["night_over_noon"], results["qa_tile"]["pass_ratio"], results["qa_tile"]["pass_frac"]))

    if do_bench:
        bakes = {4: get_bake(18.1, 4, True), 3: get_bake(18.1, 3, True)}
        for zoom, n in ((1.0, 20), (1.0, 60), (0.75, 20), (0.75, 60)):
            r = bench(T, bakes, n, zoom)
            results["bench"].append(r)
            print("bench zoom %.2f · %d pips · %d frames: total mean %.2f p95 %.2f max %.2f ms  (crop %.2f · field %.2f · apply %.2f · sprites %.2f) · warm-up %d ms" % (
                zoom, r["pips"], r["frames"], r["total"]["mean"], r["total"]["p95"], r["total"]["max"], r["crop"]["mean"], r["field"]["mean"],
                r["apply"]["mean"], r["sprites"]["mean"], r["warm_ms"]))
        # the resample alternative for 0.75x (crop 1707x587 from the 4 px bake, BOX to 1280x440), steps 2-4 only
        bk4 = bakes[4]
        N = nature.Nature(T, SEED)
        now = now_at(18.1)
        N.update(now, 3.0)
        ts = []
        for i in range(120):
            bx0, by0 = T.site[0] * 4 - 853, T.site[1] * 4 - 293
            cx0, cy0, cw, ch, ox, oy = bake.view_cells(bx0, by0, 1707, 587, 4)
            t1 = time.perf_counter()
            crop = bk4.crop(cx0 * 4, cy0 * 4, cw * 4, ch * 4)
            field = N.modulation((cx0, cy0, cw, ch), now + i / 30.0)
            out = bake.apply(crop, field, ox, oy, 1707, 587, N.last_sparkle, 4)
            out = bake.resample(out, (1280, 440))
            ts.append((time.perf_counter() - t1) * 1000)
        arr = np.array(ts[10:])
        results["bench_alt_075_resample"] = {"mean": round(float(arr.mean()), 2), "p95": round(float(np.percentile(arr, 95)), 2), "max": round(float(arr.max()), 2)}
        print("alt 0.75x path (4 px bake crop 1707x587 -> apply -> BOX): mean %.2f p95 %.2f ms (no sprites)" % (arr.mean(), np.percentile(arr, 95)))
    else:
        try:                                                           # keep the last measured numbers with the new frames
            old = json.load(open(os.path.join(HERE, "timings.json")))
            results["bench"] = old.get("bench", [])
            results["bench_alt_075_resample"] = old.get("bench_alt_075_resample")
        except Exception:
            pass
    results["bakes"] = {os.path.basename(b.path): b.stats() for b in bakes_by_hour.values()}
    with open(os.path.join(HERE, "timings.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)
    print("wrote timings.json")


if __name__ == "__main__":
    main()
