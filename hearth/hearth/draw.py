"""Moonlit woods, warm stone, one fire. All people come from real chat."""
from __future__ import annotations

import hashlib
import math
import os
from functools import lru_cache
from typing import Dict, Tuple

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .sim import Hearth, clothes_color

W, H = 1280, 720
# Overscan lets the camera pull back without inventing black borders.
SW, SH = 1664, 1024
CX, CY = SW // 2, 594
_GLOW_STOPS = (0.0, 0.08, 0.18, 0.35, 0.55, 0.78, 1.0, 1.15)
_FONT: Dict[Tuple[str, int], object] = {}
_PLATES: Dict[float, Image.Image] = {}
_NIGHT = None
_LIGHT = None


def _mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def _smooth(a, b, x):
    u = max(0.0, min(1.0, (x - a) / (b - a)))
    return u * u * (3.0 - 2.0 * u)


def _identity(slug):
    return int.from_bytes(hashlib.sha256(slug.encode('utf-8')).digest()[:4], 'big')


def _font(size: int, bold: bool = False):
    key = ('b' if bold else 'r', size)
    if key not in _FONT:
        for path in (
            '/System/Library/Fonts/Supplemental/Arial%s.ttf' % (' Bold' if bold else ''),
            '/System/Library/Fonts/Avenir Next.ttc',
            '/Library/Fonts/Arial Unicode.ttf'):
            if os.path.isfile(path):
                try:
                    _FONT[key] = ImageFont.truetype(path, size)
                    break
                except OSError:
                    pass
        else:
            _FONT[key] = ImageFont.load_default()
    return _FONT[key]


def _pine(d, x, ground, height, color, seed, rim=None):
    rng = np.random.RandomState(seed)
    lean = rng.uniform(-0.06, 0.06) * height
    top = ground - height
    trunk = max(1, int(height * 0.028))
    d.line([(x, ground + 4), (x + lean, top)], fill=color, width=trunk)
    for j in range(8):
        u = (j + 1) / 9.0
        y = top + height * u
        width = height * (0.025 + 0.23 * u) * rng.uniform(0.82, 1.1)
        mid = x + lean * (1 - u)
        pts = [(mid, y - height * 0.19), (mid - width * 0.7, y - height * 0.03),
               (mid - width, y + height * 0.075), (mid - width * 0.35, y + height * 0.05),
               (mid, y + height * 0.09), (mid + width * 0.5, y + height * 0.05),
               (mid + width, y + height * 0.065), (mid + width * 0.6, y - height * 0.025)]
        d.polygon(pts, fill=color)
        if rim:
            d.line([pts[0], pts[1], pts[2]], fill=rim, width=1)


