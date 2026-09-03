"""Opt-in API -> persistent worker -> artifact check against the reported files.

Run with ASTRODONCEL_LIVE_COMBINE=1. Downloads public FITS into pytest's isolated
cache and never connects to or mutates the production NAS/database.
"""

import os

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend import main as core
from backend import worker
from backend.db import SessionLocal, TaskRecord


@pytest.mark.skipif(os.environ.get("ASTRODONCEL_LIVE_COMBINE") != "1", reason="opt-in public archive download")
@pytest.mark.parametrize("station,focus,times", [
    ("MEXICO-LANCE", "62", ["161459", "162959", "164459", "165959"]),
    ("MEXICO-LANCE", "63", ["161459", "162959", "164459", "165959"]),
    ("SPAIN-SIGUENZA", "02", ["161501", "163001", "164501", "170001"]),
])
def test_reported_hour_through_persistent_worker(station, focus, times):
    client = TestClient(core.app)
    filenames = [f"{station}_20260903_{stamp}_{focus}.fit.gz" for stamp in times]
    created = client.post("/api/tasks", json={
        "type": "combine_time", "station": station, "date": "2026-09-03",
        "options": {"filenames": filenames},
    })
    assert created.status_code == 202, created.text
    task_id = created.json()["id"]
    try:
        assert worker.run_once()
        status = client.get(f"/api/tasks/{task_id}").json()
        assert status["status"] == "succeeded", status
        artifact_response = client.get(status["result"]["artifact_url"])
        assert artifact_response.status_code == 200
        artifact = artifact_response.json()
        assert artifact["filenames"] == filenames
        assert artifact["focus_code"] == focus
        assert 3598 < artifact["duration_seconds"] < 3602
        assert artifact["time_axis"] == sorted(set(artifact["time_axis"]))
        assert 14380 < len(artifact["time_axis"]) <= 14400
        assert np.asarray(artifact["z"]).shape == (200, len(artifact["time_axis"]))
        print(f"{station} FC {focus}: {artifact['start_at']} -> {artifact['end_at']}, "
              f"{artifact['duration_seconds']} s, {len(artifact['time_axis'])} samples, 4 blocks")
    finally:
        with SessionLocal() as session:
            session.delete(session.get(TaskRecord, task_id))
            session.commit()
