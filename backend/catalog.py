"""Parser, ingestion, queries and statistics for e-CALLISTO burst catalogues."""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from backend.db import BurstEvent, CatalogMonth, Station, engine, session_scope

ASTRODONCEL_REPORT_BASES = (
    "https://astrodoncel.uah.es/ecallistodata/burst_reports",
    "http://astrodoncel.uah.es/ecallistodata/burst_reports",
)
LEGACY_BURSTLIST_BASE = "http://soleil.i4ds.ch/solarradio/data/BurstLists/2010-yyyy_Monstein"
DEFAULT_CATALOG_SOURCE = "dearce_v3"
CATALOG_SOURCES = {
    "dearce_v3": {
        "label": "deARCE detection (v3)",
        "urls": [
            f"{base}/{{year}}/NCELESTINA_{{year}}_{{month:02d}}.link"
            for base in ASTRODONCEL_REPORT_BASES
        ] + [f"{LEGACY_BURSTLIST_BASE}/{{year}}/e-CALLISTO_{{year}}_{{month:02d}}.txt"],
    },
    "ecallisto_v2": {
        "label": "Official e-CALLISTO (v2)",
        "urls": [
            f"{base}/{{year}}/Ne-CALLISTO_{{year}}_{{month:02d}}.link"
            for base in ASTRODONCEL_REPORT_BASES
        ],
    },
    "legacy_monthly": {
        "label": "e-CALLISTO monthly report",
        "urls": [f"{LEGACY_BURSTLIST_BASE}/{{year}}/e-CALLISTO_{{year}}_{{month:02d}}.txt"],
    },
}


def _clean_station(token: str) -> str:
    return token.strip().strip("()[]").strip().upper().replace("_", "-")


def source_label(source: str) -> str:
    return CATALOG_SOURCES.get(source, {}).get("label", source)


def _optional_float(value: str) -> float | None:
    try:
        return float(value.strip())
    except (TypeError, ValueError):
        return None


def _plain_text(line: str) -> str:
    """Turn AstroDoncel .link HTML cells into their displayed tabular text."""
    return unescape(re.sub(r"<[^>]+>", "", line))


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def parse_burst_list(text: str, source: str = DEFAULT_CATALOG_SOURCE) -> list[dict]:
    events: list[dict] = []
    seen_keys: set[str] = set()
    for raw in text.splitlines():
        line = _plain_text(raw).strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"\t+", line)
        if len(parts) < 4:
            parts = re.split(r"\s{2,}", line, maxsplit=6)
        if len(parts) < 4 or not re.fullmatch(r"\d{8}", parts[0].strip()):
            continue
        if len(parts) >= 7:
            date_raw, time_raw, type_raw = (part.strip() for part in parts[:3])
            min_lon, mid_lon, max_lon = (_optional_float(value) for value in parts[3:6])
            station_raw = "\t".join(parts[6:])
        else:
            date_raw, time_raw, type_raw, station_raw = parts[:4]
            date_raw, time_raw, type_raw = date_raw.strip(), time_raw.strip(), type_raw.strip()
            min_lon = mid_lon = max_lon = None
        time_match = re.search(r"(\d{2}:\d{2})-(\d{2}:\d{2})", time_raw)
        if "#" in time_raw or not time_match:
            continue
        start_raw, end_raw = time_match.groups()
        normalized_time = f"{start_raw}-{end_raw}"
        try:
            started = datetime.strptime(date_raw + start_raw, "%Y%m%d%H:%M").replace(tzinfo=timezone.utc)
            ended = datetime.strptime(date_raw + end_raw, "%Y%m%d%H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if ended < started:
            ended += timedelta(days=1)
        burst_match = re.match(r"(?P<type>[A-Za-z]+)(?:[/ -]?(?P<intensity>[123]))?", type_raw.strip())
        burst_type = burst_match.group("type").upper() if burst_match else type_raw.strip().upper()
        intensity = int(burst_match.group("intensity")) if burst_match and burst_match.group("intensity") else None
        stations = [_clean_station(value) for value in station_raw.split(",")]
        stations = [value for value in stations if value]
        key = f"{date_raw}:{normalized_time}:{type_raw}:{','.join(stations)}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        events.append({
            "source": source, "event_key": key, "started_at": started, "ended_at": ended,
            "burst_type": burst_type, "intensity": intensity, "stations": stations,
            "min_lon": min_lon, "mid_lon": mid_lon, "max_lon": max_lon,
            "score": None, "metadata_json": {
                "raw_type": type_raw.strip(),
                "source_label": source_label(source),
            },
        })
    return events


