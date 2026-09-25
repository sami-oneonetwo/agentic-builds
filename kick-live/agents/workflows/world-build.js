export const meta = {
  name: 'kick-live-world-build',
  description: 'Build PIP HOLLOW v1 (docs/WORLD.md) on the hardened compositor: world core, then parallel verbs/rounds/panels/audio/keepers, integrate to local HLS with a relay-held deploy, QA on real frames, fix',
  phases: [
    { title: 'Core', detail: 'cave sim, pips, behaviour, world.json, WORLD_API.md' },
    { title: 'Modules', detail: 'verbs, world events, panels+layout, audio, keepers+honesty' },
    { title: 'Integrate', detail: 'assemble, budget run, gates, HLS via relay, deploy test' },
    { title: 'QA', detail: 'stranger, honesty/legibility, art-rule review' },
    { title: 'Fix', detail: 'apply blocking fixes, re-prove' },
  ],
}
const ROOT = '/Users/sandy/Workspace/agentic-builds/kick-live'
const LIVE_RUN = '/Users/sandy/.local/share/kick-live/run-live'
const CANON_RUN = '/Users/sandy/.local/share/kick-live/run'
const CONTRACT = `
## Project contract (read fully; then cat the spec)
Repo: ${ROOT}. THE SPEC IS ${ROOT}/docs/WORLD.md — cat it in full before anything else; section numbers below refer to it. Also cat ${ROOT}/stream/COMPOSITOR_API.md (Panel/StateStore/AudioEngine/RoundEngine/ChatBridge contracts, write ownership, hot-reload, relay, run-dir guard) and skim ${ROOT}/docs/CONCEPT.md §5-§8 (palette, fonts, motion, audio plumbing, state.json) and ${ROOT}/docs/journal.md entries 011-015.
The platform is the HARDENED compositor already in ${ROOT}/stream/ (relay.py, hot-reload of stream/panels/* and stream/scenes/*, run-dir guard, write_owned, ported hotfixes). Build on it; do not fork it.

Rules:
- NEVER go live, never MODE=live, never touch STREAM_KEY. Test with --self-test (PNGs) or MODE=test (local HLS).
- NEVER write to ${LIVE_RUN} or ${CANON_RUN}. Use an ISOLATED run dir: prefix every command with RUN_DIR=/tmp/pip-<yourlabel> (env.sh honours it; the compositor guard refuses the live dirs in test mode anyway).
- HONESTY IS THE ART RULE (WORLD.md §1, §10, §11): every creature on screen is a real person who chatted. Synthetic pips exist ONLY under an explicit test flag (e.g. KL_TEST_PIPS=N) that the compositor refuses unless run_dir is a /tmp path and --self-test or MODE=test is active; assert every frame in normal mode that len(animate entities) == len(pips hatched from real chat records). No fake names, no padded counts, ever. No name is drawn before the 3 s hold + username blocklist clear (nameless seed). Absence is never punished; nothing dies.
- NO IP: invented names (pip, Hollow, keeper, glowmoss, seed, burrow, platform, chamber); angular side-view sprites in the name colour, no yellow default, no round faces, no multiplication/breeding (WORLD.md §6 art note, §13). Write/obey ${ROOT}/docs/art-rules.md.
- NEVER commit/push. Own ONLY your assigned files; others build concurrently.
- Bash preferred. Python = $PYTHON (~/.local/share/kick-live/venv/bin/python, **3.9**: from __future__ import annotations; no match; no X|Y at runtime; pillow 11, numpy 2, requests, websockets + stdlib only). ffmpeg $FFMPEG / $FFPROBE via env.sh. Fonts per CONCEPT §5.
- Performance: 1280x720 @ 30 fps; the world sim is 320x110 upscaled 4x (WORLD.md §6); target ≤ 10 ms/frame for the world at 20 pips, graceful-degrade ladder (glow → labels → bubbles) above budget, last-good-frame on any exception; text at screen scale only, ≥ 20 px; nothing flashes > 1 Hz; something moves every frame (drips, moss pulse, sleepers breathing).
- chat.jsonl has two record shapes (Pusher: username/content; webhook: user/text); normalise and de-dup on id (existing StateStore/ChatBridge do this — reuse).
- Every deliverable: real run, real output as evidence (frame paths, ms numbers, assertions passed). No unobserved success claims.
`
const BUILD_SCHEMA = { type: 'object', properties: {
  files: { type: 'array', items: { type: 'string' } },
  interface_notes: { type: 'string' },
  usage: { type: 'string' }, tested: { type: 'boolean' },
  test_evidence: { type: 'string' }, frame_ms: { type: 'string' },
  known_issues: { type: 'array', items: { type: 'string' } },
}, required: ['files', 'interface_notes', 'usage', 'tested', 'test_evidence', 'known_issues'] }
const VERIFY_SCHEMA = { type: 'object', properties: {
  verdict: { type: 'string', enum: ['pass', 'pass_with_fixes', 'fail'] },
  issues_found: { type: 'array', items: { type: 'string' } },
  issues_fixed: { type: 'array', items: { type: 'string' } },
  remaining: { type: 'array', items: { type: 'string' } },
  frame_grid_path: { type: 'string' }, evidence: { type: 'string' },
}, required: ['verdict', 'issues_found', 'issues_fixed', 'remaining', 'evidence'] }

