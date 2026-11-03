"""Two consecutive blocks used as one observation."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend import burst_types
from backend import main as core
from backend.main import app
from backend.observation import ObservationError, join_blocks

client = TestClient(app)
FIRST, SECOND = "MRO_20240101_120000_01.fit", "MRO_20240101_121500_01.fit"


def block(start: datetime, value: float):
    header = {"DATE-OBS": start.strftime("%Y/%m/%d"), "TIME-OBS": start.strftime("%H:%M:%S.%f"), "CDELT1": 0.25}
    return np.full((2, 3600), value), np.array([80.0, 45.0]), np.arange(3600) * 0.25, header


@pytest.fixture
def blocks(monkeypatch):
    def load(second_offset_s):
        t0 = datetime(2024, 1, 1, 12, tzinfo=timezone.utc)
        data = {
            FIRST: block(t0, 1.0),
            SECOND: block(t0 + timedelta(seconds=900 + second_offset_s), 2.0),
        }
        monkeypatch.setattr(core, "_load_raw_cached", lambda path: data[path])
        monkeypatch.setattr(core, "_download_from_ethz", lambda _station, _date, filename=None: filename)
    return load


def test_join_drops_overlap_and_rejects_gaps(blocks):
    blocks(-0.5)  # recorder overlap: two duplicated samples, measured times untouched
    joined = join_blocks([FIRST, SECOND])
    assert joined.data.shape == (2, 7198)
    assert joined.overlap_samples_dropped == 2
    assert joined.time_labels[3600] == "2024-01-01T12:15:00.000Z"
    assert joined.offsets_s[3600] == pytest.approx(900.0)
    blocks(900)  # a whole missing block
    with pytest.raises(ObservationError, match="Missing observations"):
        join_blocks([FIRST, SECOND])


def test_boundary_burst_gives_one_detection():
    # Three windows over two blocks (window 100, n 200); the same burst cut by the
    # outer windows and seen whole by the middle one.
    def box(x0, x1, score):
        return (x0, 0.2, x1, 0.4, score, 1)

    windows = [(0, [box(0.90, 1.0, 0.5)]), (50, [box(0.40, 0.60, 0.9)]), (100, [box(0.0, 0.10, 0.5)])]
    merged = burst_types.merge_windows(windows, 100, 200, iou=0.7)
    assert len(merged) == 1
    assert merged[0][0] == pytest.approx(0.45) and merged[0][2] == pytest.approx(0.55)


def test_endpoint_accepts_two_blocks_in_any_order(blocks):
    blocks(0.0)
    params = {"station": "MRO", "date": "2024-01-01", "freq_mhz": 80, "filenames": [SECOND, FIRST]}
    response = client.get("/api/lightcurve", params=params)
    assert response.status_code == 200
    body = response.json()
    assert body["filenames"] == [FIRST, SECOND]
    assert len(body["times"]) == 7200 and body["times"][-1] == "2024-01-01T12:29:59.750Z"
    params["filenames"] = [FIRST, SECOND, "MRO_20240101_123000_01.fit"]
    assert client.get("/api/lightcurve", params=params).status_code == 422
