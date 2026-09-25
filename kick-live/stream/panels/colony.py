"""stream/panels/colony.py - COLONY strip (WORLD.md 5 row 6): 0,512,420,144.

  line 1  HN Medium 22  `17 have hatched here` (`nobody has hatched here yet`), with the milestone caption on its own
          HN Medium 20  row: `3 more until the Pool opens`, over an 8 px bar (real fraction of the way from the last
                        milestone to the next; the ladder is world.json `milestones` = 3 5 10 25 50). A milestone
                        reached but not yet carved: `milestone 10 reached · carved next session` (amber) when no keeper
                        is on duty, or `milestone 10 reached · the keepers are carving` when one is.
                        (The spec's one-line form measures 512 px at 22 px; the strip is 420 wide, hence two rows.)
  line 2  Menlo 22      `3 awake · 14 asleep` + ` · night 4 for @sami` when it fits 388 px, otherwise that fact joins
                        the rotation (the newest speaker's real sessions_seen; no name under !kill).
  line 3  Menlo 20      8 s rotation: last world event (`glow-rain · picked by @sami · v0.5.3` from round.last_result /
                        world.event_log), the nightly board from world.last_board (`last night: @sami fed 6 pips ·
                        @kai dug the most · 1 hatched`), `night 4 for @sami` when line 2 had no room, and the `!stats`
                        card for 10 s (ctx.stats_until).

Every number is a len() the world computed over real records; every name passes through the world panel's
`shown_name()` (blocklist -> `builder #N`). Nothing here is invented; an empty item is skipped, not filled.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Tuple

from PIL import ImageDraw

from stream import layout as L
from stream.panels import Panel, register
from stream.state_store import iso_to_epoch
from stream.world import keepers as K          # chamber names (the Ledge, East Chamber, the Pool, the Loft, the Deep): one source

ROTATE_S = 8.0
STATS_S = 10.0
BAR_H = 8


def _ordinal(n: int) -> str:
    n = int(n)
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "%d%s" % (n, suf)


def _world():
    m = sys.modules.get("stream.panels.world")
    sc = m.scene() if (m is not None and hasattr(m, "scene")) else None
    if sc is None or not getattr(sc, "booted", False):
        return None, None
    return sc, m


def _shown(m, raw) -> Optional[str]:
    try:
        return m.shown_name(raw) if m is not None else None
    except Exception:
        return None


def _names_on(ctx) -> bool:
    if ctx.chat_display is False:
        return False
    return (ctx.chat_cfg or {}).get("display") is not False


class ColonyPanel(Panel):
    key, region = "colony", "colony"

    # ------------------------------------------------------------------ model
    @staticmethod
    def _ladder(sc) -> Tuple[int, Optional[int], int, Optional[str], bool]:
        """(hatched, next_milestone, prev_milestone, next_chamber_name, reached_uncarved)"""
        w = sc.world
        hatched = sc.hatched_ever()
        wd = w.data.get("world") or {}
        ladder = list(wd.get("milestones") or [3, 5, 10, 25, 50])
        reached = set(wd.get("milestones_reached") or [])
        prev = 0
        nxt = None
        name = None
        for i, m in enumerate(ladder):
            if m in reached or (hatched >= m and m in reached):
                prev = m
                continue
            nxt = m
            name = K.chamber_name(m)
            break
        uncarved = nxt is not None and hatched >= nxt and nxt not in reached
        return hatched, nxt, prev, name, uncarved

    def _line1(self, sc, ctx) -> Tuple[str, str, float, Any]:
        """(headline, caption, bar fraction, colour)."""
        hatched, nxt, prev, name, uncarved = self._ladder(sc)
        accent = L.preset(ctx.preset)["accent"]
        head = "nobody has hatched here yet" if hatched == 0 else "%d ha%s hatched here" % (hatched, "s" if hatched == 1 else "ve")
        if nxt is None:
            return (head, "every chamber is open", 1.0, accent)
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
        return (head, "%d more until %s opens" % (more, name), max(0.0, min(1.0, frac)), L.COLORS["text"])

    @staticmethod
    def _keeper_fresh(ctx) -> bool:
        hb = iso_to_epoch((ctx.agent or {}).get("heartbeat_ts"))
        return hb is not None and (ctx.now - hb) < 120.0

    def _line2(self, sc, m, ctx, maxw: int = 388) -> Tuple[str, Optional[str]]:
        """(`3 awake · 14 asleep[ · night 4 for @sami]`, the night fact when it did not fit -> rotation item)."""
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
        if night and L.text_width("Menlo", 22, s + " · " + night) <= maxw:
            return s + " · " + night, None
        return s, night

    def _items(self, sc, m, ctx, now: float, extra: Optional[str] = None) -> List[Tuple[str, Any]]:
        names_on = _names_on(ctx)
        items: List[Tuple[str, Any]] = []
        if extra:
            items.append((extra, L.COLORS["text"]))
        res = (ctx.round or {}).get("last_result") or {}
        title = L.strip_non_bmp(str(res.get("title") or ""))
        ver = res.get("version") or (ctx.version or {}).get("string") or ""
        if title:
            by = _shown(m, res.get("picked_by")) if names_on else None
            if res.get("agent_pick"):
                items.append(("%s · nobody voted · %s" % (title, ver), L.COLORS["text2"]))
            elif by:
                items.append(("%s · picked by @%s · %s" % (title, by, ver), L.COLORS["text"]))
            else:
                items.append(("%s · %s" % (title, ver), L.COLORS["text"]))
        wd = sc.world.data.get("world") or {}
        ev = list(wd.get("event_log") or [])
        if ev and ev[-1].get("text"):
            items.append((L.strip_non_bmp(str(ev[-1]["text"])), L.COLORS["text2"]))
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
            items.append(("every light is a real person.", L.COLORS["text2"]))
        return items

    def _stats_card(self, sc, ctx, maxw: int = 388) -> str:
        """`!stats` card: progressively shorter forms until one fits the strip (all real: chat_stats + world len())."""
        cs = ctx.chat_stats or {}
        rate, ppl = cs.get("msgs_per_min_5m"), cs.get("unique_chatters_5m")
        st = sc.stats()
        try:
            rate_s = "%.1f" % float(rate) if rate is not None else "--"
        except Exception:
            rate_s = "--"
        ppl_s = "--" if ppl is None else str(ppl)
        ver = (ctx.version or {}).get("string") or ""
        hatched, awake = int(st.get("hatched_ever") or 0), int(st.get("awake") or 0)
        cands = ["stats: %s/min · %s ppl · %d hatched · %d awake · %s" % (rate_s, ppl_s, hatched, awake, ver),
                 "stats: %s/min · %s ppl · %d hatched · %s" % (rate_s, ppl_s, hatched, ver),
                 "stats: %s/min · %s ppl · %d hatched" % (rate_s, ppl_s, hatched),
                 "stats: %s/min · %d hatched" % (rate_s, hatched)]
        for c in cands:
            if L.text_width("Menlo", 20, c) <= maxw:
                return c
        return cands[-1]

    def _line3(self, sc, m, ctx, now: float, extra: Optional[str] = None) -> Tuple[str, Any]:
        if ctx.stats_until and now < float(ctx.stats_until):
            return self._stats_card(sc, ctx), L.COLORS["text"]
        items = self._items(sc, m, ctx, now, extra)
        return items[int(now // ROTATE_S) % len(items)]

    # ------------------------------------------------------------------ panel
    def inputs(self, ctx):
        sc, m = _world()
        if sc is None:
            return ("boot", ctx.preset)
        now = float(ctx.now or 0.0)
        l2, extra = self._line2(sc, m, ctx)
        return (self._line1(sc, ctx), l2, self._line3(sc, m, ctx, now, extra), ctx.preset)

    def render(self, ctx, size):
        w, h = size
        img = self.base(size)
        d = ImageDraw.Draw(img)
        accent = L.preset(ctx.preset)["accent"]
        maxw = w - 2 * L.PAD
        sc, m = _world()
        f1, f2, f3 = L.font("HN Medium", 22), L.font("Menlo", 22), L.font("Menlo", 20)
        if sc is None:
            d.text((L.PAD, 12), "the cave is waking…", font=f1, fill=L.COLORS["text2"])
            return img
        now = float(ctx.now or 0.0)
        head, cap, frac, c1 = self._line1(sc, ctx)
        d.text((L.PAD, 6), L.truncate("HN Medium", 22, head, maxw), font=f1, fill=L.COLORS["text"])
        d.text((L.PAD, 32), L.truncate("HN Medium", 20, cap, maxw), font=L.font("HN Medium", 20), fill=c1 if c1 != L.COLORS["text"] else L.COLORS["text2"])
        # 8 px bar (hairline track, fill = real fraction; amber while a reached milestone waits for a keeper)
        by = 58
        d.rectangle([L.PAD, by, L.PAD + maxw - 1, by + BAR_H - 1], fill=L.COLORS["hairline"])
        fw = int(round(maxw * frac))
        if fw > 0:
            d.rectangle([L.PAD, by, L.PAD + fw - 1, by + BAR_H - 1], fill=L.COLORS["warn"] if c1 == L.COLORS["warn"] else accent)
        l2, extra = self._line2(sc, m, ctx, maxw)
        d.text((L.PAD, 76), L.truncate("Menlo", 22, l2, maxw), font=f2, fill=L.COLORS["text"])
        t3, c3 = self._line3(sc, m, ctx, now, extra)
        d.text((L.PAD, 110), L.truncate("Menlo", 20, t3, maxw), font=f3, fill=c3)
        return img


register(ColonyPanel())
