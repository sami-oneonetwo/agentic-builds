# World API — LONGGRASS: what the verbs / rounds / text-layer / panels / audio agents code against

Owner: the world core (`stream/scenes/steading.py`, `stream/world/*`). Spec: `docs/OPENWORLD.md` (§4 map and camera,
§5 entity model, §6 verbs, §7 art and budget, §8 layout content, §12 honesty); art: `docs/ART.md` (the look) and
`docs/art-rules.md` (what may appear and move). Python 3.9, pillow 11, numpy 2, stdlib. **Nothing here reads
`time.time()` in the frame path: `ctx.now` only**, so `--self-test` stays deterministic from a seed. Every coordinate
below is in **map cells** (960x440; 1 cell = 4 screen px at the 1x zoom) unless it says screen px.

This revision replaces the cave's contract (`CaveScene`, `hollow.py`, `world.json` schema 1); §11 keeps a pointer to
it for the rollback week. Where a section describes a module that is still landing (scene, behaviour, text layer),
it states the contract those modules are built to; the gate modules (§4) and the panel contract (§2.1) are code on
disk, exercised by their self-tests and by `/tmp/lg-copy-panels/test_panels.py`.

## 1. The flow, one frame

```
chat.jsonl ──StateStore.drain_chat()──► ChatBridge.ingest()   (hold 3 s, blocklist, hidden, builder #N, leading-verb rule)
                      │                          │
                ctx.chat_raw (≤20, unmoderated)   ctx.chat (≤10, moderated, past the hold, display_name)
                      │                          │
  SteadingScene.frame(ctx, size):                │
    _ingest:  raw record, no pip  → Behaviour.seed_drop(key)      a NAMELESS tuft drifts in from the upwind edge on the
                                                                  real wind vector toward its hashed spot on the Moot
                                                                  green; the settler's 23-frame sheet (~0.75 s) starts
                                                                  rendering in a worker thread NOW (the hold covers it)
              raw record, has pip → Behaviour.message(key)        hop + brighten this frame; a sleeper stands up at its camp
              moderated record    → WorldState.ensure_pip(...)    identity frozen once (name, n, colour_idx, genome+salt)
                                    Behaviour.hold_cleared(...)   ≥ 3 s after the seed → "hatch" on the green (if the
                                                                  sheet is not ready, the tuft holds one more beat;
                                                                  a frame never blocks on art)
                                    Behaviour.speak(key, text)    bubble text 6 s → "speak"; awake pips look (look_l/r)
              ctx.recent_votes    → Behaviour.walk_to(key, "A")   → "walk" along the BFS route, "arrive" at the waystone
              verbs (ChatBridge)  → scene.command(verb, actor, target, arg, now)   go / plant / camp / fire / sow / ...
              ctx.round.number ↑  → Behaviour.release_votes()     everyone leaves the waystones
              ctx.mod.hidden_users→ lie down in the grass / the tuft blows away
              ctx.session.ending  → Behaviour.start_credits()     one by one to their camps → "credits"
    nature.update(now, chat_rate)        wind (base = real chat rate), gusts, cloud drift
    Behaviour.tick(now, dt) → events     2D targets, routes, slide rule, stuck detector, wander with Moot gravity,
                                         wear under every real step (land.step), sleep at own camp after 20 min
    camera.update(now, dt, awake, seeds, events, moot, stops, lead_key)   EVENT > MOOT > FOLLOW > CLOSE > DRIFT
    _honesty_check                       every entity origin "chat" (or "test" under KL_TEST_PIPS in /tmp + test mode);
                                         land.provenance_violations() every 5 s; wear sum == 8 x steps + spill
    _persist                             world.json (atomic, ≤ every 5 s), camera every 5 s, minutes_present, tiers,
                                         care-log playback on wake
    render:  B = bakes.want(season_idx, sun, land.bake_ver, marks)           the ready ground bake (or its fallback)
             crop = B.ground(...)  field = nature.modulation(window, now)     tint x wind x clouds x shadows x tide x rain
             rgb = bake.apply(crop, field, ...)  → glow (after dusk) → live sprites y-sorted (creatures + shadows,
             planted trees, fires, smoke, banners, carried items) → particles → Image.fromarray → RGBA `size`
```

The scene draws **no text**. Names, bubbles, plates, waystone letters and counts, the plank, the land line, the time
dial, the minimap, edge arrows and place labels are the text layer's job (`stream/panels/world.py`) at screen scale
(≥ 20 px), using `scene.entities()`, `scene.events` and `scene.camera.sim_to_screen()`.

## 2. `SteadingScene` (stream/scenes/steading.py)

