"""Feature routers kept separate from the legacy scientific core."""

from __future__ import annotations

import io
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
from astropy.io import fits
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from backend.catalog import (
    CATALOG_SOURCES,
    DEFAULT_CATALOG_SOURCE,
    ingest_month,
    list_events,
    source_label,
    station_statistics,
)
from backend.db import TaskRecord, session_scope
from backend.security import (
    validate_combine_filenames,
    validate_date,
    validate_filename_context,
    validate_station,
)
from backend.version import APP_NAME, APP_VERSION

router = APIRouter(prefix="/api", tags=["analysis"])
_TASK_CREATE_LOCK = threading.Lock()
logger = logging.getLogger(__name__)


class TaskCreate(BaseModel):
    type: str
    station: str
    date: str
    options: dict = Field(default_factory=dict)


def _range(start: str, end: str | None) -> tuple[datetime, datetime]:
    try:
        start_dt = _task_instant(start, "start")
        end_dt = _task_instant(end, "end") if end else start_dt + timedelta(days=1)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Dates must use ISO format YYYY-MM-DD") from exc
    if end_dt <= start_dt or end_dt - start_dt > timedelta(days=366):
        raise HTTPException(status_code=422, detail="Date range must be positive and at most 366 days")
    return start_dt, end_dt


def _task_instant(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{field_name} must be an ISO date-time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field_name} must be an ISO date-time") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ensure_months(
    start: datetime,
    end: datetime,
    source: str = DEFAULT_CATALOG_SOURCE,
) -> list[str]:
    warnings: list[str] = []
    cursor = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cursor < end:
        try:
            ingest_month(cursor.year, cursor.month, source=source)
        except Exception as exc:
            logger.warning("Catalogue refresh failed for %s %s: %s", source, cursor.strftime("%Y-%m"), exc)
            if source == "uah_mysql":
                warnings.append(f"{cursor:%Y-%m}: the UAH database is temporarily unavailable")
            else:
                warnings.append(f"{cursor:%Y-%m}: {exc}")
        cursor = (cursor + timedelta(days=32)).replace(day=1)
    return warnings


@router.get("/bursts")
def get_bursts(
    start: str = Query(..., description="Inclusive YYYY-MM-DD"),
    end: str | None = Query(None, description="Exclusive YYYY-MM-DD"),
    station: str | None = Query(None, description="Case-insensitive station name fragment"),
    burst_type: str | None = Query(None, alias="type"),
    source: str = DEFAULT_CATALOG_SOURCE,
):
    start_dt, end_dt = _range(start, end)
    if station:
        try:
            station = validate_station(station)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if source not in CATALOG_SOURCES:
        raise HTTPException(status_code=422, detail=f"Unknown catalogue source: {source}")
    warnings = _ensure_months(start_dt, end_dt, source)
    events = list_events(start_dt, end_dt, station, burst_type, source)
    unfiltered_events = events if not burst_type else list_events(start_dt, end_dt, station, source=source)
    return {
        "events": events,
        "count": len(events),
        "source": source,
        "source_label": source_label(source),
        "available_types": sorted({
            event["burst_type"] for event in unfiltered_events if event.get("burst_type")
        }),
        "available_sources": [
            {"id": key, "label": value["label"]}
            for key, value in CATALOG_SOURCES.items()
        ],
        "warnings": warnings,
    }


@router.get("/stats/stations")
def get_station_stats(
    start: str,
    end: str | None = None,
    source: str = DEFAULT_CATALOG_SOURCE,
):
    start_dt, end_dt = _range(start, end)
    if source not in CATALOG_SOURCES:
        raise HTTPException(status_code=422, detail=f"Unknown catalogue source: {source}")
    warnings = _ensure_months(start_dt, end_dt, source)
    ranking = station_statistics(start_dt, end_dt, source)
    return {
        "ranking": ranking,
        "count": len(ranking),
        "source": source,
        "source_label": source_label(source),
        "warnings": warnings,
    }


@router.get("/stats/timeline")
def get_event_timeline(
    start: str,
    end: str | None = None,
    source: str = DEFAULT_CATALOG_SOURCE,
):
    start_dt, end_dt = _range(start, end)
    if source not in CATALOG_SOURCES:
        raise HTTPException(status_code=422, detail=f"Unknown catalogue source: {source}")
    _ensure_months(start_dt, end_dt, source)
    counts: dict[str, int] = {}
    for event in list_events(start_dt, end_dt, source=source):
        day = event["started_at"][:10]
        counts[day] = counts.get(day, 0) + 1
    points = []
    cursor = start_dt
    while cursor < end_dt:
        day = cursor.date().isoformat()
        points.append({"date": day, "count": counts.get(day, 0)})
        cursor += timedelta(days=1)
    return {"points": points, "source": source, "source_label": source_label(source)}


