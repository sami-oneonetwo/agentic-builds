"""audio.py - the generated soundtrack (CONCEPT section 6, WORLD.md section 7), synthesised in numpy inside the
frame loop.

    engine = AudioEngine(sr=48000, block=1600, fps=30)
    pcm = engine.block(frame_index, ctx)      # -> np.int16 array, shape (1600, 2), lockstep with the frame
    engine.last_block                          # the same array (the scope panel draws its left channel)
    engine.level_dbfs                          # RMS of the last block in dBFS (float, -120 when silent)
    engine.trigger(name, **kw)                 # external event: "vote"(semitones=) | "ship" | "fail" | "builder"
                                               #                  | "pluck"(user=) | "theme" | "tick"(semitones=)
    engine.attach_world(scene)                 # optional: the CaveScene whose events + awake count drive the world
                                               # layers. Without it the engine looks for one on its own (below).

Two modes, decided every block:

  LEGACY (no world scene anywhere): exactly the SHIP IT LIVE bed and cues below, unchanged.
  WORLD  (a `CaveScene` is attached, passed as `ctx.world`, or found as a module attribute `SCENE`/`scene` on
         `stream.scenes.hollow` or any loaded `stream.panels.*` module): the pad becomes a voice bank whose voice
         count EQUALS the awake pip count (WORLD.md 7), and the chat pluck / new-builder / vote-blip detectors are
         replaced by the scene's events (speak / hatch / arrive) so nothing sounds twice. `block()` runs before the
         panels each frame, so the engine hears frame N-1's events at frame N (33 ms) and consumes each frame's list
         exactly once (keyed on `scene.frames`; a duplicate-frame block with ctx=None re-reads nothing).

Legacy layers (all float64 in -1..1, summed before the master):
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

World layers (WORLD.md 7; every one of them is caused by a real record: an awake pip, a scene event, or a
state.json field the rounds / keeper agents own):
  pad      voice bank: voice k (0..7) = chord tone k % 3, detuned by a per-voice cent offset (voices 6-7 one octave
           up), 3 partials each; voice k sounds only while awake pips > k, 2 s attack (first light = the first
           voice fading in), 3 s release; per-voice level (3/max(n,3))^0.25 so 8 voices are ~+1 dB over 3 and
           the colony's size is heard as thickness; 0 awake = no pad (drips and crackle only); the pulse is gated
           by the same envelope; fog halves the low-pass cutoff; lights-out drops to the sub voice (root / 2)
                                                                                       -24 dBFS at 3 voices
  drips    `drip_land{x}` -> decaying sine at a pentatonic pitch one octave up (A4..G6) with a 2 ms splash and a
           short downward glide, panned by x; when the scene is silent for 8 s the engine drips itself every 2-6 s
                                                                                       -30 dBFS
  crackle  kept                                                                        -40 dBFS
  motif    `speak{pip,text}` -> the pip's two-note motif (degree, degree+2) from stable_hash(name) % 10 (the same
           identity as the legacy pluck), one Karplus-Strong note per word chunk, max 6, one note per 250 ms on
           the pluck bus, auto-muted above 10 speaks/min                               -20 dBFS
  hatch    `hatch{first_ever}` -> the G5-C6 new-builder rise, then the motif; a re-hatch plays the motif only
                                                                                       -20 dBFS
  wake     rising third (soft triangle); `sleep` -> descending third an octave down    -26 dBFS
  tier_up  rising third + a 300 ms low-pass sweep on the pad                           -20 dBFS
  feed/pet soft pop / a two-note duet built from BOTH pips' degrees (a dyad)          -22 dBFS
  gift     200 ms triangle two-note (also played back per gift in a wake's care log)   -24 dBFS
  dig      low thud; `plant` -> thud then a high sparkle                               -22 dBFS
  walk     footstep clicks at 4 Hz per walking pip from `walk` to `arrive` (4 s cap), global 1 per 60 ms
                                                                                       -30 dBFS
  arrive   the vote blip on platform arrival, +1 semitone per vote in the round        -20 dBFS
  seed     `seed_land` soft thud panned by x; `sink` a low plop                        -30 dBFS
  hop      1.6 kHz tick, 1 per 120 ms                                                  -30 dBFS
  emote    wave: two high blips; sit / duck: one low blip                              -26 dBFS
  credits  `credits{pip}` -> the pip's motif descending                                -26 dBFS
  ship     existing chime + a 600 ms low-pass sweep; a `feast` ship = the chime as one chord;
           weather glow-rain = pink noise through a 1.5 kHz low-pass while it falls    -16 / -34 dBFS
  keeper   macro.active rising edge (lantern lowering) = chain rattle (filtered noise bursts, decelerating);
           macro.last_reload ok = chime + low rock rumble; failed = the existing saw + thud
                                                                                       -20 dBFS

Master unchanged: fixed gain so the bed sits at about -18 dBFS integrated (see MASTER_GAIN, calibrated against
ffmpeg volumedetect), then a tanh soft limiter into a -6 dBFS peak ceiling: it cannot clip by construction.
The engine never raises out of block(): on any internal error it returns silence for that block.
Python 3.9; numpy only.
"""
from __future__ import annotations

import math
import sys
import zlib
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

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
# world layers (WORLD.md 7)
LVL_DRIP = -30.0
LVL_WAKE = -26.0
LVL_TIER = -20.0
LVL_CARE = -22.0
LVL_GIFT = -24.0
LVL_DIG = -22.0
LVL_STEP = -30.0
LVL_SEED = -30.0
LVL_HOP = -30.0
LVL_EMOTE = -26.0
LVL_CREDITS = -26.0
LVL_RAIN = -34.0
LVL_KEEPER = -20.0
# The bed (pad + pulse + texture) sums to about -23.3 dBFS; this trim lands it at -18 dBFS integrated.
# Calibrated with: $FFMPEG -f s16le -ar 48000 -ac 2 -i bed.pcm -af volumedetect  (mean_volume -18.x dB)
MASTER_GAIN = 1.78
# raw layer RMS measured over 15 s (stream/audio.py calibration): pad -1.06, pulse -17.67, texture -41.16 dBFS
PAD_GAIN = db(LVL_PAD) * db(1.06)
PULSE_GAIN = db(LVL_PULSE) * db(17.67)
TEX_GAIN = 0.10                        # crackle is sparse impulses: set by PEAK (~-28 dBFS pre-master), not RMS
PLUCK_PEAK = db(LVL_PLUCK) * 3.0       # plucks are peak-normalised (KS onset is ~17 dB above its 300 ms RMS)
CEILING = 0.5          # -6.02 dBFS peak ceiling of the tanh limiter
# world voice bank: raw RMS of 3 steady voices measured -3.88 dBFS (python stream/audio.py --world-cal 3)
VOICE_GAIN = db(LVL_PAD) * db(3.88)
VOICES_MAX = 8
VOICE_ATTACK_S = 2.0
VOICE_RELEASE_S = 3.0
# per-voice: chord tone index, detune (fraction), octave multiplier, level
VOICE_TABLE = [(0, -0.0030, 1.0, 1.0), (1, +0.0030, 1.0, 1.0), (2, -0.0055, 1.0, 1.0), (0, +0.0055, 1.0, 0.9),
               (1, -0.0085, 1.0, 0.9), (2, +0.0085, 1.0, 0.9), (0, -0.0040, 2.0, 0.5), (1, +0.0040, 2.0, 0.5)]
