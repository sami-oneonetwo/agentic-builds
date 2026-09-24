#!/usr/bin/env python3
"""Kick OAuth token store and small API client, for the receiver and for agents.

Tokens live OUTSIDE the repo at ~/.config/kick-live/tokens.json (mode 600):
  {"user": {access_token, refresh_token, expires_at, scope}, "app": {access_token, expires_at}}

Library use (from any agent/tool):
    import kick_oauth as ko
    ko.user_token()   # refreshes automatically, raises if nobody has logged in yet
    ko.app_token()    # client_credentials token, cached
    ko.api_get("/channels", token=ko.user_token())

CLI:
    kick_oauth.py status
    kick_oauth.py urls                      redirect + webhook URLs to paste into the Kick app
    kick_oauth.py login-url [scope ...]     URL to open in a browser to authorize the channel account
    kick_oauth.py app-token | user-token    print a bearer token (for curl)
    kick_oauth.py whoami                    GET /users with the user token
    kick_oauth.py subscribe <event>[:v] ... POST /events/subscriptions (webhook method)
    kick_oauth.py subscriptions             GET /events/subscriptions
    kick_oauth.py unsubscribe <id> ...      DELETE /events/subscriptions?id=...
"""
import json
import os
import stat
import sys
import time

import requests

AUTHORIZE_URL = "https://id.kick.com/oauth/authorize"
TOKEN_URL = "https://id.kick.com/oauth/token"
API_BASE = "https://api.kick.com/public/v1"
UA = "kick-live/0.1 (+https://github.com/sami-oneonetwo/agentic-builds)"

CONFIG_DIR = os.path.expanduser(os.environ.get("KICK_LIVE_CONFIG_DIR", "~/.config/kick-live"))
ENV_FILE = os.environ.get("KICK_LIVE_ENV", os.path.join(CONFIG_DIR, "env"))
TOKENS_FILE = os.environ.get("KICK_TOKENS_FILE", os.path.join(CONFIG_DIR, "tokens.json"))
_here = os.path.dirname(os.path.abspath(__file__))
RUN_DIR = os.environ.get("RUN_DIR", os.path.join(os.path.dirname(_here), "run"))
PUBLIC_URL_FILE = os.path.join(RUN_DIR, "public_url")

EVENT_VERSIONS = {  # docs.kick.com/events/event-types, all v1 as of 2026-09-24
    "chat.message.sent": 1, "channel.followed": 1, "channel.subscription.renewal": 1,
    "channel.subscription.gifts": 1, "channel.subscription.new": 1, "channel.reward.redemption.updated": 1,
    "livestream.status.updated": 1, "livestream.metadata.updated": 1, "moderation.banned": 1, "kicks.gifted": 1,
}


def _load_env_file():
    """Fill os.environ from the secrets file if scripts/env.sh was not sourced."""
    if not os.path.exists(ENV_FILE):
        return
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip().replace("export ", "")
            v = v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)


_load_env_file()


class KickAuthError(RuntimeError):
    pass


def client_id(required=True):
    v = os.environ.get("KICK_CLIENT_ID", "")
    if required and not v:
        raise KickAuthError("KICK_CLIENT_ID is empty. Create the app at https://kick.com/settings/developer "
                            "and fill %s" % ENV_FILE)
    return v


def client_secret():
    v = os.environ.get("KICK_CLIENT_SECRET", "")
    if not v:
        raise KickAuthError("KICK_CLIENT_SECRET is empty in %s" % ENV_FILE)
    return v


def public_url(required=True):
    """The https origin of the tunnel: env, then run/public_url written by tunnel.sh, then ngrok's local API."""
    u = os.environ.get("KICK_PUBLIC_URL", "").strip()
    if not u and os.path.exists(PUBLIC_URL_FILE):
        with open(PUBLIC_URL_FILE) as f:
            u = f.read().strip()
    if not u:
        try:
            r = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=1)
            for t in r.json().get("tunnels", []):
                if t.get("public_url", "").startswith("https://"):
                    u = t["public_url"]
                    break
        except Exception:  # noqa: BLE001
            pass
    if required and not u:
        raise KickAuthError("No public URL. Start the tunnel (scripts/kick-app.sh up) or set KICK_PUBLIC_URL")
    return u.rstrip("/") if u else ""


def redirect_uri(pub=None):
    return (pub or public_url()) + "/oauth/callback"


def webhook_url(pub=None):
    return (pub or public_url()) + "/webhooks/kick"


# --- token store ------------------------------------------------------------
def _read_tokens():
    if not os.path.exists(TOKENS_FILE):
        return {}
    with open(TOKENS_FILE) as f:
        return json.load(f)


def _write_tokens(d):
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    tmp = TOKENS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=2)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, TOKENS_FILE)


