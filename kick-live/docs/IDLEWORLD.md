# IDLEWORLD — an idle world that chat shapes: accrual, the wish ledger, the feedback ladder, the probe loop (spec, 2026-09-27, synthesis)

> **Release status, 2026-09-27 13:36 AEST:** The stream is live. Schema 3, persistent settlers without sleep,
> errands/ROAM, personal return summaries, pixel-art sprites with natural tones, the age director and the wish post
> are deployed. See `HANDOFF.md` for operational truth. Earlier “design only”, “stream OFF”, schema-2 and sleep
> descriptions below are historical context, not current instructions. The 100-chatter feedback/scale rows and
> open-ended new-mechanic generation beyond the shipped recipes remain follow-up work, not completed features.

Owner direction (terminal, 2026-09-27 morning; binding): *"built like a generative world that is similar to an idle
game. The world should progress through stages and chat can build and shape that as it goes ... dynamically generate
what the chat is asking for ... Let chat shape it but also create a general structure and flow. Every time someone
chats they then exist in the world forever. Create an agent that is on a loop that continuously probes and questions
how the world is going ... feed back ideas."* Follow-up: per-chatter agents at 100 concurrent chatters, and *"People
love feedback on the screen ... at least sometimes, their messages are known to be ingested."*

This is the synthesis of four lenses (idle-game systems, generative content, live-stream feedback, honesty and
operations) and three judges. **Spine: the idle-game LEDGER built on `docs/AGES.md`** (three keys, no sleep, the age
ladder, the 90 s build). Grafted: the content architect's recipe REGISTRY as data behind the wish post; the feedback
designer's count budgets, conditional acks and the eight probe questions; the auditor's guardrails as preconditions,
not afterthoughts (one writer per file, write-time copy validation, the keeper gate, the two 100-chatter frame-path
bombs). Every conflict the judges found is resolved in §0.2. Design only: nothing here is implemented, the stream is
OFF, and every implementation step is test-mode in this worktree.

All paths under `/Users/sandy/Workspace/agentic-builds/.claude/worktrees/idle-world/kick-live` (HEAD a2d5fc4). Run dir
`L=~/.local/share/kick-live/run-live` (read only), snapshot `S=~/.local/share/kick-live/live-snapshot-v3`,
`PY=~/.local/share/kick-live/venv/bin/python` (3.9, numpy 2.0.2, Pillow 11.3.0).

---

## 0. Ground truth and decisions

### 0.1 Read from the tree and the run dir (2026-09-27; not from any brief)

- **The stream is OFF.** The owner typed `nuke` at 20:13:51 local on 26 Sep (`L/chat.jsonl` last line, badges
  broadcaster); `scripts/stop.sh` wrote `pipeline stopped` at 20:15:14; `L/pids/` is empty; only ngrok + kickapp survive.
  Nothing in this spec touches `L`; implementation runs under `RUN_DIR=/tmp/lg-*` in `MODE=test`; going live (and the
  one relay-held child restart the spine edits need) is the owner's decision.
- `L/world.json` schema 2: **3 pips** (atleastonce voting / gear 2 / 336 min / 52 msgs / camp tier 1 at 521,231; Sami
  walking / 2 / 141 min / 25 msgs / camp 1 at 547,295; Lordoomer asleep / 1 / 20 min / 2 msgs / camp 0 at 590,284);
  **16 stones** all cairn `moot` (Sami 9, atleastonce 5, Lordoomer 2), 3 flower marks, 0 fields, `raisings []`,
  `hatched_ever 3`, `bake_ver 3`, cursor offset 29747 of 30605 bytes. `L/chat.jsonl`: 109 lines, **97 unique ids**,
  3 chatters, 3 calendar dates (UTC == AEST for every record): plain 41, verb 29, vote 17, idea 10. Unparsed
  verb-like heads the grammar drops: `dig` 8, `build` 4, `theme` 4, `cut` 1, `climb` 1, `zoom` 1. **Only 6 of 10
  `!idea` texts exist in `state.json ideas[]`** (`rounds._apply_chat` L1277 drops the 2nd idea inside 180 s and the 4th
  open one silently; the 60 s history cutoff across 15 supervisor restarts ate the rest) while the bridge acked
  `on the board` for all ten (`chat_bridge.py` L1071).
- **The STONES key has no chat source today.** `stack` is in `LATER_VERBS` (`chat_bridge.py` L220-221) and `_check_verb`
  refuses it at L1200 before its 45 s cooldown (L222-224) and its cap of 3 (L1221-1222) are ever reached; all 16 live
  stones came from `rounds._expedition_watch` (L1070-1116). The path below the refusal is complete and unexercised:
  `parse_verb` L735 -> `_queue_verb` -> `pump` L1248 -> `steading.command("stack")` L1934-1948 (nearest Fell boulder
  -> `behaviour.fetch` L1119-1126 -> `_arrive` pickup/place L1517-1536 -> `_persist` `place:stone` L875-887 ->
  `land.stack` L663-673, ONE record) -> `stone` event -> plank L1273-1278.
- **Two agency gates test `is_awake`:** `rounds._expedition_watch` L1096 and `Behaviour.fetch` L1123. After AGES row 1
  (`is_awake` -> `is_on_land`, true for away bodies) both would credit an away body with a stone. They move to
  `is_present()` in the same deploy as the stack un-refusal (§0.2 row 8).
- **No on-air copy guard exists.** `compositor.BANNED_COPY` (L71-79) is applied by `_hud_checks` (L811), which is called
  only from `run_selftest` (L1120), never in `run_stream`. Any string the panel draws from chatter or model text has no
  live check. Every wish-derived string in this spec is a closed-table noun validated at WRITE time (§5.1).
- **Two 100-chatter frame-path bombs:** `honesty._refresh_chat_names` (L167-179) re-reads the whole `chat.jsonl` every
  2 s whenever its size changed (seconds per scan at ~90 MB/day on the frame thread); `recompute_from_chat` caps its
  read at 64 MB (`state.py` L873, L886-887) and silently forgets the oldest chatters on a cold boot, which breaks
  exists-forever. Both are fixed in §7 before any growth push.
- **Hot-reload boundary** (`compositor.HotReloader.WATCH` L194-196, non-recursive): `stream/panels`, `stream/scenes`,
  `stream/world/*.py` hot-reload as one batch (`WORLD_ORDER` L384; a never-imported new world module is imported fresh by
  the scene, L402-404, so a NEW `stream/world/registry.py` needs no compositor edit). Spine files (`compositor.py`,
  `chat_bridge.py`, `rounds.py`, `state_store.py`, `audio.py`, `layout.py`, `relay.py`) and `stream/world/art/*.py`
  need `scripts/deploy.sh` (relay-held child restart, ffmpeg untouched, owner told first).
- **Text layer facts:** plank = ONE HN Medium 22 row at (16,16), `PRIO_EVENT 1 < VERB 2 < LIGHT 3 < YOU 4 < CREDITS 5`
  (`panels/world.py` L139), notices capped at 16 (L1125); ONE plate per `PLATE_ROTATE_S 5` (L208); bubbles Menlo 22, one
  per pip, 8 s (L2032-2095); `DENSITY_FALLBACK 40` (L110) flips labels to on-speak; `_notice` L1115; `_consume_events`
  L1129-1335; `_mark_list` L2622-2698; camera `EVENT_TYPES` L70 with `EVENT_HOLD_S 4`, 1.5x hatch close-up while <= 2
  awake (L69, L402-404). `MOOT_LAYOUT` (`steading.py` L111-117): beacon (6,-10), hearth (-16,10), cairn (16,10), sign
  (0,46); the sign is drawn <= 480 px wide (120 cells at 1x) centred on its post, so nothing else may sit on row 46.
- **Ownership and writers:** `state.json` has four writers under `OWNED_PATHS` (`state_store.py` L121-131, flock +
  atomic replace, O(file) per write; `RoundEngine.merge_foreign` L196 overwrites foreign drift within a frame);
  `world.json` has exactly ONE writer (the scene's `_persist`, atomic tmp+replace, no lock: a second writer loses
  records); `ideas[]` is capped at `IDEAS_KEEP 50` (L177); `_append_jsonl` (`rounds.py` L498-506) and `JsonlTail`
  (`state_store.py` L359-405) are the append-only pattern already used for `ships.jsonl`.
- **Kit:** `buildings.KINDS = hut well garden fence_h fence_v banner lantern smoke` (L43, `render` L256-289, closed
  if/elif L272-287); props `tree bush flowers stone cairn(1..5) waystone campfire beacon glow` (`props.py` L65-278); no
  bridge, no monument, no post sprite; `Keepers.reveal_rows` (L827) has NO drawing consumer; `RAISING_SITES` L90-94.
- **Measured budget:** C2 (60 pips, 0.75x) scene avg 11.41 / p95 12.08 / max 15.02 ms; contended by the sheet worker
  13.24 / 20.79 / 26.0 (AGES §0.1). Nothing at 100 here settlers has been measured.
- **Disk:** 36 GiB free, 4.2 GB of stale `/tmp/lg-*` (4838 frame PNGs, 40 `.npy`). Every harness below cleans up and
  refuses under 20 GB (journal 035).

### 0.2 Decisions in one table (the judges' fatal flaws removed, the grafts folded in)

