"""Join consecutive e-Callisto blocks of one receiver into a single observation.

A burst can straddle the end of one 15-minute file. The joined matrix keeps the
measured UTC time of every sample: boundary jitter is tolerated, duplicated
samples are dropped, and gaps or real overlaps are rejected, never bridged.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime

import numpy as np


class ObservationError(ValueError):
    """The requested blocks cannot form one continuous observation (path-free message)."""


@dataclass(frozen=True)
class Observation:
    data: np.ndarray            # raw channels x samples
    freqs: np.ndarray
    time_labels: list[str]      # real UTC of each sample
    offsets_s: np.ndarray       # seconds since the start of the first block
    start: datetime             # DATE-OBS/TIME-OBS of the first block
    headers: list               # FITS header of each block
    filenames: list[str]
    block_samples: list[int]    # samples each block contributed before trimming overlaps
    overlap_samples_dropped: int
    duration_s: float

    @property
    def header(self):
        return self.headers[0]


_CACHE: OrderedDict[tuple, tuple[list, Observation]] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 4


def _epoch(label: str) -> float:
    return datetime.fromisoformat(label.replace("Z", "+00:00")).timestamp()


def join_blocks(paths: list[str]) -> Observation:
    """Load the FITS files in ``paths`` (chronological order) and stitch them in time."""
    from backend import main as core

    entries = []
    for path in paths:
        try:
            entries.append(core._load_raw_cached(path))
        except Exception as exc:
            # Never return the local cache/NAS path in an error.
            raise ObservationError(
                f"Could not read FITS data in {os.path.basename(path)}. Check the source file and retry."
            ) from exc
    key = tuple(paths)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        # Reuse only while the raw-file cache still holds the very same arrays.
        if hit and len(hit[0]) == len(entries) and all(a is b for a, b in zip(hit[0], entries, strict=True)):
            _CACHE.move_to_end(key)
            return hit[1]
    observation = _stitch(entries, [os.path.basename(path) for path in paths])
    if len(paths) > 1:
        with _CACHE_LOCK:
            _CACHE[key] = (entries, observation)
            while len(_CACHE) > _CACHE_MAX:
                _CACHE.popitem(last=False)
    return observation


def _stitch(entries: list, names: list[str]) -> Observation:
    from backend import main as core

    start = core._observation_start(entries[0][3])
    if len(entries) == 1:
        raw, freqs, time_arr, header = entries[0]
        offsets = core._time_offsets_seconds(time_arr, header)
        step = float(np.median(np.diff(offsets))) if offsets.size > 1 else 0.0
        return Observation(raw, freqs, core._times_to_utc(time_arr, header), offsets, start,
                           [header], names, [offsets.size], 0, step * offsets.size)

    matrices, labels, offsets_parts, headers, block_samples = [], [], [], [], []
    reference_freqs = None
    previous_end = None
    previous_cadence = None
    overlap_samples_dropped = 0
    for name, (raw, freqs, time_arr, header) in zip(names, entries, strict=True):
        if reference_freqs is None:
            reference_freqs = np.asarray(freqs)
        elif len(freqs) != len(reference_freqs) or not np.allclose(freqs, reference_freqs, rtol=0, atol=1e-3):
            raise ObservationError(
                f"Incompatible frequency axis in {name}. The receiver configuration changed; "
                "choose another starting block or use Spectral overview to view separate groups."
            )
        block_labels = core._times_to_utc(time_arr, header)
        instants = np.array([_epoch(label) for label in block_labels])
        if raw.shape != (len(freqs), len(instants)) or len(instants) < 2 or not np.all(np.diff(instants) > 0):
            raise ObservationError(f"Invalid or non-increasing time axis in {name}; cannot build a continuous observation.")
        cadence = float(np.median(np.diff(instants)))
        # Offsets stay relative to the first block's start, not to each block's own.
        block_offsets = core._time_offsets_seconds(time_arr, header) + (core._observation_start(header) - start).total_seconds()
        if previous_end is not None:
            # Recorder boundaries can jitter by a second or two. Do not shift
            # measured UTC times, bridge missing blocks, or keep duplicate time.
            tolerance = max(2.0, 1.5 * max(cadence, previous_cadence))
            gap = float(instants[0] - (previous_end + previous_cadence))
            if gap > tolerance:
                raise ObservationError(
                    f"Missing observations before {name} (gap {gap:.1f} s). "
                    "Choose consecutive blocks or use Spectral overview to display gaps."
                )
            if gap < -tolerance:
                raise ObservationError(f"Overlapping observations in {name}. Select consecutive blocks from one receiver.")
            first = int(np.searchsorted(instants, previous_end, side="right"))
            if first == len(instants):
                raise ObservationError(f"No new time samples in {name}.")
            overlap_samples_dropped += first
            raw, block_labels, block_offsets = raw[:, first:], block_labels[first:], block_offsets[first:]
        block_samples.append(len(instants))
        previous_end, previous_cadence = instants[-1], cadence
        matrices.append(raw)
        labels.extend(block_labels)
        offsets_parts.append(block_offsets)
        headers.append(header)
    return Observation(
        np.concatenate(matrices, axis=1), reference_freqs, labels, np.concatenate(offsets_parts), start,
        headers, names, block_samples, overlap_samples_dropped,
        (previous_end + previous_cadence) - _epoch(labels[0]),
    )
