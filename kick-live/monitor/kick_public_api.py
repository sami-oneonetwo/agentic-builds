#!/usr/bin/env python
"""kick_public_api.py -- minimal OAuth-app client for https://api.kick.com/public/v1 (stdlib only).

The developer-app helper (kickapp/kick_oauth.py) lives on origin/worktree-kick-ngrok-tunnel and is not in this
tree, and it needs `requests`. This module is the stdlib twin the monitors can import: same secrets file, same
token store, same shape on disk, so the two can be used interchangeably (and refresh the same user token).

  secrets   $KICK_LIVE_ENV      default ~/.config/kick-live/env       KICK_CLIENT_ID / KICK_CLIENT_SECRET
  tokens    $KICK_TOKENS_FILE   default ~/.config/kick-live/tokens.json
            {"user": {access_token, refresh_token, expires_at, scope}, "app": {access_token, expires_at}}

Auth is the developer app only (client_credentials for reads, the authorised user token for channel writes).
No browser cookie, ever (memory rule kick-auth-oauth-only).

    import kick_public_api as ko
    ko.app_token()                                   # client_credentials token, cached in tokens.json
    ko.user_token()                                  # refreshes when < 120 s left; raises if nobody logged in
    ko.get("/categories/34", token=ko.app_token())   # parsed JSON; raises KickApiError on >= 400
    ko.request("PATCH", "/channels", ko.user_token(), body={"stream_title": "..."})

Python 3.9 compatible.
"""
from __future__ import annotations

import json
import os
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

TOKEN_URL = "https://id.kick.com/oauth/token"
API_BASE = "https://api.kick.com/public/v1"
UA = "kick-live/0.1 (+https://github.com/sami-oneonetwo/agentic-builds)"
TIMEOUT = 20.0

CONFIG_DIR = os.path.expanduser(os.environ.get("KICK_LIVE_CONFIG_DIR", "~/.config/kick-live"))
ENV_FILE = os.environ.get("KICK_LIVE_ENV", os.path.join(CONFIG_DIR, "env"))
TOKENS_FILE = os.environ.get("KICK_TOKENS_FILE", os.path.join(CONFIG_DIR, "tokens.json"))


class KickApiError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


# --------------------------------------------------------------------------- secrets
def _load_env_file() -> None:
    """Fill os.environ from the secrets file when scripts/env.sh was not sourced (env wins)."""
    if not os.path.exists(ENV_FILE):
        return
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip().replace("export ", "")
                os.environ.setdefault(k, v.strip().strip('"').strip("'"))
    except OSError:
        pass


_load_env_file()


def client_id() -> str:
    v = os.environ.get("KICK_CLIENT_ID", "")
    if not v:
        raise KickApiError("KICK_CLIENT_ID is empty (fill %s)" % ENV_FILE)
    return v


def client_secret() -> str:
    v = os.environ.get("KICK_CLIENT_SECRET", "")
    if not v:
        raise KickApiError("KICK_CLIENT_SECRET is empty (fill %s)" % ENV_FILE)
    return v


# --------------------------------------------------------------------------- token store
def _read_tokens() -> Dict[str, Any]:
    if not os.path.exists(TOKENS_FILE):
        return {}
    try:
        with open(TOKENS_FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_tokens(d: Dict[str, Any]) -> None:
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    tmp = TOKENS_FILE + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=2)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, TOKENS_FILE)


def _post_token(form: Dict[str, str]) -> Dict[str, Any]:
    data = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST", headers={
        "User-Agent": UA, "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        raise KickApiError("token endpoint %s: %s" % (e.code, body), status=e.code, body=body)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise KickApiError("token endpoint network error: %s" % e)


