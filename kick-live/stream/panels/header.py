"""Header panels (OPENWORLD.md 8 rows 1-2; HUD pass 2026-09-26, journal 028). The header is the thumbnail: it is
composited LAST by the compositor (region key starts with "header") so it is drawn over every world state.

  header_center 0,0,880,66    THE THUMBNAIL. Headline Arial Black 56 at x 16, glyphs centred on y 33:
                              awake == 0 -> `SAY ANYTHING` (the instruction; 484 px, wider than `NOBODY AWAKE` so it
                              survives the 320x180 directory tile better); awake >= 1 -> `3 AWAKE` (the live count is
                              the honest signal, and the flip SAY ANYTHING -> 1 AWAKE is the newcomer's first ack).
                              Before the world boots / on a stale state.json: `SAY ANYTHING`, never a number, never
                              `NOBODY AWAKE`, never `-- AWAKE`.
                              Right of the headline (x = 16 + headline + 16) a two-row Menlo 22 column at y 7 / 36:
                              awake == 0: `a creature walks out` / `with your name` (text colour);
                              awake >= 1: `say anything` / `a creature walks out with your name` (text2);
                              pre-boot / stale: `the land is waking up…` (text2) on row 1, row 2 empty.
                              The round clock, the settled count and the raising line LEFT this region: the clock is
                              the vote card's fuse (stream/panels/world.py), the headcount lives once in the land strip,
                              the raising is land strip row 3.
  header_right  880,0,400,66  row 1 (y 7) `LONGGRASS   ● LIVE`, right-aligned to x 1264 (canvas): the wordmark Menlo 22
                              text2, a 16 px gap, a status dot (r 6), 8 px, `LIVE` Menlo 22. The dot is red when
                              metrics.is_live AND the chat listener is connected with fresh chat_stats.json, amber when
                              the listener is disconnected / stale (the old header_left dot's test), a dim hairline dot
                              with no `LIVE` word when the poll says offline. Row 2 (y 38) Menlo 20 text2: the CLOCK ROW
                              the world panel computes from its nature model (`midday · wind NE fresh · spring`; the
                              world clock + `a day here is one hour` in hour mode): nature declared in one muted row,
                              here and not on the land because the land's bottom-right is where the camera frames the
                              waystones (HUD fix pass, journal 030: the chip was pasted over the letters' counts). Without
                              a booted land (the cave, pre-boot) row 1 alone, vertically centred, as before. No viewer
                              count (Kick prints it beside the player), no version string, no `day N`.

header_left is gone (stream/layout.py REMOVED_REGIONS): Kick's player already prints the channel name, and the
micro `header_tagline` slot turned that corner into a slogan generator (`CHAT BUILDS THIS` on the live frame).

Every value comes from ctx (state.json / metrics.jsonl / chat_stats.json) or the world scene. Nothing is invented: the
awake count is the number of real chatters awake on the land (stream/panels/world.py `world_counts()`).
"""
from __future__ import annotations

import sys
from typing import Optional, Tuple

from PIL import Image, ImageDraw

from stream import layout as L
from stream.panels import Panel, register
from stream.state_store import iso_to_epoch

CHAT_STATS_FRESH_S = 60.0     # chat_stats.json is rewritten every 10 s by the listener; older -> "reconnecting"
COL_GAP = 16                  # px between the headline and the right column
HEADLINE_X = 16
WORDMARK_LAND = "LONGGRASS"
WORDMARK_CAVE = "PIP HOLLOW"
WORDMARK = WORDMARK_LAND      # kept for callers that import the old constant
SAY = "SAY ANYTHING"
COL_ZERO = ("a creature walks out", "with your name")
COL_AWAKE = ("say anything", "a creature walks out with your name")
COL_BOOT = ("the land is waking up…", "")
COL_ZERO_CAVE = ("a pip hatches", "with your name")
COL_AWAKE_CAVE = ("say anything", "a pip hatches with your name")
COL_BOOT_CAVE = ("the cave is waking up…", "")


