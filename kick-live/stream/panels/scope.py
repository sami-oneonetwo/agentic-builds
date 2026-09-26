"""Scope (region 16, CONCEPT 3 row 16): a real oscilloscope of the audio block handed to ffmpeg THIS frame.

Live (ctx.audio_source == "fifo" and ctx.audio_block present): a 1 px accent polyline, 144 px wide (x 8..152),
of the block's left channel folded into 144 bins (~11 samples each, mean per bin, so nothing aliases).
A small ring buffer of the last RING_BLOCKS blocks (4 x 1600 = 133 ms) lives in the panel and drives a slow
automatic gain (the bed sits at about -24 dBFS, so raw samples would be a flat line); gain is clamped 1..16 x
and smoothed over ~10 frames, never jumps. `micro.scope_style == "bars"` swaps the polyline for an 8-segment
level meter (RMS of the current block, -60..-6 dBFS, top segment amber) with a peak-hold marker that decays
one segment per 6 frames.

Fallback (no FIFO, `--no-audio`, or no block): the compositor's own synth is NOT what the viewer hears
(run.sh's aevalsrc bed is), so nothing is drawn as if it were measured: an unlit 8-segment meter outline plus
the honest label `audio: fallback` / `no audio` (Menlo 20, grey). The readout region says the same.

Data: ctx.audio_block (np.int16 (1600, 2) or None), ctx.audio_source ("fifo"|"fallback"|"none"), ctx.audio_level,
ctx.micro.scope_style, ctx.preset, ctx.frame. Never reads a file, never calls time.time().
"""
from __future__ import annotations

import math

import numpy as np
from PIL import ImageDraw

from stream import layout as L
from stream.panels import Panel, register

RING_BLOCKS = 4
X0, WIDTH = 8, 144
SEGMENTS = 8
SEG_W, SEG_GAP = 16, 2                      # 8 * 16 + 7 * 2 = 142 px, inside the 144 px scope width
DB_FLOOR, DB_CEIL = -60.0, -6.0             # meter range; -6 dBFS is the master limiter ceiling
PEAK_HOLD_FRAMES = 6


