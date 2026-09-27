"""stream/world/honesty.py - the per-frame honesty assertion (WORLD.md 1, 10, 11; docs/art-rules.md 1).

    from stream.world.honesty import HonestyMonitor
    mon = HonestyMonitor(scene)                 # one per CaveScene; keeps counters across frames
    img = scene.frame(ctx, size)
    rep = mon.check(ctx, now)                   # Report: rep.ok, rep.violations [(rule, detail)], rep.counts, rep.unverified
    mon.line()                                  # readout text: "honesty: 1200 frames · 0 violations"
    mon.summary()                               # dict for stats / the QA gate

    $PYTHON stream/world/honesty.py --self-test          # RUN_DIR under /tmp only; exit 0 only when the clean run
                                                          # has 0 violations AND every planted fake pip is caught

Every rule is a `len()` over real records, never a sample string. The rules:

  origin      every entity has origin "chat" (or "test" when stream.world.test_pips_allowed() said so for this scene)
  record      every ANIMATE entity (not a seed) maps to one row in world.json["pips"] created from a chat record;
              len(animate entities) == len(animate entities with a real record)
  chat_jsonl  every real pip key appears as a chatter in $RUN_DIR/chat.jsonl (both record shapes, de-duped on id);
              hatched_ever() == len(real pips). Re-scanned when the file grows, never more than every 2 s.
  hold        nothing about a seed carries a name (entities() gives display_name None AND key None); an entity that
              hatched in this process hatched >= hold_s after its seed dropped; a seed's name is only stored once
              the bridge cleared it (cleared == True)
  name        an entity's display_name is the pip's FILTERED display name (builder #N on a blocklist hit), never a
              raw name the filter would change
  counts      present_count / hatched_ever / platform_counts are len() over the entities they claim; asleep_count is 0
              (nobody sleeps, AGES 1.1)
  text        a bubble is the owner's own moderated text (seen in ctx.chat), one of the owner's own words, or a
              learned word carrying a real source; pips never generate text
  roster      (AGES 4.2) every settler on the land is one real person, one each: len(hatched real entities) ==
              len(hatched real pip rows), no row without a settler, no entity for a banished key, and never more rows
              than distinct real chatters ever in chat.jsonl minus banished minus quarantined. Tolerance: the hold +
              one frame (a tuft's row lands before its hatch)
  here        len(entities with is_present()) == scene.distinct_recent_chatters(ctx, now). A pip flips to here on the
              RAW record (one frame) while the reference counts the MODERATED one (hold later), so a drift is
              tolerated for max(presence_grace_s, hold_s + 1 s) and counted separately as `presence_drift`; longer =
              violation. (The 12 s walk-home grace is gone: nobody walks home.)
  agency      (AGES 4.2) an AWAY settler claims nothing a person could: no bubble spoken while away, no state
              `voting` / platform slot, no carry in (berry, gift), no hop or wave started while away, no walking.then
              outside idle | errand:* | sit | gather | credits. `enforce` clears the text / drops the vote. AND every
              record-changing EVENT this frame names a HERE actor (RECORD_EVENTS_PIP by `pip`: stack / stone / place /
              plant / sow / harvest / camp / fire / go / speak / hop / emote / pickup; RECORD_EVENTS_BY by `by`: feed /
              pet / gift / hearth; a `walk` whose then is a verb's or whose `to` is a place label), AND every stone /
              mark record that appeared on the land since the last frame names a here settler (the first frame takes
              the baseline). This is the net under rounds' expedition / bonfire / harvest cards: a round can only act
              through here settlers (AGES 9).
  idle        (AGES 1.3, what idle motion may never do) the land's errands keep their rules: never the same errand twice
              running per settler (walk events then errand:<name>; a build's haul may repeat), an AWAY body's errand never
              aims within 2 cells of the newest speaker, an away body never dwells within 2.5 cells of a waystone, the
              Moot ring holds <= 30 % of the away settlers (+1 for a here -> away flip mid-errand), <= 2 visitors per
              door, <= 4 sitting at one fire. Asserted from this frame's walk / arrive events and the entities' state.
  scene       the scene's own _honesty_check removed something (stats()["honesty_violations"] grew)
  wear        (the land, OPENWORLD.md 12 / AGES 4.2) land.take_wear_added() per frame: added == 8 x (present settlers
              that entered a new cell) + the 4-neighbour spill (<= 2 per neighbour, so <= 16 x steps), and zero wear
              while zero settlers are present (an away body moved by the land, the survey camera, the weather and
              test pips never write wear)
  marks       (the land) land.provenance_violations() every MARKS_EVERY_S: every camp / mark / stone / field owner is a
              row in world.json["pips"]

`enforce=True` (default) also REMOVES an animate entity that has no real record and clears a bubble whose text the
owner never typed, so a bug upstream cannot put a fake creature or invented words on screen. A pip RECORD with no
chat.jsonl chatter (a tampered world.json) is quarantined (WorldState.quarantine: out of `pips`, kept for audit,
never drawn, never counted) once it has been missing from the file for ORPHAN_GRACE_S; the boot path already does
this in WorldState.recompute_from_chat. Padded COUNTS are never "fixed": they stay a reported violation.
Python 3.9: from __future__ import annotations; stdlib + numpy only.
"""
from __future__ import annotations

import collections
import json
import os
import sys
from typing import Any, Deque, Dict, List, Optional, Sequence, Set, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stream.state_store import normalise_chat, run_path  # noqa: E402

RULES = ("origin", "record", "chat_jsonl", "hold", "name", "counts", "text", "roster", "here", "agency", "idle", "scene", "wear", "marks",
         "age",                                # W4 hook: `age` (AGES 4.2)
         "placed")                             # W6 hook: every standing placed row carries a validated recipe (validate_registry)
SEED_STATES = ("seed", "hatching")
# ---- W6 hook (IDLEWORLD 5.2): the gate copy of the registry allowlist and the write-time validators. honesty.py is in the
# keeper gate's DENY set, so this copy is what makes "chat is data" true: a probe-drafted parts list is checked HERE.
FN_ALLOWLIST: Dict[str, Dict[str, Tuple[int, int]]] = {           # fn -> {int arg: (lo, hi)}
    "buildings.garden": {}, "buildings.banner": {}, "buildings.lantern": {},
    "props.tree": {"age": (0, 2)}, "props.bush": {}, "props.flowers": {}, "props.stone": {}, "props.cairn": {"n": (1, 5)},
}
FN_DENIED = ("buildings.hut", "buildings.well", "buildings.fence_h", "buildings.fence_v", "props.beacon", "props.campfire", "props.waystone")
FN_DENIED_PREFIXES = ("creatures.",)               # nothing in a recipe is a figure
LIT_RULES = ("owner_here", "anyone_here", "never")
FORBIDDEN_PART_FIELDS = ("moves", "speed", "path", "frames", "rate")
PLACED_STATUSES = ("rising", "stands", "hidden")
PLACED_GAP, CAMP_GAP = 6, 12
LIFETIME_BASE, LIFETIME_PER_CAMP_TIER = 2, 1      # registry.CAPS by value (the validator never trusts the row's own numbers)


def _palette_keys() -> Set[str]:
    try:
        from stream.world.art.tiles import FLAT
        return set(FLAT.keys())
    except Exception:
        return set()


def validate_copy(text: Any) -> bool:
    """Every string a panel composes from a wish (a plate noun, a plank noun, a board title, a plaque) passes the
    compositor's banned-copy list, the day / version / clock patterns and the username blocklist. False = draw nothing."""
    s = str(text or "")
    if not s.strip():
        return False
    try:
        from stream import compositor as C
        if C.Compositor.banned_copy_hits([s]):
            return False
    except Exception:
        import re as _re
        if _re.search(r"(?<![a-z0-9_])(?:ai|keeper|keepers|build|builds|show|live|version|viewer|viewers|camera|fake|honest)(?![a-z0-9_])", s.lower()) \
                or _re.search(r"(?<![a-z0-9_])v\d+\.\d+", s.lower()) or _re.search(r"(?<![a-z0-9_])day \d+", s.lower()):
            return False
    try:
        from stream.chat_bridge import word_lists
        if word_lists().blocked(s) is not None:
            return False
    except Exception:
        pass
    return True


