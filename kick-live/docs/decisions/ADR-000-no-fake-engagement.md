# ADR-000: No synthetic viewers or chat

Status: accepted (by default, 2026-09-24; owner may overturn)

## Context
The ask targets 100 viewers and an active chat. The channel has 2 followers. Synthetic viewers or
bot chatters would hit the number instantly.

## Decision
The pipeline never opens fake viewer sessions or posts bot chat. Reported viewer count and chat rate
are the figures Kick's API and Pusher chat return. QA "viewer agents" fetch HLS only to verify the
stream plays and are not counted as viewers.

## Consequences
- The 100-viewer target may not be met, and the report will say so.
- Effort goes into content, interactivity, and stability, which are the only levers that count.
- If the owner explicitly authorises a load test on Kick infrastructure, this ADR is superseded and
  the loop is re-scoped as a load test.
