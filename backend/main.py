"""
AstroDoncel API — backend FastAPI para espectrogramas e-CALLISTO.
Motor científico portado de e-CALLISTO FITS Analyzer (Sahan S Liyanage, v2.4.1).
"""

from __future__ import annotations

import asyncio
import glob
import html
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen

import numpy as np
from astropy.io import fits
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from scipy.ndimage import median_filter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AstroDoncel API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR_LOCAL = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data")
)
ECALLISTO_DATA_DIR = os.environ.get(
    "ECALLISTO_DATA_DIR", "/var/services/web/ecallistodata"
)
ETHZ_BASE_URL = "http://soleil.i4ds.ch/solarradio/data/2002-20yy_Callisto"

# Lista estática de respaldo — 76 estaciones reales extraídas del archivo ETHZ
# (generada escaneando múltiples fechas de 2024-2026)
_STATIONS_FALLBACK: list[str] = [
    "ALASKA-ANCHORAGE",
    "ALASKA-COHOE",
    "ALASKA-HAARP",
    "ALGERIA-CRAAG",
    "ALMATY",
    "AUSTRALIA-ASSA",
    "AUSTRIA-KRUMBACH",
    "AUSTRIA-MICHELBACH",
    "AUSTRIA-OE3FLB",
    "AUSTRIA-UNIGRAZ",
    "BIR",
    "BRAZIL",
    "CROATIA-VISNJAN",
    "DENMARK",
    "EGYPT-ALEXANDRIA",
    "EGYPT-SPACEAGENCY",
    "ETHIOPIA",
    "FINLAND-KEMPELE",
    "FINLAND-RUISSALO",
    "FINLAND-SIUNTIO",
    "GERMANY-DLR",
    "GERMANY-ESSEN",
    "GLASGOW",
    "GREENLAND",
    "HUMAIN",
    "HURBANOVO",
    "INDIA-GAURI",
    "INDIA-OOTY",
    "INDIA-UDAIPUR",
    "INDONESIA",
    "ITALY-STRASSOLT",
    "JAPAN-IBARAKI",
    "KASI",
    "MALAYSIA-BANTING",
    "MEXART",
    "MEXICO-ENSENADA-UNAM",
    "MEXICO-FCFM-UANL",
    "MEXICO-FCFM-UNACH",
    "MEXICO-LANCE",
    "MEXICO-LANCE-A",
    "MEXICO-LANCE-B",
    "MEXICO-UANL-INFIERNILLO",
    "MONGOLIA-UB",
    "MRO",
    "MRT1",
    "NASA-GSFC",
    "NORWAY-EGERSUND",
    "NORWAY-NY-AALESUND",
    "NORWAY-RANDABERG",
    "NZ-WAIRAKEI-DLR",
    "PARAGUAY",
    "POLAND-BALDY",
    "POLAND-GROTNIKI",
    "ROMANIA",
    "ROSWELL-NM",
    "RWANDA",
    "SPAIN-PERALEJOS",
    "SPAIN-SIGUENZA",
    "SRI-LANKA",
    "SSRT",
    "SWISS-BLEN5M-E",
    "SWISS-CALU",
    "SWISS-FM",
    "SWISS-HB9SCT",
    "SWISS-HEITERSWIL",
    "SWISS-IRSOL",
    "SWISS-LANDSCHLACHT",
    "SWISS-MUHEN",
    "TAIWAN-NCU",
    "TRIEST",
    "TURKEY",
    "UNAM",
    "URUGUAY",
    "USA-ARIZONA-ERAU",
    "USA-BOSTON",
    "UZBEKISTAN",
]


# ── Modelos ──────────────────────────────────────────────────────────────────

class SpectrogramResponse(BaseModel):
    station: str
    date: str
    filename: str
    time_axis: list[str]
    freq_axis: list[float]
    z: list[list[float]]
    vmin: float
    vmax: float
    fits_header: dict
    rfi_masked_channels: list[int] = []


class GoesResponse(BaseModel):
    date: str
    available: bool
    reason: str
    times: list[str]
    xrsb: list[float]
    satellite: int | None = None


class StationsResponse(BaseModel):
    stations: list[str]
    source: str


class FileEntry(BaseModel):
    filename: str
    time: str    # "HH:MM:SS"
    label: str   # para mostrar en UI


class FilesResponse(BaseModel):
    station: str
    date: str
    files: list[FileEntry]
    source: str  # "local", "ethz", "mixed"


# ── Helpers de I/O ───────────────────────────────────────────────────────────

