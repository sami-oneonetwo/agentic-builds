"""stream/panels/chat_log.py - compact CHAT LOG (WORLD.md 5 row 8, replaces chat_pane): 840,512,440,144.

Last 5 moderated messages past the 3 s hold (ctx.chat: ChatBridge.visible(), display_name already filtered), newest at
the bottom, Menlo 22 at 26 px line height, one line per message (truncated with …): username in its hashed colour
(the same hash the pip's body uses), a letter chip on votes, a shield chip row for the most recent mod action (60 s,
from state.mod.actions; the mod's and target's names pass the world's name filter). Empty: `chat is quiet. say
anything.` !kill: `chat hidden by mod`. Paused: an amber header line; the list freezes (the bridge freezes it).

This region exists for moderation visibility on the VOD; the show does not depend on it (chat lives in the bubbles).
No name is ever taken from ctx.chat_raw.
"""
from __future__ import annotations

import sys
from typing import Dict, List, Optional, Tuple

from PIL import ImageDraw

from stream import layout as L
from stream.panels import Panel, register
from stream.state_store import iso_to_epoch

LINE_H = 26
FONT, SIZE = "Menlo", 22
MAX_ROWS = 5
MOD_SHOW_S = 60.0
_MONO_ADV: Dict[int, int] = {}


def _adv(size: int) -> int:
    a = _MONO_ADV.get(size)
    if a is None:
        a = max(1, L.text_width(FONT, size, "0"))
        _MONO_ADV[size] = a
    return a


def _width(size: int, text: str) -> int:
    try:
        if text.isascii():
            return len(text) * _adv(size)
    except AttributeError:
        pass
    return L.text_width(FONT, size, text)


def _names_on(ctx) -> bool:
    if ctx.chat_display is False:
        return False
    return (ctx.chat_cfg or {}).get("display") is not False


def _shown(raw) -> Optional[str]:
    """The filtered display name of a chatter who HAS a pip record (a record exists only past the 3 s hold, so this can
    never leak a name inside the hold); None otherwise. The blocklist-only path (shown_name) is not used here."""
    m = sys.modules.get("stream.panels.world")
    if m is None or not hasattr(m, "shown_name_cleared"):
        return None
    try:
        return m.shown_name_cleared(raw)
    except Exception:
        return None


MOD_WORDS = {"hide": "hid a user", "unhide": "unhid a user", "banish": "banished a user", "unbanish": "unbanished a user",
             "rename": "cleared a nickname", "pause": "paused chat", "resume": "resumed chat", "kill": "hid chat",
             "unkill": "showed chat", "clear": "cleared the backlog"}


