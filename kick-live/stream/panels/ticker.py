"""Ticker (CONCEPT section 3, region 15; OPENWORLD.md 8 row 9, 12): 880x64 right-to-left crawl at `micro.ticker_speed`
px/s (default 120).

Items, separated by ` · `:
  * the last 10 patch notes from ships.jsonl  ->  `v0.3.11 @sam: palette ember` (agent picks: `v0.3.12 agent pick:
    tempo 100 bpm`; failed ships: `v0.3.12 FAILED: ...` in red; kill switch on: names become `[chat hidden by mod]`)
  * a keeper ship line  `SHIPPED v0.6.0 · Longgrass` for 30 s (stream/world/keepers.py `last_ticker`)
  * the honesty line, on the land (OPENWORLD 12): `no camera, no mic, no fake viewers. every name on this land is a
    real person in chat. the wind is just the wind.`; on the cave the WORLD.md 5 line (`every light in this cave...`)
  * the legend: `say anything: a creature walks out with your name`, then ONLY the verbs the running world really
    parses (the scene's `verbs()`, else stream.chat_bridge's VERBS minus its `LATER_VERBS`), in the spec's order
    `go · plant · camp · sow · fire · stack · feed ...`, then `A / B / C walks your pip to a waystone`; the `!commands`
    join once the room has company (awake > 1)
  * `a day here is one hour` ONLY while the world runs the compressed day (`world_day: "hour"`, OPENWORLD 2.2)
  * the rule, only while a keeper is on duty: `the keepers are AI agents. they raise this land live, from your
    !ideas, and you watch it go up.` (cave: `...build this cave live... watch it land.`)

The whole strip (opaque, panel fill, coloured segments) is rendered ONCE per content change; every frame is a
crop (or two crops when the seam is on screen) of that strip, so a frame costs well under 1 ms. The crawl
position is an accumulator advanced by speed/fps per frame, so a `ticker_speed` micro-ship changes the pace
without a jump, and the self-test's virtual clock stays deterministic.
"""
from __future__ import annotations

import sys
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw

from stream import layout as L
from stream.panels import Panel, register
from stream.state_store import iso_to_epoch

FONT, SIZE = "HN Medium", 24
SEP = "  ·  "
HONESTY_LAND = ("no camera, no mic, no fake viewers. every name on this land is a real person in chat. "
                "the wind is just the wind.")                                                        # OPENWORLD 12
RULE_LAND = "the keepers are AI agents. they raise this land live, from your !ideas, and you watch it go up."   # OPENWORLD 10
HOUR_DAY = "a day here is one hour"                                                                  # OPENWORLD 2.2
HONESTY_CAVE = "no camera, no mic, no fake viewers. every light in this cave is a real person."      # WORLD.md 5 row 9
RULE_CAVE = "the keepers are AI agents. they build this cave live, from your !ideas, and you watch it land."   # WORLD.md 9
HONESTY, RULE = HONESTY_LAND, RULE_LAND
SAY_LAND = "say anything: a creature walks out with your name"
SAY_CAVE = "say anything: a pip hatches with your name"
# the spec's legend order (OPENWORLD 8 row 9); only verbs the running world parses are drawn, at most LEGEND_MAX
LEGEND_ORDER = ("go", "plant", "camp", "sow", "fire", "stack", "feed", "pet", "gift", "swim", "wave", "sit", "dance")
LEGEND_MAX = 8
V0_VERBS = ("go", "plant", "feed", "pet")       # the v0 preview set, used only when neither the scene nor the parser says
KEEPER_TICKER_S = 30.0          # a keeper ship rides the ticker this long (stream/world/keepers.py last_ticker)
DEFAULT_SPEED = 120.0
MIN_SPEED, MAX_SPEED = 20.0, 400.0


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


def _is_land() -> bool:
    return hasattr(_scene(), "land")


def _world_day() -> str:
    """`real` | `hour` from the scene's Nature (or the world block); `real` when unknown."""
    sc = _scene()
    if sc is None or not getattr(sc, "booted", False):
        return "real"
    nat = getattr(sc, "nature", None)
    wd = getattr(nat, "world_day", None)
    if wd:
        return str(wd)
    try:
        return str(((sc.world.data.get("world") or {}).get("world_day")) or "real")
    except Exception:
        return "real"


def available_verbs() -> Tuple[str, ...]:
    """The verbs a viewer can type that DO something, from the running world: the scene's `verbs()` when it has one,
    else stream.chat_bridge's VERBS minus the ones it parses only to refuse (`LATER_VERBS`), else the v0 set."""
    sc = _scene()
    fn = getattr(sc, "verbs", None)
    if callable(fn):
        try:
            vs = tuple(str(v).lower() for v in fn())
            if vs:
                return vs
        except Exception:
            pass
    cb = sys.modules.get("stream.chat_bridge")
    vs = tuple(getattr(cb, "VERBS", ()) or ())
    if vs:
        later = set(getattr(cb, "LATER_VERBS", {}) or {})
        return tuple(v for v in vs if v not in later)
    return V0_VERBS


