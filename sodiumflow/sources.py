"""Replaceable sources: deterministic simulator, saved CSV, serial stream."""
from __future__ import annotations
import csv
import math
from collections import deque
from pathlib import Path
import numpy as np


class Simulator:
    """Correlated band-limited noise transported between measurement points."""
    def __init__(self, fs=860., spacing=0.15, velocity=2.4, noise=0.12, seed=42):
        self.fs, self.spacing, self.velocity, self.noise = fs, spacing, velocity, noise
        self.rng = np.random.default_rng(seed)
        self.history = np.zeros(int(fs * 2) + 10)
        self.state = 0.0
        self.index = 0

    def read(self, count: int):
        count = max(1, int(count))
        # Generate a colored broadband random feature sequence continuously.
        white = self.rng.normal(size=count)
        features = np.empty(count)
        for i, w in enumerate(white):
            self.state = 0.65 * self.state + 0.35 * w
            features[i] = self.state
        old = self.history
        full = np.concatenate([old, features])
        offset = self.spacing / self.velocity * self.fs
        query = len(old) + np.arange(count) - offset
        downstream = np.interp(query, np.arange(len(full)), full)
        self.history = full[-len(old):].copy()
        x = features + self.rng.normal(scale=self.noise, size=count)
        y = downstream + self.rng.normal(scale=self.noise, size=count)
        t = (self.index + np.arange(count)) / self.fs
        self.index += count
        return t, x, y


class CsvReplay:
    """CSV columns time_s, ch1_v, ch2_v; sampling rate must match configuration."""
    def __init__(self, path: str, fs: float):
        with open(path, encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f))
        if len(rows) < 2:
            raise ValueError('CSV пуст')
        values = np.array([[float(r[k]) for k in ('time_s', 'ch1_v', 'ch2_v')] for r in rows], dtype=float)
        if not np.all(np.isfinite(values)) or np.any(np.diff(values[:, 0]) <= 0):
            raise ValueError('Некорректные временные метки CSV')
        actual = 1 / np.median(np.diff(values[:, 0]))
        if abs(actual / fs - 1) > 0.02:
            raise ValueError(f'Частота CSV {actual:.2f} Гц отличается от настроенной {fs:.2f} Гц')
        self.data, self.pos = values, 0

    def read(self, count):
        if self.pos >= len(self.data):
            raise EOFError('Файл CSV полностью воспроизведён')
        end = min(self.pos + count, len(self.data))
        part = self.data[self.pos:end]
        self.pos = end
        return part[:, 0], part[:, 1], part[:, 2]


class SerialStream:
    """Custom USB serial adapter protocol: ASCII `time_s,ch1_v,ch2_v` per line.

    This is *not* a universal ADS1115 driver. A bridge MCU must sample both
    ADCs with a shared timebase and transmit timestamped, synchronized pairs.
    """
    def __init__(self, port, baud=230400, timeout=0.04):
        import serial
        self.connection = serial.Serial(port, baudrate=baud, timeout=timeout)
        self.buffer = deque()

    def read(self, count):
        # Nonblocking UI-friendly bounded reads; serial I/O in production
        # should be moved to a QThread if the bridge can block.
        for _ in range(min(int(count), 1024)):
            line = self.connection.readline()
            if not line:
                break
            try:
                t, a, b = map(float, line.decode('ascii').strip().split(','))
                if all(map(math.isfinite, (t, a, b))):
                    self.buffer.append((t, a, b))
            except (ValueError, UnicodeDecodeError):
                continue
        take = min(int(count), len(self.buffer))
        if not take:
            return np.array([]), np.array([]), np.array([])
        block = np.array([self.buffer.popleft() for _ in range(take)])
        return block[:, 0], block[:, 1], block[:, 2]

    def close(self):
        self.connection.close()