```python
from stream.scenes.steading import SteadingScene
scene = SteadingScene(run_dir=None, seed=None, log=None, sleep_after_s=1200.0, hold_s=3.0, name_filter=None)
```
| member | type | meaning |
|---|---|---|
| `frame(ctx, size) -> PIL.Image` | RGBA, exactly `size` | never raises; last good frame on an internal error, one stderr line. **Refuses to boot** (keeps the last good frame, `booted` False) when `world.migration_ok` is False (§3). Call once per frame from the `world` panel's `render()`. |
| `booted` | bool | True after the first frame booted the world (the panels read nothing before that) |
| `events` | `list[dict]` | events produced by THIS frame (§6); read after `frame()`, replaced next frame |
| `entities(now=None) -> list[dict]` | | one per entity (§5). Seeds have `display_name: None` and `key: None`. |
| `awake_count()`, `asleep_count()`, `hatched_ever()` | int | `len()` over real records; `awake` = state in (awake, walking, voting, curled). Test pips never count. |
| `platform_counts() -> {"A": [keys], "B": [...], "C": [...]}` | | who STANDS at each waystone (state `voting`); the embodied tally the rounds read (API name kept) |
| `command(verb, actor, target=None, arg=None, now=None) -> (ok, reason)` | | §7 |
| `verbs() -> tuple[str]` *(optional)* | | the verb words `command()` implements in THIS build. The ticker legend draws only these; when the scene has no `verbs()` it reads `stream.chat_bridge.VERBS` minus `LATER_VERBS` (the words the parser accepts and acts on), so the legend never advertises a verb that would be refused (§2.1). |
| `world` | `WorldState` (schema 2) | §3. Read freely; write only through its methods. |
| `land` | `Land` | `world.land`: wear, marks, camps, fields, stones, raisings, strips, weather, camera, hearth, bake_ver (§3) |
| `nature` | `Nature` | wind / clouds / sun / moon / seasons / tide / weather (§4.2); `nature.world_day` is `"real"` or `"hour"` |
| `camera` | `Camera` | §4.4; `camera.mode`, `.zoom`, `.view_rect()`, `.sim_to_screen()`, `.edge_arrows()`, `.minimap()`, `.drift_stop` |
| `bakes` | `BakeManager` | §4.3; `bakes.baking`, `.current`, `.pending` (the readout shows `baking <season>…`) |
| `behaviour` | `Behaviour` | `behaviour.newest_speaker` (key), `behaviour.get(key)`, `entities` |
| `keepers` | `Keepers` or None | beacon / notices / raisings (`stream/world/keepers.py`); `raising`, `last_raised`, `waiting`, `raising_line(now, ctx)`, `last_ticker`, `last_ticker_t` |
| `honesty` | `HonestyMonitor` | `line()`, `summary()`; the readout shows its line when it contains `violation` |
| `degrade` | dict | `{"clouds", "wind", "shadows", "glow", "labels_on_speak", "bubbles_single", "zoom_pinned": bool, "level": int}` — the ladder of OPENWORLD §7.4 on the scene's own ms averaged over 30 frames (> 14 clouds off + wind static; > 18 glow off, then shadows; > 20 labels-on-speak; > 24 bubbles single; > 28 zoom pinned; one step back per 300 clean frames). The cave's dict had only glow / labels_on_speak / bubbles_single / level; panels read keys with `.get`. |
| `stats() -> dict` | | `frames, errors, last_ms, avg_ms, degrade, entities, awake, asleep, hatched_ever, settled, honesty_violations, test_pips, camera{mode,x,y,zoom,cuts}, bake{ready,baking,ms}, sheets{cached,pending}` |
| `distinct_recent_chatters(ctx, now) -> int` | | honesty reference: distinct real chatters in the last 20 min of this session (self-test asserts `== awake real entities`) |

`ctx` fields the scene reads: `now`, `session{id, started_ts, ending}`, `micro{canvas_seed, weather, colony_rule}`,
`preset`, `chat_raw`, `chat`, `recent_votes`, `round{number}`, `mod{hidden_users}`, `mod_paused`, `agent{heartbeat_ts}`,
`macro{active}`, `compositor_live{selftest}`, `chat_stats{msgs_per_min_5m}` (the wind). `run_dir` defaults to `$RUN_DIR`;
`world.json` and `bake/` live there (the run-dir guard keeps test runs out of the live dirs).

### 2.1 What the strips read: the panel contract (`stream/panels/world.py` module functions)

The header, the land strip (`colony.py`), the keeper strip, the readout and the ticker never construct a scene. They
read the live one through the world panel module (so a hot-reload of the scene is followed) and fall back to the
cave's words when the scene has no `land`. This is the contract `/tmp/lg-copy-panels/test_panels.py` exercises
against a scene stub built from the real `WorldState(schema=2)`, `Nature`, `Camera` and `BakeManager`:

