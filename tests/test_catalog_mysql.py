import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import Column, Float, Integer, MetaData, String, Table, create_engine, insert

from backend import catalog, catalog_mysql
from backend.db import BurstEvent, CatalogMonth, session_scope


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
    assert catalog.ingest_month(2044, 1, source=source, force=True) == 2

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