phase('Core')
const core = await agent(`${CONTRACT}

## Assignment: the world core (WORLD.md §3, §6, §12 rows 1-4)
Files you own: ${ROOT}/stream/scenes/hollow.py, ${ROOT}/stream/world/__init__.py, ${ROOT}/stream/world/pips.py, ${ROOT}/stream/world/behaviour.py, ${ROOT}/stream/world/state.py, ${ROOT}/stream/WORLD_API.md, ${ROOT}/docs/art-rules.md.
- hollow.py: the cave sim per §6 (320x110 grid: ceiling with cave mouth at x 236-268 showing the REAL sky colour from the real local clock and the real moon phase; cavern; floor; soil with 16 burrow slots; three stone platforms at x 40/160/280; lantern chain at (300,0)-(300,10); glow buffer; drips that fall and land; glowmoss that pulses); renders a 320x110 RGB numpy frame each tick and upscales 4x with integer nearest (np.kron or repeat) into a 1280x440 image for the 'world' region; a CaveScene class with frame(ctx, size) matching how stream/scenes are consumed (read COMPOSITOR_API.md); graceful-degrade ladder + last-good-frame on exception; deterministic from a seed; terrain persistence (dug cells, moss) via state.py.
- pips.py: sprite generator per §6: 4 stencils × parts, hashed from the Kick username (colour, parts, motif seed), tiers (size rows), 2-frame walk, blink, curl/sleep frames, seed/egg 3 crack frames; reject-and-reseed rule for ugly/unreadable combos; cache by (name, tier, frame); --sheet writes pips_sheet.png for review.
- behaviour.py: seed drop at hashed x within 1 frame of a message record; NAMELESS until the hold clears (the caller tells it when a record is cleared); hatch; wander (20-40 px/s screen), face newest speaker, walk-to(target), hop, blink 4-7 s, brighten/dim energy (cosmetic), curl+sleep into a burrow after 20 min silence, wake on message with care-log playback hook; credits walk.
- state.py: world.json schema (§3 JSON example) in $RUN_DIR: pips keyed by lowercase username with immutable identity after hatch, energy, tier, sessions, minutes_present, first_seen, last_seen, care_log, gifts, words, bonds, nickname; terrain (dug cells, moss with planter/night); colony milestones; atomic writes (tmp+os.replace) + daily .bak; join with builders.json (#N); recompute counts from chat.jsonl by (session, owner) with a cursor, never increment on boot (014.2). Loader tolerates missing/corrupt files.
- WORLD_API.md: exact signatures and the flow: chat record → bridge (hold/filter) → behaviour events → sim → text layer; what the verbs/rounds/panels/audio agents call and receive (events list per frame, e.g. [{'type':'hatch','pip':...},{'type':'speak','pip':...,'text':...},{'type':'walk','pip':...,'to':'A'}]).
- art-rules.md: the §6 art note and §13 IP/entity rules, testable.
Test (RUN_DIR=/tmp/pip-core): a standalone harness renders 300 frames with KL_TEST_PIPS=12 synthetic pips (allowed only here) to /tmp/pip-core/frames/*.png; save pips_sheet.png; measure ms/frame at 12 and at 60 pips; downscale frame 299 to 320x180 and Read it: cave mouth sky, moss, pips visible; render one frame with 0 pips and confirm it is dark but not black (sky + moss visible). Reload world.json and prove identity is stable. Return the structured result; interface_notes must carry the exact API the module agents code against.`,
  { model: 'fable', label: 'core', phase: 'Core', effort: 'high', schema: BUILD_SCHEMA })
