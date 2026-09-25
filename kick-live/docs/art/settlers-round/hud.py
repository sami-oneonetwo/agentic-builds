"""hud.py - settlers-round HUD style sheet + drawing helpers (SETTLEMENT top-down). From studio-c, plus a settler
HEAD ICON in the show-on-speak pill and chat rows (the head is the settler's portrait; the dot stays as a fallback).

Principle: text lives in the frame around the world, not on it. The world region (1280x440) carries only
show-on-speak name pills (>= 20 px) and creature emotes. Everything else sits in an opaque header (64 px) and a
translucent bottom band (216 px) whose panels are dark, warm and rounded so the world glows through.

Fonts (all from /System/Library/Fonts): Arial Rounded Bold for display, Verdana / Verdana Bold for body and pills.
Every text size is >= 20 px so it survives a 3 Mbps encode and the 320x180 thumb still shows the header shape.

    import hud
    hud.header(img, ...); hud.panel(img, (x0, y0, x1, y1), "COLONY", lines); pill = hud.pill("@kai_dnb", dot=(r,g,b))
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_DISPLAY = "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf"
FONT_BODY = "/System/Library/Fonts/Supplemental/Verdana.ttf"
FONT_BODY_BOLD = "/System/Library/Fonts/Supplemental/Verdana Bold.ttf"

SIZES: Dict[str, int] = {"title": 40, "header": 22, "panel_title": 22, "body": 22, "pill": 20, "caption": 20}
COLOURS: Dict[str, Tuple] = {
    "header_bg": (26, 20, 16),
    "panel": (28, 22, 18, 226),
    "panel_border": (232, 214, 178),
    "cream": (248, 240, 224),
    "muted": (192, 178, 150),
    "gold": (247, 196, 86),
    "live": (238, 72, 60),
    "ok": (126, 206, 128),
    "pill_bg": (28, 22, 18, 232),
    "shadow": (0, 0, 0, 90),
}
LAYOUT: Dict[str, int] = {
    "W": 1280, "H": 720, "header_h": 64, "world_y0": 64, "world_h": 440, "band_y0": 504, "band_h": 192,
    "caption_y0": 696, "caption_h": 24, "gap": 8, "pad": 14, "radius": 12, "border": 2, "line_h": 28,
}
_FONTS: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(kind: str = "body", size: Optional[int] = None) -> ImageFont.FreeTypeFont:
    path = {"display": FONT_DISPLAY, "body": FONT_BODY, "bold": FONT_BODY_BOLD}[kind]
    size = size or SIZES["body"]
    key = (path, size)
    if key not in _FONTS:
        _FONTS[key] = ImageFont.truetype(path, size)
    return _FONTS[key]


def text_w(text: str, f: ImageFont.FreeTypeFont) -> int:
    l, t, r, b = f.getbbox(text)
    return r - l


def display_text(d: ImageDraw.ImageDraw, x: int, y: int, text: str, f: ImageFont.FreeTypeFont, fill) -> int:
    """Display-font text; Arial Rounded has no middle dot, so ' · ' separators are drawn as a real dot."""
    parts = text.split("·")
    size = f.size
    for i, part in enumerate(parts):
        if i:
            r = max(3, size // 9)
            cy = y + int(size * 0.62)
            d.ellipse([x + size * 0.18, cy - r, x + size * 0.18 + 2 * r, cy + r], fill=fill)
            x += int(size * 0.36) + 2 * r
        d.text((x, y), part, font=f, fill=fill)
        x += text_w(part, f)
    return x


def display_w(text: str, f: ImageFont.FreeTypeFont) -> int:
    parts = text.split("·")
    r = max(3, f.size // 9)
    return sum(text_w(p, f) for p in parts) + (len(parts) - 1) * (int(f.size * 0.36) + 2 * r)


def draw_segments(d: ImageDraw.ImageDraw, x: int, y: int, segs: Sequence[Tuple[str, Tuple]], f: ImageFont.FreeTypeFont) -> int:
    for text, colour in segs:
        d.text((x, y), text, font=f, fill=colour)
        x += text_w(text, f)
    return x


def fit_segments(segs: Sequence[Tuple[str, Tuple]], f: ImageFont.FreeTypeFont, width: int) -> List[Tuple[str, Tuple]]:
    """Truncate a segment list to `width` px, ending in an ellipsis. Never lets text run under a widget or off a panel."""
    out, used = [], 0
    for text, colour in segs:
        w = text_w(text, f)
        if used + w <= width:
            out.append((text, colour))
            used += w
            continue
        cut = text
        while cut and text_w(cut + "…", f) > width - used:
            cut = cut[:-1]
        if cut:
            out.append((cut.rstrip() + "…", colour))
        break
    return out


def overlay(img: Image.Image, fn) -> None:
    """Draw with an RGBA layer and alpha-composite it onto `img` (RGB) in place."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    fn(ImageDraw.Draw(layer), layer)
    img.paste(Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB"))


def panel(img: Image.Image, box: Tuple[int, int, int, int], title: str, lines: Sequence[Sequence[Tuple[str, Tuple]]],
          title_colour: Tuple = None, right: Optional[Image.Image] = None) -> None:
    x0, y0, x1, y1 = box
    L = LAYOUT

    def draw(d, layer):
        d.rounded_rectangle([x0, y0, x1, y1], radius=L["radius"], fill=COLOURS["panel"], outline=COLOURS["panel_border"], width=L["border"])
        display_text(d, x0 + L["pad"], y0 + 8, title, font("display", SIZES["panel_title"]), title_colour or COLOURS["gold"])
        y = y0 + 8 + SIZES["panel_title"] + 10
        fb = font("body", SIZES["body"])
        avail_full = x1 - x0 - 2 * L["pad"]
        avail_side = avail_full - (right.width + 10 if right is not None else 0)
        for i, segs in enumerate(lines):
            widget_rows = 0 if right is None else int(math.ceil((right.height + 12 - (SIZES["panel_title"] + 8)) / L["line_h"]))
            avail = avail_side if (right is not None and i < widget_rows) else avail_full
            draw_segments(d, x0 + L["pad"], y, fit_segments(segs, fb, avail), fb)
            y += L["line_h"]
        if right is not None:
            layer.paste(right, (x1 - right.width - L["pad"], y0 + 10), right)
    overlay(img, draw)


def header(img: Image.Image, left: Sequence[Tuple[str, Tuple]], centre: str, right_top: Sequence[Tuple[str, Tuple]],
           right_bottom: Sequence[Tuple[str, Tuple]], live: bool = True, progress: float = 0.0) -> None:
    L = LAYOUT
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, L["W"], L["header_h"]], fill=COLOURS["header_bg"])
    fh = font("body", SIZES["header"])
    d.text((16, 8), left[0][0], font=fh, fill=left[0][1])
    d.text((16, 34), left[1][0], font=font("bold", SIZES["header"]), fill=left[1][1])
    ft = font("display", SIZES["title"])
    w = display_w(centre, ft)
    display_text(d, (L["W"] - w) // 2, 8, centre, ft, COLOURS["cream"])
    fb = font("bold", SIZES["header"])
    # right column, right-aligned
    for row, (segs, yy) in enumerate(((right_top, 8), (right_bottom, 34))):
        total = sum(text_w(t, fb) for t, _ in segs) + (30 if (row == 0 and live) else 0)
        x = L["W"] - 16 - total
        if row == 0 and live:
            d.ellipse([x + 2, yy + 6, x + 18, yy + 22], fill=COLOURS["live"])
            x += 30
        draw_segments(d, x, yy, segs, fb)
    # thin progress line under the header (next event countdown)
    d.rectangle([0, L["header_h"] - 4, L["W"], L["header_h"]], fill=(52, 42, 34))
    d.rectangle([0, L["header_h"] - 4, int(L["W"] * max(0.0, min(1.0, progress))), L["header_h"]], fill=COLOURS["gold"])


def caption(img: Image.Image, left: str, right: str) -> None:
    L = LAYOUT
    d = ImageDraw.Draw(img)
    d.rectangle([0, L["caption_y0"], L["W"], L["H"]], fill=COLOURS["header_bg"])
    f = font("body", SIZES["caption"])
    d.text((16, L["caption_y0"] + 1), left, font=f, fill=COLOURS["muted"])
    d.text((L["W"] - 16 - text_w(right, f), L["caption_y0"] + 1), right, font=f, fill=COLOURS["muted"])


def pill(text: str, dot: Optional[Tuple[int, int, int]] = None, tail: bool = True, icon: Optional[Image.Image] = None,
         colour: Optional[Tuple[int, int, int]] = None) -> Image.Image:
    """Show-on-speak name pill for the world: dark rounded pill, the name in the settler's colour (20 px bold), the
    settler's HEAD ICON on the left (or a colour dot when no icon is given) and a small tail pointing down at them."""
    f = font("bold", SIZES["pill"])
    tw = text_w(text, f)
    iw = (icon.width + 8) if icon is not None else (22 if dot else 0)
    hh = 34
    w, h = tw + iw + 24, hh + (6 if tail else 0)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, hh - 1], radius=15, fill=COLOURS["pill_bg"], outline=COLOURS["panel_border"], width=2)
    if tail:
        d.polygon([(w // 2 - 6, hh - 2), (w // 2 + 6, hh - 2), (w // 2, hh + 5)], fill=COLOURS["panel_border"])
        d.polygon([(w // 2 - 4, hh - 3), (w // 2 + 4, hh - 3), (w // 2, hh + 2)], fill=COLOURS["pill_bg"][:3])
    x = 10
    if icon is not None:
        im.paste(icon, (x, (hh - icon.height) // 2), icon)
        x += iw
    elif dot:
        d.ellipse([x + 2, 10, x + 16, 24], fill=dot, outline=COLOURS["panel_border"], width=2)
        x += iw
    d.text((x, 5), text, font=f, fill=colour or COLOURS["cream"])
    return im


def bubble(text: str, max_w: int = 260) -> Image.Image:
    """Short speech bubble (used sparingly; chat text normally goes to the log). 22 px body font."""
    f = font("body", SIZES["body"])
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if text_w(t, f) > max_w and cur:
            lines.append(cur)
            cur = w_
        else:
            cur = t
    lines.append(cur)
    tw = max(text_w(l, f) for l in lines)
    w, h = tw + 28, len(lines) * LAYOUT["line_h"] + 16
    im = Image.new("RGBA", (w, h + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=12, fill=(250, 244, 230, 240), outline=(60, 46, 38), width=2)
    d.polygon([(18, h - 2), (34, h - 2), (22, h + 7)], fill=(250, 244, 230))
    for i, l in enumerate(lines):
        d.text((14, 6 + i * LAYOUT["line_h"]), l, font=f, fill=(40, 30, 26))
    return im


def minimap(cat_rgb: np.ndarray, view: Tuple[int, int, int, int], size: Tuple[int, int] = (150, 110)) -> Image.Image:
    """Minimap tile for the COLONY panel: a coarse colour map with the current viewport outlined in gold."""
    im = Image.fromarray(cat_rgb).resize(size, Image.Resampling.NEAREST).convert("RGBA")
    d = ImageDraw.Draw(im)
    sx, sy = size[0] / cat_rgb.shape[1], size[1] / cat_rgb.shape[0]
    x0, y0, x1, y1 = view
    d.rectangle([x0 * sx, y0 * sy, x1 * sx, y1 * sy], outline=COLOURS["gold"], width=2)
    frame = Image.new("RGBA", (size[0] + 6, size[1] + 6), (0, 0, 0, 0))
    ImageDraw.Draw(frame).rounded_rectangle([0, 0, size[0] + 5, size[1] + 5], radius=6, fill=COLOURS["panel_border"])
    frame.paste(im, (3, 3))
    return frame


def style_sheet_image() -> Image.Image:
    """A one-look reference of the HUD system: panel, pill, bubble, fonts and sizes."""
    img = Image.new("RGB", (1280, 420), (96, 150, 78))
    header(img, [("atleastonce", COLOURS["muted"]), ("SETTLEMENT · settlers-round", COLOURS["cream"])], "14 SETTLED · 12 AWAKE",
           [("LIVE · 7 watching", COLOURS["cream"])], [("NEXT EVENT 01:23", COLOURS["gold"])], progress=0.55)
    panel(img, (16, 90, 440, 250), "COLONY", [[("14 settled · ", COLOURS["cream"]), ("12 awake", COLOURS["ok"])],
                                              [("day 5 · evening · wind E fresh", COLOURS["muted"])],
                                              [("last event: rain · by ", COLOURS["muted"]), ("@sami.exe", (250, 204, 84))]])
    p = pill("@kai_dnb", dot=(80, 170, 230))
    img.paste(p, (470, 100), p)
    b = bubble("B! the well goes by the plaza")
    img.paste(b, (470, 150), b)
    d = ImageDraw.Draw(img)
    y = 270
    for k, (kind, size) in enumerate((("display", 40), ("display", 22), ("bold", 22), ("body", 22), ("bold", 20), ("body", 20))):
        display_text(d, 16 + (k // 3) * 560, y + (k % 3) * 44, "%s %d · Aa Bb 0123" % (kind, size), font(kind, size), COLOURS["cream"])
    return img


if __name__ == "__main__":
    style_sheet_image().save("/Users/sandy/Workspace/agentic-builds/kick-live/docs/art/settlers-round/hud_style.png")
    print("ok")
