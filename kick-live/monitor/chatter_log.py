#!/usr/bin/env python
"""chatter_log.py -- the chatter funnel, derived from chat.jsonl + metrics.jsonl (read-only inputs).

Per chatter (key = lower-case username):
  first_seen_ts, first_kind (vote | verb | idea | plain), first_text (60-char preview), second_within_10m
  (a 2nd message inside 10 min of the 1st), messages, last_seen, days_seen, first_message_stream_offset_s
  (seconds after the live session's started_at, when metrics show us live at that moment), is_owner
  (broadcaster badge, the channel's own slug, or $KICK_OWNER_ACCOUNTS), is_staff (Kick staff badge), badges.
  "external" in the summary means neither owner nor staff-badged.

Per UTC hour (bucket "YYYY-MM-DDTHH"):
  arrivals (sum of positive viewer_count steps between consecutive live polls of the same session),
  avg/peak viewers, live_samples, msgs, unique_chatters, first_time_chatters, chatters_per_viewer
  (unique_chatters / avg_viewers), plus the title and category that were live.

Outputs:
  $RUN_DIR/chatters.json               {generated_at, summary, chatters{}, hourly[]}   (--out to change)
  <repo>/run/reports/YYYY-MM-DD.md     daily markdown for --date (default: today UTC); --all-days writes one per
                                       day seen; --reports-dir to change (run/ is gitignored except .gitkeep)

  --summary        print one status line from an existing chatters.json (no recompute; used by scripts/status.sh)
  --table          print the hourly table for the report day to stdout

Honesty: every number is a count over the real files. Duplicate rows (the same message id arrives once from
the Pusher listener and once from the webhook receiver) are counted once. Owner accounts are counted AND
flagged (is_owner), and the summary gives external (non-owner) figures separately; nothing is filtered away
silently. Chat text is data: the previews are stripped of control characters and truncated.

Names and text follow the on-air moderation rule (stream/chat_bridge.py name_for(): "Never the raw name"):
  * a username that hits stream/moderation/blocklist.txt, or whose key is in world.json quarantine/banished
    (!hide / banish), is written as `builder #N` (N from $RUN_DIR/builders.json) in chatters.json AND the
    markdown report; the chatters{} key becomes "builder-N" so the raw name appears nowhere in the outputs;
  * first_text (60-char preview) is kept in chatters.json only when it passes the same blocklist, else it reads
    "[filtered: blocklist]"; the markdown report never contains chat text, only first_kind.
  The blocklist matcher is stream.chat_bridge.WordLists when importable, else an equivalent local copy of its
  leet-normalised whole-token rules; the report header names which one was used and the term count. Counts
  are never changed by masking (a masked chatter is still one chatter). --self-test proves the masking offline.

Paths: everything is resolved from ONE RUN_DIR (monitor/run_paths.py): $RUN_DIR (default <repo>/run) gives
chat.jsonl, metrics.jsonl, builders.json, world.json, chatters.json. $CHAT_FILE / $METRICS_FILE are honoured
only when they live under that RUN_DIR (scripts/env.sh exports them from a possibly different RUN_DIR).

Environment: RUN_DIR, KICK_CHANNEL, KICK_OWNER_ACCOUNTS. Python 3.9, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from run_paths import RunPaths  # noqa: E402

PATHS = RunPaths()
RUN_DIR = PATHS.run_dir
CHAT_FILE = PATHS.chat
METRICS_FILE = PATHS.metrics
OUT_FILE = PATHS.path("chatters.json")
BUILDERS_FILE = PATHS.path("builders.json")
WORLD_FILE = PATHS.path("world.json")
BLOCKLIST_FILE = os.path.join(REPO_ROOT, "stream", "moderation", "blocklist.txt")
REPORTS_DIR = os.path.join(REPO_ROOT, "run", "reports")
CHANNEL = os.environ.get("KICK_CHANNEL", "atleastonce")
# Owner accounts: the channel slug, the broadcaster badge, plus any names in $KICK_OWNER_ACCOUNTS (comma list).
OWNER_ACCOUNTS = {CHANNEL.lower()} | {x.strip().lower() for x in os.environ.get("KICK_OWNER_ACCOUNTS", "").split(",") if x.strip()}

SECOND_MSG_WINDOW_S = 10 * 60
PREVIEW_LEN = 60

# Mirrors stream/chat_bridge.py (OPENWORLD.md 6): exact-token vote, !idea, leading verb (<= 4 tokens).
VOTE_RE = re.compile(r"^!?([abc])$", re.IGNORECASE)
IDEA_RE = re.compile(r"^!idea\b", re.IGNORECASE)
VERBS = {"go", "home", "plant", "camp", "fire", "feed", "pet", "gift", "wave", "sit", "dance", "forget", "name",
         "teach", "sow", "harvest", "stack", "swim", "sing", "explore", "water",
         "walk", "head", "light", "pitch"}
MAX_VERB_TOKENS = 4
TOKEN_TRIM = "!?.,;:"
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]+")


# --------------------------------------------------------------------------- helpers
def parse_ts(v: Any) -> Optional[datetime]:
    """ISO (Z / offset / naive=UTC, 'YYYY-MM-DD HH:MM:SS' too) -> aware UTC datetime."""
    if not isinstance(v, str) or not v.strip():
        return None
    s = v.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
    if len(s) >= 19 and s[10] == " ":
        s = s[:10] + "T" + s[11:]
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def hour_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H")


def clean(text: Any, limit: int = PREVIEW_LEN) -> str:
    s = _CTRL_RE.sub(" ", "" if text is None else str(text)).strip()
    return s if len(s) <= limit else s[: limit - 3] + "..."


def classify(text: str) -> str:
    t = (text or "").strip()
    if VOTE_RE.match(t):
        return "vote"
    if IDEA_RE.match(t):
        return "idea"
    toks = t.split()
    if toks and len(toks) <= MAX_VERB_TOKENS:
        head = toks[0].strip(TOKEN_TRIM).lower()
        if head in VERBS:
            return "verb"
    return "plain"


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not os.path.isfile(path):
        return rows
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _to_int(v: Any) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None



# --------------------------------------------------------------------------- name / text filter (builder #N rule)
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b",
                       "@": "a", "$": "s", "!": "i", "|": "l", "+": "t"})
_SUFFIXES = ("", "s", "es", "z", "ed", "ing", "er", "ers")
_SUFFIX_MIN_LEN = 5
_SPACED_RUN_MIN = 3


def _norm(s: str) -> str:
    """Local copy of stream.chat_bridge._norm (leet-normalised lowercase, non-alnum -> space, 3+ repeats -> 2)."""
    s = (s or "").lower().translate(_LEET)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"(.)\1{2,}", r"\1\1", s)
    return re.sub(r"\s+", " ", s).strip()


class _LocalWordLists(object):
    """Fallback with the same matching rules as stream.chat_bridge.WordLists.blocked(); used only when that
    module cannot be imported (stream/ mid-edit, missing tree)."""

    def __init__(self, blocklist_path: str):
        self.blocklist_path = blocklist_path
        self.block_terms: List[str] = []

    def reload(self, now: float = 0.0, force: bool = True) -> None:
        terms: List[str] = []
        try:
            with open(self.blocklist_path, "r", encoding="utf-8") as fh:
                for ln in fh:
                    ln = ln.split("#", 1)[0].strip()
                    if ln:
                        n = _norm(ln)
                        if n and n not in terms:
                            terms.append(n)
        except OSError:
            pass
        self.block_terms = terms

    @staticmethod
    def _token_hit(tok: str, term: str) -> bool:
        if tok == term:
            return True
        if len(term) >= _SUFFIX_MIN_LEN and tok.startswith(term):
            return tok[len(term):] in _SUFFIXES
        return False

    def blocked(self, text: str) -> Optional[str]:
        if not self.block_terms or not text:
            return None
        n = _norm(text)
        if not n:
            return None
        tokens = n.split(" ")
        joined: List[str] = []
        run: List[str] = []
        for tok in tokens + [""]:
            if len(tok) == 1:
                run.append(tok)
                continue
            if len(run) >= _SPACED_RUN_MIN:
                joined.append("".join(run))
            run = []
        padded = " " + n + " "
        for term in self.block_terms:
            if " " in term:
                if " " + term + " " in padded:
                    return term
                continue
            for tok in tokens + joined:
                if self._token_hit(tok, term):
                    return term
        return None


class NameFilter(object):
    """username -> display name under the on-air rule: blocklist hit or quarantined/banished key -> `builder #N`."""

    def __init__(self, blocklist_path: str = BLOCKLIST_FILE, builders_path: str = BUILDERS_FILE,
                 world_path: str = WORLD_FILE):
        self.blocklist_path = blocklist_path
        self.source = "local"
        self.words: Any = None
        try:
            if REPO_ROOT not in sys.path:
                sys.path.insert(0, REPO_ROOT)
            from stream.chat_bridge import WordLists  # type: ignore
            self.words = WordLists(blocklist_path=blocklist_path, allowlist_path=os.devnull)
            self.words.reload(0.0, force=True)
            self.source = "stream.chat_bridge.WordLists"
        except Exception:  # noqa: BLE001 - stream/ may be mid-edit; the local twin has the same rules
            self.words = _LocalWordLists(blocklist_path)
            self.words.reload()
        self.terms = len(getattr(self.words, "block_terms", []) or [])
        self.builders: Dict[str, Any] = {}
        try:
            with open(builders_path, "r", encoding="utf-8") as fh:
                b = json.load(fh)
            if isinstance(b, dict):
                self.builders = {str(k).lower(): v for k, v in b.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            pass
        self.hidden: Dict[str, str] = {}
        try:
            with open(world_path, "r", encoding="utf-8") as fh:
                w = json.load(fh)
            for field in ("quarantine", "banished"):
                v = w.get(field) if isinstance(w, dict) else None
                keys = v.keys() if isinstance(v, dict) else (v if isinstance(v, list) else [])
                for k in keys:
                    self.hidden.setdefault(str(k).lower(), field)
        except (OSError, ValueError, AttributeError):
            pass
        self.masked: Dict[str, str] = {}   # raw key -> reason (for the summary count only; never written out)

    def builder_n(self, key: str) -> Optional[int]:
        b = self.builders.get(key.lower()) or {}
        return _to_int(b.get("n"))

    def reason(self, username: str) -> Optional[str]:
        k = (username or "").lower()
        if k in self.hidden:
            return self.hidden[k]
        if self.words.blocked(username):
            return "blocklist"
        return None

    def display(self, username: str) -> Tuple[str, Optional[str]]:
        """(display name, mask reason or None). A masked name is `builder #N` (N from builders.json, else ?)."""
        r = self.reason(username)
        if r is None:
            return username, None
        n = self.builder_n(username)
        self.masked[username.lower()] = r
        return "builder #%s" % (n if n is not None else "?"), r

    def text_ok(self, text: str) -> bool:
        return self.words.blocked(text) is None

    def describe(self) -> Dict[str, Any]:
        return {"blocklist": self.blocklist_path, "matcher": self.source, "terms": self.terms,
                "builders_known": len(self.builders), "hidden_keys": len(self.hidden), "masked_chatters": len(self.masked)}


# --------------------------------------------------------------------------- normalise chat rows
def normalise_chat(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Both row shapes -> {ts, id, user, text, badges, type}; dedupe by id (earliest ts wins); sorted."""
    by_id: Dict[str, Dict[str, Any]] = {}
    anon: List[Dict[str, Any]] = []
    for r in rows:
        user = r.get("username") or r.get("user")
        text = r.get("content") if r.get("content") is not None else r.get("text")
        if not user or text is None:
            continue
        ts = parse_ts(r.get("created_at")) or parse_ts(r.get("ts"))
        if ts is None:
            continue
        rec = {"ts": ts, "id": r.get("id"), "user": str(user), "text": str(text),
               "badges": [str(b) for b in (r.get("badges") or []) if isinstance(b, (str, int))],
               "type": r.get("type") or ("webhook" if r.get("source") == "webhook" else "message")}
        mid = rec["id"]
        if not mid:
            anon.append(rec)
            continue
        prev = by_id.get(str(mid))
        if prev is None or rec["ts"] < prev["ts"]:
            if prev is not None and not rec["badges"]:
                rec["badges"] = prev["badges"]          # keep badges from whichever copy had them
            by_id[str(mid)] = rec
        elif prev is not None and not prev["badges"] and rec["badges"]:
            prev["badges"] = rec["badges"]
    out = list(by_id.values()) + anon
    out.sort(key=lambda x: x["ts"])
    return out


