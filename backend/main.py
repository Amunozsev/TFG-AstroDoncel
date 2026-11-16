"""
AstroDoncel Studio API — FastAPI backend for e-CALLISTO spectrograms.
Scientific engine adapted from e-CALLISTO FITS Analyzer (Sahan S. Liyanage, through v2.8.0).
"""

from __future__ import annotations

import asyncio
import glob
import html
import json
import logging
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
from astropy.io import fits
from fastapi import FastAPI, HTTPException, Query
from fastapi import Request as FastAPIRequest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend import catalog, catalog_mysql, processing
from backend.api_features import router as feature_router
from backend.db import FitsFile, GoesDay, Station, init_db, session_scope
from backend.observation import Observation, ObservationError, join_blocks
from backend.security import (
    fits_focus_code,
    safe_join,
    validate_date,
    validate_filename_context,
    validate_observation_filenames,
    validate_station,
)
from backend.timeutil import as_utc, iso_ms, parse_utc
from backend.version import APP_NAME, APP_VERSION

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
USER_AGENT = f"{APP_NAME.replace(' ', '-')}/{APP_VERSION}"


async def _background_catalog_sync() -> None:
    """Refresh the current authoritative UAH month without blocking requests."""
    interval = max(1.0, float(os.environ.get("BURST_SOURCE_REFRESH_MINUTES", "60"))) * 60
    while True:
        now = datetime.now(timezone.utc)
        try:
            await asyncio.to_thread(
                catalog.ingest_month,
                now.year,
                now.month,
                source=catalog_mysql.SOURCE_ID,
                force=True,
            )
        except Exception as exc:
            logger.warning("Background UAH catalogue refresh failed: %s", exc)
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Prepare mandatory local state before accepting traffic."""
    os.makedirs(DATA_DIR_LOCAL, exist_ok=True)
    Path(DATA_DIR_LOCAL, ".astrodoncel-cache").touch(exist_ok=True)
    os.makedirs(os.environ.get("TASK_RESULT_DIR", os.path.join("data", "task_results")), exist_ok=True)
    init_db()
    sync_task = None
    if catalog.DEFAULT_CATALOG_SOURCE == catalog_mysql.SOURCE_ID and catalog_mysql.is_configured():
        sync_task = asyncio.create_task(_background_catalog_sync(), name="uah-catalog-sync")
    try:
        yield
    finally:
        if sync_task:
            sync_task.cancel()
            with suppress(asyncio.CancelledError):
                await sync_task


app = FastAPI(title=f"{APP_NAME} API", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
app.include_router(feature_router)


@app.middleware("http")
async def request_observability(request: FastAPIRequest, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))[:64]
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    response.headers["X-Request-ID"] = request_id
    response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    logger.info("request id=%s method=%s path=%s status=%s duration_ms=%.1f", request_id, request.method, request.url.path, response.status_code, elapsed_ms)
    return response


_configured_origins = os.environ.get("FRONTEND_ORIGINS", "")
app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        [origin.strip().rstrip("/") for origin in _configured_origins.split(",") if origin.strip()]
        if _configured_origins.strip()
        else ["http://localhost:5173", "http://127.0.0.1:5173"]
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR_LOCAL = os.path.normpath(
    os.environ.get(
        "DATA_DIR_LOCAL",
        os.path.join(os.path.dirname(__file__), "..", "data"),
    )
)
ECALLISTO_DATA_DIR = os.environ.get(
    "ECALLISTO_DATA_DIR", "/var/services/web/ecallistodata"
)
ETHZ_BASE_URL = "http://soleil.i4ds.ch/solarradio/data/2002-20yy_Callisto"
_DOWNLOAD_LOCKS: dict[str, threading.Lock] = {}
_DOWNLOAD_LOCKS_GUARD = threading.Lock()
_MAX_IDLE_LOCKS = 1024


def _prune_idle_locks(locks: dict[str, threading.Lock]) -> None:
    """Forget per-key locks nobody holds once there are many (caller holds the guard).

    The API runs for weeks, and one lock per file or day would otherwise
    accumulate forever.
    """
    if len(locks) > _MAX_IDLE_LOCKS:
        for key in [key for key, lock in locks.items() if not lock.locked()]:
            del locks[key]


# Static fallback list — 76 real stations extracted from the ETHZ archive
# (generated by scanning multiple dates from 2024-2026)
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


# Approximate geographic coordinates (latitude, longitude in degrees) for the
# e-CALLISTO network. Values are best-effort from the public station catalogue
# and are only used to place markers on the world map — precision to the city /
# observatory level is sufficient. Stations reported by ETHZ but absent here are
# still returned by /api/stations; they simply cannot be plotted.
_STATIONS_GEO: dict[str, tuple[float, float]] = {
    "ALASKA-ANCHORAGE": (61.218, -149.900),
    "ALASKA-COHOE": (60.420, -151.260),
    "ALASKA-HAARP": (62.390, -145.150),
    "ALGERIA-CRAAG": (36.800, 3.050),
    "ALMATY": (43.240, 76.910),
    "AUSTRALIA-ASSA": (-34.960, 138.600),
    "AUSTRIA-KRUMBACH": (47.510, 9.900),
    "AUSTRIA-MICHELBACH": (48.050, 15.790),
    "AUSTRIA-OE3FLB": (48.100, 15.800),
    "AUSTRIA-UNIGRAZ": (47.070, 15.440),
    "BIR": (53.090, -7.920),
    "BRAZIL": (-23.200, -45.860),
    "CROATIA-VISNJAN": (45.280, 13.720),
    "DENMARK": (55.680, 12.570),
    "EGYPT-ALEXANDRIA": (31.200, 29.920),
    "EGYPT-SPACEAGENCY": (30.030, 31.210),
    "ETHIOPIA": (9.030, 38.740),
    "FINLAND-KEMPELE": (64.910, 25.500),
    "FINLAND-RUISSALO": (60.430, 22.170),
    "FINLAND-SIUNTIO": (60.140, 24.190),
    "GERMANY-DLR": (50.850, 7.130),
    "GERMANY-ESSEN": (51.460, 7.010),
    "GLASGOW": (55.870, -4.290),
    "GREENLAND": (64.180, -51.720),
    "HUMAIN": (50.190, 5.250),
    "HURBANOVO": (47.870, 18.190),
    "INDIA-GAURI": (18.500, 73.850),
    "INDIA-OOTY": (11.410, 76.690),
    "INDIA-UDAIPUR": (24.580, 73.710),
    "INDONESIA": (-6.900, 107.600),
    "ITALY-STRASSOLT": (45.970, 13.320),
    "JAPAN-IBARAKI": (36.340, 140.450),
    "KASI": (36.400, 127.370),
    "LEARMONTH": (-22.220, 114.100),
    "MALAYSIA-BANTING": (2.820, 101.500),
    "MAURITIUS": (-20.200, 57.500),
    "MEXART": (20.360, -101.330),
    "MEXICO-ENSENADA-UNAM": (31.870, -116.670),
    "MEXICO-FCFM-UANL": (25.720, -100.310),
    "MEXICO-FCFM-UNACH": (16.750, -93.110),
    "MEXICO-LANCE": (19.700, -101.200),
    "MEXICO-LANCE-A": (19.700, -101.200),
    "MEXICO-LANCE-B": (19.700, -101.200),
    "MEXICO-UANL-INFIERNILLO": (25.500, -100.000),
    "MONGOLIA-UB": (47.920, 106.920),
    "MRO": (-26.700, 116.600),
    "MRT1": (-20.200, 57.600),
    "NASA-GSFC": (38.990, -76.840),
    "NORWAY-EGERSUND": (58.450, 5.990),
    "NORWAY-NY-AALESUND": (78.920, 11.930),
    "NORWAY-RANDABERG": (59.000, 5.600),
    "NZ-WAIRAKEI-DLR": (-38.630, 176.100),
    "PARAGUAY": (-25.300, -57.600),
    "PERU-ICA": (-14.080, -75.730),
    "PHOENIX": (47.340, 8.110),
    "POLAND-BALDY": (53.600, 20.600),
    "POLAND-GROTNIKI": (51.800, 19.300),
    "ROMANIA": (44.400, 26.100),
    "ROSWELL-NM": (33.390, -104.520),
    "RWANDA": (-1.950, 30.060),
    "SPAIN-PERALEJOS": (40.650, -1.860),
    "SPAIN-SIGUENZA": (41.070, -2.640),
    "SRI-LANKA": (6.900, 79.860),
    "SSRT": (51.750, 102.220),
    "SWISS-BLEN5M-E": (47.340, 8.110),
    "SWISS-CALU": (47.000, 8.000),
    "SWISS-FM": (47.300, 8.100),
    "SWISS-HB9SCT": (47.300, 8.000),
    "SWISS-HEITERSWIL": (47.350, 9.100),
    "SWISS-IRSOL": (46.000, 8.960),
    "SWISS-LANDSCHLACHT": (47.600, 9.200),
    "SWISS-MUHEN": (47.300, 8.060),
    "TAIWAN-NCU": (24.970, 121.190),
    "TRIEST": (45.650, 13.780),
    "TURKEY": (39.900, 32.800),
    "UNAM": (19.330, -99.180),
    "URUGUAY": (-34.900, -56.200),
    "USA-ARIZONA-ERAU": (34.610, -112.450),
    "USA-BOSTON": (42.360, -71.060),
    "UZBEKISTAN": (41.330, 69.290),
}


# ── Station coordinate registry (authoritative: from FITS headers) ────────────
# Each CALLISTO FITS file declares its own site: OBS_LAT / OBS_LAC (N|S) and
# OBS_LON / OBS_LOC (E|W). That is the real source of truth, so we harvest
# coordinates from the data itself and persist them. `_STATIONS_GEO` above is
# only a fallback used until a station's real coordinates have been learned.
_COORD_REGISTRY_PATH = os.path.join(DATA_DIR_LOCAL, "station_coords.json")
_COORD_REGISTRY: dict[str, dict] = {}
_COORD_REGISTRY_LOCK = threading.Lock()
_COORD_REGISTRY_LOADED = False
_LOCAL_HARVEST_DONE = False
_COORD_ATTEMPTS: dict[str, float] = {}       # station -> last download-harvest ts
_COORD_ATTEMPT_COOLDOWN = 6 * 3600.0         # don't re-download a failing station too often
_COORD_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="coords")


def _load_coord_registry() -> None:
    global _COORD_REGISTRY, _COORD_REGISTRY_LOADED
    with _COORD_REGISTRY_LOCK:
        if _COORD_REGISTRY_LOADED:
            return
        try:
            with open(_COORD_REGISTRY_PATH, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                _COORD_REGISTRY = loaded
        except Exception:
            _COORD_REGISTRY = {}
        _COORD_REGISTRY_LOADED = True


def _save_coord_registry() -> None:
    try:
        os.makedirs(DATA_DIR_LOCAL, exist_ok=True)
        with _COORD_REGISTRY_LOCK:
            snapshot = dict(_COORD_REGISTRY)
        tmp = _COORD_REGISTRY_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, indent=0, sort_keys=True)
        os.replace(tmp, _COORD_REGISTRY_PATH)
    except Exception as exc:
        logger.debug("Could not persist coord registry: %s", exc)


def _coords_from_header(header) -> tuple[float, float] | None:
    """Extract (lat, lon) in signed degrees from CALLISTO OBS_* header keywords."""
    try:
        lat_raw = header.get("OBS_LAT")
        lon_raw = header.get("OBS_LON")
        if lat_raw is None or lon_raw is None:
            return None
        lat = abs(float(lat_raw))
        lon = abs(float(lon_raw))
        if str(header.get("OBS_LAC", "N")).strip().upper().startswith("S"):
            lat = -lat
        if str(header.get("OBS_LOC", "E")).strip().upper().startswith("W"):
            lon = -lon
        if not (np.isfinite(lat) and np.isfinite(lon)):
            return None
        if abs(lat) < 1e-6 and abs(lon) < 1e-6:
            return None  # (0, 0) means the station left the field unset
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return None
        return round(lat, 4), round(lon, 4)
    except Exception:
        return None


def _record_station_coords(station: str, header) -> bool:
    """Persist FITS-derived coordinates for a station. Returns True if updated."""
    coords = _coords_from_header(header)
    if not coords:
        return False
    name = station.upper()
    entry = {"lat": coords[0], "lon": coords[1], "source": "fits"}
    _load_coord_registry()
    with _COORD_REGISTRY_LOCK:
        if _COORD_REGISTRY.get(name) == entry:
            return False
        _COORD_REGISTRY[name] = entry
    _save_coord_registry()
    try:
        with session_scope() as session:
            station = session.get(Station, name)
            if station is None:
                session.add(Station(name=name, lat=coords[0], lon=coords[1], coord_source="fits"))
            else:
                station.lat = coords[0]
                station.lon = coords[1]
                station.coord_source = "fits"
                station.updated_at = datetime.now(timezone.utc)
    except Exception as exc:
        logger.debug("Could not persist station coordinates in database: %s", exc)
    logger.info("Learned coordinates for %s from FITS: %.4f, %.4f", name, *coords)
    return True


def _station_from_filename(filename: str) -> str | None:
    """Return the STATION prefix (upper-case) of a CALLISTO filename."""
    m = re.match(r"([A-Za-z0-9][A-Za-z0-9_-]*?)_\d{8}_\d{6}", filename)
    return m.group(1).upper() if m else None


def _harvest_coords_from_local() -> int:
    """Populate the registry from locally cached FITS files (one per station)."""
    global _LOCAL_HARVEST_DONE
    _load_coord_registry()
    with _COORD_REGISTRY_LOCK:
        if _LOCAL_HARVEST_DONE:
            return 0
        _LOCAL_HARVEST_DONE = True
    if not os.path.isdir(DATA_DIR_LOCAL):
        return 0

    by_station: dict[str, str] = {}
    for path in glob.glob(os.path.join(DATA_DIR_LOCAL, "*.fit*")):
        st = _station_from_filename(os.path.basename(path))
        if st:
            by_station.setdefault(st, path)

    added = 0
    for st, path in by_station.items():
        with _COORD_REGISTRY_LOCK:
            cur = _COORD_REGISTRY.get(st)
        if cur and cur.get("source") == "fits":
            continue
        try:
            with fits.open(path, memmap=False) as hdul:
                if _record_station_coords(st, hdul[0].header):
                    added += 1
        except Exception:
            continue
    if added:
        logger.info("Harvested %d station coordinates from local FITS files", added)
    return added


def _harvest_coords_by_download(stations: list[str], date: str) -> None:
    """Background task: fetch one FITS per station and learn its coordinates."""
    for st in stations:
        try:
            path = (
                _find_local_fits_file(st, date)
                or _find_nas_fits_file(st, date)
                or _download_from_ethz(st, date)
            )
            if not path:
                continue
            with fits.open(path, memmap=False) as hdul:
                _record_station_coords(st, hdul[0].header)
        except Exception as exc:
            logger.debug("Coord harvest failed for %s: %s", st, exc)


def _resolve_station_coords(name: str) -> tuple[float, float, str] | None:
    """Return (lat, lon, source) — FITS registry first, hand fallback second."""
    try:
        with session_scope() as session:
            persisted = session.get(Station, name.upper())
            if persisted and persisted.lat is not None and persisted.lon is not None:
                return float(persisted.lat), float(persisted.lon), persisted.coord_source or "fits"
    except Exception as exc:
        logger.debug("Database coordinate lookup unavailable: %s", exc)
    _load_coord_registry()
    with _COORD_REGISTRY_LOCK:
        reg = _COORD_REGISTRY.get(name)
    if reg:
        return float(reg["lat"]), float(reg["lon"]), "fits"
    fb = _STATIONS_GEO.get(name)
    if fb:
        return fb[0], fb[1], "approx"
    return None


# ── Models ───────────────────────────────────────────────────────────────────

class SpectrogramResponse(BaseModel):
    station: str
    date: str
    filename: str
    filenames: list[str] = Field(default_factory=list)  # blocks actually used, chronological
    time_axis: list[str]
    freq_axis: list[float]
    z: list[list[float]]
    vmin: float
    vmax: float
    fits_header: dict
    rfi_stats: dict = Field(default_factory=dict)
    unit: str = "relative digits"
    scale_mode: str = "relative"


class CombinedSpectrogramResponse(BaseModel):
    date: str
    layers: list[SpectrogramResponse]
    failed: list[dict]   # [{station, reason}, ...] for stations with no data


class BurstDetection(BaseModel):
    type: str              # type2, type3, type3s, type4 or type5
    score: float           # model confidence, 0-1
    experimental: bool     # IV and V: few training examples, wide test intervals
    start_utc: str
    end_utc: str
    start_s: float
    end_s: float
    freq_low_mhz: float
    freq_high_mhz: float


class BurstDetectResponse(BaseModel):
    model_config = {"protected_namespaces": ()}  # allow the model_version field

    station: str
    date: str
    filename: str
    filenames: list[str] = Field(default_factory=list)
    available: bool
    reason: str = ""
    model_version: str | None = None
    model_sha256: str | None = None
    threshold: float | None = None
    detections: list[BurstDetection] = Field(default_factory=list)


class GoesResponse(BaseModel):
    date: str
    available: bool
    reason: str
    times: list[str]
    xrsb: list[float]
    satellite: int | None = None
    product: str | None = None


class StationsResponse(BaseModel):
    stations: list[str]
    source: str
    retention_days: int = 90
    details: list[dict] = Field(default_factory=list)


class StationGeo(BaseModel):
    station: str
    lat: float
    lon: float
    operative: bool
    burst_count: int = 0        # bursts recorded by this station in `burst_month`
    coord_source: str = "approx"  # "fits" (from station data) | "approx" (fallback)


class StationsGeoResponse(BaseModel):
    stations: list[StationGeo]
    source: str
    operative_count: int
    total_count: int
    reference_date: str  # last ETHZ day scanned for "operative" status, or ""
    burst_month: str = ""  # "YYYY-MM" of the burst list used, or "" if unavailable
    burst_total: int = 0   # total burst-station detections counted that month
    unmapped: list[str] = Field(default_factory=list)   # live stations we have no coordinates for (yet)
    fits_coord_count: int = 0  # how many plotted coords came from real FITS headers
    retention_days: int = 90


class FileEntry(BaseModel):
    filename: str
    time: str    # "HH:MM:SS"
    label: str   # display label for the UI
    focus_code: str | None = None


class FilesResponse(BaseModel):
    station: str
    date: str
    files: list[FileEntry]
    source: str  # "local", "ethz", "mixed"


# ── I/O helpers ──────────────────────────────────────────────────────────────

def _find_local_fits_file(station: str, date: str) -> str | None:
    """Search the local cache by exact station token and observation date."""
    files = _fits_in_directory(DATA_DIR_LOCAL, station, date)
    return safe_join(DATA_DIR_LOCAL, files[0]) if files else None


def _nas_date_directory(date: str) -> str:
    validate_date(date)
    root = os.path.realpath(ECALLISTO_DATA_DIR)
    date_dir = os.path.realpath(os.path.join(root, *date.split("-")))
    if os.path.commonpath((root, date_dir)) != root:
        raise ValueError("Resolved archive directory escapes the configured root")
    return date_dir


def _fits_in_directory(root: str, station: str, date: str) -> list[str]:
    station = validate_station(station)
    validate_date(date)
    # Compressed files first.
    found = []
    for ext in (".fit.gz", ".fits.gz", ".fit", ".fits"):
        for path in sorted(glob.glob(os.path.join(root, f"{station.upper()}_{date.replace('-', '')}_*{ext}"))):
            name = os.path.basename(path)
            try:
                validate_filename_context(name, station, date)
                if os.path.isfile(safe_join(root, name)):
                    found.append(name)
            except ValueError:
                continue
    return found


def _find_nas_fits_file(station: str, date: str, filename: str | None = None) -> str | None:
    """Resolve only a validated observation inside the read-only NAS archive."""
    date_dir = _nas_date_directory(date)
    if filename is not None:
        path = safe_join(date_dir, validate_filename_context(filename, station, date))
        return path if os.path.isfile(path) else None
    files = _fits_in_directory(date_dir, station, date)
    if not files:
        return None
    return safe_join(date_dir, files[0])


def _time_from_filename(filename: str) -> str:
    """Extract start time as HH:MM:SS from a CALLISTO filename.

    Handles all naming variants: with or without the trailing _NN segment,
    and both .fit / .fits / .fit.gz / .fits.gz extensions.
    """
    m = re.search(r'_\d{8}_(\d{2})(\d{2})(\d{2})', filename)
    if m:
        return f"{m.group(1)}:{m.group(2)}:{m.group(3)}"
    return "??:??:??"


def _list_local_fits_files(station: str, date: str) -> list[str]:
    """List validated observations in the cache and optional NAS archive."""
    return sorted(set(
        _fits_in_directory(DATA_DIR_LOCAL, station, date)
        + _fits_in_directory(_nas_date_directory(date), station, date)
    ))


_ARCHIVE_DAY_CACHE: dict[str, tuple[float, dict[str, list[str]]]] = {}
_ARCHIVE_DAY_CACHE_LOCK = threading.Lock()
_ARCHIVE_DAY_FETCH_LOCKS: dict[str, threading.Lock] = {}
_ARCHIVE_DAY_CACHE_MAX = 31  # about 0.6 MB per day


def _archive_inventory_for_date(date: str) -> dict[str, list[str]]:
    """Return the live archive's station-to-filenames inventory for one UTC day."""
    try:
        validate_date(date)
        dt = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return {}
    now = datetime.now(timezone.utc).timestamp()
    ttl = float(os.environ.get("ARCHIVE_INDEX_REFRESH_MINUTES", "60")) * 60.0
    with _ARCHIVE_DAY_CACHE_LOCK:
        cached = _ARCHIVE_DAY_CACHE.get(date)
    if cached and now - cached[0] < ttl:
        return cached[1]

    # Several views can need the same daily index at once (station list,
    # Burst Reports navigation and Xmatch). Fetch it once and let the other
    # requests reuse the result instead of opening duplicate remote requests.
    with _ARCHIVE_DAY_CACHE_LOCK:
        _prune_idle_locks(_ARCHIVE_DAY_FETCH_LOCKS)
        fetch_lock = _ARCHIVE_DAY_FETCH_LOCKS.setdefault(date, threading.Lock())
    with fetch_lock:
        now = datetime.now(timezone.utc).timestamp()
        with _ARCHIVE_DAY_CACHE_LOCK:
            cached = _ARCHIVE_DAY_CACHE.get(date)
        if cached and now - cached[0] < ttl:
            return cached[1]

        dir_url = f"{ETHZ_BASE_URL}/{dt.strftime('%Y/%m/%d')}/"
        try:
            req = Request(dir_url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=15) as resp:
                page = resp.read().decode("utf-8", errors="replace")
        except Exception:
            return cached[1] if cached else {}

        expected_date = dt.strftime("%Y%m%d")
        inventory: dict[str, list[str]] = {}
        for raw_name in re.findall(r'href="([^"]+\.fits?(?:\.gz)?)"', page, re.IGNORECASE):
            filename = os.path.basename(html.unescape(raw_name))
            station = _station_from_filename(filename)
            if station is None or f"_{expected_date}_" not in filename.upper():
                continue
            try:
                validate_filename_context(filename, station, date)
            except ValueError:
                continue
            inventory.setdefault(station, []).append(filename)
        inventory = {
            station: sorted(set(filenames))
            for station, filenames in inventory.items()
        }
        with _ARCHIVE_DAY_CACHE_LOCK:
            _ARCHIVE_DAY_CACHE[date] = (now, inventory)
            if len(_ARCHIVE_DAY_CACHE) > _ARCHIVE_DAY_CACHE_MAX:
                oldest = min(_ARCHIVE_DAY_CACHE, key=lambda day: _ARCHIVE_DAY_CACHE[day][0])
                del _ARCHIVE_DAY_CACHE[oldest]
        return inventory