SUB_VOICE = len(VOICE_TABLE)           # index 8: root / 2, lights-out only
STEP_GAP_S = 0.25                      # one footstep per 250 ms per walking pip
STEP_GLOBAL_GAP_S = 0.06
WALK_CAP_S = 4.0
HOP_GAP_S = 0.12
SELF_DRIP_AFTER_S = 8.0
RAIN_LOOP_S = 4.0
WORLD_SCAN_BLOCKS = 30

# ---- pitch tables ---------------------------------------------------------------------------------------
NOTE_HZ = {"A2": 110.0, "B2": 123.47, "C3": 130.81, "D3": 146.83, "E3": 164.81, "F3": 174.61, "G3": 196.0}
PAD_NOTES = ["A2", "B2", "C3", "D3", "E3", "F3", "G3"]
CHORDS = [("A2", "C3", "E3"),     # i    Am
          ("F3", "A2", "C3"),     # VI   F
          ("C3", "E3", "G3"),     # III  C
          ("G3", "B2", "D3")]     # VII  G
BARS_PER_CHORD = 8
# A-minor pentatonic over two octaves, A3 .. G5 (10 degrees) + A5, C6 so a motif's (degree + 2) always exists
PENTA_HZ = [220.0, 261.63, 293.66, 329.63, 392.0, 440.0, 523.25, 587.33, 659.25, 783.99]
PENTA_EXT_HZ = PENTA_HZ + [880.0, 1046.5]


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
        return self._render_amp(amp, ramp)

    def _render_amp(self, amp: np.ndarray, ramp: np.ndarray) -> np.ndarray:
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


class _VoiceBank(_Osc):
    """World pad: 8 detuned voices (+ a sub voice) x 7 notes x 3 partials. Voice k plays chord tone k % 3; its
    gain follows the awake count. Only the active oscillators are rendered (<= ~50 of the 175)."""

    def __init__(self, sr: int):
        freqs: List[float] = []
        note_of: List[int] = []
        voice_of: List[int] = []
        base_amp: List[float] = []
        for vi, (_tone, det, octv, lvl) in enumerate(VOICE_TABLE):
            for ni, name in enumerate(PAD_NOTES):
                f = NOTE_HZ[name] * (1.0 + det) * octv
                for k, a in ((1, 0.55), (2, 0.22), (3, 0.07)):
                    freqs.append(f * k)
                    base_amp.append(a * lvl)
                    note_of.append(ni)
                    voice_of.append(vi)
        for ni, name in enumerate(PAD_NOTES):                    # sub voice: root / 2, sine only
            freqs.append(NOTE_HZ[name] * 0.5)
            base_amp.append(0.9)
            note_of.append(ni)
            voice_of.append(SUB_VOICE)
        self.freqs = np.asarray(freqs, np.float64)
        self.note_of = np.asarray(note_of, np.int64)
        self.voice_of = np.asarray(voice_of, np.int64)
        self.base_amp = np.asarray(base_amp, np.float64)
        self.phase = (np.arange(len(freqs)) * 0.41) % 1.0
        self.inc = self.freqs / float(sr)
        self.prev_amp = np.zeros(len(freqs), np.float64)

    def render_voices(self, vn_env: np.ndarray, vgain: np.ndarray, fc: float, ramp: np.ndarray) -> np.ndarray:
        """vn_env: (9, 7) per-voice note envelopes; vgain: (9,) per-voice gains (awake envelope x level)."""
        amp = self.base_amp * vn_env[self.voice_of, self.note_of] * vgain[self.voice_of] * one_pole_gain(self.freqs, fc)
        return self._render_amp(amp, ramp)


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


