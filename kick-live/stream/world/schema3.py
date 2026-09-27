"""stream/world/schema3.py - world.json schema 3 (AGES 5, IDLEWORLD 6.1-6.3, 2.1 boot replay): the W3 slice's logic.

    from stream.world import schema3 as S3
    new, report = S3.migrate_v3_doc(old_doc, chat_path, now)        # a schema-2 document -> a NEW schema-3 one (old untouched)
    ok, problems, gates = S3.verify_v3(old_doc, new, chat_path, now) # every 6.3 gate as (name, shown value, passed)
    S3.print_gates(gates)                                            # one line per gate, the owner reads it before a live run
    S3.adopt_v3(doc)                                                 # load-time defaults for a schema-3 document (state._adopt)
    S3.recompute_wishes(run_dir, chat_path, cursor, builders, log)   # chat.jsonl -> $RUN_DIR/wishes.jsonl replay rows, by id
    S3.wish_eligible(record)                                         # -> "plain" | "idea" | "theme" | "ask" | None

Schema 3 adds, world block: `age` (int, earned, monotonic; written at gate time by the age sequencer, never here),
`age_built` (int <= age), `age_history[]` ({idx, name, ts, at: {people, stones, days}, raised_by: [keys], stones_placed,
wished_by: {}}), `days_on_air[]` (ISO LOCAL dates with >= 1 moderated record), `age_build` (None | {...}), `wish_post[]`,
`placed[]`, `placed_seq` (int); `cursor.wishes_offset`. Pip: `days_seen[]` (distinct local chat dates), `last_told`
({ts, age, camp_tier, tree_stage, flower_stage, placed, people, stones}), `camp.nights[] -> camp.sessions[]` (values
copied; `nights` kept readable one release), `camp.tiers[]` ({tier, ts} history). `sleep_t` / `nights_streak` are dropped.

Rules: identity fields are copied byte-for-byte (the 5.4 guard, extended by the 6.3 gates); every number a `len()`;
nothing here draws or reads the run dir except the two files it is handed; the wish text lands ONLY in the ledger file
(chat is data: never in a path, a shell or an instruction). Hot-reloadable: every import of a sibling module is lazy,
nothing imports behaviour / honesty. Python 3.9.
"""
from __future__ import annotations

import copy
import json
import os
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

SCHEMA3 = 3
LAST_TOLD_KEYS = ("ts", "age", "camp_tier", "tree_stage", "flower_stage", "placed", "people", "stones")
WISHES_FILE = "wishes.jsonl"
WISHES_ARCHIVE_DIR = "wishes.archive"
CAP_LEDGER_TEXT, CAP_IDEA_TEXT, CAP_ASK_TEXT = 120, 60, 140       # the ledger caps (rounds.CAP_LEDGER_TEXT, bridge CAP_IDEA / CAP_ASK)
MAX_SCAN_BYTES = 64 * 1024 * 1024
WORLD_KEYS_V3 = ("age", "age_built", "age_history", "days_on_air", "age_build", "wish_post", "placed", "placed_seq")
# the bridge's own tables, mirrored for a bare harness (chat_bridge is asked first when it imports)
_VOTE_RE = re.compile(r"^!?([abc])$", re.IGNORECASE)
_CMD_RE = re.compile(r"^!(\w+)\s*(.*)$", re.DOTALL)
_MOD_CMDS = frozenset(("hide", "unhide", "pause", "resume", "kill", "unkill", "clear", "banish", "unbanish", "rename"))
_OPS_CMDS = frozenset(("stats", "help"))                                    # bot commands: an ops token, never a wish
_OPS_PHRASES = frozenset(("pause bot", "bot pause", "resume bot", "bot resume", "unpause bot"))
_STATE_MAP = {"asleep": "idle", "curled": "idle", "awake": "idle", "burrowed": "hidden"}
_DROPPED_PIP_KEYS = ("sleep_t", "nights_streak")


# ---------------------------------------------------------------------------- lazy siblings
def _ss():
    from stream import state_store as SS
    return SS


def _land():
    from stream.world import land as LAND
    return LAND


def _iso(t: Optional[float]) -> Optional[str]:
    return _ss().epoch_to_iso(float(t), ms=True) if t else None


def _epoch(s: Any) -> Optional[float]:
    return _ss().iso_to_epoch(s)


