"""hud.py - SETTLEMENT HUD style sheet (studio-a).

Principle: text lives in two bands that never overlap the world: a 72 px header and a 208 px footer.
The world region is 1280x440 in between (y = 72..512). The only text allowed on the world is a
creature's own speech (a small plate that appears when they talk, in their colour) and the vote
markers for a live event. Every glyph is >= 20 px. Panels are warm plum, translucent, 1 px gold
hairline; headings in a rounded face so the whole thing feels like a picture book, not a dashboard.
"""
from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
HEADER_H = 72
WORLD_Y0 = 72
WORLD_H = 440
FOOTER_Y0 = WORLD_Y0 + WORLD_H     # 512
FOOTER_H = H - FOOTER_Y0           # 208

STYLE = {
    "font_title": ("/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf", 0),   # headings, the big number
    "font_body": ("/System/Library/Fonts/Avenir Next.ttc", 5),                          # Medium: panel body, speech
    "font_body_bold": ("/System/Library/Fonts/Avenir Next.ttc", 2),                     # Demi Bold: names, header
    "font_mono": ("/System/Library/Fonts/Menlo.ttc", 0),                                # debug / seed line only
    "size_title": 40,      # the one big line in the header
    "size_heading": 22,    # panel headings
    "size_body": 21,       # panel body
    "size_small": 20,      # the smallest glyph anywhere (footer status)
    "size_speech": 20,     # speech plates on the world
    "panel_fill": (58, 40, 62, 226),          # warm plum, translucent
    "panel_fill_dark": (40, 28, 46, 240),
    "panel_border": (222, 178, 96, 200),      # gold hairline
    "panel_radius": 14,
    "ink": (250, 242, 228),                   # cream text
    "ink_muted": (204, 186, 172),
    "accent": (246, 196, 100),                # gold
    "live": (240, 82, 82),
    "plate_fill": (30, 22, 34, 178),          # speech plate
    "plate_ink": (252, 246, 236),
    "header_fill": (46, 32, 52, 255),
    "footer_fill": (46, 32, 52, 255),
    "divider": (222, 178, 96, 90),
}

_F = {}


def font(kind, size):
    key = (kind, size)
    if key not in _F:
        path, idx = STYLE["font_" + kind]
        _F[key] = ImageFont.truetype(path, size, index=idx)
    return _F[key]


def text_w(d, s, f):
    x0, y0, x1, y1 = d.textbbox((0, 0), s, font=f)
    return x1 - x0


def panel(layer, box, title=None, fill=None):
    """Draw a rounded translucent panel on an RGBA layer; returns the content box (x, y, x1, y1)."""
    d = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=STYLE["panel_radius"], fill=fill or STYLE["panel_fill"], outline=STYLE["panel_border"], width=1)
    cy = y0 + 10
    if title:
        d.text((x0 + 14, cy), title, font=font("title", STYLE["size_heading"]), fill=STYLE["accent"])
        cy += STYLE["size_heading"] + 8
        d.line([x0 + 14, cy - 2, x1 - 14, cy - 2], fill=STYLE["divider"], width=1)
        cy += 4
    return (x0 + 14, cy, x1 - 14, y1 - 10)


def lines(layer, cbox, rows, size=None, gap=4):
    """rows: list of str or list of [(text, colour), ...] segments. Never draws past the content box:
    a row that would overflow is cut with an ellipsis, rows past the bottom are dropped."""
    d = ImageDraw.Draw(layer)
    f = font("body", size or STYLE["size_body"])
    x, y = cbox[0], cbox[1]
    maxw = cbox[2] - cbox[0]
    for row in rows:
        if y + f.size > cbox[3]:
            break
        if isinstance(row, str):
            row = [(row, STYLE["ink"])]
        cx = x
        for seg, col in row:
            w = text_w(d, seg, f)
            if cx - x + w > maxw:
                room = maxw - (cx - x)
                while seg and text_w(d, seg + "…", f) > room:
                    seg = seg[:-1]
                seg = (seg.rstrip() + "…") if seg else ""
                if seg:
                    d.text((cx, y), seg, font=f, fill=col)
                break
            d.text((cx, y), seg, font=f, fill=col)
            cx += w
        y += f.size + gap
    return y


