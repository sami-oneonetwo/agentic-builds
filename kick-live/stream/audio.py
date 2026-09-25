"""audio.py - the generated soundtrack (CONCEPT section 6), synthesised in numpy inside the frame loop.

    engine = AudioEngine(sr=48000, block=1600, fps=30)
    pcm = engine.block(frame_index, ctx)      # -> np.int16 array, shape (1600, 2), lockstep with the frame
    engine.last_block                          # the same array (the scope panel draws its left channel)
    engine.level_dbfs                          # RMS of the last block in dBFS (float, -120 when silent)
    engine.trigger(name, **kw)                 # external event: "vote"(semitones=) | "ship" | "fail" | "builder"
                                               #                  | "pluck"(user=) | "theme" | "tick"(semitones=)

Layers (all float64 in -1..1, summed before the master):
  pad      3 detuned voices per chord tone (sine, sine +1 oct, 4-harmonic triangle), Am F C G loop (i VI III VII),
           chord change every 8 bars, one-pole low-pass at 1.2 kHz with a 0.1 Hz LFO on the cutoff applied
           spectrally (exact for stationary partials, zero per-sample cost), 6 s attack on chord changes,
           8 ms Haas offset for width, 3 dB sidechain dip on every kick               -24 dBFS
  pulse    tempo 85 BPM default (ctx.micro.audio_tempo / ctx.audio_cfg.tempo in {72, 85, 100}, applied at the
           next bar), sine kick 60->40 Hz sweep with exponential decay on beats 1 and 3, filtered-noise hat
           on the off-beat 8ths                                                       -30 dBFS
  texture  sparse impulse noise through a ~2 kHz low-pass (vinyl crackle)             -40 dBFS
  pluck    Karplus-Strong string per rendered chat message (new id in ctx.chat), pitch = A-minor pentatonic
           degree from a stable hash of the username % 10 over two octaves (A3..G5), 300 ms, through a 375 ms
           comb delay (0.35 feedback); rate-limited to 1 per 250 ms and auto-muted above 10 msg/min
                                                                                       -20 dBFS
  vote     30 ms sine, A4 + one semitone per vote in the round (reset on round change) -20 dBFS
  tick     filtered click each second for the last 10 s of a micro round; quarter-note tick rising a semitone
           every 10 s for the last 60 s of a macro deadline                            -22 dBFS
  ship     major arpeggio A-C#-E over 400 ms (ctx.version.string changed)              -16 dBFS
  fail     descending minor third on a detuned saw, 300 ms, plus an 80 Hz thud (ctx.version.failed grew)
                                                                                       -16 dBFS
  builder  two ascending notes G5-C6, 200 ms (ctx.new_builders grew)                  -20 dBFS
  theme    600 ms low-pass sweep on the pad (ctx.theme.set_ts changed)                 n/a

Master: fixed gain so the bed sits at about -18 dBFS integrated (see MASTER_GAIN, calibrated against
ffmpeg volumedetect), then a tanh soft limiter into a -6 dBFS peak ceiling: it cannot clip by construction.
The engine never raises out of block(): on any internal error it returns silence for that block.
Python 3.9; numpy only.
"""
from __future__ import annotations

import math
import sys
import zlib
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

SR = 48000
BLOCK = 1600
TEMPOS = (72, 85, 100)



def db(x: float) -> float:
    """dBFS -> linear amplitude."""
    return 10 ** (x / 20.0)


# ---- levels (dBFS RMS of the layer alone, before MASTER_GAIN) -------------------------------------------
LVL_PAD = -24.0
LVL_PULSE = -30.0
LVL_TEXTURE = -40.0
LVL_PLUCK = -20.0
LVL_VOTE = -20.0
LVL_TICK = -22.0
LVL_SHIP = -16.0
LVL_FAIL = -16.0
LVL_BUILDER = -20.0
# The bed (pad + pulse + texture) sums to about -23.3 dBFS; this trim lands it at -18 dBFS integrated.
# Calibrated with: $FFMPEG -f s16le -ar 48000 -ac 2 -i bed.pcm -af volumedetect  (mean_volume -18.x dB)
MASTER_GAIN = 1.78
# raw layer RMS measured over 15 s (stream/audio.py calibration): pad -1.06, pulse -17.67, texture -41.16 dBFS
PAD_GAIN = db(LVL_PAD) * db(1.06)
PULSE_GAIN = db(LVL_PULSE) * db(17.67)
TEX_GAIN = 0.10                        # crackle is sparse impulses: set by PEAK (~-28 dBFS pre-master), not RMS
PLUCK_PEAK = db(LVL_PLUCK) * 3.0       # plucks are peak-normalised (KS onset is ~17 dB above its 300 ms RMS)
CEILING = 0.5          # -6.02 dBFS peak ceiling of the tanh limiter

