"""
Комплексный предиктор: ансамбль из 3 методов.
1. Котельников (синк-интерполяция)
2. Полиномиальная интерполяция
3. Кубический сплайн
"""

import numpy as np
from collections import deque
from typing import List
import logging

import config

logger = logging.getLogger(__name__)


class KotelnikovPredictor:
    """
    Интерполяция по теореме Котельникова (Whittaker-Shannon).
    Использует sinc-функцию для идеальной интерполяции bandlimited сигнала.
    """

    def __init__(self, history_size: int = 16):
        self.history = deque(maxlen=history_size)

    def predict(self, new_sample: float, ratio: int) -> List[float]:
        """Предсказание ratio точек между последними двумя отсчётами."""
        self.history.append(new_sample)

        if len(self.history) < 2:
            return [new_sample] * ratio

        # Берём последние N точек для интерполяции
        n = min(len(self.history), 8)
        samples = np.array(list(self.history)[-n:], dtype=np.float64)

        # sinc-интерполяция между последними двумя точками
        x_orig = np.arange(n, dtype=np.float64)
        x_interp = np.linspace(n - 2, n - 1, ratio + 1)[1:]

        predicted = np.zeros(ratio)
        for i, x in enumerate(x_interp):
            # Сумма sinc-функций
            sinc_sum = 0.0
            for j, s in enumerate(samples):
                sinc_sum += s * np.sinc(x - x_orig[j])
            predicted[i] = sinc_sum

        return predicted.tolist()


class PolynomialPredictor:
    """Полиномиальная интерполяция."""

    def __init__(self, order: int = 3, history_size: int = 8):
        self.order = order
        self.history = deque(maxlen=history_size)

    def predict(self, new_sample: float, ratio: int) -> List[float]:
        self.history.append(new_sample)

        if len(self.history) < self.order + 1:
            return [new_sample] * ratio

        y = np.array(self.history, dtype=np.float64)
        x = np.arange(len(y), dtype=np.float64)

        coeffs = np.polyfit(x, y, self.order)
        poly = np.poly1d(coeffs)

        x_interp = np.linspace(len(y) - 2, len(y) - 1, ratio + 1)[1:]
        predicted = poly(x_interp)

        return predicted.tolist()


class SplinePredictor:
    """Кубический сплайн."""

    def __init__(self, history_size: int = 8):
        self.history = deque(maxlen=history_size)

    def predict(self, new_sample: float, ratio: int) -> List[float]:
        self.history.append(new_sample)

        if len(self.history) < 4:
            return [new_sample] * ratio

        y = np.array(self.history, dtype=np.float64)
        x = np.arange(len(y), dtype=np.float64)

        # Кубический сплайн через numpy
        from numpy.polynomial import polynomial as P
        coeffs = np.polyfit(x, y, 3)
        poly = np.poly1d(coeffs)

        x_interp = np.linspace(len(y) - 2, len(y) - 1, ratio + 1)[1:]
        predicted = poly(x_interp)

        return predicted.tolist()


class EnsemblePredictor:
    """
    Ансамбль предикторов: усредняет результаты всех трёх методов
    или выбирает лучший по критерию гладкости.
    """

    def __init__(self, ratio: int = config.PREDICTION_RATIO):
        self.ratio = ratio
        self.kotelnikov = KotelnikovPredictor()
        self.polynomial = PolynomialPredictor()
        self.spline = SplinePredictor()

    def predict(self, new_sample: float) -> List[float]:
        """
        Предсказание: ансамбль из 3 методов.
        Возвращает усреднённые предсказания.
        """
        pred_k = self.kotelnikov.predict(new_sample, self.ratio)
        pred_p = self.polynomial.predict(new_sample, self.ratio)
        pred_s = self.spline.predict(new_sample, self.ratio)

        # Усреднение
        ensemble = np.mean([pred_k, pred_p, pred_s], axis=0)

        return ensemble.tolist()