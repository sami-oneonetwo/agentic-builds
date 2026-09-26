"""chat_bridge.py - ChatBridge: the CONCEPT 7 command parser, the CONCEPT 7.1 moderation pipeline and the
WORLD.md section 4 verb parser (the verbs agent's half of the world contract, stream/WORLD_API.md section 6).

The StateStore tails chat.jsonl (both record shapes, de-duped on id) and the compositor hands the
new normalised messages to ChatBridge.ingest() every frame. Nothing from chat reaches a pixel or a
name slot (chat log, platform tallies, plank, founders, ticker) without passing through here.

Pipeline (CONCEPT 7.1, in order, for every record):
  1. 3 s render hold            show_t = t + 3 s; visible() only returns messages past their hold so the
                                filter and a human !hide can beat the render. Verbs land at show_t too.
  2. hidden / paused check      mod.hidden_users (from !hide, !banish, three strikes, state.json) -> the record
                                is ignored entirely (message, vote, idea, verb); !pause freezes the pane
  3. URL strip                  any token with a scheme, www. or a .tld pattern -> "[link]"
  4. non-BMP strip + emotes     astral code points removed, "[emote:123:name]" -> ":name:"
  5. word filter                stream/moderation/blocklist.txt (leet-normalised, whole-word; suffix tolerant
                                for terms >= 5 letters; "n i g g e r" runs re-joined); a hit drops the
                                message AND its vote/idea/verb, increments .dropped and is ONE STRIKE;
                                three strikes in a session burrow the owner's pip (WORLD.md 11.5)
  6. username filter            same list on the username -> "builder #N" everywhere
  7. length caps                120 chars displayed (60 for !idea, 140 for !ask)
  8. per-user render rate       1 rendered line per user per 2 s; excess lines never reach the pane
                                (votes still count, verbs still land, !idea still reaches the RoundEngine)
  9. kill switch                chat.display (!kill / !unkill): visible() -> [] ; panels draw
                                "chat hidden by mod" for every name slot

THE NAME PATH (WORLD.md 11.1-11.2, closes journal 014.1). There is exactly one accessor that turns a chatter
into drawable text: `name_for(key, now)`. It applies the username blocklist ("builder #N") AND the hold: until
the chatter's first record of this run is past its show_t the name is "builder #N" (their real builder number,
nothing about the username). tallies(), recent_votes(), founders, the same-frame vote ack and every mod notice
go through it. The raw-name path (`_voter_name`, `"mod action: hid @%s" % target`) is deleted, not bypassed.
`display_name` on the message dict is the filtered name; consumers see it only through visible() (past the hold).

Verbs (OPENWORLD.md 6: the exact-token rule plus the LEADING-VERB rule; parsed on the trimmed text, case-insensitive):
  A message is a verb when it has no URL, at most MAX_VERB_TOKENS (4) whitespace tokens, its first token
  (optionally `!`-prefixed) is a verb in VERB_SPECS or an alias in VERB_ALIASES (walk/head -> go, light -> fire,
  pitch -> camp, a bare direction word -> go), and after the stop-words `a an the to at my some on` are dropped
  EVERY remaining token is a known object word for that verb (a place, a direction, `@name` where the verb takes
  one, flower|tree|reed, camp|tent|hut|here, fire|hearth). Otherwise it is plain chat. So `plant a flower` ->
  plant flower, `go to the river` -> go river, `light the fire` -> fire, `walk north` -> go north, `home` -> go
  home, while `go away`, `plant based`, `go go go` and any 5+ token sentence do nothing. name/teach keep the
  exact one-word form (a nickname is free text, never an object word): `name Muffin`, never `name @sam`.
  A verb message is still a plain message (kind "plain": it wakes, hops and bubbles) with m["verb"] set to
  {verb, target, arg, form} where form is the canonical reading (`go river`) the plank echoes.
  Table (v0 preview; rate limits per user, checked at ingest so the refusal shows at once):
    go <north|south|east|west|river|ford|moot|fell|wood|shore|marsh|orchard|steading|home|@name>  1 per 5 s
    home (= go home) ; plant [flower|tree|reed] (bare = flower; flowers 3, trees 1, reeds 3 per session) ;
    camp [here|tent|hut] 1 per session ; fire (alias light) 1 per 10 min ; feed/pet [@name] 30 s ;
    gift @name 1 per target per session ; wave/sit/dance 5 s ; name <word> 10 min ; forget.
    sow / harvest / stack / swim / sing / explore / water @name / teach <word> parse (so they never bubble as
    commands elsewhere) and refuse with `<verb> · not yet · try: go river · plant a flower · camp` (v1 / v1.1 / v2 items).
    dig and duck are gone (OPENWORLD 6: nothing to carve or duck under outdoors); they are plain chat now.
  Every refusal is a 4 s AMBER plank notice (level "warn" -> layout COLORS["warn"]) AND a `notice` world event: a
  second person trying never sees nothing happen. Application: at show_t the bridge calls
  world.command(verb, actor, target=, arg=, now=) on the attached scene: go -> ("go", actor, target=key|None,
  arg=place|direction|"home"), plant -> ("plant", actor, arg=kind), camp/fire/wave/sit/dance/forget -> (verb,
  actor); `your pip is not awake yet` is retried for 3 s (the hatch lands a frame after the hold); other
  refusals go to the plank. Any `@word` inside a world reason is scrubbed before the plank (filtered names only).
  feed/pet/gift at a sleeping or absent pip are recorded by the world in care_log and the plank says so
  (`@kai left a berry at @lu's camp`).
  The world is reached by attach_world(scene) (explicit) or discovered from sys.modules (a stream.scenes /
  stream.panels module holding `SCENE`); verbs queue (bounded, 10 s) until a world is present.

Commands (case-insensitive, after moderation):
  A/B/C/!a/!b/!c        trimmed text matches ^!?[abc]$ EXACTLY; 1 vote per user per round, a new letter moves it
  !idea <text>          nominate (arg capped at 60); the RoundEngine dedupes (+N) and enforces 1/user/3 min
  !theme <preset>       one of layout.PRESETS (8); 60 s global cooldown
  !stats / !help        30 s global cooldown each; stats_until = now + 10 s, help_until = now + 20 s
  !ask <question>       arg capped at 140; accepted only while state.ask.enabled
  !hide u / !unhide u / !pause / !resume / !clear     broadcaster or moderator badge
  !banish u / !unbanish u / !rename u                 broadcaster or moderator badge (WORLD.md 4, 11.6):
                        banish = hide + world.banish (record kept in world.json.banished, moss reverted,
                        nickname gone, shield chip via mod_actions); rename strips a nickname
  !kill / !unkill                                     broadcaster only (also the KICK_CHANNEL owner)

Public surface (exact; stream/COMPOSITOR_API.md section 5 + the world hooks):
  ChatBridge(run_dir, log=None, blocklist_path=None, allowlist_path=None)
  .ingest(msgs, now, ctx=None) -> list[msg]   classified + moderated copies of the new messages (pumps verbs)
  .visible(now, n=10) -> list[msg]            moderated, past the hold, newest last; [] when display is off (pumps)
  .pump(now)                                  apply due verbs / mod world ops; idempotent per `now`
  .attach_world(scene) ; .world               the CaveScene (or None); .world_events ; .drain_world_events()
  .name_for(key, now=None) -> str             THE filtered + held name path
  .tallies(now=None) -> {"A": [names], ...}   voters (name_for) in vote order, this round
  .vote_count() -> int ; .recent_votes(n=5, now=None) -> [(name, letter, t)]
  .reset_round(opened_t)                      RoundEngine: keep only votes with t >= opened_t - 1
  .notice(now) -> (text, level) | None ; .help_until ; .stats_until
  .founders -> list[str] ; .builders -> dict ; .builder_n(name) ; .flush(now, force=False)
  .display ; .paused ; .hidden (set: mod hides | burrowed | banished) ; .burrowed {key: reason} ; .banished
  .dropped ; .rate_limited ; .strikes {key: n} ; .mod_actions ; .new_builders ; .verb_log ; .stats()
  .word_ok(word) ; .filter_words(words)       dictionary allowlist + blocklist for words a pip repeats unprompted
  ChatBridge.classify(text) -> (kind, arg, letter)   [static]
  ChatBridge.parse_verb(text) -> (verb, target, arg) | None   [static]
  ChatBridge.clean_text(text, cap) -> str            [static]
  module: word_lists() ; word_ok(word) ; filter_words(words)   the same lists for modules with no bridge handle

Message dict returned by ingest (and held in ctx.chat):
  {id, ts, t, name, text, text_clean, color, badges[], source, type,
   kind: vote|idea|theme|stats|help|ask|mod|plain, arg, letter, accepted, notice, dropped, drop_reason,
   rate_limited, display_name, builder_n, first_ever, show_t, history,
   verb: None | {verb, target, arg}, verb_ok: None|bool, verb_reason: None|str}

World events (.world_events, drained by whoever draws the plank; the world's own events stay in scene.events):
  notice{text, level, by}  verb{verb, by, target, arg, ok, reason}  nickname{pip, nickname}  burrowed{pip, reason}
  banish{pip, by}  unbanish{pip, by}  rename{pip, by}

builders.json ($RUN_DIR/builders.json, atomic, flushed every 10 s, persists across sessions):
  {"name_lower": {"n": 1, "name": "Sam", "first_seen": iso, "last_seen": iso, "sessions": 3, "votes": 41, "ships": 6,
                  "burrowed_session": id|absent, "banished": true|absent}}

History: records already in chat.jsonl at boot (older than HISTORY_S) are ingested for founders,
builders and tallies, but !idea/!theme/!stats/!help side effects, verbs, notices and builder blips are NOT
replayed (the previous compositor instance already did that). Mod commands in history are re-applied
silently so a !hide / !banish survives a compositor restart even if state.json lagged.

Python 3.9 only.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Dict, List, Optional, Set, Tuple

try:
    from stream import layout as L
    from stream.state_store import epoch_to_iso, write_state_atomic
except Exception:  # pragma: no cover
    import layout as L  # type: ignore
    from state_store import epoch_to_iso, write_state_atomic  # type: ignore

# ----------------------------------------------------------------------------- constants
HOLD_S = 3.0                 # 7.1 step 1
RATE_S = 2.0                 # 7.1 step 8
THEME_COOLDOWN_S = 60.0
CMD_COOLDOWN_S = 30.0
NOTICE_S = 5.0
THEME_NOTICE_S = 10.0        # `@name set theme: ember` lives here (CONCEPT 7 said header toast; QA 2026-09-25 moved it so
                             # the SHIPPED/FAILED scoreline never disappears from the thumbnail)
VOTE_ACK_S = 5.0             # `@name stands at A · light: gold · closes in 1:27` within the same frame as
                             # ingest (QA rank 3a; HUD pass journal 028: the tally is who STANDS at the stone at close, so
                             # the ack leads with the walk). The name goes through name_for(): a first-time chatter inside
                             # their hold reads `builder #N` (WORLD.md 11.1)
IDEA_ACK_S = 5.0
HINT_S = 5.0                 # an unparsed message that carried one of our own words: the plank names the exact token
HINT_COOLDOWN_S = 10.0       # ... at most once per user per 10 s
HINT_MAX_TOKENS = 10
HELD_ROWS_MAX = 2            # the chat log shows at most this many `name: …` rows for records inside their hold (one per chatter)
VOTE_STAND_GRACE_S = 14.0    # a vote whose pip is neither standing at nor walking to a stone this long after the hold is dropped
HELP_SHOW_S = 20.0
STATS_SHOW_S = 10.0
CAP_PLAIN, CAP_IDEA, CAP_ASK = 120, 60, 140
KEEP = 200                   # moderated messages kept in memory
HISTORY_S = 60.0             # a record older than this at ingest time is boot history
BLOCKLIST_RELOAD_S = 5.0
BUILDERS_FLUSH_S = 10.0

# -- verbs (OPENWORLD.md 6: exact-token + leading-verb rule)
MAX_VERB_TOKENS = 4
STOP_WORDS = frozenset(("a", "an", "the", "to", "at", "my", "some", "on"))
DIRECTIONS = ("north", "south", "east", "west")
PLACES = ("river", "ford", "moot", "fell", "wood", "shore", "marsh", "orchard", "steading")   # terrain.places keys
PLACE_LABELS = {"river": "the river", "ford": "the Ford", "moot": "the Moot", "fell": "the Fell", "wood": "the Wood",
                "shore": "the Shore", "marsh": "the Reed Marsh", "orchard": "the Orchard Slope",
                "steading": "the Steading", "home": "home"}
# object words per verb -> canonical arg (None = word accepted, no arg carried)
GO_OBJECTS = dict({d: d for d in DIRECTIONS}, **{p: p for p in PLACES})
GO_OBJECTS.update({"home": "home", "camp": "home", "tent": "home", "hut": "home",
                   "sea": "shore", "beach": "shore", "coast": "shore", "hill": "fell", "hills": "fell",
                   "forest": "wood", "woods": "wood", "trees": "wood", "reeds": "marsh", "green": "moot",
                   "village": "steading", "stones": "moot", "waystones": "moot"})
PLANT_OBJECTS = {"flower": "flower", "flowers": "flower", "tree": "tree", "sapling": "tree", "reed": "reed", "reeds": "reed"}
CAMP_OBJECTS = {"here": None, "camp": None, "tent": None, "hut": None}
FIRE_OBJECTS = {"fire": None, "campfire": None, "hearth": None}
# verb -> spec: objects {word: canonical}, targets (min, max) of @names, args (min, max) of object words,
#               total (max of targets + objects), bare_target (a plain token may be a username, the old feed/pet form),
#               default_arg (arg when no object word was typed), canon (the verb actually queued)
VERB_SPECS: Dict[str, Dict] = {
    "go":      {"objects": GO_OBJECTS, "targets": (0, 1), "args": (0, 1), "total": 1},
    "home":    {"objects": {}, "targets": (0, 0), "args": (0, 0), "canon": "go", "default_arg": "home"},
    "plant":   {"objects": PLANT_OBJECTS, "targets": (0, 0), "args": (0, 1), "default_arg": "flower"},
    "camp":    {"objects": CAMP_OBJECTS, "targets": (0, 0), "args": (0, 1)},
    "fire":    {"objects": FIRE_OBJECTS, "targets": (0, 0), "args": (0, 1)},
    "feed":    {"objects": {}, "targets": (0, 1), "args": (0, 0), "bare_target": True},
    "pet":     {"objects": {}, "targets": (0, 1), "args": (0, 0), "bare_target": True},
    "gift":    {"objects": {}, "targets": (1, 1), "args": (0, 0), "bare_target": True},
    "wave":    {"objects": {}, "targets": (0, 0), "args": (0, 0)},
    "sit":     {"objects": {}, "targets": (0, 0), "args": (0, 0)},
    "dance":   {"objects": {}, "targets": (0, 0), "args": (0, 0)},
    "forget":  {"objects": {}, "targets": (0, 0), "args": (0, 0)},
    "name":    {"word": True},
    "teach":   {"word": True},
    # parsed so they never bubble as commands elsewhere; refused with LATER_VERBS copy until their raising lands
    "sow":     {"objects": {"field": None}, "targets": (0, 0), "args": (0, 1)},
    "harvest": {"objects": {"field": None}, "targets": (0, 0), "args": (0, 1)},
    "stack":   {"objects": {"stone": None, "stones": None}, "targets": (0, 0), "args": (0, 1)},
    "swim":    {"objects": {}, "targets": (0, 0), "args": (0, 0)},
    "sing":    {"objects": {}, "targets": (0, 0), "args": (0, 0)},
    "explore": {"objects": {}, "targets": (0, 0), "args": (0, 0)},
    "water":   {"objects": {}, "targets": (1, 1), "args": (0, 0), "bare_target": True},
}
VERB_ALIASES = {"walk": "go", "head": "go", "light": "fire", "pitch": "camp"}
# unparsed-with-hint (OPENWORLD 6 addendum, journal 028): a short message that did NOT parse but carries one of our own
# words gets `to do that, type: <canonical form>` on the plank. Every hint is assembled from these tables, never from
# the typed text, never with an @name. `hut / build / settle` -> camp; `light / warm / campfire` -> fire; `grow / seed /
# flower / tree` -> plant X; `walk / move / run / further` + a direction or place -> go X; `vote / pick / choose` + a
# letter -> the letter; a verb that needs an object and got none -> its shortest example (`go` -> `go river`).
HINT_VERB_SYNONYMS = {"hut": "camp", "tent": "camp", "build": "camp", "settle": "camp", "pitch": "camp",
                      "light": "fire", "warm": "fire", "campfire": "fire", "hearth": "fire",
                      "grow": "plant", "seed": "plant", "sow": "plant", "planting": "plant",
                      "walk": "go", "move": "go", "head": "go", "explore": "go",
                      "vote": "vote", "pick": "vote", "choose": "vote", "voting": "vote"}
# NOT synonyms (false positives are worse than silence): `there` (`hello there`), `further`, `run`, `home` (`I'm going
# home` is a goodbye, not a verb) -- `go north further` / `go home` already carry the verb word.
HINT_PLANT_WORDS = {"flower": "flower", "flowers": "flower", "tree": "tree", "trees": "tree", "sapling": "tree", "reed": "reed", "reeds": "reed"}
HINT_EXAMPLES = {"go": "go river", "plant": "plant flower", "camp": "camp", "fire": "fire"}
PITCH_NEEDS_OBJECT = True                       # `pitch` alone is chat; `pitch a tent` / `pitch camp` is camp
VERBS = tuple(VERB_SPECS.keys())
TARGET_VERBS = {v: s["targets"] for v, s in VERB_SPECS.items() if s.get("targets", (0, 0))[1] > 0}
WORD_VERBS = {v for v, s in VERB_SPECS.items() if s.get("word")}           # exactly one plain word (<= 12 alnum)
LATER_VERBS = {v: "%s · not yet · try: go river · plant a flower · camp" % v          # world voice, never roadmap-speak (`comes in a later raising`)
               for v in ("sow", "harvest", "stack", "swim", "sing", "explore", "water", "teach")}
VERB_COOLDOWN_S = {"go": 5.0, "fire": 600.0, "feed": 30.0, "pet": 30.0, "wave": 5.0, "sit": 5.0, "dance": 5.0,
                   "name": 600.0, "sing": 60.0, "explore": 60.0, "water": 60.0, "stack": 45.0, "swim": 30.0,
                   "teach": 300.0}
PLANT_SESSION_CAP = {"flower": 3, "tree": 1, "reed": 3}   # OPENWORLD 6: trees 1 / flowers 3 per session (reeds as flowers)
PLANT_CAP_COPY = {"flower": "three flowers a night · yours are planted", "tree": "one tree a night · yours is planted",
                  "reed": "three reeds a night · yours are planted"}
CAMP_SESSION_CAP = 1
GO_WHERE = "go where? north · south · east · west · river · ford · moot · fell · wood · shore · marsh · orchard · home · @name"
SING_GLOBAL_S = 10.0
NICK_MAX = 12
RESERVED_NICKS = {"keeper", "keepers", "mod", "mods", "moderator", "admin", "kick", "hollow", "longgrass", "steading",
                  "moot", "beacon", "cairn", "pip", "wind"}
NAME_TOKEN_RE = re.compile(r"^[a-z0-9_]{1,25}$")
TOKEN_TRIM = "!?.,;:"
VERB_RETRY_S = 3.0           # `your pip is not awake yet` after the hold: the hatch lands a frame later
RETRY_REASONS = ("your pip is not awake yet", "the cave is still waking", "the land is still waking")
VERB_WAIT_WORLD_S = 10.0     # no world attached: keep the verb this long, then drop it (logged)
VERB_LOG_KEEP = 100
WORLD_EVENTS_KEEP = 200
WORLD_PROBE_S = 2.0
STRIKES_MAX = 3
STRIKES_REASON = "3 filtered messages"

VOTE_RE = re.compile(r"^!?([abc])$", re.IGNORECASE)
CMD_RE = re.compile(r"^!(\w+)\s*(.*)$", re.DOTALL)
_TLDS = ("com|net|org|io|gg|tv|me|co|xyz|ru|de|uk|us|info|link|app|dev|ly|to|cc|biz|stream|live|"
         "site|online|club|shop|store|top|fun|icu|buzz|tk|ml|ga|cf|gq|pw|ws|vip|bet|casino|porn|sex|xxx")
URL_RE = re.compile(
    r"(?i)(?:"
    r"\b[a-z][a-z0-9+.-]*://[^\s]+"                  # scheme://...
    r"|\bwww\.[^\s]+"                                # www.host
    r"|(?<![\w@])(?:[a-z0-9-]+\.)+(?:" + _TLDS + r")\b(?:[/?#][^\s]*)?"   # host.tld[/path]
    r")")
EMOTE_RE = re.compile(r"\[emote:(\d+):([^\]]*)\]")
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b",
                       "@": "a", "$": "s", "!": "i", "|": "l", "+": "t", "(": "c", "€": "e", "£": "l"})
_SUFFIXES = ("", "s", "es", "z", "ed", "ing", "er", "ers")   # only for terms >= SUFFIX_MIN_LEN letters
SUFFIX_MIN_LEN = 5            # "spic" must not match "spices"; "retard" may match "retarded"
SPACED_RUN_MIN = 3            # "n i g g e r": a run of >= 3 single-letter tokens is re-joined and re-checked

MOD_CMDS = {"hide", "unhide", "pause", "resume", "kill", "unkill", "clear", "banish", "unbanish", "rename"}
PAUSE_BOT_PHRASES = ("pause bot", "bot pause")          # owner's failsafe phrase -> mod pause (badge still required)
RESUME_BOT_PHRASES = ("resume bot", "bot resume", "unpause bot")
# Theme phrasing (journal 023 addendum: the owner's `Change the colour to kick colours` fell through as chat). A short
# message (<= THEME_PHRASE_MAX_TOKENS words, no URL) that names exactly ONE preset and carries a theme word is read
# as `!theme <preset>`: `kick colours`, `theme kick`, `make it kick coloured`. A theme word with no preset gets the
# plank hint `type !theme kick · ember · ...` (THEME_HINT_COOLDOWN_S). Longer sentences never trigger anything.
THEME_WORDS = frozenset(("theme", "themes", "colour", "colours", "coloured", "color", "colors", "colored", "palette",
                         "recolour", "recolor", "tint"))
THEME_PHRASE_MAX_TOKENS = 8
THEME_HINT_COOLDOWN_S = 30.0
_WORD_RE = re.compile(r"[a-z]+")
BROADCASTER_ONLY = {"kill", "unkill"}
KINDS = ("vote", "idea", "theme", "stats", "help", "ask", "mod", "plain")

_HERE = os.path.dirname(os.path.abspath(__file__))
BLOCKLIST_PATH = os.path.join(_HERE, "moderation", "blocklist.txt")
ALLOWLIST_PATH = os.path.join(_HERE, "moderation", "allowlist.txt")


def _norm(s: str) -> str:
    """Leet-normalised lowercase, non-alnum -> space, repeated letters collapsed, single-spaced."""
    s = (s or "").lower().translate(_LEET)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"(.)\1{2,}", r"\1\1", s)          # loooool -> lool ; niggger -> nigger (doubles are kept: niger != nigger)
    return re.sub(r"\s+", " ", s).strip()


def _badge_roles(badges) -> Tuple[bool, bool]:
    """(is_mod, is_owner) from the badge list; tolerant of 'Broadcaster', dict-ish strings, etc."""
    owner = mod = False
    for b in badges or []:
        s = str(b).lower()
        if "broadcaster" in s:
            owner = mod = True
        elif "moderator" in s or s == "mod":
            mod = True
    return mod, owner


# ----------------------------------------------------------------------------- word lists
class WordLists(object):
    """blocklist.txt (drop / builder #N) + allowlist.txt (what a pip may repeat unprompted). Both hot-reloaded
    within BLOCKLIST_RELOAD_S of a change. WORLD.md 11.3: words a pip mutters must be in the allowlist AND pass
    the blocklist; the text layer calls word_ok()/filter_words() on WorldState.top_words() before drawing."""

    def __init__(self, blocklist_path: Optional[str] = None, allowlist_path: Optional[str] = None, log=None):
        self.blocklist_path = blocklist_path or BLOCKLIST_PATH
        self.allowlist_path = allowlist_path or ALLOWLIST_PATH
        self.log = log or (lambda m: None)
        self.block_terms: List[str] = []
        self.allow: Set[str] = set()
        self._mtimes: Dict[str, Optional[float]] = {}
        self._checked: Optional[float] = None

    def reload(self, now: float, force: bool = False) -> None:
        if not force and self._checked is not None and now - self._checked < BLOCKLIST_RELOAD_S:
            return
        self._checked = now
        self._reload_one(self.blocklist_path, "block")
        self._reload_one(self.allowlist_path, "allow")

    def _reload_one(self, path: str, which: str) -> None:
        try:
            st = os.stat(path)
        except OSError:
            have = len(self.block_terms) if which == "block" else len(self.allow)
            if have and self._mtimes.get(path) is not None:
                self.log("%slist missing: %s (keeping %d terms)" % (which, path, have))
            self._mtimes[path] = None
            return
        if st.st_mtime == self._mtimes.get(path):
            return
        self._mtimes[path] = st.st_mtime
        terms: List[str] = []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for ln in fh:
                    ln = ln.split("#", 1)[0].strip()
                    if not ln:
                        continue
                    if which == "block":
                        n = _norm(ln)
                        if n and n not in terms:
                            terms.append(n)
                    else:
                        for tok in ln.lower().split():
                            terms.append(tok)
        except Exception as e:
            self.log("%slist read failed: %r" % (which, e))
            return
        if which == "block":
            self.block_terms = terms
            self.log("blocklist loaded: %d terms from %s" % (len(terms), path))
        else:
            self.allow = set(terms)
            self.log("allowlist loaded: %d words from %s" % (len(self.allow), path))

    @staticmethod
    def _token_hit(tok: str, term: str) -> bool:
        if tok == term:
            return True
        if len(term) >= SUFFIX_MIN_LEN and tok.startswith(term):
            return tok[len(term):] in _SUFFIXES
        return False

    def blocked(self, text: str) -> Optional[str]:
        """Returns the matching blocklist term (normalised) or None."""
        if not self.block_terms or not text:
            return None
        n = _norm(text)
        if not n:
            return None
        tokens = n.split(" ")
        joined: List[str] = []           # spaced-out evasion: "n i g g e r" -> join runs of >= SPACED_RUN_MIN letters
        run: List[str] = []
        for tok in tokens + [""]:
            if len(tok) == 1:
                run.append(tok)
                continue
            if len(run) >= SPACED_RUN_MIN:
                joined.append("".join(run))
            run = []
        padded = " " + n + " "
        for term in self.block_terms:
            if " " in term:
                if " " + term + " " in padded:
                    return term
                continue
            for tok in tokens:
                if self._token_hit(tok, term):
                    return term
            for tok in joined:
                if self._token_hit(tok, term):
                    return term
        return None

    def allowed(self, word: str) -> bool:
        """Dictionary allowlist, exact lowercase token. An empty allowlist allows nothing (a pip then mutters nothing)."""
        w = (word or "").strip().lower()
        return bool(w) and w in self.allow

    def word_ok(self, word: str) -> bool:
        return self.allowed(word) and self.blocked(word) is None

    def filter_words(self, words) -> List[str]:
        return [w for w in (words or []) if self.word_ok(w)]


_WORDS: Optional[WordLists] = None


def word_lists(now: Optional[float] = None) -> WordLists:
    """The shared default lists (default paths), reloaded on demand. For modules that hold no bridge."""
    global _WORDS
    if _WORDS is None:
        _WORDS = WordLists()
    import time as _t
    _WORDS.reload(now if now is not None else _t.time())
    return _WORDS


def word_ok(word: str, now: Optional[float] = None) -> bool:
    return word_lists(now).word_ok(word)


def filter_words(words, now: Optional[float] = None) -> List[str]:
    return word_lists(now).filter_words(words)


# ----------------------------------------------------------------------------- the bridge
class ChatBridge(object):
    def __init__(self, run_dir: str, log=None, blocklist_path: Optional[str] = None, allowlist_path: Optional[str] = None):
        self.run_dir = run_dir
        self.log = log or (lambda m: sys.stderr.write("chat_bridge: %s\n" % m))
        self.blocklist_path = blocklist_path or BLOCKLIST_PATH
        self.allowlist_path = allowlist_path or ALLOWLIST_PATH
        self.channel_owner = (os.environ.get("KICK_CHANNEL") or "atleastonce").strip().lower()
        if blocklist_path is None and allowlist_path is None:
            global _WORDS
            if _WORDS is None:
                _WORDS = WordLists(log=self.log)
            self.words = _WORDS
        else:
            self.words = WordLists(self.blocklist_path, self.allowlist_path, log=self.log)

        self.messages: List[Dict] = []                     # moderated, renderable (never dropped ones)
        self._votes: Dict[str, Tuple[str, float]] = {}     # name_lower -> (letter, t)
        self._voted_this_round: Set[str] = set()           # for builders[].votes (1 per user per round)
        self._round_opened_t: Optional[float] = None
        self._last_render_t: Dict[str, float] = {}
        self._notice: Optional[Tuple[str, str, float]] = None   # text, level, until
        self._ack_notice: Optional[Tuple[str, str, float]] = None   # `@name voted A`: its own slot, so a !theme / cooldown
                                                                    # notice landing in the same batch cannot hide the ack
        self._last_theme_t: Optional[float] = None
        self._last_theme_hint_t: Optional[float] = None
        self.help_until = 0.0
        self.stats_until = 0.0
        self.help_by: Optional[str] = None                  # who asked !help / !stats (the plank answers them by name)
        self.stats_by: Optional[str] = None
        self._round_remaining: Optional[float] = None       # from ctx at ingest: the vote ack's `closes in m:ss`
        self._round_titles: Dict[str, str] = {}             # letter -> option title, from ctx at ingest: the ack's ` · light: gold`
        self._round_remaining_at: Optional[float] = None
        self._hint_t: Dict[str, float] = {}                 # key -> t of the last unparsed-with-hint
        self._last_help_t: Optional[float] = None
        self._last_stats_t: Optional[float] = None
        self.display = True
        self.paused = False
        self._pause_t: Optional[float] = None
        self._hidden: Set[str] = set()                      # mod !hide (mirrored to state.mod.hidden_users)
        self.burrowed: Dict[str, str] = {}                  # three strikes this session: key -> reason
        self.banished: Set[str] = set()                     # !banish (persists in builders.json until !unbanish)
        self.strikes: Dict[str, int] = {}                   # blocklist hits on a user's text this session
        self._unhidden_t: Dict[str, float] = {}             # !unhide grace so a lagging state.mod cannot re-hide
        self.dropped = 0                                    # moderation.dropped (blocklist hits)
        self.rate_limited = 0
        self._founders: List[str] = []                     # KEYS of the first 10 chatters; names resolve via name_for()
        self._session_seen: Set[str] = set()
        self.new_builders = 0                               # first-ever chatters this run (audio cue)
        self.mod_actions: List[Dict] = []
        self._state_synced = False
        self.ingested = 0
        self.session_id: Optional[str] = None
        self._now: float = 0.0                              # the latest `now` this bridge has seen (name_for's hold clock)
        self._first_show_t: Dict[str, float] = {}           # key -> show_t of their first record this run (the hold gate)
        self._held_acks: List[Tuple[float, str, str]] = []  # (show_t, key, letter): a vote cast inside the chatter's first hold is
                                                            # acked nameless at once and again BY NAME when the hold clears (journal 030)

        # -- verbs / world
        self.world = None
        self._world_explicit = False
        self._world_probe_t: Optional[float] = None
        self._pending: List[Dict] = []
        self._pumped_at: Optional[float] = None
        self._verb_last: Dict[Tuple[str, str], float] = {}  # (key, verb) -> t of the last accepted use
        self._plant_used: Dict[Tuple[str, str], int] = {}   # (key, kind) -> plants this session (OPENWORLD 6 caps)
        self._camp_used: Dict[str, int] = {}                # key -> `camp` uses this session (1)
        self._stack_used: Dict[str, int] = {}               # key -> stones this session (3; v1)
        self._sow_used: Set[str] = set()                    # keys that sowed this session (v1)
        self._gift_used: Set[Tuple[str, str]] = set()       # (by, target) this session
        self._sing_global_t: Optional[float] = None
        self.verb_log: List[Dict] = []
        self.world_events: List[Dict] = []
        self.verbs_ok = 0
        self.verbs_refused = 0

        self.builders_path = os.path.join(run_dir, "builders.json")
        self.builders: Dict[str, Dict] = {}
        self._builders_dirty = False
        self._builders_flushed: Optional[float] = None
        self._load_builders()

    # ------------------------------------------------------------------ builders.json
    def _load_builders(self) -> None:
        try:
            with open(self.builders_path, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if isinstance(d, dict):
                self.builders = {str(k).lower(): v for k, v in d.items() if isinstance(v, dict)}
        except Exception:
            self.builders = {}
        for k, b in self.builders.items():
            # a chatter from a previous session already served their hold that night (and their sleeping pip is
            # labelled from world.json): only the live blocklist still applies. New chatters wait for show_t.
            self._first_show_t.setdefault(k, float("-inf"))
            if b.get("banished") is True:
                self.banished.add(k)
                self._hidden.add(k)

    def builder_n(self, name: str) -> Optional[int]:
        b = self.builders.get((name or "").lower())
        if not b:
            return None
        try:
            return int(b.get("n"))
        except Exception:
            return None

    def _touch_builder(self, name: str, t: float, history: bool) -> bool:
        """Registers the chatter; returns True on the user's first-ever message."""
        k = (name or "").lower()
        if not k:
            return False
        first = False
        b = self.builders.get(k)
        if b is None:
            nxt = 1 + max([int(x.get("n") or 0) for x in self.builders.values()] or [0])
            b = {"n": nxt, "name": name, "first_seen": epoch_to_iso(t), "last_seen": epoch_to_iso(t),
                 "sessions": 0, "votes": 0, "ships": 0}
            self.builders[k] = b
            first = True
            if not history:
                self.new_builders += 1
        b["last_seen"] = epoch_to_iso(t)
        if b.get("name") != name and name:
            b["name"] = name                      # keep the latest capitalisation
        if k not in self._session_seen:
            self._session_seen.add(k)
            b["sessions"] = int(b.get("sessions", 0)) + 1
            if len(self._founders) < 10 and k not in self._founders:
                self._founders.append(k)
        self._builders_dirty = True
        return first

    def flush(self, now: float, force: bool = False) -> None:
        if not self._builders_dirty:
            return
        if not force and self._builders_flushed is not None and now - self._builders_flushed < BUILDERS_FLUSH_S:
            return
        try:
            write_state_atomic(self.builders_path, self.builders)
            self._builders_dirty = False
            self._builders_flushed = now
        except Exception as e:
            self.log("builders.json write failed: %r" % (e,))

    # ------------------------------------------------------------------ word lists (compat shims)
    def _load_blocklist(self, now: float) -> None:
        self.words.reload(now)

    @property
    def _block_terms(self) -> List[str]:
        return self.words.block_terms

    def _blocked(self, text: str) -> Optional[str]:
        return self.words.blocked(text)

    def word_ok(self, word: str) -> bool:
        return self.words.word_ok(word)

    def filter_words(self, words) -> List[str]:
        return self.words.filter_words(words)

    # ------------------------------------------------------------------ classify / clean / verbs
    @staticmethod
    def classify(text: str) -> Tuple[str, str, Optional[str]]:
        """-> (kind, arg, letter). Vote iff the trimmed text is exactly ^!?[abc]$ (case-insensitive)."""
        t = (text or "").strip()
        m = VOTE_RE.match(t)
        if m:
            return "vote", "", m.group(1).upper()
        # Owner's failsafe (2026-09-26, terminal): the exact words `pause bot` stop chat ingestion (same as the mod
        # `!pause`); `resume bot` resumes. Kind "mod" still requires the broadcaster/moderator badge downstream.
        low = re.sub(r"\s+", " ", t.lower())
        if low in PAUSE_BOT_PHRASES:
            return "mod", "pause", None
        if low in RESUME_BOT_PHRASES:
            return "mod", "resume", None
        m = CMD_RE.match(t)
        if m:
            cmd, arg = m.group(1).lower(), m.group(2).strip()
            arg = re.sub(r"\s+", " ", arg)
            if cmd == "idea":
                return "idea", arg[:CAP_IDEA], None
            if cmd == "theme":
                return "theme", (arg.split(" ")[0].lower().lstrip("#") if arg else ""), None
            if cmd == "ask":
                return "ask", arg[:CAP_ASK], None
            if cmd in ("stats", "help"):
                return cmd, "", None
            if cmd in MOD_CMDS:
                return "mod", (cmd + " " + arg).strip(), None
        preset = ChatBridge.theme_phrase(t)
        if preset:
            return "theme", preset, None
        return "plain", "", None

    @staticmethod
    def theme_phrase(text: str) -> Optional[str]:
        """`kick colours` / `theme kick` / `make it kick coloured` -> "kick"; None when the message is not a theme ask
        (no theme word, no or several presets, a URL, or more than THEME_PHRASE_MAX_TOKENS words)."""
        t = (text or "").strip()
        if not t or t.startswith("!") or URL_RE.search(t):
            return None
        if len(t.split()) > THEME_PHRASE_MAX_TOKENS:
            return None
        words = _WORD_RE.findall(t.lower())
        if not any(w in THEME_WORDS for w in words):
            return None
        presets = sorted(set(w for w in words if w in L.PRESETS))
        return presets[0] if len(presets) == 1 else None

    @staticmethod
    def theme_hint_due(text: str) -> bool:
        """A short message with a theme word but no preset: the plank should say how (`type !theme kick`)."""
        t = (text or "").strip()
        if not t or t.startswith("!") or URL_RE.search(t) or len(t.split()) > THEME_PHRASE_MAX_TOKENS:
            return False
        words = _WORD_RE.findall(t.lower())
        return any(w in THEME_WORDS for w in words) and not any(w in L.PRESETS for w in words)

    @staticmethod
    def hint_for(text: str) -> Optional[str]:
        """The plank hint for a message that did NOT parse (call only when parse_verb() is None): `try: go north` /
        `try: go river` / `try: camp` / `try: plant tree` / `try: fire` / `try: B` / `try: !theme kick` (the world's
        voice, two words: the same fact the old seven-word sentence carried). None when the message is longer than
        HINT_MAX_TOKENS, carries a URL, or names none of our words. The hint is built ONLY from canonical tokens in the
        tables above: the typed words and any @name never reach the plank. A bare object word (`river`, `trees`) is a
        hint only in a message of <= 2 tokens (`river please`); `I love trees` and `the river is pretty` stay chat."""
        t = (text or "").strip()
        if not t or URL_RE.search(t):
            return None
        raw = t.split()
        if len(raw) > HINT_MAX_TOKENS:
            return None
        toks = [tok.lower().strip(TOKEN_TRIM).lstrip("!") for tok in raw]
        toks = [w for w in toks if w and not w.startswith("@")]
        if not toks:
            return None
        # `bbbbb` / `AAA` (journal 031: a repeated letter fell through as plain chat): a vote is exactly one letter
        if len(toks) == 1 and len(toks[0]) >= 2 and toks[0][0] in "abc" and toks[0] == toks[0][0] * len(toks[0]):
            return "try: %s" % toks[0][0].upper()
        # a preset word with no theme word (`kick would be nice`): the theme verb
        presets = [w for w in toks if w in L.PRESETS]
        if len(presets) == 1 and not any(w in THEME_WORDS for w in toks) and not any(w in VERB_SPECS or w in VERB_ALIASES for w in toks):
            return "try: !theme %s" % presets[0]
        verb = None
        for w in toks:
            if w in VERB_SPECS and w not in ("name", "teach", "home") and w not in LATER_VERBS:
                verb = VERB_SPECS[w].get("canon", w)
                break
            if w in VERB_ALIASES:
                verb = VERB_ALIASES[w]
                break
        syn = next((HINT_VERB_SYNONYMS[w] for w in toks if w in HINT_VERB_SYNONYMS), None)
        letters = [w.upper() for w in toks if w in ("a", "b", "c")]
        direction = next((w for w in toks if w in DIRECTIONS), None)
        place = next((GO_OBJECTS[w] for w in toks if w in GO_OBJECTS and w not in ("home", "camp", "tent", "hut")), None)
        plant_obj = next((HINT_PLANT_WORDS[w] for w in toks if w in HINT_PLANT_WORDS), None)
        if syn == "vote" and len(letters) == 1:
            return "try: %s" % letters[0]
        v = verb or syn
        if v is None:
            if len(toks) <= 2 and (direction or place):
                return "try: go %s" % (direction or place)
            if len(toks) <= 2 and plant_obj:
                return "try: plant %s" % plant_obj
            return None
        if v == "vote":
            return None
        if v == "go":
            if direction:
                return "try: go %s" % direction
            if place:
                return "try: go %s" % place
            return "try: %s" % HINT_EXAMPLES["go"]
        if v == "plant":
            return "try: plant %s" % (plant_obj or "flower")
        if v in ("camp", "fire"):
            return "try: %s" % v
        if v in HINT_EXAMPLES:
            return "try: %s" % HINT_EXAMPLES[v]
        if v in VERB_SPECS and not VERB_SPECS[v].get("word"):
            return "try: %s" % v
        return None

    def _title_of(self, letter: str) -> str:
        """` · light: gold`: the option's title from the round the compositor handed ingest() (empty when unknown), so a
        letter typed while the Moot is off view still gets its meaning on the plank (journal 034)."""
        t = (self._round_titles or {}).get(str(letter or "").upper())
        return (" · " + t) if t else ""

    def _closes_in(self, now: float) -> str:
        """` · closes in 1:27` from the round clock the compositor handed ingest() (empty when no round is open)."""
        if self._round_remaining is None or self._round_remaining_at is None:
            return ""
        rem = self._round_remaining - (float(now) - self._round_remaining_at)
        if rem < 0:
            return ""
        rem = int(rem)
        return " · closes in %d:%02d" % (rem // 60, rem % 60)

    @staticmethod
    def parse_verb(text: str) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
        """OPENWORLD.md 6 exact-token + leading-verb rule -> (verb, target_key|None, arg|None) or None.
        A message parses only when: no URL; at most MAX_VERB_TOKENS whitespace tokens; the first token (optionally
        `!`-prefixed, trailing punctuation trimmed) is a verb, an alias or a bare direction word; and after the
        STOP_WORDS are dropped every remaining token is a known object word for that verb (or an `@name` where the
        verb takes one). Anything else is plain chat: `go away`, `plant based`, `I love to sing`, `right?`.
        name/teach take exactly one free word (never `@user`, never a stop-word drop): a nickname is not an object."""
        t = (text or "").strip()
        if not t or URL_RE.search(t):
            return None
        raw = t.split()
        if len(raw) > MAX_VERB_TOKENS:
            return None
        toks = [tok.lower().strip(TOKEN_TRIM) for tok in raw]
        first = toks[0]
        if first.startswith("!"):
            first = first[1:]
        if not first:
            return None
        if len(toks) == 1 and first in DIRECTIONS:
            return "go", None, first                        # a bare direction word walks (`north`)
        typed = first
        verb = VERB_ALIASES.get(first, first)
        spec = VERB_SPECS.get(verb)
        if spec is None:
            return None
        rest = toks[1:]
        if spec.get("word"):
            if len(rest) != 1 or raw[1].startswith("@"):
                return None                                 # `name @sam` is a username, not a nickname
            w = raw[1].strip(TOKEN_TRIM)
            if not re.match(r"^[a-z0-9]{1,%d}$" % NICK_MAX, w, re.IGNORECASE):
                return None
            return verb, None, w
        objects: List[Optional[str]] = []
        targets: List[str] = []
        legacy_ok = spec.get("bare_target") and len(rest) == 1     # `feed sami`: the exact-token form kept as-is
        for tok in rest:
            if tok in STOP_WORDS:
                continue
            if tok.startswith("@"):
                nm = tok[1:]
                if spec["targets"][1] == 0 or not NAME_TOKEN_RE.match(nm):
                    return None
                targets.append(nm)
                continue
            if tok in spec["objects"]:
                objects.append(spec["objects"][tok])
                continue
            if legacy_ok and NAME_TOKEN_RE.match(tok):
                targets.append(tok)                         # two tokens only: `feed the river` stays chat
                continue
            return None                                     # an unknown word anywhere -> plain chat
        lo_t, hi_t = spec["targets"]
        lo_a, hi_a = spec["args"]
        if not (lo_t <= len(targets) <= hi_t and lo_a <= len(objects) <= hi_a):
            return None
        if len(targets) + len(objects) > spec.get("total", 2):
            return None
        if typed == "pitch" and PITCH_NEEDS_OBJECT and not objects:
            return None                                     # `pitch` alone is chat; `pitch a tent` is camp
        arg = None
        for o in objects:
            if o is not None:
                arg = o
        if arg is None:
            arg = spec.get("default_arg")
        return spec.get("canon", verb), (targets[0] if targets else None), arg

    @staticmethod
    def verb_form(verb: str, target: Optional[str], arg: Optional[str]) -> str:
        """The canonical reading the plank echoes (`go river`, `plant flower`, `feed @sami`). Target keys are shown
        with `@` here only for the log; drawn copy goes through name_for()."""
        parts = [verb]
        if target:
            parts.append("@" + target)
        if arg:
            parts.append(str(arg))
        return " ".join(parts)

    @staticmethod
    def clean_text(text: str, cap: int) -> str:
        """URL -> [link], non-BMP stripped, [emote:id:name] -> :name:, whitespace folded, capped."""
        s = L.strip_non_bmp(text or "")
        s = EMOTE_RE.sub(lambda m: ":%s:" % (m.group(2).strip() or "emote"), s)
        s = URL_RE.sub("[link]", s)
        s = re.sub(r"[\x00-\x1f\x7f]+", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        if cap and len(s) > cap:
            s = s[:max(1, cap - 1)].rstrip() + "…"
        return s

    # ------------------------------------------------------------------ THE name path
    def _display_name(self, name: str) -> str:
        """Username blocklist (7.1 step 6): a hit renders as `builder #N`. Used by name_for() and by the world's
        boot filter (CaveScene._default_filter) for pips loaded from world.json."""
        if self._blocked(name):
            n = self.builder_n(name)
            return "builder #%s" % (n if n is not None else "?")
        return name

    def _cleared(self, key: str, now: float) -> bool:
        st = self._first_show_t.get(key)
        return st is not None and now >= st

    def name_for(self, key: str, now: Optional[float] = None) -> str:
        """The only way a chatter becomes drawable text: filtered (blocklist -> builder #N) AND held (until the
        chatter's first record of this run is past its 3 s show_t -> builder #N). Never the raw name."""
        k = (key or "").lower()
        if not k:
            return "?"
        t = self._now if now is None else now
        b = self.builders.get(k) or {}
        n = b.get("n")
        if not self._cleared(k, t):
            return "builder #%s" % (n if n is not None else "?")
        return self._display_name(b.get("name") or k)

    def _at(self, key: str, now: Optional[float] = None) -> str:
        return "@" + self.name_for(key, now)

    # ------------------------------------------------------------------ world hooks
    def attach_world(self, scene) -> None:
        """Hand the bridge the CaveScene (anything with .command(verb, actor, target, arg, now)). Explicit wiring
        wins over discovery. Pass None to detach."""
        self.world = scene
        self._world_explicit = scene is not None

    def _get_world(self, now: float):
        if self._world_explicit:
            return self.world
        if self._world_probe_t is not None and now - self._world_probe_t < WORLD_PROBE_S and self.world is not None:
            return self.world
        self._world_probe_t = now
        found = None
        for name, mod in list(sys.modules.items()):
            if mod is None or not (name.startswith("stream.scenes.") or name.startswith("stream.panels.")):
                continue
            for attr in ("SCENE", "scene", "WORLD"):
                cand = getattr(mod, attr, None)
                if cand is not None and callable(getattr(cand, "command", None)):
                    found = cand
                    break
            if found is not None:
                break
        if found is not self.world:
            self.world = found
            if found is not None:
                self.log("world attached: %s.%s" % (type(found).__module__, type(found).__name__))
        return self.world

    def _emit(self, ev: Dict) -> None:
        self.world_events.append(ev)
        if len(self.world_events) > WORLD_EVENTS_KEEP:
            del self.world_events[:-WORLD_EVENTS_KEEP]

    def drain_world_events(self) -> List[Dict]:
        out, self.world_events = self.world_events, []
        return out

    def _plank(self, text: str, now: float, level: str = "warn", by: Optional[str] = None, dur: float = NOTICE_S) -> None:
        """A plank notice (ctx.notice for `dur` s) plus a `notice` world event."""
        self._set_notice(text, level, now, dur)
        self._emit({"type": "notice", "text": text, "level": level, "by": by})

    # ------------------------------------------------------------------ ingest
    def _sync_state(self, ctx) -> None:
        """Merge mod state from state.json (once at boot, plus hidden_users every call) and track the session."""
        if ctx is None:
            return
        sid = (ctx.session or {}).get("id") or None
        if sid != self.session_id:
            if self.session_id is not None:
                self._new_session()
            self.session_id = sid
        state_mod = ctx.mod or {}
        now = float(ctx.now or self._now or 0.0)
        for u in state_mod.get("hidden_users") or []:
            u = str(u).lower()
            if u in self._hidden or u in self.burrowed:
                continue
            if now - self._unhidden_t.get(u, -1e9) < 2.0:
                continue                                    # just unhidden; state.json has not caught up yet
            b = self.builders.get(u) or {}
            bs = b.get("burrowed_session")
            if bs is not None and not b.get("banished"):
                if bs == self.session_id:
                    self.burrowed[u] = STRIKES_REASON       # a deploy restart inside the session: still burrowed
                # an earlier session's strikes burrow: not a mod hide, and it ends with the session
                continue
            self._hidden.add(u)
        if self._state_synced:
            return
        self._state_synced = True
        cfg = ctx.chat_cfg or {}
        if cfg.get("display") is False:
            self.display = False
        if state_mod.get("paused") is True:
            self.paused = True
            self._pause_t = ctx.now

    def _new_session(self) -> None:
        """Per-session verb state ends with the session (WORLD.md 4: plant once per session, gift once per target,
        strikes burrow for the session)."""
        self.burrowed = {}
        self.strikes = {}
        self._plant_used = {}
        self._camp_used = {}
        self._stack_used = {}
        self._sow_used = set()
        self._gift_used = set()
        self._session_seen = set()
        for b in self.builders.values():
            if b.pop("burrowed_session", None) is not None:
                self._builders_dirty = True

    def ingest(self, msgs: List[Dict], now: float, ctx=None) -> List[Dict]:
        self._now = max(self._now, float(now))
        self.words.reload(now)
        self._sync_state(ctx)
        rr = getattr(ctx, "round_remaining", None) if ctx is not None else None
        if rr is not None and (ctx.round or {}).get("phase") != "ship":
            self._round_remaining, self._round_remaining_at = float(rr), float(now)
        else:
            self._round_remaining = None
        titles: Dict[str, str] = {}
        for o in ((getattr(ctx, "round", None) or {}).get("options") or []) if ctx is not None else []:
            if isinstance(o, dict) and o.get("letter") and o.get("title"):
                titles[str(o["letter"]).upper()] = L.strip_non_bmp(str(o["title"])).strip()
        self._round_titles = titles
        ask_enabled = bool(((ctx.ask if ctx is not None else None) or {}).get("enabled"))
        out: List[Dict] = []
        for raw in msgs or []:
            try:
                m = self._ingest_one(raw, now, ask_enabled)
            except Exception as e:                     # one bad record never kills the frame loop
                self.log("ingest failed for %r: %r" % (raw.get("id") if isinstance(raw, dict) else raw, e))
                continue
            if m is not None:
                out.append(m)
        if len(self.messages) > KEEP:
            del self.messages[:-KEEP]
        self.pump(now)
        return out

    def _ingest_one(self, raw: Dict, now: float, ask_enabled: bool) -> Optional[Dict]:
        if not isinstance(raw, dict):
            return None
        self.ingested += 1
        m = dict(raw)
        name = str(m.get("name") or "").strip()
        key = name.lower()
        t = m.get("t")
        if not isinstance(t, (int, float)):
            t = now
            m["t"] = t
        history = (now - t) > HISTORY_S
        text = m.get("text") or ""
        kind, arg, letter = self.classify(text)
        badges = list(m.get("badges") or [])
        is_mod, is_owner = _badge_roles(badges)
        if key and key == self.channel_owner:      # the channel owner is the broadcaster even on webhook records
            is_mod = is_owner = True
            if "broadcaster" not in badges:
                badges.append("broadcaster")
        m["badges"] = badges
        cap = CAP_IDEA if kind == "idea" else (CAP_ASK if kind == "ask" else CAP_PLAIN)
        m.update({"kind": kind, "arg": arg, "letter": letter, "accepted": True, "notice": None,
                  "dropped": False, "drop_reason": None, "rate_limited": False, "first_ever": False,
                  "display_name": "?", "builder_n": None, "show_t": t + HOLD_S,
                  "text_clean": self.clean_text(text, cap), "history": history,
                  "verb": None, "verb_ok": None, "verb_reason": None})
        if m.get("type") not in (None, "message"):
            m.update({"dropped": True, "drop_reason": "not a message", "accepted": False})
            return m

        # -- mod commands act immediately (gated on badges); never rendered in the pane
        if kind == "mod":
            if is_mod:
                self._apply_mod(arg, name, is_owner, now, history)
                m["dropped"], m["drop_reason"] = True, "mod command"
                return m
            kind = m["kind"] = "plain"
            m["arg"] = ""

        # -- step 2: hidden users are ignored entirely (message, vote, idea, verb)
        if key in self.hidden:
            m.update({"dropped": True, "drop_reason": "hidden", "accepted": False})
            return m

        # -- step 5: word filter on the text (raw and cleaned, leet-normalised) -> drop message + vote/idea/verb; a strike
        hit = self._blocked(text) or self._blocked(m["text_clean"])
        if kind == "idea" or kind == "ask":
            hit = hit or self._blocked(arg)
        if hit:
            self.dropped += 1
            m.update({"dropped": True, "drop_reason": "blocklist", "accepted": False})
            if not history:
                self.log("dropped msg %s from %r (blocklist)" % (m.get("id"), name))
                self._strike(key, now)
            return m

        # -- builders.json / founders ; step 6: username filter -> "builder #N" ; the hold gate for name_for()
        m["first_ever"] = self._touch_builder(name, t, history)
        m["builder_n"] = self.builder_n(name)
        m["display_name"] = self._display_name(name) if name else "?"
        if key and (key not in self._first_show_t or m["show_t"] < self._first_show_t[key]):
            self._first_show_t[key] = m["show_t"]

        # -- votes count instantly (1 per user per round; a new letter moves it); the NAME waits for name_for()
        if kind == "vote" and letter:
            if self._round_opened_t is None or t >= self._round_opened_t - 1.0:
                self._votes[key] = (letter, t)
                if not history:
                    if self._cleared(key, now):
                        self._ack("%s stands at %s%s%s" % (self._at(key, now), letter, self._title_of(letter), self._closes_in(now)), now)
                    else:
                        # their first record this run is still inside its 3 s hold: the tuft on the land is nameless, so the
                        # same-frame ack says so (`someone new`, never `builder #N` for a name that is merely waiting) and the
                        # ack is repeated by name at show_t, the moment they first see themselves (pump())
                        self._ack("someone new stands at %s%s%s" % (letter, self._title_of(letter), self._closes_in(now)), now)
                        self._held_acks.append((float(self._first_show_t.get(key, m["show_t"])), key, letter))
                if key not in self._voted_this_round:
                    self._voted_this_round.add(key)
                    b = self.builders.get(key)
                    if b is not None:
                        b["votes"] = int(b.get("votes", 0)) + 1
                        self._builders_dirty = True
            else:
                m["accepted"] = False
        elif kind == "idea":
            if not arg:
                m["accepted"] = False
                if not history:
                    self._set_notice("!idea <what should change>", "warn", now)
            elif not history:
                self._ack("%s's idea is on the board" % self._at(key, now), now, dur=IDEA_ACK_S)
        elif kind == "theme":
            if history:
                m["accepted"] = False
            else:
                ok, note = self._check_theme(arg, now)
                m["accepted"] = ok
                if note:
                    self._set_notice(note, "warn", now)
                    m["notice"] = note
                if ok:
                    self._last_theme_t = now
                    self._set_notice("%s set theme: %s" % (self._at(key, now), arg), "info", now, THEME_NOTICE_S)
        elif kind == "help":
            if history:
                m["accepted"] = False
            elif self._last_help_t is None or now - self._last_help_t >= CMD_COOLDOWN_S:
                self._last_help_t = now
                self.help_until = now + HELP_SHOW_S
                self.help_by = key or None
            else:
                m["accepted"] = False
        elif kind == "stats":
            if history:
                m["accepted"] = False
            elif self._last_stats_t is None or now - self._last_stats_t >= CMD_COOLDOWN_S:
                self._last_stats_t = now
                self.stats_until = now + STATS_SHOW_S
                self.stats_by = key or None
            else:
                m["accepted"] = False
        elif kind == "ask":
            m["accepted"] = bool(arg) and ask_enabled and not history
        elif kind == "plain" and key:
            pv = self.parse_verb(text)
            if pv is not None:
                self._queue_verb(m, key, pv, t, now, history)
            elif not history and self.theme_hint_due(text) and (
                    self._last_theme_hint_t is None or now - self._last_theme_hint_t >= THEME_HINT_COOLDOWN_S):
                self._last_theme_hint_t = now
                self._set_notice("try: !theme " + " · ".join(L.PRESETS.keys()), "warn", now, HINT_S)
            elif not history:
                hint = self.hint_for(text)
                if hint and (key not in self._hint_t or now - self._hint_t[key] >= HINT_COOLDOWN_S):
                    self._hint_t[key] = now
                    m["hint"] = hint
                    self._set_notice(hint, "warn", now, HINT_S)

        # -- step 8: per-user render rate 1 line / 2 s (votes already counted, ideas already classified, verbs queued)
        last = self._last_render_t.get(key)
        if last is not None and t - last < RATE_S:
            m["rate_limited"] = True
            self.rate_limited += 1
        else:
            self._last_render_t[key] = t
            self.messages.append(m)
        return m

    # ------------------------------------------------------------------ strikes (WORLD.md 11.5)
    def _strike(self, key: str, now: float) -> None:
        if not key:
            return
        self.strikes[key] = self.strikes.get(key, 0) + 1
        if self.strikes[key] != STRIKES_MAX or key in self.burrowed:
            return
        self.burrowed[key] = STRIKES_REASON
        self._votes.pop(key, None)
        b = self.builders.get(key)
        if b is not None and self.session_id:
            b["burrowed_session"] = self.session_id
            self._builders_dirty = True
        self._pending = [p for p in self._pending if p["key"] != key or p.get("mod")]
        self._plank("%s's pip burrowed: %s" % (self._at(key, now), STRIKES_REASON), now, "warn", by=key)
        self._emit({"type": "burrowed", "pip": key, "reason": STRIKES_REASON})
        self.log("three strikes: %s burrowed for the session" % key)

    # ------------------------------------------------------------------ verbs
    def _known_pip(self, key: str) -> bool:
        """A chatter the world can have a pip for: in builders.json or already in world.json."""
        if key in self.builders:
            return True
        w = self.world
        try:
            return w is not None and w.world is not None and (w.world.pip(key) is not None)
        except Exception:
            return False

    def _queue_verb(self, m: Dict, key: str, pv: Tuple[str, Optional[str], Optional[str]], t: float, now: float,
                    history: bool) -> None:
        verb, target, word = pv
        form = self.verb_form(verb, target, word)
        # the leading-verb rule understood something other than the literal text: the plank echoes the reading
        typed = re.sub(r"\s+", " ", (m.get("text") or "").strip().lower().lstrip("!"))
        understood = form if typed != form and typed != form.replace("@", "") else None
        m["verb"] = {"verb": verb, "target": target, "arg": word, "form": form}
        if history:
            m["verb_ok"], m["verb_reason"] = False, "history"        # the previous instance already applied it
            return
        reason = self._check_verb(key, verb, target, word, t, now)
        if reason is not None:
            m["verb_ok"], m["verb_reason"] = False, reason
            self.verbs_refused += 1
            self._plank(reason, now, "warn", by=key)
            self._log_verb(now, key, verb, target, word, False, reason)
            return
        # reserve the slot NOW (a second try inside the hold must already see the limit); released if the world refuses
        if verb in VERB_COOLDOWN_S:
            self._verb_last[(key, verb)] = t
        if verb == "plant":
            self._plant_used[(key, word or "flower")] = self._plant_used.get((key, word or "flower"), 0) + 1
        elif verb == "camp":
            self._camp_used[key] = self._camp_used.get(key, 0) + 1
        elif verb == "gift" and target:
            self._gift_used.add((key, target))
        elif verb == "stack":
            self._stack_used[key] = self._stack_used.get(key, 0) + 1
        elif verb == "sow":
            self._sow_used.add(key)
        if verb == "sing":
            self._sing_global_t = t
        self._pending.append({"mid": m.get("id"), "key": key, "verb": verb, "target": target, "arg": word,
                              "t": t, "due": m["show_t"], "expires": m["show_t"] + VERB_RETRY_S,
                              "wait_until": m["show_t"] + VERB_WAIT_WORLD_S, "m": m, "mod": False,
                              "understood": understood})

    def _check_verb(self, key: str, verb: str, target: Optional[str], word: Optional[str], t: float,
                    now: float) -> Optional[str]:
        """Rate limits and argument rules (the verbs agent's half; the world refuses only what it cannot do).
        Returns the plank-ready refusal or None. Never echoes an unknown target (it could be anything)."""
        if verb in LATER_VERBS:
            return LATER_VERBS[verb]
        if target is not None:
            if target == key and verb == "gift":
                return "gifts are for other pips"
            if target == key and verb == "go":
                return "you are already there"
            if not self._known_pip(target):
                return "no pip by that name here"
            if target in self.banished or target in self.hidden:
                return "no pip by that name here"       # a hidden pip is not a destination or a target either
        if verb == "go" and target is None and not word:
            return GO_WHERE                              # OPENWORLD 6: the refusal names the place list
        if verb == "plant":
            kind = word or "flower"
            if kind not in PLANT_SESSION_CAP:
                return "plant what? flower · tree · reed"
            if self._plant_used.get((key, kind), 0) >= PLANT_SESSION_CAP[kind]:
                return PLANT_CAP_COPY[kind]
        if verb == "camp" and self._camp_used.get(key, 0) >= CAMP_SESSION_CAP:
            return "camp once a night · yours is pitched"
        if verb == "stack" and self._stack_used.get(key, 0) >= 3:
            return "three stones a night · the cairn has yours"
        if verb == "sow" and key in self._sow_used:
            return "one field a night · yours is sown"
        if verb == "name":
            w = (word or "")
            wl = w.lower()
            if len(w) > NICK_MAX or not w:
                return "names are 1-12 letters"
            if wl in RESERVED_NICKS or wl == self.channel_owner or wl in self.builders or self._known_pip(wl):
                return "that name belongs to a real chatter"
            if self._blocked(w):
                return "that word is not allowed"
        if verb == "gift" and (key, target) in self._gift_used:
            return "you already left %s a gift tonight" % self._at(target, now)
        cd = VERB_COOLDOWN_S.get(verb)
        if cd is not None:
            last = self._verb_last.get((key, verb))
            if last is not None and t - last < cd:
                left = cd - (t - last)
                if left >= 90:
                    return "%s again in %d min" % (verb, max(1, int(round(left / 60.0))))
                return "%s again in %d s" % (verb, max(1, int(round(left))))
        if verb == "sing" and self._sing_global_t is not None and t - self._sing_global_t < SING_GLOBAL_S:
            return "the land is still ringing · sing in %d s" % max(1, int(round(SING_GLOBAL_S - (t - self._sing_global_t))))
        return None

    def pump(self, now: float) -> None:
        """Apply every pending verb / mod world op whose hold has passed. Called by ingest(), visible() and
        notice() (the compositor calls those every frame), idempotent per `now`; a harness may call it directly."""
        now = float(now)
        self._now = max(self._now, now)
        if self._pumped_at == now:
            return
        self._pumped_at = now
        if self._held_acks:
            self._pump_held_acks(now)
        if not self._pending:
            return
        world = self._get_world(now)
        keep: List[Dict] = []
        for p in self._pending:
            if now < p["due"]:
                keep.append(p)
                continue
            key = p["key"]
            if not p.get("mod") and key in self.hidden:
                self._verb_done(p, False, "hidden", now, quiet=True)
                continue
            if world is None or not getattr(world, "booted", True):
                if now < p["wait_until"]:
                    keep.append(p)
                else:
                    self._verb_done(p, False, "the land did not hear that", now, quiet=True)
                continue
            try:
                ok, reason = self._apply(world, p, now)
            except Exception as e:                       # the world's problem never kills the frame loop
                self.log("verb %s by %s failed in the world: %r" % (p["verb"], key, e))
                ok, reason = False, "the land did not hear that"
            if not ok and reason in RETRY_REASONS and now < p["expires"]:
                keep.append(p)
                continue
            self._verb_done(p, ok, reason, now)
        self._pending = keep
        if world is not None and getattr(world, "booted", True):
            self._reconcile_votes(world, now)

    def _pump_held_acks(self, now: float) -> None:
        """The by-name vote ack for a chatter whose first record just cleared its hold (their vote was acked nameless
        at ingest). Skipped when they are hidden by then or their vote moved / was dropped (the world's own ack said so)."""
        due = [h for h in self._held_acks if now >= h[0]]
        if not due:
            return
        self._held_acks = [h for h in self._held_acks if now < h[0]]
        hidden = self.hidden
        for _show_t, key, letter in due:
            if key in hidden or (self._votes.get(key) or (None,))[0] != letter:
                continue
            self._ack("%s stands at %s%s%s" % (self._at(key, now), letter, self._title_of(letter), self._closes_in(now)), now)

    def held_rows(self, now: float) -> List[Dict]:
        """Real messages inside their 3 s hold (their `t` already reached, so a record stamped ahead of this clock waits
        unseen), oldest first, one per chatter, at most HELD_ROWS_MAX, as [{"name": <filtered display name, or None while
        the chatter's FIRST record of this run is the one waiting>}]. Nothing of the text is exposed: the chat log draws a
        muted `name: …` (or `someone is arriving...` when nameless) so a person sees their message was received
        before the hold clears (journal 030: the second `did it work?` attempt). [] when the pane is off or paused."""
        if not self.display or self.paused:
            return []
        hidden = self.hidden
        out: List[Dict] = []
        seen: Set[str] = set()
        for m in reversed(self.messages[-12:]):                  # newest first; one row per chatter; at most HELD_ROWS_MAX
            t = float(m.get("t") or 0)
            if m.get("dropped") or m.get("history") or not (t <= now < float(m.get("show_t") or 0)):
                continue                                         # `t <= now`: a record stamped ahead of this clock is not "in hold" yet
            key = (m.get("name") or "").lower()
            if not key or key in hidden or key in seen:
                continue
            seen.add(key)
            out.append({"name": self.name_for(key, now) if self._cleared(key, now) else None})
            if len(out) >= HELD_ROWS_MAX:
                break
        out.reverse()
        return out

    def _reconcile_votes(self, world, now: float) -> None:
        """The tally is who STANDS at a stone at close (rounds.py tally_source `platforms`): a vote whose pip walked off
        its stone (go / home / @name / camp before the round closed) is popped here in the same tick the world moved it,
        so vote_count(), the zero-vote plank, the card header and the stones agree. A vote younger than the hold plus
        the walk (VOTE_STAND_GRACE_S) is left alone: the pip may still be on its way. Only with an embodied world."""
        b = getattr(world, "behaviour", None)
        if b is None or not hasattr(b, "get"):
            return
        for key, (letter, t) in list(self._votes.items()):
            if now - float(t) < HOLD_S + VOTE_STAND_GRACE_S:
                continue
            try:
                e = b.get(key)
            except Exception:
                continue
            if e is None:
                continue
            plat = getattr(e, "platform", None)
            if plat is None or not e.is_awake():
                self._votes.pop(key, None)
            elif plat != letter:
                self._votes[key] = (plat, t)               # moved by a later letter the world already knows

    def _apply(self, world, p: Dict, now: float) -> Tuple[bool, str]:
        verb, actor, tgt, word = p["verb"], p["key"], p["target"], p["arg"]
        if p.get("mod"):
            return self._apply_mod_world(world, p, now)
        if verb in ("feed", "pet", "gift"):
            asleep = self._target_asleep(world, tgt or actor)
            ok, reason = world.command(verb, actor, target=(tgt or None), now=now)
            if ok:
                p["asleep"] = asleep
            return ok, reason
        if verb == "go":
            # ("go", actor, target=key|None, arg=place|direction|"home"): the scene routes on the coarse grid
            return world.command("go", actor, target=(tgt or None), arg=word, now=now)
        if verb == "plant":
            return world.command("plant", actor, arg=(word or "flower"), now=now)
        if verb in ("camp", "fire", "wave", "sit", "dance", "forget"):
            return world.command(verb, actor, now=now)
        if verb == "name":
            ok, reason = world.command("name", actor, arg=word, now=now)
            if not ok and reason == "unknown verb":
                return self._set_nickname(world, actor, word)
            return ok, reason
        if verb in LATER_VERBS:
            return False, LATER_VERBS[verb]
        return False, "unknown verb"

    @staticmethod
    def _target_asleep(world, key: str) -> bool:
        try:
            e = world.behaviour.get(key)
            return e is None or not e.is_awake()
        except Exception:
            return False

    @staticmethod
    def _set_nickname(world, key: str, word: Optional[str]) -> Tuple[bool, str]:
        """Until the world core grows a `name` verb: write pips[key].nickname (WORLD.md 3.2) through WorldState."""
        try:
            ws = world.world
            p = ws.pip(key)
            if p is None:
                return False, "your pip is not awake yet"
            p["nickname"] = word
            ws.dirty = True
            return True, "ok"
        except Exception:
            return False, "the cave did not hear that"

    def _verb_done(self, p: Dict, ok: bool, reason: str, now: float, quiet: bool = False) -> None:
        key, verb, tgt, word = p["key"], p["verb"], p["target"], p["arg"]
        m = p.get("m")
        if isinstance(m, dict):
            m["verb_ok"], m["verb_reason"] = ok, reason
        if p.get("mod"):
            self._log_verb(now, key, verb, tgt, word, ok, reason)
            return
        if ok:
            self.verbs_ok += 1
            self._success_notice(p, now)
        else:
            self.verbs_refused += 1
            if verb in VERB_COOLDOWN_S and self._verb_last.get((key, verb)) == p["t"]:
                self._verb_last.pop((key, verb), None)            # a refused try costs no cooldown
            if verb == "plant":
                k = (key, word or "flower")
                if self._plant_used.get(k, 0) > 0:
                    self._plant_used[k] -= 1
            elif verb == "camp":
                if self._camp_used.get(key, 0) > 0:
                    self._camp_used[key] -= 1
            elif verb == "stack":
                if self._stack_used.get(key, 0) > 0:
                    self._stack_used[key] -= 1
            elif verb == "sow":
                self._sow_used.discard(key)
            elif verb == "gift" and tgt:
                self._gift_used.discard((key, tgt))
            if not quiet:
                self._plank(self._safe_reason(reason, verb), now, "warn", by=key)
        self._log_verb(now, key, verb, tgt, word, ok, reason)

    def _safe_reason(self, reason: str, verb: Optional[str] = None) -> str:
        """The world's reasons are plank-ready except when they echo a typed name (`no pip called @x here`, `too close
        to @kai's camp`): a raw `@word` never reaches a pixel, so it is scrubbed here. `unknown verb` from an older
        world core reads as the verb not being on the land yet."""
        r = reason or "not now"
        if r == "unknown verb":
            return "%s is not on this land yet" % (verb or "that")
        if "@" in r:
            if re.match(r"^no (pip|one) ", r):
                return "no pip by that name here"
            return re.sub(r"@[A-Za-z0-9_]+", "someone", r)
        return r

    def _success_notice(self, p: Dict, now: float) -> None:
        key, verb, tgt, arg = p["key"], p["verb"], p["target"], p["arg"]
        me = self._at(key, now)
        if verb == "forget":
            self._plank("%s's pip forgot everything" % me, now, "info", by=key)
        elif verb == "name":
            self._emit({"type": "nickname", "pip": key, "nickname": p["arg"]})
            self._plank("%s's pip is called %s now" % (me, p["arg"]), now, "info", by=key)
        elif verb == "gift":
            self._plank("%s left a gift at %s's camp" % (me, self._at(tgt, now)), now, "info", by=key)
        elif verb in ("feed", "pet") and p.get("asleep") and tgt and tgt != key:
            what = "left a berry at %s's camp" if verb == "feed" else "petted %s's sleeping pip"
            self._plank("%s %s" % (me, what % self._at(tgt, now)), now, "info", by=key)
        elif verb == "go":
            # the plank says what was understood (OPENWORLD 15): the destination, filtered name if it is a person
            if tgt:
                self._plank("%s walks to %s" % (me, self._at(tgt, now)), now, "info", by=key)
            elif arg == "home":
                self._plank("%s heads home" % me, now, "info", by=key)
            elif arg in DIRECTIONS:
                self._plank("%s walks %s" % (me, arg), now, "info", by=key)
            elif arg:
                self._plank("%s walks to %s" % (me, PLACE_LABELS.get(arg, arg)), now, "info", by=key)
        elif p.get("understood"):
            # `plant a flower` -> `plant flower`: the world's own event carries the effect; this echoes the reading.
            # Rebuilt here so a target is drawn through name_for(), never as the typed `@word`.
            parts = [verb]
            if tgt:
                parts.append(self._at(tgt, now))
            if arg:
                parts.append(str(arg))
            self._plank("%s · %s" % (me, " ".join(parts)), now, "info", by=key, dur=3.0)

    def _log_verb(self, now: float, key: str, verb: str, tgt: Optional[str], word: Optional[str], ok: bool,
                  reason: str) -> None:
        rec = {"ts": epoch_to_iso(now), "by": key, "verb": verb, "target": tgt, "arg": word, "ok": ok, "reason": reason}
        self.verb_log.append(rec)
        if len(self.verb_log) > VERB_LOG_KEEP:
            del self.verb_log[:-VERB_LOG_KEEP]
        self._emit(dict(rec, type="verb"))

    # ------------------------------------------------------------------ mod commands
    def _apply_mod(self, arg: str, by: str, is_owner: bool, now: float, history: bool = False) -> None:
        parts = arg.split(" ", 1)
        cmd = parts[0].lower()
        target = parts[1].strip().split(" ")[0].lstrip("@").lower() if len(parts) > 1 and parts[1].strip() else ""
        if cmd in BROADCASTER_ONLY and not is_owner:
            return
        note = None
        # Idempotent re-application (a record < 60 s old re-read after a relay deploy restart, state.mod already
        # carries the effect): apply silently, no new mod.actions entry, no notice, no activity line.
        already = ((cmd == "hide" and target in self._hidden) or (cmd == "unhide" and target not in self.hidden)
                   or (cmd == "pause" and self.paused) or (cmd == "resume" and not self.paused)
                   or (cmd == "kill" and not self.display) or (cmd == "unkill" and self.display)
                   or (cmd == "banish" and target in self.banished) or (cmd == "unbanish" and target not in self.banished))
        if cmd == "hide" and target:
            if target == self.channel_owner:
                return                                  # nobody hides the broadcaster
            self._hidden.add(target)
            self._votes.pop(target, None)
            b = self.builders.get(target)
            if b is not None and b.pop("burrowed_session", None) is not None:
                self._builders_dirty = True             # a mod hide supersedes a strikes burrow
            note = "mod action: hid %s" % self._at(target, now)
        elif cmd == "unhide" and target:
            if target in self.banished:
                if not history:
                    self._set_notice("that user is banished · !unbanish lifts it", "warn", now)
                return
            self._hidden.discard(target)
            self.burrowed.pop(target, None)
            self.strikes.pop(target, None)
            self._unhidden_t[target] = now
            b = self.builders.get(target)
            if b is not None and b.pop("burrowed_session", None) is not None:
                self._builders_dirty = True
            note = "mod action: unhid %s" % self._at(target, now)
        elif cmd == "banish" and target:
            if target == self.channel_owner:
                return
            self._hidden.add(target)
            self.banished.add(target)
            self._votes.pop(target, None)
            self._pending = [p for p in self._pending if p["key"] != target or p.get("mod")]
            b = self.builders.get(target)
            if b is not None:
                b["banished"] = True
                b.pop("burrowed_session", None)
                self._builders_dirty = True
            self._queue_mod_op("banish", by, target, now)
            note = "mod action: banished %s" % self._at(target, now)
            self._emit({"type": "banish", "pip": target, "by": (by or "").lower()})
        elif cmd == "unbanish" and target:
            self.banished.discard(target)
            self._hidden.discard(target)
            self._unhidden_t[target] = now
            b = self.builders.get(target)
            if b is not None and b.pop("banished", None) is not None:
                self._builders_dirty = True
            self._queue_mod_op("unbanish", by, target, now)
            note = "mod action: unbanished %s" % self._at(target, now)
            self._emit({"type": "unbanish", "pip": target, "by": (by or "").lower()})
        elif cmd == "rename" and target:
            self._queue_mod_op("rename", by, target, now)
            note = "mod action: cleared %s's nickname" % self._at(target, now)
            self._emit({"type": "rename", "pip": target, "by": (by or "").lower()})
        elif cmd == "pause":
            if not self.paused:
                self.paused, self._pause_t = True, now
            note = "chat paused by mod"
        elif cmd == "resume":
            self.paused, self._pause_t = False, None
            note = "chat resumed"
        elif cmd == "kill":
            self.display = False
            note = "chat hidden by mod"
        elif cmd == "unkill":
            self.display = True
            note = "chat visible again"
        elif cmd == "clear":
            note = "backlog cleared by mod"          # RoundEngine wipes state.ideas when it mirrors the action
        else:
            return
        if history or already:
            return                                      # re-applied silently after a restart
        self.mod_actions.append({"ts": epoch_to_iso(now), "by": by, "action": cmd, "target": target or None})
        # The plank is the person-facing slot (WORLD.md 2.2). Per-user mod ops (hide/unhide/banish/unbanish/rename) are
        # NOT announced there: naming a hidden user is a leak and `mod action: hid @builder #6` is jargon to a stranger.
        # They stay on the record (state.mod.actions -> chat log shield row, activity.jsonl). Chat-wide state changes
        # (pause/resume/kill/unkill/clear) still get the 4 s line, because every viewer is affected.
        if note and cmd in ("pause", "resume", "kill", "unkill", "clear"):
            self._set_notice(note, "warn", now)
        self.log("mod %s %s by %s" % (cmd, target or "", by))

    def _queue_mod_op(self, op: str, by: str, target: str, now: float) -> None:
        """A mod op the world must mirror (banish / unbanish / rename): due now, waits for a world if none yet."""
        self._pending.append({"mid": None, "key": target, "verb": op, "target": target, "arg": None, "by": (by or "").lower(),
                              "t": now, "due": now, "expires": now + VERB_RETRY_S, "wait_until": now + VERB_WAIT_WORLD_S,
                              "m": None, "mod": True})

    def _apply_mod_world(self, world, p: Dict, now: float) -> Tuple[bool, str]:
        op, target, by = p["verb"], p["target"], p.get("by") or ""
        ws = getattr(world, "world", None)
        if op == "banish":
            ok, reason = world.command("banish", by, target=target, now=now)
            if ok:
                return True, "ok"
            # the mod's own pip may not be awake (world.command insists); the world API exposes the pieces
            try:
                world.behaviour.entities.pop(target, None)
                if ws is not None and ws.banish(target, now):
                    world.behaviour.events.append({"type": "banish", "pip": target})
                    return True, "ok"
                return False, "no such pip"
            except Exception as e:
                return False, "banish failed: %r" % (e,)
        if op == "unbanish":
            try:
                return (True, "ok") if (ws is not None and ws.unbanish(target)) else (False, "not banished")
            except Exception as e:
                return False, "unbanish failed: %r" % (e,)
        if op == "rename":
            try:
                ok, reason = world.command("rename", by, target=target, now=now)
                if ok or reason != "unknown verb":
                    return ok, ("ok" if ok else reason)
            except Exception:
                pass
            ok, reason = self._set_nickname(world, target, None)    # older world cores without a `rename` verb
            return ok, ("ok" if ok else "no such pip")
        return False, "unknown mod op"

    def _check_theme(self, preset: str, now: float) -> Tuple[bool, Optional[str]]:
        if preset not in L.PRESETS:
            return False, "themes: " + " ".join(sorted(L.PRESETS.keys()))
        if self._last_theme_t is not None and now - self._last_theme_t < THEME_COOLDOWN_S:
            return False, "theme cooldown %d s" % max(1, int(round(THEME_COOLDOWN_S - (now - self._last_theme_t))))
        return True, None

    def _set_notice(self, text: str, level: str, now: float, dur: float = NOTICE_S) -> None:
        self._notice = (text, level, now + dur, now)

    def _ack(self, text: str, now: float, dur: float = VOTE_ACK_S) -> None:
        """Same-frame public acknowledgement (`@name stands at A · light: gold · closes in 1:27`) for
        VOTE_ACK_S. Several accepted in one ingest batch share the strip (the panel truncates to its width) so no voter
        is skipped. It has priority over the regular notice while it lasts; the regular notice keeps its own expiry."""
        cur = self._ack_notice
        if cur and cur[2] == now + dur:
            text = cur[0] + " · " + text
        self._ack_notice = (text, "ok", now + dur, now)

    def notice(self, now: float):
        """(text, level, start, until) of the live notice: a person's answer, NEWEST FIRST (HUD pass, journal 028: each ack has
        its own timer; a 5 s vote ack must not hide the refusal or hint that came after it). The start lets the world
        panel rank its own person-facing lines against this one by age."""
        self.pump(now)
        live = [n for n in (self._ack_notice, self._notice) if n and now < n[2]]
        if not live:
            return None
        n = max(live, key=lambda q: q[3] if len(q) > 3 else 0.0)
        return (n[0], n[1], n[3] if len(n) > 3 else None, n[2])      # + until: the plank fades its last 0.5 s (journal 034)

    # ------------------------------------------------------------------ views
    @property
    def hidden(self) -> Set[str]:
        """Everyone the world must not draw or hear: mod hides, three-strikes burrows, banished. Mirrored by the
        RoundEngine into state.mod.hidden_users, which is what CaveScene reads to burrow a pip."""
        if not self.burrowed:
            return self._hidden
        return self._hidden | set(self.burrowed)

    @property
    def founders(self) -> List[str]:
        """Display names (name_for) of the first 10 chatters of this session, minus anyone hidden."""
        hidden = self.hidden
        return [self.name_for(k) for k in self._founders if k not in hidden]

    def visible(self, now: float, n: int = 10) -> List[Dict]:
        """Moderated messages past their 3 s hold, newest last. [] when the kill switch is on.
        While paused the pane is frozen at the moment of the pause (votes keep counting)."""
        self.pump(now)
        if not self.display:
            return []
        cutoff = now if not (self.paused and self._pause_t is not None) else min(now, self._pause_t)
        hidden = self.hidden
        out = []
        for m in self.messages:
            if m.get("show_t", 0) > cutoff:
                continue
            if (m.get("name") or "").lower() in hidden:
                continue
            out.append(m)
        return out[-n:]

    def reset_round(self, opened_t: float) -> None:
        """New round opened at opened_t: drop votes cast before it, keep later ones (a round resumed
        from state.json after a compositor restart re-tallies the votes already in chat.jsonl)."""
        self._round_opened_t = opened_t
        self._votes = {k: v for k, v in self._votes.items() if v[1] >= opened_t - 1.0}
        self._voted_this_round = set(self._votes.keys())

    def tallies(self, now: Optional[float] = None) -> Dict[str, List[str]]:
        """Voters per letter in vote order, as name_for() names (filtered AND held: a first-time chatter inside
        their 3 s hold reads `builder #N`, then their name). The count is honest at once, the name waits."""
        t: Dict[str, List[str]] = {"A": [], "B": [], "C": []}
        hidden = self.hidden
        for key, (letter, when) in sorted(self._votes.items(), key=lambda kv: kv[1][1]):
            if letter in t and key not in hidden:
                t[letter].append(self.name_for(key, now))
        return t

    def vote_count(self) -> int:
        hidden = self.hidden
        return sum(1 for k in self._votes if k not in hidden)

    def recent_votes(self, n: int = 5, now: Optional[float] = None) -> List[Tuple[str, str, float]]:
        hidden = self.hidden
        items = [kv for kv in sorted(self._votes.items(), key=lambda kv: kv[1][1]) if kv[0] not in hidden]
        return [(self.name_for(k, now), v[0], v[1]) for k, v in items[-n:]]

    def stats(self) -> Dict:
        return {"ingested": self.ingested, "dropped": self.dropped, "rate_limited": self.rate_limited,
                "hidden": sorted(self.hidden), "burrowed": dict(self.burrowed), "banished": sorted(self.banished),
                "strikes": dict(self.strikes), "paused": self.paused, "display": self.display,
                "votes": self.vote_count(), "builders": len(self.builders), "founders": self.founders,
                "blocklist_terms": len(self.words.block_terms), "allowlist_words": len(self.words.allow),
                "verbs_ok": self.verbs_ok, "verbs_refused": self.verbs_refused, "pending_verbs": len(self._pending),
                "world_attached": self.world is not None}


def _self_test() -> int:
    """`$PYTHON stream/chat_bridge.py`: the leading-verb rule table (OPENWORLD 6) as assertions. Exit 0 on pass."""
    P = ChatBridge.parse_verb
    cases = {
        # exact-token forms kept
        "feed": ("feed", None, None), "feed @Sami": ("feed", "sami", None), "FEED  sami": ("feed", "sami", None),
        "!pet": ("pet", None, None), "gift @lu": ("gift", "lu", None), "gift": None, "feed @sami now": None,
        "plant": ("plant", None, "flower"), "wave": ("wave", None, None), "sit": ("sit", None, None),
        "dance": ("dance", None, None), "forget": ("forget", None, None), "name Muffin": ("name", None, "Muffin"),
        "name @sam": None, "name averyverylongname": None, "teach ratio": ("teach", None, "ratio"),
        # leading-verb rule (owner feedback, journal 019 addendum)
        "plant a flower": ("plant", None, "flower"), "plant a tree": ("plant", None, "tree"),
        "plant some reeds": ("plant", None, "reed"), "Plant a Flower!": ("plant", None, "flower"),
        "go to the river": ("go", None, "river"), "go river": ("go", None, "river"), "walk north": ("go", None, "north"),
        "head to the ford": ("go", None, "ford"), "north": ("go", None, "north"), "go home": ("go", None, "home"),
        "home": ("go", None, "home"), "go to my camp": ("go", None, "home"), "go @kai": ("go", "kai", None),
        "go to @kai": ("go", "kai", None), "go": ("go", None, None), "go to the sea": ("go", None, "shore"),
        "light the fire": ("fire", None, None), "light": ("fire", None, None), "fire": ("fire", None, None),
        "light the hearth": ("fire", None, None), "camp": ("camp", None, None), "camp here": ("camp", None, None),
        "pitch a tent": ("camp", None, None), "pitch": None,
        # plain chat, never a verb
        "go away": None, "plant based": None, "go go go": None, "plant @atleastonce": None, "go kai": None,
        "I love to sing in the shower": None, "right?": None, "I dug it": None, "dig": None, "dig now": None,
        "duck": None, "the north": None, "go to the river please now": None, "go https://x.com": None,
        "go @kai river": None, "feed the river": None, "camp fire": None, "sit down": None,
        # stubs parse (so they never bubble as commands elsewhere) and are refused later
        "sow": ("sow", None, None), "sow a field": ("sow", None, None), "harvest": ("harvest", None, None),
        "stack": ("stack", None, None), "stack stones": ("stack", None, None), "swim": ("swim", None, None),
        "sing": ("sing", None, None), "explore": ("explore", None, None), "water @kai": ("water", "kai", None),
        "water": None,
    }
    bad = []
    for txt, want in cases.items():
        got = P(txt)
        if got != want:
            bad.append((txt, got, want))
    for txt, got, want in bad:
        print("FAIL parse_verb(%r) -> %r, want %r" % (txt, got, want))
    # unparsed-with-hint (HUD pass, journal 028): the exact canonical token, never the typed words, never an @name
    HINTS = {"go north further": "try: go north", "can you go to the river please": "try: go river",
             "build a hut here": "try: camp", "plant some trees please": "try: plant tree",
             "warm us up": "try: fire", "I pick B": "try: B", "kick would be nice": "try: !theme kick",
             "go north @hiddenname": "try: go north", "go there": "try: go river",
             "river please": "try: go river", "bbbbb": "try: B", "AAA": "try: A", "!ccc": "try: C",
             # false positives are worse than silence
             "I love trees": None, "the river is pretty": None, "hello land": None, "anyone here": None, "hello there": None,
             "I'm going home now": None, "further than that": None,
             "I love trees and rivers and the long grass of home ok": None, "go https://x.com/north": None,
             "I would go north if I could but I cannot right now ok": None}
    for txt, want in HINTS.items():
        assert P(txt) is None, txt
        got = ChatBridge.hint_for(txt)
        if got != want:
            bad.append((txt, got, want))
            print("FAIL hint_for(%r) -> %r, want %r" % (txt, got, want))
        assert got is None or "@" not in got, (txt, got)
    # every token of every message with > 4 tokens is chat, whatever it starts with
    assert P("go to the river now please") is None
    assert P("plant a flower a flower") is None
    # the rule never fires on a URL
    assert P("go www.river.com") is None
    # classify untouched
    b = ChatBridge("/tmp/lg-verbs")
    assert b.classify("A") == ("vote", "", "A") and b.classify("!b")[2] == "B" and b.classify("abc")[0] == "plain"
    assert b.classify("!idea show the diff bigger") == ("idea", "show the diff bigger", None)
    assert b.classify("pause bot") == ("mod", "pause", None)
    assert b.classify("  Pause   BOT ") == ("mod", "pause", None)
    assert b.classify("resume bot") == ("mod", "resume", None)
    assert b.classify("pause the bot") == ("plain", "", None)
    assert b.classify("pause bot please") == ("plain", "", None)
    assert b.classify("!hide @spammer") == ("mod", "hide @spammer", None)
    # refusals are amber (level "warn") and scrub raw names
    assert b._safe_reason("no pip called @troll here", "feed") == "no pip by that name here"
    assert b._safe_reason("too close to @kai's camp", "camp") == "too close to someone's camp"
    assert b._safe_reason("unknown verb", "go") == "go is not on this land yet"
    assert L.COLORS["warn"].upper() == "#FFB020"
    print("parse_verb: %d cases, %d failed" % (len(cases), len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(_self_test())
