"""The wish registry: DATA + pure functions (IDLEWORLD.md §2.2-2.5, §5, §8 row 2).

Hot-reloadable, tunable, side-effect free. The keyword tables, the kit recipes, the caps and the refusal copy live
here; the validator that makes "chat is data" true lives in `honesty.py` (`validate_registry`, `FN_ALLOWLIST`), which
is why this module holds only closed tables and never a path, a shell string or a model call.

    classify(text, verb, hint) -> Wish(cls, noun, merge_key, recipe, param, value)
    merge_key(text) -> str
    place(recipe, owner_camp_xy, land, terrain) -> (x, y) | None
    $PY stream/world/registry.py --self-test

Precedence when several tables match: refuse > have_it > recipe > project > menu > mechanic > silent > unknown.
Two scoped rules sit inside that order (both explained at the call site): a mechanic VERB in head position (`cut some
trees`) says what to do with the noun, so it classes `mechanic` before the noun's recipe; a destructive word beside an
`outside` word (`remove the grey area of the screen`) is a comment on the stream, not an act on the land, so it never
draws the destructive refusal.

Every string a panel may compose from this module is a closed-table noun or a template over one; every one of them is
checked against `compositor.banned_copy_hits` in `--self-test`. A chatter's sentence is never a value in any table.

Nothing here imports `behaviour`, `honesty`, `state`, `steading`, `panels.world` or `chat_bridge`; `terrain`, `land`
and the art kit are imported lazily inside functions and only for geometry / the self-test.
"""
from __future__ import annotations

import collections
import math
import os
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ---------------------------------------------------------------------------- the record
# `cls` is the class column (`class` is a keyword): recipe:<slug> | project:<slug> | menu:<param>:<value> | mechanic |
# have_it | refuse:animate | refuse:destructive | silent | unknown. `noun` is the closed-table noun a plank / plate may
# print (None when no table knows one). `merge_key` is the cluster key (§2.5). `recipe` is a RECIPES slug or None.
# `param` / `value` are set for menu wishes (a real MENU param and one of its values) and for `silent` (`param` = the
# silent group: outside | clock | theme | chat | verb).
Wish = collections.namedtuple("Wish", "cls noun merge_key recipe param value")

# ---------------------------------------------------------------------------- word tables (lower-cased canonical stems)
# The bridge's tag (§2.1 b): a plain line with >= 3 tokens whose first content token is one of these is a wish.
WISH_HEADS: Tuple[str, ...] = ("build", "make", "add", "put", "dig", "cut", "climb", "zoom", "raise", "give", "want",
                               "need", "more", "less", "bigger", "change", "turn", "wish", "should")

# `build` / `make` / `raise` with no noun any table knows is an ask to raise SOMETHING: promoted as a mechanic (§2.2 the
# live `build something` x2), never `unknown`.
BUILD_HEADS: Tuple[str, ...] = ("build", "make", "raise")

# chat_bridge.STOP_WORDS (L159) plus the function words merge_key skips when it looks for the first content token.
STOP_WORDS = frozenset(("a", "an", "the", "to", "at", "my", "some", "on", "of", "in", "out", "up", "down", "here",
                        "there", "this", "that", "it", "its", "is", "are", "be", "all", "for", "with", "and", "or",
                        "me", "us", "we", "i", "you", "your", "our", "please", "can", "could", "would", "let's",
                        "lets", "let", "just", "so", "now", "also", "too", "very", "really", "actual", "actually",
                        "into", "from", "by", "as", "if", "then", "than", "them", "they", "not", "no", "yes", "do",
                        "does", "did", "have", "has", "had", "get", "got", "go", "one", "thing", "things", "field",
                        "whole", "completely", "new", "little", "big", "large", "grey", "gray", "area", "somewhere"))

# aliases and plurals -> canonical stem (§2.5: `lamp -> lantern`, `flag -> banner`, `beat|techno|song -> music`,
# `rocks -> stones`). Sixty-plus entries; every table below is keyed by the canonical stem.
SYNONYMS: Dict[str, str] = {
    # recipes
    "lanterns": "lantern", "lamp": "lantern", "lamps": "lantern", "lamppost": "lantern", "lampposts": "lantern",
    "banners": "banner", "flag": "banner", "flags": "banner", "pennant": "banner", "pennants": "banner",
    "gardens": "garden", "veg": "garden", "vegetable": "garden", "vegetables": "garden", "herb": "garden",
    "herbs": "garden", "bed": "garden", "beds": "garden", "allotment": "garden",
    "flowers": "flower", "meadow": "flower", "bloom": "flower", "blooms": "flower", "blossom": "flower",
    "blossoms": "flower", "daisies": "flower", "roses": "flower",
    "trees": "tree", "orchard": "tree", "forest": "tree", "wood": "tree", "woods": "tree", "grove": "tree",
    "groves": "tree", "sapling": "tree", "saplings": "tree",
    "rocks": "stones", "circle": "stones", "ring": "stones", "henge": "stones", "boulders": "stones",
    "benches": "bench", "seat": "bench", "seats": "bench", "chair": "bench", "chairs": "bench",
    # projects
    "castles": "castle", "keeps": "castle", "keep": "castle", "tower": "castle", "towers": "castle",
    "fort": "castle", "fortress": "castle", "wall": "castle", "walls": "castle",
    "bridges": "bridge", "wells": "well",
    "tavern": "hall", "inn": "hall", "pub": "hall", "longhouse": "hall", "market": "hall", "halls": "hall",
    "square": "plaza", "plazas": "plaza",
    "harbor": "harbour", "harbours": "harbour", "dock": "harbour", "docks": "harbour", "port": "harbour",
    "boat": "harbour", "boats": "harbour", "ship": "harbour", "ships": "harbour",
    # menu
    "storm": "rain", "storms": "rain", "raining": "rain", "foggy": "fog", "mist": "fog", "misty": "fog",
    "windy": "wind", "sunny": "clear", "sunshine": "clear",
    "techno": "music", "beat": "music", "beats": "music", "song": "music", "songs": "music", "tune": "music",
    "tunes": "music", "drum": "music", "drums": "music", "bass": "music",
    "feast": "bonfire", "party": "bonfire", "bonfires": "bonfire",
    # mechanics
    "holes": "hole", "mining": "mine", "mines": "mine", "tunnels": "tunnel", "gem": "gems", "chopping": "chop",
    "chopped": "chop", "cutting": "cut", "digging": "dig", "fishing": "fish", "farming": "farm", "farms": "farm",
    # refusals
    "dogs": "dog", "puppy": "dog", "puppies": "dog", "cats": "cat", "kitten": "cat", "kittens": "cat",
    "birds": "bird", "cows": "cow", "horses": "horse", "wolves": "wolf", "dragons": "dragon", "pets": "pet",
    "animals": "animal", "chickens": "chicken", "ducks": "duck",
    "destroying": "destroy", "destroyed": "destroy", "killing": "kill", "burning": "burn", "removing": "remove",
    "deleting": "delete", "demolishing": "demolish", "torch": "burn",
    # have_it
    "huts": "hut", "tents": "tent", "houses": "house", "homes": "home", "roads": "road", "paths": "path",
    "cottage": "house", "cabin": "house",
    # theme / colour
    "colours": "colour", "colors": "colour", "color": "colour", "themes": "theme",
}

