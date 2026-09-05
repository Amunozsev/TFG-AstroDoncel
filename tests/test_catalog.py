"""Catalogue parsing, source databases and synchronization."""

import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import Column, Float, Integer, MetaData, String, Table, create_engine, insert

from backend import catalog, catalog_mysql
from backend.catalog import DEFAULT_CATALOG_SOURCE, list_events, parse_burst_list
from backend.db import BurstEvent, CatalogMonth, normalize_database_url, session_scope

SAMPLE = """#Date\tTime\tType\tStations
20240101\t18:02-18:03\tIII/2\tMEXICO-LANCE, (USA-ARIZONA-ERAU)
20240101\t22:51-22:55\tCTM\tAustralia-ASSA
20240102\t##:##-##:##\t---\t---
bad line
"""


def test_parse_burst_list_rows():
    events = parse_burst_list(SAMPLE)
    assert len(events) == 2
    assert events[0]["burst_type"] == "III"
    assert events[0]["intensity"] == 2
    assert events[0]["stations"] == ["MEXICO-LANCE", "USA-ARIZONA-ERAU"]


def test_parse_burst_list_utc_and_source():
    event = parse_burst_list(SAMPLE)[1]
    assert event["started_at"].isoformat() == "2024-01-01T22:51:00+00:00"
    assert event["source"] == DEFAULT_CATALOG_SOURCE


def test_parse_burst_list_is_deterministic():
    first = parse_burst_list(SAMPLE)[0]["event_key"]
    assert first == parse_burst_list(SAMPLE)[0]["event_key"]


def test_parse_burst_list_ignores_duplicate_rows():
    duplicated = SAMPLE + "20240101\t18:02-18:03\tIII/2\tMEXICO-LANCE, (USA-ARIZONA-ERAU)\n"
    assert len(parse_burst_list(duplicated)) == 2


def test_parse_burst_list_rolls_end_into_next_day():
    event = parse_burst_list("20240101\t23:58-00:04\tIII\tMRO\n")[0]
    assert event["started_at"].isoformat() == "2024-01-01T23:58:00+00:00"
    assert event["ended_at"].isoformat() == "2024-01-02T00:04:00+00:00"


def test_parse_astrodoncel_link_rows_with_longitudes_and_html():
    sample = (
        '20260701\t<a href="daily.php">05:31-05:31</a>\tIII/1\t'
        '13.0\t73.7\t77.5\t'
        '<a href="spectro.php?station=GERMANY-DLR">GERMANY-DLR</a>, '
        '<a href="spectro.php?station=POLAND-BALDY">POLAND-BALDY</a>\n'
    )
    event = parse_burst_list(sample)[0]
    assert event["min_lon"] == 13.0
    assert event["mid_lon"] == 73.7
    assert event["max_lon"] == 77.5
    assert event["stations"] == ["GERMANY-DLR", "POLAND-BALDY"]
    assert event["metadata_json"]["source_label"] == "deARCE (v3)"


def test_list_events_matches_case_insensitive_station_fragment():
    started_at = datetime(2026, 8, 25, 11, 15, tzinfo=timezone.utc)
    with session_scope() as session:
        session.add(BurstEvent(
            source="test_partial_station",
            event_key="partial-station-search",
            started_at=started_at,
            ended_at=datetime(2026, 8, 25, 11, 16, tzinfo=timezone.utc),
            burst_type="III",
            stations=["BIR", "GLASGOW", "GERMANY-DLR"],
        ))

    events = list_events(
        datetime(2026, 8, 25, tzinfo=timezone.utc),
        datetime(2026, 8, 26, tzinfo=timezone.utc),
        station="glas",
        source="test_partial_station",
    )

    assert len(events) == 1
    assert "GLASGOW" in events[0]["stations"]


def test_event_key_fits_the_column_for_a_widely_observed_burst():
    stations = ", ".join(f"STATION-{index:03d}" for index in range(60))
    event = parse_burst_list(f"20260501\t15:26-15:29\tV/3\t{stations}\n")[0]
    assert len(event["stations"]) == 60
    assert len(event["event_key"]) <= BurstEvent.__table__.c.event_key.type.length


def test_event_key_still_separates_different_station_sets():
    shared_row = "20260501\t15:26-15:29\tV/3\t"
    first = parse_burst_list(shared_row + "BIR, GLASGOW\n")[0]
    second = parse_burst_list(shared_row + "BIR, HUMAIN\n")[0]
    assert first["event_key"] != second["event_key"]


