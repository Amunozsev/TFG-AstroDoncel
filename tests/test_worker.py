"""Worker recovery and block combination, including opt-in archive checks."""

import gzip
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend import main as core
from backend import worker
from backend.db import SessionLocal, TaskRecord, init_db
from backend.security import fits_focus_code, validate_combine_filenames
from backend.worker import recover_stale_tasks


def test_two_sqlite_workers_do_not_execute_the_same_queued_task(monkeypatch):
    task_id = str(uuid.uuid4())
    with SessionLocal() as session:
        session.add(TaskRecord(id=task_id, task_type="test_claim", status="queued", payload={}))
        session.commit()
    selected = threading.Barrier(2)
    original_scalar = SessionLocal.class_.scalar
    executions = []

    def scalar(session, statement, *args, **kwargs):
        result = original_scalar(session, statement, *args, **kwargs)
        if statement._for_update_arg is not None:
            selected.wait(timeout=5)
        return result

    monkeypatch.setattr(SessionLocal.class_, "scalar", scalar)
    monkeypatch.setitem(worker.HANDLERS, "test_claim", lambda task: executions.append(task.id) or {"files": 1})
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: worker.run_once(), range(2)))
        assert sorted(results) == [False, True]
        assert executions == [task_id]
        with SessionLocal() as session:
            task = session.get(TaskRecord, task_id)
            assert task.status == "succeeded"
            assert task.attempts == 1
    finally:
        with SessionLocal() as session:
            session.delete(session.get(TaskRecord, task_id))
            session.commit()


def test_cancellation_between_final_checkpoint_and_result_publication(monkeypatch):
    task_id = str(uuid.uuid4())
    with SessionLocal() as session:
        session.add(TaskRecord(id=task_id, task_type="test_late_cancel", status="queued", payload={}))
        session.commit()
    original_update = worker._update

    def update(task_id, **values):
        if values.get("status") == "succeeded":
            response = TestClient(core.app).post(f"/api/tasks/{task_id}/cancel")
            assert response.json()["status"] == "cancel_requested"
        original_update(task_id, **values)

    monkeypatch.setattr(worker, "_update", update)
    monkeypatch.setitem(worker.HANDLERS, "test_late_cancel", lambda _: {"files": 1})
    try:
        assert worker.run_once()
        with SessionLocal() as session:
            task = session.get(TaskRecord, task_id)
            assert task.status == "cancelled"
            assert task.result is None
    finally:
        with SessionLocal() as session:
            session.delete(session.get(TaskRecord, task_id))
            session.commit()


def test_retention_removes_late_cancelled_artifact_only(tmp_path, monkeypatch):
    task_id = str(uuid.uuid4())
    with SessionLocal() as session:
        session.add(TaskRecord(
            id=task_id, task_type="combine_time", status="cancelled", payload={}, result=None,
            updated_at=datetime.now(timezone.utc) - timedelta(days=40),
        ))
        session.commit()
    artifact = tmp_path / f"{task_id}.json.gz"
    artifact.write_bytes(b"cancelled result")
    unrelated = tmp_path / "preserved.json.gz"
    unrelated.write_bytes(b"unrelated result")
    monkeypatch.setattr(worker, "RESULT_DIR", str(tmp_path))
    assert worker.cleanup_completed_tasks(retention_days=30) == 1
    assert not artifact.exists()
    assert unrelated.read_bytes() == b"unrelated result"
    with SessionLocal() as session:
        assert session.get(TaskRecord, task_id) is None


@pytest.mark.parametrize("failure", [False, True])
def test_worker_honours_cancellation_during_handler(monkeypatch, failure):
    task_id = str(uuid.uuid4())
    with SessionLocal() as session:
        session.add(TaskRecord(id=task_id, task_type="test_cancel", status="queued", payload={}))
        session.commit()

    def handler(task):
        response = TestClient(core.app).post(f"/api/tasks/{task.id}/cancel")
        assert response.status_code == 202
        if failure:
            raise OSError("C:/private/cache: disk failure")
        return {"files": 2}

    monkeypatch.setitem(worker.HANDLERS, "test_cancel", handler)
    try:
        assert worker.run_once()
        with SessionLocal() as session:
            stored = session.get(TaskRecord, task_id)
            assert stored.status == "cancelled"
            assert stored.result is None
    finally:
        with SessionLocal() as session:
            session.delete(session.get(TaskRecord, task_id))
            session.commit()


def test_worker_does_not_publish_internal_error_paths(monkeypatch):
    task_id = str(uuid.uuid4())
    with SessionLocal() as session:
        session.add(TaskRecord(id=task_id, task_type="test_private", status="queued", payload={}, max_attempts=1))
        session.commit()

    def handler(_task):
        raise OSError("C:/private/cache: disk failure")

    monkeypatch.setitem(worker.HANDLERS, "test_private", handler)
    try:
        assert worker.run_once()
        response = TestClient(core.app).get(f"/api/tasks/{task_id}")
        assert response.json()["status"] == "failed"
        assert "C:/private" not in response.text
    finally:
        with SessionLocal() as session:
            session.delete(session.get(TaskRecord, task_id))
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


# Regression cases for the 2026-09-03 Mexico/Siguenza reports

def name(clock, receiver="62", extension="fit.gz"):
    suffix = f"_{receiver}" if receiver else ""
    return f"MEXICO-LANCE_20260903_{clock}{suffix}.{extension}"


