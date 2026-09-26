"""stream/scenes/steading.py - LONGGRASS, the Steading: the open-land scene (OPENWORLD.md 4, 7.3-7.4, 12, 13 row 1).

    from stream.scenes.steading import SteadingScene
    scene = SteadingScene(run_dir=None, seed=None)      # run_dir defaults to $RUN_DIR; world.json (schema 2) lives there
    img = scene.frame(ctx, size)                        # RGBA exactly `size`; the camera's crop of the painted land
    scene.events                                        # this frame's events (list of dicts; WORLD_API.md 5 + x, y cells)
    scene.entities()                                    # for the text layer: cells + screen boxes, names, states, bubbles
    scene.awake_count() ; scene.asleep_count() ; scene.hatched_ever() ; scene.platform_counts()   # waystone slots
    scene.command(verb, actor, target=None, arg=None, now=None) -> (ok, reason)                  # verbs agent
    scene.sim_to_screen(x, y) -> (sx, sy) | None ; scene.scale ; scene.origin ; scene.degrade ; scene.stats()
    scene.camera ; scene.nature ; scene.terrain ; scene.land ; scene.world ; scene.behaviour
    scene.waystones() ; scene.plates(now) ; scene.info(now) ; scene.minimap_image(size)

The scene draws NO text: names, bubbles, waystone letters, plates, the plank, the time dial and the minimap frame
are the text layer's job at screen scale (nothing under 20 px). It draws the painted land (a crop of the memmapped
ground bake), the per-frame modulation field (tint by the real hour with the 0.55 floor x cloud shadows x wind bands
x the shadow layer x tide x sparkle), the glow buffer after dusk (honest sources only: a lit hearth, a real person's
fire or window, the beacon on a fresh keeper heartbeat, awake pips), then the y-sorted live sprites from the art
atlas (waystones, beacon, hearth, cairn, planted trees, camp fires, settlers, nameless tufts).

How the frame is made (7.3): 1. BakeManager.want(season, sun octant, bake_ver) -> the CURRENT ready GroundBake (a
missing one is painted in a daemon thread; its cell-res biome fallback shows meanwhile). 2. the camera's bake-pixel
crop (1280x456 at 1x from the 4 px/cell bake; 0.75x is a straight 1280x456 crop of a 3 px/cell bake; 1.5x is an
853x293 crop BILINEAR-upsampled). 3. Nature.modulation at cell resolution, bake.apply's fixed-point multiply.
4. glow. 5. sprites. 6. Image.fromarray. Whole-map work never runs on the frame path: bakes, region repaints after
a mark changed, trail-threshold repaints and settler sheets (0.75 s each) run on one worker thread; the frame path
blits cache hits only. A settler whose sheet is not ready yet is drawn as the nameless tuft one more beat, never
rendered inline; sheets are requested at seed-drop time (the 3 s hold covers it) and at boot for known settlers.

Frame flow: ingest ctx.chat_raw (tuft drifts in on the wind, nothing drawn from names) -> ctx.chat (moderated, past
the hold: hatch with display_name, speak, wake) -> ctx.recent_votes (walk to a waystone) -> behaviour.tick ->
persistence (positions in cells, camps on the first real sleep, camera every 5 s) -> camera.update -> render.
`frame()` never raises: any error returns the last good frame (or a flat tinted meadow), one stderr line per burst.
A failed schema-2 migration REFUSES to boot (OPENWORLD 5.4): every frame is the last good one and stats() says why.

Degrade ladder (own ms averaged over 30 frames, 7.4): > 14 clouds off + wind bands off; > 18 glow off; > 18 shadow
layer off; > 20 labels_on_speak + plates stop rotating; > 24 bubbles_single; > 28 zoom pinned at 1x; one step back per
300 clean frames; the flags are for the text layer and nature.

POSITIONS: every coordinate the scene exposes is a MAP CELL (960x440, 1 cell = 4 px at 1x), straight from the 2-D
behaviour (stream/world/behaviour.py: Entity.x / y are the feet cell, fx / fy the 8-direction facing, `side` the
sprite mirror, frame_name() the atlas frame or a tuft frame). The behaviour owns motion (routes, the tuft's drift,
standing slots, going home to sleep); the scene owns what is drawn, the persistence, the camera inputs, the bake and
the verbs' land side (camps, marks, fields, stones). A cave-era behaviour (no MAP_W) refuses to boot, loudly.
Test hooks: KL_TEST_PIPS (only under /tmp in test mode), `force_zoom` (test mode only).
`$PYTHON stream/scenes/steading.py --self-test` (RUN_DIR under /tmp, MODE=test).

HONESTY (OPENWORLD 12): entities exist only for real chat records (origin "chat") or, under KL_TEST_PIPS in a /tmp
run dir in test mode, synthetic ones (origin "test"). `_honesty_check` removes anything else every frame and
land.provenance_violations() is checked every 5 s; both count into stats()["honesty_violations"]. Every count is a
len(); a seed carries no name; the survey camera visits only real marks and three natural points; the wind is just
the wind.
"""
from __future__ import annotations

import hashlib
import math
import os
import queue
import re
import sys
import threading
import time as _time
import traceback
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
from PIL import Image, ImageDraw

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stream import layout as L  # noqa: E402
from stream.state_store import iso_to_epoch  # noqa: E402
from stream.world import HOLD_S, SLEEP_AFTER_S, test_pips_allowed  # noqa: E402
from stream.world import behaviour as BH  # noqa: E402
from stream.world import bake as BK  # noqa: E402
from stream.world import camera as CAM  # noqa: E402
from stream.world import land as LAND  # noqa: E402
from stream.world import nature as NAT  # noqa: E402
from stream.world import terrain as TER  # noqa: E402
from stream.world.behaviour import Behaviour  # noqa: E402
from stream.world.state import WorldState  # noqa: E402
try:                                                                   # cave constants (the shim's waystone slots)
    from stream.world.state import PLATFORMS as _PLATFORMS, PLATFORM_TOP as _PLATFORM_TOP  # noqa: E402
except Exception:                                                      # pragma: no cover
    _PLATFORMS, _PLATFORM_TOP = ((40, 40), (140, 40), (240, 40)), 85
from stream.world.art import creatures, props, tiles  # noqa: E402

NAME = "steading"
SCREEN = (1280, 456)          # the world region (HUD pass, journal 028: was 440; 480 missed the 12 ms scene gate)
PPC = 4                                   # bake px per cell at 1x
SAVE_S = 5.0
FORCE_SAVE_EVENTS = ("camp", "camp_new", "camp_raised", "plant", "sow", "harvest", "stone", "place", "sleep", "hatch", "cairn_named")
HISTORY_S = 60.0                          # a record older than this when first seen is boot/deploy history (ChatBridge.HISTORY_S)
SEED_SINK_S = HOLD_S + 4.0
HEARTBEAT_FRESH_S = 120.0
DEGRADE_MS = (14.0, 18.0, 18.0, 20.0, 24.0, 28.0)   # clouds+wind · glow · shadows · labels/plates · bubbles · zoom pin
DEGRADE_WINDOW = 30
RESTORE_FRAMES = 300
PROVENANCE_S = 5.0
WEAR_REPAINT_S = 2.0                      # trail-threshold repaints are batched on the worker at most this often
CHAT_RATE_WINDOW_S = 300.0
DUSK_GLOW_AT = 0.15                       # night_amount above which the glow buffer runs
EMBERS_S = 20 * 60.0                      # a camp fire burns while the owner is awake and for this long after
SEED_RING = 30                            # a tuft lands inside this ring around the Moot centre (3.1)
TUFT_W, TUFT_H = 20, 16
MOOT_LAYOUT = {                           # cell offsets from the Moot centre; the waystones come from the behaviour
    "beacon": (6, -10),                       # = keepers.beacon_state(): the minimap's amber dot and the post agree
    "hearth": (-16, 10), "cairn": (16, 10),
}
HOP_BODY_FRAMES = ("hop0", "hop1")            # drawn body-only over creatures.shadow() so the shadow stays on the ground
# Settlers are drawn slightly larger than the atlas's 1x sizes (owner fix pass, journal 023 handoff: 26/30/34/42 px read
# small on the 440 px land). The atlas renders every frame at 2x (its working resolution is the same, so a sheet costs
# the same ~0.75 s) and the scene BOX-downsamples to SETTLER_SCALE x the camera zoom: crisp outlines, no bilinear blur.
SETTLER_SCALE = 1.2
SETTLER_RENDER_ZOOM = 2
LETTERS = ("A", "B", "C")
SPRITE_PRIO_HATCH, SPRITE_PRIO_AWAKE, SPRITE_PRIO_SLEEP, SPRITE_PRIO_REST = 0, 1, 2, 3
WORKER_PACE_S = 0.004                     # the worker sleeps this long between settler frames (GIL courtesy)
FIRST_FRAMES = ("idle0", "idle1", "walk0", "walk1", "walk2", "walk3", "speak0", "speak1", "blink")
SLEEP_FRAMES = ("sleep",)
_MOD_CMD_RE = re.compile(r"^\s*!(hide|unhide|pause|resume|kill|unkill|clear|banish|unbanish|rename)\b", re.IGNORECASE)


def _log(msg: str) -> None:
    try:
        sys.stderr.write("steading: %s\n" % msg)
        sys.stderr.flush()
    except Exception:
        pass


def _hash01(*keys) -> float:
    h = hashlib.sha1(("|".join(str(k) for k in keys)).encode("utf-8")).digest()
    return int.from_bytes(h[:4], "little") / 4294967295.0


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _cells_behaviour() -> bool:
    """True for the 2-D behaviour (positions in map cells: it defines MAP_W and camera_inputs)."""
    return hasattr(BH, "MAP_W") and hasattr(Behaviour, "camera_inputs")


class _Ctx(object):
    """Minimal ctx for standalone use (a real ctx from StateStore already behaves like this)."""
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return None

    def get(self, name, default=None):
        v = self.__dict__.get(name)
        return default if v is None else v


# ----------------------------------------------------------------------------- the worker (never the frame thread)
class _Worker(threading.Thread):
    """One daemon thread for everything that may take longer than a frame: settler sheets (0.75 s each), region
    repaints of the bake after a mark changed, trail-threshold repaints, the minimap image. Jobs are (priority, fn)."""

    def __init__(self, log):
        super().__init__(name="steading-worker", daemon=True)
        self.q: "queue.PriorityQueue" = queue.PriorityQueue()
        self.log = log
        self.seq = 0
        self.done = 0
        self.errors = 0
        self.busy = False
        self._lock = threading.Lock()

    def submit(self, prio: int, fn, *args) -> None:
        with self._lock:
            self.seq += 1
            self.q.put((int(prio), self.seq, fn, args))

    def pending(self) -> int:
        return self.q.qsize()

    def run(self) -> None:
        while True:
            prio, _, fn, args = self.q.get()
            self.busy = True
            try:
                fn(*args)
                self.done += 1
            except Exception:
                self.errors += 1
                if self.errors <= 5:
                    self.log("worker job failed (%d): %s" % (self.errors, traceback.format_exc().strip().splitlines()[-1]))
            finally:
                self.busy = False
                self.q.task_done()


class _Sprites(object):
    """Settler frames from the art atlas, rendered on the worker and only ever READ on the frame path.
    `ready[(key, tier, frame)]` = the set of sun octants rendered; `get()` returns a cache hit or None."""

    def __init__(self, worker: _Worker):
        self.worker = worker
        self.ready: Dict[Tuple[str, int, str], Set[int]] = {}
        self.queued: Set[Tuple[str, int, str, int]] = set()
        self._zoomed: Dict[Tuple, np.ndarray] = {}
        self.requests = 0

    @staticmethod
    def sun_of(octant: int) -> Tuple[float, float]:
        return BK.octant_sun(octant)

    def request(self, key: str, tier: int, octant: int, frames: Sequence[str], prio: int) -> None:
        """Queue the frames not yet rendered at this octant (hop frames are rendered body-only + their shadow)."""
        key = (key or "").lower()
        tier = int(tier)
        todo = [f for f in frames if octant not in self.ready.get((key, tier, f), ()) and (key, tier, f, octant) not in self.queued]
        if not todo:
            return
        for f in todo:
            self.queued.add((key, tier, f, octant))
        self.requests += len(todo)
        self.worker.submit(prio, self._render_many, key, tier, octant, tuple(todo))

    def _render_many(self, key: str, tier: int, octant: int, frames: Sequence[str]) -> None:
        sun = self.sun_of(octant)
        for f in frames:
            _time.sleep(WORKER_PACE_S)                    # hand the GIL back between 32 ms renders: frames breathe
            try:
                if f in HOP_BODY_FRAMES:
                    creatures.render(key, tier, f, SETTLER_RENDER_ZOOM, 1, sun, with_shadow=False)
                    creatures.shadow(tier, f, SETTLER_RENDER_ZOOM, sun)
                else:
                    creatures.render(key, tier, f, SETTLER_RENDER_ZOOM, 1, sun)
                self.ready.setdefault((key, tier, f), set()).add(octant)
            finally:
                self.queued.discard((key, tier, f, octant))

    def has(self, key: str, tier: int, frame: str) -> bool:
        return bool(self.ready.get((key, tier, frame)))

    @staticmethod
    def factor(zoom: float) -> float:
        """Screen px per atlas px: the 2x render scaled to SETTLER_SCALE x the camera zoom (0.6 at 1x)."""
        return float(zoom) * SETTLER_SCALE / float(SETTLER_RENDER_ZOOM)

    @staticmethod
    def _scaled(base: np.ndarray, k: float) -> np.ndarray:
        w, h = max(1, int(round(base.shape[1] * k))), max(1, int(round(base.shape[0] * k)))
        method = Image.Resampling.BOX if k < 1 else Image.Resampling.BILINEAR
        return np.asarray(Image.fromarray(base).resize((w, h), method))

    def get(self, key: str, tier: int, frame: str, octant: int, facing: int, zoom: float) -> Optional[Tuple[np.ndarray, str]]:
        """A cache hit for (key, tier, frame) at this octant (else any rendered octant, else idle0), or None. The hit is
        the atlas's 2x render BOX-downsampled to SETTLER_SCALE x zoom (cached per zoom); nothing is rendered here."""
        key = (key or "").lower()
        for f in (frame, "idle0"):
            octs = self.ready.get((key, tier, f))
            if not octs:
                continue
            o = octant if octant in octs else next(iter(octs))
            body_only = f in HOP_BODY_FRAMES
            zk = (key, tier, f, o, facing, zoom)
            arr = self._zoomed.get(zk)
            if arr is None:
                base = creatures.render(key, tier, f, SETTLER_RENDER_ZOOM, facing, self.sun_of(o), with_shadow=not body_only)
                arr = self._scaled(base, self.factor(zoom))
                if len(self._zoomed) > 4000:
                    self._zoomed.clear()
                self._zoomed[zk] = arr
            return arr, f
        return None

    def shadow(self, tier: int, frame: str, octant: int, zoom: float) -> np.ndarray:
        """The ground ellipse alone (creatures.shadow, cached by the art module) at this zoom."""
        zk = ("shadow", tier, frame, octant, zoom)
        arr = self._zoomed.get(zk)
        if arr is None:
            base = creatures.shadow(int(tier), frame, SETTLER_RENDER_ZOOM, self.sun_of(octant))
            arr = self._scaled(base, self.factor(zoom))
            self._zoomed[zk] = arr
        return arr


def _tuft(phase: int) -> np.ndarray:
    """The nameless seed: a grey bundle of grass on the wind (no colour, no name). phase 0 drifting (leaning),
    1 settled, 2 split (the three 1 Hz frames of the hold). 20x16 px at 1x, ground point at the bottom centre."""
    key = ("tuft", phase)
    out = props._CACHE.get(key) if hasattr(props, "_CACHE") else None
    if out is not None:
        return out
    W, H = TUFT_W, TUFT_H
    ss = 3
    im = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, base = W * ss / 2.0, H * ss - 3 * ss
    d.ellipse([cx - 7 * ss, base - 2 * ss, cx + 7 * ss, base + 2 * ss], fill=(24, 18, 12, 90))
    lean = (-4.0, 0.0, 0.0)[phase]
    spread = (1.0, 1.0, 1.7)[phase]
    grey = ((150, 152, 148, 255), (176, 178, 172, 255), (128, 130, 126, 255))
    for i, ang in enumerate((-0.9, -0.45, 0.0, 0.45, 0.9)):
        L_ = (8.5 + (i % 2) * 2.0) * ss
        x1 = cx + (math.sin(ang) * 4.0 * spread + lean) * ss
        y1 = base - math.cos(ang) * L_ * (0.8 if phase == 0 else 1.0)
        d.line([(cx + (i - 2) * 1.2 * ss, base), (x1, y1)], fill=grey[i % 3], width=int(1.6 * ss))
        d.ellipse([x1 - 1.4 * ss, y1 - 1.4 * ss, x1 + 1.4 * ss, y1 + 1.4 * ss], fill=grey[(i + 1) % 3], outline=(44, 36, 30, 255))
    out = np.asarray(im.resize((W, H), Image.Resampling.LANCZOS))
    if hasattr(props, "_CACHE"):
        props._CACHE[key] = out
    return out


