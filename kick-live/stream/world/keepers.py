"""stream/world/keepers.py - the keepers: AI agents as the world's tenders, never creatures (WORLD.md 8.2, 9, 11).

    from stream.world.keepers import Keepers, lantern_state, keeper_lines, scrolls, classify_scroll, colony_bar
    keepers = Keepers(scene).attach()           # wraps scene.frame(): after every frame Keepers.tick() runs and its
                                                # events are appended to scene.events (never raises into the frame)
    lantern_state(ctx, now)                     # {"on_duty", "state": lit|dark|carving|flare|fail, "lowered", "sway", "flicker"}
    keeper_lines(ctx, now, keepers=keepers)     # keeper strip: {"line1", "line2", "fail_lines": [...3 + reverting], "header", "ticker"}
    scrolls(ctx, n=3)                           # wall scrolls: [{"id", "text", "by", "label", "tone"}] in world terms
    colony_bar(hatched, keepers=keepers)        # "3 have hatched here · 2 more until the Pool opens" (+ fraction)
    $PYTHON stream/world/keepers.py --self-test # RUN_DIR under /tmp only

What the keepers ARE on screen: a lantern on a chain at sim (300, 0-10), drawn by the scene from the same state
this module reads; a plain-language line in the keeper strip; wall scrolls for `!idea`; and rock that gets carved
live. They never speak in chat, never appear as a figure, never write a name that has not passed the filter.

Lantern / strip (WORLD.md 9):
  agent.heartbeat_ts fresh (< 120 s)   lit, lowered, 0.25 Hz flicker          `keeper on duty`
  stale / absent                        raised, dark                          `no keeper on duty · scrolls kept for next time`
  macro.active                          swings at 0.5 Hz                      `carving: <title> · asked by @<by> · 12:40 left`
  macro.last_reload.ok (<= 1 s ago)     flares                                `last carved: <title> · v0.5.0 · asked by @<by>`
  macro.last_reload.ok False (<= 20 s)  one red flicker                       first 3 traceback lines + `reverting to v0.4.2`
Never a live diff, only plain words; the failure lines exist only while a failure is fresh.

Chamber carve (WORLD.md 8.2): the colony bar counts distinct real people who have ever hatched (`len(pips)`), ladder
3 / 5 / 10 / 25 / 50. When WorldState.milestone_check() returns one and a keeper is on duty, the rock of the named
chamber crumbles over CARVE_S seconds through the core API (WorldState.set_terrain, protected cells never touched),
every awake pip turns to look, WorldState.mark_milestone() records it and `world.chambers` gets the row with the
person whose hatch crossed the line. No keeper on duty: the milestone waits (`milestone reached · keepers will carve
it next session`) and nothing is recorded until a keeper carves it. Nothing here creates, moves or names a pip.

`!idea` scrolls (WORLD.md 4, 9): agents/duty.py `classify` writes ideas[].class/status/reason; this module maps them
to world terms: `instant` -> a platform option next round, `macro` -> carving next, `declined: <reason>`, plus
`on the platforms now`, `carved · vX`, `pinned to the wall` for the rounds-owned states.
Python 3.9: from __future__ import annotations; numpy + stdlib only.
"""
from __future__ import annotations

import math
import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stream.state_store import iso_to_epoch  # noqa: E402
from stream.world import SIM_W, SIM_H  # noqa: E402
from stream.world.state import (MILESTONES, LEDGE_X, VOID_ROWS, SOIL_ROWS, MOUTH_X, LANTERN_X,  # noqa: E402
                                protected_mask)

HEARTBEAT_FRESH_S = 120.0
FAIL_SHOW_S = 20.0
FLARE_S = 1.0
CARVE_S = 20.0                        # rock crumbles into a new chamber over this long (a build you can watch land)
CARVE_STEP_S = 0.5                    # terrain (and the static cave layer) is updated this often while carving
FAIL_LINES = 3
LINE_MAX = 60

# Chambers, in sim px. Every box stays clear of the platforms' protected floor, the mouth pillars and the lantern
# column (protected_mask() is applied on top). `seed` is where the crumbling starts; `open` is which edge is open.
CHAMBERS: Dict[int, Dict[str, Any]] = {
    3: {"name": "the Ledge", "box": (LEDGE_X[0], 44, LEDGE_X[1], VOID_ROWS[1] + 1), "seed": (LEDGE_X[1], 66)},
    5: {"name": "East Chamber", "box": (MOUTH_X[1] + 7, 3, LANTERN_X - 3, 14), "seed": (MOUTH_X[1] + 7, 13)},
    10: {"name": "the Pool", "box": (190, SOIL_ROWS[0], 276, SOIL_ROWS[0] + 4), "seed": (233, SOIL_ROWS[0])},
    25: {"name": "the Loft", "box": (60, 3, 150, 14), "seed": (105, 13)},
    50: {"name": "the Deep", "box": (44, SIM_H - 3, 300, SIM_H), "seed": (172, SIM_H - 3)},
}


def chamber_name(m: int) -> str:
    c = CHAMBERS.get(int(m))
    return c["name"] if c else "chamber %d" % int(m)


