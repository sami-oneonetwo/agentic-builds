"""stream/world/behaviour.py - what pips do on the land, frame by frame (OPENWORLD.md 3, 4.4 gravity, 5.1, 6, 12; row 5
of the build order; docs/AGES.md 1, 4, 8: nobody lies down). The 2D rewrite of the cave's state machine: the entity
states, the hold timing, speak / hop / blink, care and credits are kept; positions are MAP CELLS (960x440, 1 cell =
4 px at 1x), targets are 2D with easing, walks follow terrain.py's coarse BFS route with a one-cell slide rule and a
3 s stuck detector, the idle life is an errand table (home / Moot / water / stroll) the land runs for here and away
settlers alike, camps are homes, votes are standing slots at the three waystones, a pip can carry a berry or a
stone, and a newcomer is a nameless tuft on the wind until the hold clears.

TWO AXES (AGES 1.1). Presence is about the PERSON and is derived, never stored, never drawn as a count:
`Entity.is_present(t)` = the owner's record landed within `present_s` (1200 s) of now (`t - last_active_t`); it gates
every verb, bubble, mutter, hop, vote, mark, fire, wear and the camera's FOLLOW list. Activity is the body's state
(`STATES`): a settler is `ON_LAND` (idle / walking / voting / sitting / hauling) from its hatch onward, forever minus
`!banish`; `hidden` (mod !hide) is the ONE lying pose. Nobody sleeps, nobody walks home to lie down, nothing decays.

    from stream.world.behaviour import Behaviour, waystone_positions
    b = Behaviour(seed=41370704, present_s=1200.0, hold_s=3.0,     # sleep_after_s= is the same knob (alias, one release)
                  terrain=T,                  # terrain.generate(4471): passable / cost / route / places (None = flat test land)
                  land=ws.land,               # wear under real footsteps via land.step() (None = no wear)
                  moot=T.site,                # the Moot green centre (seeds land here, wander gravity, waystones)
                  wind=lambda: N.wind.vector, # unit vector the wind blows TOWARD; the tuft rides it in (or a fixed tuple)
                  sheet_ready=lambda key: True)  # the art cache says the settler's sheet is rendered; a hatch waits (<= 4 s) for it
    b.seed_drop(key, t)                        # a record landed: a nameless tuft drifts in from upwind toward a hashed spot on the green
    b.hold_cleared(key, t, display_name, tier, energy, salt, first_ever)   # the bridge cleared the hold: the tuft may pop
    b.sink(key, t)                             # hidden inside the hold / never cleared: the wind takes the tuft, nothing hatches
    b.place_settler(key, tier, energy, salt, camp, display_name, t=now, x=None, y=None, last_seen=None)   # boot: a past
                                               # chatter STANDING where the record last saw it (else the camp door); here iff
                                               # last_seen is inside present_s (place_sleeper is the same call, alias kept)
    b.message(key, t, seen_t=None)             # existing pip, record landed (pre-hold): hop + brighten; a gap > present_s is a
                                               # `return` (drop the errand, hop, face the camera); seen_t = the record's own time
    b.speak(key, t, text, learned_from=None)   # after the hold: bubble 8 s; settlers within 50 cells look toward the speaker
    b.walk_to(key, "A"|"B"|"C"|(x, y), t, then="idle")   # vote at a waystone slot / walk somewhere; then = what to do on arrival
    b.go(key, "river"|"north"|"home"|"@name", t) -> (ok, reason)   # the `go` verb: places, 8 directions (60 cells), home, a person
    b.fetch(key, (px, py), (qx, qy), t, kind="stone")    # `stack`: walk to a stone, carry it, walk to the cairn, place it
    b.carry(key, t, "berry") ; b.drop(key, t) ; b.hop(key, t) ; b.emote(key, "wave"|"sit"|"dance", t)
    b.care_received(key, t, by) ; b.set_camp(key, x, y) ; b.hide(key, t) ; b.crowd_bounce("A", t)
    b.release_votes(t) ; b.start_credits(t) ; b.set_tier(key, tier, t)
    b.session_id = ctx.session["id"]           # the scene's session (camps are the scene's / the land's business now)
    b.night = 0.0                              # nature.night_amount (0 day .. 1 night) or a callable: the errand table's weights
    events = b.tick(t, dt)                     # advance one frame; returns this frame's events (EVENTS below)
    b.entities ; b.present() ; b.present_count() ; b.awake() (= on the land) ; b.platform_counts() ; b.newest_speaker
    b.awake_count() (= present_count, alias one release) ; b.asleep_count() (always 0; goes once its callers are gone)
    b.waystones                                # [(x, y)] x3 for A / B / C on the Moot
    b.camera_inputs(t, round_remaining=None)   # {"awake": [HERE settlers], "seeds": [(x, y)], "moot": {...}} for Camera.update()

EVENTS (dicts, `type` first; names kept from the cave so audio / text-layer / rounds consumers still match): seed,
seed_land, sink, hatch, first_light (= the spec's "first breath"), return (the old `wake`: away -> here; carries
`camp`, `away_s`, `only_light`), speak, hop, walk, arrive, leave_platform, blink, tier_up, emote, credits_start,
credits, credits_end, mutter_due, burrowed (a mod hid the user: state `hidden`), plus the land's: stuck (QA counter;
a reroute follows), pickup, place (a carried thing set down: the scene calls land.stack for a stone). There is no
`sleep`, `wake`, `curl` or `uncurl` event any more. Every event carries `pip` (the lowercase key) except seed /
seed_land / sink (`key` only: nothing about a tuft may be drawn as a name). `walk` carries `to` (a letter, a place
name, or [x, y]: an errand's `to` is always the cell pair) and `then` (`vote`, `idle`, `errand:<name>`, `sit`,
`credits`, `pickup:...`, `place:...`); `arrive` carries `at` (letter / then-tag), `gave_up` when the stuck detector
ended a walk and `short` when the target lay across water and the pip stopped on the nearest reachable bank cell.

IDLE LIFE (AGES 1.3, the minimal table): once per dwell end (never per frame) `_pick_idle` draws an errand for a
here or away settler alike: home (its camp door; 25 day / 55 night), moot (a free cell on the Moot ring 10-24 cells
out; 20 / 10), water (the nearest bank within 160 cells, 50 % sit; 15 / 5), stroll (the old +/-8-40 cell hop with
30 % Moot gravity and the 200-cell cap; 15). Never the same errand twice running; every weight shifts +/-30 % per
name and a per-name `tempo` 0.75-1.3 scales the dwell and the 4-6 cells/s errand speed, so twenty idlers desync for
free. An errand is the land's, not the person's: `then` = `errand:<name>` (or `sit`), `last_active_t` is untouched,
no wear is laid unless the person is here, nothing is said, no stone is stood at. `huddle` (rounds) is kept one
release: every errand aims at the Moot; `follow` and `scatter` are gone.

PATHING: terrain.route() on the 60x28 block grid (a block is open at >= 50 % passable, so a river or the Wood's edge
can still cut a leg); a clear straight line up to 48 cells skips it; the route is string-pulled; a leg the line cannot
cross is refined by a bounded cell-level wavefront BFS (`_Ground.local_path`, ~0.6 ms, spliced once per leg); the
one-cell slide rule skirts convex trunks and banks between refinements; 3 s without progress = `stuck` (a fresh route,
then the walk ends where the pip stands). Measured on this Mac: 60 test pips x 5 min of random `go` targets = 0 stuck,
0 in water, tick 0.32 ms avg (see the self-test: `RUN_DIR=/tmp/lg-behaviour $PYTHON stream/world/behaviour.py`).

HONESTY (OPENWORLD 12, AGES 4): an Entity exists only because `seed_drop` / `place_settler` was called for a real
chat record (origin "chat") or by the test-pip hook (origin "test", refused outside test mode by the scene). Nothing
here invents an entity. Nothing moves itself except a pip; the tuft is moved by the wind (a real vector from the real
chat rate); an away settler is moved by the land (the errand table) the way wind moves grass. Wear is written only
from `_move` for a PRESENT origin-"chat" pip through `land.step()` (which itself refuses test / unknown keys). An
away settler never speaks, mutters, hops, votes, carries, wears a trail or stands at a stone. Absence is never
punished: nobody lies down, energy (the glow strength only) dims while unattended and never below the floor; nothing
here decays a mark. A pip is never teleported: a walk the stuck detector cannot finish ends where the pip stands. No
position is ever committed on an impassable cell (water, trunks, boulders, the 12-cell edge margin), so a pip is
never in the river except at the Ford.

Speeds (cells/s; 1 cell = 4 screen px at 1x): errands 4-6 x tempo, `go` 8, a vote walk max(10, dist / 2 s) capped
at 30 so a far voter still arrives in a few seconds. Marsh and the Ford slow a walk to 0.6x, sand / hill to 0.8x
(terrain.cost). Everything eases in over ~9 frames. Python 3.9, numpy only; nothing here reads time.time().
"""
from __future__ import annotations

import math
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stream.world import HOLD_S, SLEEP_AFTER_S  # noqa: E402
from stream.world import land as LAND  # noqa: E402

MAP_W, MAP_H, EDGE_MARGIN, DEFAULT_MOOT = LAND.MAP_W, LAND.MAP_H, LAND.EDGE_MARGIN, LAND.DEFAULT_MOOT

STATES = ("seed", "hatching", "idle", "walking", "voting", "sitting", "hauling", "hidden")
ON_LAND = ("idle", "walking", "voting", "sitting", "hauling")
HIDDEN_STATES = ("hidden", "burrowed")             # the one lying pose (moderation, not presence); `burrowed` is the cave's name
LEGACY_STATES = {"awake": "idle", "curled": "idle", "asleep": "idle", "burrowed": "hidden"}   # mapped on the way in (tick, load)
_LEGACY_ON_LAND = ("awake", "curled")              # a consumer that still writes the cave's names is on the land until the tick maps it
AWAKE_STATES = ON_LAND                             # legacy export (hollow.py); one release
LETTERS = ("A", "B", "C")
PLATFORM_LETTERS = LETTERS                  # the cave's name for the same three votes (rounds / hollow.py compat)
WANDER_X = (EDGE_MARGIN, MAP_W - EDGE_MARGIN)   # legacy import (hollow.py); the wander range is now the whole passable land

# sprite frames the atlas supplies (docs/ART.md 7); the tuft frames are the scene's prop, not a creature frame
FRAMES = ("idle0", "idle1", "blink", "look_l", "look_r", "walk0", "walk1", "walk2", "walk3", "hop0", "hop1",
          "wave0", "wave1", "point", "sit", "sleep", "carry_berry", "carry_stone", "carry_tool", "speak0", "speak1",
          "joy", "love")
TUFT_FRAMES = ("tuft0", "tuft1", "tuft2")   # drifting, settled, splitting (1 Hz, OPENWORLD 3.1)

SPEED_MIN, SPEED_MAX = 5.0, 10.0            # cells/s default for a plain walk_to (a verb's walk; the old wander range)
ERRAND_SPEED = (4.0, 6.0)                   # cells/s for the land's errands (x tempo), slower than `go` (AGES 1.3)
ERRANDS = ("home", "moot", "water", "stroll")
ERRAND_WEIGHTS = {"home": (25.0, 55.0), "moot": (20.0, 10.0), "water": (15.0, 5.0), "stroll": (15.0, 15.0)}   # day / night
ERRAND_DWELL = {"home": (30.0, 90.0), "moot": (10.0, 30.0), "water": (15.0, 40.0), "stroll": (1.0, 3.0)}      # s, x tempo
SIT_DWELL = (20.0, 90.0)                    # s a sit from an errand is sticky (x tempo)
TEMPO = (0.75, 1.3)                         # per-name tempo scaling pause length and errand speed
MOOT_RING = (10.0, 24.0)                    # an errand to the Moot ends on this ring around the green's centre (never the centre)
WATER_MAX_CELLS = 160                       # the water errand looks this far for a bank
GO_SPEED = 8.0                              # cells/s for `go` (OPENWORLD 3.1)
VOTE_WALK_S = 2.0                           # a vote walk aims to arrive in ~2 s ...
VOTE_SPEED_CAP = 30.0                       # ... but never faster than this (a far voter takes a few seconds, no teleport)
EASE_FRAMES = 9
COST_MULT = {0: 0.0, 1: 1.0, 2: 0.8, 3: 0.6}   # terrain.cost -> speed multiplier (marsh / ford 0.6, sand / hill 0.8)
WAYPOINT_R = 0.9                            # cells: a route waypoint counts as reached (corners around obstacles stay tight)
ARRIVE_R = 0.6                              # cells: the final target counts as reached
LOS_MAX = 48.0                              # a straight leg up to this long skips the BFS when the line is clear
LOS_RECHECK_S = 0.5                         # string-pull the route this often while walking
LOCAL_PAD = 10                              # cells of padding around a blocked leg for the cell-level wavefront BFS
LOCAL_MAX_ITER = 200                        # wavefront steps (= path cells) before a leg counts as unreachable
LOCAL_BOX_MAX = 120                         # the fine search never covers more than this many cells a side
STUCK_S = 3.0                               # no progress toward the leg for this long -> stuck (reroute once, then give up)
STUCK_PROGRESS = 0.5                        # cells of progress that reset the stuck timer
STUCK_GIVE_UP = 2                           # the second stuck on one walk ends it where the pip stands
MOOT_GRAVITY = 0.30                         # 30 % of strolls head toward the Moot (4.4)
IDLE_RADIUS = 200.0                         # an errand never targets farther than this from the Moot
WANDER_STEP = 40.0                          # cells: a stroll is +/- this
FACE_WIND_P = 0.2                           # an idle pause turns to face the wind this often

