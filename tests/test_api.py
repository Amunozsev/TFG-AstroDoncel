from fastapi.testclient import TestClient

from backend import api_features
from backend import main as core
from backend.db import SessionLocal, TaskRecord
from backend.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200


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


def test_xmatch_timeline_builds_clickable_station_events(monkeypatch):
    event = {
        "id": 7,
        "source": "dearce_v3",
        "source_label": "deARCE detection (v3)",
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
