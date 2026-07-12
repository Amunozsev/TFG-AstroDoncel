"""Parser, ingestion, queries and statistics for official e-CALLISTO burst lists."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from sqlalchemy import select

from backend.db import BurstEvent, session_scope

BURSTLIST_BASE = "http://soleil.i4ds.ch/solarradio/data/BurstLists/2010-yyyy_Monstein"


def _clean_station(token: str) -> str:
    return token.strip().strip("()[]").strip().upper().replace("_", "-")


def parse_burst_list(text: str, source: str = "official_v2") -> list[dict]:
    events: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"\t+", line, maxsplit=3)
        if len(parts) < 4:
            parts = re.split(r"\s{2,}", line, maxsplit=3)
        if len(parts) < 4 or not re.fullmatch(r"\d{8}", parts[0]):
            continue
        date_raw, time_raw, type_raw, station_raw = parts
        if "#" in time_raw or "-" not in time_raw:
            continue
        start_raw, end_raw = time_raw.split("-", 1)
        try:
            started = datetime.strptime(date_raw + start_raw, "%Y%m%d%H:%M").replace(tzinfo=timezone.utc)
            ended = datetime.strptime(date_raw + end_raw, "%Y%m%d%H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        burst_match = re.match(r"(?P<type>[A-Za-z]+)(?:[/ -]?(?P<intensity>[123]))?", type_raw.strip())
        burst_type = burst_match.group("type").upper() if burst_match else type_raw.strip().upper()
        intensity = int(burst_match.group("intensity")) if burst_match and burst_match.group("intensity") else None
        stations = [_clean_station(value) for value in station_raw.split(",")]
        stations = [value for value in stations if value]
        key = f"{date_raw}:{time_raw}:{type_raw}:{','.join(stations)}"
        events.append({
            "source": source, "event_key": key, "started_at": started, "ended_at": ended,
            "burst_type": burst_type, "intensity": intensity, "stations": stations,
            "score": None, "metadata_json": {"raw_type": type_raw.strip()},
        })
    return events


def ingest_month(year: int, month: int, source: str = "official_v2") -> int:
    url = f"{BURSTLIST_BASE}/{year:04d}/e-CALLISTO_{year:04d}_{month:02d}.txt"
    request = Request(url, headers={"User-Agent": "AstroDoncel/1.0"})
    with urlopen(request, timeout=20) as response:
        events = parse_burst_list(response.read().decode("utf-8", errors="replace"), source)
    inserted = 0
    with session_scope() as session:
        existing = set(session.scalars(select(BurstEvent.event_key).where(BurstEvent.source == source)))
        for event in events:
            if event["event_key"] not in existing:
                session.add(BurstEvent(**event))
                inserted += 1
    return inserted


def list_events(start: datetime, end: datetime, station: str | None = None, burst_type: str | None = None, source: str | None = None) -> list[dict]:
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
            "id": row.id, "source": row.source,
            "started_at": row.started_at.replace(tzinfo=timezone.utc).isoformat(),
            "ended_at": row.ended_at.replace(tzinfo=timezone.utc).isoformat(),
            "burst_type": row.burst_type, "intensity": row.intensity,
            "stations": row.stations, "score": row.score,
        } for row in rows]


def station_statistics(start: datetime, end: datetime) -> list[dict]:
    events = list_events(start, end)
    counts: dict[str, int] = {}
    for event in events:
        for station in event["stations"]:
            counts[station] = counts.get(station, 0) + 1
    return [{"station": station, "count": count} for station, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