BLINK_MIN, BLINK_MAX = 4.0, 7.0
BLINK_LEN = 0.15
LOOK_CELLS = 50.0                           # settlers this close look toward a speaker (ART.md: ~200 px; a look is a reaction)
LOOK_S = 2.5
SPEAK_S = 8.0                # a bubble is the only place a message is readable now the chat log is gone (journal 034: was 6)
MOUTH_S = 1.0
HOP_TICKS = (3, 6, 2)                       # hop0 x3, hop1 x6 on a parabola, hop0 x2 (ART.md 7)
HOP_S = sum(HOP_TICKS) / 30.0
HOP_LIFT = 0.27                             # of the standing height; the scene scales it by the tier's px height
CURL_FLOOR = 0.2                            # energy (the glow strength) never dims below this; there is no curl state any more
DECAY_PER_MIN = 0.01
ATTENTION_S = 60.0
EMOTE_S = 2.0
LOVE_S = 1.0
JOY_S = 1.0
TUFT_DRIFT_S = 2.0                          # the tuft crosses the frame for 2 s, settles, then splits until the hold clears
TUFT_DRIFT_CELLS = 150.0                    # from just past the upwind edge of a 1x window to the landing spot
TUFT_RING = 30                              # landing spot: hashed inside this ring around the green's centre (3.1)
SHEET_GRACE_S = 4.0                         # a hatch waits this long at most for the settler's sheet (never blocks a frame)
SEED_TIMEOUT_S = HOLD_S + 4.0
CREDITS_GAP_S = 1.5
MUTTER_FIRST = (20.0, 35.0)
MUTTER_GAP = (45.0, 90.0)
CARRY_S = 2.4                               # a berry is carried this long, then eaten with a 3-frame flash
FLASH_S = 3.0 / 30.0
GO_DIR_CELLS = 60.0                         # `go north` walks up to this far
STAND_ROW = 3                               # standing slots at a waystone: 3 per row, rows 2 cells further from the stone
STAND_DX, STAND_DY = 3.0, 2.0
STAND_Y0 = 9.0                              # first standing row this far south of the stone (36 px at 1x): the letter + count stack
                                            # above the stone (WAYSTONE_LETTER_DY 128 -> count bottom at cy - 48) clears a tier-3
                                            # head (drawn 86 px tall at 1.2x: top at cy + 36 - 79 = cy - 43). QA night frame 599
                                            # had the '2' over a face at +3 cells.
WAYSTONE_OFFSETS = ((-12.0, -4.0), (0.0, -9.0), (12.0, -4.0))   # A, B, C around the Moot green's centre

DIRECTIONS: Dict[str, Tuple[float, float]] = {
    "north": (0.0, -1.0), "south": (0.0, 1.0), "east": (1.0, 0.0), "west": (-1.0, 0.0),
    "northeast": (0.7071, -0.7071), "northwest": (-0.7071, -0.7071), "southeast": (0.7071, 0.7071), "southwest": (-0.7071, 0.7071),
    "n": (0.0, -1.0), "s": (0.0, 1.0), "e": (1.0, 0.0), "w": (-1.0, 0.0),
    "ne": (0.7071, -0.7071), "nw": (-0.7071, -0.7071), "se": (0.7071, 0.7071), "sw": (-0.7071, 0.7071),
    "up": (0.0, -1.0), "down": (0.0, 1.0), "left": (-1.0, 0.0), "right": (1.0, 0.0),
}
PLACE_WORDS = ("moot", "steading", "ford", "river", "shore", "fell", "wood", "marsh", "orchard")
PLACE_ALIASES = {"green": "moot", "village": "steading", "camp": "steading", "sea": "shore", "beach": "shore", "hill": "fell",
                 "hills": "fell", "forest": "wood", "woods": "wood", "trees": "wood", "reeds": "marsh", "reed": "marsh",
                 "swamp": "marsh", "orchards": "orchard", "water": "river", "bank": "river"}
GO_HELP = "go where? north · south · east · west · river · ford · moot · fell · wood · shore · marsh · orchard · home · @name"

Vec = Tuple[float, float]


# ---------------------------------------------------------------------------- pure helpers
def name_hash(key: str, salt: str = "") -> int:
    return LAND.name_hash(key, salt)


def hashed_x(key: str, lo: int = WANDER_X[0], hi: int = WANDER_X[1]) -> float:
    """Legacy (hollow.py): a deterministic x from the name. The land uses `landing_spot` instead."""
    h = name_hash(key, ":x")
    return float(lo + h % max(1, hi - lo))


def quantise_facing(dx: float, dy: float) -> Tuple[int, int]:
    """A motion vector -> one of 8 unit directions in {-1, 0, 1}^2 (never (0, 0) unless the input is zero)."""
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return (0, 0)
    a = math.atan2(dy, dx)
    o = int(round(a / (math.pi / 4.0))) % 8
    return ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))[o]


def waystone_positions(moot: Vec, terrain=None) -> List[Tuple[int, int]]:
    """A, B, C standing stones on the Moot green, in a shallow arc north of its centre (the scene draws them; rounds
    count the pips standing in their slots)."""
    mx, my = float(moot[0]), float(moot[1])
    out = []
    for ox, oy in WAYSTONE_OFFSETS:
        x, y = int(round(mx + ox)), int(round(my + oy))
        if terrain is not None:
            x, y = terrain.nearest_passable(x, y, 12)
        out.append((x, y))
    return out


def stand_slot(stone: Vec, i: int) -> Vec:
    """The i-th standing slot south of a waystone: 3 per row (x = stone - 3 + 3 col), the first row STAND_Y0 cells
    south, rows 2 cells further back, so two real people never share a cell (the cave's slot rule in 2D)."""
    col, row = i % STAND_ROW, i // STAND_ROW
    return (float(stone[0]) - STAND_DX + STAND_DX * col, float(stone[1]) + STAND_Y0 + STAND_DY * row)


def landing_spot(key: str, moot: Vec, terrain=None, ring: int = TUFT_RING) -> Vec:
    """Where a newcomer's tuft lands: an (x, y) hashed from the username inside `ring` cells of the green's centre,
    nudged to the nearest passable dry cell (3.1). Deterministic per name."""
    h = name_hash(key, ":land")
    ang = (h % 3600) / 3600.0 * 2.0 * math.pi
    rad = 4.0 + ((h >> 16) % 1000) / 1000.0 * (ring - 4.0)
    x, y = float(moot[0]) + rad * math.cos(ang), float(moot[1]) + rad * math.sin(ang)
    x, y = LAND.clamp_cell(x, y)
    if terrain is not None:
        xi, yi = terrain.nearest_passable(int(round(x)), int(round(y)), 24)
        return (float(xi), float(yi))
    return (float(int(round(x))), float(int(round(y))))


# ---------------------------------------------------------------------------- the land the pips walk (terrain or flat)
class _Ground(object):
    """Thin wrapper so Behaviour runs with terrain.py's Terrain or, in a harness, with a flat passable land."""

    def __init__(self, terrain=None, moot: Optional[Vec] = None):
        self.T = terrain
        if terrain is not None:
            self.passable = terrain.passable
            self.cost = terrain.cost
            self.water = getattr(terrain, "water", None)
            self.w, self.h = int(terrain.w), int(terrain.h)
            site = getattr(terrain, "site", None)
            self.moot: Vec = tuple(moot) if moot else ((float(site[0]), float(site[1])) if site else (float(DEFAULT_MOOT[0]), float(DEFAULT_MOOT[1])))
            self.places = getattr(terrain, "places", {}) or {}
        else:
            self.w, self.h = MAP_W, MAP_H
            p = np.zeros((MAP_H, MAP_W), bool)
            p[EDGE_MARGIN:MAP_H - EDGE_MARGIN, EDGE_MARGIN:MAP_W - EDGE_MARGIN] = True
            self.passable = p
            self.cost = p.astype(np.uint8)
            self.water = None
            self.moot = tuple(moot) if moot else (float(DEFAULT_MOOT[0]), float(DEFAULT_MOOT[1]))
            self.places = {}

    def ok(self, x: float, y: float) -> bool:
        xi, yi = int(math.floor(x)), int(math.floor(y))
        return 0 <= xi < self.w and 0 <= yi < self.h and bool(self.passable[yi, xi])

    def nearest(self, x: float, y: float, r: int = 24) -> Vec:
        if self.T is not None:
            xi, yi = self.T.nearest_passable(int(round(x)), int(round(y)), r)
            return (float(xi), float(yi))
        cx, cy = LAND.clamp_cell(x, y)
        return (float(int(round(cx))), float(int(round(cy))))

    def speed_mult(self, x: float, y: float) -> float:
        xi, yi = int(x), int(y)
        if 0 <= xi < self.w and 0 <= yi < self.h:
            return COST_MULT.get(int(self.cost[yi, xi]), 1.0) or 1.0
        return 1.0

    def clear_line(self, a: Vec, b: Vec) -> bool:
        """Every cell on the straight line a -> b is passable (sampled once per cell)."""
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        n = int(math.ceil(d)) * 2 + 1
        if n <= 1:
            return self.ok(*b)
        xs = np.floor(np.linspace(a[0], b[0], n)).astype(np.int32)
        ys = np.floor(np.linspace(a[1], b[1], n)).astype(np.int32)
        if xs.min() < 0 or ys.min() < 0 or xs.max() >= self.w or ys.max() >= self.h:
            return False
        return bool(self.passable[ys, xs].all())

    def route(self, a: Vec, b: Vec) -> List[Vec]:
        if self.T is None:
            return [(float(b[0]), float(b[1]))]
        r = self.T.route((a[0], a[1]), (b[0], b[1]))
        return [(float(x), float(y)) for (x, y) in r]

    def local_path(self, a: Vec, b: Vec, pad: int = LOCAL_PAD) -> Tuple[List[Vec], bool]:
        """Cell-level 4-connected wavefront BFS inside the box around a -> b (the coarse grid says a block is open
        when half of it is, so a river or the Wood's edge can cut a leg the slide rule cannot skirt). Returns
        (waypoints, reached): the string-pulled path to b, or, when b is unreachable inside the box, the path to the
        reachable cell nearest b (a walker stops on the bank, never in the water). ([], False) = cannot move at all."""
        ax, ay, bx, by = int(math.floor(a[0])), int(math.floor(a[1])), int(math.floor(b[0])), int(math.floor(b[1]))
        x0, x1 = max(0, min(ax, bx) - pad), min(self.w, max(ax, bx) + pad + 1)
        y0, y1 = max(0, min(ay, by) - pad), min(self.h, max(ay, by) + pad + 1)
        if x1 - x0 > LOCAL_BOX_MAX or y1 - y0 > LOCAL_BOX_MAX:
            return [], False
        P = self.passable[y0:y1, x0:x1]
        sy, sx, gy, gx = ay - y0, ax - x0, by - y0, bx - x0
        if not P[sy, sx]:
            return [], False
        dist = np.full(P.shape, -1, np.int16)
        dist[sy, sx] = 0
        front = np.zeros(P.shape, bool)
        front[sy, sx] = True
        reached = bool(P[gy, gx]) and (sy, sx) == (gy, gx)
        for k in range(1, LOCAL_MAX_ITER + 1):
            new = np.zeros(P.shape, bool)
            new[1:, :] |= front[:-1, :]
            new[:-1, :] |= front[1:, :]
            new[:, 1:] |= front[:, :-1]
            new[:, :-1] |= front[:, 1:]
            new &= P
            new &= dist < 0
            if not new.any():
                break
            dist[new] = k
            front = new
            if dist[gy, gx] >= 0:
                reached = True
                break
        if not reached:
            ys, xs = np.nonzero(dist >= 0)
            if len(xs) == 0:
                return [], False
            dd = (xs - gx) ** 2 + (ys - gy) ** 2
            k = int(np.argmin(dd))
            gy, gx = int(ys[k]), int(xs[k])
            if (gy, gx) == (sy, sx):
                return [], False
        # backtrack from the goal down the distance field
        cells = [(gx, gy)]
        cy, cx = gy, gx
        guard = 0
        while dist[cy, cx] > 0 and guard < LOCAL_MAX_ITER + 2:
            guard += 1
            d = int(dist[cy, cx])
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < P.shape[0] and 0 <= nx < P.shape[1] and dist[ny, nx] == d - 1:
                    cy, cx = ny, nx
                    break
            cells.append((cx, cy))
        cells.reverse()                                            # from the pip to the goal, in box coordinates
        pts = [(float(x + x0) + 0.5, float(y + y0) + 0.5) for (x, y) in cells]   # cell centres
        pts[0] = (float(a[0]), float(a[1]))                                        # ... from where the pip really stands
        # string-pull: keep only the corners the straight lines need
        out: List[Vec] = []
        i = 0
        n = len(pts)
        while i < n - 1:
            j = i + 1
            step = 3
            while j + step < n and self.clear_line(pts[i], pts[j + step]):
                j += step
            while j + 1 < n and self.clear_line(pts[i], pts[j + 1]):
                j += 1
            out.append(pts[j])
            i = j
        if not out:
            out = [pts[-1]]
        return out, reached


