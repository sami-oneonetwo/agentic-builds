#!/usr/bin/env python
"""relay.py - owns ffmpeg's inputs so the compositor can restart without dropping ingest.

    stream/run.sh (SOURCE=compositor) runs:
        relay.py --sock $RUN_DIR/relay.sock --audio-fifo $FIFO -- $PYTHON stream/compositor.py  | ffmpeg ...

The relay is the ONLY process whose stdout (rgb24 video) and FIFO (s16le audio) ffmpeg reads. It ticks
at fps wallclock, ALWAYS, and emits exactly one video frame + one audio block per tick:

  * a fresh frame from the connected compositor when one is queued;
  * otherwise the last good frame is repeated (first HOLD_S seconds of an outage), then a dark
    "deploying..." card that keeps the header strip of the last good frame and animates so nothing
    freezes; audio fades to silence over one block and stays silent until frames return.

So ffmpeg never sees EOF on either input and the encoder keeps its pid, its timestamps and its ingest
connection across any number of compositor restarts.

Wire protocol (unix stream socket, one client at a time, newest connection wins):
    header  struct ">4sI"  = kind (4 ascii bytes) + payload length (big-endian uint32)
    kind b"HELO"  payload = JSON {"w","h","fps","block","pid"}          (first message)
    kind b"FRM0"  payload = struct ">I" audio_len + video rgb24 (w*h*3 bytes) + audio s16le (audio_len bytes, may be 0)
    kind b"PING"  payload empty
Anything else, a wrong video length, or a payload > 16 MB closes that client.

Child supervision (the part after `--`): the relay spawns the compositor with RELAY_SOCK set, writes its
pid to --pid-file, restarts it on exit (0.2 s after a clean exit / SIGTERM, backoff 1..10 s after a crash,
reset after 60 s of healthy running). SIGTERM/SIGINT to the relay: child terminated, loop stopped, exit 0.
SIGUSR1 to the relay: restart the child (what scripts/deploy.sh may use instead of signalling the child).

Every outage is measured and logged (`gap:` lines on stderr, $ACTIVITY_FILE line actor "relay") and
mirrored to --status (JSON, rewritten every second): frames out / fresh / repeated / card, gaps[].

Python 3.9, stdlib + pillow (numpy optional). Never imports the compositor: a broken deploy must not be
able to take the relay down with it.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional, Tuple

HDR = struct.Struct(">4sI")
K_HELO, K_FRM, K_PING = b"HELO", b"FRM0", b"PING"
MAX_PAYLOAD = 16 * 1024 * 1024
HOLD_S = 0.75            # repeat the last good frame this long before switching to the card
IN_DEPTH = 4             # input queue depth before the oldest queued frame is dropped
PRIME_DEPTH = 2          # frames to buffer after a (re)connect before consuming (absorbs clock jitter)
SOCKBUF = 2 * 1024 * 1024
STATUS_EVERY_S = 1.0
LOG_EVERY_S = 10.0

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def log(msg: str) -> None:
    sys.stderr.write("%s relay: %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


def _read_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    buf = bytearray(n)
    mv = memoryview(buf)
    off = 0
    while off < n:
        got = sock.recv_into(mv[off:], n - off)
        if got <= 0:
            return None
        off += got
    return bytes(buf)


class Card(object):
    """Renders the 'deploying...' frame with pillow. Fonts/colours from stream.layout when it imports, safe defaults otherwise."""

    def __init__(self, w: int, h: int):
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401
        self.Image, self.ImageDraw = Image, ImageDraw
        self.w, self.h = w, h
        self.header_h = 72
        self.bg, self.panel, self.hair = (11, 14, 20), (17, 21, 29), (28, 33, 48)
        self.text, self.text2, self.accent = (230, 232, 238), (138, 144, 160), (83, 252, 24)
        self.f_title = self.f_body = self.f_small = None
        try:
            sys.path.insert(0, ROOT)
            from stream import layout as L
            self.f_title, self.f_body, self.f_small = L.font("HN Bold", 34), L.font("Menlo", 22), L.font("Menlo", 20)
            hx = L.hex_rgb
            self.bg, self.panel, self.hair = hx(L.COLORS["bg"]), hx(L.COLORS["panel"]), hx(L.COLORS["hairline"])
            self.text, self.text2, self.accent = hx(L.COLORS["text"]), hx(L.COLORS["text2"]), hx(L.COLORS["accent"])
        except Exception as e:  # layout may be exactly what a bad deploy broke
            log("card: stream.layout unavailable (%r), using built-in fonts" % (e,))
            for path in ("/System/Library/Fonts/HelveticaNeue.ttc", "/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf"):
                try:
                    self.f_title = ImageFont.truetype(path, 34)
                    self.f_body = ImageFont.truetype(path, 22)
                    self.f_small = ImageFont.truetype(path, 20)
                    break
                except Exception:
                    continue
            if self.f_title is None:
                self.f_title = self.f_body = self.f_small = ImageFont.load_default()
        self._base: Optional[bytes] = None       # rendered body without the moving parts, keyed on header bytes id
        self._base_key = None

    def render(self, last_frame: Optional[bytes], elapsed: float, restarts: int) -> bytes:
        img = self.Image.new("RGB", (self.w, self.h), self.bg)
        if last_frame is not None and len(last_frame) == self.w * self.h * 3:
            hdr = self.Image.frombytes("RGB", (self.w, self.h), last_frame).crop((0, 0, self.w, self.header_h))
            img.paste(hdr, (0, 0))
        d = self.ImageDraw.Draw(img)
        d.line([(0, self.header_h), (self.w, self.header_h)], fill=self.hair, width=1)
        cx, cy = self.w // 2, self.h // 2
        d.text((cx, cy - 40), "deploying…", font=self.f_title, fill=self.text, anchor="mm")
        d.text((cx, cy + 6), "compositor restarting · %.1f s · encoder untouched" % elapsed, font=self.f_body, fill=self.text2, anchor="mm")
        d.text((cx, cy + 40), "restart %d · stream stays up while the renderer reloads" % restarts, font=self.f_small, fill=self.text2, anchor="mm")
        # moving bar: 6 px, bounces once per 2 s (0.5 Hz, never a flash)
        bw, bh, span = 160, 6, 480
        ph = (elapsed % 2.0) / 2.0
        ph = ph * 2 if ph < 0.5 else (1.0 - ph) * 2
        x0 = cx - span // 2 + int(ph * (span - bw))
        d.rectangle([cx - span // 2, cy + 78, cx + span // 2, cy + 78 + bh], fill=self.panel)
        d.rectangle([x0, cy + 78, x0 + bw, cy + 78 + bh], fill=self.accent)
        return img.tobytes()


class Relay(object):
    def __init__(self, a):
        self.w, self.h, self.fps = int(a.width), int(a.height), float(a.fps)
        self.frame_dt = 1.0 / self.fps
        self.vlen = self.w * self.h * 3
        self.block = int(round(48000 / self.fps))
        self.alen = self.block * 2 * 2
        self.sock_path = a.sock
        self.run_dir = os.path.abspath(a.run_dir)
        self.audio_fifo = a.audio_fifo
        self.child_cmd: List[str] = list(a.child or [])
        self.child_log = a.child_log
        self.pid_file = a.pid_file
        self.status_path = a.status
        self.activity_file = a.activity_file
        self.max_frames = int(a.frames or 0)
        self.hold_s = float(a.hold_s)

        self.running = True
        self.inq: "queue.Queue[Tuple[bytes, bytes]]" = queue.Queue()
        self.vq: "queue.Queue" = queue.Queue(maxsize=6)
        self.aq: "queue.Queue" = queue.Queue(maxsize=64)
        self.client: Optional[socket.socket] = None
        self.client_lock = threading.Lock()
        self.client_pid: Optional[int] = None
        self.connected = False
        self.primed = False
        self.card = Card(self.w, self.h)

        self.last_video: Optional[bytes] = None
        self.last_audio: Optional[bytes] = None
        self.silence = bytes(self.alen)
        self.fresh_at: Optional[float] = None       # perf_counter of the last fresh frame
        self.gap_open: Optional[Dict] = None
        self.gaps: List[Dict] = []
        self.n = {"out": 0, "fresh": 0, "repeated": 0, "card": 0, "in_dropped": 0, "audio_dropped": 0,
                  "catchup": 0, "connects": 0, "child_restarts": 0, "protocol_errors": 0}
        self.tick_ms: List[float] = []
        self.writer_error: Optional[str] = None
        self.child: Optional[subprocess.Popen] = None
        self.child_started_at = 0.0
        self.restart_child_flag = False
        self.t_start = 0.0

    # ------------------------------------------------------------------ io helpers
    def _activity(self, text: str) -> None:
        if not self.activity_file:
            return
        try:
            ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".%03dZ" % int((time.time() % 1) * 1000)
            with open(self.activity_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": ts, "actor": "relay", "text": text[:200]}) + "\n")
        except Exception as e:
            log("activity append failed: %r" % (e,))

    def _writer(self, open_fn, q: "queue.Queue", name: str) -> None:
        # FIFO open() blocks until ffmpeg opens the read end, so it lives here, never on the tick thread
        try:
            with open_fn() as f:
                while True:
                    b = q.get()
                    if b is None:
                        return
                    f.write(b)
        except Exception as e:
            self.writer_error = "%s writer: %r" % (name, e)
            log("stopping: %s" % self.writer_error)
            self.running = False

    def _put_video(self, b: bytes) -> None:
        while self.running:
            try:
                self.vq.put(b, timeout=0.5)
                return
            except queue.Full:
                continue

    def _put_audio(self, b: bytes) -> None:
        try:
            self.aq.put_nowait(b)
        except queue.Full:                      # ffmpeg has not opened the FIFO yet: never stall video for audio
            self.n["audio_dropped"] += 1

    # ------------------------------------------------------------------ socket server
    def _serve(self) -> None:
        try:
            if os.path.exists(self.sock_path):
                os.unlink(self.sock_path)
        except OSError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.sock_path)
        srv.listen(2)
        log("listening on %s" % self.sock_path)
        while self.running:
            try:
                srv.settimeout(0.5)
                c, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError as e:
                if self.running:
                    log("accept failed: %r" % (e,))
                    time.sleep(0.2)
                continue
            threading.Thread(target=self._client, args=(c,), daemon=True).start()
        try:
            srv.close()
            os.unlink(self.sock_path)
        except OSError:
            pass

    def _client(self, c: socket.socket) -> None:
        for opt in (socket.SO_RCVBUF, socket.SO_SNDBUF):
            try:
                c.setsockopt(socket.SOL_SOCKET, opt, SOCKBUF)
            except OSError:
                pass
        c.settimeout(5.0)
        with self.client_lock:
            old = self.client
            self.client = c
            if old is not None:
                try:
                    old.close()             # newest connection wins; the old reader thread ends on its recv error
                except OSError:
                    pass
        self.n["connects"] += 1
        pid = None
        try:
            while self.running:
                hdr = _read_exact(c, HDR.size)
                if hdr is None:
                    break
                kind, ln = HDR.unpack(hdr)
                if ln > MAX_PAYLOAD:
                    self.n["protocol_errors"] += 1
                    log("client: payload %d too large, closing" % ln)
                    break
                payload = _read_exact(c, ln) if ln else b""
                if payload is None:
                    break
                if kind == K_FRM:
                    if ln < 4:
                        self.n["protocol_errors"] += 1
                        break
                    (al,) = struct.unpack(">I", payload[:4])
                    video = payload[4:4 + self.vlen]
                    audio = payload[4 + self.vlen:4 + self.vlen + al]
                    if len(video) != self.vlen or len(audio) != al or (al and al != self.alen):
                        self.n["protocol_errors"] += 1
                        log("client: bad frame lengths video=%d audio=%d (want %d/%d), closing" % (len(video), al, self.vlen, self.alen))
                        break
                    self._enqueue(video, audio)
                elif kind == K_HELO:
                    try:
                        info = json.loads(payload.decode("utf-8") or "{}")
                    except Exception:
                        info = {}
                    pid = info.get("pid")
                    with self.client_lock:
                        if self.client is c:
                            self.client_pid = pid
                    log("client connected pid=%s %s" % (pid, json.dumps(info, sort_keys=True)))
                elif kind == K_PING:
                    pass
                else:
                    self.n["protocol_errors"] += 1
                    log("client: unknown kind %r, closing" % (kind,))
                    break
        except socket.timeout:
            log("client pid=%s: no data for 5 s, dropping it" % pid)
        except OSError as e:
            if self.running and self.client is c:
                log("client pid=%s read error: %r" % (pid, e))
        finally:
            try:
                c.close()
            except OSError:
                pass
            with self.client_lock:
                if self.client is c:
                    self.client = None
                    self.client_pid = None

    def _enqueue(self, video: bytes, audio: bytes) -> None:
        self.inq.put((video, audio))
        while self.inq.qsize() > IN_DEPTH:
            try:
                self.inq.get_nowait()
                self.n["in_dropped"] += 1
            except queue.Empty:
                break

    # ------------------------------------------------------------------ child
    def _spawn_child(self) -> None:
        if not self.child_cmd:
            return
        env = dict(os.environ)
        env["RELAY_SOCK"] = self.sock_path
        # Live-state contamination guard (journal 012 #1): the child may only touch files under OUR run dir.
        # env.sh exports $STATE_FILE etc.; a shell that sourced it before setting RUN_DIR points them at the shared dir.
        env["RUN_DIR"] = self.run_dir
        for name in ("STATE_FILE", "CHAT_FILE", "ACTIVITY_FILE", "METRICS_FILE"):
            p = env.get(name)
            if p and os.path.abspath(os.path.dirname(p)) != self.run_dir:
                env.pop(name, None)
                log("child env: dropped %s=%s (outside run dir %s)" % (name, p, self.run_dir))
        if self.audio_fifo:
            env["AUDIO_SOURCE"] = "pipe:" + self.audio_fifo     # the child renders audio; the relay is the one writing the FIFO
        else:
            env.pop("AUDIO_SOURCE", None)
        errf = None
        try:
            errf = open(self.child_log, "ab", buffering=0) if self.child_log else None
            self.child = subprocess.Popen(self.child_cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                          stderr=errf if errf is not None else None, env=env, cwd=ROOT)
        except Exception as e:
            log("child spawn failed: %r" % (e,))
            self.child = None
            return
        finally:
            if errf is not None:
                errf.close()
        self.child_started_at = time.perf_counter()
        if self.pid_file:
            try:
                with open(self.pid_file, "w") as fh:
                    fh.write("%d\n" % self.child.pid)
            except OSError as e:
                log("pid file write failed: %r" % (e,))
        log("child started pid=%d: %s" % (self.child.pid, " ".join(self.child_cmd)))

    def _supervise(self) -> None:
        if not self.child_cmd:
            return
        backoff = 1.0
        self._spawn_child()
        while self.running:
            time.sleep(0.1)
            ch = self.child
            if ch is None:
                time.sleep(backoff)
                self._spawn_child()
                continue
            if self.restart_child_flag:
                self.restart_child_flag = False
                log("restart requested (SIGUSR1): terminating child pid=%d" % ch.pid)
                try:
                    ch.terminate()
                except OSError:
                    pass
            rc = ch.poll()
            if rc is None:
                continue
            ran = time.perf_counter() - self.child_started_at
            if ran >= 60.0:
                backoff = 1.0
            self.n["child_restarts"] += 1
            if rc == 0 or rc == -signal.SIGTERM:
                delay = 0.2
            else:
                delay = backoff
                backoff = min(10.0, backoff * 2)
            log("child pid=%d exited rc=%s after %.1f s; respawn in %.1f s (restart #%d)" % (ch.pid, rc, ran, delay, self.n["child_restarts"]))
            self.child = None
            end = time.perf_counter() + delay
            while self.running and time.perf_counter() < end:
                time.sleep(0.05)
            if self.running:
                self._spawn_child()
        ch = self.child
        if ch is not None and ch.poll() is None:
            try:
                ch.terminate()
                ch.wait(timeout=5)
            except Exception:
                try:
                    ch.kill()
                except OSError:
                    pass
        if self.pid_file:
            try:
                os.unlink(self.pid_file)
            except OSError:
                pass

    # ------------------------------------------------------------------ status
    def _status(self, force: bool = False) -> None:
        if not self.status_path:
            return
        d = dict(self.n)
        d.update({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pid": os.getpid(), "fps": self.fps, "connected": self.connected, "client_pid": self.client_pid,
            "child_pid": self.child.pid if self.child is not None else None,
            "uptime_s": round(time.perf_counter() - self.t_start, 1) if self.t_start else 0,
            "tick_ms_avg": round(sum(self.tick_ms[-300:]) / max(1, len(self.tick_ms[-300:])), 2),
            "gap_open": self.gap_open, "gaps": self.gaps[-20:], "writer_error": self.writer_error,
        })
        tmp = self.status_path + ".tmp"
        try:
            with open(tmp, "w") as fh:
                json.dump(d, fh)
            os.replace(tmp, self.status_path)
        except OSError as e:
            log("status write failed: %r" % (e,))

    def _report(self) -> str:
        ms = self.tick_ms[-300:]
        avg = sum(ms) / len(ms) if ms else 0.0
        mx = max(ms) if ms else 0.0
        return ("out=%d fresh=%d repeated=%d card=%d in_dropped=%d catchup=%d audio_dropped=%d connected=%s child=%s "
                "restarts=%d gaps=%d tick ms avg %.2f max %.1f" % (
                    self.n["out"], self.n["fresh"], self.n["repeated"], self.n["card"], self.n["in_dropped"], self.n["catchup"],
                    self.n["audio_dropped"], "yes" if self.connected else "no",
                    self.child.pid if self.child is not None else "-", self.n["child_restarts"], len(self.gaps), avg, mx))

    # ------------------------------------------------------------------ the tick
    def _tick(self, i: int, now_pc: float) -> None:
        item = None
        depth = self.inq.qsize()
        if depth and (self.primed or depth >= PRIME_DEPTH):
            self.primed = True
            try:
                item = self.inq.get_nowait()
            except queue.Empty:
                item = None
        if item is not None:
            video, audio = item
            self.last_video, self.last_audio = video, audio if audio else None
            self.fresh_at = now_pc
            self.n["fresh"] += 1
            if not self.connected:
                self.connected = True
            if self.gap_open is not None:
                g = self.gap_open
                g["end_frame"] = i
                g["duration_s"] = round((i - g["start_frame"]) * self.frame_dt, 2)
                g["repeated_frames"] = g["repeated"] + g["card"]
                self.gap_open = None
                self.gaps.append(g)
                msg = "gap #%d closed: compositor absent %.2f s = %d frames held (%d last-frame repeats + %d card frames); encoder never saw EOF" % (
                    len(self.gaps), g["duration_s"], g["repeated_frames"], g["repeated"], g["card"])
                log(msg)
                # the activity feed is on screen: viewer words there, the frame arithmetic stays in relay.log
                self._activity("held the picture %.1f s while the compositor came up, stream never dropped" % g["duration_s"])
            self._put_video(video)
            self._put_audio(audio if audio else self.silence)
            return
        # nothing fresh this tick
        if self.gap_open is None:
            self.gap_open = {"start_frame": i, "start_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                             "repeated": 0, "card": 0, "had_frame": self.last_video is not None}
            if self.connected or self.n["fresh"]:
                log("gap #%d opened at frame %d (queue empty%s)" % (len(self.gaps) + 1, i, "" if self.client is not None else ", no client"))
        self.connected = False
        self.primed = False
        absent = (now_pc - self.fresh_at) if self.fresh_at is not None else float("inf")
        if self.last_video is not None and absent <= self.hold_s:
            self.n["repeated"] += 1
            self.gap_open["repeated"] += 1
            self._put_video(self.last_video)
        else:
            self.n["card"] += 1
            self.gap_open["card"] += 1
            el = absent if absent != float("inf") else (now_pc - self.t_start)
            try:
                self._put_video(self.card.render(self.last_video, el, self.n["child_restarts"]))
            except Exception as e:
                log("card render failed: %r; repeating last frame" % (e,))
                self._put_video(self.last_video or bytes(self.vlen))
        # audio: fade the last real block to zero once, then silence
        if self.last_audio is not None:
            try:
                import numpy as np
                blk = np.frombuffer(self.last_audio, dtype=np.int16).reshape(-1, 2).astype(np.float32)
                ramp = np.linspace(1.0, 0.0, blk.shape[0], dtype=np.float32)[:, None]
                fade = (blk * ramp).astype(np.int16).tobytes()
            except Exception:
                fade = self.silence
            self.last_audio = None
            self._put_audio(fade)
        else:
            self._put_audio(self.silence)

    # ------------------------------------------------------------------ main loop
    def run(self) -> int:
        threading.Thread(target=self._writer, args=(lambda: os.fdopen(os.dup(1), "wb", buffering=0), self.vq, "video"), daemon=True).start()
        if self.audio_fifo:
            threading.Thread(target=self._writer, args=(lambda: open(self.audio_fifo, "wb", buffering=0), self.aq, "audio"), daemon=True).start()
        threading.Thread(target=self._serve, daemon=True).start()
        sup = threading.Thread(target=self._supervise, daemon=True)
        sup.start()
        self._activity("relay start fps=%g sock=%s audio=%s child=%s" % (self.fps, self.sock_path, "fifo" if self.audio_fifo else "none",
                                                                        "yes" if self.child_cmd else "no"))
        self.t_start = time.perf_counter()
        i = 0
        last_log = last_status = self.t_start
        while self.running:
            target = self.t_start + i * self.frame_dt
            now_pc = time.perf_counter()
            if now_pc < target:
                time.sleep(target - now_pc)
                now_pc = time.perf_counter()
            t0 = now_pc
            try:
                self._tick(i, now_pc)
            except Exception as e:                       # the loop must outlive any bug in here
                log("tick %d failed: %r; emitting last frame" % (i, e))
                self._put_video(self.last_video or bytes(self.vlen))
                self._put_audio(self.silence)
            self.n["out"] += 1
            i += 1
            self.tick_ms.append((time.perf_counter() - t0) * 1000.0)
            if len(self.tick_ms) > 3000:
                del self.tick_ms[:-3000]
            # catch-up: if the tick thread stalled (stdout blocked), emit extra ticks rather than drift
            behind = (time.perf_counter() - self.t_start) / self.frame_dt - i
            k = 0
            while behind >= 1.0 and k < 3 and self.running:
                try:
                    self._tick(i, time.perf_counter())
                except Exception:
                    self._put_video(self.last_video or bytes(self.vlen))
                    self._put_audio(self.silence)
                self.n["out"] += 1
                self.n["catchup"] += 1
                i += 1; k += 1; behind -= 1.0
            if now_pc - last_status >= STATUS_EVERY_S:
                last_status = now_pc
                self._status()
            if now_pc - last_log >= LOG_EVERY_S:
                last_log = now_pc
                log(self._report())
            if self.max_frames and i >= self.max_frames:
                break
        self.running = False
        for q in (self.vq, self.aq):
            try:
                q.put(None, timeout=0.5)
            except queue.Full:
                pass
        sup.join(timeout=8.0)
        if self.gap_open is not None:
            g = self.gap_open
            g["end_frame"] = i
            g["duration_s"] = round((i - g["start_frame"]) * self.frame_dt, 2)
            g["repeated_frames"] = g["repeated"] + g["card"]
            g["unclosed"] = True
            self.gaps.append(g)
            self.gap_open = None
        self._status(force=True)
        log("exit: " + self._report())
        self._activity("relay stop after %d frames (%s)" % (self.n["out"], self.writer_error or "clean"))
        return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    run_dir = os.environ.get("RUN_DIR") or os.path.join(ROOT, "run")
    ap.add_argument("--sock", default=os.path.join(run_dir, "relay.sock"), help="unix socket path (default $RUN_DIR/relay.sock)")
    ap.add_argument("--run-dir", default=run_dir, help="run dir the child may write to (default $RUN_DIR); its env is sanitised to it")
    ap.add_argument("--audio-fifo", default=None, help="s16le FIFO to write (default from AUDIO_SOURCE=pipe:PATH; none otherwise)")
    ap.add_argument("--fps", type=float, default=float(os.environ.get("STREAM_FPS") or 30))
    ap.add_argument("--width", type=int, default=int(os.environ.get("STREAM_WIDTH") or 1280))
    ap.add_argument("--height", type=int, default=int(os.environ.get("STREAM_HEIGHT") or 720))
    ap.add_argument("--frames", type=int, default=0, help="stop after N output frames (tests)")
    ap.add_argument("--hold-s", type=float, default=HOLD_S, help="repeat the last frame this long before the card (default %.2f)" % HOLD_S)
    ap.add_argument("--pid-file", default=None, help="where to write the child's pid (default $PID_DIR/compositor.pid)")
    ap.add_argument("--child-log", default=None, help="child stderr appended here (default: inherit)")
    ap.add_argument("--status", default=os.path.join(run_dir, "relay_status.json"), help="status JSON, rewritten every second")
    ap.add_argument("--activity-file", default=os.environ.get("ACTIVITY_FILE") or os.path.join(run_dir, "activity.jsonl"))
    ap.add_argument("child", nargs=argparse.REMAINDER, help="-- <compositor command to spawn and supervise>")
    a = ap.parse_args(argv)
    if a.child and a.child[0] == "--":
        a.child = a.child[1:]
    if a.audio_fifo is None:
        src = os.environ.get("AUDIO_SOURCE") or ""
        if src.startswith("pipe:"):
            a.audio_fifo = src[len("pipe:"):]
    if a.audio_fifo and not os.path.exists(a.audio_fifo):
        log("audio fifo %s does not exist; running video-only" % a.audio_fifo)
        a.audio_fifo = None
    if a.pid_file is None:
        pid_dir = os.environ.get("PID_DIR") or os.path.join(run_dir, "pids")
        try:
            os.makedirs(pid_dir, exist_ok=True)
            a.pid_file = os.path.join(pid_dir, "compositor.pid")
        except OSError:
            a.pid_file = None
    os.makedirs(os.path.dirname(os.path.abspath(a.sock)), exist_ok=True)

    r = Relay(a)

    def _stop(signum, _f):
        log("signal %d, stopping" % signum)
        r.running = False

    def _restart(signum, _f):
        r.restart_child_flag = True
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGUSR1, _restart)
    log("start fps=%g %dx%d block=%d sock=%s audio=%s child=%s" % (a.fps, a.width, a.height, r.block, a.sock, a.audio_fifo or "none",
                                                                  " ".join(a.child) if a.child else "none"))
    return r.run()


if __name__ == "__main__":
    sys.exit(main())