def _looks_like_scene(obj: Any) -> bool:
    """Duck-typed CaveScene: a per-frame `events` list, `awake_count()`, and a `frames` counter."""
    try:
        return (obj is not None and not isinstance(obj, type) and isinstance(getattr(obj, "events", None), list)
                and callable(getattr(obj, "awake_count", None)) and isinstance(getattr(obj, "frames", None), int))
    except Exception:
        return False


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
        init_rng = np.random.default_rng(20260925)          # init-time renders only: the texture rng stays as it was

        # -- pad
        self._osc = _Osc(self.sr)
        self._note_env = np.zeros(len(PAD_NOTES), np.float64)
        self._note_env[[PAD_NOTES.index(x) for x in CHORDS[0]]] = 1.0
        self._chord_idx = 0
        self._haas = int(0.008 * self.sr)                    # 384 samples
        self._pad_tail = np.zeros(self._haas, np.float64)
        self._sweep_until = -1                               # theme sweep end (sample position)
        self._sweep_len = int(0.6 * self.sr)
        self._sweep_cur = self._sweep_len

        # -- world voice bank (WORLD.md 7): voices == awake pips
        self._bank = _VoiceBank(self.sr)
        self._vn_env = np.zeros((SUB_VOICE + 1, len(PAD_NOTES)), np.float64)
        self._vgain = np.zeros(SUB_VOICE + 1, np.float64)    # per-voice awake envelope (0..1)
        self.awake_voices = 0
        self._weather = "clear"

        # -- pulse
        self._tempo = 85.0
        self._pending_tempo: Optional[float] = None
        self._beat = 0.0                                     # beat position (float, 4 beats per bar)
        self._hat_prev = 0.0

        # -- pluck bus
        self._plucks: List[np.ndarray] = [karplus_strong(f, self.sr, 0.30, 1000 + i) for i, f in enumerate(PENTA_EXT_HZ)]
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
        self._cache["ship_chord"] = self._tone([440.0, 554.37, 659.25, 880.0], 0.60, LVL_SHIP - 2.0, decay=3.5, attack_s=0.01)
        self._cache["fail"] = self._seq([(self._tone([329.63, 329.63 * 1.006], 0.15, LVL_FAIL - 2.0, decay=1.5, wave="saw"), 0.0),
                                         (self._tone([277.18, 277.18 * 1.006], 0.15, LVL_FAIL - 2.0, decay=4.0, wave="saw"), 0.15),
                                         (self._tone([80.0], 0.30, LVL_FAIL - 3.0, decay=7.0, attack_s=0.001), 0.0)])
        self._cache["builder"] = self._seq([(self._tone([783.99], 0.10, LVL_BUILDER, decay=3.0), 0.0),
                                            (self._tone([1046.5], 0.20, LVL_BUILDER, decay=5.0), 0.10)])
        # world one-shots (pitch-independent ones here; per-degree ones are cached on first use)
        self._cache["feed"] = self._tone([260.0, 520.0], 0.055, LVL_CARE, decay=7.0, attack_s=0.001)
        self._cache["dig"] = self._seq([(self._tone([80.0], 0.14, LVL_DIG, decay=6.0, attack_s=0.001), 0.0),
                                        (self._tone([55.0], 0.10, LVL_DIG - 6.0, decay=5.0, attack_s=0.001), 0.01)])
        self._cache["plant"] = self._seq([(self._cache["dig"], 0.0)] +
                                         [(self._tone([f], 0.07, LVL_DIG - 5.0, decay=5.0, attack_s=0.001, pan=p), 0.12 + 0.06 * i)
                                          for i, (f, p) in enumerate(((2093.0, -0.3), (2637.0, 0.3), (3136.0, 0.0)))])
        self._cache["seed_land"] = self._tone([120.0, 60.0], 0.06, LVL_SEED, decay=6.0, attack_s=0.001)
        self._cache["sink"] = self._seq([(self._tone([110.0], 0.12, LVL_SEED, decay=4.0, attack_s=0.004), 0.0),
                                         (self._tone([82.4], 0.16, LVL_SEED, decay=5.0, attack_s=0.004), 0.10)])
        self._cache["hop"] = self._tone([1600.0], 0.012, LVL_HOP, decay=5.0, attack_s=0.0005)
        self._cache["emote_wave"] = self._seq([(self._tone([1760.0], 0.04, LVL_EMOTE, decay=4.0), 0.0),
                                               (self._tone([2093.0], 0.05, LVL_EMOTE, decay=4.0), 0.06)])
        self._cache["emote_low"] = self._tone([330.0], 0.06, LVL_EMOTE, decay=5.0, wave="tri")
        self._cache["step"] = self._noise_burst(init_rng, 0.012, LVL_STEP, taps=6, decay=9.0)
        self._cache["rattle"] = self._rattle(init_rng)
        self._cache["rumble"] = self._rumble(init_rng)
        self._cache["carve"] = self._seq([(self._cache["ship"], 0.0), (self._cache["rumble"], 0.0)])
        self._drips: List[np.ndarray] = [self._drip(f * 2.0, init_rng) for f in PENTA_HZ]
        # per-degree stings rendered now (~30 ms once) so no block pays a first-use render (> 1.5 ms) on air
        for deg in range(10):
            self._cache["wake%d" % deg] = self._third(deg, LVL_WAKE, True)
            self._cache["sleep%d" % deg] = self._third(deg, LVL_WAKE, False, octave=0.5, d1=0.20, d2=0.30)
            self._cache["tier%d" % deg] = self._third(deg, LVL_TIER, True, d1=0.14, d2=0.30)
            self._cache["credits%d" % deg] = self._third(deg, LVL_CREDITS, False, d1=0.18, d2=0.34)
            self._gift_buf(deg)
        self._rain = self._pink_loop(init_rng)              # (m, 2) periodic pink noise, low-passed at 1.5 kHz
        self._rain_env = 0.0
        self._rain_pos = 0

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
        self._last_result_title = ""
        self._macro_active: Optional[bool] = None
        self._last_reload_ts: Optional[str] = None
        self._reload_seen = False
        self._last_fail_pos = -10 ** 9

        # -- world scene (events + awake count)
        self._world: Any = None                              # attach_world()
        self._world_found: Any = None                        # auto-discovered
        self._world_where: Optional[Tuple[str, str, bool]] = None   # (module, attr, via .scene) it was found at
        self._world_scan_at = -1
        self._world_frames_seen: Optional[int] = None
        self.world_mode = False
        self._speak_pos: Deque[int] = deque()
        self._walking: Dict[str, List[int]] = {}             # key -> [next_step_pos, until_pos, side]
        self._last_step_pos = -10 ** 9
        self._last_hop_pos = -10 ** 9
        self._last_drip_pos = 0
        self._next_self_drip = 0
        self._drip_rng = np.random.default_rng(41370705)
        self.stats = {"plucks": 0, "plucks_dropped": 0, "votes": 0, "ships": 0, "fails": 0, "builders": 0,
                      "ticks": 0, "themes": 0, "pre_peak": 0.0,
                      "world_events": 0, "motifs": 0, "motif_notes": 0, "motifs_dropped": 0, "drips": 0,
                      "self_drips": 0, "steps": 0, "stings": 0, "keeper": 0, "hatches": 0, "world_blocks": 0}

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
            elif wave == "tri":                              # odd harmonics 1,3,5,7 with alternating sign, 1/k^2
                for j, k in enumerate((1, 3, 5, 7)):
                    sig += ((-1.0) ** j) * np.sin(2.0 * math.pi * k * ph) / (k * k)
            else:
                sig += np.sin(2.0 * math.pi * ph)
        sig *= env / max(1, len(freqs))
        rms = float(np.sqrt(np.mean(sig ** 2))) or 1.0
        sig *= db(level_db) / rms * 0.6                      # ~level_db RMS over the whole one-shot
        return self._stereo(sig, pan)

    def _noise_burst(self, rng, dur_s: float, level_db: float, taps: int = 6, decay: float = 8.0, pan: float = 0.0) -> np.ndarray:
        """Short filtered noise burst (footstep, chain link). Deterministic: init-time rng."""
        m = max(8, int(dur_s * self.sr))
        t = np.arange(m, dtype=np.float64) / self.sr
        sig = rng.uniform(-1.0, 1.0, m)
        if taps > 1:
            sig = np.convolve(sig, np.full(taps, 1.0 / taps), mode="same")
        sig *= np.exp(-decay * t / dur_s) * np.minimum(1.0, t / 0.0008)
        sig[-min(m, 32):] *= np.linspace(1.0, 0.0, min(m, 32))
        rms = float(np.sqrt(np.mean(sig ** 2))) or 1.0
        sig *= db(level_db) / rms * 0.6
        return self._stereo(sig, pan)

    def _rattle(self, rng) -> np.ndarray:
        """Lantern chain lowering: 9 metallic bursts, decelerating over ~1.3 s, wandering left-right."""
        parts = []
        t = 0.0
        for i in range(9):
            parts.append((self._noise_burst(rng, 0.035, LVL_KEEPER - 2.0, taps=3, decay=10.0, pan=0.25 * math.sin(i * 1.7)), t))
            parts.append((self._tone([2400.0 + 300.0 * ((i * 7) % 5)], 0.03, LVL_KEEPER - 8.0, decay=8.0, attack_s=0.0005), t))
            t += 0.09 + 0.02 * i
        return self._seq(parts)

    def _rumble(self, rng) -> np.ndarray:
        """Low rock rumble under a carve ship: brown-ish noise (cumulative sum, leaky) low-passed, 0.9 s."""
        m = int(0.9 * self.sr)
        t = np.arange(m, dtype=np.float64) / self.sr
        w = rng.uniform(-1.0, 1.0, m)
        b = np.empty(m, np.float64)
        acc = 0.0
        # leaky integrator, chunked (16-sample chunks keep the python loop at ~2.7k iterations, init only)
        step = 16
        for i in range(0, m, step):
            seg = w[i:i + step]
            cs = np.cumsum(seg) + acc
            b[i:i + step] = cs
            acc = float(cs[-1]) * 0.985
        b = np.convolve(b, np.full(24, 1.0 / 24.0), mode="same")
        b *= np.exp(-4.0 * t / 0.9) * np.minimum(1.0, t / 0.02)
        b[-96:] *= np.linspace(1.0, 0.0, 96)
        rms = float(np.sqrt(np.mean(b ** 2))) or 1.0
        b *= db(LVL_KEEPER - 4.0) / rms * 0.6
        return self._stereo(b, 0.0)

    def _drip(self, f: float, rng) -> np.ndarray:
        """Water drip plink: decaying sine with a short downward glide and a 2 ms splash, 260 ms, -30 dBFS RMS."""
        m = int(0.26 * self.sr)
        t = np.arange(m, dtype=np.float64) / self.sr
        glide = 0.08 * 0.02 * (1.0 - np.exp(-t / 0.02))          # +8 % at onset, gone after ~20 ms (integrated)
        sig = np.sin(2.0 * math.pi * (f * t + f * glide)) * np.exp(-t / 0.075)
        splash = np.zeros(m, np.float64)
        k = int(0.002 * self.sr)
        splash[:k] = rng.uniform(-1.0, 1.0, k) * np.linspace(1.0, 0.0, k) * 0.5
        sig = (sig + splash) * np.minimum(1.0, t / 0.0008)
        sig[-96:] *= np.linspace(1.0, 0.0, 96)
        rms = float(np.sqrt(np.mean(sig ** 2))) or 1.0
        sig *= db(LVL_DRIP) / rms * 0.6
        return self._stereo(sig, 0.0)

    def _pink_loop(self, rng) -> np.ndarray:
        """Seamless pink-noise loop (FFT synthesis on integer bins -> periodic), low-passed at 1.5 kHz, stereo
        decorrelated, RMS at LVL_RAIN. Used only while ctx.micro.weather == glow-rain."""
        m = int(RAIN_LOOP_S * self.sr)
        freqs = np.fft.rfftfreq(m, 1.0 / self.sr)
        mag = np.zeros_like(freqs)
        mag[1:] = 1.0 / np.sqrt(freqs[1:]) * one_pole_gain(freqs[1:], 1500.0)
        out = np.empty((m, 2), np.float64)
        for ch in range(2):
            ph = rng.uniform(0.0, 2.0 * math.pi, freqs.shape[0])
            spec = mag * np.exp(1j * ph)
            x = np.fft.irfft(spec, m)
            rms = float(np.sqrt(np.mean(x ** 2))) or 1.0
            out[:, ch] = x / rms * db(LVL_RAIN)
        return out

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

    @staticmethod
    def _repan(buf: np.ndarray, pan: float) -> np.ndarray:
        """Re-pan a centre-rendered stereo one-shot (both channels equal) without re-rendering it."""
        if abs(pan) < 1e-3:
            return buf
        pan = max(-1.0, min(1.0, pan))
        lg, rg = math.cos((pan + 1) * math.pi / 4) * math.sqrt(2), math.sin((pan + 1) * math.pi / 4) * math.sqrt(2)
        mono = buf.mean(axis=1)
        return np.stack([mono * lg, mono * rg], axis=1)

    def _add(self, buf: np.ndarray, offset_s: float = 0.0) -> None:
        self._events.append((self._pos + int(offset_s * self.sr), buf))
        if len(self._events) > 200:
            del self._events[:-200]

    def _sweep(self, dur_s: float) -> None:
        """Low-pass sweep on the pad: 300 Hz -> normal over dur_s (theme 600 ms, tier-up 300 ms, ship 600 ms)."""
        self._sweep_cur = max(1, int(dur_s * self.sr))
        self._sweep_until = self._pos + self._sweep_cur

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
                self._sweep(0.6)
                self.stats["themes"] += 1
            elif name == "pluck":
                deg = int(kw.get("degree", stable_hash(kw.get("user", "")) % 10)) % 10
                self._pluck_queue.append(deg)
        except Exception as e:                               # a bad trigger must never reach the loop
            self.errors += 1
            self.log("trigger %s failed (%r)" % (name, e))

    # ================================================================================== world scene lookup
    def attach_world(self, scene: Any) -> None:
        """Give the engine the CaveScene explicitly (the world panel or the compositor may call this)."""
        self._world = scene if _looks_like_scene(scene) else None
        self._world_frames_seen = None

    def _find_world(self) -> Any:
        """Auto-discovery: `SCENE` / `scene` (or any scene-shaped attribute) on stream.scenes.hollow or a loaded
        stream.panels.* module. Re-checked every WORLD_SCAN_BLOCKS blocks: hot reload makes a new CaveScene.
        Once found, the re-check is one getattr on the module it came from; the full scan runs only when that
        attribute no longer holds the same object."""
        where = self._world_where
        if where is not None:
            mod = sys.modules.get(where[0])
            obj = getattr(mod, where[1], None) if mod is not None else None
            if where[2]:
                obj = getattr(obj, "scene", None)
            if obj is self._world_found and _looks_like_scene(obj):
                return obj
        cands = []
        m = sys.modules.get("stream.scenes.hollow")
        if m is not None:
            cands.append(("stream.scenes.hollow", m))
        cands += [(name, mod) for name, mod in list(sys.modules.items()) if name.startswith("stream.panels.") and mod is not None]
        for name, mod in cands:
            for attr in ("SCENE", "scene", "_SCENE", "CAVE", "WORLD"):
                obj = getattr(mod, attr, None)
                if _looks_like_scene(obj):
                    self._world_where = (name, attr, False)
                    return obj
        for name, mod in cands:
            try:
                items = list(vars(mod).items())
            except Exception:
                continue
            for attr, obj in items:
                if attr.startswith("__"):
                    continue
                if _looks_like_scene(obj):
                    self._world_where = (name, attr, False)
                    return obj
                sc = getattr(obj, "scene", None)              # a panel instance holding its scene
                if not isinstance(obj, type) and _looks_like_scene(sc):
                    self._world_where = (name, attr, True)
                    return sc
        self._world_where = None
        return None

    def _scene(self):
        if self._world is not None:
            return self._world
        blk = self._pos // self.n
        if self._world_scan_at < 0 or blk - self._world_scan_at >= WORLD_SCAN_BLOCKS:
            self._world_scan_at = blk
            found = self._find_world()
            if found is not None and found is not self._world_found:
                self._world_found = found
                self._world_frames_seen = None
                self.log("world scene found (%s); pad voices now follow the awake count" % type(found).__name__)
            elif found is None and self._world_found is not None:
                self.log("world scene gone; back to the legacy bed")
                self._world_found = None
        return self._world_found

    # ================================================================================== ctx detection
    def _detect(self, ctx) -> None:
        if ctx is None:
            return
        now = ctx.now
        world = self.world_mode
        # a scene handed over on ctx wins over discovery (an integrator may set ctx.world)
        cw = getattr(ctx, "world", None)
        if cw is not None and _looks_like_scene(cw) and cw is not self._world:
            self.attach_world(cw)
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
        # weather (rounds agent owns state.micro.weather): glow-rain noise, fog cutoff, lights-out sub voice
        try:
            self._weather = str((ctx.micro or {}).get("weather") or "clear").lower()
        except Exception:
            self._weather = "clear"
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
            if self._last_votes is not None and vc > self._last_votes and not world:
                for _ in range(min(3, vc - self._last_votes)):     # world mode: the blip plays on platform arrival
                    self.trigger("vote", semitones=self._votes_in_round)
                    self._votes_in_round += 1
            self._last_votes = vc
        # ship chime / fail buzz
        ver = ctx.version or {}
        vs = ver.get("string")
        if vs != self._last_version:
            if self._last_version is not None:
                title = ""
                try:
                    title = str((rnd.get("last_result") or {}).get("title") or "").lower()
                except Exception:
                    title = ""
                if world and title.startswith("feast"):
                    self._add(self._cache["ship_chord"])
                    self.stats["ships"] += 1
                else:
                    self.trigger("ship")
                if world:
                    self._sweep(0.6)
            self._last_version = vs
        failed = ver.get("failed")
        if failed is not None:
            if self._last_failed is not None and failed > self._last_failed:
                self._fail_once()
            self._last_failed = failed
        # new builder (world mode: the hatch event carries first_ever and plays the rise itself)
        nb = ctx.new_builders
        if nb is not None:
            if self._last_builders is not None and nb > self._last_builders and not world:
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
        # keeper (WORLD.md 9): lantern lowering = chain rattle on the macro.active rising edge; a carve ship =
        # chime + rumble when macro.last_reload changes with ok; a failed reload = the fail buzz
        act = bool(mac.get("active"))
        if self._macro_active is None:
            self._macro_active = act
        elif act and not self._macro_active:
            if world:
                self._add(self._cache["rattle"])
                self.stats["keeper"] += 1
            self._macro_active = act
        else:
            self._macro_active = act
        lr = mac.get("last_reload") or {}
        lts = lr.get("ts") if isinstance(lr, dict) else None
        if not self._reload_seen:
            self._reload_seen = True
            self._last_reload_ts = lts
        elif lts != self._last_reload_ts:
            self._last_reload_ts = lts
            if world and lts:
                if lr.get("ok"):
                    self._add(self._cache["carve"])
                    self._sweep(0.6)
                    self.stats["keeper"] += 1
                else:
                    self._fail_once()
        # chat plucks: one per newly rendered message (legacy only; the world's `speak` events replace them)
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
                if world:
                    continue
                if now is not None:
                    self._msg_times.append(float(now))
                    while self._msg_times and float(now) - self._msg_times[0] > 60.0:
                        self._msg_times.popleft()
                    self.plucks_muted = len(self._msg_times) > 10
                if self.plucks_muted:
                    self.stats["plucks_dropped"] += 1
                    continue
                self.trigger("pluck", user=m.get("name") or m.get("display_name") or "")

    def _fail_once(self) -> None:
        """version.failed and macro.last_reload.ok=False can describe the same failure: one buzz per second."""
        if self._pos - self._last_fail_pos >= self.sr:
            self._last_fail_pos = self._pos
            self.trigger("fail")

    # ================================================================================== world events
    def _pip_degree(self, scene, key: str) -> int:
        """The pip's pentatonic degree: stable_hash(name as Kick sent it) % 10, the legacy pluck identity."""
        name = key or ""
        try:
            w = getattr(scene, "world", None)
            p = w.pip(key) if w is not None else None
            if p and p.get("name"):
                name = str(p.get("name"))
        except Exception:
            pass
        return stable_hash(name) % 10

    def _pip_pan(self, scene, key: str, x: Optional[float] = None, deg: Optional[int] = None) -> float:
        if x is None:
            try:
                e = scene.behaviour.get(key)
                x = float(e.x) if e is not None else None
            except Exception:
                x = None
        if x is not None:
            return max(-0.6, min(0.6, (float(x) / 320.0 - 0.5) * 1.2))
        if deg is not None:
            return (deg - 4.5) / 4.5 * 0.6
        return 0.0

    def _schedule_pluck(self, deg: int, at_pos: int, pan: float) -> bool:
        """One Karplus-Strong note on the pluck bus at >= at_pos, keeping the 250 ms bus spacing.
        Notes that would land more than 2.5 s late are dropped (a flood becomes a strum, not a backlog)."""
        deg = max(0, min(len(self._plucks) - 1, int(deg)))
        at = max(int(at_pos), self._pos, self._last_pluck_pos + self._pluck_gap)
        if at - self._pos > int(2.5 * self.sr):
            return False
        self._events.append((at, self._stereo(self._plucks[deg] * PLUCK_PEAK, pan)))
        if len(self._events) > 200:
            del self._events[:-200]
        self._last_pluck_pos = at
        self.stats["plucks"] += 1
        return True

    def _motif(self, deg: int, chunks: int, pan: float, offset_s: float = 0.0, descending: bool = False) -> int:
        """The two-note motif (degree, degree + 2), one note per chunk, max 6; returns notes scheduled."""
        chunks = max(1, min(6, int(chunks)))
        notes = [deg + 2, deg] if descending else [deg, deg + 2]
        done = 0
        start = self._pos + int(offset_s * self.sr)
        for i in range(chunks):
            if self._schedule_pluck(notes[i % 2], start + i * self._pluck_gap, pan):
                done += 1
        self.stats["motif_notes"] += done
        return done

    def _sting(self, key: str, make) -> None:
        if key not in self._cache:
            self._cache[key] = make()
        self._add(self._cache[key])
        self.stats["stings"] += 1

    def _third(self, deg: int, level: float, rising: bool, octave: float = 1.0, d1: float = 0.16, d2: float = 0.24) -> np.ndarray:
        a, b = PENTA_EXT_HZ[max(0, min(11, deg))] * octave, PENTA_EXT_HZ[max(0, min(11, deg + 2))] * octave
        f1, f2 = (a, b) if rising else (b, a)
        return self._seq([(self._tone([f1], d1, level, decay=3.0, wave="tri", attack_s=0.02), 0.0),
                          (self._tone([f2], d2, level, decay=3.5, wave="tri", attack_s=0.02), d1 * 0.85)])

    def _world_event(self, scene, ev: Dict[str, Any]) -> None:
        typ = ev.get("type")
        key = str(ev.get("pip") or ev.get("key") or "")
        if typ == "speak":
            # 10 speaks / min -> auto-mute (CONCEPT 6 pluck rule carried over to motifs)
            self._speak_pos.append(self._pos)
            while self._speak_pos and self._pos - self._speak_pos[0] > 60 * self.sr:
                self._speak_pos.popleft()
            self.plucks_muted = len(self._speak_pos) > 10
            if self.plucks_muted:
                self.stats["motifs_dropped"] += 1
                return
            deg = self._pip_degree(scene, key)
            words = str(ev.get("text") or "").split()
            if self._motif(deg, len(words) or 1, self._pip_pan(scene, key, deg=deg)):
                self.stats["motifs"] += 1
        elif typ == "hatch":
            deg = self._pip_degree(scene, key)
            pan = self._pip_pan(scene, key, ev.get("x"), deg)
            if ev.get("first_ever"):
                self._add(self._repan(self._cache["builder"], pan))
                self.stats["builders"] += 1
                self._motif(deg, 2, pan, offset_s=0.28)
            else:
                self._motif(deg, 2, pan)
            self.stats["hatches"] += 1
        elif typ == "drip_land":
            self._plink(ev.get("x"))
        elif typ == "wake":
            deg = self._pip_degree(scene, key)
            self._sting("wake%d" % deg, lambda: self._third(deg, LVL_WAKE, True))
            gifts = sum(1 for c in (ev.get("care_log") or []) if isinstance(c, dict) and c.get("verb") == "gift")
            for i in range(min(3, gifts)):
                self._events.append((self._pos + int((0.5 + 0.3 * i) * self.sr), self._gift_buf(deg)))
        elif typ == "sleep":
            deg = self._pip_degree(scene, key)
            self._sting("sleep%d" % deg, lambda: self._third(deg, LVL_WAKE, False, octave=0.5, d1=0.20, d2=0.30))
        elif typ == "tier_up":
            deg = self._pip_degree(scene, key)
            self._sting("tier%d" % deg, lambda: self._third(deg, LVL_TIER, True, d1=0.14, d2=0.30))
            self._sweep(0.3)
        elif typ == "feed":
            self._add(self._repan(self._cache["feed"], self._pip_pan(scene, key)))
            self.stats["stings"] += 1
        elif typ == "pet":
            da, dbb = self._pip_degree(scene, str(ev.get("by") or key)), self._pip_degree(scene, key)
            lvl = LVL_CARE - (4.0 if ev.get("asleep") else 0.0)
            self._sting("pet%d_%d_%d" % (da, dbb, int(bool(ev.get("asleep")))), lambda: self._duet(da, dbb, lvl))
        elif typ == "gift":
            deg = self._pip_degree(scene, key)
            self._add(self._gift_buf(deg))
            self.stats["stings"] += 1
        elif typ == "dig":
            self._add(self._repan(self._cache["dig"], self._pip_pan(scene, key)))
            self.stats["stings"] += 1
        elif typ == "plant":
            self._add(self._repan(self._cache["plant"], self._pip_pan(scene, key, ev.get("x"))))
            self.stats["stings"] += 1
        elif typ == "walk":
            to = ev.get("to")
            cap = WALK_CAP_S * (1.5 if to == "burrow" else 1.0)
            if len(self._walking) < 40 or key in self._walking:
                self._walking[key] = [self._pos + int(0.1 * self.sr), self._pos + int(cap * self.sr), 1]
        elif typ == "arrive":
            self._walking.pop(key, None)
            if ev.get("at") in ("A", "B", "C"):
                self.trigger("vote", semitones=self._votes_in_round)
                self._votes_in_round += 1
        elif typ in ("leave_platform", "curl", "uncurl", "blink", "first_light", "forget", "banish", "burrowed",
                     "credits_start", "credits_end", "seed", "world_error"):
            if typ in ("banish", "burrowed"):
                self._walking.pop(key, None)
        elif typ == "seed_land":
            self._add(self._repan(self._cache["seed_land"], self._pip_pan(scene, key, ev.get("x"))))
            self.stats["stings"] += 1
        elif typ == "sink":
            self._add(self._cache["sink"])
            self.stats["stings"] += 1
        elif typ == "hop":
            if self._pos - self._last_hop_pos >= int(HOP_GAP_S * self.sr):
                self._last_hop_pos = self._pos
                self._add(self._repan(self._cache["hop"], self._pip_pan(scene, key)))
        elif typ == "emote":
            kind = str(ev.get("kind") or "")
            self._add(self._repan(self._cache["emote_wave" if kind == "wave" else "emote_low"], self._pip_pan(scene, key)))
            self.stats["stings"] += 1
        elif typ == "credits":
            self._walking.pop(key, None)
            deg = self._pip_degree(scene, key)
            self._sting("credits%d" % deg, lambda: self._third(deg, LVL_CREDITS, False, d1=0.18, d2=0.34))

    def _duet(self, da: int, dbb: int, level: float) -> np.ndarray:
        fa, fb = PENTA_EXT_HZ[max(0, min(11, da))], PENTA_EXT_HZ[max(0, min(11, dbb))]
        dy = self._tone([fa, fb], 0.22, level, decay=3.0, wave="tri", attack_s=0.015)
        return self._seq([(dy, 0.0), (dy, 0.20)])

    def _gift_buf(self, deg: int) -> np.ndarray:
        k = "gift%d" % deg
        if k not in self._cache:
            a, b = PENTA_EXT_HZ[max(0, min(11, deg))], PENTA_EXT_HZ[max(0, min(11, deg + 2))]
            self._cache[k] = self._seq([(self._tone([a], 0.10, LVL_GIFT, decay=3.0, wave="tri", attack_s=0.01), 0.0),
                                        (self._tone([b], 0.10, LVL_GIFT, decay=3.0, wave="tri", attack_s=0.01), 0.10)])
        return self._cache[k]

    def _plink(self, x=None) -> None:
        deg = int(self._drip_rng.integers(0, len(self._drips)))
        pan = 0.0 if x is None else max(-0.6, min(0.6, (float(x) / 320.0 - 0.5) * 1.2))
        self._add(self._repan(self._drips[deg], pan))
        self._last_drip_pos = self._pos
        self.stats["drips"] += 1

    def _world_tick(self, scene) -> int:
        """Consume the scene's events exactly once per scene frame; return the awake count. Never raises."""
        awake = 0
        try:
            fr = getattr(scene, "frames", None)
            if fr is not None and fr != self._world_frames_seen:
                self._world_frames_seen = fr
                evs = getattr(scene, "events", None) or []
                if evs:
                    self.stats["world_events"] += len(evs)
                    for ev in evs:
                        try:
                            if isinstance(ev, dict):
                                self._world_event(scene, ev)
                        except Exception as e:
                            self.errors += 1
                            if self.errors % 100 == 1:
                                self.log("world event %r failed (%r)" % (ev.get("type") if isinstance(ev, dict) else ev, e))
            awake = int(scene.awake_count() or 0)
        except Exception as e:
            self.detect_errors += 1
            if self.detect_errors % 100 == 1:
                self.log("world tick failed (%r); voices hold" % (e,))
            awake = self.awake_voices
        # footsteps: 4 Hz per walking pip, global 1 per 60 ms, alternate left/right, until arrive or the cap
        if self._walking:
            end = self._pos + self.n
            gap, ggap = int(STEP_GAP_S * self.sr), int(STEP_GLOBAL_GAP_S * self.sr)
            for k in list(self._walking):
                st = self._walking[k]
                if st[1] <= self._pos:
                    self._walking.pop(k, None)
                    continue
                while st[0] < end:
                    at = max(st[0], self._last_step_pos + ggap)
                    if at < end:
                        self._events.append((at, self._repan(self._cache["step"], 0.25 * st[2])))
                        self._last_step_pos = at
                        self.stats["steps"] += 1
                        st[2] = -st[2]
                    st[0] = max(st[0], at) + gap
            if len(self._events) > 200:
                del self._events[:-200]
        # self-drips when the scene has been silent about drips for 8 s (an erroring scene still drips)
        if self._pos - self._last_drip_pos > int(SELF_DRIP_AFTER_S * self.sr):
            if self._next_self_drip <= self._pos:
                self._plink(None)
                self.stats["self_drips"] += 1
                self._next_self_drip = self._pos + int(self._drip_rng.uniform(2.0, 6.0) * self.sr)
        else:
            self._next_self_drip = 0
        return awake

    # ================================================================================== layers
    def _cutoff(self) -> float:
        t0 = self._pos / float(self.sr)
        fc = 1200.0 * (1.0 + 0.4 * math.sin(2.0 * math.pi * 0.1 * t0))
        if self._pos < self._sweep_until:
            prog = 1.0 - (self._sweep_until - self._pos) / float(self._sweep_cur)
            fc = 300.0 + (fc - 300.0) * prog * prog
        return fc

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
        fc = self._cutoff()
        mono = self._osc.render(self._note_env, fc, self._ramp)
        return self._haas_pair(mono, kick_env)

    def _haas_pair(self, mono: np.ndarray, kick_env: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        n = self.n
        mono = mono * (1.0 - 0.29 * kick_env)               # sidechain: 3 dB dip on the kick
        # 8 ms Haas: right channel is the left delayed by 384 samples
        full = np.concatenate([self._pad_tail, mono])
        right = full[:n]
        self._pad_tail = full[n:]
        return mono, right

    def _world_pad(self, kick_env: np.ndarray, awake: int) -> Tuple[np.ndarray, np.ndarray, float]:
        """Voice bank: voices == min(8, awake). Returns (left, right, presence) where presence (0..1) gates the pulse."""
        n = self.n
        blk_s = n / float(self.sr)
        nv = max(0, min(VOICES_MAX, int(awake)))
        self.awake_voices = nv
        # per-voice note targets: voice k -> chord tone k % 3 of the current chord; the sub voice -> the root
        chord = CHORDS[self._chord_idx]
        target = np.zeros_like(self._vn_env)
        for vi, (tone, _d, _o, _l) in enumerate(VOICE_TABLE):
            target[vi, PAD_NOTES.index(chord[tone])] = 1.0
        target[SUB_VOICE, PAD_NOTES.index(chord[0])] = 1.0
        up, down = blk_s / 6.0, blk_s / 3.0
        rising = target > self._vn_env
        self._vn_env = np.where(rising, np.minimum(target, self._vn_env + up), np.maximum(target, self._vn_env - down))
        # per-voice awake envelope: 2 s attack, 3 s release; lights-out -> the sub voice + a faint root
        g_target = np.zeros(SUB_VOICE + 1, np.float64)
        if nv > 0:
            if self._weather == "lights-out":
                g_target[0] = 0.5
                g_target[SUB_VOICE] = 1.0
            else:
                g_target[:nv] = 1.0
        a_up, a_down = blk_s / VOICE_ATTACK_S, blk_s / VOICE_RELEASE_S
        rising = g_target > self._vgain
        self._vgain = np.where(rising, np.minimum(g_target, self._vgain + a_up), np.maximum(g_target, self._vgain - a_down))
        presence = float(min(1.0, self._vgain[:SUB_VOICE].sum() + self._vgain[SUB_VOICE]))
        if presence <= 1e-6 and not (self._bank.prev_amp > 1e-5).any():
            self._bank.phase = (self._bank.phase + self._bank.inc * n) % 1.0
            zero = np.zeros(n, np.float64)
            l, r = self._haas_pair(zero, kick_env)
            return l, r, 0.0
        # level: (3 / max(n, 3)) ** 0.25 per voice so 8 voices sit ~1 dB over the 3-voice calibration point
        lvl = (3.0 / max(3.0, float(max(nv, 1)))) ** 0.25
        vgain = self._vgain * lvl
        fc = self._cutoff()
        if self._weather == "fog":
            fc *= 0.5
        mono = self._bank.render_voices(self._vn_env, vgain, fc, self._ramp)
        l, r = self._haas_pair(mono, kick_env)
        return l, r, presence

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

    def _rain_block(self) -> Optional[np.ndarray]:
        """Glow-rain: the pink loop with a 1 s fade in / out; None when silent."""
        n = self.n
        target = 1.0 if self._weather == "glow-rain" else 0.0
        if target <= 0.0 and self._rain_env <= 1e-6:
            return None
        step = n / float(self.sr)                           # 1 s ramp
        e0 = self._rain_env
        e1 = min(1.0, e0 + step) if target > e0 else max(0.0, e0 - step)
        self._rain_env = e1
        m = self._rain.shape[0]
        i0 = self._rain_pos
        i1 = i0 + n
        if i1 <= m:
            seg = self._rain[i0:i1]
        else:
            seg = np.concatenate([self._rain[i0:], self._rain[:i1 - m]])
        self._rain_pos = i1 % m
        env = e0 + (e1 - e0) * self._ramp
        return seg * env[:, None]

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
            scene = self._scene()
            self.world_mode = scene is not None
            try:
                self._detect(ctx)                           # a malformed ctx must not silence the bed
            except Exception as e:
                self.detect_errors += 1
                if self.detect_errors % 100 == 1:
                    self.log("ctx detection failed (%r); bed continues" % (e,))
            scene = self._world if self._world is not None else scene   # ctx.world may have attached one
            self.world_mode = scene is not None
            pulse, kick_env = self._pulse()
            if self.world_mode:
                self.stats["world_blocks"] += 1
                awake = self._world_tick(scene)
                pad_l, pad_r, presence = self._world_pad(kick_env, awake)
                pulse = pulse * presence                    # 0 awake: drips and crackle only
            else:
                self.awake_voices = 0
                pad_l, pad_r = self._pad(kick_env)
            tex = self._texture()
            self._pluck_bus()
            pad_gain = VOICE_GAIN if self.world_mode else PAD_GAIN
            out = np.empty((self.n, 2), np.float64)
            out[:, 0] = pad_l * pad_gain + pulse * PULSE_GAIN + tex * TEX_GAIN
            out[:, 1] = pad_r * pad_gain + pulse * PULSE_GAIN + tex * TEX_GAIN
            if self.world_mode:
                rain = self._rain_block()
                if rain is not None:
                    out += rain
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
    #   default: 10 s with every legacy event fired via a fake ctx; --bed renders the bed alone for calibration.
    #   --world      drive a REAL CaveScene (RUN_DIR must be under /tmp) with scripted chat records, verbs, votes,
    #                weather and a keeper build; the engine consumes the scene's events (WORLD.md 7 evidence run)
    #   --world-cal N  render N steady voices (no events) for the VOICE_GAIN calibration number
    import argparse
    import os
    import time

    ap = argparse.ArgumentParser()
    ap.add_argument("--bed", action="store_true", help="bed only (pad+pulse+texture), no events")
    ap.add_argument("--world", action="store_true", help="world mode against a real CaveScene in $RUN_DIR (/tmp only)")
    ap.add_argument("--world-cal", type=int, default=None, help="steady N-voice pad for level calibration")
    ap.add_argument("--out", default=None, help="write raw s16le stereo 48k to this path")
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--awake", type=int, default=3, help="--world: how many scripted chatters (1-8)")
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
    report: List[str] = []

    if a.world_cal is not None:
        class _Steady(object):
            frames = 0
            events: List[Dict] = []

            def __init__(self, n):
                self.n = n

            def awake_count(self):
                return self.n
        e.attach_world(_Steady(a.world_cal))
        raw = []
        for i in range(frames):
            e._vgain[:] = 0.0                                # measure the raw voice sum at full gain, no attack
            e._vgain[:a.world_cal] = 1.0
            kick0 = np.zeros(e.n)
            l, r, _p = e._world_pad(kick0, a.world_cal)
            e._pos += e.n
            raw.append(l)
        x = np.concatenate(raw[30:])                         # skip the note-envelope attack
        rms = float(np.sqrt(np.mean(x ** 2)))
        print("world-cal voices=%d raw voice-bank RMS %.2f dBFS (VOICE_GAIN is derived from the 3-voice number)" % (
            a.world_cal, 20 * math.log10(rms) if rms > 0 else -120))
        sys.exit(0)

    scene = None
    if a.world:
        run_dir = os.environ.get("RUN_DIR") or "/tmp/pip-audio"
        rp = os.path.realpath(run_dir)
        assert rp.startswith("/tmp/") or rp.startswith("/private/tmp/"), "world harness: RUN_DIR must be under /tmp (%s)" % run_dir
        os.makedirs(run_dir, exist_ok=True)
        os.environ["RUN_DIR"] = run_dir
        os.environ.pop("KL_TEST_PIPS", None)                 # no synthetic pips: every pip below comes from a chat record
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)
        from stream.scenes.hollow import CaveScene
        from stream.state_store import epoch_to_iso
        wj = os.path.join(run_dir, "world.json")
        if os.path.exists(wj):
            os.remove(wj)
        scene = CaveScene(run_dir=run_dir, seed=7, sleep_after_s=20.0)   # 20 s sleep window so sleep is heard in-run
        # NOT attached explicitly: prove the auto-discovery path (a module attribute named SCENE on a loaded module)
        import stream.scenes.hollow as _hm
        _hm.SCENE = scene
        session = {"id": "audio-harness", "started_ts": epoch_to_iso(t0 - 30, ms=False), "ending": False}
        names = ["harness-ada", "harness-bo", "harness-cy", "harness-di", "harness-ez", "harness-fay", "harness-gus", "harness-hal"][:max(1, min(8, a.awake))]
        raw_recs: List[Dict] = []
        clear_recs: List[Dict] = []
        rec_i = [0]

        def rec(name, text, t, kind="plain", letter=None):
            rec_i[0] += 1
            return {"id": "au-%04d" % rec_i[0], "ts": None, "t": t, "name": name, "text": text, "text_clean": text,
                    "kind": kind, "letter": letter, "display_name": name, "builder_n": None, "first_ever": True,
                    "dropped": False, "show_t": t + 3.0}

        SIZE = (1280, 440)
        awake_log: List[Tuple[int, int, int]] = []
        sound_at: Dict[str, int] = {}
        scene_ev: Dict[str, int] = {}
        pending_clear: List[Tuple[int, Dict]] = []
        votes: List[Tuple[str, str, float]] = []
        weather = "clear"
        macro = {"active": False, "last_reload": None}
        version = {"string": "v0.5.0", "failed": 0}
        rnd_no = 1
        hidden: List[str] = []

    version_l = {"string": "v0.1.0", "failed": 0}
    votes_l = 0
    builders = 0
    theme = {"set_ts": None}
    chat: List[Dict] = []
    ending = False
    for i in range(frames):
        now = t0 + i / 30.0
        if a.world:
            # ---- script: chatters arrive 1.5 s apart (seed -> hatch 3 s later), talk, vote, get fed/petted, dig,
            # plant, emote; weather + a keeper build; then everyone sleeps (20 s quiet) and the session ends
            for k, nm in enumerate(names):
                if i == 30 + k * 45:
                    r = rec(nm, "hello cave %d words here" % (k + 2), now)
                    raw_recs.append(r)
                    pending_clear.append((i + 90, dict(r)))
                if i == 30 + k * 45 + 240:
                    r = rec(nm, "again from %s" % nm, now)
                    raw_recs.append(r)
                    pending_clear.append((i + 90, dict(r)))
            if i == 60 and len(names) >= 1:
                r = rec("harness-hidden", "hi", now)
                raw_recs.append(r)                           # hidden by a mod inside the hold: the seed sinks
            if i >= 75:
                hidden = ["harness-hidden"]
            if i == 420 and names:
                votes = [(names[0], "B", now)]
                r = rec(names[0], "B", now, "vote", "B")
                raw_recs.append(r)
                pending_clear.append((i + 90, dict(r)))
            if i == 450 and len(names) > 1:
                votes = votes + [(names[1], "A", now)]
            if i == 480 and len(names) > 1:
                scene.command("feed", names[1], names[0], now=now)
            if i == 520 and len(names) > 1:
                scene.command("pet", names[0], names[1], now=now)
            if i == 560 and names:
                scene.command("dig", names[0], now=now)
            if i == 600 and names:
                scene.command("plant", names[0], now=now)
            if i == 620 and names:
                scene.command("wave", names[0], now=now)
            if i == 640 and names:
                scene.command("hop", names[0], now=now)
            if i == 660:
                weather = "glow-rain"
            if i == 720:
                weather = "lights-out"
            if i == 780:
                weather = "fog"
            if i == 840:
                weather = "clear"
            if i == 700:
                macro = {"active": True, "last_reload": None}
            if i == 760:
                macro = {"active": True, "last_reload": {"ts": "2026-09-25T12:00:00Z", "ok": True, "module": "stream/scenes/hollow.py"}}
            if i == 800:
                version = {"string": "v0.5.1", "failed": 0}
                rnd_no = 2                                   # round change releases the platforms
            if i == frames - 300:
                ending = True                                # 10 s of credits: every awake pip walks to its burrow
            for due, r in list(pending_clear):
                if i >= due:
                    clear_recs.append(r)
                    pending_clear.remove((due, r))
            ctx = FakeCtx(now=now, frame=i, fps=30.0, session=dict(session, ending=ending), micro={"canvas_seed": 41370704, "weather": weather, "audio_tempo": 85},
                          preset="kick", chat_raw=list(raw_recs[-20:]), chat=list(clear_recs[-10:]), recent_votes=list(votes[-5:]),
                          round={"number": rnd_no, "phase": "open", "last_result": {"title": "feast: everyone eats"}}, round_remaining=100.0,
                          mod={"hidden_users": list(hidden)}, agent={"heartbeat_ts": "2026-09-25T12:00:00Z"}, macro=macro,
                          compositor_live={"selftest": True}, mod_paused=False, version=version, vote_count=len(votes),
                          chat_display=True, theme={"set_ts": None})
            awake_before = scene.awake_count() if scene.booted else 0   # what the scene says when the block runs
            tp = time.perf_counter()
            b = e.block(i, ctx)                              # audio FIRST, exactly like Compositor.render_frame
            times.append((time.perf_counter() - tp) * 1000)
            scene.frame(ctx, SIZE)
            for ev in scene.events:
                scene_ev[ev["type"]] = scene_ev.get(ev["type"], 0) + 1
            if i % 30 == 0:
                awake_log.append((i // 30, awake_before, e.awake_voices))
        else:
            if not a.bed:
                if i == 30:
                    chat.append({"id": "m1", "name": "alice", "t": now})
                if i == 32:
                    chat.append({"id": "m2", "name": "bob", "t": now})
                if i == 34:
                    chat.append({"id": "m3", "name": "carol", "t": now})
                if i in (60, 75, 90):
                    votes_l += 1
                if i == 120:
                    version_l = {"string": "v0.1.1", "failed": 0}
                if i == 165:
                    version_l = {"string": "v0.1.1", "failed": 1}
                if i == 210:
                    builders += 1
                if i == 240:
                    theme = {"set_ts": "2026-01-01T00:00:00Z"}
                rem = 12.0 - (i - 150) / 30.0 if i >= 150 else 100.0
            else:
                rem = 100.0
            ctx = FakeCtx(now=now, frame=i, micro={"audio_tempo": 85}, round={"number": 1, "phase": "open"},
                          round_remaining=rem, vote_count=votes_l, version=version_l, new_builders=builders,
                          theme=theme, chat=list(chat[-10:]), chat_display=True)
            tp = time.perf_counter()
            b = e.block(i, ctx)
            times.append((time.perf_counter() - tp) * 1000)
        peak = max(peak, int(np.abs(b.astype(np.int32)).max()))
        chunks.append(b)
    pcm = np.concatenate(chunks)
    rms = float(np.sqrt(np.mean((pcm.astype(np.float64) / 32767.0) ** 2)))
    times_np = np.asarray(times)
    print("frames=%d block=%s dtype=%s mode=%s" % (frames, chunks[0].shape, chunks[0].dtype, "world" if e.world_mode else "legacy"))
    print("ms/block: avg %.3f  p95 %.3f  p99 %.3f  max %.3f (frame %d)  blocks over 1.5 ms: %d of %d" % (
        times_np.mean(), np.percentile(times_np, 95), np.percentile(times_np, 99), times_np.max(), int(times_np.argmax()),
        int((times_np > 1.5).sum()), len(times_np)))
    print("rms %.2f dBFS  peak %d (%.2f dBFS)  errors=%d detect_errors=%d muted=%s" % (
        20 * math.log10(rms) if rms > 0 else -120, peak, 20 * math.log10(peak / 32767.0), e.errors, e.detect_errors, e.plucks_muted))
    print("stats=%s" % e.stats)
    if a.out:
        with open(a.out, "wb") as fh:
            fh.write(pcm.tobytes())
        print("wrote %s (%d bytes)" % (a.out, pcm.nbytes))
    if a.world:
        print("scene events: %s" % dict(sorted(scene_ev.items())))
        print("awake (as the scene reported it when the block ran) vs pad voices, per second (s, awake, voices): %s" % awake_log)
        bad = [(s, aw, v) for s, aw, v in awake_log if v != min(8, aw)]
        print("HONESTY pad voices == min(8, awake) at every sampled second: %s%s" % ("OK" if not bad else "FAIL", "" if not bad else " %r" % bad))
        st = scene.stats()
        print("scene honesty_violations=%d test_pips=%d errors=%d hatched_ever=%d" % (st["honesty_violations"], st["test_pips"], st["errors"], st["hatched_ever"]))
        assert not bad, bad
        assert st["honesty_violations"] == 0 and st["test_pips"] == 0
        assert e.errors == 0 and e.detect_errors == 0, (e.errors, e.detect_errors)
