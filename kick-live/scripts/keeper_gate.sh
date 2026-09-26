#!/usr/bin/env bash
# scripts/keeper_gate.sh - the sandbox gate for tier-2 keeper builds (IDLEWORLD.md 5.2, build row P2).
#
# A STAGE is a staged copy of the tree (rsync of a worktree, or a build agent's output). The gate diffs the stage
# against a BASELINE (the live snapshot S, or the worktree's committed HEAD with --against-tree), applies the ALLOW /
# DENY policy, hashes honesty.py + state_store.py, greps the added lines for revert-list words and agents/ + scripts/
# for world.json writers, then prints gates 1-11 in the spec's order. Gates 7-10 are LIVE actions (backups, the cp
# into S, the log watch, the HLS probe): this script never performs them; it prints the exact command for each and
# marks it SKIP. Nothing here writes to S or to the live run dir; the only files written are under /tmp/lg-* and the
# lock dir you name.
#
# Usage:
#   keeper_gate.sh --stage DIR [--snapshot DIR | --against-tree] [--live-run DIR] [--ignore PATH]...
#                  [--run-gates] [--compositor N] [--tag TAG] [--no-lock-check]
#   keeper_gate.sh --lock [--lock-dir DIR]        take $LOCK (mkdir-based; pid + ts inside); exit 3 if a live pid holds it
#   keeper_gate.sh --unlock [--lock-dir DIR]      release $LOCK when held by this shell's ancestry or a dead pid
#   keeper_gate.sh --self-test                    fixture stages under /tmp/lg-P2-ops-selftest-*: honesty edit -> 2,
#                                                 'animal' added -> 2, clean -> 0, world.json writer in agents/ -> 2, lock
# Options:
#   --stage DIR        the staged tree to judge (required unless --lock/--unlock/--self-test)
#   --snapshot DIR     the baseline tree (default $KL_SNAPSHOT or ~/.local/share/kick-live/live-snapshot-v3), read only
#   --against-tree     baseline = `git archive HEAD` of the worktree this script lives in (committed copies, not the
#                      working tree), extracted under /tmp
#   --live-run DIR     the run dir whose pause_bot.json / world.json / chat.jsonl / builders.json are READ (default
#                      $RUN_DIR, else ~/.local/share/kick-live/run-live); copies go to /tmp, the source is never written
#   --ignore PATH      a stage-relative path or glob to leave out of the policy diff (repeatable; e.g. ops files that
#                      ship by the owner's copy step, never through this gate)
#   --run-gates        run gate 3 (py_compile) and gate 4 (module self-tests) for real; without it they print PLAN
#   --compositor N     also run gate 5 (compositor --self-test N on copies of the live run files) and gate 6b
#   --tag TAG          the tag used in the printed gate-7 backup names (default kg-<date>)
#   --no-lock-check    do not refuse when world_batch.lock is held by another live pid
#   --lock-dir DIR     where world_batch.lock lives (default $LIVE_RUN/pids)
#
# Exit: 0 every policy check and every executed gate passed; 2 a policy violation or a failed gate; 3 the world batch
# lock is held by a live pid (or a lock op failed); 4 bad arguments / missing stage. Every gate line is printed as
#   gate N  PASS|FAIL|SKIP|PLAN  <name>  <detail>
# Cleanup trap: selftest/frame_*.png and bake/*.npy under every run dir this script creates, and under the stage's own
# run/ dir, are deleted on exit; report/ text is kept. Refuses heavy gates under 20 GB free (owner rule, journal 035).
set -uo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-$HOME/.local/share/kick-live/venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"

STAGE=""; SNAPSHOT="${KL_SNAPSHOT:-$HOME/.local/share/kick-live/live-snapshot-v3}"; AGAINST_TREE=0
LIVE_RUN="${RUN_DIR:-$HOME/.local/share/kick-live/run-live}"
RUN_GATES=0; COMPOSITOR_N=0; TAG="kg-$(date +%Y%m%d)"; LOCK_CHECK=1; LOCK_DIR=""; MODE_LOCK=""; SELF_TEST=0
IGNORES=()
MIN_FREE_GB=20

usage() { sed -n '2,38p' "$SELF" | sed 's/^# \{0,1\}//'; }
die() { echo "keeper_gate.sh: $*" >&2; exit 4; }

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --stage) STAGE="${2:-}"; shift ;;
    --snapshot) SNAPSHOT="${2:-}"; shift ;;
    --against-tree) AGAINST_TREE=1 ;;
    --live-run) LIVE_RUN="${2:-}"; shift ;;
    --ignore) IGNORES+=("${2:-}"); shift ;;
    --run-gates) RUN_GATES=1 ;;
    --compositor) COMPOSITOR_N="${2:-300}"; shift ;;
    --tag) TAG="${2:-}"; shift ;;
    --no-lock-check) LOCK_CHECK=0 ;;
    --lock-dir) LOCK_DIR="${2:-}"; shift ;;
    --lock) MODE_LOCK=lock ;;
    --unlock) MODE_LOCK=unlock ;;
    --self-test) SELF_TEST=1 ;;
    *) die "unknown option '$1' (try --help)" ;;
  esac
  shift
done
[ -n "$LOCK_DIR" ] || LOCK_DIR="$LIVE_RUN/pids"
LOCK="$LOCK_DIR/world_batch.lock"