# ---- pitch tables ---------------------------------------------------------------------------------------
NOTE_HZ = {"A2": 110.0, "B2": 123.47, "C3": 130.81, "D3": 146.83, "E3": 164.81, "F3": 174.61, "G3": 196.0}
PAD_NOTES = ["A2", "B2", "C3", "D3", "E3", "F3", "G3"]
CHORDS = [("A2", "C3", "E3"),     # i    Am
          ("F3", "A2", "C3"),     # VI   F
          ("C3", "E3", "G3"),     # III  C
          ("G3", "B2", "D3")]     # VII  G
BARS_PER_CHORD = 8
# A-minor pentatonic over two octaves, A3 .. G5 (10 degrees)
PENTA_HZ = [220.0, 261.63, 293.66, 329.63, 392.0, 440.0, 523.25, 587.33, 659.25, 783.99]


def stable_hash(s: str) -> int:
    """Process-independent hash (Python's hash() is salted per process)."""
    return zlib.crc32(str(s).encode("utf-8", "ignore")) & 0xFFFFFFFF


def one_pole_gain(f: np.ndarray, fc: float) -> np.ndarray:
    """Magnitude response of a one-pole low-pass at cutoff fc, evaluated at frequencies f."""
    return 1.0 / np.sqrt(1.0 + (f / max(fc, 1.0)) ** 2)


# =========================================================================================================
class _Osc:
    """Oscillator bank for the pad: 7 notes x 6 partials, rendered with a single 2-D np.sin per block."""

    def __init__(self, sr: int):
        freqs: List[float] = []
        note_of: List[int] = []
        base_amp: List[float] = []
        for ni, name in enumerate(PAD_NOTES):
            f = NOTE_HZ[name]
            # voice 1: sine, detuned -0.25 %; voice 2: sine one octave up, detuned +0.25 %
            freqs += [f * 0.9975, f * 2.0 * 1.0025]
            base_amp += [0.55, 0.22]
            note_of += [ni, ni]
            # voice 3: "triangle" = odd harmonics 1,3,5,7 with 1/k^2 weights (band-limited by construction)
            for k in (1, 3, 5, 7):
                freqs.append(f * k * 1.0008)
                base_amp.append(0.45 / (k * k))
                note_of.append(ni)
        self.freqs = np.asarray(freqs, np.float64)
        self.note_of = np.asarray(note_of, np.int64)
        self.base_amp = np.asarray(base_amp, np.float64)
        self.phase = (np.arange(len(freqs)) * 0.37) % 1.0        # spread start phases so voices do not stack
        self.inc = self.freqs / float(sr)
        self.prev_amp = np.zeros(len(freqs), np.float64)

    def render(self, note_env: np.ndarray, fc: float, ramp: np.ndarray) -> np.ndarray:
        """note_env: (7,) gains per note for this block; fc: low-pass cutoff; ramp: (n,) 0..1 linear."""
        amp = self.base_amp * note_env[self.note_of] * one_pole_gain(self.freqs, fc)
        active = (amp > 1e-5) | (self.prev_amp > 1e-5)
        n = ramp.shape[0]
        if not active.any():
            self.phase = (self.phase + self.inc * n) % 1.0
            self.prev_amp = amp
            return np.zeros(n, np.float64)
        idx = np.flatnonzero(active)
        ph = self.phase[idx, None] + self.inc[idx, None] * np.arange(n, dtype=np.float64)[None, :]
        a = self.prev_amp[idx, None] + (amp[idx] - self.prev_amp[idx])[:, None] * ramp[None, :]
        out = (a * np.sin(2.0 * math.pi * ph)).sum(axis=0)
        self.phase = (self.phase + self.inc * n) % 1.0
        self.prev_amp = amp
        return out