def app_token(min_ttl: int = 120) -> str:
    d = _read_tokens()
    t = d.get("app") or {}
    try:
        if t.get("access_token") and float(t.get("expires_at", 0)) - time.time() > min_ttl:
            return t["access_token"]
    except (TypeError, ValueError):
        pass
    resp = _post_token({"grant_type": "client_credentials", "client_id": client_id(),
                        "client_secret": client_secret()})
    d = _read_tokens()  # re-read: another writer may have refreshed the user token meanwhile
    d["app"] = {"access_token": resp["access_token"],
                "expires_at": time.time() + int(resp.get("expires_in", 3600)),
                "obtained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _write_tokens(d)
    return resp["access_token"]


def user_token(min_ttl: int = 120) -> str:
    d = _read_tokens()
    t = d.get("user")
    if not t or not t.get("access_token"):
        raise KickApiError("No user token in %s. Authorise once via the kickapp receiver (scripts/kick-app.sh login)" % TOKENS_FILE)
    try:
        if float(t.get("expires_at", 0)) - time.time() > min_ttl:
            return t["access_token"]
    except (TypeError, ValueError):
        pass
    if not t.get("refresh_token"):
        raise KickApiError("User token expired and no refresh token; re-authorise via the kickapp receiver")
    resp = _post_token({"grant_type": "refresh_token", "refresh_token": t["refresh_token"],
                        "client_id": client_id(), "client_secret": client_secret()})
    d = _read_tokens()
    d["user"] = {
        "access_token": resp["access_token"],
        "refresh_token": resp.get("refresh_token") or t.get("refresh_token"),
        "expires_at": time.time() + int(resp.get("expires_in", 3600)),
        "scope": resp.get("scope") or t.get("scope"),
        "obtained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _write_tokens(d)
    return resp["access_token"]


def user_scopes() -> str:
    return str(((_read_tokens().get("user") or {}).get("scope")) or "")


# --------------------------------------------------------------------------- API
def request(method: str, path: str, token: str, params: Optional[Dict[str, Any]] = None,
            body: Optional[Dict[str, Any]] = None, base: str = API_BASE,
            timeout: float = TIMEOUT) -> Dict[str, Any]:
    """One call against the public API. Returns parsed JSON ({} on 204). Raises KickApiError on >= 400.

    `params` values that are lists are exploded (?a=1&a=2), matching the docs' form/explode style.
    """
    url = base + path
    if params:
        pairs = []
        for k, v in params.items():
            if v is None:
                continue
            if isinstance(v, (list, tuple)):
                pairs.extend((k, str(x)) for x in v)
            else:
                pairs.append((k, str(v)))
        if pairs:
            url += "?" + urllib.parse.urlencode(pairs)
    data = None
    headers = {"Authorization": "Bearer " + token, "User-Agent": UA, "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return {}
            parsed = json.loads(raw.decode("utf-8", "replace"))
            return parsed if isinstance(parsed, dict) else {"data": parsed}
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")[:500]
        raise KickApiError("%s %s -> %s: %s" % (method.upper(), path, e.code, text), status=e.code, body=text)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise KickApiError("%s %s network error: %s" % (method.upper(), path, e))


def get(path: str, token: Optional[str] = None, **params: Any) -> Dict[str, Any]:
    return request("GET", path, token or app_token(), params=params or None)


def _req(method: str, path: str, token: str, **kw: Any) -> Dict[str, Any]:
    """kick_oauth.py-compatible spelling: ko._req("PATCH", "/channels", tok, json={...})."""
    return request(method, path, token, params=kw.get("params"), body=kw.get("json"))


if __name__ == "__main__":  # tiny status check, prints nothing secret
    d = _read_tokens()
    out = {}
    for k in ("user", "app"):
        t = d.get(k)
        out[k] = None if not t else {"expires_in_s": int(float(t.get("expires_at", 0)) - time.time()),
                                     "scope": t.get("scope"), "has_refresh": bool(t.get("refresh_token"))}
    print(json.dumps({"tokens_file": TOKENS_FILE, "client_id_set": bool(os.environ.get("KICK_CLIENT_ID")),
                      "tokens": out}, indent=2))