def _list_ethz_files(station: str, date: str) -> list[str]:
    """Return the filenames advertised by the live ETHZ archive index."""
    try:
        station = validate_station(station)
    except ValueError:
        return []
    return _archive_inventory_for_date(date).get(station.upper(), [])


def _download_from_ethz(station: str, date: str, filename: str | None = None) -> str | None:
    """Resolve the cache/NAS first, then download a missing FITS from ETHZ.

    If `filename` is given, downloads that specific file.
    Otherwise, downloads the first file matching station/date.
    Saves to DATA_DIR_LOCAL for reuse in future calls.
    """
    try:
        station = validate_station(station)
        validate_date(date)
        if filename is not None:
            filename = validate_filename_context(filename, station, date)
        dt = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return None

    dir_url = f"{ETHZ_BASE_URL}/{dt.strftime('%Y/%m/%d')}/"
    os.makedirs(DATA_DIR_LOCAL, exist_ok=True)

    if filename:
        local_path = safe_join(DATA_DIR_LOCAL, filename)
        with _DOWNLOAD_LOCKS_GUARD:
            _prune_idle_locks(_DOWNLOAD_LOCKS)
            download_lock = _DOWNLOAD_LOCKS.setdefault(local_path, threading.Lock())
        with download_lock:
            if os.path.isfile(local_path):
                logger.info("File already cached: %s", local_path)
                return local_path
            nas_path = _find_nas_fits_file(station, date, filename)
            if nas_path:
                return nas_path
            file_url = dir_url + filename
            temporary_path = f"{local_path}.{uuid.uuid4().hex}.part"
            max_bytes = int(os.environ.get("MAX_FITS_DOWNLOAD_BYTES", str(128 * 1024 * 1024)))
            logger.info("Downloading %s → %s", file_url, local_path)
            try:
                req = Request(file_url, headers={"User-Agent": USER_AGENT})
                downloaded = 0
                with urlopen(req, timeout=120) as resp:
                    declared = resp.headers.get("Content-Length")
                    if declared and int(declared) > max_bytes:
                        raise ValueError(f"Remote FITS exceeds {max_bytes} bytes")
                    with open(temporary_path, "wb") as fh:
                        while chunk := resp.read(512 * 1024):
                            downloaded += len(chunk)
                            if downloaded > max_bytes:
                                raise ValueError(f"Remote FITS exceeds {max_bytes} bytes")
                            fh.write(chunk)
                with fits.open(temporary_path, memmap=False) as downloaded_fits:
                    downloaded_fits.verify("exception")
                    if not downloaded_fits or downloaded_fits[0].data is None:
                        raise ValueError("Downloaded file has no primary FITS data")
                os.replace(temporary_path, local_path)
                logger.info("Download complete (%d bytes)", downloaded)
                with _FILES_CACHE_LOCK:
                    _FILES_CACHE.pop((station.upper(), date), None)
                return local_path
            except Exception as exc:
                logger.error("Failed to download %s: %s", file_url, exc)
                try:
                    os.remove(temporary_path)
                except OSError:
                    pass
                return None

    local = _find_local_fits_file(station, date) or _find_nas_fits_file(station, date)
    if local:
        return local
    matches = _list_ethz_files(station, date)
    if not matches:
        logger.warning("No files for '%s' in ETHZ on %s", station, date)
        return None

    return _download_from_ethz(station, date, filename=matches[0])



