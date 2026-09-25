"""stream/scenes/canvas.py - the generative CANVAS scene (CONCEPT 4/5).

Two sims, both simulated at half resolution (stage body 840x236 -> 420x118) and upscaled 2x,
drawn as a single accent colour on black, deterministic from `state.micro.canvas_seed`:

  reaction_diffusion  Gray-Scott, the measured approach from stream/experiments/avtest/gen.py
                      (float32 U/V fields, np.roll Laplacian, 3 steps per frame). Rules
                      (state.micro.canvas_rule) pick the feed/kill pair: coral, mitosis, spots, worms,
                      waves (the rounds.py MENU set) plus maze and solitons. A small V blob is dropped
                      every 4 s from the seeded RNG so a settled rule (coral) never freezes.
  flow_field          (MENU spells it "flowfield") 20 000 particles advected by a periodic
                      incompressible curl field (4 seeded travelling sines: vx = d psi/dy, vy = -d psi/dx)
                      deposited into a decaying half-res buffer with np.bincount. Rules: swirl, stream,
                      orbit; an RD rule name under this scene falls back to swirl (the chip says so).

Public API (see stream/scenes/__init__.py):

    scene = CanvasScene()
    img = scene.frame(ctx, size, chip=True, chip_anchor="br", dim=1.0)   # RGBA, exactly `size`

`frame()` never raises: any internal error -> the last good frame (or a plain black + accent
fallback), one line on stderr, `scene.errors` counts them. Re-seeds when canvas_seed / canvas_scene /
canvas_rule / size changes. The chip reads `scene v0.3.13 · coral · seed @kai` where @kai is the real
picker of the last shipped canvas option in ships.jsonl (agent pick -> `seed agent`, nothing shipped
yet -> `seed 41370704`). Never time.time(): the sim advances by ctx.frame (capped 4 steps per call).
"""
from __future__ import annotations

import sys
import traceback
import zlib
from typing import Dict, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw

from stream import layout as L

DEFAULT_SEED = 41370704
DEFAULT_SCENE = "reaction_diffusion"
DEFAULT_RULE = "coral"
BLOB_EVERY_FRAMES = 120          # 4 s at 30 fps: one new V blob (never faster than 1 Hz)
MAX_STEPS_PER_CALL = 4           # catch-up cap when frames were skipped
WARMUP_STEPS = 150               # one-off at (re)seed so frame 0 already shows structure

# Gray-Scott feed / kill pairs (Pearson), with Du=0.16 Dv=0.08 on the 5-point roll Laplacian (gen.py)
RD_RULES: Dict[str, Tuple[float, float]] = {
    "coral":    (0.0545, 0.0620),
    "mitosis":  (0.0367, 0.0649),
    "worms":    (0.0780, 0.0610),
    "maze":     (0.0290, 0.0570),
    "solitons": (0.0300, 0.0620),
    "spots":    (0.0260, 0.0610),
    "waves":    (0.0180, 0.0510),
}
FLOW_SCENE_NAMES = ("flow_field", "flowfield", "flow")    # rounds.py MENU spells it "flowfield"
FLOW_RULES = ("swirl", "stream", "orbit")
N_PARTICLES = 20000


def _log(msg: str) -> None:
    try:
        sys.stderr.write("canvas: %s\n" % msg)
        sys.stderr.flush()
    except Exception:
        pass


def _lut(accent_hex: str) -> np.ndarray:
    """256-entry RGBA ramp black -> accent (gamma 1.6 so the field reads as glow, not fog)."""
    r, g, b = L.hex_rgb(accent_hex)
    t = (np.arange(256, dtype=np.float32) / 255.0) ** 1.6
    lut = np.empty((256, 4), np.uint8)
    lut[:, 0] = (t * r).astype(np.uint8)
    lut[:, 1] = (t * g).astype(np.uint8)
    lut[:, 2] = (t * b).astype(np.uint8)
    lut[:, 3] = 255
    return lut


