"""
Драйвер ADS1115 для двух независимых датчиков.
"""

import time
import logging
from typing import Optional

import config
from utils.error_handler import (
    retry_with_backoff, circuit_breaker_adc, error_handler
)

logger = logging.getLogger(__name__)

try:
    import smbus2
except ImportError:
    smbus2 = None
    logger.warning("smbus2 not available, ADC will not work")

# Регистры ADS1115
REG_CONVERSION = 0x00
REG_CONFIG = 0x01

# Биты конфигурации
OS_SINGLE = 0x8000
MUX_SINGLE_0 = 0x4000
MODE_CONT = 0x0000
DR_860 = 0x00E0
COMP_QUE_NON = 0x0003

GAIN_MAP = {
    2/3: 0x0000,
    1: 0x0200,
    2: 0x0400,
    4: 0x0600,
    8: 0x0800,
    16: 0x0A00,
}


class ADS1115Driver:
    """Драйвер одного ADS1115."""

    def __init__(self, bus: int = config.I2C_BUS,
                 addr: int = config.ADS1115_ADDR_CH0):
        if smbus2 is None:
            raise RuntimeError("smbus2 not installed")
        self.bus_num = bus
        self.addr = addr
        self.bus: Optional[smbus2.SMBus] = None
        self._connect()

    @retry_with_backoff()
    def _connect(self):
        """Подключение к I2C с retry."""
        try:
            self.bus = smbus2.SMBus(self.bus_num)
            self._configure()
            logger.info(f"ADS1115 @ 0x{self.addr:02X} connected")
        except Exception as e:
            logger.error(f"Failed to connect to ADS1115 @ 0x{self.addr:02X}: {e}")
            raise

    def _configure(self):
        """Конфигурация ADS1115."""
        cfg = (OS_SINGLE | MUX_SINGLE_0 | GAIN_MAP[config.GAIN] |
               MODE_CONT | DR_860 | COMP_QUE_NON)
        self.bus.write_i2c_block_data(
            self.addr, REG_CONFIG,
            [(cfg >> 8) & 0xFF, cfg & 0xFF]
        )

    @error_handler(default_value=0)
    def read_raw(self) -> int:
        """Чтение сырого значения с circuit breaker."""
        def _read():
            data = self.bus.read_i2c_block_data(self.addr, REG_CONVERSION, 2)
            val = (data[0] << 8) | data[1]
            if val > 0x7FFF:
                val -= 0x10000
            return val
        return circuit_breaker_adc.call(_read)

    @error_handler(default_value=0.0)
    def read_voltage(self) -> float:
        """Чтение напряжения."""
        raw = self.read_raw()
        return raw * config.LSB_VOLTAGE

    def close(self):
        """Закрытие соединения."""
        if self.bus:
            self.bus.close()
            self.bus = None


class DualADCSystem:
    """Система из двух независимых ADS1115."""

    def __init__(self):
        self.adc_ch0 = ADS1115Driver(addr=config.ADS1115_ADDR_CH0)
        self.adc_ch1 = ADS1115Driver(addr=config.ADS1115_ADDR_CH1)
        logger.info("Dual ADC system initialized")

    def read_both(self) -> tuple:
        """Чтение обоих каналов."""
        v0 = self.adc_ch0.read_voltage()
        v1 = self.adc_ch1.read_voltage()
        return v0, v1

    def close(self):
        """Закрытие обоих ADC."""
        self.adc_ch0.close()
        self.adc_ch1.close()