"""API endpoints and archive identifier security."""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np
import pytest
from astropy.io import fits
from fastapi.testclient import TestClient

from backend import api_features
from backend import main as core
from backend.db import SessionLocal, Station, TaskRecord
from backend.main import app
from backend.security import safe_join, validate_filename_context, validate_fits_filename, validate_station

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200


@pytest.mark.parametrize("value", [None, 42, {}, ["MRO"]])
def test_overview_rejects_non_string_station_entries(value):
    response = client.post("/api/tasks", json={
        "type": "spectral_overview", "station": "MRO", "date": "2024-01-01",
        "options": {"stations": [value]},
    })
    assert response.status_code == 422


def test_overview_rejects_non_canonical_date():
    response = client.post("/api/tasks", json={
        "type": "spectral_overview", "station": "MRO", "date": "2024-1-1",
    })
    assert response.status_code == 422


@pytest.mark.parametrize("limit", [0, -1])
@pytest.mark.parametrize("endpoint", ["/api/spectrogram", "/api/spectrogram/combine"])
def test_spectrogram_rejects_non_positive_bin_limit(endpoint, limit, monkeypatch):
    monkeypatch.setattr(core, "_build_spectrogram", lambda *_args, **_kwargs: pytest.fail("Invalid bins reached processing"))
    response = client.get(endpoint, params={
        "station": "MRO", "stations": "MRO", "date": "2024-01-01", "max_time_bins": limit,
    })
    assert response.status_code == 422


@pytest.mark.parametrize("frequency", ["nan", "inf", "-inf"])
def test_lightcurve_rejects_non_finite_frequency_before_file_access(frequency, monkeypatch):
    monkeypatch.setattr(api_features, "_resolve_file", lambda *_args: pytest.fail("Invalid frequency reached FITS I/O"))
    response = client.get("/api/lightcurve", params={
        "station": "MRO", "date": "2024-01-01", "filename": "MRO_20240101_120000.fit", "freq_mhz": frequency,
    })
    assert response.status_code == 422


