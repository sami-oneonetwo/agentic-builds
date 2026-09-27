# Resuming the live world

> **PAUSED BY OWNER, 2026-09-27 13:59 AEST.** All project streaming processes, monitors, keeper heartbeat, webhook server and ngrok tunnel were stopped. The probe cron was cancelled. Runtime pause_bot.json is present. World and code are preserved. Do not restart, re-arm automation, or deploy until the owner explicitly asks to resume. Earlier live/running descriptions below are historical.

Current handoff: `docs/HANDOFF.md`, top section, updated 2026-09-27. The older plans are design history.
Active branch: `origin/worktree-idle-world`. No automatic merge to main.

## Inspect before changing anything

```bash
T="$HOME/Workspace/agentic-builds/.claude/worktrees/idle-world/kick-live"
L="$HOME/.local/share/kick-live/run-live"
PY="$HOME/.local/share/kick-live/venv/bin/python"
RUN_DIR="$L" bash "$T/scripts/status.sh"
tail -40 "$T/docs/journal.md"
test ! -e "$L/pause_bot.json"
```

Use current pidfiles and verify command identity, not historical PIDs. The probe is a session cron, so no probe PID
is expected unless the headless alternative was deliberately started. The live snapshot is distinct from the working
checkout. Never copy uncommitted work to it just because a self-test passed on some other tree.

## Probe tick

```bash
MODE=live "$PY" "$T/agents/probe.py" --run-dir "$L" observe --json
MODE=live "$PY" "$T/agents/probe.py" --run-dir "$L" dossiers
```

Read `agents/prompts/probe.md`, answer the eight questions from the observation, then pipe the validated JSON to
`MODE=live "$PY" "$T/agents/probe.py" --run-dir "$L" ingest --orchestrator`. This does not build or deploy.
Only append a probe journal paragraph when ingest returns a non-null paragraph. Do not write a quiet-tick commit.
Re-arm one session cron at `7,27,47 * * * *` after resuming if needed. It dies with the session and expires after
seven days. Check the existing job list first. When paused, observe only: no dossiers, board writes, or deploy.

`agents/probe.sh --once` is the optional headless alternative, not currently running. It needs the session's API
configuration and `MODE=live`; do not source streaming secrets into it. Do not run it alongside the session cron.

## Deployment and recovery

Small world changes: exact tested, backed-up batch of watched world/scene/panel files, then verify reload probation,
new error lines, honesty and Kick HLS. Art/spine changes need one relay-held renderer-child restart via `deploy.sh`.
Never restart the encoder for a small change. Schema migration and replay must be tested on copies first.
A paused/stopped pipeline may be intentional: inspect ops_switch and supervisor logs before relaunching.

If relaunch has been authorized and the pipeline is genuinely stopped:

```bash
RUN_DIR="$L" KL_LIVE=1 MODE=live SOURCE=compositor AUDIO_SOURCE="pipe:$L/a.pcm" \
  bash "$HOME/.local/share/kick-live/live-current/scripts/start.sh"
```

Keeper heartbeat and category sampler currently run from the worktree; the ops switch runs from the snapshot.
Use each script's documented launch recipe, avoid duplicates, and strip streaming secrets from non-streaming processes.
Validate playback with `validate/hls_probe.py --channel atleastonce --seconds 8 --out <fresh-evidence-directory>`.

## State that persists

`world.json` schema 3 stores identities, homes, dates, age history, wish papers and placed objects. Append-only chat and
wish ledgers preserve provenance. Session cron/workflows do not survive a session exit. Do not rotate active chat
files while the compositor is running. Never overwrite current state with a test fixture or stale backup.
