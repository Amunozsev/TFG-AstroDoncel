"""
AstroDoncel API — backend FastAPI para espectrogramas e-Callisto.
"""

from __future__ import annotations

import glob
import html
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError

import numpy as np
from astropy.io import fits
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from scipy.ndimage import median_filter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AstroDoncel API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Carpeta local: ../data/ relativa a este archivo
DATA_DIR_LOCAL = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data")
)
# Carpeta NAS (producción)
ECALLISTO_DATA_DIR = os.environ.get(
    "ECALLISTO_DATA_DIR", "/var/services/web/ecallistodata"
)
# Servidor de archivo e-Callisto (ETHZ)
ETHZ_BASE_URL = "http://soleil.i4ds.ch/solarradio/data/2.0Hz"


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


class GoesResponse(BaseModel):
    date: str
    available: bool
    reason: str
    times: list[str]       # HH:MM:SS, mismo formato que time_axis
    flux: list[float]      # W/m² canal 0.1–0.8 nm


# ── Helpers de I/O ───────────────────────────────────────────────────────────

def _open_fits(path: str):
    """Abre un archivo FITS (soporta .fit, .fits, .fit.gz, .fits.gz)."""
    try:
        return fits.open(path, memmap=False)
    except Exception as exc:
        logger.error("Error al abrir %s: %s", path, exc)
        raise HTTPException(status_code=500, detail=f"No se pudo abrir el archivo FITS: {exc}")


def _find_local_fits_file(station: str) -> str | None:
    """Busca el primer .fit.gz de la estación en ../data/ (desarrollo local)."""
    if not os.path.isdir(DATA_DIR_LOCAL):
        return None
    for ext in (".fit.gz", ".fits.gz", ".fit", ".fits"):
        matches = glob.glob(os.path.join(DATA_DIR_LOCAL, f"*{station}*{ext}"))
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
        matches = glob.glob(os.path.join(date_dir, f"*{station}*{ext}"))
        if matches:
            return sorted(matches)[0]
    return None


