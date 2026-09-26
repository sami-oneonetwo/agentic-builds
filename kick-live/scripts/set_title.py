#!/usr/bin/env python
"""set_title.py -- keep the Kick stream title (and custom tags) accurate from runtime state, via the OAuth app.

Title A (default):  Your name becomes a pixel settler. Type anything. AI agents build the village · Day {N} · {S} settled
Title B (--variant B): Chat spawns pixel settlers. AI keepers build your !idea live · Day {N} · {S} settled

  N = number of distinct UTC stream days: the dates of every started_at seen in $RUN_DIR/metrics.jsonl rows with
      is_live=true, plus Kick's current started_at from $RUN_DIR/channel.json (never typed by hand)
  S = len(pips) in $RUN_DIR/world.json, the real settlers record (every pip is a person who typed)

EVERY input comes from ONE resolved RUN_DIR ($RUN_DIR, else <repo>/run). $METRICS_FILE is honoured only when it
lives under that RUN_DIR (monitor/run_paths.py); `source scripts/env.sh` exports METRICS_FILE from the secrets-file
RUN_DIR, so `RUN_DIR=.../run-live set_title.py` used to read run/metrics.jsonl (missing) and print Day 1 on day 3.
The script now REFUSES (exit 2) when metrics.jsonl is missing or has no is_live rows (channel.json alone would
always give N=1), and when channel.json's live started_at date is not among the metrics days (the two files must
come from the same poller). The resolved paths and row counts are part of every decision output.

Then PATCH https://api.kick.com/public/v1/channels {"stream_title": ..., "custom_tags": [...]} with the
channel's user token (scope channel:write, refreshed by ko.user_token()) ONLY when

  * the built title differs from the channel's current stream_title (GET /public/v1/channels?slug=...), and
  * the last PATCH recorded in $RUN_DIR/title_state.json is older than --min-interval-h (default 24 h; the
    pre-registered A/B protocol is the only reason to pass a smaller value), and
  * --dry-run is not set.

custom_tags: docs.kick.com/apis/channels (read 2026-09-26) lists PatchChannelsParams = {category_id, custom_tags
(array of strings, maxItems 10), stream_title (minLength 1)}, so tags ARE supported and ride along in the same PATCH
(--no-tags to leave them). Our channel currently has custom_tags = null. There is no plain `tags` field.
category_id is deliberately NOT sent: category changes are a separate, evidence-gated, owner-approved step.

--dry-run prints exactly what would be sent and never PATCHes. Exit 0 = nothing to do or PATCHed; 3 = PATCH failed;
2 = could not build the title (missing files). Every non-dry run appends one line to $RUN_DIR/title_log.jsonl;
a --dry-run writes nothing anywhere.

Auth: the developer app only. kickapp/kick_oauth.py is used when importable ($KICKAPP_DIR, /tmp/lg-kickapp/...,
<repo>/kickapp); otherwise monitor/kick_public_api.py, which reads and writes the same tokens.json.
Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO_ROOT, "monitor"))
from run_paths import RunPaths  # noqa: E402  (RUN_DIR-only resolution; $METRICS_FILE outside RUN_DIR is ignored)

PATHS = RunPaths()
RUN_DIR = PATHS.run_dir
METRICS_FILE = PATHS.metrics
CHANNEL_FILE = PATHS.path("channel.json")
WORLD_FILE = PATHS.path("world.json")
STATE_FILE = PATHS.path("title_state.json")
LOG_FILE = PATHS.path("title_log.jsonl")
SLUG = os.environ.get("KICK_CHANNEL", "atleastonce")

TITLES = {
    "A": "Your name becomes a pixel settler. Type anything. AI agents build the village · Day {N} · {S} settled",
    "B": "Chat spawns pixel settlers. AI keepers build your !idea live · Day {N} · {S} settled",
}
# docs/research/kick-growth-2026-09-26.md, Title and tile: 10 tags, the API maximum
TAGS = ["Chat Plays", "Interactive", "Pixel Art", "AI Agents", "Community Game", "Sandbox", "No Camera",
        "Live Build", "Vote", "English"]
TITLE_WARN_LEN = 140


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_ko():
    """kick_oauth.py (worktree helper) if importable, else the stdlib twin in monitor/."""
    for d in (os.environ.get("KICKAPP_DIR"), "/tmp/lg-kickapp/kick-live/kickapp", os.path.join(REPO_ROOT, "kickapp")):
        if d and os.path.isfile(os.path.join(d, "kick_oauth.py")):
            sys.path.insert(0, d)
            try:
                import kick_oauth as ko  # type: ignore
                return ko, "kick_oauth(%s)" % d
            except ImportError:
                sys.path.pop(0)
    sys.path.insert(0, os.path.join(REPO_ROOT, "monitor"))
    import kick_public_api as ko  # type: ignore
    return ko, "monitor/kick_public_api.py"


def read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _date_of(started_at: Any) -> Optional[str]:
    if not isinstance(started_at, str) or len(started_at) < 10:
        return None
    d = started_at[:10]
    return d if d[4] == "-" and d[7] == "-" else None


def stream_days() -> Dict[str, Any]:
    """Distinct UTC dates of live started_at values. Refuses (error set) without live metrics rows: channel.json
    alone always yields N=1, which is exactly the false title this guards against."""
    days: Set[str] = set()
    rows = 0
    live_rows = 0
    exists = os.path.isfile(METRICS_FILE)
    if exists:
        with open(METRICS_FILE, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                rows += 1
                if r.get("is_live") is True:
                    live_rows += 1
                    d = _date_of(r.get("started_at"))
                    if d:
                        days.add(d)
    ch = read_json(CHANNEL_FILE) or {}
    kick_started = ch.get("started_at") or ((ch.get("livestream") or {}).get("created_at") if isinstance(ch.get("livestream"), dict) else None)
    channel_day = _date_of(kick_started) if ch.get("is_live") is True else None
    out: Dict[str, Any] = {"N": 0, "days": [], "metrics_path": METRICS_FILE, "metrics_exists": exists,
                           "metrics_rows": rows, "metrics_live_rows": live_rows, "channel_path": CHANNEL_FILE,
                           "kick_started_at": kick_started, "channel_is_live": ch.get("is_live"),
                           "channel_day": channel_day, "error": None}
    if not exists:
        out["error"] = "metrics.jsonl missing at %s (RUN_DIR=%s); refusing to derive Day N from channel.json alone" % (METRICS_FILE, RUN_DIR)
        return out
    if live_rows == 0 or not days:
        out["error"] = "%s has %d rows but no is_live=true rows with a started_at; refusing (N would be 1 by construction)" % (METRICS_FILE, rows)
        return out
    if channel_day is not None and channel_day not in days:
        # channel.json and metrics.jsonl must come from the same poller / RUN_DIR; a started_at the metrics never
        # saw means the two files disagree (mixed run dirs, or a poller that stopped appending metrics).
        out["error"] = "channel.json started_at %s (day %s) is not among metrics days %s; files disagree, refusing" % (
            kick_started, channel_day, sorted(days))
        return out
    if channel_day is not None:
        days.add(channel_day)
    out["N"], out["days"] = len(days), sorted(days)
    return out


def settled() -> Dict[str, Any]:
    w = read_json(WORLD_FILE)
    if w is None:
        return {"S": None, "error": "world.json missing or unreadable at %s" % WORLD_FILE}
    pips = w.get("pips")
    if isinstance(pips, dict):
        n = len(pips)
    elif isinstance(pips, list):
        n = len(pips)
    else:
        return {"S": None, "error": "world.json has no pips"}
    return {"S": n, "schema": w.get("schema"), "quarantined": len(w.get("quarantine") or {}), "banished": len(w.get("banished") or {})}


def build_title(variant: str, n: int, s: int) -> str:
    return TITLES[variant].format(N=n, S=s)


def current_channel(ko) -> Dict[str, Any]:
    """stream_title + custom_tags from the public API (app token, read-only); channel.json as fallback."""
    try:
        tok = ko.app_token()
        r = ko._req("GET", "/channels", tok, params={"slug": SLUG})
        data = r.get("data") or []
        if data and isinstance(data[0], dict):
            d = data[0]
            st = d.get("stream") if isinstance(d.get("stream"), dict) else {}
            return {"title": d.get("stream_title"), "custom_tags": st.get("custom_tags"),
                    "category": (d.get("category") or {}).get("name") if isinstance(d.get("category"), dict) else None,
                    "is_live": st.get("is_live"), "source": "public_api"}
    except Exception as e:  # noqa: BLE001 - fall back to the poller's file
        err = str(e)
    else:
        err = "empty data"
    ch = read_json(CHANNEL_FILE) or {}
    return {"title": ch.get("title"), "custom_tags": None, "category": ch.get("category"), "is_live": ch.get("is_live"),
            "source": "channel.json (api: %s)" % err}


def append_log(obj: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="set_title.py", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog="\n".join(__doc__.split("\n\n")[1:]))
    p.add_argument("--variant", choices=sorted(TITLES), default="A", help="title variant (default A)")
    p.add_argument("--dry-run", action="store_true", help="print the decision and the exact PATCH body; never PATCH")
    p.add_argument("--no-tags", action="store_true", help="do not send custom_tags")
    p.add_argument("--min-interval-h", type=float, default=24.0,
                   help="refuse to PATCH within this many hours of the last PATCH (default 24; A/B blocks only)")
    p.add_argument("--json", action="store_true", help="machine-readable decision on stdout")
    args = p.parse_args(argv)

    ko, ko_src = load_ko()
    days = stream_days()
    st = settled()
    if st.get("S") is None:
        print("set_title: cannot build title: %s" % st.get("error"), file=sys.stderr)
        return 2
    if days.get("error") or days["N"] == 0:
        print("set_title: cannot build title: %s" % (days.get("error") or "no live started_at"), file=sys.stderr)
        print("set_title: paths: %s" % json.dumps(PATHS.describe(), ensure_ascii=False), file=sys.stderr)
        return 2
    title = build_title(args.variant, days["N"], st["S"])
    cur = current_channel(ko)
    state = read_json(STATE_FILE) or {}
    last_patch = state.get("last_patch_ts")
    since_h = None
    if isinstance(last_patch, str):
        try:
            since_h = (time.time() - datetime.strptime(last_patch[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()) / 3600.0
        except ValueError:
            since_h = None

    body: Dict[str, Any] = {"stream_title": title}
    if not args.no_tags and (cur.get("custom_tags") or None) != TAGS:
        body["custom_tags"] = TAGS
    title_differs = (cur.get("title") or "") != title
    tags_differ = "custom_tags" in body
    window_ok = since_h is None or since_h >= args.min_interval_h
    reasons = []
    if not title_differs and not tags_differ:
        reasons.append("title and tags already current")
    elif not title_differs:
        reasons.append("title current; only tags differ")
    if not window_ok:
        reasons.append("last PATCH %.1f h ago < %.0f h" % (since_h, args.min_interval_h))
    would_patch = (title_differs or tags_differ) and window_ok
    if not title_differs and tags_differ:
        # tags alone still count as a write: respect the same window
        would_patch = window_ok

    decision = {
        "ts": utc_now_iso(), "variant": args.variant, "title": title, "title_len": len(title),
        "N": days["N"], "days": days["days"], "S": st["S"], "kick_started_at": days["kick_started_at"],
        "metrics_path": days["metrics_path"], "metrics_rows": days["metrics_rows"], "metrics_live_rows": days["metrics_live_rows"],
        "channel_day": days["channel_day"], "paths": PATHS.describe(),
        "world_path": WORLD_FILE, "state_path": STATE_FILE,
        "current_title": cur.get("title"), "current_tags": cur.get("custom_tags"), "current_source": cur.get("source"),
        "current_category": cur.get("category"), "is_live": cur.get("is_live"),
        "title_differs": title_differs, "tags_differ": tags_differ, "last_patch_ts": last_patch,
        "hours_since_last_patch": (round(since_h, 2) if since_h is not None else None),
        "would_patch": would_patch, "reasons": reasons, "body": body, "dry_run": args.dry_run, "auth": ko_src,
        "patched": False, "error": None,
    }
    if len(title) > TITLE_WARN_LEN:
        decision["warning"] = "title is %d chars (> %d), Kick may truncate" % (len(title), TITLE_WARN_LEN)

    if would_patch and not args.dry_run:
        try:
            tok = ko.user_token()
            ko._req("PATCH", "/channels", tok, json=body)
            decision["patched"] = True
            new_state = {"last_patch_ts": decision["ts"], "last_title": title, "variant": args.variant,
                         "tags": body.get("custom_tags", state.get("tags")), "N": days["N"], "S": st["S"]}
            tmp = STATE_FILE + ".tmp.%d" % os.getpid()
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(new_state, fh, indent=2)
            os.replace(tmp, STATE_FILE)
        except Exception as e:  # noqa: BLE001
            decision["error"] = str(e)[:300]
    if not args.dry_run:   # dry runs touch nothing in RUN_DIR
        append_log({k: v for k, v in decision.items() if k not in ("days",)})

    if args.json:
        print(json.dumps(decision, ensure_ascii=False, indent=1))
    else:
        print("set_title %s%s" % ("DRY-RUN " if args.dry_run else "", decision["ts"]))
        print("  variant %s  N=%d (days %s)  S=%d  auth=%s" % (args.variant, days["N"], ", ".join(days["days"]), st["S"], ko_src))
        print("  run_dir: %s" % RUN_DIR)
        print("  metrics: %s  (%d rows, %d live; channel.json day %s)" % (METRICS_FILE, days["metrics_rows"], days["metrics_live_rows"], days["channel_day"]))
        print("  world:   %s   state: %s" % (WORLD_FILE, STATE_FILE))
        if PATHS.ignored:
            print("  note:    ignored env overrides outside RUN_DIR: %s" % json.dumps(PATHS.ignored))
        print("  current: %r  tags=%r  (%s)" % (cur.get("title"), cur.get("custom_tags"), cur.get("source")))
        print("  title:   %r  (%d chars)" % (title, len(title)))
        print("  body:    %s" % json.dumps(body, ensure_ascii=False))
        print("  would PATCH: %s%s" % (would_patch, ("  [" + "; ".join(reasons) + "]") if reasons else ""))
        if decision.get("warning"):
            print("  warning: %s" % decision["warning"])
        if args.dry_run:
            print("  dry-run: nothing sent")
        elif decision["patched"]:
            print("  PATCHED /public/v1/channels; state -> %s" % STATE_FILE)
        elif decision["error"]:
            print("  PATCH FAILED: %s" % decision["error"])
    if decision["error"]:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