# --------------------------------------------------------------------------- metrics -> live sessions
def live_rows(metrics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in metrics:
        ts = parse_ts(r.get("ts"))
        if ts is None or not isinstance(r.get("is_live"), bool):
            continue
        out.append({"ts": ts, "is_live": r["is_live"], "viewer_count": _to_int(r.get("viewer_count")),
                    "started_at": parse_ts(r.get("started_at")), "title": r.get("title"), "category": r.get("category")})
    out.sort(key=lambda x: x["ts"])
    return out


def stream_offset(ts: datetime, mrows: List[Dict[str, Any]]) -> Optional[float]:
    """Seconds since the live session's started_at, using the last poll at/before ts (within 3 min)."""
    best = None
    for r in mrows:            # mrows is sorted; small files, a linear scan is fine
        if r["ts"] <= ts:
            best = r
        else:
            break
    if best is None or not best["is_live"] or best["started_at"] is None:
        return None
    if (ts - best["ts"]).total_seconds() > 180:
        return None
    return round((ts - best["started_at"]).total_seconds(), 1)


# --------------------------------------------------------------------------- build
def build(chat_rows: List[Dict[str, Any]], metrics_rows: List[Dict[str, Any]],
          name_filter: Optional[NameFilter] = None) -> Dict[str, Any]:
    nf = name_filter or NameFilter()
    chat = normalise_chat(chat_rows)
    mrows = live_rows(metrics_rows)
    now = datetime.now(timezone.utc)

    chatters: Dict[str, Dict[str, Any]] = {}
    for m in chat:
        key = m["user"].lower()
        c = chatters.get(key)
        if c is None:
            c = {"username": m["user"], "first_seen_ts": iso(m["ts"]), "_first": m["ts"],
                 "first_kind": classify(m["text"]), "first_text": clean(m["text"]),
                 "first_message_stream_offset_s": stream_offset(m["ts"], mrows),
                 "second_within_10m": False, "messages": 0, "last_seen": None, "_days": set(), "_badges": set(),
                 "is_owner": False, "is_staff": False, "kinds": {"vote": 0, "verb": 0, "idea": 0, "plain": 0}}
            chatters[key] = c
        elif c["messages"] == 1 and (m["ts"] - c["_first"]).total_seconds() <= SECOND_MSG_WINDOW_S:
            c["second_within_10m"] = True
        c["messages"] += 1
        c["last_seen"] = iso(m["ts"])
        c["_days"].add(m["ts"].strftime("%Y-%m-%d"))
        c["_badges"].update(m["badges"])
        c["kinds"][classify(m["text"])] += 1
        if "broadcaster" in m["badges"] or key in OWNER_ACCOUNTS:
            c["is_owner"] = True
        if "staff" in m["badges"]:
            c["is_staff"] = True
    for c in chatters.values():
        c["days_seen"] = sorted(c.pop("_days"))
        c["badges"] = sorted(c.pop("_badges"))
        c.pop("_first")

    # hourly buckets: metrics
    hours: Dict[str, Dict[str, Any]] = {}

    def bucket(k: str) -> Dict[str, Any]:
        b = hours.get(k)
        if b is None:
            b = {"hour": k, "arrivals": 0, "live_samples": 0, "_viewers": [], "peak_viewers": None,
                 "msgs": 0, "_users": set(), "first_time_chatters": 0, "first_time_external": 0,
                 "title": None, "category": None}
            hours[k] = b
        return b

    prev: Optional[Dict[str, Any]] = None
    for r in mrows:
        b = bucket(hour_key(r["ts"]))
        if r["is_live"]:
            b["live_samples"] += 1
            if r["viewer_count"] is not None:
                b["_viewers"].append(r["viewer_count"])
            b["title"] = r["title"] or b["title"]
            b["category"] = r["category"] or b["category"]
            if (prev is not None and prev["is_live"] and prev["viewer_count"] is not None and r["viewer_count"] is not None
                    and prev["started_at"] == r["started_at"] and (r["ts"] - prev["ts"]).total_seconds() <= 120):
                step = r["viewer_count"] - prev["viewer_count"]
                if step > 0:
                    b["arrivals"] += step
        prev = r
    for m in chat:
        b = bucket(hour_key(m["ts"]))
        b["msgs"] += 1
        b["_users"].add(m["user"].lower())
    for c in chatters.values():
        b = bucket(c["first_seen_ts"][:13])
        b["first_time_chatters"] += 1
        if not c["is_owner"] and not c["is_staff"]:
            b["first_time_external"] += 1

    hourly: List[Dict[str, Any]] = []
    for k in sorted(hours):
        b = hours[k]
        vs = b.pop("_viewers")
        users = b.pop("_users")
        b["avg_viewers"] = round(sum(vs) / len(vs), 2) if vs else None
        b["peak_viewers"] = max(vs) if vs else None
        b["unique_chatters"] = len(users)
        b["chatters_per_viewer"] = (round(len(users) / b["avg_viewers"], 2) if b["avg_viewers"] else None)
        b["title"] = clean(b["title"], 120) if b["title"] else None
        hourly.append(b)

    # summary
    ext = [c for c in chatters.values() if not c["is_owner"] and not c["is_staff"]]
    offsets = [c["first_message_stream_offset_s"] for c in chatters.values() if c["first_message_stream_offset_s"] is not None]

    def rate(cs: List[Dict[str, Any]]) -> Optional[float]:
        return round(100.0 * sum(1 for c in cs if c["second_within_10m"]) / len(cs), 1) if cs else None

    kinds = {"vote": 0, "verb": 0, "idea": 0, "plain": 0}
    for c in chatters.values():
        kinds[c["first_kind"]] += 1
    today = now.strftime("%Y-%m-%d")
    today_hours = [h for h in hourly if h["hour"].startswith(today)]
    summary = {
        "chatters_total": len(chatters),
        "chatters_owner_accounts": sum(1 for c in chatters.values() if c["is_owner"]),
        "chatters_staff_accounts": sum(1 for c in chatters.values() if c["is_staff"] and not c["is_owner"]),
        "chatters_external": len(ext),
        "messages_total": len(chat),
        "duplicate_rows_dropped": len(chat_rows) - len(chat),
        "second_message_rate_pct": rate(list(chatters.values())),
        "second_message_rate_external_pct": rate(ext),
        "first_kind_counts": kinds,
        "median_first_message_stream_offset_s": (round(statistics.median(offsets), 1) if offsets else None),
        "arrivals_total": sum(h["arrivals"] for h in hourly),
        "arrivals_today": sum(h["arrivals"] for h in today_hours),
        "first_time_chatters_today": sum(h["first_time_chatters"] for h in today_hours),
        "first_time_external_today": sum(h["first_time_external"] for h in today_hours),
        "hours_with_data": len(hourly),
        "first_chat_ts": iso(chat[0]["ts"]) if chat else None,
        "last_chat_ts": iso(chat[-1]["ts"]) if chat else None,
        "metrics_rows_known_state": len(mrows),
        "note": ("no external chatter yet: every chatter is the broadcaster or a Kick-staff-badged account; "
                 "the external funnel is empty" if chatters and not ext else None),
    }
    # the name path (stream/chat_bridge.py name_for(): never the raw name for a blocklisted / hidden chatter)
    masked: Dict[str, Dict[str, Any]] = {}
    for key, c in sorted(chatters.items(), key=lambda kv: kv[1]["first_seen_ts"]):
        disp, reason = nf.display(c["username"])
        if reason is not None:
            c["username"] = disp
            c["name_masked"] = reason
            c["first_text"] = "[filtered: %s]" % reason
            out_key = disp.replace("builder #", "builder-")
            while out_key in masked:            # two hidden chatters without a builder number
                out_key += "_"
        else:
            c["name_masked"] = None
            if not nf.text_ok(c["first_text"]):
                c["first_text"] = "[filtered: blocklist]"
            out_key = key
        masked[out_key] = c
    summary["chatters_name_masked"] = sum(1 for c in masked.values() if c["name_masked"])
    return {"generated_at": iso(now), "channel": CHANNEL, "inputs": {"chat": CHAT_FILE, "metrics": METRICS_FILE},
            "name_filter": nf.describe(), "summary": summary, "chatters": masked, "hourly": hourly}


# --------------------------------------------------------------------------- rendering
def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return ("%.2f" % v).rstrip("0").rstrip(".")
    return str(v)


def table(rows: List[Dict[str, Any]], cols: List[Tuple[str, str]], md: bool = False) -> str:
    cells = [[_fmt(r.get(k)) for k, _ in cols] for r in rows]
    heads = [h for _, h in cols]
    if md:
        out = ["| " + " | ".join(heads) + " |", "|" + "|".join("---" for _ in heads) + "|"]
        out += ["| " + " | ".join(c.replace("|", "\\|") for c in row) + " |" for row in cells]
        return "\n".join(out)
    w = [max([len(h)] + [len(row[i]) for row in cells]) for i, h in enumerate(heads)]
    out = ["  ".join(h.ljust(w[i]) for i, h in enumerate(heads))]
    out += ["  ".join(c.ljust(w[i]) for i, c in enumerate(row)) for row in cells]
    return "\n".join(out)


HOUR_COLS = [("hour", "hour (UTC)"), ("live_samples", "polls"), ("avg_viewers", "avg v"), ("peak_viewers", "peak"),
             ("arrivals", "arrivals"), ("msgs", "msgs"), ("unique_chatters", "chatters"),
             ("first_time_chatters", "1st-time"), ("first_time_external", "1st ext"), ("chatters_per_viewer", "chat/viewer"),
             ("category", "category")]
CHATTER_COLS = [("username", "chatter"), ("first_seen_ts", "first seen"), ("first_kind", "1st kind"),
                ("first_message_stream_offset_s", "offset s"), ("second_within_10m", "2nd<10m"), ("messages", "msgs"),
                ("last_seen", "last seen"), ("is_owner", "owner"), ("is_staff", "staff")]
assert all(k != "first_text" for k, _ in CHATTER_COLS), "chat text never goes into the markdown report"


def summary_line(d: Dict[str, Any]) -> str:
    s = d.get("summary") or {}
    return ("chatters  %s total (%s ext, %s owner, %s staff)  2nd-msg<10m %s%% (ext %s%%)  arrivals today %s  1st-time today %s (ext %s)  "
            "median 1st-msg offset %ss  first kinds vote/verb/idea/plain %s/%s/%s/%s  [%s]" % (
                _fmt(s.get("chatters_total")), _fmt(s.get("chatters_external")), _fmt(s.get("chatters_owner_accounts")),
                _fmt(s.get("chatters_staff_accounts")), _fmt(s.get("second_message_rate_pct")), _fmt(s.get("second_message_rate_external_pct")),
                _fmt(s.get("arrivals_today")), _fmt(s.get("first_time_chatters_today")), _fmt(s.get("first_time_external_today")),
                _fmt(s.get("median_first_message_stream_offset_s")),
                *[_fmt((s.get("first_kind_counts") or {}).get(k)) for k in ("vote", "verb", "idea", "plain")],
                d.get("generated_at")))


def render_day_md(d: Dict[str, Any], day: str) -> str:
    s = d["summary"]
    nf = d.get("name_filter") or {}
    hours = [h for h in d["hourly"] if h["hour"].startswith(day)]
    new = [c for c in d["chatters"].values() if c["first_seen_ts"].startswith(day)]
    day_arrivals = sum(h["arrivals"] for h in hours)
    day_msgs = sum(h["msgs"] for h in hours)
    day_live = sum(h["live_samples"] for h in hours)
    vs = [h["avg_viewers"] for h in hours if h["avg_viewers"] is not None]
    lines = [
        "# %s chatter funnel, %s (UTC)" % (d["channel"], day),
        "",
        "Generated %s from `%s` and `%s`. Real counts only; duplicate message ids (Pusher + webhook copies) counted once (%d dropped overall)."
        % (d["generated_at"], os.path.basename(d["inputs"]["chat"]), os.path.basename(d["inputs"]["metrics"]), s["duplicate_rows_dropped"]),
        "",
        "Names follow the on-air rule: a username that hits `stream/moderation/blocklist.txt` (%s terms, matcher %s) or a "
        "quarantined/banished key renders as `builder #N`; %s chatter(s) masked here. No chat text is reproduced in this report."
        % (nf.get("terms", "?"), nf.get("matcher", "?"), s.get("chatters_name_masked", 0)),
        "",
        "## Day",
        "",
        "- live polls: %d (15 s cadence, so about %s of live time sampled)" % (day_live, _hm(day_live * 15)),
        "- viewer_count: mean of hourly averages %s, hour peaks max %s" % (
            _fmt(round(sum(vs) / len(vs), 2)) if vs else "-", _fmt(max((h["peak_viewers"] or 0) for h in hours) if hours else None)),
        "- arrivals (positive viewer_count steps): %d" % day_arrivals,
        "- messages: %d, first-time chatters: %d (external %d)" % (day_msgs, len(new), sum(1 for c in new if not c["is_owner"] and not c["is_staff"])),
        "- second message within 10 min, all time: %s%% of %d chatters (external: %s%% of %d)" % (
            _fmt(s["second_message_rate_pct"]), s["chatters_total"], _fmt(s["second_message_rate_external_pct"]), s["chatters_external"]),
        "- median first-message offset into the live session, all time: %s s" % _fmt(s["median_first_message_stream_offset_s"]),
    ]
    if s.get("note"):
        lines.append("- note: %s" % s["note"])
    lines += ["", "## Hours", ""]
    lines.append(table(hours, HOUR_COLS, md=True) if hours else "_no metrics or chat rows for this day_")
    lines += ["", "## First-time chatters this day", ""]
    lines.append(table(new, CHATTER_COLS, md=True) if new else "_none_")
    lines += ["", "## All chatters (funnel)", ""]
    lines.append(table(list(d["chatters"].values()), CHATTER_COLS, md=True) if d["chatters"] else "_none yet_")
    lines += ["", "Columns: `arrivals` = sum of positive viewer_count deltas between consecutive live polls of one session; "
                  "`chat/viewer` = unique chatters in the hour / mean viewer_count; `offset s` = seconds after Kick's started_at "
                  "when the chatter's first message landed (null when we were not polling live at that moment). "
                  "Owner accounts (broadcaster badge, channel slug, $KICK_OWNER_ACCOUNTS) and Kick-staff-badged accounts are counted "
                  "and flagged, never hidden; `external` excludes both.", ""]
    return "\n".join(lines)


def _hm(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    return "%dh %02dm" % (h, rem // 60)



# --------------------------------------------------------------------------- self-test
def self_test() -> int:
    """Offline: a blocklisted username and a quarantined key must render as builder #N everywhere; blocklisted
    text must not survive in chatters.json; the markdown must carry no chat text and no raw masked name."""
    import tempfile
    fails: List[str] = []
    with tempfile.TemporaryDirectory() as td:
        bl = os.path.join(td, "blocklist.txt")
        with open(bl, "w", encoding="utf-8") as fh:
            fh.write("# test list\nzorbleface\nsnargwort\n")
        with open(os.path.join(td, "builders.json"), "w", encoding="utf-8") as fh:
            json.dump({"zorblefaces": {"n": 7, "name": "ZorbleFaces"}, "quietone": {"n": 8, "name": "QuietOne"},
                       "goodname": {"n": 9, "name": "GoodName"}}, fh)
        with open(os.path.join(td, "world.json"), "w", encoding="utf-8") as fh:
            json.dump({"pips": {}, "quarantine": {"quietone": {"reason": "mod hide"}}, "banished": {}}, fh)
        chat = [
            {"ts": "2026-09-26T01:00:00Z", "id": "m1", "username": "ZorbleFaces", "content": "hello there", "badges": []},
            {"ts": "2026-09-26T01:00:05Z", "id": "m2", "username": "QuietOne", "content": "go river", "badges": []},
            {"ts": "2026-09-26T01:00:10Z", "id": "m3", "username": "GoodName", "content": "what a snargwort stream", "badges": []},
            {"ts": "2026-09-26T01:00:12Z", "id": "m4", "username": "GoodName", "content": "a", "badges": []},
        ]
        metrics = [{"ts": "2026-09-26T00:59:50Z", "is_live": True, "viewer_count": 2, "started_at": "2026-09-26 00:04:03",
                    "title": "t", "category": "Software Development"}]
        nf = NameFilter(bl, os.path.join(td, "builders.json"), os.path.join(td, "world.json"))
        d = build(chat, metrics, name_filter=nf)
        blob = json.dumps(d, ensure_ascii=False)
        md = render_day_md(d, "2026-09-26")
        for raw in ("ZorbleFaces", "zorbleface", "QuietOne", "quietone", "snargwort"):
            if raw in blob:
                fails.append("raw %r survives in chatters.json output" % raw)
            if raw in md:
                fails.append("raw %r survives in the markdown report" % raw)
        if "builder-7" not in d["chatters"] or d["chatters"]["builder-7"]["username"] != "builder #7":
            fails.append("blocklisted username not rendered as builder #7: %r" % sorted(d["chatters"]))
        if "builder-8" not in d["chatters"] or d["chatters"]["builder-8"]["name_masked"] != "quarantine":
            fails.append("quarantined key not masked: %r" % sorted(d["chatters"]))
        g = d["chatters"].get("goodname") or {}
        if g.get("username") != "GoodName" or g.get("first_text") != "[filtered: blocklist]":
            fails.append("clean name must stay, blocklisted text must be filtered: %r" % g)
        if d["summary"]["chatters_total"] != 3 or d["summary"]["chatters_name_masked"] != 2:
            fails.append("counts changed by masking: %r" % d["summary"])
        if "builder #7" not in md or "GoodName" not in md:
            fails.append("markdown missing builder #7 / GoodName")
        if "hello there" in md or "go river" in md:
            fails.append("chat text leaked into markdown")
        if nf.terms != 2:
            fails.append("blocklist terms: %d" % nf.terms)
    for f in fails:
        print("chatter_log SELF-TEST FAIL: %s" % f)
    print("chatter_log self-test %s (matcher %s, 9 checks)" % ("PASS" if not fails else "FAIL", nf.source))
    return 0 if not fails else 1


# --------------------------------------------------------------------------- main
def main(argv: Optional[List[str]] = None) -> int:
    global CHAT_FILE, METRICS_FILE
    p = argparse.ArgumentParser(prog="chatter_log.py", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog="\n".join(__doc__.split("\n\n")[1:]))
    p.add_argument("--chat", default=CHAT_FILE, help="chat.jsonl (default $CHAT_FILE)")
    p.add_argument("--metrics", default=METRICS_FILE, help="metrics.jsonl (default $METRICS_FILE)")
    p.add_argument("--out", default=OUT_FILE, help="chatters.json path (default $RUN_DIR/chatters.json); '-' = do not write")
    p.add_argument("--reports-dir", default=REPORTS_DIR, help="daily markdown dir (default <repo>/run/reports)")
    p.add_argument("--date", default=None, help="report day YYYY-MM-DD UTC (default today)")
    p.add_argument("--all-days", action="store_true", help="write a report for every day with data")
    p.add_argument("--no-report", action="store_true", help="skip the markdown report")
    p.add_argument("--table", action="store_true", help="print the hourly + chatter tables to stdout")
    p.add_argument("--summary", action="store_true", help="print one status line from the existing chatters.json and exit")
    p.add_argument("--json", action="store_true", help="print chatters.json content to stdout")
    p.add_argument("--blocklist", default=BLOCKLIST_FILE, help="username/text blocklist (default stream/moderation/blocklist.txt)")
    p.add_argument("--builders", default=BUILDERS_FILE, help="builders.json for builder #N (default $RUN_DIR/builders.json)")
    p.add_argument("--world", default=WORLD_FILE, help="world.json for quarantine/banished keys (default $RUN_DIR/world.json)")
    p.add_argument("--self-test", action="store_true", help="offline check of the builder #N masking, exit 0/1")
    args = p.parse_args(argv)
    if args.self_test:
        return self_test()

    if args.summary:
        try:
            with open(args.out if args.out != "-" else OUT_FILE, "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError) as e:
            print("chatters  no data (%s)" % e)
            return 1
        print(summary_line(d))
        return 0

    CHAT_FILE, METRICS_FILE = args.chat, args.metrics
    nf = NameFilter(args.blocklist, args.builders, args.world)
    d = build(read_jsonl(args.chat), read_jsonl(args.metrics), name_filter=nf)
    if args.out != "-":
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        tmp = "%s.tmp.%d" % (args.out, os.getpid())
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        os.replace(tmp, args.out)
    written: List[str] = []
    if not args.no_report:
        days = sorted({h["hour"][:10] for h in d["hourly"]}) if args.all_days else [args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")]
        os.makedirs(args.reports_dir, exist_ok=True)
        for day in days:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                p.error("--date must be YYYY-MM-DD")
            path = os.path.join(args.reports_dir, "%s.md" % day)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(render_day_md(d, day))
            written.append(path)
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    if args.table:
        day = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        print(summary_line(d))
        print()
        print(table([h for h in d["hourly"] if h["hour"].startswith(day)] or d["hourly"][-24:], HOUR_COLS))
        print()
        print(table(list(d["chatters"].values()), CHATTER_COLS))
    if not args.json and not args.table:
        print(summary_line(d))
    for w in written:
        print("wrote %s" % w)
    if args.out != "-":
        print("wrote %s" % args.out)
    print("paths run_dir=%s chat=%s metrics=%s name_filter=%s" % (RUN_DIR, args.chat, args.metrics, json.dumps(nf.describe())))
    if PATHS.ignored:
        print("note: ignored env overrides outside RUN_DIR: %s" % json.dumps(PATHS.ignored))
    return 0


if __name__ == "__main__":
    sys.exit(main())
