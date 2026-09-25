"""hud.py - studio-b HUD style sheet: warm, quiet frames around a living world.

Principle: the world is the show. Text lives in a 72 px header and a 108 px footer; on the world only
speech bubbles of pips that are speaking right now and their name tags, all >= 20 px.

Fonts (system only):
    TITLE  Arial Rounded Bold      - friendly, matches the glossy pips  (header title, panel titles, counters)
    BODY   Avenir Next Demi Bold   - clean at 20-22 px on a dark panel  (body copy, chat, labels)
    BODY_M Avenir Next Medium      - secondary lines
Sizes: counter 44, title 30, panel title 22, body 22, small 20 (minimum anywhere on screen)
Colours: dark pine panels at 86% over the world, cream text, honey accent, live red, cream speech bubbles.

    draw_panel(overlay, box, title)      rounded panel + title band
    draw_text(draw, xy, s, kind, size)   text with a soft drop shadow
    bubble(overlay, anchor, s)           speech bubble pointing down at a pip
    name_tag(overlay, anchor, name, col) 20 px pill with the pip's colour dot
    header(overlay, ...) / footer_panels(overlay, ...)
    style_sheet(path)                    writes hud_style.png
"""
from __future__ import annotations

import os
from typing import Dict, List, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = {
    "title": ("/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf", 0),
    "body": ("/System/Library/Fonts/Avenir Next.ttc", 2),    # Demi Bold
    "body_m": ("/System/Library/Fonts/Avenir Next.ttc", 5),  # Medium
}
SIZES = {"counter": 44, "title": 30, "panel_title": 22, "body": 22, "small": 20}
C = {
    "panel": (26, 33, 29, 220),
    "panel_edge": (233, 214, 168, 235),
    "panel_inner": (12, 16, 14, 120),
    "text": (247, 241, 226, 255),
    "muted": (196, 201, 186, 255),
    "honey": (242, 188, 84, 255),
    "live": (232, 70, 70, 255),
    "ink": (32, 28, 24, 255),
    "bubble": (250, 246, 236, 240),
    "bubble_edge": (120, 96, 60, 255),
    "tag": (26, 33, 29, 200),
    "header_bar": (242, 188, 84, 255),
}
W, H = 1280, 720
HEADER_H = 72
FOOTER_Y = 604
WORLD = (0, HEADER_H, W, FOOTER_Y)  # x0, y0, x1, y1 -> 1280 x 540

_F: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    key = (kind, size)
    if key not in _F:
        path, idx = FONTS[kind]
        _F[key] = ImageFont.truetype(path, size, index=idx)
    return _F[key]


def draw_text(d: ImageDraw.ImageDraw, xy, s: str, kind="body", size=22, fill=None, shadow=True, anchor="la"):
    f = font(kind, size)
    fill = fill or C["text"]
    if shadow:
        d.text((xy[0] + 1, xy[1] + 2), s, font=f, fill=(0, 0, 0, 140), anchor=anchor)
    d.text(xy, s, font=f, fill=fill, anchor=anchor)


def text_w(s: str, kind="body", size=22) -> int:
    f = font(kind, size)
    return int(f.getlength(s))


def fit(s: str, max_w: int, kind="body", size=22) -> str:
    """Truncate with an ellipsis so a line never runs past its panel."""
    f = font(kind, size)
    if f.getlength(s) <= max_w:
        return s
    while s and f.getlength(s + "…") > max_w:
        s = s[:-1]
    return s.rstrip() + "…"


def draw_panel(ov: Image.Image, box, title: str = None, fill=None, radius=12):
    d = ImageDraw.Draw(ov)
    x0, y0, x1, y1 = box
    d.rounded_rectangle([x0 + 2, y0 + 3, x1 + 2, y1 + 3], radius, fill=(0, 0, 0, 70))  # drop
    d.rounded_rectangle([x0, y0, x1, y1], radius, fill=fill or C["panel"], outline=C["panel_edge"], width=2)
    d.rounded_rectangle([x0 + 3, y0 + 3, x1 - 3, y1 - 3], radius - 3, outline=C["panel_inner"], width=1)
    if title:
        draw_text(d, (x0 + 14, y0 + 8), title, "title", SIZES["panel_title"], C["honey"])
        tw = text_w(title, "title", SIZES["panel_title"])
        d.line([(x0 + 14 + tw + 10, y0 + 22), (x1 - 14, y0 + 22)], fill=(233, 214, 168, 70), width=1)
    return d


