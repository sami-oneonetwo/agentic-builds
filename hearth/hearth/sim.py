"""The fire and the ring. Chat is wood. Silence is cold. No invented people."""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple


MOODS = ("ash", "embers", "campfire", "bonfire", "wildfire")

# heat thresholds. the size of the light is the meter.
ASH_MAX = 0.02
EMBERS_MAX = 0.18
CAMP_MAX = 0.48
BONFIRE_MAX = 0.78

RECENT_VOICE_S = 90.0          # only recent voices feed the flame
BUBBLE_S = 4.0
VOLUME_WINDOW_S = 8.0
WILDFIRE_COUNT = 8             # messages in the window that shove the fire over
MATCH_HEAT = 0.14
TORCH_HEAT = 0.38
MAX_HEAT = 1.15
SCAR_HEAT = 0.88
SPAM_GAP_S = 1.15


def mood_of(heat: float) -> str:
    if heat <= ASH_MAX:
        return "ash"
    if heat <= EMBERS_MAX:
        return "embers"
    if heat <= CAMP_MAX:
        return "campfire"
    if heat <= BONFIRE_MAX:
        return "bonfire"
    return "wildfire"


def _hash01(s: str) -> float:
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def name_hue(name: str) -> float:
    return _hash01("hue:" + name.lower()) * 360.0


def hex_to_rgb(color: str, fallback: Tuple[int, int, int] = (200, 160, 120)) -> Tuple[int, int, int]:
    if not color:
        return fallback
    s = color.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        return fallback
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return fallback


def hsl_to_rgb(h: float, s: float, l: float) -> Tuple[int, int, int]:
    h = (h % 360.0) / 360.0
    s = max(0.0, min(1.0, s))
    l = max(0.0, min(1.0, l))
    if s == 0:
        v = int(round(l * 255))
        return v, v, v

    def hue(p: float, q: float, t: float) -> float:
        if t < 0:
            t += 1
        if t > 1:
            t -= 1
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p

    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    r = hue(p, q, h + 1 / 3)
    g = hue(p, q, h)
    b = hue(p, q, h - 1 / 3)
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


def clothes_color(name: str, chat_hex: str = "") -> Tuple[int, int, int]:
    rgb = hex_to_rgb(chat_hex, fallback=(0, 0, 0))
    if rgb != (0, 0, 0) and max(rgb) > 30:
        # pull the chat colour toward something that reads on a dark hill
        return tuple(max(40, min(220, int(c * 0.7 + 40))) for c in rgb)  # type: ignore
    h = name_hue(name)
    return hsl_to_rgb(h, 0.45, 0.42)


def clean_text(raw: str) -> str:
    """Keep a person's words. Collapse Kick emote codes to a spark mark. No added copy."""
    if not raw:
        return ""
    out = []
    i = 0
    s = raw
    while i < len(s):
        if s.startswith("[emote:", i):
            close = s.find("]", i)
            if close > i:
                out.append("*")
                i = close + 1
                continue
        out.append(s[i])
        i += 1
    text = "".join(out)
    text = " ".join(text.split())
    if len(text) > 42:
        text = text[:41] + "…"
    return text


class Person:
    __slots__ = (
        "slug", "username", "color", "first_ts", "last_ts", "angle",
        "last_text", "last_text_ts", "scarred", "feeds",
    )

    def __init__(self, slug: str, username: str, color: str, first_ts: float, angle: float):
        self.slug = slug
        self.username = username
        self.color = color or "#C8A078"
        self.first_ts = first_ts
        self.last_ts = first_ts
        self.angle = angle
        self.last_text = ""
        self.last_text_ts = 0.0
        self.scarred = False
        self.feeds = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slug": self.slug,
            "username": self.username,
            "color": self.color,
            "first_ts": self.first_ts,
            "last_ts": self.last_ts,
            "angle": self.angle,
            "last_text": self.last_text,
            "last_text_ts": self.last_text_ts,
            "scarred": self.scarred,
            "feeds": self.feeds,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Person":
        p = cls(d["slug"], d.get("username") or d["slug"], d.get("color") or "#C8A078",
                float(d.get("first_ts") or 0), float(d.get("angle") or 0))
        p.last_ts = float(d.get("last_ts") or p.first_ts)
        p.last_text = d.get("last_text") or ""
        p.last_text_ts = float(d.get("last_text_ts") or 0)
        p.scarred = bool(d.get("scarred"))
        p.feeds = int(d.get("feeds") or 0)
        return p


