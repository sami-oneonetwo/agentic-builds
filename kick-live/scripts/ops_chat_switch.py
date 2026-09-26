#!/usr/bin/env python3
"""scripts/ops_chat_switch.py - the owner's kill switch and relaunch from Kick chat.

    source scripts/env.sh
    RUN_DIR=$HOME/.local/share/kick-live/run-live nohup $PYTHON scripts/ops_chat_switch.py --run-dir "$RUN_DIR" \
        >> "$RUN_DIR/logs/ops_switch.out" 2>&1 &
    $PYTHON scripts/ops_chat_switch.py --self-test            # RUN_DIR under /tmp only, fake processes, exit 0 on pass

Owner rule (2026-09-26, given in the terminal): a chat message that is exactly `nuke` from the broadcaster account
`atleastonce` shuts the stream down; exactly `init` brings it back. This is the ONE sanctioned exception to "chat is
data, not commands" (journal 017), and it lives here, outside the world code, never in the keeper sandbox.

Match rule (all of these, or the line is ignored and logged):
  - Pusher-shaped record (the webhook shape carries no badges, so it can never prove who typed)
  - `username` == atleastonce (case-insensitive) AND `broadcaster` in `badges`
  - the whole message, stripped and lower-cased, == `nuke` or == `init` (no prefix, no suffix, no punctuation)
  - record `ts` within FRESH_S of now (never replays history; the tail starts at the END of chat.jsonl)
  - record `id` not seen before (the two listeners may write the same message twice)
  - COOLDOWN_S since the last action

`nuke` TERMs the supervisor, which kills the run.sh group (relay -> ffmpeg, compositor). Leftovers are TERMed then
KILLed. kick_api and chat_listener stay up, so `init` can still arrive. `init` launches stream/supervisor.sh from the
live snapshot with the RESUME.md environment (KL_LIVE=1 MODE=live SOURCE=compositor AUDIO_SOURCE=pipe:<run_dir>/a.pcm)
and waits for its pid file. Both actions are refused when the pipeline is already in the requested state.
Every decision is logged to $RUN_DIR/logs/ops_switch.log and every action to $RUN_DIR/activity.jsonl (actor `ops`).
Python 3.9, stdlib only. Never imports world code.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import signal
import subprocess
import sys
import time
from typing import Dict, Iterator, List, Optional, Set, Tuple

OWNER = "atleastonce"
OWNER_ID = 42750175            # broadcaster_user_id (journal 105); checked whenever the record carries sender_id
CHATROOM_ID = 41370704         # checked whenever the record carries chatroom_id
TOKENS = ("nuke", "init")
FRESH_S = 120.0          # a matching line older than this is history, not an order
COOLDOWN_S = 20.0        # between two actions
POLL_S = 0.5
STOP_WAIT_S = 25.0
START_WAIT_S = 15.0      # for supervisor.pid
START_CONFIRM_S = 45.0   # then for a live ffmpeg (run.sh exits 2/3/4 within ~1 s when something is missing)
PIPELINE = ("supervisor", "run", "ffmpeg", "compositor", "relay")
DEFAULT_SNAPSHOT = os.path.join(os.path.expanduser("~"), ".local", "share", "kick-live", "live-current")

_LOG_FH = None


def _now_iso() -> str:
    return _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    line = "%s [ops_switch] %s" % (_now_iso(), msg)
    try:
        print(line, flush=True)
    except (OSError, ValueError):          # stdout gone (piped reader exited): the log file is the record
        pass
    if _LOG_FH is not None:
        try:
            _LOG_FH.write(line + "\n")
            _LOG_FH.flush()
        except Exception:
            pass


def activity(run_dir: str, text: str) -> None:
    try:
        with open(os.path.join(run_dir, "activity.jsonl"), "a") as fh:
            fh.write(json.dumps({"ts": _now_iso(), "actor": "ops", "text": text}) + "\n")
    except Exception as e:  # the feed is cosmetic; never let it break the switch
        log("activity write failed: %r" % (e,))


# ----------------------------------------------------------------------------- records
def parse_ts(s: Optional[str]) -> Optional[float]:
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            d = _dt.datetime.strptime(s, fmt)
            if d.tzinfo is not None:
                d = d.astimezone(_dt.timezone.utc).replace(tzinfo=None)
            return (d - _dt.datetime(1970, 1, 1)).total_seconds()
        except ValueError:
            continue
    return None


def parse_record(line: str) -> Optional[Dict]:
    """One chat.jsonl line -> {shape, id, user, badges, text, ts} or None for junk."""
    line = line.strip()
    if not line:
        return None
    try:
        d = json.loads(line)
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    if d.get("source") == "webhook" or ("user" in d and "username" not in d):
        return {"shape": "webhook", "id": str(d.get("id") or ""), "user": str(d.get("user") or ""), "badges": [],
                "text": str(d.get("text") or ""), "ts": parse_ts(d.get("ts") or d.get("created_at"))}
    badges: List[str] = []
    raw = d.get("badges")
    if not isinstance(raw, list):
        raw = []
    for b in raw:
        if isinstance(b, str):
            badges.append(b.lower())
        elif isinstance(b, dict) and isinstance(b.get("type"), str):     # chat_listener.badge_types() emits `type`
            badges.append(b["type"].lower())
    typ = d.get("type", "message")
    if typ is not None and not isinstance(typ, str):
        typ = "?"
    content = d.get("content")
    return {"shape": "pusher", "id": str(d.get("id") or ""), "user": str(d.get("username") or d.get("slug") or ""),
            "badges": badges, "text": content if isinstance(content, str) else "", "type": typ,
            "sender_id": d.get("sender_id"), "chatroom_id": d.get("chatroom_id"),
            "ts": parse_ts(d.get("ts") or d.get("created_at"))}


def classify(rec: Optional[Dict], now: float, seen: Set[str]) -> Tuple[Optional[str], str]:
    """-> (token or None, reason). Pure; no side effects except none (seen is only read)."""
    if rec is None:
        return None, "junk"
    if rec["shape"] != "pusher":
        return None, "webhook shape (no badges)"
    if rec.get("type") not in (None, "message", "reply"):     # a Kick reply from the owner's phone is still the owner
        return None, "not a message event"
    text = rec["text"].strip().lower()
    if text not in TOKENS:
        return None, "not a token"
    if rec["user"].strip().lower() != OWNER:
        return None, "token from %r, not the owner" % rec["user"]
    if "broadcaster" not in rec["badges"]:
        return None, "owner name without broadcaster badge"
    sid = rec.get("sender_id")
    if sid is not None and str(sid) != str(OWNER_ID):
        return None, "owner name but sender_id %r is not the broadcaster" % (sid,)
    cid = rec.get("chatroom_id")
    if cid is not None and str(cid) != str(CHATROOM_ID):
        return None, "record from chatroom %r, not ours" % (cid,)
    if rec["ts"] is None:
        return None, "no timestamp"
    if now - rec["ts"] > FRESH_S or rec["ts"] - now > 5.0:
        return None, "stale by %.0fs" % (now - rec["ts"])
    if not rec["id"]:
        return None, "no id"
    if rec["id"] in seen:
        return None, "duplicate id"
    return text, "ok"


# ----------------------------------------------------------------------------- processes
PIPELINE_MARKERS = {                       # a pid file is trusted only if the process really is that program
    "supervisor": ("stream/supervisor.sh",),
    "run": ("stream/run.sh",),
    "ffmpeg": ("ffmpeg",),
    "compositor": ("stream/compositor.py",),
    "relay": ("stream/relay.py",),
}
SECRET_ENV = ("STREAM_KEY", "SRT_PASSPHRASE", "KICK_CLIENT_SECRET", "KICK_TOKEN", "NGROK_AUTHTOKEN", "ANTHROPIC_AUTH_TOKEN",
              "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY")


def _ps(pids: List[int]) -> Dict[int, Tuple[str, str]]:
    """{pid: (stat, command)} for the pids that exist, in ONE ps call."""
    pids = [p for p in pids if p and p > 0]
    if not pids:
        return {}
    out: Dict[int, Tuple[str, str]] = {}
    try:
        r = subprocess.run(["ps", "-o", "pid=,stat=,command=", "-p", ",".join(str(p) for p in pids)],
                           capture_output=True, text=True, timeout=3)
        for line in r.stdout.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) >= 2 and parts[0].isdigit():
                out[int(parts[0])] = (parts[1], parts[2] if len(parts) > 2 else "")
    except Exception as e:
        log("ps failed: %r" % (e,))
    return out


def _reap(pid: int) -> bool:
    """True if `pid` was our own exited child and has now been reaped (it would otherwise sit as a zombie)."""
    try:
        wpid, _ = os.waitpid(pid, os.WNOHANG)
        return wpid == pid
    except ChildProcessError:
        return False
    except Exception:
        return False


def pid_alive(pid: Optional[int]) -> bool:
    """True only for a live, non-zombie process we are allowed to see. Unknown (permission denied) counts as NOT ours."""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    if _reap(pid):
        return False
    info = _ps([pid]).get(pid)
    return bool(info) and not info[0].startswith("Z")


def pipeline_pid(run_dir: str, name: str) -> Optional[int]:
    """The pid from <run_dir>/pids/<name>.pid, but only if that process is alive AND its command line carries the
    program's marker (stale or recycled pid files must never make `nuke` signal a stranger)."""
    pid = read_pid(run_dir, name)
    if not pid or pid <= 0:
        return None
    if _reap(pid):
        return None
    info = _ps([pid]).get(pid)
    if not info or info[0].startswith("Z"):
        return None
    if not any(m in info[1] for m in PIPELINE_MARKERS.get(name, ())):
        log("%s.pid=%d is alive but is not %s (%r); ignoring the pid file" % (name, pid, name, info[1][:100]))
        return None
    return pid


