from backend.catalog import parse_burst_list

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
    assert event["source"] == "official_v2"


def test_parse_burst_list_is_deterministic():
    first = parse_burst_list(SAMPLE)[0]["event_key"]
    assert first == parse_burst_list(SAMPLE)[0]["event_key"]