def validate_registry(row: Any, land=None, terrain=None, ledger_ids: Optional[Set[str]] = None, banished: Optional[Set[str]] = None,
                      placed_rows: Optional[Sequence[Dict[str, Any]]] = None, pips: Optional[Dict[str, Dict]] = None,
                      caps: Optional[Dict[str, int]] = None) -> Tuple[bool, str]:
    """(ok, reason) for one placed[] row (IDLEWORLD 5.2, 6.1): every part fn in FN_ALLOWLIST with int args in range; no
    moves / speed / path / frames / rate field on the row or a part; colour `owner` or an ART.md palette key (an RGB
    triple is refused); lit_rule closed (`always` refused); footprint >= 1x1; owner a real, unbanished pip who is an
    asker (a banished owner's row must be `hidden`); every asker a pip row or a banished record; every wish_id in the
    ledger id set (when one is given); the cell passable, dry, off the Moot green, off a trail, PLACED_GAP from other
    placed rows, CAMP_GAP from other camps; the lifetime cap (2 + camp tier) from the placed records themselves and
    the session / age caps when `caps` counts are given. Pure: no writes, no imports of the locked modules."""
    import math as _m
    if not isinstance(row, dict):
        return False, "row is not a dict"
    for k in FORBIDDEN_PART_FIELDS:
        if k in row:
            return False, "row carries %r" % k
    rid = row.get("id")
    if not isinstance(rid, str) or not rid.startswith("p-"):
        return False, "id %r is not p-NNNN" % (rid,)
    status = row.get("status")
    if status not in PLACED_STATUSES:
        return False, "status %r" % (status,)
    try:
        from stream.world import registry as R
    except Exception:
        R = None
    recipe = row.get("recipe")
    parts = row.get("parts")
    if parts is None:
        spec = ((getattr(R, "RECIPES", None) or {}).get(recipe)) if R is not None else None
        if not isinstance(spec, dict):
            return False, "unknown recipe %r" % (recipe,)
        parts = spec.get("parts") or []
        lit_rule = row.get("lit_rule", spec.get("lit_rule"))
        footprint = spec.get("footprint", (1, 1))
    else:
        lit_rule = row.get("lit_rule")
        footprint = row.get("footprint", (1, 1))
    if not isinstance(parts, (list, tuple)) or not parts:
        return False, "no parts"
    palette = None
    for part in parts:
        try:
            fn, args, dx, dy = part
        except Exception:
            return False, "malformed part %r" % (part,)
        fn = str(fn)
        if any(fn.startswith(p) for p in FN_DENIED_PREFIXES) or fn in FN_DENIED or fn not in FN_ALLOWLIST:
            return False, "part %r is not in the allowlist" % fn
        args = dict(args or {})
        for k in FORBIDDEN_PART_FIELDS:
            if k in args:
                return False, "part %s carries %r" % (fn, k)
        for k, (lo, hi) in FN_ALLOWLIST[fn].items():
            v = args.get(k)
            if isinstance(v, bool) or not isinstance(v, int) or v < lo or v > hi:
                return False, "%s.%s=%r outside %d..%d" % (fn, k, v, lo, hi)
        col = args.get("colour")
        if col is not None:
            if palette is None:
                palette = _palette_keys()
            if not isinstance(col, str) or (col != "owner" and col not in palette):
                return False, "colour %r is not `owner` or a palette key" % (col,)
        if isinstance(dx, bool) or isinstance(dy, bool) or not isinstance(dx, (int, float)) or not isinstance(dy, (int, float)):
            return False, "part %s offset %r" % (fn, (dx, dy))
    if lit_rule not in LIT_RULES:
        return False, "lit_rule %r" % (lit_rule,)
    try:
        fw, fh = footprint
        if int(fw) < 1 or int(fh) < 1:
            return False, "footprint %r" % (footprint,)
    except Exception:
        return False, "footprint %r" % (footprint,)
    owner = str(row.get("owner") or "").lower()
    ban = set(str(k).lower() for k in (banished or ()))
    askers = [str(a).lower() for a in (row.get("askers") or [])]
    if not owner:
        return False, "no owner"
    if owner in ban and status != "hidden":
        return False, "owner %r is banished: the row must be hidden" % owner
    if owner not in askers:
        return False, "owner %r is not an asker" % owner
    if pips is not None:
        p = pips.get(owner)
        if (p is None or p.get("_test")) and not (owner in ban and status == "hidden"):
            return False, "owner %r is not a real pip" % owner
        for a in askers:
            q = pips.get(a)
            if (q is None or q.get("_test")) and a not in ban:
                return False, "asker %r is not a real pip" % a
    if ledger_ids is not None:
        wids = [str(w) for w in (row.get("wish_ids") or [])]
        if not wids:
            return False, "no wish_ids"
        for w in wids:
            if w not in ledger_ids:
                return False, "wish_id %r is not in the ledger" % w
    x, y = row.get("x"), row.get("y")
    if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return False, "no cell"
    xi, yi = int(round(x)), int(round(y))
    pas = getattr(land, "passable", None) if land is not None else getattr(terrain, "passable", None)
    wat = getattr(land, "water", None) if land is not None else getattr(terrain, "water", None)
    try:
        if pas is not None and (yi < 0 or xi < 0 or not bool(pas[yi, xi])):
            return False, "cell (%d, %d) is not passable" % (xi, yi)
        if wat is not None and bool(wat[yi, xi]):
            return False, "cell (%d, %d) is water" % (xi, yi)
    except IndexError:
        return False, "cell (%d, %d) is off the map" % (xi, yi)
    if land is not None:
        try:
            if land.on_green(xi, yi):
                return False, "cell (%d, %d) is on the Moot green" % (xi, yi)
            if land.is_trail(xi, yi):
                return False, "cell (%d, %d) is on a trail" % (xi, yi)
        except Exception as ex:
            return False, "land rules unverifiable: %r" % (ex,)
        try:
            for c in land.camps():
                if c.get("key") == owner or c.get("x") is None:
                    continue
                if _m.hypot(float(c["x"]) - xi, float(c["y"]) - yi) < CAMP_GAP:
                    return False, "within CAMP_GAP of another camp"
        except Exception:
            pass
    tier = 0
    if pips is not None:
        camp = (pips.get(owner) or {}).get("camp")
        tier = int(camp.get("tier") or 0) if isinstance(camp, dict) else 0
    mine = 1
    for other in placed_rows or ():
        if not isinstance(other, dict) or other.get("id") == rid or other.get("status") == "hidden":
            continue
        try:
            if _m.hypot(float(other.get("x")) - xi, float(other.get("y")) - yi) < PLACED_GAP:
                return False, "within PLACED_GAP of %s" % other.get("id")
        except Exception:
            continue
        if str(other.get("owner") or "").lower() == owner:
            mine += 1
    if status != "hidden" and mine > LIFETIME_BASE + LIFETIME_PER_CAMP_TIER * tier:
        return False, "over the lifetime cap (%d placed, cap %d)" % (mine, LIFETIME_BASE + LIFETIME_PER_CAMP_TIER * tier)
    if caps is not None and R is not None:
        try:
            ok, why = R.cap_check(int(caps.get("person_placed", 0)), int(caps.get("person_session", 0)), int(caps.get("age_placed", 0)),
                                  int(caps.get("age", 0)), int(caps.get("camp_tier", tier)))
        except Exception as ex:
            return False, "cap check unverifiable: %r" % (ex,)
        if not ok:
            return False, "over cap: %s" % why
    return True, "ok"
HIDDEN_STATES = ("hidden", "burrowed")           # the one lying pose (mod !hide); `burrowed` is the cave's name for it
MOVING_STATES = ("walking", "hauling")           # the states the land advances (a haul is a walk with a stone)
AWAY_THEN_OK = ("idle", "sit", "gather", "credits")   # a walking.then the land may give an away body (plus errand:<name>)
IDLE_CAP_DEFAULTS = {"MOOT_AWAY_CAP": 0.30, "DOOR_VISITOR_CAP": 2, "FIRE_SIT_CAP": 4, "FIRE_SIT_CELLS": 6.0}   # AGES 1.3


def _idle_caps() -> Tuple[float, int, int, float]:
    """The idle director's caps, read from the behaviour module LOADED RIGHT NOW (never bound at import: the compositor's
    world-batch hot-reload re-executes honesty before behaviour, WORLD_ORDER, so an import-time binding would see the
    previous behaviour and a failed import would switch the rule off for the whole deploy). A behaviour without the
    names (the cave's tree) gives the spec's defaults; the rule is never skipped."""
    m = sys.modules.get("stream.world.behaviour")
    g = (lambda n: getattr(m, n, IDLE_CAP_DEFAULTS[n])) if m is not None else (lambda n: IDLE_CAP_DEFAULTS[n])
    return float(g("MOOT_AWAY_CAP")), int(g("DOOR_VISITOR_CAP")), int(g("FIRE_SIT_CAP")), float(g("FIRE_SIT_CELLS"))


STONE_STAND_CELLS = 2.5                          # an away body dwelling this close to a waystone cell "stands at a waystone"
SPEAKER_TARGET_CELLS = 2.0                       # an errand aimed this close to the newest speaker "targets the newest speaker"
LAND_THEN_PREFIXES = ("errand:", "haul:")        # W4 hook: `haul:pick` / `haul:place` are the age raising's (the land moves them, AGES 2.5)
RECORD_EVENTS_PIP = ("stack", "stone", "place", "plant", "sow", "harvest", "camp", "fire", "go", "speak", "hop", "emote", "pickup")
RECORD_EVENTS_BY = ("feed", "pet", "gift", "hearth")    # the actor is `by` (the recipient `pip` may be away, AGES 1.5)
RECORD_LISTS = (("stones", "by", "stone"), ("marks", "owner", "mark"))   # land lists diffed per frame: (attr, owner key, word)
CLAIM_SLACK_S = 1.0                              # a hop / wave / bubble that STARTED while here may outlive the window flip by this
CHAT_RESCAN_S = 2.0
TEXT_MEMORY = 20
ORPHAN_GRACE_S = 5.0          # a real pip is created from a record the listener already appended; the names scan lags <= 2 s
MARKS_EVERY_S = 5.0           # land.provenance_violations() walks every mark: every 5 s (OPENWORLD.md 12)
try:                          # the land's wear constants (absent on the cave's rollback tree: the wear rule is then skipped)
    from stream.world.land import WEAR_STEP as _WEAR_STEP, WEAR_SPILL as _WEAR_SPILL  # noqa: E402
except Exception:             # pragma: no cover
    _WEAR_STEP, _WEAR_SPILL = 8, 2


class Report(object):
    __slots__ = ("frame", "now", "violations", "counts", "unverified", "drift")

    def __init__(self, frame: int, now: float):
        self.frame = frame
        self.now = now
        self.violations: List[Tuple[str, str]] = []
        self.counts: Dict[str, int] = {}
        self.unverified: List[str] = []
        self.drift = False

    @property
    def ok(self) -> bool:
        return not self.violations

    def add(self, rule: str, detail: str) -> None:
        self.violations.append((rule, detail))

    def rules(self) -> Set[str]:
        return set(r for r, _ in self.violations)

    def __repr__(self) -> str:
        return "Report(frame=%d ok=%s violations=%r counts=%r)" % (self.frame, self.ok, self.violations, self.counts)


def chat_names(path: str) -> Optional[Set[str]]:
    """Distinct lowercase chatter names in a chat.jsonl (both shapes: username/content and user/text; de-duped on id).
    None when the file cannot be read (unverifiable, not a violation)."""
    names: Set[str] = set()
    ids: Set[str] = set()
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            m = normalise_chat(json.loads(line.decode("utf-8", "replace")))
        except Exception:
            continue
        if m is None or m["id"] in ids or not m.get("name"):
            continue
        ids.add(m["id"])
        if m.get("type") in (None, "message"):
            names.add(m["name"].lower())
    return names


