"""Safely prune only downloaded FITS files from AstroDoncel's cache."""

from __future__ import annotations

import argparse
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

CACHE_MARKER = ".astrodoncel-cache"
FITS_PATTERNS = ("*.fit", "*.fits", "*.fit.gz", "*.fits.gz")


@dataclass(frozen=True)
class CacheFile:
    path: Path
    size: int
    mtime: float


@dataclass(frozen=True)
class PrunePlan:
    root: Path
    files: tuple[CacheFile, ...]
    victims: tuple[CacheFile, ...]
    bytes_before: int
    bytes_after: int
    free_before: int
    free_after: int


def _non_negative(name: str, value: float) -> float:
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value


def _cache_files(root: Path) -> tuple[CacheFile, ...]:
    discovered: set[Path] = set()
    for pattern in FITS_PATTERNS:
        discovered.update(path for path in root.glob(pattern) if path.is_file() and not path.is_symlink())
    files: list[CacheFile] = []
    for path in discovered:
        stat = path.stat()
        files.append(CacheFile(path=path, size=stat.st_size, mtime=stat.st_mtime))
    return tuple(sorted(files, key=lambda item: (item.mtime, item.path.name)))


def plan_prune(
    data_dir: Path,
    *,
    max_gb: float = 20.0,
    max_age_days: float = 90.0,
    min_idle_minutes: float = 60.0,
    min_free_gb: float = 5.0,
    now: float | None = None,
) -> PrunePlan:
    """Build a deterministic plan without changing the filesystem."""
    max_gb = _non_negative("max_gb", max_gb)
    max_age_days = _non_negative("max_age_days", max_age_days)
    min_idle_minutes = _non_negative("min_idle_minutes", min_idle_minutes)
    min_free_gb = _non_negative("min_free_gb", min_free_gb)
    root = data_dir.resolve()
    if not root.is_dir():
        raise ValueError(f"Cache directory does not exist: {root}")

    files = _cache_files(root)
    bytes_before = sum(item.size for item in files)
    free_before = shutil.disk_usage(root).free
    cache_limit = int(max_gb * 1024**3)
    required_free = int(min_free_gb * 1024**3)
    current_time = time.time() if now is None else now
    age_cutoff = current_time - max_age_days * 86400
    idle_cutoff = current_time - min_idle_minutes * 60

    selected: set[Path] = set()
    bytes_after = bytes_before
    free_after = free_before
    for item in files:
        old_enough = item.mtime <= idle_cutoff
        expired = max_age_days == 0 or item.mtime < age_cutoff
        over_cache_limit = bytes_after > cache_limit
        below_free_target = free_after < required_free
        if old_enough and (expired or over_cache_limit or below_free_target):
            selected.add(item.path)
            bytes_after -= item.size
            free_after += item.size

    victims = tuple(item for item in files if item.path in selected)
    return PrunePlan(
        root=root,
        files=files,
        victims=victims,
        bytes_before=bytes_before,
        bytes_after=bytes_after,
        free_before=free_before,
        free_after=free_after,
    )


def apply_plan(plan: PrunePlan) -> tuple[Path, ...]:
    """Apply a plan only to a directory explicitly marked as this cache."""
    if not (plan.root / CACHE_MARKER).is_file():
        raise RuntimeError(
            f"Refusing to delete: {plan.root} does not contain the {CACHE_MARKER} marker"
        )
    deleted: list[Path] = []
    for item in plan.victims:
        try:
            stat = item.path.stat()
        except FileNotFoundError:
            continue
        if item.path.is_symlink() or stat.st_size != item.size or stat.st_mtime != item.mtime:
            continue
        item.path.unlink()
        deleted.append(item.path)
    return tuple(deleted)


def print_plan(plan: PrunePlan, *, apply: bool) -> None:
    action = "DELETE" if apply else "WOULD DELETE"
    for item in plan.victims:
        print(f"{action} {item.path} ({item.size / 1024**2:.1f} MiB)")
    print(
        f"Cache: {len(plan.files)} files, {plan.bytes_before / 1024**3:.2f} GiB; "
        f"after plan: {len(plan.files) - len(plan.victims)} files, "
        f"{plan.bytes_after / 1024**3:.2f} GiB; "
        f"free space after plan: {plan.free_after / 1024**3:.2f} GiB"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--max-gb", type=float, default=20.0)
    parser.add_argument("--max-age-days", type=float, default=90.0)
    parser.add_argument("--min-idle-minutes", type=float, default=60.0)
    parser.add_argument("--min-free-gb", type=float, default=5.0)
    parser.add_argument("--apply", action="store_true", help="Delete files; default is a dry run")
    args = parser.parse_args()
    plan = plan_prune(
        args.data_dir,
        max_gb=args.max_gb,
        max_age_days=args.max_age_days,
        min_idle_minutes=args.min_idle_minutes,
        min_free_gb=args.min_free_gb,
    )
    print_plan(plan, apply=args.apply)
    if args.apply:
        deleted = apply_plan(plan)
        print(f"Deleted {len(deleted)} files")


if __name__ == "__main__":
    main()
