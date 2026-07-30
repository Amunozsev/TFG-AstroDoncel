import uuid
from datetime import datetime, timedelta, timezone

import numpy as np

from backend.db import BurstEvent, SessionLocal, TaskRecord, init_db
from backend.worker import _burst_detect_day, recover_stale_tasks


def test_full_day_scan_reports_processed_skipped_and_existing_candidates(monkeypatch):
    from backend import burst_detect
    from backend import main as core

    task_id = str(uuid.uuid4())
    filename = f"TEST-SCAN_{task_id}_120000.fit"
    missing_filename = f"TEST-SCAN_{task_id}_121500.fit"
    event_key = f"{filename}:0:2026-07-30T12:00:00Z"
    task = TaskRecord(
        id=task_id,
        task_type="burst_detect_day",
        status="running",
        progress=0,
        payload={"station": "TEST-SCAN", "date": "2026-07-30", "options": {}},
    )
    with SessionLocal() as session:
        session.add(task)
        session.commit()

    monkeypatch.setattr(core, "_list_local_fits_files", lambda *_: [filename])
    monkeypatch.setattr(core, "_list_ethz_files", lambda *_: [filename, missing_filename])
    monkeypatch.setattr(
        core,
        "_download_from_ethz",
        lambda _station, _date, item: None if item == missing_filename else item,
    )
    monkeypatch.setattr(
        core,
        "_load_raw_cached",
        lambda _path: (np.ones((2, 2)), np.array([45.0, 46.0]), np.array([0.0, 1.0]), {}),
    )
    monkeypatch.setattr(core, "_time_offsets_seconds", lambda *_: np.array([0.0, 1.0]))
    monkeypatch.setattr(
        core,
        "_observation_start",
        lambda _header: datetime(2026, 7, 30, 12, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        burst_detect,
        "detect_bursts",
        lambda *_: {
            "is_burst": True,
            "is_candidate": True,
            "events": [{
                "start_utc": "2026-07-30T12:00:00Z",
                "end_utc": "2026-07-30T12:01:00Z",
                "peak_score": 0.91,
                "freq_band_mhz": [45.0, 46.0],
            }],
            "event_source": "sahan_window_postprocess",
            "file_score": 0.87,
            "model_version": "test",
            "model_sha256": "abc",
            "inference_method": "cnn_mil_onnx",
            "localization_method": "sahan_window_postprocess",
        },
    )

    try:
        first = _burst_detect_day(task)
        assert first["files_discovered"] == 2
        assert first["files_processed"] == 1
        assert first["files_skipped"] == 1
        assert first["events_found"] == 1
        assert first["events_inserted"] == 1
        assert first["ml_candidates"] == 1
        assert first["heuristic_candidates"] == 0
        assert first["recommended_candidates"] == 1
        assert first["candidates"][0]["is_new"] is True
        assert first["candidates"][0]["persisted"] is True
        assert first["candidates"][0]["is_recommended"] is True
        assert first["candidates"][0]["source"] == "ml_cnn"

        second = _burst_detect_day(task)
        assert second["events_found"] == 1
        assert second["events_inserted"] == 0
        assert second["candidates"][0]["is_new"] is False

        monkeypatch.setattr(
            burst_detect,
            "detect_bursts",
            lambda *_: {
                "is_burst": False,
                "is_candidate": True,
                "events": [{
                    "start_utc": "2026-07-30T12:00:00Z",
                    "end_utc": "2026-07-30T12:01:00Z",
                    "peak_score": 0.55,
                    "freq_band_mhz": [45.0, 46.0],
                }],
                "event_source": "visual_candidate",
                "file_score": 0.55,
                "model_version": "test",
                "model_sha256": "abc",
                "inference_method": "cnn_mil_onnx",
                "localization_method": "visual_candidate",
            },
        )
        visual = _burst_detect_day(task)
        assert visual["ml_candidates"] == 0
        assert visual["heuristic_candidates"] == 1
        assert visual["recommended_candidates"] == 0
        assert visual["events_inserted"] == 0
        assert visual["candidates"][0]["id"] is None
        assert visual["candidates"][0]["persisted"] is False
        assert visual["candidates"][0]["is_new"] is False
    finally:
        with SessionLocal() as session:
            detection = session.query(BurstEvent).filter(BurstEvent.event_key == event_key).one_or_none()
            if detection:
                session.delete(detection)
            stored_task = session.get(TaskRecord, task_id)
            if stored_task:
                session.delete(stored_task)
            session.commit()


def test_stale_running_task_is_requeued():
    init_db()
    task_id = str(uuid.uuid4())
    with SessionLocal() as session:
        session.add(TaskRecord(
            id=task_id,
            task_type="spectral_overview",
            status="running",
            progress=0.2,
            payload={"station": "MRO", "date": "2024-01-01", "options": {}},
            attempts=1,
            max_attempts=2,
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
            updated_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ))
        session.commit()
    try:
        assert recover_stale_tasks(stale_minutes=15) >= 1
        with SessionLocal() as session:
            task = session.get(TaskRecord, task_id)
            assert task.status == "queued"
            assert "stale worker heartbeat" in task.error
    finally:
        with SessionLocal() as session:
            task = session.get(TaskRecord, task_id)
            if task:
                session.delete(task)
                session.commit()