def test_catalog_month_refresh_is_single_flight(monkeypatch):
    active = 0
    max_active = 0
    state_lock = threading.Lock()

    def fake_ingest(*_args, **_kwargs):
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.03)
        with state_lock:
            active -= 1
        return 1

    monkeypatch.setattr(catalog, "_ingest_month_locked", fake_ingest)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: catalog.ingest_month(2026, 8), range(4)))

    assert results == [1, 1, 1, 1]
    assert max_active == 1


# MySQL/MariaDB source and synchronization

def _row(event_id, date="20440101", time="23:58-00:04", intensity=2, remarks="checked"):
    return {
        "event_id": event_id,
        "date": date,
        "time": time,
        "key": "K-1",
        "type": "III",
        "intensity": intensity,
        "remarks": remarks,
        "stations": "BIR, GLASGOW",
        "min_lon": 0.0,
        "mid_lon": 11.2,
        "max_lon": 73.7,
    }


def test_mysql_configuration_keeps_special_password_literal(monkeypatch):
    monkeypatch.delenv("BURST_SOURCE_DATABASE_URL", raising=False)
    monkeypatch.setenv("BURST_SOURCE_MYSQL_HOST", "db.internal")
    monkeypatch.setenv("BURST_SOURCE_MYSQL_PORT", "3307")
    monkeypatch.setenv("BURST_SOURCE_MYSQL_DATABASE", "srbs_callisto")
    monkeypatch.setenv("BURST_SOURCE_MYSQL_USER", "studio_reader")
    monkeypatch.setenv("BURST_SOURCE_MYSQL_PASSWORD", "literal-$-password")

    url = catalog_mysql.configured_source_url()

    assert url.drivername == "mysql+pymysql"
    assert url.host == "db.internal"
    assert url.port == 3307
    assert url.password == "literal-$-password"


def test_read_rows_reflects_a_compatible_table(tmp_path):
    url = f"sqlite:///{(tmp_path / 'source.db').as_posix()}"
    engine = create_engine(url)
    metadata = MetaData()
    reports = Table(
        "burst_reports",
        metadata,
        Column("event_id", Integer),
        Column("Date", String),
        Column("Time", String),
        Column("Type", String),
        Column("Intensity", Integer),
        Column("Stations", String),
        Column("Min. Long.", Float),
        Column("Mid. Long.", Float),
        Column("Max. Long.", Float),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(reports).values({
            "event_id": 4,
            "Date": "20440101",
            "Time": "12:03-12:05",
            "Type": "V",
            "Intensity": 3,
            "Stations": "MRO",
            "Min. Long.": -7.9,
            "Mid. Long.": 5.3,
            "Max. Long.": 77.5,
        }))
    engine.dispose()

    rows = catalog_mysql.read_rows(source_url=url)

    assert rows == [{
        "event_id": 4,
        "date": "20440101",
        "time": "12:03-12:05",
        "type": "V",
        "intensity": 3,
        "stations": "MRO",
        "min_lon": -7.9,
        "mid_lon": 5.3,
        "max_lon": 77.5,
    }]


@pytest.mark.skipif(
    not os.environ.get("ASTRODONCEL_TEST_MYSQL_URL"),
    reason="No disposable MariaDB test service configured",
)
def test_read_rows_against_mariadb():
    url = os.environ["ASTRODONCEL_TEST_MYSQL_URL"]
    engine = create_engine(url)
    metadata = MetaData()
    reports = Table(
        "burst_reports_integration",
        metadata,
        Column("event_id", Integer),
        Column("Date", String(8)),
        Column("Time", String(20)),
        Column("Type", String(20)),
        Column("Intensity", Integer),
        Column("Stations", String(200)),
        Column("Min. Long.", Float),
        Column("Mid. Long.", Float),
        Column("Max. Long.", Float),
    )
    metadata.drop_all(engine, tables=[reports])
    metadata.create_all(engine, tables=[reports])
    try:
        with engine.begin() as connection:
            connection.execute(insert(reports).values({
                "event_id": 7,
                "Date": "20440103",
                "Time": "10:11-10:13",
                "Type": "II",
                "Intensity": 2,
                "Stations": "BIR",
                "Min. Long.": -1.0,
                "Mid. Long.": 2.0,
                "Max. Long.": 3.0,
            }))
        rows = catalog_mysql.read_rows(source_url=url, table_name=reports.name)
        assert rows[0]["event_id"] == 7
        assert rows[0]["stations"] == "BIR"
    finally:
        metadata.drop_all(engine, tables=[reports])
        engine.dispose()


