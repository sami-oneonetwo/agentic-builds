"""layout.py - single source of geometry, fonts and palette for the PIP HOLLOW compositor.

Every region from docs/WORLD.md section 5 (header/footer kept from CONCEPT.md section 3) is here as LAYOUT[key] = {
    "box":  (x, y, w, h)      pixel rectangle on the 1280x720 canvas
    "font": "<face name>"     one of FONT_FILES keys (AB, HN, HN Medium, HN Bold, Menlo, Menlo Bold)
    "size": <px>              primary text size for the region (never under 20)
    "role": "<what it shows>" human-readable purpose
}
Regions never move and never change font scale. Micro-ships may change colour/content, never geometry.

Panels reference a region by key (Panel.region). A panel's render() receives (w, h) of that box.
Composite keys (header, stage) exist for panels that want the whole strip.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, List, Tuple

W, H = 1280, 720
PAD = 16                 # inner padding in every region
MIN_TEXT_PX = 20         # nothing on screen is under 20 px

# ---------------------------------------------------------------------------- regions
LAYOUT: Dict[str, Dict] = {
    # header strip (the thumbnail: only this survives at 320x180)
    "header":        {"box": (0, 0, 1280, 66),   "font": "HN Medium", "size": 22, "role": "composite header strip"},
    "header_left":   {"box": (0, 0, 300, 66),    "font": "HN Medium", "size": 22, "role": "`atleastonce` / `PIP HOLLOW` wordmark + chat-link dot"},
    "header_center": {"box": (300, 0, 620, 66),  "font": "AB",        "size": 56, "role": "`3 AWAKE` AB 56 (`NOBODY AWAKE` AB 40) + `· 17 HATCHED` / `NEXT EVENT mm:ss` Menlo 24 (+ keeper carving line Menlo 20)"},
    "header_right":  {"box": (920, 0, 360, 66),  "font": "Menlo",     "size": 22, "role": "version string; red LIVE dot + real `N watching` or `--`"},
    "countdown":     {"box": (0, 66, 1280, 6),   "font": "none",      "size": 0,  "role": "full-width bar shrinking right-to-left over the 180 s round"},
    # the world (WORLD.md 5, region 5): the 320x110 sim at 4x plus the screen-scale text layer
    "world":         {"box": (0, 72, 1280, 440), "font": "Menlo",     "size": 22, "role": "the cave: sim 320x110 at 4x; plank HN Medium 22, pip labels Menlo 20, bubbles Menlo 22, platform letters AB 56"},
    # the three strips under the world (WORLD.md 5, regions 6-8)
    "colony":        {"box": (0, 512, 420, 144),   "font": "HN Medium", "size": 22, "role": "colony bar (hatched / next milestone), awake · asleep line, 8 s rotation (last event, nightly board, !stats)"},
    "keeper":        {"box": (420, 512, 420, 144), "font": "HN Medium", "size": 22, "role": "keeper on duty / off duty; carving or last carved line; traceback lines only on failure"},
    "chat_log":      {"box": (840, 512, 440, 144), "font": "Menlo",     "size": 22, "role": "last 5 moderated messages past the hold, 26 px lines, letter chip on votes, shield chip on mod actions"},
    # footer
    "ticker":        {"box": (0, 656, 880, 64),    "font": "HN Medium", "size": 24, "role": "right-to-left crawl: events / ships, honesty line, command legend"},
    "scope":         {"box": (880, 656, 160, 64),  "font": "none",      "size": 0,  "role": "oscilloscope of this frame's 1600-sample audio block (left channel)"},
    "readout":       {"box": (1040, 656, 240, 64), "font": "Menlo",     "size": 20, "role": "chat rate / chatters; fps · frame ms · uptime; stale/fallback flags; `world: glow off`"},
}

# Removed with the living-world pivot (WORLD.md 5): stage_title, stage_step, stage_body, activity_feed, ballot,
# chat_pinned, chat_pane, founders, ask_card, next_up (and the composite `stage`). Their information moved: stage ->
# lantern + keeper strip; activity feed -> keeper line 2 + ticker; ballot -> the three stone platforms; pinned strip ->
# the plank; chat -> bubbles + chat_log; founders -> plank `woke the Hollow` + nightly board; next up -> wall scrolls.
REMOVED_REGIONS = ("stage", "stage_title", "stage_step", "stage_body", "activity_feed", "ballot", "chat_pinned",
                   "chat_pane", "founders", "ask_card", "next_up")

# World text-layer geometry (region-relative px inside `world`; WORLD.md 5 row 5)
WORLD_PLANK_XY = (16, 12)        # canvas (16, 84): the plank's top-left
WORLD_BUBBLE_MAX_W = 408         # bubble box max width, 3 lines of Menlo 22
WORLD_DENSITY_FALLBACK = 40      # above this many awake pips: labels only while speaking, sleepers stop rotating labels


def region_box(key: str) -> Tuple[int, int, int, int]:
    return LAYOUT[key]["box"]


def region_size(key: str) -> Tuple[int, int]:
    x, y, w, h = LAYOUT[key]["box"]
    return (w, h)


# ---------------------------------------------------------------------------- colours
COLORS = {
    "bg":        "#0B0E14",
    "panel":     "#11151D",
    "hairline":  "#1C2130",
    "text":      "#E6E8EE",
    "text2":     "#8A90A0",
    "add":       "#3DDC84",
    "remove":    "#FF6B6B",
    "warn":      "#FFB020",
    "danger":    "#FF4D4D",
    "accent":    "#53FC18",
}

# 8 fixed accent presets (every one >= 4.5:1 on #0B0E14). No user hex is ever accepted.
PRESETS = {
    "kick":    {"accent": "#53FC18", "names": ["#53FC18", "#7DD3FC", "#FCD34D", "#F9A8D4", "#C4B5FD", "#FDBA74"]},
    "ember":   {"accent": "#FF6A2B", "names": ["#FF6A2B", "#FFB020", "#FDE68A", "#FCA5A5", "#F9A8D4", "#FDBA74"]},
    "ice":     {"accent": "#5AD1FF", "names": ["#5AD1FF", "#93C5FD", "#A5F3FC", "#C4B5FD", "#E0F2FE", "#BAE6FD"]},
    "violet":  {"accent": "#A78BFA", "names": ["#A78BFA", "#C4B5FD", "#F9A8D4", "#7DD3FC", "#FCD34D", "#DDD6FE"]},
    "gold":    {"accent": "#FFC53D", "names": ["#FFC53D", "#FDE68A", "#FDBA74", "#FCD34D", "#FFE8A3", "#FBBF24"]},
    "magenta": {"accent": "#FF5CA8", "names": ["#FF5CA8", "#F9A8D4", "#FBCFE8", "#C4B5FD", "#FCA5A5", "#FDA4AF"]},
    "cyan":    {"accent": "#22D3EE", "names": ["#22D3EE", "#67E8F9", "#A5F3FC", "#7DD3FC", "#5EEAD4", "#99F6E4"]},
    "paper":   {"accent": "#E8E2D0", "names": ["#E8E2D0", "#D6D3C4", "#FDE68A", "#BAE6FD", "#FBCFE8", "#C7D2FE"]},
}
DEFAULT_PRESET = "kick"

ACTOR_COLORS = {
    "builder": "#E6E8EE", "qa": "#22D3EE", "critic": "#C4B5FD", "supervisor": "#8A90A0",
    "compositor": "#8A90A0", "ship": "accent", "mod": "#FFB020", "fail": "#FF4D4D",
    "chat": "#7DD3FC", "agent": "#E6E8EE",
}


def preset(name: str) -> Dict:
    return PRESETS.get(name or DEFAULT_PRESET, PRESETS[DEFAULT_PRESET])


def hex_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def name_color(username: str, preset_name: str) -> str:
    """Stable hashed colour for a username from the preset's 6-colour set."""
    names = preset(preset_name)["names"]
    s = 0
    for ch in (username or ""):
        s = (s * 31 + ord(ch)) & 0xFFFFFFFF
    return names[s % len(names)]


