"""common.py - shared painting helpers for studio-b (numpy + pillow only).

Everything here is deterministic: no global RNG. Sprites are painted at SS x supersampling with
PIL.ImageDraw, shaded in numpy (glossy light from the top-left), then LANCZOS-downsampled so the
32-48 px results are smooth and soft instead of jaggy.
"""
from __future__ import annotations

import colorsys
import hashlib
from typing import Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SS = 4  # supersample factor for all sprite painting

RGB = Tuple[int, int, int]


# ----------------------------------------------------------------------------- hashing
def name_bytes(name: str, salt: str = "") -> bytes:
    """32 stable bytes for a username (lowercase, trimmed). Salt separates independent traits."""
    return hashlib.sha256(("%s|%s" % ((name or "").strip().lower(), salt)).encode("utf-8")).digest()


class Genes:
    """Deterministic trait picker: g.pick(n) in [0,n), g.unit() in [0,1), g.rng() -> RandomState."""

    def __init__(self, name: str, salt: str = ""):
        self.b = name_bytes(name, salt)
        self.i = 0

    def byte(self) -> int:
        v = self.b[self.i % 32]
        self.i += 1
        return v

    def pick(self, n: int) -> int:
        return self.byte() % max(1, n)

    def unit(self) -> float:
        return self.byte() / 255.0

    def rng(self) -> np.random.RandomState:
        return np.random.RandomState(int.from_bytes(self.b[:4], "little"))


# ----------------------------------------------------------------------------- colour
def hls(h: float, l: float, s: float) -> RGB:
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360.0, min(1, max(0, l)), min(1, max(0, s)))
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def to_hls(c: Sequence[int]) -> Tuple[float, float, float]:
    h, l, s = colorsys.rgb_to_hls(c[0] / 255.0, c[1] / 255.0, c[2] / 255.0)
    return h * 360.0, l, s


def shade(c: Sequence[int], k: float) -> RGB:
    """Darken (k<1) or lighten (k>1) in HLS, keeping hue; lightening desaturates a little (glossy)."""
    h, l, s = to_hls(c)
    if k >= 1:
        l2 = l + (1 - l) * (k - 1)
        s2 = s * (1 - 0.35 * (k - 1))
    else:
        l2 = l * k
        s2 = min(1.0, s * (1 + 0.25 * (1 - k)))
    return hls(h, l2, s2)


def mix(a: Sequence[int], b: Sequence[int], t: float) -> RGB:
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))  # type: ignore


def rgba(c: Sequence[int], a: int = 255) -> Tuple[int, int, int, int]:
    return (int(c[0]), int(c[1]), int(c[2]), int(a))


def hex_rgb(h: str) -> RGB:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# ----------------------------------------------------------------------------- canvas
class Canvas:
    """RGBA canvas at SS x, with a few painterly primitives. .finish() returns the downsampled RGBA array."""

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.img = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    # coordinates are given in *final* pixels (floats ok)
    def _box(self, cx, cy, rx, ry):
        return [(cx - rx) * SS, (cy - ry) * SS, (cx + rx) * SS, (cy + ry) * SS]

    def ellipse(self, cx, cy, rx, ry, fill, outline=None, width=0.0):
        self.d.ellipse(self._box(cx, cy, rx, ry), fill=fill, outline=outline,
                       width=int(round(width * SS)) if outline else 0)

    def polygon(self, pts, fill, outline=None, width=0.0):
        p = [(x * SS, y * SS) for x, y in pts]
        self.d.polygon(p, fill=fill)
        if outline and width > 0:
            self.d.line(p + [p[0]], fill=outline, width=int(round(width * SS)), joint="curve")

    def line(self, pts, fill, width):
        self.d.line([(x * SS, y * SS) for x, y in pts], fill=fill, width=max(1, int(round(width * SS))),
                    joint="curve")

    def arc(self, cx, cy, rx, ry, a0, a1, fill, width):
        self.d.arc(self._box(cx, cy, rx, ry), a0, a1, fill=fill, width=max(1, int(round(width * SS))))

    def rounded_rect(self, x0, y0, x1, y1, r, fill, outline=None, width=0.0):
        self.d.rounded_rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], radius=r * SS, fill=fill,
                                 outline=outline, width=int(round(width * SS)) if outline else 0)

    def rect(self, x0, y0, x1, y1, fill):
        self.d.rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], fill=fill)

    def paste(self, other: "Canvas", dx=0, dy=0):
        self.img.alpha_composite(other.img, (int(round(dx * SS)), int(round(dy * SS))))

    def blur(self, radius: float):
        self.img = self.img.filter(ImageFilter.GaussianBlur(radius * SS))
        self.d = ImageDraw.Draw(self.img)

    def array(self) -> np.ndarray:
        return np.array(self.img)

    def set_array(self, a: np.ndarray):
        self.img = Image.fromarray(a.astype(np.uint8), "RGBA")
        self.d = ImageDraw.Draw(self.img)

    def finish(self) -> np.ndarray:
        return np.array(self.img.resize((self.w, self.h), Image.LANCZOS))


