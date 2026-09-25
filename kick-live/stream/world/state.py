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

Rules: identity fields (name, n, colour_idx, genome incl. salt, born_ts) are written once and never recomputed.
Counts are never incremented on boot: `recompute_from_chat` walks chat.jsonl from the stored cursor and adds
`(session_id, name_lower)` pairs to a SET per pip, so re-ingest is idempotent (fixes 014.2). Energy never
decays while asleep or while the stream is off (WORLD.md 10): decay is applied only by the behaviour tick
for awake pips. Nothing here draws text; `display_name` is stored from the moderated record so the text
layer never needs the raw name path (014.1).
"""
from __future__ import annotations

import base64
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

SCHEMA = 1
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


def _default_data() -> Dict[str, Any]:
    return {
        "schema": SCHEMA,
        "updated_ts": None,
        "cursor": {"chat_jsonl_offset": 0, "last_id": None},
        "pips": {},
        "world": {
            "terrain_b64": None,
            "moss": [],
            "nests": [],
            "chambers": [{"name": "the Hollow", "opened_ts": None, "by": None, "milestone": 0}],
            "milestones": list(MILESTONES),
            "milestones_reached": [],
            "hatched_ever": 0,
            "woke_log": [],
            "visits": [],
            "board": {"session_id": None, "fed": {}, "dug": {}, "hatched": []},
            "last_board": None,
            "event_log": [],
        },
        "sessions": [],           # [{id, started_ts, last_ts}] every session this module has seen (live or inferred)
        "banished": {},
        "quarantine": {},         # {key: {record, reason, ts}}: world.json pips with NO chat.jsonl chatter (WORLD.md 1, 11)
    }


def _default_pip(key: str, name: str, display_name: str, n: Optional[int], t: float, genome: Dict[str, int]) -> Dict[str, Any]:
    return {
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


class WorldState(object):
    """Owner of $RUN_DIR/world.json. One instance per compositor process (the world module)."""

    def __init__(self, run_dir: str, log: Optional[Callable[[str], None]] = None,
                 name_filter: Optional[Callable[[str], str]] = None):
        self.run_dir = run_dir
        self.log = log or (lambda m: None)
        self.path = os.path.join(run_dir, "world.json")
        self.chat_path = run_path(run_dir, "CHAT_FILE", "chat.jsonl")
        self.builders_path = os.path.join(run_dir, "builders.json")
        self.name_filter = name_filter or (lambda s: s)
        self.data: Dict[str, Any] = _default_data()
        self.builders: Dict[str, Dict] = {}
        self.dirty = False
        self._last_flush: Optional[float] = None
        self._terrain: Optional[np.ndarray] = None
        self.loaded_ok = False
        self.load_errors = 0
        self.session_id: Optional[str] = None
        self.load()

    # ------------------------------------------------------------------ load / save
    def load(self) -> bool:
        """Read world.json; a missing or corrupt file leaves the defaults (and is logged), never raises."""
        self.data = _default_data()
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if not isinstance(d, dict) or not isinstance(d.get("pips"), dict):
                raise ValueError("world.json is not an object with pips")
            base = _default_data()
            for k, v in d.items():
                base[k] = v
            for k, v in _default_data()["world"].items():
                base["world"].setdefault(k, v)
            base["pips"] = {str(k).lower(): v for k, v in base["pips"].items() if isinstance(v, dict) and not v.get("_test")}
            self.data = base
            self.loaded_ok = True
        except FileNotFoundError:
            self.loaded_ok = False
        except Exception as e:
            self.load_errors += 1
            self.loaded_ok = False
            self.log("world.json unreadable (%r): starting from the newest .bak if any" % (e,))
            if not self._load_bak():
                self.data = _default_data()
        self._load_builders()
        self._terrain = None
        self.data["world"]["hatched_ever"] = self.hatched_ever
        return self.loaded_ok

    def _load_bak(self) -> bool:
        for bak in sorted(glob.glob(self.path + ".bak-*"), reverse=True):
            try:
                with open(bak, "r", encoding="utf-8") as fh:
                    d = json.load(fh)
                if isinstance(d, dict) and isinstance(d.get("pips"), dict):
                    base = _default_data()
                    base.update(d)
                    self.data = base
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
            if self._terrain is not None:
                self.data["world"]["terrain_b64"] = base64.b64encode(np.packbits(self._terrain.reshape(-1))).decode("ascii")
            self.data["schema"] = SCHEMA
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
            for old in sorted(glob.glob(self.path + ".bak-*"))[:-BAK_KEEP]:
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
            return p, False
        g, salt = P.resolve_genome(key, 0)
        p = _default_pip(key, name or key, display_name or self.name_filter(name or key), n if n is not None else self.builder_n(key), t, g)
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
        if burrow is not None:
            p["burrow"] = int(burrow)
        if vote != "keep":
            p["vote"] = vote
        self.dirty = True

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
        p = self.data["pips"].pop(key, None)
        if p is None:
            return False
        self.data.setdefault("quarantine", {})[key] = {"record": p, "reason": reason, "ts": _iso(now)}
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
        key = (key or "").lower()
        p = self.data["pips"].pop(key, None)
        if p is None:
            return False
        p["banished_ts"] = _iso(t)
        self.data.setdefault("banished", {})[key] = p
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
        self.data["pips"][key] = p
        self.data["world"]["hatched_ever"] = self.hatched_ever
        self.dirty = True
        return True


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
