"""Scientific processing and processed FITS export."""

import io

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


def test_decimation_limits_width_and_labels():
    data = np.arange(40, dtype=float).reshape(2, 20)
    labels = [str(i) for i in range(20)]
    result, result_labels = _decimate_time(data, labels, 5)
    assert result.shape == (2, 5)
    assert len(result_labels) == 5


def test_rfi_masks_persistent_hot_channel():
    rng = np.random.default_rng(1)
    data = rng.normal(0, 1, (16, 200))
    data[5, ::4] += 30
    _cleaned, channels, stats = _mitigate_rfi(data, z_thresh=4, occupancy_thresh=0.1, impulsive=False)
    assert 5 in channels
    assert stats["masked_fraction"] > 0


# Processed FITS export and provenance

def test_processed_fits_contains_provenance_and_both_axes(monkeypatch):
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
        station="MRO", date="2024-01-01", filename="MRO_20240101_120000.fit", rfi=False
    )
    with fits.open(io.BytesIO(response.body), checksum=True) as hdus:
        assert [hdu.name for hdu in hdus] == ["PRIMARY", "FREQUENCY_AXIS", "TIME_AXIS"]
        assert hdus[0].header["PROCVER"] == "AstroDoncel Studio 0.5.0"
        assert "background subtraction" in str(hdus[0].header["HISTORY"])
        assert hdus[1].data["FREQUENCY_MHZ"].tolist() == [40.0, 45.0, 50.0]
        assert hdus[2].data["TIME_OFFSET_S"].tolist() == [0.0, 1.0, 2.0, 3.0]
        assert hdus[2].data["TIME_UTC"][0] == "2024-01-01T12:00:00.000Z"
