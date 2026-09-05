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
from sqlalchemy import select, update

from backend.db import TaskRecord, init_db, session_scope
from backend.security import fits_focus_code, validate_combine_filenames

RESULT_DIR = os.environ.get("TASK_RESULT_DIR", os.path.join("data", "task_results"))
logger = logging.getLogger(__name__)


class TaskCancelled(Exception):
    """Raised at cooperative cancellation checkpoints."""


class TaskFailure(ValueError):
    """An actionable, path-free scientific task error safe to show publicly."""


def _update(task_id: str, **values) -> None:
    with session_scope() as session:
        values["updated_at"] = datetime.now(timezone.utc)
        statement = update(TaskRecord).where(TaskRecord.id == task_id)
        if values.get("status") in {"queued", "succeeded", "failed"}:
            # Compare-and-set: a late success/retry must not overwrite a
            # cancellation that the API has already accepted.
            changed = session.execute(statement.where(TaskRecord.status == "running").values(**values))
            if changed.rowcount == 0:
                session.execute(statement.where(TaskRecord.status == "cancel_requested").values(
                    status="cancelled", result=None, error="Cancelled by user",
                    updated_at=values["updated_at"],
                ))
        else:
            session.execute(statement.where(
                TaskRecord.status.in_(["running", "cancel_requested"]),
            ).values(**values))


def _check_cancelled(task_id: str) -> None:
    with session_scope() as session:
        task = session.get(TaskRecord, task_id)
        if task and task.status in {"cancel_requested", "cancelled"}:
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
            # A cancellation can arrive just after publication but before the
            # result is saved. Such terminal tasks still own their UUID artifact.
            artifact = f"{task.id}.json.gz"
            try:
                valid_id = str(uuid.UUID(task.id)) == task.id
            except ValueError:
                valid_id = False
            if valid_id:
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
        raise TaskFailure("No FITS observations were available inside the requested UTC interval")

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
    try:
        filenames = validate_combine_filenames(
            task.payload.get("options", {}).get("filenames"), station, date,
        )
    except ValueError as exc:
        raise TaskFailure(str(exc)) from exc
    matrices, labels = [], []
    reference_freqs = None
    previous_end = None
    previous_cadence = None
    overlap_samples_dropped = 0
    for index, filename in enumerate(filenames):
        _check_cancelled(task.id)
        path = core._download_from_ethz(station, date, filename)
        if not path:
            raise TaskFailure(f"Could not retrieve {filename}. Check archive availability and retry.")
        try:
            raw, freqs, time_values, header = core._load_raw_cached(path)
        except Exception as exc:
            # Do not return the local cache/NAS path in a public task error.
            raise TaskFailure(f"Could not read FITS data in {filename}. Check the source file and retry.") from exc
        if reference_freqs is None:
            reference_freqs = np.asarray(freqs)
        elif len(freqs) != len(reference_freqs) or not np.allclose(freqs, reference_freqs, rtol=0, atol=1e-3):
            raise TaskFailure(
                f"Incompatible frequency axis in {filename}. The receiver configuration changed; "
                "choose another starting block or use Spectral overview to view separate groups."
            )
        block_labels = core._times_to_utc(time_values, header)
        instants = np.array([
            datetime.fromisoformat(label.replace("Z", "+00:00")).timestamp()
            for label in block_labels
        ])
        if raw.shape != (len(freqs), len(instants)) or len(instants) < 2 or not np.all(np.diff(instants) > 0):
            raise TaskFailure(f"Invalid or non-increasing time axis in {filename}; cannot build a continuous observation.")
        cadence = float(np.median(np.diff(instants)))
        if previous_end is not None:
            # Recorder boundaries can jitter by a second or two. Do not shift
            # measured UTC times, bridge missing blocks, or keep duplicate time.
            tolerance = max(2.0, 1.5 * max(cadence, previous_cadence))
            gap = float(instants[0] - (previous_end + previous_cadence))
            if gap > tolerance:
                raise TaskFailure(
                    f"Missing observations before {filename} (gap {gap:.1f} s). "
                    "Choose consecutive blocks or use Spectral overview to display gaps."
                )
            if gap < -tolerance:
                raise TaskFailure(
                    f"Overlapping observations in {filename}. Select consecutive blocks from one receiver."
                )
            first = int(np.searchsorted(instants, previous_end, side="right"))
            if first == len(instants):
                raise TaskFailure(f"No new time samples in {filename}.")
            overlap_samples_dropped += first
            raw, block_labels = raw[:, first:], block_labels[first:]
        previous_end, previous_cadence = instants[-1], cadence
        matrices.append(raw)
        labels.extend(block_labels)
        _update(task.id, progress=(index + 1) / len(filenames) * 0.8)
    _check_cancelled(task.id)
    processed = core._subtract_background(np.concatenate(matrices, axis=1))
    vmin, vmax = core._percentile_clip_global(processed)
    start_instant = datetime.fromisoformat(labels[0].replace("Z", "+00:00")).timestamp()
    metadata = {
        "focus_code": fits_focus_code(filenames[0]),
        "start_at": labels[0], "end_at": labels[-1],
        "duration_seconds": round((previous_end + previous_cadence) - start_instant, 3),
        "overlap_samples_dropped": overlap_samples_dropped,
        "time_basis": "FITS DATE-OBS/TIME-OBS and time axis; no clock rounding",
    }
    artifact = _write_artifact(task.id, {
        "station": station, "date": date, "filenames": filenames, "time_axis": labels,
        "freq_axis": np.round(reference_freqs, 3).tolist(),
        "z": np.round(np.nan_to_num(processed), 4).tolist(), "vmin": vmin, "vmax": vmax,
        **metadata,
    })
    return {"files": len(filenames), "artifact_url": f"/api/tasks/{task.id}/artifact", "artifact": artifact, **metadata}


HANDLERS = {
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
        claimed = session.execute(update(TaskRecord).where(
            TaskRecord.id == task.id, TaskRecord.status == "queued",
        ).values(status="running", attempts=TaskRecord.attempts + 1, updated_at=datetime.now(timezone.utc)))
        if claimed.rowcount != 1:
            return False
        task_id = task.id
    with session_scope() as session:
        task = session.get(TaskRecord, task_id)
    try:
        _check_cancelled(task.id)
        result = HANDLERS[task.task_type](task)
        _check_cancelled(task.id)
        _update(task.id, status="succeeded", progress=1.0, result=result, error=None)
    except TaskCancelled as exc:
        _update(task.id, status="cancelled", error=str(exc))
    except Exception as exc:
        logger.exception("Task %s (%s) failed", task.id, task.task_type)
        status = "queued" if task.attempts < task.max_attempts else "failed"
        error = str(exc) if isinstance(exc, TaskFailure) else "Task processing failed; inspect server logs using the task id"
        _update(task.id, status=status, error=error)
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
