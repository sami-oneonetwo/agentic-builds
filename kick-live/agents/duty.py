#!/usr/bin/env python3
"""agents/duty.py - the on-duty agent's hands on the live show.

The compositor owns rounds/version/micro; this tool only writes the fields the concept reserves for
an external agent: agent.*, ideas[].class/status/reason, macro.*, ask.*. Every write re-reads the
on-disk state.json and replaces it atomically (tmp + os.replace), the same protocol rounds.py uses,
so neither side clobbers the other. Every action also appends one line to activity.jsonl so it shows
on the stream's activity feed (actor "agent").

Usage (source scripts/env.sh first, or pass --run-dir):
  duty.py heartbeat [--name claude] [--interval 30]      loop: on_duty=true + fresh heartbeat_ts
  duty.py off                                             on_duty=false (clean hand-off)
  duty.py list                                            open ideas with id/class/status
  duty.py classify <id> <instant|macro|declined> [--reason TEXT] [--status queued|declined|open]
  duty.py macro-start --title T --file PATH --minutes N [--by USER]   header shows MACRO clock
  duty.py macro-step <PLAN|EDIT|TEST|SHIP|LIVE> [--label TEXT] [--status-line TEXT]...
  duty.py macro-done --ok|--fail [--error TEXT] [--commit SHA]
  duty.py say TEXT                                        activity line only (actor agent)
Python 3.9. stdlib only. Never fakes a number or a name.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time

RUN_DIR = os.environ.get("RUN_DIR") or os.path.expanduser("~/.local/share/kick-live/run")
STEPS = ["PLAN", "EDIT", "TEST", "SHIP", "LIVE"]


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def paths(run_dir: str):
    return os.path.join(run_dir, "state.json"), os.path.join(run_dir, "activity.jsonl")


def read_state(path: str) -> dict:
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return {}


def write_state(path: str, d: dict) -> None:
    d["updated_ts"] = now_iso()
    tmp = "%s.tmp.duty.%d" % (path, os.getpid())
    with open(tmp, "w") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def activity(act_path: str, text: str, actor: str = "agent") -> None:
    with open(act_path, "a") as fh:
        fh.write(json.dumps({"ts": now_iso(), "actor": actor, "text": text[:200]}, ensure_ascii=False) + "\n")


def mutate(run_dir: str, fn, note: str = "") -> dict:
    sp, ap = paths(run_dir)
    d = read_state(sp)
    fn(d)
    write_state(sp, d)
    if note:
        activity(ap, note)
    return d


def cmd_heartbeat(a):
    sp, ap = paths(a.run_dir)

    def on(d):
        d.setdefault("agent", {}).update({"on_duty": True, "heartbeat_ts": now_iso(), "name": a.name})
    mutate(a.run_dir, on, "%s on duty: classifying !idea, building macro-ships" % a.name)
    try:
        while True:
            time.sleep(a.interval)
            mutate(a.run_dir, on)
    except KeyboardInterrupt:
        pass
    finally:
        mutate(a.run_dir, lambda d: d.setdefault("agent", {}).update({"on_duty": False}),
               "%s going off duty" % a.name)


def cmd_off(a):
    mutate(a.run_dir, lambda d: d.setdefault("agent", {}).update({"on_duty": False}), "agent off duty")
    print("off duty")


def cmd_list(a):
    d = read_state(paths(a.run_dir)[0])
    for i in d.get("ideas", []):
        print("%-7s %-8s %-9s +%s @%s  %s%s" % (i.get("id"), i.get("class"), i.get("status"), i.get("plus", 0),
                                                i.get("by"), (i.get("text") or "")[:70],
                                                ("  [%s]" % i["reason"]) if i.get("reason") else ""))
    ag = d.get("agent") or {}
    print("agent:", ag.get("name"), "on_duty" if ag.get("on_duty") else "off", ag.get("heartbeat_ts"))


def cmd_classify(a):
    status = a.status or {"instant": "queued", "macro": "queued", "declined": "declined"}[a.klass]
    hit = {}

    def fn(d):
        # Exactly ONE idea is updated: the first whose id matches AND (if --match given) whose text
        # contains the substring. Ids can collide (seen live: two "i-0002"), so --match disambiguates.
        for i in d.get("ideas", []):
            if i.get("id") == a.id and (not a.match or a.match.lower() in (i.get("text") or "").lower()):
                i["class"] = a.klass
                i["status"] = status
                i["reason"] = a.reason
                hit.update(i)
                break
    mutate(a.run_dir, fn)
    if not hit:
        sys.exit("no idea with id %s%s" % (a.id, (" matching %r" % a.match) if a.match else ""))
    note = "idea %s by @%s -> %s%s" % (a.id, hit.get("by"), a.klass, (": %s" % a.reason) if a.reason else "")
    activity(paths(a.run_dir)[1], note)
    print(note)


def cmd_macro_start(a):
    t0 = now_iso()
    dl = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=a.minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def fn(d):
        d["macro"] = {"active": True, "title": a.title, "requested_by": a.by, "module": a.file, "file": a.file,
                      "started_ts": t0, "deadline_ts": dl, "step": "PLAN", "step_index": 0,
                      "step_label": "1/5 planning", "status_lines": [], "last_reload": d.get("macro", {}).get("last_reload")}
    mutate(a.run_dir, fn, "macro-ship started: %s (requested by @%s), deadline %d min" % (a.title, a.by or "agent", a.minutes))
    print("macro started, deadline", dl)


def cmd_macro_step(a):
    idx = STEPS.index(a.step)

    def fn(d):
        m = d.setdefault("macro", {})
        m.update({"step": a.step, "step_index": idx, "step_label": a.label or "%d/5 %s" % (idx + 1, a.step.lower())})
        if a.status_line:
            m["status_lines"] = (m.get("status_lines") or [])[-6:] + list(a.status_line)
    mutate(a.run_dir, fn, "macro %s: %s" % (a.step, a.label or ""))
    print("step", a.step)


def cmd_macro_done(a):
    def fn(d):
        m = d.setdefault("macro", {})
        m.update({"active": False, "step": "LIVE" if a.ok else "SHIP", "step_index": 4 if a.ok else 3,
                  "step_label": "5/5 live" if a.ok else "build failed",
                  "last_reload": {"ts": now_iso(), "ok": bool(a.ok), "module": m.get("module"), "error": a.error, "commit": a.commit}})
        v = d.setdefault("version", {})
        if a.ok:
            v["macro"] = int(v.get("macro") or 0) + 1
            v["micro"] = 0
            v["string"] = "v%d.%d.%d" % (int(v.get("major") or 0), v["macro"], 0)
            v["shipped"] = int(v.get("shipped") or 0) + 1
            if a.commit:
                v["commit"] = a.commit
        else:
            v["failed"] = int(v.get("failed") or 0) + 1
        if a.idea:
            for i in d.get("ideas", []):
                if i.get("id") == a.idea:
                    i["status"] = "shipped" if a.ok else "failed"
    d = mutate(a.run_dir, fn)
    v = d.get("version", {})
    note = ("SHIPPED %s (macro) %s%s" % (v.get("string"), d.get("macro", {}).get("title", ""), (" · %s" % a.commit) if a.commit else "")
            if a.ok else "BUILD FAILED: %s · %s" % (d.get("macro", {}).get("title", ""), a.error or "unknown"))
    activity(paths(a.run_dir)[1], note, actor="ship" if a.ok else "fail")
    print(note)


def cmd_say(a):
    activity(paths(a.run_dir)[1], " ".join(a.text))


def main(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", default=RUN_DIR)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("heartbeat"); s.add_argument("--name", default="claude"); s.add_argument("--interval", type=int, default=30); s.set_defaults(f=cmd_heartbeat)
    s = sub.add_parser("off"); s.set_defaults(f=cmd_off)
    s = sub.add_parser("list"); s.set_defaults(f=cmd_list)
    s = sub.add_parser("classify"); s.add_argument("id"); s.add_argument("klass", choices=["instant", "macro", "declined"])
    s.add_argument("--reason"); s.add_argument("--status", choices=["queued", "declined", "open"])
    s.add_argument("--match", help="substring of the idea text, to disambiguate colliding ids"); s.set_defaults(f=cmd_classify)
    s = sub.add_parser("macro-start"); s.add_argument("--title", required=True); s.add_argument("--file", required=True)
    s.add_argument("--minutes", type=int, default=15); s.add_argument("--by"); s.set_defaults(f=cmd_macro_start)
    s = sub.add_parser("macro-step"); s.add_argument("step", choices=STEPS); s.add_argument("--label")
    s.add_argument("--status-line", action="append"); s.set_defaults(f=cmd_macro_step)
    s = sub.add_parser("macro-done"); g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--ok", action="store_true"); g.add_argument("--fail", action="store_true")
    s.add_argument("--error"); s.add_argument("--commit"); s.add_argument("--idea"); s.set_defaults(f=cmd_macro_done)
    s = sub.add_parser("say"); s.add_argument("text", nargs="+"); s.set_defaults(f=cmd_say)
    a = p.parse_args(argv)
    if a.cmd == "macro-done":
        a.ok = bool(a.ok)
    a.f(a)


if __name__ == "__main__":
    main(sys.argv[1:])
