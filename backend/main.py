"""
AstroDoncel API — backend FastAPI para espectrogramas e-CALLISTO.
Motor científico portado de e-CALLISTO FITS Analyzer (Sahan S Liyanage, v2.4.1).
"""

from __future__ import annotations

import glob
import html
import json
import logging
import os
import re
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
ETHZ_BASE_URL = "http://soleil.i4ds.ch/solarradio/data/2.0Hz"

# Lista estática de respaldo — estaciones reales de la red e-Callisto
_STATIONS_FALLBACK: list[str] = sorted([
    "AFRICA-AGADIR",
    "ALASKA-ANCHORAGE",
    "ALASKA-FAIRBANKS",
    "ALASKA-HAARP",
    "ALASKA-JUNEAU",
    "ALASKA-KODIAK",
    "ARGENTINA",
    "AUSTRALIA-MURRIYANG",
    "AUSTRIA-GRAZ",
    "AUSTRIA-MONDSEE",
    "AUSTRIA-OE5XHQ",
    "AUSTRIA-ZELL",
    "BANGLADESH",
    "BIR",
    "CANADA-PENTICTON",
    "CHILE-SANTIAGO",
    "CHINA-NRAO",
    "CZ-ONDREJOV",
    "EGYPT",
    "ETHIOPIA",
    "FINLAND",
    "FRANCE-NANCAY",
    "GERMANY-TREMSDORF",
    "GREENLAND",
    "GUATEMALA",
    "HUMAIN",
    "INDIA-GAURIBIDANUR",
    "INDIA-PUNE",
    "INDONESIA-PARI",
    "ISRAEL",
    "ITALY-CATANIA",
    "JAPAN-IBARAKI",
    "KASI",
    "KENYA",
    "LEARMONTH",
    "MALAYSIA",
    "MAURITIUS",
    "MEXICO-UNAM",
    "MONGOLIA",
    "NAMIBIA",
    "NEW-ZEALAND",
    "NIGERIA",
    "NORWAY",
    "PAKISTAN-PESHAWAR",
    "PERU-ICA",
    "PHOENIX",
    "PORTUGAL",
    "ROMANIA",
    "RUSSIA-SSRT",
    "SCOTLAND",
    "SOUTH-AFRICA-HartRAO",
    "SPAIN-PERALEJOS",
    "SPAIN-SIGUENZA",
    "SSRT",
    "SWISS-LANDSCHLACHT",
    "SWISS-WOLLERAU",
    "TAIWAN-NJIT",
    "TURKEY-ISTANBUL",
    "UK",
    "UKRAINE",
])


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
    flux: list[float]


class StationsResponse(BaseModel):
    stations: list[str]
    source: str


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


def _download_from_ethz(station: str, date: str) -> str | None:
    """Descarga el primer archivo FITS de la estación desde el archivo ETHZ.

    Estrategia (portada de sunpy_archive.py / fits_io.py de Sahan):
    1. Inspecciona el índice HTTP del directorio de la fecha.
    2. Busca primero por coincidencia exacta de prefijo STATION_YYYYMMDD_,
       luego por substring como fallback.
    3. Guarda en DATA_DIR_LOCAL para reusar en llamadas futuras.
    """
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return None

    dir_url = f"{ETHZ_BASE_URL}/{dt.strftime('%Y/%m/%d')}/"
    logger.info("Consultando archivo ETHZ: %s", dir_url)

    try:
        req = Request(dir_url, headers={"User-Agent": "AstroDoncel/1.0"})
        with urlopen(req, timeout=15) as resp:
            page = resp.read().decode("utf-8", errors="replace")
    except URLError as exc:
        logger.warning("No se pudo acceder al archivo ETHZ: %s", exc)
        return None

    # Coincidencia exacta de prefijo: STATION_YYYYMMDD_HHMMSS_NN.fit[.gz]
    date_str = dt.strftime("%Y%m%d")
    prefix_re = re.compile(
        r'href="(' + re.escape(station.upper()) + r'_' + date_str + r'_\d{6}_\d{2}\.fit(?:\.gz)?)"',
        re.IGNORECASE,
    )
    matches = sorted(set(prefix_re.findall(page)))

    if not matches:
        # Fallback: substring (cubre variaciones menores de nombre)
        all_files = re.findall(r'href="([^"]+\.fit(?:\.gz)?)"', page, re.IGNORECASE)
        matches = sorted(
            c for c in all_files if station.upper() in html.unescape(c).upper()
        )

    if not matches:
        logger.warning("No hay archivos de '%s' en ETHZ para %s", station, date)
        return None

    filename = matches[0]
    file_url = dir_url + filename
    os.makedirs(DATA_DIR_LOCAL, exist_ok=True)
    local_path = os.path.join(DATA_DIR_LOCAL, filename)

    if os.path.isfile(local_path):
        logger.info("Archivo ya en caché: %s", local_path)
        return local_path

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

