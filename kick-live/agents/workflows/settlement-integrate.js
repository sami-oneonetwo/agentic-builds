export const meta = {
  name: 'kick-live-settlement-integrate',
  description: 'Resume the LONGGRASS build from the files on disk: Integrate -> QA -> Fix (no gate/module reruns). For a fresh session after the original workflow cache is gone.',
  phases: [
    { title: 'Integrate', detail: 'assemble from disk, migration, pre-bake, HLS via relay, hot-reload test' },
    { title: 'QA', detail: 'stranger, honesty, art on real frames at three hours' },
    { title: 'Fix', detail: 'close blockers, re-prove' },
  ],
}
const ROOT = '/Users/sandy/Workspace/agentic-builds/kick-live'
const LIVE_RUN = '/Users/sandy/.local/share/kick-live/run-live'
const MODE = (args && args.mode) || 'v0'
const CONTRACT = `
## Contract (read fully, then cat the spec)
Repo ${ROOT}. THE SPEC IS ${ROOT}/docs/OPENWORLD.md — cat it in full. Art source of truth: ${ROOT}/docs/ART.md + ${ROOT}/stream/world/art/. Also ${ROOT}/stream/WORLD_API.md, ${ROOT}/stream/COMPOSITOR_API.md, ${ROOT}/docs/WORLD.md §2.1, §3.1-3.3, §8.3, §11, and journal entries 015-023 in ${ROOT}/docs/journal.md (the owner's verdicts and the fix-pass notes: HUD plates at top-left must not stack over settlers/labels; settlers slightly larger at 1x; keeper strip carries a plain explainer line; theme phrasing "kick colours" → !theme kick; camera follow/drift hand-over bug seen in /tmp/lg-integ contact sheets).
The world modules already exist on disk (built by earlier agents): stream/world/{terrain,nature,bake,camera,land,state,behaviour,keepers,honesty}.py, stream/scenes/steading.py, stream/panels/world.py + colony/header/keeper/readout/ticker copy, stream/chat_bridge.py verbs, stream/rounds.py, stream/audio.py, docs/gate/ (six gate frames + timings.json). Read their docstrings for interfaces; there are no agent reports to lean on.
Build target: ${MODE === 'v1' ? 'FULL v1 per OPENWORLD.md §13' : 'v0 PREVIEW per OPENWORLD.md §13 (painted land, camera DRIFT/FOLLOW at 1x, tint/wind/clouds/shadows, camps from migration, hatch, go, existing verbs)'}.
Rules: never go live; never write to ${LIVE_RUN} or ~/.local/share/kick-live/run; RUN_DIR=/tmp/lg-<label>; never commit; Python $PYTHON (3.9) via \`source ${ROOT}/scripts/env.sh\`; numpy+pillow only; honesty rules (OPENWORLD §12); no animate non-persons; no IP look-alikes; HUD text >= 20 px; night floor 0.55; layout.py geometry untouched (deploy is hot-reload); hollow.py + pips.py stay on disk for rollback. A settler sheet costs ~0.75 s: render off the frame loop (the 3 s hold covers it). Frame budget: scene avg < 12 ms at 0.75x with 60 test pips, ~8 ms at 1x with 20. Real evidence for every claim.`
const VERIFY_SCHEMA = { type: 'object', properties: { verdict: { type: 'string', enum: ['pass', 'pass_with_fixes', 'fail'] }, issues_found: { type: 'array', items: { type: 'string' } }, issues_fixed: { type: 'array', items: { type: 'string' } }, remaining: { type: 'array', items: { type: 'string' } }, frame_grid_path: { type: 'string' }, evidence: { type: 'string' } }, required: ['verdict', 'issues_found', 'issues_fixed', 'remaining', 'evidence'] }