# stem -> recipe slug (tier 1). `flower` -> flowerbed only when no `plant` verb parsed (a parsed verb never reaches
# classify, so the check is the `verb` argument).
RECIPE_WORDS: Dict[str, str] = {
    "lantern": "lantern", "banner": "banner", "garden": "garden", "flower": "flowerbed", "tree": "trees",
    "stones": "stone_ring", "bench": "bench_stones",
}
# stem -> project slug (tier 3, AGE_PROJECTS)
PROJECT_WORDS: Dict[str, str] = {
    "castle": "keep", "bridge": "bridge", "well": "well", "hall": "hall", "plaza": "plaza", "harbour": "harbour",
}
# stem -> (MENU param, MENU value) — real rounds.MENU params and values only (a wish biases draw_options, §2.3 tier 2)
MENU_WORDS: Dict[str, Tuple[str, str]] = {
    "rain": ("weather", "rain"), "fog": ("weather", "fog"), "wind": ("weather", "wind"), "clear": ("weather", "clear"),
    "music": ("audio_pattern", "pulse_hats"),
    "bonfire": ("bonfire", "now"),
}
# stems that name a mechanic (tier 2: promoted to ideas[] for the orchestrator)
MECHANIC_WORDS: Tuple[str, ...] = ("dig", "hole", "mine", "tunnel", "gems", "cut", "chop", "axe", "lumber", "fish", "farm")
# the mechanic VERBS: in head position they decide the class before the noun's table (`cut some trees` is not a wish for trees)
MECHANIC_VERBS: Tuple[str, ...] = ("dig", "mine", "cut", "chop", "fish", "farm")
# stem -> have_it key (answered from records: a camp exists at hatch, paths wear where you walk)
HAVE_IT_WORDS: Dict[str, str] = {"hut": "camp", "tent": "camp", "house": "camp", "home": "camp", "road": "path", "path": "path"}
REFUSE_WORDS: Dict[str, Tuple[str, ...]] = {
    "animate": ("dog", "cat", "bird", "cow", "sheep", "horse", "wolf", "dragon", "animal", "chicken", "duck", "fish", "pet"),
    "destructive": ("kill", "destroy", "burn", "delete", "remove", "tear", "demolish", "nuke"),
}
# `fish` / `pet` are refusal nouns only after a determiner (`a fish`, `my pet`); bare they are the verb `pet` / the
# mechanic `fish`.
NOUN_ONLY_AFTER = frozenset(("a", "an", "the", "some", "my", "our", "your", "pet", "more"))
SILENT_WORDS: Dict[str, Tuple[str, ...]] = {
    "outside": ("repo", "commit", "code", "github", "bot", "ai", "prompt", "claude", "stream", "camera", "mic",
                "overlay", "hud", "screen", "zoom", "art", "style", "font", "keeper", "keepers", "help", "stats",
                "commands", "mod", "mods", "discord", "twitch", "kick"),
    "clock": ("night", "dark", "day", "morning", "sunset", "sunrise", "time", "evening", "noon", "midnight"),
    "theme": ("colour", "theme"),
    # `chat` is the fallback group: no head, no noun (greetings, goodbyes, laughs)
}
THEME_PRESETS: Tuple[str, ...] = ("kick", "ember", "gold", "ice", "violet")

# merge_key -> the closed-table noun a plank / plate may print (§2.4). Nothing here is a chatter's word.
NOUNS: Dict[str, str] = {
    "lantern": "a lantern", "banner": "a banner", "garden": "a garden", "flowerbed": "a flowerbed", "trees": "trees",
    "stone_ring": "a stone ring", "bench_stones": "a bench",
    "keep": "a castle", "bridge": "a bridge", "well": "a well", "hall": "a hall", "plaza": "a plaza", "harbour": "a harbour",
    "weather:rain": "rain", "weather:fog": "fog", "weather:wind": "wind", "weather:clear": "clear skies",
    "audio_pattern:music": "music", "bonfire:bonfire": "a bonfire",
    "camp": "a tent", "path": "a path",
    "mechanic": "an idea",
}
# the `try:` tail of a refusal rotates three of these six (§2.4)
TRY_NOUNS: Tuple[str, ...] = ("a lantern", "a banner", "trees", "a garden", "a flowerbed", "a bench")

