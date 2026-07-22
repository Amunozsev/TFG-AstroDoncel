from fastapi.testclient import TestClient

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