class _Comb:
    """y[n] = x[n] + fb * y[n - D] with D > block, as a ring buffer (the pluck bus delay)."""

    def __init__(self, delay: int, fb: float):
        self.buf = np.zeros(delay, np.float64)
        self.d = delay
        self.fb = fb
        self.w = 0

    def process(self, x: np.ndarray) -> np.ndarray:
        n = x.shape[0]
        # the read pointer for y[n-D] is exactly the write pointer (buffer length == delay)
        y = x + self.fb * self._read(n)
        self._write(y)
        return y

    def _read(self, n: int) -> np.ndarray:
        end = self.w + n
        if end <= self.d:
            return self.buf[self.w:end].copy()
        first = self.buf[self.w:]
        return np.concatenate([first, self.buf[:end - self.d]])

    def _write(self, y: np.ndarray) -> None:
        n = y.shape[0]
        end = self.w + n
        if end <= self.d:
            self.buf[self.w:end] = y
        else:
            k = self.d - self.w
            self.buf[self.w:] = y[:k]
            self.buf[:n - k] = y[k:]
        self.w = end % self.d


def karplus_strong(freq: float, sr: int, dur_s: float, seed: int, decay: float = 0.996) -> np.ndarray:
    """Plucked string: noise burst into a delay line with a 2-tap average, rendered chunk-wise."""
    n_delay = max(2, int(round(sr / freq)))
    length = int(dur_s * sr)
    rng = np.random.default_rng(seed)
    # one leading zero so the 2-tap average y[i-N] + y[i-N-1] never indexes before the buffer
    y = np.zeros(length + n_delay + 2, np.float64)
    burst = rng.uniform(-1.0, 1.0, n_delay)
    burst = np.convolve(burst, np.full(3, 1.0 / 3.0), mode="same")     # softened excitation (less harsh onset)
    y[1:n_delay + 1] = burst - burst.mean()
    i = n_delay + 1
    while i < length + 1:
        m = min(n_delay, length + 1 - i)
        y[i:i + m] = decay * 0.5 * (y[i - n_delay:i - n_delay + m] + y[i - n_delay - 1:i - n_delay - 1 + m])
        i += m
    out = y[1:length + 1]
    fade = int(0.05 * sr)
    if fade > 0 and fade < length:
        out[-fade:] *= np.linspace(1.0, 0.0, fade)
    out[:64] *= np.linspace(0.0, 1.0, 64)                   # click-free onset
    pk = float(np.abs(out).max()) or 1.0
    return out / pk                                         # peak-normalised to 1.0; PLUCK_PEAK applied at trigger


