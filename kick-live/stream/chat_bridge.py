"""chat_bridge.py - ChatBridge: the CONCEPT 7 command parser and the CONCEPT 7.1 moderation pipeline.

The StateStore tails chat.jsonl (both record shapes, de-duped on id) and the compositor hands the
new normalised messages to ChatBridge.ingest() every frame. Nothing from chat reaches a pixel or a
name slot (chat pane, ballot voter names, founders strip, ticker) without passing through here.

Pipeline (CONCEPT 7.1, in order, for every record):
  1. 3 s render hold            show_t = t + 3 s; visible() only returns messages past their hold so the
                                filter and a human !hide can beat the render
  2. hidden / paused check      mod.hidden_users (from !hide and state.json) -> the record is ignored
                                entirely (message, vote, idea); !pause freezes the pane, votes still count
  3. URL strip                  any token with a scheme, www. or a .tld pattern -> "[link]"
  4. non-BMP strip + emotes     astral code points removed, "[emote:123:name]" -> ":name:"
  5. word filter                stream/moderation/blocklist.txt (leet-normalised, whole-word; suffix tolerant
                                for terms >= 5 letters; "n i g g e r" runs re-joined); a hit drops the
                                message AND its vote/idea and increments .dropped (moderation.dropped)
  6. username filter            same list on the username -> display_name "builder #N" everywhere
  7. length caps                120 chars displayed (60 for !idea, 140 for !ask)
  8. per-user render rate       1 rendered line per user per 2 s; excess lines never reach the pane
                                (votes still count, !idea still reaches the RoundEngine)
  9. kill switch                chat.display (!kill / !unkill): visible() -> [] ; panels draw
                                "chat hidden by mod" for every name slot
Votes are counted instantly (a bare letter cannot be offensive) but the voter's name still goes
through 2, 6 and 9 before it is drawn (tallies()/recent_votes() apply them).

Commands (case-insensitive, after moderation):
  A/B/C/!a/!b/!c        trimmed text matches ^!?[abc]$ EXACTLY; 1 vote per user per round, a new letter moves it
  !idea <text>          nominate (arg capped at 60); the RoundEngine dedupes (+N) and enforces 1/user/3 min
  !theme <preset>       one of layout.PRESETS (8); 60 s global cooldown; unknown -> 4 s list notice,
                        cooldown -> "theme cooldown 41 s"
  !stats / !help        30 s global cooldown each; stats_until = now + 10 s, help_until = now + 20 s
  !ask <question>       arg capped at 140; accepted only while state.ask.enabled
  !hide u / !unhide u / !pause / !resume / !clear     broadcaster or moderator badge
  !kill / !unkill                                     broadcaster only (also the KICK_CHANNEL owner)

Public surface (exact, see stream/COMPOSITOR_API.md section 5):
  ChatBridge(run_dir, log=None, blocklist_path=None)
  .ingest(msgs, now, ctx=None) -> list[msg]   classified + moderated copies of the new messages
  .visible(now, n=10) -> list[msg]            moderated, past the hold, newest last; [] when display is off
  .tallies() -> {"A": [names], "B": [...], "C": [...]}   voters (display names) in vote order, this round
  .vote_count() -> int ; .recent_votes(n=5) -> [(name, letter, t)]
  .reset_round(opened_t)                      RoundEngine: keep only votes with t >= opened_t - 1
  .notice(now) -> (text, level) | None ; .help_until ; .stats_until
  .founders -> list[str] ; .builders -> dict ; .builder_n(name) ; .flush(now, force=False)
  .display ; .paused ; .hidden (set of lowercase names) ; .dropped ; .mod_actions ; .new_builders
  ChatBridge.classify(text) -> (kind, arg, letter)   [static]
  ChatBridge.clean_text(text, cap) -> str            [static]

Message dict returned by ingest (and held in ctx.chat):
  {id, ts, t, name, text, text_clean, color, badges[], source, type,
   kind: vote|idea|theme|stats|help|ask|mod|plain, arg, letter, accepted, notice, dropped, drop_reason,
   rate_limited, display_name, builder_n, first_ever, show_t}

builders.json ($RUN_DIR/builders.json, atomic, flushed every 10 s, persists across sessions):
  {"name_lower": {"n": 1, "name": "Sam", "first_seen": iso, "last_seen": iso, "sessions": 3, "votes": 41, "ships": 6}}

History: records already in chat.jsonl at boot (older than HISTORY_S) are ingested for founders,
builders and tallies, but !idea/!theme/!stats/!help side effects, notices and builder blips are NOT
replayed (the previous compositor instance already did that). Mod commands in history are re-applied
silently (no activity line) so a !hide survives a compositor restart even if state.json lagged.

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
NOTICE_S = 4.0
THEME_NOTICE_S = 10.0        # `@name set theme: ember` lives here (CONCEPT 7 said header toast; QA 2026-09-25 moved it so
                             # the SHIPPED/FAILED scoreline never disappears from the thumbnail)
VOTE_ACK_S = 1.5             # `@name voted A` on the pinned strip within the same frame as ingest (QA rank 3a): the
                             # name already passed steps 2 and 6, which are synchronous; the message body keeps HOLD_S
HELP_SHOW_S = 20.0
STATS_SHOW_S = 10.0
CAP_PLAIN, CAP_IDEA, CAP_ASK = 120, 60, 140
KEEP = 200                   # moderated messages kept in memory
HISTORY_S = 60.0             # a record older than this at ingest time is boot history
BLOCKLIST_RELOAD_S = 5.0
BUILDERS_FLUSH_S = 10.0

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

MOD_CMDS = {"hide", "unhide", "pause", "resume", "kill", "unkill", "clear"}
BROADCASTER_ONLY = {"kill", "unkill"}
KINDS = ("vote", "idea", "theme", "stats", "help", "ask", "mod", "plain")


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


class ChatBridge(object):
    def __init__(self, run_dir: str, log=None, blocklist_path: Optional[str] = None):
        self.run_dir = run_dir
        self.log = log or (lambda m: sys.stderr.write("chat_bridge: %s\n" % m))
        here = os.path.dirname(os.path.abspath(__file__))
        self.blocklist_path = blocklist_path or os.path.join(here, "moderation", "blocklist.txt")
        self.channel_owner = (os.environ.get("KICK_CHANNEL") or "atleastonce").strip().lower()
        self._block_terms: List[str] = []                  # normalised terms (words and phrases)
        self._block_mtime = None
        self._block_checked: Optional[float] = None

        self.messages: List[Dict] = []                     # moderated, renderable (never dropped ones)
        self._votes: Dict[str, Tuple[str, float]] = {}     # name_lower -> (letter, t)
        self._voted_this_round: Set[str] = set()           # for builders[].votes (1 per user per round)
        self._round_opened_t: Optional[float] = None
        self._last_render_t: Dict[str, float] = {}
        self._notice: Optional[Tuple[str, str, float]] = None   # text, level, until
        self._ack_notice: Optional[Tuple[str, str, float]] = None   # `@name voted A`: its own slot, so a !theme / cooldown
                                                                    # notice landing in the same batch cannot hide the ack
        self._last_theme_t: Optional[float] = None
        self.help_until = 0.0
        self.stats_until = 0.0
        self._last_help_t: Optional[float] = None
        self._last_stats_t: Optional[float] = None
        self.display = True
        self.paused = False
        self._pause_t: Optional[float] = None
        self.hidden: Set[str] = set()
        self.dropped = 0                                    # moderation.dropped (blocklist hits)
        self.rate_limited = 0
        self._founders: List[str] = []                     # display names of the first 10 chatters (see .founders)
        self._session_seen: Set[str] = set()
        self.new_builders = 0                               # first-ever chatters this run (audio cue)
        self.mod_actions: List[Dict] = []
        self._state_synced = False
        self.ingested = 0

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
            if len(self._founders) < 10:
                shown = self._display_name(name)
                if k not in [f[0] for f in self._founders]:
                    self._founders.append((k, shown))
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

    # ------------------------------------------------------------------ blocklist
    def _load_blocklist(self, now: float) -> None:
        if self._block_checked is not None and now - self._block_checked < BLOCKLIST_RELOAD_S:
            return
        self._block_checked = now
        try:
            st = os.stat(self.blocklist_path)
        except OSError:
            if self._block_terms:
                self.log("blocklist missing: %s (keeping %d terms)" % (self.blocklist_path, len(self._block_terms)))
            return
        if st.st_mtime == self._block_mtime:
            return
        self._block_mtime = st.st_mtime
        terms: List[str] = []
        try:
            with open(self.blocklist_path, "r", encoding="utf-8") as fh:
                for ln in fh:
                    ln = ln.split("#", 1)[0].strip()
                    if not ln:
                        continue
                    n = _norm(ln)
                    if n and n not in terms:
                        terms.append(n)
        except Exception as e:
            self.log("blocklist read failed: %r" % (e,))
            return
        self._block_terms = terms
        self.log("blocklist loaded: %d terms from %s" % (len(terms), self.blocklist_path))

    @staticmethod
    def _token_hit(tok: str, term: str) -> bool:
        if tok == term:
            return True
        if len(term) >= SUFFIX_MIN_LEN and tok.startswith(term):
            return tok[len(term):] in _SUFFIXES
        return False

    def _blocked(self, text: str) -> Optional[str]:
        """Returns the matching blocklist term (normalised) or None."""
        if not self._block_terms or not text:
            return None
        n = _norm(text)
        if not n:
            return None
        tokens = n.split(" ")
        # spaced-out evasion: "n i g g e r" -> join runs of >= SPACED_RUN_MIN single-letter tokens
        joined: List[str] = []
        run: List[str] = []
        for tok in tokens + [""]:
            if len(tok) == 1:
                run.append(tok)
                continue
            if len(run) >= SPACED_RUN_MIN:
                joined.append("".join(run))
            run = []
        padded = " " + n + " "
        for term in self._block_terms:
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

    # ------------------------------------------------------------------ classify / clean
    @staticmethod
    def classify(text: str) -> Tuple[str, str, Optional[str]]:
        """-> (kind, arg, letter). Vote iff the trimmed text is exactly ^!?[abc]$ (case-insensitive)."""
        t = (text or "").strip()
        m = VOTE_RE.match(t)
        if m:
            return "vote", "", m.group(1).upper()
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
        return "plain", "", None

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

    def _display_name(self, name: str) -> str:
        if self._blocked(name):
            n = self.builder_n(name)
            return "builder #%s" % (n if n is not None else "?")
        return name

    # ------------------------------------------------------------------ ingest
    def _sync_state(self, ctx) -> None:
        """Merge mod state from state.json (once at boot, plus hidden_users every call)."""
        if ctx is None:
            return
        state_mod = ctx.mod or {}
        for u in state_mod.get("hidden_users") or []:
            self.hidden.add(str(u).lower())
        if self._state_synced:
            return
        self._state_synced = True
        cfg = ctx.chat_cfg or {}
        if cfg.get("display") is False:
            self.display = False
        if state_mod.get("paused") is True:
            self.paused = True
            self._pause_t = ctx.now

    def ingest(self, msgs: List[Dict], now: float, ctx=None) -> List[Dict]:
        self._load_blocklist(now)
        self._sync_state(ctx)
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
                  "display_name": name or "?", "builder_n": None, "show_t": t + HOLD_S,
                  "text_clean": self.clean_text(text, cap), "history": history})

        # -- mod commands act immediately (gated on badges); never rendered in the pane
        if kind == "mod":
            if is_mod:
                self._apply_mod(arg, name, is_owner, now, history)
                m["dropped"], m["drop_reason"] = True, "mod command"
                return m
            kind = m["kind"] = "plain"
            m["arg"] = ""

        # -- step 2: hidden users are ignored entirely (message, vote, idea)
        if key in self.hidden:
            m.update({"dropped": True, "drop_reason": "hidden", "accepted": False})
            return m

        # -- step 5: word filter on the text (raw and cleaned, leet-normalised) -> drop message + vote/idea
        hit = self._blocked(text) or self._blocked(m["text_clean"])
        if kind == "idea" or kind == "ask":
            hit = hit or self._blocked(arg)
        if hit:
            self.dropped += 1
            m.update({"dropped": True, "drop_reason": "blocklist", "accepted": False})
            if not history:
                self.log("dropped msg %s from %r (blocklist)" % (m.get("id"), name))
            return m

        # -- builders.json / founders ; step 6: username filter -> "builder #N"
        m["first_ever"] = self._touch_builder(name, t, history)
        m["builder_n"] = self.builder_n(name)
        m["display_name"] = self._display_name(name) if name else "?"

        # -- votes count instantly (1 per user per round; a new letter moves it)
        if kind == "vote" and letter:
            if self._round_opened_t is None or t >= self._round_opened_t - 1.0:
                self._votes[key] = (letter, t)
                if not history:
                    self._ack("@%s voted %s" % (m["display_name"], letter), now)
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
                self._ack("@%s nominated an idea" % m["display_name"], now)
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
                    self._set_notice("@%s set theme: %s" % (m["display_name"], arg), "info", now, THEME_NOTICE_S)
        elif kind == "help":
            if history:
                m["accepted"] = False
            elif self._last_help_t is None or now - self._last_help_t >= CMD_COOLDOWN_S:
                self._last_help_t = now
                self.help_until = now + HELP_SHOW_S
            else:
                m["accepted"] = False
        elif kind == "stats":
            if history:
                m["accepted"] = False
            elif self._last_stats_t is None or now - self._last_stats_t >= CMD_COOLDOWN_S:
                self._last_stats_t = now
                self.stats_until = now + STATS_SHOW_S
            else:
                m["accepted"] = False
        elif kind == "ask":
            m["accepted"] = bool(arg) and ask_enabled and not history

        # -- step 8: per-user render rate 1 line / 2 s (votes already counted, ideas already classified)
        last = self._last_render_t.get(key)
        if last is not None and t - last < RATE_S:
            m["rate_limited"] = True
            self.rate_limited += 1
        else:
            self._last_render_t[key] = t
            self.messages.append(m)
        return m

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
        already = ((cmd == "hide" and target in self.hidden) or (cmd == "unhide" and target not in self.hidden)
                   or (cmd == "pause" and self.paused) or (cmd == "resume" and not self.paused)
                   or (cmd == "kill" and not self.display) or (cmd == "unkill" and self.display))
        if cmd == "hide" and target:
            if target == self.channel_owner:
                return                                  # nobody hides the broadcaster
            self.hidden.add(target)
            self._votes.pop(target, None)
            note = "mod action: hid @%s" % target
        elif cmd == "unhide" and target:
            self.hidden.discard(target)
            note = "mod action: unhid @%s" % target
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
        if note:
            self._set_notice(note, "warn", now)
        self.log("mod %s %s by %s" % (cmd, target or "", by))

    def _check_theme(self, preset: str, now: float) -> Tuple[bool, Optional[str]]:
        if preset not in L.PRESETS:
            return False, "themes: " + " ".join(sorted(L.PRESETS.keys()))
        if self._last_theme_t is not None and now - self._last_theme_t < THEME_COOLDOWN_S:
            return False, "theme cooldown %d s" % max(1, int(round(THEME_COOLDOWN_S - (now - self._last_theme_t))))
        return True, None

    def _set_notice(self, text: str, level: str, now: float, dur: float = NOTICE_S) -> None:
        self._notice = (text, level, now + dur)

    def _ack(self, text: str, now: float) -> None:
        """Same-frame public acknowledgement (`@name voted A`) for VOTE_ACK_S. Several accepted in one ingest batch
        share the strip (`@nova voted A · @rin voted C`; the panel truncates to its width) so no voter is skipped. It
        has priority over the regular notice while it lasts; the regular notice keeps its own expiry underneath."""
        cur = self._ack_notice
        if cur and cur[2] == now + VOTE_ACK_S:
            text = cur[0] + " · " + text
        self._ack_notice = (text, "ok", now + VOTE_ACK_S)

    def notice(self, now: float):
        if self._ack_notice and now < self._ack_notice[2]:
            return (self._ack_notice[0], self._ack_notice[1])
        if self._notice and now < self._notice[2]:
            return (self._notice[0], self._notice[1])
        return None

    # ------------------------------------------------------------------ views
    @property
    def founders(self) -> List[str]:
        """Display names of the first 10 chatters of this session, minus anyone a mod has hidden."""
        return [shown for k, shown in self._founders if k not in self.hidden]

    def visible(self, now: float, n: int = 10) -> List[Dict]:
        """Moderated messages past their 3 s hold, newest last. [] when the kill switch is on.
        While paused the pane is frozen at the moment of the pause (votes keep counting)."""
        if not self.display:
            return []
        cutoff = now if not (self.paused and self._pause_t is not None) else min(now, self._pause_t)
        out = []
        for m in self.messages:
            if m.get("show_t", 0) > cutoff:
                continue
            if (m.get("name") or "").lower() in self.hidden:
                continue
            out.append(m)
        return out[-n:]

    def reset_round(self, opened_t: float) -> None:
        """New round opened at opened_t: drop votes cast before it, keep later ones (a round resumed
        from state.json after a compositor restart re-tallies the votes already in chat.jsonl)."""
        self._round_opened_t = opened_t
        self._votes = {k: v for k, v in self._votes.items() if v[1] >= opened_t - 1.0}
        self._voted_this_round = set(self._votes.keys())

    def _voter_name(self, key: str) -> str:
        b = self.builders.get(key) or {}
        return self._display_name(b.get("name") or key)

    def tallies(self) -> Dict[str, List[str]]:
        t: Dict[str, List[str]] = {"A": [], "B": [], "C": []}
        for key, (letter, when) in sorted(self._votes.items(), key=lambda kv: kv[1][1]):
            if letter in t and key not in self.hidden:
                t[letter].append(self._voter_name(key))
        return t

    def vote_count(self) -> int:
        return sum(1 for k in self._votes if k not in self.hidden)

    def recent_votes(self, n: int = 5) -> List[Tuple[str, str, float]]:
        items = [kv for kv in sorted(self._votes.items(), key=lambda kv: kv[1][1]) if kv[0] not in self.hidden]
        return [(self._voter_name(k), v[0], v[1]) for k, v in items[-n:]]

    def stats(self) -> Dict:
        return {"ingested": self.ingested, "dropped": self.dropped, "rate_limited": self.rate_limited,
                "hidden": sorted(self.hidden), "paused": self.paused, "display": self.display,
                "votes": self.vote_count(), "builders": len(self.builders), "founders": self.founders,
                "blocklist_terms": len(self._block_terms)}


if __name__ == "__main__":
    b = ChatBridge("/tmp/cp-chat-bridge")
    for txt in ["A", "!b", " c ", "abc", "!idea show the diff bigger", "!theme ember", "!theme nope",
                "hello https://x.com/y [emote:1:kek]", "!hide @spammer", "!kill"]:
        print(repr(txt), "->", b.classify(txt), "|", b.clean_text(txt, 120))