def _open_fits(path: str):
    """Abre un archivo FITS (soporta .fit, .fits, .fit.gz, .fits.gz)."""
    try:
        return fits.open(path, memmap=False)
    except Exception as exc:
        logger.error("Error al abrir %s: %s", path, exc)
        raise HTTPException(status_code=500, detail=f"No se pudo abrir el archivo FITS: {exc}")


def _find_local_fits_file(station: str, date: str) -> str | None:
    """Busca en ../data/ primero por (estación + fecha), luego solo por estación."""
    if not os.path.isdir(DATA_DIR_LOCAL):
        return None
    # Coincidencia estación + fecha específica
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
        date_str = dt.strftime("%Y%m%d")
        for ext in (".fit.gz", ".fits.gz", ".fit", ".fits"):
            matches = glob.glob(
                os.path.join(DATA_DIR_LOCAL, f"*{station.upper()}*{date_str}*{ext}")
            )
            if matches:
                return sorted(matches)[0]
    except ValueError:
        pass
    # Coincidencia solo por estación (útil en desarrollo con archivos de muestra)
    for ext in (".fit.gz", ".fits.gz", ".fit", ".fits"):
        matches = glob.glob(os.path.join(DATA_DIR_LOCAL, f"*{station.upper()}*{ext}"))
        if matches:
            return sorted(matches)[0]
    return None


def _find_nas_fits_file(station: str, date: str) -> str | None:
    """Busca en la estructura NAS ECALLISTO_DATA_DIR/YYYY/MM/DD/."""
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return None
    date_dir = os.path.join(
        ECALLISTO_DATA_DIR, dt.strftime("%Y"), dt.strftime("%m"), dt.strftime("%d")
    )
    if not os.path.isdir(date_dir):
        return None
    for ext in (".fit.gz", ".fits.gz", ".fit", ".fits"):
        matches = glob.glob(os.path.join(date_dir, f"*{station.upper()}*{ext}"))
        if matches:
            return sorted(matches)[0]
    return None


def _time_from_filename(filename: str) -> str:
    """Extrae la hora de inicio en formato HH:MM:SS del nombre de archivo CALLISTO."""
    m = re.search(r'_\d{8}_(\d{2})(\d{2})(\d{2})_\d+', filename)
    if m:
        return f"{m.group(1)}:{m.group(2)}:{m.group(3)}"
    return "??:??:??"


def _list_local_fits_files(station: str, date: str) -> list[str]:
    """Devuelve nombres de archivo locales cacheados para estación/fecha."""
    if not os.path.isdir(DATA_DIR_LOCAL):
        return []
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
        date_str = dt.strftime("%Y%m%d")
    except ValueError:
        return []
    found: list[str] = []
    for ext in (".fit.gz", ".fits.gz", ".fit", ".fits"):
        for path in glob.glob(
            os.path.join(DATA_DIR_LOCAL, f"*{station.upper()}*{date_str}*{ext}")
        ):
            found.append(os.path.basename(path))
    return sorted(set(found))


def _list_ethz_files(station: str, date: str) -> list[str]:
    """Escanea el índice HTTP de ETHZ y devuelve nombres de archivo disponibles."""
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return []
    dir_url = f"{ETHZ_BASE_URL}/{dt.strftime('%Y/%m/%d')}/"
    try:
        req = Request(dir_url, headers={"User-Agent": "AstroDoncel/1.0"})
        with urlopen(req, timeout=15) as resp:
            page = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return []
    date_str = dt.strftime("%Y%m%d")
    prefix_re = re.compile(
        r'href="(' + re.escape(station.upper()) + r'_' + date_str + r'_\d{6}_\d{2}\.fit(?:\.gz)?)"',
        re.IGNORECASE,
    )
    matches = sorted(set(prefix_re.findall(page)))
    if not matches:
        all_files = re.findall(r'href="([^"]+\.fit(?:\.gz)?)"', page, re.IGNORECASE)
        matches = sorted(c for c in all_files if station.upper() in html.unescape(c).upper())
    return matches


