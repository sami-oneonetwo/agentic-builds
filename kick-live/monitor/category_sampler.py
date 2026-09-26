#!/usr/bin/env python
"""category_sampler.py -- where would our stream land on each honest category page? (read-only, OAuth app)

Every pass (default one per 10 min; --once for a single pass) samples, through the developer app's
client_credentials token, for each category in CATEGORIES:

  GET /public/v1/livestreams?category_id=X&sort=viewer_count&limit=100   the live list, top 100 by CCV
  GET /public/v2/livestreams?category_id=X&limit=1000 (+cursor)          only when v1 is capped at 100 or fails,
                                                                          to count every live channel (client sort)
  GET /public/v1/categories/X                                             Kick's own category viewer_count
  kick.com/api/v1/subcategories/<slug> and kick.com/stream/livestreams/en?subcategory=<slug>
                                                                          unauthenticated site fallback: OFF by
                                                                          default, `--site-fallback` opts in and is
                                                                          honoured ONLY with --once (research runs);
                                                                          never in loop mode (research doc item 3:
                                                                          site endpoints are read-only research,
                                                                          never in the live pipeline; they would
                                                                          also hit the on-air poller's IP exactly
                                                                          when the app is being rate limited)

and appends one JSON line per category to $RUN_DIR/category_samples.jsonl:

  {ts, pass_id, category_id, category, slug, live_channels, total_viewers, list_viewers, median_viewers,
   rank24_cutoff, top1_viewers, our_rank, our_viewer_count, our_would_be_rank, channels_le3, source, capped, note}

  total_viewers   Kick's category viewer_count (the number on the browse tile)
  list_viewers    sum of viewer_count over the live list we fetched (differs from total_viewers by a few: Kick
                  counts anonymous/embedded viewers per category slightly differently; both are recorded)
  rank24_cutoff   viewer_count of the 24th channel (page one is 24 tiles); null when fewer than 24 are live
  our_rank        1-based position of our slug in that list when we are live there, else null
  our_would_be_rank  1 + number of channels with more viewers than our current viewer_count (channel.json,
                  metrics.jsonl), for the categories we are not in; null when we are offline

$RUN_DIR/category_latest.json holds the compact latest table for kick_api.py, report.py and status.sh.
A --once run prints the table. Rate limiting: >= 1 s between requests, one pass per --interval (600 s,
jittered +0-60 s). On an HTTP 429 from the app the rest of that pass is skipped (the skipped categories are
recorded with error "skipped: 429 ...", never invented) and, in loop mode, the next wait doubles from the
interval (cap 1 h) until a pass completes without a 429. This never PATCHes anything; category changes are a
separate, owner-approved step.

Categories: Software Development 34, Games + Demos 242, Game Development 4037, Art 32,
Science & Technology 70, VTubers 415, Retro Games 61. "Pixel Art" is not a Kick category
(GET /categories?q=Pixel+Art returns only game titles, checked 2026-09-26), so it is listed as a note.

Environment: RUN_DIR (default <repo>/run), KICK_CHANNEL (default atleastonce), KICK_LIVE_ENV, KICK_TOKENS_FILE.
Every file (samples, latest table, channel.json, metrics.jsonl, pid) is resolved from that ONE RUN_DIR
(monitor/run_paths.py); $METRICS_FILE / $PID_DIR are honoured only when they live under it.
Python 3.9 compatible, stdlib only (monitor/kick_public_api.py does the OAuth). --self-test runs offline.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import signal
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kick_public_api as ko  # noqa: E402

from run_paths import RunPaths  # noqa: E402

REPO_ROOT = os.path.dirname(HERE)
PATHS = RunPaths()
RUN_DIR = PATHS.run_dir
PID_DIR = PATHS.pid_dir
SAMPLES_FILE = PATHS.path("category_samples.jsonl")
LATEST_FILE = PATHS.path("category_latest.json")
CHANNEL_FILE = PATHS.path("channel.json")
METRICS_FILE = PATHS.metrics
OUR_SLUG = os.environ.get("KICK_CHANNEL", "atleastonce")

# (id, name, site slug). Ids confirmed via GET /public/v1/categories?q=... on 2026-09-26.
CATEGORIES: List[Tuple[int, str, str]] = [
    (34, "Software Development", "software-development"),
    (242, "Games + Demos", "games-+-demos"),
    (4037, "Game Development", "game-development"),
    (32, "Art", "art"),
    (70, "Science & Technology", "science-technology"),
    (415, "VTubers", "vtubers"),
    (61, "Retro Games", "retro-games"),
]
NOTES = {"pixel-art": "not a Kick category: GET /public/v1/categories?q=Pixel+Art returns only game titles "
                      "(Final Fantasy: Pixel Remaster, Pixel Worlds, ...); Digital Art (1634) exists but is not "
                      "sampled (not on the research list)"}
MIN_GAP_S = 1.0          # polite spacing between HTTP requests
PAGE_ONE = 24
BACKOFF_CAP_S = 3600.0   # loop mode: after a 429 the next wait doubles from --interval, capped here


class RateLimited(Exception):
    """HTTP 429 from the public API: stop this pass, let the loop back off."""
SITE_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

_last_req = 0.0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str, level: str = "info") -> None:
    sys.stderr.write("%s [category_sampler] %s: %s\n" % (utc_now_iso(), level, msg))
    sys.stderr.flush()


def _pace() -> None:
    global _last_req
    wait = MIN_GAP_S - (time.monotonic() - _last_req)
    if wait > 0:
        time.sleep(wait)
    _last_req = time.monotonic()


def append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_json_atomic(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _int(v: Any) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- our own state
def our_state() -> Dict[str, Any]:
    """Our current viewer_count / category from channel.json (fresh) or the last metrics line."""
    out: Dict[str, Any] = {"is_live": None, "viewer_count": None, "category": None, "category_id": None, "src": None}
    ch = read_json(CHANNEL_FILE) or {}
    ts = ch.get("updated_at") or ch.get("ts")
    fresh = False
    if ts:
        try:
            age = (datetime.now(timezone.utc) - datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)).total_seconds()
            fresh = age < 180
        except ValueError:
            fresh = False
    if fresh and ch.get("slug", OUR_SLUG) == OUR_SLUG and isinstance(ch.get("is_live"), bool):
        out.update({"is_live": ch["is_live"], "viewer_count": _int(ch.get("viewer_count")),
                    "category": ch.get("category"), "src": "channel.json"})
        ls = ch.get("livestream") if isinstance(ch.get("livestream"), dict) else {}
        cats = ls.get("categories") if isinstance(ls.get("categories"), list) else []
        if cats and isinstance(cats[0], dict):
            out["category_id"] = _int(cats[0].get("id"))
        return out
    try:
        with open(METRICS_FILE, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 8192))
            lines = [ln for ln in fh.read().decode("utf-8", "replace").split("\n") if ln.strip()]
        for ln in reversed(lines):
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if isinstance(row.get("is_live"), bool):
                out.update({"is_live": row["is_live"], "viewer_count": _int(row.get("viewer_count")),
                            "category": row.get("category"), "src": "metrics.jsonl"})
                break
    except OSError:
        pass
    return out


# --------------------------------------------------------------------------- fetchers
def fetch_public_list(cat_id: int, token: str) -> Tuple[List[Dict[str, Any]], str, bool]:
    """-> (rows [{slug, viewer_count, title, started_at}], source, capped). Raises KickApiError when both fail."""
    rows: List[Dict[str, Any]] = []
    capped = False
    err1: Optional[Exception] = None
    try:
        _pace()
        r = ko.request("GET", "/livestreams", token,
                       params={"category_id": cat_id, "sort": "viewer_count", "limit": 100})
        for x in r.get("data") or []:
            if isinstance(x, dict):
                rows.append({"slug": x.get("slug"), "viewer_count": _int(x.get("viewer_count")) or 0,
                             "title": x.get("stream_title"), "started_at": x.get("started_at")})
        capped = len(rows) >= 100
        if not capped:
            return rows, "public_v1", False
    except ko.KickApiError as e:
        if e.status == 429:
            raise RateLimited(str(e))
        err1 = e
        log("v1 livestreams failed for %d: %s" % (cat_id, e), "warn")
    # v2: complete, cursor-paginated, unsorted -> client sort
    rows2: List[Dict[str, Any]] = []
    cursor = None
    try:
        for _ in range(20):  # 20 x 1000 = plenty; also a hard stop against a looping cursor
            _pace()
            params: Dict[str, Any] = {"category_id": cat_id, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            r = ko.request("GET", "/livestreams", token, params=params, base=ko.API_BASE.replace("/v1", "/v2"))
            for x in r.get("data") or []:
                if isinstance(x, dict):
                    rows2.append({"slug": (x.get("channel") or {}).get("slug") if isinstance(x.get("channel"), dict) else None,
                                  "viewer_count": _int(x.get("viewer_count")) or 0,
                                  "title": x.get("title"), "started_at": x.get("started_at")})
            nxt = (r.get("pagination") or {}).get("next_cursor") if isinstance(r.get("pagination"), dict) else None
            if not nxt or nxt == cursor:
                break
            cursor = nxt
        rows2.sort(key=lambda x: -x["viewer_count"])
        return rows2, "public_v2", False
    except ko.KickApiError as e:
        if e.status == 429:
            raise RateLimited(str(e))
        log("v2 livestreams failed for %d: %s" % (cat_id, e), "warn")
        if rows:
            return rows, "public_v1", capped  # v1 worked but was capped; report it as capped
        raise err1 or e


def fetch_public_category(cat_id: int, token: str) -> Dict[str, Any]:
    _pace()
    try:
        r = ko.request("GET", "/categories/%d" % cat_id, token)
    except ko.KickApiError as e:
        if e.status == 429:
            raise RateLimited(str(e))
        raise
    d = r.get("data") if isinstance(r.get("data"), dict) else {}
    return {"name": d.get("name"), "viewer_count": _int(d.get("viewer_count")), "tags": d.get("tags")}


def _site_get(url: str) -> Any:
    _pace()
    req = urllib.request.Request(url, headers={"User-Agent": SITE_UA, "Accept": "application/json",
                                               "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def fetch_site(slug: str) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Unauthenticated kick.com fallback (research-grade endpoints). -> (rows, category viewers)."""
    q = urllib.parse.quote(slug, safe="-")
    total = None
    try:
        sub = _site_get("https://kick.com/api/v1/subcategories/%s" % q)
        total = _int(sub.get("viewers")) if isinstance(sub, dict) else None
    except (urllib.error.URLError, OSError, ValueError) as e:
        log("site subcategory failed for %s: %s" % (slug, e), "warn")
    # The page's next_page_url DROPS the subcategory filter (checked 2026-09-26: it reads
    # /stream/livestreams/en?page=2), so we build every page URL ourselves, keep only rows whose categories[]
    # carry our slug, and dedupe by channel id.
    rows: List[Dict[str, Any]] = []
    seen = set()
    for page_no in range(1, 21):
        page = _site_get("https://kick.com/stream/livestreams/en?subcategory=%s&limit=100&sort=desc&page=%d" % (q, page_no))
        data = page.get("data") if isinstance(page, dict) else page
        if not data:
            break
        for x in data or []:
            if not isinstance(x, dict):
                continue
            cats = x.get("categories") if isinstance(x.get("categories"), list) else []
            cat_slugs = {str(c.get("slug")) for c in cats if isinstance(c, dict)}
            if cat_slugs and slug not in cat_slugs:
                continue
            ch = x.get("channel") if isinstance(x.get("channel"), dict) else {}
            key = x.get("channel_id") or ch.get("id") or ch.get("slug")
            if key in seen:
                continue
            seen.add(key)
            rows.append({"slug": ch.get("slug") or x.get("channel_slug"), "viewer_count": _int(x.get("viewer_count")) or 0,
                         "title": x.get("session_title"), "started_at": x.get("start_time")})
        if not (isinstance(page, dict) and page.get("next_page_url")):
            break
    rows.sort(key=lambda x: -x["viewer_count"])
    return rows, total


