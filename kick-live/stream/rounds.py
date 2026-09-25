"""rounds.py - RoundEngine: the 180 s micro-round lifecycle (CONCEPT sections 4 and 8) and every
state.json write made by the compositor process.

    engine = RoundEngine(run_dir, store, bridge, log=None, round_s=180, changelog_path=None,
                         closing_s=150, ship_hold_s=5)
    engine.tick(now, ctx, chat)     # once per frame; chat = the classified messages ChatBridge.ingest()
                                    # returned this frame (theme/idea/mod commands are applied from it)

Lifecycle: open (0-150 s, votes accepted) -> closing (150-180 s) -> ship (winner, or an agent pick
labelled agent_pick=True when nobody voted; apply it to state.micro / theme / audio; append
$RUN_DIR/ships.jsonl and one line to docs/CHANGELOG.md; version re-derived; activity line actor
"ship"; round.phase == "ship" for ship_hold_s so the stage shows the RESULT card) -> next open.

Ballot: 3 options. When an idea in state.ideas has class == "instant" and status == "queued" it takes
one card (id "idea.<id>", source "idea"); the rest come from MENU, one parameter per card, never the
parameter that shipped last round, and preferring parameters that were not on the previous ballot.
Menu option ids are "micro.<param>.<value>"; applying one sets state.micro[param] = value, and for
palette also state.theme.preset, for audio_tempo also state.audio.tempo, for audio_pattern also
state.audio.pattern. canvas_seed has one value, "new": applying it rolls a fresh random seed.
The "chaos" menu entry (macro-ship v0.1, requested live by @atleastonce) is a pseudo-parameter: when
it ships, apply_option rolls ONE other menu parameter to a value it does not currently have, rewrites
the option's title to "chaos -> <what changed>" and its id to the real "micro.<param>.<value>", and
never stores "chaos" in state.micro, so ships.jsonl / CHANGELOG / the RESULT card stay honest.
An idea option may carry {"param": p, "value": v} (set by the agent when it classifies it "instant");
applying it then sets that micro parameter too. Otherwise the ship only records it and marks the
idea "shipped". An idea that loses IDEA_MAX_BALLOTS ballots is declined ("lost N ballots").
Idea ids are "i-%04d" with n = max(existing numeric id) + 1 (never len+1: ids collided live).

Versions (CONCEPT 8.1): version.* is DERIVED from ships.jsonl, never adopted from state.json.
Replay in event order: ok macro -> macro += 1, micro = 0; ok micro -> micro += 1; ok False -> failed += 1;
shipped = ok lines. string = v{major}.{macro}.{micro}; major comes from state.json at boot (0).
A macro-ship recorded by agents/duty.py `macro-done` (it writes macro.last_reload = {ts, ok, module,
error, commit} and bumps version.* on disk, but appends no ships.jsonl line) is honoured by writing the
missing line ourselves the moment we see it: {kind: "macro", macro_ts: <last_reload.ts>, ...}; macro_ts
de-duplicates across restarts. Replay is in file (append) order. duty's own version bump on disk is ignored
(version is owned here) and comes out identical from the replay.

Ownership (journal 012 finding 1: a foreign test run wrote version/round into the live state.json and
the engine adopted it). The engine keeps its last written state in memory and treats that as the
truth for the blocks it owns: version, round, micro, theme, chat, metrics, audio, compositor,
session.{id,started_ts}, mod.{hidden_users,paused,actions}. From disk it merges only what others own:
macro.*, agent.*, ask.*, session.ending, extra mod keys, and ideas[].class/reason/param/value/status
when they changed since our last write (the agent classifies; duty macro-done marks shipped/failed).
A foreign write to an owned block is detected within a frame, logged once per event and overwritten
by the in-memory copy on the next state.json write (a "drift" write happens immediately).
Test hooks (KL_SEED, a non-180 s round, a redirected CHANGELOG) are REFUSED against the canonical run
dir (~/.local/share/kick-live/run) so a test can never drive the live show.

Committing is NOT done here: the CHANGELOG line and the intended commit message
("ship v0.3.12: palette ember (voted by @sam)") are recorded (ships.jsonl `commit_msg`,
engine.last_commit_msg); the owner/compositor commits. `commit` is `git rev-parse --short HEAD`
at ship time (the hash the card shows) or null when git is unavailable.

Writes: state.json atomically (tmp + os.replace). updated_ts is refreshed on every write and at least
every 5 s (with the compositor counters), which keeps ctx.stale False. A raise anywhere inside ship()
is caught: the round still closes with a ships.jsonl line ok=false + error, version.failed += 1, no
micro bump, and the next round opens on time. tick() never raises.

Self-test (isolated run dir, no ffmpeg, no stream):
    RUN_DIR=/tmp/cp-rounds-port $PYTHON -m stream.rounds --self-test --run-dir /tmp/cp-rounds-port
"""
from __future__ import annotations

import copy
import json
import os
import random
import re
import subprocess
import sys
import threading
import traceback
from typing import Any, Dict, List, Optional, Tuple

try:
    from stream import layout as L
    from stream.state_store import epoch_to_iso, iso_to_epoch, write_state_atomic, run_path
except Exception:  # pragma: no cover
    import layout as L  # type: ignore
    from state_store import epoch_to_iso, iso_to_epoch, write_state_atomic, run_path  # type: ignore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANONICAL_RUN_DIR = os.path.expanduser("~/.local/share/kick-live/run")
CANONICAL_RUN_DIRS = tuple(os.path.realpath(d) for d in
                           [CANONICAL_RUN_DIR, os.path.expanduser("~/.local/share/kick-live/run-live")]
                           + ([os.environ["KL_LIVE_RUN_DIR"]] if os.environ.get("KL_LIVE_RUN_DIR") else []))

# The 12-parameter micro menu (CONCEPT 8.1 `micro`) + the chaos pseudo-parameter. One entry per state.micro key.
# Titles are what the ballot card shows (HN 22, 2 lines max in the card's 184 px title column, checked by
# `--check-titles`) and what ships.jsonl / CHANGELOG / the RESULT card record. QA (2026-09-25): a stranger's first
# ballot read "typewriter: 30 chars/s | scope: mirror | stage canvas: flow field", so nothing told them what pressing
# A would do. Every title is now the VISIBLE OUTCOME ("repaint everything orange (ember)"), and the preset / value
# stays in brackets so `!theme ember` remains learnable from the card.
MENU: List[Dict] = [
    {"param": "palette",        "values": sorted(L.PRESETS.keys()),                        "title": "repaint everything {v}",
     "labels": {"kick": "green (kick)", "ember": "orange (ember)", "ice": "light blue (ice)", "violet": "purple (violet)",
                "gold": "yellow (gold)", "magenta": "pink (magenta)", "cyan": "cyan", "paper": "off-white (paper)"}},
    {"param": "canvas_scene",   "values": ["reaction_diffusion", "flowfield"],              "title": "swap the sim to {v}",
     "labels": {"reaction_diffusion": "reaction diffusion", "flowfield": "20k particles"}},
    {"param": "canvas_rule",    "values": ["coral", "mitosis", "spots", "worms", "waves"],  "title": "make the sim grow {v}",
     "labels": {"mitosis": "cell splits"}},
    {"param": "canvas_seed",    "values": ["new"],                                          "title": "restart the sim from scratch"},
    {"param": "audio_tempo",    "values": [72, 85, 100],                                    "title": "{v}",
     "labels": {72: "slower beat (72 bpm)", 85: "medium beat (85 bpm)", 100: "faster beat (100 bpm)"}},
    {"param": "audio_pattern",  "values": ["pad_pulse", "pad_only", "pulse_hats", "half_time"], "title": "{v}",
     "labels": {"pad_pulse": "beat back on: pad + pulse", "pad_only": "drop the beat: pad only",
                "pulse_hats": "add hi-hats to the beat", "half_time": "half-time beat"}},
    {"param": "ticker_speed",   "values": [90, 120, 160],                                   "title": "{v}",
     "labels": {90: "slow the bottom ticker down", 120: "bottom ticker at normal speed", 160: "speed the bottom ticker up"}},
    {"param": "header_tagline", "values": ["SHIP IT LIVE", "CHAT BUILDS THIS", "YOU PICK WHAT CHANGES", "REBUILT EVERY 3 MIN"],
     "title": "tagline: {v}"},
    {"param": "typewriter_cps", "values": [30, 40, 60],                                     "title": "{v}",
     "labels": {30: "type the diff slower (30/s)", 40: "type the diff at 40 chars/s", 60: "type the diff faster (60/s)"}},
    {"param": "scope_style",    "values": ["line", "bars", "dots", "mirror"],               "title": "audio wave as {v}",
     "labels": {"line": "a line", "mirror": "a mirrored line"}},
    {"param": "stage_default",  "values": ["diff", "canvas", "status"],                     "title": "stage shows {v}",
     "labels": {"diff": "the live diff", "canvas": "the sim", "status": "build status"}},
    {"param": "chime_variant",  "values": ["arpeggio", "bell", "pluck"],                    "title": "ship sound: {v}",
     "labels": {"arpeggio": "an arpeggio", "bell": "a bell", "pluck": "a pluck"}},
    # macro-ship requested by @atleastonce (!idea "change everything. Make it all random"): rolls ONE other
    # parameter to a random new value when it ships; the ship title records what actually changed.
    {"param": "chaos",          "values": ["roll"],                                                "title": "chaos: randomise one thing"},
]
# Stranger gate (QA rank 2): while fewer than STRANGER_MIN_CHATTERS people chatted in the last 15 min (chat_stats.json
# unique_chatters_15m, mirrored into state.chat; unknown counts as "few"), these parameters stay out of the draw. Their
# effect is small or audio-only, so a first-time viewer could not predict what pressing the letter does.
STRANGER_MIN_CHATTERS = 3
STRANGER_HIDDEN = ("typewriter_cps", "scope_style", "chime_variant", "audio_pattern")
CHAOS_PARAM = "chaos"
MENU_BY_PARAM: Dict[str, Dict] = {m["param"]: m for m in MENU}
REAL_PARAMS: List[str] = [m["param"] for m in MENU if m["param"] != CHAOS_PARAM]
LETTERS = ("A", "B", "C")
IDEA_MAX_BALLOTS = 2
IDEAS_KEEP = 50
COUNTERS_EVERY_S = 5.0
_VERSION_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)")
_IDEA_ID_RE = re.compile(r"^i-(\d+)$")

