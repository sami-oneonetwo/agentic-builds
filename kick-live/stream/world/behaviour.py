"""stream/world/behaviour.py - what pips do, frame by frame (WORLD.md 2.2, 3.3, 6.4, 12 row 3).

    from stream.world.behaviour import Behaviour
    b = Behaviour(seed=41370704, sleep_after_s=1200.0, hold_s=3.0)
    b.seed_drop(key, t)                        # a record landed: nameless seed at the hashed x, within this frame
    b.hold_cleared(key, t, display_name, tier, energy, salt, first_ever)   # bridge cleared the hold: hatch
    b.sink(key, t)                             # hidden inside the hold: the seed sinks, nothing hatches
    b.place_sleeper(key, tier, energy, salt, slot, display_name)          # boot: a past chatter asleep in a burrow
    b.message(key, t)                          # existing pip, record landed (pre-hold): hop + brighten; asleep -> wake
    b.speak(key, t, text, learned_from=None)   # after the hold: bubble for 6 s; every awake pip faces the speaker
    b.walk_to(key, "A"|"B"|"C"|x, t) ; b.release_votes(t) ; b.hop(key, t) ; b.emote(key, "wave"|"sit"|"duck", t)
    b.care_received(key, t)                    # feed / pet landed on this pip: brighten, bob
    b.start_credits(t)                         # session end: one by one to the burrows, minutes tonight per pip
    events = b.tick(t, dt)                     # advance; returns this frame's events (see EVENTS below)
    b.entities ; b.awake() ; b.awake_count() ; b.asleep_count() ; b.platform_counts() ; b.newest_speaker

EVENTS (dicts, `type` first): seed, sink, hatch, wake, sleep, speak, hop, walk, arrive, leave_platform, blink,
tier_up, curl, uncurl, emote, credits, first_light. Every event carries `pip` (the lowercase key) except seed/sink
(`key` only: nothing about a seed may be drawn as a name). Consumers: audio (motifs, stings), the text layer
(labels, bubbles), rounds (arrive/leave -> platform tallies), the ticker.

Honest presence: an Entity exists only because `seed_drop`/`place_sleeper` was called for a real chat record
(origin "chat") or by the test-pip hook (origin "test", refused outside test mode by the scene). Nothing here
invents an entity. Absence is never punished: energy decays only while awake and unattended, never below the
curl floor, never while asleep. Speeds: 20-40 screen px/s = 5-10 sim px/s. Everything eases over 8-10 frames.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from stream.world import SIM_W, SIM_H, HOLD_S, SLEEP_AFTER_S
from stream.world import pips as P
from stream.world.state import (PLATFORMS, PLATFORM_TOP, PLATFORM_LETTERS, LEDGE_X, FLOOR_ROWS, BURROW_SLOTS,
                                burrow_box)

STATES = ("seed", "hatching", "awake", "walking", "voting", "curled", "asleep", "burrowed")
AWAKE_STATES = ("awake", "walking", "voting", "curled")
FLOOR_Y = FLOOR_ROWS[0]                  # feet row on the floor (88)
WANDER_X = (LEDGE_X[1] + 4, SIM_W - 28)  # floor x range pips wander (the Ledge is solid; the right wall holds scrolls)
SPEED_MIN, SPEED_MAX = 5.0, 10.0         # sim px/s  (20-40 screen px/s)
EASE_FRAMES = 9
BLINK_MIN, BLINK_MAX = 4.0, 7.0
BLINK_LEN = 0.15
SPEAK_S = 6.0
MOUTH_S = 1.0
HOP_S = 8.0 / 30.0
HOP_PX = 3.0
CURL_FLOOR = 0.2
DECAY_PER_MIN = 0.01
ATTENTION_S = 60.0
TWITCH_MIN, TWITCH_MAX = 8.0, 15.0
TWITCH_LEN = 0.2
SEED_FALL_PX_PER_FRAME = 2.0
SEED_TIMEOUT_S = HOLD_S + 4.0
CREDITS_GAP_S = 1.5
PLATFORM_STAND_SPACING = 3
VOTE_WALK_S = 2.0                        # a vote walk ARRIVES within 1-3 s (WORLD.md 4): speed = max(wander max, dist / 2 s)


def hashed_x(key: str, lo: int = WANDER_X[0], hi: int = WANDER_X[1]) -> float:
    """Landing x of a seed: sha1 of the lowercase name (the 31-hash shifts near-identical names to near-identical x)."""
    import hashlib
    h = int(hashlib.sha1(("x:" + (key or "").lower()).encode("utf-8")).hexdigest()[:8], 16)
    return float(lo + h % max(1, hi - lo))


class Entity(object):
    """One creature (or a nameless seed). Positions are sim px; y is the FEET row."""
    __slots__ = ("key", "origin", "state", "display_name", "tier", "energy", "salt", "x", "y", "facing", "vx",
                 "target_x", "target_y", "speed", "speed_max", "platform", "burrow", "seed_t", "seed_y", "hatch_t",
                 "cleared", "next_blink_t", "blink_until", "hop_t", "speak_until", "mouth_until", "text", "pause_until",
                 "last_active_t", "last_attention_t", "sleep_t", "twitch_t", "twitch_until", "emote", "emote_until",
                 "on_arrive", "minutes_tonight", "first_ever", "wake_t", "bob_phase", "born_t", "credits_done",
                 "learned_from", "walk_frame_t")

    def __init__(self, key: str, origin: str, t: float):
        self.key = key
        self.origin = origin
        self.state = "seed"
        self.display_name: Optional[str] = None
        self.tier = 0
        self.energy = 0.6
        self.salt = 0
        self.x = hashed_x(key)
        self.y = float(FLOOR_Y)
        self.facing = 1
        self.vx = 0.0
        self.target_x: Optional[float] = None
        self.target_y: Optional[float] = None
        self.speed = 0.0
        self.speed_max = SPEED_MIN
        self.platform: Optional[str] = None
        self.burrow: Optional[int] = None
        self.seed_t = t
        self.seed_y = 14.0
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
        self.sleep_t: Optional[float] = None
        self.twitch_t = t + TWITCH_MIN
        self.twitch_until = 0.0
        self.emote: Optional[str] = None
        self.emote_until = 0.0
        self.on_arrive: Optional[str] = None
        self.minutes_tonight = 0.0
        self.first_ever = False
        self.wake_t: Optional[float] = None
        self.bob_phase = (P.name_hash(key) % 60) / 60.0
        self.born_t = t
        self.credits_done = False
        self.learned_from: Optional[str] = None
        self.walk_frame_t = 0.0

    # -- read-only helpers ----------------------------------------------------------
    def is_awake(self) -> bool:
        return self.state in AWAKE_STATES

    def hop_offset(self, t: float) -> float:
        ph = (t - self.hop_t) / HOP_S
        if 0.0 <= ph <= 1.0:
            return -HOP_PX * math.sin(math.pi * ph)
        return 0.0

    def frame_name(self, t: float) -> str:
        """Which sprite frame to draw now (WORLD.md 6.2 frame list)."""
        if self.state == "seed":
            return "egg0"
        if self.state == "hatching":
            k = int(max(0.0, t - self.seed_t))                # one crack per second, under the 1 Hz rule
            return "egg%d" % min(2, k)
        if self.state in ("asleep", "burrowed"):
            return "curled" if t < self.twitch_until else "asleep"
        if self.state == "curled":
            return "curled"
        if self.emote and t < self.emote_until:
            return "%s%d" % (self.emote, int((t * 2.0) % 2))    # 2-frame emote at 1 Hz
        if t < self.blink_until:
            return "blink"
        if t < self.mouth_until:
            return "speak"
        if self.state == "walking" and abs(self.vx) > 0.5:
            return "walk%d" % int((t * 4.0) % 2)               # alternate legs every 250 ms
        return "idle%d" % int(((t + self.bob_phase * 2.0) * 0.5) % 2)   # 1 px bob at 0.5 Hz

    def draw_y(self, t: float) -> float:
        return self.y + self.hop_offset(t) if self.state not in ("seed", "hatching") else self.seed_y

    def to_dict(self, t: float) -> Dict[str, Any]:
        return {"key": self.key, "origin": self.origin, "state": self.state, "display_name": self.display_name,
                "tier": self.tier, "energy": round(self.energy, 3), "salt": self.salt, "x": self.x,
                "y": self.draw_y(t), "facing": self.facing, "frame": self.frame_name(t), "platform": self.platform,
                "burrow": self.burrow, "text": self.text if t < self.speak_until else None,
                "speaking": t < self.speak_until, "learned_from": self.learned_from, "first_ever": self.first_ever,
                "minutes_tonight": round(self.minutes_tonight, 2), "awake": self.is_awake()}


class Behaviour(object):
    def __init__(self, seed: int = 41370704, sleep_after_s: float = SLEEP_AFTER_S, hold_s: float = HOLD_S):
        self.rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
        self.sleep_after_s = float(sleep_after_s)
        self.hold_s = float(hold_s)
        self.entities: Dict[str, Entity] = {}
        self.newest_speaker: Optional[str] = None
        self.newest_speaker_t = -1e9
        self.first_light_done = False
        self.first_light_pending: Optional[str] = None   # the session's FIRST message came from a stranger's seed: first
                                                         # light waits for that hatch (a sleeper waking meanwhile does not take it)
        self.credits_active = False
        self._credits_queue: List[str] = []
        self._credits_next_t = 0.0
        self._last_t: Optional[float] = None
        self.events: List[Dict[str, Any]] = []
        self.colony_rule = "free"          # free / follow / scatter / huddle (rounds may set it)

    # ------------------------------------------------------------------ helpers
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
        return [e for e in self.entities.values() if e.is_awake()]

    def awake_count(self) -> int:
        return sum(1 for e in self.entities.values() if e.is_awake())

    def asleep_count(self) -> int:
        return sum(1 for e in self.entities.values() if e.state in ("asleep", "burrowed"))

    def hatched(self) -> List[Entity]:
        return [e for e in self.entities.values() if e.state not in ("seed", "hatching")]

    def platform_counts(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {k: [] for k in PLATFORM_LETTERS}
        for e in self.entities.values():
            if e.state == "voting" and e.platform in out:
                out[e.platform].append(e.key)
        return out

    def free_burrow(self, preferred: Optional[int] = None) -> int:
        used = {e.burrow for e in self.entities.values() if e.burrow is not None}
        if preferred is not None and (preferred not in used):
            return int(preferred) % BURROW_SLOTS
        for i in range(BURROW_SLOTS):
            if i not in used:
                return i
        return int(preferred if preferred is not None else 0) % BURROW_SLOTS   # 17+ sleepers share slots

    # ------------------------------------------------------------------ chat-driven entry points
    def seed_drop(self, key: str, t: float, x: Optional[float] = None, origin: str = "chat") -> Entity:
        """A record from a chatter with no pip: the nameless seed drops from the ceiling at the hashed x. Nothing
        about the name is stored for drawing; `key` is the lowercase username used only as the dict key."""
        key = (key or "").lower()
        e = self.entities.get(key)
        if e is not None:
            return e
        e = Entity(key, origin, t)
        if x is not None:
            e.x = float(x)
        e.state = "seed"
        e.seed_t = t
        e.seed_y = 14.0
        self.entities[key] = e
        if not self.first_light_done and self.first_light_pending is None and self.awake_count() == 0:
            self.first_light_pending = key           # WORLD.md 2.2: the session's first MESSAGE is first light, credited at hatch
        self._ev("seed", key=key, x=e.x)
        return e

    def hold_cleared(self, key: str, t: float, display_name: str, tier: int = 0, energy: float = 0.6, salt: int = 0,
                     first_ever: bool = True) -> Optional[Entity]:
        """The bridge cleared the hold (blocklist passed or `builder #N` chosen, no mod hide): the seed may hatch.
        The hatch itself lands when the egg has finished cracking (>= hold_s after the seed), so a fast clear never
        shortens the nameless period."""
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
        """Hidden by a mod inside the hold, or never cleared: the seed sinks into the soil. No hatch, no name."""
        key = (key or "").lower()
        e = self.entities.get(key)
        if e is None or e.state not in ("seed", "hatching"):
            return False
        del self.entities[key]
        self._ev("sink", key=key)
        if self.first_light_pending == key:
            self.first_light_pending = None          # the seed never hatched: first light goes to whoever is awake first
            if not self.first_light_done:
                awake = sorted(self.awake(), key=lambda o: (o.wake_t if o.wake_t is not None else o.born_t))
                if awake:
                    self.first_light_done = True
                    self._ev("first_light", pip=awake[0].key)
        return True

    def place_sleeper(self, key: str, tier: int, energy: float, salt: int, slot: Optional[int], display_name: Optional[str],
                      origin: str = "chat", t: float = 0.0) -> Entity:
        """Boot: a past chatter's pip asleep in its burrow (real record, real last_seen; it never acts as present)."""
        key = (key or "").lower()
        e = self.entities.get(key)
        if e is None:
            e = Entity(key, origin, t)
            self.entities[key] = e
        e.display_name = display_name
        e.tier, e.energy, e.salt = int(tier), float(energy), int(salt)
        e.cleared = True
        e.burrow = self.free_burrow(slot)
        bx, by, bw, bh = burrow_box(e.burrow)
        e.x, e.y = bx + bw / 2.0, float(by + bh - 1)
        e.state = "asleep"
        e.sleep_t = t
        e.vx = 0.0
        e.twitch_t = t + self._u(TWITCH_MIN, TWITCH_MAX)
        return e

    def message(self, key: str, t: float) -> Optional[Entity]:
        """A record from an existing pip's owner landed (pre-hold): hop + brighten within this frame; a sleeper wakes."""
        e = self.get(key)
        if e is None or e.state in ("seed", "hatching"):
            return e
        e.last_active_t = t
        e.last_attention_t = t
        e.energy = min(1.0, e.energy + 0.15)
        if e.state in ("asleep", "burrowed"):
            self._wake(e, t)
        else:
            if e.state == "curled":
                e.state = "awake"
                self._ev("uncurl", pip=e.key)
            e.hop_t = t
            self._ev("hop", pip=e.key)
        return e

    def _wake(self, e: Entity, t: float) -> None:
        e.state = "walking"
        e.wake_t = t
        e.sleep_t = None
        e.speed_max = self._u(SPEED_MIN, SPEED_MAX)
        e.speed = 0.0
        e.target_x = min(WANDER_X[1], max(WANDER_X[0], e.x + self._u(-12, 12)))
        e.target_y = float(FLOOR_Y)
        e.on_arrive = "idle"
        e.minutes_tonight = 0.0
        e.credits_done = False
        self._ev("wake", pip=e.key, burrow=e.burrow, only_light=(self.awake_count() == 1))
        if not self.first_light_done and self.first_light_pending is None and self.awake_count() == 1:
            # the session's first message came from a RETURNING chatter: that is first light too (WORLD.md 2.2)
            self.first_light_done = True
            self._ev("first_light", pip=e.key)

    def speak(self, key: str, t: float, text: str, learned_from: Optional[str] = None) -> Optional[Entity]:
        """After the hold: the owner's own words in a bubble for SPEAK_S; every awake pip turns to the speaker."""
        e = self.get(key)
        if e is None or e.state in ("seed", "hatching", "asleep", "burrowed"):
            return None
        e.text = text
        e.learned_from = learned_from
        e.speak_until = t + SPEAK_S
        e.mouth_until = t + MOUTH_S
        e.last_active_t = t
        self.newest_speaker, self.newest_speaker_t = e.key, t
        for o in self.entities.values():
            if o is not e and o.is_awake() and o.state != "walking":
                o.facing = 1 if e.x >= o.x else -1
        self._ev("speak", pip=e.key, text=text, learned_from=learned_from)
        return e

    def hop(self, key: str, t: float) -> None:
        e = self.get(key)
        if e is not None and e.is_awake():
            e.hop_t = t
            self._ev("hop", pip=e.key)

    def emote(self, key: str, kind: str, t: float) -> bool:
        e = self.get(key)
        if e is None or not e.is_awake() or kind not in ("wave", "sit", "duck"):
            return False
        e.emote, e.emote_until = kind, t + 2.0
        e.last_active_t = t
        self._ev("emote", pip=e.key, kind=kind)
        return True

    def care_received(self, key: str, t: float, by: Optional[str] = None) -> bool:
        e = self.get(key)
        if e is None:
            return False
        e.last_attention_t = t
        e.energy = min(1.0, e.energy + 0.10)
        if e.state == "curled":
            e.state = "awake"
            self._ev("uncurl", pip=e.key)
        if e.is_awake():
            e.hop_t = t
        return True

    def walk_to(self, key: str, target, t: float) -> bool:
        """target: a platform letter, or a sim x on the floor. Sleepers never walk (honest: the owner is absent)."""
        e = self.get(key)
        if e is None or not e.is_awake():
            return False
        if isinstance(target, str) and target.upper() in PLATFORM_LETTERS:
            letter = target.upper()
            if e.platform == letter and e.state == "voting":
                return True
            if e.state == "voting":
                self._ev("leave_platform", pip=e.key, platform=e.platform)
            idx = PLATFORM_LETTERS.index(letter)
            px, pw = PLATFORMS[idx]
            standing = len(self.platform_counts()[letter])
            spread = (standing % 8) * PLATFORM_STAND_SPACING - 10
            e.platform = letter
            e.target_x = float(px + pw / 2 + spread)
            e.target_y = float(PLATFORM_TOP)
            e.on_arrive = "vote"
        else:
            e.platform = None
            e.target_x = float(min(WANDER_X[1], max(WANDER_X[0], float(target))))
            e.target_y = float(FLOOR_Y)
            e.on_arrive = "idle"
        e.state = "walking"
        if e.y != float(FLOOR_Y) and e.target_y != e.y:
            e.y = float(FLOOR_Y)                       # step down off a platform first
        if e.on_arrive == "vote":                      # purposeful: the voter sees the tally count them within 1-3 s
            e.speed_max = max(SPEED_MAX, abs(e.target_x - e.x) / VOTE_WALK_S)
        else:
            e.speed_max = self._u(SPEED_MIN, SPEED_MAX)
        e.last_active_t = t
        self._ev("walk", pip=e.key, to=e.platform or int(e.target_x))
        return True

    def release_votes(self, t: float) -> None:
        """A new round opened: everyone standing on a platform steps down and wanders."""
        for e in list(self.entities.values()):
            if e.state == "voting" or e.platform is not None:
                had = e.platform
                e.platform = None
                if e.state == "voting":
                    e.state = "awake"
                    e.y = float(FLOOR_Y)
                    e.pause_until = t + self._u(0.2, 1.5)
                    self._ev("leave_platform", pip=e.key, platform=had)

    def start_credits(self, t: float) -> None:
        if self.credits_active:
            return
        self.credits_active = True
        self._credits_queue = [e.key for e in sorted(self.awake(), key=lambda e: e.x)]
        self._credits_next_t = t
        self._ev("credits_start", count=len(self._credits_queue))

    def set_tier(self, key: str, tier: int, t: float) -> None:
        e = self.get(key)
        if e is not None and int(tier) != e.tier:
            e.tier = int(tier)
            self._ev("tier_up", pip=e.key, tier=e.tier)

    # ------------------------------------------------------------------ the tick
    def tick(self, t: float, dt: Optional[float] = None) -> List[Dict[str, Any]]:
        if dt is None:
            dt = 1.0 / 30.0 if self._last_t is None else max(0.0, min(0.5, t - self._last_t))
        self._last_t = t
        for e in list(self.entities.values()):
            st = e.state
            if st == "seed" or st == "hatching":
                self._tick_seed(e, t)
            elif st in ("asleep", "burrowed"):
                self._tick_sleeper(e, t)
            else:
                self._tick_awake(e, t, dt)
        if self.credits_active:
            self._tick_credits(t)
        out, self.events = self.events, []
        return out

    def _tick_seed(self, e: Entity, t: float) -> None:
        if e.seed_y < FLOOR_Y:
            e.seed_y = min(float(FLOOR_Y), e.seed_y + SEED_FALL_PX_PER_FRAME)
            if e.seed_y >= FLOOR_Y:
                self._ev("seed_land", key=e.key, x=e.x)
        if e.cleared and t - e.seed_t >= self.hold_s:
            self._hatch(e, t)
        elif not e.cleared and t - e.seed_t > SEED_TIMEOUT_S:
            self.sink(e.key, t)

    def _hatch(self, e: Entity, t: float) -> None:
        e.state = "awake"
        e.y = float(FLOOR_Y)
        e.hatch_t = t
        e.born_t = t
        e.last_active_t = t
        e.last_attention_t = t
        e.pause_until = t + self._u(1.0, 2.5)
        e.next_blink_t = t + self._u(BLINK_MIN, BLINK_MAX)
        e.minutes_tonight = 0.0
        first_light = not self.first_light_done and (self.first_light_pending == e.key or
                                                     (self.first_light_pending is None and self.awake_count() == 1))
        ev = self._ev("hatch", pip=e.key, display_name=e.display_name, first_ever=e.first_ever, x=e.x,
                      only_light=(self.awake_count() == 1))
        if first_light:
            self.first_light_done = True
            self.first_light_pending = None
            self._ev("first_light", pip=e.key)
        for o in self.entities.values():
            if o is not e and o.is_awake():
                o.facing = 1 if e.x >= o.x else -1
        return None

    def _tick_sleeper(self, e: Entity, t: float) -> None:
        if t >= e.twitch_t:
            e.twitch_until = t + TWITCH_LEN
            e.twitch_t = t + self._u(TWITCH_MIN, TWITCH_MAX)

    def _tick_awake(self, e: Entity, t: float, dt: float) -> None:
        e.minutes_tonight += dt / 60.0
        if t >= e.next_blink_t:                                   # blink every 4-7 s
            e.blink_until = t + BLINK_LEN
            e.next_blink_t = t + self._u(BLINK_MIN, BLINK_MAX)
            self._ev("blink", pip=e.key)
        if t - e.last_attention_t > ATTENTION_S:                  # cosmetic dim: -0.01 per unattended minute
            e.energy = max(0.0, e.energy - DECAY_PER_MIN * dt / 60.0)
        if e.state != "curled" and e.energy < CURL_FLOOR and e.state in ("awake",):
            e.state = "curled"
            e.vx = 0.0
            self._ev("curl", pip=e.key)
        # 20 min of silence -> yawn, walk to the burrow, sleep (never while standing on a platform mid-round? it
        # leaves the platform: a sleeper cannot vote)
        if not self.credits_active and e.state != "walking" and t - e.last_active_t >= self.sleep_after_s and e.on_arrive != "sleep":
            self._go_to_burrow(e, t, reason="quiet")
        if e.state == "walking":
            self._move(e, t, dt)
        elif e.state == "awake" and t >= e.pause_until and not self.first_light_done is None:
            self._pick_wander(e, t)

    def _go_to_burrow(self, e: Entity, t: float, reason: str) -> None:
        if e.burrow is None:
            e.burrow = self.free_burrow(P.name_hash(e.key) % BURROW_SLOTS)
        bx, by, bw, bh = burrow_box(e.burrow)
        if e.state == "voting":
            self._ev("leave_platform", pip=e.key, platform=e.platform)
        e.platform = None
        e.state = "walking"
        e.y = float(FLOOR_Y)
        e.target_x = float(bx + bw / 2.0)
        e.target_y = float(FLOOR_Y)
        e.on_arrive = "sleep" if reason == "quiet" else "credits"
        e.speed_max = self._u(SPEED_MIN, SPEED_MAX)
        self._ev("walk", pip=e.key, to="burrow", reason=reason)

    def _pick_wander(self, e: Entity, t: float) -> None:
        lo, hi = WANDER_X
        r = self.rng.random()
        if self.colony_rule == "huddle":
            tx = (lo + hi) / 2.0 + self._u(-20, 20)
        elif self.colony_rule == "scatter":
            tx = self._u(lo, hi)
        elif (self.colony_rule == "follow" or r < 0.3) and self.newest_speaker and self.newest_speaker != e.key \
                and self.newest_speaker in self.entities:
            s = self.entities[self.newest_speaker]
            tx = s.x + self._u(-14, 14)
        else:
            tx = e.x + self._u(-40, 40)
        e.target_x = float(min(hi, max(lo, tx)))
        e.target_y = float(FLOOR_Y)
        e.on_arrive = "idle"
        e.state = "walking"
        e.speed_max = self._u(SPEED_MIN, SPEED_MAX)
        e.speed = 0.0

    def _move(self, e: Entity, t: float, dt: float) -> None:
        if e.target_x is None:
            e.state = "awake"
            return
        dx = e.target_x - e.x
        if abs(dx) < 0.6:
            e.x = e.target_x
            e.vx = 0.0
            self._arrive(e, t)
            return
        e.facing = 1 if dx > 0 else -1
        e.speed = min(e.speed_max, e.speed + e.speed_max / EASE_FRAMES)      # ease-in over ~9 frames
        step = min(abs(dx), e.speed * dt)
        e.vx = step / max(dt, 1e-6) * e.facing
        e.x += step * e.facing

    def _arrive(self, e: Entity, t: float) -> None:
        act = e.on_arrive or "idle"
        e.on_arrive = None
        if act == "vote" and e.platform is not None:
            e.state = "voting"
            e.y = float(PLATFORM_TOP)
            self._ev("arrive", pip=e.key, at=e.platform)
        elif act in ("sleep", "credits") and e.burrow is not None:
            bx, by, bw, bh = burrow_box(e.burrow)
            e.x, e.y = bx + bw / 2.0, float(by + bh - 1)
            e.state = "asleep"
            e.sleep_t = t
            e.vx = 0.0
            e.twitch_t = t + self._u(TWITCH_MIN, TWITCH_MAX)
            if act == "credits":
                e.credits_done = True
                self._ev("credits", pip=e.key, minutes_tonight=round(e.minutes_tonight, 1))
            else:
                self._ev("sleep", pip=e.key, burrow=e.burrow, quiet_s=int(t - e.last_active_t))
        else:
            e.state = "awake"
            e.y = float(FLOOR_Y)
            e.pause_until = t + self._u(1.0, 4.0)
            if self.newest_speaker and self.newest_speaker in self.entities and self.newest_speaker != e.key:
                e.facing = 1 if self.entities[self.newest_speaker].x >= e.x else -1

    def _tick_credits(self, t: float) -> None:
        if t < self._credits_next_t:
            return
        while self._credits_queue:
            k = self._credits_queue.pop(0)
            e = self.entities.get(k)
            if e is not None and e.is_awake() and e.on_arrive != "credits":
                self._go_to_burrow(e, t, reason="credits")
                self._credits_next_t = t + CREDITS_GAP_S
                return
        if not any(e.is_awake() for e in self.entities.values()):
            self.credits_active = False
            self._ev("credits_end")
