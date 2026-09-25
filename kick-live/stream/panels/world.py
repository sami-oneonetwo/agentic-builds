"""stream/panels/world.py - the WORLD region (0,72,1280,440): CaveScene frame + the screen-scale TEXT LAYER.

WORLD.md 5 row 5, 2.2, 10, 11; contract in stream/WORLD_API.md. The scene (stream/scenes/hollow.py) draws the cave,
the glow and every pip sprite and NO text. This panel calls `SCENE.frame(ctx, size)` once per frame and draws, at
screen scale (nothing under 20 px, every string cached as an RGBA strip):

  plank        HN Medium 22 at region (16, 12) (canvas 16, 84): event notices (4-10 s), verb refusals (ctx.notice),
               first light `@name woke the Hollow · HH:MM`, zero-vote amber line under 30 s, `!help` legend, then
               an 8 s idle rotation: the one-line pitch / `N pips sleep here. nobody awake. say anything and yours
               wakes.` / `nobody has hatched here yet...` / the LAST FIVE REAL VISITORS with real timestamps
  pip labels   Menlo 20 `@name` in the pip's hashed colour, centred above each awake pip; drawn ONLY for entities the
               scene hands over with a display_name (a seed has none: the 3 s hold + blocklist path lives in the
               scene / ChatBridge, never here); sleepers labelled one at a time on a 5 s rotation with a real
               `last seen`; `Muffin (@sam)` when a nickname exists (the @name never disappears)
  bubbles      Menlo 22 in a #11151D box, 1 px #1C2130 border, max 408 px wide, 3 lines, 6 s, ONE per pip: the
               owner's own moderated text (or `learned · from @src`); a returning pip's care log rides in the same
               bubble as a first line (`back after 2 nights · fed by @kai x2`)
  platforms    AB 56 letter carved (dim) above each stone platform, the count Menlo 22 = len(pips standing there),
               the last 3 standing names Menlo 20 under it (a standing pip has no floating label: the row is it)
  moss labels  Menlo 20 `moss · @name · night 3` on a 5 s rotation
  hatch tags   `#N` (the real builder number) under a fresh pip for 3 s; `you are the only light in the cave.` 10 s
  degrade      obeys scene.degrade: labels_on_speak (also above 40 awake, WORLD.md 5), bubbles_single (one shared
               line at the bottom of the world); the readout shows `world: glow off`
  !kill        ctx.chat_display False -> no name anywhere in this region; bubbles read `chat hidden by mod`

Honesty (WORLD.md 11): every name drawn here comes from `scene.entities()` (display_name already filtered) or from a
`world.json` pip record's `display_name` via `shown_name()`. No string in this file names a person. Every count is
a len() the scene computed. `stats()["honesty_violations"]` counts any drawn name whose key is not a world pip.

The panel never returns a placeholder: any text-layer error returns the scene frame bare (one stderr line per burst);
a scene error is already the scene's last good frame. `budget_ms = 24` (WORLD_API 7). Hot reload: the CaveScene
instance is parked on the `stream.panels` package (`_WORLD_SCENE`), so a reload of THIS file keeps the entities
when the scene class is unchanged, and a reload of stream/scenes/hollow.py (which re-executes this module too)
makes a fresh scene from the new class, re-booted from world.json.
"""
from __future__ import annotations

import os
import re
import sys
import time as _time
import traceback
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from stream import layout as L
from stream import panels as _PKG
from stream.panels import Panel, register
from stream.state_store import iso_to_epoch
from stream.scenes import hollow as H
from stream.world import pips as P
from stream.world import keepers as K
from stream.world.honesty import HonestyMonitor
from stream.world.state import PLATFORMS, PLATFORM_LETTERS

PLANK_XY = getattr(L, "WORLD_PLANK_XY", (16, 12))
PLANK_ROW2_DY = 40                    # a second plank row: the newcomer's sticky line when an ack / refusal holds row 1
BUBBLE_MAX_W = getattr(L, "WORLD_BUBBLE_MAX_W", 408)
DENSITY_FALLBACK = getattr(L, "WORLD_DENSITY_FALLBACK", 40)
LABEL_FONT, LABEL_SIZE, LABEL_H = "Menlo", 20, 24
BUBBLE_FONT, BUBBLE_SIZE, BUBBLE_LINE_H, BUBBLE_PAD = "Menlo", 22, 26, 10
PLANK_FONT, PLANK_SIZE = "HN Medium", 22
PLANK_MAX_W = 820                     # the plank ends before the cave mouth / lantern column
ROTATE_S = 8.0
SLEEPER_ROTATE_S = 5.0
MOSS_ROTATE_S = 5.0
NOTICE_S = 4.0
FIRST_LIGHT_S = 10.0
LEGEND = ("feed · pet · dig · plant   (exact word, or with @name)", "A / B / C = walk your pip to a platform",
          "!idea <text> = a scroll for the keepers", "!theme <preset> = change the light", "!stats · !help")
LEGEND_ITEM_S = 5.0
TEXT_CACHE_MAX = 1400
STATS_EVERY = 300
PLATFORM_TITLE_Y = 184                # Menlo 20 option title (WORLD.md 8.1 `title on the platform`) above the carved letter
PLATFORM_LETTER_Y = 210               # AB 56 glyph bottom lands at region y 273; a standing tier-3 sprite starts at 292
PLATFORM_COUNT_Y = 245
PLATFORM_NAMES_Y = 276
PLATFORM_NAMES_MAX_W = 400            # the platform's own width: up to 3 names untruncated, else `N standing` (never `@quietnood…`)
PLATFORM_TITLE_MAX_W = 340
GUTTER = 16                           # sleeper labels and platform titles never touch the region edge (art-rules 4)
ALONE_PROMPT_S = 45.0                 # one awake pip and no second chatter for this long -> the loneliness plank (WORLD.md 10)
SLEEPERS_LIT_S = 5.0                  # `anyone` / `here` from a lone chatter lights every sleeper's label this long
PLATFORM_CLUSTER_PX = 40              # a pip this close to an occupied platform's crowd gets no floating label (the row is it)
LABEL_STEP = 22                       # de-collision step for labels / care lines (max 3 steps, then label-on-speak)
LABEL_MAX_STEPS = 3
SOIL_LABEL_Y = 372                    # moss labels live in the soil band (region y 368-440 = canvas 440-512), never at pip height
PRIO_EVENT, PRIO_VERB, PRIO_LIGHT, PRIO_YOU, PRIO_CREDITS = 1, 2, 3, 4, 5   # plank priority: the person outranks the world


_LONELY_RE = re.compile(r"\b(anyone|anybody|here|hello|alone|else|nobody|empty|dead)\b", re.IGNORECASE)


def _ordinal(n: int) -> str:
    n = int(n)
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "%d%s" % (n, suf)


