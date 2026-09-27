"""stream/world/ledger.py - the personal ledger: the return beat, the nightly board, flower drifts (IDLEWORLD.md 1.4, 1.5,
1.7, 3.2 return rows, 5.1; AGES.md 1.1 return, 1.5; build row 8 = W5).

    compose_return(pip, world, now, away_s=None, land=None) -> '@kai is back · the Camp rose · your tent is a hut · 4 walked in'
                                                              ('@kai is back' on an empty diff; None under 20 min away)
    snapshot(world, key, now, land=None)                   -> the last_told dict {ts, age, camp_tier, tree_stage, flower_stage,
                                                              placed, people, stones}, every value a len() or a stage index
    nightly_board(world, now, land=None)                   -> 'yesterday · @sami stacked 3 · 1 walked in · @kai's tent rose ·
                                                              a lantern stands' from timestamps; None when nothing happened
    stats_extra(pip, world) / stats_line(pip, world, ...)  -> ['1 stands'] for !stats when placed rows exist
    camp_plate_first_here(pip) / camp_plate_suffix(pip)    -> 'first here 26 Sep' / ' · first here 26 Sep'
    flower_drift_stage(mark, now) -> 1 | 3 | 5 blooms at 0 / 2 / 7 real days; drift_clumps(x, y, variant, blooms) -> offsets
    names_clause(names, cap=6)   -> '@a @b @c @d @e @f and 14 others'
    on_return(scene, ev, key, now) / on_hatch(scene, key, now) / frame_hook(scene, ev, now) / board_plate(scene, now)
                                  -> the scene / panel hooks' whole logic (the hooks are one call each)
    $PY stream/world/ledger.py --self-test          (pure fixtures, < 1 s)
    MODE=test RUN_DIR=/tmp/lg-w5-scene $PY stream/world/ledger.py --scene-test   (a real scene: return line, 8-day drift)

Rules (OPENWORLD 12, IDLEWORLD 5.1): every clause is a diff of two len()s or two stage indices over REAL records; every
verb is sign-carvable and nothing is negative (`rose`, `stands`, `spread`, `walked in`, `went up`, `is back`, `stacked`);
never `day N`, never a clock, never a promise; every composed line is checked with `compositor.Compositor.banned_copy_hits`
at write time and a failed line falls back to the bare `@name is back` (or nothing). Chat text never enters a line: the
only nouns are the registry's closed-table nouns carried on `placed[]` rows. `last_told` is written only when the file
already carries the field or state.SCHEMA >= 3 (W3 owns the schema bump); before that the return line still tells what
exists (an empty diff: `@kai is back`). Absence is never punished: an away person's line says what GREW, never what they
missed.

Schema-3 fields (AGES 5, IDLEWORLD 6.1) are read with .get defaults so this runs on a schema-2 file: world.age,
age_history[], placed[], pip.last_told, camp.tiers[]. Hot-reloadable: nothing from behaviour / honesty / steading /
panels is imported at module level; land, layout, compositor and the scene are imported lazily inside functions.
"""
from __future__ import annotations

import importlib
import math
import os
import sys
import time as _time
from typing import Any, Dict, List, Optional, Sequence, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stream.state_store import iso_to_epoch, epoch_to_iso  # noqa: E402

AWAY_MIN_S = 20 * 60.0                      # under this gap nothing is said (today's rule, IDLEWORLD 1.4)
MAX_CLAUSES = 3                             # the return line: `@kai is back` + up to three diff clauses
BOARD_MAX_CLAUSES = 4                       # the nightly board: `yesterday` + up to four clauses
BOARD_S = 600.0                             # the board rides the one-plate rotation this long after day_turn
RETURN_LINE_S = 6.0                         # the plank line (PRIO_YOU) shows this long
MUTTER_AFTER_S = 2.5                        # the own-word mutter lands this long after the return hop
NAMES_CAP = 6                               # `@a @b @c @d @e @f and 14 others`
DAY_S = 86400.0
LONG_AWAY_S = 7 * DAY_S                     # three bells + everyone looks (audio / behaviour read ev["away_s"]; here for callers)
FLOWER_STAGES = ((0.0, 1), (2.0, 3), (7.0, 5))     # (real days since planting, blooms drawn); len(marks) unchanged
TREE_STAGES = ((0.0, "sapling"), (3.0, "young"), (14.0, "canopy"))   # mirrors land.TREE_STAGES (read lazily when a Land is given)
CAMP_RISE = {1: "your camp is a tent", 2: "your tent is a hut", 3: "your hut has a chimney"}   # by the tier reached
CAMP_WORDS = ("camp", "tent", "hut", "hut")
TREE_RISE = {1: "your tree is young", 2: "your tree has a canopy"}
FLOWER_RISE = "your flowers spread"

# every clause form, with sample numbers, for the banned-copy fixture (IDLEWORLD 1.4: `rose`, `stands`, `spread`,
# `walked in`, `went up`, `is back`; never `built`, `day N`, `awake`)
CLAUSE_FORMS = ("@kai is back", "the Camp rose", "the Camp and the Steading rose", "the Camp, the Steading and 1 more rose",
                "your camp is a tent", "your tent is a hut", "your hut has a chimney", "your tree is young",
                "your tree has a canopy", "your flowers spread", "your lantern stands", "the castle stands", "4 walked in",
                "1 walked in", "9 stones went up", "1 stone went up", "yesterday", "@sami stacked 3", "@sami @jo stacked 5",
                "@kai's tent rose", "@kai's hut rose", "@kai's and 2 others' camps rose", "a lantern stands", "2 stand",
                "1 stands", "3 stand", "first here 26 Sep", "@a @b @c @d @e @f and 14 others")


# ----------------------------------------------------------------------------- small helpers
def _wd(world) -> Dict[str, Any]:
    """The world block of a WorldState or a raw world.json dict."""
    data = getattr(world, "data", None)
    if isinstance(data, dict):
        return data.get("world") or {}
    if isinstance(world, dict):
        return world.get("world") or {}
    return {}


def _pips(world) -> Dict[str, Dict]:
    data = getattr(world, "data", None)
    if isinstance(data, dict):
        return data.get("pips") or {}
    if isinstance(world, dict):
        return world.get("pips") or {}
    return {}


def _pip(world, key: Optional[str]) -> Optional[Dict]:
    if not key:
        return None
    return _pips(world).get(str(key).lower())


def _key_of(pip: Dict, world) -> str:
    for kk, pp in _pips(world).items():
        if pp is pip:
            return kk
    return str((pip or {}).get("name") or "").lower()


