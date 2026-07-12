"""Feature routers kept separate from the legacy scientific core."""

from __future__ import annotations

import io
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
from astropy.io import fits
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.catalog import ingest_month, list_events, station_statistics
from backend.db import TaskRecord, init_db, session_scope
from backend.security import safe_join, validate_date, validate_filename_context, validate_station

router = APIRouter(prefix="/api", tags=["analysis"])


class TaskCreate(BaseModel):
    type: str
    station: str
    date: str
    options: dict = Field(default_factory=dict)


class TypeIIBandSplitRequest(BaseModel):
    upper_time_seconds: list[float]
    upper_freqs_mhz: list[float]
    lower_time_seconds: list[float]
    lower_freqs_mhz: list[float]
    analysis_frequency_mhz: float
    shock_speed_km_s: float


def _range(start: str, end: str | None) -> tuple[datetime, datetime]:
    try:
        start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
        end_dt = datetime.fromisoformat(end).replace(tzinfo=timezone.utc) if end else start_dt + timedelta(days=1)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Dates must use ISO format YYYY-MM-DD") from exc
    if end_dt <= start_dt or end_dt - start_dt > timedelta(days=366):
        raise HTTPException(status_code=422, detail="Date range must be positive and at most 366 days")
    return start_dt, end_dt


def _ensure_months(start: datetime, end: datetime) -> list[str]:
    warnings: list[str] = []
    cursor = start.replace(day=1)
    while cursor < end:
        try:
            ingest_month(cursor.year, cursor.month)
        except Exception as exc:
            warnings.append(f"{cursor:%Y-%m}: {exc}")
        cursor = (cursor + timedelta(days=32)).replace(day=1)
    return warnings


@router.get("/bursts")
def get_bursts(
    start: str = Query(..., description="Inclusive YYYY-MM-DD"),
    end: str | None = Query(None, description="Exclusive YYYY-MM-DD"),
    station: str | None = None,
    burst_type: str | None = Query(None, alias="type"),
    source: str | None = None,
):
    start_dt, end_dt = _range(start, end)
    if station:
        try:
            station = validate_station(station)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    warnings = _ensure_months(start_dt, end_dt)
    events = list_events(start_dt, end_dt, station, burst_type, source)
    return {"events": events, "count": len(events), "warnings": warnings}


@router.get("/stats/stations")
def get_station_stats(start: str, end: str | None = None):
    start_dt, end_dt = _range(start, end)
    warnings = _ensure_months(start_dt, end_dt)
    ranking = station_statistics(start_dt, end_dt)
    return {"ranking": ranking, "count": len(ranking), "warnings": warnings}


@router.get("/stats/timeline")
def get_event_timeline(start: str, end: str | None = None):
    start_dt, end_dt = _range(start, end)
    _ensure_months(start_dt, end_dt)
    counts: dict[str, int] = {}
    for event in list_events(start_dt, end_dt):
        day = event["started_at"][:10]
        counts[day] = counts.get(day, 0) + 1
    return {"points": [{"date": day, "count": counts[day]} for day in sorted(counts)]}


@router.get("/xmatch")
def cross_match_events(start: str, end: str | None = None, tolerance_minutes: int = Query(5, ge=0, le=60)):
    """Cross-match ML candidates against official radio-burst reports."""
    start_dt, end_dt = _range(start, end)
    events = list_events(start_dt, end_dt)
    ml = [event for event in events if event["source"] == "ml"]
    official = [event for event in events if event["source"] != "ml"]
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


@router.post("/analysis/type-ii-band-split")
def type_ii_band_split(payload: TypeIIBandSplitRequest):
    from backend.type_ii import calculate

    try:
        return calculate(
            payload.upper_time_seconds, payload.upper_freqs_mhz,
            payload.lower_time_seconds, payload.lower_freqs_mhz,
            payload.analysis_frequency_mhz, payload.shock_speed_km_s,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _resolve_file(station: str, date: str, filename: str) -> str:
    from backend import main as core

    station = validate_station(station)
    validate_date(date)
    filename = validate_filename_context(filename, station, date)
    local = safe_join(core.DATA_DIR_LOCAL, filename)
    if os.path.isfile(local):
        return local
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
def export_processed_fits(station: str, date: str, filename: str, rfi: bool = False):
    from backend import main as core

    try:
        path = _resolve_file(station, date, filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    data, frequencies, time_axis, header = core._load_raw_cached(path)
    processed = core._subtract_background(data)
    if rfi:
        processed, _channels, _stats = core._mitigate_rfi(processed)
    primary = fits.PrimaryHDU(np.asarray(processed, dtype=np.float32), header=header)
    axes = fits.BinTableHDU.from_columns([
        fits.Column(name="FREQUENCY_MHZ", format="D", array=np.asarray(frequencies, dtype=float)),
    ], name="FREQUENCY_AXIS")
    buffer = io.BytesIO()
    fits.HDUList([primary, axes]).writeto(buffer)
    output = re.sub(r"\.fits?(?:\.gz)?$", "_processed.fits", os.path.basename(filename), flags=re.IGNORECASE)
    return Response(
        buffer.getvalue(), media_type="application/fits",
        headers={"Content-Disposition": f'attachment; filename="{output}"'},
    )


@router.post("/tasks", status_code=202)
def create_task(task: TaskCreate):
    allowed = {"burst_detect_day", "spectral_overview", "combine_time"}
    if task.type not in allowed:
        raise HTTPException(status_code=422, detail=f"Unsupported task type; choose {sorted(allowed)}")
    try:
        station = validate_station(task.station)
        date = validate_date(task.date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    task_id = str(uuid.uuid4())
    with session_scope() as session:
        session.add(TaskRecord(
            id=task_id, task_type=task.type, status="queued", progress=0.0,
            payload={"station": station, "date": date, "options": task.options},
        ))
    return {"id": task_id, "status": "queued"}


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


try:
    init_db()
except Exception:
    # Core FITS endpoints remain available if PostgreSQL is temporarily down.
    pass