def save_user_tokens(resp):
    d = _read_tokens()
    d["user"] = {
        "access_token": resp["access_token"],
        "refresh_token": resp.get("refresh_token"),
        "expires_at": time.time() + int(resp.get("expires_in", 3600)),
        "scope": resp.get("scope"),
        "obtained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _write_tokens(d)


def token_status():
    d = _read_tokens()
    out = {}
    for k in ("user", "app"):
        t = d.get(k)
        if not t:
            out[k] = "absent"
        else:
            left = int(t.get("expires_at", 0) - time.time())
            out[k] = {"expires_in_s": left, "scope": t.get("scope"), "has_refresh": bool(t.get("refresh_token"))}
    return out


def _post_token(data):
    r = requests.post(TOKEN_URL, data=data, timeout=15, headers={"User-Agent": UA, "Accept": "application/json"})
    if r.status_code != 200:
        raise KickAuthError("token endpoint %s: %s" % (r.status_code, r.text[:500]))
    return r.json()


def exchange_code(code, verifier, redirect):
    return _post_token({
        "grant_type": "authorization_code", "code": code, "client_id": client_id(),
        "client_secret": client_secret(), "redirect_uri": redirect, "code_verifier": verifier,
    })


def user_token(min_ttl=120):
    d = _read_tokens()
    t = d.get("user")
    if not t:
        raise KickAuthError("No user token. Authorize once: scripts/kick-app.sh login")
    if t["expires_at"] - time.time() > min_ttl:
        return t["access_token"]
    if not t.get("refresh_token"):
        raise KickAuthError("User token expired and no refresh token. Run scripts/kick-app.sh login")
    resp = _post_token({
        "grant_type": "refresh_token", "refresh_token": t["refresh_token"],
        "client_id": client_id(), "client_secret": client_secret(),
    })
    if not resp.get("scope"):
        resp["scope"] = t.get("scope")
    save_user_tokens(resp)
    return resp["access_token"]


def app_token(min_ttl=120):
    d = _read_tokens()
    t = d.get("app")
    if t and t["expires_at"] - time.time() > min_ttl:
        return t["access_token"]
    resp = _post_token({"grant_type": "client_credentials", "client_id": client_id(),
                        "client_secret": client_secret()})
    d["app"] = {"access_token": resp["access_token"], "expires_at": time.time() + int(resp.get("expires_in", 3600))}
    _write_tokens(d)
    return resp["access_token"]


# --- API --------------------------------------------------------------------
def _req(method, path, token, **kw):
    headers = {"Authorization": "Bearer " + token, "User-Agent": UA, "Accept": "application/json"}
    r = requests.request(method, API_BASE + path, headers=headers, timeout=20, **kw)
    if r.status_code >= 400:
        raise KickAuthError("%s %s -> %s: %s" % (method, path, r.status_code, r.text[:500]))
    return r.json() if r.content else {}


def api_get(path, token=None, **params):
    return _req("GET", path, token or user_token(), params=params or None)


def api_post(path, body, token=None):
    return _req("POST", path, token or user_token(), json=body)


def api_delete(path, token=None, **params):
    return _req("DELETE", path, token or user_token(), params=params or None)


def subscribe(events, token=None, broadcaster_user_id=None):
    items = []
    for e in events:
        name, _, ver = e.partition(":")
        if name not in EVENT_VERSIONS:
            raise KickAuthError("unknown event %r; known: %s" % (name, ", ".join(sorted(EVENT_VERSIONS))))
        items.append({"name": name, "version": int(ver or EVENT_VERSIONS[name])})
    body = {"events": items, "method": "webhook"}
    if broadcaster_user_id:
        body["broadcaster_user_id"] = int(broadcaster_user_id)
    return api_post("/events/subscriptions", body, token=token)


# --- CLI --------------------------------------------------------------------
def _main(argv):
    cmd = argv[1] if len(argv) > 1 else "status"
    args = argv[2:]
    if cmd == "status":
        print(json.dumps({"env_file": ENV_FILE, "tokens_file": TOKENS_FILE, "client_id_set": bool(client_id(False)),
                          "public_url": public_url(False) or None, "tokens": token_status()}, indent=2))
    elif cmd == "urls":
        pub = public_url()
        print("Redirect URL:  %s\nWebhook URL:   %s" % (redirect_uri(pub), webhook_url(pub)))
    elif cmd == "login-url":
        import urllib.parse
        scope = " ".join(args) if args else None
        u = public_url() + "/oauth/start" + ("?" + urllib.parse.urlencode({"scope": scope}) if scope else "")
        print(u)
    elif cmd == "app-token":
        print(app_token())
    elif cmd == "user-token":
        print(user_token())
    elif cmd == "whoami":
        print(json.dumps(api_get("/users"), indent=2))
    elif cmd == "subscribe":
        if not args:
            raise KickAuthError("usage: subscribe <event>[:version] ...")
        print(json.dumps(subscribe(args), indent=2))
    elif cmd == "subscriptions":
        print(json.dumps(api_get("/events/subscriptions"), indent=2))
    elif cmd == "unsubscribe":
        print(json.dumps(api_delete("/events/subscriptions", id=args), indent=2))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(_main(sys.argv))
    except KickAuthError as e:
        sys.stderr.write("kick_oauth: %s\n" % e)
        sys.exit(1)