def _night():
    """All terrain detail is built once, never inside the frame budget."""
    global _NIGHT, _LIGHT
    if _NIGHT is not None:
        return _NIGHT
    rng = np.random.RandomState(1209)
    yy, xx = np.ogrid[:SH, :SW]
    sky_t = np.clip(yy / 540.0, 0, 1)
    sky = np.zeros((SH, SW, 3), dtype=np.float32)
    for c, (top, bottom) in enumerate(zip((8, 15, 29), (40, 67, 77))):
        sky[..., c] = top + (bottom - top) * sky_t
    mx, my = 492, 249
    halo = np.exp(-((xx - mx) ** 2 + (yy - my) ** 2) / (2 * 110.0 ** 2))
    sky += halo[..., None] * np.array([22, 30, 33], dtype=np.float32)
    noise = rng.normal(0, 0.7, (SH, SW, 1))
    img = Image.fromarray(np.uint8(np.clip(sky + noise, 0, 255)))
    d = ImageDraw.Draw(img)
    for i in range(330):
        x, y = int(rng.randint(40, SW - 40)), int(rng.randint(45, 397))
        if (x - mx) ** 2 + (y - my) ** 2 < 60 ** 2:
            continue
        b = int(rng.randint(70, 156))
        r = 1 if i % 17 == 0 else 0
        d.ellipse((x-r, y-r, x+r, y+r), fill=(b - 8, b, b + 12))
        if r:
            d.point((x-2, y), fill=(52, 68, 82))
            d.point((x+2, y), fill=(52, 68, 82))
    # A shaded moon, with a soft blue halo rather than a hard circular badge.
    d.ellipse((mx-31, my-31, mx+31, my+31), fill=(181, 199, 198))
    d.ellipse((mx-25, my-29, mx+30, my+25), fill=(201, 212, 201))
    for x, y, r in [(-11, -8, 5), (4, 15, 7), (11, -12, 4), (-15, 12, 3)]:
        d.ellipse((mx+x-r, my+y-r, mx+x+r, my+y+r), fill=(176, 195, 188))
    # Layered mountain faces; distant edges are cooler and less contrasty.
    for k, col in enumerate(((39, 60, 73), (29, 49, 65), (20, 39, 51))):
        xs = list(range(-100, SW + 140, 120))
        ys = [360 + k*47 + rng.uniform(-72, 39) for _ in xs]
        ridge = list(zip(xs, ys))
        d.polygon(ridge + [(SW+100, SH), (-100, SH)], fill=col)
        for i in range(1, len(ridge)-1):
            x, y = ridge[i]
            if y < ridge[i-1][1] and y < ridge[i+1][1]:
                d.polygon([(x, y), (x+55, y+105), (x-9, y+64), ridge[i-1]],
                          fill=_mix(col, (60, 82, 91), 0.18))
                d.line([ridge[i-1], (x, y), (x+15, y+26)], fill=_mix(col, (81, 100, 105), 0.16), width=1)
    for band, (base, color) in enumerate(((466, (18, 37, 45)), (501, (12, 29, 35)))):
        for i in range(60):
            x = i * 29 + int(rng.randint(-12, 12))
            y = base + 18 * math.sin(x * .006 + band)
            height = int(rng.randint(31, 90))
            _pine(d, x, y, height, color, 1300 + band*100 + i)
    # Sloping moss/earth clearing. Texture follows perspective instead of flat bands.
    ground = [(0, 573), (210, 539), (425, 552), (655, 527), (905, 534),
              (1120, 550), (1400, 541), (SW, 568), (SW, SH), (0, SH)]
    d.polygon(ground, fill=(17, 29, 29))
    soil = Image.new('RGB', (SW, SH), (0, 0, 0))
    sd = ImageDraw.Draw(soil)
    for i in range(100):
        u = i / 99.0
        r = 305 - u*185
        sd.ellipse((CX-r*1.3, CY-r*.26, CX+r*1.3, CY+r*.68),
                   fill=_mix((17, 29, 29), (43, 39, 32), u*.62))
    mask = soil.convert('L').point(lambda v: 255 if v else 0)
    img.paste(soil, (0, 0), mask)
    d = ImageDraw.Draw(img)
    for i in range(10800):
        x, y = int(rng.randint(0, SW)), int(rng.randint(564, SH))
        depth = (y - 520) / 504.0
        dist = ((x-CX)/335.0)**2 + ((y-CY-35)/122.0)**2
        if dist < 1.0:
            col = ((45, 43, 34), (31, 35, 31), (52, 47, 37))[i % 3]
            d.line((x, y, x + max(1, int(depth*5)), y), fill=col, width=1)
        else:
            col = ((22, 38, 33), (26, 42, 36), (12, 23, 25), (30, 43, 37))[i % 4]
            ln = max(2, int(rng.uniform(4, 13) * depth))
            d.line((x, y, x + rng.randint(-4, 5), y-ln), fill=col, width=1)
    for x, y, sz in ((527, 664, 18), (1107, 677, 23), (403, 818, 27), (1266, 866, 35), (953, 817, 12)):
        d.polygon([(x-sz, y+7), (x-sz*.7, y-sz*.5), (x+sz*.1, y-sz*.8),
                   (x+sz, y-sz*.15), (x+sz*.8, y+8)], fill=(30, 42, 42))
        d.line([(x-sz*.7, y-sz*.5), (x+sz*.1, y-sz*.8), (x+sz*.65, y-sz*.35)], fill=(52, 62, 57), width=2)
    # Foreground trees bracket, rather than fill, the clearing.
    for x, y, ht, seed in ((187, 809, 514, 991), (1448, 780, 445, 992),
                            (36, 920, 555, 993), (1632, 973, 576, 994)):
        _pine(d, x, y, ht, (7, 17, 21), seed, (17, 31, 34))
    for i in range(135):
        x = int(rng.randint(140, SW-140))
        y = int(rng.randint(903, SH))
        ht = int(rng.randint(15, 43))
        d.line([(x-6, y), (x, y-ht), (x+2, y-ht-4)], fill=(8, 20, 21), width=2)
    # Static light geometry used to bake complete cold-to-hot plates.
    pool = np.exp(-(((xx-CX)/285.0)**2 + ((yy-CY-36)/148.0)**2)*1.35)
    halo = np.exp(-(((xx-CX)/213.0)**2 + ((yy-CY+75)/220.0)**2)*1.6)
    ground_mask = np.clip((yy-516)/74., 0, 1)
    _LIGHT = (pool * ground_mask, halo)
    _NIGHT = img
    return img


