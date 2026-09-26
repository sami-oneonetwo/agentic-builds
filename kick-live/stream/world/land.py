"""stream/world/land.py - LONGGRASS mutable land layers on world.json schema 2 (OPENWORLD.md 4.1-4.2, 5.2-5.4, 12).

The Land is everything real people leave on the ground: wear under their footsteps, marks (flower, tree, reed, flag,
notice), camps on the ladder hollow -> tent -> hut -> hut with a chimney, one field per person, stones on the cairn
and the ladder they fill, keeper raisings, opened land strips, plus the weather, the camera and the bake version the
scene needs across a hot-reload. Every mutable layer lives in `world.json["world"]` and every mark carries an owner
key that must exist in `world.json["pips"]` (the honesty rule: every name on this land is a real person who chatted).

    from stream.world.state import WorldState
    ws = WorldState(run_dir, schema=2)            # loads + migrates (guarded); ws.land is this module's object
    land = ws.land
    land.step("sami", cx, cy)                   # +8 on the cell, +2 on its 4 neighbours, cap 255, never decrements
    land.trail_tier(cx, cy)                     # 0 grass, 1 pressed (>= 8), 2 bare earth (>= 48), 3 road (>= 160)
    land.add_mark("flower", x, y, "sami", now)  # -> (mark, "ok") or (None, reason); owner must be a real pip
    land.set_camp("sami", x, y, now)            # camp rules 5.3; tier from sessions_seen via the ladder 1/2/5/10
    land.sow("sami", now) ; land.field_stage(f, now) ; land.harvest("sami", now)
    land.stack("sami", now) ; land.stock ; land.ladder() ; land.cairn_named() ; land.plaque()
    land.walked_mask() ; land.walked_fraction()  # minimap: cells within 24 of any real footstep; % from len()
    land.save_camera(cam.to_dict()) ; land.camera() ; land.set_weather("rain", now) ; land.bump_bake("hut tier")
    land.provenance_violations()                # every mark / camp / field / stone owner must be in pips

Pure helpers used by the migration: camp_tier_for_sessions(), hashed_camp_spot(), name_hash(), MAP_W / MAP_H.
Nothing here reads the clock or the run dir: callers pass `now`. Nothing here draws. numpy only, Python 3.9.
Honesty (OPENWORLD 12): wear is written only through `step()` for a real, non-test pip; the survey camera, the
weather and test pips never write wear or marks; absence is never punished (wear never decrements, marks never
decay, camps are never dismantled except by `!banish`, which keeps an audit record).
"""
from __future__ import annotations