def chamber_mask(m: int) -> np.ndarray:
    """Cells the carve of milestone `m` may open (jagged edges, protected cells removed). Empty for unknown m."""
    out = np.zeros((SIM_H, SIM_W), dtype=bool)
    c = CHAMBERS.get(int(m))
    if not c:
        return out
    x0, y0, x1, y1 = c["box"]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(SIM_W, x1), min(SIM_H, y1)
    if x1 <= x0 or y1 <= y0:
        return out
    out[y0:y1, x0:x1] = True
    # jagged rim: a deterministic 0-2 px bite along each edge so the chamber does not read as a rectangle
    for x in range(x0, x1):
        bite = (x * 7 + m) % 3
        out[y0:y0 + bite, x] = False
        out[max(y0, y1 - ((x * 5 + 1) % 3)):y1, x] = False
    for y in range(y0, y1):
        bite = (y * 3 + m) % 3
        out[y, x0:x0 + bite] = False
        out[y, max(x0, x1 - ((y * 11 + 2) % 3)):x1] = False
    out &= ~protected_mask()
    return out


def carve_order(mask: np.ndarray, seed: Tuple[int, int]) -> np.ndarray:
    """0..1 per cell: how far into the build each cell crumbles (distance from the seed point, normalised)."""
    ys, xs = np.nonzero(mask)
    order = np.ones((SIM_H, SIM_W), dtype=np.float32)
    if ys.size == 0:
        return order
    d = np.sqrt((xs - seed[0]) ** 2 + (ys - seed[1]) ** 2).astype(np.float32)
    mx = float(d.max()) or 1.0
    order[ys, xs] = d / mx
    return order


def _fresh(ctx, now: float) -> bool:
    hb = iso_to_epoch(((getattr(ctx, "agent", None) or {}).get("heartbeat_ts")))
    return hb is not None and 0.0 <= (now - hb) < HEARTBEAT_FRESH_S


