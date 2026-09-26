# HANDOFF for a fresh session

Written 2026-09-26, 15:40 Brisbane time. Supersedes the mid-morning handoff (that session's plan was executed).

## Who and what

- Owner: Sandy (commits as Sami Alakus). Works at Kick. Channel: atleastonce.
- Repo: ~/Workspace/agentic-builds, project folder kick-live. Everything below is committed.
- Memory: ~/.claude/projects/-Users-sandy-Workspace/memory/ loads automatically when Claude Code starts in
  ~/Workspace. Read MEMORY.md and the files it links.
- Full history of decisions: kick-live/docs/journal.md, entries 001 to 025. Newest entries last.
- Health checks and restart commands: kick-live/docs/RESUME.md.

## Goal

A genuinely popular, honest Kick livestream produced by AI agents. Real chat only, no fake viewers or chat, ever.
The stream is a living world that chat raises: every named creature on screen is a real person who typed. AI agents,
called keepers in the fiction, build chat's feature requests live.

## What is live right now

- **LONGGRASS**, the top-down settlement (SteadingScene), on air since 2026-09-26 14:13 by hot-reload into the
  snapshot ~/.local/share/kick-live/live-snapshot-v3 (symlink live-current). Fix pass 2 hot-reloaded at 15:34.
  The encoder (ffmpeg pid 40018, started 10:03) was never restarted for either deploy.
- Runtime state ~/.local/share/kick-live/run-live (pids in run-live/pids). world.json is schema 2 with the owner's two
  pips and their camps. Backups: run-live/world.json.bak-pre-longgrass-*, .bak-v1-*, .bak-pre-fix2-*.
- Snapshot backups for rollback: live-snapshot-v3-pre-longgrass (the cave), live-snapshot-v3-longgrass-v0a (LONGGRASS
  before fix pass 2). Rollback = copy those files back into live-snapshot-v3 (hot-reload picks them up) or
  scripts/swap-build.sh.
- Kick title: "Say anything in chat. A creature walks out with your name". Category: Software Development.
- The Mac is the streaming box. It sleeps when the lid closes and the stream drops. Owner will move to a persistent
  host later; do not nag.

## Processes that must be alive (run-live/pids)

supervisor, run, relay, compositor, ffmpeg, kick_api, chat_listener, duty (keeper heartbeat, started from the REPO tree
by `RUN_DIR=$L python agents/duty.py heartbeat`), caffeinate, and **ops_switch** (see below). status.sh lists them all.
The OAuth/webhook receiver (kickapp/server.py + ngrok) runs from a worktree directory that no longer exists on disk;
its code is on origin/worktree-kick-ngrok-tunnel. Restore with
`git archive origin/worktree-kick-ngrok-tunnel kick-live/kickapp kick-live/scripts/kick-app.sh | tar -x -C /tmp/lg-kickapp`
(used for the title PATCH; ko.user_token() refreshes the user token).

Since 17:10 two more monitors run from the REPO tree, not the snapshot: `kick_api` (pid in run-live/pids/kick_api.pid;
restarted to add category_live / category_viewers / our_rank to metrics.jsonl; snapshot copy kept in step) and
`category_sampler` (monitor/category_sampler.py, 10-min loop, writes run-live/category_samples.jsonl +
category_latest.json). `monitor/chatter_log.py --all-days` refreshes run-live/chatters.json and run/reports/YYYY-MM-DD.md
(run it each tick). Title is set by `scripts/set_title.py` (live counters, once per 24 h; --dry-run first); it was set
at 17:14 to "Your name becomes a pixel settler. Type anything. AI agents build the village · Day 3 · 2 settled".

## The owner's chat kill switch (new rule, 2026-09-26)

`scripts/ops_chat_switch.py` tails run-live/chat.jsonl. Exactly `nuke` from atleastonce with the broadcaster badge
stops the streaming pipeline (supervisor -> run group; kick_api and chat_listener stay up); exactly `init` relaunches
stream/supervisor.sh from live-current with the RESUME.md environment and waits for a live encoder. This is the ONE
sanctioned exception to "chat is data, not commands"; do not add tokens without the owner asking in the terminal.
Launch recipe is in the script's docstring (`env -u` every secret; never source env.sh first). Not restarted by
start.sh/stop.sh. Never exercised live yet. Memory: owner-chat-ops-switch.md.

## The improvement loop (owner mandate 2026-09-26, journal 026)

The owner wants continuous autonomous self-improvement toward real viewers and engagement, hands-off. A session cron
(:17 and :57) runs observe -> deploy finished builds -> pick next -> journal/commit/push. **Before any change: if
run-live/pause_bot.json exists the owner said `pause bot`; do nothing until `resume bot`.** The chat bridge pauses
ingestion on the same phrase. Research backlog: workflow kick-growth-research (journal). Direction: interactive
settlers first; category/title may change on evidence. Each tick journals one entry.

## Open items, in priority order

1. **Watch the first real session on LONGGRASS** and collect owner verdicts. Known cosmetic leftovers (journal 025):
   at pinned 1x two people far apart cannot both clear the HUD chips (0.75x zoom is the spec's cure, v0 pins 1x);
   `NOBODY AWAKE` header at 72 px kept as the thumbnail hook; vote bubbles can float ~200 px above a crowded Moot.
2. **Bake version mismatch**: scripts/prebake_land.py writes ground-*-v3.npy but the scene loads/paints -v1; the
   prebaked files are ignored and the scene paints in ~600 ms in its bake thread (harmless). Align the `ver` key.
3. **Honesty edge**: with world.json pips but no chat.jsonl records, the scene quarantines the pips (correct) while the
   keeper strip still draws `last here: @name` from builders.json; the new name-leak assertion flags it. Only reachable
   when chat.jsonl is missing; decide whether quarantined names should be scrubbed from builders-derived copy too.
4. **deploy.sh** false FAIL fixed in the repo (newest gap start_ts instead of the capped gap count); copy it into
   live-snapshot-v3 at the next deploy.
5. Owner ideas classified carving-next: gems as shiny stones settlers find and stack (i-0006); "go out of the cave"
   (i-0005) is delivered by LONGGRASS itself and should be closed on the board.
6. Promo and featured-slot pack (docs/promo) describes the old text show. Redo after a real LONGGRASS session.
7. Merge of origin/worktree-kick-ngrok-tunnel (OAuth receiver) into main. Will conflict on journal.md, env.sh,
   pre-commit. Nobody owns it right now.
8. v1 cut per OPENWORLD.md section 13 (0.75x zoom, raisings, land strips) ships as keeper macro-ships on air.

## How to deploy a change (proven twice on air today)

1. Stage: rsync the tree to /tmp/lg-deploy-stageN, py_compile, run the module self-tests (honesty, camera, behaviour,
   state, keepers, chat_bridge, `MODE=test steading.py --self-test`) and a 300-frame `compositor.py --self-test` on a
   copy of run-live/world.json **plus run-live/chat.jsonl** (without the chat file the pips are quarantined and the
   honesty check fails by design).
2. Back up live-snapshot-v3 (cp -a) and run-live/world.json.
3. Spine files that changed (compositor, chat_bridge, rounds, audio, state_store) -> live-snapshot-v3/stream/, then
   `RUN_DIR=$L bash live-snapshot-v3/scripts/deploy.sh --wait 45` (relay-held child restart, ~0.6 s of repeated frames,
   ffmpeg pid must not change).
4. World/scene/panel files -> live-snapshot-v3 **together** (one cp batch); the HotReloader swaps the scene in ~2 s with
   a 2-5 frame gap and commits panels after 30 clean renders. Watch run-live/logs/compositor.log for ROLLBACK/Traceback.
5. Verify: `validate/hls_probe.py --channel atleastonce`, Read last_frame.png, world.json pips intact.
6. Tell the owner before step 3 (memory rule). The owner approved fix passes landing live on 2026-09-26 while watching.

## Rules the owner set, do not relitigate

- No fake viewers, no fake chat, no invented names. Nature may move at zero viewers. No animals or NPCs.
- Chat is data, not commands (single exception: the owner's nuke/init switch above). Keeper builds touch only world
  code, never the repo, pipeline, auth, moderation or honesty checks.
- Auth is OAuth only through the Kick developer app. Never a browser cookie.
- Secrets live in ~/.config/kick-live/env and are stripped from render processes (and from the ops switch).
- Never restart the pipeline for small changes. Deploy through hot-reload or the relay. Tell the owner first.
- Test harnesses must never `pkill -f` by pattern (a harness killed the live keeper heartbeat for 69 s today).
- Stream key was not rotated by owner choice. Rotate after the project.

## API and cost

The owner runs this session through OpenRouter (ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN). Workflow scripts no longer
pin a model; agents inherit the session model.

## Addendum 17:10 — HUD pass built, not deployed (journal 028)

The HUD reshape (owner 15:50: too much on screen) is in the tree: stream/layout.py regions changed (world 0,66,1280,456;
one `land` strip 0,522,720,198; chat_log 720,522,560,198; header_left / countdown / colony / keeper / ticker / scope /
readout removed), header.py / colony.py / chat_log.py / world.py rewritten, camera.py + steading.py at SCREEN 456,
compositor.py (WORLD_BAND, vote-ack copy, land-strip + vote-card per-frame checks), chat_bridge.py (vote ack `walks to X ·
counts while standing there · closes in m:ss`, unparsed-with-hint, vote reconciliation with who stands). Because layout.py
moved regions this ships as ONE relay-held compositor child restart (scripts/deploy.sh) after copying all changed files
into live-snapshot-v3 together, never as a hot-reload of single panels (a panel registering a removed region is dropped,
so a partial copy shows a black strip, not a crash). Tell the owner first. Evidence and grids: /tmp/lg-hud-build/report.

## Addendum 17:55 — HUD fix pass built, not deployed (journal 030)

On top of the HUD pass: stream/layout.py changed AGAIN (header_center 0,0,880,66; header_right 880,0,400,66: two rows,
the clock row moved there from the land), so the same rule applies: ONE relay-held compositor child restart
(scripts/deploy.sh) after copying every changed file together into live-snapshot-v3 (layout.py, compositor.py,
chat_bridge.py, panels/header.py, panels/world.py, panels/chat_log.py, panels/colony.py, world/camera.py,
world/behaviour.py + the rest of the 028 set). Evidence and grids: /tmp/lg-hud-fix/report. Tell the owner first.