def speech_plate(layer, anchor_xy, text, name, name_colour, above=True):
    """A small rounded plate above a creature: '@name' in their colour, then what they said. 20 px."""
    d = ImageDraw.Draw(layer)
    fn = font("body_bold", STYLE["size_speech"])
    ft = font("body", STYLE["size_speech"])
    nm = "@" + name
    w_name = text_w(d, nm, fn)
    w_text = text_w(d, text, ft)
    pad = 10
    w = w_name + 10 + w_text + pad * 2
    h = STYLE["size_speech"] + 14
    ax, ay = anchor_xy
    x0 = int(min(max(ax - w / 2, 4), W - w - 4))
    y0 = int(ay - h - 10) if above else int(ay + 6)
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=10, fill=STYLE["plate_fill"], outline=(name_colour[0], name_colour[1], name_colour[2], 200), width=1)
    # tail
    tx = int(min(max(ax, x0 + 14), x0 + w - 14))
    if above:
        d.polygon([(tx - 6, y0 + h - 1), (tx + 6, y0 + h - 1), (tx, y0 + h + 7)], fill=STYLE["plate_fill"])
    d.text((x0 + pad, y0 + 6), nm, font=fn, fill=name_colour)
    d.text((x0 + pad + w_name + 10, y0 + 6), text, font=ft, fill=STYLE["plate_ink"])
    return (x0, y0, x0 + w, y0 + h)


def name_tag(layer, anchor_xy, name, name_colour, suffix=""):
    """Tiny name plate under a creature (show-on-speak / on hover in crowds)."""
    d = ImageDraw.Draw(layer)
    f = font("body_bold", STYLE["size_small"])
    s = "@" + name + suffix
    w = text_w(d, s, f) + 14
    h = STYLE["size_small"] + 8
    x0 = int(anchor_xy[0] - w / 2)
    y0 = int(anchor_xy[1] + 2)
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=8, fill=STYLE["plate_fill"])
    d.text((x0 + 7, y0 + 3), s, font=f, fill=name_colour)


def header(layer, channel, subtitle, big, live_text, right2):
    d = ImageDraw.Draw(layer)
    d.rectangle([0, 0, W, HEADER_H], fill=STYLE["header_fill"])
    d.line([0, HEADER_H - 1, W, HEADER_H - 1], fill=STYLE["panel_border"], width=1)
    d.text((18, 10), channel, font=font("body", STYLE["size_small"]), fill=STYLE["ink_muted"])
    d.text((18, 38), subtitle, font=font("body_bold", STYLE["size_small"]), fill=STYLE["ink"])
    ft = font("title", STYLE["size_title"])
    parts = [p.strip() for p in big.split("·")]          # the rounded face has no middle dot: draw one
    dot_gap = 44
    bw = sum(text_w(d, p, ft) for p in parts) + dot_gap * (len(parts) - 1)
    cx = (W - bw) / 2
    for i, p in enumerate(parts):
        d.text((cx, 12), p, font=ft, fill=STYLE["ink"])
        cx += text_w(d, p, ft)
        if i < len(parts) - 1:
            d.ellipse([cx + dot_gap / 2 - 5, 32, cx + dot_gap / 2 + 5, 42], fill=STYLE["accent"])
            cx += dot_gap
    fr = font("body_bold", STYLE["size_small"])
    lw = text_w(d, live_text, fr)
    d.ellipse([W - 18 - lw - 26, 16, W - 18 - lw - 12, 30], fill=STYLE["live"])
    d.text((W - 18 - lw, 10), live_text, font=fr, fill=STYLE["ink"])
    fr2 = font("body", STYLE["size_small"])
    d.text((W - 18 - text_w(d, right2, fr2), 38), right2, font=fr2, fill=STYLE["accent"])


STATUS_Y = H - 28          # the 20 px status strip under the panels
PANEL_Y0 = FOOTER_Y0 + 10
PANEL_Y1 = STATUS_Y - 6    # panels are 512+10 .. 686


def footer_base(layer, status=""):
    d = ImageDraw.Draw(layer)
    d.rectangle([0, FOOTER_Y0, W, H], fill=STYLE["footer_fill"])
    d.line([0, FOOTER_Y0, W, FOOTER_Y0], fill=STYLE["panel_border"], width=1)
    if status:
        d.text((14, STATUS_Y + 2), status, font=font("body", STYLE["size_small"]), fill=STYLE["ink_muted"])


def sun_dial(layer, box, hour, evening):
    """Little day-wheel: sky gradient with the sun/moon position. Purely decorative, no text."""
    d = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = box
    sky = (236, 150, 96) if evening else (176, 196, 226)
    d.rounded_rectangle(box, radius=10, fill=sky + (255,), outline=STYLE["panel_border"])
    t = (hour - 6) / 12.0
    import math
    cx = x0 + 10 + (x1 - x0 - 20) * max(0, min(1, t))
    cy = y1 - 10 - (y1 - y0 - 24) * math.sin(math.pi * max(0, min(1, t)))
    d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=(255, 226, 130) if not evening else (255, 190, 90))
    d.rectangle([x0 + 1, y1 - 9, x1 - 1, y1 - 1], fill=(96, 132, 70, 255))