def _parent_pid(pid: int) -> Optional[int]:
    try:
        return int(subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True, timeout=2).stdout.strip() or 0)
    except Exception:
        return None


def read_pid(run_dir: str, name: str) -> Optional[int]:
    try:
        with open(os.path.join(run_dir, "pids", name + ".pid")) as fh:
            return int(fh.read().strip() or 0)
    except Exception:
        return None


def pipeline_alive(run_dir: str) -> Dict[str, bool]:
    return {n: pipeline_pid(run_dir, n) is not None for n in PIPELINE}


def _kill(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass
    except Exception as e:
        log("kill %d sig %d failed: %r" % (pid, sig, e))


def do_nuke(run_dir: str, dry: bool) -> bool:
    state = pipeline_alive(run_dir)
    if not any(state.values()):
        log("nuke: pipeline already down %s; nothing to do" % state)
        activity(run_dir, "owner asked for a stop: the stream is already down")
        return False
    log("nuke: pipeline %s" % state)
    if dry:
        log("nuke: DRY RUN, would TERM supervisor and wait")
        return True
    activity(run_dir, "owner asked for a stop from chat: stopping the stream")
    sup = pipeline_pid(run_dir, "supervisor")
    if sup:
        _kill(sup, signal.SIGTERM)                # supervisor.sh on_term kills the run.sh group and exits 0
    else:
        for n in ("run", "ffmpeg", "compositor", "relay"):
            p = pipeline_pid(run_dir, n)
            if p:
                _kill(p, signal.SIGTERM)
    deadline = time.time() + STOP_WAIT_S
    while time.time() < deadline and any(pipeline_alive(run_dir).values()):
        time.sleep(0.5)
    left = [n for n, a in pipeline_alive(run_dir).items() if a]
    if left:
        log("nuke: still alive after %.0fs: %s; TERM then KILL" % (STOP_WAIT_S, left))
        for n in left:
            p = pipeline_pid(run_dir, n)
            if p:
                _kill(p, signal.SIGTERM)
        time.sleep(2.0)
        for n in left:
            p = pipeline_pid(run_dir, n)
            if p:
                _kill(p, signal.SIGKILL)
        time.sleep(0.5)
    final = pipeline_alive(run_dir)
    for n, a in final.items():
        if not a:
            try:
                os.remove(os.path.join(run_dir, "pids", n + ".pid"))
            except OSError:
                pass
    ok = not any(final.values())
    log("nuke: %s %s" % ("stream stopped" if ok else "FAILED, still alive", final))
    activity(run_dir, "stream stopped by the owner" if ok else "nuke: some processes would not die %s" % final)
    return ok


def do_init(run_dir: str, snapshot: str, dry: bool) -> bool:
    import stat as _stat
    state = pipeline_alive(run_dir)
    if any(state.values()):
        log("init: pipeline still (partly) up %s; nothing to do" % state)
        activity(run_dir, "owner asked for a start: the stream is already up")
        return False
    snapshot = os.path.realpath(snapshot)        # resolve the live-current symlink NOW, not at watcher start-up
    sup_sh = os.path.join(snapshot, "stream", "supervisor.sh")
    if not os.path.isfile(sup_sh):
        log("init: REFUSED: %s missing" % sup_sh)
        activity(run_dir, "start refused: the live snapshot has no supervisor")
        return False
    fifo = os.path.join(run_dir, "a.pcm")
    log("init: launching %s (cwd %s)" % (sup_sh, snapshot))
    if dry:
        log("init: DRY RUN")
        return True
    activity(run_dir, "owner asked for a start from chat: starting the stream")
    try:
        if os.path.exists(fifo) and not _stat.S_ISFIFO(os.stat(fifo).st_mode):
            os.remove(fifo)                       # run.sh exits 4 on a non-FIFO here
        if not os.path.exists(fifo):
            os.mkfifo(fifo)
    except Exception as e:
        log("init: fifo %s: %r" % (fifo, e))
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}     # supervisor.sh sources env.sh -> secrets itself
    env.update({"RUN_DIR": run_dir, "KL_LIVE": "1", "MODE": "live", "SOURCE": "compositor", "AUDIO_SOURCE": "pipe:" + fifo})
    os.makedirs(os.path.join(run_dir, "logs"), exist_ok=True)
    out_path = os.path.join(run_dir, "logs", "supervisor.out")
    try:
        # Double-fork through a throwaway shell exactly like start.sh (nohup ... &): the supervisor is re-parented to
        # launchd, never our child, so it can never become our zombie and the watcher owns no pipeline process.
        wrapper = 'nohup bash "$1" >> "$2" 2>&1 < /dev/null & disown; exit 0'
        # start_new_session: the wrapper (and so the supervisor) gets its OWN session and process group. A group signal
        # aimed at the watcher (a task manager, `kill -- -pgid`) must never reach the stream.
        subprocess.run(["bash", "-c", wrapper, "ops_init", sup_sh, out_path], cwd=snapshot, env=env, timeout=10,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                       start_new_session=True, check=True)
    except Exception as e:
        log("init: launch failed: %r" % (e,))
        activity(run_dir, "start failed: could not launch the supervisor")
        return False
    deadline = time.time() + START_WAIT_S
    while time.time() < deadline and pipeline_pid(run_dir, "supervisor") is None:
        time.sleep(0.25)
    sup = pipeline_pid(run_dir, "supervisor")
    if sup is None:
        log("init: FAILED: no live supervisor within %.0fs (snapshot %s)" % (START_WAIT_S, snapshot))
        activity(run_dir, "start failed: the supervisor did not come up")
        return False
    # supervisor.pid is written BEFORE run.sh starts; run.sh dies in ~1 s on a missing key / FIFO / tool and the
    # supervisor then exits "fatal, not restarting". Success means an encoder is actually running.
    deadline = time.time() + START_CONFIRM_S
    while time.time() < deadline:
        if pipeline_pid(run_dir, "ffmpeg") is not None:
            break
        if pipeline_pid(run_dir, "supervisor") is None:
            break
        time.sleep(0.5)
    ff = pipeline_pid(run_dir, "ffmpeg")
    sup = pipeline_pid(run_dir, "supervisor")
    ok = ff is not None and sup is not None
    log("init: %s (supervisor pid %s, ffmpeg pid %s, snapshot %s)" % ("stream up" if ok else "FAILED: encoder never started", sup, ff, snapshot))
    activity(run_dir, "stream starting again for the owner" if ok else "start failed: the encoder did not come up (see logs/supervisor.out)")
    return ok


