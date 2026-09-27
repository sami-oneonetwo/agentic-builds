"""The hill, the fire, the ring. No HUD. No explainer copy."""
from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .sim import Hearth, Person, clothes_color, hsl_to_rgb, mood_of

W, H = 1280, 720
CX, CY = 640, 430          # fire sits a little below centre so the sky has room
BASE_RING = 210.0

_FONT: Dict[Tuple[str, int], object] = {}
_STARFIELD: Optional[Image.Image] = None
_HILL: Optional[Image.Image] = None
_HILL_MASK: Optional[Image.Image] = None
_NIGHT: Optional[Image.Image] = None
_GLOW: Dict[int, Image.Image] = {}  # heat*1000 key
_GLOW_STOPS = (0.0, 0.10, 0.30, 0.55, 0.85, 1.15)


def _font(size: int, bold: bool = False) -> object:
    key = ("b" if bold else "r", size)
    f = _FONT.get(key)
    if f is not None:
        return f
    paths = [
        ("/System/Library/Fonts/Supplemental/Arial Black.ttf", 0) if bold else ("/System/Library/Fonts/Supplemental/Arial.ttf", 0),
        ("/System/Library/Fonts/Avenir Next.ttc", 1 if bold else 0),
        ("/System/Library/Fonts/Menlo.ttc", 1 if bold else 0),
        ("/Library/Fonts/Arial Unicode.ttf", 0),
    ]
    for path, idx in paths:
        if not os.path.isfile(path):
            continue
        try:
            f = ImageFont.truetype(path, size, index=idx)
            _FONT[key] = f
            return f
        except OSError:
            continue
    f = ImageFont.load_default()
    _FONT[key] = f
    return f