import base64
import hashlib
import math
import zlib
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------- map constants (OPENWORLD 4.1)
MAP_W, MAP_H = 960, 440           # cells; 1 cell = 4x4 screen px at 1x
MAP_SEED = 4471                   # the approved mockup's seed is the first candidate (terrain.py owns generation)
EDGE_MARGIN = 12                  # the window never shows the map edge (camera clamp, 4.4)
STEADING_RING = (24, 60)          # camps cluster 24-60 cells from the Moot green
DEFAULT_MOOT = (MAP_W // 2, MAP_H // 2)   # until terrain.py's places registry is injected

# wear (5.2): +8 on the exact cell, +2 on its 4 neighbours per step into a new cell; never decrements
WEAR_STEP, WEAR_SPILL, WEAR_CAP = 8, 2, 255
WEAR_PRESSED, WEAR_BARE, WEAR_ROAD = 8, 48, 160
WALKED_RADIUS = 24                # minimap "walked" = within 24 cells of any real footstep (4.2)

# camps (5.3): sessions_seen -> tier 0 hollow / 1 tent / 2 hut / 3 hut with a chimney
CAMP_LADDER = (1, 2, 5, 10)
CAMP_KINDS = ("hollow", "tent", "hut", "hut_chimney")
CAMP_WORDS = ("camp", "tent", "hut", "hut")          # the plate word per tier
CAMP_GAP, CAMP_GAP_BONDED, BOND_MIN = 12, 6, 3       # cells between camps; bonded (3+ both ways) may sit at 6
MOOT_GREEN_R = 16                                     # no camp / mark on the Moot green

# fields (6 `sow`): stages by real days since sowing (rain rounds may advance `sown_ts` a fraction)
FIELD_W, FIELD_H = 3, 2
FIELD_STAGES = ((0.0, "tilled"), (1.0, "sprout"), (3.0, "green"), (7.0, "gold"))

# marks (6 `plant`): never on water, trail, the Moot green or within 4 cells of another person's mark
MARK_TYPES = ("flower", "tree", "reed", "flag", "notice")
MARK_GAP = 4
MARK_CAP_LIFETIME = 40
TREE_STAGES = ((0.0, "sapling"), (3.0, "young"), (14.0, "canopy"))

# stones / raisings (10)
STONE_LADDER = (20, 60, 150)
RAISING_NAMES = ("the Ford bridge", "the well", "the hall")
CAIRN_NAME_AT = 3                 # a cairn is NAMED when 3 distinct real people have stacked

WEATHER_STATES = ("clear", "breeze", "overcast", "rain", "gale", "fog", "snow")
NATURAL_POINTS = ("ford", "fell", "shore")

DAY_S = 86400.0


# ---------------------------------------------------------------------------- pure helpers
def name_hash(key: str, salt: str = "") -> int:
    """Deterministic 64-bit hash of a lower-cased username (sha1), independent of Python's hash seed."""
    h = hashlib.sha1(((key or "").lower() + salt).encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big")


def camp_tier_for_sessions(sessions_seen: int) -> int:
    """The camp ladder 5.3: 1 session -> 0 hollow, 2 -> 1 tent, 5 -> 2 hut, 10 -> 3 hut with a chimney. Never shrinks
    (sessions_seen never shrinks either); a pip with 0 sessions has no camp."""
    n = int(sessions_seen or 0)
    t = -1
    for i, need in enumerate(CAMP_LADDER):
        if n >= need:
            t = i
    return t


def clamp_cell(x: float, y: float, margin: int = EDGE_MARGIN) -> Tuple[float, float]:
    return (min(MAP_W - 1 - margin, max(margin, float(x))), min(MAP_H - 1 - margin, max(margin, float(y))))


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(float(ax) - float(bx), float(ay) - float(by))


def _ok_cell(x: float, y: float, passable: Optional[np.ndarray], water: Optional[np.ndarray]) -> bool:
    cx, cy = int(round(x)), int(round(y))
    if not (EDGE_MARGIN <= cx < MAP_W - EDGE_MARGIN and EDGE_MARGIN <= cy < MAP_H - EDGE_MARGIN):
        return False
    try:
        if passable is not None and not bool(passable[cy, cx]):
            return False
        if water is not None and bool(water[cy, cx]):
            return False
    except IndexError:
        return False
    return True


def hashed_camp_spot(key: str, moot: Tuple[float, float] = DEFAULT_MOOT, taken: Sequence[Tuple[float, float]] = (),
                     passable: Optional[np.ndarray] = None, water: Optional[np.ndarray] = None,
                     gap: int = CAMP_GAP, ring: Tuple[int, int] = STEADING_RING) -> Tuple[int, int]:
    """A camp position hashed from the name inside the Steading ring (5.4): angle and radius from sha1(name); if the
    spot is on water / impassable / on the green / within `gap` cells of a taken camp, the next hashed candidate is
    tried (up to 96), then the ring widens. Deterministic for (name, taken order)."""
    mx, my = float(moot[0]), float(moot[1])
    r0, r1 = ring
    for attempt in range(160):
        h = name_hash(key, ":camp:%d" % attempt)
        ang = (h % 3600) / 3600.0 * 2.0 * math.pi
        widen = 0 if attempt < 96 else (attempt - 95) * 4
        rad = r0 + ((h >> 16) % max(1, (r1 - r0) + 1)) + widen
        x, y = mx + rad * math.cos(ang), my + rad * math.sin(ang)
        x, y = clamp_cell(x, y)
        if rad < MOOT_GREEN_R + 2:
            continue
        if not _ok_cell(x, y, passable, water):
            continue
        if any(_dist(x, y, tx, ty) < gap for tx, ty in taken):
            continue
        return int(round(x)), int(round(y))
    x, y = clamp_cell(mx + r1, my)
    return int(round(x)), int(round(y))


def spot_beside(key: str, cx: float, cy: float, i: int, taken: Sequence[Tuple[float, float]] = (),
                passable: Optional[np.ndarray] = None, water: Optional[np.ndarray] = None,
                rmin: int = 3, rmax: int = 6, gap: int = MARK_GAP) -> Tuple[int, int]:
    """A mark spot 3-6 cells beside a camp, hashed from (name, i) so a migrated flower always lands in the same place."""
    for attempt in range(64):
        h = name_hash(key, ":mark:%d:%d" % (i, attempt))
        ang = (h % 3600) / 3600.0 * 2.0 * math.pi
        rad = rmin + ((h >> 16) % max(1, rmax - rmin + 1)) + (0 if attempt < 32 else attempt - 31)
        x, y = clamp_cell(cx + rad * math.cos(ang), cy + rad * math.sin(ang))
        if not _ok_cell(x, y, passable, water):
            continue
        if any(_dist(x, y, tx, ty) < gap for tx, ty in taken):
            continue
        return int(round(x)), int(round(y))
    x, y = clamp_cell(cx + rmax, cy)
    return int(round(x)), int(round(y))


def stage_by_days(stages: Sequence[Tuple[float, str]], age_s: Optional[float]) -> Tuple[int, str]:
    """(index, name) of the last stage whose day threshold the real age has passed."""
    if age_s is None:
        return 0, stages[0][1]
    days = max(0.0, float(age_s)) / DAY_S
    idx = 0
    for i, (d, _) in enumerate(stages):
        if days >= d:
            idx = i
    return idx, stages[idx][1]


def encode_wear(wear: np.ndarray) -> str:
    return base64.b64encode(zlib.compress(np.ascontiguousarray(wear, dtype=np.uint8).tobytes(), 6)).decode("ascii")


def decode_wear(b64: Optional[str], shape: Tuple[int, int] = (MAP_H, MAP_W)) -> np.ndarray:
    """uint8 (MAP_H, MAP_W); None / corrupt / wrong size -> zeros (a fresh land, nothing worn)."""
    if b64:
        try:
            raw = zlib.decompress(base64.b64decode(b64))
            a = np.frombuffer(raw, dtype=np.uint8)
            if a.size == shape[0] * shape[1]:
                return a.reshape(shape).copy()
        except Exception:
            pass
    return np.zeros(shape, dtype=np.uint8)


def dilate_square(mask: np.ndarray, radius: int) -> np.ndarray:
    """True within `radius` cells (Chebyshev) of any True cell: an integral-image box filter, O(N), numpy only."""
    m = mask.astype(np.int32)
    h, w = m.shape
    r = int(radius)
    pad = np.zeros((h + 2 * r + 1, w + 2 * r + 1), dtype=np.int32)
    pad[r + 1:r + 1 + h, r + 1:r + 1 + w] = m
    s = pad.cumsum(0).cumsum(1)
    k = 2 * r + 1
    tot = s[k:, k:] - s[:-k, k:] - s[k:, :-k] + s[:-k, :-k]
    return tot[:h, :w] > 0


# ---------------------------------------------------------------------------- the Land
class Land(object):
    """The mutable land layers of one WorldState (schema 2). Construct through `WorldState.land`."""

    def __init__(self, ws, moot: Optional[Tuple[float, float]] = None, log: Optional[Callable[[str], None]] = None):
        self.ws = ws
        self.log = log or getattr(ws, "log", None) or (lambda m: None)
        self.moot: Tuple[float, float] = tuple(moot) if moot else tuple(self.world.get("moot") or DEFAULT_MOOT)
        self.passable: Optional[np.ndarray] = None       # terrain.py layers, injected by the scene (set_terrain_layers)
        self.water: Optional[np.ndarray] = None
        self._wear: Optional[np.ndarray] = None
        self._wear_ver = 0                                 # bumps on every step(); the walked mask caches on it
        self._wear_saved_ver = 0
        self._walked: Optional[Tuple[int, np.ndarray, int]] = None
        self.wear_added_frame = 0                          # honesty: wear this module added since the last take_wear_added()
        self.steps_frame = 0

    # ------------------------------------------------------------------ document access
    @property
    def world(self) -> Dict[str, Any]:
        return self.ws.data["world"]

    @property
    def pips(self) -> Dict[str, Dict]:
        return self.ws.data["pips"]

    def _dirty(self) -> None:
        self.ws.dirty = True

    def set_terrain_layers(self, passable: Optional[np.ndarray] = None, water: Optional[np.ndarray] = None,
                           moot: Optional[Tuple[float, float]] = None) -> None:
        """The scene injects terrain.py's masks (bool (MAP_H, MAP_W)) and the Moot centre once they exist."""
        self.passable, self.water = passable, water
        if moot:
            self.moot = (float(moot[0]), float(moot[1]))
            self.world["moot"] = [int(round(self.moot[0])), int(round(self.moot[1]))]

    def real_pip(self, key: str) -> Optional[Dict]:
        """The pip row for a REAL chatter (test pips and unknown keys -> None): the provenance gate for every write."""
        p = self.pips.get((key or "").lower())
        if p is None or p.get("_test"):
            return None
        return p

    # ------------------------------------------------------------------ wear
    @property
    def wear(self) -> np.ndarray:
        if self._wear is None:
            self._wear = decode_wear(self.world.get("wear_b64"))
        return self._wear

    def step(self, key: str, cx: float, cy: float) -> int:
        """A real awake pip entered a new cell: +8 there, +2 on the 4 neighbours, cap 255. Returns the wear actually
        added (0 when refused: unknown / test pip, off-map). Only Behaviour._move may call this."""
        p = self.real_pip(key)
        if p is None:
            return 0
        x, y = int(round(cx)), int(round(cy))
        if not (0 <= x < MAP_W and 0 <= y < MAP_H):
            return 0
        w = self.wear
        added = 0
        for dx, dy, amt in ((0, 0, WEAR_STEP), (1, 0, WEAR_SPILL), (-1, 0, WEAR_SPILL), (0, 1, WEAR_SPILL), (0, -1, WEAR_SPILL)):
            xx, yy = x + dx, y + dy
            if 0 <= xx < MAP_W and 0 <= yy < MAP_H:
                old = int(w[yy, xx])
                new = min(WEAR_CAP, old + amt)
                if new != old:
                    w[yy, xx] = new
                    added += new - old
        if added:
            self._wear_ver += 1
            self.wear_added_frame += added
            self.steps_frame += 1
            self._dirty()
        return added

    def take_wear_added(self) -> Tuple[int, int]:
        """(wear added, steps) since the last call: the HonestyMonitor checks added == 8 x steps + spill (12 h)."""
        out = (self.wear_added_frame, self.steps_frame)
        self.wear_added_frame, self.steps_frame = 0, 0
        return out

    def wear_at(self, cx: float, cy: float) -> int:
        x, y = int(round(cx)), int(round(cy))
        if 0 <= x < MAP_W and 0 <= y < MAP_H:
            return int(self.wear[y, x])
        return 0

    @staticmethod
    def tier_of_wear(v: int) -> int:
        return 3 if v >= WEAR_ROAD else 2 if v >= WEAR_BARE else 1 if v >= WEAR_PRESSED else 0

    def trail_tier(self, cx: float, cy: float) -> int:
        """0 grass · 1 pressed grass (one walk is visible) · 2 bare earth · 3 stone-edged road."""
        return self.tier_of_wear(self.wear_at(cx, cy))

    def trail_tier_map(self) -> np.ndarray:
        """uint8 (MAP_H, MAP_W) of trail tiers, for the ground bake (trails by wear threshold)."""
        w = self.wear
        return (w >= WEAR_PRESSED).astype(np.uint8) + (w >= WEAR_BARE).astype(np.uint8) + (w >= WEAR_ROAD).astype(np.uint8)

    def is_trail(self, cx: float, cy: float) -> bool:
        return self.wear_at(cx, cy) >= WEAR_PRESSED

    @property
    def wear_version(self) -> int:
        return self._wear_ver

    def walked_mask(self, radius: int = WALKED_RADIUS) -> np.ndarray:
        """bool (MAP_H, MAP_W): within `radius` cells of any real footstep. Cached on the wear version, so a frame
        that calls it every 10 frames pays the ~5 ms box filter only after somebody actually walked."""
        if self._walked is None or self._walked[0] != self._wear_ver or self._walked[2] != radius:
            self._walked = (self._wear_ver, dilate_square(self.wear > 0, radius), radius)
        return self._walked[1]

    def walked_cells(self, radius: int = WALKED_RADIUS) -> int:
        return int(np.count_nonzero(self.walked_mask(radius)))

    def walked_fraction(self, radius: int = WALKED_RADIUS) -> float:
        """`4 % walked` = len(walked cells) / len(all cells)."""
        return self.walked_cells(radius) / float(MAP_W * MAP_H)

    def flush(self) -> None:
        """Serialise wear into world["wear_b64"] when it changed since the last flush (state.save calls this)."""
        if self._wear is not None and self._wear_ver != self._wear_saved_ver:
            self.world["wear_b64"] = encode_wear(self._wear)
            self._wear_saved_ver = self._wear_ver

    # ------------------------------------------------------------------ marks
    @property
    def marks(self) -> List[Dict]:
        return self.world.setdefault("marks", [])

    def _next_id(self, prefix: str) -> str:
        n = int(self.world.get("mark_seq") or 0) + 1
        self.world["mark_seq"] = n
        return "%s-%d" % (prefix, n)

    def marks_by(self, owner: str) -> List[Dict]:
        o = (owner or "").lower()
        return [m for m in self.marks if m.get("owner") == o]

    def marks_of_type(self, typ: str) -> List[Dict]:
        return [m for m in self.marks if m.get("type") == typ]

    def mark_near(self, x: float, y: float, gap: int = MARK_GAP, exclude_owner: Optional[str] = None) -> Optional[Dict]:
        for m in self.marks:
            if exclude_owner is not None and m.get("owner") == exclude_owner:
                continue
            if _dist(x, y, m.get("x", -999), m.get("y", -999)) < gap:
                return m
        return None

    def on_green(self, x: float, y: float) -> bool:
        return _dist(x, y, self.moot[0], self.moot[1]) < MOOT_GREEN_R

    def mark_allowed(self, key: str, x: float, y: float, typ: str = "flower") -> Tuple[bool, str]:
        """The `plant` placement rules (6): never on water, trail, the Moot green or within 4 cells of another
        person's mark; 40 marks lifetime. Per-session caps stay in the verbs agent."""
        p = self.real_pip(key)
        if p is None:
            return False, "no pip called @%s here" % (key or "?")
        if typ not in MARK_TYPES:
            return False, "you can plant a flower, a tree or reeds"
        if not _ok_cell(x, y, self.passable, self.water):
            return False, "nothing grows there"
        if self.water is not None and typ != "reed" and bool(self.water[int(round(y)), int(round(x))]):
            return False, "not on the water"
        if self.is_trail(x, y):
            return False, "not on a trail"
        if self.on_green(x, y):
            return False, "not on the Moot green"
        if self.mark_near(x, y, MARK_GAP, exclude_owner=(key or "").lower()) is not None:
            return False, "too close to someone's mark"
        if len(self.marks_by(key)) >= MARK_CAP_LIFETIME:
            return False, "you have left %d marks already" % MARK_CAP_LIFETIME
        return True, "ok"

    def add_mark(self, typ: str, x: float, y: float, owner: str, t: float, extra: Optional[Dict] = None,
                 check: bool = True) -> Tuple[Optional[Dict], str]:
        """Append a mark with provenance. `check=False` skips the placement rules (migration, keeper flags) but never
        the owner rule. Bumps bake_ver for marks that live in the painted ground (trees)."""
        okey = (owner or "").lower()
        p = self.real_pip(okey)
        if p is None:
            return None, "no pip called @%s here" % (owner or "?")
        if check:
            ok, reason = self.mark_allowed(okey, x, y, typ)
            if not ok:
                return None, reason
        m = {"id": self._next_id(typ), "type": typ, "x": int(round(x)), "y": int(round(y)), "owner": okey,
             "ts": self.ws.iso(t), "extra": dict(extra or {})}
        self.marks.append(m)
        mp = p.setdefault("marks_planted", {"flower": 0, "tree": 0, "reed": 0, "stone": 0})
        if typ in ("flower", "tree", "reed"):
            mp[typ] = int(mp.get(typ) or 0) + 1
        if typ == "tree":
            self.bump_bake("tree planted")
        self._dirty()
        return m, "ok"

    def tree_stage(self, mark: Dict, now: float, orchard: bool = False) -> Tuple[int, str]:
        """sapling -> young at day 3 -> canopy at day 14 by real days (1.5x on the Orchard Slope)."""
        t0 = self.ws.epoch(mark.get("ts"))
        age = None if t0 is None else (now - t0) * (1.5 if orchard else 1.0) + float((mark.get("extra") or {}).get("watered_s") or 0.0)
        return stage_by_days(TREE_STAGES, age)

    def remove_marks(self, owner: str) -> List[Dict]:
        """Every mark of an owner (`!banish`): returned for the audit record, removed from the land."""
        o = (owner or "").lower()
        gone = [m for m in self.marks if m.get("owner") == o]
        if gone:
            self.world["marks"] = [m for m in self.marks if m.get("owner") != o]
            self.bump_bake("marks removed")
            self._dirty()
        return gone

    # ------------------------------------------------------------------ camps (5.3)
    def camp_of(self, key: str) -> Optional[Dict]:
        p = self.real_pip(key)
        return p.get("camp") if p else None

    def camps(self) -> List[Dict]:
        """Derived: one entry per real pip with a camp: {key, x, y, tier, kind, built_ts, nights, last_seen_ts,
        sessions_seen, colour, display_name}. A `len()` over this is the `N camps` count."""
        out = []
        for k, p in self.pips.items():
            c = p.get("camp")
            if p.get("_test") or not isinstance(c, dict):
                continue
            tier = int(c.get("tier") or 0)
            out.append({"key": k, "x": c.get("x"), "y": c.get("y"), "tier": tier, "kind": CAMP_KINDS[min(3, max(0, tier))],
                        "word": CAMP_WORDS[min(3, max(0, tier))], "built_ts": c.get("built_ts"), "nights": len(c.get("nights") or []),
                        "last_seen_ts": p.get("last_seen_ts"), "sessions_seen": int(p.get("sessions_seen") or 0),
                        "colour": p.get("colour"), "display_name": p.get("display_name") or p.get("name") or k})
        return out

    @property
    def settled(self) -> int:
        """`17 SETTLED` = len(real pips with a camp)."""
        return sum(1 for p in self.pips.values() if isinstance(p.get("camp"), dict) and not p.get("_test"))

    def bonded(self, a: str, b: str) -> bool:
        pa, pb = self.real_pip(a), self.real_pip(b)
        if pa is None or pb is None:
            return False
        return int((pa.get("bonds") or {}).get(b) or 0) >= BOND_MIN and int((pb.get("bonds") or {}).get(a) or 0) >= BOND_MIN

    def camp_allowed(self, key: str, x: float, y: float) -> Tuple[bool, str]:
        """`camp` rules: within the Steading ring or anywhere passable, never on water, trail, the Moot green, or within
        12 cells of another's camp unless bonded (3+ both ways), then 6."""
        k = (key or "").lower()
        if self.real_pip(k) is None:
            return False, "no pip called @%s here" % (key or "?")
        if not _ok_cell(x, y, self.passable, self.water):
            return False, "you can't camp there"
        if self.is_trail(x, y):
            return False, "not on a trail"
        if self.on_green(x, y):
            return False, "the Moot green is everyone's"
        for c in self.camps():
            if c["key"] == k or c["x"] is None:
                continue
            gap = CAMP_GAP_BONDED if self.bonded(k, c["key"]) else CAMP_GAP
            if _dist(x, y, c["x"], c["y"]) < gap:
                return False, "too close to @%s's %s" % (c["display_name"], c["word"])
        return True, "ok"

    def set_camp(self, key: str, x: float, y: float, t: float, tier: Optional[int] = None, check: bool = True,
                 session_id: Optional[str] = None) -> Tuple[Optional[Dict], str]:
        """Pitch or move the camp to (x, y). Tier = the ladder over sessions_seen unless given; the old spot keeps its
        wear. `home` follows the camp. Bumps bake_ver (a hut lives in the painted ground)."""
        k = (key or "").lower()
        p = self.real_pip(k)
        if p is None:
            return None, "no pip called @%s here" % (key or "?")
        if check:
            ok, reason = self.camp_allowed(k, x, y)
            if not ok:
                return None, reason
        old = p.get("camp") if isinstance(p.get("camp"), dict) else None
        nights = list(old.get("nights") or []) if old else []
        if session_id and session_id not in nights:
            nights.append(session_id)
        if tier is None:
            tier = max(0, camp_tier_for_sessions(p.get("sessions_seen") or 0))
            if old is not None:
                tier = max(tier, int(old.get("tier") or 0))
        camp = {"x": int(round(x)), "y": int(round(y)), "tier": int(tier),
                "built_ts": (old or {}).get("built_ts") or self.ws.iso(t), "nights": nights}
        p["camp"] = camp
        p["home"] = [camp["x"], camp["y"]]
        self.bump_bake("camp %s" % ("moved" if old else "pitched"))
        self._dirty()
        return camp, "ok"

    def record_night(self, key: str, session_id: Optional[str], t: float) -> Optional[int]:
        """The owner slept at their camp this session: `nights` gains the session id and the tier is re-read from the
        ladder. Returns the new tier when it rose (the scene raises the upgrade over 12 frames), else None."""
        p = self.real_pip(key)
        if p is None or not session_id:
            return None
        camp = p.get("camp")
        if not isinstance(camp, dict):
            return None
        nights = camp.setdefault("nights", [])
        if session_id not in nights:
            nights.append(session_id)
            self._dirty()
        return self.upgrade_camp(key)

    def upgrade_camp(self, key: str) -> Optional[int]:
        """Re-read the ladder over sessions_seen; raise the tier when it crossed a threshold (never lowers)."""
        p = self.real_pip(key)
        camp = p.get("camp") if p else None
        if not isinstance(camp, dict):
            return None
        want = max(0, camp_tier_for_sessions(p.get("sessions_seen") or 0))
        if want > int(camp.get("tier") or 0):
            camp["tier"] = want
            self.bump_bake("camp tier")
            self._dirty()
            return want
        return None

    def plate(self, key: str, now: Optional[float] = None) -> Optional[Dict]:
        """Data for the camp plate: {word, night, built_night, last_seen_ts}; the text layer renders the words and runs
        the display name through the filter. `night` = len(nights) (or sessions_seen when nights is empty)."""
        p = self.real_pip(key)
        camp = p.get("camp") if p else None
        if not isinstance(camp, dict):
            return None
        nights = len(camp.get("nights") or []) or int(p.get("sessions_seen") or 0)
        return {"key": (key or "").lower(), "word": CAMP_WORDS[min(3, int(camp.get("tier") or 0))], "tier": int(camp.get("tier") or 0),
                "night": nights, "built_ts": camp.get("built_ts"), "last_seen_ts": p.get("last_seen_ts"),
                "colour": p.get("colour"), "x": camp.get("x"), "y": camp.get("y")}

    # ------------------------------------------------------------------ fields (`sow` / `harvest`)
    def field_of(self, key: str) -> Optional[Dict]:
        p = self.real_pip(key)
        f = p.get("field") if p else None
        return f if isinstance(f, dict) else None

    def sow(self, key: str, t: float) -> Tuple[Optional[Dict], str]:
        """Till a 3x2 field beside the camp (one per person). Refused without a camp or when a field exists."""
        k = (key or "").lower()
        p = self.real_pip(k)
        if p is None:
            return None, "no pip called @%s here" % (key or "?")
        camp = p.get("camp")
        if not isinstance(camp, dict):
            return None, "pitch a camp first"
        if isinstance(p.get("field"), dict):
            return None, "you already have a field"
        taken = [(m["x"], m["y"]) for m in self.marks] + [(c["x"], c["y"]) for c in self.camps() if c["key"] != k]
        fx, fy = spot_beside(k, camp["x"], camp["y"], 99, taken, self.passable, self.water, rmin=6, rmax=9, gap=4)
        f = {"x": fx, "y": fy, "sown_ts": self.ws.iso(t), "stage": "tilled", "harvests": 0, "waterers": [], "boost_s": 0.0}
        p["field"] = f
        self._reindex_fields()
        self.bump_bake("field sown")
        self._dirty()
        return f, "ok"

    def field_age_s(self, f: Dict, now: float) -> Optional[float]:
        t0 = self.ws.epoch(f.get("sown_ts"))
        if t0 is None:
            return None
        return (now - t0) + float(f.get("boost_s") or 0.0)

    def field_stage(self, f: Dict, now: float) -> Tuple[int, str]:
        """tilled -> sprout day 1 -> green day 3 -> gold day 7, by real days plus any rain / water boost."""
        return stage_by_days(FIELD_STAGES, self.field_age_s(f, now))

    def advance_fields(self, now: float, boost_s: float = 0.0) -> List[str]:
        """Refresh every field's stored `stage` (bumping bake_ver on a change); a rain round passes a boost.
        Returns the keys whose stage changed."""
        changed = []
        for k, p in self.pips.items():
            f = p.get("field")
            if p.get("_test") or not isinstance(f, dict):
                continue
            if boost_s:
                f["boost_s"] = float(f.get("boost_s") or 0.0) + float(boost_s)
                self._dirty()
            _, name = self.field_stage(f, now)
            if name != f.get("stage"):
                f["stage"] = name
                changed.append(k)
        if changed:
            self._reindex_fields()
            self.bump_bake("field stage")
            self._dirty()
        return changed

    def water_mark(self, key: str, by: str, now: float, hours: float = 6.0) -> Tuple[bool, str]:
        """`water @name` (v1.1): advance the target's field by 6 real hours, one waterer per field per session."""
        f = self.field_of(key)
        b = (by or "").lower()
        if f is None:
            return False, "@%s has no field" % (key or "?")
        if self.real_pip(b) is None:
            return False, "no pip called @%s here" % (by or "?")
        sid = getattr(self.ws, "session_id", None) or ""
        tag = "%s@%s" % (b, sid)
        if tag in (f.get("waterers") or []):
            return False, "you watered that field tonight already"
        f.setdefault("waterers", []).append(tag)
        f["boost_s"] = float(f.get("boost_s") or 0.0) + hours * 3600.0
        self._dirty()
        return True, "ok"

    def harvest(self, key: str, now: float) -> Tuple[bool, str]:
        """When gold: `harvests` += 1 and the field returns to tilled (sown now). Refused otherwise."""
        f = self.field_of(key)
        if f is None:
            return False, "you have no field. try: sow"
        idx, name = self.field_stage(f, now)
        if name != "gold":
            return False, "your field is %s, not gold yet" % name
        f["harvests"] = int(f.get("harvests") or 0) + 1
        f["sown_ts"] = self.ws.iso(now)
        f["boost_s"] = 0.0
        f["stage"] = "tilled"
        f["waterers"] = []
        self._reindex_fields()
        self.bump_bake("harvest")
        self._dirty()
        return True, "ok"

    def fields(self) -> List[Dict]:
        """Derived index of every real pip's field (also stored at world["fields"] for the renderer / minimap)."""
        return self._reindex_fields()

    def _reindex_fields(self) -> List[Dict]:
        out = []
        for k, p in self.pips.items():
            f = p.get("field")
            if p.get("_test") or not isinstance(f, dict):
                continue
            out.append({"owner": k, "x": f.get("x"), "y": f.get("y"), "w": FIELD_W, "h": FIELD_H, "stage": f.get("stage") or "tilled",
                        "harvests": int(f.get("harvests") or 0), "colour": p.get("colour")})
        self.world["fields"] = out
        return out

    def fields_gold(self, now: float) -> int:
        return sum(1 for p in self.pips.values() if isinstance(p.get("field"), dict) and not p.get("_test")
                   and self.field_stage(p["field"], now)[1] == "gold")

    # ------------------------------------------------------------------ stones, the cairn, the ladder (10)
    @property
    def stones(self) -> List[Dict]:
        return self.world.setdefault("stones", [])

    @property
    def stock(self) -> int:
        """Derived: len(stones)."""
        return len(self.stones)

    def stack(self, key: str, t: float, cairn_id: str = "moot") -> Tuple[Optional[Dict], str]:
        k = (key or "").lower()
        p = self.real_pip(k)
        if p is None:
            return None, "no pip called @%s here" % (key or "?")
        rec = {"by": k, "ts": self.ws.iso(t), "cairn_id": cairn_id}
        self.stones.append(rec)
        mp = p.setdefault("marks_planted", {"flower": 0, "tree": 0, "reed": 0, "stone": 0})
        mp["stone"] = int(mp.get("stone") or 0) + 1
        self._dirty()
        return rec, "ok"

    def stackers(self, cairn_id: str = "moot") -> Dict[str, int]:
        out: Dict[str, int] = {}
        for s in self.stones:
            if s.get("cairn_id", "moot") == cairn_id:
                out[s["by"]] = out.get(s["by"], 0) + 1
        return out

    def plaque(self, cairn_id: str = "moot", n: int = 3) -> List[Tuple[str, int]]:
        """Top `n` distinct stackers by count (keys; the text layer filters the names)."""
        return sorted(self.stackers(cairn_id).items(), key=lambda kv: (-kv[1], kv[0]))[:n]

    def cairn_height(self, cairn_id: str = "moot") -> int:
        return sum(1 for s in self.stones if s.get("cairn_id", "moot") == cairn_id)

    def cairn_named(self, cairn_id: str = "moot") -> bool:
        """Named when 3 distinct real people have stacked."""
        return len(self.stackers(cairn_id)) >= CAIRN_NAME_AT

    def ladder(self) -> Dict[str, Any]:
        """{stock, next, index, name, done}: `stone 13 of 20 · the Ford bridge`."""
        stock = self.stock
        done = len(self.raisings)
        idx = min(done, len(STONE_LADDER) - 1)
        nxt = STONE_LADDER[idx] if done < len(STONE_LADDER) else None
        return {"stock": stock, "next": nxt, "index": idx, "name": RAISING_NAMES[idx] if done < len(RAISING_NAMES) else None,
                "done": done, "ready": nxt is not None and stock >= nxt, "last_by": self.stones[-1]["by"] if self.stones else None}

    @property
    def raisings(self) -> List[Dict]:
        return self.world.setdefault("raisings", [])

    def add_raising(self, name: str, version: str, t: float, at_stock: Optional[int] = None) -> Dict:
        rec = {"name": name, "at_stock": int(self.stock if at_stock is None else at_stock), "shipped_ts": self.ws.iso(t),
               "version": version, "plaque": [k for k, _ in self.plaque()]}
        self.raisings.append(rec)
        self.bump_bake("raising")
        self._dirty()
        return rec

    @property
    def land_strips(self) -> List[Dict]:
        return self.world.setdefault("land_strips", [])

    def open_strip(self, side: str, biome: str, by: Optional[str], version: str, t: float) -> Dict:
        rec = {"side": side, "biome": biome, "opened_ts": self.ws.iso(t), "by": (by or "").lower() or None, "version": version}
        self.land_strips.append(rec)
        self.bump_bake("land strip")
        self._dirty()
        return rec

    # ------------------------------------------------------------------ weather, camera, hearth, bake, days
    def weather(self) -> Dict[str, Any]:
        return self.world.setdefault("weather", {"state": "clear", "since_ts": None, "chain_seed": MAP_SEED})

    def set_weather(self, state: str, t: float, until_ts: Optional[float] = None) -> Dict[str, Any]:
        w = self.weather()
        if state not in WEATHER_STATES:
            state = "clear"
        if w.get("state") != state or until_ts is not None:
            w["state"], w["since_ts"] = state, self.ws.iso(t)
            w["until_ts"] = self.ws.iso(until_ts) if until_ts else None
            self._dirty()
        return w

    def camera(self) -> Optional[Dict[str, Any]]:
        c = self.world.get("camera")
        return dict(c) if isinstance(c, dict) else None

    def save_camera(self, d: Dict[str, Any]) -> None:
        self.world["camera"] = dict(d)
        self._dirty()

    @property
    def hearth(self) -> Dict[str, Any]:
        return self.world.setdefault("hearth", {"lit_ts": None, "by": None})

    def light_hearth(self, by: str, t: float) -> bool:
        if self.real_pip(by) is None:
            return False
        self.hearth["lit_ts"], self.hearth["by"] = self.ws.iso(t), (by or "").lower()
        self._dirty()
        return True

    def hearth_lit(self, session_started: Optional[float]) -> bool:
        """The Moot hearth burns only if a real person lit it THIS session."""
        t = self.ws.epoch(self.hearth.get("lit_ts"))
        return t is not None and session_started is not None and t >= session_started - 60.0

    @property
    def bake_ver(self) -> int:
        return int(self.world.get("bake_ver") or 1)

    def bump_bake(self, reason: str = "") -> int:
        self.world["bake_ver"] = self.bake_ver + 1
        self.world["bake_reason"] = reason
        self._dirty()
        return self.world["bake_ver"]

    @property
    def days(self) -> int:
        """`day 6 of Longgrass` = len(distinct session ids seen)."""
        return len({s.get("id") for s in (self.ws.data.get("sessions") or []) if s.get("id")})

    def counts(self, now: float) -> Dict[str, int]:
        """Every number a strip may draw, each a len(): camps, fields, fields_gold, trees, flowers, stones, marks, days, settled."""
        return {"camps": len(self.camps()), "fields": len(self.fields()), "fields_gold": self.fields_gold(now),
                "trees": len(self.marks_of_type("tree")), "flowers": len(self.marks_of_type("flower")),
                "stones": self.stock, "marks": len(self.marks), "days": self.days, "settled": self.settled,
                "walked_pct": int(round(100.0 * self.walked_fraction()))}

    # ------------------------------------------------------------------ survey stops for the DRIFT camera
    def survey_stops(self, natural: Optional[Sequence[Dict]] = None) -> List[Dict]:
        """Every real mark the DRIFT camera may visit (camps, fields, trees, the cairn when it has stones) plus the
        three fixed natural points the scene passes. Nothing else: the camera never frames emptiness as if someone
        were there."""
        stops: List[Dict] = []
        for c in self.camps():
            if c["x"] is not None:
                stops.append({"id": "camp:" + c["key"], "kind": "camp", "owner": c["key"], "x": c["x"], "y": c["y"]})
        for f in self.fields():
            stops.append({"id": "field:" + f["owner"], "kind": "field", "owner": f["owner"], "x": f["x"], "y": f["y"]})
        for m in self.marks_of_type("tree"):
            stops.append({"id": m["id"], "kind": "tree", "owner": m["owner"], "x": m["x"], "y": m["y"]})
        if self.stock:
            stops.append({"id": "cairn:moot", "kind": "cairn", "owner": None, "x": int(self.moot[0]), "y": int(self.moot[1])})
        for n in natural or []:
            stops.append({"id": "natural:" + str(n.get("kind")), "kind": "natural", "owner": None, "x": n["x"], "y": n["y"],
                          "name": n.get("name") or n.get("kind")})
        return stops

    # ------------------------------------------------------------------ honesty (12)
    def provenance_violations(self) -> List[str]:
        """Every mark, camp, field, stone, raising plaque name and hearth lighter must resolve to a real pip row."""
        out = []
        for m in self.marks:
            if self.real_pip(m.get("owner") or "") is None:
                out.append("mark %s (%s) owner %r has no pip" % (m.get("id"), m.get("type"), m.get("owner")))
        for s in self.stones:
            if self.real_pip(s.get("by") or "") is None:
                out.append("stone by %r has no pip" % (s.get("by"),))
        for k, p in self.pips.items():
            if p.get("_test") and (p.get("camp") or p.get("field")):
                out.append("test pip %s owns a camp or field" % k)
        for r in self.raisings:
            for k in r.get("plaque") or []:
                if self.real_pip(k) is None:
                    out.append("raising %r plaque names %r with no pip" % (r.get("name"), k))
        if self.hearth.get("by") and self.real_pip(self.hearth["by"]) is None:
            out.append("hearth lit by %r with no pip" % (self.hearth["by"],))
        return out

    def purge_owner(self, key: str) -> Dict[str, Any]:
        """`!banish`: remove the owner's marks, stones, camp and field from the land; return the audit record."""
        k = (key or "").lower()
        gone_marks = self.remove_marks(k)
        gone_stones = [s for s in self.stones if s.get("by") == k]
        if gone_stones:
            self.world["stones"] = [s for s in self.stones if s.get("by") != k]
        p = self.pips.get(k)
        rec = {"marks": gone_marks, "stones": gone_stones, "camp": p.get("camp") if p else None, "field": p.get("field") if p else None}
        if p is not None:
            p["camp"], p["field"], p["home"] = None, None, None
        if self.hearth.get("by") == k:
            self.hearth["lit_ts"], self.hearth["by"] = None, None
        self._reindex_fields()
        self.bump_bake("banish")
        self._dirty()
        return rec

    def restore_owner(self, key: str, rec: Optional[Dict[str, Any]]) -> None:
        """`!unbanish`: put the audit record's marks / stones / camp / field back."""
        k = (key or "").lower()
        p = self.pips.get(k)
        if p is None or not isinstance(rec, dict):
            return
        for m in rec.get("marks") or []:
            self.marks.append(m)
        for s in rec.get("stones") or []:
            self.stones.append(s)
        if isinstance(rec.get("camp"), dict):
            p["camp"] = rec["camp"]
            p["home"] = [rec["camp"].get("x"), rec["camp"].get("y")]
        if isinstance(rec.get("field"), dict):
            p["field"] = rec["field"]
        self._reindex_fields()
        self.bump_bake("unbanish")
        self._dirty()


__all__ = ["Land", "MAP_W", "MAP_H", "MAP_SEED", "EDGE_MARGIN", "STEADING_RING", "DEFAULT_MOOT", "CAMP_LADDER",
           "CAMP_KINDS", "CAMP_WORDS", "STONE_LADDER", "RAISING_NAMES", "FIELD_STAGES", "TREE_STAGES", "MARK_TYPES",
           "WEATHER_STATES", "name_hash", "camp_tier_for_sessions", "hashed_camp_spot", "spot_beside", "stage_by_days",
           "encode_wear", "decode_wear", "dilate_square", "clamp_cell"]
