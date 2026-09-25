export const meta = {
  name: 'kick-live-world-qa-round',
  description: 'Re-run the three PIP HOLLOW QA lenses on fresh frames, then fix blockers; repeat up to N rounds until all three pass',
  phases: [{ title: 'Render' }, { title: 'QA' }, { title: 'Fix' }],
}
const ROOT = '/Users/sandy/Workspace/agentic-builds/kick-live'
const ROUNDS = (args && args.rounds) || 2
const CONTRACT = `
## Contract (read fully)
Repo ${ROOT}. THE SPEC is ${ROOT}/docs/WORLD.md; also ${ROOT}/docs/art-rules.md, ${ROOT}/stream/WORLD_API.md, ${ROOT}/stream/COMPOSITOR_API.md, and journal entries 015-018 in ${ROOT}/docs/journal.md.
Rules: never go live; never write to ~/.local/share/kick-live/run or run-live; use RUN_DIR=/tmp/pipqa-<label>; never commit; Python is $PYTHON (3.9) via \`source ${ROOT}/scripts/env.sh\`; honesty is the art rule (every creature = a real chat record; no name before the 3 s hold + username filter; counts from len()); no IP look-alikes; nothing under 20 px; something moves every frame.
THE BAR (owner, 2026-09-25): the previous text show was "very boring". The question every QA answers first is: **with ONE real viewer awake on a dead night, does this screen feel alive and worth typing into?** Judge the 1-awake and 0-awake frames as hard as the 6-awake frame.
`
const QA_SCHEMA = { type: 'object', properties: {
  verdict: { type: 'string', enum: ['pass', 'fail'] },
  checks: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, pass: { type: 'boolean' }, evidence: { type: 'string' } }, required: ['name', 'pass', 'evidence'] } },
  blocking_issues: { type: 'array', items: { type: 'string' } }, suggestions: { type: 'array', items: { type: 'string' } },
}, required: ['verdict', 'checks', 'blocking_issues', 'suggestions'] }
const FIX_SCHEMA = { type: 'object', properties: {
  verdict: { type: 'string', enum: ['pass', 'pass_with_fixes', 'fail'] },
  issues_fixed: { type: 'array', items: { type: 'string' } }, remaining: { type: 'array', items: { type: 'string' } }, evidence: { type: 'string' },
}, required: ['verdict', 'issues_fixed', 'remaining', 'evidence'] }

const RENDER = (label) => `${CONTRACT}
## Render fresh evidence frames (label ${label})
RUN_DIR=/tmp/pipqa-${label}. Seed chat.jsonl (both record shapes) so the run passes through: 0 awake for the first 90 frames (only sleepers from a prior session in world.json/builders.json), then ONE stranger's first message ("hello?"), then 60 s of that single person: a vote, "feed", "dig", "plant", "sing", a second message; then 4 more users arrive over 60 s with votes, a nickname, a URL, a slur, a blocklisted username, a mod !hide during a hold, a dup id. Also plant a fake pip in world.json before boot (it must be refused) and record what happened. Run --self-test for ~900 frames. Produce: /tmp/pipqa-${label}/f_0awake.png (frame ~60), f_1awake_first.png (first hatch), f_1awake_60s.png (~60 s in alone), f_crowd.png (last), grid.png (3x3 across the run), thumb_0awake.png and thumb_crowd.png at 320x180, and honesty.log (assertion output). Return the paths and any exceptions seen in compositor.log.`
const RENDER_SCHEMA = { type: 'object', properties: { paths: { type: 'array', items: { type: 'string' } }, exceptions: { type: 'array', items: { type: 'string' } }, fake_pip_result: { type: 'string' } }, required: ['paths', 'exceptions', 'fake_pip_result'] }

