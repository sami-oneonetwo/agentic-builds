"""Ticker (CONCEPT section 3, region 15): 880x64 right-to-left crawl at `micro.ticker_speed` px/s (default 120).

Items, separated by ` · `:
  * the last 10 patch notes from ships.jsonl  ->  `v0.3.11 @sam: palette ember` (agent picks: `v0.3.12 agent pick:
    tempo 100 bpm`; failed ships: `v0.3.12 FAILED: ...` in red; kill switch on: names become `[chat hidden by mod]`)
  * a chamber carve    `SHIPPED v0.5.0 · the Ledge opened · by @kai's hatch` for 30 s (stream/world/keepers.py)
  * the honesty line   `no camera, no mic, no fake viewers. every light in this cave is a real person.` (WORLD.md 5)
  * the command legend `feed · pet · dig · plant   A / B / C   !idea` (`!ask` only when ask.enabled)
  * the rule           `the keepers are AI agents. they build this cave live, from your !ideas, and you watch it land.`

The whole strip (opaque, panel fill, coloured segments) is rendered ONCE per content change; every frame is a
crop (or two crops when the seam is on screen) of that strip, so a frame costs well under 1 ms. The crawl
position is an accumulator advanced by speed/fps per frame, so a `ticker_speed` micro-ship changes the pace
without a jump, and the self-test's virtual clock stays deterministic.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from stream import layout as L
from stream.panels import Panel, register

FONT, SIZE = "HN Medium", 24
SEP = "  ·  "
HONESTY = "no camera, no mic, no fake viewers. every light in this cave is a real person."     # WORLD.md 5 row 9
RULE = "the keepers are AI agents. they build this cave live, from your !ideas, and you watch it land."   # WORLD.md 9
KEEPER_TICKER_S = 30.0          # a chamber carve rides the ticker this long (stream/world/keepers.py last_ticker)
DEFAULT_SPEED = 120.0
MIN_SPEED, MAX_SPEED = 20.0, 400.0


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
        """`SHIPPED v0.5.0 · the Ledge opened · by @kai's hatch` for 30 s after a milestone carve (names already
        filtered by the keepers module), read through the world panel module so a hot reload is followed."""
        import sys as _sys
        m = _sys.modules.get("stream.panels.world")
        try:
            kp = m.keepers() if (m is not None and hasattr(m, "keepers")) else None
            if kp is not None and kp.last_ticker and (ctx.now - float(kp.last_ticker_t)) < KEEPER_TICKER_S:
                return L.strip_non_bmp(str(kp.last_ticker))
        except Exception:
            pass
        return None

    @classmethod
    def _content_key(cls, ctx):
        """Cheap hashable summary of everything that changes the strip's pixels."""
        ships = tuple((str(s.get("version")), str(s.get("picked_by")), str(s.get("title")), bool(s.get("agent_pick")),
                       s.get("ok") is not False) for s in (ctx.ships or [])[-10:])
        return (ships, ctx.chat_display is not False, bool((ctx.ask or {}).get("enabled")), ctx.preset, cls._keeper_line(ctx))

    def _items(self, ctx):
        """-> list of items; each item is a list of (text, colour) segments."""
        accent = L.preset(ctx.preset)["accent"]
        text, text2, danger = L.COLORS["text"], L.COLORS["text2"], L.COLORS["danger"]
        names_ok = ctx.chat_display is not False
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
        items.append([(HONESTY, text)])
        # WORLD.md 5 row 9 legend: the world verbs (exact word), the letters, !idea (sing is a later carving)
        legend = [("say anything: a pip hatches with your name", text), ("   ", text2),
                  ("feed", accent), (" · ", text2), ("pet", accent), (" · ", text2), ("dig", accent), (" · ", text2),
                  ("plant", accent), ("   ", text2), ("A", accent), (" / ", text2), ("B", accent), (" / ", text2), ("C", accent),
                  (" walks your pip to a platform", text2), ("   ", text2), ("!idea <what to carve>", accent),
                  ("   ", text2), ("!theme ember", accent), ("   ", text2), ("!stats", accent), ("   ", text2), ("!help", accent)]
        if (ctx.ask or {}).get("enabled"):
            legend += [("   ", text2), ("!ask <anything>", accent)]
        items.append(legend)
        items.append([(RULE, text)])
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


register(Ticker())
