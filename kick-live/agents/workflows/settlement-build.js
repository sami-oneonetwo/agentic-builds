export const meta = {
  name: 'kick-live-settlement-build',
  description: 'Build LONGGRASS (docs/OPENWORLD.md) on the hardened compositor: gate frames first, then parallel modules, integrate, QA, fix. Art from stream/world/art (docs/ART.md).',
  phases: [
    { title: 'Gate', detail: 'terrain + nature + camera; six real frames + timing for the owner' },
    { title: 'Modules', detail: 'scene, behaviour, state/land, world panel, verbs, rounds, keepers, audio, copy' },
    { title: 'Integrate', detail: 'assemble, migration, pre-bake, HLS via relay, hot-reload deploy test' },
    { title: 'QA', detail: 'stranger, honesty, art on real frames at three hours' },
    { title: 'Fix', detail: 'close blockers, re-prove' },
  ],
}
const ROOT = '/Users/sandy/Workspace/agentic-builds/kick-live'
const LIVE_RUN = '/Users/sandy/.local/share/kick-live/run-live'
const MODE = (args && args.mode) || 'v0'   // 'v0' preview tonight, or 'v1' full
const CONTRACT = `
## Contract (read fully, then cat the spec)
Repo ${ROOT}. THE SPEC IS ${ROOT}/docs/OPENWORLD.md — cat it in full; section numbers below refer to it. Art source of truth: ${ROOT}/docs/ART.md and the generators in ${ROOT}/stream/world/art/ (cat ART.md and the module docstrings; run their examples). Also: ${ROOT}/stream/WORLD_API.md, ${ROOT}/stream/COMPOSITOR_API.md, ${ROOT}/docs/WORLD.md §2.1, §3.1-3.3, §8.3, §11 (still normative), journal entries 015-021.
Build target: ${MODE === 'v1' ? 'FULL v1 per OPENWORLD.md §13 (rows 1-8, 10, 12-15, v1 parts of 9 and 11)' : 'v0 PREVIEW per OPENWORLD.md §13: painted land (bake) + camera DRIFT/FOLLOW at 1x + tint/wind/clouds/shadows + camps from migration + hatch + go + the existing verbs; no new fields/raisings; rounds MENU may stay as is'}.
Rules: never go live; never write to ${LIVE_RUN} or ~/.local/share/kick-live/run; RUN_DIR=/tmp/lg-<label> for tests; never commit; Python $PYTHON (3.9) via \`source ${ROOT}/scripts/env.sh\`; numpy+pillow only; honesty rules (OPENWORLD §12: every name = real chatter; nature moves, nothing else moves itself; nameless tuft until the 3 s hold + username filter; counts from len(); mark provenance); no animate non-persons; no IP look-alikes; every HUD text >= 20 px; night floor 0.55; layout.py geometry untouched (deploy is hot-reload); keep hollow.py + pips.py on disk for rollback.
Frame budget (OPENWORLD §7.3): scene avg < 12 ms at 0.75x with 60 test pips (KL_TEST_PIPS, test mode only), ~8 ms at 1x with 20; measure on this Mac and report numbers.
MEASURED ART COSTS (docs/ART.md): a settler's 23-frame sheet costs ~0.75 s to render (31.9 ms/frame at 1x) — NEVER on the frame loop: pre-render sheets in a background thread at seed-drop time (the 3 s nameless hold covers it) and at boot for known settlers before the first frame; ground paint of a 40x27-tile window is 50 ms and region repaint 19 ms — bake in a background thread, never per frame; world compose with 20 settlers is ~2.2 ms. Design the scene so a hatch never stalls a frame (if a sheet is not ready when the hold clears, show the tuft one more beat rather than block).
Own only your assigned files; others build concurrently. Real evidence for every claim (frame paths, ms, assertion output).`
const BUILD_SCHEMA = { type: 'object', properties: { files: { type: 'array', items: { type: 'string' } }, interface_notes: { type: 'string' }, usage: { type: 'string' }, tested: { type: 'boolean' }, test_evidence: { type: 'string' }, frame_ms: { type: 'string' }, known_issues: { type: 'array', items: { type: 'string' } } }, required: ['files', 'interface_notes', 'usage', 'tested', 'test_evidence', 'known_issues'] }
const VERIFY_SCHEMA = { type: 'object', properties: { verdict: { type: 'string', enum: ['pass', 'pass_with_fixes', 'fail'] }, issues_found: { type: 'array', items: { type: 'string' } }, issues_fixed: { type: 'array', items: { type: 'string' } }, remaining: { type: 'array', items: { type: 'string' } }, frame_grid_path: { type: 'string' }, evidence: { type: 'string' } }, required: ['verdict', 'issues_found', 'issues_fixed', 'remaining', 'evidence'] }

