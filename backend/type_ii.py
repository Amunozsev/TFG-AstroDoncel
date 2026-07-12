"""Experimental Type-II band-splitting calculations ported from Sahan's analyzer."""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import curve_fit

MU_0 = 4.0 * math.pi * 1e-7
PROTON_MASS_KG = 1.67262192369e-27
PLASMA_FREQ_COEFF_MHZ = 0.00898


def _power_law(time_s, amplitude, exponent):
    return amplitude * np.power(time_s, -exponent)


def _fit(times, frequencies):
    x = np.asarray(times, dtype=float)
    y = np.asarray(frequencies, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y) & (x > 0) & (y > 0)
    if mask.sum() < 3:
        raise ValueError("Each band needs at least three positive points")
    slope, intercept = np.polyfit(np.log(x[mask]), np.log(y[mask]), 1)
    params, _ = curve_fit(
        _power_law, x[mask], y[mask], p0=(math.exp(intercept), max(1e-6, -slope)),
        bounds=([1e-12, 1e-9], [np.inf, np.inf]), maxfev=10000,
    )
    return float(params[0]), abs(float(params[1])), x[mask]


def calculate(upper_times, upper_freqs, lower_times, lower_freqs, analysis_frequency_mhz, shock_speed_km_s):
    upper_a, upper_b, upper_x = _fit(upper_times, upper_freqs)
    lower_a, lower_b, lower_x = _fit(lower_times, lower_freqs)
    start, end = max(upper_x.min(), lower_x.min()), min(upper_x.max(), lower_x.max())
    if end <= start:
        raise ValueError("Upper and lower bands do not overlap in time")
    samples = np.linspace(start, end, 128)
    upper = _power_law(samples, upper_a, upper_b)
    lower = _power_law(samples, lower_a, lower_b)
    if np.any(upper <= lower):
        raise ValueError("Upper-band frequencies must remain above lower-band frequencies")
    compression = float((np.mean(upper) / np.mean(lower)) ** 2)
    if not 1.0 < compression < 4.0:
        raise ValueError("Derived compression ratio must be between 1 and 4")
    mach = math.sqrt((compression * (compression + 5.0)) / (2.0 * (4.0 - compression)))
    alfven_speed = float(shock_speed_km_s) / mach
    density = (float(analysis_frequency_mhz) / PLASMA_FREQ_COEFF_MHZ) ** 2
    magnetic_tesla = alfven_speed * 1000.0 * math.sqrt(MU_0 * PROTON_MASS_KG * density * 1e6)
    drift = -upper_a * upper_b * np.power(samples, -upper_b - 1.0)
    return {
        "compression_ratio": compression,
        "alfven_mach_number": mach,
        "alfven_speed_km_s": alfven_speed,
        "electron_density_cm3": density,
        "magnetic_field_g": magnetic_tesla * 1e4,
        "bandwidth_mhz": float(np.mean(upper - lower)),
        "upper_avg_drift_mhz_s": float(np.mean(drift)),
        "fit": {"upper": {"a": upper_a, "b": upper_b}, "lower": {"a": lower_a, "b": lower_b}},
        "warning": "Experimental result; validate band picks and assumptions before scientific use.",
    }