# ----------------------------------------------------------------------------- the scene
class SteadingScene(object):
    name = NAME

    def __init__(self, run_dir: Optional[str] = None, seed: Optional[int] = None, log=None,
                 sleep_after_s: float = SLEEP_AFTER_S, hold_s: float = HOLD_S, name_filter=None,
                 allow_zoom: bool = False, map_seed: int = LAND.MAP_SEED):
        self.run_dir = run_dir or os.environ.get("RUN_DIR") or os.path.join(_ROOT, "run")
        self.log = log or _log
        self.seed = int(seed) if seed is not None else None
        self.map_seed = int(map_seed)
        self.sleep_after_s = float(sleep_after_s)
        self.hold_s = float(hold_s)
        self._name_filter = name_filter
        self.allow_zoom = bool(allow_zoom)            # v0 preview pins 1x (OPENWORLD 13); the ladder pins it too
        self.force_zoom: Optional[float] = None       # TEST HOOK (test mode only): pin the camera at a zoom
        self.world: Optional[WorldState] = None
        self.behaviour: Optional[Behaviour] = None
        self.land = None
        self.terrain: Optional["TER.Terrain"] = None
        self.nature: Optional["NAT.Nature"] = None
        self.camera: Optional["CAM.Camera"] = None
        self.bakes: Optional["BK.BakeManager"] = None
        self._bakes75: Optional["BK.BakeManager"] = None
        self.rng = np.random.default_rng(0)
        self.booted = False
        self.refused: Optional[str] = None
        self.session_id: Optional[str] = None
        self.events: List[Dict[str, Any]] = []
        self.last_good: Optional[Image.Image] = None
        self.errors = 0
        self.frames = 0
        self.scale = float(PPC)
        self.origin = (0, 0)
        self.size = SCREEN
        self.degrade_level = 0
        self._ms: List[float] = []
        self._all_ms: List[float] = []
        self._clean = 0
        self.last_ms = 0.0
        self.sections: Dict[str, float] = {}
        self._seen_raw: Dict[str, float] = {}
        self._seen_clear: Dict[str, float] = {}
        self._seed_t: Dict[str, float] = {}
        self._votes_seen: Dict[str, Tuple[str, float]] = {}
        self._round_no: Optional[int] = None
        self._last_now: Optional[float] = None
        self._last_save: Optional[float] = None
        self._last_provenance: Optional[float] = None
        self._chat_times: List[float] = []
        self.honesty_violations = 0
        self.provenance_violations: List[str] = []
        self.test_pips = 0
        self._ending_seen = False
        self._chat_ids_seen = 0
        self._pos: Dict[str, Tuple[float, float]] = {}
        self._boot_fail = 0
        self._fires: Dict[str, float] = {}             # key -> epoch the owner lit their camp fire (embers after sleep)
        self._cairn_named_seen = False
        self._marks: Dict[str, Any] = {}
        self._marks_sig: Optional[Tuple] = None
        self._marks_ver = 0
        self._bake_marks_ver: Dict[int, int] = {}
        self._caster: Optional[np.ndarray] = None
        self._caster_key: Optional[Tuple] = None
        self._bake_ver_applied: Optional[int] = None    # the version the CURRENT bake file is named for
        self._rename_pending: Optional[int] = None
        self._trail_full_check = False
        self._wear_seen_ver = 0
        self._wear_job_t: Optional[float] = None
        self._tier_base: Optional[np.ndarray] = None
        self._minimap: Dict[Tuple, Image.Image] = {}
        self._minimap_job: Optional[Tuple] = None
        self._rgba: Optional[np.ndarray] = None
        self._boot_ms = 0.0
        self._octant = 0
        self._cam_log = None                          # TEST HOOK (KL_CAMERA_LOG, test mode only): per-frame camera rows
        self.worker = _Worker(self.log)
        self.worker.start()
        self.sprites = _Sprites(self.worker)
        self._terrain_thread = threading.Thread(target=self._gen_terrain, name="steading-terrain", daemon=True)
        self._terrain_err: Optional[str] = None
        self._terrain_thread.start()                  # 390 ms once per process: never inside a frame

    # ------------------------------------------------------------------ boot
    def _gen_terrain(self) -> None:
        try:
            t0 = _time.perf_counter()
            T = TER.generate(self.map_seed, LAND.MAP_W, LAND.MAP_H)
            self.terrain = T
            self.log("terrain %d ready in %.0f ms (site %s, moot_r %d)" % (self.map_seed, (_time.perf_counter() - t0) * 1000, T.site, T.moot_r))
        except Exception as e:
            self._terrain_err = "%s: %s" % (type(e).__name__, e)
            self.log("terrain FAILED: %s" % self._terrain_err)

    def _boot(self, ctx) -> None:
        t0 = _time.perf_counter()
        now = float(ctx.now or _time.time())
        if not _cells_behaviour():
            self.refused = "stream/world/behaviour.py is the cave's 1-D version (no MAP_W / camera_inputs): the land needs the 2-D behaviour"
            self.log("REFUSING TO BOOT: %s" % self.refused)
            return
        T = self.terrain
        moot = (float(T.site[0]), float(T.site[1]))
        self.world = WorldState(self.run_dir, log=self.log, name_filter=self._name_filter or self._default_filter(),
                                schema=2, moot=moot, passable=T.passable, water=T.water, now=now)
        if not self.world.migration_ok or self.world.schema < 2:
            self.refused = "schema 2 migration failed: %s" % ((self.world.migration or {}).get("problems") or "unknown")
            self.log("REFUSING TO BOOT (5.4): %s; keeping the last good frame" % self.refused)
            return
        if int((self.world.data.get("world") or {}).get("map_seed") or self.map_seed) != self.map_seed:
            want = int(self.world.data["world"]["map_seed"])
            self.log("world.json map_seed %d != %d: regenerating terrain inline" % (want, self.map_seed))
            self.map_seed = want
            self.terrain = T = TER.generate(want, LAND.MAP_W, LAND.MAP_H)
            moot = (float(T.site[0]), float(T.site[1]))
        self.land = self.world.land
        self.land.set_terrain_layers(T.passable, T.water, moot)
        wblk = self.world.data["world"]
        self.nature = NAT.Nature(T, self.map_seed, hemisphere=wblk.get("hemisphere") or None,
                                 world_day=wblk.get("world_day") or "real")
        self.camera = CAM.Camera(map_w=T.w, map_h=T.h, margin=TER.EDGE_MARGIN, zoom=1.0, allow_zoom=self.allow_zoom, moot=moot)
        resumed = self.camera.resume(self.land.camera())
        self.bakes = BK.BakeManager(self.run_dir, T, log=self.log, px_per_cell=PPC)
        sess = ctx.session or {}
        self.session_id = sess.get("id") or None
        micro = ctx.micro or {}
        seed = self.seed if self.seed is not None else (int(micro.get("canvas_seed") or 41370704) ^ (LAND.name_hash(str(self.session_id)) & 0xFFFF))
        self.rng = np.random.default_rng(seed & 0xFFFFFFFF)
        self.nature.update(now, 0.0)
        self._octant = BK.sun_octant(self.nature.sun(now))
        self.behaviour = Behaviour(seed=seed, sleep_after_s=self.sleep_after_s, hold_s=self.hold_s, terrain=T, land=self.land,
                                   moot=moot, wind=lambda: self.nature.wind.vector, sheet_ready=self._sheet_ready)
        self.world.begin_session(self.session_id, now)
        rec = self.world.recompute_from_chat(now, self.session_id)
        self.log("boot: world.json %s schema %d, %d pips, chat.jsonl recompute %r, camera %s" % (
            "loaded" if self.world.loaded_ok else "fresh", self.world.schema, len(self.world.pips), rec,
            "resumed" if resumed else "at the Moot"))
        # every known pip starts asleep at its camp (a real past chatter with a real last_seen); a message wakes it
        cutoff = now - self.sleep_after_s
        for key, p in sorted(self.world.pips.items(), key=lambda kv: kv[1].get("last_seen_ts") or ""):
            if not p.get("_test") and not isinstance(p.get("camp"), dict) and p.get("state") not in ("seed", "hatching"):
                self.world.ensure_camp(key, now)                   # slept before (real last_seen) -> a hollow, tier by the ladder
            e = self.behaviour.place_sleeper(key, int(p.get("tier") or 0), float(p.get("energy") or 0.6),
                                             int((p.get("genome") or {}).get("salt") or 0), p.get("camp"),
                                             p.get("display_name") or self.world.name_filter(p.get("name") or key), t=now,
                                             x=p.get("x"), y=p.get("y"))
            last = iso_to_epoch(p.get("last_seen_ts"))
            if last is not None and last >= cutoff and self._in_session(last, ctx):
                self._restore_awake(e, p, last, now)
            else:
                self.world.set_state(key, "asleep", e.x, e.y)
            self.sprites.request(key, e.tier, self._octant, SLEEP_FRAMES if not e.is_awake() else FIRST_FRAMES,
                                 SPRITE_PRIO_SLEEP if not e.is_awake() else SPRITE_PRIO_AWAKE)
        for key, e in self.behaviour.entities.items():
            self.sprites.request(key, e.tier, self._octant, creatures.FRAMES, SPRITE_PRIO_REST)
        self.test_pips = test_pips_allowed(self.run_dir, ctx)
        if os.environ.get("KL_SLEEP_AFTER_S") and test_pips_allowed(self.run_dir, ctx, dict(os.environ, KL_TEST_PIPS="1")):
            try:                                                    # TEST HOOK: a short awake window so a harness sees FOLLOW -> DRIFT -> FOLLOW
                sa = float(os.environ["KL_SLEEP_AFTER_S"])
                if 5.0 <= sa < self.sleep_after_s:
                    self.sleep_after_s = sa
                    self.behaviour.sleep_after_s = sa
                    self.log("TEST HOOK: KL_SLEEP_AFTER_S=%.0f (pips sleep after %.0f s of quiet, not %d min)" % (sa, sa, int(SLEEP_AFTER_S // 60)))
            except ValueError:
                pass
        cam_log = os.environ.get("KL_CAMERA_LOG")
        if cam_log and test_pips_allowed(self.run_dir, ctx, dict(os.environ, KL_TEST_PIPS="1")):
            try:                                                    # TEST HOOK: per-frame camera rows for the QA harness
                self._cam_log = open(cam_log, "a")
                self._cam_log.write("frame,now,mode,cx,cy,zoom,speed,awake,awake_in_view,awake_in_safe,seeds,seeds_in_view,awake_under_hud,hud_nudge,framed,framed_under_hud,des_cy,tgt_cy,min_head_sy,hud_left\n")
                self.log("TEST HOOK: KL_CAMERA_LOG=%s" % cam_log)
            except OSError:
                self._cam_log = None
        if self.test_pips:
            self._spawn_test_pips(now)
            try:                                                    # TEST HOOK (with KL_TEST_PIPS only): pin a zoom for the budget gate
                fz = float(os.environ.get("KL_FORCE_ZOOM") or 0)
                if fz in CAM.ZOOMS:
                    self.force_zoom = fz
                    self.log("TEST HOOK: KL_FORCE_ZOOM=%.2f" % fz)
            except ValueError:
                pass
        if self.force_zoom is not None and not test_pips_allowed(self.run_dir, ctx, dict(os.environ, KL_TEST_PIPS="1")):
            self.force_zoom = None                                  # the hook is test-mode only
        self._marks_build(now)
        season_idx = NAT.season_index(self.nature.season(now))
        found = self._existing_bake_ver(season_idx, self._octant, self.land.bake_ver)
        self._bake_ver_applied = found if found is not None else self.land.bake_ver
        if found is not None and found != self.land.bake_ver:
            self._trail_full_check = True                           # an older file: trails painted since are re-checked
        B = self._want_bake(now)
        if found is not None and found != self.land.bake_ver:
            self._bake_marks_ver[id(B)] = -1                        # ... and every mark region is repainted, then renamed
        self.worker.submit(SPRITE_PRIO_HATCH, self._job_warm_props, self._octant, float(season_idx))
        self.booted = True
        self._boot_ms = (_time.perf_counter() - t0) * 1000
        self.log("boot done in %.0f ms; %d entities, %d camps, bake %s" % (
            self._boot_ms, len(self.behaviour.entities), len(self.land.camps()), (self.bakes.current.stats() if self.bakes.current else None)))

    def _sheet_ready(self, key: str) -> bool:
        """The behaviour asks before a hatch (<= 4 s grace): is this settler's first frame rendered? Never renders."""
        e = self.behaviour.get(key) if self.behaviour is not None else None
        tier = int(e.tier) if e is not None else 0
        return self.sprites.has(key, tier, "idle0")

    def _restore_awake(self, e, p: Dict[str, Any], last: float, now: float) -> None:
        """Deploy continuity (journal 011): an owner who chatted inside the awake window resumes where world.json
        last saw the pip, with the sleep timer counting from their real last message. No wake event, no hop."""
        e.state = "awake"
        e.sleep_t = None
        e.wake_t = last
        e.last_active_t = last
        e.last_attention_t = last
        e.spoke_t = last
        e.vx = e.vy = 0.0
        e.route, e.target, e.then = [], None, None
        e.minutes_tonight = 0.0
        px, py = p.get("x"), p.get("y")
        if px is not None and py is not None:
            e.x, e.y = self.behaviour.ground.nearest(float(px), float(py))
        f = p.get("facing")
        if isinstance(f, (list, tuple)) and len(f) >= 2:
            e.facing = (int(f[0]), int(f[1]))
        e.pause_until = now + self._u(0.5, 2.0)
        if p.get("state") == "voting" and p.get("vote") in LETTERS:
            self.behaviour.walk_to(e.key, p["vote"], now)
        self.world.set_state(e.key, e.state)

    def _in_session(self, t: float, ctx) -> bool:
        started = iso_to_epoch((ctx.session or {}).get("started_ts"))
        return started is None or t >= started - 60.0

    def _session_started(self, ctx) -> Optional[float]:
        return iso_to_epoch((ctx.session or {}).get("started_ts"))

    def _default_filter(self):
        """display_name for boot-loaded pips: the bridge's blocklist path (builder #N on a hit)."""
        try:
            from stream.chat_bridge import ChatBridge
            br = ChatBridge(self.run_dir, log=lambda m: None)
            br._load_blocklist(0.0)

            def f(name: str) -> str:
                try:
                    return br._display_name(name)
                except Exception:
                    return "builder #%s" % (br.builder_n(name) or "?")
            return f
        except Exception as e:
            self.log("no ChatBridge name filter (%r): boot pips carry no display name until they chat" % (e,))
            return lambda name: None

    def _spawn_test_pips(self, now: float) -> None:
        """TEST ONLY (guarded by test_pips_allowed): synthetic pips (origin 'test') spread over passable land around
        the Moot, hatched by the behaviour as their sheets land. Never persisted as real rows (`_test`), never counted,
        never given camps (land.real_pip refuses them)."""
        self.log("TEST HOOK: KL_TEST_PIPS=%d synthetic pips (run_dir %s, test mode)" % (self.test_pips, self.run_dir))
        T = self.terrain
        sx, sy = T.site
        for i in range(self.test_pips):
            key = "test-pip-%02d" % i
            p, created = self.world.ensure_pip(key, key, "test pip %d" % i, None, now - 10.0)
            p["_test"] = True
            board = self.world.data["world"]["board"]
            board["hatched"] = [k for k in board.get("hatched", []) if k != key]
            x = y = None
            for k in range(40):
                x = sx + (_hash01("bx", key, k) - 0.5) * 300
                y = sy + (_hash01("by", key, k) - 0.5) * 100
                if T.is_passable(x, y):
                    break
            tier = int(p.get("tier") or i % 4)
            self.behaviour.seed_drop(key, now - self.hold_s - 1.0, x, y, origin="test")
            self.behaviour.hold_cleared(key, now - self.hold_s - 1.0, "test pip %d" % i, tier,
                                        0.4 + 0.6 * ((i * 7) % 10) / 10.0, int(p["genome"]["salt"]), created)
            self.sprites.request(key, tier, self._octant, FIRST_FRAMES, SPRITE_PRIO_AWAKE)
            self.sprites.request(key, tier, self._octant, creatures.FRAMES, SPRITE_PRIO_REST)

    def _u(self, a: float, b: float) -> float:
        return float(a + (b - a) * self.rng.random())

    # ------------------------------------------------------------------ positions (cells)
    @staticmethod
    def _pos_of(e, now: float = 0.0) -> Tuple[float, float]:
        """The entity's feet cell (the behaviour owns motion: sleepers lie at their camp, tufts ride the wind)."""
        return float(e.x), float(e.y)

    @staticmethod
    def _facing_of(e) -> Tuple[float, float]:
        return float(getattr(e, "fx", 1) or 0.0), float(getattr(e, "fy", 0) or 0.0)

    # ------------------------------------------------------------------ ingest (carried from hollow.py)
    def _ingest(self, ctx, now: float) -> None:
        b, w = self.behaviour, self.world
        sess = ctx.session or {}
        sid = sess.get("id")
        if sid and sid != self.session_id:
            self.session_id = sid
            w.begin_session(sid, now)
        hidden = set(str(u).lower() for u in ((ctx.mod or {}).get("hidden_users") or []))
        owner = (os.environ.get("KICK_CHANNEL") or "atleastonce").strip().lower()
        # 1. raw records: within one frame a tuft drifts in (nameless) or the owner's pip hops. Names are hashed, never drawn.
        for m in (ctx.chat_raw or []):
            mid = m.get("id")
            if not mid or mid in self._seen_raw:
                continue
            self._seen_raw[mid] = now
            key = (m.get("name") or "").lower()
            if not key or key in hidden or m.get("type") not in (None, "message"):
                continue
            t = float(m.get("t") or now)
            aged = (now - t) > HISTORY_S
            in_window = t >= now - self.sleep_after_s and self._in_session(t, ctx)
            if aged and not in_window:
                continue
            if _MOD_CMD_RE.match(str(m.get("text") or "")) and (key == owner or self._is_mod(m)):
                continue                                          # a mod command is not a message: no seed, no hop (11.9)
            if not aged:
                self._chat_times.append(t)                        # the wind's base speed is the REAL chat rate
            if w.pip(key) is not None:
                w.touch_seen(key, t)
            e = b.get(key)
            if e is None:
                if w.pip(key) is None:
                    if aged:
                        continue
                    b.seed_drop(key, now)
                    self._seed_t[key] = now
                    self.sprites.request(key, 0, self._octant, FIRST_FRAMES, SPRITE_PRIO_HATCH)   # the hold covers the render
                else:                                             # known pip missing an entity (banish undo etc.)
                    p = w.pip(key)
                    e2 = b.place_sleeper(key, int(p.get("tier") or 0), float(p.get("energy") or 0.6),
                                         int((p.get("genome") or {}).get("salt") or 0), p.get("camp"), p.get("display_name"),
                                         t=now, x=p.get("x"), y=p.get("y"))
                    self.sprites.request(key, e2.tier, self._octant, FIRST_FRAMES, SPRITE_PRIO_AWAKE)
                    b.message(key, now)
            elif aged:
                if e.state in ("asleep", "burrowed") and e.key not in hidden:
                    self.sprites.request(key, e.tier, self._octant, FIRST_FRAMES, SPRITE_PRIO_AWAKE)
                    b.message(key, now)                           # wake only; no hop for an old record
            else:
                if e.state in ("asleep", "burrowed"):
                    self.sprites.request(key, e.tier, self._octant, FIRST_FRAMES, SPRITE_PRIO_AWAKE)
                b.message(key, now)
        # 2. moderated records past the hold: hatch with the FILTERED display name, speak the owner's words, count.
        for m in (ctx.chat or []):
            mid = m.get("id")
            if not mid or mid in self._seen_clear or m.get("dropped"):
                continue
            self._seen_clear[mid] = now
            key = (m.get("name") or "").lower()
            if not key or key in hidden:
                continue
            t = float(m.get("t") or now)
            if m.get("history") or (now - t) > HISTORY_S:
                self._ingest_history(m, key, t, now, ctx)
                continue
            p, created = w.ensure_pip(key, m.get("name") or key, m.get("display_name") or None, m.get("builder_n"), t)
            e = b.get(key)
            if e is None or e.state in ("seed", "hatching"):
                b.hold_cleared(key, now, p.get("display_name") or ("builder #%s" % (p.get("n") or "?")),
                               int(p.get("tier") or 0), float(p.get("energy") or 0.6), int(p["genome"]["salt"]),
                               bool(m.get("first_ever")) or created)
                if e is None:
                    b.get(key).seed_t = now - self.hold_s      # the raw record was missed: hatch now, hold already served
                self.sprites.request(key, int(p.get("tier") or 0), self._octant, FIRST_FRAMES, SPRITE_PRIO_HATCH)
                self.sprites.request(key, int(p.get("tier") or 0), self._octant, creatures.FRAMES, SPRITE_PRIO_REST)
            elif e.state in ("asleep", "burrowed"):
                b.message(key, now)
            if e is not None and e.is_awake() and e.display_name is None:
                e.display_name = p.get("display_name")
            w.record_message(key, t, self.session_id, m.get("text_clean") or m.get("text"), history=False)
            w.visit(key, t)
            newt = w.update_tier(p)
            if newt is not None:
                b.set_tier(key, newt, now)
                self.sprites.request(key, newt, self._octant, creatures.FRAMES, SPRITE_PRIO_AWAKE)
            if m.get("kind") == "vote" and m.get("letter"):
                p["votes_cast"] = int(p.get("votes_cast") or 0) + 1
            text = m.get("text_clean") or ""
            if text and not ctx.mod_paused and (m.get("kind") in (None, "plain") or m.get("kind") == "vote"):
                ent = b.get(key)
                if ent is not None and ent.is_awake():
                    b.speak(key, now, text if m.get("kind") != "vote" else text.upper())
                elif ent is not None:
                    ent.text, ent.speak_until = text, now + 6.0   # speaks as it hatches
            self._chat_ids_seen += 1
        # 3. votes: walk to the waystone within one frame of the tally changing
        for name, letter, t in (ctx.recent_votes or []):
            key = self._key_for_display(name)
            if key is None:
                continue
            prev = self._votes_seen.get(key)
            if prev != (letter, t):
                self._votes_seen[key] = (letter, t)
                b.walk_to(key, letter, now)
        rnd = (ctx.round or {}).get("number")
        if rnd is not None and rnd != self._round_no:
            if self._round_no is not None:
                b.release_votes(now)
                self._votes_seen = {}
            self._round_no = rnd
        rule = ((ctx.micro or {}).get("colony_rule") or "free")
        b.colony_rule = rule if rule in ("free", "follow", "scatter", "huddle") else "free"
        # 4. hidden users lie down in the grass (no label, no plate); seeds past the hold with no clearance blow away
        for e in list(b.entities.values()):
            if e.key in hidden and e.state not in ("burrowed", "seed", "hatching"):
                b.hide(e.key, now)                                # lies down in the grass, unlabelled (12)
            elif e.key in hidden and e.state in ("seed", "hatching"):
                b.sink(e.key, now)
            elif e.state in ("seed", "hatching") and not e.cleared and now - e.seed_t > SEED_SINK_S:
                b.sink(e.key, now)
        # 5. session end -> credits
        if sess.get("ending") and not self._ending_seen:
            self._ending_seen = True
            b.start_credits(now)
        # bounded memories
        for d in (self._seen_raw, self._seen_clear):
            if len(d) > 4000:
                for k in sorted(d, key=d.get)[:2000]:
                    d.pop(k, None)
        if len(self._chat_times) > 2000:
            del self._chat_times[:-1000]

    @staticmethod
    def _is_mod(m: Dict[str, Any]) -> bool:
        for bdg in (m.get("badges") or []):
            s = str(bdg).lower()
            if "broadcaster" in s or "moderator" in s or s == "mod":
                return True
        return False

    def _ingest_history(self, m: Dict[str, Any], key: str, t: float, now: float, ctx) -> None:
        """A moderated record the previous compositor instance already showed (boot / relay-deploy history)."""
        b, w = self.behaviour, self.world
        p, created = w.ensure_pip(key, m.get("name") or key, m.get("display_name") or None, m.get("builder_n"), t)
        e = b.get(key)
        if e is None or e.state in ("seed", "hatching"):
            if e is not None:
                b.sink(key, now)                                  # a stray seed for a history record never hatches
            if not p.get("_test") and not isinstance(p.get("camp"), dict):
                w.ensure_camp(key, now)
            e = b.place_sleeper(key, int(p.get("tier") or 0), float(p.get("energy") or 0.6),
                                int((p.get("genome") or {}).get("salt") or 0), p.get("camp"),
                                p.get("display_name") or ("builder #%s" % (p.get("n") or "?")), t=now, x=p.get("x"), y=p.get("y"))
            w.set_state(key, "asleep", e.x, e.y)
            self.sprites.request(key, e.tier, self._octant, SLEEP_FRAMES, SPRITE_PRIO_SLEEP)
        if self._in_session(t, ctx):
            w.record_message(key, t, self.session_id, None, history=True)
        else:
            w.touch_seen(key, t)
        visits = (w.data.get("world") or {}).get("visits") or []
        last_v = max([iso_to_epoch(v.get("ts")) or 0.0 for v in visits if v.get("name") == key] or [0.0])
        if t > last_v:
            w.visit(key, t)
        newt = w.update_tier(p)
        if newt is not None:
            b.set_tier(key, newt, now)
        if e.state in ("asleep", "burrowed") and t >= now - self.sleep_after_s and self._in_session(t, ctx):
            self.sprites.request(key, e.tier, self._octant, FIRST_FRAMES, SPRITE_PRIO_AWAKE)
            b.message(key, now)                                   # awake = chatted in the last 20 min of this session
        if e.is_awake() and e.display_name is None:
            e.display_name = p.get("display_name")
        self._chat_ids_seen += 1

    def _key_for_display(self, shown: str) -> Optional[str]:
        s = (shown or "").lower()
        if not s:
            return None
        if s in self.world.pips:
            return s
        if s.startswith("builder #"):
            try:
                n = int(s.split("#", 1)[1])
            except Exception:
                return None
            for k, p in self.world.pips.items():
                if p.get("n") == n:
                    return k
        return s if s in self.behaviour.entities else None

    def chat_rate(self, now: float) -> float:
        """Real messages per minute over the last 5 min (the wind's base speed)."""
        cut = now - CHAT_RATE_WINDOW_S
        n = sum(1 for t in self._chat_times if t >= cut)
        return 60.0 * n / CHAT_RATE_WINDOW_S

    # ------------------------------------------------------------------ persistence per frame
    def _persist(self, ctx, now: float, events: List[Dict[str, Any]], dt: float) -> None:
        w, b, land = self.world, self.behaviour, self.land
        for e in b.entities.values():
            if e.origin != "chat" and e.origin != "test":
                continue
            p = w.pip(e.key)
            if p is None:
                continue
            if e.is_awake():
                w.presence(e.key, dt)
                if p.get("energy") != e.energy:
                    p["energy"] = round(e.energy, 4)
                    w.dirty = True
            x, y = self._pos.get(e.key) or self._pos_of(e, now)
            if p.get("state") != e.state:
                w.set_state(e.key, e.state, None, None, None, e.platform if e.state == "voting" else None)
            if e.state not in ("seed", "hatching") and (p.get("x") != int(round(x)) or p.get("y") != int(round(y))):
                fx, fy = self._facing_of(e)
                w.set_pos(e.key, x, y, (fx, fy))
        for ev in events:
            typ = ev.get("type")
            key = ev.get("pip") or ev.get("key")
            e = b.get(key) if key else None
            if e is not None and (typ in ("hatch", "wake", "sleep", "seed", "seed_land", "walk", "arrive") or "x" in ev):
                if typ in ("seed", "seed_land") and getattr(e, "seed_to", None) is not None:
                    x, y = e.seed_to                                 # the LANDING spot (3.1): the camera eases there, never
                else:                                                # to the tuft's start 150 cells upwind
                    x, y = self._pos.get(e.key) or self._pos_of(e, now)
                ev["x"], ev["y"] = round(x, 1), round(y, 1)          # cells (the behaviour's x was the cave's floor px)
            if typ == "hatch":
                p = w.pip(key)
                if p is not None:
                    p["state"] = "awake"
            elif typ == "wake":
                care = w.take_care_log(key)
                ev["care_log"] = care
                p = w.pip(key)
                if p is not None:
                    last = iso_to_epoch(p.get("last_seen_ts"))
                    ev["away_s"] = (now - last) if last else None
                camp = land.camp_of(key)
                ev["camp"] = dict(camp) if isinstance(camp, dict) else None
                if key in self._fires:
                    self._fires[key] = now                          # the fire relights
            elif typ == "first_light":
                w.woke(key, now)
                ev["alias"] = "first_breath"                         # LONGGRASS name (3.1); the type stays for its consumers
                if w.pip(key) is not None and not (w.pip(key) or {}).get("_test"):
                    if land.light_hearth(key, now):
                        b.events.append({"type": "hearth", "by": key, "x": self.moot_xy("hearth")[0], "y": self.moot_xy("hearth")[1]})
            elif typ == "sleep":
                p = w.pip(key)
                if p is not None and not p.get("_test") and e is not None:
                    before = land.camp_of(key)
                    camp = w.ensure_camp(key, now, self.session_id, e.x, e.y)
                    if isinstance(camp, dict):
                        b.set_camp(key, camp["x"], camp["y"])        # the land may have moved a refused spot to the ring
                        self._pos[key] = (float(e.x), float(e.y))    # entities() this frame sees the settled spot
                        ev["camp"] = [camp["x"], camp["y"]]
                        ev["x"], ev["y"] = float(e.x), float(e.y)
                        w.set_pos(key, e.x, e.y, (e.fx, e.fy))
                        if before is None:
                            b.events.append({"type": "camp", "pip": key, "x": camp["x"], "y": camp["y"], "tier": camp.get("tier", 0), "first": True})
            elif typ == "place" and ev.get("kind") == "stone":
                p = w.pip(key)
                if p is not None and not p.get("_test"):
                    rec, why = land.stack(key, now)
                    lad = land.ladder()
                    ev.update({"stacked": rec is not None, "reason": why, "stock": lad.get("stock"), "ladder": lad})
                    if rec is not None:
                        b.events.append({"type": "stone", "pip": key, "stock": lad.get("stock"), "next": lad.get("next"),
                                         "name": lad.get("name"), "x": self.moot_xy("cairn")[0], "y": self.moot_xy("cairn")[1]})
                        if land.cairn_named() and not self._cairn_named_seen:
                            self._cairn_named_seen = True
                            b.events.append({"type": "cairn_named", "x": self.moot_xy("cairn")[0], "y": self.moot_xy("cairn")[1],
                                             "plaque": land.plaque()})
        for e in b.awake():
            p = w.pip(e.key)
            if p is not None:
                nt = w.update_tier(p)
                if nt is not None:
                    b.set_tier(e.key, nt, now)
                    self.sprites.request(e.key, nt, self._octant, creatures.FRAMES, SPRITE_PRIO_AWAKE)
        w.touch_session(now)
        if self.camera is not None:
            self.camera.maybe_persist(land, now)
        # a camp or a mark is a promise ("camps are never dismantled", 12): it reaches world.json in the same frame,
        # not at the next 5 s tick (QA: kai_dnb's camp was on screen but absent from world.json at 03:53:12)
        if any(ev.get("type") in FORCE_SAVE_EVENTS for ev in events):
            if w.save(now, force=True):
                self._last_save = now
        elif self._last_save is None or now - self._last_save >= SAVE_S:
            if w.save(now, force=False):
                self._last_save = now
            elif self._last_save is None:
                self._last_save = now

    def save_now(self, now: Optional[float] = None) -> bool:
        """Forced flush of world.json (+ the camera) for a compositor exit or a scene swap; never raises."""
        if not self.booted or self.world is None:
            return False
        t = float(now if now is not None else (self._last_now or _time.time()))
        try:
            if self.camera is not None and self.land is not None:
                self.camera._persist_t = None
                self.camera.maybe_persist(self.land, t)
            ok = bool(self.world.save(t, force=True))
            if self._cam_log is not None:
                self._cam_log.flush()
            self.log("world.json saved on shutdown (%s)" % ("ok" if ok else "unchanged"))
            return ok
        except Exception:
            self.log("save_now failed: %s" % traceback.format_exc().strip().splitlines()[-1])
            return False

    # ------------------------------------------------------------------ honesty
    def _honesty_check(self, now: float) -> None:
        b = self.behaviour
        allowed_test = self.test_pips > 0
        bad = [k for k, e in b.entities.items() if e.origin != "chat" and not (allowed_test and e.origin == "test")]
        if bad:
            self.honesty_violations += len(bad)
            for k in bad:
                del b.entities[k]
            self.log("HONESTY: removed %d entities with no real chat record (%s)" % (len(bad), ", ".join(bad[:5])))
        real = sum(1 for e in b.entities.values() if e.origin == "chat" or (allowed_test and e.origin == "test"))
        if real != len(b.entities):
            self.honesty_violations += 1
        if self._last_provenance is None or now - self._last_provenance >= PROVENANCE_S:
            self._last_provenance = now
            try:
                bad_marks = self.land.provenance_violations()
            except Exception:
                bad_marks = []
            if bad_marks:
                self.honesty_violations += len(bad_marks)
                self.provenance_violations = list(bad_marks)[:20]
                self.log("HONESTY: %d marks without a real owner: %s" % (len(bad_marks), "; ".join(bad_marks[:3])))

    # ------------------------------------------------------------------ marks -> bake
    def moot_xy(self, what: str) -> Tuple[int, int]:
        sx, sy = self.terrain.site
        dx, dy = MOOT_LAYOUT[what]
        return int(sx + dx), int(sy + dy)

    def waystones(self) -> Dict[str, Tuple[int, int]]:
        """The three voting stones on the Moot, in cells (the behaviour's placement; the text layer draws the letters)."""
        if self.behaviour is not None and getattr(self.behaviour, "waystones", None):
            return {k: (int(round(x)), int(round(y))) for k, (x, y) in zip(LETTERS, self.behaviour.waystones)}
        sx, sy = self.terrain.site
        return {k: (int(sx + dx), int(sy + dy)) for k, (dx, dy) in zip(LETTERS, ((-12, -4), (0, -9), (12, -4)))}

    @staticmethod
    def _hut_footprint(camp: Dict[str, Any]) -> Tuple[int, int]:
        """Camp (x, y) = where the owner lies; the bake wants the footprint's top-left (8 wide; 6 tall for a hollow,
        one 8-cell tile for a tent / hut)."""
        tier = int(camp.get("tier") or 0)
        return int(camp["x"]) - 4, int(camp["y"]) - (6 if tier <= 0 else 8)

    def _marks_build(self, now: float) -> bool:
        """The marks dict bake.py paints from, rebuilt only when a camp / flower / field / bake_ver changed."""
        land = self.land
        camps = land.camps()
        flowers = land.marks_of_type("flower")
        fields = land.fields()
        sig = (land.bake_ver, tuple(sorted((c["key"], c["x"], c["y"], c["tier"]) for c in camps)),
               tuple((m["id"], m["x"], m["y"]) for m in flowers),
               tuple((f["owner"], f["x"], f["y"], land.field_stage(self.world.pip(f["owner"]).get("field") or {}, now)[0]) for f in fields
                     if self.world.pip(f["owner"]) is not None))
        if sig == self._marks_sig and self._marks:
            return False
        huts = []
        for c in camps:
            if c["x"] is None:
                continue
            hx, hy = self._hut_footprint(c)
            huts.append({"x": hx, "y": hy, "tier": int(c["tier"]), "owner": c["key"], "lit": False})
        wear = land.wear
        marks = {"wear": wear.copy() if bool(wear.any()) else None,
                 "huts": huts,
                 "fields": [{"x": f["x"], "y": f["y"], "owner": f["owner"], "stage": sig[3][i][3]} for i, f in enumerate(
                     [f for f in fields if self.world.pip(f["owner"]) is not None])],
                 "flowers": [{"x": m["x"], "y": m["y"], "owner": m["owner"], "variant": LAND.name_hash(m["owner"], "flower") % 5} for m in flowers],
                 "stones": []}
        self._marks, self._marks_sig = marks, sig
        self._marks_ver += 1
        self._tier_base = None
        return True

    def _trees(self, now: float) -> List[Dict[str, Any]]:
        out = []
        land = self.land
        orch = self.terrain.places.get("orchard")
        for m in land.marks_of_type("tree"):
            orchard = bool(orch and math.hypot(m["x"] - orch["x"], m["y"] - orch["y"]) <= orch["radius"])
            st = land.tree_stage(m, now, orchard)[0]
            out.append({"x": m["x"], "y": m["y"], "stage": st, "owner": m["owner"], "id": m["id"]})
        return out

    def _caster_for(self, trees: List[Dict[str, Any]]) -> np.ndarray:
        key = (self._marks_ver, tuple((t["x"], t["y"], t["stage"]) for t in trees))
        if self._caster is None or key != self._caster_key:
            self._caster = BK.casters_for_marks(self.terrain, self._marks, trees)
            self._caster_key = key
        return self._caster

    def _existing_bake_ver(self, season_idx: int, octant: int, current: int) -> Optional[int]:
        """The newest bake file on disk for this season / octant with a version <= current (a boot opens it in ~10 ms
        and repaints the marks that changed since, instead of painting the whole land again)."""
        d = BK.bake_dir(self.run_dir)
        if not os.path.isdir(d):
            return None
        best = None
        pre = "ground-%d-%d-o%d-v" % (self.terrain.seed, int(season_idx) % 4, int(octant) % 8)
        for f in os.listdir(d):
            if f.startswith(pre) and f.endswith(".npy") and "-p" not in f[len(pre):]:
                try:
                    v = int(f[len(pre):-4])
                except ValueError:
                    continue
                if v <= int(current) and (best is None or v > best):
                    best = v
        return best

    def _want_bake(self, now: float) -> "BK.GroundBake":
        N = self.nature
        season_idx = NAT.season_index(N.season(now))
        sun = N.sun(now)
        B = self.bakes.want(season_idx, sun, self._bake_ver_applied, self._marks)
        if id(B) not in self._bake_marks_ver:
            self._bake_marks_ver[id(B)] = self._marks_ver
        return B

    def _bake_sync(self, now: float) -> None:
        """Marks changed (bake_ver bumped by land): repaint the changed regions on the worker instead of a whole new
        bake, then rename the file to the new version so the next boot finds it (OPENWORLD 7.3 step 1)."""
        land = self.land
        changed = self._marks_build(now)
        cur = self.bakes.current
        if cur is not None and cur.ready and self._bake_marks_ver.get(id(cur)) != self._marks_ver:
            regions = self._mark_regions()
            self._bake_marks_ver[id(cur)] = self._marks_ver
            self.worker.submit(1, self._job_repaint, cur, tuple(regions), dict(self._marks))
        if land.bake_ver != self._bake_ver_applied and self._rename_pending != land.bake_ver:
            self._rename_pending = land.bake_ver
            bakes = [m.current for m in (self.bakes, self._bakes75) if m is not None and m.current is not None]
            self.worker.submit(2, self._job_rename_all, tuple(bakes), land.bake_ver)
        # trails: wear thresholds crossed since the bake's snapshot -> region repaints, batched every 2 s
        if (land.wear_version != self._wear_seen_ver or self._trail_full_check) and (self._wear_job_t is None or now - self._wear_job_t >= WEAR_REPAINT_S):
            self._wear_seen_ver = land.wear_version
            self._wear_job_t = now
            if cur is not None and cur.ready:
                self.worker.submit(3, self._job_trails, cur)
        if changed and self._bakes75 is not None and self._bakes75.current is not None and self._bakes75.current.ready:
            self.worker.submit(1, self._job_repaint, self._bakes75.current, tuple(self._mark_regions()), dict(self._marks))

    def _mark_regions(self) -> List[Tuple[int, int, int, int]]:
        regs = []
        for h in self._marks.get("huts", ()):
            regs.append((h["x"] - 2, h["y"] - 6, h["x"] + 18, h["y"] + 12))
        for f in self._marks.get("fields", ()):
            regs.append((f["x"] - 1, f["y"] - 1, f["x"] + 5, f["y"] + 4))
        for m in self._marks.get("flowers", ()):
            regs.append((m["x"] - 3, m["y"] - 4, m["x"] + 4, m["y"] + 2))
        return regs

    # worker jobs (never on the frame thread)
    def _job_repaint(self, B: "BK.GroundBake", regions: Sequence[Tuple[int, int, int, int]], marks: Dict) -> None:
        B.marks = marks
        if B.px != PPC:
            B._spr_cache.clear()
        for r in regions:
            x0, y0, x1, y1 = r
            B.repaint((max(0, x0), max(0, y0), min(self.terrain.w, x1), min(self.terrain.h, y1)))

    def _job_rename_all(self, bakes: Sequence["BK.GroundBake"], ver: int) -> None:
        """After the region repaints landed: the file(s) carry the new version so the next boot finds them; the
        manager's key follows (`_bake_ver_applied`), so no whole bake is ever started for a mark change."""
        for B in bakes:
            if not B.ready or B.bake_ver == ver:
                continue
            new = BK.bake_path(self.run_dir, self.terrain.seed, B.season_idx, B.octant, ver, B.px)
            try:
                os.replace(B.path, new)
                B.path, B.bake_ver = new, int(ver)
            except OSError as e:
                self.log("bake rename failed: %s" % e)
        self._bake_ver_applied = int(ver)
        self._rename_pending = None

    def _job_trails(self, B: "BK.GroundBake") -> None:
        land = self.land
        live = land.trail_tier_map()
        base = self._tier_base
        if self._trail_full_check:
            self._trail_full_check = False
            base = np.zeros_like(live)                       # an older file: assume no trail in it, repaint every worn tile
        if base is None:
            w = self._marks.get("wear")
            base = np.zeros_like(live) if w is None else ((w >= LAND.WEAR_PRESSED).astype(np.uint8) + (w >= LAND.WEAR_BARE).astype(np.uint8)
                                                           + (w >= LAND.WEAR_ROAD).astype(np.uint8))
        diff = live != base
        if not diff.any():
            self._tier_base = live
            return
        ys, xs = np.nonzero(diff)
        self._marks["wear"] = land.wear.copy()
        self._tier_base = live
        # group changed cells by 8-cell tile, then merge into a few bounding boxes (one per 88-cell strip row)
        tiles_ = set(zip((ys // 8).tolist(), (xs // 8).tolist()))
        rows: Dict[int, List[int]] = {}
        for ty, tx in tiles_:
            rows.setdefault(ty // 11, []).append(tx)
        for strip, txs in rows.items():
            tys = [ty for ty, tx in tiles_ if ty // 11 == strip]
            x0, x1 = min(txs) * 8, (max(txs) + 1) * 8
            y0, y1 = min(tys) * 8, (max(tys) + 1) * 8
            B.repaint((max(0, x0 - 2), max(0, y0 - 2), min(self.terrain.w, x1 + 2), min(self.terrain.h, y1 + 2)), self._marks)

    def _job_warm_props(self, octant: int, season: float) -> None:
        """The Moot's props and the glow discs are drawn lazily by the art module (10-20 ms each on first use): render
        them on the worker at boot so the first frames do not pay for them (a hatch never does either)."""
        sun = BK.octant_sun(octant)
        acc = L.hex_rgb(L.preset(None)["accent"])
        for i in range(3):
            props.waystone(acc, i, sun)
        for ph in range(4):
            props.campfire(ph, True, sun)
            props.beacon(ph, True, acc, sun)
        props.campfire(0, False, sun)
        props.beacon(0, False, (150, 150, 150), sun)
        for n in range(1, 6):
            props.cairn(n, sun)
        for age in range(3):
            for wind in range(4):
                props.tree(age, 0, wind, season, sun)
        for r, col in ((70, (255, 170, 80)), (110, (255, 180, 90)), (22, (255, 214, 130))):
            for k in range(0, 11):
                props.glow(r, col, round(0.2 + 0.05 * k, 2))
        for ph in range(3):
            _tuft(ph)

    def _job_minimap(self, key: Tuple, size: Tuple[int, int]) -> None:
        """The honest minimap picture: the WHOLE map, walked land saturated, unwalked at 55 % (no fog of war)."""
        T = self.terrain
        rgb = T.biome_rgb().astype(np.float32)
        grey = rgb.mean(axis=2, keepdims=True)
        walked = self.land.walked_mask()
        sat = np.where(walked[..., None], 1.0, 0.55).astype(np.float32)
        out = np.clip(grey + (rgb - grey) * sat, 0, 255).astype(np.uint8)
        im = Image.fromarray(out).resize(size, Image.Resampling.BOX).convert("RGBA")
        self._minimap = {key: im}
        self._minimap_job = None

    def minimap_image(self, size: Tuple[int, int] = (144, 66)) -> Optional[Image.Image]:
        """RGBA whole-map image with the walked / unwalked saturation split, refreshed on the worker when wear
        changes; None until the first one lands. The camera rectangle and dots are the text layer's."""
        if not self.booted:
            return None
        key = (self.land.wear_version // 50, tuple(size))
        im = self._minimap.get(key)
        if im is None and self._minimap_job != key:
            self._minimap_job = key
            self.worker.submit(4, self._job_minimap, key, tuple(size))
        return im if im is not None else (next(iter(self._minimap.values())) if self._minimap else None)

    # ------------------------------------------------------------------ frame
    def frame(self, ctx, size) -> Image.Image:
        """RGBA exactly `size`. Never raises."""
        w, h = int(size[0]), int(size[1])
        self.size = (w, h)
        t0 = _time.perf_counter()
        try:
            if ctx is None:
                ctx = _Ctx(now=_time.time(), frame=0)
            now = float(ctx.now if ctx.now is not None else _time.time())
            if self.refused:
                return self._fallback(w, h, now)
            if not self.booted:
                if self.terrain is None:
                    if self._terrain_err:
                        self.refused = "terrain: " + self._terrain_err
                    return self._fallback(w, h, now)               # the terrain thread is still running: a beat of meadow
                try:
                    self._boot(ctx)
                except Exception:
                    self._boot_fail += 1
                    self.log("boot failed (%d): %s" % (self._boot_fail, traceback.format_exc().strip().splitlines()[-1]))
                    if self._boot_fail <= 2:
                        self.log(traceback.format_exc())
                    if self._boot_fail >= 3:
                        self.refused = "boot failed 3 times: %s" % traceback.format_exc().strip().splitlines()[-1]
                    return self._fallback(w, h, now)
                if self.refused or not self.booted:
                    return self._fallback(w, h, now)
            dt = 1.0 / 30.0 if self._last_now is None else max(0.0, min(0.5, now - self._last_now))
            self._last_now = now
            self.events = []
            t1 = _time.perf_counter()
            self._ingest(ctx, now)
            self._honesty_check(now)
            ev = self.behaviour.tick(now, dt)
            self._idle_life(ev, now)
            self._layout(now)
            self._persist(ctx, now, ev, dt)
            self.events.extend(ev)
            t2 = _time.perf_counter()
            self._camera(ctx, now, dt, ev)
            self.nature.update(now, self.chat_rate(now))
            oct_ = BK.sun_octant(self.nature.sun(now))
            if oct_ != self._octant:
                self._octant = oct_                                  # ~every 1.75 h: sheets re-render on the worker
                for k, e in self.behaviour.entities.items():
                    self.sprites.request(k, e.tier, oct_, FIRST_FRAMES if e.is_awake() else SLEEP_FRAMES, SPRITE_PRIO_AWAKE)
                    self.sprites.request(k, e.tier, oct_, creatures.FRAMES, SPRITE_PRIO_REST)
            self._bake_sync(now)
            t3 = _time.perf_counter()
            rgb = self._ground(ctx, now, w, h)
            t4 = _time.perf_counter()
            self._glow(rgb, ctx, now, w, h)
            t5 = _time.perf_counter()
            self._sprites(rgb, ctx, now, w, h)
            t6 = _time.perf_counter()
            img = self._to_image(rgb)
            self.last_good = img
            self.frames += 1
            t7 = _time.perf_counter()
            self.sections = {"sim": (t2 - t1) * 1000, "camera+bake": (t3 - t2) * 1000, "ground": (t4 - t3) * 1000,
                             "glow": (t5 - t4) * 1000, "sprites": (t6 - t5) * 1000, "image": (t7 - t6) * 1000}
            self._budget((t7 - t0) * 1000.0)
            return img
        except Exception:
            self.errors += 1
            if self.errors <= 3 or self.errors % 300 == 0:
                self.log("frame failed (%d): %s" % (self.errors, traceback.format_exc().strip().splitlines()[-1]))
            self.events = [{"type": "world_error", "count": self.errors}]
            return self._fallback(w, h, float(getattr(ctx, "now", None) or _time.time()))

    def _idle_life(self, ev: List[Dict[str, Any]], now: float) -> None:
        """Between messages: an idle awake pip mutters one of ITS OWNER'S real tokens (allowlist + blocklist)."""
        b, w = self.behaviour, self.world
        for e_ in ev:
            if e_.get("type") == "mutter_due":
                p = w.pip(e_.get("pip"))
                ent = b.get(e_.get("pip"))
                if p is None or ent is None or not ent.is_awake() or p.get("_test"):
                    continue
                try:
                    from stream.chat_bridge import filter_words
                    words = filter_words(w.top_words(p), now)
                except Exception:
                    words = []
                if words:
                    word = words[int(self.rng.integers(len(words)))]
                    was_active = ent.last_active_t
                    b.speak(ent.key, now, word)
                    ent.last_active_t = was_active           # a mutter is the pip's, not the owner's: the sleep timer keeps counting
                    e_["type"], e_["text"] = "mutter", word

    def _layout(self, now: float) -> None:
        """Every entity's feet cell for this frame (one pass; camera, persist, render and entities() read it)."""
        pos = {}
        for k, e in self.behaviour.entities.items():
            pos[k] = self._pos_of(e, now)
        self._pos = pos

    def _camera(self, ctx, now: float, dt: float, ev: List[Dict[str, Any]]) -> None:
        b, cam = self.behaviour, self.camera
        inp = b.camera_inputs(now, getattr(ctx, "round_remaining", None))
        for a in inp["awake"]:                                  # head height per tier (cells at 1x) for the camera's HUD dead zone
            ent = b.get(a.get("key"))
            a["top"] = self._head_cells(int(ent.tier) if ent is not None else 3)
        T = self.terrain
        natural = []
        for kind in ("ford", "fell", "shore"):
            p = T.places.get(kind)
            if p:
                natural.append({"kind": kind, "x": p["x"], "y": p["y"], "name": p.get("label")})
        stops = self.land.survey_stops(natural)
        cam.allow_zoom = self.allow_zoom and self.degrade_level < 6
        cam.update(now, dt, awake=inp["awake"], seeds=inp["seeds"], events=ev, moot=inp["moot"], stops=stops, lead_key=b.newest_speaker)
        if self.force_zoom in CAM.ZOOMS and self.test_pips:
            cam.zoom = cam.zoom_prev = cam.target_zoom = self.force_zoom
            cam._clamp_pos()
        if self._cam_log is not None:
            self._camera_log(now, inp)

    _HEAD_CELLS: Dict[int, float] = {}

    @classmethod
    def _head_cells(cls, tier: int) -> float:
        """Feet -> head top in cells at 1x: the atlas anchor at the render zoom x SETTLER_SCALE / zoom / 4 px per cell."""
        v = cls._HEAD_CELLS.get(tier)
        if v is None:
            try:
                ay = creatures.anchor(max(0, min(3, tier)), SETTLER_RENDER_ZOOM)[1]
                v = float(ay) * SETTLER_SCALE / float(SETTLER_RENDER_ZOOM) / 4.0 + 0.5
            except Exception:
                v = CAM.HEAD_CELLS
            cls._HEAD_CELLS[tier] = v
        return v

    def _camera_log(self, now: float, inp: Dict[str, Any]) -> None:
        """TEST HOOK (KL_CAMERA_LOG=path, MODE=test, run dir under /tmp): one CSV row per frame for the camera QA:
        frame, now, mode, cx, cy, zoom, speed, awake, awake in view, awake inside the safe band, seeds, seeds in view.
        Reads only what the frame already computed; draws nothing; never on air."""
        cam = self.camera
        try:
            aw = inp.get("awake") or []
            sd = inp.get("seeds") or []
            in_view = sum(1 for a in aw if cam.in_view(a["x"], a["y"], 0.0))
            safe = 0
            for a in aw:
                r = cam.sim_to_screen(a["x"], a["y"], self.size)
                if r is not None and CAM.HUD_TOP_PX <= r[1] <= self.size[1] - CAM.HUD_BOTTOM_PX:
                    safe += 1
            sv = sum(1 for (x, y) in sd if cam.in_view(x, y, 0.0))
            under = 0
            for a in aw:                                            # the head box under a top HUD chip box (the owner's verdict)
                r = cam.sim_to_screen(a["x"], a["y"], self.size)
                if r is None:
                    continue
                top = r[1] - float(a.get("top") or CAM.HEAD_CELLS) * cam.scale(self.size)
                for bx0, by0, bx1, by1 in cam.hud_boxes:
                    if by0 <= 0 < by1 and bx0 <= r[0] <= bx1 and top < by1 and r[1] > by0:
                        under += 1
                        break
            framed = list(getattr(cam, "_nudge_pts", None) or [])
            f_under = 0
            min_head = 9999.0
            for x, y, top in framed:                                # the points the mode is framing (people, stones with their letters)
                r = cam.sim_to_screen(x, y, self.size)
                if r is None:
                    continue
                ty = r[1] - float(top) * cam.scale(self.size)
                for bx0, by0, bx1, by1 in cam.hud_boxes:
                    if by0 <= 0 < by1 and bx0 <= r[0] <= bx1 and r[1] > by0:
                        min_head = min(min_head, ty)
                        if ty < by1:
                            f_under += 1
                            break
            left = next((b for b in cam.hud_boxes if b[0] == 0), (0, 0, 0, 0))
            self._cam_log.write("%d,%.3f,%s,%.2f,%.2f,%.2f,%.2f,%d,%d,%d,%d,%d,%d,%.2f,%d,%d,%.2f,%.2f,%.1f,%dx%d\n" % (
                self.frames, now, cam.mode, cam.cx, cam.cy, cam.zoom, cam.speed, len(aw), in_view, safe, len(sd), sv, under, cam.hud_nudge,
                len(framed), f_under, cam.desired[1], cam.target[1], min_head if min_head < 9999 else -1.0, left[2], left[3]))
            if self.frames % 30 == 0:
                self._cam_log.flush()
        except Exception:
            pass

    # ------------------------------------------------------------------ the ground (7.3 steps 1-3)
    def _ground(self, ctx, now: float, w: int, h: int) -> np.ndarray:
        cam, N = self.camera, self.nature
        zoom = cam.zoom
        trees = self._trees(now)
        caster = self._caster_for(trees) if N.degrade["shadows"] else None
        if zoom == 0.75:
            if self._bakes75 is None:
                self._bakes75 = BK.BakeManager(self.run_dir, self.terrain, log=self.log, px_per_cell=3)
            B = self._bakes75.want(NAT.season_index(N.season(now)), N.sun(now), self._bake_ver_applied, self._marks)
            if id(B) not in self._bake_marks_ver:
                self._bake_marks_ver[id(B)] = self._marks_ver
            px = 3
            px0, py0, pw, ph = cam.bake_crop(px, zoom)
        else:
            B = self._want_bake(now)
            px = PPC
            px0, py0, pw, ph = cam.bake_crop(px, zoom)
        cx0, cy0, cw, ch, ox, oy = BK.view_cells(px0, py0, pw, ph, px)
        crop = B.ground(cx0 * px, cy0 * px, cw * px, ch * px)
        field = N.modulation((cx0, cy0, cw, ch), now, caster=caster)
        rgb = BK.apply(crop, field, ox, oy, pw, ph, N.last_sparkle, px)
        if (pw, ph) != (w, h):
            rgb = np.ascontiguousarray(BK.resample(rgb, (w, h)))
        if not rgb.flags.writeable:
            rgb = rgb.copy()
        self._view = (cam.view_rect(), w / float(cam.window()[0]))
        self.scale = self._view[1]
        self.origin = (0, 0)
        self._bake_now = B
        return rgb

    def to_screen(self, x: float, y: float) -> Tuple[float, float]:
        """Cells -> px inside the world region for the frame being drawn (no culling)."""
        (x0, y0, vw, vh), s = self._view
        return (x - x0) * s, (y - y0) * s

    # ------------------------------------------------------------------ glow after dusk (7.3 step 4)
    def _glow_sources(self, ctx, now: float) -> List[Tuple[float, float, int, Tuple[int, int, int], float]]:
        """(x, y cells, radius px at 1x, colour, strength): honest sources only."""
        out = []
        land = self.land
        night = NAT.night_amount(self.nature.hour(now))
        started = self._session_started(ctx)
        if land.hearth_lit(started if started is not None else (now - 3600.0)):
            hx, hy = self.moot_xy("hearth")
            out.append((hx, hy - 1.5, 70, (255, 170, 80), 0.50 + 0.20 * night))
        if self._beacon_lit(ctx, now):
            bx, by = self.moot_xy("beacon")
            acc = L.hex_rgb(L.preset(ctx.preset)["accent"])
            out.append((bx, by - 9, 110, (255, 180, 90), 0.35 + 0.20 * night))
        for c in land.camps():
            key = c["key"]
            e = self.behaviour.get(key)
            lit_t = self._fires.get(key)
            if lit_t is not None and (e is not None and e.is_awake() or now - lit_t < EMBERS_S):
                fx, fy = self._fire_xy(c)
                out.append((fx, fy - 1.5, 70, (255, 170, 80), (0.50 if e is not None and e.is_awake() else 0.22)))
            if c["tier"] >= 2 and e is not None and (e.is_awake() or self._slept_tonight(key, ctx)):
                out.append((c["x"], c["y"] - 3, 22, (255, 214, 130), 0.30 + 0.12 * night))
        for k, e in self.behaviour.entities.items():
            if e.is_awake():
                x, y = self._pos[k]
                col = creatures.palette(k)["main"]
                out.append((x, y - 3, 18, tuple(int(v) for v in col), 0.16 + 0.10 * e.energy))
        return out

    def _slept_tonight(self, key: str, ctx) -> bool:
        p = self.world.pip(key) or {}
        last = iso_to_epoch(p.get("last_seen_ts"))
        started = self._session_started(ctx)
        return last is not None and started is not None and last >= started - 60.0

    def _beacon_lit(self, ctx, now: float) -> bool:
        hb = iso_to_epoch((ctx.agent or {}).get("heartbeat_ts"))
        return hb is not None and (now - hb) < HEARTBEAT_FRESH_S

    @staticmethod
    def _fire_xy(camp: Dict[str, Any]) -> Tuple[float, float]:
        return float(camp["x"]) + 7.0, float(camp["y"]) + 2.0

    def _glow(self, rgb: np.ndarray, ctx, now: float, w: int, h: int) -> None:
        if self.degrade_level >= 2:
            return
        night = NAT.night_amount(self.nature.hour(now))
        if night < DUSK_GLOW_AT:
            return
        zoom = self.camera.zoom
        (x0, y0, vw, vh) = self._view[0]
        for (x, y, r, col, strength) in self._glow_sources(ctx, now):
            if x < x0 - r / 4.0 or x > x0 + vw + r / 4.0 or y < y0 - r / 4.0 or y > y0 + vh + r / 4.0:
                continue
            rr = max(4, int(round(r * zoom)))
            g = props.glow(rr, col, round(min(1.0, strength * min(1.0, night / 0.6)), 2))
            sx, sy = self.to_screen(x, y)
            BK.blit_add(rgb, g, int(round(sx)) - rr, int(round(sy)) - rr)

    # ------------------------------------------------------------------ live sprites (7.3 step 5)
    def _sprites(self, rgb: np.ndarray, ctx, now: float, w: int, h: int) -> None:
        b, N, cam = self.behaviour, self.nature, self.camera
        zoom = cam.zoom
        sun = N.sun(now)
        (x0, y0, vw, vh), s = self._view
        pad = 24.0
        live: List[Tuple[float, int, str, Any]] = []
        n = 0

        def visible(x, y):
            return (x0 - pad) <= x <= (x0 + vw + pad) and (y0 - pad) <= y <= (y0 + vh + pad)

        for letter, (x, y) in self.waystones().items():
            if visible(x, y):
                live.append((y, n, "waystone", (x, y, letter))); n += 1
        bx, by = self.moot_xy("beacon")
        if visible(bx, by):
            live.append((by, n, "beacon", (bx, by))); n += 1
        hx, hy = self.moot_xy("hearth")
        if visible(hx, hy):
            live.append((hy, n, "hearth", (hx, hy))); n += 1
        if self.land.stock:
            cx_, cy_ = self.moot_xy("cairn")
            if visible(cx_, cy_):
                live.append((cy_, n, "cairn", (cx_, cy_))); n += 1
        for t in self._trees(now):
            if visible(t["x"], t["y"]):
                live.append((t["y"], n, "tree", t)); n += 1
        for c in self.land.camps():
            lit_t = self._fires.get(c["key"])
            if lit_t is None:
                continue
            e = b.get(c["key"])
            if not (e is not None and e.is_awake() or now - lit_t < EMBERS_S):
                continue
            fx, fy = self._fire_xy(c)
            if visible(fx, fy):
                live.append((fy, n, "fire", (fx, fy, e is not None and e.is_awake()))); n += 1
        for k, e in b.entities.items():
            x, y = self._pos[k]
            if visible(x, y):
                live.append((y, n, "pip", e)); n += 1
        live.sort(key=lambda o: (o[0], o[1]))
        fire_phase = int(now * 6) % 4
        wind_phase = N.wind.atlas_phase(now)
        season = float(N.season(now))
        started = self._session_started(ctx)
        hearth_lit = self.land.hearth_lit(started if started is not None else (now - 3600.0))
        beacon_lit = self._beacon_lit(ctx, now)
        acc = L.hex_rgb(L.preset(ctx.preset)["accent"])
        for _, _, kind, data in live:
            if kind == "pip":
                self._blit_pip(rgb, data, now, zoom, s)
                continue
            if kind == "waystone":
                x, y, letter = data
                spr = props.waystone(acc, LETTERS.index(letter), sun)
            elif kind == "beacon":
                x, y = data
                spr = props.beacon(fire_phase if beacon_lit else 0, beacon_lit, acc if beacon_lit else (150, 150, 150), sun)
            elif kind == "hearth":
                x, y = data
                spr = props.campfire(fire_phase if hearth_lit else 0, hearth_lit, sun)
            elif kind == "cairn":
                x, y = data
                spr = props.cairn(min(5, 1 + self.land.stock // 4), sun)
            elif kind == "tree":
                x, y = data["x"], data["y"]
                spr = props.tree(NAT.tree_age_for_atlas(data["stage"]), LAND.name_hash(data["id"]) % 4, wind_phase, season, sun)
            else:
                x, y, awake = data
                spr = props.campfire(fire_phase if awake else 0, True, sun) if awake else props.campfire(0, False, sun)
            spr = self._zoomed_prop(spr, zoom)
            sx, sy = self.to_screen(x, y)
            BK.put(rgb, spr, int(round(sx)), int(round(sy)))

    _prop_zoom_cache: Dict[Tuple[int, float], np.ndarray] = {}

    def _zoomed_prop(self, spr: np.ndarray, zoom: float) -> np.ndarray:
        if zoom == 1.0:
            return spr
        key = (id(spr), zoom)
        out = self._prop_zoom_cache.get(key)
        if out is None:
            wz, hz = max(1, int(round(spr.shape[1] * zoom))), max(1, int(round(spr.shape[0] * zoom)))
            out = np.asarray(Image.fromarray(spr).resize((wz, hz), Image.Resampling.BOX if zoom < 1 else Image.Resampling.BILINEAR))
            if len(self._prop_zoom_cache) > 600:
                self._prop_zoom_cache.clear()
            self._prop_zoom_cache[key] = out
        return out

    def _blit_pip(self, rgb: np.ndarray, e, now: float, zoom: float, s: float) -> None:
        x, y = self._pos[e.key]
        sx, sy = self.to_screen(x, y)
        frame = e.frame_name(now)
        if frame.startswith("tuft") or e.state in ("seed", "hatching"):
            self._blit_tuft(rgb, e, now, sx, sy, zoom, phase=int(frame[-1]) if frame[-1].isdigit() else None)
            return
        facing = -1 if int(getattr(e, "side", 1) or 1) < 0 else 1
        hit = self.sprites.get(e.key, int(e.tier), frame, self._octant, facing, zoom)
        if hit is None:
            self._blit_tuft(rgb, e, now, sx, sy, zoom, phase=1)      # sheet not ready: the tuft one more beat, never a stall
            return
        spr, used = hit
        k = self.sprites.factor(zoom)                                # atlas (2x) px -> screen px
        ax, ay = creatures.anchor(int(e.tier), SETTLER_RENDER_ZOOM)
        lift = 0.0
        if used in HOP_BODY_FRAMES:                                  # body up the parabola, the shadow stays on the ground
            sh = self.sprites.shadow(int(e.tier), used, self._octant, zoom)
            BK.blit(rgb, sh, int(round(sx - ax * k)), int(round(sy - ay * k)))
            lift = -e.hop_lift(now) * creatures.height(int(e.tier), SETTLER_RENDER_ZOOM) * k
        if e.state in ("asleep", "burrowed"):
            spr = self._dimmed(spr, e.key, used, facing)
        BK.blit(rgb, spr, int(round(sx - ax * k)), int(round(sy - ay * k + lift)))

    _dim_cache: Dict[Tuple, np.ndarray] = {}

    def _dimmed(self, spr: np.ndarray, key: str, frame: str, facing: int) -> np.ndarray:
        """A sleeper at 80 %: at rest, not absent (absence is never punished; the 0.55 floor keeps it visible)."""
        ck = (key, frame, facing, spr.shape)
        out = self._dim_cache.get(ck)
        if out is None or out.shape != spr.shape:
            out = spr.copy()
            out[..., :3] = (out[..., :3].astype(np.uint16) * 205 // 255).astype(np.uint8)
            if len(self._dim_cache) > 600:
                self._dim_cache.clear()
            self._dim_cache[ck] = out
        return out

    def _blit_tuft(self, rgb: np.ndarray, e, now: float, sx: float, sy: float, zoom: float, phase: Optional[int] = None) -> None:
        if phase is None:
            age = now - e.seed_t
            phase = 0 if age < self.hold_s * 0.75 else (1 if age < self.hold_s else 2)
        phase = max(0, min(2, int(phase)))
        spr = self._zoomed_prop(_tuft(phase), zoom)
        BK.blit(rgb, spr, int(round(sx - spr.shape[1] / 2.0)), int(round(sy - spr.shape[0] + 3 * zoom)))

    # ------------------------------------------------------------------ output
    def _to_image(self, rgb: np.ndarray) -> Image.Image:
        h, w = rgb.shape[:2]
        if self._rgba is None or self._rgba.shape[:2] != (h, w):
            self._rgba = np.empty((h, w, 4), np.uint8)
            self._rgba[..., 3] = 255
        self._rgba[..., :3] = rgb
        return Image.fromarray(self._rgba, "RGBA")

    def _fallback(self, w: int, h: int, now: float) -> Image.Image:
        if self.last_good is not None and self.last_good.size == (w, h):
            return self.last_good
        hour = NAT.real_hour(now)
        tint = NAT.tint(hour, 0.0)
        g = tiles.season_colour("grass", 1.0) if hasattr(tiles, "season_colour") else (104, 164, 78)
        col = tuple(int(g[i] * tint[i]) for i in range(3)) + (255,)
        return Image.new("RGBA", (w, h), col)

    def _budget(self, ms: float) -> None:
        self.last_ms = ms
        self._ms.append(ms)
        self._all_ms.append(ms)
        if len(self._all_ms) > 3000:
            del self._all_ms[:-3000]
        if len(self._ms) > DEGRADE_WINDOW:
            del self._ms[:-DEGRADE_WINDOW]
        avg = sum(self._ms) / len(self._ms)
        if len(self._ms) >= DEGRADE_WINDOW:
            want = 0
            for i, lim in enumerate(DEGRADE_MS):
                if avg > lim:
                    want = i + 1
            if want > self.degrade_level:
                self.degrade_level += 1                          # one rung per window, never a jump
                self._clean = 0
                self._ms = []
                self.log("degrade -> level %d (avg %.1f ms)" % (self.degrade_level, avg))
                self._apply_degrade()
                return
        if avg <= DEGRADE_MS[0] * 0.75:
            self._clean += 1
            if self._clean >= RESTORE_FRAMES and self.degrade_level > 0:
                self.degrade_level -= 1
                self._clean = 0
                self.log("degrade <- level %d" % self.degrade_level)
                self._apply_degrade()
        else:
            self._clean = 0

    def _apply_degrade(self) -> None:
        lvl = self.degrade_level
        if self.nature is not None:
            self.nature.degrade["clouds"] = lvl < 1
            self.nature.degrade["wind"] = lvl < 1
            self.nature.degrade["shadows"] = lvl < 3
        if self.camera is not None:
            self.camera.allow_zoom = self.allow_zoom and lvl < 6

    # ------------------------------------------------------------------ public read API
    @property
    def degrade(self) -> Dict[str, Any]:
        lvl = self.degrade_level
        return {"glow": lvl < 2, "labels_on_speak": lvl >= 4, "bubbles_single": lvl >= 5, "level": lvl,
                "clouds": lvl < 1, "wind": lvl < 1, "shadows": lvl < 3, "plates_rotate": lvl < 4, "zoom_pinned": lvl >= 6 or not self.allow_zoom}

    def sim_to_screen(self, x: float, y: float, clamp: bool = False) -> Optional[Tuple[int, int]]:
        """Cells -> px inside the world region; None when off-view (the text layer culls), or clamped to the edge."""
        if self.camera is None:
            return None
        r = self.camera.sim_to_screen(x, y, self.size, margin_px=(0.0 if not clamp else 1e9))
        if r is None:
            return None
        sx, sy = r
        if clamp:
            sx, sy = min(self.size[0], max(0.0, sx)), min(self.size[1], max(0.0, sy))
        return int(round(sx)), int(round(sy))

    def entities(self, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """One dict per entity for the text layer: cells (x, y = feet), the screen box (sx, sy top-left, sw, sh),
        in_view, display_name (None for a seed), state, frame, bubble text (only while speaking), platform (waystone
        letter), tier, colour (hex), camp. Seeds carry no name and no key."""
        if not self.booted:
            return []
        t = now if now is not None else (self._last_now or 0.0)
        out = []
        zoom = self.camera.zoom
        s = self.size[0] / float(self.camera.window()[0])
        x0, y0, vw, vh = self.camera.view_rect()
        for e in self.behaviour.entities.values():
            d = e.to_dict(t)
            x, y = self._pos.get(e.key) or self._pos_of(e, t)
            seed = e.state in ("seed", "hatching")
            if seed:
                bw, bh = TUFT_W * zoom, TUFT_H * zoom
                ax, ay = bw / 2.0, bh - 3 * zoom
            else:
                k = self.sprites.factor(zoom)                      # the drawn size: SETTLER_SCALE x zoom of the 1x atlas
                W, H = creatures.size(int(e.tier), SETTLER_RENDER_ZOOM)
                ax_, ay_ = creatures.anchor(int(e.tier), SETTLER_RENDER_ZOOM)
                bw, bh, ax, ay = W * k, H * k, ax_ * k, ay_ * k
            sx, sy = (x - x0) * s, (y - y0) * s
            fx, fy = self._facing_of(e)
            p = self.world.pip(e.key) or {}
            camp = p.get("camp") if isinstance(p.get("camp"), dict) else None
            d.update({"x": round(x, 2), "y": round(y, 2), "sx": int(round(sx - ax)), "sy": int(round(sy - ay)),
                      "sw": int(round(bw)), "sh": int(round(bh)), "feet_sx": int(round(sx)), "feet_sy": int(round(sy)),
                      "in_view": bool((x0 <= x <= x0 + vw) and (y0 <= y <= y0 + vh)),
                      "fx": fx, "fy": fy, "colour": p.get("colour") or creatures.colour_hex(e.key),
                      "camp": dict(camp) if camp else (d.get("camp")), "burrow": None})
            if seed:
                d["display_name"] = None
                d["key"] = None                                   # not even the key leaves for a seed
                d["colour"] = None
                d["camp"] = None
            out.append(d)
        return out

    def plates(self, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """Camp plates for the text layer: {key, display_name (filtered), word, tier, night, last_seen_ts, colour,
        x, y (the door cell), sx, sy, in_view}. Every row resolves to a real pip with a real camp (12)."""
        if not self.booted:
            return []
        out = []
        for c in self.land.camps():
            pl = self.land.plate(c["key"], now)
            if pl is None:
                continue
            r = self.camera.sim_to_screen(c["x"], c["y"], self.size, margin_px=1e9)
            pl.update({"display_name": c["display_name"], "sx": int(round(r[0])) if r else None, "sy": int(round(r[1])) if r else None,
                       "in_view": self.camera.in_view(c["x"], c["y"], 4), "kind": c["kind"], "nights": c["nights"]})
            out.append(pl)
        return out

    def awake_count(self) -> int:
        return self.behaviour.awake_count() if self.booted else 0

    def asleep_count(self) -> int:
        return self.behaviour.asleep_count() if self.booted else 0

    def hatched_ever(self) -> int:
        return self.world.hatched_ever if self.booted else 0

    def platform_counts(self) -> Dict[str, List[str]]:
        """Who is STANDING at each waystone (state voting) - the embodied tally (11)."""
        return self.behaviour.platform_counts() if self.booted else {k: [] for k in LETTERS}

    def info(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Nature + camera + land facts for the plank, the land line, the time dial and the minimap."""
        if not self.booted:
            return {"booted": False, "refused": self.refused}
        t = now if now is not None else (self._last_now or 0.0)
        d = self.nature.describe(t)
        d.update({"camera": self.camera.stats(), "drift_stop": self.camera.drift_stop, "counts": self.land.counts(t),
                  "walked_fraction": round(self.land.walked_fraction(), 4), "settled": self.land.settled,
                  "hearth_lit": bool(self.land.hearth.get("lit_ts")), "bake": self.bakes.current.stats() if self.bakes.current else None,
                  "baking": bool(self.bakes.baking), "degrade": self.degrade, "zoom": self.camera.zoom, "booted": True})
        return d

    def stats(self) -> Dict[str, Any]:
        arr = np.array(self._all_ms[-300:]) if self._all_ms else None
        return {"frames": self.frames, "errors": self.errors, "last_ms": round(self.last_ms, 2),
                "avg_ms": round(sum(self._ms) / len(self._ms), 2) if self._ms else None,
                "avg300_ms": round(float(arr.mean()), 2) if arr is not None else None,
                "p95_ms": round(float(np.percentile(arr, 95)), 2) if arr is not None else None,
                "max_ms": round(float(arr.max()), 2) if arr is not None else None,
                "sections_ms": {k: round(v, 2) for k, v in self.sections.items()},
                "degrade": self.degrade, "entities": len(self.behaviour.entities) if self.booted else 0,
                "awake": self.awake_count(), "asleep": self.asleep_count(), "hatched_ever": self.hatched_ever(),
                "honesty_violations": self.honesty_violations, "test_pips": self.test_pips,
                "sprite_cache": creatures.cache_stats(), "sprites_ready": sum(len(v) for v in self.sprites.ready.values()),
                "worker": {"pending": self.worker.pending(), "done": self.worker.done, "errors": self.worker.errors},
                "camera": self.camera.stats() if self.camera else None,
                "bake": self.bakes.current.stats() if (self.bakes and self.bakes.current) else None,
                "baking": bool(self.bakes.baking) if self.bakes else False,
                "boot_ms": round(self._boot_ms), "refused": self.refused, "coords": "cells",
                "camps": len(self.land.camps()) if self.booted else 0}

    def distinct_recent_chatters(self, ctx, now: float) -> int:
        """Honesty reference: distinct real chatters in the last sleep window of THIS session."""
        if not self.booted:
            return 0
        hidden = set(str(u).lower() for u in ((ctx.mod or {}).get("hidden_users") or []))
        cutoff = now - self.sleep_after_s
        keys = set()
        for k, p in self.world.pips.items():
            if p.get("_test"):
                continue
            last = iso_to_epoch(p.get("last_seen_ts"))
            if last is not None and last >= cutoff and k not in hidden and self._in_session(last, ctx):
                keys.add(k)
        return len(keys)

    # ------------------------------------------------------------------ commands (verbs agent)
    def command(self, verb: str, actor: str, target: Optional[str] = None, arg: Optional[str] = None,
                now: Optional[float] = None) -> Tuple[bool, str]:
        """Positive-only verbs on the world. Rate limits, cooldown copy and blocklist are the verbs agent's job."""
        if not self.booted:
            return False, "the land is still waking"
        b, w, land = self.behaviour, self.world, self.land
        t = float(now if now is not None else (self._last_now or 0.0))
        actor = (actor or "").lower()
        tgt = (target or actor).lower().lstrip("@")
        me = b.get(actor)
        verb = (verb or "").lower()
        if verb == "banish":
            b.entities.pop(tgt, None)
            if w.banish(tgt, t):
                b.events.append({"type": "banish", "pip": tgt, "by": actor})
                return True, "ok"
            return False, "no such pip"
        if verb == "unbanish":
            if w.unbanish(tgt):
                b.events.append({"type": "unbanish", "pip": tgt, "by": actor})
                return True, "ok"
            return False, "not banished"
        if verb in ("name", "rename"):
            who = tgt if verb == "rename" else actor
            p = w.pip(who)
            if p is None:
                return False, "your pip is not awake yet" if verb == "name" else "no such pip"
            nick = None
            if verb == "name" and arg:
                nick = L.strip_non_bmp(str(arg))[:12] or None
            p["nickname"] = nick
            w.dirty = True
            b.events.append({"type": "nickname" if nick else "rename", "pip": who, "nickname": nick, "by": actor})
            return True, "ok"
        if me is None or not me.is_awake():
            return False, "your pip is not awake yet"
        x, y = self._pos.get(actor) or self._pos_of(me, t)
        if verb in ("feed", "pet"):
            other = b.get(tgt)
            if w.pip(tgt) is None:
                return False, "no pip called @%s here" % tgt
            w.care(tgt, actor, verb, t)
            if verb == "feed":
                b.carry(actor, t)
            if other is not None and other.is_awake():
                b.care_received(tgt, t, actor)
                if me.platform is None and tgt != actor:
                    ox, oy = self._pos.get(tgt) or self._pos_of(other, t)
                    b.walk_to(actor, (ox + (-6.0 if ox > x else 6.0), oy), t)
                else:
                    b.hop(actor, t)
                b.events.append({"type": verb, "pip": tgt, "by": actor, "asleep": False})
            else:
                b.events.append({"type": verb, "pip": tgt, "by": actor, "asleep": True})
            return True, "ok"
        if verb == "gift":
            other = b.get(tgt)
            if w.pip(tgt) is None:
                return False, "no pip called @%s here" % tgt
            if other is not None and other.is_awake():
                return False, "gifts are for sleeping pips"
            w.gift(tgt, actor, t)
            b.events.append({"type": "gift", "pip": tgt, "by": actor})
            return True, "ok"
        if verb == "dig":
            return False, "nothing to dig out here. try camp · plant · go"
        if verb == "plant":
            typ = (arg or "flower").strip().lower()
            if typ not in ("flower", "tree", "reed"):
                return False, "plant a flower, a tree or reeds"
            # the cell under the feet is the pip's own pressed grass (one step = wear 8 = "on a trail"), so the mark goes
            # on the nearest allowed cell within 3 (the same rule `camp` uses); the land's own reason is kept otherwise
            mx_, my_, reason = self._mark_near(actor, x, y, typ)
            if mx_ is None:
                return False, reason
            m, reason = land.add_mark(typ, mx_, my_, actor, t)
            if m is None:
                return False, reason
            b.events.append({"type": "plant", "pip": actor, "x": m["x"], "y": m["y"], "mark": typ, "id": m["id"]})
            self._bake_sync(t)
            return True, "ok"
        if verb == "camp":
            # 5.3: the cell the pip stands on is its own pressed grass (one step = wear 8 = "on a trail"), so the bedroll
            # goes on the nearest allowed cell within 6 (diagonals first, the same rule as the first sleep); the land's
            # own reason is kept when nothing nearby is allowed (water, the green, another's camp, a real road)
            cx_, cy_, reason = self._camp_near(actor, x, y)
            if cx_ is None:
                return False, reason
            camp, reason = land.set_camp(actor, cx_, cy_, t, check=True, session_id=self.session_id)
            if camp is None:
                return False, reason
            b.set_camp(actor, camp["x"], camp["y"])
            b.events.append({"type": "camp", "pip": actor, "x": camp["x"], "y": camp["y"], "tier": camp.get("tier", 0), "first": False})
            self._bake_sync(t)
            return True, "ok"
        if verb in ("fire", "light"):
            sx_, sy_ = self.terrain.site
            if math.hypot(x - sx_, y - sy_) <= self.terrain.moot_r + 6:
                if land.light_hearth(actor, t):
                    hx, hy = self.moot_xy("hearth")
                    b.events.append({"type": "hearth", "by": actor, "x": hx, "y": hy})
                    return True, "ok"
                return False, "your pip is not awake yet"
            camp = land.camp_of(actor)
            if not isinstance(camp, dict):
                return False, "no camp to light a fire at. say `camp` first"
            self._fires[actor] = t
            fx, fy = self._fire_xy(camp)
            b.events.append({"type": "fire", "pip": actor, "x": fx, "y": fy})
            if math.hypot(x - camp["x"], y - camp["y"]) > 10:
                b.walk_to(actor, (float(camp["x"]) + 3.0, float(camp["y"]) + 3.0), t)
            return True, "ok"
        if verb in ("go", "walk", "head"):
            if verb == "walk" and arg is not None and self._is_number(arg):
                return (True, "ok") if b.walk_to(actor, float(arg), t) else (False, "cannot walk there")
            where = (arg or "").strip() or ("@" + tgt if target else "")
            ok, reason = b.go(actor, where, t)
            if ok:
                b.events.append({"type": "go", "pip": actor, "place": where.lower().lstrip("@") if not where.startswith("@") else where,
                                 "place_label": (self.terrain.places.get(where.lower()) or {}).get("label")})
            return ok, reason
        if verb == "sow":
            f, reason = land.sow(actor, t)
            if f is None:
                return False, reason
            b.events.append({"type": "sow", "pip": actor, "x": f["x"], "y": f["y"]})
            self._bake_sync(t)
            return True, "ok"
        if verb == "harvest":
            ok, reason = land.harvest(actor, t)
            if ok:
                b.events.append({"type": "harvest", "pip": actor})
                self._bake_sync(t)
            return ok, reason
        if verb == "stack":
            if getattr(me, "carry", None):
                return False, "your hands are full"
            T = self.terrain
            cands = [(bx, by) for (bx, by, _v) in T.boulders]
            if not cands:
                return False, "no loose stones on this land"
            near = min(cands, key=lambda c: math.hypot(c[0] - x, c[1] - y))
            pick = T.nearest_passable(int(near[0]), int(near[1]) + 2, 12)
            cx_, cy_ = self.moot_xy("cairn")
            place = T.nearest_passable(int(cx_), int(cy_) + 3, 12)
            if not b.fetch(actor, (float(pick[0]), float(pick[1])), (float(place[0]), float(place[1])), t, "stone"):
                return False, "no way to the stones from here"
            b.events.append({"type": "stack", "pip": actor, "x": pick[0], "y": pick[1]})
            return True, "ok"
        if verb in ("wave", "sit", "duck", "dance"):
            return (True, "ok") if b.emote(actor, "sit" if verb == "duck" else verb, t) else (False, "not now")
        if verb == "hop":
            b.hop(actor, t)
            return True, "ok"
        if verb == "vote":
            return (True, "ok") if b.walk_to(actor, (arg or "").upper(), t) else (False, "cannot walk there")
        if verb == "forget":
            w.forget(actor)
            b.events.append({"type": "forget", "pip": actor})
            return True, "ok"
        if verb == "credits":
            b.start_credits(t)
            return True, "ok"
        return False, "unknown verb"

    def _camp_near(self, actor: str, x: float, y: float, r_max: int = 6) -> Tuple[Optional[int], Optional[int], str]:
        """The nearest cell within r_max of (x, y) where land.camp_allowed() says yes (the standing cell first, then
        rings, diagonals first so the bedroll never sits on the 4-neighbour spill). (None, None, reason) when none."""
        return self._near_allowed(lambda qx, qy: self.land.camp_allowed(actor, qx, qy), x, y, r_max, "you can't camp there")

    def _mark_near(self, actor: str, x: float, y: float, typ: str, r_max: int = 3) -> Tuple[Optional[int], Optional[int], str]:
        """The nearest cell within r_max of the feet where land.mark_allowed() says yes (`plant`: the standing cell is
        the pip's own pressed grass, so the flower goes one cell beside the footsteps, like the bedroll)."""
        return self._near_allowed(lambda qx, qy: self.land.mark_allowed(actor, qx, qy, typ), x, y, r_max, "nothing grows there")

    def _near_allowed(self, allowed, x: float, y: float, r_max: int, fallback: str) -> Tuple[Optional[int], Optional[int], str]:
        b = self.behaviour
        cx, cy = int(math.floor(x)), int(math.floor(y))
        first_reason = None
        ground = getattr(b, "ground", None)
        for r in range(0, r_max + 1):
            cands = [(cx + dx, cy + dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1) if max(abs(dx), abs(dy)) == r]
            cands.sort(key=lambda c: (-(abs(c[0] - cx) == abs(c[1] - cy)), abs(c[0] - cx) + abs(c[1] - cy)))
            for (qx, qy) in cands:
                if ground is not None and not ground.ok(qx + 0.5, qy + 0.5):
                    continue
                ok, reason = allowed(qx, qy)
                if ok:
                    return qx, qy, "ok"
                if first_reason is None:
                    first_reason = reason
        return None, None, first_reason or fallback

    @staticmethod
    def _is_number(s: Any) -> bool:
        try:
            float(s)
            return True
        except Exception:
            return False


def get_scene(**kw) -> SteadingScene:
    return SteadingScene(**kw)


# ----------------------------------------------------------------------------- self-test (RUN_DIR under /tmp, MODE=test)
def _self_test() -> bool:                                       # pragma: no cover - a harness, run by hand / the QA gate
    import json
    import shutil
    from stream.state_store import epoch_to_iso

    run_dir = os.environ.get("RUN_DIR") or "/tmp/lg-scene"
    rp = os.path.realpath(run_dir)
    if not (rp.startswith("/tmp/") or rp.startswith("/private/tmp/")):
        print("REFUSED: RUN_DIR must be under /tmp (got %r)" % run_dir, file=sys.stderr)
        return False
    if os.environ.get("MODE") != "test":
        print("REFUSED: MODE=test required", file=sys.stderr)
        return False
    keep_bakes = "--keep-bakes" in sys.argv
    if os.path.isdir(run_dir):
        for f in os.listdir(run_dir):
            p = os.path.join(run_dir, f)
            if f == "bake" and keep_bakes:
                continue
            (shutil.rmtree if os.path.isdir(p) else os.remove)(p)
    os.makedirs(run_dir, exist_ok=True)
    os.environ["RUN_DIR"] = run_dir
    ok_all = True
    results: Dict[str, Any] = {}

    def check(cond, msg):
        nonlocal ok_all
        print("  [%s] %s" % ("ok" if cond else "FAIL", msg))
        if not cond:
            ok_all = False

    def local_today(hour: float) -> float:
        lt = _time.localtime()
        midnight = _time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst))
        return midnight + hour * 3600.0

    sid = "selftest-%d" % int(_time.time())

    def mkctx(now, frame, chat_raw=(), chat=(), hb=None, votes=()):
        return _Ctx(now=now, frame=frame, session={"id": sid, "started_ts": epoch_to_iso(now0), "ending": False},
                    micro={"canvas_seed": 4471}, preset="kick", chat_raw=list(chat_raw), chat=list(chat), recent_votes=list(votes),
                    round={"number": 1}, round_remaining=120.0, mod={"hidden_users": []}, mod_paused=False,
                    agent={"heartbeat_ts": epoch_to_iso(hb) if hb else None}, macro={}, compositor_live={"selftest": True}, selftest=True)

    def raw(mid, name, text, t):
        return {"id": mid, "name": name, "text": text, "t": t, "type": "message", "badges": []}

    def clear(mid, name, text, t, first=False, n=None):
        return {"id": mid, "name": name, "display_name": name, "text": text, "text_clean": text, "t": t, "kind": "plain",
                "first_ever": first, "builder_n": n, "dropped": False, "history": False}

    def chat_line(mid, name, text, t):
        with open(os.path.join(run_dir, "chat.jsonl"), "a") as fh:
            fh.write(json.dumps({"id": mid, "username": name, "content": text, "ts": epoch_to_iso(t), "badges": []}) + "\n")

    # ------------------------------------------------------------------ A. a stranger at dusk: tuft -> hatch, camera, honesty
    print("[A] stranger at 18:07: tuft on the wind, hatch after the hold, FOLLOW, honesty")
    os.environ.pop("KL_TEST_PIPS", None)
    now0 = local_today(18.0 + 7 / 60.0)
    sc = SteadingScene(run_dir=run_dir, seed=7, log=lambda m: print("    scene: " + m), sleep_after_s=120.0)
    size = SCREEN
    names = ("willow_9", "kai_dnb")
    fps = 30.0
    t_boot = _time.perf_counter()
    while not sc.booted and _time.perf_counter() - t_boot < 20:
        sc.frame(mkctx(now0, 0), size)
        _time.sleep(0.01)
    check(sc.booted and not sc.refused, "booted (terrain thread + world.json schema %s) in %.0f ms; boot step %.0f ms" % (
        sc.world.schema if sc.world else None, (_time.perf_counter() - t_boot) * 1000, sc._boot_ms))
    check(sc.camera.mode == "DRIFT" and sc.awake_count() == 0, "0 awake: camera %s at (%.0f, %.0f), nobody drawn" % (sc.camera.mode, sc.camera.cx, sc.camera.cy))
    from stream.world.honesty import HonestyMonitor
    from stream.world import keepers as _K
    mon = HonestyMonitor(sc, enforce=True, log=lambda m: print("    honesty: " + m))
    keep = _K.Keepers(sc, log=lambda m: print("    keepers: " + m)).attach()
    mon_bad = 0
    tuft_in_view = 0
    seed_frame, hatch_frame, seed_named, first_body = None, None, False, None
    bake_wait_max = 0.0
    frames_during_bake = 0
    ms = []
    saved = {}
    for f in range(1, 900):
        now = now0 + f / fps
        raw_recs, clear_recs = [], []
        if f == 90:
            raw_recs.append(raw("m1", names[0], "hello land", now))
            chat_line("m1", names[0], "hello land", now)
        if f == 90 + int(3.2 * fps):
            clear_recs.append(clear("m1", names[0], "hello land", now0 + 90 / fps, first=True, n=3))
        if f == 400:
            raw_recs.append(raw("m2", names[1], "go river", now))
            chat_line("m2", names[1], "go river", now)
        if f == 400 + int(3.2 * fps):
            clear_recs.append(clear("m2", names[1], "go river", now0 + 400 / fps, first=True, n=4))
        if f == 520:
            ok, why = sc.command("go", names[1], arg="river", now=now)
            print("    command go river -> %s %s" % (ok, why))
            ex, ey = sc._pos[names[0]]
            cxr, cyr = int(round(ex)), int(round(ey))
            B0 = sc.bakes.current
            before = B0.crop((cxr - 4) * 4, (cyr - 6) * 4, 32, 24).copy() if B0.ready else None
            ok2, why2 = sc.command("camp", names[0], now=now)
            print("    command camp -> %s %s (bake_ver %d)" % (ok2, why2, sc.land.bake_ver))
            camp_spot = (cxr, cyr, before)
            ok3, why3 = sc.command("plant", names[0], arg="flower", now=now)
            print("    command plant flower -> %s %s" % (ok3, why3))
            ok4, why4 = sc.command("fire", names[0], now=now)
            print("    command fire -> %s %s" % (ok4, why4))
        ctx = mkctx(now, f, raw_recs, clear_recs)
        t1 = _time.perf_counter()
        img = sc.frame(ctx, size)
        dtms = (_time.perf_counter() - t1) * 1000
        if sc.bakes.baking:
            frames_during_bake += 1
            bake_wait_max = max(bake_wait_max, dtms)
        ms.append(dtms)
        rep = mon.check(ctx, now)
        if not rep.ok:
            mon_bad += len(rep.violations)
            if mon_bad <= 5:
                print("    honesty monitor: %r" % (rep.violations,))
        ents = sc.entities(now)
        for e in ents:
            if e["state"] in ("seed", "hatching"):
                if e.get("in_view"):
                    tuft_in_view += 1
                    if tuft_in_view == 20:
                        img.save(os.path.join(run_dir, "A_tuft.png"))
                        saved["tuft"] = os.path.join(run_dir, "A_tuft.png")
                if seed_frame is None:
                    seed_frame = f
                if e.get("display_name") is not None or e.get("key") is not None or e.get("colour") is not None:
                    seed_named = True
            if e["state"] not in ("seed", "hatching") and e.get("display_name") == names[0] and hatch_frame is None:
                hatch_frame = f
        for ev in sc.events:
            if ev.get("type") == "hatch":
                print("    hatch @ frame %d: %s x=%s y=%s (camera %s)" % (f, ev.get("display_name"), ev.get("x"), ev.get("y"), sc.camera.mode))
        if f in (150, 300, 600, 890):
            path = os.path.join(run_dir, "A_frame_%03d.png" % f)
            img.save(path)
            saved[f] = path
        if f == 300 and first_body is None:
            first_body = sc.sprites.has(names[0], 0, "idle0")
    check(seed_frame == 90, "tuft appears the frame the raw record lands (frame %s)" % seed_frame)
    check(not seed_named, "the tuft carries no name, no key, no colour during the hold")
    check(hatch_frame is not None and (hatch_frame - 90) / fps >= 3.0, "hatch >= 3 s after the seed (%.2f s)" % (((hatch_frame or 0) - 90) / fps))
    check(sc.honesty_violations == 0, "honesty violations == 0 (%d)" % sc.honesty_violations)
    check(mon_bad == 0, "HonestyMonitor (the panel's tender) reported %d violations over 900 frames: %s" % (mon_bad, mon.line()))
    check(keep.errors == 0 and getattr(sc, "keepers", None) is keep, "Keepers wrapper attached and ticked without errors (%d)" % keep.errors)
    check(tuft_in_view >= 20, "the tuft was in view for %d frames during the hold (camera eased to it)" % tuft_in_view)
    ref = sc.distinct_recent_chatters(mkctx(now, 899), now)
    check(sc.awake_count() == ref == 2, "awake_count %d == distinct recent chatters %d == 2" % (sc.awake_count(), ref))
    check(sc.camera.cuts == 0, "camera never cut (cuts=%d, max step speed %.1f cells/s <= 60)" % (sc.camera.cuts, sc.camera.max_step_speed))
    check(sc.camera.max_step_speed <= CAM.PAN_CAP + 1e-6, "pan cap held")
    check(sc.camera.mode in ("FOLLOW", "CLOSE", "EVENT"), "camera follows the real people (mode %s)" % sc.camera.mode)
    check(len(sc.land.camps()) >= 1, "camp pitched by a real chatter -> %d camps, bake_ver %d, %d flowers" % (len(sc.land.camps()), sc.land.bake_ver, len(sc.land.marks_of_type("flower"))))
    cx_, cy_, before = camp_spot
    c0 = sc.land.camp_of(names[0])
    # `camp` pitches on the nearest allowed cell within 6 of where the pip stands (_camp_near: the standing cell is its
    # own pressed grass, so the bedroll goes one cell beside the footsteps); the repaint is judged over the footprint
    # around the STANDING cell, which the real footprint overlaps by construction.
    after = sc.bakes.current.crop((cx_ - 4) * 4, (cy_ - 6) * 4, 32, 24).copy()
    changed = int(np.count_nonzero((after != before).any(axis=2))) if before is not None else -1
    near = c0 is not None and max(abs(int(c0["x"]) - cx_), abs(int(c0["y"]) - cy_)) <= 6
    check(changed > 50 and near, "the hollow's 8x6-cell footprint was REPAINTED into the memmapped bake on the worker: %d of 768 px changed; camp %s within 6 cells of the standing cell %s (file %s, pending jobs %d)" % (
        changed, (c0["x"], c0["y"]) if c0 else None, (cx_, cy_), sc.bakes.current.stats()["path"], sc.worker.pending()))
    check(sc.errors == 0, "frame errors == 0 (%d)" % sc.errors)
    check(bake_wait_max < 24.0, "bake thread never blocked a frame: %d frames during the bake, max %.1f ms" % (frames_during_bake, bake_wait_max))
    arr = np.array(ms[30:])
    results["A"] = {"avg_ms": round(float(arr.mean()), 2), "p95_ms": round(float(np.percentile(arr, 95)), 2), "max_ms": round(float(arr.max()), 2),
                    "frames_during_bake": frames_during_bake, "bake_frame_max_ms": round(bake_wait_max, 2), "seed_frame": seed_frame,
                    "hatch_frame": hatch_frame, "camps": len(sc.land.camps()), "camera": sc.camera.stats(), "saved": saved,
                    "bake": sc.bakes.current.stats() if sc.bakes.current else None, "boot_ms": round(sc._boot_ms)}
    print("    A: avg %.2f p95 %.2f max %.2f ms over %d frames; sections %s" % (arr.mean(), np.percentile(arr, 95), arr.max(), len(arr), sc.stats()["sections_ms"]))
    print("    A: entities %s" % [(e["key"], e["state"], e["x"], e["y"], e["sx"], e["sy"], e["in_view"]) for e in sc.entities(now)])
    print("    A: plates %s" % [(p["key"], p["word"], p["night"], p["x"], p["y"], p["in_view"]) for p in sc.plates(now)])
    print("[A2] a vote stands at a waystone; 2 min of quiet -> both walk home and sleep at their camps; a message wakes one")
    f0 = 900
    votes = [(names[1], "A", now0 + f0 / fps)]
    stood = None
    for f in range(f0, f0 + 240):
        now = now0 + f / fps
        img = sc.frame(mkctx(now, f, votes=votes), size)
        if sc.platform_counts()["A"] == [names[1]] and stood is None:
            stood = f
            img.save(os.path.join(run_dir, "A2_vote.png"))
    check(stood is not None and (stood - f0) / fps <= 8.0, "vote: %s walked to waystone A and stands there (platform_counts) after %.1f s" % (names[1], ((stood or f0) - f0) / fps))
    slept, woke = [], None
    f = f0 + 240
    now = now0 + f / fps
    # advance 130 s of world time at 0.5 s per frame (the behaviour's dt cap): quiet -> home -> sleep
    for k in range(300):
        now += 0.5
        f += 1
        img = sc.frame(mkctx(now, f), size)
        for ev in sc.events:
            if ev.get("type") == "sleep":
                slept.append((ev.get("pip"), ev.get("camp"), ev.get("new_camp")))
                print("    sleep: %s at camp %s (new %s) · land camps %d" % (ev.get("pip"), ev.get("camp"), ev.get("new_camp"), len(sc.land.camps())))
        if len(slept) >= 2 and sc.awake_count() == 0:
            break
    img.save(os.path.join(run_dir, "A2_asleep.png"))
    check(len(slept) == 2 and sc.awake_count() == 0 and sc.asleep_count() == 2, "both slept (%d sleep events, %d awake, %d asleep)" % (len(slept), sc.awake_count(), sc.asleep_count()))
    check(len(sc.land.camps()) == 2 and all(isinstance(sc.world.pip(n).get("camp"), dict) for n in names), "a first real sleep created a camp for each (%s)" % [(c["key"], c["x"], c["y"], c["kind"]) for c in sc.land.camps()])
    ents = sc.entities(now)
    check(all(e["state"] == "asleep" and e.get("camp") and abs(e["x"] - e["camp"]["x"]) <= 1 for e in ents), "sleepers lie at their own camp: %s" % [(e["key"], e["x"], e["y"], e.get("camp")) for e in ents])
    check(sc.camera.mode == "DRIFT", "0 awake again: the camera surveys (mode %s, stop %s)" % (sc.camera.mode, (sc.camera.drift_stop or {}).get("id")))
    f += 1
    now += 1 / fps
    sc.frame(mkctx(now, f, [raw("m3", names[0], "back", now)]), size)
    chat_line("m3", names[0], "back", now)
    wake_ev = [ev for ev in sc.events if ev.get("type") == "wake"]
    check(len(wake_ev) == 1 and wake_ev[0].get("pip") == names[0] and wake_ev[0].get("camp"), "a raw record wakes the sleeper at its camp this frame: %s" % (wake_ev[0] if wake_ev else None))
    check(sc.awake_count() == 1 and sc.camera.mode == "EVENT", "1 awake; the camera holds the wake (mode %s)" % sc.camera.mode)
    for k in range(60):
        f += 1
        now += 1 / fps
        img = sc.frame(mkctx(now, f), size)
    img.save(os.path.join(run_dir, "A2_woke.png"))
    check(sc.errors == 0 and sc.honesty_violations == 0, "A2 clean (errors %d, honesty %d)" % (sc.errors, sc.honesty_violations))
    print("    A2: info %s" % {k: v for k, v in sc.info(now).items() if k in ("clock", "day_part", "wind", "season", "camera", "counts", "settled", "hearth_lit", "zoom")})
    print("    A2: stats %s" % {k: v for k, v in sc.stats().items() if k in ("frames", "errors", "avg300_ms", "p95_ms", "max_ms", "honesty_violations", "sprites_ready", "worker", "bake", "camps")})
    sc.world.save(now, force=True)
    cam_saved = dict(sc.land.camera() or {})

    # ------------------------------------------------------------------ B. hot-reload resume: a second scene on the same run dir
    print("[B] hot-reload resume on the same run dir (camera continues, sleepers at camps, no wake)")
    now_b = now + 0.5
    sc2 = SteadingScene(run_dir=run_dir, seed=7, log=lambda m: print("    scene2: " + m), sleep_after_s=120.0)
    t_boot = _time.perf_counter()
    while not sc2.booted and _time.perf_counter() - t_boot < 20:
        sc2.frame(mkctx(now_b, 0), size)
        _time.sleep(0.01)
    img = sc2.frame(mkctx(now_b + 1 / fps, 1), size)
    check(sc2.booted and sc2.bakes.current is not None and sc2.bakes.current.loaded_from_disk,
          "second boot loaded the bake from disk (%s) in %.0f ms; land bake_ver %d, file ver %s" % (
              sc2.bakes.current.stats() if sc2.bakes.current else None, sc2._boot_ms, sc2.land.bake_ver, sc2._bake_ver_applied))
    check(abs(sc2.camera.cx - float(cam_saved.get("x", -1))) < 2.5 and abs(sc2.camera.cy - float(cam_saved.get("y", -1))) < 2.5,
          "camera resumed at the persisted position (%.1f, %.1f) ~ saved (%s, %s) after one frame (<= 60 cells/s x 1/30 s)" % (
              sc2.camera.cx, sc2.camera.cy, cam_saved.get("x"), cam_saved.get("y")))
    for _ in range(90):                                              # the mark repaints + rename land on the worker
        sc2.frame(mkctx(now_b + 2 / fps, 2), size)
        _time.sleep(0.005)
    check(sc2._bake_ver_applied == sc2.land.bake_ver and sc2.bakes.current.bake_ver == sc2.land.bake_ver and not sc2.bakes.baking,
          "mark changes were REPAINTED into the existing bake and the file renamed to v%d (no whole bake started: %s)" % (
              sc2.land.bake_ver, sc2.bakes.current.stats()["path"]))
    check(sc2.awake_count() == 1 and sc2.asleep_count() == 1 and not any(ev.get("type") == "wake" for ev in sc2.events),
          "the owner who chatted inside the window resumed awake without a wake event, the other sleeps at its camp (%d awake, %d asleep)" % (sc2.awake_count(), sc2.asleep_count()))
    e_sleep = next((e for e in sc2.entities(now_b) if e["state"] == "asleep"), None)
    check(e_sleep is not None and e_sleep.get("camp") and abs(e_sleep["x"] - e_sleep["camp"]["x"]) <= 1, "the boot-placed sleeper lies at its camp: %s" % (
        ((e_sleep or {}).get("key"), (e_sleep or {}).get("x"), (e_sleep or {}).get("camp")),))
    check(sc2.honesty_violations == 0 and sc2.errors == 0, "clean second boot")
    results["B"] = {"boot_ms": round(sc2._boot_ms), "camera": sc2.camera.stats(), "bake": sc2.bakes.current.stats() if sc2.bakes.current else None}

    # ------------------------------------------------------------------ C. night 23:00, 0.75x with 60 test pips: the budget gate
    for label, n_pips, zoom, hour in (("C1", 20, 1.0, 18.1), ("C2", 60, 0.75, 18.1), ("C3", 20, 1.0, 23.0)):
        print("[%s] budget: %d test pips at %.2fx, %02.0f:00, 300 frames" % (label, n_pips, zoom, hour))
        os.environ["KL_TEST_PIPS"] = str(n_pips)
        nowc = local_today(hour)
        sc3 = SteadingScene(run_dir=run_dir, seed=11, log=lambda m: None, sleep_after_s=1200.0)
        sc3.allow_zoom = zoom != 1.0
        sc3.force_zoom = zoom
        t_boot = _time.perf_counter()
        while not sc3.booted and _time.perf_counter() - t_boot < 30:
            sc3.frame(mkctx(nowc, 0), size)
            _time.sleep(0.005)
        # warm: let the worker land the first frames of every test pip (never on the frame path); report how long
        def all_ready() -> bool:
            if not sc3.booted:
                return False
            for i in range(n_pips):
                e = sc3.behaviour.get("test-pip-%02d" % i)
                if e is None or not sc3.sprites.has(e.key, e.tier, "idle0"):
                    return False
            return True
        t_w = _time.perf_counter()
        k = 1
        while _time.perf_counter() - t_w < 90 and not all_ready():
            sc3.frame(mkctx(nowc + k / fps, k), size)
            k += 1
            _time.sleep(0.005)
        warm_ms = (_time.perf_counter() - t_w) * 1000
        check(sc3.booted and not sc3.refused, "test scene booted (refused=%r)" % sc3.refused)
        while sc3.booted and (sc3.bakes.baking or (sc3._bakes75 is not None and sc3._bakes75.baking)):
            sc3.frame(mkctx(nowc + k / fps, k), size)
            k += 1
            _time.sleep(0.005)
        # contended: the worker is still rendering the rest of the sheets (the on-air shape right after a busy hatch)
        msc = []
        for f in range(300):
            now = nowc + (k + 90) / fps + f / fps
            t1 = _time.perf_counter()
            img = sc3.frame(mkctx(now, k + 90 + f, hb=now - 10), size)
            msc.append((_time.perf_counter() - t1) * 1000)
        arr_c = np.array(msc[10:])
        lvl_c = sc3.degrade_level
        # steady: every sheet rendered, the ladder re-armed so glow / clouds / shadows are all on
        t_d = _time.perf_counter()
        while (sc3.worker.pending() or sc3.worker.busy) and _time.perf_counter() - t_d < 120:
            k += 1
            sc3.frame(mkctx(nowc + (k + 400) / fps, k + 400, hb=nowc), size)
            _time.sleep(0.005)
        drain_ms = (_time.perf_counter() - t_d) * 1000
        sc3.degrade_level, sc3._ms, sc3._clean = 0, [], 0
        sc3._apply_degrade()
        msc = []
        for f in range(300):
            now = nowc + (k + 800) / fps + f / fps
            t1 = _time.perf_counter()
            img = sc3.frame(mkctx(now, k + 800 + f, hb=now - 10), size)
            msc.append((_time.perf_counter() - t1) * 1000)
        arr = np.array(msc[10:])
        drawn = sum(1 for e in sc3.entities(now) if e["awake"] and e.get("origin") == "test")
        check(sc3.test_pips == n_pips and drawn == n_pips, "%d test pips awake and drawn (origin test, never persisted as real)" % drawn)
        check(sc3.camera.zoom == zoom, "zoom pinned at %.2fx for the test (%s)" % (zoom, sc3.camera.zoom))
        limit = 12.0
        check(float(arr.mean()) < limit, "steady scene avg %.2f ms < %.0f ms (p95 %.2f, max %.2f) at %.2fx with %d pips; glow/clouds/shadows on, level %d" % (
            arr.mean(), limit, np.percentile(arr, 95), arr.max(), zoom, n_pips, sc3.degrade_level))
        print("    %s contended (worker rendering sheets): avg %.2f p95 %.2f max %.2f ms, ladder reached level %d; drained in %.0f ms" % (
            label, arr_c.mean(), np.percentile(arr_c, 95), arr_c.max(), lvl_c, drain_ms))
        check(sc3.honesty_violations == 0 and sc3.errors == 0, "honesty 0, errors 0")
        path = os.path.join(run_dir, "%s_%dpips_%.2fx_%02.0fh.png" % (label, n_pips, zoom, hour))
        img.save(path)
        a = np.asarray(img.convert("RGB"), np.float32) / 255.0
        lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
        results[label] = {"pips": n_pips, "zoom": zoom, "hour": hour, "avg_ms": round(float(arr.mean()), 2), "p95_ms": round(float(np.percentile(arr, 95)), 2),
                          "max_ms": round(float(arr.max()), 2), "warm_ms": round(warm_ms), "sections_ms": sc3.stats()["sections_ms"],
                          "contended": {"avg_ms": round(float(arr_c.mean()), 2), "p95_ms": round(float(np.percentile(arr_c, 95)), 2),
                                        "max_ms": round(float(arr_c.max()), 2), "degrade_level_reached": lvl_c, "drain_ms": round(drain_ms)},
                          "frame_mean_lum": round(float(lum.mean()), 3), "frame_frac_above_0.12": round(float((lum > 0.12).mean()), 3),
                          "camera": sc3.camera.stats(), "saved": path, "sprites_ready": sc3.stats()["sprites_ready"], "degrade": sc3.degrade_level}
        print("    %s: avg %.2f p95 %.2f max %.2f ms · warm-up %.0f ms · sections %s · mean lum %.3f · %s" % (
            label, arr.mean(), np.percentile(arr, 95), arr.max(), warm_ms, sc3.stats()["sections_ms"], lum.mean(), path))
        if hour >= 22:
            check(float((lum > 0.12).mean()) >= 0.60, "night frame: %.0f%% of pixels above 0.12 luminance (the 0.55 floor)" % (100 * (lum > 0.12).mean()))
    os.environ.pop("KL_TEST_PIPS", None)

    # ------------------------------------------------------------------ D. degrade ladder + refusal path
    print("[D] degrade ladder steps one rung per window; the migration guard refuses to boot")
    sc4 = sc3
    lvl0 = sc4.degrade_level
    for k in range(DEGRADE_WINDOW + 2):
        sc4._budget(30.0)
    check(sc4.degrade_level == lvl0 + 1, "one rung after a 30-frame window over 14 ms (level %d)" % sc4.degrade_level)
    d = sc4.degrade
    check(d["clouds"] is False and d["wind"] is False and sc4.nature.degrade["clouds"] is False, "level 1 turns clouds + wind bands off for nature")
    for k in range(6 * (DEGRADE_WINDOW + 1)):
        sc4._budget(30.0)
    check(sc4.degrade_level == 6 and sc4.degrade["zoom_pinned"] and sc4.degrade["glow"] is False and sc4.degrade["bubbles_single"], "ladder tops out at 6: glow off, bubbles single, zoom pinned")
    bad_dir = os.path.join(run_dir, "refuse")
    os.makedirs(bad_dir, exist_ok=True)
    with open(os.path.join(bad_dir, "world.json"), "w") as fh:
        json.dump({"schema": 1, "pips": {"ghost": {"name": "ghost", "n": 1, "colour_idx": 0, "genome": {"salt": 0}, "born_ts": None,
                                                    "sessions_seen": 2, "state": "asleep"}}, "world": {}, "sessions": []}, fh)
    sc5 = SteadingScene(run_dir=bad_dir, seed=1, log=lambda m: print("    scene5: " + m))
    t_boot = _time.perf_counter()
    img5 = None
    while _time.perf_counter() - t_boot < 20 and not (sc5.booted or sc5.refused):
        img5 = sc5.frame(mkctx(now0, 0), size)
        _time.sleep(0.01)
    check(bool(sc5.refused) or sc5.booted, "a broken schema-1 file either migrates under the guard or is refused: refused=%r booted=%s" % (sc5.refused, sc5.booted))
    check(img5 is not None and img5.size == size, "the refusal path still returns a frame of the right size")
    results["D"] = {"refused": sc5.refused, "migration": sc5.world.migration if sc5.world else None}

    with open(os.path.join(run_dir, "selftest.json"), "w") as fh:
        json.dump(results, fh, indent=1, default=str)
    print("wrote %s" % os.path.join(run_dir, "selftest.json"))
    print("SELF-TEST %s" % ("PASS" if ok_all else "FAIL"))
    return ok_all


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(0 if _self_test() else 1)
    print(__doc__)
