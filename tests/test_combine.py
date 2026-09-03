"""Regression cases for the 2026-09-03 Mexico/Siguenza combine reports."""

import gzip
import json
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from backend import main as core
from backend import worker
from backend.db import TaskRecord
from backend.security import fits_focus_code, validate_combine_filenames


def name(clock, receiver="62", extension="fit.gz"):
    suffix = f"_{receiver}" if receiver else ""
    return f"MEXICO-LANCE_20260903_{clock}{suffix}.{extension}"


@pytest.fixture
def combine(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "RESULT_DIR", str(tmp_path))
    monkeypatch.setattr(worker, "_update", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "_check_cancelled", lambda *_args: None)

    def run(starts, *, receivers=None, frequencies=None, missing=False, time_values=None):
        files = [name(start.strftime("%H%M%S"), (receivers or ["62"] * len(starts))[i]) for i, start in enumerate(starts)]
        datasets = {}
        for i, (filename, start) in enumerate(zip(files, starts, strict=True)):
            datasets[filename] = (
                np.full((2, 3600), i + 1.0),
                np.array((frequencies or [[80.0, 45.0]] * len(starts))[i]),
                np.arange(3600) * 0.25 if time_values is None else time_values,
                {"DATE-OBS": "2026/09/03", "TIME-OBS": start.strftime("%H:%M:%S.%f"), "CDELT1": 0.25},
            )
        monkeypatch.setattr(core, "_download_from_ethz", lambda _station, _date, filename: None if missing else filename)
        monkeypatch.setattr(core, "_load_raw_cached", lambda filename: datasets[filename])
        task = TaskRecord(id=str(uuid.uuid4()), payload={
            "station": "MEXICO-LANCE", "date": "2026-09-03", "options": {"filenames": files},
        })
        result = worker._combine_time(task)
        with gzip.open(tmp_path / result["artifact"], "rt") as handle:
            return result, json.load(handle)
    return run


def starts(clock="16:14:59.182", count=4):
    start = datetime.fromisoformat(f"2026-09-03T{clock}").replace(tzinfo=timezone.utc)
    return [start + timedelta(minutes=15 * i) for i in range(count)]


def test_four_blocks_cover_one_hour_with_exact_fits_times(combine):
    result, artifact = combine(starts())
    assert result["files"] == 4
    assert result["duration_seconds"] == pytest.approx(3600)
    assert artifact["focus_code"] == "62"
    assert len(artifact["time_axis"]) == 14400
    assert np.array(artifact["z"]).shape == (2, 14400)
    assert artifact["time_axis"][0] == "2026-09-03T16:14:59.182Z"
    assert artifact["time_axis"][-1] == "2026-09-03T17:14:58.932Z"
    assert artifact["time_axis"] == sorted(set(artifact["time_axis"]))


def test_small_recorder_overlap_is_trimmed_without_shifting_timestamps(combine):
    times = starts(count=2)
    times[1] -= timedelta(seconds=0.5)
    result, artifact = combine(times)
    assert result["overlap_samples_dropped"] == 2
    assert len(artifact["time_axis"]) == 7198
    assert artifact["time_axis"][3600] == "2026-09-03T16:29:59.182Z"
    assert artifact["time_axis"] == sorted(set(artifact["time_axis"]))


def test_gap_is_not_painted_as_a_continuous_observation(combine):
    times = starts(count=2)
    times[1] += timedelta(minutes=15)
    with pytest.raises(ValueError, match="Missing observations.*Spectral overview"):
        combine(times)


def test_large_overlap_is_rejected(combine):
    times = starts(count=2)
    times[1] -= timedelta(minutes=5)
    with pytest.raises(ValueError, match="Overlapping observations"):
        combine(times)


def test_non_increasing_time_axis_is_rejected(combine):
    with pytest.raises(ValueError, match="non-increasing time axis"):
        combine(starts(count=2), time_values=np.zeros(3600))


def test_small_clock_jitter_keeps_native_samples(combine):
    times = starts(count=2)
    times[1] += timedelta(seconds=0.2)
    result, artifact = combine(times)
    assert result["overlap_samples_dropped"] == 0
    assert len(artifact["time_axis"]) == 7200
    assert artifact["time_axis"][3600] == "2026-09-03T16:29:59.382Z"


def test_receiver_change_is_rejected_even_with_identical_frequency_axes(combine):
    with pytest.raises(ValueError, match="different receivers"):
        combine(starts(count=2), receivers=["62", "63"])


def test_configuration_change_has_actionable_error(combine):
    with pytest.raises(ValueError, match="Incompatible frequency axis.*configuration changed"):
        combine(starts(count=2), frequencies=[[80, 45], [79, 45]])


def test_download_failure_names_file_not_server_path(combine):
    with pytest.raises(ValueError, match="Could not retrieve MEXICO-LANCE.*retry"):
        combine(starts(count=2), missing=True)


def test_filename_validation_sorts_and_rejects_duplicate_copies():
    assert validate_combine_filenames([name("163000"), name("161500")], "MEXICO-LANCE", "2026-09-03") == [name("161500"), name("163000")]
    with pytest.raises(ValueError, match="unique observations"):
        validate_combine_filenames([name("161500"), name("161500", extension="fits")], "MEXICO-LANCE", "2026-09-03")


def test_no_focus_code_is_not_mistaken_for_observation_time():
    assert fits_focus_code(name("161500", receiver=None)) is None
    assert core._focus_code_from_filename(name("161500", receiver=None)) is None
    assert fits_focus_code(name("161500")) == "62"
