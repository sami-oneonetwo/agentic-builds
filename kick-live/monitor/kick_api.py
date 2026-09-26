#!/usr/bin/env python
"""kick_api.py -- poller for the Kick public channel API (read-only).

Polls https://kick.com/api/v2/channels/<slug> with a browser User-Agent and
writes one JSON line per sample to $METRICS_FILE:

    {ts, is_live, viewer_count, title, category, followers,
     source: "api" | "hls" | "none", http_status, latency_ms, ...,
     category_live, category_viewers, our_rank}

The last three come from $RUN_DIR/category_latest.json (monitor/category_sampler.py) when that table is
younger than 20 min, else null; existing consumers keep every field they already read.

On HTTP 403/429/5xx or a network error it backs off exponentially
(2, 4, 8 ... 120 s), logs to stderr, and falls back to a liveness check on the
channel's HLS playback_url (200 with #EXTINF or a variant playlist => live).
The last good playback_url is cached in $RUN_DIR/kick_api_cache.json so the
fallback works even when the API is blocked and the process was restarted.

Importable API for other modules:

    from monitor.kick_api import get_channel, sample
    raw = get_channel("atleastonce")   # full channel JSON, raises KickApiError
    s   = sample("atleastonce")        # normalised sample dict, never raises

Python 3.9 compatible. Stdlib only.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import signal
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Paths and defaults (mirror scripts/env.sh; env wins, else sane defaults)
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_DIR = os.environ.get("RUN_DIR") or os.path.join(REPO_ROOT, "run")
METRICS_FILE = os.environ.get("METRICS_FILE") or os.path.join(RUN_DIR, "metrics.jsonl")
ACTIVITY_FILE = os.environ.get("ACTIVITY_FILE") or os.path.join(RUN_DIR, "activity.jsonl")
LOG_DIR = os.environ.get("LOG_DIR") or os.path.join(RUN_DIR, "logs")
PID_DIR = os.environ.get("PID_DIR") or os.path.join(RUN_DIR, "pids")
CHANNEL_FILE = os.path.join(RUN_DIR, "channel.json")          # --json-state output
CACHE_FILE = os.path.join(RUN_DIR, "kick_api_cache.json")     # playback_url + last is_live
CATEGORY_LATEST_FILE = os.path.join(RUN_DIR, "category_latest.json")   # written by monitor/category_sampler.py
CATEGORY_FRESH_S = 20 * 60                                    # older than this -> category_* fields are null
CATEGORY_FIELDS = ("category_live", "category_viewers", "our_rank")

DEFAULT_SLUG = os.environ.get("KICK_CHANNEL", "atleastonce")
DEFAULT_API_URL = "https://kick.com/api/v2/channels/{slug}"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 10.0
BACKOFF_START = 2.0
BACKOFF_CAP = 120.0

_VERBOSE = False


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str, level: str = "info") -> None:
    sys.stderr.write("%s [kick_api] %s: %s\n" % (utc_now_iso(), level, msg))
    sys.stderr.flush()


def debug(msg: str) -> None:
    if _VERBOSE:
        log(msg, "debug")


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    _ensure_dir(path)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_json_atomic(path: str, obj: Dict[str, Any]) -> None:
    _ensure_dir(path)
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def log_activity(actor: str, text: str) -> None:
    append_jsonl(ACTIVITY_FILE, {"ts": utc_now_iso(), "actor": actor, "text": text})


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def is_http_url(url: Any) -> bool:
    """True only for a non-empty str with an http/https scheme and a host."""
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def build_api_url(slug: str, api_url: Optional[str] = None) -> str:
    """Expand {slug} in api_url (or the default). Unknown/odd braces are left alone."""
    template = api_url or DEFAULT_API_URL
    try:
        return template.format(slug=slug)
    except (KeyError, IndexError, ValueError):
        return template.replace("{slug}", slug)


class KickApiError(Exception):
    """Raised by get_channel() on any non-200 response or network failure."""

    def __init__(self, message: str, status: Optional[int] = None, latency_ms: Optional[int] = None):
        super().__init__(message)
        self.status = status
        self.latency_ms = latency_ms


def http_get(url: str, timeout: float = DEFAULT_TIMEOUT, accept: str = "*/*") -> Tuple[int, bytes, int]:
    """GET url. Returns (status, body, latency_ms). Raises KickApiError on network error.

    HTTP error statuses are returned, not raised, so callers can branch on them.
    Only http(s) URLs are fetched; anything else (e.g. a tampered cache with a
    file:// URL) is rejected as a network error.
    """
    if not is_http_url(url):
        raise KickApiError("refusing non-http(s) url: %r" % (url,), status=None, latency_ms=0)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        },
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, body, int((time.monotonic() - t0) * 1000)
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:  # pragma: no cover - defensive
            body = b""
        return e.code, body, int((time.monotonic() - t0) * 1000)
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError,
            http.client.HTTPException, ValueError) as e:
        # HTTPException covers BadStatusLine / IncompleteRead / RemoteDisconnected
        # from a misbehaving server; ValueError covers unparsable URLs.
        reason = " ".join(str(getattr(e, "reason", None) or e or type(e).__name__).split())
        raise KickApiError("network error: %s" % reason,
                           status=None, latency_ms=int((time.monotonic() - t0) * 1000))


def get_channel(slug: str = DEFAULT_SLUG, api_url: Optional[str] = None,
                timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """Fetch the full public channel object for slug.

    Returns the parsed JSON dict. Raises KickApiError (with .status) on any
    non-200 status, unparsable body, or network error.
    """
    url = build_api_url(slug, api_url)
    status, body, latency_ms = http_get(url, timeout=timeout, accept="application/json")
    if status != 200:
        raise KickApiError("HTTP %d from %s" % (status, url), status=status, latency_ms=latency_ms)
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError as e:
        raise KickApiError("non-JSON body from %s: %s" % (url, e), status=status, latency_ms=latency_ms)
    if not isinstance(data, dict):
        raise KickApiError("unexpected JSON shape from %s" % url, status=status, latency_ms=latency_ms)
    data["_http_status"] = status
    data["_latency_ms"] = latency_ms
    return data


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def _to_int(v: Any) -> Optional[int]:
    """Kick sometimes returns counts as strings ("2") and sometimes as ints; normalise."""
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None


def _first_category_name(cats: Any) -> Optional[str]:
    if isinstance(cats, list) and cats:
        c = cats[0]
        if isinstance(c, dict):
            return c.get("name") or c.get("slug")
    return None


def parse_channel(data: Dict[str, Any], slug: str) -> Dict[str, Any]:
    """Normalise a raw channel object into a metrics sample (source 'api')."""
    ls = data.get("livestream")
    live = isinstance(ls, dict)
    is_live = bool(ls.get("is_live", True)) if live else False
    chatroom = data.get("chatroom") if isinstance(data.get("chatroom"), dict) else {}
    return {
        "ts": utc_now_iso(),
        "slug": data.get("slug") or slug,
        "is_live": is_live,
        "viewer_count": (_to_int(ls.get("viewer_count")) if live else None),
        "title": (ls.get("session_title") if live else None),
        "category": (_first_category_name(ls.get("categories")) if live else None),
        "last_category": _first_category_name(data.get("recent_categories")),
        "started_at": (ls.get("created_at") or ls.get("start_time")) if live else None,
        "followers": _to_int(data.get("followers_count")),
        "channel_id": _to_int(data.get("id")),
        "chatroom_id": _to_int(chatroom.get("id")),
        "source": "api",
        "http_status": data.get("_http_status", 200),
        "latency_ms": data.get("_latency_ms"),
    }


# ---------------------------------------------------------------------------
# HLS fallback
# ---------------------------------------------------------------------------
def hls_is_live(playback_url: str, timeout: float = DEFAULT_TIMEOUT) -> Tuple[Optional[bool], Optional[int], Optional[int]]:
    """Liveness via the HLS manifest. Returns (is_live, http_status, latency_ms).

    200 + #EXTM3U + (#EXTINF or #EXT-X-STREAM-INF) => True
    200 + #EXTM3U without either, or 4xx (IVS returns 404 when offline) => False
    200 that is not an M3U8 at all (empty body, HTML page), 5xx, non-http(s)
    URL or network error => None (unknown)
    """
    if not is_http_url(playback_url):
        log("hls fallback: invalid playback_url %r" % (playback_url,), "warn")
        return None, None, None
    try:
        status, body, latency_ms = http_get(
            playback_url, timeout=timeout,
            accept="application/vnd.apple.mpegurl,application/x-mpegURL,*/*")
    except KickApiError as e:
        log("hls fallback network error: %s" % e, "warn")
        return None, None, e.latency_ms
    if status == 200:
        text = body.decode("utf-8", "replace")
        if "#EXTM3U" not in text[:64]:
            log("hls fallback: 200 but body is not an M3U8 (%d bytes); liveness unknown" % len(body), "warn")
            return None, status, latency_ms
        live = ("#EXTINF" in text) or ("#EXT-X-STREAM-INF" in text)
        return live, status, latency_ms
    if 400 <= status < 500:
        return False, status, latency_ms
    return None, status, latency_ms


# ---------------------------------------------------------------------------
# Cache (playback_url + last known is_live), survives restarts
# ---------------------------------------------------------------------------
def load_cache(slug: str) -> Dict[str, Any]:
    cache = read_json(CACHE_FILE) or {}
    if cache.get("slug") not in (None, slug):
        cache = {}
    if not is_http_url(cache.get("playback_url")):
        cache.pop("playback_url", None)
        # Secondary source: a channel.json written by an earlier --json-state run.
        ch = read_json(CHANNEL_FILE) or {}
        if is_http_url(ch.get("playback_url")) and ch.get("slug", slug) == slug:
            cache["playback_url"] = ch["playback_url"]
    if not isinstance(cache.get("last_is_live"), bool):
        cache.pop("last_is_live", None)
    cache["slug"] = slug
    return cache


def save_cache(cache: Dict[str, Any]) -> None:
    try:
        write_json_atomic(CACHE_FILE, cache)
    except OSError as e:
        log("could not write cache %s: %s" % (CACHE_FILE, e), "warn")


# ---------------------------------------------------------------------------
# One sample (API, then HLS fallback)
# ---------------------------------------------------------------------------
def sample(slug: str = DEFAULT_SLUG, api_url: Optional[str] = None,
           playback_url: Optional[str] = None, timeout: float = DEFAULT_TIMEOUT,
           cache: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Take one sample. Never raises.

    Tries the channel API; on failure falls back to HLS liveness using
    playback_url, the cache, or a previously saved cache file. The returned
    dict always has source in {"api", "hls", "none"} and, when the API failed,
    an "error" key. "api_ok" is True only when the API answered 200.
    The raw channel object is attached under "_raw" (stripped before writing).
    """
    cache = cache if cache is not None else load_cache(slug)
    try:
        raw = get_channel(slug, api_url=api_url, timeout=timeout)
    except KickApiError as e:
        return _fallback_sample(e, slug, playback_url, timeout, cache)
    except Exception as e:  # defensive: keep the loop alive on anything unexpected
        return _fallback_sample(KickApiError("unexpected %s: %s" % (type(e).__name__, e)),
                                slug, playback_url, timeout, cache)
    s = parse_channel(raw, slug)
    s["api_ok"] = True
    s["_raw"] = raw
    if is_http_url(raw.get("playback_url")):
        cache["playback_url"] = raw["playback_url"]
    return s


def _fallback_sample(e: KickApiError, slug: str, playback_url: Optional[str],
                     timeout: float, cache: Dict[str, Any]) -> Dict[str, Any]:
    """HLS liveness sample used when the API call failed. Never raises."""
    log("api failed (%s); trying HLS fallback" % e, "warn")
    pb = playback_url if is_http_url(playback_url) else cache.get("playback_url")
    if not is_http_url(pb):
        return {
            "ts": utc_now_iso(), "slug": slug, "is_live": None, "viewer_count": None,
            "title": None, "category": None, "followers": None, "source": "none",
            "http_status": e.status, "latency_ms": e.latency_ms, "api_ok": False,
            "error": "%s; no cached playback_url for HLS fallback" % e,
        }
    try:
        live, hstatus, hlat = hls_is_live(pb, timeout=timeout)
    except Exception as ex:  # defensive
        log("hls fallback unexpected %s: %s" % (type(ex).__name__, ex), "warn")
        live, hstatus, hlat = None, None, None
    return {
        "ts": utc_now_iso(), "slug": slug, "is_live": live, "viewer_count": None,
        "title": None, "category": None, "followers": None, "source": "hls",
        "http_status": e.status, "hls_http_status": hstatus,
        "latency_ms": hlat, "api_ok": False, "error": str(e),
    }


# ---------------------------------------------------------------------------
# Category context (from monitor/category_sampler.py's category_latest.json)
# ---------------------------------------------------------------------------
def _parse_iso_utc(ts: Any) -> Optional[datetime]:
    if not isinstance(ts, str) or len(ts) < 19:
        return None
    try:
        return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def category_context(s: Dict[str, Any], path: Optional[str] = None,
                     now: Optional[datetime] = None) -> Dict[str, Any]:
    """{category_live, category_viewers, our_rank} for the sample's category, or all-null.

    Reads category_latest.json (the sampler's compact table). Values are used only when the table is
    younger than CATEGORY_FRESH_S; the entry is the one where the sampler found our slug (our_rank set),
    else the one whose name matches the sample's category. Never raises.
    """
    out: Dict[str, Any] = {k: None for k in CATEGORY_FIELDS}
    latest = read_json(path or CATEGORY_LATEST_FILE)
    if not latest:
        return out
    ts = _parse_iso_utc(latest.get("ts"))
    now = now or datetime.now(timezone.utc)
    if ts is None or (now - ts).total_seconds() > CATEGORY_FRESH_S or (now - ts).total_seconds() < -60:
        return out
    cats = latest.get("categories")
    if not isinstance(cats, dict):
        return out
    entry: Optional[Dict[str, Any]] = None
    for c in cats.values():
        if isinstance(c, dict) and c.get("our_rank") is not None and not c.get("error"):
            entry = c
            break
    if entry is None:
        name = (s.get("category") or "")
        if isinstance(name, str) and name:
            for c in cats.values():
                if isinstance(c, dict) and str(c.get("category") or "").lower() == name.lower() and not c.get("error"):
                    entry = c
                    break
    if entry is None:
        return out
    out["category_live"] = _to_int(entry.get("live_channels"))
    out["category_viewers"] = _to_int(entry.get("total_viewers"))
    # our_rank is only meaningful while we are live; a stale rank on an offline row would mislead
    out["our_rank"] = _to_int(entry.get("our_rank")) if s.get("is_live") else None
    return out


def with_category(s: Dict[str, Any]) -> Dict[str, Any]:
    """Attach the three category_* fields (null when unknown) to a sample, in place."""
    try:
        s.update(category_context(s))
    except Exception as e:  # defensive: the poller must never die on the side table
        log("category context failed: %s" % e, "warn")
        for k in CATEGORY_FIELDS:
            s.setdefault(k, None)
    return s


def self_test() -> int:
    """Offline check of category_context() against a temp table: fresh, stale, offline, missing."""
    import tempfile
    failures = []
    now = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "category_latest.json")
        table = {"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "categories": {
            "34": {"category": "Software Development", "live_channels": 8, "total_viewers": 33, "our_rank": 3},
            "242": {"category": "Games + Demos", "live_channels": 36, "total_viewers": 344, "our_rank": None}}}
        write_json_atomic(p, table)
        live = {"is_live": True, "category": "Software Development"}
        got = category_context(live, path=p, now=now)
        if got != {"category_live": 8, "category_viewers": 33, "our_rank": 3}:
            failures.append("fresh live: %r" % got)
        got = category_context({"is_live": False, "category": None}, path=p, now=now)
        if got != {"category_live": 8, "category_viewers": 33, "our_rank": None}:
            failures.append("offline keeps context, drops rank: %r" % got)
        table["categories"]["34"]["our_rank"] = None
        write_json_atomic(p, table)
        got = category_context({"is_live": True, "category": "Games + Demos"}, path=p, now=now)
        if got != {"category_live": 36, "category_viewers": 344, "our_rank": None}:
            failures.append("name match: %r" % got)
        table["ts"] = (now - timedelta(seconds=CATEGORY_FRESH_S + 5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        write_json_atomic(p, table)
        got = category_context(live, path=p, now=now)
        if got != {k: None for k in CATEGORY_FIELDS}:
            failures.append("stale must be null: %r" % got)
        got = category_context(live, path=os.path.join(td, "missing.json"), now=now)
        if got != {k: None for k in CATEGORY_FIELDS}:
            failures.append("missing must be null: %r" % got)
        with open(p, "w") as fh:
            fh.write("{not json")
        got = category_context(live, path=p, now=now)
        if got != {k: None for k in CATEGORY_FIELDS}:
            failures.append("corrupt must be null: %r" % got)
    # existing parsers still produce the legacy keys
    s = parse_channel({"slug": "x", "livestream": {"viewer_count": "2", "session_title": "t",
                                                   "categories": [{"name": "Software Development"}],
                                                   "created_at": "2026-09-26 00:04:03"}}, "x")
    with_category(s)
    for k in ("viewer_count", "is_live", "title", "category", "started_at") + CATEGORY_FIELDS:
        if k not in s:
            failures.append("missing key %s" % k)
    if s["viewer_count"] != 2 or s["is_live"] is not True:
        failures.append("parse_channel regression: %r" % s)
    for f in failures:
        log("SELF-TEST FAIL: %s" % f, "error")
    log("self-test %s (%d checks)" % ("PASS" if not failures else "FAIL", 8))
    return 0 if not failures else 1


# ---------------------------------------------------------------------------
# Loop plumbing
# ---------------------------------------------------------------------------
def public_sample(s: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in s.items() if not k.startswith("_")}


def write_channel_state(s: Dict[str, Any], cache: Dict[str, Any]) -> None:
    """Maintain $RUN_DIR/channel.json: last good full sample + playback_url."""
    raw = s.get("_raw") or {}
    state = public_sample(s)
    state["playback_url"] = raw.get("playback_url") or cache.get("playback_url")
    state["updated_at"] = utc_now_iso()
    if raw:
        chatroom = raw.get("chatroom") if isinstance(raw.get("chatroom"), dict) else {}
        state["channel_id"] = _to_int(raw.get("id"))
        state["chatroom_id"] = _to_int(chatroom.get("id"))
        state["user_id"] = _to_int(raw.get("user_id"))
        state["is_banned"] = raw.get("is_banned")
        state["vod_enabled"] = raw.get("vod_enabled")
        rc = raw.get("recent_categories")
        state["recent_categories"] = [c.get("name") for c in (rc if isinstance(rc, list) else []) if isinstance(c, dict)]
        state["livestream"] = raw.get("livestream") if isinstance(raw.get("livestream"), dict) else None
    else:
        prev = read_json(CHANNEL_FILE) or {}
        carry = ["channel_id", "chatroom_id", "user_id", "recent_categories", "followers"]
        if state.get("is_live") is not False:
            # keep old livestream details only while we do not know the channel went offline
            carry += ["livestream", "title", "category", "viewer_count"]
        for k in carry:
            if state.get(k) is None and prev.get(k) is not None:
                state[k] = prev[k]
        state["stale"] = True
    write_json_atomic(CHANNEL_FILE, state)


def handle_transition(s: Dict[str, Any], cache: Dict[str, Any]) -> None:
    """Append to $ACTIVITY_FILE when is_live flips between known states."""
    now = s.get("is_live")
    if now is None:
        return
    prev = cache.get("last_is_live")
    if prev is not None and bool(prev) != bool(now):
        if now:
            bits = [s.get("title") or "(no title)"]
            if s.get("category"):
                bits.append(s["category"])
            text = "%s went LIVE via %s: %s" % (s.get("slug"), s.get("source"), " / ".join(bits))
        else:
            text = "%s went OFFLINE (detected via %s)" % (s.get("slug"), s.get("source"))
        log(text)
        try:
            log_activity("monitor", text)
        except OSError as e:
            log("could not write activity: %s" % e, "warn")
    cache["last_is_live"] = bool(now)
    cache["last_is_live_ts"] = s.get("ts")


def _pid_path() -> str:
    return os.path.join(PID_DIR, "kick_api.pid")


def run_loop(args: argparse.Namespace) -> int:
    cache = load_cache(args.channel)
    if args.playback_url:
        cache["playback_url"] = args.playback_url
    backoff = BACKOFF_START
    count = 0
    stop = {"flag": False}

    def _stop(signum, _frame):
        log("signal %d, stopping" % signum)
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    try:
        _ensure_dir(_pid_path())
        with open(_pid_path(), "w") as fh:
            fh.write("%d\n" % os.getpid())
    except OSError as e:
        log("could not write pid file: %s" % e, "warn")

    log("polling %s every %.0fs -> %s" % (args.channel, args.interval, args.metrics_file))
    try:
        while not stop["flag"]:
            s = sample(args.channel, api_url=args.api_url, timeout=args.timeout, cache=cache)
            with_category(s)
            handle_transition(s, cache)
            try:
                append_jsonl(args.metrics_file, public_sample(s))
            except OSError as e:
                log("could not append metrics: %s" % e, "error")
            if args.json_state:
                try:
                    write_channel_state(s, cache)
                except OSError as e:
                    log("could not write channel.json: %s" % e, "warn")
            save_cache(cache)
            count += 1
            if s.get("api_ok"):
                debug("api ok live=%s viewers=%s latency=%sms" % (s["is_live"], s["viewer_count"], s["latency_ms"]))
                backoff = BACKOFF_START
                delay = args.interval
            else:
                delay = min(backoff, BACKOFF_CAP)
                log("sample via %s (is_live=%s); backing off %.0fs" % (s["source"], s["is_live"], delay), "warn")
                backoff = min(backoff * 2, BACKOFF_CAP)
            if args.max_samples and count >= args.max_samples:
                log("max samples (%d) reached" % args.max_samples)
                break
            # Sleep in small steps so signals stop us promptly.
            end = time.monotonic() + delay
            while not stop["flag"] and time.monotonic() < end:
                time.sleep(min(0.5, max(0.0, end - time.monotonic())))
    finally:
        try:
            os.remove(_pid_path())
        except OSError:
            pass
    return 0


def run_once(args: argparse.Namespace) -> int:
    cache = load_cache(args.channel)
    if args.playback_url:
        cache["playback_url"] = args.playback_url
    s = sample(args.channel, api_url=args.api_url, timeout=args.timeout, cache=cache)
    with_category(s)
    handle_transition(s, cache)
    if args.json_state:
        write_channel_state(s, cache)
    save_cache(cache)
    if args.write_metrics:
        append_jsonl(args.metrics_file, public_sample(s))
    out = public_sample(s)
    if args.raw and s.get("_raw"):
        out["raw"] = s["_raw"]
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    if s.get("source") == "none" or s.get("is_live") is None:
        log("hard failure: %s" % s.get("error", "unknown"), "error")
        return 2
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kick_api.py",
        description="Poll the Kick public channel API and append samples to metrics.jsonl. Read-only.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  kick_api.py --once                          one sample to stdout (exit 2 on hard failure)\n"
            "  kick_api.py --interval 15 --json-state      loop; also maintain $RUN_DIR/channel.json\n"
            "  kick_api.py --once --api-url https://httpbin.org/status/403\n"
            "                                              simulate a blocked API -> HLS fallback\n"
            "\nenvironment: RUN_DIR, METRICS_FILE, ACTIVITY_FILE, PID_DIR, KICK_CHANNEL (see scripts/env.sh)\n"
            "files: %s (metrics), %s (cache), %s (--json-state), %s (category context)" % (METRICS_FILE, CACHE_FILE, CHANNEL_FILE, CATEGORY_LATEST_FILE)
        ),
    )
    p.add_argument("--channel", "--slug", default=DEFAULT_SLUG, help="channel slug (default: $KICK_CHANNEL or %(default)s)")
    p.add_argument("--api-url", default=None,
                   help="override API URL; may contain {slug}. Default: " + DEFAULT_API_URL)
    p.add_argument("--playback-url", default=None, help="override/seed the HLS playback_url used for the fallback")
    p.add_argument("--interval", type=float, default=15.0, help="seconds between polls in loop mode (default: %(default)s)")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="HTTP timeout in seconds (default: %(default)s)")
    p.add_argument("--once", action="store_true", help="take one sample, print JSON to stdout, exit 0 (2 on hard failure)")
    p.add_argument("--write-metrics", action="store_true", help="with --once: also append the sample to the metrics file")
    p.add_argument("--raw", action="store_true", help="with --once: include the raw channel JSON under 'raw'")
    p.add_argument("--json-state", action="store_true", help="also maintain $RUN_DIR/channel.json (last good sample + playback_url)")
    p.add_argument("--metrics-file", default=METRICS_FILE, help="metrics JSONL path (default: $METRICS_FILE)")
    p.add_argument("--max-samples", type=int, default=0, help="loop mode: stop after N samples (0 = forever)")
    p.add_argument("--self-test", action="store_true", help="offline check of the category_* enrichment, exit 0/1")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging to stderr")
    return p


def main(argv: Optional[list] = None) -> int:
    global _VERBOSE
    args = build_parser().parse_args(argv)
    _VERBOSE = args.verbose
    if args.self_test:
        return self_test()
    if args.interval <= 0:
        log("--interval must be > 0", "error")
        return 2
    if args.timeout <= 0:
        log("--timeout must be > 0", "error")
        return 2
    if args.max_samples < 0:
        log("--max-samples must be >= 0", "error")
        return 2
    if args.playback_url is not None and not is_http_url(args.playback_url):
        log("--playback-url must be an http(s) URL", "error")
        return 2
    try:
        if args.once:
            return run_once(args)
        return run_loop(args)
    except KeyboardInterrupt:
        log("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
