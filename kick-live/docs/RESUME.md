# Resuming kick-live in a new Claude Code session

Everything that matters survives a session close **except work that is still running inside the
session** (background workflows, monitors). The live stream, the repo, the snapshots, the runtime
dirs and the memory files are all on disk and unaffected.

## What survives
- Repo: `~/Workspace/agentic-builds` (all committed and pushed; check `git status`).
- Live stream: processes under `~/.local/share/kick-live/run-live/pids/` keep running as long as the
  Mac stays awake. Code: `~/.local/share/kick-live/live-current` (symlink to the live snapshot).
- Memory: `~/.claude/projects/-Users-sandy-Workspace/memory/` (loaded automatically when Claude Code
  starts in `~/Workspace`; not tied to the API key).
- Secrets: `~/.config/kick-live/env`, OAuth tokens `~/.config/kick-live/tokens.json`.

## What does not survive
- Any workflow mid-flight. Its completed agents are cached only for the **same session id**.
  Reopening this exact conversation (`claude --continue` in `~/Workspace`, or `claude --resume` and
  pick "SSH key generation for GitHub") keeps the session id, so
  `Workflow({scriptPath, resumeFromRunId})` still works. A brand-new conversation cannot resume
  the cache; use the integrate-only workflow below instead.

## Steps
```bash
cd ~/Workspace && git -C agentic-builds pull
tail -80 agentic-builds/kick-live/docs/journal.md          # latest entries first: what was mid-flight
L=~/.local/share/kick-live/run-live
for n in supervisor relay compositor ffmpeg kick_api chat_listener duty; do kill -0 $(cat $L/pids/$n.pid) 2>/dev/null && echo "$n up" || echo "$n DOWN"; done
curl -s http://127.0.0.1:8080/health | head -c 200         # OAuth/webhook receiver (peer's kickapp)
```
If the pipeline is down: `RUN_DIR=$L KL_LIVE=1 MODE=live SOURCE=compositor AUDIO_SOURCE=pipe:$L/a.pcm bash ~/.local/share/kick-live/live-current/scripts/start.sh`
and `RUN_DIR=$L ~/.local/share/kick-live/venv/bin/python agentic-builds/kick-live/agents/duty.py heartbeat &`.
If the receiver/tunnel is down: `bash ~/Workspace/agentic-builds/.claude/worktrees/kick-ngrok-tunnel/kick-live/scripts/kick-app.sh up`.

## LONGGRASS is live (state as of 2026-09-26 15:40)
The integrate-only workflow ran to completion (journal 024, 025); LONGGRASS was hot-reloaded into live-snapshot-v3 at
14:13 and fix pass 2 at 15:34. See docs/HANDOFF.md for the current state, open items and the proven deploy recipe.
Also check the owner's chat kill switch: `kill -0 $(cat $L/pids/ops_switch.pid)`; relaunch recipe in the docstring of
`scripts/ops_chat_switch.py` (never `source env.sh` first).

## Using a different API key / gateway
Claude Code reads `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` (or `ANTHROPIC_API_KEY`) and
`ANTHROPIC_MODEL`. The gateway must speak the Anthropic Messages API; check the provider's docs for
their Anthropic-compatible endpoint and model ids before relying on it. Model availability may differ
(the workflows pin `model: 'fable'`; adjust if the gateway lacks it). The conversation transcript and
memory are local and independent of the key.
