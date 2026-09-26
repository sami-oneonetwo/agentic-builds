"""stream/panels/keeper.py - KEEPER strip (OPENWORLD.md 8 row 7, 10; WORLD.md 5 row 7 on the cave): 420,512,420,144.

On the land (the scene exposes a schema-2 `land`):
  line 1   HN Medium 22  `keeper on duty · beacon lit` (accent) when agent.heartbeat_ts is fresh (< 120 s), else
                         `no keeper on duty · notices kept for next time` (secondary; wraps to two rows). The beacon on
                         its post at the Moot is lit on exactly the same test (the scene reads the same field), so the
                         strip, the beacon and its minimap dot agree.
  line 2   Menlo 22      macro.active: `raising: <title> · asked by @<requested_by> · 12:40 left`
                         else the land keepers' own line when they expose one (`raising_line(now, ctx)`), else
                         `last raised: <title> · v0.7.0 · asked by @sam` from the newest `kind: macro` line in ctx.ships
                         (ships.jsonl), else, with no keeper on duty, the last three real visitors `last here: @a 18:00 ·
                         @b 14:59`, else `!idea <text> pins a notice to the board on the Moot`. Plain language only,
                         never a live diff.
  lines 3-5 Menlo 20     ONLY on failure, for 20 s after macro.last_reload.ts with ok False: the first 2 lines of the
                         error + `reverting to <current version>`. Failure is content only when it happens.
  glyph                  the beacon (a post with an iron basket, 24 px): lit accent + a flame on a fresh heartbeat,
                         dark otherwise. The keepers are never a figure (docs/art-rules.md).

On the cave (no `land`) every line keeps the cave copy from journal 021 (`keeper on duty` / `the keepers are away
tonight`, `carving:` / `last carved:`), with the lantern glyph, so a panel-only hot-reload never changes the cave.

Names (`requested_by`, `picked_by`, visitors) are raw usernames written by the agent or the world: they pass through
the world panel's `shown_name()` (blocklist -> `builder #N`) before drawing; under !kill no name is drawn at all.
"""
from __future__ import annotations

import sys
from typing import List, Optional, Tuple

from PIL import ImageDraw

from stream import layout as L
from stream.panels import Panel, register
from stream.state_store import iso_to_epoch

HEARTBEAT_FRESH_S = 120.0
FAIL_SHOW_S = 20.0
IDEA_HINT_LAND = "!idea <text> pins a notice to the board on the Moot"
# The owner asked in chat what the keepers are (journal 023): the strip explains itself in plain words, alternating
# every EXPLAIN_ROTATE_S with whatever line 2 would otherwise carry (never while a raising is going up).
EXPLAINER_LAND = "the keepers are AI agents building this show live"     # two Menlo 22 rows in the 364 px strip
EXPLAINER_CAVE = EXPLAINER_LAND
EXPLAIN_ROTATE_S = 8.0
IDEA_HINT_CAVE = "!idea <text> leaves a scroll for the keepers"
IDEA_HINT = IDEA_HINT_LAND
ON_DUTY_LAND, OFF_DUTY_LAND = "keeper on duty · beacon lit", "no keeper on duty · notices kept for next time"
ON_DUTY_CAVE, OFF_DUTY_CAVE = "keeper on duty", "the keepers are away tonight"
WAITING_LAND = "your !idea <text> waits on the board for them"
WAITING_CAVE = "your !idea <text> waits on the wall for them"


