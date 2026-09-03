from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.prune_cache import CACHE_MARKER, apply_plan, plan_prune


def _fits(path: Path, *, size: int, mtime: float) -> Path:
    path.write_bytes(b"x" * size)
    os.utime(path, (mtime, mtime))
    return path


def test_plan_is_a_dry_run_and_ignores_non_fits(tmp_path: Path) -> None:
    old = _fits(tmp_path / "OLD.fit.gz", size=20, mtime=100)
    note = tmp_path / "keep.txt"
    note.write_text("not cache data", encoding="utf-8")

    plan = plan_prune(
        tmp_path,
        max_gb=100,
        max_age_days=1,
        min_idle_minutes=60,
        min_free_gb=0,
        now=200_000,
    )

    assert [item.path for item in plan.victims] == [old]
    assert old.exists()
    assert note.exists()


def test_apply_refuses_unmarked_directories(tmp_path: Path) -> None:
    old = _fits(tmp_path / "OLD.fit", size=10, mtime=100)
    plan = plan_prune(
        tmp_path,
        max_gb=0,
        max_age_days=0,
        min_idle_minutes=0,
        min_free_gb=0,
        now=200,
    )

    with pytest.raises(RuntimeError, match=CACHE_MARKER):
        apply_plan(plan)
    assert old.exists()


def test_apply_deletes_only_planned_fits_from_marked_cache(tmp_path: Path) -> None:
    (tmp_path / CACHE_MARKER).touch()
    old = _fits(tmp_path / "OLD.fits", size=10, mtime=100)
    recent = _fits(tmp_path / "RECENT.fit", size=10, mtime=199_900)
    note = tmp_path / "keep.txt"
    note.write_text("keep", encoding="utf-8")
    plan = plan_prune(
        tmp_path,
        max_gb=100,
        max_age_days=1,
        min_idle_minutes=60,
        min_free_gb=0,
        now=200_000,
    )

    deleted = apply_plan(plan)

    assert deleted == (old,)
    assert not old.exists()
    assert recent.exists()
    assert note.exists()


def test_apply_skips_a_file_changed_after_the_plan(tmp_path: Path) -> None:
    (tmp_path / CACHE_MARKER).touch()
    old = _fits(tmp_path / "OLD.fit", size=10, mtime=100)
    plan = plan_prune(
        tmp_path,
        max_gb=0,
        max_age_days=0,
        min_idle_minutes=0,
        min_free_gb=0,
        now=200,
    )
    old.write_bytes(b"changed")

    assert apply_plan(plan) == ()
    assert old.exists()
