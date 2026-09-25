"""stream/panels/keeper.py - KEEPER strip (WORLD.md 5 row 7, 9): 420,512,420,144.

  line 1   HN Medium 22  `keeper on duty` (accent) when agent.heartbeat_ts is fresh (< 120 s), else
                         `no keeper on duty · scrolls kept for next time` (secondary; 449 px at 22 px, so it wraps to
                         two rows: rows are laid out top-down at 26 px and the failure lines take priority over a
                         second row). The lantern in the cave is lit on exactly the same test (the scene reads the same
                         field), so the strip and the lantern agree.
  line 2   Menlo 22      macro.active: `carving: <title> · asked by @<requested_by> · 12:40 left`
                         otherwise `last carved: <title> · v0.5.0 · asked by @sam` from the newest `kind: macro` line
                         in ctx.ships (ships.jsonl), or `nothing carved yet · !idea <text> asks for something` when
                         there is none. Plain language only, never a live diff.
  lines 3-5 Menlo 20     ONLY on failure, for 20 s after macro.last_reload.ts with ok False: the first 3 lines of the
                         error + `reverting to <current version>`. Failure is content only when it happens.

Names (`requested_by`, `picked_by`) are raw usernames written by the agent: they pass through the world panel's
`shown_name()` (blocklist -> `builder #N`) before drawing; under !kill no name is drawn at all.
"""
from __future__ import annotations

import sys
from typing import List, Optional, Tuple

from PIL import ImageDraw

from stream import layout as L
from stream.panels import Panel, register
from stream.state_store import iso_to_epoch
from stream.world import keepers as K

HEARTBEAT_FRESH_S = 120.0
FAIL_SHOW_S = 20.0
IDEA_HINT = "!idea <text> leaves a scroll for the keepers"