const LENSES = (paths) => [
  { key: 'stranger', prompt: `You are a bored stranger who clicked from the Kick directory at 11pm and you are the ONLY one there. Read ${paths.join(', ')} (Read tool). Answer literally, with frame evidence: in the 0-awake frame, would I type anything, and what on screen made me? After my first message, did the screen answer ME within seconds in a way I understand (creature, name, my words)? Alone for 60 s: is anything alive and changing (drips, moss, sky, my pip doing things), or is it a dark box? Did the verbs the plank suggested actually work when I tried them? Could I read what A/B/C would DO before voting, and did my vote visibly count within ~3 s? Anything confusing, ugly, or mod-jargon shown to me? Pass only if you would still be there at 10 minutes alone.` },
  { key: 'honesty', prompt: `Audit honesty, moderation and legibility on ${paths.join(', ')} plus /tmp/pipqa-*/honesty.log and the seeded chat.jsonl. Every creature maps to a seeded record (list them). The planted fake pip in world.json was REFUSED (not shown as sleeper or awake). No name visible before its hold; the slur user and blocklisted username never drawn anywhere including chat log and mod notices; the hidden-in-hold user never drawn raw; mod notices never leak raw target names. Counts equal len(). 320x180 thumbs: awake count legible; at 0 awake a light source is visible. All text >= 20 px. Pass/fail with evidence.` },
  { key: 'art', prompt: `Review ${paths.join(', ')} and ${ROOT}/docs/art-rules.md and the sprite sheet under /tmp/pip-core or /tmp/pip-integ. Does the cave read as a CAVE at 1280x720 and at 320x180 (rock vs void contrast, irregular ceiling/floor, cave mouth with sky, moss, drips)? Do sprites keep a readable silhouette for light name colours (outline vs glow)? Do labels avoid collisions where pips gather? Do all sprites have eyes and a visible speak frame? Distinct from Thronglets and pet IP? Anything that looks cheap at Kick's 3 Mbps encode? Pass/fail with pixel-level fixes.` },
]

let lastQa = null
for (let round = 1; round <= ROUNDS; round++) {
  phase('Render')
  const r = await agent(RENDER(`r${round}`), { model: 'fable', label: `render:r${round}`, phase: 'Render', effort: 'high', schema: RENDER_SCHEMA })
  const paths = (r && r.paths && r.paths.length) ? r.paths : [`/tmp/pipqa-r${round}/grid.png`]
  log(`round ${round}: rendered ${paths.length} evidence files; fake pip: ${r ? r.fake_pip_result : 'n/a'}`)
  phase('QA')
  const qa = (await parallel(LENSES(paths).map(q => () => agent(`${CONTRACT}\n## QA (${q.key}), round ${round}\n${q.prompt}\nReturn structured pass/fail + blocking issues + suggestions.`,
    { model: 'fable', label: `qa:${q.key}:r${round}`, phase: 'QA', effort: 'high', schema: QA_SCHEMA })))).filter(Boolean)
  lastQa = qa
  const blocking = qa.flatMap(q => q.blocking_issues || [])
  log(`round ${round} QA: ${qa.map(q => q.verdict).join(',')}; blocking=${blocking.length}`)
  if (!blocking.length && qa.length === 3) { return { round, verdict: 'pass', qa } }
  phase('Fix')
  const fixed = await agent(`${CONTRACT}
## Fix round ${round}: close every blocker below in the owning files under ${ROOT}/stream/ or ${ROOT}/agents/
${blocking.map((b, i) => `${i + 1}. ${b}`).join('\n')}
Suggestions worth taking if cheap: ${JSON.stringify(qa.flatMap(q => q.suggestions || []).slice(0, 12))}
Do not regress: honesty assertions, moderation hold/filters, legibility (>= 20 px), motion every frame, frame budget (<= 10 ms world at 20 pips), run-dir guard, relay/hot-reload. After fixing: py_compile everything, re-run the honesty self-test, and re-render a 300-frame self-test into /tmp/pipqa-fix${round} with the same seed shape (0 awake → 1 awake → crowd) and Read your own frames to confirm each blocker is visibly gone. Return what you fixed, what remains, and evidence.`,
    { model: 'fable', label: `fix:r${round}`, phase: 'Fix', effort: 'high', schema: FIX_SCHEMA })
  log(`round ${round} fix: ${fixed ? fixed.verdict : 'null'}; remaining=${fixed ? (fixed.remaining || []).length : '?'}`)
}
return { round: ROUNDS, verdict: 'exhausted', qa: lastQa }