def _epoch(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return iso_to_epoch(str(v))
    except Exception:
        return None


def _people(world) -> int:
    """hatched_ever as a len() over real hatched pips (the WorldState property when there is one)."""
    he = getattr(world, "hatched_ever", None)
    if isinstance(he, int):
        return he
    try:
        return sum(1 for p in _pips(world).values() if not p.get("_test") and p.get("state") not in ("seed", "hatching"))
    except Exception:
        return int(_wd(world).get("hatched_ever") or 0)


def _stones(world) -> List[Dict]:
    return [s for s in (_wd(world).get("stones") or []) if isinstance(s, dict)]


def _placed(world) -> List[Dict]:
    return [r for r in (_wd(world).get("placed") or []) if isinstance(r, dict)]


def _age_history(world) -> List[Dict]:
    return [r for r in (_wd(world).get("age_history") or []) if isinstance(r, dict)]


def _age(world) -> int:
    try:
        return int(_wd(world).get("age") or 0)
    except Exception:
        return 0


def shown_name(pip: Optional[Dict]) -> Optional[str]:
    """The @-less display name (already through the name filter at ensure_pip) or `builder #N`; None for no row."""
    if not isinstance(pip, dict):
        return None
    nm = pip.get("display_name")
    if nm:
        return str(nm)
    n = pip.get("n")
    return "builder #%s" % (n if n is not None else "?")


def banned_hits(strings: Sequence[str]) -> List[str]:
    """compositor.Compositor.banned_copy_hits imported lazily (a missing import fails closed: everything is a hit)."""
    try:
        comp = importlib.import_module("stream.compositor")
        return list(comp.Compositor.banned_copy_hits(list(strings)))
    except Exception:
        return ["<compositor unavailable: %s>" % s for s in strings]


def clean(line: Optional[str]) -> bool:
    """True when the composed line passes the owner's copy gate (whole-token banned words, `day N`, versions, clocks)."""
    if not line:
        return False
    return not banned_hits([line])


def plural(n: int, one: str, many: Optional[str] = None) -> str:
    return "%d %s" % (n, one if n == 1 else (many if many is not None else one + "s"))


def names_clause(names: Sequence[str], cap: int = NAMES_CAP, prefix: str = "", max_w: Optional[int] = None,
                 face: str = "HN Medium", size: int = 22, pad: int = 24) -> str:
    """`@a @b @c` or, above `cap`, `@a @b @c @d @e @f and 14 others` (IDLEWORLD 1.4 founders form). With `max_w` (the
    plate's PLATE_MAX_W) the shown names shrink below `cap` until `prefix + clause` fits at `face`/`size` (+ the chip's
    padding); the count in `and N others` is always len(names) - shown, a len()."""
    names = [str(n) for n in names if n]

    def form(k: int) -> str:
        if k >= len(names):
            return " ".join("@" + n for n in names)
        return "%s and %d others" % (" ".join("@" + n for n in names[:k]), len(names) - k)

    k = min(cap, len(names))
    if max_w is None:
        return form(k)
    try:
        Lmod = importlib.import_module("stream.layout")
        width = lambda s: int(Lmod.text_width(face, size, s)) + pad     # noqa: E731
    except Exception:
        return form(k)
    while k > 1 and width(prefix + form(k)) > int(max_w):
        k -= 1
    return form(k)


def date_word(t: Optional[float]) -> str:
    """`26 Sep` in local time (a date, never `day N`); '' when unknown."""
    if t is None:
        return ""
    try:
        lt = _time.localtime(float(t))
        return "%d %s" % (lt.tm_mday, _time.strftime("%b", lt))
    except Exception:
        return ""


def local_date(t: float) -> str:
    return _time.strftime("%Y-%m-%d", _time.localtime(float(t)))


# ----------------------------------------------------------------------------- stages by real days
def _stage_by_days(stages, age_s: Optional[float]):
    if age_s is None:
        return 0, stages[0][1]
    days = max(0.0, float(age_s)) / DAY_S
    idx = 0
    for i, (d, _v) in enumerate(stages):
        if days >= d:
            idx = i
    return idx, stages[idx][1]


def flower_drift_stage(mark: Dict, now: float) -> int:
    """Blooms drawn for a flower mark: 1 at planting, 3 at real day 2, a 5-bloom drift at real day 7 (IDLEWORLD 1.1).
    No new record, len(marks) unchanged, owner unchanged: the land grows round the person's one record."""
    t0 = _epoch((mark or {}).get("ts"))
    age = None if t0 is None else max(0.0, float(now) - t0)
    return int(_stage_by_days(FLOWER_STAGES, age)[1])


def flower_stage_index(mark: Dict, now: float) -> int:
    """0 / 1 / 2 for the return diff (`your flowers spread` when it rose)."""
    t0 = _epoch((mark or {}).get("ts"))
    age = None if t0 is None else max(0.0, float(now) - t0)
    return int(_stage_by_days(FLOWER_STAGES, age)[0])


def tree_stage_index(mark: Dict, now: float, land=None) -> int:
    """The land's own tree_stage when a Land is given (Orchard 1.5x, watering); the plain real-days stage otherwise."""
    if land is not None:
        try:
            orchard = False
            places = getattr(getattr(land, "terrain", None), "places", None)
            if isinstance(places, dict) and places.get("orchard"):
                o = places["orchard"]
                orchard = math.hypot(float(mark.get("x", 0)) - o["x"], float(mark.get("y", 0)) - o["y"]) <= float(o.get("radius") or 0)
            return int(land.tree_stage(mark, now, orchard)[0])
        except Exception:
            pass
    t0 = _epoch((mark or {}).get("ts"))
    age = None if t0 is None else max(0.0, float(now) - t0) + float(((mark or {}).get("extra") or {}).get("watered_s") or 0.0)
    return int(_stage_by_days(TREE_STAGES, age)[0])


def drift_clumps(x: int, y: int, variant: int, blooms: int) -> List[Tuple[float, float, int]]:
    """(dx, dy, variant) cell offsets for the clumps of a drift round the mark cell: one clump at the mark for 1 bloom,
    3 / 5 along a short curve inside the mark's repaint region (steading._mark_regions: x-5..x+6, y-5..y+2 cells; a
    props.flowers clump is 22 x 18 px = 5.5 x 4.5 cells at 1x, so |dx| <= 2.2 and -0.5 <= dy <= 0.5 keep every pixel in
    the region). Deterministic from the cell so a repaint never moves a bloom."""
    n = 5 if blooms >= 5 else (3 if blooms >= 3 else 1)
    out: List[Tuple[float, float, int]] = [(0.0, 0.0, int(variant))]
    if n == 1:
        return out
    h = (int(x) * 73856093) ^ (int(y) * 19349663)
    flip = 1.0 if (h >> 4) & 1 else -1.0
    bow = 0.35 + ((h >> 8) % 100) / 100.0 * 0.15                     # the curve's sag (cells)
    span = 2.2 if n == 5 else 1.4
    for i in range(n - 1):
        dx = -span + 2.0 * span * i / float(n - 2)                    # -span .. +span along the curve, both sides of the mark
        if abs(dx) < 0.6:                                             # never on the mark's own clump
            dx = 0.6 * (1.0 if dx >= 0 else -1.0)
        dy = flip * bow * (1.0 - (dx / span) ** 2) - 0.25             # a gentle bow above / below the row
        dy = max(-0.5, min(0.5, dy))
        v = (int(variant) + 2 + (i % 2)) % 5 if (h >> (12 + i)) & 1 else int(variant)   # a second colour in some clumps
        out.append((round(dx, 2), round(dy, 2), v))
    return out


# ----------------------------------------------------------------------------- the personal snapshot (last_told)
def own_camp_tier(pip: Dict, world=None, land=None) -> int:
    """The camp tier shown: W3's camp_tier_for(p, age) when the land has it, else the stored camp.tier; -1 without a camp."""
    camp = (pip or {}).get("camp")
    if not isinstance(camp, dict):
        return -1
    fn = getattr(land, "camp_tier_for", None) if land is not None else None
    if callable(fn):
        try:
            return int(fn(pip, _age(world)))
        except Exception:
            pass
    try:
        return int(camp.get("tier") or 0)
    except Exception:
        return 0


def own_marks(world, key: str, typ: str) -> List[Dict]:
    k = str(key or "").lower()
    return [m for m in (_wd(world).get("marks") or []) if isinstance(m, dict) and str(m.get("type") or "") == typ
            and str(m.get("owner") or "").lower() == k]


def own_placed(world, key: str) -> List[Dict]:
    """placed[] rows this person owns or asked for (IDLEWORLD 6.1 derived `wishes_granted`)."""
    k = str(key or "").lower()
    out = []
    for r in _placed(world):
        if str(r.get("owner") or "").lower() == k or k in [str(a).lower() for a in (r.get("askers") or [])]:
            out.append(r)
    return out


def snapshot(world, key: str, now: float, land=None) -> Dict[str, Any]:
    """The last_told dict to store after telling (IDLEWORLD 1.4 / 6.1): every value a len() or a stage index."""
    p = _pip(world, key) or {}
    trees = own_marks(world, key, "tree")
    flowers = own_marks(world, key, "flower")
    return {
        "ts": epoch_to_iso(float(now)),
        "age": _age(world),
        "camp_tier": own_camp_tier(p, world, land),
        "tree_stage": max([tree_stage_index(m, now, land) for m in trees] or [-1]),
        "flower_stage": max([flower_stage_index(m, now) for m in flowers] or [-1]),
        "placed": len(own_placed(world, key)),
        "people": _people(world),
        "stones": len(_stones(world)),
    }


def may_write_last_told(world) -> bool:
    """W3 owns schema 3: the field is written only when the file already carries it or state.SCHEMA >= 3."""
    try:
        st = importlib.import_module("stream.world.state")
        if int(getattr(st, "SCHEMA", 2)) >= 3:
            return True
    except Exception:
        pass
    try:
        if int(getattr(world, "schema", 0) or 0) >= 3:
            return True
    except Exception:
        pass
    try:
        return any("last_told" in p for p in _pips(world).values())
    except Exception:
        return False


# ----------------------------------------------------------------------------- the return line
def placed_noun(row: Dict) -> Optional[str]:
    """The closed-table noun of a placed row (registry NOUNS when present); None when it is not a word we may draw."""
    noun = row.get("noun")
    if not noun:
        rec = row.get("recipe")
        try:
            reg = importlib.import_module("stream.world.registry")
            table = getattr(reg, "NOUNS", None)
            if isinstance(table, dict) and rec in table:
                v = table[rec]
                noun = v.get("noun") if isinstance(v, dict) else (v if isinstance(v, str) else None)
        except Exception:
            noun = None
        noun = noun or (str(rec) if rec else None)
    if not noun:
        return None
    s = str(noun).strip().lower()
    if not s or len(s) > 24 or any(ch in s for ch in "@#/\\:;\n") or not clean(s):
        return None
    return s


def _ages_rose(world, since: Optional[float]) -> Optional[str]:
    rows = [r for r in _age_history(world) if since is not None and (_epoch(r.get("ts")) or 0) > since]
    if not rows:
        return None
    names = [str(r.get("name") or "").strip() for r in rows if r.get("name")]
    names = [n if n.lower().startswith("the ") else ("the " + n) for n in names]
    if not names:
        return None
    if len(names) == 1:
        return "%s rose" % names[0]
    if len(names) == 2:
        return "%s and %s rose" % (names[0], names[1])
    return "%s, %s and %d more rose" % (names[0], names[1], len(names) - 2)


def compose_return(pip: Dict, world, now: float, away_s: Optional[float] = None, land=None,
                   key: Optional[str] = None) -> Optional[str]:
    """<= 3 diff clauses from pip.last_told against the current len()s, in the spec's order: ages rose, own camp tier,
    own tree stage, own flower drift, own placed thing, people delta, stones delta. `@kai is back` on an empty diff (or
    without a last_told, i.e. before W3's schema); None under 20 min away."""
    if not isinstance(pip, dict):
        return None
    k = str(key or "").lower() or _key_of(pip, world)
    nm = shown_name(pip)
    if not nm:
        return None
    told = pip.get("last_told") if isinstance(pip.get("last_told"), dict) else None
    told_ts = _epoch(told.get("ts")) if told else None
    gap = float(away_s) if away_s is not None else ((float(now) - told_ts) if told_ts is not None else None)
    if gap is None or gap < AWAY_MIN_S:
        return None
    head = "@%s is back" % nm
    clauses: List[str] = []
    if told:
        cur = snapshot(world, k, now, land)

        def old(field: str) -> int:
            v = told.get(field)
            try:
                return int(v) if v is not None else -1
            except Exception:
                return -1

        c = _ages_rose(world, told_ts)
        if c:
            clauses.append(c)
        t_old, t_new = old("camp_tier"), int(cur["camp_tier"])
        if t_new > t_old and t_new >= 1:
            clauses.append(CAMP_RISE.get(t_new, "your camp rose"))
        elif t_new > t_old and t_new == 0:
            clauses.append("your camp stands")
        s_old, s_new = old("tree_stage"), int(cur["tree_stage"])
        if s_new > s_old and s_new >= 1:
            clauses.append(TREE_RISE.get(s_new, "your tree grew"))
        f_old, f_new = old("flower_stage"), int(cur["flower_stage"])
        if f_new > f_old and f_new >= 1:
            clauses.append(FLOWER_RISE)
        new_placed = [r for r in own_placed(world, k) if told_ts is not None and (_epoch(r.get("ts")) or 0) > told_ts
                      and str(r.get("status") or "stands") == "stands"]
        for r in new_placed[:1]:
            noun = placed_noun(r)
            if noun:
                mine = str(r.get("owner") or "").lower() == k
                clauses.append(("your %s stands" if mine else "the %s stands") % noun)
        d_people = int(cur["people"]) - max(0, old("people"))
        if d_people > 0:
            clauses.append("%d walked in" % d_people)
        d_stones = int(cur["stones"]) - max(0, old("stones"))
        if d_stones > 0:
            clauses.append(plural(d_stones, "stone") + " went up")
    line = " · ".join([head] + clauses[:MAX_CLAUSES])
    if not clean(line):
        return head if clean(head) else None
    return line


# ----------------------------------------------------------------------------- the nightly board (day_turn)
def _yesterday_window(now: float) -> Tuple[float, float]:
    lt = _time.localtime(float(now))
    midnight = _time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    return midnight - DAY_S, midnight


def nightly_board(world, now: float, land=None) -> Optional[str]:
    """`yesterday · @sami stacked 3 · 1 walked in · @kai's tent rose · a lantern stands` from stones[].ts, pips[].born_ts,
    camp.tiers[].ts and placed[].ts inside yesterday's local calendar day; only clauses with a count > 0; at most four;
    never a `day N` token. None when nothing happened yesterday."""
    t0, t1 = _yesterday_window(now)

    def inside(ts: Any) -> bool:
        t = _epoch(ts)
        return t is not None and t0 <= t < t1

    pips = _pips(world)
    clauses: List[str] = []
    # stackers (the top two by count, their stones summed)
    by: Dict[str, int] = {}
    for s in _stones(world):
        if inside(s.get("ts")):
            kk = str(s.get("by") or "").lower()
            if kk in pips and not pips[kk].get("_test"):
                by[kk] = by.get(kk, 0) + 1
    if by:
        top = sorted(by.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
        names = [n for n in (shown_name(pips[k_]) for k_, _n in top) if n]
        if names:
            clauses.append("%s stacked %d" % (" ".join("@" + n for n in names), sum(n for _k, n in top)))
    # walked in
    born = sum(1 for p in pips.values() if not p.get("_test") and p.get("state") not in ("seed", "hatching") and inside(p.get("born_ts")))
    if born:
        clauses.append("%d walked in" % born)
    # camps that rose (camp.tiers[] rows, W3; the word of the tier reached)
    rose: List[Tuple[str, int]] = []
    for k_, p in pips.items():
        camp = p.get("camp")
        if p.get("_test") or not isinstance(camp, dict):
            continue
        tiers = [r for r in (camp.get("tiers") or []) if isinstance(r, dict) and inside(r.get("ts")) and int(r.get("tier") or 0) >= 1]
        if tiers:
            nm = shown_name(p)
            if nm:
                rose.append((nm, max(int(r.get("tier") or 0) for r in tiers)))
    if len(rose) == 1:
        clauses.append("@%s's %s rose" % (rose[0][0], CAMP_WORDS[min(3, rose[0][1])]))
    elif len(rose) > 1:
        clauses.append("@%s's and %d others' camps rose" % (rose[0][0], len(rose) - 1))
    # placed things that stand
    stood = [r for r in _placed(world) if inside(r.get("ts")) and str(r.get("status") or "stands") == "stands"]
    if len(stood) == 1:
        noun = placed_noun(stood[0])
        if noun:
            clauses.append("%s %s stands" % ("an" if noun[:1] in "aeiou" else "a", noun))
    elif len(stood) > 1:
        clauses.append("%d stand" % len(stood))
    if not clauses:
        return None
    line = " · ".join(["yesterday"] + clauses[:BOARD_MAX_CLAUSES])
    return line if clean(line) else None


# ----------------------------------------------------------------------------- !stats and the camp plate
def stats_extra(pip: Dict, world) -> List[str]:
    """Extra `!stats` clauses this slice owns: `1 stands` / `3 stand` when the person's placed rows exist."""
    if not isinstance(pip, dict):
        return []
    n = len([r for r in own_placed(world, _key_of(pip, world)) if str(r.get("status") or "stands") == "stands"])
    if n <= 0:
        return []
    s = "%d stand%s" % (n, "s" if n == 1 else "")
    return [s] if clean(s) else []


def stats_line(pip: Dict, world, now: Optional[float] = None, land=None) -> Optional[str]:
    """The whole `!stats` line as this module would compose it (the panel composes its own and appends stats_extra):
    `@kai · hut · 5 stones · 41 min here · 1 stands`. Every number a len()."""
    nm = shown_name(pip)
    if not nm:
        return None
    parts = ["@" + nm]
    tier = own_camp_tier(pip, world, land)
    if tier >= 0:
        parts.append(CAMP_WORDS[min(3, tier)])
    k = _key_of(pip, world)
    stones = sum(1 for s in _stones(world) if str(s.get("by") or "").lower() == k)
    if stones:
        parts.append(plural(stones, "stone"))
    mins = int(round(float(pip.get("minutes_present") or 0.0)))
    if mins:
        parts.append("%d min here" % mins)
    parts.extend(stats_extra(pip, world))
    line = " · ".join(parts)
    return line if clean(line) else None


def camp_plate_first_here(pip: Dict) -> str:
    """`first here 26 Sep` from first_seen_ts (born_ts when older records lack it); '' when unknown."""
    if not isinstance(pip, dict):
        return ""
    t = _epoch(pip.get("first_seen_ts")) or _epoch(pip.get("born_ts"))
    d = date_word(t)
    if not d:
        return ""
    s = "first here " + d
    return s if clean(s) else ""


def camp_plate_suffix(pip: Dict) -> str:
    s = camp_plate_first_here(pip)
    return (" · " + s) if s else ""


# ----------------------------------------------------------------------------- the scene / panel hooks' logic
def _state(scene) -> Dict[str, Any]:
    st = getattr(scene, "_w5", None)
    if not isinstance(st, dict):
        st = {"mutter_at": {}, "board": None, "date": None}
        try:
            scene._w5 = st
        except Exception:
            pass
    return st


def on_hatch(scene, key: str, now: float) -> None:
    """`last_told` is written at hatch (IDLEWORLD 1.4) when the schema allows the field."""
    w = getattr(scene, "world", None)
    p = w.pip(key) if w is not None else None
    if p is None or p.get("_test") or not may_write_last_told(w):
        return
    p["last_told"] = snapshot(w, key, now, getattr(scene, "land", None))
    w.dirty = True


def on_return(scene, ev: Dict[str, Any], key: str, now: float) -> Optional[str]:
    """The `return` event's ledger side (steading._persist hook): ev["told"] / ev["now"] / ev["told_line"] attached, the
    plank line composed and validated here (the panel only draws ev["told_line"] at PRIO_YOU), last_told rewritten when
    the schema allows it, the own-word mutter scheduled. Returns the line (None under 20 min / no real pip)."""
    w = getattr(scene, "world", None)
    p = w.pip(key) if w is not None else None
    if p is None or p.get("_test"):
        return None
    land = getattr(scene, "land", None)
    told = p.get("last_told") if isinstance(p.get("last_told"), dict) else None
    line = compose_return(p, w, now, away_s=ev.get("away_s"), land=land, key=key)
    cur = snapshot(w, key, now, land)
    ev["told"], ev["now"] = (dict(told) if told else None), cur
    if line:
        ev["told_line"] = line
        ev["plate_pin_s"] = 10.0
        _state(scene)["mutter_at"][str(key).lower()] = float(now) + MUTTER_AFTER_S
    if may_write_last_told(w):
        p["last_told"] = cur
        w.dirty = True
    return line


def frame_hook(scene, ev: List[Dict[str, Any]], now: float) -> None:
    """Once per frame before steading._idle_life: (a) a due return mutter becomes a `mutter_due` event (the scene answers
    it with one of the owner's OWN allowlisted words, here-only); (b) a `day_turn` event (W3's record_visit, or this
    module's local-date change fallback while W3 is absent) computes the nightly board for BOARD_S."""
    st = _state(scene)
    b, w = getattr(scene, "behaviour", None), getattr(scene, "world", None)
    due = [k for k, t in st["mutter_at"].items() if float(now) >= t]
    for k in due:
        st["mutter_at"].pop(k, None)
        e = b.get(k) if b is not None else None
        if e is None or not e.is_present(now):
            continue
        ev.append({"type": "mutter_due", "pip": k, "why": "return"})
    today = local_date(now)
    if st["date"] is None:
        st["date"] = today                                      # a boot never turns the day
    elif st["date"] != today and not any(e_.get("type") == "day_turn" for e_ in ev):
        st["date"] = today
        ev.append({"type": "day_turn", "date": today, "by": "ledger"})
    for e_ in ev:
        if e_.get("type") == "day_turn":
            st["date"] = today
            text = nightly_board(w, now, getattr(scene, "land", None)) if w is not None else None
            st["board"] = (text, float(now) + BOARD_S) if text else None
            if text:
                e_["board"] = text


def board_plate(scene, now: float) -> Optional[str]:
    """The nightly board's plate text while it rides the rotation (panels.world._mark_list hook); None otherwise."""
    st = getattr(scene, "_w5", None)
    if not isinstance(st, dict) or not st.get("board"):
        return None
    text, until = st["board"]
    if float(now) >= float(until):
        st["board"] = None
        return None
    return text


# ----------------------------------------------------------------------------- self-tests
def _fixture_world(now: float) -> Dict[str, Any]:
    """A raw world.json-shaped dict (schema 2 + the schema-3 fields this module reads) with three real pips."""
    def pip(name: str, n: int, born: float, camp_tier: int = 1) -> Dict[str, Any]:
        return {"name": name, "display_name": name, "n": n, "born_ts": epoch_to_iso(born), "first_seen_ts": epoch_to_iso(born),
                "last_seen_ts": epoch_to_iso(now), "state": "idle", "minutes_present": 41.2, "sessions_seen": 3,
                "camp": {"x": 500, "y": 200, "tier": camp_tier, "built_ts": epoch_to_iso(born), "nights": [], "tiers": []}}
    return {"schema": 2,
            "pips": {"kai": pip("kai", 4, now - 3 * DAY_S, 1), "sami": pip("sami", 1, now - 30 * DAY_S, 2), "jo": pip("jo", 7, now - 2 * DAY_S, 0)},
            "world": {"hatched_ever": 3, "stones": [{"by": "sami", "ts": epoch_to_iso(now - 2 * 3600), "cairn_id": "moot"}],
                      "marks": [{"id": "m1", "type": "flower", "x": 510, "y": 205, "owner": "kai", "ts": epoch_to_iso(now - 8 * DAY_S)},
                                {"id": "m2", "type": "tree", "x": 520, "y": 210, "owner": "kai", "ts": epoch_to_iso(now - 4 * DAY_S)}],
                      "age": 0, "age_history": [], "placed": []}}


def _self_test(verbose: bool = True) -> bool:
    ok = True

    def gate(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and bool(passed)
        print("  [%s] %s%s" % ("PASS" if passed else "FAIL", name, (" · " + detail) if detail else ""))

    print("ledger --self-test")
    now = _time.time()
    W = _fixture_world(now)
    kai = W["pips"]["kai"]
    # 1. the row-8 fixture: 25 min away, age_history +1 row, camp tier +1 -> exactly the spec line
    kai["last_told"] = snapshot(W, "kai", now - 25 * 60)
    W["world"]["age"] = 1
    W["world"]["age_history"].append({"idx": 1, "name": "the Camp", "ts": epoch_to_iso(now - 60), "raised_by": ["sami"]})
    kai["camp"]["tier"] = 2
    line = compose_return(kai, W, now, away_s=25 * 60)
    gate("25 min away, age +1 row, camp tier +1", line == "@kai is back · the Camp rose · your tent is a hut", repr(line))
    # 2. the four-clause case is cut at three, in the spec's order
    W["pips"]["new1"] = dict(W["pips"]["jo"], name="new1", display_name="new1", n=9, born_ts=epoch_to_iso(now - 30))
    W["world"]["stones"].append({"by": "sami", "ts": epoch_to_iso(now - 10), "cairn_id": "moot"})
    line4 = compose_return(kai, W, now, away_s=25 * 60)
    gate("<= 3 clauses, spec order", line4 == "@kai is back · the Camp rose · your tent is a hut · 1 walked in", repr(line4))
    # 3. empty diff -> `@kai is back`; under 20 min -> nothing; no last_told (schema 2) -> `@kai is back`
    W2 = _fixture_world(now)
    W2["pips"]["kai"]["last_told"] = snapshot(W2, "kai", now - 30 * 60)
    e_line = compose_return(W2["pips"]["kai"], W2, now, away_s=30 * 60)
    gate("empty diff", e_line == "@kai is back", repr(e_line))
    gate("under 20 min: nothing", compose_return(kai, W, now, away_s=19 * 60 + 59) is None)
    gate("no last_told (schema 2 file): bare line", compose_return(W2["pips"]["jo"], W2, now, away_s=3600) == "@jo is back")
    gate("no last_told and no away_s: nothing (no gap to measure)", compose_return(W2["pips"]["jo"], W2, now) is None)
    # 4. every clause form passes the copy gate; a poisoned noun never reaches a line
    hits = banned_hits(list(CLAUSE_FORMS) + [line, line4, e_line or ""])
    gate("every clause form passes banned_copy_hits", not hits, repr(hits))
    W3 = _fixture_world(now)
    W3["pips"]["kai"]["last_told"] = snapshot(W3, "kai", now - 3600)
    W3["world"]["placed"] = [{"id": "p-0001", "ts": epoch_to_iso(now - 60), "recipe": "lantern", "noun": "lantern", "owner": "kai",
                              "askers": ["kai"], "status": "stands"}]
    l_line = compose_return(W3["pips"]["kai"], W3, now, away_s=3600)
    gate("own placed row -> `your lantern stands`", l_line == "@kai is back · your lantern stands", repr(l_line))
    W3["world"]["placed"][0]["noun"] = "ai build"
    p_line = compose_return(W3["pips"]["kai"], W3, now, away_s=3600)
    gate("a banned noun on a placed row draws no clause", p_line == "@kai is back", repr(p_line))
    W3["world"]["placed"][0].update({"noun": "castle", "owner": "sami", "askers": ["kai", "sami"]})
    a_line = compose_return(W3["pips"]["kai"], W3, now, away_s=3600)
    gate("asked-for placed row -> `the castle stands`", a_line == "@kai is back · the castle stands", repr(a_line))
    # 5. tree / flower / stones clauses
    W4 = _fixture_world(now)
    W4["world"]["marks"][0]["ts"] = epoch_to_iso(now - 1.5 * DAY_S)      # flower planted 1.5 days ago
    W4["world"]["marks"][1]["ts"] = epoch_to_iso(now - 2.9 * DAY_S)      # tree 2.9 days: sapling
    W4["pips"]["kai"]["last_told"] = snapshot(W4, "kai", now)
    later = now + 1.0 * DAY_S                                              # a day on: flower day 2.5 (3 blooms), tree day 3.9 (young)
    W4["world"]["stones"] += [{"by": "sami", "ts": epoch_to_iso(later - 5), "cairn_id": "moot"} for _ in range(9)]
    t_line = compose_return(W4["pips"]["kai"], W4, later, away_s=DAY_S)
    gate("tree young + flowers spread + 9 stones went up", t_line == "@kai is back · your tree is young · your flowers spread · 9 stones went up", repr(t_line))
    # 6. names clause > 6 -> `and N others` fits the 22 px plate
    many = ["name%02d" % i for i in range(20)]
    nc = names_clause(many)
    gate("names_clause caps at 6 + `and 14 others`", nc.endswith(" and 14 others") and nc.count("@") == 6, nc)
    try:
        Lmod = importlib.import_module("stream.layout")
        prefix = "the Camp · since 26 Sep · raised by "
        fit = names_clause(many, prefix=prefix, max_w=640)
        pw = Lmod.text_width("HN Medium", 22, prefix + fit) + 2 * 12
        shown = fit.count("@")
        gate("founders plate > 6 names -> `and N others` fits PLATE_MAX_W 640 at HN Medium 22", pw <= 640 and fit.endswith(" and %d others" % (20 - shown))
             and shown >= 1, "%d px · %s" % (pw, fit))
        gate("names that fit are not cut", names_clause(["sami", "jo"], prefix=prefix, max_w=640) == "@sami @jo")
    except Exception as ex:
        gate("plate width measured", False, repr(ex))
    # 7. the nightly board: from timestamps, `yesterday`, no `day N`
    W5 = _fixture_world(now)
    y0, y1 = _yesterday_window(now)
    mid = (y0 + y1) / 2.0
    W5["world"]["stones"] = [{"by": "sami", "ts": epoch_to_iso(mid + i), "cairn_id": "moot"} for i in range(3)]
    W5["pips"]["jo"]["born_ts"] = epoch_to_iso(mid)
    W5["pips"]["kai"]["camp"]["tiers"] = [{"tier": 1, "ts": epoch_to_iso(mid + 100)}]
    W5["world"]["placed"] = [{"id": "p-0002", "ts": epoch_to_iso(mid + 200), "noun": "lantern", "owner": "kai", "askers": [], "status": "stands"}]
    board = nightly_board(W5, now)
    gate("nightly board from timestamps", board == "yesterday · @sami stacked 3 · 1 walked in · @kai's tent rose · a lantern stands", repr(board))
    gate("day_turn plate has no `day N` and passes the copy gate", bool(board) and " day " not in (" " + board.lower() + " ") and not banned_hits([board]))
    gate("nothing yesterday -> no board", nightly_board(_fixture_world(now - 40 * DAY_S), now) is None)
    W5["world"]["stones"][0]["ts"] = epoch_to_iso(now - 30)                                  # today's stone is not yesterday's
    b2 = nightly_board(W5, now)
    gate("today's records stay off yesterday's board", b2 == "yesterday · @sami stacked 2 · 1 walked in · @kai's tent rose · a lantern stands", repr(b2))
    # 8. flower drift stages and clumps
    st0, st2, st8 = (flower_drift_stage({"ts": epoch_to_iso(now - d * DAY_S)}, now) for d in (0.5, 2.0, 8.0))
    gate("flower drift 1 / 3 / 5 blooms at 0 / 2 / 7 real days", (st0, st2, st8) == (1, 3, 5), "%s" % ((st0, st2, st8),))
    gate("no timestamp -> 1 bloom", flower_drift_stage({}, now) == 1)
    cl = drift_clumps(510, 205, 2, 5)
    gate("5-bloom drift = 5 clumps inside the repaint region, deterministic", len(cl) == 5 and all(abs(dx) <= 2.2 and -0.5 <= dy <= 0.5 for dx, dy, _v in cl)
         and cl[0] == (0.0, 0.0, 2) and cl == drift_clumps(510, 205, 2, 5), repr(cl))
    gate("3 blooms = 3 clumps, 1 bloom = the mark alone", len(drift_clumps(1, 1, 0, 3)) == 3 and drift_clumps(1, 1, 0, 1) == [(0.0, 0.0, 0)])
    # 9. !stats and the camp plate
    gate("stats_extra without placed rows", stats_extra(W["pips"]["kai"], W) == [])
    W3b = dict(W3, world=dict(W3["world"], placed=W3["world"]["placed"] * 2))
    gate("stats_extra `1 stands` / `2 stand`", stats_extra(W3["pips"]["kai"], W3) == ["1 stands"] and stats_extra(W3["pips"]["kai"], W3b) == ["2 stand"])
    sl = stats_line(W3["pips"]["kai"], W3)
    gate("stats_line", sl == "@kai · tent · 41 min here · 1 stands" and clean(sl), repr(sl))
    fh = camp_plate_first_here(kai)
    gate("camp plate `first here <date>`", fh == "first here " + date_word(now - 3 * DAY_S) and clean(fh), fh)
    # 10. snapshot keys and the write gate on a schema-2 file
    snap = snapshot(W, "kai", now)
    gate("snapshot keys", sorted(snap) == ["age", "camp_tier", "flower_stage", "people", "placed", "stones", "tree_stage", "ts"], repr(snap))
    # With state.SCHEMA >= 3 in the tree (W3 landed) the gate is open for every file: the first save migrates and writes the
    # field; on an older tree (SCHEMA 2) a schema-2 file without the field must NOT be written. Assert the rule that applies.
    _st_schema = int(getattr(importlib.import_module("stream.world.state"), "SCHEMA", 2))
    if _st_schema >= 3:
        gate("last_told write gate: state.SCHEMA >= 3 -> written even on a file without the field", may_write_last_told(_fixture_world(now)))
    else:
        gate("last_told write gate: schema 2 file without the field -> not written", not may_write_last_told(_fixture_world(now)))
    gate("last_told write gate: a file carrying the field -> written", may_write_last_told(W))
    print("ledger --self-test: %s" % ("PASS" if ok else "FAIL"))
    return ok


def _scene_test() -> bool:                                       # pragma: no cover - a harness (RUN_DIR under /tmp, MODE=test)
    """A real SteadingScene on a /tmp run dir: a chatter hatches, plants a flower whose record is back-dated 8 days, a
    5-bloom drift is painted by the bake (len(marks) unchanged, repaint <= 19 ms, provenance 0); then the person is away
    25 min and returns: ev["told_line"] rides the event, last_told is not written on a schema-2 file."""
    import json
    import shutil
    import numpy as np
    run_dir = os.environ.get("RUN_DIR") or "/tmp/lg-w5-scene"
    rp = os.path.realpath(run_dir)
    if not (rp.startswith("/tmp/") or rp.startswith("/private/tmp/")) or os.environ.get("MODE") != "test":
        print("REFUSED: RUN_DIR under /tmp and MODE=test required", file=sys.stderr)
        return False
    if os.path.isdir(run_dir):
        shutil.rmtree(run_dir)
    os.makedirs(run_dir, exist_ok=True)
    os.environ["RUN_DIR"] = run_dir
    os.environ.pop("KL_TEST_PIPS", None)
    from stream.scenes.steading import SteadingScene, _Ctx, SCREEN
    ok = True

    def gate(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and bool(passed)
        print("  [%s] %s%s" % ("PASS" if passed else "FAIL", name, (" · " + detail) if detail else ""))

    print("ledger --scene-test (run dir %s)" % run_dir)
    lt = _time.localtime()
    now0 = _time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst)) + 14 * 3600.0
    sid = "w5-%d" % int(_time.time())
    fps = 30.0

    def mkctx(now, frame, chat_raw=(), chat=()):
        return _Ctx(now=now, frame=frame, session={"id": sid, "started_ts": epoch_to_iso(now0), "ending": False}, micro={"canvas_seed": 4471},
                    preset="kick", chat_raw=list(chat_raw), chat=list(chat), recent_votes=[], round={"number": 1}, round_remaining=120.0,
                    mod={"hidden_users": []}, mod_paused=False, agent={"heartbeat_ts": None}, macro={}, compositor_live={"selftest": True}, selftest=True)

    def raw(mid, name, text, t):
        return {"id": mid, "name": name, "text": text, "t": t, "type": "message", "badges": []}

    def clear(mid, name, text, t):
        return {"id": mid, "name": name, "display_name": name, "text": text, "text_clean": text, "t": t, "kind": "plain",
                "first_ever": True, "builder_n": 3, "dropped": False, "history": False}

    def chat_line(mid, name, text, t):
        with open(os.path.join(run_dir, "chat.jsonl"), "a") as fh:
            fh.write(json.dumps({"id": mid, "username": name, "content": text, "ts": epoch_to_iso(t), "badges": []}) + "\n")

    name = "kai_w5"
    sc = SteadingScene(run_dir=run_dir, seed=7, log=lambda m: None, sleep_after_s=120.0)
    size = SCREEN
    t_boot = _time.perf_counter()
    while not sc.booted and _time.perf_counter() - t_boot < 30:
        sc.frame(mkctx(now0, 0), size)
        _time.sleep(0.01)
    gate("scene booted", sc.booted and not sc.refused, "%.0f ms" % ((_time.perf_counter() - t_boot) * 1000))
    now = now0
    f = 0
    for f in range(1, 260):
        now = now0 + f / fps
        rr, cc = [], []
        if f == 30:
            rr.append(raw("w1", name, "hello land", now))
            chat_line("w1", name, "hello land", now)
        if f == 30 + int(3.2 * fps):
            cc.append(clear("w1", name, "hello land", now0 + 30 / fps))
        sc.frame(mkctx(now, f, rr, cc), size)
        _time.sleep(0.002)
    e = sc.behaviour.get(name)
    gate("the chatter hatched and is here", e is not None and e.is_present(now) and sc.present_count() == 1)
    okc, whyc = sc.command("camp", name, now=now)
    okp, whyp = sc.command("plant", name, arg="flower", now=now)
    if not okp:                                                      # the feet stood on a trail: plant the flower beside the camp instead
        camp = sc.land.camp_of(name) or {}
        cx0, cy0 = int(camp.get("x") or sc.land.moot[0]), int(camp.get("y") or sc.land.moot[1])
        for r in range(3, 14):
            for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r), (r, r), (-r, r), (r, -r), (-r, -r)):
                if sc.land.mark_allowed(name, cx0 + dx, cy0 + dy, "flower")[0]:
                    m_, whyp = sc.land.add_mark("flower", cx0 + dx, cy0 + dy, name, now)
                    okp = m_ is not None
                    break
            if okp:
                break
    gate("camp + flower planted", okc and okp, "%s / %s" % (whyc, whyp))
    n_marks = len(sc.land.marks)
    mk = [m for m in sc.land.marks_of_type("flower") if m.get("owner") == name]
    gate("one flower mark owned by the chatter", len(mk) == 1, "%d" % len(mk))
    if len(mk) != 1:
        print("ledger --scene-test: FAIL (no flower mark to test the drift with)")
        return False
    mk[0]["ts"] = epoch_to_iso(now - 8 * DAY_S)                     # the record is 8 real days old (a back-dated fixture, never a new row)
    sc.world.dirty = True
    while sc.bakes.baking:
        f += 1
        now += 1 / fps
        sc.frame(mkctx(now, f), size)
        _time.sleep(0.005)
    for _ in range(150):                                             # the marks dict rebuilds (blooms in its signature) and the worker repaints
        f += 1
        now += 1 / fps
        sc.frame(mkctx(now, f), size)
        _time.sleep(0.003)
    fl = [x for x in sc._marks.get("flowers", ()) if x.get("owner") == name]
    gate("the marks dict carries blooms 5 for the 8-day flower", len(fl) == 1 and int(fl[0].get("blooms") or 1) == 5, repr(fl))
    gate("len(marks) unchanged by the drift", len(sc.land.marks) == n_marks, "%d" % len(sc.land.marks))
    B = sc.bakes.current
    x, y = int(mk[0]["x"]), int(mk[0]["y"])
    region = (max(0, x - 5), max(0, y - 5), min(sc.terrain.w, x + 6), min(sc.terrain.h, y + 2))
    B.marks = dict(sc._marks)
    ms = [B.repaint(region) for _ in range(5)]
    gate("repaint of the drift region <= 19 ms", max(ms) <= 19.0, "%.1f ms max over 5 (%s)" % (max(ms), ", ".join("%.1f" % v for v in ms)))
    px = B.px
    full5 = np.zeros((sc.terrain.h * px, sc.terrain.w * px, 3), dtype=np.uint8)   # paint_props indexes the bake's pixel space
    full1 = full5.copy()
    B.marks = dict(sc._marks, flowers=[dict(fl[0], blooms=5)], huts=[], fields=[])
    B.paint_props(full5, region)
    B.marks = dict(sc._marks, flowers=[dict(fl[0], blooms=1)], huts=[], fields=[])
    B.paint_props(full1, region)
    B.marks = dict(sc._marks)
    n5, n1 = int((full5.sum(axis=2) > 0).sum()), int((full1.sum(axis=2) > 0).sum())
    gate("a 5-bloom drift paints more than one clump", n5 > n1 * 2, "%d px vs %d px" % (n5, n1))
    prov = sc.land.provenance_violations()
    gate("provenance 0", not prov and sc.honesty_violations == 0, repr(prov))
    # the return beat: away 25 min (present_s 120 s here), then a raw record -> `return` with the ledger line
    p = sc.world.pip(name)
    had_told = "last_told" in (p or {})
    snap_before = snapshot(sc.world, name, now, sc.land)
    now += 25 * 60.0
    f += 1
    sc.frame(mkctx(now, f), size)
    gate("the chatter is away after 25 min", not sc.behaviour.get(name).is_present(now))
    now += 1 / fps
    f += 1
    sc.frame(mkctx(now, f, [raw("w2", name, "back", now)]), size)
    chat_line("w2", name, "back", now)
    ret = [ev for ev in sc.events if ev.get("type") == "return"]
    gate("one return event", len(ret) == 1 and ret[0].get("pip") == name, repr([(ev.get("type"), ev.get("pip")) for ev in sc.events]))
    tl = ret[0].get("told_line") if ret else None
    gate("the return line rides the event (`@kai_w5 is back`: no last_told on a schema-2 file -> bare line)", tl == "@%s is back" % name, repr(tl))
    gate("ev now/told attached; told is None before the schema bump", bool(ret) and ret[0].get("now") is not None and ret[0].get("told") is None,
         repr(ret[0].get("now") if ret else None))
    p = sc.world.pip(name)
    st = importlib.import_module("stream.world.state")
    if int(getattr(st, "SCHEMA", 2)) >= 3 or had_told:
        gate("last_told written (schema >= 3)", isinstance(p.get("last_told"), dict))
    else:
        gate("last_told NOT written on a schema-2 file (W3 owns the bump)", "last_told" not in p)
    gate("snapshot people/stones are len()s", snap_before["people"] == sc.world.hatched_ever and snap_before["stones"] == len(sc.land.stones), repr(snap_before))
    # the own-word mutter lands ~2.5 s after the return
    muttered = None
    for _ in range(int(4 * fps)):
        f += 1
        now += 1 / fps
        sc.frame(mkctx(now, f), size)
        m = [ev for ev in sc.events if ev.get("type") in ("mutter", "mutter_due") and ev.get("pip") == name and ev.get("why") == "return"]
        if m:
            muttered = m[0]
            break
    gate("own-word mutter scheduled on return (spoken only if the owner has an allowlisted word)", muttered is not None, repr(muttered))
    # day_turn fallback + the board plate
    _state(sc)["date"] = "1970-01-01"
    f += 1
    now += 1 / fps
    sc.frame(mkctx(now, f), size)
    dt_ev = [ev for ev in sc.events if ev.get("type") == "day_turn"]
    gate("local-date change -> one day_turn event (W3 absent)", len(dt_ev) == 1 and dt_ev[0].get("by") == "ledger", repr(dt_ev))
    bp = board_plate(sc, now)
    gate("board plate is None when nothing happened yesterday (never an empty `yesterday`)", bp is None or (bp.startswith("yesterday · ") and clean(bp)), repr(bp))
    gate("scene clean", sc.errors == 0 and sc.honesty_violations == 0, "errors %d honesty %d" % (sc.errors, sc.honesty_violations))
    try:
        for root, _d, files in os.walk(run_dir):
            for fn in files:
                if fn.endswith((".png", ".npy")):
                    os.remove(os.path.join(root, fn))
    except Exception:
        pass
    print("ledger --scene-test: %s" % ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":   # pragma: no cover
    if "--self-test" in sys.argv:
        sys.exit(0 if _self_test() else 1)
    if "--scene-test" in sys.argv:
        sys.exit(0 if _scene_test() else 1)
    print(__doc__)
