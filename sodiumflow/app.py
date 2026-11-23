"""Qt dashboard for research-oriented two-channel flow analysis."""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from collections import deque
import math
import numpy as np
from PySide6 import QtCore, QtWidgets, QtGui
import pyqtgraph as pg
from .core import Settings, analyze
from .sources import Simulator, CsvReplay, SerialStream
from .storage import CsvRecorder

BG = '#0c1321'
PANEL = '#142033'
BORDER = '#253651'
TEXT = '#e9f3ff'
MUTED = '#91a4bd'
CYAN = '#42d8ec'
ORANGE = '#ffba69'
GREEN = '#59e3a1'
RED = '#ff758a'

STYLESHEET = f'''
QWidget {{ background: {BG}; color: {TEXT}; font-family: "Segoe UI", Arial; font-size: 12px; }}
QMainWindow {{ background: {BG}; }}
QFrame#panel, QGroupBox {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; }}
QGroupBox {{ margin-top: 12px; padding: 16px 12px 12px 12px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 15px; padding: 0 8px; color: {MUTED}; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#metric {{ color: {TEXT}; font-size: 27px; font-weight: 700; }}
QPushButton {{ background: #203450; border: 1px solid #34506d; border-radius: 8px; padding: 8px 14px; font-weight: 600; }}
QPushButton:hover {{ background: #2c4566; }}
QPushButton:disabled {{ color: #67788d; background: #152438; }}
QPushButton#primary {{ background: #0c829b; color: white; border-color: #1db0c4; }}
QPushButton#primary:hover {{ background: #119cb4; }}
QComboBox,QDoubleSpinBox,QSpinBox,QLineEdit {{ background: #0f1b2c; border: 1px solid #38506a; border-radius: 6px; padding: 5px; min-height: 22px; }}
QStatusBar {{ color: {MUTED}; border-top: 1px solid {BORDER}; }}
'''


def make_plot(label, ylabel):
    plot = pg.PlotWidget()
    plot.setBackground(PANEL)
    plot.setTitle(label, color=TEXT, size='11pt')
    plot.showGrid(x=True, y=True, alpha=0.15)
    plot.setLabel('left', ylabel, color=MUTED)
    plot.getAxis('bottom').setTextPen(MUTED)
    plot.getAxis('left').setTextPen(MUTED)
    plot.getPlotItem().getViewBox().setMouseEnabled(x=True, y=True)
    return plot