log(`core: ${core ? core.files.length : 0} files, ${core ? core.frame_ms : ''}`)

phase('Modules')
const API = core ? `\nCore interface_notes (code against these EXACTLY; also cat ${ROOT}/stream/WORLD_API.md):\n${core.interface_notes}\n` : ''
const MODULES = [
  { key: 'verbs', files: 'stream/chat_bridge.py (verb parser + world hooks only), stream/moderation/allowlist.txt',
    spec: `WORLD.md §4 and §11: exact-token verb regex; v1 verbs feed [@name], pet [@name], dig, plant, wave/sit/duck, name <word> (nickname may not equal any chatter's username; @username part never disappears), forget, !banish/!unbanish (mod-gated), plus the existing votes/!idea/!theme/!help/!stats/!hide/!pause/!kill. Rate limits per §4 with the refusal REASON emitted as a plank notice event. care_log entries for feed/pet/gift at sleeping/absent pips. FILTERED-NAME PATH EVERYWHERE (014.1): tallies() and every name the world draws must come from the filtered/held record; delete the raw-name path. Three-strikes rule. Emit world events per WORLD_API.md. Test with a seeded chat.jsonl (both shapes, dup ids, a URL, a slur, a blocklisted username, a mod !hide during the hold, 'sing' inside a sentence must NOT match) and show the event stream + refusals.` },
  { key: 'rounds', files: 'stream/rounds.py (MENU + world event effects only)',
    spec: `WORLD.md §8: replace the parameter MENU with world events (weather: glow-rain/lights-out/fog; colony_rule; feast; dig_site; music; light; chaos stays), embodied tally = pips standing on platforms A/B/C (read from world state via the API), zero-vote honest copy, event effects applied to the world through the core API, ships.jsonl/version unchanged. Keep chaos semantics. Unit-test a full round with 3 pips on platforms (test mode) → the right event fires and the world reacts.` },
  { key: 'panels', files: 'stream/layout.py (regions), stream/panels/world.py, stream/panels/colony.py, stream/panels/keeper.py, stream/panels/chat_log.py, stream/panels/header.py (56 px AWAKE count rework), and DELETE/disable the removed panels listed in §5 (stage_title, stage_step, stage_body, activity_feed, ballot, chat_pinned, chat_pane, founders, ask_card, next_up) so they no longer register',
    spec: `WORLD.md §5 exactly: new regions world (0,72,1280,440), colony (0,512,420,144), keeper (420,512,420,144), chat_log (840,512,440,144); header_center shows '3 AWAKE' at 56 px / 'NOBODY AWAKE' at 40 px, '· 17 HATCHED', 'NEXT EVENT 01:23'; header_right gets LIVE + viewers + version. panels/world.py is the TEXT LAYER over the cave: plank (rotation, notices, first light, last-five-visitors), pip labels (Menlo 20, hashed colour, only after hold), bubbles (Menlo 22, 3 lines, 6 s, one per pip), platform letters AB 56 + counts + last 3 names, wall scrolls (v1.1 ok), moss labels rotation, density fallback > 40 awake. colony/keeper/chat_log per §5 rows 6-8. All text ≥ 20 px, cached per string. Test --self-test with 12 synthetic pips (test mode) and with 0 pips; Read the frames; 320x180 downscale must show the awake count and a light source at 0 pips.` },
  { key: 'audio', files: 'stream/audio.py (world layers only)',
    spec: `WORLD.md §7: pad voice count = awake pips (drips-only at 0), drips plink, per-pip two-note motif from name hash on speak (max 6 chunks), hatch/wake/sleep/tier stings, pet duet, footsteps, event stings, lantern rattle on keeper build; keep -18 dBFS integrated with the limiter; measure with volumedetect; block cost < 1.5 ms. Keep AudioEngine.block(frame_index, ctx) and consume world events from ctx per WORLD_API.md.` },
  { key: 'keepers', files: 'agents/duty.py (world hooks only), stream/world/honesty.py, stream/world/keepers.py',
    spec: `WORLD.md §9 + §11: lantern states from agent.heartbeat_ts; plain-language build line; failure lines (3 traceback lines + reverting) only on failure; chamber carve on colony milestones (3/5/10/25/50 hatched) via the core API; !idea → wall scroll → duty.py classify maps to 'instant' (platform option next round) / 'carving next' / 'declined: reason' in world terms. honesty.py: the per-frame assertion module (animate entities == pips from real records; no label before hold; counts from len()) with a self-test that FAILS on a planted fake pip. Extend duty.py minimally (macro-start/done announce as keeper carving in the world; do not break existing commands).` },
]
const modules = (await parallel(MODULES.map(m => () => agent(`${CONTRACT}
${API}
## Assignment: ${m.key}
Files you own (do not touch others): ${m.files}
${m.spec}
Use RUN_DIR=/tmp/pip-${m.key}. Return the structured result with real evidence.`,
  { model: 'fable', label: `mod:${m.key}`, phase: 'Modules', effort: 'high', schema: BUILD_SCHEMA })))).filter(Boolean)
