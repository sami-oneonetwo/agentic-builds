"""stream/panels/chat_pane.py - chat pinned strip (region 10) and chat messages pane (region 11).

Both panels draw ONLY from ctx (COMPOSITOR_API.md section 3). No names are ever invented: the pane
shows ctx.chat (moderated, past the 3 s hold, newest last), the strip shows ctx.notice / help /
round state. Kill switch: ctx.chat_display (ChatBridge) and state.chat.display are both honoured on
every frame; either being False draws "chat hidden by mod" instead of any name.

ChatPinned (840,72,440,40; HN Medium 22)
  priority: hidden -> notice (4 s, colour by level) -> paused -> !help legend (5 s per item, 20 s)
            -> 5 min chat silence legend -> "0 votes, your letter decides this one" (<30 s, amber)
            -> rotation every 20 s (Type A, B or C / !idea / !theme, + !ask only when ask.enabled)
  motion: text fades in over 8 frames on change; a 1 Hz progress hairline shows the 20 s rotation.

ChatPane (840,112,440,272; Menlo 22, 26 px lines)
  last 10 messages, wrapped at 408 px, continuation lines indented, at most 4 lines per message;
  username in L.name_color(name, preset); "#N" builder tag on a user's first-ever message; letter
  chip on votes; NOMINATED tag on !idea; theme/ask/mod tags; newest message gets a 1 s accent
  highlight fade (10 steps) and the column slides up over 8 frames when a message lands.
  The text strip is rendered once per message-set change and cached; the per-frame work while
  animating is one paste + one rectangle.
  empty: "chat is empty. be the first: type A"   paused: amber "chat paused by mod" header line.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from stream import layout as L
from stream.panels import Panel, register

ROTATE_S = 20.0
ROTATION = ("Type A, B or C to vote", "!idea <what should change>", "!theme ember")
ASK_PROMPT = "!ask <anything>, answered on screen"
LEGEND = (
    "A / B / C in chat = your vote",
    "!idea <text> = nominate a change",
    "!theme <preset> = repaint the stream",
    "presets: kick ember ice violet gold",
    "presets: magenta cyan paper",
    "!stats = live numbers   !help = this",
)
LEGEND_ITEM_S = 5.0
SILENCE_S = 300.0
FADE_FRAMES = 8
SLIDE_FRAMES = 8
HIGHLIGHT_S = 1.0
HIGHLIGHT_STEPS = 10
MAX_LINES_PER_MSG = 4
TAGS = {"idea": ("NOMINATED", "warn"), "theme": ("theme", "text2"), "ask": ("ASK", "text2"),
        "mod": ("mod action", "warn"), "stats": ("stats", "text2"), "help": ("help", "text2")}


def _rgb(h: str) -> Tuple[int, int, int]:
    return L.hex_rgb(h)


def _mix(a: str, b: str, f: float) -> Tuple[int, int, int]:
    """Linear blend of two hex colours: f=0 -> a, f=1 -> b."""
    f = 0.0 if f < 0 else (1.0 if f > 1 else f)
    ra, rb = _rgb(a), _rgb(b)
    return tuple(int(round(ra[i] + (rb[i] - ra[i]) * f)) for i in range(3))


def _ease_out(x: float) -> float:
    x = 0.0 if x < 0 else (1.0 if x > 1 else x)
    return 1.0 - (1.0 - x) * (1.0 - x)


def display_on(ctx) -> bool:
    """Kill switch: ChatBridge.display (ctx.chat_display) AND state.chat.display must both be on."""
    if ctx.chat_display is False:
        return False
    cfg = ctx.chat_cfg or {}
    if cfg.get("display") is False:
        return False
    return True


_MONO_ADVANCE: Dict[int, int] = {}


def _mono_advance(size: int) -> int:
    """Menlo is monospace: one cached getlength("0") per size replaces hundreds of getlength calls."""
    a = _MONO_ADVANCE.get(size)
    if a is None:
        a = max(1, L.text_width("Menlo", size, "0"))
        _MONO_ADVANCE[size] = a
    return a


def _isascii(s: str) -> bool:
    try:
        return s.isascii()
    except AttributeError:  # pragma: no cover (3.9 has str.isascii)
        return all(ord(ch) < 128 for ch in s)


def mono_width(size: int, text: str) -> int:
    """Pixel width of `text` at Menlo `size`: exact count-based for ASCII, getlength otherwise."""
    if _isascii(text):
        return len(text) * _mono_advance(size)
    return L.text_width("Menlo", size, text)


def mono_wrap(size: int, text: str, max_w: int, max_lines: int = 0) -> List[str]:
    """L.wrap semantics (greedy words, hard-split overlong words, … on the capped last line) but
    measured by character count when the text is ASCII. Non-ASCII text falls back to L.wrap."""
    if not _isascii(text or ""):
        return L.wrap("Menlo", size, text, max_w, max_lines)
    cols = max(1, max_w // _mono_advance(size))
    lines: List[str] = []
    cur = ""
    for wd in (text or "").split(" "):
        cand = wd if not cur else cur + " " + wd
        if len(cand) <= cols:
            cur = cand
            continue
        if cur:
            lines.append(cur)
        while len(wd) > cols:
            lines.append(wd[:cols])
            wd = wd[cols:]
        cur = wd
    if cur:
        lines.append(cur)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1] + " …"
        if len(last) > cols:
            last = last[:max(0, cols - 1)] + "…"
        lines[-1] = last
    return lines


def mono_wrap2(size: int, text: str, first_w: int, rest_w: int, max_lines: int = 0) -> List[str]:
    """Greedy wrap where line 0 has first_w pixels (after the name/chips) and every later line has
    rest_w (after the indent). Overlong words are hard-split at the current line's width. ASCII text
    is measured by character count; anything else falls back to L.wrap per line width."""
    text = text or ""
    if not _isascii(text):
        lines = L.wrap("Menlo", size, text, first_w, 0)
        if len(lines) > 1:
            lines = [lines[0]] + L.wrap("Menlo", size, " ".join(lines[1:]), rest_w, max(0, max_lines - 1) if max_lines else 0)
        return lines[:max_lines] if max_lines and len(lines) > max_lines else (lines or [""])
    adv = _mono_advance(size)
    c_first, c_rest = max(1, first_w // adv), max(1, rest_w // adv)
    lines: List[str] = []
    cur = ""

    def cols() -> int:
        return c_first if not lines else c_rest

    for wd in text.split(" "):
        cand = wd if not cur else cur + " " + wd
        if len(cand) <= cols():
            cur = cand
            continue
        if cur:
            lines.append(cur)
            cur = ""
        while len(wd) > cols():
            k = cols()
            lines.append(wd[:k])
            wd = wd[k:]
        cur = wd
    if cur or not lines:
        lines.append(cur)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        k = c_rest if max_lines > 1 else c_first
        last = lines[-1] + " …"
        if len(last) > k:
            last = last[:max(0, k - 1)] + "…"
        lines[-1] = last
    return lines


def _level_color(level: Optional[str], accent: str) -> str:
    if level == "danger":
        return L.COLORS["danger"]
    if level in ("ok", "accent"):
        return accent
    if level in ("info", "plain", "text"):
        return L.COLORS["text"]
    return L.COLORS["warn"]


# =============================================================================== pinned strip
class ChatPinned(Panel):
    key, region = "chat_pinned", "chat_pinned"
    FONT, SIZE = "HN Medium", 22

    def __init__(self):
        self._last_txt: Optional[str] = None
        self._since_frame: int = 0

    def _pick(self, ctx) -> Tuple[str, str, bool]:
        """-> (text, colour, show_rotation_progress)"""
        accent = L.preset(ctx.preset)["accent"]
        if not display_on(ctx):
            return "chat hidden by mod", L.COLORS["warn"], False
        n = ctx.notice
        if n and isinstance(n, (tuple, list)) and n and n[0]:
            return str(n[0]), _level_color(n[1] if len(n) > 1 else None, accent), False
        if ctx.mod_paused:
            return "chat paused by mod", L.COLORS["warn"], False
        now = ctx.now or 0.0
        if ctx.help_until and now < ctx.help_until:
            return LEGEND[int(now / LEGEND_ITEM_S) % len(LEGEND)], L.COLORS["text"], False
        raw = ctx.chat_raw or []
        last_t = raw[-1].get("t") if raw else None
        if last_t is not None and now - last_t > SILENCE_S:
            return LEGEND[int(now / LEGEND_ITEM_S) % len(LEGEND)], L.COLORS["text2"], False
        rem = ctx.round_remaining
        phase = (ctx.round or {}).get("phase")
        if (ctx.vote_count or 0) == 0 and rem is not None and 0 <= rem < 30 and phase != "ship":
            return "0 votes, your letter decides this one", L.COLORS["warn"], False
        if (ctx.vote_count or 0) == 0 and not (getattr(ctx, "founders", None) or []):
            # nobody has voted or chatted yet: pin the one instruction that matters instead of cycling to `!theme ember`
            return ROTATION[0], L.COLORS["text"], False
        items = list(ROTATION)
        if (ctx.ask or {}).get("enabled"):
            items.append(ASK_PROMPT)
        return items[int(now / ROTATE_S) % len(items)], L.COLORS["text"], True

    def inputs(self, ctx):
        txt, col, prog = self._pick(ctx)
        frame = ctx.frame or 0
        if txt != self._last_txt:
            # Only the 20 s rotation eases in. The first text ever, and every notice (`@nova voted A`, cooldowns, mod
            # actions) land at full colour on the frame they are set: the acknowledgement must be visible within one
            # frame of ingest (CONCEPT 2), not 8 frames later.
            instant = self._last_txt is None or not prog
            self._last_txt = txt
            self._since_frame = frame - (FADE_FRAMES if instant else 0)
        step = min(FADE_FRAMES, max(0, frame - self._since_frame))
        prog_step = int(((ctx.now or 0.0) % ROTATE_S) / ROTATE_S * 20) if prog else -1   # 1 Hz
        return (txt, col, step, prog_step, ctx.preset)

    def render(self, ctx, size):
        w, h = size
        img = self.base(size)
        d = ImageDraw.Draw(img)
        txt, col, prog = self._pick(ctx)
        frame = ctx.frame or 0
        step = min(FADE_FRAMES, max(0, frame - self._since_frame))
        fill = _mix(L.COLORS["panel"], col, _ease_out(step / float(FADE_FRAMES)))
        maxw = w - 2 * L.PAD
        d.text((L.PAD, 7), L.truncate(self.FONT, self.SIZE, txt, maxw), font=L.font(self.FONT, self.SIZE), fill=fill)
        if prog:
            accent = L.preset(ctx.preset)["accent"]
            p = ((ctx.now or 0.0) % ROTATE_S) / ROTATE_S
            p = int(p * 20) / 20.0
            x1 = L.PAD + int(maxw * p)
            d.line([(L.PAD, h - 2), (L.PAD + maxw, h - 2)], fill=L.COLORS["hairline"], width=1)
            if x1 > L.PAD:
                d.line([(L.PAD, h - 2), (x1, h - 2)], fill=_mix(L.COLORS["panel"], accent, 0.55), width=1)
        return img


# =============================================================================== message pane
class ChatPane(Panel):
    key, region = "chat_pane", "chat_pane"
    LINE_H = 26
    FONT, SIZE = "Menlo", 22

    def __init__(self):
        self._strip_key = None
        self._strip: Optional[Image.Image] = None
        self._strip_new_rows = 0          # rows belonging to the newest message (for highlight + slide)
        self._newest_id = None
        self._slide_frame = -10 ** 9
        self._first_ids_seen = False

    # ------------------------------------------------------------------ model
    @staticmethod
    def _msgs(ctx) -> List[Dict]:
        msgs = ctx.chat or []
        return [m for m in msgs if isinstance(m, dict)][-10:]

    def _highlight_step(self, ctx, msgs) -> int:
        if not msgs:
            return 0
        t = msgs[-1].get("show_t")
        if t is None:
            t = msgs[-1].get("t")
        if t is None:
            return 0
        f = 1.0 - ((ctx.now or 0.0) - float(t)) / HIGHLIGHT_S
        if f <= 0:
            return 0
        return min(HIGHLIGHT_STEPS, int(f * HIGHLIGHT_STEPS) + 1)

    def inputs(self, ctx):
        on = display_on(ctx)
        msgs = self._msgs(ctx) if on else []
        ids = tuple(str(m.get("id")) for m in msgs)
        newest = ids[-1] if ids else None
        frame = ctx.frame or 0
        if newest != self._newest_id:
            # the first message set we ever see (boot history) does not slide
            if self._first_ids_seen and newest is not None:
                self._slide_frame = frame
            self._newest_id = newest
        self._first_ids_seen = True
        slide = min(SLIDE_FRAMES, max(0, frame - self._slide_frame))
        return (ids, self._highlight_step(ctx, msgs), slide, on, bool(ctx.mod_paused), ctx.preset)

    # ------------------------------------------------------------------ text strip (cached)
    def _rows(self, ctx, msgs, maxw, max_rows: int = 0) -> Tuple[List[Tuple[List, bool]], int]:
        """-> (rows, rows_of_newest). row = ([segments], is_newest); segment = (kind, text, colour).
        Built newest-first and stopped once max_rows are filled, so ten 120-char messages never cost
        forty rows of layout when only ten can be shown."""
        accent = L.preset(ctx.preset)["accent"]
        indent = "  "
        indent_w = mono_width(self.SIZE, indent)
        chunks: List[List[Tuple[List, bool]]] = []
        new_rows = 0
        n_rows = 0
        for idx in range(len(msgs) - 1, -1, -1):
            if max_rows and n_rows >= max_rows:
                break
            m = msgs[idx]
            name = m.get("display_name") or m.get("name") or "?"
            name = L.strip_non_bmp(str(name)) or "?"
            ncol = L.name_color(name, ctx.preset)
            segs: List[Tuple[str, str, object]] = [("text", name, ncol)]
            if m.get("first_ever") and m.get("builder_n"):
                segs.append(("text", " #%d" % int(m["builder_n"]), accent))
            kind = m.get("kind")
            accepted = m.get("accepted", True)
            body = m.get("text_clean")
            if body is None:
                body = L.strip_non_bmp(str(m.get("text") or ""))
            if kind == "vote" and m.get("letter"):
                segs.append(("chip", str(m["letter"])[:1].upper(), accent if accepted else L.COLORS["text2"]))
                if body.strip().lstrip("!").upper() == str(m.get("letter")).upper():
                    body = ""                                   # the chip already says it
            elif kind in TAGS:
                label, col = TAGS[kind]
                arg = L.strip_non_bmp(str(m.get("arg") or ""))
                if kind == "theme" and accepted and arg:
                    label, body = "theme: %s" % arg, ""          # the tag already says it
                elif kind == "idea" and arg:
                    body = arg                                  # show the idea text, not "!idea ..."
                elif kind == "ask":
                    if not accepted:
                        label = "ask (off)"
                    if arg:
                        body = arg
                segs.append(("tag", label, L.COLORS.get(col, L.COLORS["text2"])))
            if body:
                segs.append(("text", ": ", L.COLORS["text2"]))
            pw = sum(self._seg_w(k, t) for k, t, _ in segs)
            lines = mono_wrap2(self.SIZE, body, max(60, maxw - pw), maxw - indent_w, MAX_LINES_PER_MSG) if body else [""]
            newest = idx == len(msgs) - 1
            msg_rows = [(segs + [("text", lines[0], L.COLORS["text"])], newest)]
            for extra in lines[1:]:
                msg_rows.append(([("text", indent + extra, L.COLORS["text"])], newest))
            chunks.append(msg_rows)
            n_rows += len(msg_rows)
            if newest:
                new_rows = len(msg_rows)
        rows: List[Tuple[List, bool]] = []
        for msg_rows in reversed(chunks):
            rows.extend(msg_rows)
        if max_rows and len(rows) > max_rows:
            rows = rows[-max_rows:]
        return rows, new_rows

    def _seg_w(self, kind: str, text: str) -> int:
        if kind == "chip":
            return 30
        if kind == "tag":
            return mono_width(20, text) + 14
        return mono_width(self.SIZE, text)

    def _build_strip(self, ctx, msgs, w: int, max_rows: int = 0) -> Tuple[Image.Image, int]:
        maxw = w - 2 * L.PAD
        rows, new_rows = self._rows(ctx, msgs, maxw, max_rows)
        strip = Image.new("RGBA", (w, max(1, self.LINE_H * len(rows))), (0, 0, 0, 0))
        d = ImageDraw.Draw(strip)
        f = L.font(self.FONT, self.SIZE)
        f_small = L.font("Menlo Bold", 20)
        f_tag = L.font("Menlo", 20)
        y = 0
        for segs, _newest in rows:
            x = L.PAD
            for kind, text, col in segs:
                if kind == "chip":
                    # 24x22 rounded chip, letter in bg colour so it reads at 320x180 too
                    d.rounded_rectangle([x + 4, y + 1, x + 26, y + 23], radius=4, fill=col)
                    tw = mono_width(20, text)
                    d.text((x + 15 - tw // 2, y + 1), text, font=f_small, fill=L.COLORS["bg"])
                    x += 30
                elif kind == "tag":
                    tw = mono_width(20, text)
                    d.rounded_rectangle([x + 4, y + 2, x + tw + 10, y + 23], radius=4, outline=col, width=1)
                    d.text((x + 7, y + 1), text, font=f_tag, fill=col)
                    x += tw + 14
                else:
                    d.text((x, y), text, font=f, fill=col)
                    x += mono_width(self.SIZE, text)
            y += self.LINE_H
        return strip, new_rows

    # ------------------------------------------------------------------ render
    def render(self, ctx, size):
        w, h = size
        img = self.base(size)
        d = ImageDraw.Draw(img)
        accent = L.preset(ctx.preset)["accent"]
        f = L.font(self.FONT, self.SIZE)
        if not display_on(ctx):
            d.text((L.PAD, h // 2 - 13), "chat hidden by mod", font=f, fill=L.COLORS["warn"])
            return img
        msgs = self._msgs(ctx)
        top = 6
        if ctx.mod_paused:
            d.text((L.PAD, 4), L.truncate("Menlo", 20, "chat paused by mod · votes still count", w - 2 * L.PAD),
                   font=L.font("Menlo", 20), fill=L.COLORS["warn"])
            d.line([(L.PAD, 30), (w - L.PAD, 30)], fill=L.COLORS["hairline"], width=1)
            top = 34
        if not msgs:
            d.text((L.PAD, h // 2 - 26), "chat is empty.", font=f, fill=L.COLORS["text2"])
            d.text((L.PAD, h // 2 + 2), "be the first: type A", font=f, fill=L.COLORS["text"])
            return img

        avail_h = h - top - 6
        max_rows = max(1, avail_h // self.LINE_H)
        skey = (tuple(str(m.get("id")) for m in msgs), ctx.preset, w, max_rows)
        if skey != self._strip_key or self._strip is None:
            self._strip, self._strip_new_rows = self._build_strip(ctx, msgs, w, max_rows)
            self._strip_key = skey
        strip = self._strip
        total_rows = strip.size[1] // self.LINE_H
        shown_rows = min(total_rows, max_rows)
        crop = strip.crop((0, strip.size[1] - shown_rows * self.LINE_H, w, strip.size[1]))

        # slide: the column arrives from below over SLIDE_FRAMES frames (ease-out)
        frame = ctx.frame or 0
        k = min(SLIDE_FRAMES, max(0, frame - self._slide_frame))
        offset = 0
        if k < SLIDE_FRAMES and self._strip_new_rows:
            offset = int(round(self.LINE_H * self._strip_new_rows * (1.0 - _ease_out(k / float(SLIDE_FRAMES)))))
        y0 = h - 6 - crop.size[1] + offset

        # highlight under the newest message (1 s fade, 10 steps)
        step = self._highlight_step(ctx, msgs)
        if step > 0 and self._strip_new_rows:
            a = int(70 * (step / float(HIGHLIGHT_STEPS)))
            ny0 = y0 + crop.size[1] - self._strip_new_rows * self.LINE_H
            ny1 = min(h - 2, y0 + crop.size[1] - 2)
            if ny1 > ny0:
                d.rectangle([4, max(top, ny0 - 1), w - 5, ny1], fill=tuple(list(_rgb(accent)) + [a]))
                d.rectangle([4, max(top, ny0 - 1), 6, ny1], fill=accent)
        # paste through a mask so the slide never draws over the header line / paused line
        window = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        window.paste(crop, (0, y0), crop)
        if top > 1:
            cut = Image.new("RGBA", (w, top), (0, 0, 0, 0))
            window.paste(cut, (0, 0))
        img.alpha_composite(window)
        return img


register(ChatPinned())
register(ChatPane())
