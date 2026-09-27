#!/usr/bin/env python
"""hearth frame loop. 1280x720 rgb24 at 30 fps on stdout. s16le 48 kHz stereo on a FIFO.

Does not touch kick-live run dirs. Chat is data: lines from chat.jsonl feed the fire.

  python -m hearth.compositor --self-test 90 --run-dir /tmp/hearth-x
  python -m hearth.compositor --run-dir DIR --audio-fifo PATH
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import sys
import threading
import time
from typing import List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hearth.audio import FireAudio  # noqa: E402
from hearth.chat import ChatTail  # noqa: E402
from hearth.draw import H, W, render  # noqa: E402
from hearth.sim import Hearth, mood_of  # noqa: E402

LIVE_KICK = (
    os.path.join(os.path.expanduser("~"), ".local", "share", "kick-live", "run"),
    os.path.join(os.path.expanduser("~"), ".local", "share", "kick-live", "run-live"),
)


def log(msg: str) -> None:
    sys.stderr.write("%s hearth: %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


def refuse_kick_live(run_dir: str) -> Optional[str]:
    real = os.path.realpath(run_dir)
    for d in LIVE_KICK:
        if real == os.path.realpath(d):
            return ("REFUSING: run_dir %s is the kick-live runtime. hearth has its own dir "
                    "(~/.local/share/hearth/run).") % run_dir
    for env_name in ("CHAT_FILE", "STATE_FILE", "ACTIVITY_FILE"):
        p = os.environ.get(env_name)
        if not p:
            continue
        parent = os.path.realpath(os.path.dirname(os.path.abspath(p)))
        for d in LIVE_KICK:
            if parent == os.path.realpath(d):
                return ("REFUSING: $%s points into kick-live (%s). unset it, or re-source hearth/scripts/env.sh."
                        % (env_name, p))
    return None


class Compositor:
    def __init__(self, run_dir: str, fps: float, audio_fifo: Optional[str], no_audio: bool,
                 chat_file: Optional[str] = None, replay: Optional[str] = None,
                 clock_shift: float = 0.0) -> None:
        self.run_dir = run_dir
        self.fps = float(fps)
        self.dt = 1.0 / self.fps
        self.block = int(round(48000 / self.fps))
        self.audio_fifo = audio_fifo
        self.no_audio = no_audio
        self.clock_shift = clock_shift
        self.world = Hearth()
        self.state_path = os.path.join(run_dir, "hearth.json")
        self.world.load(self.state_path)
        chat_path = chat_file or os.environ.get("CHAT_FILE") or os.path.join(run_dir, "chat.jsonl")
        self.chat_path = chat_path
        cursor = None
        if os.path.isfile(self.state_path):
            with open(self.state_path, "r", encoding="utf-8") as fh:
                cursor = json.load(fh).get("chat_cursor")
        self.tail = ChatTail(chat_path, cursor=cursor)
        self.replay = replay
        self.demo_script = None
        self.demo_t0 = None
        self.audio = None if no_audio else FireAudio(block=self.block, fps=self.fps)
        self.vq: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=8)
        self.aq: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=24)
        self.stop = False
        self.writer_error: Optional[str] = None
        self.dropped = 0
        self.saved_at = 0.0
        os.makedirs(run_dir, exist_ok=True)

    def _now(self) -> float:
        return time.time() + self.clock_shift

    def _ingest(self, now: float) -> None:
        if self.demo_script is not None:
            if self.demo_t0 is None:
                self.demo_t0 = now
            elapsed = now - self.demo_t0
            while self.demo_script and self.demo_script[0][0] <= elapsed:
                _, rec = self.demo_script.pop(0)
                rec = dict(rec)
                rec["id"] = "demo-%s-%s" % (rec.get("slug"), elapsed)
                p = self.world.ingest(rec, now)
                if p is not None and self.audio is not None:
                    pan = max(-1.0, min(1.0, (p.angle / 3.14159) - 1.0))
                    self.audio.pop(pan=pan)
            return
        for rec in self.tail.poll():
            p = self.world.ingest(rec, now)
            if p is not None and self.audio is not None:
                pan = max(-1.0, min(1.0, (p.angle / 3.14159) - 1.0))
                self.audio.pop(pan=pan)

    def _save(self, now: float, force: bool = False) -> None:
        if not force and now - self.saved_at < 2.5:
            return
        try:
            # State and consumed chat position are one atomic checkpoint.
            state = self.world.to_dict()
            state["chat_cursor"] = self.tail.checkpoint()
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(state, fh, separators=(",", ":"))
            os.replace(tmp, self.state_path)
            self.saved_at = now
        except OSError as e:
            log("save failed: %r" % (e,))

    def _writer(self, open_fn, q: "queue.Queue", name: str) -> None:
        try:
            f = open_fn()
        except Exception as e:
            self.writer_error = "%s open: %r" % (name, e)
            return
        try:
            while True:
                b = q.get()
                if b is None:
                    break
                f.write(b)
        except Exception as e:
            self.writer_error = "%s writer: %r" % (name, e)
        try:
            f.close()
        except Exception:
            pass

    def _put(self, q: "queue.Queue", b: bytes) -> None:
        if self.writer_error:
            return
        try:
            q.put(b, timeout=0.4)
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            self.dropped += 1
            try:
                q.put_nowait(b)
            except queue.Full:
                pass

    def _start_writers(self) -> None:
        threading.Thread(
            target=self._writer,
            args=(lambda: os.fdopen(os.dup(1), "wb", buffering=0), self.vq, "video"),
            daemon=True,
        ).start()
        if self.audio_fifo:
            path = self.audio_fifo

            def _open_fifo():
                # O_RDWR so we don't block waiting for ffmpeg to open the other end
                fd = os.open(path, os.O_RDWR)
                return os.fdopen(fd, "wb", buffering=0)

            threading.Thread(
                target=self._writer,
                args=(_open_fifo, self.aq, "audio"),
                daemon=True,
            ).start()

    def _frame(self, now: float, frame: int, last: Optional[object]):
        self._ingest(now)
        self.world.tick(now, self.dt)
        img = render(self.world, now, frame)
        shown = getattr(self.world, "shown_heat", self.world.heat)
        pcm = None if self.audio is None else self.audio.block_pcm(shown, mood_of(shown))
        if frame % (int(self.fps) * 2) == 0:
            log("frame=%d heat=%.3f mood=%s people=%d voices=%d dropped=%d" % (
                frame, self.world.heat, self.world.mood, len(self.world.people),
                len(self.world.voices(now)), self.dropped))
        self._save(now)
        return img, pcm

    def run(self) -> int:
        self._start_writers()
        # hill/glow cache once, before the clock starts, so frame 0 is not 177ms
        try:
            from hearth.draw import _GLOW_STOPS, _glow_at, _night
            _night()
            for hv in _GLOW_STOPS:
                _glow_at(hv)
            render(self.world, self._now(), 0)
        except Exception:
            pass
        frame = 0
        t0 = time.perf_counter()
        last = None
        while not self.stop:
            target = t0 + frame * self.dt
            now_wall = time.perf_counter()
            if now_wall < target:
                time.sleep(target - now_wall)
            elif now_wall - target > self.dt:
                # duplicate last picture rather than drift; keep crackle moving
                if last is not None:
                    img, _old = last
                    self._put(self.vq, img.tobytes())
                    if self.audio is not None and self.audio_fifo:
                        shown = getattr(self.world, "shown_heat", self.world.heat)
                        pcm = self.audio.block_pcm(shown, mood_of(shown))
                        self._put(self.aq, pcm.tobytes())
                    self.dropped += 1
                    frame += 1
                    continue
            now = self._now()
            img, pcm = self._frame(now, frame, last)
            last = (img, pcm)
            self._put(self.vq, img.tobytes())
            if pcm is not None and self.audio_fifo:
                self._put(self.aq, pcm.tobytes())
            if self.writer_error:
                log(self.writer_error)
                break
            frame += 1
        self._save(self._now(), force=True)
        self.vq.put(None)
        if self.audio_fifo:
            self.aq.put(None)
        return 0

    def run_selftest(self, n: int, out_dir: str) -> int:
        os.makedirs(out_dir, exist_ok=True)
        duration = n * self.dt
        script = _scripted_chat(duration)
        t0 = 1_000_000.0
        saves = []
        moods = []
        for i in range(n):
            now = t0 + i * self.dt
            while script and script[0][0] <= (now - t0):
                _, rec = script.pop(0)
                rec = dict(rec)
                rec["id"] = "st-%d-%s" % (i, rec.get("slug"))
                self.world.ingest(rec, now)
            self.world.tick(now, self.dt)
            img = render(self.world, now, i)
            moods.append(self.world.mood)
            keep = i in (0, n // 5, n // 2, (n * 4) // 5, n - 1) or i % max(1, n // 12) == 0
            if keep:
                img.save(os.path.join(out_dir, "frame_%04d.png" % i))
                saves.append(i)
        meta = {
            "frames": n,
            "saved": saves,
            "people": len(self.world.people),
            "heat": self.world.heat,
            "mood": self.world.mood,
            "moods_seen": sorted(set(moods)),
            "slugs": sorted(self.world.people),
        }
        with open(os.path.join(out_dir, "meta.json"), "w") as fh:
            json.dump(meta, fh, indent=2)
        log("self-test wrote %d pngs to %s people=%d mood=%s" % (len(saves), out_dir, meta["people"], meta["mood"]))
        return 0


def _scripted_chat(duration: float = 20.0) -> List:
    """A fake night for the self-test / preview. Names are fixtures, not live people.

    Packed into `duration` seconds so a short self-test still walks embers -> fire -> roar.
    """
    def msg(t, slug, text, color="#C8A078"):
        return (t, {"slug": slug, "username": slug, "content": text, "color": color, "type": "message"})
    s = max(6.0, float(duration))
    out = []
    out.append(msg(0.08 * s, "ash", "hey"))
    out.append(msg(0.14 * s, "ash", "is this on"))
    out.append(msg(0.22 * s, "jo", "warm", "#7EC8E3"))
    out.append(msg(0.28 * s, "ash", "sit"))
    out.append(msg(0.36 * s, "ren", "brought wood", "#E8A87C"))
    out.append(msg(0.42 * s, "jo", "stay"))
    out.append(msg(0.48 * s, "kip", "first", "#B4D6A8"))
    out.append(msg(0.54 * s, "ren", "the night is long"))
    names = ["ash", "jo", "ren", "kip", "nix", "boa", "sol", "mae"]
    colors = ["#C8A078", "#7EC8E3", "#E8A87C", "#B4D6A8", "#D4A5C9", "#F0C27A", "#9BB7D4", "#E07A5F"]
    t = 0.62 * s
    end = 0.92 * s
    step = max(0.08, (end - t) / 24.0)
    for i in range(24):
        slug = names[i % len(names)]
        out.append(msg(t, slug, ["fire", "more", "yes", "go", "keep"][i % 5], colors[i % len(colors)]))
        t += step
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="hearth")
    ap.add_argument("--run-dir", default=os.environ.get("RUN_DIR") or "/tmp/hearth")
    ap.add_argument("--fps", type=float, default=float(os.environ.get("STREAM_FPS") or 30))
    ap.add_argument("--audio-fifo", default=None)
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--self-test", type=int, default=0, metavar="N")
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--chat-file", default=None)
    ap.add_argument("--clock-shift", type=float, default=0.0)
    ap.add_argument("--demo", action="store_true", help="play a scripted night (fixtures, not live people)")
    a = ap.parse_args(argv)

    fifo = a.audio_fifo
    if fifo is None:
        src = os.environ.get("AUDIO_SOURCE") or ""
        if src.startswith("pipe:"):
            fifo = src[5:]
    msg = refuse_kick_live(a.run_dir)
    if msg:
        log(msg)
        return 2
    os.makedirs(a.run_dir, exist_ok=True)
    comp = Compositor(a.run_dir, a.fps, fifo, a.no_audio or bool(a.self_test),
                      chat_file=a.chat_file, clock_shift=a.clock_shift)

    def on_stop(_s=None, _f=None):
        comp.stop = True
    signal.signal(signal.SIGTERM, on_stop)
    signal.signal(signal.SIGINT, on_stop)

    if a.demo:
        dur = (a.frames / a.fps) if a.frames else 20.0
        comp.demo_script = _scripted_chat(dur)
        log("demo night packed into %.1fs" % dur)
    if a.self_test:
        out = os.path.join(a.run_dir, "selftest")
        return comp.run_selftest(a.self_test, out)
    if a.frames:
        # stream N frames then exit (preview)
        n = a.frames
        orig_stop = comp.stop

        class C:
            i = 0
        t0 = time.perf_counter()
        comp._start_writers()
        while C.i < n and not comp.stop:
            target = t0 + C.i * comp.dt
            w = time.perf_counter()
            if w < target:
                time.sleep(target - w)
            now = comp._now()
            img, pcm = comp._frame(now, C.i, None)
            comp._put(comp.vq, img.tobytes())
            if pcm is not None and fifo:
                comp._put(comp.aq, pcm.tobytes())
            C.i += 1
        comp._save(comp._now(), force=True)
        comp.vq.put(None)
        if fifo:
            comp.aq.put(None)
        time.sleep(0.2)
        return 0
    log("start run_dir=%s fps=%g chat=%s fifo=%s" % (a.run_dir, a.fps, comp.chat_path, fifo or "-"))
    return comp.run()


if __name__ == "__main__":
    sys.exit(main())