# ------------------------------------------------------------------ work dirs + the cleanup trap (gate 11)
WORK="${KG_WORK:-/tmp/lg-P2-ops-gate-$$}"
CLEAN_DIRS=("$WORK")
cleanup() {
  local d
  for d in "${CLEAN_DIRS[@]}"; do
    [ -d "$d" ] || continue
    find "$d" -path '*/selftest/frame_*.png' -delete 2>/dev/null || true
    find "$d" -path '*/bake/*.npy' -delete 2>/dev/null || true
  done
  if [ -n "$STAGE" ] && [ -d "$STAGE/run" ]; then
    rm -f "$STAGE"/run/selftest/frame_*.png "$STAGE"/run/bake/*.npy 2>/dev/null || true
  fi
  # the gate's own scratch (baseline extraction, self-test run dirs) goes; report/ text under $WORK/report is kept
  if [ -d "$WORK" ]; then
    find "$WORK" -mindepth 1 -maxdepth 1 ! -name report -exec rm -rf {} + 2>/dev/null || true
    rmdir "$WORK" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# ------------------------------------------------------------------ the world batch lock (mkdir-based)
pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }
lock_holder() { cat "$LOCK/pid" 2>/dev/null || true; }
lock_take() {
  mkdir -p "$LOCK_DIR" || { echo "lock: cannot create $LOCK_DIR" >&2; return 3; }
  if mkdir "$LOCK" 2>/dev/null; then
    echo "$$" > "$LOCK/pid"; date -u +%Y-%m-%dT%H:%M:%SZ > "$LOCK/ts"
    echo "lock: taken $LOCK pid $$ ts $(cat "$LOCK/ts")"; return 0
  fi
  local h; h="$(lock_holder)"
  if pid_alive "$h"; then
    echo "lock: HELD by live pid $h since $(cat "$LOCK/ts" 2>/dev/null || echo '?') at $LOCK; refusing" >&2; return 3
  fi
  echo "lock: stale (pid ${h:-?} dead, ts $(cat "$LOCK/ts" 2>/dev/null || echo '?')); re-taking"
  rm -rf "$LOCK"
  mkdir "$LOCK" || { echo "lock: race, could not re-take" >&2; return 3; }
  echo "$$" > "$LOCK/pid"; date -u +%Y-%m-%dT%H:%M:%SZ > "$LOCK/ts"
  echo "lock: taken $LOCK pid $$ ts $(cat "$LOCK/ts")"
}
lock_release() {
  [ -d "$LOCK" ] || { echo "lock: not held ($LOCK absent)"; return 0; }
  local h; h="$(lock_holder)"
  if [ -n "$h" ] && [ "$h" != "$$" ] && [ "$h" != "${PPID}" ] && [ "$h" != "${KG_LOCK_PID:-}" ] && pid_alive "$h"; then
    echo "lock: held by live pid $h (not us); refusing to unlock (set KG_LOCK_PID=$h if that pid is yours)" >&2; return 3
  fi
  rm -rf "$LOCK" && echo "lock: released $LOCK (was pid ${h:-?})"
}
lock_check() {
  [ "$LOCK_CHECK" = 1 ] || return 0
  [ -d "$LOCK" ] || return 0
  local h; h="$(lock_holder)"
  if [ -n "$h" ] && [ "$h" != "$$" ] && [ "$h" != "$PPID" ] && pid_alive "$h"; then
    echo "keeper_gate.sh: world_batch.lock held by live pid $h ($LOCK); one agent on the world batch at a time" >&2
    return 3
  fi
  return 0
}
if [ "$MODE_LOCK" = lock ]; then lock_take; exit $?; fi
if [ "$MODE_LOCK" = unlock ]; then lock_release; exit $?; fi

# ------------------------------------------------------------------ helpers
gate() { # gate <n> <status> <name> <detail>
  printf 'gate %-2s %-4s %-22s %s\n' "$1" "$2" "$3" "$4"
}
FAILS=0
fail() { FAILS=$((FAILS + 1)); }
free_gb() { df -g "${1:-/tmp}" | awk 'NR==2 {print $4}'; }
rel_matches_ignore() { # rel path against IGNORES globs
  local p="$1" g
  for g in "${IGNORES[@]+"${IGNORES[@]}"}"; do
    # shellcheck disable=SC2254
    case "$p" in $g) return 0 ;; esac
  done
  return 1
}
# ALLOW / DENY policy (IDLEWORLD.md 5.2). state.py is denied for tier-2 builds (schema + migration belong to lane W);
# KG_ALLOW_STATE=1 admits it for a lane-W stage. land.py is allowed except its provenance / purge / restore bodies
# (checked by symbol, not line number, in policy_land).
classify_path() { # prints ALLOW | DENY | OUTSIDE
  local p="$1"
  case "$p" in
    stream/world/honesty.py) echo DENY; return ;;
    stream/world/state.py) if [ "${KG_ALLOW_STATE:-0}" = 1 ]; then echo ALLOW; else echo DENY; fi; return ;;
    stream/world/art/*.py) echo ALLOW; return ;;
    stream/world/*/*) echo OUTSIDE; return ;;
    stream/world/*.py) echo ALLOW; return ;;
    stream/scenes/*.py|stream/panels/*.py) echo ALLOW; return ;;
    stream/compositor.py|stream/chat_bridge.py|stream/rounds.py|stream/state_store.py|stream/layout.py|stream/relay.py|stream/audio.py) echo DENY; return ;;
    stream/moderation/*|scripts/*|monitor/*|agents/*|kickapp/*) echo DENY; return ;;
    docs/art-rules.md|docs/AGES.md|docs/IDLEWORLD.md) echo DENY; return ;;
    *) echo OUTSIDE; return ;;
  esac
}

# ------------------------------------------------------------------ self-test fixtures
if [ "$SELF_TEST" = 1 ]; then
  FX="/tmp/lg-P2-ops-selftest-$$"; CLEAN_DIRS+=("$FX")
  mkdir -p "$FX/base"
  git -C "$ROOT" archive HEAD stream agents scripts monitor 2>/dev/null | tar -x -C "$FX/base" || die "self-test: git archive HEAD failed"
  mk() { rm -rf "$FX/$1"; cp -R "$FX/base" "$FX/$1"; }
  rc_of() { # rc_of <name> <expected> -- cmd...
    local name="$1" want="$2"; shift 2
    local out rc
    out="$("$@" 2>&1)"; rc=$?
    if [ "$rc" = "$want" ]; then echo "self-test PASS $name: exit $rc (expected $want)"
    else echo "self-test FAIL $name: exit $rc (expected $want)"; echo "$out" | sed 's/^/    /'; FAILS=$((FAILS + 1)); fi
    echo "$out" | grep -E '^(gate [0-9]+ +FAIL|policy (FAIL|DENY|OUTSIDE)|hash FAIL|revert FAIL|writer|lock)' | head -6 | sed 's/^/    /'
  }
  COMMON=(--live-run "$FX/run" --snapshot "$FX/base" --lock-dir "$FX/run/pids" --no-lock-check)
  mkdir -p "$FX/run"
  export KG_WORK="$FX/work"          # every child gate run keeps its scratch + report inside the fixture dir

  mk clean;  printf '\n# keeper build: a comment only\n' >> "$FX/clean/stream/world/keepers.py"
  rc_of "clean stage (keepers.py comment)" 0 bash "$SELF" --stage "$FX/clean" "${COMMON[@]}"

  mk honest; printf '\n# widened\n' >> "$FX/honest/stream/world/honesty.py"
  rc_of "stage editing honesty.py" 2 bash "$SELF" --stage "$FX/honest" "${COMMON[@]}"

  mk animal; printf '\nanimal_count = 0  # keeper build\n' >> "$FX/animal/stream/world/land.py"
  rc_of "diff adding 'animal'" 2 bash "$SELF" --stage "$FX/animal" "${COMMON[@]}"

  mk sleepy; printf '\nNEW_STATE = "asleep"\n' >> "$FX/sleepy/stream/world/behaviour.py"
  rc_of "diff adding sleep as a state" 2 bash "$SELF" --stage "$FX/sleepy" "${COMMON[@]}"

  mk writer; mkdir -p "$FX/writer/agents"
  printf 'import json, os\nwp = os.path.join("/tmp/x", "world.json")\nwith open(wp, "w") as fh:\n    json.dump({}, fh)\n' > "$FX/writer/agents/bad_writer.py"
  rc_of "agents/ file writing world.json" 2 bash "$SELF" --stage "$FX/writer" "${COMMON[@]}"
  rc_of "writer rule alone (policy diff ignored)" 2 bash "$SELF" --stage "$FX/writer" "${COMMON[@]}" --ignore 'agents/*'
  mk copier; printf 'import os, shutil\ndef f(run_dir):\n    shutil.copy2("/tmp/x.json", os.path.join(run_dir, "world.json"))\n' > "$FX/copier/scripts/bad_copier.py"
  rc_of "scripts/ file copying over the run dir world.json" 2 bash "$SELF" --stage "$FX/copier" "${COMMON[@]}" --ignore 'scripts/*'

  mk spine; printf '\n# spine touch\n' >> "$FX/spine/stream/chat_bridge.py"
  rc_of "stage editing chat_bridge.py (DENY)" 2 bash "$SELF" --stage "$FX/spine" "${COMMON[@]}"

  mk paused; touch "$FX/run/pause_bot.json"
  rc_of "pause_bot.json present" 2 bash "$SELF" --stage "$FX/paused" "${COMMON[@]}"
  rm -f "$FX/run/pause_bot.json"

  # lock: take, second take refuses (live pid = this shell), unlock, stale re-take
  rc_of "lock take" 0 bash "$SELF" --lock --lock-dir "$FX/run/pids"
  echo "$$" > "$FX/run/pids/world_batch.lock/pid"     # the child exited; hold it as this live shell
  rc_of "lock refused while held by live pid" 3 bash "$SELF" --lock --lock-dir "$FX/run/pids"
  rc_of "gate refuses while lock held" 3 bash "$SELF" --stage "$FX/clean" --live-run "$FX/run" --snapshot "$FX/base" --lock-dir "$FX/run/pids"
  rc_of "unlock refused for another live pid without KG_LOCK_PID" 3 env -u KG_LOCK_PID bash "$SELF" --unlock --lock-dir "$FX/run/pids"
  rc_of "unlock with KG_LOCK_PID" 0 env KG_LOCK_PID="$$" bash "$SELF" --unlock --lock-dir "$FX/run/pids"
  mkdir -p "$FX/run/pids/world_batch.lock"; echo 999999 > "$FX/run/pids/world_batch.lock/pid"; echo stale > "$FX/run/pids/world_batch.lock/ts"
  rc_of "stale lock (dead pid) re-taken" 0 bash "$SELF" --lock --lock-dir "$FX/run/pids"
  rm -rf "$FX/run/pids/world_batch.lock"

  # the cleanup trap: a fake frame + npy under the stage's run dir must be gone after a run, report/ kept
  mk trapt; mkdir -p "$FX/trapt/run/selftest" "$FX/trapt/run/bake" "$FX/trapt/run/report"
  : > "$FX/trapt/run/selftest/frame_0001.png"; : > "$FX/trapt/run/bake/ground-x.npy"; echo kept > "$FX/trapt/run/report/gate.txt"
  bash "$SELF" --stage "$FX/trapt" "${COMMON[@]}" > /dev/null 2>&1
  if [ ! -e "$FX/trapt/run/selftest/frame_0001.png" ] && [ ! -e "$FX/trapt/run/bake/ground-x.npy" ] && [ -s "$FX/trapt/run/report/gate.txt" ]; then
    echo "self-test PASS cleanup trap: frame png + npy deleted, report/ kept"
  else echo "self-test FAIL cleanup trap"; FAILS=$((FAILS + 1)); fi

  rm -rf "$FX"
  if [ "$FAILS" = 0 ]; then echo "keeper_gate.sh --self-test: all fixtures behaved"; exit 0; fi
  echo "keeper_gate.sh --self-test: $FAILS fixture(s) FAILED"; exit 2
fi

# ------------------------------------------------------------------ a real run
[ -n "$STAGE" ] || die "--stage DIR is required (or --lock / --unlock / --self-test)"
[ -d "$STAGE" ] || die "stage $STAGE is not a directory"
STAGE="$(cd "$STAGE" && pwd)"
case "$STAGE" in "$HOME/.local/share/kick-live/live-snapshot"*|"$LIVE_RUN"*) die "the stage may not be the live snapshot or the run dir" ;; esac
mkdir -p "$WORK/report"
REPORT="$WORK/report/keeper_gate.txt"

run_main() {
echo "keeper_gate.sh  stage=$STAGE"
if [ "$AGAINST_TREE" = 1 ]; then
  BASE="$WORK/base-head"; mkdir -p "$BASE"
  git -C "$ROOT" archive HEAD | tar -x -C "$BASE" || die "git archive HEAD failed in $ROOT"
  echo "baseline=$BASE (git archive HEAD $(git -C "$ROOT" rev-parse --short HEAD) of $ROOT)"
else
  [ -d "$SNAPSHOT" ] || die "snapshot $SNAPSHOT is not a directory"
  BASE="$(cd "$SNAPSHOT" && pwd)"
  echo "baseline=$BASE (read only)"
fi
echo "live-run=$LIVE_RUN (read only)  lock=$LOCK  tag=$TAG"

if ! lock_check; then exit 3; fi

# ---- policy: the diff
GOVERNED=(stream agents scripts monitor kickapp docs/art-rules.md docs/AGES.md docs/IDLEWORLD.md)
CHANGED=()
for g in "${GOVERNED[@]}"; do
  if [ -e "$STAGE/$g" ] || [ -e "$BASE/$g" ]; then
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      CHANGED+=("$line")
    done < <(
      if [ -d "$STAGE/$g" ] || [ -d "$BASE/$g" ]; then
        diff -rq -x '__pycache__' -x '*.pyc' -x 'experiments' -x 'run' -x '.git' -x '.DS_Store' "$BASE/$g" "$STAGE/$g" 2>/dev/null \
          | sed -E -e "s#^Files $BASE/(.*) and $STAGE/.* differ\$#M \\1#" \
                   -e "s#^Only in $STAGE/?([^:]*): (.*)\$#A \\1/\\2#" \
                   -e "s#^Only in $BASE/?([^:]*): (.*)\$#D \\1/\\2#" \
          | sed -E 's#^([MAD]) /+#\1 #; s#//+#/#g'
      elif [ ! -e "$BASE/$g" ]; then echo "A $g"
      elif [ ! -e "$STAGE/$g" ]; then echo "D $g"
      else
        cmp -s "$BASE/$g" "$STAGE/$g" || echo "M $g"
      fi
    )
  fi
done
N_ALLOW=0; N_DENY=0; N_OUT=0; N_IGN=0
for c in "${CHANGED[@]+"${CHANGED[@]}"}"; do
  op="${c%% *}"; p="${c#* }"
  if rel_matches_ignore "$p"; then N_IGN=$((N_IGN + 1)); echo "policy IGNORE  $op $p"; continue; fi
  cls="$(classify_path "$p")"
  case "$cls" in
    ALLOW) N_ALLOW=$((N_ALLOW + 1)); echo "policy ALLOW   $op $p" ;;
    DENY) N_DENY=$((N_DENY + 1)); echo "policy DENY    $op $p" ;;
    *) N_OUT=$((N_OUT + 1)); echo "policy OUTSIDE $op $p" ;;
  esac
done
echo "policy: ${#CHANGED[@]} changed path(s): $N_ALLOW allow, $N_DENY deny, $N_OUT outside, $N_IGN ignored"
if [ "$N_DENY" -gt 0 ] || [ "$N_OUT" -gt 0 ]; then echo "policy FAIL: $((N_DENY + N_OUT)) path(s) outside ALLOW"; fail; else echo "policy PASS: every changed path is inside ALLOW"; fi

# ---- policy: land.py provenance / purge / restore bodies unchanged (by symbol)
if [ -f "$STAGE/stream/world/land.py" ] && [ -f "$BASE/stream/world/land.py" ]; then
  "$PY" - "$BASE/stream/world/land.py" "$STAGE/stream/world/land.py" <<'PYEOF' || fail
import ast, sys
GUARD = ("provenance_violations", "purge_owner", "restore_owner")
def bodies(path):
    out = {}
    try:
        tree = ast.parse(open(path).read())
    except Exception as e:
        print("policy land.py: cannot parse %s (%s)" % (path, e)); return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in GUARD:
            out[node.name] = ast.dump(node)
    return out
a, b = bodies(sys.argv[1]), bodies(sys.argv[2])
if a is None or b is None:
    sys.exit(1)
bad = [n for n in GUARD if a.get(n) != b.get(n)]
if bad:
    print("policy FAIL land.py guarded bodies changed: %s (5.2: provenance / purge / restore are outside ALLOW)" % ", ".join(bad)); sys.exit(1)
print("policy PASS land.py guarded bodies unchanged (%s)" % ", ".join(GUARD))
PYEOF
fi

# ---- hashes: honesty.py + state_store.py must equal the baseline's
for f in stream/world/honesty.py stream/state_store.py; do
  if [ ! -f "$STAGE/$f" ]; then echo "hash FAIL $f missing from stage"; fail; continue; fi
  hs="$(shasum -a 256 "$STAGE/$f" | cut -c1-64)"; hb="$(shasum -a 256 "$BASE/$f" 2>/dev/null | cut -c1-64)"
  if [ "$hs" = "$hb" ]; then echo "hash PASS $f sha256 ${hs:0:16}... == baseline"
  else echo "hash FAIL $f sha256 stage ${hs:0:16}... != baseline ${hb:0:16}..."; fail; fi
done

# ---- revert-word grep over ADDED lines of the tier-2 code (ALLOW-class .py only; identifiers / strings; comments
# stripped). DENY / OUTSIDE paths already fail the policy above, and ops code (category `cat_id`, `subprocess sleep`)
# and rule text in docs legitimately carry these words; the world code a keeper build may touch must not.
ADDED="$WORK/added.diff"; : > "$ADDED"
for c in "${CHANGED[@]+"${CHANGED[@]}"}"; do
  op="${c%% *}"; p="${c#* }"
  rel_matches_ignore "$p" && continue
  [ "$(classify_path "$p")" = ALLOW ] || continue
  case "$p" in *.py) ;; *) continue ;; esac
  if [ "$op" = D ]; then continue; fi
  if [ -d "$STAGE/$p" ]; then continue; fi
  if [ "$op" = A ]; then sed "s#^#+#" "$STAGE/$p" | sed "s#^#$p: #" >> "$ADDED"
  else diff -u "$BASE/$p" "$STAGE/$p" | grep -E '^\+' | grep -Ev '^\+\+\+ ' | sed "s#^#$p: #" >> "$ADDED"; fi
done
# `_` and camelCase joins count as word boundaries so `animal_count` / `AnimalKind` are hits (identifiers, not only strings)
REVERT_RE='(?<![A-Za-z0-9])(animals?|npcs?|mascots?|birds?|dogs?|cats?|fish|hunger|hungry|decay(s|ed|ing)?|starv(e|es|ed|ing|ation)|die|dies|dying|death|creatures\.)(?![A-Za-z0-9])'
SLEEP_RE='(["\x27])(a?sleep|sleeping|curled|burrowed)\1|\bSTATE_(A?SLEEP|SLEEPING)\b|\bsleep_t\b|\bnights_streak\b'
HITS="$("$PY" - "$ADDED" "$REVERT_RE" "$SLEEP_RE" <<'PYEOF'
import re, sys
path, rre, sre = sys.argv[1:4]
R, S = re.compile(rre, re.I), re.compile(sre)
n = 0
for ln in open(path, encoding="utf-8", errors="replace"):
    ln = ln.rstrip("\n")
    try:
        where, body = ln.split(": +", 1)
    except ValueError:
        continue
    code = body.split("#", 1)[0] if not body.lstrip().startswith("#") else ""
    if not code.strip():
        continue
    camel = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", code)
    m = R.search(camel) or S.search(code)
    if m:
        n += 1
        print("revert FAIL %s: %s  [%s]" % (where, body.strip()[:110], m.group(0)))
sys.exit(1 if n else 0)
PYEOF
)"; rc=$?
if [ $rc = 0 ]; then echo "revert PASS no revert-list word (animal npc mascot bird dog cat fish hunger decay starve die death, sleep-as-a-state) in $(grep -c . "$ADDED" || true) added line(s)"
else echo "$HITS"; fail; fi

# ---- world.json writers in agents/ and scripts/ (only the scene writes world.json; 0.2 row 2)
"$PY" - "$STAGE" <<'PYEOF' || fail
import ast, os, re, sys
stage = sys.argv[1]
files = []
for sub in ("agents", "scripts"):
    for dp, dn, fn in os.walk(os.path.join(stage, sub)):
        dn[:] = [d for d in dn if d not in ("__pycache__", "node_modules")]
        files += [os.path.join(dp, f) for f in fn if f.endswith(".py")]
WRITE_MODES = ("w", "a", "x", "r+", "w+", "a+", "wb", "ab")
hits = []
for path in sorted(files):
    rel = os.path.relpath(path, stage)
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except Exception as e:
        hits.append("%s: unparsable (%s)" % (rel, e)); continue
    def mentions_world(node):
        return any(isinstance(n, ast.Constant) and isinstance(n.value, str) and "world.json" in n.value for n in ast.walk(node))
    tainted = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and mentions_world(node.value):
            for t in node.targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        tainted.add(n.id)
    def is_world(node):
        return mentions_world(node) or any(isinstance(n, ast.Name) and n.id in tainted for n in ast.walk(node))
    RUNDIR_RE = re.compile(r"run_?dir|RUN_DIR|\blive\b|\bL\b", re.I)
    def names_in(node):
        return " ".join(n.id for n in ast.walk(node) if isinstance(n, ast.Name)) + " " + " ".join(
            n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute))
    def is_run_world(node):
        # a copy / rename whose DESTINATION is world.json inside a run dir (a scratch copy under /tmp is the sanctioned
        # pattern: prebake_land.py copies world.json INTO its scratch and never back)
        if not is_world(node):
            return False
        srcs = [node] + [a.value for a in ast.walk(tree) if isinstance(a, ast.Assign)
                         and any(isinstance(t, ast.Name) and t.id in tainted and any(isinstance(n, ast.Name) and n.id == t.id for n in ast.walk(node)) for t in a.targets)]
        return any(RUNDIR_RE.search(names_in(x)) for x in srcs)
    handles = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
        args = node.args
        if name == "open" and args and is_world(args[0]):
            mode = None
            if len(args) > 1 and isinstance(args[1], ast.Constant):
                mode = args[1].value
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = kw.value.value
            if isinstance(mode, str) and any(m in mode for m in ("w", "a", "x", "+")):
                hits.append("%s:%d open(%s, %r) on a world.json path" % (rel, node.lineno, ast.unparse(args[0]) if hasattr(ast, "unparse") else "?", mode))
        elif name in ("replace", "rename", "copy", "copy2", "copyfile", "move") and len(args) >= 2 and is_run_world(args[1]):
            hits.append("%s:%d %s(..., run dir world.json) writes world.json" % (rel, node.lineno, name))
        elif name in ("write_text", "write_bytes") and isinstance(fn, ast.Attribute) and is_world(fn.value):
            hits.append("%s:%d %s on a world.json path" % (rel, node.lineno, name))
    # `with open(wp, "w") as fh: json.dump(x, fh)` is caught by the open() rule above; json.dump to a tainted handle too
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            for item in node.items:
                c = item.context_expr
                if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "open" and c.args and is_world(c.args[0]) and item.optional_vars is not None:
                    mode = c.args[1].value if len(c.args) > 1 and isinstance(c.args[1], ast.Constant) else "r"
                    if any(m in str(mode) for m in ("w", "a", "x", "+")):
                        for n in ast.walk(item.optional_vars):
                            if isinstance(n, ast.Name):
                                handles.add(n.id)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "dump" and len(node.args) >= 2:
            tgt = node.args[1]
            if isinstance(tgt, ast.Name) and tgt.id in handles:
                hits.append("%s:%d json.dump into a world.json handle" % (rel, node.lineno))
if hits:
    for h in hits:
        print("writer FAIL " + h)
    sys.exit(1)
print("writer PASS no world.json writer in agents/ or scripts/ (%d file(s) scanned)" % len(files))
PYEOF

# ------------------------------------------------------------------ gates 1-11, printed in the spec's order
# gate 1: pause_bot.json absent
if [ -e "$LIVE_RUN/pause_bot.json" ]; then gate 1 FAIL pause_bot.json "present at $LIVE_RUN/pause_bot.json (owner's pause; change nothing)"; fail
else gate 1 PASS pause_bot.json "absent in $LIVE_RUN"; fi

# gate 2: df avail >= 20 GB
FREE="$(free_gb /tmp)"
if [ -n "$FREE" ] && [ "$FREE" -ge "$MIN_FREE_GB" ]; then gate 2 PASS df "avail ${FREE} GB on /tmp (>= ${MIN_FREE_GB})"; HEAVY_OK=1
else gate 2 FAIL df "avail ${FREE:-?} GB on /tmp (< ${MIN_FREE_GB}); heavy gates refused"; HEAVY_OK=0; fail; fi

# gate 3: py_compile
COMPILE_GLOBS=(stream/*.py stream/panels/*.py stream/scenes/*.py stream/world/*.py stream/world/art/*.py agents/*.py)
COMPILE_FILES=()
for g in "${COMPILE_GLOBS[@]}"; do for f in "$STAGE"/$g; do [ -f "$f" ] && COMPILE_FILES+=("$f"); done; done
if [ "${#COMPILE_FILES[@]}" = 0 ]; then gate 3 FAIL py_compile "no python files found under $STAGE"; fail
else
  out="$(cd "$STAGE" && "$PY" -m py_compile "${COMPILE_FILES[@]}" 2>&1)"; rc=$?
  find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
  if [ $rc = 0 ]; then gate 3 PASS py_compile "${#COMPILE_FILES[@]} files"; else gate 3 FAIL py_compile "$(echo "$out" | head -3 | tr '\n' ' ')"; fail; fi
fi

# gate 4: module self-tests under /tmp
declare -a ST_NAMES=(behaviour honesty state camera keepers chat_bridge rounds registry steading)
st_cmd() { # prints the command for a module self-test name, run dir = $1
  local rd="$1" n="$2"
  case "$n" in
    behaviour) echo "RUN_DIR=$rd $PY stream/world/behaviour.py --self-test" ;;
    honesty) echo "RUN_DIR=$rd $PY stream/world/honesty.py --self-test" ;;
    state) if grep -q -- '"--to"' "$STAGE/stream/world/state.py" 2>/dev/null && [ -f "$LIVE_RUN/world.json" ]; then   # W3 adds --to 3; HEAD has only the 1 -> 2 form
             echo "RUN_DIR=$rd $PY stream/world/state.py --self-test && cp $LIVE_RUN/world.json $rd/world.json && RUN_DIR=$rd $PY stream/world/state.py --migrate-copy $rd/world.json --to 3"
           else echo "RUN_DIR=$rd $PY stream/world/state.py --self-test"; fi ;;
    camera) echo "RUN_DIR=$rd $PY stream/world/camera.py --self-test" ;;
    keepers) echo "RUN_DIR=$rd $PY stream/world/keepers.py --self-test" ;;
    chat_bridge) echo "RUN_DIR=$rd $PY stream/chat_bridge.py --self-test" ;;
    rounds) echo "RUN_DIR=$rd $PY -m stream.rounds --self-test --run-dir $rd" ;;
    registry) if [ -f "$STAGE/stream/world/registry.py" ]; then echo "RUN_DIR=$rd $PY stream/world/registry.py --self-test"; else echo ""; fi ;;
    steading) echo "MODE=test RUN_DIR=$rd $PY stream/scenes/steading.py --self-test" ;;
  esac
}
if [ "$RUN_GATES" = 1 ] && [ "$HEAVY_OK" = 1 ]; then
  G4=0
  for n in "${ST_NAMES[@]}"; do
    rd="$WORK/st-$n"; mkdir -p "$rd"
    cmd="$(st_cmd "$rd" "$n")"
    if [ -z "$cmd" ]; then gate 4 SKIP "self-test:$n" "module absent from stage"; continue; fi
    t0=$(date +%s)
    if (cd "$STAGE" && env -u STREAM_KEY -u SRT_PASSPHRASE -u KICK_CLIENT_SECRET -u KICK_TOKEN -u NGROK_AUTHTOKEN -u KICK_CLIENT_ID bash -c "$cmd" > "$WORK/report/selftest-$n.log" 2>&1); then
      gate 4 PASS "self-test:$n" "$(( $(date +%s) - t0 )) s, log report/selftest-$n.log"
    else gate 4 FAIL "self-test:$n" "exit $?; tail: $(tail -2 "$WORK/report/selftest-$n.log" | tr '\n' ' ' | cut -c1-160)"; G4=1; fi
  done
  [ $G4 = 0 ] || fail
elif [ "$RUN_GATES" = 1 ]; then gate 4 SKIP self-tests "refused: under ${MIN_FREE_GB} GB free"; fail
else
  for n in "${ST_NAMES[@]}"; do cmd="$(st_cmd "/tmp/lg-${TAG}-st-$n" "$n")"; [ -n "$cmd" ] && gate 4 PLAN "self-test:$n" "(cd $STAGE && $cmd)"; done
fi

# gate 5: compositor 300 frames on copies of the live run files
SRUN="$WORK/stage-run"
N_PLAN="$COMPOSITOR_N"; [ "$N_PLAN" -gt 0 ] 2>/dev/null || N_PLAN=300
G5CMD="mkdir -p $SRUN && cp $LIVE_RUN/world.json $LIVE_RUN/chat.jsonl $LIVE_RUN/builders.json $SRUN/ && cd $STAGE && MODE=test RUN_DIR=$SRUN $PY stream/compositor.py --self-test $N_PLAN"
if [ "${COMPOSITOR_N:-0}" -gt 0 ] && [ "$HEAVY_OK" = 1 ]; then
  if [ ! -f "$LIVE_RUN/chat.jsonl" ] || [ ! -f "$LIVE_RUN/world.json" ]; then gate 5 FAIL compositor "no world.json + chat.jsonl in $LIVE_RUN (without chat.jsonl the pips are quarantined and honesty fails by design)"; fail
  else
    mkdir -p "$SRUN"; cp "$LIVE_RUN/world.json" "$LIVE_RUN/chat.jsonl" "$SRUN/"; [ -f "$LIVE_RUN/builders.json" ] && cp "$LIVE_RUN/builders.json" "$SRUN/"
    t0=$(date +%s)
    (cd "$STAGE" && env -u STREAM_KEY -u SRT_PASSPHRASE -u KICK_CLIENT_SECRET -u KICK_TOKEN -u NGROK_AUTHTOKEN -u KICK_CLIENT_ID MODE=test RUN_DIR="$SRUN" "$PY" stream/compositor.py --self-test "$COMPOSITOR_N" > "$WORK/report/compositor-selftest.log" 2>&1); rc=$?
    # the compositor exits 0 even when one of its printed gates fails: every `-> FAIL` line, a non-PASS honesty check
    # and a missing honesty line each fail this gate; p95 is quoted from its `frame budget` line
    CLOG="$WORK/report/compositor-selftest.log"
    hv="$(grep -Eo 'honesty check: (PASS|FAIL)[^;]*' "$CLOG" | tail -1 | cut -c1-90)"
    p95="$(grep -Eo 'frame budget: p95 [0-9.]+ ms[^>]*-> (PASS|FAIL)' "$CLOG" | tail -1)"
    nfail="$(grep -c -- '-> FAIL' "$CLOG" || true)"
    if [ $rc = 0 ] && [ "${nfail:-0}" = 0 ] && echo "$hv" | grep -q 'honesty check: PASS'; then
      gate 5 PASS compositor "$COMPOSITOR_N frames in $(( $(date +%s) - t0 )) s; ${hv}; ${p95:-frame budget line not found}; log report/compositor-selftest.log"
    else
      gate 5 FAIL compositor "exit $rc, ${nfail:-0} printed FAIL line(s); ${hv:-honesty line not found}; ${p95:-}; $(grep -- '-> FAIL' "$CLOG" | sed 's/^[0-9:]* compositor: //' | tr '\n' ' ' | cut -c1-200)"; fail
    fi
    rm -f "$SRUN"/selftest/frame_*.png "$SRUN"/bake/*.npy 2>/dev/null || true
  fi
elif [ "${COMPOSITOR_N:-0}" -gt 0 ]; then gate 5 SKIP compositor "refused: under ${MIN_FREE_GB} GB free"; fail
else gate 5 PLAN compositor "$G5CMD   # honesty_violations must be 0/0, p95 < 25 ms"; fi

# gate 6: static grep of added panel / scene strings against BANNED_COPY (+ day N / vN.N); _hud_checks runs inside gate 5
"$PY" - "$STAGE" "$ADDED" <<'PYEOF' || fail
import ast, os, re, sys
stage, added = sys.argv[1:3]
sys.path.insert(0, stage)
try:
    src = open(os.path.join(stage, "stream", "compositor.py"), encoding="utf-8").read()
    ns = {}
    for name in ("BANNED_COPY", "BANNED_COPY_RE", "BANNED_VERSION_RE", "BANNED_DAY_RE"):
        m = re.search(r"^%s\s*=\s*(.+?)(?=^\S)" % name, src, re.M | re.S)
        if not m:
            raise ValueError(name)
        exec("import re\n%s = %s" % (name, m.group(1).strip()), ns)
except Exception as e:
    print("gate 6  FAIL banned_copy         cannot load BANNED_COPY from the stage's compositor.py (%s)" % e); sys.exit(1)
R, V, D = ns["BANNED_COPY_RE"], ns["BANNED_VERSION_RE"], ns["BANNED_DAY_RE"]
STR_RE = re.compile(r"""(?P<q>["'])(?P<s>(?:\\.|(?!(?P=q)).)*)(?P=q)""")
hits, n = [], 0
for ln in open(added, encoding="utf-8", errors="replace"):
    try:
        where, body = ln.rstrip("\n").split(": +", 1)
    except ValueError:
        continue
    if not (where.startswith("stream/panels/") or where.startswith("stream/scenes/") or where.startswith("stream/world/")):
        continue
    code = body.split("#", 1)[0]
    for m in STR_RE.finditer(code):
        s = m.group("s")
        if len(s) < 3 or " " not in s and len(s) < 6:
            continue
        n += 1
        low = re.sub(r"@\S+", "", s.lower())
        if R.search(low) or V.search(low) or D.search(low):
            hits.append("%s: %r" % (where, s[:80]))
if hits:
    for h in hits:
        print("gate 6  FAIL banned_copy         added string carries a banned token: " + h)
    sys.exit(1)
print("gate 6  PASS banned_copy         %d added string literal(s) in panels/scenes/world pass BANNED_COPY + day N + vN.N (the frame check _hud_checks runs inside gate 5)" % n)
PYEOF

# gates 7-10 are live actions: printed, never run here (the owner decides deploy)
TS="$(date +%Y%m%dT%H%M%S)"
gate 7 SKIP backups "cp -a $SNAPSHOT $HOME/.local/share/kick-live/live-snapshot-v3-$TAG && cp $LIVE_RUN/world.json $LIVE_RUN/world.json.bak-pre-$TAG-$TS"
if [ "$N_ALLOW" -gt 0 ]; then
  CPLIST=""
  for c in "${CHANGED[@]+"${CHANGED[@]}"}"; do p="${c#* }"; rel_matches_ignore "$p" && continue; [ "$(classify_path "$p")" = ALLOW ] && CPLIST="$CPLIST $p"; done
  gate 8 SKIP cp-batch "ONE batch into S (world batch + scene + panel together):  (cd $STAGE && for f in$CPLIST; do cp \"\$f\" \"$SNAPSHOT/\$f\"; done)  # art/*.py needs scripts/deploy.sh (child restart)"
else gate 8 SKIP cp-batch "nothing to copy (0 ALLOW paths)"; fi
gate 9 SKIP watch-log "tail -f $LIVE_RUN/logs/compositor.log | grep -E 'committed after 30 clean renders|ROLLBACK|hot reload FAILED|Traceback'"
gate 10 SKIP hls-probe "RUN_DIR=$LIVE_RUN $PY validate/hls_probe.py --channel \${KICK_CHANNEL:-atleastonce} --seconds 8 --out $LIVE_RUN/probe/$TAG  # then Read last_frame.png"

# gate 11: cleanup (the EXIT trap does it; report it here)
gate 11 PASS cleanup "trap deletes selftest/frame_*.png + bake/*.npy under $WORK/* and $STAGE/run; report/ kept at $WORK/report"

if [ "$FAILS" = 0 ]; then echo "keeper_gate.sh: PASS (0 violations, every executed gate passed); report $REPORT"; exit 0; fi
echo "keeper_gate.sh: FAIL ($FAILS check(s) failed); report $REPORT"; exit 2
}
run_main 2>&1 | tee "$REPORT"
exit "${PIPESTATUS[0]}"