def _ident(v: Any) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def world_v3_defaults() -> Dict[str, Any]:
    return {"age": 0, "age_built": 0, "age_history": [], "days_on_air": [], "age_build": None,
            "wish_post": [], "placed": [], "placed_seq": 0}


def pip_v3_defaults() -> Dict[str, Any]:
    return {"days_seen": [], "last_told": None}


def adopt_v3(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Load-time defaults for a parsed schema-3 document (state._adopt calls it): every 6.1 key present with its empty
    value, `camp.sessions` mirrored from `nights` when a row predates the rename, `camp.tiers` a list. Never rewrites a
    value that is there."""
    w = doc.setdefault("world", {})
    for k, v in world_v3_defaults().items():
        w.setdefault(k, copy.deepcopy(v))
    cur = doc.setdefault("cursor", {})
    cur.setdefault("wishes_offset", 0)
    for p in (doc.get("pips") or {}).values():
        if not isinstance(p, dict):
            continue
        for k, v in pip_v3_defaults().items():
            p.setdefault(k, copy.deepcopy(v))
        camp = p.get("camp")
        if isinstance(camp, dict):
            if camp.get("sessions") is None:
                camp["sessions"] = list(camp.get("nights") or [])
            if not isinstance(camp.get("tiers"), list):
                camp["tiers"] = []
    return doc


# ---------------------------------------------------------------------------- chat.jsonl scans (dates)
def chat_scan(chat_path: Optional[str], max_bytes: int = MAX_SCAN_BYTES) -> Dict[str, Any]:
    """Distinct LOCAL dates with a moderated record, overall and per chatter key, plus each key's first record epoch.
    Both record shapes, de-duped on id, webhook `type != message` and test rows ignored. Missing file -> empty sets."""
    out: Dict[str, Any] = {"dates": [], "by_key": {}, "first_t": {}, "records": 0, "readable": False}
    if not chat_path:
        return out
    try:
        size = os.path.getsize(chat_path)
        with open(chat_path, "rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            data = fh.read()
    except OSError:
        return out
    out["readable"] = True
    SS = _ss()
    LAND = _land()
    ids: Set[str] = set()
    dates: Set[str] = set()
    by_key: Dict[str, Set[str]] = {}
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            m = SS.normalise_chat(json.loads(line.decode("utf-8", "replace")))
        except Exception:
            continue
        if m is None or m["id"] in ids or not m.get("name") or m.get("t") is None:
            continue
        ids.add(m["id"])
        if m.get("type") not in (None, "message"):
            continue
        d = LAND.local_date(float(m["t"]))
        if d is None:
            continue
        key = m["name"].lower()
        dates.add(d)
        by_key.setdefault(key, set()).add(d)
        ft = out["first_t"].get(key)
        if ft is None or float(m["t"]) < ft:
            out["first_t"][key] = float(m["t"])
        out["records"] += 1
    out["dates"] = sorted(dates)
    out["by_key"] = {k: sorted(v) for k, v in by_key.items()}
    return out


# ---------------------------------------------------------------------------- the Land over a bare document
class _DocView(object):
    """The slice of WorldState that land.Land reads: `data`, `iso`, `epoch`, `log`, `dirty`, `hatched_ever`. Lets the
    verifier run `provenance_violations()` over a migrated document that no WorldState has adopted yet."""

    def __init__(self, data: Dict[str, Any], log: Optional[Callable[[str], None]] = None):
        self.data = data
        self.log = log or (lambda m: None)
        self.dirty = False
        self.session_id = None

    @staticmethod
    def iso(t: Optional[float]) -> Optional[str]:
        return _iso(t)

    @staticmethod
    def epoch(s: Any) -> Optional[float]:
        return _epoch(s)

    @property
    def hatched_ever(self) -> int:
        return hatched_count(self.data)


def hatched_count(doc: Dict[str, Any]) -> int:
    """PEOPLE = len(real rows past the hatch); banished rows live outside `pips` already."""
    return sum(1 for p in (doc.get("pips") or {}).values()
               if isinstance(p, dict) and not p.get("_test") and p.get("state") not in ("seed", "hatching"))


def _tree_stage_of(key: str, world: Dict[str, Any], now: float) -> int:
    LAND = _land()
    best = 0
    for m in world.get("marks") or []:
        if m.get("type") == "tree" and str(m.get("owner") or "").lower() == key:
            t0 = _epoch(m.get("ts"))
            idx, _ = LAND.stage_by_days(LAND.TREE_STAGES, None if t0 is None else now - t0)
            best = max(best, idx)
    return best


def seed_last_told(key: str, p: Dict[str, Any], world: Dict[str, Any], people: int, stones: int, now: float) -> Dict[str, Any]:
    """6.3: `last_told` for a migrated pip so the first return after the deploy says what rose: {ts: last_seen_ts, age: 0,
    camp_tier: stored, tree_stage: current, flower_stage: 0, placed: 0, people, stones}."""
    camp = p.get("camp") if isinstance(p.get("camp"), dict) else {}
    return {"ts": p.get("last_seen_ts") or p.get("first_seen_ts") or _iso(now), "age": 0,
            "camp_tier": int(camp.get("tier") or 0) if camp else 0, "tree_stage": _tree_stage_of(key, world, now),
            "flower_stage": 0, "placed": 0, "people": int(people), "stones": int(stones)}


# ---------------------------------------------------------------------------- 2 -> 3, pure
def migrate_v3_doc(old: Dict[str, Any], chat_path: Optional[str] = None, now: Optional[float] = None,
                   log: Optional[Callable[[str], None]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A NEW schema-3 document from a schema-2 one; `old` is never touched (deep-copied first). Identity copied, never
    rebuilt. `days_seen` / `days_on_air` from the chat copy's LOCAL dates; camps: `nights -> sessions` (copied, `nights`
    kept), `tiers` seeded from the stored tier, then re-read through `camp_tier_for(p, age)` (never lower; the Camp's floor
    lifts a hollow to a tent); `age = age_gate(people, stones, days)`, `age_built 0`, `age_history` rows to the earned rung;
    `wish_post []`, `placed []`, `placed_seq 0`, `cursor.wishes_offset 0`; `last_told` on every pip. (new_doc, report)."""
    import time as _time
    log = log or (lambda m: None)
    LAND = _land()
    now = float(now if now is not None else _time.time())
    new = copy.deepcopy(old)
    report: Dict[str, Any] = {"from_schema": int(new.get("schema") or 1), "to_schema": SCHEMA3, "pips": 0, "camps": 0,
                              "camps_lifted": 0, "chat": chat_path}
    w = new.setdefault("world", {})
    for k, v in world_v3_defaults().items():
        w.setdefault(k, copy.deepcopy(v))
    cur = new.setdefault("cursor", {})
    cur.setdefault("wishes_offset", 0)
    scan = chat_scan(chat_path)
    report["chat_readable"] = scan["readable"]
    days_on_air = sorted(set(w.get("days_on_air") or []) | set(scan["dates"]))
    w["days_on_air"] = days_on_air
    pips = new.get("pips") or {}
    stones = len(w.get("stones") or [])
    people = hatched_count(new)
    age = LAND.age_gate(people, stones, len(days_on_air))
    for key, p in sorted(pips.items()):
        if not isinstance(p, dict):
            continue
        report["pips"] += 1
        st = p.get("state")
        if st in _STATE_MAP:
            p["state"] = _STATE_MAP[st]
        if p.get("state") == "voting":
            p["state"], p["vote"] = "idle", None
        for k in _DROPPED_PIP_KEYS:
            p.pop(k, None)
        p["days_seen"] = sorted(set(p.get("days_seen") or []) | set(scan["by_key"].get(key, [])))
        camp = p.get("camp")
        if isinstance(camp, dict):
            report["camps"] += 1
            sessions = list((camp.get("sessions") if camp.get("sessions") is not None else camp.get("nights")) or [])
            camp["sessions"] = sessions
            camp["nights"] = list(sessions)                    # readable one release (the sleep era's name)
            stored = int(camp.get("tier") or 0)
            if not isinstance(camp.get("tiers"), list) or not camp["tiers"]:
                camp["tiers"] = [{"tier": stored, "ts": camp.get("built_ts")}]
            want = LAND.camp_tier_for(p, age)
            if want > stored:
                camp["tier"] = want
                camp["tiers"].append({"tier": want, "ts": _iso(now)})
                report["camps_lifted"] += 1
        p["last_told"] = seed_last_told(key, p, w, people, stones, now)
    w["age"] = int(age)
    w["age_built"] = 0
    w["age_build"] = None
    w["hatched_ever"] = people
    if not w.get("age_history"):
        w["age_history"] = _age_history_rows(new, scan, age, people, stones, len(days_on_air), now)
    w.setdefault("wish_post", [])
    w.setdefault("placed", [])
    w.setdefault("placed_seq", 0)
    new["schema"] = SCHEMA3
    report.update({"people": people, "stones": stones, "days": len(days_on_air), "age": int(age), "age_name": LAND.age_name(age),
                   "days_on_air": list(days_on_air)})
    log("schema 2 -> 3: %d pips, %d camps (%d lifted by the floor), people %d · stones %d · days %d -> age %d (%s)" % (
        report["pips"], report["camps"], report["camps_lifted"], people, stones, len(days_on_air), age, LAND.age_name(age)))
    return new, report


def _age_history_rows(doc: Dict[str, Any], scan: Dict[str, Any], age: int, people: int, stones: int, days: int,
                      now: float) -> List[Dict[str, Any]]:
    """One row per rung 0..age. Row 0 (the Clearing) is the first chatter's; the top rung carries today's counts and every
    pip on the land, top stackers first (AGES 5); rungs between carry their own needs (the land passed them unseen)."""
    LAND = _land()
    pips = doc.get("pips") or {}
    stacks: Dict[str, int] = {}
    for s in (doc.get("world") or {}).get("stones") or []:
        k = str(s.get("by") or "").lower()
        stacks[k] = stacks.get(k, 0) + 1

    def first_t(k: str) -> float:
        ft = scan["first_t"].get(k)
        if ft is None:
            ft = _epoch((pips.get(k) or {}).get("first_seen_ts")) or _epoch((pips.get(k) or {}).get("born_ts")) or now
        return float(ft)

    hatched = [k for k, p in pips.items() if isinstance(p, dict) and not p.get("_test") and p.get("state") not in ("seed", "hatching")]
    by_first = sorted(hatched, key=first_t)
    by_stacks = sorted(hatched, key=lambda k: (-stacks.get(k, 0), first_t(k)))
    rows: List[Dict[str, Any]] = []
    for idx in range(0, int(age) + 1):
        need = LAND.age_need(idx)
        if idx == 0:
            first = by_first[:1]
            rows.append({"idx": 0, "name": LAND.age_name(0), "ts": _iso(first_t(first[0])) if first else _iso(now),
                         "at": {"people": min(people, 1), "stones": 0, "days": min(days, 1)}, "raised_by": first,
                         "stones_placed": 0, "wished_by": {}})
        elif idx == int(age):
            rows.append({"idx": idx, "name": LAND.age_name(idx), "ts": _iso(now),
                         "at": {"people": people, "stones": stones, "days": days}, "raised_by": by_stacks,
                         "stones_placed": 0, "wished_by": {}})
        else:
            rows.append({"idx": idx, "name": LAND.age_name(idx), "ts": _iso(now),
                         "at": {"people": need[0], "stones": need[1], "days": need[2]}, "raised_by": by_stacks,
                         "stones_placed": 0, "wished_by": {}})
    return rows


# ---------------------------------------------------------------------------- the 6.3 gates
def verify_v3(old: Dict[str, Any], new: Dict[str, Any], chat_path: Optional[str] = None,
              now: Optional[float] = None) -> Tuple[bool, List[str], List[Tuple[str, str, bool]]]:
    """Every 6.3 gate, printed by the caller and asserted here: pip count equal; IDENTITY_FIELDS (+ salt) byte-identical
    per pip and the record fields unchanged; stone / mark / camp counts equal; every `nights` value in `sessions`; every
    camp tier >= old; `len(days_on_air)` == distinct local dates in the chat copy; `age == age_gate`; `age_built == 0 <=
    age`; `wish_post == []`, `placed == []`, `placed_seq == 0`; every pip has `last_told` with the eight keys; provenance
    violations []; schema 3; banished / quarantine key sets kept; camps on the map with tiers 0-3. (ok, problems, gates)."""
    import time as _time
    LAND = _land()
    now = float(now if now is not None else _time.time())
    problems: List[str] = []
    gates: List[Tuple[str, str, bool]] = []

    def gate(name: str, shown: str, ok: bool, problem: Optional[str] = None) -> None:
        gates.append((name, shown, bool(ok)))
        if not ok:
            problems.append(problem or ("%s: %s" % (name, shown)))

    op, np_ = old.get("pips") or {}, new.get("pips") or {}
    gate("pip count equal", "%d == %d" % (len(op), len(np_)), len(op) == len(np_) and set(op) == set(np_))
    ident_fields = ("name", "n", "colour_idx", "genome", "born_ts")
    try:
        from stream.world import state as _S
        ident_fields = tuple(getattr(_S, "IDENTITY_FIELDS", ident_fields))
    except Exception:
        pass
    bad_ident: List[str] = []
    bad_rec: List[str] = []
    for key in op:
        if key not in np_:
            bad_ident.append("%s missing" % key)
            continue
        for f in ident_fields:
            if _ident(op[key].get(f)) != _ident(np_[key].get(f)):
                bad_ident.append("%s.%s" % (key, f))
        if _ident((op[key].get("genome") or {}).get("salt")) != _ident((np_[key].get("genome") or {}).get("salt")):
            bad_ident.append("%s.genome.salt" % key)
        for f in ("sessions_seen", "session_ids", "minutes_present", "own_messages", "last_seen_ts", "first_seen_ts", "tier"):
            if _ident(op[key].get(f)) != _ident(np_[key].get(f)):
                bad_rec.append("%s.%s" % (key, f))
    gate("identity bytes per pip", "%d pips x %d fields + salt identical" % (len(op), len(ident_fields)) if not bad_ident else "changed: " + ", ".join(bad_ident[:4]),
         not bad_ident)
    gate("record fields unchanged", "sessions_seen · session_ids · minutes_present · own_messages · last_seen · first_seen · tier" if not bad_rec else "changed: " + ", ".join(bad_rec[:4]),
         not bad_rec)
    ow, nw = old.get("world") or {}, new.get("world") or {}
    for blk in ("stones", "marks"):
        a, b = len(ow.get(blk) or []), len(nw.get(blk) or [])
        gate("%s count equal" % blk[:-1], "%d == %d" % (a, b), a == b)
    oc = sum(1 for p in op.values() if isinstance(p.get("camp"), dict))
    nc = sum(1 for p in np_.values() if isinstance(p.get("camp"), dict))
    gate("camp count equal", "%d == %d" % (oc, nc), oc == nc)
    subset_bad, tier_bad, bounds_bad = [], [], []
    mw, mh = int(nw.get("map_w") or LAND.MAP_W), int(nw.get("map_h") or LAND.MAP_H)
    for key, p in np_.items():
        c = p.get("camp")
        o = (op.get(key) or {}).get("camp") if isinstance(op.get(key), dict) else None
        if not isinstance(c, dict):
            continue
        sessions = c.get("sessions") or []
        for v in (o or {}).get("nights") or []:
            if v not in sessions:
                subset_bad.append("%s:%s" % (key, v))
        if int(c.get("tier") or 0) < int((o or {}).get("tier") or 0):
            tier_bad.append("%s %s -> %s" % (key, (o or {}).get("tier"), c.get("tier")))
        try:
            inside = 0 <= int(c.get("x", -1)) < mw and 0 <= int(c.get("y", -1)) < mh
        except (TypeError, ValueError):
            inside = False
        if not inside or int(c.get("tier", -1)) not in (0, 1, 2, 3):
            bounds_bad.append(key)
    gate("nights subset of sessions", "%d camps" % nc if not subset_bad else "missing: " + ", ".join(subset_bad[:4]), not subset_bad)
    gate("camp tier >= old", ", ".join("%s %s->%s" % (k, ((op.get(k) or {}).get("camp") or {}).get("tier"), (p.get("camp") or {}).get("tier"))
                                        for k, p in sorted(np_.items()) if isinstance(p.get("camp"), dict)) or "no camps",
         not tier_bad, "camp tier lowered: " + ", ".join(tier_bad))
    gate("camps on the map, tiers 0-3", "%d camps" % nc if not bounds_bad else "bad: " + ", ".join(bounds_bad[:4]), not bounds_bad)
    scan = chat_scan(chat_path)
    doa = list(nw.get("days_on_air") or [])
    distinct = scan["dates"]
    no_chat = not scan["readable"] and not os.path.exists(str(chat_path or ""))     # a run dir with no chat.jsonl yet
    gate("days_on_air == distinct local chat dates", "%d == %d %s%s" % (len(doa), len(distinct), doa, " (no chat file, both empty)" if no_chat and not doa else ""),
         (scan["readable"] and sorted(set(doa)) == doa and doa == distinct) or (no_chat and not doa and not distinct),
         "days_on_air %r != chat dates %r%s" % (doa, distinct, "" if scan["readable"] else (" (no chat file: days_on_air must be empty)" if no_chat else " (chat copy unreadable)")))
    people, stones = hatched_count(new), len(nw.get("stones") or [])
    want_age = LAND.age_gate(people, stones, len(doa))
    gate("age == age_gate(people, stones, days)", "%s == age_gate(%d, %d, %d) = %d (%s)" % (nw.get("age"), people, stones, len(doa), want_age, LAND.age_name(want_age)),
         int(nw.get("age") or 0) == want_age)
    gate("age_built == 0 <= age", "%s, age %s" % (nw.get("age_built"), nw.get("age")),
         int(nw.get("age_built") or 0) == 0 and 0 <= int(nw.get("age") or 0))
    hist = nw.get("age_history") or []
    gate("age_history rows 0..age", "%d rows, idx %s" % (len(hist), [r.get("idx") for r in hist]),
         [r.get("idx") for r in hist] == list(range(0, int(nw.get("age") or 0) + 1))
         and all(isinstance(r.get("raised_by"), list) and all(k in np_ for k in r["raised_by"]) for r in hist))
    gate("wish_post == []", repr(nw.get("wish_post")), nw.get("wish_post") == [])
    gate("placed == []", repr(nw.get("placed")), nw.get("placed") == [])
    gate("placed_seq == 0", repr(nw.get("placed_seq")), int(nw.get("placed_seq") or 0) == 0)
    gate("cursor.wishes_offset present", repr((new.get("cursor") or {}).get("wishes_offset")), "wishes_offset" in (new.get("cursor") or {}))
    told_bad = [k for k, p in np_.items() if not isinstance(p.get("last_told"), dict) or any(f not in p["last_told"] for f in LAST_TOLD_KEYS)]
    gate("last_told on every pip (8 keys)", "%d pips" % len(np_) if not told_bad else "missing: " + ", ".join(told_bad[:4]), not told_bad)
    seen_bad = [k for k, p in np_.items() if not isinstance(p.get("days_seen"), list) or sorted(set(p["days_seen"])) != p["days_seen"]]
    gate("days_seen sorted distinct local dates", ", ".join("%s %d" % (k, len(p.get("days_seen") or [])) for k, p in sorted(np_.items())) or "no pips",
         not seen_bad, "days_seen malformed: " + ", ".join(seen_bad))
    states_bad = [k for k, p in np_.items() if p.get("state") in _STATE_MAP or p.get("state") not in ("seed", "hatching", "idle", "walking", "voting", "sitting", "hauling", "hidden")]
    gate("states in the schema-3 vocabulary", "%d pips" % len(np_) if not states_bad else "bad: " + ", ".join(states_bad[:4]), not states_bad)
    dropped_bad = [k for k, p in np_.items() if any(f in p for f in _DROPPED_PIP_KEYS)]
    gate("sleep-era keys dropped", "sleep_t · nights_streak" if not dropped_bad else "still on: " + ", ".join(dropped_bad[:4]), not dropped_bad)
    try:
        viol = LAND.Land(_DocView(new)).provenance_violations()
    except Exception as e:
        viol = ["provenance check failed: %r" % (e,)]
    gate("provenance violations", repr(viol), viol == [])
    gate("schema == 3", repr(new.get("schema")), int(new.get("schema") or 0) == SCHEMA3)
    for blk in ("banished", "quarantine"):
        same = set((old.get(blk) or {}).keys()) == set((new.get(blk) or {}).keys())
        gate("%s keys kept" % blk, "%d" % len(new.get(blk) or {}), same)
    for f in ("terrain_b64", "moss", "nests", "chambers"):
        if f in nw:
            problems.append("world block still carries schema-1 key %r" % f)
    return (not problems), problems, gates


def print_gates(gates: List[Tuple[str, str, bool]], out: Optional[Callable[[str], None]] = None, tag: str = "migrate") -> None:
    out = out or print
    width = max([len(g[0]) for g in gates] or [0])
    for name, shown, ok in gates:
        out("[%s] gate %s  %s  %s" % (tag, name.ljust(width), "ok  " if ok else "FAIL", shown))
    out("[%s] %d gates, %d passed, %d failed" % (tag, len(gates), sum(1 for g in gates if g[2]), sum(1 for g in gates if not g[2])))


# ---------------------------------------------------------------------------- the boot replay (IDLEWORLD 2.1)
def ledger_ids(run_dir: str) -> Set[str]:
    """Every id in $RUN_DIR/wishes.jsonl plus the rotated archives under wishes.archive/ (P4 writes them)."""
    ids: Set[str] = set()
    paths = [os.path.join(run_dir, WISHES_FILE)]
    arch = os.path.join(run_dir, WISHES_ARCHIVE_DIR)
    try:
        if os.path.isdir(arch):
            paths.extend(sorted(os.path.join(arch, f) for f in os.listdir(arch) if f.endswith(".jsonl")))
    except OSError:
        pass
    for path in paths:
        try:
            with open(path, "rb") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line.decode("utf-8", "replace"))
                    except Exception:
                        continue
                    if isinstance(row, dict) and row.get("id") is not None:
                        ids.add(str(row["id"]))
        except OSError:
            continue
    return ids


