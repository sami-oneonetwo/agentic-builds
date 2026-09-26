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

LONGGRASS (docs/OPENWORLD.md 10; land mode, chosen per scene: `Keepers.land_mode` is True when the scene's world is
schema 2 / carries a Land). Everything above stays for the cave's rollback week; on the land:
  beacon_state(ctx, now, moot)      the lantern on a post at the Moot: lantern_state() + {x, y, minimap_dot}; lit ONLY on a
                                    fresh heartbeat, swinging during a macro build, a flare on a ship, one red flicker on a fail
  keeper_lines(ctx, now, land=True) `keeper on duty · beacon lit` / `no keeper on duty · notices kept for next time`,
                                    `raising: <title> · asked by @sam · 12:40 left`, `last raised: the well · v0.7.0`
  notices(ctx, n=3)                 the board on the Moot: `!idea`s in land terms (`instant · a waystone option next round`,
                                    `raising next`, `declined: <reason>`, `on the waystones now`, `raised · vX`, `pinned to the board`)
  land_bar(walked, keepers)         `17 have walked here · 8 more until the Coast opens` (head-count ladder 3 / 5 / 10 / 25 / 50:
                                    3 sets the cairn, 5 the hearth ring, 10+ open land strips (v1.1); colony_bar() dispatches here)
  ladder_line(land, nf, ctx)        the stone ladder for the land strip: `stone 13 of 20 · the Ford bridge · last by @kai`
  nightly_board(scene, now, ...)    `last night: @sami stacked 3 stones · 1 arrived · 2 fields went gold` from real rows only
  Keepers.tick() on the land        head-count milestones: 3 / 5 are recorded (`land_milestones`) and bump the bake when a keeper
                                    is on duty, else they wait (`land reached · keepers will open it next session`); 10 / 25 / 50
                                    (land strips) always wait in v1. RAISINGS: when land.ladder()["ready"] (20 / 60 / 150 stones)
                                    and a keeper is on duty, `Keepers.raising` = {name, x, y, t0, progress, plaque} runs RAISE_S
                                    seconds with at most one `raising_step` per second (reveal_rows(progress, h) = how many sprite
                                    rows the scene shows, bottom-up), every awake pip turns to the site, then land.add_raising()
                                    records it with the top three stackers; events `raising` / `raising_step` / `raising_ship`.
                                    `raising_line(now, ctx)` is the keeper strip's line while it goes up; `last_raised` after.
  Nothing here creates, moves or names a pip; every name passes the filter; the beacon lights on the heartbeat alone.
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
from stream.world.land import DEFAULT_MOOT  # noqa: E402

HEARTBEAT_FRESH_S = 120.0
FAIL_SHOW_S = 20.0
FLARE_S = 1.0
CARVE_S = 20.0                        # rock crumbles into a new chamber over this long (a build you can watch land)
CARVE_STEP_S = 0.5                    # terrain (and the static cave layer) is updated this often while carving
FAIL_LINES = 3
LINE_MAX = 60
# LONGGRASS (OPENWORLD.md 10)
RAISE_S = 20.0                        # a raising goes up over this long (survey stakes -> scaffold rows -> the finished sprite)
RAISE_STEP_S = 1.0                    # the reveal advances at most 1 Hz (nothing flashes above 1 Hz)
LAND_MILESTONES: Dict[int, str] = {3: "the cairn", 5: "the hearth ring", 10: "the Coast", 25: "the Birch Wood", 50: "the Tarn"}
LAND_STRIP_MILESTONES = (10, 25, 50)  # open a 320x440 strip: v1.1 keeper ships; they WAIT in v1
RAISING_SITES = {                     # place key + cell offset from it (the scene may refine to the nearest passable cell)
    "the Ford bridge": ("ford", (0, 0)),
    "the well": ("moot", (14, -6)),
    "the hall": ("moot", (-24, 10)),
}
KEEPER_RULE_LAND = "the keepers are AI agents. they raise this land live, from your !ideas, and you watch it go up."
HONESTY_LINE_LAND = ("no camera, no mic, no fake viewers. every name on this land is a real person in chat. "
                     "the wind is just the wind.")

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


def beacon_state(ctx, now: float, moot: Optional[Tuple[float, float]] = None) -> Dict[str, Any]:
    """OPENWORLD.md 10: the beacon on its post at the Moot, from the SAME heartbeat test as the strip and the minimap
    dot. lantern_state() plus the post's cell position and `minimap_dot` (an amber dot at the Moot only while lit)."""
    st = lantern_state(ctx, now)
    mx, my = (float(moot[0]), float(moot[1])) if moot else (float(DEFAULT_MOOT[0]), float(DEFAULT_MOOT[1]))
    st.update({"x": mx + 6.0, "y": my - 10.0, "minimap_dot": bool(st["on_duty"]), "lit": st["state"] in ("lit", "carving", "flare"),
               "swing": st["sway"], "kind": "beacon"})
    return st