# ---------------------------------------------------------------------------- fonts
_SYS = "/System/Library/Fonts"
# face name -> list of (path, index) candidates, first that loads wins
FONT_FILES = {
    "AB":         [(os.path.join(_SYS, "Supplemental", "Arial Black.ttf"), 0), (os.path.join(_SYS, "ArialHB.ttc"), 0),
                   (os.path.join(_SYS, "Avenir Next.ttc"), 0)],
    "HN":         [(os.path.join(_SYS, "HelveticaNeue.ttc"), 0), (os.path.join(_SYS, "Avenir Next.ttc"), 0)],
    "HN Medium":  [(os.path.join(_SYS, "HelveticaNeue.ttc"), 10), (os.path.join(_SYS, "HelveticaNeue.ttc"), 0),
                   (os.path.join(_SYS, "Avenir Next.ttc"), 0)],
    "HN Bold":    [(os.path.join(_SYS, "HelveticaNeue.ttc"), 1), (os.path.join(_SYS, "Avenir Next.ttc"), 0)],
    "Menlo":      [(os.path.join(_SYS, "Menlo.ttc"), 0), (os.path.join(_SYS, "Monaco.ttf"), 0)],
    "Menlo Bold": [(os.path.join(_SYS, "Menlo.ttc"), 1), (os.path.join(_SYS, "Monaco.ttf"), 0)],
}

