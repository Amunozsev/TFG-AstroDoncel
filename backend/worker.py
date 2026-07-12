"""Dedicated polling worker for CPU/memory-heavy scientific jobs."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import time
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select

from backend.db import BurstEvent, TaskRecord, init_db, session_scope

RESULT_DIR = os.environ.get("TASK_RESULT_DIR", os.path.join("data", "task_results"))


def _update(task_id: str, **values) -> None:
    with session_scope() as session:
        task = session.get(TaskRecord, task_id)
        for key, value in values.items():
            setattr(task, key, value)
        task.updated_at = datetime.now(timezone.utc)


def _write_artifact(task_id: str, payload: dict) -> str:
    os.makedirs(RESULT_DIR, exist_ok=True)
    filename = f"{task_id}.json.gz"
    path = os.path.join(RESULT_DIR, filename)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"))
    return filename


def _burst_detect_day(task: TaskRecord) -> dict:
    from backend import burst_detect
    from backend import main as core

    station, date = task.payload["station"], task.payload["date"]
    filenames = sorted(set(core._list_local_fits_files(station, date)) | set(core._list_ethz_files(station, date)))
    detections = 0
    for index, filename in enumerate(filenames):
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
                    exists = session.scalar(select(BurstEvent.id).where(BurstEvent.source == "ml", BurstEvent.event_key == key))
                    if not exists:
                        reports = session.scalars(
                            select(BurstEvent).where(
                                BurstEvent.source != "ml",
                                BurstEvent.started_at <= ended,
                                BurstEvent.ended_at >= started,
                            )
                        ).all()
                        matched = next((report for report in reports if station.upper() in report.stations), None)
                        session.add(BurstEvent(
                            source="ml", event_key=key, started_at=started, ended_at=ended,
                            burst_type=matched.burst_type if matched else None, stations=[station], score=result["file_score"],
                            metadata_json={
                                "filename": filename, "event": event, "model_version": result["model_version"],
                                "matched_official_event_id": matched.id if matched else None,
                            },
                        ))
                        detections += 1
        _update(task.id, progress=(index + 1) / max(1, len(filenames)))
    return {"files_processed": len(filenames), "events_inserted": detections}


def _spectral_overview(task: TaskRecord) -> dict:
    from backend import main as core

    station, date = task.payload["station"], task.payload["date"]
    filenames = sorted(set(core._list_local_fits_files(station, date)) | set(core._list_ethz_files(station, date)))
    loaded = []
    for index, filename in enumerate(filenames):
        try:
            path = core._download_from_ethz(station, date, filename)
            raw, frequencies, time_values, header = core._load_raw_cached(path)
            labels = core._times_to_utc(time_values, header)
            width = min(160, raw.shape[1])
            edges = np.linspace(0, raw.shape[1], width + 1, dtype=int)
            # Maximum preserves short burst peaks that a block mean can erase.
            reduced = np.stack([np.nanmax(raw[:, edges[i]:max(edges[i] + 1, edges[i + 1])], axis=1) for i in range(width)], axis=1)
            label_indices = np.minimum(raw.shape[1] - 1, (edges[:-1] + edges[1:]) // 2)
            loaded.append({
                "filename": filename, "freqs": np.asarray(frequencies), "raw": reduced,
                "times": [labels[int(item)] for item in label_indices],
            })
        except Exception:
            continue
        _update(task.id, progress=(index + 1) / max(1, len(filenames)))
    if not loaded:
        raise ValueError("No compatible FITS files were available for the daily overview")
    # Use the largest compatible receiver/frequency group.
    groups: dict[tuple, list[dict]] = {}
    for segment in loaded:
        key = tuple(np.round(segment["freqs"], 3).tolist())
        groups.setdefault(key, []).append(segment)
    selected = max(groups.values(), key=len)
    baseline = np.nanmedian(np.concatenate([segment["raw"] for segment in selected], axis=1), axis=1, keepdims=True)
    panels = [{"start_hour": hour, "end_hour": hour + 4, "segments": []} for hour in range(0, 24, 4)]
    for segment in selected:
        hour = int(segment["times"][0][11:13])
        processed = np.nan_to_num(segment["raw"] - baseline)
        panels[min(5, hour // 4)]["segments"].append({
            "filename": segment["filename"], "time_axis": segment["times"],
            "freq_axis": np.round(segment["freqs"], 3).tolist(), "z": np.round(processed, 4).tolist(),
        })
    artifact = _write_artifact(task.id, {"station": station, "date": date, "panels": panels, "baseline": "daily_median", "downsample": "peak_preserving"})
    return {"segments": len(selected), "panels": 6, "artifact_url": f"/api/tasks/{task.id}/artifact", "artifact": artifact}


def _combine_time(task: TaskRecord) -> dict:
    from backend import main as core

    station, date = task.payload["station"], task.payload["date"]
    filenames = task.payload.get("options", {}).get("filenames", [])
    if not 2 <= len(filenames) <= 16:
        raise ValueError("combine_time needs 2 to 16 filenames")
    matrices, labels = [], []
    reference_freqs = None
    for index, filename in enumerate(filenames):
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
            _update(task.id, status="succeeded", progress=1.0, result=result, error=None)
        except Exception as exc:
            status = "queued" if task.attempts < task.max_attempts else "failed"
            _update(task.id, status=status, error=str(exc))
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    init_db()
    while True:
        worked = run_once()
        if args.once:
            return
        if not worked:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