# ----------------------------------------------------------------------------- ownership contract
# Blocks this engine owns outright (in memory is the truth; disk copies are overwritten).
OWNED_BLOCKS = ("version", "round", "micro", "theme", "chat", "metrics", "audio", "compositor")
# Blocks we own only partly: the listed sub-keys are ours, anything else in the block is foreign.
OWNED_SUBKEYS: Dict[str, Tuple[str, ...]] = {
    "session": ("id", "started_ts"),            # scripts/stop.sh --credits writes session.ending
    "mod": ("hidden_users", "paused", "actions"),
}
# Blocks other processes own (agents/duty.py, the responder): always taken from disk.
FOREIGN_BLOCKS = ("macro", "agent", "ask")
# Idea fields the agent may set (duty.py classify / macro-done --idea). The list itself is ours.
IDEA_FOREIGN_FIELDS = ("class", "reason", "param", "value")


def merge_foreign(s: Dict, disk: Optional[Dict], prev: Optional[Dict] = None) -> List[str]:
    """Copy the blocks other processes own from `disk` into `s` (in place). `prev` is the state this
    process last wrote: an ideas[] field is adopted from disk only when it differs from what we last
    wrote (i.e. someone else changed it), so our own pending change is never undone by a stale disk
    copy. Returns the list of things merged (for logging). Never raises on odd shapes."""
    merged: List[str] = []
    if not isinstance(disk, dict):
        return merged
    for k in FOREIGN_BLOCKS:
        d = disk.get(k)
        if isinstance(d, dict) and d != s.get(k):
            s[k] = copy.deepcopy(d)
            merged.append(k)
    for k, subs in OWNED_SUBKEYS.items():
        d = disk.get(k)
        if not isinstance(d, dict):
            continue
        blk = s.setdefault(k, {})
        if not isinstance(blk, dict):
            continue
        for kk, vv in d.items():
            if kk not in subs and blk.get(kk) != vv:
                blk[kk] = copy.deepcopy(vv)
                merged.append("%s.%s" % (k, kk))
    disk_ideas = {str(i.get("id")): i for i in (disk.get("ideas") or []) if isinstance(i, dict)}
    prev_ideas = {str(i.get("id")): i for i in ((prev or {}).get("ideas") or []) if isinstance(i, dict)}
    for i in s.get("ideas") or []:
        if not isinstance(i, dict):
            continue
        iid = str(i.get("id"))
        d = disk_ideas.get(iid)
        if not d:
            continue
        p = prev_ideas.get(iid, i)
        for f in IDEA_FOREIGN_FIELDS:
            if f in d and d.get(f) != p.get(f) and d.get(f) != i.get(f):
                i[f] = d[f]
                merged.append("ideas[%s].%s" % (iid, f))
        ds = d.get("status")
        if ds is not None and ds != p.get("status") and ds != i.get("status"):
            # someone else moved this idea since our last write (agent classify / declined / macro shipped);
            # a card we are voting on right now only yields to a decline
            if i.get("status") != "ballot" or ds == "declined":
                i["status"] = ds
                merged.append("ideas[%s].status" % iid)
    return merged


def owned_drift(mem: Optional[Dict], other: Optional[Dict]) -> List[str]:
    """Owned blocks/sub-keys in `other` (a state read from disk) that differ from `mem` (what we wrote)."""
    if not isinstance(mem, dict) or not isinstance(other, dict):
        return []
    out: List[str] = []
    for k in OWNED_BLOCKS:
        if other.get(k) != mem.get(k):
            out.append(k)
    for k, subs in OWNED_SUBKEYS.items():
        a, b = mem.get(k) or {}, other.get(k) or {}
        if not isinstance(a, dict) or not isinstance(b, dict):
            continue
        for kk in subs:
            if a.get(kk) != b.get(kk):
                out.append("%s.%s" % (k, kk))
    return out


# ----------------------------------------------------------------------------- helpers
def _git_head_from_files(root: str) -> Optional[str]:
    """HEAD's 40-hex hash by reading .git/HEAD -> refs/heads/<b> (or packed-refs); no subprocess. None if unsure."""
    d = os.path.abspath(root)
    while not os.path.exists(os.path.join(d, ".git")):   # the repo root may be a parent of kick-live/
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent
    git = os.path.join(d, ".git")
    if os.path.isfile(git):                       # worktree: `gitdir: <path>`
        with open(git, encoding="utf-8") as fh:
            line = fh.read().strip()
        git = line[len("gitdir:"):].strip() if line.startswith("gitdir:") else git
    with open(os.path.join(git, "HEAD"), encoding="utf-8") as fh:
        head = fh.read().strip()
    if not head.startswith("ref:"):
        return head if re.match(r"^[0-9a-f]{40}$", head) else None
    ref = head[4:].strip()
    p = os.path.join(git, ref)
    if not os.path.isfile(p):                     # worktree gitdir is .git/worktrees/<n>; refs live in the common dir
        common = os.path.join(git, "commondir")
        if os.path.isfile(common):
            with open(common, encoding="utf-8") as fh:
                git = os.path.normpath(os.path.join(git, fh.read().strip()))
            p = os.path.join(git, ref)
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as fh:
            h = fh.read().strip()
        return h if re.match(r"^[0-9a-f]{40}$", h) else None
    packed = os.path.join(git, "packed-refs")
    if os.path.isfile(packed):
        with open(packed, encoding="utf-8") as fh:
            for ln in fh:
                parts = ln.strip().split(" ", 1)
                if len(parts) == 2 and parts[1] == ref and re.match(r"^[0-9a-f]{40}$", parts[0]):
                    return parts[0]
    return None


def _git_short_hash() -> Optional[str]:
    """Short HEAD hash for the ship record. Fast path reads the .git files (~0.1 ms) because `git rev-parse` costs
    ~35 ms on this Mac and ship() runs inside the frame loop (it made the SHIP frame the one over-budget frame).
    Falls back to the subprocess when the files do not resolve."""
    try:
        h = _git_head_from_files(ROOT)
        if h:
            return h[:7]
    except Exception:
        pass
    try:
        out = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=3)
        h = out.stdout.strip()
        return h if out.returncode == 0 and h else None
    except Exception:
        return None


