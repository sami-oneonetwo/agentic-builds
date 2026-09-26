"""stream/world/camera.py - the LONGGRASS camera (OPENWORLD.md 4.3-4.5): a float centre in cells, three zooms as crop
sizes, five modes evaluated in priority order, a critically damped spring under a hard pan cap, never a cut.

    from stream.world.camera import Camera
    cam = Camera()                                   # map 960x440 cells, window 320x110 at 1x, 12-cell edge clamp
    cam.resume(land.camera())                        # world.json["camera"] -> no jump on a hot-reload (None = snap to the Moot)
    cam.update(now, dt,                              # once per frame, ctx.now only; pure function of state + inputs
               awake=[{"key": "sami", "x": 480, "y": 220, "fx": 1, "fy": 0, "walking": True, "spoke_t": now - 3}],
               seeds=[(x, y)],                        # pending nameless tufts (no key, no name)
               events=[{"type": "hatch", "x": x, "y": y}],   # this frame's camera-worthy events (seed_land, hatch, wake, camp, ...)
               moot={"stones": [(x, y), (x, y), (x, y)], "voters": ["sami"], "walking_to_stone": False, "round_remaining": 25},
               stops=land.survey_stops(natural))     # DRIFT survey targets: real marks + the three natural points
    cam.mode ; cam.cx, cam.cy ; cam.zoom             # "DRIFT" ...; centre in cells; 0.75 / 1.0 / 1.5
    cam.view_rect()          -> (x0, y0, w, h) in cells (floats; the window the scene shows)
    cam.bake_crop(ppc=4)     -> (px0, py0, pw, ph) integer pixels on the 4 px/cell bake (1707x587 / 1280x440 / 853x293)
    cam.sim_to_screen(x, y, size=(1280, 440)) -> (sx, sy) or None when off-view
    cam.zoom_blend(now)      -> (zoom_from, zoom_to, alpha 0..1): alpha < 1 during the 12-frame crossfade
    cam.edge_arrows(size)    -> [{"key", "x", "y", "side", "sx", "sy", "dist"}] awake pips outside the window
    cam.drift_stop           -> the survey stop in view during DRIFT ({"kind", "owner", "x", "y"}) for the plank copy
    cam.minimap(size=(144, 66)) -> {"scale", "view": (x, y, w, h) px, "to_px": callable}   geometry for the minimap
    cam.to_dict() ; cam.maybe_persist(land, now)     # {x, y, zoom, mode, saved_ts} into world.json every 5 s

Motion rules (4.4): critically damped spring, 0.8 s time constant, pan speed capped at 60 cells/s and enforced on the
displacement itself (so no input can ever produce a cut: the only cut is the first frame of a session, `snap()`);
a 1.5 s / 10-cell dead zone so a wandering pip is not chased; zoom changes only when the pan speed is under
2 cells/s and 20 s after the last change, as a 12-frame crossfade; a 12-cell clamp keeps the map edge off screen.
Modes in priority order: EVENT (hold 4 s) > MOOT (last 30 s of a round with anyone at a waystone) > FOLLOW (weighted
mean of awake pips with two-axis lead room) > CLOSE (one slow pip, 1.5x) > DRIFT (a 4 cells/s survey over real marks
and three natural points, 20 s dwell at a camp, 12 s elsewhere, no repeat inside 10 min). Honesty: FOLLOW needs a real
entity; DRIFT visits only real marks and fixed natural points; the camera never writes wear or marks.
Python 3.9, stdlib + math only; nothing here reads time.time().
"""
from __future__ import annotations

import math
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stream.world.land import MAP_W, MAP_H, EDGE_MARGIN, DEFAULT_MOOT  # noqa: E402

# ---------------------------------------------------------------------------- constants (4.3, 4.4)
PPC = 4                                                   # bake pixels per cell at 1x
ZOOMS = (0.75, 1.0, 1.5)
CROP_PX = {0.75: (1707, 587), 1.0: (1280, 440), 1.5: (853, 293)}   # crop of the 4 px/cell bake per zoom
WINDOW = {z: (CROP_PX[z][0] / float(PPC), CROP_PX[z][1] / float(PPC)) for z in ZOOMS}   # window in cells
SCREEN = (1280, 440)
MODES = ("EVENT", "MOOT", "FOLLOW", "CLOSE", "DRIFT")

SPRING_TAU_S = 0.8            # time constant; omega = 2 / tau gives ~1.5 s to settle within 10 %
PAN_CAP = 60.0                # cells/s, enforced on the per-frame displacement
DEAD_ZONE_S = 1.5             # a small retarget must persist this long before the camera follows it
DEAD_ZONE_CELLS = 10.0        # ... unless the retarget is bigger than this
DEAD_ZONE_MIN = 2.0           # below this the retarget is ignored altogether
ZOOM_REST_SPEED = 2.0         # cells/s: zoom only at rest
ZOOM_MIN_GAP_S = 20.0
ZOOM_FADE_S = 12 / 30.0       # 12 frames
LEAD_FRAC = 0.15              # lead room: the target sits 15 % of the window ahead of the newest mover
LEAD_HOLD_S = 2.0             # the lead offset flips only after the facing has held this long
EVENT_HOLD_S = 4.0
HATCH_CLOSE_S = 3.0
EVENT_TYPES = ("seed_land", "seed", "hatch", "wake", "camp", "camp_raised", "raising", "raising_ship", "land_open", "cairn_named")
MOOT_LAST_S = 30.0
MOOT_RADIUS = 120.0
FOLLOW_MARGIN = 24.0          # cells around the group's bounding box (x)
FOLLOW_MARGIN_Y = 12.0        # cells above / below the group inside the SAFE band (a settler stands ~10 cells tall)
# The HUD lives in the world region: plank rows + land line + dial rows fill the top 152 px (x 0-700), the minimap the
# top-right 176x132 px, the place label the bottom 44 px. People framed under those chips read as "HUD stacks over
# settlers" (owner verdict, journal 023 handoff), so every people-framing mode centres its target in the SAFE band
# between them: the desired centre is lifted by half the difference so the group sits at region y ~274, not 220.
HUD_TOP_PX = 152
HUD_BOTTOM_PX = 44
HUD_LEFT_W = 700              # the top-left stack's x extent (the panel refreshes `hud_boxes` from what it actually drew)
HUD_RIGHT_BOX = (1104, 0, 1280, 132)
HUD_BOXES_DEFAULT = ((0, 0, HUD_LEFT_W, HUD_TOP_PX), HUD_RIGHT_BOX)
HEAD_CELLS = 20.0             # a settler's head top above its feet cell (creatures tier 3 drawn at 1.2x: anchor 79 px = 20 cells at 1x)
STONE_TOP_CELLS = 36.0        # a waystone's letter + count + option row stack above the stone cell (~144 px at 1x)
HUD_NUDGE_PAD_PX = 32.0       # the spring lags a walker by ~0.8 s (6 cells at 8 cells/s): the lift starts this early
WIDE_HYSTERESIS = 1.25        # to come back from 0.75x the group must fit 1x with a 25 % bigger margin
CLUSTER_LINK = 60.0
CLOSE_MOVE_CELLS = 40.0
CLOSE_WINDOW_S = 30.0
DRIFT_SPEED = 4.0             # cells/s (16 screen px/s at 1x)
DRIFT_DWELL_CAMP_S = 20.0
DRIFT_DWELL_OTHER_S = 12.0
DRIFT_REPEAT_S = 600.0        # never repeats a route inside 10 min
PERSIST_S = 5.0
WEIGHT_SPOKE, WEIGHT_WALK, WEIGHT_SEED, WEIGHT_IDLE, SPOKE_WINDOW_S = 3.0, 2.0, 2.0, 1.0, 10.0


