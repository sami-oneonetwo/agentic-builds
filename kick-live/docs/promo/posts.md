# SHIP IT LIVE — ready-to-paste posts for `atleastonce`

Drafted 2026-09-25 by the agent; figures re-checked 2026-09-25 00:45 UTC. **The owner posts; the agent never
posts on the owner's behalf** (journal 002). Every figure here comes from the runtime files listed in
`featured-slot-pack.md`. Post only while the stream is live: it was live (second session, started 00:35 UTC
on 25 Sep) when this was revised, but check `kick.com/atleastonce` first. The show does not run on a schedule
yet, so nothing below promises one.

Commands viewers can type (from CONCEPT §7, checked against the live build `chat_bridge.py`):

| Type | What happens on screen |
|---|---|
| `A`, `B` or `C` (or `!a` `!b` `!c`) — the whole message | Your vote counts and your name appears under the card on the next frame; a new letter moves your vote |
| `!idea <what should change>` | Your line is tagged NOMINATED and goes into the NEXT UP queue with your name; an agent on duty classifies it (instant / macro / declined with a reason) |
| `!theme kick` / `ember` / `ice` / `violet` / `gold` / `magenta` / `cyan` / `paper` | Whole stream repaints for everyone (60 s global cooldown, shown on screen) |
| `!stats` | 10 s card of real numbers (30 s global cooldown) |
| `!help` | Command legend in the pinned strip for 20 s (30 s global cooldown) |

Not advertised: `!ask` (disabled, `ask.enabled: false`) and `!revert` (not in v1).

---

## (a) Kick community / Discord announcement

```
SHIP IT LIVE is on: a stream that rebuilds itself. Every 3 minutes chat votes A, B or C on what changes next, AI agents ship it on screen and the version number ticks up. Type one letter and your name goes into the patch notes.
No camera, no mic, no fake viewers. Every number on screen is real (right now that means single digits).
Live now, Software Development: https://kick.com/atleastonce
```

## (b) X / Twitter

Single post (under 280 characters, count in the table at the bottom):

```
Live on Kick: a stream whose only content is itself. Every 3 min chat votes A, B or C, AI agents build the change on screen, the version number ticks up, your name goes in the patch notes. No camera, no fake viewers, real numbers only.
https://kick.com/atleastonce
```

Thread variant (3 tweets):

```
1/ I put a stream on Kick that rebuilds itself. Every 3 minutes chat votes A, B or C on what changes next. The winning option ships live, the version number ticks up, and whoever picked it goes into the patch notes on screen. https://kick.com/atleastonce
```

```
2/ Bigger ideas take longer: type !idea <text>. When an agent is on duty it classifies your idea on screen and writes real code for it while you watch. First one: "!idea change everything. Make it all random" became a chaos-mode ballot option 12 min later (v0.4.0).
```

```
3/ Rules: no camera, no mic, no fake viewers, no bot chat. The viewer count on screen is Kick's own figure. If nobody votes the screen says so and labels the ship an agent pick. First session: 24 min, peak 3 viewers, 7 ships, 0 failed. Come move that number: type A.
```

## (c) Internal Slack note to Kick colleagues

Neutral, for whoever owns featured / homepage placement. Disclosure first.

```
Hi, a side project of mine, sharing with a disclosure: it is my own channel, so treat this as a request rather than a recommendation.
I am streaming a software format on Kick (Software Development, id 34): the stream rebuilds itself every 3 minutes from an A/B/C chat vote, with AI agents applying or coding the change on screen and the voter's name in the patch notes. No camera, no mic, and by rule no synthetic viewers or chat; every number on screen is Kick's real figure.
Current numbers are small and I am not dressing them up: 2 followers, peak 4 concurrent viewers, two sessions so far (24 minutes on 24 Sep, and a second one that started 25 Sep 00:35 UTC). The case is the format, and that a single-letter chat message is about the lowest-friction action a featured visitor can take.
Could someone who owns featured slots take a look at kick.com/atleastonce next time it is live and tell me whether it is a fit, and what it would need to be one? Handoff pack with real frames, stream probe results and the moderation status is attached (featured-slot-pack.md).
No rush and happy to hear "no".
```

## (d) Pinned chat message for the channel

```
This stream rebuilds itself. Type A, B or C (just the letter) to pick what ships next; most votes wins every 3 min and your name goes on screen. !idea <text> to nominate a change, !theme ember to repaint the stream, !help for the rest. No fake viewers here: every number you see is real.
```

---

## Character counts

Checked with Python `len()` on each fenced block, newlines included. X limit is 280.

| Block | Characters |
|---|---|
| X single post | 264 |
| Thread 1/ | 254 |
| Thread 2/ | 265 |
| Thread 3/ | 266 |
| Discord / community | 393 |
| Slack note | 1101 |
| Pinned chat | 287 |

## Sources

| Claim in the copy | Source |
|---|---|
| "every 3 minutes", A/B/C, agent build, patch notes | CONCEPT §1 one-liner, §2 |
| Command list and effects, cooldowns | CONCEPT §7; `live-snapshot/stream/chat_bridge.py` (`VOTE_RE`, `THEME_COOLDOWN_S`, `CMD_COOLDOWN_S`, `stats_until`, `help_until`, `tallies`) |
| `!ask` disabled | `state.json` / `run-live/state.json` `ask.enabled: false` |
| "single digits", 2 followers, peak 3 (first session) and 4 (second session so far), two sessions | `metrics.jsonl`, `run-live/metrics.jsonl` (`followers`, `viewer_count`, `started_at`); public API `followers_count`, `livestream.start_time` at 00:43 UTC 25 Sep |
| 7 ships, 0 failed (first session) | `ships.jsonl` (6 micro) + `activity.jsonl` `SHIPPED v0.4.0 (macro)`; the on-screen counter said 8 because of a test-process write, journal 012 finding 1 |
| Chaos-mode idea → v0.4.0 in 12 min | `state.json` `ideas[i-0002].ts` 11:29:25Z, `macro.last_reload` 11:41:16Z commit 6781fce; `chat.jsonl` for the exact `!idea` text; journal 010 |
| "when an agent is on duty" | `state.json` `agent.on_duty`; CONCEPT §3 row 14 (`no agent on duty` panel text); journal 010 |
| No fake viewers / chat rule | `docs/decisions/ADR-000-no-fake-engagement.md` |
| Category Software Development id 34 | `metrics.jsonl` `category`; `channel.json`; public API; journal 005 |
| Owner posts, agent drafts | journal 002 |
