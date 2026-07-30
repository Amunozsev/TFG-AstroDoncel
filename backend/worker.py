"""Dedicated polling worker for CPU/memory-heavy scientific jobs."""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select

from backend.db import BurstEvent, TaskRecord, init_db, session_scope

RESULT_DIR = os.environ.get("TASK_RESULT_DIR", os.path.join("data", "task_results"))
logger = logging.getLogger(__name__)


class TaskCancelled(Exception):
    """Raised at cooperative cancellation checkpoints."""


def _update(task_id: str, **values) -> None:
    with session_scope() as session:
        task = session.get(TaskRecord, task_id)
        for key, value in values.items():
            setattr(task, key, value)
        task.updated_at = datetime.now(timezone.utc)


def _check_cancelled(task_id: str) -> None:
    with session_scope() as session:
        task = session.get(TaskRecord, task_id)
        if task and task.status == "cancel_requested":
            raise TaskCancelled("Cancelled by user")


def recover_stale_tasks(stale_minutes: int | None = None) -> int:
    """Requeue interrupted work, or fail it when its retry budget is exhausted."""
    minutes = stale_minutes or int(os.environ.get("TASK_STALE_MINUTES", "15"))
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    recovered = 0
    with session_scope() as session:
        stale = session.scalars(select(TaskRecord).where(
            TaskRecord.status.in_(["running", "cancel_requested"]),
            TaskRecord.updated_at < cutoff,
        )).all()
        for task in stale:
            if task.status == "cancel_requested":
                task.status = "cancelled"
                task.error = "Cancellation completed after a stale worker heartbeat"
            else:
                task.status = "queued" if task.attempts < task.max_attempts else "failed"
                task.error = "Recovered after a stale worker heartbeat"
            task.updated_at = datetime.now(timezone.utc)
            recovered += 1
    return recovered


def cleanup_completed_tasks(retention_days: int | None = None) -> int:
    """Delete expired terminal tasks and only their strictly named artifacts."""
    days = retention_days if retention_days is not None else int(os.environ.get("TASK_RETENTION_DAYS", "30"))
    if days < 1:
        raise ValueError("TASK_RETENTION_DAYS must be at least 1")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    removed = 0
    result_root = os.path.realpath(RESULT_DIR)
    with session_scope() as session:
        expired = session.scalars(select(TaskRecord).where(
            TaskRecord.status.in_(["succeeded", "failed", "cancelled"]),
            TaskRecord.updated_at < cutoff,
        )).all()
        for task in expired:
            artifact = task.result.get("artifact") if task.result else None
            if artifact == f"{task.id}.json.gz":
                artifact_path = os.path.realpath(os.path.join(result_root, artifact))
                if os.path.commonpath((result_root, artifact_path)) == result_root:
                    try:
                        os.remove(artifact_path)
                    except FileNotFoundError:
                        pass
            session.delete(task)
            removed += 1
    return removed


