"""
Продвинутая обработка ошибок: retry, circuit breaker, graceful degradation.
"""

import time
import functools
import logging
from typing import Callable, Any, Optional
from threading import Lock
from enum import Enum

import config

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"        # Нормальная работа
    OPEN = "open"            # Ошибки, не пропускаем вызовы
    HALF_OPEN = "half_open"  # Пробуем восстановить


class CircuitBreaker:
    """
    Circuit Breaker pattern.
    После N ошибок — блокирует вызовы на timeout, потом пробует снова.
    """

    def __init__(self, threshold=config.CIRCUIT_BREAKER_THRESHOLD,
                 timeout=config.CIRCUIT_BREAKER_TIMEOUT_S):
        self.threshold = threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = CircuitState.CLOSED
        self._lock = Lock()

    def call(self, func: Callable, *args, **kwargs) -> Any:
        with self._lock:
            if self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_time > self.timeout:
                    self.state = CircuitState.HALF_OPEN
                    logger.info("Circuit breaker: HALF_OPEN, trying...")
                else:
                    raise CircuitBreakerOpenError(
                        f"Circuit is OPEN, {self.timeout}s timeout not elapsed"
                    )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        with self._lock:
            self.failure_count = 0
            self.state = CircuitState.CLOSED

    def _on_failure(self):
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.threshold:
                self.state = CircuitState.OPEN
                logger.error(
                    f"Circuit breaker: OPEN after {self.failure_count} failures"
                )


class CircuitBreakerOpenError(Exception):
    """Circuit breaker открыт, вызов заблокирован."""
    pass


def retry_with_backoff(max_attempts=config.RETRY_MAX_ATTEMPTS,
                       base_delay=config.RETRY_BASE_DELAY_S,
                       max_delay=config.RETRY_MAX_DELAY_S,
                       exceptions=(Exception,)):
    """
    Декоратор retry с экспоненциальной задержкой.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt+1}/"
                            f"{max_attempts}): {e}. Retrying in {delay:.2f}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {e}"
                        )
            raise last_exception
        return wrapper
    return decorator


def error_handler(default_value=None, log_exceptions=True):
    """
    Декоратор: ловит исключения, логирует, возвращает default_value.
    Graceful degradation.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if log_exceptions:
                    logger.exception(f"Error in {func.__name__}: {e}")
                return default_value
        return wrapper
    return decorator


class GracefulDegradation:
    """
    Управление режимами работы при деградации.
    """

    def __init__(self):
        self.mode = "full"  # full, degraded, minimal, offline
        self._lock = Lock()

    def set_mode(self, mode: str):
        with self._lock:
            if mode in ("full", "degraded", "minimal", "offline"):
                self.mode = mode
                logger.warning(f"Degradation mode changed to: {mode}")

    def get_mode(self) -> str:
        with self._lock:
            return self.mode

    def is_operational(self) -> bool:
        return self.get_mode() != "offline"


# Глобальные экземпляры
circuit_breaker_adc = CircuitBreaker()
degradation = GracefulDegradation()