def _header_to_dict(header) -> dict:
    """Convert a FITS header to a JSON-serializable dict."""
    result: dict = {}
    for key, value in header.items():
        if key in ("COMMENT", "HISTORY", ""):
            continue
        try:
            result[key] = value if isinstance(value, (int, float, str, bool)) else str(value)
        except Exception:
            result[key] = str(value)
    return result


def _record_fits_metadata(station: str, path: str, header) -> None:
    """Persist searchable FITS metadata without making processing depend on the DB."""
    filename = os.path.basename(path)
    match = re.search(r"_(\d{8})_(\d{6})", filename)
    if not match:
        return
    observed = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    try:
        with session_scope() as session:
            station_name = station.upper()
            row = session.scalar(select(FitsFile).where(FitsFile.filename == filename))
            if row is None:
                row = FitsFile(filename=filename, station=station_name, observed_at=observed)
                session.add(row)
            row.path = path
            row.origin = "nas" if os.path.realpath(path).startswith(os.path.realpath(ECALLISTO_DATA_DIR)) else "cache"
            row.focus_code = fits_focus_code(filename)
            row.fits_header = _header_to_dict(header)
            station_row = session.get(Station, station_name)
            if station_row is None:
                session.add(Station(
                    name=station_name,
                    first_seen_at=observed,
                    last_seen_at=observed,
                ))
            else:
                first_seen = as_utc(station_row.first_seen_at) if station_row.first_seen_at else None
                last_seen = as_utc(station_row.last_seen_at) if station_row.last_seen_at else None
                station_row.first_seen_at = min(first_seen or observed, observed)
                station_row.last_seen_at = max(last_seen or observed, observed)
                station_row.updated_at = datetime.now(timezone.utc)
    except Exception as exc:
        logger.debug("Could not persist FITS metadata: %s", exc)


