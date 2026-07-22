import io

import numpy as np
from astropy.io import fits

from backend import api_features
from backend import main as core


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
        assert hdus[0].header["PROCVER"] == "AstroDoncel 0.3.0"
        assert "background subtraction" in str(hdus[0].header["HISTORY"])
        assert hdus[1].data["FREQUENCY_MHZ"].tolist() == [40.0, 45.0, 50.0]
        assert hdus[2].data["TIME_OFFSET_S"].tolist() == [0.0, 1.0, 2.0, 3.0]
        assert hdus[2].data["TIME_UTC"][0] == "2024-01-01T12:00:00.000Z"
