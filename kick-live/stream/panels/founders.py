"""stream/panels/founders.py - founders strip (region 12: 840,384,440,28; Menlo 20).

`founders: sam kai lu (3)` - the first 10 real chatters of the session (ctx.founders, ChatBridge's
list with state.chat.founders as fallback), in arrival order, for the whole stream. Each name is in
its hashed palette colour (L.name_color) so it matches the chat pane. Names that do not fit are
folded into `…` and the count is always drawn. A new founder lands with a 1 s accent pulse
(10 quantised steps, then the panel is static again). Hidden users (state.mod.hidden_users) are
never drawn. Kill switch: `founders: chat hidden by mod`.
Empty: `founders: nobody yet. first is #1` (33 chars = 396 px, fits the 408 px text width).
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from PIL import ImageDraw

from stream import layout as L
from stream.panels import Panel, register

FONT, SIZE = "Menlo", 20
PULSE_FRAMES = 30          # 1 s at 30 fps
PULSE_STEPS = 10
EMPTY_TEXT = "founders: nobody yet. first is #1"


def _mix(a: str, b: str, f: float) -> Tuple[int, int, int]:
    f = 0.0 if f < 0 else (1.0 if f > 1 else f)
    ra, rb = L.hex_rgb(a), L.hex_rgb(b)
    return tuple(int(round(ra[i] + (rb[i] - ra[i]) * f)) for i in range(3))


def _display_on(ctx) -> bool:
    if ctx.chat_display is False:
        return False
    if (ctx.chat_cfg or {}).get("display") is False:
        return False
    return True


class Founders(Panel):
    key, region = "founders", "founders"

    def __init__(self):
        self._count: Optional[int] = None
        self._pulse_frame = -10 ** 9

    def _names(self, ctx) -> List[str]:
        hidden = set(str(u).lower() for u in ((ctx.mod or {}).get("hidden_users") or []))
        out: List[str] = []
        for n in (ctx.founders or []):
            s = L.strip_non_bmp(str(n)).strip()
            if s and s.lower() not in hidden and s not in out:
                out.append(s)
        return out[:10]

    def inputs(self, ctx):
        on = _display_on(ctx)
        names = self._names(ctx) if on else []
        frame = ctx.frame or 0
        if self._count is not None and len(names) > self._count:
            self._pulse_frame = frame          # a founder just landed -> pulse the newest name
        self._count = len(names)
        k = max(0, frame - self._pulse_frame)
        step = min(PULSE_STEPS, k * PULSE_STEPS // PULSE_FRAMES)
        return (tuple(names), on, step, ctx.preset)

    def render(self, ctx, size):
        w, h = size
        img = self.base(size)
        d = ImageDraw.Draw(img)
        f = L.font(FONT, SIZE)
        maxw = w - 2 * L.PAD
        y = 3
        if not _display_on(ctx):
            d.text((L.PAD, y), L.truncate(FONT, SIZE, "founders: chat hidden by mod", maxw), font=f, fill=L.COLORS["warn"])
            return img
        names = self._names(ctx)
        if not names:
            d.text((L.PAD, y), L.truncate(FONT, SIZE, EMPTY_TEXT, maxw), font=f, fill=L.COLORS["text2"])
            return img
        accent = L.preset(ctx.preset)["accent"]
        frame = ctx.frame or 0
        step = min(PULSE_STEPS, max(0, frame - self._pulse_frame) * PULSE_STEPS // PULSE_FRAMES)
        label = "founders: "
        suffix = " (%d)" % len(names)
        ell = "…"
        x = L.PAD
        d.text((x, y), label, font=f, fill=L.COLORS["text2"])
        x += L.text_width(FONT, SIZE, label)
        limit = L.PAD + maxw - L.text_width(FONT, SIZE, suffix)
        drawn = 0
        for i, n in enumerate(names):
            piece = n if i == 0 else " " + n
            pw = L.text_width(FONT, SIZE, piece)
            more_after = i < len(names) - 1
            reserve = L.text_width(FONT, SIZE, ell) if more_after else 0
            if x + pw + reserve > limit and drawn > 0:
                d.text((x, y), ell, font=f, fill=L.COLORS["text2"])
                x += L.text_width(FONT, SIZE, ell)
                break
            col = L.name_color(n, ctx.preset)
            if i == len(names) - 1 and step < PULSE_STEPS:
                col = _mix(accent, col, step / float(PULSE_STEPS))      # newest founder: accent -> own colour
            if i == 0:
                d.text((x, y), n, font=f, fill=col)
            else:
                d.text((x + L.text_width(FONT, SIZE, " "), y), n, font=f, fill=col)
            x += pw
            drawn += 1
        d.text((x, y), suffix, font=f, fill=L.COLORS["text2"])
        return img


register(Founders())