# ---------------------------------------------------------------------------- recipes (tier 1, DATA over the closed kit)
# part = (fn, args, dx, dy): fn is `module.function` in the §2.3 allowlist; args are literal or one of the closed
# tokens the scene resolves at draw time: "owner" (the owner's colour / hue variant), "rule" (lit by lit_rule),
# "wind" (nature.wind.atlas_phase(now), <= 1 Hz), "season" (the current season float), "sun" (the sun tuple).
# dx, dy are cells from the site cell. No part carries moves / speed / path / frames / rate (§5.2).
FN_ALLOWLIST: Dict[str, Dict[str, Tuple[int, int]]] = {           # fn -> {int arg: (lo, hi)}; honesty.py holds the gate copy
    "buildings.garden": {}, "buildings.banner": {}, "buildings.lantern": {},
    "props.tree": {"age": (0, 2)}, "props.bush": {}, "props.flowers": {}, "props.stone": {}, "props.cairn": {"n": (1, 5)},
}
LIT_RULES: Tuple[str, ...] = ("owner_here", "anyone_here", "never")
FORBIDDEN_PART_FIELDS: Tuple[str, ...] = ("moves", "speed", "path", "frames", "rate")
_RING8 = [(round(4 * math.cos(a * math.pi / 4), 1), round(4 * math.sin(a * math.pi / 4), 1)) for a in range(8)]
RECIPES: Dict[str, Dict[str, Any]] = {
    "lantern": {"parts": [("buildings.lantern", {"lit": "rule"}, 0, 0)],
                "footprint": (1, 1), "caster_h": 3, "lit_rule": "owner_here",
                "site": {"from": "camp", "dist": (5, 7)}},
    "banner": {"parts": [("buildings.banner", {"colour": "owner", "phase": "wind"}, 0, 0)],
               "footprint": (1, 1), "caster_h": 3, "lit_rule": "never",
               "site": {"from": "camp", "dist": (4, 6)}},
    "garden": {"parts": [("buildings.garden", {"colour": "owner"}, 0, 0)],
               "footprint": (1, 1), "caster_h": 1, "lit_rule": "never",
               "site": {"from": "camp", "dist": (5, 7)}},
    "flowerbed": {"parts": [("props.flowers", {"variant": "owner", "wind": "wind"}, dx, dy)
                            for dx, dy in ((-1.0, 0.0), (-0.5, -0.4), (0.0, -0.6), (0.5, -0.4), (1.0, 0.0))],
                  "footprint": (2, 1), "caster_h": 0, "lit_rule": "never",
                  "site": {"from": "camp", "dist": (5, 7)}},
    "trees": {"parts": [("props.tree", {"age": 1, "variant": i, "wind": "wind", "season": "season"}, dx, dy)
                        for i, (dx, dy) in enumerate(((-1, 0), (1, -1), (0, 1)))],
              "footprint": (3, 2), "caster_h": 3, "lit_rule": "never",
              "site": {"from": "camp", "dist": (10, 16), "never_trail": True}},
    "stone_ring": {"parts": [("props.stone", {"variant": i % 3}, dx, dy) for i, (dx, dy) in enumerate(_RING8)],
                   "footprint": (3, 3), "caster_h": 1, "lit_rule": "never",
                   "site": {"from": "moot", "dist": (18, 26), "fallback": "camp"}},
    "bench_stones": {"parts": [("props.stone", {"variant": 2}, -0.5, 0), ("props.stone", {"variant": 2}, 0.5, 0)],
                     "footprint": (2, 1), "caster_h": 1, "lit_rule": "never",
                     "site": {"from": "camp", "dist": (4, 6), "facing": "moot"}},
}
# tier 3: project slug -> the age whose build raises it (AGES §2.3 contents); a slug with no age is a Century wish slot
AGE_PROJECTS: Dict[str, int] = {"well": 2, "plaza": 3, "bridge": 3, "hall": 4, "keep": 4, "harbour": 5}

# ---------------------------------------------------------------------------- caps (§0.2 row 17) and pacing
CAPS: Dict[str, Any] = {
    "first_free": True,                 # a person's FIRST placed thing is never refused by the age cap
    "per_session": 1,                   # then one placed thing per session
    "lifetime_base": 2, "lifetime_per_camp_tier": 1,     # lifetime = 2 + camp tier
    "age_total": {0: 12, 1: 30, 2: 80, 3: 200, 4: 500},  # beyond first items, per age
    "century_step": 120,                # + 120 per Century (age 5, 6, ...)
    "open_papers": 1,                   # one open paper per person on the post
}
PLACE_EVERY_S = 90.0
RAISE_S = 20.0
PLACED_GAP = 6
RING_WIDEN = 4                      # place(): one wider ring past the recipe's band when the band is full
CAMP_GAP = 12
MARK_GAP = 4
MOOT_GREEN_R = 16
REFUSE_COOLDOWN_S = 30.0
MAP_W, MAP_H, EDGE_MARGIN = 960, 440, 12       # land.py / terrain.py constants, repeated for the pure fallback


def age_total_cap(age: int) -> int:
    """Placed things the age admits beyond everyone's first (ages 0-4 from the table, +120 per Century)."""
    a = max(0, int(age))
    tbl = CAPS["age_total"]
    top = max(tbl)
    if a in tbl:
        return int(tbl[a])
    return int(tbl[top]) + int(CAPS["century_step"]) * (a - top)


def lifetime_cap(camp_tier: int) -> int:
    return int(CAPS["lifetime_base"]) + int(CAPS["lifetime_per_camp_tier"]) * max(0, int(camp_tier))


def cap_check(person_placed: int, person_session: int, age_placed: int, age: int, camp_tier: int) -> Tuple[bool, str]:
    """(ok, reason). Counts are len()s the scene derives from placed[]: this person's rows, their rows this session,
    the age's rows beyond first items. The first item is never refused by the age cap (§0.2 row 17)."""
    if person_placed == 0 and CAPS["first_free"]:
        return True, "first"
    if person_session >= int(CAPS["per_session"]):
        return False, "session"
    if person_placed >= lifetime_cap(camp_tier):
        return False, "lifetime"
    if age_placed >= age_total_cap(age):
        return False, "age"
    return True, "ok"


# ---------------------------------------------------------------------------- copy (closed templates; the self-test runs
# every one through compositor.banned_copy_hits). The panel prefixes `@name · ` itself; `{noun}` is a NOUNS value.
REFUSE_COPY: Dict[str, str] = {
    "animate": "no dogs here · try: {a} · {b} · {c}",
    "destructive": "nothing here comes down · try: {a} · {b}",
}
PLANK_TEMPLATES: Dict[str, str] = {
    "wish": "@{name}'s wish is pinned · {noun} · {n} pinned",
    "wish_nonoun": "@{name}'s wish is pinned · {n} pinned",
    "plus": "+1 for {noun}",
    "have_camp": "@{name} · your tent grows as you stay · {days} days here",
    "have_path": "@{name} · paths wear where you walk · try: go river",
    "placed": "@{name}'s {noun} rises",
    "stands": "{noun} stands · @{name}",
    "return_stands": "your {bare} stands",
}
PLATE_TEMPLATES: Dict[str, str] = {
    "wished": "wished: {noun} · @{name} +{n}",
    "wished_one": "wished: {noun} · @{name}",
    "wished_nonoun": "wished · @{name} · today",
    "plaque": "{bare} · {names} · since {date}",
    "plaque_more": "{bare} · {names} and {n} more · since {date}",
    "ask": "{noun} · {n} ask",
    "project_clause": "{noun} · {n} ask",
}


def refuse_copy(kind: str, rot: int = 0) -> str:
    """One refusal line (without the `@name · ` prefix); `rot` rotates the `try:` tail through TRY_NOUNS."""
    tpl = REFUSE_COPY.get(kind) or REFUSE_COPY["destructive"]
    n = len(TRY_NOUNS)
    r = int(rot) % n
    return tpl.format(a=TRY_NOUNS[r], b=TRY_NOUNS[(r + 1) % n], c=TRY_NOUNS[(r + 2) % n])


def bare_noun(noun: str) -> str:
    """`a lantern` -> `lantern` for plaque / return forms (`your lantern stands`)."""
    for art in ("an ", "a "):
        if noun.startswith(art):
            return noun[len(art):]
    return noun


