from __future__ import annotations

import numpy as np
import pytest

from backend.burst_types import box_to_physical, decode
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


def test_model_output_decodes_to_clipped_boxes_per_class():
    # Raw YOLO output: cx, cy, w, h and five class scores for four anchors.
    output = np.zeros((9, 4), np.float32)
    output[:4, 0] = [512, 100, 100, 200]   # type III, 0.9
    output[:4, 1] = [515, 108, 100, 200]   # same box, lower score: suppressed
    output[:4, 2] = [515, 108, 100, 200]   # same box, other class (IIIs): kept
    output[:4, 3] = [1000, 300, 100, 100]  # below the threshold
    output[5, :2], output[6, 2], output[4, 3] = [0.9, 0.8], 0.4, 0.2
    boxes = decode(output, conf=0.32, iou=0.7, pad=8)
    assert [(b[4], b[5]) for b in boxes] == [pytest.approx((0.9, 1)), pytest.approx((0.4, 2))]
    # The 8 px padding is removed and the box is clipped to the 400 px image.
    assert boxes[0][:4] == pytest.approx((462 / 1024, 0.0, 562 / 1024, 192 / 400))
