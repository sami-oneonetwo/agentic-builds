"""paint.py - tiny supersampled SDF painter shared by creatures.py and buildings.py (studio-a).

Shapes are described as signed-distance fields in unit coordinates (0..1 across a B px canvas),
painted front-to-back with premultiplied "over" blending at SS x resolution, then box-filtered down.
That is what gives every sprite soft, rounded edges at 32-48 px without any external asset.
numpy + pillow only.
"""
import colorsys
import numpy as np

SS = 4  # supersample factor


def hsv(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, min(1.0, max(0.0, s)), min(1.0, max(0.0, v)))
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def lerp(a, b, t):
    """a, b: rgb tuples or (..,3) arrays; t: scalar or (..) array."""
    a = np.asarray(a, np.float32)
    b = np.asarray(b, np.float32)
    t = np.asarray(t, np.float32)
    if t.ndim:
        t = t[..., None]
    return a * (1 - t) + b * t


# ----------------------------------------------------------------------------- sdf primitives (unit coords)
def ell(x, y, cx, cy, rx, ry):
    return (np.sqrt(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2) - 1.0) * min(rx, ry)


def circ(x, y, cx, cy, r):
    return np.hypot(x - cx, y - cy) - r


def seg(x, y, ax, ay, bx, by, r):
    """capsule from a to b with radius r"""
    px, py = x - ax, y - ay
    dx, dy = bx - ax, by - ay
    h = np.clip((px * dx + py * dy) / (dx * dx + dy * dy + 1e-9), 0, 1)
    return np.hypot(px - dx * h, py - dy * h) - r


def box(x, y, cx, cy, hx, hy, r=0.0):
    qx = np.abs(x - cx) - hx + r
    qy = np.abs(y - cy) - hy + r
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r


def union(*ds):
    return np.minimum.reduce(list(ds))


def smin(a, b, k):
    """smooth union"""
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b * (1 - h) + a * h - k * h * (1 - h)


def ring(d, w):
    return np.abs(d) - w


def rot(x, y, px, py, deg):
    """rotate the coordinate grid about (px, py); painting in the returned coords rotates the shape."""
    a = np.deg2rad(deg)
    c, s = np.cos(a), np.sin(a)
    dx, dy = x - px, y - py
    return px + c * dx - s * dy, py + s * dx + c * dy


class Canvas:
    def __init__(self, B, aspect=1.0):
        """B px wide canvas; height = B*aspect. Unit coords: x in 0..1, y in 0..aspect."""
        self.B = B
        self.Hpx = int(round(B * aspect))
        self.N = B * SS
        self.M = self.Hpx * SS
        self.rgb = np.zeros((self.M, self.N, 3), np.float32)
        self.a = np.zeros((self.M, self.N), np.float32)
        ys, xs = np.mgrid[0:self.M, 0:self.N].astype(np.float32)
        self.x = (xs + 0.5) / self.N
        self.y = (ys + 0.5) / self.N

    def paint(self, sdf, colour, alpha=1.0, soft=1.0):
        d = sdf * self.N
        cov = np.clip(0.5 - d / soft, 0, 1) * alpha
        if not cov.any():
            return
        col = np.asarray(colour, np.float32) / 255.0
        a = cov[..., None]
        self.rgb = col * a + self.rgb * (1 - a)
        self.a = cov + self.a * (1 - cov)

    def out(self):
        B, H = self.B, self.Hpx
        rgb = self.rgb.reshape(H, SS, B, SS, 3).mean((1, 3))
        a = self.a.reshape(H, SS, B, SS).mean((1, 3))
        aa = np.maximum(a[..., None], 1e-4)
        rgb = np.where(a[..., None] > 1e-4, rgb / aa, 0)
        return np.dstack([np.clip(rgb * 255, 0, 255), np.clip(a * 255, 0, 255)]).astype(np.uint8)


# ----------------------------------------------------------------------------- compositor-side blit
def blit(dst, spr, x, y, tint=None):
    """Alpha-blend RGBA sprite `spr` onto RGB uint8 `dst` with its top-left at (x, y). Clips. Optional
    tint = (r, g, b) multipliers (time-of-day). ~30-60 us for a 48 px sprite."""
    H, W = dst.shape[:2]
    h, w = spr.shape[:2]
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, W), min(y + h, H)
    if x1 <= x0 or y1 <= y0:
        return
    s = spr[y0 - y:y1 - y, x0 - x:x1 - x]
    a = s[..., 3:4].astype(np.float32) * (1.0 / 255.0)
    src = s[..., :3].astype(np.float32)
    if tint is not None:
        src = src * np.asarray(tint, np.float32)
    region = dst[y0:y1, x0:x1]
    region[...] = (src * a + region.astype(np.float32) * (1 - a)).astype(np.uint8)


def blit_add(dst, spr_rgb_f, x, y):
    """Additive glow: spr is float32 (h,w,3) 0..255 contribution."""
    H, W = dst.shape[:2]
    h, w = spr_rgb_f.shape[:2]
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, W), min(y + h, H)
    if x1 <= x0 or y1 <= y0:
        return
    s = spr_rgb_f[y0 - y:y1 - y, x0 - x:x1 - x]
    region = dst[y0:y1, x0:x1]
    region[...] = np.minimum(region.astype(np.float32) + s, 255).astype(np.uint8)