# ---------------------------------------------------------------------------- one creature
class Entity(object):
    """One pip (or a nameless tuft). Positions are map cells (floats); (x, y) is the FEET cell."""
    __slots__ = ("key", "origin", "state", "display_name", "tier", "energy", "salt", "x", "y", "fx", "fy", "side",
                 "vx", "vy", "speed", "speed_max", "target", "route", "then", "platform", "slot", "camp", "burrow",
                 "seed_t", "seed_from", "seed_to", "seed_landed", "seed_y", "hatch_t", "cleared", "next_blink_t",
                 "blink_until", "hop_t", "speak_until", "mouth_until", "text", "pause_until", "last_active_t",
                 "last_attention_t", "spoke_t", "sleep_t", "twitch_t", "twitch_until", "emote", "emote_until",
                 "love_until", "joy_until", "look_key", "look_until", "minutes_tonight", "first_ever", "wake_t",
                 "bob_phase", "born_t", "credits_done", "learned_from", "carry", "carry_until", "flash_until",
                 "next_mutter_t", "progress_t", "progress_best", "stuck_n", "stuck_total", "last_cell", "los_t",
                 "cells_walked", "walk_speed", "short", "leg_t", "present", "present_s", "tempo", "errand", "sit_until")

    def __init__(self, key: str, origin: str, t: float):
        self.key = key
        self.origin = origin
        self.state = "seed"
        self.display_name: Optional[str] = None
        self.tier = 0
        self.energy = 0.6
        self.salt = 0
        self.x = float(DEFAULT_MOOT[0])
        self.y = float(DEFAULT_MOOT[1])
        self.fx, self.fy = 1, 0                 # 8-direction facing (the camera's lead room, the sprite's look)
        self.side = 1                           # last non-zero horizontal facing: the sprite mirror
        self.vx = self.vy = 0.0
        self.speed = 0.0
        self.speed_max = SPEED_MIN
        self.target: Optional[Vec] = None       # the walk's final target (cells)
        self.route: List[Vec] = []              # waypoints still ahead, ending at target
        self.then: Optional[str] = None         # what to do on arrival: idle / vote / errand:<name> / sit / credits / pickup:<k> / place:<k>
        self.platform: Optional[str] = None     # waystone letter while voting or walking to vote
        self.slot: Optional[int] = None
        self.camp: Optional[Tuple[int, int]] = None
        self.burrow = None                      # legacy attribute (hollow.py); always None on the land
        self.seed_t = t
        self.seed_from: Vec = (self.x, self.y)
        self.seed_to: Vec = (self.x, self.y)
        self.seed_landed = False
        self.seed_y = 0.0                       # legacy attribute (hollow.py)
        self.hatch_t: Optional[float] = None
        self.cleared = False
        self.next_blink_t = t + BLINK_MIN
        self.blink_until = 0.0
        self.hop_t = -1e9
        self.speak_until = 0.0
        self.mouth_until = 0.0
        self.text: Optional[str] = None
        self.pause_until = t
        self.last_active_t = t
        self.last_attention_t = t
        self.spoke_t: Optional[float] = None
        self.sleep_t: Optional[float] = None    # inert legacy attributes (the cave scene still writes them); nothing reads them
        self.twitch_t = 0.0
        self.twitch_until = 0.0
        self.emote: Optional[str] = None
        self.emote_until = 0.0
        self.love_until = 0.0
        self.joy_until = 0.0
        self.look_key: Optional[str] = None
        self.look_until = 0.0
        self.minutes_tonight = 0.0
        self.first_ever = False
        self.wake_t: Optional[float] = None
        self.bob_phase = (name_hash(key) % 60) / 60.0
        self.born_t = t
        self.credits_done = False
        self.learned_from: Optional[str] = None
        self.carry: Optional[str] = None        # None | "berry" | "stone" | "tool"
        self.carry_until = float("inf")
        self.flash_until = 0.0
        self.next_mutter_t = 1e18
        self.progress_t = t
        self.progress_best = float("inf")
        self.stuck_n = 0                        # stuck events on the CURRENT walk
        self.stuck_total = 0                    # lifetime (QA: never fires twice on one pip in the 5-min test)
        self.last_cell: Optional[Tuple[int, int]] = None
        self.los_t = -1e9
        self.cells_walked = 0
        self.walk_speed = 0.0
        self.short = False                      # the walk was shortened to the nearest reachable cell
        self.leg_t = -1e9                       # the frame the current leg was last refined at cell level
        self.present = False                    # the here / away flag, refreshed every tick from last_active_t (AGES 1.1)
        self.present_s = SLEEP_AFTER_S          # the window (the Behaviour's present_s, copied each tick)
        self.tempo = TEMPO[0] + (TEMPO[1] - TEMPO[0]) * ((name_hash(key, ":tempo") % 1000) / 1000.0)   # 0.75-1.3 per name
        self.errand: Optional[str] = None       # the last errand picked (never the same twice running)
        self.sit_until = 0.0

    # -- read-only helpers ----------------------------------------------------------
    def is_on_land(self) -> bool:
        """The body is on the land (idle / walking / voting / sitting / hauling): drawn standing, moved by the land, a camera
        dead-zone point. Not a seed, not hidden."""
        return self.state in ON_LAND or self.state in _LEGACY_ON_LAND

    def is_awake(self) -> bool:
        """Legacy name for is_on_land() (one release): NOT presence. Use is_present() for anything the person could claim."""
        return self.is_on_land()

    def is_present(self, t: Optional[float] = None) -> bool:
        """`here` (AGES 1.1): the owner's record landed within present_s of now (t - last_active_t <= present_s) and the body is
        on the land. Without `t` the flag the last tick computed is returned (message() flips it the same frame). Every verb,
        bubble, mutter, hop, vote, wear, fire and the camera's FOLLOW list are gated on this; nothing else about a person."""
        if not self.is_on_land():
            return False
        if t is None:
            return self.present
        return (float(t) - self.last_active_t) <= self.present_s

    @property
    def facing(self) -> Tuple[int, int]:
        return (self.fx, self.fy)

    @facing.setter
    def facing(self, v) -> None:
        """Accepts (fx, fy) or the cave's 1 / -1 horizontal facing."""
        if isinstance(v, (int, float)):
            self.fx, self.fy = (1 if v >= 0 else -1), 0
        else:
            self.fx, self.fy = int(v[0]), int(v[1])
        if self.fx:
            self.side = self.fx

    @property
    def waystone(self) -> Optional[str]:
        return self.platform

    def pos(self) -> Vec:
        return (self.x, self.y)

    def cell(self) -> Tuple[int, int]:
        return (int(math.floor(self.x)), int(math.floor(self.y)))

    def walking(self) -> bool:
        return self.state == "walking" and math.hypot(self.vx, self.vy) > 0.5

    def hop_phase(self, t: float) -> float:
        ph = (t - self.hop_t) / HOP_S
        return ph if 0.0 <= ph <= 1.0 else -1.0

    def hop_lift(self, t: float) -> float:
        """0..1 of HOP_LIFT during the airborne ticks (the scene lifts the body; the shadow stays on the ground)."""
        ph = self.hop_phase(t)
        if ph < 0:
            return 0.0
        a = HOP_TICKS[0] / float(sum(HOP_TICKS))
        b = (HOP_TICKS[0] + HOP_TICKS[1]) / float(sum(HOP_TICKS))
        if a <= ph <= b:
            u = (ph - a) / (b - a)
            return HOP_LIFT * math.sin(math.pi * u)
        return 0.0

    def hop_offset(self, t: float) -> float:
        """Legacy: the lift in cells (negative = up), for callers that add it to y."""
        return -self.hop_lift(t) * 4.0

    def frame_name(self, t: float) -> str:
        """Which atlas frame to draw now (docs/ART.md 7); tufts return TUFT_FRAMES for the scene's prop."""
        st = self.state
        if st in ("seed", "hatching"):
            if not self.seed_landed:
                return "tuft0"
            age = t - self.seed_t
            return "tuft1" if age < HOLD_S - 0.5 else "tuft2"
        if st in HIDDEN_STATES:
            return "sleep"                                              # the ONE lying pose: a mod hid the user (moderation, not presence)
        if st == "sitting":
            return "sit"
        ph = self.hop_phase(t)
        if ph >= 0:
            a = HOP_TICKS[0] / float(sum(HOP_TICKS))
            b = (HOP_TICKS[0] + HOP_TICKS[1]) / float(sum(HOP_TICKS))
            return "hop1" if a <= ph <= b else "hop0"
        if t < self.love_until:
            return "love"
        if t < self.joy_until:
            return "joy"
        if self.emote and t < self.emote_until:
            if self.emote == "sit":
                return "sit"
            if self.emote == "dance":
                return ("joy", "wave1", "hop1", "wave0")[int((t * 4.0) % 4)]
            return "%s%d" % (self.emote, int((t * 4.0) % 2))          # wave0 / wave1 every 0.25 s
        if self.carry:
            return "carry_%s" % self.carry
        if self.walking():
            return "walk%d" % int((t * 8.0) % 4)                        # 8 fps contact / pass / contact / pass
        if t < self.blink_until:
            return "blink"
        if t < self.mouth_until:
            return "speak%d" % int((t * 5.0) % 2)                       # every 6 ticks
        if self.look_key and t < self.look_until:
            return "look_l" if self.side < 0 else "look_r"
        return "idle%d" % int(((t + self.bob_phase * 1.6) / 0.8) % 2)   # breath every ~0.8 s

    def draw_y(self, t: float) -> float:
        return self.y

    def to_dict(self, t: float) -> Dict[str, Any]:
        return {"key": self.key, "origin": self.origin, "state": self.state, "display_name": self.display_name,
                "tier": self.tier, "energy": round(self.energy, 3), "salt": self.salt, "x": self.x, "y": self.y,
                "lift": round(self.hop_lift(t), 3), "facing": [self.fx, self.fy], "side": self.side,
                "frame": self.frame_name(t), "platform": self.platform, "waystone": self.platform, "burrow": None,
                "camp": list(self.camp) if self.camp else None,
                "target": [self.target[0], self.target[1]] if self.target else None,
                "walking": self.walking(), "then": self.then,
                "text": self.text if t < self.speak_until else None, "speaking": t < self.speak_until,
                "spoke_t": self.spoke_t, "learned_from": self.learned_from, "first_ever": self.first_ever,
                "minutes_tonight": round(self.minutes_tonight, 2), "present": self.is_present(),
                "on_land": self.is_on_land(), "awake": self.is_on_land(), "errand": self.errand,
                "carry": self.carry, "carrying": self.carry is not None, "flash": t < self.flash_until,
                "hidden": self.state in HIDDEN_STATES, "stuck": self.stuck_total}


