import numpy as np
import pytest
from sodiumflow.core import Settings, analyze
from sodiumflow.sources import Simulator, CsvReplay
from sodiumflow.storage import CsvRecorder


def test_known_delay():
    cfg = Settings()
    src = Simulator(fs=cfg.sample_rate, spacing=cfg.sensor_spacing_m, velocity=2.4, seed=9)
    _, x, y = src.read(int(cfg.sample_rate * 5))
    result = analyze(x, y, cfg)
    assert result.valid, result.reason
    assert result.velocity_m_s == pytest.approx(2.4, rel=0.08)
    assert result.flow_m3_h == pytest.approx(2.4 * np.pi*(.03/2)**2*3600, rel=.08)
    assert result.coefficient > 0.65


def test_constant_signals_rejected():
    cfg = Settings()
    r = analyze(np.ones(1000), np.ones(1000), cfg)
    assert not r.valid
    assert r.velocity_m_s is None


def test_wrong_filter_rejected():
    with pytest.raises(ValueError, match='Найквиста'):
        Settings(highcut_hz=500).validate()


def test_negative_delay_not_accepted_as_forward_velocity():
    cfg = Settings(min_correlation=.8)
    rng = np.random.default_rng(5)
    x = rng.normal(size=4000)
    y = np.r_[x[60:], np.zeros(60)]
    r = analyze(x, y, cfg)
    assert not r.valid


def test_csv_roundtrip(tmp_path):
    p = tmp_path / 'data.csv'
    fs = 100.0
    t = np.arange(250) / fs
    with_rec = CsvRecorder(p)
    with_rec.write(t, t*2, t*3)
    with_rec.close()
    replay = CsvReplay(str(p), fs)
    a,b,c = replay.read(80)
    assert len(a) == 80
    assert np.allclose(b, a*2)
    assert np.allclose(c, a*3)
