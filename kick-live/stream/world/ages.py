"""stream/world/ages.py - the ages of the settlement (AGES.md 2.1-2.5, 4.2 `age`; IDLEWORLD.md 1.2, 1.6, 2.3 tier 3).

    from stream.world import ages as AG
    d = AG.AgeDirector(scene)                 # the scene makes one at boot (steading._boot, W4 hook)
    d.round_closed(now, ctx)                  # the scene's round-close hook: age_check() once per round close
    evs = d.tick(now, ctx, behaviour_events)  # every frame after behaviour.tick: the 90 s sequencer, the hauls
    d.live_sprites(now, visible)              # (y, sprite, (x, y)) rows the scene y-sorts with its props
    d.plate_marks(now, shown)                 # the monument plate, both forms, for the world panel's ONE-plate rotation
    AG.age_gate(people, stones, days)         # the ladder as a function; AG.age_ok(world) for honesty

The three keys are len()s (PEOPLE = hatched_ever, STONES = len(stones), DAYS = distinct local dates with a real
record). The gate is checked at a round close only, never inside a ship hold, the last 30 s of a round or a keeper
raising. A met gate writes `age` and an `age_history` row with a forced save; the visible build runs off
`age_built < age`, so a reboot mid-build resumes (the delivered count is the history row's `stones_placed`) and two
ages earned at once play back to back. `age` never decreases: honesty's `age` rule asserts it every frame.

Schema: the fields are read with .get() (schema 2 has none: the gate is computed from counts) and WRITTEN only when
the world file already carries `age` or state.SCHEMA >= 3 (W3's migration); otherwise the director keeps its state in
memory and logs once. Imports of behaviour / honesty / keepers / compositor / registry are lazy (hot reload order).

The build (~90 s): call (bells once, everyone turns, camera EVENT at the Moot easing to 0.75x, plank
`the Camp · 3 people · 16 stones · 3 days`) -> gathering (every settler walks to the Moot ring, Behaviour.gather_to)
-> build (min(24, pile) REAL stones hauled from the pile beside the cairn to the sites by settlers walking with
then `haul:pick` / `haul:place` and `carry_stone`; the pile shrinks by exactly the delivered count; the sites' finished
sprites reveal bottom-up through Keepers.reveal_rows at <= 1 Hz, paced 60-75 s) -> plaque (the plate flips, joy 1 s,
camp floors cascade one per 2.5 s, `age_built = age`, bake_ver bump, the plate pins 20 s).

Copy: every plate / plank string is composed here and checked with compositor.Compositor.banned_copy_hits before
it is handed out; a string that fails is not drawn. No `day N`, no `longgrass`, no `build`, no promise words.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
import re
import sys
import time as _time
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ----------------------------------------------------------------------------- the ladder (AGES 2.2), local fallback
AGE_LADDER_FALLBACK: Tuple[Tuple[int, int, int], ...] = ((1, 0, 1), (3, 10, 2), (5, 30, 5), (10, 80, 10), (25, 200, 25))
AGE_NAMES_FALLBACK: Tuple[str, ...] = ("the Clearing", "the Camp", "the Steading", "the Village", "the Town")
CENTURY_STEP = (25, 200, 25)          # beyond the table: (25 + 25 k, 200 + 200 k, 25 + 25 k), `the Nth Century`
KEY_WORDS = (("people", "person", "people"), ("stones", "stone", "stones"), ("days", "day", "days"))

PILE_RESERVE = 5                      # the cairn's own stones: pile = len(stones) - 5 - placed
HAULS_MAX = 24                        # stones moved per build, at most
HAULERS_MAX = 8                       # settlers hauling at once
HAUL_SPEED = 6.0                      # cells/s (AGES 2.5)
CALL_S = 5.0                          # step 1: bells, everyone turns
GATHER_S = 20.0                       # step 2 ends: everyone at the Moot ring
BUILD_S = 60.0                        # step 3 nominal (the reveal is paced to this whether one hauls or twenty)
BUILD_MAX_S = 75.0                    # step 3 hard cap: what is not moved by then stays in the pile (logged once)
PLAQUE_S = 10.0                       # step 4
REVEAL_STEP_S = 1.0                   # the reveal advances at most 1 Hz (nothing flashes above 1 Hz)
FLARE_HZ = 1.0                        # the beacon flare during a build toggles at 1 Hz (was 2 Hz)
CAM_ZOOM = 0.75
CAM_REISSUE_S = 10.0                  # the camera EVENT is re-asserted this often while the build runs
FLOOR_CASCADE_S = 2.5                 # camp floors rise one per this many seconds in the plaque step
PLATE_PIN_S = 20.0                    # the plate pins this long after the plaque
PLATE_ALT_S = 10.0                    # the two plate forms alternate at this cadence in the rotation
NAMES_MAX = 6                         # `raised by` names shown; beyond: `and N others`
SAVE_EVERY_S = 5.0                    # age_build saved this often while a build runs
MIN_ROUND_LEFT_S = 30.0               # never start inside the last 30 s of a round
BOOT_GRACE_S = 3.0                    # a build never starts in the first frames (sheets landing)
NEXT_BUILD_GAP_S = 5.0                # two ages earned at once: the second build starts this long after the first
HAUL_RELEASE_S = 20.0                 # a hauler that did not arrive in this long is released (a stuck walk)
PROJECT_MIN_ASKERS = 2
LEDGER_FILE = "wishes.jsonl"
FENCES_ON = False                     # AGES 2.3 fences round sown fields ship after the art-rules exception (D1) is written

# ----------------------------------------------------------------------------- copy checks (compositor by value, else the same patterns)
_BANNED_FALLBACK = ("ai", "keeper", "keepers", "on duty", "build", "builds", "show", "live", "version", "fps", "ms", "viewer",
                    "viewers", "watching", "camera", "mic", "fake", "honest", "honesty", "surveying", "awake", "longgrass")
_BANNED_RE = re.compile(r"(?<![a-z0-9_])(?:%s)(?![a-z0-9_])" % "|".join(re.escape(t) for t in sorted(_BANNED_FALLBACK, key=len, reverse=True)))
_DAY_RE = re.compile(r"(?<![a-z0-9_])day \d+")
_VERSION_RE = re.compile(r"(?<![a-z0-9_])v\d+\.\d+")
_CLOCK_RE = re.compile(r"(?<![0-9:])\d{1,2}:\d{2}(?![0-9:])")


def banned_hits(strings: Sequence[str]) -> List[str]:
    """compositor.Compositor.banned_copy_hits when importable (the owner's rule as a function), else the same patterns."""
    try:
        from stream import compositor as C
        fn = getattr(C, "banned_copy_hits", None) or C.Compositor.banned_copy_hits
        return list(fn(list(strings)))
    except Exception:
        out = []
        for t in strings:
            low = re.sub(r"@[^\s·]+", "", str(t or "")).lower()
            if _BANNED_RE.search(low) or _DAY_RE.search(low) or _VERSION_RE.search(low) or _CLOCK_RE.search(low):
                out.append(str(t))
        return out


def validated(text: Optional[str]) -> Optional[str]:
    """The string when it passes the copy check, else None (a failed string draws nothing)."""
    if not text:
        return None
    return None if banned_hits([text]) else text


def flare_on(now: float) -> bool:
    """The beacon flare phase during a build: keepers.flare_on when present (W4 hook there), else 1 Hz here."""
    try:
        from stream.world import keepers as K
        fn = getattr(K, "flare_on", None)
        if callable(fn):
            return bool(fn(now))
    except Exception:
        pass
    return int(now * FLARE_HZ) % 2 == 0


# ----------------------------------------------------------------------------- ladder math
def ladder() -> Tuple[Tuple[Tuple[int, int, int], ...], Tuple[str, ...]]:
    """(AGE_LADDER, AGE_NAMES): land.py's when W3 added them there, else the local fallback."""
    try:
        from stream.world import land as LAND
        lad = getattr(LAND, "AGE_LADDER", None)
        names = getattr(LAND, "AGE_NAMES", None)
        if lad and names and len(lad) >= 2 and len(names) >= 2:
            return tuple(tuple(int(v) for v in r) for r in lad), tuple(str(n) for n in names)
    except Exception:
        pass
    return AGE_LADDER_FALLBACK, AGE_NAMES_FALLBACK


def rung(idx: int) -> Tuple[int, int, int]:
    """(people, stones, days) required for age `idx`; beyond the table the Centuries."""
    lad, _ = ladder()
    idx = max(0, int(idx))
    if idx < len(lad):
        return lad[idx]
    k = idx - len(lad) + 1
    top = lad[-1]
    return (top[0] + CENTURY_STEP[0] * k, top[1] + CENTURY_STEP[1] * k, top[2] + CENTURY_STEP[2] * k)


def _ordinal(n: int) -> str:
    n = int(n)
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "%d%s" % (n, suf)


def age_name(idx: int) -> str:
    lad, names = ladder()
    idx = max(0, int(idx))
    if idx < len(names):
        return names[idx]
    return "the %s Century" % _ordinal(idx - len(lad) + 1)


def age_gate(people: int, stones: int, days: int, cap: int = 200) -> int:
    """The highest rung all three keys reach (AND of three; nothing is spent)."""
    p, s, d = int(people), int(stones), int(days)
    idx = 0
    while idx + 1 <= cap:
        rp, rs, rd = rung(idx + 1)
        if p >= rp and s >= rs and d >= rd:
            idx += 1
        else:
            break
    return idx


def shortfalls(idx: int, people: int, stones: int, days: int) -> List[Tuple[str, int, int]]:
    """For the rung `idx`: [(key, short_by, required)] for the keys still short, most binding first: the ladder's
    order people > stones > days (AGES 2.4 / IDLEWORLD 1.6 examples: `2 more people · 14 more stones · 2 more days`,
    `1 more person and 4 stones`; a person is the slowest key to come at the funnel's rates)."""
    rp, rs, rd = rung(idx)
    out = []
    for (key, _s, _p), have, req in zip(KEY_WORDS, (people, stones, days), (rp, rs, rd)):
        short = int(req) - int(have)
        if short > 0:
            out.append((key, short, int(req)))
    return out


def _count_word(n: int, key: str) -> str:
    for k, one, many in KEY_WORDS:
        if k == key:
            return "%d %s" % (n, one if n == 1 else many)
    return "%d %s" % (n, key)


def forward_text(idx: int, people: int, stones: int, days: int, project: Optional[Tuple[str, int]] = None) -> Optional[str]:
    """`the Steading · 2 more people · 14 more stones · 2 more days` (most binding first) + ONE project clause
    `· a bridge · 12 ask` when given. None when nothing is short (the age is earned) or the copy check fails."""
    parts = ["%d more %s" % (short, (one if short == 1 else many))
             for (key, short, _req) in shortfalls(idx, people, stones, days)
             for (k, one, many) in KEY_WORDS if k == key]
    if not parts:
        return None
    text = "%s · %s" % (age_name(idx), " · ".join(parts))
    if project and project[0] and int(project[1]) >= PROJECT_MIN_ASKERS:
        text += " · %s · %d ask" % (project[0], int(project[1]))
    return validated(text)


def gap_line(idx: int, people: int, stones: int, days: int) -> Optional[str]:
    """The plank's gap line after a round close when a key moved: `1 more person and 4 stones until the Steading`."""
    sf = shortfalls(idx, people, stones, days)
    if not sf:
        return None
    words = []
    for i, (key, short, _req) in enumerate(sf):
        w = _count_word(short, key)                              # `1 person` / `4 stones`
        words.append(("%d more %s" % (short, w.split(" ", 1)[1])) if i == 0 else w)
    if len(words) == 1:
        body = words[0]
    elif len(words) == 2:
        body = "%s and %s" % (words[0], words[1])
    else:
        body = "%s, %s and %s" % (words[0], words[1], words[2])
    return validated("%s until %s" % (body, age_name(idx)))


def turn_line(idx: int, people: int, stones: int, days: int) -> Optional[str]:
    """The plank at the turn: `the Camp · 3 people · 16 stones · 3 days`."""
    return validated("%s · %s · %s · %s" % (age_name(idx), _count_word(people, "people"), _count_word(stones, "stones"),
                                            _count_word(days, "days")))


def since_text(ts: Optional[str]) -> Optional[str]:
    """`26 Sep` (local date, no leading zero, no year, no clock) from an ISO timestamp."""
    if not ts:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        t = _dt.datetime.fromisoformat(s)
        if t.tzinfo is None:
            t = t.replace(tzinfo=_dt.timezone.utc)
        loc = t.astimezone()
        return "%d %s" % (loc.day, loc.strftime("%b"))
    except Exception:
        return None


def names_clause(names: Sequence[str], limit: int = NAMES_MAX) -> str:
    """`@a @b @c` with `and N others` beyond `limit`."""
    names = [n for n in names if n]
    shown = ["@%s" % n for n in names[:limit]]
    rest = len(names) - len(shown)
    out = " ".join(shown)
    if rest > 0:
        out += " and %d other%s" % (rest, "" if rest == 1 else "s")
    return out


def reached_text(idx: int, since: Optional[str], people: int, raised_by: Sequence[str],
                 wished: Optional[Tuple[str, Sequence[str]]] = None) -> Optional[str]:
    """`the Camp · since 26 Sep · 3 have walked here · raised by @a @b @c`; with a project wished for the age:
    `· a bridge · wished by @kai @jo` before `raised by`. Every number a len()."""
    parts = [age_name(idx)]
    if since:
        parts.append("since %s" % since)
    people = int(people)
    if people > 0:
        parts.append("%d ha%s walked here" % (people, "s" if people == 1 else "ve"))
    if wished and wished[0] and wished[1]:
        parts.append(wished[0])
        parts.append("wished by " + names_clause(wished[1]))
    if raised_by:
        parts.append("raised by " + names_clause(raised_by))
    return validated(" · ".join(parts))


# ----------------------------------------------------------------------------- honesty helpers (AGES 4.2 `age`)
def age_ok(world: Dict[str, Any], last_age: Optional[int] = None, people: Optional[int] = None,
           days: Optional[int] = None) -> Tuple[bool, List[str]]:
    """(ok, problems) for a world block (or the director's memory block): `age <= age_gate(people, stones, days)`,
    monotonic against `last_age`, `age_built <= age`, `sum(stones_placed) <= len(stones)`. `people` / `days` default to
    the block's `hatched_ever` / `len(days_on_air)`."""
    probs: List[str] = []
    try:
        age = int(world.get("age") or 0)
        built = int(world.get("age_built") or 0)
        stones = len(world.get("stones") or [])
        p = int(world.get("hatched_ever") or 0) if people is None else int(people)
        d = len(world.get("days_on_air") or []) if days is None else int(days)
    except Exception as ex:
        return False, ["age fields unreadable: %r" % (ex,)]
    gate = age_gate(p, stones, d)
    if age > gate:
        probs.append("age %d > age_gate(%d people, %d stones, %d days) = %d" % (age, p, stones, d, gate))
    if last_age is not None and age < int(last_age):
        probs.append("age regressed %d -> %d" % (int(last_age), age))
    if built > age:
        probs.append("age_built %d > age %d" % (built, age))
    placed = 0
    at_stones = 0                                                # the stones on record at reach: a later `!banish` purges a
    for h in world.get("age_history") or []:                     # person's stones, the placed count is the raising's history
        try:
            placed += int((h or {}).get("stones_placed") or 0)
            at_stones = max(at_stones, int(((h or {}).get("at") or {}).get("stones") or 0))
        except Exception:
            probs.append("age_history row unreadable")
    if placed > max(stones, at_stones):
        probs.append("stones_placed %d > len(stones) %d" % (placed, stones))
    if age < 0 or built < 0:
        probs.append("negative age")
    return (not probs), probs


def age_violations(scene, monitor=None) -> List[str]:
    """The honesty `age` rule for a scene: reads the director's block (world or memory), remembers the last age on the
    monitor (`_age_last`) so a regression across frames is caught; the gate uses the director's day count. A history
    row's counts at reach are the record: a later `!banish` that drops a count below the rung is NOT a violation
    (AGES 2.5 never-regress), so the gate is checked against the greater of the live counts and the counts at reach."""
    d = getattr(scene, "ages", None)
    w = getattr(scene, "world", None)
    blk = None
    people = days = None
    if d is not None:
        try:
            blk = d.block()
            people, _s, days = d.counts()
        except Exception as ex:
            return ["director unreadable: %r" % (ex,)]
    elif w is not None:
        try:
            blk = (w.data.get("world") or {})
            people = int(getattr(w, "hatched_ever", 0) or 0)
        except Exception as ex:
            return ["world unreadable: %r" % (ex,)]
    if blk is None or "age" not in blk:
        return []                                                  # schema 2 with no director: nothing to assert
    last = getattr(monitor, "_age_last", None) if monitor is not None else None
    ok, probs = age_ok(blk, last_age=last, people=people, days=days)
    if not ok and any(p_.startswith("age ") and "> age_gate" in p_ for p_ in probs):
        at = None
        for h in blk.get("age_history") or []:
            if int((h or {}).get("idx") or -1) == int(blk.get("age") or 0):
                at = (h or {}).get("at")
        if isinstance(at, dict):
            rp, rs, rd = rung(int(blk.get("age") or 0))
            if int(at.get("people") or 0) >= rp and int(at.get("stones") or 0) >= rs and int(at.get("days") or 0) >= rd:
                probs = [p_ for p_ in probs if not (p_.startswith("age ") and "> age_gate" in p_)]   # earned at reach: history
    if monitor is not None:
        try:
            cur = int(blk.get("age") or 0)
            monitor._age_last = max(int(last), cur) if last is not None else cur
        except Exception:
            pass
    return probs


# ----------------------------------------------------------------------------- the keys from records
def local_dates(chat_path: str, offset: int = 0, banished: Sequence[str] = (), max_bytes: int = 64 * 1024 * 1024) -> Tuple[Set[str], int]:
    """Distinct LOCAL calendar dates with >= 1 chat record (type message, a named sender not banished) from `offset`;
    returns (dates, new_offset). One read; the caller keeps the offset and calls again for the tail."""
    dates: Set[str] = set()
    try:
        size = os.path.getsize(chat_path)
    except OSError:
        return dates, 0
    if offset > size:
        offset = 0
    if size - offset > max_bytes:
        offset = size - max_bytes
    try:
        with open(chat_path, "rb") as fh:
            fh.seek(offset)
            data = fh.read(size - offset)
    except OSError:
        return dates, offset
    last_nl = data.rfind(b"\n")
    if last_nl < 0:
        return dates, offset
    ban = set(str(b).lower() for b in banished)
    for line in data[: last_nl + 1].splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line.decode("utf-8", "replace"))
        except Exception:
            continue
        if not isinstance(m, dict) or m.get("type") not in (None, "message"):
            continue
        name = str(m.get("username") or m.get("user") or m.get("name") or m.get("slug") or "").lower()
        if not name or name in ban:
            continue
        ts = m.get("ts") or m.get("created_at")
        t = None
        if isinstance(ts, str):
            try:
                t = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=_dt.timezone.utc)
            except Exception:
                t = None
        elif m.get("t") is not None:
            try:
                t = _dt.datetime.fromtimestamp(float(m["t"]), tz=_dt.timezone.utc)
            except Exception:
                t = None
        if t is None:
            continue
        dates.add(t.astimezone().date().isoformat())
    return dates, offset + last_nl + 1


