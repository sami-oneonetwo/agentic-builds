"""Next up (region 14, CONCEPT 3 row 14): the macro agenda. `NEXT UP (macro)` + up to 3 rows (Menlo 20, 26 px
apart at region y 36 / 62 / 88, so the last row ends at y 112 inside the 120 px box).

Rows, in order: the macro build in progress (`now: <title> · <step_label>`, accent) when `macro.active`,
then `!idea` entries that are not shipped, sorted by open-before-declined, `plus` descending, oldest first:
  @name: idea text                                 +N        (name in its palette colour, +N in accent)
  @name: idea text                                 macro     (class chip when nobody has +1'd it yet)
  declined: <reason> · idea text                             (grey, never silently dropped)
Header right: `no agent on duty` (amber) when agent.on_duty is false or the heartbeat is older than 120 s.
Empty: `no agent on duty. backlog open, next session ships it.` / `backlog empty.` + the !idea hint.
`chat.display=false` (!kill) replaces every requester name with `chat hidden by mod`.

Data: ctx.ideas[] {id,text,by,ts,plus,class,status,reason}, ctx.macro, ctx.agent, ctx.chat_display, ctx.preset, ctx.now.
"""
from __future__ import annotations

from PIL import ImageDraw

from stream import layout as L
from stream.panels import Panel, register
from stream.state_store import iso_to_epoch

HEARTBEAT_S = 120.0
ROW_Y = (36, 62, 88)
HIDDEN = "chat hidden by mod"


class NextUp(Panel):
    key, region = "next_up", "next_up"

    # ------------------------------------------------------------------ model
    @staticmethod
    def _display(ctx) -> bool:
        return True if ctx.chat_display is None else bool(ctx.chat_display)

    @staticmethod
    def _on_duty(ctx) -> bool:
        ag = ctx.agent if isinstance(ctx.agent, dict) else {}
        hb = iso_to_epoch(ag.get("heartbeat_ts"))
        return bool(ag.get("on_duty")) and hb is not None and ctx.now is not None and (ctx.now - hb) < HEARTBEAT_S

    @staticmethod
    def _macro_row(ctx):
        mc = ctx.macro if isinstance(ctx.macro, dict) else {}
        if not mc.get("active") or not mc.get("title"):
            return None
        return {"kind": "macro", "title": L.strip_non_bmp(str(mc.get("title"))), "by": mc.get("requested_by"),
                "step": L.strip_non_bmp(str(mc.get("step_label") or mc.get("step") or ""))}

    def _rows(self, ctx):
        ideas = [i for i in (ctx.ideas or []) if isinstance(i, dict) and i.get("status") != "shipped"]

        def order(i):
            return (1 if (i.get("status") == "declined" or i.get("class") == "declined") else 0,
                    -int(i.get("plus") or 0), str(i.get("ts") or ""))
        ideas.sort(key=order)
        rows = []
        mr = self._macro_row(ctx)
        if mr:
            rows.append(mr)
        for i in ideas:
            rows.append({"kind": "idea", "id": i.get("id"), "by": L.strip_non_bmp(str(i.get("by") or "")),
                         "text": L.strip_non_bmp(str(i.get("text") or "")).strip(), "plus": int(i.get("plus") or 0),
                         "cls": str(i.get("class") or ""), "declined": i.get("status") == "declined" or i.get("class") == "declined",
                         "reason": L.strip_non_bmp(str(i.get("reason") or "")).strip()})
        return rows[:3]

    # ------------------------------------------------------------------ Panel API
    def inputs(self, ctx):
        return (tuple(tuple(sorted(r.items())) for r in self._rows(ctx)), self._on_duty(ctx), self._display(ctx), ctx.preset)

    def render(self, ctx, size):
        w, h = size
        img = self.base(size)
        d = ImageDraw.Draw(img)
        accent = L.preset(ctx.preset)["accent"]
        fh, f = L.font("HN Medium", 22), L.font("Menlo", 20)
        display = self._display(ctx)
        on_duty = self._on_duty(ctx)
        maxw = w - 2 * L.PAD

        d.text((L.PAD, 6), "NEXT UP (macro)", font=fh, fill=L.COLORS["text2"])
        if not on_duty:
            tag = "no agent on duty"
            d.text((w - L.PAD - L.text_width("Menlo", 20, tag), 8), tag, font=f, fill=L.COLORS["warn"])

        rows = self._rows(ctx)
        if not rows:
            if not on_duty:
                d.text((L.PAD, ROW_Y[0]), L.truncate("Menlo", 20, "no agent on duty. backlog open,", maxw), font=f, fill=L.COLORS["text2"])
                d.text((L.PAD, ROW_Y[1]), L.truncate("Menlo", 20, "next session ships it.", maxw), font=f, fill=L.COLORS["text2"])
            else:
                d.text((L.PAD, ROW_Y[0]), L.truncate("Menlo", 20, "backlog empty. nominate one:", maxw), font=f, fill=L.COLORS["text2"])
            d.text((L.PAD, ROW_Y[2]), L.truncate("Menlo", 20, "!idea <what should change>", maxw), font=f, fill=L.COLORS["text"])
            return img

        for r, y in zip(rows, ROW_Y):
            if r["kind"] == "macro":
                who = ("@%s" % r["by"]) if (r["by"] and display) else (HIDDEN if r["by"] else "")
                txt = "now: %s%s%s" % (r["title"], (" · " + r["step"]) if r["step"] else "", (" · " + who) if who else "")
                d.text((L.PAD, y), L.truncate("Menlo", 20, txt, maxw), font=f, fill=accent)
                continue
            if r["declined"]:
                txt = "declined: %s · %s" % (r["reason"] or "no reason given", r["text"])
                d.text((L.PAD, y), L.truncate("Menlo", 20, txt, maxw), font=f, fill=L.COLORS["text2"])
                continue
            # right tag: +N (accent) when others repeated it, else the agent's class chip
            tag, tcol = "", L.COLORS["text2"]
            if r["plus"] > 0:
                tag, tcol = "+%d" % r["plus"], accent
            elif r["cls"] in ("instant", "macro"):
                tag = r["cls"]
            tagw = (L.text_width("Menlo", 20, tag) + 12) if tag else 0
            if tag:
                d.text((w - L.PAD - L.text_width("Menlo", 20, tag), y), tag, font=f, fill=tcol)
            # left: @name in its palette colour, then ": text"
            x = L.PAD
            if r["by"]:
                name = ("@" + r["by"]) if display else HIDDEN
                ncol = L.name_color(r["by"], ctx.preset) if display else L.COLORS["warn"]
                # a username gets half the row; the fixed kill-switch label keeps its full 18 glyphs (216 px)
                name = L.truncate("Menlo", 20, name, max(48, (maxw - tagw) // 2) if display else maxw - tagw - 72)
                d.text((x, y), name, font=f, fill=ncol)
                x += L.text_width("Menlo", 20, name)
                d.text((x, y), ": ", font=f, fill=L.COLORS["text2"])
                x += L.text_width("Menlo", 20, ": ")
            body_w = w - L.PAD - tagw - x
            if body_w >= 36:
                d.text((x, y), L.truncate("Menlo", 20, r["text"] or "(empty idea)", body_w), font=f, fill=L.COLORS["text"])
        return img


register(NextUp())