log(`modules done: ${modules.length}/${MODULES.length}`)

phase('Integrate')
const integrated = await agent(`${CONTRACT}
Core + module reports (honour their interfaces): ${JSON.stringify([core, ...modules].filter(Boolean).map(r => ({ files: r.files, interface_notes: r.interface_notes, known_issues: r.known_issues })), null, 1)}

## Assignment: integrate PIP HOLLOW and prove it as one running show
1. Read everything under ${ROOT}/stream/ (compositor.py, relay.py, layout.py, state_store.py, chat_bridge.py, rounds.py, audio.py, panels/*, scenes/*, world/*) and agents/duty.py. Reconcile every interface mismatch in the owning files. py_compile all. Confirm the removed panels no longer register and the new regions render.
2. RUN_DIR=/tmp/pip-integ. Seed chat.jsonl (both shapes) with ~30 messages from ~8 real-shaped users over time: first messages (hatch), votes (walk to platforms), feed/pet/dig/plant, a nickname, a URL, a slur, a blocklisted username, a dup id, a mod !hide during a hold, and 'sing' inside a sentence. Seed metrics.jsonl (viewer_count 2→4) and chat_stats.json.
3. --self-test 600 → frames; build a 3x3 grid (/tmp/pip-integ/grid.png) + last_frame.png + a 320x180 thumb. Read them. Confirm: seeds nameless during hold, names appear only after; slur/blocklisted user rendered as builder #N or dropped; hidden user burrowed; platforms show counts = pips standing; plank notices for refusals; bubbles ≤ 3 lines; every text ≥ 20 px; 0-pip frame dark-but-lit; honesty assertions pass; a planted fake pip makes the assertion fail (then remove it).
4. Budget: KL_TEST_PIPS=60 (test mode) for 300 frames — report ms avg/p95 and which degrade rung engaged.
5. MODE=test SOURCE=compositor via relay to local HLS for 40 s; at ~15 s run scripts/deploy.sh (compositor child restart under the relay): ffmpeg pid unchanged, playlist continuous, hls_probe PASS, relay repeated-frame count reported. Touch panels/world.py mid-run and prove hot reload.
6. Let a round complete with pips on platforms (KL_ROUND_S) → the world event fires; ships.jsonl line written; duty.py macro-start/done shows as keeper carving.
Fix every bug in the owning files. Return verdict, frame_grid_path, evidence.`,
  { model: 'fable', label: 'integrate', phase: 'Integrate', effort: 'high', schema: VERIFY_SCHEMA })
