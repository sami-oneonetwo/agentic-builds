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
        self.bright_state = 0.0
        self.pops: List[Tuple[int, float]] = []  # start sample, pan
        self.last_heat = 0.1
        self.level_dbfs = -60.0

    def pop(self, pan: float = 0.0) -> None:
        self.pops.append((self.t, max(-1.0, min(1.0, pan))))
        if len(self.pops) > 12:
            self.pops = self.pops[-12:]

    def _onepole(self, white: np.ndarray, cut: float, state: float) -> Tuple[np.ndarray, float]:
        n = white.shape[0]
        out = np.empty(n, dtype=np.float64)
        x = state
        a = float(cut)
        for i in range(n):
            x = x + a * (float(white[i]) - x)
            out[i] = x
        return out, float(x)

    def block_pcm(self, heat: float, mood: str) -> np.ndarray:
        n = self.block
        t0 = self.t
        tt = (t0 + np.arange(n)) / float(self.sr)
        heat = max(0.0, min(1.2, heat))
        # ramp heat across the block so a log catching doesn't click
        h_line = np.linspace(self.last_heat, heat, n)

        f1 = 42.0 + 14.0 * heat
        f2 = f1 * 1.007
        f3 = f1 * 0.51
        drone_amp = 0.010 + 0.062 * heat
        if heat < 0.03:
            drone_amp *= 0.20
        drone = drone_amp * (
            np.sin(2 * math.pi * f1 * tt)
            + 0.55 * np.sin(2 * math.pi * f2 * tt)
            + 0.35 * np.sin(2 * math.pi * f3 * tt)
        )
        drone *= 0.78 + 0.22 * np.sin(2 * math.pi * 0.07 * tt)

        white = self.rng.randn(n)
        cut = 0.14 + 0.50 * heat
        low, self.crackle_state = self._onepole(white, cut, self.crackle_state)
        bright, self.bright_state = self._onepole(white, min(0.85, 0.35 + 0.5 * heat), self.bright_state)

        density = 0.0015 + 0.038 * heat
        gate = (self.rng.rand(n) < density).astype(np.float64)
        # hold a click for a few samples so it reads as a spark, not a zip
        hold = np.maximum(gate, np.roll(gate, 1) * 0.6)
        crackle = (low * 0.65 + bright * 0.35) * hold * (0.07 + 0.28 * h_line)
        if heat < 0.03:
            crackle *= 0.12

        wind = np.zeros(n)
        wind_amp = 0.016 * max(0.0, 0.28 - heat) / 0.28
        if wind_amp > 0:
            wind = wind_amp * low * (0.45 + 0.55 * np.sin(2 * math.pi * 0.11 * tt))

        roar_amp = 0.10 * max(0.0, heat - 0.48) / 0.67
        roar = roar_amp * low * (0.55 + 0.45 * np.sin(2 * math.pi * (6.0 + 6.0 * heat) * tt))

        left = drone + crackle + wind + roar
        right = drone * 0.96 + crackle * 1.05 + wind * 1.12 + roar * 0.98

        for start, pan in self.pops:
            rel = t0 - start
            if rel >= n or rel + n < 0:
                continue
            env = (np.arange(n) + rel).astype(np.float64)
            dur = int(0.11 * self.sr)
            e = np.clip(1.0 - env / float(dur), 0, 1)
            e = e * e
            thud = e * 0.26 * np.sin(2 * math.pi * 78.0 * (tt - tt[0]))
            spark = e * 0.10 * white
            g = thud + spark
            lamt = 0.5 - 0.5 * pan
            ramt = 0.5 + 0.5 * pan
            left = left + g * lamt
            right = right + g * ramt
        self.pops = [(s, p) for s, p in self.pops if self.t + n - s < self.sr]

        stereo = np.stack([left, right], axis=1)
        peak = float(np.max(np.abs(stereo)))
        if peak > 0.55:
            stereo *= 0.55 / peak
        pcm = np.clip(stereo * 32767.0, -32767, 32767).astype(np.int16)
        rms = float(np.sqrt(np.mean((pcm.astype(np.float64) / 32767.0) ** 2)))
        self.level_dbfs = -120.0 if rms < 1e-9 else 20.0 * math.log10(rms)
        self.t += n
        self.last_heat = heat
        return pcm