def _mmss(sec) -> str:
    sec = max(0, int(sec))
    return "%02d:%02d" % (sec // 60, sec % 60)


def _wm():
    return sys.modules.get("stream.panels.world")


def _scene():
    m = _wm()
    if m is None or not hasattr(m, "scene"):
        return None
    try:
        return m.scene()
    except Exception:
        return None


def _land():
    """The Land the booted scene draws, or None on the cave / before boot."""
    sc = _scene()
    return getattr(sc, "land", None) if (sc is not None and getattr(sc, "booted", False)) else None


def _is_land_scene() -> bool:
    return hasattr(_scene(), "land")


def _shown(raw) -> Optional[str]:
    m = _wm()
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
    """The Keepers attached to the live world scene, or None."""
    m = _wm()
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
        land = _is_land_scene()
        if self._fresh(ctx):
            return (ON_DUTY_LAND if land else ON_DUTY_CAVE), L.preset(ctx.preset)["accent"]
        return (OFF_DUTY_LAND if land else OFF_DUTY_CAVE), L.COLORS["text2"]

    @staticmethod
    def _visitors(ctx) -> Optional[str]:
        """`last here: @a 18:00 · @b 14:59` from the world's real visits (WORLD.md 10, kept); None before boot. Built
        to fit the strip's two Menlo 22 rows whole: three visitors, else two, else one; never a chopped name."""
        m = _wm()
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
            if not segs:
                return None
            maxw = L.region_size("keeper")[0] - 2 * L.PAD - 24
            for n in range(len(segs), 0, -1):
                text = "last here: " + " · ".join(segs[:n])
                rows = L.wrap("Menlo", 22, text, maxw, 2)
                if rows and not rows[-1].endswith("…"):
                    return text
            return None
        except Exception:
            return None

    @staticmethod
    def _last_macro(ctx):
        for s in reversed(list(ctx.ships or [])):
            if isinstance(s, dict) and s.get("kind") == "macro":
                return s
        return None

    def _line2(self, ctx) -> Tuple[str, str]:
        """Line 2, with the plain explainer on every other EXPLAIN_ROTATE_S slot unless a build is going up."""
        text, colour = self._line2_inner(ctx)
        mac = ctx.macro or {}
        if not mac.get("active") and not str(text).startswith(("raising:", "carving:")):
            if int(float(ctx.now) // EXPLAIN_ROTATE_S) % 2 == 0:
                return (EXPLAINER_LAND if _is_land_scene() else EXPLAINER_CAVE), L.COLORS["text"]
        return text, colour

    def _line2_inner(self, ctx) -> Tuple[str, str]:
        land = _land() is not None
        raise_w, raised_w, failed_w = ("raising", "raised", "raise") if land else ("carving", "carved", "carve")
        mac = ctx.macro or {}
        names_on = _names_on(ctx)
        kp = _keepers()
        if kp is not None and not mac.get("active"):
            # the keepers module's own line (a milestone carve on the cave; a raising / land opening on the land) outranks
            # the ships.jsonl line
            try:
                fn = getattr(kp, "raising_line", None) if land else getattr(kp, "carving_line", None)
                cl = fn(float(ctx.now), ctx=ctx) if callable(fn) else None
                if cl is not None:
                    return L.strip_non_bmp(cl["line"] if isinstance(cl, dict) else str(cl)), L.COLORS["text"]
                lc = getattr(kp, "last_raised", None) if land else getattr(kp, "last_carved", None)
                if lc is not None and ctx.now - float(lc.get("t") or 0) < 600.0:
                    who = _shown(lc.get("by")) if (names_on and lc.get("by")) else None
                    tail = (" · opened by @%s's arrival" % who) if who else ""
                    return ("last %s: %s · %s%s" % (raised_w, lc["name"], lc["version"], tail), L.COLORS["text"])
                if getattr(kp, "waiting", None) is not None:
                    # the land strip already says the land waits for a keeper; this strip shows the people instead
                    vis = self._visitors(ctx)
                    if vis:
                        return vis, L.COLORS["text2"]
                    return (WAITING_LAND if land else WAITING_CAVE), L.COLORS["text2"]
            except Exception:
                pass
        if mac.get("active"):
            title = L.strip_non_bmp(str(mac.get("title") or ("a new raising" if land else "a new chamber")))
            who = _shown(mac.get("requested_by")) if names_on else None
            dl = iso_to_epoch(mac.get("deadline_ts"))
            rem = None if dl is None else int(dl - ctx.now)
            tail = (" · %s left" % _mmss(rem)) if (rem is not None and rem >= 0) else (" · overdue" if rem is not None else "")
            return "%s: %s%s%s" % (raise_w, title, (" · asked by @%s" % who) if who else "", tail), L.COLORS["text"]
        last = self._last_macro(ctx)
        if last is not None:
            title = L.strip_non_bmp(str(last.get("title") or "macro-ship"))
            ver = last.get("version") or ""
            who = _shown(last.get("requested_by") or last.get("picked_by")) if names_on else None
            ok = last.get("ok") is not False
            head = ("last %s" % raised_w) if ok else ("last %s failed" % failed_w)
            return ("%s: %s%s%s" % (head, title, (" · %s" % ver) if ver else "", (" · asked by @%s" % who) if who else ""),
                    L.COLORS["text"] if ok else L.COLORS["warn"])
        vis = self._visitors(ctx) if not self._fresh(ctx) else None
        if vis:
            return vis, L.COLORS["text2"]
        return (IDEA_HINT_LAND if land else IDEA_HINT_CAVE), L.COLORS["text2"]

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

    def lines(self, ctx):
        """The exact strings drawn: ((line1, colour), (line2, colour), fail_lines, land: bool) -- the test surface.
        Memoised per (ctx.now, ctx.frame): inputs() and render() share one computation a frame."""
        memo_key = (ctx.now, ctx.frame, ctx.chat_display, ctx.preset)
        memo = getattr(self, "_memo", None)
        if memo is not None and memo[0] == memo_key:
            return memo[1]
        out = (self._line1(ctx), self._line2(ctx), tuple(self._failure(ctx)), _is_land_scene())
        self._memo = (memo_key, out)
        return out

    def inputs(self, ctx):
        return self.lines(ctx) + (ctx.preset,)

    def render(self, ctx, size):
        w, h = size
        img = self.base(size)
        d = ImageDraw.Draw(img)
        maxw = w - 2 * L.PAD - 24                # the beacon / lantern glyph sits in the last 24 px
        (t1, c1), (t2, c2), fail, land = self.lines(ctx)
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
        lit = self._fresh(ctx)
        accent = L.preset(ctx.preset)["accent"]
        lx = w - L.PAD - 8
        if land:
            # the beacon (24 px): a post, an iron basket at the top, a flame only on the same honesty test as the scene's
            # beacon (a fresh keeper heartbeat); the post is banded like the atlas's
            d.line([(lx, 18), (lx, 44)], fill=L.COLORS["text2"], width=3)
            d.line([(lx - 6, 44), (lx + 6, 44)], fill=L.COLORS["text2"], width=2)
            d.rectangle([lx - 7, 8, lx + 7, 18], fill=accent if lit else L.COLORS["hairline"], outline=L.COLORS["text2"], width=1)
            if lit:
                d.polygon([(lx - 3, 9), (lx, 2), (lx + 3, 9)], fill=L.COLORS["text"])
                d.rectangle([lx - 1, 28, lx + 1, 30], fill=accent)
        else:
            # the cave's lantern on a chain (rollback week)
            for yy in (6, 10, 14):
                d.point((lx, yy), fill=L.COLORS["text2"])
            d.polygon([(lx - 7, 22), (lx + 7, 22), (lx + 4, 17), (lx - 4, 17)], fill=L.COLORS["text2"])
            d.rectangle([lx - 6, 23, lx + 6, 37], fill=accent if lit else L.COLORS["hairline"], outline=L.COLORS["text2"], width=1)
            if lit:
                d.rectangle([lx - 2, 27, lx + 2, 33], fill=L.COLORS["text"])
            d.line([(lx - 7, 39), (lx + 7, 39)], fill=L.COLORS["text2"], width=2)
        return img


register(KeeperPanel())