@pytest.fixture
def combine(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "RESULT_DIR", str(tmp_path))
    monkeypatch.setattr(worker, "_update", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "_check_cancelled", lambda *_args: None)

    def run(starts, *, receivers=None, frequencies=None, missing=False, time_values=None):
        files = [name(start.strftime("%H%M%S"), (receivers or ["62"] * len(starts))[i]) for i, start in enumerate(starts)]
        datasets = {}
        for i, (filename, start) in enumerate(zip(files, starts, strict=True)):
            datasets[filename] = (
                np.full((2, 3600), i + 1.0),
                np.array((frequencies or [[80.0, 45.0]] * len(starts))[i]),
                np.arange(3600) * 0.25 if time_values is None else time_values,
                {"DATE-OBS": "2026/09/03", "TIME-OBS": start.strftime("%H:%M:%S.%f"), "CDELT1": 0.25},
            )
        monkeypatch.setattr(core, "_download_from_ethz", lambda _station, _date, filename: None if missing else filename)
        monkeypatch.setattr(core, "_load_raw_cached", lambda filename: datasets[filename])
        task = TaskRecord(id=str(uuid.uuid4()), payload={
            "station": "MEXICO-LANCE", "date": "2026-09-03", "options": {"filenames": files},
        })
        result = worker._combine_time(task)
        with gzip.open(tmp_path / result["artifact"], "rt") as handle:
            return result, json.load(handle)
    return run


def starts(clock="16:14:59.182", count=4):
    start = datetime.fromisoformat(f"2026-09-03T{clock}").replace(tzinfo=timezone.utc)
    return [start + timedelta(minutes=15 * i) for i in range(count)]


def test_four_blocks_cover_one_hour_with_exact_fits_times(combine):
    result, artifact = combine(starts())
    assert result["files"] == 4
    assert result["duration_seconds"] == pytest.approx(3600)
    assert artifact["focus_code"] == "62"
    assert len(artifact["time_axis"]) == 14400
    assert np.array(artifact["z"]).shape == (2, 14400)
    assert artifact["time_axis"][0] == "2026-09-03T16:14:59.182Z"
    assert artifact["time_axis"][-1] == "2026-09-03T17:14:58.932Z"
    assert artifact["time_axis"] == sorted(set(artifact["time_axis"]))


def test_small_recorder_overlap_is_trimmed_without_shifting_timestamps(combine):
    times = starts(count=2)
    times[1] -= timedelta(seconds=0.5)
    result, artifact = combine(times)
    assert result["overlap_samples_dropped"] == 2
    assert len(artifact["time_axis"]) == 7198
    assert artifact["time_axis"][3600] == "2026-09-03T16:29:59.182Z"
    assert artifact["time_axis"] == sorted(set(artifact["time_axis"]))


def test_gap_is_not_painted_as_a_continuous_observation(combine):
    times = starts(count=2)
    times[1] += timedelta(minutes=15)
    with pytest.raises(ValueError, match="Missing observations.*Spectral overview"):
        combine(times)


def test_large_overlap_is_rejected(combine):
    times = starts(count=2)
    times[1] -= timedelta(minutes=5)
    with pytest.raises(ValueError, match="Overlapping observations"):
        combine(times)


def test_non_increasing_time_axis_is_rejected(combine):
    with pytest.raises(ValueError, match="non-increasing time axis"):
        combine(starts(count=2), time_values=np.zeros(3600))


def test_small_clock_jitter_keeps_native_samples(combine):
    times = starts(count=2)
    times[1] += timedelta(seconds=0.2)
    result, artifact = combine(times)
    assert result["overlap_samples_dropped"] == 0
    assert len(artifact["time_axis"]) == 7200
    assert artifact["time_axis"][3600] == "2026-09-03T16:29:59.382Z"


def test_receiver_change_is_rejected_even_with_identical_frequency_axes(combine):
    with pytest.raises(ValueError, match="different receivers"):
        combine(starts(count=2), receivers=["62", "63"])


def test_configuration_change_has_actionable_error(combine):
    with pytest.raises(ValueError, match="Incompatible frequency axis.*configuration changed"):
        combine(starts(count=2), frequencies=[[80, 45], [79, 45]])


def test_download_failure_names_file_not_server_path(combine):
    with pytest.raises(ValueError, match="Could not retrieve MEXICO-LANCE.*retry"):
        combine(starts(count=2), missing=True)


def test_filename_validation_sorts_and_rejects_duplicate_copies():
    assert validate_combine_filenames([name("163000"), name("161500")], "MEXICO-LANCE", "2026-09-03") == [name("161500"), name("163000")]
    with pytest.raises(ValueError, match="unique observations"):
        validate_combine_filenames([name("161500"), name("161500", extension="fits")], "MEXICO-LANCE", "2026-09-03")


def test_no_focus_code_is_not_mistaken_for_observation_time():
    assert fits_focus_code(name("161500", receiver=None)) is None
    assert core._focus_code_from_filename(name("161500", receiver=None)) is None
    assert fits_focus_code(name("161500")) == "62"


# Opt-in API -> persistent worker -> artifact check.
# ASTRODONCEL_LIVE_COMBINE=1 downloads public FITS into the isolated test cache.

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
