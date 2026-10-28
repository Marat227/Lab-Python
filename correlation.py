"""
Кросс-корреляция для определения временной задержки.
"""

import numpy as np
import logging

import config

logger = logging.getLogger(__name__)


def cross_correlate(s1: np.ndarray, s2: np.ndarray,
                    fs: float = config.TARGET_SPS) -> dict:
    """
    Кросс-корреляция двух сигналов.
    Возвращает задержку τ, скорость v, и метаданные.
    """
    # Убираем DC-компоненту
    s1 = s1 - np.mean(s1)
    s2 = s2 - np.mean(s2)

    # FFT-based корреляция
    n = len(s1)
    fft_size = 2 * n
    S1 = np.fft.rfft(s1, fft_size)
    S2 = np.fft.rfft(s2, fft_size)
    R = np.fft.irfft(S1 * np.conj(S2), fft_size)

    # Нормировка
    std1 = np.std(s1)
    std2 = np.std(s2)
    if std1 > 1e-9 and std2 > 1e-9:
        R /= (std1 * std2 * n)
    else:
        logger.warning("Signal std too low, correlation may be unreliable")

    # Сдвиг
    R = np.concatenate([R[n:], R[:n]])
    lags = np.arange(-n, n) / fs

    # Пик
    peak_idx = np.argmax(np.abs(R))
    tau = lags[peak_idx]
    correlation_peak = R[peak_idx]

    # Скорость
    if abs(tau) > 1e-9:
        velocity = config.SENSOR_DISTANCE_M / abs(tau)
    else:
        velocity = 0.0

    return {
        'tau': tau,
        'velocity': velocity,
        'correlation_peak': correlation_peak,
        'R': R,
        'lags': lags,
        'peak_idx': peak_idx,
    }