import uuid
from datetime import datetime, timedelta, timezone

from backend.db import SessionLocal, TaskRecord, init_db
from backend.worker import recover_stale_tasks


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
