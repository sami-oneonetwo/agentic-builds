"""stream/panels/activity_feed.py - region 8 (0,372,840,120): the last 4 lines of $ACTIVITY_FILE.

`20:14:07 builder  Edit stream/scenes/ballot.py +18 -2`  Menlo 22, 28 px line height, actor coloured
(builder white, qa cyan, critic violet, supervisor/compositor grey, ship accent, mod amber, fail red, chat blue).
A new line slides up over 8 frames (ease-out): every row moves up one line height while the newest enters from
the bottom edge and the oldest leaves through the top edge (clipped by the region, never drawn outside it).

Cache discipline (journal 009): the cache key is the 4 rows + the 8-step slide counter, so the panel renders
8 times per new line and then never again; each row is a cached RGBA strip, so a slide frame is 4-5 pastes.
Reads nothing from disk: ctx.activity is the StateStore's tail of activity.jsonl (250 ms poll)."""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from stream import layout as L
from stream.panels import Panel, register
from stream.state_store import iso_to_epoch

ROW_H = 28
ROWS = 4
SLIDE_FRAMES = 8
STRIP_CACHE_MAX = 64
COL_TIME = L.PAD                 # hh:mm:ss  (8 x 13 px)
COL_ACTOR = L.PAD + 116          # up to 10 chars ("compositor", "supervisor" are 10)
COL_TEXT = L.PAD + 258


def _blit(dst: Image.Image, strip: Image.Image, x: int, y: int) -> None:
    """alpha_composite that tolerates a strip partly above the top edge (PIL rejects negative dest coords)."""
    if y < 0:
        if y <= -strip.size[1]:
            return
        strip = strip.crop((0, -y, strip.size[0], strip.size[1]))
        y = 0
    if y >= dst.size[1]:
        return
    dst.alpha_composite(strip, (x, y))


def _hhmmss(ts) -> str:
    t = iso_to_epoch(ts) if ts else None
    if t is None:
        return "--:--:--"
    lt = time.localtime(t)                     # the owner's clock, matches the journal / kl_activity lines
    return "%02d:%02d:%02d" % (lt.tm_hour, lt.tm_min, lt.tm_sec)


class ActivityFeed(Panel):
    key, region = "activity_feed", "activity_feed"

    def __init__(self):
        self._rows: Optional[Tuple] = None
        self._prev_top: Optional[Tuple] = None      # the row that scrolls out during a slide
        self._anim_start: Optional[int] = None
        self._strips: Dict[Tuple, Image.Image] = {}

    # ---- data ------------------------------------------------------------------
    @staticmethod
    def _rows_of(ctx) -> Tuple:
        rows: List[Tuple[str, str, str]] = []
        for a in (ctx.activity or [])[-ROWS:]:
            if not isinstance(a, dict):
                continue
            rows.append((_hhmmss(a.get("ts")), L.strip_non_bmp(str(a.get("actor") or "?"))[:10],
                         L.strip_non_bmp(str(a.get("text") or "")).replace("\n", " ")))
        return tuple(rows)

    def inputs(self, ctx):
        rows = self._rows_of(ctx)
        if rows != self._rows:
            old = self._rows or ()
            # a genuinely new line arrived (not just a re-read of the same tail) -> slide; keep the row that leaves
            self._prev_top = old[0] if (old and len(old) >= ROWS and len(rows) >= ROWS and rows[:-1] == old[1:]) else None
            self._anim_start = ctx.frame if old else None      # no slide for the very first fill
            self._rows = rows
        step = SLIDE_FRAMES
        if self._anim_start is not None:
            step = max(0, min(SLIDE_FRAMES, int(ctx.frame) - int(self._anim_start)))
        return (rows, step, ctx.preset)

    # ---- drawing ---------------------------------------------------------------
    def _actor_colour(self, actor: str, text: str, accent: str) -> str:
        col = L.ACTOR_COLORS.get(actor, L.COLORS["text2"])
        if col == "accent":
            col = accent
        low = text.lower()
        if actor in ("compositor", "supervisor") and ("failed" in low or "disabled" in low or "watchdog" in low):
            col = L.COLORS["danger"]
        return col

    def _strip(self, row: Tuple[str, str, str], newest: bool, accent: str, w: int) -> Image.Image:
        key = (row, newest, accent)
        img = self._strips.get(key)
        if img is None:
            if len(self._strips) >= STRIP_CACHE_MAX:
                self._strips.clear()
            hh, actor, text = row
            img = Image.new("RGBA", (w, ROW_H), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            f = L.font("Menlo", 22)
            d.text((COL_TIME, 2), hh, font=f, fill=L.COLORS["text2"])
            d.text((COL_ACTOR, 2), actor, font=f, fill=self._actor_colour(actor, text, accent))
            d.text((COL_TEXT, 2), L.truncate("Menlo", 22, text, w - COL_TEXT - L.PAD), font=f,
                   fill=L.COLORS["text"] if newest else L.COLORS["text2"])
            self._strips[key] = img
        return img

    def render(self, ctx, size):
        w, h = size
        img = self.base(size)
        accent = L.preset(ctx.preset)["accent"]
        rows = self._rows or ()
        if not rows:
            d = ImageDraw.Draw(img)
            d.text((L.PAD, 4), "activity", font=L.font("Menlo", 20), fill=L.COLORS["text2"])
            d.text((L.PAD, h // 2 - 8), L.truncate("Menlo", 22, "no agent activity yet. the compositor is running rounds on its own.", w - 2 * L.PAD),
                   font=L.font("Menlo", 22), fill=L.COLORS["text2"])
            return img
        step = SLIDE_FRAMES
        if self._anim_start is not None:
            step = max(0, min(SLIDE_FRAMES, int(ctx.frame) - int(self._anim_start)))
        t = step / float(SLIDE_FRAMES)
        ease = 1.0 - (1.0 - t) * (1.0 - t)                      # ease-out over 8 frames
        offset = int(round(ROW_H * (1.0 - ease))) if step < SLIDE_FRAMES else 0
        n = len(rows)
        y_first = h - 4 - ROW_H * n                              # rows sit on the bottom edge (newest last)
        if offset and self._prev_top is not None:               # the row leaving through the top edge
            _blit(img, self._strip(self._prev_top, False, accent, w), 0, y_first - ROW_H + offset)
        for i, row in enumerate(rows):
            y = y_first + i * ROW_H + (offset if n >= ROWS or i == n - 1 else 0)
            if y <= -ROW_H or y >= h:
                continue
            _blit(img, self._strip(row, i == n - 1, accent, w), 0, y)
        return img


register(ActivityFeed())