_FONT_CACHE: Dict[Tuple[str, int], object] = {}


def font(name: str, size: int):
    """Cached PIL ImageFont for a face name + size. Falls back to Monaco / Avenir Next / PIL default."""
    from PIL import ImageFont
    key = (name, int(size))
    f = _FONT_CACHE.get(key)
    if f is not None:
        return f
    for path, idx in FONT_FILES.get(name, []) + FONT_FILES["Menlo"]:
        try:
            f = ImageFont.truetype(path, int(size), index=idx)
            break
        except Exception:
            continue
    if f is None:
        f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


def text_width(name: str, size: int, text: str) -> int:
    f = font(name, size)
    try:
        return int(f.getlength(text))
    except Exception:
        return int(f.getbbox(text)[2])


def _fit(name: str, size: int, text: str, max_w: int, suffix: str = "") -> int:
    """Largest n such that text[:n] + suffix fits in max_w px. Binary search: O(log n) font measurements
    instead of the one-character-per-loop shave that cost O(n) measurements per call (journal 009)."""
    if max_w <= 0 or not text:
        return 0
    if text_width(name, size, text + suffix) <= max_w:
        return len(text)
    lo, hi = 0, len(text) - 1                  # invariant: text[:lo] fits, text[:hi+1] does not
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if text_width(name, size, text[:mid] + suffix) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return lo


_WORD_BOUNDARY_KEEP = 0.6      # cut at a word boundary when it keeps >= 60 % of the characters that fit
_TRAIL_PUNCT = " ,;:·-–—("


@lru_cache(maxsize=8192)
def truncate(name: str, size: int, text: str, max_w: int, ell: str = "…") -> str:
    """Fit text into max_w px, ending in `ell` when it had to be cut. The cut lands on a word boundary
    ("palette ember, picked by …" not "palette ember, picked by @sa…") unless that would throw away
    more than 40 % of what fits (one long token, a username, a hash): then it cuts mid-token.
    Memoised (lru_cache 8192): the same title/strip/feed line is measured once, not every render."""
    if text_width(name, size, text) <= max_w:
        return text
    n = _fit(name, size, text, max_w, ell)
    if n <= 0:
        return ell if text_width(name, size, ell) <= max_w else ""
    head = text[:n]
    if n < len(text) and text[n] != " ":       # cut fell inside a word: back up to the last space
        sp = head.rfind(" ")
        if sp > 0 and sp >= int(n * _WORD_BOUNDARY_KEEP):
            head = head[:sp]
    head = head.rstrip(_TRAIL_PUNCT)
    if not head:
        head = text[:n]
    return head + ell


@lru_cache(maxsize=4096)
def _wrap_tuple(name: str, size: int, text: str, max_w: int, max_lines: int) -> Tuple[str, ...]:
    words = (text or "").split(" ")
    lines: List[str] = []
    cur = ""
    for wd in words:
        cand = wd if not cur else cur + " " + wd
        if text_width(name, size, cand) <= max_w:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            # hard-split a single overlong word (binary search per piece, not one measurement per character)
            while len(wd) > 1 and text_width(name, size, wd) > max_w:
                k = max(1, _fit(name, size, wd, max_w))
                lines.append(wd[:k]); wd = wd[k:]
            cur = wd
    if cur:
        lines.append(cur)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = truncate(name, size, lines[-1] + " …", max_w)
    return tuple(lines)


def wrap(name: str, size: int, text: str, max_w: int, max_lines: int = 0):
    """Greedy word wrap to pixel width; returns a NEW list of lines (last one truncated with … if capped).
    Memoised on (font, size, text, width, max_lines); callers may mutate the returned list freely."""
    return list(_wrap_tuple(name, int(size), text or "", int(max_w), int(max_lines or 0)))


def strip_non_bmp(s: str) -> str:
    return "".join(ch for ch in (s or "") if ord(ch) < 0x10000)


if __name__ == "__main__":  # quick geometry sanity print
    for k, v in LAYOUT.items():
        x, y, w, h = v["box"]
        assert 0 <= x and x + w <= W and 0 <= y and y + h <= H, k
        print("%-14s x=%4d y=%4d w=%4d h=%4d  %s %s  %s" % (k, x, y, w, h, v["font"], v["size"], v["role"]))
    for n in FONT_FILES:
        print(n, font(n, 22).getname())