# ---------------------------------------------------------------------------- classification
_TOKEN_RE = re.compile(r"[a-z][a-z']*")
_AT_RE = re.compile(r"@[^\s·]+")


def tokens(text: str) -> List[str]:
    """Lower-cased word tokens with @names stripped and `!cmd` reduced to its word (`!theme kick` -> theme kick)."""
    low = _AT_RE.sub(" ", str(text or "").lower())
    return _TOKEN_RE.findall(low)


def canon(tok: str) -> str:
    return SYNONYMS.get(tok, tok)


def head_of(toks: Sequence[str]) -> Optional[str]:
    """The first content token when it is a WISH_HEAD (§2.1 b: the first non-stop token, or the one after
    `can we / could we / let's / please`)."""
    for t in toks:
        if t in STOP_WORDS:
            continue
        return t if t in WISH_HEADS else None
    return None


def content_tokens(toks: Sequence[str], skip: Iterable[str] = ()) -> List[str]:
    sk = set(skip)
    return [t for t in toks if t not in STOP_WORDS and t not in sk]


def _first_match(canons: Sequence[str], table: Dict[str, Any], toks: Sequence[str]) -> Optional[str]:
    """The first canonical stem in `table`. `well` counts only after a determiner or under a head (`well done`,
    `well, ...` are not wishes)."""
    for i, c in enumerate(canons):
        if c not in table:
            continue
        if c == "well":
            prev = toks[i - 1] if i > 0 else ""
            if prev not in NOUN_ONLY_AFTER and head_of(toks) is None:
                continue
        return c
    return None


def _refusal(canons: Sequence[str], toks: Sequence[str], outside: bool) -> Optional[str]:
    for i, c in enumerate(canons):
        if c in REFUSE_WORDS["animate"]:
            if c in ("fish", "pet"):
                prev = toks[i - 1] if i > 0 else ""
                if prev not in NOUN_ONLY_AFTER:
                    continue
            return "animate"
    if not outside:
        for c in canons:
            if c in REFUSE_WORDS["destructive"]:
                return "destructive"
    return None


def classify(text: str, verb: Optional[str] = None, hint: Optional[str] = None, kind: str = "plain") -> Wish:
    """Class one wish-tagged record (§2.2). `verb` is parse_verb's result (a parsed verb never reaches the pipeline:
    such a record classes `silent` with param `verb`); `hint` is hint_for's result (informational; the bridge already
    drew it); `kind` is `plain` or `idea` (an `!idea` that matches nothing above is a `mechanic`, never `unknown`)."""
    if verb:
        return Wish("silent", None, "verb", None, "verb", None)
    toks = tokens(text)
    canons = [canon(t) for t in toks]
    is_idea = (kind or "plain") == "idea"
    head = head_of(toks)
    outside = any(c in SILENT_WORDS["outside"] for c in canons)
    clock = any(c in SILENT_WORDS["clock"] for c in canons)
    theme = any(c in SILENT_WORDS["theme"] for c in canons) or (toks[:1] == ["theme"])

    # 1. refusals (scoped: destructive words beside an outside word are a comment on the stream, §docstring)
    r = _refusal(canons, toks, outside)
    if r is not None:
        return Wish("refuse:%s" % r, None, "refuse:%s" % r, None, None, None)
    # 2. have_it: a camp exists at hatch, paths wear where you walk (answered from records, no paper)
    h = _first_match(canons, HAVE_IT_WORDS, toks)
    if h is not None:
        mk = HAVE_IT_WORDS[h]
        return Wish("have_it", NOUNS.get(mk), mk, None, None, None)
    # 3. a mechanic verb in head position says what to do with the noun (`cut some trees`, `dig a hole`)
    first = content_tokens(toks)
    if first and canon(first[0]) in MECHANIC_VERBS:
        mk = "mechanic:%s" % canon(first[0])
        return Wish("mechanic", NOUNS["mechanic"], mk, None, None, None)
    # 4. recipe (flowerbed only when no plant verb parsed: `verb` is None here by construction)
    c = _first_match(canons, RECIPE_WORDS, toks)
    if c is not None:
        slug = RECIPE_WORDS[c]
        return Wish("recipe:%s" % slug, NOUNS.get(slug), slug, slug, None, None)
    # 5. project
    c = _first_match(canons, PROJECT_WORDS, toks)
    if c is not None:
        slug = PROJECT_WORDS[c]
        return Wish("project:%s" % slug, NOUNS.get(slug), slug, None, None, None)
    # 6. menu (a real MENU param and value)
    c = _first_match(canons, MENU_WORDS, toks)
    if c is not None:
        param, value = MENU_WORDS[c]
        mk = "%s:%s" % (param, c)
        return Wish("menu:%s:%s" % (param, value), NOUNS.get(mk, c), mk, None, param, value)
    # 7. mechanic words anywhere
    for c in canons:
        if c in MECHANIC_WORDS:
            return Wish("mechanic", NOUNS["mechanic"], "mechanic:%s" % c, None, None, None)
    # 8. `build` / `make` / `raise` with nothing the kit knows: an ask to raise something (promoted as a mechanic)
    if head in BUILD_HEADS:
        rest = content_tokens(toks, skip=(head,))
        word = canon(rest[0]) if rest else head
        return Wish("mechanic", NOUNS["mechanic"], "mechanic:%s" % word, None, None, None)
    # 9. silent groups: theme (the `try: !theme` hint already fired), clock, outside
    if theme:
        return Wish("silent", None, "theme", None, "theme", None)
    if clock:
        return Wish("silent", None, "clock", None, "clock", None)
    if outside:
        return Wish("silent", None, "outside", None, "outside", None)
    # 10. an idea that matched nothing above is an ask for the orchestrator
    if is_idea:
        rest = content_tokens(toks, skip=(head,) if head else ())
        word = canon(rest[0]) if rest else "idea"
        return Wish("mechanic", NOUNS["mechanic"], "mechanic:%s" % word, None, None, None)
    # 11. a head with a noun no table knows
    if head is not None:
        rest = content_tokens(toks, skip=(head,))
        word = canon(rest[0]) if rest else head
        return Wish("unknown", None, word, None, None, None)
    # 12. no head, no noun: the bubble is the ack
    return Wish("silent", None, "chat", None, "chat", None)


def merge_key(text: str, verb: Optional[str] = None, hint: Optional[str] = None, kind: str = "plain") -> str:
    """The cluster key (§2.5): the classifier slug, or for `unknown` the first content token after the head, singularised."""
    return classify(text, verb, hint, kind).merge_key