def _plate_at(heat):
    if heat not in _PLATES:
        base = np.asarray(_night(), dtype=np.float32)
        pool, halo = _LIGHT
        warmth = 0.045 + 0.955 * (heat / 1.15)**0.65
        base += pool[..., None] * np.array((101, 57, 20)) * warmth
        base += halo[..., None] * np.array((38, 16, 4)) * warmth
        yy, xx = np.ogrid[:SH, :SW]
        edge = np.clip(1 - .22 * (((xx-SW/2)/(SW*.63))**2 + ((yy-SH/2)/(SH*.7))**2), .58, 1)
        base *= edge[..., None]
        _PLATES[heat] = Image.fromarray(np.uint8(np.clip(base, 0, 255)))
    return _PLATES[heat]


def _glow_at(heat):
    """Compatibility with compositor warmup; cache complete lit plates, not glows."""
    h = max(0.0, min(1.15, heat))
    for lo, hi in zip(_GLOW_STOPS, _GLOW_STOPS[1:]):
        if h <= hi:
            return Image.blend(_plate_at(lo), _plate_at(hi), (h-lo)/(hi-lo))
    return _plate_at(_GLOW_STOPS[-1]).copy()


def _seat(n_people, heat):
    return 162.0 + 34 * _smooth(.12, 1.15, heat) + 12 * min(n_people, 32)/32.


def _person_pos(p, ring, t):
    r = ring + 1.1 * math.sin(t*.65 + p.angle*3)
    return CX + math.cos(p.angle)*r*1.3, CY + math.sin(p.angle)*r*.48 + 27, r


@lru_cache(maxsize=256)
def _person_sprite(slug, color, heat_step, scarred, facing):
    """A tiny hard-grid sitter; stable identity, bounded colour/light cache."""
    seed = _identity(slug)
    col = clothes_color(slug, color)
    col = _mix(col, (108, 100, 76), .25)
    if scarred:
        col = _mix(col, (48, 40, 34), .4)
    light = heat_step / 6.
    shade = _mix(col, (15, 25, 32), .52)
    lit = _mix(col, (238, 177, 86), .20 + .20*light)
    face = _mix((139, 132, 111), (239, 207, 146), .32 + .58*light)
    hair = ((42, 37, 30), (75, 54, 33), (104, 81, 48), (52, 58, 51))[seed % 4]
    ink = (8, 18, 25)
    im = Image.new('RGBA', (32, 39))
    d = ImageDraw.Draw(im)
    # Folded legs and boots ground the sitter; the torso overlaps their knees.
    d.polygon([(4, 30), (9, 27), (24, 27), (29, 32), (26, 37), (5, 37), (2, 34)], fill=ink)
    d.rectangle((5, 30, 13, 34), fill=(43, 48, 46))
    d.rectangle((19, 30, 27, 34), fill=(50, 52, 45))
    d.rectangle((7, 34, 13, 36), fill=(21, 28, 29))
    d.rectangle((19, 34, 25, 36), fill=(21, 28, 29))
    d.polygon([(9, 19), (23, 19), (27, 28), (24, 32), (8, 32), (5, 28)], fill=ink)
    d.polygon([(10, 20), (22, 20), (24, 30), (8, 30)], fill=shade)
    d.rectangle((11, 21, 20, 28), fill=col)
    d.rectangle((12, 21, 20, 23), fill=lit)
    d.line((7, 23, 10, 28, 15, 28), fill=lit, width=3)
    d.line((24, 23, 22, 28, 18, 28), fill=col, width=3)
    d.rectangle((13, 27, 15, 29), fill=face)
    d.rectangle((17, 27, 19, 29), fill=face)
    d.rectangle((13, 18, 19, 22), fill=ink)
    d.rectangle((14, 19, 18, 21), fill=face)
    d.polygon([(8, 6), (11, 3), (22, 3), (25, 6), (25, 16), (22, 20), (10, 20), (7, 16), (7, 8)], fill=ink)
    d.rectangle((9, 7, 23, 16), fill=face)
    d.rectangle((11, 16, 21, 18), fill=face)
    d.rectangle((9, 8, 10, 15), fill=_mix(face, hair, .3))
    d.rectangle((22, 9, 23, 15), fill=_mix(face, (255, 216, 149), .3))
    eyes = 1 if facing else -1
    d.rectangle((12+eyes, 12, 13+eyes, 14), fill=ink)
    d.rectangle((18+eyes, 12, 19+eyes, 14), fill=ink)
    if seed % 3 == 0:
        hat = _mix(col, (129, 106, 66), .45)
        d.rectangle((8, 4, 24, 8), fill=ink)
        d.rectangle((10, 1, 21, 7), fill=ink)
        d.rectangle((11, 2, 20, 6), fill=hat)
        d.rectangle((8, 7, 24, 8), fill=_mix(hat, (235, 201, 143), .3))
    else:
        d.rectangle((9, 4, 23, 7), fill=hair)
        d.rectangle((8, 6, 10, 11), fill=hair)
        d.rectangle((22, 6, 24, 10), fill=hair)
        d.rectangle((12, 3, 20, 4), fill=hair)
        d.rectangle((11, 7, 14 + seed % 4, 9), fill=hair)
        d.line((11, 4, 19, 4), fill=_mix(hair, (165, 133, 82), .3), width=1)
    return im.resize((64, 78), Image.Resampling.NEAREST)


