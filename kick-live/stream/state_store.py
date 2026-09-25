"""state_store.py - read-only view of the run directory for the compositor.

StateStore reads (throttled to every 250 ms, driven by the `now` the loop passes in; this module
never calls time.time()):
  $STATE_FILE        state.json (CONCEPT section 8.1)          -> ctx.state + typed shortcuts
  $CHAT_FILE         chat.jsonl tail, both record shapes, de-dup on id, normalised name/text
  $RUN_DIR/chat_stats.json                                     -> ctx.chat_stats
  $METRICS_FILE      metrics.jsonl last line                   -> ctx.metrics
  $ACTIVITY_FILE     activity.jsonl tail (last 50)             -> ctx.activity
Missing or unreadable files fall back to safe defaults. state.json older than 10 s -> ctx.stale=True.
A default state.json is written if absent.

Chat record shapes on the same file (de-dup on `id`):
  Pusher listener : {ts, id, username, content, color, badges, type, ...}
  webhook receiver: {ts, source:"webhook", id, user, user_id, text, broadcaster}
Normalised message dict: {id, ts, t, name, text, color, badges, source, type}

Public surface:
  StateStore(run_dir, log=None)
  .refresh(now)                 throttled re-read (call every frame; cheap when nothing changed)
  .ctx(now, frame, fps, **extra) -> Ctx   read-only snapshot; extra keys are attached verbatim
  .drain_chat() -> list[msg]    new normalised chat messages since the last drain (ChatBridge uses it)
  .state -> dict                latest parsed state.json (deep-copied on write, mutate a copy)
  .set_state(d)                 make an in-memory state visible immediately (RoundEngine after a write)
  write_state_atomic(path, d)   tmp + os.replace
  write_owned(path, owned_paths, updates)   re-read disk, overwrite ONLY the given dotted paths, keep the rest
  OWNED_PATHS                   who owns which state.json paths (COMPOSITOR_API.md section 8)
  path_owned(path, owned_paths) -> bool
  read_state_file(path) -> dict | None
  iso_to_epoch(s) / epoch_to_iso(t)
"""
from __future__ import annotations

import copy
import datetime as _dt
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

try:
    import fcntl                       # write_owned() serialises writers with flock; best effort, POSIX only
except Exception:  # pragma: no cover
    fcntl = None

REFRESH_S = 0.25
STALE_S = 10.0
CHAT_KEEP = 300
ACTIVITY_KEEP = 50
_BOOT_TAIL_BYTES = 256 * 1024     # on boot read at most the last 256 KiB of a jsonl file


