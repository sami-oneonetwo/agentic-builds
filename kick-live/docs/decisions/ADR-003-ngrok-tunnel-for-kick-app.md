# ADR-003: ngrok tunnel with a reserved domain fronts the Kick developer app

Status: accepted (2026-09-24)

## Context
The official Kick API needs an OAuth app (Client ID/Secret) with a registered redirect URL, and
Kick webhooks need a public HTTPS endpoint. The agents run on a laptop behind NAT with no public
DNS. The owner asked for an ngrok tunnel to supply both URLs.

## Decision
- A single local receiver (`kickapp/server.py`, 127.0.0.1:8787) serves `/oauth/callback` and
  `/webhooks/kick`. One tunnel, one domain, two paths.
- ngrok v3 static binary at `~/.local/bin/ngrok` (Homebrew belongs to another account). The
  authtoken is passed via the `NGROK_AUTHTOKEN` environment variable from `~/.config/kick-live/env`,
  so no ngrok config file holding a secret is written.
- A **reserved ngrok domain** (`NGROK_DOMAIN`, free tier includes one) is required in practice:
  Kick validates the redirect URL exactly, and an ephemeral URL would need the app re-edited on
  every restart. The script warns loudly if it is missing.
- Webhook signatures are verified with Kick's published RSA key before anything is stored.
- Tokens are stored outside the repo and refreshed by `kickapp/kick_oauth.py`, which is also the
  library agents import. Agents never see the client secret directly.

## Alternatives considered
- Cloudflare Tunnel: needs a domain in Cloudflare; not available here.
- Polling the unofficial `kick.com/api/v2` and Pusher only (current monitor plan): keeps working for
  read-only metrics and stays as the fallback, but gives no write access (title, chat) and no
  signed events.
- Running the receiver on a VPS: more moving parts than the task warrants today.

## Consequences
- The laptop must be awake with `scripts/kick-app.sh up` running for callbacks and webhooks to land.
- Free ngrok shows an interstitial page on the first browser visit to the domain; this affects the
  OAuth redirect only cosmetically (the browser clicks through once) and does not affect webhooks.
- If the domain ever changes, the Kick app's two URLs must be updated by hand.
