"""Countdown bar (CONCEPT section 3, region 4): the full-width 1280x6 strip under the header.

The bar is anchored at x=0 and its right edge walks left as the round elapses (full at round open, empty at
the deadline). Accent colour from the current preset, amber under 30 s, red under 10 s. During the 5 s SHIP
phase the bar is full in accent (or red when the ship failed). When no round is open (no deadline in
state.json) a dim 160 px sweep crosses the strip every 8 s so the region still moves.

Re-renders only when the filled pixel width or the colour changes (~7 px/s in a 180 s round).
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from stream import layout as L
from stream.panels import Panel, register

WARN_S = 30.0
DANGER_S = 10.0
IDLE_SWEEP_W = 160
IDLE_SWEEP_PERIOD_S = 8.0


def _blend(hex_a: str, hex_b: str, t: float):
    a, b = L.hex_rgb(hex_a), L.hex_rgb(hex_b)
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


class Countdown(Panel):
    key, region = "countdown", "countdown"

    def _geom(self, ctx):
        """-> ("bar", px, colour) | ("idle", sweep_x, colour). Pure function of ctx; used as the cache key."""
        w = L.region_size(self.region)[0]
        accent = L.preset(ctx.preset)["accent"]
        rnd = ctx.round or {}
        phase = rnd.get("phase") or "open"
        rem, opened, deadline = ctx.round_remaining, ctx.round_opened_t, ctx.round_deadline_t
        if phase == "ship":
            res = rnd.get("last_result") or {}
            return ("bar", w, L.COLORS["danger"] if res.get("ok") is False else accent)
        if rem is None or opened is None or deadline is None or deadline <= opened:
            # idle: a dim sweep so the strip is never static
            per = IDLE_SWEEP_PERIOD_S
            x = int(((ctx.now % per) / per) * (w + IDLE_SWEEP_W)) - IDLE_SWEEP_W
            return ("idle", x, accent)
        frac = max(0.0, min(1.0, rem / float(deadline - opened)))
        col = accent
        if rem < DANGER_S:
            col = L.COLORS["danger"]
        elif rem < WARN_S:
            col = L.COLORS["warn"]
        return ("bar", int(round(w * frac)), col)

    def inputs(self, ctx):
        return self._geom(ctx)

    def render(self, ctx, size):
        w, h = size
        img = Image.new("RGBA", size, L.COLORS["hairline"])
        d = ImageDraw.Draw(img)
        kind, px, col = self._geom(ctx)
        if kind == "idle":
            # 160 px sweep with a soft ramp: dim accent at the tail, brighter at the head
            for i in range(0, IDLE_SWEEP_W, 8):
                x0 = px + i
                if x0 + 8 <= 0 or x0 >= w:
                    continue
                t = 0.15 + 0.45 * (i / float(IDLE_SWEEP_W))
                d.rectangle([max(0, x0), 0, min(w - 1, x0 + 7), h - 1], fill=_blend(L.COLORS["hairline"], col, t))
            return img
        if px > 0:
            d.rectangle([0, 0, px - 1, h - 1], fill=col)
            # 6 px brighter tip at the moving edge so the eye finds it
            tip = max(0, px - 6)
            d.rectangle([tip, 0, px - 1, h - 1], fill=_blend(col, "#FFFFFF", 0.35))
        return img


# HUD pass (journal 028): this region left stream/layout.py; the module stays on disk (its copy and tests are
# reused by the land strip) but registers nothing. `Countdown` would be dropped by register() anyway.
# register(Countdown())