# ── Observation (one block, or two consecutive blocks of one receiver) ───────

def _block_paths(station: str, date: str, names: list[str]) -> list[str]:
    """Local paths of already validated block names; FileNotFoundError if one is missing."""
    paths = []
    for name in names:
        path = _download_from_ethz(station, date, filename=name)
        if not path:
            raise FileNotFoundError(f"Could not retrieve '{name}' for '{station}' on {date}.")
        paths.append(path)
    return paths


def _requested_blocks(station: str, date: str, filename: str | None, filenames: list[str] | None) -> list[str]:
    """Validate the block names of an interactive request (``filenames`` wins); HTTP 422 if invalid."""
    try:
        station = validate_station(station)
        validate_date(date)
        return validate_observation_filenames(filename, filenames, station, date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def open_observation(station: str, date: str, filename: str | None, filenames: list[str] | None) -> Observation:
    """Validate, resolve and join the requested block(s). Raises HTTPException (404 or 422)."""
    names = _requested_blocks(station, date, filename, filenames)
    try:
        return join_blocks(_block_paths(station, date, names))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ObservationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── Single-station pipeline helper ───────────────────────────────────────────

def _spectrogram_response(
    station: str,
    date: str,
    observation: Observation,
    data: np.ndarray,
    freqs,
    time_axis: list[str],
    rfi_stats: dict,
    scale_mode: str,
) -> SpectrogramResponse:
    vmin, vmax = processing.percentile_clip(data.astype(float))
    data_out = np.nan_to_num(np.array(data, dtype=float), nan=0.0, posinf=vmax, neginf=vmin)
    return SpectrogramResponse(
        station=station,
        date=date,
        filename=observation.filenames[0],
        filenames=observation.filenames,
        time_axis=time_axis,
        freq_axis=np.round(np.asarray(freqs, dtype=float), 3).tolist(),
        z=np.round(data_out, 4).tolist(),
        vmin=round(vmin, 4),
        vmax=round(vmax, 4),
        fits_header=_header_to_dict(observation.header),
        rfi_stats=rfi_stats,
        unit="dB" if scale_mode == "median_db" else "relative digits",
        scale_mode=scale_mode,
    )


def _build_spectrogram(
    station: str,
    date: str,
    filename: str | None = None,
    rfi: bool = False,
    filenames: list[str] | None = None,
    max_time_bins: int | None = None,
    rfi_z_thresh: float = 6.0,
    rfi_occupancy: float = 0.15,
    rfi_min_component: int = 9,
    rfi_impulsive: bool = True,
    scale_mode: str = "relative",
) -> SpectrogramResponse:
    """Resolve a FITS file and run the full processing pipeline for one station.

    Raises FileNotFoundError when no file can be located, RuntimeError on
    processing failures. Never raises HTTPException — callers handle that.

    When max_time_bins is set, the time axis is block-mean decimated before
    background subtraction.
    """
    station = validate_station(station)
    validate_date(date)
    names = validate_observation_filenames(filename, filenames, station, date) if (filename or filenames) else []
    if names:
        fits_paths = _block_paths(station, date, names)
    else:
        fits_path = _download_from_ethz(station, date)
        if not fits_path:
            raise FileNotFoundError(
                f"No file found for station '{station}' on {date}. "
                "Check the station name or whether the ETHZ server (soleil.i4ds.ch) is reachable."
            )
        fits_paths = [fits_path]

    logger.info("Processing %s", fits_paths)
    fits_path = fits_paths[0]
    try:
        observation = join_blocks(fits_paths)
        data_raw, freqs = observation.data, observation.freqs
        data_raw = processing.scale(data_raw, scale_mode)
        for block_path, block_header in zip(fits_paths, observation.headers, strict=True):
            _record_station_coords(station, block_header)  # learn the real site from its data
            _record_fits_metadata(station, block_path, block_header)
        time_labels = observation.time_labels

        if max_time_bins is not None:
            data, time_labels = processing.decimate_time(data_raw, time_labels, max_time_bins)
        else:
            data = data_raw

        rfi_args = dict(
            z_thresh=rfi_z_thresh,
            occupancy_thresh=rfi_occupancy,
            min_component_size=rfi_min_component,
            impulsive=rfi_impulsive,
        ) if rfi else None
        data, rfi_stats = processing.process(data, rfi_args)
        if rfi:
            logger.info(
                "RFI applied: %d persistent channels, %.2f%% samples masked",
                rfi_stats["persistent_channels"], 100.0 * rfi_stats["masked_fraction"],
            )

        return _spectrogram_response(
            station, date, observation, data, freqs, time_labels, rfi_stats, scale_mode,
        )
    except ObservationError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Error processing FITS '{fits_path}': {exc}") from exc


_COMBINE_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="combine")
_MAX_COMBINE_STATIONS = 6


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "name": APP_NAME, "version": APP_VERSION}


@app.get("/ready")
def readiness():
    from sqlalchemy import text

    database = "ok"
    try:
        with session_scope() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        database = "degraded"
    from backend import burst_types

    model_ok, model_reason = burst_types.is_available()
    payload = {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "burst_model": "ok" if model_ok else "unavailable",
        "burst_model_reason": model_reason,
    }
    if database != "ok":
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=503, content=payload)
    return payload


# e-CALLISTO monthly burst lists (deARCE (v3), UAH / ETHZ). One text file per month
# lists every detected solar radio burst and the stations that recorded it.
_BURSTLIST_BASE = "http://soleil.i4ds.ch/solarradio/data/BurstLists/2010-yyyy_Monstein"
_BURST_CACHE: dict[str, tuple[float, dict[str, int]]] = {}
_BURST_CACHE_TTL = 1800.0  # seconds (monthly file changes at most a few times/day)
_BURST_CACHE_LOCK = threading.Lock()


