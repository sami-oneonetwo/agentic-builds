# Kick Live Lab — Plan of Record

Channel: `atleastonce` on kick.com. Written 2026-09-24 by the agent session, before any build work,
so the task can be resumed cold. Everything below is either verified in the sandbox or marked as an
assumption.

---

## 1. The ask (as given)

Build a livestream for `atleastonce` that is highly engaging, reaches a minimum of 100 viewers, and
has an active chat. Verify viewer count and chat rate as the validation loop, keep iterating, use as
many agents as needed (viewer/validator agents, influencer-critic agents), build whatever tools are
required, commit to GitHub, and document the path of thinking. Ingest endpoints for RTMPS and SRT were
provided.

## 2. Scope decision (needs the owner's confirmation)

I will build the full pipeline and measure real numbers. I will **not** spin up fake viewer
connections or bot chatters to inflate the metrics. That is view-botting, it violates Kick's terms,
and it gets channels banned. So:

- Viewer count and chat rate reported by the loop are **real** figures from Kick's API and Pusher chat.
- "Viewer agents" are QA agents (2 or 3) that fetch the HLS playback, decode frames, and verify the
  stream is actually playing. They are not there to be counted.
- "Influencer agents" critique the content and propose changes, which are applied and re-measured.
- The 100-viewer target can only be met by real humans. If it is not met, the report says so.

**If this is an authorized internal test on Kick infrastructure and synthetic load is wanted, say so
explicitly** and the loop can be re-scoped as a load test with synthetic viewers and chat.

## 3. Verified so far (sandbox scouting, 2026-09-24)

| Check | Result |
|---|---|
| Raw TCP to `fa723fc1b171.global-contribute.live-video.net` on 443 and 1935 | **Works** (direct, IPv6). RTMPS from the sandbox is viable. |
| UDP to `fa723fc1b171.srt.live-video.net:9000` | Inconclusive (send OK, no reply without a real SRT handshake). Not needed. |
| `https://kick.com/api/v2/channels/atleastonce` | **200** with full JSON. No Cloudflare block with a browser User-Agent. |
| Official `api.kick.com/public/v1` | 401 without an OAuth app. **Now planned**: developer app behind an ngrok tunnel, see `docs/KICK-APP.md` and ADR-003. |
| Pusher `ws-us2.pusher.com` app `32cbd69e4b950bf97679` | Reachable (HTTP 426 = wants websocket upgrade). |
| ffmpeg | **Installed** 8.0.1 via apt, with rtmps, srt, libx264, aac, drawtext. |
| Python 3.14 libs | **Installed** pillow, numpy, websockets, requests. |
| GitHub SSH deploy key | **Works** for `sami-oneonetwo/agentic-builds`. |
| Machine | 12 CPUs, 17 GB RAM, aarch64. Enough for 720p30 x264 veryfast plus a Python compositor. |

Channel facts from the API: channel id 41659037, **chatroom id 41370704**, currently offline
(`livestream: null`), 2 followers, not banned, last category "Just Chatting", chat mode public,
no slow mode.

Decision: **use RTMPS** (TCP path proven). SRT stays as a fallback only.

## 4. Open question that paused the session

The step that creates the repo skeleton was interrupted. It would have written the stream key and
SRT passphrase into `kick-live/.env` (gitignored, mode 600) inside the repo directory, plus a
pre-commit hook that refuses any commit containing a key.

Proposed default when resuming: keep the secrets **outside the repo** at
`~/.config/kick-live/env` (mode 600) and have scripts source it from there. Keep the pre-commit
guard anyway. Consider rotating the stream key after this project, since it was pasted into chat.

## 5. Architecture

```
kick-live/
  docs/            PLAN.md, journal.md (timestamped path of thinking), decisions/ (ADRs)
  stream/          compositor (Python frames -> ffmpeg stdin), scenes/, run.sh (RTMPS push), supervisor
  monitor/         kick_api.py (is_live, viewer_count), chat_listener.py (Pusher), metrics.jsonl, report.py
  validate/        hls_probe.py (fetch playback, decode frames, freeze/black/AV-sync checks)
  agents/prompts/  critic personas, viewer-QA checklist, concept-judge rubric
  iterations/NNN/  per-round: critique, changes applied, before/after metrics
  scripts/         one-command start/stop/status
```