# ----------------------------------------------------------------------------- time helpers
def iso_to_epoch(s: Any) -> Optional[float]:
    """'2026-09-24T10:31:02.512Z' -> epoch seconds. Accepts numbers too. None on failure."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    try:
        st = str(s).strip()
        if st.endswith("Z") or st.endswith("z"):
            st = st[:-1] + "+00:00"
        if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", st):
            st += "+00:00"
        # python 3.9 fromisoformat wants exactly 3 or 6 fractional digits
        m = re.match(r"^(.*T\d{2}:\d{2}:\d{2})\.(\d+)(.*)$", st)
        if m:
            frac = (m.group(2) + "000000")[:6]
            st = "%s.%s%s" % (m.group(1), frac, m.group(3) or "+00:00")
        d = _dt.datetime.fromisoformat(st)
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        return d.timestamp()
    except Exception:
        return None


def epoch_to_iso(t: float, ms: bool = True) -> str:
    d = _dt.datetime.fromtimestamp(float(t), tz=_dt.timezone.utc)
    if ms:
        return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def run_path(run_dir: str, env_name: str, default_name: str) -> str:
    """Resolve a run-dir file. $STATE_FILE / $CHAT_FILE / $ACTIVITY_FILE / $METRICS_FILE from env.sh win
    ONLY when $RUN_DIR is the same directory AND the file actually lives inside it. env.sh derives those
    variables from $RUN_DIR at `source` time, so `source env.sh; RUN_DIR=/tmp/cp-x python ...` leaves
    $STATE_FILE pointing at the OLD dir: such a stale value is ignored (that is how a test run against
    /tmp/cp-x wrote into the shared run dir's state.json; guard proven 2026-09-25)."""
    env_run = os.environ.get("RUN_DIR")
    if env_run and os.path.realpath(env_run) == os.path.realpath(run_dir):
        p = os.environ.get(env_name)
        if p and os.path.realpath(os.path.dirname(os.path.abspath(p))) == os.path.realpath(run_dir):
            return p
    return os.path.join(run_dir, default_name)


def write_state_atomic(path: str, d: Dict) -> None:
    tmp = path + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    os.replace(tmp, path)


# ----------------------------------------------------------------------------- write ownership
# Which process owns which state.json paths (the table in COMPOSITOR_API.md section 8). A writer passes
# ITS list to write_owned(); every update outside it is dropped and logged, so several processes can
# share one file without adopting each other's fields (journal 012: a test run's version/round fields
# leaked into the live state because the engine re-read the whole file and wrote it all back).
#
# Path grammar (dotted):  block            round, version.micro, chat.display
#                         list index       ideas.3.status
#                         list element id  ideas[i-0002].class      (element whose "id" == "i-0002")
#                         append           ideas[+]                 (value appended; must be the last segment)
# Owned-path patterns use the same grammar; `ideas[]` is a wildcard for any element, a bare block name
# (`round`) covers everything under it. `updated_ts` is the stale heartbeat: every write refreshes it.
OWNED_PATHS: Dict[str, List[str]] = {
    # RoundEngine (stream/rounds.py) - runs inside the compositor process
    "rounds": ["session", "version", "round", "micro", "theme",
               "ideas[+]", "ideas[].id", "ideas[].text", "ideas[].by", "ideas[].ts", "ideas[].plus", "ideas[].status"],
    # the frame loop's own mirrors; the RoundEngine writes them on the compositor's behalf (same process)
    "compositor": ["compositor", "chat", "mod", "metrics", "audio"],
    # agents/duty.py - the on-duty agent, a separate process
    "agent": ["agent", "macro", "ask", "ideas[].class", "ideas[].status", "ideas[].reason"],
    # scripts/stop.sh --credits
    "stop": ["session.ending"],
}

_TOK_RE = re.compile(r"\[([^\]]*)\]|([^.\[\]]+)")


def _tokens(path: str) -> List[Tuple[str, str]]:
    """'ideas[i-2].class' -> [('key','ideas'), ('idx','i-2'), ('key','class')]; 'ideas.3.x' -> keys '3' (digits = index)."""
    out: List[Tuple[str, str]] = []
    for m in _TOK_RE.finditer(path or ""):
        if m.group(1) is not None:
            out.append(("idx", m.group(1)))
        else:
            out.append(("key", m.group(2)))
    return out


def path_owned(path: str, owned_paths: List[str]) -> bool:
    """True when `path` is covered by one of the owned patterns (prefix match, `[]` = any element)."""
    toks = _tokens(path)
    if not toks:
        return False
    for pat in owned_paths or []:
        p = _tokens(pat)
        if not p or len(p) > len(toks):
            continue
        ok = True
        for a, b in zip(p, toks):
            if a == ("idx", ""):                                   # wildcard element
                if (b[0] == "idx" and b[1] != "+") or (b[0] == "key" and b[1].isdigit()):
                    continue
                ok = False
                break
            if a != b:
                ok = False
                break
        if ok:
            return True
    return False


def _set_path(root: Dict, path: str, value: Any) -> Optional[str]:
    """Set `value` at dotted `path` inside root (dicts/lists created on the way). Returns an error or None."""
    toks = _tokens(path)
    if not toks:
        return "empty path"
    cur: Any = root
    for i, (kind, name) in enumerate(toks):
        last = i == len(toks) - 1
        if isinstance(cur, list):
            if kind == "idx" and name == "+":
                if not last:
                    return "append [+] must be the last segment"
                cur.append(copy.deepcopy(value))
                return None
            if name.isdigit():
                j = int(name)
                if j >= len(cur):
                    return "index %d out of range (len %d)" % (j, len(cur))
                if last:
                    cur[j] = copy.deepcopy(value)
                    return None
                cur = cur[j]
                continue
            hit = -1
            for j, el in enumerate(cur):
                if isinstance(el, dict) and str(el.get("id")) == name:
                    hit = j
                    break
            if hit < 0:
                return "no element with id %r" % name
            if last:
                cur[hit] = copy.deepcopy(value)
                return None
            cur = cur[hit]
            continue
        if not isinstance(cur, dict):
            return "cannot descend into %s at %r" % (type(cur).__name__, name)
        if kind == "idx":
            return "index %r on a dict" % name
        if last:
            cur[name] = copy.deepcopy(value)
            return None
        nxt = cur.get(name)
        if nxt is None:
            nk, nn = toks[i + 1]
            nxt = [] if (nk == "idx" or nn.isdigit()) else {}
            cur[name] = nxt
        cur = nxt
    return None


def read_state_file(path: str) -> Optional[Dict]:
    """Parsed state.json or None when missing / half-written / not an object."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def write_owned(path: str, owned_paths: List[str], updates: Dict[str, Any], log=None, now: Optional[float] = None,
                strict: bool = False, base: Optional[Dict] = None) -> Dict:
    """Re-read state.json from disk, overwrite ONLY the dotted paths in `updates` (each must be covered by
    `owned_paths`, see OWNED_PATHS), keep everything else exactly as on disk, refresh `updated_ts`, write
    atomically (tmp + os.replace) under an flock on `<path>.lock`. Returns the merged dict as written.

    Updates outside the owned paths are DROPPED and reported through `log` (raise ValueError when strict).
    `base` is used when the file is missing or unreadable (e.g. default_state(...)); otherwise {}.
    Values are deep-copied, so the caller may keep mutating its own copy. Example:

        write_owned(state_file, OWNED_PATHS["rounds"] + OWNED_PATHS["compositor"],
                    {"round": s["round"], "version": s["version"], "compositor": counters})
        write_owned(state_file, OWNED_PATHS["agent"], {"agent.on_duty": True, "ideas[i-0002].class": "macro"})
    """
    import time as _time
    lock = None
    if fcntl is not None:
        try:
            lock = open(path + ".lock", "a")
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        except Exception:
            lock = None
    rejected: List[Tuple[str, str]] = []
    try:
        d = read_state_file(path)
        if d is None:
            d = copy.deepcopy(base) if base else {}
        for p, v in (updates or {}).items():
            if not path_owned(p, owned_paths):
                rejected.append((p, "not owned"))
                continue
            err = _set_path(d, p, v)
            if err:
                rejected.append((p, err))
        d["updated_ts"] = epoch_to_iso(now if now is not None else _time.time())
        write_state_atomic(path, d)
    finally:
        if lock is not None:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                lock.close()
            except Exception:
                pass
    if rejected:
        msg = "write_owned(%s): dropped %s" % (os.path.basename(path), ", ".join("%s (%s)" % r for r in rejected))
        if log:
            log(msg)
        else:
            sys.stderr.write("state_store: %s\n" % msg)
        if strict:
            raise ValueError(msg)
    return d


def default_state(now_iso: str) -> Dict:
    """A complete, safe state.json (CONCEPT 8.1) for a fresh run dir."""
    return {
        "schema": 1,
        "updated_ts": now_iso,
        "session": {"id": now_iso, "started_ts": now_iso, "ending": False},
        "version": {"string": "v0.1.0", "major": 0, "macro": 1, "micro": 0, "commit": None, "shipped": 0, "failed": 0},
        "theme": {"preset": "kick", "set_by": None, "set_ts": None, "cooldown_until": None},
        "round": {"number": 0, "phase": "open", "opened_ts": None, "deadline_ts": None, "options": [], "last_result": None},
        "micro": {"palette": "kick", "canvas_scene": "reaction_diffusion", "canvas_rule": "coral", "canvas_seed": 41370704,
                  "audio_tempo": 85, "audio_pattern": "pad_pulse", "ticker_speed": 120, "header_tagline": "SHIP IT LIVE",
                  "typewriter_cps": 40, "scope_style": "line", "stage_default": "diff", "chime_variant": "arpeggio"},
        "macro": {"active": False, "title": None, "requested_by": None, "module": None, "started_ts": None, "deadline_ts": None,
                  "step": None, "step_index": 0, "step_label": None, "file": None, "status_lines": [], "last_reload": None},
        "agent": {"on_duty": False, "heartbeat_ts": None, "name": "builder"},
        "ideas": [],
        "ask": {"enabled": False, "current": None, "queue": [], "last": None},
        "chat": {"display": True, "connected": False, "founders": [], "msgs_per_min_5m": 0.0, "unique_chatters_5m": 0},
        "mod": {"paused": False, "hidden_users": [], "actions": []},
        "metrics": {"is_live": False, "viewer_count": None, "viewer_peak": None, "polled_ts": None, "poll_ok": False},
        "audio": {"source": "fifo", "tempo": 85, "pattern": "pad_pulse", "muted_plucks": False},
        "compositor": {"fps_target": 30, "fps_actual": 0.0, "frame_ms_avg": 0.0, "frame_ms_p95": 0.0, "dropped_frames": 0,
                       "scene": "STATUS", "uptime_s": 0},
    }


def _deep_merge_defaults(d: Dict, defaults: Dict) -> Dict:
    """Fill missing keys from defaults (one level of nesting is enough for state.json)."""
    out = dict(defaults)
    for k, v in (d or {}).items():
        if isinstance(v, dict) and isinstance(defaults.get(k), dict):
            m = dict(defaults[k]); m.update(v); out[k] = m
        else:
            out[k] = v
    return out


# ----------------------------------------------------------------------------- chat normalisation
def normalise_chat(obj: Dict) -> Optional[Dict]:
    """Both chat.jsonl shapes -> one dict. None if it is not a chat message."""
    if not isinstance(obj, dict):
        return None
    mid = obj.get("id")
    if mid is None:
        return None
    name = obj.get("username") or obj.get("user") or ""
    text = obj.get("content")
    if text is None:
        text = obj.get("text")
    if text is None:
        return None
    ts = obj.get("ts") or obj.get("created_at")
    t = iso_to_epoch(ts)
    badges = obj.get("badges") or []
    if isinstance(badges, str):
        badges = [badges]
    src = obj.get("source") or ("webhook" if "user_id" in obj and "username" not in obj else "pusher")
    if obj.get("broadcaster") is True and "broadcaster" not in badges:
        badges = list(badges) + ["broadcaster"]
    return {
        "id": str(mid),
        "ts": ts if isinstance(ts, str) else (epoch_to_iso(t) if t else None),
        "t": t,
        "name": str(name),
        "text": str(text),
        "color": obj.get("color"),
        "badges": [str(b).lower() for b in badges],
        "source": src,
        "type": obj.get("type") or "message",
    }


# ----------------------------------------------------------------------------- jsonl tail
class JsonlTail(object):
    """Incremental reader of an append-only jsonl file. Handles truncation and rotation."""

    def __init__(self, path: str, boot_tail_bytes: int = _BOOT_TAIL_BYTES):
        self.path = path
        self.offset = 0
        self.inode = None
        self.partial = b""
        self.boot_tail_bytes = boot_tail_bytes
        self._booted = False

    def read_new(self) -> List[Dict]:
        out: List[Dict] = []
        try:
            st = os.stat(self.path)
        except OSError:
            return out
        if self.inode is not None and (st.st_ino != self.inode or st.st_size < self.offset):
            self.offset, self.partial = 0, b""        # rotated / truncated
        self.inode = st.st_ino
        if not self._booted:
            self._booted = True
            if st.st_size > self.boot_tail_bytes:
                self.offset = st.st_size - self.boot_tail_bytes
        if st.st_size == self.offset:
            return out
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                data = fh.read(st.st_size - self.offset)
        except OSError:
            return out
        self.offset += len(data)
        data = self.partial + data
        lines = data.split(b"\n")
        self.partial = lines.pop()             # incomplete last line (or b"")
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                obj = json.loads(ln.decode("utf-8", "replace"))
            except Exception:
                continue
            if isinstance(obj, dict):
                out.append(obj)
        return out


# ----------------------------------------------------------------------------- ctx
class Ctx(object):
    """Read-only-by-convention snapshot handed to panels, audio, rounds. Attributes listed in
    COMPOSITOR_API.md. Unknown attribute -> None (never raises) so panels can be lenient."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return None

    def get(self, name, default=None):
        v = self.__dict__.get(name)
        return default if v is None else v


# ----------------------------------------------------------------------------- store
class StateStore(object):
    def __init__(self, run_dir: str, log=None, state_file: Optional[str] = None, chat_file: Optional[str] = None,
                 activity_file: Optional[str] = None, metrics_file: Optional[str] = None):
        self.run_dir = run_dir
        self.state_file = state_file or run_path(run_dir, "STATE_FILE", "state.json")
        self.chat_file = chat_file or run_path(run_dir, "CHAT_FILE", "chat.jsonl")
        self.activity_file = activity_file or run_path(run_dir, "ACTIVITY_FILE", "activity.jsonl")
        self.metrics_file = metrics_file or run_path(run_dir, "METRICS_FILE", "metrics.jsonl")
        self.stats_file = os.path.join(run_dir, "chat_stats.json")
        self.log = log or (lambda m: sys.stderr.write("state_store: %s\n" % m))

        self._state: Dict = default_state("1970-01-01T00:00:00Z")
        self._state_mtime = None
        self._last_refresh = None
        self._state_read_ok = False
        self.stale = True
        self.updated_t: Optional[float] = None

        self._chat_tail = JsonlTail(self.chat_file)
        self._act_tail = JsonlTail(self.activity_file, boot_tail_bytes=32 * 1024)
        self._ships_tail = JsonlTail(os.path.join(run_dir, "ships.jsonl"), boot_tail_bytes=32 * 1024)
        self.ships: List[Dict] = []           # last 20 lines of ships.jsonl (patch notes for the ticker)
        self._seen_ids: Dict[str, bool] = {}
        self._seen_order: List[str] = []
        self.chat: List[Dict] = []            # recent normalised messages (raw, unmoderated)
        self._chat_new: List[Dict] = []       # undrained
        self.activity: List[Dict] = []
        self.metrics: Dict = {}
        self._metrics_mtime = None
        self.chat_stats: Dict = {}
        self._stats_mtime = None
        self.errors = 0

    # -- state.json ----------------------------------------------------------------
    @property
    def state(self) -> Dict:
        return self._state

    def set_state(self, d: Dict) -> None:
        self._state = _deep_merge_defaults(d, default_state(d.get("updated_ts") or "1970-01-01T00:00:00Z"))

    def ensure_state_file(self, now: float) -> None:
        if not os.path.exists(self.state_file):
            try:
                os.makedirs(os.path.dirname(self.state_file) or ".", exist_ok=True)
                d = default_state(epoch_to_iso(now))
                write_state_atomic(self.state_file, d)
                self.set_state(d)
                self.log("wrote default state.json at %s" % self.state_file)
            except Exception as e:
                self.log("cannot write default state.json: %r" % (e,))

    def _read_state(self, now: float) -> None:
        try:
            st = os.stat(self.state_file)
        except OSError:
            self._state_read_ok = False
            return
        if st.st_mtime == self._state_mtime and self._state_read_ok:
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if not isinstance(d, dict):
                raise ValueError("state.json is not an object")
            self.set_state(d)
            self._state_mtime = st.st_mtime
            self._state_read_ok = True
        except Exception as e:
            # half-written or bad file: keep the last good state
            self.errors += 1
            if self.errors % 50 == 1:
                self.log("state.json read failed (%r); keeping last good" % (e,))

    # -- chat -----------------------------------------------------------------------
    def _read_chat(self) -> None:
        for obj in self._chat_tail.read_new():
            m = normalise_chat(obj)
            if m is None or m["id"] in self._seen_ids:
                continue
            self._seen_ids[m["id"]] = True
            self._seen_order.append(m["id"])
            if len(self._seen_order) > 5000:
                for old in self._seen_order[:1000]:
                    self._seen_ids.pop(old, None)
                del self._seen_order[:1000]
            self.chat.append(m)
            self._chat_new.append(m)
        if len(self.chat) > CHAT_KEEP:
            del self.chat[:-CHAT_KEEP]

    def drain_chat(self) -> List[Dict]:
        out, self._chat_new = self._chat_new, []
        return out

    # -- small files ----------------------------------------------------------------
    def _read_activity(self) -> None:
        new = self._act_tail.read_new()
        if new:
            self.activity.extend(o for o in new if isinstance(o, dict) and "text" in o)
            if len(self.activity) > ACTIVITY_KEEP:
                del self.activity[:-ACTIVITY_KEEP]

    def _read_ships(self) -> None:
        new = self._ships_tail.read_new()
        if new:
            self.ships.extend(o for o in new if isinstance(o, dict) and "version" in o)
            if len(self.ships) > 20:
                del self.ships[:-20]

    def _read_metrics(self) -> None:
        try:
            st = os.stat(self.metrics_file)
        except OSError:
            return
        if st.st_mtime == self._metrics_mtime:
            return
        self._metrics_mtime = st.st_mtime
        try:
            with open(self.metrics_file, "rb") as fh:
                fh.seek(max(0, st.st_size - 8192))
                tail = fh.read().decode("utf-8", "replace").strip().splitlines()
            for ln in reversed(tail):
                ln = ln.strip()
                if not ln:
                    continue
                obj = json.loads(ln)
                if isinstance(obj, dict):
                    self.metrics = obj
                    break
        except Exception:
            pass

    def _read_stats(self) -> None:
        try:
            st = os.stat(self.stats_file)
        except OSError:
            return
        if st.st_mtime == self._stats_mtime:
            return
        self._stats_mtime = st.st_mtime
        try:
            with open(self.stats_file, "r", encoding="utf-8") as fh:
                obj = json.load(fh)
            if isinstance(obj, dict):
                self.chat_stats = obj
        except Exception:
            pass

    # -- refresh --------------------------------------------------------------------
    def refresh(self, now: float, force: bool = False) -> bool:
        """Re-read everything at most every 250 ms. Returns True when a read cycle ran."""
        if not force and self._last_refresh is not None and now - self._last_refresh < REFRESH_S:
            return False
        self._last_refresh = now
        for fn in (lambda: self._read_state(now), self._read_chat, self._read_activity, self._read_ships,
                   self._read_metrics, self._read_stats):
            try:
                fn()
            except Exception as e:
                self.errors += 1
                if self.errors % 50 == 1:
                    self.log("refresh step failed: %r" % (e,))
        self.updated_t = iso_to_epoch(self._state.get("updated_ts"))
        self.stale = (self.updated_t is None) or (now - self.updated_t > STALE_S)
        return True

    # -- ctx ------------------------------------------------------------------------
    def ctx(self, now: float, frame: int, fps: float, **extra) -> Ctx:
        s = self._state
        met = self.metrics or {}
        polled_t = iso_to_epoch(met.get("ts"))
        metrics = {
            "is_live": bool(met.get("is_live")) if met else False,
            "viewer_count": met.get("viewer_count") if met else None,
            "viewer_peak": met.get("viewer_peak") if met else None,
            "polled_ts": met.get("ts"),
            "poll_ok": bool(met) and met.get("viewer_count") is not None and polled_t is not None and (now - polled_t) < 60,
            "title": met.get("title"),
            "source": met.get("source"),
        }
        rnd = s.get("round") or {}
        deadline_t = iso_to_epoch(rnd.get("deadline_ts"))
        opened_t = iso_to_epoch(rnd.get("opened_ts"))
        remaining = (deadline_t - now) if deadline_t else None
        theme = s.get("theme") or {}
        c = Ctx(
            now=now, frame=frame, fps=fps,
            state=s, stale=self.stale, updated_t=self.updated_t,
            session=s.get("session") or {},
            version=s.get("version") or {},
            round=rnd, round_remaining=remaining, round_opened_t=opened_t, round_deadline_t=deadline_t,
            micro=s.get("micro") or {},
            theme=theme, preset=(theme.get("preset") or (s.get("micro") or {}).get("palette") or "kick"),
            macro=s.get("macro") or {},
            agent=s.get("agent") or {},
            ideas=s.get("ideas") or [],
            ask=s.get("ask") or {},
            chat_cfg=s.get("chat") or {},
            mod=s.get("mod") or {},
            founders=list((s.get("chat") or {}).get("founders") or []),
            metrics=metrics,
            chat_stats=self.chat_stats,
            chat_raw=self.chat[-20:],
            chat=self.chat[-10:],           # ChatBridge replaces this with moderated messages
            activity=self.activity[-8:],
            ships=self.ships[-10:],
            audio_cfg=s.get("audio") or {},
            compositor=s.get("compositor") or {},
        )
        for k, v in extra.items():
            setattr(c, k, v)
        return c


if __name__ == "__main__":  # smoke: python stream/state_store.py [run_dir]
    import time
    rd = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("RUN_DIR", "/tmp/cp-spine")
    st = StateStore(rd)
    now = time.time()
    st.ensure_state_file(now)
    st.refresh(now, force=True)
    c = st.ctx(now, 0, 30.0)
    print("stale=%s version=%s round=%s chat=%d activity=%d metrics=%s" % (
        c.stale, c.version.get("string"), c.round.get("phase"), len(st.chat), len(st.activity), c.metrics))
    for m in st.chat[-5:]:
        print(" ", m["name"], ":", m["text"][:60])