# ----------------------------------------------------------------------------- tail
def tail(path: str, stop: List[bool]) -> Iterator[str]:
    """Yield new complete lines appended to `path`, starting at its END; survive truncation and replacement."""
    fh = None
    ino = None
    buf = ""
    from_start = False        # first open: skip history; after a rotation/truncation: the whole new file is new
    while not stop[0]:
        if fh is None:
            try:
                fh = open(path, "r", encoding="utf-8", errors="replace")
                st = os.fstat(fh.fileno())
                ino = st.st_ino
                if not from_start:
                    fh.seek(0, os.SEEK_END)
                from_start = True
                buf = ""
            except FileNotFoundError:
                from_start = True         # a file that appears later is all new
                time.sleep(POLL_S)
                continue
        chunk = fh.read()
        if chunk:
            buf += chunk
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                yield line
            continue
        try:
            st = os.stat(path)
            pos = fh.tell()
            if st.st_ino != ino or st.st_size < pos:       # rotated or truncated: reopen at the start of the new file
                log("chat.jsonl replaced or truncated; reopening")
                fh.close()
                fh = None
                continue
        except FileNotFoundError:
            fh.close()
            fh = None
            continue
        time.sleep(POLL_S)


# ----------------------------------------------------------------------------- main loop
def run(run_dir: str, snapshot: str, dry: bool) -> int:
    global _LOG_FH
    run_dir = os.path.realpath(run_dir)
    os.makedirs(os.path.join(run_dir, "logs"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "pids"), exist_ok=True)
    _LOG_FH = open(os.path.join(run_dir, "logs", "ops_switch.log"), "a")
    mine = os.path.join(run_dir, "pids", "ops_switch.pid")
    old = read_pid(run_dir, "ops_switch")
    if pid_alive(old) and old != os.getpid():
        log("REFUSING: another ops_switch is alive (pid %s)" % old)
        return 1
    with open(mine, "w") as fh:
        fh.write(str(os.getpid()))
    stop = [False]

    def _term(signum, frame):
        stop[0] = True

    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)
    chat = os.path.join(run_dir, "chat.jsonl")
    log("watching %s for %s from @%s (broadcaster badge); snapshot %s%s" % (chat, "/".join(TOKENS), OWNER, snapshot, " DRY RUN" if dry else ""))
    import collections
    seen: Set[str] = set()
    seen_order: "collections.deque[str]" = collections.deque()
    last_init = 0.0
    try:
        for line in tail(chat, stop):
            try:
                rec = parse_record(line)
                now = time.time()
                token, why = classify(rec, now, seen)
                if rec and rec.get("text", "").strip().lower() in TOKENS:
                    log("token-looking line from %r badges=%s shape=%s -> %s" % (rec.get("user"), rec.get("badges"), rec.get("shape"), token or why))
                if not token:
                    continue
                seen.add(rec["id"])
                seen_order.append(rec["id"])
                while len(seen_order) > 5000:
                    seen.discard(seen_order.popleft())
                if token == "nuke":                      # the emergency stop is never rate-limited; do_nuke is idempotent
                    do_nuke(run_dir, dry)
                else:
                    if now - last_init < COOLDOWN_S:
                        log("init ignored: cooldown (%.0fs since the last start)" % (now - last_init))
                        activity(run_dir, "start ignored: wait %d s and say it again" % int(COOLDOWN_S - (now - last_init)) if not dry else "dry")
                        continue
                    last_init = now
                    do_init(run_dir, snapshot, dry)
            except Exception as e:                       # one bad line or one failed action must never end the watcher
                log("line handling failed: %r (line %r)" % (e, line[:200]))
                continue
    finally:
        try:
            if read_pid(run_dir, "ops_switch") == os.getpid():
                os.remove(mine)
        except OSError:
            pass
        log("exiting")
    return 0


