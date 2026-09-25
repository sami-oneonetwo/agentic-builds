"""Header panels (CONCEPT section 3, regions 1-3). The header is the thumbnail: it is composited LAST by the
compositor (region key starts with "header") so it is drawn over every stage state including the ship flash.

  header_left   0,0,300,66    wordmark `atleastonce` / tagline (micro.header_tagline) + chat-link dot
                              (green = Pusher listener connected and chat_stats.json fresh, amber = reconnecting)
  header_center 300,0,620,66  version at Arial Black 56 (the hook that survives 320x180), then the countdown
                              digits mm:ss ALSO at Arial Black 56 (accent; amber < 30 s, red < 10 s, same rule as the
                              bar) so the thumbnail carries two numbers and one of them ticks; right of the digits a
                              Menlo 20 stack: `NEXT SHIP` over `round N`, or `MACRO in mm:ss` during an agent build.
                              QA (2026-09-25) measured the old Menlo 24 clock at 5 px tall / luminance 119 at 320x180:
                              illegible, which failed the CONCEPT 3 gate "confirm the version number and NEXT SHIP read".
  header_right  920,0,360,66  `SHIPPED n · FAILED m` scoreline, red LIVE dot + real `N watching` (`--` when the
                              poll is stale/failed or the stream is offline). No toast here any more: the theme
                              notice lives in the pinned strip (chat_bridge), so the scoreline never disappears.

Every value comes from ctx (state.json / metrics.jsonl / chat_stats.json). Nothing is invented: viewers are
the last real poll or `--`. Re-render cadence: left/right on state change, centre once per second (clock).
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from stream import layout as L
from stream.panels import Panel, register
from stream.state_store import iso_to_epoch

CHAT_STATS_FRESH_S = 60.0     # chat_stats.json is rewritten every 10 s by the listener; older -> "reconnecting"
CLOCK_GAP = 24                # px between the version and the countdown digits (both AB 56)
LABEL_GAP = 14                # px between the digits and the Menlo 20 label stack


def _mmss(sec) -> str:
    if sec is None:
        return "--:--"
    sec = max(0, int(sec))
    if sec >= 6000:
        return "%d:%02d:%02d" % (sec // 3600, (sec // 60) % 60, sec % 60)
    return "%02d:%02d" % (sec // 60, sec % 60)


def _blend(hex_a: str, hex_b: str, t: float):
    a, b = L.hex_rgb(hex_a), L.hex_rgb(hex_b)
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _chat_connected(ctx) -> bool:
    """Green dot iff the Pusher listener says connected AND its stats file is fresh; else amber (reconnecting)."""
    cs = ctx.chat_stats or {}
    if cs:
        t = iso_to_epoch(cs.get("ts"))
        fresh = t is not None and (ctx.now - t) < CHAT_STATS_FRESH_S
        return bool(cs.get("connected")) and fresh
    return bool((ctx.chat_cfg or {}).get("connected"))


# ----------------------------------------------------------------------------- region 1
class HeaderLeft(Panel):
    key, region = "header_left", "header_left"

    def inputs(self, ctx):
        return ((ctx.micro or {}).get("header_tagline") or "SHIP IT LIVE", _chat_connected(ctx), ctx.preset)

    def render(self, ctx, size):
        w, h = size
        img = Image.new("RGBA", size, L.COLORS["bg"])
        d = ImageDraw.Draw(img)
        accent = L.preset(ctx.preset)["accent"]
        connected = _chat_connected(ctx)
        f = L.font("HN Medium", 22)
        # chat-link dot, vertically centred, with a faint ring so it reads at 320x180
        cx, cy, r = L.PAD + 7, h // 2, 7
        dot = L.COLORS["add"] if connected else L.COLORS["warn"]
        d.ellipse([cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3], outline=_blend(dot, L.COLORS["bg"], 0.6), width=1)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=dot)
        tx = L.PAD + 14 + 14
        max_w = w - tx - L.PAD
        tag = L.strip_non_bmp((ctx.micro or {}).get("header_tagline") or "SHIP IT LIVE")
        # two 22 px lines: channel (secondary) over tagline (accent); HN Medium 22 bbox spans y 6..22
        d.text((tx, 8), L.truncate("HN Medium", 22, "atleastonce", max_w), font=f, fill=L.COLORS["text2"])
        d.text((tx, 34), L.truncate("HN Medium", 22, tag, max_w), font=f, fill=accent)
        return img


# ----------------------------------------------------------------------------- region 2 (the thumbnail)
class HeaderCenter(Panel):
    key, region = "header_center", "header_center"

    def __init__(self):
        self._ab: dict = {}            # (text, colour, max_w) -> 66 px tall AB 56 strip; the version + ~4 clock colours

    @staticmethod
    def _macro_rem(ctx):
        mac = ctx.macro or {}
        if not mac.get("active"):
            return None
        dl = iso_to_epoch(mac.get("deadline_ts"))
        return None if dl is None else int(dl - ctx.now)

    @staticmethod
    def _clock(ctx):
        """(label, digits, colour role). The digits are the round countdown; during the 5 s ship hold they read 00:00
        under a SHIPPING / FAILED label (the round really is at zero), never a made-up number."""
        rnd = ctx.round or {}
        phase = rnd.get("phase") or "open"
        rem = ctx.round_remaining
        if phase == "ship":
            res = rnd.get("last_result") or {}
            if res.get("ok") is False:
                return ("FAILED", "00:00", "danger")
            return ("SHIPPING", "00:00", "accent")
        secs = None if rem is None else int(max(0, rem))
        role = "accent"
        if secs is not None and rem < 10:
            role = "danger"
        elif secs is not None and rem < 30:
            role = "warn"
        return ("NEXT SHIP", _mmss(secs), role)

    def inputs(self, ctx):
        mac = ctx.macro or {}
        return ((ctx.version or {}).get("string") or "v0.0.0", self._clock(ctx), self._macro_rem(ctx),
                bool(mac.get("active")), (ctx.round or {}).get("number"), ctx.preset, bool(ctx.stale))

    def _ab_strip(self, txt: str, col, max_w: int):
        """Cached 66 px tall Arial Black 56 strip, glyphs centred on y 33 (AB 56 bbox spans y 21..63)."""
        key = (txt, col, max_w)
        img = self._ab.get(key)
        if img is None:
            f = L.font("AB", 56)
            t = L.truncate("AB", 56, txt, max_w, ell="…")
            bb = f.getbbox(t)
            img = Image.new("RGBA", (max(1, bb[2]), 66), (0, 0, 0, 0))
            ImageDraw.Draw(img).text((0, 33 - (bb[1] + bb[3]) // 2), t, font=f, fill=col)
            if len(self._ab) > 24:
                self._ab.clear()
            self._ab[key] = img
        return img

    def render(self, ctx, size):
        w, h = size
        img = Image.new("RGBA", size, L.COLORS["bg"])
        d = ImageDraw.Draw(img)
        accent = L.preset(ctx.preset)["accent"]
        roles = dict(L.COLORS)
        roles["accent"] = accent
        label, digits, role = self._clock(ctx)
        ver = (ctx.version or {}).get("string") or "v0.0.0"
        # version (white, grey when state.json is stale) | 24 px | digits (accent / amber / red) | 14 px | label stack
        dig_w = L.text_width("AB", 56, digits)
        vimg = self._ab_strip(ver, L.COLORS["text"] if not ctx.stale else L.COLORS["text2"],
                              w - 2 * L.PAD - CLOCK_GAP - dig_w - LABEL_GAP - 60)
        img.alpha_composite(vimg, (L.PAD, 0))
        cx = L.PAD + vimg.size[0] + CLOCK_GAP
        dimg = self._ab_strip(digits, roles.get(role, L.COLORS["text"]), w - cx - L.PAD)
        img.alpha_composite(dimg, (cx, 0))
        lx = cx + dimg.size[0] + LABEL_GAP
        avail = w - lx - L.PAD
        if avail < 40:
            return img
        f20 = L.font("Menlo", 20)
        # line 1 (bbox y 4..19 at y 8): the label; line 2 (y 38): macro deadline or the round number
        d.text((lx, 8), L.truncate("Menlo", 20, label, avail), font=f20,
               fill=roles.get(role, L.COLORS["text2"]) if role in ("warn", "danger") else L.COLORS["text2"])
        mrem = self._macro_rem(ctx)
        if (ctx.macro or {}).get("active"):
            tail = (" in %s" % _mmss(mrem)) if (mrem is not None and mrem >= 0) else (" overdue" if mrem is not None else "")
            line = "MACRO" + tail
            col = L.COLORS["warn"] if (mrem is not None and mrem < 60) else L.COLORS["text2"]
        else:
            n = (ctx.round or {}).get("number")
            line = ("round %s" % n) if n else ""
            col = L.COLORS["text2"]
        if line:
            d.text((lx, 38), L.truncate("Menlo", 20, line, avail), font=f20, fill=col)
        return img


# ----------------------------------------------------------------------------- region 3
class HeaderRight(Panel):
    key, region = "header_right", "header_right"

    @staticmethod
    def _viewers(ctx):
        """(live, text) -- `--` whenever the number is not a fresh real poll."""
        m = ctx.metrics or {}
        live = bool(m.get("is_live"))
        n = m.get("viewer_count")
        if live and m.get("poll_ok") and n is not None:
            try:
                n = int(n)
            except Exception:
                return live, "--"
            return live, "%d" % n
        return live, "--"

    def inputs(self, ctx):
        v = ctx.version or {}
        return (int(v.get("shipped") or 0), int(v.get("failed") or 0), self._viewers(ctx), ctx.preset)

    def render(self, ctx, size):
        w, h = size
        img = Image.new("RGBA", size, L.COLORS["bg"])
        d = ImageDraw.Draw(img)
        accent = L.preset(ctx.preset)["accent"]
        f = L.font("Menlo", 22)
        right = w - L.PAD
        # line 1 (y 8): scoreline, right-aligned, on every frame (theme notices live in the pinned strip)
        v = ctx.version or {}
        shipped, failed = int(v.get("shipped") or 0), int(v.get("failed") or 0)
        segs = [("SHIPPED ", L.COLORS["text2"]), ("%d" % shipped, L.COLORS["text"]),
                (" · FAILED ", L.COLORS["text2"]), ("%d" % failed, L.COLORS["danger"] if failed else L.COLORS["text2"])]
        total = sum(L.text_width("Menlo", 22, s) for s, _ in segs)
        x = right - total
        for s, col in segs:
            d.text((x, 8), s, font=f, fill=col)
            x += L.text_width("Menlo", 22, s)
        # line 2 (y 36): LIVE dot + real viewers, right-aligned
        live, n = self._viewers(ctx)
        word = "LIVE" if live else "OFFLINE"
        segs = [(word, L.COLORS["text"] if live else L.COLORS["text2"]), ("  %s watching" % n, L.COLORS["text"] if (live and n != "--") else L.COLORS["text2"])]
        total = sum(L.text_width("Menlo", 22, s) for s, _ in segs)
        x = right - total
        dot = L.COLORS["danger"] if live else L.COLORS["hairline"]
        d.ellipse([x - 22, 42, x - 10, 54], fill=dot)
        for s, col in segs:
            d.text((x, 36), s, font=f, fill=col)
            x += L.text_width("Menlo", 22, s)
        return img


register(HeaderLeft())
register(HeaderCenter())
register(HeaderRight())
