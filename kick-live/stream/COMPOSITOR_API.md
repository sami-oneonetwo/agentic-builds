# Compositor API — the contract every stream module codes against

Spine files (owner: compositor spine). Everything else in `stream/` plugs into these.

| File | What it is |
|---|---|
| `stream/compositor.py` | the executable frame loop (30 fps, rgb24 to stdout, s16le audio to a FIFO, or `--self-test N` PNGs) |
| `stream/layout.py` | `LAYOUT`, colours, presets, fonts, text helpers. The ONLY source of geometry. |
| `stream/panels/__init__.py` | `Panel` base class, `register()`, `PANEL_REGISTRY`, `discover()`, `placeholder()` |
| `stream/panels/*.py` | one module per region; each ends with `register(SomePanel())` |
| `stream/state_store.py` | `StateStore` -> read-only `ctx` snapshot; jsonl tailing; `write_state_atomic`; time helpers |
| `stream/chat_bridge.py` | `ChatBridge`: classify, votes, moderation stub, founders, builders.json |
| `stream/rounds.py` | `RoundEngine`: 180 s micro rounds, ships.jsonl, CHANGELOG, version bump, state.json writes |
| `stream/audio.py` | `AudioEngine.block(frame_index, ctx) -> np.int16 (1600, 2)` |

