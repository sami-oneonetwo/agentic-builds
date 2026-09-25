"""stream/panels/stage.py - the stage (CONCEPT 3 regions 5-7, scenes from CONCEPT 4).

Three panels, one module:
  stage_title  (0,72,840,48)   task row + scene chip (chip = the body's EFFECTIVE scene, see current_scene())
  stage_step   (0,120,840,16)  PLAN > EDIT > TEST > SHIP > LIVE rail, active segment pulses at 1 Hz (sine, no strobe)
  stage_body   (0,136,840,236) mode-switching body:
     BUILDING  diff typewriter of a REAL `git diff` (working tree of a tracked file, else the last commit that
               touched it), new hunks typed at micro.typewriter_cps (40 default), '+' green '-' red, blinking cursor,
               header `live diff . <file>` / `replaying patch . <file>` when typing lags the edit by > 10 s
     STATUS    macro.status_lines (pass green / fail red / counts) or the round summary with the real idle timer
     CANVAS    another agent's file: stream/scenes/canvas.py (or stream/panels/canvas.py) exposing
               render(ctx, size) -> RGBA; imported if present, else STATUS
     SHIP      5 s RESULT card SHIPPED / BUILD FAILED with commit, one accent fade (35 % -> 0, <= 400 ms) on the
               stage body only, never full frame, never the header
     ATTRACT   hook sentence + `how to drive this stream` card, breathing accent bar (1 Hz)
     STATS     the !stats card (all real numbers), kept from the spine

Scene selection. The compositor owns ctx.scene (SHIP / ATTRACT / BUILDING / STATUS). Inside that, the body picks
its effective scene; anything may steer it with a HINT, in priority order:
  1. set_scene_hint(scene, until=None)   (module-level, in-process: RoundEngine / compositor / a macro module)
  2. ctx.scene_hint                       (a compositor extra, if the loop passes one)
  3. state.json  "stage": {"scene": "CANVAS", "until": "<iso>"}   (any process, via the RoundEngine-preserved block)
  4. micro.stage_default == "canvas"      (chat voted the canvas in)
Valid hints: BUILDING (alias DIFF), STATUS, CANVAS, ATTRACT. SHIP always wins (round.phase == ship). CANVAS without a
canvas module falls back to STATUS. current_scene() returns the effective scene of the last frame (the title chip
and the step rail read it); scene_hint(now) returns the active in-process hint.

Performance (journal 009, ported from the live hotfix): render() never re-types the whole panel. Full lines are
pasted from a strip cache, only the line under the cursor is drawn, and the reveal is quantised to cps/5-char steps
(8 chars at 40 cps: <= 5 typing renders/s, never more than 6/s with the 2 Hz cursor). The typewriter restarts
ONLY when the clock-stripped content changes: an embedded hh:mm:ss clock (CLOCK_RE) that ticks in a line updates
the text in place and never resets the reveal, so a clock line can never make the panel re-type forever. No cache
key contains a ticking clock except the 1 Hz cursor blink and the once-per-second idle caption.

Test hooks (env, never production): KL_STAGE_REPO=<git repo dir> points the diff watcher at another repository.
"""
from __future__ import annotations

import importlib
import math
import os
import re
import subprocess
import threading
import time
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from stream import layout as L
from stream.panels import Panel, register
from stream.state_store import iso_to_epoch

STEPS = ("PLAN", "EDIT", "TEST", "SHIP", "LIVE")
STEP_LABELS = ("planning the next change", "editing the stream", "running tests", "shipping the winner", "live, round open")
BODY_SCENES = ("BUILDING", "STATUS", "CANVAS", "SHIP", "ATTRACT", "STATS")

DIFF_POLL_S = 2.0        # CONCEPT 4: git diff polled every 2 s
DIFF_FRESH_S = 20.0      # diff changed within 20 s -> BUILDING; unchanged 20 s -> STATUS
DIFF_LAG_S = 10.0        # typing lags the real edit by > 10 s -> "replaying patch"
IDLE_CANVAS_S = 60.0     # STATUS idle > 60 s -> CANVAS (when a canvas module exists)
SHIP_FADE_S = 0.4        # <= 400 ms accent fade, stage body only
SHIP_FADE_STEPS = 12     # 12 quantised alpha steps over the fade (one per frame at 30 fps)
LINE_H = 26              # Menlo 22 line height inside the body
MAX_LINES = 8            # CONCEPT 3: 8 diff lines
MAX_DIFF_LINES = 400     # keep the watcher's buffer bounded
STRIP_CACHE_MAX = 400
CLOCK_RE = re.compile(r"\d{2}:\d{2}:\d{2}")   # hh:mm:ss anywhere in a line: stripped before content comparison
REVEAL_STEPS_PER_S = 5   # quantised reveal: chars per step = cps / 5 (>= 8) -> <= 5 typing renders per second
STEP_K_RE = re.compile(r"^\s*\d\s*/\s*5\s+")   # leading "k/5 " in an agent-written macro.step_label
ATTRACT_STEPS_PER_S = 6  # breathing bar in ATTRACT: 6 quantised steps/s (was 8) so no body scene exceeds 6 renders/s


def strip_clock(text: str) -> str:
    """Line with every hh:mm:ss clock removed (the typewriter's content key)."""
    return CLOCK_RE.sub("", text)


