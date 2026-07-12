"""Validation and safe path resolution for user-controlled archive identifiers."""

from __future__ import annotations

import os
import re
from datetime import datetime

STATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
FITS_FILENAME_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]*_\d{8}_\d{6}"
    r"(?:_[A-Za-z0-9-]+)?\.fits?(?:\.gz)?$",
    re.IGNORECASE,
)


def validate_station(value: str) -> str:
    station = value.strip()
    if station != value or not STATION_RE.fullmatch(station):
        raise ValueError("Invalid station identifier")
    return station


def validate_date(value: str) -> str:
    datetime.strptime(value, "%Y-%m-%d")
    return value


def validate_fits_filename(value: str) -> str:
    if value != os.path.basename(value) or not FITS_FILENAME_RE.fullmatch(value):
        raise ValueError("Invalid CALLISTO FITS filename")
    stamp = re.search(r"_(\d{8})_(\d{6})(?:_|\.)", value)
    try:
        datetime.strptime("".join(stamp.groups()), "%Y%m%d%H%M%S")
    except (AttributeError, ValueError) as exc:
        raise ValueError("Invalid observation timestamp in FITS filename") from exc
    return value


def validate_filename_context(filename: str, station: str, date: str) -> str:
    clean = validate_fits_filename(filename)
    expected_date = datetime.strptime(validate_date(date), "%Y-%m-%d").strftime("%Y%m%d")
    match = re.match(r"^(?P<station>.+)_(?P<date>\d{8})_\d{6}", clean)
    if not match or match.group("station").upper() != validate_station(station).upper() or match.group("date") != expected_date:
        raise ValueError("Filename does not belong to the requested station and date")
    return clean


def safe_join(root: str, filename: str) -> str:
    """Join an archive filename and prove it remains below ``root``."""
    clean_name = validate_fits_filename(filename)
    root_real = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(root_real, clean_name))
    if os.path.commonpath((root_real, candidate)) != root_real:
        raise ValueError("Resolved path escapes the configured data directory")
    return candidate