# ----------------------------------------------------------------------------- sims
class GrayScott(object):
    """U/V float32 fields at (h, w); step() = one Euler step; field8() = V as uint8 0..255."""

    def __init__(self, w: int, h: int, seed: int, rule: str):
        self.w, self.h = int(w), int(h)
        self.rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
        self.f, self.k = RD_RULES.get(rule, RD_RULES[DEFAULT_RULE])
        self.U = np.ones((self.h, self.w), np.float32)
        self.V = np.zeros((self.h, self.w), np.float32)
        for _ in range(int(self.rng.integers(14, 22))):
            self.blob()
        self.steps = 0

    def blob(self) -> None:
        r = int(self.rng.integers(3, 8))
        cy = int(self.rng.integers(r, self.h - r))
        cx = int(self.rng.integers(r, self.w - r))
        self.V[cy - r:cy + r, cx - r:cx + r] = 0.5
        self.U[cy - r:cy + r, cx - r:cx + r] = 0.5

    def step(self, n: int = 1) -> None:
        U, V, f, k = self.U, self.V, self.f, self.k
        for _ in range(n):
            lu = np.roll(U, 1, 0) + np.roll(U, -1, 0) + np.roll(U, 1, 1) + np.roll(U, -1, 1) - 4.0 * U
            lv = np.roll(V, 1, 0) + np.roll(V, -1, 0) + np.roll(V, 1, 1) + np.roll(V, -1, 1) - 4.0 * V
            uvv = U * V * V
            U += 0.16 * lu - uvv + f * (1.0 - U)
            V += 0.08 * lv + uvv - (f + k) * V
        self.steps += n
        np.clip(U, 0.0, 1.0, out=U)
        np.clip(V, 0.0, 1.0, out=V)

    def field8(self) -> np.ndarray:
        return (np.minimum(self.V * 3.2, 1.0) * 255.0).astype(np.uint8)


class FlowField(object):
    """20k particles in a seeded incompressible curl field, deposited into a decaying buffer.

    psi(x, y, t) = sum_i a_i sin(kx_i x + ky_i y + phi_i + omega_i t), with kx_i = 2 pi n_i / w and
    ky_i = 2 pi m_i / h (integers) so the field is periodic and the wrap seam is invisible.
    vx = d psi / d y, vy = -d psi / d x, scaled to ~0.8 px per step; 0.5 % of the particles respawn
    every step so the streaks keep refreshing. Rules: swirl (cells), orbit (tight cells), stream
    (long trails + a uniform drift)."""

    PARAMS = {  # rule -> (wavelength range px, buffer decay, deposit gain, drift px/step)
        "swirl":  ((60.0, 130.0), 0.92, 0.07, 0.0),
        "orbit":  ((35.0, 75.0), 0.92, 0.07, 0.0),
        "stream": ((90.0, 236.0), 0.965, 0.03, 0.6),
    }

    def __init__(self, w: int, h: int, seed: int, rule: str):
        self.w, self.h = int(w), int(h)
        self.rng = np.random.default_rng((int(seed) * 7919 + 13) & 0xFFFFFFFF)
        self.rule = rule if rule in FLOW_RULES else FLOW_RULES[0]
        wl, self.decay, self.gain_dep, self.drift = self.PARAMS[self.rule]
        n = N_PARTICLES
        self.px = self.rng.random(n, dtype=np.float32) * self.w
        self.py = self.rng.random(n, dtype=np.float32) * self.h
        self.buf = np.zeros((self.h, self.w), np.float32)
        terms = 4
        kmag = 2 * np.pi / self.rng.uniform(wl[0], wl[1], terms)
        ang = self.rng.uniform(0, 2 * np.pi, terms)
        if self.rule == "stream":
            ang = self.rng.uniform(-0.3, 0.3, terms) + np.pi / 2        # k along y -> flow along x
        nx = np.rint(kmag * np.cos(ang) * self.w / (2 * np.pi))
        ny = np.rint(kmag * np.sin(ang) * self.h / (2 * np.pi))
        ny[(nx == 0) & (ny == 0)] = 1.0
        self.kx = (2 * np.pi * nx / self.w).astype(np.float32)
        self.ky = (2 * np.pi * ny / self.h).astype(np.float32)
        self.ph = self.rng.uniform(0, 2 * np.pi, terms).astype(np.float32)
        self.om = self.rng.uniform(-0.012, 0.012, terms).astype(np.float32)
        self.amp = self.rng.uniform(0.6, 1.0, terms).astype(np.float32)
        kk = np.sqrt(self.kx ** 2 + self.ky ** 2)
        self.gain = np.float32(0.8 / max(1e-6, float((self.amp * kk).sum())))
        self.t = 0
        self.steps = 0

    def step(self, n: int = 1) -> None:
        w, h = self.w, self.h
        for _ in range(n):
            vx = np.full_like(self.px, self.drift / max(self.gain, 1e-6))
            vy = np.zeros_like(self.py)
            for i in range(len(self.kx)):
                c = np.cos(self.kx[i] * self.px + self.ky[i] * self.py + self.ph[i] + self.om[i] * self.t)
                vx += (self.amp[i] * self.ky[i]) * c
                vy -= (self.amp[i] * self.kx[i]) * c
            self.px += vx * self.gain
            self.py += vy * self.gain
            np.mod(self.px, w, out=self.px)
            np.mod(self.py, h, out=self.py)
            k = len(self.px) // 200
            idx = self.rng.integers(0, len(self.px), k)
            self.px[idx] = self.rng.random(k, dtype=np.float32) * w
            self.py[idx] = self.rng.random(k, dtype=np.float32) * h
            flat = self.py.astype(np.int32) * w + self.px.astype(np.int32)
            dep = np.bincount(flat, minlength=w * h)[: w * h].astype(np.float32).reshape(h, w)
            self.buf *= self.decay
            self.buf += dep * self.gain_dep
            self.t += 1
        self.steps += n

    def field8(self) -> np.ndarray:
        return (np.minimum(self.buf, 1.0) * 255.0).astype(np.uint8)