# --------------------------------------------------------------------------- one sample
def summarise(rows: List[Dict[str, Any]], ours: Dict[str, Any]) -> Dict[str, Any]:
    counts = [r["viewer_count"] for r in rows]
    out: Dict[str, Any] = {
        "live_channels": len(rows),
        "list_viewers": sum(counts),
        "median_viewers": (float(statistics.median(counts)) if counts else None),
        "rank24_cutoff": (counts[PAGE_ONE - 1] if len(counts) >= PAGE_ONE else None),
        "top1_viewers": (counts[0] if counts else None),
        "channels_le3": sum(1 for c in counts if c <= 3),
        "our_rank": None, "our_viewer_count": None, "our_would_be_rank": None,
    }
    for i, r in enumerate(rows):
        if (r.get("slug") or "").lower() == OUR_SLUG.lower():
            out["our_rank"] = i + 1
            out["our_viewer_count"] = r["viewer_count"]
            break
    if ours.get("is_live") and ours.get("viewer_count") is not None:
        vc = ours["viewer_count"]
        others = [c for r, c in zip(rows, counts) if (r.get("slug") or "").lower() != OUR_SLUG.lower()]
        out["our_would_be_rank"] = 1 + sum(1 for c in others if c > vc)
    return out


def sample_category(cat: Tuple[int, str, str], token: Optional[str], ours: Dict[str, Any],
                    pass_id: str, site_fallback: bool = False) -> Dict[str, Any]:
    """One category. Raises RateLimited on a 429 (the caller skips the rest of the pass)."""
    cat_id, name, slug = cat
    rec: Dict[str, Any] = {"ts": utc_now_iso(), "pass_id": pass_id, "category_id": cat_id, "category": name,
                           "slug": slug, "source": None, "capped": False, "total_viewers": None, "note": None}
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    if token:
        try:
            rows, src, capped = fetch_public_list(cat_id, token)
            rec["source"], rec["capped"] = src, capped
        except ko.KickApiError as e:
            errors.append("list: %s" % e)
        try:
            c = fetch_public_category(cat_id, token)
            rec["total_viewers"] = c["viewer_count"]
            if c.get("name") and c["name"] != name:
                rec["note"] = "Kick names it %r" % c["name"]
        except ko.KickApiError as e:
            errors.append("category: %s" % e)
    if rec["source"] is None and site_fallback:
        try:
            rows, total = fetch_site(slug)
            rec["source"] = "site"
            if rec["total_viewers"] is None:
                rec["total_viewers"] = total
        except (urllib.error.URLError, OSError, ValueError) as e:
            errors.append("site: %s" % e)
    if rec["source"] is None:
        rec["error"] = "; ".join(errors) or "no source"
        rec.update({"live_channels": None, "list_viewers": None, "median_viewers": None, "rank24_cutoff": None,
                    "top1_viewers": None, "channels_le3": None, "our_rank": None, "our_viewer_count": None,
                    "our_would_be_rank": None})
        return rec
    rec.update(summarise(rows, ours))
    if rec["total_viewers"] is None:
        rec["total_viewers"] = rec["list_viewers"]
        rec["note"] = ((rec["note"] + "; ") if rec["note"] else "") + "total_viewers = list sum (category endpoint unavailable)"
    if errors:
        rec["note"] = ((rec["note"] + "; ") if rec["note"] else "") + "; ".join(errors)
    return rec