# ---------------------------------------------------------------------------- the behaviour
class Behaviour(object):
    def __init__(self, seed: int = 41370704, sleep_after_s: float = SLEEP_AFTER_S, hold_s: float = HOLD_S,
                 terrain=None, land=None, moot: Optional[Vec] = None,
                 wind: Union[None, Vec, Callable[[], Vec]] = None,
                 sheet_ready: Optional[Callable[[str], bool]] = None, waystones: Optional[Sequence[Vec]] = None,
                 present_s: Optional[float] = None):
        self.rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
        self.present_s = float(present_s if present_s is not None else sleep_after_s)   # the here window (AGES 1.1)
        self.hold_s = float(hold_s)
        self.ground = _Ground(terrain, moot)
        self.land = land
        self.wind = wind if wind is not None else (1.0, 0.25)
        self.sheet_ready = sheet_ready
        self.waystones: List[Vec] = [(float(x), float(y)) for (x, y) in (waystones or waystone_positions(self.ground.moot, terrain))]
        self.entities: Dict[str, Entity] = {}
        self.newest_speaker: Optional[str] = None
        self.newest_speaker_t = -1e9
        self.first_light_done = False
        self.first_light_pending: Optional[str] = None   # the session's FIRST message came from a stranger's tuft: first
                                                         # breath waits for that hatch (a sleeper waking meanwhile does not take it)
        self.credits_active = False
        self._credits_queue: List[str] = []
        self._credits_next_t = 0.0
        self._last_t: Optional[float] = None
        self.events: List[Dict[str, Any]] = []
        self.colony_rule = "free"          # free / huddle honoured (rounds may set follow / scatter: ignored, one release)
        self.session_id: Optional[str] = None   # set by the scene (informational: camps are the scene's / the land's)
        self.night: Union[float, Callable[[], float]] = 0.0   # nature.night_amount for the errand weights (the scene sets it)
        self.stats_routes = 0
        self.stats_stuck = 0
        self.stats_local = 0

    # ------------------------------------------------------------------ helpers
    @property
    def sleep_after_s(self) -> float:
        """Legacy name for present_s (one release): the scene's test hook and the cave still set it."""
        return self.present_s

    @sleep_after_s.setter
    def sleep_after_s(self, v: float) -> None:
        self.present_s = float(v)

    def _night(self) -> float:
        try:
            n = float(self.night() if callable(self.night) else self.night)
        except Exception:
            n = 0.0
        return 0.0 if n < 0.0 else (1.0 if n > 1.0 else n)

    @property
    def moot(self) -> Vec:
        return self.ground.moot

    @property
    def terrain(self):
        return self.ground.T

    def set_terrain(self, terrain, moot: Optional[Vec] = None) -> None:
        self.ground = _Ground(terrain, moot or (self.ground.moot if terrain is None else None))
        self.waystones = [(float(x), float(y)) for (x, y) in waystone_positions(self.ground.moot, terrain)]

    def set_land(self, land) -> None:
        self.land = land

    def wind_vector(self) -> Vec:
        w = self.wind() if callable(self.wind) else self.wind
        try:
            vx, vy = float(w[0]), float(w[1])
        except Exception:
            vx, vy = 1.0, 0.25
        d = math.hypot(vx, vy)
        return (vx / d, vy / d) if d > 1e-6 else (1.0, 0.0)

    def _ev(self, typ: str, **kw) -> Dict[str, Any]:
        d = {"type": typ}
        d.update(kw)
        self.events.append(d)
        return d

    def _u(self, a: float, b: float) -> float:
        return float(a + (b - a) * self.rng.random())

    def get(self, key: str) -> Optional[Entity]:
        return self.entities.get((key or "").lower())

    def awake(self) -> List[Entity]:
        """Every settler ON THE LAND (here or away): what is drawn standing and moved by the land. Not a presence count."""
        return [e for e in self.entities.values() if e.is_on_land()]

    def on_land(self) -> List[Entity]:
        return self.awake()

    def present(self) -> List[Entity]:
        """The `here` settlers (AGES 1.1): owner's record within present_s. A len() over real entities, never a sample."""
        return [e for e in self.entities.values() if e.is_present()]

    def present_count(self) -> int:
        return sum(1 for e in self.entities.values() if e.is_present())

    def awake_count(self) -> int:
        """Legacy name for present_count() (one release; rounds / compositor / audio / panels still call it)."""
        return self.present_count()

    def asleep_count(self) -> int:
        """Nobody sleeps (AGES 1.1): always 0. Deleted once rounds.py / panels stop calling it."""
        return 0

    def hatched(self) -> List[Entity]:
        return [e for e in self.entities.values() if e.state not in ("seed", "hatching")]

    def seeds(self) -> List[Entity]:
        return [e for e in self.entities.values() if e.state in ("seed", "hatching")]

    def platform_counts(self) -> Dict[str, List[str]]:
        """Who is STANDING at each waystone (state `voting`) AND here: the embodied tally, a len() per letter. A vote is
        the person's (AGES 1.1: voting requires here); an away body at a stone is stepped off by the next tick and is
        never counted."""
        out: Dict[str, List[str]] = {k: [] for k in LETTERS}
        for e in self.entities.values():
            if e.state == "voting" and e.platform in out and e.is_present():
                out[e.platform].append(e.key)
        return out

    def free_burrow(self, preferred: Optional[int] = None) -> int:
        """Legacy (hollow.py): there are no burrows on the land."""
        return 0

    def camera_inputs(self, t: float, round_remaining: Optional[float] = None) -> Dict[str, Any]:
        """The awake / seeds / moot arguments for Camera.update(), straight from the entities (no invention). The `awake`
        list (the key is the camera's name) holds the HERE settlers only (AGES 1.4: FOLLOW weights apply to here settlers;
        away bodies weigh 0 and the camera surveys at 0 present until ROAM, row 2)."""
        awake = [{"key": e.key, "x": e.x, "y": e.y, "fx": e.fx, "fy": e.fy, "walking": e.walking(), "spoke_t": e.spoke_t}
                 for e in self.entities.values() if e.is_present(t)]
        # a tuft is framed by where it will LAND (3.1: the camera eases toward the landing spot on the green), never by
        # its start 150 cells upwind, which would drag the frame off the people for the whole hold
        seeds = [tuple(e.seed_to) if not e.seed_landed and e.seed_to is not None else (e.x, e.y)
                 for e in self.entities.values() if e.state in ("seed", "hatching")]
        pc = self.platform_counts()
        voters = [k for ks in pc.values() for k in ks]
        walking_to = any(e.state == "walking" and e.then == "vote" for e in self.entities.values())
        moot = {"stones": list(self.waystones), "voters": voters, "walking_to_stone": walking_to, "round_remaining": round_remaining}
        return {"awake": awake, "seeds": seeds, "moot": moot}

    # ------------------------------------------------------------------ chat-driven entry points
    def seed_drop(self, key: str, t: float, x: Optional[float] = None, y: Optional[float] = None, origin: str = "chat") -> Entity:
        """A record from a chatter with no pip: a nameless tuft drifts in from the upwind edge along the wind vector
        toward its hashed landing spot on the Moot green (3.1). Nothing about the name is stored for drawing; `key` is
        the lowercase username used only as the dict key (and later for the art genome)."""
        key = (key or "").lower()
        e = self.entities.get(key)
        if e is not None:
            return e
        e = Entity(key, origin, t)
        to = landing_spot(key, self.ground.moot, self.ground.T) if x is None or y is None else self.ground.nearest(float(x), float(y))
        wx, wy = self.wind_vector()
        frm = (to[0] - wx * TUFT_DRIFT_CELLS, to[1] - wy * TUFT_DRIFT_CELLS)
        e.seed_from, e.seed_to = frm, to
        e.x, e.y = frm
        e.fx, e.fy = quantise_facing(wx, wy)
        if e.fx:
            e.side = e.fx
        e.state = "seed"
        e.seed_t = t
        self.entities[key] = e
        if not self.first_light_done and self.first_light_pending is None and self.present_count() == 0:
            self.first_light_pending = key           # the session's first MESSAGE is first breath, credited at hatch
        self._ev("seed", key=key, x=to[0], y=to[1], from_x=frm[0], from_y=frm[1])
        return e

    def hold_cleared(self, key: str, t: float, display_name: str, tier: int = 0, energy: float = 0.6, salt: int = 0,
                     first_ever: bool = True) -> Optional[Entity]:
        """The bridge cleared the hold (blocklist passed or `builder #N` chosen, no mod hide): the tuft may pop. The
        hatch itself lands when the hold has run (>= hold_s after the seed) AND the settler's sheet is ready (or the
        grace has passed), so a fast clear never shortens the nameless period and a slow render never stalls a frame."""
        key = (key or "").lower()
        e = self.entities.get(key)
        if e is None:
            e = self.seed_drop(key, t - self.hold_s)
        e.display_name = display_name
        e.tier = int(tier)
        e.energy = float(energy)
        e.salt = int(salt)
        e.first_ever = bool(first_ever)
        e.cleared = True
        if e.state == "seed":
            e.state = "hatching"
        return e

    def sink(self, key: str, t: float) -> bool:
        """Hidden by a mod inside the hold, or never cleared: the wind takes the tuft. No hatch, no name."""
        key = (key or "").lower()
        e = self.entities.get(key)
        if e is None or e.state not in ("seed", "hatching"):
            return False
        del self.entities[key]
        self._ev("sink", key=key)
        if self.first_light_pending == key:
            self.first_light_pending = None          # the tuft never hatched: first breath goes to whoever is here first
            if not self.first_light_done:
                here = sorted(self.present(), key=lambda o: o.last_active_t)
                if here:
                    self.first_light_done = True
                    self._ev("first_light", pip=here[0].key)
        return True

    def place_settler(self, key: str, tier: int, energy: float, salt: int, camp=None, display_name: Optional[str] = None,
                      origin: str = "chat", t: float = 0.0, x: Optional[float] = None, y: Optional[float] = None,
                      last_seen: Optional[float] = None) -> Entity:
        """Boot: a past chatter's settler STANDING on the land (AGES 8: nobody lies down): at the saved (x, y) when that
        cell is passable, else at its camp door, else at its hashed Steading-ring spot. `camp` is the pip row's camp dict
        / (x, y) / None (an int is the cave's burrow slot: ignored). `last_seen` (epoch) is the owner's real last record:
        `last_active_t` starts there, so the settler is here iff that record is inside present_s (the old _restore_awake
        collapses into this call); None = away. The camp itself is the land's record (ws.ensure_camp)."""
        key = (key or "").lower()
        e = self.entities.get(key)
        if e is None:
            e = Entity(key, origin, t)
            self.entities[key] = e
        e.display_name = display_name
        e.tier, e.energy, e.salt = int(tier), float(energy), int(salt)
        e.cleared = True
        cx = cy = None
        if isinstance(camp, dict) and camp.get("x") is not None and camp.get("y") is not None:
            cx, cy = float(camp["x"]), float(camp["y"])
        elif isinstance(camp, (tuple, list)) and len(camp) >= 2:
            cx, cy = float(camp[0]), float(camp[1])
        if cx is not None:
            e.camp = (int(round(cx)), int(round(cy)))
        if x is not None and y is not None and self.ground.ok(float(x), float(y)):
            e.x, e.y = float(x), float(y)                      # where the record last saw it, standing
        elif e.camp is not None:
            e.x, e.y = self.ground.nearest(float(e.camp[0]) + 2.0, float(e.camp[1]) + 3.0)   # the camp door
        elif x is not None and y is not None:
            e.x, e.y = self.ground.nearest(float(x), float(y))
        else:
            taken = [o.camp for o in self.entities.values() if o.camp and o is not e]
            hx, hy = LAND.hashed_camp_spot(key, self.ground.moot, taken, self.ground.passable, self.ground.water)
            e.x, e.y = float(hx), float(hy)
        e.state = "idle"
        e.vx = e.vy = 0.0
        e.speed = 0.0
        e.route, e.target, e.then = [], None, None
        e.platform, e.slot = None, None
        e.last_active_t = float(last_seen) if last_seen is not None else (t - self.present_s - 1.0)
        e.last_attention_t = e.last_active_t
        e.present_s = self.present_s
        e.present = (t - e.last_active_t) <= self.present_s
        e.minutes_tonight = 0.0
        e.pause_until = t + self._u(0.5, 3.0)
        e.next_blink_t = t + self._u(BLINK_MIN, BLINK_MAX)
        e.next_mutter_t = (t + self._u(*MUTTER_FIRST)) if e.present else 1e18
        e.fx, e.fy = 0, 1
        return e

    def place_sleeper(self, *a, **kw) -> Entity:
        """Legacy name for place_settler() (one release; hollow.py). Nobody is placed lying down."""
        return self.place_settler(*a, **kw)

    def set_camp(self, key: str, x: float, y: float) -> bool:
        """The land settled a camp spot (ws.ensure_camp may fall back to the hashed ring spot): remember it. Never moves
        anyone (a camp is a home, not a bed)."""
        e = self.get(key)
        if e is None:
            return False
        e.camp = (int(round(x)), int(round(y)))
        return True

    def message(self, key: str, t: float, seen_t: Optional[float] = None) -> Optional[Entity]:
        """A record from an existing pip's owner landed (pre-hold): the settler is HERE from this frame. A gap longer than
        present_s (or a hidden settler let back) is a `return` (the old wake, renamed: drop the errand, hop, face the
        camera); else a hop + brighten. `seen_t` is the record's own time when the scene ingests an older record (deploy
        history), so presence flips with the same clock the honesty reference reads."""
        e = self.get(key)
        if e is None or e.state in ("seed", "hatching"):
            return e
        gap = t - e.last_active_t
        e.last_active_t = max(e.last_active_t, float(seen_t)) if seen_t is not None else t
        e.last_attention_t = t
        e.energy = min(1.0, e.energy + 0.15)
        e.present_s = self.present_s
        if e.state == "hidden" or gap > self.present_s:
            self._return(e, t, gap)
        else:
            e.hop_t = t
            self._ev("hop", pip=e.key)
        e.present = e.is_on_land() and (t - e.last_active_t) <= self.present_s
        return e

    def _return(self, e: Entity, t: float, away_s: Optional[float]) -> None:
        """away -> here (AGES 1.1): drop the errand in one frame, hop, brighten, face the camera. Nothing moves: the settler
        is wherever the land took it. The `return` event carries the camp and the gap for the plank, the care log and
        the camera's hold."""
        if e.state == "hidden":
            e.state = "idle"
        if e.state == "walking" and (e.then is None or e.then in ("idle", "sit") or str(e.then).startswith("errand:")):
            e.route, e.target, e.then = [], None, None
            e.state = "idle"
        elif e.state == "sitting":
            e.state = "idle"
        e.speed = 0.0
        e.vx = e.vy = 0.0
        e.pause_until = t + self._u(0.6, 1.5)
        e.minutes_tonight = 0.0
        e.credits_done = False
        e.hop_t = t
        e.next_mutter_t = t + self._u(*MUTTER_FIRST)
        e.fx, e.fy = 0, 1                            # faces the camera
        e.present = True
        n_here = self.present_count()
        self._ev("return", pip=e.key, camp=list(e.camp) if e.camp else None, x=e.x, y=e.y,
                 away_s=(int(away_s) if away_s is not None else None), only_light=(n_here == 1))
        if not self.first_light_done and self.first_light_pending is None and n_here == 1:
            # the session's first message came from a RETURNING chatter: that is first breath too
            self.first_light_done = True
            self._ev("first_light", pip=e.key)

    def speak(self, key: str, t: float, text: str, learned_from: Optional[str] = None) -> Optional[Entity]:
        """After the hold: the owner's own words in a bubble for SPEAK_S; settlers within 50 cells look toward it (a look
        is a reaction the land allows an away body, AGES 1.3)."""
        e = self.get(key)
        if e is None or e.state in ("seed", "hatching") or e.state in HIDDEN_STATES:
            return None
        e.text = text
        e.learned_from = learned_from
        e.speak_until = t + SPEAK_S
        e.mouth_until = t + MOUTH_S
        e.last_active_t = t
        e.spoke_t = t
        e.next_mutter_t = t + self._u(*MUTTER_GAP)
        self.newest_speaker, self.newest_speaker_t = e.key, t
        for o in self.entities.values():
            if o is not e and o.is_on_land() and o.state != "walking":
                d = math.hypot(e.x - o.x, e.y - o.y)
                if d <= LOOK_CELLS:
                    o.look_key, o.look_until = e.key, t + LOOK_S
                    self._face(o, e.x - o.x, e.y - o.y)
        self._ev("speak", pip=e.key, text=text, learned_from=learned_from)
        return e

    def hop(self, key: str, t: float) -> None:
        """A hop is the person's (here only, AGES 1.3)."""
        e = self.get(key)
        if e is not None and e.is_present(t):
            e.hop_t = t
            self._ev("hop", pip=e.key)

    def crowd_bounce(self, letter: str, t: float) -> int:
        """The leading waystone's crowd bounces (last 30 s of a round): every pip standing there hops once."""
        n = 0
        for e in self.entities.values():
            if e.state == "voting" and e.platform == (letter or "").upper() and t - e.hop_t > HOP_S:
                e.hop_t = t + n * 0.05
                n += 1
        return n

    def emote(self, key: str, kind: str, t: float) -> bool:
        e = self.get(key)
        if e is None or not e.is_on_land() or kind not in ("wave", "sit", "dance"):
            return False
        e.emote, e.emote_until = kind, t + EMOTE_S
        self._ev("emote", pip=e.key, kind=kind)     # the record that carried the verb already made the person here
        return True

    def care_received(self, key: str, t: float, by: Optional[str] = None) -> bool:
        """feed / pet landed on this settler: a here settler hops with hearts; an away one only looks at the giver (AGES 1.5:
        hearts on the doer only, the care log plays back on return)."""
        e = self.get(key)
        if e is None or not e.is_on_land():
            return False
        e.last_attention_t = t
        e.energy = min(1.0, e.energy + 0.10)
        if by:
            o = self.get(by)
            if o is not None:
                self._face(e, o.x - e.x, o.y - e.y)
        if e.is_present(t):
            e.hop_t = t
            e.love_until = t + HOP_S + LOVE_S
            e.flash_until = t + FLASH_S
        return True

    def carry(self, key: str, t: float, kind: str = "berry", dur: Optional[float] = CARRY_S) -> bool:
        """The pip carries a berry (eaten after `dur` with a 3-frame flash) or a stone / tool (until drop())."""
        e = self.get(key)
        if e is None or not e.is_on_land() or kind not in ("berry", "stone", "tool"):
            return False
        e.carry = kind
        e.carry_until = (t + dur) if (dur is not None and kind == "berry") else float("inf")
        return True

    def drop(self, key: str, t: float) -> Optional[str]:
        e = self.get(key)
        if e is None or e.carry is None:
            return None
        kind, e.carry, e.carry_until = e.carry, None, float("inf")
        if kind == "berry":
            e.flash_until = t + FLASH_S
        return kind

    def hide(self, key: str, t: float, reason: str = "hidden by mod") -> bool:
        """A mod hid the user: the pip lies down in the grass where it stands (no label, no plate), state `hidden`: the ONE
        lying pose, moderation not presence. The event keeps the cave's name `burrowed` for its consumers."""
        e = self.get(key)
        if e is None or e.state in ("seed", "hatching") or e.state in HIDDEN_STATES:
            return False
        if e.state == "voting":
            self._ev("leave_platform", pip=e.key, platform=e.platform)
        e.platform, e.slot = None, None
        e.route, e.target, e.then = [], None, None
        e.vx = e.vy = 0.0
        e.carry = None
        e.text, e.speak_until = None, 0.0
        e.state = "hidden"
        e.present = False
        self._ev("burrowed", pip=e.key, reason=reason)
        return True

    def drip_landed(self, x: float, t: float, y: Optional[float] = None) -> None:
        """Legacy (hollow.py): something landed at (x, y); idle pips nearby turn to look."""
        for e in self.entities.values():
            if not e.is_awake() or e.state == "walking":
                continue
            dx, dy = x - e.x, (y - e.y) if y is not None else 0.0
            if 1.0 < math.hypot(dx, dy) <= 30.0:
                self._face(e, dx, dy)

    # ------------------------------------------------------------------ walking
    def _face(self, e: Entity, dx: float, dy: float) -> None:
        fx, fy = quantise_facing(dx, dy)
        if fx or fy:
            e.fx, e.fy = fx, fy
            if fx:
                e.side = fx

    def _plan(self, e: Entity, target: Vec, t: float, fresh: bool = False) -> bool:
        """Set e.route toward `target` (already passable): a clear straight line up to LOS_MAX skips the BFS; else the
        coarse route, string-pulled so the pip does not detour to block centres. Returns False when unreachable."""
        g = self.ground
        d = math.hypot(target[0] - e.x, target[1] - e.y)
        if not fresh and d <= LOS_MAX and g.clear_line(e.pos(), target):
            e.route = [target]
            return True
        self.stats_routes += 1
        r = g.route(e.pos(), target)
        if not r:
            return False
        if not r or (abs(r[-1][0] - target[0]) > 0.5 or abs(r[-1][1] - target[1]) > 0.5):
            r.append(target)
        e.route = r
        return self._string_pull(e, t)

    def _string_pull(self, e: Entity, t: float) -> bool:
        """Drop leading waypoints the pip can already see past (a clear straight line to the next one), then make
        sure the first leg is walkable at cell level (a blocked leg is refined by the local wavefront BFS)."""
        while len(e.route) > 1:
            nxt = e.route[1]
            if math.hypot(nxt[0] - e.x, nxt[1] - e.y) <= LOS_MAX and self.ground.clear_line(e.pos(), nxt):
                e.route.pop(0)
            else:
                break
        e.progress_best = float("inf")
        return self._ensure_leg(e, t)

    def _ensure_leg(self, e: Entity, t: float, pad: int = LOCAL_PAD) -> bool:
        """If the straight line to the next waypoint crosses water / a trunk, splice in the cell-level path. When the
        waypoint is unreachable the walk is shortened to the nearest reachable cell (`short` on the arrive event).
        Returns False when the pip cannot move from where it stands."""
        if not e.route:
            return False
        leg = e.route[0]
        if self.ground.clear_line(e.pos(), leg):
            return True
        if e.leg_t == t:
            return True                                            # refined this frame already: walk it, do not loop
        e.leg_t = t
        self.stats_local += 1
        pts, reached = self.ground.local_path(e.pos(), leg, pad)
        pts = [p for p in pts if math.hypot(p[0] - e.x, p[1] - e.y) > 0.5]
        if not pts:
            return bool(reached)
        if reached:
            e.route = pts + e.route[1:]
        else:
            e.route = pts                                          # stop on the bank: the rest of the way is water
            e.target = pts[-1]
            e.short = True
        return True

    def _start_walk(self, e: Entity, target: Vec, t: float, then: str, speed: Optional[float] = None,
                    to_label: Any = None, fresh: bool = False) -> bool:
        target = self.ground.nearest(target[0], target[1], 24)
        if not self.ground.ok(*target):
            return False
        if then != "vote" and e.platform is not None and (e.state == "voting" or (e.state == "walking" and e.then == "vote")):
            # a standing voter walks off, OR a voter still on the way to a stone is sent somewhere else (`A` then `go
            # north` ten seconds later): both drop the vote (the tally is who stands at close), and both say so on the
            # plank through this event (journal 030: the walker's case was silent, the vote vanished without a word)
            self._ev("leave_platform", pip=e.key, platform=e.platform)
            e.platform, e.slot = None, None
        e.target = target
        e.short = False
        if not self._plan(e, target, t, fresh=fresh):
            e.target, e.route = None, []
            return False
        e.then = then
        e.state = "walking"
        e.speed = 0.0
        e.speed_max = float(speed) if speed else self._u(SPEED_MIN, SPEED_MAX)
        e.walk_speed = e.speed_max
        e.stuck_n = 0
        e.progress_t = t
        e.progress_best = float("inf")
        e.los_t = t
        e.emote = None
        if e.state == "sitting":
            e.sit_until = 0.0
        # presence is the PERSON'S record (message / speak), never a derived verb: the record that carried this walk
        # already made them here, and moving last_active_t here would outrun the honesty reference (last_seen_ts)
        self._ev("walk", pip=e.key, to=(to_label if to_label is not None else [target[0], target[1]]), then=then)
        return True

    def walk_to(self, key: str, target, t: float, then: str = "idle", speed: Optional[float] = None) -> bool:
        """target: a waystone letter (vote), an (x, y) in cells, or (legacy) a bare x. Seeds and hidden settlers never walk.
        `then` names what happens on arrival (idle / pickup:<kind> / place:<kind> / any tag). A verb: the caller's person
        is here (the scene / bridge gate on it); this call marks the activity."""
        e = self.get(key)
        if e is None or not e.is_on_land():
            return False
        if isinstance(target, str) and target.upper() in LETTERS:
            letter = target.upper()
            if e.platform == letter and (e.state == "voting" or (e.state == "walking" and e.then == "vote")):
                return True
            if e.state == "voting":
                self._ev("leave_platform", pip=e.key, platform=e.platform)
                e.platform, e.slot = None, None
            stone = self.waystones[LETTERS.index(letter)]
            taken = {o.slot for o in self.entities.values() if o is not e and o.platform == letter and o.is_on_land() and o.slot is not None}
            i = 0
            while i in taken and i < 60:
                i += 1
            slot = self.ground.nearest(*stand_slot(stone, i))
            d = math.hypot(slot[0] - e.x, slot[1] - e.y)
            spd = min(VOTE_SPEED_CAP, max(SPEED_MAX, d / VOTE_WALK_S))
            e.platform, e.slot = letter, i
            if not self._start_walk(e, slot, t, "vote", speed=spd, to_label=letter):
                e.platform, e.slot = None, None
                return False
            return True
        if isinstance(target, (int, float)):
            target = (float(target), e.y)
        tx, ty = float(target[0]), float(target[1])
        e.platform, e.slot = (None, None) if then != "vote" else (e.platform, e.slot)
        return self._start_walk(e, (tx, ty), t, then, speed=speed)

    def go(self, key: str, where: str, t: float) -> Tuple[bool, str]:
        """The `go` verb (6): a place, one of 8 directions (up to 60 cells), `home` (the camp door) or `@name` (that
        settler, wherever the land took it). Walks at 8 cells/s along the coarse route; the camera leads it; wear follows."""
        e = self.get(key)
        if e is None:
            return False, "no pip called @%s here" % (key or "?")
        if e.state in ("seed", "hatching"):
            return False, "your settler is still arriving"
        if not e.is_on_land():
            return False, "no pip called @%s here" % (key or "?")
        w = (where or "").strip().lower().lstrip("!")
        if w.startswith("the "):
            w = w[4:]
        w = PLACE_ALIASES.get(w, w)
        label: Any = w
        if w.startswith("@"):
            o = self.get(w[1:])
            if o is None or o.state in ("seed", "hatching"):
                return False, "no pip called %s here" % w
            if o is e:
                return False, "you are already there"
            if o.is_on_land():
                dx, dy = e.x - o.x, e.y - o.y
                d = math.hypot(dx, dy) or 1.0
                tx, ty = o.x + dx / d * 6.0, o.y + dy / d * 6.0
            elif o.camp:
                tx, ty = o.camp[0] + 6.0, o.camp[1] + 4.0
            else:
                tx, ty = o.x + 6.0, o.y + 4.0
            label = w
        elif w in ("home", "camp"):
            if not e.camp:
                return False, "you have no camp yet · type camp"
            tx, ty = float(e.camp[0]) + 2.0, float(e.camp[1]) + 3.0
            label = "home"
        elif w in DIRECTIONS:
            dx, dy = DIRECTIONS[w]
            tx = ty = None
            for dist in (GO_DIR_CELLS, 45.0, 30.0, 20.0, 12.0):
                cx, cy = LAND.clamp_cell(e.x + dx * dist, e.y + dy * dist)
                nx, ny = self.ground.nearest(cx, cy, 16)
                if math.hypot(nx - e.x, ny - e.y) >= min(8.0, dist * 0.5):
                    tx, ty = nx, ny
                    break
            if tx is None:
                return False, "the land ends that way"
        elif w in PLACE_WORDS:
            p = self.ground.places.get(w)
            if p is None:
                if w == "moot" or w == "steading":
                    px, py, pr = self.ground.moot[0], self.ground.moot[1], 12
                else:
                    return False, "the %s is not on this land yet" % w
            else:
                px, py, pr = float(p["x"]), float(p["y"]), max(4, int(p.get("radius") or 8) // 2)
            h = name_hash(key, ":go:" + w)
            ang = (h % 3600) / 3600.0 * 2.0 * math.pi
            rad = 2.0 + ((h >> 16) % 1000) / 1000.0 * (pr - 2.0)
            tx, ty = px + rad * math.cos(ang), py + rad * math.sin(ang)
        else:
            return False, GO_HELP
        if not self._start_walk(e, (tx, ty), t, "idle", speed=GO_SPEED, to_label=label):
            return False, "no way through to %s from here" % (label if isinstance(label, str) else "there")
        return True, "ok"

    def fetch(self, key: str, pick: Vec, place: Vec, t: float, kind: str = "stone") -> bool:
        """`stack` (6): walk to `pick`, carry a `kind` (event pickup), walk to `place`, set it down (event place; the
        scene then calls land.stack for a stone). Seeds and hidden settlers never fetch."""
        e = self.get(key)
        if e is None or not e.is_on_land() or kind not in ("stone", "berry", "tool"):
            return False
        then = "pickup:%s:%d:%d" % (kind, int(round(place[0])), int(round(place[1])))   # the place target rides in `then`
        return self._start_walk(e, (float(pick[0]), float(pick[1])), t, then, speed=GO_SPEED, to_label=[pick[0], pick[1]])

    def gather_to(self, key: str, target, t: float) -> bool:
        """A gathering card (AGES 1.3: `the gathering card and an age build` move away bodies like rain, and neither writes
        a record): the land walks this settler, here or away, toward `target` (cells) at errand speed with then=`gather`.
        NOT a verb: no record, `last_active_t` untouched, no wear unless the person is here (the walk's own rule), and a
        standing voter keeps its stone (a vote is the person's). Seeds and hidden settlers never walk."""
        e = self.get(key)
        if e is None or not e.is_on_land():
            return False
        if e.state == "voting" or (e.state == "walking" and e.then == "vote"):
            return False
        if e.state == "sitting":
            e.state = "idle"
        h = name_hash(e.key, ":gather")
        ang = (h % 3600) / 3600.0 * 2.0 * math.pi
        rad = 6.0 + ((h >> 16) % 1000) / 1000.0 * 10.0
        tx, ty = float(target[0]) + rad * math.cos(ang), float(target[1]) + rad * math.sin(ang) * 0.7
        tgt = self.ground.nearest(*LAND.clamp_cell(tx, ty), 12)
        spd = self._u(ERRAND_SPEED[0], ERRAND_SPEED[1]) * e.tempo
        return self._start_walk(e, tgt, t, "gather", speed=spd)

    def release_votes(self, t: float) -> None:
        """A new round opened: everyone standing at a waystone steps off and wanders."""
        for e in list(self.entities.values()):
            if e.state == "voting" or e.platform is not None:
                had = e.platform
                e.platform, e.slot = None, None
                if e.state == "voting":
                    e.state = "idle"
                    e.pause_until = t + self._u(0.2, 1.5)
                    self._ev("leave_platform", pip=e.key, platform=had)
                elif e.state == "walking" and e.then == "vote":
                    e.then = "idle"

    def start_credits(self, t: float) -> None:
        if self.credits_active:
            return
        self.credits_active = True
        for e in self.entities.values():
            e.credits_done = False
        self._credits_queue = [e.key for e in sorted(self.on_land(), key=lambda e: e.x)]
        self._credits_next_t = t
        self._ev("credits_start", count=len(self._credits_queue))

    def set_tier(self, key: str, tier: int, t: float) -> None:
        e = self.get(key)
        if e is not None and int(tier) != e.tier:
            e.tier = int(tier)
            if e.is_on_land():
                e.joy_until = t + JOY_S
            self._ev("tier_up", pip=e.key, tier=e.tier)

    # ------------------------------------------------------------------ the tick
    def tick(self, t: float, dt: Optional[float] = None) -> List[Dict[str, Any]]:
        if dt is None:
            dt = 1.0 / 30.0 if self._last_t is None else max(0.0, min(0.5, t - self._last_t))
        self._last_t = t
        for e in list(self.entities.values()):
            st = LEGACY_STATES.get(e.state)
            if st is not None:
                e.state = st                                       # the cave's names, mapped on the way in (one release)
            st = e.state
            e.present_s = self.present_s
            e.present = st in ON_LAND and (t - e.last_active_t) <= self.present_s
            if st == "seed" or st == "hatching":
                self._tick_seed(e, t)
            elif st in HIDDEN_STATES:
                e.vx = e.vy = 0.0                                  # lies in the grass until a mod lets the person back
            else:
                self._tick_body(e, t, dt)
        if self.credits_active:
            self._tick_credits(t)
        out, self.events = self.events, []
        return out

    def _tick_seed(self, e: Entity, t: float) -> None:
        age = t - e.seed_t
        if not e.seed_landed:
            s = min(1.0, max(0.0, age / TUFT_DRIFT_S))
            k = 1.0 - (1.0 - s) ** 2                              # ease-out: fast off the edge, settling onto the green
            e.x = e.seed_from[0] + (e.seed_to[0] - e.seed_from[0]) * k
            e.y = e.seed_from[1] + (e.seed_to[1] - e.seed_from[1]) * k
            if s >= 1.0:
                e.x, e.y = e.seed_to
                e.seed_landed = True
                self._ev("seed_land", key=e.key, x=e.x, y=e.y)
        if e.cleared and age >= self.hold_s:
            ready = True
            if self.sheet_ready is not None and age < self.hold_s + SHEET_GRACE_S:
                try:
                    ready = bool(self.sheet_ready(e.key))
                except Exception:
                    ready = True
            if ready:
                self._hatch(e, t)
        elif not e.cleared and age > SEED_TIMEOUT_S:
            self.sink(e.key, t)

    def _hatch(self, e: Entity, t: float) -> None:
        e.x, e.y = e.seed_to if not e.seed_landed else (e.x, e.y)
        e.seed_landed = True
        e.state = "idle"
        e.hatch_t = t
        e.born_t = t
        e.last_active_t = t
        e.last_attention_t = t
        e.present = True
        e.present_s = self.present_s
        e.spoke_t = t
        e.pause_until = t + self._u(1.0, 2.5)
        e.next_blink_t = t + self._u(BLINK_MIN, BLINK_MAX)
        e.minutes_tonight = 0.0
        e.next_mutter_t = t + self._u(*MUTTER_FIRST)
        e.fx, e.fy = 0, 1
        first_light = not self.first_light_done and (self.first_light_pending == e.key or
                                                     (self.first_light_pending is None and self.present_count() == 1))
        self._ev("hatch", pip=e.key, display_name=e.display_name, first_ever=e.first_ever, x=e.x, y=e.y,
                 only_light=(self.present_count() == 1))
        if first_light:
            self.first_light_done = True
            self.first_light_pending = None
            self._ev("first_light", pip=e.key)
        for o in self.entities.values():
            if o is not e and o.is_on_land() and o.state != "walking" and math.hypot(e.x - o.x, e.y - o.y) <= LOOK_CELLS:
                self._face(o, e.x - o.x, e.y - o.y)
                o.look_key, o.look_until = e.key, t + LOOK_S

    def _tick_body(self, e: Entity, t: float, dt: float) -> None:
        """Every hatched, unhidden settler, here or away (AGES 1.1 / 1.3): blink, the glow's slow dim, the berry, the mutter
        (here only), then the walk / the stand at a stone (here only) / the sit / the next errand. Nobody lies down and
        nothing here reads the quiet as a reason to go home."""
        if e.present:
            e.minutes_tonight += dt / 60.0
        if t >= e.next_blink_t:                                   # blink every 4-7 s
            e.blink_until = t + BLINK_LEN
            e.next_blink_t = t + self._u(BLINK_MIN, BLINK_MAX)
            self._ev("blink", pip=e.key)
        if t - e.last_attention_t > ATTENTION_S:                  # cosmetic dim (the glow strength): -0.01 per unattended minute
            e.energy = max(CURL_FLOOR, e.energy - DECAY_PER_MIN * dt / 60.0)
        if e.carry == "berry" and t >= e.carry_until:              # the berry is eaten
            self.drop(e.key, t)
        if e.state == "voting" and not e.present:
            # a vote is the person's (AGES 4.2 agency): the body of an away person steps off the stone at once
            self._ev("leave_platform", pip=e.key, platform=e.platform)
            e.platform, e.slot = None, None
            e.state = "idle"
            e.pause_until = t + self._u(0.5, 2.0)
        if e.present and e.state in ("idle", "sitting") and t >= e.speak_until and t >= e.next_mutter_t and not self.credits_active:
            e.next_mutter_t = t + self._u(*MUTTER_GAP)
            self._ev("mutter_due", pip=e.key)            # the scene answers with one of the owner's OWN allowlisted words
        if e.state == "walking":
            self._move(e, t, dt)
        elif e.state == "voting":
            e.vx = e.vy = 0.0
        elif e.state == "sitting":
            e.vx = e.vy = 0.0
            if t >= e.sit_until:
                e.state = "idle"
                e.pause_until = t + self._u(0.5, 2.5)
        elif e.state == "idle" and t >= e.pause_until and not (self.credits_active and e.credits_done):
            self._pick_idle(e, t)

    def _stand_at_camp(self, e: Entity, t: float) -> None:
        """Credits (stop.sh --credits): the settler walks home and STANDS at the door with its name and minutes (AGES 1.1).
        Without a camp it stands where it is. Nobody lies down, no camp is pitched."""
        if e.state == "voting":
            self._ev("leave_platform", pip=e.key, platform=e.platform)
            e.platform, e.slot = None, None
        if e.state == "sitting":
            e.state = "idle"
        if e.camp:
            tgt: Vec = (float(e.camp[0]) + 2.0, float(e.camp[1]) + 3.0)
        else:
            tgt = e.pos()
        if math.hypot(tgt[0] - e.x, tgt[1] - e.y) <= ARRIVE_R + 0.5 or not self._start_walk(e, tgt, t, "credits", speed=GO_SPEED):
            e.route, e.target, e.then = [], None, "credits"
            self._arrive(e, t)                                     # already there / no way home: the credits land where it stands

    def _nearest_bank(self, x: float, y: float, r: int = WATER_MAX_CELLS) -> Optional[Vec]:
        """The passable cell beside the nearest water cell within `r` of (x, y), or None (flat harness / no water near)."""
        W = self.ground.water
        if W is None:
            return None
        xi, yi = int(x), int(y)
        x0, x1 = max(0, xi - r), min(self.ground.w, xi + r + 1)
        y0, y1 = max(0, yi - r), min(self.ground.h, yi + r + 1)
        ys, xs = np.nonzero(W[y0:y1, x0:x1])
        if len(xs) == 0:
            return None
        dd = (xs + x0 - x) ** 2 + (ys + y0 - y) ** 2
        k = int(np.argmin(dd))
        if dd[k] > r * r:
            return None
        wx, wy = float(xs[k] + x0), float(ys[k] + y0)
        d = math.hypot(wx - x, wy - y) or 1.0
        bank = self.ground.nearest(wx - (wx - x) / d * 1.5, wy - (wy - y) / d * 1.5, 8)   # one step back toward the settler
        return bank if self.ground.ok(*bank) else None

    def _pick_idle(self, e: Entity, t: float) -> None:
        """The land moves the settler (AGES 1.3, the minimal table): once per dwell end, here or away alike, draw an errand
        by the day / night weights (never the same twice running, +/-30 % per name), walk at 4-6 cells/s x tempo and
        dwell on arrival (`_arrive`). The errand is the land's, not the person's: `then` is `errand:<name>` (or `sit`),
        `last_active_t` is untouched, no wear unless the person is here. `huddle` (rounds) aims every errand at the Moot."""
        n = self._night()
        mx, my = self.ground.moot
        opts: List[Tuple[str, float]] = []
        for name in ERRANDS:
            if name == e.errand or (name == "home" and not e.camp) or (name == "water" and self.ground.water is None):
                continue
            d, nt = ERRAND_WEIGHTS[name]
            w = (d * (1.0 - n) + nt * n) * (0.7 + 0.6 * (((name_hash(e.key, ":w:" + name) >> 8) % 1000) / 1000.0))
            if w > 0:
                opts.append((name, w))
        if not opts:
            opts = [("stroll", 1.0)]
        r = self.rng.random() * sum(w for _, w in opts)
        pick = opts[-1][0]
        for name, w in opts:
            r -= w
            if r <= 0:
                pick = name
                break
        then = "errand:" + pick
        if self.colony_rule == "huddle":
            tx, ty = mx + self._u(-20, 20), my + self._u(-14, 14)
        elif pick == "home":
            tx, ty = float(e.camp[0]) + 2.0, float(e.camp[1]) + 3.0                          # the door, as `go home`
        elif pick == "moot":
            ang, rad = self._u(0, 2 * math.pi), self._u(MOOT_RING[0], MOOT_RING[1])
            tx, ty = mx + rad * math.cos(ang), my + rad * math.sin(ang) * 0.7
            for sx, sy in self.waystones:                                                     # never a standing slot
                if math.hypot(tx - sx, ty - (sy + STAND_Y0 + STAND_DY)) < 6.0:
                    ty += 8.0
        elif pick == "water":
            bank = self._nearest_bank(e.x, e.y)
            if bank is None:
                e.errand = pick                                                               # not retried at once
                e.pause_until = t + self._u(1.0, 3.0)
                return
            tx, ty = bank
            if self.rng.random() < 0.5:
                then = "sit"
        else:                                                                                 # stroll: the old hop
            if self.rng.random() < MOOT_GRAVITY:
                f = self._u(0.2, 0.6)
                tx, ty = e.x + (mx - e.x) * f + self._u(-8, 8), e.y + (my - e.y) * f + self._u(-6, 6)
            else:
                ang, rad = self._u(0, 2 * math.pi), self._u(8, WANDER_STEP)
                tx, ty = e.x + rad * math.cos(ang), e.y + rad * math.sin(ang) * 0.7
        d = math.hypot(tx - mx, ty - my)
        if d > IDLE_RADIUS:                                         # 4.4 gravity cap: life stays findable
            tx, ty = mx + (tx - mx) * IDLE_RADIUS / d, my + (ty - my) * IDLE_RADIUS / d
        tx, ty = LAND.clamp_cell(tx, ty)
        tgt = self.ground.nearest(tx, ty, 12)
        e.errand = pick
        if math.hypot(tgt[0] - e.x, tgt[1] - e.y) < 2.0 or not self.ground.ok(*tgt):
            e.pause_until = t + self._u(1.0, 3.0) * e.tempo
            if self.rng.random() < FACE_WIND_P:
                wx, wy = self.wind_vector()
                self._face(e, -wx, -wy)
            return
        spd = self._u(ERRAND_SPEED[0], ERRAND_SPEED[1]) * e.tempo
        if not self._start_walk(e, tgt, t, then, speed=spd):
            e.pause_until = t + self._u(1.0, 3.0)

    def _move(self, e: Entity, t: float, dt: float) -> None:
        if e.target is None or not e.route:
            e.state = "idle"
            e.vx = e.vy = 0.0
            return
        g = self.ground
        if t - e.los_t >= LOS_RECHECK_S and len(e.route) > 1:
            e.los_t = t
            if not self._string_pull(e, t):
                self._arrive(e, t, gave_up=True)
                return
        e.speed = min(e.speed_max, e.speed + e.speed_max / EASE_FRAMES)      # ease-in over ~9 frames
        budget = e.speed * g.speed_mult(e.x, e.y) * dt
        x0, y0 = e.x, e.y
        x, y = x0, y0
        guard = 0
        while e.route and guard < 6:
            guard += 1
            leg = e.route[0]
            last = len(e.route) == 1
            dx, dy = leg[0] - x, leg[1] - y
            d = math.hypot(dx, dy)
            if d < (ARRIVE_R if last else WAYPOINT_R):
                if last:
                    if g.ok(*leg):
                        x, y = leg
                    e.x, e.y = x, y
                    e.vx = e.vy = 0.0
                    self._wear(e, x, y)
                    self._arrive(e, t)
                    return
                e.route.pop(0)
                e.progress_best = float("inf")
                e.progress_t = t
                e.x, e.y = x, y
                if not self._string_pull(e, t):
                    self._arrive(e, t, gave_up=True)
                    return
                continue
            # progress / stuck detector (3 s without 0.5 cell of progress toward the leg)
            if d < e.progress_best - STUCK_PROGRESS:
                e.progress_best = d
                e.progress_t = t
            elif t - e.progress_t > STUCK_S:
                e.x, e.y = x, y
                self._stuck(e, t)
                return
            if budget <= 1e-6:
                break
            ux, uy = dx / d, dy / d
            step = min(d, budget)
            nsub = max(1, int(math.ceil(step)))
            sub = step / nsub
            moved = 0.0
            for _ in range(nsub):
                got = None
                for cx, cy in self._slide_candidates(ux, uy):
                    nx, ny = x + cx * sub, y + cy * sub
                    if g.ok(nx, ny):
                        got = (nx, ny)
                        break
                if got is None:
                    break
                x, y = got
                moved += sub
            budget -= moved
            if moved < step - 1e-9:
                break                                             # blocked (partly) this frame; the stuck timer runs
        e.vx, e.vy = (x - x0) / max(dt, 1e-6), (y - y0) / max(dt, 1e-6)
        if x != x0 or y != y0:
            self._face(e, x - x0, y - y0)
            e.x, e.y = x, y
            self._wear(e, x, y)

    def _wear(self, e: Entity, x: float, y: float) -> None:
        """A real, PRESENT pip entered a new cell: +8 wear there through land.step() (the ONLY writer of wear, 12). An away
        settler is moved by the land and wears no trail (AGES 1.3 / 4.2: zero wear while zero settlers are here)."""
        cell = (int(math.floor(x)), int(math.floor(y)))
        if cell == e.last_cell:
            return
        e.last_cell = cell
        e.cells_walked += 1
        if not e.is_present():
            return
        if self.land is not None and e.origin == "chat":
            try:
                self.land.step(e.key, cell[0], cell[1])
            except Exception:
                pass

    @staticmethod
    def _slide_candidates(ux: float, uy: float):
        """The desired direction, then the one-cell slide rule: axis-only moves, then +/-45 and +/-90 degree turns,
        so a convex trunk or bank is skirted instead of stopping the pip."""
        yield (ux, uy)
        if abs(ux) > 1e-6:
            yield (1.0 if ux > 0 else -1.0, 0.0)
        if abs(uy) > 1e-6:
            yield (0.0, 1.0 if uy > 0 else -1.0)
        c, s = math.cos(math.pi / 4.0), math.sin(math.pi / 4.0)
        yield (ux * c - uy * s, ux * s + uy * c)
        yield (ux * c + uy * s, -ux * s + uy * c)
        yield (-uy, ux)
        yield (uy, -ux)

    def _stuck(self, e: Entity, t: float) -> None:
        """No progress for 3 s: reroute once from here on the coarse grid (fresh BFS); the second time, the walk ends
        where the pip stands (never a teleport, never through water)."""
        e.stuck_n += 1
        e.stuck_total += 1
        self.stats_stuck += 1
        self._ev("stuck", pip=e.key, n=e.stuck_n, x=e.x, y=e.y)
        e.progress_t = t
        e.progress_best = float("inf")
        if e.stuck_n >= STUCK_GIVE_UP or e.target is None:
            self._arrive(e, t, gave_up=True)
            return
        # step aside one cell (perpendicular to the leg) before the fresh route so a corner is not re-tried head-on
        leg = e.route[0] if e.route else e.target
        dx, dy = leg[0] - e.x, leg[1] - e.y
        d = math.hypot(dx, dy) or 1.0
        for sx, sy in ((-dy / d, dx / d), (dy / d, -dx / d), (-dx / d, -dy / d)):
            nx, ny = e.x + sx * 1.5, e.y + sy * 1.5
            if self.ground.ok(nx, ny) and self.ground.clear_line(e.pos(), (nx, ny)):
                e.x, e.y = nx, ny
                break
        e.leg_t = -1e9
        if not self._plan(e, e.target, t, fresh=True) or not self._ensure_leg(e, t, pad=LOCAL_PAD * 2):
            self._arrive(e, t, gave_up=True)

    def _arrive(self, e: Entity, t: float, gave_up: bool = False) -> None:
        act = e.then or "idle"
        e.then = None
        e.route = []
        e.target = None
        e.speed = 0.0
        e.vx = e.vy = 0.0
        if act == "vote" and e.platform is not None and not gave_up and not e.short:
            e.state = "voting"
            stone = self.waystones[LETTERS.index(e.platform)]
            self._face(e, stone[0] - e.x, stone[1] - e.y)
            self._ev("arrive", pip=e.key, at=e.platform)
            return
        if act == "credits":
            e.platform, e.slot = None, None
            e.state = "idle"
            e.credits_done = True
            e.fx, e.fy = 0, 1                                      # stands at the door, facing out, with name + minutes
            e.pause_until = t + self._u(1.0, 4.0)
            self._ev("credits", pip=e.key, minutes_tonight=round(e.minutes_tonight, 1),
                     camp=list(e.camp) if e.camp else None, x=e.x, y=e.y)
            return
        if act == "sit" and not gave_up:
            e.platform, e.slot = None, None
            e.state = "sitting"                                    # sticky 20-90 s x tempo; a message or a round event ends it
            e.sit_until = t + self._u(*SIT_DWELL) * e.tempo
            self._ev("arrive", pip=e.key, at=act, x=e.x, y=e.y, gave_up=gave_up, short=e.short)
            e.short = False
            return
        if act.startswith("pickup:") and not gave_up:
            parts = act.split(":")
            kind = parts[1] if len(parts) > 1 else "stone"
            e.carry, e.carry_until = kind, float("inf")
            self._ev("pickup", pip=e.key, kind=kind, x=e.x, y=e.y)
            if len(parts) >= 4:
                px, py = float(parts[2]), float(parts[3])
                e.state = "idle"
                e.pause_until = t + 0.4
                if self._start_walk(e, (px, py), t, "place:%s" % kind, speed=GO_SPEED, to_label=[px, py]):
                    return
            e.state = "idle"
            e.pause_until = t + self._u(1.0, 3.0)
            return
        if act.startswith("place:") and not gave_up:
            kind = act.split(":")[1] if ":" in act else (e.carry or "stone")
            if e.carry:
                e.carry, e.carry_until = None, float("inf")
            e.hop_t = t
            self._ev("place", pip=e.key, kind=kind, x=e.x, y=e.y)
        e.platform, e.slot = None, None
        e.state = "idle"
        if act.startswith("errand:") or act == "gather":
            name = act.split(":", 1)[1] if ":" in act else "moot"      # a gathering ends like the Moot errand: stand and look
            lo, hi = ERRAND_DWELL.get(name, (1.0, 3.0))
            e.pause_until = t + self._u(lo, hi) * e.tempo          # the dwell: stand / look, then the next errand
            if name == "home":
                e.fx, e.fy = 0, 1                                  # stands at the door facing out
            elif name == "moot":
                mx, my = self.ground.moot
                self._face(e, mx - e.x, my - e.y)                  # looks at the monument / board / beacon
        else:
            e.pause_until = t + self._u(1.0, 4.0)
        if not act.startswith(("place:", "errand:", "gather")) and self.newest_speaker and self.newest_speaker in self.entities and self.newest_speaker != e.key:
            s = self.entities[self.newest_speaker]
            if math.hypot(s.x - e.x, s.y - e.y) <= LOOK_CELLS:
                self._face(e, s.x - e.x, s.y - e.y)                # a look (reaction), never a walk target
        self._ev("arrive", pip=e.key, at=act, x=e.x, y=e.y, gave_up=gave_up, short=e.short)
        e.short = False

    def _tick_credits(self, t: float) -> None:
        if t < self._credits_next_t:
            return
        while self._credits_queue:
            k = self._credits_queue.pop(0)
            e = self.entities.get(k)
            if e is not None and e.is_on_land() and not e.credits_done and e.then != "credits":
                self._stand_at_camp(e, t)
                self._credits_next_t = t + CREDITS_GAP_S
                return
        if not any(e.is_on_land() and not e.credits_done for e in self.entities.values()):
            self.credits_active = False
            self._ev("credits_end")

    # ------------------------------------------------------------------ stats / honesty helpers
    def in_water_count(self) -> int:
        """Hatched pips standing on an impassable cell (water, trunk, boulder, margin): must always be 0."""
        return sum(1 for e in self.entities.values() if e.state not in ("seed", "hatching") and not self.ground.ok(e.x, e.y))

    def stats(self) -> Dict[str, Any]:
        return {"entities": len(self.entities), "present": self.present_count(), "on_land": len(self.on_land()),
                "awake": self.present_count(),
                "seeds": len(self.seeds()), "routes": self.stats_routes, "local_paths": self.stats_local, "stuck": self.stats_stuck,
                "in_water": self.in_water_count(), "voting": sum(len(v) for v in self.platform_counts().values())}


# ---------------------------------------------------------------------------- self-test
def _selftest(run_dir: str) -> int:   # pragma: no cover (exercised by `$PYTHON stream/world/behaviour.py`)
    import shutil
    import time as _time
    from stream.world import terrain
    ok_all = True

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal ok_all
        print("[%s] %s%s" % ("ok" if cond else "FAIL", name, (" · " + detail) if detail else ""))
        if not cond:
            ok_all = False

    rp = os.path.realpath(run_dir)
    if not (rp.startswith("/tmp/") or rp.startswith("/private/tmp/")):
        print("refused: RUN_DIR must be under /tmp (got %s)" % run_dir)
        return 2
    T = terrain.generate(4471)
    moot = (float(T.site[0]), float(T.site[1]))
    FPS, DT = 30.0, 1.0 / 30.0
    wind = [(1.0, 0.3)]
    now = 1_700_000_000.0

    # ---- 1. the tuft: nameless, on the wind, hatch never before the hold, waits for the sheet up to the grace
    ready = {"v": False}
    b = Behaviour(seed=7, sleep_after_s=60.0, hold_s=3.0, terrain=T, moot=moot, wind=lambda: wind[0], sheet_ready=lambda k: ready["v"])
    e = b.seed_drop("newcomer_one", now)
    land_xy = e.seed_to
    check("tuft lands inside 30 cells of the green on a passable cell",
          math.hypot(land_xy[0] - moot[0], land_xy[1] - moot[1]) <= TUFT_RING + 1 and T.is_passable(*land_xy), "%r" % (land_xy,))
    check("tuft starts upwind (150 cells against the wind)", abs(math.hypot(e.x - land_xy[0], e.y - land_xy[1]) - TUFT_DRIFT_CELLS) < 1e-6)
    d0 = e.to_dict(now)
    check("tuft dict carries no name", d0["display_name"] is None and d0["frame"] == "tuft0")
    evs = []
    b.hold_cleared("newcomer_one", now + 0.5, "Newcomer", 0, 0.6, 0, True)
    landed_t = hatch_t = None
    for i in range(1, int(9 * FPS)):
        t = now + i * DT
        if t >= now + 3.0 + 1.0:
            ready["v"] = True                       # the sheet lands 1 s after the hold
        for ev in b.tick(t, DT):
            evs.append(ev["type"])
            if ev["type"] == "seed_land":
                landed_t = t
            if ev["type"] == "hatch":
                hatch_t = t
    check("seed_land at ~2 s, hatch waited for the sheet (>= 4 s, < grace)", landed_t is not None and abs(landed_t - now - 2.0) < 0.1
          and hatch_t is not None and 3.9 <= hatch_t - now <= 4.2, "land %.2f hatch %.2f" % (landed_t - now, hatch_t - now))
    check("first_light credited to the tuft's hatch", "first_light" in evs and evs.index("first_light") == evs.index("hatch") + 1)
    e = b.get("newcomer_one")
    check("hatched pip stands on the landing spot, passable, here", T.is_passable(e.x, e.y) and e.is_on_land() and e.is_present(t))
    # grace: a sheet that never comes still hatches at hold + 4 s
    b2 = Behaviour(seed=8, hold_s=3.0, terrain=T, moot=moot, sheet_ready=lambda k: False)
    b2.seed_drop("slow_sheet", now)
    b2.hold_cleared("slow_sheet", now, "Slow", 0, 0.6, 0, True)
    ht = None
    for i in range(1, int(9 * FPS)):
        for ev in b2.tick(now + i * DT, DT):
            if ev["type"] == "hatch":
                ht = now + i * DT
    check("sheet never ready -> hatch at hold + grace (7 s)", ht is not None and 6.9 <= ht - now <= 7.2, "%.2f" % ((ht or now) - now))
    # sink: hidden inside the hold
    b2.seed_drop("hidden_one", now + 10)
    b2.tick(now + 10.5, DT)
    check("sink removes an uncleared tuft, no hatch", b2.sink("hidden_one", now + 11) and b2.get("hidden_one") is None)

    # ---- 2. go: places, directions, home, @name; every committed position passable
    b.speak("newcomer_one", now + 9, "hello land")
    ok, why = b.go("newcomer_one", "river", now + 9)
    check("go river accepted", ok, why)
    ok2, why2 = b.go("newcomer_one", "away", now + 9)
    check("go away refused with the place list", not ok2 and why2.startswith("go where?"), why2)
    ok3, why3 = b.go("newcomer_one", "home", now + 9)
    check("go home refused without a camp", not ok3 and "camp" in why3, why3)
    arrived = None
    t = now + 9
    for i in range(int(60 * FPS)):
        t += DT
        for ev in b.tick(t, DT):
            if ev["type"] == "arrive" and arrived is None:
                arrived = (t, ev)
        e = b.get("newcomer_one")
        assert T.is_passable(e.x, e.y), "in water at %r" % ((e.x, e.y),)
        if arrived:
            break
    riv = T.places["river"]
    check("arrived by the river at 8 cells/s, never in water", arrived is not None and math.hypot(e.x - riv["x"], e.y - riv["y"]) <= riv["radius"] + 2
          and not arrived[1]["gave_up"], "%.1f s, %r" % ((arrived[0] - now - 9) if arrived else -1, (round(e.x), round(e.y))))
    # directions
    e = b.get("newcomer_one")
    x0, y0 = e.x, e.y
    ok, why = b.go("newcomer_one", "north", t)
    check("go north accepted; target ~60 cells north", ok and e.target is not None and e.target[1] < y0 - 20, "%r -> %r" % ((round(x0), round(y0)), e.target))

    # ---- 3. votes: slots at the waystones, tally = len(), release
    for k in ("voter_a", "voter_b", "voter_c", "voter_d"):
        b.seed_drop(k, t - 10)
        b.hold_cleared(k, t - 10, k, 1, 0.6, 0, True)
    for i in range(int(2 * FPS)):
        t += DT
        b.tick(t, DT)
    for k, letter in (("voter_a", "A"), ("voter_b", "A"), ("voter_c", "B"), ("voter_d", "A")):
        check("walk_to %s accepted for %s" % (letter, k), b.walk_to(k, letter, t))
    cam = b.camera_inputs(t, 40)
    check("camera inputs: walking_to_stone while voters walk, 3 stones", cam["moot"]["walking_to_stone"] and len(cam["moot"]["stones"]) == 3)
    for i in range(int(12 * FPS)):
        t += DT
        b.tick(t, DT)
    pc = b.platform_counts()
    slots = {(round(b.get(k).x, 1), round(b.get(k).y, 1)) for k in pc["A"]}
    check("tally A=3 B=1 from standing pips, distinct slots", len(pc["A"]) == 3 and len(pc["B"]) == 1 and len(slots) == 3, "%r" % pc)
    check("crowd_bounce hops every A voter", b.crowd_bounce("A", t) == 3)
    b.release_votes(t)
    check("release_votes empties the tally", sum(len(v) for v in b.platform_counts().values()) == 0)

    # ---- 4. 2 min quiet (AGES 1.1 / 8): nobody lies down. The settler stays on the land standing or erranding, present
    #         False, wear delta 0 (no land here: the wear gate is section 7); a message is a `return`, not a wake
    ev_types = []
    states = set()
    errand_walks = 0
    walk_thens = []
    for i in range(int(75 * FPS)):
        t += DT
        for ev in b.tick(t, DT):
            if ev.get("pip") == "voter_c":
                ev_types.append(ev["type"])
                if ev["type"] == "walk":
                    walk_thens.append(str(ev.get("then") or ""))
                    if walk_thens[-1].startswith(("errand:", "sit")):
                        errand_walks += 1
        states.add(b.get("voter_c").state)
    e = b.get("voter_c")
    check("quiet 60 s: voter_c stays on the land (states %s), present False, no sleep / wake / curl event, never the lying pose" % sorted(states),
          e.is_on_land() and not e.is_present(t) and states <= set(ON_LAND) and not ({"sleep", "wake", "curl", "camp_new"} & set(ev_types))
          and e.frame_name(t) != "sleep" and e.platform is None and e.camp is None, "events %r" % sorted(set(ev_types)))
    check("the land moved it: >= 1 errand walk (then errand:* / sit), no verb-tagged walk while away", errand_walks >= 1
          and all(w.startswith(("errand:", "sit")) for w in walk_thens), "%d errand walks, thens %r" % (errand_walks, sorted(set(walk_thens))))
    check("everyone quiet -> present_count 0, all still on the land", b.present_count() == 0 and len(b.on_land()) == 5 and b.asleep_count() == 0,
          "present %d on_land %d" % (b.present_count(), len(b.on_land())))
    b.message("voter_c", t)
    ret = [ev for ev in b.tick(t + DT, DT) if ev["type"] == "return"]
    e = b.get("voter_c")
    check("a message after > present_s is a `return` (away_s >= 60), the settler is here, hops, keeps its place",
          len(ret) == 1 and ret[0]["pip"] == "voter_c" and (ret[0]["away_s"] or 0) >= 60 and e.is_present(t + DT) and e.hop_phase(t + DT) >= 0
          and b.present_count() == 1, "%r" % (ret[:1],))
    ok, why = b.go("voter_c", "home", t + 1)
    check("go home still refused without a camp (nobody slept one into being)", not ok and "camp" in why, why)
    b.set_camp("voter_c", int(e.x) + 6, int(e.y) + 4)
    ok, why = b.go("voter_c", "home", t + 1)
    check("go home accepted once the land recorded a camp", ok, why)
    rets = []
    for k in ("voter_a", "voter_b", "voter_d", "newcomer_one"):
        b.message(k, t + 1)                           # their owners chat again: each is a return where it stands
    rets = [ev for ev in b.tick(t + 1 + DT, DT) if ev["type"] == "return"]
    check("four more returns, no wake event, present_count 5", len(rets) == 4 and b.present_count() == 5, "%d returns" % len(rets))
    ok, why = b.go("voter_a", "@voter_c", t + 1)
    check("go @name accepted", ok, why)

    # ---- 5. carry / fetch: pick a stone on the Fell, carry it to the cairn, place it
    fell = T.places["fell"]
    ok = b.fetch("voter_b", (fell["x"], fell["y"]), moot, t + 1)
    check("fetch accepted", ok)
    seen = []
    for i in range(int(90 * FPS)):
        t += DT
        for ev in b.tick(t, DT):
            if ev.get("pip") == "voter_b" and ev["type"] in ("pickup", "place", "arrive", "stuck"):
                seen.append(ev["type"])
                if ev["type"] == "pickup":
                    check("carry frame while carrying the stone", b.get("voter_b").frame_name(t + 0.2) == "carry_stone")
        if "place" in seen:
            break
    check("fetch: pickup then place at the cairn", seen[:1] == ["pickup"] and "place" in seen and b.get("voter_b").carry is None, "%r" % seen)
    berry_ok = b.carry("voter_a", t, "berry")
    check("berry carried 2.4 s then eaten", berry_ok and b.get("voter_a").carry == "berry")
    for i in range(int(3 * FPS)):
        t += DT
        b.tick(t, DT)
    check("berry gone after CARRY_S", b.get("voter_a").carry is None)

    # ---- 6. credits: everyone walks home one by one and STANDS at the door (or where it is) with its minutes; nobody lies down
    for k in ("voter_a", "voter_b", "voter_c", "voter_d", "newcomer_one"):
        b.message(k, t)
    b.tick(t + DT, DT)
    n_land = len(b.on_land())
    b.start_credits(t)
    creds = []
    ended = False
    for i in range(int(90 * FPS)):
        t += DT
        for ev in b.tick(t, DT):
            if ev["type"] == "credits":
                creds.append(ev)
            elif ev["type"] == "credits_end":
                ended = True
    ec = b.get("voter_c")
    check("credits: one `credits` event per settler, all still standing on the land, credits_end, no sleep event",
          len(creds) == n_land >= 4 and ended and not b.credits_active and all(e.is_on_land() and e.frame_name(t) != "sleep" for e in b.hatched()),
          "%d credits of %d on the land" % (len(creds), n_land))
    check("the settler with a camp stands at its door", ec.camp is not None and math.hypot(ec.x - (ec.camp[0] + 2), ec.y - (ec.camp[1] + 3)) <= 3.0,
          "at %r, camp %r" % ((round(ec.x), round(ec.y)), ec.camp))

    # ---- 7. wear honesty with a real schema-2 WorldState in RUN_DIR: only chat pips write wear, 8 per step + spill
    from stream.world.state import WorldState
    if os.path.isdir(run_dir):
        shutil.rmtree(run_dir)
    os.makedirs(run_dir)
    ws = WorldState(run_dir, schema=2, moot=(int(moot[0]), int(moot[1])), passable=T.passable, water=T.water, now=now)
    ws.ensure_pip("walker_real", "walker_real", "walker_real", 5, now)
    ws.ensure_pip("test-pip-00", "test-pip-00", "test pip 0", None, now)
    ws.pips["test-pip-00"]["_test"] = True
    bw = Behaviour(seed=3, hold_s=3.0, terrain=T, land=ws.land, moot=moot)
    for k, o in (("walker_real", "chat"), ("test-pip-00", "test")):
        bw.seed_drop(k, now - 10, origin=o)
        bw.hold_cleared(k, now - 10, k, 1, 0.6, 0, True)
    bw.tick(now, DT)
    bw.go("walker_real", "shore", now)
    bw.go("test-pip-00", "shore", now)
    tw = now
    steps_before = bw.get("walker_real").cells_walked
    added_total = steps_total = 0
    for i in range(int(20 * FPS)):
        tw += DT
        bw.tick(tw, DT)
        a, s = ws.land.take_wear_added()
        assert a <= 16 * s, "wear added %d for %d steps" % (a, s)
        added_total += a
        steps_total += s
    real_cells = bw.get("walker_real").cells_walked - steps_before
    test_cells = bw.get("test-pip-00").cells_walked
    check("wear: real pip steps == land steps, 8..16 per step; test pip wrote nothing",
          steps_total == real_cells and real_cells > 20 and 8 * steps_total <= added_total <= 16 * steps_total and test_cells > 0
          and int(ws.land.wear.sum()) == added_total, "steps %d (test walked %d) added %d" % (steps_total, test_cells, added_total))
    # the real pip's person goes quiet (present_s 30 s): the settler stays on the land, is moved by the land (errands), and
    # lays NO wear while away (AGES 1.3 / 4.2: zero wear while zero settlers are here); the person's next message brings it
    # back and its steps wear the land again
    ws.begin_session("sess-b", tw)
    bw.session_id = "sess-b"
    bw.present_s = 30.0
    away_states = set()
    away_frames = walking_away = errand_walks = 0
    steps_away = added_away = 0
    for i in range(int(90 * FPS)):
        tw += DT
        e = bw.get("walker_real")
        evs = bw.tick(tw, DT)
        a, s = ws.land.take_wear_added()
        if not e.is_present(tw):
            away_frames += 1
            steps_away += s
            added_away += a
            away_states.add(e.state)
            if e.walking():
                walking_away += 1
            errand_walks += sum(1 for ev in evs if ev["type"] == "walk" and ev["pip"] == "walker_real"
                                and str(ev.get("then") or "").startswith(("errand:", "sit")))
    e = bw.get("walker_real")
    check("quiet 30 s: walker_real stays on the land (states %s), erranded (%d errand walks, %d walking frames), present False, "
          "wear delta 0 while away (steps %d added %d), no camp pitched" % (sorted(away_states), errand_walks, walking_away, steps_away, added_away),
          away_frames > 30 * FPS and away_states <= set(ON_LAND) and errand_walks >= 1 and walking_away > 0 and steps_away == 0 and added_away == 0
          and not e.is_present(tw) and ws.pips["walker_real"].get("camp") is None and bw.ground.ok(e.x, e.y))
    bw.message("walker_real", tw)
    ret = [ev for ev in bw.tick(tw + DT, DT) if ev["type"] == "return" and ev["pip"] == "walker_real"]
    ws.land.take_wear_added()
    bw.go("walker_real", "orchard", tw + DT)
    steps_back = 0
    for i in range(int(8 * FPS)):
        tw += DT
        bw.tick(tw, DT)
        a, s = ws.land.take_wear_added()
        steps_back += s
    check("a message returns the settler (event `return`, away_s >= 30) and its steps wear the land again",
          len(ret) == 1 and (ret[0]["away_s"] or 0) >= 30 and bw.get("walker_real").is_present(tw) and steps_back > 10,
          "return %r steps_back %d" % (ret[:1], steps_back))
    # a camp is the land's record (ws.ensure_camp / the `camp` verb), never a lie-down: the entity follows the record
    camp = ws.ensure_camp("walker_real", tw, "sess-b", int(e.x) + 3, int(e.y) + 3)
    if isinstance(camp, dict):
        bw.set_camp("walker_real", camp["x"], camp["y"])
    check("ensure_camp records a camp for the real pip; the entity remembers it and stays standing where it is",
          isinstance(camp, dict) and bw.get("walker_real").camp == (camp["x"], camp["y"]) and bw.get("walker_real").is_on_land()
          and camp.get("nights") == ["sess-b"], "%r" % (camp,))
    check("no provenance violations on the land", ws.land.provenance_violations() == [], "%r" % ws.land.provenance_violations())
    ws.save(tw, force=True)
    check("world.json flushed in RUN_DIR", os.path.exists(os.path.join(run_dir, "world.json")))

    # ---- 8. pathing harness: 60 test pips, random go targets for 5 min, zero stuck twice, zero in water; tick timing
    bh = Behaviour(seed=11, hold_s=3.0, terrain=T, moot=moot)
    th = now
    for i in range(60):
        k = "test-pip-%02d" % i
        bh.seed_drop(k, th - 10, origin="test")
        bh.hold_cleared(k, th - 10, "test pip %d" % i, i % 4, 0.6, 0, True)
    bh.tick(th, DT)
    rng = np.random.default_rng(5)
    targets = list(PLACE_WORDS) + ["north", "south", "east", "west", "ne", "sw"]
    ms = []
    stuck_events = []
    gave_up = 0
    short = 0
    arrivals = 0
    in_water_max = 0
    n_frames = int(300 * FPS)
    for i in range(n_frames):
        th += DT
        if i % int(FPS) == 0:                             # every second two pips get a random `go`
            for _ in range(2):
                k = "test-pip-%02d" % int(rng.integers(60))
                if bh.get(k).state != "walking":
                    w = targets[int(rng.integers(len(targets)))]
                    bh.go(k, w, th)
        t0 = _time.perf_counter()
        evs = bh.tick(th, DT)
        ms.append((_time.perf_counter() - t0) * 1000.0)
        for ev in evs:
            if ev["type"] == "stuck":
                stuck_events.append(ev)
            elif ev["type"] == "arrive":
                arrivals += 1
                gave_up += 1 if ev.get("gave_up") else 0
                short += 1 if ev.get("short") else 0
        if i % 30 == 0:
            in_water_max = max(in_water_max, bh.in_water_count())
    twice = [e for e in bh.entities.values() if e.stuck_total >= 2]
    arr = np.array(ms)
    print("[pathing] 60 pips x 300 s: arrivals %d (short %d: stopped on a bank, target across water), stuck events %d (pips stuck twice: %d), gave_up %d, coarse routes %d, local paths %d, in_water max %d" % (
        arrivals, short, len(stuck_events), len(twice), gave_up, bh.stats_routes, bh.stats_local, in_water_max))
    print("[timing] behaviour.tick 60 pips: avg %.3f ms · p95 %.3f · max %.3f (n=%d)" % (arr.mean(), np.percentile(arr, 95), arr.max(), len(arr)))
    check("pathing: zero in-water positions over 5 min", in_water_max == 0)
    check("pathing: the 3 s detector never fired twice on one pip", len(twice) == 0, "%d stuck events total" % len(stuck_events))
    check("pathing: hundreds of arrivals, none given up", arrivals > 200 and gave_up == 0, "arrivals %d gave_up %d" % (arrivals, gave_up))
    check("timing: tick avg < 1.0 ms at 60 pips", arr.mean() < 1.0, "%.3f ms" % arr.mean())
    far = max(math.hypot(e.x - moot[0], e.y - moot[1]) for e in bh.entities.values())
    print("[gravity] farthest pip from the Moot after 5 min: %.0f cells (idle cap %d; go targets may be farther)" % (far, IDLE_RADIUS))
    # idle-only gravity: no go commands, 60 pips wander 3 min
    bg = Behaviour(seed=12, hold_s=3.0, terrain=T, moot=moot)
    tg = now
    for i in range(60):
        k = "test-pip-%02d" % i
        bg.seed_drop(k, tg - 10, origin="test")
        bg.hold_cleared(k, tg - 10, "t%d" % i, 0, 0.6, 0, True)
    for i in range(int(180 * FPS)):
        tg += DT
        bg.tick(tg, DT)
    far_idle = max(math.hypot(e.x - moot[0], e.y - moot[1]) for e in bg.entities.values())
    check("idle wander stays within 200 cells of the Moot", far_idle <= IDLE_RADIUS + 2, "%.0f cells" % far_idle)
    print("[frames] sample:", sorted({e.frame_name(tg) for e in bg.entities.values()}))
    check("every frame name is in the atlas set", all(e.frame_name(tg) in FRAMES for e in bg.entities.values()))
    print("[states] STATES / ON_LAND / HIDDEN_STATES:", STATES, ON_LAND, HIDDEN_STATES)
    check("nobody lies down: no hatched pip ever draws the lying pose unless hidden",
          all(e.frame_name(tg) != "sleep" for e in bg.entities.values()) and all(e.frame_name(th) != "sleep" for e in bh.entities.values()))
    print("[legacy] AWAKE_STATES (= ON_LAND) / WANDER_X / PLATFORM_LETTERS exported:", AWAKE_STATES, WANDER_X, PLATFORM_LETTERS)
    # --- gather_to (the bonfire / gathering card, AGES 1.3): moves an AWAY body without a record; a voter keeps its stone
    for e in bg.entities.values():
        e.last_active_t = tg - bg.present_s - 30.0                  # everyone away
    bg.tick(tg, DT)
    ga = bg.entities["test-pip-00"]
    la0 = ga.last_active_t
    ok_g = bg.gather_to(ga.key, moot, tg)
    check("gather_to walks an away settler toward the Moot with then='gather' (no record: last_active_t untouched, still away)",
          ok_g and ga.state == "walking" and ga.then == "gather" and ga.last_active_t == la0 and not ga.is_present(tg),
          "ok=%s state=%s then=%s present=%s" % (ok_g, ga.state, ga.then, ga.is_present(tg)))
    ev_g = bg.tick(tg + DT, DT)
    wg = [ev for ev in ev_g if ev.get("type") == "walk" and ev.get("pip") == ga.key]
    check("gather walk event carries then='gather' and a cell pair, never a place label",
          len(wg) == 1 and wg[0].get("then") == "gather" and isinstance(wg[0].get("to"), list), str(wg))
    gv = bg.entities["test-pip-01"]
    gv.last_active_t = tg
    bg.walk_to(gv.key, "A", tg)
    check("gather_to refuses a voter on its way to / standing at a stone (a vote is the person's)", not bg.gather_to(gv.key, moot, tg) and gv.then == "vote", "then=%s" % gv.then)
    print("RESULT:", "PASS" if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":   # pragma: no cover
    sys.exit(_selftest(os.environ.get("RUN_DIR") or "/tmp/lg-behaviour"))