def parse_version(s: Any) -> Optional[Tuple[int, int, int]]:
    m = _VERSION_RE.match(str(s or "").strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def version_string(major: int, macro: int, micro: int) -> str:
    return "v%d.%d.%d" % (int(major), int(macro), int(micro))


def commit_message(version: str, title: str, picked_by: Optional[str]) -> str:
    """The commit the owner makes for this ship: `ship v0.3.12: palette ember (voted by @sam)`."""
    who = ("voted by @%s" % picked_by) if picked_by else "agent pick"
    return "ship %s: %s (%s)" % (version, (title or "").replace(": ", " ", 1), who)


def next_idea_id(ideas: List[Dict]) -> str:
    """i-%04d with n = max(existing numeric id) + 1. Never len(ideas)+1 (collided live, journal 010)."""
    n = 0
    for i in ideas or []:
        m = _IDEA_ID_RE.match(str((i or {}).get("id") or "")) if isinstance(i, dict) else None
        if m:
            n = max(n, int(m.group(1)))
    return "i-%04d" % (n + 1)


def read_ships(path: str) -> List[Dict]:
    out: List[Dict] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    o = json.loads(ln)
                except Exception:
                    continue
                if isinstance(o, dict) and "version" in o:
                    out.append(o)
    except OSError:
        pass
    return out


def derive_version(ships: List[Dict], base: Optional[Dict] = None) -> Dict:
    """version.* from ships.jsonl lines (CONCEPT 8.1). Pure replay in FILE order (append order; timestamps
    are not trusted for ordering because duty.py and the engine keep separate clocks): ok macro -> macro += 1,
    micro = 0; ok micro -> micro += 1; ok False -> failed += 1. shipped = ok lines. Only `major` is taken
    from `base` (state.json); the version STRING on old lines is never trusted (journal 012)."""
    base = base or {}
    try:
        major = int(base.get("major") or 0)
    except Exception:
        major = 0
    macro = micro = shipped = failed = 0
    commit = None
    for o in ships:
        if o.get("ok") is False:
            failed += 1
            continue
        shipped += 1
        if o.get("kind") == "macro":
            macro += 1
            micro = 0
        else:
            micro += 1
        commit = o.get("commit") or commit
    return {"string": version_string(major, macro, micro), "major": major, "macro": macro, "micro": micro,
            "commit": commit, "shipped": shipped, "failed": failed}


# ----------------------------------------------------------------------------- engine
class RoundEngine(object):
    def __init__(self, run_dir: str, store, bridge, log=None, round_s: float = 180.0, changelog_path: Optional[str] = None,
                 closing_s: float = 150.0, ship_hold_s: float = 5.0):
        self.run_dir = run_dir
        self.store = store
        self.bridge = bridge
        self.log = log or (lambda m: sys.stderr.write("rounds: %s\n" % m))
        seed = os.environ.get("KL_SEED")
        # Test hooks never drive the live show: against the canonical run dir they are refused, loudly.
        self.canonical = os.path.realpath(run_dir) in CANONICAL_RUN_DIRS      # run, run-live (journal 013), $KL_LIVE_RUN_DIR
        if self.canonical and (float(round_s) != 180.0 or seed or changelog_path):
            self.log("REFUSING test hooks against the canonical run dir %s (round_s=%s KL_SEED=%s changelog=%s): "
                     "using 180 s rounds, unseeded RNG, docs/CHANGELOG.md" % (run_dir, round_s, seed, changelog_path))
            round_s, closing_s, seed, changelog_path = 180.0, 150.0, None, None
        self.round_s = float(round_s)
        self.closing_s = min(float(closing_s), self.round_s)
        self.ship_hold_s = float(ship_hold_s)
        self.ships_path = os.path.join(run_dir, "ships.jsonl")
        self.changelog_path = changelog_path or os.path.join(ROOT, "docs", "CHANGELOG.md")
        self.activity_path = run_path(run_dir, "ACTIVITY_FILE", "activity.jsonl")
        rd = os.path.abspath(run_dir) + os.sep
        for what, p in (("state.json", getattr(store, "state_file", "") or ""), ("activity.jsonl", self.activity_path)):
            if p and not os.path.abspath(p).startswith(rd):
                self.log("WARNING: %s resolves to %s, outside run_dir %s (stale env.sh paths? set RUN_DIR before sourcing it)"
                         % (what, p, run_dir))
        self._ship_until: Optional[float] = None
        self._last_write: Optional[float] = None
        self._last_counters_write: Optional[float] = None
        self._last_tally_sig = None
        self._last_mod_sig = None
        self._last_tallies: Optional[Dict[str, List[str]]] = None
        self._tallies_failed = False
        self._tick_errors = 0
        self._commit: Optional[str] = None          # refreshed off the frame path (git takes ~25 ms)
        self._commit_thread: Optional[threading.Thread] = None
        self._refresh_commit_async()
        self._booted = False
        self._rng = random.Random()
        if seed:
            self._rng.seed(int(seed))
            self.log("TEST HOOK: KL_SEED=%s" % seed)
        self.ships = 0                    # ships this process
        self.fails = 0                    # failed ships this process
        self.last_commit_msg: Optional[str] = None
        self.last_error: Optional[str] = None
        self._prev_ballot_params: List[str] = []
        # ownership: the state we last wrote is the truth for OWNED_BLOCKS / OWNED_SUBKEYS
        self._mem: Optional[Dict] = None
        self.drift_events = 0             # foreign writes to owned keys seen (and overwritten)
        self._drift_sig = None
        # version source of truth: every ships.jsonl line we know of (loaded at boot, appended on ship)
        self._ships_lines: List[Dict] = []
        self._macro_seen: set = set()     # macro_ts values already recorded as macro lines
        self._last_macro_ts: Optional[str] = None
        self.macro_ships = 0              # duty macro-dones honoured this process

    # ------------------------------------------------------------------ io
    def _refresh_commit_async(self) -> None:
        """`git rev-parse --short HEAD` in a daemon thread: never a subprocess inside tick()/ship()."""
        if self._commit_thread is not None and self._commit_thread.is_alive():
            return

        def work():
            h = _git_short_hash()
            if h:
                self._commit = h
        try:
            self._commit_thread = threading.Thread(target=work, name="rounds-git", daemon=True)
            self._commit_thread.start()
        except Exception as e:
            self.log("git hash thread failed: %r" % (e,))

    def _append_jsonl(self, path: str, obj: Dict) -> bool:
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
            return True
        except Exception as e:
            self.log("append %s failed: %r" % (os.path.basename(path), e))
            return False

    def _activity(self, actor: str, text: str, now: float) -> None:
        self._append_jsonl(self.activity_path, {"ts": epoch_to_iso(now), "actor": actor, "text": text[:200]})

    def _read_disk_state(self) -> Optional[Dict]:
        try:
            with open(self.store.state_file, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            return d if isinstance(d, dict) else None
        except Exception:
            return None

    def _merge_foreign(self, s: Dict, disk: Optional[Dict]) -> List[str]:
        return merge_foreign(s, disk, self._mem)

    def _compose(self, now: float) -> Dict:
        """The state this tick works on: our last written state (owned blocks are the truth) with the
        foreign-owned blocks refreshed from the store's copy of disk. Before the first write, disk is
        the seed (round resume, micro look) and _boot() re-derives version from ships.jsonl."""
        cur = self.store.state
        if self._mem is None:
            return copy.deepcopy(cur)
        drift = owned_drift(self._mem, cur)
        if drift:
            sig = tuple(drift)
            if sig != self._drift_sig:
                self._drift_sig = sig
                self.drift_events += 1
                self.log("foreign write to owned state ignored, restoring from memory: %s (event %d)" % (
                    ", ".join(drift), self.drift_events))
                if self.drift_events <= 3:
                    self._activity("compositor", "state.json: foreign write to %s ignored (owned by rounds)" % ", ".join(drift)[:120], now)
        else:
            self._drift_sig = None
        s = copy.deepcopy(self._mem)
        self._merge_foreign(s, cur)
        return s

    def _write(self, s: Dict, now: float) -> None:
        self._merge_foreign(s, self._read_disk_state())     # last-250-ms foreign writes (duty.py) survive
        s["updated_ts"] = epoch_to_iso(now)
        try:
            write_state_atomic(self.store.state_file, s)
            try:
                self.store._state_mtime = os.stat(self.store.state_file).st_mtime
                self.store._state_read_ok = True
            except OSError:
                pass
            self._last_write = now
        except Exception as e:
            self.log("state.json write failed: %r" % (e,))
        self.store.set_state(s)
        self._mem = copy.deepcopy(self.store.state)          # post-defaults copy: compares equal to the store
        self._drift_sig = None

    # ------------------------------------------------------------------ version
    def _version(self, s: Dict, extra: Optional[List[Dict]] = None) -> Dict:
        return derive_version(self._ships_lines + (extra or []), s.get("version") or {})

    def _record_ship(self, s: Dict, line: Dict) -> None:
        """Append one ships.jsonl line and make it the version source of truth."""
        self._ships_lines.append(line)
        self._append_jsonl(self.ships_path, line)
        s["version"] = self._version(s)

    def _sync_macro(self, s: Dict, now: float) -> bool:
        """agents/duty.py macro-done writes macro.last_reload (and bumps version.* on disk, which we do not
        adopt). Turn each new last_reload.ts into the ships.jsonl `macro` line CONCEPT 8.1 expects, once."""
        lr = (s.get("macro") or {}).get("last_reload") or {}
        ts = lr.get("ts") if isinstance(lr, dict) else None
        if not ts or ts == self._last_macro_ts:
            return False
        self._last_macro_ts = ts
        if ts in self._macro_seen:
            return False
        self._macro_seen.add(ts)
        m = s.get("macro") or {}
        ok = bool(lr.get("ok"))
        module = lr.get("module") or m.get("module") or m.get("file") or "macro"
        title = (m.get("title") or "macro-ship %s" % os.path.basename(str(module)))[:80]
        who = m.get("requested_by")
        cand = {"ts": epoch_to_iso(now), "kind": "macro", "ok": ok, "macro_ts": ts}
        after = self._version(s, [cand])
        shown = after["string"] if ok else self._version(s)["string"]
        msg = "ship %s: %s (macro-ship%s)" % (shown, title, (", requested by @%s" % who) if who else "")
        line = {"ts": epoch_to_iso(now), "version": shown, "kind": "macro", "option_id": "macro.%s" % module,
                "title": title, "picked_by": who, "agent_pick": False, "ok": ok, "commit": lr.get("commit"),
                "error": lr.get("error"), "votes": 0, "total_votes": 0, "source": "macro", "requested_by": who,
                "round": (s.get("round") or {}).get("number"), "commit_msg": msg if ok else None, "macro_ts": ts}
        self._record_ship(s, line)
        self.macro_ships += 1
        fake = {"title": title, "votes": 0}
        self._changelog(now, ok, shown, fake, "macro-ship by agent%s" % ((", requested by @%s" % who) if who else ""),
                        0, msg, lr.get("error"), commit=lr.get("commit"))
        # duty.py already wrote the on-screen "SHIPPED ... (macro)" activity line; only log here.
        self.log("macro-done from duty honoured: %s %s ok=%s commit=%s -> version %s" % (
            ts, title, ok, lr.get("commit"), s["version"]["string"]))
        return True

    # ------------------------------------------------------------------ options
    @staticmethod
    def _title(entry: Dict, v: Any) -> str:
        label = (entry.get("labels") or {}).get(v, v)
        return entry["title"].format(v=label)

    def _option_for(self, param: str, current: Dict, letter: str) -> Dict:
        entry = MENU_BY_PARAM[param]
        choices = [v for v in entry["values"] if v != current.get(param)] or list(entry["values"])
        v = self._rng.choice(choices)
        return {"letter": letter, "id": "micro.%s.%s" % (param, v), "title": self._title(entry, v),
                "source": "menu", "votes": 0, "voters": [], "param": param, "value": v}

    def _pick_idea(self, s: Dict) -> Optional[Dict]:
        ideas = [i for i in (s.get("ideas") or []) if isinstance(i, dict)
                 and i.get("class") == "instant" and i.get("status") == "queued" and (i.get("text") or "").strip()]
        if not ideas:
            return None
        # most +N first, then oldest
        ideas.sort(key=lambda i: (-int(i.get("plus") or 0), iso_to_epoch(i.get("ts")) or 0.0))
        return ideas[0]

    @staticmethod
    def stranger_mode(s: Dict) -> bool:
        """True while fewer than STRANGER_MIN_CHATTERS distinct people chatted in the last 15 min (or nobody knows)."""
        n = (s.get("chat") or {}).get("unique_chatters_15m")
        try:
            return n is None or int(n) < STRANGER_MIN_CHATTERS
        except Exception:
            return True

    def draw_options(self, s: Dict, exclude_param: Optional[str] = None) -> List[Dict]:
        """3 options: one queued instant !idea when present, the rest from MENU. Never `exclude_param`
        (the parameter that just shipped), never STRANGER_HIDDEN while stranger_mode(s), and prefer parameters
        that were not on the previous ballot."""
        micro = s.get("micro") or {}
        avoid = set(self._prev_ballot_params)
        hidden = set(STRANGER_HIDDEN) if self.stranger_mode(s) else set()
        pool = [m["param"] for m in MENU if m["param"] != exclude_param and m["param"] not in hidden]
        fresh = [p for p in pool if p not in avoid]
        stale = [p for p in pool if p in avoid]
        self._rng.shuffle(fresh)
        self._rng.shuffle(stale)
        params = fresh + stale
        letters = list(LETTERS)
        self._rng.shuffle(letters)
        options: List[Dict] = []
        idea = self._pick_idea(s)
        if idea is not None:
            opt = {"letter": letters.pop(), "id": "idea.%s" % idea.get("id"), "title": (idea.get("text") or "")[:60],
                   "source": "idea", "requested_by": idea.get("by"), "votes": 0, "voters": [], "idea_id": str(idea.get("id"))}
            if idea.get("param") in MENU_BY_PARAM and idea.get("value") is not None:
                opt["param"], opt["value"] = idea["param"], idea["value"]
                params = [p for p in params if p != idea["param"]]
            options.append(opt)
            idea["status"] = "ballot"
            idea["ballots"] = int(idea.get("ballots") or 0) + 1
        while letters:
            if not params:
                params = [m["param"] for m in MENU if m["param"] != exclude_param and m["param"] not in hidden]
            options.append(self._option_for(params.pop(0), micro, letters.pop()))
        options.sort(key=lambda o: o["letter"])
        self._prev_ballot_params = [o["param"] for o in options if o.get("param")]
        return options

    def open_round(self, s: Dict, now: float, exclude_param: Optional[str] = None) -> None:
        rnd = s.setdefault("round", {})
        rnd["number"] = int(rnd.get("number") or 0) + 1
        rnd["phase"] = "open"
        rnd["opened_ts"] = epoch_to_iso(now)
        rnd["deadline_ts"] = epoch_to_iso(now + self.round_s)
        rnd["options"] = self.draw_options(s, exclude_param)
        self._ship_until = None
        self._last_tally_sig = None
        self.bridge.reset_round(now)
        self.log("round %d open: %s" % (rnd["number"], " | ".join("%s %s" % (o["letter"], o["title"]) for o in rnd["options"])))

    # ------------------------------------------------------------------ apply
    def roll_chaos(self, s: Dict, opt: Dict) -> Tuple[str, Any]:
        """The chaos card shipped: pick ONE real parameter and a value it does not currently have, and
        rewrite the option in place so every record shows what actually changed."""
        micro = s.get("micro") or {}
        entry = MENU_BY_PARAM[self._rng.choice(REAL_PARAMS)]
        cur = micro.get(entry["param"])
        vals = [v for v in entry["values"] if str(v) != str(cur)] or list(entry["values"])
        value = self._rng.choice(vals)
        param = entry["param"]
        opt["title"] = "chaos → " + self._title(entry, value)
        opt["id"] = "micro.%s.%s" % (param, value)
        opt["param"], opt["value"] = param, value
        opt["chaos"] = True
        return param, value

    def apply_option(self, s: Dict, opt: Dict, picked_by: Optional[str]) -> None:
        """Land a winning option in state. Menu options set state.micro[param] (+ theme/audio mirrors);
        idea options mark the idea shipped and apply their param/value when the agent attached one.
        A chaos option is resolved to a real parameter first (roll_chaos) and never stored as "chaos"."""
        oid = str(opt.get("id") or "")
        now_iso = s.get("updated_ts")
        param, value = opt.get("param"), opt.get("value")
        if oid.startswith("micro."):
            parts = oid.split(".", 2)
            param = param or (parts[1] if len(parts) > 1 else None)
            if value is None and len(parts) > 2:
                value = parts[2]
                entry = MENU_BY_PARAM.get(param or "")
                if entry:   # restore the typed value (ints) from the menu
                    for v in entry["values"]:
                        if str(v) == value:
                            value = v
                            break
        elif oid.startswith("idea."):
            iid = opt.get("idea_id") or oid[len("idea."):]
            for i in s.get("ideas") or []:
                if str(i.get("id")) == str(iid):
                    i["status"] = "shipped"
                    i["shipped_ts"] = now_iso
                    if param is None and i.get("param") in MENU_BY_PARAM and i.get("value") is not None:
                        param, value = i["param"], i["value"]
        else:
            raise ValueError("unknown option id %r" % oid)
        if not param:
            return
        if param == CHAOS_PARAM:
            param, value = self.roll_chaos(s, opt)
        if param not in MENU_BY_PARAM or param == CHAOS_PARAM:
            raise ValueError("unknown micro parameter %r" % param)
        if param == "canvas_seed":
            value = self._rng.randrange(1, 2 ** 31 - 1)
        micro = s.setdefault("micro", {})
        micro.pop(CHAOS_PARAM, None)      # belt: never a "chaos" key in state.micro
        micro[param] = value
        if param == "palette":
            if value not in L.PRESETS:
                raise ValueError("unknown palette %r" % value)
            s.setdefault("theme", {}).update({"preset": value, "set_by": picked_by or "agent", "set_ts": now_iso})
        elif param == "audio_tempo":
            s.setdefault("audio", {})["tempo"] = value
        elif param == "audio_pattern":
            s.setdefault("audio", {})["pattern"] = value

    # ------------------------------------------------------------------ ship
    def _tallies(self) -> Dict[str, List[str]]:
        """bridge.tallies() with a last-known-good fallback: a broken bridge degrades to 'no new votes'
        instead of taking the round engine down with it."""
        try:
            t = self.bridge.tallies()
            if isinstance(t, dict):
                self._last_tallies = t
                return t
        except Exception as e:
            if not self._tallies_failed:
                self._tallies_failed = True
                self.log("bridge.tallies() failed (%r); using the last known tallies" % (e,))
        return getattr(self, "_last_tallies", None) or {"A": [], "B": [], "C": []}

    def _winner(self, options: List[Dict]) -> Tuple[Dict, bool, Optional[str], int]:
        """-> (winner, agent_pick, picked_by, total_votes). Ties go to the option that reached the tied
        count first (earliest last vote); at 0 votes a random agent pick labelled agent_pick=True."""
        tallies = self.bridge.tallies()      # deliberately unguarded: a raise here is a FAILED ship (tick() records it)
        for o in options:
            o["voters"] = list(tallies.get(o.get("letter"), []))
            o["votes"] = len(o["voters"])
        total = sum(o["votes"] for o in options)
        if total == 0:
            return self._rng.choice(options), True, None, 0
        best = max(o["votes"] for o in options)
        tied = [o for o in options if o["votes"] == best]
        if len(tied) > 1:
            votes = getattr(self.bridge, "_votes", None) or {}
            last_t: Dict[str, float] = {}
            for _name, lt in votes.items():
                try:
                    letter, t = lt[0], float(lt[1])
                except Exception:
                    continue
                last_t[letter] = max(last_t.get(letter, 0.0), t)
            tied.sort(key=lambda o: (last_t.get(o.get("letter"), float("inf")), o.get("letter")))
        w = tied[0]
        return w, False, (w["voters"][0] if w["voters"] else None), total

    def ship(self, s: Dict, now: float) -> None:
        rnd = s.setdefault("round", {})
        options = rnd.get("options") or []
        if not options:
            self.open_round(s, now)
            return
        winner, agent_pick, picked_by, total = self._winner(options)
        before = self._version(s)
        after = self._version(s, [{"kind": "micro", "ok": True, "ts": epoch_to_iso(now)}])
        new_version = after["string"]
        ok, error = True, None
        snapshot = {k: copy.deepcopy(s.get(k)) for k in ("micro", "theme", "audio", "ideas")}
        opt_snapshot = copy.deepcopy(winner)
        try:
            self.apply_option(s, winner, picked_by)
        except Exception as e:
            ok, error = False, ("%s: %s" % (type(e).__name__, e))[:200]
            for k, v in snapshot.items():       # nothing half-applied
                s[k] = v
            winner.clear()
            winner.update(opt_snapshot)
            self.log("ship apply failed: %s\n%s" % (error, traceback.format_exc().strip()))
        # losing ideas go back to the queue (or are declined after IDEA_MAX_BALLOTS losses)
        for o in options:
            if o is winner or o.get("source") != "idea":
                continue
            for i in s.get("ideas") or []:
                if str(i.get("id")) == str(o.get("idea_id") or o["id"][5:]) and i.get("status") == "ballot":
                    if int(i.get("ballots") or 0) >= IDEA_MAX_BALLOTS:
                        i["status"], i["reason"] = "declined", "lost %d ballots" % int(i.get("ballots") or 0)
                    else:
                        i["status"] = "queued"
        if ok:
            self.ships += 1
        else:
            self.fails += 1
            self.last_error = error
        shown_version = new_version if ok else before["string"]
        who = ("voted by @%s" % picked_by) if picked_by else "agent pick"
        msg = commit_message(new_version, winner.get("title") or "", picked_by)
        self.last_commit_msg = msg if ok else None
        rnd["phase"] = "ship"
        rnd["last_result"] = {"letter": winner.get("letter"), "title": winner.get("title"), "picked_by": picked_by,
                              "agent_pick": agent_pick, "version": shown_version, "ts": epoch_to_iso(now),
                              "votes": winner["votes"], "total_votes": total, "option_id": winner.get("id"),
                              "source": winner.get("source"), "ok": ok, "error": error, "commit": self._commit,
                              "chaos": bool(winner.get("chaos"))}
        self._ship_until = now + self.ship_hold_s
        line = {"ts": epoch_to_iso(now), "version": shown_version, "kind": "micro", "option_id": winner.get("id"),
                "title": winner.get("title"), "picked_by": picked_by, "agent_pick": agent_pick, "ok": ok,
                "commit": self._commit, "error": error, "votes": winner["votes"], "total_votes": total,
                "source": winner.get("source"), "requested_by": winner.get("requested_by"),
                "round": rnd.get("number"), "commit_msg": (msg if ok else None)}
        if winner.get("chaos"):
            line["chaos"] = True
        self._record_ship(s, line)      # version.* re-derived from ships.jsonl (single source of truth)
        self._changelog(now, ok, shown_version, winner, who, total, msg, error)
        if ok:
            self._activity("ship", "%s %s, %s%s" % (shown_version, winner.get("title"), who,
                                                    (", %s" % self._commit) if self._commit else ""), now)
        else:
            self._activity("ship", "FAILED %s %s, %s: %s" % (shown_version, winner.get("title"), who, error), now)
        if picked_by and ok:
            b = (self.bridge.builders or {}).get(picked_by.lower())
            if b is not None:
                b["ships"] = int(b.get("ships", 0)) + 1
                self.bridge._builders_dirty = True
        self.log("SHIP %s %s (%s) %d/%d votes ok=%s%s" % (shown_version, winner.get("title"), who, winner["votes"], total, ok,
                                                        (" error=%s" % error) if error else ""))

    def _changelog(self, now: float, ok: bool, version: str, winner: Dict, who: str, total: int, msg: str,
                   error: Optional[str], commit: Optional[str] = None) -> None:
        commit = commit or self._commit
        try:
            os.makedirs(os.path.dirname(self.changelog_path) or ".", exist_ok=True)
            new = not os.path.exists(self.changelog_path) or os.path.getsize(self.changelog_path) == 0
            with open(self.changelog_path, "a", encoding="utf-8") as fh:
                if new:
                    fh.write("# CHANGELOG\n\nOne line per ship, appended by stream/rounds.py at ship time. "
                             "Every line is a real round with real votes; `agent pick` means nobody voted.\n\n")
                votes = "%d/%d votes" % (int(winner.get("votes") or 0), total) if total else "0 votes"
                if ok:
                    fh.write("- %s ship %s: %s (%s, %s)%s · commit msg: `%s`\n" % (
                        epoch_to_iso(now, ms=False), version, winner.get("title"), who, votes,
                        (" %s" % commit) if commit else "", msg))
                else:
                    fh.write("- %s FAILED ship after %s: %s (%s, %s) error: %s\n" % (
                        epoch_to_iso(now, ms=False), version, winner.get("title"), who, votes, error))
        except Exception as e:
            self.log("CHANGELOG append failed: %r" % (e,))

    # ------------------------------------------------------------------ commands from chat
    def _apply_chat(self, s: Dict, chat: List[Dict], now: float) -> bool:
        dirty = False
        for m in chat or []:
            kind = m.get("kind")
            who = m.get("display_name") or m.get("name") or "chat"
            if kind == "theme" and m.get("accepted") and m.get("arg") in L.PRESETS:
                s.setdefault("theme", {}).update({"preset": m["arg"], "set_by": who, "set_ts": epoch_to_iso(now),
                                                  "cooldown_until": epoch_to_iso(now + 60)})
                s.setdefault("micro", {})["palette"] = m["arg"]
                self._activity("chat", "@%s set theme: %s" % (who, m["arg"]), now)
                dirty = True
            elif kind == "idea" and (m.get("arg") or "").strip() and not m.get("dropped"):
                ideas = s.setdefault("ideas", [])
                text = m["arg"].strip()
                mine = [i for i in ideas if i.get("by") == who and i.get("status") in ("open", "queued", "ballot")]
                recent = [i for i in mine if (iso_to_epoch(i.get("ts")) or 0) > now - 180]
                dup = next((i for i in ideas if (i.get("text") or "").lower() == text.lower() and i.get("status") != "declined"), None)
                if dup is not None:
                    if dup.get("by") != who and who not in (dup.get("plus_by") or []):
                        dup["plus"] = int(dup.get("plus") or 0) + 1
                        dup.setdefault("plus_by", []).append(who)
                        dirty = True
                    continue
                if recent or len(mine) >= 3:
                    continue    # 1 per user per 3 min, 3 open per user (CONCEPT 7)
                ideas.append({"id": next_idea_id(ideas), "text": text, "by": who, "ts": epoch_to_iso(now),
                              "plus": 0, "class": "pending", "status": "open", "reason": None})
                self._activity("chat", "@%s nominated: %s" % (who, text), now)
                if len(ideas) > IDEAS_KEEP:
                    del ideas[:-IDEAS_KEEP]
                dirty = True
        # mod state mirror (ChatBridge acts immediately; state.mod is the record)
        mod = s.setdefault("mod", {})
        hidden = sorted(self.bridge.hidden)
        if mod.get("hidden_users") != hidden or bool(mod.get("paused")) != bool(self.bridge.paused):
            mod["hidden_users"] = hidden
            mod["paused"] = bool(self.bridge.paused)
            dirty = True
        if self.bridge.mod_actions:
            for a in list(self.bridge.mod_actions):
                mod.setdefault("actions", []).append(a)
                self._activity("mod", "%s %s(%s)" % (a.get("action"), ("%s " % a["target"]) if a.get("target") else "", a.get("by")), now)
                if a.get("action") == "clear":
                    s["ideas"] = []
                    self._activity("mod", "backlog cleared by mod", now)
            mod["actions"] = mod.get("actions", [])[-20:]
            self.bridge.mod_actions = []
            dirty = True
        ch = s.setdefault("chat", {})
        if bool(ch.get("display", True)) != bool(self.bridge.display):
            ch["display"] = bool(self.bridge.display)
            dirty = True
        return dirty

    # ------------------------------------------------------------------ counters (every 5 s = stale heartbeat)
    def _counters(self, s: Dict, ctx, now: float) -> None:
        ch = s.setdefault("chat", {})
        if self.bridge.founders and ch.get("founders") != list(self.bridge.founders):
            ch["founders"] = list(self.bridge.founders)
        st = (ctx.chat_stats if ctx is not None else None) or {}
        if st:
            ch["msgs_per_min_5m"] = st.get("msgs_per_min_5m", ch.get("msgs_per_min_5m"))
            ch["unique_chatters_5m"] = st.get("unique_chatters_5m", ch.get("unique_chatters_5m"))
            ch["unique_chatters_15m"] = st.get("unique_chatters_15m", ch.get("unique_chatters_15m"))   # stranger gate
            ch["connected"] = bool(st.get("connected", ch.get("connected")))
        m = (ctx.metrics if ctx is not None else None) or {}
        if m:
            met = s.setdefault("metrics", {})
            met.update({"is_live": m.get("is_live"), "viewer_count": m.get("viewer_count"),
                        "polled_ts": m.get("polled_ts"), "poll_ok": m.get("poll_ok")})
            if m.get("viewer_count") is not None:
                met["viewer_peak"] = max(int(m["viewer_count"]), int(met.get("viewer_peak") or 0))
        live = ctx.compositor_live if ctx is not None else None
        if live:
            s["compositor"] = copy.deepcopy(live)   # no aliasing: live["hot_reload"] mutates in place and would read as foreign drift
        src = ctx.audio_source if ctx is not None else None
        if src:
            s.setdefault("audio", {})["source"] = src

    # ------------------------------------------------------------------ boot
    def _boot(self, s: Dict, now: float) -> None:
        self._ships_lines = read_ships(self.ships_path)
        self._macro_seen = set(o.get("macro_ts") for o in self._ships_lines if o.get("kind") == "macro" and o.get("macro_ts"))
        cur = s.get("version") or {}
        derived = self._version(s)
        if derived != {k: cur.get(k) for k in derived}:
            self.log("version derived from ships.jsonl: %s (%d lines; state.json had %s, not adopted)" % (
                derived["string"], len(self._ships_lines), cur.get("string")))
        s["version"] = derived
        # a duty macro-done that happened while we were down (or before this scheme) gets its macro line now
        self._sync_macro(s, now)
        rnd = s.setdefault("round", {})
        deadline_t = iso_to_epoch(rnd.get("deadline_ts"))
        opened_t = iso_to_epoch(rnd.get("opened_ts"))
        phase = rnd.get("phase") or "open"
        if rnd.get("options"):
            self._prev_ballot_params = [o.get("param") for o in rnd["options"] if isinstance(o, dict) and o.get("param")]
        resumable = (deadline_t is not None and opened_t is not None and rnd.get("options")
                     and deadline_t - now <= self.round_s and now - deadline_t < self.ship_hold_s)
        if resumable and phase in ("open", "closing"):
            self.bridge.reset_round(opened_t)     # votes since opened_ts re-tally from chat.jsonl history
            self.log("resumed round %s (%s, %.0f s left, %d votes so far)" % (
                rnd.get("number"), phase, deadline_t - now, self.bridge.vote_count()))
        elif resumable and phase == "ship":
            self._ship_until = now + 1.0
        else:
            last = (rnd.get("last_result") or {}).get("option_id") or ""
            excl = last.split(".")[1] if last.startswith("micro.") and last.count(".") >= 2 else None
            self.open_round(s, now, exclude_param=excl)
        (s.get("micro") or {}).pop(CHAOS_PARAM, None)
        sess = s.setdefault("session", {})
        if not sess.get("started_ts"):
            sess["started_ts"] = epoch_to_iso(now)
            sess["id"] = epoch_to_iso(now, ms=False)
        sess.setdefault("ending", False)

    # ------------------------------------------------------------------ tick
    def _due(self, now: float, chat: Optional[List[Dict]]) -> bool:
        """Cheap read-only check: is there anything to do this frame? Keeps the per-frame cost near zero."""
        if not self._booted or chat or self.bridge.mod_actions:
            return True
        if self._last_counters_write is None or now - self._last_counters_write >= COUNTERS_EVERY_S:
            return True
        s = self.store.state
        if self._mem is not None and owned_drift(self._mem, s):
            return True                                   # foreign write to an owned block: restore now
        lr = (s.get("macro") or {}).get("last_reload") or {}
        if isinstance(lr, dict) and lr.get("ts") and lr.get("ts") != self._last_macro_ts:
            return True                                   # duty macro-done landed
        rnd = (self._mem or s).get("round") or {}
        phase = rnd.get("phase") or "open"
        if phase == "ship":
            return self._ship_until is None or now >= self._ship_until
        deadline_t = iso_to_epoch(rnd.get("deadline_ts"))
        opened_t = iso_to_epoch(rnd.get("opened_ts"))
        if deadline_t is None or opened_t is None or now >= deadline_t:
            return True
        if phase == "open" and now - opened_t >= self.closing_s:
            return True
        tallies = self._tallies()
        sig = tuple((k, tuple(v)) for k, v in sorted(tallies.items()))
        if sig != self._last_tally_sig:
            return True
        mod_sig = (tuple(sorted(self.bridge.hidden)), bool(self.bridge.paused), bool(self.bridge.display))
        if mod_sig != self._last_mod_sig:
            return True
        return False

    def tick(self, now: float, ctx, chat: Optional[List[Dict]] = None) -> None:
        """Once per frame. Never raises: the work happens on a deep copy, so a failure anywhere simply
        skips this frame's write and the next frame re-evaluates from the last good state."""
        try:
            due = self._due(now, chat)
        except Exception:
            due = True
        if not due:
            return
        try:
            self._tick(now, ctx, chat)
        except Exception:
            self._tick_errors += 1
            if self._tick_errors <= 3 or self._tick_errors % 300 == 0:
                self.log("tick failed (%d so far), state not written this frame:\n%s" % (
                    self._tick_errors, traceback.format_exc().strip()))
            if self._tick_errors == 1:
                self._activity("compositor", "round engine tick failed: %s" % traceback.format_exc().strip().splitlines()[-1][:150], now)

    def _tick(self, now: float, ctx, chat: Optional[List[Dict]]) -> None:
        drift_before = self._mem is not None and bool(owned_drift(self._mem, self.store.state))
        s = self._compose(now)
        dirty = drift_before
        if not self._booted:
            self._booted = True
            self._boot(s, now)
            dirty = True
        elif self._sync_macro(s, now):
            dirty = True
        rnd = s.setdefault("round", {})
        phase = rnd.get("phase") or "open"
        deadline_t = iso_to_epoch(rnd.get("deadline_ts"))
        opened_t = iso_to_epoch(rnd.get("opened_ts"))

        if phase == "ship":
            if self._ship_until is None or now >= self._ship_until:
                last = (rnd.get("last_result") or {}).get("option_id") or ""
                excl = last.split(".")[1] if last.startswith("micro.") and last.count(".") >= 2 else None
                if not excl and last.startswith("idea."):
                    for o in rnd.get("options") or []:
                        if o.get("id") == last and o.get("param"):
                            excl = o["param"]
                self.open_round(s, now, exclude_param=excl)
                dirty = True
        elif deadline_t is None or opened_t is None:
            self.open_round(s, now)
            dirty = True
        elif now >= deadline_t:
            try:
                self.ship(s, now)
            except Exception as e:
                # ship() guards apply_option itself; this is the belt for anything else (disk, tallies)
                self.log("ship failed hard: %r\n%s" % (e, traceback.format_exc().strip()))
                self.fails += 1
                self.last_error = repr(e)
                rnd["phase"] = "ship"
                cur = self._version(s)["string"]
                rnd["last_result"] = {"letter": None, "title": "round %s" % rnd.get("number"), "picked_by": None, "agent_pick": True,
                                      "version": cur, "ts": epoch_to_iso(now), "ok": False, "error": repr(e)[:200]}
                self._ship_until = now + self.ship_hold_s
                self._record_ship(s, {"ts": epoch_to_iso(now), "version": cur, "kind": "micro",
                                      "option_id": None, "title": rnd["last_result"]["title"], "picked_by": None,
                                      "agent_pick": True, "ok": False, "commit": self._commit, "error": repr(e)[:200],
                                      "votes": 0, "total_votes": 0, "round": rnd.get("number")})
                self._activity("ship", "FAILED round %s: %s" % (rnd.get("number"), repr(e)[:120]), now)
            dirty = True
        elif phase == "open" and now - opened_t >= self.closing_s:
            rnd["phase"] = "closing"
            self._refresh_commit_async()          # hash is current by ship time, without blocking a frame
            dirty = True

        # tallies -> options (only when they changed)
        if rnd.get("phase") in ("open", "closing"):
            tallies = self._tallies()
            sig = tuple((k, tuple(v)) for k, v in sorted(tallies.items()))
            if sig != self._last_tally_sig:
                self._last_tally_sig = sig
                for o in rnd.get("options") or []:
                    o["voters"] = list(tallies.get(o.get("letter"), []))
                    o["votes"] = len(o["voters"])
                dirty = True

        if self._apply_chat(s, chat or [], now):
            dirty = True
        self._last_mod_sig = (tuple(sorted(self.bridge.hidden)), bool(self.bridge.paused), bool(self.bridge.display))

        if self._last_counters_write is None or now - self._last_counters_write >= COUNTERS_EVERY_S:
            self._last_counters_write = now
            self._counters(s, ctx, now)
            dirty = True

        if dirty:
            self._write(s, now)


# ----------------------------------------------------------------------------- self-test
def _self_test(run_dir: str) -> int:   # pragma: no cover - exercised by `--self-test`
    """Real StateStore + real ChatBridge + real agents/duty.py against an ISOLATED run dir. Prints one
    PASS/FAIL line per check and returns the number of failures. Refuses the canonical run dir."""
    import shutil
    import time as _time
    try:
        from stream.state_store import StateStore, normalise_chat
        from stream.chat_bridge import ChatBridge
    except Exception:  # pragma: no cover
        from state_store import StateStore, normalise_chat  # type: ignore
        from chat_bridge import ChatBridge  # type: ignore

    run_dir = os.path.abspath(run_dir)
    if run_dir == os.path.abspath(CANONICAL_RUN_DIR) or not run_dir.startswith("/tmp/"):
        print("self-test refuses run_dir %s (use an isolated /tmp/cp-* dir)" % run_dir)
        return 1
    shutil.rmtree(run_dir, ignore_errors=True)
    os.makedirs(run_dir)
    for k in ("STATE_FILE", "CHAT_FILE", "ACTIVITY_FILE", "METRICS_FILE"):
        os.environ.pop(k, None)
    os.environ["RUN_DIR"] = run_dir
    os.environ["KL_SEED"] = "7"
    fails = 0
    logs: List[str] = []

    def log(m):
        logs.append(m)
        sys.stderr.write("rounds: %s\n" % m)

    def check(name, cond, detail=""):
        nonlocal fails
        print("%s %s%s" % ("PASS" if cond else "FAIL", name, (" -- %s" % detail) if detail else ""))
        if not cond:
            fails += 1

    def disk():
        with open(os.path.join(run_dir, "state.json")) as fh:
            return json.load(fh)

    ROUND_S, CLOSING_S, HOLD_S = 6.0, 5.0, 1.0
    FPS, DT = 30, 1.0 / 30
    t0 = _time.time()
    now = [t0]
    frame = [0]
    store = StateStore(run_dir, log=log)
    store.ensure_state_file(now[0])
    store.refresh(now[0], force=True)
    bridge = ChatBridge(run_dir, log=log)
    engine = RoundEngine(run_dir, store, bridge, log=log, round_s=ROUND_S, closing_s=CLOSING_S, ship_hold_s=HOLD_S,
                         changelog_path=os.path.join(run_dir, "CHANGELOG.md"))
    tick_ms: List[float] = []

    def step(n=1, chat=None):
        out = []
        for _ in range(n):
            now[0] += DT
            frame[0] += 1
            store.refresh(now[0])
            new = store.drain_chat()
            if chat:
                new = new + chat
                chat = None
            try:
                tal = bridge.tallies()
            except Exception:
                tal = {}
            ctx = store.ctx(now[0], frame[0], FPS, tallies=tal, vote_count=bridge.vote_count(),
                            compositor_live={"fps_target": 30, "fps_actual": 30.0, "frame_ms_avg": 1.0, "frame_ms_p95": 2.0,
                                             "dropped_frames": 0, "scene": "BUILDING", "uptime_s": int(now[0] - t0)},
                            audio_source="none")
            classified = bridge.ingest(new, now[0], ctx) if new else []
            out.extend(classified)
            a = _time.perf_counter()
            engine.tick(now[0], ctx, classified)
            tick_ms.append((_time.perf_counter() - a) * 1000.0)
        return out

    mid = [0]

    def msg(name, text):
        mid[0] += 1
        return normalise_chat({"ts": epoch_to_iso(now[0]), "id": "t-%d" % mid[0], "username": name, "content": text,
                               "color": "#ffffff", "badges": [], "type": "message"})

    # --- 1. boot: version derived (v0.0.0 with no ships), round 1 open, chaos never in micro
    step(1)
    d = disk()
    check("boot: version derived from empty ships.jsonl", d["version"]["string"] == "v0.0.0" and d["version"]["shipped"] == 0, d["version"]["string"])
    check("boot: round 1 open with 3 options", d["round"]["number"] == 1 and len(d["round"]["options"]) == 3)
    check("menu: chaos entry present, not a micro key", CHAOS_PARAM in MENU_BY_PARAM and CHAOS_PARAM not in d["micro"])

    # --- 2. seeded votes: 2 for one letter, 1 for another -> that option ships with picked_by = first voter
    opts = {o["letter"]: o for o in d["round"]["options"]}
    win_letter, lose_letter = "B", "C"
    step(3, chat=[msg("test_voter_1", win_letter), msg("test_voter_2", lose_letter), msg("test_voter_3", "!%s" % win_letter.lower())])
    d = disk()
    votes = {o["letter"]: o["votes"] for o in d["round"]["options"]}
    check("votes mirrored into round.options", votes == {win_letter: 2, lose_letter: 1, "A": 0}, str(votes))
    step(int(ROUND_S * FPS) + 5)      # past the deadline -> ship
    d = disk()
    lines = read_ships(os.path.join(run_dir, "ships.jsonl"))
    lr = d["round"]["last_result"]
    check("ship 1: the seeded winner shipped", lr["letter"] == win_letter and lr["picked_by"] == "test_voter_1" and lr["votes"] == 2 and lr["total_votes"] == 3,
          json.dumps(lr)[:160])
    check("ship 1: version v0.0.1 from ships.jsonl", d["version"]["string"] == "v0.0.1" and len(lines) == 1 and lines[0]["version"] == "v0.0.1", d["version"]["string"])
    won = opts[win_letter]
    if won.get("param") == CHAOS_PARAM:
        check("ship 1 (chaos card won): micro has no chaos key, id rewritten", CHAOS_PARAM not in d["micro"] and lr["option_id"].startswith("micro.") and "chaos" not in lr["option_id"])
    else:
        got = d["micro"].get(won["param"])
        if won["param"] == "canvas_seed":
            check("ship 1: canvas_seed rerolled to a fresh int", isinstance(got, int) and got != 41370704, str(got))
        else:
            check("ship 1: micro[%s] == %s" % (won["param"], won["value"]), got == won["value"], str(got))

    # --- 3. chaos roll via a real round: put the chaos card on the live ballot and vote for it
    step(int(HOLD_S * FPS) + 3)       # ship hold -> round 2 open
    d = disk()
    check("round 2 open after hold", d["round"]["number"] == 2 and d["round"]["phase"] == "open", "%s/%s" % (d["round"]["number"], d["round"]["phase"]))
    chaos_opt = {"letter": "A", "id": "micro.chaos.roll", "title": "chaos: randomise one parameter", "source": "menu",
                 "votes": 0, "voters": [], "param": CHAOS_PARAM, "value": "roll"}
    engine._mem["round"]["options"] = [chaos_opt] + [o for o in engine._mem["round"]["options"] if o["letter"] != "A"]
    micro_before = dict(d["micro"])
    step(2, chat=[msg("test_voter_4", "a")])
    step(int(ROUND_S * FPS) + 5)
    d = disk()
    lr = d["round"]["last_result"]
    lines = read_ships(os.path.join(run_dir, "ships.jsonl"))
    changed = {k: (micro_before.get(k), v) for k, v in d["micro"].items() if micro_before.get(k) != v}
    check("chaos: title rewritten to what changed", str(lr["title"]).startswith("chaos → ") and lr["chaos"] is True, lr["title"])
    check("chaos: option id is the real param", lr["option_id"].startswith("micro.") and lr["option_id"].split(".")[1] in REAL_PARAMS, lr["option_id"])
    check("chaos: exactly one real parameter changed, never 'chaos'", len(changed) == 1 and CHAOS_PARAM not in d["micro"] and lr["option_id"].split(".")[1] in changed, str(changed))
    check("chaos: ships.jsonl line carries the real param + chaos flag", lines[-1]["option_id"] == lr["option_id"] and lines[-1].get("chaos") is True and lines[-1]["version"] == "v0.0.2")

    # --- 4. idea ids: max(existing)+1, then a duty classify is merged (foreign field on our block)
    engine._mem["ideas"] = [{"id": "i-0007", "text": "old seven", "by": "someone", "ts": epoch_to_iso(now[0] - 900), "plus": 0, "class": "pending", "status": "open", "reason": None},
                            {"id": "i-0002", "text": "old two", "by": "someone", "ts": epoch_to_iso(now[0] - 900), "plus": 0, "class": "pending", "status": "open", "reason": None}]
    step(int(HOLD_S * FPS) + 3)
    step(2, chat=[msg("test_voter_5", "!idea show the diff bigger")])
    d = disk()
    ids = [i["id"] for i in d["ideas"]]
    check("idea id = max(existing)+1", ids[-1] == "i-0008" and ids[-1] not in ids[:-1], str(ids))
    duty = [sys.executable, os.path.join(ROOT, "agents", "duty.py"), "--run-dir", run_dir]
    r = subprocess.run(duty + ["classify", "i-0008", "macro", "--reason", "needs a new panel"], capture_output=True, text=True, timeout=20)
    check("duty classify ran", r.returncode == 0, (r.stdout + r.stderr).strip()[:120])
    step(12)
    d = disk()
    i8 = next(i for i in d["ideas"] if i["id"] == "i-0008")
    check("duty classify merged into ideas[].class/status/reason", i8["class"] == "macro" and i8["status"] == "queued" and i8["reason"] == "needs a new panel", json.dumps(i8)[:160])
    check("round survived duty's write (owned key kept)", d["round"]["number"] == 3, str(d["round"]["number"]))

    # --- 5. duty macro-done -> ships.jsonl macro line -> version v0.1.0, macro/agent preserved
    r1 = subprocess.run(duty + ["macro-start", "--title", "pixel art bot", "--file", "stream/panels/pixel.py", "--minutes", "5", "--by", "test_voter_5"], capture_output=True, text=True, timeout=20)
    r2 = subprocess.run(duty + ["macro-step", "TEST", "--label", "3/5 testing"], capture_output=True, text=True, timeout=20)
    r3 = subprocess.run(duty + ["macro-done", "--ok", "--commit", "abc1234", "--idea", "i-0008"], capture_output=True, text=True, timeout=20)
    check("duty macro-start/step/done ran", r1.returncode == 0 and r2.returncode == 0 and r3.returncode == 0, (r3.stdout + r3.stderr).strip()[:120])
    dd = disk()
    check("duty wrote its own version bump on disk (v0.1.0 by its arithmetic)", dd["version"]["string"] == "v0.1.0" and dd["version"]["shipped"] == 3, dd["version"]["string"])
    step(12)
    d = disk()
    lines = read_ships(os.path.join(run_dir, "ships.jsonl"))
    mac = [o for o in lines if o["kind"] == "macro"]
    check("macro-done -> one ships.jsonl macro line", len(mac) == 1 and mac[0]["ok"] is True and mac[0]["commit"] == "abc1234" and mac[0]["title"] == "pixel art bot" and mac[0]["picked_by"] == "test_voter_5",
          json.dumps(mac[-1])[:200] if mac else "none")
    check("version after macro: v0.1.0, shipped 3, from ships.jsonl replay", d["version"] == {"string": "v0.1.0", "major": 0, "macro": 1, "micro": 0, "commit": "abc1234", "shipped": 3, "failed": 0}, json.dumps(d["version"]))
    check("macro.* preserved from duty", d["macro"]["title"] == "pixel art bot" and d["macro"]["active"] is False and d["macro"]["last_reload"]["commit"] == "abc1234")
    check("ideas[i-0008].status shipped via duty --idea merged", next(i for i in d["ideas"] if i["id"] == "i-0008")["status"] == "shipped")
    step(6)
    lines = read_ships(os.path.join(run_dir, "ships.jsonl"))
    check("macro line not duplicated on later ticks", sum(1 for o in lines if o["kind"] == "macro") == 1)

    # --- 6. foreign writer scribbles version.micro=99 / round.number=999 / micro.palette mid-run
    scrib = disk()
    scrib["version"]["micro"] = 99
    scrib["version"]["string"] = "v9.9.99"
    scrib["round"]["number"] = 999
    scrib["micro"]["palette"] = "zzz"
    scrib["agent"] = {"on_duty": True, "heartbeat_ts": epoch_to_iso(now[0]), "name": "foreign-writer"}
    write_state_atomic(os.path.join(run_dir, "state.json"), scrib)
    _time.sleep(0.02)
    ev0 = engine.drift_events
    store.refresh(now[0] + 0.3, force=True)
    adopted = store.state["version"]["micro"] == 99
    step(2)
    d = disk()
    check("store saw the scribble (precondition)", adopted)
    check("engine did NOT adopt version.micro=99", d["version"]["micro"] == 0 and d["version"]["string"] == "v0.1.0" and store.state["version"]["micro"] == 0, json.dumps(d["version"]))
    check("engine did NOT adopt round.number=999 / micro.palette=zzz", d["round"]["number"] == 3 and d["micro"]["palette"] != "zzz", "%s %s" % (d["round"]["number"], d["micro"]["palette"]))
    check("foreign agent.* from the same write WAS adopted", d["agent"]["name"] == "foreign-writer" and d["agent"]["on_duty"] is True)
    check("drift logged once as an event", engine.drift_events == ev0 + 1 and any("foreign write to owned state" in m for m in logs), str(engine.drift_events))
    # a second scribble of the same shape is a new event once we have restored
    scrib = disk(); scrib["version"]["micro"] = 42
    write_state_atomic(os.path.join(run_dir, "state.json"), scrib)
    store.refresh(now[0] + 0.6, force=True)
    step(2)
    check("second scribble also restored", disk()["version"]["micro"] == 0 and engine.drift_events == ev0 + 2)

    # --- 7. a raise inside ship (tallies) is a FAILED ship, engine keeps going
    real_tallies = bridge.tallies
    bridge.tallies = lambda: (_ for _ in ()).throw(RuntimeError("injected"))
    step(int(ROUND_S * FPS) + 8)
    bridge.tallies = real_tallies
    d = disk()
    lines = read_ships(os.path.join(run_dir, "ships.jsonl"))
    check("injected tallies raise -> FAILED ship recorded, failed=1, micro unchanged", lines[-1]["ok"] is False and "injected" in str(lines[-1]["error"])
          and d["version"]["failed"] == 1 and d["version"]["micro"] == 0, "%s | last line ok=%s error=%s" % (json.dumps(d["version"]), lines[-1]["ok"], lines[-1]["error"]))
    step(int(HOLD_S * FPS) + 3)
    check("next round opened after the failed ship", disk()["round"]["phase"] == "open" and disk()["round"]["number"] == 4)

    # --- 8. restart: a new engine over the same run dir re-derives the same version and dedups the macro
    engine2 = RoundEngine(run_dir, store, bridge, log=log, round_s=ROUND_S, closing_s=CLOSING_S, ship_hold_s=HOLD_S,
                          changelog_path=os.path.join(run_dir, "CHANGELOG.md"))
    engine2.tick(now[0] + DT, store.ctx(now[0] + DT, frame[0] + 1, FPS), [])
    lines2 = read_ships(os.path.join(run_dir, "ships.jsonl"))
    check("restart: version re-derived identically, no duplicate macro line", disk()["version"]["string"] == "v0.1.0" and len(lines2) == len(lines))

    # --- 9. canonical run dir refuses test hooks (construct only; nothing is written)
    class _Silent(object):
        state_file = os.path.join(CANONICAL_RUN_DIR, "state.json.NEVER")
    class _NoBridge(object):
        hidden = set(); paused = False; display = True; mod_actions = []; founders = []; builders = {}
        def reset_round(self, t): pass
        def tallies(self): return {"A": [], "B": [], "C": []}
        def vote_count(self): return 0
    e3 = RoundEngine(CANONICAL_RUN_DIR, _Silent(), _NoBridge(), log=log, round_s=3.0, changelog_path="/tmp/x.md")
    check("canonical run dir refuses test hooks", e3.round_s == 180.0 and e3.changelog_path.endswith("docs/CHANGELOG.md") and any("REFUSING test hooks" in m for m in logs))

    # --- 10. derive_version over the real live-night file shape (copied in memory, read-only)
    hist = [{"ts": "2026-09-24T11:25:08Z", "version": "vX", "kind": "micro", "ok": True},
            {"ts": "2026-09-24T11:28:13Z", "version": "vX", "kind": "micro", "ok": True},
            {"ts": "2026-09-24T11:40:20Z", "version": "vX", "kind": "micro", "ok": True},
            {"ts": "2026-09-25T00:00:00Z", "version": "vX", "kind": "macro", "ok": True, "macro_ts": "2026-09-24T11:41:16Z", "commit": "6781fce"},
            {"ts": "2026-09-24T11:43:28Z", "version": "vX", "kind": "micro", "ok": True}]
    dv = derive_version(hist, {"major": 0})
    check("derive_version: file-order replay ignores old version strings", dv["string"] == "v0.1.1" and dv["shipped"] == 5 and dv["commit"] == "6781fce", dv["string"])

    tick_ms.sort()
    p95 = tick_ms[int(len(tick_ms) * 0.95)]
    print("tick cost over %d frames: avg %.3f ms, p95 %.3f ms, max %.3f ms" % (len(tick_ms), sum(tick_ms) / len(tick_ms), p95, tick_ms[-1]))
    print("ships.jsonl lines: %d  CHANGELOG lines: %d  drift events: %d  run_dir: %s" % (
        len(read_ships(os.path.join(run_dir, "ships.jsonl"))),
        sum(1 for ln in open(os.path.join(run_dir, "CHANGELOG.md")) if ln.startswith("- ")), engine.drift_events, run_dir))
    print("%d check(s) failed" % fails if fails else "ALL CHECKS PASSED")
    return fails


def check_titles(max_w: int = 184, max_lines: int = 2) -> int:
    """Every MENU title (each value) must wrap into <= max_lines HN 22 lines inside the ballot card's title column
    (264 px card - 68 px letter column - 12 px pad = 184 px) with nothing truncated. Returns the failure count."""
    fails = 0
    for m in MENU:
        for v in m["values"]:
            t = RoundEngine._title(m, v)
            lines = L.wrap("HN", 22, t, max_w, max_lines=max_lines)
            bad = len(lines) > max_lines or "…" in " ".join(lines) or any(L.text_width("HN", 22, ln) > max_w for ln in lines)
            fails += 1 if bad else 0
            print("%s %-15s %-10s %-34s -> %s" % ("FAIL" if bad else " ok ", m["param"], str(v), t, " | ".join(lines)))
    print("%d title(s) do not fit %d px x %d lines" % (fails, max_w, max_lines) if fails else "ALL %d TITLES FIT" % sum(len(m["values"]) for m in MENU))
    return fails


if __name__ == "__main__":
    if "--check-titles" in sys.argv:
        sys.exit(1 if check_titles() else 0)
    if "--self-test" in sys.argv:
        rd = None
        if "--run-dir" in sys.argv:
            rd = sys.argv[sys.argv.index("--run-dir") + 1]
        rd = rd or os.environ.get("RUN_DIR") or "/tmp/cp-rounds-selftest"
        sys.exit(1 if _self_test(rd) else 0)
    print("MENU (%d params):" % len(MENU))
    for m in MENU:
        print("  %-15s %s" % (m["param"], m["values"]))
    ships = read_ships(sys.argv[1]) if len(sys.argv) > 1 else []
    if ships:
        print("derived version from %s: %s" % (sys.argv[1], derive_version(ships)))