@router.get("/xmatch")
def cross_match_events(start: str, end: str | None = None, tolerance_minutes: int = Query(5, ge=0, le=60)):
    """Cross-match ML candidates against official radio-burst reports."""
    start_dt, end_dt = _range(start, end)
    events = list_events(start_dt, end_dt)
    ml = [event for event in events if event["source"] == "ml_cnn"]
    official = [event for event in events if event["source"] in CATALOG_SOURCES]
    tolerance = timedelta(minutes=tolerance_minutes)
    matches = []
    for candidate in ml:
        candidate_start = datetime.fromisoformat(candidate["started_at"])
        compatible = []
        for report in official:
            report_start = datetime.fromisoformat(report["started_at"])
            if abs(report_start - candidate_start) <= tolerance and set(candidate["stations"]) & set(report["stations"]):
                compatible.append(report)
        matches.append({"candidate": candidate, "reports": compatible})
    return {"matches": matches, "candidate_count": len(ml), "matched_count": sum(bool(item["reports"]) for item in matches)}


@router.get("/xmatch/timeline")
def get_xmatch_timeline(
    date: str,
    source: str = DEFAULT_CATALOG_SOURCE,
):
    """Build an interactive station/event timeline from live archive evidence."""
    from backend import main as core

    try:
        validate_date(date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if source not in CATALOG_SOURCES:
        raise HTTPException(status_code=422, detail=f"Unknown catalogue source: {source}")
    start_at = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
    end_at = start_at + timedelta(days=1)
    warnings = _ensure_months(start_at, end_at, source)
    events = list_events(start_at, end_at, source=source)
    inventory = core._archive_inventory_for_date(date)
    stations = set(inventory)
    for event in events:
        stations.update(event["stations"])

    nominal_minutes = int(os.environ.get("XMATCH_NOMINAL_BLOCK_MINUTES", "15"))

    def merged_availability(starts: list[datetime]) -> list[dict[str, str]]:
        merged: list[list[datetime]] = []
        for started in sorted(set(starts)):
            ended = min(started + timedelta(minutes=nominal_minutes), end_at)
            if merged and started <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], ended)
            else:
                merged.append([started, ended])
        return [
            {"start_at": started.isoformat(), "end_at": ended.isoformat()}
            for started, ended in merged
        ]

    rows = []
    for station in sorted(stations):
        starts: list[datetime] = []
        receiver_blocks: dict[str, list[tuple[datetime, datetime, str]]] = {}
        for filename in inventory.get(station, []):
            raw_time = core._time_from_filename(filename)
            try:
                started = datetime.fromisoformat(f"{date}T{raw_time}+00:00")
            except ValueError:
                continue
            ended = min(started + timedelta(minutes=nominal_minutes), end_at)
            starts.append(started)
            focus_code = core._focus_code_from_filename(filename) or "unknown"
            receiver_blocks.setdefault(focus_code, []).append((started, ended, filename))
        station_events = [
            event for event in events
            if station in event["stations"]
        ]
        receivers = []
        for focus_code, blocks in sorted(receiver_blocks.items()):
            ordered_blocks = sorted(blocks, key=lambda block: (block[0], block[2]))
            receivers.append({
                "focus_code": focus_code,
                "availability": merged_availability([block[0] for block in ordered_blocks]),
                "blocks": [
                    {
                        "filename": filename,
                        "start_at": started.isoformat(),
                        "end_at": ended.isoformat(),
                    }
                    for started, ended, filename in ordered_blocks
                ],
            })
        rows.append({
            "station": station,
            "positive": bool(station_events),
            "availability": merged_availability(starts),
            "receivers": receivers,
            "events": station_events,
        })
    return {
        "date": date,
        "source": source,
        "source_label": source_label(source),
        "rows": rows,
        "station_count": len(rows),
        "receiver_count": sum(len(row["receivers"]) for row in rows),
        "positive_count": sum(row["positive"] for row in rows),
        "availability_basis": (
            "Heuristic intervals inferred from live archive filename start times "
            f"using a nominal {nominal_minutes}-minute block duration. "
            "Focus codes are kept as separate receiver rows."
        ),
        "warnings": warnings,
    }


def _resolve_file(station: str, date: str, filename: str) -> str:
    from backend import main as core

    station = validate_station(station)
    validate_date(date)
    filename = validate_filename_context(filename, station, date)
    downloaded = core._download_from_ethz(station, date, filename)
    if not downloaded:
        raise HTTPException(status_code=404, detail="FITS file not found")
    return downloaded


