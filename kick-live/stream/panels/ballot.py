"""Ballot (region 9, CONCEPT 3 row 9): three 264x140 letter cards + the instruction line.

Card (region-relative, geometry from stream.layout): letter AB 56 top-left, option title HN 22 (2 lines),
`idea by @name` for chat-sourced options, 8 px tally bar (share of this round's votes, eased over
EASE_FRAMES = 10 frames with a cubic ease-out, no jumps), `N votes` Menlo 22, the last 3 voter names
Menlo 20 in their hashed palette colours (the newest vote glows for 1 s), a `leading` / `tied` /
`SHIPPED` / `agent pick` tag. The single leading card gets a 2 px accent border and a faint accent
tint; tied leaders share a dimmer border so nobody looks like a winner who is not.

Instruction line (HN Bold 26 accent, layout.BALLOT_INSTRUCTION_Y: the CTA and the deadline are one sentence, so it
re-renders once a second with the clock; QA 2026-09-25 found the old Menlo 20 grey line left no legible CTA above 20 px):
  open, votes            TYPE A, B or C IN CHAT · MOST VOTES SHIP IN 01:23                (accent)
  closing / under 30 s   A LEADS WITH 3 VOTES · CLOSES IN 0:12 · TYPE A, B or C          (or `A AND B TIED AT 2`)
  under 30 s, 0 votes    0 VOTES · YOUR LETTER DECIDES · TYPE A, B or C · 0:12           (amber)
  ship, nobody voted     NOBODY VOTED · AGENT PICKED C · NEXT ONE IS YOURS                (amber)
  ship, voted            SHIPPED v0.1.3 · picked by @sam · next one is yours              (accent)
Honest by construction: every count is len(ctx.tallies[letter]) (ChatBridge, live) or the option's
mirrored voters; at zero votes every bar is empty and every count reads `0 votes`.
`chat.display=false` (!kill) replaces every name with `chat hidden by mod`.

Data: ctx.round.options[] {letter,id,title,source,requested_by,votes,voters}, ctx.tallies, ctx.recent_votes,
ctx.round.phase / last_result, ctx.round_remaining, ctx.chat_display, ctx.preset, ctx.frame (animation clock).
"""
from __future__ import annotations

from PIL import ImageDraw

from stream import layout as L
from stream.panels import Panel, register

EASE_FRAMES = 10            # tally bar ease-out length (CONCEPT 5: 8-10 frames)
GLOW_S = 1.0                # newest vote highlight length, fades in 10 steps (one fade per vote, never a flash)
LETTERS = ("A", "B", "C")
HIDDEN = "chat hidden by mod"