def _download_from_ethz(station: str, date: str, filename: str | None = None) -> str | None:
    """Descarga un archivo FITS desde el archivo ETHZ.

    Si `filename` se especifica, descarga ese archivo concreto.
    Si no, descarga el primer archivo que coincida con la estación/fecha.
    Guarda en DATA_DIR_LOCAL para reusar en llamadas futuras.
    """
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return None

    dir_url = f"{ETHZ_BASE_URL}/{dt.strftime('%Y/%m/%d')}/"
    os.makedirs(DATA_DIR_LOCAL, exist_ok=True)

    if filename:
        local_path = os.path.join(DATA_DIR_LOCAL, filename)
        if os.path.isfile(local_path):
            logger.info("Archivo ya en caché: %s", local_path)
            return local_path
        file_url = dir_url + filename
        logger.info("Descargando %s → %s", file_url, local_path)
        try:
            req = Request(file_url, headers={"User-Agent": "AstroDoncel/1.0"})
            with urlopen(req, timeout=120) as resp:
                with open(local_path, "wb") as fh:
                    while chunk := resp.read(512 * 1024):
                        fh.write(chunk)
            logger.info("Descarga completada (%d bytes)", os.path.getsize(local_path))
            return local_path
        except Exception as exc:
            logger.error("Fallo al descargar %s: %s", file_url, exc)
            try:
                os.remove(local_path)
            except OSError:
                pass
            return None

    # Sin filename: inspecciona el directorio para encontrar el primero que coincida
    logger.info("Consultando archivo ETHZ: %s", dir_url)
    try:
        req = Request(dir_url, headers={"User-Agent": "AstroDoncel/1.0"})
        with urlopen(req, timeout=15) as resp:
            page = resp.read().decode("utf-8", errors="replace")
    except URLError as exc:
        logger.warning("No se pudo acceder al archivo ETHZ: %s", exc)
        return None

    date_str = dt.strftime("%Y%m%d")
    prefix_re = re.compile(
        r'href="(' + re.escape(station.upper()) + r'_' + date_str + r'_\d{6}_\d{2}\.fit(?:\.gz)?)"',
        re.IGNORECASE,
    )
    matches = sorted(set(prefix_re.findall(page)))
    if not matches:
        all_files = re.findall(r'href="([^"]+\.fit(?:\.gz)?)"', page, re.IGNORECASE)
        matches = sorted(c for c in all_files if station.upper() in html.unescape(c).upper())
    if not matches:
        logger.warning("No hay archivos de '%s' en ETHZ para %s", station, date)
        return None

    return _download_from_ethz(station, date, filename=matches[0])


# ── Carga FITS (portado de fits_io.load_callisto_fits de Sahan) ──────────────

def _get_col_1d(table, *names: str) -> np.ndarray | None:
    """Busca una columna por nombre (case-insensitive) y devuelve array 1D float."""
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
            return arr[0].ravel().astype(float)  # tabla repetida → primera fila
        except Exception:
            continue
    return None


def _axis_from_header(header, axis_num: int, length: int) -> np.ndarray | None:
    """Reconstruye eje por WCS (CRVALn, CDELTn, CRPIXn)."""
    try:
        crval = header.get(f"CRVAL{axis_num}")
        cdelt = header.get(f"CDELT{axis_num}")
        crpix = header.get(f"CRPIX{axis_num}", 1.0)
        if crval is None or cdelt is None:
            return None
        i = np.arange(int(length), dtype=float) + 1.0  # FITS es 1-based
        return float(crval) + (i - float(crpix)) * float(cdelt)
    except Exception:
        return None


def _freq_axis_from_range(header, length: int) -> np.ndarray | None:
    """Reconstruye eje de frecuencias desde FREQMIN/FREQMAX del header."""
    try:
        lo = header.get("FREQMIN")
        hi = header.get("FREQMAX")
        if lo is None or hi is None:
            return None
        lo, hi = float(lo), float(hi)
        if not (np.isfinite(lo) and np.isfinite(hi)):
            return None
        # CALLISTO: frecuencia alta en primera fila → linspace(hi→lo)
        return np.linspace(max(lo, hi), min(lo, hi), int(length), dtype=float)
    except Exception:
        return None


