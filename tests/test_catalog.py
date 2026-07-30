from backend.catalog import DEFAULT_CATALOG_SOURCE, parse_burst_list

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
    assert event["metadata_json"]["source_label"] == "deARCE detection (v3)"