class ChatLog(Panel):
    key, region = "chat_log", "chat_log"

    @staticmethod
    def _msgs(ctx) -> List[Dict]:
        """Last 5 moderated messages of THIS run. Boot / deploy history (records older than HISTORY_S when first seen,
        flagged `history` by the bridge) is not shown: a 2-day-old line under a live cave reads as live chat."""
        return [m for m in (ctx.chat or []) if isinstance(m, dict) and not m.get("dropped") and not m.get("history")][-MAX_ROWS:]

    @staticmethod
    def _mod_row(ctx) -> Optional[Tuple[str, str, str]]:
        """(by, action words, "") for the newest mod action inside MOD_SHOW_S. The TARGET is never printed: a human
        !hide inside the hold exists to keep a name off screen, and this row must not defeat it (WORLD.md 11.1). The
        mod's own name shows only when the mod has a pip record (= past the hold); else `mod`."""
        acts = (ctx.mod or {}).get("actions") or []
        if not acts:
            return None
        a = acts[-1] if isinstance(acts[-1], dict) else None
        if a is None:
            return None
        t = iso_to_epoch(a.get("ts"))
        if t is None or ctx.now - t > MOD_SHOW_S:
            return None
        by = _shown(a.get("by")) or "mod"
        act = str(a.get("action") or "")
        return (by, MOD_WORDS.get(act, "mod action"), "")

    def inputs(self, ctx):
        on = _names_on(ctx)
        msgs = self._msgs(ctx) if on else []
        return (tuple(str(m.get("id")) for m in msgs), on, bool(ctx.mod_paused), self._mod_row(ctx) if on else None, ctx.preset)

    def render(self, ctx, size):
        w, h = size
        img = self.base(size)
        d = ImageDraw.Draw(img)
        accent = L.preset(ctx.preset)["accent"]
        f = L.font(FONT, SIZE)
        f20 = L.font("Menlo", 20)
        f20b = L.font("Menlo Bold", 20)
        maxw = w - 2 * L.PAD
        if not _names_on(ctx):
            d.text((L.PAD, h // 2 - 13), "chat hidden by mod", font=f, fill=L.COLORS["warn"])
            return img
        rows: List[List[Tuple[str, str, str]]] = []            # row = [(kind, text, colour)]
        mod = self._mod_row(ctx)
        for m in self._msgs(ctx):
            name = L.strip_non_bmp(str(m.get("display_name") or "?")) or "?"
            key = str(m.get("name") or name).lower()
            segs: List[Tuple[str, str, str]] = [("text", name, L.name_color(key, ctx.preset))]
            if m.get("first_ever") and m.get("builder_n"):
                segs.append(("text", " #%d" % int(m["builder_n"]), accent))
            body = m.get("text_clean")
            if body is None:
                body = L.strip_non_bmp(str(m.get("text") or ""))
            kind = m.get("kind")
            if kind == "vote" and m.get("letter"):
                segs.append(("chip", str(m["letter"])[:1].upper(), accent if m.get("accepted", True) else L.COLORS["text2"]))
                if body.strip().lstrip("!").upper() == str(m.get("letter")).upper():
                    body = ""
            elif kind == "idea":
                segs.append(("tag", "idea", L.COLORS["warn"]))
                body = L.strip_non_bmp(str(m.get("arg") or body))
            elif kind == "theme":
                segs.append(("tag", "theme", L.COLORS["text2"]))
            if body:
                segs.append(("text", ": ", L.COLORS["text2"]))
                segs.append(("text", body, L.COLORS["text"]))
            rows.append(segs)
        if mod is not None:
            by, action, tgt = mod
            rows.append([("shield", "mod", L.COLORS["warn"]), ("text", " %s %s%s" % (by, action, (" " + tgt) if tgt else ""), L.COLORS["text2"])])
        rows = rows[-MAX_ROWS:]
        top = 6
        if ctx.mod_paused:
            d.text((L.PAD, 4), L.truncate("Menlo", 20, "chat paused by mod · votes still count", maxw), font=f20, fill=L.COLORS["warn"])
            d.line([(L.PAD, 30), (w - L.PAD, 30)], fill=L.COLORS["hairline"], width=1)
            top = 34
        if not rows:
            d.text((L.PAD, h // 2 - 13), "chat is quiet. say anything.", font=f, fill=L.COLORS["text2"])
            return img
        avail_rows = max(1, (h - top - 6) // LINE_H)
        rows = rows[-avail_rows:]
        y = h - 6 - LINE_H * len(rows)
        for segs in rows:
            x = L.PAD
            # widths of everything before the body, so the body gets what is left and is truncated once
            for kind, text, col in segs:
                if x >= w - L.PAD:
                    break
                if kind == "chip":
                    d.rounded_rectangle([x + 4, y + 1, x + 26, y + 23], radius=4, fill=col)
                    tw = _width(20, text)
                    d.text((x + 15 - tw // 2, y + 1), text, font=f20b, fill=L.COLORS["bg"])
                    x += 30
                elif kind == "tag":
                    tw = _width(20, text)
                    d.rounded_rectangle([x + 4, y + 2, x + tw + 10, y + 23], radius=4, outline=col, width=1)
                    d.text((x + 7, y + 1), text, font=f20, fill=col)
                    x += tw + 14
                elif kind == "shield":
                    # a 16x20 shield outline with the word beside it
                    d.polygon([(x + 4, y + 3), (x + 20, y + 3), (x + 20, y + 14), (x + 12, y + 22), (x + 4, y + 14)], outline=col)
                    d.text((x + 26, y + 1), text, font=f20, fill=col)
                    x += 26 + _width(20, text) + 4
                else:
                    t = L.truncate(FONT, SIZE, text, max(0, w - L.PAD - x))
                    if t:
                        d.text((x, y), t, font=f, fill=col)
                        x += _width(SIZE, t)
            y += LINE_H
        return img


register(ChatLog())
