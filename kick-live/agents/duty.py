#!/usr/bin/env python3
"""agents/duty.py - the on-duty agent's hands on the live show.

The compositor owns rounds/version/micro; this tool only writes the fields the concept reserves for
an external agent: agent.*, ideas[].class/status/reason, macro.*, ask.*. Every write goes through
`state_store.write_owned` (flock, re-read, set ONLY the agent-owned dotted paths, atomic replace), so a
stale round/version field this process read a moment earlier can never be resurrected (COMPOSITOR_API
8.1). Every action also appends one line to activity.jsonl (actor "agent").

In the world (WORLD.md 9) the agent is a KEEPER: a lantern, never a creature. The world reads the
fields written here through ctx (agent.heartbeat_ts -> lantern lit/dark; macro.active -> lantern
swings + `carving: <title> · asked by @who · 12:40 left`; macro.last_reload -> `last carved` /
3 traceback lines + `reverting to vX`; ideas[].class -> wall scroll `instant · a platform option next
round` / `carving next` / `declined: <reason>`). stream/world/keepers.py turns that state into the
lantern and the strip; nothing here draws.

Usage (source scripts/env.sh first, or pass --run-dir):
  duty.py heartbeat [--name claude] [--interval 30]      loop: on_duty=true + fresh heartbeat_ts (lantern lit)
  duty.py off                                             on_duty=false (clean hand-off; lantern goes dark in 120 s)
  duty.py list                                            open ideas with id/class/status + the scroll label the world shows
  duty.py classify <id> <instant|macro|declined> [--reason TEXT] [--status queued|declined|open]
                   [--param P --value V]                  instant: attach the MENU parameter the platform option applies
  duty.py macro-start --title T --file PATH --minutes N [--by USER]   lantern swings, strip `carving: T · asked by @USER`
  duty.py macro-step <PLAN|EDIT|TEST|SHIP|LIVE> [--label TEXT] [--status-line TEXT]...
  duty.py macro-done --ok|--fail [--error TEXT] [--commit SHA] [--idea ID]   ok: `last carved`; fail: 3 lines + reverting
  duty.py say TEXT                                        activity line only (actor agent)
  duty.py world                                           read-only: world.json counts, milestones, chambers, keeper strip preview
Python 3.9. stdlib only (stream.state_store / stream.world.keepers are used when importable, never required).
Never fakes a number or a name; names in activity lines pass the same blocklist filter as the screen.
"""
from __future__ import annotations

import argparse
import copy
import datetime as _dt
import json
import os
import sys
import time

RUN_DIR = os.environ.get("RUN_DIR") or os.path.expanduser("~/.local/share/kick-live/run")
STEPS = ["PLAN", "EDIT", "TEST", "SHIP", "LIVE"]
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
try:                                                   # owned-path writes (COMPOSITOR_API 8.1); stdlib-only module
    from stream.state_store import write_owned as _write_owned, OWNED_PATHS as _OWNED
except Exception:                                      # pragma: no cover - fallback keeps the old whole-file protocol
    _write_owned, _OWNED = None, None

WORLD_TERMS = {"instant": "instant · a platform option next round", "macro": "carving next", "declined": "declined"}
_name_filter_cache = {}


def shown_name(run_dir: str, name):
    """The name as the screen shows it: through the bridge's blocklist (builder #N on a hit). None -> None."""
    if not name:
        return None
    f = _name_filter_cache.get(run_dir)
    if f is None:
        try:
            from stream.chat_bridge import ChatBridge
            br = ChatBridge(run_dir, log=lambda m: None)
            br._load_blocklist(0.0)
            f = br._display_name
        except Exception:
            f = lambda n: n                            # noqa: E731 - no bridge: the name is passed through as before
        _name_filter_cache[run_dir] = f
    try:
        return f(str(name).lstrip("@"))
    except Exception:
        return None


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


