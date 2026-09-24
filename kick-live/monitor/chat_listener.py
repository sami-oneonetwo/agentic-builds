#!/usr/bin/env python
"""Kick chat listener (Pusher websocket) for chatroom 41370704.

Connects to Kick's public Pusher endpoint, subscribes to ``chatrooms.<id>.v2``,
and appends one JSON line per chat message to $CHAT_FILE. Every 10 s it rewrites
$RUN_DIR/chat_stats.json atomically with rolling chat-rate figures. Connection
state is logged to stderr and appended to $ACTIVITY_FILE (actor "chat").

Read-only: this program never sends chat messages and never authenticates.

Environment (all optional; defaults match scripts/env.sh):
  RUN_DIR            runtime dir            default <repo>/run
  CHAT_FILE          chat jsonl             default $RUN_DIR/chat.jsonl
  ACTIVITY_FILE      on-screen feed jsonl   default $RUN_DIR/activity.jsonl
  KICK_CHATROOM_ID   chatroom id            default 41370704
  KICK_PUSHER_URL    websocket url          default wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679?...

Examples:
  chat_listener.py --duration 40                 # live for 40 s, then exit 0
  chat_listener.py --replay fixtures/pusher_frames.jsonl   # offline parser test
  chat_listener.py                               # run until SIGINT/SIGTERM
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- paths
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RUN_DIR = os.environ.get("RUN_DIR") or os.path.join(REPO, "run")
CHAT_FILE = os.environ.get("CHAT_FILE") or os.path.join(RUN_DIR, "chat.jsonl")
ACTIVITY_FILE = os.environ.get("ACTIVITY_FILE") or os.path.join(RUN_DIR, "activity.jsonl")
STATS_FILE = os.path.join(RUN_DIR, "chat_stats.json")
CHATROOM_ID = int(os.environ.get("KICK_CHATROOM_ID") or 41370704)
PUSHER_URL = os.environ.get("KICK_PUSHER_URL") or (
    "wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679"
    "?protocol=7&client=js&version=8.4.0&flash=false"
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

IDLE_PING_SECONDS = 60.0      # send our own pusher:ping after this much silence
PONG_TIMEOUT_SECONDS = 30.0   # if nothing arrives after our ping, reconnect
STATS_INTERVAL_SECONDS = 10.0
BACKOFF_MAX_SECONDS = 60.0
WARM_WINDOW_SECONDS = 15 * 60

log = logging.getLogger("chat")


# --------------------------------------------------------------------------- helpers
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_iso(ts: str) -> Optional[float]:
    """ISO-8601 (with Z or offset) -> epoch seconds, or None."""
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Python 3.9 fromisoformat does not accept more than 6 fractional digits.
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            head, _, tail = s.partition(".")
            frac = ""
            off = ""
            for i, ch in enumerate(tail):
                if ch in "+-":
                    frac, off = tail[:i], tail[i:]
                    break
            else:
                frac = tail
            dt = datetime.fromisoformat(head + "." + (frac[:6] or "0").ljust(6, "0") + off)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_json_atomic(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    os.replace(tmp, path)


def activity(text: str, activity_file: Optional[str]) -> None:
    """Append an on-screen feed line. activity_file=None disables the feed (--no-activity)."""
    if not activity_file:
        return
    try:
        append_jsonl(activity_file, {"ts": utc_now_iso(), "actor": "chat", "text": text})
    except OSError as exc:  # never let the feed kill the listener
        log.warning("activity write failed: %s", exc)


# --------------------------------------------------------------------------- parsing
def parse_frame(raw: str) -> Optional[Dict[str, Any]]:
    """Raw websocket text -> {'event': str, 'channel': str|None, 'data': Any}.

    Pusher wraps payloads as a JSON *string* inside ``data``; we decode one level.
    Returns None for anything that is not a Pusher frame.
    """
    try:
        frame = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(frame, dict) or "event" not in frame:
        return None
    data = frame.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            pass  # leave as string
    return {"event": str(frame["event"]), "channel": frame.get("channel"), "data": data}


def badge_types(sender: Dict[str, Any]) -> List[str]:
    identity = sender.get("identity") or {}
    out: List[str] = []
    for b in identity.get("badges") or []:
        if isinstance(b, dict):
            t = b.get("type") or b.get("text")
            if t:
                out.append(str(t))
        elif isinstance(b, str):
            out.append(b)
    return out


def normalize_chat_message(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """ChatMessageEvent payload -> flat record for chat.jsonl."""
    if not isinstance(data, dict):
        return None
    sender = data.get("sender") or {}
    identity = sender.get("identity") or {}
    content = data.get("content")
    if content is None:
        return None
    return {
        "ts": utc_now_iso(),
        "created_at": data.get("created_at"),
        "id": data.get("id"),
        "chatroom_id": data.get("chatroom_id"),
        "sender_id": sender.get("id"),
        "username": sender.get("username"),
        "slug": sender.get("slug"),
        "content": str(content),
        "color": identity.get("color"),
        "badges": badge_types(sender),
        "type": data.get("type") or "message",
    }


def short_event_name(event: str) -> str:
    return event.rsplit("\\", 1)[-1]


# --------------------------------------------------------------------------- stats
class ChatStats:
    """Rolling stats from an in-memory deque of (epoch_seconds, username)."""

    def __init__(self) -> None:
        self.entries: Deque[Tuple[float, str]] = deque()
        self.total_session = 0
        self.last_message_ts: Optional[str] = None
        self.last_username: Optional[str] = None
        self.connected = False
        self.reconnects = 0
        self.started_at = utc_now_iso()

    def prune(self, now: float) -> None:
        cutoff = now - WARM_WINDOW_SECONDS
        while self.entries and self.entries[0][0] < cutoff:
            self.entries.popleft()

    def add(self, epoch: float, username: str, ts_iso: str, live: bool = True) -> None:
        self.entries.append((epoch, username or ""))
        if live:
            self.total_session += 1
        if self.last_message_ts is None or (parse_iso(self.last_message_ts) or 0) <= epoch:
            self.last_message_ts = ts_iso
            self.last_username = username

    def warm_from_file(self, path: str, now: Optional[float] = None) -> int:
        """Load the last 15 min of chat.jsonl into the deque. Returns rows loaded."""
        now = now or time.time()
        if not os.path.exists(path):
            return 0
        loaded = 0
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as fh:
                fh.seek(max(0, size - 4 * 1024 * 1024))
                blob = fh.read()
            lines = blob.split(b"\n")
            if size > len(blob):
                lines = lines[1:]  # first line may be partial
            rows: List[Tuple[float, str, str]] = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line.decode("utf-8", "replace"))
                except ValueError:
                    continue
                epoch = parse_iso(obj.get("ts") or "") or parse_iso(obj.get("created_at") or "")
                if epoch is None or epoch < now - WARM_WINDOW_SECONDS:
                    continue
                rows.append((epoch, obj.get("username") or "", obj.get("ts") or obj.get("created_at") or ""))
            rows.sort(key=lambda r: r[0])
            for epoch, user, ts in rows:
                self.add(epoch, user, ts, live=False)
                loaded += 1
        except OSError as exc:
            log.warning("warm-up read of %s failed: %s", path, exc)
        return loaded

    def snapshot(self, now: Optional[float] = None) -> Dict[str, Any]:
        now = now or time.time()
        self.prune(now)
        m1 = m5 = 0
        u5, u15 = set(), set()
        for epoch, user in self.entries:
            age = now - epoch
            if age <= 60:
                m1 += 1
            if age <= 300:
                m5 += 1
                u5.add(user.lower())
            u15.add(user.lower())
        return {
            "ts": utc_now_iso(),
            "msgs_last_1m": m1,
            "msgs_per_min_5m": round(m5 / 5.0, 2),
            "unique_chatters_5m": len(u5),
            "unique_chatters_15m": len(u15),
            "total_session": self.total_session,
            "last_message_ts": self.last_message_ts,
            "last_username": self.last_username,
            "connected": self.connected,
            "reconnects": self.reconnects,
            "chatroom_id": CHATROOM_ID,
            "started_at": self.started_at,
        }


# --------------------------------------------------------------------------- event handling
class Listener:
    def __init__(
        self,
        chatroom_id: int,
        chat_file: Optional[str],
        stats_file: Optional[str],
        activity_file: Optional[str],
        echo: bool = False,
    ) -> None:
        self.chatroom_id = chatroom_id
        self.chat_file = chat_file
        self.stats_file = stats_file
        self.activity_file = activity_file
        self.echo = echo
        self.stats = ChatStats()
        self.stop = asyncio.Event()
        self.subscribed = False

    # -- events --------------------------------------------------------------
    def handle_frame(self, raw: str) -> Optional[Dict[str, Any]]:
        """Parse one frame and act on it. Returns the normalized chat record if any."""
        frame = parse_frame(raw)
        if frame is None:
            log.debug("non-pusher frame ignored: %.120s", raw)
            return None
        event, data = frame["event"], frame["data"]
        name = short_event_name(event)

        if name == "ChatMessageEvent":
            rec = normalize_chat_message(data)
            if rec is None:
                log.debug("ChatMessageEvent without content: %.200s", raw)
                return None
            epoch = parse_iso(rec["ts"]) or time.time()
            self.stats.add(epoch, rec["username"] or "", rec["ts"], live=True)
            if self.chat_file:
                try:
                    append_jsonl(self.chat_file, rec)
                except OSError as exc:
                    log.error("chat write failed: %s", exc)
            if self.echo:
                sys.stdout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                sys.stdout.flush()
            log.info("msg %s: %s", rec["username"], rec["content"][:120])
            return rec

        if event == "pusher:connection_established":
            sid = data.get("socket_id") if isinstance(data, dict) else None
            to = data.get("activity_timeout") if isinstance(data, dict) else None
            log.info("connection_established socket_id=%s activity_timeout=%s", sid, to)
        elif event == "pusher_internal:subscription_succeeded":
            self.subscribed = True
            log.info("subscription_succeeded channel=%s", frame["channel"])
        elif event == "pusher:error":
            log.warning("pusher:error %s", data)
        elif event in ("pusher:ping", "pusher:pong"):
            log.debug("%s", event)
        else:
            # MessageDeletedEvent, UserBannedEvent, UserUnbannedEvent, PinnedMessageCreatedEvent,
            # PinnedMessageDeletedEvent, ChatroomUpdatedEvent, StreamHostEvent, GiftedSubscriptions...
            log.debug("event %s on %s: %.200s", name, frame["channel"], json.dumps(data, ensure_ascii=False) if data is not None else "")
        return None

    # -- stats ---------------------------------------------------------------
    def write_stats(self) -> Dict[str, Any]:
        snap = self.stats.snapshot()
        if self.stats_file:
            try:
                write_json_atomic(self.stats_file, snap)
            except OSError as exc:
                log.error("stats write failed: %s", exc)
        return snap

    async def stats_loop(self, interval: float) -> None:
        while not self.stop.is_set():
            self.write_stats()
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    # -- network -------------------------------------------------------------
    async def run_connection(self) -> None:
        """One websocket session. Returns when the socket closes or errors."""
        from websockets.asyncio.client import connect  # websockets >= 13

        channel = "chatrooms.%d.v2" % self.chatroom_id
        log.info("connecting %s", PUSHER_URL.split("?")[0])
        async with connect(
            PUSHER_URL,
            additional_headers={"User-Agent": USER_AGENT, "Origin": "https://kick.com"},
            ping_interval=None,  # Pusher has its own app-level ping/pong
            open_timeout=20,
            close_timeout=5,
            max_size=2 ** 20,
        ) as ws:
            self.stats.connected = True
            self.subscribed = False
            self._activity("chat listener connected")
            await ws.send(json.dumps({"event": "pusher:subscribe", "data": {"auth": "", "channel": channel}}))
            log.info("subscribe sent channel=%s", channel)
            awaiting_pong_since: Optional[float] = None
            while not self.stop.is_set():
                timeout = PONG_TIMEOUT_SECONDS if awaiting_pong_since else IDLE_PING_SECONDS
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    if awaiting_pong_since:
                        raise ConnectionError("no data %.0fs after our pusher:ping" % PONG_TIMEOUT_SECONDS)
                    await ws.send(json.dumps({"event": "pusher:ping", "data": {}}))
                    awaiting_pong_since = time.time()
                    log.debug("idle %.0fs, sent pusher:ping", IDLE_PING_SECONDS)
                    continue
                awaiting_pong_since = None
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", "replace")
                frame = parse_frame(raw)
                if frame and frame["event"] == "pusher:ping":
                    await ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
                    log.debug("pusher:ping -> pong")
                    continue
                if frame and frame["event"] == "pusher_internal:subscription_succeeded":
                    self._activity("chat listener subscribed to %s" % channel)
                if frame and frame["event"] == "pusher:error":
                    code = frame["data"].get("code") if isinstance(frame["data"], dict) else None
                    try:
                        code = int(code) if code is not None else None
                    except (TypeError, ValueError):
                        code = None
                    if code and 4000 <= code < 4100:
                        # 4000-4099: reconnecting won't help (bad app key etc.), but keep trying slowly
                        self.handle_frame(raw)
                        raise ConnectionError("pusher fatal error %s" % code)
                try:
                    self.handle_frame(raw)
                except Exception as exc:  # parser bug must not drop the socket
                    log.exception("handler error on frame %.200s: %s", raw, exc)

    async def run_forever(self) -> None:
        backoff = 1.0
        while not self.stop.is_set():
            t0 = time.time()
            try:
                await self.run_connection()
                reason = "closed"
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # ConnectionClosed, OSError, InvalidStatus, ConnectionError...
                reason = "%s: %s" % (type(exc).__name__, str(exc)[:200] or "-")
            finally:
                was_connected = self.stats.connected
                self.stats.connected = False
                self.subscribed = False
            if self.stop.is_set():
                break
            if was_connected:
                self._activity("chat listener disconnected (%s)" % reason.split(":")[0])
            # a session that lasted a while earns a fresh backoff
            if time.time() - t0 > 120:
                backoff = 1.0
            log.warning("disconnected (%s); reconnecting in %.0fs", reason, backoff)
            self.stats.reconnects += 1
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=backoff)
                break
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, BACKOFF_MAX_SECONDS)

    async def run(self, duration: Optional[float], stats_interval: float) -> int:
        loop = asyncio.get_running_loop()
        # Python 3.9: an Event made outside the running loop binds to the wrong loop.
        self.stop = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._request_stop, sig)
            except (NotImplementedError, RuntimeError):
                pass
        warmed = self.stats.warm_from_file(self.chat_file) if self.chat_file else 0
        log.info("warm-up: %d messages from the last 15 min of %s", warmed, self.chat_file)
        self._activity("chat listener starting (chatroom %d)" % self.chatroom_id)
        stats_task = loop.create_task(self.stats_loop(stats_interval), name="stats")
        net_task = loop.create_task(self.run_forever(), name="net")
        # A signal only sets self.stop; the recv loop may be parked in ws.recv() for up to
        # IDLE_PING_SECONDS, so wait on the stop event too and cancel the network task on exit.
        stop_task = loop.create_task(self.stop.wait(), name="stop")
        try:
            done, _ = await asyncio.wait(
                {net_task, stop_task},
                timeout=duration if duration is not None else None,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                log.info("duration %.0fs reached, exiting", duration)
        finally:
            self.stop.set()
            for t in (net_task, stats_task, stop_task):
                if not t.done():
                    t.cancel()
            for t in (net_task, stats_task, stop_task):
                try:
                    await t
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    log.error("task %s died: %s: %s", t.get_name(), type(exc).__name__, exc)
            self.stats.connected = False
            snap = self.write_stats()
            self._activity("chat listener stopped (total_session=%d)" % snap["total_session"])
            log.info("final stats: %s", json.dumps(snap))
        return 0

    def _activity(self, text: str) -> None:
        activity(text, self.activity_file)

    def _request_stop(self, sig: int) -> None:
        log.info("signal %s received, stopping", sig)
        self.stop.set()


# --------------------------------------------------------------------------- replay
def replay(path: str, out_file: Optional[str]) -> int:
    """Feed raw Pusher frames (one JSON per line) through the parser. No network."""
    lst = Listener(CHATROOM_ID, chat_file=out_file, stats_file=None, activity_file=None, echo=True)
    n_frames = n_msgs = 0
    try:
        fh = open(path, "r", encoding="utf-8")
    except OSError as exc:
        log.error("cannot read replay file %s: %s", path, exc)
        return 2
    with fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            n_frames += 1
            frame = parse_frame(line)
            name = short_event_name(frame["event"]) if frame else "invalid"
            rec = lst.handle_frame(line)
            if rec:
                n_msgs += 1
            else:
                sys.stdout.write(json.dumps({"event": name, "channel": frame["channel"] if frame else None,
                                             "handled": frame is not None}) + "\n")
    snap = lst.stats.snapshot()
    sys.stdout.write(json.dumps({"replay_summary": {"frames": n_frames, "chat_messages": n_msgs,
                                                    "stats": snap}}, ensure_ascii=False) + "\n")
    return 0 if n_frames else 1


# --------------------------------------------------------------------------- main
def main(argv: Optional[List[str]] = None) -> int:
    global CHATROOM_ID, ACTIVITY_FILE
    ap = argparse.ArgumentParser(
        prog="chat_listener.py",
        description=__doc__.split("\n\n")[0],
        epilog="\n".join(__doc__.split("\n\n")[1:]),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--duration", type=float, metavar="N", help="run for N seconds then exit 0 (0 = connect, write stats once, exit)")
    ap.add_argument("--replay", metavar="FILE", help="offline: parse raw Pusher frames from FILE (jsonl), print records, no network")
    ap.add_argument("--replay-out", metavar="FILE", help="with --replay: also append parsed records to FILE (default: none, so fixtures never pollute chat.jsonl)")
    ap.add_argument("--chatroom", type=int, default=CHATROOM_ID, help="chatroom id (default %d)" % CHATROOM_ID)
    ap.add_argument("--stats-interval", type=float, default=STATS_INTERVAL_SECONDS, help="seconds between chat_stats.json rewrites (default 10)")
    ap.add_argument("--echo", action="store_true", help="also print each chat record to stdout in live mode")
    ap.add_argument("--no-activity", action="store_true", help="do not write to the activity feed")
    ap.add_argument("-v", "--verbose", action="store_true", help="debug logging (shows every non-chat event)")
    args = ap.parse_args(argv)
    if args.duration is not None and args.duration < 0:
        ap.error("--duration must be >= 0")
    if args.stats_interval < 1:
        ap.error("--stats-interval must be >= 1 second")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [chat] %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stderr,
    )
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    CHATROOM_ID = args.chatroom
    if args.no_activity:
        ACTIVITY_FILE = None  # type: ignore[assignment]

    if args.replay:
        return replay(args.replay, args.replay_out)

    os.makedirs(RUN_DIR, exist_ok=True)
    lst = Listener(args.chatroom, chat_file=CHAT_FILE, stats_file=STATS_FILE,
                   activity_file=ACTIVITY_FILE, echo=args.echo)
    log.info("chat_file=%s stats_file=%s activity_file=%s", CHAT_FILE, STATS_FILE, ACTIVITY_FILE)
    try:
        return asyncio.run(lst.run(args.duration, args.stats_interval))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
