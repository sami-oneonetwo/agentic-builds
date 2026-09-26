"""Footer readout (CONCEPT section 3, region 17; OPENWORLD.md 8 row 11): 240x64, two Menlo 20 lines, once per second.

  line 1  `chat 0.4/m · 2 ppl`     Pusher listener figures from chat_stats.json (5 min window); `--` when absent.
          When something is wrong the line rotates every 5 s between the chat figures and each flag:
          `state: stale 14s` (state.json heartbeat > 10 s), `audio: fallback` (run.sh aevalsrc bed carries audio),
          `audio: none`, `chat: reconnecting` (listener disconnected or chat_stats.json older than 60 s),
          `dropped 3 frames`, and the world's degrade ladder (OPENWORLD 7.4): `world: clouds off`, `world: glow off`,
          `world: shadows off`, `world: zoom pinned` (the cave's ladder only has `world: glow off`), plus the honesty
          monitor's line when it reports a violation. Flags are amber. `baking spring…` rides in the same rotation
          (secondary, not amber: a bake in the background is the design, not a fault) while a ground bake thread runs.
  line 2  `30fps 11ms 1:23:45`     the compositor's own counters (fps_actual, frame_ms_avg, uptime); fps turns
          amber when it is 1.5+ under target after the first 10 s, ms turns amber over 20 ms.

240 px at Menlo 20 (12 px/glyph) holds 18 glyphs with an 8 px gutter each side, so every line is built to
<= 18 chars and truncated as a last resort.

The world facts come through `stream.panels.world`: `world_degrade()` (the scene's `degrade` dict), `honesty_line()`
and `scene().bakes` (the scene's BakeManager, for the season being baked). Nothing here reads the clock: `ctx.now` only.
"""
from __future__ import annotations

import sys
from typing import List, Optional, Tuple

from PIL import ImageDraw

from stream import layout as L
from stream.panels import Panel, register
from stream.state_store import iso_to_epoch

PAD = 8
ROTATE_S = 5.0
CHAT_STATS_FRESH_S = 60.0
MAX_CHARS = 18
# degrade key -> flag text (each <= 18 glyphs); the order is the ladder's order (OPENWORLD 7.4)
DEGRADE_FLAGS = (("clouds", False, "world: clouds off"), ("glow", False, "world: glow off"),
                 ("shadows", False, "world: shadows off"), ("zoom_pinned", True, "world: zoom pinned"))
SEASON_NAMES = ("spring", "summer", "autumn", "winter")


