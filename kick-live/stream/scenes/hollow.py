"""stream/scenes/hollow.py - PIP HOLLOW, the cave sim (WORLD.md 3, 6, 10, 11; stream/WORLD_API.md).

    from stream.scenes.hollow import CaveScene
    scene = CaveScene(run_dir=None, seed=None)          # run_dir defaults to $RUN_DIR; world.json lives there
    img = scene.frame(ctx, size)                        # RGBA exactly `size`; the 320x110 sim upscaled by an integer
    scene.events                                        # this frame's events (list of dicts; see WORLD_API.md)
    scene.entities()                                    # for the text layer: screen-space boxes, names, states, bubbles
    scene.awake_count() ; scene.asleep_count() ; scene.hatched_ever() ; scene.platform_counts()
    scene.command(verb, actor, target=None, arg=None, now=None) -> (ok, reason)     # verbs agent
    scene.sim_to_screen(x, y) -> (sx, sy) ; scene.scale ; scene.origin ; scene.degrade ; scene.stats()

The scene draws NO text: names, bubbles, platform letters and the plank are the text layer's job at screen scale
(nothing under 20 px). It draws rock, floor, soil, 16 burrows, three platforms, the Ledge, the cave mouth with the
real local-clock sky and the real moon phase, the lantern chain (lit only on a fresh keeper heartbeat), drips,
glowmoss, the glow buffer and every pip sprite.

Frame flow (every call): ingest ctx.chat_raw (seed drops / hops within one frame, nothing drawn from names) ->
ingest ctx.chat (moderated, past the hold: hatch with display_name, speak, wake) -> ctx.recent_votes (walk to a
platform) -> behaviour.tick -> persistence -> render -> upscale. `frame()` never raises: any error returns the
last good frame (or a dark cave with the sky), one stderr line per burst.

Degrade ladder (own render ms averaged over 30 frames): > 16 ms drops glow (`degrade["glow"] False`), > 20 ms sets
`labels_on_speak`, > 24 ms sets `bubbles_single`; one step restored every 300 clean frames. The flags are for the
text layer; the readout shows `world: glow off`.

HONESTY: entities exist only for real chat records (origin "chat") or, under KL_TEST_PIPS in a /tmp run dir in a
test mode, synthetic ones (origin "test"). Every frame `_honesty_check` removes any entity that violates that
and counts it in `stats()["honesty_violations"]`; the self-test asserts the count stays 0 and that
awake_count() == distinct real chatters in the last 20 min.
"""
from __future__ import annotations

import datetime as _dt
import math
import os
import re
import sys
import time as _time
import traceback
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stream import layout as L  # noqa: E402
from stream.state_store import iso_to_epoch  # noqa: E402
from stream.world import SIM_W, SIM_H, UPSCALE, HOLD_S, SLEEP_AFTER_S, test_pips_allowed  # noqa: E402
from stream.world import pips as P  # noqa: E402
from stream.world.behaviour import Behaviour, AWAKE_STATES  # noqa: E402
from stream.world.state import (WorldState, MOUTH_X, VOID_ROWS, FLOOR_ROWS, SOIL_ROWS, LEDGE_X, PLATFORMS,  # noqa: E402
                                PLATFORM_TOP, PLATFORM_LETTERS, BURROW_SLOTS, LANTERN_X, burrow_box, protected_mask)

NAME = "hollow"
GLOW_R = 12                          # 24x24 kernel
MOSS_R = 6                           # 12x12 kernel
GLOW_GAIN = 0.85
DEGRADE_MS = (16.0, 20.0, 24.0)
DEGRADE_WINDOW = 30
RESTORE_FRAMES = 300
DRIP_GAP = (2.0, 6.0)
DRIP_SPEED = 2.0                     # sim px per frame
STAR_N = 6
MOON_X, MOON_Y = 257, 3
SYNODIC = 29.530588853
NEW_MOON_EPOCH = 947182440.0         # 2000-01-06 18:14 UTC
HEARTBEAT_FRESH_S = 120.0
SAVE_S = 5.0
SEED_SINK_S = HOLD_S + 4.0
HISTORY_S = 60.0                     # a record older than this when first seen is boot/deploy history (ChatBridge.HISTORY_S)
_MOD_CMD_RE = re.compile(r"^\s*!(hide|unhide|pause|resume|kill|unkill|clear|banish|unbanish|rename)\b", re.IGNORECASE)
_BG = np.array(L.hex_rgb(L.COLORS["bg"]), dtype=np.uint8)
_ROCK = np.array(L.hex_rgb(L.COLORS["panel"]), dtype=np.uint8)
_EDGE = np.array(L.hex_rgb(L.COLORS["hairline"]), dtype=np.uint8)
_TEXT2 = np.array(L.hex_rgb(L.COLORS["text2"]), dtype=np.uint8)
_TEXT = np.array(L.hex_rgb(L.COLORS["text"]), dtype=np.uint8)
SKY_NIGHT = (L.hex_rgb("#0B0E14"), L.hex_rgb("#141A2A"))       # CONCEPT 5 / WORLD 6.1 (no new hexes)
SKY_DAY = (L.hex_rgb("#1D2B4A"), L.hex_rgb("#3A5F8A"))


def _log(msg: str) -> None:
    try:
        sys.stderr.write("hollow: %s\n" % msg)
        sys.stderr.flush()
    except Exception:
        pass


def _kernel(r: int, power: float = 2.0, hole: float = 0.0) -> np.ndarray:
    """Radial falloff kernel (2r x 2r). `hole` > 0 makes it a RING: zero within `hole` sim px of the centre (the
    body's own half-width) with a 1.5 px ramp, so a light name colour never dissolves its own angular outline."""
    ax = np.arange(-r, r, dtype=np.float32) + 0.5
    dpx = np.sqrt(ax[None, :] ** 2 + ax[:, None] ** 2)
    d = dpx / float(r)
    k = np.clip(1.0 - d, 0.0, 1.0) ** power
    if hole > 0:
        k = k * np.clip((dpx - hole) / 1.5, 0.0, 1.0)
        k[dpx < hole] = 0.0
    return k.astype(np.float32)