def pill(ov: Image.Image, xy, s: str, fill, text_fill=None, size=20, kind="body", pad=10) -> Tuple[int, int]:
    d = ImageDraw.Draw(ov)
    tw = text_w(s, kind, size)
    h = size + 10
    x, y = xy
    d.rounded_rectangle([x, y, x + tw + 2 * pad, y + h], h // 2, fill=fill)
    draw_text(d, (x + pad, y + 3), s, kind, size, text_fill or C["text"], shadow=False)
    return tw + 2 * pad, h


def name_tag(ov: Image.Image, anchor, name: str, colour: Sequence[int], size=20):
    """20 px pill centred above `anchor` (the pip's head), with the pip's colour as a dot."""
    d = ImageDraw.Draw(ov)
    s = "@" + name
    tw = text_w(s, "body", size)
    w, h = tw + 34, size + 8
    x = int(anchor[0] - w / 2)
    y = int(anchor[1] - h - 4)
    d.rounded_rectangle([x, y, x + w, y + h], h // 2, fill=C["tag"], outline=(233, 214, 168, 120), width=1)
    d.ellipse([x + 9, y + h / 2 - 6, x + 21, y + h / 2 + 6], fill=tuple(colour) + (255,), outline=(255, 255, 255, 180))
    draw_text(d, (x + 26, y + 2), s, "body", size, C["text"], shadow=False)
    return (x, y, x + w, y + h)


def bubble(ov: Image.Image, anchor, s: str, size=20, max_w=300, accent=None):
    """Cream speech bubble whose tail points down at `anchor` (pip head). Wraps at max_w."""
    d = ImageDraw.Draw(ov)
    f = font("body", size)
    words, lines, cur = s.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if f.getlength(t) > max_w and cur:
            lines.append(cur)
            cur = w_
        else:
            cur = t
    if cur:
        lines.append(cur)
    lw = max(int(f.getlength(l)) for l in lines)
    pad, lh = 12, size + 6
    bw, bh = lw + 2 * pad, len(lines) * lh + 2 * pad - 4
    x = int(min(max(8, anchor[0] - bw / 2), W - bw - 8))
    y = int(anchor[1] - bh - 14)
    d.rounded_rectangle([x + 2, y + 3, x + bw + 2, y + bh + 3], 10, fill=(0, 0, 0, 60))
    d.rounded_rectangle([x, y, x + bw, y + bh], 10, fill=C["bubble"], outline=C["bubble_edge"], width=2)
    ax = int(anchor[0])
    d.polygon([(ax - 7, y + bh - 1), (ax + 7, y + bh - 1), (ax, y + bh + 10)], fill=C["bubble"], outline=C["bubble_edge"])
    d.line([(ax - 7, y + bh - 1), (ax + 7, y + bh - 1)], fill=C["bubble"], width=3)
    for i, l in enumerate(lines):
        d.text((x + pad, y + pad - 3 + i * lh), l, font=f, fill=accent or C["ink"])
    return (x, y, x + bw, y + bh + 10)


def header(ov: Image.Image, left: List[str], centre: str, right: List[Tuple[str, Sequence[int]]], progress=0.0):
    d = ImageDraw.Draw(ov)
    d.rectangle([0, 0, W, HEADER_H], fill=(26, 33, 29, 255))
    # honey progress bar (next event) along the header bottom
    d.rectangle([0, HEADER_H - 6, W, HEADER_H], fill=(60, 52, 40, 255))
    d.rectangle([0, HEADER_H - 6, int(W * progress), HEADER_H], fill=C["header_bar"])
    draw_text(d, (18, 8), left[0], "body", 22, C["muted"])
    if len(left) > 1:
        draw_text(d, (18, 36), left[1], "body_m", 20, C["muted"])
    # centre counter: parts joined by a drawn dot (the title font has no middle-dot glyph)
    parts = [p.strip() for p in centre.split("|")]
    size = SIZES["counter"]
    gap = 34
    while True:
        f = font("title", size)
        widths = [f.getlength(p) for p in parts]
        total = sum(widths) + gap * (len(parts) - 1)
        if total <= 560 or size <= 32:
            break
        size -= 2
    x = W // 2 - total / 2
    ty = 10 + (SIZES["counter"] - size) // 2
    for i, (p, w_) in enumerate(zip(parts, widths)):
        draw_text(d, (x, ty), p, "title", size, C["text"])
        x += w_
        if i < len(parts) - 1:
            d.ellipse([x + gap / 2 - 5, ty + size * 0.5, x + gap / 2 + 5, ty + size * 0.5 + 10], fill=C["honey"])
            x += gap
    y = 8
    for s, col in right:
        if s.startswith("LIVE"):
            tw = text_w(s, "body", 22)
            d.ellipse([W - 18 - tw - 22, y + 7, W - 18 - tw - 8, y + 21], fill=C["live"])
        draw_text(d, (W - 18, y), s, "body", 22, tuple(col), anchor="ra")
        y += 28


def footer_panels(ov: Image.Image, panels: List[Tuple[str, List[Tuple[str, Sequence[int]]]]], x_split=None):
    """Up to 3 panels across the footer; each = (title, [(line, colour), ...]) with 22 px lines."""
    xs = x_split or [(8, 420), (430, 850), (860, 1272)]
    for (title, lines), (x0, x1) in zip(panels, xs):
        d = draw_panel(ov, (x0, FOOTER_Y + 6, x1, H - 6), title)
        y = FOOTER_Y + 36
        for s, col in lines:
            draw_text(d, (x0 + 14, y), fit(s, x1 - x0 - 28), "body", SIZES["body"], tuple(col))
            y += 25


def minimap_panel(ov: Image.Image, box, mini: Image.Image, caption: str):
    d = draw_panel(ov, box, None)
    x0, y0, x1, y1 = box
    mw, mh = mini.size
    ov.paste(mini, (x0 + (x1 - x0 - mw) // 2, y0 + 8))
    d.rectangle([x0 + (x1 - x0 - mw) // 2 - 1, y0 + 7, x0 + (x1 - x0 - mw) // 2 + mw, y0 + 8 + mh], outline=C["panel_edge"])
    draw_text(d, ((x0 + x1) // 2, y1 - 28), caption, "body", 20, C["muted"], anchor="ma")


# ----------------------------------------------------------------------------- style sheet
def style_sheet(path: str) -> str:
    bg = Image.new("RGBA", (W, H), (110, 168, 78, 255))
    d = ImageDraw.Draw(bg)
    for y in range(HEADER_H, FOOTER_Y, 32):  # faux land so panel alpha can be judged
        for x in range(0, W, 32):
            d.rectangle([x, y, x + 31, y + 31], fill=(104 + ((x // 32 + y // 32) % 3) * 6, 160 + ((x // 32) % 2) * 8, 76, 255))
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    header(ov, ["atleastonce · SETTLEMENT · v0.7", "concept render · names are examples"], "14 SETTLED | 12 AWAKE",
           [("LIVE · 7 watching", C["live"]), ("NEXT EVENT 01:23", C["honey"])], 0.62)
    footer_panels(ov, [
        ("COLONY", [("14 settled · 6 more: the Mill opens", C["text"]), ("12 awake · 2 asleep · day 5", C["text"]),
                    ("last event: rain · by @sami.exe", C["muted"])]),
        ("KEEPER", [("keeper on duty · surveying East Field", C["text"]), ("12:40 left · then the well vote", C["text"]),
                    ("keepers are AI agents", C["muted"])]),
        ("CHAT LOG", [("@kai_dnb  B", C["text"]), ("@sami.exe  we need a bridge over it", C["text"]),
                      ("@noor.wav  planting by the water", C["text"])]),
    ])
    # spec swatches on the world area
    dd = ImageDraw.Draw(ov)
    x = 24
    for name in ("panel", "panel_edge", "text", "muted", "honey", "live", "bubble", "tag"):
        dd.rounded_rectangle([x, 96, x + 56, 152], 8, fill=C[name], outline=(0, 0, 0, 120))
        draw_text(dd, (x, 158), name.replace("panel_", ""), "body_m", 20, C["text"])
        x += 110
    draw_text(dd, (24, 200), "TITLE Arial Rounded Bold 30", "title", 30)
    draw_text(dd, (24, 240), "BODY Avenir Next Demi Bold 22 - the smallest text anywhere is 20 px", "body", 22)
    draw_text(dd, (24, 272), "BODY_M Avenir Next Medium 20 - secondary lines only", "body_m", 20, C["muted"])
    draw_text(dd, (24, 320), "counter 44", "title", 44)
    bubble(ov, (900, 420), "B! the well goes by the plaza", 20)
    name_tag(ov, (900, 440), "kai_dnb", (208, 82, 76))
    bubble(ov, (1100, 420), "planting by the water, who's with me", 20)
    name_tag(ov, (1100, 440), "noor.wav", (86, 168, 96))
    pill(ov, (24, 400), "state pill · 20 px", C["tag"])
    pill(ov, (240, 400), "vote ack", C["honey"], C["ink"])
    draw_text(dd, (24, 460), "rules: world text = bubbles for pips speaking now + their tags (20 px), fade after 4 s;", "body", 22)
    draw_text(dd, (24, 490), "everything else lives in the header (72 px) or footer (108 px). Honey bar = time to next event.", "body", 22)
    draw_text(dd, (24, 520), "panels: dark pine 86 % over the land, 2 px cream edge, 12 px radius, 1 px inner shadow line.", "body", 22)
    out = Image.alpha_composite(bg, ov).convert("RGB")
    out.save(path)
    return path


if __name__ == "__main__":
    print("wrote", style_sheet(os.path.join(os.path.dirname(os.path.abspath(__file__)), "hud_style.png")))