def test_parse_uah_database_rows_preserves_metadata_and_midnight():
    event = catalog.parse_uah_database_rows([_row("external-1")], 2044, 1)[0]

    assert event["event_key"] == "mysql:external-1"
    assert event["started_at"] == datetime(2044, 1, 1, 23, 58, tzinfo=timezone.utc)
    assert event["ended_at"] == datetime(2044, 1, 2, 0, 4, tzinfo=timezone.utc)
    assert event["stations"] == ["BIR", "GLASGOW"]
    assert event["intensity"] == 2
    assert event["min_lon"] == 0.0
    assert event["metadata_json"]["key"] == "K-1"
    assert event["metadata_json"]["remarks"] == "checked"


def test_parse_uah_database_row_matches_the_published_export_shape():
    event = catalog.parse_uah_database_rows([{
        "event_id": 2026083001,
        "date": 20260830,
        "time": "01:14-01:21",
        "key": "---",
        "type": "---",
        "intensity": 2,
        "remarks": None,
        "stations": "INDIA-GAURI, INDONESIA, Australia-ASSA",
        "min_lon": 77.5,
        "mid_lon": 157.9,
        "max_lon": -145.2,
    }], 2026, 8)[0]

    assert event["event_key"] == "mysql:2026083001"
    assert event["burst_type"] is None
    assert event["stations"] == ["INDIA-GAURI", "INDONESIA", "AUSTRALIA-ASSA"]
    assert event["intensity"] == 2
    assert event["max_lon"] == -145.2
    assert event["metadata_json"]["key"] is None


def test_uah_database_sync_updates_and_removes_stale_events(monkeypatch):
    source = catalog_mysql.SOURCE_ID
    cache_key = f"{source}:2044-01"
    with session_scope() as session:
        for row in session.query(BurstEvent).filter(BurstEvent.source == source).all():
            session.delete(row)
        marker = session.get(CatalogMonth, cache_key)
        if marker:
            session.delete(marker)

    rows = [_row("one"), _row("two", date="20440102", time="12:00-12:01")]
    monkeypatch.setattr(catalog_mysql, "read_rows", lambda: rows)
    inserted = catalog.ingest_month(2044, 1, source=source, force=True)
    with session_scope() as session:
        assert session.query(BurstEvent).filter(BurstEvent.source == source).count() == 2
    assert inserted == 2
    assert catalog.ingest_month(2044, 1, source=source, force=True) == 0

    rows = [_row("one", intensity=3, remarks="corrected")]
    assert catalog.ingest_month(2044, 1, source=source, force=True) == 0

    events = catalog.list_events(
        datetime(2044, 1, 1, tzinfo=timezone.utc),
        datetime(2044, 2, 1, tzinfo=timezone.utc),
        source=source,
    )
    assert len(events) == 1
    assert events[0]["intensity"] == 3
    assert events[0]["metadata"]["remarks"] == "corrected"

    with session_scope() as session:
        for row in session.query(BurstEvent).filter(BurstEvent.source == source).all():
            session.delete(row)
        marker = session.get(CatalogMonth, cache_key)
        if marker:
            session.delete(marker)


# Database URL compatibility

def test_managed_postgres_urls_use_psycopg3():
    assert normalize_database_url("postgres://user:pass@db/name") == (
        "postgresql+psycopg://user:pass@db/name"
    )
    assert normalize_database_url("postgresql://user:pass@db/name") == (
        "postgresql+psycopg://user:pass@db/name"
    )
    assert normalize_database_url("sqlite:///data/test.db") == "sqlite:///data/test.db"


def test_migrations_accept_percent_encoded_database_passwords():
    # Offline SQL exercises the real Alembic environment without connecting to
    # a database. ConfigParser must never interpolate the encoded password.
    env = {**os.environ, "DATABASE_URL": "postgresql+psycopg://reader:encoded%25password@localhost/unused"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE stations" in result.stdout
