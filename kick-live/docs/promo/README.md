# docs/promo — promotion pack for SHIP IT LIVE (`kick.com/atleastonce`)

Drafted by the agent on 2026-09-24/25 from the runtime files of the first live session, fact-checked and
revised 2026-09-25 00:45 UTC during the second live session. Nothing in here is committed automatically;
the owner reviews and decides.

## The rule

**The owner posts. The agent drafts.** The agent never posts to Kick, X, Discord or Slack on the
owner's behalf, never submits the featured-slot request, and never fills in the owner's contact details
(journal 002). The pack and the posts are handoff material for the owner to send as they see fit.

Two further rules carried from the repo:

- **Real numbers only.** Every figure, name and claim traces to a runtime file under
  `~/.local/share/kick-live/run/` (first session) or `~/.local/share/kick-live/run-live/` (second session),
  or to the public Kick API; the sources tables in each file say which.
  No synthetic viewers, no bot chat, no invented testimonials (ADR-000).
- **Say the numbers plainly.** The channel has 2 followers, peaked at 3 viewers in the first session and
  at 4 so far in the second. The case for featuring is the format, not the current audience, and the
  copy says so.

## What is in the folder

| File | What it is | Who reads it |
|---|---|---|
| `featured-slot-pack.md` | One page for whoever owns featured / homepage placement at Kick: channel, category, exact title, hook, what a viewer sees, why it is featurable, what happens to featured traffic, honest current numbers for both sessions, reliability evidence from Kick's own HLS playback, moderation status (live build vs planned), risks and asks, time window, contact placeholder, and a sources table for every number | The featured-placement owner, handed over by the channel owner |
| `posts.md` | Ready-to-paste copy in fenced blocks: Kick community / Discord announcement, X single post (<280 chars) and a 3-tweet thread, internal Slack note to Kick colleagues, pinned chat message; plus the exact commands viewers can type and character counts | The owner, to paste while the stream is live |
| `last_frame.png` | 1280x720 frame decoded from Kick's own HLS playback of the live show (probe `promo-1`, 2026-09-24 11:42:51 UTC). Verified byte-identical (`cmp`) to `run/probe/promo-1/last_frame.png` at 00:44 UTC on 25 Sep; that directory was removed from the run dir later that morning, so this copy is the record. sha256 `2b629d53dcc1ff66f40e10cf5e4fefdb8e47f4a1bba627c8254a404ee99031fb` | Embedded in the pack |
| `frame_grid.png` | Nine frames across 7.5 s of the same playback, showing the countdown, bar and ticker moving. Verified byte-identical to `run/probe/promo-1/frame_grid.png` at the same time. sha256 `009c2571b8e5954cb8efb583452ece7e89e58bdd304dd63c78c2c7e5a4a588bc` | Embedded in the pack |
| `probe-promo-1.json` | Excerpt of `run/probe/promo-1/probe.json` (all checks, video, audio, manifest, variants, latency; signed playlist URLs omitted), transcribed from a read of the original before the directory was removed | Source for the probe row in the pack |
| `thumb_320.png` | `last_frame.png` downscaled to 320x180 with Pillow (LANCZOS): the directory-tile legibility check. The version number, `NEXT SHIP` and the A/B/C letters read at that size. sha256 `ec02202d4d861015cb635517f52a7e0b3be6dbd122c55fbc7cd877160a2165d7` | Embedded in the pack |

PNGs under `docs/**` are allowed by `.gitignore` (`!docs/**/*.png`).

## Before the owner sends anything

1. The channel must be live. It went live again at 00:35:05 UTC on 2026-09-25 (second session, journal 013)
   and was live when this was revised; confirm on `kick.com/atleastonce` before posting.
2. Fill in the contact line in `featured-slot-pack.md`.
3. Close the blockers the pack names before asking for a featured window: populate the moderation
   blocklist (currently 0 terms), land the one pending compositor swap outside any featured window, and
   diagnose the 00:39 UTC ingest drop from the second session.
4. Re-run the probe (`run-live/probe/`) if the frame has changed materially (the second session is already
   at v0.4.5 with a different palette), and refresh the PNGs here.