def _burst_counts_for_month(year: int, month: int) -> dict[str, int]:
    """Return {STATION_UPPER: burst_count} from the monthly e-CALLISTO burst list.

    Counts, per station, the number of burst events it participated in during the
    given month. Results are cached for `_BURST_CACHE_TTL` seconds. Returns an
    empty dict when the list cannot be fetched or parsed.
    """
    key = f"{year:04d}-{month:02d}"
    now = datetime.now(timezone.utc).timestamp()
    with _BURST_CACHE_LOCK:
        cached = _BURST_CACHE.get(key)
        if cached and (now - cached[0]) < _BURST_CACHE_TTL:
            return cached[1]

    url = f"{_BURSTLIST_BASE}/{year:04d}/e-CALLISTO_{year:04d}_{month:02d}.txt"
    counts: dict[str, int] = {}
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.debug("Burst list %s unavailable: %s", key, exc)
        with _BURST_CACHE_LOCK:
            _BURST_CACHE[key] = (now, {})
        return {}

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("Product"):
            continue
        # Columns are tab-separated: Date <tab> Time <tab> Type <tab> Stations
        parts = re.split(r"\t+", line)
        if len(parts) < 4:
            parts = re.split(r"\s{2,}", line)  # fallback if tabs were lost
        if len(parts) < 4:
            continue
        time_field = parts[1]
        if "#" in time_field:  # "##:##-##:##" marks a day with no bursts
            continue
        stations_field = parts[-1]
        for token in stations_field.split(","):
            name = token.strip().upper()
            # Drop any trailing quality annotation like "(good)" if present
            name = re.sub(r"\s*\(.*?\)\s*$", "", name)
            if name:
                counts[name] = counts.get(name, 0) + 1

    with _BURST_CACHE_LOCK:
        _BURST_CACHE[key] = (now, counts)
    logger.info("Burst list %s parsed: %d stations, %d detections",
                key, len(counts), sum(counts.values()))
    return counts


# Cache for the "which stations reported recently" scan. Operative status has
# daily granularity, so a few minutes of caching is accurate — and it means any
# number of client refreshes are served from memory instead of hammering the
# external ETHZ server (soleil.i4ds.ch).
_STATION_SCAN_CACHE: tuple[float, list[str], str] | None = None
_STATION_SCAN_LOCK = threading.Lock()