def _write_artifact(task_id: str, payload: dict) -> str:
    os.makedirs(RESULT_DIR, exist_ok=True)
    filename = f"{task_id}.json.gz"
    path = os.path.join(RESULT_DIR, filename)
    temporary_path = f"{path}.{uuid.uuid4().hex}.part"
    try:
        with gzip.open(temporary_path, "wt", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
        os.replace(temporary_path, path)
    finally:
        try:
            os.remove(temporary_path)
        except OSError:
            pass
    return filename


def _burst_detect_day(task: TaskRecord) -> dict:
    from backend import burst_detect
    from backend import main as core

    station, date = task.payload["station"], task.payload["date"]
    filenames = sorted(set(core._list_local_fits_files(station, date)) | set(core._list_ethz_files(station, date)))
    detections = 0
    for index, filename in enumerate(filenames):
        _check_cancelled(task.id)
        path = core._download_from_ethz(station, date, filename)
        if not path:
            continue
        raw, freqs, times, header = core._load_raw_cached(path)
        result = burst_detect.detect_bursts(raw, freqs, core._time_offsets_seconds(times, header), core._observation_start(header))
        if result["is_burst"] or result["is_candidate"]:
            for event_index, event in enumerate(result["events"]):
                started = datetime.fromisoformat(event["start_utc"].replace("Z", "+00:00"))
                ended = datetime.fromisoformat(event["end_utc"].replace("Z", "+00:00"))
                key = f"{filename}:{event_index}:{event['start_utc']}"
                with session_scope() as session:
                    detection_source = (
                        "heuristic_visual" if result["event_source"].startswith("visual") else "ml_cnn"
                    )
                    exists = session.scalar(select(BurstEvent.id).where(
                        BurstEvent.source == detection_source, BurstEvent.event_key == key
                    ))
                    if not exists:
                        reports = session.scalars(
                            select(BurstEvent).where(
                                BurstEvent.source.in_([
                                    "dearce_v3",
                                    "ecallisto_v2",
                                    "legacy_monthly",
                                    "official_v2",
                                ]),
                                BurstEvent.started_at <= ended,
                                BurstEvent.ended_at >= started,
                            )
                        ).all()
                        matched = next((report for report in reports if station.upper() in report.stations), None)
                        session.add(BurstEvent(
                            source=detection_source, event_key=key, started_at=started, ended_at=ended,
                            burst_type=None, stations=[station], score=result["file_score"],
                            metadata_json={
                                "filename": filename, "event": event, "model_version": result["model_version"],
                                "model_sha256": result["model_sha256"],
                                "inference_method": result["inference_method"],
                                "localization_method": result["localization_method"],
                                "matched_official_event_id": matched.id if matched else None,
                                "matched_official_burst_type": matched.burst_type if matched else None,
                            },
                        ))
                        detections += 1
        _update(task.id, progress=(index + 1) / max(1, len(filenames)))
    return {"files_processed": len(filenames), "events_inserted": detections}


def _spectral_overview(task: TaskRecord) -> dict:
    from backend import main as core

    options = task.payload.get("options", {})
    stations = options.get("stations") or [task.payload["station"]]
    start_at = datetime.fromisoformat(
        options.get("start_at", f"{task.payload['date']}T00:00:00+00:00")
    ).astimezone(timezone.utc)
    end_at = datetime.fromisoformat(
        options.get("end_at", f"{task.payload['date']}T23:59:59+00:00")
    ).astimezone(timezone.utc)

    dates = []
    cursor = start_at.date()
    while cursor <= end_at.date():
        dates.append(cursor.isoformat())
        cursor += timedelta(days=1)

    work: list[tuple[str, str, str]] = []
    for station in stations:
        for date in dates:
            filenames = sorted(
                set(core._list_local_fits_files(station, date))
                | set(core._list_ethz_files(station, date))
            )
            work.extend((station, date, filename) for filename in filenames)

    loaded_by_station: dict[str, list[dict]] = {station: [] for station in stations}
    errors_by_station: dict[str, int] = {station: 0 for station in stations}
    for index, (station, date, filename) in enumerate(work):
        _check_cancelled(task.id)
        try:
            path = core._download_from_ethz(station, date, filename)
            if not path:
                raise ValueError("FITS file could not be downloaded")
            raw, frequencies, time_values, header = core._load_raw_cached(path)
            labels = core._times_to_utc(time_values, header)
            instants = [
                datetime.fromisoformat(label.replace("Z", "+00:00")).astimezone(timezone.utc)
                for label in labels
            ]
            selected_indices = [
                item for item, instant in enumerate(instants)
                if start_at <= instant < end_at
            ]
            if not selected_indices:
                continue
            selected_raw = raw[:, selected_indices]
            selected_labels = [labels[item] for item in selected_indices]
            width = min(120, selected_raw.shape[1])
            edges = np.linspace(0, selected_raw.shape[1], width + 1, dtype=int)
            # Maximum preserves short burst peaks that a block mean can erase.
            reduced = np.stack([
                np.nanmax(
                    selected_raw[:, edges[item]:max(edges[item] + 1, edges[item + 1])],
                    axis=1,
                )
                for item in range(width)
            ], axis=1)
            label_indices = np.minimum(
                selected_raw.shape[1] - 1,
                (edges[:-1] + edges[1:]) // 2,
            )
            loaded_by_station[station].append({
                "filename": filename,
                "freqs": np.asarray(frequencies),
                "raw": reduced,
                "times": [selected_labels[int(item)] for item in label_indices],
            })
        except Exception:
            errors_by_station[station] += 1
            logger.debug("Overview skipped %s/%s", station, filename, exc_info=True)
        finally:
            _update(task.id, progress=(index + 1) / max(1, len(work)) * 0.9)

    station_results = []
    total_segments = 0
    for station in stations:
        grouped: dict[tuple, list[dict]] = {}
        for segment in loaded_by_station[station]:
            key = tuple(np.round(segment["freqs"], 3).tolist())
            grouped.setdefault(key, []).append(segment)
        receiver_groups = []
        for group_index, segments in enumerate(grouped.values(), start=1):
            combined = np.concatenate([segment["raw"] for segment in segments], axis=1)
            baseline = np.nanmedian(combined, axis=1, keepdims=True)
            processed_group = np.nan_to_num(combined - baseline)
            vmin, vmax = core._percentile_clip_global(processed_group)
            output_segments = []
            for segment in segments:
                processed = np.nan_to_num(segment["raw"] - baseline)
                output_segments.append({
                    "filename": segment["filename"],
                    "time_axis": segment["times"],
                    "freq_axis": np.round(segment["freqs"], 3).tolist(),
                    "z": np.round(processed, 4).tolist(),
                })
            frequencies = segments[0]["freqs"]
            receiver_groups.append({
                "id": group_index,
                "frequency_min_mhz": round(float(np.nanmin(frequencies)), 3),
                "frequency_max_mhz": round(float(np.nanmax(frequencies)), 3),
                "vmin": vmin,
                "vmax": vmax,
                "segments": output_segments,
            })
            total_segments += len(output_segments)
        station_results.append({
            "station": station,
            "status": "ok" if receiver_groups else "no_data",
            "groups": receiver_groups,
            "files_skipped": errors_by_station[station],
        })

    if not any(result["status"] == "ok" for result in station_results):
        raise ValueError("No FITS observations were available inside the requested UTC interval")

    payload = {
        "start_at": start_at.isoformat(),
        "end_at": end_at.isoformat(),
        "stations": station_results,
        "baseline": "median per station and compatible receiver group",
        "intensity_unit": "relative detector digits",
        "downsample": "peak_preserving",
    }
    artifact = _write_artifact(task.id, payload)
    _update(task.id, progress=0.98)
    return {
        "stations_requested": len(stations),
        "stations_with_data": sum(result["status"] == "ok" for result in station_results),
        "segments": total_segments,
        "artifact_url": f"/api/tasks/{task.id}/artifact",
        "artifact": artifact,
    }


def _combine_time(task: TaskRecord) -> dict:
    from backend import main as core

    station, date = task.payload["station"], task.payload["date"]
    filenames = task.payload.get("options", {}).get("filenames", [])
    if not 2 <= len(filenames) <= 16:
        raise ValueError("combine_time needs 2 to 16 filenames")
    matrices, labels = [], []
    reference_freqs = None
    for index, filename in enumerate(filenames):
        _check_cancelled(task.id)
        path = core._download_from_ethz(station, date, filename)
        raw, freqs, time_values, header = core._load_raw_cached(path)
        if reference_freqs is None:
            reference_freqs = np.asarray(freqs)
        elif len(freqs) != len(reference_freqs) or not np.allclose(freqs, reference_freqs, atol=1e-3):
            raise ValueError(f"Incompatible frequency axis in {filename}")
        matrices.append(raw)
        labels.extend(core._times_to_utc(time_values, header))
        _update(task.id, progress=(index + 1) / len(filenames) * 0.8)
    processed = core._subtract_background(np.concatenate(matrices, axis=1))
    vmin, vmax = core._percentile_clip_global(processed)
    artifact = _write_artifact(task.id, {
        "station": station, "date": date, "filenames": filenames, "time_axis": labels,
        "freq_axis": np.round(reference_freqs, 3).tolist(),
        "z": np.round(np.nan_to_num(processed), 4).tolist(), "vmin": vmin, "vmax": vmax,
    })
    return {"files": len(filenames), "artifact_url": f"/api/tasks/{task.id}/artifact", "artifact": artifact}


HANDLERS = {
    "burst_detect_day": _burst_detect_day,
    "spectral_overview": _spectral_overview,
    "combine_time": _combine_time,
}


def run_once() -> bool:
    with session_scope() as session:
        task = session.scalar(
            select(TaskRecord)
            .where(TaskRecord.status == "queued")
            .order_by(TaskRecord.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if not task:
            return False
        task.status = "running"
        task.attempts += 1
        task.updated_at = datetime.now(timezone.utc)
        task_id = task.id
    with session_scope() as session:
        task = session.get(TaskRecord, task_id)
        try:
            result = HANDLERS[task.task_type](task)
            _check_cancelled(task.id)
            _update(task.id, status="succeeded", progress=1.0, result=result, error=None)
        except TaskCancelled as exc:
            _update(task.id, status="cancelled", error=str(exc))
        except Exception as exc:
            logger.exception("Task %s (%s) failed", task.id, task.task_type)
            status = "queued" if task.attempts < task.max_attempts else "failed"
            _update(task.id, status=status, error=str(exc))
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--cleanup-only", action="store_true")
    args = parser.parse_args()
    init_db()
    recover_stale_tasks()
    cleanup_completed_tasks()
    if args.cleanup_only:
        return
    last_recovery = time.monotonic()
    last_cleanup = time.monotonic()
    while True:
        worked = run_once()
        if args.once:
            return
        if not worked:
            time.sleep(args.poll_seconds)
        if time.monotonic() - last_recovery >= 60:
            recover_stale_tasks()
            last_recovery = time.monotonic()
        if time.monotonic() - last_cleanup >= 3600:
            cleanup_completed_tasks()
            last_cleanup = time.monotonic()


if __name__ == "__main__":
    main()