def _error_rec(cat: Tuple[int, str, str], pass_id: str, error: str) -> Dict[str, Any]:
    cat_id, name, slug = cat
    rec: Dict[str, Any] = {"ts": utc_now_iso(), "pass_id": pass_id, "category_id": cat_id, "category": name,
                           "slug": slug, "source": None, "capped": False, "total_viewers": None, "note": None, "error": error}
    rec.update({"live_channels": None, "list_viewers": None, "median_viewers": None, "rank24_cutoff": None,
                "top1_viewers": None, "channels_le3": None, "our_rank": None, "our_viewer_count": None,
                "our_would_be_rank": None})
    return rec


def run_pass(site_fallback: bool = False, categories: Optional[List[Tuple[int, str, str]]] = None) -> Dict[str, Any]:
    cats = categories or CATEGORIES
    ours = our_state()
    pass_id = utc_now_iso()
    token: Optional[str] = None
    rate_limited: Optional[str] = None
    try:
        token = ko.app_token()
    except ko.KickApiError as e:
        if e.status == 429:
            rate_limited = "token endpoint 429: %s" % e
        log("no app token (%s); %s" % (e, "using site fallback" if site_fallback else "nothing to sample"), "error")
    recs: List[Dict[str, Any]] = []
    for i, cat in enumerate(cats):
        if rate_limited:
            rec = _error_rec(cat, pass_id, "skipped: %s" % rate_limited)
        else:
            try:
                rec = sample_category(cat, token, ours, pass_id, site_fallback=site_fallback)
            except RateLimited as e:
                rate_limited = "429 rate limit (%s)" % e
                log("429 on %s; skipping the remaining %d categories this pass" % (cat[1], len(cats) - i - 1), "warn")
                rec = _error_rec(cat, pass_id, "429 rate limit: %s" % e)
        recs.append(rec)
        try:
            append_jsonl(SAMPLES_FILE, rec)
        except OSError as e:
            log("could not append %s: %s" % (SAMPLES_FILE, e), "error")
    latest = {
        "ts": pass_id, "generated_at": utc_now_iso(), "our_slug": OUR_SLUG,
        "ours": {"is_live": ours.get("is_live"), "viewer_count": ours.get("viewer_count"),
                 "category": ours.get("category"), "category_id": ours.get("category_id"), "src": ours.get("src")},
        "our_category_id": next((r["category_id"] for r in recs if r.get("our_rank")), ours.get("category_id")),
        "categories": {str(r["category_id"]): {k: r.get(k) for k in (
            "category", "slug", "live_channels", "total_viewers", "list_viewers", "median_viewers", "rank24_cutoff",
            "top1_viewers", "channels_le3", "our_rank", "our_viewer_count", "our_would_be_rank", "source", "capped",
            "note", "error", "ts")} for r in recs},
        "rate_limited": rate_limited,
        "site_fallback": bool(site_fallback),
        "notes": NOTES,
        "samples_file": SAMPLES_FILE,
        "paths": PATHS.describe(),
    }
    try:
        write_json_atomic(LATEST_FILE, latest)
    except OSError as e:
        log("could not write %s: %s" % (LATEST_FILE, e), "error")
    return latest