# =========================================================================================================
class AudioEngine(object):
    def __init__(self, sr: int = SR, block: int = BLOCK, fps: float = 30.0, log=None):
        self.sr = int(sr)
        self.n = int(block)
        self.fps = float(fps)
        self.log = log or (lambda m: sys.stderr.write("audio: %s\n" % m))
        self.last_block = np.zeros((self.n, 2), np.int16)
        self.level_dbfs = -120.0
        self.errors = 0
        self.detect_errors = 0
        self._pos = 0                                       # absolute sample position (start of next block)
        self._idx = np.arange(self.n, dtype=np.float64)
        self._ramp = self._idx / float(self.n)
        self._rng = np.random.default_rng(41370704)

        # -- pad
        self._osc = _Osc(self.sr)
        self._note_env = np.zeros(len(PAD_NOTES), np.float64)
        self._note_env[[PAD_NOTES.index(x) for x in CHORDS[0]]] = 1.0
        self._chord_idx = 0
        self._haas = int(0.008 * self.sr)                    # 384 samples
        self._pad_tail = np.zeros(self._haas, np.float64)
        self._sweep_until = -1                               # theme sweep end (sample position)
        self._sweep_len = int(0.6 * self.sr)

        # -- pulse
        self._tempo = 85.0
        self._pending_tempo: Optional[float] = None
        self._beat = 0.0                                     # beat position (float, 4 beats per bar)
        self._hat_prev = 0.0

        # -- pluck bus
        self._plucks: List[np.ndarray] = [karplus_strong(f, self.sr, 0.30, 1000 + i) for i, f in enumerate(PENTA_HZ)]
        self._comb = _Comb(int(0.375 * self.sr), 0.35)
        self._pluck_queue: Deque[int] = deque()
        self._last_pluck_pos = -10 ** 9
        self._pluck_gap = int(0.25 * self.sr)
        self._msg_times: Deque[float] = deque()
        self.plucks_muted = False
        self._seen_chat: Dict[str, bool] = {}
        self._seen_order: Deque[str] = deque()

        # -- one-shot events: list of [start_sample, buffer (m,2)]; fixed shapes pre-rendered once
        self._events: List[Tuple[int, np.ndarray]] = []
        self._cache: Dict[str, np.ndarray] = {}
        self._cache["ship"] = self._seq([(self._tone([f, f * 2.0], 0.40 - i * 0.13, LVL_SHIP - 3.0, decay=4.0), i * 0.13)
                                         for i, f in enumerate((440.0, 554.37, 659.25))])
        self._cache["fail"] = self._seq([(self._tone([329.63, 329.63 * 1.006], 0.15, LVL_FAIL - 2.0, decay=1.5, wave="saw"), 0.0),
                                         (self._tone([277.18, 277.18 * 1.006], 0.15, LVL_FAIL - 2.0, decay=4.0, wave="saw"), 0.15),
                                         (self._tone([80.0], 0.30, LVL_FAIL - 3.0, decay=7.0, attack_s=0.001), 0.0)])
        self._cache["builder"] = self._seq([(self._tone([783.99], 0.10, LVL_BUILDER, decay=3.0), 0.0),
                                            (self._tone([1046.5], 0.20, LVL_BUILDER, decay=5.0), 0.10)])

        # -- ctx change detectors
        self._last_votes: Optional[int] = None
        self._last_round: Optional[int] = None
        self._last_version: Optional[str] = None
        self._last_failed: Optional[int] = None
        self._last_builders: Optional[int] = None
        self._last_theme_ts: Optional[str] = None
        self._theme_seen = False
        self._last_round_sec: Optional[int] = None
        self._votes_in_round = 0
        self.stats = {"plucks": 0, "plucks_dropped": 0, "votes": 0, "ships": 0, "fails": 0, "builders": 0,
                      "ticks": 0, "themes": 0, "pre_peak": 0.0}

    # ================================================================================== events / triggers
    def _tone(self, freqs: List[float], dur_s: float, level_db: float, decay: float = 6.0, wave: str = "sine",
              attack_s: float = 0.003, pan: float = 0.0) -> np.ndarray:
        m = int(dur_s * self.sr)
        t = np.arange(m, dtype=np.float64) / self.sr
        env = np.exp(-decay * t / dur_s) * np.minimum(1.0, t / max(attack_s, 1e-4))
        env[-min(m, 96):] *= np.linspace(1.0, 0.0, min(m, 96))
        sig = np.zeros(m, np.float64)
        for f in freqs:
            ph = (f * t) % 1.0
            if wave == "saw":
                sig += 2.0 * ph - 1.0
            else:
                sig += np.sin(2.0 * math.pi * ph)
        sig *= env / max(1, len(freqs))
        rms = float(np.sqrt(np.mean(sig ** 2))) or 1.0
        sig *= db(level_db) / rms * 0.6                      # ~level_db RMS over the whole one-shot
        return self._stereo(sig, pan)

    def _seq(self, parts: List[Tuple[np.ndarray, float]]) -> np.ndarray:
        """Mix stereo one-shots at offsets (seconds) into one buffer."""
        total = max(int(off * self.sr) + buf.shape[0] for buf, off in parts)
        out = np.zeros((total, 2), np.float64)
        for buf, off in parts:
            o = int(off * self.sr)
            out[o:o + buf.shape[0]] += buf
        return out

    @staticmethod
    def _stereo(sig: np.ndarray, pan: float = 0.0) -> np.ndarray:
        pan = max(-1.0, min(1.0, pan))
        lg, rg = math.cos((pan + 1) * math.pi / 4), math.sin((pan + 1) * math.pi / 4)
        return np.stack([sig * lg * math.sqrt(2), sig * rg * math.sqrt(2)], axis=1)

    def _add(self, buf: np.ndarray, offset_s: float = 0.0) -> None:
        self._events.append((self._pos + int(offset_s * self.sr), buf))
        if len(self._events) > 96:
            del self._events[:-96]

    def trigger(self, name: str, **kw) -> None:
        try:
            if name == "vote":
                semis = int(kw.get("semitones", self._votes_in_round))
                key = "vote%d" % semis
                if key not in self._cache:
                    self._cache[key] = self._tone([440.0 * 2 ** (semis / 12.0)], 0.030, LVL_VOTE, decay=3.0, attack_s=0.002)
                self._add(self._cache[key])
                self.stats["votes"] += 1
            elif name in ("ship", "fail", "builder"):
                self._add(self._cache[name])
                self.stats[name + "s"] += 1
            elif name == "tick":
                semis = int(kw.get("semitones", 0))
                key = "tick%d" % semis
                if key not in self._cache:
                    f = 1760.0 * 2 ** (semis / 12.0)
                    self._cache[key] = self._tone([f, f * 1.5], 0.025, LVL_TICK, decay=6.0, attack_s=0.0005)
                self._add(self._cache[key])
                self.stats["ticks"] += 1
            elif name == "theme":
                self._sweep_until = self._pos + self._sweep_len
                self.stats["themes"] += 1
            elif name == "pluck":
                deg = int(kw.get("degree", stable_hash(kw.get("user", "")) % 10)) % 10
                self._pluck_queue.append(deg)
        except Exception as e:                               # a bad trigger must never reach the loop
            self.errors += 1
            self.log("trigger %s failed (%r)" % (name, e))

    # ================================================================================== ctx detection
    def _detect(self, ctx) -> None:
        if ctx is None:
            return
        now = ctx.now
        # tempo (applied at the next bar boundary)
        tempo = None
        try:
            tempo = (ctx.micro or {}).get("audio_tempo") or (ctx.audio_cfg or {}).get("tempo")
        except Exception:
            tempo = None
        if tempo:
            try:
                tempo = float(tempo)
                if tempo in TEMPOS and abs(tempo - self._tempo) > 0.01:
                    self._pending_tempo = tempo
            except (TypeError, ValueError):
                pass
        # votes / rounds
        rnd = ctx.round or {}
        num = rnd.get("number")
        if num != self._last_round:
            self._last_round = num
            self._votes_in_round = 0
            self._last_votes = ctx.vote_count if ctx.vote_count is not None else 0
            self._last_round_sec = None
        vc = ctx.vote_count
        if vc is not None:
            if self._last_votes is not None and vc > self._last_votes:
                for _ in range(min(3, vc - self._last_votes)):
                    self.trigger("vote", semitones=self._votes_in_round)
                    self._votes_in_round += 1
            self._last_votes = vc
        # ship chime / fail buzz
        ver = ctx.version or {}
        vs = ver.get("string")
        if vs != self._last_version:
            if self._last_version is not None:
                self.trigger("ship")
            self._last_version = vs
        failed = ver.get("failed")
        if failed is not None:
            if self._last_failed is not None and failed > self._last_failed:
                self.trigger("fail")
            self._last_failed = failed
        # new builder
        nb = ctx.new_builders
        if nb is not None:
            if self._last_builders is not None and nb > self._last_builders:
                self.trigger("builder")
            self._last_builders = nb
        # theme sweep
        tts = (ctx.theme or {}).get("set_ts")
        if not self._theme_seen:
            self._theme_seen = True
            self._last_theme_ts = tts
        elif tts != self._last_theme_ts:                     # any change after boot (None -> ts included)
            self.trigger("theme")
            self._last_theme_ts = tts
        # round tick: last 10 s of a micro round (not while shipping)
        rem = ctx.round_remaining
        if rem is not None and rnd.get("phase") != "ship" and 0.0 < rem <= 10.0:
            sec = int(math.ceil(rem))
            if self._last_round_sec is not None and sec != self._last_round_sec:
                self.trigger("tick", semitones=0)
            self._last_round_sec = sec
        else:
            self._last_round_sec = None
        # macro deadline: quarter-note ticks in the last 60 s, +1 semitone every 10 s (handled in pulse)
        self._macro_tick_semis = None
        mac = ctx.macro or {}
        if mac.get("active") and mac.get("deadline_ts") and now is not None:
            dl = _iso_to_epoch(mac.get("deadline_ts"))
            if dl is not None and 0.0 < dl - now <= 60.0:
                self._macro_tick_semis = int((60.0 - (dl - now)) // 10.0)
        # chat plucks: one per newly rendered message
        chat = ctx.chat
        if chat and ctx.chat_display is not False:
            for m in chat:
                mid = m.get("id") if isinstance(m, dict) else None
                if mid is None or mid in self._seen_chat:
                    continue
                self._seen_chat[mid] = True
                self._seen_order.append(mid)
                if len(self._seen_order) > 400:
                    old = self._seen_order.popleft()
                    self._seen_chat.pop(old, None)
                if self._pos == 0 and ctx.frame is not None and ctx.frame == 0:
                    continue                                # history at boot is not "new"
                if now is not None:
                    self._msg_times.append(float(now))
                    while self._msg_times and float(now) - self._msg_times[0] > 60.0:
                        self._msg_times.popleft()
                    self.plucks_muted = len(self._msg_times) > 10
                if self.plucks_muted:
                    self.stats["plucks_dropped"] += 1
                    continue
                self.trigger("pluck", user=m.get("name") or m.get("display_name") or "")

    # ================================================================================== layers
    def _pad(self, kick_env: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        n = self.n
        # chord: every 8 bars; 6 s attack / 3 s release on the note envelopes
        target = np.zeros(len(PAD_NOTES), np.float64)
        target[[PAD_NOTES.index(x) for x in CHORDS[self._chord_idx]]] = 1.0
        blk_s = n / float(self.sr)
        up, down = blk_s / 6.0, blk_s / 3.0
        rising = target > self._note_env
        self._note_env = np.where(rising, np.minimum(target, self._note_env + up),
                                  np.maximum(target, self._note_env - down))
        # low-pass cutoff: 1.2 kHz with a 0.1 Hz LFO (+-40 %), theme sweep 300 Hz -> 1.2 kHz over 600 ms
        t0 = self._pos / float(self.sr)
        fc = 1200.0 * (1.0 + 0.4 * math.sin(2.0 * math.pi * 0.1 * t0))
        if self._pos < self._sweep_until:
            prog = 1.0 - (self._sweep_until - self._pos) / float(self._sweep_len)
            fc = 300.0 + (fc - 300.0) * prog * prog
        mono = self._osc.render(self._note_env, fc, self._ramp)
        mono *= (1.0 - 0.29 * kick_env)                     # sidechain: 3 dB dip on the kick
        # 8 ms Haas: right channel is the left delayed by 384 samples
        full = np.concatenate([self._pad_tail, mono])
        right = full[:n]
        self._pad_tail = full[n:]
        return mono, right

    def _pulse(self) -> Tuple[np.ndarray, np.ndarray]:
        n = self.n
        spb = 60.0 / self._tempo                            # seconds per beat
        beat = self._beat + self._idx * (self._tempo / 60.0) / self.sr
        beat_end = self._beat + n * (self._tempo / 60.0) / self.sr
        # kick on beats 1 and 3: time since last even beat
        kt = (beat % 2.0) * spb
        kick_env = np.exp(-kt * 9.0)
        ph = 40.0 * kt + 20.0 * 0.06 * (1.0 - np.exp(-kt / 0.06))   # 60 -> 40 Hz sweep, integrated
        kick = np.sin(2.0 * math.pi * ph) * kick_env * np.minimum(1.0, kt * 800.0)
        # hat on the off-beat 8ths: filtered (differenced) noise, 25 ms
        ht = ((beat + 0.5) % 1.0) * spb
        noise = self._rng.uniform(-1.0, 1.0, n)              # bounded noise: hat peaks stay predictable
        hp = np.empty(n, np.float64)
        hp[0] = noise[0] - self._hat_prev
        hp[1:] = noise[1:] - noise[:-1]
        self._hat_prev = noise[-1]
        hat = hp * np.exp(-ht * 90.0) * 0.35
        # macro deadline quarter-note tick on each beat crossing inside this block
        if self._macro_tick_semis is not None:
            b0, b1 = int(math.floor(self._beat)), int(math.floor(beat_end - 1e-9))
            if b1 > b0:
                self.trigger("tick", semitones=self._macro_tick_semis)
        # bar boundary -> pending tempo lands, chord advances every 8 bars
        bar0, bar1 = int(self._beat // 4), int(beat_end // 4)
        if bar1 > bar0:
            if self._pending_tempo is not None:
                self._tempo = self._pending_tempo
                self._pending_tempo = None
            self._chord_idx = (bar1 // BARS_PER_CHORD) % len(CHORDS)
        self._beat = beat_end
        sig = kick * 0.9 + hat
        return sig, kick_env

    def _texture(self) -> np.ndarray:
        n = self.n
        hits = self._rng.random(n) < (18.0 / self.sr)       # ~18 crackles per second
        imp = np.zeros(n, np.float64)
        k = int(hits.sum())
        if k:
            imp[hits] = self._rng.uniform(-1.0, 1.0, k) * (self._rng.random(k) ** 2)
        # ~2 kHz low-pass: 12-tap moving average
        return np.convolve(imp, np.full(12, 1.0 / 12.0), mode="same") * 6.0

    def _pluck_bus(self) -> None:
        # schedule at most one pluck per 250 ms; a burst becomes a strum, the rest is dropped
        while self._pluck_queue and self._pos - self._last_pluck_pos >= self._pluck_gap:
            deg = self._pluck_queue.popleft()
            pan = (deg - 4.5) / 4.5 * 0.6
            buf = self._stereo(self._plucks[deg] * PLUCK_PEAK, pan)
            self._events.append((self._pos, buf))
            self._last_pluck_pos = self._pos
            self.stats["plucks"] += 1
        if len(self._pluck_queue) > 4:
            self.stats["plucks_dropped"] += len(self._pluck_queue) - 4
            while len(self._pluck_queue) > 4:
                self._pluck_queue.pop()

    def _events_mix(self, out: np.ndarray) -> None:
        start, end = self._pos, self._pos + self.n
        keep = []
        for ev in self._events:
            es = ev[0]
            buf = ev[1]
            ee = es + buf.shape[0]
            if ee <= start:
                continue
            keep.append(ev)
            if es >= end:
                continue
            lo, hi = max(es, start), min(ee, end)
            out[lo - start:hi - start] += buf[lo - es:hi - es]
        self._events = keep

    # ================================================================================== main entry
    def block(self, frame_index: int, ctx=None) -> np.ndarray:
        try:
            self._macro_tick_semis = None
            try:
                self._detect(ctx)                           # a malformed ctx must not silence the bed
            except Exception as e:
                self.detect_errors += 1
                if self.detect_errors % 100 == 1:
                    self.log("ctx detection failed (%r); bed continues" % (e,))
            pulse, kick_env = self._pulse()
            pad_l, pad_r = self._pad(kick_env)
            tex = self._texture()
            self._pluck_bus()
            out = np.empty((self.n, 2), np.float64)
            out[:, 0] = pad_l * PAD_GAIN + pulse * PULSE_GAIN + tex * TEX_GAIN
            out[:, 1] = pad_r * PAD_GAIN + pulse * PULSE_GAIN + tex * TEX_GAIN
            # plucks go through the comb (mono send, stereo return), other one-shots straight in
            ev = np.zeros((self.n, 2), np.float64)
            self._events_mix(ev)
            wet = self._comb.process(ev.mean(axis=1))
            out += ev
            out[:, 0] += (wet - ev.mean(axis=1)) * 0.7
            out[:, 1] += (wet - ev.mean(axis=1)) * 0.7
            # master: fixed gain -> tanh soft limiter into a -6 dBFS ceiling
            out *= MASTER_GAIN
            pk = float(np.abs(out).max())
            if pk > self.stats["pre_peak"]:
                self.stats["pre_peak"] = pk
            out = CEILING * np.tanh(out / CEILING)
            rms = float(np.sqrt(np.mean(out[:, 0] ** 2)))
            self.level_dbfs = 20.0 * math.log10(rms) if rms > 1e-9 else -120.0
            pcm = (np.clip(out, -CEILING, CEILING) * 32767.0).astype(np.int16)
        except Exception as e:
            self.errors += 1
            if self.errors % 100 == 1:
                self.log("block failed (%r); emitting silence" % (e,))
            pcm = np.zeros((self.n, 2), np.int16)
        self._pos += self.n
        self.last_block = pcm
        return pcm


def _iso_to_epoch(s) -> Optional[float]:
    if not s:
        return None
    try:
        from datetime import datetime, timezone
        t = str(s).replace("Z", "+00:00")
        d = datetime.fromisoformat(t)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except Exception:
        try:
            return float(s)
        except Exception:
            return None


# =========================================================================================================
if __name__ == "__main__":
    # Standalone harness: python stream/audio.py [--bed] [--out PATH] [--seconds N]
    #   default: 10 s with every event fired via a fake ctx; --bed renders the bed alone for level calibration.
    import argparse
    import time

    ap = argparse.ArgumentParser()
    ap.add_argument("--bed", action="store_true", help="bed only (pad+pulse+texture), no events")
    ap.add_argument("--out", default=None, help="write raw s16le stereo 48k to this path")
    ap.add_argument("--seconds", type=float, default=10.0)
    a = ap.parse_args()

    class FakeCtx(object):
        def __init__(self, **kw):
            self.__dict__.update(kw)

        def __getattr__(self, name):
            return None

        def get(self, name, default=None):
            v = self.__dict__.get(name)
            return default if v is None else v

    e = AudioEngine()
    frames = int(a.seconds * 30)
    t0 = 1_700_000_000.0
    times = []
    peak = 0
    chunks = []
    version = {"string": "v0.1.0", "failed": 0}
    votes = 0
    builders = 0
    theme = {"set_ts": None}
    chat: List[Dict] = []
    for i in range(frames):
        now = t0 + i / 30.0
        if not a.bed:
            if i == 30:
                chat.append({"id": "m1", "name": "alice", "t": now})
            if i == 32:
                chat.append({"id": "m2", "name": "bob", "t": now})
            if i == 34:
                chat.append({"id": "m3", "name": "carol", "t": now})
            if i in (60, 75, 90):
                votes += 1
            if i == 120:
                version = {"string": "v0.1.1", "failed": 0}
            if i == 165:
                version = {"string": "v0.1.1", "failed": 1}
            if i == 210:
                builders += 1
            if i == 240:
                theme = {"set_ts": "2026-01-01T00:00:00Z"}
            rem = 12.0 - (i - 150) / 30.0 if i >= 150 else 100.0
        else:
            rem = 100.0
        ctx = FakeCtx(now=now, frame=i, micro={"audio_tempo": 85}, round={"number": 1, "phase": "open"},
                      round_remaining=rem, vote_count=votes, version=version, new_builders=builders,
                      theme=theme, chat=list(chat[-10:]), chat_display=True)
        tp = time.perf_counter()
        b = e.block(i, ctx)
        times.append((time.perf_counter() - tp) * 1000)
        peak = max(peak, int(np.abs(b.astype(np.int32)).max()))
        chunks.append(b)
    pcm = np.concatenate(chunks)
    rms = float(np.sqrt(np.mean((pcm.astype(np.float64) / 32767.0) ** 2)))
    times_np = np.asarray(times)
    print("frames=%d block=%s dtype=%s" % (frames, chunks[0].shape, chunks[0].dtype))
    print("ms/block: avg %.3f  p95 %.3f  max %.3f (frame %d)" % (
        times_np.mean(), np.percentile(times_np, 95), times_np.max(), int(times_np.argmax())))
    print("rms %.2f dBFS  peak %d (%.2f dBFS)  errors=%d  stats=%s muted=%s" % (
        20 * math.log10(rms) if rms > 0 else -120, peak, 20 * math.log10(peak / 32767.0), e.errors, e.stats, e.plucks_muted))
    if a.out:
        with open(a.out, "wb") as fh:
            fh.write(pcm.tobytes())
        print("wrote %s (%d bytes)" % (a.out, pcm.nbytes))
