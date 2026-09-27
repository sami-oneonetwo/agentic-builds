"""stream/world/wishes.py - the wish post + registry consumer (IDLEWORLD.md 2.2-2.5, 3.2-3.3, 5.1-5.2, 6.1-6.2; 8 row 9, W6).

    from stream.world import wishes as W
    post = W.WishPost(scene)                  # attached by the scene at boot (hook); sets scene.menu_wishes /
                                              # take_promotions / promotions_pending for rounds.py (S1 hooks)
    post.on_record(m, key, t, now)            # every ctx.chat record with m["wish"], the frame it clears the hold
    events = post.tick(now, ctx, frame_events)   # the place queue, the reveal, wish_class.jsonl re-classes -> scene events
    post.camera_filter(events, now)           # `placed` is a camera EVENT only under the 3.3 rule
    post.glow_sources(now) ; post.live_sprites(now, visible, n) ; post.draw(rgb, data, ...)
    post.structures()                         # static parts of standing rows for the bake (marks["structures"])
    W.plate_rows(scene, now, shown) ; W.plate_pins(scene, now, present) ; W.plank_line(scene, ev, shown)
    W.plank_log(run_dir, now, text, prio) ; W.hide_owner(world, key) ; W.restore_owner_rows(world, key, rec)
    W.part_sprite(structure_row, sun, season) -> (spr, dx_px, dy_px)      # bake.paint_props
    $PY stream/world/wishes.py --self-test    # the 8 row 9 fixture under /tmp (MODE=test)
    $PY stream/world/wishes.py --clip         # a lantern placed and revealed; report/ PNGs at 720p and 320x180

What this module owns (and nothing else does): the classification call (`registry.classify`) for every wish-tagged
record, the ONE paper per person in `world.wish_post[]`, the clusters (`merge_key` -> distinct askers by first ask),
the place queue (FIFO by first ask, one raise per PLACE_EVERY_S, `registry.CAPS` through `registry.cap_check`,
`registry.place` for the site, `honesty.validate_registry` before the first pixel), the `placed[]` rows (rising ->
stands, hidden on banish), the bottom-up reveal at <= 1 Hz over RAISE_S, the events `wish` / `placed` / `placed_step` /
`placed_ship` / `wish_refused` / `wish_have`, the outcome ledger `wishes.out.jsonl`, the `wish_class.jsonl` tail, the
menu bias and the promotions for rounds.py, the plate / plank copy (closed templates over `registry.NOUNS`, every
string through `validate_copy` at write time) and `plank_log.jsonl`.

Honesty (5.1): every number drawn is a len(); the paper count is people with an open paper; a placed row names an
owner who asked and every asker; a banished owner's rows are hidden and its plaque masked; nothing here says what is
coming ("pinned", "+N", "N ask", "rises", "stands" are the only forward words); a chatter's sentence is never a value
in a template (the noun is `registry.NOUNS[merge_key]`); no text reaches a path or a shell.

Schema: the fields `wish_post`, `placed`, `placed_seq` (6.1) are read with .get() and created on first write, so a
schema-2 world.json works (W3 bumps SCHEMA and migrates). Nothing here imports behaviour / honesty / state at module
level: every cross-module import is inside a function (compositor.HotReloader re-executes stream/world modules in
WORLD_ORDER; an unlisted module follows alphabetically, so `registry` and `wishes` reload after the core).
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
import sys
import time as _time
import traceback
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ---------------------------------------------------------------------------- constants (IDLEWORLD 2.3-2.4, 3.1, 3.3)
PLACE_EVERY_S = 90.0             # one raise per this (registry.PLACE_EVERY_S is the same number; this copy is the scene's)
RAISE_S = 20.0                   # the reveal runs this long, bottom-up, <= 1 Hz
REFUSE_COOLDOWN_S = 30.0         # one refusal line per person per this
PLACED_EVENT_GAP_S = 60.0        # `placed` is a camera EVENT at most this often
PLACED_EVENT_MAX_HERE = 2        # ... and only while <= this many are here, or the owner is here
POST_PIN_S = 10.0                # the post's plate pins this long after every wish ...
POST_PIN_MAX_HERE = 10           # ... while <= this many are here
PLACED_PLATE_PIN_S = 20.0        # a placed thing's plate pins this long at the ship
PLANK_NEW_ONLY_ABOVE = 100       # at this many here only a NEW cluster or a placed thing gets a plank line (3.2)
MENU_WINDOW_S = 900.0            # menu wishes count inside this window (the round window, 2.5)
RECIPE_WINDOW_S = 24 * 3600.0    # recipe clusters live this long (2.5)
LIVE_SPRITES_MAX = 24            # live registry sprites in view (the rest stay baked)
TAIL_EVERY_S = 2.0               # wish_class.jsonl / wishes.jsonl tails
PLANK_LOG_MAX = 2000             # plank_log.jsonl rotates past this many lines
LANTERN_GLOW = (46, (255, 186, 96), 0.42)
TRY_ROT_START = 0
POST_KEY = "post"                # MOOT_LAYOUT["post"] (steading hook) = (34, 10)
POST_OFFSET = (34, 10)           # the fallback when the scene's layout lacks the key
PAPERS_MAX = 5
PLANK_PRIO_VERB = 2              # panels/world.py PRIO_VERB (by value: the panel is not imported here)
PLANK_DUR_S = 5.0
OUT_STAGES = ("classified", "pinned", "unpinned", "queued", "placed", "raised", "refused", "promoted", "answered")
STRUCTURE_LIVE_FNS = ("buildings.lantern",)          # always live (lit state follows presence)
STRUCTURE_WIND_FNS = ("buildings.banner",)           # live keyed on the wind phase; baked fallback under degrade >= 3
BANNER_BAKED_FALLBACK_DEGRADE = 3
GARDEN_OFFSET_CELLS = (-3, -2)                       # buildings.garden anchors at its footprint's top-left: the site is its centre


def _log(msg: str) -> None:
    sys.stderr.write("[wishes] %s\n" % msg)
    sys.stderr.flush()


def _reg():
    """The registry as it is NOW (a hot reload re-executes it under its dotted name)."""
    from stream.world import registry
    return registry


def _iso(t: float) -> str:
    return _dt.datetime.fromtimestamp(float(t), tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % int((t % 1) * 1000))


def _epoch(s: Any) -> Optional[float]:
    try:
        from stream.state_store import iso_to_epoch
        return iso_to_epoch(s)
    except Exception:
        return None


def _since_text(ts: Any) -> str:
    """`3 Oct`: a day word for the plaque, never a clock (BANNED_CLOCK_RE) and never `day N` (BANNED_DAY_RE)."""
    t = _epoch(ts)
    if t is None:
        return "today"
    d = _dt.datetime.fromtimestamp(t)
    return "%d %s" % (d.day, d.strftime("%b"))


# ---------------------------------------------------------------------------- copy (validated at write time, 5.1)
_COPY_FAILED_LOGGED: Set[str] = set()


def validate_copy(text: str) -> bool:
    """honesty.validate_copy when it exists (banned copy + day / version / clock patterns + the blocklist), else the
    compositor's banned_copy_hits alone. A failed string draws nothing and logs one line (per string)."""
    ok = True
    try:
        from stream.world import honesty as H
        fn = getattr(H, "validate_copy", None)
        if callable(fn):
            ok = bool(fn(text))
        else:
            raise AttributeError("validate_copy")
    except Exception:
        try:
            from stream import compositor as C
            ok = not C.Compositor.banned_copy_hits([text])
        except Exception:
            ok = True
        if ok:
            try:
                from stream.chat_bridge import word_lists
                ok = word_lists().blocked(text) is None
            except Exception:
                pass
    if not ok and text not in _COPY_FAILED_LOGGED:
        _COPY_FAILED_LOGGED.add(text)
        _log("copy refused at write time (drawn nothing): %d chars" % len(str(text or "")))
    return ok


def _tpl(kind: str, table: str, **kw) -> Optional[str]:
    R = _reg()
    tbl = getattr(R, table, {})
    t = tbl.get(kind)
    if not t:
        return None
    try:
        s = t.format(**kw)
    except Exception:
        return None
    return s if validate_copy(s) else None


# ---------------------------------------------------------------------------- the clusters
class Cluster(object):
    __slots__ = ("merge_key", "cls", "noun", "askers", "wish_ids", "first_ts", "last_ts", "status", "recipe")

    def __init__(self, merge_key: str, cls: str, noun: Optional[str], recipe: Optional[str], ts: float):
        self.merge_key = merge_key
        self.cls = cls
        self.noun = noun
        self.recipe = recipe
        self.askers: List[str] = []
        self.wish_ids: List[str] = []
        self.first_ts = float(ts)
        self.last_ts = float(ts)
        self.status = "open"                 # open | queued | placed | capped

    def join(self, key: str, wish_id: str, ts: float) -> bool:
        """True when this is a NEW asker (a person joins a cluster once, 2.5)."""
        if wish_id and wish_id not in self.wish_ids:
            self.wish_ids.append(wish_id)
            if len(self.wish_ids) > 200:
                del self.wish_ids[:-200]
        self.last_ts = max(self.last_ts, float(ts))
        if key in self.askers:
            return False
        self.askers.append(key)
        return True

    def window(self) -> float:
        if self.cls.startswith("menu"):
            return MENU_WINDOW_S
        if self.cls.startswith("project"):
            return float("inf")              # projects cluster for the life of the age (W4 reads them)
        return RECIPE_WINDOW_S