| # | question | decision | why |
|---|---|---|---|
| 1 | where wishes live: `state.json wishes[]` (P1, P3) vs append-only jsonl (P2, P4) | **`$RUN_DIR/wishes.jsonl`**, append-only, never truncated, re-derivable from `chat.jsonl` by `recompute_wishes` at boot; NO `wishes[]` block in `state.json`; the agent's channel is a separate append-only `wish_class.jsonl`; the scene's outcomes are `wishes.out.jsonl` | one syscall per message, one writer thread, no flock whole-file rewrite per plain message at 100 msg/min, no `WISHES_KEEP` drop (exists forever), no ownership fight with `merge_foreign` |
| 2 | who writes `world.json` | **the scene only** (`_persist`); agents append jsonl the scene tails; no agent uses `duty._plain_merge`; the gate greps `agents/` for `world.json` writes | atomic replace with no lock: two writers lose records |
| 3 | where the validator lives | **`honesty.py`** (`validate_registry`, `FN_ALLOWLIST`), byte-hashed by `scripts/keeper_gate.sh`; recipes, keyword tables, caps and refusal copy are DATA in `stream/world/registry.py` (hot-reload, tunable) | the code that makes "chat is data" true is not in the sandbox an agent may widen; the tunables stay tunable |
| 4 | what a plate / plank / post may quote | **a closed-table noun only** (`a castle`, `a lantern`, `fog`); the chatter's sentence appears only in their own bubble; every panel-composed string passes `BANNED_COPY_RE` + `BANNED_DAY_RE` + `BANNED_VERSION_RE` + `WordLists.blocked` at write time | the on-air copy check does not exist (0.1); `wished: build a castle` would carry a banned token to air |
| 5 | the instant beat for a wish: paper pin (P1) vs keyword plank (P2) vs silent until an orchestrator takes it (P3) vs registry row (P4) | **same-frame, deterministic, in-process:** the bridge tags `m["wish"]`, the SCENE classifies with the keyword table (a dict lookup) at ingest, pins ONE paper per person on the wish post and emits `wish`; the plank says `@kai's wish is pinned · a castle · 4 pinned`; no model, no file round trip, no daemon on the stranger's clock | the ack must never depend on a process that can be dead |
| 6 | fulfilment lanes and latency | **four tiers by size class** (§2.3): 0 same-frame (hop, bubble, verb, hint, paper); 1 kit recipes placed by the owner's camp within minutes, paced one raise per 90 s, capped per person and age; 2 mechanics/menu through `ideas[]` / the ballot; 3 projects (castle, bridge, hall, well, plaza, harbour) as AGE CONTENTS and Century wish slots, never ad hoc | a stranger owns a named thing in minute three; a castle stays a ladder goal the plate counts (`a castle · 12 ask`), never a promise |
| 7 | on-screen promises: `taken` (P3), `next: Kai's lantern`, `the Town raises it` (P2) | **none.** The only wish beats are `pinned` (a record the person made), `+N` / `N ask` (a `len()`), and `stands` / `rose` (a record placed). `taken` lives in the board and the ledger only | the plate never says a structure is coming; an age never waits on the agents (AGES §2.1) |
| 8 | stack cap / cooldown: age-scaled (P1) vs fixed (P4) | **v1 keeps 45 s / 3**, hauling day 20 s / 6; the Fell round trip median is MEASURED in the S1 gate; `AGE_VERBS` with age-scaled caps is v1.1 (§1.3) | the boulder walk is a griefing surface never exercised live; measure before loosening |
| 9 | hint `build` -> camp or stack | **both, by object:** `build` + a camp noun (`hut tent house home settle pitch`) -> `try: camp`; `build` alone or + `stone(s) rock cairn` -> `try: stack stone` | `hint_for` takes the FIRST synonym token (L686); moving `build` blindly turns the live `Build a hut here` into `try: stack stone` |
| 10 | refusal copy | **as short as a sign, never a rule recital, names what CAN be done**; greetings / goodbyes / clock words / UI asks are SILENT (the bubble is the ack); one refusal per person per 30 s; the person's words never echoed | `every walker is a person`, `the sun here is the real sun`, `that is outside the land` are explainer copy (owner 032) |
| 11 | telemetry on the plank (`14 spoke · 2 wishes taken`) | **no message counts on any surface**; counts shown are people, stones, days, pinned, standing, ask | a chat-volume count is Kick's number in world clothing |
| 12 | wish surface: P1 post at (-6,46), P2 post at (-14,46), P3 rail on the board between rounds | **ONE wish post at `MOOT_LAYOUT["post"] = (34, 10)`** (east of the cairn, outside the green, inside the 1.5x Moot dwell frame), one prop with 1..5 papers, reserved in the placer; the rail is dropped | row 46 belongs to the 480 px sign; the board is empty ~3 % of the time (180 s rounds + 5 s hold + immediate reopen) |
| 13 | the model | **nothing on any person's clock needs a model.** Keyword classing is in-process; the probe's THINK step (a Claude session or `claude -p`) proposes only; a batched model call for long-tail clustering / recipe drafting is `--model`, off by default, budget-capped, writes only closed enums into `wish_class.jsonl` | the streaming box owes no network dependency; a wrong model output becomes `chat`, never a pixel |
| 14 | probe autonomy (`--act`) | **propose-only, always.** The orchestrator (a session) builds through `agents/workflows/wish-build.js`; the owner decides deploy | an unattended agent editing world code beside the encoder is the 4.2 GB frame-dump pattern |
| 15 | return line at 100 chatters in the bubble (P3) vs on the plank (P1) | **plank, `PRIO_YOU`, always**; batched `@kai @jo are back` above 2 returns in 5 s with each personal line following FIFO 4 s | bubbles carry only the person's own words (pips never generate text) |
| 16 | which records become ledger rows | **every moderated record that is not a vote, a mod command or history** (plain incl. verb-parsed, `!idea`, `!theme`, `!ask`); the post pins only wish-tagged rows the classifier does not class `chat / clock / outside / theme` | the ledger mirrors chat; the post shows asks |
| 17 | placement caps (P2 3 lifetime / P4 3 per day / P1 one notice) | **one table in `registry.CAPS`:** a person's FIRST placed thing is never refused by the age cap; then 1 per session, lifetime `2 + camp tier`; age total (beyond first items) `{0: 12, 1: 30, 2: 80, 3: 200, 4: 500, +120 per Century}`; one open paper per person | the 9th first-timer must never see `full`; regulars accumulate a plot, not a pile |
| 18 | fences / a second beacon as recipes (P1 castle, P2 garden fences, beacon_post) | **never a recipe a chatter can ask for.** Fences are age-built only (AGES §2.3; art-rules exception written first); the beacon is the keepers' one lantern | the revert list; a second beacon reads as keeper presence no heartbeat backs |
| 19 | wish text reaching agents (P4 "an LLM writing a sprite from chat" vs the owner's brief) | **wish text reaches an agent only as quoted data inside a fixed JSON schema and the CONTRACT; outputs are data validated against the closed registry, or code through `keeper_gate.sh`'s allowlist; wish text is never in a shell string, a file path or a prompt's instruction position** | the sanctioned `!idea -> duty macro` path already does this; forbidding it blocks the brief |
| 20 | pip counters (`pip.wishes.asked/taken/raised`) | **none incremented**; every number derives at read time from the ledger / `placed[]`; `last_told` is a snapshot, not a counter | every number a `len()` |
| 21 | probe cadence and journal | **one 20 min THINK tick** (5 min above 50 msgs/min; OBSERVE every 10 min in Python), JSON report every tick, a journal paragraph ONLY when something changed or a proposal is made | a paragraph every 20 min is 72 commits a day |
| 22 | serial order on `steading.py` / `behaviour.py` / `honesty.py` | **one published lane W** (§8): AGES rows 1-4, then W5 return beat, W6 wish post + registry consumer, W7 density, W8 scale; one agent at a time | journal 034 |

### 0.3 What this keeps, fixes and supersedes in AGES.md and OPENWORLD.md

**Kept from AGES.md, unchanged:** the here/away axes (§1.1), camps at hatch and `camp_tier_for(p, age)` (§1.2), the
errand table and variety rules (§1.3), ROAM (§1.4), the three keys and `AGE_LADDER ((1,0,1),(3,10,2),(5,30,5),
(10,80,10),(25,200,25))` with Centuries `(25+25k, 200+200k, 25+25k)` (§2.1-2.2), what rises per age (§2.3), the
monument plate in two forms (§2.4), the 90 s build (§2.5), the menu changes (§3), the honesty mechanics (§4.2), schema
3 (§5), the budget (§6), rows 1-4 of the build order (§7, renumbered W1-W4 here with hours revised upward).

**Fixed in AGES.md (before W4 ships; each is a banned token or an art rule):** §2.4 / §2.5 plank `Longgrass is a
Steading · ...` -> `the Steading · 5 people · 31 stones · 5 days` (`longgrass` is in `BANNED_COPY`); §4.1 rule text
`day 3` -> `3 days` (`BANNED_DAY_RE`); §2.5 the beacon flare during a build must be <= 1 Hz (today's raising flare
toggles at 2 Hz, `steading.py` L1518-1519); §1.1 `awake_count` alias is code only, never a drawn word; §3 "`stack`
unchanged" is wrong: `stack` is refused today and is un-refused by S1; §2.3 fences and lantern posts ship only after
the art-rules §2 exception is written (D1).

**Superseded:** AGES §7 rows 5-8 are re-cut into lanes S, P, Q, D and the later list (§8); OPENWORLD §10's raisings
for `!idea` builds become the tier-2 lane through the keeper gate; OPENWORLD §11's "nightly board" becomes a real plate
(§1.4); OPENWORLD §12 bullets are replaced by §5.1 here; OPENWORLD §8's object table gains the wish post and its plate
forms (D1).

---

## 1. Structure and flow: the idle game

### 1.1 What accrues, who owns it, what never moves by itself

Idle games retain on five beats: visible accrual while away, tiers that unlock verbs and sights, a return beat, earned
milestones, and prestige without loss. All five fit the owner's rules **if every accrual is a `len()` over real records
and the only things that move by themselves are real time and real nature.** People never accrue anything by being
away; the LAND accrues around their records.

| ledger | records (all `len()`s, nothing spent, nothing decays) | source |
|---|---|---|
| per message | one pip row forever (`ensure_pip` `state.py` L430-466); `own_messages`; `words{}` (L479-496); `last_seen_ts`; ONE ledger row in `wishes.jsonl` (§2.1); the hop at `show_t` (`behaviour.message` L775-791) | chat.jsonl |
| per person | `days_seen[]` (AGES §1.2), `minutes_present` (here only), stones (`stones[].by`), marks (`marks[].owner`), camp tier (`camp_tier_for(p, age)`), gear tier (`tier_for` L537-549: 5 msgs / 10 min -> 1; 3 sessions / 120 min -> 2; 10 / 600 -> 3), `placed[]` rows owned or asked, `last_told` snapshot (§1.4), `camp.tiers[]` history | world.json |
| per day | `days_on_air[]`; the nightly board from timestamps (§1.4) | chat.jsonl, world.json |
| per age | `age`, `age_history[].raised_by` (every key on the land at the turn, top stackers first, PLUS the project askers, §2.3 tier 3), `stones_placed`, Century wish slots | world.json |

Real nature that moves between visits (art-rules §2 lists "the growth of planted things by real calendar days"):
`tree_stage` (exists, `land.py` L406: sapling -> young at real day 3 -> canopy at day 14, 1.5x on the Orchard); NEW
flower drift growth: a flower mark draws 1 bloom at planting, 3 at real day 2, a 5-bloom drift at real day 7
(`stage_by_days(mark.ts)`, the same helper as trees; drawn by the bake as extra `props.flowers` clumps on a short
curve round the mark cell; **no new record, `len(marks)` unchanged, owner unchanged**; the plate reads `flower · @x ·
since 26 Sep`); sun, moon, season, weather chain, wind = chat rate; the errand life of away settlers (AGES §1.3: the
land moves them, they never write a record).

### 1.2 The ladder (AGES §2.2, kept) and what each rung unlocks

| idx | name | people / stones / days | verbs open (v1.1 `AGE_VERBS`; v1 = today's set minus the `stack` refusal) | sights (AGES §2.3, kit only unless ART) | wish lanes open |
|---|---|---|---|---|---|
| 0 | the Clearing | 1 / 0 / 1 | go home plant camp fire feed pet gift wave sit dance name stack | pressed grass, bedrolls, waystones, beacon, board, cairn, **the wish post** | recipes (first item per person always; age total 12) |
| 1 | the Camp (earned: 3 / 16 / 3) | 3 / 10 / 2 | same | hearth ring, the pile, tent floor, monument plate | recipes total 30; 0 wish slots |
| 2 | the Steading | 5 / 30 / 5 | + sow harvest water | well, waystone cap marks, age-built fences round sown fields, dirt spokes | recipes 80; 1 wish slot (§2.3) |
| 3 | the Village | 10 / 80 / 10 | + swim sing teach | hut floor, longhouse at 8 days / 600 min, plaza, banners, presence-lit lantern posts, Ford bridge (ART) | recipes 200; 2 slots |
| 4 | the Town | 25 / 200 / 25 | + explore | the hall with sunrise / sunset bell, monument top (ART), stone bases, the Coast strip | recipes 500; 3 slots |
| 5+ | the Nth Century | +25 / +200 / +25 | | one monument ring per Century + the slot structures | +120 recipes; 3 + k slots |

Personal ladder (never needs other people, so a solo regular has a two-week arc while the people key waits): camp
0/1/2/3 by `days_seen` 1/2/4/8 or minutes 0/30/180/600 with the age floor and the age+1 ceiling (AGES §1.2; `land.py`
`camp_tier_for` replaces `camp_tier_for_sessions` L85-93; `set_camp` L473-499 never lowers; NEW `camp.tiers[]` row per
rise for the nightly board); gear 0-3 by `tier_for`; trees and flower drifts by real days; placed things by asks.

Collective projects, all `len()`-driven: the age build (AGES §2.5), hauling day, expeditions (arrival stones for HERE
walkers only), desire paths (wear thresholds 8/48/160 -> path0/1/2, `bake.py` L58, L181-203), the land strips at
10/25/50 people (`keepers.LAND_STRIP_MILESTONES` L89), and the wish slots.

### 1.3 The stone key, fixed honestly (slice S1)

The fix is one honest edit plus a hint table, not a new key: remove `"stack"` from the `LATER_VERBS` tuple
(`chat_bridge.py` L221). Keep 45 s / cap 3 (L222-224, L1221-1222); hauling day sets 20 s / 6 for the round through
`RoundEngine._world_effect` (L910-1024) writing `self.bridge.hauling_until = now + window` (RoundEngine already holds
`self.bridge`, L1287) which `_check_verb` reads; `stones_double` (L865-870) and the `x2` title are deleted; the card
title becomes `hauling day · stones for the Steading` (the next age name from the ladder via `_get_world`, else
`hauling day`). Hints: `HINT_VERB_SYNONYMS` (L207) gains `"stone": "stack", "stones": "stack", "rock": "stack", "cairn":
"stack"`; `"build"` becomes a two-branch rule in `hint_for` (L654-720): if any token is in `("hut", "tent", "house",
"home", "settle", "pitch")` -> `camp`, else `stack`; `HINT_EXAMPLES` (L215) gains `"stack": "stack stone"`; the
still-gated verbs' copy becomes `%s · not yet · try: stack stone · plant a flower · camp` (v1) and, once ages exist,
`sow · when the Steading stands · try: stack stone` (v1.1 `AGE_VERBS = {"stack": 0, "sow": 2, "harvest": 2, "water":
2, "swim": 3, "sing": 3, "teach": 3, "explore": 4}` read through `_get_world` L863-884 -> `scene.age()`; refuse when no
world). `monitor/chatter_log.py` VERBS (L80-82) already lists `stack`; it gains an `unparsed-head` kind for `dig build
cut climb zoom`. Agency gates in the SAME child restart: `rounds._expedition_watch` L1096 `is_awake()` ->
`is_present()`; `Behaviour.fetch` L1123 likewise (behaviour.py is lane W, so W1 carries that one line).

Why STONES stays the labour key: a key must be performable by a here person today, capped per session (attention, not
grind), one record per act, and visibly accumulating in one place. `stack` is all four once un-refused. Marks are a
3-per-session spam lever with a 40 lifetime cap (`MARK_CAP_LIFETIME` L64); messages are not labour; wishes are never a
key. **Gate before S1 ships:** measure the median `stack` round trip from three Steading-ring camps to the nearest
`terrain.boulders` (L169, filtered outside the Moot ring at L513) in `steading --self-test`; if > 60 s, add a nearer
seeded boulder field to the terrain generator (world content, not a mark) in the same slice.

### 1.4 The return beat and the nightly board ("look what grew")

Fires on the `return` event (AGES §1.1: `behaviour.message` L783-785 emits `return` instead of `wake` when the gap
exceeds `PRESENT_S`). `pip.last_told = {ts, age, camp_tier, tree_stage, flower_stage, placed, people, stones}` is
written at hatch and after every return line (schema 3, `_default_pip` L170-191; written in `steading._persist` where
`wake` is handled today, L845-855). The scene attaches `ev["told"] = last_told` and `ev["now"] = {same keys}` to the
event, then overwrites `last_told`. The panel (`_consume_events`, a `return` branch beside `wake` L1193) composes up to
THREE clauses in this order, each a diff of `len()`s, then the plank at `PRIO_YOU`:

| diff | clause |
|---|---|
| `age_history` rows with `ts > told.ts` | `the Camp rose` / two rows `the Camp and the Steading rose` |
| own camp tier rose | `your tent is a hut` (tier 1 -> 2), `your camp is a tent` (0 -> 1), `your hut has a chimney` (2 -> 3) |
| own `tree_stage` max rose | `your tree has a canopy` / `your tree is young` |
| own flower drift stage rose | `your flowers spread` |
| own placed / asked `placed[]` rows with `ts > told.ts` | `your lantern stands` / `the castle stands` |
| `hatched_ever` delta | `4 walked in` |
| `len(stones)` delta | `9 stones went up` |

Example: `@kai is back · the Camp rose · your tent is a hut · 4 walked in`. Empty diff: `@kai is back`; under 20 min
away nothing at all (today's rule). After 7+ days away: three bells (`audio._camp_bell` L706 x3 in the owner's degree)
and everyone within 50 cells looks (AGES §1.1). The camera glides to the settler wherever its errand took it (AGES
§1.4). The monument plate pins 10 s. At the same moment `_idle_life` (L1257-1276) has the settler mutter its person's
own top word from `words{}` once (here-only, the existing allowlisted-own-words path): a delayed personal proof the
world kept their words. Banned-copy fixture: every clause form above is asserted clean (`rose`, `stands`, `spread`,
`walked in`, `went up`, `is back`; never `built`, `day N`, `awake`).

**The nightly board.** On the first `here` of a new local date (`record_visit`, `state.ensure_camp` L601-625 edit site)
the scene emits `day_turn`; for 10 minutes the ONE-plate rotation carries `yesterday · @sami stacked 3 · 1 walked in ·
@kai's tent rose · a lantern stands`, computed from `stones[].ts`, `pips[].born_ts`, `camp.tiers[].ts`, `placed[].ts`
(only clauses with a count > 0; at most four; names through `_shown` L1092). Never a `day N` token.

**Founders' plaques.** `age_history[-1].raised_by` on the monument plate: `the Camp · since 26 Sep · raised by @sami
@atleastonce @lordoomer`; above 6 names `raised by @sami @atleastonce and 14 others`. A banish masks the name
(`builder #N`) but never drops the row (`purge_owner` L829-845 never lowers age or edits `age_history`).

**Camp plate** (`_mark_list` L2639-2640): `@kai's camp · 1 day here · first here 26 Sep` (`first_seen_ts` exists).
**`!stats`** (`_stats_card` L1523): `@kai · hut · 3 days here · 5 stones · 41 min here · 1 stands · the Camp`.

### 1.5 The roster: exists forever, asserted

One pip per chatter ever (`ensure_pip` is the only constructor; `recompute_from_chat` L873-960 replays chat.jsonl from
the cursor at boot); one ledger row per eligible message ever (`recompute_wishes`, §2.1, re-derives `wishes.jsonl`
from `chat.jsonl` alone); one `placed[]` row per thing ever placed; one `age_history` row per age. Honesty `roster`
rule (AGES §4.2): `len(on-land entities) == len(real pip rows) == distinct real chatters ever minus banished minus
quarantined`, plus NEW: `len(wishes.jsonl ids) >= eligible records since cursor.wishes_offset` at boot (printed by the
migration gate), and every `placed[].owner`, `placed[].askers[]`, `wish_post[].key` a real pip. `!banish` is the only
subtraction and keeps an audit record (`purge_owner`); rotation (§7.4) archives, never deletes.

### 1.6 The world at 1-2 viewers, honestly

Real time and real nature move (§1.1); one message per calendar day advances DAYS; the owner alone can stack 3 stones a
night (6 on hauling day), plant, and climb the personal camp ladder by days; a stranger's first recipe wish stands by
their camp within minutes (tier 1 is deterministic and needs nobody else); the flower they planted is a drift when
they return; the nightly board names last night's stackers. What cannot move solo is the PEOPLE key, and the forward
plate says exactly why: `the Steading · 2 more people · 14 more stones · 2 more days` (most binding first). That is
the classic idle-game "next unlock" line and it is true. The stall detector is the probe (§4), never a nudge or a fake
count. At ZERO viewers: away settlers errand between camps, Moot and water (ROAM), weather and season move, trees and
drifts grow by real days, the keys wait for a real person, the plank is blank.

### 1.7 One stranger, one regular

**A stranger, minutes:** types anything; a tuft lands at the Moot; 3 s later it hatches in their name colour, camera
EVENT 1.5x, plank `that's you, @kai`, a camp appears on the Steading ring with plate `@kai's camp · 1 day here`; their
words float over their head verbatim. `go river`: they watch themselves walk. `stack stone`: they fetch a boulder from
the Fell and set it on the cairn: `stone 17 · 13 more until the Steading`. `a lantern by my tent`: the same frame a
paper goes up on the wish post, `@kai's wish is pinned · a lantern · 1 pinned`; within 90 s the camera eases to their
camp (<= 2 here), a lantern post rises bottom-up over 20 s while their settler walks over with `carry_tool`, one hammer
tick per 2 s, plank `the lantern stands · @kai`, plate pinned 20 s and forever in the rotation, and it glows whenever
Kai is here. `build a castle`: paper + `@kai's wish is pinned · a castle · 1 pinned`; the plate rotation carries
`wished: a castle · @kai`; nothing promises a castle. **Hours:** the monument plate names the gap; an expedition card
walks everyone to the Ford and a stone lands in their name; the pile beside the cairn visibly grows. **Days:** they
come back to `@kai is back · the Camp rose · your tent is a hut · 4 walked in`; their flower is a drift; the camp
plate says `2 days here`. **Weeks:** their name is on the Camp's founders plaque forever; the Village opened `sing` and
the far bank; if enough people asked, the castle rose as a Century slot with `wished by @kai · raised by @sami @jo`.

**A regular:** stacks to the cap (the plank counts down to the next age), votes, plants, visits; hauling day doubles
the pace; the camp ladder climbs by `days_seen` (tent day 2, hut day 4, chimney day 8), gear by minutes, trees by real
days; every return is a diff line; an age turns while they watch (the 90 s build, everyone hauling) or turned while
they were away and the return line says so; nothing they earned is ever taken back.

---

## 2. The wish pipeline: any message can shape the world

### 2.1 The record: tag site, write site, ledger shape, boot replay

**Tag site (spine, S1).** `chat_bridge._ingest_one`, the `elif kind == "plain" and key:` branch (L1104-1117), after
`parse_verb` and the hint logic, and the `idea` branch (L1065-1071): set `m["wish"] = True` and `m["head"] = <word>`
when the record is not `history`, not `dropped`, and either (a) it is an `!idea`, or (b) `text_clean` has >= 3 tokens
and its first non-stop token (or the token after `can we / could we / let's / please`) is in `WISH_HEADS = ("build",
"make", "add", "put", "dig", "cut", "climb", "zoom", "raise", "give", "want", "need", "more", "less", "bigger",
"change", "turn", "wish", "should")`, or (c) it has <= 3 tokens and one of them is a recipe noun (`registry.RECIPE_WORDS`
keys, e.g. `a lantern`, `trees please`). The bridge never classifies beyond the tag (the noun tables live in the
hot-reloadable registry); it also sets `raw["dropped"] = True` in place on the raw record for blocklist / hidden drops
(L1021-1035) so the scene skips the hop (§3.4). Blocklisted, hidden and mod records never reach L1104, so a wish never
carries a bad name. The `!idea` ack at L1071 is REMOVED: the panel's `pinned` line (§2.4) is the ack, and it fires only
after the record exists.

**Write site (spine, S1).** `RoundEngine._apply_chat` (L1254-1306), a new branch before the idea branch:
`if kind in ("plain", "idea", "theme", "ask") and not m.get("history") and not m.get("dropped"):
self._append_jsonl(os.path.join(run_dir, "wishes.jsonl"), row)` (helper L498-506, one syscall). The idea branch and
its board caps (L1277-1278, `IDEAS_KEEP`) are untouched: caps stay on the BOARD, the LEDGER takes every id. Not
`state.json` (§0.2 row 1).

**Ledger row (`$RUN_DIR/wishes.jsonl`, append-only, one process, one thread: `render_frame` runs `engine.tick` then
`scene.frame` sequentially):**

```
{"id": "32b9a2d3-…",              # the chat id: the dedupe key, matches chat.jsonl
 "ts": "2026-09-26T05:51:12Z", "key": "atleastonce", "by": "atleastonce", "n": 1,
 "kind": "plain",                  # plain | idea | theme | ask
 "text": "Build a castle in the field there",   # text_clean, CAP_PLAIN 120; for an idea the arg (CAP_IDEA 60)
 "verb": null, "hint": "camp",     # parse_verb result / hint_for result if any
 "wish": true, "head": "build",    # the tag (b) / (a) / (c); false for a plain sentence with no head
 "first_ever": false, "session": "2026-09-24T11:22:08.014Z", "src": "live"}   # src replay for boot-derived rows
```

**Boot replay (`recompute_wishes`, W3, `state.py` inside the `recompute_from_chat` loop L925-955 with a second cursor
`cursor.wishes_offset`).** Load the id set from `wishes.jsonl` (+ the archive manifest, §7.4); walk `chat.jsonl` from
`cursor.wishes_offset`; for every record that is not a vote (`VOTE_RE`), a mod command (`MOD_CMDS`), an ops token
(`TOKENS`) or a webhook `type != message`, append a row with `src: "replay"` if its id is missing; advance the offset to
the last full line; print `wishes: +N replay rows, M already present`. Idempotent (a second run adds 0). After the first
run on the live copy the ledger holds every one of the 97 messages that qualifies, including the 4 lost `!idea` texts,
each `class: pending` for the probe. The ledger is thereby re-derivable from `chat.jsonl` alone.

### 2.2 Classification: keyword first and in-process, batched model off-path

**Where.** `stream/world/registry.py` (NEW, hot-reload, DATA + pure functions): `RECIPE_WORDS`, `PROJECT_WORDS`,
`MENU_WORDS`, `MECHANIC_WORDS`, `REFUSE_WORDS`, `SILENT_WORDS`, `SYNONYMS`, `RECIPES`, `CAPS`, `REFUSE_COPY`,
`AGE_PROJECTS`, `classify(text, verb, hint) -> Wish(class, noun, merge_key, recipe, param, value)`,
`merge_key(text) -> str`. The SCENE calls `registry.classify` in `_ingest` (L669-700) for every `m["wish"]` record in
`ctx.chat`, in the same frame the record clears the hold (a dict lookup; the cost is microseconds). Output classes and
what each does:

| class | matches (lower-cased stems; `SYNONYMS` folds plurals and 60 aliases) | same-frame effect | later |
|---|---|---|---|
| `recipe:<slug>` | `lantern lamp lamppost` -> lantern · `banner flag pennant` -> banner · `garden veg vegetables herbs bed` -> garden · `flower flowers meadow bloom blossom` -> flowerbed (only when no `plant` verb parsed) · `tree trees orchard forest wood grove` -> trees · `stones circle ring henge rocks` -> stone_ring · `bench seat chairs` -> bench_stones | paper pinned; plank `@kai's wish is pinned · a lantern · 3 pinned` | placed by the scene within 90 s if caps allow (§2.3 tier 1) |
| `project:<slug>` | `castle keep tower fort fortress wall walls` -> keep (Town) · `bridge` -> bridge (Village) · `well` -> well (Steading) · `hall tavern inn pub longhouse market` -> hall (Town) · `plaza square` -> plaza (Village) · `harbour harbor dock port boat ship` -> harbour (Century) | paper pinned; plank `@kai's wish is pinned · a castle · 1 pinned` | joins `AGE_PROJECTS` ask count (§2.3 tier 3) |
| `menu:<param>:<value>` | `rain fog wind clear storm sunny` -> weather · `music techno beat song tune drum bass` -> audio_pattern · `bonfire feast party` -> bonfire | paper pinned; plank `@kai's wish is pinned · fog · 2 pinned` | biases `draw_options` next round; card title `fog · 3 ask` (§2.3 tier 2) |
| `mechanic` | `dig hole mine tunnel gems cut chop axe lumber fish farm` and any `!idea` that matched nothing above | paper pinned; plank as above with noun `an idea` | promoted to `ideas[]` for the orchestrator (§2.3 tier 2) |
| `have_it` | `hut tent house home` (a camp exists) · `road path roads` | plank `@kai · your tent grows as you stay · 2 days here` / `@kai · paths wear where you walk · try: go river`; no paper | none: answered from records |
| `refuse:animate` | `dog cat bird fish(noun) cow sheep horse wolf dragon pet(noun) animal chicken duck` | plank `@kai · no dogs here · try: a lantern · a banner · trees` | ledger only |
| `refuse:destructive` | `kill destroy burn delete remove tear demolish nuke` | plank `@kai · nothing here comes down · try: a lantern · a garden` | ledger only |
| `silent` | `outside` (`repo commit code github bot ai prompt claude stream camera mic overlay hud screen zoom`) · `clock` (`night dark day morning sunset time`) · `theme` (`colour color theme` + a preset: the existing `try: !theme kick` hint already fires) · `chat` (no head, no noun, greetings, goodbyes, laughs, `good night`) | nothing but the bubble (the person's own words) | ledger only; the probe clusters them (`zoom out` x2 becomes a probe proposal) |
| `unknown` | a head (§2.1 b) with a noun no table knows | paper pinned; plank `@kai's wish is pinned · 4 pinned` (no noun) | the probe clusters and proposes; a later `wish_class` row may re-class it |

Order of precedence when several match: `refuse:*` > `have_it` > `recipe` > `project` > `menu` > `mechanic` >
`silent` > `unknown`. A verb-parsed message never reaches `classify` (the verb ran). On the live transcript the table
classes 41 plain lines as: recipe 0, project 2 (`Build a castle in the field there`, `Build a hut here` -> have_it),
menu 3 (`techno beat`, `theme kick` x2 -> theme/silent), mechanic 12 (`dig` x8, `cut some trees`, `build something` x2,
`dig a hole`), silent 20, unknown 3; the 10 ideas: mechanic 7, menu 1 (`turn this to night` -> clock: silent), silent 2
(`zoom out`, `improve the art style`: outside). The honest number a stranger should hear: about one plain line in eight
pins a paper with a noun the world can act on today; the rest pin as asks the probe reads, or stay a bubble.

**Model (off-path, `probe.py --model`, v1.1, off by default).** Pending `unknown` and `mechanic` rows are batched every
10 s or 25 rows into ONE call, JSON in / JSON out `{id, class, noun, merge_key, recipe?, reason}` with `class` in the
closed enum above and `recipe` validated against `RECIPES` slugs or a parts list the validator accepts (§2.3 tier 3);
anything off-enum becomes `silent`; the model never sees a path, never emits code, never emits a shell string; rows
land in `wish_class.jsonl` (§6.2) which the scene tails and applies (a re-class from `unknown` to `recipe:lantern` pins
the noun late; a re-class to `silent` un-pins the paper without a plank line). Budget `WISH_USD_PER_HOUR 3.0` printed
by the daemon from its own token counts at the price sheet in effect when enabled (checked against the gateway before
the flag is ever turned on); above it, keyword-only. The keyword pass fulfils every recipe without a model.

### 2.3 The tiers

**Tier 0 (exists, same frame, no model):** hop at `show_t`, bubble with the person's own words, the verb machine, the
hint, the vote walk, and NEW the paper on the post (§2.4). Deterministic in the compositor process.

**Tier 1, kit recipes (W6).** `registry.RECIPES` is DATA over the closed kit; a recipe is a list of parts, each `fn`
from `honesty.FN_ALLOWLIST = {buildings.garden, buildings.banner, buildings.lantern, props.tree(age 0-2),
props.bush, props.flowers, props.stone, props.cairn(n 1-5)}` with argument ranges; `creatures.*`, `buildings.hut`,
`buildings.well`, `buildings.fence_*`, `props.beacon`, `props.campfire`, `props.waystone` are NOT in the allowlist
(nothing in a recipe is a figure, a home, a fence, a keeper light, a fire or a vote stone). v1 recipes:

| slug | parts (fn, args, dx, dy in cells) | footprint | caster_h | lit_rule | site |
|---|---|---|---|---|---|
| lantern | `buildings.lantern` lit by rule | 1x1 | 3 | `owner_here` | 6 cells from the owner's camp door, ring search |
| banner | `buildings.banner` phase = `nature.wind.atlas_phase(now)` (<= 1 Hz), colour owner | 1x1 | 3 | never | 5 cells from the camp |
| garden | `buildings.garden` colour owner | 1x1 | 1 | never | 6 cells from the camp; never a fence |
| flowerbed | 5 x `props.flowers` on a short curve, one colour (owner hue variant) | 2x1 | 0 | never | 6 cells from the camp |
| trees | 3 x `props.tree(age 1)` | 3x2 | 2+r | never | 10-16 cells from the camp, never on a trail |
| stone_ring | 8 x `props.stone` on a 4-cell radius | 3x3 | 1 | never | Moot ring 18-26 cells out, or by the camp |
| bench_stones | 2 x `props.stone` variant 2 side by side | 2x1 | 1 | never | 5 cells from the camp facing the Moot |

Placement is the scene's (`registry.place(recipe, owner, land, terrain) -> (x, y) | None`): the owner's camp door + a
ring search over `terrain.nearest_passable` (L634) with `land.mark_allowed` rules (L361-380: never water, a trail, the
Moot green `MOOT_GREEN_R 16`, within `MARK_GAP 4` of someone else's mark) plus `PLACED_GAP 6` against other placed
items and `CAMP_GAP 12` against other camps. Pacing: one raise per `PLACE_EVERY_S 90`; a FIFO by first ask. Caps
(`registry.CAPS`, §0.2 row 17). The scene writes ONE `placed[]` row (§6.1) with `status: "rising"`, emits `placed`
(x, y, owner, askers, recipe), then `placed_step` at <= 1 Hz for `RAISE_S 20` (the `Keepers.reveal_rows` mask finally
gets its consumer in `steading._sprites` L1467-1552: the finished composite is blitted bottom-up), then `placed_ship`
-> `status: "stands"`, `land.bump_bake("placed")`, forced save (`FORCE_SAVE_EVENTS` L95 gains `placed`, `placed_ship`).
If the owner is here their settler walks to the site with `carry_tool` (`behaviour.fetch` kind `tool`) and does `joy`
1 s at the ship; with nobody here the object rises at the same pace, honestly, because it is a record. Static parts
join the bake (`_marks_build` L971-1003 adds `marks["structures"]`; `bake._objects` L361-387 y-sorts them; `paint_props`
L402-434 blits; `casters_for_marks` L206-224 writes `caster_h`); the lit lantern is a live sprite + `props.glow(46,
(255,186,96), 0.42)` in `_glow_sources` (L1407-1434) gated on `is_present(owner)`; banners are live sprites keyed on
the wind phase and fall back to the baked frame under degrade >= 3; live registry sprites cap at 24 in view.

**Tier 2, mechanics and menu (S1 + W6).** `menu:*` wishes never touch `ideas[]`: `RoundEngine.draw_options` (L637-668)
asks `scene.menu_wishes()` (a dict `(param, value) -> len(distinct askers in the open window)`) and draws the top-asked
card first (ties to `MENU` order; the stranger gate `STRANGER_MIN_CHATTERS 3` L162 still hides audio cards), with the
title `fog · 3 ask` (rounds composes titles; the board check compares drawn titles to `board_title`, so the ` · N ask`
suffix is part of the option title). `mechanic` wishes and every `!idea` are promoted: the scene queues
`{"text": noun-or-idea-text, "by": display_name, "plus_by": [...], "merge_key", "wish_ids"}` in
`scene.take_promotions()`; `RoundEngine.tick` (L1409) drains it once per frame and appends `ideas[]` rows exactly as
`_apply_chat` L1279-1283 does (`next_idea_id` L335, `class: "pending"`, `status: "open"`, `source: "wish"`; `OWNED_PATHS
["rounds"]` gains `ideas[].source`), deduped by `merge_key` (a repeat by another person is `plus += 1`), still under the
board caps (an over-cap promotion waits in the scene's queue, never lost: the ledger has it). From there `duty.py
classify / macro-start / macro-done` (L191-317) and the keeper gate (§5.2) are the build path, exactly as for `!idea`
today; the ballot card `idea.<id>` and the `raised · vX` plate are the existing surfaces. An idea row's `text` is the
catalogue noun or the `!idea` arg (already `CAP_IDEA 60`, blocklist-filtered `by`); board titles pass `banned_copy_hits`
in the self-test and `validate_copy` at write time (§5.1).

**Tier 3, projects (W4 + later W9).** `registry.AGE_PROJECTS = {"well": 2, "plaza": 3, "bridge": 3, "hall": 4, "keep":
4, "harbour": 5}` maps project slugs onto AGES §2.3 contents. A project wish only accumulates askers: the monument's
forward plate (`_mark_list` L2668-2683 per AGES) gains ONE clause for the most-asked project with >= 2 distinct askers:
`the Village · 2 more people · 14 more stones · a bridge · 12 ask`. When the age turns, the age build (AGES §2.5)
raises the object and `age_history[-1].raised_by` is the union of everyone on the land at the turn AND the project's
askers, top stackers first; the plaque reads `the bridge · wished by @kai @jo · raised by @sami @atleastonce · 3 Oct`.
A project with no age slot (`harbour`) is a Century wish slot (W9): slots per age 0 / 0 / 1 / 2 / 3 / 3+k are filled
at gate time from the highest-ranked project clusters whose recipe (a parts list over the same allowlist, drafted by
the probe as DATA in `wish_class.jsonl`, validated by `honesty.validate_registry`) exists and fits a site from a
generic `SITES` table extending `keepers.RAISING_SITES` (L90-94) with ring positions; the slot structure receives pile
stones in the haul step; **a slot with no valid recipe is skipped and the age still turns.** The plate never says a
structure is coming; the only forward form is the ask count.

### 2.4 The post, the plate, the plank (the instant feedback)

- **The post** is one prop `props.post(papers: int, sun)` (NEW ART, 1 function: a wooden post with 1..5 cream paper
  squares; `kit_image` gains it; ART.md §10 documents it; child restart with S1) at `MOOT_LAYOUT["post"] = (34, 10)`,
  drawn as a live sprite (`_sprites` kind `post`) with `papers = min(5, len(world.wish_post))`, reserved in the placer
  (`_Placer` L890), culled with the cairn. Papers are PEOPLE with an open paper, so 100 wishes draw as one sprite.
- **`world.wish_post[]`** (schema 3, scene-only writer): one row per key `{key, wish_id, ts, class, noun, merge_key}`;
  the newest replaces the person's older paper (the older ledger row stays open and still counts toward its cluster);
  provenance: every `key` a real pip. A `silent` re-class removes the row.
- **Plank** (`_consume_events`, new `wish` branch): `@kai's wish is pinned · a castle · 4 pinned` (`PRIO_VERB`, `tie`
  with record-writing acts, 5 s); the noun is `registry.NOUNS[merge_key]` (`a castle`, `a lantern`, `fog`, `an idea`),
  never the sentence; `4 pinned = len(wish_post)`. A repeat of an open cluster by another person: `+1 for a castle`.
  At 100: only a NEW cluster or a placed thing gets a line (§3).
- **Plate** (the ONE-plate rotation, anchored at the post): `wished: a castle · @kai +3` for the top three clusters by
  distinct askers (`+3 = len(askers) - 1`), rotating; a cluster with no noun (`unknown`): `wished · @kai · today`; pins
  10 s after every `wish` event (like the cairn pin, `CAIRN_PIN_S` L183) while <= 10 people are here.
- **Refusals** (`registry.REFUSE_COPY`, §2.2): `PRIO_VERB`, 5 s, only when the person is here, at most one per person
  per 30 s (`REFUSE_COOLDOWN_S`), never echoing their words; the `try:` tail rotates three of the six recipe nouns.
- **Audio** (`audio.py` L1333-1421, spine, S1): `wish` -> the existing `pickup` sting (a paper pin); `placed` ->
  the raising path (a soft hammer tick every second `placed_step`); `placed_ship` -> raising chime + rumble;
  `return` -> the `wake` branch (L1361) renamed, one bell, three at `away_s >= 7 d`; `age` -> bells west to east;
  `day_turn`, refusals, re-classes -> nothing.

### 2.5 Dedupe, merge, permanent credit

`merge_key`: the classifier slug (`lantern`, `keep`, `weather:fog`, `mechanic:dig`); for `unknown` rows the first
content token after `STOP_WORDS` (L159) and the head, singularised (`SYNONYMS` covers plurals and 60 aliases: `lamp ->
lantern`, `flag -> banner`, `beat|techno|song -> music`, `rocks -> stones`). A cluster = the set of ledger rows with one
`merge_key` and status not `placed`; recipes cluster within 24 h, projects for the life of the age, menu within the
current round window. A person joins a cluster once (their second `castle` bumps nothing; the dossier logs it).
`askers = distinct keys`, ordered by first ask. When a recipe cluster is placed, the `placed[]` row carries every asker
(`askers[]`, `wish_ids[]`); the plaque plate `lantern · @kai @jo @sami · since 3 Oct` names the first three and
`and N more` beyond; `!stats` counts `1 stands` from `len(placed rows where owner == key or key in askers)`; the
return line says `your lantern stands`. A wish for something the person already has is answered from records
(`have_it`). Credit is forever: `placed[]` rows are never deleted; `status: "hidden"` (banish) hides the sprite and
masks the name; `!unbanish` restores.

### 2.6 The per-chatter dossier and the worker model (the owner's "an agent for jo")

**Dossier** `$RUN_DIR/chatters/<key>.json`, written atomically by `probe.py` ONLY (never read by the scene; a derived
index over the ledger, `wishes.out.jsonl`, `wish_class.jsonl` and `world.json pips`): `{key, display_name, n,
first_seen, last_seen, sessions[], days_seen[], counts {plain, verb, vote, idea, wish}, messages: [{id, ts, kind,
text}] (last 200), wishes: [{id, merge_key, class, status}], placed: ["p-0031"], asked_with: {"jo": 2}, marks:
{flower, tree, reed, stone}, camp_tier, gear_tier, notes: []}`. It is what the THINK step reads (`kai asked for a
lantern twice, has a hut, stacked 9 stones`) and it is untrusted data (the prompt says so). A dossier never produces a
plaque string: plaques are templates over catalogue nouns and `name_for` names.

**Per-chatter agents: answered with numbers.** Intake is not the queue that would be slow: `ChatBridge.ingest`
(L951-978) costs ~0.2 ms of regex and dict work per record; 100 chatters at 2 lines/min are 3.3 records/s, about
0.02 ms per 33 ms frame. What IS slow is generation, and it does not parallelise per person: `world.json` has one
writer, the scene raises one thing per 90 s (40 an hour) and runs one age build at a time, so 100 resident agents
would queue behind one scene; they cannot merge (23 asks for a bridge become 23 fights over one site, where one cluster
gives one plaque with 23 names); each idles 99 % of the time while holding a ~4 k-token context (100 of them cost about
100x a batched classifier at any price sheet); and the loudest chatter would get the most builds. **"Jo's agent" is
therefore Jo's ROW plus Jo's SHARD:** her pip row (~1.5 KB), her per-user cooldowns and caps in the bridge, her open
paper on the post, her dossier file, and fair scheduling (first placed item never refused; bubble rotation by
oldest-last-bubbled; the probe's fairness term for askers never granted). Generation shards by CLUSTER, never by
person: the keyword classifier is in-process and instant; the probe classifies the long tail in batches; if builds must
parallelise, at most 3 builder agents in flight sharded by `crc32(merge_key) % 3`, at most 1 on the world batch
(journal 034). Jo loses nothing a resident process could give her within the 3 s hold, and the frame gets nothing it
could not draw.

---

## 3. The feedback ladder: every message is seen to land

**Contract at every density:** every accepted record produces a BODY beat (hop within `HOLD_S` + one frame, speak
pluck) unconditionally (the hop is a frame flag, never on the degrade ladder), a WORDS beat (bubble or a 1 s label
brighten) under a fair rotation, a VOICE beat (plank) only when the person outranks the world, and a RECORD beat (a
paper, a stone, a mark, a camp, a placed thing) that outlives the visit, at least once per session. Density is bounded
by COUNTS, asserted in self-tests, with `DEGRADE_MS` (`steading.py` L99) as the frame-time backstop.

### 3.1 Density rules (W7)

| surface | rule |
|---|---|
| bubbles (`panels/world.py` L2032-2095) | `BUBBLE_BUDGET 6` alive in view; `BUBBLE_S 8` at <= 6 speakers/min, 5 s above 30/min; candidates beyond the budget are picked by `last_bubbled_t` oldest first (a never-bubbled person always beats one just bubbled); the rest get a 1 s label brighten (`_label_override` L1990); the shared bottom line (L2072-2093) becomes a FIFO queue, one speaker per 2.5 s, never last-wins; a bubble unshown after 8 s is dropped (the hop already happened; the words are learned) |
| labels (L1969-2030) | on-speak above `DENSITY_FALLBACK 40` here settlers; away settlers lose labels above 24 in view (AGES §1.5) |
| plank (ONE row) | priority table: first-ever and return lines `PRIO_YOU` > record-writing acts (stone, plant, camp, fire, gift, wish pinned, placed) `PRIO_VERB` with `tie` > age / gap lines `PRIO_EVENT` > movement verbs and refusals `PRIO_VERB` 3 s; grouped forms above 12 acks queued in 10 s: `@kai @jo @mo walked in · 41 have walked here`, `4 stand at A · 2 at B`, `@kai @jo @mo planted`; stone lines deduped to one per 5 s reading the latest count; **no message counts, ever** |
| plates (ONE) | `PLATE_ROTATE_S 5`; pins: monument 10 s after hatch / stone / age; post 10 s after a wish while <= 10 here; placed 20 s at the ship; camp plates rotate while the owner is here or a dwell pins them |
| post | 1..5 papers = `min(5, people with a paper)` |
| camera | `EVENT_MIN_GAP_S 8` between EVENT glides (a beat still fires plank + plate + bell without the glide); `placed` is an EVENT only when <= 2 here or the owner is here, and never within 60 s of the last `placed` EVENT; the 1.5x hatch close-up stays limited to <= 2 here (`HATCH_CLOSE_MAX_AWAKE`); never a cut (`PAN_CAP 60`) |
| wind | base speed = chat rate (exists): a 100-person room is a visible gale |

### 3.2 Per message kind at 1 / 10 / 100 concurrent chatters

| kind | 1 chatter | 10 | 100 |
|---|---|---|---|
| **first-ever message** | tuft lands (`someone new walked in` during the hold), hatch after 3 s with a hop, camera EVENT 1.5x, plank `that's you, @kai`, camp pitched with plate `@kai's camp · 1 day here` pinned 10 s, monument plate pins `the Camp · since 26 Sep · 3 have walked here`, hatch chord | same; the plank line is guaranteed (`PRIO_YOU`); `@kai walked in · 7 have walked here` 5 s; no close-up above 2 here | tuft + hatch + hop always; plank batches `@kai @jo @mo walked in · 41 have walked here` every 5 s; no close-up; camp plate not pinned; the monument count ticks |
| **plain sentence** (no verb, no wish) | hop + pluck, bubble 8 s with the words verbatim, label, camera FOLLOW weight SPOKE 3; a paper is NOT pinned; later the settler mutters one of their own top words | same; bubbles within the budget | hop + pluck always; bubble under the rotation (6 x 5 s = 72 bubbles/min against ~200 msg/min: every speaker is bubbled within ~3 lines) else a 1 s label brighten; words still learned |
| **verb** (go plant camp fire feed pet gift wave sit dance stack) | the body does it within one frame of `show_t`; plank `@kai walks to the river` / `@kai planted a flower`; mark plate pins; camera follows the walker; sting | body + plank if free (record-writing acts outrank movement); refusals (`go where?`, `three flowers a night`) as person lines | the body moving IS the ack; plank only for record-writing verbs, grouped (`@kai @jo @mo planted`); refusals dropped when the plank is busy (a still body is the refusal); plates rotate |
| **vote** (A/B/C) | the settler walks to the stone, `0 +1` then `1` under the letter, name under the letter, plank `@kai stands at B · closes in 1:27`, board row lights | same; up to 3 names then `4 standing`; MOOT camera in the last 30 s; plank grouped `4 stand at A · 2 at B` | the count under the letter (a `len()` of bodies) and the crowd ARE the ack; grouped line once per 5 s; the leader band moves |
| **stack** | walk to the Fell, `carry_stone` back, set down with a hop, pile +1 (cairn stone while under 5), plank `stone 17 · 13 more until the Steading`, monument plate pins 10 s, stone click | same; the line is a record-writing act | the pile grows one prop per stone; one plank line per 5 s reading the latest count; the plate pins |
| **wish** (head + noun, or `!idea`) | bubble + hop, a paper goes up on the post, plank `@kai's wish is pinned · a lantern · 1 pinned`, plate `wished: a lantern · @kai`, pickup sting | same; a repeat by another: `+1 for a castle`; plate `wished: a castle · @kai +3` | hop + bubble lottery as plain; the post shows 5 papers; the plate rotates the top three clusters `wished: a castle · @kai +37`; plank only for a NEW cluster or a placed thing; every wish still exists as a ledger row and (if classed) a paper |
| **placed thing rises** (tier 1) | camera EVENT to the site (<= 2 here), the object rises bottom-up over 20 s, the owner's settler walks over with a tool, hammer tick per 2 s, plank `the lantern stands · @kai`, plate pinned 20 s then in rotation forever, chime | EVENT only if the owner is here and >= 60 s since the last raise EVENT; otherwise plate pin + plank | plate pin + plank `the lantern stands · @kai @jo +19`; the crowd gathering at the site (AGES gathering rule) is the mass feedback |
| **return** (> 20 min away) | hop, brighten, face the camera, camera glides to the settler, plank `@kai is back · the Camp rose · your tent is a hut` (`PRIO_YOU`), one bell (three after 7+ days, everyone looks), monument plate pins 10 s, one own-word mutter | same | `@kai @jo are back` batched above 2 returns in 5 s, then each personal diff line 4 s FIFO (returns are rarer than messages and are the highest-value beat) |
| **refused wish** (animate / destructive) | plank `@kai · no dogs here · try: a lantern · a banner · trees` 5 s | same, one per person per 30 s | only if the plank is free; the bubble still shows their words |
| **silent classes** (outside / clock / theme / chat) | bubble only (the `try: !theme kick` hint fires for theme words) | same | same |
| **blocked** (blocklist / hidden / three strikes) | nothing drawn, nothing named, NO hop (`raw["dropped"]`, §2.1); the record and its vote / verb / idea / wish are dropped before `_touch_builder`; a strike is counted; three strikes hide the settler for the session (the ONE lying pose, moderation not presence) | same | same |
| **rate-limited** (`RATE_S 2`) | hop kept, bubble skipped | same | same |
| **unparsed with one of our words** | `try: go river` at most once per 10 s per person (`HINT_COOLDOWN_S`) | same | may be lost behind acks; the bubble remains |

### 3.3 The camera's role

FOLLOW / CLOSE at 1-2 here keep the camera on the person who typed (weights SPOKE 3 / WALK 2 / SEED 2 / IDLE 1 for
HERE settlers); EVENT beats: `hatch`, `return`, `placed` (rules above), `age`, `camp`, `cairn_named`; MOOT in the last
30 s of a round with voters; ROAM when nobody is here (AGES §1.4); the wish post and the monument sit inside the 1.5x
Moot dwell frame so Kick's 320x180 tile shows the sign, the post's papers and the plate. `EVENT_TYPES` (`camera.py` L70)
gains `return`, `placed`, `placed_ship`, `age`, `age_built`; `EVENT_MIN_GAP_S 8` and `PLACED_EVENT_GAP_S 60` are new
constants beside `EVENT_HOLD_S` (L67).

### 3.4 Blocked lines produce nothing

Today a blocklisted message still hops the body (the raw record reaches `steading._ingest` before moderation). S1 sets
`raw["dropped"] = True` in place at `chat_bridge.py` L1026-1035 (blocklist) and L1021 (hidden); W7 makes
`steading._ingest` (L616-746) skip `seed_drop` / `message` for `raw.get("dropped")`. `ingest` runs before
`scene.frame` in `render_frame` (compositor L740-752), so the flag is set when the scene reads the record.

---

## 4. The probe agent: a loop that questions the world and feeds the orchestrator

### 4.1 Shape

One Python process `agents/probe.py` (stdlib only; launched like `duty.py heartbeat` with `env -u` for every stream
secret; pid `$RUN_DIR/pids/probe.pid`; log `$RUN_DIR/logs/probe.out`; in `scripts/stop.sh` L45-52, `scripts/status.sh`
L70, `monitor/report.py process_health` L428) does the deterministic half: OBSERVE (readers), CLASSIFY (long-tail
clustering, dossiers), the BOARD (bookkeeping, anti-thrash), INGEST (validate a THINK result). The THINK half is a
model reading `agents/prompts/probe.md` in one of two runtimes (§4.6). The probe **never writes** `world.json`,
`chat.jsonl`, `state.json` beyond its heartbeat, or any file outside `$RUN_DIR/probe/`, `$RUN_DIR/chatters/`,
`$RUN_DIR/wish_class.jsonl`, `docs/journal.md`; it never edits chat_bridge / rounds / honesty / moderation / pipeline
code; it never executes wish text; it never speaks on screen.

### 4.2 Cadence and triggers

- OBSERVE every 10 min (Python, `probe.py observe --json > $RUN_DIR/probe/observe.json`, ~1 s, read-only).
- THINK every 20 min, or every 5 min while `chat_stats.msgs_per_min_5m > 50`, or on a trigger: >= 5 new wish-tagged
  ledger rows, a first-time chatter, a `return` with `away_s >= 7 d`, `viewer_count >= 1` with chat silence > 30 min,
  `honesty_violations > 0`, a finished build (`macro.last_reload.ts` moved) or a `placed_ship`.
- `pause_bot.json` present (`ops_chat_switch.py` L46, L413-414): OBSERVE only, `paused: true` in the report, no board
  writes, no journal line.
- `df` < 20 GB: only `kind: "fix"` proposals (never a build).
- A journal paragraph `Tick HH:MM (probe): ...` is appended after entry 037 (`docs/journal.md` L1137+) ONLY when a
  proposal is made, a status changed (taken / built / rejected / expired) or health is red; every tick writes the JSON
  report regardless.

### 4.3 Inputs (exact files and fields; every reader is a function in `probe.py observe`)

| file | fields |
|---|---|
| `chat.jsonl` (both shapes via `monitor/chatter_log.normalise_chat` L310-339, `classify` L124-135) | messages and unique chatters per window; first-time chatters (first id per lower-cased user); second message within 10 min; unparsed heads (`dig build cut climb zoom`); seconds since the last message |
| `wishes.jsonl`, `wishes.out.jsonl`, `wish_class.jsonl` (§6.2) | open rows by class and `merge_key`; distinct askers per cluster; askers with zero placed / raised; pin -> place latency; refusal counts by class; re-class counts |
| `acks.jsonl` (§6.2) | `ack_ms` p50 / p95 = `ack_t - t` per kind (the metric the code map lists as missing) |
| `plank_log.jsonl` (§6.2) | what the plank said at the second a stranger typed again |
| `metrics.jsonl` (`kick_api.parse_channel` L239-262) | viewer_count now / avg / peak, is_live, started_at, arrivals (positive deltas, same started_at, <= 120 s: `chatter_log.py` L424-429), followers delta, our_rank |
| `chat_stats.json` | msgs_last_1m, msgs_per_min_5m, unique_chatters_5m / 15m, connected |
| `chatters.json` regenerated read-only (`chatter_log.py --out - --no-report --json`, L662-666) | summary.second_message_rate_pct, first_kind_counts, median_first_message_stream_offset_s, first_time_chatters_today, arrivals_today |
| `state.json` | ideas[] {id, text, by, ts, plus, class, status, reason, source}; round.number / options / last_result.total_votes; agent.on_duty / heartbeat_ts; macro.active / last_reload; version.shipped / failed; compositor.fps_actual / frame_ms_p95 / dropped_frames / hot_reload |
| `world.json` | hatched_ever, len(stones) and stones by `by`, marks, age / age_built / age_history / age_build, days_on_air, wish_post, placed, milestones_reached, event_log[50]; pips[*].last_seen_ts / minutes_present / own_messages / tier / camp.tier / days_seen / last_told |
| `ships.jsonl`, `activity.jsonl` | ships per window, share with total_votes > 0, agent_pick share, option_id histogram; actors world / ship / agent / deploy / probe |
| `logs/compositor.log` | newest `honesty_violations=... by_rule {...}` line (compositor L1189-1194), `ROLLBACK`, `hot reload FAILED` |
| `relay_status.json`, `pids/*.pid`, `df`, `pause_bot.json`, `probe/probe_board.jsonl` | connected, child_restarts, gaps[-1]; processes alive N / expected; free GB; paused; its own memory |

### 4.4 The eight questions (answered with numbers every THINK; each may yield 0-2 ideas)

1. **Strangers' first minute:** who chatted for the first time since the last tick; the kind of their first line; did a
   second line follow within 10 min; what did the plank and camera show at that second (`plank_log.jsonl`)?
2. **Silence:** viewers >= 1 and no message for > 15 min: what did the idle frame show (ROAM subject, board, sign in
   view) and which idle beat has never been tried?
3. **Unfulfilled wishes:** clusters of open rows older than 30 min by `merge_key`; which has the most DISTINCT askers;
   which askers have never had anything placed or raised; which `unknown` clusters could become a recipe (a parts list
   over the allowlist) or a project?
4. **Stagnation:** which of people / stones / days moved since the last tick; `Land.age_forward()` gap; stones per hour;
   did anyone try `stack` and how many refusals (`acks.jsonl` kind stack, ok false)?
5. **Reaction:** which world events (event_log, ships, placed) were followed by a message within 60 s; which option_ids
   drew votes; which plank line preceded a second message?
6. **What a returner would notice:** for pips with `last_seen_ts > 24 h`, what changed since `last_told` and is the
   return line non-empty and true?
7. **Health:** honesty 0, fps p95 < 25 ms, relay gaps, disk >= 20 GB, pause flag, duplicate heartbeat processes,
   rollbacks. Anything red: the ONLY idea this tick is the fix (`kind: "fix"`, tier 0).
8. **Last build:** did the newest ship / raising / placed thing draw a reaction (messages or arrivals in the 10 min
   after vs the 10 min before)?

### 4.5 Scoring, board, anti-thrash

`score = 2*reach + 2*askers + recency + fairness - 1.5*tier` with reach in {0 nobody, 1 one regular, 2 every chatter, 3
every stranger's first minute}, `askers = min(3, distinct askers)`, recency 1 if any evidence < 1 h, fairness 1 if any
asker has nothing placed, tier 0-3 (0 copy / constant in a hot-reload file < 15 min; 1 one-file world mechanic < 1 h;
2 multi-file hot-reload feature 1-3 h; 3 spine / art / schema: `deploy.sh` or a migrate-copy, owner told first, at
most one per day). **Rule compliance is a GATE, not a score:** an idea that adds an NPC, an animal, decay, hunger, a
HUD / AI line, a non-`len()` number, a fence a chatter can ask for, a promise of what will rise, or touches repo /
pipeline / auth / moderation / honesty code is written `closed` with the reason and never ranked. Ties break to the
smaller tier. Top 5 -> `latest.json`.

**Board:** `$RUN_DIR/probe/probe_board.jsonl` (append-only, one row per idea event) and `$RUN_DIR/probe/latest.json`:

```
{"ts": "...", "tick": 41, "paused": false,
 "health": {"honesty": 0, "fps_p95": 12.8, "relay_gaps": 7, "disk_gb": 36, "processes": "10/10"},
 "funnel": {"arrivals_24h": 196, "first_time_24h": 1, "second_rate_pct": 66.7, "viewers_avg": 1.6},
 "keys": {"people": 3, "stones": 16, "days": 3, "age": 1, "forward": [["people", 2], ["stones", 14], ["days", 2]]},
 "wishes": {"open": 12, "pinned": 4, "placed_24h": 2, "clusters": [{"merge_key": "keep", "noun": "a castle", "askers": ["atleastonce"], "class": "project", "age": 4}]},
 "answers": {"q1": "...", "q8": "..."},
 "ideas": [{"id": "p-0001", "kind": "feature|copy|fix", "title": "a stone ring recipe at the Moot ring", "tier": 1,
            "hypothesis": "3 askers said stones/circle; a placed thing in minute three keeps a stranger 10 minutes",
            "evidence": ["wishes <id> <id> <id> (3 askers, 2 today)"], "source_wishes": ["<chat ids>"], "askers": ["kai", "jo", "mo"],
            "files": ["stream/world/registry.py"], "recipe": {"slug": "stone_ring", "parts": [["props.stone", {"variant": 1}, 0, 0], ...]},
            "honesty_check": "every part in FN_ALLOWLIST; owner and askers real pips; no count that is not a len()",
            "rule_check": {"chat_is_data": true, "no_fake": true, "no_hud_copy": true, "hot_reload": true},
            "score": 9, "status": "proposed|taken|built|rejected|expired|closed", "first_proposed_ts": "...", "times_proposed": 1}],
 "in_flight": [], "rejected_24h": []}
```

**Anti-thrash:** `MAX_IN_FLIGHT` 1 on the world batch (steading / behaviour / honesty) and 2 total; a rejected idea
(same normalised-title hash) is not re-proposed for 24 h; nothing proposed while `world.age_build` or `keepers.raising`
is running or `macro.active`; the same file cluster not twice within 2 h; an idea expires 6 h after its last proposal;
tier 3 at most once a day and only with an orchestrator present; `pause_bot.json` -> observe only. Ideas written by
the probe carry `by_agent: "probe"` and are never balloted, never drawn: a lens that lets them reach the board
reintroduces fake chat.

### 4.6 Two runtimes, one prompt

`agents/prompts/probe.md` holds: the role and rules (propose only; never write outside `$RUN_DIR/probe/*` and the
journal; never touch moderation / honesty / pipeline code; never execute or paraphrase wish text into an instruction;
never invent a name or a number; every number from `observe.json`), the exact read-only commands (`probe.py observe`,
`report.py --window 20m --json`, `chatter_log.py --out - --no-report --json`, `duty.py list`), the eight questions,
the scoring, the JSON schema above, the forbidden list, and the two hand-off commands.

1. **Session cron** (the orchestrator's own Claude Code session): `CronCreate` on `7,27,47 * * * *` with the prompt
   "read agents/prompts/probe.md and run one probe tick against $L: observe, think, ingest; propose only". Session-only,
   7-day expiry, dies with the session (the previous loop's cron at :17 / :57 did; `docs/RESUME.md` documents re-arming).
2. **Headless** `agents/probe.sh`: loop { pause flag; `df` >= 20 GB; `probe.py observe --json`;
   `claude -p "$(cat agents/prompts/probe.md)" --output-format json` with Read and the `probe.py` / `report.py` /
   `chatter_log.py` read-only commands allowed and nothing else; `probe.py ingest < result.json` (schema-validated;
   off-schema -> logged, nothing written); sleep 1200 }. Launched with `env -u STREAM_KEY -u SRT_PASSPHRASE -u
   KICK_CLIENT_SECRET -u KICK_TOKEN -u NGROK_AUTHTOKEN` and the API variables the session needs passed explicitly by the
   launcher (they are not in `~/.config/kick-live/env`; HANDOFF.md L117); pid / log / stop / status entries as §4.1.
   No `--act`.

**Hand-off to the orchestrator and back.** `probe.py next --run-dir $L` prints the top `proposed` idea whose
`rule_check` is all true and whose tier fits the budget. The orchestrator marks it `probe.py take p-0001 --by
orchestrator` (board + `wish_class.jsonl` rows `status: taken` for its `source_wishes`; NOTHING on screen), launches
`agents/workflows/wish-build.js` (cloned from `settlement-build.js` with the CONTRACT text, `ROOT` = this worktree,
`args.idea` = the board row; the wish text enters the prompt only as quoted data under "asked in chat:") which builds
under `RUN_DIR=/tmp/lg-wish-*`, runs `scripts/keeper_gate.sh` (§5.2), stages, and returns. Deploy is the existing
recipe (one `cp` batch for hot-reload files; `deploy.sh` for spine / art), owner told first. Results flow back:
`duty.py macro-start / macro-done` -> `rounds._sync_macro` -> `ships.jsonl` macro line -> `keepers._macro_events`
`keeper_carved`; for a recipe idea, the new `RECIPES` entry hot-reloads and the scene places the cluster's item on its
next pacing slot -> `placed_ship` -> `wish_class.jsonl` rows `status: raised`; `probe.py built p-0001 --commit <sha>`;
an activity line actor `probe` (`the stone ring stands · asked by @kai @jo @mo`); one journal paragraph. The next
THINK answers Q8 against it.

---

## 5. Honesty rules and the sandbox boundary

### 5.1 Rule text for OPENWORLD.md §12 (replaces the "Every number is a `len()`", "Camps, plates, plaques" and "Chat is data" bullets; adds five; AGES §4.1 stays with `day 3` -> `3 days`)

> **Every number is a `len()`:** `3 have walked here`, `16 stones`, `3 days`, `2 more people`, `4 pinned`, `12 ask`,
> `4 standing`; no sample string is drawn, no count of messages or viewers is ever a world word.
> **A wish is a record.** Every ordinary message and every `!idea` is one row in the wish ledger the moment it clears the
> hold, re-derivable from `chat.jsonl` alone; the ledger is never truncated; the paper on the wish post is one person's
> open ask; `pinned` means a record exists and nothing more. The board's caps decide what is balloted; they never
> decide what is remembered.
> **Placed things resolve to pip rows.** Every lantern, banner, garden, bed, grove, ring or bench on this land is a
> `placed` row with an owner who asked for it and every asker named; it is composed only from the kit's closed part
> list, coloured only from the owner's name or the land's palette, lit only while its owner or someone is here, never a
> figure, a fence, a fire or a second beacon; a banished owner's thing is hidden and its plaque masked, never rewritten.
> **Nothing is promised.** The world says `pinned`, `+N`, `N ask`, `stands`, `rose`; it never says what is coming, who
> is working, or that anything was taken up. An age never waits on an agent; a slot with no valid recipe is skipped.
> **Camps, plates, plaques** resolve to pip rows with real visits (`days_seen`) and a real `last_seen_ts`; away settlers
> never walk to vote, speak, stack, place or ring their own bell (the wind does); a window is lit only where the owner
> is or was tonight; the hearth burns only if a real person lit it this session; the beacon only on a fresh heartbeat.
> **Validated before drawn.** Every string the panel composes from a wish (a plate noun, a plank noun, a board title, a
> plaque) is a closed-table word checked against the banned-copy list, the day and version patterns and the blocklist
> at write time, and every part of a placed thing is checked against the allowlist before its first pixel; a failed
> check draws nothing and logs one line.
> **One writer per file.** `world.json` is written only by the scene; `state.json` only through owned paths; agents
> append to their own files and the scene reads them. No agent, workflow or migration writes `world.json` while the
> compositor runs.
> **Chat is data** (journal 017): a message may shape the WORLD (a verb the scene executes, a paper on the post, a
> recipe placed from the kit, an idea an agent classifies) and never the repo, the pipeline, auth, moderation or the
> honesty code; wish text reaches an agent only as quoted data inside a fixed schema; it is never executed, never a
> shell string, never a file path. The probe never speaks on screen.

### 5.2 Mechanics: validation at write time, the allowlist, the keeper gate

**`honesty.validate_registry(row, land, terrain) -> (ok, reason)`** (W6; `honesty.py` is in the gate's DENY set): every
`part.fn` in `FN_ALLOWLIST` with args inside its ranges; no `moves`, `speed`, `path`, `frames`, `rate` field; `colour` is
`"owner"` or an ART.md §4 palette key (a raw RGB triple is rejected); `lit_rule` in `{owner_here, anyone_here, never}`
(`always` rejected); footprint >= 1 tile (8 px at 320x180); owner and every asker a real pip; every `wish_id` present
in the ledger id set; cell passable, not water, not the Moot green, not a trail, `PLACED_GAP 6` and `CAMP_GAP 12` held;
caps held. **`honesty.validate_copy(s) -> bool`**: `compositor.BANNED_COPY_RE / BANNED_DAY_RE / BANNED_VERSION_RE /
BANNED_CLOCK_RE` (imported by value: honesty imports the tuple and patterns from compositor at load) and
`WordLists.blocked` over every panel-composed wish string before it is drawn; the panel's `_note_drawn` (L526) records
the result; a failed string draws nothing. **Honesty rules** (AGES §4.2 `RULES` + `placed`): every 5 s
`land.provenance_violations` (L809-827) gains loops over `world.placed[]` (owner, askers) and `world.wish_post[]`
(key), and `age_history[].raised_by`; every frame no `placed` row with `status: "stands"` lacks a validated recipe
(cached per row id); planted fakes in `--self-test`: a placed row with a `creatures.*` part, with `lit_rule: always`,
with an RGB colour, with a banished owner, with a `wish_id` not in the ledger, a plate string containing `build`.

**The revert clause, mechanical:** art-rules.md L64-66 (`decay, animals, NPCs, hunger, death, a fog of war, fences or
carved words`) + OPENWORLD L677-679 (any franchise look). For registry rows the allowlist refuses the kinds; for tier-2
code the gate greps the diff for `asleep|burrowed|hunger|decay|npc|animal|fog|creatures\.` additions; a shipped build
that trips honesty on air is rolled back by the compositor (L943-975) and its placed rows set `hidden`. The art-rules
§2 exception (D1, before any fence ships): *fences and lantern posts are age-built only, round a person's own sown
field, never a verb, never a recipe a chatter can ask for.*

**Sandbox for tier-2 keeper builds (`scripts/keeper_gate.sh`, P2).** ALLOW: `stream/world/*.py` except `honesty.py`,
`state.py` (schema and migration) and `land.py` L809-862 (provenance / purge / restore); `stream/scenes/*.py`;
`stream/panels/*.py`; `stream/world/art/*.py` (child restart). DENY: `stream/compositor.py`, `chat_bridge.py`,
`rounds.py`, `state_store.py`, `layout.py`, `relay.py`, `audio.py`, `stream/moderation/*`, `scripts/*`, `monitor/*`,
`agents/*`, `docs/art-rules.md`, `docs/AGES.md`, `docs/IDLEWORLD.md`, anything under `~/.config`, the run dir. The
gate takes a stage dir, diffs it against `S`, and exits 2 if any changed path is outside ALLOW or inside DENY, if
`honesty.py` or `state_store.py` differ from the worktree's committed copies (sha256), or if the diff adds a revert
word. Gates, all printed, in order: (1) `pause_bot.json` absent; (2) `df -g` avail >= 20; (3) `py_compile` of
`stream/*.py stream/panels/*.py stream/scenes/*.py stream/world/*.py stream/world/art/*.py agents/*.py`; (4) module
self-tests (behaviour, honesty clean + every fake caught, state incl. `--migrate-copy --to 3` when the schema changed,
camera, keepers, chat_bridge, rounds, registry, `MODE=test steading --self-test`), all under `/tmp`; (5)
`cp $L/world.json $L/chat.jsonl $L/builders.json /tmp/lg-stageN-run/ && MODE=test RUN_DIR=/tmp/lg-stageN-run $PY
stream/compositor.py --self-test 300` with `honesty_violations` 0/0, board / copy / tile gates, p95 < 25 ms (a run
WITHOUT chat.jsonl quarantines the pips and fails by design); (6) a static grep of every new panel string against
`BANNED_COPY` plus the compositor's `_hud_checks` over the 300 frames; (7) backups `cp -a $S ~/.local/share/kick-live/
live-snapshot-v3-<tag>` and `cp $L/world.json $L/world.json.bak-pre-<tag>-<ts>`; (8) ONE `cp` batch into `S` (world
batch + scene + panel together; layout.py never partially); (9) watch `compositor.log` for `committed after 30 clean
renders` or `ROLLBACK`; (10) `validate/hls_probe.py --seconds 8`, read `last_frame.png`; (11) delete
`selftest/frame_*.png` and `bake/*.npy`, keep `report/`. Every harness runs under `trap 'rm -f $RUN_DIR/selftest/
frame_*.png $RUN_DIR/bake/*.npy' EXIT`; `/tmp/lg-*` older than 48 h without a `report/` is deleted by the probe's
OBSERVE; never `pkill -f`; `$L/pids/world_batch.lock` (pid) enforces one agent on the world batch. Probation and
rollback are the safety net, not the gate: a wrong-but-running build is caught only by gates 4-6, which is why they
are mandatory and printed.

---

## 6. Data: schema 3 plus the wish files; migration on a copy with printed gates

### 6.1 `world.json` schema 3 (AGES §5 kept; additions in bold)

**World block, new:** `age` (int, earned, monotonic, written at gate time); `age_built` (int <= age); `age_history[]`
rows `{idx, name, ts, at: {people, stones, days}, raised_by: [keys], stones_placed, wished_by: {slug: [keys]}}`;
`days_on_air[]` (ISO local dates); `age_build` (`{idx, t0, step, needed, delivered, sites[]}` or null);
**`wish_post[]`** rows `{key, wish_id, ts, class, noun, merge_key}` (one per key); **`placed[]`** rows `{id: "p-%04d",
ts, recipe, owner, askers: [keys], wish_ids: [chat ids], merge_key, x, y, age_idx, lit_rule, status: rising | stands |
hidden, reveal_t0, plaque: null}`; **`placed_seq`** (int); **`cursor.wishes_offset`** (int, beside `chat_jsonl_offset`).
Unchanged: `stones`, `marks`, `raisings` (`!idea` macro builds only), `milestones_reached`, `land_milestones`,
`wear_b64`, `camera`, `weather`, `hearth`, `bake_ver`, `mark_seq`, `history`.

**Pip, new / changed:** `state` in `seed hatching idle walking voting sitting hauling hidden` (`_adopt` L285-300 maps
`asleep | curled | awake -> idle`, `burrowed -> hidden`); `days_seen[]`; `camp.nights[] -> camp.sessions[]` (copied);
**`camp.tiers[]`** rows `{tier, ts}` (seeded from `{tier: stored, ts: camp.built_ts}`); **`last_told`** `{ts, age,
camp_tier, tree_stage, flower_stage, placed, people, stones}`; `sleep_t`, `nights_streak`, `quiet_s` no longer written
(old keys ignored); `presence()` accrues only while here. `FORCE_SAVE_EVENTS` (L95) drops `sleep`, gains `age`,
`age_built`, `camp_floor`, `wish`, `placed`, `placed_ship`, `day_turn`.

**Derived, never stored:** `wishes_granted(key) = len(placed rows with owner == key or key in askers)`; `pinned =
len(wish_post)`; `askers(merge_key)`; `Land.pile() = len(stones) - 5 - sum(stones_placed)`; camp tier shown =
`camp_tier_for(p, age)`.

### 6.2 Run-dir files (append-only unless stated; writer in brackets)

| file | writer | row |
|---|---|---|
| `wishes.jsonl` (the ledger) | RoundEngine live rows, `recompute_wishes` replay rows (one process, one thread) | §2.1 |
| `wishes.out.jsonl` | the scene | `{"id", "ts", "stage": "classified|pinned|unpinned|queued|placed|raised|refused|promoted", "class", "noun", "merge_key", "item": "p-0031", "reason"}` |
| `wish_class.jsonl` (`wish_class.N.jsonl` when N probes partition by `crc32(key) % N`) | `probe.py` (agent) | `{"ts", "id" | "merge_key", "class", "noun", "recipe"?, "rank", "status": "pending|taken|raised|kept|closed", "reason", "by_agent": "probe"}`; the scene tails it (`JsonlTail`) and applies re-classes, ranks, recipes; a row for an id not in the ledger is ignored |
| `acks.jsonl` | the bridge (`_ack` L1626 / `_plank` L895), buffered, flushed with the 5 s cadence | `{"id", "t", "ack_t", "kind", "ok", "reason"}` (no text); rotated at 5 MB keep 2 |
| `plank_log.jsonl` | the world panel, one line per plank text change | `{"t", "text", "prio", "mode"}`; cap 2000 lines then rotate |
| `chatters/<key>.json` | `probe.py` only, atomic | §2.6 |
| `probe/observe.json`, `probe/latest.json` (overwritten), `probe/probe_board.jsonl` | `probe.py` | §4.5 |
| `chat.manifest.json`, `chat.archive/YYYY-MM-DD.jsonl`, `wishes.archive/...` | `scripts/rotate_chat.py` (ops action, never on air, never during a boot replay) | `{"files": [{"path", "first_ts", "last_ts", "lines", "bytes"}], "live": "chat.jsonl"}` |
| `state.json` | + `OWNED_PATHS["probe"] = ["probe"]` for `{heartbeat_ts, last_report}` only; `OWNED_PATHS["rounds"]` gains `ideas[].source` | |

### 6.3 Migration 2 -> 3 on a copy, with printed gates (W3, rehearsed in Q1)

`state.py --migrate-copy $L/world.json --chat $L/chat.jsonl --to 3 --out /tmp/lg-mig/world.json` (mirrors `migrate_v2
/ migrate_v2_doc / verify_migration / migrate_copy` L1002-1379; `migrate_copy` today returns `skipped` for schema >= 2
and gains `--to`; refuses canonical dirs). `migrate_v3_doc`: the state map; `camp.nights -> camp.sessions` (`nights`
kept one release); `camp.tiers` seeded; `days_seen[]` and `days_on_air[]` from local chat dates; `age =
age_gate(hatched_ever, len(stones), len(days_on_air))`, `age_built 0`, `age_history` rows at reach with `raised_by` =
keys present by first record date; `wish_post []`, `placed []`, `placed_seq 0`, `cursor.wishes_offset 0`; every pip
`last_told = {ts: last_seen_ts, age: 0, camp_tier: stored, tree_stage: current, flower_stage: 0, placed: 0, people:
hatched_ever, stones: len(stones)}` so the first return after deploy says `the Camp rose` (and `your tent is a hut`
where the floor lifted a tier). `verify_v3` prints and asserts: pip count equal; `IDENTITY_FIELDS` byte-identical
(L67); stone / mark / camp counts equal; every `nights` value in `sessions`; every camp tier >= old; `len(days_on_air)
== distinct local dates in chat.jsonl`; `age == age_gate`; `age_built == 0 <= age`; `wish_post == []`, `placed == []`;
every pip has `last_told` with the eight keys; `provenance_violations == []`; `save()` round-trips schema 3 (save writes
the loaded schema, L344, never a silent upgrade). Then the boot replay on the copy prints `wishes: +N replay rows, 0
present` where N == the count of eligible records computed from the chat copy (votes 17, mod / ops tokens and webhook
non-messages excluded; the exact N is computed, never copied from here), and a second run prints `+0`. Then `MODE=test
RUN_DIR=/tmp/lg-mig $PY stream/compositor.py --self-test 300` with the chat copy: honesty 0/0, the Camp build plays
(hearth ring, the pile of 11, Lordoomer's tent floor, `the Camp · since 26 Sep · 3 have walked here`), the post stands
with 0 papers. Live path (owner's decision, later): `WorldState.load` (L259-282) sees schema 2 under code SCHEMA 3,
writes `world.json.bak-pre-idle-<ts>`, migrates in memory, verifies, and REFUSES TO BOOT on a failed verify (the panel
keeps the last good frame; the module rolls back after probation; rehearse the static-watchdog behaviour,
`STATIC_WATCHDOG_FRAMES 30`, on the copy). Rollback for a week: the `.bak` plus the parked schema-2 module.

---

## 7. Performance and scale budget

### 7.1 Intake (one queue, sharded by kind, never by person)

`ChatBridge.ingest` (L951-978) is ~0.2 ms of regex and dict work per record, drained once per frame (compositor
L740-752). 100 chatters at 2 lines/min = 3.3 records/s = ~0.02 ms per frame; a 1000-message raid minute = 17 records/s
= ~0.1 ms per frame. Per record the additions are: the wish tag (a set lookup), one `_append_jsonl` (one `write`
syscall, ~20 us), one `registry.classify` in the scene (dict lookups over <= 20 tokens, ~30 us), one `wish_post` row
replace. Votes are applied at `show_t` by `pump` with per-(key, verb) cooldowns already sharded per person; the world's
`_ingest` per message is `ensure_pip` + `record_message` dict work with saves throttled to 5 s. The 3 s hold is the only
latency. Nothing model-shaped is on the frame path.

### 7.2 Frame path (scene budget < 12-13 ms at 60 settlers; world panel 24 ms; compositor p95 < 25 ms)

| added by this design | cost | rule |
|---|---|---|
| the wish post (one live sprite, 1..5 papers) | one `_zoomed_prop` blit | warmed in `_job_warm_props` (L1138-1159) |
| placed things | baked (off the frame path); repaint of one region ~19 ms in the bake thread per placement; lit lanterns and banners are live sprites | live registry sprites <= 24 in view (`REGISTRY_LIVE_CAP`); banners fall back to the baked frame under degrade >= 3; glows only under degrade < 2 (exists) |
| the reveal (20 s per raise) | one masked blit at <= 1 Hz | never two raises at once |
| return diff | O(1) dict compare on the `return` event | |
| bubbles | capped at 6 | `BUBBLE_BUDGET`; the shared line is one text blit |
| plank grouping | string joins at <= 1 Hz | |
| keyword classing | ~30 us per wish-tagged record | |
| `acks.jsonl` / `plank_log.jsonl` | buffered, flushed with the 5 s cadence | rotated (§6.2) |

Gates (`steading.py --self-test`, every world-batch reload): **C2** unchanged (60 pips, 0.75x, < 19 ms; target avg < 13
with all 60 away and erranding); **C5** 60 settlers 0 here for 5 min (AGES); **D'** boot burst 60 settlers (AGES);
**E'** the 90 s age build with 24 hauls and 2 slot structures: avg < 13 ms, no frame > 24 ms; **C6 (measure first,
W7)** 100 test pips all here, 30 hops/min, 0.75x, 200 placed rows baked: hop events == message count within
`HOLD_S` + one frame, <= 6 bubbles per frame, honesty 0, scene avg / p95 / max RECORDED; the target is p95 < 19 ms and
the doc promise at 100 is written from the measurement, never before it; if the target is missed the degrade rungs
(labels on speak > 20 ms, bubbles single > 24, zoom pinned > 28) engage and the hop + count-tick contract still holds
because hops are a frame flag. Bake-thread gate unchanged (max blocked frame 10 ms); behaviour `tick < 0.5 ms` at 60
walkers; compositor 300-frame p95 < 25 ms with `KL_TEST_PIPS=100`.

### 7.3 Memory and file sizes

Sprites: AGES §6 (errand set 13 frames for away settlers, LRU 48 full sets per octant, <= 96 MB, `idle0` first, paced
worker). `world.json`: a live pip row is 1.0-1.5 KB, so 100 pips ~150 KB, 1000 pips ~1.5 MB serialised every 5 s
(20-40 ms on the frame thread): above 300 pips `save` serialises on the scene `_Worker` (L169) and the frame thread
only swaps the dict (W8); `placed[]` rows ~300 B (500 rows = 150 KB); `wish_post` <= one row per pip; `words` 24
(`WORDS_KEEP` L74), `care_log` <= 20, `history` <= 30 rows, `event_log` 50. Run-dir growth at a sustained 100 msg/min:
`chat.jsonl` ~90 MB/day, `wishes.jsonl` ~50 MB/day (about 60 % of records qualify), `wishes.out.jsonl` ~2 rows per
wish, `acks.jsonl` one row per ack (rotated at 5 MB), `plank_log.jsonl` 2000 lines, dossiers <= 40 KB each, the probe
board grows by ideas only. `scripts/rotate_chat.py` (P4) moves closed days of `chat.jsonl` and `wishes.jsonl` to
`*.archive/YYYY-MM-DD.jsonl` above 256 MB and writes the manifests; rotation is an ops action, never on air, never
during a boot replay.

### 7.4 The two frame-path bombs (W8, before any growth push)

1. `honesty.chat_names` (L101-124) / `_refresh_chat_names` (L167-179) becomes incremental: keep `{offset, partial,
   names}` (the `JsonlTail` pattern), read only the appended bytes on size change, re-read from 0 only on inode change
   or truncation; gate: a 200 MB synthetic `chat.jsonl` under `/tmp` costs < 1 ms per frame after warm-up.
2. `recompute_from_chat` (L873) raises `max_bytes` to 512 MB, reads the manifest's archive files first, then the live
   file, with the cursor as `{file, offset}`; gate: a replay across archive + live equals a replay over one file.
Every reader of `chat.jsonl` (`state.recompute_from_chat`, `honesty.chat_names`, `state_store.JsonlTail`,
`monitor/chatter_log.normalise_chat`) learns the manifest in the same release or they disagree on who chatted.

### 7.5 Degrade ladder additions (on top of AGES §6)

Hops are never on the ladder. > 14 ms: idle picks every other tick; > 16 ms: no new errands outside the camera window;
> 80 settlers: away settlers outside the window tick at 1/4 rate, unanimated; degrade >= 3: banners static, lantern
glows off (degrade >= 2 already); degrade >= 4: plates rotate off except pins; degrade >= 5: bubbles single (the FIFO
line). Feedback density degrades by rung, never to zero: every message still hops and ticks a count somewhere.

---

## 8. Build order

Lanes: **W** = the world batch (`behaviour.py`, `honesty.py`, `state.py`, `land.py`, `steading.py`, `panels/world.py`,
`camera.py`, `bake.py`, `keepers.py`): strictly SERIAL, one agent at a time, in the order below (journal 034). **S** =
the spine + art batch: one agent, disjoint files, PARALLEL with W; its deploy (later, owner's call) is ONE relay-held
child restart. **P** = new files and ops: PARALLEL with everything. **Q** after W7 + S1 + P1-P3. **D** last. Every row
runs under `RUN_DIR=/tmp/lg-*`, `MODE=test`, deletes its frame PNGs and `.npy`, refuses under 20 GB free, and never
touches `L`. W6 needs P1 and S1 on disk in the worktree (not deployed). Hours are agent-hours revised upward from the
proposals (the judges found them 1.5-2x short).

| row | slice | files | h | lane | gates | v1 |
|---|---|---|---|---|---|---|
| 1 | **S1 spine + art batch:** `stack` out of `LATER_VERBS`; hint table (`stone/stones/rock/cairn -> stack`, two-branch `build`, `HINT_EXAMPLES stack`); still-gated verb copy `try: stack stone`; `_target_asleep -> _target_absent`; `m["wish"]` + `m["head"]` tag; `raw["dropped"]`; `!idea` ack removed; `acks.jsonl` buffered writer; `rounds._apply_chat` ledger append; `_expedition_watch` `is_present`; `hauling_until` relief 20 s / 6, `stones_double` deleted, title `hauling day · stones for the Steading`; `draw_options` menu bias + ` · N ask` title; `tick` drains `scene.take_promotions()` into `ideas[]` (`source: wish`); `audio.py` `return` + `wish` + `placed*` mapping; `state_store.OWNED_PATHS` `probe` + `ideas[].source`; `props.post(papers)`; `chatter_log` VERBS sync + `unparsed-head` kind + manifest awareness | `stream/chat_bridge.py`, `stream/rounds.py`, `stream/audio.py`, `stream/state_store.py`, `stream/world/art/props.py`, `monitor/chatter_log.py` | 4 | S | `chat_bridge --self-test`: `stack` / `stack stone` / `stack stones` parse and are not refused; cap 3 -> `three stones a night · the cairn has yours`; `hint_for("build a castle") == "try: stack stone"`, `hint_for("Build a hut here") == "try: camp"`, `hint_for("stones") == "try: stack stone"`; wish tag on plain >= 3 tokens with a head, on `a lantern`, on every `!idea`, never on history / dropped / votes; `raw["dropped"]` set for a blocklisted record; no idea ack; `rounds --self-test`: one ledger row per eligible record, zero for history / dropped / votes / mod; a hauling card sets `bridge.hauling_until` and no `x2` title; `--check-titles` passes; `--world-test`: an away walker earns no expedition stone; `draw_options` draws a wished `fog · 3 ask` first; one promotion -> one idea with `plus == askers - 1`, no duplicate on replay; `props.py` kit sheet renders `post(1..5)`; the Fell round-trip median from three ring camps measured and printed (<= 60 s, else a nearer seeded boulder field added); `py_compile`; deploy (later) = ONE `deploy.sh` child restart, ffmpeg pid unchanged | v1 |
| 2 | **P1 registry data module:** `RECIPE_WORDS`, `PROJECT_WORDS`, `MENU_WORDS`, `MECHANIC_WORDS`, `REFUSE_WORDS`, `SILENT_WORDS`, `SYNONYMS` (60), `NOUNS`, `RECIPES` (7), `CAPS`, `REFUSE_COPY`, `AGE_PROJECTS`, `WISH_HEADS`, `classify()`, `merge_key()`, `place()` geometry, `--self-test` | `stream/world/registry.py` (new) | 2.5 | P | the 41 live plain lines + 10 ideas class as §2.2 (fixture from the transcript nouns, never fake chatters in a run dir); every `REFUSE_COPY`, `NOUNS` entry and plate / plank template passes `compositor.banned_copy_hits`, `BANNED_DAY_RE`, `BANNED_VERSION_RE`; every recipe part fn name is in the §2.3 allowlist; caps complete for ages 0-5; `good night`, `hello there`, `wtf is this` class `silent`; `I want to go home` classes `have_it`, never a paper | v1 |
| 3 | **P2 ops baseline:** `scripts/keeper_gate.sh` (ALLOW / DENY, sha256 of `honesty.py` + `state_store.py`, revert-word grep, gates 1-11 printed, cleanup traps, `world_batch.lock`); `stop.sh` L45-52 + `status.sh` L70 + `report.py process_health` L428 gain `probe`, `duty`; `duty.py heartbeat --pid-file`; `report.py build_status` gains world / wish fields; the six snapshot-missing files listed for the deploy day | `scripts/keeper_gate.sh` (new), `scripts/stop.sh`, `scripts/status.sh`, `monitor/report.py`, `agents/duty.py` | 2 | P | gate dry run against `S` for the current worktree: 0 paths outside ALLOW; a fixture stage that edits `honesty.py` exits 2; a fixture diff adding `animal` exits 2; `stop.sh` / `status.sh` list every pid name; every harness in `scripts/` carries the cleanup trap; the df and pause checks print | v1 |
| 4 | **W1 AGES row 1, nobody lies down** (+ `Behaviour.fetch` L1123 `is_present`; `message` emits `return`) | `stream/world/behaviour.py`, `stream/world/honesty.py`, `stream/world/state.py`, `stream/world/__init__.py`, `stream/scenes/steading.py`, `stream/panels/world.py` | 3 | W | AGES §8 gates: `behaviour --self-test` 60 settlers x 5 min 0 stuck / 0 in water / tick < 0.5 ms; `honesty --self-test` clean + every fake caught (away bubble, away at waystone B, padded `present_count`, wear at 0 present); steading A2 rewritten (2 min quiet: both remain on the land, `present_count` 0, wear delta 0), C2 < 19 ms; a `fetch` by an away body returns False; compositor 300 frames on copies with honesty 0 | v1 |
| 5 | **W2 AGES row 2, idle life + ROAM** | `stream/world/behaviour.py`, `stream/world/camera.py`, `stream/scenes/steading.py`, `stream/panels/world.py`, `stream/world/honesty.py` | 4 | W | C5 (60 settlers 0 here 5 min: 0 stuck, 0 in water, 0 wear, 0 violations, ROAM never targets a missing settler); D'; `camera --self-test` ROAM case (pan cap held, Moot dwell every third hold at 1.5x, 0 cuts); label density rule at 24 away in view | v1 |
| 6 | **W3 AGES row 3, schema 3 + camps + this spec's fields:** `days_seen`, `days_on_air`, `camp.sessions`, `camp.tiers[]`, `camp_tier_for(p, age)`, camp at hatch, `record_visit` + `day_turn`, plate `N days here · first here <date>`, `last_told`, `wish_post []`, `placed []`, `placed_seq`, `cursor.wishes_offset` + `recompute_wishes`, `migrate_v3` / `verify_v3` / `--migrate-copy --to 3 --chat` | `stream/world/state.py`, `stream/world/land.py`, `stream/scenes/steading.py`, `stream/panels/world.py` | 4.5 | W | `--migrate-copy` on the live copy prints every §6.3 gate and exits 0; a forged identity field exits 1; the boot replay prints `+N` then `+0`; `state --self-test` fixtures for `last_told` round-trip, `camp.tiers` seeding, `days_on_air == distinct local dates`; `save()` round-trips schema 3; plate fixture has no `night N` | v1 |
| 7 | **W4 AGES row 4, ages core:** `AGE_LADDER`, `age_check` at round close, `age` / `age_built` / `age_history` / `age_build`, the pile, the 90 s sequencer on `reveal_rows` (its first drawing consumer) and the repaint scheduler, Camp + Steading objects, monument plate both forms + the project ask clause (reads `registry.AGE_PROJECTS` and the ledger clusters when present), founders plaque `and N others`, camera EVENT + 0.75x, bells / chime at <= 1 Hz, plank `the Steading · 5 people · 31 stones · 5 days`, `wished_by` on `age_history` | `stream/world/land.py`, `stream/world/state.py`, `stream/scenes/steading.py`, `stream/panels/world.py`, `stream/world/keepers.py`, `stream/world/bake.py`, `stream/world/camera.py`, `stream/world/honesty.py` | 7 | W | E' (90 s build, 24 hauls, 0.75x: avg < 13 ms, no frame > 24 ms); never-regress test (age monotonic across a reboot mid-build; banish never lowers age); honesty `age` rule + fakes (regressed age, `age_built > age`); every age string passes `banned_copy_hits` (no `longgrass`, no `day N`); beacon flare <= 1 Hz; provenance covers `raised_by`; the Camp build plays on the migrated copy | v1 |
| 8 | **W5 the return beat + personal ledger:** `return` branch composing <= 3 diff clauses from `last_told`, snapshot rewrite, three bells at 7+ days, own-word mutter on return, nightly board plate on `day_turn`, flower drift stages baked, `!stats` `1 stands`, camp plate `first here` | `stream/world/state.py`, `stream/world/behaviour.py`, `stream/scenes/steading.py`, `stream/panels/world.py`, `stream/world/land.py`, `stream/world/bake.py` | 3.5 | W | a pip returning after 25 min with `age_history` grown by one row and camp tier +1 yields exactly `@x is back · the Camp rose · your tent is a hut`; empty diff yields `@x is back`; under 20 min nothing; fixture of every clause form: `banned_copy_hits == 0`; a flower mark aged 8 days paints a 5-bloom drift, `len(marks)` unchanged, repaint <= 19 ms, provenance 0; `day_turn` plate fixture has no `day N`; plate fixture > 6 names -> `and N others` <= plate width at 22 px; C2 unchanged | v1 |
| 9 | **W6 the wish post + registry consumer:** `MOOT_LAYOUT["post"]`, post sprite + placer reserve, `registry.classify` in `_ingest`, `wish_post` rows, `wish` / `placed` / `placed_step` / `placed_ship` / `day_turn` events, `wishes.out.jsonl`, `wish_class.jsonl` tail, the place queue (90 s pacing, caps, `registry.place`), `honesty.validate_registry` + `validate_copy` + `FN_ALLOWLIST` + fakes, `placed[]` writes, `marks["structures"]` bake + casters, lit-lantern glow gated on `is_present(owner)`, banner live sprite + fallback, reveal via `reveal_rows`, plates (`wished: ...`, `lantern · @kai @jo · since 3 Oct`), plank lines, refusal table + cooldown, `menu_wishes()` / `take_promotions()`, `plank_log.jsonl`, `purge_owner` hides placed rows / `restore_owner` restores, camera `EVENT_TYPES` + `PLACED_EVENT_GAP_S` | `stream/scenes/steading.py`, `stream/panels/world.py`, `stream/world/honesty.py`, `stream/world/land.py`, `stream/world/bake.py`, `stream/world/camera.py` | 8 | W | steading fixture: 40 identical wishes from 40 keys -> one cluster with 40 askers, 40 `wish_post` rows, the post draws 5 papers, the plate reads `wished: a castle · @a +39`; `pinned` fires only after the `wish_post` row exists; a blocklisted record never reaches `classify`; a `silent` class pins nothing; `honesty --self-test`: 12 planted bad placed rows all refused (a `creatures.*` part, `lit_rule: always`, an RGB colour, a banished owner, a `wish_id` not in the ledger, a water cell, the Moot green, a trail, over cap, an unknown fn, a `rate` field, a fence) and none drawn; a person's first item is never refused by the age cap, the second in one session is; pacing one raise per 90 s; the reveal is bottom-up at <= 1 Hz in a /tmp clip judged at 320x180 and 720p; live registry sprites <= 24 in view; C2 < 19 ms with 200 placed rows baked; provenance 0 after banish and after unbanish; every composed string passes `validate_copy`; `menu_wishes` / `take_promotions` round-trip with the S1 rounds self-test; hot-reload probation 30 renders clean on a /tmp compositor run | v1 |
| 10 | **W7 feedback density + blocked lines + C6:** `BUBBLE_BUDGET 6` with oldest-last-bubbled rotation, label brighten, FIFO shared line, the plank priority table, grouped lines, 5 s stone dedupe, `EVENT_MIN_GAP_S 8`, return batching, `_ingest` skips `raw["dropped"]`, C6 harness | `stream/panels/world.py`, `stream/scenes/steading.py`, `stream/world/behaviour.py`, `stream/world/camera.py` | 3.5 | W | C6 measure-first (§7.2): hop events == message count within hold + 1 frame; <= 6 bubbles per frame; every speaker bubbled within 3 lines; no EVENT within 8 s of another; 0 cuts; honesty 0; scene avg / p95 / max recorded; compositor 300 frames `KL_TEST_PIPS=100` board / copy / tile gates pass; a blocked record produces no hop (fixture); no plank string contains a message count; frame PNGs and `.npy` deleted | v1 |
| 11 | **W8 scale hardening (before any growth push):** incremental `chat_names`, `recompute_from_chat` cap 512 MB + manifest reader + `{file, offset}` cursor, `save` on the `_Worker` above 300 pips, `care_log` / `history` caps | `stream/world/honesty.py`, `stream/world/state.py`, `stream/scenes/steading.py` | 3 | W | honesty self-test with a 200 MB synthetic `chat.jsonl` under /tmp (deleted after): rescan < 1 ms per frame after warm-up; state self-test replays across archive + live identically to one file; D' with 300 fixture pips: no frame > 24 ms after frame 10, save on the worker; honesty roster rule holds across the rotation | v1 |
| 12 | **P3 the probe:** `probe.py` (observe / classify / dossiers / ingest / next / take / built / reject / anti-thrash / `--self-test`), `prompts/probe.md`, `probe.sh`, `workflows/wish-build.js` (cloned CONTRACT, `ROOT` = this worktree), the session-cron recipe text | `agents/probe.py` (new), `agents/prompts/probe.md` (new), `agents/probe.sh` (new), `agents/workflows/wish-build.js` (new) | 5 | P | `probe.py --self-test` on a fixture run dir (copies under /tmp): every reader returns its documented fields; `observe` changes nothing but `probe/observe.json` (run-dir mtime diff); `ingest` rejects off-schema JSON and writes nothing; a rejected id is not re-proposed within 24 h; `pause_bot.json` -> `paused: true` and no board write; `MAX_IN_FLIGHT` honoured; closed ideas never ranked; a synthetic 40-asker cluster ranks first; a dossier is written only by the probe; `ps -E` shows no stream secret in the launched env; one dry `claude -p` tick yields schema-valid JSON; `probe.sh` refuses under 20 GB and never writes outside `probe/`, `chatters/`, `wish_class.jsonl`; nothing on screen | v1 |
| 13 | **P4 rotation:** `scripts/rotate_chat.py` (chat + wishes archives, manifests) | `scripts/rotate_chat.py` (new) | 1.5 | P | refuses while `compositor.pid` is alive; the manifest lists every archive with line and byte counts; a fixture replay across archive + live equals the unrotated replay; never touches `L` unless the owner runs it by hand | v1 (tool), use v1.1 |
| 14 | **Q1 QA + staging (test mode only):** migration copy, 300-frame compositor run with real chat copy + the migrated world, every C gate, clips, keeper gate dry run, cleanup | `/tmp/lg-idle-stage*/` (deleted after; `report/` kept); the stage recipe per HANDOFF.md L86-99 | 3 | Q | `df` >= 20 GB before launch; §6.3 gates printed, exit 0; compositor 300 frames on the migrated copy + chat copy: `honesty_violations` 0/0, p95 < 25 ms, 0 banned-copy hits, board / tile gates; C2 / C5 / D' / E' / C6 recorded; `keeper_gate.sh` dry run 0 violations; clips at 320x180 and 720p of the return beat, a paper pin, a lantern raise, the Camp build, the Moot dwell with the post in frame; every plate name resolves to a `chat.jsonl` chatter; PNGs / `.npy` deleted; the owner reads the gate report before any live decision | v1 |
| 15 | **D1 docs:** OPENWORLD §8 table (post, plate forms), §10 (tier-2 lane), §11 (nightly board real), §12 (= §5.1 here); ART.md §9 / §10 (post, recipe parts); art-rules §2 (fence / lantern exception, growth-by-real-days note beside tree stages); AGES.md fixes (§0.3) + status; HANDOFF (processes, probe tick order, gate); RESUME (probe launch line, cron recipe); journal 038; WORLD_API (`present_count`, ROAM, age / wish / placed events) | `docs/OPENWORLD.md`, `docs/ART.md`, `docs/art-rules.md`, `docs/AGES.md`, `docs/HANDOFF.md`, `docs/RESUME.md`, `docs/journal.md`, `stream/WORLD_API.md` | 2 | D | every copy string quoted in the docs passes `banned_copy_hits` (a doc grep in the gate); journal 038 lists what shipped in test mode vs what waits for the owner's live decision; RESUME has the probe launch and cron lines | v1 |
| L1 | **W9 Centuries composer:** wish slots per age filled from ranked project clusters with validated parts lists (probe-drafted DATA in `wish_class.jsonl`), generic `SITES` over `RAISING_SITES`, monument ring per Century, `AGE_LADDER` extension | `stream/world/land.py`, `stream/scenes/steading.py`, `stream/world/bake.py`, `stream/world/keepers.py`, `stream/world/honesty.py`, `stream/panels/world.py` | 5 | W | a turn with 0 valid recipes still turns; a slot structure composes only allowlist parts and passes the ART.md §14 sheet at 320x180; E' with 2 slots; provenance 0 | later |
| L2 | **Village art:** the Ford bridge, the monument top, lantern posts on the spoke, the plaza tiles (child restart) | `stream/world/art/buildings.py`, `stream/world/art/props.py`, `stream/world/art/tiles.py`, `docs/ART.md` | 3 + 1.5 | S | ART.md §14 checklist on the review sheets; `render_gate.py` tiles | later |
| L3 | **`AGE_VERBS`** age-scaled stack cap / cooldown (3/45 -> 4/30 -> 6/20) after the walk measurement and a first live week of stack refusal counts | `stream/chat_bridge.py` | 1 | S | rung-naming refusal copy passes `banned_copy_hits`; cap per age asserted | later |
| L4 | **probe `--model`:** batched long-tail classification into the closed enum, recipe drafting as parts lists, `WISH_USD_PER_HOUR` | `agents/probe.py`, `agents/prompts/probe.md` | 2 | P | off-enum -> `silent`; budget cap flips to keyword-only; prices checked against the live gateway first | later |
| L5 | builder pool sharded by cluster (`crc32(merge_key) % 3`), only if more than one build a day is ever wanted | `agents/probe.py`, `agents/workflows/wish-build.js` | 2 | P | never two on the world batch (`world_batch.lock`) | later |

**Totals (v1):** W 36.5 h serial (the critical path), S 4 h, P 11 h, Q 3 h, D 2 h = **56.5 agent-hours**; later rows
14.5 h + 1.5 h art. Parallel plan: S1 and P1-P3 start with W1; P4 any time; W6 starts only after W5 AND with P1 + S1
on disk; Q1 after W7; D1 drafts alongside and closes after Q1.

---

## 9. Risks

- **The spine deploy is one shot.** S1 touches `chat_bridge.py`, `rounds.py`, `audio.py`, `state_store.py` and
  `props.py`: one relay-held child restart with every file copied together (a partial copy is the journal 028 / 029
  black-strip pattern); until it lands the STONES key has exactly one live source and the honest plate reads `14 more
  stones` for a long time. Going live is the owner's decision; the stream is off today.
- **The stack walk is unmeasured.** If the median Fell round trip is > 60 s the 3-per-session loop is mostly waiting
  and the griefing surface (boulder walks across the map) is real; S1's gate measures it and adds a nearer seeded
  boulder field if needed; the first live week counts stack refusals per chatter in `acks.jsonl` (Q4).
- **A return line that reads as the AI talking.** Every clause is a verb the world would carve on a sign and a diff of
  `len()`s; the fixture covers every form; nothing negative, ever.
- **False-positive papers.** `WISH_HEADS` is small and needs a noun or >= 3 tokens; goodbyes, greetings, clock and UI
  words are `silent`; `have_it` answers a house wish from records; the probe's re-class to `silent` un-pins quietly;
  false negatives cost nothing (the bubble still shows, the ledger still has the row).
- **A bad recipe is a bad picture.** Placement checks water / trail / green / camps / marks / other placed items; the
  allowlist has no figure, fence, home, fire or beacon; ART.md §14 is re-run on the composite sheet before any recipe
  class ships; the age cap bounds the count.
- **Wish-derived text on air has no live guard today.** Every plate / plank / board string from a wish is a closed-table
  noun through `validate_copy` at write time; the 300-frame self-test still runs `_hud_checks`; a failed string draws
  nothing.
- **Two writers on `world.json`.** Agents append jsonl; the scene is the only writer; the gate greps `agents/` and
  `scripts/` for `world.json` writes; a future lens must not add one.
- **`honesty.chat_names` and the 64 MB cap** bite before any growth push (W8 is v1 and last in the W lane; the ledger's
  own manifest rides P4).
- **Hot-reload probation catches raises, not dishonesty.** Gates 4-6 of the keeper gate are mandatory and printed; an
  orchestrator that skips them under time pressure removes the safety net.
- **Camera hijack by raises at 10+ here** is prevented by the `placed` EVENT rule (<= 2 here or owner here, 60 s gap);
  at 1-2 here the raise IS the show.
- **The people key cannot be earned solo** by design; the personal ladder (camp by days, gear by minutes, trees and
  drifts by real days, a first placed thing in minute three) ships in the same release as the forward plate so there
  is always something climbing.
- **Papers that never rise** (`unknown`, `project`) could read as ignored: the paper is an ask the probe reads, the
  plate shows the ask count, and nothing ever says a thing is coming; the probe's Q3 and fairness term keep the loop
  pointed at them.
- **Prompt injection through wish text** is contained because the model's output is a closed enum validated in
  `honesty.py` (DENY set, hashed by the gate); wish text never sits in an instruction position or a shell string.
- **The probe going blind or thrashing:** propose-only; `MAX_IN_FLIGHT 1 / 2`; 24 h rejection memory; nothing during a
  build, a raising or a macro; `pause_bot.json` observe-only; a journal paragraph only when something changed.
- **Disk:** every harness cleans frame PNGs and `.npy` and refuses under 20 GB; the probe's OBSERVE deletes stale
  `/tmp/lg-*` without a `report/` after 48 h.
- **Workflows hard-code `ROOT`** to the main checkout (`agents/workflows/*.js` L7); `wish-build.js` points at this
  worktree; the harness must not stage the wrong tree into the gate.
- **Migration on a file three real people care about:** copy first, extended and printed gates, refuse-to-boot,
  `.bak-pre-idle`, the static-watchdog behaviour rehearsed on the copy, rollback for a week.
- **Copy drift in AGES.md itself** (`Longgrass`, `day 3`, the 2 Hz flare) is corrected in D1 before W4 ships; the doc
  grep in the gate keeps it corrected.