def keeper_lines(ctx, now: float, name_filter: Optional[Callable[[str], Optional[str]]] = None, keepers: "Optional[Keepers]" = None,
                 run_dir: Optional[str] = None, land: Optional[bool] = None) -> Dict[str, Any]:
    """The keeper strip (WORLD.md 5 region 7 / OPENWORLD.md 8 row 7) in plain words. `fail_lines` is non-empty ONLY
    while a build failure is fresh (<= 20 s). `header` is the header_center line during a build (`keeper carving ·
    12:40 left`, `keeper raising · 12:40 left` on the land), else None. `land` picks the copy set; None = ask the
    keepers (their scene), else the cave's words."""
    nf = name_filter if isinstance(name_filter, _NameFilter) else _NameFilter(name_filter, getattr(keepers, "scene", None), run_dir)
    if land is None:
        land = bool(keepers is not None and keepers.land_mode)
    lan = lantern_state(ctx, now)
    mac = getattr(ctx, "macro", None) or {}
    lr = mac.get("last_reload") or {}
    verb, past, noun = ("raising", "raised", "raising") if land else ("carving", "carved", "build")
    if land:
        line1 = "keeper on duty · beacon lit" if lan["on_duty"] else "no keeper on duty · notices kept for next time"
    else:
        line1 = "keeper on duty" if lan["on_duty"] else "no keeper on duty · scrolls kept for next time"
    out: Dict[str, Any] = {"line1": line1, "line2": None, "fail_lines": [], "header": None, "ticker": None, "lantern": lan, "land": land}
    who = nf(mac.get("requested_by"), ctx)
    asked = (" · asked by @%s" % who) if who else ""
    own = None
    if keepers is not None:
        own = keepers.raising_line(now, nf, ctx) if land else keepers.carving_line(now, nf, ctx)
    last_own = (keepers.last_raised if land else keepers.last_carved) if keepers is not None else None
    if mac.get("active"):
        dl = iso_to_epoch(mac.get("deadline_ts"))
        left = (" · %s left" % _mmss(dl - now)) if dl is not None and dl >= now else (" · overdue" if dl is not None else "")
        out["line2"] = _clip("%s: %s%s%s" % (verb, mac.get("title") or ("something new" if not land else "a new raising"), asked, left))
        out["header"] = "keeper %s%s" % (verb, left)
    elif own is not None:
        out["line2"] = own["line"]
        out["header"] = own["header"]
    elif lr.get("ts") and (last_own is None or (iso_to_epoch(lr.get("ts")) or 0.0) >= last_own["t"]):
        title = mac.get("title") or (lr.get("module") and os.path.basename(str(lr.get("module")))) or ("the last %s" % noun)
        if lr.get("ok"):
            ver = _last_macro_version(ctx) or _version(ctx)
            out["line2"] = _clip("last %s: %s · %s%s" % (past, title, ver, asked))
        else:
            out["line2"] = _clip("last %s failed: %s%s" % (noun, title, asked))
            since = lan["since_reload_s"]
            if since is not None and 0.0 <= since <= FAIL_SHOW_S:
                err = str(lr.get("error") or "no error text recorded")
                lines = [ln.strip() for ln in err.replace("\r", "").split("\n") if ln.strip()][:FAIL_LINES]
                out["fail_lines"] = [_clip(ln) for ln in lines] + ["reverting to %s" % _version(ctx)]
    elif last_own is not None:
        lc = last_own
        if land:
            names = [nf(k, ctx) for k in (lc.get("plaque") or [])]
            names = ["@%s" % n for n in names if n]
            out["line2"] = _clip("last raised: %s · %s%s" % (lc["name"], lc["version"], (" · stones by %s" % " ".join(names)) if names else ""))
        else:
            who_c = nf(lc.get("by"), ctx) if lc.get("by") else None
            out["line2"] = _clip("last carved: %s · %s%s" % (lc["name"], lc["version"], (" · opened by @%s's hatch" % who_c) if who_c else ""))
    elif land and keepers is not None and keepers.waiting_raising is not None:
        stock = getattr(keepers.land, "stock", None)
        out["line2"] = _clip("%s%s waits for a keeper" % (("%d stones: " % stock) if stock else "", keepers.waiting_raising))
    elif keepers is not None and keepers.waiting is not None:
        if land:
            m = int(keepers.waiting)
            if m in LAND_STRIP_MILESTONES:
                out["line2"] = "land reached · keepers will open %s next session" % land_name(m)
            else:
                out["line2"] = "%d have walked here · keepers will set %s next session" % (m, land_name(m))
        else:
            out["line2"] = "milestone reached · keepers will carve %s next session" % chamber_name(keepers.waiting)
    else:
        out["line2"] = ("nothing raised yet · !idea <text> pins a notice to the board" if land
                        else "nothing carved yet · !idea <text> pins a scroll for the keepers")
    if keepers is not None and keepers.last_ticker and now - keepers.last_ticker_t < 30.0:
        out["ticker"] = keepers.last_ticker
    return out


def land_name(m: int) -> str:
    return LAND_MILESTONES.get(int(m), "the land beyond %d" % int(m))


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


NOTICE_LABELS = {
    "declined": ("declined", "grey"),
    "shipped": ("raised", "accent"),
    "ballot": ("on the waystones now", "accent"),
    "instant": ("instant · a waystone option next round", "accent"),
    "macro": ("raising next", "accent"),
    "pending": ("pinned to the board", "text"),
}


def classify_notice(idea: Dict[str, Any], ctx=None) -> Dict[str, str]:
    """Land terms for one state.ideas[] entry (the board on the Moot; OPENWORLD.md 10)."""
    status = str(idea.get("status") or "open")
    cls = str(idea.get("class") or "pending")
    if status == "declined" or cls == "declined":
        reason = _clip(str(idea.get("reason") or "no reason given"), 40)
        return {"label": "declined: %s" % reason, "tone": "grey", "cls": "declined"}
    if status == "shipped":
        return {"label": "raised · %s" % _version(ctx) if ctx is not None else "raised", "tone": "accent", "cls": "shipped"}
    if status == "failed":
        return {"label": "raising failed · kept for next time", "tone": "grey", "cls": "failed"}
    if status == "ballot":
        return {"label": NOTICE_LABELS["ballot"][0], "tone": "accent", "cls": "ballot"}
    if cls in ("instant", "macro"):
        lab, tone = NOTICE_LABELS[cls]
        return {"label": lab, "tone": tone, "cls": cls}
    return {"label": NOTICE_LABELS["pending"][0], "tone": "text", "cls": "pending"}


