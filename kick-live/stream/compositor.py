#!/usr/bin/env python
"""compositor.py - SHIP IT LIVE frame loop. 1280x720 rgb24 at 30 fps on stdout for stream/run.sh
(SOURCE=compositor), s16le 48 kHz stereo audio in lockstep on a FIFO, or PNG frames for --self-test.

Usage:
  python stream/compositor.py                      # stream: rgb24 frames -> stdout (run.sh pipes to ffmpeg)
  python stream/compositor.py --audio-fifo PATH    # also write 48000/fps samples per frame to the FIFO
                                                   # (default: AUDIO_SOURCE=pipe:PATH from the environment)
  python stream/compositor.py --self-test 90       # render 90 PNGs to $RUN_DIR/selftest/, no ffmpeg, no FIFO
  --run-dir DIR   override $RUN_DIR      --fps N   override $STREAM_FPS (30; 24 is the fallback)
  --frames N      stop after N frames    --no-audio  skip the in-process AudioEngine entirely
Test hooks: KL_FAULT_PANELS=key1,key2 makes those panels raise in render(); KL_SLOW_PANELS=key1 makes
them sleep 35 ms per render (trips the 28 ms frame-time guard). Both prove the loop survives.
KL_ROUND_S=<sec> shortens the micro round; KL_CHANGELOG=<path> redirects the CHANGELOG append (tests only).
KL_SELFTEST_REALTIME=1 paces --self-test at real fps (so a file can be edited mid-run).

Run-dir guard (journal 012): the canonical LIVE run dirs are ~/.local/share/kick-live/run and
~/.local/share/kick-live/run-live (+ $KL_LIVE_RUN_DIR). Any test mode (--self-test, --frames, KL_*) pointed at
one of them exits 2 before touching a file; stream mode into one of them needs KL_LIVE=1 or an explicit
--run-dir <canonical>, otherwise exit 2 (an inherited $RUN_DIR is never enough to start a live render).

Hot reload (journal 011, no-restart rule): stream/panels/*.py and stream/scenes/*.py are watched (mtime, every
2 s). A changed file is py_compile'd first (syntax error -> logged, old module kept), then executed as a NEW
module object and its panels re-registered without restarting the loop or touching ffmpeg. If the new panel
raises within its first 30 renders the previous panel + module object are restored (rollback) and an
activity line is written. KL_HOT_RELOAD=0 disables the watcher.

Pacing: wallclock. If the loop falls a whole frame behind, the last frame is duplicated (with a fresh
audio block) rather than letting stream time drift; counted as dropped_frames. One frame = one audio
block, so A/V cannot drift by construction. Nothing here ever goes live: it only writes to stdout and
the FIFO run.sh hands it.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import py_compile
import queue
import re
import signal
import sys
import threading
import time
import traceback
from typing import Dict, List, Optional, Set, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw  # noqa: E402

from stream import layout as L  # noqa: E402
from stream.panels import PANEL_REGISTRY, IMPORT_ERRORS, discover, placeholder  # noqa: E402
from stream.state_store import StateStore, epoch_to_iso, iso_to_epoch, run_path  # noqa: E402
from stream.chat_bridge import ChatBridge  # noqa: E402
from stream.rounds import RoundEngine  # noqa: E402
from stream.audio import AudioEngine  # noqa: E402

PANEL_BUDGET_MS = 28.0
PANEL_STRIKES = 30
PANEL_RETRY_FRAMES = 300
STATIC_WATCHDOG_FRAMES = 30
WORLD_BAND = (0, 720)            # the static watchdog watches the WORLD rows = the whole frame (full-bleed land, journal 034)
# the owner's rule as a mechanical gate (journal 032 / 034): none of these may appear, as a whole token, in any string the
# world panel writes ITSELF (plank, plates, board, sign, marker, arrows, letters). A person's own words (bubbles, labels)
# are theirs and are excluded; `@tokens` are stripped before matching. Wall clocks match outside the timer / closes-in forms.
BANNED_COPY = ("ai", "keeper", "keepers", "on duty", "build", "builds", "show", "live", "version", "fps", "ms", "viewer", "viewers",
               "watching", "camera", "mic", "fake", "honest", "honesty", "surveying", "awake", "longgrass", "chat is quiet",
               "someone is arriving", "leads", "tied", "reverting", "next round soon", "picked", "failed", "counts while standing",
               "to do that, type", "the keepers read it next", "one letter decides it")
BANNED_COPY_RE = re.compile(r"(?<![a-z0-9_])(?:%s)(?![a-z0-9_])" % "|".join(re.escape(t) for t in sorted(BANNED_COPY, key=len, reverse=True)))
BANNED_VERSION_RE = re.compile(r"(?<![a-z0-9_])v\d+\.\d+")
BANNED_DAY_RE = re.compile(r"(?<![a-z0-9_])day \d+")
BANNED_CLOCK_RE = re.compile(r"(?<![0-9:])\d{1,2}:\d{2}(?![0-9:])")
CLOCK_OK_RE = re.compile(r"(closes in \d{1,2}:\d{2}|^\d{1,2}:\d{2}$|A B C · \d{1,2}:\d{2})")
TILE_SIZES = ((320, 180), (284, 160))   # Kick's directory tile and the smallest card it actually serves
TILE_MIN_PX = 16.0                      # a creature + its name chip must be at least this tall at 284 wide
HOT_RELOAD_S = 2.0               # file watch interval (wallclock)
HOT_RELOAD_SETTLE_S = 0.3        # a file modified less than this long ago may still be half-written: next poll
HOT_RELOAD_PROBATION = 30        # renders during which a raise rolls back to the previous panel + module
TEST_ENV_HOOKS = ("KL_ROUND_S", "KL_FAULT_PANELS", "KL_SLOW_PANELS", "KL_CHANGELOG", "KL_SELFTEST_REALTIME", "KL_TEST_PIPS",
                  "KL_CLOCK_SHIFT_S",      # nature.py: shifts the clock the LIGHT reads (dawn / noon / 23:00 renders), MODE=test only
                  "KL_FORCE_ZOOM")         # steading.py: pins the camera zoom for the budget gate, with KL_TEST_PIPS only


def log(msg: str) -> None:
    sys.stderr.write("%s compositor: %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


# ---------------------------------------------------------------------------- run-dir guard
def canonical_run_dirs() -> List[str]:
    """The LIVE run dirs (realpaths): ~/.local/share/kick-live/run, .../run-live, plus $KL_LIVE_RUN_DIR."""
    home = os.path.expanduser("~")
    dirs = [os.path.join(home, ".local", "share", "kick-live", "run"),
            os.path.join(home, ".local", "share", "kick-live", "run-live")]
    extra = os.environ.get("KL_LIVE_RUN_DIR")
    if extra:
        dirs.append(extra)
    return [os.path.realpath(d) for d in dirs]


def test_mode_reasons(self_test: int, frames: int, env=None) -> List[str]:
    """Why this invocation counts as a test: --self-test, --frames, or any KL_* test hook in the environment."""
    env = os.environ if env is None else env
    out: List[str] = []
    if self_test:
        out.append("--self-test")
    if frames:
        out.append("--frames")
    for k in TEST_ENV_HOOKS:
        if env.get(k):
            out.append(k)
    return out


def run_dir_guard(run_dir: str, explicit_run_dir: bool, reasons: List[str], env=None) -> Optional[str]:
    """None when the start is allowed, else the refusal message (caller prints it and exits 2).
    Test mode + canonical dir -> always refused. Stream mode + canonical dir -> needs KL_LIVE=1 or --run-dir."""
    env = os.environ if env is None else env
    real = os.path.realpath(run_dir)
    canon = canonical_run_dirs()
    if real not in canon:
        # Belt and braces for the leak that bit on 2026-09-25: env.sh derives $STATE_FILE etc. from $RUN_DIR at
        # source time, so a later `RUN_DIR=/tmp/cp-x` prefix leaves them pointing at the shared dir. run_path()
        # now ignores such stale values; still refuse if any derived file would land in a canonical dir.
        for env_name, default_name in (("STATE_FILE", "state.json"), ("CHAT_FILE", "chat.jsonl"),
                                       ("ACTIVITY_FILE", "activity.jsonl"), ("METRICS_FILE", "metrics.jsonl")):
            p = run_path(run_dir, env_name, default_name)
            if os.path.realpath(os.path.dirname(os.path.abspath(p))) in canon:
                return ("REFUSING to start: run_dir is %s but $%s=%s points into the canonical LIVE run dir.\n"
                        "  Stale env.sh export? unset %s (or re-source scripts/env.sh with RUN_DIR already set)." % (run_dir, env_name, p, env_name))
        return None
    if reasons:
        return ("REFUSING to start: run_dir %s is the canonical LIVE run dir and this is a test run (%s).\n"
                "  Tests must use an isolated dir: RUN_DIR=/tmp/cp-<label> $PYTHON stream/compositor.py ... or --run-dir /tmp/cp-<label>.\n"
                "  (journal 012: a test against the shared dir wrote foreign version/round fields into the live state.json)"
                % (run_dir, ", ".join(reasons)))
    if env.get("KL_LIVE") == "1" or explicit_run_dir:
        return None
    return ("REFUSING to start: run_dir %s is the canonical LIVE run dir (inherited from $RUN_DIR) but neither KL_LIVE=1\n"
            "  nor an explicit --run-dir %s was given. A live render must say so: KL_LIVE=1 ... or --run-dir <canonical>."
            % (run_dir, run_dir))


class Slot(object):
    def __init__(self, panel):
        self.panel = panel
        self.key = panel.key
        self.box = L.region_box(panel.region)
        self.size = (self.box[2], self.box[3])
        self.img: Optional[Image.Image] = None
        self.last_inputs = object()
        self.error_logged = False
        self.retry_at = -1
        self.disabled_until = -1
        self.strikes = 0
        self.renders = 0
        self.render_ms_total = 0.0
        self.render_ms_max = 0.0
        self.prev: Optional[Tuple] = None      # (previous panel or None, [(modname, previous module or None)]) while on probation
        self.probation = 0                     # renders left before a hot-reloaded panel is committed

    def reset(self) -> None:
        self.last_inputs = object()
        self.error_logged = False
        self.retry_at = -1
        self.disabled_until = -1
        self.strikes = 0

    def rebox(self) -> None:
        self.box = L.region_box(self.panel.region)
        self.size = (self.box[2], self.box[3])


class HotReloader(object):
    """Watches stream/panels/*.py and stream/scenes/*.py (mtime + size, every HOT_RELOAD_S s of wallclock).

    change -> py_compile (syntax error: logged + activity line, old module kept)
           -> the file is executed as a NEW module object under its dotted name (the old object survives for
              rollback), register() calls land in PANEL_REGISTRY, the matching Slot gets the new panel with
              `prev` armed for HOT_RELOAD_PROBATION renders
           -> a scene file also re-executes every panel module whose source mentions `stream.scenes`, so the
              stage rebinds to the fresh scene module (their Slot.prev carries the scene module too)
    An import-time exception restores sys.modules and the registry (old module kept). A raise inside
    inputs()/render() while `prev` is armed -> Compositor._rollback(): previous panel + module objects back,
    one stderr line + one activity line. Nothing here touches the encoder: ffmpeg never notices.
    """

    WATCH = (("stream.panels", os.path.join(ROOT, "stream", "panels")),
             ("stream.scenes", os.path.join(ROOT, "stream", "scenes")),
             ("stream.world", os.path.join(ROOT, "stream", "world")))     # world core: re-exec, then the scene rebinds

    def __init__(self, comp: "Compositor"):
        self.comp = comp
        self.enabled = os.environ.get("KL_HOT_RELOAD", "1") != "0"
        self.sig: Dict[str, Tuple[int, int]] = self._scan()
        self.last_poll: Optional[float] = None
        self.pyc_dir = os.path.join(comp.run_dir, ".hotreload")
        self.stats: Dict = {"reloads": 0, "rejected": 0, "rollbacks": 0, "last": None}

    def _scan(self) -> Dict[str, Tuple[int, int]]:
        out: Dict[str, Tuple[int, int]] = {}
        for _pkg, d in self.WATCH:
            try:
                names = os.listdir(d)
            except OSError:
                continue
            for n in names:
                if not n.endswith(".py") or n.startswith("_"):
                    continue
                p = os.path.join(d, n)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                out[p] = (st.st_mtime_ns, st.st_size)
        return out

    def poll(self, wall_now: float, frame: int) -> None:
        """Call once per frame; does the stat walk every HOT_RELOAD_S seconds."""
        if not self.enabled:
            return
        if self.last_poll is not None and wall_now - self.last_poll < HOT_RELOAD_S:
            return
        self.last_poll = wall_now
        cur = self._scan()
        changed: List[str] = []
        for p, sig in sorted(cur.items()):
            if self.sig.get(p) == sig:
                continue
            if wall_now - sig[0] / 1e9 < HOT_RELOAD_SETTLE_S:
                continue                                   # still being written; look again next poll
            self.sig[p] = sig
            changed.append(p)
        # A deploy drops many files in one poll (OPENWORLD.md 14: world core + scene + panels together). The world
        # modules are re-executed as ONE batch with ONE scene/panel cascade, and a scene or panel file that cascade
        # already re-executed (or imported fresh from disk) is not executed a second time, so the swap constructs one
        # scene, not one per changed file.
        world = [p for p in changed if self._modname(p)[0] == "stream.world"]
        handled: Set[str] = set()
        if world:
            try:
                handled = self._reload_world_modules(world, frame)
            except Exception:
                log("hot reload: unexpected error on the world batch %s:\n%s" % ([os.path.relpath(p, ROOT) for p in world], traceback.format_exc()))
        for p in changed:
            if p in world:
                continue
            modname = self._modname(p)[1]
            if modname and modname in handled:
                log("hot reload: %s already re-executed by this poll's world cascade; not swapped twice" % os.path.relpath(p, ROOT))
                continue
            try:
                self._changed(p, frame)
            except Exception:
                log("hot reload: unexpected error on %s:\n%s" % (p, traceback.format_exc()))
        for p in list(self.sig):
            if p not in cur:
                self.sig.pop(p, None)
                log("hot reload: %s removed; the loaded module stays" % os.path.relpath(p, ROOT))

    def _modname(self, path: str) -> Tuple[Optional[str], Optional[str]]:
        d = os.path.abspath(os.path.dirname(path))
        for pkg, wd in self.WATCH:
            if os.path.abspath(wd) == d:
                return pkg, pkg + "." + os.path.splitext(os.path.basename(path))[0]
        return None, None

    def _syntax_error(self, path: str) -> Optional[str]:
        """py_compile the file into $RUN_DIR/.hotreload/ (never into the package's __pycache__). None when it compiles."""
        try:
            os.makedirs(self.pyc_dir, exist_ok=True)
            cfile = os.path.join(self.pyc_dir, os.path.basename(path) + "c")
            py_compile.compile(path, cfile=cfile, doraise=True)
            return None
        except py_compile.PyCompileError as e:
            msg = str(getattr(e, "msg", e) or e)
            lines = [ln.strip() for ln in msg.strip().splitlines() if ln.strip()]
            m = re.search(r"line (\d+)", msg)
            return "%s%s" % (lines[-1] if lines else "compile error", " (line %s)" % m.group(1) if m else "")
        except Exception as e:
            return repr(e)

    def _changed(self, path: str, frame: int) -> None:
        pkg, modname = self._modname(path)
        if not modname:
            return
        rel = os.path.relpath(path, ROOT)
        err = self._syntax_error(path)
        if err:
            self.stats["rejected"] += 1
            msg = "hot reload REJECTED %s: %s; old module kept" % (rel, err)
            log(msg)
            self.comp._activity(msg)
            return
        if pkg == "stream.scenes":
            self._reload_scene(modname, path, frame)
        elif pkg == "stream.world":
            self._reload_world_modules([path], frame)
        else:
            self._reload_panel_module(modname, path, frame, [])

    @staticmethod
    def _exec_fresh(modname: str, path: str) -> Tuple[Optional[object], Optional[str]]:
        """Execute `path` as a NEW module object registered as `modname`. (module, None) or (None, error)."""
        old = sys.modules.get(modname)
        try:
            spec = importlib.util.spec_from_file_location(modname, path)
            mod = importlib.util.module_from_spec(spec)
            mod.__package__ = modname.rpartition(".")[0]
            sys.modules[modname] = mod
            spec.loader.exec_module(mod)
            # `from stream.scenes import hollow as H` reads the PARENT PACKAGE attribute, not sys.modules: without this
            # rebind a re-executed panel would keep the old scene / world module object (integration finding).
            HotReloader._rebind_parent(modname, mod)
            return mod, None
        except Exception:
            if old is not None:
                sys.modules[modname] = old
                HotReloader._rebind_parent(modname, old)
            else:
                sys.modules.pop(modname, None)
            return None, traceback.format_exc().strip().splitlines()[-1]

    @staticmethod
    def _rebind_parent(modname: str, mod) -> None:
        pkg, _, child = modname.rpartition(".")
        parent = sys.modules.get(pkg) if pkg else None
        if parent is not None:
            try:
                setattr(parent, child, mod)
            except Exception:
                pass

    def _reload_panel_module(self, modname: str, path: str, frame: int, cascade: List[Tuple[str, object]]) -> bool:
        old_mod = sys.modules.get(modname)
        before = dict(PANEL_REGISTRY)
        _mod, err = self._exec_fresh(modname, path)
        if err:
            PANEL_REGISTRY.clear()
            PANEL_REGISTRY.update(before)
            self.stats["rejected"] += 1
            msg = "hot reload FAILED %s at import: %s; old module kept" % (modname, err)
            log(msg)
            self.comp._activity(msg)
            return False
        changed = [k for k, v in PANEL_REGISTRY.items() if before.get(k) is not v]
        if not changed:
            log("hot reload: %s re-executed but registered no panel; nothing swapped" % modname)
            return True
        prev_mods: List[Tuple[str, object]] = [(modname, old_mod)] + list(cascade)
        # the world scene instance parked on the panels package (stream.panels._WORLD_SCENE) before this swap: a
        # rollback puts it back, so the restored world panel renders ITS scene, not the one the new module installed
        prev_scene = getattr(sys.modules.get("stream.panels"), "_WORLD_SCENE", None) if old_mod is not None else None
        prev_scene = getattr(old_mod, "SCENE", prev_scene) if prev_scene is None and old_mod is not None else prev_scene
        for k in changed:
            panel = PANEL_REGISTRY[k]
            slot = self.comp.slot_for(k)
            if slot is None:
                slot = self.comp.add_slot(panel)
                slot.prev = (None, prev_mods, prev_scene)  # rollback = drop the slot again
            else:
                slot.prev = (slot.panel, prev_mods, prev_scene)
                slot.panel = panel
                slot.rebox()
            slot.reset()
            slot.probation = HOT_RELOAD_PROBATION
            self.comp.apply_test_hooks(panel)
        self.stats["reloads"] += 1
        self.stats["last"] = modname
        msg = "hot reload: %s -> panel%s [%s] live from frame %d (rollback armed for %d renders)" % (
            modname, "s" if len(changed) > 1 else "", " ".join(changed), frame, HOT_RELOAD_PROBATION)
        log(msg)
        self.comp._activity(msg)
        return True

    # leaves first, so a re-executed module binds the NEW object of everything it imports (behaviour -> terrain / land /
    # state; bake -> terrain / nature; keepers / honesty -> behaviour / state); anything unlisted follows alphabetically
    WORLD_ORDER = ("terrain", "nature", "state", "land", "camera", "bake", "pips", "honesty", "keepers", "behaviour")

    def _reload_world_modules(self, paths: List[str], frame: int) -> Set[str]:
        """stream/world/*.py changed (WORLD_API.md 9; several at once on a deploy, OPENWORLD.md 14): execute each
        LOADED one fresh under its name in dependency order, then ONE cascade: every loaded scene module is re-executed
        (the cave for the rollback week, the land for LONGGRASS) and the panels that mention `stream.scenes` are rebound
        once, after the last scene, with every re-executed module on their rollback list. A world file that was never
        imported (a new module) is left to the scene's own import, which reads the current file. Returns the dotted
        names this cascade re-executed or imported fresh, so poll() does not swap them a second time."""
        before = set(sys.modules)
        order = {n: i for i, n in enumerate(self.WORLD_ORDER)}
        paths = sorted(paths, key=lambda p: (order.get(os.path.splitext(os.path.basename(p))[0], len(order)), p))
        cascade: List[Tuple[str, object]] = []
        done: List[str] = []
        for path in paths:
            modname = self._modname(path)[1]
            if not modname:
                continue
            if modname not in sys.modules:
                log("hot reload: %s changed but was never imported; the scene imports it fresh" % modname)
                continue
            if modname not in before:
                log("hot reload: %s was imported fresh by an earlier module of this batch; current already" % modname)
                continue
            old_mod = sys.modules.get(modname)
            _mod, err = self._exec_fresh(modname, path)
            if err:
                self.stats["rejected"] += 1
                msg = "hot reload FAILED %s at import: %s; old module kept" % (modname, err)
                log(msg)
                self.comp._activity(msg)
                continue
            self.stats["reloads"] += 1
            self.stats["last"] = modname
            cascade.append((modname, old_mod))
            done.append(modname)
        handled: Set[str] = set(done)
        if not done:
            return handled
        scenes = [("stream.scenes." + n, os.path.join(ROOT, "stream", "scenes", n + ".py")) for n in ("hollow", "steading")]
        loaded = [(m, p) for m, p in scenes if m in sys.modules and os.path.exists(p)]
        if not loaded:
            log("hot reload: %s re-executed (no scene loaded to rebind)" % ", ".join(done))
            return handled
        for i, (smod, spath) in enumerate(loaded):
            last = i == len(loaded) - 1
            log("hot reload: %s re-executed; rebinding the scene %s" % (", ".join(done), smod))
            handled.add(smod)
            if last:
                handled.update(self._reload_scene(smod, spath, frame, cascade=cascade))
            else:
                old_scene = sys.modules.get(smod)
                _m, err = self._exec_fresh(smod, spath)
                if err:
                    self.stats["rejected"] += 1
                    msg = "hot reload FAILED %s at import: %s; old module kept" % (smod, err)
                    log(msg)
                    self.comp._activity(msg)
                    continue
                self.stats["reloads"] += 1
                cascade.append((smod, old_scene))
        # modules the cascade imported for the first time (e.g. stream.scenes.steading pulled in by the world panel) were
        # read from the current file: a change notice for them in the same poll must not execute them again
        handled.update(m for m in sys.modules if m not in before and m.startswith(("stream.scenes.", "stream.panels.", "stream.world.")))
        return handled

    def _reload_world_module(self, modname: str, path: str, frame: int) -> None:
        """Single-file form kept for callers; see _reload_world_modules."""
        self._reload_world_modules([path], frame)

    def _reload_scene(self, modname: str, path: str, frame: int, cascade: Optional[List[Tuple[str, object]]] = None) -> List[str]:
        """Returns the dotted names of the panel modules it re-executed ([] when the scene failed to import)."""
        old_mod = sys.modules.get(modname)
        _mod, err = self._exec_fresh(modname, path)
        if err:
            self.stats["rejected"] += 1
            msg = "hot reload FAILED %s at import: %s; old module kept" % (modname, err)
            log(msg)
            self.comp._activity(msg)
            return []
        self.stats["reloads"] += 1
        self.stats["last"] = modname
        deps: List[Tuple[str, str]] = []
        for pkg, d in self.WATCH:
            if pkg != "stream.panels":
                continue
            for n in sorted(os.listdir(d)):
                if not n.endswith(".py") or n.startswith("_"):
                    continue
                p = os.path.join(d, n)
                try:
                    with open(p, "r", encoding="utf-8") as fh:
                        src = fh.read()
                except OSError:
                    continue
                if "stream.scenes" in src and (pkg + "." + n[:-3]) in sys.modules:
                    deps.append((pkg + "." + n[:-3], p))
        msg = "hot reload: %s -> fresh scene module at frame %d; rebinding %s" % (
            modname, frame, ", ".join(m for m, _ in deps) or "no panels")
        log(msg)
        self.comp._activity(msg)
        for dep_mod, dep_path in deps:
            self._reload_panel_module(dep_mod, dep_path, frame, [(modname, old_mod)] + list(cascade or []))
        return [m for m, _ in deps]


class Compositor(object):
    def __init__(self, run_dir: str, fps: float, audio_fifo: Optional[str], no_audio: bool, selftest: int = 0):
        self.run_dir = run_dir
        self.fps = float(fps)
        self.frame_dt = 1.0 / self.fps
        self.block = int(round(48000 / self.fps))
        self.audio_fifo = audio_fifo
        self.selftest = selftest
        # RELAY_SOCK (set by stream/relay.py, the process that owns ffmpeg's pipes): send frames + audio blocks
        # over that unix socket instead of stdout/FIFO, so this process can restart without ffmpeg noticing.
        self.relay_sock = None if selftest else (os.environ.get("RELAY_SOCK") or None)
        self.activity_file = run_path(run_dir, "ACTIVITY_FILE", "activity.jsonl")
        os.makedirs(run_dir, exist_ok=True)

        self.store = StateStore(run_dir, log=log)
        self.bridge = ChatBridge(run_dir, log=log)
        # Test hooks (never set in production): KL_ROUND_S shortens the 180 s round so a self-test can
        # exercise open -> closing -> ship; KL_CHANGELOG redirects the CHANGELOG append away from docs/.
        round_s = float(os.environ.get("KL_ROUND_S") or 180.0)
        self.engine = RoundEngine(run_dir, self.store, self.bridge, log=log, round_s=round_s,
                                  closing_s=round_s * (150.0 / 180.0), changelog_path=os.environ.get("KL_CHANGELOG") or None)
        if round_s != 180.0:
            log("TEST HOOK: KL_ROUND_S=%g (rounds are %g s, not 180 s)" % (round_s, round_s))
        self.audio = None if no_audio else AudioEngine(block=self.block, fps=self.fps, log=log)
        if audio_fifo:
            self.audio_source = "fifo"
        elif no_audio:
            self.audio_source = "none"
        else:
            self.audio_source = "fallback"       # run.sh aevalsrc bed carries the audio

        discover(log)
        for m in IMPORT_ERRORS:
            self._activity("panel import failed: %s" % m[:160])
        faults = set(filter(None, (os.environ.get("KL_FAULT_PANELS") or "").split(",")))
        slows = set(filter(None, (os.environ.get("KL_SLOW_PANELS") or "").split(",")))
        self._faults, self._slows = faults, slows
        # world FIRST (the colony / keeper / ticker strips read its counts the same tick), header LAST (the thumbnail)
        order = sorted(PANEL_REGISTRY.values(), key=lambda p: (p.region.startswith("header"), p.region != "world", p.key))
        self.slots: List[Slot] = []
        for p in order:
            self.apply_test_hooks(p)
            self.slots.append(Slot(p))
        log("%d panels: %s" % (len(self.slots), " ".join(s.key for s in self.slots)))
        self.reloader = HotReloader(self)
        if self.reloader.enabled:
            log("hot reload: watching %d files under stream/panels + stream/scenes + stream/world every %g s" % (len(self.reloader.sig), HOT_RELOAD_S))

        self.canvas = Image.new("RGB", (L.W, L.H), L.COLORS["bg"])
        self.frame_ms: List[float] = []
        self.dropped = 0
        self.frames = 0
        self.same_frames = 0
        self.same_world = 0
        self.longest_static_world = 0
        self.last_bytes: Optional[bytes] = None
        self.last_world: Optional[bytes] = None
        self.running = True
        self.vq: "queue.Queue" = queue.Queue(maxsize=6)
        self.aq: "queue.Queue" = queue.Queue(maxsize=64)
        self.writer_error: Optional[str] = None
        self._boot_chat: List[Dict] = []      # recent (< 60 s) !idea/!theme records found at boot, applied on the first tick
        self.counters: Dict = {"fps_target": int(round(self.fps)), "fps_actual": 0.0, "frame_ms_avg": 0.0, "frame_ms_p95": 0.0,
                               "dropped_frames": 0, "scene": "STATUS", "uptime_s": 0, "panels_disabled": [],
                               "hot_reload": self.reloader.stats, "selftest": bool(selftest)}
        self._frame_votes: List[Dict] = []    # accepted live votes ingested this frame (vote-to-strip latency proof)
        self.vote_acks = [0, 0]               # [acknowledged on the same frame, total]
        self.boot_frames = 0                  # self-test: frames before the land scene booted (excluded from the watchdog / tile gate)
        self.board_checked = 0                # self-test: frames the MOOT BOARD was drawn
        self.board_mismatch = 0               # ... where its lit segment / titles disagreed with who stands / the round's options
        self.copy_frames = 0                  # self-test: frames the copy check ran over the panel's own strings
        self.copy_hits = 0                    # ... banned strings drawn (must stay 0)
        self.tile_stats: Dict[str, int] = {k: 0 for k in ("frames", "awake_frames", "awake_ok", "zero_frames", "zero_ok", "moot_frames", "moot_ok",
                                                          "sign_frames", "marker_due", "marker_ok")}

    # ------------------------------------------------------------------ slots (hot reload uses these)
    def slot_for(self, key: str) -> Optional[Slot]:
        for s in self.slots:
            if s.key == key:
                return s
        return None

    def add_slot(self, panel) -> Slot:
        """Insert a slot for a newly registered panel, keeping header panels last."""
        slot = Slot(panel)
        if panel.region.startswith("header"):
            self.slots.append(slot)
        elif panel.region == "world":
            self.slots.insert(0, slot)
        else:
            idx = next((i for i, s in enumerate(self.slots) if s.panel.region.startswith("header")), len(self.slots))
            self.slots.insert(idx, slot)
        return slot

    def apply_test_hooks(self, panel) -> None:
        if panel.key in self._faults:
            self._inject_fault(panel)
        if panel.key in self._slows:
            self._inject_slow(panel)

    # ------------------------------------------------------------------ test hooks
    @staticmethod
    def _inject_fault(panel):
        def boom(ctx, size):
            raise RuntimeError("injected fault (KL_FAULT_PANELS)")
        panel.render = boom
        log("TEST HOOK: panel %s will raise in render()" % panel.key)

    @staticmethod
    def _inject_slow(panel):
        orig = panel.render

        def slow(ctx, size):
            time.sleep(0.035)
            return orig(ctx, size)
        panel.render = slow
        orig_inputs = panel.inputs
        panel.inputs = lambda ctx: (orig_inputs(ctx), ctx.frame)     # force a render every frame
        log("TEST HOOK: panel %s sleeps 35 ms per render (over the %g ms budget)" % (panel.key, PANEL_BUDGET_MS))

    # ------------------------------------------------------------------ io
    def _activity(self, text: str) -> None:
        try:
            with open(self.activity_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": epoch_to_iso(time.time()), "actor": "compositor", "text": text[:200]}) + "\n")
        except Exception as e:
            log("activity append failed: %r" % (e,))

    def _writer(self, open_fn, q: "queue.Queue", name: str) -> None:
        # open() of a FIFO blocks until ffmpeg opens the read end: that is why it lives in its own thread
        try:
            with open_fn() as f:
                while True:
                    b = q.get()
                    if b is None:
                        return
                    f.write(b)
        except (BrokenPipeError, OSError) as e:
            self.writer_error = "%s writer: %r" % (name, e)
            self.running = False
        except Exception as e:  # pragma: no cover
            self.writer_error = "%s writer: %r" % (name, e)
            self.running = False

    def _put(self, q: "queue.Queue", b) -> bool:
        """Bounded put that gives up when the writer died (so a closed pipe can never hang the loop)."""
        while self.running:
            try:
                q.put(b, timeout=0.5)
                return True
            except queue.Full:
                continue
        return False

    def _relay_writer(self) -> None:
        """RELAY_SOCK mode: one FRM0 message per frame (video + this frame's audio block) to stream/relay.py.
        Protocol: header struct('>4sI') kind+length; FRM0 payload = '>I' audio_len + rgb24 + s16le. See relay.py."""
        import socket
        import struct
        hdr = struct.Struct(">4sI")
        s = None
        try:
            deadline = time.time() + 30.0
            while self.running:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    s.connect(self.relay_sock)
                    break
                except OSError as e:
                    s.close(); s = None
                    if time.time() > deadline:
                        raise RuntimeError("relay socket %s not accepting connections: %r" % (self.relay_sock, e))
                    time.sleep(0.25)
            if s is None:
                return
            for opt in (socket.SO_SNDBUF, socket.SO_RCVBUF):
                try:
                    s.setsockopt(socket.SOL_SOCKET, opt, 2 * 1024 * 1024)
                except OSError:
                    pass
            hello = json.dumps({"w": L.W, "h": L.H, "fps": self.fps, "block": self.block, "pid": os.getpid()}).encode("utf-8")
            s.sendall(hdr.pack(b"HELO", len(hello)) + hello)
            log("relay: connected to %s" % self.relay_sock)
            while True:
                v = self.vq.get()
                if v is None:
                    while True:                     # drain the audio side too, or shutdown waits 2 s on a full aq
                        try:
                            self.aq.get_nowait()
                        except queue.Empty:
                            break
                    return
                a = b""
                if self.audio_fifo:
                    a = self.aq.get()
                    if a is None:
                        return
                s.sendall(hdr.pack(b"FRM0", 4 + len(v) + len(a)) + struct.pack(">I", len(a)))
                s.sendall(v)
                if a:
                    s.sendall(a)
        except Exception as e:
            self.writer_error = "relay writer: %r" % (e,)
            self.running = False
        finally:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass

    def _start_writers(self) -> None:
        if self.relay_sock:
            threading.Thread(target=self._relay_writer, daemon=True).start()
            return
        threading.Thread(target=self._writer, args=(lambda: os.fdopen(os.dup(1), "wb", buffering=0), self.vq, "video"), daemon=True).start()
        if self.audio_fifo:
            threading.Thread(target=self._writer, args=(lambda: open(self.audio_fifo, "wb", buffering=0), self.aq, "audio"), daemon=True).start()

    # ------------------------------------------------------------------ scene
    def _scene(self, ctx) -> str:
        rnd = ctx.round or {}
        if rnd.get("phase") == "ship":
            return "SHIP"
        ag = ctx.agent or {}
        hb = iso_to_epoch(ag.get("heartbeat_ts"))
        fresh = hb is not None and ctx.now - hb < 120
        if (ctx.macro or {}).get("active") and fresh:
            return "BUILDING"
        last_chat = self.bridge.messages[-1].get("t") if self.bridge.messages else None
        if not fresh and (last_chat is None or ctx.now - last_chat > 300) and not ag.get("on_duty"):
            return "ATTRACT"
        return "STATUS"

    # ------------------------------------------------------------------ frame
    def _ctx(self, now: float, frame: int, audio_block=None):
        extras = dict(
            tallies=self.bridge.tallies(now), vote_count=self.bridge.vote_count(), recent_votes=self.bridge.recent_votes(5, now),
            chat=self.bridge.visible(now, 10), chat_held=self.bridge.held_rows(now), notice=self.bridge.notice(now), help_until=self.bridge.help_until,
            stats_until=self.bridge.stats_until, chat_display=self.bridge.display, mod_paused=self.bridge.paused,
            help_by=getattr(self.bridge, "help_by", None), stats_by=getattr(self.bridge, "stats_by", None),
            builders=self.bridge.builders, new_builders=self.bridge.new_builders, audio_block=audio_block,
            audio_level=(self.audio.level_dbfs if self.audio else None), audio_source=self.audio_source,
            compositor_live=self.counters, scene=self.counters.get("scene"),
        )
        ctx = self.store.ctx(now, frame, self.fps, **extras)
        if self.bridge.founders:
            ctx.founders = list(self.bridge.founders)
        return ctx

    def render_frame(self, now: float, frame: int) -> Image.Image:
        self.store.refresh(now)
        new_msgs = self.store.drain_chat()
        ctx0 = self._ctx(now, frame)
        classified = self.bridge.ingest(new_msgs, now, ctx0) if new_msgs else []
        if self._boot_chat:
            classified = self._boot_chat + classified
            self._boot_chat = []
        try:
            self.engine.tick(now, ctx0, classified)
        except Exception:
            log("round engine tick failed:\n" + traceback.format_exc())
        self.bridge.flush(now)
        blk = None
        if self.audio is not None:
            blk = self.audio.block(frame, self._ctx(now, frame))
        ctx = self._ctx(now, frame, blk)
        self.counters["scene"] = self._scene(ctx)
        ctx.scene = self.counters["scene"]

        for slot in self.slots:
            self._render_slot(slot, ctx, frame)
        # state.json compositor.scene = what the stage chip actually shows (QA: a forced ATTRACT run wrote "STATUS")
        st = sys.modules.get("stream.panels.stage")
        if st is not None and hasattr(st, "current_scene"):
            try:
                self.counters["scene"] = str(st.current_scene())
            except Exception:
                pass
        votes = [m for m in classified if m.get("kind") == "vote" and m.get("accepted") and not m.get("history")]
        if votes:
            self._log_vote_ack(votes, frame)
        return self.canvas

    @staticmethod
    def _world_booted() -> bool:
        """True once the land scene has booted (before that the frame is the scene's flat meadow beat, identical by
        design while the terrain thread runs: the watchdog and the tile gate start counting from the first real frame)."""
        wm = sys.modules.get("stream.panels.world")
        try:
            sc = wm.scene() if (wm is not None and hasattr(wm, "scene")) else None
            return bool(sc is not None and getattr(sc, "booted", False))
        except Exception:
            return True

    def _world_static(self, b: bytes) -> None:
        """Track identical WORLD-region frames (rows 0-720 of the rgb24 buffer: the whole frame is the land now)."""
        if not self._world_booted():
            self.boot_frames += 1
            self.last_world = None
            return
        wb = b[L.W * 3 * WORLD_BAND[0]:L.W * 3 * WORLD_BAND[1]]
        self.same_world = self.same_world + 1 if wb == self.last_world else 0
        self.last_world = wb
        if self.same_world > self.longest_static_world:
            self.longest_static_world = self.same_world

    @staticmethod
    def banned_copy_hits(strings: List[str]) -> List[str]:
        """The owner's rule as a function: every drawn string of ours that carries a banned token (case-insensitive, whole
        token, @names stripped first), a version tag, `day N` or a wall clock outside the timer forms."""
        hits: List[str] = []
        for t in strings:
            raw = str(t or "")
            low = re.sub(r"@[^\s·]+", "", raw).lower()
            if BANNED_COPY_RE.search(low) or BANNED_VERSION_RE.search(low) or BANNED_DAY_RE.search(low):
                hits.append(raw)
            elif BANNED_CLOCK_RE.search(low) and not CLOCK_OK_RE.search(raw):
                hits.append(raw)
        return hits

    def _hud_checks(self) -> None:
        """Per-frame self-test assertions for the full-bleed land (journal 034): the MOOT BOARD lights the letter with the
        unique max standing count (None on a tie / zero) and draws the round's option titles WHOLE (== the panel's own
        board_title(): HN-safe glyphs, cut only past BOARD_TITLE_MAX_W, which no menu title reaches), for every frame it
        is drawn; and no string the world panel wrote itself carries a banned token (the copy check)."""
        wm = sys.modules.get("stream.panels.world")
        pnl = getattr(wm, "PANEL", None) if wm is not None else None
        if pnl is None or not self._world_booted():
            return
        if getattr(pnl, "last_board_drawn", False):
            self.board_checked += 1
            ns = dict(getattr(pnl, "last_stone_n", {}) or {})
            try:
                sc = wm.scene()
                pc = sc.platform_counts() if sc is not None else {}
                ns = {k: len(v or []) for k, v in pc.items()} or ns      # an independent read of who stands
            except Exception:
                pass
            best = max(ns.values()) if ns else 0
            leaders = [k for k, n in ns.items() if n == best and n > 0]
            want_lit = leaders[0] if len(leaders) == 1 else None
            rnd = self.store.state.get("round") or {}
            phase = rnd.get("phase") or "open"
            lit = getattr(pnl, "last_board_lit", None)
            if phase == "ship":
                res = rnd.get("last_result") or {}
                want_lit = str(res.get("letter") or "").upper() or None
                if res.get("ok") is False:
                    want_lit = None
            want_titles = {}
            bt = getattr(wm, "board_title", None)
            for o in rnd.get("options") or []:
                if isinstance(o, dict) and o.get("letter") and o.get("title"):
                    raw = L.strip_non_bmp(str(o["title"])).strip()
                    want_titles[str(o["letter"]).upper()] = bt(raw) if callable(bt) else L.truncate("HN Medium", 22, raw, 560)
            got_titles = dict(getattr(pnl, "last_board_titles", {}) or {})
            ok_titles = all(got_titles.get(k, "") == v for k, v in want_titles.items()) if want_titles else True
            if ok_titles and any("\u2192" in v or "\u2190" in v for v in got_titles.values()):
                ok_titles = False                                   # an arrow reached an HN face: it renders as .notdef
            if ok_titles and any(v.endswith("…") and len(v) < len(want_titles.get(k, "")) for k, v in got_titles.items()
                                 if L.text_width("HN Medium", 22, want_titles.get(k, "")) <= 560):
                ok_titles = False                                   # a title that fits was cut
            if lit != want_lit or not ok_titles:
                self.board_mismatch += 1
                if self.board_mismatch <= 3:
                    log("moot board check: lit %r want %r; titles %r want %r" % (lit, want_lit, got_titles, want_titles))
        copy = list(getattr(pnl, "last_copy", []) or [])
        self.copy_frames += 1
        hits = self.banned_copy_hits(copy)
        if hits:
            self.copy_hits += len(hits)
            if self.copy_hits <= 5:
                log("copy check: banned string(s) drawn: %r" % (hits[:3],))
        # the tile gate's per-frame facts (from panel stats, not pixels)
        try:
            sc = wm.scene()
            awake = int(sc.awake_count()) if sc is not None else 0
            cam = getattr(sc, "camera", None)
            mode = getattr(cam, "mode", None)
            stop = getattr(cam, "drift_stop", None) or {}
            at_moot = mode == "DRIFT" and (stop.get("kind") == "moot" or stop.get("id") == "moot") and getattr(cam, "_drift_arrived_t", None) is not None
            self.tile_stats["frames"] += 1
            if awake >= 1:
                self.tile_stats["awake_frames"] += 1
                if float(getattr(pnl, "last_tile_px", 0.0) or 0.0) >= TILE_MIN_PX:
                    self.tile_stats["awake_ok"] += 1
            else:
                self.tile_stats["zero_frames"] += 1
                if int(getattr(pnl, "last_marks_in_view", 0) or 0) + int(getattr(pnl, "last_sleepers_in_view", 0) or 0) > 0 or getattr(pnl, "last_sign_in_view", False):
                    self.tile_stats["zero_ok"] += 1
                if at_moot:
                    self.tile_stats["moot_frames"] += 1
                    if getattr(pnl, "last_stones_in_view", 0) == 3 and getattr(pnl, "last_beacon_in_view", False) and getattr(pnl, "last_sign_in_view", False):
                        self.tile_stats["moot_ok"] += 1
            if getattr(pnl, "last_sign_in_view", False):
                self.tile_stats["sign_frames"] += 1
            rnd = self.store.state.get("round") or {}
            if awake >= 1 and rnd.get("options") and (rnd.get("phase") or "open") != "ship" and getattr(pnl, "last_stones_in_view", 0) == 0:
                self.tile_stats["marker_due"] += 1
                if getattr(pnl, "last_marker", None):
                    self.tile_stats["marker_ok"] += 1
        except Exception:
            pass

    def _log_vote_ack(self, votes: List[Dict], frame: int) -> None:
        """Prove CONCEPT 2 'name on screen within one second': the world plank (stream/panels/world.py PANEL.last_plank;
        the legacy pinned strip when no world panel is loaded) on the SAME frame the vote was ingested must read
        `@name stands at X · <title> · closes in m:ss` (journal 034: `stands at` carries the standing rule in two words;
        the option title rides along). A first-time chatter inside their 3 s hold is nameless on the land, so their
        same-frame ack reads `someone new stands at X` (the by-name ack follows at show_t, journal 030); `stands at X` is
        what is asserted, plus the display name when it is already past the hold. Counted in self.vote_acks."""
        wm = sys.modules.get("stream.panels.world")
        pnl = getattr(wm, "PANEL", None) if wm is not None else None
        txt = getattr(pnl, "last_plank", None) if pnl is not None else None
        where = "world plank"
        if txt is None:
            slot = self.slot_for("chat_pinned")
            key = getattr(slot, "last_inputs", None) if slot is not None else None
            txt = key[0] if isinstance(key, tuple) and key else None
            where = "pinned strip"
        for m in votes:
            want = "@%s stands at %s" % (m.get("display_name"), m.get("letter"))
            held = "stands at %s" % m.get("letter")
            s = str(txt or "")
            ok = bool(txt) and (want in s or (held in s and ("someone new" in s or "@builder #" in s)))   # several votes in one frame share the plank
            self.vote_acks[1] += 1
            self.vote_acks[0] += 1 if ok else 0
            log("vote ack: frame %d %s -> %s reads %r (%s)" % (frame, want, where, txt, "same frame" if ok else "NOT shown"))

    def _paste(self, slot: Slot, img: Image.Image) -> None:
        tile = Image.new("RGB", slot.size, L.COLORS["panel"])
        if img.size != slot.size:
            fixed = Image.new("RGBA", slot.size, (0, 0, 0, 0))
            fixed.paste(img, (0, 0))
            img = fixed
        if img.mode == "RGBA":
            tile.paste(img, (0, 0), img)
        else:
            tile.paste(img.convert("RGB"), (0, 0))
        slot.img = tile
        self.canvas.paste(tile, (slot.box[0], slot.box[1]))

    def _fail(self, slot: Slot, frame: int, note: str, exc: bool) -> None:
        if not slot.error_logged:
            slot.error_logged = True
            tb = traceback.format_exc().strip().splitlines()[-1] if exc else note
            log("panel %s failed: %s (placeholder shown, retry in %d frames)" % (slot.key, tb, PANEL_RETRY_FRAMES))
            self._activity("%s panel restarting after an error (%s)" % (slot.key.replace("_", " "), tb.split(":", 1)[0][:40]))
        slot.retry_at = frame + PANEL_RETRY_FRAMES
        slot.last_inputs = object()
        self._paste(slot, placeholder(slot.size, slot.key, note))

    def _rollback(self, slot: Slot, ctx, frame: int, why: str) -> None:
        """A hot-reloaded panel raised during probation: restore the previous panel and module objects."""
        old_panel, mods = slot.prev[0], slot.prev[1]
        prev_scene = slot.prev[2] if len(slot.prev) > 2 else None
        slot.prev = None
        slot.probation = 0
        for name, mod in mods:
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
                HotReloader._rebind_parent(name, mod)
        if prev_scene is not None and slot.key == "world":
            try:                                        # the previous world panel renders the scene it was built with
                setattr(sys.modules["stream.panels"], "_WORLD_SCENE", prev_scene)
            except Exception:
                pass
        self.reloader.stats["rollbacks"] += 1
        if old_panel is None:                       # the reload had ADDED this panel: drop it again
            PANEL_REGISTRY.pop(slot.key, None)
            self.slots = [s for s in self.slots if s is not slot]
            msg = "hot reload ROLLBACK %s: %s; new panel removed, previous modules restored" % (slot.key, why)
            log(msg)
            self._activity(msg)
            return
        PANEL_REGISTRY[slot.key] = old_panel
        slot.panel = old_panel
        slot.rebox()
        slot.reset()
        msg = "hot reload ROLLBACK %s: %s; previous panel + module restored" % (slot.key, why)
        log(msg)
        self._activity(msg)
        self._render_slot(slot, ctx, frame)         # prev is None now: a second raise takes the placeholder path

    def _render_slot(self, slot: Slot, ctx, frame: int) -> None:
        if frame < slot.retry_at or frame < slot.disabled_until:
            return
        if slot.disabled_until >= 0 and frame == slot.disabled_until:
            slot.disabled_until = -1
            slot.strikes = 0
            log("panel %s re-enabled for a retry" % slot.key)
        try:
            key = slot.panel.inputs(ctx)
        except Exception:
            if slot.prev is not None and slot.probation > 0:
                self._rollback(slot, ctx, frame, "inputs() raised: " + traceback.format_exc().strip().splitlines()[-1][:120])
                return
            self._fail(slot, frame, "inputs() raised", True)
            return
        if slot.img is not None and key == slot.last_inputs:
            return
        t0 = time.perf_counter()
        try:
            img = slot.panel.render(ctx, slot.size)
            if not isinstance(img, Image.Image):
                raise TypeError("render() returned %r, not a PIL Image" % type(img))
        except Exception:
            if slot.prev is not None and slot.probation > 0:
                self._rollback(slot, ctx, frame, "render() raised: " + traceback.format_exc().strip().splitlines()[-1][:120])
                return
            self._fail(slot, frame, "render() raised", True)
            return
        dt = (time.perf_counter() - t0) * 1000.0
        slot.renders += 1
        slot.render_ms_total += dt
        slot.render_ms_max = max(slot.render_ms_max, dt)
        slot.last_inputs = key
        if slot.probation > 0:
            slot.probation -= 1
            if slot.probation == 0 and slot.prev is not None:
                slot.prev = None                    # committed: the new module is now the fallback
                log("hot reload: panel %s committed after %d clean renders" % (slot.key, HOT_RELOAD_PROBATION))
        if slot.error_logged:
            slot.error_logged = False
            log("panel %s recovered" % slot.key)
        self._paste(slot, img)
        budget = getattr(slot.panel, "budget_ms", PANEL_BUDGET_MS) or PANEL_BUDGET_MS
        if dt > budget:
            slot.strikes += 1
            if slot.strikes >= PANEL_STRIKES:
                slot.disabled_until = frame + PANEL_RETRY_FRAMES
                msg = "panel %s disabled: %d consecutive renders over %.0f ms (last %.1f ms); placeholder for %d frames" % (
                    slot.key, slot.strikes, budget, dt, PANEL_RETRY_FRAMES)
                log(msg)
                self._activity(msg)
                self.counters["panels_disabled"] = sorted(set(self.counters.get("panels_disabled", []) + [slot.key]))
                self._paste(slot, placeholder(slot.size, slot.key, "over budget, disabled"))
        else:
            slot.strikes = 0

    # ------------------------------------------------------------------ stats
    def _update_counters(self, t_start: float, now_pc: float) -> None:
        ms = self.frame_ms[-300:]
        if ms:
            srt = sorted(ms)
            self.counters["frame_ms_avg"] = round(sum(ms) / len(ms), 1)
            self.counters["frame_ms_p95"] = round(srt[min(len(srt) - 1, int(len(srt) * 0.95))], 1)
        el = max(1e-6, now_pc - t_start)
        self.counters["fps_actual"] = round(self.frames / el, 1) if self.frames else 0.0
        self.counters["dropped_frames"] = self.dropped
        self.counters["uptime_s"] = int(el)

    def _report(self, tag: str) -> str:
        ms = self.frame_ms
        if not ms:
            return tag + ": no frames"
        srt = sorted(ms)
        p95 = srt[min(len(srt) - 1, int(len(srt) * 0.95))]
        over = sum(1 for m in ms if m > 1000.0 / self.fps)
        heavy = sorted(self.slots, key=lambda s: -s.render_ms_max)[:4]
        return "%s: %d frames, render ms avg %.1f p95 %.1f max %.1f, %d over %.1f ms budget, %d dup/dropped, panels(max ms): %s" % (
            tag, len(ms), sum(ms) / len(ms), p95, max(ms), over, 1000.0 / self.fps, self.dropped,
            ", ".join("%s %.1f/%d" % (s.key, s.render_ms_max, s.renders) for s in heavy))

    # ------------------------------------------------------------------ loops
    def _prime(self, now: float) -> None:
        self.store.ensure_state_file(now)
        self.store.refresh(now, force=True)
        # boot: everything already in chat.jsonl is history -> ingest without triggering blips
        hist = self.store.drain_chat()
        if hist:
            classified = self.bridge.ingest(hist, now, self._ctx(now, 0))
            # Records younger than the bridge's HISTORY window (60 s) are treated as live by the bridge (blips,
            # theme/idea accepted) but the previous compositor may not have processed them: a relay deploy restarts
            # this process in ~0.5 s. Hand them to the RoundEngine on the first tick so no !idea / !theme is lost
            # across a deploy (ideas de-duplicate on text; an older record is boot history and is NOT re-applied).
            cur_preset = (self.store.state.get("theme") or {}).get("preset")
            self._boot_chat = [m for m in classified if not m.get("history") and m.get("kind") in ("idea", "theme")
                               and not (m.get("kind") == "theme" and m.get("arg") == cur_preset)]   # already applied
            log("ingested %d historical chat messages (%d recent commands handed to the round engine)" % (
                len(hist), len(self._boot_chat)))
        self._activity("compositor start fps=%g audio=%s run_dir=%s" % (self.fps, self.audio_source, self.run_dir))

    def run_selftest(self, n: int) -> int:
        out_dir = os.path.join(self.run_dir, "selftest")
        os.makedirs(out_dir, exist_ok=True)
        t_wall = time.time()
        self._prime(t_wall)
        # Warm-up (same as run_stream): fonts + every panel's first strip cost 120-170 ms on frame 0 and were the only
        # over-budget frame of every run. Rendered untimed here so the 120 timed frames measure steady state.
        t0 = time.perf_counter()
        try:
            self.render_frame(t_wall - self.frame_dt, 0)
        except Exception:
            log("warm-up render failed (ignored):\n" + traceback.format_exc())
        log("self-test warm-up render: %.1f ms (fonts + panel caches primed before frame 0)" % ((time.perf_counter() - t0) * 1000.0))
        try:
            import numpy as _np
        except Exception:
            _np = None
        tile_frames: List[Tuple[int, Image.Image]] = []
        lum_sum, lum_frac_sum, lum_n = 0.0, 0.0, 0
        t_start = time.perf_counter()
        realtime = os.environ.get("KL_SELFTEST_REALTIME") == "1"
        if realtime:
            log("TEST HOOK: KL_SELFTEST_REALTIME=1 (self-test paced at %g fps)" % self.fps)
        for i in range(n):
            if realtime:
                lag = t_start + i * self.frame_dt - time.perf_counter()
                if lag > 0:
                    time.sleep(lag)
            self.reloader.poll(time.time(), i)     # wallclock: the watched files change in real time
            now = t_wall + i * self.frame_dt        # virtual clock: deterministic, one frame apart
            t0 = time.perf_counter()
            img = self.render_frame(now, i)
            ms = (time.perf_counter() - t0) * 1000.0
            self.frame_ms.append(ms)
            if ms > 1000.0 / self.fps:
                slow = sorted(self.slots, key=lambda s: -s.render_ms_max)[:3]
                log("self-test frame %d over budget: %.1f ms (scene %s, round %s; heaviest so far: %s)" % (
                    i, ms, self.counters.get("scene"), ((self.store.state.get("round") or {}).get("phase")),
                    ", ".join("%s %.1f" % (s.key, s.render_ms_max) for s in slow)))
            self.frames += 1
            b = img.tobytes()
            self.same_frames = self.same_frames + 1 if b == self.last_bytes else 0
            self.last_bytes = b
            self._world_static(b)
            self._hud_checks()
            if _np is not None and (i % 30 == 29 or i == n - 1):
                # the tile gate's luminance facts on the whole frame (the night floor: >= 60 % of pixels above 0.12)
                small = img.resize((320, 180), Image.Resampling.BOX)
                a = _np.asarray(small, _np.float32) / 255.0
                lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
                lum_sum += float(lum.mean()); lum_frac_sum += float((lum > 0.12).mean()); lum_n += 1
            if i in (n // 4, n // 2, (3 * n) // 4, n - 1):
                tile_frames.append((i, img.copy()))
            img.save(os.path.join(out_dir, "frame_%04d.png" % i))
            if i % 30 == 0:
                self._update_counters(t_start, time.perf_counter())
        self._update_counters(t_start, time.perf_counter())
        log(self._report("self-test"))
        log("static-frame watchdog: longest identical run %d frames (limit %d); WORLD region (rows %d-%d) longest static run %d frames after boot (%d boot frames skipped) -> %s" % (
            self.same_frames, STATIC_WATCHDOG_FRAMES, WORLD_BAND[0], WORLD_BAND[1], self.longest_static_world, self.boot_frames,
            "PASS" if self.longest_static_world < STATIC_WATCHDOG_FRAMES else "FAIL"))
        if self.longest_static_world >= STATIC_WATCHDOG_FRAMES:
            rc_static = 1
        else:
            rc_static = 0
        log("vote ack check: %d/%d live votes acknowledged on the world plank in the same frame" % (self.vote_acks[0], self.vote_acks[1]))
        # full-bleed land (journal 034): the MOOT BOARD agrees with who stands and the round's options in every frame it is
        # drawn; no banned copy is ever drawn; the tile gate's facts
        log("moot board check: %d/%d drawn frames lit the unique leader and carried the round's titles whole -> %s" % (
            self.board_checked - self.board_mismatch, self.board_checked, "PASS" if not self.board_mismatch else "FAIL"))
        log("copy check: %d blocked strings drawn in %d frames -> %s" % (self.copy_hits, self.copy_frames, "PASS" if not self.copy_hits else "FAIL"))
        ts = self.tile_stats
        tile_ok = True
        if ts["awake_frames"]:
            ok_a = ts["awake_ok"] == ts["awake_frames"]
            tile_ok = tile_ok and ok_a
            log("tile gate: awake >= 1 in %d frames, a creature + name chip >= %.0f px at 284 wide in %d -> %s" % (
                ts["awake_frames"], TILE_MIN_PX, ts["awake_ok"], "PASS" if ok_a else "FAIL"))
        if ts["zero_frames"]:
            ok_z = ts["zero_ok"] == ts["zero_frames"]
            tile_ok = tile_ok and ok_z
            log("tile gate: 0 awake in %d frames, a real mark / sleeper / the sign in view in %d -> %s" % (ts["zero_frames"], ts["zero_ok"], "PASS" if ok_z else "FAIL"))
        if ts["moot_frames"]:
            ok_m = ts["moot_ok"] == ts["moot_frames"]
            tile_ok = tile_ok and ok_m
            log("tile gate: DRIFT Moot dwell in %d frames, stones + beacon + sign all in view in %d -> %s" % (ts["moot_frames"], ts["moot_ok"], "PASS" if ok_m else "FAIL"))
        if ts["marker_due"]:
            ok_k = ts["marker_ok"] == ts["marker_due"]
            tile_ok = tile_ok and ok_k
            log("moot marker check: round open, awake >= 1, no stone in view in %d frames; marker drawn in %d -> %s" % (ts["marker_due"], ts["marker_ok"], "PASS" if ok_k else "FAIL"))
        log("tile gate: sign in view in %d/%d frames; frame mean luminance %.3f, frac > 0.12 = %.2f over %d samples" % (
            ts["sign_frames"], ts["frames"], (lum_sum / lum_n) if lum_n else -1.0, (lum_frac_sum / lum_n) if lum_n else -1.0, lum_n))
        if lum_n and (lum_frac_sum / lum_n) < 0.60:
            tile_ok = False
            log("tile gate: frac > 0.12 luminance %.2f < 0.60 -> FAIL" % (lum_frac_sum / lum_n))
        try:
            self._write_tiles(out_dir, tile_frames)
        except Exception:
            log("tiles.png failed:\n" + traceback.format_exc())
        p95 = sorted(self.frame_ms)[min(len(self.frame_ms) - 1, int(len(self.frame_ms) * 0.95))] if self.frame_ms else 0.0
        log("frame budget: p95 %.1f ms (gate < 25 ms at 6 awake) -> %s" % (p95, "PASS" if p95 < 25.0 else "FAIL"))
        rc = rc_static
        if self.board_mismatch or self.copy_hits or not tile_ok:
            rc = 1
        # WORLD.md 11: the honesty assertions run every frame inside the world panel (HonestyMonitor); the self-test
        # fails when any frame had a violation (a planted fake pip must turn this red).
        wm = sys.modules.get("stream.panels.world")
        if wm is not None and hasattr(wm, "honesty_summary"):
            try:
                hs = wm.honesty_summary()
                st = wm.PANEL.stats() if hasattr(wm, "PANEL") else {}
                sc_st = wm.scene().stats() if hasattr(wm, "scene") else {}
                if hs is not None:
                    bad = int(hs.get("violations") or 0) + int(sc_st.get("honesty_violations") or 0) + int(st.get("honesty_violations") or 0)
                    last = (hs.get("last") or {}).get("counts") or {}
                    log("honesty check: %s (%d frames checked, %d violation(s) %s, scene removed %d, panel unknown-name draws %d; "
                        "entities %s awake %s asleep %s hatched %s recent chatters %s test pips %s)" % (
                            "PASS" if bad == 0 else "FAIL", int(hs.get("frames") or 0), int(hs.get("violations") or 0),
                            json.dumps(hs.get("by_rule") or {}), int(sc_st.get("honesty_violations") or 0), int(st.get("honesty_violations") or 0),
                            last.get("entities"), last.get("awake"), last.get("asleep"), last.get("hatched_ever"),
                            last.get("recent_chatters"), last.get("test_pips")))
                    if bad:
                        rc = 1
                log("world panel: avg %s ms max %s ms, scene avg %s ms, degrade %s, keepers %s" % (
                    st.get("avg_ms"), st.get("max_ms"), sc_st.get("avg_ms"), json.dumps(st.get("degrade")), json.dumps(st.get("keepers"))))
            except Exception:
                log("honesty summary failed:\n" + traceback.format_exc())
        try:                                            # ART.md 7.2: the SETTLER sheet rides along with every self-test (what is on the land)
            sheet = self._settlers_sheet(out_dir)
            if sheet:
                log("wrote the settler review sheet (real pips on this land + sample names, all frames at 1x / 2x, four tiers) to %s" % sheet)
        except Exception:
            log("settlers_sheet.png failed:\n" + traceback.format_exc())
        log("wrote %d PNGs to %s" % (n, out_dir))
        self._world_shutdown()
        self.bridge.flush(time.time(), force=True)
        return rc

    @staticmethod
    def _write_tiles(out_dir: str, frames: List[Tuple[int, Image.Image]]) -> Optional[str]:
        """tiles.png: the sampled frames at 320x180 and 284x160 (LANCZOS), the frame as Kick's directory serves it."""
        if not frames:
            return None
        cols = len(frames)
        sheet = Image.new("RGB", (cols * 330, 180 + 160 + 30), (12, 14, 20))
        d = ImageDraw.Draw(sheet)
        for i, (fi, im) in enumerate(frames):
            for j, (tw, th) in enumerate(TILE_SIZES):
                t = im.convert("RGB").resize((tw, th), Image.Resampling.LANCZOS)
                sheet.paste(t, (i * 330 + 5, 5 + j * 190))
            d.text((i * 330 + 5, 360), "frame %d · 320x180 / 284x160" % fi, fill=(220, 220, 220))
        path = os.path.join(out_dir, "tiles.png")
        sheet.save(path)
        return path

    @staticmethod
    def _world_shutdown() -> None:
        """A forced world.json flush on exit (12: camps are promises; the 5 s throttle must not lose the last camp)."""
        wm = sys.modules.get("stream.panels.world")
        try:
            sc = wm.scene() if (wm is not None and hasattr(wm, "scene")) else None
            if sc is not None and hasattr(sc, "save_now"):
                sc.save_now(time.time())
        except Exception:
            log("world shutdown save failed:\n" + traceback.format_exc())

    @staticmethod
    def _settlers_sheet(out_dir: str) -> Optional[str]:
        """settlers_sheet.png: the canonical settlers (stream/world/art/creatures) for the real pips of this run first,
        padded with sample names to eight rows; the cave's pip sheet (stream.world.pips) is the rollback art, not the land's."""
        wm = sys.modules.get("stream.panels.world")
        sc = wm.scene() if (wm is not None and hasattr(wm, "scene")) else None
        if sc is None or getattr(sc, "camera", None) is None:            # the cave: the old sheet still applies
            from stream.world import pips as _P
            return _P.sheet(os.path.join(out_dir, "pips_sheet.png"), None, None)
        from stream.world.art import creatures as _C
        names: List[str] = []
        try:
            pips = (sc.world.data.get("pips") or {}) if getattr(sc, "world", None) is not None else {}
            names = [k for k, p in pips.items() if not p.get("_test")][:8]
        except Exception:
            names = []
        for extra in ("quietnoodle", "kai_dnb", "fern_ok", "moss_m", "willow_9", "sami", "atleastonce", "rivergrass"):
            if len(names) >= 8:
                break
            if extra not in names:
                names.append(extra)
        img = _C.sheet_image(names)
        path = os.path.join(out_dir, "settlers_sheet.png")
        img.save(path)
        return path

    def run_stream(self, max_frames: int = 0) -> int:
        self._start_writers()
        t_wall0 = time.time()
        self._prime(t_wall0)
        # Warm-up: frame 0 costs ~170 ms (font loading, first text strips). Rendered before the clock starts so a
        # (re)start does not begin 5 frames behind and log 3 catch-up dups as "dropped" on the readout.
        try:
            self.render_frame(t_wall0, 0)
        except Exception:
            log("warm-up render failed (ignored):\n" + traceback.format_exc())
        self.frame_ms = []
        t_start = time.perf_counter()
        i = 0
        last_log = t_start
        static_logged = False

        def emit(frame_bytes: bytes, idx: int, ctx=None):
            """Duplicate frame: same pixels, but a FRESH audio block so the pad keeps its phase (no click)."""
            self._put(self.vq, frame_bytes)
            if self.audio_fifo:
                blk = self.audio.block(idx, ctx) if self.audio is not None else None
                if blk is None:
                    import numpy as np
                    blk = np.zeros((self.block, 2), np.int16)
                self._put(self.aq, blk.tobytes())

        while self.running:
            target = t_start + i * self.frame_dt
            now_pc = time.perf_counter()
            if now_pc < target:
                time.sleep(target - now_pc)
            now = time.time()
            self.reloader.poll(now, i)
            t0 = time.perf_counter()
            img = self.render_frame(now, i)
            b = img.tobytes()
            self.frame_ms.append((time.perf_counter() - t0) * 1000.0)
            if len(self.frame_ms) > 3000:
                del self.frame_ms[:-3000]
            self.frames += 1
            self.same_frames = self.same_frames + 1 if b == self.last_bytes else 0
            self._world_static(b)
            if self.same_world >= STATIC_WATCHDOG_FRAMES and not static_logged:
                static_logged = True
                self._activity("watchdog: the cave has not moved for %d frames (world rows %d-%d)" % (self.same_world, WORLD_BAND[0], WORLD_BAND[1]))
            elif self.same_world < STATIC_WATCHDOG_FRAMES:
                static_logged = False
            self.last_bytes = b
            # the audio block for THIS frame was already rendered inside render_frame (scope shows it)
            self._put(self.vq, b)
            if self.audio_fifo:
                blk = self.audio.last_block if self.audio is not None else None
                if blk is None:
                    import numpy as np
                    blk = np.zeros((self.block, 2), np.int16)
                self._put(self.aq, blk.tobytes())
            i += 1
            # catch-up: duplicate the last frame (fresh audio block) rather than drift
            behind = (time.perf_counter() - t_start) / self.frame_dt - i
            dups = 0
            while behind >= 1.0 and dups < 3 and self.running:
                emit(b, i, None)
                i += 1; dups += 1; behind -= 1.0; self.dropped += 1
            if now_pc - last_log >= 10.0:
                last_log = now_pc
                self._update_counters(t_start, now_pc)
                log(self._report("running"))
            elif i % 30 == 0:
                self._update_counters(t_start, time.perf_counter())
            if max_frames and i >= max_frames:
                break
        for q in (self.vq, self.aq):
            try:
                q.put(None, timeout=0.5)
            except queue.Full:
                pass
        deadline = time.time() + 2.0
        while (not self.vq.empty() or not self.aq.empty()) and time.time() < deadline:
            time.sleep(0.02)
        self._world_shutdown()
        self.bridge.flush(time.time(), force=True)
        log(self._report("exit"))
        if self.writer_error:
            log("stopped: %s" % self.writer_error)
        self._activity("compositor stop after %d frames (%s)" % (self.frames, self.writer_error or "clean"))
        return 0


SENSITIVE_ENV = ['STREAM_KEY', 'SRT_PASSPHRASE', 'KICK_CLIENT_SECRET', 'KICK_TOKEN', 'NGROK_AUTHTOKEN', 'KICK_CLIENT_ID']


def _scrub_secrets() -> None:
    """Second layer after run.sh: this process never needs a stream key, token or client secret."""
    for k in SENSITIVE_ENV:
        os.environ.pop(k, None)


def main(argv=None) -> int:
    _scrub_secrets()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", type=int, default=0, metavar="N", help="render N PNG frames to $RUN_DIR/selftest and exit")
    ap.add_argument("--audio-fifo", default=None, help="s16le FIFO path (default from AUDIO_SOURCE=pipe:PATH)")
    ap.add_argument("--no-audio", action="store_true", help="do not run the AudioEngine at all")
    ap.add_argument("--run-dir", default=None, help="override $RUN_DIR")
    ap.add_argument("--fps", type=float, default=None, help="override $STREAM_FPS (30; 24 fallback)")
    ap.add_argument("--frames", type=int, default=0, help="stream mode: stop after N frames")
    a = ap.parse_args(argv)

    run_dir = a.run_dir or os.environ.get("RUN_DIR") or os.path.join(ROOT, "run")
    # Run-dir guard BEFORE anything touches the directory (Compositor() writes activity + default state).
    refusal = run_dir_guard(run_dir, a.run_dir is not None, test_mode_reasons(a.self_test, a.frames))
    if refusal:
        log(refusal)
        return 2
    fps = a.fps or float(os.environ.get("STREAM_FPS") or 30)
    fifo = a.audio_fifo
    if fifo is None and not a.self_test:
        src = os.environ.get("AUDIO_SOURCE") or ""
        if src.startswith("pipe:"):
            fifo = src[len("pipe:"):]
    if fifo and not os.path.exists(fifo):
        log("audio fifo %s does not exist; running without the audio FIFO" % fifo)
        fifo = None
    if a.self_test:
        fifo = None

    comp = Compositor(run_dir, fps, fifo, a.no_audio, selftest=a.self_test)

    def _stop(signum, _frame):
        log("signal %d, stopping" % signum)
        comp.running = False
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    # SIGPIPE stays ignored (Python's default): when ffmpeg closes the pipe the writer thread gets a
    # BrokenPipeError, sets running=False, and the loop exits through the normal report path.

    log("start run_dir=%s fps=%g block=%d audio=%s selftest=%d relay=%s" % (run_dir, fps, comp.block, comp.audio_source, a.self_test,
                                                                            comp.relay_sock or "no (stdout)"))
    if a.self_test:
        return comp.run_selftest(a.self_test)
    return comp.run_stream(a.frames)


if __name__ == "__main__":
    sys.exit(main())
