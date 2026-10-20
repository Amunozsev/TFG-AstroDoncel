"""Type II kinematics: backbone fit, Newkirk shock and band-splitting physics."""

import numpy as np
import pytest

from backend import type_ii


def test_backbone_of_a_drifting_lane_recovers_the_power_law():
    times = np.arange(30, 301, 0.25)
    freqs = np.linspace(200, 45, 200)
    lane = 400 * times ** -0.3
    spectrum = np.exp(-((freqs[:, None] - lane[None, :]) / 3) ** 2) * 50
    spectrum[:, times > 250] = -1  # no emission: these instants must be skipped
    polygon = [(30, 210), (300, 210), (300, 40), (30, 40)]
    t, f = type_ii.backbone_points(spectrum, freqs, times, polygon)
    assert t.max() <= 250
    fit = type_ii.fit_power_law(t, f)
    assert fit["a"] == pytest.approx(400, rel=0.02)
    assert fit["b"] == pytest.approx(0.3, rel=0.02)


def test_shock_matches_the_desktop_analyzer_formulas():
    times = np.linspace(10, 200, 100)
    freqs = 300 * times ** -0.3
    result = type_ii.shock_parameters(times, freqs, fold=2, harmonic=True)
    # Independent check with the constants of the e-CALLISTO FITS Analyzer.
    f = freqs[0] / 2
    drift = 300 * 0.3 * times[0] ** -1.3 / 2
    log_ratio = np.log(f**2 / (2 * 3.385))
    speed = 13853221.38 * drift / (f * log_ratio**2)
    height = 4.32 * np.log(10) / log_ratio
    assert result["summary"]["start_speed_km_s"] == pytest.approx(speed, rel=2e-3)
    assert result["summary"]["start_height_rsun"] == pytest.approx(height, rel=2e-3)


def test_band_splitting_physics_by_hand():
    # X = 1.5**2: M_A = sqrt(2.25 * 7.25 / (2 * 1.75)).
    assert type_ii.alfven_mach(2.25) == pytest.approx(2.1589, rel=1e-4)
    # v_A = 1000 km/s, n = 1e8 cm^-3: B = v_A * sqrt(mu_0 m_p n) = 4.585 G.
    assert type_ii.magnetic_field_gauss(1000, 1e8) == pytest.approx(4.585, rel=1e-3)
    times = np.linspace(20, 120, 30)
    lower = 120 * times ** -0.2
    result = type_ii.band_splitting(times, 1.5 * lower, times, lower)
    assert result["summary"]["compression_ratio"]["mean"] == pytest.approx(2.25, rel=1e-3)