_CLUSTER_CACHE: Dict[str, Tuple[int, Dict[str, Set[str]]]] = {}


def project_clusters(run_dir: str, banished: Sequence[str] = ()) -> Dict[str, Set[str]]:
    """slug -> distinct asker keys from the wish ledger ($RUN_DIR/wishes.jsonl), classed with registry.classify
    (`project:<slug>`); cached by file size. {} when the ledger or the registry is absent (W6 / W5 own them)."""
    path = os.path.join(run_dir or "", LEDGER_FILE)
    try:
        size = os.path.getsize(path)
    except OSError:
        return {}
    hit = _CLUSTER_CACHE.get(path)
    if hit is not None and hit[0] == size:
        return hit[1]
    out: Dict[str, Set[str]] = {}
    try:
        from stream.world import registry as R
        projects = dict(getattr(R, "AGE_PROJECTS", {}) or {})
        classify = getattr(R, "classify", None)
    except Exception:
        projects, classify = {}, None
    if not projects or not callable(classify):
        _CLUSTER_CACHE[path] = (size, out)
        return out
    ban = set(str(b).lower() for b in banished)
    try:
        with open(path, "rb") as fh:
            data = fh.read(min(size, 16 * 1024 * 1024))
    except OSError:
        return out
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line.decode("utf-8", "replace"))
        except Exception:
            continue
        if not isinstance(row, dict) or not row.get("wish", True):
            continue
        key = str(row.get("key") or row.get("by") or "").lower()
        text = row.get("text")
        if not key or key in ban or not isinstance(text, str) or not text.strip():
            continue
        try:
            w = classify(text, verb=row.get("verb"), hint=row.get("hint"), kind=str(row.get("kind") or "plain"))
            cls = str(getattr(w, "cls", "") or "")
        except Exception:
            continue
        if cls.startswith("project:"):
            slug = cls.split(":", 1)[1]
            if slug in projects:
                out.setdefault(slug, set()).add(key)
    _CLUSTER_CACHE[path] = (size, out)
    return out


def project_noun(slug: str) -> Optional[str]:
    try:
        from stream.world import registry as R
        n = (getattr(R, "NOUNS", {}) or {}).get(slug)
        return str(n) if n else None
    except Exception:
        return None


# ----------------------------------------------------------------------------- kit composites (AGES 2.3, the existing kit only)
_COMPOSITES: Dict[Tuple, np.ndarray] = {}
_REVEALED: Dict[Tuple, np.ndarray] = {}

# what rises per age: (object, layout point, cell offset). Points: moot / hearth / cairn (steading.MOOT_LAYOUT names).
AGE_SITES: Dict[int, Tuple[Tuple[str, str, Tuple[int, int]], ...]] = {
    1: (("hearth_ring", "hearth", (0, 3)),),
    2: (("well", "moot", (14, -6)), ("cairn_ring", "cairn", (0, 2)), ("drift", "moot", (-22, 14)), ("drift2", "moot", (22, 18))),
    3: (("longhouse", "moot", (-24, 10)), ("plaza_ring", "moot", (0, 17))),
    4: (("hall", "moot", (-24, 10)), ("stone_bases", "moot", (26, -12))),
}
PILE_OFFSET = (7, 2)                  # the pile stands beside the cairn (cell offset from the cairn's ground point)


def _sun_b(sun) -> Tuple[float, float]:
    try:
        from stream.world.art import props
        return props._sun_bucket(sun)
    except Exception:
        return (round(float(sun[0]), 2), round(float(sun[1]), 2))