class Metric(QtWidgets.QFrame):
    def __init__(self, title, unit):
        super().__init__()
        self.setObjectName('panel')
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(18, 13, 18, 13)
        name = QtWidgets.QLabel(title.upper())
        name.setObjectName('muted')
        self.value = QtWidgets.QLabel('—')
        self.value.setObjectName('metric')
        hint = QtWidgets.QLabel(unit)
        hint.setObjectName('muted')
        lay.addWidget(name)
        lay.addWidget(self.value)
        lay.addWidget(hint)
    def set(self, value, color=TEXT):
        self.value.setText(value)
        self.value.setStyleSheet(f'color:{color}')


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('SodiumFlow Next  |  Анализ двухканального расходомера')
        self.resize(1500, 950)
        self.cfg = Settings()
        self.source = None
        self.recorder = None
        self.running = False
        self.t = deque(maxlen=int(self.cfg.sample_rate*30))
        self.x = deque(maxlen=int(self.cfg.sample_rate*30))
        self.y = deque(maxlen=int(self.cfg.sample_rate*30))
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self._setup_ui()
        self.apply_config()
        self.statusBar().showMessage('Готово • начните с режима «Симуляция»')

    def _setup_ui(self):
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        outer = QtWidgets.QVBoxLayout(root)
        outer.setContentsMargins(20, 20, 20, 12)
        outer.setSpacing(16)
        top = QtWidgets.QHBoxLayout()
        headings = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel('SODIUMFLOW  <span style="color:#42d8ec">NEXT</span>')
        title.setTextFormat(QtCore.Qt.RichText)
        title.setStyleSheet('font-size:26px;font-weight:750;letter-spacing:1px')
        subtitle = QtWidgets.QLabel('Двухканальный анализ сигналов • Исследовательская версия 1.0')
        subtitle.setObjectName('muted')
        headings.addWidget(title)
        headings.addWidget(subtitle)
        top.addLayout(headings)
        top.addStretch()
        self.state = QtWidgets.QLabel('●  ОСТАНОВЛЕНО')
        self.state.setStyleSheet(f'font-size:13px;font-weight:700;color:{MUTED}')
        top.addWidget(self.state)
        outer.addLayout(top)

        metrics = QtWidgets.QHBoxLayout()
        self.m_v = Metric('Скорость потока', 'м/с')
        self.m_q = Metric('Объёмный расход', 'м³/ч • оценка')
        self.m_lag = Metric('Задержка', 'мс')
        self.m_conf = Metric('Корреляция', 'коэффициент Пирсона')
        for w in (self.m_v, self.m_q, self.m_lag, self.m_conf):
            metrics.addWidget(w, 1)
        outer.addLayout(metrics)

        content = QtWidgets.QHBoxLayout()
        content.setSpacing(16)
        plots = QtWidgets.QVBoxLayout()
        plots.setSpacing(14)
        self.signal_plot = make_plot('Сигналы датчиков — последние отсчёты', 'В')
        self.signal_plot.setLabel('bottom', 'Время', units='s')
        self.p1 = self.signal_plot.plot(pen=pg.mkPen(CYAN, width=1.4), name='CH1')
        self.p2 = self.signal_plot.plot(pen=pg.mkPen(ORANGE, width=1.4), name='CH2')
        self.signal_plot.addLegend(offset=(14, 6))
        self.corr_plot = make_plot('Кросс-корреляция — положительные задержки', 'ρ*')
        self.corr_plot.setLabel('bottom', 'Задержка', units='ms')
        self.pc = self.corr_plot.plot(pen=pg.mkPen(GREEN, width=2))
        self.spectrum_plot = make_plot('Амплитудный спектр первого канала', 'амплитуда')
        self.spectrum_plot.setLabel('bottom', 'Частота', units='Hz')
        self.ps = self.spectrum_plot.plot(pen=pg.mkPen(ORANGE, width=1.6))
        for w in (self.signal_plot, self.corr_plot, self.spectrum_plot):
            w.setMinimumHeight(165)
            plots.addWidget(w, 1)
        content.addLayout(plots, 4)

        side = QtWidgets.QScrollArea()
        side.setWidgetResizable(True)
        side.setFrameShape(QtWidgets.QFrame.NoFrame)
        side.setMinimumWidth(325)
        side.setMaximumWidth(390)
        side_content = QtWidgets.QWidget()
        side_l = QtWidgets.QVBoxLayout(side_content)
        side_l.setContentsMargins(2, 0, 2, 0)
        side_l.setSpacing(13)
        side.setWidget(side_content)
        content.addWidget(side, 1)
        outer.addLayout(content, 1)

        source_box = QtWidgets.QGroupBox('Источник данных')
        src_form = QtWidgets.QFormLayout(source_box)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(['Симуляция', 'CSV-файл', 'Serial / внешний мост'])
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.port = QtWidgets.QLineEdit('COM3')
        self.pick = QtWidgets.QPushButton('Выбрать CSV…')
        self.pick.clicked.connect(self.select_csv)
        self.csv_path = ''
        self.sim_speed = self.spin(2.4, .2, 8, .1, 2)
        src_form.addRow('Режим', self.mode)
        src_form.addRow('Скорость симуляции, м/с', self.sim_speed)
        src_form.addRow('CSV', self.pick)
        src_form.addRow('Порт (230400 бод)', self.port)
        side_l.addWidget(source_box)

        cfg_box = QtWidgets.QGroupBox('Параметры измерений')
        form = QtWidgets.QFormLayout(cfg_box)
        self.fs = self.spin(860, 20, 100000, 10, 0)
        self.distance = self.spin(150, .1, 10000, 5, 1)
        self.diameter = self.spin(30, .1, 2000, 1, 1)
        self.low = self.spin(3, .1, 10000, 1, 1)
        self.high = self.spin(250, .2, 40000, 5, 1)
        self.minv = self.spin(.2, .01, 100, .1, 2)
        self.maxv = self.spin(8, .02, 200, .5, 2)
        self.threshold = self.spin(.45, .01, 1, .05, 2)
        self.win = self.spin(3, .4, 30, .5, 1)
        self.factor = self.spin(1, .01, 100, .01, 3)
        for label, w in [('Частота, Гц',self.fs),('Расстояние, мм',self.distance),('Диаметр трубы, мм',self.diameter),('Фильтр от, Гц',self.low),('Фильтр до, Гц',self.high),('Мин. скорость, м/с',self.minv),('Макс. скорость, м/с',self.maxv),('Порог корреляции',self.threshold),('Окно, с',self.win),('Коэф. калибровки',self.factor)]:
            form.addRow(label, w)
        side_l.addWidget(cfg_box)
        buttons = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton('▶  Запустить')
        self.start_btn.setObjectName('primary')
        self.start_btn.clicked.connect(self.toggle)
        self.record_btn = QtWidgets.QPushButton('●  Запись CSV')
        self.record_btn.clicked.connect(self.toggle_record)
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.record_btn)
        side_l.addLayout(buttons)
        self.diagnostic = QtWidgets.QLabel('Ожидание данных')
        self.diagnostic.setWordWrap(True)
        self.diagnostic.setStyleSheet(f'color:{MUTED};padding:10px')
        side_l.addWidget(self.diagnostic)
        side_l.addStretch()
        self.mode_changed()

    @staticmethod
    def spin(value, minimum, maximum, step, decimals):
        widget = QtWidgets.QDoubleSpinBox()
        widget.setDecimals(decimals)
        widget.setRange(minimum, maximum)
        widget.setSingleStep(step)
        widget.setValue(value)
        return widget

    def mode_changed(self):
        mode = self.mode.currentIndex()
        self.sim_speed.setEnabled(mode == 0)
        self.pick.setEnabled(mode == 1)
        self.port.setEnabled(mode == 2)

    def select_csv(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Открыть сигналы', '', 'CSV (*.csv)')
        if path:
            self.csv_path = path
            self.pick.setText(Path(path).name[:24])

    def apply_config(self):
        cfg = Settings(sample_rate=self.fs.value(), sensor_spacing_m=self.distance.value()/1000,
                       pipe_diameter_mm=self.diameter.value(), lowcut_hz=self.low.value(),
                       highcut_hz=self.high.value(), min_velocity_m_s=self.minv.value(),
                       max_velocity_m_s=self.maxv.value(), min_correlation=self.threshold.value(),
                       window_seconds=self.win.value(), calibration_factor=self.factor.value())
        cfg.validate()
        self.cfg = cfg
        maximum = int(cfg.sample_rate * 30)
        self.t = deque(maxlen=maximum)
        self.x = deque(maxlen=maximum)
        self.y = deque(maxlen=maximum)

    def toggle(self):
        if self.running:
            self.stop()
            return
        try:
            self.apply_config()
            if self.mode.currentIndex() == 0:
                self.source = Simulator(self.cfg.sample_rate, self.cfg.sensor_spacing_m, self.sim_speed.value())
            elif self.mode.currentIndex() == 1:
                if not self.csv_path:
                    raise ValueError('Сначала выберите CSV-файл')
                self.source = CsvReplay(self.csv_path, self.cfg.sample_rate)
            else:
                self.source = SerialStream(self.port.text().strip())
            self.running = True
            self.timer.start()
            self.state.setText('●  СБОР ДАННЫХ')
            self.state.setStyleSheet(f'font-size:13px;font-weight:700;color:{GREEN}')
            self.start_btn.setText('■  Остановить')
            self.mode.setEnabled(False)
            self.statusBar().showMessage('Источник запущен')
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, 'Ошибка запуска', str(error))

    def stop(self):
        self.timer.stop()
        self.running = False
        if self.source is not None and hasattr(self.source, 'close'):
            self.source.close()
        self.source = None
        self.state.setText('●  ОСТАНОВЛЕНО')
        self.state.setStyleSheet(f'font-size:13px;font-weight:700;color:{MUTED}')
        self.start_btn.setText('▶  Запустить')
        self.mode.setEnabled(True)
        self.statusBar().showMessage('Измерение остановлено')

    def toggle_record(self):
        if self.recorder is not None:
            self.recorder.close()
            self.recorder = None
            self.record_btn.setText('●  Запись CSV')
            self.statusBar().showMessage('CSV сохранён')
            return
        file, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'Сохранить поток измерений', f'sodiumflow_{datetime.now():%Y%m%d_%H%M%S}.csv', 'CSV (*.csv)')
        if file:
            try:
                self.recorder = CsvRecorder(file)
                self.record_btn.setText('■  Закончить запись')
            except OSError as err:
                QtWidgets.QMessageBox.warning(self, 'Запись не началась', str(err))

    def tick(self):
        try:
            count = max(1, round(self.cfg.sample_rate*.1))
            t, x, y = self.source.read(count)
            if not len(t):
                return
            if len(t) != len(x) or len(t) != len(y):
                raise ValueError('Источник вернул несинхронные массивы')
            if self.t and t[0] <= self.t[-1]:
                raise ValueError('Не монотонные временные метки источника')
            if len(t) > 1 and np.max(np.abs(np.diff(t) - 1/self.cfg.sample_rate)) > .02/self.cfg.sample_rate:
                raise ValueError('Нестабильная частота источника — анализ остановлен')
            self.t.extend(t)
            self.x.extend(x)
            self.y.extend(y)
            if self.recorder:
                self.recorder.write(t, x, y)
            n = int(self.cfg.window_seconds * self.cfg.sample_rate)
            if len(self.x) < max(64, n):
                self.diagnostic.setText(f'Накопление данных: {len(self.x)}/{n} отсчётов')
                return
            tt = np.asarray(self.t)[-n:]
            xx = np.asarray(self.x)[-n:]
            yy = np.asarray(self.y)[-n:]
            self.p1.setData(tt, xx)
            self.p2.setData(tt, yy)
            result = analyze(xx, yy, self.cfg)
            pos = (result.lags_s >= 0) & (result.lags_s <= self.cfg.sensor_spacing_m/self.cfg.min_velocity_m_s)
            self.pc.setData(result.lags_s[pos]*1000, result.correlations[pos])
            self.ps.setData(result.frequencies_hz, result.spectrum_ch1)
            if result.valid:
                self.m_v.set(f'{result.velocity_m_s:.3f}', GREEN)
                self.m_q.set(f'{result.flow_m3_h:.3f}', GREEN)
                self.m_lag.set(f'{result.lag_s*1000:.2f}', TEXT)
                self.m_conf.set(f'{result.coefficient:.3f}', GREEN)
                self.diagnostic.setText(f'✓ Корреляция подтверждена\nSNR пика: {result.snr:.2f}\nσ1: {result.sigma_ch1:.4f} В\nσ2: {result.sigma_ch2:.4f} В')
            else:
                self.m_v.set('Н/Д', RED)
                self.m_q.set('Н/Д', RED)
                self.m_lag.set('Н/Д', RED)
                self.m_conf.set(f'{result.coefficient:.3f}', ORANGE)
                self.diagnostic.setText('⚠ ' + result.reason)
        except EOFError as e:
            self.stop()
            self.diagnostic.setText(str(e))
        except Exception as e:
            self.stop()
            QtWidgets.QMessageBox.warning(self, 'Ошибка измерения', str(e))

    def closeEvent(self, event):
        if self.running:
            self.stop()
        if self.recorder:
            self.recorder.close()
            self.recorder = None
        super().closeEvent(event)


def main():
    app = QtWidgets.QApplication([])
    app.setApplicationName('SodiumFlow Next')
    app.setStyle('Fusion')
    app.setStyleSheet(STYLESHEET)
    pg.setConfigOptions(antialias=True)
    window = MainWindow()
    window.show()
    app.exec()
