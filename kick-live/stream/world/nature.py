"""nature.py - everything that moves on LONGGRASS that is not a person (docs/OPENWORLD.md sections 2.2, 4, 7.3 step 3).

    The wind is just the wind. Nothing here has a name, a count or a key: it is wind, cloud, water, sun, moon, tide,
    season and growth. It is declared as "world" on the ticker's honesty line, never counted as presence.

Wind        base speed = the REAL chat rate (msgs/min over 5 min) with a floor so still air never happens (6 cells/s at
            0 msg/min, 14 at 20, a gale above); direction drifts on a 40 s LFO; gust pulses every 6-20 s. Two travelling
            brightness fronts (wavelengths 40 and 90 cells, +-8 %) roll along the wind vector over grass cells only.
Clouds      2-3 soft angular shadow blobs 60-140 cells wide drift at the wind speed and darken the ground to 85 %.
Sun / moon  `tiles.sun_vector(hour)` is the light direction the atlas is lit by; `tint(hour, moon)` is the ground's
            daylight multiplier (dawn warm, noon neutral, dusk rose, night blue-grey) whose luminance never drops under
            the 0.55 FLOOR (+ up to 0.05 from the real moon phase); `shadow(hour)` is the shadow vector every caster
            (hut, tree, boulder) throws, long west at dawn, short at noon, long east at dusk, faint at night.
Water       a scrolled sparkle on water cells, moon glitter at night; the tide's wet-sand band moves 0-3 cells on the
            real 12 h 25 m tide.
Seasons     by the real date; hemisphere from the machine timezone (Australia/* -> south), overridable.
Growth      planted trees and sown fields advance by REAL calendar days whether or not the stream is live.
Weather     v1: rounds only (`Weather.set_round`); the seeded Markov chain is a v1.1 keeper ship (stub kept).
World day   `world_day="real"` (default) or `"hour"`: a 60-real-minute day (36 day / 6 dusk / 12 night / 6 dawn, noon
            at :30). The disclosed lever if 23:00 reads cold. Seasons and growth stay on real days either way.

The per-frame product is `Nature.modulation(view, now)`: one float32 (h, w, 3) field at CELL resolution for the
camera's window (110x320 at 1x, 147x427 at 0.75x) = tint x clouds x wind bands x shadow layer x sparkle x tide x rain.
bake.apply() repeats it x4 and multiplies it into the painted crop in fixed point. Nothing here touches a pixel.

    from stream.world import terrain, nature
    T = terrain.generate(4471)
    N = nature.Nature(T, seed=4471, world_day="real")
    N.update(now, chat_rate_per_min)                 # once per frame, before modulation()
    field = N.modulation((x0, y0, 320, 110), now)     # (110, 320, 3) float32, ~0.5 ms
    N.describe(now) -> {"clock": "18:07", "day_part": "evening", "wind": "wind NE · fresh", "season": "spring", ...}

Deterministic from (seed, now, chat rate); reads no clock itself (`now` is ctx.now). numpy only, Python 3.9.
"""
from __future__ import annotations

import math
import os
import time
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from stream.world.art import tiles

NIGHT_FLOOR = 0.55
MOON_MAX = 0.05
NIGHT_TINT = (0.52, 0.55, 0.74)          # luminance 0.557 x daylight: the floor, blue-grey, never black
# (hour, (r, g, b)) daylight multipliers; linear between keys
# every channel <= 1.0: the field only ever darkens or tints the painted ground (bake.apply takes the high byte of an
# 8x8-bit product, no clamp pass), so "warm dawn" is the blues held back, never the reds pushed past the paint
TINT_KEYS: Sequence[Tuple[float, Tuple[float, float, float]]] = (
    (0.0, NIGHT_TINT), (4.6, NIGHT_TINT), (5.6, (0.74, 0.70, 0.86)), (6.6, (1.00, 0.88, 0.78)), (8.0, (1.00, 0.96, 0.92)),
    (10.0, (1.0, 1.0, 1.0)), (16.0, (1.0, 1.0, 1.0)), (17.5, (1.00, 0.91, 0.81)), (18.7, (1.00, 0.80, 0.70)),
    (19.5, (0.86, 0.72, 0.82)), (20.6, NIGHT_TINT), (24.0, NIGHT_TINT),
)
DAY_PARTS = ((0, "night"), (5, "dawn"), (7, "morning"), (11, "midday"), (14, "afternoon"), (17, "evening"), (19.5, "dusk"), (20.6, "night"))
SEASON_NAMES = ("spring", "summer", "autumn", "winter")
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
TIDE_PERIOD_S = (12 * 60 + 25) * 60.0
SYNODIC_S = 29.530588853 * 86400.0
NEW_MOON_EPOCH = 1704628800.0            # 2024-01-07 12:00 UTC (a new moon, Fred Espenak's tables), fine to the hour
WIND_FLOOR, WIND_FRESH, WIND_GALE = 6.0, 14.0, 20.0      # cells/s at 0, 20 and 40+ msg/min
CLOUD_DARK = 0.15
WIND_AMP = 0.06                  # the bands swing 12 % crest to trough (0.88 .. 1.0), grass only
SHADOW_DARK = {"day": 0.80, "low": 0.78, "night": 0.90}