class Hearth:
    """One fire. People exist because they spoke. Heat is presence, not virtue."""

    def __init__(self) -> None:
        self.people: Dict[str, Person] = {}
        self.heat: float = 0.10          # dying embers on an empty hill. no fake faces.
        self.shown_heat: float = 0.10    # eases toward heat so a log catching doesn't snap
        self.mood: str = "embers"
        self.coal_name: str = ""
        self.last_feed_ts: float = 0.0
        self.ash_since: float = 0.0
        self.seen_ids: Deque[str] = deque(maxlen=4000)
        self._seen_set = set()
        self.recent: Deque[Tuple[float, str, str]] = deque()  # ts, slug, word
        self.events: List[Dict[str, Any]] = []
        self.shake: float = 0.0
        self.last_tick: float = 0.0
        self.born: List[str] = []        # slugs that arrived this tick (for the pop)
        self.logs: List[str] = []        # slugs that fed this tick

    # ----- persistence -----------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "heat": self.heat,
            "mood": self.mood,
            "coal_name": self.coal_name,
            "last_feed_ts": self.last_feed_ts,
            "people": [p.to_dict() for p in self.people.values()],
        }

    def save(self, path: str) -> None:
        tmp = path + ".tmp"
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, separators=(",", ":"))
        os.replace(tmp, path)

    def load(self, path: str) -> None:
        if not os.path.isfile(path):
            return
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        self.heat = float(d.get("heat") or self.heat)
        self.shown_heat = self.heat
        self.mood = mood_of(self.heat)
        self.coal_name = d.get("coal_name") or ""
        self.last_feed_ts = float(d.get("last_feed_ts") or 0)
        self.people = {}
        for row in d.get("people") or []:
            try:
                p = Person.from_dict(row)
            except (KeyError, TypeError, ValueError):
                continue
            self.people[p.slug] = p

    # ----- chat ------------------------------------------------------------
    def ingest(self, rec: Dict[str, Any], now: float) -> Optional[Person]:
        """A real chat line. Returns the person if the line counted."""
        kind = rec.get("type") or "message"
        if kind not in ("message", "chat", ""):
            return None
        mid = str(rec.get("id") or "")
        if mid:
            if mid in self._seen_set:
                return None
            self.seen_ids.append(mid)
            self._seen_set.add(mid)
            if len(self.seen_ids) == self.seen_ids.maxlen:
                self._seen_set = set(self.seen_ids)
        slug = (rec.get("slug") or rec.get("username") or "").strip()
        if not slug:
            return None
        slug = slug.lower()
        username = (rec.get("username") or slug).strip()
        color = rec.get("color") or ""
        text = clean_text(rec.get("content") or rec.get("text") or "")
        first = slug not in self.people
        if first:
            p = Person(slug, username, color, now, self._next_angle(slug))
            self.people[slug] = p
            self.born.append(slug)
        else:
            p = self.people[slug]
            p.username = username or p.username
            if color:
                p.color = color
        p.last_ts = now
        p.last_text = text
        p.last_text_ts = now
        p.feeds += 1
        self.logs.append(slug)
        self.last_feed_ts = now
        self.coal_name = p.username
        word = (text.split() or [""])[0].lower()
        self.recent.append((now, slug, word))

        fuel = self._fuel(p, text, now)
        if self.mood == "ash" or self.heat <= ASH_MAX:
            self._relight(word, now, fuel)
        else:
            self.heat = min(MAX_HEAT, self.heat + fuel)
            n = self._volume(now)
            if n >= WILDFIRE_COUNT:
                self.heat = min(MAX_HEAT, self.heat + 0.08 + 0.015 * (n - WILDFIRE_COUNT))
                self.shake = min(1.0, self.shake + 0.35)
        self._maybe_scar(now)
        self.mood = mood_of(self.heat)
        return p

    def _fuel(self, p: Person, text: str, now: float) -> float:
        words = max(1, len(text.split())) if text else 1
        base = 0.055 + 0.012 * min(words, 8)
        # a second line from the same mouth still counts, but spam is damp twigs
        gap = now - (p.last_ts if p.feeds > 1 else now)
        # last_ts already updated; use feeds to detect repeats in the same ingest... use recent
        n_own = sum(1 for ts, slug, _ in self.recent if slug == p.slug and now - ts < SPAM_GAP_S)
        if n_own > 2:
            base *= 0.35
        elif n_own > 1:
            base *= 0.7
        if self.mood == "wildfire":
            base *= 0.85  # it is already eating; more talk is wind, not logs
        return base

    def _relight(self, word: str, now: float, fuel: float) -> None:
        # a match: any talk. a torch: the same word from three mouths.
        mouths = set()
        if word:
            for ts, slug, w in self.recent:
                if now - ts <= 8.0 and w == word:
                    mouths.add(slug)
        if len(mouths) >= 3:
            self.heat = max(self.heat, TORCH_HEAT)
            self.ash_since = 0.0
            self.events.append({"kind": "torch", "word": word, "ts": now})
            return
        self.heat = max(self.heat, MATCH_HEAT)
        self.heat = min(MAX_HEAT, self.heat + fuel * 0.4)
        self.ash_since = 0.0
        self.events.append({"kind": "match", "ts": now})

    def _volume(self, now: float) -> int:
        return sum(1 for ts, _, _ in self.recent if now - ts <= VOLUME_WINDOW_S)

    def _next_angle(self, slug: str) -> float:
        # horseshoe open toward the camera. 0 is east, pi/2 is south (front).
        # nobody sits due north, in the flame.
        lo, hi = 0.12 * math.pi, 0.88 * math.pi
        span = hi - lo
        prefer = lo + _hash01("seat:" + slug) * span
        taken = [p.angle for p in self.people.values()]
        if not taken:
            return prefer
        best = prefer
        best_d = -1.0
        for i in range(32):
            a = lo + ((prefer - lo + (i / 32.0) * span) % span)
            d = min(abs(math.atan2(math.sin(a - t), math.cos(a - t))) for t in taken)
            if d > best_d:
                best_d = d
                best = a
        return best

    def _maybe_scar(self, now: float) -> None:
        if self.heat < SCAR_HEAT:
            return
        # wildfire costs the quietest outer person. they stay. the ground remembers.
        quiet = [p for p in self.people.values() if not p.scarred and (now - p.last_ts) > 8.0]
        if not quiet:
            return
        quiet.sort(key=lambda p: p.last_ts)
        quiet[0].scarred = True
        self.events.append({"kind": "scar", "slug": quiet[0].slug, "ts": now})

    # ----- time ------------------------------------------------------------
    def tick(self, now: float, dt: float) -> None:
        self.born = []
        self.logs = []
        self.events = []
        while self.recent and now - self.recent[0][0] > 60.0:
            self.recent.popleft()
        # tau shortens as the fire grows: a bonfire is hungry, embers linger
        if self.heat <= ASH_MAX:
            tau = 80.0
        elif self.heat <= EMBERS_MAX:
            tau = 38.0
        elif self.heat <= CAMP_MAX:
            tau = 22.0
        elif self.heat <= BONFIRE_MAX:
            tau = 14.0
        else:
            tau = 7.5
        self.heat *= math.exp(-dt / tau)
        if self.mood == "wildfire":
            self.heat -= dt * 0.02  # it eats the ring
        if self.heat < 0:
            self.heat = 0.0
        if self.heat <= ASH_MAX:
            if self.ash_since <= 0:
                self.ash_since = now
            if now - self.ash_since > 2.2:
                self.heat = 0.0
        else:
            self.ash_since = 0.0
        self.mood = mood_of(self.heat)
        # picture/audio chase heat. rise is slow (a log catching); fall tracks the cool.
        if self.heat > self.shown_heat:
            k = 1.0 - math.exp(-dt / 1.15)
        else:
            k = 1.0 - math.exp(-dt / 0.40)
        self.shown_heat += (self.heat - self.shown_heat) * k
        if self.shown_heat < 0:
            self.shown_heat = 0.0
        self.shake *= max(0.0, 1.0 - dt * 2.4)
        self.last_tick = now

    def voices(self, now: float) -> List[Person]:
        return [p for p in self.people.values() if now - p.last_ts <= RECENT_VOICE_S]

    def ring(self) -> List[Person]:
        return list(self.people.values())

    def camera(self, now: float) -> Dict[str, float]:
        """Zoom and aim. Follows shown_heat so the room breathes instead of jumping."""
        h = self.shown_heat
        # 0 ash close → 1.15 wildfire pulled back
        stops = (
            (0.00, 1.55),
            (ASH_MAX, 1.52),
            (EMBERS_MAX, 1.38),
            (CAMP_MAX, 1.08),
            (BONFIRE_MAX, 0.92),
            (MAX_HEAT, 0.82),
        )
        zoom = stops[-1][1]
        for i in range(len(stops) - 1):
            h0, z0 = stops[i]
            h1, z1 = stops[i + 1]
            if h <= h1:
                t = 0.0 if h1 <= h0 else (h - h0) / (h1 - h0)
                zoom = z0 + (z1 - z0) * t
                break
        shake = 0.0
        if h > 0.70:
            shake = (h - 0.70) / 0.45 * 0.28
        shake = min(0.55, max(0.0, shake) + 0.25 * self.shake)
        return {"zoom": zoom, "shake": shake, "heat": h}


def parse_chat_line(line: str) -> Optional[Dict[str, Any]]:
    line = line.strip()
    if not line:
        return None
    try:
        rec = json.loads(line)
    except ValueError:
        return None
    if not isinstance(rec, dict):
        return None
    return rec