phase('Gate')
const gate = (await parallel([
  () => agent(`${CONTRACT}
## Gate part A: terrain + nature + the six frames (OPENWORLD §13 gate, §4.1-4.2, §2.2, §7)
Files you own: ${ROOT}/stream/world/terrain.py, ${ROOT}/stream/world/nature.py, ${ROOT}/stream/world/bake.py (ground painter: paint the seeded map at 4 px/cell into a memory-mapped bake using the art atlas ground.paint; local repaint; bake_ver), ${ROOT}/docs/gate/ (frames).
Build terrain.py per §4.1 (seed → elevation/moisture → sea SE, site search, river traced downhill and carved, the Ford, biomes, passable/cost/caster, coarse BFS grid, places registry) and nature.py per §2.2/§4 (wind field from chat rate, cloud blobs, sun vector + tint by real hour with the 0.55 floor, tide, seasons by real date, growth by real days; the Markov weather chain may stub to rounds-only). Then render SIX 1280x720 frames FROM THESE MODULES + the art atlas (not the mockup scripts): dawn, noon, 23:00 × 0 awake and 3 awake (test pips at camps), current season, plus 320x180 tiles of each, into ${ROOT}/docs/gate/. Time the per-frame path (§7.3 steps 2-4: crop + modulation + sprite blit) at 1x and 0.75x with 20 and 60 test pips; report ms. If 23:00 reads cold, also render with world_day="hour" and say which you recommend. Return paths, timings, and the exact API terrain/nature/bake expose.`,
    { model: 'fable', label: 'gate:terrain-nature', phase: 'Gate', effort: 'high', schema: BUILD_SCHEMA }),
  () => agent(`${CONTRACT}
## Gate part B: camera + land/state schema 2 (OPENWORLD §4.3-4.5, §5)
Files you own: ${ROOT}/stream/world/camera.py, ${ROOT}/stream/world/land.py, ${ROOT}/stream/world/state.py (schema 2 + guarded migration only; keep every existing API).
camera.py: float centre in cells, zooms 0.75/1/1.5 as crop sizes, modes EVENT > MOOT > FOLLOW (2-axis lead room) > CLOSE > DRIFT (survey over real marks), 0.8 s damped spring, 60 cells/s cap, never a cut, zoom only at rest (crossfade may be a luminance dip), edge arrows data, 12-cell clamp, minimap data (whole map, walked saturated vs pale, N% walked from len()), persistence every 5 s. land.py + state.py: wear (never decrements), marks with owner provenance, camps ladder 1/2/5/10 sessions, fields, stones/ladder, raisings, land strips, weather, camera, bake_ver; migration 1→2 on a COPY with the identity/count guard (§5.4). Unit tests: camera never exceeds the cap or cuts across a 10 s scripted follow; migration of a copy of ${LIVE_RUN}/world.json passes the guard (read it, never write it). Return exact APIs.`,
    { model: 'fable', label: 'gate:camera-land', phase: 'Gate', effort: 'high', schema: BUILD_SCHEMA }),
])).filter(Boolean)
log(`gate done: ${gate.length}/2; frames under docs/gate/`)
const API = gate.map(g => g.interface_notes).join('\n---\n')

