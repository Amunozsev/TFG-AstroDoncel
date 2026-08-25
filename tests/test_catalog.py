from datetime import datetime, timezone

from backend.catalog import DEFAULT_CATALOG_SOURCE, list_events, parse_burst_list
from backend.db import BurstEvent, session_scope

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