log(`integrate: ${integrated ? integrated.verdict : 'null'}`)

phase('QA')
const GRID = integrated && integrated.frame_grid_path ? integrated.frame_grid_path : '/tmp/pip-integ/grid.png'
const QA = [
  { key: 'stranger', prompt: `You are a bored stranger who clicked from the Kick directory at 11pm. Read the frames at ${GRID} and /tmp/pip-integ/last_frame.png and the thumb (regenerate into /tmp/pip-qa1 via --self-test with the integrator's seed if missing). Answer literally: within 60 s would I type something, and what makes me? Would I stay 10 minutes if I were the only one there? Would I come back tomorrow? What is confusing or ugly? Give pass/fail per WORLD.md §2.2 beat and the 3 highest-leverage changes, each measurable in chat_stats.json/metrics.jsonl.` },
  { key: 'honesty', prompt: `Audit honesty, moderation and legibility on the real frames at ${GRID} and the seeded chat.jsonl in /tmp/pip-integ: every creature maps to a seeded real-shaped record (list them); no name visible before its hold; the slur user and blocklisted username never drawn; the hidden user burrowed; counts equal len(); 320x180 thumb shows the awake count and a light at 0 pips (render a 0-pip frame); all text ≥ 20 px. Try to plant a fake pip via world.json and confirm the assertion refuses it. Pass/fail with evidence.` },
  { key: 'art', prompt: `Review ${ROOT}/docs/art-rules.md, the sprite sheet (find pips_sheet.png under /tmp/pip-core or /tmp/pip-integ), and the frames at ${GRID}. Are the pips visibly distinct from Thronglets and any known pet IP (angular, side-view, name colour, no yellow default, no round faces)? Does the cave read as a cave at 320x180? Is anything cheap-looking or unreadable at Kick's 3 Mbps encode? Pass/fail with concrete pixel-level fixes.` },
]
const qa = (await parallel(QA.map(q => () => agent(`${CONTRACT}\n\n## QA: ${q.key}\n${q.prompt}\nReturn structured pass/fail + blocking issues + suggestions.`,
  { model: 'fable', label: `qa:${q.key}`, phase: 'QA', effort: 'high', schema: { type: 'object', properties: {
    verdict: { type: 'string', enum: ['pass', 'fail'] },
    checks: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, pass: { type: 'boolean' }, evidence: { type: 'string' } }, required: ['name', 'pass', 'evidence'] } },
    blocking_issues: { type: 'array', items: { type: 'string' } }, suggestions: { type: 'array', items: { type: 'string' } },
  }, required: ['verdict', 'checks', 'blocking_issues', 'suggestions'] } })))).filter(Boolean)
const blocking = qa.flatMap(q => q.blocking_issues || [])
log(`QA: ${qa.map(q => q.verdict).join(',')}; blocking=${blocking.length}`)

let fixed = null
if (blocking.length) {
  phase('Fix')
  fixed = await agent(`${CONTRACT}
## Fix the blocking issues QA found, then re-prove
${blocking.map((b, i) => `${i + 1}. ${b}`).join('\n')}
Cheap high-value suggestions to weigh: ${JSON.stringify(qa.flatMap(q => q.suggestions || []))}
Fix in the owning files under ${ROOT}/stream/ or agents/. Do not regress honesty, legibility, motion, moderation, or the frame budget. Re-run: --self-test 300 into /tmp/pip-fix, rebuild the grid + thumb, re-run the honesty self-test, re-run MODE=test HLS + hls_probe. Return verdict + fixes + new frame_grid_path + evidence.`,
    { model: 'fable', label: 'fix', phase: 'Fix', effort: 'high', schema: VERIFY_SCHEMA })
}
return { core: core && core.files, modules: modules.map(m => m.files), integrated, qa, fixed }