def test_selected_nas_file_works_without_remote_archive(tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    folder = archive / "2024" / "01" / "01"
    folder.mkdir(parents=True)
    cache = tmp_path / "cache"
    cache.mkdir()
    filename = "MRO_20240101_120000.fit"
    fits.PrimaryHDU(np.arange(12).reshape(3, 4), header=fits.Header({
        "DATE-OBS": "2024-01-01", "TIME-OBS": "12:00:00",
        "CRVAL1": 0, "CDELT1": 0.25, "CRVAL2": 80, "CDELT2": -10,
    })).writeto(folder / filename)
    monkeypatch.setattr(core, "DATA_DIR_LOCAL", str(cache))
    monkeypatch.setattr(core, "ECALLISTO_DATA_DIR", str(archive))
    monkeypatch.setattr(core, "_list_ethz_files", lambda *_args: [])
    monkeypatch.setattr(core, "_FILES_CACHE", {})
    monkeypatch.setattr(core, "urlopen", lambda *_args, **_kwargs: pytest.fail("NAS file triggered a download"))
    assert filename in [entry["filename"] for entry in client.get(
        "/api/files", params={"station": "MRO", "date": "2024-01-01"},
    ).json()["files"]]
    response = client.get("/api/files/download", params={"station": "MRO", "date": "2024-01-01", "filename": filename})
    assert response.status_code == 200
    assert response.content == (folder / filename).read_bytes()
    assert list(cache.iterdir()) == []


def test_detector_response_retains_model_provenance(monkeypatch):
    from backend import burst_detect

    monkeypatch.setattr(burst_detect, "is_available", lambda: (True, ""))
    monkeypatch.setattr(core, "_download_from_ethz", lambda *_args, **_kwargs: "synthetic.fit")
    monkeypatch.setattr(core, "_load_raw_cached", lambda *_args: (
        np.ones((2, 3)), np.array([80, 45]), np.arange(3), {"DATE-OBS": "2024-01-01"},
    ))
    result = {
        "file_score": 0.8, "threshold": 0.6, "events": [], "inference_ms": 1,
        "model_sha256": "a" * 64, "inference_method": "cnn_mil_onnx",
        "localization_method": "sahan_window_postprocess", "bundle_name": "test-bundle",
    }
    monkeypatch.setattr(burst_detect, "detect_bursts", lambda *_args: result)
    response = client.get("/api/burst/detect", params={
        "station": "MRO", "date": "2024-01-01", "filename": "MRO_20240101_120000.fit",
    })
    assert response.status_code == 200
    for key in ("model_sha256", "inference_method", "localization_method", "bundle_name"):
        assert response.json()[key] == result[key]


def test_file_path_is_gone():
    response = client.get("/api/spectrogram", params={"station": "MRO", "date": "2024-01-01", "file_path": "C:/Windows/win.ini"})
    assert response.status_code == 410


def test_filename_traversal_rejected():
    response = client.get("/api/spectrogram", params={"station": "MRO", "date": "2024-01-01", "filename": "../secret.fit"})
    assert response.status_code == 422


def test_filename_context_rejected():
    response = client.get("/api/spectrogram", params={"station": "MRO", "date": "2024-01-01", "filename": "BIR_20240101_120000_01.fit.gz"})
    assert response.status_code == 422


def test_station_traversal_rejected():
    response = client.get("/api/files", params={"station": "../etc", "date": "2024-01-01"})
    assert response.status_code == 422


def test_invalid_task_type_rejected():
    response = client.post("/api/tasks", json={"type": "shell", "station": "MRO", "date": "2024-01-01"})
    assert response.status_code == 422


def test_combine_task_validates_filename_context():
    response = client.post("/api/tasks", json={
        "type": "combine_time", "station": "MRO", "date": "2024-01-01",
        "options": {"filenames": ["MRO_20240101_120000.fit.gz", "BIR_20240101_121500.fit.gz"]},
    })
    assert response.status_code == 422


def test_tasks_are_deduplicated_and_can_be_cancelled():
    body = {"type": "spectral_overview", "station": "MRO", "date": "2099-12-30", "options": {}}
    first = client.post("/api/tasks", json=body)
    second = client.post("/api/tasks", json=body)
    assert first.status_code == 202
    assert second.status_code == 202
    task_id = first.json()["id"]
    assert second.json() == {"id": task_id, "status": "queued", "deduplicated": True}
    cancelled = client.post(f"/api/tasks/{task_id}/cancel")
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "cancelled"
    with SessionLocal() as session:
        stored = session.get(TaskRecord, task_id)
        if stored:
                session.delete(stored)
                session.commit()


def test_spectral_overview_validates_interval_and_multiple_stations():
    response = client.post("/api/tasks", json={
        "type": "spectral_overview",
        "station": "MRO",
        "date": "2024-01-01",
        "options": {
            "stations": ["MRO", "BIR"],
            "start_at": "2024-01-01T02:15:00Z",
            "end_at": "2024-01-01T06:45:00Z",
        },
    })
    assert response.status_code == 202
    task_id = response.json()["id"]
    try:
        with SessionLocal() as session:
            stored = session.get(TaskRecord, task_id)
            assert stored.payload["options"]["stations"] == ["MRO", "BIR"]
            assert stored.payload["options"]["start_at"].startswith("2024-01-01T02:15")
    finally:
        with SessionLocal() as session:
            stored = session.get(TaskRecord, task_id)
            if stored:
                session.delete(stored)
                session.commit()


def test_spectral_overview_rejects_backwards_interval():
    response = client.post("/api/tasks", json={
        "type": "spectral_overview",
        "station": "MRO",
        "date": "2024-01-01",
        "options": {
            "stations": ["MRO"],
            "start_at": "2024-01-01T08:00:00Z",
            "end_at": "2024-01-01T07:00:00Z",
        },
    })
    assert response.status_code == 422


def test_combine_task_rejects_mixed_receivers_and_duplicate_copies():
    for filenames, message in [
        (["MRO_20240101_120000_01.fit.gz", "MRO_20240101_121500_02.fit.gz"], "different receivers"),
        (["MRO_20240101_120000_01.fit.gz", "MRO_20240101_120000_01.fits"], "unique observations"),
        (["MRO_20240101_120000_01.fit.gz", 42], "strings"),
    ]:
        response = client.post("/api/tasks", json={
            "type": "combine_time", "station": "MRO", "date": "2024-01-01",
            "options": {"filenames": filenames},
        })
        assert response.status_code == 422
        assert message in response.json()["detail"]


def test_removed_full_day_scan_task_is_rejected():
    response = client.post("/api/tasks", json={
        "type": "burst_detect_day", "station": "MRO", "date": "2024-01-01",
    })
    assert response.status_code == 422


def test_xmatch_timeline_builds_clickable_station_events(monkeypatch):
    event = {
        "id": 7,
        "source": "dearce_v3",
        "source_label": "deARCE (v3)",
        "started_at": "2026-07-24T12:04:00+00:00",
        "ended_at": "2026-07-24T12:05:00+00:00",
        "burst_type": "III",
        "intensity": 1,
        "min_lon": -7.9,
        "mid_lon": 11.1,
        "max_lon": 73.7,
        "stations": ["MRO"],
        "score": None,
        "metadata": {},
    }
    monkeypatch.setattr(api_features, "_ensure_months", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(api_features, "list_events", lambda *_args, **_kwargs: [event])
    monkeypatch.setattr(
        core,
        "_archive_inventory_for_date",
        lambda _date: {"MRO": ["MRO_20260724_120000_01.fit.gz"]},
    )
    result = api_features.get_xmatch_timeline("2026-07-24")
    row = result["rows"][0]
    assert row["station"] == "MRO"
    assert row["positive"] is True
    assert row["events"] == [event]
    assert row["availability"][0]["start_at"].startswith("2026-07-24T12:00:00")
    assert row["receivers"] == [{
        "focus_code": "01",
        "availability": row["availability"],
        "blocks": [{
            "filename": "MRO_20260724_120000_01.fit.gz",
            "start_at": row["availability"][0]["start_at"],
            "end_at": row["availability"][0]["end_at"],
        }],
    }]


def test_xmatch_timeline_keeps_simultaneous_focus_codes_separate(monkeypatch):
    event = {
        "id": 8,
        "started_at": "2026-08-25T10:25:00+00:00",
        "ended_at": "2026-08-25T10:28:00+00:00",
        "stations": ["GERMANY-DLR"],
    }
    monkeypatch.setattr(api_features, "_ensure_months", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(api_features, "list_events", lambda *_args, **_kwargs: [event])
    monkeypatch.setattr(
        core,
        "_archive_inventory_for_date",
        lambda _date: {
            "GERMANY-DLR": [
                "GERMANY-DLR_20260825_101500_01.fit.gz",
                "GERMANY-DLR_20260825_101500_02.fit.gz",
                "GERMANY-DLR_20260825_101500_03.fit.gz",
                "GERMANY-DLR_20260825_101500_62.fit.gz",
                "GERMANY-DLR_20260825_101501_63.fit.gz",
            ],
        },
    )

    result = api_features.get_xmatch_timeline("2026-08-25")

    row = result["rows"][0]
    assert [receiver["focus_code"] for receiver in row["receivers"]] == [
        "01", "02", "03", "62", "63",
    ]
    assert result["receiver_count"] == 5
    assert all(len(receiver["blocks"]) == 1 for receiver in row["receivers"])


def test_archive_inventory_fetch_is_single_flight_per_day(monkeypatch):
    date = "2042-01-01"
    calls = 0
    calls_lock = threading.Lock()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'<a href="MRO_20420101_120000_01.fit.gz">file</a>'

    def fake_urlopen(*_args, **_kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.03)
        return Response()

    monkeypatch.setattr(core, "urlopen", fake_urlopen)
    with core._ARCHIVE_DAY_CACHE_LOCK:
        core._ARCHIVE_DAY_CACHE.pop(date, None)
        core._ARCHIVE_DAY_FETCH_LOCKS.pop(date, None)

    with ThreadPoolExecutor(max_workers=3) as executor:
        inventories = list(executor.map(core._archive_inventory_for_date, [date] * 3))

    assert calls == 1
    assert all(inventory == {"MRO": ["MRO_20420101_120000_01.fit.gz"]} for inventory in inventories)


def test_station_inventory_hides_stale_rows_but_preserves_recent_and_live(monkeypatch):
    old_name = "TEST-RETIRED-STATION"
    recent_name = "TEST-RECENT-STATION"
    live_name = "TEST-LIVE-STATION"
    with SessionLocal() as session:
        session.merge(Station(
            name=old_name,
            first_seen_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            last_seen_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        ))
        session.merge(Station(
            name=recent_name,
            first_seen_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            last_seen_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        ))
        session.commit()
    monkeypatch.setenv("STATION_RETENTION_DAYS", "30")
    monkeypatch.setattr(core, "_scan_recent_ethz_stations", lambda: ([live_name], "2026-08-24"))
    try:
        result = core.get_stations()
        assert live_name in result.stations
        assert recent_name in result.stations
        assert old_name not in result.stations
        assert result.retention_days == 30
    finally:
        with SessionLocal() as session:
            for name in (old_name, recent_name):
                row = session.get(Station, name)
                if row:
                    session.delete(row)
            session.commit()


# Archive identifiers and path safety

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
