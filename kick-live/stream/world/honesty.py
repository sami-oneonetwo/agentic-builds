"""stream/world/honesty.py - the per-frame honesty assertion (WORLD.md 1, 10, 11; docs/art-rules.md 1).

    from stream.world.honesty import HonestyMonitor
    mon = HonestyMonitor(scene)                 # one per CaveScene; keeps counters across frames
    img = scene.frame(ctx, size)
    rep = mon.check(ctx, now)                   # Report: rep.ok, rep.violations [(rule, detail)], rep.counts, rep.unverified
    mon.line()                                  # readout text: "honesty: 1200 frames · 0 violations"
    mon.summary()                               # dict for stats / the QA gate

    $PYTHON stream/world/honesty.py --self-test          # RUN_DIR under /tmp only; exit 0 only when the clean run
                                                          # has 0 violations AND every planted fake pip is caught

Every rule is a `len()` over real records, never a sample string. The rules:

  origin      every entity has origin "chat" (or "test" when stream.world.test_pips_allowed() said so for this scene)
  record      every ANIMATE entity (not a seed) maps to one row in world.json["pips"] created from a chat record;
              len(animate entities) == len(animate entities with a real record)
  chat_jsonl  every real pip key appears as a chatter in $RUN_DIR/chat.jsonl (both record shapes, de-duped on id);
              hatched_ever() == len(real pips). Re-scanned when the file grows, never more than every 2 s.
  hold        nothing about a seed carries a name (entities() gives display_name None AND key None); an entity that
              hatched in this process hatched >= hold_s after its seed dropped; a seed's name is only stored once
              the bridge cleared it (cleared == True)
  name        an entity's display_name is the pip's FILTERED display name (builder #N on a blocklist hit), never a
              raw name the filter would change
  counts      awake_count / asleep_count / hatched_ever / platform_counts are len() over the entities they claim
  text        a bubble is the owner's own moderated text (seen in ctx.chat), one of the owner's own words, or a
              learned word carrying a real source; pips never generate text
  presence    len(awake real entities) == scene.distinct_recent_chatters(ctx, now); a boundary-frame drift is
              tolerated for `presence_grace_s` (default 2 s) and counted separately as `presence_drift`
  scene       the scene's own _honesty_check removed something (stats()["honesty_violations"] grew)

`enforce=True` (default) also REMOVES an animate entity that has no real record and clears a bubble whose text the
owner never typed, so a bug upstream cannot put a fake creature or invented words on screen. Counts and records are
never "fixed": a padded count or a pip with no chat record stays a reported violation (the readout shows it).
Python 3.9: from __future__ import annotations; stdlib + numpy only.
"""
from __future__ import annotations

import collections
import json
import os
import sys
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stream.state_store import normalise_chat, run_path  # noqa: E402

RULES = ("origin", "record", "chat_jsonl", "hold", "name", "counts", "text", "presence", "scene")
SEED_STATES = ("seed", "hatching")
SLEEP_STATES = ("asleep", "burrowed")
CHAT_RESCAN_S = 2.0
TEXT_MEMORY = 20


class Report(object):
    __slots__ = ("frame", "now", "violations", "counts", "unverified", "drift")

    def __init__(self, frame: int, now: float):
        self.frame = frame
        self.now = now
        self.violations: List[Tuple[str, str]] = []
        self.counts: Dict[str, int] = {}
        self.unverified: List[str] = []
        self.drift = False

    @property
    def ok(self) -> bool:
        return not self.violations

    def add(self, rule: str, detail: str) -> None:
        self.violations.append((rule, detail))

    def rules(self) -> Set[str]:
        return set(r for r, _ in self.violations)

    def __repr__(self) -> str:
        return "Report(frame=%d ok=%s violations=%r counts=%r)" % (self.frame, self.ok, self.violations, self.counts)


def chat_names(path: str) -> Optional[Set[str]]:
    """Distinct lowercase chatter names in a chat.jsonl (both shapes: username/content and user/text; de-duped on id).
    None when the file cannot be read (unverifiable, not a violation)."""
    names: Set[str] = set()
    ids: Set[str] = set()
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            m = normalise_chat(json.loads(line.decode("utf-8", "replace")))
        except Exception:
            continue
        if m is None or m["id"] in ids or not m.get("name"):
            continue
        ids.add(m["id"])
        if m.get("type") in (None, "message"):
            names.add(m["name"].lower())
    return names


