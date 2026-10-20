"""Input contract of the burst-type detector, shared by training and inference.

The detector sees each FITS file as the portal shows it by default: relative
digits, robust background subtraction, no RFI filter and a 2-98 % intensity
clip. The image keeps the FITS channel order (high frequency on top) and spans
the whole file in time.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from backend.main import _percentile_clip_global, _subtract_background

IMAGE_WIDTH = 1024   # time; a 26 s type III spans about 30 px of a 900 s file
IMAGE_HEIGHT = 400   # frequency; receivers have 100-300 channels
CLASSES = ("type2", "type3", "type3s", "type4", "type5")


def spectrogram_image(data_raw: np.ndarray) -> np.ndarray:
    """Return the detector input for one FITS matrix (channels x samples) as uint8 (H, W)."""
    data = _subtract_background(np.asarray(data_raw, dtype=np.float32))
    vmin, vmax = _percentile_clip_global(data)
    scaled = np.clip((data - vmin) / max(vmax - vmin, 1e-9), 0.0, 1.0)
    scaled = np.nan_to_num(scaled, nan=0.0).astype(np.float32)
    resized = Image.fromarray(scaled, mode="F").resize((IMAGE_WIDTH, IMAGE_HEIGHT), Image.BILINEAR)
    return (np.asarray(resized) * 255.0).round().clip(0, 255).astype(np.uint8)


def box_to_physical(box: tuple[float, float, float, float], duration_s: float,
                    freqs_mhz: np.ndarray) -> dict[str, float]:
    """Convert a box in image fractions (x0, y0, x1, y1; y down) to seconds and MHz.

    Rows follow the FITS channel order, so a fraction maps to a channel index
    and the frequency is read from that channel, not interpolated linearly.
    """
    x0, y0, x1, y1 = box
    n = len(freqs_mhz)
    top = min(int(np.floor(y0 * n)), n - 1)
    bottom = min(max(int(np.ceil(y1 * n)) - 1, top), n - 1)
    channel_freqs = (float(freqs_mhz[top]), float(freqs_mhz[bottom]))
    return {
        "start_s": x0 * duration_s,
        "end_s": x1 * duration_s,
        "freq_low_mhz": min(channel_freqs),
        "freq_high_mhz": max(channel_freqs),
    }
