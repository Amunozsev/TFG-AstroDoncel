"""Prune only downloaded FITS cache files using age and total-size limits."""

from __future__ import annotations

import argparse
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--max-gb", type=float, default=20.0)
    parser.add_argument("--max-age-days", type=int, default=90)
    parser.add_argument("--apply", action="store_true", help="Delete files; default is a dry run")
    args = parser.parse_args()
    root = args.data_dir.resolve()
    patterns = ("*.fit", "*.fits", "*.fit.gz", "*.fits.gz")
    files = sorted({path for pattern in patterns for path in root.glob(pattern)}, key=lambda path: path.stat().st_mtime)
    cutoff = time.time() - args.max_age_days * 86400
    total = sum(path.stat().st_size for path in files)
    limit = int(args.max_gb * 1024**3)
    victims: list[Path] = []
    for path in files:
        if path.stat().st_mtime < cutoff or total > limit:
            victims.append(path)
            total -= path.stat().st_size
    for path in victims:
        print(f"{'DELETE' if args.apply else 'WOULD DELETE'} {path}")
        if args.apply:
            path.unlink()
    print(f"Kept {len(files) - len(victims)} files ({total / 1024**3:.2f} GiB)")


if __name__ == "__main__":
    main()