def reveal_quantum(cps: int) -> int:
    """Characters per reveal step for a typing speed: 8 at 40 cps, 40 at 200 cps (always <= 5 steps/s)."""
    return max(8, int(math.ceil(cps / float(REVEAL_STEPS_PER_S))))

# ----------------------------------------------------------------------------- scene hint API
_HINT_LOCK = threading.Lock()
_HINT: Dict[str, Optional[object]] = {"scene": None, "until": None}
_CURRENT: Dict[str, object] = {"scene": "STATUS", "step": 0, "label": STEP_LABELS[0]}


def set_scene_hint(scene: Optional[str], until: Optional[float] = None) -> None:
    """Steer the stage body. scene in BUILDING/DIFF/STATUS/CANVAS/ATTRACT or None to clear; until = epoch or None."""
    with _HINT_LOCK:
        _HINT["scene"] = scene.upper() if scene else None
        _HINT["until"] = float(until) if until is not None else None


def clear_scene_hint() -> None:
    set_scene_hint(None)


def scene_hint(now: float) -> Optional[str]:
    with _HINT_LOCK:
        s, until = _HINT["scene"], _HINT["until"]
    if not s:
        return None
    if until is not None and now >= until:
        return None
    return _normalise_hint(s)


def current_scene() -> str:
    """Effective body scene of the last frame (what the chip and the step rail show)."""
    return str(_CURRENT["scene"])


def _normalise_hint(s) -> Optional[str]:
    if not s:
        return None
    s = str(s).upper()
    if s == "DIFF":
        s = "BUILDING"
    return s if s in ("BUILDING", "STATUS", "CANVAS", "ATTRACT") else None


def _state_hint(ctx) -> Optional[str]:
    st = (ctx.state or {}).get("stage") if isinstance(ctx.state, dict) else None
    if not isinstance(st, dict):
        return None
    until = iso_to_epoch(st.get("until")) if st.get("until") else None
    if until is not None and ctx.now >= until:
        return None
    return _normalise_hint(st.get("scene"))


# ----------------------------------------------------------------------------- canvas import (another agent's file)
_CANVAS: Dict[str, object] = {"fn": None, "checked_t": None, "broken_until": -1.0}


def _canvas_renderer(now: float):
    """render(ctx, size) callable from stream/scenes/canvas.py or stream/panels/canvas.py, else None. Re-probes every 60 s."""
    if _CANVAS["fn"] is not None:
        return None if now < float(_CANVAS["broken_until"]) else _CANVAS["fn"]
    ct = _CANVAS["checked_t"]
    if ct is not None and now - float(ct) < 60.0:
        return None
    _CANVAS["checked_t"] = now
    for modname in ("stream.scenes.canvas", "stream.panels.canvas"):
        try:
            m = importlib.import_module(modname)
        except Exception:
            continue
        for attr in ("render_canvas", "render"):
            fn = getattr(m, attr, None)
            if callable(fn):
                _CANVAS["fn"] = fn
                return fn
        obj = getattr(m, "CANVAS", None) or getattr(m, "Canvas", None)
        if obj is not None:
            try:
                inst = obj() if isinstance(obj, type) else obj
            except Exception:
                continue
            if callable(getattr(inst, "render", None)):
                _CANVAS["fn"] = inst.render
                return inst.render
    return None


# ----------------------------------------------------------------------------- diff watcher (background, never in render)
def _kick_live_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _clean_diff(text: str) -> Tuple[str, ...]:
    out: List[str] = []
    for ln in text.splitlines():
        if ln.startswith(("diff --git", "index ", "--- ", "+++ ", "similarity index", "rename ", "new file mode", "deleted file mode")):
            continue
        ln = L.strip_non_bmp(ln.replace("\t", "    ").rstrip())
        out.append(ln)
        if len(out) >= MAX_DIFF_LINES:
            break
    return tuple(out)