def _draw_person(img, p, x, y, now, heat):
    d = ImageDraw.Draw(img)
    length = 30 + heat*28
    away = (x-CX)/230.
    d.polygon([(x-19, y+6), (x+19, y+6), (x+22+away*length, y+length*.48),
               (x-20+away*length, y+length*.48)], fill=(12, 23, 24))
    d.ellipse((x-30, y-3, x+30, y+13), fill=(12, 23, 24))
    step = max(0, min(6, int(heat/1.15*6)))
    a = _person_sprite(p.slug, p.color, step, p.scarred, x < CX)
    b = _person_sprite(p.slug, p.color, min(6, step+1), p.scarred, x < CX)
    sprite = Image.blend(a, b, max(0, min(1, heat/1.15*6-step)))
    img.paste(sprite, (int(x-32), int(y-65)), sprite)
    age = now-p.last_ts
    if 0 <= age < 1.2:
        # A little log travels out of the lap, toward the fire.
        u = _smooth(0, 1.2, age)
        lx, ly = x + (CX-x)*u, y-15 + (CY-y+15)*u - math.sin(u*math.pi)*48
        d = ImageDraw.Draw(img)
        d.line((lx-7, ly-3, lx+8, ly+3), fill=(35, 24, 18), width=7)
        d.line((lx-7, ly-4, lx+8, ly+2), fill=(136, 86, 39), width=3)


def _tongue(d, x, bottom, width, height, t, phase, color):
    pts = []
    for side in (1, -1):
        steps = range(21) if side == 1 else range(20, -1, -1)
        for j in steps:
            u = j/20.
            bend = math.sin(u*5 - t*3.4 + phase)*u*width*.34
            bend += math.sin(u*9 - t*4.5 + phase*2)*u*u*width*.16
            radius = width*.5*(1-u)**.65 * (.88+.12*math.sin(u*12-t*4+phase))
            pts.append((x+bend+side*radius, bottom-u*height))
    d.polygon(pts, fill=color)