def _mmss(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return "%d:%02d" % (s // 60, s % 60)


def _clip(s: str, n: int = LINE_MAX) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _version(ctx) -> str:
    v = getattr(ctx, "version", None) or {}
    return str(v.get("string") or "v%d.%d.%d" % (int(v.get("major") or 0), int(v.get("macro") or 0), int(v.get("micro") or 0)))


class _NameFilter(object):
    """Filtered names only. Prefers the caller's filter, then the scene's WorldState filter (the bridge's blocklist
    path), then a ChatBridge built for the run dir; when nothing can filter, no name is written at all."""

    def __init__(self, fn: Optional[Callable[[str], Optional[str]]] = None, scene=None, run_dir: Optional[str] = None):
        self.fn = fn
        self.scene = scene
        self.run_dir = run_dir
        self._bridge = None
        self._tried = False

    def __call__(self, name: Optional[str], ctx=None) -> Optional[str]:
        if not name:
            return None
        if ctx is not None and getattr(ctx, "chat_display", None) is False:
            return None                                          # !kill: no names anywhere
        name = str(name).lstrip("@")
        if self.fn is not None:
            try:
                return self.fn(name)
            except Exception:
                return None
        w = getattr(self.scene, "world", None)
        if w is not None:
            p = w.pip(name.lower()) if hasattr(w, "pip") else None
            if p is not None and p.get("display_name"):
                return str(p["display_name"])
            nf = getattr(w, "name_filter", None)
            if nf is not None:
                try:
                    r = nf(name)
                    if r:
                        return str(r)
                except Exception:
                    pass
        if not self._tried:
            self._tried = True
            try:
                from stream.chat_bridge import ChatBridge
                self._bridge = ChatBridge(self.run_dir or os.environ.get("RUN_DIR") or os.path.join(_ROOT, "run"), log=lambda m: None)
                self._bridge._load_blocklist(0.0)
            except Exception:
                self._bridge = None
        if self._bridge is not None:
            try:
                return self._bridge._display_name(name)
            except Exception:
                return None
        return None


# ---------------------------------------------------------------------------- lantern + strip
def lantern_state(ctx, now: float) -> Dict[str, Any]:
    fresh = _fresh(ctx, now)
    mac = getattr(ctx, "macro", None) or {}
    lr = mac.get("last_reload") or {}
    lr_t = iso_to_epoch(lr.get("ts"))
    since = (now - lr_t) if lr_t is not None else None
    state = "lit" if fresh else "dark"
    if mac.get("active"):
        state = "carving"
    elif since is not None and 0.0 <= since <= FAIL_SHOW_S and lr.get("ok") is False:
        state = "fail"
    elif since is not None and 0.0 <= since <= FLARE_S and lr.get("ok"):
        state = "flare"
    sway = math.sin(2 * math.pi * 0.5 * now) if mac.get("active") else 0.0
    flicker = 0.75 + 0.25 * math.sin(2 * math.pi * 0.25 * now) if fresh else 0.0
    return {"on_duty": fresh, "state": state, "lowered": fresh, "sway": sway, "flicker": flicker,
            "since_reload_s": since, "red": state == "fail" and since is not None and since < 1.0}


def keeper_lines(ctx, now: float, name_filter: Optional[Callable[[str], Optional[str]]] = None, keepers: "Optional[Keepers]" = None,
                 run_dir: Optional[str] = None) -> Dict[str, Any]:
    """The keeper strip (WORLD.md 5 region 7) in plain words. `fail_lines` is non-empty ONLY while a build failure is
    fresh (<= 20 s). `header` is the header_center line during a build (`keeper carving · 12:40 left`), else None."""
    nf = name_filter if isinstance(name_filter, _NameFilter) else _NameFilter(name_filter, getattr(keepers, "scene", None), run_dir)
    lan = lantern_state(ctx, now)
    mac = getattr(ctx, "macro", None) or {}
    lr = mac.get("last_reload") or {}
    out: Dict[str, Any] = {"line1": "keeper on duty" if lan["on_duty"] else "no keeper on duty · scrolls kept for next time",
                           "line2": None, "fail_lines": [], "header": None, "ticker": None, "lantern": lan}
    who = nf(mac.get("requested_by"), ctx)
    asked = (" · asked by @%s" % who) if who else ""
    carve = keepers.carving_line(now, nf, ctx) if keepers is not None else None
    if mac.get("active"):
        dl = iso_to_epoch(mac.get("deadline_ts"))
        left = (" · %s left" % _mmss(dl - now)) if dl is not None and dl >= now else (" · overdue" if dl is not None else "")
        out["line2"] = _clip("carving: %s%s%s" % (mac.get("title") or "something new", asked, left))
        out["header"] = "keeper carving%s" % left
    elif carve is not None:
        out["line2"] = carve["line"]
        out["header"] = carve["header"]
    elif lr.get("ts") and (keepers is None or keepers.last_carved is None or (iso_to_epoch(lr.get("ts")) or 0.0) >= keepers.last_carved["t"]):
        title = mac.get("title") or (lr.get("module") and os.path.basename(str(lr.get("module")))) or "the last build"
        if lr.get("ok"):
            ver = _last_macro_version(ctx) or _version(ctx)
            out["line2"] = _clip("last carved: %s · %s%s" % (title, ver, asked))
        else:
            out["line2"] = _clip("last build failed: %s%s" % (title, asked))
            since = lan["since_reload_s"]
            if since is not None and 0.0 <= since <= FAIL_SHOW_S:
                err = str(lr.get("error") or "no error text recorded")
                lines = [ln.strip() for ln in err.replace("\r", "").split("\n") if ln.strip()][:FAIL_LINES]
                out["fail_lines"] = [_clip(ln) for ln in lines] + ["reverting to %s" % _version(ctx)]
    elif keepers is not None and keepers.last_carved is not None:
        lc = keepers.last_carved
        who_c = nf(lc.get("by"), ctx) if lc.get("by") else None
        out["line2"] = _clip("last carved: %s · %s%s" % (lc["name"], lc["version"], (" · opened by @%s's hatch" % who_c) if who_c else ""))
    elif keepers is not None and keepers.waiting is not None:
        out["line2"] = "milestone reached · keepers will carve %s next session" % chamber_name(keepers.waiting)
    else:
        out["line2"] = "nothing carved yet · !idea <text> pins a scroll for the keepers"
    if keepers is not None and keepers.last_ticker and now - keepers.last_ticker_t < 30.0:
        out["ticker"] = keepers.last_ticker
    return out


def _last_macro_version(ctx) -> Optional[str]:
    for line in reversed(list(getattr(ctx, "ships", None) or [])):
        if isinstance(line, dict) and line.get("kind") == "macro" and line.get("ok"):
            return str(line.get("version") or "") or None
    return None


# ---------------------------------------------------------------------------- scrolls (!idea)
SCROLL_LABELS = {
    "declined": ("declined", "grey"),
    "shipped": ("carved", "accent"),
    "ballot": ("on the platforms now", "accent"),
    "instant": ("instant · a platform option next round", "accent"),
    "macro": ("carving next", "accent"),
    "pending": ("pinned to the wall", "text"),
}


def classify_scroll(idea: Dict[str, Any], ctx=None) -> Dict[str, str]:
    """World terms for one state.ideas[] entry (written by rounds.py and duty.py classify)."""
    status = str(idea.get("status") or "open")
    cls = str(idea.get("class") or "pending")
    if status == "declined" or cls == "declined":
        reason = _clip(str(idea.get("reason") or "no reason given"), 40)
        return {"label": "declined: %s" % reason, "tone": "grey", "cls": "declined"}
    if status == "shipped":
        return {"label": "carved · %s" % _version(ctx) if ctx is not None else "carved", "tone": "accent", "cls": "shipped"}
    if status == "failed":
        return {"label": "build failed · kept for next time", "tone": "grey", "cls": "failed"}
    if status == "ballot":
        return {"label": SCROLL_LABELS["ballot"][0], "tone": "accent", "cls": "ballot"}
    if cls in ("instant", "macro"):
        lab, tone = SCROLL_LABELS[cls]
        return {"label": lab, "tone": tone, "cls": cls}
    return {"label": SCROLL_LABELS["pending"][0], "tone": "text", "cls": "pending"}


def scrolls(ctx, n: int = 3, name_filter: Optional[Callable[[str], Optional[str]]] = None, run_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Up to `n` wall scrolls: open/queued/ballot first (newest first), then the newest declined. Names filtered."""
    nf = name_filter if isinstance(name_filter, _NameFilter) else _NameFilter(name_filter, None, run_dir)
    ideas = [i for i in (getattr(ctx, "ideas", None) or []) if isinstance(i, dict) and (i.get("text") or "").strip()]
    live = [i for i in ideas if i.get("status") in ("open", "queued", "ballot")]
    done = [i for i in ideas if i.get("status") in ("declined", "shipped", "failed")]
    live.sort(key=lambda i: iso_to_epoch(i.get("ts")) or 0.0, reverse=True)
    done.sort(key=lambda i: iso_to_epoch(i.get("ts")) or 0.0, reverse=True)
    out = []
    for i in (live + done)[:n]:
        c = classify_scroll(i, ctx)
        out.append({"id": str(i.get("id")), "text": _clip(str(i.get("text")), 60), "by": nf(i.get("by"), ctx),
                    "label": c["label"], "tone": c["tone"], "cls": c["cls"], "plus": int(i.get("plus") or 0)})
    return out


# ---------------------------------------------------------------------------- colony bar copy
def next_milestone(hatched: int, ladder: Optional[List[int]] = None) -> Optional[int]:
    for m in (ladder or MILESTONES):
        if int(hatched) < int(m):
            return int(m)
    return None


def colony_bar(hatched: int, keepers: "Optional[Keepers]" = None, ladder: Optional[List[int]] = None) -> Dict[str, Any]:
    """`3 have hatched here · 2 more until the Pool opens` plus the bar fraction (real numbers only)."""
    hatched = int(hatched)
    ladder = ladder or MILESTONES
    nxt = next_milestone(hatched, ladder)
    if keepers is not None and keepers.waiting is not None:
        text = "%d have hatched here · milestone reached · keepers will carve it next session" % hatched
        return {"text": text, "fraction": 1.0, "next": keepers.waiting}
    if keepers is not None and keepers.carving is not None:
        c = keepers.carving
        return {"text": "%d have hatched here · %s is opening" % (hatched, c["name"]), "fraction": 1.0, "next": c["m"]}
    if nxt is None:
        return {"text": "%d have hatched here · every chamber is open" % hatched, "fraction": 1.0, "next": None}
    prev = 0
    for m in ladder:
        if m <= hatched:
            prev = m
    frac = (hatched - prev) / float(max(1, nxt - prev))
    if hatched == 0:
        text = "nobody has hatched here yet · %d until %s opens" % (nxt, chamber_name(nxt))
    else:
        text = "%d %s hatched here · %d more until %s opens" % (hatched, "has" if hatched == 1 else "have", nxt - hatched, chamber_name(nxt))
    return {"text": text, "fraction": max(0.0, min(1.0, frac)), "next": nxt}


# ---------------------------------------------------------------------------- the per-frame keeper
class Keepers(object):
    def __init__(self, scene, name_filter: Optional[Callable[[str], Optional[str]]] = None, carve_s: float = CARVE_S, log=None):
        self.scene = scene
        self.nf = _NameFilter(name_filter, scene, getattr(scene, "run_dir", None))
        self.carve_s = float(carve_s)
        self.log = log or (lambda m: sys.stderr.write("keepers: %s\n" % m))
        self.carving: Optional[Dict[str, Any]] = None
        self.waiting: Optional[int] = None
        self._waiting_announced: Optional[int] = None
        self._macro_active: Optional[bool] = None
        self._macro_ts: Optional[str] = None
        self.last_ticker: Optional[str] = None
        self.last_ticker_t = -1e18
        self.chambers_opened = 0
        self.last_carved: Optional[Dict[str, Any]] = None       # {"name", "by", "version", "t"}
        self.errors = 0
        self.ticks = 0
        self._attached = False
        self._protected = protected_mask()

    # -- wiring
    def attach(self) -> "Keepers":
        """Wrap scene.frame so tick() runs after every frame; its events land in scene.events. Idempotent."""
        if self._attached:
            return self
        scene, orig = self.scene, self.scene.frame
        me = self

        def frame(ctx, size):
            img = orig(ctx, size)
            try:
                now = float(getattr(ctx, "now", None) or getattr(scene, "_last_now", None) or 0.0)
                evs = me.tick(ctx, now)
                if evs:
                    scene.events.extend(evs)
            except Exception:
                me.errors += 1
                if me.errors <= 3:
                    me.log("tick failed (%d): %s" % (me.errors, traceback.format_exc().strip().splitlines()[-1]))
            return img
        scene.frame = frame
        scene.keepers = self
        self._attached = True
        return self

    # -- per frame
    def tick(self, ctx, now: float) -> List[Dict[str, Any]]:
        self.ticks += 1
        scene = self.scene
        if not getattr(scene, "booted", False) or scene.world is None or scene.behaviour is None:
            return []
        evs: List[Dict[str, Any]] = []
        self._macro_events(ctx, now, evs)
        w = scene.world
        if self.carving is None:
            m = w.milestone_check()
            if m is not None:
                by_key = self._crossing_key()
                if _fresh(ctx, now):
                    self._start_carve(m, by_key, now, ctx, evs)
                else:
                    self.waiting = m
                    if self._waiting_announced != m:
                        self._waiting_announced = m
                        evs.append({"type": "milestone_waiting", "milestone": m, "chamber": chamber_name(m), "count": w.hatched_ever})
                        self.log("milestone %d reached (%d hatched); no keeper on duty, %s waits" % (m, w.hatched_ever, chamber_name(m)))
            else:
                self.waiting = None
        if self.carving is not None:
            self._step_carve(now, ctx, evs)
        return evs

    def _crossing_key(self) -> Optional[str]:
        """The real person whose hatch crossed the line: the newest-born pip (test pips never count)."""
        best, best_t = None, None
        for k, p in self.scene.world.pips.items():
            if p.get("_test"):
                continue
            t = iso_to_epoch(p.get("born_ts")) or 0.0
            if best_t is None or t > best_t:
                best, best_t = k, t
        return best

    def _look_at(self, x: float) -> None:
        for e in self.scene.behaviour.awake():
            e.facing = 1 if x >= e.x else -1

    def _start_carve(self, m: int, by_key: Optional[str], now: float, ctx, evs: List[Dict[str, Any]]) -> None:
        w = self.scene.world
        mask = chamber_mask(m) & ~w.terrain()
        if not mask.any():
            # nothing left to carve (already open, or an unknown milestone): record it and move on, honestly
            w.mark_milestone(m, by_key, now)
            evs.append({"type": "milestone", "milestone": m, "chamber": chamber_name(m), "by": by_key, "count": w.hatched_ever, "carved": False})
            self.waiting = None
            return
        seed = CHAMBERS.get(m, {}).get("seed", (int(np.nonzero(mask)[1].mean()), int(np.nonzero(mask)[0].mean())))
        self.carving = {"m": m, "name": chamber_name(m), "by": by_key, "t0": now, "mask": mask,
                        "order": carve_order(mask, seed), "cells": int(mask.sum()), "carved": 0, "last_step": -1e18, "seed": seed}
        self.waiting = None
        self._look_at(float(seed[0]))
        shown = self.nf(by_key, ctx) if by_key else None
        w.log_event("keeper carving %s%s" % (chamber_name(m), (" · opened by @%s's hatch" % shown) if shown else ""), now)
        evs.append({"type": "milestone", "milestone": m, "chamber": chamber_name(m), "by": by_key, "count": w.hatched_ever, "carved": True})
        evs.append({"type": "carve_start", "milestone": m, "chamber": chamber_name(m), "by": by_key, "cells": self.carving["cells"],
                    "x": int(seed[0]), "y": int(seed[1]), "duration_s": self.carve_s})
        self.log("milestone %d (%d hatched): carving %s, %d cells over %.0f s%s" % (
            m, w.hatched_ever, chamber_name(m), self.carving["cells"], self.carve_s, (" · by @%s's hatch" % shown) if shown else ""))

    def _step_carve(self, now: float, ctx, evs: List[Dict[str, Any]]) -> None:
        c = self.carving
        w = self.scene.world
        progress = min(1.0, max(0.0, (now - c["t0"]) / max(0.1, self.carve_s)))
        if now - c["last_step"] >= CARVE_STEP_S or progress >= 1.0:
            c["last_step"] = now
            open_now = c["mask"] & (c["order"] <= progress + 1e-6)
            new_cells = int((open_now & ~w.terrain()).sum())
            if new_cells:
                w.set_terrain(w.terrain() | open_now)
                c["carved"] = int((c["mask"] & w.terrain()).sum())
                evs.append({"type": "carve_step", "chamber": c["name"], "progress": round(progress, 3), "cells": c["carved"]})
        if progress >= 1.0:
            m, by = c["m"], c["by"]
            w.mark_milestone(m, by, now)
            row = {"name": c["name"], "opened_ts": iso_to_epoch_inv(now), "by": by, "milestone": m, "cells": c["carved"]}
            chambers = w.data["world"].setdefault("chambers", [])
            if not any(ch.get("milestone") == m for ch in chambers):
                chambers.append(row)
            shown = self.nf(by, ctx) if by else None
            ver = _version(ctx)
            w.log_event("%s opened%s · %s" % (c["name"], (" · by @%s's hatch" % shown) if shown else "", ver), now)
            w.dirty = True
            try:
                w.save(now, force=True)
            except Exception as ex:
                self.log("save after carve failed: %r" % (ex,))
            self._look_at(float(c["seed"][0]))
            self.last_ticker = "SHIPPED %s · %s opened%s" % (ver, c["name"], (" · by @%s's hatch" % shown) if shown else "")
            self.last_ticker_t = now
            self.last_carved = {"name": c["name"], "by": by, "version": ver, "t": now}
            evs.append({"type": "carve_done", "milestone": m, "chamber": c["name"], "by": by, "cells": c["carved"], "version": ver})
            self.chambers_opened += 1
            self.log("%s open: %d cells, milestone %d recorded" % (c["name"], c["carved"], m))
            self.carving = None

    def _macro_events(self, ctx, now: float, evs: List[Dict[str, Any]]) -> None:
        """A keeper build (agents/duty.py macro-start / macro-done) announced in the world: pips look at the lantern."""
        mac = getattr(ctx, "macro", None) or {}
        active = bool(mac.get("active"))
        if self._macro_active is not None and active and not self._macro_active:
            self._look_at(float(LANTERN_X))
            evs.append({"type": "keeper_carving", "title": mac.get("title"), "by": mac.get("requested_by")})
        self._macro_active = active
        lr = mac.get("last_reload") or {}
        ts = lr.get("ts")
        if ts and ts != self._macro_ts:
            if self._macro_ts is not None:                     # not the one we booted with
                self._look_at(float(LANTERN_X))
                if lr.get("ok"):
                    evs.append({"type": "keeper_carved", "title": mac.get("title"), "by": mac.get("requested_by"),
                                "version": _last_macro_version(ctx) or _version(ctx)})
                else:
                    err = str(lr.get("error") or "")
                    evs.append({"type": "keeper_carve_failed", "title": mac.get("title"), "by": mac.get("requested_by"),
                                "error_lines": [ln.strip() for ln in err.split("\n") if ln.strip()][:FAIL_LINES],
                                "reverting_to": _version(ctx)})
            self._macro_ts = ts

    # -- read API
    def carving_line(self, now: float, nf=None, ctx=None) -> Optional[Dict[str, str]]:
        c = self.carving
        if c is None:
            return None
        nf = nf or self.nf
        left = max(0.0, c["t0"] + self.carve_s - now)
        shown = nf(c["by"], ctx) if c["by"] else None
        return {"line": _clip("carving: %s · %s left%s" % (c["name"], _mmss(left), (" · opened by @%s's hatch" % shown) if shown else "")),
                "header": "keeper carving · %s left" % _mmss(left)}

    def stats(self) -> Dict[str, Any]:
        return {"ticks": self.ticks, "errors": self.errors, "carving": None if self.carving is None else
                {k: self.carving[k] for k in ("m", "name", "by", "cells", "carved")}, "waiting": self.waiting,
                "chambers_opened": self.chambers_opened, "attached": self._attached}


def iso_to_epoch_inv(t: float) -> str:
    from stream.state_store import epoch_to_iso
    return epoch_to_iso(t, ms=True)


# ---------------------------------------------------------------------------- self-test
def _selftest(run_dir: str) -> int:
    import json
    import shutil
    import time as _time
    from stream.scenes.hollow import CaveScene, _Ctx
    from stream.state_store import epoch_to_iso
    from stream.world.honesty import HonestyMonitor

    rp = os.path.realpath(run_dir)
    if not (rp.startswith("/tmp/") or rp.startswith("/private/tmp/")):
        print("refused: RUN_DIR must be under /tmp (got %s)" % run_dir)
        return 2
    os.environ.pop("KL_TEST_PIPS", None)
    if os.path.isdir(run_dir):
        shutil.rmtree(run_dir)
    os.makedirs(run_dir)
    ok = True
    fps = 30.0
    t0 = _time.time()
    session = {"id": "keepers-" + epoch_to_iso(t0, ms=False), "started_ts": epoch_to_iso(t0 - 30, ms=False), "ending": False}
    names = ["keepers-test-ana", "keepers-test-bo", "keepers-test-cy"]
    chat_path = os.path.join(run_dir, "chat.jsonl")
    with open(chat_path, "w") as fh:                     # three real-shaped records: hatched_ever == 3 == milestone 3
        fh.write(json.dumps({"id": "k-1", "ts": epoch_to_iso(t0 - 7200), "username": names[0], "content": "hello", "type": "message"}) + "\n")
        fh.write(json.dumps({"id": "k-2", "ts": epoch_to_iso(t0 - 7100), "user": names[1], "text": "hi", "user_id": 3}) + "\n")
        fh.write(json.dumps({"id": "k-3", "ts": epoch_to_iso(t0 - 60), "username": names[2], "content": "yo", "type": "message"}) + "\n")

    def mkctx(now, frame, hb=None, macro=None, ideas=None, chat_display=True, version="v0.5.0", ships=None):
        return _Ctx(now=now, frame=frame, fps=fps, session=session, micro={"canvas_seed": 41370704}, preset="kick",
                    chat_raw=[], chat=[], recent_votes=[], round={"number": 1}, mod={"hidden_users": []},
                    agent={"heartbeat_ts": hb, "on_duty": hb is not None, "name": "claude"}, macro=macro or {"active": False},
                    compositor_live={"selftest": True}, mod_paused=False, chat_display=chat_display, ideas=ideas or [],
                    version={"string": version, "major": 0, "macro": 5, "micro": 0}, ships=ships or [])

    size = (1280, 440)
    frames_dir = os.path.join(run_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    # ---- A. no keeper on duty: the milestone waits, nothing is carved or recorded
    scene = CaveScene(run_dir=run_dir, seed=5, sleep_after_s=60.0)
    keep = Keepers(scene, carve_s=2.0).attach()
    mon = HonestyMonitor(scene, enforce=False, log=lambda m: None)
    evs: Dict[str, int] = {}
    now = t0
    for i in range(30):
        now = t0 + i / fps
        img = scene.frame(mkctx(now, i, hb=None), size)
        mon.check(mkctx(now, i), now)
        for e in scene.events:
            evs[e["type"]] = evs.get(e["type"], 0) + 1
    terr0 = scene.world.terrain().copy()
    ledge_before = int(terr0[44:88, 0:40].sum())
    lines = keeper_lines(mkctx(now, 0, hb=None), now, keepers=keep)
    print("[A] no keeper: hatched_ever=%d waiting=%r milestones_reached=%r ledge carved cells=%d events=%r" % (
        scene.hatched_ever(), keep.waiting, scene.world.data["world"]["milestones_reached"], ledge_before, dict(sorted(evs.items()))))
    print("[A] strip: %r" % (lines,))
    print("[A] colony bar: %r" % (colony_bar(scene.hatched_ever(), keep),))
    if keep.waiting != 3 or scene.world.data["world"]["milestones_reached"] or ledge_before != 0 or evs.get("milestone_waiting") != 1:
        print("FAIL A"); ok = False
    if lines["line1"] != "no keeper on duty · scrolls kept for next time" or lines["fail_lines"] or "next session" not in (lines["line2"] or ""):
        print("FAIL A strip"); ok = False
    img.save(os.path.join(frames_dir, "A_waiting.png"))

    # ---- B. keeper comes on duty: the Ledge crumbles over carve_s, every awake pip looks, milestone recorded
    hb = epoch_to_iso(now)
    evs = {}
    steps = []
    n = int(2.0 * fps) + 20
    for i in range(n):
        now += 1.0 / fps
        ctx = mkctx(now, i, hb=hb)
        img = scene.frame(ctx, size)
        rep = mon.check(ctx, now)
        for e in scene.events:
            evs[e["type"]] = evs.get(e["type"], 0) + 1
            if e["type"] == "carve_step":
                steps.append((round(now - t0, 2), e["progress"], e["cells"]))
        if i == 40:                                           # progress ~0.67: rock half crumbled
            mid = keeper_lines(ctx, now, keepers=keep)
            img.save(os.path.join(frames_dir, "B_carving_mid.png"))
    terr1 = scene.world.terrain()
    ledge_after = int(terr1[44:88, 0:40].sum())
    ch = scene.world.data["world"]["chambers"]
    print("[B] keeper on duty: events=%r" % (dict(sorted(evs.items())),))
    print("[B] carve steps (t, progress, cells): %r" % (steps[:3] + ["..."] + steps[-2:],))
    print("[B] ledge carved cells before=%d after=%d; milestones_reached=%r; chambers=%r" % (
        ledge_before, ledge_after, scene.world.data["world"]["milestones_reached"], [(c["name"], c.get("milestone"), c.get("by"), c.get("cells")) for c in ch]))
    print("[B] mid-carve strip: %r" % ({k: mid[k] for k in ("line1", "line2", "header", "fail_lines")},))
    print("[B] after strip: %r" % ({k: v for k, v in keeper_lines(mkctx(now, 0, hb=hb), now, keepers=keep).items() if k != "lantern"},))
    print("[B] protected cells untouched: %s; honesty during carve: %r" % (
        not bool((terr1 & protected_mask() & ~terr0).any()), {k: mon.summary()[k] for k in ("frames", "violations", "by_rule")}))
    print("[B] event_log tail: %r" % (scene.world.data["world"]["event_log"][-2:],))
    saved = json.load(open(os.path.join(run_dir, "world.json")))
    print("[B] world.json on disk: milestones_reached=%r chambers=%d terrain_b64=%s" % (
        saved["world"]["milestones_reached"], len(saved["world"]["chambers"]), "yes" if saved["world"].get("terrain_b64") else "no"))
    if evs.get("carve_start") != 1 or evs.get("carve_done") != 1 or ledge_after < 500 or scene.world.data["world"]["milestones_reached"] != [3]:
        print("FAIL B carve"); ok = False
    if not any(c.get("milestone") == 3 and c["name"] == "the Ledge" for c in ch) or saved["world"]["milestones_reached"] != [3]:
        print("FAIL B record"); ok = False
    if (terr1 & protected_mask() & ~terr0).any():
        print("FAIL B protected"); ok = False
    after = keeper_lines(mkctx(now, 0, hb=hb), now, keepers=keep)
    if not (after["line2"] or "").startswith("last carved: the Ledge · v0.5.0"):
        print("FAIL B after-strip"); ok = False
    if mid["header"] is None or not (mid["line2"] or "").startswith("carving: the Ledge · 0:0") or mid["fail_lines"]:
        print("FAIL B strip"); ok = False
    if mon.summary()["violations"]:
        print("FAIL B honesty"); ok = False
    img.save(os.path.join(frames_dir, "B_ledge_open.png"))
    # names: the crossing person's shown name is the pip's filtered display name; !kill removes it
    by = ch[-1].get("by")
    shown = keep.nf(by, mkctx(now, 0, hb=hb))
    hidden = keep.nf(by, mkctx(now, 0, hb=hb, chat_display=False))
    print("[B] crossing pip key=%r shown=%r under !kill=%r" % (by, shown, hidden))
    if hidden is not None:
        print("FAIL B kill"); ok = False

    # ---- C. lantern + strip for every agent state (WORLD.md 9 table), failure lines ONLY on failure
    base = now
    fresh = epoch_to_iso(base)
    stale = epoch_to_iso(base - 600)
    cases = {
        "fresh": mkctx(base, 0, hb=fresh),
        "stale": mkctx(base, 0, hb=stale),
        "macro": mkctx(base, 0, hb=fresh, macro={"active": True, "title": "the Pool", "requested_by": names[0],
                                                  "deadline_ts": epoch_to_iso(base + 760), "last_reload": None}),
        "shipped": mkctx(base, 0, hb=fresh, macro={"active": False, "title": "East Chamber", "requested_by": names[1],
                                                    "last_reload": {"ts": epoch_to_iso(base - 0.5), "ok": True, "module": "x.py"}},
                         ships=[{"kind": "macro", "ok": True, "version": "v0.6.0"}]),
        "failed": mkctx(base, 0, hb=fresh, macro={"active": False, "title": "the Deep", "requested_by": names[2],
                                                   "last_reload": {"ts": epoch_to_iso(base - 5), "ok": False, "module": "y.py",
                                                                   "error": "Traceback (most recent call last):\n  File \"y.py\", line 3\n    boom()\nNameError: name 'boom' is not defined"}},
                        version="v0.4.2"),
        "failed_old": mkctx(base, 0, hb=fresh, macro={"active": False, "title": "the Deep", "requested_by": names[2],
                                                       "last_reload": {"ts": epoch_to_iso(base - 45), "ok": False, "error": "x\ny\nz\nw"}}),
    }
    want_state = {"fresh": "lit", "stale": "dark", "macro": "carving", "shipped": "flare", "failed": "fail", "failed_old": "lit"}
    for k, c in cases.items():
        lan = lantern_state(c, base)
        kl = keeper_lines(c, base, keepers=None, run_dir=run_dir)
        print("[C] %-10s lantern=%-8s lowered=%-5s line1=%r line2=%r header=%r fail_lines=%r" % (
            k, lan["state"], lan["lowered"], kl["line1"], kl["line2"], kl["header"], kl["fail_lines"]))
        if lan["state"] != want_state[k]:
            print("FAIL C lantern %s" % k); ok = False
        if k == "failed" and (len(kl["fail_lines"]) != 4 or kl["fail_lines"][-1] != "reverting to v0.4.2"):
            print("FAIL C fail lines"); ok = False
        if k != "failed" and kl["fail_lines"]:
            print("FAIL C fail lines shown outside a fresh failure"); ok = False
        if k == "macro" and (kl["header"] != "keeper carving · 12:40 left" or "asked by @" not in kl["line2"]):
            print("FAIL C macro line"); ok = False
        if k == "shipped" and not kl["line2"].startswith("last carved: East Chamber · v0.6.0"):
            print("FAIL C shipped line"); ok = False
        if k == "stale" and kl["line1"] != "no keeper on duty · scrolls kept for next time":
            print("FAIL C stale"); ok = False

    # ---- D. scrolls: duty.py classify outcomes in world terms
    ideas = [
        {"id": "i-0001", "text": "make it rain glow", "by": names[0], "ts": epoch_to_iso(base - 100), "plus": 2, "class": "instant", "status": "queued", "reason": None},
        {"id": "i-0002", "text": "a second chamber", "by": names[1], "ts": epoch_to_iso(base - 90), "plus": 0, "class": "macro", "status": "queued", "reason": None},
        {"id": "i-0003", "text": "let pips die", "by": names[2], "ts": epoch_to_iso(base - 80), "plus": 0, "class": "declined", "status": "declined", "reason": "absence is never punished"},
        {"id": "i-0004", "text": "fog tonight", "by": names[0], "ts": epoch_to_iso(base - 70), "plus": 0, "class": "pending", "status": "open", "reason": None},
        {"id": "i-0005", "text": "on the ballot", "by": names[1], "ts": epoch_to_iso(base - 60), "plus": 1, "class": "instant", "status": "ballot", "reason": None},
    ]
    sc = scrolls(mkctx(base, 0, ideas=ideas), n=5, run_dir=run_dir)
    for s in sc:
        print("[D] scroll %s by @%s: %r -> %s (%s)" % (s["id"], s["by"], s["text"], s["label"], s["tone"]))
    labels = {s["id"]: s["label"] for s in sc}
    if labels.get("i-0001") != "instant · a platform option next round" or labels.get("i-0002") != "carving next":
        print("FAIL D instant/macro"); ok = False
    if labels.get("i-0003") != "declined: absence is never punished" or labels.get("i-0004") != "pinned to the wall" or labels.get("i-0005") != "on the platforms now":
        print("FAIL D declined/pending/ballot"); ok = False
    if sc[0]["id"] != "i-0005" or sc[-1]["id"] != "i-0003":
        print("FAIL D order (live newest first, declined last)"); ok = False
    if any(s["by"] is not None for s in scrolls(mkctx(base, 0, ideas=ideas, chat_display=False), n=5, run_dir=run_dir)):
        print("FAIL D !kill names"); ok = False

    # ---- E. macro announce in the world (duty.py macro-start / macro-done seen through ctx.macro)
    evs = {}
    seq = [
        mkctx(base + 1, 0, hb=fresh, macro={"active": False, "last_reload": {"ts": epoch_to_iso(base - 100), "ok": True}}),
        mkctx(base + 2, 1, hb=fresh, macro={"active": True, "title": "gift verb", "requested_by": names[0], "deadline_ts": epoch_to_iso(base + 900)}),
        mkctx(base + 3, 2, hb=fresh, macro={"active": False, "title": "gift verb", "requested_by": names[0],
                                            "last_reload": {"ts": epoch_to_iso(base + 3), "ok": True, "module": "verbs.py"}}),
        mkctx(base + 4, 3, hb=fresh, macro={"active": False, "title": "gift verb", "requested_by": names[0],
                                            "last_reload": {"ts": epoch_to_iso(base + 4), "ok": False, "error": "SyntaxError: bad\nline 2"}}),
    ]
    for c in seq:
        scene.frame(c, size)
        for e in scene.events:
            if e["type"].startswith("keeper_"):
                evs[e["type"]] = e
    print("[E] macro announce events: %r" % ({k: {kk: vv for kk, vv in v.items() if kk != "type"} for k, v in evs.items()},))
    if set(evs) != {"keeper_carving", "keeper_carved", "keeper_carve_failed"} or evs["keeper_carve_failed"]["error_lines"] != ["SyntaxError: bad", "line 2"]:
        print("FAIL E"); ok = False

    # ---- F. colony bar copy from real counts
    for h in (0, 1, 3, 4, 12, 60):
        print("[F] hatched=%d -> %r" % (h, colony_bar(h)))
    if colony_bar(0)["text"] != "nobody has hatched here yet · 3 until the Ledge opens" or colony_bar(4)["text"] != "4 have hatched here · 1 more until East Chamber opens":
        print("FAIL F"); ok = False
    print("[stats] keepers=%r honesty=%r scene=%r" % (keep.stats(), {k: mon.summary()[k] for k in ("frames", "violations")},
                                                       {k: scene.stats()[k] for k in ("frames", "errors", "honesty_violations", "avg_ms")}))
    print("[frames] %s" % ", ".join(os.path.join(frames_dir, f) for f in sorted(os.listdir(frames_dir))))
    print("KEEPERS SELF-TEST %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        sys.exit(_selftest(os.environ.get("RUN_DIR") or "/tmp/pip-keepers-k"))
    print(__doc__)