phase('Integrate')
const integrated = await agent(`${CONTRACT}
## Assignment: integrate LONGGRASS from the files on disk and prove it as one running show
1. Read everything under ${ROOT}/stream/ and agents/duty.py; reconcile interface mismatches in the owning files; py_compile all; confirm the world panel creates a SteadingScene and hollow.py/pips.py remain for rollback.
2. RUN_DIR=/tmp/lg-integ2: copy ${LIVE_RUN}/world.json there (read-only source), run the schema-2 migration on it (guard must pass), pre-bake the ground for the current season. Seed chat.jsonl (both record shapes) with ~30 messages over time: first messages, "go river"/"go home", "plant a flower", "camp", "fire", "kick colours"/"theme kick", votes, feed/pet, a URL, a slur, a blocklisted username, a mod !hide during a hold, a dup id. Seed metrics/chat_stats.
3. --self-test 900 → frames at dawn/noon/23:00; grid.png + last_frame.png + three 320x180 tiles; Read them. Confirm: open warm land; camera follows awake settlers and never leaves everyone off-screen (fix the follow/drift hand-over); HUD plates never cover settlers or labels; tuft nameless during hold; names only after; hidden user never drawn; minimap honest; every text >= 20 px; honesty assertions pass; a planted fake creature is refused; keeper strip shows the explainer line.
4. Budget: KL_TEST_PIPS=60 at 0.75x for 300 frames — scene avg/p95 and degrade rung; and 20 pips at 1x.
5. MODE=test via relay to local HLS for 40 s: start with hollow as the scene, drop the world files in mid-run and prove the HotReloader swapped the scene live (log lines), relay never saw a gap, hls_probe PASS; then scripts/deploy.sh once and confirm ffmpeg pid unchanged.
6. Let a round complete with settlers at waystones → event fires; duty.py macro-start/done shows on the beacon/notice board.
Fix every bug in the owning files. Return verdict, frame_grid_path, evidence.`,
  { model: 'fable', label: 'integrate', phase: 'Integrate', effort: 'high', schema: VERIFY_SCHEMA })

phase('QA')
const GRID = integrated && integrated.frame_grid_path ? integrated.frame_grid_path : '/tmp/lg-integ2/grid.png'
const QA = [
  { key: 'stranger', prompt: `You are a bored stranger who clicked from the Kick directory at 11pm and you are the only one there. Read ${GRID}, /tmp/lg-integ2/last_frame.png and the tiles. The owner called the previous world "a prison... cold and stagnant" and wants open, warm, alive. Literally: at 0 awake, inviting living land or dead map? After my first message, did the land answer ME? Alone 60 s: what moves? Do "go river" and "plant a flower" work? Can I read what A/B/C do and see my vote count in ~3 s? Pass only if you'd stay 10 min alone and type twice.` },
  { key: 'honesty', prompt: `Audit OPENWORLD §12 on ${GRID} and /tmp/lg-integ2 (chat.jsonl, world.json): every named creature maps to a record; nameless tuft during hold; slur/blocklisted names never drawn; hidden-in-hold user never drawn raw; mod notices without targets; counts from len(); mark provenance; whole-map minimap, no fog of war; night floor >= 0.55 in the 23:00 frame (measure); planted fake creature refused. Pass/fail with evidence.` },
  { key: 'art', prompt: `Review against ${ROOT}/docs/ART.md: canonical settlers on the land (not the old pips); silhouettes readable at 1x and 320x180; settler size at 1x adequate; consistent light with the sun vector; tiles seamless; camps in builders' colours; HUD plates not stacking over the land's labels; anything cheap at 3 Mbps; anything resembling Thronglets/Pokémon/AoE assets. Pass/fail with pixel-level fixes.` },
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
Do not regress honesty, legibility, the night floor, motion at zero, the frame budget, or the hot-reload path. Re-render into /tmp/lg-fix2 (dawn/noon/23:00, 0 and 3 awake), rebuild grid + tiles, re-run the honesty self-test and a MODE=test HLS probe. Return verdict + fixes + new frame_grid_path + evidence.`,
    { model: 'fable', label: 'fix', phase: 'Fix', effort: 'high', schema: VERIFY_SCHEMA })
}
return { mode: MODE, integrated, qa, fixed }