def classify_kind(text: str) -> Optional[str]:
    """The ledger kind of a moderated text: "plain" | "idea" | "theme" | "ask", or None for a vote, a mod command, an ops
    token (`pause bot`, `!stats`, `!help`). Asks the bridge's own classify when it imports; mirrors it otherwise."""
    t = (text or "").strip()
    if not t:
        return None
    try:
        from stream.chat_bridge import ChatBridge
        kind = ChatBridge.classify(t)[0]
    except Exception:
        kind = None
        if _VOTE_RE.match(t):
            kind = "vote"
        elif re.sub(r"\s+", " ", t.lower()) in _OPS_PHRASES:
            kind = "mod"
        else:
            cm = _CMD_RE.match(t)
            if cm:
                cmd = cm.group(1).lower()
                kind = cmd if cmd in ("idea", "theme", "ask", "stats", "help") else ("mod" if cmd in _MOD_CMDS else "plain")
            else:
                kind = "plain"
    if kind in ("plain", "idea", "theme", "ask"):
        return kind
    return None


def wish_eligible(m: Dict[str, Any]) -> Optional[str]:
    """A normalised chat record's ledger kind, or None when the ledger never keeps it (a vote, a mod command, an ops
    token, a webhook `type != message`, a nameless or timeless row)."""
    if not isinstance(m, dict) or m.get("type") not in (None, "message"):
        return None
    if not m.get("name") or m.get("t") is None or m.get("id") is None:
        return None
    return classify_kind(m.get("text") or "")