class Scope(Panel):
    key, region = "scope", "scope"

    def __init__(self):
        self._ring = None                   # float32 (RING_BLOCKS * n,) left channel, oldest first
        self._ring_frame = None             # frame index of the last block folded into the ring
        self._gain = 6.0
        self._peak_seg = 0
        self._peak_age = 0

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _left(blk):
        """Left channel of the block as float32 in -1..1, or None."""
        if blk is None:
            return None
        try:
            a = np.asarray(blk)
            if a.ndim == 2:
                a = a[:, 0]
            if a.size == 0:
                return None
            if a.dtype.kind in "iu":
                return a.astype(np.float32) / 32768.0
            return np.clip(a.astype(np.float32), -1.0, 1.0)
        except Exception:
            return None

    @staticmethod
    def _live(ctx) -> bool:
        return ctx.audio_source == "fifo" and ctx.audio_block is not None

    @staticmethod
    def _style(ctx) -> str:
        """micro.scope_style from the round MENU: line (default) | bars | dots | mirror; anything else -> line."""
        st = (ctx.micro or {}).get("scope_style") if isinstance(ctx.micro, dict) else None
        return st if st in ("bars", "dots", "mirror") else "line"

    def _update_ring(self, ctx, left) -> None:
        """Fold this frame's block into the ring once per frame and ease the display gain toward 0.85 / peak."""
        frame = int(ctx.frame or 0)
        if self._ring_frame == frame:
            return
        self._ring_frame = frame
        n = left.shape[0]
        if self._ring is None or self._ring.shape[0] != RING_BLOCKS * n:
            self._ring = np.zeros(RING_BLOCKS * n, np.float32)
        self._ring[:-n] = self._ring[n:]
        self._ring[-n:] = left
        peak = float(np.max(np.abs(self._ring))) if self._ring.size else 0.0
        target = 0.85 / peak if peak > 1e-6 else 16.0
        target = max(1.0, min(16.0, target))
        self._gain += (target - self._gain) * 0.1

    @staticmethod
    def _dbfs(left) -> float:
        rms = float(np.sqrt(np.mean(np.square(left, dtype=np.float64)))) if left.size else 0.0
        return 20.0 * math.log10(rms) if rms > 1e-9 else -120.0

    # ------------------------------------------------------------------ drawing
    def _bins(self, left):
        """WIDTH values in -1..1: per-bin mean of the block (~11 samples per px), times the eased display gain."""
        n = left.shape[0]
        if n >= WIDTH:
            edges = np.linspace(0, n, WIDTH + 1).astype(int)
            sums = np.add.reduceat(left.astype(np.float64), edges[:-1])
            ys = sums / np.maximum(1, np.diff(edges))
        else:
            ys = np.interp(np.linspace(0, n - 1, WIDTH), np.arange(n), left)
        return np.clip(ys * self._gain, -1.0, 1.0)

    def _draw_line(self, d, left, h: int, accent: str, style: str = "line") -> None:
        mid = h // 2
        d.line([(X0, mid), (X0 + WIDTH - 1, mid)], fill=L.COLORS["hairline"], width=1)
        ys = self._bins(left)
        amp = float(h // 2 - 6)
        if style == "mirror":
            # symmetric envelope: |sample| drawn above and below the centre line, 1 px columns
            for i in range(WIDTH):
                e = int(round(abs(ys[i]) * amp))
                d.line([(X0 + i, mid - e), (X0 + i, mid + e)], fill=accent, width=1)
            return
        pts = [(X0 + i, int(round(mid - ys[i] * amp))) for i in range(WIDTH)]
        if style == "dots":
            d.point(pts, fill=accent)
            return
        d.line(pts, fill=accent, width=1)

    def _draw_meter(self, d, h: int, lit: int, accent: str, peak_seg: int = 0, tall: bool = True, label=None) -> None:
        top, bottom = (8, h - 8) if tall else (8, 30)
        for i in range(SEGMENTS):
            x = X0 + 1 + i * (SEG_W + SEG_GAP)
            box = [x, top, x + SEG_W - 1, bottom]
            if i < lit:
                col = L.COLORS["warn"] if i == SEGMENTS - 1 else accent
                d.rectangle(box, fill=col)
            else:
                d.rectangle(box, outline=L.COLORS["hairline"], width=1)
            if peak_seg and i == peak_seg - 1 and i >= lit:
                d.rectangle([x, top, x + SEG_W - 1, top + 2], fill=accent)
        if label:
            d.text((X0, 38), L.truncate("Menlo", 20, label, WIDTH), font=L.font("Menlo", 20), fill=L.COLORS["text2"])

    # ------------------------------------------------------------------ Panel API
    def inputs(self, ctx):
        if self._live(ctx):
            return (ctx.frame, ctx.preset, self._style(ctx))          # the block changes every frame
        return ("meter", ctx.audio_source, ctx.preset)

    def render(self, ctx, size):
        w, h = size
        img = self.base(size)
        d = ImageDraw.Draw(img)
        accent = L.preset(ctx.preset)["accent"]
        left = self._left(ctx.audio_block) if self._live(ctx) else None
        if left is None:
            label = "self-test" if (ctx.compositor_live or {}).get("selftest") else ("fallback bed" if ctx.audio_source == "fallback" else "no audio")   # <= 12 glyphs = 144 px
            self._draw_meter(d, h, 0, accent, tall=False, label=label)
            return img
        self._update_ring(ctx, left)
        if self._style(ctx) == "bars":
            db = ctx.audio_level if isinstance(ctx.audio_level, (int, float)) else self._dbfs(left)
            frac = (float(db) - DB_FLOOR) / (DB_CEIL - DB_FLOOR)
            lit = int(max(0, min(SEGMENTS, round(frac * SEGMENTS))))
            if lit >= self._peak_seg:
                self._peak_seg, self._peak_age = lit, 0
            else:
                self._peak_age += 1
                if self._peak_age >= PEAK_HOLD_FRAMES:
                    self._peak_seg, self._peak_age = max(lit, self._peak_seg - 1), 0
            self._draw_meter(d, h, lit, accent, peak_seg=self._peak_seg, tall=True)
        else:
            self._draw_line(d, left, h, accent, self._style(ctx))
        return img


# HUD pass (journal 028): this region left stream/layout.py; the module stays on disk (its copy and tests are
# reused by the land strip) but registers nothing. `Scope` would be dropped by register() anyway.
# register(Scope())
