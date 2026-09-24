# Kick Live Lab — Journal

Path of thinking, newest entry last. One entry per session or per iteration round.
Times are Australia/Brisbane (+10:00) unless marked UTC.

---

## 001 — 2026-09-24 19:35 — Resume on a new machine, scope defaults, Phase 0

**Context.** PLAN.md was written in a Linux sandbox earlier today. This session runs on a
different machine: Apple M3 Pro (12 cores, 36 GB), macOS, user account `sandy`, repo at
`/Users/sandy/Workspace/agentic-builds`. Nothing from the sandbox carried over except the plan.

**Owner instruction.** "Read the kick-live for your objective. Go and don't stop." The plan listed
three owner decisions. No answers were given, so I took the plan's proposed defaults and record them
here so they can be overturned:

1. **No fake engagement.** Viewer and chat numbers are real Kick API and Pusher figures. No synthetic
   viewers or chatters. See ADR-000.
2. **Secrets live outside the repo** at `~/.config/kick-live/env` (mode 600). A template was created
   there. `.env.example` in the repo documents the keys. Pre-commit hook blocks key patterns and was
   tested against a planted key. See ADR-002.
3. **No chat posting as the channel, no promotion.** `KICK_TOKEN` stays blank.

**Blocker: no stream key on this machine.** The key was pasted into the *previous* session's chat,
not this one, and no env file existed here. Every part of the pipeline is being built so that
`scripts/start.sh` goes live the moment `STREAM_KEY` is filled in at `~/.config/kick-live/env`.
Until then, Phase 1 (go live and prove it) cannot complete. The end-to-end path is instead tested
against a local HLS output written by the same ffmpeg command.

**Environment findings (this Mac).**

| Check | Result |
|---|---|
| `kick.com/api/v2/channels/atleastonce` | 200. id 41659037, chatroom 41370704, 2 followers, offline. `playback_url` present even while offline. |
| TCP to `fa723fc1b171.global-contribute.live-video.net` 443 and 1935 | Open. RTMPS viable from here too. |
| Pusher `ws-us2.pusher.com` app `32cbd69e4b950bf97679` | 426 (wants websocket). Reachable. |
| ffmpeg | Not on PATH. `/opt/homebrew` belongs to another account (`s.alakus`) but its ffmpeg 9.0.1 runs; it lacks `drawtext`. Downloaded static ffmpeg/ffprobe 9.0.2 (martin-riedl.de, arm64) to `~/.local/bin/ffmpeg-static`; has rtmps, srt, libx264, aac, h264_videotoolbox, drawtext, freezedetect, blackdetect. **Static build is primary.** |
| Python | System 3.9.6 only. Homebrew 3.14 venv failed (ensurepip). Created venv at `~/.local/share/kick-live/venv` from 3.9 with pillow 11.3, numpy 2.0, websockets 15, requests 2.32. |
| sudo | Password required. No system-level installs. Everything is per-user. |
| Fonts | Menlo, Monaco, Helvetica Neue, Avenir Next, Arial Black available under `/System/Library/Fonts`. |

**Decisions this entry.**
- `scripts/env.sh` is the single source of tool paths, secrets, and runtime file locations. All
  scripts source it. Runtime data goes to `kick-live/run/` (gitignored): `metrics.jsonl`,
  `chat.jsonl`, `activity.jsonl`, `state.json`, `logs/`, `pids/`.
- The on-screen "agent activity feed" is fed by anything appending to `run/activity.jsonl`. That is
  how the build agents themselves will show up on the stream.

**Next.** Workflow 1: concept judge panel (5 personas, 3 judges, synthesizer) in parallel with
building the measurement and validation tools, which do not depend on the concept.