def next_delay(interval: float, jitter: float, rate_limited: bool, prev_delay: Optional[float]) -> float:
    """Loop wait after a pass: interval + jitter normally; after a 429 double the previous wait starting from
    2 x interval, capped at BACKOFF_CAP_S. Pure, so --self-test can check it."""
    if not rate_limited:
        return interval + random.uniform(0, jitter)
    base = max(interval * 2.0, (prev_delay or 0.0) * 2.0)
    return min(base, BACKOFF_CAP_S)


def effective_site_fallback(once: bool, requested: bool) -> bool:
    """The unauthenticated kick.com endpoints are research-only: honoured with --once, never in loop mode."""
    return bool(once and requested)


# --------------------------------------------------------------------------- table
def render_table(latest: Dict[str, Any]) -> str:
    o = latest.get("ours") or {}
    hdr = "category sampler  %s  us: live=%s viewers=%s in %r (%s)" % (
        latest.get("ts"), o.get("is_live"), o.get("viewer_count"), o.get("category"), o.get("src"))
    cols = ("id", "category", "live", "cat_viewers", "list_sum", "median", "rank24_cut", "top1", "<=3", "our_rank", "would_be", "src")
    rows = [cols]
    for cid, c in sorted((latest.get("categories") or {}).items(), key=lambda kv: int(kv[0])):
        if c.get("error"):
            rows.append((cid, c.get("category"), "ERR", c.get("error")[:60], "", "", "", "", "", "", "", ""))
            continue
        rows.append((cid, c.get("category"), c.get("live_channels"), c.get("total_viewers"), c.get("list_viewers"),
                     c.get("median_viewers"), c.get("rank24_cutoff") if c.get("rank24_cutoff") is not None else "-(<24 live)",
                     c.get("top1_viewers"), c.get("channels_le3"), c.get("our_rank"), c.get("our_would_be_rank"),
                     (c.get("source") or "") + ("*capped" if c.get("capped") else "")))
    srows = [["" if v is None else str(v) for v in r] for r in rows]
    widths = [max(len(r[i]) for r in srows) for i in range(len(cols))]
    lines = [hdr] + ["  ".join(v.ljust(widths[i]) for i, v in enumerate(r)) for r in srows]
    for k, v in (latest.get("notes") or {}).items():
        lines.append("note %s: %s" % (k, v))
    return "\n".join(lines)


