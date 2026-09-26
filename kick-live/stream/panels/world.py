"""stream/panels/world.py - the WORLD region (0,0,1280,720): the scene frame + the screen-scale TEXT LAYER.

Two scenes, one panel (OPENWORLD.md 8; WORLD.md 5 row 5, 11 still normative). Full-bleed land (owner 2026-09-26 18:35,
journal 032 / 034): the world IS the frame. No header, no strip, no chat log, no card, no minimap; every fact a
stranger needs is an object in the world the camera can frame, in ONE wood material, and the only screen-fixed object
is the plank. Zero explainer copy: nothing drawn here says AI, keeper, LIVE, LONGGRASS, camera, mic, fake, honest,
version, fps, viewers, awake, surveying, a result sentence or a wall clock (the compositor's copy check makes the
owner's rule mechanical).

  LONGGRASS  `stream/scenes/steading.py` `SteadingScene` (the painted land, a camera). The scene draws the ground, the
             modulation, the sprites and NO text. This panel draws, at screen scale (nothing under 20 px, every string
             cached as an RGBA strip, everything placed through the float camera and CULLED off-view):
    plank        HN Medium 22 cream on a wood chip (38 px) at canvas (16, 16): THE LAND'S SINGLE VOICE, one row, fades
                 out over 0.5 s after 5 s, sticky lines never fade, BLANK at idle (no camera captions of any kind).
                 Priority, top wins: `chat is reconnecting…` (amber, sticky) > person lines newest first (the bridge's
                 `@kai stands at B · light: gold · closes in 1:27`, `try: go river`, this panel's `@kai left B · that
                 vote is dropped`, the newcomer's `someone new walked in` / `that's you, @kai` / sticky `@kai · try: go
                 river · plant a flower · camp`, `@kai walked in · 4 have walked here`, `next: camp · plant a flower`,
                 the returning regular, !stats) > world events (`new round · type A, B or C`, `the cairn is named`,
                 `the Coast is open`) > BLANK. Its real drawn box is the camera's only top dead-zone box and the placer's
                 only fixed reserve.
    SIGN         `SAY ANYTHING` AB 56 cream + 1 px dark stroke on a wood board (<= 480x70, two 6 px posts to the anchor
                 cell MOOT_LAYOUT["sign"] = Moot+(0, +38)); the carved blend once anyone is awake. World-anchored,
                 screen-scale, culled off-view with a 300 px margin. The one instruction the frame needs, at the spot
                 where it comes true; AB 56 is 14 px in the 320x180 directory tile, the one text size proven legible.
    waystones    AB 56 letters (AB 40 at 0.75x so they never overprint 36 px apart) above the three stones, the
                 leader in the accent, a glyph fading to 40 % while a sprite box crosses it (people walk in front of
                 letters); count Menlo 22 under each (`0 +1` while a voter walks); up to 3 names else `4 standing`,
                 placer-stacked.
    MOOT BOARD   one wood board above the B stone, centred on the letters' x span, bottom 6 px above the letter strips
                 (place_up, 4 steps, culled with the stones, never a fixed fallback), STACKED: a 30 px top rail [`type A,
                 B or C` Menlo 20 left only at 0 standing][the timer Menlo Bold 24 right: cream / amber < 30 s / red < 10 s
                 / amber `closing` once the deadline passed and the manager has not shipped], then one 34 px row per
                 option [AB 28 letter][HN Medium 22 title WHOLE up to 560 px: every menu title fits; `→` is mapped to `·`
                 because HelveticaNeue has no arrow] with carved lines between rows; the leading row sits on a band of
                 the accent (its letter accent, its title cream; tie / zero lights nothing); a 4 px fuse cord along the
                 6 px bottom rail shrinking left to right with a 6 px ember, burnt out while `closing`, full during the
                 ship hold (the winner stays lit, the others dim to 40 %, the cord flares white 1 s; a land pick lights
                 muted amber); nothing between rounds. No result prose, ever.
    Moot marker  `◂ A B C · 1:27` Menlo 22 on wood at the frame edge toward the stones, only while a round is open,
                 anyone is awake and no stone is in view (the people arrows' grammar; the ballot is never invisible).
    labels       Menlo 20 `@name` in the creature's genome colour, stroked, on a CONTRAST CHIP (a hue that misses
                 4.5:1 over the brightest grass gets a darker chip, never a different colour), above the sprite,
                 de-collided by the placer; `#N` for 3 s after a first-ever hatch; standing pips have no floating label
    bubbles      Menlo 22 in #11151D, 1 px #1C2130 border, max 408 px, 3 lines, 8 s, ONE per pip: the person's own
                 moderated words verbatim (the on-frame echo of chat now the log is gone)
    plates       HN Medium 22 on wood, ONE at a time over the marks in view, whole inside the frame, 5 s rotation:
                 `@sami's tent · night 4` (a DRIFT dwell adds ` · last here yesterday`, a day word, never a clock),
                 `flower · @moss_m · today`, `tree · @moss_m · sapling · 3 days`, `field · @moss_m · gold`, `the Shore ·
                 first reached by @kai`, the cairn's plate `3 have walked here · 2 more and the cairn is named` (pinned
                 10 s after every hatch and during the DRIFT Moot dwell; at 0 the forward form `3 more and the cairn is
                 named`) / `cairn · @a @b @c`, a raising `raising · the Ford bridge · for @moss_m` (pinned at its site,
                 the beacon flares) then `the Ford bridge · raised for @moss_m · today` (10 min); a failure: nothing.
                 A camp plate rotates only while its owner is awake or when the DRIFT stop pins it.
    edge arrows  `@kai · 210 paces →` Menlo 22 in their colour on wood at the nearest frame edge for awake pips outside
                 the window
    beacon / hearth / cairn are the scene's sprites: the keeper presence is the beacon, lit or dark, no words.
    degrade      labels_on_speak / bubbles_single from scene.degrade; plates stop rotating at level >= 2; density
                 fallback above 40 awake unchanged; `!kill` -> no name anywhere in this region
  PIP HOLLOW `stream/scenes/hollow.py` `CaveScene`: the cave text layer is kept VERBATIM below (`_text_layer_cave`) so
             the rollback (OPENWORLD 14: the panel importing `hollow` again) is a file swap, not a rewrite.

Honesty (OPENWORLD 12, WORLD.md 11): every name drawn here comes from `scene.entities()` (display_name already filtered)
or from a `world.json` pip record's `display_name` via `shown_name()` (blocklist -> `builder #N`); a seed has no name and
none is drawn (the 3 s hold lives in the scene / ChatBridge, never here). No string in this file names a person. Every
count is a len() the scene or the land computed. Nature words (wind, season, moon, day part) are declared as nature.
`stats()["honesty_violations"]` counts any drawn name whose key is not a world pip.

The panel never returns a placeholder: any text-layer error returns the scene frame bare (one stderr line per burst);
a scene error is already the scene's last good frame. `budget_ms = 24` (WORLD_API 7). Hot reload: the scene instance is
parked on the `stream.panels` package (`_WORLD_SCENE`), so a reload of THIS file keeps the entities when the scene class
is unchanged, and a reload of the scene module (which re-executes this module too) makes a fresh scene from the new
class. The scene class is `steading.SteadingScene` when that module imports, else `hollow.CaveScene`.
"""
from __future__ import annotations

import math
import os
import re
import sys
import time as _time
import traceback
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
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
from stream.world import HOLD_S

try:                                                     # the land scene (built alongside; absent = the cave, the rollback)
    from stream.scenes import steading as _STEADING       # noqa: F401
except Exception as _e:                                  # pragma: no cover - import failure is the documented rollback path
    _STEADING = None
    _STEADING_ERR = repr(_e)
else:
    _STEADING_ERR = None

PLANK_XY = getattr(L, "WORLD_PLANK_XY", (16, 16))
PLANK_ROW2_DY = 40                    # the CAVE's second plank row (rollback path only; the land has one row)
BUBBLE_MAX_W = getattr(L, "WORLD_BUBBLE_MAX_W", 408)
DENSITY_FALLBACK = getattr(L, "WORLD_DENSITY_FALLBACK", 40)
LABEL_FONT, LABEL_SIZE, LABEL_H = "Menlo", 20, 24
BUBBLE_FONT, BUBBLE_SIZE, BUBBLE_LINE_H, BUBBLE_PAD = "Menlo", 22, 26, 10
PLANK_FONT, PLANK_SIZE = "HN Medium", 22
PLANK_MAX_W = 820                     # the plank ends before the cave mouth / lantern column
ROTATE_S = 8.0
SLEEPER_ROTATE_S = 5.0
MOSS_ROTATE_S = 5.0
NOTICE_S = 5.0
PLANK_FADE_S = 0.5                    # a plank line fades out over its last half second (sticky lines never fade)
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

# ----------------------------------------------------------------------------- LONGGRASS text-layer geometry (OPENWORLD 8; full-bleed land, journal 034)
DIAL_R = 32                           # dial_img() is kept for the cave rollback; the land no longer draws a dial
REGION_H = 720
HUD_RESERVE_LEFT = (0, 0, 840, 54)    # the plank row: labels / plates never land under it (fallback; the real box is used)
HUD_BOXES_FALLBACK = (HUD_RESERVE_LEFT,)
# the wood material: one carpenter's work for the plank, the sign, the board, the plates, the arrows and the marker
WOOD = (74, 50, 32)
WOOD_TOP = (232, 214, 178)            # 1 px light top edge
WOOD_BOTTOM = (28, 22, 18)            # 1 px dark bottom edge
WOOD_ALPHA = 235
WOOD_BURN = (192, 178, 150)           # a dim title on the board (the non-leading options)
WOOD_PAD_X, WOOD_PAD_Y = 12, 8        # HN Medium 22 + 2 x 8 = 38 px chip
CREAM_CARVED_T = 0.65                 # the sign's lettering once anyone is awake: cream at 65 % over the wood
SIGN_TEXT = "SAY ANYTHING"
SIGN_FONT, SIGN_SIZE = "AB", 56
SIGN_MAX_W, SIGN_BODY_H = 480, 70
SIGN_PAD_X = 24
SIGN_POST_W, SIGN_POST_H = 6, 26
SIGN_CULL_PX = 300.0
# the MOOT BOARD is STACKED: one row per option, the whole title on every row (fix pass, 2026-09-26: the one-row board
# gave each title 174 px and cut 6 of the 7 menu titles; the vote is the stream's one interaction, so a stranger must read
# what A, B and C ARE). Rows are BOARD_ROW_H tall; the top rail carries `type A, B or C` (0 standing) and the timer.
BOARD_TITLE_MAX_W = 560               # every menu title is <= 320 px whole (`chaos · expedition to the Shore`); only a
                                      # 60-char !idea title can still be cut, and the compositor's board check asserts the
                                      # drawn string == this truncation of the round's title
BOARD_MIN_W = 300
BOARD_ROW_H, BOARD_RAIL_H, BOARD_TOP_RAIL_H = 34, 6, 30
BOARD_LETTER_FONT, BOARD_LETTER_SIZE, BOARD_LETTER_W = "AB", 28, 28
BOARD_TITLE_FONT, BOARD_TITLE_SIZE = "HN Medium", 22
BOARD_TIMER_FONT, BOARD_TIMER_SIZE = "Menlo Bold", 24
BOARD_TIMER_INSET = 12
BOARD_DIVIDER_W = 2
BOARD_SEG_PAD = 8
BOARD_GAP_ABOVE_LETTERS = 6
BOARD_TOP_RAIL_TEXT = "type A, B or C"
BOARD_CLOSING_TEXT = "closing"        # the timer at 0 with the round still open (the manager ships it a tick later): never a frozen 0:00
BOARD_LIT_ALPHA = 44                  # the leading row's band: the accent at this alpha over the wood
BOARD_SHIP_FLARE_S = 1.0
BOARD_H_MAX = BOARD_TOP_RAIL_H + 3 * BOARD_ROW_H + BOARD_RAIL_H   # 138: camera.STONE_TOP_PX = 128 + 6 + this + 2
LETTER_OVER_SPRITE_ALPHA = 0.4        # an A/B/C glyph fades to 40 % while a sprite box intersects it (people over letters)
FUSE_H, EMBER_W = 4, 6
MARKER_FONT, MARKER_SIZE = "Menlo", 22
CAIRN_PIN_S = 10.0                    # the cairn's plate is pinned this long after every hatch
RAISED_PLATE_S = 600.0                # a landed raising keeps its plate in the rotation this long
NEXT_TWO = {"go": "next: camp · plant a flower",
            "camp": "next: plant a flower · fire",
            "plant": "next: go river · camp",
            "fire": "next: camp · plant a flower",
            "vote": "next: camp · plant a flower"}
NEXT_TWO_S = 8.0
STICKY_S, STICKY_CAP_S = 20.0, 60.0    # the newcomer's try-line: seen-time, hard cap
TRY_LINE = "try: go river · plant a flower · camp"
THATS_YOU_S = 4.0                      # `that's you, @kai` rides the 4 s hatch EVENT hold, then the sticky try-line
ROUND_OPEN_LINE = "new round · type A, B or C"
RECONNECT_LINE = "chat is reconnecting…"
PAUSED_LINE = "chat is paused"
IN_HOLD_LINE = "someone new walked in"
CHAT_STATS_FRESH_S = 60.0
_PLANK_LOG = os.environ.get("KL_PLANK_LOG") == "1" and os.environ.get("MODE") == "test"   # test hook: log every plank change
CHIP_FONT, CHIP_SIZE = "HN Medium", 22
CHIP_PAD = 8
CHIP_ALPHAS = (153, 204, 235, 255)    # 60 % base; a hue that misses 4.5:1 over the brightest grass gets the next one
CREAM = (248, 240, 224)               # hud.COLOURS["cream"]: the tint direction for a hue no chip can lift (deep blues / violets)
CONTRAST_MIN = 4.5
GRASS_BRIGHT = ((118, 178, 92), (234, 214, 160), (244, 172, 64))   # spring grass, sand, ripe field (ART.md 4): the sweep backgrounds
LAND_LABEL_H = LABEL_SIZE + 12        # a Menlo 20 chip
PLATE_H = CHIP_SIZE + 2 * WOOD_PAD_Y  # an HN Medium 22 wood plate
PLATE_ROTATE_S = 5.0
PLATE_MAX_W = 640                     # `17 have walked here · 8 more until the Birch Wood opens` whole (HN Medium 22 ~ 600 px)
HATCH_TAG_S = 3.0
ONLY_ONE_S = 10.0
PLACE_LABEL_S = 4.0
PLACE_RETARGET_CELLS = 30.0
EDGE_INSET = 24
WAYSTONE_LETTER_DY = 128              # the AB 56 strip's top this far above the stone's cell (glyph rows 21-63 of the 65 px
                                      # strip, the Menlo 22 count under it ends at strip top + 80 = cy - 48): clears the stone's
                                      # top and a tier-3 voter's head (86 px tall at 1.2x) on behaviour's first standing row
                                      # (STAND_Y0 = 9 cells south -> head top cy - 43). QA night frame 599 had '2' over a face.
LETTER_STACK_H = 80                   # strip top -> count bottom (see above); a HUD-forced shift may lower the stack until the
                                      # count sits on the stone (cy - 2), never further; else all three letters are culled together
WAYSTONE_LETTER_WIDE = (40, 100, 62)  # (AB size, strip DY, stack H) at 0.75x: the stones are 36 px apart there and an AB 56
                                      # glyph is 44 px wide, so the letters overprinted as one `ABC` smear (live tile, research)
OPTIONS_ROW_MAX_STEPS = 4
HUT_SPRITE_W, HUT_SPRITE_H = 32 + 2 * 3 + 4, 32 + 10 + 4   # buildings._hut: T + 2*OVERHANG + 4 wide (per tile), T + ROOF_RISE + 4 tall
HUT_SPRITE_DX, HUT_SPRITE_DY = 3 + 2, 10 + 2               # the footprint origin inside the sprite (OVERHANG + 2, ROOF_RISE + 2)
CAMP_TO_BUILDING = {0: None, 1: 0, 2: 1, 3: 2}             # camp tier -> hut tier (bake.py); a hollow has no sprite, only its footprint
FORBIDDEN_MIN_LEN = 3
CAMP_FOOTPRINT = {0: (8, 6), 1: (10, 8), 2: (14, 12), 3: (14, 12)}   # cells (OPENWORLD 5.3)
TIER_H_PX = (26, 30, 34, 42)          # standing heights at 1x (ART.md 2) for a screen box when the scene gives none
LEGEND_LAND = (TRY_LINE, "feed · pet · gift @name · sow · stack · swim", "!idea <text> · !theme <preset> · !stats · !help")
ARROWS = {"left": "←", "right": "→", "top": "↑", "bottom": "↓"}
MARKER_GLYPHS = {"left": "◂", "right": "▸", "top": "▴", "bottom": "▾"}

_LONELY_RE = re.compile(r"\b(anyone|anybody|here|hello|alone|else|nobody|empty|dead)\b", re.IGNORECASE)