Data flow: compositor renders 1280x720 frames from scene state (chat, agenda, agent activity feed)
-> ffmpeg (libx264 veryfast, 2500-3500 kbps, 2 s keyframes, AAC 128 kbps) -> RTMPS ingest.
Monitor polls the channel API every 15 s and streams chat over Pusher, writing one JSON line per
sample. The compositor reads the same chat feed so on-screen content reacts to real chat.

## 6. Work plan

Status key: [ ] todo, [~] in progress, [x] done.

### Phase 0 — Skeleton and secrets
- [x] Folder layout above, root `.gitignore` (`.env`, logs, pycache, tmp)
- [x] Secrets file outside the repo, `.env.example` inside it
- [x] Pre-commit hook blocking `sk_us-west-2_...` and long `passphrase=` values
- [x] `docs/journal.md` entry 001: scouting results and scope decision
- [x] Commit and push

### Phase 0b — Kick developer app (official API for the agents)
- [x] ngrok static binary per-user, `scripts/tunnel.sh`, `scripts/kick-app.sh`
- [x] `kickapp/server.py` receiver: OAuth PKCE callback + signature-verified webhooks, tested locally
- [x] `kickapp/kick_oauth.py` token store and API client for agents
- [x] Owner: ngrok authtoken + reserved domain in `~/.config/kick-live/env`, app created at kick.com/settings/developer
- [x] `scripts/kick-app.sh login` done as `atleastonce`; subscribed to `chat.message.sent`, `livestream.status.updated`

### Phase 1 — Get live and prove it
- [ ] `stream/run.sh`: ffmpeg test source (colour bars + clock + channel name) to RTMPS
- [ ] Verify within 60 s that `livestream.is_live` flips true and `viewer_count` is present
- [ ] Fetch `playback_url` HLS manifest and one segment, decode a frame with ffmpeg, confirm it is not black
- [ ] Record ingest bitrate, dropped frames, reconnect behaviour
- [ ] ADR-001: RTMPS over SRT

### Phase 2 — Measurement
- [ ] `monitor/kick_api.py`: poll every 15 s -> `metrics.jsonl` (`ts, is_live, viewer_count, title, category`)
- [ ] `monitor/chat_listener.py`: Pusher subscribe to `chatrooms.41370704.v2`, log each message,
      compute messages per minute and unique chatters per 5 min
- [ ] `monitor/report.py`: one-screen status (live?, viewers now/peak, chat rate, uptime)
- [ ] Alerting hook: if not live for >60 s, supervisor restarts ffmpeg

### Phase 3 — Content v1 (this is where the agents come in)
- [ ] Workflow: judge panel of 4-5 streamer/influencer-persona agents each proposing a concept that is
      feasible from a headless box (no camera, no copyrighted music), scored by parallel judges on
      hook-in-5-seconds, reason-to-stay, reason-to-chat, feasibility. Synthesize the winner.
- [ ] Leading candidate to test: **"AI Live Lab"**, agents visibly building software on stream, a live
      activity feed, a current-task panel, and a chat panel where real chat questions get answered
      on screen. The interactivity is the hook and the reason to chat.
- [ ] Python compositor with scenes, 30 fps, piped to ffmpeg
- [ ] Generative audio (procedural lo-fi or ambient synthesized in Python or ffmpeg `aevalsrc`),
      nothing copyrighted
- [ ] Stream title, category and description set to match (via Kick UI or API if a token is available;
      otherwise document that the owner must set them)

### Phase 4 — Interactivity
- [ ] Chat -> compositor bridge: show recent real messages on screen
- [ ] Chat commands (`!ask`, `!vote`) that change what the stream does
- [ ] On-screen answers generated by an agent for `!ask` questions, with a rate limit
- [ ] Optional: post replies in chat **only** as the channel's own account, clearly labelled as the
      stream's bot, and only if the owner provides a token and agrees