def noun_for(merge_key_: str, cls: Optional[str] = None) -> Optional[str]:
    """The closed-table noun for a cluster, or None (an `unknown` cluster has no noun; the plank omits it)."""
    if merge_key_ in NOUNS:
        return NOUNS[merge_key_]
    if (cls or "").startswith("mechanic") or merge_key_.startswith("mechanic:"):
        return NOUNS["mechanic"]
    return None


# ---------------------------------------------------------------------------- placement geometry (§2.3 tier 1)
def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def _in_bounds(x: int, y: int, w: int, h: int) -> bool:
    return EDGE_MARGIN <= x < w - EDGE_MARGIN and EDGE_MARGIN <= y < h - EDGE_MARGIN


def _cell_ok(x: int, y: int, land, terrain, camps: Sequence[Tuple[float, float]], placed: Sequence[Tuple[float, float]],
             moot: Optional[Tuple[float, float]], never_trail: bool) -> bool:
    """One cell against the §2.3 rules: passable, not water, not a trail, not the Moot green, MARK_GAP from anyone's
    mark, PLACED_GAP from other placed items, CAMP_GAP from other camps. Duck-typed over land / terrain so the pure
    fallback (both None) still holds the gaps and the bounds."""
    w = int(getattr(terrain, "w", MAP_W) or MAP_W)
    h = int(getattr(terrain, "h", MAP_H) or MAP_H)
    if not _in_bounds(x, y, w, h):
        return False
    if terrain is not None:
        try:
            if not terrain.is_passable(x, y):
                return False
            water = getattr(terrain, "water", None)
            if water is not None and bool(water[y, x]):
                return False
        except Exception:
            return False
    if land is not None:
        try:
            if getattr(land, "passable", None) is not None and not bool(land.passable[y, x]):
                return False
            if getattr(land, "water", None) is not None and bool(land.water[y, x]):
                return False
            if hasattr(land, "is_trail") and land.is_trail(x, y):
                return False
            if hasattr(land, "on_green") and land.on_green(x, y):
                return False
            if hasattr(land, "mark_near") and land.mark_near(x, y, MARK_GAP) is not None:
                return False
        except Exception:
            return False
    elif moot is not None and _dist(x, y, moot[0], moot[1]) < MOOT_GREEN_R:
        return False
    if never_trail and terrain is not None:
        tr = getattr(terrain, "trail", None)
        try:
            if tr is not None and bool(tr[y, x]):
                return False
        except Exception:
            pass
    for (cx, cy) in camps:
        if _dist(x, y, cx, cy) < CAMP_GAP:
            return False
    for (px, py) in placed:
        if _dist(x, y, px, py) < PLACED_GAP:
            return False
    return True