class DiffWatcher(object):
    """Polls a REAL git diff every 2 s (wall clock) in a daemon thread and hands the panel an immutable snapshot.
    Target: macro.file when it has a working-tree diff, else the first tracked file with one, else the last commit
    that touched macro.file (or the last commit at all). GIT_OPTIONAL_LOCKS=0 so it never takes the index lock."""

    def __init__(self, repo: Optional[str] = None, poll_s: float = DIFF_POLL_S):
        self.repo = repo or os.environ.get("KL_STAGE_REPO") or _kick_live_root()
        self.poll_s = poll_s
        self.file_hint: Optional[str] = None
        self._lock = threading.Lock()
        self.lines: Tuple[str, ...] = ()
        self.label = "reading git diff"
        self.source = "none"
        self.changed_t: Optional[float] = None
        self.polls = 0
        self.error: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self._resolved = False

    # -- public
    def start(self) -> None:
        if self._thread is not None:
            return
        try:
            self._poll()                      # one synchronous poll (~100 ms, once) so frame 0 already types a real diff
        except Exception as e:
            self.error = repr(e)
        self._thread = threading.Thread(target=self._run, name="stage-diff-watcher", daemon=True)
        self._thread.start()

    def snapshot(self):
        with self._lock:
            return (self.lines, self.label, self.source, self.changed_t, self.polls, self.error)

    # -- internals
    def _run(self) -> None:
        while True:
            time.sleep(self.poll_s)
            try:
                self._poll()
            except Exception as e:
                with self._lock:
                    self.error = repr(e)

    def _git(self, *args) -> str:
        env = dict(os.environ)
        env["GIT_OPTIONAL_LOCKS"] = "0"
        env["GIT_PAGER"] = "cat"
        p = subprocess.run(["git", "-C", self.repo] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           stdin=subprocess.DEVNULL, timeout=2.0, check=False, env=env)
        if p.returncode != 0:
            raise RuntimeError("git %s rc=%d %s" % (args[0], p.returncode, p.stderr.decode("utf-8", "replace").strip()[:120]))
        return p.stdout.decode("utf-8", "replace")

    @staticmethod
    def _match(hint: Optional[str], names: List[str]) -> Optional[str]:
        if not hint:
            return None
        h = hint.strip().lstrip("./")
        for n in names:
            if n == h or n.endswith("/" + h):
                return n
        return None

    def _poll(self) -> None:
        if not self._resolved:
            # `git -C <subdir>` prints names relative to the toplevel; run from the toplevel so pathspecs match
            top = self._git("rev-parse", "--show-toplevel").strip()
            if top:
                self.repo = top
            self._resolved = True
        hint = self.file_hint
        names = [n for n in self._git("diff", "--name-only").splitlines() if n.strip()]
        target = self._match(hint, names) or (names[0] if names else None)
        if target:
            text = self._git("diff", "--", target)
            label, source = "live diff · %s" % os.path.basename(target), "worktree"
        else:
            path = [hint] if hint else []
            names2 = []
            try:
                names2 = [n for n in self._git("log", "-1", "--name-only", "--format=", "--", *path).splitlines() if n.strip()]
            except Exception:
                names2 = []
            if not names2 and path:       # hint never committed: fall back to the last commit at all
                path = []
                names2 = [n for n in self._git("log", "-1", "--name-only", "--format=", "--").splitlines() if n.strip()]
            target = self._match(hint, names2) or (names2[0] if names2 else None)
            if target:
                h = self._git("log", "-1", "--format=%h", "--", target).strip()
                text = self._git("log", "-1", "-p", "--format=", "--", target)
                label, source = "last commit %s · %s" % (h, os.path.basename(target)), "commit"
            else:
                text, label, source = "", "no git diff available", "none"
        lines = _clean_diff(text)
        with self._lock:
            self.polls += 1
            self.error = None
            if lines != self.lines or label != self.label:
                self.lines, self.label, self.source = lines, label, source
                self.changed_t = time.time()


# ----------------------------------------------------------------------------- shared helpers
def _leader(ctx):
    opts = (ctx.round or {}).get("options") or []
    tall = ctx.tallies or {}
    best, best_n = None, -1
    for o in opts:
        n = len(tall.get(o.get("letter"), [])) if tall else int(o.get("votes") or 0)
        if n > best_n:
            best, best_n = o, n
    return best, best_n


def _agent_fresh(ctx) -> bool:
    """True while an agent heartbeat is < 120 s old (the compositor's BUILDING condition, CONCEPT 4)."""
    hb = iso_to_epoch((ctx.agent or {}).get("heartbeat_ts"))
    return hb is not None and (ctx.now - hb) < 120


def _next_version(ctx):
    v = ctx.version or {}
    return "v%d.%d.%d" % (int(v.get("major") or 0), int(v.get("macro") or 0), int(v.get("micro") or 0) + 1)


def _prev_version(ctx):
    v = ctx.version or {}
    return "v%d.%d.%d" % (int(v.get("major") or 0), int(v.get("macro") or 0), max(0, int(v.get("micro") or 0) - 1))


