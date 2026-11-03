"""Type II radio burst kinematics: Newkirk shock speed and band-splitting.

* plasma frequency  f_p [MHz] = 8.98e-3 * sqrt(n_e [cm^-3]);
* Newkirk (1961) corona multiplied by a fold factor n:
  n_e(R) = n * 4.2e4 * 10**(4.32 / R), with R in solar radii, so
  R = 4.32 / log10(f_p**2 / (n * 8.98e-3**2 * 4.2e4));
* every backbone point becomes a height R(t) and a straight line fitted to
  R(t) gives the shock speed: the slope does not depend on where the time
  axis starts, so one block or two joined blocks give the same speed;
* band-splitting: compression X = (f_upper / f_lower)**2, Alfvén Mach number
  of a perpendicular shock in a low-beta plasma
  M_A = sqrt(X (X + 5) / (2 (4 - X)))  (Vršnak et al. 2002), Alfvén speed
  v_A = v / M_A and B = v_A * sqrt(mu_0 * m_p * n_e) with the upstream
  (lower band) density.

Times are seconds since the start of the loaded observation. Newkirk heights
and everything derived from them are model-dependent estimates;
band-splitting results are experimental.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import linregress

R_SUN_KM = 695_700.0  # IAU 2015 nominal solar radius
PLASMA_FREQ_COEFF_MHZ = 8.98e-3
NEWKIRK_N0_CM3 = 4.2e4
NEWKIRK_EXPONENT = 4.32
MU_0 = 4e-7 * math.pi
PROTON_MASS_KG = 1.67262192e-27
_NEWKIRK_F2_MHZ2 = PLASMA_FREQ_COEFF_MHZ**2 * NEWKIRK_N0_CM3  # f_p**2 at 10**0 density
_BAND_SAMPLES = 50


def _points(times_s, freqs_mhz) -> tuple[np.ndarray, np.ndarray]:
    t = np.asarray(times_s, dtype=float).ravel()
    f = np.asarray(freqs_mhz, dtype=float).ravel()
    if t.shape != f.shape:
        raise ValueError("Times and frequencies must have the same length.")
    keep = np.isfinite(t) & np.isfinite(f) & (f > 0)
    if np.count_nonzero(keep) < 3:
        raise ValueError("At least three points with frequency > 0 MHz are needed.")
    order = np.argsort(t[keep])
    return t[keep][order], f[keep][order]


def backbone_points(data, freqs_mhz, times_s, polygon) -> tuple[np.ndarray, np.ndarray]:
    """Frequency of maximum intensity at each time inside a polygon.

    ``data`` is the background-subtracted spectrum (frequency, time) and
    ``polygon`` a list of (time_s, freq_mhz) vertices. A column is kept only
    when its maximum exceeds the background by three times the noise, estimated
    robustly over the whole observation (1.4826 * median absolute deviation),
    so instants without burst emission do not enter the fit.
    """
    data = np.asarray(data, dtype=float)
    freqs = np.asarray(freqs_mhz, dtype=float)
    times = np.asarray(times_s, dtype=float)
    vertices = np.asarray(polygon, dtype=float)
    if vertices.ndim != 2 or vertices.shape[0] < 3 or vertices.shape[1] != 2:
        raise ValueError("The burst region needs at least three (time, frequency) vertices.")
    columns = np.flatnonzero((times >= vertices[:, 0].min()) & (times <= vertices[:, 0].max()))
    rows = np.flatnonzero((freqs >= vertices[:, 1].min()) & (freqs <= vertices[:, 1].max()))
    if columns.size == 0 or rows.size == 0:
        raise ValueError("The burst region does not cover any sample of this observation.")
    inside = _inside_polygon(times[columns][None, :], freqs[rows][:, None], vertices)
    region = np.where(inside, data[np.ix_(rows, columns)], -np.inf)
    region[~np.isfinite(region)] = -np.inf
    peak_rows = np.argmax(region, axis=0)
    peaks = region[peak_rows, np.arange(columns.size)]
    finite = data[np.isfinite(data)]
    noise = 1.4826 * np.median(np.abs(finite - np.median(finite)))
    keep = peaks > np.median(finite) + 3 * noise
    return times[columns][keep], freqs[rows][peak_rows[keep]]


def _inside_polygon(x, y, vertices) -> np.ndarray:
    """Even-odd ray casting on broadcast arrays of x and y."""
    inside = np.zeros(np.broadcast(x, y).shape, dtype=bool)
    x0, y0 = vertices[-1]
    for x1, y1 in vertices:
        if y0 != y1:
            crosses = (y1 > y) != (y0 > y)
            x_cross = x1 + (y - y1) * (x0 - x1) / (y0 - y1)
            inside ^= crosses & (x < x_cross)
        x0, y0 = x1, y1
    return inside


def newkirk_height(freq_mhz, fold: int) -> np.ndarray:
    """Heliocentric height in solar radii where f is the local plasma frequency."""
    ratio = np.square(np.asarray(freq_mhz, dtype=float)) / (fold * _NEWKIRK_F2_MHZ2)
    if np.any(ratio <= 1):
        raise ValueError("Frequency is below the Newkirk model cutoff.")
    return NEWKIRK_EXPONENT / np.log10(ratio)


def fit_height_time(times_s, freqs_mhz, fold: int = 1, harmonic: bool = False) -> dict:
    """Straight line R(t) = R0 + v t through the Newkirk heights of the points.

    For harmonic emission the observed frequency is halved first, since the
    density model applies to the fundamental plasma frequency.
    """
    if fold not in (1, 2, 3, 4):
        raise ValueError("The Newkirk fold must be 1, 2, 3 or 4.")
    t, observed = _points(times_s, freqs_mhz)
    harmonic_number = 2 if harmonic else 1
    line = linregress(t, newkirk_height(observed / harmonic_number, fold))
    if line.slope <= 0:
        raise ValueError("The points must drift to lower frequencies (an outward shock).")
    fit = {
        "fold": fold, "harmonic": harmonic,
        "height0_rsun": float(line.intercept), "speed_rsun_s": float(line.slope),
        "speed_km_s": float(line.slope) * R_SUN_KM, "speed_err_km_s": float(line.stderr) * R_SUN_KM,
        "r2": float(line.rvalue**2), "points": int(t.size), "t_start_s": float(t[0]), "t_end_s": float(t[-1]),
    }
    fit["rmse_mhz"] = float(np.sqrt(np.mean((observed - fitted_frequency(t, fit)) ** 2)))
    return fit


def fitted_height(t, fit: dict) -> np.ndarray:
    return fit["height0_rsun"] + fit["speed_rsun_s"] * np.asarray(t, dtype=float)


def fitted_frequency(t, fit: dict) -> np.ndarray:
    """Observed frequency (MHz) of the fitted line, inverting the Newkirk model."""
    fundamental = np.sqrt(fit["fold"] * _NEWKIRK_F2_MHZ2 * np.power(10.0, NEWKIRK_EXPONENT / fitted_height(t, fit)))
    return fundamental * (2 if fit["harmonic"] else 1)


def _fitted_drift(t, fit: dict) -> np.ndarray:
    """df/dt in MHz/s of the fitted line: (df/dR) * v."""
    height = fitted_height(t, fit)
    return -fitted_frequency(t, fit) * NEWKIRK_EXPONENT * math.log(10) / (2 * height**2) * fit["speed_rsun_s"]


def shock_parameters(times_s, freqs_mhz, fold: int = 1, harmonic: bool = False) -> dict:
    """Shock speed from the height-time line and the fitted curve for the plot."""
    fit = fit_height_time(times_s, freqs_mhz, fold, harmonic)
    t, _ = _points(times_s, freqs_mhz)
    ends = np.array([t[0], t[-1]])
    height, freq, drift = fitted_height(ends, fit), fitted_frequency(ends, fit), _fitted_drift(ends, fit)
    return {
        "fit": fit,
        "fold": fold,
        "harmonic": harmonic,
        "curve": {
            "time_s": t.tolist(),
            "fit_freq_mhz": fitted_frequency(t, fit).tolist(),
            "height_rsun": fitted_height(t, fit).tolist(),
        },
        "summary": {
            "speed_km_s": fit["speed_km_s"], "speed_err_km_s": fit["speed_err_km_s"],
            "start_freq_mhz": float(freq[0]), "end_freq_mhz": float(freq[1]),
            "start_drift_mhz_s": float(drift[0]), "end_drift_mhz_s": float(drift[1]),
            "start_height_rsun": float(height[0]), "end_height_rsun": float(height[1]),
        },
    }


def alfven_mach(compression) -> np.ndarray:
    """Alfvén Mach number of a perpendicular low-beta shock (Vršnak et al. 2002)."""
    x = np.asarray(compression, dtype=float)
    if np.any((x <= 1) | (x >= 4)):
        raise ValueError("The band ratio gives a compression outside 1 < X < 4.")
    return np.sqrt(x * (x + 5) / (2 * (4 - x)))


def magnetic_field_gauss(alfven_speed_km_s, density_cm3) -> np.ndarray:
    """B = v_A * sqrt(mu_0 * m_p * n) for a proton-electron plasma."""
    density_m3 = np.asarray(density_cm3, dtype=float) * 1e6
    return np.asarray(alfven_speed_km_s, dtype=float) * 1e3 * np.sqrt(MU_0 * PROTON_MASS_KG * density_m3) * 1e4


def band_splitting(upper_s, upper_mhz, lower_s, lower_mhz, fold: int = 1, harmonic: bool = False) -> dict:
    """Shock compression, Alfvén speed and magnetic field from split type II lanes.

    The upper lane is emitted downstream and the lower lane upstream of the
    shock, so the shock speed and the density for B come from the lower lane.
    Both fits are only compared where their time ranges overlap.
    """
    upper_fit = fit_height_time(upper_s, upper_mhz, fold, harmonic)
    lower_fit = fit_height_time(lower_s, lower_mhz, fold, harmonic)
    start = max(upper_fit["t_start_s"], lower_fit["t_start_s"])
    end = min(upper_fit["t_end_s"], lower_fit["t_end_s"])
    if end <= start:
        raise ValueError("The upper and lower lanes must overlap in time.")
    t = np.linspace(start, end, _BAND_SAMPLES)
    harmonic_number = 2 if harmonic else 1
    upper = fitted_frequency(t, upper_fit) / harmonic_number
    lower = fitted_frequency(t, lower_fit) / harmonic_number
    compression = np.square(upper / lower)
    mach = alfven_mach(compression)
    speed = lower_fit["speed_km_s"]
    alfven_speed = speed / mach
    density = np.square(lower / PLASMA_FREQ_COEFF_MHZ)
    field = magnetic_field_gauss(alfven_speed, density)
    height = fitted_height(t, lower_fit)

    def stats(values):
        return {"mean": float(np.mean(values)), "std": float(np.std(values))}

    return {
        "upper_fit": upper_fit,
        "lower_fit": lower_fit,
        "fold": fold,
        "harmonic": harmonic,
        "profile": {
            "time_s": t.tolist(),
            "height_rsun": height.tolist(),
            "magnetic_field_g": field.tolist(),
        },
        "summary": {
            "relative_bandwidth": stats((upper - lower) / lower),
            "compression_ratio": stats(compression),
            "alfven_mach": stats(mach),
            "shock_speed_km_s": {"value": speed, "error": lower_fit["speed_err_km_s"]},
            "alfven_speed_km_s": stats(alfven_speed),
            "magnetic_field_g": stats(field),
            "height_rsun": stats(height),
        },
    }