def _hyp(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def _top(a: Dict[str, Any]) -> float:
    """Cells from a pip's feet to its head top: the scene's per-tier `top` when it gives one, else the tier-3 bound."""
    try:
        t = a.get("top")
        return float(t) if t else HEAD_CELLS
    except (TypeError, ValueError):
        return HEAD_CELLS


def _spring_step(x: float, v: float, target: float, dt: float, omega: float) -> Tuple[float, float]:
    """One implicit step of a critically damped spring (stable for any dt)."""
    f = 1.0 + 2.0 * dt * omega
    oo = omega * omega
    hoo = dt * oo
    hhoo = dt * hoo
    det_inv = 1.0 / (f + hhoo)
    det_x = f * x + dt * v + hhoo * target
    det_v = v + hoo * (target - x)
    return det_x * det_inv, det_v * det_inv


class Camera(object):
    """The camera state machine. All coordinates are map cells (floats). `update()` is the only mutator per frame."""

    def __init__(self, map_w: int = MAP_W, map_h: int = MAP_H, margin: int = EDGE_MARGIN, zoom: float = 1.0,
                 allow_zoom: bool = True, moot: Tuple[float, float] = DEFAULT_MOOT, tau_s: float = SPRING_TAU_S,
                 pan_cap: float = PAN_CAP):
        self.map_w, self.map_h, self.margin = int(map_w), int(map_h), int(margin)
        self.moot = (float(moot[0]), float(moot[1]))
        self.allow_zoom = bool(allow_zoom)        # False pins 1x (v0 preview, the degrade ladder's > 28 ms rung)
        self.omega = 2.0 / float(tau_s)
        self.pan_cap = float(pan_cap)
        self.cx, self.cy = self.moot
        self.vx = self.vy = 0.0
        self.zoom = zoom if zoom in ZOOMS else 1.0
        self.zoom_prev = self.zoom
        self.zoom_change_t: Optional[float] = None
        self.mode = "DRIFT"
        self.target = self.moot                    # the committed spring target
        self.desired = self.moot                   # this frame's raw wish (before the dead zone)
        # the HUD as a camera dead zone (journal 021 / 023 verdicts: chips never stack over people): boxes in region px,
        # refreshed every frame by the world panel from the chips it actually drew; `_nudge_pts` are the points the
        # chosen mode is framing with the height of what stands on them, `hud_nudge` the cells the target was pushed
        self.hud_boxes: List[Tuple[int, int, int, int]] = [tuple(b) for b in HUD_BOXES_DEFAULT]
        self._nudge_pts: List[Tuple[float, float, float]] = []
        self.hud_nudge = 0.0
        self.target_zoom = self.zoom
        self._dz_since: Optional[float] = None
        # lead room
        self._lead = (0.0, 0.0)
        self._lead_cand = (0.0, 0.0)
        self._lead_cand_since: Optional[float] = None
        # events
        self._event: Optional[Dict[str, Any]] = None
        self._event_t: Optional[float] = None
        # per-pip movement history for CLOSE
        self._hist: Dict[str, List[Tuple[float, float, float]]] = {}
        # drift
        self._drift_stop: Optional[Dict[str, Any]] = None
        self._drift_pt: Optional[Tuple[float, float]] = None
        self._drift_arrived_t: Optional[float] = None
        self._drift_visited: Dict[str, float] = {}
        # bookkeeping
        self.last_t: Optional[float] = None
        self.speed = 0.0
        self.max_step_speed = 0.0                  # the largest displacement/dt ever applied (test evidence)
        self.cuts = 0                              # snaps after the first frame (must stay 0 on air)
        self._persist_t: Optional[float] = None
        self._awake_cache: List[Dict[str, Any]] = []
        self._clamp_pos()

    # ------------------------------------------------------------------ geometry
    def window(self, zoom: Optional[float] = None) -> Tuple[float, float]:
        return WINDOW[zoom if zoom in ZOOMS else self.zoom]

    def _clamp_xy(self, x: float, y: float, zoom: Optional[float] = None) -> Tuple[float, float]:
        w, h = self.window(zoom)
        lo_x, hi_x = self.margin + w / 2.0, self.map_w - self.margin - w / 2.0
        lo_y, hi_y = self.margin + h / 2.0, self.map_h - self.margin - h / 2.0
        if hi_x < lo_x:
            lo_x = hi_x = self.map_w / 2.0
        if hi_y < lo_y:
            lo_y = hi_y = self.map_h / 2.0
        return min(hi_x, max(lo_x, x)), min(hi_y, max(lo_y, y))

    def _clamp_pos(self) -> None:
        self.cx, self.cy = self._clamp_xy(self.cx, self.cy)

    def view_rect(self, zoom: Optional[float] = None) -> Tuple[float, float, float, float]:
        """(x0, y0, w, h) in cells of the window the scene shows (for `zoom`, default the current one)."""
        w, h = self.window(zoom)
        return self.cx - w / 2.0, self.cy - h / 2.0, w, h

    def bake_crop(self, ppc: int = PPC, zoom: Optional[float] = None) -> Tuple[int, int, int, int]:
        """Integer pixel rect on the ppc px/cell bake: panning is in whole bake pixels (4.3)."""
        z = zoom if zoom in ZOOMS else self.zoom
        pw, ph = CROP_PX[z]
        if ppc != PPC:
            pw, ph = int(round(pw * ppc / float(PPC))), int(round(ph * ppc / float(PPC)))
        x0, y0, w, h = self.view_rect(z)
        px0 = int(round(x0 * ppc))
        py0 = int(round(y0 * ppc))
        px0 = max(0, min(self.map_w * ppc - pw, px0))
        py0 = max(0, min(self.map_h * ppc - ph, py0))
        return px0, py0, pw, ph

    def scale(self, size: Tuple[int, int] = SCREEN, zoom: Optional[float] = None) -> float:
        """Screen px per cell (4 x zoom at 1280 wide)."""
        w, _ = self.window(zoom)
        return size[0] / w

    def sim_to_screen(self, x: float, y: float, size: Tuple[int, int] = SCREEN, margin_px: float = 0.0,
                      zoom: Optional[float] = None) -> Optional[Tuple[float, float]]:
        """Cells -> screen px inside the world region; None when outside the window (plus `margin_px`)."""
        x0, y0, w, h = self.view_rect(zoom)
        s = size[0] / w
        sx, sy = (x - x0) * s, (y - y0) * s
        if sx < -margin_px or sy < -margin_px or sx > size[0] + margin_px or sy > size[1] + margin_px:
            return None
        return sx, sy

    def screen_to_sim(self, sx: float, sy: float, size: Tuple[int, int] = SCREEN) -> Tuple[float, float]:
        x0, y0, w, h = self.view_rect()
        s = size[0] / w
        return x0 + sx / s, y0 + sy / s

    def in_view(self, x: float, y: float, pad: float = 0.0) -> bool:
        x0, y0, w, h = self.view_rect()
        return (x0 - pad) <= x <= (x0 + w + pad) and (y0 - pad) <= y <= (y0 + h + pad)

    def zoom_blend(self, now: float) -> Tuple[float, float, float]:
        """(zoom_from, zoom_to, alpha): alpha < 1 for ZOOM_FADE_S after a zoom change (the crossfade / luminance dip)."""
        if self.zoom_change_t is None or self.zoom_prev == self.zoom:
            return self.zoom, self.zoom, 1.0
        a = (now - self.zoom_change_t) / ZOOM_FADE_S
        return self.zoom_prev, self.zoom, max(0.0, min(1.0, a))

    # ------------------------------------------------------------------ persistence (4.4: every 5 s)
    def to_dict(self, now: Optional[float] = None) -> Dict[str, Any]:
        return {"x": round(self.cx, 2), "y": round(self.cy, 2), "zoom": self.zoom, "mode": self.mode,
                "saved_ts": now, "drift_stop": (self._drift_stop or {}).get("id")}

    def resume(self, d: Optional[Dict[str, Any]]) -> bool:
        """Adopt a persisted position (the hot-reload path): the frame continues where the old scene left it. With
        None the camera snaps to the Moot (the one allowed cut: the first frame of a session)."""
        if isinstance(d, dict) and d.get("x") is not None and d.get("y") is not None:
            z = d.get("zoom") if d.get("zoom") in ZOOMS else 1.0
            self.zoom = self.zoom_prev = z if self.allow_zoom else 1.0
            self.snap(float(d["x"]), float(d["y"]), first=True)
            self.mode = d.get("mode") if d.get("mode") in MODES else "DRIFT"
            return True
        self.snap(self.moot[0], self.moot[1], first=True)
        return False

    def snap(self, x: float, y: float, first: bool = True) -> None:
        """Place the camera instantly. Only legal as the first frame of a session (`first=True`); any later snap is
        counted in `cuts` so a test can assert it never happened."""
        if not first:
            self.cuts += 1
        self.cx, self.cy = self._clamp_xy(x, y)
        self.vx = self.vy = 0.0
        self.target = self.desired = (self.cx, self.cy)

    def maybe_persist(self, land, now: float) -> bool:
        if self._persist_t is not None and now - self._persist_t < PERSIST_S:
            return False
        self._persist_t = now
        try:
            land.save_camera(self.to_dict(now))
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ the per-frame update
    def update(self, now: float, dt: float, awake: Optional[Sequence[Dict[str, Any]]] = None,
               seeds: Optional[Sequence[Tuple[float, float]]] = None, events: Optional[Sequence[Dict[str, Any]]] = None,
               moot: Optional[Dict[str, Any]] = None, stops: Optional[Sequence[Dict[str, Any]]] = None,
               lead_key: Optional[str] = None) -> "Camera":
        """Evaluate the mode ladder, move the spring under the cap, settle zoom. `awake` items: key, x, y, fx, fy,
        walking (bool), spoke_t (epoch of the last message or None). Returns self."""
        dt = max(1e-3, min(0.25, float(dt)))
        awake = [a for a in (awake or []) if a.get("x") is not None and a.get("y") is not None]
        seeds = [s for s in (seeds or []) if s is not None]
        self._awake_cache = awake
        self._track_history(now, awake)
        for ev in events or []:
            if ev.get("type") in EVENT_TYPES and ev.get("x") is not None and ev.get("y") is not None:
                self._event, self._event_t = dict(ev), now

        self._nudge_pts = []
        mode, desired, want_zoom = self._choose(now, awake, seeds, moot, stops, lead_key)
        self.mode = mode
        z_eff = want_zoom if self.allow_zoom else 1.0
        # the SAFE band: whatever the mode framed sits between the HUD chips and the place label, never under them
        self.desired = self._clamp_xy(desired[0], desired[1] - self.safe_dy(z_eff), z_eff)
        self._apply_dead_zone(now, mode)
        self._hud_dead_zone(z_eff)
        self._settle_zoom(now, want_zoom)
        self._move(dt)
        self.last_t = now
        return self

    # ------------------------------------------------------------------ the safe band (HUD avoidance)
    def _hud_dead_zone(self, zoom: float) -> None:
        """Treat the HUD chips as a dead zone for people: with the target as it stands, project every framed point's
        top (feet minus the head height; a stone minus its letter stack) and, if one would land under a top HUD box,
        lift the target (camera centre up = sprites down) by the cells needed. Capped so the lowest feet stay inside
        the region. A pure function of the target, so it re-applies every frame and the spring smooths it."""
        pts = self._nudge_pts
        self.hud_nudge = 0.0
        if not pts:
            return
        z = zoom if zoom in ZOOMS else 1.0
        w, h = self.window(z)
        s = SCREEN[0] / w
        tx, ty = self._clamp_xy(self.target[0], self.target[1], z)
        x0, y0 = tx - w / 2.0, ty - h / 2.0
        need = 0.0
        for x, y, top in pts:
            sx = (x - x0) * s
            sy_top = (y - top - y0) * s
            for bx0, by0, bx1, by1 in self.hud_boxes:
                if by0 > 0 or by1 <= 0:
                    continue                                   # only the boxes hanging from the region's top edge
                if bx0 - 24 <= sx <= bx1 + 24 and sy_top < by1 + HUD_NUDGE_PAD_PX:
                    need = max(need, (by1 + HUD_NUDGE_PAD_PX - sy_top) / s)
        if need <= 0.0:
            return
        low = max(y for _, y, _ in pts)
        room = (SCREEN[1] - HUD_BOTTOM_PX) / s - (low - y0)     # cells the lowest feet may still drop before the bottom band
        need = min(need, max(0.0, room))
        if need <= 0.0:
            return
        self.hud_nudge = need
        self.target = self._clamp_xy(tx, ty - need, z)

    @staticmethod
    def safe_dy(zoom: float) -> float:
        """Cells the camera centre is lifted so the framed point lands in the middle of the band the HUD leaves free
        (region y HUD_TOP_PX .. SCREEN_H - HUD_BOTTOM_PX): (152 - 44) / 2 = 54 px above the window centre."""
        z = zoom if zoom in ZOOMS else 1.0
        return (HUD_TOP_PX - HUD_BOTTOM_PX) / 2.0 / (PPC * z)

    @staticmethod
    def safe_h(zoom: float) -> float:
        """The safe band's height in cells at this zoom (the vertical room a framed group may use)."""
        z = zoom if zoom in ZOOMS else 1.0
        return WINDOW[z][1] - (HUD_TOP_PX + HUD_BOTTOM_PX) / float(PPC * z)

    # ------------------------------------------------------------------ mode ladder (4.4 table)
    def _choose(self, now, awake, seeds, moot, stops, lead_key) -> Tuple[str, Tuple[float, float], float]:
        # 1. EVENT: that point, hold 4 s, 1x (1.5x for a 3 s hatch close-up when only one pip is awake)
        if self._event is not None and self._event_t is not None:
            age = now - self._event_t
            if age <= EVENT_HOLD_S:
                z = 1.0
                if self._event.get("type") == "hatch" and len(awake) == 1 and age <= HATCH_CLOSE_S:
                    z = 1.5
                ex, ey = float(self._event["x"]), float(self._event["y"])
                hw, hh = WINDOW[1.0][0] / 2.0, self.safe_h(1.0) / 2.0
                self._nudge_pts = [(ex, ey, HEAD_CELLS)]       # the event is the subject; only people who can share its frame count
                self._nudge_pts += [(float(a["x"]), float(a["y"]), _top(a)) for a in awake
                                    if abs(float(a["x"]) - ex) <= hw and abs(float(a["y"]) - ey) <= hh]
                return "EVENT", (float(self._event["x"]), float(self._event["y"])), z
            self._event = None
        # 2. MOOT: last 30 s with anyone standing at a waystone, or any pip walking to one
        if moot and moot.get("stones"):
            rem = moot.get("round_remaining")
            standing = bool(moot.get("voters"))
            walking = bool(moot.get("walking_to_stone"))
            if walking or (standing and rem is not None and 0 <= float(rem) <= MOOT_LAST_S):
                pts = [(float(x), float(y)) for x, y in moot["stones"]]
                mx = sum(p[0] for p in pts) / len(pts)
                my = sum(p[1] for p in pts) / len(pts)
                near = [(float(a["x"]), float(a["y"])) for a in awake if _hyp(a["x"], a["y"], mx, my) <= MOOT_RADIUS]
                self._nudge_pts = [(x, y, STONE_TOP_CELLS) for x, y in pts]
                self._nudge_pts += [(float(a["x"]), float(a["y"]), _top(a)) for a in awake if _hyp(a["x"], a["y"], mx, my) <= MOOT_RADIUS]
                pts += near
                c, z = self._frame_points(pts)
                return "MOOT", c, z
        # 3 / 4. FOLLOW / CLOSE: a real entity is required
        if awake or seeds:
            # the waystones' letter stacks join the dead-zone points whenever anyone stands at or walks to a stone (a
            # 180 s round has voters standing long before the MOOT window opens): their letters must not be culled
            # under the HUD chips while people are reading them
            stones_top: List[Tuple[float, float, float]] = []
            if moot and moot.get("stones") and (moot.get("voters") or moot.get("walking_to_stone")):
                stones_top = [(float(x), float(y), STONE_TOP_CELLS) for x, y in moot["stones"]]
            if len(awake) == 1 and not seeds and self._slow(awake[0], now):
                a = awake[0]
                lead = self._lead_room(now, a, 1.5)
                self._nudge_pts = [(float(a["x"]), float(a["y"]), _top(a))] + stones_top
                return "CLOSE", (float(a["x"]) + lead[0], float(a["y"]) + lead[1]), 1.5
            self._drift_stop, self._drift_pt, self._drift_arrived_t = None, None, None
            out = self._follow(now, awake, seeds, lead_key)
            self._nudge_pts += stones_top
            return out
        # 5. DRIFT
        return self._drift(now, stops or [])

    def _follow(self, now, awake, seeds, lead_key) -> Tuple[str, Tuple[float, float], float]:
        pts: List[Tuple[float, float, float]] = []
        for a in awake:
            w = WEIGHT_IDLE
            st = a.get("spoke_t")
            if st is not None and now - float(st) <= SPOKE_WINDOW_S:
                w = WEIGHT_SPOKE
            elif a.get("walking"):
                w = WEIGHT_WALK
            pts.append((float(a["x"]), float(a["y"]), w))
        for x, y in seeds:
            pts.append((float(x), float(y), WEIGHT_SEED))
        # zoom by bounding box; if the group does not fit at 0.75x, follow the last speaker's cluster
        group = pts
        c, z = self._frame_points([(x, y) for x, y, _ in group])
        if z is None:
            anchor = self._newest(awake, lead_key) or (awake[0] if awake else None)
            ax, ay = (float(anchor["x"]), float(anchor["y"])) if anchor else (pts[0][0], pts[0][1])
            group = self._cluster(pts, ax, ay)
            c, z = self._frame_points([(x, y) for x, y, _ in group])
            if z is None:
                z = 0.75
        tw = sum(w for _, _, w in group) or 1.0
        mx = sum(x * w for x, _, w in group) / tw
        my = sum(y * w for _, y, w in group) / tw
        mover = self._newest(awake, lead_key)
        lead = self._lead_room(now, mover, z) if mover is not None else (0.0, 0.0)
        cx_, cy_ = mx + lead[0], my + lead[1]
        # every awake person who will be ON SCREEN is a dead-zone point, not only the followed cluster: when two pips
        # stand too far apart for the safe band (zoom pinned at 1x), the unframed one still walked under the plank rows
        # (camera run frames 1200 / 1833); the lift is capped so the followed feet stay above the bottom band
        ww, wh = self.window(z if self.allow_zoom else 1.0)
        self._nudge_pts = [(float(a["x"]), float(a["y"]), _top(a)) for a in awake
                           if abs(float(a["x"]) - cx_) <= ww / 2.0 + 4 and abs(float(a["y"]) - cy_) <= wh / 2.0 + 4]
        for x, y in seeds:
            self._nudge_pts.append((float(x), float(y), HEAD_CELLS))
        return "FOLLOW", (cx_, cy_), z

    def _newest(self, awake, lead_key) -> Optional[Dict[str, Any]]:
        if lead_key:
            for a in awake:
                if a.get("key") == lead_key:
                    return a
        walkers = [a for a in awake if a.get("walking")]
        pool = walkers or list(awake)
        if not pool:
            return None
        return max(pool, key=lambda a: (float(a.get("spoke_t") or 0.0), str(a.get("key") or "")))

    def _lead_room(self, now, a, zoom) -> Tuple[float, float]:
        """Two-axis lead room: 15 % of the window ahead of the newest mover's facing; the offset flips only after the
        facing has held 2 s (so a pip turning on the spot does not swing the frame)."""
        fx, fy = float(a.get("fx") or 0.0), float(a.get("fy") or 0.0)
        n = math.hypot(fx, fy)
        cand = (fx / n, fy / n) if n > 1e-6 else self._lead
        if cand != self._lead_cand:
            self._lead_cand, self._lead_cand_since = cand, now
        elif self._lead_cand_since is not None and now - self._lead_cand_since >= LEAD_HOLD_S:
            self._lead = cand
        if self._lead == (0.0, 0.0) and self._lead_cand_since is not None and self._lead_cand_since == now:
            self._lead = cand                      # the very first facing needs no hold
        w, h = self.window(zoom if self.allow_zoom else 1.0)
        return self._lead[0] * LEAD_FRAC * w, self._lead[1] * LEAD_FRAC * h

    def _frame_points(self, pts: Sequence[Tuple[float, float]]) -> Tuple[Tuple[float, float], Optional[float]]:
        """Centre of the points' bounding box and the zoom that fits it with a 24-cell margin (None: not even 0.75x)."""
        if not pts:
            return (self.cx, self.cy), 1.0
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        bw, bh = (max(xs) - min(xs)) + 2 * FOLLOW_MARGIN, (max(ys) - min(ys)) + 2 * FOLLOW_MARGIN_Y
        c = ((max(xs) + min(xs)) / 2.0, (max(ys) + min(ys)) / 2.0)
        w1, h1 = WINDOW[1.0][0], self.safe_h(1.0)          # the group must fit the SAFE band, not the whole window
        hyst = WIDE_HYSTERESIS if self.zoom == 0.75 else 1.0
        if bw * hyst <= w1 and bh * hyst <= h1:
            return c, 1.0
        w0, h0 = WINDOW[0.75][0], self.safe_h(0.75)
        if bw <= w0 and bh <= h0:
            return c, 0.75
        return c, None

    @staticmethod
    def _cluster(pts, ax, ay):
        """The connected cluster (link radius 60 cells) containing the anchor point."""
        rest = list(pts)
        out: List[Tuple[float, float, float]] = []
        frontier = [(ax, ay)]
        while frontier:
            fx, fy = frontier.pop()
            keep = []
            for p in rest:
                if _hyp(p[0], p[1], fx, fy) <= CLUSTER_LINK:
                    out.append(p)
                    frontier.append((p[0], p[1]))
                else:
                    keep.append(p)
            rest = keep
        return out or list(pts)

    def _track_history(self, now, awake) -> None:
        keys = set()
        for a in awake:
            k = a.get("key")
            if not k:
                continue
            keys.add(k)
            h = self._hist.setdefault(k, [])
            if not h or now - h[-1][0] >= 1.0:
                h.append((now, float(a["x"]), float(a["y"])))
            while len(h) > 1 and now - h[0][0] > CLOSE_WINDOW_S + 1.0:
                h.pop(0)
        for k in list(self._hist.keys()):
            if k not in keys:
                del self._hist[k]

    def _slow(self, a, now) -> bool:
        """CLOSE trigger: this pip has moved < 40 cells over the last 30 s (and has been watched that long)."""
        h = self._hist.get(a.get("key") or "")
        if not h or now - h[0][0] < CLOSE_WINDOW_S - 1.0:
            return False
        moved = 0.0
        for (t0, x0, y0), (t1, x1, y1) in zip(h, h[1:]):
            moved += _hyp(x0, y0, x1, y1)
        moved += _hyp(h[-1][1], h[-1][2], float(a["x"]), float(a["y"]))
        return moved < CLOSE_MOVE_CELLS

    # ------------------------------------------------------------------ DRIFT (0 awake, no seed)
    @property
    def drift_stop(self) -> Optional[Dict[str, Any]]:
        return self._drift_stop if self.mode == "DRIFT" else None

    def _drift(self, now, stops) -> Tuple[str, Tuple[float, float], float]:
        stops = [s for s in stops if s.get("x") is not None and s.get("y") is not None]
        if not stops:
            self._drift_stop = None
            return "DRIFT", self.moot, 1.0
        ids = {s["id"] for s in stops}
        if self._drift_stop is not None and self._drift_stop.get("id") not in ids:
            self._drift_stop, self._drift_pt, self._drift_arrived_t = None, None, None
        framed = (self.cx, self.cy + self.safe_dy(self.zoom))    # the point now sitting in the safe band's centre
        if self._drift_stop is None:
            self._drift_stop = self._pick_stop(now, stops)
            self._drift_pt = framed
            self._drift_arrived_t = None
        s = self._drift_stop
        sx, sy = float(s["x"]), float(s["y"])
        if self._drift_pt is None:
            self._drift_pt = framed
        px, py = self._drift_pt
        d = _hyp(px, py, sx, sy)
        step = DRIFT_SPEED * (now - self.last_t if self.last_t is not None else 1 / 30.0)
        if d <= max(step, 1.5):
            self._drift_pt = (sx, sy)
            if self._drift_arrived_t is None:
                self._drift_arrived_t = now
                self._drift_visited[s["id"]] = now
            dwell = DRIFT_DWELL_CAMP_S if s.get("kind") == "camp" else DRIFT_DWELL_OTHER_S
            if now - self._drift_arrived_t >= dwell:
                nxt = self._pick_stop(now, stops, exclude=s["id"])
                if nxt is not None and nxt["id"] != s["id"]:
                    self._drift_stop, self._drift_arrived_t = nxt, None
        else:
            self._drift_pt = (px + (sx - px) / d * step, py + (sy - py) / d * step)
        return "DRIFT", self._drift_pt, 1.0

    def _pick_stop(self, now, stops, exclude: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Nearest stop not visited inside 10 min (route never repeats early); if all were, the least recent."""
        cands = [s for s in stops if s.get("id") != exclude] or list(stops)
        if not cands:
            return None
        fresh = [s for s in cands if now - self._drift_visited.get(s["id"], -1e12) >= DRIFT_REPEAT_S]
        if fresh:
            return min(fresh, key=lambda s: (_hyp(self.cx, self.cy, float(s["x"]), float(s["y"])), s["id"]))
        return min(cands, key=lambda s: (self._drift_visited.get(s["id"], -1e12), s["id"]))

    # ------------------------------------------------------------------ dead zone, zoom, motion
    def _apply_dead_zone(self, now, mode) -> None:
        """Commit `desired` as the spring target at once when it moved > 10 cells or the mode is EVENT / MOOT / DRIFT
        (a moving survey point); a 2-10 cell wish must persist 1.5 s; under 2 cells is ignored."""
        d = _hyp(self.desired[0], self.desired[1], self.target[0], self.target[1])
        if mode in ("EVENT", "MOOT", "DRIFT") or d > DEAD_ZONE_CELLS:
            self.target, self._dz_since = self.desired, None
            return
        if d < DEAD_ZONE_MIN:
            self._dz_since = None
            return
        if self._dz_since is None:
            self._dz_since = now
        elif now - self._dz_since >= DEAD_ZONE_S:
            self.target, self._dz_since = self.desired, None

    def _settle_zoom(self, now, want: float) -> None:
        want = want if want in ZOOMS else 1.0
        if not self.allow_zoom:
            want = 1.0
        self.target_zoom = want
        if want == self.zoom:
            return
        if self.speed > ZOOM_REST_SPEED:
            return
        if self.zoom_change_t is not None and now - self.zoom_change_t < ZOOM_MIN_GAP_S:
            return
        self.zoom_prev, self.zoom, self.zoom_change_t = self.zoom, want, now
        self._clamp_pos()

    def _move(self, dt: float) -> None:
        tx, ty = self._clamp_xy(self.target[0], self.target[1])
        nx, vx = _spring_step(self.cx, self.vx, tx, dt, self.omega)
        ny, vy = _spring_step(self.cy, self.vy, ty, dt, self.omega)
        dx, dy = nx - self.cx, ny - self.cy
        step = math.hypot(dx, dy)
        cap = self.pan_cap * dt
        if step > cap:                                  # the cap is on the displacement: no input can cut
            k = cap / step
            dx, dy = dx * k, dy * k
            vx, vy = dx / dt, dy / dt
        nx, ny = self._clamp_xy(self.cx + dx, self.cy + dy)
        step = _hyp(nx, ny, self.cx, self.cy)
        self.speed = step / dt
        self.max_step_speed = max(self.max_step_speed, self.speed)
        self.cx, self.cy, self.vx, self.vy = nx, ny, vx, vy

    # ------------------------------------------------------------------ overlays data
    def edge_arrows(self, size: Tuple[int, int] = SCREEN, awake: Optional[Sequence[Dict[str, Any]]] = None,
                    inset: float = 24.0) -> List[Dict[str, Any]]:
        """Awake pips outside the window: the frame edge nearest them, a screen point on that edge (inset) and the
        distance in cells (`@kai · 210 paces ->`). The text layer filters the name and picks the colour."""
        out = []
        x0, y0, w, h = self.view_rect()
        s = size[0] / w
        cx, cy = x0 + w / 2.0, y0 + h / 2.0
        for a in (awake if awake is not None else self._awake_cache):
            x, y = float(a["x"]), float(a["y"])
            if self.in_view(x, y):
                continue
            dx, dy = x - cx, y - cy
            if abs(dx) / (w / 2.0) >= abs(dy) / (h / 2.0):
                side = "right" if dx > 0 else "left"
                t = (w / 2.0) / abs(dx)
            else:
                side = "bottom" if dy > 0 else "top"
                t = (h / 2.0) / abs(dy)
            ex, ey = cx + dx * t, cy + dy * t
            sx = min(size[0] - inset, max(inset, (ex - x0) * s))
            sy = min(size[1] - inset, max(inset, (ey - y0) * s))
            out.append({"key": a.get("key"), "x": x, "y": y, "side": side, "sx": sx, "sy": sy,
                        "dist": int(round(_hyp(x, y, cx, cy)))})
        return out

    def minimap(self, size: Tuple[int, int] = (144, 66)) -> Dict[str, Any]:
        """Geometry for the honest minimap: the WHOLE map scaled into `size`, the camera rectangle in minimap px and
        a cells -> minimap px function for dots. Land.walked_mask() / walked_fraction() supply the saturation split."""
        sc = min(size[0] / float(self.map_w), size[1] / float(self.map_h))
        x0, y0, w, h = self.view_rect()

        def to_px(x: float, y: float) -> Tuple[int, int]:
            return int(round(x * sc)), int(round(y * sc))

        return {"scale": sc, "size": (int(round(self.map_w * sc)), int(round(self.map_h * sc))),
                "view": (x0 * sc, y0 * sc, w * sc, h * sc), "to_px": to_px}

    def stats(self) -> Dict[str, Any]:
        return {"mode": self.mode, "x": round(self.cx, 1), "y": round(self.cy, 1), "zoom": self.zoom,
                "target_zoom": self.target_zoom, "speed": round(self.speed, 2), "max_speed": round(self.max_step_speed, 2),
                "cuts": self.cuts, "drift_stop": (self._drift_stop or {}).get("id"), "hud_nudge": round(self.hud_nudge, 2)}


# ---------------------------------------------------------------------------- self-test (OPENWORLD 7.5 gate 3)
def _self_test(verbose: bool = True) -> bool:
    """A 10 s scripted follow, a 10 s MOOT sweep from far away, a DRIFT survey and a zoom hold; asserts the per-frame
    speed never exceeds the cap, no cut happened, zooms changed only at rest and the clamp held."""
    import random
    fps, dt = 30.0, 1 / 30.0
    ok = True
    notes = []

    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
        notes.append(("PASS" if cond else "FAIL") + " " + msg)

    # 1. scripted follow: one pip walks 8 cells/s east then north, speaks, then a second pip appears 300 cells away
    cam = Camera()
    cam.resume(None)
    t = 1000.0
    px, py = cam.moot[0] - 60, cam.moot[1]
    max_speed, prev = 0.0, (cam.cx, cam.cy)
    modes = set()
    for i in range(int(10 * fps)):
        t += dt
        if i < 150:
            px += 8.0 * dt
            fx, fy = 1.0, 0.0
        else:
            py -= 8.0 * dt
            fx, fy = 0.0, -1.0
        awake = [{"key": "sami", "x": px, "y": py, "fx": fx, "fy": fy, "walking": True, "spoke_t": t - 2}]
        if i >= 200:
            awake.append({"key": "kai", "x": px + 300, "y": py + 80, "fx": -1, "fy": 0, "walking": False, "spoke_t": t})
        cam.update(t, dt, awake=awake)
        modes.add(cam.mode)
        sp = _hyp(cam.cx, cam.cy, prev[0], prev[1]) / dt
        max_speed = max(max_speed, sp)
        prev = (cam.cx, cam.cy)
    check(max_speed <= PAN_CAP + 1e-6, "follow: max per-frame speed %.2f cells/s <= cap %.0f" % (max_speed, PAN_CAP))
    check(cam.cuts == 0, "follow: cuts == 0 (%d)" % cam.cuts)
    check("FOLLOW" in modes, "follow: FOLLOW mode engaged (%s)" % sorted(modes))
    x0, y0, w, h = cam.view_rect()
    check(x0 >= EDGE_MARGIN - 1e-6 and y0 >= EDGE_MARGIN - 1e-6 and x0 + w <= MAP_W - EDGE_MARGIN + 1e-6 and y0 + h <= MAP_H - EDGE_MARGIN + 1e-6,
          "follow: clamp keeps the 12-cell margin (view %.1f,%.1f %.1fx%.1f)" % (x0, y0, w, h))
    arrows = cam.edge_arrows()
    check(any(a["key"] == "kai" for a in arrows) or cam.in_view(px + 300, py + 80), "follow: far pip has an edge arrow or is in view (%d arrows)" % len(arrows))

    # 2. round close from 400 cells away: an ease at the cap, never a cut; zoom only at rest
    cam2 = Camera()
    cam2.resume({"x": 200, "y": 100, "zoom": 1.0, "mode": "DRIFT"})
    stones = [(cam2.moot[0] - 20, cam2.moot[1] + 10), (cam2.moot[0], cam2.moot[1] + 10), (cam2.moot[0] + 20, cam2.moot[1] + 10)]
    t = 2000.0
    ms, prev = 0.0, (cam2.cx, cam2.cy)
    zoom_events = []
    for i in range(int(10 * fps)):
        t += dt
        z0 = cam2.zoom
        cam2.update(t, dt, awake=[{"key": "a", "x": stones[0][0], "y": stones[0][1] - 2, "fx": 0, "fy": 1, "walking": False, "spoke_t": None}],
                    moot={"stones": stones, "voters": ["a"], "walking_to_stone": False, "round_remaining": 25 - i * dt})
        if cam2.zoom != z0:
            zoom_events.append((i, cam2.speed))
        ms = max(ms, _hyp(cam2.cx, cam2.cy, prev[0], prev[1]) / dt)
        prev = (cam2.cx, cam2.cy)
    check(ms <= PAN_CAP + 1e-6, "moot: max speed %.2f <= cap over a 400-cell ease" % ms)
    check(cam2.mode == "MOOT", "moot: mode is MOOT (%s)" % cam2.mode)
    # the waystones sit in the SAFE band: the centre is lifted by safe_dy (13.5 cells at 1x) above them
    moot_off = _hyp(cam2.cx, cam2.cy, cam2.moot[0], cam2.moot[1] + 10 - Camera.safe_dy(cam2.zoom))
    check(moot_off < 40, "moot: arrived near the waystones (%.1f cells off the safe-band centre)" % moot_off)
    sy_st = cam2.sim_to_screen(stones[1][0], stones[1][1])
    check(sy_st is not None and HUD_TOP_PX <= sy_st[1] <= SCREEN[1] - HUD_BOTTOM_PX, "moot: the middle stone is drawn inside the safe band (screen y %s, band %d-%d)" % (None if sy_st is None else int(sy_st[1]), HUD_TOP_PX, SCREEN[1] - HUD_BOTTOM_PX))
    check(all(sp <= ZOOM_REST_SPEED for _, sp in zoom_events), "moot: zoom changed only at rest (%s)" % zoom_events)

    # 3. DRIFT: survey over real stops, dwell, no repeat inside 10 min, continuous motion
    cam3 = Camera()
    cam3.resume(None)
    stops = [{"id": "camp:a", "kind": "camp", "owner": "a", "x": 400, "y": 200}, {"id": "camp:b", "kind": "camp", "owner": "b", "x": 560, "y": 260},
             {"id": "natural:ford", "kind": "natural", "owner": None, "x": 500, "y": 150}]
    t = 3000.0
    visited, ms, prev = [], 0.0, (cam3.cx, cam3.cy)
    still = 0
    for i in range(int(120 * fps)):
        t += dt
        cam3.update(t, dt, stops=stops)
        sid = (cam3._drift_stop or {}).get("id")
        if not visited or visited[-1] != sid:
            visited.append(sid)
        sp = _hyp(cam3.cx, cam3.cy, prev[0], prev[1]) / dt
        ms = max(ms, sp)
        prev = (cam3.cx, cam3.cy)
    check(cam3.mode == "DRIFT", "drift: mode DRIFT at 0 awake")
    check(ms <= PAN_CAP + 1e-6, "drift: max speed %.2f <= cap" % ms)
    check(len(visited) >= 2 and len(set(visited)) == len(visited), "drift: visited %s without an early repeat" % visited)
    check(ms <= DRIFT_SPEED * 1.6, "drift: survey speed %.2f cells/s stays near %.0f" % (ms, DRIFT_SPEED))

    # 4. CLOSE: one pip standing still 35 s -> 1.5x after the rest + 20 s gates, then a 12-frame blend
    cam4 = Camera()
    cam4.resume(None)
    t = 4000.0
    for i in range(int(40 * fps)):
        t += dt
        cam4.update(t, dt, awake=[{"key": "solo", "x": cam4.moot[0] + 5, "y": cam4.moot[1], "fx": 1, "fy": 0, "walking": False, "spoke_t": None}])
    zf, zt, a = cam4.zoom_blend(t)
    check(cam4.mode == "CLOSE" and cam4.zoom == 1.5, "close: one still pip -> CLOSE at 1.5x (mode %s zoom %s)" % (cam4.mode, cam4.zoom))
    px0, py0, pw, ph = cam4.bake_crop()
    check((pw, ph) == CROP_PX[1.5] and px0 >= 0 and py0 >= 0, "close: bake crop %dx%d at (%d,%d)" % (pw, ph, px0, py0))
    check(a == 1.0, "close: crossfade finished (alpha %.2f)" % a)
    pin = Camera(allow_zoom=False)
    pin.resume(None)
    t = 5000.0
    for i in range(int(40 * fps)):
        t += dt
        pin.update(t, dt, awake=[{"key": "solo", "x": pin.moot[0], "y": pin.moot[1], "fx": 1, "fy": 0, "walking": False, "spoke_t": None}])
    check(pin.zoom == 1.0, "pinned: allow_zoom=False keeps 1x (%s)" % pin.zoom)
    s_pin = pin.sim_to_screen(pin.moot[0], pin.moot[1])
    check(s_pin is not None and HUD_TOP_PX <= s_pin[1] <= SCREEN[1] - HUD_BOTTOM_PX, "pinned: the followed pip stands inside the safe band, never under the HUD chips (screen y %s)" % (None if s_pin is None else int(s_pin[1])))
    s2 = pin.sim_to_screen(pin.moot[0], pin.moot[1])
    check(s2 is not None and abs(s2[0] - 640 - 0.15 * 320 * 4 * -1) < 200, "pinned: sim_to_screen returns a point (%s)" % (s2,))

    # 4b. HUD dead zone: three pips spanning 34 cells vertically (fits the 1x safe band), the newest speaker at the
    #     top walking SOUTH so the lead room (ahead of it) pulls the frame down past its head: without the dead zone its
    #     head sits at region y ~90 under the plank rows; with it the target is lifted and no head is under the chips
    hud = Camera(allow_zoom=False)
    hud.resume(None)
    t = 6000.0
    mx_, my_ = hud.moot
    grp = [{"key": "n", "x": mx_ - 40, "y": my_ - 34, "fx": 0, "fy": 1, "walking": True, "spoke_t": t},
           {"key": "s", "x": mx_ - 30, "y": my_, "fx": 0, "fy": 1, "walking": False, "spoke_t": None},
           {"key": "e", "x": mx_ + 40, "y": my_ - 10, "fx": 1, "fy": 0, "walking": False, "spoke_t": None}]
    for i in range(int(12 * fps)):
        t += dt
        for a in grp:
            a["spoke_t"] = t if a["key"] == "n" else a["spoke_t"]
        hud.update(t, dt, awake=grp)
    heads = []
    for a in grp:
        r = hud.sim_to_screen(a["x"], a["y"] - HEAD_CELLS)
        heads.append((a["key"], None if r is None else (int(r[0]), int(r[1]))))
    under = [k for k, r in heads if r is not None and r[0] < HUD_LEFT_W + 24 and r[1] < HUD_TOP_PX]
    check(hud.mode == "FOLLOW" and not under and hud.hud_nudge > 0.0, "hud dead zone: no followed head under the top-left chips (heads %s, nudge %.1f cells)" % (heads, hud.hud_nudge))
    feet = [hud.sim_to_screen(a["x"], a["y"]) for a in grp]
    check(all(f is not None and f[1] <= SCREEN[1] for f in feet), "hud dead zone: every framed pip's feet stay inside the region (%s)" % [None if f is None else int(f[1]) for f in feet])

    # 5. persistence round trip: resume keeps the position (no jump)
    d = cam4.to_dict(t)
    cam5 = Camera()
    cam5.resume(d)
    check(abs(cam5.cx - cam4.cx) < 0.01 and abs(cam5.cy - cam4.cy) < 0.01 and cam5.zoom == cam4.zoom, "persist: resume(to_dict()) restores x/y/zoom")

    if verbose:
        for n in notes:
            print("[camera] " + n)
        print("[camera] self-test %s" % ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if _self_test() else 1)