def _mmss(sec) -> str:
    sec = max(0, int(sec))
    return "%02d:%02d" % (sec // 60, sec % 60)


def _shown(raw) -> Optional[str]:
    m = sys.modules.get("stream.panels.world")
    if m is None or not hasattr(m, "shown_name"):
        return None
    try:
        return m.shown_name(raw)
    except Exception:
        return None


def _names_on(ctx) -> bool:
    if ctx.chat_display is False:
        return False
    return (ctx.chat_cfg or {}).get("display") is not False


def _keepers():
    """The Keepers attached to the live world scene (milestone carves), or None."""
    m = sys.modules.get("stream.panels.world")
    if m is None or not hasattr(m, "keepers"):
        return None
    try:
        return m.keepers()
    except Exception:
        return None


class KeeperPanel(Panel):
    key, region = "keeper", "keeper"

    @staticmethod
    def _fresh(ctx) -> bool:
        hb = iso_to_epoch((ctx.agent or {}).get("heartbeat_ts"))
        return hb is not None and (ctx.now - hb) < HEARTBEAT_FRESH_S

    def _line1(self, ctx) -> Tuple[str, str]:
        if self._fresh(ctx):
            return "keeper on duty", L.preset(ctx.preset)["accent"]
        return "the keepers are away tonight", L.COLORS["text2"]

    @staticmethod
    def _visitors(ctx) -> Optional[str]:
        """`last here: @a 18:00 · @b 14:59` from the world's real visits (HEARTH graft, WORLD.md 10); None before boot."""
        m = sys.modules.get("stream.panels.world")
        if m is None or not hasattr(m, "scene") or not _names_on(ctx):
            return None
        try:
            sc = m.scene()
            if sc is None or not sc.booted:
                return None
            visits = list((sc.world.data.get("world") or {}).get("visits") or [])[-3:]
            segs = []
            for v in reversed(visits):
                nm = m.shown_name(v.get("name"))
                if nm:
                    segs.append("@%s %s" % (nm, m.when_text(v.get("ts"), float(ctx.now))))
            return ("last here: " + " · ".join(segs)) if segs else None
        except Exception:
            return None

    @staticmethod
    def _last_macro(ctx):
        for s in reversed(list(ctx.ships or [])):
            if isinstance(s, dict) and s.get("kind") == "macro":
                return s
        return None

    def _line2(self, ctx) -> Tuple[str, str]:
        mac = ctx.macro or {}
        names_on = _names_on(ctx)
        kp = _keepers()
        if kp is not None and not mac.get("active"):
            # a milestone carve in progress / just finished (stream/world/keepers.py) outranks the ships.jsonl line
            try:
                cl = kp.carving_line(float(ctx.now), ctx=ctx)
                if cl is not None:
                    return L.strip_non_bmp(cl["line"]), L.COLORS["text"]
                lc = kp.last_carved
                if lc is not None and ctx.now - float(lc.get("t") or 0) < 600.0:
                    who = _shown(lc.get("by")) if (names_on and lc.get("by")) else None
                    return ("last carved: %s · %s%s" % (lc["name"], lc["version"], (" · opened by @%s's hatch" % who) if who else ""),
                            L.COLORS["text"])
                if kp.waiting is not None:
                    # the colony strip already says `<chamber> opens next time a keeper is here`; this strip shows the
                    # people instead of repeating it
                    vis = self._visitors(ctx)
                    if vis:
                        return vis, L.COLORS["text2"]
                    return "your !idea <text> waits on the wall for them", L.COLORS["text2"]
            except Exception:
                pass
        if mac.get("active"):
            title = L.strip_non_bmp(str(mac.get("title") or "a new chamber"))
            who = _shown(mac.get("requested_by")) if names_on else None
            dl = iso_to_epoch(mac.get("deadline_ts"))
            rem = None if dl is None else int(dl - ctx.now)
            tail = (" · %s left" % _mmss(rem)) if (rem is not None and rem >= 0) else (" · overdue" if rem is not None else "")
            return "carving: %s%s%s" % (title, (" · asked by @%s" % who) if who else "", tail), L.COLORS["text"]
        last = self._last_macro(ctx)
        if last is not None:
            title = L.strip_non_bmp(str(last.get("title") or "macro-ship"))
            ver = last.get("version") or ""
            who = _shown(last.get("requested_by") or last.get("picked_by")) if names_on else None
            ok = last.get("ok") is not False
            return ("%s: %s%s%s" % ("last carved" if ok else "last carve failed", title, (" · %s" % ver) if ver else "",
                                    (" · asked by @%s" % who) if who else ""),
                    L.COLORS["text"] if ok else L.COLORS["warn"])
        vis = self._visitors(ctx) if not self._fresh(ctx) else None
        if vis:
            return vis, L.COLORS["text2"]
        return IDEA_HINT, L.COLORS["text2"]

    def _failure(self, ctx) -> List[str]:
        lr = (ctx.macro or {}).get("last_reload") or {}
        if not isinstance(lr, dict) or lr.get("ok") is not False:
            return []
        t = iso_to_epoch(lr.get("ts"))
        if t is None or ctx.now - t > FAIL_SHOW_S:
            return []
        err = str(lr.get("error") or "build failed")
        lines = [ln.strip() for ln in err.strip().splitlines() if ln.strip()][:2] or ["build failed"]   # 2 + reverting always fit
        ver = (ctx.version or {}).get("string") or "the last good version"
        return [L.strip_non_bmp(ln) for ln in lines] + ["reverting to %s" % ver]

    def inputs(self, ctx):
        return (self._line1(ctx), self._line2(ctx), tuple(self._failure(ctx)), ctx.preset)

    def render(self, ctx, size):
        w, h = size
        img = self.base(size)
        d = ImageDraw.Draw(img)
        maxw = w - 2 * L.PAD - 24                # the lantern glyph sits in the last 24 px
        t1, c1 = self._line1(ctx)
        t2, c2 = self._line2(ctx)
        fail = self._failure(ctx)
        rows: List[Tuple[str, str, int, str]] = []            # (font, text, size, colour)
        l1 = L.wrap("HN Medium", 22, t1, maxw, 1 if fail else 2)
        rows += [("HN Medium", ln, 22, c1) for ln in l1]
        l2 = L.wrap("Menlo", 22, t2, maxw, 1 if fail else 2)          # 4 rows of 22 px + gaps = 136 px, fits 144
        rows += [("Menlo", ln, 22, c2) for ln in l2]
        for i, ln in enumerate(fail):
            col = L.COLORS["danger"] if i == 0 else (L.COLORS["warn"] if ln.startswith("reverting") else L.COLORS["text2"])
            rows.append(("Menlo", ln, 20, col))
        y = 8
        for font, txt, sz, col in rows:
            step = 26 if sz == 22 else 22
            if y + step > h - 2:
                break
            d.text((L.PAD, y), L.truncate(font, sz, txt, maxw), font=L.font(font, sz), fill=col)
            y += step + (6 if sz == 22 else 0)
        # lantern glyph (24 px): a dotted chain, a hood, a glass body and a base, lit only on the same honesty test as the
        # cave's lantern (a fresh keeper heartbeat)
        lit = self._fresh(ctx)
        accent = L.preset(ctx.preset)["accent"]
        lx = w - L.PAD - 8
        for yy in (6, 10, 14):
            d.point((lx, yy), fill=L.COLORS["text2"])
        d.polygon([(lx - 7, 22), (lx + 7, 22), (lx + 4, 17), (lx - 4, 17)], fill=L.COLORS["text2"])
        d.rectangle([lx - 6, 23, lx + 6, 37], fill=accent if lit else L.COLORS["hairline"], outline=L.COLORS["text2"], width=1)
        if lit:
            d.rectangle([lx - 2, 27, lx + 2, 33], fill=L.COLORS["text"])
        d.line([(lx - 7, 39), (lx + 7, 39)], fill=L.COLORS["text2"], width=2)
        return img


register(KeeperPanel())
