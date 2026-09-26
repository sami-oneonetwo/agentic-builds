"""stream/panels/colony.py - THE LAND strip (OPENWORLD.md 8 row 6; HUD pass 2026-09-26, journal 028): region `land`,
0,522,720,198. One strip under the land instead of three (colony + keeper + ticker): a caption, not a dashboard.

  row 1  HN Medium 24  text   (16,12)   `2 have walked here · 1 more and the cairn is named` / `17 have walked here ·
                                        8 more until the Coast opens` / `17 have walked here` / `nobody has walked here
                                        yet` / warn `3 have walked here · the keepers name the cairn next session` /
                                        `3 have walked here · the keepers are naming the cairn`. THE one home of the
                                        headcount (len(real pip rows that hatched)); no `day N`, no bar.
  row 2  HN Medium 22  text   (16,50)   `AI keepers build this show live from chat's ideas` -- STATIC, every frame (the
                                        owner had to ask in chat what the keepers are, journal 023).
  row 3  HN Medium 22         (16,80)   keeper state, the ONLY rotating text in the footer. Priority: failure (20 s,
                                        warn) `a raising failed · reverting to the last good version` > raising (pinned,
                                        accent) `raising the Ford bridge · asked by @moss_m · 12:40 left` > just raised
                                        (10 min, text) `just raised the Ford bridge · asked by @moss_m` > idle 10 s
                                        alternation (text2): heartbeat fresh `a keeper is on duty now · type !idea <what
                                        to raise>` / stale `no keeper on duty · your !idea waits on the board`,
                                        alternating at 0 awake with `2 sleep at their camps · last here: @atleastonce
                                        14:19`. No traceback text, no version string, no beacon glyph.
  rows 4-5 HN Medium 20 text2 (16,114) / (16,138)  the honesty line, VERBATIM OPENWORLD 12, split at the sentence break,
                                        STATIC every frame: `no camera, no mic, no fake viewers.` / `every name on this
                                        land is a real person in chat. the wind is just the wind.` (ADR-000). If a
                                        fallback font widens a row past 688 px it wraps to a third row, never truncates.

On the cave (no `land`: the rollback week) the same five rows carry the cave's words (`17 have hatched here`, WORLD.md 5
row 9 honesty line), so a panel-only hot-reload never changes the cave's meaning.

Every number is a len() the world computed over real records (test pips carry `_test` and are excluded by the
Land / WorldState); every name passes through the world panel's `shown_name()` (blocklist -> `builder #N`) and is
dropped under !kill. Nothing here is invented; an item that cannot be said whole is skipped, never chopped.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Tuple

from PIL import ImageDraw

from stream import layout as L
from stream.panels import Panel, register
from stream.state_store import iso_to_epoch
from stream.world import keepers as K          # cave chamber names (the Ledge, East Chamber, ...): one source, rollback week

ROTATE_S = 10.0
HEARTBEAT_FRESH_S = 120.0
FAIL_SHOW_S = 20.0
JUST_RAISED_S = 600.0
MAX_W = 688                                     # 720 - 2 * PAD
F1, F2, F4 = ("HN Medium", 24), ("HN Medium", 22), ("HN Medium", 20)
ROW_Y = (14, 56, 88, 130, 156)            # the 198 px strip (world 456): a row of air over the 174 px plan

KEEPERS_LINE_LAND = "AI keepers build this show live from chat's ideas"          # 482 px HN Medium 22
KEEPERS_LINE_CAVE = "AI keepers build this show live from chat's ideas"
HONESTY_LAND = ("no camera, no mic, no fake viewers.",                                 # 333 px HN Medium 20
                "every name on this land is a real person in chat. the wind is just the wind.")   # 675 px
HONESTY_CAVE = ("no camera, no mic, no fake viewers.", "every light in this cave is a real person.")
ON_DUTY = "a keeper is on duty now · type !idea <what to raise>"                        # 516 px (journal 030: `one is on duty` had no subject)
OFF_DUTY = "no keeper on duty · your !idea waits on the board"                          # 493 px
FAILED = "a raising failed · reverting to the last good version"                       # 494 px
FAILED_CAVE = "a carving failed · reverting to the last good version"

# head-count ladder on the land (OPENWORLD 4.1, 10): what each milestone does. `until` completes `N more <until>`
# (`and the cairn is named` / `until the Coast opens`); `doing` while the keepers act on a reached milestone; `waiting`
# while it waits for a keeper. Longest form first; every form has a shorter fallback. Milestones the world file carries
# that are not listed here read `N more until the land grows`.
LAND_LADDER: Dict[int, Dict[str, Any]] = {
    3:  {"until": ("and the cairn is named", "until the cairn is named"),
         "doing": ("the keepers are naming the cairn", "keepers naming the cairn"),
         "waiting": ("the keepers name the cairn next session", "the cairn is named next session")},
    5:  {"until": ("and the hearth ring rises", "until the hearth ring"),
         "doing": ("the keepers are raising the hearth ring", "keepers raising the hearth ring"),
         "waiting": ("the keepers raise the hearth ring next session", "the hearth ring rises next session")},
    10: {"until": ("until the Coast opens",),
         "doing": ("the keepers are opening the Coast",),
         "waiting": ("the keepers open the Coast next session", "the Coast opens next session")},
    25: {"until": ("until the Birch Wood opens",),
         "doing": ("the keepers are opening the Birch Wood",),
         "waiting": ("the keepers open the Birch Wood next session", "the Birch Wood opens next session")},
    50: {"until": ("until the Tarn opens",),
         "doing": ("the keepers are opening the Tarn",),
         "waiting": ("the keepers open the Tarn next session", "the Tarn opens next session")},
}
LADDER_UNKNOWN = {"until": ("until the land grows",), "doing": ("the keepers are opening the land",),
                  "waiting": ("the keepers open more land next session", "more land opens next session")}


def _forms(v) -> Tuple[str, ...]:
    return tuple(v) if isinstance(v, (tuple, list)) else (str(v),)


def _mmss(sec) -> str:
    sec = max(0, int(sec))
    return "%02d:%02d" % (sec // 60, sec % 60)


def _world():
    """(scene, world panel module) once the scene has booted, else (None, None)."""
    m = sys.modules.get("stream.panels.world")
    sc = m.scene() if (m is not None and hasattr(m, "scene")) else None
    if sc is None or not getattr(sc, "booted", False):
        return None, None
    return sc, m


def _land(sc):
    """The Land (world.json schema 2) the scene draws, or None on the cave."""
    return getattr(sc, "land", None) if sc is not None else None


def _shown(m, raw) -> Optional[str]:
    try:
        return m.shown_name(raw) if m is not None else None
    except Exception:
        return None


def _names_on(ctx) -> bool:
    if ctx.chat_display is False:
        return False
    return (ctx.chat_cfg or {}).get("display") is not False


_WIDTHS: Dict[Tuple[str, int, str], int] = {}       # (font, size, text) -> px; the same lines are measured every frame


def _width(font: Tuple[str, int], text: str) -> int:
    key = (font[0], font[1], text)
    w = _WIDTHS.get(key)
    if w is None:
        w = L.text_width(font[0], font[1], text)
        if len(_WIDTHS) > 4000:
            _WIDTHS.clear()
        _WIDTHS[key] = w
    return w


def _fits(font: Tuple[str, int], text: str, maxw: int) -> bool:
    return _width(font, text) <= maxw


def _shortest_fit(font: Tuple[str, int], cands: List[str], maxw: int) -> str:
    """The first candidate (longest form first) that fits; the last one is the fallback (truncated at draw time).
    Only for lines that carry no name (a chopped name is never drawn: art-rules 5)."""
    for c in cands:
        if _fits(font, c, maxw):
            return c
    return cands[-1]


def _fit_or_none(font: Tuple[str, int], cands: List[str], maxw: int) -> Optional[str]:
    """The first candidate that fits, or None: an item that cannot be said whole is skipped, never chopped."""
    for c in cands:
        if c and _fits(font, c, maxw):
            return c
    return None


def honesty_rows(land: bool, maxw: int = MAX_W) -> List[str]:
    """The honesty line as drawn rows: the two spec rows, each wrapped further (never truncated) if a fallback font
    widens one past `maxw`. The founding rule is never cut (ADR-000)."""
    rows: List[str] = []
    for r in (HONESTY_LAND if land else HONESTY_CAVE):
        if _fits(F4, r, maxw):
            rows.append(r)
        else:
            rows.extend(L.wrap(F4[0], F4[1], r, maxw, 0))
    return rows


class ColonyPanel(Panel):
    key, region = "colony", "land"

    # ================================================================== shared
    @staticmethod
    def _keeper_fresh(ctx) -> bool:
        hb = iso_to_epoch((ctx.agent or {}).get("heartbeat_ts"))
        return hb is not None and (ctx.now - hb) < HEARTBEAT_FRESH_S

    @staticmethod
    def _ladder_state(sc) -> Tuple[int, Optional[int], int, bool]:
        """(hatched, next_milestone, prev_milestone, reached_but_not_recorded) from the world's real ladder rows."""
        w = sc.world
        hatched = int(sc.hatched_ever())
        wd = w.data.get("world") or {}
        ladder = [int(m) for m in (wd.get("milestones") or [3, 5, 10, 25, 50])]
        reached = set(int(m) for m in (wd.get("milestones_reached") or []))
        prev, nxt = 0, None
        for m in ladder:
            if m in reached:
                prev = m
                continue
            nxt = m
            break
        waiting = nxt is not None and hatched >= nxt and nxt not in reached
        return hatched, nxt, prev, waiting

    @staticmethod
    def _keepers(m):
        try:
            return m.keepers() if (m is not None and hasattr(m, "keepers")) else None
        except Exception:
            return None

    # ================================================================== row 1: the headcount (the land)
    def _row1_land(self, sc, ctx) -> Tuple[str, Any]:
        hatched, nxt, prev, waiting = self._ladder_state(sc)
        accent = L.preset(ctx.preset)["accent"]
        if hatched == 0:
            return "nobody has walked here yet", L.COLORS["text"]
        head = "%d ha%s walked here" % (hatched, "s" if hatched == 1 else "ve")
        if nxt is None:
            return head, L.COLORS["text"]
        info = LAND_LADDER.get(int(nxt), LADDER_UNKNOWN)
        if waiting:
            kp = getattr(sc, "keepers", None)
            busy = getattr(kp, "raising", None) or getattr(kp, "opening", None) or getattr(kp, "carving", None)
            if busy or self._keeper_fresh(ctx):
                cands = ["%s · %s" % (head, f) for f in _forms(info["doing"])] + [head]
                return _shortest_fit(F1, cands, MAX_W), accent
            cands = ["%s · %s" % (head, f) for f in _forms(info["waiting"])] + [head]
            return _shortest_fit(F1, cands, MAX_W), L.COLORS["warn"]
        more = nxt - hatched
        cands = ["%s · %d more %s" % (head, more, f) for f in _forms(info["until"])] + [head]
        return _shortest_fit(F1, cands, MAX_W), L.COLORS["text"]

    def _row1_cave(self, sc, ctx) -> Tuple[str, Any]:
        hatched, nxt, prev, uncarved = self._ladder_state(sc)
        name = K.chamber_name(nxt) if nxt is not None else None
        accent = L.preset(ctx.preset)["accent"]
        head = "nobody has hatched here yet" if hatched == 0 else "%d ha%s hatched here" % (hatched, "s" if hatched == 1 else "ve")
        if nxt is None or hatched == 0:
            return head, L.COLORS["text"]
        if uncarved:
            if self._keeper_fresh(ctx):
                return _shortest_fit(F1, ["%s · the keepers are carving %s" % (head, name), head], MAX_W), accent
            return _shortest_fit(F1, ["%s · %s opens when a keeper is back" % (head, name), head], MAX_W), L.COLORS["warn"]
        return _shortest_fit(F1, ["%s · %d more until %s opens" % (head, nxt - hatched, name), head], MAX_W), L.COLORS["text"]

    # ================================================================== row 3: the keeper state
    def _visitors(self, sc, m, ctx, now: float) -> Optional[str]:
        """`2 sleep at their camps · last here: @atleastonce 14:19` from the world's real visits (0 awake only)."""
        if not _names_on(ctx):
            return None
        try:
            asleep = int(sc.asleep_count())
            visits = list((sc.world.data.get("world") or {}).get("visits") or [])[-3:]
            segs = []
            for v in reversed(visits):
                nm = m.shown_name(v.get("name"))
                if nm:
                    segs.append("@%s %s" % (nm, m.when_text(v.get("ts"), now)))
            head = ("%d sleep%s at %s camp%s" % (asleep, "s" if asleep == 1 else "", "its" if asleep == 1 else "their",
                                                  "" if asleep == 1 else "s")) if asleep else ""
            cands = []
            for n in range(len(segs), 0, -1):
                tail = "last here: " + " · ".join(segs[:n])
                cands.append((head + " · " + tail) if head else tail)
            if head:
                cands.append(head)
            return _fit_or_none(F2, cands, MAX_W)
        except Exception:
            return None

    @staticmethod
    def _last_macro(ctx):
        for s in reversed(list(ctx.ships or [])):
            if isinstance(s, dict) and s.get("kind") == "macro":
                return s
        return None

    def _failure(self, ctx, land: bool) -> bool:
        lr = (ctx.macro or {}).get("last_reload") or {}
        if not isinstance(lr, dict) or lr.get("ok") is not False:
            return False
        t = iso_to_epoch(lr.get("ts"))
        return t is not None and ctx.now - t <= FAIL_SHOW_S

    def _row3(self, sc, m, ctx, now: float, land: bool) -> Tuple[str, Any]:
        accent = L.preset(ctx.preset)["accent"]
        names_on = _names_on(ctx)
        raise_w = "raising" if land else "carving"
        raised_w = "raised" if land else "carved"
        # 1. failure (20 s): plain words, no traceback, no version
        if self._failure(ctx, land):
            return (FAILED if land else FAILED_CAVE), L.COLORS["warn"]
        # 2. a raising going up: pinned
        mac = ctx.macro or {}
        kp = self._keepers(m)
        if mac.get("active"):
            title = L.strip_non_bmp(str(mac.get("title") or ("a new raising" if land else "a new chamber")))
            who = _shown(m, mac.get("requested_by")) if names_on else None
            dl = iso_to_epoch(mac.get("deadline_ts"))
            rem = None if dl is None else int(dl - now)
            left = (" · %s left" % _mmss(rem)) if (rem is not None and rem >= 0) else (" · overdue" if rem is not None else "")
            cands = []
            if who:
                cands.append("%s %s · asked by @%s%s" % (raise_w, title, who, left))
            cands.append("%s %s%s" % (raise_w, title, left))
            cands.append("%s %s" % (raise_w, title))
            return _shortest_fit(F2, cands, MAX_W), accent
        if kp is not None:
            try:
                r = getattr(kp, "raising", None) if land else getattr(kp, "carving", None)
                if isinstance(r, dict) and r.get("name"):
                    left = max(0.0, float(r.get("t0") or now) + float(getattr(kp, "carve_s", 0.0) or 0.0) - now)
                    return _shortest_fit(F2, ["%s %s · %s left" % (raise_w, r["name"], _mmss(left)), "%s %s" % (raise_w, r["name"])], MAX_W), accent
                # 3. just raised (10 min)
                lc = getattr(kp, "last_raised", None) if land else getattr(kp, "last_carved", None)
                if isinstance(lc, dict) and lc.get("name") and now - float(lc.get("t") or 0) < JUST_RAISED_S:
                    who = _shown(m, lc.get("by")) if (names_on and lc.get("by")) else None
                    cands = (["just %s %s · asked by @%s" % (raised_w, lc["name"], who)] if who else []) + ["just %s %s" % (raised_w, lc["name"])]
                    return _fit_or_none(F2, cands, MAX_W) or cands[-1], L.COLORS["text"]
            except Exception:
                pass
        last = self._last_macro(ctx)
        if last is not None and last.get("ok") is not False:
            t = iso_to_epoch(last.get("ts"))
            if t is not None and now - t < JUST_RAISED_S:
                title = L.strip_non_bmp(str(last.get("title") or "a raising"))
                who = _shown(m, last.get("requested_by") or last.get("picked_by")) if names_on else None
                cands = (["just %s %s · asked by @%s" % (raised_w, title, who)] if who else []) + ["just %s %s" % (raised_w, title)]
                return _fit_or_none(F2, cands, MAX_W) or cands[-1], L.COLORS["text"]
        # 4. idle: the duty line, alternating (10 s) with the visitors line when nobody is awake
        duty = ON_DUTY if self._keeper_fresh(ctx) else OFF_DUTY
        if not land:
            duty = duty.replace("what to raise", "what to carve")
        items = [duty]
        try:
            if int(sc.awake_count()) == 0:
                vis = self._visitors(sc, m, ctx, now)
                if vis:
                    items.append(vis)
        except Exception:
            pass
        return items[int(now // ROTATE_S) % len(items)], L.COLORS["text2"]

    # ================================================================== model -> the five rows
    def lines(self, ctx) -> Optional[Dict[str, Any]]:
        """The exact strings the strip draws (also the cache key and the test surface): None before the scene boots.
        {"row1": (text, colour), "row2": text, "row3": (text, colour), "honesty": [rows], "land": bool}
        Memoised per (ctx.now, ctx.frame): inputs() and render() share one computation a frame."""
        memo_key = (ctx.now, ctx.frame, ctx.chat_display, ctx.preset)
        memo = getattr(self, "_memo", None)
        if memo is not None and memo[0] == memo_key:
            return memo[1]
        d = self._lines(ctx)
        self._memo = (memo_key, d)
        return d

    def _lines(self, ctx) -> Optional[Dict[str, Any]]:
        sc, m = _world()
        if sc is None:
            return None
        now = float(ctx.now or 0.0)
        land = _land(sc) is not None
        row1 = self._row1_land(sc, ctx) if land else self._row1_cave(sc, ctx)
        row3 = self._row3(sc, m, ctx, now, land)
        return {"row1": row1, "row2": KEEPERS_LINE_LAND if land else KEEPERS_LINE_CAVE, "row3": row3,
                "honesty": honesty_rows(land), "land": land}

    # ================================================================== panel
    def inputs(self, ctx):
        d = self.lines(ctx)
        if d is None:
            sc = None
            m = sys.modules.get("stream.panels.world")
            try:
                sc = m.scene() if (m is not None and hasattr(m, "scene")) else None
            except Exception:
                sc = None
            land = hasattr(sc, "land")
            # the same shape as a booted key: the keepers sentence and the honesty rows are drawn before boot too
            return (("boot", land), KEEPERS_LINE_LAND if land else KEEPERS_LINE_CAVE, ("", ""), tuple(honesty_rows(land)), ctx.preset)
        return (d["row1"], d["row2"], d["row3"], tuple(d["honesty"]), ctx.preset)

    def render(self, ctx, size):
        w, h = size
        img = self.base(size)
        d = ImageDraw.Draw(img)
        maxw = w - 2 * L.PAD
        f1, f2, f4 = L.font(*F1), L.font(*F2), L.font(*F4)
        lines = self.lines(ctx)
        land = True
        if lines is None:
            m = sys.modules.get("stream.panels.world")
            try:
                sc = m.scene() if (m is not None and hasattr(m, "scene")) else None
            except Exception:
                sc = None
            land = hasattr(sc, "land")
            d.text((L.PAD, ROW_Y[0]), "the land is waking…" if land else "the cave is waking…", font=f1, fill=L.COLORS["text2"])
            d.text((L.PAD, ROW_Y[1]), KEEPERS_LINE_LAND if land else KEEPERS_LINE_CAVE, font=f2, fill=L.COLORS["text"])
            rows = honesty_rows(land, maxw)
        else:
            land = lines["land"]
            t1, c1 = lines["row1"]
            d.text((L.PAD, ROW_Y[0]), L.truncate(F1[0], F1[1], t1, maxw), font=f1, fill=c1)
            d.text((L.PAD, ROW_Y[1]), L.truncate(F2[0], F2[1], lines["row2"], maxw), font=f2, fill=L.COLORS["text"])
            t3, c3 = lines["row3"]
            d.text((L.PAD, ROW_Y[2]), L.truncate(F2[0], F2[1], t3, maxw), font=f2, fill=c3)
            rows = lines["honesty"]
        # the honesty line: two static rows (a third only when a fallback font forces a wrap; never truncated)
        y = ROW_Y[3]
        for r in rows[:3]:
            d.text((L.PAD, y), r, font=f4, fill=L.COLORS["text2"])
            y += 24
        return img


register(ColonyPanel())