# ----------------------------------------------------------------------------- scene
class CanvasScene(object):
    name = "canvas"

    def __init__(self, default_scene: Optional[str] = None):
        self.default_scene = default_scene or DEFAULT_SCENE
        self.sim = None
        self.sim_key = None            # (scene, rule, seed, w, h)
        self.start_frame = 0
        self.last_good: Optional[Image.Image] = None
        self.errors = 0
        self._lut_cache: Dict[str, np.ndarray] = {}
        self._chip_cache: Dict = {}    # (text, accent) -> RGBA chip image
        self.last_ms = 0.0
        self.steps_per_frame = 3

    # ---- inputs -----------------------------------------------------------------
    @staticmethod
    def params(ctx) -> Tuple[str, str, int]:
        micro = (ctx.micro if ctx is not None else None) or {}
        scene = str(micro.get("canvas_scene") or DEFAULT_SCENE).lower()
        if scene in FLOW_SCENE_NAMES:
            scene = "flow_field"
        rule = str(micro.get("canvas_rule") or DEFAULT_RULE).lower()
        raw = micro.get("canvas_seed")
        if raw is None or raw == "":
            seed = DEFAULT_SEED
        else:
            try:
                seed = int(raw)
            except (TypeError, ValueError):
                seed = zlib.crc32(str(raw).encode("utf-8"))    # any string seed is still deterministic
        return scene, rule, seed

    @staticmethod
    def seed_credit(ctx) -> str:
        """`@name` of the real picker of the last shipped canvas option, `agent` for an agent pick,
        else the seed number. Never a made-up name."""
        ships = (ctx.ships if ctx is not None else None) or []
        for s in reversed(list(ships)):
            oid = str(s.get("option_id") or "")
            if "canvas" in oid and s.get("ok", True):
                if s.get("agent_pick") or not s.get("picked_by"):
                    return "agent"
                return "@" + L.strip_non_bmp(str(s.get("picked_by")))
        _, _, seed = CanvasScene.params(ctx)
        return str(seed)

    def chip_text(self, ctx) -> str:
        scene, rule, _ = self.params(ctx)
        v = ((ctx.version if ctx is not None else None) or {}).get("string") or "v0.0.0"
        if scene == "flow_field":
            label = "flow field %s" % (rule if rule in FLOW_RULES else FLOW_RULES[0])   # the rule the sim really runs
        else:
            label = rule if rule in RD_RULES else DEFAULT_RULE
        return "scene %s · %s · seed %s" % (v, label, self.seed_credit(ctx))

    # ---- sim lifecycle --------------------------------------------------------------
    def _ensure_sim(self, ctx, sw: int, sh: int) -> None:
        scene, rule, seed = self.params(ctx)
        key = (scene, rule, seed, sw, sh)
        if key == self.sim_key and self.sim is not None:
            return
        if scene == "flow_field":
            sim = FlowField(sw, sh, seed, rule)
            sim.step(45)
        else:
            sim = GrayScott(sw, sh, seed, rule)
            sim.step(WARMUP_STEPS)
        self.sim, self.sim_key = sim, key
        self.start_frame = int(getattr(ctx, "frame", 0) or 0)
        self.target_steps = sim.steps

    def _advance(self, ctx) -> None:
        frame = int(getattr(ctx, "frame", 0) or 0)
        elapsed = max(0, frame - self.start_frame)
        want = elapsed * self.steps_per_frame - (self.sim.steps - self.target_steps)
        n = max(1, min(MAX_STEPS_PER_CALL, want))          # at least 1 step: something moves every call
        if isinstance(self.sim, GrayScott) and elapsed > 0 and elapsed % BLOB_EVERY_FRAMES == 0 and not getattr(self, "_blobbed_at", None) == elapsed:
            self._blobbed_at = elapsed
            self.sim.blob()
        self.sim.step(n)

    # ---- drawing ---------------------------------------------------------------------
    def _colourise(self, small: np.ndarray, size: Tuple[int, int], accent: str, dim: float) -> Image.Image:
        w, h = size
        lut = self._lut_cache.get(accent)
        if lut is None:
            lut = self._lut_cache[accent] = _lut(accent)
        if dim < 0.999:
            small = (small.astype(np.float32) * max(0.0, dim)).astype(np.uint8)
        big = Image.fromarray(small, "L").resize((w, h), Image.BILINEAR)   # 2x upscale, smooth
        rgba = lut[np.asarray(big)]                                          # (h, w, 4) uint8
        return Image.fromarray(np.ascontiguousarray(rgba), "RGBA")

    def _chip(self, text: str, accent: str) -> Image.Image:
        key = (text, accent)
        img = self._chip_cache.get(key)
        if img is not None:
            return img
        f = L.font("Menlo", 20)
        tw = L.text_width("Menlo", 20, text)
        cw, ch = tw + 20, 28
        img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, cw - 1, ch - 1], radius=4, fill=(17, 21, 29, 230), outline=L.COLORS["hairline"])
        d.text((10, 3), text, font=f, fill=accent)
        if len(self._chip_cache) > 16:
            self._chip_cache.clear()
        self._chip_cache[key] = img
        return img

    def _fallback(self, size: Tuple[int, int], accent: str) -> Image.Image:
        if self.last_good is not None and self.last_good.size == tuple(size):
            return self.last_good
        img = Image.new("RGBA", size, (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        w, h = size
        d.rectangle([L.PAD, L.PAD, w - L.PAD, h - L.PAD], outline=L.COLORS["hairline"])
        d.text((L.PAD * 2, L.PAD * 2), "canvas: scene error, sim paused", font=L.font("Menlo", 20), fill=accent)
        return img

    def frame(self, ctx, size, chip: bool = True, chip_anchor: str = "br", dim: float = 1.0) -> Image.Image:
        """RGBA image exactly `size`. Never raises."""
        w, h = int(size[0]), int(size[1])
        accent = L.COLORS["accent"]
        try:
            accent = L.preset(ctx.preset if ctx is not None else None)["accent"]
            sw, sh = max(8, w // 2), max(8, h // 2)
            self._ensure_sim(ctx, sw, sh)
            self._advance(ctx)
            img = self._colourise(self.sim.field8(), (w, h), accent, dim)
            if chip:
                text = L.truncate("Menlo", 20, self.chip_text(ctx), w - 2 * L.PAD - 20)
                c = self._chip(text, accent)
                x = L.PAD if chip_anchor.endswith("l") else w - L.PAD - c.size[0]
                y = L.PAD if chip_anchor.startswith("t") else h - L.PAD - c.size[1]
                img.alpha_composite(c, (max(0, x), max(0, y)))
            self.last_good = img
            return img
        except Exception:
            self.errors += 1
            if self.errors <= 3:
                _log("frame failed (%d): %s" % (self.errors, traceback.format_exc().strip().splitlines()[-1]))
            if self.errors % 60 == 0:
                self.sim, self.sim_key = None, None       # every 2 s: try a fresh sim
            return self._fallback((w, h), accent)
