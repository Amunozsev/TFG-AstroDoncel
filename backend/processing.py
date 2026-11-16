"""Scientific processing of e-CALLISTO FITS data: loading, background subtraction and RFI cleaning."""

from __future__ import annotations

import logging
import threading
import warnings
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import numpy as np
from astropy.io import fits
from scipy.ndimage import label as ndi_label

from backend.timeutil import iso_ms, parse_utc

logger = logging.getLogger(__name__)


# FITS loading

def get_col_1d(table, *names: str) -> np.ndarray | None:
    """Find a column by name (case-insensitive) and return it as a 1D float array."""
    if table is None:
        return None
    col_names = (
        getattr(table, "names", None)
        or getattr(getattr(table, "dtype", None), "names", None)
        or []
    )
    lowered = {str(n).lower(): str(n) for n in col_names}
    for name in names:
        key = lowered.get(name.lower())
        if key is None:
            continue
        try:
            col = table[key]
            arr = np.array(col)
            if arr.ndim == 0:
                continue
            if arr.ndim == 1:
                return arr.astype(float)
            return arr[0].ravel().astype(float)  # repeated table → first row
        except Exception:
            continue
    return None


def axis_from_header(header, axis_num: int, length: int) -> np.ndarray | None:
    """Reconstruct an axis from WCS keywords (CRVALn, CDELTn, CRPIXn)."""
    try:
        crval = header.get(f"CRVAL{axis_num}")
        cdelt = header.get(f"CDELT{axis_num}")
        crpix = header.get(f"CRPIX{axis_num}", 1.0)
        if crval is None or cdelt is None:
            return None
        i = np.arange(int(length), dtype=float) + 1.0  # FITS is 1-based
        return float(crval) + (i - float(crpix)) * float(cdelt)
    except Exception:
        return None


def freq_axis_from_range(header, length: int) -> np.ndarray | None:
    """Reconstruct the frequency axis from FREQMIN/FREQMAX header keywords."""
    try:
        lo = header.get("FREQMIN")
        hi = header.get("FREQMAX")
        if lo is None or hi is None:
            return None
        lo, hi = float(lo), float(hi)
        if not (np.isfinite(lo) and np.isfinite(hi)):
            return None
        # CALLISTO: highest frequency in first row → linspace(hi→lo)
        return np.linspace(max(lo, hi), min(lo, hi), int(length), dtype=float)
    except Exception:
        return None