def _hms(s) -> str:
    s = max(0, int(s or 0))
    if s >= 3600:
        return "%d:%02d:%02d" % (s // 3600, (s // 60) % 60, s % 60)
    return "%02d:%02d" % (s // 60, s % 60)


def _fit(txt: str) -> str:
    return txt if len(txt) <= MAX_CHARS else txt[:MAX_CHARS - 1] + "…"


def _baking_season(wm) -> Optional[str]:
    """The season name of the ground bake running in the background, or None: read from the scene's BakeManager
    (`scene().bakes`: `.baking`, then the `pending` or `current` bake's `season_idx`)."""
    try:
        sc = wm.scene() if hasattr(wm, "scene") else None
        bm = getattr(sc, "bakes", None) if (sc is not None and getattr(sc, "booted", False)) else None
        if bm is None or not getattr(bm, "baking", False):
            return None
        b = getattr(bm, "pending", None)
        if b is None or not getattr(b, "baking", False):
            b = getattr(bm, "current", None)
        idx = int(getattr(b, "season_idx", 0) or 0) if b is not None else 0
        return SEASON_NAMES[idx % 4]
    except Exception:
        return None


class Readout(Panel):
    key, region = "readout", "readout"

    @staticmethod
    def _chat_line(ctx):
        cs = ctx.chat_stats or {}
        rate = cs.get("msgs_per_min_5m")
        n = cs.get("unique_chatters_5m")
        try:
            rf = None if rate is None else float(rate)
        except Exception:
            rf = None
        try:
            ppl = "--" if n is None else "%d" % int(n)
        except Exception:
            ppl = "--"
        # progressively shorter forms until the line fits 18 glyphs: 0.4 -> 12 -> drop "ppl"
        cands = []
        if rf is None:
            cands.append("chat --/m · %s ppl" % ppl)
        else:
            cands.append("chat %.1f/m · %s ppl" % (rf, ppl))
            cands.append("chat %d/m · %s ppl" % (int(round(rf)), ppl))
            cands.append("chat %d/m · %s" % (int(round(rf)), ppl))
        for c in cands:
            if len(c) <= MAX_CHARS:
                return c
        return _fit(cands[-1])

    @staticmethod
    def world_flags() -> Tuple[List[str], Optional[str]]:
        """(degrade flags, baking season) from the live world panel module; ([], None) before boot."""
        wm = sys.modules.get("stream.panels.world")
        if wm is None:
            return [], None
        out: List[str] = []
        try:
            dg = wm.world_degrade() if hasattr(wm, "world_degrade") else None
            if dg:
                level = int(dg.get("level") or 0)
                for key, bad, text in DEGRADE_FLAGS:
                    if key in dg and bool(dg.get(key)) == bad:
                        if key == "zoom_pinned" and level <= 0:
                            continue            # pinned by design (v0 preview `allow_zoom=False`), not by the ladder: no flag
                        out.append(text)
            hl = wm.honesty_line() if hasattr(wm, "honesty_line") else None
            if hl and "violation" in hl:
                out.append(_fit(hl))
        except Exception:
            pass
        return out, _baking_season(wm)

    @classmethod
    def _flags(cls, ctx) -> List[Tuple[str, str]]:
        """[(text, colour)] -- every flag amber except the informational `baking <season>…`."""
        out: List[Tuple[str, str]] = []
        warn, info = L.COLORS["warn"], L.COLORS["text2"]
        if ctx.stale:
            age = (ctx.now - ctx.updated_t) if ctx.updated_t else None
            out.append(("state: stale" if age is None else _fit("state: stale %ds" % int(age)), warn))
        cl0 = ctx.compositor_live or {}
        selftest = bool(cl0.get("selftest"))
        if not selftest and ctx.audio_source == "fallback":
            out.append(("audio: fallback", warn))          # run.sh aevalsrc bed carries the audio (18-char line limit)
        elif not selftest and ctx.audio_source == "none":
            out.append(("audio: none", warn))
        cs = ctx.chat_stats or {}
        if cs:
            t = iso_to_epoch(cs.get("ts"))
            fresh = t is not None and (ctx.now - t) < CHAT_STATS_FRESH_S
            if not cs.get("connected") or not fresh:
                out.append(("chat: reconnecting", warn))
        elif not selftest:
            out.append(("chat: reconnecting", warn))       # no chat_stats.json yet: the listener is not up; plain words, no jargon
        cl = ctx.compositor_live or {}
        dropped = int(cl.get("dropped_frames") or 0)
        if dropped:
            out.append((_fit("dropped %d frame%s" % (dropped, "" if dropped == 1 else "s")), warn))
        flags, baking = cls.world_flags()
        out += [(f, warn) for f in flags]
        if baking:
            out.append((_fit("baking %s…" % baking), info))
        return out

    def _lines(self, ctx):
        """-> ((text, colour), (segments...)) — the exact pixels; also the cache key (changes about once a second)."""
        slots = [(self._chat_line(ctx), L.COLORS["text2"])] + self._flags(ctx)
        idx = int((ctx.now or 0) // ROTATE_S) % len(slots)
        l1 = slots[idx]
        cl = ctx.compositor_live or {}
        target = float(cl.get("fps_target") or ctx.fps or 30)
        fps = float(cl.get("fps_actual") or 0.0)
        ms = float(cl.get("frame_ms_avg") or 0.0)
        up = int(cl.get("uptime_s") or 0)
        fps_col = L.COLORS["text2"]
        if up >= 10 and fps > 0 and fps < target - 1.5:
            fps_col = L.COLORS["warn"]
        ms_col = L.COLORS["warn"] if ms > 20.0 else L.COLORS["text2"]
        if cl.get("selftest"):                      # frames render faster than realtime here; label it so a screenshot is not misread
            l2 = (("self-test", L.COLORS["warn"]), (" %dms" % int(round(ms)), ms_col), (" " + _hms(up), L.COLORS["text2"]))
        else:
            l2 = (("%dfps" % int(round(fps)), fps_col), (" %dms" % int(round(ms)), ms_col), (" " + _hms(up), L.COLORS["text2"]))
        return l1, l2

    def inputs(self, ctx):
        return self._lines(ctx)

    def render(self, ctx, size):
        w, h = size
        img = self.base(size)
        d = ImageDraw.Draw(img)
        f = L.font("Menlo", 20)
        (t1, c1), l2 = self._lines(ctx)
        d.text((PAD, 8), L.truncate("Menlo", 20, t1, w - 2 * PAD), font=f, fill=c1)
        x = PAD
        for t, col in l2:
            d.text((x, 34), t, font=f, fill=col)
            x += L.text_width("Menlo", 20, t)
        return img


# HUD pass (journal 028): this region left stream/layout.py; the module stays on disk (its copy and tests are
# reused by the land strip) but registers nothing. `Readout` would be dropped by register() anyway.
# register(Readout())