| function | returns | who reads it |
|---|---|---|
| `scene()` | the live scene instance (never a second one); `hasattr(scene(), "land")` says "a land scene", `scene().land` is None until it boots | every strip |
| `world_counts()` | `(awake, asleep, hatched_ever)` as `len()`s, or `(None, None, None)` before boot | header (`3 AWAKE` / `NOBODY AWAKE` / `-- AWAKE`), land strip line 2, ticker (`!commands` only when awake > 1) |
| `world_degrade()` | `dict(scene.degrade)` or None | readout: `world: clouds off` / `world: glow off` / `world: shadows off` / `world: zoom pinned` |
| `is_land(sc=None)`, `scene_kind()` | True / `"steading"` once a land scene has booted (camera + land present); the strips also treat a not-yet-booted land scene (`hasattr(scene(), "land")`) as the land for their wordmark and column word | header |
| `land()`, `nature()`, `camera()`, `terrain()` | the scene's objects or None | text layer; strips read them off `scene()` |
| `world_info(now)` | `{kind, camps, fields, fields_gold, trees, flowers, stones, marks, days, settled, walked_pct, ladder, clock, world_clock, day_part, season, wind, moon, weather, world_day, hemisphere, camera{...}, baking: bool, awake, asleep, settled_pips}` or None on the cave | text layer land line / time dial; the strips read the same `land.counts()` / `nature.describe()` directly |
| `scene().bakes` | the scene's `BakeManager` (`.baking`, `.pending`, `.current` with `.season_idx`) | readout `baking spring…` |
| `honesty_line()` / `honesty_summary()` | the HonestyMonitor's line / dict | readout (a line containing `violation`) |
| `keepers()` | `scene().keepers` or None | keeper strip line 2, ticker keeper line, land strip caption |
| `shown_name(raw)` | the filtered display name for a username (pip row's `display_name`, blocklist → `builder #N`), None before boot | every name on every strip; under `!kill` (`ctx.chat_display` False) no strip draws a name at all |
| `when_text(ts_iso, now)` | `21:14` / `yesterday 10:40` / `Sep 24 10:40` / `--` | keeper strip visitors |

And the scene attributes those strips read directly (all via `getattr`, all optional): `land` (`land.settled`,
`land.days`, `land.counts(now)`, `land.ladder()`, `land.plaque()`, `land.raisings`, `land.land_strips`),
`nature` (`describe(now)["season"]`, `world_day`), `bakes` (`baking`, `pending`/`current`.`season_idx`), `verbs()`,
`behaviour.newest_speaker`, `keepers.raising` / `.opening` / `.waiting`.

What each strip derives (OPENWORLD §8; the cave's copy stays on the cave):

| region | on the land | source |
|---|---|---|
| `header_left` | `atleastonce` / **`LONGGRASS`** | scene class has `land` |
| `header_center` | `3 AWAKE` AB 56 · **`· 17 SETTLED`** Menlo 24 (`len(real pips with a camp)`) · `NEXT EVENT 01:23`; during a build `keeper raising · 12:40 left` | `world_counts()`, `land.settled`, `ctx.round`, `ctx.macro` |
| `colony` → **the land** | `17 have walked here` / `day 6 · 8 more until the Coast opens` over the bar (ladder 3 / 5 / 10 / 25 / 50: cairn named, hearth ring, the Coast, the Birch Wood, the Tarn) / `3 awake · 14 asleep · 6 camps · spring · 2 fields gold` as far as 388 px allows / rotation: `stone 13 of 20 · the Ford bridge`, last event, `the well · raised v0.7.0`, `the Coast · opened by @kai`, `cairn · stones by @kai @sami`, `last night: @sami stacked 3 stones · 1 arrived`, the `!stats` card | `hatched_ever()`, `world.milestones[_reached]`, `land.*` |
| `keeper` | `keeper on duty · beacon lit` / `no keeper on duty · notices kept for next time`; `raising: the Ford bridge · asked by @sam · 12:40 left` / `last raised: the well · v0.7.0`; `last here: @a 18:00 · @b 14:59`; `!idea <text> pins a notice to the board on the Moot`; failure lines 20 s; the beacon glyph | `ctx.agent.heartbeat_ts`, `ctx.macro`, `ctx.ships`, `keepers()`, `world.visits` |
| `readout` | flags above + `baking spring…` (secondary, not amber) | `world_degrade()`, `world_status()` / `bakes` |
| `ticker` | honesty line `no camera, no mic, no fake viewers. every name on this land is a real person in chat. the wind is just the wind.`; legend `say anything: a creature walks out with your name   go · plant · … A / B / C walks your pip to a waystone` built **only from `verbs()`** (else `stream.chat_bridge.VERBS` minus `LATER_VERBS`); `a day here is one hour` only on `world_day: "hour"`; the rule `the keepers are AI agents. they raise this land live, from your !ideas, and you watch it go up.` only while a keeper is on duty | `verbs()`, `nature.world_day`, `ctx.agent` |

Strip rules: every number is a `len()`; every name passes `shown_name()`; a line that does not fit its width is
shortened by dropping a fact or a form, or skipped, **never a chopped name**; nothing under 20 px; the strips compute
their lines once per frame (memoised on `ctx.now`/`ctx.frame`) and redraw only when a line changes.

## 3. `WorldState` schema 2 and `Land` (stream/world/state.py, stream/world/land.py)

```python
ws = WorldState(run_dir, log=None, name_filter=None, schema=2, moot=T.site, passable=T.passable, water=T.water, now=ctx.now)
ws.schema -> 2 ; ws.migration -> report | None ; ws.migration_ok -> bool   # False => the scene MUST refuse to boot
land = ws.land                                                              # None on a schema-1 document
```
`schema=None` keeps the file's schema (a fresh file is 1: the cave's contract); `schema=2` asks for LONGGRASS: a fresh
file starts at 2, a schema-1 file is migrated on a copy under the §5.4 guard (`world.json.bak-v1-<stamp>` written
first, never pruned; adopted only if `ok`). **Pass terrain's places centre and masks BEFORE the migration** (as above)
or camps hash around the map centre (480, 220). Everything the cave had is kept (`ensure_pip`, `record_message`,
`presence`, `tier_for`, `care`, `gift`, `bond`, `forget`, `woke`, `visit`, `log_event`, `banish`, `quarantine`,
`recompute_from_chat`, `save`, `backup`, `data`, `builders`), plus:

```python
ws.set_pos(key, x, y, facing=(fx, fy)|None) ; ws.set_carry(key, "berry"|"stone"|None, t)
ws.ensure_camp(key, t, session_id=None, x=None, y=None) -> camp | None   # first real sleep -> hollow tier 0 where the pip
                                                                          # stood (else the hashed Steading-ring spot); later
                                                                          # sleeps record the night and re-read the ladder
ws.plant_moss(...) on schema 2 -> land.add_mark("flower") ; ws.quarantine() / ws.banish() also purge the owner's land (audit kept)
ws.migrate_v2(now, moot_xy, passable, water, dry_run=False, write_bak=True) -> report{from_schema, to_schema, pips, camps,
    flowers, flowers_dropped, nests, nests_dropped, ok, problems[], bak?}
migrate_copy(src_path, out_path=None, moot=None) -> report      # refuses run-live / run and the source path
$PYTHON stream/world/state.py --migrate-copy SRC.json [--out /tmp/x/world.json] [--moot X,Y] ; --self-test
```
Schema-2 pip row: the v1 fields minus `burrow` / `digs` / `moss_planted`, plus `y` (cells), `facing [fx, fy]`,
`colour "#RRGGBB"` (from `art.creatures.genome`), `camp {x, y, tier, built_ts, nights[]} | None`, `field {x, y, sown_ts,
stage, harvests, waterers[], boost_s} | None`, `carry`, `carry_since_ts`, `home [x, y] | None`, `marks_planted {flower,
tree, reed, stone}`, `history {digs, burrow, moss_planted, x_v1, y_v1}`. World block: `map_seed, map_w, map_h, moot,
hemisphere, world_day, wear_b64, marks[], fields[], stones[], raisings[], land_strips[], camera, weather{state,
since_ts, chain_seed, until_ts?}, hearth{lit_ts, by}, bake_ver, bake_reason, mark_seq, history{v1}` + the kept
`milestones, milestones_reached, hatched_ever, woke_log, visits, board, last_board, event_log`. The nightly board on
the land may carry `stacked {key: n}`, `walked {key: cells}`, `fed {key: n}`, `hatched [keys]`, `gold [keys]`; the
land strip reads whichever keys exist.

Migration rules (§5.4, implemented): identity deep-copied byte-identical; hatched pips with `sessions_seen ≥ 1` get a
camp at `hashed_camp_spot` inside the Steading ring (24-60 cells from the Moot, 12-cell gap), tier from the ladder,
`built_ts` = `first_seen_ts`, `nights` = `session_ids`; each moss row → a flower mark 3-6 cells beside the planter's
camp (ownerless rows dropped and counted); nests → the second parent's camp 6-8 cells from the first; `voting` →
`asleep`. Guard: identity + salt byte-identical, counts and key sets equal, record fields unchanged, banished /
quarantine keys kept, no v1 fields left, every mark owned, every camp / mark on the map, no two camps on one cell.

`Land` (get it as `ws.land`; every write goes through `real_pip()`, so test pips and unknown keys are refused; wear
never decrements; marks never decay): wear `step / take_wear_added / wear_at / trail_tier / walked_mask /
walked_fraction`; marks `add_mark / mark_allowed / marks_by / marks_of_type / remove_marks / tree_stage`; camps
`camp_of / camps / settled / camp_allowed / set_camp / record_night / upgrade_camp / plate / bonded`; fields `sow /
field_stage / advance_fields / water_mark / harvest / fields / fields_gold`; stones `stack / stackers / plaque /
cairn_height / cairn_named / ladder → {stock, next, index, name, done, ready, last_by}`; `add_raising / raisings`,
`open_strip / land_strips`; `weather / set_weather`, `camera / save_camera`, `hearth / light_hearth / hearth_lit`,
`bake_ver / bump_bake`, `days` (distinct sessions), `counts(now) → {camps, fields, fields_gold, trees, flowers,
stones, marks, days, settled, walked_pct}`, `survey_stops(natural)` for the camera's DRIFT, honesty
`provenance_violations / purge_owner / restore_owner`. Constants: `CAMP_LADDER (1, 2, 5, 10)`, `CAMP_KINDS`,
`CAMP_WORDS ("camp", "tent", "hut", "hut")`, `STONE_LADDER (20, 60, 150)`, `RAISING_NAMES`, `CAIRN_NAME_AT 3`,
`WEATHER_STATES`, `MARK_CAP_LIFETIME 40`.

## 4. The gate modules (on disk, self-tested)

### 4.1 Terrain (`stream/world/terrain.py`)
`T = terrain.generate(seed=4471, w=960, h=440)` (cached per key; 390 ms). Arrays (440, 960): `elevation`, `moisture`,
`height`, `moisture8`, `biome` (B_DEEP 0 … B_MARSH 10, `BIOME_NAMES`, `WATER_BIOMES`, `PASSABLE_BIOMES`, `COST`,
`BIOME_RGB`), `water`, `sea`, `pond`, `river`, `ford`, `passable`, `cost`, `caster`, `solid`, `shade`, `shore_dist`,
`sparkle_phase`. Lists `trees`, `boulders`, `ford_stones`, `river_path`; points `site` (the Moot centre, (564, 244)
for 4471), `moot_r` 26, `ford_centre`, `fell_top`, `fell_centre`; coarse grid `grid` (28, 60), `block_of`; places
`places[name]` / `place(name)` for moot, steading, ford, river, shore, fell, wood, marsh, orchard; queries
`in_bounds`, `is_passable`, `nearest_passable`, `route(a, b) -> [(x, y)]` (8-connected BFS, no corner cutting, `[]` if
unreachable); exports `cells()`, `biome_rgb()`, `grass_mask()`, `summary()`, `save_png(path, scale)`.

### 4.2 Nature (`stream/world/nature.py`)
`N = Nature(T, seed, hemisphere=None, world_day="real"|"hour", tz=None, clouds=None)`; `N.update(now, chat_rate_per_min)`
once per frame; `N.modulation((x0, y0, w, h), now, caster=None) -> float32 (h, w, 3)` every value ≤ 1.0 (tint x wind
bands x cloud shadows x shadow layer x tide band x rain); `N.last_sparkle` after it. `N.degrade` = {clouds, wind,
shadows, sparkle}. Reads: `hour`, `clock`, `world_clock`, `season` 0..4, `sun`, `moon`, `tint`, `is_night`,
`describe(now) -> {clock, world_clock, hour, day_part, night, wind ("wind NE · fresh"), wind_speed, wind_from, gust,
season, season_f, hemisphere, moon, moon_phase, tide_cells, weather, world_day, tint, sun}`. Members `wind`, `clouds`,
`weather` (`set_round(state, now, duration_s=180)`, `state_at(now)`). Constants: `NIGHT_TINT (0.52, 0.55, 0.74)`
(luminance 0.557 ≥ `NIGHT_FLOOR` 0.55) + `MOON_MAX` 0.05; `SEASON_NAMES`, `DAY_PARTS`. Growth: `tree_stage(planted_ts,
now, orchard)` 0/1/2 (day 3 / 14, 1.5x on the orchard), `field_stage(sown_ts, now, rain_bonus_days)` 0..3 (day 1/3/7).

### 4.3 Bake (`stream/world/bake.py`)
File `$RUN_DIR/bake/ground-<seed>-<season0-3>-o<sun octant>-v<bake_ver>[-p3].npy` (uint8 (1760, 3840, 3) memmap,
20.3 MB; `-p3` = 3 px/cell (1320, 2880, 3), 11.4 MB, for the 0.75x zoom). `GroundBake(run_dir, T, season_idx, sun,
bake_ver, marks, log, px_per_cell)`; `.start(background=True)` (opens an existing file in 1-10 ms, else paints in a
daemon thread: strips via `tiles.Ground`, y-sorted props, huts by camp tier, flowers; tmp + `os.replace`; prune to 4
files); `.ready / .baking / .progress / .error / .ms`; `.crop / .fallback / .ground`; `.repaint(region, marks)` (4.5-5.4
ms for a hut). `BakeManager(run_dir, T, log, px_per_cell)`: `.want(season_idx, sun, bake_ver, marks) -> GroundBake`
once per frame (returns the CURRENT ready bake, lands the next in the background, swaps when ready; the very first
bake serves its fallback), `.current`, `.pending`, `.baking`. Per frame: `bake.view_cells(...)`, `B.ground(...)`,
`N.modulation(...)`, `bake.apply(crop, field, ox, oy, w, h, N.last_sparkle, cell_px)`, `bake.resample(rgb, (1280, 440))`.
Marks dict: `{"wear": uint8 (H, W) | None, "huts": [{x, y, tier 0-3, owner, lit}], "fields": [{x, y, stage, owner}],
"flowers": [{x, y, owner, variant}], "stones": []}`. The bake name carries the sun octant (props are lit per octant
like the sprites; ~1.75 h of world time per octant, re-baked lazily in the thread).

### 4.4 Camera (`stream/world/camera.py`)
`Camera(map_w=960, map_h=440, margin=12, zoom=1.0, allow_zoom=True, moot=(480, 220), tau_s=0.8, pan_cap=60.0)`.
`resume(land.camera())` (None snaps to the Moot: the one allowed cut, first frame); `update(now, dt, awake=[{key, x, y,
fx, fy, walking, spoke_t}], seeds=[(x, y)], events=[{type, x, y}], moot={stones, voters, walking_to_stone,
round_remaining}, stops=land.survey_stops(natural), lead_key=None)`. Reads: `mode` (EVENT / MOOT / FOLLOW / CLOSE /
DRIFT), `cx, cy`, `zoom` ∈ (0.75, 1.0, 1.5), `speed`, `cuts` (must stay 0 on air), `view_rect()`, `bake_crop(ppc=4)`,
`scale()`, `sim_to_screen(x, y) -> (sx, sy) | None`, `screen_to_sim`, `in_view`, `zoom_blend(now)`, `edge_arrows()
-> [{key, x, y, side, sx, sy, dist}]`, `drift_stop -> {id, kind, owner, x, y} | None`, `minimap(size=(144, 66))`,
`to_dict(now)`, `maybe_persist(land, now)`, `stats()`. `EVENT_TYPES = ("seed_land", "seed", "hatch", "wake", "camp",
"camp_raised", "raising", "raising_ship", "land_open", "cairn_named")`. `allow_zoom=False` pins 1x (v0 preview, the
degrade rung > 28 ms). Motion: critically damped spring (tau 0.8 s), displacement clamped to 60 cells/s, dead zone
(> 10 cells immediate; 2-10 after 1.5 s; < 2 ignored), 12-cell edge clamp, zoom only at rest and ≥ 20 s apart.

### 4.5 Atlas interface (`stream/world/art/`, `docs/ART.md`)
| module | call | notes |
|---|---|---|
| `creatures` | `genome(name) -> {hue, accent, outline, hair, …, "body"}`, `render(name, tier, frame, zoom, sun) -> RGBA`, `shadow(name, tier, zoom)`, `head_icon(name)`, `sheet_image()` | 23 frames (idle0/1, blink, look_l/r, walk0-3, hop0/1, wave0/1, point, sit, sleep, carry_berry/stone/tool, speak0/1, joy, love); tiers 26 / 30 / 34 / 42 px at 1x; cached per sun octant; **a sheet costs ~0.75 s: never on the frame loop** |
| `buildings` | `render(kind, tier, colour, seed, lit, sun) -> (RGBA, (dx, dy))` | hut 0 tent / 1 hut / 2 chimney / 3 hall, well, garden, fence, banner, lantern, smoke, waystone, beacon, cairn |
| `props` | `render(kind, stage, season, zoom)`, `anchor(spr)` | tree by age 0-3, bush, flower clump, stones, cairn, waystone, campfire (4 phases), beacon |
| `tiles` | `Ground(...)` (4 px/cell), `repaint(region)`, `grade(rgb, hour, water)`, `sun_vector(hour)`, `CAT`, `FLAT` | 32 px tiles, nothing crosses a tile edge; wind phase 0-3; the bake paints through this |
| `hud` | `font(size >= 20)`, `place_pills`, `fit_segments`, chrome tokens | screen scale only |

## 5. `scene.entities()` item (the land)

```python
{"key": "sami", "origin": "chat", "state": "walking", "display_name": "Sami", "tier": 1, "energy": 0.62, "salt": 0,
 "x": 571.4, "y": 250.0,                     # map cells, y = the feet row
 "facing": [1, 0],                           # unit vector quantised to 8 directions (the camera's lead room, the sprite flip)
 "sx": 660, "sy": 296, "sw": 30, "sh": 34,    # screen box inside the world region via camera.sim_to_screen(); None off-view
 "frame": "walk1", "waystone": None, "camp": {"x": 463, "y": 271, "tier": 1},
 "text": "hello", "speaking": True, "learned_from": None,  # bubble text ONLY while speaking (6 s), else None
 "first_ever": True, "minutes_tonight": 3.2, "awake": True, "colour": "#9B52E5",
 "carrying": None | "berry" | "stone", "flash": False, "route_len": 12, "target": [582, 215]}
```
States: `seed hatching awake walking voting curled asleep burrowed`. For `seed` / `hatching` the dict has
`display_name: None` and `key: None`: **nothing about a seed may be drawn as a name.** `burrowed` = hidden by a mod
(lying in the grass, no label, no plate). `display_name` is already the filtered name (`builder #N` on a blocklist
hit); if `ctx.chat_display` is False the text layer draws no names at all (`!kill`). Standing pips (`voting`) hold a
slot at a waystone (3 per row, 7 cells apart) and are counted by `platform_counts()`. Sleepers lie at their own camp
(frame `sleep`, a 1 % breath) and never move.

## 6. Events (`scene.events`, one list per frame)

| type | fields | who consumes |
|---|---|---|
| `seed` | `key, x, y, from_edge` | audio (nothing draws a name); camera EVENT |
| `seed_land` | `key, x, y` | audio (tuft landing) |
| `sink` | `key` | plank `the wind took that one` |
| `hatch` | `pip, display_name, first_ever, x, y, only_one` | audio (rise + motif), text layer (`#N` in the label 3 s, `you're the only one out here right now. the wind was already blowing.` 10 s), header tick, camera EVENT (1.5x close-up when `only_one`) |
| `first_breath` | `pip` | audio (first pad voice, every camp bell west to east), plank `@name walked into Longgrass · HH:MM` (replaces the cave's `first_light`) |
| `speak` / `mutter` / `hop` / `blink` / `emote` / `tier_up` | as the cave | audio, text layer |
| `walk` | `pip, to` (`"A"/"B"/"C"`, a place name, `"home"`, `"@key"` or `[x, y]`), `route_len`, `reason?` | audio footsteps by the cell under the pip; text layer place label 4 s |
| `arrive` | `pip, at` (a waystone letter or a place) | rounds (tally changed), audio vote blip |
| `leave_platform` | `pip, platform` | rounds |
| `stuck` | `pip, x, y` | QA only (the 3 s detector re-routed; must never fire twice on one pip) |
| `wake` | `pip, camp, care_log[], away_s, homecoming` | text layer care-log bubble, audio rising third (three bells on a 7+ day homecoming), camera EVENT |
| `sleep` | `pip, camp, quiet_s` | text layer `asleep · quiet 20 min`, fire → embers, audio descending third |
| `camp` | `pip, x, y, tier, word` | plank `@name's camp · night 1`, audio (cloth flap + peg tap), camera EVENT, `land.bump_bake` |
| `camp_raised` | `pip, tier, word` | 12-frame raise, plate `@name's hut · night 5`, audio hammer ticks, camera EVENT |
| `fire` | `pip, at: "camp" \| "hearth", x, y` | glow kernel + smoke + crackle; hearth only from a real person this session |
| `plant` | `pip, type: flower \| tree \| reed, x, y` | audio thud + sparkle; plate on rotation |
| `sow` / `harvest` | `pip, x, y` / `pip, fed: [keys]` | field in the owner's colour; feast chord + hearts; ticker credits |
| `stack` / `stone_placed` | `pip, from` / `pip, n, cairn_named` | carry frame; a click (the naming stone a bell); land strip `stone 13 of 20` |
| `cairn_named` | `by: [keys]` | plaque, camera EVENT |
| `raising` / `raising_ship` | `name, at_stock, plaque` / `name, version` | stakes then scaffold rows at ≤ 1 Hz; chime + rumble; camera EVENT |
| `land_open` | `side, biome, by, version` | minimap rescales, camera clamp moves; notice board; camera EVENT |
| `feed` / `pet` / `gift` | `pip, by, asleep` | audio pop / duet, hearts |
| `swim` | `pip, x, y` | splash, bob 40 cells with the flow |
| `refusal` | `pip, verb, reason` | plank, amber, 4 s (every refusal is visible) |
| `forget`, `banish`, `burrowed` | `pip`, `reason?` | plank (never naming a mod target) |
| `credits_start` / `credits` / `credits_end` | `count` / `pip, minutes_tonight` | text layer credits line |
| `weather` | `state, from_round` | audio beds; text layer land line |
| `sunrise` / `sunset` | `clock` | one soft bell |
| `world_error` | `count` | readout |

## 7. Commands (verbs agent → world)

```python
ok, reason = scene.command("go", actor="atleastonce", arg="river", now=ctx.now)
```
v0 preview implements `go <place|direction|home|@name>` (aliases `walk`, `head`, a bare direction word), `plant
[flower|tree|reed]`, `feed [target]`, `pet [target]`, `gift target` (only at a sleeper's or absent pip's camp),
`wave|sit|dance`, `hop`, `vote` (`arg="A"`), `name`, `forget`, `credits`, `banish target`. v1 adds `camp`, `fire`
(alias `light`), `sow` / `harvest`, `stack`, `swim`, `home`; v1.1 `explore`, `water @name`, `sing`. `reason` is
plank-ready plain words on refusal (`your pip is not awake yet`, `no pip called @x here`, `nowhere called x · try
river ford moot fell wood shore marsh orchard home`, `too far from the water`, `that spot is someone's camp`).
**Rate limits, cooldown copy, the exact-token and leading-verb parsing, the text blocklist and three-strikes stay in
the verbs agent** (`stream/chat_bridge.py`); the world only refuses what it cannot do. `scene.verbs()` lists the words
this build implements; the ticker legend draws exactly those.

## 8. Budget and degrade (measured 2026-09-25, this Mac, `docs/gate/render_gate.py` → `docs/gate/timings.json`)

Scene path (steps 2-4 of OPENWORLD §7.3: crop + modulation field + fixed-point apply + sprite blits), 300 frames each:

| zoom | bake | pips | crop | field | apply | sprites | **total mean** | p95 | max |
|---|---|---|---|---|---|---|---|---|---|
| 1x | 4 px/cell | 20 | 0.02 | 1.13 | 1.85 | 1.33 | **4.34 ms** | 5.03 | 6.73 |
| 1x | 4 px/cell | 60 | 0.04 | 1.18 | 1.92 | 3.47 | **6.60 ms** | 7.37 | 13.52 |
| 0.75x | 3 px/cell | 20 | 0.02 | 1.85 | 2.15 | 1.17 | **5.20 ms** | | |
| 0.75x | 3 px/cell | 60 | 0.03 | 1.87 | 2.19 | 2.85 | **6.94 ms** | | |

The 0.75x zoom reads a second bake at 3 px/cell (a straight 1280x440 crop); the alternative (crop the 4 px bake and
BOX-resample per frame) measured 9.85 ms mean and was rejected. Gate: scene average < 12 ms at 0.75x with 60 test
pips: **passes with margin**. Off the frame loop: a settler sheet 0.75 s (31.9 ms/frame; pre-rendered in a worker
thread at seed drop and at boot), a ground bake 0.78-0.87 s per season/octant in a daemon thread, terrain 390 ms once.
Strips (this contract, `/tmp/lg-copy-panels/test_panels.py`, 300 frames of the virtual clock, `inputs()` every
frame and `render()` only when the cache key changed, as the compositor does): the land strip `inputs()` 0.16 ms
avg / 0.53 max with a redraw of 3.0 ms (2 redraws in 10 s: the 8 s rotation); keeper 0.011 ms / redraw 2.1 ms;
header_center 0.008 / 0.76; readout 0.012 / 0.88; ticker 0.014 ms `inputs()` + 0.04 ms per frame (a crop of its
cached strip), all on a 28 ms per-panel budget. Inside the full compositor self-test with the real `SteadingScene`
(90 frames, `KL_TEST_PIPS=3`, `/tmp/lg-copy-panels/steading`): colony max 4.9 ms over 5 redraws, keeper 4.2 ms over 2. Degrade ladder: §2 `degrade`; `budget_ms 24` on the world panel unchanged; last-good-frame on
any error with one stderr line.

## 9. Test hooks

- `KL_TEST_PIPS=N`: N synthetic pips (origin `test`, `_test: true`, names `test-pip-NN`, display `test pip N`),
  honoured only when `run_dir` is under `/tmp` AND (`ctx.compositor_live["selftest"]` or `MODE=test`):
  `stream.world.test_pips_allowed()`. Never written to `world.json`, never counted, never write wear or marks.
- `RUN_DIR=/tmp/lg-<label>` for every test; never `~/.local/share/kick-live/run-live` or `run`.
- `$PYTHON docs/gate/render_gate.py` (six frames + tiles + timings), `$PYTHON stream/world/camera.py` (camera
  self-test), `$PYTHON stream/world/state.py --self-test`, `--migrate-copy`, `$PYTHON stream/world/keepers.py
  --self-test`, `$PYTHON stream/compositor.py --self-test N` (the whole frame; honesty check every frame).
- `/tmp/lg-copy-panels/test_panels.py`: the strips against a schema-2 world migrated from a copy of the live file
  (camps from migration), a chatter created through `ensure_pip`, a `_test` row that must never count, a real bake
  thread for the readout flag, `!kill`, the compressed-day line, the degrade flags, widths, font sizes, hot reload.
- `SteadingScene(sleep_after_s=60)` shortens the 20 min sleep window for a harness; `hold_s` likewise (never on air).

## 10. Hot reload note

`stream/scenes/*.py`, `stream/panels/*.py` AND `stream/world/*.py` (including `stream/world/art/*`) are watched by
the compositor's HotReloader. A changed world module is executed fresh under its name, the `stream.world` package
attribute is rebound, then the scene module is re-executed and every panel module that mentions `stream.scenes` (the
world panel) re-executes too. A re-executed scene module creates a fresh scene in the world panel (`stream.panels
._WORLD_SCENE` is replaced when the class object changed): the world re-boots from `world.json` (schema 2, the
migration guard applies), sleepers at their camps, an owner who chatted inside the awake window at their saved x / y
with the sleep timer counting from their real last message, the camera resumed from `world.camera` (no cut), the
ground bake opened from `$RUN_DIR/bake/` (1-10 ms) or painted in the background while the fallback shows. The strips
(`colony`, `header`, `keeper`, `readout`, `ticker`) read the scene through `stream.panels.world` at call time, so a
panel-only reload keeps the scene and a scene reload is followed on the next frame; while the world panel still
imports `hollow` (the swap has not landed, or the rollback) every strip keeps the cave's words automatically.

## 11. The cave (rollback week)

`stream/scenes/hollow.py` (`CaveScene`), `stream/world/pips.py` and `world.json` schema 1 stay on disk for one week
(OPENWORLD §14). Their contract is the previous revision of this file (`git log -- stream/WORLD_API.md`) and the
`hollow.py` module docstring; the strips' cave branches implement it unchanged. Rollback = the world panel importing
`hollow` again against `world.json.bak-YYYYMMDD`.