def gloss_shade(c: Canvas, colour: RGB, light=(-0.6, -0.75), strength=0.55, spec=(0.35, 0.55, 0.16),
                rim=0.18, only_alpha_of: np.ndarray = None):
    """Shade the currently painted opaque pixels of `colour` as a glossy convex blob.

    Pixels whose RGB equals `colour` exactly get: a top-left to bottom-right gradient (strength),
    a soft specular blob at (spec[0], spec[1]) of the shape's bbox with radius spec[2], and a faint rim
    light along the bottom-right edge. Works on the SS canvas before finish()."""
    a = c.array().astype(np.float32)
    m = (a[..., 3] > 0) & (np.abs(a[..., 0] - colour[0]) < 2) & (np.abs(a[..., 1] - colour[1]) < 2) & \
        (np.abs(a[..., 2] - colour[2]) < 2)
    if only_alpha_of is not None:
        m &= only_alpha_of
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    gx = (xs - x0) / w - 0.5
    gy = (ys - y0) / h - 0.5
    grad = 1.0 + strength * (-(gx * light[0] + gy * light[1]) * 1.6)  # brighter towards the light
    grad = np.clip(grad, 1 - strength, 1 + strength * 0.75)
    # specular
    dx = (xs - x0) / w - spec[0]
    dy = (ys - y0) / h - spec[1]
    d = np.sqrt(dx * dx + dy * dy)
    sp = np.clip(1 - d / spec[2], 0, 1) ** 2 * 0.85
    # rim light (bottom right), darker core band just inside the bottom edge (contact shading)
    rim_v = np.clip((gx + gy) - 0.55, 0, 1) * rim * 2.5
    base = np.array(colour, np.float32)
    col = base[None, :] * grad[:, None]
    col = col + (255 - col) * (sp[:, None] * 0.9)
    col = col + (255 - col) * rim_v[:, None]
    a[ys, xs, :3] = np.clip(col, 0, 255)
    c.set_array(a)


def soft_shadow(c: Canvas, cx, cy, rx, ry, alpha=110, blur=1.2):
    s = Canvas(c.w, c.h)
    s.ellipse(cx, cy, rx, ry, (20, 24, 18, alpha))
    s.blur(blur)
    c.paste(s)


def alpha_blit(dst: np.ndarray, src: np.ndarray, x: int, y: int) -> None:
    """Composite RGBA src onto RGB(uint8) dst at (x,y), clipped. ~30 us for a 48x48 sprite."""
    H, W = dst.shape[:2]
    h, w = src.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    s = src[y0 - y:y1 - y, x0 - x:x1 - x]
    a = s[..., 3:4].astype(np.uint16)
    if not a.any():
        return
    d = dst[y0:y1, x0:x1]
    d[...] = ((s[..., :3].astype(np.uint16) * a + d.astype(np.uint16) * (255 - a)) // 255).astype(np.uint8)


def tint_rgba(src: np.ndarray, colour: Sequence[float]) -> np.ndarray:
    """Multiply an RGBA sprite's colour by a (r,g,b) factor triple (time-of-day light)."""
    out = src.copy()
    out[..., :3] = np.clip(src[..., :3].astype(np.float32) * np.array(colour, np.float32)[None, None, :], 0, 255)
    return out
