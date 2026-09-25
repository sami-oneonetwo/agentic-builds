"""stream/panels/ask_card.py - ask / answer card (region 13: 840,412,440,124; HN 24 / Menlo 20).

state.ask.enabled = true  (responder attached, CONCEPT 3 #13)
    current set : `@name asked: <q>` (HN 24, 1 line) then the answer typed at micro.typewriter_cps
                  (default 40 chars/s) from ask.current.answered_ts, HN 24 wrapped, up to 3 lines
                  (a 4th line does not fit under a question row in 124 px; the last line ends with …),
                  a steady accent cursor block while typing (no blink), `answering… (queue N)` while
                  the answer is null.
    no current  : `your question here:` / `!ask <anything>, answered on screen` (+ `last: @by · q`).
state.ask.enabled = false (v1 default): the LAST SHIP card, all real:
    LAST SHIP                              shipped 12 · failed 2
    v0.3.12 · palette ember                                (HN 24)
    @sam · 7f3a1c2         or  agent pick · no commit      (Menlo 20, accent / text2)
    2 votes of 3 · 4 min ago                               (Menlo 20, "ago" re-rendered every 10 s)
    A failed ship (ships.jsonl ok=false) draws BUILD FAILED in red with the error.
    Nothing shipped yet: `nothing shipped yet.` + the real countdown to the first ship.
    When the version string changes the card gets one 25 % accent tint fading over 10 frames (<= 400 ms).
Source: the newer of ctx.ships[-1] (ships.jsonl) and ctx.round.last_result. Names come from those
records only; with the chat kill switch on the picker reads `chat hidden by mod`.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from PIL import ImageDraw

from stream import layout as L
from stream.panels import Panel, register
from stream.state_store import iso_to_epoch

FLASH_FRAMES = 10
ANSWER_LINES = 3
ANSWER_CAP = 280
AGO_STEP_S = 10


def _mix(a: str, b: str, f: float) -> Tuple[int, int, int]:
    f = 0.0 if f < 0 else (1.0 if f > 1 else f)
    ra, rb = L.hex_rgb(a), L.hex_rgb(b)
    return tuple(int(round(ra[i] + (rb[i] - ra[i]) * f)) for i in range(3))


def _display_on(ctx) -> bool:
    if ctx.chat_display is False:
        return False
    if (ctx.chat_cfg or {}).get("display") is False:
        return False
    return True


def _ago(now: float, t: Optional[float]) -> str:
    if t is None:
        return ""
    s = int(max(0.0, now - t)) // AGO_STEP_S * AGO_STEP_S
    if s < AGO_STEP_S:
        return "just now"
    if s < 60:
        return "%d s ago" % s
    m = s // 60
    if m < 60:
        return "%d min ago" % m
    return "%d h %02d min ago" % (m // 60, m % 60)


def _mmss(sec: float) -> str:
    sec = int(max(0.0, sec))
    return "%02d:%02d" % (sec // 60, sec % 60)


class AskCard(Panel):
    key, region = "ask_card", "ask_card"

    def __init__(self):
        self._ver: Optional[str] = None
        self._flash_frame = -10 ** 9
        self._answer_seen: Dict[Tuple, float] = {}       # (by, question) -> now when the answer first appeared

    # ------------------------------------------------------------------ model
    @staticmethod
    def _last_ship(ctx) -> Optional[Dict]:
        ships = [s for s in (ctx.ships or []) if isinstance(s, dict) and s.get("version")]
        cand = []
        if ships:
            cand.append(dict(ships[-1]))
        lr = (ctx.round or {}).get("last_result") or {}
        if lr.get("version"):
            d = dict(lr)
            d.setdefault("ok", True)
            cand.append(d)
        if not cand:
            return None
        cand.sort(key=lambda s: iso_to_epoch(s.get("ts")) or 0.0)
        best = cand[-1]
        if best.get("votes") is None:
            # round.last_result carries no tally for seeded / older ships: take it from the matching ships.jsonl line
            # (stage._ship_failed does the same lookup) so a real vote is never reported as "no tally"
            for sh in reversed(ships):
                if sh.get("version") == best.get("version"):
                    for k in ("votes", "total_votes", "kind", "commit", "picked_by", "agent_pick", "ok"):
                        if best.get(k) is None and sh.get(k) is not None:
                            best[k] = sh[k]
                    break
        return best

    def _cps(self, ctx) -> float:
        try:
            cps = float((ctx.micro or {}).get("typewriter_cps") or 40)
        except Exception:
            cps = 40.0
        return min(200.0, max(10.0, cps))

    def _typed(self, ctx, cur: Dict) -> Tuple[str, bool]:
        """-> (answer text revealed so far, done)"""
        ans = L.strip_non_bmp(str(cur.get("answer") or ""))[:ANSWER_CAP]
        if not ans:
            return "", False
        key = (cur.get("by"), cur.get("question"))
        t0 = iso_to_epoch(cur.get("answered_ts"))
        if t0 is None:
            t0 = self._answer_seen.setdefault(key, ctx.now or 0.0)
        n = int(max(0.0, (ctx.now or 0.0) - t0) * self._cps(ctx))
        if n >= len(ans):
            return ans, True
        return ans[:n], False

    def inputs(self, ctx):
        ask = ctx.ask or {}
        frame = ctx.frame or 0
        ver = (ctx.version or {}).get("string")
        if ver != self._ver:
            if self._ver is not None:
                self._flash_frame = frame            # a ship just landed: one tint fade
            self._ver = ver
        flash = min(FLASH_FRAMES, max(0, frame - self._flash_frame))
        if ask.get("enabled"):
            cur = ask.get("current") or {}
            shown, done = self._typed(ctx, cur) if cur else ("", True)
            last = ask.get("last") or {}
            return ("ask", cur.get("by"), cur.get("question"), len(shown), done, len(ask.get("queue") or []),
                    last.get("by"), last.get("question"), ctx.preset, _display_on(ctx))
        ls = self._last_ship(ctx) or {}
        rem = ctx.round_remaining
        return ("ship", ls.get("version"), ls.get("title"), ls.get("picked_by"), ls.get("commit"), ls.get("ok"),
                ls.get("votes"), ls.get("total_votes"), _ago(ctx.now or 0.0, iso_to_epoch(ls.get("ts"))),
                (ctx.version or {}).get("shipped"), (ctx.version or {}).get("failed"),
                (None if ls else _mmss(rem) if rem is not None else None), flash, _display_on(ctx), ctx.preset)

    # ------------------------------------------------------------------ render
    def render(self, ctx, size):
        w, h = size
        accent = L.preset(ctx.preset)["accent"]
        frame = ctx.frame or 0
        flash = min(FLASH_FRAMES, max(0, frame - self._flash_frame))
        fill = L.COLORS["panel"]
        if flash < FLASH_FRAMES:
            fill = _mix(L.COLORS["panel"], accent, 0.25 * (1.0 - flash / float(FLASH_FRAMES)))
        img = self.base(size, fill)
        d = ImageDraw.Draw(img)
        f24, f20 = L.font("HN", 24), L.font("Menlo", 20)
        maxw = w - 2 * L.PAD
        ask = ctx.ask or {}
        if ask.get("enabled"):
            self._render_ask(ctx, d, w, h, maxw, f24, f20, accent, ask)
        else:
            self._render_ship(ctx, d, w, h, maxw, f24, f20, accent)
        return img

    def _render_ask(self, ctx, d, w, h, maxw, f24, f20, accent, ask) -> None:
        cur = ask.get("current") or {}
        queue_n = len(ask.get("queue") or [])
        if not cur:
            d.text((L.PAD, 4), "your question here:", font=f24, fill=L.COLORS["text2"])
            lines = L.wrap("HN", 24, "!ask <anything>, answered on screen", maxw, max_lines=2)
            y = 32
            for ln in lines:
                d.text((L.PAD, y), ln, font=f24, fill=L.COLORS["text"])
                y += 28
            last = ask.get("last") or {}
            if last.get("question") and y <= h - 26:
                who = ("@%s" % last.get("by")) if (last.get("by") and _display_on(ctx)) else "someone"
                d.text((L.PAD, y + 2), L.truncate("Menlo", 20, "last: %s · %s" % (who, L.strip_non_bmp(str(last.get("question")))), maxw),
                       font=f20, fill=L.COLORS["text2"])
            elif queue_n and y <= h - 26:
                d.text((L.PAD, y + 2), "queue %d" % queue_n, font=f20, fill=L.COLORS["text2"])
            return
        by = cur.get("by") if _display_on(ctx) else "chat hidden by mod"
        q = L.strip_non_bmp(str(cur.get("question") or ""))
        shown, done = self._typed(ctx, cur)
        if not cur.get("answer"):
            qlines = L.wrap("HN", 24, "@%s asked: %s" % (by, q), maxw, max_lines=2)
            y = 4
            for ln in qlines:
                d.text((L.PAD, y), ln, font=f24, fill=L.COLORS["text"])
                y += 28
            d.text((L.PAD, max(y + 6, 66)), "answering… (queue %d)" % queue_n, font=f20, fill=L.COLORS["text2"])
            return
        d.text((L.PAD, 4), L.truncate("HN", 24, "@%s asked: %s" % (by, q), maxw), font=f24, fill=L.COLORS["text2"])
        lines = L.wrap("HN", 24, shown, maxw - 14, max_lines=ANSWER_LINES) if shown else [""]
        y = 32
        for i, ln in enumerate(lines):
            d.text((L.PAD, y), ln, font=f24, fill=L.COLORS["text"])
            if i == len(lines) - 1 and not done:
                cx = L.PAD + L.text_width("HN", 24, ln) + 3
                d.rectangle([cx, y + 3, cx + 10, y + 25], fill=accent)       # steady cursor, no blink
            y += 28

    def _render_ship(self, ctx, d, w, h, maxw, f24, f20, accent) -> None:
        ver = ctx.version or {}
        score = "shipped %s · failed %s" % (ver.get("shipped", 0), ver.get("failed", 0))
        d.text((L.PAD, 4), "LAST SHIP", font=f20, fill=L.COLORS["text2"])
        sw = L.text_width("Menlo", 20, score)
        if sw <= maxw - 120:
            d.text((w - L.PAD - sw, 4), score, font=f20, fill=L.COLORS["text2"])
        ls = self._last_ship(ctx)
        if not ls:
            d.text((L.PAD, 32), "nothing shipped yet.", font=f24, fill=L.COLORS["text"])
            rem = ctx.round_remaining
            if rem is not None and rem >= 0:
                sub = "first ship in %s. vote now" % _mmss(rem)
            elif rem is not None:
                sub = "first ship landing now"
            else:
                sub = "first ship lands after round 1"
            d.text((L.PAD, 64), L.truncate("Menlo", 20, sub, maxw), font=f20, fill=L.COLORS["text2"])
            d.text((L.PAD, 92), L.truncate("Menlo", 20, "type A, B or C in chat", maxw), font=f20, fill=accent)
            return
        ok = ls.get("ok") is not False
        title = L.strip_non_bmp(str(ls.get("title") or ""))
        if ok:
            d.text((L.PAD, 30), L.truncate("HN", 24, "%s · %s" % (ls.get("version"), title), maxw), font=f24, fill=L.COLORS["text"])
        else:
            d.text((L.PAD, 30), L.truncate("HN", 24, "BUILD FAILED · %s" % title, maxw), font=f24, fill=L.COLORS["danger"])
        picked = ls.get("picked_by")
        if ls.get("agent_pick") or not picked:
            who, wcol = "agent pick", L.COLORS["text2"]
        elif _display_on(ctx):
            who, wcol = "@%s" % L.strip_non_bmp(str(picked)), accent
        else:
            who, wcol = "chat hidden by mod", L.COLORS["warn"]
        commit = ls.get("commit") or "no commit"
        d.text((L.PAD, 62), L.truncate("Menlo", 20, "%s · %s" % (who, commit), maxw), font=f20, fill=wcol)
        if ok:
            votes = ls.get("votes")
            total = ls.get("total_votes")
            if votes is None:
                vtxt = "no tally"
            elif total is not None and total != votes:
                vtxt = "%d vote%s of %d" % (int(votes), "" if int(votes) == 1 else "s", int(total))
            else:
                vtxt = "%d vote%s" % (int(votes), "" if int(votes) == 1 else "s")
            ago = _ago(ctx.now or 0.0, iso_to_epoch(ls.get("ts")))
            line = vtxt + ((" · " + ago) if ago else "") + (" · %s" % ls.get("kind") if ls.get("kind") == "macro" else "")
        else:
            line = L.strip_non_bmp(str(ls.get("error") or "reverted to the previous version"))
        d.text((L.PAD, 92), L.truncate("Menlo", 20, line, maxw), font=f20, fill=L.COLORS["text2"] if ok else L.COLORS["danger"])


register(AskCard())