def _persist_station_inventory(names: list[str], reference_date: str) -> None:
    """Persist archive-derived sightings without overwriting FITS coordinates."""
    if not names or not reference_date:
        return
    observed = datetime.strptime(reference_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        for name in names:
            station = session.get(Station, name)
            if station is None:
                session.add(Station(
                    name=name,
                    first_seen_at=observed,
                    last_seen_at=observed,
                    updated_at=now,
                ))
            else:
                first_seen = station.first_seen_at
                last_seen = station.last_seen_at
                if first_seen and first_seen.tzinfo is None:
                    first_seen = first_seen.replace(tzinfo=timezone.utc)
                if last_seen and last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                station.first_seen_at = min(first_seen or observed, observed)
                station.last_seen_at = max(last_seen or observed, observed)
                station.updated_at = now


def _station_retention_days() -> int:
    try:
        return max(1, min(3650, int(os.environ.get("STATION_RETENTION_DAYS", "90"))))
    except ValueError:
        logger.warning("Invalid STATION_RETENTION_DAYS; using 90")
        return 90


def _known_station_names(reference_date: str = "") -> set[str]:
    """Return stations seen recently, plus FITS-only stations without a sighting date.

    Historical rows remain in the database for provenance, but stations absent
    beyond the configured retention window automatically leave the live UI.
    """
    retention_days = _station_retention_days()
    try:
        anchor = (
            datetime.strptime(reference_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if reference_date
            else datetime.now(timezone.utc)
        )
    except ValueError:
        anchor = datetime.now(timezone.utc)
    cutoff = anchor - timedelta(days=retention_days)
    try:
        with session_scope() as session:
            return set(session.scalars(
                select(Station.name).where(
                    Station.last_seen_at.is_(None) | (Station.last_seen_at >= cutoff)
                )
            ).all())
    except Exception as exc:
        logger.debug("Persisted station catalogue unavailable: %s", exc)
        return set()


def _scan_recent_ethz_stations() -> tuple[list[str], str]:
    """Scan the ETHZ archive for the most recent day that has data.

    Returns (sorted unique station names, reference_date 'YYYY-MM-DD'). Results
    are cached for STATION_REFRESH_MINUTES. When ETHZ is unreachable, the
    last good scan is served if available, otherwise ([], "").
    """
    global _STATION_SCAN_CACHE
    now = datetime.now(timezone.utc).timestamp()
    ttl = float(os.environ.get("STATION_REFRESH_MINUTES", "60")) * 60.0
    with _STATION_SCAN_LOCK:
        cached = _STATION_SCAN_CACHE
    if cached and (now - cached[0]) < ttl:
        return cached[1], cached[2]

    latest: tuple[list[str], str] | None = None
    for days_back in range(0, 8):
        dt = datetime.now(timezone.utc) - timedelta(days=days_back)
        ref = dt.strftime("%Y-%m-%d")
        unique = sorted(_archive_inventory_for_date(ref))
        if unique:
            _persist_station_inventory(unique, ref)
            if latest is None:
                latest = (unique, ref)
    if latest is not None:
        unique, ref = latest
        logger.info(
            "Stations found in ETHZ: %d active on %s; recent history persisted",
            len(unique),
            ref,
        )
        with _STATION_SCAN_LOCK:
            _STATION_SCAN_CACHE = (now, unique, ref)
        return unique, ref

    # ETHZ unreachable right now — fall back to the last good scan if we have one.
    if cached:
        logger.warning("ETHZ unreachable; serving cached station scan from %s", cached[2])
        return cached[1], cached[2]
    return [], ""


@app.get("/api/stations", response_model=StationsResponse)
def get_stations():
    """Return all known stations plus archive-derived active/inactive state."""
    reporting, ref_date = _scan_recent_ethz_stations()
    reporting_set = set(reporting)
    known = _known_station_names(ref_date)
    catalog = sorted(known | reporting_set)
    source = "ethz+persisted"
    if not catalog:
        logger.warning("No dynamic station inventory available; using bootstrap fallback")
        catalog = list(_STATIONS_FALLBACK)
        source = "bootstrap"

    persisted: dict[str, Station] = {}
    try:
        with session_scope() as session:
            persisted = {
                item.name: item
                for item in session.scalars(select(Station).where(Station.name.in_(catalog))).all()
            }
    except Exception as exc:
        logger.debug("Station activity details unavailable: %s", exc)
    details = []
    for name in catalog:
        stored = persisted.get(name)
        details.append({
            "station": name,
            "active": name in reporting_set,
            "last_seen_at": stored.last_seen_at.isoformat() if stored and stored.last_seen_at else None,
        })
    return StationsResponse(
        stations=catalog,
        source=source,
        retention_days=_station_retention_days(),
        details=details,
    )


@app.get("/api/stations/geo", response_model=StationsGeoResponse)
def get_stations_geo():
    """Return mappable stations with coordinates and live operative status.

    A station is flagged *operative* when it reported at least one file on the
    most recent day scanned in the ETHZ archive. When ETHZ is unreachable the
    catalogue is still returned, but every station is marked non-operative and
    `reference_date` is empty so the frontend can indicate the status is stale.
    """
    reporting, ref_date = _scan_recent_ethz_stations()
    reporting_set = set(reporting)

    # Fill the coordinate registry from any FITS files we already have on disk.
    _harvest_coords_from_local()

    # Burst counts come from the current month's list (fall back to the ETHZ
    # reference month if "now" has no list yet).
    anchor = datetime.now(timezone.utc)
    burst_counts = _burst_counts_for_month(anchor.year, anchor.month)
    if not burst_counts and ref_date:
        ref_dt = datetime.strptime(ref_date, "%Y-%m-%d")
        burst_counts = _burst_counts_for_month(ref_dt.year, ref_dt.month)
        anchor = ref_dt
    burst_month = f"{anchor.year:04d}-{anchor.month:02d}" if burst_counts else ""

    # The catalogue is driven by real data: stations reporting now, plus every
    # station we already know coordinates for. The hand-written list is never the
    # source of truth for *which* stations exist — only a coordinate fallback.
    # Station existence comes from archive/catalog sightings. The coordinate
    # registry is only a lookup table and must never create phantom stations.
    catalog = reporting_set | _known_station_names(ref_date)

    entries: list[StationGeo] = []
    unmapped: list[str] = []
    fits_count = 0
    for name in sorted(catalog):
        operative = name in reporting_set
        coords = _resolve_station_coords(name)
        if coords is None:
            if operative:  # surface only live stations we can't place yet
                unmapped.append(name)
            continue
        if coords[2] == "fits":
            fits_count += 1
        entries.append(
            StationGeo(
                station=name,
                lat=coords[0],
                lon=coords[1],
                operative=operative,
                burst_count=burst_counts.get(name, 0),
                coord_source=coords[2],
            )
        )

    # Learn real coordinates in the background for live stations still on the
    # fallback (or unmapped), a few per call, throttled to spare the archive.
    now_ts = datetime.now(timezone.utc).timestamp()
    need = [
        e.station for e in entries if e.coord_source == "approx" and e.operative
    ] + unmapped
    todo = [
        st for st in need
        if now_ts - _COORD_ATTEMPTS.get(st, 0) > _COORD_ATTEMPT_COOLDOWN
    ][:6]
    if todo and ref_date:
        for st in todo:
            _COORD_ATTEMPTS[st] = now_ts
        _COORD_EXECUTOR.submit(_harvest_coords_by_download, todo, ref_date)

    operative_count = sum(1 for e in entries if e.operative)
    return StationsGeoResponse(
        stations=entries,
        source="ethz" if ref_date else "static",
        operative_count=operative_count,
        total_count=len(entries),
        reference_date=ref_date,
        burst_month=burst_month,
        burst_total=sum(burst_counts.values()),
        unmapped=sorted(unmapped),
        fits_coord_count=fits_count,
        retention_days=_station_retention_days(),
    )


_FILES_CACHE: dict[tuple[str, str], tuple[float, FilesResponse]] = {}
_FILES_CACHE_LOCK = threading.Lock()
_FILES_CACHE_TTL = 120.0


@app.get("/api/files", response_model=FilesResponse)
def get_files(
    station: str = Query(..., description="e-Callisto station name"),
    date: str = Query(..., description="Observation date, format YYYY-MM-DD"),
):
    """List all burst files available for a station and date.

    Merges locally cached files (already downloaded) with those available on ETHZ.
    Each entry includes the filename and the start time extracted from its name.
    """
    try:
        station = validate_station(station)
        validate_date(date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    cache_key = (station.upper(), date)
    now = datetime.now(timezone.utc).timestamp()
    with _FILES_CACHE_LOCK:
        cached_response = _FILES_CACHE.get(cache_key)
    if cached_response and now - cached_response[0] < _FILES_CACHE_TTL:
        return cached_response[1]

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
        entries.append(FileEntry(
            filename=fn, time=t, label=f"{cached}{t}",
            focus_code=fits_focus_code(fn),
        ))

    response = FilesResponse(station=station, date=date, files=entries, source=source)
    with _FILES_CACHE_LOCK:
        # Drop expired listings so the cache only holds the last few minutes.
        for key in [key for key, (saved, _) in _FILES_CACHE.items() if now - saved >= _FILES_CACHE_TTL]:
            del _FILES_CACHE[key]
        _FILES_CACHE[cache_key] = (now, response)
    return response


@app.get("/api/spectrogram", response_model=SpectrogramResponse)
def get_spectrogram(
    station: str = Query(..., description="e-Callisto station, e.g. SPAIN-SIGUENZA"),
    date: str = Query(..., description="Observation date, format YYYY-MM-DD"),
    filename: str = Query(default=None, description="Specific FITS filename"),
    filenames: list[str] | None = Query(default=None, description="One or two consecutive blocks of one receiver; wins over filename"),
    rfi: bool = Query(default=False, description="Apply full RFI cleaning"),
    max_time_bins: int = Query(default=None, ge=1, description="Decimate time axis to at most N columns (overview mode)"),
    rfi_z_thresh: float = Query(default=6.0, ge=0.5, le=20.0, description="RFI robust z-score threshold"),
    rfi_occupancy: float = Query(default=0.15, ge=0.01, le=1.0, description="RFI channel occupancy threshold"),
    rfi_min_component: int = Query(default=9, ge=1, le=500, description="Min connected-component size for impulsive RFI"),
    rfi_impulsive: bool = Query(default=True, description="Enable impulsive (connected-component) RFI stage"),
    scale_mode: str = Query(default="relative", pattern="^(relative|median_db)$"),
):
    """Return the spectrogram for an e-Callisto station.

    With a filename the file comes from the local cache, else ETHZ. Without one,
    the first local match is used, then the NAS, then ETHZ. The API never accepts
    filesystem paths.

    Processing pipeline:
    - Always: robust background subtraction (25th percentile per frequency channel).
    - If rfi=true: additionally applies RFI mitigation (occupancy +
      connected components + channel-median inpainting).
    - vmin/vmax are always recomputed on the processed data.
    """
    try:
        return _build_spectrogram(
            station, date,
            filename=filename,
            filenames=filenames,
            rfi=rfi,
            max_time_bins=max_time_bins,
            rfi_z_thresh=rfi_z_thresh,
            rfi_occupancy=rfi_occupancy,
            rfi_min_component=rfi_min_component,
            rfi_impulsive=rfi_impulsive,
            scale_mode=scale_mode,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ObservationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error processing spectrogram for %s %s", station, date)
        raise HTTPException(status_code=500, detail="Spectrogram processing failed; use the request id to inspect server logs") from exc


@app.get("/api/spectrogram/combine", response_model=CombinedSpectrogramResponse)
async def get_spectrogram_combine(
    date: str = Query(..., description="Observation date, format YYYY-MM-DD"),
    stations: list[str] = Query(..., description="Station names to combine"),
    filename: str = Query(default=None, description="Primary station filename for 15-min block sync"),
    rfi: bool = Query(default=False, description="Apply full RFI cleaning"),
    max_time_bins: int = Query(default=None, ge=1, description="Decimate time axis to at most N columns (overview mode)"),
    rfi_z_thresh: float = Query(default=6.0, ge=0.5, le=20.0),
    rfi_occupancy: float = Query(default=0.15, ge=0.01, le=1.0),
    rfi_min_component: int = Query(default=9, ge=1, le=500),
    rfi_impulsive: bool = Query(default=True),
    scale_mode: str = Query(default="relative", pattern="^(relative|median_db)$"),
):
    """Return per-station spectrograms for multiple stations, processed concurrently.

    When `filename` is provided, the primary station (stations[0]) is fetched with
    that exact file and all secondary stations are synced to the same 15-minute block
    by scanning for a file whose HHMM matches the primary's. Stations with no matching
    file for that block are reported in `failed`.
    """
    if not stations:
        raise HTTPException(status_code=422, detail="At least one station is required.")
    try:
        validate_date(date)
        stations = [validate_station(station) for station in stations]
        if filename:
            filename = validate_filename_context(filename, stations[0], date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if len(stations) > _MAX_COMBINE_STATIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Too many stations requested: {len(stations)} > {_MAX_COMBINE_STATIONS}.",
        )

    # Derive HHMM target for time-sync (strip colons from "HH:MM:SS" → "HHMMSS")
    target_hhmm: str | None = None
    if filename:
        raw = _time_from_filename(filename).replace(":", "")  # "HHMMSS" or "??????"
        if len(raw) >= 4 and raw[:4].isdigit():
            target_hhmm = raw[:4]

    rfi_kwargs = dict(
        rfi_z_thresh=rfi_z_thresh,
        rfi_occupancy=rfi_occupancy,
        rfi_min_component=rfi_min_component,
        rfi_impulsive=rfi_impulsive,
        scale_mode=scale_mode,
    )

    def _process_one(
        st: str,
        exact_filename: str | None,
        match_hhmm: str | None,
    ) -> tuple[str, SpectrogramResponse | None, str | None]:
        try:
            if exact_filename:
                # Primary station: use the exact file the user selected
                logger.info("combine: station=%s exact_file=%s", st, exact_filename)
                result = _build_spectrogram(
                    st, date, filename=exact_filename,
                    rfi=rfi, max_time_bins=max_time_bins,
                    **rfi_kwargs,
                )
            elif match_hhmm:
                # Secondary station: scan available files and pick the one matching HHMM
                local = set(_list_local_fits_files(st, date))
                ethz = set(_list_ethz_files(st, date))
                all_files = sorted(local | ethz)
                matched = next(
                    (
                        f for f in all_files
                        if _time_from_filename(f).replace(":", "")[:4] == match_hhmm
                    ),
                    None,
                )
                if matched is None:
                    raise FileNotFoundError(
                        f"No file for time block {match_hhmm[:2]}:{match_hhmm[2:]} on {date}."
                    )
                logger.info("combine: station=%s matched_file=%s", st, matched)
                result = _build_spectrogram(
                    st, date, filename=matched,
                    rfi=rfi, max_time_bins=max_time_bins,
                    **rfi_kwargs,
                )
            else:
                # No time anchor was derived — refuse rather than silently loading an
                # arbitrary file, which would produce unsynchronised or duplicated data.
                raise FileNotFoundError(
                    f"No time anchor for station '{st}': cannot determine which "
                    "15-minute block to load. Provide a primary filename."
                )
            return st, result, None
        except Exception as exc:
            logger.warning("combine: %s failed: %s", st, exc)
            reason = str(exc) if isinstance(exc, FileNotFoundError) else "FITS processing failed; inspect server logs using the request id"
            return st, None, reason

    # Primary station gets the exact filename; secondaries get HHMM sync
    tasks = [
        (st, filename if (i == 0 and filename) else None, target_hhmm if i > 0 else None)
        for i, st in enumerate(stations)
    ]

    loop = asyncio.get_event_loop()
    futures = [
        loop.run_in_executor(_COMBINE_EXECUTOR, _process_one, st, fname, hhmm)
        for st, fname, hhmm in tasks
    ]
    results = await asyncio.gather(*futures)

    layers: list[SpectrogramResponse] = []
    failed: list[dict] = []
    for st, layer, reason in results:
        if layer is not None:
            layers.append(layer)
        else:
            failed.append({"station": st, "reason": reason})

    if not layers:
        raise HTTPException(
            status_code=404,
            detail=f"No data found for any of the requested stations on {date}.",
        )

    return CombinedSpectrogramResponse(date=date, layers=layers, failed=failed)


# ── High-resolution zoom patch ────────────────────────────────────────────────

# Zoom patches may be denser than the 1500-col overview: this ceiling only
# guards against pathological requests (e.g. full-file zoom at raw resolution).
_MAX_ZOOM_COLS = 2400


@app.get("/api/spectrogram/zoom", response_model=SpectrogramResponse)
def get_spectrogram_zoom(
    station: str = Query(..., description="e-Callisto station"),
    date: str = Query(..., description="Observation date, format YYYY-MM-DD"),
    filename: str | None = Query(default=None, description="Exact filename already shown in the overview"),
    filenames: list[str] | None = Query(default=None, description="One or two consecutive blocks; wins over filename"),
    t0: str = Query(..., description="Start time ISO-8601 UTC (from Plotly xaxis.range)"),
    t1: str = Query(..., description="End time ISO-8601 UTC (from Plotly xaxis.range)"),
    f0: float = Query(..., description="Start frequency MHz (from Plotly yaxis.range)"),
    f1: float = Query(..., description="End frequency MHz (from Plotly yaxis.range)"),
    rfi: bool = Query(default=False),
    rfi_z_thresh: float = Query(default=6.0, ge=0.5, le=20.0),
    rfi_occupancy: float = Query(default=0.15, ge=0.01, le=1.0),
    rfi_min_component: int = Query(default=9, ge=1, le=500),
    rfi_impulsive: bool = Query(default=True),
    scale_mode: str = Query(default="relative", pattern="^(relative|median_db)$"),
):
    """Return a maximum-resolution patch for a time+frequency bounding box.

    Uses the raw-data LRU cache so repeated zoom requests on the same file
    do not re-parse the FITS. Background subtraction and optional RFI cleaning
    use the whole duration of the selected channels, as in the overview, so
    zoomed intensities stay comparable with the full view; only the colour
    range (vmin/vmax) is computed on the zoomed region.
    """
    observation = open_observation(station, date, filename, filenames)

    try:
        data_raw, freqs = observation.data, observation.freqs
        time_labels: list[str] = observation.time_labels

        # ── Column indices (time) ─────────────────────────────────────────────
        try:
            t0_ts = parse_utc(t0).timestamp()
            t1_ts = parse_utc(t1).timestamp()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Cannot parse time bounds: {exc}")
        if t0_ts > t1_ts:
            t0_ts, t1_ts = t1_ts, t0_ts

        label_ts = np.array([parse_utc(lb).timestamp() for lb in time_labels])
        col0 = int(np.searchsorted(label_ts, t0_ts, side="left"))
        col1 = int(np.searchsorted(label_ts, t1_ts, side="right"))
        col0 = max(0, col0)
        col1 = min(data_raw.shape[1], col1)

        # ── Row indices (frequency, handle descending axis) ───────────────────
        freqs_arr = np.asarray(freqs)
        f_lo, f_hi = min(f0, f1), max(f0, f1)
        if freqs_arr.size > 1 and freqs_arr[-1] > freqs_arr[0]:
            # Ascending frequency axis
            row0 = int(np.searchsorted(freqs_arr, f_lo, side="left"))
            row1 = int(np.searchsorted(freqs_arr, f_hi, side="right"))
        else:
            # Descending: flip, searchsort, then map back to original indices
            freqs_flip = freqs_arr[::-1]
            r0 = int(np.searchsorted(freqs_flip, f_lo, side="left"))
            r1 = int(np.searchsorted(freqs_flip, f_hi, side="right"))
            n = len(freqs_arr)
            row0 = n - r1
            row1 = n - r0
        row0 = max(0, row0)
        row1 = min(data_raw.shape[0], row1)

        if col1 <= col0 or row1 <= row0:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Zoom box is outside data range or too narrow "
                    f"(cols {col0}:{col1}, rows {row0}:{row1})."
                ),
            )

        # ── Process the selected channels over the whole file, then slice ─────
        rfi_args = dict(
            z_thresh=rfi_z_thresh,
            occupancy_thresh=rfi_occupancy,
            min_component_size=rfi_min_component,
            impulsive=rfi_impulsive,
        ) if rfi else None
        data_proc, rfi_stats = processing.process(processing.scale(data_raw[row0:row1, :], scale_mode), rfi_args)
        data_proc = data_proc[:, col0:col1]
        freqs_slice = freqs_arr[row0:row1]
        time_slice: list[str] = time_labels[col0:col1]

        # Decimate only if the slice is still very wide
        if data_proc.shape[1] > _MAX_ZOOM_COLS:
            data_proc, time_slice = processing.decimate_time(data_proc, time_slice, _MAX_ZOOM_COLS)

        return _spectrogram_response(
            station, date, observation, data_proc, freqs_slice, time_slice, rfi_stats, scale_mode,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Zoom failed for %s %s: %s", station, observation.filenames, exc)
        raise HTTPException(status_code=500, detail="Zoom processing failed; use the request id to inspect server logs") from exc


# ── Automatic burst detection and classification (YOLO11s, ONNX) ─────────────

# Single thread: one file takes well under a second and the ONNX session is a
# shared singleton, so serialising requests is enough (no task worker needed).
_BURST_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="burst")


@app.get("/api/burst/detect", response_model=BurstDetectResponse)
async def detect_burst(
    station: str = Query(..., description="e-Callisto station"),
    date: str = Query(..., description="Observation date, format YYYY-MM-DD"),
    filename: str | None = Query(default=None, description="Exact FITS filename (as shown in the overview)"),
    filenames: list[str] | None = Query(default=None, description="One or two consecutive blocks; wins over filename"),
):
    """Detect and classify the solar radio bursts of one FITS file (or two consecutive ones).

    Each detection is a box with its burst type (II, III, IIIs, IV, V), the
    model confidence and its extent in UTC and MHz. IV and V are flagged as
    experimental.

    ONNX Runtime is optional: when it or the model is unavailable, the
    endpoint answers with ``available=false`` and a reason instead of failing.
    """
    names = _requested_blocks(station, date, filename, filenames)
    station = validate_station(station)

    from backend import burst_types  # deferred: inference runtime stays optional

    ok, reason = burst_types.is_available()
    if not ok:
        return BurstDetectResponse(
            station=station, date=date, filename=names[0], filenames=names,
            available=False, reason=reason,
        )

    def _run() -> dict:
        observation = open_observation(station, date, None, names)
        return burst_types.detect(
            observation.data, observation.freqs, observation.offsets_s, observation.start,
            observation.block_samples,
        )

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(_BURST_EXECUTOR, _run)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Burst detection failed for %s: %s", names, exc)
        raise HTTPException(status_code=500, detail="Burst detection failed; use the request id to inspect server logs") from exc

    logger.info("Burst detection %s: %d detection(s), %.0f ms",
                names, len(result["detections"]), result.pop("inference_ms"))
    return BurstDetectResponse(
        station=station, date=date, filename=names[0], filenames=names,
        available=True, **result,
    )


# ── GOES/XRS overlay ─────────────────────────────────────────────────────────

_GOES_CACHE_DIR = os.path.join(DATA_DIR_LOCAL, "goes_cache")
_GOES_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="goes-fido")

# Preferred GOES satellite order by epoch.
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
    """Select the XRS-B column (long channel, 0.1–0.8 nm) by heuristic scoring."""
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


# NOAA publishes two XRS science products per day. They are never mixed: the
# native high-cadence flux is preferred and the 1-minute average is a fallback.
_GOES_PRODUCTS = ("flx1s", "avg1m")
_GOES_PAYLOAD_FORMAT = 2
# Science files appear a few days after the UTC day ends; dates this recent
# get an explanatory message instead of a generic failure.
_GOES_PUBLICATION_DELAY_DAYS = 7
_GOES_UNAVAILABLE_UNTIL: dict[str, float] = {}
_GOES_UNAVAILABLE_LOCK = threading.Lock()


def _goes_max_days() -> int:
    try:
        return max(1, int(os.environ.get("GOES_CACHE_MAX_DAYS", "60")))
    except ValueError:
        return 60


def _goes_unavailable_retry_seconds() -> float:
    try:
        return max(0.0, float(os.environ.get("GOES_UNAVAILABLE_RETRY_MINUTES", "30"))) * 60
    except ValueError:
        return 1800.0


def _goes_xrsb_series(path: str, target_date) -> tuple[list[datetime], list[float]]:
    """Read the XRS-B column of one NOAA file, keeping valid samples of the day."""
    from sunpy import timeseries as ts

    df = ts.TimeSeries(path).to_dataframe()
    numeric_cols = [c for c in df.columns if np.issubdtype(df[c].dtype, np.number)]
    if not numeric_cols:
        return [], []
    col_b = _pick_xrsb_column(numeric_cols) or numeric_cols[-1]
    flux = np.asarray(df[col_b].values, dtype=float)
    idx = df.index
    times_py = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else list(idx)
    times: list[datetime] = []
    values: list[float] = []
    for t, f in zip(times_py, flux, strict=False):
        if not np.isfinite(f) or f <= 0.0:
            continue
        t = t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)
        if t.date() != target_date:
            continue
        times.append(t)
        values.append(float(f))
    return times, values