def load_callisto_data(hdul) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load e-CALLISTO data and return (data, freqs, time_offsets).

    Axes come from the BIN table, then the WCS header, then FREQMIN/FREQMAX, then indices.
    A transposed data array is corrected.
    """
    header = hdul[0].header
    raw = hdul[0].data
    if raw is None:
        raise ValueError("HDU[0] contains no image data.")

    data = np.array(raw, dtype=float)
    data = np.squeeze(data)
    while data.ndim > 2:
        data = data[0]
    if data.ndim != 2:
        raise ValueError(f"Expected 2D data after squeeze, got shape={data.shape}.")

    freqs: np.ndarray | None = None
    time: np.ndarray | None = None

    # Look for axes in secondary HDUs (BIN tables)
    for hdu in hdul[1:]:
        try:
            table = hdu.data
        except Exception:
            continue
        if table is None:
            continue
        if freqs is None:
            freqs = get_col_1d(table, "frequency", "freq")
        if time is None:
            time = get_col_1d(table, "time", "times")
        if freqs is not None and time is not None:
            break

    # Fallback: WCS from primary header
    if freqs is None:
        freqs = axis_from_header(header, 2, data.shape[0])
    if freqs is None:
        freqs = freq_axis_from_range(header, data.shape[0])
    if time is None:
        time = axis_from_header(header, 1, data.shape[1])

    # Final fallback: integer indices
    if freqs is None:
        logger.warning("Frequency axis not found; using indices")
        freqs = np.arange(data.shape[0], dtype=float)
    if time is None:
        logger.warning("Time axis not found; using indices")
        time = np.arange(data.shape[1], dtype=float)

    freqs = np.asarray(freqs, dtype=float).ravel()
    time = np.asarray(time, dtype=float).ravel()

    # Fix transposition: data must be (n_freq, n_time)
    if data.shape != (len(freqs), len(time)) and data.shape == (len(time), len(freqs)):
        data = data.T
        logger.debug("Transposed axes detected and corrected")
    elif data.shape != (len(freqs), len(time)):
        if len(freqs) != data.shape[0]:
            freqs = np.arange(data.shape[0], dtype=float)
        if len(time) != data.shape[1]:
            time = np.arange(data.shape[1], dtype=float)

    return data, freqs, time


# Time axes

def observation_start(header) -> datetime:
    """Resolve observation start time to UTC from DATE-OBS/TIME-OBS."""
    date_obs = str(header.get("DATE-OBS", "1970-01-01")).strip().replace("/", "-")
    time_obs = str(header.get("TIME-OBS", "")).strip()

    # Case 1: DATE-OBS already contains full ISO datetime (DATE-OBS = "YYYY-MM-DDThh:mm:ss")
    if "T" in date_obs:
        try:
            return parse_utc(date_obs)
        except Exception:
            pass

    # Case 2: combine DATE-OBS (date only) with TIME-OBS
    date_part = date_obs.split("T")[0]
    time_part = time_obs if time_obs else "00:00:00"
    try:
        return parse_utc(f"{date_part}T{time_part}")
    except Exception:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def time_offsets_seconds(time_arr: np.ndarray, header) -> np.ndarray:
    """Normalise the raw time axis to seconds since observation start.

    If CDELT1 is available it is used to rescale the axis when the time array
    consists of integer indices (steps of ~1.0).
    """
    arr = np.asarray(time_arr, dtype=float).ravel()
    cdelt1 = header.get("CDELT1")
    if cdelt1 is not None and arr.size > 1:
        diffs = np.diff(arr)
        # Heuristic: if all steps are ~1.0, multiply by CDELT1 (seconds per pixel)
        if np.allclose(diffs, 1.0, atol=1e-3):
            try:
                arr = arr * float(cdelt1)
            except Exception:
                pass
    return arr


def times_to_utc(time_arr: np.ndarray, header) -> list[str]:
    """Convert relative time offsets (seconds) to absolute ISO 8601 UTC timestamps.

    Each value in `time_arr` is interpreted as seconds elapsed since the
    observation start (DATE-OBS + TIME-OBS).
    """
    base = observation_start(header)
    arr = time_offsets_seconds(time_arr, header)

    return [iso_ms(base + timedelta(seconds=float(t))) for t in arr]


# Scientific processing pipeline

def subtract_background(data: np.ndarray) -> np.ndarray:
    """Per-channel background subtraction using each row's 25th percentile.

    The low percentile is robust against intense solar emission.
    """
    arr = np.asarray(data, dtype=np.float32)
    row_invalid = ~np.any(np.isfinite(arr), axis=1)
    baseline = np.full((arr.shape[0], 1), np.nan, dtype=np.float32)
    valid = ~row_invalid
    if np.any(valid):
        baseline[valid, :] = np.nanpercentile(
            arr[valid, :], 25.0, axis=1, keepdims=True
        ).astype(np.float32)
    out = (arr - baseline).astype(np.float32)
    out[row_invalid, :] = np.nan
    return out


def detect_persistent_narrowband_rfi(
    data: np.ndarray,
    z_thresh: float = 6.0,
    occupancy_thresh: float = 0.15,
    eps: float = 1e-6,
) -> tuple[np.ndarray, np.ndarray]:
    """Detect persistent narrowband RFI channels by time-occupancy.

    A channel is flagged when the fraction of samples whose robust z-score
    exceeds z_thresh is above occupancy_thresh.

    Returns (2D boolean mask, per-channel occupancy fractions).
    """
    arr = np.asarray(data, dtype=np.float32)
    with warnings.catch_warnings():
        # All-NaN rows (dead channels) are expected; they yield occ=0 below.
        warnings.simplefilter("ignore", category=RuntimeWarning)
        med = np.nanmedian(arr, axis=1, keepdims=True)
        mad = np.nanmedian(np.abs(arr - med), axis=1, keepdims=True)
    with np.errstate(invalid="ignore"):
        z = (arr - med) / (mad + eps)
        occ = np.mean(np.abs(z) > z_thresh, axis=1)
    occ = np.nan_to_num(occ, nan=0.0)
    ch_mask = occ > occupancy_thresh
    mask = np.repeat(ch_mask[:, None], arr.shape[1], axis=1)
    return mask, occ.astype(np.float32)


def detect_impulsive_rfi(
    data: np.ndarray,
    z_thresh: float = 6.0,
    min_component_size: int = 9,
    eps: float = 1e-6,
) -> np.ndarray:
    """Detect impulsive RFI hotspots via connected components.

    Thresholds the global robust z-score and keeps only connected components
    of at least min_component_size pixels.
    """
    arr = np.asarray(data, dtype=np.float32)
    med = np.nanmedian(arr)
    mad = np.nanmedian(np.abs(arr - med))
    with np.errstate(invalid="ignore"):
        z = (arr - med) / (mad + eps)
        candidate = np.abs(z) > z_thresh
    candidate &= np.isfinite(arr)
    labeled, n_comp = ndi_label(candidate)
    if n_comp == 0:
        return np.zeros_like(candidate, dtype=bool)
    sizes = np.bincount(labeled.ravel())
    keep = np.zeros(n_comp + 1, dtype=bool)
    keep[1:] = sizes[1:] >= max(1, int(min_component_size))
    return keep[labeled]


def inpaint_with_channel_median(data: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Replace masked samples with their channel median (global median for empty channels)."""
    arr = np.asarray(data, dtype=np.float32)
    mask = np.asarray(mask, dtype=bool)
    out = arr.copy()

    finite = np.where(np.isfinite(out), out, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        row_median = np.nanmedian(finite, axis=1)
        global_median = np.nanmedian(finite)
    if not np.isfinite(global_median):
        global_median = 0.0

    for f in range(out.shape[0]):
        row_mask = mask[f]
        if not row_mask.any():
            continue
        fill = row_median[f]
        if not np.isfinite(fill):
            fill = global_median
        out[f, row_mask] = fill
    return out.astype(np.float32)


def mitigate_rfi(
    data: np.ndarray,
    *,
    z_thresh: float = 6.0,
    occupancy_thresh: float = 0.15,
    min_component_size: int = 9,
    impulsive: bool = True,
) -> tuple[np.ndarray, list[int], dict]:
    """RFI cleaning adapted from Sahan S. Liyanage's Burst_No_Burst.

    Steps:
    1. Persistent narrowband RFI: per-channel occupancy of |z| > z_thresh.
    2. Impulsive RFI: connected components of the global z-score map
       (optional — strong solar bursts can also form large bright components,
       so this stage can be disabled from the UI).
    3. Inpaint every masked sample with its channel median.

    Returns (cleaned_data, masked_channel_indices, stats).
    """
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError("mitigate_rfi expects a 2D array (freq, time).")

    persistent_mask, occupancy = detect_persistent_narrowband_rfi(
        arr, z_thresh=float(z_thresh), occupancy_thresh=float(occupancy_thresh)
    )
    if impulsive:
        impulsive_mask = detect_impulsive_rfi(
            arr, z_thresh=float(z_thresh), min_component_size=int(min_component_size)
        )
    else:
        impulsive_mask = np.zeros_like(persistent_mask, dtype=bool)
    combined_mask = persistent_mask | impulsive_mask
    cleaned = inpaint_with_channel_median(arr, combined_mask)

    masked_channels = [int(i) for i in np.where(np.any(persistent_mask, axis=1))[0]]
    stats = {
        "persistent_channels": len(masked_channels),
        "masked_fraction": round(float(combined_mask.mean()), 5),
        "occupancy_mean": round(float(np.mean(occupancy)), 5),
        "impulsive_enabled": bool(impulsive),
    }
    return cleaned.astype(np.float32), masked_channels, stats


DIGITS_TO_DB = 2500.0 / 255.0 / 25.4  # instrumental digits to dB


def scale(data: np.ndarray, scale_mode: str) -> np.ndarray:
    if scale_mode not in {"relative", "median_db"}:
        raise ValueError("scale_mode must be relative or median_db")
    return data * DIGITS_TO_DB if scale_mode == "median_db" else data


def process(data: np.ndarray, rfi_args: dict | None) -> tuple[np.ndarray, dict]:
    """Background subtraction plus optional RFI cleaning; returns (data, rfi_stats)."""
    data = subtract_background(data)
    if rfi_args is None:
        return data, {}
    data, _channels, stats = mitigate_rfi(data, **rfi_args)
    return data, stats


def percentile_clip(data: np.ndarray, lo: float = 2.0, hi: float = 98.0) -> tuple[float, float]:
    """Compute vmin (lo percentile) and vmax (hi percentile) over all data."""
    if not 0 <= lo < hi <= 100:
        raise ValueError("percentile bounds must satisfy 0 <= lo < hi <= 100")
    # Both bounds in one call: a single order-statistics pass.
    values = np.asarray(data)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0, 1.0
    vmin, vmax = np.percentile(finite, [lo, hi])
    return float(vmin), float(vmax)

# Raw FITS cache (avoids re-parsing the same file on every zoom)

_RAW_CACHE: OrderedDict[str, tuple] = OrderedDict()
_RAW_CACHE_LOCK = threading.Lock()
_RAW_CACHE_MAX = 8


def load_raw_cached(
    fits_path: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, object]:
    """Open a FITS file and return (data, freqs, time_arr, header), using an LRU cache.

    The returned arrays are the *raw* unprocessed data — background subtraction
    and RFI cleaning are intentionally NOT applied here so that callers can slice
    first and then process only the relevant region.
    Cached entries are never mutated by callers (all processing functions create
    new arrays), so it is safe to return the arrays without copying.
    """
    with _RAW_CACHE_LOCK:
        if fits_path in _RAW_CACHE:
            _RAW_CACHE.move_to_end(fits_path)
            return _RAW_CACHE[fits_path]
    # Cache miss — load outside the lock so we don't block other threads
    with fits.open(fits_path, memmap=False) as hdul:
        data, freqs, time_arr = load_callisto_data(hdul)
        header = hdul[0].header.copy()
    entry = (data, freqs, time_arr, header)
    with _RAW_CACHE_LOCK:
        # A concurrent thread may have inserted the same key; prefer its entry
        if fits_path not in _RAW_CACHE:
            _RAW_CACHE[fits_path] = entry
        _RAW_CACHE.move_to_end(fits_path)
        while len(_RAW_CACHE) > _RAW_CACHE_MAX:
            _RAW_CACHE.popitem(last=False)
        return _RAW_CACHE[fits_path]


def decimate_time(
    data: np.ndarray,
    time_labels: list[str],
    max_cols: int,
) -> tuple[np.ndarray, list[str]]:
    """Block-mean the time axis down to at most max_cols columns.

    Frequencies are NOT decimated. The time labels list is decimated in lockstep
    by taking the first label of each block (the block-start timestamp).
    """
    n_cols = data.shape[1]
    if max_cols < 1:
        raise ValueError("max_cols must be positive")
    if n_cols <= max_cols:
        return data, time_labels
    k = (n_cols + max_cols - 1) // max_cols
    n_full = (n_cols // k) * k
    decimated = data[:, :n_full].reshape(data.shape[0], n_full // k, k).mean(axis=2)
    if n_full < n_cols:
        decimated = np.concatenate((decimated, data[:, n_full:].mean(axis=1, keepdims=True)), axis=1)
    dec_labels = time_labels[::k]
    return decimated, dec_labels
