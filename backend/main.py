"""
AstroDoncel API — backend FastAPI para espectrogramas e-Callisto.
"""

from __future__ import annotations

import glob
import logging
import os
from datetime import datetime

import numpy as np
from astropy.io import fits
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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

# Carpeta local de datos: ../data/ relativa a este archivo (funciona en Windows y Mac)
DATA_DIR_LOCAL = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data")
)

# Carpeta NAS (producción): configurable por variable de entorno
ECALLISTO_DATA_DIR = os.environ.get(
    "ECALLISTO_DATA_DIR", "/var/services/web/ecallistodata"
)


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


# ---------------------------------------------------------------------------
# Helpers de I/O
# ---------------------------------------------------------------------------


def _open_fits(path: str):
    """Abre un archivo FITS (soporta .fit, .fits, .fit.gz, .fits.gz)."""
    try:
        return fits.open(path, memmap=False)
    except Exception as exc:
        logger.error("Error al abrir %s: %s", path, exc)
        raise HTTPException(
            status_code=500,
            detail=f"No se pudo abrir el archivo FITS: {exc}",
        )


def _find_local_fits_file(station: str) -> str | None:
    """Busca el primer .fit/.fit.gz de la estación en la carpeta local ../data/.

    Usa glob con rutas relativas al propio archivo main.py para evitar
    rutas hardcodeadas que fallen entre Windows y Mac.
    """
    if not os.path.isdir(DATA_DIR_LOCAL):
        logger.debug("Carpeta local de datos no encontrada: %s", DATA_DIR_LOCAL)
        return None
    for ext in (".fit.gz", ".fits.gz", ".fit", ".fits"):
        matches = glob.glob(os.path.join(DATA_DIR_LOCAL, f"*{station}*{ext}"))
        if matches:
            return sorted(matches)[0]
    return None


def _find_nas_fits_file(station: str, date: str) -> str:
    """Localiza el primer archivo FITS de la estación en el directorio NAS de fecha."""
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Formato de fecha inválido: '{date}'. Use YYYY-MM-DD.",
        )

    date_dir = os.path.join(
        ECALLISTO_DATA_DIR,
        dt.strftime("%Y"),
        dt.strftime("%m"),
        dt.strftime("%d"),
    )

    if not os.path.isdir(date_dir):
        raise HTTPException(
            status_code=404,
            detail=f"No existe el directorio de datos para {date}: {date_dir}",
        )

    for ext in (".fit.gz", ".fits.gz", ".fit", ".fits"):
        matches = glob.glob(os.path.join(date_dir, f"*{station}*{ext}"))
        if matches:
            return sorted(matches)[0]

    raise HTTPException(
        status_code=404,
        detail=f"No se encontraron archivos FITS para '{station}' en {date_dir}",
    )


# ---------------------------------------------------------------------------
# Helpers de extracción de ejes
# ---------------------------------------------------------------------------


def _col_to_1d(col) -> np.ndarray | None:
    """Extrae un array 1D a partir de una columna de tabla FITS BIN.

    Las tablas e-Callisto tienen 1 fila que contiene el array completo,
    por lo que col puede ser de shape (1, N) o (N,).
    """
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
    """Extrae los ejes temporales (s desde medianoche UTC) y de frecuencia (MHz).

    Estrategia:
    1. HDU[1] para TIME, HDU[2] para FREQUENCY.
    2. Fallback: buscar en todos los HDUs (caso real: ambos en HDU[1]).
    3. Fallback final: np.linspace.
    """
    header = hdul[0].header
    data = hdul[0].data
    n_freq, n_time = data.shape

    time_arr: np.ndarray | None = None
    freq_arr: np.ndarray | None = None

    if len(hdul) > 1:
        try:
            table = hdul[1].data
            if table is not None:
                time_arr = _col_to_1d(table["TIME"])
        except Exception as exc:
            logger.debug("TIME no encontrado en HDU[1]: %s", exc)

    if len(hdul) > 2:
        try:
            table = hdul[2].data
            if table is not None:
                freq_arr = _col_to_1d(table["FREQUENCY"])
        except Exception as exc:
            logger.debug("FREQUENCY no encontrado en HDU[2]: %s", exc)

    for hdu in hdul[1:]:
        if time_arr is not None and freq_arr is not None:
            break
        try:
            table = hdu.data
            if table is None:
                continue
            names_upper = {str(n).upper() for n in (getattr(table, "names", None) or [])}
            if time_arr is None and "TIME" in names_upper:
                time_arr = _col_to_1d(table["TIME"])
            if freq_arr is None and "FREQUENCY" in names_upper:
                freq_arr = _col_to_1d(table["FREQUENCY"])
        except Exception:
            continue

    if time_arr is None:
        logger.warning("Eje temporal no encontrado en tablas BIN; usando linspace")
        time_start = _header_ut_seconds(header)
        time_arr = np.linspace(time_start, time_start + 14.0 * 60.0, n_time)

    if freq_arr is None:
        logger.warning("Eje de frecuencias no encontrado en tablas BIN; usando linspace")
        f_min = float(header.get("FREQMIN", 45.0))
        f_max = float(header.get("FREQMAX", 400.0))
        freq_arr = np.linspace(f_max, f_min, n_freq)

    return time_arr.ravel(), freq_arr.ravel()


