"""Pure, hardware-independent DSP and engineering calculations."""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
from scipy.signal import butter, sosfiltfilt, correlate, correlation_lags, detrend


@dataclass(frozen=True)
class Settings:
    sample_rate: float = 860.0
    sensor_spacing_m: float = 0.15
    pipe_diameter_mm: float = 30.0
    lowcut_hz: float = 3.0
    highcut_hz: float = 250.0
    min_velocity_m_s: float = 0.2
    max_velocity_m_s: float = 8.0
    min_correlation: float = 0.45
    window_seconds: float = 3.0
    calibration_factor: float = 1.0

    def validate(self) -> None:
        if not (20 <= self.sample_rate <= 100000):
            raise ValueError('Частота дискретизации должна быть 20–100000 Гц')
        if self.sensor_spacing_m <= 0 or self.pipe_diameter_mm <= 0:
            raise ValueError('Геометрические размеры должны быть положительными')
        if not (0 < self.lowcut_hz < self.highcut_hz < self.sample_rate / 2):
            raise ValueError('Полоса фильтра должна быть строго ниже частоты Найквиста')
        if not (0 < self.min_velocity_m_s < self.max_velocity_m_s):
            raise ValueError('Пределы скорости заданы неверно')
        if not (0 < self.min_correlation <= 1):
            raise ValueError('Минимальная корреляция должна быть от 0 до 1')
        if not (0.3 <= self.window_seconds <= 30):
            raise ValueError('Окно анализа должно быть от 0.3 до 30 секунд')
        if self.calibration_factor <= 0:
            raise ValueError('Поправочный коэффициент должен быть положительным')


@dataclass
class Result:
    valid: bool
    reason: str
    velocity_m_s: float | None
    flow_m3_h: float | None
    lag_s: float | None
    coefficient: float
    snr: float
    sigma_ch1: float
    sigma_ch2: float
    rms_ch1: float
    rms_ch2: float
    lags_s: np.ndarray
    correlations: np.ndarray
    filtered_ch1: np.ndarray
    filtered_ch2: np.ndarray
    frequencies_hz: np.ndarray
    spectrum_ch1: np.ndarray


def analyze(ch1: np.ndarray, ch2: np.ndarray, cfg: Settings) -> Result:
    """Cross-correlate simultaneous, uniformly spaced channel samples.

    A positive lag indicates that channel 2 receives the feature after channel 1.
    Rejects negative and physically impossible propagation delays. The parabolic
    peak adjustment is an estimate, not additional acquired samples.
    """
    cfg.validate()
    a, b = np.asarray(ch1, dtype=float), np.asarray(ch2, dtype=float)
    if a.ndim != 1 or b.ndim != 1 or len(a) != len(b) or len(a) < max(64, int(cfg.sample_rate * 0.4)):
        raise ValueError('Нужны два равных одномерных массива минимум по 0.4 с')
    if not (np.all(np.isfinite(a)) and np.all(np.isfinite(b))):
        raise ValueError('Сигналы содержат NaN или бесконечность')
    sos = butter(4, [cfg.lowcut_hz, cfg.highcut_hz], btype='bandpass', fs=cfg.sample_rate, output='sos')
    x, y = sosfiltfilt(sos, detrend(a)), sosfiltfilt(sos, detrend(b))
    sigma_a, sigma_b = float(np.std(x)), float(np.std(y))
    freqs = np.fft.rfftfreq(len(x), 1 / cfg.sample_rate)
    magnitude = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    lag_min = cfg.sensor_spacing_m / cfg.max_velocity_m_s
    lag_max = cfg.sensor_spacing_m / cfg.min_velocity_m_s
    lags = correlation_lags(len(y), len(x), mode='full')
    corr = correlate(y, x, mode='full', method='fft')
    # Correct overlap/sample count bias at large lags, with per-pair Pearson
    # normalization at the selected peak below.
    lo = max(1, int(math.ceil(lag_min * cfg.sample_rate)))
    hi = min(len(x) - 3, int(math.floor(lag_max * cfg.sample_rate)))
    valid_range = (lags >= lo) & (lags <= hi)
    norm = (sigma_a * sigma_b * len(x))
    normalized = corr / norm if norm > 1e-15 else np.zeros_like(corr)
    selected = np.flatnonzero(valid_range)
    def output(reason: str, lag: float | None = None, coefficient: float = 0.0, snr: float = 0.0):
        velocity = cfg.sensor_spacing_m / lag if lag is not None else None
        flow = velocity * math.pi * (cfg.pipe_diameter_mm / 2000) ** 2 * 3600 * cfg.calibration_factor if velocity is not None else None
        return Result(reason == 'OK', reason, velocity if reason == 'OK' else None,
                      flow if reason == 'OK' else None, lag if reason == 'OK' else None,
                      coefficient, snr, sigma_a, sigma_b, float(np.sqrt(np.mean(a*a))),
                      float(np.sqrt(np.mean(b*b))), lags / cfg.sample_rate,
                      normalized, x, y, freqs, magnitude)
    if sigma_a < 1e-8 or sigma_b < 1e-8:
        return output('Недостаточная вариация сигнала')
    if selected.size == 0:
        return output('Заданный диапазон скорости не разрешается при этой частоте АЦП')
    peak_i = selected[np.argmax(normalized[selected])]
    # True normalized Pearson correlation on aligned, overlapping pairs.
    nlag = int(lags[peak_i])
    left, right = x[:-nlag], y[nlag:]
    left, right = left - left.mean(), right - right.mean()
    pair_norm = np.linalg.norm(left) * np.linalg.norm(right)
    rho = float(np.dot(left, right) / pair_norm) if pair_norm > 1e-15 else 0.0
    background = normalized[selected]
    snr = float((normalized[peak_i] - np.median(background)) / (np.std(background) + 1e-12))
    fraction = 0.0
    if 1 <= peak_i < len(corr) - 1:
        c0, c1, c2 = normalized[peak_i - 1:peak_i + 2]
        denominator = c0 - 2*c1 + c2
        if abs(denominator) > 1e-12:
            fraction = float(np.clip(0.5*(c0-c2)/denominator, -0.5, 0.5))
    delay = (nlag + fraction) / cfg.sample_rate
    if rho < cfg.min_correlation:
        return output('Низкая достоверность корреляции', coefficient=rho, snr=snr)
    if delay <= 0:
        return output('Не обнаружена положительная задержка', coefficient=rho, snr=snr)
    return output('OK', delay, rho, snr)