class HonestyMonitor(object):
    def __init__(self, scene, name_filter=None, enforce: bool = True, presence_grace_s: float = 2.0, log=None):
        self.scene = scene
        self._filter = name_filter
        self.enforce = bool(enforce)
        self.presence_grace_s = float(presence_grace_s)
        self.log = log or (lambda m: sys.stderr.write("honesty: %s\n" % m))
        self.frames = 0
        self.failed_frames = 0
        self.violations_total = 0
        self.by_rule: Dict[str, int] = {r: 0 for r in RULES}
        self.drift_frames = 0
        self.removed = 0
        self.last: Optional[Report] = None
        self._texts: Dict[str, Deque[str]] = {}
        self._chat_seen: Set[str] = set()
        self._chat_names: Optional[Set[str]] = None
        self._chat_size = -1
        self._chat_scan_t = -1e18
        self._scene_hv = None
        self._drift_since: Optional[float] = None
        self._roster_since: Optional[float] = None
        self._logged = 0
        self._missing_since: Dict[str, float] = {}
        self._last_pick: Dict[str, Tuple[Any, Any]] = {}      # idle rule: each settler's last (errand, errand_t) pick
        self.idle_events_checked = 0
        self.quarantined = 0
        self._marks_t = -1e18
        self.wear_steps_total = 0
        self.wear_added_total = 0
        self._records_seen: Dict[str, int] = {}                # len(land.stones / marks) at the last frame (agency: new records)
        self.record_events_checked = 0
        self._placed_ok: Set[str] = set()                      # W6 hook: standing placed rows validated once per id
        self._placed_bad: Dict[str, Tuple[float, str]] = {}

    # ------------------------------------------------------------------ helpers
    def _name_filter(self):
        if self._filter is not None:
            return self._filter
        w = getattr(self.scene, "world", None)
        return getattr(w, "name_filter", None)

    def _chat_path(self) -> str:
        w = getattr(self.scene, "world", None)
        p = getattr(w, "chat_path", None)
        return p or run_path(self.scene.run_dir, "CHAT_FILE", "chat.jsonl")

    def _refresh_chat_names(self, now: float) -> None:
        path = self._chat_path()
        try:
            size = os.path.getsize(path)
        except OSError:
            size = -2
        if size == self._chat_size and self._chat_names is not None:
            return
        if now - self._chat_scan_t < CHAT_RESCAN_S and self._chat_names is not None:
            return
        self._chat_scan_t = now
        self._chat_size = size
        self._chat_names = chat_names(path) if size >= 0 else None

    def _remember_texts(self, ctx) -> None:
        for m in (getattr(ctx, "chat", None) or []):
            mid = m.get("id")
            if not mid or mid in self._chat_seen or m.get("dropped"):
                continue
            self._chat_seen.add(mid)
            key = (m.get("name") or "").lower()
            if not key:
                continue
            dq = self._texts.get(key)
            if dq is None:
                dq = self._texts[key] = collections.deque(maxlen=TEXT_MEMORY)
            for t in (m.get("text_clean"), m.get("text")):
                if t:
                    dq.append(str(t))
        if len(self._chat_seen) > 5000:
            self._chat_seen = set(list(self._chat_seen)[-2500:])

    def _text_allowed(self, key: str, text: str, pip: Optional[Dict], learned_from: Optional[str]) -> bool:
        if not text:
            return True
        cands = set(self._texts.get(key, ()))
        if text in cands or text.upper() in set(c.upper() for c in cands):
            return True
        if pip is not None:
            if text in (pip.get("words") or {}):
                return True
            if learned_from:
                for lw in (pip.get("learned") or []):
                    if lw.get("word") == text and (lw.get("from") or "").lower() == str(learned_from).lower():
                        return True
            return text.lower() in set(str(w).lower() for w in (pip.get("words") or {}))
        return False

    # ------------------------------------------------------------------ the check
    def check(self, ctx, now: Optional[float] = None) -> Report:
        scene = self.scene
        t = float(now if now is not None else (getattr(ctx, "now", None) or getattr(scene, "_last_now", None) or 0.0))
        rep = Report(self.frames, t)
        self.frames += 1
        if not getattr(scene, "booted", False) or scene.behaviour is None or scene.world is None:
            rep.counts = {"entities": 0}
            self.last = rep
            return rep
        b, w = scene.behaviour, scene.world
        self._remember_texts(ctx)
        allowed_test = int(getattr(scene, "test_pips", 0) or 0) > 0
        ents = dict(b.entities)
        hold_s = float(getattr(scene, "hold_s", 3.0))
        eps = 1.0 / 30.0 + 1e-6
        nf = self._name_filter()
        chat_display = getattr(ctx, "chat_display", None)

        # -- scene: the scene's own guard fired (it deletes entities with a foreign origin)
        hv = int(getattr(scene, "honesty_violations", 0) or 0)
        if self._scene_hv is not None and hv > self._scene_hv:
            rep.add("scene", "scene removed %d entity/ies with no real record" % (hv - self._scene_hv))
        self._scene_hv = hv

        animate = 0
        animate_real = 0
        present_real = 0
        on_land_real = 0
        hidden_real = 0
        try:
            banished = set(str(k).lower() for k in ((getattr(w, "data", None) or {}).get("banished") or {}).keys())
        except Exception:
            banished = set()
        remove: List[str] = []
        for key, e in ents.items():
            origin = getattr(e, "origin", None)
            is_test = origin == "test" and allowed_test
            # -- origin
            if origin != "chat" and not is_test:
                rep.add("origin", "%s origin=%r" % (key, origin))
                remove.append(key)
                continue
            # -- roster: a settler for a BANISHED key (whatever its record says) is never on the land
            if not is_test and key in banished:
                rep.add("roster", "%s has a settler on the land but is banished" % key)
                remove.append(key)
                continue
            p = w.pip(key)
            if e.state in SEED_STATES:
                # -- hold: a seed stores a name only once the bridge cleared it
                if e.display_name is not None and not e.cleared:
                    rep.add("hold", "seed %s carries a name before the hold cleared" % key)
                    if self.enforce:
                        e.display_name = None
                continue
            animate += 1
            # -- record
            if p is None or (is_test and not p.get("_test")) or (not is_test and p.get("_test")):
                rep.add("record", "%s (%s) has no %spip record" % (key, e.state, "" if not is_test else "test "))
                remove.append(key)
                continue
            animate_real += 1
            here = bool(e.is_present(t)) if hasattr(e, "is_present") else bool(e.is_awake())
            if not is_test:
                if e.state in HIDDEN_STATES:
                    hidden_real += 1
                elif e.is_awake():
                    on_land_real += 1              # on the land (drawn standing, moved by the land)
                if here:
                    present_real += 1              # here: the person's record is inside present_s
                # -- agency: an away body claims nothing a person could (AGES 4.2)
                if not here and e.state not in HIDDEN_STATES:
                    claims = []
                    la, ps = float(getattr(e, "last_active_t", 0.0)), float(getattr(e, "present_s", 1200.0))
                    spoke_t = getattr(e, "spoke_t", None)
                    if e.text is not None and t < e.speak_until and (spoke_t is None or spoke_t - la > ps + CLAIM_SLACK_S):
                        claims.append("bubble")
                    if e.state == "voting":
                        claims.append("state voting")
                    if getattr(e, "platform", None) is not None:
                        claims.append("platform %s" % e.platform)
                    if getattr(e, "carry", None) in ("berry", "gift"):
                        claims.append("carry %s" % e.carry)
                    if float(getattr(e, "hop_t", -1e9)) - la > ps + CLAIM_SLACK_S and t - float(getattr(e, "hop_t", -1e9)) < 1.0:
                        claims.append("hop")
                    if getattr(e, "emote", None) == "wave" and t < float(getattr(e, "emote_until", 0.0)) \
                            and float(getattr(e, "emote_until", 0.0)) - 2.0 - la > ps + CLAIM_SLACK_S:
                        claims.append("wave")
                    then = getattr(e, "then", None)
                    if e.state in MOVING_STATES and then is not None and then not in AWAY_THEN_OK and not str(then).startswith(LAND_THEN_PREFIXES):   # W4 hook
                        claims.append("walking.then=%s" % then)
                    if e.state in ("idle", "sitting"):
                        for sx, sy in (getattr(b, "waystones", None) or ()):
                            if ((e.x - sx) ** 2 + (e.y - sy) ** 2) ** 0.5 <= STONE_STAND_CELLS:
                                rep.add("idle", "away %s dwells at a waystone (%.1f, %.1f)" % (key, e.x, e.y))
                                break
                    if claims:
                        rep.add("agency", "away %s claims %s" % (key, ", ".join(claims)))
                        if self.enforce:
                            if "bubble" in claims:
                                e.text, e.speak_until = None, 0.0
                            if e.state == "voting" or getattr(e, "platform", None) is not None:
                                e.platform, e.slot = None, None
                                if e.state == "voting":
                                    e.state = "idle"
            # -- hold: hatched in this process -> hatch_t - seed_t >= hold_s; a label needs a cleared hold
            if e.hatch_t is not None and e.hatch_t - e.seed_t < hold_s - eps:
                rep.add("hold", "%s hatched %.2fs after its seed (hold %.1fs)" % (key, e.hatch_t - e.seed_t, hold_s))
            if e.display_name is not None and not e.cleared:
                rep.add("hold", "%s labelled without a cleared hold" % key)
            # -- name: the filtered name, never the raw one the filter would change
            if e.display_name is not None and not is_test:
                want = p.get("display_name")
                if want is None and nf is not None:
                    try:
                        want = nf(p.get("name") or key)
                    except Exception:
                        want = None
                shown = str(e.display_name)
                if want is not None and shown != str(want) and not shown.startswith("builder #"):
                    rep.add("name", "%s shows %r, filtered name is %r" % (key, shown, want))
                elif want is None and nf is not None and not shown.startswith("builder #"):
                    try:
                        if nf(shown) != shown:
                            rep.add("name", "%s shows a name the filter changes" % key)
                    except Exception:
                        pass
            # -- text
            if e.text is not None and t < e.speak_until and not is_test:
                if not self._text_allowed(key, str(e.text), p, e.learned_from):
                    rep.add("text", "%s speaks words the owner never typed: %r" % (key, str(e.text)[:40]))
                    if self.enforce:
                        e.text, e.speak_until = None, 0.0
        if remove and self.enforce:
            for k in remove:
                if k in b.entities:
                    del b.entities[k]
                    self.removed += 1
        # -- entities(): nothing about a seed leaves for the text layer
        try:
            for d in scene.entities(t):
                if d.get("state") in SEED_STATES and (d.get("display_name") is not None or d.get("key") is not None):
                    rep.add("hold", "entities() exposes a seed's name/key")
                    break
        except Exception as ex:
            rep.unverified.append("entities(): %r" % (ex,))
        # -- record (count form): every animate entity is backed by a record
        if animate != animate_real:
            rep.add("record", "animate entities %d != with real record %d" % (animate, animate_real))
        # -- chat_jsonl: every real pip is a chatter in chat.jsonl; hatched_ever is len()
        real_pips = [k for k, p in w.pips.items() if not p.get("_test")]
        self._refresh_chat_names(t)
        if self._chat_names is None:
            if real_pips:
                rep.unverified.append("chat.jsonl unreadable: %d pips not cross-checked" % len(real_pips))
        else:
            missing = [k for k in real_pips if k not in self._chat_names]
            if missing:
                rep.add("chat_jsonl", "%d pip(s) with no chat.jsonl record: %s" % (len(missing), ", ".join(sorted(missing)[:5])))
            for k in list(self._missing_since):
                if k not in missing:
                    self._missing_since.pop(k, None)
            for k in missing:
                since = self._missing_since.setdefault(k, t)
                if self.enforce and t - since >= ORPHAN_GRACE_S:
                    # a record with no chatter: never drawn, never counted. Entity gone, record to quarantine (audit).
                    if k in b.entities:
                        del b.entities[k]
                        self.removed += 1
                    if hasattr(w, "quarantine") and w.quarantine(k, t, "no chat.jsonl record (honesty monitor)"):
                        self.quarantined += 1
                        self.log("quarantined %s: no chat.jsonl record for %.1fs" % (k, t - since))
                    self._missing_since.pop(k, None)
            real_pips = [k for k, p in w.pips.items() if not p.get("_test")]
        try:
            he = int(scene.hatched_ever())
        except Exception:
            he = -1
        hatched_real = sum(1 for k in real_pips if (w.pips.get(k) or {}).get("state") not in SEED_STATES)
        if he != hatched_real:
            rep.add("counts", "hatched_ever() %d != len(real hatched pips) %d" % (he, hatched_real))
        live = b.entities
        # -- roster (AGES 4.2): one real person per settler, one settler per hatched row, never more rows than chatters
        rows_hatched = [k for k in real_pips if (w.pips.get(k) or {}).get("state") not in SEED_STATES]
        ents_hatched = [k for k, e in live.items() if getattr(e, "origin", None) == "chat" and e.state not in SEED_STATES]
        try:
            quarantined = set(str(k).lower() for k in ((w.data.get("quarantine") or {}).keys()))
        except Exception:
            quarantined = set()
        roster_bad: List[str] = []
        no_entity = [k for k in rows_hatched if k not in live]
        if no_entity:
            roster_bad.append("%d hatched row(s) with no settler on the land: %s" % (len(no_entity), ", ".join(sorted(no_entity)[:4])))
        if len(ents_hatched) != len(rows_hatched):
            roster_bad.append("hatched settlers %d != hatched real rows %d" % (len(ents_hatched), len(rows_hatched)))
        if self._chat_names is not None:
            chatters_ref = set(self._chat_names) - banished - quarantined
            if len(real_pips) > len(chatters_ref):
                roster_bad.append("%d rows > %d distinct chatters ever minus banished / quarantined" % (len(real_pips), len(chatters_ref)))
        if roster_bad:
            if self._roster_since is None:
                self._roster_since = t
            elif t - self._roster_since > hold_s + eps:
                rep.add("roster", "; ".join(roster_bad))
        else:
            self._roster_since = None
        # -- counts: present / platforms are len() over the entities they claim (test pips included, as drawn); asleep is 0
        n_present = sum(1 for e in live.values() if (e.is_present(t) if hasattr(e, "is_present") else e.is_awake()))
        try:
            pc_fn = getattr(scene, "present_count", None) or scene.awake_count
            if int(pc_fn()) != n_present:
                rep.add("counts", "present_count() %d != len(present entities) %d" % (pc_fn(), n_present))
            ac = getattr(scene, "asleep_count", None)
            if callable(ac) and int(ac()) != 0:
                rep.add("counts", "asleep_count() %d: nobody sleeps" % ac())
            pc = scene.platform_counts()
            for letter, keys in pc.items():
                standing = sorted(k for k, e in live.items() if e.state == "voting" and e.platform == letter)
                if sorted(keys) != standing:
                    rep.add("counts", "platform %s lists %r, standing %r" % (letter, sorted(keys), standing))
        except Exception as ex:
            rep.unverified.append("counts: %r" % (ex,))
        # -- agency (events, AGES 4.2 second clause): every record-changing event this frame names a HERE actor. The entity
        # pass above sees only what an away body holds; this one sees what was done in its name (a round card's `go`, a
        # stone stacked by rounds, a verb relayed for an away key). Test-origin actors are skipped (as drawn).
        try:
            evs = list(getattr(scene, "events", None) or [])
        except Exception:
            evs = []
        ev_bad: List[str] = []
        for ev in evs:
            if not isinstance(ev, dict):
                continue
            typ = ev.get("type")
            actor = None
            if typ in RECORD_EVENTS_BY:
                actor = ev.get("by")
            elif typ in RECORD_EVENTS_PIP:
                actor = ev.get("pip") or ev.get("key")
            elif typ == "walk":
                then = str(ev.get("then") or "idle")
                verb_walk = (then not in AWAY_THEN_OK and not then.startswith(LAND_THEN_PREFIXES)) or isinstance(ev.get("to"), str)   # W4 hook
                if verb_walk:
                    actor = ev.get("pip") or ev.get("key")
            if not actor:
                continue
            self.record_events_checked += 1
            ak = str(actor).lower()
            e = live.get(ak)
            if e is None:
                ev_bad.append("%s by %s (no settler on the land)" % (typ, ak))
            elif getattr(e, "origin", None) == "test":
                continue
            elif not (e.is_present(t) if hasattr(e, "is_present") else e.is_awake()):
                ev_bad.append("%s by away %s%s" % (typ, ak, (" then=%s to=%r" % (ev.get("then"), ev.get("to"))) if typ == "walk" else ""))
        if ev_bad:
            rep.add("agency", "record event(s) naming no here actor: " + "; ".join(ev_bad[:4]))
        # -- idle (AGES 1.3): the errand table's own rules, read off this frame's walk / arrive events (never skipped: the caps
        #    resolve against the behaviour loaded now, _idle_caps; a failure is reported, not swallowed)
        try:
            self._idle_rule(rep, evs, live, b, t)
        except Exception as ex:
            rep.unverified.append("idle: %r" % (ex,))
            self._logged += 1
            if self._logged <= 5:
                self.log("honesty idle rule skipped this frame: %r" % (ex,))
        # -- here: present real == distinct chatters in the present window of this session
        try:
            ref = int(scene.distinct_recent_chatters(ctx, t))
        except Exception as ex:
            ref = None
            rep.unverified.append("distinct_recent_chatters: %r" % (ex,))
        if ref is not None:
            if present_real != ref:
                rep.drift = True
                self.drift_frames += 1
                if self._drift_since is None:
                    self._drift_since = t
                elif t - self._drift_since > max(self.presence_grace_s, hold_s + 1.0):
                    rep.add("here", "present real %d != distinct recent chatters %d for %.1fs" % (present_real, ref, t - self._drift_since))
            else:
                self._drift_since = None
        # -- wear / marks (the land only; the cave has no Land and skips both)
        land = getattr(scene, "land", None)
        if land is not None:
            take = getattr(land, "take_wear_added", None)
            if callable(take):
                try:
                    added, steps = take()
                except Exception as ex:
                    added, steps = 0, 0
                    rep.unverified.append("take_wear_added: %r" % (ex,))
                self.wear_steps_total += int(steps)
                self.wear_added_total += int(added)
                if (added > 0) != (steps > 0):
                    rep.add("wear", "wear added %d for %d step(s)" % (added, steps))
                elif added > steps * (_WEAR_STEP + 4 * _WEAR_SPILL):
                    rep.add("wear", "wear added %d > %d x %d step(s) (8 + 4 x 2 spill)" % (added, _WEAR_STEP + 4 * _WEAR_SPILL, steps))
                if steps > 0 and present_real == 0:
                    rep.add("wear", "%d wear step(s) laid while no settler is present" % steps)
            # -- agency (records): a stone or mark that appeared since the last frame names a HERE settler (AGES 4.1 `never
            # adds a stone`, `never leaves a mark`); the first frame only takes the baseline (history is the record's)
            for attr, owner_key, what in RECORD_LISTS:
                try:
                    rows = list(getattr(land, attr, None) or [])
                except Exception:
                    rows = []
                seen = self._records_seen.get(attr)
                if seen is not None and len(rows) > seen:
                    for rec in rows[seen:]:
                        who = str((rec or {}).get(owner_key) or "").lower()
                        e = live.get(who)
                        here_ = e is not None and (e.is_present(t) if hasattr(e, "is_present") else e.is_awake())
                        if e is None or (getattr(e, "origin", None) != "test" and not here_):
                            rep.add("agency", "%s recorded for %s who is %s" % (what, who or "?", "away" if e is not None else "not on the land"))
                self._records_seen[attr] = len(rows)
            if t - self._marks_t >= MARKS_EVERY_S:
                self._marks_t = t
                try:
                    bad = list(land.provenance_violations() or [])
                except Exception as ex:
                    bad = []
                    rep.unverified.append("provenance_violations: %r" % (ex,))
                if bad:
                    rep.add("marks", "%d mark(s) whose owner is not a pip row: %s" % (len(bad), "; ".join(str(b) for b in bad[:3])))
            try:                                              # W6 hook: no `stands` row without a validated recipe (cached per id)
                self._check_placed(scene, rep, t)
            except Exception as ex:
                rep.unverified.append("placed: %r" % (ex,))
        # -- age (AGES 4.2; W4 hook): age <= age_gate(people, stones, days), monotonic across frames, age_built <= age,
        #    stones_placed <= len(stones); the assertions live in ages.age_violations (schema 2 with no director: nothing)
        try:
            from stream.world import ages as _AG
            for s_ in _AG.age_violations(scene, self):
                rep.add("age", s_)
        except Exception as ex:
            rep.unverified.append("age: %r" % (ex,))
        rep.counts = {"entities": len(live), "animate": animate, "animate_real": animate_real, "present": n_present,
                      "present_real": present_real, "on_land_real": on_land_real, "hidden_real": hidden_real,
                      "seeds": sum(1 for e in live.values() if e.state in SEED_STATES),
                      "real_pips": len(real_pips), "hatched_ever": he, "recent_chatters": ref if ref is not None else -1,
                      "test_pips": int(getattr(scene, "test_pips", 0) or 0), "removed_total": self.removed}
        if chat_display is False:
            rep.counts["names_hidden"] = 1
        if rep.violations:
            self.failed_frames += 1
            self.violations_total += len(rep.violations)
            for r in rep.rules():
                self.by_rule[r] = self.by_rule.get(r, 0) + 1
            self._logged += 1
            if self._logged <= 5 or self._logged % 300 == 0:
                self.log("frame %d: %s" % (rep.frame, "; ".join("%s: %s" % v for v in rep.violations[:4])))
        self.last = rep
        return rep

    def _idle_rule(self, rep: Report, evs: List[Dict[str, Any]], live: Dict[str, Any], b, t: float) -> None:
        """The idle director's rules (AGES 1.3) checked at the events that could break them: a `walk` with then errand:<name>
        (never the same twice running; an away body's target never the newest speaker; the Moot cap; the door cap) and an
        `arrive` at a sit (the fire cap)."""
        _MOOT_CAP, _DOOR_CAP, _FIRE_CAP, _FIRE_CELLS = _idle_caps()
        away_n = None
        speaker = None
        sk = getattr(b, "newest_speaker", None)
        # the newest speaker counts while its word is inside the here window (present_s): a person who spoke hours ago and is
        # parked somewhere is not "the newest speaker" the errands must avoid (AGES 1.3 is about the person talking now)
        if sk and t - float(getattr(b, "newest_speaker_t", -1e9)) <= float(getattr(b, "present_s", 1200.0)):
            speaker = live.get(str(sk).lower())
        # never the same errand twice running: read off the director's own pick memory (errand, errand_t): a new pick time
        # with the same name is a repeat (a walk event alone would miss picks that ended where the settler stood)
        for key, e in live.items():
            if getattr(e, "origin", None) == "test" or not e.is_awake():
                continue
            cur = (getattr(e, "errand", None), getattr(e, "errand_t", None))
            prev = self._last_pick.get(key)
            if prev is not None and cur[0] is not None and cur[1] != prev[1] and cur[0] == prev[0] and cur[0] != "haul":
                rep.add("idle", "%s picked errand %s twice running" % (key, cur[0]))
            self._last_pick[key] = cur
        for ev in evs:
            if not isinstance(ev, dict):
                continue
            typ = ev.get("type")
            key = str(ev.get("pip") or ev.get("key") or "").lower()
            e = live.get(key)
            if e is None or getattr(e, "origin", None) == "test":
                continue
            here = e.is_present(t) if hasattr(e, "is_present") else e.is_awake()
            if typ == "walk":
                then = str(ev.get("then") or "")
                if not then.startswith("errand:"):
                    continue
                name = then.split(":", 1)[1]
                if name in ("haul_drop",):
                    continue
                self.idle_events_checked += 1
                to = ev.get("to")
                if not here and speaker is not None and speaker is not e and isinstance(to, (list, tuple)) and len(to) >= 2:
                    if ((float(to[0]) - speaker.x) ** 2 + (float(to[1]) - speaker.y) ** 2) ** 0.5 <= SPEAKER_TARGET_CELLS:
                        rep.add("idle", "away %s's errand %s targets the newest speaker %s" % (key, name, speaker.key))
                if name == "moot" and not here:
                    if away_n is None:
                        away_n = sum(1 for o in live.values() if o.is_awake() and not (o.is_present(t) if hasattr(o, "is_present") else True))
                    on_moot = sum(1 for o in live.values() if o.is_awake() and getattr(o, "errand", None) == "moot"
                                  and not (o.is_present(t) if hasattr(o, "is_present") else True))
                    import math as _m
                    if on_moot > _m.ceil(_MOOT_CAP * away_n) + 1:
                        rep.add("idle", "Moot ring holds %d of %d away settlers (cap %.0f %%)" % (on_moot, away_n, _MOOT_CAP * 100))
                if name == "visit":
                    vk = getattr(e, "visit_key", None)
                    if vk:
                        n_v = sum(1 for o in live.values() if o.is_awake() and getattr(o, "errand", None) == "visit" and getattr(o, "visit_key", None) == vk)
                        if n_v > _DOOR_CAP:
                            rep.add("idle", "%d visitors at %s's door (cap %d)" % (n_v, vk, _DOOR_CAP))
            elif typ == "arrive" and ev.get("at") == "sit":
                fire = getattr(e, "sit_at", None)
                if fire is not None:
                    n_s = sum(1 for o in live.values() if o.state == "sitting" and getattr(o, "sit_at", None) is not None
                              and ((o.sit_at[0] - fire[0]) ** 2 + (o.sit_at[1] - fire[1]) ** 2) ** 0.5 <= _FIRE_CELLS)
                    if n_s > _FIRE_CAP:
                        rep.add("idle", "%d sitting at the fire (%.0f, %.0f) (cap %d)" % (n_s, fire[0], fire[1], _FIRE_CAP))

    def _check_placed(self, scene, rep: Report, t: float) -> None:
        """W6 hook (IDLEWORLD 5.2): every `stands` placed row passes validate_registry against the land, the pips, the
        banished set and the ledger id set the scene's wish post holds (skipped when no post is attached); a row that
        fails is reported every frame and re-validated every MARKS_EVERY_S."""
        w = scene.world.data.get("world") or {}
        rows = w.get("placed") or []
        if not rows:
            return
        post = getattr(scene, "wishes", None)
        fn = getattr(post, "ledger_ids", None)
        ledger = set(fn()) if callable(fn) else None
        pips = scene.world.data.get("pips") or {}
        banished = set(str(k).lower() for k in (scene.world.data.get("banished") or {}))
        for row in rows:
            if not isinstance(row, dict) or row.get("status") != "stands":
                continue
            rid = str(row.get("id"))
            if rid in self._placed_ok:
                continue
            last = self._placed_bad.get(rid)
            if last is not None and t - last[0] < MARKS_EVERY_S:
                rep.add("placed", "%s: %s" % (rid, last[1]))
                continue
            ok, why = validate_registry(row, land=getattr(scene, "land", None), terrain=getattr(scene, "terrain", None), ledger_ids=ledger,
                                        banished=banished, placed_rows=[r for r in rows if r is not row], pips=pips)
            if ok:
                self._placed_ok.add(rid)
                self._placed_bad.pop(rid, None)
            else:
                self._placed_bad[rid] = (t, why)
                rep.add("placed", "%s: %s" % (rid, why))

    # ------------------------------------------------------------------ readouts
    def summary(self) -> Dict[str, Any]:
        return {"frames": self.frames, "failed_frames": self.failed_frames, "violations": self.violations_total,
                "by_rule": {k: v for k, v in self.by_rule.items() if v}, "presence_drift_frames": self.drift_frames,
                "removed": self.removed, "quarantined": self.quarantined, "last": None if self.last is None else
                {"ok": self.last.ok, "violations": list(self.last.violations), "counts": dict(self.last.counts),
                 "unverified": list(self.last.unverified)}}

    def line(self) -> str:
        """One readout line (Menlo 20 in 240 px fits ~19 chars): the NUMBER must survive, so `honesty: 199 bad`."""
        if self.violations_total:
            return "honesty: %d bad" % self.violations_total
        return "honesty: %d frames ok" % self.frames


