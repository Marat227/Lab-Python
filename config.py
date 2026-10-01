# Файл конфигурации расходомера. Указаны физические, аппаратные и математические параметры

  # Расстояние между двумя датчиками константа, 15 см.
SENSOR_DISTANCE_M = 0.15

  # Калибровочный полином: Q = a*σ² + b*σ + c
  # Q — расход (условные единицы или м³/ч после калибровки)
  # σ — среднеквадратичное отклонение сигнала
CALIBRATION_POLY = [1.2, 2.1, 5.0]  # коэффициенты подобраны опытным путем через эксперименты
  #Настройка АЦП ADS
I2C_BUS = 1
ADS1115_ADDR_CH0 = 0x48  # Первый датчик
ADS1115_ADDR_CH1 = 0x49  # Второй датчик

GAIN = 2/3               # Делитель из документации для пределов измерения в ±6.144V
FS_VOLTAGE = 6.144       # Полная шкала измерения
RESOLUTION = 16          #Разрешение(Пропускная способность АЦП)
LSB_VOLTAGE = FS_VOLTAGE / (2**(RESOLUTION - 1))  # ~187.5 мкВ, расчет вольтажа

  # Частоты
ADC_REAL_SPS = 860       # Реальная скорость ADS1115 из документации. 860 выборок в секунду
TARGET_SPS = 10000       # Целевая эффективная частота для определения расхода
PREDICTION_RATIO = TARGET_SPS // ADC_REAL_SPS  # Предсказания
  # Параметры мат обработки
CORRELATION_WINDOW = 4096   # Точек в окне корреляции
RMS_WINDOW = 1024           # Точек для СКО
UPDATE_INTERVAL_MS = 100    # Обновление GUI, мс
  # Параметры фильтрации сигнала
  # Полосовой фильтр (Гц)
BANDPASS_LOW = 10.0 #Нижняя граница
BANDPASS_HIGH = 2000.0 #Верхняя граница
BUTTERWORTH_ORDER = 4

  # Обнаружение выбросов
OUTLIER_IQR_MULTIPLIER = 1.5
OUTLIER_ZSCORE_THRESHOLD = 3.5

  # Валидация спектра
SPECTRAL_PEAK_MIN_RATIO = 3.0  # Пик должен быть в N раз выше шума
SPECTRAL_NOISE_FLOOR_PERCENTILE = 10

  # Валидация корреляции
CORRELATION_MIN_PEAK = 0.3       # Минимальная высота пика
CORRELATION_MIN_SHARPNESS = 2.0  # Минимальная острота пика
CORRELATION_MIN_SNR = 5.0        # Минимальное SNR

  # Временная согласованность
TEMPORAL_WINDOW_SIZE = 10        # Размер окна для проверки
TEMPORAL_MAX_DEVIATION = 0.3     # Макс. отклонение скорости (30%)

  # Система принятия решений
DECISION_CONFIDENCE_THRESHOLD = 0.7  # Порог принятия решения
DECISION_WEIGHTS = {
    'bandpass': 0.15,
    'outlier': 0.15,
    'spectral': 0.20,
    'correlation': 0.30,
    'temporal': 0.20,
}
  # Логирование

LOG_FILE = '.measurement_log.json'
LOG_MAX_SIZE_MB = 100
LOG_ROTATION_COUNT = 5
LOG_ASYNC_QUEUE_SIZE = 1000
  # Error handler

RETRY_MAX_ATTEMPTS = 3
RETRY_BASE_DELAY_S = 0.1
RETRY_MAX_DELAY_S = 5.0
CIRCUIT_BREAKER_THRESHOLD = 5
CIRCUIT_BREAKER_TIMEOUT_S = 10.0