def _log(msg: str) -> None:
    try:
        sys.stderr.write("world-panel: %s\n" % msg)
        sys.stderr.flush()
    except Exception:
        pass


def _blend(hex_a: str, hex_b: str, t: float) -> Tuple[int, int, int]:
    a, b = L.hex_rgb(hex_a), L.hex_rgb(hex_b)
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


# ----------------------------------------------------------------------------- the scene instance (survives reloads)
def _run_dir() -> str:
    """--run-dir from the compositor's argv wins (it is not exported to the environment), then $RUN_DIR."""
    argv = sys.argv or []
    for i, a in enumerate(argv):
        if a == "--run-dir" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--run-dir="):
            return a.split("=", 1)[1]
    return os.environ.get("RUN_DIR") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "run")


def _attach_tenders(sc: H.CaveScene) -> None:
    """The keepers (milestone carves, keeper-build announcements; wraps scene.frame, idempotent) and the honesty
    monitor (every frame after the scene: forged entities removed, counts/names/text cross-checked against the real
    records). Both live on the scene instance so a panel-only reload finds them already attached."""
    if getattr(sc, "keepers", None) is None:
        try:
            K.Keepers(sc, log=lambda m: _log("keepers: %s" % m)).attach()
        except Exception as e:
            _log("keepers not attached: %r" % (e,))
    if getattr(sc, "honesty", None) is None:
        try:
            sc.honesty = HonestyMonitor(sc, enforce=True, log=lambda m: _log("honesty: %s" % m))
        except Exception as e:
            _log("honesty monitor not attached: %r" % (e,))


def _make_scene() -> H.CaveScene:
    prev = getattr(_PKG, "_WORLD_SCENE", None)
    if prev is not None and type(prev) is H.CaveScene:       # same class object: a panel-only reload keeps the colony
        sc = prev
    else:
        sc = H.CaveScene(run_dir=_run_dir(), log=lambda m: _log("scene: %s" % m))
        _PKG._WORLD_SCENE = sc
    _attach_tenders(sc)
    return sc


SCENE = _make_scene()


def scene() -> H.CaveScene:
    """The live CaveScene (other panels read counts and names through this; never construct a second one)."""
    return getattr(_PKG, "_WORLD_SCENE", None) or SCENE


def keepers() -> Optional[K.Keepers]:
    """The Keepers attached to the live scene (colony / keeper strips read carve state through this)."""
    return getattr(scene(), "keepers", None)


def world_degrade() -> Optional[Dict[str, Any]]:
    """scene.degrade (glow / labels_on_speak / bubbles_single / level) or None before boot (readout: `world: glow off`)."""
    sc = scene()
    return dict(sc.degrade) if (sc is not None and sc.booted) else None


def honesty_line() -> Optional[str]:
    mon = getattr(scene(), "honesty", None)
    return mon.line() if mon is not None else None


def honesty_summary() -> Optional[Dict[str, Any]]:
    mon = getattr(scene(), "honesty", None)
    return mon.summary() if mon is not None else None


def world_counts() -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """(awake, asleep, hatched_ever) as len() over the scene's real records, or (None, None, None) before boot."""
    sc = scene()
    if sc is None or not sc.booted:
        return None, None, None
    return sc.awake_count(), sc.asleep_count(), sc.hatched_ever()


def shown_name(raw: Optional[str]) -> Optional[str]:
    """The filtered display name for a username: the pip record's stored display_name (blocklist -> `builder #N`)
    or, for a name with no pip yet, the world's name filter. None before boot (then draw nothing)."""
    if not raw:
        return None
    sc = scene()
    if sc is None or not sc.booted or sc.world is None:
        return None
    key = str(raw).lower().lstrip("@")
    p = sc.world.pip(key)
    if p is not None:
        return p.get("display_name") or ("builder #%s" % (p.get("n") if p.get("n") is not None else "?"))
    try:
        s = sc.world.name_filter(str(raw).lstrip("@"))
    except Exception:
        return None
    return L.strip_non_bmp(str(s)) if s else None


def shown_name_cleared(raw: Optional[str]) -> Optional[str]:
    """The filtered display name of a chatter who has a pip RECORD (records are created only from moderated records past
    the 3 s hold, so this can never show a name inside its hold); None for anyone else. The chat log's shield row uses
    this for the mod's name; targets are never named there."""
    if not raw:
        return None
    sc = scene()
    if sc is None or not sc.booted or sc.world is None:
        return None
    p = sc.world.pip(str(raw).lower().lstrip("@"))
    if p is None:
        return None
    return p.get("display_name") or ("builder #%s" % (p.get("n") if p.get("n") is not None else "?"))


def when_text(ts_iso: Optional[str], now: float) -> str:
    """A real timestamp in local words: `21:14`, `yesterday 10:40`, `Sep 24 10:40`; `--` when unknown."""
    t = iso_to_epoch(ts_iso) if isinstance(ts_iso, str) else (float(ts_iso) if ts_iso else None)
    if t is None:
        return "--"
    lt, ln = _time.localtime(t), _time.localtime(now)
    hm = _time.strftime("%H:%M", lt)
    if (lt.tm_year, lt.tm_yday) == (ln.tm_year, ln.tm_yday):
        return hm
    if (lt.tm_year, lt.tm_yday + 1) == (ln.tm_year, ln.tm_yday) or (lt.tm_year + 1 == ln.tm_year and ln.tm_yday == 1):
        return "yesterday " + hm
    return _time.strftime("%b %d ", lt) + hm


# ----------------------------------------------------------------------------- cached text strips
_TEXT: Dict[Tuple, Image.Image] = {}