# ---------------------------------------------------------------------------- the post
class WishPost(object):
    def __init__(self, scene, run_dir: Optional[str] = None, log: Optional[Callable[[str], None]] = None):
        self.scene = scene
        self.run_dir = run_dir or getattr(scene, "run_dir", None) or os.environ.get("RUN_DIR") or os.path.join(_ROOT, "run")
        self.log = log or getattr(scene, "log", None) or _log
        self._seen: Set[str] = set()                    # chat ids this post classified
        self._ledger_ids: Set[str] = set()              # wishes.jsonl ids (tail) + ids seen as chat records
        self._clusters: Dict[str, Cluster] = {}
        self._id_key: Dict[str, Tuple[str, str]] = {}   # wish id -> (key, merge_key) for re-classes
        self._queue: List[Dict[str, Any]] = []          # place queue: {merge_key, recipe, first_ts}
        self._promotions: List[Dict[str, Any]] = []
        self._menu: Dict[Tuple[str, str], Dict[str, float]] = {}
        self._refuse_t: Dict[str, float] = {}
        self._rot = TRY_ROT_START
        self._last_place_t: Optional[float] = None
        self._rising: Optional[str] = None
        self._rising_steps = 0
        self._post_pin_until = 0.0
        self._placed_pin: Optional[Tuple[str, float]] = None
        self._last_placed_event_t: Optional[float] = None
        self._tail_t: Optional[float] = None
        self._class_tail = None
        self._ledger_tail = None
        self._valid_cache: Dict[str, Tuple[bool, str]] = {}
        self._reveal_cache: Dict[Tuple, np.ndarray] = {}
        self._pending_events: List[Dict[str, Any]] = []
        self._out_path = os.path.join(self.run_dir, "wishes.out.jsonl")
        self.stats_: Dict[str, int] = {"classified": 0, "pinned": 0, "placed": 0, "raised": 0, "refused": 0, "promoted": 0,
                                       "reclassed": 0, "copy_refused": 0, "live_sprites": 0}
        self._booted_from_ledger = False
        # the S1 rounds hooks read these off the scene (getattr-guarded there): no scene edit needed
        try:
            scene.menu_wishes = self.menu_wishes
            scene.take_promotions = self.take_promotions
            scene.promotions_pending = self.promotions_pending
            scene.wishes = self
        except Exception:
            pass

    # ------------------------------------------------------------------ document access (.get everywhere: schema 2 works)
    def _wblk(self) -> Optional[Dict[str, Any]]:
        w = getattr(self.scene, "world", None)
        if w is None:
            return None
        try:
            return w.data["world"]
        except Exception:
            return None

    def wish_post(self) -> List[Dict[str, Any]]:
        w = self._wblk()
        rows = (w or {}).get("wish_post")
        return rows if isinstance(rows, list) else []

    def placed(self) -> List[Dict[str, Any]]:
        w = self._wblk()
        rows = (w or {}).get("placed")
        return rows if isinstance(rows, list) else []

    def _set(self, field: str, value: Any) -> None:
        w = self._wblk()
        if w is None:
            return
        w[field] = value
        self._dirty()

    def _dirty(self) -> None:
        try:
            self.scene.world.dirty = True
        except Exception:
            pass

    def _pips(self) -> Dict[str, Dict[str, Any]]:
        try:
            return self.scene.world.data["pips"]
        except Exception:
            return {}

    def _banished(self) -> Set[str]:
        try:
            return set(str(k).lower() for k in (self.scene.world.data.get("banished") or {}))
        except Exception:
            return set()

    def _now(self) -> float:
        t = getattr(self.scene, "_last_now", None)
        return float(t) if t is not None else _time.time()

    def _present(self, key: str, now: float) -> bool:
        b = getattr(self.scene, "behaviour", None)
        e = b.get(key) if b is not None else None
        try:
            return bool(e is not None and e.is_present(now))
        except Exception:
            return False

    def _present_count(self) -> int:
        try:
            return int(self.scene.present_count())
        except Exception:
            return 0

    def post_xy(self) -> Tuple[int, int]:
        sc = self.scene
        try:
            layout = getattr(sys.modules.get(type(sc).__module__), "MOOT_LAYOUT", None) or {}
            dx, dy = layout.get(POST_KEY, POST_OFFSET)
            sx, sy = sc.terrain.site
            return int(sx + dx), int(sy + dy)
        except Exception:
            try:
                mx, my = sc.land.moot
                return int(mx + POST_OFFSET[0]), int(my + POST_OFFSET[1])
            except Exception:
                return (0, 0)

    def papers(self) -> int:
        """1..5 papers = min(5, people with an open paper); 0 = a bare post (a paper is a record)."""
        return max(0, min(PAPERS_MAX, len(self.wish_post())))

    def ledger_ids(self) -> Set[str]:
        return self._ledger_ids

    # ------------------------------------------------------------------ outcomes (wishes.out.jsonl, 6.2)
    def _out(self, wid: Optional[str], now: float, stage: str, cls: Optional[str] = None, noun: Optional[str] = None,
             merge_key: Optional[str] = None, item: Optional[str] = None, reason: Optional[str] = None) -> None:
        if stage in self.stats_:
            self.stats_[stage] += 1
        row = {"id": wid, "ts": _iso(now), "stage": stage, "class": cls, "noun": noun, "merge_key": merge_key,
               "item": item, "reason": reason}
        try:
            os.makedirs(self.run_dir, exist_ok=True)
            with open(self._out_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
        except Exception:
            pass

    # ------------------------------------------------------------------ boot: clusters from the ledger (records, never a re-pin)
    def boot(self, now: float) -> Dict[str, int]:
        """Rebuild the clusters and the place queue from `wishes.jsonl` (+ `wishes.out.jsonl` outcomes) so a restart
        keeps every ask; papers are already in world.wish_post (persisted). Idempotent; never emits an event."""
        if self._booted_from_ledger:
            return {}
        self._booted_from_ledger = True
        out = {"rows": 0, "clusters": 0, "queued": 0}
        R = _reg()
        done: Dict[str, str] = {}
        try:
            with open(self._out_path, "r", encoding="utf-8") as fh:
                for ln in fh:
                    try:
                        r = json.loads(ln)
                    except Exception:
                        continue
                    if r.get("id"):
                        done[str(r["id"])] = str(r.get("stage") or "")
        except OSError:
            pass
        placed_ids: Set[str] = set()
        for row in self.placed():
            for w in row.get("wish_ids") or []:
                placed_ids.add(str(w))
            if row.get("status") == "rising":
                self._rising = str(row.get("id"))
                self._rising_steps = 0
                if self._last_place_t is None:
                    self._last_place_t = _epoch(row.get("ts"))
        rows = self._read_ledger_rows()
        for r in rows:
            wid = str(r.get("id") or "")
            if wid:
                self._ledger_ids.add(wid)
            if not r.get("wish") or not wid or wid in self._seen:
                continue
            key = str(r.get("key") or r.get("by") or "").lower()
            ts = _epoch(r.get("ts")) or now
            if not key or key not in self._pips() or key in self._banished():
                continue
            verb = r.get("verb")
            if r.get("src") == "replay" and r.get("kind") == "plain" and not verb:
                # Older replay ledgers omitted verb metadata. A past planting action
                # is not consent to create another object on every boot.
                from stream.chat_bridge import ChatBridge
                parsed = ChatBridge.parse_verb(str(r.get("text") or ""))
                verb = parsed[0] if parsed else None
            w = R.classify(str(r.get("text") or ""), verb=verb, hint=r.get("hint"),
                           kind="idea" if r.get("kind") == "idea" else "plain")
            self._seen.add(wid)
            out["rows"] += 1
            if w.cls in ("silent", "have_it") or w.cls.startswith("refuse"):
                continue
            # Projects remain part of the settlement's record across restarts.
            # Recipe/menu requests retain their own bounded freshness window.
            window = MENU_WINDOW_S if w.cls.startswith("menu") else RECIPE_WINDOW_S
            if not w.cls.startswith("project") and now - ts > window:
                continue
            c = self._cluster(w, ts)
            c.join(key, wid, ts)
            self._id_key[wid] = (key, c.merge_key)
            if w.cls.startswith("menu") and w.param and w.value is not None:
                self._menu.setdefault((w.param, str(w.value)), {})[key] = ts
            if w.recipe and wid not in placed_ids and done.get(wid) not in ("placed", "refused", "unpinned") and c.status == "open":
                self._enqueue(c, ts)
                out["queued"] += 1
        out["clusters"] = len(self._clusters)
        for c in self._clusters.values():
            if any(w in placed_ids for w in c.wish_ids):
                c.status = "placed"
        return out

    def _read_ledger_rows(self) -> List[Dict[str, Any]]:
        path = os.path.join(self.run_dir, "wishes.jsonl")
        rows: List[Dict[str, Any]] = []
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            return rows
        for ln in data.split(b"\n"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln.decode("utf-8", "replace"))
            except Exception:
                continue
            if isinstance(r, dict):
                rows.append(r)
        return rows

    # ------------------------------------------------------------------ the record (2.2): one call per wish-tagged record
    def on_record(self, m: Dict[str, Any], key: str, t: float, now: float) -> Optional[Any]:
        """Classify one moderated record the frame it clears the hold and apply the class. Returns the Wish or None.
        A dropped (blocklisted / hidden) or history record never reaches classify."""
        if not isinstance(m, dict) or not m.get("wish") or m.get("dropped") or m.get("history"):
            return None
        mid = str(m.get("id") or "")
        key = str(key or m.get("name") or "").lower()
        if not mid or not key or mid in self._seen:
            return None
        self._seen.add(mid)
        self._ledger_ids.add(mid)
        text = str(m.get("text_clean") or m.get("text") or "")
        kind = "idea" if m.get("kind") == "idea" else "plain"
        R = _reg()
        try:
            w = R.classify(text, verb=m.get("verb"), hint=m.get("hint"), kind=kind)
        except Exception as e:
            self.log("registry.classify failed: %r" % (e,))
            return None
        self._out(mid, now, "classified", w.cls, w.noun, w.merge_key)
        try:
            self._apply(key, mid, float(t), w, now, text if kind == "idea" else None, m.get("display_name"))
        except Exception:
            self.log("wish apply failed: %s" % traceback.format_exc().strip().splitlines()[-1])
        return w

    def _cluster(self, w, ts: float) -> Cluster:
        c = self._clusters.get(w.merge_key)
        if c is None or ts - c.last_ts > c.window():
            c = Cluster(w.merge_key, w.cls, w.noun, w.recipe, ts)
            self._clusters[w.merge_key] = c
        return c

    def _events(self) -> List[Dict[str, Any]]:
        b = getattr(self.scene, "behaviour", None)
        ev = getattr(b, "events", None)
        if isinstance(ev, list):
            return ev
        return self._pending_events

    def _apply(self, key: str, mid: str, ts: float, w, now: float, idea_text: Optional[str], display: Optional[str]) -> None:
        cls = str(w.cls)
        px, py = self.post_xy()
        if cls == "silent":
            return
        if cls.startswith("refuse:"):
            kind = cls.split(":", 1)[1]
            self._out(mid, now, "refused", cls, w.noun, w.merge_key, reason=kind)
            last = self._refuse_t.get(key)
            if self._present(key, now) and (last is None or now - last >= REFUSE_COOLDOWN_S):
                self._refuse_t[key] = now
                self._events().append({"type": "wish_refused", "pip": key, "kind": kind, "rot": self._rot, "id": mid})
                self._rot += 1
            return
        if cls == "have_it":
            days = 0
            try:
                camp = (self._pips().get(key) or {}).get("camp")
                if isinstance(camp, dict):
                    days = len(camp.get("sessions") or camp.get("nights") or [])
            except Exception:
                days = 0
            self._out(mid, now, "answered", cls, w.noun, w.merge_key)
            if self._present(key, now):
                self._events().append({"type": "wish_have", "pip": key, "what": w.merge_key, "days": days, "id": mid})
            return
        # a paper: recipe / project / menu / mechanic / unknown
        c = self._cluster(w, ts)
        was_new = not c.askers
        joined = c.join(key, mid, ts)
        self._id_key[mid] = (key, c.merge_key)
        rows = [r for r in self.wish_post() if r.get("key") != key]          # the newest replaces the person's older paper
        rows.append({"key": key, "wish_id": mid, "ts": _iso(ts), "class": cls, "noun": w.noun, "merge_key": w.merge_key})
        self._set("wish_post", rows)
        self._out(mid, now, "pinned", cls, w.noun, w.merge_key)
        self._post_pin_until = now + POST_PIN_S                            # plate_pins() gates it on <= 10 here at draw time
        self._events().append({"type": "wish", "pip": key, "x": px, "y": py, "merge_key": c.merge_key, "noun": w.noun,
                               "pinned": len(rows), "new": was_new, "plus": (joined and not was_new), "askers": len(c.askers),
                               "id": mid, "class": cls})
        if cls.startswith("menu") and w.param and w.value is not None:
            self._menu.setdefault((w.param, str(w.value)), {})[key] = ts
        elif cls == "mechanic":
            self._promote(c, key, mid, idea_text, display, now)
        elif w.recipe:
            if c.status == "open":
                # the caps are read at the ask (the person learns at once) and again at the raise (a session may have turned)
                counts = self._cap_counts(key, int((self._wblk() or {}).get("age") or 0))
                ok, why = _reg().cap_check(counts["person_placed"], counts["person_session"], counts["age_placed"], counts["age"], counts["camp_tier"])
                if not ok:
                    c.status = "capped"
                    self._out(mid, now, "refused", cls, w.noun, w.merge_key, reason="cap:%s" % why)
                else:
                    self._enqueue(c, ts)
                    self._out(mid, now, "queued", cls, w.noun, w.merge_key)

    def _promote(self, c: Cluster, key: str, mid: str, idea_text: Optional[str], display: Optional[str], now: float) -> None:
        mk = c.merge_key.split(":", 1)[1] if c.merge_key.startswith("mechanic:") else c.merge_key
        text = (idea_text or mk or "idea").strip()
        who = str(display or key)
        for pr in self._promotions:
            if pr.get("merge_key") == mk:
                if who != pr.get("by") and who not in pr["plus_by"]:
                    pr["plus_by"].append(who)
                if mid not in pr["wish_ids"]:
                    pr["wish_ids"].append(mid)
                self._out(mid, now, "promoted", c.cls, c.noun, c.merge_key, reason="plus")
                return
        self._promotions.append({"text": text[:60], "by": who, "plus_by": [], "merge_key": mk, "wish_ids": [mid]})
        if len(self._promotions) > 200:
            del self._promotions[:-200]
        self._out(mid, now, "promoted", c.cls, c.noun, c.merge_key)

    def _enqueue(self, c: Cluster, ts: float) -> None:
        if any(q.get("merge_key") == c.merge_key for q in self._queue):
            return
        c.status = "queued"
        self._queue.append({"merge_key": c.merge_key, "recipe": c.recipe, "first_ts": float(ts)})
        self._queue.sort(key=lambda q: q["first_ts"])                        # FIFO by first ask

    # ------------------------------------------------------------------ rounds.py hooks (S1: getattr-guarded there)
    def menu_wishes(self) -> Dict[Tuple[str, str], int]:
        """{(param, value): len(distinct askers in the open window)}."""
        now = self._now()
        out: Dict[Tuple[str, str], int] = {}
        for (param, value), asks in list(self._menu.items()):
            live = {k: t for k, t in asks.items() if now - t <= MENU_WINDOW_S}
            if live:
                self._menu[(param, value)] = live
                out[(param, value)] = len(live)
            else:
                self._menu.pop((param, value), None)
        return out

    def take_promotions(self) -> List[Dict[str, Any]]:
        out, self._promotions = self._promotions, []
        return out

    def promotions_pending(self) -> bool:
        return bool(self._promotions)

    def project_asks(self) -> Dict[str, List[str]]:
        """{slug: [asker keys]} for open project clusters (W4 reads the most-asked project for the monument plate)."""
        return {c.merge_key: list(c.askers) for c in self._clusters.values() if c.cls.startswith("project:") and c.askers}

    def clusters(self) -> Dict[str, Cluster]:
        return self._clusters

    # ------------------------------------------------------------------ the per-frame tick
    def tick(self, now: float, ctx=None, frame_events: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Called by the scene once per frame after the behaviour tick: tails, the place queue, the reveal. Returns the
        events this frame (the scene appends them to its own list)."""
        out: List[Dict[str, Any]] = []
        if not getattr(self.scene, "booted", False):
            return out
        if not self._booted_from_ledger:
            try:
                rep = self.boot(now)
                if rep:
                    self.log("wishes: ledger replay %r, %d papers, %d placed" % (rep, len(self.wish_post()), len(self.placed())))
            except Exception:
                self.log("wishes boot failed: %s" % traceback.format_exc().strip().splitlines()[-1])
        if self._pending_events:
            out.extend(self._pending_events)
            del self._pending_events[:]
        try:
            if self._tail_t is None or now - self._tail_t >= TAIL_EVERY_S:
                self._tail_t = now
                self._tails(now, out)
        except Exception:
            self.log("wishes tail failed: %s" % traceback.format_exc().strip().splitlines()[-1])
        try:
            self._rising_tick(now, out)
            if self._rising is None and not self._age_building():
                self._place_tick(now, out)
        except Exception:
            self.log("wishes place tick failed: %s" % traceback.format_exc().strip().splitlines()[-1])
        return out

    def rising(self) -> Optional[str]:
        """The placed row rising right now (its id) or None (W4's age_check holds while one rises)."""
        return self._rising or next((r.get("id") for r in self.placed() if r.get("status") == "rising"), None)

    def _age_building(self) -> bool:
        """W4 seam: True while the age director's 90 s build runs (scene.ages.build) or the world block carries an
        `age_build` in flight (a resumed build before the director's first tick): the place queue waits, nothing lost."""
        d = getattr(self.scene, "ages", None)
        try:
            if d is not None and getattr(d, "build", None) is not None:
                return True
        except Exception:
            pass
        w = self._wblk()
        return bool(isinstance(w, dict) and w.get("age_build"))

    # -- tails: the probe's re-classes (wish_class.jsonl) and the ledger's ids (wishes.jsonl)
    def _tails(self, now: float, out: List[Dict[str, Any]]) -> None:
        from stream.state_store import JsonlTail
        if self._ledger_tail is None:
            self._ledger_tail = JsonlTail(os.path.join(self.run_dir, "wishes.jsonl"), boot_tail_bytes=1 << 30)
        for r in self._ledger_tail.read_new():
            if r.get("id"):
                self._ledger_ids.add(str(r["id"]))
        if self._class_tail is None:
            self._class_tail = JsonlTail(os.path.join(self.run_dir, "wish_class.jsonl"), boot_tail_bytes=1 << 30)
        for r in self._class_tail.read_new():
            try:
                self._reclass(r, now, out)
            except Exception:
                continue

    def _reclass(self, r: Dict[str, Any], now: float, out: List[Dict[str, Any]]) -> None:
        wid = str(r.get("id") or "")
        cls = str(r.get("class") or "")
        if not wid or (wid not in self._ledger_ids and wid not in self._seen):
            return                                                          # an id not in the ledger is ignored (6.2)
        if wid not in self._id_key:
            return
        key, old_mk = self._id_key[wid]
        R = _reg()
        if cls == "silent":
            rows = [x for x in self.wish_post() if x.get("wish_id") != wid]
            if len(rows) != len(self.wish_post()):
                self._set("wish_post", rows)
                self._out(wid, now, "unpinned", cls, None, old_mk, reason="reclass")
            c = self._clusters.get(old_mk)
            if c is not None and wid in c.wish_ids:
                c.wish_ids.remove(wid)
                if not any(self._id_key.get(x, ("",))[0] == key for x in c.wish_ids) and key in c.askers:
                    c.askers.remove(key)
            self.stats_["reclassed"] += 1
            return
        if cls.startswith("recipe:") or cls.startswith("project:") or cls.startswith("menu:") or cls in ("mechanic", "unknown"):
            slug = cls.split(":", 1)[1] if ":" in cls else None
            recipe = slug if (cls.startswith("recipe:") and slug in getattr(R, "RECIPES", {})) else None
            mk = str(r.get("merge_key") or slug or old_mk)
            noun = r.get("noun") if (r.get("noun") in getattr(R, "NOUNS", {}).values()) else R.noun_for(mk, cls)
            w = R.Wish(cls, noun, mk, recipe, None, None)
            c = self._cluster(w, now)
            c.join(key, wid, now)
            self._id_key[wid] = (key, mk)
            rows = [x for x in self.wish_post() if x.get("key") != key]
            rows.append({"key": key, "wish_id": wid, "ts": _iso(now), "class": cls, "noun": noun, "merge_key": mk})
            self._set("wish_post", rows)
            self._out(wid, now, "pinned", cls, noun, mk, reason="reclass")
            self.stats_["reclassed"] += 1
            if recipe and c.status == "open":
                self._enqueue(c, now)
            px, py = self.post_xy()
            out.append({"type": "wish", "pip": key, "x": px, "y": py, "merge_key": mk, "noun": noun, "pinned": len(rows),
                        "new": len(c.askers) == 1, "plus": False, "askers": len(c.askers), "id": wid, "class": cls, "reclass": True})

    # -- the place queue (2.3 tier 1)
    def _session_start(self) -> Optional[float]:
        try:
            sid = self.scene.session_id
            for s in self.scene.world.data.get("sessions") or []:
                if s.get("id") == sid:
                    return _epoch(s.get("started_ts"))
        except Exception:
            return None
        return None

    def _cap_counts(self, owner: str, age: int) -> Dict[str, int]:
        rows = [r for r in self.placed() if r.get("status") != "hidden"]
        mine = sorted((r for r in rows if r.get("owner") == owner), key=lambda r: str(r.get("ts") or ""))
        started = self._session_start()
        session = 0
        for r in mine:
            t = _epoch(r.get("ts"))
            if started is not None and t is not None and t >= started - 60.0:
                session += 1
        firsts: Set[str] = set()
        beyond = 0
        for r in sorted(rows, key=lambda r: str(r.get("ts") or "")):
            o = str(r.get("owner") or "")
            if o not in firsts:
                firsts.add(o)
                continue
            if int(r.get("age_idx") or 0) == int(age):
                beyond += 1
        camp = (self._pips().get(owner) or {}).get("camp")
        tier = int(camp.get("tier") or 0) if isinstance(camp, dict) else 0
        return {"person_placed": len(mine), "person_session": session, "age_placed": beyond, "age": int(age), "camp_tier": tier}

    def _camp_xy(self, owner: str) -> Optional[Tuple[float, float]]:
        p = self._pips().get(owner) or {}
        camp = p.get("camp")
        if isinstance(camp, dict) and camp.get("x") is not None:
            return float(camp["x"]), float(camp["y"])
        b = getattr(self.scene, "behaviour", None)
        e = b.get(owner) if b is not None else None
        if e is not None and e.is_on_land():
            return float(e.x), float(e.y) - 3.0
        try:
            from stream.world import land as LAND
            ld = self.scene.land
            taken = [(c["x"], c["y"]) for c in ld.camps() if c.get("x") is not None]
            return tuple(float(v) for v in LAND.hashed_camp_spot(owner, ld.moot, taken, ld.passable, ld.water))
        except Exception:
            return None

    def _validate(self, row: Dict[str, Any], at_placement: bool = False) -> Tuple[bool, str]:
        """honesty.validate_registry over one row. at_placement=True is the place queue's gate for a NEW row (site: never
        water, a trail, the Moot green, the gaps, the caps); the default re-checks a standing / rising row with the
        ENDURING set only (provenance / type / schema): a trail worn across it later or a camp pitched beside it never
        un-draws a placed thing (credit is forever, IDLEWORLD 2.5)."""
        try:
            from stream.world import honesty as H
            fn = getattr(H, "validate_registry", None)
        except Exception:
            fn = None
        rows = [r for r in self.placed() if r.get("id") != row.get("id")]
        if callable(fn):
            try:
                kw = dict(land=getattr(self.scene, "land", None), terrain=getattr(self.scene, "terrain", None),
                          ledger_ids=self._ledger_ids, banished=self._banished(), placed_rows=rows, pips=self._pips())
                try:
                    ok, why = fn(row, at_placement=at_placement, **kw)
                except TypeError:                                   # an older honesty.py without the flag: the full check
                    ok, why = fn(row, **kw)
                return bool(ok), str(why)
            except Exception as e:
                return False, "validator raised %r" % (e,)
        R = _reg()
        probs = R.recipe_problems(str(row.get("recipe")))
        return (not probs), ("; ".join(probs) if probs else "ok (registry static checks only)")

    def _place_tick(self, now: float, out: List[Dict[str, Any]]) -> None:
        if not self._queue:
            return
        if self._last_place_t is not None and now - self._last_place_t < PLACE_EVERY_S:
            return
        R = _reg()
        w = self._wblk()
        if w is None:
            return
        age = int(w.get("age") or 0)
        pips = self._pips()
        banished = self._banished()
        while self._queue:
            item = self._queue[0]
            c = self._clusters.get(item["merge_key"])
            if c is None or not c.askers or not item.get("recipe"):
                self._queue.pop(0)
                continue
            first_id = c.wish_ids[0] if c.wish_ids else None
            owner = next((k for k in c.askers if k in pips and not pips[k].get("_test") and k not in banished), None)
            if owner is None:
                self._queue.pop(0)
                c.status = "open"
                self._out(first_id, now, "refused", c.cls, c.noun, c.merge_key, reason="no real owner")
                continue
            counts = self._cap_counts(owner, age)
            ok, why = R.cap_check(counts["person_placed"], counts["person_session"], counts["age_placed"], counts["age"], counts["camp_tier"])
            if not ok:
                self._queue.pop(0)
                c.status = "capped"
                self._out(first_id, now, "refused", c.cls, c.noun, c.merge_key, reason="cap:%s" % why)
                continue
            camp_xy = self._camp_xy(owner)
            others = [r for r in self.placed() if r.get("status") != "hidden"]
            moot = None
            try:
                moot = (float(self.scene.land.moot[0]), float(self.scene.land.moot[1]))
            except Exception:
                pass
            seq = int(w.get("placed_seq") or 0) + 1
            xy = R.place(item["recipe"], camp_xy, getattr(self.scene, "land", None), getattr(self.scene, "terrain", None),
                         placed=others, moot_xy=moot, seed=seq) if camp_xy is not None else None
            if xy is None:
                self._queue.pop(0)
                c.status = "open"
                self._out(first_id, now, "refused", c.cls, c.noun, c.merge_key, reason="no site")
                continue
            spec = R.RECIPES.get(item["recipe"]) or {}
            row = {"id": "p-%04d" % seq, "ts": _iso(now), "recipe": item["recipe"], "owner": owner,
                   "askers": [k for k in c.askers if k in pips or k in banished], "wish_ids": list(c.wish_ids),
                   "merge_key": c.merge_key, "x": int(xy[0]), "y": int(xy[1]), "age_idx": age,
                   "lit_rule": str(spec.get("lit_rule") or "never"), "status": "rising", "reveal_t0": float(now), "plaque": None}
            ok, why = self._validate(row, at_placement=True)
            if not ok:
                self._queue.pop(0)
                c.status = "open"
                self.log("placed row refused by the validator (%s): %s" % (row["id"], why))
                self._out(first_id, now, "refused", c.cls, c.noun, c.merge_key, reason="validate:%s" % why)
                continue
            rows = list(self.placed())
            rows.append(row)
            w["placed"] = rows
            w["placed_seq"] = seq
            self._dirty()
            self._queue.pop(0)
            c.status = "placed"
            self._last_place_t = now
            self._rising = row["id"]
            self._rising_steps = 0
            self._valid_cache[row["id"]] = (True, why)
            for wid in c.wish_ids:
                self._out(wid, now, "placed", c.cls, c.noun, c.merge_key, item=row["id"])
            self._owner_walks(owner, row, now)
            out.append({"type": "placed", "pip": owner, "item": row["id"], "x": row["x"], "y": row["y"], "recipe": row["recipe"],
                        "askers": list(row["askers"]), "merge_key": c.merge_key, "noun": c.noun})
            return

    def _owner_walks(self, owner: str, row: Dict[str, Any], now: float) -> None:
        """The owner's settler walks to the site with a tool when the person is here (a body moving toward its own
        record, then=idle: not a verb walk, never an away claim)."""
        b = getattr(self.scene, "behaviour", None)
        if b is None:
            return
        e = b.get(owner)
        if e is None or not e.is_present(now) or e.state == "voting":
            return
        try:
            b.carry(owner, now, "tool")
            b.walk_to(owner, (float(row["x"]) + 2.0, float(row["y"]) + 1.0), now, then="idle")
        except Exception:
            pass

    def _rising_tick(self, now: float, out: List[Dict[str, Any]]) -> None:
        rid = self._rising
        if rid is None:
            return
        row = next((r for r in self.placed() if r.get("id") == rid), None)
        if row is None or row.get("status") != "rising":
            self._rising = None
            return
        t0 = float(row.get("reveal_t0") or _epoch(row.get("ts")) or now)
        progress = max(0.0, min(1.0, (now - t0) / RAISE_S))
        step = int(math.floor(max(0.0, now - t0)))
        if step > self._rising_steps and progress < 1.0:
            self._rising_steps = step
            out.append({"type": "placed_step", "item": rid, "progress": round(progress, 3), "x": row["x"], "y": row["y"], "pip": row.get("owner")})
        if progress >= 1.0:
            row["status"] = "stands"
            self._dirty()
            self._rising = None
            self._valid_cache.pop(rid, None)
            try:
                self.scene.land.bump_bake("placed")
            except Exception:
                pass
            self._placed_pin = (rid, now + PLACED_PLATE_PIN_S)
            R = _reg()
            noun = R.noun_for(str(row.get("merge_key") or ""), None) or R.NOUNS.get(str(row.get("recipe")))
            for wid in row.get("wish_ids") or []:
                self._out(wid, now, "raised", None, noun, row.get("merge_key"), item=rid)
            b = getattr(self.scene, "behaviour", None)
            e = b.get(row.get("owner")) if b is not None else None
            if e is not None and e.is_present(now):
                try:
                    b.drop(row["owner"], now)
                    e.joy_until = now + 1.0
                except Exception:
                    pass
            out.append({"type": "placed_ship", "pip": row.get("owner"), "item": rid, "x": row["x"], "y": row["y"],
                        "recipe": row.get("recipe"), "askers": list(row.get("askers") or []), "merge_key": row.get("merge_key"), "noun": noun})

    # ------------------------------------------------------------------ the camera (3.3)
    def camera_filter(self, events: Sequence[Dict[str, Any]], now: float) -> List[Dict[str, Any]]:
        """`placed` / `placed_ship` glide the camera only while <= 2 are here or the owner is here, and never within
        PLACED_EVENT_GAP_S of the last placed EVENT; otherwise the event loses its cell (plank + plate + bell still fire)."""
        out: List[Dict[str, Any]] = []
        for ev in events:
            if ev.get("type") in ("placed", "placed_ship") and ev.get("x") is not None:
                ok = (self._present_count() <= PLACED_EVENT_MAX_HERE) or self._present(str(ev.get("pip") or ""), now)
                gap_ok = self._last_placed_event_t is None or now - self._last_placed_event_t >= PLACED_EVENT_GAP_S
                if ok and gap_ok:
                    self._last_placed_event_t = now
                    out.append(ev)
                else:
                    e2 = dict(ev)
                    e2.pop("x", None)
                    e2.pop("y", None)
                    out.append(e2)
            else:
                out.append(ev)
        return out

    # ------------------------------------------------------------------ what stands: validated rows, parts, structures
    def valid_rows(self, status: Tuple[str, ...] = ("stands",)) -> List[Dict[str, Any]]:
        out = []
        for row in self.placed():
            if row.get("status") not in status:
                continue
            rid = str(row.get("id") or "")
            v = self._valid_cache.get(rid)
            if v is None:
                v = self._validate(row)
                self._valid_cache[rid] = v
                if not v[0]:
                    self.log("placed row %s not drawn: %s" % (rid, v[1]))
            if v[0]:
                out.append(row)
        return out

    def parts_of(self, row: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Resolved parts of one row: {x, y (cells, the ground point), fn, args, owner, id, caster_h, lit_rule}."""
        R = _reg()
        spec = R.RECIPES.get(str(row.get("recipe"))) or {}
        parts = row.get("parts") if isinstance(row.get("parts"), list) else spec.get("parts") or []
        out = []
        owner = str(row.get("owner") or "")
        for part in parts:
            try:
                fn, args, dx, dy = part
            except Exception:
                continue
            args = dict(args or {})
            x = int(round(float(row["x"]) + float(dx)))
            y = int(round(float(row["y"]) + float(dy)))
            if fn == "buildings.garden":
                x, y = x + GARDEN_OFFSET_CELLS[0], y + GARDEN_OFFSET_CELLS[1]
            out.append({"x": x, "y": y, "fn": fn, "args": args, "owner": owner, "id": str(row.get("id")),
                        "caster_h": int(spec.get("caster_h") or 0), "lit_rule": str(row.get("lit_rule") or spec.get("lit_rule") or "never")})
        return out

    def structures(self) -> List[Dict[str, Any]]:
        """Static parts of every standing row for the bake (lanterns are live; banners bake as the fallback frame)."""
        out = []
        for row in self.valid_rows():
            for p in self.parts_of(row):
                if p["fn"] in STRUCTURE_LIVE_FNS:
                    continue
                out.append(p)
        return out

    def structures_sig(self) -> Tuple:
        return tuple((r.get("id"), r.get("status"), r.get("x"), r.get("y")) for r in self.placed() if r.get("status") == "stands")

    def structure_regions(self) -> List[Tuple[int, int, int, int]]:
        return [(p["x"] - 6, p["y"] - 8, p["x"] + 7, p["y"] + 4) for p in self.structures()]

    # ------------------------------------------------------------------ glow (lit lanterns, gated on presence)
    def _lit(self, row: Dict[str, Any], now: float) -> bool:
        rule = str(row.get("lit_rule") or "never")
        if rule == "owner_here":
            return self._present(str(row.get("owner") or ""), now)
        if rule == "anyone_here":
            return self._present_count() > 0
        return False

    def glow_sources(self, now: float) -> List[Tuple[float, float, int, Tuple[int, int, int], float]]:
        out = []
        for row in self.valid_rows():
            if not self._lit(row, now):
                continue
            for p in self.parts_of(row):
                if p["fn"] == "buildings.lantern":
                    r, col, s = LANTERN_GLOW
                    out.append((float(p["x"]), float(p["y"]) - 3.0, r, col, s))
        return out

    # ------------------------------------------------------------------ live sprites (the post, rising rows, lanterns, banners)
    def live_sprites(self, now: float, visible: Callable[[float, float], bool], n0: int, degrade: int = 0) -> List[Tuple[float, int, str, Any]]:
        live: List[Tuple[float, int, str, Any]] = []
        n = n0
        px, py = self.post_xy()
        if visible(px, py):
            live.append((float(py), n, "wish", {"what": "post", "x": px, "y": py})); n += 1
        count = 0
        rows = self.valid_rows(("rising", "stands"))
        for row in rows:
            rising = row.get("status") == "rising"
            for p in self.parts_of(row):
                if not rising and p["fn"] not in STRUCTURE_LIVE_FNS and p["fn"] not in STRUCTURE_WIND_FNS:
                    continue
                if not rising and p["fn"] in STRUCTURE_WIND_FNS and degrade >= BANNER_BAKED_FALLBACK_DEGRADE:
                    continue                                                 # the baked frame stands in
                if not visible(p["x"], p["y"]):
                    continue
                if count >= LIVE_SPRITES_MAX:
                    break
                count += 1
                d = dict(p)
                d["what"] = "part"
                d["rising"] = rising
                d["t0"] = float(row.get("reveal_t0") or _epoch(row.get("ts")) or now) if rising else None
                d["lit"] = self._lit(row, now)
                live.append((float(p["y"]), n, "wish", d)); n += 1
        self.stats_["live_sprites"] = count
        return live

    def _sprite_for(self, p: Dict[str, Any], sun, wind_phase: int, season: float, lit: bool) -> Tuple[np.ndarray, int, int]:
        """(sprite, dx_px, dy_px) at 1x: the pixel offset from the ground cell's pixel origin (x*4, y*4) to the sprite's
        top-left (the bake and the live path share it)."""
        from stream.world.art import props, buildings
        fn, args, owner = p["fn"], p.get("args") or {}, p.get("owner") or ""
        if fn.startswith("buildings."):
            kind = fn.split(".", 1)[1]
            colour = owner if args.get("colour") == "owner" else (args.get("colour") if isinstance(args.get("colour"), str) else (180, 120, 90))
            seed = int(wind_phase) if args.get("phase") == "wind" else None
            spr, (dx, dy) = buildings.render(kind, 1, colour or (180, 120, 90), seed, bool(lit), sun)
            return spr, int(dx), int(dy)
        name = fn.split(".", 1)[1]
        variant = args.get("variant")
        if variant == "owner":
            from stream.world import land as LAND
            variant = LAND.name_hash(owner, "flower") % 5
        variant = int(variant or 0)
        wind = int(wind_phase) if args.get("wind") == "wind" else 0
        if name == "tree":
            spr = props.tree(int(args.get("age", 1)), variant % 4, wind, float(season), sun)
        elif name == "bush":
            spr = props.bush(variant, wind, float(season), sun)
        elif name == "flowers":
            spr = props.flowers(variant % 5, wind)
        elif name == "stone":
            spr = props.stone(variant % 3, sun)
        elif name == "cairn":
            spr = props.cairn(int(args.get("n", 1)), sun)
        else:
            raise ValueError("no such part %r" % fn)
        ax, ay = props.anchor(spr)
        return spr, int(ax) - 2, int(ay) - 3

    def draw(self, rgb: np.ndarray, data: Dict[str, Any], now: float, sun, wind_phase: int, season: float, zoom: float,
             degrade: int, to_screen: Callable[[float, float], Tuple[float, float]], zoomed: Callable[[np.ndarray, float], np.ndarray]) -> None:
        """Blit one live item (the scene's y-sorted loop hands each here)."""
        from stream.world.art import props
        from stream.world import bake as BK
        if data.get("what") == "post":
            spr = props.post(self.papers(), sun)
            sx, sy = to_screen(float(data["x"]), float(data["y"]))
            BK.put(rgb, zoomed(spr, zoom), int(round(sx)), int(round(sy)))
            return
        spr, dx, dy = self._sprite_for(data, sun, wind_phase, season, bool(data.get("lit")))
        if data.get("rising") and data.get("t0") is not None:
            progress = max(0.0, min(1.0, math.floor(max(0.0, now - float(data["t0"]))) / RAISE_S))      # <= 1 Hz steps
            rows = self._reveal_rows(progress, int(spr.shape[0]))
            if rows <= 0:
                return
            key = (id(spr), rows)
            masked = self._reveal_cache.get(key)
            if masked is None:
                masked = spr.copy()
                masked[:spr.shape[0] - rows, :, 3] = 0                        # bottom-up: the top rows stay transparent
                if len(self._reveal_cache) > 256:
                    self._reveal_cache.clear()
                self._reveal_cache[key] = masked
            spr = masked
        sx, sy = to_screen(float(data["x"]), float(data["y"]))
        z = zoomed(spr, zoom)
        BK.blit(rgb, z, int(round(sx - dx * zoom)), int(round(sy - dy * zoom)))

    @staticmethod
    def _reveal_rows(progress: float, sprite_h: int) -> int:
        try:
            from stream.world import keepers as K
            return int(K.Keepers.reveal_rows(progress, sprite_h))
        except Exception:
            return int(round(max(0.0, min(1.0, progress)) * int(sprite_h)))

    # ------------------------------------------------------------------ readouts
    def stats(self) -> Dict[str, Any]:
        return dict(self.stats_, papers=len(self.wish_post()), placed_rows=len(self.placed()), queue=len(self._queue),
                    clusters=len(self._clusters), rising=self._rising, promotions=len(self._promotions))

    def top_clusters(self, now: float, n: int = 3) -> List[Cluster]:
        keys = {r.get("merge_key") for r in self.wish_post()}
        cs = [c for c in self._clusters.values() if c.merge_key in keys and c.askers and c.status != "placed"]
        cs.sort(key=lambda c: (-len(c.askers), c.first_ts))
        return cs[:n]


# ---------------------------------------------------------------------------- bake hook helpers (module functions)
def part_sprite(p: Dict[str, Any], sun, season: float) -> Tuple[np.ndarray, int, int]:
    """For bake.paint_props: (sprite at 4 px/cell, dx_px, dy_px) of one structure row; the bake wind phase is 0."""
    return WishPost._sprite_for(None, p, sun, 0, float(season), False)


def caster_paint(caster: np.ndarray, marks: Optional[Dict[str, Any]]) -> None:
    """For bake.casters_for_marks: structures cast `caster_h` over a cell or two at their foot."""
    for s in (marks or {}).get("structures", ()):
        h = int(s.get("caster_h") or 0)
        if h <= 0:
            continue
        x, y = int(s["x"]), int(s["y"])
        y0, y1 = max(0, y - 1), min(caster.shape[0], y + 1)
        x0, x1 = max(0, x - 1), min(caster.shape[1], x + 2)
        if y1 > y0 and x1 > x0:
            caster[y0:y1, x0:x1] = np.maximum(caster[y0:y1, x0:x1], h)


# ---------------------------------------------------------------------------- panel hook helpers (plates, plank, log)
def _post_of(sc) -> Optional[WishPost]:
    """The scene's WishPost (duck-typed: a hot reload or a `__main__` run may hold another class object)."""
    p = getattr(sc, "wishes", None)
    return p if (p is not None and callable(getattr(p, "wish_post", None)) and callable(getattr(p, "placed", None))) else None


def plate_rows(sc, now: float, shown: Callable[[str], Optional[str]]) -> List[Tuple[str, str, float, float, Optional[str], str]]:
    """(id, kind, x, y, owner, text) rows for panels/world._mark_list: the post's plate (the top three clusters by
    distinct askers, rotating) and one plaque per standing placed row. Every text passes validate_copy."""
    post = _post_of(sc)
    if post is None:
        return []
    R = _reg()
    out: List[Tuple[str, str, float, float, Optional[str], str]] = []
    top = post.top_clusters(now, 3)
    texts: List[str] = []
    for c in top:
        first = next((k for k in c.askers if shown(k)), None)
        if first is None:
            continue
        nm = shown(first)
        n = len(c.askers) - 1
        if c.noun:
            t = _tpl("wished", "PLATE_TEMPLATES", noun=c.noun, name=nm, n=n) if n > 0 else _tpl("wished_one", "PLATE_TEMPLATES", noun=c.noun, name=nm)
        else:
            t = _tpl("wished_nonoun", "PLATE_TEMPLATES", name=nm)
        if t:
            texts.append(t)
    if texts:
        px, py = post.post_xy()
        slot = int(now // 5.0) % len(texts)
        out.append(("post:wished", "post", float(px), float(py) + 3.0, None, texts[slot]))
    for row in post.valid_rows():
        names = [shown(k) for k in (row.get("askers") or [row.get("owner")])]
        names = ["@" + n for n in names if n]
        if not names:
            continue                                                         # a banished owner's plaque is masked
        noun = R.noun_for(str(row.get("merge_key") or ""), None) or R.NOUNS.get(str(row.get("recipe")))
        if not noun:
            continue
        bare = R.bare_noun(noun)
        date = _since_text(row.get("ts"))
        if len(names) > 3:
            t = _tpl("plaque_more", "PLATE_TEMPLATES", bare=bare, names=" ".join(names[:3]), n=len(names) - 3, date=date)
        else:
            t = _tpl("plaque", "PLATE_TEMPLATES", bare=bare, names=" ".join(names), date=date)
        if t:
            out.append(("placed:%s" % row.get("id"), "placed", float(row["x"]), float(row["y"]) + 2.0, str(row.get("owner") or ""), t))
    return out


def plate_sig(sc) -> int:
    post = _post_of(sc)
    if post is None:
        return 0
    return 10007 * len(post.wish_post()) + 31 * len(post.placed()) + sum(1 for r in post.placed() if r.get("status") == "stands")


def plate_pins(sc, now: float, present: int) -> List[str]:
    post = _post_of(sc)
    if post is None:
        return []
    out: List[str] = []
    if now < post._post_pin_until and present <= POST_PIN_MAX_HERE:
        out.append("post:wished")
    if post._placed_pin is not None and now < post._placed_pin[1]:
        out.append("placed:%s" % post._placed_pin[0])
    return out


def reserve_post(placer, sc, cam, size) -> None:
    """The post's screen box is reserved in the panel's placer (culled with the cairn: same visibility test)."""
    post = _post_of(sc)
    if post is None:
        return
    try:
        px, py = post.post_xy()
        pt = cam.sim_to_screen(float(px), float(py), size, margin_px=0.0)
        if pt is None:
            return
        z = float(getattr(cam, "zoom", 1.0) or 1.0)
        w_, h_ = int(24 * z), int(44 * z)
        placer.reserve(int(pt[0]) - w_ // 2, int(pt[1]) - h_, int(pt[0]) + w_ // 2, int(pt[1]) + 4)
    except Exception:
        pass


def plank_line(sc, ev: Dict[str, Any], shown: Callable[[str], Optional[str]]) -> Optional[Tuple[str, int, float, bool]]:
    """(text, prio, dur, tie) for one wish event, or None. The noun is registry.NOUNS[merge_key], never the sentence;
    every number a len(); every string through validate_copy."""
    post = _post_of(sc)
    R = _reg()
    typ = ev.get("type")
    nm = shown(str(ev.get("pip") or ""))
    if typ == "wish":
        if not nm:
            return None
        here = post._present_count() if post is not None else 0
        if here > PLANK_NEW_ONLY_ABOVE and not ev.get("new"):
            return None
        noun = ev.get("noun")
        if ev.get("plus"):
            t = _tpl("plus", "PLANK_TEMPLATES", noun=noun) if noun else None
        elif ev.get("new") or int(ev.get("askers") or 1) <= 1:
            n = int(ev.get("pinned") or (len(post.wish_post()) if post else 1))
            t = _tpl("wish", "PLANK_TEMPLATES", name=nm, noun=noun, n=n) if noun else _tpl("wish_nonoun", "PLANK_TEMPLATES", name=nm, n=n)
        else:
            return None                                                      # the same person again: bumps nothing (2.5)
        return (t, PLANK_PRIO_VERB, PLANK_DUR_S, True) if t else None
    if typ == "placed":
        noun = ev.get("noun") or R.NOUNS.get(str(ev.get("recipe")))
        if not nm or not noun:
            return None
        t = _tpl("placed", "PLANK_TEMPLATES", name=nm, noun=noun)
        return (t, PLANK_PRIO_VERB, PLANK_DUR_S, True) if t else None
    if typ == "placed_ship":
        noun = ev.get("noun") or R.NOUNS.get(str(ev.get("recipe")))
        names = ["@" + n for n in (shown(k) for k in (ev.get("askers") or [ev.get("pip")])) if n]
        if not names or not noun:
            return None
        tail = " ".join(names[:3]) + ((" +%d" % (len(names) - 3)) if len(names) > 3 else "")
        t = "the %s stands · %s" % (R.bare_noun(noun), tail)
        return (t, PLANK_PRIO_VERB, PLANK_DUR_S, True) if validate_copy(t) else None
    if typ == "wish_refused":
        if not nm:
            return None
        t = "@%s · %s" % (nm, R.refuse_copy(str(ev.get("kind") or "destructive"), int(ev.get("rot") or 0)))
        return (t, PLANK_PRIO_VERB, PLANK_DUR_S, False) if validate_copy(t) else None
    if typ == "wish_have":
        if not nm:
            return None
        if ev.get("what") == "camp":
            t = _tpl("have_camp", "PLANK_TEMPLATES", name=nm, days=int(ev.get("days") or 0))
        else:
            t = _tpl("have_path", "PLANK_TEMPLATES", name=nm)
        return (t, PLANK_PRIO_VERB, PLANK_DUR_S, False) if t else None
    return None


_PLANK_LOG_N: Dict[str, int] = {}


def plank_log(run_dir: str, now: float, text: Optional[str], prio: Optional[int], mode: str = "land") -> None:
    """One row per plank text change: {t, text, prio, mode}; rotates past PLANK_LOG_MAX lines (keeps one .1)."""
    if not run_dir:
        return
    path = os.path.join(run_dir, "plank_log.jsonl")
    try:
        n = _PLANK_LOG_N.get(path)
        if n is None:
            n = 0
            try:
                with open(path, "rb") as fh:
                    n = sum(1 for _ in fh)
            except OSError:
                n = 0
        if n >= PLANK_LOG_MAX:
            try:
                os.replace(path, path + ".1")
            except OSError:
                pass
            n = 0
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": _iso(now), "text": text, "prio": prio, "mode": mode}) + "\n")
        _PLANK_LOG_N[path] = n + 1
    except Exception:
        pass


# ---------------------------------------------------------------------------- land hook helpers (banish / unbanish)
def hide_owner(world: Dict[str, Any], key: str) -> Dict[str, Any]:
    """`!banish`: the owner's placed rows go `hidden` (credit is forever: never deleted), their paper leaves the post.
    Returns the audit record restore_owner_rows() takes back."""
    k = (key or "").lower()
    rec: Dict[str, Any] = {"placed": [], "paper": None}
    rows = world.get("placed")
    if isinstance(rows, list):
        for r in rows:
            if r.get("owner") == k and r.get("status") != "hidden":
                rec["placed"].append({"id": r.get("id"), "status": r.get("status")})
                r["status"] = "hidden"
    papers = world.get("wish_post")
    if isinstance(papers, list):
        keep = [p for p in papers if p.get("key") != k]
        gone = [p for p in papers if p.get("key") == k]
        if gone:
            rec["paper"] = gone[-1]
            world["wish_post"] = keep
    return rec


def restore_owner_rows(world: Dict[str, Any], key: str, rec: Optional[Dict[str, Any]]) -> None:
    """`!unbanish`: hidden rows stand again (their prior status), the paper returns."""
    if not isinstance(rec, dict):
        return
    k = (key or "").lower()
    prior = {str(p.get("id")): str(p.get("status") or "stands") for p in (rec.get("placed") or []) if isinstance(p, dict)}
    rows = world.get("placed")
    if isinstance(rows, list):
        for r in rows:
            if r.get("owner") == k and r.get("status") == "hidden" and str(r.get("id")) in prior:
                r["status"] = prior[str(r.get("id"))] if prior[str(r.get("id"))] in ("rising", "stands") else "stands"
    paper = rec.get("paper")
    if isinstance(paper, dict) and paper.get("key") == k:
        papers = world.get("wish_post")
        if not isinstance(papers, list):
            papers = []
        papers = [p for p in papers if p.get("key") != k] + [paper]
        world["wish_post"] = papers


def provenance_rows(world: Dict[str, Any], real_pip: Callable[[str], Optional[Dict]], banished: Optional[Set[str]] = None) -> List[str]:
    """For land.provenance_violations: every placed owner / asker and every paper key resolves to a pip row (a banished
    key is a record too: its rows are hidden, its plaque masked)."""
    out: List[str] = []
    ban = set(banished or ())
    for r in (world.get("placed") or []):
        if not isinstance(r, dict):
            continue
        o = str(r.get("owner") or "").lower()
        if real_pip(o) is None and not (o in ban and r.get("status") == "hidden"):
            out.append("placed %s owner %r has no pip" % (r.get("id"), o))
        for a in r.get("askers") or []:
            a = str(a).lower()
            if real_pip(a) is None and a not in ban:
                out.append("placed %s asker %r has no pip" % (r.get("id"), a))
    for p in (world.get("wish_post") or []):
        if isinstance(p, dict) and real_pip(str(p.get("key") or "")) is None:
            out.append("paper %r has no pip" % (p.get("key"),))
    return out


# ---------------------------------------------------------------------------- self-test (8 row 9) and the clip
def _fixture_keys(n: int) -> List[str]:
    """`a` .. `z`, `aa` .. : fixture keys (a /tmp run dir only; never a run dir the stream reads)."""
    out: List[str] = []
    i = 0
    while len(out) < n:
        s = ""
        k = i
        while True:
            s = chr(ord("a") + k % 26) + s
            k = k // 26 - 1
            if k < 0:
                break
        out.append(s)
        i += 1
    return out


def _guard_tmp(run_dir: str) -> bool:
    rp = os.path.realpath(run_dir)
    if not (rp.startswith("/tmp/") or rp.startswith("/private/tmp/")):
        print("REFUSED: RUN_DIR must be under /tmp (got %r)" % run_dir)
        return False
    if os.environ.get("MODE") != "test":
        print("REFUSED: MODE=test required")
        return False
    return True


class _Harness(object):
    """A booted SteadingScene in a /tmp run dir with real-shaped chat records (chat.jsonl + wishes.jsonl written like
    the listener and RoundEngine do) so the honesty monitor's `here` / `chat_jsonl` rules hold."""

    def __init__(self, run_dir: str, keys: Sequence[str], seed: int = 7, test_pips: int = 0, sleep_after_s: float = 1200.0):
        import shutil
        from stream.scenes import steading as ST
        from stream.state_store import epoch_to_iso
        self.ST, self.iso = ST, epoch_to_iso
        if os.path.isdir(run_dir):
            shutil.rmtree(run_dir)
        os.makedirs(run_dir)
        os.environ["RUN_DIR"] = run_dir
        if test_pips:
            os.environ["KL_TEST_PIPS"] = str(int(test_pips))
        else:
            os.environ.pop("KL_TEST_PIPS", None)
        self.run_dir = run_dir
        self.keys = list(keys)
        self.now0 = _time.time() - 600.0
        self.now = self.now0
        self.sid = "w6-%d" % int(self.now0)
        self.n = 0
        self.raw: List[Dict[str, Any]] = []
        self.clear: List[Dict[str, Any]] = []
        self.logs: List[str] = []
        self.chat_path = os.path.join(run_dir, "chat.jsonl")
        with open(self.chat_path, "w") as fh:
            for k in self.keys:                                        # every fixture key chatted an hour ago (a real record)
                fh.write(json.dumps({"id": "hist-%s" % k, "ts": epoch_to_iso(self.now0 - 3600.0), "username": k, "content": "hello", "type": "message"}) + "\n")
        self.scene = ST.SteadingScene(run_dir=run_dir, seed=seed, log=self.logs.append, sleep_after_s=sleep_after_s)
        self.size = ST.SCREEN
        tb = _time.perf_counter()
        while not (self.scene.booted or self.scene.refused) and _time.perf_counter() - tb < 60.0:
            self.frame()
            _time.sleep(0.01)
        assert self.scene.booted, "scene did not boot: %r %s" % (self.scene.refused, self.logs[-3:])
        from stream.world.honesty import HonestyMonitor
        self.mon = HonestyMonitor(self.scene, enforce=False, log=lambda m: self.logs.append("honesty: " + m))
        self.events: List[Dict[str, Any]] = []

    def ctx(self, votes=()):
        return self.ST._Ctx(now=self.now, frame=self.n, fps=30.0, session={"id": self.sid, "started_ts": self.iso(self.now0), "ending": False},
                            micro={"canvas_seed": 4471}, preset="kick", chat_raw=list(self.raw[-40:]), chat=list(self.clear[-40:]),
                            recent_votes=list(votes), round={"number": 1}, round_remaining=120.0, mod={"hidden_users": []},
                            mod_paused=False, agent={"heartbeat_ts": None}, macro={}, compositor_live={"selftest": True}, selftest=True)

    def frame(self, dt: float = 1.0 / 30.0):
        self.now += dt
        self.n += 1
        img = self.scene.frame(self.ctx(), self.size)
        if self.scene.booted and hasattr(self, "mon"):
            self.mon.check(self.ctx(), self.now)
            for ev in self.scene.events:
                self.events.append(dict(ev, _frame=self.n))
        return img

    def say(self, key: str, text: str, wish: bool = True, head: Optional[str] = "build", kind: str = "plain", dropped: bool = False,
            verb: Optional[str] = None) -> str:
        """A record lands (raw) and clears the hold the same frame (the hold is the bridge's; the scene sees both lists);
        chat.jsonl and wishes.jsonl get the rows the listener / RoundEngine write."""
        mid = "w6-%04d" % (len(self.raw) + 1)
        t = self.now
        with open(self.chat_path, "a") as fh:
            fh.write(json.dumps({"id": mid, "ts": self.iso(t), "username": key, "content": text, "type": "message"}) + "\n")
        raw = {"id": mid, "name": key, "text": text, "t": t, "type": "message", "badges": []}
        if dropped:
            raw["dropped"] = True
        self.raw.append(raw)
        m = {"id": mid, "name": key, "display_name": key, "text": text, "text_clean": text, "t": t, "kind": kind, "first_ever": False,
             "builder_n": None, "dropped": dropped, "history": False, "wish": wish, "head": head, "verb": verb, "hint": None}
        self.clear.append(m)
        if not dropped:
            with open(os.path.join(self.run_dir, "wishes.jsonl"), "a") as fh:
                fh.write(json.dumps({"id": mid, "ts": self.iso(t), "key": key, "by": key, "n": 1, "kind": kind, "text": text, "verb": verb,
                                     "hint": None, "wish": wish, "head": head, "first_ever": False, "session": self.sid, "src": "live"}) + "\n")
        return mid


def _self_test() -> bool:
    run_dir = os.environ.get("RUN_DIR") or "/tmp/lg-w6-wishes"
    if not _guard_tmp(run_dir):
        return False
    ok_all = True

    def check(cond, msg):
        nonlocal ok_all
        print("  [%s] %s" % ("ok" if cond else "FAIL", msg))
        if not cond:
            ok_all = False

    keys = _fixture_keys(40)
    print("[setup] 40 fixture keys %s .. %s in %s" % (keys[0], keys[-1], run_dir))
    H = _Harness(run_dir, keys, seed=7)
    sc = H.scene
    post = _post_of(sc)
    check(post is not None, "the scene attached a WishPost at boot (steading hook)")
    if post is None:
        return False
    check(callable(getattr(sc, "menu_wishes", None)) and callable(getattr(sc, "take_promotions", None)) and callable(getattr(sc, "promotions_pending", None)),
          "scene.menu_wishes / take_promotions / promotions_pending exist for rounds.py")
    px, py = post.post_xy()
    check((px, py) == (int(sc.terrain.site[0]) + 34, int(sc.terrain.site[1]) + 10), "the post stands at MOOT_LAYOUT['post'] = (34, 10): %r" % ((px, py),))
    # every fixture key stands on the land (a real past chatter) and is made HERE by a record
    for k in keys:
        H.say(k, "hello again", wish=False, head=None)
    for _ in range(3):
        H.frame()
    check(sc.present_count() == 40, "40 fixture people here (present_count %d)" % sc.present_count())

    # ---- A. 40 identical wishes -> one cluster, 40 askers, 40 papers, 5 drawn, the plate reads `wished: a castle · @a +39`
    print("[A] 40 x `build a castle` from 40 keys")
    pinned_frames: List[Tuple[int, int]] = []
    for k in keys:
        H.say(k, "build a castle", head="build")
        H.frame()
        for ev in sc.events:
            if ev.get("type") == "wish":
                pinned_frames.append((len(post.wish_post()), int(ev.get("pinned") or 0)))
    c = post.clusters().get("keep")
    check(c is not None and len(c.askers) == 40, "one cluster `keep` with 40 askers (%s)" % (len(c.askers) if c else None))
    check(len(post.wish_post()) == 40, "40 wish_post rows (%d)" % len(post.wish_post()))
    check(post.papers() == 5, "the post draws 5 papers (%d)" % post.papers())
    check(len(pinned_frames) == 40 and all(n >= p and n >= 1 for n, p in pinned_frames), "the `wish` event (the plank's `pinned`) fired 40 times, each with the row already in wish_post")
    shown = lambda k: k if k in sc.world.pips else None    # noqa: E731 (the panel's _shown: a pip row's display name)
    rows = plate_rows(sc, H.now, shown)
    texts = [r[5] for r in rows if r[1] == "post"]
    check(texts == ["wished: a castle · @a +39"], "plate reads %r" % (texts,))
    check(plate_pins(sc, H.now, sc.present_count()) == [], "the post plate pins only while <= 10 are here (40 here: %r)" % plate_pins(sc, H.now, sc.present_count()))
    check(plate_pins(sc, H.now, 3) == ["post:wished"], "... and pins for 10 s with 3 here")
    # the plank line for the first and a later asker
    ev_first = {"type": "wish", "pip": "a", "noun": "a castle", "new": True, "plus": False, "pinned": 1, "askers": 1}
    ev_plus = {"type": "wish", "pip": "b", "noun": "a castle", "new": False, "plus": True, "pinned": 2, "askers": 2}
    l1, l2 = plank_line(sc, ev_first, shown), plank_line(sc, ev_plus, shown)
    check(l1 is not None and l1[0] == "@a's wish is pinned · a castle · 1 pinned" and l1[1] == PLANK_PRIO_VERB, "plank pinned line %r" % (l1,))
    check(l2 is not None and l2[0] == "+1 for a castle", "plank plus line %r" % (l2,))
    # a project accumulates askers only (W4's plate clause reads project_asks)
    check(post.project_asks().get("keep") == keys, "project_asks()['keep'] lists the 40 askers by first ask")
    check(not post._queue, "a project never joins the place queue (%d queued)" % len(post._queue))

    # ---- B. a blocklisted record never reaches classify; a silent class pins nothing
    print("[B] dropped and silent records")
    n_seen = len(post._seen)
    n_papers = len(post.wish_post())
    H.say("a", "build a dog house", dropped=True)
    H.frame()
    check(len(post._seen) == n_seen, "a dropped (blocklisted) record never reached classify")
    H.say("b", "good night everyone", head=None)
    H.frame()
    check(len(post.wish_post()) == n_papers, "a `silent` class pins nothing (%d papers)" % len(post.wish_post()))
    outs = [json.loads(l) for l in open(os.path.join(run_dir, "wishes.out.jsonl"))]
    check(any(o["stage"] == "classified" and o["class"] == "silent" for o in outs), "the silent row is in wishes.out.jsonl as classified")

    # ---- C. refusals: one plank line per person per 30 s, never echoing words; have_it answers from records
    print("[C] refusals and have_it")
    H.say("c", "can we have a dog", head="can")
    H.frame()
    ref = [e for e in sc.events if e.get("type") == "wish_refused"]
    H.say("c", "we want a cat too", head="want")
    H.frame()
    ref2 = [e for e in H.events if e.get("type") == "wish_refused" and e.get("pip") == "c"]
    check(len(ref) == 1 and len(ref2) == 1, "one refusal line for c inside REFUSE_COOLDOWN_S (%d, %d)" % (len(ref), len(ref2)))
    line = plank_line(sc, ref[0], shown) if ref else None
    check(line is not None and line[0].startswith("@c · no dogs here · try: ") and "dog house" not in line[0] and "cat" not in line[0], "refusal copy %r" % (line,))
    check(len(post.wish_post()) == n_papers, "a refusal pins no paper")
    H.say("d", "build a hut here", head="build")
    H.frame()
    have = [e for e in H.events if e.get("type") == "wish_have" and e.get("pip") == "d"]
    check(len(have) == 1 and have[0].get("what") == "camp", "have_it answers from records (%r)" % (have[-1] if have else None,))
    hl = plank_line(sc, have[0], shown) if have else None
    check(hl is not None and hl[0].startswith("@d · your tent grows as you stay · "), "have_it plank %r" % (hl,))

    # ---- D. menu wishes -> menu_wishes(); mechanic -> take_promotions() in the rounds shape
    print("[D] menu_wishes / take_promotions shapes")
    for k in ("e", "f", "g"):
        H.say(k, "give us fog please", head="give")
        H.frame()
    H.say("e", "more fog", head="more")
    H.frame()
    mw = sc.menu_wishes()
    check(mw == {("weather", "fog"): 3}, "menu_wishes() == {('weather', 'fog'): 3} (a repeat by e counts once): %r" % (mw,))
    H.say("h", "dig a hole", head="dig")
    H.frame()
    H.say("i", "dig a hole please", head="dig")
    H.frame()
    H.say("j", "build a pixel art bot", head="build", kind="idea")
    H.frame()
    check(sc.promotions_pending() is True, "promotions_pending() before the drain")
    promos = sc.take_promotions()
    check(sc.promotions_pending() is False and sc.take_promotions() == [], "take_promotions() drains")
    dig = next((p for p in promos if p.get("merge_key") == "dig"), None)
    idea = next((p for p in promos if p.get("merge_key") != "dig"), None)
    check(dig is not None and set(dig) == {"text", "by", "plus_by", "merge_key", "wish_ids"} and dig["by"] == "h" and dig["plus_by"] == ["i"]
          and len(dig["wish_ids"]) == 2 and dig["text"] == "dig", "mechanic promotion shape %r" % (dig,))
    check(idea is not None and idea["text"] == "build a pixel art bot" and idea["by"] == "j", "idea promotion carries the idea text %r" % (idea,))
    try:
        from stream import compositor as C
        check(not C.Compositor.banned_copy_hits([p["text"] for p in promos if p["merge_key"] == "dig"]), "the mechanic promotion text passes banned_copy_hits")
    except Exception as e:
        print("    (compositor import skipped: %r)" % (e,))

    # ---- E. the place queue: first item never refused, the second in one session is; pacing 90 s; the reveal
    print("[E] place queue, caps, pacing, reveal")
    H.say("k", "a lantern", head=None)
    H.frame()
    placed_ev = [e for e in H.events if e.get("type") == "placed"]
    check(len(placed_ev) == 1 and placed_ev[0]["pip"] == "k" and placed_ev[0]["recipe"] == "lantern", "k's first item placed at once (%r)" % (placed_ev[-1:],))
    row = next((r for r in post.placed() if r.get("owner") == "k"), None)
    check(row is not None and row["status"] == "rising" and row["askers"] == ["k"] and row["wish_ids"] and row["id"] == "p-0001" and row["age_idx"] == 0
          and row["lit_rule"] == "owner_here" and set(row) >= {"id", "ts", "recipe", "owner", "askers", "wish_ids", "merge_key", "x", "y", "age_idx", "lit_rule", "status", "reveal_t0", "plaque"},
          "placed row shape (6.1) %r" % ({k_: row[k_] for k_ in ("id", "status", "recipe", "x", "y", "lit_rule")} if row else None,))
    ek = sc.behaviour.get("k")
    check(ek is not None and ek.carry == "tool" and ek.state == "walking", "k's settler walks to the site with a tool (carry=%r state=%r)" % (getattr(ek, "carry", None), getattr(ek, "state", None)))
    pl = plank_line(sc, placed_ev[0], shown) if placed_ev else None
    check(pl is not None and pl[0] == "@k's a lantern rises", "placed plank %r" % (pl,))
    H.say("k", "a banner", head=None)
    H.frame()
    H.say("l", "a garden", head=None)
    H.frame()
    steps = 0
    frames_step: List[int] = []
    t_start = H.now
    while H.now - t_start < RAISE_S + 2.0:
        H.frame()
        for ev in sc.events:
            if ev.get("type") == "placed_step":
                steps += 1
                frames_step.append(H.n)
    gaps = [b - a for a, b in zip(frames_step, frames_step[1:])]
    check(steps >= 15 and all(g >= 29 for g in gaps), "placed_step at <= 1 Hz over RAISE_S (%d steps, min gap %s frames)" % (steps, min(gaps) if gaps else None))
    row = next((r for r in post.placed() if r.get("owner") == "k"), None)
    ship = [e for e in H.events if e.get("type") == "placed_ship"]
    check(row is not None and row["status"] == "stands" and len(ship) == 1, "the lantern stands after RAISE_S (status %r, ships %d)" % (row and row["status"], len(ship)))
    sl = plank_line(sc, ship[0], shown) if ship else None
    check(sl is not None and sl[0] == "the lantern stands · @k", "ship plank %r" % (sl,))
    check("placed:p-0001" in plate_pins(sc, H.now, 1), "the placed plate is pinned after the ship")
    pr = [r for r in plate_rows(sc, H.now, shown) if r[1] == "placed"]
    check(len(pr) == 1 and pr[0][5].startswith("lantern · @k · since "), "plaque plate %r" % (pr[0][5] if pr else None,))
    outs = [json.loads(l) for l in open(os.path.join(run_dir, "wishes.out.jsonl"))]
    refused = [o for o in outs if o["stage"] == "refused" and o["merge_key"] == "banner"]
    check(bool(refused) and refused[0]["reason"] == "cap:session", "k's second item in one session refused by the cap (%r)" % (refused[:1],))
    check(not any(r.get("owner") == "l" for r in post.placed()) and any(q["merge_key"] == "garden" for q in post._queue), "l's garden waits for the 90 s pacing")
    while H.now - t_start < PLACE_EVERY_S + 1.0:
        H.frame(0.5)
    check(any(r.get("owner") == "l" and r.get("recipe") == "garden" for r in post.placed()), "l's garden placed one raise after 90 s")
    lt = [e for e in H.events if e.get("type") == "placed"]
    check(len(lt) == 2 and lt[1]["_frame"] > lt[0]["_frame"] and (H.now - t_start) >= PLACE_EVERY_S, "pacing: two raises, 90 s apart")
    check(all(post._validate(r)[0] for r in post.placed()), "every placed row passes honesty.validate_registry")
    structs = post.structures()
    check(not any(s["fn"] == "buildings.lantern" for s in structs), "lanterns are live sprites, never baked (%d structures)" % len(structs))
    # regression: a trail worn across the standing lantern LATER (k walks across the site) never revokes it: the row stays
    # in valid_rows / live sprites, the monitor's `placed` rule stays silent, provenance 0; a NEW row on that cell is refused
    lrow = next(r for r in post.placed() if r.get("recipe") == "lantern")
    lx, ly = int(lrow["x"]), int(lrow["y"])
    v_before = H.mon.summary()["violations"]
    sc.behaviour.walk_to("k", (float(lx) + 3.0, float(ly) + 1.0), H.now)          # a here settler walks across the site
    for _ in range(60):
        H.frame()
    for dy_ in (-1, 0, 1):
        sc.land.wear[ly + dy_, max(0, lx - 2):lx + 3] = 255                          # ... and the cell is a worn trail now
    check(sc.land.is_trail(lx, ly), "the lantern's cell is a trail after the walk (wear %d)" % int(sc.land.wear_at(lx, ly)))
    post._valid_cache.clear()
    H.mon._placed_ok.discard(lrow["id"])
    for _ in range(3):
        H.frame()
    live_ids = [d[3].get("id") for d in post.live_sprites(H.now, lambda x, y: True, 0)]
    ok_end, why_end = post._validate(lrow)
    ok_new, why_new = post._validate(lrow, at_placement=True)
    check(lrow in post.valid_rows() and lrow["id"] in live_ids and lrow["status"] == "stands",
          "the standing lantern stays valid and drawn with a trail across it (%r)" % (why_end,))
    check(ok_end and not ok_new and "trail" in why_new, "enduring check ok, a NEW placement on that cell refused: %r" % (why_new,))
    check(H.mon.summary()["violations"] == v_before and not sc.land.provenance_violations(), "honesty 0 through the walk-across (%d before, %d after), provenance 0" % (v_before, H.mon.summary()["violations"]))
    ek = sc.behaviour.get("k")
    glows = post.glow_sources(H.now)
    check(len(glows) == 1 and ek.is_present(H.now), "the lit lantern glows while k is here (%d sources)" % len(glows))
    ek.last_active_t = H.now - sc.sleep_after_s - 5.0
    H.frame()
    check(post.glow_sources(H.now) == [], "... and not once k is away")
    ek.last_active_t = H.now
    H.frame()

    # ---- F. camera gate, live sprite cap, wish_class re-class, banish / unbanish provenance, plank_log, copy
    print("[F] camera gate, re-class, banish, plank_log")
    ev_p = {"type": "placed", "pip": "zz-nobody", "x": 1, "y": 1, "item": "p-x"}
    post._last_placed_event_t = None
    f1 = post.camera_filter([ev_p], H.now)
    check("x" not in f1[0], "with 40 here and the owner away a `placed` is no camera EVENT")
    post._last_placed_event_t = None
    f2 = post.camera_filter([dict(ev_p, pip="k")], H.now)
    check("x" in f2[0], "... but with the owner here it glides")
    f3 = post.camera_filter([dict(ev_p, pip="k")], H.now + 10.0)
    check("x" not in f3[0], "... and never within PLACED_EVENT_GAP_S of the last")
    visible = lambda x, y: True   # noqa: E731
    live = post.live_sprites(H.now, visible, 0, degrade=0)
    check(len(live) >= 2 and live[0][3]["what"] == "post" and any(d[3].get("fn") == "buildings.lantern" for d in live), "live sprites: the post + the lit lantern (%d)" % len(live))
    check(post.stats()["live_sprites"] <= LIVE_SPRITES_MAX, "live registry sprites <= 24 in view")
    # a probe re-class: an unknown -> recipe pins the noun late; -> silent un-pins without a plank line
    mid_u = H.say("m", "bigger mountains please", head="bigger")
    H.frame()
    check(any(p["key"] == "m" and p["class"] == "unknown" for p in post.wish_post()), "an unknown head pins a paper without a noun")
    with open(os.path.join(run_dir, "wish_class.jsonl"), "a") as fh:
        fh.write(json.dumps({"ts": H.iso(H.now), "id": mid_u, "class": "silent", "status": "closed", "reason": "test", "by_agent": "probe"}) + "\n")
        fh.write(json.dumps({"ts": H.iso(H.now), "id": "not-in-the-ledger", "class": "recipe:lantern", "by_agent": "probe"}) + "\n")
    n_ev = len(H.events)
    for _ in range(3):
        H.frame(1.0)
    check(not any(p["key"] == "m" for p in post.wish_post()), "a `silent` re-class removes the paper")
    check(not any(e.get("type") == "wish" for e in H.events[n_ev:]), "... with no plank line, and an id not in the ledger is ignored")
    # banish k: the lantern hides, the paper leaves, provenance stays 0; unbanish restores
    sc.command("banish", "atleastonce", target="k", now=H.now)
    H.frame()
    row = next((r for r in post.placed() if r.get("owner") == "k"), None)
    pv = sc.land.provenance_violations()
    check(row is not None and row["status"] == "hidden" and pv == [], "banish: k's lantern hidden, provenance %r" % (pv,))
    check(not any(p["key"] == "k" for p in post.wish_post()) and post.glow_sources(H.now) == [] and not any(r[4] == "k" for r in plate_rows(sc, H.now, shown)),
          "banish: no paper, no glow, plaque masked")
    rep = H.mon.check(H.ctx(), H.now)
    check("placed" not in rep.rules() and "marks" not in rep.rules(), "honesty clean after banish (%r)" % (rep.violations,))
    sc.command("unbanish", "atleastonce", target="k", now=H.now)
    H.frame()
    row = next((r for r in post.placed() if r.get("owner") == "k"), None)
    pv = sc.land.provenance_violations()
    check(row is not None and row["status"] == "stands" and pv == [], "unbanish: the lantern stands again, provenance %r" % (pv,))
    # plank_log rows and the copy gate on every composed string
    plank_log(run_dir, H.now, "@k's wish is pinned · a lantern · 1 pinned", PLANK_PRIO_VERB)
    pl_rows = [json.loads(l) for l in open(os.path.join(run_dir, "plank_log.jsonl"))]
    check(bool(pl_rows) and set(pl_rows[-1]) == {"t", "text", "prio", "mode"}, "plank_log.jsonl row shape %r" % (pl_rows[-1:],))
    strings = [r[5] for r in plate_rows(sc, H.now, shown)] + [x[0] for x in (l1, l2, line, hl, pl, sl) if x]
    try:
        from stream import compositor as C
        hits = C.Compositor.banned_copy_hits(strings)
        check(not hits, "%d composed strings pass banned_copy_hits (%r)" % (len(strings), hits[:3]))
    except Exception as e:
        print("    (compositor import skipped: %r)" % (e,))
    check(validate_copy("@k's wish is pinned · a lantern · 1 pinned") and not validate_copy("the keepers build it next"), "validate_copy: template ok, banned words refused")
    s = H.mon.summary()
    check(s["violations"] == 0, "honesty monitor: 0 violations over %d frames (%r)" % (s["frames"], s["by_rule"]))
    check(sc.stats()["honesty_violations"] == 0 and sc.errors == 0, "scene: 0 honesty violations, 0 frame errors")
    # a restart keeps the clusters and the queue (records, never a re-pin)
    post2 = WishPost(sc)
    rep2 = post2.boot(H.now)
    check(rep2["clusters"] >= 2 and "keep" in post2.clusters() and len(post2.clusters()["keep"].askers) == 40 and rep2["queued"] == 0,
          "a fresh WishPost rebuilds the clusters from the ledger (%r) with nothing re-queued" % (rep2,))
    sc.wishes = post
    print("[stats] %r" % (post.stats(),))
    print("wishes --self-test: %s" % ("PASS" if ok_all else "FAIL"))
    return ok_all


def _clip() -> bool:
    """A lantern placed and revealed with KL_TEST_PIPS: report/ PNGs at 720p and a 320x180 grid; provenance 0 after
    banish and unbanish. Frames go to report/ only (kept); nothing else is written outside the run dir."""
    run_dir = os.environ.get("RUN_DIR") or "/tmp/lg-w6-clip"
    if not _guard_tmp(run_dir):
        return False
    from PIL import Image
    keys = ["kai", "jo"]
    H = _Harness(run_dir, keys, seed=7, test_pips=6)
    sc = H.scene
    post = _post_of(sc)
    ok = post is not None
    rep_dir = os.path.join(run_dir, "report")
    os.makedirs(rep_dir, exist_ok=True)
    for k in keys:
        H.say(k, "hello", wish=False, head=None)
    for _ in range(45):
        H.frame()
    H.say("kai", "a lantern", head=None)
    H.say("jo", "a lantern too", head=None)
    frames: List[Tuple[float, Image.Image]] = []
    t0 = H.now
    steps = 0
    i = 0
    while H.now - t0 < RAISE_S + 3.0:
        img = H.frame()
        i += 1
        for ev in sc.events:
            if ev.get("type") == "placed_step":
                steps += 1
        if i % 90 == 1:
            frames.append((H.now - t0, img.copy()))
    row = next((r for r in post.placed() if r.get("owner") == "kai"), None)
    ok = ok and row is not None and row["status"] == "stands" and steps >= 15 and row["askers"] == ["kai", "jo"]
    print("[clip] placed row %r steps %d present %d test_pips %d" % ({k: row[k] for k in ("id", "status", "x", "y", "askers")} if row else None, steps, sc.present_count(), sc.test_pips))
    site = sc.sim_to_screen(row["x"], row["y"]) if row else None
    tiles = []
    for t, img in frames[:8]:
        img.save(os.path.join(rep_dir, "reveal_720p_%02ds.png" % int(t)))
        tiles.append(img.resize((320, 180), Image.Resampling.BOX))
    if tiles:
        cols = 4
        rows_ = (len(tiles) + cols - 1) // cols
        grid = Image.new("RGBA", (320 * cols, 180 * rows_), (0, 0, 0, 255))
        for k_, tl in enumerate(tiles):
            grid.paste(tl, ((k_ % cols) * 320, (k_ // cols) * 180))
        grid.save(os.path.join(rep_dir, "reveal_grid_320x180.png"))
    if site is not None and frames:
        sx, sy = int(site[0]), int(site[1])
        box = (max(0, sx - 80), max(0, sy - 90), min(1280, sx + 80), min(720, sy + 30))
        strip = Image.new("RGBA", ((box[2] - box[0]) * len(frames[:8]), box[3] - box[1]))
        for k_, (t, img) in enumerate(frames[:8]):
            strip.paste(img.crop(box), (k_ * (box[2] - box[0]), 0))
        strip = strip.resize((strip.size[0] * 2, strip.size[1] * 2), Image.Resampling.NEAREST)
        strip.save(os.path.join(rep_dir, "reveal_site_strip_2x.png"))
    pv0 = sc.land.provenance_violations()
    sc.command("banish", "atleastonce", target="kai", now=H.now)
    H.frame()
    pv1 = sc.land.provenance_violations()
    hidden = row is not None and row["status"] == "hidden"
    sc.command("unbanish", "atleastonce", target="kai", now=H.now)
    H.frame()
    pv2 = sc.land.provenance_violations()
    stands = row is not None and row["status"] == "stands"
    s = H.mon.summary()
    print("[clip] provenance before %d / banished %d (hidden=%s) / unbanished %d (stands=%s); honesty violations %d over %d frames %r; scene honesty %d errors %d" % (
        len(pv0), len(pv1), hidden, len(pv2), stands, s["violations"], s["frames"], s["by_rule"], sc.stats()["honesty_violations"], sc.errors))
    ok = ok and not pv0 and not pv1 and not pv2 and hidden and stands and s["violations"] == 0 and sc.errors == 0
    H.frame()
    H.frame().save(os.path.join(rep_dir, "final_720p.png"))
    print("[clip] report/: %s" % ", ".join(sorted(os.listdir(rep_dir))))
    print("wishes --clip: %s" % ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":     # pragma: no cover
    from stream.world import wishes as _SELF          # run the tests against the module object the scene imports
    if "--self-test" in sys.argv:
        sys.exit(0 if _SELF._self_test() else 1)
    if "--clip" in sys.argv:
        sys.exit(0 if _SELF._clip() else 1)
    print(__doc__)