def _draw_fire(img, heat, t):
    h = max(0, min(1.15, heat))
    strength = _smooth(0, .07, h)
    scale = h/1.15
    d = ImageDraw.Draw(img)
    d.ellipse((CX-67, CY-13, CX+67, CY+32), fill=(19, 22, 20))
    # Back stones, with distinct cool and fire-lit facets.
    for i in range(15):
        a = math.tau*i/15.
        x, y = CX+math.cos(a)*64, CY+math.sin(a)*21+12
        r = 7 + i % 4
        col = _mix((37, 43, 42), (108, 86, 56), .3 + h*.5)
        d.polygon([(x-r, y), (x-r*.55, y-r*.7), (x+r*.4, y-r*.65),
                   (x+r, y+2), (x+r*.65, y+r*.45), (x-r*.65, y+r*.45)], fill=(22, 28, 28))
        d.polygon([(x-r, y), (x-r*.55, y-r*.7), (x+r*.4, y-r*.65), (x+r*.7, y)], fill=col)
    for i in range(38):
        a = i*2.39996
        rad = math.sqrt((i+.5)/38.)*44
        x, y = CX+math.cos(a)*rad, CY+math.sin(a)*rad*.29+9
        pulse = .66+.34*math.sin(t*1.4+i*3)
        col = _mix((60, 31, 22), (245, 117, 35), (.18+.65*scale)*pulse)
        d.rectangle((x-3, y-2, x+4, y+2), fill=col)
    for x0, y0, x1, y1 in ((-48, 11, 40, -3), (-38, -4, 45, 16), (-10, 19, 22, -14)):
        d.line((CX+x0, CY+y0, CX+x1, CY+y1), fill=(29, 23, 19), width=13)
        d.line((CX+x0, CY+y0-4, CX+x1, CY+y1-4), fill=(83, 51, 28), width=3)
        for j in range(1, 5):
            u = j/5.
            x, y = CX+x0+(x1-x0)*u, CY+y0+(y1-y0)*u
            d.line((x-2, y-3, x+1, y+3), fill=_mix((74, 40, 23), (215, 104, 29), scale), width=1)
    if strength < .001:
        return
    # Flames/bloom are local (384 x 416), never a full-frame blur.
    fw, fh = 384, 416
    fx, fy = CX-fw//2, CY-fh+24
    flames = Image.new('RGB', (fw, fh))
    fd = ImageDraw.Draw(flames)
    height = (20 + 232*scale**.66) * strength
    spread = 23+54*scale
    base = fh-28
    for i in range(7):
        phase = i*1.91
        x = fw/2 + (i-3)*spread*.22 + math.sin(t*1.1+i)*3*strength
        ht = height*(.64+.29*math.sin(i*2.1+1)**2) * (1+.07*math.sin(t*3.1+phase))
        width = (22+37*scale) * (1+.13*math.sin(t*2.4+phase)) * strength
        _tongue(fd, x, base, width, ht, t, phase, (194, 52+7*i, 12))
    for i in range(5):
        phase = i*2.21+.7
        x = fw/2+(i-2)*spread*.23
        ht = height*(.48+.25*math.sin(i*2.5)**2)*(1+.08*math.sin(t*3.3+phase))
        _tongue(fd, x, base-2, (22+24*scale)*strength, ht, t, phase, (255, 139+13*i, 34+9*i))
        _tongue(fd, x-2, base-1, (10+13*scale)*strength, ht*.55, t, phase+.2, (255, 234, 151))
    for i in range(48):
        rate = .24+(i%7)*.033
        life = (t*rate+i*.618034) % 1.
        visibility = max(0, min(1, (h*45+3-i)*.4))
        fade = math.sin(math.pi*life)**1.3 * visibility * strength
        drift = math.sin(i*12.9)*(.25+life)*spread + math.sin(life*4+i)*18*life
        x = fw/2+drift
        y = base-life*(height+95)
        col = _mix((0, 0, 0), _mix((255, 214, 111), (214, 65, 15), life), fade)
        fd.line((x, y, x-1.4, y+2+life*3), fill=col, width=1+(i%5 == 0))
    bloom = flames.resize((fw//3, fh//3), Image.Resampling.BILINEAR)
    bloom = bloom.filter(ImageFilter.GaussianBlur(4)).resize((fw, fh), Image.Resampling.BILINEAR)
    flames = ImageChops.screen(flames, bloom)
    area = img.crop((fx, fy, fx+fw, fy+fh))
    img.paste(ImageChops.screen(area, flames), (fx, fy))
    # Smoke curls: low-res translucent light scattering, fading at both ends.
    smoke = Image.new('RGBA', (144, 192))
    sd = ImageDraw.Draw(smoke)
    for i in range(8):
        life = (t*.095+i/8.) % 1.
        sx = 72 + math.sin(life*5+t*.15+i*.3)*life*21
        sy = 179-life*164
        r = 5+life*16
        alpha = int((7+scale*11)*math.sin(math.pi*life)*strength)
        sd.ellipse((sx-r, sy-r*.6, sx+r, sy+r*.6), fill=(107, 114, 115, alpha))
    smoke = smoke.filter(ImageFilter.GaussianBlur(3)).resize((288, 384), Image.Resampling.BILINEAR)
    img.paste(smoke, (CX-144, int(CY-height*.55-350)), smoke)


@lru_cache(maxsize=128)
def _bubble(text, name):
    font, nf = _font(14), _font(11)
    scratch = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    box = scratch.textbbox((0, 0), text, font=font)
    tw = box[2]-box[0]
    width = min(440, tw+22)
    out = Image.new('RGBA', (width+8, 47))
    d = ImageDraw.Draw(out)
    d.rounded_rectangle((3, 2, width+3, 28), radius=5, fill=(12, 24, 28, 230), outline=(106, 116, 101, 180))
    d.text((14-box[0], 6-box[1]), text, font=font, fill=(233, 225, 199))
    nb = scratch.textbbox((0, 0), name, font=nf)
    d.text(((out.width-nb[2]+nb[0])/2, 33-nb[1]), name, font=nf, fill=(164, 181, 174))
    return out


def _camera_box(world, now):
    cam = world.camera(now)
    zoom = .82 + (max(.82, min(1.55, cam['zoom'])) - .82) * (.38 / .73)
    # Give a crowd extra rows without letting foreground people leave the shot.
    zoom = min(zoom, 1.20 - .38 * _smooth(8, 32, len(world.people)))
    cw, ch = W/zoom, H/zoom
    shake = min(.55, max(0., cam['shake']))
    x = SW/2-cw/2 + math.sin(now*19)*3*shake
    y = SH/2-ch/2 + math.cos(now*17)*2*shake
    x, y = max(0., min(SW-cw, x)), max(0., min(SH-ch, y))
    return x, y, x+cw, y+ch


def _positions(world, ring, now):
    positions = []
    for i, p in enumerate(world.ring()):
        if i < 10:
            x, y, _ = _person_pos(p, ring, now)
        else:
            # Further arrivals sit in staggered outer rows, not on top of friends.
            row, col = divmod(i-10, 12)
            angle = math.pi * (.12 + .76 * ((col+.5)/12.))
            radius = ring + 46 + row*39
            x = CX + math.cos(angle)*radius*1.3
            y = CY + math.sin(angle)*radius*.48 + 60 + row*40
        positions.append((p, x, y))
    return sorted(positions, key=lambda item: item[2])


def render(world: Hearth, now: float, frame: int) -> Image.Image:
    heat = max(0., min(1.15, getattr(world, 'shown_heat', world.heat)))
    # Flicker modulates the cached light, not the sky geometry or camera.
    light = heat * (1 + .015*math.sin(now*5.1) + .01*math.sin(now*8.3))
    img = _glow_at(light)
    ring = _seat(len(world.people), heat)
    positions = _positions(world, ring, now)
    d = ImageDraw.Draw(img)
    for p, x, y in positions:
        if p.scarred:
            d.ellipse((x-29, y-7, x+30, y+15), fill=(27, 24, 21))
    for p, x, y in positions:
        if y < CY+10:
            _draw_person(img, p, x, y, now, heat)
    _draw_fire(img, heat, now)
    for p, x, y in positions:
        if y >= CY+10:
            _draw_person(img, p, x, y, now, heat)
    # Render human words after the camera transform so they stay legible.
    box = _camera_box(world, now)
    result = img.transform((W, H), Image.Transform.EXTENT, box, Image.Resampling.BILINEAR)
    factor = W/(box[2]-box[0])
    for p, x, y in positions:
        age = now-p.last_text_ts
        if p.last_text and 0 <= age <= 4.:
            bubble = _bubble(p.last_text, p.username[:16])
            fade = _smooth(0., .18, age)*(1-_smooth(3.5, 4., age))
            alpha = bubble.getchannel('A').point(lambda v: int(v*fade))
            bx = max(8, min(W-bubble.width-8, (x-box[0])*factor-bubble.width/2))
            by = max(8, min(H-bubble.height-8, (y-70-box[1])*factor-bubble.height))
            result.paste(bubble, (int(bx), int(by)), alpha)
    return result
