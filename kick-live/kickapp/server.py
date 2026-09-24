#!/usr/bin/env python3
"""Local HTTP receiver that sits behind the ngrok tunnel for the Kick developer app.

Routes (all relative to the public tunnel URL):
  GET  /health                 liveness, also shows the URLs to register on Kick
  GET  /oauth/start?scope=...  builds a PKCE authorize URL and 302s the browser to id.kick.com
  GET  /oauth/callback         Kick redirects here with ?code&state; exchanges the code, saves tokens
  POST /webhooks/kick          verifies Kick-Event-Signature (RSA-SHA256 PKCS#1 v1.5) and appends
                               one JSON line per event to $RUN_DIR/webhooks.jsonl

Config comes from the environment (scripts/env.sh sources ~/.config/kick-live/env):
  KICK_CLIENT_ID, KICK_CLIENT_SECRET   from the Kick developer app
  KICK_APP_PORT                        local port (default 8787)
  KICK_PUBLIC_URL                      https://<domain> of the tunnel. If unset, read from
                                       $RUN_DIR/public_url, else asked from the ngrok API on :4040
  KICK_PUBLIC_KEY_FILE                 override Kick's webhook public key (tests only)
Stdlib + requests + cryptography. Python 3.9 compatible.
"""
import base64
import collections
import hashlib
import json
import os
import secrets
import sys
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kick_oauth as ko  # noqa: E402

RUN_DIR = ko.RUN_DIR
PORT = int(os.environ.get("KICK_APP_PORT", "8787"))
WEBHOOKS_FILE = os.path.join(RUN_DIR, "webhooks.jsonl")
CHAT_FILE = os.environ.get("CHAT_FILE", os.path.join(RUN_DIR, "chat.jsonl"))
PUBLIC_KEY_CACHE = os.path.join(RUN_DIR, "kick_public_key.pem")
PUBLIC_KEY_URL = "https://api.kick.com/public/v1/public-key"
DEFAULT_SCOPES = os.environ.get(
    "KICK_SCOPES",
    "user:read channel:read channel:write chat:write events:subscribe",
)

_pending = {}  # state -> {"verifier": str, "created": float, "scope": str}
_seen_ids = collections.OrderedDict()
_public_key = None


def log(msg):
    sys.stderr.write("%s kickapp %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), msg))
    sys.stderr.flush()


def append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(obj, separators=(",", ":")) + "\n")


def load_public_key():
    global _public_key
    if _public_key is not None:
        return _public_key
    override = os.environ.get("KICK_PUBLIC_KEY_FILE")
    if override:
        with open(override, "rb") as f:
            pem = f.read()
    elif os.path.exists(PUBLIC_KEY_CACHE):
        with open(PUBLIC_KEY_CACHE, "rb") as f:
            pem = f.read()
    else:
        r = requests.get(PUBLIC_KEY_URL, timeout=10, headers={"User-Agent": ko.UA})
        r.raise_for_status()
        pem = r.json()["data"]["public_key"].encode()
        os.makedirs(RUN_DIR, exist_ok=True)
        with open(PUBLIC_KEY_CACHE, "wb") as f:
            f.write(pem)
    _public_key = serialization.load_pem_public_key(pem)
    return _public_key


def verify_signature(msg_id, ts, body, sig_b64):
    if not (msg_id and ts and sig_b64):
        return False
    try:
        sig = base64.b64decode(sig_b64)
        signed = msg_id.encode() + b"." + ts.encode() + b"." + body
        load_public_key().verify(sig, signed, padding.PKCS1v15(), hashes.SHA256())
        return True
    except (InvalidSignature, ValueError):
        return False


def pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class Handler(BaseHTTPRequestHandler):
    server_version = "kick-live-app/0.1"

    def log_message(self, fmt, *args):
        log("%s %s" % (self.address_string(), fmt % args))

    # --- helpers ---------------------------------------------------------
    def send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, bytes):
            data = body
        elif ctype == "application/json":
            data = json.dumps(body, indent=2).encode()
        else:
            data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def html(self, code, title, text):
        page = ("<!doctype html><title>%s</title><body style='font:16px system-ui;padding:2rem'>"
                "<h2>%s</h2><pre style='white-space:pre-wrap'>%s</pre></body>" % (title, title, text))
        self.send(code, page, "text/html")

    # --- GET -------------------------------------------------------------
    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path in ("/", "/health"):
                pub = ko.public_url(required=False)
                self.send(200, {
                    "ok": True,
                    "service": "kick-live app receiver",
                    "public_url": pub or None,
                    "redirect_url": ko.redirect_uri(pub) if pub else None,
                    "webhook_url": ko.webhook_url(pub) if pub else None,
                    "client_id_set": bool(ko.client_id(required=False)),
                    "tokens": ko.token_status(),
                })
            elif u.path == "/oauth/start":
                self.oauth_start(q)
            elif u.path == "/oauth/callback":
                self.oauth_callback(q)
            elif u.path == "/webhooks/kick":
                self.send(200, {"ok": True, "hint": "POST signed Kick events here"})
            else:
                self.send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            log("error: %s\n%s" % (e, traceback.format_exc()))
            self.html(500, "kick-live: error", str(e))

    def oauth_start(self, q):
        client_id = ko.client_id()
        pub = ko.public_url()
        scope = " ".join(q.get("scope", [DEFAULT_SCOPES]))
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(24)
        now = time.time()
        for s in [s for s, v in _pending.items() if now - v["created"] > 900]:
            _pending.pop(s, None)
        _pending[state] = {"verifier": verifier, "created": now, "scope": scope}
        params = {
            "client_id": client_id,
            "redirect_uri": ko.redirect_uri(pub),
            "response_type": "code",
            "scope": scope,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        url = ko.AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)
        log("oauth start -> %s (scope=%s)" % (ko.redirect_uri(pub), scope))
        self.send(302, b"", "text/plain", {"Location": url})

    def oauth_callback(self, q):
        if "error" in q:
            self.html(400, "Kick authorization failed",
                      "%s: %s" % (q["error"][0], q.get("error_description", [""])[0]))
            return
        state = q.get("state", [None])[0]
        code = q.get("code", [None])[0]
        pending = _pending.pop(state, None) if state else None
        if not (code and pending):
            self.html(400, "kick-live: bad OAuth callback",
                      "Missing code or unknown/expired state. Start again at /oauth/start")
            return
        tokens = ko.exchange_code(code, pending["verifier"], ko.redirect_uri(ko.public_url()))
        ko.save_user_tokens(tokens)
        try:
            me = ko.api_get("/users", token=tokens["access_token"])
            d = (me.get("data") or [{}])[0]
            who = "Logged in as %s (user id %s)." % (d.get("name"), d.get("user_id"))
        except Exception as e:  # noqa: BLE001
            who = "Token saved; /users lookup failed: %s" % e
        log("oauth callback ok. %s" % who)
        self.html(200, "kick-live: Kick authorization complete",
                  "%s\nScopes: %s\nTokens saved to %s\nYou can close this tab."
                  % (who, tokens.get("scope"), ko.TOKENS_FILE))

    # --- POST ------------------------------------------------------------
    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        if u.path != "/webhooks/kick":
            self.send(404, {"error": "not found"})
            return
        h = self.headers
        msg_id = h.get("Kick-Event-Message-Id")
        ts = h.get("Kick-Event-Message-Timestamp")
        sig = h.get("Kick-Event-Signature")
        etype = h.get("Kick-Event-Type")
        ever = h.get("Kick-Event-Version")
        if not verify_signature(msg_id, ts, body, sig):
            log("webhook REJECTED bad signature type=%s id=%s" % (etype, msg_id))
            self.send(401, {"error": "invalid signature"})
            return
        if msg_id in _seen_ids:
            self.send(200, {"ok": True, "duplicate": True})
            return
        _seen_ids[msg_id] = True
        while len(_seen_ids) > 2000:
            _seen_ids.popitem(last=False)
        try:
            payload = json.loads(body.decode() or "null")
        except ValueError:
            payload = {"_raw": body.decode(errors="replace")}
        rec = {"received_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "id": msg_id, "ts": ts,
               "type": etype, "version": ever, "payload": payload}
        append_jsonl(WEBHOOKS_FILE, rec)
        if etype == "chat.message.sent" and isinstance(payload, dict):
            sender = payload.get("sender") or {}
            append_jsonl(CHAT_FILE, {
                "ts": ts, "source": "webhook", "id": payload.get("message_id") or msg_id,
                "user": sender.get("username"), "user_id": sender.get("user_id"),
                "text": payload.get("content"),
                "broadcaster": (payload.get("broadcaster") or {}).get("username"),
            })
        log("webhook ok type=%s v=%s id=%s" % (etype, ever, msg_id))
        self.send(200, {"ok": True})


def main():
    os.makedirs(RUN_DIR, exist_ok=True)
    try:
        load_public_key()
        log("Kick webhook public key loaded")
    except Exception as e:  # noqa: BLE001
        log("warning: could not load Kick public key yet (%s); will retry on first webhook" % e)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    log("listening on http://127.0.0.1:%d  (run dir %s)" % (PORT, RUN_DIR))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