def _mss(sec) -> str:
    """`1:27`: the vote card's timer and the plank's `closes in` tail (m:ss, no leading zero)."""
    sec = max(0, int(sec or 0))
    return "%d:%02d" % (sec // 60, sec % 60)


# HelveticaNeue has no arrows: U+2192 rendered as .notdef on the board (`C chaos ▯ follow…`, night0 frame 299). Every
# string drawn through an HN face passes through here first; Menlo keeps its arrows (edge arrows, the Moot marker).
_HN_GLYPH_MAP = {"→": "·", "←": "·", "↑": "·", "↓": "·", "▸": "·", "◂": "·", "✓": "·", "✗": "·"}


def hn_safe(text: str) -> str:
    """Map the glyphs HelveticaNeue lacks to the middle dot the wood already speaks in."""
    t = str(text or "")
    if any(ch in t for ch in _HN_GLYPH_MAP):
        for a, b in _HN_GLYPH_MAP.items():
            t = t.replace(a, b)
        t = re.sub(r"(?:\s*·\s*){2,}", " · ", t)
    return t


def board_title(title: Any) -> str:
    """The string the MOOT BOARD draws for a round option's title: non-BMP stripped, HN-safe glyphs, whole up to
    BOARD_TITLE_MAX_W (the compositor's board check uses this same function for its expectation)."""
    t = hn_safe(L.strip_non_bmp(str(title or ""))).strip()
    return L.truncate(BOARD_TITLE_FONT, BOARD_TITLE_SIZE, t, BOARD_TITLE_MAX_W) if t else ""


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


def _scene_class():
    """SteadingScene when stream/scenes/steading.py imports and defines it, else the cave (the rollback)."""
    cls = getattr(_STEADING, "SteadingScene", None) if _STEADING is not None else None
    return cls or H.CaveScene


def _attach_tenders(sc) -> None:
    """The keepers (milestone carves / raisings, keeper-build announcements; wraps scene.frame, idempotent) and the
    honesty monitor (every frame after the scene: forged entities removed, counts/names/text cross-checked against the
    real records). Both live on the scene instance so a panel-only reload finds them already attached."""
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


def _make_scene():
    cls = _scene_class()
    prev = getattr(_PKG, "_WORLD_SCENE", None)
    if prev is not None and type(prev) is cls:               # same class object: a panel-only reload keeps the colony
        sc = prev
    else:
        if prev is not None and hasattr(prev, "save_now"):    # the scene being replaced flushes world.json first (12: camps are promises)
            try:
                prev.save_now()
            except Exception:
                pass
        try:
            sc = cls(run_dir=_run_dir(), log=lambda m: _log("scene: %s" % m))
        except Exception as e:
            if cls is not H.CaveScene:                        # a broken land scene falls back to the cave, loudly (14: rollback)
                _log("%s failed to construct (%r); falling back to the cave" % (cls.__name__, e))
                if prev is not None and type(prev) is H.CaveScene:
                    sc = prev
                else:
                    sc = H.CaveScene(run_dir=_run_dir(), log=lambda m: _log("scene: %s" % m))
            else:
                raise
        _PKG._WORLD_SCENE = sc
    _attach_tenders(sc)
    return sc


SCENE = _make_scene()
if _STEADING_ERR:
    _log("steading scene not importable (%s): the cave is the scene" % _STEADING_ERR)


def scene():
    """The live scene (other panels read counts and names through this; never construct a second one)."""
    return getattr(_PKG, "_WORLD_SCENE", None) or SCENE


def is_land(sc=None) -> bool:
    """True when the scene is the LONGGRASS land (it carries a camera, a land and nature); False for the cave."""
    sc = sc if sc is not None else scene()
    return getattr(sc, "camera", None) is not None and (getattr(sc, "land", None) is not None
                                                          or getattr(getattr(sc, "world", None), "land", None) is not None)


def scene_kind() -> str:
    return "steading" if is_land() else "hollow"


def camera():
    """The scene's Camera (stream/world/camera.py) or None on the cave."""
    return getattr(scene(), "camera", None)


def land():
    """The scene's Land (stream/world/land.py) or None on the cave / before boot."""
    sc = scene()
    ld = getattr(sc, "land", None)
    if ld is None and getattr(sc, "world", None) is not None:
        ld = getattr(sc.world, "land", None)
    return ld


def nature():
    return getattr(scene(), "nature", None)


def terrain():
    return getattr(scene(), "terrain", None)


def keepers() -> Optional[K.Keepers]:
    """The Keepers attached to the live scene (colony / keeper strips read carve state through this)."""
    return getattr(scene(), "keepers", None)


def world_degrade() -> Optional[Dict[str, Any]]:
    """scene.degrade (glow / labels_on_speak / bubbles_single / level, + clouds / zoom_pinned on the land) or None."""
    sc = scene()
    return dict(sc.degrade) if (sc is not None and getattr(sc, "booted", False)) else None


def honesty_line() -> Optional[str]:
    mon = getattr(scene(), "honesty", None)
    return mon.line() if mon is not None else None


def honesty_summary() -> Optional[Dict[str, Any]]:
    mon = getattr(scene(), "honesty", None)
    return mon.summary() if mon is not None else None


def world_counts() -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """(awake, asleep, hatched_ever) as len() over the scene's real records, or (None, None, None) before boot."""
    sc = scene()
    if sc is None or not getattr(sc, "booted", False):
        return None, None, None
    return sc.awake_count(), sc.asleep_count(), sc.hatched_ever()


def world_info(now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """What the copy panels (the land strip, header, readout) may draw about the land: every number a len(), every
    nature word from nature.py. None on the cave or before boot."""
    sc = scene()
    if not is_land(sc) or not getattr(sc, "booted", False):
        return None
    out: Dict[str, Any] = {"kind": "steading"}
    try:
        ld = land()
        t = float(now if now is not None else (getattr(sc, "_last_now", None) or 0.0))
        if ld is not None:
            out.update(ld.counts(t))
            out["ladder"] = ld.ladder()
        nt = nature()
        if nt is not None:
            d = nt.describe(t) if t else nt.describe()
            out.update({"clock": d.get("clock"), "world_clock": d.get("world_clock"), "day_part": d.get("day_part"),
                        "season": d.get("season"), "wind": d.get("wind"), "moon": d.get("moon"), "weather": d.get("weather"),
                        "world_day": d.get("world_day"), "hemisphere": d.get("hemisphere")})
        cam = camera()
        if cam is not None:
            out["camera"] = cam.stats()
        bk = getattr(sc, "bakes", None) or getattr(sc, "bake", None)
        if bk is not None:
            out["baking"] = bool(getattr(bk, "baking", False))
        out["awake"], out["asleep"], out["settled_pips"] = sc.awake_count(), sc.asleep_count(), sc.hatched_ever()
    except Exception:
        pass
    return out


def shown_name(raw: Optional[str]) -> Optional[str]:
    """The filtered display name for a username: the pip record's stored display_name (blocklist -> `builder #N`)
    or, for a name with no pip yet, the world's name filter. None before boot (then draw nothing)."""
    if not raw:
        return None
    sc = scene()
    if sc is None or not getattr(sc, "booted", False) or sc.world is None:
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
    if sc is None or not getattr(sc, "booted", False) or sc.world is None:
        return None
    p = sc.world.pip(str(raw).lower().lstrip("@"))
    if p is None:
        return None
    return p.get("display_name") or ("builder #%s" % (p.get("n") if p.get("n") is not None else "?"))


_WHEN: Dict[Tuple, str] = {}


def when_text(ts_iso: Optional[str], now: float) -> str:
    """A real timestamp in local words: `21:14`, `yesterday 10:40`, `Sep 24 10:40`; `--` when unknown. Memoised per
    (timestamp, minute of now): plates ask for dozens per frame and the answer only moves at midnight."""
    key = (ts_iso, int(now // 60))
    s = _WHEN.get(key)
    if s is not None:
        return s
    t = iso_to_epoch(ts_iso) if isinstance(ts_iso, str) else (float(ts_iso) if ts_iso else None)
    if t is None:
        s = "--"
    else:
        lt, ln = _time.localtime(t), _time.localtime(now)
        hm = _time.strftime("%H:%M", lt)
        if (lt.tm_year, lt.tm_yday) == (ln.tm_year, ln.tm_yday):
            s = hm
        elif (lt.tm_year, lt.tm_yday + 1) == (ln.tm_year, ln.tm_yday) or (lt.tm_year + 1 == ln.tm_year and ln.tm_yday == 1):
            s = "yesterday " + hm
        else:
            s = _time.strftime("%b %d ", lt) + hm
    if len(_WHEN) > 2000:
        _WHEN.clear()
    _WHEN[key] = s
    return s


# ----------------------------------------------------------------------------- cached text strips
_TEXT: Dict[Tuple, Image.Image] = {}
# every string the LONGGRASS text layer builds this frame (cached or not): after the layer the panel asserts none of
# them carries a raw hidden / blocklisted / quarantined username (OPENWORLD 12 "nameless until the hold", "builder #N
# on every surface"). `_OURS` is the subset this panel wrote itself (plank, plates, board, sign, marker, arrows, letters):
# the compositor's copy check runs the owner's banned-token list over it; a person's own words (bubbles, labels) are
# excluded, and @tokens are stripped before matching.
_DRAWN: List[str] = []
_OURS: List[str] = []
_COLLECT = [False]
_FORBIDDEN_RE: Dict[frozenset, Any] = {}


def _note_drawn(text: str, ours: bool = True) -> None:
    if _COLLECT[0]:
        _DRAWN.append(text)
        if ours:
            _OURS.append(text)


def text_strip(font: str, size: int, text: str, colour, stroke: bool = True, ours: bool = True) -> Image.Image:
    """RGBA strip of `text` drawn at (1, 0) with a 1 px bg-coloured stroke (legible over glow). Cached per string."""
    key = (font, size, text, colour, stroke)
    _note_drawn(text, ours)
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


_FADED: Dict[Tuple, Tuple[Image.Image, Image.Image]] = {}


def _faded(im: Image.Image, k: float) -> Image.Image:
    """`im` with its alpha scaled by k (cached per source strip: the A/B/C glyphs while a sprite crosses them). The
    source is kept in the cache entry so its id() can never be reused by another strip while the entry lives."""
    key = (id(im), int(k * 100))
    hit = _FADED.get(key)
    if hit is not None and hit[0] is im:
        return hit[1]
    out = im.copy()
    out.putalpha(out.getchannel("A").point(lambda v: int(v * k)))
    if len(_FADED) > 64:
        _FADED.clear()
    _FADED[key] = (im, out)
    return out


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
    """The cave's plank: HN Medium 22 on a panel-coloured board with a hairline edge (the fiction's wooden sign)."""
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


# ----------------------------------------------------------------------------- LONGGRASS chips (60 % dark, rounded) + contrast
_CHIP: Dict[Tuple, Image.Image] = {}


def chip_img(text: str, colour, face: str = CHIP_FONT, size: int = CHIP_SIZE, alpha: int = CHIP_ALPHAS[0],
             max_w: Optional[int] = None, stroke: bool = False, ours: bool = True) -> Image.Image:
    """Text on a rounded dark contrast chip: labels (a person's colour needs the alpha ladder). Cached per string."""
    key = (text, colour, face, size, alpha, max_w, stroke)
    _note_drawn(text, ours)
    im = _CHIP.get(key)
    if im is not None:
        return im
    if max_w:
        text = L.truncate(face, size, text, max_w - 2 * CHIP_PAD)
    f = L.font(face, size)
    tw = L.text_width(face, size, text)
    w, h = tw + 2 * CHIP_PAD, size + 12
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im, "RGBA")
    d.rounded_rectangle([0, 0, w - 1, h - 1], 6, fill=tuple(list(L.hex_rgb(L.COLORS["bg"])) + [int(alpha)]))
    if stroke:
        d.text((CHIP_PAD, 4), text, font=f, fill=colour, stroke_width=1, stroke_fill=L.COLORS["bg"])
    else:
        d.text((CHIP_PAD, 4), text, font=f, fill=colour)
    if len(_CHIP) > TEXT_CACHE_MAX:
        for k in list(_CHIP)[:TEXT_CACHE_MAX // 2]:
            _CHIP.pop(k, None)
    _CHIP[key] = im
    return im


_ROW: Dict[Tuple, Image.Image] = {}


def row_chip(segs: Sequence[Tuple[str, Any]], face: str = LABEL_FONT, size: int = LABEL_SIZE, alpha: int = CHIP_ALPHAS[1]) -> Image.Image:
    """Several coloured text segments side by side on ONE rounded dark chip (the guaranteed A/B/C options row: the
    letters in the carved colour, the leading option's title in the accent, the rest in text2). Cached per row."""
    key = (tuple((str(t), str(c)) for t, c in segs), face, size, alpha)
    im = _ROW.get(key)
    for t, _c in segs:
        _note_drawn(str(t))
    if im is not None:
        return im
    f = L.font(face, size)
    widths = [L.text_width(face, size, str(t)) for t, _c in segs]
    w, h = sum(widths) + 2 * CHIP_PAD, size + 12
    im = Image.new("RGBA", (max(1, w), h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im, "RGBA")
    d.rounded_rectangle([0, 0, w - 1, h - 1], 6, fill=tuple(list(L.hex_rgb(L.COLORS["bg"])) + [int(alpha)]))
    x = CHIP_PAD
    for (t, c), tw in zip(segs, widths):
        d.text((x, 4), str(t), font=f, fill=c, stroke_width=1, stroke_fill=L.COLORS["bg"])
        x += tw
    if len(_ROW) > 200:
        _ROW.clear()
    _ROW[key] = im
    return im


def _lum(rgb: Sequence[float]) -> float:
    def ch(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb[:3]
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast_ratio(fg: Sequence[float], bg: Sequence[float]) -> float:
    """WCAG contrast ratio of two RGB triples."""
    a, b = _lum(fg), _lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


_CHIP_ALPHA: Dict[str, Tuple[str, int]] = {}


def _passes(fg: Sequence[float], alpha: int) -> bool:
    chip = L.hex_rgb(L.COLORS["bg"])
    k = alpha / 255.0
    for grass in GRASS_BRIGHT:
        bg = tuple(chip[i] * k + grass[i] * (1 - k) for i in range(3))
        if contrast_ratio(fg, bg) < CONTRAST_MIN:
            return False
    return True


def label_style(colour_hex: str) -> Tuple[str, int]:
    """(text colour, chip alpha) for a creature label (OPENWORLD 7.5 gate 2): the darkest-needed of CHIP_ALPHAS so the
    label reads >= 4.5:1 over the chip composited on the brightest grass, sand and ripe field. A failing hue gets a darker
    chip, never a different hue; the wheel's deep blues and violets (luminance ~0.14) miss 4.5:1 even on an opaque chip,
    so those keep their hue and are lightened toward cream in 10 % steps only as far as the ratio needs. Cached."""
    hit = _CHIP_ALPHA.get(colour_hex)
    if hit is not None:
        return hit
    try:
        fg = L.hex_rgb(colour_hex)
    except Exception:
        fg = (230, 232, 238)
    out = None
    for alpha in CHIP_ALPHAS:
        if _passes(fg, alpha):
            out = (colour_hex, alpha)
            break
    if out is None:
        col = fg
        for step in range(1, 10):
            t = step / 10.0
            col = tuple(int(round(fg[i] + (CREAM[i] - fg[i]) * t)) for i in range(3))
            if _passes(col, CHIP_ALPHAS[-1]):
                break
        out = ("#%02X%02X%02X" % col, CHIP_ALPHAS[-1])
    _CHIP_ALPHA[colour_hex] = out
    return out


def chip_alpha(colour_hex: str) -> int:
    return label_style(colour_hex)[1]


def label_colour(colour_hex: str) -> str:
    return label_style(colour_hex)[0]


def label_chip(text: str, colour_hex: str) -> Image.Image:
    """A creature label: Menlo 20 in the creature's colour, stroked, on its contrast chip (the person's name: not ours)."""
    col, alpha = label_style(colour_hex)
    return chip_img(text, col, LABEL_FONT, LABEL_SIZE, alpha, stroke=True, ours=False)


# ----------------------------------------------------------------------------- the wood material (journal 034)
_WOOD: Dict[Tuple, Image.Image] = {}


def wood_board(w: int, h: int) -> Image.Image:
    """An opaque-ish plank of wood: WOOD fill at alpha 235, a 1 px light top edge and a 1 px dark bottom edge, a 2 px
    drop shadow. The one material every text object on the land is made of."""
    key = ("board", w, h)
    im = _WOOD.get(key)
    if im is not None:
        return im
    im = Image.new("RGBA", (w + 2, h + 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im, "RGBA")
    d.rectangle([2, 2, w + 1, h + 1], fill=(0, 0, 0, 90))                    # shadow
    d.rectangle([0, 0, w - 1, h - 1], fill=WOOD + (WOOD_ALPHA,))
    d.line([(0, 0), (w - 1, 0)], fill=WOOD_TOP + (255,), width=1)
    d.line([(0, h - 1), (w - 1, h - 1)], fill=WOOD_BOTTOM + (255,), width=1)
    if len(_WOOD) > 400:
        _WOOD.clear()
    _WOOD[key] = im
    return im


def wood_chip(text: str, colour=CREAM, face: str = CHIP_FONT, size: int = CHIP_SIZE, max_w: Optional[int] = None,
              ours: bool = True) -> Image.Image:
    """Text (cream by default, 1 px dark stroke) on a wood plank: the plank, plates, arrows, the Moot marker. Cached."""
    if face.startswith("HN"):
        text = hn_safe(text)
    key = ("chip", text, tuple(colour) if not isinstance(colour, str) else colour, face, size, max_w)
    _note_drawn(text, ours)
    im = _WOOD.get(key)
    if im is not None:
        return im
    if max_w:
        text = L.truncate(face, size, text, max_w - 2 * WOOD_PAD_X)
    f = L.font(face, size)
    tw = L.text_width(face, size, text)
    w, h = tw + 2 * WOOD_PAD_X, size + 2 * WOOD_PAD_Y
    im = wood_board(w, h).copy()
    d = ImageDraw.Draw(im, "RGBA")
    d.text((WOOD_PAD_X, WOOD_PAD_Y - 3), text, font=f, fill=colour, stroke_width=1, stroke_fill=WOOD_BOTTOM)
    if len(_WOOD) > 400:
        _WOOD.clear()
    _WOOD[key] = im
    return im


def wood_contrast(alpha: int = WOOD_ALPHA) -> float:
    """Cream over the wood chip composited on the brightest noon sand: the gate the material must clear (>= 4.5:1)."""
    k = alpha / 255.0
    worst = 99.0
    for grass in GRASS_BRIGHT:
        bg = tuple(WOOD[i] * k + grass[i] * (1 - k) for i in range(3))
        worst = min(worst, contrast_ratio(CREAM, bg))
    return worst


def _colour_of(sc, key: Optional[str], e: Optional[Dict[str, Any]] = None, preset: Optional[str] = None) -> str:
    """The creature's colour: the entity's (the scene reads the genome), else the pip row's `colour`, else the cave hash."""
    if e is not None and e.get("colour"):
        return str(e["colour"])
    if key and getattr(sc, "world", None) is not None:
        p = sc.world.pip(key) or {}
        if p.get("colour"):
            return str(p["colour"])
    return P.colour_hex(key or "", preset)


# ----------------------------------------------------------------------------- the time dial (sun / real-phase moon)
_DIAL: Dict[Tuple, Image.Image] = {}


def dial_img(hour: float, moon_phase: float, night: float) -> Image.Image:
    """64x64 (+ a chip margin): the sun on a day arc east -> west, or the real-phase moon on the night arc, over a
    ground stripe. The sky is read from the dial because a top-down land has no sky band (OPENWORLD 2.2)."""
    key = (round(hour * 20) / 20.0, round(moon_phase, 2), round(night, 2))
    im = _DIAL.get(key)
    if im is not None:
        return im
    r = DIAL_R
    disc = Image.new("RGBA", (2 * r, 2 * r), (0, 0, 0, 0))
    dd = ImageDraw.Draw(disc)
    day_top, day_bot = np.array((120, 160, 220)), np.array((236, 200, 150))
    night_top, night_bot = np.array((34, 40, 78)), np.array((70, 76, 120))
    top = day_top * (1 - night) + night_top * night
    bot = day_bot * (1 - night) + night_bot * night
    for row in range(2 * r):
        t = row / (2 * r - 1)
        c = tuple(int(v) for v in (top * (1 - t) + bot * t))
        dd.line([(0, row), (2 * r, row)], fill=c + (255,))
    ground = tuple(int(v) for v in np.array((74, 100, 50)) * (1 - night) + np.array((40, 52, 60)) * night)
    dd.rectangle([0, r + 10, 2 * r, 2 * r], fill=ground + (255,))
    dd.line([(0, r + 10), (2 * r, r + 10)], fill=(30, 40, 30, 255), width=2)
    if night < 0.5:                                           # the sun: east (right) at 06:00, west (left) at 18:00
        t = (hour - 6.0) / 12.0
        ang = math.pi * (1 - min(1.0, max(0.0, t)))
        px_, py_ = r + math.cos(ang) * (r - 12), r + 10 - math.sin(ang) * (r - 8)
        dd.ellipse([px_ - 7, py_ - 7, px_ + 7, py_ + 7], fill=(255, 226, 140, 255))
    else:                                                     # the moon takes the night arc, with its real phase
        t = ((hour - 18.0) % 24.0) / 12.0
        ang = math.pi * (1 - min(1.0, max(0.0, t)))
        px_, py_ = r + math.cos(ang) * (r - 12), r + 10 - math.sin(ang) * (r - 8)
        dd.ellipse([px_ - 7, py_ - 7, px_ + 7, py_ + 7], fill=(235, 235, 225, 255))
        k = math.cos(2 * math.pi * moon_phase)
        if abs(k) > 0.05:
            off = 7 * k
            dd.ellipse([px_ - 7 + off, py_ - 7, px_ + 7 + off, py_ + 7], fill=(48, 54, 92, 255))
        for (sx, sy) in ((12, 10), (44, 16), (30, 6), (52, 30)):
            dd.point((sx, sy), fill=(255, 255, 255, 255))
    m = Image.new("L", (2 * r, 2 * r), 0)
    ImageDraw.Draw(m).ellipse([0, 0, 2 * r - 1, 2 * r - 1], fill=255)
    disc.putalpha(m)
    im = Image.new("RGBA", (2 * r + 8, 2 * r + 8), (0, 0, 0, 0))
    ImageDraw.Draw(im, "RGBA").rounded_rectangle([0, 0, 2 * r + 7, 2 * r + 7], 8, fill=tuple(list(L.hex_rgb(L.COLORS["bg"])) + [CHIP_ALPHAS[0]]))
    im.alpha_composite(disc, (4, 4))
    if len(_DIAL) > 64:
        _DIAL.clear()
    _DIAL[key] = im
    return im


# ----------------------------------------------------------------------------- the label placer (from the cave)
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

    def place_down(self, x0: int, y0: int, w: int, h: int, step: int, max_steps: int, ceiling: int = 10 ** 6) -> Optional[int]:
        """Like place_up() downward: None (nothing reserved) when no free row is found within max_steps."""
        y = y0
        for _ in range(max_steps + 1):
            if y + h > ceiling:
                return None
            if self._free(x0, y, x0 + w, y + h):
                self.boxes.append((x0, y, x0 + w, y + h))
                return y
            y += step
        return None

    def place_either(self, x0: int, y0: int, w: int, h: int, step: int, max_steps: int, floor: int, ceiling: int) -> Optional[int]:
        """Up first, then below (the gate mockup's plate rule); None when neither side has room."""
        y = self.place_up(x0, y0, w, h, step, max_steps, floor)
        if y is not None:
            return y
        y = y0 + step
        for _ in range(max_steps):
            if y + h > ceiling:
                return None
            if self._free(x0, y, x0 + w, y + h):
                self.boxes.append((x0, y, x0 + w, y + h))
                return y
            y += step
        return None


def _days_ago_text(t0: Optional[float], now: float) -> str:
    """`today` / `yesterday` / `N days ago` from a real timestamp (calendar days in local time); `today` when unknown."""
    if t0 is None:
        return "today"
    try:
        d0 = _time.localtime(float(t0))
        d1 = _time.localtime(float(now))
        days = int((_time.mktime((d1.tm_year, d1.tm_mon, d1.tm_mday, 0, 0, 0, 0, 0, -1)) -
                    _time.mktime((d0.tm_year, d0.tm_mon, d0.tm_mday, 0, 0, 0, 0, 0, -1))) // 86400)
    except Exception:
        return "today"
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return "%d days ago" % days


def _hud_bottom_under(x0: int, y0: int, x1: int, y1: int, boxes: Sequence[Tuple[int, int, int, int]]) -> Optional[int]:
    """The lowest bottom edge among the top-hanging HUD boxes a box overlaps, or None when it overlaps none."""
    out = None
    for bx0, by0, bx1, by1 in boxes:
        if by0 > 0:
            continue
        if x0 < bx1 and bx0 < x1 and y0 < by1 and by0 < y1:
            out = by1 if out is None else max(out, by1)
    return out


def _in_hud(x0: int, y0: int, x1: int, y1: int, boxes: Optional[Sequence[Tuple[int, int, int, int]]] = None) -> bool:
    """True when a box would sit under the plank: this frame's actual chip box when given, else the reserve constant."""
    for bx0, by0, bx1, by1 in (boxes if boxes else HUD_BOXES_FALLBACK):
        if x0 < bx1 and bx0 < x1 and y0 < by1 and by0 < y1:
            return True
    return False


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
        self.name_leaks = 0                           # drawn strings carrying a raw hidden / blocklisted / quarantined name (must stay 0)
        self._leaks_logged = 0
        self.last_stone_counts: Dict[str, str] = {}  # letter -> the count string drawn over the stone
        self.last_stone_n: Dict[str, int] = {}       # letter -> len(standing) the letters were drawn with
        self.last_board_drawn = False                # the MOOT BOARD was on the frame (self-test surface)
        self.last_board_lit: Optional[str] = None    # the letter whose segment is lit (None on a tie / zero)
        self.last_board_titles: Dict[str, str] = {}  # letter -> the title string the board drew (truncated at 230 px)
        self.last_board_timer: Optional[str] = None
        self.last_marker: Optional[str] = None       # the Moot edge marker text when drawn
        self.last_sign_in_view = False
        self.last_stones_in_view = 0
        self.last_beacon_in_view = False
        self.last_marks_in_view = 0                  # real marks / camps whose anchor was inside the frame
        self.last_sleepers_in_view = 0
        self.last_tile_px = 0.0                      # tallest creature + name chip on the frame, in px at 284 wide
        self.last_copy: List[str] = []               # every string this panel wrote itself this frame (copy check)
        self._board_img: Optional[Image.Image] = None
        self._board_key = None
        self._board_titles: Dict[str, str] = {}
        self._sign_img: Optional[Image.Image] = None
        self._sign_key = None
        self._cairn_pin_until = 0.0                  # the cairn's plate is pinned after every hatch
        self._plank_until: Optional[float] = None    # when the current plank line ends (for the fade), None = sticky
        self._go_pending: Dict[str, float] = {}       # key -> t of a verb-walk (`go`) whose arrival earns a next-two hint
        self._verbed: set = set()                     # keys that used a verb this session (the newcomer sticky ends)
        self._round_seen: Optional[float] = None      # the round opened_t last seen (round-open notice once per round)
        self._breath_t: Dict[str, float] = {}         # key -> t of its hatch / first breath (the hearth it lights is not a verb)
        self.last_hud_boxes: List[Tuple[int, int, int, int]] = list(HUD_BOXES_FALLBACK)
        self.last_sprite_boxes = 0
        self._notices: List[Dict[str, Any]] = []      # {start, until, text, colour, named}
        self._care: Dict[str, Tuple[str, float]] = {}
        self._hatch_tag: Dict[str, Tuple[str, float]] = {}
        self._only_light: Optional[Tuple[str, float]] = None
        self._label_override: Dict[str, Tuple[str, float]] = {}
        self._ms: List[float] = []
        self._text_ms: List[float] = []
        self._frames = 0
        self._errors = 0
        self.honesty_violations = 0
        self._last_counts = (0, 0)
        self.last_plank: Optional[str] = None            # the plank text of the last frame (compositor vote-ack check)
        self.last_plank_row2: Optional[str] = None       # always None on the land (one row; kept for the cave path)
        self.last_placed: List[Tuple[int, int, int]] = []
        self.last_plates: List[str] = []                 # plate texts drawn last frame (QA)
        self.last_arrows: List[str] = []
        self._alone_since: Optional[float] = None       # WORLD.md 10: one person, dead night
        self._alone_prompted = False
        self._sleepers_lit_until = 0.0
        self._lonely_t = -1e9                            # the last loneliness plank (the 45 s prompt and the `anyone?` answer never stack)
        # land-only state
        self._place: Optional[Tuple[str, float]] = None  # (label, until) bottom-left place label after a retarget
        self._cam_target: Optional[Tuple[float, float]] = None
        self._cam_mode: Optional[str] = None
        self._plate_slot: Optional[int] = None           # frozen rotation slot while plates are static (degrade >= 2)
        self._marks_cache: Tuple[float, int, List] = (-1e9, -1, [])   # plate texts rebuilt at most once a second
        self._camps: List[Dict[str, Any]] = []          # land.camps() / fields() once per frame (both walk every pip row)
        self._fields: List[Dict[str, Any]] = []

    def inputs(self, ctx):
        return ctx.frame                              # the sim moves every frame

    # ------------------------------------------------------------------ names
    @staticmethod
    def _names_on(ctx) -> bool:
        if ctx.chat_display is False:
            return False
        cfg = ctx.chat_cfg or {}
        return cfg.get("display") is not False

    def _shown(self, sc, key: Optional[str]) -> Optional[str]:
        """@-less display name for a pip key; None when there is no such real pip (then nothing is drawn)."""
        if not key:
            return None
        p = sc.world.pip(key)
        if p is None:
            self.honesty_violations += 1
            return None
        return p.get("display_name") or ("builder #%s" % (p.get("n") if p.get("n") is not None else "?"))

    def _label_text(self, sc, e: Dict[str, Any]) -> Optional[str]:
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
                prio: int = PRIO_EVENT, sticky: bool = False, key: Optional[str] = None, cap: Optional[float] = None,
                tie: bool = False) -> None:
        """Queue a plank line. `prio` decides who wins when several are live (person-facing lines outrank world events;
        never last-appended-wins). `sticky` lines count only the seconds they were actually shown toward `dur` (a vote
        ack or a refusal covering them pauses their clock), capped at 2.5 x dur."""
        st = start if start is not None else now
        self._notices.append({"start": st, "until": st + dur, "dur": dur, "shown": 0.0, "hard_until": st + (cap if cap else dur * 2.5),
                              "text": text, "colour": colour, "named": named, "prio": int(prio), "sticky": bool(sticky), "key": key,
                              "tie": bool(tie)})
        if len(self._notices) > 16:
            self._notices.sort(key=lambda n: (n["prio"], n["start"]))
            del self._notices[:-16]

    def _consume_events(self, sc, ctx, now: float, accent: str, land_mode: bool = False) -> None:
        w = sc.world
        names_on_ev = self._names_on(ctx)
        # first breath lights the hearth for the newcomer (steading 3.1): that `hearth` event, which lands a frame or two
        # after the first_light, is not the `fire` verb (it must not end the sticky or earn a hint)
        for ev in sc.events or []:
            if ev.get("type") in ("first_light", "first_breath", "hatch") and ev.get("pip"):
                self._breath_t[ev["pip"]] = now
        for ev in sc.events or []:
            typ = ev.get("type")
            try:
                if typ == "seed" and land_mode:
                    # inside the 3 s hold (nameless): a typist whose camera is mid-EVENT elsewhere sees a landing within one
                    # frame; the line names no one and ends at the hatch. Test pips (origin test) say nothing.
                    ent = sc.behaviour.get(ev.get("key")) if ev.get("key") else None
                    if ent is None or getattr(ent, "origin", "chat") != "test":
                        self._notice(now, IN_HOLD_LINE, L.COLORS["text"], dur=HOLD_S + 1.5, named=False, prio=PRIO_YOU, key="seed:" + str(ev.get("key") or ""))
                elif typ == "sink":
                    if not land_mode:
                        self._notice(now, "the soil did not take that one", L.COLORS["text2"], named=False)
                    self._end_sticky("seed:" + str(ev.get("key") or ev.get("pip") or ""))
                elif typ == "hatch":
                    key = ev.get("pip")
                    p = w.pip(key) if key else None
                    if p is not None and p.get("n") is not None:
                        self._hatch_tag[key] = ("#%d" % int(p["n"]), now + HATCH_TAG_S)
                    if ev.get("only_light") and key and not land_mode:
                        self._only_light = (key, now + ONLY_ONE_S)
                    nm = self._shown(sc, key)
                    if land_mode:
                        self._end_sticky("seed:" + str(key or ""))
                        self._cairn_pin_until = now + CAIRN_PIN_S
                    if land_mode and nm:
                        if sc.awake_count() <= 1:
                            # `that's you` pairs with the 1.5x hatch cut (the strongest ownership ack), then the try-line
                            # sticks until their first verb (20 s of SEEN time, 60 s cap)
                            self._notice(now, "that's you, @%s" % nm, accent, dur=THATS_YOU_S, prio=PRIO_YOU, key=key)
                            if key not in self._verbed:
                                self._notice(now, "@%s · %s" % (nm, TRY_LINE), L.COLORS["text"], dur=STICKY_S, start=now + THATS_YOU_S,
                                             prio=PRIO_YOU, sticky=True, key=key, cap=STICKY_CAP_S)
                        else:
                            n_ever = int(sc.hatched_ever())
                            self._notice(now, "@%s walked in · %d have walked here" % (nm, n_ever), accent, dur=5.0, prio=PRIO_YOU, key=key)
                    if ev.get("first_ever"):
                        if land_mode:
                            pass
                        else:
                            # WORLD.md 2.2 T+4 to T+10 s: one second after the hatch, for a SEEN 8 s (sticky), above every world line
                            self._notice(now, "that's you. try: feed · pet · dig · plant", L.COLORS["text"], dur=8.0, named=False,
                                         start=now + 1.0, prio=PRIO_YOU, sticky=True)
                            self._notice(now, "your pip sleeps here when you go. it is here tomorrow.", L.COLORS["text2"], dur=6.0,
                                         named=False, start=now + 9.0, prio=PRIO_LIGHT, sticky=True)
                            self._notice(now, "stay ten minutes and your pip grows a row of pixels.", L.COLORS["text2"], dur=6.0,
                                         named=False, start=now + 17.0, prio=PRIO_LIGHT, sticky=True)
                elif typ == "speak":
                    # the cave answers `is anyone here` with the sleepers; the land says nothing (no idle captions, journal 034)
                    if not land_mode and sc.awake_count() == 1 and _LONELY_RE.search(str(ev.get("text") or "")):
                        self._sleepers_lit_until = now + SLEEPERS_LIT_S
                        self._lonely_plank(sc, ev.get("pip"), now, asked=True, land_mode=land_mode)
                elif typ in ("first_light", "first_breath"):
                    nm = self._shown(sc, ev.get("pip"))
                    if nm and not land_mode:
                        self._notice(now, "@%s woke the Hollow · %s" % (nm, _time.strftime("%H:%M", _time.localtime(now))), accent,
                                     dur=FIRST_LIGHT_S, prio=PRIO_LIGHT)
                elif typ == "wake":
                    self._care_line(sc, ev, now)
                    if ev.get("only_light") and ev.get("pip") and not land_mode:
                        self._only_light = (ev["pip"], now + ONLY_ONE_S)
                elif typ == "sleep":
                    nm = self._shown(sc, ev.get("pip"))
                    if nm:
                        q = int(round(float(ev.get("quiet_s") or getattr(sc, "sleep_after_s", 1200.0)) / 60.0))
                        self._label_override[ev["pip"]] = ("@%s · asleep · quiet %d min" % (nm, q), now + 8.0)
                elif typ == "tier_up":
                    nm = self._shown(sc, ev.get("pip"))
                    if nm:
                        self._notice(now, "@%s's %s grew" % (nm, "creature" if land_mode else "pip"), accent, prio=PRIO_VERB)
                elif typ == "forget":
                    nm = self._shown(sc, ev.get("pip"))
                    if nm:
                        self._notice(now, "@%s's %s forgot everything" % (nm, "creature" if land_mode else "pip"), L.COLORS["text"], prio=PRIO_VERB)
                elif typ == "burrowed":
                    reason = str(ev.get("reason") or "")
                    if "hidden" not in reason and "mod" not in reason:          # a hidden user's name never appears
                        nm = self._shown(sc, ev.get("pip"))
                        if nm:
                            verb = "lay down in the grass" if land_mode else "burrowed"
                            self._notice(now, "@%s's %s %s: %s" % (nm, "creature" if land_mode else "pip", verb, reason or "for tonight"), L.COLORS["warn"], prio=PRIO_VERB)
                elif typ in ("feed", "pet", "gift"):
                    by = self._shown(sc, ev.get("by"))
                    nm = self._shown(sc, ev.get("pip"))
                    if by and nm:
                        who = "creature" if land_mode else "pip"
                        if by == nm:
                            line = ("@%s's %s ate a berry" % (nm, who)) if typ == "feed" else ("@%s petted their own %s" % (nm, who))
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
                        what = str(ev.get("kind") or ev.get("mark") or ("flower" if land_mode else "glowmoss"))
                        art = "" if what == "glowmoss" else ("a " if what[:1] not in "aeiou" else "an ")
                        self._notice(now, "@%s plants %s%s" % (nm, art, what) if land_mode else "@%s planted %s%s" % (nm, art, what), accent, prio=PRIO_VERB)
                    if land_mode:
                        self._verb_done(sc, ev.get("pip"), "plant", now)
                # -- LONGGRASS events (OPENWORLD 6, camera EVENT_TYPES); unknown types are ignored, never invented
                elif typ in ("camp", "camp_new"):
                    nm = self._shown(sc, ev.get("pip"))
                    if nm:
                        self._notice(now, "@%s makes camp" % nm, accent, prio=PRIO_VERB)
                    self._verb_done(sc, ev.get("pip"), "camp", now)
                elif typ == "camp_raised":
                    nm = self._shown(sc, ev.get("pip"))
                    if nm:
                        self._notice(now, "@%s's camp · %s · night %d" % (nm, str(ev.get("word") or "camp"), int(ev.get("night") or ev.get("nights") or 1)),
                                     accent, dur=6.0, prio=PRIO_VERB)
                elif typ in ("fire", "hearth"):
                    nm = self._shown(sc, ev.get("pip") or ev.get("by"))
                    if nm:
                        line = ("@%s lights the hearth" % nm) if (typ == "hearth" or ev.get("hearth")) else ("@%s lights a fire" % nm)
                        self._notice(now, line, accent, prio=PRIO_VERB)
                    if now - self._breath_t.get(ev.get("pip") or ev.get("by"), -1e9) > 15.0:
                        self._verb_done(sc, ev.get("pip") or ev.get("by"), "fire", now)
                elif typ == "sow":
                    nm = self._shown(sc, ev.get("pip"))
                    if nm:
                        self._notice(now, "@%s sowed a field" % nm, accent, prio=PRIO_VERB)
                elif typ == "harvest":
                    nm = self._shown(sc, ev.get("pip"))
                    if nm:
                        self._notice(now, "@%s harvests the field" % nm, accent, dur=6.0, prio=PRIO_VERB)
                elif typ == "place" and str(ev.get("kind") or "") == "stone":
                    nm = self._shown(sc, ev.get("pip"))
                    if nm:
                        ld0 = getattr(sc, "land", None)
                        tail = (" · stone %d" % ld0.stock) if ld0 is not None and ld0.stock else ""
                        self._notice(now, "@%s placed a stone on the cairn%s" % (nm, tail), accent, prio=PRIO_VERB)
                elif typ in ("stack", "stone"):
                    nm = self._shown(sc, ev.get("pip") or ev.get("by"))
                    if nm:
                        n = ev.get("stock")
                        tail = (" · stone %d" % int(n)) if n is not None else ""
                        self._notice(now, "@%s stacked a stone on the cairn%s" % (nm, tail), accent, prio=PRIO_VERB)
                elif typ == "cairn_named":
                    self._notice(now, "the cairn is named", accent, dur=8.0, named=False)
                elif typ in ("raising", "raising_ship", "land_open"):
                    name = L.strip_non_bmp(str(ev.get("name") or ""))
                    # a raising (started / landed) is the plate at its site (pinned while raising, 10 min after) and the
                    # beacon's flare; the plank says only that new land is open (a world event, 8 s)
                    if name and typ == "land_open":
                        self._notice(now, "%s is open" % name, accent, dur=8.0, named=False)
                elif typ in ("go", "walk") and land_mode and isinstance(ev.get("to"), str):
                    # a VERB walk (the wander's `to` is a cell pair): the sticky ends and the arrival earns a next-two hint
                    # (the camera needs no subtitle: you can see it moving)
                    key = ev.get("pip")
                    if key and str(ev.get("then") or "idle") == "idle":
                        self._go_pending[key] = now
                        self._verbed.add(key)
                        self._end_sticky(key)
                elif typ == "arrive" and land_mode:
                    key = ev.get("pip")
                    at = str(ev.get("at") or "")
                    if key and at in PLATFORM_LETTERS:
                        self._verb_done(sc, key, "vote", now)
                    elif key and key in self._go_pending:
                        self._go_pending.pop(key, None)
                        self._verb_done(sc, key, "go", now)
                elif typ == "leave_platform" and land_mode:
                    if _PLANK_LOG:
                        _log("leave_platform: %r" % (ev,))       # TEST HOOK (KL_PLANK_LOG=1): the event as evidence
                    self._vote_left(sc, ctx, ev, now, accent)
                elif typ == "swim":
                    nm = self._shown(sc, ev.get("pip"))
                    if nm:
                        self._notice(now, "@%s went for a swim" % nm, L.COLORS["text"], dur=3.0, prio=PRIO_VERB)
                elif typ == "credits_start":
                    n = int(ev.get("count") or 0)
                    if land_mode:
                        self._notice(now, "goodnight · %d walk%s home" % (n, "s" if n == 1 else ""), L.COLORS["text"], dur=3.0, named=False, prio=PRIO_CREDITS)
                    else:
                        self._notice(now, "goodnight. %d pip%s walk home." % (n, "" if n == 1 else "s"), L.COLORS["text"], dur=3.0, named=False, prio=PRIO_CREDITS)
                elif typ == "credits":
                    nm = self._shown(sc, ev.get("pip"))
                    if nm:
                        self._notice(now, "@%s · %d min tonight" % (nm, int(round(float(ev.get("minutes_tonight") or 0)))), L.COLORS["text"], dur=1.5, prio=PRIO_CREDITS)
                elif typ == "credits_end":
                    where = "the land sleeps" if land_mode else "the Hollow sleeps. see you next time."
                    self._notice(now, where, L.COLORS["text2"], dur=20.0, named=False, prio=PRIO_CREDITS)
                # -- keepers (stream/world/keepers.py events ride in scene.events): NOT on the plank. The plank is the
                #    person-facing slot (WORLD.md 2.2); the keeper strip and the land strip show these.
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

    def _lonely_plank(self, sc, key: Optional[str], now: float, asked: bool = False, land_mode: bool = False) -> None:
        """WORLD.md 10 `one person, dead night` (the CAVE): the plank answers loneliness with the real colony. `N sleep
        here` is a len(); the sleeper named is the one nearest the awake pip (a real past chatter); the nearest sleeper
        stirs once. The land says nothing (journal 034: no idle captions; `the wind was already blowing` is a wind word)."""
        if land_mode:
            return
        sleepers = [e for e in sc.behaviour.entities.values() if e.state == "asleep" and e.display_name]
        me = sc.behaviour.get(key) if key else None
        n = len(sleepers)
        if me is not None and sleepers:
            near = min(sleepers, key=lambda e: math.hypot(e.x - me.x, float(getattr(e, "y", 0.0)) - float(getattr(me, "y", 0.0))))
            nm = self._shown(sc, near.key)
            try:
                sc.behaviour.stir(near.key, now)
            except Exception:
                pass
        else:
            near, nm = None, None
        if n == 0:
            if land_mode:
                txt = "nobody else has ever walked here. you're the first." if asked else "you're the only one out here right now. the wind was already blowing."
            else:
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

    def _end_sticky(self, key: Optional[str]) -> None:
        """The newcomer's `that's you` line ends at their first verb."""
        if key:
            self._notices = [n for n in self._notices if not (n.get("sticky") and n.get("key") == key)]

    def _verb_done(self, sc, key: Optional[str], verb: str, now: float) -> None:
        """A verb completed (walk arrived / mark placed / vote counted): the sticky ends and, while the person is alone
        (awake <= 1), the plank offers the next two things for 8 s (priority 3, delivered when relevant)."""
        if not key:
            return
        self._verbed.add(key)
        self._end_sticky(key)
        line = NEXT_TWO.get(verb)
        if line and sc.awake_count() <= 1:
            self._notice(now, line, L.COLORS["text"], dur=NEXT_TWO_S, named=False, start=now + 0.5, prio=PRIO_YOU, key=key)

    def _vote_left(self, sc, ctx, ev: Dict[str, Any], now: float, accent: str) -> None:
        """A standing / walking voter left a stone (behaviour `leave_platform`). The tally is who stands at close
        (rounds tally_source `platforms`), so the plank says the true thing: the vote is dropped (a move to another
        letter is the bridge's vote ack).
        Silent when the round just opened (everyone steps off: the round-open line says so), when the tally is not
        embodied, or when the person is walking home to sleep."""
        key = ev.get("pip")
        left = str(ev.get("platform") or "")
        why = None
        e = sc.behaviour.get(key) if key else None
        nm = self._shown(sc, key) if key else None
        opened = ctx.round_opened_t
        if not key or left not in PLATFORM_LETTERS:
            why = "no key / letter"
        elif str((ctx.round or {}).get("tally_source") or "") != "platforms":
            why = "tally_source %r" % (ctx.round or {}).get("tally_source")
        elif (ctx.round or {}).get("phase") == "ship":
            why = "ship hold"
        elif opened is not None and now - float(opened) < 3.0:
            why = "round just opened"
        elif e is None or e.state == "asleep" or getattr(e, "then", None) in ("sleep", "credits"):
            why = "asleep / walking home"
        elif not nm:
            why = "no shown name"
        if why is not None:
            if _PLANK_LOG:
                _log("vote_left: silent (%s) for %r" % (why, key))    # TEST HOOK (KL_PLANK_LOG=1)
            return
        if e.platform in PLATFORM_LETTERS and e.platform != left:
            return          # moved to another letter: the bridge's same-frame ack (`@x stands at A · light: gold · closes in
                            # 0:28`) already says it; a second `moved to A` line would be the same fact twice (journal 030)
        self._notice(now, "@%s left %s · that vote is dropped" % (nm, left), L.COLORS["warn"], dur=5.0, prio=PRIO_VERB, key=key, tie=True)

    def _care_line(self, sc, ev: Dict[str, Any], now: float) -> None:
        """`back after 2 nights · your tree grew · fed by @kai x2 · gift from @sami` from the REAL care log / land."""
        key = ev.get("pip")
        if not key:
            return
        parts: List[str] = []
        away = ev.get("away_s")
        if away is not None and float(away) >= 6 * 3600:
            nights = max(1, int(round(float(away) / 86400.0)))
            parts.append("back after %d night%s" % (nights, "" if nights == 1 else "s"))
        for g in ev.get("growth") or []:                        # the land's real growth since the last visit (`your tree grew`)
            s = L.strip_non_bmp(str(g))
            if s:
                parts.append(s)
        counts: Dict[Tuple[str, str], int] = {}
        land_mode = getattr(sc, "camera", None) is not None
        for c in (ev.get("care_log") or []) if not land_mode else []:      # the land keeps the real facts short (journal 034)
            by = self._shown(sc, c.get("by"))
            if not by:
                continue
            k = (str(c.get("verb") or "feed"), by)
            counts[k] = counts.get(k, 0) + 1
        for (verb, by), n in sorted(counts.items()):
            word = {"feed": "fed by", "pet": "petted by", "gift": "gift from", "water": "watered by"}.get(verb, verb + " by")
            parts.append("%s @%s%s" % (word, by, (" x%d" % n) if n > 1 else ""))
        if parts:
            self._care[key] = (" · ".join(parts), now + 6.0)
            nm = self._shown(sc, key)
            if nm and land_mode:
                head = parts[0]
                if head.startswith("back after"):
                    line = "@%s is %s" % (nm, " · ".join(parts))
                else:
                    line = "@%s is back · %s" % (nm, " · ".join(parts))
                self._notice(now, line, L.preset(getattr(self, "_preset", None) or "kick")["accent"], dur=6.0, prio=PRIO_VERB, key=key)

    # ------------------------------------------------------------------ plank
    @staticmethod
    def _chat_down(ctx) -> bool:
        """The chat listener is disconnected or its stats file is stale (typing will not land): the plank says so.
        Never in a self-test with no listener at all (nothing to reconnect to)."""
        cs = ctx.chat_stats or {}
        if cs:
            t = iso_to_epoch(cs.get("ts"))
            fresh = t is not None and (float(ctx.now) - t) < CHAT_STATS_FRESH_S
            return not (bool(cs.get("connected")) and fresh)
        if (ctx.compositor_live or {}).get("selftest"):
            return False
        return (ctx.chat_cfg or {}).get("connected") is False

    def _plank_text(self, sc, ctx, now: float, names_on: bool, accent: str, land_mode: bool = False) -> Optional[Tuple[str, Any]]:
        """(text, colour) for plank row 1, or None for a blank plank (the land only: a quiet plank is fine, journal 028)."""
        if land_mode:
            return self._plank_text_land(sc, ctx, now, names_on, accent)
        return self._plank_text_cave(sc, ctx, now, names_on, accent, land_mode=False)

    def _plank_text_land(self, sc, ctx, now: float, names_on: bool, accent: str) -> Optional[Tuple[str, Any]]:
        # 0. the one flag that changes what a viewer should do: typing will not land
        self._plank_until = None
        if self._chat_down(ctx):
            return RECONNECT_LINE, L.COLORS["warn"]
        # 1. a direct answer to a person, NEWEST FIRST across both sources: the bridge's same-frame vote ack (`@name walks
        #    to C · counts while standing there · closes in 1:27`), a refusal (amber), an unparsed-with-hint (`to do that,
        #    type: go north`), a mod notice; and this panel's own person lines (vote dropped / moved, the care log, hints)
        nt = ctx.notice if (ctx.notice and isinstance(ctx.notice, (tuple, list)) and ctx.notice[0] and names_on) else None
        live = self._live_notices(now, names_on)
        person = [q for q in live if q["prio"] >= PRIO_VERB and not q.get("sticky")]
        if nt is not None:
            nt_start = nt[2] if (len(nt) > 2 and nt[2] is not None) else now
            # a same-frame tie goes to the bridge's answer (a vote ack is the person's own ack) unless this panel's line
            # is the world's consequence of the verb the bridge just echoed (`go north` -> bridge `@x walks north`, world
            # `@x left A · that vote is dropped`, flagged `tie`; journal 030: with a strict `>` that line never showed)
            newer = [q for q in person if q["start"] > float(nt_start) or (q["start"] == float(nt_start) and q.get("tie"))]
            if not newer:
                lvl = (nt[1] if len(nt) > 1 else None)
                col = L.COLORS["danger"] if lvl == "danger" else (accent if lvl in ("ok", "accent", "info") else L.COLORS["warn"])
                self._plank_until = float(nt[3]) if (len(nt) > 3 and nt[3] is not None) else None
                return str(nt[0]), col
            live = newer + [q for q in live if q.get("sticky")]
        if live:
            n = max(live, key=lambda q: (q["prio"], q["start"]))        # the person outranks the world; then newest
            if n.get("sticky"):
                n["shown"] += 1.0 / float(ctx.fps or 30)
            else:
                self._plank_until = float(n["until"])
            return n["text"], n["colour"]
        if ctx.mod_paused:
            self._plank_until = None
            return PAUSED_LINE, L.COLORS["warn"]
        # !help: the try-line again for 20 s (by name when the bridge says who asked)
        if ctx.help_until and now < float(ctx.help_until):
            who = shown_name(getattr(ctx, "help_by", None)) if names_on else None
            head = ("@%s · " % who) if who else ""
            self._plank_until = float(ctx.help_until)
            return head + TRY_LINE, L.COLORS["text"]
        # !stats: a personal answer, to the asker, 10 s
        if ctx.stats_until and now < float(ctx.stats_until):
            card = self._stats_card(sc, ctx, now, names_on)
            if card:
                self._plank_until = float(ctx.stats_until)
                return card, L.COLORS["text"]
        # idle: BLANK. The vote's states are the MOOT BOARD's (lit segment, cord); the camera needs no subtitle.
        return None

    def _stats_card(self, sc, ctx, now: float, names_on: bool) -> Optional[str]:
        """`@name · hut · 4 marks · 2 stones · 41 min here` for the asker (ctx.stats_by), every number a len()."""
        key = str(getattr(ctx, "stats_by", None) or "").lower()
        nm = self._shown(sc, key) if (key and names_on) else None
        if not nm:
            return None
        ld = land()
        parts = ["@%s" % nm]
        try:
            pl = (ld.plate(key, now) if ld is not None else None) or {}
            if pl.get("word"):
                parts.append(str(pl["word"]))
            n_marks = sum(1 for m in (ld.marks if ld is not None else []) if str(m.get("owner") or "").lower() == key)
            if n_marks:
                parts.append("%d mark%s" % (n_marks, "" if n_marks == 1 else "s"))
            stones = 0
            for k, n in (ld.plaque("moot", 50) if ld is not None else []):
                if str(k).lower() == key:
                    stones = int(n)
            if stones:
                parts.append("%d stone%s" % (stones, "" if stones == 1 else "s"))
            e = sc.behaviour.get(key)
            mins = int(round(float(getattr(e, "minutes_tonight", 0.0) or 0.0))) if e is not None else 0
            if mins:
                parts.append("%d min here" % mins)
        except Exception:
            pass
        return " · ".join(parts)

    def _plank_text_cave(self, sc, ctx, now: float, names_on: bool, accent: str, land_mode: bool = False) -> Tuple[str, Any]:
        nt = ctx.notice if (ctx.notice and isinstance(ctx.notice, (tuple, list)) and ctx.notice[0] and names_on) else None
        lvl = (nt[1] if nt is not None and len(nt) > 1 else None)
        if nt is not None:
            # a direct answer to a person outranks the world's own event lines: the same-frame `@name voted A` ack
            # (1.5 s, CONCEPT 2), a verb refusal (`feed again in 26 s`; every refusal shows for 4 s in amber),
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
            return "chat paused by mod · %s keep moving" % ("creatures" if land_mode else "pips"), L.COLORS["warn"]
        if ctx.help_until and now < float(ctx.help_until):
            legend = LEGEND_LAND if land_mode else LEGEND
            return legend[int(now / LEGEND_ITEM_S) % len(legend)], L.COLORS["text"]
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
                    who = "the land chose" if land_mode else "the Hollow chose"      # never `keepers`, never `picked` (banned copy)
                    return "nobody voted. %s %s." % (who, title), L.COLORS["text"]
                by = shown_name(res.get("picked_by")) if names_on else None
                return ("%s · picked by @%s" % (title, by)) if by else title, accent
        # idle rotation
        items: List[Tuple[str, Any]] = []
        hatched, awake, asleep = sc.hatched_ever(), sc.awake_count(), sc.asleep_count()
        if land_mode:
            ld = land()
            settled = ld.settled if ld is not None else asleep
            if hatched == 0:
                items.append(("nobody has walked here yet. say anything and you are the first.", L.COLORS["text"]))
            elif awake == 0:
                items.append(("%d settled here. nobody awake. say anything and yours wakes." % settled, L.COLORS["text"]))
            else:
                items.append(("say anything in chat. a creature walks out with your name.", L.COLORS["text"]))
        else:
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
                        where = "Longgrass" if land_mode else "the Hollow"
                        items.append(("@%s woke %s · %s" % (nm, where, when_text(last.get("ts"), now)), accent))
        items.append(((LEGEND_LAND if land_mode else LEGEND)[0], L.COLORS["text2"]))
        # the call to action (items[0]) comes back every other slot: CTA, visitors, CTA, woke, CTA, legend, ...
        slot = int(now // ROTATE_S)
        if slot % 2 == 0 or len(items) == 1:
            return items[0]
        rest = items[1:]
        return rest[(slot // 2) % len(rest)]

    def _live_notices(self, now: float, names_on: bool) -> List[Dict[str, Any]]:
        return [n for n in self._notices if n["start"] <= now and (names_on or not n["named"])
                and (n["until"] > now if not n.get("sticky") else n["hard_until"] > now)]

    def _plank_row2(self, ctx, now: float, names_on: bool, primary: Optional[str]) -> Optional[Tuple[str, Any]]:
        """The CAVE's second plank row (the newcomer's sticky while row 1 is held). The land has ONE row: its sticky
        lives in row 1 and yields to a newer person line, its seen-clock running only while shown (journal 034)."""
        if is_land():
            return None
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
        t1 = _time.perf_counter()
        try:
            img = base.copy()                          # the scene keeps `base` as its last good frame: never draw on it
            if is_land(sc):
                _COLLECT[0] = True
                del _DRAWN[:]
                del _OURS[:]
                try:
                    self._text_layer_land(img, sc, ctx, size)
                    self._check_drawn(sc, ctx)
                finally:
                    _COLLECT[0] = False
            else:
                self._text_layer_cave(img, sc, ctx, size)
        except Exception:
            self._errors += 1
            if self._errors <= 3 or self._errors % 300 == 0:
                _log("text layer failed (%d): %s" % (self._errors, traceback.format_exc().strip().splitlines()[-1]))
            img = base
        t2 = _time.perf_counter()
        ms = (t2 - t0) * 1000.0
        self._ms.append(ms)
        self._text_ms.append((t2 - t1) * 1000.0)
        if len(self._ms) > STATS_EVERY:
            del self._ms[:-STATS_EVERY]
            del self._text_ms[:-STATS_EVERY]
        self._frames += 1
        if self._frames % STATS_EVERY == 0:
            st = sc.stats() if getattr(sc, "booted", False) else {}
            _log("frame %d: panel avg %.2f ms max %.2f (text layer avg %.2f) (scene avg %s ms, degrade %s) awake=%s asleep=%s hatched=%s "
                 "entities=%s honesty_violations=%d/%s text_cache=%d chips=%d" % (
                     self._frames, sum(self._ms) / len(self._ms), max(self._ms), sum(self._text_ms) / len(self._text_ms),
                     st.get("avg_ms"), (st.get("degrade") or {}).get("level"),
                     st.get("awake"), st.get("asleep"), st.get("hatched_ever"), st.get("entities"),
                     self.honesty_violations, st.get("honesty_violations"), len(_TEXT), len(_CHIP)))
        return img

    # ================================================================== LONGGRASS text layer
    @staticmethod
    def _cells_of(e: Dict[str, Any]) -> Optional[Tuple[float, float]]:
        x, y = e.get("x"), e.get("y")
        if x is None or y is None:
            return None
        return float(x), float(y)

    def _screen_box(self, e: Dict[str, Any], cam, size) -> Optional[Tuple[int, int, int, int]]:
        """(sx, sy, sw, sh) of the sprite on screen: the scene's own box when it gives one, else the camera transform
        of the feet cell and the tier height. None when off-view (culled)."""
        w, h = size
        if e.get("sx") is not None and e.get("sy") is not None:
            sx, sy, sw, sh = int(e["sx"]), int(e["sy"]), int(e.get("sw") or 24), int(e.get("sh") or 32)
            if sx + sw < -40 or sy + sh < -40 or sx > w + 40 or sy > h + 40:
                return None
            return sx, sy, sw, sh
        c = self._cells_of(e)
        if c is None:
            return None
        pt = cam.sim_to_screen(c[0], c[1], size, margin_px=60.0)
        if pt is None:
            return None
        k = cam.scale(size) / 4.0
        tier = int(e.get("tier") or 0)
        sh = int(TIER_H_PX[min(3, max(0, tier))] * k)
        sw = int(sh * 0.9)
        return int(pt[0] - sw / 2.0), int(pt[1] - sh), sw, sh

    @staticmethod
    def _waystones(sc, T, ld) -> List[Tuple[float, float]]:
        """The three waystones' cells: the scene's (behaviour) placement when it exposes one, else a fixed triangle on
        the Moot green (geometry, not a name: the letters stand empty at 0 awake)."""
        for src in (sc, getattr(sc, "behaviour", None), getattr(sc, "land", None)):
            ws = getattr(src, "waystones", None) if src is not None else None
            if callable(ws):
                try:
                    ws = ws()
                except Exception:
                    ws = None
            if ws:
                out = []
                if isinstance(ws, dict):                        # steading.waystones() -> {"A": (x, y), "B": ..., "C": ...}
                    items = [ws.get(k) for k in PLATFORM_LETTERS]
                else:
                    items = list(ws)[:3]
                for s in items:
                    if s is None:
                        continue
                    if isinstance(s, dict):
                        out.append((float(s["x"]), float(s["y"])))
                    else:
                        out.append((float(s[0]), float(s[1])))
                if len(out) == 3:
                    return out
        if ld is not None and ld.moot is not None:
            mx, my = float(ld.moot[0]), float(ld.moot[1])
        elif T is not None:
            mx, my = float(T.site[0]), float(T.site[1])
        else:
            mx, my = 480.0, 220.0
        return [(mx - 14, my + 6), (mx, my - 10), (mx + 14, my + 6)]

    def _place_label(self, sc, cam, T, now: float) -> Optional[str]:
        """Bottom-left place name for 4 s after a camera retarget (mode change or a target > 30 cells away), from
        terrain.places (never a person's name)."""
        if cam is None or T is None:
            return None
        tgt = tuple(cam.target) if getattr(cam, "target", None) else None
        moved = self._cam_target is None or (tgt is not None and math.hypot(tgt[0] - self._cam_target[0], tgt[1] - self._cam_target[1]) > PLACE_RETARGET_CELLS)
        if moved or cam.mode != self._cam_mode:
            self._cam_target, self._cam_mode = tgt, cam.mode
            label = None
            stop = cam.drift_stop if cam.mode == "DRIFT" else None
            if stop is not None and stop.get("kind") == "natural":
                label = str(stop.get("name") or "")
            if not label and tgt is not None:
                best, bd = None, 1e9
                for name, p in (getattr(T, "places", None) or {}).items():
                    if name == "steading":
                        continue
                    d = math.hypot(tgt[0] - p["x"], tgt[1] - p["y"])
                    if d < bd and d <= max(40.0, 2.0 * float(p.get("radius") or 0)):
                        best, bd = p, d
                if best is not None:
                    label = str(best.get("label") or best.get("name"))
            if label:
                self._place = (L.strip_non_bmp(label), now + PLACE_LABEL_S)
        if self._place and self._place[1] > now:
            return self._place[0]
        return None

    def _text_layer_land(self, img: Image.Image, sc, ctx, size) -> None:
        if not getattr(sc, "booted", False):
            return
        w, h = size
        now = float(ctx.now if ctx.now is not None else _time.time())
        accent = L.preset(ctx.preset)["accent"]
        names_on = self._names_on(ctx)
        deg = sc.degrade or {}
        cam = sc.camera
        ld = getattr(sc, "land", None) or sc.world.land
        T = getattr(sc, "terrain", None)
        ents = sc.entities(now)
        awake = sc.awake_count()
        labels_on_speak = bool(deg.get("labels_on_speak")) or awake > DENSITY_FALLBACK
        dense = awake > DENSITY_FALLBACK
        plates_static = bool(deg.get("plates_static")) or deg.get("plates_rotate") is False or dense
        self._preset = ctx.preset
        self._consume_events(sc, ctx, now, accent, land_mode=True)
        # a new round: everyone steps off the stones (behaviour.release_votes); said once, only when someone is here to read it
        opened = ctx.round_opened_t
        if opened != self._round_seen:
            if self._round_seen is not None and opened is not None and awake >= 1 and (ctx.round or {}).get("phase") != "ship":
                self._notice(now, ROUND_OPEN_LINE, L.COLORS["text"], dur=5.0, named=False, prio=PRIO_EVENT)
            self._round_seen = opened
        self._alone_since, self._alone_prompted = None, False        # the land has no loneliness prompt (journal 034)

        try:
            self._camps = ld.camps() if ld is not None else []
            self._fields = ld.fields() if ld is not None else []
        except Exception:
            self._camps, self._fields = [], []
        placer = _Placer()
        # 0. the plank is built FIRST (pasted last, over everything) so its real extent, not a constant, is what labels /
        #    plates / letters avoid, and the camera gets the same box as its dead zone (journal 021 / 023: "HUD plates
        #    stack over settlers"). Then every sprite on screen is reserved: a chip never lands on a person or a camp.
        plank, plank_box = self._plank_strip(sc, ctx, now, names_on, accent, size)
        hud_boxes: List[Tuple[int, int, int, int]] = [plank_box] if plank_box is not None else []
        for bx in hud_boxes:
            placer.reserve(*bx)
        self.last_hud_boxes = list(hud_boxes)
        try:
            cam.hud_boxes = [tuple(int(v) for v in bx) for bx in hud_boxes]
        except Exception:
            pass
        sprite_boxes = self._sprite_boxes(ents, cam, size)
        for bx in sprite_boxes:
            placer.reserve(*bx)
        self.last_sprite_boxes = len(sprite_boxes)
        body_boxes = self._body_boxes(ents, cam, size)             # the drawn bodies (tighter than the atlas frames): the letter fade
        zoom = float(getattr(cam, "zoom", 1.0) or 1.0)
        tile_k = 284.0 / float(w)

        # 0b. the SAY ANYTHING sign at the spawn (world-anchored, screen-scale): a fixed object, reserved before anything
        #     else is placed so no name row or plate lands under it
        self._sign(img, placer, sc, cam, size, awake)

        # 1. waystone letters, counts, standing names (culled; their boxes are reserved so nothing covers a letter)
        counts = sc.platform_counts()
        walking = self._walking_to(sc)
        carved = L.COLORS["text"]
        ns = {k: len(counts.get(k) or []) for k in PLATFORM_LETTERS}
        best_votes = max(ns.values()) if ns else 0
        leaders = [k for k, n in ns.items() if n == best_votes and n > 0]
        leader = leaders[0] if len(leaders) == 1 else None
        cluster_px: List[Tuple[int, int]] = []
        stone_row: Dict[str, Tuple[int, int, int]] = {}          # letter -> (x0, x1, bottom y) of the carved rows
        options = {str(o.get("letter") or "").upper(): o for o in ((ctx.round or {}).get("options") or []) if isinstance(o, dict)}
        letters_px: Dict[str, Tuple[int, int, int]] = {}         # letter -> (cx, letter top y, letter bottom y) of the letters drawn
        # the letters are one row: when the plank would cull one of them, all three drop by the same amount (down to the
        # count sitting on its stone); if that is not enough, all three are culled together (never `A C` without `B`);
        # the camera's dead zone normally keeps the stones clear whenever people are at them
        letter_size, letter_dy, stack_h = (WAYSTONE_LETTER_WIDE if zoom == 0.75 else (56, WAYSTONE_LETTER_DY, LETTER_STACK_H))
        try:
            glyph_pad = int(L.font("AB", letter_size).getbbox("A")[1])      # empty strip rows above the glyph (21 at AB 56)
        except Exception:
            glyph_pad = 0
        stones_cells = self._waystones(sc, T, ld)
        stones_px: List[Tuple[str, int, int]] = []
        stone_counts: Dict[str, str] = {}
        stones_in_view = 0
        for letter, (wx, wy) in zip(PLATFORM_LETTERS, stones_cells):
            pt = cam.sim_to_screen(wx, wy, size, margin_px=120.0)
            if pt is not None:
                stones_px.append((letter, int(pt[0]), int(pt[1])))
            if cam.in_view(wx, wy):
                stones_in_view += 1
        self.last_stones_in_view = stones_in_view
        shift = 0
        for letter, cx, cy in stones_px:
            ly = cy - letter_dy
            hb = _hud_bottom_under(cx - 27, ly - 4, cx + 63, ly + letter_size + 13, hud_boxes)
            if hb is not None:
                shift = max(shift, hb + 4 - (ly - 4))
        letters_ok = shift <= letter_dy - stack_h - 2
        for letter, cx, cy in stones_px:
            keys = counts.get(letter) or []
            n = len(keys)
            if n:
                cluster_px.append((cx, cy))
            if not letters_ok:
                continue                                   # the stones stand under the plank: no letter is drawn beneath them
            lt = text_strip("AB", letter_size, letter, accent if letter == leader else carved, stroke=True)
            ly = cy - letter_dy + shift
            lx0, ly0, lx1, ly1 = cx - lt.size[0] // 2 + 4, ly + glyph_pad, cx + lt.size[0] // 2 - 4, ly + lt.size[1] - 3   # the glyph, not the strip
            if any(bx0 < lx1 and bx1 > lx0 and by0 < ly1 and by1 > ly0 for (bx0, by0, bx1, by1) in body_boxes):
                lt = _faded(lt, LETTER_OVER_SPRITE_ALPHA)      # a settler walks in front of the glyph, never under it (QA: `C` over @kai_dnb)
            _paste(img, lt, cx - lt.size[0] // 2, ly)
            letters_px[letter] = (cx, ly + glyph_pad, ly + lt.size[1])         # the glyph's real top, not the strip's
            # the count sits centred UNDER its letter: the stones stand 12 cells (48 px at 1x) apart and an AB 56 glyph is
            # 44 px wide, so a count beside the letter was hidden under the next letter (integration frame 540)
            ct = text_strip("Menlo", 22, "%d" % n, accent if n else L.COLORS["text2"])
            cty = ly + lt.size[1] - 6
            _paste(img, ct, cx - ct.size[0] // 2, cty)
            x0, x1 = cx - lt.size[0] // 2, cx + lt.size[0] // 2
            k_walk = int(walking.get(letter) or 0)
            stone_counts[letter] = ("%d +%d" % (n, k_walk)) if k_walk else "%d" % n
            if k_walk:                                     # `0 +1`: the ack plank and the digit never disagree while a voter walks over
                wt = text_strip("Menlo", 20, "+%d" % k_walk, L.COLORS["text2"])
                _paste(img, wt, cx + ct.size[0] // 2 + 3, cty + 2)
                x1 = max(x1, cx + ct.size[0] // 2 + 3 + wt.size[0])
            placer.reserve(x0 - 4, ly + glyph_pad - 4, x1 + 4, cty + ct.size[1] + 2)
            bottom = cty + ct.size[1]
            if n and names_on:
                shown = [nm for nm in (self._shown(sc, k) for k in keys[-3:]) if nm]
                segs: List[Image.Image] = []
                total = 0
                for j, nm in enumerate(shown):
                    if segs:
                        sep = text_strip(LABEL_FONT, LABEL_SIZE, " · ", L.COLORS["text2"])
                        segs.append(sep); total += sep.size[0]
                    k = keys[-3:][j]
                    st = text_strip(LABEL_FONT, LABEL_SIZE, "@" + nm, _colour_of(sc, k, None, ctx.preset), ours=False)
                    segs.append(st); total += st.size[0]
                if total > PLATFORM_NAMES_MAX_W and len(shown) > 1:
                    st = text_strip(LABEL_FONT, LABEL_SIZE, "%d standing" % n, L.COLORS["text"])
                    segs, total = [st], st.size[0]
                rx = max(GUTTER, min(w - GUTTER - total, cx - total // 2))
                # adjacent stones' name rows would overprint (48 px apart, a name is ~108 px): the placer stacks them
                ry = placer.place_down(rx, bottom + 2, total, LABEL_H, LABEL_H + 2, 4, ceiling=h - 48)
                if ry is None and len(segs) > 1:
                    st = text_strip(LABEL_FONT, LABEL_SIZE, "%d standing" % n, L.COLORS["text"])
                    segs, total = [st], st.size[0]
                    rx = max(GUTTER, min(w - GUTTER - total, cx - total // 2))
                    ry = placer.place_down(rx, bottom + 2, total, LABEL_H, LABEL_H + 2, 4, ceiling=h - 48)
                if ry is not None:
                    for st in segs:
                        _paste(img, st, rx, ry); rx += st.size[0]
                    x0, x1 = min(x0, rx - total), max(x1, rx)
                    bottom = ry + LABEL_H
            stone_row[letter] = (x0, x1, bottom)
        self.last_stone_counts = stone_counts
        self.last_stone_n = {k: ns[k] for k in stone_counts}

        # 1b. the MOOT BOARD above the letters (option titles, the lit leader, the timer, the fuse cord) and, when every
        #     stone is off view with a round open, the Moot edge marker
        has_round, rem = self._moot_board(img, placer, ctx, now, options, ns, leader, letters_px, accent, size)
        self._moot_marker(img, placer, cam, stones_cells, stones_in_view, has_round, rem, awake, size, hud_boxes)

        # 1c. the beacon's in-view fact (the tile gate)
        try:
            bx, by = sc.moot_xy("beacon")
            self.last_beacon_in_view = bool(cam.in_view(float(bx), float(by)))
        except Exception:
            self.last_beacon_in_view = False

        # 2. plates: the DRIFT stop's plate (while the camera dwells) + one rotating plate over the marks in view
        plates_drawn: List[str] = []
        if names_on:
            self._plates(img, sc, cam, ld, now, size, placer, plates_drawn, plates_static, ctx.preset)
        self.last_plates = plates_drawn

        # 3. labels: awake above the sprite (contrast chip); a sleeper lies at its camp, whose plate names it (a `sleep`
        #    override lights a sleeper's own label). De-collision through the placer.
        placed: List[Tuple[int, int, int]] = []
        label_pos: Dict[str, Tuple[int, int]] = {}
        boxes: Dict[str, Tuple[int, int, int, int]] = {}
        name_in_bubble: Dict[str, Tuple[str, str]] = {}
        drawn_names = 0
        tile_px = 0.0
        sleepers_in_view = 0
        ents = sorted(ents, key=lambda e: (e.get("y") or 0, e.get("key") or ""))
        for e in ents:
            key = e.get("key")
            if not key or e.get("display_name") is None or e.get("state") in ("burrowed", "seed", "hatching"):
                continue                                   # a seed: nothing about it is drawn (OPENWORLD 12)
            box = self._screen_box(e, cam, size)
            if box is None:
                continue
            boxes[key] = box
            sx, sy, sw, sh = box
            cx, top = sx + sw // 2, sy
            if e.get("in_view"):
                if e.get("awake"):
                    tile_px = max(tile_px, (sh + LABEL_H + 2) * tile_k)
                else:
                    sleepers_in_view += 1
            if not names_on:
                continue
            txt = None
            if e.get("awake"):
                if e.get("state") == "voting" and str(e.get("platform")) in stone_row:
                    label_pos[key] = (cx, top - 4)
                    continue                               # its name is in the waystone row (else, letters culled: its own label)
                if labels_on_speak and not e.get("speaking") and key not in self._label_override and key not in self._hatch_tag:
                    continue
                if not e.get("speaking") and any(abs(cx - px) <= PLATFORM_CLUSTER_PX and abs(top - py) <= 80 for px, py in cluster_px):
                    label_pos[key] = (cx, top - 4)
                    continue
                txt = self._label_text(sc, e)
            else:
                ov = self._label_override.get(key)
                if ov:
                    txt = ov[0]
            if not txt:
                continue
            col = _colour_of(sc, key, e, ctx.preset)
            strip = label_chip(txt, col)
            lw, lh = strip.size
            x0 = max(2, min(w - lw - 2, cx - lw // 2))
            y = placer.place_up(x0, top - lh - 4, lw, lh, lh + 2, LABEL_MAX_STEPS, floor=2)
            if y is None:
                y = placer.place_down(x0, sy + sh + 4, lw, lh, lh + 2, 2, ceiling=h - 2)
            if y is None:
                if e.get("speaking"):
                    name_in_bubble[key] = (txt, col)       # crowded: the name rides as the bubble's first row
                label_pos[key] = (cx, top - 4)
                continue                                   # crowded and silent: label-on-speak for this pip
            placed.append((x0, x0 + lw, y))
            _paste(img, strip, x0, y)
            label_pos[key] = (cx, y)
            drawn_names += 1
        self.last_tile_px = round(tile_px, 1)
        self.last_sleepers_in_view = sleepers_in_view

        # 4. bubbles (one per pip, 8 s; care log rides as the first line; !kill -> nothing)
        single: Optional[Tuple[float, str, str]] = None
        for e in ents:
            key = e.get("key")
            if not key or not e.get("awake") or key not in boxes:
                continue
            care = self._care.get(key)
            text = e.get("text") if e.get("speaking") else None
            if not text and not care:
                continue
            rows: List[Tuple[str, str]] = []
            if not names_on:
                continue                                   # !kill: nothing is said; names and words simply leave the land
            else:
                if key in name_in_bubble:
                    rows.append(name_in_bubble[key])
                if care:
                    rows.append((L.truncate(BUBBLE_FONT, BUBBLE_SIZE, care[0], BUBBLE_MAX_W - 2 * BUBBLE_PAD), L.COLORS["text2"]))
                if text:
                    body = L.strip_non_bmp(str(text))
                    if e.get("learned_from"):
                        src = self._shown(sc, e.get("learned_from"))
                        body = "%s · from @%s" % (body, src) if src else body
                    for ln in L.wrap(BUBBLE_FONT, BUBBLE_SIZE, body, BUBBLE_MAX_W - 2 * BUBBLE_PAD, max(1, 3 - len(rows))):
                        rows.append((ln, L.COLORS["text"]))
            if not rows:
                continue
            nm = e.get("display_name") if names_on else None
            cand = (float(e.get("minutes_tonight") or 0), nm, rows[-1][0])
            if deg.get("bubbles_single"):
                if single is None or e.get("speaking"):
                    single = cand
                continue
            b = bubble_img(rows)
            bw, bh = b.size
            sx, sy, sw, sh = boxes[key]
            cx, ly = label_pos.get(key, (sx + sw // 2, sy - 2))
            by = None
            if e.get("state") == "voting" and e.get("platform") and str(e.get("platform")) in stone_row:
                # a standing pip speaks BESIDE the letter column, at the creature's height
                r0, r1, _rb = stone_row[str(e.get("platform"))]
                side_x = max(cx + 40, r1 + 10)
                if side_x + bw > w - 2:
                    side_x = min(cx - 40, r0 - 10) - bw
                bx = max(2, min(w - bw - 2, side_x))
                by = placer.place_up(bx, max(2, sy + sh - 8 - bh), bw, bh, BUBBLE_LINE_H, 8, floor=2)
            else:
                bx = max(2, min(w - bw - 2, cx - bw // 2))
                by = placer.place_up(bx, max(2, ly - 4 - bh), bw, bh, BUBBLE_LINE_H, 8, floor=2)
                if by is None:
                    by = placer.place_down(bx, sy + sh + 4, bw, bh, BUBBLE_LINE_H, 6, ceiling=h - 2)
            if by is None:
                if single is None or e.get("speaking"):
                    single = cand                          # no room anywhere: the shared bottom line carries it
                continue
            _paste(img, b, bx, by)
        if single is not None:
            _, nm, line = single
            txt = ("@%s: %s" % (nm, line)) if nm else line
            # the same plated bubble as every other speech line (QA: `@moss_m: go home` landed as dim text over grass at night)
            b = bubble_img([(L.truncate(BUBBLE_FONT, BUBBLE_SIZE, txt, BUBBLE_MAX_W - 2 * BUBBLE_PAD), L.COLORS["text"])])
            bx = max(2, min(w - b.size[0] - 2, 420))
            by = placer.place_up(bx, h - 8 - b.size[1], b.size[0], b.size[1], BUBBLE_LINE_H, 4, floor=2)   # never over a plate / label (frame 899)
            _paste(img, b, bx, by if by is not None else h - 8 - b.size[1])

        # 6. edge arrows: awake creatures outside the window, `@kai · 210 paces ->` in their colour on wood at the nearest edge
        arrows_drawn: List[str] = []
        if names_on:
            awake_pts = [{"key": e.get("key"), "x": e["x"], "y": e["y"]} for e in ents
                         if e.get("key") and e.get("awake") and e.get("display_name") is not None and e.get("x") is not None and e.get("y") is not None]
            try:
                arrows = cam.edge_arrows(size, awake=awake_pts, inset=EDGE_INSET)
            except Exception:
                arrows = []
            for a in arrows[:8]:
                nm = self._shown(sc, a.get("key"))
                if not nm:
                    continue
                glyph = ARROWS.get(str(a.get("side")), "→")
                paces = int(round(float(a.get("dist") or 0) / 5.0) * 5)          # to the nearest 5: one strip per ~0.6 s of walking, not per frame
                txt = "@%s · %d paces %s" % (nm, paces, glyph) if a.get("side") != "left" else \
                      "%s %d paces · @%s" % (glyph, paces, nm)
                strip = wood_chip(txt, label_colour(_colour_of(sc, a.get("key"), None, ctx.preset)), MARKER_FONT, MARKER_SIZE)
                yy, ax = self._edge_place(placer, a, strip.size, size)
                if yy is None:
                    continue
                _paste(img, strip, ax, yy)
                arrows_drawn.append(txt)
        self.last_arrows = arrows_drawn

        # 7. the plank (top-left), over everything else in the region; built in step 0 so the placer and the camera saw
        #    its real box
        if plank is not None:
            _paste(img, plank, PLANK_XY[0], PLANK_XY[1])

        self._last_counts = (drawn_names, len(ents))
        self.last_placed = placed
        self.last_copy = list(_OURS)

    @staticmethod
    def _edge_place(placer: _Placer, a: Dict[str, Any], strip_size: Tuple[int, int], size) -> Tuple[Optional[int], int]:
        """(y, x) for an edge chip at the frame edge the camera gave, EDGE_INSET-ish, pushed out of anything already
        placed (the plank box included); (None, x) when no free row exists."""
        w, h = size
        lw, lh = strip_size
        sx, sy = int(a["sx"]), int(a["sy"])
        side = a.get("side")
        if side == "right":
            ax, ay = w - lw - 4, sy - lh // 2
        elif side == "left":
            ax, ay = 4, sy - lh // 2
        elif side == "top":
            ax, ay = sx - lw // 2, 4
        else:
            ax, ay = sx - lw // 2, h - lh - 4
        ax = max(2, min(w - lw - 2, ax))
        ay = max(2, min(h - lh - 2, ay))
        return placer.place_either(ax, ay, lw, lh, lh + 2, 8, floor=2, ceiling=h - 2), ax

    # ------------------------------------------------------------------ the plank (the land's single voice)
    def _plank_strip(self, sc, ctx, now: float, names_on: bool, accent: str, size) -> Tuple[Optional[Image.Image], Optional[Tuple[int, int, int, int]]]:
        """(strip, box) for the ONE plank row at PLANK_XY, or (None, None) when blank. The box hangs from y 0 so the
        camera treats it as its dead zone. A timed line fades out over its last PLANK_FADE_S; sticky lines never fade."""
        w, h = size
        pt = self._plank_text(sc, ctx, now, names_on, accent, land_mode=True)
        txt = pt[0] if pt is not None else None
        if _PLANK_LOG and txt != self.last_plank:
            _log("plank: %r" % (txt,))                              # TEST HOOK (KL_PLANK_LOG=1): the copy as evidence
        self.last_plank = txt
        self.last_plank_row2 = None
        if pt is None:
            return None, None
        chip = wood_chip(L.strip_non_bmp(pt[0]), pt[1], PLANK_FONT, PLANK_SIZE, max_w=PLANK_MAX_W)
        until = self._plank_until
        if until is not None and 0.0 <= until - now < PLANK_FADE_S:
            k = max(0.0, min(1.0, (until - now) / PLANK_FADE_S))
            if k < 1.0:
                faded = chip.copy()
                a = faded.getchannel("A").point(lambda v: int(v * k))
                faded.putalpha(a)
                chip = faded
        box = (0, 0, min(w, PLANK_XY[0] + chip.size[0] + 6), PLANK_XY[1] + chip.size[1] + 4)
        return chip, box

    # ------------------------------------------------------------------ the MOOT BOARD (the vote's one home, with the stones)
    def _board_model(self, ctx, now: float, options: Dict[str, Dict[str, Any]], ns: Dict[str, int], leader: Optional[str]) -> Dict[str, Any]:
        rnd = ctx.round or {}
        phase = rnd.get("phase") or "open"
        rem = ctx.round_remaining
        titles: Dict[str, str] = {}
        for k in PLATFORM_LETTERS:
            t = board_title((options.get(k) or {}).get("title"))
            if t:
                titles[k] = t
        has_round = bool(titles) and rem is not None and phase != "ship"
        closing = bool(has_round and rem is not None and rem <= 0)      # the deadline passed, the manager has not shipped yet
        timer = BOARD_CLOSING_TEXT if closing else (_mss(rem) if (has_round and rem is not None and rem >= 0) else "")
        standing = sum(ns.values())
        lit, lit_role, dim_others, ship_t = leader, "accent", False, None
        if phase == "ship":
            res = rnd.get("last_result") or {}
            letter = str(res.get("letter") or "").upper()
            ship_t = iso_to_epoch(res.get("ts"))
            if res.get("ok") is False or letter not in titles:
                lit, lit_role = None, "accent"           # a failed ship: the land simply does not change; nothing lights
            else:
                lit, lit_role, dim_others = letter, ("amber" if res.get("agent_pick") else "accent"), True
        timer_role = "cream"
        if closing:
            timer_role = "warn"
        elif timer and rem is not None:
            timer_role = "danger" if rem < 10 else ("warn" if rem < 30 else "cream")
        top_rail = bool(has_round and timer)                             # the rail holds the timer; between rounds / in the ship hold there is none
        top_text = BOARD_TOP_RAIL_TEXT if (has_round and standing == 0) else ""
        return {"titles": titles, "has_round": has_round, "timer": timer, "timer_role": timer_role, "lit": lit, "lit_role": lit_role,
                "dim_others": dim_others, "top_rail": top_rail, "top_text": top_text, "closing": closing, "phase": phase, "rem": rem,
                "ship_t": ship_t}

    def _board_image(self, m: Dict[str, Any], accent: str) -> Image.Image:
        """The board itself (cached on its strings; the fuse is drawn on the frame after the paste). STACKED: a top rail
        [`type A, B or C` left at 0 standing][timer right], then one BOARD_ROW_H row per option [AB 28 letter][HN Medium
        22 title, WHOLE up to BOARD_TITLE_MAX_W] with 1 px carved lines between rows; the leading row sits on a band of the
        accent (BOARD_LIT_ALPHA) with its letter in the accent and its title cream; the others burn dim; in the ship hold
        the losers dim to 40 % toward the wood. No result prose."""
        key = (tuple(sorted(m["titles"].items())), m["lit"], m["lit_role"], m["dim_others"], m["timer"], m["timer_role"], m["top_rail"],
               m["top_text"], accent)
        if self._board_img is not None and self._board_key == key:
            self.last_board_titles = dict(self._board_titles)
            return self._board_img
        f_letter, f_title, f_timer = L.font(BOARD_LETTER_FONT, BOARD_LETTER_SIZE), L.font(BOARD_TITLE_FONT, BOARD_TITLE_SIZE), L.font(BOARD_TIMER_FONT, BOARD_TIMER_SIZE)
        letters = [k for k in PLATFORM_LETTERS if k in m["titles"]]
        titles = {k: m["titles"][k] for k in letters}                 # already board_title(): whole up to BOARD_TITLE_MAX_W
        widths = {k: L.text_width(BOARD_TITLE_FONT, BOARD_TITLE_SIZE, titles[k]) for k in letters}
        tw_timer = L.text_width(BOARD_TIMER_FONT, BOARD_TIMER_SIZE, m["timer"]) if m["timer"] else 0
        tw_top = L.text_width("Menlo", 20, m["top_text"]) if m["top_text"] else 0
        title_x = BOARD_SEG_PAD + BOARD_LETTER_W + 6
        rail_w = (BOARD_SEG_PAD + tw_top + BOARD_SEG_PAD if tw_top else 0) + (tw_timer + 2 * BOARD_TIMER_INSET if tw_timer else 0)
        bw = max(BOARD_MIN_W, title_x + (max(widths.values()) if widths else 0) + BOARD_SEG_PAD + 4, rail_w)
        bh = (BOARD_TOP_RAIL_H if m["top_rail"] else 0) + len(letters) * BOARD_ROW_H + BOARD_RAIL_H
        im = wood_board(bw, bh).copy()
        d = ImageDraw.Draw(im, "RGBA")
        roles = {"accent": L.hex_rgb(accent), "amber": L.hex_rgb(L.COLORS["warn"]), "cream": CREAM, "warn": L.hex_rgb(L.COLORS["warn"]),
                 "danger": L.hex_rgb(L.COLORS["danger"])}
        y0 = 0
        if m["top_rail"]:
            if tw_top:
                d.text((BOARD_SEG_PAD, 2), m["top_text"], font=L.font("Menlo", 20), fill=CREAM, stroke_width=1, stroke_fill=WOOD_BOTTOM)
            if tw_timer:
                d.text((bw - BOARD_TIMER_INSET - tw_timer, (BOARD_TOP_RAIL_H - BOARD_TIMER_SIZE) // 2 - 3), m["timer"], font=f_timer,
                       fill=roles.get(m["timer_role"], CREAM), stroke_width=1, stroke_fill=WOOD_BOTTOM)
            d.line([(6, BOARD_TOP_RAIL_H - 1), (bw - 7, BOARD_TOP_RAIL_H - 1)], fill=WOOD_BOTTOM + (255,), width=1)
            y0 = BOARD_TOP_RAIL_H
        dim = lambda c: tuple(int(round(WOOD[i] + (c[i] - WOOD[i]) * 0.4)) for i in range(3))     # 40 % toward the wood
        for i, k in enumerate(letters):
            lit = (k == m["lit"])
            ry = y0 + i * BOARD_ROW_H
            if lit:
                d.rectangle([2, ry + 1, bw - 3, ry + BOARD_ROW_H - 2], fill=roles[m["lit_role"]] + (BOARD_LIT_ALPHA,))
            lcol = roles[m["lit_role"]] if lit else CREAM
            tcol = CREAM if lit else WOOD_BURN
            if m["dim_others"] and not lit:
                lcol, tcol = dim(lcol), dim(tcol)
            bb = f_letter.getbbox(k)
            d.text((BOARD_SEG_PAD + (BOARD_LETTER_W - (bb[2] - bb[0])) // 2 - bb[0], ry + (BOARD_ROW_H - (bb[3] - bb[1])) // 2 - bb[1]), k,
                   font=f_letter, fill=lcol, stroke_width=1, stroke_fill=WOOD_BOTTOM)
            d.text((title_x, ry + (BOARD_ROW_H - BOARD_TITLE_SIZE) // 2 - 3), titles[k], font=f_title, fill=tcol,
                   stroke_width=1, stroke_fill=WOOD_BOTTOM)
            if i < len(letters) - 1:
                d.line([(6, ry + BOARD_ROW_H - 1), (bw - 7, ry + BOARD_ROW_H - 1)], fill=WOOD_BOTTOM + (140,), width=1)
        self.last_board_titles = dict(titles)
        self._board_titles = dict(titles)
        self._board_img, self._board_key = im, key
        return im

    def _moot_board(self, img, placer: _Placer, ctx, now: float, options: Dict[str, Dict[str, Any]], ns: Dict[str, int], leader: Optional[str],
                    letters_px: Dict[str, Tuple[int, int, int]], accent: str, size) -> Tuple[bool, Optional[float]]:
        """One wooden board anchored above the letters (centred on their x span, bottom 6 px above the letter strips;
        place_up, OPTIONS_ROW_MAX_STEPS, no fixed fallback: culled with the stones): the three option titles with the
        leader lit, the round timer, the fuse cord along the bottom rail, `type A, B or C` on a top rail only when nobody
        stands. Returns (has_round, remaining) for the edge marker."""
        w, h = size
        m = self._board_model(ctx, now, options, ns, leader)
        self.last_board_drawn, self.last_board_lit, self.last_board_timer = False, None, None
        if not m["titles"] or not letters_px:
            self.last_board_titles = {}
            return m["has_round"], m["rem"]
        for t in m["titles"].values():
            _note_drawn(t)
        if m["timer"]:
            _note_drawn(m["timer"])
        if m["top_text"]:
            _note_drawn(m["top_text"])
        board = self._board_image(m, accent)
        bw, bh = board.size[0] - 2, board.size[1] - 2
        cxs = [v[0] for v in letters_px.values()]
        top = min(v[1] for v in letters_px.values())
        x = max(GUTTER, min(w - bw - GUTTER, (min(cxs) + max(cxs)) // 2 - bw // 2))
        y = placer.place_up(x, top - bh - BOARD_GAP_ABOVE_LETTERS, bw, bh, 12, OPTIONS_ROW_MAX_STEPS, floor=2)
        if y is None:
            self.last_board_titles = {}
            return m["has_round"], m["rem"]
        _paste(img, board, x, y)
        self.last_board_drawn, self.last_board_lit, self.last_board_timer = True, m["lit"], (m["timer"] or None)
        # the fuse: a 4 px cord along the bottom rail shrinking left to right (accent / amber < 30 s / red < 10 s) with a
        # 6 px ember at its head; full during the ship hold (white flare for 1 s); nothing between rounds
        rail_y = y + bh - BOARD_RAIL_H + 1
        rnd = ctx.round or {}
        opened, deadline = ctx.round_opened_t, ctx.round_deadline_t
        d = ImageDraw.Draw(img, "RGBA")
        cx0, cx1 = x + 4, x + bw - 4
        if m["phase"] == "ship" and m["lit"] is not None:
            ship_t = m["ship_t"] if m["ship_t"] is not None else (deadline if deadline is not None else now)
            col = (255, 255, 255) if now - float(ship_t) < BOARD_SHIP_FLARE_S else (L.hex_rgb(L.COLORS["warn"]) if m["lit_role"] == "amber" else L.hex_rgb(accent))
            d.rectangle([cx0, rail_y, cx1, rail_y + FUSE_H - 1], fill=col + (255,))
            return m["has_round"], m["rem"]
        if not m["has_round"] or m["closing"] or opened is None or deadline is None or deadline <= opened:
            return m["has_round"], m["rem"]                    # closing: the cord is burnt out; the rail says `closing`
        frac = max(0.0, min(1.0, float(m["rem"]) / float(deadline - opened)))
        col = L.hex_rgb(accent)
        if m["rem"] < 10:
            col = L.hex_rgb(L.COLORS["danger"])
        elif m["rem"] < 30:
            col = L.hex_rgb(L.COLORS["warn"])
        px = int(round((cx1 - cx0) * frac))
        if px > 0:
            d.rectangle([cx0, rail_y, cx0 + px, rail_y + FUSE_H - 1], fill=col + (255,))
            ex0 = max(cx0, cx0 + px - EMBER_W // 2)
            d.rectangle([ex0, rail_y - 1, ex0 + EMBER_W - 1, rail_y + FUSE_H], fill=(255, 236, 200, 255))
        return m["has_round"], m["rem"]

    def _moot_marker(self, img, placer: _Placer, cam, stones_cells: Sequence[Tuple[float, float]], stones_in_view: int, has_round: bool,
                     rem: Optional[float], awake: int, size, hud_boxes) -> None:
        """`← A B C · 1:27` on wood at the frame edge toward the stones' centroid: only while a round is open, anyone is
        awake and no waystone is inside the view (the people arrows' grammar: the ballot is never invisible)."""
        self.last_marker = None
        if not has_round or awake < 1 or stones_in_view > 0 or not stones_cells or rem is None or rem < 0:
            return
        mx = sum(p[0] for p in stones_cells) / len(stones_cells)
        my = sum(p[1] for p in stones_cells) / len(stones_cells)
        try:
            arrows = cam.edge_arrows(size, awake=[{"key": "moot", "x": mx, "y": my}], inset=EDGE_INSET)
        except Exception:
            arrows = []
        if not arrows:
            return
        a = arrows[0]
        side = str(a.get("side") or "right")
        glyph = ARROWS.get(side, "→")
        timer = _mss(rem)
        txt = ("%s A B C · %s" % (glyph, timer)) if side in ("left", "top") else ("A B C · %s %s" % (timer, glyph))
        col = L.hex_rgb(L.COLORS["danger"]) if rem < 10 else (L.hex_rgb(L.COLORS["warn"]) if rem < 30 else CREAM)
        strip = wood_chip(txt, col, MARKER_FONT, MARKER_SIZE)
        yy, ax = self._edge_place(placer, a, strip.size, size)
        if yy is None:
            return
        _paste(img, strip, ax, yy)
        self.last_marker = txt

    # ------------------------------------------------------------------ the SAY ANYTHING sign (the invitation, in the world)
    def _sign_image(self, carved: bool) -> Image.Image:
        key = ("sign", carved)
        if self._sign_img is not None and self._sign_key == key:
            return self._sign_img
        f = L.font(SIGN_FONT, SIGN_SIZE)
        tw = L.text_width(SIGN_FONT, SIGN_SIZE, SIGN_TEXT)
        body_w = min(SIGN_MAX_W, tw + 2 * SIGN_PAD_X)
        total_h = SIGN_BODY_H + SIGN_POST_H
        im = Image.new("RGBA", (body_w + 2, total_h + 2), (0, 0, 0, 0))
        d = ImageDraw.Draw(im, "RGBA")
        for px in (4, body_w - 4 - SIGN_POST_W):                                   # posts from the body's bottom corners to the anchor
            d.rectangle([px + 2, SIGN_BODY_H, px + SIGN_POST_W + 1, total_h + 1], fill=(0, 0, 0, 90))
            d.rectangle([px, SIGN_BODY_H - 2, px + SIGN_POST_W - 1, total_h - 1], fill=WOOD + (255,))
            d.line([(px, SIGN_BODY_H - 2), (px, total_h - 1)], fill=WOOD_TOP + (255,), width=1)
            d.line([(px + SIGN_POST_W - 1, SIGN_BODY_H - 2), (px + SIGN_POST_W - 1, total_h - 1)], fill=WOOD_BOTTOM + (255,), width=1)
        im.alpha_composite(wood_board(body_w, SIGN_BODY_H), (0, 0))
        col = tuple(int(round(WOOD[i] + (CREAM[i] - WOOD[i]) * CREAM_CARVED_T)) for i in range(3)) if carved else CREAM
        bb = f.getbbox(SIGN_TEXT)
        d = ImageDraw.Draw(im, "RGBA")
        d.text(((body_w - (bb[2] - bb[0])) // 2 - bb[0], (SIGN_BODY_H - (bb[3] - bb[1])) // 2 - bb[1]), SIGN_TEXT, font=f, fill=col,
               stroke_width=1, stroke_fill=WOOD_BOTTOM)
        self._sign_img, self._sign_key = im, key
        return im

    def _sign(self, img, placer: _Placer, sc, cam, size, awake: int) -> None:
        w, h = size
        self.last_sign_in_view = False
        try:
            ax, ay = sc.moot_xy("sign")
        except Exception:
            ld = getattr(sc, "land", None)
            if ld is None or ld.moot is None:
                return
            ax, ay = float(ld.moot[0]), float(ld.moot[1]) + 46.0
        pt = cam.sim_to_screen(float(ax), float(ay), size, margin_px=SIGN_CULL_PX)
        if pt is None:
            return
        _note_drawn(SIGN_TEXT)
        sign = self._sign_image(carved=awake >= 1)
        sw, sh = sign.size[0] - 2, sign.size[1] - 2
        x = int(round(pt[0])) - sw // 2
        y = int(round(pt[1])) - sh
        _paste(img, sign, x, y)
        placer.reserve(x - 2, y - 2, x + sw + 2, y + sh + 2)
        self.last_sign_in_view = bool(x + 8 < w and x + sw - 8 > 0 and y + 8 < h and y + SIGN_BODY_H - 8 > 0)

    def _body_boxes(self, ents: Sequence[Dict[str, Any]], cam, size) -> List[Tuple[int, int, int, int]]:
        """The drawn BODY of every in-view creature (a person or a tuft), tighter than the scene's square atlas frame
        (a tier-3 frame is ~76 px square at 1.5x while the body inside it is ~40 wide with empty rows above the head):
        x inset by a quarter of the frame each side, the top 15 % of the frame dropped. Used only to decide whether an
        A/B/C glyph fades while someone walks in front of it; the placer keeps the full frames."""
        w, h = size
        out: List[Tuple[int, int, int, int]] = []
        for e in ents:
            bx = self._screen_box(e, cam, size)
            if bx is None:
                continue
            sx, sy, sw, sh = bx
            if sx + sw < 0 or sy + sh < 0 or sx > w or sy > h:
                continue
            ix, iy = int(sw * 0.25), int(sh * 0.15)
            out.append((sx + ix, sy + iy, sx + sw - ix, sy + sh))
        return out

    def _sprite_boxes(self, ents: Sequence[Dict[str, Any]], cam, size) -> List[Tuple[int, int, int, int]]:
        """Screen boxes of everything drawn on the land that a chip must not cover: every in-view entity (a seed's tuft
        included) and every in-view camp's sprite (hut / tent) or footprint (a hollow)."""
        w, h = size
        out: List[Tuple[int, int, int, int]] = []
        for e in ents:
            bx = self._screen_box(e, cam, size)
            if bx is None:
                continue
            sx, sy, sw, sh = bx
            if sx + sw < 0 or sy + sh < 0 or sx > w or sy > h:
                continue
            out.append((sx - 2, sy - 2, sx + sw + 2, sy + sh + 2))
        try:
            z = float(cam.scale(size)) / 4.0
        except Exception:
            z = 1.0
        for c in self._camps:
            if c.get("x") is None or c.get("y") is None:
                continue
            tier = int(c.get("tier") or 0)
            bt = CAMP_TO_BUILDING.get(tier, 1)
            if bt is None:
                hx, hy = float(c["x"]) - 4.0, float(c["y"]) - 6.0            # a hollow: the 8x6 footprint only
                pt = cam.sim_to_screen(hx, hy, size, margin_px=200.0)
                if pt is None:
                    continue
                bw, bh = 8 * 4 * z, 6 * 4 * z
                x0, y0 = pt
            else:
                hx, hy = float(c["x"]) - 4.0, float(c["y"]) - 8.0            # steading._hut_footprint: one 8-cell tile
                pt = cam.sim_to_screen(hx, hy, size, margin_px=200.0)
                if pt is None:
                    continue
                tiles = 2 if bt >= 2 else 1
                bw, bh = (HUT_SPRITE_W + 32 * (tiles - 1)) * z, HUT_SPRITE_H * z
                x0, y0 = pt[0] - HUT_SPRITE_DX * z, pt[1] - HUT_SPRITE_DY * z
            if x0 + bw < 0 or y0 + bh < 0 or x0 > w or y0 > h:
                continue
            out.append((int(x0) - 2, int(y0) - 2, int(x0 + bw) + 2, int(y0 + bh) + 2))
        return out

    @staticmethod
    def _walking_to(sc) -> Dict[str, int]:
        """Real pips walking to a waystone right now, per letter (state walking, then vote): the `+N` beside the count."""
        out: Dict[str, int] = {}
        b = getattr(sc, "behaviour", None)
        if b is None:
            return out
        try:
            for e in b.entities.values():
                if e.state == "walking" and getattr(e, "then", None) == "vote" and e.platform in PLATFORM_LETTERS:
                    out[e.platform] = out.get(e.platform, 0) + 1
        except Exception:
            return {}
        return out

    def _check_drawn(self, sc, ctx) -> None:
        """Honesty hardening (12): no string built by this frame's text layer carries a raw hidden, blocklisted
        (`builder #N`) or quarantined username as a whole token. Counts into honesty_violations; logs without the name."""
        try:
            hidden = set(str(u).lower() for u in ((ctx.mod or {}).get("hidden_users") or []))
            pips = (sc.world.data.get("pips") or {}) if getattr(sc, "world", None) is not None else {}
            forb = set(hidden)
            for k, p in pips.items():
                dn = p.get("display_name")
                if dn is None or str(dn).startswith("builder #"):
                    forb.add(str(k).lower())
            forb.update(str(k).lower() for k in ((sc.world.data.get("quarantine") or {}) if getattr(sc, "world", None) is not None else {}))
            forb = frozenset(n for n in forb if len(n) >= FORBIDDEN_MIN_LEN)
            if not forb or not _DRAWN:
                return
            rx = _FORBIDDEN_RE.get(forb)
            if rx is None:
                if len(_FORBIDDEN_RE) > 64:
                    _FORBIDDEN_RE.clear()
                rx = re.compile(r"(?<![a-z0-9_])(?:%s)(?![a-z0-9_])" % "|".join(re.escape(n) for n in sorted(forb, key=len, reverse=True)))
                _FORBIDDEN_RE[forb] = rx
            hits = 0
            for t in _DRAWN:
                if rx.search(str(t).lower()):
                    hits += 1
            if hits:
                self.honesty_violations += hits
                self.name_leaks += hits
                self._leaks_logged += 1
                if self._leaks_logged <= 3 or self._leaks_logged % 300 == 0:
                    _log("HONESTY: %d drawn string(s) this frame carry a hidden / blocklisted / quarantined username (never shown)" % hits)
        except Exception:
            pass

    # ------------------------------------------------------------------ plates (ONE at a time, on wood)
    def _plates(self, img, sc, cam, ld, now: float, size, placer: _Placer, drawn: List[str], static: bool, preset) -> None:
        """Camp / flower / tree / field plates, the cairn's plate and a raising's plate: HN Medium 22 on wood, one
        rotating plate per 5 s over the marks in view. Pinned: the DRIFT stop's plate while the camera dwells (the Moot
        dwell pins the cairn's), the cairn's for 10 s after a hatch, a raising in progress at its site. Every plate
        resolves to a pip row (display_name filtered) or a len(); nothing is invented."""
        if ld is None:
            return
        w, h = size
        marks = self._mark_list(sc, ld, now)
        in_view: List[Tuple] = []
        n_real = 0
        for mk in marks:
            pt = cam.sim_to_screen(mk[2], mk[3], size, margin_px=0.0)
            if pt is not None:
                in_view.append(mk + (pt,))
                if mk[1] in ("camp", "field", "flower", "tree", "reed", "flag", "cairn_stack"):
                    n_real += 1
        self.last_marks_in_view = n_real
        if not in_view:
            return
        in_view.sort(key=lambda m: m[0])
        pick: List[Tuple] = []
        picked_ids: set = set()
        stop = cam.drift_stop if cam.mode == "DRIFT" else None
        pin_ids: List[str] = []
        if stop is not None:
            sid = str(stop.get("id") or "")
            pin_ids.append("cairn:walkers" if (stop.get("kind") == "moot" or sid == "moot") else sid)
        if now < self._cairn_pin_until:
            pin_ids.append("cairn:walkers")
        pin_ids += [m[0] for m in in_view if m[1] == "raising"]
        for pid in pin_ids:
            if pid in picked_ids:
                continue
            pinned = next((m for m in in_view if m[0] == pid), None)
            if pinned is not None:
                pick.append(pinned)
                picked_ids.add(pid)
        if static:
            if self._plate_slot is None:
                self._plate_slot = int(now // PLATE_ROTATE_S)
            slot = self._plate_slot
        else:
            self._plate_slot = None
            slot = int(now // PLATE_ROTATE_S)
        rest = [m for m in in_view if m[0] not in picked_ids]
        try:
            anyone_awake = int(sc.awake_count()) > 0
        except Exception:
            anyone_awake = False
        if anyone_awake:
            # with people here, a camp plate rotates only while its owner is awake (it names THEM at their own camp);
            # a sleeper's tent plate over a sleeper is the least useful text for a stranger
            rest = [m for m in rest if m[1] != "camp" or self._owner_awake(sc, m[4])]
        if rest and not pick:
            pick.append(rest[slot % len(rest)])
        drift_camp = stop is not None and stop.get("kind") == "camp"
        for mk in pick:
            _id, kind, _x, _y, owner, text, (px, py) = mk
            if kind == "camp" and drift_camp and _id == str(stop.get("id") or ""):
                text = text + self._last_here(sc, owner, now)     # a DRIFT dwell adds ` · last here yesterday` (a day word, never a clock)
            strip = wood_chip(text, CREAM, CHIP_FONT, CHIP_SIZE, max_w=PLATE_MAX_W)
            pw, ph = strip.size
            x0 = max(2, min(w - pw - 2, int(px) - pw // 2))
            y0 = max(2, min(h - ph - 2, int(py) + 4))           # whole inside the region
            y = placer.place_either(x0, y0, pw, ph, ph + 4, 4, floor=2, ceiling=h - 2)
            if y is None:
                continue
            _paste(img, strip, x0, y)
            drawn.append(text)

    def _last_here(self, sc, key: Optional[str], now: float) -> str:
        try:
            p = sc.world.pip(key) or {}
            t0 = iso_to_epoch(p.get("last_seen_ts"))
            if t0 is None:
                return ""
            return " · last here " + _days_ago_text(t0, now)
        except Exception:
            return ""

    @staticmethod
    def _owner_awake(sc, key: Optional[str]) -> bool:
        b = getattr(sc, "behaviour", None)
        if b is None or not key:
            return False
        try:
            e = b.get(key)
            return bool(e is not None and e.is_awake())
        except Exception:
            return False

    CAIRN_UNTIL = {3: "and the cairn is named", 5: "and the hearth ring rises", 10: "until the Coast opens",
                   25: "until the Birch Wood opens", 50: "until the Tarn opens"}

    def _cairn_plate_text(self, sc) -> Optional[str]:
        """The walker count on the cairn's plate, forward form: `3 have walked here · 2 more and the cairn is named` /
        `17 have walked here · 8 more until the Coast opens` / `17 have walked here`; at 0 `3 more and the cairn is
        named` (never a negative shopfront). Every number a len() of real rows; no keeper words."""
        try:
            hatched = int(sc.hatched_ever())
            wd = sc.world.data.get("world") or {}
            ladder = [int(m) for m in (wd.get("milestones") or [3, 5, 10, 25, 50])]
            reached = set(int(m) for m in (wd.get("milestones_reached") or []))
        except Exception:
            return None
        nxt = next((m for m in ladder if m not in reached), None)
        until = self.CAIRN_UNTIL.get(int(nxt), "until the land grows") if nxt is not None else None
        if hatched == 0:
            return ("%d more %s" % (nxt, until)) if nxt is not None else None
        head = "%d ha%s walked here" % (hatched, "s" if hatched == 1 else "ve")
        if nxt is None or hatched >= nxt:
            return head
        return "%s · %d more %s" % (head, nxt - hatched, until)

    def _mark_list(self, sc, ld, now: float) -> List[Tuple[str, str, float, float, Optional[str], str]]:
        """(id, kind, x, y, owner, text) for every real mark with its plate text; rebuilt at most once a second (or when
        the number of camps / marks changes), since the texts move by the day and the rows by the session."""
        built_t, n_prev, cached = self._marks_cache
        kp = getattr(sc, "keepers", None)
        raising = getattr(kp, "raising", None) if kp is not None else None
        n_now = len(self._camps) + len(self._fields) + len(ld.marks) + ld.stock + (1000 if raising else 0) + int(sc.hatched_ever())
        if cached is not None and now - built_t < 1.0 and n_now == n_prev:
            return cached
        marks: List[Tuple[str, str, float, float, Optional[str], str]] = []    # (id, kind, x, y, owner, text)
        for c in self._camps:
            if c.get("x") is None:
                continue
            nm = self._shown(sc, c["key"])
            if not nm:
                continue
            fw, fh = CAMP_FOOTPRINT.get(int(c.get("tier") or 0), (10, 8))
            night = int(c.get("nights") or 0) or int(c.get("sessions_seen") or 0)
            text = "@%s's %s · night %d" % (nm, c["word"], max(1, night))
            marks.append(("camp:" + c["key"], "camp", float(c["x"]) + fw / 2.0, float(c["y"]) + fh, c["key"], text))
        for f in self._fields:
            nm = self._shown(sc, f["owner"])
            if not nm or f.get("x") is None:
                continue
            fo = ld.field_of(f["owner"])
            stage = ld.field_stage(fo, now)[1] if fo else str(f.get("stage") or "tilled")
            hv = int(f.get("harvests") or 0)
            text = "field · @%s · %s%s" % (nm, stage, (" · %d harvest%s" % (hv, "" if hv == 1 else "s")) if hv else "")
            marks.append(("field:" + f["owner"], "field", float(f["x"]) + 1.5, float(f["y"]) + 2.0, f["owner"], text))
        for m in ld.marks:
            typ = str(m.get("type") or "")
            if typ not in ("flower", "tree", "reed", "flag"):
                continue
            nm = self._shown(sc, m.get("owner"))
            if not nm:
                continue
            t0 = iso_to_epoch(m.get("ts")) if isinstance(m.get("ts"), str) else None
            when = _days_ago_text(t0, now).replace(" ago", "")          # `today` / `yesterday` / `3 days`
            if typ == "tree":
                stage = ld.tree_stage(m, now)[1]
                text = "tree · @%s · %s · %s" % (nm, stage, when)
            elif typ == "flag":
                text = "%s · first reached by @%s" % (L.strip_non_bmp(str((m.get("extra") or {}).get("place") or "here")), nm)
            else:
                text = "%s · @%s · %s" % (typ, nm, when)
            marks.append((str(m.get("id")), typ, float(m["x"]), float(m["y"]) + 1.0, m.get("owner"), text))
        # the cairn: the walker count (its plate), and the stackers when it has stones
        cx_, cy_ = float(ld.moot[0]) + 16.0, float(ld.moot[1]) + 10.0
        mxy = getattr(sc, "moot_xy", None)
        if callable(mxy):
            try:
                cx_, cy_ = (float(v) for v in mxy("cairn"))
            except Exception:
                pass
        walkers = self._cairn_plate_text(sc)
        if walkers:
            marks.append(("cairn:walkers", "cairn", cx_, cy_ + 3.0, None, walkers))
        if ld.stock:
            top = [(self._shown(sc, k), n) for k, n in ld.plaque("moot", 3)]
            names = " ".join("@" + nm for nm, _n in top if nm)
            if names:
                marks.append(("cairn:stack", "cairn_stack", cx_, cy_ + 3.0, None, "cairn · " + names))
        # a raising in progress (pinned at its site) and the last one landed (10 min)
        try:
            if isinstance(raising, dict) and raising.get("name"):
                by = self._shown(sc, (raising.get("plaque") or [None])[0])
                text = "raising · %s%s" % (L.strip_non_bmp(str(raising["name"])), (" · for @%s" % by) if by else "")
                marks.append(("raising:" + str(raising["name"]), "raising", float(raising.get("x") or ld.moot[0]), float(raising.get("y") or ld.moot[1]), None, text))
            lr = getattr(kp, "last_raised", None) if kp is not None else None
            if isinstance(lr, dict) and lr.get("name") and now - float(lr.get("t") or 0) < RAISED_PLATE_S:
                by = self._shown(sc, lr.get("by"))
                text = "%s · raised%s · %s" % (L.strip_non_bmp(str(lr["name"])), (" for @%s" % by) if by else "", _days_ago_text(float(lr.get("t") or now), now))
                marks.append(("raised:" + str(lr["name"]), "raised", float(lr.get("x") or ld.moot[0]), float(lr.get("y") or ld.moot[1]), None, text))
        except Exception:
            pass
        self._marks_cache = (now, n_now, marks)
        return marks

    # ================================================================== the cave text layer (PIP HOLLOW, kept verbatim for rollback)
    def _text_layer_cave(self, img: Image.Image, sc, ctx, size) -> None:
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

        # 4. the only-light line (10 s)
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

        # 5. moss labels on a 5 s rotation, in the SOIL BAND under the floor
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
        txt, col = self._plank_text(sc, ctx, now, names_on, accent) or ("", L.COLORS["text2"])
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
        cam = getattr(sc, "camera", None)
        booted = getattr(sc, "booted", False)
        return {"kind": scene_kind(), "frames": self._frames, "errors": self._errors,
                "avg_ms": round(sum(self._ms) / len(self._ms), 2) if self._ms else None,
                "max_ms": round(max(self._ms), 2) if self._ms else None,
                "text_avg_ms": round(sum(self._text_ms) / len(self._text_ms), 2) if self._text_ms else None,
                "text_max_ms": round(max(self._text_ms), 2) if self._text_ms else None,
                "honesty_violations": self.honesty_violations, "name_leaks": self.name_leaks,
                "stone_counts": dict(self.last_stone_counts), "board": {"drawn": self.last_board_drawn, "lit": self.last_board_lit,
                                                                        "titles": dict(self.last_board_titles), "timer": self.last_board_timer},
                "marker": self.last_marker, "sign_in_view": self.last_sign_in_view, "stones_in_view": self.last_stones_in_view,
                "beacon_in_view": self.last_beacon_in_view, "marks_in_view": self.last_marks_in_view, "sleepers_in_view": self.last_sleepers_in_view,
                "tile_px": self.last_tile_px, "plank": self.last_plank, "plank_row2": self.last_plank_row2,
                "hud_boxes": list(self.last_hud_boxes), "sprite_boxes": self.last_sprite_boxes,
                "labels_drawn": self._last_counts[0], "entities": self._last_counts[1], "plates_drawn": len(self.last_plates),
                "arrows_drawn": len(self.last_arrows), "text_cache": len(_TEXT), "bubble_cache": len(_BUBBLE), "chip_cache": len(_CHIP),
                "camera": cam.stats() if cam is not None else None,
                "honesty": mon.summary() if mon is not None else None, "keepers": kp.stats() if kp is not None else None,
                "degrade": dict(sc.degrade) if booted else None}


def _warm() -> None:
    """Load the faces and draw one chip of each kind at import time (the hot-reload moment), so frame 0 does not pay
    the ~50 ms of font loading inside the frame budget."""
    try:
        for face, size in (("Menlo", 20), ("Menlo", 22), ("HN Medium", 22), ("AB", 56)):
            L.font(face, size)
        for face, size in (("AB", 40), ("AB", 28), ("Menlo Bold", 24)):
            L.font(face, size)
        chip_img("warm", L.COLORS["text"])
        wood_chip("warm", CREAM)
        wood_chip("warm", CREAM, "Menlo", 22)
        label_chip("@warm", "#E6E8EE")
        text_strip("AB", 56, "A", L.COLORS["text"])
        text_strip("AB", 40, "A", L.COLORS["text"])
        text_strip("Menlo", 22, "0", L.COLORS["text2"])
        bubble_img([("warm", L.COLORS["text"])])
        dial_img(12.0, 0.5, 0.0)
    except Exception as e:
        _log("font warm-up skipped: %r" % (e,))


_warm()
PANEL = WorldPanel()
register(PANEL)
