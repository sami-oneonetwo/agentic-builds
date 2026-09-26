"""stream/world/state.py - world.json persistence (WORLD.md 3.1-3.4, 11, 12 row 4).

    from stream.world.state import WorldState
    ws = WorldState(run_dir, log=print, name_filter=None)       # loads $RUN_DIR/world.json (tolerates missing/corrupt)
    ws.begin_session(session_id, now)                            # once per compositor boot: sessions log, daily .bak
    ws.recompute_from_chat(now, session_id)                      # chat.jsonl -> pips by distinct (session, owner), cursor
    p = ws.ensure_pip("sami", "Sami", "Sami", n=2, t=now)        # identity is frozen the first time; later calls no-op it
    ws.record_message("sami", now, session_id, text_clean)       # own_messages, words, last_seen, session_ids, energy
    ws.presence("sami", dt_s)                                    # minutes_present while awake and the stream is live
    ws.update_tier(p) -> new tier or None                        # sessions or minutes, never message count alone
    ws.care("sami", by="atleastonce", verb="feed", t=now) ; ws.gift(...) ; ws.bond("a", "b")
    ws.terrain() -> np.bool_ (110, 320) carved mask ; ws.set_terrain(mask) ; ws.moss (list) ; ws.plant_moss(...)
    ws.save(now, force=False)                                    # atomic tmp + os.replace, at most every 5 s unless forced
    ws.hatched_ever ; ws.pips ; ws.data ; ws.builders (builders.json join, read-only)

Schema 2 (OPENWORLD.md 5, LONGGRASS):
    ws = WorldState(run_dir, schema=2)                           # loads; a schema-1 file is migrated on a COPY under the
                                                                 # 5.4 guard (identity byte-identical, pip count equal);
                                                                 # on failure ws.schema stays 1 and ws.migration_ok False:
                                                                 # the scene REFUSES to boot (keeps the last good frame)
    ws.migrate_v2(now, moot_xy=(x, y), passable=mask, water=mask, dry_run=False) -> report   # explicit form
    ws.schema -> 1 | 2 ; ws.migration -> report | None ; ws.land -> stream.world.land.Land (schema 2 only, else None)
    ws.set_pos("sami", x, y, facing=(fx, fy)) ; ws.set_carry("sami", "stone", now) ; ws.ensure_camp("sami", now, sid)
    ws.iso(t) ; ws.epoch(s)                                      # the timestamp helpers Land uses
    $PYTHON stream/world/state.py --migrate-copy SRC.json [--out /tmp/x/world.json]   # 5.4: run the guard on a copy
    $PYTHON stream/world/state.py --self-test                    # v1 -> v2 on a fixture + land / camera round trips
Schema 2 pip fields: `y` (map cells), `facing [fx, fy]`, `colour` (art.creatures.genome hex), `camp {x, y, tier,
built_ts, nights[]}`, `field`, `carry`, `carry_since_ts`, `home [x, y]`, `marks_planted {flower, tree, reed, stone}`,
`history {digs, burrow, moss_planted, x_v1, y_v1}`; `burrow`, `digs`, `moss_planted` are dropped from the row.
World block gains `map_seed, map_w, map_h, moot, hemisphere, world_day, wear_b64, marks, fields, stones, raisings,
land_strips, camera, weather, hearth, bake_ver, mark_seq, history{v1}`; `terrain_b64, moss, nests, chambers` are dropped.
A schema-1 document is still read and written unchanged (the cave's rollback week): `save()` writes the schema it
loaded, never upgrades by itself.

Rules: identity fields (name, n, colour_idx, genome incl. salt, born_ts) are written once and never recomputed.
Counts are never incremented on boot: `recompute_from_chat` walks chat.jsonl from the stored cursor and adds
`(session_id, name_lower)` pairs to a SET per pip, so re-ingest is idempotent (fixes 014.2). Energy never
decays while asleep or while the stream is off (WORLD.md 10): decay is applied only by the behaviour tick
for awake pips. Nothing here draws text; `display_name` is stored from the moderated record so the text
layer never needs the raw name path (014.1).
"""
from __future__ import annotations

import base64
import copy
import datetime as _dt
import glob
import json
import os
import re
import sys
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stream.state_store import write_state_atomic, iso_to_epoch, epoch_to_iso, normalise_chat, run_path  # noqa: E402
from stream.world import SIM_W, SIM_H  # noqa: E402
from stream.world import pips as P  # noqa: E402
from stream.world import land as LAND  # noqa: E402

SCHEMA_V1 = 1                     # PIP HOLLOW (the cave); still read and written for the rollback week
SCHEMA = 2                        # LONGGRASS (OPENWORLD.md 5)
IDENTITY_FIELDS = ("name", "n", "colour_idx", "genome", "born_ts")   # byte-identical across the migration (5.4)
FLUSH_S = 5.0
DIG_W = 5                         # a dig pocket is 5 wide x 3 tall sim cells (20 x 12 px on screen)
DIG_CAP = 45                      # cells per user per session (3 full pockets)
BAK_KEEP = 7
MILESTONES = [3, 5, 10, 25, 50]
HIST_GAP_S = 45 * 60.0            # a gap this long between records in history = a new (pseudo) session
WORDS_KEEP = 24                   # counts kept per pip; top 8 are the "words" the pip may mutter
WORDS_TOP = 8
CARE_LOG_MAX = 20
EVENT_LOG_MAX = 50
STOPWORDS = set("""a an the and or but if then so of to in on at by for with from as is are was were be been being am
i me my mine you your yours he him his she her hers it its we us our they them their this that these those there here
what which who whom whose when where why how not no yes do does did done have has had having can could will would shall
should may might must just very too also only even still yet up down out over under again more most less lol lmao omg
ok okay hi hello hey yo im ive youre thats dont cant wont didnt isnt its u ur r y n""".split())
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'_-]{1,15}")


def _iso(t: Optional[float]) -> Optional[str]:
    return epoch_to_iso(float(t), ms=True) if t else None


def default_hemisphere() -> str:
    """`south` when the machine timezone is Australia/* (or another southern zone), else `north`. Overridable in
    world.json["world"]["hemisphere"]; the land line names the season so a mistake is visible (OPENWORLD 2.2)."""
    tz = os.environ.get("TZ") or ""
    if not tz:
        try:
            tz = os.readlink("/etc/localtime")
        except OSError:
            tz = ""
    south = ("Australia/", "Pacific/Auckland", "Africa/Johannesburg", "America/Sao_Paulo", "America/Argentina",
             "America/Santiago", "Antarctica/")
    return "south" if any(s in tz for s in south) else "north"


def _default_world(schema: int = SCHEMA_V1) -> Dict[str, Any]:
    common = {
        "milestones": list(MILESTONES),
        "milestones_reached": [],
        "hatched_ever": 0,
        "woke_log": [],
        "visits": [],
        "board": {"session_id": None, "fed": {}, "dug": {}, "hatched": []},
        "last_board": None,
        "event_log": [],
    }
    if int(schema) >= 2:
        common.update({
            "map_seed": LAND.MAP_SEED, "map_w": LAND.MAP_W, "map_h": LAND.MAP_H,
            "moot": [LAND.DEFAULT_MOOT[0], LAND.DEFAULT_MOOT[1]],
            "hemisphere": default_hemisphere(), "world_day": "real",
            "wear_b64": None,               # uint8 960x440 zlib + base64; None = nothing worn yet
            "marks": [], "fields": [], "stones": [], "raisings": [], "land_strips": [],
            "camera": None,
            "weather": {"state": "clear", "since_ts": None, "chain_seed": LAND.MAP_SEED},
            "hearth": {"lit_ts": None, "by": None},
            "bake_ver": 1, "mark_seq": 0,
            "history": {},
        })
    else:
        common.update({
            "terrain_b64": None,
            "moss": [],
            "nests": [],
            "chambers": [{"name": "the Hollow", "opened_ts": None, "by": None, "milestone": 0}],
        })
    return common


def _default_data(schema: int = SCHEMA_V1) -> Dict[str, Any]:
    return {
        "schema": int(schema),
        "updated_ts": None,
        "cursor": {"chat_jsonl_offset": 0, "last_id": None},
        "pips": {},
        "world": _default_world(schema),
        "sessions": [],           # [{id, started_ts, last_ts}] every session this module has seen (live or inferred)
        "banished": {},
        "quarantine": {},         # {key: {record, reason, ts}}: world.json pips with NO chat.jsonl chatter (WORLD.md 1, 11)
    }


def pip_colour(key: str) -> Optional[str]:
    """The creature's body colour from the art genome (`art.creatures.genome(name)["colour"]`, a hex string): labels,
    plates, roofs, field borders and minimap dots use it (OPENWORLD 5.1). None if the atlas is unavailable."""
    try:
        from stream.world.art import creatures as _C
        return str(_C.genome((key or "").lower())["colour"])
    except Exception:
        return None


def _v2_pip_fields(key: str) -> Dict[str, Any]:
    return {
        "facing": [1, 0], "colour": pip_colour(key),
        "camp": None, "field": None, "carry": None, "carry_since_ts": None, "home": None,
        "marks_planted": {"flower": 0, "tree": 0, "reed": 0, "stone": 0},
        "history": {},
    }


def _default_pip(key: str, name: str, display_name: str, n: Optional[int], t: float, genome: Dict[str, int],
                 schema: int = SCHEMA_V1) -> Dict[str, Any]:
    p = {
        "name": name, "display_name": display_name, "n": n,
        "colour_idx": P.colour_idx(key),
        "genome": dict(genome),
        "born_ts": _iso(t),
        "sessions_seen": 0, "session_ids": [],
        "minutes_present": 0.0, "own_messages": 0, "nights_streak": 0,
        "last_seen_ts": _iso(t), "first_seen_ts": _iso(t),
        "tier": 0, "energy": 0.6, "state": "seed",
        "x": None, "y": None, "burrow": None, "vote": None,
        "words": {}, "learned": [], "bonds": {}, "nickname": None,
        "care_log": [], "gifts_pending": [],
        "moss_planted": 0, "digs": 0, "votes_cast": 0, "events_picked": 0,
        "raised_in_nest": None, "strikes": 0,
    }
    if int(schema) >= 2:
        for f in ("burrow", "moss_planted", "digs"):
            p.pop(f, None)
        p.update(_v2_pip_fields(key))
    return p