def _download_from_ethz(station: str, date: str) -> str | None:
    """Descarga el primer .fit.gz de la estación desde el archivo ETHZ (soleil.i4ds.ch).

    Estrategia de Sahan: inspeccionar el índice de directorio HTTP y descargar
    el primer archivo que coincida. El archivo se guarda en DATA_DIR_LOCAL para
    ser reutilizado en llamadas futuras.
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

    # Extraer href de archivos FITS que coincidan con la estación
    candidates = re.findall(r'href="([^"]+\.fit(?:\.gz)?)"', page, re.IGNORECASE)
    station_upper = station.upper()
    matches = sorted(
        [c for c in candidates if station_upper in html.unescape(c).upper()]
    )
    if not matches:
        logger.warning("No hay archivos de %s en ETHZ para %s", station, date)
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


# ── Helpers de extracción de ejes ────────────────────────────────────────────

def _col_to_1d(col) -> np.ndarray | None:
    """Extrae un array 1D a partir de una columna de tabla FITS BIN."""
    if col is None:
        return None
    try:
        arr = np.asarray(col, dtype=float)
    except Exception:
        return None
    if arr.ndim == 0:
        return None
    if arr.ndim == 1:
        return arr
    return arr[0].ravel()


def _extract_axes(hdul) -> tuple[np.ndarray, np.ndarray]:
    """Extrae ejes temporal (s desde inicio de observación) y de frecuencia (MHz)."""
    header = hdul[0].header
    data = hdul[0].data
    n_freq, n_time = data.shape

    time_arr: np.ndarray | None = None
    freq_arr: np.ndarray | None = None

    # Intento 1: HDU[1] → TIME, HDU[2] → FREQUENCY
    if len(hdul) > 1:
        try:
            t = hdul[1].data
            if t is not None:
                time_arr = _col_to_1d(t["TIME"])
        except Exception as exc:
            logger.debug("TIME no en HDU[1]: %s", exc)

    if len(hdul) > 2:
        try:
            f = hdul[2].data
            if f is not None:
                freq_arr = _col_to_1d(f["FREQUENCY"])
        except Exception as exc:
            logger.debug("FREQUENCY no en HDU[2]: %s", exc)

    # Intento 2: buscar en todos los HDUs (caso común: ambos en HDU[1])
    for hdu in hdul[1:]:
        if time_arr is not None and freq_arr is not None:
            break
        try:
            table = hdu.data
            if table is None:
                continue
            names = {str(n).upper() for n in (getattr(table, "names", None) or [])}
            if time_arr is None and "TIME" in names:
                time_arr = _col_to_1d(table["TIME"])
            if freq_arr is None and "FREQUENCY" in names:
                freq_arr = _col_to_1d(table["FREQUENCY"])
        except Exception:
            continue

    # Fallback linspace
    if time_arr is None:
        logger.warning("Eje temporal no encontrado; usando linspace")
        t0 = _header_ut_seconds(header)
        time_arr = np.linspace(0.0, 14.0 * 60.0, n_time)

    if freq_arr is None:
        logger.warning("Eje de frecuencias no encontrado; usando linspace")
        f_min = float(header.get("FREQMIN", 45.0))
        f_max = float(header.get("FREQMAX", 400.0))
        freq_arr = np.linspace(f_max, f_min, n_freq)

    return time_arr.ravel(), freq_arr.ravel()


def _header_ut_seconds(header) -> float:
    """Extrae TIME-OBS como segundos desde medianoche."""
    try:
        t = str(header.get("TIME-OBS", "00:00:00")).strip()
        hh, mm, ss = t.split(":")
        return int(hh) * 3600 + int(mm) * 60 + float(ss)
    except Exception:
        return 0.0


def _times_to_utc(time_arr: np.ndarray, header) -> list[str]:
    """Convierte el vector de offsets (s) a etiquetas HH:MM:SS UTC.

    El TIME del FITS BIN es relativo al inicio del archivo; se suma TIME-OBS
    para obtener la hora UTC absoluta.
    """
    t0 = _header_ut_seconds(header)
    labels = []
    for t in time_arr:
        total = float(t) + t0
        h = int(total // 3600) % 24
        m = int(total % 3600) // 60
        s = int(total % 60)
        labels.append(f"{h:02d}:{m:02d}:{s:02d}")
    return labels


# ── Helpers de procesamiento ─────────────────────────────────────────────────

def _subtract_background(data: np.ndarray) -> np.ndarray:
    """Sustracción básica: resta la mediana de cada canal de frecuencia."""
    fondo = np.nanmedian(data, axis=1, keepdims=True)
    return data.astype(np.float32) - fondo.astype(np.float32)


def _clean_rfi(data: np.ndarray) -> np.ndarray:
    """Limpieza RFI inspirada en el algoritmo de Sahan (rfi_filters + noise_reduction).

    Pipeline:
    1. Filtro mediana 2D 3×3 — elimina picos RFI puntuales tiempo/frecuencia.
    2. Sustracción de fondo robusto — percentil 25 de cada canal de frecuencia
       (más robusto que la mediana ante emisión solar intensa).
    3. No se aplica ecualización de ruido (eso es Sprint 3 con RFI Toolkit completo).
    """
    arr = np.array(data, dtype=np.float32)

    # 1. Filtro mediana 2D
    filtered = median_filter(arr, size=(3, 3), mode="nearest").astype(np.float32)

    # 2. Fondo robusto: percentil 25 por canal de frecuencia (eje temporal)
    bg = np.nanpercentile(filtered, 25.0, axis=1, keepdims=True).astype(np.float32)
    cleaned = filtered - bg

    return cleaned.astype(np.float32)


def _percentile_clip(data: np.ndarray) -> tuple[float, float]:
    """Calcula vmin (p2) y vmax (p99.5) para la escala de color."""
    vmin = float(np.nanpercentile(data, 2))
    vmax = float(np.nanpercentile(data, 99.5))
    return vmin, vmax


def _header_to_dict(header) -> dict:
    """Convierte un header FITS a diccionario JSON-serializable."""
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
    """Comprobación de salud del servicio."""
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/spectrogram", response_model=SpectrogramResponse)
def get_spectrogram(
    station: str = Query(..., description="Estación e-Callisto, ej. SPAIN-SIGUENZA"),
    date: str = Query(..., description="Fecha de observación, formato YYYY-MM-DD"),
    file_path: str = Query(default=None, description="Ruta absoluta (override manual)"),
    sahan_filter: bool = Query(default=False, description="Aplica limpieza RFI avanzada (Sahan)"),
):
    """Devuelve el espectrograma de una estación e-Callisto.

    Orden de resolución:
    1. file_path explícito (override)
    2. ../data/ local (desarrollo)
    3. NAS estructurado por fecha (producción)
    4. Descarga automática desde archivo ETHZ (soleil.i4ds.ch)
    """
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Formato de fecha inválido: '{date}'")

    # Resolver ruta
    if file_path:
        if not os.path.isfile(file_path):
            raise HTTPException(status_code=404, detail=f"Archivo no encontrado: {file_path}")
        fits_path = file_path
        logger.info("Usando file_path explícito: %s", fits_path)
    else:
        fits_path = (
            _find_local_fits_file(station)
            or _find_nas_fits_file(station, date)
            or _download_from_ethz(station, date)
        )
        if not fits_path:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No se encontró ningún archivo para '{station}' en {date}. "
                    "Comprueba que el NAS esté montado o que el servidor ETHZ sea accesible."
                ),
            )

    logger.info("Procesando %s", fits_path)

    try:
        with _open_fits(fits_path) as hdul:
            raw_data = hdul[0].data
            if raw_data is None:
                raise HTTPException(status_code=500, detail="HDU[0] no contiene imagen.")

            data = np.array(raw_data, dtype=np.float32)
            header = hdul[0].header
            time_arr, freq_arr = _extract_axes(hdul)
            time_labels = _times_to_utc(time_arr, header)

            # Procesamiento según modo
            if sahan_filter:
                data = _clean_rfi(data)
                logger.info("Filtro Sahan (RFI cleaning) aplicado")
            # Sin filtro: datos crudos con vmin/vmax adaptativos

            vmin, vmax = _percentile_clip(data)
            data_clean = np.nan_to_num(data, nan=0.0, posinf=vmax, neginf=vmin)

            return SpectrogramResponse(
                station=station,
                date=date,
                filename=os.path.basename(fits_path),
                time_axis=time_labels,
                freq_axis=[round(float(f), 3) for f in freq_arr],
                z=[[round(float(v), 4) for v in row] for row in data_clean.tolist()],
                vmin=round(vmin, 4),
                vmax=round(vmax, 4),
                fits_header=_header_to_dict(header),
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error inesperado procesando %s", fits_path)
        raise HTTPException(status_code=500, detail=f"Error al procesar FITS: {exc}")


@app.get("/api/goes", response_model=GoesResponse)
def get_goes(date: str = Query(..., description="Fecha YYYY-MM-DD")):
    """Devuelve el flujo GOES XRS (canal 0.1–0.8 nm) para una fecha.

    Fuente: NOAA SWPC JSON API (gratuita, sin autenticación).
    Cobertura: últimos 7 días. Para datos más antiguos devuelve available=False.
    """
    try:
        target_dt = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Formato de fecha inválido: '{date}'")

    # Comprobar si la fecha está dentro de la ventana de 7 días de NOAA SWPC
    now_utc = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    days_ago = (now_utc - target_dt).days
    if days_ago > 7:
        return GoesResponse(
            date=date,
            available=False,
            reason=f"Datos GOES solo disponibles para los últimos 7 días vía NOAA SWPC. "
                   f"Para {date} (hace {days_ago} días) se necesitaría el archivo NGDC (Sprint 3).",
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

    # Filtrar por fecha y canal largo (0.1–0.8 nm = clasificación B/C/M/X)
    target_prefix = date  # "YYYY-MM-DD"
    records = [
        row for row in raw
        if str(row.get("time_tag", "")).startswith(target_prefix)
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

    # Convertir time_tag "YYYY-MM-DD HH:MM:SS" → "HH:MM:SS"
    times_out = []
    flux_out = []
    for row in records:
        tag = str(row.get("time_tag", ""))
        flux = row.get("flux") or row.get("observed_flux", 0.0)
        if not tag or flux is None:
            continue
        hms = tag[11:19] if len(tag) >= 19 else tag
        times_out.append(hms)
        flux_out.append(float(flux))

    return GoesResponse(
        date=date,
        available=True,
        reason="",
        times=times_out,
        flux=flux_out,
    )


# uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