def _pack_goes_series(times: list[datetime], values: list[float]) -> dict:
    """Store a day compactly without moving any timestamp.

    Times become the first instant plus run-length encoded steps in ms
    (e.g. [[1000, 5000], [999, 1]]); flux keeps four significant figures.
    """
    t0_ms = round(times[0].timestamp() * 1000)
    epochs = [round(t.timestamp() * 1000) for t in times]
    steps: list[list[int]] = []
    for previous, current in zip(epochs, epochs[1:], strict=False):
        delta = current - previous
        if steps and steps[-1][0] == delta:
            steps[-1][1] += 1
        else:
            steps.append([delta, 1])
    return {"t0_ms": t0_ms, "steps_ms": steps, "xrsb": [float(f"{value:.4g}") for value in values]}


def _unpack_goes_series(series: dict) -> tuple[list[int], list[float]]:
    """Return (epoch milliseconds, flux) from a packed day."""
    epochs = [series["t0_ms"]]
    for delta, count in series["steps_ms"]:
        for _ in range(count):
            epochs.append(epochs[-1] + delta)
    return epochs, series["xrsb"]


def _fetch_goes_xrsb_sync(date_str: str) -> dict:
    """Download one GOES XRS-B science product for a full UTC day.

    Returns {"satellite": int, "product": "flx1s"|"avg1m", "series": packed}.
    The downloaded NetCDF file is removed once read; the database keeps the
    packed series.
    """
    try:
        from sunpy.net import Fido
        from sunpy.net import attrs as a
    except ImportError as exc:
        raise RuntimeError(
            f"sunpy is not installed in the backend ({exc}). "
            "Install with: pip install 'sunpy[net,timeseries]'"
        )

    target = datetime.strptime(date_str, "%Y-%m-%d")
    start = target.strftime("%Y-%m-%d 00:00:00")
    end = target.strftime("%Y-%m-%d 23:59:59")
    os.makedirs(_GOES_CACHE_DIR, exist_ok=True)
    last_err: Exception | None = None

    for sat in _preferred_goes_satellites(target.year):
        for product in _GOES_PRODUCTS:
            try:
                query = Fido.search(
                    a.Time(start, end),
                    a.Instrument.xrs,
                    a.goes.SatelliteNumber(sat),
                    a.Resolution(product),
                )
                if len(query) == 0 or sum(len(t) for t in query) == 0:
                    continue
                paths = Fido.fetch(query, path=os.path.join(_GOES_CACHE_DIR, "{file}"))
                try:
                    for path in paths:
                        times, values = _goes_xrsb_series(path, target.date())
                        if times:
                            logger.info("GOES-%d XRS %s: %d valid samples", sat, product, len(times))
                            return {"satellite": sat, "product": product, "series": _pack_goes_series(times, values)}
                finally:
                    for path in paths:
                        with suppress(OSError):
                            os.remove(path)
            except Exception as exc:
                logger.debug("GOES-%d %s failed: %s", sat, product, exc)
                last_err = exc

    raise RuntimeError(
        f"No GOES/XRS data found for {date_str}"
        + (f" ({last_err})" if last_err else "")
    )