def _tagger(run_dir: str):
    """The bridge's wish tag (IDLEWORLD 2.1 (a)/(b)/(c)) when the bridge imports; None in a bare harness (tag off)."""
    try:
        from stream.chat_bridge import ChatBridge
        return ChatBridge(run_dir, log=lambda m: None)
    except Exception:
        return None


def replay_row(m: Dict[str, Any], kind: str, n: Optional[int], tagger=None) -> Dict[str, Any]:
    """One ledger row from a chat record the running spine never wrote (`src: "replay"`, `class: "pending"` for the probe).
    The text lands in the row only; for an `!idea` / `!theme` / `!ask` the argument, capped like the live rows."""
    text = str(m.get("text") or "").strip()
    arg = text
    cm = _CMD_RE.match(text)
    if kind in ("idea", "theme", "ask") and cm:
        arg = re.sub(r"\s+", " ", cm.group(2).strip())
        if kind == "theme":
            arg = (arg.split(" ")[0].lower().lstrip("#") if arg else "")
    cap = CAP_IDEA_TEXT if kind == "idea" else (CAP_ASK_TEXT if kind == "ask" else CAP_LEDGER_TEXT)
    wish, head, verb = False, None, None
    if tagger is not None:
        try:
            parsed = tagger.parse_verb(text) if kind == "plain" else None
            verb = parsed[0] if parsed else None
            if verb is None:
                wish, head = tagger.wish_tag(arg if kind == "idea" else text, kind)
        except Exception:
            wish, head = False, None
    t = float(m["t"])
    return {"id": str(m["id"]), "ts": m.get("ts") or _ss().epoch_to_iso(t), "key": str(m.get("name") or "").lower(),
            "by": str(m.get("name") or "?"), "n": n, "kind": kind, "text": arg[:cap], "verb": verb, "hint": None,
            "wish": bool(wish), "head": head, "first_ever": False, "session": None, "src": "replay", "class": "pending"}