def _over(dst: np.ndarray, spr: np.ndarray, x: int, y: int) -> None:
    """RGBA `spr` over RGBA `dst` at (x, y) (bake.blit writes RGB destinations only)."""
    h, w = spr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(dst.shape[1], x + w), min(dst.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return
    s = spr[y0 - y:y1 - y, x0 - x:x1 - x]
    a = s[..., 3:4].astype(np.uint16)
    if not a.any():
        return
    d = dst[y0:y1, x0:x1]
    da = d[..., 3:4].astype(np.uint16)
    d[..., :3] = ((s[..., :3].astype(np.uint16) * a + d[..., :3].astype(np.uint16) * (255 - a)) // 255).astype(np.uint8)
    d[..., 3:4] = np.minimum(255, a + (da * (255 - a)) // 255).astype(np.uint8)


def _compose(items: Sequence[Tuple[float, float, np.ndarray]], pad: int = 2) -> np.ndarray:
    """Composite (dx, dy, sprite) items, y-sorted, by their ground points relative to the composite's ground point
    (props.anchor convention: bottom centre, 4 px up). Returns one RGBA array."""
    from stream.world.art import props
    if not items:
        return np.zeros((8, 8, 4), dtype=np.uint8)
    xs0, xs1, ys0, ys1 = [], [], [], []
    for dx, dy, spr in items:
        ax, ay = props.anchor(spr)
        xs0.append(dx - ax)
        xs1.append(dx - ax + spr.shape[1])
        ys0.append(dy - ay)
        ys1.append(dy - ay + spr.shape[0])
    x0, x1 = int(math.floor(min(xs0))) - pad, int(math.ceil(max(xs1))) + pad
    y0, y1 = int(math.floor(min(ys0))) - pad, int(math.ceil(max(ys1))) + pad
    y1 = max(y1, 4 + pad)                                    # the ground point (0, 0) sits 4 px above the bottom
    half = max(-x0, x1)
    w, h = 2 * half, y1 - y0
    canvas = np.zeros((h, w, 4), dtype=np.uint8)
    gx, gy = half, h - 4                                     # composite ground point (bottom centre, 4 px up)
    for dx, dy, spr in sorted(items, key=lambda it: it[1]):
        ax, ay = props.anchor(spr)
        _over(canvas, spr, int(round(gx + dx)) - ax, int(round(gy + dy)) - ay)
    return canvas


def _ring(n: int, rx: float, ry: float, sun, variant0: int = 0, seed: str = "ring") -> List[Tuple[float, float, np.ndarray]]:
    from stream.world.art import props
    from stream.world import land as LAND
    out = []
    for i in range(int(n)):
        a = 2.0 * math.pi * i / max(1, n) + 0.3
        j = LAND.name_hash(seed, str(i)) % 7 - 3
        out.append((rx * math.cos(a) + j * 0.3, ry * math.sin(a), props.stone((variant0 + i) % 3, sun)))
    return out


def pile_sprite(n: int, sun) -> np.ndarray:
    """The loose stones beside the cairn: exactly `n` stones (every stone drawn once), a spiral heap, y-sorted."""
    from stream.world.art import props
    n = max(0, int(n))
    key = ("pile", n, _sun_b(sun))
    hit = _COMPOSITES.get(key)
    if hit is not None:
        return hit
    items = []
    golden = math.pi * (3.0 - math.sqrt(5.0))
    for k in range(n):
        r = 3.2 * math.sqrt(k)
        a = k * golden
        items.append((r * math.cos(a), 0.55 * r * math.sin(a), props.stone(k % 3, sun)))
    spr = _compose(items)
    _COMPOSITES[key] = spr
    return spr


def site_sprite(obj: str, sun) -> np.ndarray:
    """One finished site object from the kit (a composite RGBA with a props.anchor ground point)."""
    from stream.world.art import props, buildings
    key = (obj, _sun_b(sun))
    hit = _COMPOSITES.get(key)
    if hit is not None:
        return hit
    items: List[Tuple[float, float, np.ndarray]] = []
    if obj == "hearth_ring":                                  # 8 props.stone round the Moot hearth (decoration)
        items = _ring(8, 22.0, 11.0, sun, 1, "hearth")
    elif obj == "cairn_ring":                                 # the cairn gains a base ring of pile stones
        items = _ring(10, 15.0, 7.5, sun, 0, "cairn")
    elif obj == "plaza_ring":
        items = _ring(14, 34.0, 15.0, sun, 2, "plaza")
    elif obj == "stone_bases":
        items = [(-10.0, 0.0, props.stone(1, sun)), (0.0, 1.0, props.stone(2, sun)), (10.0, 0.0, props.stone(0, sun))]
    elif obj in ("drift", "drift2"):                          # denser meadow flower drifts round the Steading
        for i in range(7):
            a = 0.9 * i
            items.append((10.0 * math.cos(a) * (1.0 + 0.12 * i), 4.0 * math.sin(a) * (1.0 + 0.1 * i), props.flowers(i % 4, 0)))
    elif obj == "well":
        spr, (dx, dy) = buildings.render("well", 1, (168, 158, 146), None, False, sun)
        items = [(0.0, 0.0, _rebased(spr, dx, dy))]
    elif obj == "longhouse":
        spr, (dx, dy) = buildings.render("hut", 3, (150, 112, 82), "longhouse", False, sun)
        items = [(0.0, 0.0, _rebased(spr, dx, dy, foot=True))]
    elif obj == "hall":
        spr, (dx, dy) = buildings.render("hut", 3, (166, 160, 150), "hall", False, sun)
        items = [(0.0, 0.0, _rebased(spr, dx, dy, foot=True))]
    elif obj.startswith("monument_ring"):
        k = int(obj.rsplit(":", 1)[-1]) if ":" in obj else 1
        items = _ring(10 + 2 * k, 15.0 + 4.0 * k, 7.5 + 2.0 * k, sun, k, obj)
    else:
        items = _ring(6, 12.0, 6.0, sun, 0, obj)
    spr = _compose(items)
    _COMPOSITES[key] = spr
    return spr


def _rebased(spr: np.ndarray, dx: int, dy: int, foot: bool = False) -> np.ndarray:
    """A buildings.render sprite (anchor offset dx, dy from its ground point) padded so props.anchor (bottom centre, 4 px
    up) lands on that ground point. `foot`: the building's ground point is its footprint's top-left; use the bottom
    centre of the sprite instead (the hut stands on its base)."""
    h, w = spr.shape[:2]
    if foot:
        gx, gy = w // 2, h - 2
    else:
        gx, gy = int(dx), int(dy)
    half = max(gx, w - gx)
    W = 2 * half
    pad_bot = max(0, 4 - (h - gy))                          # the ground row ends up 4 px above the bottom (a sprite whose
    H = h + pad_bot                                          # body reaches further below its ground point draws those px higher)
    out = np.zeros((H, W, 4), dtype=np.uint8)
    ox = half - gx
    out[0:h, ox:ox + w] = spr
    return out


def reveal_rows(progress: float, sprite_h: int) -> int:
    try:
        from stream.world import keepers as K
        return int(K.Keepers.reveal_rows(progress, sprite_h))
    except Exception:
        return int(round(max(0.0, min(1.0, progress)) * int(sprite_h)))


def revealed(spr: np.ndarray, progress: float) -> np.ndarray:
    """The finished sprite with its bottom `reveal_rows` rows shown (the raising's reveal mask, its first drawing consumer)."""
    h = spr.shape[0]
    rows = reveal_rows(progress, h)
    if rows >= h:
        return spr
    key = (id(spr), rows)
    hit = _REVEALED.get(key)
    if hit is None:
        hit = np.zeros_like(spr)
        if rows > 0:
            hit[h - rows:] = spr[h - rows:]
        if len(_REVEALED) > 400:
            _REVEALED.clear()
        _REVEALED[key] = hit
    return hit


# ----------------------------------------------------------------------------- the director
class AgeDirector(object):
    """Owns the age state (in the world block when the file carries it, else in memory), the gate check at round close,
    the 90 s build sequencer, the pile, the site composites and the plate / plank strings."""

    def __init__(self, scene, log: Optional[Callable[[str], None]] = None):
        self.scene = scene
        self.log = log or getattr(scene, "log", None) or (lambda m: sys.stderr.write("ages: %s\n" % m))
        self.mem: Dict[str, Any] = {}                            # the block when the world file cannot hold the fields
        self.persist: Optional[bool] = None                      # decided at the first block() read
        self._logged_mem = False
        self.build: Optional[Dict[str, Any]] = None              # the running sequencer
        self._pending: List[Dict[str, Any]] = []
        self._dates: Set[str] = set()
        self._chat_offset = 0
        self._dates_t = -1e18
        self._last_keys: Optional[Tuple[int, int, int]] = None
        self._boot_t: Optional[float] = None
        self._next_build_t = 0.0
        self._save_t = -1e18
        self._cam_t = -1e18
        self._plate_pin_until = 0.0
        self._plate_cache: Tuple[float, Tuple, List] = (-1e18, (), [])
        self._reveal_t = -1e18
        self._reveal_p: Dict[str, float] = {}
        self._deferred = 0                                        # age checks refused by a hold / the last 30 s / a raising
        self._test_build_due = False
        self._test_build_at = BOOT_GRACE_S
        self.checks = 0
        self.turns = 0                                            # ages earned while this director ran
        self.builds_done = 0
        self.hauls_done = 0
        self.errors = 0
        self.stats_plank: List[str] = []
        self.forced_build = False                                 # TEST HOOK (KL_AGE_BUILD, test mode only)
        try:
            self._refresh_dates(float(getattr(scene, "_last_now", None) or _time.time()), force=True)
        except Exception as ex:
            self.log("ages: day count unavailable at boot (%r)" % (ex,))
        try:
            self._resume()
        except Exception as ex:
            self.errors += 1
            self.log("ages: resume failed: %r" % (ex,))

    # ------------------------------------------------------------------ the block
    def _world(self) -> Optional[Dict[str, Any]]:
        w = getattr(self.scene, "world", None)
        try:
            return w.data["world"] if w is not None else None
        except Exception:
            return None

    def block(self) -> Dict[str, Any]:
        """The dict the age fields live in: the world block when it already has `age` or state.SCHEMA >= 3, else memory
        (seeded from the world block's counts; logged once)."""
        wb = self._world()
        if wb is None:
            return self.mem
        if self.persist is None:
            schema3 = False
            try:
                from stream.world import state as ST
                schema3 = int(getattr(ST, "SCHEMA", 2) or 2) >= 3
            except Exception:
                schema3 = False
            self.persist = ("age" in wb) or schema3
            if not self.persist and not self._logged_mem:
                self._logged_mem = True
                self.log("ages: world.json is schema 2 without age fields; the age state stays in memory until the migration")
        if self.persist:
            wb.setdefault("age", 0)
            wb.setdefault("age_built", 0)
            wb.setdefault("age_history", [])
            return wb
        if not self.mem:
            self.mem = {"age": int(wb.get("age") or 0), "age_built": int(wb.get("age_built") or 0),
                        "age_history": list(wb.get("age_history") or []), "age_build": None}
        # the memory block mirrors the record lists it asserts against (read-only views)
        self.mem["stones"] = wb.get("stones") or []
        self.mem["hatched_ever"] = wb.get("hatched_ever")
        self.mem["days_on_air"] = wb.get("days_on_air") or sorted(self._dates)
        return self.mem

    @property
    def age(self) -> int:
        return int(self.block().get("age") or 0)

    @property
    def age_built(self) -> int:
        return int(self.block().get("age_built") or 0)

    @property
    def history(self) -> List[Dict[str, Any]]:
        return self.block().setdefault("age_history", [])

    def _dirty(self, force: bool = False, now: Optional[float] = None) -> None:
        w = getattr(self.scene, "world", None)
        if w is None or not self.persist:
            return
        w.dirty = True
        if force:
            try:
                w.save(float(now if now is not None else _time.time()), force=True)
            except Exception as ex:
                self.log("ages: forced save failed: %r" % (ex,))

    # ------------------------------------------------------------------ the keys
    def _refresh_dates(self, now: float, force: bool = False) -> None:
        w = getattr(self.scene, "world", None)
        path = getattr(w, "chat_path", None) if w is not None else None
        if not path:
            path = os.path.join(getattr(self.scene, "run_dir", "") or "", "chat.jsonl")
        if not force and now - self._dates_t < 30.0:
            return
        self._dates_t = now
        ban = list((getattr(w, "data", {}) or {}).get("banished", {}).keys()) if w is not None else []
        dates, off = local_dates(path, self._chat_offset, ban)
        self._dates |= dates
        self._chat_offset = off

    def days(self) -> int:
        wb = self._world() or {}
        doa = wb.get("days_on_air")
        if isinstance(doa, list) and doa:
            return len(doa)                                       # W3's field when present
        return len(self._dates)

    def people(self) -> int:
        w = getattr(self.scene, "world", None)
        try:
            return int(getattr(w, "hatched_ever", 0) or 0)
        except Exception:
            wb = self._world() or {}
            return int(wb.get("hatched_ever") or 0)

    def stones(self) -> int:
        wb = self._world() or {}
        return len(wb.get("stones") or [])

    def counts(self) -> Tuple[int, int, int]:
        return self.people(), self.stones(), self.days()

    def placed_total(self) -> int:
        n = 0
        for h in self.history:
            try:
                n += int((h or {}).get("stones_placed") or 0)
            except Exception:
                pass
        return n

    def pile(self) -> int:
        """len(stones) - 5 - placed: the loose stones beside the cairn (never negative)."""
        return max(0, self.stones() - PILE_RESERVE - self.placed_total())

    def gate(self) -> int:
        p, s, d = self.counts()
        return age_gate(p, s, d)

    # ------------------------------------------------------------------ geometry
    def _moot_xy(self, what: str) -> Tuple[float, float]:
        fn = getattr(self.scene, "moot_xy", None)
        if callable(fn) and what != "moot":
            try:
                x, y = fn(what)
                return float(x), float(y)
            except Exception:
                pass
        ld = getattr(self.scene, "land", None)
        m = getattr(ld, "moot", None)
        if m is None:
            T = getattr(self.scene, "terrain", None)
            m = getattr(T, "site", None) or (480.0, 220.0)
        off = {"hearth": (-16, 10), "cairn": (16, 10), "beacon": (6, -10)}.get(what, (0, 0))
        return float(m[0]) + off[0], float(m[1]) + off[1]

    def _snap(self, x: float, y: float, r: int = 24) -> Tuple[float, float]:
        T = getattr(self.scene, "terrain", None)
        fn = getattr(T, "nearest_passable", None)
        if callable(fn):
            try:
                nx, ny = fn(int(round(x)), int(round(y)), r) or (x, y)
                return float(nx), float(ny)
            except Exception:
                pass
        return float(x), float(y)

    def pile_xy(self) -> Tuple[float, float]:
        cx, cy = self._moot_xy("cairn")
        return self._snap(cx + PILE_OFFSET[0], cy + PILE_OFFSET[1], 12)

    def sites_for(self, idx: int) -> List[Dict[str, Any]]:
        """The site objects age `idx` raises: [{obj, x, y}] (cells, ground points)."""
        idx = int(idx)
        rows = AGE_SITES.get(idx)
        if rows is None:
            lad, _n = ladder()
            k = max(1, idx - len(lad) + 1)
            rows = (("monument_ring:%d" % k, "cairn", (0, 2 + k)),)
        out = []
        for obj, point, (dx, dy) in rows:
            px, py = self._moot_xy(point)
            x, y = px + dx, py + dy
            if obj in ("well", "longhouse", "hall"):
                x, y = self._snap(x, y, 24)
            out.append({"obj": obj, "x": float(x), "y": float(y)})
        return out

    # ------------------------------------------------------------------ the gate (AGES 2.5)
    def _in_hold(self, ctx) -> Tuple[bool, str]:
        try:
            live = getattr(ctx, "compositor_live", None) or {}
            if isinstance(live, dict) and (live.get("hold") or live.get("probation")):
                return True, "ship hold"
            macro = getattr(ctx, "macro", None) or {}
            if isinstance(macro, dict) and macro.get("active"):
                return True, "macro in flight"
            rem = getattr(ctx, "round_remaining", None)
            if rem is not None and 0 <= float(rem) <= MIN_ROUND_LEFT_S:
                return True, "last %d s of a round" % int(MIN_ROUND_LEFT_S)
            kp = getattr(self.scene, "keepers", None)
            if kp is not None and getattr(kp, "raising", None):
                return True, "keeper raising"
        except Exception:
            pass
        return False, ""

    def round_closed(self, now: float, ctx) -> Optional[int]:
        """The scene's round-close hook: the gate once per close; else the plank's gap line when a key moved."""
        try:
            self._refresh_dates(now, force=True)
            turned = self.age_check(now, ctx)
            if turned is None:
                p, s, d = self.counts()
                keys = (p, s, d)
                if self._last_keys is not None and keys != self._last_keys and self.build is None:
                    line = gap_line(self.age + 1, p, s, d)
                    if line:
                        self._emit({"type": "age_gap", "plank": line, "idx": self.age + 1})
                self._last_keys = keys
            return turned
        except Exception as ex:
            self.errors += 1
            self.log("ages: round_closed failed: %r" % (ex,))
            return None

    def age_check(self, now: float, ctx=None) -> Optional[int]:
        """Compare the three ints once (the caller is the round close). Refused inside a ship hold, the last 30 s of a
        round or a keeper raising. A met gate writes `age` and one history row per rung earned with a forced save and
        returns the new age; None otherwise. Never lowers `age`."""
        held, why = self._in_hold(ctx)
        self.checks += 1
        if held:
            self._deferred += 1
            return None
        blk = self.block()
        p, s, d = self.counts()
        gate = age_gate(p, s, d)
        cur = int(blk.get("age") or 0)
        if gate <= cur:
            self._last_keys = (p, s, d)
            return None
        ts = None
        w = getattr(self.scene, "world", None)
        try:
            ts = w.iso(now) if w is not None else None
        except Exception:
            ts = None
        if not ts:
            ts = _dt.datetime.fromtimestamp(now, tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        raised = self._raised_by()
        clusters = self._clusters()
        for idx in range(cur + 1, gate + 1):
            wished = {slug: sorted(keys) for slug, keys in clusters.items() if self._project_age(slug) == idx and len(keys) >= PROJECT_MIN_ASKERS}
            askers = sorted(set(k for keys in wished.values() for k in keys) - set(raised))
            row = {"idx": idx, "name": age_name(idx), "ts": ts, "at": {"people": p, "stones": s, "days": d},
                   "raised_by": list(raised) + askers, "stones_placed": 0, "wished_by": wished}
            self.history.append(row)
        blk["age"] = gate
        self.turns += gate - cur
        self._last_keys = (p, s, d)
        self._dirty(force=True, now=now)
        self.log("ages: %s earned (%d people, %d stones, %d days); age %d -> %d, age_built %d" % (
            age_name(gate), p, s, d, cur, gate, int(blk.get("age_built") or 0)))
        return gate

    def _project_age(self, slug: str) -> Optional[int]:
        try:
            from stream.world import registry as R
            v = (getattr(R, "AGE_PROJECTS", {}) or {}).get(slug)
            return int(v) if v is not None else None
        except Exception:
            return None

    def _clusters(self) -> Dict[str, Set[str]]:
        w = getattr(self.scene, "world", None)
        ban = list((getattr(w, "data", {}) or {}).get("banished", {}).keys()) if w is not None else []
        try:
            return project_clusters(getattr(self.scene, "run_dir", "") or "", ban)
        except Exception:
            return {}

    def top_project(self) -> Optional[Tuple[str, int]]:
        """(noun, askers) for the most-asked project with >= 2 distinct askers, or None."""
        cl = self._clusters()
        best = None
        for slug, keys in cl.items():
            if len(keys) >= PROJECT_MIN_ASKERS and (best is None or len(keys) > best[1]):
                noun = project_noun(slug)
                if noun:
                    best = (noun, len(keys))
        return best

    def _raised_by(self) -> List[str]:
        """Every real pip key on the land at the turn, top stackers first, then by name."""
        b = getattr(self.scene, "behaviour", None)
        ld = getattr(self.scene, "land", None)
        counts: Dict[str, int] = {}
        try:
            counts = dict(ld.stackers()) if ld is not None else {}
        except Exception:
            counts = {}
        keys = []
        if b is not None:
            for k, e in b.entities.items():
                try:
                    if getattr(e, "origin", None) == "chat" and e.is_on_land():
                        keys.append(k)
                except Exception:
                    continue
        return sorted(keys, key=lambda k: (-counts.get(k, 0), k))

    # ------------------------------------------------------------------ the sequencer
    def _resume(self) -> None:
        blk = self.block()
        ab = blk.get("age_build")
        if isinstance(ab, dict) and int(ab.get("idx") or 0) == self.age_built + 1 and self.age_built < self.age:
            placed = 0                                            # the history row's stones_placed is the record (saved with every
            for h in self.history:                                # forced save); age_build.delivered may lag it by up to 5 s
                if int((h or {}).get("idx") or -1) == int(ab["idx"]):
                    placed = int((h or {}).get("stones_placed") or 0)
            self.build = {"idx": int(ab["idx"]), "t0": None, "needed": int(ab.get("needed") or 0),
                          "delivered": max(int(ab.get("delivered") or 0), placed), "sites": list(ab.get("sites") or []),
                          "resumed": True, "haulers": {}, "step": "resume", "floor_done": [], "floor_t": -1e18, "logged_cap": False,
                          "forced": False}
            self.log("ages: resuming %s (%d of %d stones moved before the reboot)" % (
                age_name(self.build["idx"]), self.build["delivered"], self.build["needed"]))

    def _emit(self, ev: Dict[str, Any]) -> None:
        self._pending.append(ev)

    def start_build(self, idx: int, now: float, forced: bool = False) -> Dict[str, Any]:
        """Step 1 of the transition for age `idx`: the call. `forced` is the test hook (no gate, nothing written)."""
        needed = min(HAULS_MAX, self.pile())
        sites = self.sites_for(idx)
        self.build = {"idx": int(idx), "t0": now, "needed": needed, "delivered": 0, "sites": sites, "resumed": False,
                      "haulers": {}, "step": "call", "floor_done": [], "floor_t": -1e18, "logged_cap": False, "forced": forced}
        self.forced_build = self.forced_build or forced
        self._reveal_p = {}
        p, s, d = self.counts()
        mx, my = self._moot_xy("moot")
        line = turn_line(idx, p, s, d)
        ev = {"type": "age", "idx": int(idx), "name": age_name(idx), "x": mx, "y": my, "zoom": CAM_ZOOM,
              "hold_s": GATHER_S + BUILD_MAX_S + PLAQUE_S, "at": {"people": p, "stones": s, "days": d}, "needed": needed}
        if line:
            ev["plank"] = line
            self.stats_plank.append(line)
        self._emit(ev)
        self._cam_t = now
        self._face_moot()
        self._set_behaviour_build(sites, idx)
        self.log("ages: %s rises: %d stones to move, %d site(s)%s" % (age_name(idx), needed, len(sites), " (test hook)" if forced else ""))
        return self.build

    def _set_behaviour_build(self, sites, idx: int) -> None:
        b = getattr(self.scene, "behaviour", None)
        if b is None:
            return
        try:                                                     # the Behaviour.build hook: the errand director holds
            b.build = {"pile": self.pile_xy(), "site": (sites[0]["x"], sites[0]["y"]) if sites else self._moot_xy("moot"), "idx": int(idx)}
        except Exception:
            pass

    def _face_moot(self) -> None:
        b = getattr(self.scene, "behaviour", None)
        if b is None:
            return
        mx, my = self._moot_xy("moot")
        for e in b.entities.values():
            try:
                if e.is_on_land() and e.state in ("idle", "sitting"):
                    dx, dy = mx - e.x, my - e.y
                    fx = 1 if dx > 0.5 else (-1 if dx < -0.5 else 0)
                    fy = 1 if dy > 0.5 else (-1 if dy < -0.5 else 0)
                    if fx or fy:
                        e.facing = (fx, fy)
            except Exception:
                continue

    def tick(self, now: float, ctx, events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Every frame after behaviour.tick: start a due build, run the sequencer, consume the haulers' arrive events.
        Returns the director's events for scene.events (camera / audio / plank / save consumers)."""
        self._pending = []
        try:
            if self._boot_t is None:
                self._boot_t = now
                self._maybe_test_hook(ctx)
            if self.build is None:
                if now - self._boot_t >= BOOT_GRACE_S and now >= self._next_build_t:
                    if self.age_built < self.age:
                        self.start_build(self.age_built + 1, now)
                    elif self._test_build_due and now - self._boot_t >= self._test_build_at:
                        self._test_build_due = False
                        self.start_build(self.age_built + 1, now, forced=True)
            if self.build is not None:
                self._step(now, ctx, events)
        except Exception as ex:
            self.errors += 1
            if self.errors <= 3:
                import traceback
                self.log("ages: tick failed (%d): %s" % (self.errors, traceback.format_exc().strip().splitlines()[-1]))
            if self.build is not None and self.errors > 30:
                self._finish(now, failed=True)
        out, self._pending = self._pending, []
        return out

    def _maybe_test_hook(self, ctx) -> None:
        """TEST HOOK (KL_AGE_BUILD=1, test mode under /tmp only): one forced build of age_built + 1, nothing written."""
        if os.environ.get("KL_AGE_BUILD") != "1":
            return
        try:
            from stream.world import test_pips_allowed
            if test_pips_allowed(getattr(self.scene, "run_dir", "") or "", ctx, dict(os.environ, KL_TEST_PIPS="1")) > 0:
                self._test_build_due = True
                self._test_build_at = max(BOOT_GRACE_S, float(os.environ.get("KL_AGE_BUILD_AT_S") or BOOT_GRACE_S))
                self.log("TEST HOOK: KL_AGE_BUILD=1 (one forced age raising %.0f s after boot, nothing written)" % self._test_build_at)
        except Exception:
            pass

    def _elapsed(self, now: float) -> float:
        bd = self.build
        if bd["t0"] is None:                                     # a resumed build starts at the build step
            bd["t0"] = now - GATHER_S
            bd["step"] = "build"
            self._emit_cam(now, force=True)
            self._set_behaviour_build(bd["sites"], bd["idx"])
        return now - bd["t0"]

    def _emit_cam(self, now: float, force: bool = False) -> None:
        """Re-assert the camera EVENT at the Moot (0.75x) while the build runs, unless another event holds the camera."""
        if not force and now - self._cam_t < CAM_REISSUE_S:
            return
        cam = getattr(self.scene, "camera", None)
        cur = getattr(cam, "_event", None) if cam is not None else None
        if cur is not None and cur.get("type") not in ("age", "age_cam") and not force:
            return                                               # a person's event (hatch, camp) outranks the build's frame
        self._cam_t = now
        mx, my = self._moot_xy("moot")
        left = max(4.0, (self.build["t0"] + GATHER_S + BUILD_MAX_S + PLAQUE_S) - now)
        self._emit({"type": "age_cam", "x": mx, "y": my, "zoom": CAM_ZOOM, "hold_s": left})

    def _step(self, now: float, ctx, events: Sequence[Dict[str, Any]]) -> None:
        bd = self.build
        el = self._elapsed(now)
        step = bd["step"]
        if step in ("call", "resume") and el >= CALL_S:
            bd["step"] = step = "gather"
            self._gather(now)
        if step == "gather" and el >= GATHER_S:
            bd["step"] = step = "build"
        if step == "build":
            self._hauls(now, events)
            done = bd["delivered"] >= bd["needed"]
            if (el >= GATHER_S + BUILD_S and done) or el >= GATHER_S + BUILD_MAX_S:
                if not done and not bd["logged_cap"]:
                    bd["logged_cap"] = True
                    self.log("ages: %s: %d of %d stones moved before the cap; the rest stay in the pile" % (
                        age_name(bd["idx"]), bd["delivered"], bd["needed"]))
                self._release_all(now)
                bd["step"] = step = "plaque"
                bd["plaque_t0"] = now
                self._plaque(now)
        if step == "plaque":
            self._cascade(now)
            if now - bd.get("plaque_t0", now) >= PLAQUE_S:
                self._finish(now)
                return
        self._emit_cam(now)
        if now - self._save_t >= SAVE_EVERY_S:
            self._save_t = now
            self._save_build(now)

    def _save_build(self, now: float) -> None:
        bd = self.build
        if bd is not None and bd.get("forced"):
            return
        blk = self.block()
        if bd is None:
            blk["age_build"] = None
        else:
            blk["age_build"] = {"idx": bd["idx"], "t0": bd["t0"], "step": bd["step"], "needed": bd["needed"],
                                "delivered": bd["delivered"], "sites": [dict(s) for s in bd["sites"]]}
        self._dirty(force=False)

    def _gather(self, now: float) -> None:
        b = getattr(self.scene, "behaviour", None)
        if b is None:
            return
        mx, my = self._moot_xy("moot")
        n = 0
        for k, e in list(b.entities.items()):
            try:
                if e.is_on_land() and b.gather_to(k, (mx, my), now):
                    n += 1
            except Exception:
                continue
        self.log("ages: gathering: %d settlers walk to the Moot ring" % n)

    # -- step 3: the hauls
    def _hauls(self, now: float, events: Sequence[Dict[str, Any]]) -> None:
        bd = self.build
        b = getattr(self.scene, "behaviour", None)
        if b is None or not bd["sites"]:
            return
        hs: Dict[str, Dict[str, Any]] = bd["haulers"]
        pile = self.pile_xy()
        for ev in events:
            if ev.get("type") != "arrive":
                continue
            at = str(ev.get("at") or "")
            key = ev.get("pip")
            if not at.startswith("haul:") or key not in hs:
                continue
            e = b.get(key)
            if e is None or ev.get("gave_up"):
                if e is not None and getattr(e, "carry", None) == "stone":
                    b.drop(key, now)
                self._release(key, now)
                continue
            if at == "haul:pick":
                if bd["delivered"] + self._carrying() < bd["needed"] and b.carry(key, now, "stone"):
                    site = bd["sites"][(bd["delivered"] + self._carrying()) % len(bd["sites"])]
                    side = 1.0 if (hash(key) & 1) else -1.0
                    tgt = self._snap(site["x"] + side * 3.0, site["y"] + 2.0, 8)
                    if b.walk_to(key, tgt, now, then="haul:place", speed=HAUL_SPEED):
                        hs[key] = {"stage": "to_site", "t": now}
                    else:
                        b.drop(key, now)
                        self._release(key, now)
                else:
                    self._release(key, now)
            elif at == "haul:place":
                if getattr(e, "carry", None) == "stone":
                    b.drop(key, now)
                    bd["delivered"] += 1
                    self.hauls_done += 1
                    self._record_placed(bd["idx"], bd["delivered"])
                    self._emit({"type": "age_haul", "pip": key, "idx": bd["idx"], "delivered": bd["delivered"], "needed": bd["needed"],
                                "x": e.x, "y": e.y})
                hs.pop(key, None)
                if bd["delivered"] + self._carrying() + self._to_pile() < bd["needed"] and b.walk_to(key, pile, now, then="haul:pick", speed=HAUL_SPEED):
                    hs[key] = {"stage": "to_pile", "t": now}
        # haulers that were sent elsewhere (a verb, a vote) or stalled: released
        for key in list(hs):
            e = b.get(key)
            then = str(getattr(e, "then", None) or "") if e is not None else ""
            if e is None or not e.is_on_land() or not then.startswith("haul:") or now - hs[key]["t"] > HAUL_RELEASE_S:
                if e is not None and getattr(e, "carry", None) == "stone":
                    b.drop(key, now)
                self._release(key, now)
        # dispatch: here settlers first, nearest the pile next, while stones remain unclaimed
        want = bd["needed"] - bd["delivered"] - self._carrying() - self._to_pile()
        if want <= 0 or len(hs) >= HAULERS_MAX:
            return
        cands = []
        for k, e in b.entities.items():
            if k in hs:
                continue
            try:
                if not e.is_on_land() or e.state in ("voting", "hidden") or getattr(e, "carry", None):
                    continue
                then = str(getattr(e, "then", None) or "")
                if e.state == "walking" and not (then in ("idle", "gather", "sit", "") or then.startswith("errand:")):
                    continue                                     # a verb walk or a vote walk is the person's
                here = 1 if e.is_present(now) else 0
                d = math.hypot(e.x - pile[0], e.y - pile[1])
                cands.append((-here, d, k))
            except Exception:
                continue
        cands.sort()
        for _h, _d, k in cands:
            if want <= 0 or len(hs) >= HAULERS_MAX:
                break
            if b.walk_to(k, pile, now, then="haul:pick", speed=HAUL_SPEED):
                hs[k] = {"stage": "to_pile", "t": now}
                want -= 1

    def _carrying(self) -> int:
        return sum(1 for h in self.build["haulers"].values() if h["stage"] == "to_site")

    def _to_pile(self) -> int:
        return sum(1 for h in self.build["haulers"].values() if h["stage"] == "to_pile")

    def _release(self, key: str, now: float) -> None:
        self.build["haulers"].pop(key, None)

    def _release_all(self, now: float) -> None:
        b = getattr(self.scene, "behaviour", None)
        for key in list(self.build["haulers"]):
            e = b.get(key) if b is not None else None
            if e is not None and getattr(e, "carry", None) == "stone":
                b.drop(key, now)                                 # not delivered: the stone stays counted in the pile
            self._release(key, now)

    def _record_placed(self, idx: int, delivered: int) -> None:
        """The history row's stones_placed IS the record of the pile shrinking (a reboot resumes from it)."""
        if self.build is not None and self.build.get("forced"):
            return                                               # the test hook writes nothing
        for h in self.history:
            if int(h.get("idx") or -1) == int(idx):
                h["stones_placed"] = int(delivered)
                break
        else:
            self.history.append({"idx": int(idx), "name": age_name(idx), "ts": None, "at": None, "raised_by": [],
                                 "stones_placed": int(delivered), "wished_by": {}})
        ab = self.block().get("age_build")
        if isinstance(ab, dict) and int(ab.get("idx") or -1) == int(idx):
            ab["delivered"] = int(delivered)                     # a forced save mid-build carries the live count
        self._dirty(force=False)

    # -- step 4: the plaque
    def _plaque(self, now: float) -> None:
        bd = self.build
        b = getattr(self.scene, "behaviour", None)
        if b is not None:
            for e in b.entities.values():
                try:
                    if e.is_on_land():
                        e.joy_until = now + 1.0
                except Exception:
                    continue
        mx, my = self._moot_xy("moot")
        self._emit({"type": "age_built", "idx": bd["idx"], "name": age_name(bd["idx"]), "x": mx, "y": my,
                    "stones_placed": bd["delivered"]})
        self._plate_pin_until = now + PLATE_PIN_S
        self._plate_cache = (-1e18, (), [])

    def _floor_for(self, idx: int) -> int:
        """The camp floor an age sets (AGES 1.2 / 2.3): tent from the Camp, hut from the Village."""
        return 2 if idx >= 3 else (1 if idx >= 1 else 0)

    def _cascade(self, now: float) -> None:
        bd = self.build
        if bd.get("forced") or now - bd["floor_t"] < FLOOR_CASCADE_S:
            return
        ld = getattr(self.scene, "land", None)
        if ld is None:
            return
        floor = self._floor_for(bd["idx"])
        try:
            camps = ld.camps()
        except Exception:
            return
        for c in camps:
            key = c.get("key")
            if key in bd["floor_done"] or int(c.get("tier") or 0) >= floor:
                continue
            p = ld.real_pip(key)
            camp = p.get("camp") if p else None
            if not isinstance(camp, dict):
                continue
            fn = getattr(ld, "camp_tier_for", None)               # W3's ladder when present (never lowers), else the floor
            try:
                want = int(fn(p, bd["idx"])) if callable(fn) else floor
            except Exception:
                want = floor
            want = max(want, floor)
            if want > int(camp.get("tier") or 0):
                camp["tier"] = want
                camp.setdefault("tiers", []).append({"tier": want, "ts": self._iso(now)})
                ld.bump_bake("camp floor")
                bd["floor_done"].append(key)
                bd["floor_t"] = now
                self._emit({"type": "camp_floor", "pip": key, "tier": want, "x": c.get("x"), "y": c.get("y"), "idx": bd["idx"]})
                self._dirty(force=True, now=now)
                return

    def _iso(self, now: float) -> Optional[str]:
        w = getattr(self.scene, "world", None)
        try:
            return w.iso(now) if w is not None else None
        except Exception:
            return None

    def _finish(self, now: float, failed: bool = False) -> None:
        bd = self.build
        if bd is None:
            return
        idx = bd["idx"]
        if failed:
            self.log("ages: %s: a step failed; the object stands finished" % age_name(idx))
        self._release_all(now)
        b = getattr(self.scene, "behaviour", None)
        if b is not None:
            try:
                b.build = None
            except Exception:
                pass
        if not bd.get("forced"):
            blk = self.block()
            blk["age_built"] = max(int(blk.get("age_built") or 0), idx)
            blk["age_build"] = None
            ld = getattr(self.scene, "land", None)
            try:
                if ld is not None:
                    ld.bump_bake("age %d" % idx)
            except Exception:
                pass
            self._dirty(force=True, now=now)
        self.builds_done += 1
        self.build = None
        self._next_build_t = now + NEXT_BUILD_GAP_S
        self._plate_cache = (-1e18, (), [])
        self.log("ages: %s stands (%d stones placed)%s" % (age_name(idx), bd["delivered"], " (test hook, nothing written)" if bd.get("forced") else ""))

    # ------------------------------------------------------------------ the drawing (live sprites the scene y-sorts)
    def building(self) -> bool:
        return self.build is not None

    def flare(self, now: float) -> bool:
        return self.build is not None and flare_on(now)

    def _progress(self, now: float) -> float:
        bd = self.build
        if bd is None or bd["t0"] is None:
            return 0.0
        el = now - bd["t0"]
        if bd["step"] in ("call", "gather", "resume"):
            return 0.0
        if bd["step"] == "plaque":
            return 1.0
        t_frac = max(0.0, min(1.0, (el - GATHER_S) / BUILD_S))
        h_frac = bd["delivered"] / float(max(1, bd["needed"]))
        return max(0.0, min(1.0, max(t_frac, h_frac)))

    def live_sprites(self, now: float, visible: Callable[[float, float], bool], sun=None) -> List[Tuple[float, np.ndarray, Tuple[float, float]]]:
        """(y, sprite, (x, y)) rows: the pile, every finished site of ages 1..age_built, the rising sites of the build
        (reveal mask quantised to <= 1 Hz). Sprites are cached composites: one blit each on the frame path."""
        out: List[Tuple[float, np.ndarray, Tuple[float, float]]] = []
        N = getattr(self.scene, "nature", None)
        if sun is None:
            try:
                sun = N.sun(now) if N is not None else (-0.62, -0.78)
            except Exception:
                sun = (-0.62, -0.78)
        built = self.age_built
        if built >= 1 or self.build is not None:
            n = self.pile()
            if n > 0:
                px, py = self.pile_xy()
                if visible(px, py):
                    out.append((py + 0.5, pile_sprite(n, sun), (px, py)))
        for idx in range(1, built + 1):
            for s in self.sites_for(idx):
                if visible(s["x"], s["y"]):
                    out.append((s["y"], site_sprite(s["obj"], sun), (s["x"], s["y"])))
        bd = self.build
        if bd is not None and bd["step"] in ("build", "plaque"):
            if now - self._reveal_t >= REVEAL_STEP_S:
                self._reveal_t = now
                self._reveal_p["cur"] = round(self._progress(now), 3)
            prog = self._reveal_p.get("cur", 0.0)
            for s in bd["sites"]:
                if visible(s["x"], s["y"]) and prog > 0.0:
                    out.append((s["y"], revealed(site_sprite(s["obj"], sun), prog), (s["x"], s["y"])))
        return out

    # ------------------------------------------------------------------ the plate (panels/world.py hooks)
    def plate_id(self, now: float) -> str:
        if self.build is not None or now < self._plate_pin_until:
            return "age:reached"
        return "age:reached" if int(now // PLATE_ALT_S) % 2 == 0 else "age:forward"

    def plate_pinned(self, now: float) -> bool:
        """Pinned during the build's plaque step and PLATE_PIN_S after; the panel adds its own hatch / stone / Moot-dwell pins."""
        return now < self._plate_pin_until or (self.build is not None and self.build.get("step") == "plaque")

    def plate_marks(self, now: float, shown: Callable[[Optional[str]], Optional[str]]) -> List[Tuple[str, str, float, float, Optional[str], str]]:
        """(id, kind, x, y, owner, text) rows for the ONE-plate rotation: the reached form (age >= 1) and the forward form
        (the keys still short for age + 1); each validated, cached 5 s."""
        p, s, d = self.counts()
        sig = (self.age, self.age_built, p, s, d, self.build is not None)
        t_built, sig_prev, cached = self._plate_cache
        if cached and sig == sig_prev and now - t_built < 5.0:
            return cached
        rows: List[Tuple[str, str, float, float, Optional[str], str]] = []
        cx, cy = self._moot_xy("cairn")
        age = self.age
        if age >= 1:
            row = None
            for h in self.history:
                if int(h.get("idx") or -1) == age:
                    row = h
            since = since_text((row or {}).get("ts"))
            names = []
            for k in (row or {}).get("raised_by") or []:
                try:
                    nm = shown(k)
                except Exception:
                    nm = None
                if nm:
                    names.append(nm)
            wished = None
            wb = (row or {}).get("wished_by") or {}
            if isinstance(wb, dict) and wb:
                slug = max(wb, key=lambda k_: len(wb[k_]))
                noun = project_noun(slug)
                wn = [n for n in (shown(k) for k in wb[slug]) if n]
                if noun and wn:
                    wished = (noun, wn)
            text = reached_text(age, since, p, names, wished)
            if text:
                rows.append(("age:reached", "age", cx, cy + 3.0, None, text))
        fwd = forward_text(age + 1, p, s, d, self.top_project())
        if fwd:
            rows.append(("age:forward", "age", cx, cy + 3.0, None, fwd))
        self._plate_cache = (now, sig, rows)
        return rows

    def stats(self) -> Dict[str, Any]:
        bd = self.build
        return {"age": self.age, "age_built": self.age_built, "gate": self.gate(), "counts": self.counts(), "pile": self.pile(),
                "persist": bool(self.persist), "checks": self.checks, "deferred": self._deferred, "turns": self.turns,
                "builds_done": self.builds_done, "hauls_done": self.hauls_done, "errors": self.errors,
                "build": None if bd is None else {"idx": bd["idx"], "step": bd["step"], "delivered": bd["delivered"],
                                                  "needed": bd["needed"], "haulers": len(bd["haulers"])}}


# ----------------------------------------------------------------------------- self-test
def _selftest(argv: Sequence[str]) -> int:   # pragma: no cover (exercised by `$PY stream/world/ages.py --self-test`)
    import shutil
    ok_all = True

    def check(cond, msg):
        nonlocal ok_all
        print("  [%s] %s" % ("ok" if cond else "FAIL", msg))
        if not cond:
            ok_all = False

    print("AGES self-test")
    # 1. ladder math
    lad, names_ = ladder()
    check(len(lad) >= 5 and lad[1] == (3, 10, 2), "ladder %r" % (lad,))
    check(age_gate(1, 0, 1) == 0 and age_gate(3, 10, 2) == 1 and age_gate(3, 16, 3) == 1, "gate: 1/0/1 -> 0, 3/10/2 -> 1, 3/16/3 -> 1")
    check(age_gate(5, 30, 5) == 2 and age_gate(10, 80, 10) == 3 and age_gate(25, 200, 25) == 4, "gate: 5/30/5 -> 2, 10/80/10 -> 3, 25/200/25 -> 4")
    check(age_gate(50, 400, 50) == 5 and rung(5) == (50, 400, 50) and rung(6) == (75, 600, 75), "Centuries: rung 5 %r, rung 6 %r, gate(50/400/50) = %d" % (rung(5), rung(6), age_gate(50, 400, 50)))
    check(age_gate(100, 9, 100) == 0 and age_gate(2, 999, 999) == 0 and age_gate(999, 999, 1) == 0, "AND of three: one key alone never ages the land")
    check(age_name(1) == "the Camp" and age_name(2) == "the Steading" and age_name(5) == "the 1st Century" and age_name(6) == "the 2nd Century", "names: %s / %s / %s / %s" % (age_name(1), age_name(2), age_name(5), age_name(6)))
    sf = shortfalls(2, 3, 16, 3)
    check(sf[0][0] == "people" and [r[0] for r in sf] == ["people", "stones", "days"], "forward 3/16/3 -> Steading shortfalls most binding first: %r" % (sf,))
    # 2. every string passes banned_copy_hits
    strings = [turn_line(1, 3, 16, 3), turn_line(2, 5, 31, 5), forward_text(2, 3, 16, 3), forward_text(2, 3, 16, 3, ("a bridge", 12)),
               forward_text(3, 5, 30, 5), gap_line(2, 4, 26, 5), gap_line(2, 3, 16, 3), gap_line(2, 5, 29, 5),
               reached_text(1, "26 Sep", 3, ["sami", "atleastonce", "lordoomer"]),
               reached_text(2, "3 Oct", 9, ["a", "b", "c", "d", "e", "f", "g", "h"], ("a bridge", ["kai", "jo"])),
               reached_text(5, "1 Jan", 60, ["x"] * 7), forward_text(5, 30, 250, 30)]
    for s_ in strings:
        print("    %r" % (s_,))
    check(all(strings), "every plate / plank string composed (none refused by the copy check)")
    check(not banned_hits([s for s in strings if s]), "banned_copy_hits over every string: %r" % (banned_hits([s for s in strings if s]),))
    check(turn_line(1, 3, 16, 3) == "the Camp · 3 people · 16 stones · 3 days", "turn line %r" % turn_line(1, 3, 16, 3))
    check(forward_text(2, 3, 16, 3) == "the Steading · 2 more people · 14 more stones · 2 more days", "forward %r" % forward_text(2, 3, 16, 3))
    check(gap_line(2, 4, 26, 5) == "1 more person and 4 stones until the Steading", "gap line %r" % gap_line(2, 4, 26, 5))
    check("and 2 others" in (reached_text(2, "3 Oct", 9, list("abcdefgh")) or ""), "`and N others` beyond 6 names")
    check(len(banned_hits(["day 3", "Longgrass is a Camp", "the build starts"])) == 3, "the checker itself catches `day 3`, `longgrass`, `build`")
    # 3. honesty helpers
    w0 = {"age": 1, "age_built": 1, "stones": [{}] * 16, "hatched_ever": 3, "days_on_air": ["a", "b", "c"], "age_history": [{"idx": 1, "stones_placed": 11}]}
    check(age_ok(w0)[0], "age_ok on 1 / 1 with 3/16/3: %r" % (age_ok(w0),))
    check(not age_ok(dict(w0, age=2))[0], "age 2 > gate 1 caught: %r" % (age_ok(dict(w0, age=2))[1],))
    check(not age_ok(w0, last_age=2)[0], "regressed age (2 -> 1) caught: %r" % (age_ok(w0, last_age=2)[1],))
    check(not age_ok(dict(w0, age_built=2))[0], "age_built > age caught: %r" % (age_ok(dict(w0, age_built=2))[1],))
    check(not age_ok(dict(w0, age_history=[{"idx": 1, "stones_placed": 17}]))[0], "stones_placed > len(stones) caught")
    # 3b. the kit composites: every site object and a pile of 11 compose to a non-empty RGBA (one blit each on the frame path)
    sun0 = (-0.62, -0.78)
    objs = sorted(set(o for rows in AGE_SITES.values() for (o, _p, _d) in rows)) + ["monument_ring:1"]
    comp_ok = True
    for o in objs:
        spr = site_sprite(o, sun0)
        comp_ok = comp_ok and spr.ndim == 3 and spr.shape[2] == 4 and bool(spr[..., 3].any())
        print("    composite %-16s %dx%d px" % (o, spr.shape[1], spr.shape[0]))
    pile11 = pile_sprite(11, sun0)
    check(comp_ok and pile11.shape[2] == 4 and pile11[..., 3].any(), "composites: %d site objects + a pile of 11 (%dx%d) are RGBA and drawn" % (len(objs), pile11.shape[1], pile11.shape[0]))
    check(revealed(pile11, 0.5)[..., 3].any() and not revealed(pile11, 0.0)[..., 3].any() and revealed(pile11, 1.0) is pile11, "reveal mask: 0 -> nothing, 0.5 -> the bottom half, 1 -> the sprite itself")
    if "--quick" in argv:
        print("AGES SELF-TEST %s (quick: no scene fixture)" % ("PASS" if ok_all else "FAIL"))
        return 0 if ok_all else 1
    # 4. the sequencer over a scene fixture in /tmp (real scene, test pips haul; the gate is real: 5 people / 30 stones / 5 days)
    run_dir = os.environ.get("RUN_DIR") or "/tmp/lg-ages-selftest"
    rp = os.path.realpath(run_dir)
    if not (rp.startswith("/tmp/") or rp.startswith("/private/tmp/")):
        print("refused: RUN_DIR must be under /tmp (got %s)" % run_dir)
        return 2
    os.environ["MODE"] = "test"
    os.environ["KL_TEST_PIPS"] = os.environ.get("KL_TEST_PIPS") or "12"
    os.environ.pop("KL_AGE_BUILD", None)
    if os.path.isdir(run_dir):
        shutil.rmtree(run_dir)
    os.makedirs(run_dir)
    from stream.state_store import epoch_to_iso
    from stream.scenes import steading as ST
    from stream.world.honesty import HonestyMonitor
    t0 = _time.time()
    names = ["age-chatter-%s" % c for c in "abcde"]
    chat_path = os.path.join(run_dir, "chat.jsonl")
    with open(chat_path, "w") as fh:
        for di in range(5):                                       # five distinct local dates, every chatter on the first
            day_t = t0 - (4 - di) * 86400.0 + 120.0
            for j, nm in enumerate(names if di == 0 else names[:2]):
                fh.write(json.dumps({"id": "age-%d-%d" % (di, j), "ts": epoch_to_iso(day_t + j), "username": nm,
                                     "content": "hello land", "type": "message"}) + "\n")
    dates, _off = local_dates(chat_path)
    check(len(dates) == 5, "local dates from chat.jsonl: %d %r" % (len(dates), sorted(dates)))
    sid = "ages-selftest-%d" % int(t0)

    def mkctx(now, frame, rnd=1, rem=120.0, hold=False):
        return ST._Ctx(now=now, frame=frame, fps=30.0, session={"id": sid, "started_ts": epoch_to_iso(t0 - 30), "ending": False},
                       micro={"canvas_seed": 4471}, preset="kick", chat_raw=[], chat=[], recent_votes=[],
                       round={"number": rnd}, round_remaining=rem, mod={"hidden_users": []}, mod_paused=False,
                       agent={"heartbeat_ts": None}, macro={"active": bool(hold)}, compositor_live={"selftest": True}, selftest=True)

    def boot(sc, now):
        tb = _time.perf_counter()
        while not (sc.booted or sc.refused) and _time.perf_counter() - tb < 60.0:
            sc.frame(mkctx(now, 0), size)
            _time.sleep(0.01)
        return (_time.perf_counter() - tb) * 1000

    size = (1280, 720)
    scene = ST.SteadingScene(run_dir=run_dir, seed=11, sleep_after_s=1200.0)
    now = t0
    boot_ms = boot(scene, now)
    check(scene.booted, "scene booted in %.0f ms (refused %r), %d entities" % (boot_ms, scene.refused, len(scene.behaviour.entities)))
    if not scene.booted:
        return 1
    # the world file gets the age fields (so the director persists) and 30 real stones by the five chatters
    wb = scene.world.data["world"]
    for nm in names:
        check(scene.world.pip(nm) is not None, "pip row for %s exists after recompute" % nm)
    for i in range(30):
        scene.land.stack(names[i % 5], now - 3600.0)
    wb.update({"age": 0, "age_built": 0, "age_history": [], "age_build": None})
    scene.world.save(now, force=True)
    d = getattr(scene, "ages", None)
    check(d is not None, "the scene made its AgeDirector at boot (steading hook)")
    if d is None:
        d = AgeDirector(scene)
        scene.ages = d
    d.persist = None
    p_, s_, d_ = d.counts()
    check((p_, s_, d_) == (5, 30, 5), "counts people/stones/days = %r (hatched_ever excludes the %d test pips)" % ((p_, s_, d_), scene.test_pips))
    check(d.pile() == 25, "pile = 30 - 5 - 0 = %d" % d.pile())
    check(d.block() is wb and d.persist is True, "director persists into the world block (fields present)")
    mon = HonestyMonitor(scene, enforce=True, log=lambda m: print("    honesty: " + m))
    frames = [0]
    hon_bad = [0]
    ms: List[float] = []
    ev_types: Set[str] = set()
    plank: List[str] = []

    def run(seconds, dt=0.1, rnd=1, rem=120.0):
        nonlocal now
        n = int(round(seconds / dt))
        for _ in range(n):
            now += dt
            ctx = mkctx(now, frames[0], rnd, rem)
            t_ = _time.perf_counter()
            scene.frame(ctx, size)
            ms.append((_time.perf_counter() - t_) * 1000)
            for ev in scene.events:
                ev_types.add(ev.get("type"))
                if ev.get("type") == "age" and ev.get("plank"):
                    plank.append(ev["plank"])
            rep = mon.check(ctx, now)
            if rep.violations:
                hon_bad[0] += 1
            frames[0] += 1

    run(1.0)
    # 4a. the gate fires at a round close only, never inside a hold / the last 30 s / a raising
    check(d.age_check(now, mkctx(now, 0, hold=True)) is None and d.age == 0, "age_check refused inside a macro / ship hold")
    check(d.age_check(now, mkctx(now, 0, rem=20.0)) is None and d.age == 0, "age_check refused in the last 30 s of a round")
    scene.keepers = ST._Ctx(raising={"name": "the well"})
    check(d.age_check(now, mkctx(now, 0)) is None and d.age == 0, "age_check refused while a keeper raising is in flight")
    scene.keepers = None
    run(1.0)
    check(d.age == 0 and d.build is None, "no gate check between round closes: age stays 0 with 5/30/5 met")
    turned = d.round_closed(now, mkctx(now, 0, rnd=2))
    check(turned == 2 and d.age == 2 and d.age_built == 0, "round close -> age 0 -> 2 (two rungs earned at once), age_built 0")
    check(len(wb["age_history"]) == 2 and wb["age_history"][0]["idx"] == 1 and wb["age_history"][1]["idx"] == 2, "two history rows: %r" % ([(h["idx"], h["name"], h["at"]) for h in wb["age_history"]],))
    check(set(wb["age_history"][1]["raised_by"]) == set(names), "raised_by names every real settler on the land: %r" % (wb["age_history"][1]["raised_by"],))
    saved = json.load(open(os.path.join(run_dir, "world.json")))["world"]
    check(saved.get("age") == 2 and len(saved.get("age_history") or []) == 2, "forced save in the same frame: world.json age %r" % (saved.get("age"),))
    # 4b. the sequencer: call -> gather -> build (24 hauls) -> plaque; a reboot mid-build resumes
    run(3.5)
    check(d.build is not None and d.build["idx"] == 1 and d.build["needed"] == 24, "the Camp raising started: %r" % (d.stats()["build"],))
    run(CALL_S + 2.0)
    check(d.build["step"] == "gather", "step gather at %.0f s" % (now - d.build["t0"]))
    gathering = sum(1 for e in scene.behaviour.entities.values() if e.state == "walking" and e.then == "gather")
    print("    %d settlers walking with then=gather; camera mode %s zoom %.2f target %.2f" % (gathering, scene.camera.mode, scene.camera.zoom, scene.camera.target_zoom))
    check(scene.camera.mode == "EVENT" and scene.camera.target_zoom == CAM_ZOOM, "camera EVENT at the Moot heading to 0.75x (mode %s, target %.2f)" % (scene.camera.mode, scene.camera.target_zoom))
    run(GATHER_S)
    check(d.build["step"] == "build", "step build at %.0f s" % (now - d.build["t0"]))
    run(20.0)
    st = d.stats()["build"]
    print("    mid-build: %r pile %d placed %d" % (st, d.pile(), d.placed_total()))
    check(st["delivered"] > 0 and st["haulers"] > 0, "stones are being hauled (%d delivered, %d haulers)" % (st["delivered"], st["haulers"]))
    check(d.pile() == 30 - 5 - st["delivered"], "the pile shrinks by exactly the delivered count (pile %d)" % d.pile())
    carrying = [e.key for e in scene.behaviour.entities.values() if getattr(e, "carry", None) == "stone"]
    print("    carrying now: %r" % (carrying,))
    spr_rows = d.live_sprites(now, lambda x, y: True)
    check(any(r[1].shape[0] > 8 for r in spr_rows) and len(spr_rows) >= 2, "live sprites: pile + rising site (%d rows)" % len(spr_rows))
    # reboot mid-build: save, new scene on the same run dir, the director resumes from stones_placed
    scene.save_now(now)
    delivered_at_reboot = st["delivered"]
    scene2 = ST.SteadingScene(run_dir=run_dir, seed=11, sleep_after_s=1200.0)
    boot(scene2, now)
    check(scene2.booted, "second scene booted (%r)" % (scene2.refused,))
    d2 = getattr(scene2, "ages", None)
    check(d2 is not None and d2.age == 2 and d2.age_built == 0, "age survives the reboot (age %r, built %r)" % (getattr(d2, "age", None), getattr(d2, "age_built", None)))
    check(d2 is not None and d2.build is not None and d2.build.get("resumed") and d2.build["delivered"] == delivered_at_reboot,
          "the build resumed mid-way (%r delivered of %r) instead of re-earning" % (d2.build["delivered"] if (d2 and d2.build) else None, delivered_at_reboot))
    scene, d = scene2, d2
    mon = HonestyMonitor(scene, enforce=True, log=lambda m: print("    honesty: " + m))
    ms = []
    run(BUILD_MAX_S + 12.0)
    check((d.build is None or d.build["idx"] == 2) and d.age_built == 1 and d.turns == 0,
          "the Camp stands: age_built 1 (turns this director 0: nothing re-earned); %r" % (d.stats(),))
    wb = scene.world.data["world"]
    h1 = wb["age_history"][0]
    placed1 = int(h1.get("stones_placed") or 0)
    print("    history[0] %r; pile %d; hauls done %d" % (h1, d.pile(), d.hauls_done))
    check(0 < placed1 <= 24 and d.pile() == 30 - 5 - d.placed_total(), "stones_placed %d recorded; pile = 30 - 5 - placed = %d" % (placed1, d.pile()))
    check(scene.land.stock == 30, "no stone record was added or removed by the hauls (len(stones) %d)" % scene.land.stock)
    # the second age plays back to back
    run(NEXT_BUILD_GAP_S + 2.0)
    check(d.build is not None and d.build["idx"] == 2, "the Steading raising follows (%r)" % (d.stats()["build"],))
    run(GATHER_S + BUILD_MAX_S + PLAQUE_S + 3.0)
    check(d.build is None and d.age_built == 2 and d.age == 2, "the Steading stands: age_built 2 == age 2")
    check("age" in ev_types and "age_built" in ev_types and "age_haul" in ev_types and "age_cam" in ev_types, "events seen: %r" % (sorted(t for t in ev_types if t and str(t).startswith("age")),))
    check(bool(plank) and not banned_hits(plank), "plank lines at the turns: %r" % (sorted(set(plank)),))
    marks = d.plate_marks(now, lambda k: k.replace("age-chatter-", "") if k else None)
    for m in marks:
        print("    plate %s: %r" % (m[0], m[5]))
    check(len(marks) == 2 and marks[0][0] == "age:reached" and marks[1][0] == "age:forward" and not banned_hits([m[5] for m in marks]), "both plate forms composed and clean")
    check(marks[1][5].startswith("the Village · 5 more people · 50 more stones · 5 more days"), "forward form most binding first: %r" % marks[1][5])
    # 4c. never regress: !banish drops a count below the rung; age stays, the honesty rule reads the history
    scene.world.banish(names[4], now)
    scene.land.purge_owner(names[4])
    p2, s2, d2_ = d.counts()
    print("    after banish: counts %r gate %d age %d" % ((p2, s2, d2_), d.gate(), d.age))
    check(d.age == 2 and d.age_built == 2, "banish never lowers age (age %d, built %d) though the gate now reads %d" % (d.age, d.age_built, d.gate()))
    check(d.round_closed(now, mkctx(now, 0, rnd=3)) is None and d.age == 2, "a round close after the banish changes nothing")
    probs = age_violations(scene, None)
    check(not probs, "honesty `age` after the banish: the history row's counts at reach stand (%r)" % (probs,))
    arr = np.array(ms) if ms else np.zeros(1)
    print("    frame ms over the resumed Camp raising + the Steading: avg %.2f p95 %.2f max %.2f (%d frames, dt 0.1 s sim)" % (arr.mean(), np.percentile(arr, 95), arr.max(), len(arr)))
    print("    honesty frames with violations: %d (of %d)" % (hon_bad[0], frames[0]))
    check(hon_bad[0] == 0, "honesty clean through both raisings (away haulers carry stones under the land's word)")
    # 5. memory-only path (schema 2 without age fields): nothing written, logged once
    run_dir2 = run_dir + "-mem"
    if os.path.isdir(run_dir2):
        shutil.rmtree(run_dir2)
    os.makedirs(run_dir2)
    shutil.copy(chat_path, os.path.join(run_dir2, "chat.jsonl"))
    logs: List[str] = []
    scene3 = ST.SteadingScene(run_dir=run_dir2, seed=11, sleep_after_s=1200.0, log=logs.append)
    boot(scene3, now)
    d3 = getattr(scene3, "ages", None)
    from stream.world import state as _ST3
    if int(getattr(_ST3, "SCHEMA", 2) or 2) >= 3:                 # the integrated tree (W3): a schema-2 file is migrated at load, the director persists
        check(d3 is not None and d3.persist is True and "age" in scene3.world.data["world"] and int(scene3.world.data["world"].get("age") or 0) >= 0,
              "schema 3 tree: the schema-2 copy is migrated at load and the director writes the world block (age %r)" % (scene3.world.data["world"].get("age"),))
        check(not any("stays in memory" in l_ for l_ in logs), "no memory-only log on a schema 3 tree: %r" % ([l_ for l_ in logs if "memory" in l_],))
    else:
        check(d3 is not None and d3.persist is False and "age" not in scene3.world.data["world"], "schema 2 file without age fields: memory only, nothing written")
        check(sum(1 for l_ in logs if "stays in memory" in l_) == 1, "logged once: %r" % ([l_ for l_ in logs if "memory" in l_],))
    # clean-up: frame PNGs and .npy under the run dirs (report/ kept when present)
    removed = 0
    for rd in (run_dir, run_dir2):
        for root, _dirs, files in os.walk(rd):
            for f in files:
                if f.endswith(".npy") or (f.startswith("frame_") and f.endswith(".png")):
                    os.remove(os.path.join(root, f))
                    removed += 1
    print("    cleanup: %d frame PNG / .npy removed" % removed)
    print("AGES SELF-TEST %s" % ("PASS" if ok_all else "FAIL"))
    return 0 if ok_all else 1


def _eprime(argv: Sequence[str]) -> int:   # pragma: no cover (`$PY stream/world/ages.py --eprime`)
    """E' (AGES 6): a 90 s age raising with 24 hauls at 0.75x and KL_TEST_PIPS settlers: scene avg < 13 ms, no frame
    > 24 ms (recorded honestly). Writes report/camp_build_320x180.png and report/camp_build_720p.png under RUN_DIR."""
    import shutil
    from PIL import Image
    from stream.state_store import epoch_to_iso
    from stream.scenes import steading as ST
    from stream.world.honesty import HonestyMonitor
    run_dir = os.environ.get("RUN_DIR") or "/tmp/lg-ages-eprime"
    rp = os.path.realpath(run_dir)
    if not (rp.startswith("/tmp/") or rp.startswith("/private/tmp/")):
        print("refused: RUN_DIR must be under /tmp")
        return 2
    n_pips = int(os.environ.get("KL_TEST_PIPS") or 60)
    warm_s = float(os.environ.get("KL_EPRIME_WARM_S") or 60.0)   # the sheet worker renders 60 x 23 frames first (~45 s)
    base_s = float(os.environ.get("KL_EPRIME_BASE_S") or 20.0)   # a same-box baseline window before the raising starts
    os.environ.update({"MODE": "test", "KL_TEST_PIPS": str(n_pips), "KL_FORCE_ZOOM": "0.75", "KL_AGE_BUILD": "1",
                       "KL_AGE_BUILD_AT_S": "%.0f" % (warm_s + base_s)})
    if os.path.isdir(run_dir):
        shutil.rmtree(run_dir)
    os.makedirs(os.path.join(run_dir, "report"))
    t0 = _time.time()
    names = ["eprime-%s" % c for c in "abc"]
    with open(os.path.join(run_dir, "chat.jsonl"), "w") as fh:
        for di in range(3):
            for j, nm in enumerate(names):
                fh.write(json.dumps({"id": "e-%d-%d" % (di, j), "ts": epoch_to_iso(t0 - (2 - di) * 86400.0 + j), "username": nm,
                                     "content": "hello", "type": "message"}) + "\n")
    sid = "eprime-%d" % int(t0)

    def mkctx(now, frame):
        return ST._Ctx(now=now, frame=frame, fps=30.0, session={"id": sid, "started_ts": epoch_to_iso(t0 - 30), "ending": False},
                       micro={"canvas_seed": 4471}, preset="kick", chat_raw=[], chat=[], recent_votes=[], round={"number": 1},
                       round_remaining=120.0, mod={"hidden_users": []}, mod_paused=False, agent={"heartbeat_ts": None},
                       macro={"active": False}, compositor_live={"selftest": True}, selftest=True)

    size = (1280, 720)
    scene = ST.SteadingScene(run_dir=run_dir, seed=11, sleep_after_s=1200.0)
    now = t0
    tb = _time.perf_counter()
    while not (scene.booted or scene.refused) and _time.perf_counter() - tb < 60.0:
        scene.frame(mkctx(now, 0), size)
        _time.sleep(0.01)
    if not scene.booted:
        print("scene refused: %r" % (scene.refused,))
        return 1
    for i in range(30):
        scene.land.stack(names[i % 3], now - 3600.0)              # 30 stones by real chatters: the pile holds 25
    d = getattr(scene, "ages", None)
    if d is None:
        print("no director on the scene (steading hook missing)")
        return 1
    mon = HonestyMonitor(scene, enforce=True, log=lambda m: print("    honesty: " + m))
    dt = 1.0 / 30.0
    frames = 0
    # the director's own cost on the frame path (tick + live_sprites), timed through wrappers
    cost = {"tick": 0.0, "sprites": 0.0, "n": 0}
    _tick, _live = d.tick, d.live_sprites

    def tick_timed(*a, **k):
        t_ = _time.perf_counter()
        try:
            return _tick(*a, **k)
        finally:
            cost["tick"] += _time.perf_counter() - t_
            cost["n"] += 1

    def live_timed(*a, **k):
        t_ = _time.perf_counter()
        try:
            return _live(*a, **k)
        finally:
            cost["sprites"] += _time.perf_counter() - t_
    d.tick, d.live_sprites = tick_timed, live_timed
    while now - t0 < warm_s:                                      # the sheets land on the worker (untimed)
        now += dt
        scene.frame(mkctx(now, frames), size)
        frames += 1
    pend = scene.worker.pending()
    base: List[float] = []
    while now - t0 < warm_s + base_s and d.build is None:         # the same box, the same crowd, no raising: the baseline
        now += dt
        ctx = mkctx(now, frames)
        t_ = _time.perf_counter()
        scene.frame(ctx, size)
        base.append((_time.perf_counter() - t_) * 1000)
        mon.check(ctx, now)
        frames += 1
    cost0 = dict(cost)
    ms: List[float] = []
    shots: List[Tuple[float, Image.Image]] = []
    hon_bad = 0
    t_build0 = now
    total = GATHER_S + BUILD_MAX_S + PLAQUE_S + 2.0
    next_shot = 0.0
    while now - t_build0 < total and (d.build is not None or now - t_build0 < 8.0):
        now += dt
        ctx = mkctx(now, frames)
        t_ = _time.perf_counter()
        img = scene.frame(ctx, size)
        ms.append((_time.perf_counter() - t_) * 1000)
        rep = mon.check(ctx, now)
        if rep.violations:
            hon_bad += 1
        if now - t_build0 >= next_shot:
            shots.append((now - t_build0, img.convert("RGB")))
            next_shot += total / 8.0
        frames += 1
    arr = np.array(ms)
    barr = np.array(base) if base else np.zeros(1)
    over = int((arr > 24.0).sum())
    nb = max(1, len(arr))
    print("E' scene frames %d at 0.75x with %d test pips: avg %.2f ms, p95 %.2f, max %.2f, frames > 24 ms: %d; honesty bad frames %d; director %r" % (
        len(arr), n_pips, arr.mean(), np.percentile(arr, 95), arr.max(), over, hon_bad, d.stats()))
    print("   baseline (same box, same crowd, no raising, %d frames after a %.0f s warm-up; worker pending at the start %d): avg %.2f ms, p95 %.2f, max %.2f, frames > 24 ms: %d" % (
        len(barr), warm_s, pend, barr.mean(), np.percentile(barr, 95), barr.max(), int((barr > 24.0).sum())))
    print("   director cost during the raising: tick %.3f ms/frame, live_sprites %.3f ms/frame (%d frames)" % (
        (cost["tick"] - cost0["tick"]) * 1000.0 / nb, (cost["sprites"] - cost0["sprites"]) * 1000.0 / nb, nb))
    print("   sections (last frame): %r; degrade %r; hauls %d; entities %d" % (scene.sections, scene.degrade.get("level"), d.hauls_done, len(scene.behaviour.entities)))
    if shots:
        thumbs = [im.resize((320, 180), Image.Resampling.BOX) for _t, im in shots[:8]]
        cols = 4
        rows = (len(thumbs) + cols - 1) // cols
        grid = Image.new("RGB", (320 * cols, 180 * rows), (20, 20, 20))
        for i, th in enumerate(thumbs):
            grid.paste(th, ((i % cols) * 320, (i // cols) * 180))
        grid.save(os.path.join(run_dir, "report", "camp_build_320x180.png"))
        picks = [shots[i] for i in (0, min(3, len(shots) - 1), min(5, len(shots) - 1), len(shots) - 1)]
        grid2 = Image.new("RGB", (1280 * 2, 720 * 2), (20, 20, 20))
        for i, (_t, im) in enumerate(picks):
            grid2.paste(im, ((i % 2) * 1280, (i // 2) * 720))
        grid2.save(os.path.join(run_dir, "report", "camp_build_720p.png"))
        print("   report: %s (frames at %s s)" % (os.path.join(run_dir, "report"), ", ".join("%.0f" % t for t, _ in shots)))
    ok = arr.mean() < 13.0 and over == 0 and hon_bad == 0 and d.hauls_done > 0
    print("E' %s (avg < 13: %s, no frame > 24: %s, honesty 0: %s, hauls > 0: %s)" % (
        "PASS" if ok else "FAIL", arr.mean() < 13.0, over == 0, hon_bad == 0, d.hauls_done > 0))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        sys.exit(_selftest(sys.argv[1:]))
    if "--eprime" in sys.argv[1:]:
        sys.exit(_eprime(sys.argv[1:]))
    print(__doc__)