def check_frame(scene, ctx, now: Optional[float] = None, enforce: bool = False) -> Report:
    """One-off check without keeping counters (the QA gate); `enforce` defaults off here."""
    return HonestyMonitor(scene, enforce=enforce, log=lambda m: None).check(ctx, now)


# ---------------------------------------------------------------------------- self-test
def _selftest(run_dir: str) -> int:
    """Clean run must be violation-free; every planted fake must be caught. Prints evidence; returns the exit code."""
    import shutil
    import time as _time
    from PIL import Image
    from stream.state_store import epoch_to_iso
    from stream.world.behaviour import Entity
    from stream.world.state import _default_pip
    from stream.world import pips as P
    from stream.world import behaviour as _BH
    # The scene the world panel would pick (stream/panels/world.py): the land when stream/scenes/steading.py imports and
    # the 2-D behaviour is on disk, else the cave (the rollback week). The monitor's rules are the same on both.
    SceneCls = None
    _Ctx = None
    try:
        from stream.scenes import steading as _ST
        if hasattr(_BH, "MAP_W") and hasattr(_BH.Behaviour, "camera_inputs"):
            SceneCls, _Ctx = _ST.SteadingScene, _ST._Ctx
    except Exception as e:
        print("[setup] steading scene not importable (%r): the cave is the scene" % (e,))
    if SceneCls is None:
        from stream.scenes.hollow import CaveScene as SceneCls, _Ctx  # noqa: N813
    land_scene = SceneCls.__name__ == "SteadingScene"
    os.environ.setdefault("MODE", "test")

    rp = os.path.realpath(run_dir)
    if not (rp.startswith("/tmp/") or rp.startswith("/private/tmp/")):
        print("refused: RUN_DIR must be under /tmp (got %s)" % run_dir)
        return 2
    os.environ.pop("KL_TEST_PIPS", None)
    if os.path.isdir(run_dir):
        shutil.rmtree(run_dir)
    os.makedirs(run_dir)
    fps = 30.0
    t0 = _time.time()
    session = {"id": "honesty-" + epoch_to_iso(t0, ms=False), "started_ts": epoch_to_iso(t0 - 30, ms=False), "ending": False}
    # the "real" records: both chat.jsonl shapes, written to $RUN_DIR/chat.jsonl exactly as the listener / receiver do
    names = ["honesty-chatter-a", "honesty-chatter-b", "honesty-chatter-c"]
    # a and b chatted an hour ago (placed standing at boot, away: real last_seen); c has never chatted and appears live below
    recs_file = [
        {"id": "h-0001", "ts": epoch_to_iso(t0 - 3600.0), "username": names[0], "content": "hello cave", "type": "message"},
        {"id": "h-0002", "ts": epoch_to_iso(t0 - 3500.0), "user": names[1], "text": "hi there", "user_id": 42},
    ]
    chat_path = os.path.join(run_dir, "chat.jsonl")
    with open(chat_path, "w") as fh:
        for r in recs_file:
            fh.write(json.dumps(r) + "\n")
    print("[setup] %s: %d history records (pusher + webhook shapes), names %r; %r chats live" % (
        chat_path, len(recs_file), names[:2], names[2]))

    def append_chat(rec):                                     # what the listener does the moment a message lands
        with open(chat_path, "a") as fh:
            fh.write(json.dumps(rec) + "\n")

    def bridge_rec(i, name, text, t, kind="plain", letter=None):
        return {"id": "h-%04d" % i, "ts": epoch_to_iso(t), "t": t, "name": name, "text": text, "text_clean": text,
                "kind": kind, "letter": letter, "display_name": name, "builder_n": None, "first_ever": True,
                "dropped": False, "show_t": t + 3.0, "accepted": True}

    def mkctx(now, frame, chat_raw, chat, votes=(), hb=None):
        return _Ctx(now=now, frame=frame, fps=fps, session=session, micro={"canvas_seed": 41370704}, preset="kick",
                    chat_raw=list(chat_raw), chat=list(chat), recent_votes=list(votes), round={"number": 1},
                    mod={"hidden_users": []}, agent={"heartbeat_ts": hb}, macro={"active": False},
                    compositor_live={"selftest": True}, mod_paused=False, chat_display=True)

    size = (1280, 440)
    scene = SceneCls(run_dir=run_dir, seed=11, sleep_after_s=60.0)
    if land_scene:                                            # the land boots on its first frames (terrain in a thread)
        tb = _time.perf_counter()
        while not (scene.booted or scene.refused) and _time.perf_counter() - tb < 30.0:
            scene.frame(mkctx(t0 - 1.0, 0, [], []), size)
            _time.sleep(0.01)
        print("[setup] %s booted=%s refused=%r in %.0f ms (%d entities, %d camps)" % (
            SceneCls.__name__, scene.booted, scene.refused, (_time.perf_counter() - tb) * 1000,
            len(scene.behaviour.entities) if scene.booted else 0, len(scene.land.camps()) if scene.booted else 0))
    else:
        print("[setup] %s (the cave)" % SceneCls.__name__)
    mon = HonestyMonitor(scene, enforce=False)
    raw: List[Dict] = []
    clear: List[Dict] = []
    seed_frames_nameless = 0
    seed_frames = 0
    frames_dir = os.path.join(run_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    n_clean = 300                                             # the land's hatch waits for the settler's sheet (<= 4 s more)
    ev_types: Dict[str, int] = {}
    hatch_frame = seed_frame = None
    for i in range(n_clean):
        now = t0 + i / fps
        votes = []
        if i == 30:                                           # a stranger: seed drops THIS frame, nameless for 3 s
            append_chat({"id": "h-0003", "ts": epoch_to_iso(now), "username": names[2], "content": "first time here", "type": "message"})
            raw.append(bridge_rec(3, names[2], "first time here", now))
        if i == 45:                                           # a returning chatter: `return` on the raw record
            append_chat({"id": "h-0004", "ts": epoch_to_iso(now), "user": names[0], "text": "back again", "user_id": 7})
            raw.append(bridge_rec(4, names[0], "back again", now))
        if i == 120:
            clear.append(bridge_rec(3, names[2], "first time here", now - 3.0))
        if i == 135:
            clear.append(bridge_rec(4, names[0], "back again", now - 3.0))
        if i == 180:
            append_chat({"id": "h-0005", "ts": epoch_to_iso(now), "username": names[0], "content": "B", "type": "message"})
            raw.append(bridge_rec(5, names[0], "B", now, "vote", "B"))
        if i >= 180:
            votes = [(names[0], "B", t0 + 180 / fps)]
        if i == 210:
            clear.append(bridge_rec(5, names[0], "B", now - 3.0, "vote", "B"))
        ctx = mkctx(now, i, raw[-20:], clear[-10:], votes)
        img = scene.frame(ctx, size)
        rep = mon.check(ctx, now)
        for ev in scene.events:
            ev_types[ev["type"]] = ev_types.get(ev["type"], 0) + 1
            if ev["type"] == "seed" and seed_frame is None:
                seed_frame = i
            if ev["type"] == "hatch" and ev.get("pip") == names[2]:
                hatch_frame = i
        for d in scene.entities(now):
            if d["state"] in SEED_STATES:
                seed_frames += 1
                if d["display_name"] is None and d["key"] is None:
                    seed_frames_nameless += 1
        if i in (60, 150, 239):
            img.save(os.path.join(frames_dir, "clean_%04d.png" % i))
    s = mon.summary()
    print("[clean] %d frames: failed_frames=%d violations=%d by_rule=%r drift_frames=%d unverified=%r" % (
        n_clean, s["failed_frames"], s["violations"], s["by_rule"], s["presence_drift_frames"], s["last"]["unverified"]))
    print("[clean] last counts: %r" % (s["last"]["counts"],))
    print("[clean] seed frames seen=%d, nameless (display_name None and key None)=%d; seed at frame %s, hatch at frame %s (hold 3 s = 90 frames); events %r" % (
        seed_frames, seed_frames_nameless, seed_frame, hatch_frame, dict(sorted(ev_types.items()))))
    print("[clean] hatched_ever=%d present=%d on_land=%d platform_counts=%r stats=%r" % (
        scene.hatched_ever(), scene.present_count(), len(scene.behaviour.on_land()), scene.platform_counts(),
        {k: scene.stats()[k] for k in ("frames", "errors", "honesty_violations", "test_pips", "entities")}))
    ok = True
    if s["violations"] != 0:
        print("FAIL: clean run produced violations")
        ok = False
    if seed_frames == 0 or seed_frames != seed_frames_nameless:
        print("FAIL: a seed carried a name (%d/%d)" % (seed_frames_nameless, seed_frames))
        ok = False
    if scene.hatched_ever() != 3 or s["last"]["counts"]["present_real"] != 2 or s["last"]["counts"]["on_land_real"] != 3 or s["last"]["counts"]["hidden_real"] != 0:
        print("FAIL: expected 3 real hatched, 2 present (a returned, c hatched), 3 on the land, 0 hidden (b stands, away)")
        ok = False
    b_ent = scene.behaviour.get(names[1])
    if b_ent is None or not b_ent.is_on_land() or b_ent.is_present() or b_ent.frame_name(t0 + n_clean / fps) == "sleep":
        print("FAIL: b (away) should stand on the land, never the lying pose: %r" % (b_ent.to_dict(t0 + n_clean / fps) if b_ent else None,))
        ok = False
    if any(ev in ev_types for ev in ("sleep", "wake", "curl", "uncurl")):
        print("FAIL: a sleep / wake / curl event fired: %r" % (ev_types,))
        ok = False
    if land_scene:
        print("[clean] land: wear steps %d added %d (rule wear: 8 x steps + spill), camps %d, marks %d, camera cuts %d, record events checked %d" % (
            mon.wear_steps_total, mon.wear_added_total, len(scene.land.camps()), len(scene.land.marks), scene.camera.cuts, mon.record_events_checked))
        if scene.camera.cuts != 0:
            print("FAIL: the camera cut")
            ok = False
    if "hatch" not in ev_types or ev_types.get("seed", 0) < 1:
        print("FAIL: no seed/hatch events on the live path: %r" % (ev_types,))
        ok = False

    # ---- planted fakes: each must be caught by the named rule
    now = t0 + n_clean / fps
    caught: Dict[str, bool] = {}

    def run_frames(n, extra_check=None):
        nonlocal now
        last = None
        for _ in range(n):
            now += 1.0 / fps
            ctx = mkctx(now, 0, raw[-20:], clear[-10:], [(names[0], "B", t0 + 180 / fps)])
            scene.frame(ctx, size)
            last = mon.check(ctx, now)
            if extra_check is not None:
                extra_check(ctx)
        return last

    # 1. a creature with a plausible origin but no record anywhere (a forged entity)
    ghost = Entity("ghost-nobody", "chat", now)
    ghost.state, ghost.display_name, ghost.cleared = "idle", "ghost", True
    if land_scene:
        ghost.x, ghost.y = float(scene.terrain.site[0]) + 4.0, float(scene.terrain.site[1]) + 4.0      # on the Moot green
    else:
        from stream.world.state import FLOOR_ROWS
        ghost.y = float(FLOOR_ROWS[0])
    scene.behaviour.entities["ghost-nobody"] = ghost
    rep = run_frames(2)
    caught["record (forged entity, no pip record)"] = "record" in rep.rules()
    print("[fake 1] forged entity origin=chat, no record -> %r" % (rep.violations,))
    scene.behaviour.entities.pop("ghost-nobody", None)
    run_frames(1)

    # 2. a pip record for someone who never chatted (planted in world.json), with an entity to match
    key = "never-chatted-x"
    scene.world.data["pips"][key] = _default_pip(key, "Never", "Never", None, now, P.genome(key, 0))
    scene.world.data["pips"][key]["state"] = "idle"
    scene.behaviour.place_settler(key, 0, 0.6, 0, None, "Never", t=now)
    rep = run_frames(2)
    caught["chat_jsonl (pip with no chat.jsonl record)"] = "chat_jsonl" in rep.rules()
    print("[fake 2] planted pip record with no chat.jsonl record -> %r" % (rep.violations,))
    scene.behaviour.entities.pop(key, None)
    scene.world.data["pips"].pop(key, None)
    scene.world.data["world"]["hatched_ever"] = scene.world.hatched_ever
    run_frames(1)

    # 2b. the same tamper under enforce=True: after ORPHAN_GRACE_S the entity is gone and the record is in quarantine
    key = "never-chatted-y"
    scene.world.data["pips"][key] = _default_pip(key, "Never", "Never", None, now, P.genome(key, 0))
    scene.world.data["pips"][key]["state"] = "idle"
    scene.behaviour.place_settler(key, 0, 0.6, 0, None, "Never", t=now)
    mon_e = HonestyMonitor(scene, enforce=True, log=lambda m: None)
    padded = scene.hatched_ever()
    for _ in range(int((ORPHAN_GRACE_S + 1.0) * fps)):
        now += 1.0 / fps
        ctx = mkctx(now, 0, raw[-20:], clear[-10:], [(names[0], "B", t0 + 180 / fps)])
        scene.frame(ctx, size)
        mon_e.check(ctx, now)
    gone = key not in scene.behaviour.entities and key not in scene.world.pips
    quarantined = key in (scene.world.data.get("quarantine") or {})
    caught["enforce (orphan record quarantined, entity removed)"] = gone and quarantined and scene.hatched_ever() == padded - 1
    print("[fake 2b] enforce=True orphan: entity gone=%s quarantined=%s hatched_ever %d -> %d monitor=%r" % (
        gone, quarantined, padded, scene.hatched_ever(), {k: mon_e.summary()[k] for k in ("removed", "quarantined", "by_rule")}))
    run_frames(1)

    # 2c. a world.json tampered on disk (a pip row for someone who never chatted) is quarantined AT BOOT, never placed
    from stream.world.state import WorldState
    scene.world.save(now, force=True)
    with open(scene.world.path) as fh:
        doc = json.load(fh)
    doc["pips"]["phantom-nobody"] = _default_pip("phantom-nobody", "Phantom", "Phantom", 99, now, P.genome("phantom-nobody", 0))
    doc["pips"]["phantom-nobody"]["state"] = "idle"
    doc["world"]["hatched_ever"] = len(doc["pips"])
    with open(scene.world.path, "w") as fh:
        json.dump(doc, fh)
    ws2 = WorldState(run_dir, log=lambda m: None)
    before = "phantom-nobody" in ws2.pips
    rec = ws2.recompute_from_chat(now, session["id"])
    q2 = ws2.data.get("quarantine") or {}
    caught["boot (world.json orphan quarantined by recompute_from_chat)"] = before and "phantom-nobody" not in ws2.pips and "phantom-nobody" in q2 and ws2.hatched_ever == len(ws2.pips)
    print("[fake 2c] tampered world.json at boot: loaded=%s after recompute in pips=%s in quarantine=%s hatched_ever=%d recompute=%r" % (
        before, "phantom-nobody" in ws2.pips, "phantom-nobody" in q2, ws2.hatched_ever, rec))
    scene.world.save(now, force=True)                        # put the live scene's (clean) document back on disk

    # 3. a name on a seed before the hold cleared
    early = scene.behaviour.seed_drop("early-name", now)
    early.display_name = "early"
    rep = run_frames(1)
    caught["hold (name stored on an uncleared seed)"] = "hold" in rep.rules()
    print("[fake 3] seed with a name before the hold -> %r" % (rep.violations,))
    scene.behaviour.sink("early-name", now)
    run_frames(1)

    # 4. a hatch that skipped the hold
    fast = scene.behaviour.seed_drop("fast-hatch", now)
    scene.behaviour.hold_cleared("fast-hatch", now, "fast", 0, 0.6, 0, True)
    fast.seed_t = now - 0.5
    scene.world.data["pips"]["fast-hatch"] = _default_pip("fast-hatch", "fast", "fast", None, now, P.genome("fast-hatch", 0))
    with open(chat_path, "a") as fh:                         # give it a real record so ONLY the hold rule fires
        fh.write(json.dumps({"id": "h-0009", "ts": epoch_to_iso(now), "username": "fast-hatch", "content": "x"}) + "\n")
    scene.behaviour._hatch(fast, now)                        # forced early hatch: hatch_t - seed_t = 0.5 s
    rep = run_frames(1)
    caught["hold (hatched before hold_s)"] = "hold" in rep.rules()
    print("[fake 4] hatch 0.5 s after the seed -> %r" % (rep.violations,))
    scene.behaviour.entities.pop("fast-hatch", None)
    scene.world.data["pips"].pop("fast-hatch", None)
    scene.world.data["world"]["hatched_ever"] = scene.world.hatched_ever
    run_frames(1)

    # 5. a padded count
    real_present = scene.present_count
    scene.present_count = lambda: real_present() + 1
    rep = run_frames(1)
    caught["counts (present_count padded by 1)"] = "counts" in rep.rules()
    print("[fake 5] present_count() + 1 -> %r" % (rep.violations,))
    scene.present_count = real_present
    run_frames(1)

    # 6. words the owner never typed
    e = scene.behaviour.get(names[0])
    e.text, e.speak_until = "words nobody typed here", now + 6.0
    rep = run_frames(1)
    caught["text (generated bubble)"] = "text" in rep.rules()
    print("[fake 6] bubble text the owner never typed -> %r" % (rep.violations,))
    e.text, e.speak_until = None, 0.0

    # 7. a foreign origin (the scene's own guard should also fire)
    alien = Entity("alien-origin", "mascot", now)
    alien.state, alien.display_name, alien.cleared = "idle", "mascot", True
    scene.behaviour.entities["alien-origin"] = alien
    rep = run_frames(1)
    caught["origin/scene (origin=mascot)"] = bool({"origin", "scene"} & rep.rules())
    print("[fake 7] entity origin=mascot -> %r (scene honesty_violations=%d)" % (rep.violations, scene.honesty_violations))

    # 10. an AWAY settler given a bubble (b never chatted this session): agency, cleared under enforce
    bb = scene.behaviour.get(names[1])
    assert bb is not None and not bb.is_present(now), "b should be away"
    bb.text, bb.speak_until, bb.spoke_t = "hi there", now + 6.0, now
    rep = mon.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
    caught["agency (away settler with a bubble)"] = "agency" in rep.rules()
    print("[fake 10] away settler with a bubble -> %r" % (rep.violations,))
    mon_a = HonestyMonitor(scene, enforce=True, log=lambda m: None)
    mon_a.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
    caught["enforce (away bubble cleared)"] = bb.text is None
    bb.text, bb.speak_until, bb.spoke_t = None, 0.0, None
    run_frames(1)

    # 11. an AWAY settler standing at waystone B: agency (state voting) + counts (the embodied tally counts here voters only)
    bb.state, bb.platform, bb.slot = "voting", "B", 5
    rep = mon.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
    caught["agency + counts (away settler at waystone B)"] = {"agency", "counts"} <= rep.rules()
    print("[fake 11] away settler at waystone B -> %r" % (rep.violations,))
    mon_a.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
    caught["enforce (away vote dropped)"] = bb.state == "idle" and bb.platform is None
    bb.state, bb.platform, bb.slot = "idle", None, None
    run_frames(1)

    # 12. roster: a hatched pip row with no settler on the land (planted in world.json, with a chat record so ONLY roster fires)
    key = "row-no-settler"
    with open(chat_path, "a") as fh:
        fh.write(json.dumps({"id": "h-0012", "ts": epoch_to_iso(now - 900), "username": key, "content": "long ago"}) + "\n")
    scene.world.data["pips"][key] = _default_pip(key, "Row", "Row", None, now - 900, P.genome(key, 0))
    scene.world.data["pips"][key]["state"] = "idle"
    rep = run_frames(int((ORPHAN_GRACE_S + 1.0) * fps))
    caught["roster (hatched row with no settler)"] = "roster" in rep.rules()
    print("[fake 12] pip row with no entity -> %r" % (rep.violations,))
    scene.world.data["pips"].pop(key, None)
    scene.world.data["world"]["hatched_ever"] = scene.world.hatched_ever
    run_frames(int((ORPHAN_GRACE_S + 1.0) * fps))

    # 13. roster: a settler on the land for a BANISHED key
    key = "banished-nobody"
    scene.world.data["banished"][key] = {"ts": epoch_to_iso(now), "by": "selftest"}
    scene.behaviour.place_settler(key, 0, 0.6, 0, None, "Ban", t=now)
    rep = mon.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
    caught["roster (entity for a banished key)"] = "roster" in rep.rules()
    print("[fake 13] entity for a banished key -> %r" % (rep.violations,))
    scene.behaviour.entities.pop(key, None)
    scene.world.data["banished"].pop(key, None)
    run_frames(1)

    # 14. wear laid while ZERO settlers are present (every person's window pushed shut, then one real step through land.step)
    saved_active = {k: e.last_active_t for k, e in scene.behaviour.entities.items()}
    ps_ = scene.behaviour.present_s
    for e in scene.behaviour.entities.values():
        e.last_active_t = now - ps_ - 5.0
    run_frames(1)                                            # the tick refreshes the flags: present 0, everyone still on the land
    assert scene.present_count() == 0 and all(e.is_on_land() for e in scene.behaviour.entities.values() if e.state not in SEED_STATES)
    ea = scene.behaviour.get(names[0])
    scene.land.step(names[0], int(ea.x) + 1, int(ea.y) + 1)
    rep = mon.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
    caught["wear (a step laid while zero settlers are present)"] = "wear" in rep.rules()
    print("[fake 14] wear step with 0 present -> %r" % (rep.violations,))
    for k, e in scene.behaviour.entities.items():
        if k in saved_active:
            e.last_active_t = saved_active[k]
    run_frames(2)

    # 15. a stone RECORD laid for an away settler (what rounds._expedition_watch did before the fix): agency, by the land diff
    bb = scene.behaviour.get(names[1])
    assert bb is not None and not bb.is_present(now), "b should be away"
    stock_before = scene.land.stock
    rec15, why15 = scene.land.stack(names[1], now)
    rep = mon.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
    caught["agency (stone recorded for an away settler)"] = "agency" in rep.rules() and rec15 is not None and "stone recorded for %s who is away" % names[1] in str(rep.violations)
    print("[fake 15] land.stack(away b) -> rec=%r why=%r stock %d->%d -> %r" % (rec15, why15, stock_before, scene.land.stock, rep.violations))
    run_frames(1)
    # 15b. the same stone for a HERE settler is no violation (a's record is inside present_s)
    aa = scene.behaviour.get(names[0])
    assert aa is not None and aa.is_present(now), "a should be here (gap %.1f s, present_s %.0f)" % (now - aa.last_active_t, scene.behaviour.present_s)
    scene.land.stack(names[0], now)
    rep = mon.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
    caught["agency (a here settler's stone passes)"] = "agency" not in rep.rules()
    print("[fake 15b] land.stack(here a) -> %r" % (rep.violations,))
    run_frames(1)
    # 16. record-changing EVENTS naming an away actor: an expedition `go` + `stack`, and a verb-labelled walk
    scene.events = list(scene.events) + [{"type": "go", "pip": names[1], "place": "ford"},
                                         {"type": "stack", "pip": names[1], "expedition": True, "stock": scene.land.stock},
                                         {"type": "walk", "pip": names[1], "to": "ford", "then": "idle"}]
    rep = mon.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
    vs = str(rep.violations)
    caught["agency (go / stack / verb-walk events naming an away actor)"] = "agency" in rep.rules() and "go by away" in vs and "stack by away" in vs and "walk by away" in vs
    print("[fake 16] events go / stack / walk(to='ford') for away b -> %r" % (rep.violations,))
    scene.events = [ev for ev in scene.events if ev.get("pip") != names[1]]
    run_frames(1)
    # 16b. the same three events for the HERE settler a pass
    scene.events = list(scene.events) + [{"type": "go", "pip": names[0], "place": "ford"},
                                         {"type": "walk", "pip": names[0], "to": "ford", "then": "idle"}]
    rep = mon.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
    caught["agency (a here settler's go / walk events pass)"] = "agency" not in rep.rules()
    print("[fake 16b] events go / walk for here a -> %r" % (rep.violations,))
    run_frames(1)
    # 16c. the scene API itself refuses the away verb (defence in depth, steading.command) and the frame after is clean
    if land_scene:
        stock_c = scene.land.stock
        ok16, why16 = scene.command("go", names[1], arg="ford", now=now)
        okS, whyS = scene.command("stack", names[1], now=now)
        rep = run_frames(1)
        caught["scene (away go / stack refused by scene.command, no record)"] = (not ok16) and (not okS) and "away" in why16 and scene.land.stock == stock_c and rep.ok
        print("[fake 16c] scene.command('go' / 'stack', away b) -> %r / %r; stock %d; next frame %r" % ((ok16, why16), (okS, whyS), scene.land.stock, rep.violations))

    # 17. idle (AGES 1.3): the errand table's own rules. 17a the same errand twice running (two walk events then errand:moot for
    #     away b); 17b an away body dwelling at a waystone; 17c an away body's errand aimed at the newest speaker; 17d a clean
    #     errand walk (then errand:stroll, a cell pair away from everyone) passes
    bb = scene.behaviour.get(names[1])
    assert bb is not None and not bb.is_present(now), "b should be away"
    err0, errt0 = bb.errand, bb.errand_t
    bb.errand, bb.errand_t = "moot", now
    rep_a1 = mon.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
    bb.errand, bb.errand_t = "moot", now + 1.0                    # a NEW pick (errand_t moved) of the SAME errand
    rep = mon.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
    caught["idle (the same errand twice running)"] = "idle" not in rep_a1.rules() and "idle" in rep.rules() and "twice running" in str(rep.violations)
    print("[fake 17a] two picks of errand moot running for b -> first %r, second %r" % (rep_a1.violations, rep.violations))
    bb.errand, bb.errand_t = err0, errt0
    run_frames(1)
    sx_, sy_ = scene.behaviour.waystones[1]
    bx0, by0, bst = bb.x, bb.y, bb.state
    bb.x, bb.y, bb.state, bb.route, bb.target, bb.then = float(sx_) + 1.0, float(sy_) + 1.0, "idle", [], None, None
    rep = mon.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
    caught["idle (away body dwelling at a waystone)"] = "idle" in rep.rules() and "dwells at a waystone" in str(rep.violations)
    print("[fake 17b] away b idle 1.4 cells from waystone B -> %r" % (rep.violations,))
    bb.x, bb.y, bb.state = bx0, by0, bst
    run_frames(1)
    aa = scene.behaviour.get(names[0])
    scene.behaviour.newest_speaker, scene.behaviour.newest_speaker_t = names[0], now     # spoke just now (inside the here window)
    scene.events = list(scene.events) + [{"type": "walk", "pip": names[1], "to": [aa.x, aa.y], "then": "errand:stroll"}]
    rep = mon.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
    caught["idle (away errand targets the newest speaker)"] = "idle" in rep.rules() and "targets the newest speaker" in str(rep.violations)
    print("[fake 17c] away b's errand walk aimed at the newest speaker a -> %r" % (rep.violations,))
    scene.events = [ev for ev in scene.events if ev.get("pip") != names[1]]
    run_frames(1)
    scene.events = list(scene.events) + [{"type": "walk", "pip": names[1], "to": [aa.x + 40.0, aa.y + 30.0], "then": "errand:water"}]
    rep = mon.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
    caught["idle (a clean errand walk passes)"] = "idle" not in rep.rules()
    print("[fake 17d] a clean errand walk (then errand:water, away from the speaker) -> %r" % (rep.violations,))
    scene.events = [ev for ev in scene.events if ev.get("pip") != names[1]]
    run_frames(1)
    # 17e: the newest speaker's word is OUTSIDE the here window (spoke present_s + 1 s ago): the settler is not "the newest
    #      speaker" any more, so an errand aimed where it stands is not a violation (AGES 1.3 is about the person talking now)
    scene.behaviour.newest_speaker, scene.behaviour.newest_speaker_t = names[0], now - scene.behaviour.present_s - 1.0
    scene.events = list(scene.events) + [{"type": "walk", "pip": names[1], "to": [aa.x, aa.y], "then": "errand:stroll"}]
    rep = mon.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
    caught["idle (a stale newest speaker is not a target)"] = "idle" not in rep.rules()
    print("[fake 17e] an errand aimed at a speaker whose word is outside the here window -> %r" % (rep.violations,))
    scene.events = [ev for ev in scene.events if ev.get("pip") != names[1]]
    caps_now = _idle_caps()
    caught["idle (caps resolve from the loaded behaviour, never bound at import)"] = caps_now == (0.30, 2, 4, 6.0) and "_MOOT_CAP" not in globals()
    print("[fake 17f] _idle_caps() from sys.modules -> %r (no import-time binding)" % (caps_now,))
    run_frames(1)

    # 18. W4 hook: the `age` rule's planted fakes (AGES 4.2): an age above the gate, a REGRESSED age, an age_built > age
    ages_dir = getattr(scene, "ages", None)
    if land_scene and ages_dir is not None:
        blk = ages_dir.block()
        gate0 = ages_dir.gate()
        blk["age"] = gate0 + 3
        rep = mon.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
        caught["age (age above the gate)"] = "age" in rep.rules()
        print("[fake 18a] age %d with gate %d -> %r" % (gate0 + 3, gate0, rep.violations))
        blk["age"] = gate0
        rep = mon.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
        caught["age (regressed age)"] = "age" in rep.rules() and "regressed" in str(rep.violations)
        print("[fake 18b] age %d -> %d (regressed) -> %r" % (gate0 + 3, gate0, rep.violations))
        mon._age_last = gate0
        blk["age_built"] = gate0 + 1
        rep = mon.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
        caught["age (age_built > age)"] = "age" in rep.rules() and "age_built" in str(rep.violations)
        print("[fake 18c] age_built %d > age %d -> %r" % (gate0 + 1, gate0, rep.violations))
        blk["age_built"] = min(int(blk.get("age_built") or 0), gate0)
        run_frames(1)

    # 19. W6 hook (IDLEWORLD 5.2 / 8 row 9): 12 planted bad placed rows, all refused by validate_registry and none drawn
    if land_scene:
        import numpy as np
        from stream.world import registry as _R
        post = getattr(scene, "wishes", None)
        ledger = {"h-0001", "h-0002"}
        if post is not None:
            post.ledger_ids().update(ledger)
        owner = names[0]
        camp = (scene.world.pips.get(owner) or {}).get("camp")
        camp_xy = (float(camp["x"]), float(camp["y"])) if isinstance(camp, dict) else (float(scene.terrain.site[0]) + 30.0, float(scene.terrain.site[1]))
        gx, gy = _R.place("lantern", camp_xy, scene.land, scene.terrain, seed=1) or (int(camp_xy[0]) + 6, int(camp_xy[1]) + 3)
        base = {"id": "p-0901", "ts": epoch_to_iso(now), "recipe": "lantern", "owner": owner, "askers": [owner], "wish_ids": ["h-0001"],
                "merge_key": "lantern", "x": int(gx), "y": int(gy), "age_idx": 0, "lit_rule": "owner_here", "status": "stands",
                "reveal_t0": now, "plaque": None}
        args = dict(land=scene.land, terrain=scene.terrain, ledger_ids=ledger, banished=set(), placed_rows=[], pips=scene.world.pips)
        ok0, why0 = validate_registry(base, **args)
        print("[fake 19] the honest base row validates: %s (%s) at (%d, %d)" % (ok0, why0, gx, gy))
        if not ok0:
            ok = False
        wy, wx = [int(v) for v in np.argwhere(scene.terrain.water)[0]] if bool(scene.terrain.water.any()) else (gy, gx)
        far = {"id": "p-0977", "x": int(gx) + 40, "y": int(gy), "owner": owner, "status": "stands"}
        far2 = {"id": "p-0978", "x": int(gx) + 60, "y": int(gy), "owner": owner, "status": "stands"}
        scene.land.wear[int(gy) + 12, int(gx) + 12] = 255                                  # one trail cell for fake 8
        scene.world.data["banished"]["banished-nobody"] = {"ts": epoch_to_iso(now), "by": "selftest"}
        fakes = [
            ("a creatures.* part", dict(base, id="p-0911", parts=[("creatures.render", {}, 0, 0)])),
            ("lit_rule always", dict(base, id="p-0912", lit_rule="always")),
            ("an RGB colour", dict(base, id="p-0913", recipe="banner", parts=[("buildings.banner", {"colour": (255, 0, 0)}, 0, 0)])),
            ("a banished owner", dict(base, id="p-0914", owner="banished-nobody", askers=["banished-nobody"])),
            ("a wish_id not in the ledger", dict(base, id="p-0915", wish_ids=["nope-0000"])),
            ("a water cell", dict(base, id="p-0916", x=wx, y=wy)),
            ("the Moot green", dict(base, id="p-0917", x=int(scene.land.moot[0]), y=int(scene.land.moot[1]))),
            ("a trail", dict(base, id="p-0918", x=int(gx) + 12, y=int(gy) + 12)),
            ("over cap (3rd item, lifetime 2 + tier 0)", dict(base, id="p-0919")),
            ("an unknown fn", dict(base, id="p-0920", parts=[("props.dragon", {}, 0, 0)])),
            ("a rate field", dict(base, id="p-0921", parts=[("props.stone", {"variant": 0, "rate": 2}, 0, 0)])),
            ("a fence", dict(base, id="p-0922", parts=[("buildings.fence_h", {}, 0, 0)])),
        ]
        refused = 0
        for label, row in fakes:
            a = dict(args)
            if label.startswith("over cap"):
                a["placed_rows"] = [far, far2]
            if label.startswith("a banished"):
                a["banished"] = {"banished-nobody"}
            okf, whyf = validate_registry(row, **a)
            print("[fake 19] %-42s -> %s (%s)" % (label, "REFUSED" if not okf else "ACCEPTED", whyf))
            refused += 0 if okf else 1
        caught["placed (12 planted bad rows refused by validate_registry)"] = refused == len(fakes)
        # none drawn: planted as `stands` rows, the scene's post lists none of them among its structures / live sprites, and the
        # monitor's `placed` rule names them
        planted = [dict(r) for _l, r in fakes if not _l.startswith("over cap")] + [dict(base, id="p-0919"), dict(far), dict(far2)]
        wblk = scene.world.data["world"]
        saved_rows = list(wblk.get("placed") or [])
        wblk["placed"] = saved_rows + planted
        drawn = []
        if post is not None:
            post._valid_cache.clear()
            ids = {p["id"] for p in planted}
            drawn = [s["id"] for s in post.structures() if s["id"] in ids] + [d[3].get("id") for d in post.live_sprites(now, lambda x, y: True, 0) if d[3].get("id") in ids]
        rep19 = run_frames(1)
        caught["placed (none of the planted rows drawn; the monitor names them)"] = not drawn and "placed" in rep19.rules()
        print("[fake 19] planted %d stands rows -> drawn %r, monitor rules %r" % (len(planted), drawn, sorted(rep19.rules())))
        wblk["placed"] = saved_rows
        scene.land.wear[int(gy) + 12, int(gx) + 12] = 0
        scene.world.data["banished"].pop("banished-nobody", None)
        if post is not None:
            post._valid_cache.clear()
        run_frames(1)
        # validate_copy: a template passes, a banned word / a version tag / `day N` do not
        caught["copy (validate_copy refuses banned copy)"] = validate_copy("wished: a castle · @kai +3") and validate_copy("lantern · @kai @jo · since 3 Oct") \
            and not validate_copy("the keepers build a castle") and not validate_copy("raised · v1.2") and not validate_copy("day 3 · a lantern")
        print("[fake 19] validate_copy: template ok, `build` / `v1.2` / `day 3` refused -> %s" % caught["copy (validate_copy refuses banned copy)"])

    # 8. after cleanup: violation-free again (the monitor does not get stuck)
    rep = run_frames(3)
    print("[after] clean again: ok=%s violations=%r counts=%r" % (rep.ok, rep.violations, rep.counts))
    if not rep.ok:
        print("FAIL: monitor still reports violations after the fakes were removed")
        ok = False
    # 9. enforce mode removes a forged entity so it is never drawn
    mon2 = HonestyMonitor(scene, enforce=True, log=lambda m: None)
    ghost2 = Entity("ghost-two", "chat", now)
    ghost2.state, ghost2.display_name, ghost2.cleared = "idle", "ghost2", True
    scene.behaviour.entities["ghost-two"] = ghost2
    rep2 = mon2.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
    removed = "ghost-two" not in scene.behaviour.entities
    caught["enforce (forged entity removed)"] = ("record" in rep2.rules()) and removed
    print("[fake 9] enforce=True: caught=%s removed=%s summary=%r" % ("record" in rep2.rules(), removed, mon2.summary()["removed"]))

    for k, v in caught.items():
        print("[planted] %-45s %s" % (k, "CAUGHT" if v else "MISSED"))
        if not v:
            ok = False
    img = scene.frame(mkctx(now, 0, raw[-20:], clear[-10:]), size)
    img.save(os.path.join(frames_dir, "final.png"))
    print("[frames] %s" % ", ".join(sorted(os.listdir(frames_dir))))
    print("[monitor] %r" % (mon.summary(),))
    print("HONESTY SELF-TEST %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        sys.exit(_selftest(os.environ.get("RUN_DIR") or "/tmp/pip-keepers-honesty"))
    print(__doc__)
