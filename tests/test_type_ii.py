"""Type II kinematics: backbone fit, Newkirk shock and band-splitting physics."""

import numpy as np
import pytest

from backend import type_ii


def test_backbone_follows_a_drifting_lane():
    times = np.arange(30, 301, 0.25)
    freqs = np.linspace(200, 45, 200)
    lane = 400 * times ** -0.3
    spectrum = np.exp(-((freqs[:, None] - lane[None, :]) / 3) ** 2) * 50
    spectrum[:, times > 250] = -1  # no emission: these instants must be skipped
    polygon = [(30, 210), (300, 210), (300, 40), (30, 40)]
    t, f = type_ii.backbone_points(spectrum, freqs, times, polygon)
    assert t.max() <= 250
    assert np.abs(f - 400 * t ** -0.3).max() < 1.0


def test_shock_speed_from_newkirk_heights_ignores_the_time_origin():
    # A shock at 800 km/s from 1.3 R_sun, seen in harmonic emission with fold 2.
    times = np.linspace(10, 200, 100)
    heights = 1.3 + 800 / type_ii.R_SUN_KM * times
    freqs = 2 * np.sqrt(2 * 8.98e-3**2 * 4.2e4 * 10 ** (4.32 / heights))
    result = type_ii.shock_parameters(times, freqs, fold=2, harmonic=True)
    shifted = type_ii.shock_parameters(times + 900, freqs, fold=2, harmonic=True)
    assert result["summary"]["speed_km_s"] == pytest.approx(800, rel=1e-6)
    assert result["summary"]["start_height_rsun"] == pytest.approx(heights[0], rel=1e-6)
    assert shifted["summary"]["speed_km_s"] == pytest.approx(800, rel=1e-6)


def test_band_splitting_physics_by_hand():
    # X = 1.5**2: M_A = sqrt(2.25 * 7.25 / (2 * 1.75)).
    assert type_ii.alfven_mach(2.25) == pytest.approx(2.1589, rel=1e-4)
    # v_A = 1000 km/s, n = 1e8 cm^-3: B = v_A * sqrt(mu_0 m_p n) = 4.585 G.
    assert type_ii.magnetic_field_gauss(1000, 1e8) == pytest.approx(4.585, rel=1e-3)
    times = np.linspace(20, 120, 30)
    lower = 120 - 0.3 * times
    result = type_ii.band_splitting(times, 1.5 * lower, times, lower)
    assert result["summary"]["compression_ratio"]["mean"] == pytest.approx(2.25, rel=1e-3)