# --------------------------------------------------------------------------- loop
def _pid_path() -> str:
    return os.path.join(PID_DIR, "category_sampler.pid")


def run_loop(interval: float, jitter: float, site_fallback: bool, max_passes: int = 0,
             categories: Optional[List[Tuple[int, str, str]]] = None) -> int:
    stop = {"flag": False}
    if site_fallback:
        log("site fallback requested but refused in loop mode (research-only endpoints); sampling the public API only", "warn")
    site_fallback = False

    def _stop(signum, _frame):
        log("signal %d, stopping" % signum)
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        os.makedirs(PID_DIR, exist_ok=True)
        with open(_pid_path(), "w") as fh:
            fh.write("%d\n" % os.getpid())
    except OSError as e:
        log("could not write pid file: %s" % e, "warn")
    n = 0
    cats = categories or CATEGORIES
    log("sampling %d categories every %.0fs (+0-%.0fs jitter) -> %s (run_dir %s, pid %s)" % (
        len(cats), interval, jitter, SAMPLES_FILE, RUN_DIR, _pid_path()))
    if PATHS.ignored:
        log("ignored env overrides outside RUN_DIR: %s" % json.dumps(PATHS.ignored), "warn")
    prev_delay: Optional[float] = None
    try:
        while not stop["flag"]:
            t0 = time.monotonic()
            rate_limited = False
            try:
                latest = run_pass(site_fallback=False, categories=cats)
                ok = sum(1 for c in latest["categories"].values() if not c.get("error"))
                rate_limited = bool(latest.get("rate_limited"))
                log("pass done: %d/%d categories in %.0fs%s" % (ok, len(latest["categories"]), time.monotonic() - t0,
                                                              ("  [429: %s]" % latest["rate_limited"]) if rate_limited else ""))
            except Exception as e:  # keep the loop alive
                log("pass failed: %s: %s" % (type(e).__name__, e), "error")
            n += 1
            if max_passes and n >= max_passes:
                break
            wait = next_delay(interval, jitter, rate_limited, prev_delay if rate_limited else None)
            prev_delay = wait if rate_limited else None
            if rate_limited:
                log("backing off: next pass in %.0fs (cap %.0fs)" % (wait, BACKOFF_CAP_S), "warn")
            delay = max(0.0, wait - (time.monotonic() - t0))
            end = time.monotonic() + delay
            while not stop["flag"] and time.monotonic() < end:
                time.sleep(min(1.0, max(0.0, end - time.monotonic())))
    finally:
        try:
            os.remove(_pid_path())
        except OSError:
            pass
    return 0


