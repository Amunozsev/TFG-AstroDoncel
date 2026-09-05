"""Scientific processing and processed FITS export."""

import io
from datetime import datetime, timezone

import numpy as np
import pytest
from astropy.io import fits

from backend import api_features
from backend import main as core
from backend.main import (
    _decimate_time,
    _focus_code_from_filename,
    _mitigate_rfi,
    _percentile_clip_global,
    _subtract_background,
    _time_from_filename,
)


def test_filename_metadata_helpers():
    name = "SPAIN-SIGUENZA_20240101_123456_02.fit.gz"
    assert _time_from_filename(name) == "12:34:56"
    assert _focus_code_from_filename(name) == "02"


def test_background_subtraction_centres_channels():
    data = np.array([[10, 11, 12, 13], [100, 101, 102, 103]], dtype=float)
    result = _subtract_background(data)
    assert np.allclose(np.percentile(result, 25, axis=1), 0)


def test_percentile_clip_computes_both_bounds_and_validates_range():
    data = np.arange(101, dtype=np.float32)
    assert _percentile_clip_global(data, 10, 90) == pytest.approx((10, 90))
    with pytest.raises(ValueError, match="percentile bounds"):
        _percentile_clip_global(data, 90, 10)


def test_display_limits_remain_finite_for_invalid_channels():
    assert _percentile_clip_global(np.array([np.nan, np.inf, -np.inf])) == (0, 1)
    assert _percentile_clip_global(np.array([1, 2, 3, np.nan, np.inf]), 0, 100) == (1, 3)


def test_decimation_limits_width_and_labels():
    data = np.arange(40, dtype=float).reshape(2, 20)
    labels = [str(i) for i in range(20)]
    result, result_labels = _decimate_time(data, labels, 5)
    assert result.shape == (2, 5)
    assert len(result_labels) == 5


@pytest.mark.parametrize("columns,limit", [(21, 5), (2999, 1500), (3600, 1500)])
def test_decimation_preserves_all_samples_within_the_limit(columns, limit):
    raw = np.arange(columns, dtype=float)[None, :]
    reduced, labels = _decimate_time(raw, list(range(columns)), limit)
    assert reduced.shape[1] <= limit
    edges = labels + [columns]
    for index, (start, stop) in enumerate(zip(edges, edges[1:], strict=False)):
        assert reduced[0, index] == pytest.approx(raw[0, start:stop].mean())


def test_square_fits_preserves_native_frequency_time_orientation():
    raw = np.array([[1, 2], [3, 4]], dtype=float)
    hdus = fits.HDUList([
        fits.PrimaryHDU(raw),
        fits.BinTableHDU.from_columns([
            fits.Column(name="frequency", format="D", array=[80.0, 45.0]),
            fits.Column(name="time", format="D", array=[0.0, 0.25]),
        ]),
    ])
    loaded, freqs, times = core._load_callisto_data(hdus)
    np.testing.assert_array_equal(loaded, raw)
    np.testing.assert_array_equal(freqs, [80, 45])
    np.testing.assert_array_equal(times, [0, 0.25])


@pytest.mark.parametrize("header", [
    {"DATE-OBS": "2024-01-01T12:00:00+02:00"},
    {"DATE-OBS": "2024-01-01", "TIME-OBS": "12:00:00+02:00"},
])
def test_fits_timestamps_are_converted_to_utc(header):
    assert core._times_to_utc(np.array([0.0, 0.25]), header) == [
        "2024-01-01T10:00:00.000Z", "2024-01-01T10:00:00.250Z",
    ]
    assert core._parse_utc("2024-01-01T12:00:00+02:00") == datetime(2024, 1, 1, 10, tzinfo=timezone.utc)


def test_rfi_masks_persistent_hot_channel():
    rng = np.random.default_rng(1)
    data = rng.normal(0, 1, (16, 200))
    data[5, ::4] += 30
    _cleaned, channels, stats = _mitigate_rfi(data, z_thresh=4, occupancy_thresh=0.1, impulsive=False)
    assert 5 in channels
    assert stats["masked_fraction"] > 0


# Processed FITS export and provenance

@pytest.mark.parametrize("scale_mode", ["relative", "median_db"])
def test_processed_fits_contains_provenance_and_both_axes(monkeypatch, scale_mode):
    header = fits.Header({"DATE-OBS": "2024-01-01", "TIME-OBS": "12:00:00", "CDELT1": 1.0})
    raw = np.arange(12, dtype=float).reshape(3, 4)
    monkeypatch.setattr(api_features, "_resolve_file", lambda *_args: "synthetic.fit")
    monkeypatch.setattr(
        core,
        "_load_raw_cached",
        lambda _path: (raw, np.array([40.0, 45.0, 50.0]), np.arange(4, dtype=float), header),
    )
    monkeypatch.setattr(core, "_subtract_background", lambda data: data - 1.0)

    response = api_features.export_processed_fits(
        station="MRO", date="2024-01-01", filename="MRO_20240101_120000.fit", rfi=False, scale_mode=scale_mode,
    )
    with fits.open(io.BytesIO(response.body), checksum=True) as hdus:
        assert [hdu.name for hdu in hdus] == ["PRIMARY", "FREQUENCY_AXIS", "TIME_AXIS"]
        assert hdus[0].header["PROCVER"] == "AstroDoncel Studio 0.5.0"
        assert "background subtraction" in str(hdus[0].header["HISTORY"])
        factor = 2500 / 255 / 25.4 if scale_mode == "median_db" else 1
        np.testing.assert_allclose(hdus[0].data, raw * factor - 1)
        assert hdus[0].header["BUNIT"] == ("dB" if scale_mode == "median_db" else "relative detector digits")
        assert hdus[1].data["FREQUENCY_MHZ"].tolist() == [40.0, 45.0, 50.0]
        assert hdus[2].data["TIME_OFFSET_S"].tolist() == [0.0, 1.0, 2.0, 3.0]
        assert hdus[2].data["TIME_UTC"][0] == "2024-01-01T12:00:00.000Z"