phase('Modules')
const MODULES = [
  { key: 'scene', files: 'stream/scenes/steading.py', spec: `OPENWORLD §7.3 + §13 row 1: the SteadingScene (bake load/crop/resample, modulation field, fixed-point multiply, glow after dusk, y-sorted live sprites from the art atlas at three zooms, particles (v1.1 ok), degrade ladder incl. pin zoom, last-good frame). Carry ~450 lines from hollow.py (ingest, history, persist, honesty check, entities, stats, command dispatch). Same class interface the world panel consumes (WORLD_API §9); scene name 'steading'.` },
  { key: 'behaviour', files: 'stream/world/behaviour.py', spec: `OPENWORLD §13 row 5: 2D targets with easing, BFS routes via terrain's coarse grid + slide rule + 3 s stuck detector, wander with Moot gravity, camps instead of burrows, waystone slots, carry (berry/stone), nameless tuft until hold, sleep/wake/credits semantics preserved; keep ~60% of the existing state machine.` },
  { key: 'world-panel', files: 'stream/panels/world.py', spec: `OPENWORLD §8 + §13 row 8: camera-aware text layer with culling; plank (16,84), land line (16,116), time dial (16,152) 64x64, minimap top-right (1120,88) 148x104 with walked fraction, waystone letters AB 56 + counts + names, plates/plaques/place labels, edge arrows, contrast chip; labels via the filtered-name path only; label placer from the cave carries over.` },
  { key: 'verbs', files: 'stream/chat_bridge.py (verb table + leading-verb rule only)', spec: `OPENWORLD §6: leading-verb rule (<=4 tokens, verb first, stop-words dropped, all remaining tokens known object words; "plant a flower" works, "go away" does not), go, plant <obj>, camp, fire, home, feed/pet/gift, A/B/C, emotes, name, forget, !idea/!theme, mods; ${MODE === 'v1' ? 'sow/harvest, stack, swim too' : 'sow/harvest/stack/swim may be stubbed with a friendly "comes in a later carving" refusal'}; refusals in amber with reasons; filtered names everywhere.` },
  { key: 'rounds-keepers-audio', files: 'stream/rounds.py (MENU + effects), stream/world/keepers.py (beacon, notice board), stream/audio.py (wind by chat rate, river/shore by camera distance, camp bells, footsteps by cell, sunrise/sunset bell, new stings)', spec: `OPENWORLD §9-§11: ${MODE === 'v1' ? 'full MENU and raisings via reveal masks' : 'MENU re-skin to weather/expedition/bonfire/light/music/chaos; beacon + notices; raisings v1.1'}; waystone tallies from creatures standing at waystones; audio beds; keep AudioEngine.block signature; -18 dBFS integrated.` },
  { key: 'copy-panels', files: 'stream/panels/colony.py, stream/panels/header.py (SETTLED count copy), stream/panels/keeper.py, stream/panels/readout.py, stream/panels/ticker.py (line), docs/art-rules.md, stream/WORLD_API.md, docs/WORLD.md (banner only)', spec: `OPENWORLD §8 + §13 rows 13 and 15: "the land" strip, header SETTLED/AWAKE copy, keeper strip copy, readout flags, ticker honesty line + legend; docs updates (SteadingScene, camera, atlas interface, new events; WORLD.md superseded banner per ADR-006).` },
]
const modules = (await parallel(MODULES.map(m => () => agent(`${CONTRACT}
Gate APIs (code against these exactly; also cat ${ROOT}/stream/WORLD_API.md and the gate modules):\n${API}
## Assignment: ${m.key}
Files you own (do not touch others): ${m.files}
${m.spec}
Test in isolation with RUN_DIR=/tmp/lg-${m.key} (seed state/chat as needed; KL_TEST_PIPS only in test mode). Return the structured result with real evidence.`,
  { model: 'fable', label: `mod:${m.key}`, phase: 'Modules', effort: 'high', schema: BUILD_SCHEMA })))).filter(Boolean)
log(`modules done: ${modules.length}/${MODULES.length}`)

phase('Integrate')
const integrated = await agent(`${CONTRACT}
Reports (honour interfaces): ${JSON.stringify([...gate, ...modules].map(r => ({ files: r.files, interface_notes: r.interface_notes, known_issues: r.known_issues })), null, 1)}
## Assignment: integrate LONGGRASS and prove it as one running show (OPENWORLD §14 deploy path in test)
1. Read everything under ${ROOT}/stream/ and agents/duty.py; reconcile interface mismatches in the owning files; py_compile all; confirm the world panel now creates a SteadingScene and hollow.py/pips.py remain on disk for rollback.
2. RUN_DIR=/tmp/lg-integ: copy ${LIVE_RUN}/world.json there (read-only source), run the schema-2 migration on it (guard must pass), pre-bake the ground for the current season into /tmp/lg-integ/bake/. Seed chat.jsonl (both shapes) with ~30 messages over time: first messages (walk out with name), "go river"/"go home", "plant a flower" (leading-verb rule), "camp", "fire", votes (walk to waystones), feed/pet, a URL, a slur, a blocklisted username, a mod !hide during a hold, a dup id. Seed metrics/chat_stats.
3. --self-test 900 → frames at dawn/noon/23:00 (force the clock via the nature test hook if present, else render three runs); build grid.png + last_frame.png + three 320x180 tiles; Read them. Confirm: land reads as open and warm; camera follows/drifts without cuts; tuft nameless during the hold; names only after; hidden user never drawn; minimap honest; every text >= 20 px; honesty assertions pass; a planted fake creature in world.json is refused.
4. Budget: KL_TEST_PIPS=60 at 0.75x for 300 frames — scene avg/p95 and degrade rung; and 20 pips at 1x.
5. MODE=test via relay to local HLS for 40 s; at ~15 s copy the world files into a scratch snapshot? No — test the HOT-RELOAD path itself: start with hollow as the scene, then drop steading.py/world.py into place mid-run and prove the HotReloader swapped the scene live (log lines), the relay never saw a gap, hls_probe PASS. Then also run scripts/deploy.sh once (child restart) and confirm ffmpeg pid unchanged.
6. Let a round complete with creatures at waystones → event fires; duty.py macro-start/done shows on the beacon/notice board.
Fix every bug in the owning files. Return verdict, frame_grid_path, evidence (ms, dBFS, probe, reload log lines).`,
  { model: 'fable', label: 'integrate', phase: 'Integrate', effort: 'high', schema: VERIFY_SCHEMA })