class HonestyMonitor(object):
    def __init__(self, scene, name_filter=None, enforce: bool = True, presence_grace_s: float = 2.0, log=None):
        self.scene = scene
        self._filter = name_filter
        self.enforce = bool(enforce)
        self.presence_grace_s = float(presence_grace_s)
        self.log = log or (lambda m: sys.stderr.write("honesty: %s\n" % m))
        self.frames = 0
        self.failed_frames = 0
        self.violations_total = 0
        self.by_rule: Dict[str, int] = {r: 0 for r in RULES}
        self.drift_frames = 0
        self.removed = 0
        self.last: Optional[Report] = None
        self._texts: Dict[str, Deque[str]] = {}
        self._chat_seen: Set[str] = set()
        self._chat_names: Optional[Set[str]] = None
        self._chat_size = -1
        self._chat_scan_t = -1e18
        self._scene_hv = None
        self._drift_since: Optional[float] = None
        self._logged = 0

    # ------------------------------------------------------------------ helpers
    def _name_filter(self):
        if self._filter is not None:
            return self._filter
        w = getattr(self.scene, "world", None)
        return getattr(w, "name_filter", None)

    def _chat_path(self) -> str:
        w = getattr(self.scene, "world", None)
        p = getattr(w, "chat_path", None)
        return p or run_path(self.scene.run_dir, "CHAT_FILE", "chat.jsonl")

    def _refresh_chat_names(self, now: float) -> None:
        path = self._chat_path()
        try:
            size = os.path.getsize(path)
        except OSError:
            size = -2
        if size == self._chat_size and self._chat_names is not None:
            return
        if now - self._chat_scan_t < CHAT_RESCAN_S and self._chat_names is not None:
            return
        self._chat_scan_t = now
        self._chat_size = size
        self._chat_names = chat_names(path) if size >= 0 else None

    def _remember_texts(self, ctx) -> None:
        for m in (getattr(ctx, "chat", None) or []):
            mid = m.get("id")
            if not mid or mid in self._chat_seen or m.get("dropped"):
                continue
            self._chat_seen.add(mid)
            key = (m.get("name") or "").lower()
            if not key:
                continue
            dq = self._texts.get(key)
            if dq is None:
                dq = self._texts[key] = collections.deque(maxlen=TEXT_MEMORY)
            for t in (m.get("text_clean"), m.get("text")):
                if t:
                    dq.append(str(t))
        if len(self._chat_seen) > 5000:
            self._chat_seen = set(list(self._chat_seen)[-2500:])

    def _text_allowed(self, key: str, text: str, pip: Optional[Dict], learned_from: Optional[str]) -> bool:
        if not text:
            return True
        cands = set(self._texts.get(key, ()))
        if text in cands or text.upper() in set(c.upper() for c in cands):
            return True
        if pip is not None:
            if text in (pip.get("words") or {}):
                return True
            if learned_from:
                for lw in (pip.get("learned") or []):
                    if lw.get("word") == text and (lw.get("from") or "").lower() == str(learned_from).lower():
                        return True
            return text.lower() in set(str(w).lower() for w in (pip.get("words") or {}))
        return False

    # ------------------------------------------------------------------ the check
    def check(self, ctx, now: Optional[float] = None) -> Report:
        scene = self.scene
        t = float(now if now is not None else (getattr(ctx, "now", None) or getattr(scene, "_last_now", None) or 0.0))
        rep = Report(self.frames, t)
        self.frames += 1
        if not getattr(scene, "booted", False) or scene.behaviour is None or scene.world is None:
            rep.counts = {"entities": 0}
            self.last = rep
            return rep
        b, w = scene.behaviour, scene.world
        self._remember_texts(ctx)
        allowed_test = int(getattr(scene, "test_pips", 0) or 0) > 0
        ents = dict(b.entities)
        hold_s = float(getattr(scene, "hold_s", 3.0))
        eps = 1.0 / 30.0 + 1e-6
        nf = self._name_filter()
        chat_display = getattr(ctx, "chat_display", None)

        # -- scene: the scene's own guard fired (it deletes entities with a foreign origin)
        hv = int(getattr(scene, "honesty_violations", 0) or 0)
        if self._scene_hv is not None and hv > self._scene_hv:
            rep.add("scene", "scene removed %d entity/ies with no real record" % (hv - self._scene_hv))
        self._scene_hv = hv

        animate = 0
        animate_real = 0
        awake_real = 0
        remove: List[str] = []
        for key, e in ents.items():
            origin = getattr(e, "origin", None)
            is_test = origin == "test" and allowed_test
            # -- origin
            if origin != "chat" and not is_test:
                rep.add("origin", "%s origin=%r" % (key, origin))
                remove.append(key)
                continue
            p = w.pip(key)
            if e.state in SEED_STATES:
                # -- hold: a seed stores a name only once the bridge cleared it
                if e.display_name is not None and not e.cleared:
                    rep.add("hold", "seed %s carries a name before the hold cleared" % key)
                    if self.enforce:
                        e.display_name = None
                continue
            animate += 1
            # -- record
            if p is None or (is_test and not p.get("_test")) or (not is_test and p.get("_test")):
                rep.add("record", "%s (%s) has no %spip record" % (key, e.state, "" if not is_test else "test "))
                remove.append(key)
                continue
            animate_real += 1
            if not is_test and e.is_awake():
                awake_real += 1
            # -- hold: hatched in this process -> hatch_t - seed_t >= hold_s; a label needs a cleared hold
            if e.hatch_t is not None and e.hatch_t - e.seed_t < hold_s - eps:
                rep.add("hold", "%s hatched %.2fs after its seed (hold %.1fs)" % (key, e.hatch_t - e.seed_t, hold_s))
            if e.display_name is not None and not e.cleared:
                rep.add("hold", "%s labelled without a cleared hold" % key)
            # -- name: the filtered name, never the raw one the filter would change
            if e.display_name is not None and not is_test:
                want = p.get("display_name")
                if want is None and nf is not None:
                    try:
                        want = nf(p.get("name") or key)
                    except Exception:
                        want = None
                shown = str(e.display_name)
                if want is not None and shown != str(want) and not shown.startswith("builder #"):
                    rep.add("name", "%s shows %r, filtered name is %r" % (key, shown, want))
                elif want is None and nf is not None and not shown.startswith("builder #"):
                    try:
                        if nf(shown) != shown:
                            rep.add("name", "%s shows a name the filter changes" % key)
                    except Exception:
                        pass
            # -- text
            if e.text is not None and t < e.speak_until and not is_test:
                if not self._text_allowed(key, str(e.text), p, e.learned_from):
                    rep.add("text", "%s speaks words the owner never typed: %r" % (key, str(e.text)[:40]))
                    if self.enforce:
                        e.text, e.speak_until = None, 0.0
        if remove and self.enforce:
            for k in remove:
                if k in b.entities:
                    del b.entities[k]
                    self.removed += 1
        # -- entities(): nothing about a seed leaves for the text layer
        try:
            for d in scene.entities(t):
                if d.get("state") in SEED_STATES and (d.get("display_name") is not None or d.get("key") is not None):
                    rep.add("hold", "entities() exposes a seed's name/key")
                    break
        except Exception as ex:
            rep.unverified.append("entities(): %r" % (ex,))
        # -- record (count form): every animate entity is backed by a record
        if animate != animate_real:
            rep.add("record", "animate entities %d != with real record %d" % (animate, animate_real))
        # -- chat_jsonl: every real pip is a chatter in chat.jsonl; hatched_ever is len()
        real_pips = [k for k, p in w.pips.items() if not p.get("_test")]
        self._refresh_chat_names(t)
        if self._chat_names is None:
            if real_pips:
                rep.unverified.append("chat.jsonl unreadable: %d pips not cross-checked" % len(real_pips))
        else:
            missing = [k for k in real_pips if k not in self._chat_names]
            if missing:
                rep.add("chat_jsonl", "%d pip(s) with no chat.jsonl record: %s" % (len(missing), ", ".join(sorted(missing)[:5])))
        try:
            he = int(scene.hatched_ever())
        except Exception:
            he = -1
        if he != len(real_pips):
            rep.add("counts", "hatched_ever() %d != len(real pips) %d" % (he, len(real_pips)))
        # -- counts: awake / asleep / platforms are len() over the entities they claim (test pips included, as drawn)
        live = b.entities
        n_awake = sum(1 for e in live.values() if e.is_awake())
        n_asleep = sum(1 for e in live.values() if e.state in SLEEP_STATES)
        try:
            if int(scene.awake_count()) != n_awake:
                rep.add("counts", "awake_count() %d != len(awake entities) %d" % (scene.awake_count(), n_awake))
            if int(scene.asleep_count()) != n_asleep:
                rep.add("counts", "asleep_count() %d != len(sleeping entities) %d" % (scene.asleep_count(), n_asleep))
            pc = scene.platform_counts()
            for letter, keys in pc.items():
                standing = sorted(k for k, e in live.items() if e.state == "voting" and e.platform == letter)
                if sorted(keys) != standing:
                    rep.add("counts", "platform %s lists %r, standing %r" % (letter, sorted(keys), standing))
        except Exception as ex:
            rep.unverified.append("counts: %r" % (ex,))
        # -- presence: awake real == distinct chatters in the sleep window of this session
        try:
            ref = int(scene.distinct_recent_chatters(ctx, t))
        except Exception as ex:
            ref = None
            rep.unverified.append("distinct_recent_chatters: %r" % (ex,))
        if ref is not None:
            if awake_real != ref:
                rep.drift = True
                self.drift_frames += 1
                if self._drift_since is None:
                    self._drift_since = t
                elif t - self._drift_since > self.presence_grace_s:
                    rep.add("presence", "awake real %d != distinct recent chatters %d for %.1fs" % (awake_real, ref, t - self._drift_since))
            else:
                self._drift_since = None
        rep.counts = {"entities": len(live), "animate": animate, "animate_real": animate_real, "awake": n_awake,
                      "awake_real": awake_real, "asleep": n_asleep, "seeds": sum(1 for e in live.values() if e.state in SEED_STATES),
                      "real_pips": len(real_pips), "hatched_ever": he, "recent_chatters": ref if ref is not None else -1,
                      "test_pips": int(getattr(scene, "test_pips", 0) or 0), "removed_total": self.removed}
        if chat_display is False:
            rep.counts["names_hidden"] = 1
        if rep.violations:
            self.failed_frames += 1
            self.violations_total += len(rep.violations)
            for r in rep.rules():
                self.by_rule[r] = self.by_rule.get(r, 0) + 1
            self._logged += 1
            if self._logged <= 5 or self._logged % 300 == 0:
                self.log("frame %d: %s" % (rep.frame, "; ".join("%s: %s" % v for v in rep.violations[:4])))
        self.last = rep
        return rep

    # ------------------------------------------------------------------ readouts
    def summary(self) -> Dict[str, Any]:
        return {"frames": self.frames, "failed_frames": self.failed_frames, "violations": self.violations_total,
                "by_rule": {k: v for k, v in self.by_rule.items() if v}, "presence_drift_frames": self.drift_frames,
                "removed": self.removed, "last": None if self.last is None else
                {"ok": self.last.ok, "violations": list(self.last.violations), "counts": dict(self.last.counts),
                 "unverified": list(self.last.unverified)}}

    def line(self) -> str:
        """One readout line (Menlo 20 fits ~22 chars): honest about what it checked."""
        if self.violations_total:
            return "honesty: %d violation%s" % (self.violations_total, "" if self.violations_total == 1 else "s")
        return "honesty: %d frames ok" % self.frames