_RIM_CACHE: "Dict[Tuple, np.ndarray]" = {}
_SOIL = (_ROCK.astype(np.int16) * 0.8).astype(np.uint8)         # #0D1017, the soil tone (rock at 80 %)
SPECKLE_EDGE, SPECKLE_SOIL = 0.04, 0.06                          # rock texture: 4 % hairline tone, 6 % soil tone
PLATFORM_IDLE, PLATFORM_LIVE = 0.35, 0.60                        # platform top: accent at 35 %, 60 % only while someone stands


def sprite_rim(mask: np.ndarray, key: Tuple) -> np.ndarray:
    """1 sim px outer rim of a sprite mask (8-neighbour dilation minus the mask), padded by 1 on every side: shape
    (H + 2, W + 2). Painted in the void colour under the sprite so the angular silhouette stays a solid dark line
    against its own glow (art-rules.md 3). Cached per sprite key."""
    hit = _RIM_CACHE.get(key)
    if hit is not None:
        return hit
    p = np.pad(mask, 1, mode="constant", constant_values=False)
    dil = p.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                dil |= np.roll(np.roll(p, dy, 0), dx, 1)
    rim = dil & ~p
    rim[-1, :] = False                                           # never below the feet row (the floor / platform top)
    if len(_RIM_CACHE) > 2200:
        _RIM_CACHE.clear()
    _RIM_CACHE[key] = rim
    return rim


def daylight(now: float) -> float:
    """0 at night, 1 in the day, from the REAL local clock (ramps 5-8 h and 18-21 h)."""
    lt = _time.localtime(now)
    h = lt.tm_hour + lt.tm_min / 60.0
    if h < 5.0 or h >= 21.0:
        return 0.0
    if 5.0 <= h < 8.0:
        return (h - 5.0) / 3.0
    if 18.0 <= h < 21.0:
        return 1.0 - (h - 18.0) / 3.0
    return 1.0


def moon_phase(now: float) -> float:
    """0 = new, 0.5 = full, from the 2000-01-06 new moon and the 29.53 d synodic month."""
    return ((now - NEW_MOON_EPOCH) / 86400.0 % SYNODIC) / SYNODIC


class _Ctx(object):
    """Minimal ctx for standalone use (a real ctx from StateStore already behaves like this)."""
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return None

    def get(self, name, default=None):
        v = self.__dict__.get(name)
        return default if v is None else v