def _mmss(s: float) -> str:
    s = max(0, int(s))
    return "%d:%02d" % (s // 60, s % 60)


def active_step(ctx) -> Tuple[int, str]:
    """(index 0-4, label) of the step rail. macro.step_index wins during an agent build; otherwise derived from the
    effective body scene and the round phase. Deterministic in ctx.now, no clocks in the label."""
    mac = ctx.macro or {}
    if mac.get("active") and mac.get("step_index") is not None:
        i = max(0, min(4, int(mac.get("step_index") or 0)))
        # CONCEPT 8.1 step_label already carries "k/5 " (e.g. "2/5 editing chat_pane.py"); the body header adds its
        # own "k/5 " prefix, so strip one here rather than show "2/5 2/5 editing ..."
        return i, STEP_K_RE.sub("", str(mac.get("step_label") or STEP_LABELS[i]), count=1) or STEP_LABELS[i]
    rnd = ctx.round or {}
    scene = current_scene()
    if rnd.get("phase") == "ship" or scene == "SHIP":
        return 3, STEP_LABELS[3]
    op = ctx.round_opened_t
    if op is not None and 0 <= ctx.now - op < 5:
        return 4, STEP_LABELS[4]
    if scene == "BUILDING":
        f = mac.get("file")
        return 1, ("editing %s" % os.path.basename(str(f))) if f else STEP_LABELS[1]
    if rnd.get("phase") == "closing" or str(mac.get("step") or "").upper() == "TEST" or (mac.get("status_lines") and scene == "STATUS"):
        return 2, STEP_LABELS[2]
    return 0, STEP_LABELS[0]


def _ship_failed(ctx, lr: Dict) -> Tuple[bool, List[str]]:
    """(failed, first 3 error lines) from round.last_result or the matching ships.jsonl line."""
    err = lr.get("error")
    failed = lr.get("ok") is False or bool(err)
    if not failed:
        for s in reversed(ctx.ships or []):
            if s.get("version") == lr.get("version"):
                if s.get("ok") is False:
                    failed, err = True, s.get("error")
                break
    lines: List[str] = []
    if failed:
        src = err if isinstance(err, str) else ""
        if not src and (ctx.macro or {}).get("status_lines"):
            src = "\n".join(str(x) for x in (ctx.macro or {}).get("status_lines")[-3:])
        lines = [L.strip_non_bmp(x.replace("\t", "  ").strip()) for x in (src or "no traceback captured").splitlines() if x.strip()][:3]
    return failed, lines


# ----------------------------------------------------------------------------- panels
class StageTitle(Panel):
    key, region = "stage_title", "stage_title"
    budget_ms = 28.0        # journal 009 budget (the Panel default of 20 would otherwise win over compositor.PANEL_BUDGET_MS)

    def _text(self, ctx):
        rnd = ctx.round or {}
        if rnd.get("phase") == "ship" and rnd.get("last_result"):
            lr = rnd["last_result"]
            failed, _ = _ship_failed(ctx, lr)
            who = "agent's pick" if lr.get("agent_pick") else "picked by @%s" % lr.get("picked_by")
            return "%s %s: %s, %s" % ("FAILED" if failed else "SHIPPED", lr.get("version"), lr.get("title"), who)
        mac = ctx.macro or {}
        if mac.get("active") and mac.get("title"):
            return "BUILDING %s: %s, requested by @%s" % (_next_version(ctx), mac.get("title"), mac.get("requested_by") or "chat")
        if current_scene() == "ATTRACT":
            # the chip says ATTRACT, so the title row agrees with it instead of claiming a build (QA 2026-09-25)
            rem = ctx.round_remaining
            return "WAITING FOR THE FIRST VOTE · ships in %s" % (("%02d:%02d" % (max(0, int(rem)) // 60, max(0, int(rem)) % 60)) if rem is not None else "--:--")   # header clock format; round N is in the header
        lead, n = _leader(ctx)
        if lead is None:
            return "BUILDING %s: waiting for the first round" % _next_version(ctx)
        # While the round is OPEN nothing is "picked" yet (the leader changed twice in the seeded chat), so the row
        # reports the live tally and reserves "picked by @name" for round.phase == ship, where it is already correct.
        if n <= 0:
            return "0 votes · agent picks %s unless you vote: %s" % (lead.get("letter") or "?", lead.get("title"))
        return "%s leads with %d vote%s: %s" % (lead.get("letter") or "?", n, "" if n == 1 else "s", lead.get("title"))

    def inputs(self, ctx):
        return (self._text(ctx), current_scene(), ctx.preset)

    def render(self, ctx, size):
        w, h = size
        img = self.base(size, L.COLORS["bg"])
        d = ImageDraw.Draw(img)
        accent = L.preset(ctx.preset)["accent"]
        chip = current_scene()
        cw = L.text_width("Menlo", 20, chip) + 20
        d.rounded_rectangle([w - L.PAD - cw, 12, w - L.PAD, 36], radius=4, fill=L.COLORS["panel"], outline=L.COLORS["hairline"])
        d.text((w - L.PAD - cw + 10, 13), chip, font=L.font("Menlo", 20), fill=accent)
        d.text((L.PAD, 8), L.truncate("HN Bold", 28, L.strip_non_bmp(self._text(ctx)), w - 2 * L.PAD - cw - 12),
               font=L.font("HN Bold", 28), fill=L.COLORS["text"])
        return img


class StageStep(Panel):
    """5-segment rail. 16 px tall, so the `k/5 label` lives in the stage body header line (20 px minimum text)."""
    key, region = "stage_step", "stage_step"
    budget_ms = 28.0

    def inputs(self, ctx):
        i, label = active_step(ctx)
        _CURRENT["step"], _CURRENT["label"] = i, label
        # 1 Hz sine pulse quantised to 12 steps/s -> at most 12 cheap redraws of an 840x16 strip per second
        return (i, int((ctx.now * 12) % 12), ctx.preset)

    def render(self, ctx, size):
        w, h = size
        img = Image.new("RGBA", size, L.COLORS["bg"])
        d = ImageDraw.Draw(img)
        accent = L.hex_rgb(L.preset(ctx.preset)["accent"])
        active = int(_CURRENT["step"])
        pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(2 * math.pi * ctx.now))
        seg_w = (w - 2 * L.PAD - 4 * 6) // 5
        for i in range(5):
            x0 = L.PAD + i * (seg_w + 6)
            if i == active:
                col = tuple(int(c * pulse) for c in accent)
            elif i < active:
                col = tuple(int(c * 0.45) for c in accent)
            else:
                col = L.COLORS["hairline"]
            d.rectangle([x0, 4, x0 + seg_w, h - 5], fill=col)
        return img


class StageBody(Panel):
    key, region = "stage_body", "stage_body"
    budget_ms = 28.0        # journal 009: 20 -> 28 (frame budget 33 ms); matches compositor.PANEL_BUDGET_MS

    def __init__(self, watcher: Optional[DiffWatcher] = None):
        self.watcher = watcher or DiffWatcher()
        self._boot_t: Optional[float] = None
        # typewriter state
        self._diff_lines: Tuple[str, ...] = ()
        self._diff_key: Tuple[str, ...] = ()   # clock-stripped content: the only thing that restarts the reveal
        self._disp: List[str] = []             # truncated display lines
        self._cum: List[int] = []              # cumulative char count after each line (+1 per line for the newline beat)
        self._gen = 0
        self._reveal_start: Optional[float] = None
        self._reveal_base = 0
        self._last_revealed = 0
        # caches
        self._strips: Dict[Tuple, Image.Image] = {}
        self._status_static: Optional[Tuple[Tuple, Image.Image]] = None
        self._attract_static: Optional[Tuple[Tuple, Image.Image]] = None
        self._ship_seen: Dict[str, float] = {}
        self._scene = "STATUS"

    # ---- scene -----------------------------------------------------------------
    def _canvas_ok(self, now: float) -> bool:
        return _canvas_renderer(now) is not None

    def _typed_out(self, ctx) -> bool:
        return self._cum == [] or self._last_revealed >= self._cum[-1]

    def _pick_scene(self, ctx) -> str:
        comp = str(ctx.scene or "STATUS").upper()
        if comp == "SHIP" or (ctx.round or {}).get("phase") == "ship":
            return "SHIP"
        if ctx.stats_until and ctx.now < ctx.stats_until:
            return "STATS"
        if comp == "ATTRACT":
            return "ATTRACT"
        hint = scene_hint(ctx.now) or _normalise_hint(ctx.scene_hint) or _state_hint(ctx)
        if hint == "CANVAS":
            return "CANVAS" if self._canvas_ok(ctx.now) else "STATUS"
        if hint:
            return hint
        if comp == "BUILDING":
            return "BUILDING"
        lines, _label, _src, changed_t, _polls, _err = self.watcher.snapshot()
        if lines and changed_t is not None and ctx.now - changed_t < DIFF_FRESH_S:
            return "BUILDING"
        if lines and not self._typed_out(ctx):
            return "BUILDING"                  # finish typing what the edit produced
        mac = ctx.macro or {}
        if mac.get("status_lines") or str(mac.get("step") or "").upper() == "TEST":
            return "STATUS"
        idle = ctx.now - (changed_t if changed_t is not None else (self._boot_t or ctx.now))
        if ((ctx.micro or {}).get("stage_default") == "canvas" or idle > IDLE_CANVAS_S) and self._canvas_ok(ctx.now):
            return "CANVAS"
        return "STATUS"

    # ---- typewriter bookkeeping ------------------------------------------------
    def _cols(self, w: int) -> int:
        return max(20, (w - 2 * L.PAD - 16) // max(1, L.text_width("Menlo", 22, "M")))

    def _display_lines(self, lines: Tuple[str, ...], w: int) -> List[str]:
        cols = self._cols(w)
        return [(ln[:cols - 1] + "…") if len(ln) > cols else ln for ln in lines]

    def _sync_diff(self, ctx, lines: Tuple[str, ...], w: int) -> None:
        if lines == self._diff_lines:
            return
        key = tuple(strip_clock(ln) for ln in lines)
        if key == self._diff_key:
            # Only an embedded hh:mm:ss clock ticked (journal 009): swap the text in place, keep the reveal
            # position, generation and cursor exactly where they are. A clock is fixed-width, so _cum is unchanged.
            self._disp = self._display_lines(lines, w)
            self._diff_lines = lines
            return
        old_key = self._diff_key
        appended = bool(old_key) and len(key) > len(old_key) and key[:len(old_key)] == old_key
        old_total = self._cum[-1] if self._cum else 0
        self._disp = self._display_lines(lines, w)
        cum, n = [], 0
        for ln in self._disp:
            n += len(ln) + 1
            cum.append(n)
        self._cum = cum
        self._diff_lines = lines
        self._diff_key = key
        self._gen += 1
        self._reveal_base = min(old_total, self._last_revealed) if appended else 0   # new hunks type, old ones stay
        self._reveal_start = ctx.now

    def _reveal(self, ctx) -> Tuple[int, int]:
        total = self._cum[-1] if self._cum else 0
        cps = int((ctx.micro or {}).get("typewriter_cps") or 40)
        cps = max(10, min(200, cps))
        if self._reveal_start is None:
            self._reveal_start = ctx.now
        revealed = min(total, self._reveal_base + int(max(0.0, ctx.now - self._reveal_start) * cps))
        self._last_revealed = revealed
        return revealed, total

    # ---- inputs ----------------------------------------------------------------
    def inputs(self, ctx):
        if self._boot_t is None:
            self._boot_t = ctx.now
            self.watcher.start()
        self.watcher.file_hint = (ctx.macro or {}).get("file") or None
        w, _h = L.region_size(self.region)
        scene = self._pick_scene(ctx)
        self._scene = scene
        _CURRENT["scene"] = scene
        p = ctx.preset
        if scene == "SHIP":
            lr = (ctx.round or {}).get("last_result") or {}
            age = self._ship_age(ctx, lr)
            step = SHIP_FADE_STEPS if age is None else min(SHIP_FADE_STEPS, int(age / SHIP_FADE_S * SHIP_FADE_STEPS))
            failed, err_lines = _ship_failed(ctx, lr)
            return ("SHIP", lr.get("version"), lr.get("title"), lr.get("picked_by"), lr.get("commit"), bool(lr.get("agent_pick")),
                    lr.get("votes"), failed, tuple(err_lines), step, p)
        if scene == "STATS":
            return ("STATS", int(ctx.now), p)
        if scene == "ATTRACT":
            return ("ATTRACT", int((ctx.now * ATTRACT_STEPS_PER_S) % ATTRACT_STEPS_PER_S), bool((ctx.ask or {}).get("enabled")), p)
        if scene == "CANVAS":
            return ("CANVAS", ctx.frame)
        if scene == "BUILDING":
            lines, label, _src, changed_t, _polls, _err = self.watcher.snapshot()
            self._sync_diff(ctx, lines, w)
            revealed, total = self._reveal(ctx)
            cps = max(10, min(200, int((ctx.micro or {}).get("typewriter_cps") or 40)))
            step = reveal_quantum(cps)
            q = revealed if revealed >= total else (revealed // step) * step  # 8-char steps at 40 cps: <= 5 renders/s
            blink = int((ctx.now * 2) % 2) if revealed >= total else 0       # 1 Hz cursor once typed out
            lag = (total - revealed) / float(cps) > DIFF_LAG_S
            return ("BUILDING", self._gen, q, blink, label, lag, _CURRENT["step"], _CURRENT["label"], p)
        st_lines = self._status_lines(ctx)
        _lines, _label, _src, changed_t, _polls, _err = self.watcher.snapshot()
        idle = int(ctx.now - (changed_t if changed_t is not None else (self._boot_t or ctx.now)))
        return ("STATUS", tuple(st_lines), idle, _CURRENT["step"], _CURRENT["label"], p)

    def _ship_age(self, ctx, lr: Dict) -> Optional[float]:
        key = "%s|%s" % (lr.get("version"), lr.get("ts"))
        if key not in self._ship_seen:
            if len(self._ship_seen) > 32:
                self._ship_seen.clear()
            self._ship_seen[key] = ctx.now
        t = iso_to_epoch(lr.get("ts")) if lr.get("ts") else None
        if t is not None and 0.0 <= ctx.now - t < 10.0:
            return ctx.now - t
        return ctx.now - self._ship_seen[key]

    # ---- content ---------------------------------------------------------------
    def _status_lines(self, ctx) -> List[Tuple[str, str]]:
        """[(text, colour_key)] without any ticking clock (so the cache key is stable)."""
        mac = ctx.macro or {}
        out: List[Tuple[str, str]] = []
        sl = [str(x) for x in (mac.get("status_lines") or [])]
        if sl:
            npass = sum(1 for x in sl if ("pass" in x.lower() or " ok" in x.lower() or x.lower().startswith("ok")) and "fail" not in x.lower())
            nfail = sum(1 for x in sl if "fail" in x.lower() or "error" in x.lower())
            if mac.get("title"):
                out.append(("%s %s" % (mac.get("step") or "build", mac.get("title")), "text"))
            for x in sl[-6:]:
                low = x.lower()
                col = "remove" if ("fail" in low or "error" in low) else ("add" if ("pass" in low or " ok" in low or low.startswith("ok")) else "text2")
                out.append((L.strip_non_bmp(x.replace("\t", "  ")), col))
            out.append(("%d pass · %d fail" % (npass, nfail), "add" if nfail == 0 else "remove"))
            return out
        lead, n = _leader(ctx)
        rnd = ctx.round or {}
        if lead is not None:
            out.append(("next ship: %s" % (lead.get("title") or "?"), "text"))
            tall = ctx.tallies or {}
            for o in rnd.get("options") or []:
                v = len(tall.get(o.get("letter"), [])) if tall else int(o.get("votes") or 0)
                out.append(("  %s  %-40s %d vote%s" % (o.get("letter"), (o.get("title") or "")[:40], v, "" if v == 1 else "s"), "text2"))
        else:
            out.append(("waiting for the first micro round", "text"))
        if not rnd.get("options"):
            out.append(("the compositor runs the rounds on its own; agents join when on duty", "text2"))
        return out

    # ---- drawing helpers -------------------------------------------------------
    def _strip(self, text: str, col: str, w: int) -> Image.Image:
        key = (text, col)
        img = self._strips.get(key)
        if img is None:
            if len(self._strips) >= STRIP_CACHE_MAX:
                self._strips.clear()
            img = Image.new("RGBA", (w, LINE_H), (0, 0, 0, 0))
            ImageDraw.Draw(img).text((0, 0), text, font=L.font("Menlo", 22), fill=col)
            self._strips[key] = img
        return img

    def _header(self, d: ImageDraw.ImageDraw, w: int, left: str, left_col, right: str) -> None:
        f = L.font("Menlo", 20)
        rw = L.text_width("Menlo", 20, right) if right else 0
        d.text((L.PAD, 3), L.truncate("Menlo", 20, left, w - 2 * L.PAD - rw - 24), font=f, fill=left_col)
        if right:
            d.text((w - L.PAD - rw, 3), right, font=f, fill=L.COLORS["text2"])

    @staticmethod
    def _diff_colour(ln: str, accent: str) -> str:
        if ln.startswith("+"):
            return L.COLORS["add"]
        if ln.startswith("-"):
            return L.COLORS["remove"]
        if ln.startswith("@@"):
            return accent
        return L.COLORS["text2"]

    def _card(self, size, title, title_col, lines, tint, mono=False):
        w, h = size
        img = self.base(size)
        d = ImageDraw.Draw(img)
        d.rectangle([L.PAD, L.PAD, w - L.PAD, h - L.PAD], fill=tint, outline=L.COLORS["hairline"])
        d.text((L.PAD * 2, L.PAD * 2), L.truncate("HN Bold", 34, title, w - 4 * L.PAD), font=L.font("HN Bold", 34), fill=title_col)
        y = L.PAD * 2 + 48
        fname, fsize, lh = ("Menlo", 22, 28) if mono else ("HN", 24, 32)
        for ln, col in lines:
            if y + fsize > h - L.PAD - 4:
                break
            d.text((L.PAD * 2, y), L.truncate(fname, fsize, ln, w - 4 * L.PAD), font=L.font(fname, fsize), fill=L.COLORS.get(col, col))
            y += lh
        return img

    # ---- render ----------------------------------------------------------------
    def render(self, ctx, size):
        scene = self._scene
        if scene == "SHIP":
            return self._render_ship(ctx, size)
        if scene == "STATS":
            return self._render_stats(ctx, size)
        if scene == "ATTRACT":
            return self._render_attract(ctx, size)
        if scene == "CANVAS":
            return self._render_canvas(ctx, size)
        if scene == "BUILDING":
            return self._render_building(ctx, size)
        return self._render_status(ctx, size)

    def _render_building(self, ctx, size):
        w, h = size
        accent = L.preset(ctx.preset)["accent"]
        img = self.base(size)
        d = ImageDraw.Draw(img)
        _lines, label, _src, _ct, _polls, _err = self.watcher.snapshot()
        revealed, total = self._reveal(ctx)
        cps = max(10, min(200, int((ctx.micro or {}).get("typewriter_cps") or 40)))
        lag = (total - revealed) / float(cps) > DIFF_LAG_S
        left = ("replaying patch · " + label.split("·", 1)[-1].strip()) if lag else label
        if not _agent_fresh(ctx) and not (ctx.macro or {}).get("active"):
            # nobody is editing right now: say what this really is instead of implying a live build (QA 2026-09-25)
            left = "last real patch · " + label.split("·", 1)[-1].strip() + " · no agent on duty"
            lag = False
        self._header(d, w, left, L.COLORS["warn"] if lag else L.COLORS["text2"],
                     "%d/5 %s" % (int(_CURRENT["step"]) + 1, str(_CURRENT["label"])))
        if not self._disp:
            d.text((L.PAD, 30), "no git diff to show yet", font=L.font("Menlo", 22), fill=L.COLORS["text2"])
            return img
        # which line is under the cursor
        k = 0
        while k < len(self._cum) and self._cum[k] <= revealed:
            k += 1
        done = revealed >= total
        cur_idx = min(k, len(self._disp) - 1)
        first = max(0, cur_idx + 1 - MAX_LINES)       # the window scrolls so the cursor line is always visible
        y = 28                                          # 28 + 8 x 26 = 236 = region height
        cx = cy = None
        for i in range(first, cur_idx + 1):
            ln = self._disp[i]
            col = self._diff_colour(ln, accent)
            if i < k:                                        # fully revealed line -> cached strip
                img.alpha_composite(self._strip(ln, col, w - 2 * L.PAD), (L.PAD, y))
                cx, cy = L.PAD + L.text_width("Menlo", 22, ln), y
            else:                                            # the line being typed
                before = self._cum[i - 1] if i > 0 else 0
                shown = ln[:max(0, revealed - before)]
                if shown:
                    d.text((L.PAD, y), shown, font=L.font("Menlo", 22), fill=col)
                cx, cy = L.PAD + L.text_width("Menlo", 22, shown), y
            y += LINE_H
        blink_on = (int((ctx.now * 2) % 2) == 0) if done else True
        if blink_on and cx is not None:
            d.rectangle([cx + 3, cy + 3, cx + 13, cy + LINE_H - 3], fill=accent)
        return img

    def _render_status(self, ctx, size):
        w, h = size
        lines = self._status_lines(ctx)
        key = (tuple(lines), ctx.preset, _CURRENT["step"], _CURRENT["label"])
        if self._status_static is None or self._status_static[0] != key:
            base = self.base(size)
            d = ImageDraw.Draw(base)
            self._header(d, w, "build status", L.COLORS["text2"], "%d/5 %s" % (int(_CURRENT["step"]) + 1, str(_CURRENT["label"])))
            y = 28
            for txt, col in lines[:MAX_LINES - 2]:      # 6 lines (y 28-184), the idle caption sits at y 206
                base.alpha_composite(self._strip(L.truncate("Menlo", 22, txt, w - 2 * L.PAD), L.COLORS.get(col, col), w - 2 * L.PAD), (L.PAD, y))
                y += LINE_H
            self._status_static = (key, base)
        img = self._status_static[1].copy()
        d = ImageDraw.Draw(img)
        _l, _lab, _src, changed_t, _polls, _err = self.watcher.snapshot()
        idle = ctx.now - (changed_t if changed_t is not None else (self._boot_t or ctx.now))
        cap = "agents are thinking… %s · type A, B or C to steer the next ship" % _mmss(idle)
        d.text((L.PAD, h - LINE_H - 4), L.truncate("Menlo", 22, cap, w - 2 * L.PAD), font=L.font("Menlo", 22), fill=L.COLORS["text2"])
        return img          # the idle clock ticks once a second; the step rail carries the per-frame motion

    def _render_ship(self, ctx, size):
        w, h = size
        accent = L.preset(ctx.preset)["accent"]
        lr = (ctx.round or {}).get("last_result") or {}
        failed, err_lines = _ship_failed(ctx, lr)
        age = self._ship_age(ctx, lr)
        step = SHIP_FADE_STEPS if age is None else min(SHIP_FADE_STEPS, int(age / SHIP_FADE_S * SHIP_FADE_STEPS))
        if failed:
            title = "BUILD FAILED · reverting to %s" % ((ctx.version or {}).get("string") or _prev_version(ctx))   # a failed ship never bumped the version
            body = [(x, "text") for x in err_lines] or [("no traceback captured", "text2")]
            card = self._card(size, title, L.COLORS["danger"], body, (40, 18, 22, 255), mono=True)
            tint = L.hex_rgb(L.COLORS["danger"])
        else:
            votes = lr.get("votes")
            if lr.get("agent_pick"):
                who = "nobody voted · agent picked %s · next one is yours" % (lr.get("letter") or "?")
            else:
                who = "picked by @%s with %s vote%s" % (lr.get("picked_by"), votes if votes is not None else "?", "" if votes == 1 else "s")
            title = "SHIPPED %s · %s" % (lr.get("version") or "", lr.get("title") or "")
            body = [(who, "text"), ("commit %s · next round opens in a moment" % (lr.get("commit") or "n/a"), "text2")]
            card = self._card(size, title, accent, body, (17, 21, 29, 255))
            tint = L.hex_rgb(accent)
        alpha = int(round(0.35 * 255 * (1.0 - step / float(SHIP_FADE_STEPS))))
        if alpha > 0:                                    # the ONE <= 400 ms fade, stage body only
            card.alpha_composite(Image.new("RGBA", size, tint + (alpha,)))
        return card

    def _render_stats(self, ctx, size):
        m, cs, cl, v = ctx.metrics or {}, ctx.chat_stats or {}, ctx.compositor_live or {}, ctx.version or {}
        vc = m.get("viewer_count") if m.get("poll_ok") else "--"
        lines = [("viewers now %s · peak %s" % (vc, m.get("viewer_peak") if m.get("viewer_peak") is not None else "--"), "text"),
                 ("chat %s/min · %s chatters (5 min)" % (cs.get("msgs_per_min_5m", "--"), cs.get("unique_chatters_5m", "--")), "text"),
                 ("ships %s · fails %s · uptime %ss" % (v.get("shipped", 0), v.get("failed", 0), cl.get("uptime_s", "--")), "text"),
                 ("%s fps · %s ms · dropped %s" % (cl.get("fps_actual", "--"), cl.get("frame_ms_avg", "--"), cl.get("dropped_frames", "--")), "text2")]
        return self._card(size, "STATS (all real)", L.COLORS["text"], lines, L.COLORS["panel"])

    def _render_attract(self, ctx, size):
        w, h = size
        accent = L.preset(ctx.preset)["accent"]
        ask_on = bool((ctx.ask or {}).get("enabled"))
        key = (ctx.preset, ask_on, size)
        if self._attract_static is None or self._attract_static[0] != key:
            # static layer (hook sentence + how-to card) drawn once per preset/ask change; the bar is the only per-step draw
            img = self.base(size)
            d = ImageDraw.Draw(img)
            d.text((L.PAD * 2, L.PAD), "THIS STREAM REBUILDS ITSELF.", font=L.font("HN Bold", 34), fill=L.COLORS["text"])
            d.text((L.PAD * 2, L.PAD + 42), "TYPE A, B OR C.", font=L.font("HN Bold", 34), fill=accent)
            card_y = L.PAD + 104
            d.rounded_rectangle([L.PAD, card_y, w - L.PAD, h - L.PAD // 2], radius=6, fill=L.COLORS["bg"], outline=L.COLORS["hairline"])
            rows = ["how to drive this stream", "A / B / C in chat votes the next change · most votes ships every 3 min",
                    "!idea <what should change> nominates it · !theme ember repaints it"]
            if ask_on:
                rows[2] = "!idea <text> nominates · !theme ember repaints · !ask <anything> is answered on screen"
            y = card_y + 8
            for i, ln in enumerate(rows):
                d.text((L.PAD * 2, y), L.truncate("HN Medium" if i == 0 else "HN", 24, ln, w - 4 * L.PAD),
                       font=L.font("HN Medium" if i == 0 else "HN", 24), fill=L.COLORS["text"] if i == 0 else L.COLORS["text2"])
                y += 32
            self._attract_static = (key, img)
        img = self._attract_static[1].copy()
        # breathing accent bar (1 Hz sine, ATTRACT_STEPS_PER_S quantised steps/s, no strobe): the body's own motion in ATTRACT
        phase = 0.5 + 0.5 * math.sin(2 * math.pi * ctx.now)
        bw = int(120 + 200 * phase)
        ImageDraw.Draw(img).rectangle([L.PAD * 2, L.PAD + 90, L.PAD * 2 + bw, L.PAD + 94], fill=accent)
        return img

    def _render_canvas(self, ctx, size):
        fn = _canvas_renderer(ctx.now)
        if fn is None:
            return self._render_status(ctx, size)
        try:
            img = fn(ctx, size)
            if not isinstance(img, Image.Image):
                raise TypeError("canvas render returned %r" % type(img))
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            if img.size != tuple(size):
                fixed = Image.new("RGBA", size, (0, 0, 0, 0))
                fixed.paste(img, (0, 0))
                img = fixed
            return img
        except Exception:
            _CANVAS["broken_until"] = ctx.now + 10.0        # a broken canvas costs 10 s of STATUS, never the loop
            return self._render_status(ctx, size)


register(StageTitle())
register(StageStep())
register(StageBody())
