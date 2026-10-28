"""
Калибровочная кривая: СКО → расход.
"""

import numpy as np
import logging

import config

logger = logging.getLogger(__name__)


def std_to_flow(sigma: float) -> float:
    """
    Калибровка: σ → Q.
    Q = 1.2*σ² + 2.1*σ + 5.0
    """
    Q = np.polyval(config.CALIBRATION_POLY, sigma)
    return max(float(Q), 0.0)