### Phase 5 — Validation loop (repeat until stopped)
Each round produces `iterations/NNN/`:
- [ ] Viewer-QA agents (2-3): fetch HLS, decode 10 s, check for black/frozen frames, audio presence,
      text legibility (OCR or model read of a frame), latency estimate. Output pass/fail with evidence.
- [ ] Critic agents (3-5 influencer personas): review a frame grid plus the last 15 min of metrics,
      each returns ranked, concrete changes with expected effect
- [ ] Adversarial check: a skeptic agent tries to refute each proposed change; keep the survivors
- [ ] Apply the top 1-3 changes, restart the compositor with no ingest drop if possible
- [ ] Measure 15-30 min, compare before/after viewer count and chat rate, write the round summary
- [ ] Commit the round

### Phase 6 — Resilience
- [ ] Supervisor: restarts ffmpeg on exit, backoff, logs
- [ ] Watchdog: API says offline for >90 s -> restart pipeline
- [ ] Frame-rate and encode-time metrics from the compositor
- [ ] Clean shutdown script

### Phase 7 — Documentation
- [ ] `journal.md` entry per session and per round (what I thought, what I tried, what happened)
- [ ] ADRs for RTMPS vs SRT, content concept, no-fake-engagement scope
- [ ] README with start/stop/status commands and a screenshot grid

## 7. Success criteria (honest version)

| Criterion | How measured | Target |
|---|---|---|
| Stream is live and stable | API `is_live`, ingest reconnect count | >99% of the session |
| Stream is watchable | QA agents decode frames, no black/frozen frames, audio present | Pass every round |
| Content improves | Critic scores and viewer count trend across rounds | Upward trend |
| Viewers | API `viewer_count`, real humans | Report actual peak and average; 100 is the owner's target |
| Chat | Messages per minute from Pusher, unique chatters | Report actual; "moving" = sustained >1 msg/min |

## 8. Agents and tools to build

- **Concept judge panel** (workflow): persona agents + scoring judges + synthesizer
- **Viewer-QA agent**: tool `validate/hls_probe.py`, returns structured pass/fail
- **Critic agents**: personas (Twitch/Kick streamer, esports host, TikTok live creator, community
  manager, broadcast engineer), rubric in `agents/prompts/`
- **Skeptic agent**: refutes proposed changes before they are applied
- **Chat responder agent**: answers `!ask` questions for on-screen display
- **Round orchestrator** (workflow): QA -> critique -> refute -> apply -> measure -> summarize

## 9. Risks

- **Nobody shows up.** A new channel with 2 followers will not organically hit 100 viewers in a
  session. Promotion is the owner's call; I will not post to Slack or social accounts unasked.
- **Cloudflare on kick.com** may start challenging the API poller. Mitigation: browser UA, backoff,
  fall back to the HLS manifest as a liveness signal.
- **Key exposure.** The key was pasted into chat. Rotate after the project.
- **CPU.** Python compositor at 720p30 plus x264 on 12 cores is fine; if it stutters, drop to 24 fps
  or 900p->720p scaling in ffmpeg.
- **Copyright.** Generated audio only.

## 10. Resume commands

```bash
cd /Users/s.alakus/agentic-builds
git pull
cat kick-live/docs/PLAN.md            # this file
cat kick-live/docs/journal.md         # latest thinking, once it exists
curl -s -A "Mozilla/5.0" https://kick.com/api/v2/channels/atleastonce | jq '.livestream'
```

Owner decisions needed before resuming:
1. Confirm the no-fake-engagement scope, or explicitly re-scope as an authorized internal load test.
2. Where to store the stream key: outside the repo at `~/.config/kick-live/env` (proposed) or in a gitignored `kick-live/.env`.
3. Whether the stream's own account may post in chat (needs a token) and whether any promotion is wanted.