# ----------------------------------------------------------------------------- self-test
def self_test() -> int:
    import shutil
    import tempfile
    base = tempfile.mkdtemp(prefix="lg-ops-selftest-", dir="/tmp")
    run_dir = os.path.join(base, "run")
    snap = os.path.join(base, "snap")
    os.makedirs(os.path.join(run_dir, "pids"))
    os.makedirs(os.path.join(run_dir, "logs"))
    os.makedirs(os.path.join(snap, "stream"))
    fails = 0

    def check(name, cond):
        nonlocal fails
        print("  [%s] %s" % ("ok" if cond else "FAIL", name))
        if not cond:
            fails += 1

    now = time.time()
    fresh = _dt.datetime.utcfromtimestamp(now).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    old = _dt.datetime.utcfromtimestamp(now - 3600).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def pusher(user, text, badges=("broadcaster",), ts=fresh, mid="m1", typ="message", sender_id=OWNER_ID, chatroom_id=CHATROOM_ID):
        return json.dumps({"ts": ts, "created_at": ts[:19] + "+00:00", "id": mid, "chatroom_id": chatroom_id, "sender_id": sender_id,
                           "username": user, "slug": user.lower(), "content": text, "color": "#fff", "badges": list(badges), "type": typ})

    seen: Set[str] = set()
    cases = [
        ("exact nuke from owner+badge", pusher("atleastonce", "nuke"), "nuke"),
        ("exact init from owner+badge", pusher("atleastonce", "init", mid="m2"), "init"),
        ("upper case NUKE", pusher("atleastonce", "NUKE", mid="m3"), "nuke"),
        ("padded '  nuke  '", pusher("atleastonce", "  nuke  ", mid="m4"), "nuke"),
        ("mixed-case owner name", pusher("AtLeastOnce", "init", mid="m5"), "init"),
        ("'nuke!' punctuation", pusher("atleastonce", "nuke!", mid="m6"), None),
        ("'nuke please' sentence", pusher("atleastonce", "nuke please", mid="m7"), None),
        ("'please nuke' sentence", pusher("atleastonce", "please nuke", mid="m8"), None),
        ("'!nuke' command form", pusher("atleastonce", "!nuke", mid="m9"), None),
        ("other user with broadcaster badge", pusher("someone_else", "nuke", mid="m10"), None),
        ("owner name, moderator badge only", pusher("atleastonce", "nuke", badges=("moderator",), mid="m11"), None),
        ("owner name, no badges", pusher("atleastonce", "nuke", badges=(), mid="m12"), None),
        ("owner, stale by an hour", pusher("atleastonce", "nuke", ts=old, mid="m13"), None),
        ("owner, no id", pusher("atleastonce", "nuke", mid=""), None),
        ("owner, non-message event type", pusher("atleastonce", "nuke", mid="m14", typ="celebration"), None),
        ("webhook shape from owner", json.dumps({"ts": fresh[:19] + "Z", "source": "webhook", "id": "w1", "user": "atleastonce", "text": "nuke", "broadcaster": "atleastonce"}), None),
        ("junk line", "not json at all", None),
        ("empty line", "", None),
        ("dict badges shape", json.dumps({"ts": fresh, "id": "m15", "username": "atleastonce", "content": "nuke", "badges": [{"type": "broadcaster", "text": "Broadcaster"}], "type": "message"}), "nuke"),
        ("lookalike 'atleastonce ' with trailing space", pusher("atleastonce ", "nuke", mid="m16"), "nuke"),
        ("lookalike 'at1eastonce'", pusher("at1eastonce", "nuke", mid="m17"), None),
        ("text 'in it' is not 'init'", pusher("atleastonce", "in it", mid="m18"), None),
        ("owner reply event type", pusher("atleastonce", "nuke", mid="m19", typ="reply"), "nuke"),
        ("malformed badges: int", json.dumps({"ts": fresh, "id": "m20", "username": "atleastonce", "content": "nuke", "badges": 5, "type": "message"}), None),
        ("malformed badges: string", json.dumps({"ts": fresh, "id": "m21", "username": "atleastonce", "content": "nuke", "badges": "broadcaster", "type": "message"}), None),
        ("dict badge with text only (no type)", json.dumps({"ts": fresh, "id": "m22", "username": "atleastonce", "content": "nuke", "badges": [{"text": "Broadcaster"}], "type": "message"}), None),
        ("malformed type: dict", json.dumps({"ts": fresh, "id": "m23", "username": "atleastonce", "content": "nuke", "badges": ["broadcaster"], "type": {"x": 1}}), None),
        ("timestamp 60 s in the future", pusher("atleastonce", "nuke", ts=_dt.datetime.utcfromtimestamp(now + 60).strftime("%Y-%m-%dT%H:%M:%S.000Z"), mid="m24"), None),
        ("content is a list", json.dumps({"ts": fresh, "id": "m25", "username": "atleastonce", "content": ["nuke"], "badges": ["broadcaster"], "type": "message"}), None),
        ("owner name + badge but wrong sender_id", pusher("atleastonce", "nuke", mid="m26", sender_id=1), None),
        ("owner from another chatroom", pusher("atleastonce", "nuke", mid="m27", chatroom_id=1), None),
        ("owner record without sender_id/chatroom_id fields", json.dumps({"ts": fresh, "id": "m28", "username": "atleastonce", "content": "nuke", "badges": ["broadcaster"], "type": "message"}), "nuke"),
        ("sender_id as string", pusher("atleastonce", "init", mid="m29", sender_id=str(OWNER_ID)), "init"),
    ]
    print("classify:")
    for name, line, want in cases:
        got, why = classify(parse_record(line), now, seen)
        check("%s -> %s (%s)" % (name, got, why), got == want)
    seen.add("m1")
    got, why = classify(parse_record(pusher("atleastonce", "nuke", mid="m1")), now, seen)
    check("duplicate id ignored (%s)" % why, got is None)

    print("stale / recycled pid files are never trusted:")
    stranger = subprocess.Popen(["sleep", "300"], start_new_session=True)       # a same-user process that is NOT ffmpeg
    with open(os.path.join(run_dir, "pids", "ffmpeg.pid"), "w") as fh:
        fh.write(str(stranger.pid))
    with open(os.path.join(run_dir, "pids", "supervisor.pid"), "w") as fh:
        fh.write("999999")                                                        # nobody home
    time.sleep(0.2)
    check("ffmpeg.pid pointing at a stranger is ignored", pipeline_pid(run_dir, "ffmpeg") is None)
    check("dead supervisor.pid is ignored", pipeline_pid(run_dir, "supervisor") is None)
    check("nuke with only stale pid files is a no-op", do_nuke(run_dir, dry=False) is False)
    stranger.poll()
    check("the stranger was not signalled", pid_alive(stranger.pid))
    _kill(stranger.pid, signal.SIGKILL)
    stranger.wait(timeout=5)

    print("nuke against fake processes (marked like the real programs):")
    fake_root = os.path.join(base, "stream")
    os.makedirs(fake_root, exist_ok=True)
    fake_sup = os.path.join(fake_root, "supervisor.sh")
    fake_ff = os.path.join(fake_root, "ffmpeg")
    with open(fake_sup, "w") as fh:
        fh.write("#!/usr/bin/env bash\ntrap 'kill -TERM -- -$$ 2>/dev/null; exit 0' TERM\nsleep 300 & wait\n")
    with open(fake_ff, "w") as fh:
        fh.write("#!/usr/bin/env bash\ntrap '' TERM\nsleep 300 & wait\n")       # ignores TERM: forces the KILL path; no exec, so the marker stays in its command line
    os.chmod(fake_sup, 0o755)
    os.chmod(fake_ff, 0o755)
    sup = subprocess.Popen(["bash", fake_sup], start_new_session=True)
    ff = subprocess.Popen(["bash", fake_ff], start_new_session=True)              # a stubborn leftover outside the group
    with open(os.path.join(run_dir, "pids", "supervisor.pid"), "w") as fh:
        fh.write(str(sup.pid))
    with open(os.path.join(run_dir, "pids", "ffmpeg.pid"), "w") as fh:
        fh.write(str(ff.pid))
    time.sleep(0.3)
    check("fake pipeline alive before", pipeline_alive(run_dir)["supervisor"] and pipeline_alive(run_dir)["ffmpeg"])
    t0 = time.time()
    ok = do_nuke(run_dir, dry=False)
    sup.poll(); ff.poll()
    check("do_nuke returned ok in %.1fs" % (time.time() - t0), ok)
    check("supervisor gone", not pid_alive(sup.pid) or sup.returncode is not None)
    check("leftover killed", not pid_alive(ff.pid) or ff.returncode is not None)
    check("pid files removed", not os.path.exists(os.path.join(run_dir, "pids", "supervisor.pid")))
    check("nuke when down is a no-op", do_nuke(run_dir, dry=False) is False)

    print("init against a stub supervisor.sh (through a live-current style symlink):")
    # the stub writes supervisor.pid, then plays run.sh: starts a marked fake ffmpeg and writes ffmpeg.pid
    stub_ff = os.path.join(snap, "stream", "ffmpeg")
    with open(stub_ff, "w") as fh:
        fh.write("#!/usr/bin/env bash\nsleep 30 & wait\n")
    os.chmod(stub_ff, 0o755)
    with open(os.path.join(snap, "stream", "supervisor.sh"), "w") as fh:
        fh.write('#!/usr/bin/env bash\necho $$ > "$RUN_DIR/pids/supervisor.pid"\n'
                 'echo "stub MODE=$MODE SOURCE=$SOURCE AUDIO=$AUDIO_SOURCE KL_LIVE=$KL_LIVE RUN_DIR=$RUN_DIR cwd=$(pwd) SECRET=${STREAM_KEY:-none} pgid=$(ps -o pgid= -p $$ | tr -d " ")"\n'
                 'sleep 1; bash "$(dirname "$0")/ffmpeg" & FF=$!; echo $FF > "$RUN_DIR/pids/ffmpeg.pid"\n'
                 'trap \'kill -TERM $FF 2>/dev/null; exit 0\' TERM\nwait\n')
    link = os.path.join(base, "live-current")
    os.symlink(snap, link)
    os.environ["STREAM_KEY"] = "sk_selftest_must_not_leak"
    t0 = time.time()
    ok = do_init(run_dir, link, dry=False)
    os.environ.pop("STREAM_KEY", None)
    check("do_init returned ok in %.1fs (waited for the encoder)" % (time.time() - t0), ok and time.time() - t0 >= 1.0)
    spid = read_pid(run_dir, "supervisor")
    check("stub supervisor alive (pid %s)" % spid, pid_alive(spid))
    check("stub ffmpeg identified (pid %s)" % read_pid(run_dir, "ffmpeg"), pipeline_pid(run_dir, "ffmpeg") is not None)
    time.sleep(0.5)
    with open(os.path.join(run_dir, "logs", "supervisor.out")) as fh:
        out = fh.read()
    check("stub saw the RESUME.md env", "MODE=live" in out and "SOURCE=compositor" in out and "KL_LIVE=1" in out and "a.pcm" in out
          and (("cwd=" + snap) in out or ("cwd=" + os.path.realpath(snap)) in out))
    check("stub supervisor is not our child (re-parented)", spid is not None and _parent_pid(spid) != os.getpid())
    check("secrets scrubbed from the launch env", "SECRET=none" in out)
    check("symlink resolved at action time (%s)" % os.path.realpath(snap), ("cwd=" + os.path.realpath(snap)) in out or ("cwd=" + snap) in out)
    my_pgid = os.getpgid(0)
    stub_pgid = None
    for tok in out.split():
        if tok.startswith("pgid="):
            stub_pgid = int(tok[5:] or 0)
    check("stub supervisor is in its own process group (%s vs ours %s)" % (stub_pgid, my_pgid), stub_pgid not in (None, 0, my_pgid))
    check("a.pcm fifo created", os.path.exists(os.path.join(run_dir, "a.pcm")))
    check("init when up is a no-op", do_init(run_dir, snap, dry=False) is False)
    print("nuke right after init must still run (no cooldown on the emergency stop):")
    t0 = time.time()
    ok = do_nuke(run_dir, dry=False)
    check("nuke after init stopped the stub pipeline in %.1fs" % (time.time() - t0), ok and not any(pipeline_alive(run_dir).values()))
    print("init with a bad supervisor (run.sh dies at once) must report failure:")
    with open(os.path.join(snap, "stream", "supervisor.sh"), "w") as fh:
        fh.write('#!/usr/bin/env bash\necho $$ > "$RUN_DIR/pids/supervisor.pid"\nsleep 1\nexit 4\n')
    saved = globals()["START_CONFIRM_S"]
    globals()["START_CONFIRM_S"] = 6.0
    t0 = time.time()
    ok = do_init(run_dir, link, dry=False)
    globals()["START_CONFIRM_S"] = saved
    check("init reports failure when no encoder appears (%.1fs)" % (time.time() - t0), ok is False)
    _kill(spid, signal.SIGTERM)

    print("tail: starts at the end, sees appended lines, survives truncation:")
    chat = os.path.join(run_dir, "chat.jsonl")
    with open(chat, "w") as fh:
        fh.write(pusher("atleastonce", "nuke", mid="hist") + "\n")          # history: must never be yielded
    stop = [False]
    got_lines: List[str] = []

    def feeder():
        time.sleep(0.6)
        with open(chat, "a") as fh:
            fh.write(pusher("atleastonce", "init", mid="live1") + "\n")
        time.sleep(0.8)
        with open(chat, "w") as fh:                                           # truncate + new content
            fh.write(pusher("atleastonce", "init", mid="live2") + "\n")
        time.sleep(1.2)
        stop[0] = True

    import threading
    th = threading.Thread(target=feeder, daemon=True)
    th.start()
    for line in tail(chat, stop):
        got_lines.append(line)
    ids = [parse_record(l)["id"] for l in got_lines if parse_record(l)]
    check("history not replayed, appended line seen (%s)" % ids, "hist" not in ids and "live1" in ids)
    check("line after truncation seen", "live2" in ids)

    with open(os.path.join(run_dir, "activity.jsonl")) as fh:
        acts = [json.loads(l)["text"] for l in fh]
    check("activity feed has stop + start lines (%d)" % len(acts), any("stopping" in a for a in acts) and any("starting" in a for a in acts))
    shutil.rmtree(base, ignore_errors=True)
    print("OPS SWITCH SELF-TEST %s (%d failure(s))" % ("PASS" if fails == 0 else "FAIL", fails))
    return 0 if fails == 0 else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", help="the live run dir (pids/, chat.jsonl, logs/); required unless --self-test")
    ap.add_argument("--snapshot", default=DEFAULT_SNAPSHOT, help="snapshot whose stream/supervisor.sh `init` launches (default live-current)")
    ap.add_argument("--dry-run", action="store_true", help="log what would happen; touch nothing")
    ap.add_argument("--self-test", action="store_true", help="fake processes under /tmp; exit 0 on pass")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.run_dir:
        ap.error("--run-dir is required")
    for k in SECRET_ENV:                          # the watcher never needs a secret; keep them out of its environment
        os.environ.pop(k, None)
    return run(a.run_dir, a.snapshot, a.dry_run)   # unresolved on purpose: do_init resolves live-current at action time


if __name__ == "__main__":
    sys.exit(main())