def check_frame(scene, ctx, now: Optional[float] = None, enforce: bool = False) -> Report:
    """One-off check without keeping counters (the QA gate); `enforce` defaults off here."""
    return HonestyMonitor(scene, enforce=enforce, log=lambda m: None).check(ctx, now)


# ---------------------------------------------------------------------------- self-test
def _selftest(run_dir: str) -> int:
    """Clean run must be violation-free; every planted fake must be caught. Prints evidence; returns the exit code."""
    import shutil
    import time as _time
    from PIL import Image
    from stream.scenes.hollow import CaveScene, _Ctx
    from stream.state_store import epoch_to_iso
    from stream.world.behaviour import Entity
    from stream.world.state import _default_pip, FLOOR_ROWS
    from stream.world import pips as P

    rp = os.path.realpath(run_dir)
    if not (rp.startswith("/tmp/") or rp.startswith("/private/tmp/")):
        print("refused: RUN_DIR must be under /tmp (got %s)" % run_dir)
        return 2
    os.environ.pop("KL_TEST_PIPS", None)
    if os.path.isdir(run_dir):
        shutil.rmtree(run_dir)
    os.makedirs(run_dir)
    fps = 30.0
    t0 = _time.time()
    session = {"id": "honesty-" + epoch_to_iso(t0, ms=False), "started_ts": epoch_to_iso(t0 - 30, ms=False), "ending": False}
    # the "real" records: both chat.jsonl shapes, written to $RUN_DIR/chat.jsonl exactly as the listener / receiver do
    names = ["honesty-chatter-a", "honesty-chatter-b"]
    recs_file = [
        {"id": "h-0001", "ts": epoch_to_iso(t0 + 1.0), "username": names[0], "content": "hello cave", "type": "message"},
        {"id": "h-0002", "ts": epoch_to_iso(t0 + 2.0), "user": names[1], "text": "hi there", "user_id": 42},
        {"id": "h-0003", "ts": epoch_to_iso(t0 + 6.0), "username": names[0], "content": "B", "type": "message"},
    ]
    chat_path = os.path.join(run_dir, "chat.jsonl")
    with open(chat_path, "w") as fh:
        for r in recs_file:
            fh.write(json.dumps(r) + "\n")
    print("[setup] %s: %d records (pusher + webhook shapes), names %r" % (chat_path, len(recs_file), names))

    def bridge_rec(i, name, text, t, kind="plain", letter=None):
        return {"id": "h-%04d" % i, "ts": epoch_to_iso(t), "t": t, "name": name, "text": text, "text_clean": text,
                "kind": kind, "letter": letter, "display_name": name, "builder_n": None, "first_ever": True,
                "dropped": False, "show_t": t + 3.0, "accepted": True}

    def mkctx(now, frame, chat_raw, chat, votes=(), hb=None):
        return _Ctx(now=now, frame=frame, fps=fps, session=session, micro={"canvas_seed": 41370704}, preset="kick",
                    chat_raw=list(chat_raw), chat=list(chat), recent_votes=list(votes), round={"number": 1},
                    mod={"hidden_users": []}, agent={"heartbeat_ts": hb}, macro={"active": False},
                    compositor_live={"selftest": True}, mod_paused=False, chat_display=True)

    size = (1280, 440)
    scene = CaveScene(run_dir=run_dir, seed=11, sleep_after_s=60.0)
    mon = HonestyMonitor(scene, enforce=False)
    raw: List[Dict] = []
    clear: List[Dict] = []
    seed_frames_nameless = 0
    seed_frames = 0
    frames_dir = os.path.join(run_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    n_clean = 240
    for i in range(n_clean):
        now = t0 + i / fps
        votes = []
        if i == 30:
            raw.append(bridge_rec(1, names[0], "hello cave", now))
        if i == 45:
            raw.append(bridge_rec(2, names[1], "hi there", now))
        if i == 120:
            clear.append(bridge_rec(1, names[0], "hello cave", now - 3.0))
        if i == 135:
            clear.append(bridge_rec(2, names[1], "hi there", now - 3.0))
        if i == 180:
            raw.append(bridge_rec(3, names[0], "B", now, "vote", "B"))
        if i >= 180:
            votes = [(names[0], "B", t0 + 180 / fps)]
        if i == 210:
            clear.append(bridge_rec(3, names[0], "B", now - 3.0, "vote", "B"))
        ctx = mkctx(now, i, raw[-20:], clear[-10:], votes)
        img = scene.frame(ctx, size)
        rep = mon.check(ctx, now)
        for d in scene.entities(now):
            if d["state"] in SEED_STATES:
                seed_frames += 1
                if d["display_name"] is None and d["key"] is None:
                    seed_frames_nameless += 1
        if i in (60, 150, 239):
            img.save(os.path.join(frames_dir, "clean_%04d.png" % i))
    s = mon.summary()
    print("[clean] %d frames: failed_frames=%d violations=%d by_rule=%r drift_frames=%d unverified=%r" % (
        n_clean, s["failed_frames"], s["violations"], s["by_rule"], s["presence_drift_frames"], s["last"]["unverified"]))
    print("[clean] last counts: %r" % (s["last"]["counts"],))
    print("[clean] seed frames seen=%d, nameless (display_name None and key None)=%d" % (seed_frames, seed_frames_nameless))
    print("[clean] hatched_ever=%d awake=%d asleep=%d platform_counts=%r stats=%r" % (
        scene.hatched_ever(), scene.awake_count(), scene.asleep_count(), scene.platform_counts(),
        {k: scene.stats()[k] for k in ("frames", "errors", "honesty_violations", "test_pips", "entities")}))
    ok = True
    if s["violations"] != 0:
        print("FAIL: clean run produced violations")
        ok = False
    if seed_frames == 0 or seed_frames != seed_frames_nameless:
        print("FAIL: a seed carried a name (%d/%d)" % (seed_frames_nameless, seed_frames))
        ok = False
    if scene.hatched_ever() != 2 or s["last"]["counts"]["awake_real"] != 2:
        print("FAIL: expected 2 real hatched, 2 awake")
        ok = False

    # ---- planted fakes: each must be caught by the named rule
    now = t0 + n_clean / fps
    caught: Dict[str, bool] = {}

    def run_frames(n, extra_check=None):
        nonlocal now
        last = None
        for _ in range(n):
            now += 1.0 / fps
            ctx = mkctx(now, 0, raw[-20:], clear[-10:], [(names[0], "B", t0 + 180 / fps)])
            scene.frame(ctx, size)
            last = mon.check(ctx, now)
            if extra_check is not None:
                extra_check(ctx)
        return last

    # 1. a creature with a plausible origin but no record anywhere (a forged entity)
    ghost = Entity("ghost-nobody", "chat", now)
    ghost.state, ghost.display_name, ghost.cleared, ghost.y = "awake", "ghost", True, float(FLOOR_ROWS[0])
    scene.behaviour.entities["ghost-nobody"] = ghost
    rep = run_frames(2)
    caught["record (forged entity, no pip record)"] = "record" in rep.rules()
    print("[fake 1] forged entity origin=chat, no record -> %r" % (rep.violations,))
    scene.behaviour.entities.pop("ghost-nobody", None)
    run_frames(1)

    # 2. a pip record for someone who never chatted (planted in world.json), with an entity to match
    key = "never-chatted-x"
    scene.world.data["pips"][key] = _default_pip(key, "Never", "Never", None, now, P.genome(key, 0))
    scene.behaviour.place_sleeper(key, 0, 0.6, 0, 3, "Never", t=now)
    rep = run_frames(2)
    caught["chat_jsonl (pip with no chat.jsonl record)"] = "chat_jsonl" in rep.rules()
    print("[fake 2] planted pip record with no chat.jsonl record -> %r" % (rep.violations,))
    scene.behaviour.entities.pop(key, None)
    scene.world.data["pips"].pop(key, None)
    scene.world.data["world"]["hatched_ever"] = scene.world.hatched_ever
    run_frames(1)

    # 3. a name on a seed before the hold cleared
    early = scene.behaviour.seed_drop("early-name", now)
    early.display_name = "early"
    rep = run_frames(1)
    caught["hold (name stored on an uncleared seed)"] = "hold" in rep.rules()
    print("[fake 3] seed with a name before the hold -> %r" % (rep.violations,))
    scene.behaviour.sink("early-name", now)
    run_frames(1)

    # 4. a hatch that skipped the hold
    fast = scene.behaviour.seed_drop("fast-hatch", now)
    scene.behaviour.hold_cleared("fast-hatch", now, "fast", 0, 0.6, 0, True)
    fast.seed_t = now - 0.5
    scene.world.data["pips"]["fast-hatch"] = _default_pip("fast-hatch", "fast", "fast", None, now, P.genome("fast-hatch", 0))
    with open(chat_path, "a") as fh:                         # give it a real record so ONLY the hold rule fires
        fh.write(json.dumps({"id": "h-0009", "ts": epoch_to_iso(now), "username": "fast-hatch", "content": "x"}) + "\n")
    scene.behaviour._hatch(fast, now)                        # forced early hatch: hatch_t - seed_t = 0.5 s
    rep = run_frames(1)
    caught["hold (hatched before hold_s)"] = "hold" in rep.rules()
    print("[fake 4] hatch 0.5 s after the seed -> %r" % (rep.violations,))
    scene.behaviour.entities.pop("fast-hatch", None)
    scene.world.data["pips"].pop("fast-hatch", None)
    scene.world.data["world"]["hatched_ever"] = scene.world.hatched_ever
    run_frames(1)

    # 5. a padded count
    real_awake = scene.awake_count
    scene.awake_count = lambda: real_awake() + 1
    rep = run_frames(1)
    caught["counts (awake_count padded by 1)"] = "counts" in rep.rules()
    print("[fake 5] awake_count() + 1 -> %r" % (rep.violations,))
    scene.awake_count = real_awake
    run_frames(1)

    # 6. words the owner never typed
    e = scene.behaviour.get(names[0])
    e.text, e.speak_until = "words nobody typed here", now + 6.0
    rep = run_frames(1)
    caught["text (generated bubble)"] = "text" in rep.rules()
    print("[fake 6] bubble text the owner never typed -> %r" % (rep.violations,))
    e.text, e.speak_until = None, 0.0

    # 7. a foreign origin (the scene's own guard should also fire)
    alien = Entity("alien-origin", "mascot", now)
    alien.state, alien.display_name, alien.cleared = "awake", "mascot", True
    scene.behaviour.entities["alien-origin"] = alien
    rep = run_frames(1)
    caught["origin/scene (origin=mascot)"] = bool({"origin", "scene"} & rep.rules())
    print("[fake 7] entity origin=mascot -> %r (scene honesty_violations=%d)" % (rep.violations, scene.honesty_violations))

    # 8. after cleanup: violation-free again (the monitor does not get stuck)
    rep = run_frames(3)
    print("[after] clean again: ok=%s violations=%r counts=%r" % (rep.ok, rep.violations, rep.counts))
    if not rep.ok:
        print("FAIL: monitor still reports violations after the fakes were removed")
        ok = False
    # 9. enforce mode removes a forged entity so it is never drawn
    mon2 = HonestyMonitor(scene, enforce=True, log=lambda m: None)
    ghost2 = Entity("ghost-two", "chat", now)
    ghost2.state, ghost2.display_name, ghost2.cleared = "awake", "ghost2", True
    scene.behaviour.entities["ghost-two"] = ghost2
    rep2 = mon2.check(mkctx(now, 0, raw[-20:], clear[-10:]), now)
    removed = "ghost-two" not in scene.behaviour.entities
    caught["enforce (forged entity removed)"] = ("record" in rep2.rules()) and removed
    print("[fake 9] enforce=True: caught=%s removed=%s summary=%r" % ("record" in rep2.rules(), removed, mon2.summary()["removed"]))

    for k, v in caught.items():
        print("[planted] %-45s %s" % (k, "CAUGHT" if v else "MISSED"))
        if not v:
            ok = False
    img = scene.frame(mkctx(now, 0, raw[-20:], clear[-10:]), size)
    img.save(os.path.join(frames_dir, "final.png"))
    print("[frames] %s" % ", ".join(sorted(os.listdir(frames_dir))))
    print("[monitor] %r" % (mon.summary(),))
    print("HONESTY SELF-TEST %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        sys.exit(_selftest(os.environ.get("RUN_DIR") or "/tmp/pip-keepers-honesty"))
    print(__doc__)