class WorldState(object):
    """Owner of $RUN_DIR/world.json. One instance per compositor process (the world module)."""

    def __init__(self, run_dir: str, log: Optional[Callable[[str], None]] = None,
                 name_filter: Optional[Callable[[str], str]] = None, schema: Optional[int] = None,
                 moot: Optional[Tuple[float, float]] = None, passable: Optional[np.ndarray] = None,
                 water: Optional[np.ndarray] = None, now: Optional[float] = None):
        """`schema=None` keeps whatever the file has (a fresh file is schema 1: the cave's contract). `schema=2` asks
        for LONGGRASS: a fresh file starts at 2, a schema-1 file is migrated under the 5.4 guard (see `migration_ok`).
        `moot` / `passable` / `water` are terrain.py's places centre and masks for camp placement (optional)."""
        self.run_dir = run_dir
        self.log = log or (lambda m: None)
        self.path = os.path.join(run_dir, "world.json")
        self.chat_path = run_path(run_dir, "CHAT_FILE", "chat.jsonl")
        self.builders_path = os.path.join(run_dir, "builders.json")
        self.name_filter = name_filter or (lambda s: s)
        self.want_schema: Optional[int] = int(schema) if schema is not None else None
        self._moot = tuple(moot) if moot else None
        self._passable, self._water = passable, water
        self.data: Dict[str, Any] = _default_data(self.want_schema or SCHEMA_V1)
        self.builders: Dict[str, Dict] = {}
        self.dirty = False
        self._last_flush: Optional[float] = None
        self._terrain: Optional[np.ndarray] = None
        self._land = None
        self.loaded_ok = False
        self.load_errors = 0
        self.session_id: Optional[str] = None
        self.migration: Optional[Dict[str, Any]] = None
        self.migration_ok: bool = True
        self.load()
        if self.want_schema is not None and self.want_schema >= 2:
            if self.schema < 2:
                self.migrate_v2(now=now, moot_xy=self._moot, passable=passable, water=water)
            else:
                self.migration = {"ok": True, "skipped": True, "reason": "file is schema %d" % self.schema}

    # ------------------------------------------------------------------ schema
    @property
    def schema(self) -> int:
        try:
            return int(self.data.get("schema") or SCHEMA_V1)
        except Exception:
            return SCHEMA_V1

    @property
    def land(self):
        """The Land object over this document (schema 2 only; None for a schema-1 document)."""
        if self.schema < 2:
            return None
        if self._land is None:
            self._land = LAND.Land(self, moot=self._moot, log=self.log)
            if self._passable is not None or self._water is not None:
                self._land.set_terrain_layers(self._passable, self._water)
        return self._land

    @staticmethod
    def iso(t: Optional[float]) -> Optional[str]:
        return _iso(t)

    @staticmethod
    def epoch(s: Any) -> Optional[float]:
        return iso_to_epoch(s)

    # ------------------------------------------------------------------ load / save
    def load(self) -> bool:
        """Read world.json; a missing or corrupt file leaves the defaults (and is logged), never raises. The file's
        own schema decides which world defaults are filled in (a schema-2 file never regains moss / terrain)."""
        self.data = _default_data(self.want_schema or SCHEMA_V1)
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if not isinstance(d, dict) or not isinstance(d.get("pips"), dict):
                raise ValueError("world.json is not an object with pips")
            self.data = self._adopt(d)
            self.loaded_ok = True
        except FileNotFoundError:
            self.loaded_ok = False
        except Exception as e:
            self.load_errors += 1
            self.loaded_ok = False
            self.log("world.json unreadable (%r): starting from the newest .bak if any" % (e,))
            if not self._load_bak():
                self.data = _default_data(self.want_schema or SCHEMA_V1)
        self._load_builders()
        self._terrain = None
        self._land = None
        self.data["world"]["hatched_ever"] = self.hatched_ever
        return self.loaded_ok

    @staticmethod
    def _adopt(d: Dict[str, Any]) -> Dict[str, Any]:
        """A parsed document -> the in-memory shape: defaults for ITS schema filled in, pip keys lower-cased, test rows dropped."""
        try:
            sch = int(d.get("schema") or SCHEMA_V1)
        except Exception:
            sch = SCHEMA_V1
        base = _default_data(sch)
        for k, v in d.items():
            base[k] = v
        if not isinstance(base.get("world"), dict):
            base["world"] = {}
        for k, v in _default_world(sch).items():
            base["world"].setdefault(k, v)
        base["schema"] = sch
        base["pips"] = {str(k).lower(): v for k, v in base["pips"].items() if isinstance(v, dict) and not v.get("_test")}
        return base

    def _load_bak(self) -> bool:
        for bak in sorted(glob.glob(self.path + ".bak-*"), key=os.path.getmtime, reverse=True):
            try:
                with open(bak, "r", encoding="utf-8") as fh:
                    d = json.load(fh)
                if isinstance(d, dict) and isinstance(d.get("pips"), dict):
                    self.data = self._adopt(d)
                    self.log("world.json restored from %s (%d pips)" % (os.path.basename(bak), len(d["pips"])))
                    return True
            except Exception:
                continue
        return False

    def _load_builders(self) -> None:
        try:
            with open(self.builders_path, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if isinstance(d, dict):
                self.builders = {str(k).lower(): v for k, v in d.items() if isinstance(v, dict)}
        except Exception:
            self.builders = {}

    def builder_n(self, key: str) -> Optional[int]:
        b = self.builders.get((key or "").lower()) or {}
        try:
            return int(b.get("n")) if b.get("n") is not None else None
        except Exception:
            return None

    def save(self, now: float, force: bool = False) -> bool:
        """Atomic write (tmp + os.replace). Throttled to FLUSH_S unless forced. Never raises."""
        if not force:
            if not self.dirty:
                return False
            if self._last_flush is not None and now - self._last_flush < FLUSH_S:
                return False
        try:
            if self.schema < 2:
                if self._terrain is not None:
                    self.data["world"]["terrain_b64"] = base64.b64encode(np.packbits(self._terrain.reshape(-1))).decode("ascii")
            elif self._land is not None:
                self._land.flush()                     # wear -> wear_b64 only when it changed
            self.data["schema"] = self.schema          # the schema it loaded (or migrated to); never a silent upgrade
            self.data["updated_ts"] = _iso(now)
            self.data["world"]["hatched_ever"] = self.hatched_ever
            for p in self.data["pips"].values():
                self._trim_words(p)
            os.makedirs(self.run_dir, exist_ok=True)
            # synthetic test pips (KL_TEST_PIPS) are NEVER written: world.json holds real people only
            out = dict(self.data)
            out["pips"] = {k: v for k, v in self.data["pips"].items() if not v.get("_test")}
            write_state_atomic(self.path, out)
            self.dirty = False
            self._last_flush = now
            return True
        except Exception as e:
            self.log("world.json write failed: %r" % (e,))
            return False

    def backup(self, now: float) -> Optional[str]:
        """world.json.bak-YYYYMMDD, once per day (called at session start). Keeps BAK_KEEP."""
        if not os.path.exists(self.path):
            return None
        day = _dt.datetime.fromtimestamp(now, tz=_dt.timezone.utc).strftime("%Y%m%d")
        bak = self.path + ".bak-" + day
        try:
            if not os.path.exists(bak):
                with open(self.path, "rb") as src, open(bak + ".tmp", "wb") as dst:
                    dst.write(src.read())
                os.replace(bak + ".tmp", bak)
            dailies = [b for b in sorted(glob.glob(self.path + ".bak-*")) if ".bak-v1-" not in b]   # the pre-migration copy is kept
            for old in dailies[:-BAK_KEEP]:
                try:
                    os.remove(old)
                except OSError:
                    pass
            return bak
        except Exception as e:
            self.log("world.json backup failed: %r" % (e,))
            return None

    # ------------------------------------------------------------------ sessions
    def begin_session(self, session_id: Optional[str], now: float) -> None:
        """Called once when the world module learns the live session id. Appends to the sessions log, rolls the
        nightly board, takes the daily backup. Idempotent for the same id."""
        sid = session_id or ("boot-%s" % _dt.datetime.fromtimestamp(now, tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M"))
        self.session_id = sid
        self.backup(now)
        sessions = self.data.setdefault("sessions", [])
        if not any(s.get("id") == sid for s in sessions):
            sessions.append({"id": sid, "started_ts": _iso(now), "last_ts": _iso(now)})
            if len(sessions) > 400:
                del sessions[:-400]
            w = self.data["world"]
            if w["board"].get("session_id") not in (None, sid):
                w["last_board"] = w["board"]
            w["board"] = {"session_id": sid, "fed": {}, "dug": {}, "hatched": []}
            self.dirty = True

    def touch_session(self, now: float) -> None:
        for s in self.data.get("sessions", []):
            if s.get("id") == self.session_id:
                s["last_ts"] = _iso(now)

    def session_for(self, t: float) -> str:
        """The session id that was live at epoch t (the current one if t is inside it; a known one from the
        sessions log; else an inferred `hist-...` id). Used to stamp re-ingested history."""
        for s in self.data.get("sessions", []):
            a, b = iso_to_epoch(s.get("started_ts")), iso_to_epoch(s.get("last_ts"))
            if a is not None and b is not None and a - 60.0 <= t <= b + HIST_GAP_S:
                return str(s.get("id"))
        return "hist-" + _dt.datetime.fromtimestamp(t, tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M")

    # ------------------------------------------------------------------ pips
    @property
    def pips(self) -> Dict[str, Dict]:
        return self.data["pips"]

    @property
    def hatched_ever(self) -> int:
        """len() over REAL, HATCHED pips: synthetic test pips (KL_TEST_PIPS, `_test: true`) are never counted, and a
        record whose creature is still a seed / cracking egg (state seed|hatching) counts from the hatch frame, so the
        header tick and the egg pop land in the same frame (WORLD.md 2.2 T+3 s). Quarantined orphans are not pips."""
        return sum(1 for p in self.data["pips"].values() if not p.get("_test") and p.get("state") not in ("seed", "hatching"))

    def pip(self, key: str) -> Optional[Dict]:
        return self.data["pips"].get((key or "").lower())

    def ensure_pip(self, key: str, name: str, display_name: Optional[str], n: Optional[int], t: float) -> Tuple[Dict, bool]:
        """Create the record for a real chatter (identity frozen now) or return the existing one. (pip, created)."""
        key = (key or "").lower()
        if key in self.data.get("banished", {}):
            return self.data["banished"][key], False
        q = self.data.get("quarantine") or {}
        if key in q and key not in self.data["pips"]:
            # ensure_pip is reached only from a chat record (ingest / recompute), so the orphan now HAS a chatter: restore
            rec = q.pop(key)
            if isinstance(rec, dict) and isinstance(rec.get("record"), dict):
                self.data["pips"][key] = rec["record"]
                if self.schema >= 2 and rec.get("land"):
                    self.land.restore_owner(key, rec.get("land"))
                self.log("quarantine: %s restored (a chat.jsonl record arrived)" % key)
                self.dirty = True
        p = self.data["pips"].get(key)
        if p is not None:
            if not p.get("display_name") and display_name:
                p["display_name"] = display_name
                self.dirty = True
            if p.get("n") is None and n is not None:
                p["n"] = n
                self.dirty = True
            if self.schema >= 2 and not p.get("colour"):
                p["colour"] = pip_colour(key)
                self.dirty = True
            return p, False
        g, salt = P.resolve_genome(key, 0)
        p = _default_pip(key, name or key, display_name or self.name_filter(name or key), n if n is not None else self.builder_n(key), t, g,
                         schema=self.schema)
        self.data["pips"][key] = p
        self.data["world"]["hatched_ever"] = self.hatched_ever
        board = self.data["world"]["board"]
        if self.session_id and board.get("session_id") == self.session_id:
            board.setdefault("hatched", []).append(key)
        self.dirty = True
        return p, True

    def add_session(self, p: Dict, session_id: str) -> bool:
        ids = p.setdefault("session_ids", [])
        if session_id in ids:
            return False
        ids.append(session_id)
        if len(ids) > 400:
            del ids[:-400]
        p["sessions_seen"] = len(ids)
        self.dirty = True
        return True

    def record_message(self, key: str, t: float, session_id: Optional[str], text: Optional[str] = None,
                       history: bool = False) -> Optional[Dict]:
        """One real message from the owner: counts, words, last_seen, session membership. History records
        (re-ingest) only add the (session, owner) pair and last_seen; live ones also count and brighten."""
        p = self.pip(key)
        if p is None:
            return None
        sid = session_id or self.session_for(t)
        self.add_session(p, sid)
        if not p.get("last_seen_ts") or (iso_to_epoch(p.get("last_seen_ts")) or 0) < t:
            p["last_seen_ts"] = _iso(t)
        if not history:
            p["own_messages"] = int(p.get("own_messages") or 0) + 1
            p["energy"] = min(1.0, float(p.get("energy") or 0.0) + 0.15)
            if text:
                self._learn_words(p, text)
        self.dirty = True
        return p

    def _learn_words(self, p: Dict, text: str) -> None:
        words = p.setdefault("words", {})
        names = set(self.data["pips"].keys())
        for tok in _TOKEN_RE.findall((text or "").lower()):
            if tok in STOPWORDS or tok in names or tok.startswith("!") or len(tok) < 3:
                continue
            words[tok] = int(words.get(tok) or 0) + 1
        self._trim_words(p)

    @staticmethod
    def _trim_words(p: Dict) -> None:
        words = p.get("words") or {}
        if len(words) > WORDS_KEEP:
            keep = sorted(words.items(), key=lambda kv: (-kv[1], kv[0]))[:WORDS_KEEP]
            p["words"] = dict(keep)

    @staticmethod
    def top_words(p: Dict, n: int = WORDS_TOP) -> List[str]:
        words = p.get("words") or {}
        return [w for w, _ in sorted(words.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]

    def touch_seen(self, key: str, t: float) -> None:
        """A RAW record from this pip's owner landed (pre-hold): last_seen_ts moves to t at once, so `awake` (which
        flips on the raw record) and the honesty reference (distinct chatters by last_seen) agree in the same frame.
        Counts (own_messages, words, energy) still wait for the moderated record in record_message()."""
        p = self.pip(key)
        if p is None:
            return
        if not p.get("last_seen_ts") or (iso_to_epoch(p.get("last_seen_ts")) or 0) < t:
            p["last_seen_ts"] = _iso(t)
            self.dirty = True

    def presence(self, key: str, dt_s: float) -> None:
        p = self.pip(key)
        if p is not None and dt_s > 0:
            p["minutes_present"] = float(p.get("minutes_present") or 0.0) + dt_s / 60.0
            self.dirty = True

    @staticmethod
    def tier_for(p: Dict) -> int:
        """WORLD.md 3.3 growth table: sessions or minutes present, or (tier 1 only) 5 own messages."""
        sess = int(p.get("sessions_seen") or 0)
        mins = float(p.get("minutes_present") or 0.0)
        msgs = int(p.get("own_messages") or 0)
        t = 0
        if msgs >= 5 or mins >= 10:
            t = 1
        if sess >= 3 or mins >= 120:
            t = 2
        if sess >= 10 or mins >= 600:
            t = 3
        return max(t, int(p.get("tier") or 0))     # never shrinks

    def update_tier(self, p: Dict) -> Optional[int]:
        t = self.tier_for(p)
        if t != int(p.get("tier") or 0):
            p["tier"] = t
            self.dirty = True
            return t
        return None

    def set_energy(self, key: str, e: float) -> None:
        p = self.pip(key)
        if p is not None:
            p["energy"] = max(0.0, min(1.0, float(e)))
            self.dirty = True

    def set_state(self, key: str, state: str, x: Optional[float] = None, y: Optional[float] = None,
                  burrow: Optional[int] = None, vote: Optional[str] = "keep") -> None:
        p = self.pip(key)
        if p is None:
            return
        p["state"] = state
        if x is not None:
            p["x"] = int(round(x))
        if y is not None:
            p["y"] = int(round(y))
        if burrow is not None and self.schema < 2:      # schema 2 has camps, not burrows (5.1); the argument is ignored
            p["burrow"] = int(burrow)
        if vote != "keep":
            p["vote"] = vote
        self.dirty = True

    def set_pos(self, key: str, x: float, y: float, facing: Optional[Tuple[float, float]] = None) -> None:
        """Schema 2: the pip's feet cell (x column, y row in map cells) and its 8-direction facing [fx, fy]."""
        p = self.pip(key)
        if p is None:
            return
        p["x"], p["y"] = int(round(x)), int(round(y))
        if facing is not None:
            fx, fy = float(facing[0]), float(facing[1])
            p["facing"] = [int(round(max(-1.0, min(1.0, fx)))), int(round(max(-1.0, min(1.0, fy))))]
        self.dirty = True

    def set_carry(self, key: str, kind: Optional[str], t: float) -> None:
        """`carry`: None | "berry" | "stone" with `carry_since_ts` (5.1)."""
        p = self.pip(key)
        if p is None:
            return
        p["carry"] = kind if kind in ("berry", "stone") else None
        p["carry_since_ts"] = _iso(t) if p["carry"] else None
        self.dirty = True

    def ensure_camp(self, key: str, t: float, session_id: Optional[str] = None, x: Optional[float] = None,
                    y: Optional[float] = None) -> Optional[Dict]:
        """The first real sleep creates the camp (a hollow, tier 0) at the spot the pip stood (5.1 / 5.3); later sleeps
        only record the night and re-read the ladder. A spot the rules refuse (the green, water, another's camp) falls
        back to the hashed Steading-ring spot. Returns the camp (or None for an unknown / test pip / schema 1)."""
        if self.schema < 2:
            return None
        land = self.land
        p = land.real_pip(key)
        if p is None:
            return None
        camp = p.get("camp")
        if isinstance(camp, dict):
            land.record_night(key, session_id, t)
            return camp
        px = x if x is not None else p.get("x")
        py = y if y is not None else p.get("y")
        if px is not None and py is not None:
            camp, _ = land.set_camp(key, px, py, t, check=True, session_id=session_id)
            if camp is not None:
                return camp
        taken = [(c["x"], c["y"]) for c in land.camps()]
        hx, hy = LAND.hashed_camp_spot(key, land.moot, taken, land.passable, land.water)
        camp, _ = land.set_camp(key, hx, hy, t, check=False, session_id=session_id)
        return camp

    # ------------------------------------------------------------------ care, gifts, bonds
    def care(self, key: str, by: str, verb: str, t: float) -> bool:
        p = self.pip(key)
        if p is None:
            return False
        log = p.setdefault("care_log", [])
        log.append({"by": (by or "").lower(), "verb": verb, "ts": _iso(t)})
        if len(log) > CARE_LOG_MAX:
            del log[:-CARE_LOG_MAX]
        p["energy"] = min(1.0, float(p.get("energy") or 0.0) + 0.10)
        self.bond(key, by)
        board = self.data["world"]["board"]
        if verb == "feed":
            fed = board.setdefault("fed", {})
            fed[(by or "").lower()] = int(fed.get((by or "").lower()) or 0) + 1
        self.dirty = True
        return True

    def take_care_log(self, key: str) -> List[Dict]:
        p = self.pip(key)
        if p is None:
            return []
        out = list(p.get("care_log") or [])
        p["care_log"] = []
        gifts = list(p.get("gifts_pending") or [])
        if gifts:
            out.extend({"by": g.get("from"), "verb": "gift", "ts": g.get("ts")} for g in gifts)
            p["gifts_pending"] = []
        if out:
            self.dirty = True
        return out

    def gift(self, key: str, frm: str, t: float) -> bool:
        p = self.pip(key)
        if p is None:
            return False
        p.setdefault("gifts_pending", []).append({"from": (frm or "").lower(), "ts": _iso(t)})
        self.dirty = True
        return True

    def bond(self, a: str, b: str) -> None:
        a, b = (a or "").lower(), (b or "").lower()
        if not a or not b or a == b:
            return
        for x, y in ((a, b), (b, a)):
            p = self.pip(x)
            if p is not None:
                bonds = p.setdefault("bonds", {})
                bonds[y] = int(bonds.get(y) or 0) + 1
        self.dirty = True

    def forget(self, key: str) -> bool:
        p = self.pip(key)
        if p is None:
            return False
        p["words"], p["learned"], p["care_log"] = {}, [], []
        self.dirty = True
        return True

    # ------------------------------------------------------------------ terrain and moss
    def terrain(self) -> np.ndarray:
        """Boolean (SIM_H, SIM_W) carved mask (True = carved/void). Missing or corrupt -> the default cavern."""
        if self._terrain is None:
            m = None
            b64 = self.data["world"].get("terrain_b64")
            if b64:
                try:
                    bits = np.unpackbits(np.frombuffer(base64.b64decode(b64), dtype=np.uint8))[: SIM_W * SIM_H]
                    if bits.size == SIM_W * SIM_H:
                        m = bits.reshape(SIM_H, SIM_W).astype(bool)
                except Exception as e:
                    self.log("terrain_b64 corrupt (%r): default cavern" % (e,))
            ver = int(self.data["world"].get("terrain_ver") or 1)
            if m is None:
                m = default_terrain()
            elif ver < TERRAIN_VER:
                try:
                    m = upgrade_terrain(m, ver)
                    self.log("terrain upgraded v%d -> v%d (digs kept)" % (ver, TERRAIN_VER))
                except Exception as e:
                    self.log("terrain upgrade failed (%r): keeping the saved cavern" % (e,))
            self.data["world"]["terrain_ver"] = TERRAIN_VER
            self._terrain = m
            self.dirty = True
        return self._terrain

    def set_terrain(self, mask: np.ndarray) -> None:
        self._terrain = mask.astype(bool).copy()
        self.dirty = True

    def dig_cells(self, cx: int, cy: int, protected: Optional[np.ndarray] = None) -> int:
        """Dry probe: how many of the DIG_W x 3 cells around (cx, cy) a dig there would carve (solid and unprotected)."""
        m = self.terrain()
        y0, y1 = max(0, cy - 1), min(SIM_H, cy + 2)
        x0, x1 = max(0, cx - DIG_W // 2), min(SIM_W, cx + DIG_W // 2 + 1)
        if y1 <= y0 or x1 <= x0:
            return 0
        allowed = ~m[y0:y1, x0:x1]
        if protected is not None:
            allowed = allowed & ~protected[y0:y1, x0:x1]
        return int(allowed.sum())

    def dig(self, key: str, cx: int, cy: int, protected: Optional[np.ndarray] = None, cap: int = DIG_CAP,
            radius: int = 8) -> Tuple[int, str]:
        """Carve a DIG_W x 3 pocket around (cx, cy) if inside the digger's own `radius` (8 sim px; the scene passes more
        for a pip standing on a platform, whose footing is protected). 5 wide = 20 px on screen, the legibility floor
        (fix round 1: a 3x3 hole read as an 8-12 px smudge). Returns (cells, reason)."""
        p = self.pip(key)
        if p is None:
            return 0, "no pip"
        if int(p.get("digs") or 0) >= cap:
            return 0, "dig cap reached tonight"
        px, py = p.get("x"), p.get("y")
        if px is not None and py is not None and (abs(int(px) - cx) > radius or abs(int(py) - cy) > radius):
            return 0, "too far from your pip"
        m = self.terrain().copy()
        y0, y1 = max(0, cy - 1), min(SIM_H, cy + 2)
        x0, x1 = max(0, cx - DIG_W // 2), min(SIM_W, cx + DIG_W // 2 + 1)
        region = m[y0:y1, x0:x1]
        allowed = ~region
        if protected is not None:
            allowed &= ~protected[y0:y1, x0:x1]
        n = int(allowed.sum())
        if n == 0:
            return 0, "nothing to dig there"
        region[allowed] = True
        self.set_terrain(m)
        p["digs"] = int(p.get("digs") or 0) + n
        board = self.data["world"]["board"]
        dug = board.setdefault("dug", {})
        dug[key] = int(dug.get(key) or 0) + n
        self.dirty = True
        return n, "ok"

    @property
    def moss(self) -> List[Dict]:
        return self.data["world"].setdefault("moss", [])

    def plant_moss(self, key: str, x: int, y: int, t: float) -> Optional[Dict]:
        p = self.pip(key)
        if p is None:
            return None
        if self.schema >= 2:                     # the cave verb on a LONGGRASS document plants a flower mark instead
            m, _ = self.land.add_mark("flower", x, y, key, t)
            return m
        entry = {"x": int(x), "y": int(y), "planter": key, "ts": _iso(t), "size": 0}
        self.moss.append(entry)
        p["moss_planted"] = int(p.get("moss_planted") or 0) + 1
        self.dirty = True
        return entry

    def grow_moss(self, now: float) -> None:
        """size 0-3 over 10 min of stream time since planting (then lit forever)."""
        changed = False
        for m in self.moss:
            t0 = iso_to_epoch(m.get("ts"))
            if t0 is None:
                continue
            size = min(3, int((now - t0) / 200.0))
            if size != int(m.get("size") or 0):
                m["size"] = size
                changed = True
        if changed:
            self.dirty = True

    # ------------------------------------------------------------------ milestones, logs
    def milestone_check(self) -> Optional[int]:
        """The first milestone <= hatched_ever not yet recorded, or None. Recording is the caller's (keeper's) job
        via mark_milestone()."""
        n = self.hatched_ever
        reached = self.data["world"].setdefault("milestones_reached", [])
        for m in self.data["world"].get("milestones") or MILESTONES:
            if n >= m and m not in reached:
                return m
        return None

    def mark_milestone(self, m: int, by: Optional[str], t: float) -> None:
        reached = self.data["world"].setdefault("milestones_reached", [])
        if m not in reached:
            reached.append(m)
            self.data["world"].setdefault("event_log", []).append({"ts": _iso(t), "text": "milestone %d" % m, "by": by})
            self.dirty = True

    def woke(self, key: str, t: float) -> None:
        log = self.data["world"].setdefault("woke_log", [])
        log.append({"name": key, "ts": _iso(t)})
        if len(log) > 100:
            del log[:-100]
        self.dirty = True

    def visit(self, key: str, t: float) -> None:
        v = self.data["world"].setdefault("visits", [])
        if v and v[-1].get("name") == key:
            v[-1]["ts"] = _iso(t)
        else:
            v.append({"name": key, "ts": _iso(t)})
        if len(v) > 50:
            del v[:-50]
        self.dirty = True

    def log_event(self, text: str, t: float) -> None:
        ev = self.data["world"].setdefault("event_log", [])
        ev.append({"ts": _iso(t), "text": text})
        if len(ev) > EVENT_LOG_MAX:
            del ev[:-EVENT_LOG_MAX]
        self.dirty = True

    # ------------------------------------------------------------------ quarantine (WORLD.md 1, 11: no fake names, ever)
    def quarantine(self, key: str, now: float, reason: str = "no chat.jsonl record") -> bool:
        """Move a pip record OUT of `pips` into `quarantine` (kept for audit, never placed, never counted, never drawn).
        Used at boot for world.json rows with no chatter in chat.jsonl and by the HonestyMonitor's enforce path."""
        key = (key or "").lower()
        land_rec = self.land.purge_owner(key) if (self.schema >= 2 and key in self.data["pips"]) else None
        p = self.data["pips"].pop(key, None)
        if p is None:
            return False
        self.data.setdefault("quarantine", {})[key] = {"record": p, "reason": reason, "ts": _iso(now), "land": land_rec}
        if self.schema < 2:
            self.data["world"]["moss"] = [m for m in self.moss if m.get("planter") != key]
        self.data["world"]["hatched_ever"] = self.hatched_ever
        self.dirty = True
        return True

    def quarantine_orphans(self, now: float, chat_names: Optional[Set[str]]) -> List[str]:
        """Every real pip whose name_lower is not a chatter in chat.jsonl (the same scan honesty.py uses) goes to
        quarantine. `chat_names` None = the file could not be read: unverifiable, nothing moves. One activity line."""
        if chat_names is None:
            return []
        moved = [k for k, p in list(self.data["pips"].items()) if not p.get("_test") and k not in chat_names]
        for k in moved:
            self.quarantine(k, now)
        if moved:
            line = "quarantined %d world.json pip(s) with no chat.jsonl record: %s" % (len(moved), ", ".join(sorted(moved)[:5]))
            self.log(line)
            self._activity(line, now)
        return moved

    def _activity(self, text: str, now: float) -> None:
        try:
            path = run_path(self.run_dir, "ACTIVITY_FILE", "activity.jsonl")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": epoch_to_iso(now, ms=False), "actor": "world", "text": text}) + "\n")
        except Exception:
            pass

    # ------------------------------------------------------------------ chat.jsonl recompute
    def recompute_from_chat(self, now: float, session_id: Optional[str] = None, max_bytes: int = 64 * 1024 * 1024) -> Dict[str, int]:
        """Walk chat.jsonl from the stored cursor: every distinct real chatter gets a pip record (born at their first
        record), every (session, owner) pair is added once. Idempotent: running it twice adds nothing (014.2).
        Records are stamped with the session that was live at their time; older history is bucketed by 45-min gaps."""
        out = {"records": 0, "new_pips": 0, "pairs": 0, "skipped": 0}
        cur = self.data.setdefault("cursor", {"chat_jsonl_offset": 0, "last_id": None})
        try:
            size = os.path.getsize(self.chat_path)
        except OSError:
            return out
        offset = int(cur.get("chat_jsonl_offset") or 0)
        if offset > size:                     # truncated / rotated: start over (idempotent anyway)
            offset = 0
        if size - offset > max_bytes:
            offset = size - max_bytes
        seen_ids: Set[str] = set()
        recs: List[Dict] = []
        try:
            with open(self.chat_path, "rb") as fh:
                fh.seek(offset)
                data = fh.read(size - offset)
        except OSError:
            return out
        last_nl = data.rfind(b"\n")
        if last_nl < 0:
            self._quarantine_scan(now, out)       # an existing but empty chat.jsonl: nobody chatted, so nobody is a pip
            return out
        for line in data[: last_nl + 1].splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                m = normalise_chat(json.loads(line.decode("utf-8", "replace")))
            except Exception:
                out["skipped"] += 1
                continue
            if m is None or m["id"] in seen_ids or not m.get("name") or m.get("t") is None:
                out["skipped"] += 1
                continue
            seen_ids.add(m["id"])
            if m.get("type") not in (None, "message"):
                out["skipped"] += 1               # webhook test / system lines never create a pip (WORLD.md 11.9)
                continue
            recs.append(m)
        recs.sort(key=lambda r: r["t"])
        hist_sid, prev_t = None, None
        cur_sid = session_id or self.session_id
        cur_start = None
        for s in self.data.get("sessions", []):
            if s.get("id") == cur_sid:
                cur_start = iso_to_epoch(s.get("started_ts"))
        for m in recs:
            key = m["name"].lower()
            if key in self.data.get("banished", {}):
                continue
            t = float(m["t"])
            if cur_sid and cur_start is not None and t >= cur_start - 60.0:
                sid = cur_sid
            else:
                sid = None
                for s in self.data.get("sessions", []):
                    a, b = iso_to_epoch(s.get("started_ts")), iso_to_epoch(s.get("last_ts"))
                    if a is not None and b is not None and a - 60.0 <= t <= b + HIST_GAP_S:
                        sid = str(s.get("id"))
                        break
                if sid is None:
                    if hist_sid is None or (prev_t is not None and t - prev_t > HIST_GAP_S):
                        hist_sid = "hist-" + _dt.datetime.fromtimestamp(t, tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M")
                    sid = hist_sid
            prev_t = t
            b = self.builders.get(key) or {}
            p, created = self.ensure_pip(key, b.get("name") or m["name"], None, self.builder_n(key), t)
            if created:
                out["new_pips"] += 1
                p["state"] = "asleep"
                if b.get("first_seen"):
                    p["first_seen_ts"] = b["first_seen"]
            if self.add_session(p, sid):
                out["pairs"] += 1
            if not p.get("last_seen_ts") or (iso_to_epoch(p["last_seen_ts"]) or 0) < t:
                p["last_seen_ts"] = _iso(t)
            out["records"] += 1
            cur["last_id"] = m["id"]
        cur["chat_jsonl_offset"] = offset + last_nl + 1
        self._quarantine_scan(now, out)
        self.data["world"]["hatched_ever"] = self.hatched_ever
        self.dirty = True
        return out

    def _quarantine_scan(self, now: float, out: Dict[str, int]) -> None:
        try:
            from stream.world.honesty import chat_names as _chat_names
            out["quarantined"] = len(self.quarantine_orphans(now, _chat_names(self.chat_path)))
        except Exception as e:
            self.log("quarantine scan failed (%r): nothing moved" % (e,))

    # ------------------------------------------------------------------ banish
    def banish(self, key: str, t: float) -> bool:
        """`!banish`: the pip, its camp, field, marks and stones leave the land; the audit record keeps them all."""
        key = (key or "").lower()
        land_rec = self.land.purge_owner(key) if (self.schema >= 2 and key in self.data["pips"]) else None
        p = self.data["pips"].pop(key, None)
        if p is None:
            return False
        p["banished_ts"] = _iso(t)
        if land_rec is not None:
            p["_banished_land"] = land_rec
        self.data.setdefault("banished", {})[key] = p
        if self.schema < 2:
            self.data["world"]["moss"] = [m for m in self.moss if m.get("planter") != key]
        self.data["world"]["hatched_ever"] = self.hatched_ever
        self.dirty = True
        return True

    def unbanish(self, key: str) -> bool:
        key = (key or "").lower()
        p = self.data.get("banished", {}).pop(key, None)
        if p is None:
            return False
        p.pop("banished_ts", None)
        land_rec = p.pop("_banished_land", None)
        self.data["pips"][key] = p
        if self.schema >= 2 and land_rec:
            self.land.restore_owner(key, land_rec)
        self.data["world"]["hatched_ever"] = self.hatched_ever
        self.dirty = True
        return True

    # ------------------------------------------------------------------ schema 1 -> 2 migration (OPENWORLD 5.4)
    def migrate_v2(self, now: Optional[float] = None, moot_xy: Optional[Tuple[float, float]] = None,
                   passable: Optional[np.ndarray] = None, water: Optional[np.ndarray] = None,
                   dry_run: bool = False, write_bak: bool = True) -> Dict[str, Any]:
        """Migrate the loaded schema-1 document to schema 2 ON A COPY, verify the guard (every pre-migration pip's
        identity byte-identical, pip count equal, every mark owned by a pip), then adopt the copy. On a guard failure
        nothing changes: `schema` stays 1, `migration_ok` is False and the report lists the problems, so the scene
        refuses to boot and the world panel keeps rendering the last good frame. With `write_bak` the pre-migration
        file is copied to `world.json.bak-v1-<stamp>` first (never pruned). `dry_run` verifies without adopting."""
        if self.schema >= 2:
            self.migration = {"ok": True, "skipped": True, "reason": "already schema %d" % self.schema}
            self.migration_ok = True
            return self.migration
        old = self.data
        moot = tuple(moot_xy) if moot_xy else (self._moot or tuple(old["world"].get("moot") or LAND.DEFAULT_MOOT))
        new, report = migrate_v2_doc(old, moot=moot, passable=passable, water=water, log=self.log)
        ok, problems = verify_migration(old, new)
        report.update({"ok": ok, "problems": problems, "dry_run": bool(dry_run)})
        if ok and not dry_run:
            if write_bak and os.path.exists(self.path):
                stamp_t = now if now is not None else (iso_to_epoch(old.get("updated_ts")) or 0.0)
                stamp = _dt.datetime.fromtimestamp(stamp_t, tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%S") if stamp_t else "unknown"
                bak = self.path + ".bak-v1-" + stamp
                try:
                    if not os.path.exists(bak):
                        with open(self.path, "rb") as src, open(bak + ".tmp", "wb") as dst:
                            dst.write(src.read())
                        os.replace(bak + ".tmp", bak)
                    report["bak"] = bak
                except Exception as e:
                    self.log("pre-migration backup failed (%r): NOT migrating" % (e,))
                    report.update({"ok": False, "problems": problems + ["pre-migration backup failed: %r" % (e,)]})
                    self.migration, self.migration_ok = report, False
                    return report
            self.data = new
            self._moot = moot
            self._terrain = None
            self._land = None
            self.dirty = True
            self.log("world.json migrated schema 1 -> 2: %d pips, %d camps, %d flowers from moss, %d nests bonded" % (
                len(new["pips"]), report.get("camps", 0), report.get("flowers", 0), report.get("nests", 0)))
        elif not ok:
            self.log("world.json migration REFUSED (%d problem%s): %s" % (len(problems), "" if len(problems) == 1 else "s", "; ".join(problems[:5])))
        self.migration, self.migration_ok = report, ok
        return report


# ---------------------------------------------------------------------------- terrain defaults (WORLD.md 6.1)
CEIL_ROWS = (0, 13)              # rock rows 0-13
MOUTH_X = (236, 268)             # cave mouth columns (open to the sky) rows 0-13
VOID_ROWS = (14, 87)             # cavern
FLOOR_ROWS = (88, 91)
SOIL_ROWS = (92, 109)
LEDGE_X = (0, 40)                # solid until the first keeper carve
PLATFORMS = ((40, 24), (160, 24), (280, 24))   # (x, w), 3 tall, top row PLATFORM_TOP
PLATFORM_TOP = 85
PLATFORM_LETTERS = ("A", "B", "C")
BURROW_SLOTS = 16                # 14x8 each along the soil
BURROW_W, BURROW_H = 14, 8
LANTERN_X = 300


TERRAIN_SEED = 41370704          # the default cavern is deterministic (terrain persists in world.json; only speckle is per session)
TERRAIN_VER = 2                  # 2: stalactites 4-8 px, floor rubble 1-3 px, torn mouth flanks, Ledge outcrops (fix round 1).
                                 # A saved terrain of an older version is upgraded in WorldState.terrain(): the new rock lands,
                                 # every cell a real person dug stays carved.
STALACTITE_N = (3, 5)
STALACTITE_DEPTH = (4, 8)
STALACTITE_GAP = (6, 20)


def burrow_box(i: int) -> Tuple[int, int, int, int]:
    """(x, y, w, h) of burrow slot i in sim px: 16 slots along the soil band, UNEVEN on purpose (widths 12-16, staggered
    x, y offset 0-2) so the lower wall reads as dug earth, not a row of UI cells. Deterministic per slot."""
    i = int(i) % BURROW_SLOTS
    w = 12 + (i * 5) % 5                       # 12..16
    x = 3 + i * 20 + (i * 7) % 3               # stagger 0..2
    x = min(x, SIM_W - w - 1)
    y = (96 if i % 2 == 0 else 100) + (i * 3) % 3   # offset 0..2; y + 8 <= 110
    return (x, y, w, BURROW_H)


def _runs(rng, x0: int, x1: int, lo: int, hi: int):
    """Yield (a, b) column runs of length lo..hi covering x0..x1."""
    x = x0
    while x < x1:
        n = int(rng.integers(lo, hi + 1))
        yield x, min(x1, x + n)
        x += n


def mouth_span(r: int, ver: int = TERRAIN_VER) -> Tuple[int, int]:
    """Open columns [a, b) of cave-mouth row r. v1: a 32-wide slot with a 0-3 px saw-tooth. v2: a TORN opening that
    flares 2-4 px per step toward the cavern (rows 0-13), so at tile scale it reads as a break in the rock, not a window."""
    if ver < 2:
        return MOUTH_X[0] + (r * 7) % 4, MOUTH_X[1] - (r * 5 + 2) % 4
    step = r // 2                                             # a new step every 2 rows
    flare_l = (step * 3 + (r * 7) % 3) // 2                   # 0 .. ~10 px wider at the bottom
    flare_r = (step * 2 + (r * 5 + 2) % 4) // 2
    a = MOUTH_X[0] + 3 - flare_l + ((r * 7) % 3 if r % 2 else 0)
    b = MOUTH_X[1] - 3 + flare_r - ((r * 5) % 3 if r % 2 == 0 else 0)
    return max(MOUTH_X[0] - 6, a), min(MOUTH_X[1] + 6, b)


def default_terrain(ver: int = TERRAIN_VER) -> np.ndarray:
    """True = carved (void). The cavern minus the Ledge, the mouth, 16 arched burrow recesses, plus a stepped
    ceiling (stalactite steps of 0-3 px hanging into rows 14-16) and a stepped floor (stalagmite steps of 0-2 px rising
    into rows 86-87), in seeded runs of 6-20 columns. v2 (TERRAIN_VER) adds 3-5 stalactites hanging 4-8 px into the
    void at 6-20 column spacing with matching 1-3 px rubble bumps on the floor line, a torn flared mouth, and two
    rock outcrops on the Ledge face, so ceiling, floor and wall are visibly irregular at tile scale (art-rules 4).
    The mouth pillars, the lantern column and the platform footings are left flat; protected cells (dig) are never
    carved here."""
    m = np.zeros((SIM_H, SIM_W), dtype=bool)
    m[VOID_ROWS[0]:VOID_ROWS[1] + 1, LEDGE_X[1]:SIM_W] = True
    for r in range(0, 14):                                    # the mouth
        a, b = mouth_span(r, ver)
        m[r, a:b] = True
    rng = np.random.default_rng(TERRAIN_SEED)
    keep_flat = np.zeros(SIM_W, dtype=bool)                   # columns whose ceiling / floor stay straight
    keep_flat[MOUTH_X[0] - 6:MOUTH_X[1] + 6] = True
    keep_flat[LANTERN_X - 2:LANTERN_X + 3] = True
    for a, b in _runs(rng, LEDGE_X[1], SIM_W, 6, 20):         # ceiling: rock steps hang 0-3 px into the void
        k = int(rng.integers(0, 4))
        if k:
            cols = np.arange(a, b)
            cols = cols[~keep_flat[cols]]
            m[VOID_ROWS[0]:VOID_ROWS[0] + k, cols] = False
    plat_flat = keep_flat.copy()
    for px, pw in PLATFORMS:
        plat_flat[max(0, px - 3):px + pw + 3] = True
    for a, b in _runs(rng, LEDGE_X[1], SIM_W, 6, 20):         # floor: stalagmite steps rise 0-2 px behind the feet row
        k = int(rng.integers(0, 3))
        if k:
            cols = np.arange(a, b)
            cols = cols[~plat_flat[cols]]
            m[FLOOR_ROWS[0] - k:FLOOR_ROWS[0], cols] = False
    for i in range(BURROW_SLOTS):                             # arched recess: a 1 px step arch, angular
        x, y, w, h = burrow_box(i)
        m[y, x + 2:x + w - 2] = True
        m[y + 1, x + 1:x + w - 1] = True
        m[y + 2:y + h, x:x + w] = True
    if ver >= 2:
        rng2 = np.random.default_rng(TERRAIN_SEED ^ 0x5A17)
        n = STALACTITE_N[1]                                   # five: one per ~50 columns of ceiling
        x = LEDGE_X[1] + 6
        placed = 0
        span = (SIM_W - 24 - x) // max(1, n)                  # spread across the whole ceiling, jittered by 6-20 columns
        while placed < n and x < SIM_W - 24:
            x += span - 10 + int(rng2.integers(STALACTITE_GAP[0], STALACTITE_GAP[1] + 1))
            while x < SIM_W - 24 and keep_flat[max(0, x - 3):x + 4].any():
                x += 4                                        # step past the mouth / lantern columns, never skip a spike
            if x >= SIM_W - 24:
                break
            depth = int(rng2.integers(STALACTITE_DEPTH[0], STALACTITE_DEPTH[1] + 1))
            wid = 3 if depth <= 5 else 4
            for k in range(depth):                            # a tapering spike: wide at the ceiling, 1 px at the tip
                half = max(0, int(round((wid / 2.0) * (1.0 - k / float(depth)))))
                a, b = x - half, x + half + 1
                m[VOID_ROWS[0] + k, a:b] = False
            bump = int(rng2.integers(1, 4))                    # matching rubble on the floor line under it
            bx = x + int(rng2.integers(-3, 4))
            if not plat_flat[max(0, bx - 2):bx + 3].any():
                for k in range(bump):
                    half = max(0, bump - 1 - k)
                    m[FLOOR_ROWS[0] - 1 - k, bx - half:bx + half + 1] = False
            placed += 1
        for bx in (76, 132, 196, 236, 262):                   # loose rubble on the floor line between the platforms
            if plat_flat[max(0, bx - 2):bx + 3].any():
                continue
            bump = 1 + (bx // 20) % 3                          # 1-3 px
            for k in range(bump):
                half = max(0, bump - 1 - k)
                m[FLOOR_ROWS[0] - 1 - k, bx - half:bx + half + 1] = False
        for (y0, rows, out) in ((VOID_ROWS[0] + 9, 5, 3), (VOID_ROWS[0] + 38, 7, 4), (VOID_ROWS[0] + 60, 4, 2)):
            for k in range(rows):                             # Ledge face outcrops: the left wall is torn rock, not a ruler
                d = out - (abs(k - rows // 2) * out) // max(1, rows // 2 + 1)
                m[y0 + k, LEDGE_X[1]:LEDGE_X[1] + max(1, d)] = False
    return m


def upgrade_terrain(saved: np.ndarray, saved_ver: int) -> np.ndarray:
    """A persisted terrain of an older default: apply the new rock features while keeping every cell a real person dug
    (carved in `saved` but solid in the OLD default)."""
    old = default_terrain(saved_ver)
    new = default_terrain(TERRAIN_VER)
    dug = saved & ~old
    return new | dug


def protected_mask() -> np.ndarray:
    """Cells `dig` may never carve: floor under the platforms, the cave-mouth pillar rows, the lantern column."""
    p = np.zeros((SIM_H, SIM_W), dtype=bool)
    for x, w in PLATFORMS:
        p[PLATFORM_TOP:SOIL_ROWS[0] + 2, x - 1:x + w + 1] = True
    p[0:14, MOUTH_X[0] - 6:MOUTH_X[1] + 6] = True
    p[0:14, LANTERN_X - 2:LANTERN_X + 3] = True
    return p


# ---------------------------------------------------------------------------- schema 1 -> 2 (OPENWORLD.md 5.4), pure
def _ident(v: Any) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def migrate_v2_doc(old: Dict[str, Any], moot: Tuple[float, float] = LAND.DEFAULT_MOOT, passable: Optional[np.ndarray] = None,
                   water: Optional[np.ndarray] = None, log: Optional[Callable[[str], None]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A NEW schema-2 document from a schema-1 one; `old` is never touched (deep-copied first). Rules 5.4: `burrow` ->
    `camp` at a position hashed from the name inside the Steading ring, tier from `sessions_seen`; each `moss` row ->
    a `flower` mark credited to its planter beside that camp; `nests` -> bonded camps adjacent; `terrain_b64` dropped;
    `digs` kept as history. Identity fields are copied, never rebuilt. Returns (new_doc, report)."""
    log = log or (lambda m: None)
    src = copy.deepcopy(old)
    report: Dict[str, Any] = {"from_schema": int(src.get("schema") or 1), "to_schema": SCHEMA, "pips": 0, "camps": 0,
                              "flowers": 0, "flowers_dropped": 0, "nests": 0, "nests_dropped": 0}
    new = _default_data(SCHEMA)
    for k in ("updated_ts", "cursor", "sessions", "banished", "quarantine"):
        if k in src:
            new[k] = src[k]
    w1 = src.get("world") or {}
    w2 = new["world"]
    for k in ("milestones", "milestones_reached", "hatched_ever", "woke_log", "visits", "board", "last_board", "event_log"):
        if k in w1:
            w2[k] = w1[k]
    w2["moot"] = [int(round(moot[0])), int(round(moot[1]))]
    w2["history"] = {"v1": {"chambers": w1.get("chambers") or [], "nests": w1.get("nests") or [],
                            "moss_rows": len(w1.get("moss") or []), "terrain_ver": w1.get("terrain_ver")}}

    # pips: identity copied byte-for-byte (deepcopy), burrow -> camp, digs / moss_planted -> history
    taken: List[Tuple[float, float]] = []
    pips2: Dict[str, Dict[str, Any]] = {}
    for key in sorted(src.get("pips") or {}):          # sorted: camp spots are deterministic across runs
        p = src["pips"][key]
        q = copy.deepcopy(p)
        q["history"] = {"digs": p.get("digs", 0), "burrow": p.get("burrow"), "moss_planted": p.get("moss_planted", 0),
                        "x_v1": p.get("x"), "y_v1": p.get("y")}
        for f in ("digs", "burrow", "moss_planted"):
            q.pop(f, None)
        q.update({k: v for k, v in _v2_pip_fields(key).items() if k != "history"})
        hatched = p.get("state") not in ("seed", "hatching")
        tier = LAND.camp_tier_for_sessions(p.get("sessions_seen") or 0)
        if hatched and tier >= 0:                      # they did sleep here: a camp where their nights were
            x, y = LAND.hashed_camp_spot(key, moot, taken, passable, water)
            taken.append((x, y))
            q["camp"] = {"x": x, "y": y, "tier": tier, "built_ts": p.get("first_seen_ts") or p.get("born_ts"),
                         "nights": list(p.get("session_ids") or [])}
            q["home"] = [x, y]
            q["x"], q["y"] = x, y
            report["camps"] += 1
        else:
            q["camp"], q["home"], q["x"], q["y"] = None, None, None, None
        if q.get("state") == "voting":
            q["state"], q["vote"] = "asleep", None
        pips2[key] = q
        report["pips"] += 1
    new["pips"] = pips2

    # nests -> bonded camps adjacent (the second parent's camp moves within 6-8 cells of the first)
    camp_of = lambda k: (pips2.get(k) or {}).get("camp")   # noqa: E731
    for nest in w1.get("nests") or []:
        parents = [str(x).lower() for x in (nest.get("parents") or [])][:2]
        if len(parents) == 2 and camp_of(parents[0]) and camp_of(parents[1]):
            a, b = camp_of(parents[0]), camp_of(parents[1])
            others = [(c["x"], c["y"]) for k, c in ((k, camp_of(k)) for k in pips2) if c and k != parents[1]]
            bx, by = LAND.spot_beside(parents[1], a["x"], a["y"], 7, others, passable, water, rmin=6, rmax=8, gap=LAND.CAMP_GAP_BONDED)
            b["x"], b["y"] = bx, by
            pips2[parents[1]]["home"] = [bx, by]
            pips2[parents[1]]["x"], pips2[parents[1]]["y"] = bx, by
            report["nests"] += 1
        else:
            report["nests_dropped"] += 1

    # moss -> flower marks beside the planter's camp (a real mark keeps its owner; an ownerless row is dropped)
    marks: List[Dict[str, Any]] = []
    taken_marks: List[Tuple[float, float]] = []
    per_owner: Dict[str, int] = {}
    for m in w1.get("moss") or []:
        owner = str(m.get("planter") or "").lower()
        q = pips2.get(owner)
        camp = q.get("camp") if q else None
        if not q or not camp:
            report["flowers_dropped"] += 1
            continue
        i = per_owner.get(owner, 0)
        per_owner[owner] = i + 1
        fx, fy = LAND.spot_beside(owner, camp["x"], camp["y"], i, taken_marks + taken, passable, water)
        taken_marks.append((fx, fy))
        w2["mark_seq"] = int(w2.get("mark_seq") or 0) + 1
        marks.append({"id": "flower-%d" % w2["mark_seq"], "type": "flower", "x": fx, "y": fy, "owner": owner,
                      "ts": m.get("ts"), "extra": {"from": "moss", "size": m.get("size"), "x_v1": m.get("x"), "y_v1": m.get("y")}})
        q.setdefault("marks_planted", {"flower": 0, "tree": 0, "reed": 0, "stone": 0})["flower"] += 1
        report["flowers"] += 1
    w2["marks"] = marks
    w2["fields"] = []
    w2["hatched_ever"] = sum(1 for p in pips2.values() if not p.get("_test") and p.get("state") not in ("seed", "hatching"))
    new["schema"] = SCHEMA
    return new, report


def verify_migration(old: Dict[str, Any], new: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """The 5.4 guard: every pre-migration pip's identity (name, n, colour_idx, genome incl. salt, born_ts) is
    byte-identical in the new document, the pip count matches, the key sets match, banished / quarantine keys are kept,
    every mark / camp resolves to a pip and lies inside the map. (ok, problems)."""
    problems: List[str] = []
    op, np_ = old.get("pips") or {}, new.get("pips") or {}
    if len(op) != len(np_):
        problems.append("pip count %d -> %d" % (len(op), len(np_)))
    for key in op:
        if key not in np_:
            problems.append("pip %r missing after migration" % key)
            continue
        for f in IDENTITY_FIELDS:
            if _ident(op[key].get(f)) != _ident(np_[key].get(f)):
                problems.append("pip %r field %r changed: %s -> %s" % (key, f, _ident(op[key].get(f)), _ident(np_[key].get(f))))
        if _ident((op[key].get("genome") or {}).get("salt")) != _ident((np_[key].get("genome") or {}).get("salt")):
            problems.append("pip %r salt changed" % key)
        for f in ("sessions_seen", "session_ids", "minutes_present", "own_messages", "last_seen_ts", "first_seen_ts", "tier"):
            if _ident(op[key].get(f)) != _ident(np_[key].get(f)):
                problems.append("pip %r record field %r changed" % (key, f))
    for key in np_:
        if key not in op:
            problems.append("pip %r appeared from nowhere" % key)
    for blk in ("banished", "quarantine"):
        if set((old.get(blk) or {}).keys()) != set((new.get(blk) or {}).keys()):
            problems.append("%s keys changed" % blk)
    if int(new.get("schema") or 0) != SCHEMA:
        problems.append("new schema is %r, not %d" % (new.get("schema"), SCHEMA))
    w2 = new.get("world") or {}
    mw, mh = int(w2.get("map_w") or LAND.MAP_W), int(w2.get("map_h") or LAND.MAP_H)
    for key, p in np_.items():
        c = p.get("camp")
        if c is not None:
            if not isinstance(c, dict) or not (0 <= int(c.get("x", -1)) < mw and 0 <= int(c.get("y", -1)) < mh):
                problems.append("pip %r camp off the map: %r" % (key, c))
            elif int(c.get("tier", -1)) not in (0, 1, 2, 3):
                problems.append("pip %r camp tier %r" % (key, c.get("tier")))
        for f in ("burrow", "digs", "moss_planted"):
            if f in p:
                problems.append("pip %r still carries schema-1 field %r" % (key, f))
    for m in w2.get("marks") or []:
        if m.get("owner") not in np_:
            problems.append("mark %r owner %r has no pip" % (m.get("id"), m.get("owner")))
        if not (0 <= int(m.get("x", -1)) < mw and 0 <= int(m.get("y", -1)) < mh):
            problems.append("mark %r off the map" % (m.get("id"),))
    for f in ("terrain_b64", "moss", "nests", "chambers"):
        if f in w2:
            problems.append("world block still carries schema-1 key %r" % f)
    seen = set()
    for key, p in np_.items():
        c = p.get("camp")
        if isinstance(c, dict):
            pos = (int(c["x"]), int(c["y"]))
            if pos in seen:
                problems.append("two camps share cell %r" % (pos,))
            seen.add(pos)
    return (not problems), problems


def migrate_copy(src_path: str, out_path: Optional[str] = None, moot: Optional[Tuple[float, float]] = None) -> Dict[str, Any]:
    """CLI helper: read `src_path` (never written), migrate, verify, optionally write the schema-2 copy to `out_path`
    (must not be a canonical live dir). Returns the report with `ok`."""
    with open(src_path, "r", encoding="utf-8") as fh:
        old = WorldState._adopt(json.load(fh))
    if int(old.get("schema") or 1) >= 2:
        return {"ok": True, "skipped": True, "reason": "source is already schema %s" % old.get("schema")}
    new, report = migrate_v2_doc(old, moot=tuple(moot) if moot else LAND.DEFAULT_MOOT)
    ok, problems = verify_migration(old, new)
    report.update({"ok": ok, "problems": problems, "src": src_path})
    if out_path:
        rp = os.path.realpath(out_path)
        canon = [os.path.realpath(os.path.expanduser(p)) for p in ("~/.local/share/kick-live/run-live", "~/.local/share/kick-live/run")]
        if any(rp.startswith(c + os.sep) or rp == c for c in canon) or os.path.realpath(src_path) == rp:
            report.update({"ok": False, "problems": problems + ["refusing to write into a live run dir or over the source"]})
            return report
        if ok:
            os.makedirs(os.path.dirname(rp) or ".", exist_ok=True)
            write_state_atomic(rp, new)
            report["out"] = rp
    return report


def _fixture_v1(now: float) -> Dict[str, Any]:
    """A schema-1 document like the live one: two sleepers in burrows, one moss row each, a nest, a quarantined orphan."""
    d = _default_data(SCHEMA_V1)
    for i, (key, name, n, sess) in enumerate((("atleastonce", "atleastonce", 1, 4), ("sami", "Sami", 2, 2), ("kai_dnb", "Kai_DnB", 3, 1))):
        g, _ = P.resolve_genome(key, 0)
        p = _default_pip(key, name, name, n, now - 86400 * (3 - i), g)
        p.update({"state": "asleep", "x": 150 + 60 * i, "y": 107, "burrow": 7 + i, "sessions_seen": sess,
                  "session_ids": ["hist-%d" % k for k in range(sess)], "digs": 12 * i, "moss_planted": 1,
                  "tier": 2 if sess >= 3 else 0, "words": {"plant": 3}, "bonds": {}})
        d["pips"][key] = p
    d["pips"]["atleastonce"]["bonds"] = {"sami": 3}
    d["pips"]["sami"]["bonds"] = {"atleastonce": 4}
    d["world"]["moss"] = [{"x": 140, "y": 90, "planter": "sami", "ts": _iso(now - 3600), "size": 2},
                          {"x": 200, "y": 90, "planter": "atleastonce", "ts": _iso(now - 7200), "size": 3},
                          {"x": 210, "y": 90, "planter": "nobody-here", "ts": _iso(now - 7200), "size": 1}]
    d["world"]["nests"] = [{"x": 180, "y": 92, "parents": ["atleastonce", "sami"], "built_ts": _iso(now - 600), "hatched": []}]
    d["world"]["terrain_b64"] = base64.b64encode(np.packbits(default_terrain().reshape(-1))).decode("ascii")
    d["sessions"] = [{"id": "hist-%d" % k, "started_ts": _iso(now - 86400 * (4 - k)), "last_ts": _iso(now - 86400 * (4 - k) + 3600)} for k in range(4)]
    d["quarantine"] = {"phantom": {"record": {"name": "phantom"}, "reason": "no chat.jsonl record", "ts": _iso(now)}}
    return d


def _self_test() -> bool:
    """v1 -> v2 on the fixture and on a broken copy (guard must refuse), land operations, wear round trip, save / load."""
    import tempfile
    ok = True
    notes: List[str] = []

    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
        notes.append(("PASS " if cond else "FAIL ") + msg)

    now = 1_790_000_000.0
    run_dir = tempfile.mkdtemp(prefix="lg-state-", dir="/tmp")
    old = _fixture_v1(now)
    write_state_atomic(os.path.join(run_dir, "world.json"), old)
    with open(os.path.join(run_dir, "chat.jsonl"), "w") as fh:
        for k in ("atleastonce", "Sami", "Kai_DnB"):
            fh.write(json.dumps({"id": "id-" + k, "username": k, "content": "hi", "ts": _iso(now - 100)}) + "\n")

    # 1. a schema-1 WorldState still reads and writes schema 1 (the cave's rollback contract)
    ws1 = WorldState(run_dir, log=lambda m: None)
    check(ws1.schema == 1 and ws1.land is None and "terrain_b64" in ws1.data["world"], "schema=None keeps a v1 file at schema 1")
    ws1.dirty = True
    ws1.save(now, force=True)
    with open(ws1.path) as fh:
        check(json.load(fh)["schema"] == 1, "v1 save() writes schema 1 (no silent upgrade)")

    # 2. schema=2 migrates under the guard
    ws = WorldState(run_dir, log=lambda m: None, schema=2, now=now)
    rep = ws.migration or {}
    check(ws.schema == 2 and ws.migration_ok, "schema=2 migrates a v1 file: ok=%s problems=%s" % (rep.get("ok"), rep.get("problems")))
    check(rep.get("camps") == 3 and rep.get("flowers") == 2 and rep.get("flowers_dropped") == 1 and rep.get("nests") == 1,
          "report camps=%s flowers=%s dropped=%s nests=%s" % (rep.get("camps"), rep.get("flowers"), rep.get("flowers_dropped"), rep.get("nests")))
    check(bool(rep.get("bak")) and os.path.exists(rep.get("bak") or ""), "pre-migration copy written: %s" % os.path.basename(rep.get("bak") or "?"))
    for key in old["pips"]:
        for f in IDENTITY_FIELDS:
            check(_ident(old["pips"][key][f]) == _ident(ws.pips[key][f]), "identity %s.%s byte-identical" % (key, f))
    check(ws.pips["atleastonce"]["camp"]["tier"] == 1 and ws.pips["sami"]["camp"]["tier"] == 1 and ws.pips["kai_dnb"]["camp"]["tier"] == 0,
          "camp tiers from sessions_seen 4/2/1 -> tent/tent/hollow (%s)" % [ws.pips[k]["camp"]["tier"] for k in ("atleastonce", "sami", "kai_dnb")])
    a, b = ws.pips["atleastonce"]["camp"], ws.pips["sami"]["camp"]
    d_ab = ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5
    check(6 <= d_ab <= 9, "nest -> bonded camps adjacent (%.1f cells apart)" % d_ab)
    check(ws.pips["atleastonce"]["history"]["digs"] == 0 and ws.pips["kai_dnb"]["history"]["digs"] == 24 and "burrow" not in ws.pips["sami"],
          "digs kept as history, burrow dropped")
    check(all(m["owner"] in ws.pips for m in ws.land.marks), "every migrated flower has a real owner")
    check(ws.pips["sami"]["colour"] and ws.pips["sami"]["colour"].startswith("#"), "colour from the art genome (%s)" % ws.pips["sami"]["colour"])
    check(not ws.land.provenance_violations(), "no provenance violations after migration")

    # 3. the guard refuses a tampered migration (a pip lost / an identity changed)
    bad_new, _ = migrate_v2_doc(old)
    bad_new["pips"]["sami"]["genome"]["salt"] = 1
    g_ok, g_problems = verify_migration(old, bad_new)
    check(not g_ok and any("salt" in p or "genome" in p for p in g_problems), "guard refuses a changed salt: %s" % g_problems[:1])
    bad_new2, _ = migrate_v2_doc(old)
    del bad_new2["pips"]["kai_dnb"]
    g_ok2, g_problems2 = verify_migration(old, bad_new2)
    check(not g_ok2 and any("count" in p for p in g_problems2), "guard refuses a lost pip: %s" % g_problems2[:1])

    # 4. land operations: wear never decrements, marks need owners, camps obey the gap, stones and the ladder
    land = ws.land
    cx, cy = ws.pips["sami"]["camp"]["x"], ws.pips["sami"]["camp"]["y"]
    added = land.step("sami", cx + 20, cy)
    check(added == 8 + 4 * 2, "step adds 8 + 4x2 (%d)" % added)
    check(land.step("test-pip-01", cx, cy) == 0 and land.step("nobody", cx, cy) == 0, "test / unknown pips never write wear")
    for _ in range(40):
        land.step("sami", cx + 20, cy)
    check(land.wear_at(cx + 20, cy) == 255 and land.trail_tier(cx + 20, cy) == 3, "wear caps at 255 -> road tier 3")
    frac = land.walked_fraction()
    # five worn cells (centre + 4 neighbours) dilated by 24 = a 51x51 square minus its 4 corners
    check(0 < frac < 0.02 and land.walked_cells() == 51 * 51 - 4, "walked fraction from len(): %.4f (%d cells)" % (frac, land.walked_cells()))
    mx, my = land.moot[0] + 120, land.moot[1] + 60           # well off the green and every camp
    m, why = land.add_mark("flower", mx, my, "sami", now)
    check(m is not None and why == "ok", "add_mark flower ok (%s)" % why)
    m2, why2 = land.add_mark("flower", mx + 1, my, "atleastonce", now)
    check(m2 is None and "close" in why2, "a mark within 4 cells of another's is refused (%s)" % why2)
    m3, why3 = land.add_mark("flower", mx + 20, my, "ghost", now)
    check(m3 is None, "an ownerless mark is refused (%s)" % why3)
    m4, why4 = land.add_mark("flower", cx + 20, cy, "sami", now)
    check(m4 is None and "trail" in why4, "not on a trail (%s)" % why4)
    c_ok, c_why = land.camp_allowed("kai_dnb", a["x"] + 8, a["y"])
    check(not c_ok, "an unbonded camp within 12 cells is refused (%s)" % c_why)
    c_ok2, _ = land.camp_allowed("sami", a["x"] + 7, a["y"])
    check(c_ok2, "a bonded camp may sit at 6-12 cells")
    for k in ("sami", "atleastonce", "kai_dnb"):
        land.stack(k, now)
    check(land.stock == 3 and land.cairn_named() and land.ladder()["next"] == 20 and land.ladder()["stock"] == 3, "3 distinct stackers name the cairn; ladder next 20")
    f, fw = land.sow("sami", now - 8 * 86400)
    check(f is not None, "sow beside the camp (%s)" % fw)
    check(land.field_stage(f, now)[1] == "gold" and land.fields_gold(now) == 1, "a field sown 8 days ago is gold")
    h_ok, h_why = land.harvest("sami", now)
    check(h_ok and land.field_of("sami")["harvests"] == 1 and land.field_stage(land.field_of("sami"), now)[1] == "tilled", "harvest resets to tilled (%s)" % h_why)
    ver = land.bake_ver
    land.set_camp("kai_dnb", cx + 100, cy + 40, now, check=False)
    check(land.bake_ver == ver + 1, "a camp move bumps bake_ver")
    stops = land.survey_stops([{"kind": "ford", "x": 500, "y": 150}])
    check(sum(1 for s in stops if s["kind"] == "camp") == 3 and any(s["kind"] == "natural" for s in stops), "survey stops = real camps + fields + cairn + natural points (%d)" % len(stops))

    # 5. save / load round trip keeps wear, marks, camps and the schema
    land.save_camera({"x": 480.0, "y": 220.0, "zoom": 1.0, "mode": "DRIFT"})
    ws.save(now + 1, force=True)
    ws2 = WorldState(run_dir, log=lambda m: None, schema=2)
    check(ws2.schema == 2 and ws2.migration.get("skipped"), "reload of a v2 file skips the migration")
    check(ws2.land.wear_at(cx + 20, cy) == 255 and len(ws2.land.marks) == 3 and ws2.land.camera()["x"] == 480.0, "wear / marks / camera survive save + load")
    check("moss" not in ws2.data["world"] and "terrain_b64" not in ws2.data["world"], "v2 load does not resurrect moss / terrain")
    check(ws2.hatched_ever == 3, "hatched_ever = 3 real rows")

    # 6. banish removes the land marks with an audit record; unbanish restores them
    n_marks = len(ws2.land.marks)
    ws2.banish("sami", now)
    check(len(ws2.land.marks) == n_marks - 2 and ws2.land.stock == 2 and "sami" not in ws2.pips, "banish removes sami's 2 marks and stone")
    check(not ws2.land.provenance_violations(), "no violations after banish")
    ws2.unbanish("sami")
    check(len(ws2.land.marks) == n_marks and ws2.land.stock == 3 and ws2.pips["sami"]["camp"] is not None, "unbanish restores marks, stone and camp")

    # 7. a fresh run dir at schema 2 starts empty at schema 2; ensure_pip gives v2 fields; ensure_camp on first sleep
    fresh = tempfile.mkdtemp(prefix="lg-state-fresh-", dir="/tmp")
    ws3 = WorldState(fresh, log=lambda m: None, schema=2)
    check(ws3.schema == 2 and ws3.migration_ok and len(ws3.pips) == 0, "fresh schema-2 document")
    p, created = ws3.ensure_pip("newbie", "Newbie", "Newbie", 9, now)
    check(created and "camp" in p and "burrow" not in p and p["colour"], "ensure_pip creates a v2 row")
    p["state"] = "awake"
    ws3.set_pos("newbie", ws3.land.moot[0] + 30, ws3.land.moot[1] + 5, facing=(0.7, -0.7))
    check(ws3.pips["newbie"]["facing"] == [1, -1], "set_pos quantises facing to 8 directions")
    camp = ws3.ensure_camp("newbie", now, "sess-1")
    check(camp is not None and camp["tier"] == 0 and camp["nights"] == ["sess-1"], "first sleep pitches a hollow where the pip stood")
    on_green = ws3.ensure_camp("greeny", now, "sess-1")
    check(on_green is None, "ensure_camp refuses an unknown pip")

    for n in notes:
        print("[state] " + n)
    print("[state] self-test %s (%s)" % ("PASS" if ok else "FAIL", run_dir))
    return ok


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="world.json schema tools (OPENWORLD.md 5.4)")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--migrate-copy", metavar="SRC", help="read this world.json (never written), migrate 1 -> 2 in memory, verify the guard")
    ap.add_argument("--out", metavar="PATH", help="write the migrated copy here (refused inside a live run dir)")
    ap.add_argument("--moot", metavar="X,Y", help="Moot centre in cells for camp placement (default map centre)")
    args = ap.parse_args()
    rc = 0
    if args.migrate_copy:
        moot = tuple(float(v) for v in args.moot.split(",")) if args.moot else None
        r = migrate_copy(args.migrate_copy, args.out, moot)
        print(json.dumps({k: v for k, v in r.items()}, indent=1, default=str))
        rc = 0 if r.get("ok") else 2
    if args.self_test:
        rc = rc or (0 if _self_test() else 1)
    if not args.self_test and not args.migrate_copy:
        ap.print_help()
    sys.exit(rc)