class Ticker(Panel):
    key, region = "ticker", "ticker"
    GAP = 0             # every item (incl. the last) ends with SEP, so the wrap seam already reads like any other separator

    def __init__(self):
        self._strip = None            # opaque RGBA strip, full crawl content, width = content + GAP
        self._strip_key = None
        self._items_cache = {}        # segments tuple -> pre-rendered item image (the long fixed lines render once ever)
        self._pos = 0.0               # crawl offset in px (accumulated)
        self._last_frame = None

    # ------------------------------------------------------------------ content
    @staticmethod
    def _speed(ctx) -> float:
        try:
            v = float((ctx.micro or {}).get("ticker_speed") or DEFAULT_SPEED)
        except Exception:
            v = DEFAULT_SPEED
        return max(MIN_SPEED, min(MAX_SPEED, v))

    @staticmethod
    def _keeper_line(ctx):
        """`SHIPPED v0.6.0 · Longgrass` for 30 s after a keeper ship (names already filtered by the keepers module),
        read through the world panel module so a hot reload is followed."""
        m = _wm()
        try:
            kp = m.keepers() if (m is not None and hasattr(m, "keepers")) else None
            if kp is not None and kp.last_ticker and (ctx.now - float(kp.last_ticker_t)) < KEEPER_TICKER_S:
                return L.strip_non_bmp(str(kp.last_ticker))
        except Exception:
            pass
        return None

    @staticmethod
    def _room(ctx):
        """(awake <= 1, keeper on duty): a lone viewer gets the four words and the letters, not the !command legend; the
        `keepers are AI agents` line rides only while a keeper is actually on duty (the beacon is lit)."""
        awake = None
        m = _wm()
        try:
            if m is not None and hasattr(m, "world_counts"):
                awake = m.world_counts()[0]
        except Exception:
            awake = None
        hb = iso_to_epoch((ctx.agent or {}).get("heartbeat_ts"))
        fresh = hb is not None and (float(ctx.now) - hb) < 120.0
        return (awake is None or awake <= 1, fresh)

    @classmethod
    def legend_verbs(cls) -> Tuple[str, ...]:
        """The verbs the legend draws: the spec's order filtered by what the world really parses (<= LEGEND_MAX)."""
        have = set(available_verbs())
        return tuple(v for v in LEGEND_ORDER if v in have)[:LEGEND_MAX]

    @classmethod
    def _content_key(cls, ctx):
        """Cheap hashable summary of everything that changes the strip's pixels."""
        ships = tuple((str(s.get("version")), str(s.get("picked_by")), str(s.get("title")), bool(s.get("agent_pick")),
                       s.get("ok") is not False) for s in (ctx.ships or [])[-10:])
        land = _is_land()
        return (ships, ctx.chat_display is not False, bool((ctx.ask or {}).get("enabled")), ctx.preset, cls._keeper_line(ctx),
                cls._room(ctx), land, cls.legend_verbs() if land else (), _world_day() if land else "real")

    def texts(self, ctx) -> List[str]:
        """The plain text of every item, in crawl order (the test surface)."""
        return ["".join(t for t, _c in it) for it in self._items(ctx)]

    def _items(self, ctx):
        """-> list of items; each item is a list of (text, colour) segments."""
        accent = L.preset(ctx.preset)["accent"]
        text, text2, danger = L.COLORS["text"], L.COLORS["text2"], L.COLORS["danger"]
        names_ok = ctx.chat_display is not False
        land = _is_land()
        items = []
        for s in (ctx.ships or [])[-10:]:
            ver = str(s.get("version") or "v?")
            title = L.strip_non_bmp(str(s.get("title") or "").replace(": ", " ").replace(":", ""))
            failed = s.get("ok") is False
            if s.get("agent_pick") or not s.get("picked_by"):
                who, who_col = "agent pick", text2
            elif not names_ok:
                who, who_col = "[chat hidden by mod]", text2
            else:
                nm = L.strip_non_bmp(str(s.get("picked_by")))
                who, who_col = "@" + nm, L.name_color(nm, ctx.preset)
            if failed:
                items.append([(ver + " ", danger), ("FAILED", danger), (": " + title, text2)])
            else:
                items.append([(ver + " ", accent), (who, who_col), (": " + title, text)])
        if not items:
            items.append([("no events yet: ", text2), ("the first one lands in under 3 minutes", text)])
        kl = self._keeper_line(ctx)
        if kl:
            items.append([(kl, accent)])
        items.append([(HONESTY_LAND if land else HONESTY_CAVE, text)])
        alone, keeper_here = self._room(ctx)
        if land:
            # OPENWORLD 8 row 9 legend: only verbs the world parses, the letters; the !commands once the room has company
            legend = [(SAY_LAND, text), ("   ", text2)]
            verbs = self.legend_verbs()
            for i, v in enumerate(verbs):
                if i:
                    legend.append((" · ", text2))
                legend.append((v, accent))
            if verbs:
                legend.append(("   ", text2))
            legend += [("A", accent), (" / ", text2), ("B", accent), (" / ", text2), ("C", accent),
                       (" walks your pip to a waystone", text2)]
            if not alone:
                legend += [("   ", text2), ("!idea <what to raise>", accent), ("   ", text2), ("!theme ember", accent),
                           ("   ", text2), ("!stats", accent), ("   ", text2), ("!help", accent)]
        else:
            legend = [(SAY_CAVE, text), ("   ", text2),
                      ("feed", accent), (" · ", text2), ("pet", accent), (" · ", text2), ("dig", accent), (" · ", text2),
                      ("plant", accent), ("   ", text2), ("A", accent), (" / ", text2), ("B", accent), (" / ", text2), ("C", accent),
                      (" walks your pip to a platform", text2)]
            if not alone:
                legend += [("   ", text2), ("!idea <what to carve>", accent), ("   ", text2), ("!theme ember", accent),
                           ("   ", text2), ("!stats", accent), ("   ", text2), ("!help", accent)]
        if (ctx.ask or {}).get("enabled"):
            legend += [("   ", text2), ("!ask <anything>", accent)]
        items.append(legend)
        if land and _world_day() == "hour":
            items.append([(HOUR_DAY, text2)])
        if keeper_here:
            items.append([(RULE_LAND if land else RULE_CAVE, text)])
        return items

    # ------------------------------------------------------------------ strip
    def _item_img(self, segs, h: int):
        """One item + trailing separator, rendered once and cached (a ship only renders its own new line)."""
        key = tuple(segs)
        img = self._items_cache.get(key)
        if img is not None:
            return img
        f = L.font(FONT, SIZE)
        widths = [L.text_width(FONT, SIZE, t) for t, _ in segs]
        sep_w = L.text_width(FONT, SIZE, SEP)
        img = Image.new("RGBA", (max(1, sum(widths) + sep_w), h), L.COLORS["panel"])
        d = ImageDraw.Draw(img)
        bb = f.getbbox("Ag")
        y = h // 2 - (bb[1] + bb[3]) // 2          # HN Medium 24 bbox y 7..29 -> glyphs centred in 64
        x = 0
        for (t, col), tw in zip(segs, widths):
            d.text((x, y), t, font=f, fill=col)
            x += tw
        d.text((x, y), SEP, font=f, fill=L.COLORS["text2"])
        if len(self._items_cache) > 64:
            self._items_cache.clear()
        self._items_cache[key] = img
        return img

    def _build(self, ctx, h: int):
        imgs = [self._item_img(it, h) for it in self._items(ctx)]
        total = sum(im.size[0] for im in imgs) + self.GAP
        strip = Image.new("RGBA", (max(1, total), h), L.COLORS["panel"])
        x = 0
        for im in imgs:
            strip.paste(im, (x, 0))
            x += im.size[0]
        ImageDraw.Draw(strip).line([(0, 0), (strip.size[0] - 1, 0)], fill=L.COLORS["hairline"], width=1)
        return strip

    # ------------------------------------------------------------------ Panel API
    def inputs(self, ctx):
        frame = int(ctx.frame or 0)
        if self._last_frame is None or frame < self._last_frame:
            self._pos = 0.0
        elif frame != self._last_frame:
            self._pos += self._speed(ctx) * (frame - self._last_frame) / max(1.0, float(ctx.fps or 30.0))
        self._last_frame = frame
        return (self._content_key(ctx), int(self._pos))

    def render(self, ctx, size):
        w, h = size
        key = (self._content_key(ctx), h)
        if self._strip is None or self._strip_key != key:
            self._strip = self._build(ctx, h)
            self._strip_key = key
        strip = self._strip
        sw = strip.size[0]
        off = int(self._pos) % sw
        if off + w <= sw:
            return strip.crop((off, 0, off + w, h))
        img = Image.new("RGBA", size, L.COLORS["panel"])
        first = strip.crop((off, 0, sw, h))
        img.paste(first, (0, 0))
        x = sw - off
        while x < w:                                  # strip narrower than the window: tile it
            piece = strip.crop((0, 0, min(sw, w - x), h))
            img.paste(piece, (x, 0))
            x += sw
        return img


# HUD pass (journal 028): this region left stream/layout.py; the module stays on disk (its copy and tests are
# reused by the land strip) but registers nothing. `Ticker` would be dropped by register() anyway.
# register(Ticker())