def notices(ctx, n: int = 3, name_filter: Optional[Callable[[str], Optional[str]]] = None, run_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Up to `n` notices on the Moot board: open/queued/ballot first (newest first), then the newest declined. Names
    filtered (None under !kill). Same rows as scrolls(), land words."""
    nf = name_filter if isinstance(name_filter, _NameFilter) else _NameFilter(name_filter, None, run_dir)
    ideas = [i for i in (getattr(ctx, "ideas", None) or []) if isinstance(i, dict) and (i.get("text") or "").strip()]
    live = [i for i in ideas if i.get("status") in ("open", "queued", "ballot")]
    done = [i for i in ideas if i.get("status") in ("declined", "shipped", "failed")]
    live.sort(key=lambda i: iso_to_epoch(i.get("ts")) or 0.0, reverse=True)
    done.sort(key=lambda i: iso_to_epoch(i.get("ts")) or 0.0, reverse=True)
    out = []
    for i in (live + done)[:n]:
        c = classify_notice(i, ctx)
        out.append({"id": str(i.get("id")), "text": _clip(str(i.get("text")), 60), "by": nf(i.get("by"), ctx),
                    "label": c["label"], "tone": c["tone"], "cls": c["cls"], "plus": int(i.get("plus") or 0)})
    return out


def ladder_line(land, nf: Optional[Callable] = None, ctx=None) -> Optional[str]:
    """The stone ladder for the land strip (OPENWORLD.md 8 row 6): `stone 13 of 20 · the Ford bridge · last by @kai`;
    None until a real stone lies on the cairn (a `0 of 20` would advertise a verb nobody used)."""
    if land is None:
        return None
    try:
        lad = land.ladder()
    except Exception:
        return None
    if not lad.get("stock"):
        return None
    if lad.get("next") is None:
        return "every raising stands · %d stones on the cairn" % int(lad["stock"])
    who = nf(lad.get("last_by"), ctx) if (nf is not None and lad.get("last_by")) else None
    return _clip("stone %d of %d · %s%s" % (int(lad["stock"]), int(lad["next"]), lad.get("name") or "the next raising",
                                            (" · last by @%s" % who) if who else ""), 72)


def nightly_board(scene, now: float, nf: Optional[Callable] = None, ctx=None, session_started: Optional[float] = None) -> Optional[str]:
    """`last night: @sami stacked 3 stones · 1 arrived · 2 fields went gold` from world.json rows only (stones by ts,
    pips by first_seen_ts, fields by stage). Names filtered. None when nothing happened or no land."""
    w = getattr(scene, "world", None)
    land = getattr(w, "land", None) if w is not None else None
    if land is None:
        return None
    try:
        sessions = list((w.data.get("sessions") or []))
        if len(sessions) < 2:
            return None
        prev = sessions[-2]
        t0 = w.epoch(prev.get("started_ts")) or w.epoch(prev.get("ts")) or 0.0
        t1 = w.epoch(prev.get("ended_ts")) or w.epoch(prev.get("last_ts")) or w.epoch(sessions[-1].get("started_ts")) or now
        segs = []
        stacked: Dict[str, int] = {}
        for s in land.stones:
            ts = w.epoch(s.get("ts")) or 0.0
            if t0 <= ts <= t1:
                stacked[s["by"]] = stacked.get(s["by"], 0) + 1
        if stacked:
            k, n = max(stacked.items(), key=lambda kv: (kv[1], kv[0]))
            who = nf(k, ctx) if nf is not None else k
            if who:
                segs.append("@%s stacked %d stone%s" % (who, n, "" if n == 1 else "s"))
        arrived = sum(1 for p in w.pips.values() if not p.get("_test") and t0 <= (w.epoch(p.get("first_seen_ts")) or -1) <= t1)
        if arrived:
            segs.append("%d arrived" % arrived)
        gold = land.fields_gold(now)
        if gold:
            segs.append("%d field%s went gold" % (gold, "" if gold == 1 else "s"))
        return _clip("last night: " + " · ".join(segs), 80) if segs else None
    except Exception:
        return None


# ---------------------------------------------------------------------------- colony bar copy
def land_bar(walked: int, keepers: "Optional[Keepers]" = None, ladder: Optional[List[int]] = None) -> Dict[str, Any]:
    """`17 have walked here · 8 more until the Coast opens` plus the bar fraction (real numbers only; OPENWORLD.md 8 row 6)."""
    walked = int(walked)
    ladder = ladder or MILESTONES
    nxt = next_milestone(walked, ladder)

    def until(m: int) -> str:
        return ("%s opens" % land_name(m)) if m in LAND_STRIP_MILESTONES else ("%s is set" % land_name(m))

    if keepers is not None and keepers.waiting is not None:
        m = int(keepers.waiting)
        tail = "land reached · keepers will open it next session" if m in LAND_STRIP_MILESTONES else "keepers will set %s next session" % land_name(m)
        return {"text": "%d have walked here · %s" % (walked, tail), "fraction": 1.0, "next": m}
    if keepers is not None and keepers.raising is not None:
        return {"text": "%d have walked here · the keepers are raising %s" % (walked, keepers.raising["name"]), "fraction": 1.0, "next": nxt}
    if nxt is None:
        return {"text": "%d have walked here · every strip of land is open" % walked, "fraction": 1.0, "next": None}
    prev = 0
    for m in ladder:
        if m <= walked:
            prev = m
    frac = (walked - prev) / float(max(1, nxt - prev))
    if walked == 0:
        text = "nobody has walked here yet · %d until %s" % (nxt, until(nxt))
    else:
        text = "%d %s walked here · %d more until %s" % (walked, "has" if walked == 1 else "have", nxt - walked, until(nxt))
    return {"text": text, "fraction": max(0.0, min(1.0, frac)), "next": nxt}


def next_milestone(hatched: int, ladder: Optional[List[int]] = None) -> Optional[int]:
    for m in (ladder or MILESTONES):
        if int(hatched) < int(m):
            return int(m)
    return None


def colony_bar(hatched: int, keepers: "Optional[Keepers]" = None, ladder: Optional[List[int]] = None, land: Optional[bool] = None) -> Dict[str, Any]:
    """`3 have hatched here · 2 more until the Pool opens` plus the bar fraction (real numbers only). On the land
    (`land=True`, or the keepers' scene is the land) the words are land_bar()'s."""
    if land or (land is None and keepers is not None and keepers.land_mode):
        return land_bar(hatched, keepers, ladder)
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
        # LONGGRASS (OPENWORLD.md 10)
        self.raising: Optional[Dict[str, Any]] = None           # {"name", "x", "y", "t0", "progress", "plaque", "stock", "steps"}
        self.opening: Optional[Dict[str, Any]] = None           # land strips: v1.1 (kept for the strips' copy)
        self.waiting_raising: Optional[str] = None              # stones enough, no keeper on duty
        self._waiting_raising_announced: Optional[str] = None
        self.last_raised: Optional[Dict[str, Any]] = None       # {"name", "version", "plaque", "by", "t", "x", "y"}
        self.raisings_done = 0
        self.land_milestones_set = 0
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

    # -- which world
    @property
    def land_mode(self) -> bool:
        """True when the scene's world is LONGGRASS (schema 2 / a Land): raisings and the beacon instead of carves."""
        w = getattr(self.scene, "world", None)
        if w is None:
            return False
        if getattr(self.scene, "land", None) is not None:
            return True
        try:
            return int(getattr(w, "schema", 1) or 1) >= 2 and getattr(w, "land", None) is not None
        except Exception:
            return False

    @property
    def land(self):
        ld = getattr(self.scene, "land", None)
        if ld is None:
            w = getattr(self.scene, "world", None)
            ld = getattr(w, "land", None) if w is not None else None
        return ld

    def _moot(self) -> Tuple[float, float]:
        ld = self.land
        m = getattr(ld, "moot", None) if ld is not None else None
        if m is None:
            T = getattr(self.scene, "terrain", None)
            m = getattr(T, "site", None) if T is not None else None
        return (float(m[0]), float(m[1])) if m else (float(DEFAULT_MOOT[0]), float(DEFAULT_MOOT[1]))

    # -- per frame
    def tick(self, ctx, now: float) -> List[Dict[str, Any]]:
        self.ticks += 1
        scene = self.scene
        if not getattr(scene, "booted", False) or scene.world is None or scene.behaviour is None:
            return []
        evs: List[Dict[str, Any]] = []
        self._macro_events(ctx, now, evs)
        if self.land_mode:
            self._tick_land(ctx, now, evs)
            return evs
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

    def _look_at(self, x: float, y: Optional[float] = None) -> None:
        """Every awake pip turns toward (x, y) (the cave: left / right only). Never moves anyone."""
        for e in self.scene.behaviour.awake():
            try:
                if y is None:
                    e.facing = 1 if x >= e.x else -1
                else:
                    dx, dy = x - float(e.x), y - float(getattr(e, "y", 0.0))
                    fx = 0 if abs(dx) < 1e-6 else (1 if dx > 0 else -1)
                    fy = 0 if abs(dy) < 1e-6 else (1 if dy > 0 else -1)
                    e.facing = (fx, fy) if (fx or fy) else (1, 0)
            except Exception:
                continue

    # -- LONGGRASS: milestones (3 / 5 set, 10+ wait) and raisings from the stone ladder
    def _tick_land(self, ctx, now: float, evs: List[Dict[str, Any]]) -> None:
        w = self.scene.world
        land = self.land
        fresh = _fresh(ctx, now)
        # head-count milestones
        m = w.milestone_check()
        if m is not None:
            if m in LAND_STRIP_MILESTONES or not fresh:
                # strips are v1.1 keeper ships; 3 / 5 need a keeper on duty. Nothing is recorded until it happens.
                self.waiting = m
                if self._waiting_announced != m:
                    self._waiting_announced = m
                    evs.append({"type": "milestone_waiting", "milestone": m, "chamber": land_name(m), "name": land_name(m),
                                "count": w.hatched_ever, "land": True})
                    self.log("milestone %d reached (%d have walked here): %s waits %s" % (
                        m, w.hatched_ever, land_name(m), "for the strip module (v1.1)" if m in LAND_STRIP_MILESTONES else "for a keeper on duty"))
            else:
                by_key = self._crossing_key()
                mx, my = self._moot()
                w.mark_milestone(m, by_key, now)
                rows = w.data["world"].setdefault("land_milestones", [])
                if not any(r.get("milestone") == m for r in rows):
                    rows.append({"milestone": m, "name": land_name(m), "by": by_key, "ts": iso_to_epoch_inv(now), "version": _version(ctx)})
                if land is not None:
                    try:
                        land.bump_bake(land_name(m))
                    except Exception:
                        pass
                self.waiting = None
                self.land_milestones_set += 1
                shown = self.nf(by_key, ctx) if by_key else None
                self._look_at(mx, my)
                w.log_event("the keepers set %s%s · %d have walked here" % (land_name(m), (" · by @%s's arrival" % shown) if shown else "", w.hatched_ever), now)
                self.last_ticker = "the keepers set %s · %d have walked here" % (land_name(m), w.hatched_ever)
                self.last_ticker_t = now
                evs.append({"type": "milestone", "milestone": m, "chamber": land_name(m), "name": land_name(m), "by": by_key,
                            "count": w.hatched_ever, "carved": True, "land": True, "x": int(mx), "y": int(my)})
                self.log("milestone %d (%d have walked here): %s set" % (m, w.hatched_ever, land_name(m)))
        else:
            self.waiting = None
        # raisings from the stone ladder (20 / 60 / 150)
        if land is None:
            return
        if self.raising is None:
            try:
                lad = land.ladder()
            except Exception as ex:
                lad = {"ready": False}
            if lad.get("ready") and lad.get("name"):
                if fresh:
                    self._start_raising(lad, now, ctx, evs)
                else:
                    self.waiting_raising = lad["name"]
                    if self._waiting_raising_announced != lad["name"]:
                        self._waiting_raising_announced = lad["name"]
                        evs.append({"type": "raising_waiting", "name": lad["name"], "stock": lad.get("stock")})
                        self.log("%d stones: %s is ready; no keeper on duty, it waits" % (int(lad.get("stock") or 0), lad["name"]))
            else:
                self.waiting_raising = None
        if self.raising is not None:
            self._step_raising(now, ctx, evs)

    def raising_site(self, name: str) -> Tuple[int, int]:
        """Where a raising stands: the Ford centre for the bridge, beside the Moot for the well and the hall; snapped to
        the nearest passable cell when the terrain can say."""
        place_key, (ox, oy) = RAISING_SITES.get(name, ("moot", (0, 0)))
        T = getattr(self.scene, "terrain", None)
        x, y = self._moot()
        if place_key == "ford":
            fc = getattr(T, "ford_centre", None) if T is not None else None
            pl = getattr(T, "places", {}).get("ford") if T is not None else None
            if fc:
                x, y = float(fc[0]), float(fc[1])
            elif pl:
                x, y = float(pl["x"]), float(pl["y"])
        x, y = x + ox, y + oy
        if T is not None and place_key != "ford" and hasattr(T, "nearest_passable"):
            try:
                nx, ny = T.nearest_passable(int(round(x)), int(round(y)), r=24) or (x, y)
                x, y = float(nx), float(ny)
            except Exception:
                pass
        return int(round(x)), int(round(y))

    def _start_raising(self, lad: Dict[str, Any], now: float, ctx, evs: List[Dict[str, Any]]) -> None:
        land = self.land
        name = str(lad["name"])
        x, y = self.raising_site(name)
        plaque = [k for k, _n in land.plaque()]
        self.raising = {"name": name, "x": x, "y": y, "t0": now, "progress": 0.0, "plaque": plaque, "stock": int(lad.get("stock") or 0),
                        "at_stock": int(lad.get("next") or 0), "steps": 0, "last_step": -1e18, "index": int(lad.get("index") or 0)}
        self.waiting_raising = None
        self._look_at(float(x), float(y))
        shown = [self.nf(k, ctx) for k in plaque]
        shown = ["@%s" % s for s in shown if s]
        self.scene.world.log_event("keeper raising %s · %d stones%s" % (name, self.raising["stock"], (" · stones by %s" % " ".join(shown)) if shown else ""), now)
        evs.append({"type": "raising", "name": name, "x": x, "y": y, "duration_s": self.carve_s, "plaque": list(plaque),
                    "stock": self.raising["stock"], "index": self.raising["index"]})
        self.log("raising %s at (%d, %d): %d stones, plaque %s, over %.0f s" % (name, x, y, self.raising["stock"], plaque, self.carve_s))

    def _step_raising(self, now: float, ctx, evs: List[Dict[str, Any]]) -> None:
        r = self.raising
        progress = min(1.0, max(0.0, (now - r["t0"]) / max(0.1, self.carve_s)))
        if now - r["last_step"] >= RAISE_STEP_S or progress >= 1.0:
            if progress > r["progress"] or progress >= 1.0:
                r["last_step"] = now
                r["progress"] = progress
                r["steps"] += 1
                evs.append({"type": "raising_step", "name": r["name"], "progress": round(progress, 3), "x": r["x"], "y": r["y"]})
        if progress >= 1.0:
            land = self.land
            w = self.scene.world
            ver = _version(ctx)
            rec = None
            try:
                rec = land.add_raising(r["name"], ver, now, at_stock=r.get("at_stock"))
            except Exception as ex:
                self.log("land.add_raising failed: %r" % (ex,))
            plaque = list((rec or {}).get("plaque") or r["plaque"])
            shown = ["@%s" % s for s in (self.nf(k, ctx) for k in plaque) if s]
            tail = (" · stones by %s" % " ".join(shown)) if shown else ""
            w.log_event("%s raised · %s%s" % (r["name"], ver, tail), now)
            w.dirty = True
            try:
                w.save(now, force=True)
            except Exception as ex:
                self.log("save after raising failed: %r" % (ex,))
            self._look_at(float(r["x"]), float(r["y"]))
            self.last_ticker = "SHIPPED %s · %s raised%s" % (ver, r["name"], tail)
            self.last_ticker_t = now
            self.last_raised = {"name": r["name"], "version": ver, "plaque": plaque, "by": plaque[0] if plaque else None,
                                "t": now, "x": r["x"], "y": r["y"]}
            evs.append({"type": "raising_ship", "name": r["name"], "version": ver, "plaque": plaque, "x": r["x"], "y": r["y"],
                        "stock": r["stock"], "steps": r["steps"]})
            self.raisings_done += 1
            self.log("%s raised: %s, plaque %s, %d reveal steps" % (r["name"], ver, plaque, r["steps"]))
            self.raising = None

    @staticmethod
    def reveal_rows(progress: float, sprite_h: int) -> int:
        """How many rows of a raising's finished sprite are shown, bottom-up, at `progress` (the reveal mask)."""
        return int(round(max(0.0, min(1.0, progress)) * int(sprite_h)))

    def raising_line(self, now: float, nf=None, ctx=None) -> Optional[Dict[str, str]]:
        """The keeper strip's line while a raising goes up: `raising: the Ford bridge · 0:12 left · stones by @kai @sami`."""
        r = self.raising
        if r is None:
            return None
        nf = nf or self.nf
        left = max(0.0, r["t0"] + self.carve_s - now)
        shown = ["@%s" % s for s in (nf(k, ctx) for k in (r.get("plaque") or [])) if s]
        return {"line": _clip("raising: %s · %s left%s" % (r["name"], _mmss(left), (" · stones by %s" % " ".join(shown)) if shown else "")),
                "header": "keeper raising · %s left" % _mmss(left), "progress": r["progress"]}

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
        land = self.land_mode
        bx, by_ = self._moot() if land else (float(LANTERN_X), None)
        if self._macro_active is not None and active and not self._macro_active:
            self._look_at(bx, by_)
            evs.append({"type": "keeper_carving", "title": mac.get("title"), "by": mac.get("requested_by"), "land": land})
        self._macro_active = active
        lr = mac.get("last_reload") or {}
        ts = lr.get("ts")
        if ts and ts != self._macro_ts:
            if self._macro_ts is not None:                     # not the one we booted with
                self._look_at(bx, by_)
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
                "chambers_opened": self.chambers_opened, "attached": self._attached, "land": self.land_mode,
                "raising": None if self.raising is None else {k: self.raising[k] for k in ("name", "x", "y", "progress", "stock", "steps")},
                "waiting_raising": self.waiting_raising, "raisings_done": self.raisings_done, "land_milestones_set": self.land_milestones_set}


def iso_to_epoch_inv(t: float) -> str:
    from stream.state_store import epoch_to_iso
    return epoch_to_iso(t, ms=True)


# ---------------------------------------------------------------------------- self-test
import json  # noqa: E402


def _selftest(run_dir: str) -> int:
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

    # ---- G. LONGGRASS land mode: a real schema-2 WorldState + Land + terrain under a duck-typed scene (OPENWORLD.md 10)
    ok = _selftest_land(os.path.join(run_dir, "land"), t0, fps, mkctx, epoch_to_iso) and ok
    print("KEEPERS SELF-TEST %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def _selftest_land(run_dir: str, t0: float, fps: float, mkctx, epoch_to_iso) -> bool:
    from stream.world import terrain as TERR
    from stream.world.state import WorldState
    os.makedirs(run_dir, exist_ok=True)
    ok = True
    T = TERR.generate(4471)
    ws = WorldState(run_dir, schema=2, moot=(T.site[0], T.site[1]), passable=T.passable, water=T.water, now=t0)
    ws.data.setdefault("sessions", []).append({"id": "prev-night", "started_ts": epoch_to_iso(t0 - 7200), "last_ts": epoch_to_iso(t0 - 100)})
    ws.begin_session("keepers-land", t0)
    land = ws.land
    land.set_terrain_layers(T.passable, T.water, (T.site[0], T.site[1]))
    names = ["keepers-land-ana", "keepers-land-bo", "keepers-land-cy"]
    for i, nm in enumerate(names):
        ws.ensure_pip(nm, nm, nm, i + 1, t0 - 3600)
        ws.record_message(nm, t0 - 60, "keepers-land", "hello")
        ws.set_state(nm, "awake", T.site[0] + 8 * i, T.site[1] + 20, None, None)      # hatched: counts in hatched_ever

    class _E(object):
        def __init__(self, key, x, y):
            self.key, self.x, self.y, self.state = key, float(x), float(y), "awake"
            self._f = (1, 0)

        def is_awake(self):
            return True

        @property
        def facing(self):
            return self._f

        @facing.setter
        def facing(self, v):
            self._f = tuple(v) if isinstance(v, (tuple, list)) else (int(v), 0)

    class _B(object):
        def __init__(self):
            self.ents = [_E(nm, T.site[0] + 8 * i, T.site[1] + 20) for i, nm in enumerate(names)]

        def awake(self):
            return list(self.ents)

    class _S(object):
        def __init__(self):
            self.booted, self.frames, self.world, self.land, self.behaviour, self.terrain = True, 0, ws, land, _B(), T
            self.events: List[Dict[str, Any]] = []
            self.run_dir = run_dir
            self._last_now = t0

        def frame(self, ctx, size):
            self.frames += 1
            self.events = []
            self._last_now = ctx.now
            return None

    sc = _S()
    keep = Keepers(sc, carve_s=2.0).attach()
    print("[G] land_mode=%s moot=%s" % (keep.land_mode, keep._moot()))
    if not keep.land_mode:
        print("FAIL G land_mode"); ok = False
    # G1: the beacon from the heartbeat alone
    b_on, b_off = beacon_state(mkctx(t0, 0, hb=epoch_to_iso(t0)), t0, moot=T.site), beacon_state(mkctx(t0, 0, hb=None), t0, moot=T.site)
    print("[G1] beacon lit=%s dot=%s state=%s (x %.0f y %.0f) | dark: lit=%s dot=%s state=%s" % (
        b_on["lit"], b_on["minimap_dot"], b_on["state"], b_on["x"], b_on["y"], b_off["lit"], b_off["minimap_dot"], b_off["state"]))
    if not (b_on["lit"] and b_on["minimap_dot"] and not b_off["lit"] and not b_off["minimap_dot"] and b_off["state"] == "dark"):
        print("FAIL G1 beacon"); ok = False
    # G2: milestone 3 (three real pips) WAITS with no keeper, is SET with one; strips (10+) always wait
    evs: Dict[str, int] = {}
    now = t0
    for i in range(10):
        now += 1.0 / fps
        sc.frame(mkctx(now, i, hb=None), (1280, 440))
        for e in sc.events:
            evs[e["type"]] = evs.get(e["type"], 0) + 1
    kl0 = keeper_lines(mkctx(now, 0, hb=None), now, keepers=keep)
    bar0 = colony_bar(ws.hatched_ever, keep)
    print("[G2] no keeper: waiting=%r events=%r line1=%r line2=%r bar=%r" % (keep.waiting, evs, kl0["line1"], kl0["line2"], bar0["text"]))
    if keep.waiting != 3 or ws.data["world"].get("milestones_reached") or evs.get("milestone_waiting") != 1:
        print("FAIL G2 waiting"); ok = False
    if kl0["line1"] != "no keeper on duty · notices kept for next time" or kl0["line2"] != "3 have walked here · keepers will set the cairn next session":
        print("FAIL G2 copy"); ok = False
    if bar0["text"] != "3 have walked here · keepers will set the cairn next session" or not kl0["land"]:
        print("FAIL G2 bar"); ok = False
    hb = epoch_to_iso(now)
    evs = {}
    for i in range(10):
        now += 1.0 / fps
        sc.frame(mkctx(now, i, hb=hb), (1280, 440))
        for e in sc.events:
            evs[e["type"]] = evs.get(e["type"], 0) + 1
    lm = ws.data["world"].get("land_milestones") or []
    bar1 = colony_bar(ws.hatched_ever, keep)
    faced = [e.facing for e in sc.behaviour.ents]
    print("[G2] keeper on duty: milestones_reached=%r land_milestones=%r events=%r ticker=%r bar=%r faced=%r" % (
        ws.data["world"].get("milestones_reached"), [(r["milestone"], r["name"], r["by"]) for r in lm], evs, keep.last_ticker, bar1["text"], faced))
    if ws.data["world"].get("milestones_reached") != [3] or not lm or lm[0]["name"] != "the cairn" or evs.get("milestone") != 1 or lm[0]["by"] not in names:
        print("FAIL G2 set"); ok = False
    if bar1["text"] != "3 have walked here · 2 more until the hearth ring is set" or keep.waiting is not None:
        print("FAIL G2 bar after"); ok = False
    if not all(isinstance(f, tuple) and len(f) == 2 for f in faced):
        print("FAIL G2 facing"); ok = False
    # G3: 20 stones -> the ladder is ready; no keeper -> the raising waits (copy), keeper -> raised over carve_s at <= 1 Hz steps
    for i in range(20):
        rec, why = land.stack(names[i % 3], now - 3600 + i)
        assert rec is not None, why
    ll0 = ladder_line(land, keep.nf, mkctx(now, 0))
    evs = {}
    for i in range(10):
        now += 1.0 / fps
        sc.frame(mkctx(now, i, hb=None), (1280, 440))
        for e in sc.events:
            evs[e["type"]] = evs.get(e["type"], 0) + 1
    klw = keeper_lines(mkctx(now, 0, hb=None), now, keepers=keep)
    print("[G3] 20 stones, no keeper: ladder=%r line=%r waiting_raising=%r events=%r line2=%r" % (
        land.ladder(), ll0, keep.waiting_raising, evs, klw["line2"]))
    if keep.waiting_raising != "the Ford bridge" or keep.raising is not None or evs.get("raising_waiting") != 1:
        print("FAIL G3 waiting"); ok = False
    if klw["line2"] != "20 stones: the Ford bridge waits for a keeper" or ll0 is None or not ll0.startswith("stone 20 of 20 · the Ford bridge · last by @"):
        print("FAIL G3 copy"); ok = False
    hb = epoch_to_iso(now)
    evs = {}
    steps: List[Tuple[float, float]] = []
    mid = None
    n = int(2.0 * fps) + 15
    for i in range(n):
        now += 1.0 / fps
        ctx = mkctx(now, i, hb=hb)
        sc.frame(ctx, (1280, 440))
        for e in sc.events:
            evs[e["type"]] = evs.get(e["type"], 0) + 1
            if e["type"] == "raising_step":
                steps.append((round(now - t0, 2), e["progress"]))
        if i == 30:
            mid = keeper_lines(ctx, now, keepers=keep)
    rs = land.raisings
    after = keeper_lines(mkctx(now, 0, hb=hb), now, keepers=keep)
    gaps = [round(b[0] - a[0], 2) for a, b in zip(steps[:-1], steps[1:])]
    print("[G3] keeper on duty: events=%r steps=%r gaps=%r" % (evs, steps, gaps))
    print("[G3] raisings=%r ladder=%r" % ([(r["name"], r["version"], r["at_stock"], r["plaque"]) for r in rs], land.ladder()))
    print("[G3] mid strip: %r | after: %r | ticker=%r" % ({k: mid[k] for k in ("line1", "line2", "header")}, after["line2"], keep.last_ticker))
    print("[G3] reveal rows at 0 / 0.5 / 1 of a 48-row sprite: %r; site=%r" % (
        [Keepers.reveal_rows(pv, 48) for pv in (0.0, 0.5, 1.0)], (rs[0]["name"], keep.last_raised["x"], keep.last_raised["y"]) if rs else None))
    if evs.get("raising") != 1 or evs.get("raising_ship") != 1 or len(rs) != 1 or rs[0]["name"] != "the Ford bridge" or rs[0]["at_stock"] != 20:
        print("FAIL G3 raising"); ok = False
    if not steps or min(gaps or [1.0]) < RAISE_STEP_S - 1.0 / fps or steps[-1][1] != 1.0 or len(steps) > int(2.0 / RAISE_STEP_S) + 2:
        print("FAIL G3 step rate (<= 1 Hz)"); ok = False
    if sorted(rs[0]["plaque"]) != sorted(names) or keep.last_raised is None or keep.last_raised["plaque"] != rs[0]["plaque"]:
        print("FAIL G3 plaque"); ok = False
    if mid is None or mid["header"] is None or not mid["line2"].startswith("raising: the Ford bridge · 0:0") or "stones by @" not in mid["line2"]:
        print("FAIL G3 mid copy"); ok = False
    if not after["line2"].startswith("last raised: the Ford bridge · v0.5.0 · stones by @") or not (keep.last_ticker or "").startswith("SHIPPED v0.5.0 · the Ford bridge raised"):
        print("FAIL G3 after copy"); ok = False
    ll1 = ladder_line(land, keep.nf, mkctx(now, 0))
    if not (ll1 or "").startswith("stone 20 of 60 · the well · last by @"):
        print("FAIL G3 ladder after: %r" % ll1); ok = False
    if not T.is_passable(keep.last_raised["x"], keep.last_raised["y"]) and (keep.last_raised["x"], keep.last_raised["y"]) != tuple(T.ford_centre):
        print("FAIL G3 site"); ok = False
    # G4: notices in land terms; !kill hides names; board from real rows; the on-disk world carries the raising
    ideas = [
        {"id": "i-0001", "text": "rain more often", "by": names[0], "ts": epoch_to_iso(now - 100), "plus": 2, "class": "instant", "status": "queued", "reason": None},
        {"id": "i-0002", "text": "a mill on the river", "by": names[1], "ts": epoch_to_iso(now - 90), "plus": 0, "class": "macro", "status": "queued", "reason": None},
        {"id": "i-0003", "text": "add wolves", "by": names[2], "ts": epoch_to_iso(now - 80), "plus": 0, "class": "declined", "status": "declined", "reason": "no animate non-persons"},
        {"id": "i-0004", "text": "fog tonight", "by": names[0], "ts": epoch_to_iso(now - 70), "plus": 0, "class": "pending", "status": "open", "reason": None},
        {"id": "i-0005", "text": "on the stones", "by": names[1], "ts": epoch_to_iso(now - 60), "plus": 1, "class": "instant", "status": "ballot", "reason": None},
    ]
    nt = notices(mkctx(now, 0, ideas=ideas), n=5, run_dir=run_dir)
    for s in nt:
        print("[G4] notice %s by @%s: %r -> %s (%s)" % (s["id"], s["by"], s["text"], s["label"], s["tone"]))
    labels = {s["id"]: s["label"] for s in nt}
    if labels.get("i-0001") != "instant · a waystone option next round" or labels.get("i-0002") != "raising next":
        print("FAIL G4 instant/macro"); ok = False
    if labels.get("i-0003") != "declined: no animate non-persons" or labels.get("i-0004") != "pinned to the board" or labels.get("i-0005") != "on the waystones now":
        print("FAIL G4 declined/pending/ballot"); ok = False
    if any(s["by"] is not None for s in notices(mkctx(now, 0, ideas=ideas, chat_display=False), n=5, run_dir=run_dir)):
        print("FAIL G4 !kill names"); ok = False
    board = nightly_board(sc, now, keep.nf, mkctx(now, 0))
    print("[G4] board: %r" % (board,))
    if not board or not board.startswith("last night: @keepers-land-") or "stacked 7 stones" not in board or "3 arrived" not in board:
        print("FAIL G4 board"); ok = False
    viol = land.provenance_violations()
    saved = json.load(open(os.path.join(run_dir, "world.json")))
    print("[G4] provenance violations=%r; world.json schema=%s raisings=%d stones=%d land_milestones=%d" % (
        viol, saved.get("schema"), len(saved["world"].get("raisings") or []), len(saved["world"].get("stones") or []), len(saved["world"].get("land_milestones") or [])))
    if viol or saved.get("schema") != 2 or len(saved["world"].get("raisings") or []) != 1 or len(saved["world"].get("stones") or []) != 20:
        print("FAIL G4 disk"); ok = False
    for h in (0, 1, 4, 12, 60):
        print("[G5] walked=%d -> %r" % (h, land_bar(h)))
    if land_bar(0)["text"] != "nobody has walked here yet · 3 until the cairn is set" or land_bar(12)["text"] != "12 have walked here · 13 more until the Birch Wood opens":
        print("FAIL G5"); ok = False
    print("[G] keepers stats=%r errors=%d" % (keep.stats(), keep.errors))
    if keep.errors:
        print("FAIL G errors"); ok = False
    return ok


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        sys.exit(_selftest(os.environ.get("RUN_DIR") or "/tmp/pip-keepers-k"))
    print(__doc__)
