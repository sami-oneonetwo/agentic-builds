"""Header panels (WORLD.md 5, regions 1-3). The header is the thumbnail: it is composited LAST by the compositor
(region key starts with "header") so it is drawn over every world state including event transitions.

  header_left   0,0,300,66    `atleastonce` (secondary) over `PIP HOLLOW` (accent; micro.header_tagline when a round
                              set one) + the chat-link dot (green = Pusher listener connected and chat_stats.json fresh,
                              amber = reconnecting). Unchanged geometry.
  header_center 300,0,620,66  THE THUMBNAIL: `3 AWAKE` at Arial Black 56 (`NOBODY AWAKE` at AB 40 when the count is 0),
                              then a right column: `· 17 HATCHED` and `NEXT EVENT 01:23` at Menlo 24 (22 when the
                              count strip is wide; never under 20). During a keeper build the column becomes three
                              Menlo 20 lines and adds `keeper carving · 12:40 left`. The digits are the round countdown
                              (accent / amber < 30 s / red < 10 s; `00:00` under SHIPPING / FAILED during the 5 s hold).
                              Both counts are len() over the world's real records (stream/panels/world.py
                              `world_counts()`); before the world boots the strip reads `-- AWAKE`, never a number.
  header_right  920,0,360,66  version string `v0.5.3` (Menlo 22, moved here from the centre) over a red LIVE dot +
                              real `N watching` (`--` when the poll is stale/failed or the stream is offline).

Every value comes from ctx (state.json / metrics.jsonl / chat_stats.json) or the world scene. Nothing is invented:
viewers are the last real poll or `--`; the awake count is the number of real chatters awake in the cave.
"""
from __future__ import annotations

import sys
from typing import Optional, Tuple

from PIL import Image, ImageDraw

from stream import layout as L
from stream.panels import Panel, register
from stream.state_store import iso_to_epoch

CHAT_STATS_FRESH_S = 60.0     # chat_stats.json is rewritten every 10 s by the listener; older -> "reconnecting"
COL_GAP = 12                  # px between the count strip and the right column
LEGACY_TAGLINE = "SHIP IT LIVE"
WORDMARK = "PIP HOLLOW"


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


def _world_counts() -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """(awake, asleep, hatched) from the live world panel module, or Nones when the world is not up."""
    m = sys.modules.get("stream.panels.world")
    if m is None or not hasattr(m, "world_counts"):
        return None, None, None
    try:
        return m.world_counts()
    except Exception:
        return None, None, None


# ----------------------------------------------------------------------------- region 1
class HeaderLeft(Panel):
    key, region = "header_left", "header_left"

    @staticmethod
    def _tagline(ctx) -> str:
        tag = (ctx.micro or {}).get("header_tagline")
        if not tag or tag == LEGACY_TAGLINE:
            return WORDMARK
        return L.strip_non_bmp(str(tag))

    def inputs(self, ctx):
        return (self._tagline(ctx), _chat_connected(ctx), ctx.preset)

    def render(self, ctx, size):
        w, h = size
        img = Image.new("RGBA", size, L.COLORS["bg"])
        d = ImageDraw.Draw(img)
        accent = L.preset(ctx.preset)["accent"]
        connected = _chat_connected(ctx)
        f = L.font("HN Medium", 22)
        cx, cy, r = L.PAD + 7, h // 2, 7
        dot = L.COLORS["add"] if connected else L.COLORS["warn"]
        d.ellipse([cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3], outline=_blend(dot, L.COLORS["bg"], 0.6), width=1)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=dot)
        tx = L.PAD + 14 + 14
        max_w = w - tx - L.PAD
        d.text((tx, 8), L.truncate("HN Medium", 22, "atleastonce", max_w), font=f, fill=L.COLORS["text2"])
        d.text((tx, 34), L.truncate("HN Medium", 22, self._tagline(ctx), max_w), font=f, fill=accent)
        return img