def _header_ut_seconds(header) -> float:
    """Extrae TIME-OBS de la cabecera como segundos desde medianoche."""
    try:
        t = str(header.get("TIME-OBS", "00:00:00")).strip()
        hh, mm, ss = t.split(":")
        return int(hh) * 3600 + int(mm) * 60 + float(ss)
    except Exception:
        return 0.0


def _times_to_utc(time_arr: np.ndarray, header) -> list[str]:
    """Convierte el vector de tiempos a etiquetas HH:MM:SS UTC.

    El TIME del FITS BIN contiene segundos relativos al inicio del archivo,
    no segundos absolutos desde medianoche. Hay que sumarle TIME-OBS.
    """
    t0 = _header_ut_seconds(header)  # segundos desde medianoche = TIME-OBS
    labels = []
    for t in time_arr:
        total = float(t) + t0
        h = int(total // 3600) % 24
        m = int(total % 3600) // 60
        s = int(total % 60)
        labels.append(f"{h:02d}:{m:02d}:{s:02d}")
    return labels


# ---------------------------------------------------------------------------
# Helpers de procesamiento
# ---------------------------------------------------------------------------


def _subtract_background(data: np.ndarray) -> np.ndarray:
    """Resta la mediana de cada canal de frecuencia a lo largo del eje temporal."""
    fondo = np.nanmedian(data, axis=1, keepdims=True)
    return data.astype(np.float32) - fondo.astype(np.float32)


def _percentile_clip(data: np.ndarray) -> tuple[float, float]:
    """Calcula vmin y vmax como percentiles 2 % y 99.5 % para la escala de color."""
    vmin = float(np.nanpercentile(data, 2))
    vmax = float(np.nanpercentile(data, 99.5))
    return vmin, vmax


def _header_to_dict(header) -> dict:
    """Convierte un header FITS a un diccionario JSON-serializable."""
    result: dict = {}
    for key, value in header.items():
        if key in ("COMMENT", "HISTORY", ""):
            continue
        try:
            result[key] = value if isinstance(value, (int, float, str, bool)) else str(value)
        except Exception:
            result[key] = str(value)
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health():
    """Comprobación de salud del servicio."""
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/spectrogram", response_model=SpectrogramResponse)
def get_spectrogram(
    station: str = Query(..., description="Estación e-Callisto, ej. SPAIN-SIGUENZA"),
    date: str = Query(..., description="Fecha de observación, formato YYYY-MM-DD"),
    file_path: str = Query(default=None, description="Ruta absoluta a .fit/.fit.gz (override manual)"),
    sahan_filter: bool = Query(default=False, description="Aplica sustracción de fondo por mediana de canal"),
):
    """Devuelve el espectrograma de una estación e-Callisto para una fecha dada.

    Orden de resolución del archivo:
    1. file_path explícito (override manual)
    2. Carpeta local ../data/ (desarrollo sin NAS)
    3. NAS estructurado por fecha (producción)
    """
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Formato de fecha inválido: '{date}'. Use YYYY-MM-DD.",
        )

    # Resolver ruta del archivo FITS
    if file_path:
        fits_path = file_path
        if not os.path.isfile(fits_path):
            raise HTTPException(status_code=404, detail=f"Archivo no encontrado: {fits_path}")
        logger.info("Usando file_path explícito: %s", fits_path)
    else:
        local = _find_local_fits_file(station)
        if local:
            fits_path = local
            logger.info("Archivo local encontrado: %s", fits_path)
        else:
            fits_path = _find_nas_fits_file(station, date)
            logger.info("Archivo NAS encontrado: %s", fits_path)

    try:
        with _open_fits(fits_path) as hdul:
            raw_data = hdul[0].data
            if raw_data is None:
                raise HTTPException(status_code=500, detail="HDU[0] no contiene datos de imagen.")

            data = np.array(raw_data, dtype=np.float32)
            header = hdul[0].header

            time_arr, freq_arr = _extract_axes(hdul)
            time_labels = _times_to_utc(time_arr, header)

            # Filtro Sahan: sustracción de fondo solo si se solicita
            if sahan_filter:
                data = _subtract_background(data)
                logger.info("Filtro Sahan aplicado")

            vmin, vmax = _percentile_clip(data)
            # Limpiar NaN e infinitos antes de serializar
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
        raise HTTPException(
            status_code=500,
            detail=f"Error al procesar el archivo FITS: {exc}",
        )


# uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