def _owned_updates(before: dict, after: dict) -> dict:
    """Dotted-path updates for what `fn` changed, restricted to the agent's blocks: agent, macro, ask (whole
    block) and ideas[i].class/status/reason by INDEX (ids can collide live, journal 010). version.* changes are
    deliberately not sent: rounds.py owns version and replays the macro bump from macro.last_reload itself."""
    up = {}
    for block in ("agent", "macro", "ask"):
        if after.get(block) != before.get(block):
            up[block] = after.get(block)
    b_ideas = before.get("ideas") or []
    for idx, i in enumerate(after.get("ideas") or []):
        old = b_ideas[idx] if idx < len(b_ideas) and isinstance(b_ideas[idx], dict) else {}
        if not isinstance(i, dict):
            continue
        for f in ("class", "status", "reason"):
            if i.get(f) != old.get(f):
                up["ideas.%d.%s" % (idx, f)] = i.get(f)
    return up


def mutate(run_dir: str, fn, note: str = "") -> dict:
    sp, ap = paths(run_dir)
    d = read_state(sp)
    before = copy.deepcopy(d)
    fn(d)
    if _write_owned is not None and _OWNED is not None:
        merged = _write_owned(sp, _OWNED["agent"], _owned_updates(before, d), log=lambda m: sys.stderr.write("duty: %s\n" % m),
                              base=d if not before else None)
        # fields we own come back as written; everything else is whatever the other writers hold on disk
        for k in ("agent", "macro", "ask", "ideas", "version", "round", "session"):
            if k in merged:
                d[k] = merged[k]
    else:
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
        import signal

        def _term(signum, frame):                      # SIGTERM (supervisor / stop.sh) = the same clean hand-off as ^C
            raise KeyboardInterrupt()
        signal.signal(signal.SIGTERM, _term)
    except Exception:
        pass
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


def _scroll_label(idea: dict) -> str:
    """What the wall scroll for this idea says in the world (stream/world/keepers.py), or the raw class."""
    try:
        from stream.world.keepers import classify_scroll
        return classify_scroll(idea)["label"]
    except Exception:
        return str(idea.get("class") or "pending")


def cmd_list(a):
    d = read_state(paths(a.run_dir)[0])
    for i in d.get("ideas", []):
        print("%-7s %-8s %-9s +%s @%s  %s%s  -> scroll: %s" % (
            i.get("id"), i.get("class"), i.get("status"), i.get("plus", 0), i.get("by"), (i.get("text") or "")[:60],
            ("  [%s]" % i["reason"]) if i.get("reason") else "", _scroll_label(i)))
    ag = d.get("agent") or {}
    print("agent:", ag.get("name"), "on_duty" if ag.get("on_duty") else "off", ag.get("heartbeat_ts"))


def cmd_classify(a):
    status = a.status or {"instant": "queued", "macro": "queued", "declined": "declined"}[a.klass]
    if a.klass == "declined" and not a.reason:
        a.reason = "not this time"                    # a declined scroll always shows its reason (WORLD.md 4, 9)
    if (a.param is None) != (a.value is None):
        sys.exit("--param and --value go together")
    if a.param is not None and a.klass != "instant":
        sys.exit("--param/--value only make sense for an instant idea (a platform option next round)")
    hit = {}

    def fn(d):
        # Exactly ONE idea is updated: the first whose id matches AND (if --match given) whose text
        # contains the substring. Ids can collide (seen live: two "i-0002"), so --match disambiguates.
        for i in d.get("ideas", []):
            if i.get("id") == a.id and (not a.match or a.match.lower() in (i.get("text") or "").lower()):
                i["class"] = a.klass
                i["status"] = status
                i["reason"] = a.reason
                if a.param is not None:
                    i["param"], i["value"] = a.param, a.value
                hit.update(i)
                break
    mutate(a.run_dir, fn)
    if not hit:
        sys.exit("no idea with id %s%s" % (a.id, (" matching %r" % a.match) if a.match else ""))
    if a.param is not None:                            # param/value live outside write_owned's agent list: plain merge
        def fn2(d):
            for i in d.get("ideas", []):
                if i.get("id") == a.id and i.get("class") == a.klass and (not a.match or a.match.lower() in (i.get("text") or "").lower()):
                    i["param"], i["value"] = a.param, a.value
                    break
        _plain_merge(a.run_dir, fn2)
    world = WORLD_TERMS[a.klass] + ((": %s" % a.reason) if a.klass == "declined" else "")
    who = shown_name(a.run_dir, hit.get("by"))
    note = "keeper: scroll %s%s -> %s" % (a.id, (" by @%s" % who) if who else "", world)
    activity(paths(a.run_dir)[1], note)
    print(note)