def text_strip(font: str, size: int, text: str, colour, stroke: bool = True) -> Image.Image:
    """RGBA strip of `text` drawn at (1, 0) with a 1 px bg-coloured stroke (legible over glow). Cached per string."""
    key = (font, size, text, colour, stroke)
    im = _TEXT.get(key)
    if im is not None:
        return im
    f = L.font(font, size)
    sw = 1 if stroke else 0
    try:
        bb = f.getbbox(text, stroke_width=sw)
    except TypeError:
        bb = f.getbbox(text)
    w, h = max(1, bb[2] + 2), max(1, bb[3] + 2)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if stroke:
        d.text((1, 0), text, font=f, fill=colour, stroke_width=1, stroke_fill=L.COLORS["bg"])
    else:
        d.text((1, 0), text, font=f, fill=colour)
    if len(_TEXT) > TEXT_CACHE_MAX:
        for k in list(_TEXT)[:TEXT_CACHE_MAX // 2]:
            _TEXT.pop(k, None)
    _TEXT[key] = im
    return im


_BUBBLE: Dict[Tuple, Image.Image] = {}


def bubble_img(lines: List[Tuple[str, str]], max_w: int = BUBBLE_MAX_W) -> Image.Image:
    """A speech bubble: #11151D box, 1 px #1C2130 border, 3 px tail at the bottom centre. `lines` are already wrapped
    (text, colour) rows, at most 3. Cached on the exact rows."""
    key = tuple(lines) + (max_w,)
    im = _BUBBLE.get(key)
    if im is not None:
        return im
    f = L.font(BUBBLE_FONT, BUBBLE_SIZE)
    tw = max([L.text_width(BUBBLE_FONT, BUBBLE_SIZE, t) for t, _ in lines] or [20])
    w = min(max_w, tw + 2 * BUBBLE_PAD)
    h = BUBBLE_LINE_H * max(1, len(lines)) + 2 * (BUBBLE_PAD - 3) + 6      # + tail
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    box_h = h - 6
    top_c, bot_c = L.hex_rgb(L.COLORS["panel"]), L.hex_rgb(L.COLORS["hairline"])
    for yy in range(box_h):                                   # #11151D -> #1C2130: a board, not floating text on void
        t = yy / float(max(1, box_h - 1))
        d.line([(0, yy), (w - 1, yy)], fill=tuple(int(round(top_c[i] + (bot_c[i] - top_c[i]) * t)) for i in range(3)))
    d.rectangle([0, 0, w - 1, box_h - 1], outline=L.COLORS["hairline"], width=1)
    cx = w // 2
    d.polygon([(cx - 5, box_h - 1), (cx + 5, box_h - 1), (cx, h - 1)], fill=L.COLORS["panel"])
    d.line([(cx - 5, box_h - 1), (cx, h - 1), (cx + 5, box_h - 1)], fill=L.COLORS["hairline"], width=1)
    y = BUBBLE_PAD - 4
    for t, col in lines:
        d.text((BUBBLE_PAD, y), t, font=f, fill=col)
        y += BUBBLE_LINE_H
    if len(_BUBBLE) > 200:
        _BUBBLE.clear()
    _BUBBLE[key] = im
    return im


_PLANK: Dict[Tuple, Image.Image] = {}


def plank_img(text: str, colour, max_w: int = PLANK_MAX_W) -> Image.Image:
    """The plank: HN Medium 22 on a panel-coloured board with a hairline edge (the fiction's wooden sign)."""
    key = (text, colour, max_w)
    im = _PLANK.get(key)
    if im is not None:
        return im
    f = L.font(PLANK_FONT, PLANK_SIZE)
    t = L.truncate(PLANK_FONT, PLANK_SIZE, text, max_w - 24)
    tw = L.text_width(PLANK_FONT, PLANK_SIZE, t)
    w, h = tw + 24, 36
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    fill = tuple(list(L.hex_rgb(L.COLORS["panel"])) + [230])
    d.rectangle([0, 0, w - 1, h - 1], fill=fill, outline=L.COLORS["hairline"], width=1)
    d.line([(0, h - 1), (w - 1, h - 1)], fill=_blend(L.COLORS["hairline"], L.COLORS["text2"], 0.3), width=1)
    d.text((12, 5), t, font=f, fill=colour)
    if len(_PLANK) > 120:
        _PLANK.clear()
    _PLANK[key] = im
    return im


class _Placer(object):
    """Axis-aligned boxes already drawn this frame. `up()` / `down()` slide a new box row by row until it overlaps
    nothing, so stacked labels and bubbles never cover each other (WORLD.md 5: one bubble per pip, labels legible)."""

    def __init__(self):
        self.boxes: List[Tuple[int, int, int, int]] = []

    def _free(self, x0: int, y0: int, x1: int, y1: int) -> bool:
        for bx0, by0, bx1, by1 in self.boxes:
            if x0 < bx1 and bx0 < x1 and y0 < by1 and by0 < y1:
                return False
        return True

    def up(self, x0: int, y0: int, w: int, h: int, step: int, max_steps: int = 10, floor: int = 0) -> int:
        y = y0
        for _ in range(max_steps):
            if self._free(x0, y, x0 + w, y + h) or y - step < floor:
                break
            y -= step
        self.boxes.append((x0, y, x0 + w, y + h))
        return y

    def reserve(self, x0: int, y0: int, x1: int, y1: int) -> None:
        self.boxes.append((x0, y0, x1, y1))

    def place_up(self, x0: int, y0: int, w: int, h: int, step: int, max_steps: int, floor: int = 0) -> Optional[int]:
        """Like up(), but returns None (and reserves nothing) when no free row is found within max_steps."""
        y = y0
        for _ in range(max_steps + 1):
            if self._free(x0, y, x0 + w, y + h):
                self.boxes.append((x0, y, x0 + w, y + h))
                return y
            if y - step < floor:
                break
            y -= step
        return None

    def down(self, x0: int, y0: int, w: int, h: int, step: int, max_steps: int = 6, ceiling: int = 10 ** 6) -> int:
        y = y0
        for _ in range(max_steps):
            if self._free(x0, y, x0 + w, y + h) or y + step + h > ceiling:
                break
            y += step
        self.boxes.append((x0, y, x0 + w, y + h))
        return y


def _paste(img: Image.Image, strip: Image.Image, x: int, y: int) -> None:
    """alpha_composite clipped to the image (PIL raises on a negative destination)."""
    w, h = img.size
    sw, sh = strip.size
    if x >= w or y >= h or x + sw <= 0 or y + sh <= 0:
        return
    if x < 0 or y < 0 or x + sw > w or y + sh > h:
        cx0, cy0 = max(0, -x), max(0, -y)
        cx1, cy1 = min(sw, w - x), min(sh, h - y)
        if cx1 <= cx0 or cy1 <= cy0:
            return
        strip = strip.crop((cx0, cy0, cx1, cy1))
        x, y = max(0, x), max(0, y)
    img.alpha_composite(strip, (x, y))


# ----------------------------------------------------------------------------- the panel
class WorldPanel(Panel):
    key, region = "world", "world"
    budget_ms = 24.0

    def __init__(self):
        self._notices: List[Dict[str, Any]] = []      # {start, until, text, colour, named}
        self._care: Dict[str, Tuple[str, float]] = {}
        self._hatch_tag: Dict[str, Tuple[str, float]] = {}
        self._only_light: Optional[Tuple[str, float]] = None
        self._label_override: Dict[str, Tuple[str, float]] = {}
        self._ms: List[float] = []
        self._frames = 0
        self._errors = 0
        self.honesty_violations = 0
        self._last_counts = (0, 0)
        self.last_plank: Optional[str] = None            # the plank text of the last frame (compositor vote-ack check)
        self.last_plank_row2: Optional[str] = None
        self.last_placed: List[Tuple[int, int, int]] = []
        self._alone_since: Optional[float] = None       # WORLD.md 10: one person, dead night
        self._alone_prompted = False
        self._sleepers_lit_until = 0.0
        self._lonely_t = -1e9                            # the last loneliness plank (the 45 s prompt and the `anyone?` answer never stack)

    def inputs(self, ctx):
        return ctx.frame                              # the sim moves every frame

    # ------------------------------------------------------------------ names
    @staticmethod
    def _names_on(ctx) -> bool:
        if ctx.chat_display is False:
            return False
        cfg = ctx.chat_cfg or {}
        return cfg.get("display") is not False

    def _shown(self, sc: H.CaveScene, key: Optional[str]) -> Optional[str]:
        """@-less display name for a pip key; None when there is no such real pip (then nothing is drawn)."""
        if not key:
            return None
        p = sc.world.pip(key)
        if p is None:
            self.honesty_violations += 1
            return None
        return p.get("display_name") or ("builder #%s" % (p.get("n") if p.get("n") is not None else "?"))

    def _label_text(self, sc: H.CaveScene, e: Dict[str, Any]) -> Optional[str]:
        shown = e.get("display_name") or self._shown(sc, e.get("key"))
        if not shown:
            return None
        p = sc.world.pip(e["key"]) or {}
        nick = p.get("nickname")
        txt = ("%s (@%s)" % (L.strip_non_bmp(str(nick))[:12], shown)) if nick else ("@" + shown)
        tag = self._hatch_tag.get(e["key"])
        if tag and not shown.startswith("builder #"):          # `@quietnoodle #4` for 3 s after the hatch (builder #N already says it)
            txt = "%s %s" % (txt, tag[0])
        return txt

    # ------------------------------------------------------------------ events -> notices
    def _notice(self, now: float, text: str, colour, dur: float = NOTICE_S, named: bool = True, start: Optional[float] = None,
                prio: int = PRIO_EVENT, sticky: bool = False) -> None:
        """Queue a plank line. `prio` decides who wins when several are live (person-facing lines outrank world events;
        never last-appended-wins). `sticky` lines count only the seconds they were actually shown toward `dur` (a vote
        ack or a refusal covering them pauses their clock), capped at 2.5 x dur."""
        st = start if start is not None else now
        self._notices.append({"start": st, "until": st + dur, "dur": dur, "shown": 0.0, "hard_until": st + dur * 2.5,
                              "text": text, "colour": colour, "named": named, "prio": int(prio), "sticky": bool(sticky)})
        if len(self._notices) > 16:
            self._notices.sort(key=lambda n: (n["prio"], n["start"]))
            del self._notices[:-16]

    def _consume_events(self, sc: H.CaveScene, ctx, now: float, accent: str) -> None:
        w = sc.world
        for ev in sc.events or []:
            typ = ev.get("type")
            try:
                if typ == "sink":
                    self._notice(now, "the soil did not take that one", L.COLORS["text2"], named=False)
                elif typ == "hatch":
                    key = ev.get("pip")
                    p = w.pip(key) if key else None
                    if p is not None and p.get("n") is not None:
                        self._hatch_tag[key] = ("#%d" % int(p["n"]), now + 3.0)
                    if ev.get("only_light") and key:
                        self._only_light = (key, now + 10.0)
                    if ev.get("first_ever"):
                        # WORLD.md 2.2 T+4 to T+10 s: one second after the hatch, for a SEEN 8 s (sticky), above every world line
                        self._notice(now, "that's you. try: feed · pet · dig · plant", L.COLORS["text"], dur=8.0, named=False,
                                     start=now + 1.0, prio=PRIO_YOU, sticky=True)
                        self._notice(now, "your pip sleeps here when you go. it is here tomorrow.", L.COLORS["text2"], dur=6.0,
                                     named=False, start=now + 9.0, prio=PRIO_LIGHT, sticky=True)
                        self._notice(now, "stay ten minutes and your pip grows a row of pixels.", L.COLORS["text2"], dur=6.0,
                                     named=False, start=now + 17.0, prio=PRIO_LIGHT, sticky=True)
                elif typ == "speak":
                    # a lone chatter asking `is anyone here` gets the cave's real answer: every sleeper's label lights for 5 s
                    # and the plank counts them (len()), naming one real sleeper to pet
                    if sc.awake_count() == 1 and _LONELY_RE.search(str(ev.get("text") or "")):
                        self._sleepers_lit_until = now + SLEEPERS_LIT_S
                        self._lonely_plank(sc, ev.get("pip"), now, asked=True)
                elif typ == "first_light":
                    nm = self._shown(sc, ev.get("pip"))
                    if nm:
                        self._notice(now, "@%s woke the Hollow · %s" % (nm, _time.strftime("%H:%M", _time.localtime(now))), accent,
                                     dur=FIRST_LIGHT_S, prio=PRIO_LIGHT)
                elif typ == "wake":
                    self._care_line(sc, ev, now)
                    if ev.get("only_light") and ev.get("pip"):
                        self._only_light = (ev["pip"], now + 10.0)
                elif typ == "sleep":
                    nm = self._shown(sc, ev.get("pip"))
                    if nm:
                        q = int(round(float(ev.get("quiet_s") or sc.sleep_after_s) / 60.0))
                        self._label_override[ev["pip"]] = ("@%s · asleep · quiet %d min" % (nm, q), now + 8.0)
                elif typ == "tier_up":
                    nm = self._shown(sc, ev.get("pip"))
                    if nm:
                        self._notice(now, "@%s's pip grew" % nm, accent, prio=PRIO_VERB)
                elif typ == "forget":
                    nm = self._shown(sc, ev.get("pip"))
                    if nm:
                        self._notice(now, "@%s's pip forgot everything" % nm, L.COLORS["text"], prio=PRIO_VERB)
                elif typ == "burrowed":
                    reason = str(ev.get("reason") or "")
                    if "hidden" not in reason and "mod" not in reason:          # a hidden user's name never appears
                        nm = self._shown(sc, ev.get("pip"))
                        if nm:
                            self._notice(now, "@%s's pip burrowed: %s" % (nm, reason or "for tonight"), L.COLORS["warn"], prio=PRIO_VERB)
                elif typ in ("feed", "pet", "gift"):
                    by = self._shown(sc, ev.get("by"))
                    nm = self._shown(sc, ev.get("pip"))
                    if by and nm:
                        if by == nm:
                            line = ("@%s's pip ate a glow-berry" % nm) if typ == "feed" else ("@%s petted their own pip" % nm)
                        else:
                            verb = {"feed": "fed", "pet": "petted", "gift": "left a gift for"}[typ]
                            tail = " (asleep · it will know on wake)" if ev.get("asleep") or typ == "gift" else ""
                            line = "@%s %s @%s%s" % (by, verb, nm, tail)
                        self._notice(now, line, L.COLORS["text"], prio=PRIO_VERB)
                elif typ == "dig":
                    nm = self._shown(sc, ev.get("pip"))
                    if nm:
                        self._notice(now, "@%s dug %d cells" % (nm, int(ev.get("cells") or 0)), L.COLORS["text"], prio=PRIO_VERB)
                elif typ == "plant":
                    nm = self._shown(sc, ev.get("pip"))
                    if nm:
                        self._notice(now, "@%s planted glowmoss" % nm, accent, prio=PRIO_VERB)
                elif typ == "credits_start":
                    n = int(ev.get("count") or 0)
                    self._notice(now, "goodnight. %d pip%s walk home." % (n, "" if n == 1 else "s"), L.COLORS["text"], dur=3.0, named=False, prio=PRIO_CREDITS)
                elif typ == "credits":
                    nm = self._shown(sc, ev.get("pip"))
                    if nm:
                        self._notice(now, "@%s · %d min tonight" % (nm, int(round(float(ev.get("minutes_tonight") or 0)))), L.COLORS["text"], dur=1.5, prio=PRIO_CREDITS)
                elif typ == "credits_end":
                    self._notice(now, "the Hollow sleeps. see you next time.", L.COLORS["text2"], dur=20.0, named=False, prio=PRIO_CREDITS)
                # -- keepers (stream/world/keepers.py events ride in scene.events): NOT on the plank. The plank is the
                #    person-facing slot (WORLD.md 2.2); the keeper strip (`carving: the Ledge · 0:20 left · opened by
                #    @sami's hatch`, `last carved: ...`, failures) and the colony strip (milestone caption) show these.
            except Exception:
                self._errors += 1
        # expire: plain lines at `until`; sticky lines once they have been SEEN for `dur` (or at the hard cap)
        self._notices = [n for n in self._notices if (n["until"] > now if not n.get("sticky")
                                                       else (n["shown"] < n["dur"] and n["hard_until"] > now))]
        for d in (self._care, self._hatch_tag, self._label_override):
            for k in [k for k, v in d.items() if v[1] <= now]:
                d.pop(k, None)
        if self._only_light and (self._only_light[1] <= now or sc.awake_count() > 1):
            self._only_light = None                       # `you are the only light` is a fact only while it is one

    def _lonely_plank(self, sc: H.CaveScene, key: Optional[str], now: float, asked: bool = False) -> None:
        """WORLD.md 10 `one person, dead night`: the plank answers loneliness with the real colony. `N sleep here` is a
        len(); the sleeper named is the one nearest the awake pip (a real past chatter); the nearest sleeper stirs once."""
        sleepers = [e for e in sc.behaviour.entities.values() if e.state == "asleep" and e.display_name]
        me = sc.behaviour.get(key) if key else None
        n = len(sleepers)
        if me is not None and sleepers:
            near = min(sleepers, key=lambda e: abs(e.x - me.x))
            nm = self._shown(sc, near.key)
            sc.behaviour.stir(near.key, now)
        else:
            near, nm = None, None
        if n == 0:
            txt = "nobody else has ever been here. you're the first light." if asked else "you're alone tonight. every mark you make is here tomorrow."
        elif nm:
            txt = ("%d asleep here · pet @%s and they'll know you came." % (n, nm)) if asked else \
                  ("you're alone tonight. pet @%s and they'll see it when they wake." % nm)
        else:
            txt = "%d asleep here. say anything and they hear it tomorrow." % n
        if not asked and now - self._lonely_t < 30.0:
            return                                            # the 45 s prompt yields to a fresh answer; a question is always answered
        self._lonely_t = now
        self._notice(now, txt, L.COLORS["text"], dur=8.0, prio=PRIO_LIGHT, sticky=True)

    def _care_line(self, sc: H.CaveScene, ev: Dict[str, Any], now: float) -> None:
        """`back after 2 nights · fed by @kai x2 · petted by @x · gift from @sami` from the REAL care log."""
        key = ev.get("pip")
        if not key:
            return
        parts: List[str] = []
        away = ev.get("away_s")
        if away is not None and float(away) >= 6 * 3600:
            nights = max(1, int(round(float(away) / 86400.0)))
            parts.append("back after %d night%s" % (nights, "" if nights == 1 else "s"))
        counts: Dict[Tuple[str, str], int] = {}
        for c in ev.get("care_log") or []:
            by = self._shown(sc, c.get("by"))
            if not by:
                continue
            k = (str(c.get("verb") or "feed"), by)
            counts[k] = counts.get(k, 0) + 1
        for (verb, by), n in sorted(counts.items()):
            word = {"feed": "fed by", "pet": "petted by", "gift": "gift from"}.get(verb, verb + " by")
            parts.append("%s @%s%s" % (word, by, (" x%d" % n) if n > 1 else ""))
        if parts:
            self._care[key] = (" · ".join(parts), now + 6.0)

    # ------------------------------------------------------------------ plank
    def _plank_text(self, sc: H.CaveScene, ctx, now: float, names_on: bool, accent: str) -> Tuple[str, Any]:
        nt = ctx.notice if (ctx.notice and isinstance(ctx.notice, (tuple, list)) and ctx.notice[0] and names_on) else None
        lvl = (nt[1] if nt is not None and len(nt) > 1 else None)
        if nt is not None:
            # a direct answer to a person outranks the world's own event lines: the same-frame `@name voted A` ack
            # (1.5 s, CONCEPT 2), a verb refusal (`feed again in 26 s`, WORLD.md 4: every refusal shows for 4 s),
            # a mod notice, a verb confirmation
            col = L.COLORS["danger"] if lvl == "danger" else (accent if lvl in ("ok", "accent", "info") else L.COLORS["warn"])
            return str(nt[0]), col
        live = self._live_notices(now, names_on)
        if live:
            n = max(live, key=lambda q: (q["prio"], q["start"]))        # the person outranks the world; then newest
            if n.get("sticky"):
                n["shown"] += 1.0 / float(ctx.fps or 30)
            return n["text"], n["colour"]
        if ctx.mod_paused:
            return "chat paused by mod · pips keep moving", L.COLORS["warn"]
        if ctx.help_until and now < float(ctx.help_until):
            return LEGEND[int(now / LEGEND_ITEM_S) % len(LEGEND)], L.COLORS["text"]
        rem = ctx.round_remaining
        phase = (ctx.round or {}).get("phase")
        if (ctx.vote_count or 0) == 0 and rem is not None and 0 <= rem < 30 and phase != "ship":
            return "nobody voted yet. your letter alone decides this one.", L.COLORS["warn"]
        if phase == "ship":
            res = (ctx.round or {}).get("last_result") or {}
            title = L.strip_non_bmp(str(res.get("title") or ""))
            if title:
                if res.get("agent_pick"):
                    copy_line = res.get("copy")                  # rounds' own zero-vote copy (checks the keeper heartbeat)
                    if copy_line:
                        return L.strip_non_bmp(str(copy_line)), L.COLORS["text"]
                    who = "the keepers picked" if self._keeper_fresh(ctx) else "the Hollow picked"
                    return "nobody voted. %s %s." % (who, title), L.COLORS["text"]
                by = shown_name(res.get("picked_by")) if names_on else None
                return ("%s · picked by @%s" % (title, by)) if by else title, accent
        # idle rotation
        items: List[Tuple[str, Any]] = []
        hatched, awake, asleep = sc.hatched_ever(), sc.awake_count(), sc.asleep_count()
        if hatched == 0:
            items.append(("nobody has hatched here yet. say anything and you are the first.", L.COLORS["text"]))
        elif awake == 0:
            items.append(("%d pip%s sleep here. nobody awake. say anything and yours wakes." % (asleep, "" if asleep == 1 else "s"), L.COLORS["text"]))
        else:
            items.append(("say anything in chat. a pip hatches with your name.", L.COLORS["text"]))
        if names_on:
            visits = list((sc.world.data.get("world") or {}).get("visits") or [])[-5:]
            segs = []
            for v in reversed(visits):
                nm = self._shown(sc, v.get("name"))
                if nm:
                    segs.append("@%s %s" % (nm, when_text(v.get("ts"), now)))
            if segs:
                items.append(("last here: " + " · ".join(segs), L.COLORS["text2"]))
            woke = list((sc.world.data.get("world") or {}).get("woke_log") or [])
            if woke:
                last = woke[-1]
                t = iso_to_epoch(last.get("ts"))
                started = iso_to_epoch((ctx.session or {}).get("started_ts"))
                if t is not None and (started is None or t >= started - 60):
                    nm = self._shown(sc, last.get("name"))
                    if nm:
                        items.append(("@%s woke the Hollow · %s" % (nm, when_text(last.get("ts"), now)), accent))
        items.append((LEGEND[0], L.COLORS["text2"]))
        # the call to action (items[0]) comes back every other slot: CTA, visitors, CTA, woke, CTA, legend, ...
        slot = int(now // ROTATE_S)
        if slot % 2 == 0 or len(items) == 1:
            return items[0]
        rest = items[1:]
        return rest[(slot // 2) % len(rest)]

    def _live_notices(self, now: float, names_on: bool) -> List[Dict[str, Any]]:
        return [n for n in self._notices if n["start"] <= now and (names_on or not n["named"])
                and (n["until"] > now if not n.get("sticky") else n["hard_until"] > now)]

    def _plank_row2(self, ctx, now: float, names_on: bool, primary: str) -> Optional[Tuple[str, Any]]:
        """The newcomer's sticky line (`that's you. try: ...`) when row 1 is held by something else (a vote ack, a
        refusal to another person): it drops to a second plank row instead of vanishing, and its seen-clock runs.
        WORLD.md 2.2 T+4-10 s: the stranger gets the full 8 s, whatever else chat is doing."""
        for n in sorted(self._live_notices(now, names_on), key=lambda q: -q["prio"]):
            if n.get("sticky") and n["prio"] >= PRIO_YOU and n["text"] != primary:
                n["shown"] += 1.0 / float(ctx.fps or 30)
                return n["text"], n["colour"]
        return None

    @staticmethod
    def _keeper_fresh(ctx) -> bool:
        hb = iso_to_epoch((ctx.agent or {}).get("heartbeat_ts"))
        return hb is not None and (ctx.now - hb) < 120.0

    # ------------------------------------------------------------------ render
    def render(self, ctx, size):
        t0 = _time.perf_counter()
        sc = scene()
        try:
            base = sc.frame(ctx, size)
        except Exception:
            self._errors += 1
            base = Image.new("RGBA", size, L.COLORS["bg"])
        mon = getattr(sc, "honesty", None)
        if mon is not None:                                # WORLD.md 11: asserted every frame, forged entities removed
            try:
                mon.check(ctx, float(ctx.now if ctx.now is not None else _time.time()))
            except Exception:
                self._errors += 1
        try:
            img = base.copy()                          # the scene keeps `base` as its last good frame: never draw on it
            self._text_layer(img, sc, ctx, size)
        except Exception:
            self._errors += 1
            if self._errors <= 3 or self._errors % 300 == 0:
                _log("text layer failed (%d): %s" % (self._errors, traceback.format_exc().strip().splitlines()[-1]))
            img = base
        ms = (_time.perf_counter() - t0) * 1000.0
        self._ms.append(ms)
        if len(self._ms) > STATS_EVERY:
            del self._ms[:-STATS_EVERY]
        self._frames += 1
        if self._frames % STATS_EVERY == 0:
            st = sc.stats() if sc.booted else {}
            _log("frame %d: panel avg %.2f ms max %.2f (scene avg %s ms, degrade %s) awake=%s asleep=%s hatched=%s "
                 "entities=%s honesty_violations=%d/%s text_cache=%d" % (
                     self._frames, sum(self._ms) / len(self._ms), max(self._ms), st.get("avg_ms"), (st.get("degrade") or {}).get("level"),
                     st.get("awake"), st.get("asleep"), st.get("hatched_ever"), st.get("entities"),
                     self.honesty_violations, st.get("honesty_violations"), len(_TEXT)))
        return img

    def _text_layer(self, img: Image.Image, sc: H.CaveScene, ctx, size) -> None:
        if not sc.booted:
            return
        w, h = size
        now = float(ctx.now if ctx.now is not None else _time.time())
        accent = L.preset(ctx.preset)["accent"]
        names_on = self._names_on(ctx)
        deg = sc.degrade
        ents = sc.entities(now)
        awake = sc.awake_count()
        labels_on_speak = bool(deg.get("labels_on_speak")) or awake > DENSITY_FALLBACK
        dense = awake > DENSITY_FALLBACK
        self._consume_events(sc, ctx, now, accent)
        if awake == 1:
            if self._alone_since is None:
                self._alone_since, self._alone_prompted = now, False
            elif not self._alone_prompted and now - self._alone_since >= ALONE_PROMPT_S:
                self._alone_prompted = True
                lone = next((e for e in sc.behaviour.entities.values() if e.is_awake()), None)
                self._lonely_plank(sc, lone.key if lone is not None else None, now)
        else:
            self._alone_since, self._alone_prompted = None, False

        # 1. platform titles, letters, counts, standing names (drawn first: carved into the rock; their boxes are RESERVED so no
        #    label or bubble ever covers the letter row, WORLD.md 8.1 `title on the platform`)
        placer = _Placer()
        counts = sc.platform_counts()
        carved = _blend(L.COLORS["hairline"], L.COLORS["text2"], 0.45)
        options = {str(o.get("letter") or "").upper(): o for o in ((ctx.round or {}).get("options") or []) if isinstance(o, dict)}
        best_votes = max([len(counts.get(k) or []) for k in PLATFORM_LETTERS] or [0])
        cluster_x: List[int] = []
        plat_row: Dict[str, Tuple[int, int]] = {}          # letter -> (x0, x1) of the widest carved row (letter+count / names)
        for letter, (px, pw) in zip(PLATFORM_LETTERS, PLATFORMS):
            cx, _ = sc.sim_to_screen(px + pw / 2.0, 0)
            keys = counts.get(letter) or []
            n = len(keys)
            if n:
                cluster_x.append(cx)
            opt = options.get(letter) or {}
            title = L.strip_non_bmp(str(opt.get("title") or "")).strip()
            if title:
                lead = n > 0 and n == best_votes
                ts = text_strip(LABEL_FONT, LABEL_SIZE, L.truncate(LABEL_FONT, LABEL_SIZE, title, PLATFORM_TITLE_MAX_W),
                                accent if lead else L.COLORS["text2"])
                tx = max(GUTTER, min(w - ts.size[0] - GUTTER, cx - ts.size[0] // 2))
                _paste(img, ts, tx, PLATFORM_TITLE_Y)
                placer.reserve(tx, PLATFORM_TITLE_Y, tx + ts.size[0], PLATFORM_TITLE_Y + LABEL_H)
            lt = text_strip("AB", 56, letter, "#%02x%02x%02x" % carved, stroke=False)
            _paste(img, lt, cx - lt.size[0] // 2, PLATFORM_LETTER_Y)
            ct = text_strip("Menlo", 22, "%d" % n, accent if n else L.COLORS["text2"])
            _paste(img, ct, cx + lt.size[0] // 2 + 8, PLATFORM_COUNT_Y)
            placer.reserve(cx - lt.size[0] // 2, PLATFORM_LETTER_Y, cx + lt.size[0] // 2 + 8 + ct.size[0], PLATFORM_LETTER_Y + 64)
            plat_row[letter] = (cx - lt.size[0] // 2, cx + lt.size[0] // 2 + 8 + ct.size[0])
            if n and names_on:
                # the names row: up to 3 real names UNTRUNCATED across the platform's width; when they do not fit, the row
                # says `N standing` (a len()), never a chopped name (art-rules 4)
                segs: List[Image.Image] = []
                total = 0
                shown = [self._shown(sc, k) for k in keys[-3:]]
                shown = [nm for nm in shown if nm]
                for j, nm in enumerate(shown):
                    if segs:
                        sep = text_strip(LABEL_FONT, LABEL_SIZE, " · ", L.COLORS["text2"])
                        segs.append(sep); total += sep.size[0]
                    k = keys[-3:][j] if j < len(keys[-3:]) else keys[-1]
                    st = text_strip(LABEL_FONT, LABEL_SIZE, "@" + nm, P.colour_hex(k, ctx.preset))
                    segs.append(st); total += st.size[0]
                if total > PLATFORM_NAMES_MAX_W and len(shown) > 1:
                    st = text_strip(LABEL_FONT, LABEL_SIZE, "%d standing" % n, L.COLORS["text"])
                    segs, total = [st], st.size[0]
                x = max(GUTTER, min(w - GUTTER - total, cx - total // 2))
                placer.reserve(x, PLATFORM_NAMES_Y, x + total, PLATFORM_NAMES_Y + LABEL_H)
                r0, r1 = plat_row.get(letter, (x, x + total))
                plat_row[letter] = (min(r0, x), max(r1, x + total))
                for st in segs:
                    _paste(img, st, x, PLATFORM_NAMES_Y); x += st.size[0]

        # 2. labels (awake: above the sprite; sleepers: one at a time on a 5 s rotation; standing pips: the platform row).
        #    De-collision: a label that intersects anything already placed moves up in 22 px steps, at most 3; still
        #    blocked -> that pip is label-on-speak. A pip within PLATFORM_CLUSTER_PX of an occupied platform's crowd has
        #    no floating label either (the platform row names the crowd).
        placed: List[Tuple[int, int, int]] = []
        label_pos: Dict[str, Tuple[int, int]] = {}         # key -> (cx, label top y) for the bubble anchor
        drawn_names = 0
        ents = sorted(ents, key=lambda e: (e.get("sx", 0), e.get("key") or ""))
        sleepers = [e for e in ents if e.get("state") == "asleep" and e.get("key")]
        sleeper_pick = None
        if sleepers and names_on and not dense:
            sleeper_pick = sleepers[int(now // SLEEPER_ROTATE_S) % len(sleepers)]["key"]
        for e in ents:
            key = e.get("key")
            if not key or e.get("display_name") is None or e.get("state") in ("burrowed", "seed", "hatching"):
                continue                                   # a seed: nothing about it is drawn (WORLD.md 11.1)
            cx = int(e["sx"] + e["sw"] // 2)
            top = int(e["sy"])
            if not names_on:
                continue
            txt = None
            if e.get("awake"):
                if e.get("state") == "voting" and e.get("platform"):
                    label_pos[key] = (cx, top - 4)
                    continue                               # its name is in the platform row
                if labels_on_speak and not e.get("speaking") and key not in self._label_override:
                    continue
                if not e.get("speaking") and any(abs(cx - pcx) <= PLATFORM_CLUSTER_PX + 48 for pcx in cluster_x):
                    label_pos[key] = (cx, top - 4)
                    continue                               # next to an occupied platform: the row is the readable list
                txt = self._label_text(sc, e)
            else:                                          # asleep
                ov = self._label_override.get(key)
                if ov:
                    txt = ov[0]
                elif now < self._sleepers_lit_until and not dense:
                    p = sc.world.pip(key) or {}                # `is anyone here` -> every sleeper answers with its real last seen
                    nm = self._label_text(sc, e)
                    txt = "%s · asleep since %s" % (nm, when_text(p.get("last_seen_ts"), now)) if nm else None
                elif key == sleeper_pick:
                    p = sc.world.pip(key) or {}
                    nm = self._label_text(sc, e)
                    txt = "%s · asleep · last seen %s" % (nm, when_text(p.get("last_seen_ts"), now)) if nm else None
            if not txt:
                continue
            strip = text_strip(LABEL_FONT, LABEL_SIZE, txt, P.colour_hex(key, ctx.preset))
            sw = strip.size[0]
            gut = GUTTER if not e.get("awake") else 2
            x0 = max(gut, min(w - sw - gut, cx - sw // 2))
            y = placer.place_up(x0, top - LABEL_H - 2, sw, LABEL_H, LABEL_STEP, LABEL_MAX_STEPS, floor=PLATFORM_TITLE_Y - 60)
            if y is None:
                if not e.get("speaking"):
                    label_pos[key] = (cx, top - 4)
                    continue                               # crowded: label-on-speak for this pip
                y = placer.up(x0, top - LABEL_H - 2 - LABEL_STEP * LABEL_MAX_STEPS, sw, LABEL_H, LABEL_STEP, max_steps=4, floor=2)
            placed.append((x0, x0 + sw, y))
            _paste(img, strip, x0, y)
            label_pos[key] = (cx, y)
            drawn_names += 1

        # 3. bubbles (one per pip, 6 s; care log rides as the first line; !kill -> `chat hidden by mod`)
        single: Optional[Tuple[float, str, str]] = None
        for e in ents:
            key = e.get("key")
            if not key or not e.get("awake"):
                continue
            care = self._care.get(key)
            text = e.get("text") if e.get("speaking") else None
            if not text and not care:
                continue
            rows: List[Tuple[str, str]] = []
            if not names_on:
                rows.append(("chat hidden by mod", L.COLORS["text2"]))
            else:
                if care:
                    rows.append((L.truncate(BUBBLE_FONT, BUBBLE_SIZE, care[0], BUBBLE_MAX_W - 2 * BUBBLE_PAD), L.COLORS["text2"]))
                if text:
                    body = L.strip_non_bmp(str(text))
                    if e.get("learned_from"):
                        src = self._shown(sc, e.get("learned_from"))
                        body = "%s · from @%s" % (body, src) if src else body
                    for ln in L.wrap(BUBBLE_FONT, BUBBLE_SIZE, body, BUBBLE_MAX_W - 2 * BUBBLE_PAD, 3 - len(rows)):
                        rows.append((ln, L.COLORS["text"]))
            if not rows:
                continue
            if deg.get("bubbles_single"):
                nm = e.get("display_name") if names_on else None
                cand = (float(e.get("minutes_tonight") or 0), nm, rows[-1][0])
                if single is None or e.get("speaking"):
                    single = cand
                continue
            b = bubble_img(rows)
            cx, ly = label_pos.get(key, (int(e["sx"] + e["sw"] // 2), int(e["sy"]) - 2))
            if e.get("state") == "voting" and e.get("platform"):
                # a standing pip speaks BESIDE the letter column (the letter / count / names stack is ~100 px tall; a bubble
                # pushed above it floats 200 px from the creature): just past the widest carved row, at the pip's height.
                r0, r1 = plat_row.get(str(e.get("platform")), (cx - 40, cx + 40))
                side_x = max(cx + 40, r1 + 10)
                if side_x + b.size[0] > w - 2:
                    side_x = min(cx - 40, r0 - 10) - b.size[0]
                bx = max(2, min(w - b.size[0] - 2, side_x))
                by = placer.up(bx, max(2, int(e["sy"] + e["sh"]) - 8 - b.size[1]), b.size[0], b.size[1], BUBBLE_LINE_H, max_steps=8, floor=2)
            else:
                bx = max(2, min(w - b.size[0] - 2, cx - b.size[0] // 2))
                by = placer.up(bx, max(2, ly - 4 - b.size[1]), b.size[0], b.size[1], BUBBLE_LINE_H, max_steps=8, floor=2)
            _paste(img, b, bx, by)
        if single is not None:
            _, nm, line = single
            txt = ("@%s: %s" % (nm, line)) if nm else line
            s = text_strip(BUBBLE_FONT, BUBBLE_SIZE, L.truncate(BUBBLE_FONT, BUBBLE_SIZE, txt, w - 2 * 16), L.COLORS["text"])
            _paste(img, s, 16, h - 34)

        # 4. the only-light line (10 s): ABOVE the pip's name label, through the placer, so it never overprints the
        #    label, a bubble or the platform rows (the `#N` hatch tag rides inside the name label itself)
        if self._only_light:
            for e in ents:
                key = e.get("key")
                if not key or key != self._only_light[0] or not e.get("awake"):
                    continue
                s = text_strip(LABEL_FONT, LABEL_SIZE, "you are the only light in the cave.", L.COLORS["text"])
                cx, ly = label_pos.get(key, (int(e["sx"] + e["sw"] // 2), int(e["sy"]) - 2))
                tx = max(2, min(w - s.size[0] - 2, cx - s.size[0] // 2))
                ty = placer.place_up(tx, ly - LABEL_H - 2, s.size[0], LABEL_H, LABEL_STEP, 6, floor=2)
                if ty is None:
                    ty = placer.down(tx, int(e["sy"] + e["sh"]) + 2, s.size[0], LABEL_H, LABEL_H, ceiling=h - 2)
                _paste(img, s, tx, ty)

        # 5. moss labels on a 5 s rotation, in the SOIL BAND under the floor (never at pip height where people gather);
        #    dropped at degrade level >= 2 and above the density fallback
        moss = sc.world.moss if sc.world is not None else []
        if moss and names_on and deg.get("level", 0) < 2 and not dense:
            m = moss[int(now // MOSS_ROTATE_S) % len(moss)]
            nm = self._shown(sc, m.get("planter"))
            if nm:
                p = sc.world.pip(m.get("planter")) or {}
                night = max(1, int(p.get("sessions_seen") or 1))
                s = text_strip(LABEL_FONT, LABEL_SIZE, "moss · @%s · night %d" % (nm, night), accent)
                mx, _my = sc.sim_to_screen(float(m.get("x") or 0), float(m.get("y") or 0))
                lx = max(2, min(w - s.size[0] - 2, mx - s.size[0] // 2))
                ly = placer.down(lx, SOIL_LABEL_Y, s.size[0], LABEL_H, LABEL_STEP, max_steps=3, ceiling=h - 2)
                _paste(img, s, lx, ly)

        # 6. the plank (top-left, over everything else in the region)
        txt, col = self._plank_text(sc, ctx, now, names_on, accent)
        _paste(img, plank_img(L.strip_non_bmp(txt), col), PLANK_XY[0], PLANK_XY[1])
        row2 = self._plank_row2(ctx, now, names_on, txt)
        if row2 is not None:
            _paste(img, plank_img(L.strip_non_bmp(row2[0]), row2[1]), PLANK_XY[0], PLANK_XY[1] + PLANK_ROW2_DY)
        self.last_plank = txt
        self.last_plank_row2 = row2[0] if row2 is not None else None
        self._last_counts = (drawn_names, len(ents))
        self.last_placed = placed                            # (x0, x1, y) of every label this frame, for QA

    def stats(self) -> Dict[str, Any]:
        sc = scene()
        mon = getattr(sc, "honesty", None)
        kp = getattr(sc, "keepers", None)
        return {"frames": self._frames, "errors": self._errors, "avg_ms": round(sum(self._ms) / len(self._ms), 2) if self._ms else None,
                "max_ms": round(max(self._ms), 2) if self._ms else None, "honesty_violations": self.honesty_violations,
                "labels_drawn": self._last_counts[0], "entities": self._last_counts[1], "text_cache": len(_TEXT), "bubble_cache": len(_BUBBLE),
                "honesty": mon.summary() if mon is not None else None, "keepers": kp.stats() if kp is not None else None,
                "degrade": dict(sc.degrade) if sc.booted else None}


PANEL = WorldPanel()
register(PANEL)