def _starfield() -> Image.Image:
    global _STARFIELD
    if _STARFIELD is not None:
        return _STARFIELD
    img = Image.new("RGB", (W, H), (6, 8, 18))
    px = img.load()
    # a handful of stars, hashed so they never jitter
    n = 140
    for i in range(n):
        x = (i * 7919) % W
        y = (i * 104729) % int(H * 0.62)
        b = 80 + (i * 37) % 140
        if (i * 13) % 7 == 0:
            b = min(255, b + 60)
        px[x, y] = (b, b, min(255, b + 20))
        if (i * 17) % 11 == 0 and 0 < x < W - 1 and 0 < y < H - 1:
            px[x + 1, y] = (b // 2, b // 2, b // 2)
    smear = Image.new("RGB", (W, H), (0, 0, 0))
    sd = ImageDraw.Draw(smear)
    for k in range(18):
        y = 40 + k * 14
        a = 8 + (k % 5)
        sd.ellipse((80, y, 1180, y + 90), fill=(a, a, a + 6))
    smear = smear.filter(ImageFilter.GaussianBlur(18))
    img = Image.blend(img, smear, 0.35)
    # a quiet moon, left of the bowl
    d = ImageDraw.Draw(img)
    mx, my, mr = 210, 118, 28
    d.ellipse((mx - mr - 10, my - mr - 10, mx + mr + 10, my + mr + 10), fill=(18, 20, 32))
    d.ellipse((mx - mr, my - mr, mx + mr, my + mr), fill=(210, 214, 228))
    d.ellipse((mx - mr + 11, my - mr - 4, mx + mr + 11, my + mr - 4), fill=(8, 10, 20))
    _STARFIELD = img
    return img


def _hill() -> Image.Image:
    global _HILL
    if _HILL is not None:
        return _HILL
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    # stacked ridges, darkest at the back
    ridges = [
        (H * 0.42, (8, 10, 22), 70),
        (H * 0.50, (10, 14, 26), 90),
        (H * 0.58, (12, 18, 28), 110),
        (H * 0.68, (14, 22, 30), 140),
        (H * 0.78, (16, 26, 32), 180),
    ]
    for y0, col, amp in ridges:
        pts = [(0, H)]
        for x in range(0, W + 1, 8):
            n1 = math.sin(x * 0.007 + y0) * amp * 0.35
            n2 = math.sin(x * 0.019 + y0 * 0.4) * amp * 0.18
            n3 = math.sin(x * 0.041) * 6
            y = y0 + n1 + n2 + n3
            pts.append((x, y))
        pts.append((W, H))
        d.polygon(pts, fill=col)
    d.ellipse((CX - 420, CY + 40, CX + 420, H + 180), fill=(10, 16, 22))
    # pine silhouettes on the far ridge. hashed, never jitter.
    for i in range(11):
        tx = 40 + i * 118 + (i * 19) % 37
        ty = int(H * 0.46 + math.sin(i * 1.7) * 18)
        hgt = 38 + (i * 13) % 28
        d.polygon([(tx, ty + hgt), (tx - 16, ty + hgt), (tx, ty), (tx + 16, ty + hgt)], fill=(6, 8, 16))
        d.polygon([(tx, ty + hgt - 12), (tx - 11, ty + hgt - 12), (tx, ty + 8), (tx + 11, ty + hgt - 12)], fill=(8, 10, 18))
        d.rectangle((tx - 2, ty + hgt - 4, tx + 2, ty + hgt + 8), fill=(8, 6, 12))
    _HILL = img
    return img


def _blend(a: Tuple[int, int, int], b: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def _add(base: Image.Image, overlay: Image.Image, amount: float) -> Image.Image:
    if amount <= 0:
        return base
    if overlay.mode != "RGB":
        overlay = overlay.convert("RGB")
    return Image.blend(base, overlay, max(0.0, min(1.0, amount)))


def _screen_glow(w: int, h: int, cx: float, cy: float, radius: float, color: Tuple[int, int, int], power: float = 1.6) -> Image.Image:
    import numpy as np
    yy, xx = np.ogrid[0:h, 0:w]
    d2 = (xx - cx) ** 2 + (yy - cy) ** 2
    r2 = max(1.0, radius * radius)
    tt = 1.0 - np.power(np.clip(d2 / r2, 0, 1), 1.0 / power)
    tt = np.clip(tt, 0, 1).astype(np.float32)
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[..., 0] = (color[0] * tt).astype(np.uint8)
    arr[..., 1] = (color[1] * tt).astype(np.uint8)
    arr[..., 2] = (color[2] * tt).astype(np.uint8)
    img = Image.fromarray(arr, "RGB")
    blur = max(1, min(12, int(radius * 0.04)))
    return img.filter(ImageFilter.GaussianBlur(blur))


def _flame_blob(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, color: Tuple[int, int, int], lean: float = 0.0) -> None:
    # teardrop: wide base, pointed tip, lean is wind
    pts = []
    steps = 14
    for i in range(steps + 1):
        a = math.pi * i / steps  # 0..pi around the base-ish
        # parametric drop
        t = i / float(steps)
        x = math.sin(t * math.pi) * (w / 2.0)
        y = -t * h
        x += lean * t * t * 18
        pts.append((cx + x, cy + y))
    for i in range(steps, -1, -1):
        t = i / float(steps)
        x = -math.sin(t * math.pi) * (w / 2.0)
        y = -t * h
        x += lean * t * t * 18
        pts.append((cx + x, cy + y))
    if len(pts) >= 3:
        draw.polygon(pts, fill=color)


def _draw_fire(layer: Image.Image, heat: float, mood: str, t: float) -> None:
    """Paint the flame onto layer in place. No full-frame blur."""
    d = ImageDraw.Draw(layer)
    h = max(0.0, min(1.2, heat))
    if h <= 0.012:
        pulse = 0.45 + 0.55 * math.sin(t * 1.35)
        r = 8 + 4 * pulse
        d.ellipse((CX - r * 1.4, CY - r * 0.5, CX + r * 1.4, CY + r * 0.9), fill=(28, 12, 6))
        d.ellipse((CX - 6, CY - 3, CX + 5, CY + 4), fill=(int(90 * pulse + 30), int(24 * pulse), 6))
        return

    scale = 0.50 + 1.55 * min(1.0, h)
    if h > 0.78:
        scale *= 1.0 + 0.28 * min(1.0, (h - 0.78) / 0.37)
    lean = 0.32 * math.sin(t * 1.7) + 0.14 * math.sin(t * 4.1) + 0.08 * math.sin(t * 0.6)
    if h > 0.78:
        lean += 0.55 * math.sin(t * 9.0) * min(1.0, (h - 0.78) / 0.3)

    # stone ring
    for i in range(9):
        a = (i / 9.0) * math.pi + 0.18
        rx = CX + math.cos(a) * (46 + 8 * scale) * 1.05
        ry = CY + 16 + math.sin(a) * 14
        rr = 7 + (i % 3)
        d.ellipse((rx - rr, ry - rr * 0.7, rx + rr, ry + rr * 0.85), fill=(28 + i, 22, 18))

    # logs, crossed
    d.polygon([(CX - 44 * scale, CY + 12), (CX - 6, CY + 20), (CX + 8, CY + 10), (CX - 28 * scale, CY + 2)], fill=(48, 28, 16))
    d.polygon([(CX + 42 * scale, CY + 12), (CX + 8, CY + 20), (CX - 6, CY + 10), (CX + 24 * scale, CY + 2)], fill=(38, 22, 12))
    d.polygon([(CX - 18, CY + 6), (CX + 22, CY + 14), (CX + 18, CY + 4), (CX - 14, CY - 2)], fill=(56, 32, 16))

    flicker = 0.07 * math.sin(t * 11.0) + 0.05 * math.sin(t * 17.3) + 0.03 * math.sin(t * 6.1)
    h0 = 78 * scale * (1.0 + flicker)
    w0 = 58 * scale
    _flame_blob(d, CX, CY + 6, w0 * 1.35, h0 * 0.62, (90, 22, 6), lean * 0.35)
    _flame_blob(d, CX - 10 * scale, CY + 3, w0 * 0.78, h0 * 0.92, (170, 42, 8), lean * 0.75)
    _flame_blob(d, CX + 12 * scale, CY + 3, w0 * 0.72, h0 * 0.86, (185, 55, 10), -lean * 0.55)
    _flame_blob(d, CX - 2, CY + 1, w0 * 0.95, h0 * 1.02, (220, 90, 18), lean * 0.2)
    _flame_blob(d, CX, CY - 2, w0 * 0.72, h0, (240, 130, 28), lean)
    _flame_blob(d, CX - 5, CY - 8, w0 * 0.42, h0 * 0.78, (255, 196, 72), lean * 0.28)
    _flame_blob(d, CX + 4, CY - 12, w0 * 0.26, h0 * 0.58, (255, 236, 168), lean * 0.18)
    if h > 0.45:
        _flame_blob(d, CX + 1, CY - 18, w0 * 0.14, h0 * 0.38, (255, 252, 230), lean * 0.1)

    n_sparks = int(5 + 26 * min(1.0, h))
    for i in range(n_sparks):
        seed = (i * 17 + int(t * 8) * 3) % 997
        ang = (seed * 0.31) % math.pi
        dist = (12 + (seed % 80)) * scale
        life = ((t * (1.4 + (i % 5) * 0.2) + i) % 1.6) / 1.6
        x = CX + math.cos(ang) * dist * 0.25 + lean * 12 * life
        y = CY - 12 - life * (48 + (seed % 90)) * scale
        s = 1 + (seed % 3)
        col = (255, 170 + seed % 70, 36 + seed % 50)
        d.ellipse((x - s, y - s, x + s, y + s), fill=col)
        if life < 0.5 and s > 1:
            d.ellipse((x - 1, y + 3, x + 1, y + 6), fill=(180, 70, 20))


def _seat(n_people: int, heat: float) -> float:
    extra = 22 * min(1.0, n_people / 12.0)
    extra += 50 * max(0.0, heat - 0.5)
    # flame grows up the screen; keep seats outside it
    fire_h = 70.0 * (0.55 + 1.35 * min(1.0, heat))
    if heat > 0.78:
        fire_h *= 1.25
    min_r = fire_h / 0.50 + 64.0
    return max(BASE_RING + extra, min_r)


def _person_pos(p: Person, ring: float, t: float) -> Tuple[float, float, float]:
    # a little breathing so they don't look glued
    wobble = 3.0 * math.sin(t * 0.7 + p.angle * 3)
    r = ring + wobble
    x = CX + math.cos(p.angle) * r
    y = CY + math.sin(p.angle) * r * 0.50 + 28
    return x, y, r


def _draw_person(d: ImageDraw.ImageDraw, p: Person, x: float, y: float, now: float, heat: float, close: bool) -> None:
    clothes = clothes_color(p.username, p.color)
    dim = 0.35 + 0.65 * min(1.0, heat / 0.5)
    if now - p.last_ts > 90:
        dim *= 0.55
    col = tuple(int(c * dim) for c in clothes)
    skin = _blend((40, 28, 22), (210, 170, 130), 0.55 * dim + 0.2)
    if p.scarred:
        col = _blend(col, (30, 18, 12), 0.55)

    # body: small seated figure, people-shaped
    scale = 1.55 if close else 1.35
    bw, bh = 12 * scale, 17 * scale
    # facing the fire: lean inward
    inward = math.atan2(CY - y, CX - x)
    lean_x = math.cos(inward) * 2.5
    # torso
    d.ellipse((x - bw * 1.15, y + bh - 4, x + bw * 1.15, y + bh + 6), fill=(8, 10, 12))
    d.ellipse((x - bw, y - 4, x + bw, y + bh), fill=col)
    # firelight on the chest
    if heat > 0.08:
        lit = _blend(col, (255, 160, 60), 0.18 + 0.22 * min(1.0, heat))
        d.ellipse((x - bw * 0.45 + lean_x, y + 1, x + bw * 0.35 + lean_x, y + bh * 0.55), fill=lit)
    # head
    hx, hy = x + lean_x * 0.4, y - 16 * scale
    hr = 8.0 * scale
    d.ellipse((hx - hr, hy - hr, hx + hr, hy + hr), fill=skin)
    if heat > 0.08:
        cheek = _blend(skin, (255, 150, 70), 0.22 * min(1.0, heat))
        d.ellipse((hx - 2 + lean_x, hy + 1, hx + 5 + lean_x, hy + hr * 0.55), fill=cheek)
    # hair cap from name hue
    hair = hsl_to_rgb((hash(p.slug) % 360), 0.35, 0.18 * dim + 0.08)
    d.pieslice((hx - hr - 1, hy - hr - 2, hx + hr + 1, hy + 2), 200, 340, fill=hair)
    # two-pixel eyes, looking at the fire
    eye = (20, 16, 14) if dim < 0.4 else (18, 14, 12)
    look = 1.4 if CX > x else -1.4
    d.rectangle((hx - 3 + look, hy - 1, hx - 1 + look, hy + 1), fill=eye)
    d.rectangle((hx + 1 + look, hy - 1, hx + 3 + look, hy + 1), fill=eye)
    # a log in the lap if they just fed
    if now - p.last_ts < 1.6:
        d.rectangle((x - 6, y + 6, x + 6, y + 10), fill=(70, 42, 22))


def _draw_bubble(img: Image.Image, p: Person, x: float, y: float, now: float) -> None:
    if not p.last_text or now - p.last_text_ts > 4.0:
        return
    age = now - p.last_text_ts
    if age < 0:
        return
    font = _font(13, bold=False)
    d = ImageDraw.Draw(img)
    text = p.last_text
    try:
        bbox = d.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = 8 * len(text), 12
    pad_x, pad_y = 7, 4
    bw, bh = tw + pad_x * 2, th + pad_y * 2
    bx = x - bw / 2
    by = y - 36 - bh
    bx = max(8, min(W - bw - 8, bx))
    by = max(8, by)
    # fade in / out
    # we can't do real alpha easily on RGB; dim the fill instead
    fill = (24, 20, 16)
    outline = (70, 50, 30)
    d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=6, fill=fill, outline=outline)
    d.text((bx + pad_x, by + pad_y - 1), text, font=font, fill=(230, 210, 170))
    # name under, tiny, only while speaking
    nf = _font(11, bold=False)
    name = p.username[:16]
    try:
        nb = d.textbbox((0, 0), name, font=nf)
        nw = nb[2] - nb[0]
    except Exception:
        nw = 6 * len(name)
    d.text((x - nw / 2, y + 26), name, font=nf, fill=(160, 130, 90))


def _draw_scar(d: ImageDraw.ImageDraw, p: Person, ring: float) -> None:
    if not p.scarred:
        return
    x = CX + math.cos(p.angle) * (ring + 36)
    y = CY + math.sin(p.angle) * (ring + 36) * 0.52 + 18
    d.ellipse((x - 7, y - 4, x + 7, y + 5), fill=(18, 12, 8))
    d.ellipse((x - 4, y - 2, x + 3, y + 2), fill=(28, 16, 8))


def _hill_mask() -> Image.Image:
    global _HILL_MASK
    if _HILL_MASK is None:
        _HILL_MASK = _hill().convert("L").point(lambda v: 255 if v > 8 else 0)
    return _HILL_MASK


def _night() -> Image.Image:
    global _NIGHT
    if _NIGHT is None:
        _NIGHT = Image.composite(_hill(), _starfield(), _hill_mask())
    return _NIGHT


def _look(heat: float) -> Tuple[Tuple[int, int, int], Tuple[int, int, int], float, float, float]:
    """Sky, glow colour, radius, glow amount, sky tint. Continuous in heat."""
    h = max(0.0, min(1.15, heat))
    sky = _blend((4, 5, 12), (32, 8, 4), min(1.0, h / 0.95))
    glow = _blend((24, 8, 4), (255, 92, 14), min(1.0, h / 0.90))
    glow_r = 50 + 510 * min(1.0, h / 1.05)
    glow_amt = 0.16 + 0.58 * min(1.0, h / 0.95)
    tint = 0.38 + 0.32 * min(1.0, h / 0.90)
    return sky, glow, glow_r, glow_amt, tint


def _glow_at(heat: float) -> Image.Image:
    """Cached glow at discrete heat stops, blended so the bowl never jumps."""
    h = max(0.0, min(1.15, heat))
    stops = _GLOW_STOPS
    hi = 1
    while hi < len(stops) - 1 and h > stops[hi]:
        hi += 1
    lo = hi - 1
    h0, h1 = stops[lo], stops[hi]
    t = 0.0 if h1 <= h0 else (h - h0) / (h1 - h0)

    def one(hv: float) -> Image.Image:
        key = int(round(hv * 1000))
        g = _GLOW.get(key)
        if g is None:
            _, col, rad, _, _ = _look(hv)
            g = _screen_glow(W, H, CX, CY + 10, rad, col, power=1.8)
            _GLOW[key] = g
        return g

    a, b = one(h0), one(h1)
    if t <= 0.02:
        return a
    if t >= 0.98:
        return b
    return Image.blend(a, b, t)


def _plate(heat: float) -> Image.Image:
    sky_col, _, _, glow_amt, tint_amt = _look(heat)
    night = _night()
    sky_tint = Image.new("RGB", (W, H), sky_col)
    img = Image.blend(night, sky_tint, tint_amt * 0.55)
    glow = _glow_at(heat)
    img = Image.blend(img, ImageChops_screen(img, glow), glow_amt * 0.85)
    return img


def render(world: Hearth, now: float, frame: int) -> Image.Image:
    heat = getattr(world, "shown_heat", world.heat)
    mood = mood_of(heat)
    cam = world.camera(now)
    t = now

    img = _plate(heat)
    people = world.ring()
    ring = _seat(len(world.people), heat)
    close = cam["zoom"] >= 1.3
    people = sorted(people, key=lambda p: _person_pos(p, ring, t)[1])

    d = ImageDraw.Draw(img)
    for p in people:
        _draw_scar(d, p, ring)

    behind = [p for p in people if _person_pos(p, ring, t)[1] < CY + 8]
    front = [p for p in people if p not in behind]

    for p in behind:
        x, y, _ = _person_pos(p, ring, t)
        _draw_person(d, p, x, y, now, heat, close)

    _draw_fire(img, heat, mood, t)

    d = ImageDraw.Draw(img)
    for p in front:
        x, y, _ = _person_pos(p, ring, t)
        _draw_person(d, p, x, y, now, heat, close)

    for p in people:
        x, y, _ = _person_pos(p, ring, t)
        _draw_bubble(img, p, x, y, now)

    zoom = cam["zoom"]
    shake = cam["shake"]
    if abs(zoom - 1.0) > 0.08 or shake > 0.05:
        cw = int(W / zoom)
        ch = int(H / zoom)
        ox = CX - cw // 2
        oy = CY - ch // 2 + 20
        if shake > 0:
            ox += int(8 * shake * math.sin(t * 37))
            oy += int(5 * shake * math.cos(t * 29))
        ox = max(0, min(W - cw, ox))
        oy = max(0, min(H - ch, oy))
        crop = img.crop((ox, oy, ox + cw, oy + ch))
        img = crop.resize((W, H), Image.Resampling.BILINEAR)

    return img.convert("RGB")


def ImageChops_screen(a: Image.Image, b: Image.Image) -> Image.Image:
    """screen blend without importing ImageChops for every call's sake — still use it."""
    from PIL import ImageChops
    return ImageChops.screen(a, b)