@router.get("/files/download")
def download_fits(station: str, date: str, filename: str):
    try:
        path = _resolve_file(station, date, filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FileResponse(path, filename=os.path.basename(path), media_type="application/fits")


@router.get("/lightcurve")
def get_lightcurve(station: str, date: str, filename: str, freq_mhz: list[float] = Query(...)):
    from backend import main as core

    if not 1 <= len(freq_mhz) <= 8:
        raise HTTPException(status_code=422, detail="Select between 1 and 8 frequencies")
    if not all(np.isfinite(value) for value in freq_mhz):
        raise HTTPException(status_code=422, detail="Frequencies must be finite numbers in MHz")
    try:
        path = _resolve_file(station, date, filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    data, frequencies, time_axis, header = core._load_raw_cached(path)
    times = core._times_to_utc(time_axis, header)
    processed = core._subtract_background(data)
    curves = []
    for requested in freq_mhz:
        index = int(np.nanargmin(np.abs(np.asarray(frequencies) - requested)))
        curves.append({
            "requested_mhz": requested,
            "frequency_mhz": round(float(frequencies[index]), 3),
            "intensity": np.round(np.nan_to_num(processed[index], nan=0.0), 4).tolist(),
        })
    return {"station": station, "date": date, "filename": filename, "times": times, "curves": curves, "unit": "relative digits"}


@router.get("/spectrogram/export")
def export_processed_fits(
    station: str,
    date: str,
    filename: str,
    rfi: bool = False,
    rfi_z_thresh: float = Query(default=6.0, ge=0.5, le=20.0),
    rfi_occupancy: float = Query(default=0.15, ge=0.01, le=1.0),
    rfi_min_component: int = Query(default=9, ge=1, le=500),
    rfi_impulsive: bool = True,
    scale_mode: str = Query(default="relative", pattern="^(relative|median_db)$"),
):
    from backend import main as core

    try:
        path = _resolve_file(station, date, filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    data, frequencies, time_axis, header = core._load_raw_cached(path)
    if scale_mode == "median_db":
        data = data * (2500.0 / 255.0 / 25.4)
    processed = core._subtract_background(data)
    if rfi:
        processed, _channels, _stats = core._mitigate_rfi(
            processed,
            z_thresh=rfi_z_thresh,
            occupancy_thresh=rfi_occupancy,
            min_component_size=rfi_min_component,
            impulsive=rfi_impulsive,
        )
    export_header = header.copy()
    export_header["BUNIT"] = ("dB" if scale_mode == "median_db" else "relative detector digits", "Background-subtracted intensity")
    export_header["PROCVER"] = (f"{APP_NAME} {APP_VERSION}", "Processing software")
    export_header.add_history("AstroDoncel: per-frequency background subtraction applied")
    if scale_mode == "median_db":
        export_header.add_history("AstroDoncel: instrumental median_db scale factor 2500/255/25.4 applied")
    export_header.add_history(f"AstroDoncel: RFI mitigation applied={rfi}")
    if rfi:
        export_header.add_history(
            f"AstroDoncel: RFI z={rfi_z_thresh}, occupancy={rfi_occupancy}, "
            f"min_component={rfi_min_component}, impulsive={rfi_impulsive}"
        )
    primary = fits.PrimaryHDU(np.asarray(processed, dtype=np.float32), header=export_header)
    frequency_axis = fits.BinTableHDU.from_columns([
        fits.Column(name="FREQUENCY_MHZ", format="D", array=np.asarray(frequencies, dtype=float)),
    ], name="FREQUENCY_AXIS")
    offsets = core._time_offsets_seconds(time_axis, header)
    utc_times = core._times_to_utc(time_axis, header)
    time_axis_hdu = fits.BinTableHDU.from_columns([
        fits.Column(name="TIME_OFFSET_S", format="D", unit="s", array=offsets),
        fits.Column(name="TIME_UTC", format="26A", array=np.asarray(utc_times, dtype="S26")),
    ], name="TIME_AXIS")
    buffer = io.BytesIO()
    fits.HDUList([primary, frequency_axis, time_axis_hdu]).writeto(buffer, checksum=True)
    output = re.sub(r"\.fits?(?:\.gz)?$", "_processed.fits", os.path.basename(filename), flags=re.IGNORECASE)
    return Response(
        buffer.getvalue(), media_type="application/fits",
        headers={"Content-Disposition": f'attachment; filename="{output}"'},
    )


@router.post("/tasks", status_code=202)
def create_task(task: TaskCreate):
    allowed = {"spectral_overview", "combine_time"}
    if task.type not in allowed:
        raise HTTPException(status_code=422, detail=f"Unsupported task type; choose {sorted(allowed)}")
    try:
        station = validate_station(task.station)
        date = validate_date(task.date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    options = dict(task.options)
    if task.type == "spectral_overview":
        requested_stations = options.get("stations", [station])
        max_stations = int(os.environ.get("OVERVIEW_MAX_STATIONS", "120"))
        if not isinstance(requested_stations, list) or not 1 <= len(requested_stations) <= max_stations:
            raise HTTPException(
                status_code=422,
                detail=f"spectral_overview needs 1 to {max_stations} stations",
            )
        try:
            requested_stations = list(dict.fromkeys(validate_station(item) for item in requested_stations))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        default_start = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
        start_at = _task_instant(options.get("start_at", default_start.isoformat()), "start_at")
        end_at = _task_instant(
            options.get("end_at", (default_start + timedelta(days=1)).isoformat()),
            "end_at",
        )
        max_hours = float(os.environ.get("OVERVIEW_MAX_HOURS", "72"))
        if end_at <= start_at or end_at - start_at > timedelta(hours=max_hours):
            raise HTTPException(
                status_code=422,
                detail=f"spectral_overview interval must be positive and at most {max_hours:g} hours",
            )
        options["stations"] = requested_stations
        options["start_at"] = start_at.isoformat()
        options["end_at"] = end_at.isoformat()
    if task.type == "combine_time":
        try:
            options["filenames"] = validate_combine_filenames(options.get("filenames"), station, date)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = {"station": station, "date": date, "options": options}
    task_id = str(uuid.uuid4())
    with _TASK_CREATE_LOCK:
        with session_scope() as session:
            active = session.scalars(
                select(TaskRecord).where(
                    TaskRecord.task_type == task.type,
                    TaskRecord.status.in_(["queued", "running", "cancel_requested"]),
                )
            ).all()
            duplicate = next((item for item in active if item.payload == payload), None)
            if duplicate:
                return {"id": duplicate.id, "status": duplicate.status, "deduplicated": True}
            queued_count = len(session.scalars(
                select(TaskRecord.id).where(TaskRecord.status.in_(["queued", "running", "cancel_requested"]))
            ).all())
            if queued_count >= int(os.environ.get("MAX_ACTIVE_TASKS", "100")):
                raise HTTPException(status_code=429, detail="Task queue is full; retry later")
            session.add(TaskRecord(
                id=task_id, task_type=task.type, status="queued", progress=0.0,
                payload=payload,
            ))
    return {"id": task_id, "status": "queued", "deduplicated": False}


@router.post("/tasks/{task_id}/cancel", status_code=202)
def cancel_task(task_id: str):
    try:
        uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid task id") from exc
    with session_scope() as session:
        task = session.get(TaskRecord, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        statement = update(TaskRecord).where(TaskRecord.id == task_id)
        now = datetime.now(timezone.utc)
        changed = session.execute(statement.where(TaskRecord.status == "queued").values(
            status="cancelled", error="Cancelled before execution", updated_at=now,
        ))
        if changed.rowcount == 0:
            session.execute(statement.where(TaskRecord.status == "running").values(
                status="cancel_requested", updated_at=now,
            ))
        session.refresh(task)
        return {"id": task.id, "status": task.status}


@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    with session_scope() as session:
        task = session.scalar(select(TaskRecord).where(TaskRecord.id == task_id))
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return {
            "id": task.id, "type": task.task_type, "status": task.status,
            "progress": task.progress, "result": task.result, "error": task.error,
            "created_at": task.created_at, "updated_at": task.updated_at,
        }


@router.get("/tasks/{task_id}/artifact")
def get_task_artifact(task_id: str):
    try:
        uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid task id") from exc
    with session_scope() as session:
        task = session.get(TaskRecord, task_id)
        if not task or task.status != "succeeded" or not task.result:
            raise HTTPException(status_code=404, detail="Task artifact is not available")
        artifact = task.result.get("artifact")
    if artifact != f"{task_id}.json.gz":
        raise HTTPException(status_code=500, detail="Invalid task artifact metadata")
    root = os.environ.get("TASK_RESULT_DIR", os.path.join("data", "task_results"))
    path = os.path.realpath(os.path.join(root, artifact))
    if os.path.commonpath((os.path.realpath(root), path)) != os.path.realpath(root) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Task artifact is missing")
    with open(path, "rb") as handle:
        content = handle.read()
    return Response(content, media_type="application/json", headers={"Content-Encoding": "gzip"})