def ingest_month(
    year: int,
    month: int,
    source: str = DEFAULT_CATALOG_SOURCE,
    force: bool = False,
) -> int:
    if not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")
    if source not in CATALOG_SOURCES:
        raise ValueError(f"unsupported catalogue source: {source}")
    year_month = f"{year:04d}-{month:02d}"
    cache_key = f"{source}:{year_month}"
    max_age = timedelta(hours=float(os.environ.get("CATALOG_REFRESH_HOURS", "12")))
    with session_scope() as session:
        cached = session.get(CatalogMonth, cache_key)
        if cached and not force:
            fetched_at = cached.fetched_at
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - fetched_at < max_age:
                return 0
    errors = []
    text = None
    for template in CATALOG_SOURCES[source]["urls"]:
        url = template.format(year=year, month=month)
        request = Request(url, headers={"User-Agent": "AstroDoncel/1.0"})
        try:
            with urlopen(request, timeout=20) as response:
                text = response.read().decode("utf-8", errors="replace")
            break
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    if text is None:
        raise OSError("; ".join(errors))
    if source == "dearce_v3" and "deARCE_v2" in text and "deARCE_v3" not in text:
        raise ValueError("monthly fallback identifies itself as deARCE_v2, not deARCE_v3")
    events = parse_burst_list(text, source)
    inserted = 0
    with session_scope() as session:
        existing = {
            row.event_key: row
            for row in session.scalars(select(BurstEvent).where(BurstEvent.source == source))
        }
        for event in events:
            stored = existing.get(event["event_key"])
            if stored is not None:
                stored.started_at = event["started_at"]
                stored.ended_at = event["ended_at"]
                stored.burst_type = event["burst_type"]
                stored.intensity = event["intensity"]
                stored.min_lon = event["min_lon"]
                stored.mid_lon = event["mid_lon"]
                stored.max_lon = event["max_lon"]
                stored.stations = event["stations"]
                stored.metadata_json = event["metadata_json"]
                continue
            if engine.dialect.name == "sqlite":
                statement = sqlite_insert(BurstEvent).values(**event).on_conflict_do_nothing(
                    index_elements=["source", "event_key"]
                )
                result = session.execute(statement)
                inserted += max(0, result.rowcount or 0)
            elif engine.dialect.name == "postgresql":
                statement = postgresql_insert(BurstEvent).values(**event).on_conflict_do_nothing(
                    index_elements=["source", "event_key"]
                )
                result = session.execute(statement)
                inserted += max(0, result.rowcount or 0)
            else:
                try:
                    with session.begin_nested():
                        session.add(BurstEvent(**event))
                        session.flush()
                except IntegrityError:
                    continue
                inserted += 1
            existing[event["event_key"]] = True
        station_sightings: dict[str, tuple[datetime, datetime]] = {}
        for event in events:
            for station_name in event["stations"]:
                first, last = station_sightings.get(
                    station_name,
                    (event["started_at"], event["ended_at"]),
                )
                station_sightings[station_name] = (
                    min(first, event["started_at"]),
                    max(last, event["ended_at"]),
                )
        for station_name, (first, last) in station_sightings.items():
            station = session.get(Station, station_name)
            if station is None:
                session.add(Station(
                    name=station_name,
                    first_seen_at=first,
                    last_seen_at=last,
                ))
            else:
                station.first_seen_at = min(_as_utc(station.first_seen_at) if station.first_seen_at else first, first)
                station.last_seen_at = max(_as_utc(station.last_seen_at) if station.last_seen_at else last, last)
                station.updated_at = datetime.now(timezone.utc)
        marker = session.get(CatalogMonth, cache_key)
        if marker is None:
            marker = CatalogMonth(key=cache_key, source=source, year_month=year_month)
            session.add(marker)
        marker.event_count = len(events)
        marker.fetched_at = datetime.now(timezone.utc)
    return inserted


def list_events(
    start: datetime,
    end: datetime,
    station: str | None = None,
    burst_type: str | None = None,
    source: str | None = None,
) -> list[dict]:
    with session_scope() as session:
        query = select(BurstEvent).where(BurstEvent.started_at >= start, BurstEvent.started_at < end)
        if source:
            query = query.where(BurstEvent.source == source)
        if burst_type:
            query = query.where(BurstEvent.burst_type == burst_type.upper())
        rows = session.scalars(query.order_by(BurstEvent.started_at.desc())).all()
        if station:
            station_upper = station.upper()
            rows = [row for row in rows if station_upper in row.stations]
        return [{
            "id": row.id, "source": row.source, "source_label": source_label(row.source),
            "started_at": row.started_at.replace(tzinfo=timezone.utc).isoformat(),
            "ended_at": row.ended_at.replace(tzinfo=timezone.utc).isoformat(),
            "burst_type": row.burst_type, "intensity": row.intensity,
            "min_lon": row.min_lon, "mid_lon": row.mid_lon, "max_lon": row.max_lon,
            "stations": row.stations, "score": row.score, "metadata": row.metadata_json,
        } for row in rows]


def station_statistics(
    start: datetime,
    end: datetime,
    source: str = DEFAULT_CATALOG_SOURCE,
) -> list[dict]:
    events = list_events(start, end, source=source)
    counts: dict[str, int] = {}
    for event in events:
        for station in event["stations"]:
            counts[station] = counts.get(station, 0) + 1
    return [{"station": station, "count": count} for station, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