class CaveScene(object):
    name = NAME

    def __init__(self, run_dir: Optional[str] = None, seed: Optional[int] = None, log=None,
                 sleep_after_s: float = SLEEP_AFTER_S, hold_s: float = HOLD_S, name_filter=None):
        self.run_dir = run_dir or os.environ.get("RUN_DIR") or os.path.join(_ROOT, "run")
        self.log = log or _log
        self.seed = int(seed) if seed is not None else None
        self.sleep_after_s = float(sleep_after_s)
        self.hold_s = float(hold_s)
        self._name_filter = name_filter
        self.world: Optional[WorldState] = None
        self.behaviour: Optional[Behaviour] = None
        self.rng = np.random.default_rng(0)
        self.booted = False
        self.session_id: Optional[str] = None
        self.events: List[Dict[str, Any]] = []
        self.last_good: Optional[Image.Image] = None
        self.errors = 0
        self.frames = 0
        self.scale = UPSCALE
        self.origin = (0, 0)
        self.degrade_level = 0
        self._ms: List[float] = []
        self._clean = 0
        self.last_ms = 0.0
        self._static: Optional[np.ndarray] = None
        self._static_key: Optional[Tuple] = None
        self._terrain_ver = 0
        self._glow_k = _kernel(GLOW_R, 2.2, hole=4.0)       # ring: kernel[r < 4] = 0 (the body's own half-width)
        self._moss_k = _kernel(MOSS_R, 1.8)
        self._speckle: Optional[np.ndarray] = None            # per-session rock texture (seeded at boot)
        self._protected = protected_mask()
        self._seen_raw: Dict[str, float] = {}
        self._seen_clear: Dict[str, float] = {}
        self._seed_t: Dict[str, float] = {}
        self._votes_seen: Dict[str, Tuple[str, float]] = {}
        self._round_no: Optional[int] = None
        self._last_now: Optional[float] = None
        self._last_save: Optional[float] = None
        self.drips: List[List[float]] = []
        self._next_drip = 0.0
        self._stars: Optional[np.ndarray] = None
        self.honesty_violations = 0
        self.test_pips = 0
        self._n_hidden = 0
        self._ending_seen = False
        self._chat_ids_seen = 0

    # ------------------------------------------------------------------ boot
    def _boot(self, ctx) -> None:
        now = float(ctx.now or _time.time())
        self.world = WorldState(self.run_dir, log=self.log, name_filter=self._name_filter or self._default_filter())
        sess = ctx.session or {}
        self.session_id = sess.get("id") or None
        micro = ctx.micro or {}
        seed = self.seed if self.seed is not None else (int(micro.get("canvas_seed") or 41370704) ^ (P.name_hash(str(self.session_id)) & 0xFFFF))
        self.rng = np.random.default_rng(seed & 0xFFFFFFFF)
        self.behaviour = Behaviour(seed=seed, sleep_after_s=self.sleep_after_s, hold_s=self.hold_s)
        self.world.begin_session(self.session_id, now)
        rec = self.world.recompute_from_chat(now, self.session_id)
        self.log("boot: world.json %s, %d pips, chat.jsonl recompute %r" % (
            "loaded" if self.world.loaded_ok else "fresh", len(self.world.pips), rec))
        # every known pip starts asleep in a burrow (a real past chatter with a real last_seen); a message wakes it
        cutoff = now - self.sleep_after_s
        for i, (key, p) in enumerate(sorted(self.world.pips.items(), key=lambda kv: kv[1].get("last_seen_ts") or "")):
            slot = p.get("burrow") if p.get("burrow") is not None else (P.name_hash(key) % BURROW_SLOTS)
            e = self.behaviour.place_sleeper(key, int(p.get("tier") or 0), float(p.get("energy") or 0.6),
                                             int((p.get("genome") or {}).get("salt") or 0), slot,
                                             p.get("display_name") or self.world.name_filter(p.get("name") or key), t=now)
            self.world.set_state(key, "asleep", e.x, e.y, e.burrow)
            last = iso_to_epoch(p.get("last_seen_ts"))
            if last is not None and last >= cutoff and self._in_session(last, ctx):
                self._restore_awake(e, p, last, now)      # chatted within the awake window of THIS session: awake
        self._stars = None
        self._speckle = self.rng.random((SIM_H, SIM_W)).astype(np.float32)
        self._next_drip = now + self._u(*DRIP_GAP)
        self.test_pips = test_pips_allowed(self.run_dir, ctx)
        if self.test_pips:
            self._spawn_test_pips(now)
        self.booted = True

    def _restore_awake(self, e, p: Dict[str, Any], last: float, now: float) -> None:
        """Deploy continuity (journal 011: a relay child restart must be invisible): an owner who chatted inside the
        awake window resumes where world.json last saw the pip (its x, its platform when it was STANDING), with the
        sleep timer counting from their real last message, not from this boot. No wake event, no hop: nothing happened
        to the person. Nothing is invented: x/state/vote were written by _persist from a real entity."""
        from stream.world.behaviour import WANDER_X
        e.state = "awake"
        e.sleep_t = None
        e.wake_t = last
        e.last_active_t = last
        e.last_attention_t = last
        e.vx = 0.0
        e.target_x = None
        e.minutes_tonight = 0.0
        px = p.get("x")
        if px is not None:
            e.x = float(min(WANDER_X[1], max(WANDER_X[0], float(px))))
        e.y = float(FLOOR_ROWS[0])
        e.pause_until = now + self._u(0.5, 2.0)
        if p.get("state") == "voting" and p.get("vote") in PLATFORM_LETTERS:
            e.platform = p["vote"]
            e.state = "voting"
            e.y = float(PLATFORM_TOP)
        self.world.set_state(e.key, e.state, e.x, e.y, e.burrow, e.platform if e.state == "voting" else None)

    def _in_session(self, t: float, ctx) -> bool:
        started = iso_to_epoch((ctx.session or {}).get("started_ts"))
        return started is None or t >= started - 60.0

    def _default_filter(self):
        """display_name for boot-loaded pips: the bridge's blocklist path (builder #N on a hit); raw name never
        reaches a label without passing it."""
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
        """TEST ONLY (guarded by test_pips_allowed): synthetic pips hatched instantly, origin 'test'."""
        self.log("TEST HOOK: KL_TEST_PIPS=%d synthetic pips (run_dir %s, test mode)" % (self.test_pips, self.run_dir))
        for i in range(self.test_pips):
            key = "test-pip-%02d" % i
            p, created = self.world.ensure_pip(key, key, "test pip %d" % i, None, now - 10.0)
            p["_test"] = True
            board = self.world.data["world"]["board"]
            board["hatched"] = [k for k in board.get("hatched", []) if k != key]
            e = self.behaviour.seed_drop(key, now - self.hold_s - 1.0, origin="test")
            self.behaviour.hold_cleared(key, now - self.hold_s - 1.0, "test pip %d" % i, int(p.get("tier") or i % 4),
                                        0.4 + 0.6 * ((i * 7) % 10) / 10.0, int(p["genome"]["salt"]), created)
            e.seed_y = float(FLOOR_ROWS[0])

    def _u(self, a: float, b: float) -> float:
        return float(a + (b - a) * self.rng.random())

    # ------------------------------------------------------------------ ingest
    def _ingest(self, ctx, now: float) -> None:
        b, w = self.behaviour, self.world
        sess = ctx.session or {}
        sid = sess.get("id")
        if sid and sid != self.session_id:
            self.session_id = sid
            w.begin_session(sid, now)
        hidden = set(str(u).lower() for u in ((ctx.mod or {}).get("hidden_users") or []))
        owner = (os.environ.get("KICK_CHANNEL") or "atleastonce").strip().lower()
        # 1. raw records: within one frame a seed drops (nameless) or the owner's pip hops. Names are hashed, never drawn.
        #    Age gate (integration finding, three modules hit it): at boot ctx.chat_raw is the last 20 records of
        #    chat.jsonl, hours old. Those never seed, hop or wake anyone; a record older than HISTORY_S but inside this
        #    session's awake window (a relay deploy restart) may still wake its sleeper, silently.
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
            if w.pip(key) is not None:
                w.touch_seen(key, t)                              # the owner chatted NOW: presence reference moves with the wake
            e = b.get(key)
            if e is None:
                if w.pip(key) is None:
                    if aged:
                        continue                                  # the moderated copy (history) places it asleep
                    b.seed_drop(key, now)
                    self._seed_t[key] = now
                else:                                             # known pip missing an entity (banish undo etc.)
                    p = w.pip(key)
                    b.place_sleeper(key, int(p.get("tier") or 0), float(p.get("energy") or 0.6),
                                    int((p.get("genome") or {}).get("salt") or 0), p.get("burrow"), p.get("display_name"), t=now)
                    b.message(key, now)
            elif aged:
                if e.state in ("asleep", "burrowed") and e.key not in hidden:
                    b.message(key, now)                           # wake only; no hop for an old record
            else:
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
            elif e.state in ("asleep", "burrowed"):
                b.message(key, now)
            if e is not None and e.is_awake() and e.display_name is None:
                e.display_name = p.get("display_name")
            w.record_message(key, t, self.session_id, m.get("text_clean") or m.get("text"), history=False)
            w.visit(key, t)
            newt = w.update_tier(p)
            if newt is not None:
                b.set_tier(key, newt, now)
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
        # 3. votes: walk to the platform within one frame of the tally changing
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
        # 4. hidden users burrow; seeds past the hold with no clearance sink
        for e in list(b.entities.values()):
            if e.key in hidden and e.state not in ("burrowed", "seed", "hatching"):
                e.state = "burrowed"
                e.platform = None
                if e.burrow is None:
                    e.burrow = b.free_burrow(P.name_hash(e.key) % BURROW_SLOTS)
                bx, by, bw, bh = burrow_box(e.burrow)
                e.x, e.y = bx + bw / 2.0, float(by + bh - 1)
                b.events.append({"type": "burrowed", "pip": e.key, "reason": "hidden by mod"})
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

    @staticmethod
    def _is_mod(m: Dict[str, Any]) -> bool:
        for bdg in (m.get("badges") or []):
            s = str(bdg).lower()
            if "broadcaster" in s or "moderator" in s or s == "mod":
                return True
        return False

    def _ingest_history(self, m: Dict[str, Any], key: str, t: float, now: float, ctx) -> None:
        """A moderated record the previous compositor instance already showed (boot / relay-deploy history): it
        adds the (session, owner) pair, last_seen and the tier, and wakes the pip only when the record is inside this
        session's awake window. It never bubbles, never hops, never counts own_messages again (014.2), never
        writes woke_log."""
        b, w = self.behaviour, self.world
        p, created = w.ensure_pip(key, m.get("name") or key, m.get("display_name") or None, m.get("builder_n"), t)
        e = b.get(key)
        if e is None or e.state in ("seed", "hatching"):
            if e is not None:
                b.sink(key, now)                                  # a stray seed for a history record never hatches
            e = b.place_sleeper(key, int(p.get("tier") or 0), float(p.get("energy") or 0.6),
                                int((p.get("genome") or {}).get("salt") or 0), p.get("burrow"),
                                p.get("display_name") or ("builder #%s" % (p.get("n") or "?")), t=now)
            w.set_state(key, "asleep", e.x, e.y, e.burrow)
        if self._in_session(t, ctx):
            # only THIS session's records add a (session, owner) pair here; older ones were walked by
            # recompute_from_chat at boot (chat.jsonl is the source of truth, WORLD.md 3.1), and re-stamping them
            # with a per-record pseudo-session id inflated sessions_seen (integration finding, the 014.2 pattern)
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

    # ------------------------------------------------------------------ persistence per frame
    def _persist(self, ctx, now: float, events: List[Dict[str, Any]], dt: float) -> None:
        w, b = self.world, self.behaviour
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
            if p.get("state") != e.state or p.get("x") != int(round(e.x)):
                w.set_state(e.key, e.state, e.x, e.y, e.burrow, e.platform if e.state == "voting" else None)
        for ev in events:
            typ = ev.get("type")
            if typ == "hatch":
                p = w.pip(ev["pip"])
                if p is not None:
                    p["state"] = "awake"
            elif typ == "wake":
                care = w.take_care_log(ev["pip"])
                ev["care_log"] = care
                p = w.pip(ev["pip"])
                if p is not None:
                    last = iso_to_epoch(p.get("last_seen_ts"))
                    ev["away_s"] = (now - last) if last else None
            elif typ == "first_light":
                w.woke(ev["pip"], now)
            elif typ == "sleep":
                p = w.pip(ev["pip"])
                if p is not None:
                    p["last_seen_ts"] = p.get("last_seen_ts")
        for e in b.awake():
            p = w.pip(e.key)
            if p is not None:
                nt = w.update_tier(p)
                if nt is not None:
                    b.set_tier(e.key, nt, now)
        w.grow_moss(now)
        w.touch_session(now)
        if self._last_save is None or now - self._last_save >= SAVE_S:
            if w.save(now, force=False):
                self._last_save = now
            elif self._last_save is None:
                self._last_save = now

    # ------------------------------------------------------------------ honesty
    def _honesty_check(self) -> None:
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

    # ------------------------------------------------------------------ static cave layer
    def _static_layer(self, ctx, now: float) -> np.ndarray:
        terrain = self.world.terrain()
        lt = _time.localtime(now)
        key = (self._terrain_ver, id(terrain), ctx.preset, lt.tm_yday, lt.tm_hour, lt.tm_min)
        if self._static is not None and key == self._static_key:
            return self._static
        img = np.empty((SIM_H, SIM_W, 3), dtype=np.uint8)
        img[:] = _ROCK
        rock = ~terrain
        # rock is texture, not UI fill: seeded speckle (4 % hairline tone, 6 % soil tone) on every solid cell
        sp = self._speckle if self._speckle is not None else np.zeros((SIM_H, SIM_W), dtype=np.float32)
        img[rock & (sp < SPECKLE_EDGE)] = _EDGE
        img[rock & (sp >= SPECKLE_EDGE) & (sp < SPECKLE_EDGE + SPECKLE_SOIL)] = _SOIL
        img[terrain] = _BG
        # hairline edges: rock cells with a carved 4-neighbour
        p = np.pad(terrain, 1, mode="constant", constant_values=False)
        near = p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
        img[rock & near] = _EDGE
        # floor band and soil (soil speckled back with the rock tone so the lower wall is dug earth, not a fill)
        f0, f1 = FLOOR_ROWS
        img[f0:f1 + 1, :][~terrain[f0:f1 + 1, :]] = _EDGE
        s0 = SOIL_ROWS[0]
        soil_band = np.zeros((SIM_H, SIM_W), dtype=bool)
        soil_band[s0:, :] = True
        img[soil_band & rock] = _SOIL
        img[soil_band & rock & (sp < 0.05)] = _ROCK
        img[soil_band & rock & near] = _EDGE                       # the arched recess edge (a 1 px step arch, angular)
        for i in range(BURROW_SLOTS):                              # burrow floor: darker than the void by an edge
            x, y, w, h = burrow_box(i)
            img[y + h - 1, x:x + w] = _EDGE
        # platforms: preset accent at 35 % idle with hairline end caps; 60 % is painted in _dynamic while someone stands
        acc = np.array(L.hex_rgb(L.preset(ctx.preset)["accent"]), dtype=np.float32)
        top = (acc * PLATFORM_IDLE).astype(np.uint8)
        side = (acc * 0.2).astype(np.uint8)
        for x, w in PLATFORMS:
            img[PLATFORM_TOP, x:x + w] = top
            img[PLATFORM_TOP, x] = _EDGE
            img[PLATFORM_TOP, x + w - 1] = _EDGE
            img[PLATFORM_TOP + 1:PLATFORM_TOP + 3, x:x + w] = side
        # sky in the mouth (real local hour): 3-stop gradient over rows 0-13 of the open columns
        d = daylight(now)
        c0 = tuple(SKY_NIGHT[0][i] * (1 - d) + SKY_DAY[0][i] * d for i in range(3))
        c1 = tuple(SKY_NIGHT[1][i] * (1 - d) + SKY_DAY[1][i] * d for i in range(3))
        cm = tuple((c0[i] + c1[i]) / 2.0 for i in range(3))
        mouth_rows = range(0, 14)
        for r in mouth_rows:
            f = r / 13.0
            col = [c0[i] * (1 - f) * (1 - f) + cm[i] * 2 * f * (1 - f) + c1[i] * f * f for i in range(3)]
            row = terrain[r, MOUTH_X[0] - 4:MOUTH_X[1] + 4]
            seg = img[r, MOUTH_X[0] - 4:MOUTH_X[1] + 4]
            seg[row] = np.array(col, dtype=np.uint8)
        # moon (phase from the date), only visible enough at night
        if d < 0.7:
            self._draw_moon(img, terrain, now, 1.0 - d)
        # lantern chain (lowered/raised by the keeper heartbeat, drawn dynamic in _dynamic); nothing here
        self._static, self._static_key = img, key
        return img

    def _draw_moon(self, img: np.ndarray, terrain: np.ndarray, now: float, vis: float) -> None:
        ph = moon_phase(now)
        disc = np.array([[0, 1, 1, 1, 0], [1, 1, 1, 1, 1], [1, 1, 1, 1, 1], [1, 1, 1, 1, 1], [0, 1, 1, 1, 0]], dtype=bool)
        lit = np.zeros((5, 5), dtype=bool)
        # illuminated fraction 0..1..0 ; waxing lights from the right
        frac = 0.5 * (1.0 - math.cos(2.0 * math.pi * ph))
        cols = int(round(frac * 5))
        if ph <= 0.5:
            lit[:, 5 - cols:] = True
        else:
            lit[:, :cols] = True
        lit &= disc
        dark = disc & ~lit
        bright = (_TEXT.astype(np.float32) * (0.55 + 0.35 * vis)).astype(np.uint8)
        dim = (_TEXT2.astype(np.float32) * 0.35).astype(np.uint8)
        for r in range(5):
            for c in range(5):
                y, x = MOON_Y + r, MOON_X + c
                if 0 <= y < SIM_H and 0 <= x < SIM_W and terrain[y, x]:
                    if lit[r, c]:
                        img[y, x] = bright
                    elif dark[r, c]:
                        img[y, x] = dim

    # ------------------------------------------------------------------ dynamic layers
    def _stars_init(self) -> np.ndarray:
        rng = np.random.default_rng(P.name_hash("stars") ^ (self.behaviour.rng.integers(1 << 30) if self.behaviour else 7))
        pts = []
        terrain = self.world.terrain()
        tries = 0
        while len(pts) < STAR_N and tries < 200:
            tries += 1
            x = int(rng.integers(MOUTH_X[0], MOUTH_X[1]))
            y = int(rng.integers(0, 9))
            if terrain[y, x] and not (MOON_X - 1 <= x <= MOON_X + 5 and MOON_Y - 1 <= y <= MOON_Y + 5):
                pts.append((x, y, float(rng.uniform(3.0, 6.0)), float(rng.uniform(0, 6.28))))
        return np.array(pts, dtype=np.float32).reshape(-1, 4)

    def _dynamic(self, img: np.ndarray, ctx, now: float) -> None:
        d = daylight(now)
        if self._stars is None:
            self._stars = self._stars_init()
        if d < 0.6 and len(self._stars):
            for x, y, per, ph in self._stars:                       # twinkle on 3-6 s cycles (<= 1 Hz)
                k = 0.5 + 0.5 * math.sin(2 * math.pi * now / per + ph)
                v = (_TEXT.astype(np.float32) * (0.25 + 0.55 * k) * (1.0 - d)).astype(np.uint8)
                img[int(y), int(x)] = np.maximum(img[int(y), int(x)], v)
        # drips: 1 px lines falling 2 px/frame from the ceiling to the floor, then a 3-frame splash
        if now >= self._next_drip:
            x = int(self._u(LEDGE_X[1] + 4, SIM_W - 30))
            if MOUTH_X[0] - 2 <= x <= MOUTH_X[1] + 2:
                x = MOUTH_X[1] + 6
            col = self.world.terrain()[VOID_ROWS[0]:VOID_ROWS[0] + 6, x]      # the stepped ceiling: first carved row
            open_rows = np.nonzero(col)[0]
            y0 = float(VOID_ROWS[0] + (int(open_rows[0]) if len(open_rows) else 0))
            self.drips.append([float(x), y0, 0.0])
            self._next_drip = now + self._u(*DRIP_GAP)
        floor = float(FLOOR_ROWS[0])
        drip_c = (_TEXT2.astype(np.float32) * 0.55).astype(np.uint8)
        keep = []
        for dr in self.drips:
            x, y, splash = dr
            if splash > 0:
                dr[2] -= 1
                xi = int(x)
                img[int(floor) - 1, max(0, xi - 1):min(SIM_W, xi + 2)] = drip_c
                if dr[2] > 0:
                    keep.append(dr)
                continue
            y2 = y + DRIP_SPEED
            if y2 >= floor:
                dr[1], dr[2] = floor, 3.0
                self.events.append({"type": "drip_land", "x": int(x)})
                keep.append(dr)
            else:
                dr[1] = y2
                img[int(y2) - 1:int(y2) + 1, int(x)] = drip_c
                keep.append(dr)
        self.drips = keep[-12:]
        # platform tops: the 60 % accent only while a pip stands there (the tally you can see from the tile)
        acc = np.array(L.hex_rgb(L.preset(ctx.preset)["accent"]), dtype=np.float32)
        counts = self.behaviour.platform_counts()
        for letter, (x, w) in zip(PLATFORM_LETTERS, PLATFORMS):
            if counts.get(letter):
                img[PLATFORM_TOP, x + 1:x + w - 1] = (acc * PLATFORM_LIVE).astype(np.uint8)
        # moss body pixels (accent, pulsing at 0.25 Hz; glow added in _glow)
        for m in self.world.moss:
            pulse = 0.7 + 0.3 * math.sin(2 * math.pi * 0.25 * now + (m.get("x", 0) % 7))
            size = int(m.get("size") or 0)
            x, y = int(m.get("x", 0)), int(m.get("y", 0))
            col = (acc * pulse).astype(np.uint8)
            w = 1 + size
            img[max(0, y - (1 if size >= 2 else 0)):y + 1, max(0, x - w // 2):min(SIM_W, x - w // 2 + w)] = col
        # lantern chain at x 300: lowered + lit on a fresh keeper heartbeat, raised + dark otherwise
        agent = ctx.agent or {}
        hb = iso_to_epoch(agent.get("heartbeat_ts"))
        fresh = hb is not None and (now - hb) < HEARTBEAT_FRESH_S
        macro = (ctx.macro or {}).get("active")
        sway = int(round(math.sin(2 * math.pi * 0.5 * now))) if macro else 0
        chain_len = 10 if fresh else 4
        img[0:chain_len, LANTERN_X] = _EDGE
        lx = LANTERN_X + sway
        if fresh:
            flick = 0.75 + 0.25 * math.sin(2 * math.pi * 0.25 * now)
            img[chain_len:chain_len + 3, lx - 1:lx + 2] = (acc * 0.6 * flick).astype(np.uint8)
            img[chain_len + 1, lx] = (acc * 0.9 * flick).astype(np.uint8)
        else:
            img[chain_len:chain_len + 3, lx - 1:lx + 2] = _EDGE
            img[chain_len + 1, lx] = _ROCK

    def _glow(self, img: np.ndarray, ctx, now: float) -> np.ndarray:
        """Float light buffer: one 24x24 kernel per awake pip in its colour, brightness 0.4 + 0.6 x energy (curled
        40 %), a 12x12 moss kernel pulsing at 0.25 Hz. Light density IS the population meter."""
        buf = np.zeros((SIM_H, SIM_W, 3), dtype=np.float32)
        names = L.preset(ctx.preset)["names"]
        fog = ((ctx.micro or {}).get("weather") == "fog")
        lights_out = ((ctx.micro or {}).get("weather") == "lights-out")
        if not lights_out:
            k = self._glow_k if not fog else self._glow_k[6:18, 6:18]
            r = GLOW_R if not fog else 6
            for e in self.behaviour.entities.values():
                if not e.is_awake():
                    continue
                col = np.array(L.hex_rgb(names[P.colour_idx(e.key)]), dtype=np.float32) / 255.0
                br = (0.4 + 0.6 * e.energy) * (0.4 if e.state == "curled" else 1.0) * GLOW_GAIN
                cx, cy = int(e.x), int(e.draw_y(now)) - P.tier_box(e.tier)[1] // 2
                self._add_kernel(buf, k, r, cx, cy, col * br)
        acc = np.array(L.hex_rgb(L.preset(ctx.preset)["accent"]), dtype=np.float32) / 255.0
        for m in self.world.moss:
            pulse = 0.6 + 0.4 * math.sin(2 * math.pi * 0.25 * now + (m.get("x", 0) % 7))
            self._add_kernel(buf, self._moss_k, MOSS_R, int(m.get("x", 0)), int(m.get("y", 0)) - 1,
                             acc * pulse * (0.35 + 0.15 * int(m.get("size") or 0)))
        lit = np.clip(img.astype(np.float32) + buf * 255.0, 0, 255).astype(np.uint8)
        return lit

    @staticmethod
    def _add_kernel(buf: np.ndarray, k: np.ndarray, r: int, cx: int, cy: int, col: np.ndarray) -> None:
        y0, y1 = cy - r, cy + r
        x0, x1 = cx - r, cx + r
        ky0, kx0 = max(0, -y0), max(0, -x0)
        y0c, x0c = max(0, y0), max(0, x0)
        y1c, x1c = min(SIM_H, y1), min(SIM_W, x1)
        if y1c <= y0c or x1c <= x0c:
            return
        sub = k[ky0:ky0 + (y1c - y0c), kx0:kx0 + (x1c - x0c)]
        buf[y0c:y1c, x0c:x1c, :] += sub[:, :, None] * col[None, None, :]

    def _sprites(self, img: np.ndarray, ctx, now: float) -> None:
        for e in self.behaviour.entities.values():
            fr = e.frame_name(now)
            if fr.startswith("egg"):
                rgb, mask = P.egg(fr)
                w = mask.shape[1]
                x0 = int(e.x) - w // 2
                y1 = int(e.seed_y)
                rim_key = ("egg", fr)
            else:
                rgb, mask = P.sprite(e.key, e.salt, e.tier, fr, ctx.preset, e.facing)
                w = mask.shape[1]
                x0 = int(e.x) - w // 2
                y1 = int(round(e.draw_y(now))) + 1
                rim_key = (e.key, e.salt, e.tier, fr, e.facing)
            h = mask.shape[0]
            y0 = y1 - h
            # 1 sim px void rim around the silhouette (art-rules.md 3: the angular outline stays visible inside the glow)
            rim = sprite_rim(mask, rim_key)
            rx0, ry0 = x0 - 1, y0 - 1
            rsx0, rsy0 = max(0, -rx0), max(0, -ry0)
            rx0c, ry0c = max(0, rx0), max(0, ry0)
            rx1c, ry1c = min(SIM_W, rx0 + w + 2), min(SIM_H, ry0 + h + 2)
            if rx1c > rx0c and ry1c > ry0c:
                rm = rim[rsy0:rsy0 + (ry1c - ry0c), rsx0:rsx0 + (rx1c - rx0c)]
                img[ry0c:ry1c, rx0c:rx1c][rm] = _BG
            sx0, sy0 = max(0, -x0), max(0, -y0)
            x0c, y0c = max(0, x0), max(0, y0)
            x1c, y1c = min(SIM_W, x0 + w), min(SIM_H, y1)
            if x1c <= x0c or y1c <= y0c:
                continue
            m = mask[sy0:sy0 + (y1c - y0c), sx0:sx0 + (x1c - x0c)]
            region = img[y0c:y1c, x0c:x1c]
            if e.state in ("asleep", "burrowed"):
                src = (rgb[sy0:sy0 + (y1c - y0c), sx0:sx0 + (x1c - x0c)].astype(np.float32) * 0.45).astype(np.uint8)
                region[m] = src[m]
            else:
                region[m] = rgb[sy0:sy0 + (y1c - y0c), sx0:sx0 + (x1c - x0c)][m]

    # ------------------------------------------------------------------ frame
    def frame(self, ctx, size) -> Image.Image:
        """RGBA exactly `size`. Never raises."""
        w, h = int(size[0]), int(size[1])
        t0 = _time.perf_counter()
        try:
            if ctx is None:
                ctx = _Ctx(now=_time.time(), frame=0)
            now = float(ctx.now if ctx.now is not None else _time.time())
            if not self.booted:
                self._boot(ctx)
            dt = 1.0 / 30.0 if self._last_now is None else max(0.0, min(0.5, now - self._last_now))
            self._last_now = now
            self.events = []
            self._ingest(ctx, now)
            self._honesty_check()
            ev = self.behaviour.tick(now, dt)
            self._persist(ctx, now, ev, dt)
            self.events.extend(ev)
            sim = self._static_layer(ctx, now).copy()
            self._dynamic(sim, ctx, now)
            if self.degrade_level < 1:
                sim = self._glow(sim, ctx, now)
            self._sprites(sim, ctx, now)
            img = self._upscale(sim, w, h)
            self.last_good = img
            self.frames += 1
            ms = (_time.perf_counter() - t0) * 1000.0
            self._budget(ms)
            return img
        except Exception:
            self.errors += 1
            if self.errors <= 3 or self.errors % 300 == 0:
                self.log("frame failed (%d): %s" % (self.errors, traceback.format_exc().strip().splitlines()[-1]))
            self.events = [{"type": "world_error", "count": self.errors}]
            return self._fallback(w, h)

    def _upscale(self, sim: np.ndarray, w: int, h: int) -> Image.Image:
        k = max(1, min(w // SIM_W, h // SIM_H))
        self.scale = k
        big = Image.fromarray(sim, "RGB").resize((SIM_W * k, SIM_H * k), Image.NEAREST)   # integer nearest, C speed
        if big.size == (w, h):
            self.origin = (0, 0)
            return big.convert("RGBA")
        out = Image.new("RGBA", (w, h), L.COLORS["bg"])
        ox, oy = (w - SIM_W * k) // 2, (h - SIM_H * k) // 2
        self.origin = (ox, oy)
        out.paste(big, (ox, oy))
        return out

    def _fallback(self, w: int, h: int) -> Image.Image:
        if self.last_good is not None and self.last_good.size == (w, h):
            return self.last_good
        sim = np.empty((SIM_H, SIM_W, 3), dtype=np.uint8)
        sim[:] = _ROCK
        sim[VOID_ROWS[0]:VOID_ROWS[1] + 1, LEDGE_X[1]:] = _BG
        sim[0:14, MOUTH_X[0]:MOUTH_X[1]] = np.array(SKY_NIGHT[1], dtype=np.uint8)
        return self._upscale(sim, w, h)

    def _budget(self, ms: float) -> None:
        self.last_ms = ms
        self._ms.append(ms)
        if len(self._ms) > DEGRADE_WINDOW:
            del self._ms[:-DEGRADE_WINDOW]
        avg = sum(self._ms) / len(self._ms)
        if len(self._ms) >= DEGRADE_WINDOW:
            want = 0
            for i, lim in enumerate(DEGRADE_MS):
                if avg > lim:
                    want = i + 1
            if want > self.degrade_level:
                self.degrade_level = want
                self._clean = 0
                self._ms = []
                self.log("degrade -> level %d (avg %.1f ms)" % (want, avg))
                return
        if avg <= DEGRADE_MS[0] * 0.75:
            self._clean += 1
            if self._clean >= RESTORE_FRAMES and self.degrade_level > 0:
                self.degrade_level -= 1
                self._clean = 0
                self.log("degrade <- level %d" % self.degrade_level)
        else:
            self._clean = 0

    # ------------------------------------------------------------------ public read API
    @property
    def degrade(self) -> Dict[str, bool]:
        return {"glow": self.degrade_level < 1, "labels_on_speak": self.degrade_level >= 2,
                "bubbles_single": self.degrade_level >= 3, "level": self.degrade_level}

    def sim_to_screen(self, x: float, y: float) -> Tuple[int, int]:
        return (int(self.origin[0] + x * self.scale), int(self.origin[1] + y * self.scale))

    def entities(self, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """One dict per entity for the text layer: sim + screen coordinates, display_name (None for a seed), state,
        frame, bubble text (only while speaking), platform, tier. Seeds carry no name at all."""
        if not self.booted:
            return []
        t = now if now is not None else (self._last_now or 0.0)
        out = []
        k = self.scale
        for e in self.behaviour.entities.values():
            d = e.to_dict(t)
            w, h = (P.EGG_W, P.EGG_H) if e.state in ("seed", "hatching") else P.tier_box(e.tier)
            sx, sy = self.sim_to_screen(e.x - w / 2.0, d["y"] - h)
            d.update({"sx": sx, "sy": sy, "sw": w * k, "sh": (h + 1) * k, "colour": P.colour_hex(e.key, None)})
            if e.state in ("seed", "hatching"):
                d["display_name"] = None
                d["key"] = None                                   # not even the key leaves for a seed
            out.append(d)
        return out

    def awake_count(self) -> int:
        return self.behaviour.awake_count() if self.booted else 0

    def asleep_count(self) -> int:
        return self.behaviour.asleep_count() if self.booted else 0

    def hatched_ever(self) -> int:
        return self.world.hatched_ever if self.booted else 0

    def platform_counts(self) -> Dict[str, List[str]]:
        return self.behaviour.platform_counts() if self.booted else {k: [] for k in PLATFORM_LETTERS}

    def stats(self) -> Dict[str, Any]:
        return {"frames": self.frames, "errors": self.errors, "last_ms": round(self.last_ms, 2),
                "avg_ms": round(sum(self._ms) / len(self._ms), 2) if self._ms else None,
                "degrade": self.degrade, "entities": len(self.behaviour.entities) if self.booted else 0,
                "awake": self.awake_count(), "asleep": self.asleep_count(), "hatched_ever": self.hatched_ever(),
                "honesty_violations": self.honesty_violations, "test_pips": self.test_pips,
                "sprite_cache": P.cache_size(), "drips": len(self.drips), "moss": len(self.world.moss) if self.booted else 0}

    def distinct_recent_chatters(self, ctx, now: float) -> int:
        """Honesty reference: distinct real chatters in the last sleep window of THIS session (from ctx.chat_raw and
        the world's last_seen), excluding hidden users. The self-test compares awake_count() against it."""
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
        """Positive-only verbs on the world. Rate limits, cooldown copy and blocklist are the verbs agent's job;
        this only refuses what the world cannot do. Returns (ok, reason) where reason is plank-ready plain words."""
        if not self.booted:
            return False, "the cave is still waking"
        b, w = self.behaviour, self.world
        t = float(now if now is not None else (self._last_now or 0.0))
        actor = (actor or "").lower()
        tgt = (target or actor).lower().lstrip("@")
        me = b.get(actor)
        verb = (verb or "").lower()
        # mod ops and the nickname need a RECORD, not an awake actor (integration: the bridge's fallbacks go away)
        if verb == "banish":
            b.entities.pop(tgt, None)
            if w.banish(tgt, t):
                self._terrain_ver += 1
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
        if verb in ("feed", "pet"):
            other = b.get(tgt)
            if w.pip(tgt) is None:
                return False, "no pip called @%s here" % tgt
            w.care(tgt, actor, verb, t)
            if other is not None and other.is_awake():
                b.care_received(tgt, t, actor)
                if me.platform is None and tgt != actor:
                    b.walk_to(actor, other.x + (-8 if other.x > me.x else 8), t)
                else:
                    b.hop(actor, t)          # heading to / standing on a platform: the embodied vote is never cancelled by a verb
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
            # `dig` at your feet always finds rock: beside, then below, then the other side, then deeper; a pip standing on
            # a platform (protected footing) may reach the floor just past the footing (radius 16 instead of 8)
            x, y, f = int(me.x), int(me.y), int(me.facing or 1)
            cands = [((x + 4 * f, y + 2), 8), ((x, y + 3), 8), ((x - 4 * f, y + 2), 8), ((x + 6 * f, y + 3), 8),
                     ((x, y + 5), 8), ((x - 6 * f, y + 3), 8)]
            if me.state == "voting" and me.platform in PLATFORM_LETTERS:
                px, pw = PLATFORMS[PLATFORM_LETTERS.index(me.platform)]
                cands += [((px + pw + 3, FLOOR_ROWS[0] + 2), 16), ((px - 4, FLOOR_ROWS[0] + 2), 16),
                          ((px + pw + 3, FLOOR_ROWS[0] + 4), 16), ((px - 4, FLOOR_ROWS[0] + 4), 16)]
            why = "nothing to dig there"
            for (cx, cy), radius in cands:
                if w.dig_cells(cx, cy, self._protected) <= 0:
                    continue
                n, why = w.dig(actor, cx, cy, self._protected, radius=radius)
                if n:
                    self._terrain_ver += 1
                    b.events.append({"type": "dig", "pip": actor, "cells": n})
                    return True, "ok"
                if why == "dig cap reached tonight":
                    return False, why
            return False, why
        if verb == "plant":
            m = w.plant_moss(actor, int(me.x), int(me.y), t)
            b.events.append({"type": "plant", "pip": actor, "x": m["x"], "y": m["y"]})
            return True, "ok"
        if verb in ("wave", "sit", "duck"):
            return (True, "ok") if b.emote(actor, verb, t) else (False, "not now")
        if verb == "hop":
            b.hop(actor, t)
            return True, "ok"
        if verb == "vote":
            return (True, "ok") if b.walk_to(actor, (arg or "").upper(), t) else (False, "cannot walk there")
        if verb == "walk":
            try:
                return (True, "ok") if b.walk_to(actor, float(arg), t) else (False, "cannot walk there")
            except Exception:
                return False, "where?"
        if verb == "forget":
            w.forget(actor)
            b.events.append({"type": "forget", "pip": actor})
            return True, "ok"
        if verb == "credits":
            b.start_credits(t)
            return True, "ok"
        return False, "unknown verb"

    def protected(self) -> np.ndarray:
        """Cells `dig` may never carve (platform footings, mouth pillars, lantern column); public for the rounds engine."""
        return self._protected


def get_scene(**kw) -> CaveScene:
    return CaveScene(**kw)
