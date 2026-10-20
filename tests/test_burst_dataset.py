from __future__ import annotations

import numpy as np
import pytest

from backend.burst_types import box_to_physical
from tools.burst_dataset import plot_box_to_fractions


def test_dataset_box_maps_to_seconds_and_channel_frequencies():
    # The whole plot area of an 800x600 dataset image is the whole file.
    assert plot_box_to_fractions([100, 72, 620, 408]) == (0.0, 0.0, 1.0, 1.0)

    # Second quarter of the time axis, upper half of the 200 channels.
    box = plot_box_to_fractions([255, 72, 155, 204])
    assert box == pytest.approx((0.25, 0.0, 0.5, 0.5))
    freqs = np.linspace(870.0, 45.0, 200)  # e-CALLISTO order: high frequency first
    physical = box_to_physical(box, 900.0, freqs)
    assert physical["start_s"] == pytest.approx(225.0)
    assert physical["end_s"] == pytest.approx(450.0)
    assert physical["freq_high_mhz"] == pytest.approx(870.0)
    assert physical["freq_low_mhz"] == pytest.approx(freqs[99])

    # Boxes are clipped to the plot; one entirely outside it is dropped.
    assert plot_box_to_fractions([50, 72, 100, 408])[0] == 0.0
    assert plot_box_to_fractions([0, 0, 90, 60]) is None