def _plain_merge(run_dir: str, fn) -> None:
    """For the two idea fields (param/value) rounds.py lists as agent-set but write_owned does not: re-read, set,
    replace atomically under the same lock file when possible."""
    sp = paths(run_dir)[0]
    lock = None
    try:
        import fcntl
        lock = open(sp + ".lock", "a")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    except Exception:
        lock = None
    try:
        d = read_state(sp)
        fn(d)
        write_state(sp, d)
    finally:
        if lock is not None:
            try:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                lock.close()
            except Exception:
                pass


def cmd_macro_start(a):
    t0 = now_iso()
    dl = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=a.minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def fn(d):
        d["macro"] = {"active": True, "title": a.title, "requested_by": a.by, "module": a.file, "file": a.file,
                      "started_ts": t0, "deadline_ts": dl, "step": "PLAN", "step_index": 0,
                      "step_label": "1/5 planning", "status_lines": [], "last_reload": d.get("macro", {}).get("last_reload")}
    who = shown_name(a.run_dir, a.by)
    mutate(a.run_dir, fn, "keeper carving: %s%s · %d min · the lantern swings while it lands" % (
        a.title, (" · asked by @%s" % who) if who else "", a.minutes))
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
        if _write_owned is None:
            # legacy whole-file protocol only: rounds.py owns version and replays the bump from macro.last_reload
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
    m = d.get("macro", {})
    who = shown_name(a.run_dir, m.get("requested_by"))
    asked = (" · asked by @%s" % who) if who else ""
    if a.ok:
        # rounds.py replays the same rule (ok macro -> macro += 1, micro = 0) from macro.last_reload, so the
        # string is the one it will write; it is the keeper's carve announced in the world's words.
        ver = v.get("string") if _write_owned is None else "v%d.%d.0" % (int(v.get("major") or 0), int(v.get("macro") or 0) + 1)
        note = "SHIPPED %s (macro) %s · carved by the keepers%s%s" % (ver, m.get("title", ""), asked, (" · %s" % a.commit) if a.commit else "")
    else:
        first = (a.error or "unknown").strip().splitlines()[0][:80]
        note = "carving failed: %s%s · %s · reverting to %s" % (m.get("title", ""), asked, first, v.get("string") or "the last version")
    activity(paths(a.run_dir)[1], note, actor="ship" if a.ok else "fail")
    print(note)


def cmd_say(a):
    activity(paths(a.run_dir)[1], " ".join(a.text))