def place(recipe: str, owner_camp_xy: Tuple[float, float], land=None, terrain=None, placed: Sequence[Any] = (),
          moot_xy: Optional[Tuple[float, float]] = None, seed: int = 0) -> Optional[Tuple[int, int]]:
    """The site for one recipe: the owner's camp door + a ring search at the recipe's distance band over
    `terrain.nearest_passable` with the land's mark rules; None when no cell in the band passes. `placed` is
    world.placed[] rows (dicts with x, y) or (x, y) pairs; other camps come from `land.camps()` when a land is given.
    Pure: no writes, no imports of the locked modules; deterministic for one (recipe, camp, seed)."""
    spec = RECIPES.get(recipe)
    if spec is None or owner_camp_xy is None:
        return None
    site = spec["site"]
    cx, cy = float(owner_camp_xy[0]), float(owner_camp_xy[1])
    moot = None
    if terrain is not None and getattr(terrain, "site", None):
        moot = (float(terrain.site[0]), float(terrain.site[1]))
    elif land is not None and getattr(land, "moot", None):
        moot = (float(land.moot[0]), float(land.moot[1]))
    elif moot_xy is not None:
        moot = (float(moot_xy[0]), float(moot_xy[1]))
    # the owner's camp door: the cell below the hut, snapped to passable ground
    door = (int(round(cx)), int(round(cy)) + 3)
    if terrain is not None and hasattr(terrain, "nearest_passable"):
        try:
            door = tuple(int(v) for v in terrain.nearest_passable(door[0], door[1]))
        except Exception:
            pass
    camps: List[Tuple[float, float]] = []
    if land is not None and hasattr(land, "camps"):
        try:
            camps = [(float(c["x"]), float(c["y"])) for c in land.camps()
                     if _dist(c["x"], c["y"], cx, cy) > 0.5]
        except Exception:
            camps = []
    pl: List[Tuple[float, float]] = []
    for p in placed or ():
        try:
            if isinstance(p, dict):
                pl.append((float(p["x"]), float(p["y"])))
            else:
                pl.append((float(p[0]), float(p[1])))
        except Exception:
            continue
    fw, fh = spec["footprint"]
    never_trail = bool(site.get("never_trail"))
    origins: List[Tuple[Tuple[int, int], Tuple[int, int]]] = []
    if site.get("from") == "moot" and moot is not None:
        origins.append(((int(round(moot[0])), int(round(moot[1]))), site["dist"]))
        if site.get("fallback") == "camp":
            origins.append((door, (5, 9)))
    else:
        origins.append((door, site["dist"]))
    facing = moot if site.get("facing") == "moot" and moot is not None else None
    # the ring search walks outward: the recipe's band first, then one wider ring (+RING_WIDEN cells) so a plot with
    # several placed things at the door still finds ground; beyond that the item waits (None) rather than drifts away
    widened = []
    for origin, (dmin, dmax) in origins:
        widened.append((origin, (dmin, dmax)))
        widened.append((origin, (dmax + 1, dmax + RING_WIDEN)))
    for origin, (dmin, dmax) in widened:
        ox, oy = origin
        cands: List[Tuple[float, float, int, int]] = []
        mid = (dmin + dmax) / 2.0
        for dx in range(-dmax, dmax + 1):
            for dy in range(-dmax, dmax + 1):
                d = math.hypot(dx, dy)
                if d < dmin or d > dmax:
                    continue
                x, y = ox + dx, oy + dy
                k1 = abs(d - mid)
                k2 = _dist(x, y, facing[0], facing[1]) if facing is not None else ((x * 73856093) ^ (y * 19349663) ^ int(seed)) % 997
                cands.append((k1, k2, x, y))
        cands.sort()
        for _, _, x, y in cands:
            ok = True
            for fx in range(fw):
                for fy in range(fh):
                    if not _cell_ok(x + fx - fw // 2, y + fy - fh // 2, land, terrain, camps, pl, moot, never_trail):
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                return (int(x), int(y))
    return None


# ---------------------------------------------------------------------------- introspection for the validator / self-test
def part_fn(fn: str):
    """Resolve `module.function` from the art kit lazily (`buildings.lantern` -> the `lantern` kind through render, or
    the module attribute). Returns a callable or None; never raises."""
    try:
        mod_name, name = fn.split(".", 1)
    except ValueError:
        return None
    try:
        if mod_name == "buildings":
            from stream.world.art import buildings as b
            if name in getattr(b, "KINDS", ()):
                return lambda **kw: b.render(name, **kw)
            return getattr(b, name, None)
        if mod_name == "props":
            from stream.world.art import props as p
            return getattr(p, name, None)
    except Exception:
        return None
    return None


def recipe_problems(slug: str) -> List[str]:
    """Static checks a recipe must pass (the honesty validator repeats them with the land): fn in the allowlist, int
    args in range, no motion field, colour `owner` or a name, lit_rule closed, footprint >= 1x1."""
    out: List[str] = []
    spec = RECIPES.get(slug)
    if spec is None:
        return ["no recipe %r" % slug]
    if spec.get("lit_rule") not in LIT_RULES:
        out.append("%s: lit_rule %r" % (slug, spec.get("lit_rule")))
    fw, fh = spec.get("footprint", (0, 0))
    if fw < 1 or fh < 1:
        out.append("%s: footprint %r" % (slug, spec.get("footprint")))
    for part in spec.get("parts", []):
        fn, args, dx, dy = part
        if fn not in FN_ALLOWLIST:
            out.append("%s: fn %r not in the allowlist" % (slug, fn))
            continue
        for k in FORBIDDEN_PART_FIELDS:
            if k in args:
                out.append("%s: part %s carries %r" % (slug, fn, k))
        for k, (lo, hi) in FN_ALLOWLIST[fn].items():
            v = args.get(k)
            if not isinstance(v, int) or v < lo or v > hi:
                out.append("%s: %s.%s=%r outside %d..%d" % (slug, fn, k, v, lo, hi))
        col = args.get("colour")
        if col is not None and not isinstance(col, str):
            out.append("%s: %s colour %r is not a name" % (slug, fn, col))
        if not (isinstance(dx, (int, float)) and isinstance(dy, (int, float))):
            out.append("%s: %s offset %r" % (slug, fn, (dx, dy)))
    return out


# ---------------------------------------------------------------------------- self-test
# The live transcript's 41 plain lines and 10 idea texts (understand-map 'live data', chat.jsonl 09-24..09-26), copied
# as literals: no chatter names, no run-dir writes. Expected classes follow §2.2's reading of the same lines.
_LIVE_PLAIN: Tuple[str, ...] = (
    "!theme ember", "change the sound", "!theme gold", "wtf is this", "Whats happening right now",
    "strange ass stream", "!help", "Commit this all to the repo", "hello", "dig", "dig", "dig", "dig",
    "What are the keepers? What do they do?", "Change the colour to kick colours", "theme kick", "!theme kick",
    "dig", "dig", "dig", "Let's change the music. Give it an actual techno beat", "Climb out of the cave", "test",
    "Build a hut here", "zoom outb", "cut some trees", "build something", "Build a castle in the field there",
    "hello", "say hello to @atleastonce", "wak south", "hey", "Can I become a settler too?", "of course", "hello",
    "bbbbb", "surely you don't need the space at the bottom of the screen for grey boxes", "dig a hole",
    "build something", "test", "nuke",
)
_LIVE_IDEAS: Tuple[str, ...] = (
    "change everything. Make it all random", "build something completely new. The whole thing",
    "build a pixel art bot that responds", "build a little pixel dude on screen", "go out of the cave",
    "make the cave have gems", "zoom out", "turn this to night", "improve the art style :)",
    "remove the large grey area of the screen. fill the soece with the world instead",
)
_EXPECT: Dict[str, str] = {
    "Build a castle in the field there": "project:keep", "Build a hut here": "have_it",
    "Let's change the music. Give it an actual techno beat": "menu:audio_pattern:pulse_hats",
    "theme kick": "silent", "!theme kick": "silent", "cut some trees": "mechanic", "build something": "mechanic",
    "dig": "mechanic", "dig a hole": "mechanic", "Commit this all to the repo": "silent", "zoom outb": "silent",
    "hello": "silent", "wtf is this": "silent", "Whats happening right now": "silent", "!help": "silent",
    "Change the colour to kick colours": "silent",
}
_EXPECT_IDEAS: Dict[str, str] = {
    "zoom out": "silent", "turn this to night": "silent", "improve the art style :)": "silent",
    "make the cave have gems": "mechanic", "build a little pixel dude on screen": "mechanic",
    "build a pixel art bot that responds": "mechanic",
}


def _banned_checker():
    """compositor.banned_copy_hits when importable (the owner's rule as a function), else the same three patterns copied
    by value; returns (fn, source_label)."""
    try:
        from stream import compositor as C
        fn = getattr(C, "banned_copy_hits", None) or C.Compositor.banned_copy_hits     # a staticmethod on Compositor (L798)
        assert C.BANNED_COPY and C.BANNED_DAY_RE and C.BANNED_VERSION_RE
        return fn, "compositor.Compositor.banned_copy_hits (BANNED_COPY %d tokens + BANNED_DAY_RE + BANNED_VERSION_RE)" % len(C.BANNED_COPY)
    except Exception as e:      # pragma: no cover - the spine may be mid-edit; the patterns are then local copies
        banned = ("ai", "keeper", "keepers", "on duty", "build", "builds", "show", "live", "version", "fps", "ms",
                  "viewer", "viewers", "watching", "camera", "mic", "fake", "honest", "honesty", "surveying", "awake",
                  "longgrass")
        bre = re.compile(r"(?<![a-z0-9_])(?:%s)(?![a-z0-9_])" % "|".join(re.escape(t) for t in banned))
        vre = re.compile(r"(?<![a-z0-9_])v\d+\.\d+")
        dre = re.compile(r"(?<![a-z0-9_])day \d+")

        def local(strings):
            hits = []
            for s in strings:
                low = _AT_RE.sub("", str(s or "")).lower()
                if bre.search(low) or vre.search(low) or dre.search(low):
                    hits.append(s)
            return hits
        return local, "local copy of the patterns (compositor import failed: %s)" % e


def _self_test(verbose: bool = True) -> bool:
    ok = True

    def gate(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        print("  [%s] %s%s" % ("PASS" if passed else "FAIL", name, (" · " + detail) if detail else ""))

    print("registry --self-test")
    # 1. the live transcript (41 plain + 10 ideas): histogram + the §2.2 named lines
    hist: collections.Counter = collections.Counter()
    for t in _LIVE_PLAIN:
        w = classify(t)
        hist[w.cls.split(":")[0] if not w.cls.startswith("menu") else "menu"] += 1
    gate("41 live plain lines", len(_LIVE_PLAIN) == 41, "n=%d" % len(_LIVE_PLAIN))
    print("    plain histogram: %s" % dict(sorted(hist.items())))
    for t, exp in _EXPECT.items():
        got = classify(t).cls
        gate("plain %r -> %s" % (t, exp), got == exp, "got %s" % got)
    ihist: collections.Counter = collections.Counter()
    for t in _LIVE_IDEAS:
        w = classify(t, kind="idea")
        ihist[w.cls.split(":")[0]] += 1
    gate("10 live idea texts", len(_LIVE_IDEAS) == 10, "n=%d" % len(_LIVE_IDEAS))
    print("    idea histogram: %s" % dict(sorted(ihist.items())))
    for t, exp in _EXPECT_IDEAS.items():
        got = classify(t, kind="idea").cls
        gate("idea %r -> %s" % (t, exp), got == exp, "got %s" % got)
    gate("no idea classes unknown", ihist.get("unknown", 0) == 0)
    # the ledger's silent rows still cluster: every silent row has a group in `param`
    gate("silent rows carry a group", all(classify(t).param in ("outside", "clock", "theme", "chat")
                                          for t in _LIVE_PLAIN if classify(t).cls == "silent"))

    # 2. the assignment's named cases
    cases = (("good night", "silent"), ("hello there", "silent"), ("wtf is this", "silent"),
             ("I want to go home", "have_it"), ("Build a hut here", "have_it"),
             ("Build a castle in the field there", "project:keep"), ("cut some trees", "mechanic"),
             ("a lantern", "recipe:lantern"), ("can we have a dog", "refuse:animate"),
             ("burn it all down", "refuse:destructive"), ("put a flag by my tent", "have_it"),
             ("give us fog", "menu:weather:fog"), ("more trees please", "recipe:trees"),
             ("a stone circle", "recipe:stone_ring"), ("build a bridge over the river", "project:bridge"),
             ("bigger mountains please", "unknown"), ("well done", "silent"), ("build a well", "project:well"),
             ("pet the dog", "refuse:animate"), ("go fishing", "mechanic"), ("a fish pond", "refuse:animate"),
             ("!idea remove the hud", "silent"))
    for t, exp in cases:
        w = classify(t)
        gate("%r -> %s" % (t, exp), w.cls == exp, "got %s (noun %r, key %r)" % (w.cls, w.noun, w.merge_key))
    gate("have_it never carries a recipe", classify("I want to go home").recipe is None)
    gate("a verb-parsed record classes silent:verb", classify("go north", verb="go").param == "verb")
    gate("merge_key: lamp -> lantern", merge_key("a lamp for my camp") == "lantern")
    gate("merge_key: rocks -> stones -> stone_ring", merge_key("some rocks in a ring") == "stone_ring")
    gate("merge_key: techno|beat|song -> music", len({merge_key("techno please"), merge_key("a beat"), merge_key("a song")}) == 1)
    gate("merge_key: unknown = first content token", merge_key("Climb out of the cave") == "cave")
    gate("merge_key: two `build something` cluster", merge_key("build something") == merge_key("Build something big"))
    gate("SYNONYMS >= 60 aliases", len(SYNONYMS) >= 60, "n=%d" % len(SYNONYMS))
    gate("every SYNONYM target is a known stem", all(
        c in RECIPE_WORDS or c in PROJECT_WORDS or c in MENU_WORDS or c in MECHANIC_WORDS or c in HAVE_IT_WORDS
        or any(c in v for v in REFUSE_WORDS.values()) or any(c in v for v in SILENT_WORDS.values())
        for c in set(SYNONYMS.values())), "unknown: %s" % sorted(
            c for c in set(SYNONYMS.values()) if not (
                c in RECIPE_WORDS or c in PROJECT_WORDS or c in MENU_WORDS or c in MECHANIC_WORDS or c in HAVE_IT_WORDS
                or any(c in v for v in REFUSE_WORDS.values()) or any(c in v for v in SILENT_WORDS.values()))))
    gate("WISH_HEADS has the 19 spec heads", len(WISH_HEADS) == 19 and "build" in WISH_HEADS and "should" in WISH_HEADS)

    # 3. copy: every REFUSE_COPY rotation, NOUNS entry and template rendering passes the banned-copy patterns
    check, src = _banned_checker()
    print("    copy check: %s" % src)
    strings: List[str] = []
    for kind in REFUSE_COPY:
        for rot in range(len(TRY_NOUNS)):
            strings.append("@kai · " + refuse_copy(kind, rot))
    strings.extend(NOUNS.values())
    strings.extend(TRY_NOUNS)
    for n in NOUNS.values():
        strings.append(PLANK_TEMPLATES["wish"].format(name="kai", noun=n, n=4))
        strings.append(PLANK_TEMPLATES["plus"].format(noun=n))
        strings.append(PLANK_TEMPLATES["placed"].format(name="kai", noun=n))
        strings.append(PLANK_TEMPLATES["stands"].format(name="kai", noun=n))
        strings.append(PLANK_TEMPLATES["return_stands"].format(bare=bare_noun(n)))
        strings.append(PLATE_TEMPLATES["wished"].format(noun=n, name="kai", n=3))
        strings.append(PLATE_TEMPLATES["wished_one"].format(noun=n, name="kai"))
        strings.append(PLATE_TEMPLATES["plaque"].format(bare=bare_noun(n), names="@kai @jo @sami", date="3 Oct"))
        strings.append(PLATE_TEMPLATES["plaque_more"].format(bare=bare_noun(n), names="@kai @jo @sami", n=9, date="3 Oct"))
        strings.append(PLATE_TEMPLATES["ask"].format(noun=n, n=12))
        strings.append(PLATE_TEMPLATES["project_clause"].format(noun=n, n=12))
    strings.append(PLANK_TEMPLATES["wish_nonoun"].format(name="kai", n=4))
    strings.append(PLANK_TEMPLATES["have_camp"].format(name="kai", days=2))
    strings.append(PLANK_TEMPLATES["have_path"].format(name="kai"))
    strings.append(PLATE_TEMPLATES["wished_nonoun"].format(name="kai"))
    hits = check(strings)
    gate("%d copy strings, 0 banned hits" % len(strings), not hits, "hits: %s" % hits[:5])
    gate("no template quotes a sentence ({text} never a field)", all("{text}" not in t for t in
                                                                     list(PLANK_TEMPLATES.values()) + list(PLATE_TEMPLATES.values()) + list(REFUSE_COPY.values())))
    gate("refusal copy is sign-short (<= 60 chars, no rule recital)", all(len(refuse_copy(k, r)) <= 60 for k in REFUSE_COPY for r in range(6)))

    # 4. recipes: 7 slugs, every part fn in the §2.3 allowlist, exists in the kit, args in range, no motion field
    gate("7 recipes", set(RECIPES) == {"lantern", "banner", "garden", "flowerbed", "trees", "stone_ring", "bench_stones"})
    probs = [p for s in RECIPES for p in recipe_problems(s)]
    gate("recipe static checks", not probs, "; ".join(probs[:4]))
    allow = {"buildings.garden", "buildings.banner", "buildings.lantern", "props.tree", "props.bush", "props.flowers",
             "props.stone", "props.cairn"}
    gate("FN_ALLOWLIST == §2.3 allowlist", set(FN_ALLOWLIST) == allow)
    used = sorted({p[0] for s in RECIPES.values() for p in s["parts"]})
    gate("every used fn is allowlisted", all(f in allow for f in used), "used: %s" % used)
    missing = [f for f in FN_ALLOWLIST if part_fn(f) is None]
    gate("every allowlisted fn exists in the art kit", not missing, "missing: %s" % missing)
    denied = ("creatures", "buildings.hut", "buildings.well", "buildings.fence_h", "buildings.fence_v", "props.beacon",
              "props.campfire", "props.waystone")
    gate("no figure / home / fence / fire / beacon part", not any(any(f.startswith(d) for d in denied) for f in used))
    gate("every recipe names a NOUN", all(s in NOUNS for s in RECIPES))
    gate("every project names a NOUN and AGE_PROJECTS", set(AGE_PROJECTS) == set(PROJECT_WORDS.values()) and all(s in NOUNS for s in AGE_PROJECTS))
    gate("every menu key names a NOUN", all(("%s:%s" % (p, c)) in NOUNS for c, (p, v) in MENU_WORDS.items()))

    # 5. caps complete for ages 0-5 (+120 per Century), the first item never refused, the second in one session refused
    caps = [age_total_cap(a) for a in range(6)]
    gate("caps ages 0-5", caps == [12, 30, 80, 200, 500, 620], "%s" % caps)
    gate("caps monotone", all(caps[i] < caps[i + 1] for i in range(5)))
    gate("first item never refused by the age cap", cap_check(0, 0, 10 ** 6, 0, 0)[0])
    gate("second item in one session refused", cap_check(1, 1, 0, 0, 0) == (False, "session"))
    gate("lifetime = 2 + camp tier", lifetime_cap(0) == 2 and lifetime_cap(3) == 5)
    gate("age cap holds beyond first items", cap_check(1, 0, 12, 0, 3) == (False, "age") and cap_check(1, 0, 11, 0, 3)[0])

    # 6. geometry: the pure fallback and, when the terrain imports, the real ring search
    camp = (480, 240)
    for slug in RECIPES:
        xy = place(slug, camp, None, None, placed=[(486, 243)], moot_xy=(400, 200), seed=1)
        d = _dist(xy[0], xy[1], camp[0], camp[1] + 3) if xy else -1
        lo, hi = RECIPES[slug]["site"]["dist"] if RECIPES[slug]["site"]["from"] == "camp" else (5, 9)
        m = _dist(xy[0], xy[1], 400, 200) if xy else -1
        okd = (lo - 2 <= d <= hi + 2) if RECIPES[slug]["site"]["from"] == "camp" else (17 <= m <= 27 or lo - 2 <= d <= hi + 2)
        gate("pure place(%s) in band" % slug, xy is not None and okd, "xy=%s d=%.1f" % (xy, d))
        gate("pure place(%s) holds PLACED_GAP" % slug, xy is not None and _dist(xy[0], xy[1], 486, 243) >= PLACED_GAP)
    try:
        from stream.world import terrain as T
        terr = T.generate(4471)
    except Exception as e:
        terr = None
        print("    terrain import skipped: %s" % e)
    if terr is not None:
        sx, sy = terr.site
        camp2 = terr.nearest_passable(sx + 30, sy + 8)
        for slug in RECIPES:
            xy = place(slug, camp2, None, terr, seed=2)
            good = xy is not None and terr.is_passable(*xy) and not bool(terr.water[xy[1], xy[0]]) \
                and _dist(xy[0], xy[1], sx, sy) >= MOOT_GREEN_R
            gate("terrain place(%s) passable, dry, off the green" % slug, good, "xy=%s" % (xy,))
        # one person's plot at the lifetime cap of a tier-3 camp (5 items): every later item keeps PLACED_GAP
        placed_rows: List[Dict[str, Any]] = []
        for slug in ("lantern", "banner", "garden", "flowerbed", "bench_stones"):
            xy = place(slug, camp2, None, terr, placed=placed_rows, seed=2)
            gate("terrain plot %s beside %d placed" % (slug, len(placed_rows)), xy is not None, "xy=%s" % (xy,))
            if xy:
                placed_rows.append({"x": xy[0], "y": xy[1]})
        gate("placed items hold PLACED_GAP", all(_dist(a["x"], a["y"], b["x"], b["y"]) >= PLACED_GAP
                                                 for i, a in enumerate(placed_rows) for b in placed_rows[i + 1:]))
        gate("a water camp returns None or dry ground", place("lantern", (2, 2), None, terr) is None or
             terr.is_passable(*place("lantern", (2, 2), None, terr)))
    gate("unknown recipe -> None", place("castle", camp) is None)

    # 7. no locked module was imported by this module
    locked = ("stream.world.behaviour", "stream.world.honesty", "stream.world.state", "stream.scenes.steading",
              "stream.panels.world", "stream.chat_bridge")
    import_leak = [m for m in locked if m in sys.modules and not _LOCKED_AT_IMPORT.get(m)]
    print("    (locked modules present after the test, via compositor's own imports: %s)" % import_leak)
    print("registry --self-test: %s" % ("PASS" if ok else "FAIL"))
    return ok


_LOCKED_AT_IMPORT = {m: (m in sys.modules) for m in ("stream.world.behaviour", "stream.world.honesty", "stream.world.state",
                                                    "stream.scenes.steading", "stream.panels.world", "stream.chat_bridge")}

if __name__ == "__main__":   # pragma: no cover
    if "--self-test" in sys.argv:
        sys.exit(0 if _self_test() else 1)
    for t in sys.argv[1:]:
        print(t, "->", classify(t))
