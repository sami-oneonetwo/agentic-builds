"""stream/panels/colony.py - THE LAND strip (OPENWORLD.md 8 row 6; region key stays `colony`): 0,512,420,144.

On the land (the scene exposes a schema-2 `land`):
  line 1  HN Medium 22  `17 have walked here` (`nobody has walked here yet`), with the milestone caption on its own
          HN Medium 20  row: `day 6 · 8 more until the Coast opens`, over an 8 px bar (the real fraction of the way from
                        the last head-count milestone to the next; ladder = world.json `milestones` 3 5 10 25 50:
                        3 names the cairn, 5 raises the hearth ring, 10 / 25 / 50 open the Coast / the Birch Wood /
                        the Tarn). A milestone reached but not yet acted on: `land reached · keepers will open it next
                        session` (amber) when no keeper is on duty, `the keepers are opening the Coast` when one is.
                        `day 6` = len(distinct sessions the world has seen). `17` = len(real pip rows that hatched):
                        every one of them stood up on the Moot green and walked.
  line 2  Menlo 22      `3 awake · 14 asleep` + as many of ` · 6 camps`, ` · spring`, ` · 2 fields gold` as fit 388 px
                        (camps and gold fields only when > 0); whatever does not fit joins the rotation below.
  line 3  Menlo 20      8 s rotation: stone ladder `stone 13 of 20 · the Ford bridge · last by @kai` (only once a real
                        stone lies on the cairn), the last world event (round.last_result / world.event_log), the last
                        raising `the well · raised v0.7.0`, the last opened strip `the Coast · opened by @kai's arrival ·
                        v0.8.0`, the cairn plaque `the cairn · stones by @kai @sami`, the nightly board `last night:
                        @sami stacked 3 stones · @kai walked the farthest · 1 arrived · 2 fields went gold`, the facts
                        line 2 had no room for, and the `!stats` card for 10 s (ctx.stats_until).

On the cave (no `land`: PIP HOLLOW still on air, or the rollback week) every line keeps the WORLD.md 5 row 6 copy
(`17 have hatched here`, chambers, `fed / dug` board), so a panel-only hot-reload never changes the cave's words.

Every number is a len() the world computed over real records (test pips carry `_test` and are excluded by the
Land / WorldState); every name passes through the world panel's `shown_name()` (blocklist -> `builder #N`) and is
dropped under !kill. Nothing here is invented; an empty item is skipped, not filled.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Tuple

from PIL import ImageDraw

from stream import layout as L
from stream.panels import Panel, register
from stream.state_store import iso_to_epoch
from stream.world import keepers as K          # cave chamber names (the Ledge, East Chamber, ...): one source, rollback week

ROTATE_S = 8.0
STATS_S = 10.0
BAR_H = 8
F1, F1B, F2, F3 = ("HN Medium", 22), ("HN Medium", 20), ("Menlo", 22), ("Menlo", 20)

# head-count ladder on the land (OPENWORLD 4.1, 10): what each milestone does. `until` completes `N more until ...`;
# `doing` is the caption while the keepers act on a reached milestone; `waiting` (long form first) while it waits for
# a keeper. The caption row is HN Medium 20 over 388 px (~40 glyphs), so every form has a shorter fallback and the
# `day N ·` prefix is the first thing dropped. Milestones the world file carries that are not listed here read
# `N more until the land grows`.
LAND_LADDER: Dict[int, Dict[str, Any]] = {
    3:  {"until": ("the cairn is named", "the cairn's name"),
         "doing": ("the keepers are naming the cairn", "keepers naming the cairn"),
         "waiting": ("milestone reached · the cairn is named next session", "the cairn is named next session")},
    5:  {"until": ("the hearth ring rises", "the hearth ring"),
         "doing": ("the keepers are raising the hearth ring", "keepers raising the hearth ring"),
         "waiting": ("milestone reached · the hearth ring rises next session", "the hearth ring rises next session")},
    10: {"until": ("the Coast opens",),
         "doing": ("the keepers are opening the Coast",),
         "waiting": ("land reached · keepers will open it next session", "land reached · the Coast opens next session",
                     "the Coast opens next session")},
    25: {"until": ("the Birch Wood opens",),
         "doing": ("the keepers are opening the Birch Wood",),
         "waiting": ("land reached · keepers will open it next session", "the Birch Wood opens next session")},
    50: {"until": ("the Tarn opens",),
         "doing": ("the keepers are opening the Tarn",),
         "waiting": ("land reached · keepers will open it next session", "the Tarn opens next session")},
}
LADDER_UNKNOWN = {"until": ("the land grows",), "doing": ("the keepers are opening the land",),
                  "waiting": ("land reached · keepers will open it next session", "more land opens next session")}


def _forms(v) -> Tuple[str, ...]:
    return tuple(v) if isinstance(v, (tuple, list)) else (str(v),)


def caption_forms(day: Optional[str], more: int, info: Dict[str, Any]) -> List[str]:
    """`day 6 · 8 more until the Coast opens` -> `8 more until the Coast opens` -> the shorter `until`."""
    out = []
    for u in _forms(info["until"]):
        if day:
            out.append("%s · %d more until %s" % (day, more, u))
        out.append("%d more until %s" % (more, u))
    return out


def waiting_forms(day: Optional[str], info: Dict[str, Any]) -> List[str]:
    out = []
    for w in _forms(info["waiting"]):
        if day:
            out.append("%s · %s" % (day, w))
        out.append(w)
    return out


def doing_form(day: Optional[str], info: Dict[str, Any], name: Optional[str] = None) -> List[str]:
    out = []
    forms = ("the keepers are raising %s" % name, "keepers raising %s" % name) if name else _forms(info["doing"])
    for w in forms:
        if day:
            out.append("%s · %s" % (day, w))
        out.append(w)
    return out
EMPTY_LINE_LAND = "every name on this land is a real person."
EMPTY_LINE_CAVE = "every light is a real person."


def _ordinal(n: int) -> str:
    n = int(n)
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "%d%s" % (n, suf)


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


def _join_fit(font: Tuple[str, int], head: str, parts: List[str], maxw: int, sep: str = " · ") -> Tuple[str, List[str]]:
    """`head` plus as many of `parts` (in order) as fit; -> (line, the parts that did not fit)."""
    line, rest = head, []
    for i, p in enumerate(parts):
        cand = (line + sep + p) if line else p
        if rest or not _fits(font, cand, maxw):
            rest.append(p)
        else:
            line = cand
    return line, rest


class ColonyPanel(Panel):
    key, region = "colony", "colony"

    # ================================================================== shared
    @staticmethod
    def _keeper_fresh(ctx) -> bool:
        hb = iso_to_epoch((ctx.agent or {}).get("heartbeat_ts"))
        return hb is not None and (ctx.now - hb) < 120.0

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

    def _last_result_item(self, m, ctx, names_on: bool, maxw: Optional[int] = None) -> Optional[Tuple[str, Any]]:
        """The last round's result: `rain · picked by @sami · v0.6.1`, shortened (drop the version, then the picker,
        then cut the title) so the picker's name is never chopped."""
        res = (ctx.round or {}).get("last_result") or {}
        title = L.strip_non_bmp(str(res.get("title") or ""))
        if not title:
            return None
        maxw = maxw if maxw is not None else L.region_size(self.region)[0] - 2 * L.PAD
        ver = res.get("version") or (ctx.version or {}).get("string") or ""
        by = _shown(m, res.get("picked_by")) if names_on else None
        cut = L.truncate(F3[0], F3[1], title, maxw)          # a long title (the platform's own string) is cut, never a name
        if res.get("agent_pick"):
            cands = ["%s · nobody voted · %s" % (title, ver), "%s · nobody voted" % title, cut]
            return (_shortest_fit(F3, cands, maxw), L.COLORS["text2"])
        if by:
            cands = ["%s · picked by @%s · %s" % (title, by, ver), "%s · picked by @%s" % (title, by), "%s · @%s" % (title, by)]
            fit = _fit_or_none(F3, cands, maxw)
            if fit:
                return (fit, L.COLORS["text"])
        return (_shortest_fit(F3, ["%s · %s" % (title, ver), cut], maxw), L.COLORS["text"])

    @staticmethod
    def _event_item(sc, maxw: Optional[int] = None) -> Optional[Tuple[str, Any]]:
        """The world's last event line (free text the world wrote). A line that does not fit is drawn cut only when it
        carries no name; one with a name is skipped rather than chopped."""
        wd = sc.world.data.get("world") or {}
        ev = list(wd.get("event_log") or [])
        if ev and isinstance(ev[-1], dict) and ev[-1].get("text"):
            text = L.strip_non_bmp(str(ev[-1]["text"]))
            if maxw is not None and "@" in text and not _fits(F3, text, maxw):
                return None
            return (text, L.COLORS["text2"])
        return None

    def _line3(self, items: List[Tuple[str, Any]], ctx, now: float, stats: str) -> Tuple[str, Any]:
        if ctx.stats_until and now < float(ctx.stats_until):
            return stats, L.COLORS["text"]
        return items[int(now // ROTATE_S) % len(items)]

    # ================================================================== the land (schema 2)
    def _land_line1(self, sc, land, ctx) -> Tuple[str, str, float, Any]:
        """(headline, caption, bar fraction, caption colour)."""
        hatched, nxt, prev, waiting = self._ladder_state(sc)
        accent = L.preset(ctx.preset)["accent"]
        if hatched == 0:
            head = "nobody has walked here yet"
        else:
            head = "%d ha%s walked here" % (hatched, "s" if hatched == 1 else "ve")
        day = "day %d" % int(land.days) if int(land.days) > 0 else None
        maxw = L.region_size(self.region)[0] - 2 * L.PAD
        if nxt is None:
            cands = ["%s · every strip of land is open" % day, "every strip of land is open"] if day else ["every strip of land is open"]
            return (head, _shortest_fit(F1B, cands, maxw), 1.0, L.COLORS["text2"])
        info = LAND_LADDER.get(int(nxt), LADDER_UNKNOWN)
        if waiting:
            kp = getattr(sc, "keepers", None)
            busy = getattr(kp, "raising", None) or getattr(kp, "opening", None) or getattr(kp, "carving", None)
            if busy or self._keeper_fresh(ctx):
                name = L.strip_non_bmp(str(busy["name"])) if (isinstance(busy, dict) and busy.get("name")) else None
                return (head, _shortest_fit(F1B, doing_form(day, info, name), maxw), 1.0, accent)
            return (head, _shortest_fit(F1B, waiting_forms(day, info), maxw), 1.0, L.COLORS["warn"])
        more = nxt - hatched
        frac = (hatched - prev) / float(max(1, nxt - prev))
        return (head, _shortest_fit(F1B, caption_forms(day, more, info), maxw), max(0.0, min(1.0, frac)), L.COLORS["text2"])

    def _land_line2(self, sc, land, ctx, now: float, maxw: int) -> Tuple[str, List[str]]:
        """`3 awake · 14 asleep · 6 camps · spring · 2 fields gold` as far as it fits; the rest -> rotation items."""
        awake, asleep = int(sc.awake_count()), int(sc.asleep_count())
        c = land.counts(now)
        parts: List[str] = []
        if c.get("camps"):
            parts.append("%d camp%s" % (c["camps"], "" if c["camps"] == 1 else "s"))
        season = self._season(sc, now)
        if season:
            parts.append(season)
        if c.get("fields_gold"):
            parts.append("%d field%s gold" % (c["fields_gold"], "" if c["fields_gold"] == 1 else "s"))
        line, rest = _join_fit(F2, "%d awake · %d asleep" % (awake, asleep), parts, maxw)
        # a fact that moves to the rotation reads as a sentence on its own (`spring on Longgrass`, not a bare `spring`)
        rest = [("%s on Longgrass" % p) if p == season else p for p in rest]
        return line, rest

    @staticmethod
    def _season(sc, now: float) -> Optional[str]:
        nat = getattr(sc, "nature", None)
        if nat is None:
            return None
        try:
            return str(nat.describe(now).get("season") or "") or None
        except Exception:
            return None

    def _land_items(self, sc, land, m, ctx, now: float, maxw: int, extra: List[str]) -> List[Tuple[str, Any]]:
        names_on = _names_on(ctx)
        items: List[Tuple[str, Any]] = []
        if extra:
            items.append((" · ".join(extra), L.COLORS["text"]))
        # stone ladder: only once a real stone lies on the cairn (a `0 of 20` would advertise a verb nobody used)
        try:
            lad = land.ladder()
        except Exception:
            lad = {"stock": 0}
        if int(lad.get("stock") or 0) > 0 and lad.get("next"):
            base = "stone %d of %d" % (int(lad["stock"]), int(lad["next"]))
            name = lad.get("name")
            by = _shown(m, lad.get("last_by")) if (names_on and lad.get("last_by")) else None
            cands = []
            if name and by:
                cands.append("%s · %s · last by @%s" % (base, name, by))
            if name:
                cands.append("%s · %s" % (base, name))
            if by:
                cands.append("%s · last by @%s" % (base, by))
            cands.append(base)
            items.append((_shortest_fit(F3, cands, maxw), L.COLORS["text"]))
        it = self._last_result_item(m, ctx, names_on, maxw)
        if it:
            items.append(it)
        it = self._event_item(sc, maxw)
        if it:
            items.append(it)
        # the last raising / the last opened strip (keeper ships recorded on the land)
        try:
            rs = list(land.raisings)
        except Exception:
            rs = []
        if rs and isinstance(rs[-1], dict) and rs[-1].get("name"):
            r = rs[-1]
            ver = str(r.get("version") or "")
            items.append(("%s · raised%s" % (L.strip_non_bmp(str(r["name"])), (" " + ver) if ver else ""), L.COLORS["text"]))
        try:
            strips = list(land.land_strips)
        except Exception:
            strips = []
        if strips and isinstance(strips[-1], dict):
            s = strips[-1]
            nm = L.strip_non_bmp(str(s.get("biome") or s.get("name") or "new land"))
            by = _shown(m, s.get("by")) if (names_on and s.get("by")) else None
            ver = str(s.get("version") or "")
            vtail = (" · " + ver) if ver else ""
            cands = []
            if by:
                cands += ["%s · opened by @%s's arrival%s" % (nm, by, vtail), "%s · opened by @%s%s" % (nm, by, vtail),
                          "%s · opened by @%s" % (nm, by)]
            cands += ["%s · opened%s" % (nm, vtail), "%s · opened" % nm]
            fit = _fit_or_none(F3, cands, maxw)
            if fit:
                items.append((fit, L.COLORS["text"]))
        # the cairn plaque: the top stackers by count (distinct real people); fewer names before a shorter prefix,
        # never a chopped name
        if names_on and int(lad.get("stock") or 0) > 0:
            try:
                plaque = land.plaque("moot", 3)
            except Exception:
                plaque = []
            names = [n for n in (_shown(m, k) for k, _n in plaque) if n]
            cands = []
            for k in range(len(names), 0, -1):
                cands.append("the cairn · stones by " + " ".join("@" + n for n in names[:k]))
            for k in range(len(names), 0, -1):
                cands.append("cairn · stones by " + " ".join("@" + n for n in names[:k]))
            fit = _fit_or_none(F3, cands, maxw)
            if fit:
                items.append((fit, L.COLORS["text2"]))
        it = self._land_board(sc, m, names_on, maxw)
        if it:
            items.append(it)
        if not items:
            items.append((EMPTY_LINE_LAND, L.COLORS["text2"]))
        return items

    @staticmethod
    def _land_board(sc, m, names_on: bool, maxw: int) -> Optional[Tuple[str, Any]]:
        """`last night: @sami stacked 3 stones · @kai walked the farthest · 1 arrived · 2 fields went gold` from the
        world's last_board (only the keys it really has; the longest prefix that fits)."""
        wd = sc.world.data.get("world") or {}
        lb = wd.get("last_board")
        if not isinstance(lb, dict):
            return None
        facts: List[List[str]] = []               # each fact: its forms, longest first; a fact that fits in no form is skipped

        def top(d):
            d = d or {}
            if not isinstance(d, dict) or not d:
                return None, 0
            k, v = max(d.items(), key=lambda kv: kv[1])
            return k, v

        if names_on:
            k, v = top(lb.get("stacked"))
            nm = _shown(m, k) if k else None
            if nm:
                s = "" if int(v) == 1 else "s"
                facts.append(["@%s stacked %d stone%s" % (nm, int(v), s), "@%s · %d stone%s" % (nm, int(v), s)])
            k, v = top(lb.get("walked"))
            nm = _shown(m, k) if k else None
            if nm:
                facts.append(["@%s walked the farthest" % nm, "@%s walked farthest" % nm])
            k, v = top(lb.get("fed"))
            nm = _shown(m, k) if k else None
            if nm:
                facts.append(["@%s fed %d pip%s" % (nm, int(v), "" if int(v) == 1 else "s")])
        arrived = lb.get("hatched") or lb.get("arrived") or []
        if isinstance(arrived, list) and arrived:
            facts.append(["%d arrived" % len(arrived)])
        gold = lb.get("gold") or lb.get("fields_gold") or []
        n_gold = len(gold) if isinstance(gold, list) else int(gold or 0)
        if n_gold:
            facts.append(["%d field%s went gold" % (n_gold, "" if n_gold == 1 else "s"), "%d gold" % n_gold])
        if not facts:
            return None
        line, n = "last night:", 0
        for forms in facts:                          # greedy: the longest form of each fact that still fits; skip, never chop
            for f in forms:
                cand = line + (" " if n == 0 else " · ") + f
                if _fits(F3, cand, maxw):
                    line, n = cand, n + 1
                    break
        if n == 0:
            return None
        return (line, L.COLORS["text2"])

    def _land_stats(self, sc, land, ctx, now: float, maxw: int) -> str:
        """`!stats` card: chat figures + land len()s, progressively shorter until it fits."""
        cs = ctx.chat_stats or {}
        rate, ppl = cs.get("msgs_per_min_5m"), cs.get("unique_chatters_5m")
        try:
            rate_s = "%.1f" % float(rate) if rate is not None else "--"
        except Exception:
            rate_s = "--"
        ppl_s = "--" if ppl is None else str(ppl)
        ver = (ctx.version or {}).get("string") or ""
        c = land.counts(now)
        walked, camps, awake = int(sc.hatched_ever()), int(c.get("camps") or 0), int(sc.awake_count())
        pct = int(c.get("walked_pct") or 0)
        # `!stats` asked for the card, so the shorter forms may drop the `stats:` prefix before they drop a number
        cands = ["stats: %s/min · %s ppl · %d walked · %d camps · %d %% walked · %s" % (rate_s, ppl_s, walked, camps, pct, ver),
                 "stats: %s/min · %s ppl · %d walked · %d camps · %s" % (rate_s, ppl_s, walked, camps, ver),
                 "%s/min · %s ppl · %d walked · %d camps · %d %% walked" % (rate_s, ppl_s, walked, camps, pct),
                 "%s/min · %s ppl · %d walked · %d camps" % (rate_s, ppl_s, walked, camps),
                 "%s/min · %s ppl · %d walked · %d awake" % (rate_s, ppl_s, walked, awake),
                 "%s/min · %s ppl · %d walked" % (rate_s, ppl_s, walked),
                 "stats: %s/min · %d walked" % (rate_s, walked)]
        return _shortest_fit(F3, cands, maxw)

    # ================================================================== the cave (schema 1, rollback week)
    def _cave_line1(self, sc, ctx) -> Tuple[str, str, float, Any]:
        hatched, nxt, prev, uncarved = self._ladder_state(sc)
        name = K.chamber_name(nxt) if nxt is not None else None
        accent = L.preset(ctx.preset)["accent"]
        head = "nobody has hatched here yet" if hatched == 0 else "%d ha%s hatched here" % (hatched, "s" if hatched == 1 else "ve")
        if nxt is None:
            return (head, "every chamber is open", 1.0, L.COLORS["text2"])
        if uncarved:
            kp = getattr(sc, "keepers", None)
            carving = getattr(kp, "carving", None)
            if carving:
                return (head, "the keepers are carving %s" % (carving.get("name") or name), 1.0, accent)
            if self._keeper_fresh(ctx):
                return (head, "the keepers are carving %s" % name, 1.0, accent)
            return (head, "%s opens when a keeper is back" % name, 1.0, L.COLORS["warn"])
        more = nxt - hatched
        frac = (hatched - prev) / float(max(1, nxt - prev))
        return (head, "%d more until %s opens" % (more, name), max(0.0, min(1.0, frac)), L.COLORS["text2"])

    def _cave_line2(self, sc, m, ctx, maxw: int) -> Tuple[str, List[str]]:
        awake, asleep = sc.awake_count(), sc.asleep_count()
        s = "%d awake · %d asleep" % (awake, asleep)
        night = None
        if _names_on(ctx):
            key = getattr(sc.behaviour, "newest_speaker", None)
            ent = sc.behaviour.get(key) if key else None
            if ent is not None and ent.is_awake():
                p = sc.world.pip(key) or {}
                nm = _shown(m, key)
                if nm:
                    n_night = max(1, int(p.get("sessions_seen") or 1))
                    night = ("@%s's first night" % nm) if n_night == 1 else ("@%s's %s night" % (nm, _ordinal(n_night)))
        if night and _fits(F2, s + " · " + night, maxw):
            return s + " · " + night, []
        return s, ([night] if night else [])

    def _cave_items(self, sc, m, ctx, extra: List[str]) -> List[Tuple[str, Any]]:
        names_on = _names_on(ctx)
        items: List[Tuple[str, Any]] = []
        if extra:
            items.append((" · ".join(extra), L.COLORS["text"]))
        it = self._last_result_item(m, ctx, names_on)
        if it:
            items.append(it)
        it = self._event_item(sc)
        if it:
            items.append(it)
        wd = sc.world.data.get("world") or {}
        lb = wd.get("last_board") or None
        if isinstance(lb, dict) and names_on:
            parts = []
            fed = lb.get("fed") or {}
            if fed:
                top = max(fed.items(), key=lambda kv: kv[1])
                nm = _shown(m, top[0])
                if nm:
                    parts.append("@%s fed %d pip%s" % (nm, int(top[1]), "" if int(top[1]) == 1 else "s"))
            dug = lb.get("dug") or {}
            if dug:
                top = max(dug.items(), key=lambda kv: kv[1])
                nm = _shown(m, top[0])
                if nm:
                    parts.append("@%s dug the most" % nm)
            hatched = lb.get("hatched") or []
            if hatched:
                parts.append("%d hatched" % len(hatched))
            if parts:
                items.append(("last night: " + " · ".join(parts), L.COLORS["text2"]))
        if not items:
            items.append((EMPTY_LINE_CAVE, L.COLORS["text2"]))
        return items

    def _cave_stats(self, sc, ctx, maxw: int) -> str:
        cs = ctx.chat_stats or {}
        rate, ppl = cs.get("msgs_per_min_5m"), cs.get("unique_chatters_5m")
        try:
            rate_s = "%.1f" % float(rate) if rate is not None else "--"
        except Exception:
            rate_s = "--"
        ppl_s = "--" if ppl is None else str(ppl)
        ver = (ctx.version or {}).get("string") or ""
        hatched, awake = int(sc.hatched_ever()), int(sc.awake_count())
        cands = ["stats: %s/min · %s ppl · %d hatched · %d awake · %s" % (rate_s, ppl_s, hatched, awake, ver),
                 "stats: %s/min · %s ppl · %d hatched · %s" % (rate_s, ppl_s, hatched, ver),
                 "stats: %s/min · %s ppl · %d hatched" % (rate_s, ppl_s, hatched),
                 "stats: %s/min · %d hatched" % (rate_s, hatched)]
        return _shortest_fit(F3, cands, maxw)

    # ================================================================== model -> the three lines
    def lines(self, ctx, maxw: int = 388) -> Optional[Dict[str, Any]]:
        """The exact strings the strip draws (also the cache key and the test surface): None before the scene boots.
        {"head", "caption", "frac", "caption_colour", "line2", "line3", "line3_colour", "land": bool}
        Memoised per (ctx.now, ctx.frame, maxw): inputs() and render() share one computation a frame."""
        memo_key = (ctx.now, ctx.frame, maxw, ctx.chat_display, ctx.stats_until)
        memo = getattr(self, "_memo", None)
        if memo is not None and memo[0] == memo_key:
            return memo[1]
        d = self._lines(ctx, maxw)
        self._memo = (memo_key, d)
        return d

    def _lines(self, ctx, maxw: int) -> Optional[Dict[str, Any]]:
        sc, m = _world()
        if sc is None:
            return None
        now = float(ctx.now or 0.0)
        land = _land(sc)
        if land is not None:
            head, cap, frac, c1 = self._land_line1(sc, land, ctx)
            l2, extra = self._land_line2(sc, land, ctx, now, maxw)
            items = self._land_items(sc, land, m, ctx, now, maxw, extra)
            t3, c3 = self._line3(items, ctx, now, self._land_stats(sc, land, ctx, now, maxw))
        else:
            head, cap, frac, c1 = self._cave_line1(sc, ctx)
            l2, extra = self._cave_line2(sc, m, ctx, maxw)
            items = self._cave_items(sc, m, ctx, extra)
            t3, c3 = self._line3(items, ctx, now, self._cave_stats(sc, ctx, maxw))
        return {"head": head, "caption": cap, "frac": round(float(frac), 3), "caption_colour": c1, "line2": l2,
                "line3": t3, "line3_colour": c3, "land": land is not None}

    # ================================================================== panel
    def inputs(self, ctx):
        d = self.lines(ctx, L.region_size(self.region)[0] - 2 * L.PAD)
        if d is None:
            sc = None
            m = sys.modules.get("stream.panels.world")
            try:
                sc = m.scene() if (m is not None and hasattr(m, "scene")) else None
            except Exception:
                sc = None
            return ("boot", hasattr(sc, "land"), ctx.preset)
        return (d["head"], d["caption"], d["frac"], d["caption_colour"], d["line2"], d["line3"], d["line3_colour"], ctx.preset)

    def render(self, ctx, size):
        w, h = size
        img = self.base(size)
        d = ImageDraw.Draw(img)
        accent = L.preset(ctx.preset)["accent"]
        maxw = w - 2 * L.PAD
        f1, f1b, f2, f3 = L.font(*F1), L.font(*F1B), L.font(*F2), L.font(*F3)
        lines = self.lines(ctx, maxw)
        if lines is None:
            m = sys.modules.get("stream.panels.world")
            try:
                sc = m.scene() if (m is not None and hasattr(m, "scene")) else None
            except Exception:
                sc = None
            d.text((L.PAD, 12), "the land is waking…" if hasattr(sc, "land") else "the cave is waking…", font=f1, fill=L.COLORS["text2"])
            return img
        d.text((L.PAD, 6), L.truncate(F1[0], F1[1], lines["head"], maxw), font=f1, fill=L.COLORS["text"])
        d.text((L.PAD, 32), L.truncate(F1B[0], F1B[1], lines["caption"], maxw), font=f1b, fill=lines["caption_colour"])
        # 8 px bar (hairline track, fill = the real fraction; amber while a reached milestone waits for a keeper)
        by = 58
        d.rectangle([L.PAD, by, L.PAD + maxw - 1, by + BAR_H - 1], fill=L.COLORS["hairline"])
        fw = int(round(maxw * lines["frac"]))
        if fw > 0:
            fill = L.COLORS["warn"] if lines["caption_colour"] == L.COLORS["warn"] else accent
            d.rectangle([L.PAD, by, L.PAD + fw - 1, by + BAR_H - 1], fill=fill)
        d.text((L.PAD, 76), L.truncate(F2[0], F2[1], lines["line2"], maxw), font=f2, fill=L.COLORS["text"])
        d.text((L.PAD, 110), L.truncate(F3[0], F3[1], lines["line3"], maxw), font=f3, fill=lines["line3_colour"])
        return img


register(ColonyPanel())