def cmd_world(a):
    """Read-only: what the world holds and what the keeper strip says right now. Never writes."""
    sp = paths(a.run_dir)[0]
    d = read_state(sp)
    wp = os.path.join(a.run_dir, "world.json")
    try:
        with open(wp) as fh:
            w = json.load(fh)
    except Exception as e:
        print("world.json: not readable (%s)" % (e,))
        w = {}
    pips = w.get("pips") or {}
    real = {k: p for k, p in pips.items() if not p.get("_test")}
    world = w.get("world") or {}
    asleep = sum(1 for p in real.values() if p.get("state") in ("asleep", "burrowed"))
    print("world.json: %d pips (len), %d asleep by last state, hatched_ever %d, banished %d" % (
        len(real), asleep, len(real), len(w.get("banished") or {})))
    print("milestones: ladder %r reached %r" % (world.get("milestones"), world.get("milestones_reached")))
    for c in world.get("chambers") or []:
        print("  chamber %-14s milestone %-3s opened %s by %s" % (c.get("name"), c.get("milestone"), c.get("opened_ts") or "-", c.get("by") or "-"))
    try:
        from stream.world.keepers import colony_bar, keeper_lines, lantern_state, next_milestone, chamber_name

        class _C(object):
            def __init__(self, **kw):
                self.__dict__.update(kw)

            def __getattr__(self, n):
                return None
        now = time.time()
        ships = []
        try:
            with open(os.path.join(a.run_dir, "ships.jsonl")) as fh:
                ships = [json.loads(ln) for ln in fh.read().splitlines()[-10:] if ln.strip()]
        except Exception:
            pass
        ctx = _C(agent=d.get("agent") or {}, macro=d.get("macro") or {}, version=d.get("version") or {}, ideas=d.get("ideas") or [],
                 chat_display=(d.get("chat") or {}).get("display", True), ships=ships)
        nxt = next_milestone(len(real), world.get("milestones"))
        print("next: %s" % ("%d -> %s" % (nxt, chamber_name(nxt)) if nxt else "every chamber is open"))
        print("colony bar: %s" % colony_bar(len(real))["text"])
        kl = keeper_lines(ctx, now, run_dir=a.run_dir)
        print("lantern: %s | strip: %s | %s%s" % (lantern_state(ctx, now)["state"], kl["line1"], kl["line2"],
                                                  (" | FAIL: %s" % " / ".join(kl["fail_lines"])) if kl["fail_lines"] else ""))
    except Exception as e:
        print("(keepers module not importable here: %r)" % (e,))


def main(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", default=RUN_DIR)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("heartbeat"); s.add_argument("--name", default="claude"); s.add_argument("--interval", type=int, default=30); s.set_defaults(f=cmd_heartbeat)
    s = sub.add_parser("off"); s.set_defaults(f=cmd_off)
    s = sub.add_parser("list"); s.set_defaults(f=cmd_list)
    s = sub.add_parser("classify"); s.add_argument("id"); s.add_argument("klass", choices=["instant", "macro", "declined"])
    s.add_argument("--reason"); s.add_argument("--status", choices=["queued", "declined", "open"])
    s.add_argument("--match", help="substring of the idea text, to disambiguate colliding ids")
    s.add_argument("--param", help="instant only: MENU parameter the platform option applies (e.g. weather)")
    s.add_argument("--value", help="instant only: its value (e.g. fog)"); s.set_defaults(f=cmd_classify)
    s = sub.add_parser("macro-start"); s.add_argument("--title", required=True); s.add_argument("--file", required=True)
    s.add_argument("--minutes", type=int, default=15); s.add_argument("--by"); s.set_defaults(f=cmd_macro_start)
    s = sub.add_parser("macro-step"); s.add_argument("step", choices=STEPS); s.add_argument("--label")
    s.add_argument("--status-line", action="append"); s.set_defaults(f=cmd_macro_step)
    s = sub.add_parser("macro-done"); g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--ok", action="store_true"); g.add_argument("--fail", action="store_true")
    s.add_argument("--error"); s.add_argument("--commit"); s.add_argument("--idea"); s.set_defaults(f=cmd_macro_done)
    s = sub.add_parser("say"); s.add_argument("text", nargs="+"); s.set_defaults(f=cmd_say)
    s = sub.add_parser("world"); s.set_defaults(f=cmd_world)
    a = p.parse_args(argv)
    if a.cmd == "macro-done":
        a.ok = bool(a.ok)
    a.f(a)


if __name__ == "__main__":
    main(sys.argv[1:])