def _header_ut_seconds(header) -> float:
    """Extrae TIME-OBS como segundos desde medianoche UTC."""
    try:
        t = str(header.get("TIME-OBS", "00:00:00")).strip()
        hh, mm, ss = t.split(":")
        return int(hh) * 3600 + int(mm) * 60 + float(ss)
    except Exception:
        return 0.0


def _times_to_utc(time_arr: np.ndarray, header) -> list[str]:
    """Convierte offsets en segundos a etiquetas HH:MM:SS UTC."""
    t0 = _header_ut_seconds(header)
    labels = []
    for t in time_arr:
        total = float(t) + t0
        h = int(total // 3600) % 24
        m = int(total % 3600) // 60
        s = int(total % 60)
        labels.append(f"{h:02d}:{m:02d}:{s:02d}")
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


def _percentile_clip_global(data: np.ndarray, lo: float = 2.0, hi: float = 99.5) -> tuple[float, float]:
    """Calcula vmin (percentil lo) y vmax (percentil hi) sobre todos los datos."""
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


@app.get("/api/spectrogram", response_model=SpectrogramResponse)
def get_spectrogram(
    station: str = Query(..., description="Estación e-Callisto, ej. SPAIN-SIGUENZA"),
    date: str = Query(..., description="Fecha de observación, formato YYYY-MM-DD"),
    file_path: str = Query(default=None, description="Ruta absoluta (override manual)"),
    sahan_filter: bool = Query(default=False, description="Aplica limpieza RFI completa"),
):
    """Devuelve el espectrograma de una estación e-Callisto.

    Orden de resolución: 1) file_path explícito, 2) ../data/ local, 3) NAS, 4) ETHZ.

    Pipeline de procesamiento:
    - Siempre: sustracción de fondo robusta (percentil 25 por canal de frecuencia).
    - Si sahan_filter=true: además aplica limpieza RFI completa (detección de canales
      calientes + reparación + recorte de outliers).
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


@app.get("/api/goes", response_model=GoesResponse)
def get_goes(date: str = Query(..., description="Fecha YYYY-MM-DD")):
    """Devuelve el flujo GOES XRS (canal 0.1–0.8 nm) para una fecha.

    Fuente: NOAA SWPC JSON API. Solo cubre los últimos 7 días.
    """
    try:
        target_dt = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Formato de fecha inválido: '{date}'")

    now_utc = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    days_ago = (now_utc - target_dt).days
    if days_ago > 7:
        return GoesResponse(
            date=date,
            available=False,
            reason=(
                f"Datos GOES solo disponibles para los últimos 7 días vía NOAA SWPC. "
                f"Para {date} (hace {days_ago} días) se necesitaría el archivo NGDC."
            ),
            times=[],
            flux=[],
        )

    noaa_url = "https://services.swpc.noaa.gov/json/goes/primary/xrays-7-day.json"
    logger.info("Obteniendo datos GOES de %s", noaa_url)

    try:
        req = Request(noaa_url, headers={"User-Agent": "AstroDoncel/1.0"})
        with urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"No se pudo acceder a NOAA SWPC: {exc}")

    records = [
        row for row in raw
        if str(row.get("time_tag", "")).startswith(date)
        and str(row.get("energy", "")).startswith("0.1")
    ]

    if not records:
        return GoesResponse(
            date=date,
            available=False,
            reason="No hay registros GOES para esa fecha en la ventana actual de NOAA SWPC.",
            times=[],
            flux=[],
        )

    times_out, flux_out = [], []
    for row in records:
        tag = str(row.get("time_tag", ""))
        flux = row.get("flux") or row.get("observed_flux", 0.0)
        if not tag or flux is None:
            continue
        hms = tag[11:19] if len(tag) >= 19 else tag
        times_out.append(hms)
        flux_out.append(float(flux))

    return GoesResponse(date=date, available=True, reason="", times=times_out, flux=flux_out)


# uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
