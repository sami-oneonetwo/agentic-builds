#!/usr/bin/env python
"""kick-live status report and window comparison, built only from the runtime files.

Reads (all optional; missing or empty files produce "no data", never a crash):
  $METRICS_FILE            metrics.jsonl   {ts, is_live, viewer_count, title, category, source, http_status}
  $CHAT_FILE               chat.jsonl      {ts, id, username, content, color, badges, chatroom_id}
  $RUN_DIR/chat_stats.json                 {msgs_last_1m, msgs_per_min_5m, unique_chatters_5m,
                                            unique_chatters_15m, last_message_ts, total}
  $RUN_DIR/supervisor_events.jsonl         {ts, event, detail}
  $PID_DIR/*.pid                           one pid per file
  $LOG_DIR/supervisor.log                  free text, last lines are shown

Modes:
  (default)                    one-screen human status for --window (default 15m)
  --json                       same as one JSON object
  --compare A_FROM A_TO B_FROM B_TO
                               before/after: avg viewers, peak viewers, msgs/min, unique chatters,
                               with deltas. Bounds are UTC ISO (2026-09-24T10:00:00Z) or relative
                               (-45m, -1h30m, now).
  --iteration-summary DIR      write DIR/metrics_summary.json for the current window (creates DIR)

Environment: RUN_DIR (default <repo>/run), METRICS_FILE, CHAT_FILE, LOG_DIR, PID_DIR, KICK_CHANNEL.
Rows with is_live=null (failed API polls) never count as offline; they are reported as failed polls.
Text echoed from other processes' files (log tail, event details, titles) is stripped of control
characters and credential-like values (stream keys, passphrases, tokens) are masked.
Python 3.9 compatible, stdlib only. Exit code is 0 whenever the report could be produced
(1 if --iteration-summary could not be written, 2 on bad arguments).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

# --------------------------------------------------------------------------- paths

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_DIR = os.environ.get("RUN_DIR") or os.path.join(REPO_ROOT, "run")
METRICS_FILE = os.environ.get("METRICS_FILE") or os.path.join(RUN_DIR, "metrics.jsonl")
CHAT_FILE = os.environ.get("CHAT_FILE") or os.path.join(RUN_DIR, "chat.jsonl")
CHAT_STATS_FILE = os.path.join(RUN_DIR, "chat_stats.json")
EVENTS_FILE = os.path.join(RUN_DIR, "supervisor_events.jsonl")
LOG_DIR = os.environ.get("LOG_DIR") or os.path.join(RUN_DIR, "logs")
PID_DIR = os.environ.get("PID_DIR") or os.path.join(RUN_DIR, "pids")
SUPERVISOR_LOG = os.path.join(LOG_DIR, "supervisor.log")
CHANNEL = os.environ.get("KICK_CHANNEL", "atleastonce")
STALE_POLL_S = float(os.environ.get("REPORT_STALE_POLL_S") or 120)     # metrics older than this -> STALE
STALE_CHAT_STATS_S = float(os.environ.get("REPORT_STALE_CHAT_S") or 60)  # chat_stats.json older than this -> STALE

# --------------------------------------------------------------------------- display safety

# Anything echoed from files written by other processes (supervisor.log, event details, stream
# title, usernames) is untrusted text: strip control characters and mask credentials.
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_SECRET_RES = [
    re.compile(r"sk_[A-Za-z0-9-]+_[A-Za-z0-9_-]{8,}"),                       # Kick stream keys
    re.compile(r"(rtmps?://[^\s/]+/app/)[^\s'\"]+", re.I),                      # ingest URL with key appended
    re.compile(r"((?:passphrase|streamid|token|secret|password|api[_-]?key)=)[^\s&'\"]+", re.I),
    re.compile(r"((?:STREAM_KEY|SRT_PASSPHRASE|KICK_TOKEN)\s*[=:]\s*)[^\s'\"]+"),
]
_SECRET_VALUES = [v for v in (os.environ.get(k, "") for k in ("STREAM_KEY", "SRT_PASSPHRASE", "KICK_TOKEN"))
                  if v and len(v) >= 8]


def redact(text: Any) -> str:
    s = "" if text is None else str(text)
    for v in _SECRET_VALUES:
        s = s.replace(v, "***")
    for rx in _SECRET_RES:
        s = rx.sub(lambda m: (m.group(1) if m.lastindex else "") + "***", s)
    return s


def clean(text: Any, limit: int = 160) -> str:
    """One printable line: control chars -> space, credentials masked, truncated."""
    s = redact(text)
    s = _CTRL_RE.sub(" ", s).strip()
    return s if len(s) <= limit else s[: limit - 3] + "..."

# --------------------------------------------------------------------------- time helpers

_DUR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([smhd])", re.I)
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text: str) -> float:
    """'15m' -> 900. Accepts s/m/h/d and combinations like '1h30m'. Bare number = seconds."""
    t = (text or "").strip().lower()
    if not t:
        raise ValueError("empty duration")
    if re.fullmatch(r"\d+(?:\.\d+)?", t):
        return float(t)
    parts = _DUR_RE.findall(t)
    if not parts or "".join(n + u for n, u in parts) != t.replace(" ", ""):
        raise ValueError("bad duration %r (use e.g. 15m, 1h, 24h, 1h30m)" % text)
    return sum(float(n) * _UNIT[u] for n, u in parts)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: Any) -> Optional[datetime]:
    """ISO-8601 string (Z or offset or naive=UTC) or epoch seconds/millis -> aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1e12:  # millis
            v /= 1000.0
        try:
            return datetime.fromtimestamp(v, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return parse_ts(float(s))
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    # Python 3.9 fromisoformat wants at most 6 fractional digits.
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
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


_REL_RE = re.compile(r"^[-~+]\d")


def _shield_relative_bounds(argv: List[str]) -> List[str]:
    """argparse treats '-45m' as an option flag. Rewrite the 4 tokens after --compare so a
    leading '-' becomes '~' (parse_bound reads '~' as 'ago'). Users may also type '~45m' directly."""
    out = list(argv)
    for i, tok in enumerate(out):
        if tok == "--compare":
            for j in range(i + 1, min(i + 5, len(out))):
                if _REL_RE.match(out[j]) and out[j][0] == "-":
                    out[j] = "~" + out[j][1:]
            break
    return out


def parse_bound(text: str, now: datetime) -> datetime:
    """'now', '-45m' (or '~45m'), '+0s', or an ISO timestamp."""
    t = (text or "").strip()
    if t.lower() == "now":
        return now
    if t[:1] == "~":
        t = "-" + t[1:]
    if t[:1] in "-+" and len(t) > 1 and t[1].isdigit():
        secs = parse_duration(t[1:])
        return now - timedelta(seconds=secs) if t[0] == "-" else now + timedelta(seconds=secs)
    dt = parse_ts(t)
    if dt is None:
        raise ValueError("bad time bound %r (use ISO UTC like 2026-09-24T10:00:00Z, -45m, or now)" % text)
    return dt


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def fmt_dur(seconds: Optional[float]) -> str:
    if seconds is None:
        return "n/a"
    s = int(max(0, round(seconds)))
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if d:
        return "%dd %dh %dm" % (d, h, m)
    if h:
        return "%dh %dm %ds" % (h, m, s)
    if m:
        return "%dm %ds" % (m, s)
    return "%ds" % s


def window_label(seconds: float) -> str:
    s = int(seconds)
    if s % 86400 == 0:
        return "%dd" % (s // 86400)
    if s % 3600 == 0:
        return "%dh" % (s // 3600)
    if s % 60 == 0:
        return "%dm" % (s // 60)
    return "%ds" % s

# --------------------------------------------------------------------------- file loading


def read_jsonl(path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Return (rows_with_parsed_ts, info). Rows lacking a parsable ts are dropped. Never raises."""
    info: Dict[str, Any] = {"path": path, "exists": False, "lines": 0, "bad_lines": 0, "rows": 0}
    rows: List[Dict[str, Any]] = []
    if not os.path.isfile(path):
        return rows, info
    info["exists"] = True
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                info["lines"] += 1
                try:
                    obj = json.loads(line)
                except ValueError:
                    info["bad_lines"] += 1
                    continue
                if not isinstance(obj, dict):
                    info["bad_lines"] += 1
                    continue
                ts = parse_ts(obj.get("ts"))
                if ts is None:
                    info["bad_lines"] += 1
                    continue
                obj["_ts"] = ts
                rows.append(obj)
    except OSError as exc:
        info["error"] = str(exc)
    rows.sort(key=lambda r: r["_ts"])
    info["rows"] = len(rows)
    return rows, info


def read_json(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def tail_lines(path: str, n: int) -> Optional[List[str]]:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    return [clean(ln, 160) for ln in lines[-n:]] if n > 0 else []


def to_num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def truthy_live(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "live")
    return None

# --------------------------------------------------------------------------- metrics analysis


def in_window(rows: Iterable[Dict[str, Any]], start: datetime, end: datetime,
              inclusive_end: bool = True) -> List[Dict[str, Any]]:
    if inclusive_end:
        return [r for r in rows if start <= r["_ts"] <= end]
    return [r for r in rows if start <= r["_ts"] < end]


def viewer_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """avg/peak over samples in the given rows. avg is over live samples with a numeric count."""
    live_counts = [to_num(r.get("viewer_count")) for r in rows if truthy_live(r.get("is_live"))]
    live_counts = [c for c in live_counts if c is not None]
    all_counts = [to_num(r.get("viewer_count")) for r in rows]
    all_counts = [c for c in all_counts if c is not None]
    states = [truthy_live(r.get("is_live")) for r in rows]
    live_n = sum(1 for s in states if s)
    known_n = sum(1 for s in states if s is not None)  # failed polls (is_live null) are not "offline"
    out: Dict[str, Any] = {
        "samples": len(rows),
        "live_samples": live_n,
        "unknown_samples": len(rows) - known_n,
        "avg": round(sum(live_counts) / len(live_counts), 2) if live_counts else None,
        "peak": int(max(all_counts)) if all_counts else None,
        "min_live": int(min(live_counts)) if live_counts else None,
        "uptime_pct": round(100.0 * live_n / known_n, 1) if known_n else None,
    }
    return out


def live_state(rows: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """Current live/offline state and how long it has held, from transitions in metrics.jsonl."""
    out: Dict[str, Any] = {
        "is_live": None, "since": None, "since_is_lower_bound": None, "duration_s": None,
        "viewers_now": None, "title": None, "category": None, "last_poll": None,
        "last_poll_age_s": None, "last_http_status": None, "last_source": None,
        "transitions": 0, "first_sample": None,
        "failed_polls_trailing": 0, "last_known_poll": None, "stale": None,
    }
    if not rows:
        return out
    last_row = rows[-1]
    out["last_poll"] = iso(last_row["_ts"])
    out["last_poll_age_s"] = round((now - last_row["_ts"]).total_seconds(), 1)
    out["last_http_status"] = last_row.get("http_status")
    out["last_source"] = last_row.get("source")
    out["first_sample"] = iso(rows[0]["_ts"])
    out["stale"] = out["last_poll_age_s"] > STALE_POLL_S
    # kick_api.py writes is_live=null when the API call failed (403/429/5xx): those rows say nothing
    # about the stream, so state, run start and transitions are computed over rows with a known state.
    known = [r for r in rows if truthy_live(r.get("is_live")) is not None]
    trailing = 0
    for r in reversed(rows):
        if truthy_live(r.get("is_live")) is None:
            trailing += 1
        else:
            break
    out["failed_polls_trailing"] = trailing
    if not known:
        return out
    last = known[-1]
    state = truthy_live(last.get("is_live"))
    out["is_live"] = state
    out["last_known_poll"] = iso(last["_ts"])
    out["title"] = clean(last.get("title"), 120) or None
    out["category"] = clean(last.get("category"), 60) or None
    if state:
        vc = to_num(last.get("viewer_count"))
        out["viewers_now"] = int(vc) if vc is not None else None
    # walk back to the start of the current run
    since_idx = len(known) - 1
    for i in range(len(known) - 2, -1, -1):
        if truthy_live(known[i].get("is_live")) != state:
            break
        since_idx = i
    since = known[since_idx]["_ts"]
    out["since"] = iso(since)
    out["since_is_lower_bound"] = since_idx == 0
    out["duration_s"] = round((now - since).total_seconds(), 1)
    prev = None
    trans = 0
    for r in known:
        cur = truthy_live(r.get("is_live"))
        if prev is not None and cur != prev:
            trans += 1
        prev = cur
    out["transitions"] = trans
    return out

# --------------------------------------------------------------------------- chat analysis


def chat_window_stats(rows: List[Dict[str, Any]], start: datetime, end: datetime,
                      inclusive_end: bool = True) -> Dict[str, Any]:
    win = in_window(rows, start, end, inclusive_end)
    span_min = max((end - start).total_seconds(), 1.0) / 60.0
    users = set()
    for r in win:
        u = _chat_user(r)
        if u:
            users.add(u.lower())
    return {
        "msgs": len(win),
        "msgs_per_min": round(len(win) / span_min, 2),
        "unique_chatters": len(users),
        "top_chatters": _top_chatters(win, 3),
    }


def _chat_user(r: Dict[str, Any]) -> Optional[str]:
    u = r.get("username")
    if not u and isinstance(r.get("sender"), dict):
        u = r["sender"].get("username")
    return clean(u, 40) or None if u else None


def _top_chatters(rows: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for r in rows:
        u = _chat_user(r)
        if u:
            counts[u] = counts.get(u, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    return [{"username": u, "msgs": c} for u, c in ranked]

# --------------------------------------------------------------------------- processes / supervisor


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def process_health() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(PID_DIR):
        return out
    for path in sorted(glob.glob(os.path.join(PID_DIR, "*.pid"))):
        name = os.path.splitext(os.path.basename(path))[0]
        entry: Dict[str, Any] = {"name": name, "pid": None, "alive": None, "pidfile": path}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = fh.read().strip().split()
            pid = int(raw[0]) if raw else None
        except (OSError, ValueError):
            pid = None
        if pid is None or pid <= 0:
            entry["alive"] = False
            entry["note"] = "unreadable pidfile"
        else:
            entry["pid"] = pid
            entry["alive"] = pid_alive(pid)
        out.append(entry)
    return out


_RESTART_RE = re.compile(r"restart|respawn|relaunch", re.I)


def supervisor_events(start: datetime, end: datetime) -> Dict[str, Any]:
    rows, info = read_jsonl(EVENTS_FILE)
    out: Dict[str, Any] = {
        "file_exists": info["exists"], "events_total": len(rows),
        "ffmpeg_restarts_total": None, "ffmpeg_restarts_window": None, "last_restart": None,
        "last_event": None,
    }
    if not info["exists"]:
        return out

    def is_restart(r: Dict[str, Any]) -> bool:
        ev = str(r.get("event") or "")
        detail = str(r.get("detail") or "")
        return bool(_RESTART_RE.search(ev)) or (ev.lower() in ("ffmpeg_start", "start") and "restart" in detail.lower())

    restarts = [r for r in rows if is_restart(r)]
    out["ffmpeg_restarts_total"] = len(restarts)
    out["ffmpeg_restarts_window"] = len([r for r in restarts if start <= r["_ts"] <= end])
    if restarts:
        lr = restarts[-1]
        out["last_restart"] = {"ts": iso(lr["_ts"]), "event": clean(lr.get("event"), 40), "detail": clean(lr.get("detail"))}
    if rows:
        le = rows[-1]
        out["last_event"] = {"ts": iso(le["_ts"]), "event": clean(le.get("event"), 40), "detail": clean(le.get("detail"))}
    return out

# --------------------------------------------------------------------------- report builders


def build_status(window_s: float, now: datetime, log_lines: int = 5, window_text: Optional[str] = None) -> Dict[str, Any]:
    start = now - timedelta(seconds=window_s)
    metrics, minfo = read_jsonl(METRICS_FILE)
    chat, cinfo = read_jsonl(CHAT_FILE)
    stats = read_json(CHAT_STATS_FILE)

    state = live_state(metrics, now)
    win_rows = in_window(metrics, start, now)
    vstats = viewer_stats(win_rows)
    cwin = chat_window_stats(chat, start, now)

    last_msg_ts = None
    if stats and stats.get("last_message_ts") is not None:
        last_msg_ts = parse_ts(stats.get("last_message_ts"))
    if last_msg_ts is None and chat:
        last_msg_ts = chat[-1]["_ts"]
    stats_ts = parse_ts(stats.get("ts")) if stats else None
    stats_age = round((now - stats_ts).total_seconds(), 1) if stats_ts else None
    # chat_listener.py names the session counter total_session; older writers used total.
    stats_total = None
    if stats:
        stats_total = stats.get("total") if stats.get("total") is not None else stats.get("total_session")

    report: Dict[str, Any] = {
        "generated_at": iso(now),
        "channel": CHANNEL,
        "window": (window_text or "").strip() or window_label(window_s),
        "window_s": int(window_s),
        "window_from": iso(start),
        "window_to": iso(now),
        "run_dir": RUN_DIR,
        "stream": state,
        "viewers": {
            "now": state["viewers_now"],
            "peak": vstats["peak"],
            "avg": vstats["avg"],
            "min_live": vstats["min_live"],
            "samples": vstats["samples"],
            "live_samples": vstats["live_samples"],
            "unknown_samples": vstats["unknown_samples"],
        },
        "uptime_pct": vstats["uptime_pct"],
        "chat": {
            "stats_file": {
                "exists": stats is not None,
                "msgs_last_1m": stats.get("msgs_last_1m") if stats else None,
                "msgs_per_min_5m": stats.get("msgs_per_min_5m") if stats else None,
                "unique_chatters_5m": stats.get("unique_chatters_5m") if stats else None,
                "unique_chatters_15m": stats.get("unique_chatters_15m") if stats else None,
                "total": stats_total,
                "ts": iso(stats_ts),
                "age_s": stats_age,
                "stale": (stats_age > STALE_CHAT_STATS_S) if stats_age is not None else None,
                "connected": stats.get("connected") if stats else None,
            },
            "window": cwin,
            "last_message_ts": iso(last_msg_ts),
            "last_message_age_s": round((now - last_msg_ts).total_seconds(), 1) if last_msg_ts else None,
            "total_logged": len(chat),
        },
        "processes": process_health(),
        "supervisor": supervisor_events(start, now),
        "supervisor_log_tail": tail_lines(SUPERVISOR_LOG, log_lines),
        "supervisor_log_lines": log_lines,
        "files": {"metrics": minfo, "chat": cinfo, "chat_stats": CHAT_STATS_FILE if stats is not None else None},
    }
    return report


def build_compare(bounds: List[datetime], now: datetime) -> Dict[str, Any]:
    a0, a1, b0, b1 = bounds
    metrics, minfo = read_jsonl(METRICS_FILE)
    chat, cinfo = read_jsonl(CHAT_FILE)

    def one(s: datetime, e: datetime) -> Dict[str, Any]:
        if e < s:
            s, e = e, s
        v = viewer_stats(in_window(metrics, s, e, inclusive_end=False))
        c = chat_window_stats(chat, s, e, inclusive_end=False)
        return {
            "from": iso(s), "to": iso(e), "duration_s": int((e - s).total_seconds()),
            "avg_viewers": v["avg"], "peak_viewers": v["peak"], "metric_samples": v["samples"],
            "live_samples": v["live_samples"], "uptime_pct": v["uptime_pct"],
            "msgs": c["msgs"], "msgs_per_min": c["msgs_per_min"], "unique_chatters": c["unique_chatters"],
        }

    A = one(a0, a1)
    B = one(b0, b1)

    def delta(key: str) -> Dict[str, Any]:
        x, y = A.get(key), B.get(key)
        if x is None or y is None:
            return {"abs": None, "pct": None}
        d = round(y - x, 2)
        pct = round(100.0 * d / x, 1) if x else None
        return {"abs": d, "pct": pct}

    keys = ["avg_viewers", "peak_viewers", "msgs_per_min", "unique_chatters", "uptime_pct"]
    return {
        "generated_at": iso(now),
        "channel": CHANNEL,
        "A": A, "B": B,
        "delta": {k: delta(k) for k in keys},
        "files": {"metrics": minfo, "chat": cinfo},
    }

# --------------------------------------------------------------------------- formatting


def _nd(v: Any, fmt: str = "%s") -> str:
    return "no data" if v is None else (fmt % v)


def render_status(r: Dict[str, Any]) -> str:
    st = r["stream"]
    vw = r["viewers"]
    ch = r["chat"]
    sf = ch["stats_file"]
    cw = ch["window"]
    lines: List[str] = []
    lines.append("kick-live status  %s  %s  window %s" % (r["channel"], r["generated_at"], r["window"]))

    minfo = r["files"]["metrics"]
    poll = "last poll %s ago" % fmt_dur(st["last_poll_age_s"])
    if st["last_http_status"] is not None:
        poll += ", http %s" % st["last_http_status"]
    if st["last_source"]:
        poll += ", source %s" % st["last_source"]
    if st["failed_polls_trailing"]:
        poll += ", last %d poll%s FAILED" % (st["failed_polls_trailing"], "" if st["failed_polls_trailing"] == 1 else "s")
    if st["stale"]:
        poll += "  [STALE: poller silent >%s]" % fmt_dur(STALE_POLL_S)
    if st["is_live"] is None:
        if minfo.get("error"):
            lines.append("stream    no data (%s unreadable: %s)" % (os.path.basename(METRICS_FILE), minfo["error"]))
        elif st["last_poll"] is None:
            lines.append("stream    no data (%s missing or empty)" % os.path.basename(METRICS_FILE))
        else:
            lines.append("stream    UNKNOWN  (%d polls logged, none with a known state)  %s" % (minfo["rows"], poll))
    else:
        word = "LIVE" if st["is_live"] else "OFFLINE"
        bound = "at least " if st["since_is_lower_bound"] else ""
        lines.append("stream    %s for %s%s  (since %s, %d transition%s logged)" % (
            word, bound, fmt_dur(st["duration_s"]), st["since"], st["transitions"],
            "" if st["transitions"] == 1 else "s"))
        known = vw["samples"] - vw["unknown_samples"]
        lines.append("          uptime %s: %s  (%d live of %d samples%s)  %s" % (
            r["window"], _nd(r["uptime_pct"], "%.1f%%"), vw["live_samples"], known,
            (", %d failed" % vw["unknown_samples"]) if vw["unknown_samples"] else "", poll))
        if st["title"] or st["category"]:
            lines.append("          title: %s  |  category: %s" % (st["title"] or "-", st["category"] or "-"))

    if vw["samples"] == 0:
        lines.append("viewers   no data in window")
    else:
        if st["is_live"] is None:
            now_txt = "unknown"
        elif st["is_live"]:
            now_txt = _nd(vw["now"], "%d")
        else:
            now_txt = "offline"
        lines.append("viewers   now %s   peak %s   avg %s   (%s, %d live samples)" % (
            now_txt, _nd(vw["peak"], "%d"), _nd(vw["avg"], "%.1f"), r["window"], vw["live_samples"]))

    if not sf["exists"] and ch["total_logged"] == 0:
        lines.append("chat      no data (chat.jsonl and chat_stats.json missing or empty)")
    else:
        if sf["exists"]:
            flags = ""
            if sf.get("connected") is False:
                flags += "  [listener DISCONNECTED]"
            if sf.get("stale"):
                flags += "  [STALE: chat_stats.json %s old]" % fmt_dur(sf["age_s"])
            lines.append("chat      %s msg/min (5m)   last 1m: %s   unique 5m: %s   15m: %s   total: %s%s" % (
                _nd(sf["msgs_per_min_5m"], "%.2f") if isinstance(sf["msgs_per_min_5m"], (int, float)) and not isinstance(sf["msgs_per_min_5m"], bool) else clean(_nd(sf["msgs_per_min_5m"]), 12),
                clean(_nd(sf["msgs_last_1m"]), 12), clean(_nd(sf["unique_chatters_5m"]), 12),
                clean(_nd(sf["unique_chatters_15m"]), 12), clean(_nd(sf["total"]), 12), flags))
            prefix = "         "
        else:
            prefix = "chat     "
        top = ", ".join("%s(%d)" % (t["username"], t["msgs"]) for t in cw["top_chatters"]) or "-"
        lines.append("%s window %s: %d msgs, %.2f msg/min, %d unique   last msg %s ago   top: %s" % (
            prefix, r["window"], cw["msgs"], cw["msgs_per_min"], cw["unique_chatters"],
            fmt_dur(ch["last_message_age_s"]) if ch["last_message_age_s"] is not None else "n/a", top))

    procs = r["processes"]
    if not procs:
        lines.append("procs     no pidfiles in %s" % PID_DIR)
    else:
        parts = []
        for p in procs:
            if p["pid"] is None:
                parts.append("%s[?] BAD PIDFILE" % p["name"])
            else:
                parts.append("%s[%d] %s" % (p["name"], p["pid"], "alive" if p["alive"] else "DEAD"))
        lines.append("procs     " + "   ".join(parts))

    sv = r["supervisor"]
    if not sv["file_exists"]:
        lines.append("ffmpeg    restarts: no data (supervisor_events.jsonl absent)")
    else:
        last = sv["last_restart"]
        lines.append("ffmpeg    restarts: %d in window, %d total (%d events)%s" % (
            sv["ffmpeg_restarts_window"] or 0, sv["ffmpeg_restarts_total"] or 0, sv["events_total"],
            ("   last: %s %s" % (last["ts"], last.get("detail") or last.get("event"))) if last else ""))

    tail = r["supervisor_log_tail"]
    if tail is None:
        lines.append("log       supervisor.log not present")
    elif not tail and r.get("supervisor_log_lines", 1) <= 0:
        lines.append("log       supervisor.log present (tail hidden, --log-lines 0)")
    elif not tail:
        lines.append("log       supervisor.log is empty")
    else:
        lines.append("log       supervisor.log, last %d line%s:" % (len(tail), "" if len(tail) == 1 else "s"))
        for ln in tail:
            lines.append("          " + ln)
    return "\n".join(lines)


def render_compare(c: Dict[str, Any]) -> str:
    A, B, D = c["A"], c["B"], c["delta"]
    lines: List[str] = []
    lines.append("kick-live compare  %s  %s" % (c["channel"], c["generated_at"]))
    lines.append("  A (before): %s .. %s  (%s)  %d metric samples, %d live, %d chat msgs" % (
        A["from"], A["to"], fmt_dur(A["duration_s"]), A["metric_samples"], A["live_samples"], A["msgs"]))
    lines.append("  B (after):  %s .. %s  (%s)  %d metric samples, %d live, %d chat msgs" % (
        B["from"], B["to"], fmt_dur(B["duration_s"]), B["metric_samples"], B["live_samples"], B["msgs"]))
    if A["metric_samples"] == 0 and B["metric_samples"] == 0 and A["msgs"] == 0 and B["msgs"] == 0:
        lines.append("  no data in either window")
        return "\n".join(lines)
    lines.append("  %-17s %10s %10s %12s %8s" % ("metric", "A", "B", "delta", "pct"))

    def row(label: str, key: str, fmt: str) -> None:
        a, b = A.get(key), B.get(key)
        d = D[key]
        fa = "no data" if a is None else fmt % a
        fb = "no data" if b is None else fmt % b
        fd = "n/a" if d["abs"] is None else ("%+" + fmt[1:]) % d["abs"]
        fp = "n/a" if d["pct"] is None else "%+.1f%%" % d["pct"]
        lines.append("  %-17s %10s %10s %12s %8s" % (label, fa, fb, fd, fp))

    row("avg viewers", "avg_viewers", "%.1f")
    row("peak viewers", "peak_viewers", "%d")
    row("msgs/min", "msgs_per_min", "%.2f")
    row("unique chatters", "unique_chatters", "%d")
    row("uptime %", "uptime_pct", "%.1f")
    return "\n".join(lines)

# --------------------------------------------------------------------------- main


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="report.py",
        description="kick-live one-screen status and before/after window comparison from the runtime files.",
        epilog=("examples:\n"
                "  report.py                       human status, last 15m\n"
                "  report.py --window 1h --json    same as JSON\n"
                "  report.py --compare -45m -30m -15m now\n"
                "  report.py --compare 2026-09-24T09:00:00Z 2026-09-24T09:30:00Z 2026-09-24T09:30:00Z 2026-09-24T10:00:00Z --json\n"
                "  report.py --iteration-summary iterations/003\n"
                "env: RUN_DIR METRICS_FILE CHAT_FILE LOG_DIR PID_DIR KICK_CHANNEL"),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--window", default="15m", help="lookback for viewers/chat/uptime: 15m, 1h, 24h, 1h30m (default 15m)")
    ap.add_argument("--json", action="store_true", help="print the report as one JSON object")
    ap.add_argument("--compare", nargs=4, metavar=("A_FROM", "A_TO", "B_FROM", "B_TO"),
                    help="compare window A (before) with window B (after). Bounds: UTC ISO, -45m (or '~45m', quoted for zsh), now")
    ap.add_argument("--iteration-summary", metavar="DIR", help="write DIR/metrics_summary.json for the current window")
    ap.add_argument("--log-lines", type=int, default=5, help="lines of supervisor.log to show (default 5)")
    ap.add_argument("--now", metavar="ISO", help="override the reference time (testing); default is the real UTC now")
    ap.add_argument("--paths", action="store_true", help="print the resolved runtime file paths and exit")
    args = ap.parse_args(_shield_relative_bounds(list(sys.argv[1:] if argv is None else argv)))

    if args.paths:
        for k, v in (("RUN_DIR", RUN_DIR), ("METRICS_FILE", METRICS_FILE), ("CHAT_FILE", CHAT_FILE),
                     ("CHAT_STATS_FILE", CHAT_STATS_FILE), ("EVENTS_FILE", EVENTS_FILE),
                     ("LOG_DIR", LOG_DIR), ("PID_DIR", PID_DIR), ("SUPERVISOR_LOG", SUPERVISOR_LOG)):
            print("%-16s %s  [%s]" % (k, v, "exists" if os.path.exists(v) else "missing"))
        return 0

    now = utcnow()
    if args.now:
        parsed = parse_ts(args.now)
        if parsed is None:
            ap.error("--now must be an ISO timestamp")
        now = parsed

    try:
        window_s = parse_duration(args.window)
    except ValueError as exc:
        ap.error(str(exc))
    if window_s <= 0:
        ap.error("--window must be positive")

    if args.compare:
        try:
            bounds = [parse_bound(b, now) for b in args.compare]
        except ValueError as exc:
            ap.error(str(exc))
        cmp_report = build_compare(bounds, now)
        if args.json:
            print(json.dumps(cmp_report, indent=2, sort_keys=False, default=str))
        else:
            print(render_compare(cmp_report))
        return 0

    report = build_status(window_s, now, log_lines=max(0, args.log_lines), window_text=args.window)

    summary_error = None
    if args.iteration_summary:
        out_dir = args.iteration_summary
        out_path = os.path.join(out_dir, "metrics_summary.json")
        tmp = out_path + ".tmp"
        try:
            os.makedirs(out_dir, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(report, fh, indent=2, default=str)
                fh.write("\n")
            os.replace(tmp, out_path)
            report["iteration_summary_path"] = os.path.abspath(out_path)
        except OSError as exc:
            summary_error = "cannot write %s: %s" % (out_path, exc)
            report["iteration_summary_error"] = summary_error

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(render_status(report))
        if args.iteration_summary and not summary_error:
            print("summary   wrote %s" % report["iteration_summary_path"])
    if summary_error:
        print("report.py: error: %s" % summary_error, file=sys.stderr)
        return 1
    return 0


def _entry() -> int:
    try:
        return main()
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        # e.g. `report.py --json | head`; the reader went away, that is not an error.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except OSError:
            pass
        return 0


if __name__ == "__main__":
    sys.exit(_entry())