Run it (never live from here; `MODE=live` is the owner's call through `scripts/start.sh`):

```bash
source scripts/env.sh
RUN_DIR=/tmp/cp-x $PYTHON stream/compositor.py --self-test 90 --run-dir /tmp/cp-x        # PNGs, no ffmpeg, no audio FIFO
mkfifo /tmp/cp-x/a.pcm
MODE=test SOURCE=compositor AUDIO_SOURCE=pipe:/tmp/cp-x/a.pcm DURATION=25 RUN_DIR=/tmp/cp-x bash stream/run.sh   # local HLS
$PYTHON validate/hls_probe.py --url /tmp/cp-x/hls/index.m3u8 --out /tmp/cp-x/probe
```

CLI: `--self-test N` · `--audio-fifo PATH` (default: `AUDIO_SOURCE=pipe:PATH` from env) · `--no-audio` ·
`--run-dir DIR` · `--fps N` (30; 24 is the fallback, block becomes 2000 samples) · `--frames N`.
Test hooks (env, never in production): `KL_FAULT_PANELS=key,key` (render raises), `KL_SLOW_PANELS=key`
(35 ms sleep per render), `KL_ROUND_S=6` (short rounds), `KL_CHANGELOG=/tmp/x.md` (redirect the append),
`KL_SELFTEST_REALTIME=1` (pace `--self-test` at real fps). Guards: any of these or `--self-test`/`--frames` pointed
at a canonical live run dir exits 2; stream mode into a canonical dir needs `KL_LIVE=1` or an explicit `--run-dir`
(section 9). `KL_HOT_RELOAD=0` turns the panel/scene hot reloader off.

Python is **3.9**: `from __future__ import annotations`, no `match`, no `X | Y` at runtime; pillow 11.3,
numpy 2.0, websockets, requests, stdlib only.

---

## 1. Frame loop (what the compositor does every frame)

```
now = time.time()                       (self-test: virtual clock, t0 + frame/fps)
store.refresh(now)                      re-read state.json / chat.jsonl / activity / metrics / chat_stats, <= every 250 ms
new = store.drain_chat()                normalised chat records not seen before
classified = bridge.ingest(new, now, ctx)
engine.tick(now, ctx, classified)       round lifecycle + state.json writes (caught: a raise is logged, loop continues)
blk = audio.block(frame, ctx)           1600 x 2 int16, scope panel reads it via ctx.audio_block
ctx = store.ctx(now, frame, fps, **extras)   see section 3
for panel in slots (header panels LAST so the thumbnail is always drawn over everything):
    key = panel.inputs(ctx)             raise -> placeholder, logged once
    if key != last_key: img = panel.render(ctx, size); paste onto the canvas   raise -> placeholder, logged once
write rgb24 bytes -> video queue -> stdout ; blk.tobytes() -> audio queue -> FIFO
```

* Wallclock pacing. If the loop falls >= 1 frame behind, the last frame is re-sent (with a fresh audio
  block) rather than drifting; counted in `compositor.dropped_frames`.
* Frame-time guard: a panel whose `render()` takes > `budget_ms` (`compositor.PANEL_BUDGET_MS` = 28, or the panel's own `budget_ms`) for 30 consecutive renders
  is replaced by the placeholder for 300 frames, logged to stderr and `$ACTIVITY_FILE`
  (`actor: compositor`), then retried once.
* Static watchdog: 30 identical frames in a row -> one activity line (`watchdog: ... nothing is moving`).
* Both writers run in their own threads with bounded queues. The FIFO `open()` blocks in its thread until
  ffmpeg opens the read end (that is the avtest pattern; never open the FIFO on the main thread).
  A closed pipe -> `BrokenPipeError` in the writer -> `running=False` -> clean exit with a report line.

Measured (this Mac, 17 panels, seeded state + chat, MODE=test with ffmpeg running): render ms
avg 7.5, p95 14.4, max 39 (frame 0, font loading); 750 frames in 25 s, 0 dup, 0 dropped, speed 1.00x.

---

## 2. Panel API (exact)

```python
from PIL import Image, ImageDraw
from stream import layout as L
from stream.panels import Panel, register

class Panel:
    key: str            # unique; shown on the placeholder if the panel fails
    region: str         # a key of L.LAYOUT; render() receives that box's (w, h)
    budget_ms = None    # per-render budget in ms; None -> compositor.PANEL_BUDGET_MS (28)

    def inputs(self, ctx) -> hashable:      # cache key; render() runs only when this changes (compared with ==)
    def render(self, ctx, size) -> Image.Image:   # mode "RGBA", exactly `size` (smaller is padded, larger is cropped)
```

Rules:
1. `render()` is called only when `inputs()` changes. Return a cheap tuple of strings/ints/bools. Put
   `ctx.frame` in the tuple only if the panel really must redraw every frame (ticker, scope, cursor) and
   keep your own cache for the expensive parts (pre-rendered text strip, etc.).
2. Never call `time.time()`; use `ctx.now` (float epoch) and `ctx.frame` (int). The self-test runs on a
   virtual clock and must be deterministic.
3. Never draw outside your region; never touch another panel's region; never read files (use ctx).
4. Nothing under 20 px. Body text 22 px. Use `L.font(name, size)` with names
   `AB` (Arial Black), `HN`, `HN Medium`, `HN Bold`, `Menlo`, `Menlo Bold`. `L.truncate` / `L.wrap`
   to fit; `L.strip_non_bmp` before drawing user text (ChatBridge already does it for `text_clean`).
5. Nothing flashes faster than 1 Hz. Ease over 8-10 frames; the typewriter is the only thing that jumps.
6. A raise in `inputs()` or `render()` -> `placeholder(size, key, note)` (dark box with viewer words from `PLACEHOLDER_WORDS`, e.g. `chat is catching up…`; the traceback goes to the log) for 300
   frames, one stderr line + one activity line. The loop never dies because of a panel.
7. Colours: `L.COLORS[...]`, accent = `L.preset(ctx.preset)["accent"]`, username colours
   `L.name_color(name, ctx.preset)`. Never invent a hex; `!theme` only picks from `L.PRESETS`.
8. Module = one file in `stream/panels/`, auto-imported by `discover()`; end with `register(MyPanel())`.
   An import error is logged and skipped, never fatal. Registering a second panel with an existing key
   REPLACES it (that is how a Modules-phase panel takes over a spine placeholder: same `key`, same `region`).

### Regions (`L.LAYOUT[key]["box"]` = (x, y, w, h); font/size = the region's primary text)

PIP HOLLOW layout (WORLD.md 5). The header and footer kept their CONCEPT 3 geometry; the middle of the frame is the world.

| key | box | font | panel (stream/panels/) |
|---|---|---|---|
| `header_left` | 0,0,300,66 | HN Medium 22 | header.py: `atleastonce` / `PIP HOLLOW` wordmark + chat-link dot |
| `header_center` | 300,0,620,66 | AB 56 / AB 40 / Menlo 24-20 | header.py: `3 AWAKE` (`NOBODY AWAKE`, `-- AWAKE` before the world boots), `· N HATCHED`, `NEXT EVENT mm:ss`, keeper carving line |
| `header_right` | 920,0,360,66 | Menlo 22 | header.py: version string, LIVE dot + real viewers or `--` |
| `countdown` | 0,66,1280,6 | none | countdown.py: bar shrinking right-to-left; amber < 30 s, red < 10 s |
| `world` | 0,72,1280,440 | Menlo 20/22, HN Medium 22, AB 56 | world.py: the CaveScene (320x110 sim at 4x) + the screen-scale text layer (plank, labels, bubbles, platform letters/counts) |
| `colony` | 0,512,420,144 | HN Medium 22/20, Menlo 22/20 | colony.py: hatched count + milestone bar, `N awake · M asleep`, 8 s rotation |
| `keeper` | 420,512,420,144 | HN Medium 22, Menlo 22/20 | keeper.py: `keeper on duty` / off duty, carving or last carved line, failure lines only on failure |
| `chat_log` | 840,512,440,144 | Menlo 22, 26 px lines | chat_log.py: last 5 moderated messages past the hold, letter chip, shield chip |
| `ticker` | 0,656,880,64 | HN Medium 24 | ticker.py: crawl of events / ships, chamber carves, the honesty line, the verb legend |
| `scope` | 880,656,160,64 | none | scope.py: polyline of `ctx.audio_block[:,0]`, 144 px wide |
| `readout` | 1040,656,240,64 | Menlo 20 | readout.py: `chat 0.4/m · 2 ppl` / `30fps 11ms 01:23`; `state: stale`, `audio: fallback`, `world: glow off`, honesty violations |

Removed with the pivot (`L.REMOVED_REGIONS`, a panel registering one is refused): `stage`, `stage_title`, `stage_step`,
`stage_body`, `activity_feed`, `ballot`, `chat_pinned`, `chat_pane`, `founders`, `ask_card`, `next_up`. The composite key
`header` (0,0,1280,66) remains for a panel that wants the whole strip. World geometry constants: `L.WORLD_PLANK_XY`,
`L.WORLD_BUBBLE_MAX_W`, `L.WORLD_DENSITY_FALLBACK`. The world contract (scene, entities, events, commands) is
`stream/WORLD_API.md`.

### Worked example panel

```python
"""stream/panels/my_counter.py - replaces the spine's founders strip with a vote counter."""
from __future__ import annotations
from PIL import ImageDraw
from stream import layout as L
from stream.panels import Panel, register

class VoteCounter(Panel):
    key, region = "founders", "founders"          # same key + region as the spine panel -> takes over

    def inputs(self, ctx):
        # redraw only when the count, the kill switch or the palette changes
        return (ctx.vote_count, ctx.chat_display, ctx.preset)

    def render(self, ctx, size):
        w, h = size
        img = self.base(size)                     # panel fill + 1 px hairline top border, RGBA
        d = ImageDraw.Draw(img)
        accent = L.preset(ctx.preset)["accent"]
        txt = "chat hidden by mod" if not ctx.chat_display else "%d vote%s this round" % (
            ctx.vote_count or 0, "" if ctx.vote_count == 1 else "s")
        d.text((L.PAD, 3), L.truncate("Menlo", 20, txt, w - 2 * L.PAD), font=L.font("Menlo", 20), fill=accent)
        return img

register(VoteCounter())
```

---

## 3. `ctx` — the read-only snapshot (StateStore.ctx + compositor extras)

`ctx.<missing>` returns `None`, never raises; `ctx.get(name, default)` exists. Treat it as read-only.

| attribute | type | source / meaning |
|---|---|---|
| `now` | float | epoch seconds, passed in by the loop (virtual in self-test) |
| `frame` | int | frame index since start |
| `fps` | float | target fps (30 or 24) |
| `state` | dict | the whole parsed state.json (defaults merged in) |
| `stale` | bool | `state.updated_ts` older than 10 s or unreadable |
| `updated_t` | float/None | epoch of `state.updated_ts` |
| `session` | dict | `{id, started_ts, ending}` |
| `version` | dict | `{string, major, macro, micro, commit, shipped, failed}` |
| `round` | dict | `{number, phase: open/closing/ship, opened_ts, deadline_ts, options[], last_result}` |
| `round_remaining` | float/None | `deadline - now` (negative after the deadline until the ship lands) |
| `round_opened_t`, `round_deadline_t` | float/None | epochs |
| `micro` | dict | `{palette, canvas_scene, canvas_rule, canvas_seed, audio_tempo, audio_pattern, ticker_speed, header_tagline, typewriter_cps, scope_style, stage_default, chime_variant}` |
| `theme` | dict | `{preset, set_by, set_ts, cooldown_until}` |
| `preset` | str | `theme.preset` (fallback `micro.palette`, then `kick`) -> use `L.preset(ctx.preset)` |
| `macro` | dict | `{active, title, requested_by, module, started_ts, deadline_ts, step, step_index, step_label, file, status_lines[], last_reload}` |
| `agent` | dict | `{on_duty, heartbeat_ts, name}` |
| `ideas` | list | `[{id, text, by, ts, plus, class: pending/instant/macro/declined, status: open/queued/shipped/declined, reason}]` |
| `ask` | dict | `{enabled, current, queue[], last}` |
| `chat_cfg` | dict | state.chat: `{display, connected, founders[], msgs_per_min_5m, unique_chatters_5m}` |
| `mod` | dict | `{paused, hidden_users[], actions[]}` |
| `founders` | list[str] | ChatBridge's session founders (falls back to state.chat.founders) |
| `metrics` | dict | `{is_live, viewer_count, viewer_peak, polled_ts, poll_ok, title, source}` from the LAST line of metrics.jsonl; `poll_ok` False when older than 60 s -> draw `--` |
| `chat_stats` | dict | chat_stats.json as written by the listener (`msgs_per_min_5m`, `unique_chatters_5m`, `connected`, ...) |
| `chat` | list | last 10 MODERATED messages past their 3 s hold (see message dict below) |
| `chat_raw` | list | last 20 normalised, unmoderated records (do not draw names from this) |
| `activity` | list | last 8 `{ts, actor, text}` of activity.jsonl |
| `ships` | list | last 10 lines of ships.jsonl (ticker patch notes) |
| `audio_cfg` | dict | state.audio `{source, tempo, pattern, muted_plucks}` |
| `compositor` | dict | state.compositor as last written (5 s old) |
| `compositor_live` | dict | the live counters: `fps_target, fps_actual, frame_ms_avg, frame_ms_p95, dropped_frames, scene, uptime_s, panels_disabled[]` |
| `scene` | str | `BUILDING` / `STATUS` / `SHIP` / `ATTRACT` (CANVAS/ANSWERING/CREDITS are Modules-phase) |
| `tallies` | dict | `{"A": [names...], "B": [...], "C": [...]}` in vote order, current round |
| `vote_count` | int | total votes this round |
| `recent_votes` | list | `[(name, letter, t)]`, last 5 |
| `notice` | tuple/None | `(text, level)` pinned-strip override (4 s), e.g. `("theme cooldown 41 s", "warn")` |
| `help_until`, `stats_until` | float | epoch until which the legend / stats card shows |
| `chat_display` | bool | kill switch (`!kill`); when False draw `chat hidden by mod` instead of any name |
| `mod_paused` | bool | `!pause` |
| `builders` | dict | builders.json `{name_lower: {n, first_seen, sessions, votes, ships, name}}` |
| `new_builders` | int | count of first-ever chatters this run (audio cue) |
| `audio_block` | np.ndarray/None | this frame's (1600, 2) int16 block |
| `audio_level` | float/None | RMS dBFS of that block |
| `audio_source` | str | `fifo` / `fallback` (run.sh aevalsrc bed carries audio) / `none` |

Message dict (in `ctx.chat`, and what `ChatBridge.ingest` returns):

```
{id, ts, t (epoch), name, text (raw), text_clean (URL-stripped, non-BMP-stripped, emotes -> :name:, capped),
 color, badges[], source: pusher|webhook, type,
 kind: vote|idea|theme|stats|help|ask|mod|plain, arg (idea text / theme preset / ask question), letter (A|B|C for votes),
 accepted (bool: vote counted / theme applied / command not on cooldown), notice (str|None), dropped (bool),
 display_name (name, or "builder #N" when the username hits the blocklist), builder_n (int|None), first_ever (bool),
 show_t (t + 3 s hold)}
```

---

## 4. StateStore

```python
StateStore(run_dir, log=None, state_file=None, chat_file=None, activity_file=None, metrics_file=None)
.refresh(now, force=False) -> bool      # throttled to 250 ms; never raises
.ctx(now, frame, fps, **extra) -> Ctx
.drain_chat() -> list[msg]              # new normalised records since the last drain (de-duped on id)
.state -> dict ; .set_state(d) ; .ensure_state_file(now) ; .stale ; .ships ; .activity ; .metrics ; .chat_stats
write_state_atomic(path, d)             # tmp + os.replace ; iso_to_epoch(s) ; epoch_to_iso(t, ms=True)
run_path(run_dir, "STATE_FILE", "state.json")   # env.sh paths win only when $RUN_DIR == run_dir
```

Files: `$STATE_FILE`, `$CHAT_FILE` (both record shapes, de-dup on `id`, `name = username||user`,
`text = content||text`, `broadcaster: true` adds the badge), `$RUN_DIR/chat_stats.json`, `$METRICS_FILE`
(last line), `$ACTIVITY_FILE` (tail 50), `$RUN_DIR/ships.jsonl` (tail 20). On boot a jsonl is read from
its last 256 KiB only. A missing or half-written file keeps the last good value. A default state.json is
written when absent.

---

## 5. ChatBridge

```python
ChatBridge(run_dir, log=None, blocklist_path=None)      # default stream/moderation/blocklist.txt, hot-reloaded every 5 s
.ingest(msgs, now, ctx) -> list[msg]      # classify + moderate; votes count instantly; returns classified copies
.visible(now, n=10) -> list[msg]          # moderated, past the 3 s hold, newest last; [] when display is off
.tallies() -> {"A": [...], "B": [...], "C": [...]} ; .vote_count() -> int ; .recent_votes(n=5)
.reset_round(opened_t)                    # RoundEngine calls it; keeps only votes cast at/after opened_t
.notice(now) -> (text, level) | None ; .help_until ; .stats_until   # a same-frame `@name voted A` ack (1.5 s) wins over the regular notice
.founders -> list[str] ; .builders -> dict ; .builder_n(name) ; .flush(now, force=False)   # builders.json
.display ; .paused ; .hidden (set of lowercase names) ; .dropped (blocklist hits) ; .mod_actions
ChatBridge.classify(text) -> (kind, arg, letter)   # static; vote iff trimmed text matches ^!?[abc]$ (case-insensitive)
ChatBridge.clean_text(text, cap) -> str
```

Moderation stub (CONCEPT 7.1 subset, order): 3 s hold -> hidden/paused -> URL -> `[link]` -> non-BMP +
emote normalisation -> blocklist on text (drop + `dropped` counter) -> blocklist on username (`builder #N`)
-> length cap 120/60/140 -> per-user render rate 1 per 2 s (votes still count) -> `chat.display`.
Mod commands (`!hide/!unhide/!pause/!resume/!clear` for broadcaster or moderator badge, `!kill/!unkill`
broadcaster only) act immediately and are mirrored to `state.mod` by RoundEngine.
History: records already in chat.jsonl at boot are ingested for founders/builders/tallies but their
`!idea`/`!theme` commands are NOT re-applied (the previous compositor instance already did).

---

## 6. RoundEngine

```python
RoundEngine(run_dir, store, bridge, log=None, round_s=180.0, changelog_path=None, closing_s=150.0, ship_hold_s=5.0)
.tick(now, ctx, chat) -> None      # once per frame; chat = the list ChatBridge.ingest returned this frame
.open_round(s, now, exclude_param=None) ; .ship(s, now) ; .apply_option(s, opt, picked_by) ; .draw_options(s, exclude_param)
MENU: list of {"param", "values", "title"}   # option id "micro.<param>.<value>"; idea options are "idea.<idea id>"
```

Lifecycle: `open` (0-150 s) -> `closing` (150-180 s) -> `ship` (5 s, `round.phase == "ship"`, scene SHIP)
-> next `open`. Ship = tally (`bridge.tallies()`), winner or random agent pick (`agent_pick: true`,
`picked_by: null`), `apply_option` (sets `state.micro[param]`, palette also `state.theme.preset`, tempo also
`state.audio.tempo`), version `micro += 1`, `shipped += 1`, `commit` = `git rev-parse --short HEAD`,
append `$RUN_DIR/ships.jsonl` `{ts, version, kind, option_id, title, picked_by, agent_pick, ok, commit, error, votes, total_votes}`,
append one line to `docs/CHANGELOG.md`, one activity line (`actor: ship`), `round.last_result`.
Next options: 1 from `state.ideas` with `class == "instant"` and `status == "queued"` if any, the rest from
MENU excluding the parameter that just shipped. The RoundEngine is the ONLY writer of state.json inside
the compositor process; it re-reads the store copy before every write so fields owned by other
processes (`macro.*`, `agent.*`, `ideas[].class`, `ask.*`) survive, and refreshes `updated_ts` at least
every 5 s (that is the stale heartbeat). Spine MENU: palette, audio_tempo, ticker_speed, header_tagline.
Adding parameters = adding MENU entries (+ a branch in `apply_option` when the value must land outside `micro`).

---

## 7. AudioEngine

```python
AudioEngine(sr=48000, block=1600, fps=30.0, log=None)
.block(frame_index, ctx) -> np.ndarray   # int16, shape (block, 2); never raises (silence on internal error)
.last_block ; .level_dbfs ; .trigger(name, **kw)   # "vote" (semitones=), "ship", "fail", "builder"
```

One frame = one block, written to the FIFO in lockstep, so A/V cannot drift. The rich synth replaces the
internals only; keep the signature, the shape, `last_block` and `level_dbfs` (the scope and readout use
them). Detection is ctx-driven: `ctx.vote_count` growth -> vote blip (+1 semitone per vote in the round),
`ctx.version["string"]` change -> ship chime, `ctx.new_builders` growth -> builder notes. Master: tanh soft
limiter into a -6 dBFS ceiling. Spine bed measured -24 dBFS RMS, 0.09 ms per block.

Example layer (how to add a sound without touching the loop):

```python
class MyLayer(object):
    def __init__(self, sr, n): self.sr, self.n, self.pos = sr, n, 0
    def render(self, ctx) -> np.ndarray:            # float64 (n,) in -1..1, added to the mix before the limiter
        t = (self.pos + np.arange(self.n)) / self.sr
        self.pos += self.n
        tempo = float((ctx.micro or {}).get("audio_tempo") or 85) if ctx is not None else 85.0
        beat = (t * tempo / 60.0) % 1.0
        return 0.05 * np.sin(2 * np.pi * 55 * t) * np.exp(-8.0 * beat)   # a soft 55 Hz kick on every beat
```

Bypass: `run.sh AUDIO_SOURCE=generated` (aevalsrc bed) needs no FIFO; the compositor then reports
`audio_source = "fallback"` and the readout says `audio: fallback`. `--self-test` runs with no FIFO at all.

---

## 8. state.json (CONCEPT 8.1) — who writes what

| block | writer | notes |
|---|---|---|
| `updated_ts` | RoundEngine | every write, at least every 5 s; stale if > 10 s |
| `session` | RoundEngine (boot), `scripts/stop.sh --credits` (`ending`) | |
| `version` | RoundEngine | `string = v{major}.{macro}.{micro}`; `commit` = short hash at ship time |
| `theme` | RoundEngine (`!theme`, palette ship) | `cooldown_until = set_ts + 60 s` |
| `round` | RoundEngine | `options[].votes/voters` mirrored from ChatBridge whenever they change |
| `micro` | RoundEngine (`apply_option`) | hot-applied by panels via `ctx.micro` |
| `macro`, `agent` | the building agent (outside the compositor) | RoundEngine preserves them |
| `ideas` | RoundEngine appends (`class: pending`, `status: open`); the agent sets `class`/`status`/`reason` | |
| `ask` | responder process | RoundEngine preserves it |
| `chat` | RoundEngine from ChatBridge + chat_stats.json | `display` is the kill switch |
| `mod` | RoundEngine from ChatBridge | |
| `metrics` | RoundEngine from metrics.jsonl | never typed by hand |
| `audio`, `compositor` | RoundEngine from the loop's counters | |

Other run-dir files: `chat.jsonl` (listener + webhook receiver append), `activity.jsonl` (`{ts, actor, text}`,
anyone appends via `kl_activity`), `metrics.jsonl`, `chat_stats.json`, `ships.jsonl`, `builders.json`
(ChatBridge, atomic, flushed every 10 s), `selftest/frame_XXXX.png`, `hls/` (MODE=test), `.hotreload/`
(py_compile scratch for the hot reloader), `state.json.lock` (flock taken by `write_owned`).

### 8.1 Write ownership (`state_store.write_owned`) — one file, several writers, no adoption

Journal 012: a test run against the shared dir wrote `version.*` / `round.*` into the live state.json and the live
RoundEngine adopted them, because every writer re-read the WHOLE file and wrote the WHOLE file back. From now on
each writer only ever writes the paths it owns:

| owner (process) | owned paths (`state_store.OWNED_PATHS[...]`) |
|---|---|
| `rounds` — RoundEngine, inside the compositor | `session`, `version`, `round`, `micro`, `theme`, `ideas[+]` (append), `ideas[].id/text/by/ts/plus/status` |
| `compositor` — the loop's mirrors, written by the RoundEngine on its behalf (same process) | `compositor`, `chat`, `mod`, `metrics`, `audio` |
| `agent` — `agents/duty.py`, a separate process | `agent`, `macro`, `ask`, `ideas[].class`, `ideas[].status`, `ideas[].reason` |
| `stop` — `scripts/stop.sh --credits` | `session.ending` |

`ideas[].status` is shared on purpose: rounds writes `open`/`shipped`, the agent writes `queued`/`declined`; the
value rule stays in rounds (`declined` wins unless already `shipped`). `updated_ts` is the heartbeat and is
refreshed by every write.

```python
from stream.state_store import write_owned, OWNED_PATHS
write_owned(path, owned_paths, updates, log=None, now=None, strict=False, base=None) -> dict   # the merged file as written
```
`write_owned` takes an flock on `<path>.lock`, re-reads the file from disk, sets ONLY the dotted paths in `updates`
(each must be covered by `owned_paths`, else it is dropped and logged; `strict=True` raises), refreshes
`updated_ts`, writes atomically (tmp + `os.replace`) and returns the merged dict. Missing/corrupt file -> `base`
(pass `default_state(...)`) or `{}`. Path grammar: `round.number`, `ideas.3.status` (index), `ideas[i-0002].class`
(element by `id`), `ideas[+]` (append, last segment only). Owned patterns: a bare block (`round`) covers everything
under it, `ideas[]` matches any element.

**Change rounds.py must make (owner of rounds.py, next phase):** replace `_write()`'s
`_merge_foreign(s, disk) + write_state_atomic(state_file, s)` with

```python
merged = write_owned(self.store.state_file, OWNED_PATHS["rounds"] + OWNED_PATHS["compositor"],
                     {"session": s["session"], "version": s["version"], "round": s["round"], "micro": s["micro"],
                      "theme": s["theme"], "chat": s["chat"], "mod": s["mod"], "metrics": s["metrics"],
                      "audio": s["audio"], "compositor": s["compositor"]},
                     log=self.log, now=now, base=s)
# new ideas: {"ideas[+]": idea} at the moment they are appended; a status flip: {"ideas[%s].status" % idea_id: "shipped"}
self.store.set_state(merged)          # adopt the merged file (agent.*, macro.*, ask.*, ideas[].class come from disk)
```
so the engine never adopts `version.*`/`round.*` from disk again (its in-memory copy is authoritative for its own
paths) while everything the agent owns is read back from the merged result. `_merge_foreign` then goes away.
`agents/duty.py` makes the mirror change: `mutate()` -> `write_owned(state_path, OWNED_PATHS["agent"], {...})`
(its current read-modify-write of the whole file can still resurrect stale round/version fields it read a moment earlier).

---

## 9. Run-dir guard and hot reload (compositor.py)

**Run-dir guard** (exit 2, message on stderr, before anything is written). Canonical LIVE dirs:
`~/.local/share/kick-live/run`, `~/.local/share/kick-live/run-live`, plus `$KL_LIVE_RUN_DIR`.

| invocation | run_dir canonical | result |
|---|---|---|
| `--self-test`, `--frames`, or any `KL_ROUND_S` / `KL_FAULT_PANELS` / `KL_SLOW_PANELS` / `KL_CHANGELOG` / `KL_SELFTEST_REALTIME` | yes | **refused** (even with `KL_LIVE=1`) |
| stream mode, run_dir inherited from `$RUN_DIR` | yes | refused unless `KL_LIVE=1` |
| stream mode, `--run-dir <canonical>` explicit | yes | allowed |
| anything | no (`/tmp/cp-*`) | allowed |

The live launcher (`stream/run.sh` via `scripts/start.sh` / `supervisor.sh`) starts the compositor with no
arguments, so a live start from this tree needs `KL_LIVE=1` in the environment (one line in `start.sh`, owner's
call). Related fix in `state_store.run_path`: env.sh derives `$STATE_FILE`/`$CHAT_FILE`/`$ACTIVITY_FILE`/`$METRICS_FILE`
from `$RUN_DIR` at `source` time, so `source env.sh; RUN_DIR=/tmp/cp-x python stream/compositor.py ...` used to write
`state.json` into the OLD dir. A file variable is now honoured only when it lives inside the resolved run dir;
the guard also refuses if any derived file would land in a canonical dir.

**Hot reload** (`HotReloader`, on by default, `KL_HOT_RELOAD=0` disables): `stream/panels/*.py`,
`stream/scenes/*.py` and `stream/world/*.py` are stat'ed every 2 s (wallclock). A changed file (settled >= 0.3 s) is
1. `py_compile`d into `$RUN_DIR/.hotreload/` — syntax error -> `hot reload REJECTED <file>: SyntaxError ... (line N); old module kept`
   (stderr + activity), nothing else happens;
2. executed as a NEW module object under its dotted name (the old object is kept for rollback); an import-time
   exception restores `sys.modules` and `PANEL_REGISTRY` -> `hot reload FAILED ... at import`;
3. every panel the module `register()`ed replaces its `Slot` (same key = same region, new key = new slot, headers
   stay last), caches reset, `KL_FAULT/SLOW` hooks re-applied, `rollback armed for 30 renders`;
4. a raise in `inputs()`/`render()` during those 30 renders -> `hot reload ROLLBACK <key>: ...; previous panel + module
   restored` (activity line) and the old panel renders the same frame; 30 clean renders -> `committed`.
A scene file re-executes the scene module, then every loaded panel module whose source mentions `stream.scenes`
(so the world panel rebinds to a fresh CaveScene, re-booted from world.json; its rollback list carries the scene module too).
A `stream/world/*.py` file is executed fresh under its name, the parent package attribute is rebound (so
`from stream.world import pips` sees the new module), then `stream.scenes.hollow` is re-executed as above.
`KL_TEST_PIPS` counts as a test hook for the run-dir guard. Counters: `ctx.compositor_live["hot_reload"]`
= `{reloads, rejected, rollbacks, last}`. Nothing here touches ffmpeg or the FIFO: a reload is invisible to the encoder.
Proven 2026-09-25 (isolated copy, `--self-test 500` paced with `KL_SELFTEST_REALTIME=1`): colour edit live at frame 121,
syntax error rejected, render-raise rolled back on the same frame, scene edit rebound `stage_*` and committed.