def _mix(hex_a: str, hex_b: str, t: float) -> str:
    """Opaque blend of two palette colours (t = 0 -> a, 1 -> b). Only ever mixes L.COLORS / preset hexes."""
    a, b = L.hex_rgb(hex_a), L.hex_rgb(hex_b)
    t = max(0.0, min(1.0, t))
    return "#%02X%02X%02X" % tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _ease_out(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return 1.0 - (1.0 - u) ** 3


def _mmss(s) -> str:
    s = max(0, int(s or 0))
    return "%02d:%02d" % (s // 60, s % 60)      # same format as the header's NEXT SHIP clock


class Ballot(Panel):
    key, region = "ballot", "ballot"

    def __init__(self):
        # per-letter bar animation: value at t0, target, and the frame the target last changed
        self._anim = {k: {"from": 0.0, "to": 0.0, "t0": -EASE_FRAMES} for k in LETTERS}

    # ------------------------------------------------------------------ model
    @staticmethod
    def _display(ctx) -> bool:
        return True if ctx.chat_display is None else bool(ctx.chat_display)

    def _model(self, ctx):
        rnd = ctx.round if isinstance(ctx.round, dict) else {}
        opts = [o for o in (rnd.get("options") or []) if isinstance(o, dict)][:3]
        tall = ctx.tallies if isinstance(ctx.tallies, dict) else None
        cards = []
        for i, o in enumerate(opts):
            letter = str(o.get("letter") or LETTERS[i]).upper()[:1]
            if tall is not None and letter in tall:
                voters = [str(n) for n in (tall.get(letter) or [])]        # live, within 1 s of the vote
            else:
                voters = [str(n) for n in (o.get("voters") or [])]        # mirrored by RoundEngine
            cards.append({"letter": letter, "title": L.strip_non_bmp(str(o.get("title") or "")).strip(),
                          "votes": len(voters), "voters": voters, "source": o.get("source"),
                          "by": L.strip_non_bmp(str(o.get("requested_by") or "")) or None})
        total = sum(c["votes"] for c in cards)
        return cards, total, rnd

    @staticmethod
    def _leaders(cards, total):
        best = max([c["votes"] for c in cards] or [0])
        if total <= 0 or best <= 0:
            return []
        return [c["letter"] for c in cards if c["votes"] == best]

    def _newest(self, ctx):
        """(letter, name, step) for a vote younger than GLOW_S, step 0..9 so the fade re-renders 10 times."""
        rv = ctx.recent_votes or []
        if not rv:
            return None
        try:
            name, letter, t = max(rv, key=lambda v: v[2])
        except Exception:
            return None
        if t is None or ctx.now is None:
            return None
        age = ctx.now - float(t)
        if age < 0 or age >= GLOW_S:
            return None
        return (str(letter).upper(), str(name), int(age / GLOW_S * 10))

    def _instruction(self, ctx, cards, total, rnd):
        accent = L.preset(ctx.preset)["accent"]
        phase = rnd.get("phase")
        lr = rnd.get("last_result") if isinstance(rnd.get("last_result"), dict) else {}
        rem = ctx.round_remaining
        if phase == "ship" and lr:
            if lr.get("agent_pick") or not lr.get("picked_by"):
                return ("NOBODY VOTED · AGENT PICKED %s · NEXT ONE IS YOURS" % (lr.get("letter") or "?"), L.COLORS["warn"])
            who = ("@%s" % lr.get("picked_by")) if self._display(ctx) else HIDDEN
            return ("SHIPPED %s · picked by %s · next one is yours" % (lr.get("version") or "", who), accent)
        if not cards:
            return ("OPENING THE FIRST ROUND · TYPE A, B or C IN CHAT", L.COLORS["text2"])
        closing = phase == "closing" or (rem is not None and rem < 30)
        if closing and total == 0:
            return ("0 VOTES · YOUR LETTER DECIDES · TYPE A, B or C · %s" % _mmss(rem), L.COLORS["warn"])
        if closing:
            leaders = self._leaders(cards, total)
            best = max(c["votes"] for c in cards)
            if len(leaders) == 1:
                lead = "%s LEADS WITH %d VOTE%s" % (leaders[0], best, "" if best == 1 else "S")
            else:
                lead = "%s TIED AT %d" % (" AND ".join(leaders), best)
            return ("%s · CLOSES IN %s · TYPE A, B or C" % (lead, _mmss(rem)), L.COLORS["text"])
        if rem is None:
            return ("TYPE A, B or C IN CHAT · MOST VOTES SHIPS", accent)
        return ("TYPE A, B or C IN CHAT · MOST VOTES SHIP IN %s" % _mmss(rem), accent)

    # ------------------------------------------------------------------ animation (advanced from inputs(), once per frame)
    def _shown(self, a, frame: int) -> float:
        u = (frame - a["t0"]) / float(EASE_FRAMES)
        return a["from"] + (a["to"] - a["from"]) * _ease_out(u)

    def _sync(self, ctx, cards, total) -> bool:
        frame = int(ctx.frame or 0)
        for c in cards:
            a = self._anim.setdefault(c["letter"], {"from": 0.0, "to": 0.0, "t0": -EASE_FRAMES})
            target = (c["votes"] / float(total)) if total else 0.0
            if abs(target - a["to"]) > 1e-9:
                a["from"], a["to"], a["t0"] = self._shown(a, frame), target, frame
        return any(0 <= frame - a["t0"] < EASE_FRAMES for a in self._anim.values())

    # ------------------------------------------------------------------ Panel API
    def inputs(self, ctx):
        cards, total, rnd = self._model(ctx)
        animating = self._sync(ctx, cards, total)
        lr = rnd.get("last_result") if isinstance(rnd.get("last_result"), dict) else {}
        return (
            tuple((c["letter"], c["title"], c["votes"], tuple(c["voters"][-3:]), c["source"], c["by"]) for c in cards),
            rnd.get("phase"), str(lr.get("letter")), str(lr.get("version")), bool(lr.get("agent_pick")),
            self._instruction(ctx, cards, total, rnd), self._newest(ctx), ctx.preset, self._display(ctx),
            ctx.frame if animating else None,
        )

    def render(self, ctx, size):
        w, h = size
        img = self.base(size, L.COLORS["bg"])
        d = ImageDraw.Draw(img)
        accent = L.preset(ctx.preset)["accent"]
        display = self._display(ctx)
        cards, total, rnd = self._model(ctx)
        phase = rnd.get("phase")
        lr = rnd.get("last_result") if isinstance(rnd.get("last_result"), dict) else {}
        leaders = self._leaders(cards, total)
        newest = self._newest(ctx)
        frame = int(ctx.frame or 0)
        fl, ft, fv, fn = L.font("AB", 56), L.font("HN", 22), L.font("Menlo", 22), L.font("Menlo", 20)
        cw, ch, y0 = L.BALLOT_CARD_W, L.BALLOT_CARD_H, L.BALLOT_CARD_Y

        for i, c in enumerate(cards[:3]):
            x0 = L.BALLOT_CARD_X[i]
            lead = c["letter"] in leaders
            sole = lead and len(leaders) == 1
            shipped = phase == "ship" and str(lr.get("letter")) == c["letter"]
            # card body: leading card tinted + 2 px accent border; tied leaders get a dim border; the rest hairline
            fill = _mix(L.COLORS["panel"], accent, 0.16 if shipped else (0.09 if sole else (0.05 if lead else 0.0)))
            if sole or shipped:
                outline, width = accent, 2
            elif lead:
                outline, width = _mix(L.COLORS["hairline"], accent, 0.55), 2
            else:
                outline, width = L.COLORS["hairline"], 1
            d.rounded_rectangle([x0, y0, x0 + cw - 1, y0 + ch - 1], radius=6, fill=fill, outline=outline, width=width)
            # letter (44 px glyph, rows y0+18..y0+58)
            d.text((x0 + 12, y0 - 4), c["letter"], font=fl, fill=accent if (lead or shipped) else L.COLORS["text"])
            # title: 2 lines HN 22 in the 184 px column right of the letter
            tx, tw = x0 + 68, cw - 68 - 12
            lines = L.wrap("HN", 22, c["title"] or "(untitled option)", tw, max_lines=2) or [""]
            for j, ln in enumerate(lines[:2]):
                d.text((tx, y0 + 10 + j * 26), ln, font=ft, fill=L.COLORS["text"])
            idea_by = None
            if c["source"] == "idea":
                idea_by = "idea by @%s" % c["by"] if (c["by"] and display) else ("idea from chat" if c["by"] else "chat idea")
                if not display and c["by"]:
                    idea_by = "idea by %s" % HIDDEN
                if len(lines) == 1:
                    d.text((tx, y0 + 38), L.truncate("Menlo", 20, idea_by, tw), font=fn, fill=L.COLORS["text2"])
                    idea_by = None                      # shown; the names row is free for names
            # tally bar: share of this round's votes, eased
            bx0, bx1, by = x0 + 12, x0 + cw - 12, y0 + 74
            d.rectangle([bx0, by, bx1 - 1, by + 7], fill=L.COLORS["hairline"])
            frac = self._shown(self._anim.get(c["letter"], {"from": 0.0, "to": 0.0, "t0": -EASE_FRAMES}), frame)
            if frac > 0.0005:
                bw = max(2, int(round((bx1 - bx0) * min(1.0, frac))))
                d.rectangle([bx0, by, bx0 + bw - 1, by + 7], fill=accent)
            # count + right-aligned tag
            n = c["votes"]
            d.text((x0 + 12, y0 + 86), "%d vote%s" % (n, "" if n == 1 else "s"), font=fv,
                   fill=L.COLORS["text"] if n else L.COLORS["text2"])
            tag, tcol = None, L.COLORS["text2"]
            if shipped:
                tag, tcol = ("agent pick" if (lr.get("agent_pick") or not lr.get("picked_by")) else "SHIPPED"), \
                            (L.COLORS["warn"] if (lr.get("agent_pick") or not lr.get("picked_by")) else accent)
            elif sole:
                tag, tcol = "leading", accent
            elif lead:
                tag = "tied"
            if tag:
                d.text((x0 + cw - 12 - L.text_width("Menlo", 20, tag), y0 + 88), tag, font=fn, fill=tcol)
            # names row: last 3 voters in their palette colours; the newest vote glows for 1 s
            ny, maxw = y0 + 112, cw - 24
            if not display and c["voters"]:
                d.text((x0 + 12, ny), L.truncate("Menlo", 20, HIDDEN, maxw), font=fn, fill=L.COLORS["warn"])
            elif c["voters"]:
                if newest and newest[0] == c["letter"]:
                    glow = _mix(fill, accent, 0.35 * (1.0 - newest[2] / 10.0))
                    d.rectangle([x0 + 8, ny - 2, x0 + cw - 9, ny + 22], fill=glow)
                names = [L.truncate("Menlo", 20, nm, maxw - 48) for nm in c["voters"][-3:]]
                prefix = ""
                while names:
                    prefix = ("+%d " % (n - len(names))) if n > len(names) else ""
                    if L.text_width("Menlo", 20, prefix + " ".join(names)) <= maxw:
                        break
                    names.pop(0)
                x = x0 + 12
                if prefix:
                    d.text((x, ny), prefix, font=fn, fill=L.COLORS["text2"])
                    x += L.text_width("Menlo", 20, prefix)
                for k, nm in enumerate(names):
                    is_new = bool(newest) and newest[0] == c["letter"] and newest[1] == c["voters"][-1] and k == len(names) - 1
                    d.text((x, ny), nm, font=fn, fill=accent if is_new else L.name_color(nm, ctx.preset))
                    x += L.text_width("Menlo", 20, nm + " ")
            else:
                hint = "no votes" if phase == "ship" else ("type %s to vote" % c["letter"])   # voting is closed during the ship hold
                d.text((x0 + 12, ny), L.truncate("Menlo", 20, idea_by or hint, maxw), font=fn, fill=L.COLORS["text2"])

        if not cards:
            d.text((L.PAD, 44), "opening the first round…", font=ft, fill=L.COLORS["text2"])

        txt, col = self._instruction(ctx, cards, total, rnd)
        fi_name, fi_size = L.BALLOT_INSTRUCTION_FONT, L.BALLOT_INSTRUCTION_SIZE
        d.text((L.PAD, L.BALLOT_INSTRUCTION_Y), L.truncate(fi_name, fi_size, txt, w - 2 * L.PAD), font=L.font(fi_name, fi_size), fill=col)
        return img


register(Ballot())