log(`integrate: ${integrated ? integrated.verdict : 'null'}`)

phase('QA')
const GRID = integrated && integrated.frame_grid_path ? integrated.frame_grid_path : '/tmp/lg-integ/grid.png'
const QA = [
  { key: 'stranger', prompt: `You are a bored stranger who clicked from the Kick directory at 11pm and you are the only one there. Read ${GRID}, /tmp/lg-integ/last_frame.png and the three tiles. The owner called the previous world "a prison... cold and stagnant" and wants open, warm, alive. Literally: at 0 awake, is this an inviting living land or a dead map? After my first message, did the land answer ME (creature walks out with my name, camera notices)? Alone 60 s: what moves? Do "go river" and "plant a flower" work? Can I read what A/B/C do and see my vote count in ~3 s? Pass only if you'd stay 10 min alone and type twice.` },
  { key: 'honesty', prompt: `Audit OPENWORLD §12 on ${GRID} and the seeded chat.jsonl + world.json in /tmp/lg-integ: every named creature maps to a record; nameless tuft during hold; slur/blocklisted names never drawn; hidden-in-hold user never drawn raw; mod notices without targets; counts from len(); mark provenance (every trail/flower/camp has a real owner); minimap shows the whole map with no fog of war; night floor >= 0.55 in the 23:00 frame (measure luminance); planted fake creature refused. Pass/fail with evidence.` },
  { key: 'art', prompt: `Review against ${ROOT}/docs/ART.md: are the creatures on the land the canonical art (not the old angular pips)? Silhouettes readable at 1x and at 320x180; consistent light direction with the sun vector; tiles seamless; camps/huts in builders' colours; anything cheap at 3 Mbps? Anything resembling Thronglets, Pokémon or Age of Empires assets? Pass/fail with pixel-level fixes.` },
]
const qa = (await parallel(QA.map(q => () => agent(`${CONTRACT}\n## QA: ${q.key}\n${q.prompt}\nReturn structured pass/fail + blocking issues + suggestions.`,
  { model: 'fable', label: `qa:${q.key}`, phase: 'QA', effort: 'high', schema: { type: 'object', properties: { verdict: { type: 'string', enum: ['pass', 'fail'] }, checks: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, pass: { type: 'boolean' }, evidence: { type: 'string' } }, required: ['name', 'pass', 'evidence'] } }, blocking_issues: { type: 'array', items: { type: 'string' } }, suggestions: { type: 'array', items: { type: 'string' } } }, required: ['verdict', 'checks', 'blocking_issues', 'suggestions'] } })))).filter(Boolean)
const blocking = qa.flatMap(q => q.blocking_issues || [])
log(`QA: ${qa.map(q => q.verdict).join(',')}; blocking=${blocking.length}`)
let fixed = null
if (blocking.length) {
  phase('Fix')
  fixed = await agent(`${CONTRACT}
## Fix every blocker, then re-prove
${blocking.map((b, i) => `${i + 1}. ${b}`).join('\n')}
Cheap suggestions worth taking: ${JSON.stringify(qa.flatMap(q => q.suggestions || []).slice(0, 12))}
Do not regress honesty, legibility, the night floor, motion at zero, the frame budget, or the hot-reload path. Re-render into /tmp/lg-fix (dawn/noon/23:00, 0 and 3 awake), rebuild grid + tiles, re-run the honesty self-test and a MODE=test HLS probe. Return verdict + fixes + new frame_grid_path + evidence.`,
    { model: 'fable', label: 'fix', phase: 'Fix', effort: 'high', schema: VERIFY_SCHEMA })
}
return { mode: MODE, gate: gate.map(g => g.files), modules: modules.map(m => m.files), integrated, qa, fixed }