def _mmss(sec) -> str:
    if sec is None:
        return "--:--"
    sec = max(0, int(sec))
    if sec >= 6000:
        return "%d:%02d:%02d" % (sec // 3600, (sec // 60) % 60, sec % 60)
    return "%02d:%02d" % (sec // 60, sec % 60)


def _blend(hex_a: str, hex_b: str, t: float):
    a, b = L.hex_rgb(hex_a), L.hex_rgb(hex_b)
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _chat_connected(ctx) -> bool:
    """True iff the Pusher listener says connected AND its stats file is fresh; else the dot turns amber (reconnecting)."""
    cs = ctx.chat_stats or {}
    if cs:
        t = iso_to_epoch(cs.get("ts"))
        fresh = t is not None and (ctx.now - t) < CHAT_STATS_FRESH_S
        return bool(cs.get("connected")) and fresh
    return bool((ctx.chat_cfg or {}).get("connected"))


def _scene():
    m = sys.modules.get("stream.panels.world")
    if m is None or not hasattr(m, "scene"):
        return None
    try:
        return m.scene()
    except Exception:
        return None


def _is_land() -> bool:
    """True while the world panel's scene is a land scene (it has a `land` attribute), booted or not."""
    return hasattr(_scene(), "land")


def _clock_row() -> Optional[str]:
    """The land's clock row for THIS frame (the world panel renders before the header and stashes the string it
    derived from its nature model); None on the cave / before the land boots / when the panel is not loaded."""
    m = sys.modules.get("stream.panels.world")
    pnl = getattr(m, "PANEL", None) if m is not None else None
    txt = getattr(pnl, "last_clock_row", None) if pnl is not None else None
    if not txt or not _is_land():
        return None
    return str(txt)


def _world_counts() -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """(awake, asleep, hatched) from the live world panel module, or Nones when the world is not up."""
    m = sys.modules.get("stream.panels.world")
    if m is None or not hasattr(m, "world_counts"):
        return None, None, None
    try:
        return m.world_counts()
    except Exception:
        return None, None, None


# ----------------------------------------------------------------------------- region 1 (the thumbnail)
class HeaderCenter(Panel):
    key, region = "header_center", "header_center"

    def __init__(self):
        self._ab: dict = {}            # (text, size, colour, max_w) -> 66 px tall AB strip

    @staticmethod
    def headline(ctx) -> Tuple[str, str]:
        """(text, colour role): `SAY ANYTHING` at 0 awake, before boot and on a stale state; `N AWAKE` once anyone is in.
        Never a number before boot, never `NOBODY AWAKE`, never `-- AWAKE` (the tile hook, OPENWORLD 3.1 / 8)."""
        awake, _asleep, _hatched = _world_counts()
        if awake is None or awake <= 0:
            return SAY, "text"
        return "%d AWAKE" % awake, "text"

    @staticmethod
    def column(ctx) -> Tuple[str, str, str]:
        """(row 1, row 2, colour role) for the Menlo 22 column beside the headline."""
        land = _is_land()
        awake, _asleep, _hatched = _world_counts()
        if awake is None or ctx.stale:
            r1, r2 = COL_BOOT if land else COL_BOOT_CAVE
            return r1, r2, "text2"
        if awake == 0:
            r1, r2 = COL_ZERO if land else COL_ZERO_CAVE
            return r1, r2, "text"
        r1, r2 = COL_AWAKE if land else COL_AWAKE_CAVE
        return r1, r2, "text2"

    def inputs(self, ctx):
        return (self.headline(ctx), self.column(ctx), ctx.preset, bool(ctx.stale))

    def _ab_strip(self, txt: str, size: int, col, max_w: int):
        """Cached 66 px tall Arial Black strip, glyphs centred on y 33."""
        key = (txt, size, col, max_w)
        img = self._ab.get(key)
        if img is None:
            f = L.font("AB", size)
            t = L.truncate("AB", size, txt, max_w, ell="…")
            bb = f.getbbox(t)
            img = Image.new("RGBA", (max(1, bb[2]), 66), (0, 0, 0, 0))
            ImageDraw.Draw(img).text((0, 33 - (bb[1] + bb[3]) // 2), t, font=f, fill=col)
            if len(self._ab) > 24:
                self._ab.clear()
            self._ab[key] = img
        return img

    def render(self, ctx, size):
        w, h = size
        img = Image.new("RGBA", size, L.COLORS["bg"])
        d = ImageDraw.Draw(img)
        txt, role = self.headline(ctx)
        col = L.COLORS["text2"] if ctx.stale else L.COLORS.get(role, L.COLORS["text"])
        # the headline may take at most the width that leaves 300 px for the column (`999 AWAKE` is ~360 px)
        cimg = self._ab_strip(txt, 56, col, w - HEADLINE_X - COL_GAP - 300 - L.PAD)
        img.alpha_composite(cimg, (HEADLINE_X, 0))
        lx = HEADLINE_X + cimg.size[0] + COL_GAP
        avail = w - lx - L.PAD
        if avail < 60:
            return img
        r1, r2, crole = self.column(ctx)
        ccol = L.COLORS.get(crole, L.COLORS["text2"])
        f = L.font("Menlo", 22)
        if r1:
            d.text((lx, 7), L.truncate("Menlo", 22, r1, avail), font=f, fill=ccol)
        if r2:
            d.text((lx, 36), L.truncate("Menlo", 22, r2, avail), font=f, fill=ccol)
        return img


# ----------------------------------------------------------------------------- region 2
class HeaderRight(Panel):
    key, region = "header_right", "header_right"

    @staticmethod
    def status(ctx) -> Tuple[bool, bool]:
        """(live, chat linked): live from the real metrics poll; chat linked = listener connected + fresh stats."""
        m = ctx.metrics or {}
        return bool(m.get("is_live")), _chat_connected(ctx)

    @staticmethod
    def wordmark() -> str:
        return WORDMARK_LAND if _is_land() else WORDMARK_CAVE

    def inputs(self, ctx):
        return (self.wordmark(), self.status(ctx), ctx.preset, _clock_row())

    def render(self, ctx, size):
        w, h = size
        img = Image.new("RGBA", size, L.COLORS["bg"])
        d = ImageDraw.Draw(img)
        f = L.font("Menlo", 22)
        live, linked = self.status(ctx)
        right = w - L.PAD
        clock = _clock_row()
        if clock:
            # two rows: the wordmark row at y 7, the muted clock row at y 38 (the same rows header_center's column uses)
            ty = 7
            cy = ty + 15
            f20 = L.font("Menlo", 20)
            ct = L.truncate("Menlo", 20, clock, w - 2 * L.PAD)
            d.text((right - L.text_width("Menlo", 20, ct), 38), ct, font=f20, fill=L.COLORS["text2"])
        else:
            ty = 22                                          # Menlo 22 glyphs vertically centred in 66
            cy = h // 2
        r = 6
        x = right
        if live:
            lw = L.text_width("Menlo", 22, "LIVE")
            x -= lw
            d.text((x, ty), "LIVE", font=f, fill=L.COLORS["text"])
            x -= 8
        dot = (L.COLORS["danger"] if linked else L.COLORS["warn"]) if live else L.COLORS["hairline"]
        x -= r
        d.ellipse([x - r, cy - r, x + r, cy + r], fill=dot)
        if live:
            d.ellipse([x - r - 3, cy - r - 3, x + r + 3, cy + r + 3], outline=_blend(dot, L.COLORS["bg"], 0.6), width=1)
        x -= r + 16
        wm = self.wordmark()
        ww = L.text_width("Menlo", 22, wm)
        d.text((x - ww, ty), wm, font=f, fill=L.COLORS["text2"])
        return img


register(HeaderCenter())
register(HeaderRight())
