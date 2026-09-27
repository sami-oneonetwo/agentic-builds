"""Crackle, drone, pop. Loudness follows the flame. No melody that wants a HUD."""
from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np


class FireAudio:
    def __init__(self, sr: int = 48000, block: int = 1600, fps: float = 30.0) -> None:
        self.sr = sr
        self.block = block
        self.fps = fps
        self.t = 0
        self.rng = np.random.RandomState(7)
        self.crackle_state = 0.0
        self.pops: List[Tuple[int, float]] = []  # start sample, pan
        self.last_heat = 0.1
        self.level_dbfs = -60.0

    def pop(self, pan: float = 0.0) -> None:
        self.pops.append((self.t, max(-1.0, min(1.0, pan))))
        if len(self.pops) > 12:
            self.pops = self.pops[-12:]

    def block_pcm(self, heat: float, mood: str) -> np.ndarray:
        n = self.block
        t0 = self.t
        tt = (t0 + np.arange(n)) / float(self.sr)
        heat = max(0.0, min(1.2, heat))

        # low drone: two detuned partials. thicker as the fire grows. almost gone in ash.
        f1 = 46.0 + 8.0 * heat
        f2 = f1 * 1.005
        drone_amp = 0.012 + 0.05 * heat
        if mood == "ash":
            drone_amp *= 0.25
        drone = drone_amp * (np.sin(2 * math.pi * f1 * tt) + 0.6 * np.sin(2 * math.pi * f2 * tt))
        # a slow breath on the drone
        drone *= 0.75 + 0.25 * np.sin(2 * math.pi * 0.07 * tt)

        # crackle: sparse noise bursts, denser with heat
        white = self.rng.randn(n)
        # one-pole lowpass
        out_c = np.empty(n)
        x = self.crackle_state
        cut = 0.18 + 0.45 * heat
        for i, w in enumerate(white):
            x = x + cut * (w - x)
            out_c[i] = x
        self.crackle_state = float(x)
        density = 0.002 + 0.03 * heat
        gate = (self.rng.rand(n) < density).astype(np.float64)
        # decaying clicks
        crackle = out_c * gate * (0.08 + 0.22 * heat)
        if mood == "ash":
            crackle *= 0.15

        # wind when dying
        wind = np.zeros(n)
        if mood in ("ash", "embers"):
            wind = 0.012 * out_c * (0.4 + 0.6 * np.sin(2 * math.pi * 0.11 * tt))

        # roar in wildfire
        roar = np.zeros(n)
        if mood == "wildfire":
            roar = 0.07 * out_c * (0.5 + 0.5 * np.sin(2 * math.pi * 8.0 * tt))

        left = drone + crackle + wind + roar
        right = drone * 0.96 + crackle * 1.04 + wind * 1.1 + roar
        # pops (a log landing)
        for start, pan in self.pops:
            rel = t0 - start
            if rel >= n or rel + n < 0:
                continue
            env = np.arange(n) + rel
            # 90 ms thud
            dur = int(0.09 * self.sr)
            e = np.clip(1.0 - env / float(dur), 0, 1)
            e = e * e
            thud = e * 0.22 * np.sin(2 * math.pi * 90.0 * (tt - tt[0]))
            spark = e * 0.08 * white
            g = thud + spark
            lamt = 0.5 - 0.5 * pan
            ramt = 0.5 + 0.5 * pan
            left = left + g * lamt
            right = right + g * ramt
        # drop finished pops
        self.pops = [(s, p) for s, p in self.pops if self.t + n - s < self.sr]

        stereo = np.stack([left, right], axis=1)
        peak = np.max(np.abs(stereo))
        if peak > 0.55:
            stereo *= 0.55 / peak
        pcm = np.clip(stereo * 32767.0, -32767, 32767).astype(np.int16)
        rms = float(np.sqrt(np.mean((pcm.astype(np.float64) / 32767.0) ** 2)))
        self.level_dbfs = -120.0 if rms < 1e-9 else 20.0 * math.log10(rms)
        self.t += n
        self.last_heat = heat
        return pcm