def _load_callisto_data(hdul) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Carga datos e-CALLISTO y devuelve (data, freqs, time_offsets).

    Portado de fits_io.load_callisto_fits() de Sahan con mejoras:
    - Busca columnas por nombre alternativo: frequency/freq, time/times.
    - Detecta y corrige ejes transpuestos automáticamente.
    - Fallback secuencial: tabla BIN → WCS header → FREQMIN/FREQMAX → índices.
    """
    header = hdul[0].header
    raw = hdul[0].data
    if raw is None:
        raise ValueError("HDU[0] no contiene imagen.")

    data = np.array(raw, dtype=float)
    data = np.squeeze(data)
    while data.ndim > 2:
        data = data[0]
    if data.ndim != 2:
        raise ValueError(f"Se esperaban datos 2D tras squeeze, shape={data.shape}.")

    freqs: np.ndarray | None = None
    time: np.ndarray | None = None

    # Buscar ejes en HDUs secundarios (tablas BIN)
    for hdu in hdul[1:]:
        try:
            table = hdu.data
        except Exception:
            continue
        if table is None:
            continue
        if freqs is None:
            freqs = _get_col_1d(table, "frequency", "freq")
        if time is None:
            time = _get_col_1d(table, "time", "times")
        if freqs is not None and time is not None:
            break

    # Fallback: WCS del header primario
    if freqs is None:
        freqs = _axis_from_header(header, 2, data.shape[0])
    if freqs is None:
        freqs = _freq_axis_from_range(header, data.shape[0])
    if time is None:
        time = _axis_from_header(header, 1, data.shape[1])

    # Fallback final: índices enteros
    if freqs is None:
        logger.warning("Eje de frecuencias no encontrado; usando índices")
        freqs = np.arange(data.shape[0], dtype=float)
    if time is None:
        logger.warning("Eje temporal no encontrado; usando índices")
        time = np.arange(data.shape[1], dtype=float)

    freqs = np.asarray(freqs, dtype=float).ravel()
    time = np.asarray(time, dtype=float).ravel()

    # Corregir transposición: data debe ser (n_freq, n_time)
    if data.shape == (len(time), len(freqs)):
        data = data.T
        logger.debug("Transposición de ejes detectada y corregida")
    elif data.shape != (len(freqs), len(time)):
        if len(freqs) != data.shape[0]:
            freqs = np.arange(data.shape[0], dtype=float)
        if len(time) != data.shape[1]:
            time = np.arange(data.shape[1], dtype=float)

    return data, freqs, time


# ── Ejes temporales ──────────────────────────────────────────────────────────

def _observation_start(header) -> datetime:
    """Resuelve el instante de inicio de la observación a UTC desde DATE-OBS/TIME-OBS."""
    date_obs = str(header.get("DATE-OBS", "1970-01-01")).strip().replace("/", "-")
    time_obs = str(header.get("TIME-OBS", "")).strip()

    # Caso 1: DATE-OBS ya contiene fecha+hora ISO (DATE-OBS = "YYYY-MM-DDThh:mm:ss")
    if "T" in date_obs:
        try:
            base = datetime.fromisoformat(date_obs.replace("Z", "+00:00"))
            return base if base.tzinfo else base.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    # Caso 2: combinar DATE-OBS (solo fecha) con TIME-OBS
    date_part = date_obs.split("T")[0]
    time_part = time_obs if time_obs else "00:00:00"
    try:
        return datetime.fromisoformat(f"{date_part}T{time_part}").replace(tzinfo=timezone.utc)
    except Exception:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _times_to_utc(time_arr: np.ndarray, header) -> list[str]:
    """Convierte offsets relativos en segundos a timestamps ISO 8601 UTC absolutos.

    Cada valor de `time_arr` se interpreta como segundos transcurridos desde el
    instante de inicio (DATE-OBS + TIME-OBS). Si CDELT1 está disponible se usa
    para reconstruir el eje cuando el array temporal viene como índices.
    """
    base = _observation_start(header)

    arr = np.asarray(time_arr, dtype=float).ravel()
    # Si el array parece ser índices enteros consecutivos (0,1,2,...), reescala con CDELT1
    cdelt1 = header.get("CDELT1")
    if cdelt1 is not None and arr.size > 1:
        diffs = np.diff(arr)
        # Heurística: si todos los pasos son ~1.0, multiplicar por CDELT1 (segundos por píxel)
        if np.allclose(diffs, 1.0, atol=1e-3):
            try:
                arr = arr * float(cdelt1)
            except Exception:
                pass

    labels: list[str] = []
    for t in arr:
        ts = base + timedelta(seconds=float(t))
        ms = ts.microsecond // 1000
        labels.append(f"{ts.strftime('%Y-%m-%dT%H:%M:%S')}.{ms:03d}Z")
    return labels


# ── Pipeline de procesamiento científico (portado de Sahan) ──────────────────

def _invalid_row_mask(data: np.ndarray) -> np.ndarray:
    """True en filas donde ningún valor es finito (portado de frequency_axis.py)."""
    return ~np.any(np.isfinite(data), axis=1)


def _subtract_background(data: np.ndarray) -> np.ndarray:
    """Sustracción de fondo robusta por canal de frecuencia.

    Portado de noise_reduction.subtract_background_rows() de Sahan (método 'robust').
    Usa el percentil 25 de cada fila como estimación del fondo: es robusto ante
    emisión solar intensa que eleva los percentiles altos.
    """
    arr = np.asarray(data, dtype=np.float32)
    row_invalid = _invalid_row_mask(arr)
    baseline = np.full((arr.shape[0], 1), np.nan, dtype=np.float32)
    valid = ~row_invalid
    if np.any(valid):
        baseline[valid, :] = np.nanpercentile(
            arr[valid, :], 25.0, axis=1, keepdims=True
        ).astype(np.float32)
    out = (arr - baseline).astype(np.float32)
    out[row_invalid, :] = np.nan
    return out


def _robust_z_score(values: np.ndarray) -> np.ndarray:
    """Z-score robusto basado en MAD (portado de rfi_filters._robust_z de Sahan)."""
    arr = np.asarray(values, dtype=float)
    med = np.nanmedian(arr)
    mad = np.nanmedian(np.abs(arr - med))
    if not np.isfinite(mad) or mad <= 0:
        std = np.nanstd(arr)
        if np.isfinite(std) and std > 0:
            return (arr - med) / std
        return np.where(np.abs(arr - med) > 0, np.inf, 0.0).astype(float)
    return 0.6745 * (arr - med) / mad


def _mask_hot_channels(data: np.ndarray, z_thresh: float = 6.0) -> list[int]:
    """Detecta canales de frecuencia dominados por RFI.

    Portado de rfi_filters._mask_hot_channels() de Sahan.
    Combina nivel absoluto y variabilidad de cada fila en un score, luego
    aplica z-score robusto para identificar outliers estadísticos.
    """
    if data.ndim != 2 or data.shape[0] == 0:
        return []
    row_med = np.nanmedian(data, axis=1)
    row_mad = np.nanmedian(np.abs(data - row_med[:, None]), axis=1)
    score = np.abs(row_med) + row_mad
    z = _robust_z_score(score)
    return [int(i) for i in np.where(z > float(z_thresh))[0].tolist()]


def _repair_masked_channels(data: np.ndarray, masked: list[int]) -> np.ndarray:
    """Interpola canales enmascarados desde sus vecinos adyacentes.

    Portado de rfi_filters._repair_masked_channels() de Sahan.
    """
    if not masked:
        return data
    out = data.copy()
    n = out.shape[0]
    for idx in masked:
        if idx <= 0:
            out[idx] = out[1] if n > 1 else out[0]
        elif idx >= n - 1:
            out[idx] = out[n - 2] if n > 1 else out[0]
        else:
            out[idx] = 0.5 * (out[idx - 1] + out[idx + 1])
    return out


def _percentile_clip_per_channel(data: np.ndarray, upper: float = 99.5) -> np.ndarray:
    """Recorta outliers altos por canal preservando la morfología de bursts.

    Portado de rfi_filters._percentile_clip_per_channel() de Sahan.
    Solo recorta el lado alto; el lado bajo se preserva para no perder estructura.
    """
    if data.ndim != 2 or upper <= 0 or upper >= 100:
        return data
    out = data.copy()
    highs = np.nanpercentile(out, upper, axis=1)
    for i in range(out.shape[0]):
        out[i] = np.minimum(out[i], highs[i])
    return out


def _clean_rfi(
    data: np.ndarray,
    *,
    kernel_time: int = 3,
    kernel_freq: int = 3,
    channel_z_threshold: float = 6.0,
    percentile_clip: float = 99.5,
) -> tuple[np.ndarray, list[int]]:
    """Pipeline completo de limpieza RFI. Portado de rfi_filters.clean_rfi() de Sahan.

    Pasos:
    1. Filtro mediana 2D → elimina picos puntuales en tiempo y frecuencia.
    2. Detección de canales calientes por z-score robusto.
    3. Reparación de canales enmascarados por interpolación con vecinos.
    4. Recorte de outliers altos por canal (preserva morfología de bursts).

    Devuelve (data_limpio, lista_de_indices_enmascarados).
    """
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError("_clean_rfi espera un array 2D (freq, time).")

    def _ensure_odd(v: int) -> int:
        v = max(1, int(v))
        return v if v % 2 != 0 else v + 1

    filtered = median_filter(
        arr,
        size=(_ensure_odd(kernel_freq), _ensure_odd(kernel_time)),
        mode="nearest",
    ).astype(np.float32)
    masked = _mask_hot_channels(arr, z_thresh=float(channel_z_threshold))
    repaired = _repair_masked_channels(filtered, masked)
    clipped = _percentile_clip_per_channel(repaired, upper=float(percentile_clip))

    return clipped.astype(np.float32), masked


def _percentile_clip_global(data: np.ndarray, lo: float = 2.0, hi: float = 98.0) -> tuple[float, float]:
    """Calcula vmin (percentil lo) y vmax (percentil hi) sobre todos los datos.

    El percentil alto por defecto es 98 (en lugar de 99.5) para aumentar el contraste
    visual: aplasta los outliers más extremos y permite que ráfagas/bursts moderados
    destaquen claramente sobre el fondo.
    """
    vmin = float(np.nanpercentile(data, lo))
    vmax = float(np.nanpercentile(data, hi))
    return vmin, vmax


def _header_to_dict(header) -> dict:
    """Convierte header FITS a dict JSON-serializable."""
    result: dict = {}
    for key, value in header.items():
        if key in ("COMMENT", "HISTORY", ""):
            continue
        try:
            result[key] = value if isinstance(value, (int, float, str, bool)) else str(value)
        except Exception:
            result[key] = str(value)
    return result


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": "0.2.0"}


@app.get("/api/stations", response_model=StationsResponse)
def get_stations():
    """Devuelve la lista real de estaciones e-Callisto escaneando el archivo ETHZ.

    Intenta los últimos 7 días para encontrar un día con datos. Si ETHZ no es
    accesible, devuelve la lista estática de respaldo.
    """
    for days_back in range(1, 8):
        dt = datetime.now() - timedelta(days=days_back)
        dir_url = f"{ETHZ_BASE_URL}/{dt.strftime('%Y/%m/%d')}/"
        try:
            req = Request(dir_url, headers={"User-Agent": "AstroDoncel/1.0"})
            with urlopen(req, timeout=10) as resp:
                page = resp.read().decode("utf-8", errors="replace")
            # Extrae nombre de estación: todo antes de _YYYYMMDD_HHMMSS_NN.fit[.gz]
            pattern = re.compile(
                r'href="([A-Za-z][A-Za-z0-9_-]*?)_\d{8}_\d{6}_\d{2}\.fit(?:\.gz)?"',
                re.IGNORECASE,
            )
            names = [m.upper() for m in pattern.findall(page)]
            if names:
                unique = sorted(set(names))
                logger.info(
                    "Estaciones encontradas en ETHZ: %d (fecha %s)",
                    len(unique),
                    dt.strftime("%Y-%m-%d"),
                )
                return StationsResponse(stations=unique, source="ethz")
        except Exception as exc:
            logger.debug("ETHZ stations fallido para %s: %s", dt.strftime("%Y-%m-%d"), exc)
            continue

    logger.warning("ETHZ inaccesible para lista de estaciones; usando lista estática")
    return StationsResponse(stations=_STATIONS_FALLBACK, source="static")


@app.get("/api/files", response_model=FilesResponse)
def get_files(
    station: str = Query(..., description="Estación e-Callisto"),
    date: str = Query(..., description="Fecha de observación, formato YYYY-MM-DD"),
):
    """Lista todos los archivos de bursts disponibles para una estación y fecha.

    Combina archivos en caché local (ya descargados) con los disponibles en ETHZ.
    Cada entrada incluye el nombre de archivo y la hora de inicio extraída del nombre.
    """
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Formato de fecha inválido: '{date}'")

    local = set(_list_local_fits_files(station, date))
    ethz = set(_list_ethz_files(station, date))
    all_files = sorted(local | ethz)

    source = "ethz" if ethz else ("local" if local else "none")
    if local and ethz and local != ethz:
        source = "mixed"

    entries: list[FileEntry] = []
    for fn in all_files:
        t = _time_from_filename(fn)
        cached = "★ " if fn in local else ""
        entries.append(FileEntry(filename=fn, time=t, label=f"{cached}{t}"))

    return FilesResponse(station=station, date=date, files=entries, source=source)


@app.get("/api/spectrogram", response_model=SpectrogramResponse)
def get_spectrogram(
    station: str = Query(..., description="Estación e-Callisto, ej. SPAIN-SIGUENZA"),
    date: str = Query(..., description="Fecha de observación, formato YYYY-MM-DD"),
    filename: str = Query(default=None, description="Nombre de archivo FITS concreto"),
    file_path: str = Query(default=None, description="Ruta absoluta (override manual)"),
    sahan_filter: bool = Query(default=False, description="Aplica limpieza RFI completa"),
):
    """Devuelve el espectrograma de una estación e-Callisto.

    Orden de resolución:
    1) file_path explícito
    2) filename → caché local → descarga ETHZ
    3) primera coincidencia local → NAS → descarga ETHZ

    Pipeline de procesamiento:
    - Siempre: sustracción de fondo robusta (percentil 25 por canal de frecuencia).
    - Si sahan_filter=true: además aplica limpieza RFI completa.
    - vmin/vmax se recalculan SIEMPRE sobre los datos ya procesados.
    """
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Formato de fecha inválido: '{date}'")

    if file_path:
        if not os.path.isfile(file_path):
            raise HTTPException(status_code=404, detail=f"Archivo no encontrado: {file_path}")
        fits_path = file_path
        logger.info("Usando file_path explícito: %s", fits_path)
    elif filename:
        local_path = os.path.join(DATA_DIR_LOCAL, filename)
        if os.path.isfile(local_path):
            fits_path = local_path
            logger.info("Usando archivo local cacheado: %s", fits_path)
        else:
            fits_path = _download_from_ethz(station, date, filename=filename)
        if not fits_path:
            raise HTTPException(
                status_code=404,
                detail=f"No se pudo obtener el archivo '{filename}' para '{station}' en {date}.",
            )
    else:
        fits_path = (
            _find_local_fits_file(station, date)
            or _find_nas_fits_file(station, date)
            or _download_from_ethz(station, date)
        )
        if not fits_path:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No se encontró ningún archivo para la estación '{station}' "
                    f"en la fecha {date}. Verifica el nombre de la estación o que "
                    "el servidor ETHZ (soleil.i4ds.ch) sea accesible."
                ),
            )

    logger.info("Procesando %s", fits_path)
    try:
        with _open_fits(fits_path) as hdul:
            data, freqs, time_arr = _load_callisto_data(hdul)
            header = hdul[0].header
            time_labels = _times_to_utc(time_arr, header)

            # 1. Sustracción de fondo robusta (siempre activa)
            data = _subtract_background(data)

            # 2. Limpieza RFI completa (opcional, activada por sahan_filter)
            rfi_masked: list[int] = []
            if sahan_filter:
                data, rfi_masked = _clean_rfi(data)
                logger.info(
                    "Filtro RFI aplicado: %d canales enmascarados", len(rfi_masked)
                )

            # 3. Recalcular vmin/vmax sobre datos PROCESADOS (no sobre raw)
            finite_vals = data[np.isfinite(data)]
            if finite_vals.size == 0:
                vmin, vmax = 0.0, 1.0
            else:
                vmin, vmax = _percentile_clip_global(data.astype(float))

            data_out = np.nan_to_num(
                np.array(data, dtype=float),
                nan=0.0,
                posinf=vmax,
                neginf=vmin,
            )

            return SpectrogramResponse(
                station=station,
                date=date,
                filename=os.path.basename(fits_path),
                time_axis=time_labels,
                freq_axis=[round(float(f), 3) for f in freqs],
                z=[[round(float(v), 4) for v in row] for row in data_out.tolist()],
                vmin=round(vmin, 4),
                vmax=round(vmax, 4),
                fits_header=_header_to_dict(header),
                rfi_masked_channels=rfi_masked,
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error inesperado procesando %s", fits_path)
        raise HTTPException(status_code=500, detail=f"Error al procesar FITS: {exc}")


# ── GOES/XRS overlay (portado de goes_overlay.py de Sahan, simplificado) ─────

_GOES_CACHE_DIR = os.path.join(DATA_DIR_LOCAL, "goes_cache")
_GOES_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="goes-fido")

# Orden preferido de satélites GOES por época (de goes_overlay.py de Sahan).
def _preferred_goes_satellites(year: int) -> tuple[int, ...]:
    if year >= 2025:
        return (19, 18, 17, 16)
    if year >= 2022:
        return (18, 17, 16, 15, 14, 13)
    if year >= 2017:
        return (17, 16, 15, 14, 13)
    if year >= 2010:
        return (15, 14, 13, 12, 11, 10)
    if year >= 2003:
        return (12, 11, 10, 9, 8)
    if year >= 1997:
        return (10, 9, 8)
    return (9, 8)


def _pick_xrsb_column(columns: list[str]) -> str | None:
    """Selecciona la columna XRS-B (canal largo, 0.1–0.8 nm) por puntuación heurística.

    Portado de goes_overlay._goes_channel_score() de Sahan.
    """
    best, best_score = None, -10_000
    for col in columns:
        lowered = str(col).strip().lower()
        if not lowered:
            continue
        score = 0
        if lowered == "xrsb_flux":
            score += 160
        if lowered == "b_flux":
            score += 150
        if any(tok in lowered for tok in ("xrsb", "long", "1.0", "8.0")):
            score += 60
        if lowered.startswith("b_"):
            score += 15
        if "flux" in lowered:
            score += 80
        if lowered.endswith("_flux"):
            score += 20
        if any(tok in lowered for tok in ("flag", "quality", "count", "num", "primary", "excluded")):
            score -= 220
        if any(tok in lowered for tok in ("electron", "current")):
            score -= 160
        if score > best_score:
            best, best_score = str(col), score
    return best if best_score > 0 else None


def _fetch_goes_xrsb_sync(date_str: str) -> dict:
    """Descarga XRS-B de GOES vía sunpy.net.Fido para una fecha completa UTC.

    Devuelve {"times": [...iso8601], "xrsb": [...W/m²], "satellite": int}.
    """
    try:
        from sunpy.net import Fido, attrs as a
        from sunpy import timeseries as ts
    except ImportError as exc:
        raise RuntimeError(
            f"sunpy no está instalado en el backend ({exc}). "
            "Instala con: pip install 'sunpy[net,timeseries]'"
        )

    target = datetime.strptime(date_str, "%Y-%m-%d")
    start = target.strftime("%Y-%m-%d 00:00:00")
    end = target.strftime("%Y-%m-%d 23:59:59")
    os.makedirs(_GOES_CACHE_DIR, exist_ok=True)

    sats = _preferred_goes_satellites(target.year)
    last_err: Exception | None = None

    for sat in sats:
        try:
            logger.info("Buscando GOES-%d XRS para %s en archivo SunPy…", sat, date_str)
            try:
                query = Fido.search(
                    a.Time(start, end),
                    a.Instrument.xrs,
                    a.goes.SatelliteNumber(sat),
                )
            except AttributeError:
                # API alternativa más antigua
                query = Fido.search(
                    a.Time(start, end),
                    a.Instrument("XRS"),
                    a.goes.SatelliteNumber(sat),
                )
            if len(query) == 0 or sum(len(t) for t in query) == 0:
                continue

            paths = Fido.fetch(query, path=os.path.join(_GOES_CACHE_DIR, "{file}"))
            if len(paths) == 0:
                continue

            tseries = ts.TimeSeries(list(paths), concatenate=True)
            df = tseries.to_dataframe()
            numeric_cols = [c for c in df.columns if np.issubdtype(df[c].dtype, np.number)]
            if not numeric_cols:
                continue

            col_b = _pick_xrsb_column(numeric_cols) or numeric_cols[-1]
            flux = np.asarray(df[col_b].values, dtype=float)

            idx = df.index
            times_py = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else list(idx)

            out_times: list[str] = []
            out_flux: list[float] = []
            for t, f in zip(times_py, flux):
                if not np.isfinite(f) or f <= 0.0:
                    continue
                if hasattr(t, "tzinfo") and t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                if not (target.date() == t.date() if hasattr(t, "date") else True):
                    continue
                ms = t.microsecond // 1000 if hasattr(t, "microsecond") else 0
                out_times.append(f"{t.strftime('%Y-%m-%dT%H:%M:%S')}.{ms:03d}Z")
                out_flux.append(float(f))

            if out_times:
                logger.info("GOES-%d XRS: %d muestras válidas", sat, len(out_times))
                return {"times": out_times, "xrsb": out_flux, "satellite": sat}
        except Exception as exc:
            logger.debug("GOES-%d falló: %s", sat, exc)
            last_err = exc
            continue

    raise RuntimeError(
        f"No se encontraron datos GOES/XRS para {date_str}"
        + (f" ({last_err})" if last_err else "")
    )


@app.get("/api/goes", response_model=GoesResponse)
async def get_goes(date: str = Query(..., description="Fecha YYYY-MM-DD")):
    """Devuelve el flujo GOES XRS-B (canal 0.1–0.8 nm) para el día UTC completo.

    Fuente: archivo SunPy/Fido (NOAA NGDC / NCEI). Funciona desde 1986
    aproximadamente y cubre todas las generaciones de satélites GOES.
    """
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Formato de fecha inválido: '{date}'")

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(_GOES_EXECUTOR, _fetch_goes_xrsb_sync, date)
    except Exception as exc:
        logger.warning("GOES no disponible para %s: %s", date, exc)
        return GoesResponse(
            date=date,
            available=False,
            reason=str(exc),
            times=[],
            xrsb=[],
            satellite=None,
        )

    return GoesResponse(
        date=date,
        available=True,
        reason="",
        times=result["times"],
        xrsb=result["xrsb"],
        satellite=result.get("satellite"),
    )


# uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