def recompute_wishes(run_dir: str, chat_path: str, cursor: Dict[str, Any], builders: Optional[Dict[str, Dict]] = None,
                     log: Optional[Callable[[str], None]] = None, max_bytes: int = MAX_SCAN_BYTES) -> Dict[str, Any]:
    """IDLEWORLD 2.1 boot replay: walk chat.jsonl from `cursor["wishes_offset"]`; every record the ledger keeps (not a
    vote / mod command / ops token / webhook non-message) whose id is missing from $RUN_DIR/wishes.jsonl (+ archives) gets a
    `src: "replay"` row; the offset advances to the last full line. Idempotent by id (a second run adds 0). Logs
    `wishes: +N replay rows, M already present`. Returns {added, present, eligible, skipped, offset, ok}."""
    log = log or (lambda m: None)
    out: Dict[str, Any] = {"added": 0, "present": 0, "eligible": 0, "skipped": 0, "offset": int(cursor.get("wishes_offset") or 0), "ok": False}
    try:
        size = os.path.getsize(chat_path)
    except OSError:
        log("wishes: chat.jsonl unreadable, nothing replayed")
        return out
    offset = int(cursor.get("wishes_offset") or 0)
    if offset > size:
        offset = 0
    if size - offset > max_bytes:
        offset = size - max_bytes
    try:
        with open(chat_path, "rb") as fh:
            fh.seek(offset)
            data = fh.read(size - offset)
    except OSError:
        log("wishes: chat.jsonl unreadable, nothing replayed")
        return out
    last_nl = data.rfind(b"\n")
    if last_nl < 0:
        out["ok"] = True
        log("wishes: +0 replay rows, 0 already present")
        return out
    SS = _ss()
    ids = ledger_ids(run_dir)
    seen: Set[str] = set()
    recs: List[Dict[str, Any]] = []
    for line in data[: last_nl + 1].splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            m = SS.normalise_chat(json.loads(line.decode("utf-8", "replace")))
        except Exception:
            out["skipped"] += 1
            continue
        if m is None or m["id"] in seen:
            out["skipped"] += 1
            continue
        seen.add(m["id"])
        recs.append(m)
    recs.sort(key=lambda r: float(r.get("t") or 0.0))
    tagger = _tagger(run_dir) if recs else None
    rows: List[Dict[str, Any]] = []
    for m in recs:
        kind = wish_eligible(m)
        if kind is None:
            out["skipped"] += 1
            continue
        out["eligible"] += 1
        if m["id"] in ids:
            out["present"] += 1
            continue
        key = str(m.get("name") or "").lower()
        b = (builders or {}).get(key) or {}
        try:
            n = int(b.get("n")) if b.get("n") is not None else None
        except (TypeError, ValueError):
            n = None
        rows.append(replay_row(m, kind, n, tagger))
        ids.add(m["id"])
    if rows:
        try:
            os.makedirs(run_dir, exist_ok=True)
            with open(os.path.join(run_dir, WISHES_FILE), "a", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            out["added"] = len(rows)
        except OSError as e:
            log("wishes: ledger append failed (%r): cursor not advanced" % (e,))
            return out
    cursor["wishes_offset"] = offset + last_nl + 1
    out["offset"] = cursor["wishes_offset"]
    out["ok"] = True
    log("wishes: +%d replay rows, %d already present" % (out["added"], out["present"]))
    return out


__all__ = ["SCHEMA3", "LAST_TOLD_KEYS", "WISHES_FILE", "WORLD_KEYS_V3", "world_v3_defaults", "pip_v3_defaults", "adopt_v3",
           "chat_scan", "hatched_count", "seed_last_told", "migrate_v3_doc", "verify_v3", "print_gates", "ledger_ids",
           "classify_kind", "wish_eligible", "replay_row", "recompute_wishes"]
