import os

import pytest

from backend.security import safe_join, validate_filename_context, validate_fits_filename, validate_station


@pytest.mark.parametrize("station", ["SPAIN-SIGUENZA", "MRO", "MEXICO_LANCE", "A1", "SWISS-Landschlacht"])
def test_valid_stations(station):
    assert validate_station(station) == station


@pytest.mark.parametrize("station", ["../etc", "A/B", "", " station", "A B", "A?x"])
def test_invalid_stations(station):
    with pytest.raises(ValueError):
        validate_station(station)


@pytest.mark.parametrize("filename", [
    "SPAIN-SIGUENZA_20240101_120000_01.fit.gz",
    "MRO_20240101_120000.fit",
    "AUSTRIA-UNIGRAZ_20240101_120000_62.fits.gz",
])
def test_valid_filenames(filename):
    assert validate_fits_filename(filename) == filename


@pytest.mark.parametrize("filename", ["../secret.fit", "C:\\x.fit", "x.fit", "x_20240101_120000.exe", "x_20241301_120000.fit"])
def test_invalid_filenames(filename):
    with pytest.raises(ValueError):
        validate_fits_filename(filename)


def test_filename_context_matches():
    value = "SPAIN-SIGUENZA_20240101_120000_01.fit.gz"
    assert validate_filename_context(value, "spain-siguenza", "2024-01-01") == value


def test_filename_context_rejects_other_station_or_date():
    value = "SPAIN-SIGUENZA_20240101_120000_01.fit.gz"
    with pytest.raises(ValueError):
        validate_filename_context(value, "MRO", "2024-01-01")
    with pytest.raises(ValueError):
        validate_filename_context(value, "SPAIN-SIGUENZA", "2024-01-02")


def test_safe_join_stays_below_root(tmp_path):
    result = safe_join(str(tmp_path), "MRO_20240101_120000_01.fit.gz")
    assert os.path.commonpath((str(tmp_path), result)) == str(tmp_path)