# ----------------------------------------------------------------------------- clock, hemisphere, season
def clock_shift_s(env=None) -> float:
    """TEST HOOK: `KL_CLOCK_SHIFT_S` (seconds added to the clock the LIGHT reads: hour, tint, sun, moon, season, dial
    text) so a harness can render dawn / noon / 23:00 frames on demand. Honoured only under MODE=test; 0 otherwise.
    It never moves entities, chat, rounds or persistence (they read ctx.now), only the sky over the land."""
    env = os.environ if env is None else env
    if env.get("MODE") != "test":
        return 0.0
    try:
        return float(env.get("KL_CLOCK_SHIFT_S") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def hemisphere_default() -> str:
    """'south' when the machine's timezone is Australian / NZ / southern American or African, else 'north'."""
    name = os.environ.get("TZ") or ""
    if not name:
        try:
            name = os.readlink("/etc/localtime")
        except Exception:
            name = ""
    name = name.lower()
    south = ("australia", "auckland", "pacific/auckland", "antarctica", "sao_paulo", "buenos_aires", "santiago",
             "johannesburg", "montevideo", "lima", "la_paz", "asuncion", "harare", "maputo", "windhoek", "port_moresby", "fiji")
    return "south" if any(k in name for k in south) else "north"


def local_tm(now: float, tz: Optional[str] = None) -> time.struct_time:
    if tz:
        try:
            from zoneinfo import ZoneInfo
            import datetime as _dt
            d = _dt.datetime.fromtimestamp(now, ZoneInfo(tz))
            return d.timetuple()
        except Exception:
            pass
    return time.localtime(now)


def real_hour(now: float, tz: Optional[str] = None) -> float:
    t = local_tm(now, tz)
    return t.tm_hour + t.tm_min / 60.0 + t.tm_sec / 3600.0


def compressed_hour(now: float, tz: Optional[str] = None) -> float:
    """world_day="hour": the minute of the real hour maps onto a 24 h world day: 36 min day (6:00-18:00, noon at :30),
    6 min dusk, 12 min night, 6 min dawn. 80 % of any watch is daylight."""
    t = local_tm(now, tz)
    m = t.tm_min + t.tm_sec / 60.0 + (now - math.floor(now))/60.0
    if 12 <= m < 48:
        return 6.0 + (m - 12) / 36.0 * 12.0
    if 48 <= m < 54:
        return 18.0 + (m - 48) / 6.0 * 2.0
    if 54 <= m < 60:
        return 20.0 + (m - 54) / 12.0 * 9.0
    if m < 6:
        return (24.5 + m / 12.0 * 9.0) % 24.0
    return 5.0 + (m - 6) / 6.0


def world_hour(now: float, world_day: str = "real", tz: Optional[str] = None) -> float:
    return compressed_hour(now, tz) if world_day == "hour" else real_hour(now, tz)


def day_part(hour: float) -> str:
    h = hour % 24.0
    name = DAY_PARTS[0][1]
    for start, n in DAY_PARTS:
        if h >= start:
            name = n
    return name


def season(now: float, hemisphere: Optional[str] = None, tz: Optional[str] = None) -> float:
    """Continuous season 0..4: 0 spring, 1 summer, 2 autumn, 3 winter (tiles.season_colour's scale). Southern spring
    starts 1 Sep; northern 1 Mar. Whole quarters, linear inside them."""
    hemi = hemisphere or hemisphere_default()
    t = local_tm(now, tz)
    month0 = t.tm_mon - 1
    start = 8 if hemi == "south" else 2                      # September / March
    rel = (month0 - start) % 12
    q, m_in = divmod(rel, 3)
    day_frac = (t.tm_mday - 1) / 31.0
    return (q + (m_in + day_frac) / 3.0) % 4.0


def season_index(s: float) -> int:
    return int(math.floor(s)) % 4


def season_name(s: float) -> str:
    return SEASON_NAMES[season_index(s)]


def moon_phase(now: float) -> float:
    """0 new .. 0.5 full .. 1 new again, from the mean synodic month."""
    return ((now - NEW_MOON_EPOCH) / SYNODIC_S) % 1.0


def moon_illumination(phase: float) -> float:
    return 0.5 * (1.0 - math.cos(2 * math.pi * phase))


def moon_label(phase: float) -> str:
    names = ("new moon", "waxing crescent", "first quarter", "waxing gibbous", "full moon", "waning gibbous", "last quarter", "waning crescent")
    return names[int((phase * 8 + 0.5) % 8)]


def tide_offset(now: float) -> float:
    """Wet-sand band width in cells, 0..3 on the real 12 h 25 m cycle (high tide = 3 cells wet)."""
    return 1.5 + 1.5 * math.sin(2 * math.pi * now / TIDE_PERIOD_S)


# ----------------------------------------------------------------------------- light
def sun_vector(hour: float) -> Tuple[float, float]:
    """Screen-space unit vector TOWARD the sun (x right, y down); the atlas lights every sprite with it."""
    return tiles.sun_vector(hour)


def night_amount(hour: float) -> float:
    """0 by day, 1 at full night, ramps over dusk (19.0-20.6) and dawn (4.6-6.2)."""
    h = hour % 24.0
    if 6.2 <= h <= 19.0:
        return 0.0
    if 19.0 < h < 20.6:
        return (h - 19.0) / 1.6
    if 4.6 < h < 6.2:
        return (6.2 - h) / 1.6
    return 1.0


def tint(hour: float, moon: float = 0.0) -> Tuple[float, float, float]:
    """Daylight multiplier for the ground at this hour; at night the 0.55 luminance floor plus up to 0.05 of moon."""
    h = hour % 24.0
    keys = TINT_KEYS
    for (h0, c0), (h1, c1) in zip(keys[:-1], keys[1:]):
        if h0 <= h <= h1:
            t = 0.0 if h1 == h0 else (h - h0) / (h1 - h0)
            r = c0[0] + (c1[0] - c0[0]) * t
            g = c0[1] + (c1[1] - c0[1]) * t
            b = c0[2] + (c1[2] - c0[2]) * t
            break
    else:
        r, g, b = NIGHT_TINT
    m = MOON_MAX * float(np.clip(moon, 0, 1)) * night_amount(h)
    return (r + m, g + m, b + m)


def luminance(rgb: Sequence[float]) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def shadow(hour: float) -> Tuple[float, float, float, float]:
    """(dx, dy, length, darkness): the unit shadow direction (away from the sun), the length in cells per unit caster
    height (long at dawn and dusk, short at noon, short and faint under the moon) and the darkening multiplier."""
    sx, sy = sun_vector(hour)
    alt = max(0.2, -sy)
    n = night_amount(hour)
    if n >= 1.0:
        L, dark = 0.7, SHADOW_DARK["night"]
    else:
        L = float(np.clip(0.9 / alt - 0.55, 0.35, 3.0))
        dark = SHADOW_DARK["low"] if L > 1.5 else SHADOW_DARK["day"]
        if n > 0:
            L = L * (1 - n) + 0.7 * n
            dark = dark * (1 - n) + SHADOW_DARK["night"] * n
    return (-sx, -sy, L, dark)


# ----------------------------------------------------------------------------- growth by real days
def tree_stage(planted_ts: float, now: float, orchard: bool = False) -> int:
    """0 sapling, 1 young (day 3), 2 canopy (day 14); 1.5x faster on the Orchard Slope. Never goes back."""
    days = max(0.0, (now - planted_ts) / 86400.0) * (1.5 if orchard else 1.0)
    return 2 if days >= 14 else (1 if days >= 3 else 0)


def tree_age_for_atlas(stage: int) -> int:
    """props.tree ages: sapling 0, young 1, grown 2 (the wild Wood also uses 3, old)."""
    return (0, 1, 2)[max(0, min(2, stage))]


def field_stage(sown_ts: float, now: float, rain_bonus_days: float = 0.0) -> int:
    """0 tilled, 1 sprout (day 1), 2 green (day 3), 3 gold (day 7); rain rounds add a fraction of a day."""
    days = max(0.0, (now - sown_ts) / 86400.0) + max(0.0, rain_bonus_days)
    return 3 if days >= 7 else (2 if days >= 3 else (1 if days >= 1 else 0))


def growth_label(kind: str, stage: int) -> str:
    if kind == "tree":
        return ("sapling", "young tree", "in full canopy")[max(0, min(2, stage))]
    return ("tilled", "sprouting", "green", "gold")[max(0, min(3, stage))]


# ----------------------------------------------------------------------------- wind
class Wind:
    """Base speed from the real chat rate, direction on a 40 s LFO, gust pulses every 6-20 s. Call update(now, rate)
    once per frame; read speed (cells/s), angle (radians, screen space, the direction the air MOVES), vector, dist
    (integrated travel in cells for the band phase), gust (0..1)."""

    def __init__(self, seed: int = 0):
        self.seed = int(seed)
        self.rate = 0.0
        self.speed = WIND_FLOOR
        self.base_angle = (self.seed * 0.61803398875) % 1.0 * 2 * math.pi
        self.angle = self.base_angle
        self.dist = 0.0
        self.gust = 0.0
        self.gust_front = 0.0
        self._last: Optional[float] = None
        self._gust_t0 = 0.0
        self._gust_next = 8.0

    def update(self, now: float, rate_per_min: float = 0.0, weather: str = "clear") -> None:
        rate = max(0.0, float(rate_per_min or 0.0))
        self.rate = rate
        if rate <= 20.0:
            target = WIND_FLOOR + (WIND_FRESH - WIND_FLOOR) * rate / 20.0
        else:
            target = WIND_FRESH + (WIND_GALE - WIND_FRESH) * min(1.0, (rate - 20.0) / 20.0)
        if weather == "gale":
            target = max(target, WIND_GALE)
        elif weather == "wind":
            target = max(target, WIND_FRESH)
        dt = 0.0 if self._last is None else max(0.0, min(1.0, now - self._last))
        self._last = now
        self.speed += (target - self.speed) * min(1.0, dt * 0.5)        # eases over ~2 s: chat storms build, not snap
        self.angle = self.base_angle + 0.55 * math.sin(2 * math.pi * now / 40.0) + 0.35 * math.sin(2 * math.pi * now / 610.0 + 1.0)
        self.dist += self.speed * dt
        # gusts: a seeded schedule; each gust is a front that travels ~1.6x the wind speed and fades over 3 s
        if now >= self._gust_t0 + self._gust_next:
            self._gust_t0 = now
            h = math.sin(now * 0.37 + self.seed) * 0.5 + 0.5
            self._gust_next = 6.0 + 14.0 * h
        age = now - self._gust_t0
        self.gust = max(0.0, 1.0 - age / 3.0) if age < 3.0 else 0.0
        self.gust_front = age * self.speed * 1.6

    @property
    def vector(self) -> Tuple[float, float]:
        return (math.cos(self.angle), math.sin(self.angle))

    def compass_from(self) -> str:
        """Where the wind comes FROM (the sailor's convention), screen north = up."""
        vx, vy = self.vector
        a = math.atan2(-vy, -vx)                              # the source direction in screen space (x right, y down)
        # screen angle 0 = east, -pi/2 = north (up)
        k = int(round((a + math.pi / 2) / (math.pi / 4))) % 8
        return COMPASS[k]

    def strength_word(self) -> str:
        s = self.speed
        return "calm" if s < 7 else ("light" if s < 9 else ("fresh" if s < 12 else ("strong" if s < 15 else "gale")))

    def label(self) -> str:
        return "wind %s · %s" % (self.compass_from(), self.strength_word())

    def atlas_phase(self, now: float) -> int:
        """The atlas wind phase (tiles.WIND_PLAY) the bake / props would use; sway rate follows the speed."""
        return tiles.WIND_PLAY[int(now * (0.9 + self.speed * 0.12)) % 6]


# ----------------------------------------------------------------------------- clouds
class Cloud:
    def __init__(self, seed: int, k: int, map_w: int, map_h: int):
        rng = np.random.RandomState(seed * 7 + k * 131)
        self.w = int(rng.randint(60, 141))
        self.h = int(self.w * rng.uniform(0.45, 0.7))
        self.x = float(rng.uniform(0, map_w))
        self.y = float(rng.uniform(0, map_h))
        self.map_w, self.map_h = map_w, map_h
        self.rng = rng
        # a soft angular blob: three offset ellipses, max'ed, then smoothed; alpha 0..1 at cell res
        yy, xx = np.mgrid[0:self.h, 0:self.w].astype(np.float32)
        a = np.zeros((self.h, self.w), np.float32)
        for _ in range(3):
            cx, cy = rng.uniform(0.3, 0.7) * self.w, rng.uniform(0.35, 0.65) * self.h
            rx, ry = rng.uniform(0.28, 0.42) * self.w, rng.uniform(0.28, 0.42) * self.h
            d = np.hypot((xx - cx) / rx, (yy - cy) / ry)
            a = np.maximum(a, np.clip(1.2 - d, 0, 1))
        from stream.world.terrain import box_blur
        a = box_blur(a, max(2, self.w // 14), 2)
        self.alpha = np.clip(a / max(1e-6, float(a.max())), 0, 1).astype(np.float32)

    def advance(self, dx: float, dy: float) -> None:
        self.x += dx
        self.y += dy
        margin_x, margin_y = self.w + 20, self.h + 20
        if self.x > self.map_w + margin_x:
            self.x = -margin_x
            self.y = float(self.rng.uniform(-margin_y, self.map_h + margin_y))
        elif self.x < -margin_x:
            self.x = self.map_w + margin_x
            self.y = float(self.rng.uniform(-margin_y, self.map_h + margin_y))
        if self.y > self.map_h + margin_y:
            self.y = -margin_y
            self.x = float(self.rng.uniform(-margin_x, self.map_w + margin_x))
        elif self.y < -margin_y:
            self.y = self.map_h + margin_y
            self.x = float(self.rng.uniform(-margin_x, self.map_w + margin_x))


class Clouds:
    """2-3 cloud SHADOWS (you never see the cloud, only its shadow, which is what a top-down view shows)."""

    def __init__(self, seed: int, map_w: int, map_h: int, n: Optional[int] = None):
        n = n if n is not None else 2 + (seed % 2)
        self.blobs: List[Cloud] = [Cloud(seed, k, map_w, map_h) for k in range(n)]
        self._last: Optional[float] = None

    def update(self, now: float, wind: Wind) -> None:
        dt = 0.0 if self._last is None else max(0.0, min(1.0, now - self._last))
        self._last = now
        vx, vy = wind.vector
        for b in self.blobs:
            b.advance(vx * wind.speed * dt, vy * wind.speed * dt)

    def field(self, x0: int, y0: int, w: int, h: int, dark: float = CLOUD_DARK) -> Optional[np.ndarray]:
        """Multiplier (h, w) float32 for the window at cell (x0, y0), or None when no shadow touches it."""
        out = None
        for b in self.blobs:
            bx0, by0 = int(round(b.x - b.w / 2)) - x0, int(round(b.y - b.h / 2)) - y0
            ax0, ay0 = max(0, bx0), max(0, by0)
            ax1, ay1 = min(w, bx0 + b.w), min(h, by0 + b.h)
            if ax1 <= ax0 or ay1 <= ay0:
                continue
            if out is None:
                out = np.ones((h, w), np.float32)
            sub = b.alpha[ay0 - by0:ay1 - by0, ax0 - bx0:ax1 - bx0]
            out[ay0:ay1, ax0:ax1] *= (1.0 - dark * sub)
        return out


# ----------------------------------------------------------------------------- weather (v1: rounds only)
class Weather:
    """v1: the round pick sets the weather for its window; otherwise clear. The seeded Markov chain per world-hour
    (clear / breeze / overcast / rain / gale, snow in winter) is a v1.1 keeper ship; `chain_seed` is kept for it."""

    STATES = ("clear", "breeze", "overcast", "rain", "gale", "fog", "wind", "snow")

    def __init__(self, chain_seed: int = 0):
        self.chain_seed = int(chain_seed)
        self.round_state: Optional[str] = None
        self.round_until = 0.0
        self.since_ts = 0.0

    def set_round(self, state: str, now: float, duration_s: float = 180.0) -> None:
        if state in self.STATES:
            self.round_state, self.round_until, self.since_ts = state, now + duration_s, now

    def state_at(self, now: float) -> str:
        if self.round_state and now < self.round_until:
            return self.round_state
        return "clear"

    def factors(self, now: float) -> Dict[str, float]:
        s = self.state_at(now)
        return {
            "darken": {"rain": 0.85, "overcast": 0.92, "gale": 0.90, "fog": 0.96, "snow": 0.95}.get(s, 1.0),
            "band_amp": {"gale": 1.8, "wind": 1.4, "breeze": 1.2}.get(s, 1.0),
            "river_swell": 1.3 if s == "rain" else 1.0,
        }


# ----------------------------------------------------------------------------- the facade
class Nature:
    """One object per scene. `update(now, chat_rate)` once per frame, then `modulation(view, now)`."""

    def __init__(self, terrain, seed: Optional[int] = None, hemisphere: Optional[str] = None, world_day: str = "real",
                 tz: Optional[str] = None, clouds: Optional[int] = None):
        self.T = terrain
        self.seed = int(seed if seed is not None else getattr(terrain, "seed", 0))
        self.hemisphere = hemisphere or hemisphere_default()
        self.world_day = world_day if world_day in ("real", "hour") else "real"
        self.tz = tz
        self.wind = Wind(self.seed)
        self.clouds = Clouds(self.seed, terrain.w, terrain.h, clouds)
        self.weather = Weather(self.seed)
        self.grass = terrain.grass_mask()
        self.water = terrain.water | (terrain.biome == 3)                 # ford water sparkles too
        self.sand = terrain.biome == 4
        self.now = 0.0
        self.clock_shift_s = clock_shift_s()      # TEST HOOK (MODE=test only): the light's clock, never the sim's
        self.degrade = {"clouds": True, "wind": True, "shadows": True, "sparkle": True}
        ph = np.arange(1440, dtype=np.float32) / 4.0
        self._band_lut = (1.0 - WIND_AMP * (1.0 - (0.5 * np.sin(ph * (2 * math.pi / 40.0)) + 0.5 * np.sin(ph * (2 * math.pi / 90.0) + 1.0)))).astype(np.float32)
        self.last_sparkle: Optional[Tuple[np.ndarray, np.ndarray, float]] = None
        self._grids: Dict[Tuple[int, int], Tuple[np.ndarray, np.ndarray]] = {}

    def _grid(self, w: int, h: int) -> Tuple[np.ndarray, np.ndarray]:
        g = self._grids.get((w, h))
        if g is None:
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            g = (xx, yy)
            if len(self._grids) > 8:
                self._grids.clear()
            self._grids[(w, h)] = g
        return g

    # -- per frame
    def update(self, now: float, chat_rate_per_min: float = 0.0) -> None:
        self.now = float(now)
        self.wind.update(now, chat_rate_per_min, self.weather.state_at(now))
        self.clouds.update(now, self.wind)

    # -- clock
    def _t(self, now: Optional[float]) -> float:
        """The clock the light reads: `now` (or the last update) plus the test-only shift (0 outside MODE=test)."""
        return (self.now if now is None else float(now)) + self.clock_shift_s

    def hour(self, now: Optional[float] = None) -> float:
        return world_hour(self._t(now), self.world_day, self.tz)

    def clock(self, now: Optional[float] = None) -> str:
        t = local_tm(self._t(now), self.tz)
        return "%02d:%02d" % (t.tm_hour, t.tm_min)

    def world_clock(self, now: Optional[float] = None) -> str:
        h = self.hour(now)
        return "%02d:%02d" % (int(h) % 24, int((h % 1.0) * 60))

    def season(self, now: Optional[float] = None) -> float:
        return season(self._t(now), self.hemisphere, self.tz)

    def sun(self, now: Optional[float] = None) -> Tuple[float, float]:
        return sun_vector(self.hour(now))

    def moon(self, now: Optional[float] = None) -> float:
        return moon_phase(self._t(now))

    def tint(self, now: Optional[float] = None) -> Tuple[float, float, float]:
        n = self._t(now)
        return tint(self.hour(n - self.clock_shift_s), moon_illumination(moon_phase(n)))

    def is_night(self, now: Optional[float] = None) -> bool:
        return night_amount(self.hour(now)) > 0.5

    def describe(self, now: Optional[float] = None) -> Dict:
        n = self.now if now is None else now
        h = self.hour(n)
        s = self.season(n)
        ph = moon_phase(n)
        return {
            "clock": self.clock(n), "world_clock": self.world_clock(n), "hour": round(h, 2), "day_part": day_part(h),
            "night": round(night_amount(h), 2), "wind": self.wind.label(), "wind_speed": round(self.wind.speed, 1),
            "wind_from": self.wind.compass_from(), "gust": round(self.wind.gust, 2), "season": season_name(s),
            "season_f": round(s, 2), "hemisphere": self.hemisphere, "moon": moon_label(ph), "moon_phase": round(ph, 3),
            "tide_cells": round(tide_offset(n), 2), "weather": self.weather.state_at(n), "world_day": self.world_day,
            "tint": tuple(round(v, 3) for v in self.tint(n)), "sun": tuple(round(v, 2) for v in self.sun(n)),
        }

    # -- the field
    def modulation(self, view: Tuple[float, float, int, int], now: Optional[float] = None,
                   caster: Optional[np.ndarray] = None) -> np.ndarray:
        """float32 (h, w, 3) multiplier for the window `view` = (x0, y0, w, h) in cells (x0, y0 may be floats; the
        field is computed at floor(x0), floor(y0)). `caster` overrides the terrain's caster layer (bake.casters_for_marks
        adds huts). Outside the map the field is the tint alone."""
        n = self.now if now is None else now
        x0f, y0f, w, h = view
        x0, y0 = int(math.floor(x0f)), int(math.floor(y0f))
        T = self.T
        hour = self.hour(n)
        moon = moon_illumination(moon_phase(self._t(n)))
        tr, tg, tb = tint(hour, moon)
        wf = self.weather.factors(n)
        mono = np.full((h, w), wf["darken"], np.float32)
        # map-window intersection (the camera clamp keeps this the whole window; be safe anyway)
        ax0, ay0 = max(0, x0), max(0, y0)
        ax1, ay1 = min(T.w, x0 + w), min(T.h, y0 + h)
        if ax1 <= ax0 or ay1 <= ay0:
            out = np.empty((h, w, 3), np.float32)
            out[..., 0], out[..., 1], out[..., 2] = tr, tg, tb
            return out
        sl_y, sl_x = slice(ay0, ay1), slice(ax0, ax1)
        vy, vx = slice(ay0 - y0, ay1 - y0), slice(ax0 - x0, ax1 - x0)
        sub = mono[vy, vx]
        # wind bands: two travelling fronts along the wind vector, grass only, plus the gust front. The two sines are
        # one 1-D function of the phase (period 360 cells), so a LUT replaces two transcendental passes.
        if self.degrade["wind"]:
            dx, dy = self.wind.vector
            xx, yy = self._grid(ax1 - ax0, ay1 - ay0)
            phase = xx * np.float32(dx) + yy * np.float32(dy)
            phase += np.float32((ax0 * dx + ay0 * dy - self.wind.dist) % 360.0)
            idx = (phase * np.float32(4.0)).astype(np.int32) % 1440
            band = np.take(self._band_lut, idx)
            if wf["band_amp"] != 1.0:
                band = 1.0 + (band - 1.0) * np.float32(wf["band_amp"])
            if self.wind.gust > 0:
                g = phase - np.float32(((ax0 * dx + ay0 * dy - self.wind.dist) % 360.0) + (self.wind.gust_front - 60.0) % 360.0)
                band = band + np.float32(0.06 * self.wind.gust) * np.exp(-(g / np.float32(14.0)) ** 2)
            band[~self.grass[sl_y, sl_x]] = 1.0
            if self.wind.gust > 0:
                np.minimum(band, 1.0, out=band)
            sub *= band
        # cloud shadows
        if self.degrade["clouds"]:
            cf = self.clouds.field(x0, y0, w, h)
            if cf is not None:
                mono *= cf
        # the shadow layer: every caster's shadow swings with the hour without a single blit
        if self.degrade["shadows"]:
            sdx, sdy, L, dark = shadow(hour)
            C = T.caster if caster is None else caster
            cmax = int(C[sl_y, sl_x].max()) if C[sl_y, sl_x].size else 0
            if cmax > 0:
                maxk = int(math.ceil(cmax * L))
                pad = maxk + 1
                px0, py0 = max(0, ax0 - pad), max(0, ay0 - pad)
                px1, py1 = min(T.w, ax1 + pad), min(T.h, ay1 + pad)
                Cp = C[py0:py1, px0:px1].astype(np.float32) * L
                sh = np.zeros(Cp.shape, bool)
                for k in range(1, maxk + 1):
                    m = Cp >= k
                    ox, oy = int(round(sdx * k)), int(round(sdy * k))
                    src_y0, src_y1 = max(0, -oy), min(Cp.shape[0], Cp.shape[0] - oy)
                    src_x0, src_x1 = max(0, -ox), min(Cp.shape[1], Cp.shape[1] - ox)
                    if src_y1 <= src_y0 or src_x1 <= src_x0:
                        continue
                    sh[src_y0 + oy:src_y1 + oy, src_x0 + ox:src_x1 + ox] |= m[src_y0:src_y1, src_x0:src_x1]
                shv = sh[ay0 - py0:ay1 - py0, ax0 - px0:ax1 - px0]
                sub *= np.where(shv, dark, 1.0).astype(np.float32)
        out = np.empty((h, w, 3), np.float32)
        out[..., 0] = mono * tr
        out[..., 1] = mono * tg
        out[..., 2] = mono * tb
        # water sparkle: an ADDITIVE highlight on a few water cells (bake.apply adds it per 4x4 block, so the
        # multiplicative field stays <= 1); moon glitter at night. The tide's wet band (x0.9) on the sand nearest the sea.
        self.last_sparkle = None
        if self.degrade["sparkle"]:
            wmask = self.water[sl_y, sl_x]
            if wmask.any():
                t = np.float32((n * 0.35 * wf["river_swell"]) % 1.0)           # the phase scroll as a SMALL scalar (float32 precision)
                ph = T.sparkle_phase[sl_y, sl_x] + t
                ph -= (ph >= 1.0).astype(np.float32)
                nt = night_amount(hour)
                thr = 0.94 + 0.03 * nt
                ys, xs = np.nonzero(wmask & (ph > thr))
                if len(ys):
                    gain = (0.28 + 0.22 * nt * moon) * luminance((tr, tg, tb)) * 255.0
                    self.last_sparkle = (ys + (ay0 - y0), xs + (ax0 - x0), float(gain))
            smask = self.sand[sl_y, sl_x]
            if smask.any():
                wet = smask & (T.shore_dist[sl_y, sl_x] <= 1.0 + tide_offset(n))
                if wet.any():
                    out[vy, vx] *= np.where(wet, np.float32(0.90), np.float32(1.0))[..., None]
        np.minimum(out, 1.0, out=out)
        return out


def fixed_point(field: np.ndarray) -> np.ndarray:
    """The field as uint8 x255 (it is <= 1.0 by construction): what bake.apply multiplies, keeping the high byte."""
    return np.clip(field * 255.0, 0, 255).astype(np.uint8)


if __name__ == "__main__":
    import sys
    from stream.world import terrain as _terrain
    T = _terrain.generate(4471)
    N = Nature(T, 4471)
    now = time.time()
    N.update(now, 3.0)
    for k, v in N.describe(now).items():
        print("  %s: %s" % (k, v))
    for h in (0, 5.5, 6.7, 9, 12, 17.5, 18.7, 19.5, 21, 23):
        tt = tint(h, 0.3)
        print("  tint %5.1f h -> %s lum %.3f  shadow %s" % (h, tuple(round(v, 2) for v in tt), luminance(tt), tuple(round(v, 2) for v in shadow(h))))
    assert luminance(tint(23.0, 0.0)) >= NIGHT_FLOOR, "night floor"
    t0 = time.perf_counter()
    for i in range(50):
        f = N.modulation((T.site[0] - 160, T.site[1] - 55, 320, 110), now + i / 30.0)
    print("modulation 320x110: %.2f ms/frame · shape %s · min %.2f max %.2f" % ((time.perf_counter() - t0) * 20, f.shape, f.min(), f.max()))
    t0 = time.perf_counter()
    for i in range(50):
        f = N.modulation((T.site[0] - 213, T.site[1] - 73, 427, 147), now + i / 30.0)
    print("modulation 427x147: %.2f ms/frame" % ((time.perf_counter() - t0) * 20))
    print("world_day=hour at :00 :10 :20 :30 :45 :50 :57 ->", [round(compressed_hour(3600 * 5 + m * 60), 1) for m in (0, 10, 20, 30, 45, 50, 57)])