# ----------------------------------------------------------------------------- region 2 (the thumbnail)
class HeaderCenter(Panel):
    key, region = "header_center", "header_center"

    def __init__(self):
        self._ab: dict = {}            # (text, size, colour, max_w) -> 66 px tall AB strip

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
        under SHIPPING / FAILED (the round really is at zero), never a made-up number."""
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
        # the leading option's title replaces `NEXT EVENT` once someone has voted (the tally is len(pips standing); the
        # title is the platform's own string from state.round.options), so the thumbnail says what is about to happen
        votes = sorted([int(o.get("votes") or 0) for o in rnd.get("options") or [] if isinstance(o, dict)], reverse=True)
        lead = None
        if votes and votes[0] > 0 and (len(votes) == 1 or votes[0] > votes[1]):        # a UNIQUE leader, never a tie-break
            for o in rnd.get("options") or []:
                if isinstance(o, dict) and int(o.get("votes") or 0) == votes[0] and o.get("title"):
                    lead = L.strip_non_bmp(str(o.get("title")))
        return (lead or "NEXT EVENT", _mmss(secs), role)

    @staticmethod
    def _count(ctx):
        """(text, AB size, role) for the count strip: `3 AWAKE` AB 56, `NOBODY AWAKE` AB 40, `-- AWAKE` before boot."""
        awake, _asleep, _hatched = _world_counts()
        if awake is None:
            return ("-- AWAKE", 40, "text2")
        if awake == 0:
            return ("NOBODY AWAKE", 40, "text")
        return ("%d AWAKE" % awake, 56, "text")

    def inputs(self, ctx):
        mac = ctx.macro or {}
        _awake, _asleep, hatched = _world_counts()
        return (self._count(ctx), hatched, self._clock(ctx), self._macro_rem(ctx), bool(mac.get("active")),
                ctx.preset, bool(ctx.stale))

    def _ab_strip(self, txt: str, size: int, col, max_w: int):
        """Cached 66 px tall Arial Black strip, glyphs centred on y 33."""
        key = (txt, size, col, max_w)
        img = self._ab.get(key)
        if img is None:
            f = L.font("AB", size)
            t = L.truncate("AB", size, txt, max_w, ell="…")
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
        txt, ab_size, role = self._count(ctx)
        col = roles.get(role, L.COLORS["text"])
        if ctx.stale and role == "text":
            col = L.COLORS["text2"]
        # the count strip may take at most the width that leaves 200 px for the right column
        cimg = self._ab_strip(txt, ab_size, col, w - 2 * L.PAD - COL_GAP - 200)
        img.alpha_composite(cimg, (L.PAD, 0))
        lx = L.PAD + cimg.size[0] + COL_GAP
        avail = w - lx - L.PAD
        if avail < 60:
            return img
        _awake, _asleep, hatched = _world_counts()
        hatched_txt = ("· %d HATCHED" % hatched) if hatched is not None else "· -- HATCHED"
        label, digits, crole = self._clock(ctx)
        clock_txt = "%s %s" % (label, digits)
        clock_col = roles.get(crole, L.COLORS["text2"]) if crole in ("warn", "danger") else L.COLORS["text"]
        mac = ctx.macro or {}
        if mac.get("active"):
            mrem = self._macro_rem(ctx)
            tail = ("%s left" % _mmss(mrem)) if (mrem is not None and mrem >= 0) else ("overdue" if mrem is not None else "")
            # the longest form that fits the column (`NOBODY AWAKE` leaves ~208 px): `keeper carving · 12:40 left` ->
            # `keeper carving · 12:40` -> `carving · 12:40`
            cands = ["keeper carving · %s" % tail, "keeper carving · %s" % tail.replace(" left", ""),
                     "carving · %s" % tail.replace(" left", ""), "keeper carving"] if tail else ["keeper carving"]
            keeper_line = next((c for c in cands if L.text_width("Menlo", 20, c) <= avail), cands[-1])
            f20 = L.font("Menlo", 20)
            for i, (t, c) in enumerate(((hatched_txt, L.COLORS["text2"]), (clock_txt, clock_col),
                                        (keeper_line, L.COLORS["warn"] if (mrem is not None and mrem < 60) else L.COLORS["text2"]))):
                d.text((lx, 2 + 21 * i), L.truncate("Menlo", 20, t, avail), font=f20, fill=c)
            return img
        # two lines: the largest Menlo size in (24, 22, 20) whose longest line fits the column
        fs = 24
        for cand in (24, 22, 20):
            fs = cand
            if max(L.text_width("Menlo", cand, hatched_txt), L.text_width("Menlo", cand, clock_txt)) <= avail:
                break
        if L.text_width("Menlo", fs, clock_txt) > avail:            # a long option title: keep the digits, shorten the title
            tail = " " + digits
            clock_txt = L.truncate("Menlo", fs, label, max(20, avail - L.text_width("Menlo", fs, tail))) + tail
        f = L.font("Menlo", fs)
        d.text((lx, 7), L.truncate("Menlo", fs, hatched_txt, avail), font=f, fill=L.COLORS["text2"])
        d.text((lx, 36), L.truncate("Menlo", fs, clock_txt, avail), font=f, fill=clock_col)
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
        return (v.get("string") or "v0.0.0", self._viewers(ctx), ctx.preset, bool(ctx.stale))

    def render(self, ctx, size):
        w, h = size
        img = Image.new("RGBA", size, L.COLORS["bg"])
        d = ImageDraw.Draw(img)
        f = L.font("Menlo", 22)
        right = w - L.PAD
        # line 1 (y 8): the version string, right-aligned (grey when state.json is stale)
        ver = (ctx.version or {}).get("string") or "v0.0.0"
        vw = L.text_width("Menlo", 22, ver)
        d.text((right - vw, 8), ver, font=f, fill=L.COLORS["text2"] if ctx.stale else L.COLORS["text"])
        # line 2 (y 36): LIVE dot + real viewers, right-aligned
        live, n = self._viewers(ctx)
        # `LIVE` only when the real poll says so; otherwise a dim dot and `-- watching` (never the word OFFLINE on a frame
        # that is, by definition, being watched)
        segs = ([("LIVE", L.COLORS["text"])] if live else []) + \
               [("  %s watching" % n, L.COLORS["text"] if (live and n != "--") else L.COLORS["text2"])]
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