def self_test() -> int:
    """Offline: 429 skips the rest of the pass with no further requests; the loop backoff doubles and caps;
    site fallback is never effective in loop mode; summarise() ranks correctly."""
    import tempfile
    global SAMPLES_FILE, LATEST_FILE
    fails: List[str] = []
    calls = {"n": 0, "site": 0}
    real_request, real_app_token, real_site_get, real_pace = ko.request, ko.app_token, _site_get, _pace
    saved_files = (SAMPLES_FILE, LATEST_FILE)

    def fake_request(method, path, token, params=None, body=None, base=ko.API_BASE, timeout=0):
        calls["n"] += 1
        cid = (params or {}).get("category_id")
        if path.startswith("/categories/"):
            cid = int(path.rsplit("/", 1)[1])
            if cid == 242:
                raise ko.KickApiError("GET %s -> 429: slow down" % path, status=429, body="slow down")
            return {"data": {"name": "Software Development", "viewer_count": 33}}
        if cid == 242:
            raise ko.KickApiError("GET /livestreams -> 429: slow down", status=429, body="slow down")
        return {"data": [{"slug": "a", "viewer_count": 9}, {"slug": OUR_SLUG, "viewer_count": 2}, {"slug": "b", "viewer_count": 1}]}

    def fake_site_get(url):
        calls["site"] += 1
        return {"data": []}

    try:
        with tempfile.TemporaryDirectory() as td:
            SAMPLES_FILE = os.path.join(td, "category_samples.jsonl")
            LATEST_FILE = os.path.join(td, "category_latest.json")
            ko.request, ko.app_token = fake_request, (lambda min_ttl=120: "tok")
            globals()["_site_get"] = fake_site_get
            globals()["_pace"] = lambda: None
            cats = [CATEGORIES[0], CATEGORIES[1], CATEGORIES[2], CATEGORIES[3]]
            latest = run_pass(site_fallback=True, categories=cats)   # even when asked, a 429 must not trigger the site
            c34, c242, c4037, c32 = (latest["categories"][str(c[0])] for c in cats)
            if c34.get("error") or c34.get("our_rank") != 2 or c34.get("live_channels") != 3:
                fails.append("first category should sample fine: %r" % c34)
            if not (c242.get("error") or "").startswith("429 rate limit"):
                fails.append("429 category not marked: %r" % c242.get("error"))
            for c in (c4037, c32):
                if not (c.get("error") or "").startswith("skipped: 429"):
                    fails.append("category after the 429 not skipped: %r" % c.get("error"))
            if calls["n"] != 3:   # list34 + cat34 + list242(429) ; nothing after
                fails.append("requests after the 429: %d calls (expected 3)" % calls["n"])
            if calls["site"] != 0:
                fails.append("site fallback fired on a 429 (%d calls)" % calls["site"])
            if not latest.get("rate_limited"):
                fails.append("latest.rate_limited not set")
            with open(SAMPLES_FILE) as fh:
                rows = [json.loads(ln) for ln in fh if ln.strip()]
            if len(rows) != 4 or sum(1 for r in rows if r.get("error")) != 3:
                fails.append("samples rows: %d (errors %d)" % (len(rows), sum(1 for r in rows if r.get("error"))))
        # backoff maths
        d1 = next_delay(600, 60, True, None)
        d2 = next_delay(600, 60, True, d1)
        d3 = next_delay(600, 60, True, 2000)
        if d1 != 1200 or d2 != 2400 or d3 != 3600:
            fails.append("backoff doubling/cap wrong: %s %s %s" % (d1, d2, d3))
        d0 = next_delay(600, 60, False, 2400)
        if not (600 <= d0 <= 660):
            fails.append("normal delay wrong: %s" % d0)
        if effective_site_fallback(False, True) or not effective_site_fallback(True, True) or effective_site_fallback(True, False):
            fails.append("effective_site_fallback rule wrong")
        sm = summarise([{"slug": "x", "viewer_count": 5}, {"slug": OUR_SLUG, "viewer_count": 2}, {"slug": "y", "viewer_count": 2}],
                       {"is_live": True, "viewer_count": 2})
        if sm["our_rank"] != 2 or sm["our_would_be_rank"] != 2 or sm["rank24_cutoff"] is not None or sm["channels_le3"] != 2:
            fails.append("summarise: %r" % sm)
    finally:
        ko.request, ko.app_token = real_request, real_app_token
        globals()["_site_get"], globals()["_pace"] = real_site_get, real_pace
        SAMPLES_FILE, LATEST_FILE = saved_files
    for f in fails:
        log("SELF-TEST FAIL: %s" % f, "error")
    log("self-test %s (12 checks)" % ("PASS" if not fails else "FAIL"))
    return 0 if not fails else 1


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="category_sampler.py", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog="\n".join(__doc__.split("\n\n")[1:]))
    p.add_argument("--once", action="store_true", help="one pass, print the table, exit (2 if no category could be sampled)")
    p.add_argument("--interval", type=float, default=600.0, help="seconds between passes in loop mode (default 600)")
    p.add_argument("--jitter", type=float, default=60.0, help="extra random 0..N s per interval (default 60)")
    p.add_argument("--max-passes", type=int, default=0, help="loop mode: stop after N passes (0 = forever)")
    p.add_argument("--site-fallback", action="store_true",
                   help="research runs only: with --once, fall back to the unauthenticated kick.com endpoints when both "
                        "public endpoints fail; ignored (with a warning) in loop mode")
    p.add_argument("--no-site-fallback", action="store_true", help=argparse.SUPPRESS)   # old default, now a no-op
    p.add_argument("--self-test", action="store_true", help="offline check of the 429 skip/backoff and site-fallback rules, exit 0/1")
    p.add_argument("--category", type=int, action="append", help="sample only this category id (repeatable)")
    p.add_argument("--json", action="store_true", help="with --once: print category_latest.json instead of the table")
    args = p.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.interval < 60:
        p.error("--interval must be >= 60 s (be polite to the API)")
    site = effective_site_fallback(args.once, args.site_fallback)
    cats = [c for c in CATEGORIES if not args.category or c[0] in args.category] or None
    if args.category and not cats:
        p.error("no known category among %s" % args.category)
    if args.once:
        latest = run_pass(site_fallback=site, categories=cats)
        print(json.dumps(latest, indent=1, ensure_ascii=False) if args.json else render_table(latest))
        ok = sum(1 for c in latest["categories"].values() if not c.get("error"))
        return 0 if ok else 2
    return run_loop(args.interval, args.jitter, args.site_fallback, args.max_passes, categories=cats)


if __name__ == "__main__":
    sys.exit(main())