def _store_goes_day(date: str, payload: dict) -> None:
    """Save a day and keep at most GOES_CACHE_MAX_DAYS, dropping the oldest stored."""
    with session_scope() as session:
        session.merge(GoesDay(date=date, payload=payload, updated_at=datetime.now(timezone.utc)))
        session.flush()
        stale = session.scalars(
            select(GoesDay).order_by(GoesDay.updated_at.desc(), GoesDay.date.desc()).offset(_goes_max_days())
        ).all()
        for row in stale:
            session.delete(row)


def _goes_window(value: str | None, name: str) -> float | None:
    if value is None:
        return None
    try:
        return parse_utc(value).timestamp() * 1000
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid {name}: '{value}'")


@app.get("/api/goes", response_model=GoesResponse)
async def get_goes(
    date: str = Query(..., description="Date YYYY-MM-DD"),
    start: str | None = Query(None, description="Optional ISO UTC start of the returned interval"),
    end: str | None = Query(None, description="Optional ISO UTC end of the returned interval"),
):
    """Return GOES XRS-B flux (0.1–0.8 nm channel) for a UTC day.

    Source: SunPy/Fido archive (NOAA NCEI science products). With start/end
    only the samples inside that interval are returned.
    """
    try:
        day = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid date format: '{date}'")
    start_ms, end_ms = _goes_window(start, "start"), _goes_window(end, "end")

    payload = None
    try:
        with session_scope() as session:
            cached_day = session.get(GoesDay, date)
            # Cached days of another payload format are refetched.
            if cached_day and cached_day.payload.get("format") == _GOES_PAYLOAD_FORMAT:
                payload = cached_day.payload
    except Exception as exc:
        logger.debug("Database GOES cache unavailable: %s", exc)

    if payload is None:
        recent = (datetime.now(timezone.utc).date() - day).days < _GOES_PUBLICATION_DELAY_DAYS
        unavailable_reason = (
            "GOES science data for this date are not published yet; NOAA releases them a few days after the UTC day ends"
            if recent else
            "GOES/XRS data are temporarily unavailable for this date; inspect server logs using the request id"
        )
        with _GOES_UNAVAILABLE_LOCK:
            now = time.monotonic()
            for key in [key for key, until in _GOES_UNAVAILABLE_UNTIL.items() if until <= now]:
                del _GOES_UNAVAILABLE_UNTIL[key]
            known_unavailable = date in _GOES_UNAVAILABLE_UNTIL
        if known_unavailable:
            return GoesResponse(date=date, available=False, reason=unavailable_reason, times=[], xrsb=[])
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(_GOES_EXECUTOR, _fetch_goes_xrsb_sync, date)
        except Exception as exc:
            logger.warning("GOES not available for %s: %s", date, exc)
            with _GOES_UNAVAILABLE_LOCK:
                _GOES_UNAVAILABLE_UNTIL[date] = time.monotonic() + _goes_unavailable_retry_seconds()
            return GoesResponse(date=date, available=False, reason=unavailable_reason, times=[], xrsb=[])
        payload = {"format": _GOES_PAYLOAD_FORMAT, **result}
        try:
            _store_goes_day(date, payload)
        except Exception as exc:
            logger.debug("Could not persist GOES cache: %s", exc)

    epochs, flux = _unpack_goes_series(payload["series"])
    times: list[str] = []
    values: list[float] = []
    for epoch_ms, value in zip(epochs, flux, strict=True):
        if (start_ms is None or epoch_ms >= start_ms) and (end_ms is None or epoch_ms <= end_ms):
            times.append(iso_ms(datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)))
            values.append(value)
    return GoesResponse(
        date=date,
        available=True,
        reason="",
        times=times,
        xrsb=values,
        satellite=payload.get("satellite"),
        product=payload.get("product"),
    )


def _mount_frontend() -> None:
    """Serve the production Vite build from the API in single-host deployments."""
    if os.environ.get("SERVE_FRONTEND", "").strip().lower() not in {"1", "true", "yes"}:
        return
    dist_dir = os.path.realpath(os.environ.get("FRONTEND_DIST_DIR", "frontend/dist"))
    if not os.path.isfile(os.path.join(dist_dir, "index.html")):
        logger.warning("SERVE_FRONTEND enabled but no index.html exists in %s", dist_dir)
        return
    app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")
    logger.info("Serving the AstroDoncel Studio frontend from %s", dist_dir)


_mount_frontend()
