"""Type II radio burst kinematics: drift fit, Newkirk shock and band-splitting.

The method follows the desktop e-CALLISTO FITS Analyzer (S. S. Liyanage),
written here from the underlying relations:

* plasma frequency  f_p [MHz] = 8.98e-3 * sqrt(n_e [cm^-3]);
* Newkirk (1961) corona multiplied by a fold factor n:
  n_e(R) = n * 4.2e4 * 10**(4.32 / R), with R in solar radii, so
  R = 4.32 / log10(f_p**2 / (n * 8.98e-3**2 * 4.2e4));
* shock speed v = R_sun * |dR/df| * |df/dt| from the fitted drift;
* band-splitting: compression X = (f_upper / f_lower)**2, Alfvén Mach number
  of a perpendicular shock in a low-beta plasma
  M_A = sqrt(X (X + 5) / (2 (4 - X)))  (Vršnak et al. 2002), Alfvén speed
  v_A = v / M_A and B = v_A * sqrt(mu_0 * m_p * n_e) with the upstream
  (lower band) density.

Times are seconds since the start of the FITS observation; the power law
f = a * t**(-b) needs t > 0. Newkirk heights and everything derived from them
are model-dependent estimates; band-splitting results are experimental.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import curve_fit

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
    keep = np.isfinite(t) & np.isfinite(f) & (t > 0) & (f > 0)
    if np.count_nonzero(keep) < 3:
        raise ValueError("At least three points with time > 0 s and frequency > 0 MHz are needed.")
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


def _power_law(t, a, b):
    return a * np.power(t, -b)


def fit_power_law(times_s, freqs_mhz) -> dict:
    """Least-squares fit of f = a * t**(-b) with parameter covariance."""
    t, f = _points(times_s, freqs_mhz)
    # Start from the straight line in log-log space, then fit in linear space
    # so that every point weighs by its frequency error, as measured.
    slope, intercept = np.polyfit(np.log(t), np.log(f), 1)
    p0 = (float(np.exp(intercept)), max(float(-slope), 1e-6))
    try:
        (a, b), cov = curve_fit(_power_law, t, f, p0=p0, bounds=([0, 0], [np.inf, np.inf]), maxfev=10000)
    except RuntimeError as exc:
        raise ValueError("The power-law fit did not converge for these points.") from exc
    residuals = f - _power_law(t, a, b)
    ss_tot = float(np.sum((f - f.mean()) ** 2))
    return {
        "a": float(a), "b": float(b), "covariance": cov.tolist(),
        "a_err": float(math.sqrt(cov[0, 0])), "b_err": float(math.sqrt(cov[1, 1])),
        "r2": 1.0 - float(np.sum(residuals**2)) / ss_tot if ss_tot > 0 else 0.0,
        "rmse": float(np.sqrt(np.mean(residuals**2))),
        "points": int(t.size), "t_start_s": float(t[0]), "t_end_s": float(t[-1]),
    }


def _drift(fit: dict, t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """df/dt of the fitted law and its 1-sigma error from the full covariance."""
    a, b = fit["a"], fit["b"]
    drift = -a * b * np.power(t, -b - 1)
    jacobian = np.stack([-b * np.power(t, -b - 1), -a * np.power(t, -b - 1) * (1 - b * np.log(t))])
    cov = np.asarray(fit["covariance"])
    error = np.sqrt(np.einsum("in,ij,jn->n", jacobian, cov, jacobian))
    return drift, error


def newkirk_height(freq_mhz, fold: int) -> np.ndarray:
    """Heliocentric height in solar radii where f is the local plasma frequency."""
    ratio = np.square(np.asarray(freq_mhz, dtype=float)) / (fold * _NEWKIRK_F2_MHZ2)
    if np.any(ratio <= 1):
        raise ValueError("Frequency is below the Newkirk model cutoff.")
    return NEWKIRK_EXPONENT / np.log10(ratio)


def _kinematics(freq, drift, freq_err, drift_err, fold):
    """Height, speed and their 1-sigma errors for fundamental-emission values."""
    log_ratio = np.log(np.square(freq) / (fold * _NEWKIRK_F2_MHZ2))
    height = newkirk_height(freq, fold)
    dheight_df = 2 * NEWKIRK_EXPONENT * math.log(10) / (freq * log_ratio**2)
    speed = R_SUN_KM * dheight_df * np.abs(drift)
    # ln v = ln|df/dt| - ln f - 2 ln(ln ratio) + const, so d ln v / df = -(1 + 4/L) / f.
    speed_err = speed * np.sqrt(
        (drift_err / np.abs(drift)) ** 2 + (freq_err * (1 + 4 / log_ratio) / freq) ** 2
    )
    return height, dheight_df * freq_err, speed, speed_err


def shock_parameters(times_s, freqs_mhz, fold: int = 1, harmonic: bool = False) -> dict:
    """Fit the type II backbone and derive Newkirk shock height and speed.

    For harmonic emission the observed frequency and drift are halved first,
    since the density model applies to the fundamental plasma frequency.
    """
    if fold not in (1, 2, 3, 4):
        raise ValueError("The Newkirk fold must be 1, 2, 3 or 4.")
    t, observed = _points(times_s, freqs_mhz)
    fit = fit_power_law(t, observed)
    harmonic_number = 2 if harmonic else 1
    fitted = _power_law(t, fit["a"], fit["b"]) / harmonic_number
    drift, drift_err = (value / harmonic_number for value in _drift(fit, t))
    freq_err = fit["rmse"] / harmonic_number
    height, height_err, speed, speed_err = _kinematics(fitted, drift, freq_err, drift_err, fold)
    return {
        "fit": fit,
        "fold": fold,
        "harmonic": harmonic,
        "curve": {
            "time_s": t.tolist(),
            "fit_freq_mhz": (fitted * harmonic_number).tolist(),
            "height_rsun": height.tolist(),
            "speed_km_s": speed.tolist(),
        },
        "summary": {
            # "Initial" is the first fitted instant: the highest frequency of the burst.
            "start_freq_mhz": float(fitted[0]), "start_freq_err_mhz": freq_err,
            "start_drift_mhz_s": float(drift[0]), "start_drift_err_mhz_s": float(drift_err[0]),
            "start_height_rsun": float(height[0]), "start_height_err_rsun": float(height_err[0]),
            "start_speed_km_s": float(speed[0]), "start_speed_err_km_s": float(speed_err[0]),
            # Means over the interval; the deviations describe variation, not error.
            "mean_drift_mhz_s": float(drift.mean()), "std_drift_mhz_s": float(drift.std()),
            "mean_height_rsun": float(height.mean()), "std_height_rsun": float(height.std()),
            "mean_speed_km_s": float(speed.mean()), "std_speed_km_s": float(speed.std()),
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
    if fold not in (1, 2, 3, 4):
        raise ValueError("The Newkirk fold must be 1, 2, 3 or 4.")
    upper_fit = fit_power_law(upper_s, upper_mhz)
    lower_fit = fit_power_law(lower_s, lower_mhz)
    start = max(upper_fit["t_start_s"], lower_fit["t_start_s"])
    end = min(upper_fit["t_end_s"], lower_fit["t_end_s"])
    if end <= start:
        raise ValueError("The upper and lower lanes must overlap in time.")
    t = np.linspace(start, end, _BAND_SAMPLES)
    harmonic_number = 2 if harmonic else 1
    upper = _power_law(t, upper_fit["a"], upper_fit["b"]) / harmonic_number
    lower = _power_law(t, lower_fit["a"], lower_fit["b"]) / harmonic_number
    compression = np.square(upper / lower)
    mach = alfven_mach(compression)
    drift, drift_err = (value / harmonic_number for value in _drift(lower_fit, t))
    height, _height_err, speed, _speed_err = _kinematics(
        lower, drift, lower_fit["rmse"] / harmonic_number, drift_err, fold
    )
    alfven_speed = speed / mach
    density = np.square(lower / PLASMA_FREQ_COEFF_MHZ)
    field = magnetic_field_gauss(alfven_speed, density)

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
            "shock_speed_km_s": stats(speed),
            "alfven_speed_km_s": stats(alfven_speed),
            "magnetic_field_g": stats(field),
            "height_rsun": stats(height),
        },
    }
