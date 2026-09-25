"""layout.py - single source of geometry, fonts and palette for the SHIP IT LIVE compositor.

Every region from docs/CONCEPT.md section 3 is here as LAYOUT[key] = {
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
    "header_left":   {"box": (0, 0, 300, 66),    "font": "HN Medium", "size": 22, "role": "wordmark + chat-link dot"},
    "header_center": {"box": (300, 0, 620, 66),  "font": "AB",        "size": 56, "role": "version number 56px + NEXT SHIP mm:ss (Menlo 24)"},
    "header_right":  {"box": (920, 0, 360, 66),  "font": "Menlo",     "size": 22, "role": "SHIPPED n · FAILED m, LIVE dot + N watching"},
    "countdown":     {"box": (0, 66, 1280, 6),   "font": "none",      "size": 0,  "role": "full-width bar shrinking right-to-left over the 180 s round"},
    # stage (left column, top)
    "stage":         {"box": (0, 72, 840, 300),  "font": "HN Bold",   "size": 28, "role": "composite stage (title + step + body)"},
    "stage_title":   {"box": (0, 72, 840, 48),   "font": "HN Bold",   "size": 28, "role": "BUILDING vX: option, picked by @name + scene chip (Menlo 20)"},
    "stage_step":    {"box": (0, 120, 840, 16),  "font": "none",      "size": 0,  "role": "5-segment PLAN EDIT TEST SHIP LIVE rail, active segment pulses 1 Hz"},
    "stage_body":    {"box": (0, 136, 840, 236), "font": "Menlo",     "size": 22, "role": "mode-switching body: diff/status/canvas/answer/result/attract"},
    "activity_feed": {"box": (0, 372, 840, 120), "font": "Menlo",     "size": 22, "role": "last 4 lines of activity.jsonl, actor coloured, 28 px line height"},
    "ballot":        {"box": (0, 492, 840, 164), "font": "AB",        "size": 56, "role": "three 264x140 cards at x 16/288/560 y+8, tallies, voters, instruction line"},
    # right column
    "chat_pinned":   {"box": (840, 72, 440, 40),  "font": "HN Medium", "size": 22, "role": "rotating instruction strip / cooldown notices"},
    "chat_pane":     {"box": (840, 112, 440, 272), "font": "Menlo",    "size": 22, "role": "last 10 real chat messages, newest at bottom, 26 px line height"},
    "founders":      {"box": (840, 384, 440, 28),  "font": "Menlo",    "size": 20, "role": "first 10 real chatters of the session"},
    "ask_card":      {"box": (840, 412, 440, 124), "font": "HN",       "size": 24, "role": "ask/answer card, or last shipped version card when ask.enabled=false"},
    "next_up":       {"box": (840, 536, 440, 120), "font": "HN Medium", "size": 22, "role": "NEXT UP (macro): top 3 !idea entries"},
    # footer
    "ticker":        {"box": (0, 656, 880, 64),    "font": "HN Medium", "size": 24, "role": "right-to-left crawl: patch notes, honesty line, command legend"},
    "scope":         {"box": (880, 656, 160, 64),  "font": "none",      "size": 0,  "role": "oscilloscope of this frame's 1600-sample audio block (left channel)"},
    "readout":       {"box": (1040, 656, 240, 64), "font": "Menlo",     "size": 20, "role": "chat rate / chatters; fps · frame ms · uptime; stale/fallback flags"},
}

# Ballot card geometry (inside the ballot region, region-relative)
BALLOT_CARD_W, BALLOT_CARD_H = 264, 140
BALLOT_CARD_X = (16, 288, 560)
BALLOT_CARD_Y = 0            # cards span region y 0-139 (canvas 492-631); the card border doubles as the region's top edge
BALLOT_INSTRUCTION_Y = 133   # region-relative y of the instruction line: HN Bold 26 (bbox y 7..30) -> glyphs at 140-163,
                             # under the cards and inside the 164 px box
BALLOT_INSTRUCTION_FONT, BALLOT_INSTRUCTION_SIZE = "HN Bold", 26
# NOTE: CONCEPT 3 puts the instruction at canvas y 644 in 20 px Menlo, which overruns the 656 region edge by 12 px, and
# CONCEPT 2 promises the instruction "in 40 px type". QA (2026-09-25) found the default scene had no legible CTA above
# 20 px. The cards keep their 264x140 size and x positions; they sit 2 px higher than before (y 0) so a 26 px HN Bold
# accent instruction fits below them with no overlap and no clipping. 40 px would need a card-height change (forbidden).


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
