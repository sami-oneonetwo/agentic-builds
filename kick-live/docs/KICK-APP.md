# Kick developer app: tunnel, OAuth, webhooks

How the agents get authenticated access to the official Kick API (`api.kick.com/public/v1`) and
receive Kick webhooks. Everything runs per-user on this Mac; nothing needs sudo or Homebrew.

```
browser / Kick ──https──> ngrok (NGROK_DOMAIN) ──> 127.0.0.1:8787 kickapp/server.py
                                                    ├─ GET  /oauth/start      PKCE authorize redirect
                                                    ├─ GET  /oauth/callback   code -> tokens.json
                                                    └─ POST /webhooks/kick    RSA-verified -> run/webhooks.jsonl
agents ──> kickapp/kick_oauth.py  (user_token(), app_token(), api_get/post, subscribe)
```

## One-time setup

1. **ngrok account.** Sign up (free) at https://dashboard.ngrok.com.
   - Copy the authtoken from https://dashboard.ngrok.com/get-started/your-authtoken.
   - Reserve the free static domain at https://dashboard.ngrok.com/domains (looks like
     `xxxx-yyyy.ngrok-free.app`). Without it the URL changes every restart and the Kick app breaks.
   - Put both in `~/.config/kick-live/env`:
     ```
     NGROK_AUTHTOKEN=...
     NGROK_DOMAIN=xxxx-yyyy.ngrok-free.app
     ```
2. **Bring it up and read the URLs.**
   ```bash
   kick-live/scripts/kick-app.sh up
   ```
   It starts the receiver and the tunnel and prints:
   ```
   Redirect URL:  https://<domain>/oauth/callback
   Webhook URL:   https://<domain>/webhooks/kick
   ```
3. **Create the Kick app.** The Kick account needs 2FA enabled. Go to
   https://kick.com/settings/developer, create an app, paste the two URLs above, and copy the
   Client ID and Client Secret into `~/.config/kick-live/env`:
   ```
   KICK_CLIENT_ID=...
   KICK_CLIENT_SECRET=...
   ```
   Restart the receiver so it picks them up: `scripts/kick-app.sh down && scripts/kick-app.sh up`.
4. **Authorize the channel account** (the one that owns `atleastonce`), once:
   ```bash
   kick-live/scripts/kick-app.sh login            # opens the browser; default scopes from KICK_SCOPES
   kick-live/scripts/kick-app.sh login user:read chat:write   # or explicit scopes
   ```
   Tokens land in `~/.config/kick-live/tokens.json` (mode 600) and refresh automatically.
5. **Subscribe to events** (needs `events:subscribe`):
   ```bash
   kick-live/scripts/kick-app.sh kick subscribe chat.message.sent livestream.status.updated channel.followed
   kick-live/scripts/kick-app.sh kick subscriptions
   ```
   Events arrive as one JSON line each in `kick-live/run/webhooks.jsonl`; chat messages are also
   normalised into `run/chat.jsonl` for the compositor.

## Day-to-day

| Command | Does |
|---|---|
| `scripts/kick-app.sh up` / `down` / `status` | receiver + tunnel lifecycle |
| `scripts/kick-app.sh urls` | the two URLs registered on the Kick app |
| `scripts/kick-app.sh logs` / `scripts/tunnel.sh logs` | tail logs in `run/logs/` |
| `scripts/kick-app.sh kick whoami` | `GET /users` with the user token |
| `scripts/kick-app.sh kick app-token` | client-credentials token for curl |
| http://127.0.0.1:4040 | ngrok inspector: every request through the tunnel, with replay |

From Python (any agent or tool):

```python
import sys; sys.path.insert(0, "kick-live/kickapp")
import kick_oauth as ko
ko.api_get("/channels", token=ko.user_token())              # user-scoped call, auto-refresh
ko.api_post("/chat", {"content": "hi", "type": "user"})      # needs chat:write, see ADR-000 before using
```

## Scopes (docs.kick.com/getting-started/scopes)

`user:read`, `channel:read`, `channel:write`, `channel:rewards:read`, `channel:rewards:write`,
`chat:write`, `streamkey:read`, `events:subscribe`, `moderation:ban`,
`moderation:chat_message:manage`, `kicks:read`, `ads:read`, `ads:write`.
Default requested: `user:read channel:read channel:write chat:write events:subscribe`.

## Webhook events (all version 1)

`chat.message.sent`, `channel.followed`, `channel.subscription.new`, `channel.subscription.renewal`,
`channel.subscription.gifts`, `channel.reward.redemption.updated`, `livestream.status.updated`,
`livestream.metadata.updated`, `moderation.banned`, `kicks.gifted`.

## Security notes

- Webhooks are verified with Kick's RSA public key (`GET /public/v1/public-key`, cached in
  `run/kick_public_key.pem`): SHA-256, PKCS#1 v1.5 over `messageId.timestamp.rawBody`. Bad or
  missing signatures get 401 and are not stored. Message ids are de-duplicated in memory.
- The receiver binds to 127.0.0.1 only; ngrok is the only way in.
- Secrets (`NGROK_AUTHTOKEN`, `KICK_CLIENT_SECRET`, tokens) never enter the repo. The pre-commit hook
  now also blocks those patterns. Delete `~/.config/kick-live/tokens.json` to log out.
- The ngrok inspector on :4040 shows request bodies, including OAuth callback codes. It is
  loopback-only; keep it that way.

## Verification done on 2026-09-24

Local test with a throwaway RSA key standing in for Kick's: `/health` 200 with both URLs,
`/oauth/start` 302 to `id.kick.com` with `code_challenge_method=S256`, unknown state on callback 400,
signed webhook 200 and written to `webhooks.jsonl` and `chat.jsonl`, duplicate id 200 (flagged),
tampered body 401, unsigned 401. The tunnel itself was not exercised: no ngrok authtoken was
available in this account.
